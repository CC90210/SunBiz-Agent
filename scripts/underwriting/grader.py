"""grader.py — Adon MCA SOP grading + sales metric card.

Per SOP_underwriting_for_ccs.md §§3, 5, 6, 7 (Adon/APEX, 2026-06-11).
Consumes the output of statement_parser + debt_detector, produces the
sales-focused metric card the agent reads in 3 seconds before pitching.

Public surface:
  grade_deal(parser_outputs, debt_summary) -> dict   # full grading result
  build_metric_card(grading) -> dict                  # SOP §7 card shape

Pure functions. No DB / network. Orchestrator calls into this after
debt_detector and persists the result alongside the debt summary.

Hard SOP rules enforced here (won't drift on subsequent edits):

  1. TRUE revenue excludes transfers, MCA funding wires, loan advances,
     owner injections, refunds, tax refunds, insurance payouts.
     Falls back to total_deposits when the parser hasn't been upgraded
     to extract excluded_credits — flagged via `revenue_estimation` field
     so the operator knows the number is an upper bound, not net.

  2. Positions count ONLY when the biller is a verified MCA funder
     (category=='mca_funder'). Servicer/collections rows = DEATH-BLOW
     flag, override grade to JUNK regardless of leverage.

  3. Grade table (SOP §6):
       A     leverage < 25%   NSFs 0-1   positions 0-1
       B     25% - 45%        1-3        1-2
       C     45% - 70%        3-6        3-4
       D     70% - 100%       6+         5+
       JUNK  > 100% OR any MCA in collections

  4. Recommendation (SOP §7 header row):
       A          → Fresh capital
       B          → Fresh capital
       C          → Consolidation
       D          → Workout
       JUNK       → Decline (refer to restructure)

  5. Target lender tier follows grade letter for shop-out matching:
       A → A-paper tier   (premium funders, best terms)
       B → B-paper tier
       C → C-paper tier
       D → D-paper tier
       JUNK → no tier — don't shop, refer to restructure.
"""

from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────
# Excluded-credit categories (SOP §3)
# ─────────────────────────────────────────────────────────────────────

# Categories the parser tags excluded_credits[] entries with.
# Anything in this set gets subtracted from total_deposits to compute
# TRUE revenue. Backward-compat: when the parser hasn't been upgraded
# to emit these, the field is empty and TRUE revenue == total_deposits
# (with `revenue_estimation` field flagging it as an upper bound).
EXCLUDED_CREDIT_CATEGORIES: frozenset[str] = frozenset({
    "internal_transfer",
    "mca_funding",
    "loan_advance",
    "owner_injection",
    "trust_inheritance",
    "refund_reversal",
    "tax_refund",
    "insurance_payout",
})


# ─────────────────────────────────────────────────────────────────────
# Frequency normalization (SOP §5 — daily ~21.7, weekly ~4.33)
# ─────────────────────────────────────────────────────────────────────

_FREQ_MONTHLY_MULTIPLIER: dict[str, float] = {
    "daily": 21.7,    # SOP spec — business days/month
    "weekly": 4.33,   # SOP spec
    "bi-weekly": 2.17,
    "biweekly": 2.17,
    "monthly": 1.0,
}


def _to_monthly(amount: float, frequency: str | None) -> float:
    if not frequency:
        return amount  # conservative: assume monthly
    mult = _FREQ_MONTHLY_MULTIPLIER.get(frequency.lower().strip())
    return amount * (mult if mult is not None else 1.0)


# ─────────────────────────────────────────────────────────────────────
# Revenue + leverage (SOP §3, §6)
# ─────────────────────────────────────────────────────────────────────


