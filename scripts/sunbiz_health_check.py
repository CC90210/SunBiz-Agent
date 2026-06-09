#!/usr/bin/env python3
"""sunbiz_health_check.py — standing read-only auditor for the SunBiz backend.

Built 2026-06-09 after a shop-out batch nearly shipped a merchant's funding
documents to test/placeholder lender emails. The class of bug — an automation
silently resolving recipients/branding from bad data — is invisible until a
real send (or a lucky dry-run). This script makes that class VISIBLE on demand
or on a schedule, BEFORE anything goes out.

It NEVER mutates state. It reads Supabase + the cron registry and prints a
structured report. Exit code = number of HIGH-severity issues (0 = clean), so
it can gate a cron / alert.

Checks:
  A. Cron freshness   — every enabled tenant_cron_job ran within its cadence.
  B. Queue health     — error/failed rows + how long they've been stuck.
  C. Data quality     — active TEST/placeholder lenders, suspect lender
                        contacts + submission CCs, leads whose phone isn't
                        E.164 (every SMS step fails for those).
  D. Cross-tenant     — rows the known unscoped daemons (cold_outreach drain,
                        lender-response classifier) would process from OTHER
                        tenants, i.e. live blast radius of the fail-open paths.

Usage:
  python scripts/sunbiz_health_check.py                  # human report
  python scripts/sunbiz_health_check.py --json           # machine-readable
  python scripts/sunbiz_health_check.py --tenant-id <uuid>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

bootstrap_bravo_path()
from lib.secret_loader import load_env  # noqa: E402

SUNBIZ_TENANT_ID = "aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110"

# Personal / internal / disposable domains a real LENDER submission inbox
# should never be. A lender contact on one of these is almost certainly a
# test/placeholder row that will leak merchant documents.
_SUSPECT_EMAIL = re.compile(
    r"(@gmail\.|@yahoo\.|@hotmail\.|@outlook\.|@icloud\.|sunbizfunding\.com"
    r"|aisoluton|echelonx|example\.com|test@|@test\.)",
    re.I,
)


def _client():
    e = load_env()
    from supabase import create_client
    return create_client(e["BRAVO_SUPABASE_URL"], e["BRAVO_SUPABASE_SERVICE_ROLE_KEY"])


def _age_min(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        return round((now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 60, 1)
    except Exception:
        return None


def _cadence_limit_min(schedule: str) -> float | None:
    """Rough 'should have run within' bound for a cron schedule, in minutes.
    Returns None for schedules we can't reason about cheaply."""
    s = (schedule or "").strip()
    if s == "* * * * *":
        return 5
    m = re.match(r"^\*/(\d+) ", s)
    if m:
        return int(m.group(1)) * 3
    # fixed minute/hour daily (e.g. "30 6 * * *") — allow a day + 2h grace
    if re.match(r"^\d+ \d+ \* \* \*$", s):
        return 1440 + 120
    return None


def _is_e164(p) -> bool:
    return isinstance(p, str) and p.strip().startswith("+") and len(re.sub(r"\D", "", p)) >= 11


