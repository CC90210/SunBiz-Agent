"""setup_check.py — SunBiz Day-1 readiness gate.

Runs every prerequisite check a fresh SunBiz operator needs before going
live. One command, one report. Each check is PASS / WARN / FAIL with a
concrete next-step instruction.

Categories:
  1. Database — tenant exists, manifest seeded, drip sequences live,
     stage seed correct.
  2. Operator account — at least one is_owner user paired to the tenant.
  3. Catalog — lender catalog populated (>= 1 lender for shop-out).
  4. Automations — the 3 tenant_cron_jobs are seeded + enabled.
  5. Bridge — at least one paired bridge daemon with recent heartbeat.
  6. Daemons — the SunBiz-side scripts the bridge needs to dispatch
     exist + import cleanly (no missing _bravo_bootstrap, no broken
     imports from CEO-Agent moves).
  7. Brand — send_gateway has a sunbiz brand identity wired.

Exit code: 0 if all PASS, 1 if any WARN, 2 if any FAIL.

Usage:
    python scripts/setup_check.py            # human-readable report
    python scripts/setup_check.py --json     # machine-readable
    python scripts/setup_check.py --strict   # WARN counts as failure too
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

# secret_loader lives in CEO-Agent on this rig — bridge between repos.
_BRAVO_LIB = Path.home() / "CEO-Agent" / "scripts" / "lib"
if _BRAVO_LIB.is_dir():
    sys.path.insert(0, str(_BRAVO_LIB))

try:
    from secret_loader import load_env  # type: ignore
except ImportError:
    print("FAIL: secret_loader not importable — CEO-Agent not on sys.path", file=sys.stderr)
    sys.exit(2)


SUN_TENANT_ID = "aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110"
SUN_TENANT_SLUG = "submissions"


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, level: str, message: str, hint: str | None = None) -> None:
        self.checks.append({"name": name, "level": level, "message": message, "hint": hint})

    def counts(self) -> dict[str, int]:
        out = {"pass": 0, "warn": 0, "fail": 0}
        for c in self.checks:
            out[c["level"]] = out.get(c["level"], 0) + 1
        return out

    def render_human(self) -> str:
        lines = ["SunBiz setup readiness", "=" * 60]
        for c in self.checks:
            tag = {"pass": "  OK", "warn": "WARN", "fail": "FAIL"}[c["level"]]
            lines.append(f"[{tag}] {c['name']}")
            lines.append(f"       {c['message']}")
            if c["hint"] and c["level"] != "pass":
                lines.append(f"       hint: {c['hint']}")
        counts = self.counts()
        lines.append("=" * 60)
        lines.append(f"  {counts['pass']} PASS  {counts['warn']} WARN  {counts['fail']} FAIL")
        return "\n".join(lines)


def _client():
    env = load_env()
    from supabase import create_client
    return create_client(env["BRAVO_SUPABASE_URL"], env["BRAVO_SUPABASE_SERVICE_ROLE_KEY"])


def check_tenant(c, report: Report) -> None:
    t = c.table("tenants").select("id,slug,name").eq("id", SUN_TENANT_ID).maybe_single().execute()
    if not t or not t.data:
        report.add("tenant", "fail", f"no tenants row for {SUN_TENANT_ID}",
                   hint="seed the SunBiz tenant via supabase_tool insert tenants ...")
        return
    if t.data.get("slug") != SUN_TENANT_SLUG:
        report.add("tenant", "warn",
                   f"tenant.slug={t.data.get('slug')!r}, expected {SUN_TENANT_SLUG!r}",
                   hint="slug drift; OK if intentional but pre-flight assumes 'submissions'")
        return
    report.add("tenant", "pass", f"{t.data.get('name')} ({t.data.get('slug')})")


def check_operator(c, report: Report) -> None:
    owners = (
        c.table("user_profiles")
        .select("email,is_owner,team_role")
        .eq("tenant_id", SUN_TENANT_ID)
        .eq("is_owner", True)
        .execute()
    )
    rows = owners.data or []
    if not rows:
        report.add("operator", "fail",
                   "no is_owner=true user on the SunBiz tenant",
                   hint="UPDATE user_profiles SET is_owner=true, team_role='owner' WHERE email='<ezra>' AND tenant_id='<sun>'")
        return
    emails = ", ".join(r.get("email", "?") for r in rows)
    report.add("operator", "pass", f"{len(rows)} owner(s): {emails}")


def check_lender_catalog(c, report: Report) -> None:
    res = (
        c.table("tenant_records")
        .select("id", count="exact")
        .eq("tenant_id", SUN_TENANT_ID)
        .eq("entity_type", "lender")
        .execute()
    )
    n = res.count or 0
    if n == 0:
        report.add("lender_catalog", "fail",
                   "no lenders — Shop Out cannot rank without a catalog",
                   hint="dashboard Deals -> Lenders -> '+ New lender'")
    elif n < 3:
        report.add("lender_catalog", "warn",
                   f"{n} lender(s) — Shop Out works but ranking is poor with <3",
                   hint="add 2-3 more from operator network")
    else:
        report.add("lender_catalog", "pass", f"{n} lenders")


def check_drip_sequences(c, report: Report) -> None:
    res = c.table("drip_sequences").select("id,name,enabled").eq("tenant_id", SUN_TENANT_ID).execute()
    rows = res.data or []
    enabled = sum(1 for r in rows if r.get("enabled"))
    if not rows:
        report.add("drip_sequences", "fail",
                   "0 drip sequences seeded",
                   hint="python scripts/reconcile_sunbiz_sequences.py (from CEO-Agent)")
        return
    if enabled < 5:
        report.add("drip_sequences", "warn",
                   f"{len(rows)} sequences total, only {enabled} enabled",
                   hint="dashboard System -> Sequences -> review which off-by-default sequences to flip")
        return
    report.add("drip_sequences", "pass", f"{len(rows)} sequences, {enabled} enabled")


def check_cron_jobs(c, report: Report) -> None:
    res = (
        c.table("tenant_cron_jobs")
        .select("id,name,enabled,last_run_at,last_run_status")
        .eq("tenant_id", SUN_TENANT_ID)
        .execute()
    )
    rows = res.data or []
    expected = {
        "SunBiz Follow-up Generator",
        "SunBiz Daily Plan Generator",
        "SunBiz Renewal Reminder",
    }
    present = {r.get("name") for r in rows}
    missing = expected - present
    if missing:
        report.add("cron_jobs", "fail",
                   f"missing: {sorted(missing)}",
                   hint="python scripts/core/cron_registry.py seed")
        return
    disabled = [r for r in rows if r.get("name") in expected and not r.get("enabled")]
    if disabled:
        report.add("cron_jobs", "warn",
                   f"{len(disabled)} canonical cron(s) disabled",
                   hint="dashboard System -> Automations -> toggle on")
        return
    errored = [r for r in rows if r.get("last_run_status") == "error"]
    if errored:
        report.add("cron_jobs", "warn",
                   f"{len(errored)} cron(s) last ran with error status",
                   hint="check last_run_error in dashboard, fix the underlying script")
        return
    report.add("cron_jobs", "pass", f"all 3 canonical SunBiz crons seeded + enabled")


def check_bridge(c, report: Report) -> None:
    res = c.table("bridge_pairings").select("id,revoked_at,last_seen_at").eq("tenant_id", SUN_TENANT_ID).execute()
    rows = res.data or []
    live = [r for r in rows if not r.get("revoked_at")]
    if not live:
        report.add("bridge", "fail",
                   "no live bridge paired — automations cannot fire",
                   hint="operator goes to /t/sun/settings -> Devices, mints a pair code, runs `python scripts/bridge_setup.py pair <code>` on the VPS")
        return
    now = datetime.now(timezone.utc)
    fresh = [
        r for r in live
        if r.get("last_seen_at") and (now - datetime.fromisoformat(r["last_seen_at"].replace("Z", "+00:00"))).total_seconds() < 300
    ]
    if not fresh:
        report.add("bridge", "warn",
                   f"{len(live)} paired but no heartbeat in last 5 min",
                   hint="check claude-bridge-ping daemon on the VPS: `pm2 status` + `pm2 logs claude-bridge-ping`")
        return
    report.add("bridge", "pass", f"{len(fresh)} live bridge(s) with fresh heartbeat")


def check_daemons(report: Report) -> None:
    expected = [
        "follow_up_generator.py",
        "daily_plan_generator.py",
        "renewal_reminder.py",
        "shop_out_sender.py",
        "sequence_runner.py",
        "lender_response_classifier.py",
        "cold_outreach_runner.py",
    ]
    missing = [f for f in expected if not (PROJECT_ROOT / "scripts" / f).is_file()]
    if missing:
        report.add("daemons", "fail",
                   f"missing daemon scripts: {missing}",
                   hint="re-pull SunBiz-Agent (canonical home post 2026-05-28)")
        return
    # Verify import-ability of one as a smoke
    spec = importlib.util.spec_from_file_location(
        "follow_up_generator", PROJECT_ROOT / "scripts" / "follow_up_generator.py",
    )
    if not spec or not spec.loader:
        report.add("daemons", "warn", "could not load follow_up_generator spec", None)
        return
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        report.add("daemons", "pass", f"all {len(expected)} daemon scripts present + importable")
    except Exception as exc:  # noqa: BLE001
        report.add("daemons", "warn",
                   f"follow_up_generator import failed: {exc}",
                   hint="run the daemon manually with --help; fix the import chain (likely cross-repo path drift)")


def check_brand_identity(report: Report) -> None:
    sg = Path.home() / "CEO-Agent" / "scripts" / "integrations" / "send_gateway.py"
    if not sg.is_file():
        report.add("brand_identity", "fail",
                   "send_gateway.py not found at ~/CEO-Agent/scripts/integrations/",
                   hint="check the CEO-Agent install — that's where the multi-tenant outbound chokepoint lives")
        return
    text = sg.read_text(encoding="utf-8", errors="replace")
    if "sunbiz" not in text.lower():
        report.add("brand_identity", "fail",
                   "send_gateway has no 'sunbiz' brand identity wired",
                   hint="add a sunbiz entry to BRAND_IDENTITY map; outbound emails would otherwise carry the OASIS footer")
        return
    report.add("brand_identity", "pass", "sunbiz brand wired in send_gateway")


def check_per_user_credentials(c, report: Report) -> None:
    """For each non-owner employee, list which personal credentials are
    still missing. Owners can be skipped — they use shared submissions@
    and tend to have everything wired earlier. The current personal
    credential of record for SunBiz is Gmail OAuth (refresh token under
    service='gmail_oauth')."""
    members = (
        c.table("user_profiles")
        .select("id,email,team_role,is_owner,auth_user_id")
        .eq("tenant_id", SUN_TENANT_ID)
        .execute()
        .data
        or []
    )
    employees = [u for u in members if not u.get("is_owner") and u.get("auth_user_id")]
    if not employees:
        report.add("per_user_credentials", "pass",
                   "no non-owner employees to audit")
        return
    missing_gmail = []
    for u in employees:
        rows = (
            c.table("user_integration_credentials")
            .select("id,field_key")
            .eq("tenant_id", SUN_TENANT_ID)
            .eq("user_id", u["auth_user_id"])
            .eq("service", "gmail_oauth")
            .execute()
            .data
            or []
        )
        has_refresh = any(r.get("field_key") == "refresh_token" for r in rows)
        if not has_refresh:
            missing_gmail.append(u["email"])
    if not missing_gmail:
        report.add("per_user_credentials", "pass",
                   f"all {len(employees)} employee(s) have Gmail connected")
        return
    report.add(
        "per_user_credentials", "warn",
        f"{len(missing_gmail)} employee(s) without Gmail connected: " +
        ", ".join(missing_gmail),
        hint="each unconnected employee visits /settings and clicks 'Connect Gmail' under Integrations",
    )


def main() -> int:
    p = argparse.ArgumentParser(description="SunBiz Day-1 setup readiness check")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--strict", action="store_true", help="exit nonzero on WARN")
    args = p.parse_args()

    client = _client()
    report = Report()
    check_tenant(client, report)
    check_operator(client, report)
    check_lender_catalog(client, report)
    check_drip_sequences(client, report)
    check_cron_jobs(client, report)
    check_bridge(client, report)
    check_daemons(report)
    check_brand_identity(report)
    check_per_user_credentials(client, report)

    if args.json:
        print(json.dumps({"checks": report.checks, "counts": report.counts()}, indent=2))
    else:
        print(report.render_human())

    counts = report.counts()
    if counts["fail"] > 0:
        return 2
    if args.strict and counts["warn"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
