"""no_contact_24h_monitor.py — Build 1: active-deal 24h-no-contact follow-up.

Scans the SunBiz tenant for ACTIVE deals (deal_stage IN 'Application In',
'Missing Info','Shopping') that have had ZERO inbound contact in the last 24h,
and emits a NO_CONTACT_24H event per stale deal. sequence_runner.enrollment_tick
matches that event to the (operator-opt-in) re-engagement drip and enrolls the
lead; any inbound (text/call/email) later cancels the drip and reverts the deal
to active (the cancel happens in the inbound webhooks + the daemon-side
_cancel_drips_for_lead; the revert via rpc_revert_deal_stage — see migration
078).

STATUS (2026-06-03): SCAFFOLD — NOT YET ENABLED IN PM2. Blocked on a live-data
model mismatch with the build spec (verified against production):
  * deal_stage lives on entity_type='application' records, NOT 'lead'.
  * lead_interactions is EMPTY for SunBiz (0 rows) — there is no inbound-contact
    signal to test "no contact in 24h" against.
  * applications link to leads via a legacy NUMERIC data.lead_id (e.g. '4664'),
    not a tenant_records lead UUID (0/1 active apps map to a lead record), and
    only 1/58 active apps carry data.last_contacted_at.
This file therefore queries entity_type='lead' (the spec's model, which finds
nothing) on purpose, so it is inert until CC confirms: (a) the canonical
contact-recency source, and (b) the application->lead id used for enrollment +
drip context. See the report to CC. Do NOT add to ecosystem.config.js until
resolved.

Design (mirrors sequence_runner.py): _supabase() service-role client, a
state/no_contact_24h.cursor bookkeeping cursor, _log(), a tick() with CLI
`loop --interval 1800` and `once`.

Tenant scoping: resolves the SunBiz tenant by slug OR
custom_fields.command_center_profile_slug (the 'submissions'/'sun' nuance) —
mirrors provision_secrets._resolve_tenant. Only that tenant is scanned.

Safety: honors BRAVO_FORCE_DRY_RUN — when set (the default until CC approves),
the monitor LOGS the NO_CONTACT_24H events it would publish instead of writing
them. event_bus.publish already provides durable offline fallback
(tmp/events_offline.jsonl), so no separate fallback is reimplemented here.

Idempotency: idempotency_key=f"no_contact_24h:{lead_id}:{run_date}" makes a lead
emit at most once per UTC day, which also closes the monitor-emit vs
inbound-cancel race (a same-day re-emit is a no-op duplicate).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent  # SunBiz-Agent root
STATE_DIR = REPO_ROOT / "state"
CURSOR_PATH = STATE_DIR / "no_contact_24h.cursor"
LOG_PATH = STATE_DIR / "no_contact_24h.log"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()  # adds CEO-Agent/scripts to sys.path

# Canonical active deal stages (migration 071). Inactive: Funded/Declined/Dead.
ACTIVE_DEAL_STAGES = ("Application In", "Missing Info", "Shopping")
NO_CONTACT_WINDOW_HOURS = 24
DEFAULT_INTERVAL_SECONDS = 1800
TENANT_SLUG = "sun"


def _log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] [no_contact_24h] {msg}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    print(line.rstrip())


def _read_cursor() -> Optional[str]:
    if CURSOR_PATH.exists():
        try:
            t = CURSOR_PATH.read_text(encoding="utf-8").strip()
            return t or None
        except OSError:
            return None
    return None


def _write_cursor(ts: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CURSOR_PATH.write_text(ts, encoding="utf-8")
    except OSError:
        pass


def _dry_run() -> bool:
    raw = (os.environ.get("BRAVO_FORCE_DRY_RUN") or "").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


def _supabase():
    """Service-role Supabase client, or None on any failure."""
    try:
        from lib.secret_loader import load_env  # type: ignore
    except Exception:
        return None
    try:
        env = load_env()
    except Exception:
        return None
    url = (env.get("BRAVO_SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client  # type: ignore
        return create_client(url, key)
    except Exception:
        return None


def _resolve_tenant_id(sb, slug: str = TENANT_SLUG) -> Optional[str]:
    """Resolve a tenant by slug OR custom_fields.command_center_profile_slug.
    Mirrors provision_secrets._resolve_tenant — SunBiz is slug='submissions'
    with command_center_profile_slug='sun'."""
    try:
        r = sb.table("tenants").select("id, slug, custom_fields").eq("slug", slug).limit(1).execute()
        if r.data:
            return str(r.data[0]["id"])
        allr = sb.table("tenants").select("id, slug, custom_fields").execute().data or []
        for t in allr:
            cf = t.get("custom_fields") or {}
            if isinstance(cf, dict) and cf.get("command_center_profile_slug") == slug:
                return str(t["id"])
    except Exception as exc:
        _log(f"tenant resolve failed for '{slug}': {exc}")
    return None


def _active_deal_records(sb, tenant_id: str) -> list[dict]:
    """Active-stage lead records for the tenant. Tries a server-side JSON
    filter; falls back to fetch-and-filter so a PostgREST operator quirk
    can't silently drop rows."""
    try:
        rows = (
            sb.table("tenant_records")
            .select("id, tenant_id, data")
            .eq("tenant_id", tenant_id)
            .eq("entity_type", "lead")
            .in_("data->>deal_stage", list(ACTIVE_DEAL_STAGES))
            .execute()
        ).data or []
        return rows
    except Exception as exc:
        _log(f"server-side stage filter unavailable ({exc}); falling back to client-side filter")
        rows = (
            sb.table("tenant_records")
            .select("id, tenant_id, data")
            .eq("tenant_id", tenant_id)
            .eq("entity_type", "lead")
            .execute()
        ).data or []
        return [r for r in rows if ((r.get("data") or {}).get("deal_stage") in ACTIVE_DEAL_STAGES)]


