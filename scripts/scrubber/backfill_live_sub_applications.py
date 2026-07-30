"""scrubber/backfill_live_sub_applications.py — one-time (idempotent) backfill.

Every Breeze "live sub" Ezra approved BEFORE the auto-promote wiring landed was
injected as a lead at the uw_sheet / "Live Subs" stage and then stranded there —
nothing ever turned it into a shoppable application. This script finds those
leads and runs each through the SAME dashboard promote endpoint the live approve
path now calls (promote_via_dashboard), so the backfill and the live path can
never diverge.

Default selection: entity=lead, data.source='breeze_uw_sheet', with no linked
application_id. ``--repair-hidden`` instead selects legacy Dolphin approvals
that carry both application_id and transferred_at from the old buggy route.
The promote endpoint is idempotent and only restores untouched
``application_in`` auto-promotions; operator-advanced deals are not moved back.

Usage:
  python scripts/scrubber/backfill_live_sub_applications.py --dry-run   # list only
  python scripts/scrubber/backfill_live_sub_applications.py             # promote all
  python scripts/scrubber/backfill_live_sub_applications.py --repair-hidden
  python scripts/scrubber/backfill_live_sub_applications.py --limit 2   # cap count
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

bootstrap_bravo_path()

from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402
from scrubber.telegram_bridge import load_env, supabase, promote_via_dashboard  # noqa: E402


def select_leads(rows: list[dict[str, Any]], *, repair_hidden: bool) -> list[dict[str, Any]]:
    """Pure selector kept separate so the safety boundary is regression-tested."""
    if repair_hidden:
        selected = []
        for row in rows:
            if not row.get("transferred_at") or not row.get("application_id"):
                continue
            try:
                created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
                transferred = datetime.fromisoformat(
                    str(row["transferred_at"]).replace("Z", "+00:00")
                )
            except (KeyError, TypeError, ValueError):
                continue
            # The buggy Telegram path wrote transferred_at automatically during
            # approval, typically 1-2 seconds after insert. A later operator
            # Transfer is authoritative and must never be reversed.
            if 0 <= (transferred - created).total_seconds() <= 10:
                selected.append(row)
        return selected
    return [r for r in rows if not r.get("application_id")]


def find_live_sub_leads(sb, limit: int, *, repair_hidden: bool = False) -> list[dict[str, Any]]:
    """Return missing-app leads or legacy hidden approvals, newest first."""
    q = (
        sb.table("tenant_records")
        .select(
            "id, created_at, data->>business_name, data->>stage,"
            "data->>transferred_at, data->>application_id"
        )
        .eq("tenant_id", SUNBIZ_TENANT_ID)
        .eq("entity_type", "lead")
        .eq("data->>source", "breeze_uw_sheet")
        .order("created_at", desc=True)
        .limit(limit)
    )
    rows = q.execute().data or []
    return select_leads(rows, repair_hidden=repair_hidden)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill live-sub leads into applications")
    p.add_argument("--dry-run", action="store_true", help="list candidates without promoting")
    p.add_argument(
        "--repair-hidden",
        action="store_true",
        help="restore legacy Dolphin approvals hidden by transferred_at",
    )
    p.add_argument("--limit", type=int, default=100, help="max leads to process")
    args = p.parse_args(argv)

    env = load_env()
    sb = supabase(env)
    if sb is None:
        print("supabase client unavailable (need BRAVO_SUPABASE_URL + SERVICE_ROLE_KEY)", file=sys.stderr)
        return 1

    leads = find_live_sub_leads(sb, args.limit, repair_hidden=args.repair_hidden)
    kind = "legacy hidden" if args.repair_hidden else "stranded"
    print(f"Found {len(leads)} {kind} live-sub lead(s):")
    for l in leads:
        print(f"  {l['id'][:8]}  {l.get('created_at', '')[:16]}  {l.get('business_name') or '(unnamed)'}")

    if args.dry_run:
        print("\n--dry-run: no changes made.")
        return 0
    if not leads:
        return 0

    ok = skipped = fail = 0
    print()
    for l in leads:
        lead_id = l["id"]
        promoted, detail = promote_via_dashboard(
            env,
            lead_id,
            restore_live_subs=args.repair_hidden,
        )
        if promoted:
            retained = (
                detail.get("retained_in_live_subs")
                if isinstance(detail, dict) else None
            )
            if args.repair_hidden and retained is not True:
                skipped += 1
                print(
                    f"  ↷ {lead_id[:8]} {l.get('business_name') or '?':32} "
                    "→ kept in its advanced application stage"
                )
                continue
            app_id = detail.get("application_id") if isinstance(detail, dict) else None
            pstatus = detail.get("phone_status") if isinstance(detail, dict) else None
            created = detail.get("created") if isinstance(detail, dict) else None
            ok += 1
            print(f"  ✓ {lead_id[:8]} {l.get('business_name') or '?':32} → app {str(app_id)[:8]} "
                  f"(created={created}, phone={pstatus})")
        else:
            fail += 1
            print(f"  ✗ {lead_id[:8]} {l.get('business_name') or '?':32} → FAILED: {detail}", file=sys.stderr)

    print(f"\nDone. promoted={ok} skipped_advanced={skipped} failed={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