def compute_true_monthly_revenue(parser_outputs: list[dict]) -> dict:
    """SOP §3: TRUE revenue = total_deposits − Σ excluded_credits.

    Returns {avg, excluded, source} where:
      avg: average TRUE monthly revenue across statements
      excluded: average excluded credits per statement (for display)
      source: 'parser_classified' when the parser tagged categories;
              'deposits_unfiltered' when we fell back to raw deposits.
              The metric card surfaces this so the agent knows whether
              the number is conservative-net or optimistic-gross.
    """
    if not parser_outputs:
        return {"avg": 0.0, "excluded": 0.0, "source": "deposits_unfiltered"}

    deposits_sum = 0.0
    excluded_sum = 0.0
    saw_classified = False

    for stmt in parser_outputs:
        deposits_sum += float(stmt.get("total_deposits") or 0)
        # New (post-SOP) parser shape: excluded_credits is a list of
        # {amount, category}. Sum the ones in EXCLUDED_CREDIT_CATEGORIES.
        excluded = stmt.get("excluded_credits") or []
        if excluded:
            saw_classified = True
            for entry in excluded:
                category = str(entry.get("category") or "").strip().lower()
                if category in EXCLUDED_CREDIT_CATEGORIES:
                    excluded_sum += float(entry.get("amount") or 0)

    n = len(parser_outputs)
    avg_revenue = (deposits_sum - excluded_sum) / n
    avg_excluded = excluded_sum / n
    return {
        "avg": max(0.0, round(avg_revenue, 2)),
        "excluded": round(avg_excluded, 2),
        "source": "parser_classified" if saw_classified else "deposits_unfiltered",
    }


# ─────────────────────────────────────────────────────────────────────
# Position verification (SOP §4)
# ─────────────────────────────────────────────────────────────────────


def verify_positions(parser_outputs: list[dict]) -> dict:
    """SOP §4: a position counts ONLY when the biller is a verified MCA
    funder. Servicer/collections = DEATH-BLOW. Equipment/SaaS/utility =
    NOT a position (separate buckets). Unknown = flag, do not count.

    Returns {
      positions: list[dict],          # verified MCA funder rows only
      monthly_burden: float,            # sum of positions' monthly equivalents
      collections_flag: bool,           # any 'mca_servicer' / collections seen
      equipment_lease_count: int,
      unknown_flags: list[str],         # billers we couldn't classify
    }
    """
    by_lender: dict[str, dict] = {}
    collections_flag = False
    equipment_lease_count = 0
    unknown_flags: list[str] = []

    for stmt in parser_outputs:
        for entry in stmt.get("identified_loan_payments") or []:
            lender_hint = str(entry.get("lender_hint") or "unknown").strip()
            category = str(entry.get("category") or "").strip().lower()
            amount = float(entry.get("amount") or 0)
            frequency = entry.get("frequency") or "monthly"
            monthly_eq = _to_monthly(amount, frequency)

            # SOP §4 classification dispatch.
            if category == "mca_servicer" or "collection" in lender_hint.lower() or "servicing" in lender_hint.lower():
                collections_flag = True
                continue
            if category == "equipment_lease":
                equipment_lease_count += 1
                continue
            if category in {"saas", "processor", "utility", "insurance", "auto_loan"}:
                # Operating expense, not a position. Skip silently.
                continue
            if category == "" or category == "unknown":
                # SOP §4 hard rule: "if you can't verify the name is an
                # MCA company, it is NOT a position." Flag for human
                # review; do NOT count toward burden.
                unknown_flags.append(lender_hint)
                continue
            if category != "mca_funder":
                # Defensive — any other tag falls through to unclassified
                # rather than silently counting as a position.
                unknown_flags.append(f"{lender_hint} (category={category})")
                continue

            # Verified MCA funder. Group by lower-cased hint so same-lender
            # rows across multiple statements collapse to one position.
            key = lender_hint.lower()
            row = by_lender.setdefault(key, {
                "lender_hint": lender_hint,
                "monthly_estimate": 0.0,
                "occurrences": 0,
                "frequencies": set(),
            })
            row["monthly_estimate"] += monthly_eq
            row["occurrences"] += 1
            row["frequencies"].add(frequency)

    # Average across statements so the "monthly burden" reflects ONE
    # representative month, not the cumulative across the window.
    n = max(1, len(parser_outputs))
    positions: list[dict] = []
    monthly_burden = 0.0
    for row in by_lender.values():
        avg_monthly = row["monthly_estimate"] / n
        monthly_burden += avg_monthly
        positions.append({
            "lender_hint": row["lender_hint"],
            "estimated_monthly_payment": round(avg_monthly, 2),
            "observed_in_statements": row["occurrences"],
            "frequencies_observed": sorted(row["frequencies"]),
        })
    positions.sort(key=lambda r: r["estimated_monthly_payment"], reverse=True)

    return {
        "positions": positions,
        "monthly_burden": round(monthly_burden, 2),
        "collections_flag": collections_flag,
        "equipment_lease_count": equipment_lease_count,
        "unknown_flags": unknown_flags,
    }


