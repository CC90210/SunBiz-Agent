#!/usr/bin/env python3
"""
SunBiz — interactive seeder for lender restricted_states + restricted_industries
================================================================================
The SOP §4 scoring in oasis-command-center's lib/lenders/match-fitness.ts
consumes lender.restricted_states[] and lender.restricted_industries[], but
those fields are unseeded on most lender rows, so the high-risk filters never
fire. This CLI walks Adon through the top restricted states and industries one
at a time, shows a before/after diff, and applies on confirm.

Run as:  cd /srv/sunbiz/sunbiz-agent && python3 scripts/adon_seed_lender_constraints.py

Safe to run repeatedly. By default a lender that already has a value for a
field keeps it (fill-only); pass --force to merge new picks into existing
lists too.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# The supabase SDK lives in CEO-Agent's venv, not system python — re-exec
# there if the import is missing so `python3 scripts/...` just works.
_VENV_PY = "/srv/sunbiz/ceo-agent/.venv/bin/python"
try:
    import supabase  # noqa: F401
except ImportError:
    if os.path.exists(_VENV_PY) and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PY):
        os.execv(_VENV_PY, [_VENV_PY, *sys.argv])
    print("ERROR: supabase SDK not importable and CEO-Agent venv not found.", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

bootstrap_bravo_path()

SUNBIZ_TENANT_ID = "aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110"
TOP_STATES = ["NY", "CA", "FL", "VT", "NJ", "TX"]
TOP_INDUSTRIES = ["trucking", "cannabis", "gas_station", "auto", "construction"]


def _supabase():
    from lib.secret_loader import load_env
    env = load_env(required=["BRAVO_SUPABASE_URL", "BRAVO_SUPABASE_SERVICE_ROLE_KEY"])
    from supabase import create_client
    return create_client(env["BRAVO_SUPABASE_URL"], env["BRAVO_SUPABASE_SERVICE_ROLE_KEY"])


def _fetch_lenders(sb) -> list[dict]:
    rows = (
        sb.table("tenant_records")
        .select("id, data")
        .eq("tenant_id", SUNBIZ_TENANT_ID)
        .eq("entity_type", "lender")
        .order("created_at")
        .execute()
    ).data or []
    return [r for r in rows if (r.get("data") or {}).get("name")]


def _ask_numbers(prompt: str, count: int) -> list[int]:
    """Prompt for comma-separated 1-based numbers; re-ask on bad input."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return []
        try:
            picks = sorted({int(tok) for tok in raw.replace(" ", "").split(",") if tok})
        except ValueError:
            print("  Please enter numbers like: 1,4,12 (or blank to skip)")
            continue
        bad = [n for n in picks if n < 1 or n > count]
        if bad:
            print(f"  Out of range: {bad} (valid 1-{count})")
            continue
        return picks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--force", action="store_true",
                        help="merge into lenders that already have values (default: fill-only)")
    args = parser.parse_args()

    sb = _supabase()
    lenders = _fetch_lenders(sb)
    if not lenders:
        print("No SunBiz lender rows found — nothing to seed.")
        return 0

    print(f"\n{len(lenders)} SunBiz lenders:\n")
    for i, l in enumerate(lenders, 1):
        d = l["data"]
        cur_s = d.get("restricted_states") or []
        cur_i = d.get("restricted_industries") or []
        extra = f"   (states={cur_s} industries={cur_i})" if cur_s or cur_i else ""
        print(f"  [{i:>2}] {d['name'].strip()}{extra}")

    # picks[lender_index] = {"states": set, "industries": set}
    picks: dict[int, dict[str, set]] = {}

    print("\n— Restricted STATES —")
    for state in TOP_STATES:
        nums = _ask_numbers(
            f"Which lenders restrict {state} funding? Enter numbers comma-separated (or blank to skip): ",
            len(lenders),
        )
        for n in nums:
            picks.setdefault(n - 1, {"states": set(), "industries": set()})["states"].add(state)

    print("\n— Excluded INDUSTRIES —")
    for ind in TOP_INDUSTRIES:
        nums = _ask_numbers(
            f"Which lenders exclude {ind}? Enter numbers comma-separated (or blank to skip): ",
            len(lenders),
        )
        for n in nums:
            picks.setdefault(n - 1, {"states": set(), "industries": set()})["industries"].add(ind)

    # Build the diff. Fill-only unless --force: an existing non-empty list wins.
    changes: list[tuple[dict, list, list]] = []
    for idx, sel in sorted(picks.items()):
        lender = lenders[idx]
        d = lender["data"]
        cur_s = [s.upper() for s in (d.get("restricted_states") or [])]
        cur_i = [s.lower() for s in (d.get("restricted_industries") or [])]
        new_s = sorted(set(cur_s) | {s.upper() for s in sel["states"]}) if (args.force or not cur_s) else cur_s
        new_i = sorted(set(cur_i) | {s.lower() for s in sel["industries"]}) if (args.force or not cur_i) else cur_i
        if new_s != cur_s or new_i != cur_i:
            changes.append((lender, new_s, new_i))
        elif sel["states"] or sel["industries"]:
            print(f"  ~ {d['name'].strip()}: already seeded, skipping (re-run with --force to merge)")

    if not changes:
        print("\nNothing to change. Done.")
        return 0

    print(f"\n— Preview: {len(changes)} lender(s) to update —")
    for lender, new_s, new_i in changes:
        d = lender["data"]
        print(f"\n  {d['name'].strip()}")
        print(f"    restricted_states:     {json.dumps(d.get('restricted_states') or [])}  ->  {json.dumps(new_s)}")
        print(f"    restricted_industries: {json.dumps(d.get('restricted_industries') or [])}  ->  {json.dumps(new_i)}")

    if input("\nApply? [y/N] ").strip().lower() != "y":
        print("Aborted — nothing written.")
        return 0

    for lender, new_s, new_i in changes:
        new_data = dict(lender["data"])
        new_data["restricted_states"] = new_s
        new_data["restricted_industries"] = new_i
        (
            sb.table("tenant_records")
            .update({"data": new_data})
            .eq("id", lender["id"])
            .eq("tenant_id", SUNBIZ_TENANT_ID)
            .execute()
        )
        print(f"  ✓ {lender['data']['name'].strip()}")

    print(f"\nDone — {len(changes)} lender(s) updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
