"""import_lender_catalog.py — bulk import / update known_funding_companies.

The MCA biller registry that statement_parser.py + debt_detector.py rely on
to identify existing lender positions on bank statements. Migration 069
seeded an initial 18 rows + migration 071 added 22 more with tier metadata,
which gets every SunBiz deal that's currently in the pipeline correctly
classified. This script is the bulk-update path for when:

  1. Adon ships his full BUSINESS_CONTEXT/LENDER_LIST.csv (40+ rows) or
     mca_biller_database.json (300+ rows).
  2. An operator notices a new lender appearing on statements (e.g.
     "STARFUND DAILY DEBIT $487") that none of the known patterns
     classify. They add it via a CSV row and re-run this script.
  3. Periodic refresh of contact_email / submission_notes when funders
     change reply-to addresses.

  --- CSV / JSON expected shape ---

CSV columns (header row required; column order flexible):
    name                       (required, text, unique key)
    aliases                    (optional, comma-separated)
    industry_signal_keywords   (optional, comma-separated — used by
                                statement_parser to match ACH memos)
    category                   (optional, 'mca' | 'loc' | 'term_loan')
    tier                       (optional, 1-4 — Adon §10 priority)
    typical_term_days          (optional, int)
    typical_buy_rate_min       (optional, decimal like 1.30)
    typical_buy_rate_max       (optional, decimal like 1.50)
    paper_grades_accepted      (optional, comma-separated A/B/C/D/JUNK)
    contact_email              (optional, lender submission address)
    submission_notes           (optional, free text)
    website                    (optional)

JSON shape: { "lenders": [ { ...same field names... }, ... ] }

  --- Usage ---

    # Dry-run (validate without writing):
    python scripts/import_lender_catalog.py --file data/lender_catalog.csv --dry-run

    # Real import (idempotent — re-running is safe):
    python scripts/import_lender_catalog.py --file data/lender_catalog.csv

    # JSON file:
    python scripts/import_lender_catalog.py --file path/to/mca_biller_database.json

    # Machine output for daemon callers:
    python scripts/import_lender_catalog.py --file ... --json

  --- Guarantees ---

  - Idempotent. Re-running with the same CSV doesn't duplicate rows.
    Uses INSERT ... ON CONFLICT (name) DO UPDATE.
  - Validates every row's category + tier + paper_grades_accepted before
    sending. Invalid rows are reported but don't block the rest of the
    file.
  - Dry-run never opens a Supabase connection — purely client-side
    validation + preview output.
  - Service-role credentials only — this script lives in the agent repo,
    runs on the operator's bridge / VPS, never in browser context.

  --- Exit codes ---
    0  — all rows imported (or dry-run validation passed)
    1  — file read / parse error
    2  — validation failures (some rows rejected)
    3  — Supabase connection / write failure
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env.agents"

# ─────────────────────────────────────────────────────────────────────
# Validation constants
# ─────────────────────────────────────────────────────────────────────

VALID_CATEGORIES = {"mca", "loc", "term_loan"}
VALID_TIERS = {1, 2, 3, 4}
VALID_GRADES = {"A", "B", "C", "D", "JUNK"}

REQUIRED_FIELDS = {"name"}

# Acceptable input column names → canonical DB column name. Lets the
# script tolerate Adon's exact CSV header names without manual cleanup.
COLUMN_ALIASES = {
    "lender_name": "name",
    "funder_name": "name",
    "company": "name",
    "biller_name": "name",
    "aka": "aliases",
    "also_known_as": "aliases",
    "keywords": "industry_signal_keywords",
    "ach_keywords": "industry_signal_keywords",
    "memo_patterns": "industry_signal_keywords",
    "type": "category",
    "product_type": "category",
    "priority_tier": "tier",
    "submission_tier": "tier",
    "term_days": "typical_term_days",
    "term": "typical_term_days",
    "factor_min": "typical_buy_rate_min",
    "factor_max": "typical_buy_rate_max",
    "min_factor": "typical_buy_rate_min",
    "max_factor": "typical_buy_rate_max",
    "buy_rate_min": "typical_buy_rate_min",
    "buy_rate_max": "typical_buy_rate_max",
    "grades": "paper_grades_accepted",
    "accepts": "paper_grades_accepted",
    "email": "contact_email",
    "submission_email": "contact_email",
    "notes": "submission_notes",
    "url": "website",
}

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def load_env() -> dict[str, str]:
    """Load .env.agents into a dict. Never reads it into a global."""
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    with ENV_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_supabase(env: dict[str, str]):
    """Lazy import — avoids forcing supabase-py on every CLI invocation."""
    try:
        from supabase import create_client  # type: ignore
    except ImportError:
        sys.stderr.write(
            "ERROR: supabase-py not installed. Run: pip install supabase\n"
        )
        sys.exit(3)
    url = env.get("BRAVO_SUPABASE_URL") or env.get("SUNBIZ_SUPABASE_URL")
    key = env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or env.get(
        "SUNBIZ_SUPABASE_SERVICE_ROLE_KEY"
    )
    if not url or not key:
        sys.stderr.write(
            "ERROR: missing BRAVO_SUPABASE_URL or service-role key in .env.agents\n"
        )
        sys.exit(3)
    return create_client(url, key)


def _split_array(value: Any) -> Optional[list[str]]:
    """Normalise comma-separated / pipe-separated / list inputs to a clean
    list of strings. Returns None when the value is empty/None — Postgres
    column defaults to [] so None lets the DB choose."""
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    s = str(value).strip()
    if not s:
        return None
    # Try CSV first (commas), fall back to pipes, then semicolons.
    for sep in (",", "|", ";"):
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if parts:
                return parts
    return [s]


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None


def _to_decimal(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────
# Row normalisation + validation
# ─────────────────────────────────────────────────────────────────────


@dataclass
class NormalizedRow:
    """Validated + DB-shaped lender row. None values get sent as-is so
    the column defaults kick in server-side."""

    name: str
    aliases: Optional[list[str]] = None
    industry_signal_keywords: Optional[list[str]] = None
    category: Optional[str] = None
    tier: Optional[int] = None
    typical_term_days: Optional[int] = None
    typical_buy_rate_min: Optional[float] = None
    typical_buy_rate_max: Optional[float] = None
    paper_grades_accepted: Optional[list[str]] = None
    contact_email: Optional[str] = None
    submission_notes: Optional[str] = None
    website: Optional[str] = None
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_db_payload(self) -> dict[str, Any]:
        """Drop None values so we don't send NULL on upsert and clobber
        previously-set columns when the new CSV omits them."""
        payload: dict[str, Any] = {"name": self.name}
        for f_name in (
            "aliases",
            "industry_signal_keywords",
            "category",
            "tier",
            "typical_term_days",
            "typical_buy_rate_min",
            "typical_buy_rate_max",
            "paper_grades_accepted",
            "contact_email",
            "submission_notes",
            "website",
        ):
            v = getattr(self, f_name)
            if v is not None:
                payload[f_name] = v
        return payload


def normalize_row(raw: dict[str, Any], line: int) -> NormalizedRow:
    """Convert one input row into a NormalizedRow + validate each field.
    Tolerates Adon's CSV column-name variants via COLUMN_ALIASES."""

    # Resolve aliases — input keys may be 'lender_name', 'funder_name', etc.
    canonical: dict[str, Any] = {}
    for raw_key, raw_val in raw.items():
        if raw_key is None:
            continue
        key = raw_key.strip().lower().replace(" ", "_")
        key = COLUMN_ALIASES.get(key, key)
        canonical[key] = raw_val

    name = (canonical.get("name") or "").strip()
    if not name:
        return NormalizedRow(name="", errors=[f"line {line}: missing required 'name' column"])

    row = NormalizedRow(name=name)

    row.aliases = _split_array(canonical.get("aliases"))
    row.industry_signal_keywords = _split_array(canonical.get("industry_signal_keywords"))

    # category — uppercase tolerance
    cat = canonical.get("category")
    if cat:
        cat_s = str(cat).strip().lower()
        if cat_s in VALID_CATEGORIES:
            row.category = cat_s
        else:
            row.errors.append(
                f"line {line} ({name}): invalid category '{cat}' (must be one of {sorted(VALID_CATEGORIES)})"
            )

    tier = _to_int(canonical.get("tier"))
    if tier is not None:
        if tier in VALID_TIERS:
            row.tier = tier
        else:
            row.errors.append(
                f"line {line} ({name}): tier {tier} out of range (must be 1-4 per Adon §10)"
            )

    row.typical_term_days = _to_int(canonical.get("typical_term_days"))
    if row.typical_term_days is not None and (row.typical_term_days < 30 or row.typical_term_days > 730):
        row.errors.append(
            f"line {line} ({name}): typical_term_days {row.typical_term_days} outside reasonable range 30-730"
        )

    row.typical_buy_rate_min = _to_decimal(canonical.get("typical_buy_rate_min"))
    row.typical_buy_rate_max = _to_decimal(canonical.get("typical_buy_rate_max"))
    if (row.typical_buy_rate_min is not None and row.typical_buy_rate_max is not None
            and row.typical_buy_rate_min > row.typical_buy_rate_max):
        row.errors.append(
            f"line {line} ({name}): buy_rate_min ({row.typical_buy_rate_min}) > buy_rate_max ({row.typical_buy_rate_max})"
        )

    grades = _split_array(canonical.get("paper_grades_accepted"))
    if grades:
        grades_upper = [g.upper() for g in grades]
        bad = [g for g in grades_upper if g not in VALID_GRADES]
        if bad:
            row.errors.append(
                f"line {line} ({name}): unknown paper grade(s) {bad} (valid: {sorted(VALID_GRADES)})"
            )
        else:
            row.paper_grades_accepted = grades_upper

    email = canonical.get("contact_email")
    if email and isinstance(email, str) and email.strip():
        # Basic shape check — not a full RFC 5322 parse, just gate the
        # obvious junk so we don't ship "n/a" or "TBD" into the column.
        if "@" not in email or "." not in email.split("@", 1)[-1]:
            row.errors.append(f"line {line} ({name}): contact_email '{email}' doesn't look like an email")
        else:
            row.contact_email = email.strip()

    notes = canonical.get("submission_notes")
    if notes and str(notes).strip():
        row.submission_notes = str(notes).strip()

    website = canonical.get("website")
    if website and str(website).strip():
        row.website = str(website).strip()

    return row