# ─────────────────────────────────────────────────────────────────────
# Grade table (SOP §6)
# ─────────────────────────────────────────────────────────────────────


def assign_grade(
    leverage: float,
    nsfs_per_month: float,
    position_count: int,
    collections_flag: bool,
) -> tuple[str, str]:
    """SOP §6 grade table. Returns (grade, recommendation).

    Any collections flag overrides leverage/positions and forces JUNK +
    Decline — "no funder touches a merchant in active MCA collections."
    """
    if collections_flag or leverage > 1.0:
        return ("JUNK", "Decline — refer to restructure")

    # SOP §6 thresholds. Use the WORST of the three dimensions to grade
    # so a clean leverage with 6 NSFs doesn't grade A.
    leverage_grade = _grade_from_leverage(leverage)
    nsf_grade = _grade_from_nsfs(nsfs_per_month)
    pos_grade = _grade_from_positions(position_count)

    # Take the worst (alphabetically latest letter).
    grade = max(leverage_grade, nsf_grade, pos_grade)

    recommendation = {
        "A": "Fresh capital",
        "B": "Fresh capital",
        "C": "Consolidation",
        "D": "Workout",
    }.get(grade, "Decline")

    return (grade, recommendation)


def _grade_from_leverage(leverage: float) -> str:
    if leverage < 0.25:
        return "A"
    if leverage < 0.45:
        return "B"
    if leverage < 0.70:
        return "C"
    return "D"


def _grade_from_nsfs(nsfs_per_month: float) -> str:
    if nsfs_per_month <= 1:
        return "A"
    if nsfs_per_month <= 3:
        return "B"
    if nsfs_per_month <= 6:
        return "C"
    return "D"


def _grade_from_positions(position_count: int) -> str:
    if position_count <= 1:
        return "A"
    if position_count <= 2:
        return "B"
    if position_count <= 4:
        return "C"
    return "D"


# ─────────────────────────────────────────────────────────────────────
# Top-level orchestration
# ─────────────────────────────────────────────────────────────────────


