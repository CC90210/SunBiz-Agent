"""uw_lead_enricher.py - keep approved Breeze UW leads complete.

The scrubber stages per-deal UW Sheets for Ezra. After Ezra approves a deal,
the lead exists in tenant_records and the sequence runner can fire. This worker
handles the gap discovered on 2026-07-02:

1. Re-read the original Google Sheet for approved uw_sheet leads and fill any
   missing owner/business fields with the current parser output.
2. If the sheet still lacks email/phone, try external contact enrichment via
   Firecrawl search and TruePeopleSearch through the shared research_fetch
   ladder.
3. Notify Ezra when a usable contact channel is newly found, and revive only
   sequence_state rows that failed because that channel was missing.

It never overwrites an existing value and never sends merchant outreach itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _bravo_bootstrap import bootstrap_bravo_path, load_bravo_env  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()

from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402
from import_mca_leads import normalize_email, normalize_phone  # noqa: E402
from mca_lead_scrubber import SHEET_OWNER, SHEET_TITLE_HINT, build_lead_data  # noqa: E402
from scrubber import ingest, scoring, uw_scoring  # noqa: E402
from scrubber import tps_match  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CLAIM_PATH = REPO_ROOT / "state" / "uw_lead_enricher.claim"
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})[\s.\-]?\d{3}[\s.\-]?\d{4}\b")
BAD_EMAIL_PREFIXES = {"abuse", "admin", "billing", "help", "hello", "info", "legal", "no-reply", "noreply", "privacy", "support"}
REQUIRED_SHEET_FIELDS = (
    "dba",
    "entity_type",
    "ein",
    "owner_name",
    "owner_ssn_last4",
    "business_address",
    "business_city",
    "business_zip",
    "owner_address_line1",
    "owner_address_city",
    "owner_address_state",
    "owner_address_zip",
    "business_start_date",
    "time_in_business",
    "mca_positions",
    "leverage_ratio",
)


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[uw-enricher {ts}] {msg}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_env() -> dict[str, str]:
    """Secrets from .env.agents, loaded by file path so SunBiz-Agent's own
    `scripts/lib/` package can't shadow CEO-Agent's lib.secret_loader — see
    _bravo_bootstrap.load_bravo_env. The previous `from lib.secret_loader import
    load_env` failed for exactly that reason and left this daemon depending on
    inherited process env."""
    return load_bravo_env()


def _client(env: dict[str, str]):
    url = (env.get("BRAVO_SUPABASE_URL") or env.get("SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        print("[uw-enricher] BRAVO_SUPABASE_URL / SERVICE_ROLE_KEY missing", file=sys.stderr)
        return None
    try:
        from supabase import create_client  # type: ignore
        return create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        print(f"[uw-enricher] supabase client error: {exc}", file=sys.stderr)
        return None


def _missing(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _has_email(data: dict[str, Any]) -> bool:
    return bool(normalize_email(data.get("email") or data.get("contact_email")))


def _has_phone(data: dict[str, Any]) -> bool:
    return bool(normalize_phone(data.get("phone") or data.get("contact_phone")))


def _needs_sheet_refresh(data: dict[str, Any]) -> bool:
    if not data.get("source_file_id"):
        return False
    return any(_missing(data.get(k)) for k in REQUIRED_SHEET_FIELDS)


def _is_uw_lead(data: dict[str, Any]) -> bool:
    return (
        data.get("source") == "breeze_uw_sheet"
        or data.get("stage") == "uw_sheet"
        or bool(data.get("source_file_id"))
    )


def _merge_fill_only(target: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for key, value in incoming.items():
        if _missing(value):
            continue
        if _missing(target.get(key)):
            target[key] = value
            changed.append(key)
    return changed


def _file_ref(env: dict[str, str], file_id: str, fallback_name: str = "") -> dict[str, Any]:
    svc = ingest.drive_service(env)
    meta = (
        svc.files()
        .get(
            fileId=file_id,
            fields="id,name,mimeType,modifiedTime",
            supportsAllDrives=True,
        )
        .execute()
    )
    return {
        "id": meta.get("id") or file_id,
        "name": meta.get("name") or fallback_name or file_id,
        "mime_type": meta.get("mimeType") or ingest.SHEET_MIME,
        "modified_time": meta.get("modifiedTime"),
    }


def _refresh_from_source_sheet(env: dict[str, str], data: dict[str, Any]) -> tuple[dict[str, Any], list[str], Optional[str]]:
    source_file_id = (data.get("source_file_id") or "").strip()
    if not source_file_id:
        return {}, [], "missing source_file_id"
    try:
        from scrubber import uw_sheet_parser as parser

        ref = _file_ref(env, source_file_id, data.get("source_file") or "")
        wb = ingest.fetch_workbook(env, ref)
        parsed = parser.parse_uw_sheet(wb)
        cfg = scoring.load_config()
        result = uw_scoring.score_uw_deal(parsed, cfg)
        fresh = build_lead_data(parsed, result, ref, cfg)
        return fresh, [], None
    except Exception as exc:  # noqa: BLE001
        return {}, [], str(exc)[:300]


def _flatten_text(value: Any, limit: int = 30000) -> str:
    parts: list[str] = []

    def walk(v: Any) -> None:
        if sum(len(p) for p in parts) >= limit:
            return
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for vv in v.values():
                walk(vv)
        elif isinstance(v, list):
            for vv in v:
                walk(vv)

    walk(value)
    return "\n".join(parts)[:limit]


def _confidence(text: str, data: dict[str, Any], source_kind: str) -> str:
    t = text.lower()
    business = str(data.get("business_name") or data.get("company") or "").lower()
    owner = str(data.get("owner_name") or data.get("contact_name") or data.get("name") or "").lower()
    city = str(data.get("business_city") or data.get("owner_address_city") or data.get("city") or "").lower()
    business_hit = bool(business and business in t)
    owner_hit = bool(owner and owner in t)
    city_hit = bool(city and city in t)
    if source_kind == "firecrawl" and business_hit:
        return "HIGH"
    if source_kind == "truepeoplesearch" and owner_hit and city_hit:
        return "MEDIUM"
    if business_hit or owner_hit:
        return "MEDIUM"
    return "LOW"


def _valid_email(email: str) -> Optional[str]:
    normalized = normalize_email(email)
    if not normalized:
        return None
    local, _, domain = normalized.partition("@")
    if local.lower() in BAD_EMAIL_PREFIXES:
        return None
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return None
    return normalized


def _extract_contacts(text: str, source_url: str, source_kind: str, data: dict[str, Any]) -> dict[str, Any]:
    conf = _confidence(text, data, source_kind)
    emails: list[str] = []
    phones: list[str] = []
    for m in EMAIL_RE.finditer(text):
        e = _valid_email(m.group(0))
        if e and e not in emails:
            emails.append(e)
    for m in PHONE_RE.finditer(text):
        p = normalize_phone(m.group(0))
        if p and p not in phones:
            phones.append(p)
    out: dict[str, Any] = {}
    if emails:
        out["email"] = emails[0]
        out["email_source"] = source_url
        out["email_confidence"] = conf
    if phones:
        out["phone"] = phones[0]
        out["phone_source"] = source_url
        out["phone_confidence"] = conf
    return out


def _run_json(argv: list[str], timeout: int) -> dict[str, Any]:
    try:
        res = subprocess.run(
            argv,
            cwd=str(BRAVO_ROOT or REPO_ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if res.returncode != 0:
        return {"ok": False, "error": (res.stderr or res.stdout)[-800:]}
    try:
        data = json.loads(res.stdout)
        if isinstance(data, dict):
            data.setdefault("ok", True)
            return data
        return {"ok": True, "data": data}
    except json.JSONDecodeError:
        return {"ok": False, "error": "non-json output", "stdout": res.stdout[-800:]}


def _firecrawl_search(data: dict[str, Any]) -> list[dict[str, Any]]:
    if not BRAVO_ROOT:
        return []
    city_state = " ".join(
        p for p in (
            data.get("business_city") or data.get("owner_address_city") or data.get("city"),
            data.get("business_state") or data.get("owner_address_state") or data.get("state"),
        )
        if p
    )
    query = " ".join(
        p for p in (
            data.get("business_name") or data.get("company"),
            data.get("dba"),
            data.get("owner_name") or data.get("contact_name"),
            city_state,
            "email phone",
        )
        if p
    )
    if not query:
        return []
    script = Path(BRAVO_ROOT) / "scripts" / "integrations" / "firecrawl_tool.py"
    raw = _run_json([sys.executable, str(script), "search", query, "--json"], timeout=45)
    items = raw.get("data") or raw.get("results") or raw.get("web") or []
    if isinstance(items, dict):
        items = items.get("data") or items.get("results") or []
    out: list[dict[str, Any]] = []
    for item in (items or [])[:8]:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("sourceURL") or item.get("link") or "firecrawl-search"
        text = "\n".join(
            str(item.get(k) or "") for k in ("title", "description", "markdown", "content", "text")
        )
        found = _extract_contacts(text, url, "firecrawl", data)
        if found:
            out.append(found)
    return out


def _truepeople_search(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Look the owner up by name + address and return the contact for THAT
    person — or nothing.

    Previously this handed the whole results page to _extract_contacts(), which
    regexes every phone on it and keeps the first. A people-search query for a
    common name returns many individuals, so on any multi-result page that was
    a STRANGER's number, labelled MEDIUM because _confidence() only checks that
    the owner name and city appear somewhere on the page — which is guaranteed,
    since those are the query terms echoed back.

    Now the page is split into per-person records and exactly one is selected
    (scrubber.tps_match): unique name match, else disambiguated by date of
    birth, else by address when no DOB is on file, else NO number and a
    manual-review flag. We never guess between people — a wrong number on a
    merchant's file is worse than an empty field.
    """
    if not BRAVO_ROOT:
        return None
    merchant = tps_match.merchant_from_lead(data)
    owner, city, state = merchant["name"], merchant["city"], merchant["state"]
    if not owner or not (city or state):
        return None
    text, source = _fetch_truepeople(merchant)
    if text is None:
        return None
    return _select_tps_contact(text, source, data, merchant)


