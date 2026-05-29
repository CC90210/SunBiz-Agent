"""enrich_leads.py — Google Sheets lead-enrichment workflow tool.

Codifies the multi-pass enrichment pattern that emerged from the
2026-05-29 BA Approvals work: read sheet, identify NONE rows, emit a
work file for a research agent, then write results back to the sheet
once research is done. Replaces the throwaway /tmp/ scripts that
prior passes accumulated.

Subcommands:
  audit      Identify rows where the Email column is empty (or marked
             NONE) and emit a JSON work file for a research agent.
  writeback  Given a results JSON produced by the research agent,
             write email/confidence/source into the matching rows.
  status     Print HIGH/MEDIUM/LOW/NONE recovery breakdown for a tab.

Defaults are wired for the SunBiz BA Approvals sheet but everything
is overridable for other tenant CRMs (OASIS, future client tenants).

Usage:
  python scripts/enrich_leads.py audit --tab 'January 26'
      → writes /tmp/enrich_audit_january_26.json

  # research agent does work, emits results JSON

  python scripts/enrich_leads.py writeback \\
      --results /tmp/round1_results.json --tab 'January 26'
  python scripts/enrich_leads.py status --tab 'January 26'

Sheet layout assumptions (overridable):
  B = Business         D = First Name    E = Last Name
  F = Phone Number     M = Email         N = Email Confidence
  O = Email Source
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # SunBiz-Agent root
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()
if BRAVO_ROOT is None:
    print("ERROR: CEO-Agent runtime not found. Set BRAVO_AGENT_ROOT.", file=sys.stderr)
    sys.exit(1)

GOOGLE_TOOL = BRAVO_ROOT / "scripts" / "integrations" / "google_tool.py"

# SunBiz BA Approvals sheet — the canonical default. Override with --sheet-id.
DEFAULT_SHEET_ID = "1-Bhxss7dLiUQaDgNyi1ukxafFSlnAihmuIWykVHAjfs"

# Default column letters (1-indexed positions: A=1, B=2, ..., M=13, N=14, O=15)
DEFAULT_COLS = {
    "month": "A",
    "business": "B",
    "revenue": "C",
    "fname": "D",
    "lname": "E",
    "phone": "F",
    "agent_note": "G",
    "email": "M",
    "confidence": "N",
    "source": "O",
}


def _col_to_idx(letter: str) -> int:
    """Convert a single A-Z column letter to 0-indexed position."""
    letter = letter.upper().strip()
    if not re.fullmatch(r"[A-Z]", letter):
        raise ValueError(f"Single-letter column expected, got {letter!r}")
    return ord(letter) - ord("A")


def _sheets_read(sheet_id: str, range_a1: str) -> list[list[str]]:
    """Read a sheet range via google_tool.py sheets read --json."""
    proc = subprocess.run(
        [sys.executable, str(GOOGLE_TOOL), "sheets", "read",
         sheet_id, "--range", range_a1, "--json"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sheets read failed: {proc.stderr}")
    data = json.loads(proc.stdout)
    return data.get("values", [])


def _sheets_write(sheet_id: str, range_a1: str, cells: list[list[str]]) -> int:
    """Write a 2D array of cells via google_tool.py sheets write --json-values.

    Uses the --json-values path (added 2026-05-29) so values containing
    commas/semicolons/newlines round-trip safely. Returns updated cell count.
    """
    proc = subprocess.run(
        [sys.executable, str(GOOGLE_TOOL), "sheets", "write",
         sheet_id, "--range", range_a1,
         "--json-values", json.dumps(cells), "--json"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sheets write failed: {proc.stderr}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return 0
    return int(data.get("updatedCells", 0))


def cmd_audit(args) -> int:
    """Read the tab, identify NONE / empty Email rows, emit JSON work file."""
    cols = dict(DEFAULT_COLS)
    cols["email"] = args.email_col
    cols["confidence"] = args.conf_col

    rng = f"'{args.tab}'!A1:O{args.max_rows}"
    rows = _sheets_read(args.sheet_id, rng)
    if not rows:
        print(f"No rows read from {args.tab}", file=sys.stderr)
        return 1

    email_idx = _col_to_idx(cols["email"])
    conf_idx = _col_to_idx(cols["confidence"])
    business_idx = _col_to_idx(cols["business"])
    fname_idx = _col_to_idx(cols["fname"])
    lname_idx = _col_to_idx(cols["lname"])
    phone_idx = _col_to_idx(cols["phone"])

    none_leads = []
    skipped_no_business = 0
    for i, row in enumerate(rows):
        if i == 0:
            continue  # header
        # Pad row so index access is safe
        padded = row + [""] * (15 - len(row))
        business = padded[business_idx].strip()
        if not business:
            skipped_no_business += 1
            continue
        email = padded[email_idx].strip()
        confidence = padded[conf_idx].strip()
        if email or confidence in {"HIGH", "MEDIUM", "LOW"}:
            continue  # already enriched
        phone = padded[phone_idx]
        area = ""
        m = re.search(r"\((\d{3})\)", phone)
        if m:
            area = m.group(1)
        none_leads.append({
            "row": i + 1,
            "business": business,
            "fname": padded[fname_idx],
            "lname": padded[lname_idx],
            "phone": phone,
            "area_code": area,
            "prior_confidence": confidence,
        })

    safe_tab = re.sub(r"[^a-z0-9]+", "_", args.tab.lower()).strip("_")
    out_path = Path(args.out or f"/tmp/enrich_audit_{safe_tab}.json")
    out_path.write_text(json.dumps(none_leads, indent=2), encoding="utf-8")
    print(f"Sheet: {args.tab} ({len(rows)-1} data rows)")
    print(f"NONE / empty leads: {len(none_leads)}")
    print(f"Skipped (no business name): {skipped_no_business}")
    print(f"Work file: {out_path}")
    return 0


def cmd_writeback(args) -> int:
    """Given a results JSON, write email/confidence/source back to the sheet."""
    cols = dict(DEFAULT_COLS)
    cols["email"] = args.email_col
    cols["confidence"] = args.conf_col
    cols["source"] = args.source_col
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))

    written = 0
    skipped = 0
    errors = 0
    for r in results:
        row_num = r.get("row")
        if not row_num:
            skipped += 1
            continue
        email = r.get("email", "")
        confidence = r.get("confidence", "")
        source = r.get("source", "")
        # Skip empty NONE writes unless explicitly --include-none
        if not args.include_none and not email and confidence == "NONE":
            skipped += 1
            continue
        # Write the email / confidence / source cells in a single update
        first_col = cols["email"]
        last_col = cols["source"]
        rng = f"'{args.tab}'!{first_col}{row_num}:{last_col}{row_num}"
        # Pad the cell list to span first_col → last_col
        ncols = _col_to_idx(last_col) - _col_to_idx(first_col) + 1
        cells = [email, confidence, source]
        cells = (cells + [""] * ncols)[:ncols]
        try:
            updated = _sheets_write(args.sheet_id, rng, [cells])
            written += 1
            print(f"  row {row_num:>4d}: wrote {updated} cells "
                  f"[{confidence:>6s}] {email[:48]}")
        except RuntimeError as exc:
            errors += 1
            print(f"  row {row_num:>4d}: FAILED — {exc}", file=sys.stderr)

    print(f"\nWriteback done. Written: {written}, Skipped: {skipped}, Errors: {errors}")
    return 0 if errors == 0 else 2


def cmd_status(args) -> int:
    """Print recovery breakdown for a tab."""
    cols = dict(DEFAULT_COLS)
    cols["email"] = args.email_col
    cols["confidence"] = args.conf_col
    rng = f"'{args.tab}'!A1:O{args.max_rows}"
    rows = _sheets_read(args.sheet_id, rng)
    email_idx = _col_to_idx(cols["email"])
    conf_idx = _col_to_idx(cols["confidence"])
    business_idx = _col_to_idx(cols["business"])

    tally = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "NONE": 0, "empty": 0}
    total_leads = 0
    for i, row in enumerate(rows):
        if i == 0:
            continue
        padded = row + [""] * (15 - len(row))
        if not padded[business_idx].strip():
            continue
        total_leads += 1
        confidence = padded[conf_idx].strip()
        email = padded[email_idx].strip()
        if confidence in tally:
            tally[confidence] += 1
        elif email:
            tally["HIGH"] += 1  # email without confidence — assume HIGH
        else:
            tally["empty"] += 1

    recovered = tally["HIGH"] + tally["MEDIUM"] + tally["LOW"]
    print(f"Sheet: {args.tab}")
    print(f"Total leads: {total_leads}")
    print(f"  HIGH:   {tally['HIGH']:>4d}")
    print(f"  MEDIUM: {tally['MEDIUM']:>4d}")
    print(f"  LOW:    {tally['LOW']:>4d}")
    print(f"  NONE:   {tally['NONE']:>4d}")
    print(f"  empty:  {tally['empty']:>4d}")
    if total_leads:
        print(f"Recovery rate: {recovered}/{total_leads} ({100*recovered/total_leads:.1f}%)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    common_args = lambda sp: (
        sp.add_argument("--sheet-id", default=DEFAULT_SHEET_ID),
        sp.add_argument("--tab", required=True),
        sp.add_argument("--email-col", default=DEFAULT_COLS["email"]),
        sp.add_argument("--conf-col", default=DEFAULT_COLS["confidence"]),
        sp.add_argument("--source-col", default=DEFAULT_COLS["source"]),
        sp.add_argument("--max-rows", type=int, default=1000),
    )

    sp_audit = sub.add_parser("audit", help="Identify NONE/empty rows, emit work file")
    common_args(sp_audit)
    sp_audit.add_argument("--out", help="Output JSON path (default: /tmp/enrich_audit_<tab>.json)")

    sp_writeback = sub.add_parser("writeback", help="Write results JSON back to sheet")
    common_args(sp_writeback)
    sp_writeback.add_argument("--results", required=True, help="Path to results JSON")
    sp_writeback.add_argument("--include-none", action="store_true",
                              help="Also write NONE rows (with empty Email cell). Default: skip them.")

    sp_status = sub.add_parser("status", help="Print recovery breakdown")
    common_args(sp_status)

    args = p.parse_args()
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "writeback":
        return cmd_writeback(args)
    if args.cmd == "status":
        return cmd_status(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
