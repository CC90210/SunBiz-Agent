"""Offline SOP grader verification — no DB / network.

Runs grade_deal + build_metric_card on synthetic parser outputs and asserts
the data contract: every existing metric_card field plus the new SOP fields,
a JUNK/collections case grading JUNK (not D), and positioning_merchant_safe
containing no internal lender names.

  python tests/test_grader_sop.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from underwriting.grader import grade_deal, build_metric_card  # noqa: E402


# Existing contract fields the dashboard already consumes.
EXISTING_FIELDS = {
    "grade", "recommendation", "true_monthly_revenue", "excluded_credits_monthly",
    "revenue_note", "active_mca_positions", "mca_monthly_burden", "mca_leverage_pct",
    "estimated_total_mca_balance", "estimate_quality", "nsfs_90d",
    "negative_balance_days", "collections_flag", "target_lender_tier",
    "positions", "red_flags",
}
# New SOP fields the dashboard render is being built against.
NEW_FIELDS = {
    "gross_deposits_total", "positioning_merchant_safe", "grade_justification",
    "proposed_play", "collections", "other_debt", "avg_daily_balance",
    "time_in_business_months", "data_source", "review_period", "confidence_notes",
}

LENDER_NAMES = ["ondeck", "kapitus", "forward", "bluevine", "credibly", "fora", "cfg", "rapid"]


def _clean_bca_case() -> list[dict]:
    """A clean B-grade deal: ~$80k true revenue, 2 MCA positions, low NSF."""
    stmt = {
        "statement_period": {"start": "2026-03-01", "end": "2026-03-31"},
        "total_deposits": 95000,
        "average_daily_balance": 18000,
        "nsf_events": 1,
        "overdraft_days": 1,
        "excluded_credits": [
            {"amount": 15000, "category": "internal_transfer", "memo": "Transfer from savings"},
        ],
        "card_processor_deposits": [{"processor": "Square", "amount": 40000}],
        "identified_loan_payments": [
            {"lender_hint": "OnDeck Capital", "amount": 450, "frequency": "daily", "category": "mca_funder"},
            {"lender_hint": "Forward Financing", "amount": 1200, "frequency": "weekly", "category": "mca_funder"},
            {"lender_hint": "North Star Leasing", "amount": 800, "frequency": "monthly", "category": "equipment_lease"},
            {"lender_hint": "Quickbooks", "amount": 80, "frequency": "monthly", "category": "saas"},
        ],
    }
    return [dict(stmt), dict(stmt, statement_period={"start": "2026-04-01", "end": "2026-04-30"}),
            dict(stmt, statement_period={"start": "2026-05-01", "end": "2026-05-31"})]


def _junk_collections_case() -> list[dict]:
    """A JUNK deal: an MCA in collections (death-blow) + heavy stack."""
    stmt = {
        "statement_period": {"start": "2026-03-01", "end": "2026-03-31"},
        "total_deposits": 40000,
        "average_daily_balance": 1200,
        "nsf_events": 5,
        "overdraft_days": 9,
        "excluded_credits": [],
        "identified_loan_payments": [
            {"lender_hint": "ABC MCA Servicing LLC", "amount": 600, "frequency": "weekly",
             "category": "mca_servicer", "original_lender": "Yellowstone"},
            {"lender_hint": "Credibly", "amount": 500, "frequency": "daily", "category": "mca_funder"},
            {"lender_hint": "Fora Financial", "amount": 700, "frequency": "daily", "category": "mca_funder"},
            {"lender_hint": "MysteryCo 8001234567", "amount": 300, "frequency": "daily", "category": "unknown"},
        ],
    }
    return [dict(stmt), dict(stmt), dict(stmt)]


def _check_card(card: dict, label: str) -> list[str]:
    errs: list[str] = []
    missing_existing = EXISTING_FIELDS - card.keys()
    missing_new = NEW_FIELDS - card.keys()
    if missing_existing:
        errs.append(f"[{label}] MISSING existing contract fields: {sorted(missing_existing)}")
    if missing_new:
        errs.append(f"[{label}] MISSING new SOP fields: {sorted(missing_new)}")
    return errs


def main() -> int:
    errors: list[str] = []

    # ── Case 1: clean deal ──
    g1 = grade_deal(_clean_bca_case(), None, app_data={"time_in_business_months": 28},
                    data_source="upload")
    c1 = build_metric_card(g1)
    errors += _check_card(c1, "clean")
    if c1["grade"] not in ("A", "B", "C"):
        errors.append(f"[clean] expected A/B/C, got {c1['grade']}")
    if c1["collections_flag"]:
        errors.append("[clean] collections_flag should be False")
    if c1["active_mca_positions"] != 2:
        errors.append(f"[clean] expected 2 positions, got {c1['active_mca_positions']}")
    if not any(d["type"] == "equipment" for d in c1["other_debt"]):
        errors.append("[clean] equipment lease should route to other_debt")
    for pos in c1["positions"]:
        if "est_balance_is_estimated" not in pos or not pos["est_balance_is_estimated"]:
            errors.append("[clean] each position must carry est_balance_is_estimated=True")
        if "funded_date_confidence" not in pos:
            errors.append("[clean] each position must carry funded_date_confidence")

    # ── Case 2: JUNK / collections ──
    g2 = grade_deal(_junk_collections_case(), None, data_source="upload")
    c2 = build_metric_card(g2)
    errors += _check_card(c2, "junk")
    if c2["grade"] != "JUNK":
        errors.append(f"[junk] expected JUNK, got {c2['grade']}")
    if not c2["collections_flag"]:
        errors.append("[junk] collections_flag should be True")
    if not c2["collections"]:
        errors.append("[junk] collections[] should list the servicer")
    if c2["proposed_play"]["target_funder_tier_internal"] is not None:
        errors.append("[junk] JUNK must not carry a target funder tier")
    # Hard rule: positioning_merchant_safe must contain NO lender names.
    pos_safe = (c2["positioning_merchant_safe"] or "").lower()
    leaked = [n for n in LENDER_NAMES if n in pos_safe]
    if leaked:
        errors.append(f"[junk] positioning_merchant_safe leaked lender name(s): {leaked}")
    # Also check the clean case positioning for leaks.
    pos_safe1 = (c1["positioning_merchant_safe"] or "").lower()
    leaked1 = [n for n in LENDER_NAMES if n in pos_safe1]
    if leaked1:
        errors.append(f"[clean] positioning_merchant_safe leaked lender name(s): {leaked1}")

    print("=" * 70)
    print("CLEAN CASE metric_card:")
    print(json.dumps(c1, indent=2, default=str))
    print("=" * 70)
    print("JUNK/COLLECTIONS CASE metric_card:")
    print(json.dumps(c2, indent=2, default=str))
    print("=" * 70)

    if errors:
        print("FAIL:")
        for e in errors:
            print("  - " + e)
        return 1
    print("PASS — all SOP contract assertions hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
