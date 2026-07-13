"""scrubber/backfill_live_sub_applications.py — one-time (idempotent) backfill.

Every Breeze "live sub" Ezra approved BEFORE the auto-promote wiring landed was
injected as a lead at the uw_sheet / "Live Subs" stage and then stranded there —
nothing ever turned it into a shoppable application. This script finds those
leads and runs each through the SAME dashboard promote endpoint the live approve
path now calls (promote_via_dashboard), so the backfill and the live path can
never diverge.

Selection: entity=lead, data.source='breeze_uw_sheet', NOT already transferred
(data.transferred_at is null). The promote endpoint is idempotent (it reuses a
lead's existing application and only gap-fills), so re-running is safe.

Usage:
  python scripts/scrubber/backfill_live_sub_applications.py --dry-run   # list only
  python scripts/scrubber/backfill_live_sub_applications.py             # promote all
  python scripts/scrubber/backfill_live_sub_applications.py --limit 2   # cap count
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

bootstrap_bravo_path()

from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402
from scrubber.telegram_bridge import load_env, supabase, promote_via_dashboard  # noqa: E402


def find_stranded_leads(sb, limit: int) -> list[dict[str, Any]]:
    """Live-sub leads not yet transferred to an application, newest first."""
    q = (
        sb.table("tenant_records")
        .select("id, created_at, data->>business_name, data->>stage, data->>transferred_at")
        .eq("tenant_id", SUNBIZ_TENANT_ID)
        .eq("entity_type", "lead")
        .eq("data->>source", "breeze_uw_sheet")
        .is_("data->>transferred_at", "null")
        .order("created_at", desc=True)
        .limit(limit)
    )
    return q.execute().data or []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill live-sub leads into applications")
    p.add_argument("--dry-run", action="store_true", help="list candidates without promoting")
    p.add_argument("--limit", type=int, default=100, help="max leads to process")
    args = p.parse_args(argv)

    env = load_env()
    sb = supabase(env)
    if sb is None:
        print("supabase client unavailable (need BRAVO_SUPABASE_URL + SERVICE_ROLE_KEY)", file=sys.stderr)
        return 1

    leads = find_stranded_leads(sb, args.limit)
    print(f"Found {len(leads)} stranded live-sub lead(s):")
    for l in leads:
        print(f"  {l['id'][:8]}  {l.get('created_at', '')[:16]}  {l.get('business_name') or '(unnamed)'}")

    if args.dry_run:
        print("\n--dry-run: no changes made.")
        return 0
    if not leads:
        return 0

    ok = fail = 0
    print()
    for l in leads:
        lead_id = l["id"]
        promoted, detail = promote_via_dashboard(env, lead_id)
        if promoted:
            app_id = detail.get("application_id") if isinstance(detail, dict) else None
            pstatus = detail.get("phone_status") if isinstance(detail, dict) else None
            created = detail.get("created") if isinstance(detail, dict) else None
            ok += 1
            print(f"  ✓ {lead_id[:8]} {l.get('business_name') or '?':32} → app {str(app_id)[:8]} "
                  f"(created={created}, phone={pstatus})")
        else:
            fail += 1
            print(f"  ✗ {lead_id[:8]} {l.get('business_name') or '?':32} → FAILED: {detail}", file=sys.stderr)

    print(f"\nDone. promoted={ok} failed={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