def _truepeople_url(merchant: dict[str, Any]) -> str:
    city_state = " ".join(
        str(merchant[k]) for k in ("city", "state") if str(merchant.get(k) or "").strip()
    )
    return (
        "https://www.truepeoplesearch.com/results"
        f"?name={quote_plus(str(merchant.get('name') or ''))}"
        f"&citystatezip={quote_plus(city_state)}"
    )


def _fetch_truepeople(merchant: dict[str, Any], timeout: int = 75) -> tuple[Optional[str], str]:
    """(page_text, source_url); text is None when the fetch failed. Split out so
    scrubber.phone_providers can reuse the exact fetch the daemon uses."""
    url = _truepeople_url(merchant)
    if not BRAVO_ROOT:
        return None, url
    script = Path(BRAVO_ROOT) / "scripts" / "research_fetch.py"
    raw = _run_json([sys.executable, str(script), url, "--json", "--min-chars", "200"], timeout=timeout)
    if not raw.get("ok"):
        return None, url
    return (raw.get("text") or ""), (raw.get("final_url") or url)


def _fetch_truepeople_text(merchant: dict[str, Any]) -> Optional[str]:
    """Text-only convenience wrapper for the provider registry."""
    return _fetch_truepeople(merchant)[0]


def _select_tps_contact(
    text: str,
    source: str,
    data: dict[str, Any],
    merchant: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Record-scoped selection over a people-search page. Split out from the
    fetch so it can be unit-tested against fixtures and exercised offline by
    scripts/tps_probe.py --parse-only (the live fetch is captcha-blocked)."""
    merchant = merchant or tps_match.merchant_from_lead(data)
    records = tps_match.parse_records(text)
    result = tps_match.select_record(records, merchant)
    _log(
        f"  tps: {result.outcome} ({result.reason}) "
        f"[records={result.considered} name_matches={result.name_matched}]"
    )

    # Everything a human needs to finish the job by hand in CLEAR, without
    # re-deriving it from the lead: the exact search terms we used, and the
    # people we found but could NOT confirm.
    base: dict[str, Any] = {
        "phone_lookup_outcome": result.outcome,
        "phone_lookup_reason": result.reason,
        "phone_lookup_source": source,
        "phone_lookup_checked_at": _now_iso(),
        "phone_lookup_query": _lookup_query(merchant),
    }
    candidates = _candidate_phones(records, merchant, exclude=result.record)
    if candidates:
        base["phone_lookup_candidates"] = candidates

    if not result.resolved or not result.phone:
        # Surface WHY there's no number so the daemon stops reporting an opaque
        # contact_found: 0, and so genuinely ambiguous merchants can be routed
        # to a human (or a credentialed provider) rather than silently dropped.
        if result.needs_manual_review:
            base["phone_lookup_status"] = "manual_review"
        else:
            base["phone_lookup_status"] = "not_found"
        return base

    # normalize_phone() is the house E.164 normalizer — SMS/dialers depend on it.
    phone = normalize_phone(result.phone) or result.phone
    email = _first_email(result.record.raw if result.record else "")
    out = {
        **base,
        "phone": phone,
        "phone_source": source,
        "phone_confidence": result.confidence,
        "phone_lookup_status": "found",
        "phone_lookup_matched_name": result.record.name if result.record else None,
    }
    if email:
        out.update({"email": email, "email_source": source, "email_confidence": result.confidence})
    return {k: v for k, v in out.items() if v is not None}


def _lookup_query(merchant: dict[str, Any]) -> str:
    """The search terms, as a single pasteable line for CLEAR / manual lookup."""
    name = str(merchant.get("name") or "").strip()
    where = ", ".join(
        str(merchant.get(k)).strip()
        for k in ("city", "state")
        if str(merchant.get(k) or "").strip()
    )
    bits = [b for b in (name, where) if b]
    dob = str(merchant.get("dob") or "").strip()
    if dob:
        bits.append(f"DOB {dob}")
    else:
        bits.append("DOB unknown")
    return " | ".join(bits)


def _candidate_phones(
    records: list[Any],
    merchant: dict[str, Any],
    exclude: Any = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """The same-name people we could NOT confirm, so an operator can eyeball them
    instead of starting from scratch. Shaped like MCAProfilePanel's MultiPhone
    ({number, type, ...}) so the dashboard renders them with no new component.

    Only name-matching records are included — unrelated people on the page are
    noise, and shipping them would put strangers' numbers on a merchant's file
    for no reason."""
    name = str(merchant.get("name") or "")
    out: list[dict[str, Any]] = []
    for r in records:
        if exclude is not None and r is exclude:
            continue
        if not tps_match.name_matches(getattr(r, "name", ""), name):
            continue
        for number in (getattr(r, "phones", None) or [])[:2]:
            out.append({
                "number": normalize_phone(number) or number,
                "type": "Unconfirmed",
                "name": r.name,
                "age": r.age,
                "city": r.city or None,
                "state": r.state or None,
            })
            if len(out) >= limit:
                return out
    return out


def _first_email(block: str) -> Optional[str]:
    """First usable email within ONE person's record block (not the whole page)."""
    for m in EMAIL_RE.finditer(block or ""):
        e = _valid_email(m.group(0))
        if e:
            return e
    return None


def _best_contact(candidates: list[dict[str, Any]], key: str) -> Optional[dict[str, Any]]:
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    usable = [
        c for c in candidates
        if c.get(key) and str(c.get(f"{key}_confidence") or "LOW").upper() in ("HIGH", "MEDIUM")
    ]
    if not usable:
        return None
    conf_key = f"{key}_confidence"
    return sorted(usable, key=lambda c: order.get(str(c.get(conf_key) or "LOW"), 9))[0]


def _mask_email(v: Any) -> str:
    email = normalize_email(v)
    if not email:
        return "(none)"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _mask_phone(v: Any) -> str:
    phone = normalize_phone(v)
    if not phone:
        return "(none)"
    return f"{phone[:-4]}****"


def _contact_preview(data: dict[str, Any], changed_keys: list[str]) -> str:
    parts: list[str] = []
    if "email" in changed_keys:
        parts.append(
            "email="
            + _mask_email(data.get("email"))
            + f" conf={data.get('email_confidence', 'LOW')} src={data.get('email_source', 'unknown')}"
        )
    if "phone" in changed_keys:
        parts.append(
            "phone="
            + _mask_phone(data.get("phone"))
            + f" conf={data.get('phone_confidence', 'LOW')} src={data.get('phone_source', 'unknown')}"
        )
    return " | ".join(parts)


def _enrich_contact(data: dict[str, Any], skip_web: bool = False) -> tuple[dict[str, Any], list[str]]:
    if skip_web or (_has_email(data) and _has_phone(data)):
        return {}, []
    candidates: list[dict[str, Any]] = []
    candidates.extend(_firecrawl_search(data))
    if not any(c.get("phone") for c in candidates):
        tp = _truepeople_search(data)
        if tp:
            candidates.append(tp)

    incoming: dict[str, Any] = {}
    changed: list[str] = []
    if not _has_email(data):
        c = _best_contact(candidates, "email")
        if c:
            incoming.update({k: c[k] for k in ("email", "email_source", "email_confidence") if c.get(k)})
    if not _has_phone(data):
        c = _best_contact(candidates, "phone")
        if c:
            incoming.update({k: c[k] for k in ("phone", "phone_source", "phone_confidence") if c.get(k)})
        # Carry the people-search verdict onto the lead even when NO number was
        # usable — "3 people share this name and we have no DOB" is actionable
        # (route to manual review / a credentialed provider), whereas a silent
        # absence is not. Last writer wins; only one TPS candidate is produced.
        for cand in candidates:
            for k in ("phone_lookup_outcome", "phone_lookup_reason", "phone_lookup_status",
                      "phone_lookup_source", "phone_lookup_checked_at"):
                if cand.get(k):
                    incoming[k] = cand[k]

    if incoming:
        incoming["enriched_at"] = _now_iso()
        if incoming.get("email") or _has_email(data):
            incoming["enrich_status"] = "done"
        elif incoming.get("phone") or _has_phone(data):
            incoming["enrich_status"] = "call_only"
        else:
            incoming["enrich_status"] = "none"
        for k in ("email", "phone"):
            if incoming.get(k):
                changed.append(k)
    else:
        incoming["enriched_at"] = _now_iso()
        incoming["enrich_status"] = "none"
        if candidates:
            incoming["enrich_notes"] = "low_confidence_candidates_suppressed"
    return incoming, changed


def _publish_status_event(sb, lead_id: str, data: dict[str, Any]) -> None:
    sb.table("agent_events").insert({
        "event_type": "BRAVO_RECORD_STATUS_CHANGED",
        "publisher_agent": "uw-lead-enricher",
        "source_agent": "uw-lead-enricher",
        "severity": "info",
        "payload": {
            "entity": "lead",
            "record_id": lead_id,
            "field": "stage",
            "from": data.get("stage") or "uw_sheet",
            "to": data.get("stage") or "uw_sheet",
            "data": data,
            "tenant_id": SUNBIZ_TENANT_ID,
            "triggering_event": "uw_lead_enriched",
        },
        "correlation_id": SUNBIZ_TENANT_ID,
    }).execute()


def _revive_missing_contact_steps(sb, lead_id: str, data: dict[str, Any]) -> int:
    if not (_has_email(data) or _has_phone(data)):
        return 0
    try:
        rows = (
            sb.table("sequence_state")
            .select("id,last_error")
            .eq("tenant_id", SUNBIZ_TENANT_ID)
            .eq("lead_id", lead_id)
            .eq("status", "failed")
            .limit(50)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        _log(f"sequence revive read failed lead={lead_id}: {exc}")
        return 0
    revived = 0
    for row in rows:
        err = str(row.get("last_error") or "").lower()
        can_fix = ("no email" in err and _has_email(data)) or ("no phone" in err and _has_phone(data))
        if not can_fix:
            continue
        try:
            sb.table("sequence_state").update({
                "status": "scheduled",
                "attempt_count": 0,
                "last_error": None,
                "claimed_at": None,
                "claimed_by": None,
                "scheduled_for": _now_iso(),
            }).eq("id", row["id"]).execute()
            revived += 1
        except Exception as exc:  # noqa: BLE001
            _log(f"sequence revive update failed row={row.get('id')}: {exc}")
    return revived


def _notify_ezra(env: dict[str, str], data: dict[str, Any], changed: list[str]) -> bool:
    if str(env.get("UW_ENRICH_NOTIFY_EZRA") or "1").strip().lower() in ("0", "false", "no"):
        return False
    try:
        from scrubber import telegram_bridge as tg
    except Exception as exc:  # noqa: BLE001
        _log(f"telegram import failed: {exc}")
        return False
    chat = (env.get("EZRA_TELEGRAM_CHAT_ID") or "").strip()
    if not chat:
        return False
    biz = data.get("business_name") or data.get("company") or "(unnamed)"
    bits = []
    if "email" in changed and data.get("email"):
        bits.append(f"email: {data['email']} ({data.get('email_confidence', 'LOW')})")
    if "phone" in changed and data.get("phone"):
        bits.append(f"phone: {data['phone']} ({data.get('phone_confidence', 'LOW')})")
    if not bits:
        return False
    text = "UW lead enriched - verify before relying on it.\n\n" + str(biz) + "\n" + "\n".join(bits)
    res = tg.api(env, "sendMessage", {"chat_id": chat, "text": text})
    return bool(res.get("ok"))


def _fetch_candidate_leads(sb, limit: int) -> list[dict[str, Any]]:
    try:
        rows = (
            sb.table("tenant_records")
            .select("id, tenant_id, entity_type, data, created_at")
            .eq("tenant_id", SUNBIZ_TENANT_ID)
            .eq("entity_type", "lead")
            .order("created_at", desc=True)
            .limit(max(limit * 20, 500))
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        _log(f"lead read failed: {exc}")
        return []
    out = [r for r in rows if _is_uw_lead(r.get("data") or {})]
    return out[:limit]


def _notify_ezra_manual_review(env: dict[str, str], data: dict[str, Any], lead_id: str) -> bool:
    """Tell Ezra a deal needs a hand-run phone lookup, and give him everything
    needed to do it: the reason it couldn't be resolved automatically, the exact
    search terms, and a deep link to the lead.

    Honors the same UW_ENRICH_NOTIFY_EZRA kill switch as the enrichment notice.
    Callers must guard on phone_lookup_notified_at — this fires on every call."""
    if str(env.get("UW_ENRICH_NOTIFY_EZRA") or "1").strip().lower() in ("0", "false", "no"):
        return False
    try:
        from scrubber import telegram_bridge as tg
    except Exception as exc:  # noqa: BLE001
        _log(f"telegram import failed: {exc}")
        return False
    chat = (env.get("EZRA_TELEGRAM_CHAT_ID") or "").strip()
    if not chat:
        return False

    biz = data.get("business_name") or data.get("company") or "(unnamed)"
    lines = [
        "Phone lookup needs a human.",
        "",
        str(biz),
        f"Why: {data.get('phone_lookup_reason') or 'could not be resolved automatically'}",
    ]
    query = data.get("phone_lookup_query")
    if query:
        lines.append(f"Search: {query}")
    n_candidates = len(data.get("phone_lookup_candidates") or [])
    if n_candidates:
        lines.append(f"{n_candidates} unconfirmed candidate number(s) on the lead.")
    base = (env.get("OASIS_DASHBOARD_URL") or env.get("BRAVO_DASHBOARD_URL") or "").rstrip("/")
    if base:
        lines.append(f"{base}/leads/{lead_id}")

    res = tg.api(env, "sendMessage", {"chat_id": chat, "text": "\n".join(lines)})
    return bool(res.get("ok"))


def _max_notify(env: dict[str, str]) -> int:
    """Per-pass cap on Ezra verification messages so the first backfill pass over
    a backlog of contact-less leads can't flood the Dolphin chat. 0 = unlimited."""
    try:
        return max(0, int(str(env.get("UW_ENRICH_MAX_NOTIFY") or "5").strip()))
    except ValueError:
        return 5


def _notify_enabled(env: dict[str, str]) -> bool:
    """Ezra verification notices on (default). Turning this off is an explicit
    operator decision (UW_ENRICH_NOTIFY_EZRA=0) — it also waives the notify-before-
    revive gate below, which is why it must never default off."""
    return str(env.get("UW_ENRICH_NOTIFY_EZRA") or "1").strip().lower() not in ("0", "false", "no")


def _live_enabled(env: dict[str, str]) -> bool:
    """Approval gate for the autonomous loop (Codex audit P1, 2026-07-03): a bare
    `pm2 start ecosystem.config.js` on the VPS starts EVERY registered app, which
    would run live web lookups + DB writes + drip revivals before CC's dry-run
    review. Mirrors the scrubber's SIFT_PARSER_READY pattern — the loop idles as a
    no-op until CC sets UW_ENRICH_READY=1 (via scripts/set_secret.py) and restarts.
    Manual `once` runs and `--dry-run` are operator-driven and stay ungated."""
    return str(env.get("UW_ENRICH_READY") or "").strip() == "1"


def process_once(sb, env: dict[str, str], *, dry_run: bool, limit: int, force_refresh: bool, skip_web: bool) -> dict[str, int]:
    stats = {"seen": 0, "updated": 0, "sheet_refreshed": 0, "contact_found": 0, "contact_deferred": 0, "events": 0, "revived": 0, "notified": 0, "errors": 0}
    max_notify = _max_notify(env)
    notify_on = _notify_enabled(env)
    for row in _fetch_candidate_leads(sb, limit):
        stats["seen"] += 1
        lead_id = row["id"]
        original = row.get("data") or {}
        data = dict(original)
        changed_keys: list[str] = []
        sheet_contact_keys: list[str] = []
        web_contact_keys: list[str] = []

        if force_refresh or _needs_sheet_refresh(data):
            fresh, _, err = _refresh_from_source_sheet(env, data)
            if err:
                stats["errors"] += 1
                _log(f"sheet refresh failed lead={lead_id}: {err}")
            else:
                sheet_changes = _merge_fill_only(data, fresh)
                if sheet_changes:
                    changed_keys.extend(sheet_changes)
                    # Sheet-sourced contact is merchant-provided (Jotform) — trusted
                    # provenance, unlike web-scraped candidates below.
                    sheet_contact_keys = [k for k in sheet_changes if k in ("email", "phone")]
                    stats["sheet_refreshed"] += 1

        # Ezra verification is a GATE for web-sourced contacts, not a courtesy ping
        # (Codex audit P1, 2026-07-03). Past the per-pass notify cap we DEFER the web
        # lookup entirely — no write, no revive — so a later pass (with cap headroom)
        # sources AND notifies together. Never persist a scraped contact Ezra won't
        # hear about. Dry runs are exempt: CC reviews the full candidate set.
        over_cap = (not dry_run) and notify_on and max_notify > 0 and stats["notified"] >= max_notify
        needs_web = not skip_web and not (_has_email(data) and _has_phone(data))
        if over_cap and needs_web:
            stats["contact_deferred"] += 1
        else:
            contact_incoming, contact_changed = _enrich_contact(data, skip_web=skip_web)
            contact_fill = _merge_fill_only(data, contact_incoming)
            if contact_changed:
                changed_keys.extend(contact_changed)
                web_contact_keys = [k for k in contact_changed if k in ("email", "phone")]
                stats["contact_found"] += 1
            elif contact_fill:
                changed_keys.extend(contact_fill)

        if not changed_keys:
            continue
        data["uw_enriched_at"] = _now_iso()
        data["uw_enrichment_version"] = "2026-07-03"

        preview = ", ".join(sorted(set(changed_keys))[:8])
        contact_preview = _contact_preview(data, changed_keys)
        if dry_run:
            suffix = f" contact={contact_preview}" if contact_preview else ""
            _log(f"DRY update lead={lead_id} fields={preview}{suffix}")
            continue

        try:
            sb.table("tenant_records").update({"data": data}).eq("id", lead_id).eq("tenant_id", SUNBIZ_TENANT_ID).execute()
            stats["updated"] += 1
            new_contact_keys = sheet_contact_keys + web_contact_keys
            if new_contact_keys:
                _publish_status_event(sb, lead_id, data)
                stats["events"] += 1
                notified = False
                if notify_on and _notify_ezra(env, data, new_contact_keys):
                    stats["notified"] += 1
                    notified = True
                    _log(f"notified Ezra lead={lead_id}")
                # Drip revival gate: sheet-sourced contact (merchant-provided) revives
                # freely. Web-sourced contact revives ONLY if the Ezra notice actually
                # went out — or the operator explicitly disabled notices — so failed
                # outreach never silently restarts on an unverified scraped channel.
                may_revive = bool(sheet_contact_keys) or (bool(web_contact_keys) and (notified or not notify_on))
                if may_revive:
                    stats["revived"] += _revive_missing_contact_steps(sb, lead_id, data)
                elif web_contact_keys:
                    _log(f"revive withheld lead={lead_id}: web-sourced contact but Ezra notice not confirmed")
            # No usable number and the candidates couldn't be separated — this
            # deal needs a human in CLEAR. Ping ONCE per lead (the guard below),
            # so a 5-minute loop can't turn one stuck deal into a pager storm.
            if notify_on and data.get("phone_lookup_status") == "manual_review" \
                    and not data.get("phone_lookup_notified_at"):
                if _notify_ezra_manual_review(env, data, lead_id):
                    stats["notified"] += 1
                    data["phone_lookup_notified_at"] = _now_iso()
                    try:
                        sb.table("tenant_records").update({"data": data}).eq("id", lead_id).eq(
                            "tenant_id", SUNBIZ_TENANT_ID).execute()
                    except Exception as exc:  # noqa: BLE001
                        # The ping went out; failing to stamp only risks a repeat.
                        _log(f"notify stamp failed lead={lead_id}: {exc}")
                    _log(f"notified Ezra (manual phone lookup) lead={lead_id}")
            _log(f"updated lead={lead_id} fields={preview}")
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            _log(f"update failed lead={lead_id}: {exc}")
    if stats["contact_deferred"]:
        _log(
            f"deferred web enrichment for {stats['contact_deferred']} lead(s) this pass "
            f"(notify cap={max_notify}) — nothing written for them; next pass picks them up"
        )
    return stats


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def acquire_claim(stale_seconds: int = 900) -> bool:
    CLAIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        if CLAIM_PATH.exists():
            rec = json.loads(CLAIM_PATH.read_text(encoding="utf-8"))
            ts = rec.get("ts")
            age = None
            if ts:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
                except Exception:
                    age = None
            other_pid = rec.get("pid")
            fresh = age is None or age < stale_seconds
            if other_pid != os.getpid() and _pid_alive(other_pid) and fresh:
                return False
    except Exception:
        pass
    refresh_claim()
    return True


def refresh_claim() -> None:
    try:
        CLAIM_PATH.write_text(json.dumps({"pid": os.getpid(), "ts": _now_iso()}), encoding="utf-8")
    except OSError:
        pass


def doctor(env: dict[str, str]) -> int:
    _log("-- UW lead enricher doctor --")
    sb = _client(env)
    print(f"  supabase client:       {'ok' if sb else 'MISSING'}")
    print(f"  SunBiz tenant_id:      {SUNBIZ_TENANT_ID}")
    print(f"  CEO-Agent root:        {BRAVO_ROOT or 'NOT FOUND'}")
    print(f"  Drive source owner:    {SHEET_OWNER}")
    print(f"  sheet title hint:      {SHEET_TITLE_HINT}")
    missing = ingest._missing_creds(env)
    print(f"  Breeze Drive creds:    {'all set' if not missing else 'MISSING: ' + ', '.join(missing)}")
    if not missing:
        try:
            found = ingest.discover_sheets(env, owner=SHEET_OWNER, title_hint=SHEET_TITLE_HINT, max_results=25)
            print(f"  Drive discovery:       OK ({len(found)} candidate sheets in latest scan)")
        except Exception as exc:  # noqa: BLE001
            print(f"  Drive discovery:       FAIL - {exc}")
    bravo = Path(BRAVO_ROOT) if BRAVO_ROOT else None
    print(f"  Firecrawl tool:        {'present' if bravo and (bravo / 'scripts/integrations/firecrawl_tool.py').exists() else 'missing'}")
    print(f"  research_fetch tool:   {'present' if bravo and (bravo / 'scripts/research_fetch.py').exists() else 'missing'}")
    print(f"  Ezra Telegram config:  token={'set' if env.get('EZRA_TELEGRAM_BOT_TOKEN') else 'unset'} chat={'set' if env.get('EZRA_TELEGRAM_CHAT_ID') else 'unset'}")
    print(f"  live-loop gate:        {'ENABLED (UW_ENRICH_READY=1)' if _live_enabled(env) else 'disabled — loop idles until UW_ENRICH_READY=1 (set_secret.py)'}")
    print(f"  notify cap per pass:   {_max_notify(env) or 'unlimited'} (Ezra notices {'on' if _notify_enabled(env) else 'OFF — revive gate waived'})")
    if sb:
        leads = _fetch_candidate_leads(sb, 500)
        missing_contact = sum(1 for r in leads if not (_has_email(r.get("data") or {}) and _has_phone(r.get("data") or {})))
        needs_sheet = sum(1 for r in leads if _needs_sheet_refresh(r.get("data") or {}))
        print(f"  UW leads sampled:      {len(leads)}")
        print(f"  missing contact:       {missing_contact}")
        print(f"  needs sheet refresh:   {needs_sheet}")
    return 0 if sb else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh/enrich approved Breeze UW leads")
    parser.add_argument("mode", choices=["once", "loop", "doctor"], nargs="?", default="once")
    parser.add_argument("--interval", type=int, default=300, help="seconds between loop passes")
    parser.add_argument("--limit", type=int, default=100, help="max UW leads to inspect per pass")
    parser.add_argument("--dry-run", action="store_true", help="print changes without writing")
    parser.add_argument("--force-refresh", action="store_true", help="re-read source sheets even if required fields are present")
    parser.add_argument("--skip-web", action="store_true", help="skip Firecrawl/TruePeopleSearch contact lookups")
    parser.add_argument("--no-notify", action="store_true", help="suppress Ezra Telegram verification notices")
    args = parser.parse_args(argv)

    env = _load_env()
    if args.no_notify:
        env["UW_ENRICH_NOTIFY_EZRA"] = "0"

    if args.mode == "doctor":
        return doctor(env)

    sb = _client(env)
    if sb is None:
        return 1

    if args.mode == "once":
        stats = process_once(
            sb,
            env,
            dry_run=args.dry_run,
            limit=args.limit,
            force_refresh=args.force_refresh,
            skip_web=args.skip_web,
        )
        _log(f"once stats={stats}")
        return 0 if stats["errors"] == 0 else 1

    if not acquire_claim():
        print("[uw-enricher] another instance holds the claim - exiting", file=sys.stderr)
        return 1
    _log(f"loop: refreshing UW leads every {max(60, args.interval)}s")
    while True:
        try:
            refresh_claim()
            if not args.dry_run and not _live_enabled(env):
                _log(
                    "live loop DISABLED — idling (no reads, no writes). To enable: set "
                    "UW_ENRICH_READY=1 via scripts/set_secret.py, then "
                    "`pm2 restart uw-lead-enricher --update-env`."
                )
            else:
                stats = process_once(
                    sb,
                    env,
                    dry_run=args.dry_run,
                    limit=args.limit,
                    force_refresh=args.force_refresh,
                    skip_web=args.skip_web,
                )
                _log(f"loop stats={stats}")
        except Exception as exc:  # noqa: BLE001
            print(f"[uw-enricher] tick error: {exc}", file=sys.stderr)
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    sys.exit(main())
