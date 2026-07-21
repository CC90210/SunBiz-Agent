"""backfill_dedupe_scrub_candidates.py — collapse duplicate review cards.

One-time cleanup for the duplicates created before the 2026-07-21 identity fix
(scrubber/state.py::row_hash). The old hash keyed on `mca_positions`, which
increments as the underwriter fills funder rows into the live UW Sheet, so a
single deal minted a new review card on every edit — 163 of 476 pending cards
were redundant, and one deal (nexgen networks corp 720) staged 6 times from a
single sheet.

WHAT IT DOES
Groups `pending_review` rows by `source_file_id` (one sheet IS one deal) and
keeps the NEWEST row in each group — that scrape saw the most complete sheet.
Older siblings are soft-closed to `status='superseded'` with a review_note
pointing at the survivor. Nothing is deleted, so the collapse is reversible.

WHAT IT WILL NOT TOUCH
  - `approved` / `declined` rows — reviewer decisions are final. (Verified
    2026-07-21: approved has ZERO duplicates, so no lead or application was ever
    created twice by this bug.)
  - groups of one, and rows with no source_file_id.

DRY RUN BY DEFAULT. `--apply` is required to write.

  python scripts/backfill_dedupe_scrub_candidates.py            # preview
  python scripts/backfill_dedupe_scrub_candidates.py --apply
  python scripts/backfill_dedupe_scrub_candidates.py --undo     # restore
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _bravo_bootstrap import bootstrap_bravo_path, load_bravo_env  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()

from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402

TABLE = "scrub_candidates"
SUPERSEDED = "superseded"
NOTE_PREFIX = "auto-deduped"
PAGE = 1000


def _log(msg: str) -> None:
    print(f"[dedupe-backfill] {msg}")


def _client(env: dict[str, str]):
    url = (env.get("BRAVO_SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise SystemExit("BRAVO_SUPABASE_URL / SERVICE_ROLE_KEY missing")
    from supabase import create_client  # type: ignore

    return create_client(url, key)


def _fetch_all(sb, status: str) -> list[dict[str, Any]]:
    """Every row at `status` for this tenant. Paginated — PostgREST caps at
    1000 per request and an unpaginated read silently truncates (which is how
    the duplicate count was under-reported the first time it was measured)."""
    rows: list[dict[str, Any]] = []
    page = 0
    while True:
        r = (
            sb.table(TABLE)
            .select("id,status,created_at,source_file,source_file_id,row_hash,lead_data,review_note")
            .eq("tenant_id", SUNBIZ_TENANT_ID)
            .eq("status", status)
            .order("created_at", desc=True)
            .range(page * PAGE, (page + 1) * PAGE - 1)
            .execute()
        )
        batch = r.data or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        page += 1


def _name(row: dict[str, Any]) -> str:
    d = row.get("lead_data") or {}
    return str(d.get("business_name") or d.get("company") or "(unnamed)")[:38]


def _positions(row: dict[str, Any]) -> Any:
    return (row.get("lead_data") or {}).get("mca_positions")


def plan(sb) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """[(survivor, [superseded...])] for every duplicated sheet."""
    rows = _fetch_all(sb, "pending_review")
    _log(f"pending_review rows: {len(rows)}")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        fid = r.get("source_file_id")
        if fid:
            groups[fid].append(r)
    out = []
    for fid, g in groups.items():
        if len(g) < 2:
            continue
        g.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        out.append((g[0], g[1:]))
    no_file = sum(1 for r in rows if not r.get("source_file_id"))
    _log(f"distinct sheets: {len(groups)} | duplicated: {len(out)} | rows without source_file_id (untouched): {no_file}")
    return out


def show(groups: list[tuple[dict[str, Any], list[dict[str, Any]]]], verbose: bool) -> int:
    total = sum(len(dups) for _s, dups in groups)
    if not groups:
        _log("no duplicates found — nothing to do")
        return 0
    limit = len(groups) if verbose else 12
    for survivor, dups in sorted(groups, key=lambda t: -len(t[1]))[:limit]:
        _log(f"{_name(survivor)}  ({len(dups) + 1} cards -> 1)")
        _log(f"    KEEP       {survivor['created_at'][:19]}  id={survivor['id']}  positions={_positions(survivor)}")
        for d in dups:
            _log(f"    supersede  {d['created_at'][:19]}  id={d['id']}  positions={_positions(d)}")
    if len(groups) > limit:
        _log(f"... and {len(groups) - limit} more group(s) (--verbose to list all)")
    return total


def apply(sb, groups: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> int:
    done = 0
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for survivor, dups in groups:
        for d in dups:
            note = f"{NOTE_PREFIX} {stamp} -> kept {survivor['id']}"
            try:
                sb.table(TABLE).update({"status": SUPERSEDED, "review_note": note}).eq("id", d["id"]).execute()
                done += 1
            except Exception as e:  # noqa: BLE001
                _log(f"FAILED {d['id']}: {e}")
    return done


def undo(sb) -> int:
    """Restore every row this script superseded back to pending_review."""
    rows = _fetch_all(sb, SUPERSEDED)
    mine = [r for r in rows if str(r.get("review_note") or "").startswith(NOTE_PREFIX)]
    _log(f"{SUPERSEDED} rows: {len(rows)} | written by this script: {len(mine)}")
    done = 0
    for r in mine:
        try:
            sb.table(TABLE).update({"status": "pending_review", "review_note": None}).eq("id", r["id"]).execute()
            done += 1
        except Exception as e:  # noqa: BLE001
            _log(f"FAILED {r['id']}: {e}")
    return done


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Collapse duplicate scrub_candidates review cards.")
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    ap.add_argument("--undo", action="store_true", help="restore rows this script superseded")
    ap.add_argument("--verbose", action="store_true", help="list every group, not just the worst 12")
    args = ap.parse_args(argv)

    sb = _client(load_bravo_env())

    if args.undo:
        if not args.apply:
            rows = [r for r in _fetch_all(sb, SUPERSEDED)
                    if str(r.get("review_note") or "").startswith(NOTE_PREFIX)]
            _log(f"DRY RUN — would restore {len(rows)} row(s) to pending_review. Re-run with --undo --apply.")
            return 0
        _log(f"restored {undo(sb)} row(s)")
        return 0

    groups = plan(sb)
    total = show(groups, args.verbose)
    if not total:
        return 0
    if not args.apply:
        _log("")
        _log(f"DRY RUN — would supersede {total} redundant card(s) across {len(groups)} deal(s).")
        _log("Nothing was written. Re-run with --apply to perform the collapse.")
        return 0
    n = apply(sb, groups)
    _log(f"superseded {n} row(s); {len(groups)} deal(s) now show a single card")
    _log("reversible with: --undo --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