def _leads_with_recent_inbound(sb, tenant_id: str, lead_ids: list[str], cutoff_iso: str) -> set[str]:
    """Set of lead_ids that have an inbound lead_interaction newer than cutoff."""
    if not lead_ids:
        return set()
    seen: set[str] = set()
    # Chunk the IN() to stay well under URL length limits.
    for i in range(0, len(lead_ids), 100):
        chunk = lead_ids[i:i + 100]
        try:
            rows = (
                sb.table("lead_interactions")
                .select("lead_id")
                .eq("tenant_id", tenant_id)
                .eq("direction", "inbound")
                .gt("created_at", cutoff_iso)
                .in_("lead_id", chunk)
                .execute()
            ).data or []
            for r in rows:
                if r.get("lead_id"):
                    seen.add(str(r["lead_id"]))
        except Exception as exc:
            _log(f"inbound query failed (chunk {i}): {exc}; treating chunk as contacted (fail-safe, no nag)")
            # Fail SAFE: if we can't confirm no-contact, don't nag. Mark the
            # whole chunk as "recently contacted" so they're excluded this tick.
            seen.update(str(x) for x in chunk)
    return seen


def tick(sb) -> int:
    """One scan. Returns the number of NO_CONTACT_24H events emitted (or that
    would be emitted in dry-run)."""
    from core.event_bus import publish  # type: ignore

    tenant_id = _resolve_tenant_id(sb)
    if not tenant_id:
        _log(f"tenant '{TENANT_SLUG}' not resolvable — nothing to scan")
        return 0

    now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(hours=NO_CONTACT_WINDOW_HOURS)).isoformat()
    run_date = now.date().isoformat()

    active = _active_deal_records(sb, tenant_id)
    if not active:
        _log(f"no active-stage deals for tenant={tenant_id}")
        _write_cursor(now.isoformat(timespec="seconds"))
        return 0

    active_ids = [str(r["id"]) for r in active if r.get("id")]
    contacted = _leads_with_recent_inbound(sb, tenant_id, active_ids, cutoff_iso)
    stale = [r for r in active if str(r.get("id")) not in contacted]

    dry = _dry_run()
    emitted = 0
    for rec in stale:
        lead_id = str(rec["id"])
        deal_stage = (rec.get("data") or {}).get("deal_stage")
        payload = {
            "lead_id": lead_id,
            "tenant_id": tenant_id,
            "deal_stage": deal_stage,
            "last_contact_at_iso": None,  # no inbound within the window
        }
        idem = f"no_contact_24h:{lead_id}:{run_date}"
        if dry:
            _log(f"[DRY RUN] would publish NO_CONTACT_24H lead={lead_id} stage={deal_stage} idem={idem}")
            emitted += 1
            continue
        res = publish(
            "NO_CONTACT_24H",
            payload,
            source="no_contact_24h_monitor",
            target=None,
            idempotency_key=idem,
        )
        status = res.get("status")
        if status in ("published", "duplicate", "offline"):
            if status == "published":
                emitted += 1
            _log(f"NO_CONTACT_24H lead={lead_id} stage={deal_stage} -> {status}")
        else:
            _log(f"publish unexpected status lead={lead_id}: {res}")

    _log(
        f"tick: tenant={tenant_id} active={len(active)} stale={len(stale)} "
        f"emitted={emitted} dry_run={dry}"
    )
    _write_cursor(now.isoformat(timespec="seconds"))
    return emitted


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Active-deal 24h-no-contact monitor (Build 1)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("loop", help="Run continuously")
    pl.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    sub.add_parser("once", help="Run a single scan and exit")
    args = p.parse_args(argv)

    sb = _supabase()
    if sb is None:
        _log("FATAL: no Supabase client (check BRAVO_SUPABASE_URL/SERVICE_ROLE_KEY)")
        return 2

    if args.cmd == "once":
        tick(sb)
        return 0

    interval = max(60, int(args.interval))
    _log(f"starting loop interval={interval}s dry_run={_dry_run()}")
    while True:
        try:
            tick(sb)
        except Exception as exc:  # noqa: BLE001 — daemon must not die on one bad tick
            _log(f"tick error: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
