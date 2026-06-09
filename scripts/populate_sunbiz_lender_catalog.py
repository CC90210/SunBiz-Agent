"""populate_sunbiz_lender_catalog.py — load the SOP-curated SunBiz lender
catalog into `tenant_records` so the dashboard's /lenders directory and
the Shopping Out tab render every funder from `Lender List SOP.pdf`.

This is the SHOP-OUT registry populate path. It is NOT the same as
`import_lender_catalog.py`, which writes to `known_funding_companies`
for `statement_parser.py` to match ACH memos against. The two tables
serve different parts of the stack:

  - known_funding_companies  ← statement parsing / debt detection
  - tenant_records           ← shop-out UI + match-fitness scorer

The shop-out registry needs the structured SOP fields (tier,
paper_grades, position range, defaults policy, max negative days,
reverses-only flag) so the `shop_list(deal)` filter in SOP §1 narrows
lenders to those whose hard requirements the deal actually meets.

  --- Source of truth ---

  data/sunbiz_lender_catalog.json — hand-curated from Lender List SOP.pdf
  (last refreshed 2026-05-29). When SunBiz updates a lender's box, edit
  the JSON and re-run this script.

  --- Usage ---

    # Dry-run — validate + preview without writing:
    python scripts/populate_sunbiz_lender_catalog.py \\
        --file data/sunbiz_lender_catalog.json --dry-run

    # Real (idempotent — deterministic UUIDs mean re-running upserts
    # the same rows):
    python scripts/populate_sunbiz_lender_catalog.py \\
        --file data/sunbiz_lender_catalog.json

    # Replace mode — delete every existing lender row for the SunBiz
    # tenant before inserting. Use when populating fresh / clearing test
    # rows:
    python scripts/populate_sunbiz_lender_catalog.py \\
        --file data/sunbiz_lender_catalog.json --replace

    # Machine output for daemon callers / CI:
    python scripts/populate_sunbiz_lender_catalog.py --file ... --json

  --- Guarantees ---

  - Idempotent. Row id is uuid5(NAMESPACE_DNS, "sunbiz-lender-"+slug(name)),
    so re-running with the same JSON upserts the same rows.
  - Dry-run never opens a Supabase connection — purely client-side
    validation + preview.
  - Service-role credentials only — script runs on the operator's bridge
    / VPS, never in browser context.
  - `--replace` deletes ALL entity_type='lender' rows for the SunBiz
    tenant before inserting. Other tenants are untouched.

  --- Exit codes ---
    0  — populated cleanly (or dry-run validation passed)
    1  — file read / parse error
    2  — validation failures (some rows rejected)
    3  — Supabase connection / write failure
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# CEO-Agent holds the canonical Bravo agent env (BRAVO_SUPABASE_URL +
# service-role key). SunBiz-Agent may also have its own .env.agents but
# typically doesn't carry the cross-tenant service-role credentials.
# Search CEO-Agent first; merge SunBiz-Agent keys on top of it so an
# operator-set override wins if present.
ENV_SEARCH_PATHS = [
    PROJECT_ROOT.parent / "CEO-Agent" / ".env.agents",
    PROJECT_ROOT / ".env.agents",
]

# SunBiz tenant id — single source of truth in sunbiz_constants.py.
from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402

# Namespace UUID for deterministic lender row ids. Stable across runs
# so re-importing the catalog upserts rather than duplicates.
LENDER_ID_NAMESPACE = uuid.NAMESPACE_DNS

# Field-level validation gates the JSON before it touches Supabase.
VALID_TIERS = {"A", "B", "C", "D", "Micro"}
VALID_PAPER_GRADES = {"A", "B", "C", "D", "JUNK"}
VALID_DEFAULTS_POLICIES = {"none", "satisfied_only", "accepts"}


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def load_env() -> dict[str, str]:
    """Load .env.agents into a dict. Merges from every search path that
    exists, with EARLIER paths winning (CEO-Agent canonical first; any
    SunBiz-Agent override second). No `break` — both files contribute so
    a partial sibling .env.agents doesn't shadow the canonical one."""
    env: dict[str, str] = {}
    for path in ENV_SEARCH_PATHS:
        if not path.exists():
            continue
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def get_supabase(env: dict[str, str]):
    """Lazy import + service-role client. Same pattern as the sibling
    import script — uses BRAVO_SUPABASE_URL / SUNBIZ_SUPABASE_URL with
    service-role key. Service role is required because the script writes
    across tenant boundaries (RLS would otherwise block)."""
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


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """ASCII-only slug for deterministic UUID derivation. Matches the
    pattern used by `lib/manifest/seeds.ts` slug generation so lender
    ids stay consistent if/when the dashboard ever generates them
    server-side too."""
    s = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return s or "unnamed"