def run(tenant_id: str) -> dict:
    sb = _client()
    now = datetime.now(timezone.utc)
    issues: list[dict] = []

    def add(sev, code, msg, detail=None):
        issues.append({"severity": sev, "code": code, "message": msg, "detail": detail or {}})

    report: dict = {"tenant_id": tenant_id, "checked_at": now.isoformat(), "sections": {}}

    # ---- A. Cron freshness ----
    crons = sb.table("tenant_cron_jobs").select("name,schedule,enabled,last_run_at").eq("tenant_id", tenant_id).execute().data
    cron_rows = []
    for c in sorted(crons, key=lambda x: x["name"]):
        age = _age_min(c["last_run_at"], now)
        limit = _cadence_limit_min(c["schedule"])
        stale = bool(c["enabled"] and age is not None and limit is not None and age > limit)
        cron_rows.append({"name": c["name"], "schedule": c["schedule"], "enabled": c["enabled"], "age_min": age, "stale": stale})
        if stale:
            add("HIGH", "cron_stale", f"cron '{c['name']}' last ran {age}m ago (cadence {c['schedule']})")
    report["sections"]["crons"] = cron_rows

    # ---- B. Queue health ----
    q_rows = []
    for tbl, bad in (
        ("application_lender_threads", {"error"}),
        ("cold_outreach_campaigns", {"error"}),
        ("cold_outreach_recipients", {"error", "failed"}),
        ("sequence_state", {"failed"}),
    ):
        rows = None
        ts_col = None
        for cand in ("updated_at", "created_at", None):
            cols = "status" if cand is None else f"status,{cand}"
            try:
                rows = sb.table(tbl).select(cols).eq("tenant_id", tenant_id).execute().data
                ts_col = cand
                break
            except Exception:
                continue
        if rows is None:
            q_rows.append({"table": tbl, "error": "unreadable"})
            continue
        bd = dict(Counter(r.get("status") for r in rows))
        bad_rows = [r for r in rows if r.get("status") in bad]
        oldest = max((_age_min(r.get(ts_col), now) or 0 for r in bad_rows), default=0) if ts_col else 0
        q_rows.append({"table": tbl, "breakdown": bd, "bad_count": len(bad_rows), "oldest_bad_min": oldest})
        if bad_rows:
            add("MED", "queue_stuck", f"{tbl}: {len(bad_rows)} rows in {bad} (oldest {round(oldest/60,1)}h)")
    report["sections"]["queues"] = q_rows

    # ---- C. Data quality ----
    lenders = sb.table("tenant_records").select("id,data").eq("tenant_id", tenant_id).eq("entity_type", "lender").execute().data
    bad_lenders, missing_contact, bad_cc = [], [], []
    active_n = 0
    for r in lenders:
        d = r.get("data") or {}
        active = d.get("active", True)
        if active:
            active_n += 1
        name = d.get("name", "?")
        contact = d.get("contact")
        looks_test = isinstance(name, str) and name.strip().lower().startswith("test")
        if not contact:
            if active:
                missing_contact.append(name)
        elif active and (_SUSPECT_EMAIL.search(contact) or looks_test):
            bad_lenders.append({"name": name, "contact": contact})
        ccs = d.get("submission_cc_emails") or []
        if isinstance(ccs, str):
            ccs = [ccs]
        for cc in ccs:
            if cc and _SUSPECT_EMAIL.search(cc):
                bad_cc.append({"name": name, "cc": cc})
    if bad_lenders:
        add("HIGH", "test_lender_active", f"{len(bad_lenders)} ACTIVE lender(s) with test/personal contact — shop-out will send merchant docs to them", {"lenders": bad_lenders})
    if missing_contact:
        add("MED", "lender_no_contact", f"{len(missing_contact)} active lender(s) missing a contact email")
    if bad_cc:
        add("HIGH", "test_lender_cc", f"{len(bad_cc)} lender submission_cc_emails on personal/internal domains", {"cc": bad_cc})

    leads = sb.table("tenant_records").select("id,data").eq("tenant_id", tenant_id).eq("entity_type", "lead").execute().data
    have_phone = nonE164 = 0
    for r in leads:
        d = r.get("data") or {}
        p = d.get("phone") or d.get("phone_e164") or d.get("mobile")
        if p:
            have_phone += 1
            if not _is_e164(p):
                nonE164 += 1
    if nonE164:
        add("HIGH", "phone_not_e164", f"{nonE164}/{have_phone} leads have a phone that is NOT E.164 — every SMS sequence step fails for them")
    report["sections"]["data_quality"] = {
        "lenders_total": len(lenders), "lenders_active": active_n,
        "lenders_test_active": bad_lenders, "lenders_missing_contact": len(missing_contact),
        "leads_total": len(leads), "leads_with_phone": have_phone, "leads_phone_not_e164": nonE164,
    }

    # ---- D. Cross-tenant blast radius (fail-open daemons) ----
    try:
        allc = sb.table("cold_outreach_campaigns").select("tenant_id,status").execute().data
        foreign_camp = [r for r in allc if r.get("tenant_id") != tenant_id and r.get("status") in ("queued", "sending")]
        allt = sb.table("application_lender_threads").select("tenant_id,status").execute().data
        foreign_threads = [r for r in allt if r.get("tenant_id") != tenant_id and r.get("status") == "sent"]
        report["sections"]["cross_tenant"] = {
            "foreign_campaigns_drainable": len(foreign_camp),
            "foreign_sent_threads_classifiable": len(foreign_threads),
            "distinct_tenants_with_threads": len(set(r.get("tenant_id") for r in allt)),
        }
        if foreign_camp:
            add("HIGH", "xtenant_campaigns", f"{len(foreign_camp)} non-SunBiz campaigns drainable by the unscoped cold-outreach daemon (fail-open OASIS brand)")
        if foreign_threads:
            add("MED", "xtenant_threads", f"{len(foreign_threads)} non-SunBiz sent threads processable by the unscoped lender-response classifier")
    except Exception as ex:
        report["sections"]["cross_tenant"] = {"error": str(ex)[:80]}

    report["issues"] = issues
    report["summary"] = {
        "HIGH": sum(1 for i in issues if i["severity"] == "HIGH"),
        "MED": sum(1 for i in issues if i["severity"] == "MED"),
        "total": len(issues),
    }
    return report