def grade_deal(
    parser_outputs: list[dict],
    debt_summary: dict | None = None,
) -> dict:
    """Run the full SOP grading pipeline on parsed statements.

    Inputs:
      parser_outputs: list of statement_parser JSON outputs (one per
        statement uploaded). May have excluded_credits + category fields
        from the SOP-upgraded parser, or the legacy shape from the
        pre-SOP parser (we fall back to deposits-as-revenue).
      debt_summary: optional debt_detector.summarize_debt result. Used
        only for the legacy fallback NSF count; positions are
        re-verified here (debt_detector counts every recurring debit;
        this module enforces SOP §4 strict policy).

    Output: the dict the metric card needs. Keys map 1:1 to SOP §7.
    """
    revenue = compute_true_monthly_revenue(parser_outputs)
    position_data = verify_positions(parser_outputs)

    true_revenue = revenue["avg"]
    monthly_burden = position_data["monthly_burden"]
    leverage = monthly_burden / true_revenue if true_revenue > 0 else float("inf")

    # NSFs: prefer parser per-statement nsf_events sum; fall back to
    # debt_summary's aggregate if the parser shape is sparse.
    nsf_total = sum(int(s.get("nsf_events") or 0) for s in parser_outputs)
    if nsf_total == 0 and debt_summary:
        nsf_total = int(debt_summary.get("total_nsf_events") or 0)
    nsfs_per_month = nsf_total / max(1, len(parser_outputs))

    negative_days_total = sum(int(s.get("overdraft_days") or 0) for s in parser_outputs)

    # Estimated total MCA balance: per SOP §5 it's a range derived from
    # factor × advance. Without per-position funding date + factor we
    # ballpark: monthly burden × 6 (mid factor 1.3 / 4.3 weeks ~6 mo
    # payoff). Flagged 'rough_estimate' so the operator treats it as
    # ballpark, not a quote.
    est_total_balance = round(monthly_burden * 6, 2) if monthly_burden > 0 else 0.0

    grade, recommendation = assign_grade(
        leverage=leverage if leverage != float("inf") else 999.0,
        nsfs_per_month=nsfs_per_month,
        position_count=len(position_data["positions"]),
        collections_flag=position_data["collections_flag"],
    )

    # Target lender tier — A-grade deal goes to A-paper funders, etc.
    # JUNK has no tier (don't shop).
    target_tier = None if grade == "JUNK" else grade

    red_flags: list[str] = []
    if position_data["collections_flag"]:
        red_flags.append("DEATH-BLOW: MCA in collections (defaulted advance)")
    if leverage > 1.0:
        red_flags.append(f"Leverage {leverage:.0%} exceeds 100% (debt > revenue)")
    if nsfs_per_month > 6:
        red_flags.append(f"{nsfs_per_month:.0f} NSFs/month average — heavy cash-management risk")
    if negative_days_total > 5:
        red_flags.append(f"{negative_days_total} negative-balance days across the window")
    for unknown in position_data["unknown_flags"]:
        red_flags.append(f"Unverified biller flagged for human review: {unknown}")
    if revenue["source"] == "deposits_unfiltered":
        red_flags.append(
            "True revenue uses raw deposits (parser hasn't classified excluded credits) — "
            "actual revenue is likely lower; treat the number as an upper bound"
        )

    return {
        "grade": grade,
        "recommendation": recommendation,
        "target_lender_tier": target_tier,
        "true_monthly_revenue": true_revenue,
        "excluded_credits_monthly": revenue["excluded"],
        "revenue_estimation": revenue["source"],  # 'parser_classified' or 'deposits_unfiltered'
        "active_mca_positions": len(position_data["positions"]),
        "mca_monthly_burden": monthly_burden,
        "mca_leverage": round(leverage, 3) if leverage != float("inf") else None,
        "estimated_total_mca_balance": est_total_balance,
        "estimate_quality": "rough_ballpark",
        "nsfs_window_total": nsf_total,
        "nsfs_per_month_avg": round(nsfs_per_month, 2),
        "negative_balance_days": negative_days_total,
        "collections_flag": position_data["collections_flag"],
        "equipment_lease_count": position_data["equipment_lease_count"],
        "positions_verified": position_data["positions"],
        "red_flags": red_flags,
        "unknown_biller_flags": position_data["unknown_flags"],
    }


def build_metric_card(grading: dict) -> dict:
    """SOP §7 metric card — the operator-facing surface. Just the
    fields the underwriting tab renders, in display order. Computed
    fields (leverage as %, revenue as $X,XXX) stay in grading; this
    just shapes the display."""
    return {
        "grade": grading["grade"],
        "recommendation": grading["recommendation"],
        "true_monthly_revenue": grading["true_monthly_revenue"],
        "excluded_credits_monthly": grading["excluded_credits_monthly"],
        "revenue_note": (
            f"excludes ${grading['excluded_credits_monthly']:,.0f}"
            if grading["revenue_estimation"] == "parser_classified"
            else "deposits-only basis — see Red Flags"
        ),
        "active_mca_positions": grading["active_mca_positions"],
        "mca_monthly_burden": grading["mca_monthly_burden"],
        "mca_leverage_pct": (
            round(grading["mca_leverage"] * 100, 1)
            if grading["mca_leverage"] is not None
            else None
        ),
        "estimated_total_mca_balance": grading["estimated_total_mca_balance"],
        "estimate_quality": grading["estimate_quality"],
        "nsfs_90d": grading["nsfs_window_total"],
        "negative_balance_days": grading["negative_balance_days"],
        "collections_flag": grading["collections_flag"],
        "positions": grading["positions_verified"],
        "red_flags": grading["red_flags"],
        "target_lender_tier": grading["target_lender_tier"],
    }