def lender_row_id(name: str) -> str:
    """Deterministic UUID v5 from the lender name. Re-running this
    script with the same name produces the same id, so the upsert
    actually upserts instead of duplicating."""
    return str(uuid.uuid5(LENDER_ID_NAMESPACE, f"sunbiz-lender-{slugify(name)}"))


# ─────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────


def validate_lender(lender: dict[str, Any], idx: int) -> list[str]:
    """Return a list of validation errors for one lender entry. Empty
    list means the row is fit to send to Supabase."""
    errors: list[str] = []
    name = lender.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"#{idx}: missing or empty 'name'")
        return errors  # nothing else makes sense without a name

    tier = lender.get("tier")
    if tier is not None and tier not in VALID_TIERS:
        errors.append(f"#{idx} ({name}): tier '{tier}' not in {sorted(VALID_TIERS)}")

    grades = lender.get("paper_grades")
    if grades is not None:
        if not isinstance(grades, list):
            errors.append(f"#{idx} ({name}): paper_grades must be an array")
        else:
            bad = [g for g in grades if g not in VALID_PAPER_GRADES]
            if bad:
                errors.append(
                    f"#{idx} ({name}): unknown paper grade(s) {bad}"
                )

    dp = lender.get("defaults_policy")
    if dp is not None and dp not in VALID_DEFAULTS_POLICIES:
        errors.append(
            f"#{idx} ({name}): defaults_policy '{dp}' not in {sorted(VALID_DEFAULTS_POLICIES)}"
        )

    contact = lender.get("contact")
    if contact is not None and contact != "":
        if not isinstance(contact, str) or "@" not in contact or "." not in contact.split("@", 1)[-1]:
            errors.append(f"#{idx} ({name}): contact '{contact}' doesn't look like an email")

    ccs = lender.get("submission_cc_emails")
    if ccs is not None:
        if not isinstance(ccs, list):
            errors.append(f"#{idx} ({name}): submission_cc_emails must be an array")
        else:
            for cc in ccs:
                if not isinstance(cc, str) or "@" not in cc:
                    errors.append(f"#{idx} ({name}): bad cc email '{cc}'")

    for nf in ("position_min", "position_max", "max_negative_days", "fico_floor",
               "min_monthly_revenue", "max_funded_amount"):
        v = lender.get(nf)
        if v is not None and not isinstance(v, (int, float)):
            errors.append(f"#{idx} ({name}): {nf} must be a number")

    for af in ("restricted_states", "industry_restrictions", "industry_preferences"):
        v = lender.get(af)
        if v is not None and not isinstance(v, list):
            errors.append(f"#{idx} ({name}): {af} must be an array")

    return errors


# ─────────────────────────────────────────────────────────────────────
# Load
# ─────────────────────────────────────────────────────────────────────


def load_catalog(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("lenders"), list):
        return list(data["lenders"])
    if isinstance(data, list):
        return data
    raise ValueError(
        "JSON file must contain a top-level array OR {lenders: [...]} object"
    )


# ─────────────────────────────────────────────────────────────────────
# Supabase writes
# ─────────────────────────────────────────────────────────────────────


def delete_existing_lenders(supa) -> int:
    """Hard-delete every entity_type='lender' row for the SunBiz tenant.
    Other tenants are untouched. Returns the count of rows deleted."""
    pre = (
        supa.table("tenant_records")
        .select("id", count="exact")
        .eq("tenant_id", SUNBIZ_TENANT_ID)
        .eq("entity_type", "lender")
        .execute()
    )
    count_before = pre.count or 0
    if count_before == 0:
        return 0
    supa.table("tenant_records").delete().eq(
        "tenant_id", SUNBIZ_TENANT_ID
    ).eq("entity_type", "lender").execute()
    return count_before