def _print_human(rep: dict) -> None:
    s = rep["summary"]
    print("=" * 72)
    print(f"SUNBIZ HEALTH CHECK  ·  {rep['checked_at']}  ·  tenant {rep['tenant_id'][:8]}")
    print("=" * 72)
    print("\n[A] CRONS")
    for c in rep["sections"]["crons"]:
        flag = "  ⚠️ STALE" if c["stale"] else ""
        print(f"    {c['name']:<32} {c['schedule']:<12} en={str(c['enabled']):<5} last={c['age_min']}m{flag}")
    print("\n[B] QUEUES")
    for q in rep["sections"]["queues"]:
        if "error" in q and "breakdown" not in q:
            print(f"    {q['table']:<30} ERR {q['error']}")
        else:
            extra = f"  (bad={q['bad_count']}, oldest={round(q['oldest_bad_min']/60,1)}h)" if q["bad_count"] else ""
            print(f"    {q['table']:<30} {q['breakdown']}{extra}")
    dq = rep["sections"]["data_quality"]
    print("\n[C] DATA QUALITY")
    print(f"    lenders: {dq['lenders_total']} ({dq['lenders_active']} active) | test-active={len(dq['lenders_test_active'])} | missing-contact={dq['lenders_missing_contact']}")
    for l in dq["lenders_test_active"]:
        print(f"        ⚠️ {l['name']:<14} {l['contact']}")
    print(f"    leads: {dq['leads_total']} | with phone={dq['leads_with_phone']} | NOT E.164={dq['leads_phone_not_e164']}")
    ct = rep["sections"]["cross_tenant"]
    print("\n[D] CROSS-TENANT BLAST RADIUS")
    print(f"    {ct}")
    print("\n" + "=" * 72)
    print(f"SUMMARY: {s['HIGH']} HIGH · {s['MED']} MED · {s['total']} total")
    for i in rep["issues"]:
        print(f"    [{i['severity']}] {i['code']}: {i['message']}")
    print("=" * 72)


def _maybe_alert(rep: dict) -> bool:
    """On HIGH issues, raise an agent_alerts row (deduped over 6h) and send a
    Telegram message ONLY to a SunBiz-specific chat. Deliberately never falls
    back to the empire BRAVO_TELEGRAM_CHAT_ID — that fallback is itself a
    cross-tenant leak (audit finding F5). Returns True if it alerted."""
    high = rep["summary"]["HIGH"]
    if high == 0:
        return False
    tid = rep["tenant_id"]
    high_msgs = "; ".join(i["message"] for i in rep["issues"] if i["severity"] == "HIGH")
    sb = _client()
    since = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    try:
        recent = (sb.table("agent_alerts").select("id").eq("tenant_id", tid)
                  .eq("alert_type", "health_check").gte("created_at", since).limit(1).execute().data)
    except Exception:
        recent = []
    if not recent:
        try:
            sb.table("agent_alerts").insert({
                "tenant_id": tid, "alert_type": "health_check", "severity": "urgent",
                "subject_type": "tenant", "subject_id": tid,
                "title": f"Health check: {high} HIGH issue(s)",
                "payload": {"summary": rep["summary"], "issues": rep["issues"]},
            }).execute()
        except Exception as ex:
            print(f"[alert] agent_alerts insert failed: {ex}", file=sys.stderr)
    e = load_env()
    tok, chat = e.get("BRAVO_TELEGRAM_BOT_TOKEN"), e.get("SUNBIZ_TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            import requests
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": f"⚠️ SunBiz health: {high} HIGH\n{high_msgs}"}, timeout=10)
        except Exception as ex:
            print(f"[alert] telegram failed: {ex}", file=sys.stderr)
    else:
        print("[alert] no SunBiz Telegram chat configured (SUNBIZ_TELEGRAM_CHAT_ID); alert recorded in agent_alerts only", file=sys.stderr)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="SunBiz backend health auditor (read-only)")
    ap.add_argument("--tenant-id", default=SUNBIZ_TENANT_ID)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="raise agent_alerts + Telegram on HIGH issues")
    args = ap.parse_args()
    rep = run(args.tenant_id)
    if args.json:
        print(json.dumps(rep, default=str, indent=2))
    else:
        _print_human(rep)
    if args.alert:
        # Monitoring mode: detecting+alerting IS success, so exit 0 (don't
        # mark the cron run 'failed' just because issues were found).
        _maybe_alert(rep)
        return 0
    return rep["summary"]["HIGH"]


if __name__ == "__main__":
    sys.exit(main())