# ─────────────────────────────────────────────────────────────────────
# File loaders
# ─────────────────────────────────────────────────────────────────────


def load_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "lenders" in data:
        return list(data["lenders"])
    if isinstance(data, dict) and "billers" in data:
        # Adon's mca_biller_database.json shape uses 'billers'.
        return list(data["billers"])
    if isinstance(data, list):
        return data
    raise ValueError(
        "JSON file must contain a top-level array OR {lenders: [...]} / {billers: [...]} object"
    )


def load_input(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv(path)
    if suffix in (".json", ".jsonl"):
        return load_json(path)
    raise ValueError(f"unsupported file type {suffix!r} (need .csv or .json)")


# ─────────────────────────────────────────────────────────────────────
# Import
# ─────────────────────────────────────────────────────────────────────


def upsert_rows(supa, rows: list[NormalizedRow]) -> tuple[int, int]:
    """Returns (inserted, updated). Uses Supabase upsert which doesn't
    distinguish; we report sum as written = total rows attempted."""
    valid = [r for r in rows if r.valid]
    if not valid:
        return 0, 0
    payloads = [r.to_db_payload() for r in valid]
    # Single batched upsert — Supabase handles row-level constraint
    # checks server-side. on_conflict='name' uses the UNIQUE index from
    # migration 069.
    res = supa.table("known_funding_companies").upsert(payloads, on_conflict="name").execute()
    written = len(res.data) if res.data else len(valid)
    return written, 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="import_lender_catalog",
        description="Bulk import / update known_funding_companies from CSV or JSON.",
    )
    parser.add_argument("--file", required=True, type=Path, help="Path to CSV or JSON input.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + preview without writing to Supabase.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result on stdout (one object).",
    )
    args = parser.parse_args()

    if not args.file.exists():
        sys.stderr.write(f"ERROR: file not found: {args.file}\n")
        return 1

    try:
        raw_rows = load_input(args.file)
    except (ValueError, json.JSONDecodeError) as e:
        sys.stderr.write(f"ERROR: failed to parse {args.file}: {e}\n")
        return 1
    if not raw_rows:
        sys.stderr.write("ERROR: input file contains zero rows\n")
        return 1

    normalized = [normalize_row(r, i + 2) for i, r in enumerate(raw_rows)]
    valid = [r for r in normalized if r.valid]
    invalid = [r for r in normalized if not r.valid]

    if not args.json:
        sys.stdout.write(
            f"[lender_catalog] parsed {len(normalized)} rows from {args.file.name}\n"
        )
        sys.stdout.write(
            f"  valid:   {len(valid)}\n"
            f"  invalid: {len(invalid)}\n"
        )
        for r in invalid:
            for err in r.errors:
                sys.stderr.write(f"  ! {err}\n")

    if args.dry_run:
        if not args.json:
            sys.stdout.write("[lender_catalog] DRY-RUN: no Supabase writes.\n")
            if valid[:3]:
                sys.stdout.write("  preview (first 3):\n")
                for r in valid[:3]:
                    sys.stdout.write(f"    - {r.name} (tier={r.tier}, grades={r.paper_grades_accepted})\n")
        if args.json:
            sys.stdout.write(json.dumps({
                "ok": len(invalid) == 0,
                "dry_run": True,
                "parsed": len(normalized),
                "valid": len(valid),
                "invalid": len(invalid),
                "errors": [e for r in invalid for e in r.errors],
            }) + "\n")
        return 0 if not invalid else 2

    # Real import path
    env = load_env()
    supa = get_supabase(env)
    try:
        written, _ = upsert_rows(supa, valid)
    except Exception as e:
        sys.stderr.write(f"ERROR: Supabase upsert failed: {e}\n")
        return 3

    if args.json:
        sys.stdout.write(json.dumps({
            "ok": len(invalid) == 0,
            "dry_run": False,
            "parsed": len(normalized),
            "valid": len(valid),
            "invalid": len(invalid),
            "written": written,
            "errors": [e for r in invalid for e in r.errors],
        }) + "\n")
    else:
        sys.stdout.write(f"[lender_catalog] wrote {written} rows to known_funding_companies.\n")
        if invalid:
            sys.stdout.write(f"  {len(invalid)} row(s) skipped due to validation errors (see stderr).\n")

    return 0 if not invalid else 2


if __name__ == "__main__":
    sys.exit(main())