def upsert_lenders(supa, lenders: list[dict[str, Any]]) -> int:
    """Upsert one tenant_records row per lender. on_conflict on the
    primary key column id — deterministic UUIDs mean each lender always
    targets the same row."""
    payloads = []
    for lender in lenders:
        name = lender["name"]
        # Strip the meta fields the JSON file uses for indexing; ship
        # everything else into the JSONB data column. Keys not in the
        # entity schema are tolerated — the dashboard just ignores them.
        data = {k: v for k, v in lender.items() if k != "_meta"}
        payloads.append({
            "id": lender_row_id(name),
            "tenant_id": SUNBIZ_TENANT_ID,
            "entity_type": "lender",
            "data": data,
        })
    if not payloads:
        return 0
    res = supa.table("tenant_records").upsert(
        payloads, on_conflict="id"
    ).execute()
    return len(res.data) if res.data else len(payloads)


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="populate_sunbiz_lender_catalog",
        description="Populate tenant_records with the SunBiz lender catalog from the SOP doc.",
    )
    parser.add_argument(
        "--file",
        required=True,
        type=Path,
        help="Path to the lender catalog JSON (data/sunbiz_lender_catalog.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + preview without writing to Supabase.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete all existing SunBiz lender rows before inserting.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result on stdout.",
    )
    args = parser.parse_args()

    if not args.file.exists():
        sys.stderr.write(f"ERROR: file not found: {args.file}\n")
        return 1

    try:
        lenders = load_catalog(args.file)
    except (ValueError, json.JSONDecodeError) as e:
        sys.stderr.write(f"ERROR: failed to parse {args.file}: {e}\n")
        return 1
    if not lenders:
        sys.stderr.write("ERROR: catalog contains zero lenders\n")
        return 1

    all_errors: list[str] = []
    for i, lender in enumerate(lenders, start=1):
        all_errors.extend(validate_lender(lender, i))

    if not args.json:
        sys.stdout.write(
            f"[lender_catalog] parsed {len(lenders)} lenders from {args.file.name}\n"
        )
        tiers: dict[str, int] = {}
        for l in lenders:
            t = l.get("tier", "?")
            tiers[t] = tiers.get(t, 0) + 1
        sys.stdout.write(
            "  by tier: "
            + ", ".join(f"{t}={n}" for t, n in sorted(tiers.items()))
            + "\n"
        )
        if all_errors:
            sys.stdout.write(f"  validation errors: {len(all_errors)}\n")
            for e in all_errors:
                sys.stderr.write(f"  ! {e}\n")

    if args.dry_run:
        if args.json:
            sys.stdout.write(json.dumps({
                "ok": len(all_errors) == 0,
                "dry_run": True,
                "parsed": len(lenders),
                "errors": all_errors,
            }) + "\n")
        else:
            sys.stdout.write("[lender_catalog] DRY-RUN: no Supabase writes.\n")
        return 0 if not all_errors else 2

    if all_errors:
        # Refuse to write a partially-valid catalog — the SOP is one
        # cohesive document, so a typo in one row should block the
        # whole import until corrected.
        sys.stderr.write(
            "Refusing to write: catalog has validation errors. "
            "Fix them and re-run.\n"
        )
        return 2

    env = load_env()
    supa = get_supabase(env)

    deleted = 0
    if args.replace:
        try:
            deleted = delete_existing_lenders(supa)
        except Exception as e:
            sys.stderr.write(f"ERROR: delete-existing failed: {e}\n")
            return 3

    try:
        written = upsert_lenders(supa, lenders)
    except Exception as e:
        sys.stderr.write(f"ERROR: Supabase upsert failed: {e}\n")
        return 3

    if args.json:
        sys.stdout.write(json.dumps({
            "ok": True,
            "dry_run": False,
            "parsed": len(lenders),
            "written": written,
            "deleted": deleted,
            "tenant_id": SUNBIZ_TENANT_ID,
        }) + "\n")
    else:
        if args.replace:
            sys.stdout.write(
                f"[lender_catalog] deleted {deleted} existing lender row(s).\n"
            )
        sys.stdout.write(
            f"[lender_catalog] wrote {written} row(s) to tenant_records (tenant=SunBiz).\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
