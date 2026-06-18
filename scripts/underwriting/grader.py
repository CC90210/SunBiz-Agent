"""grader.py — Adon/SunBiz MCA SOP grading + sales metric card.

Per the SunBiz underwriting SOP (Parts 2-6). Consumes the output of
statement_parser + debt_detector, produces (a) the raw `grading` dict and
(b) the `metric_card` the dashboard renders. The dashboard reads
`application_underwriting.debt_analysis.metric_card`; the field names below
are a load-bearing contract with SalesMetricCard.tsx +
ApplicationUnderwritingReport.tsx — DO NOT rename or retype them.

Public surface (unchanged signatures, back-compat positional args):
  grade_deal(parser_outputs, debt_summary, *, app_data, data_source,
             review_period) -> dict          # full grading result
  build_metric_card(grading) -> dict           # UI-shape card

Pure functions. No DB / network. The orchestrator calls into this after
debt_detector and persists both shapes alongside the debt summary.

Hard SOP rules enforced here (Part 6 — won't drift on later edits):

  1. TRUE revenue = gross deposits − excluded credits (transfers, MCA/loan
     funding wires, owner injections, refunds, tax/insurance/trust).
     gross + excluded + true are all stored. Falls back to raw deposits
     (flagged) when the parser hasn't classified excluded credits.

  2. A position counts ONLY when the biller is a verified MCA funder
     (category=='mca_funder'). mca_servicer/collections rows = DEATH-BLOW
     → grade JUNK regardless of leverage. Equipment / auto / SaaS /
     processor / utility / insurance / personal NEVER count as positions
     (they route to other_debt or are ignored). Unknown billers = human
     review, never counted.

  3. Stacking: same lender + same payment amount across statements = one
     advance (payment recurrence). Same lender + a DIFFERENT amount =
     a separate advance (a stack).

  4. Balances are ESTIMATED with a range + "needs merchant confirmation"
     when funding date / factor are unknown. Never a hard number we can't
     support. Funder-tier factor table drives the back-calc.

  5. Grade table (SOP 2.4):
       A     leverage < 25%   NSFs 0-1   positions 0-1
       B     25% - 45%        1-3        1-2
       C     45% - 70%        3-6        3-4
       D     70% - 100%       6+         5+
       JUNK  > 100% OR any MCA in collections
     Justified with specific numbers (grade_justification).

  6. NEVER show real funder/lender names in any merchant-facing field.
     positioning_merchant_safe + the proposed-play tiers are internal /
     merchant-safe respectively; lender_hint stays internal-only.
"""

from __future__ import annotations

import math
from typing import Any


# ─────────────────────────────────────────────────────────────────────
# Excluded-credit categories (SOP 2.1)
# ─────────────────────────────────────────────────────────────────────

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
# Other-debt categories (SOP 2.2 — NOT MCA positions, separate bucket)
# ─────────────────────────────────────────────────────────────────────

# Map a parser category → the other_debt `type` the dashboard renders.
OTHER_DEBT_TYPE_BY_CATEGORY: dict[str, str] = {
    "equipment_lease": "equipment",
    "auto_loan": "auto",
    "loan_other": "loan_other",
}

# Operating-expense categories: not debt, not a position — ignored for
# leverage entirely (SOP 2.2 treatment column).
_OPEX_CATEGORIES: frozenset[str] = frozenset({
    "saas", "processor", "utility", "insurance",
})


# ─────────────────────────────────────────────────────────────────────
# Frequency normalization (SOP 2.4 — daily ~21.7, weekly ~4.33)
# ─────────────────────────────────────────────────────────────────────

_FREQ_MONTHLY_MULTIPLIER: dict[str, float] = {
    "daily": 21.7,
    "weekly": 4.33,
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
# Funder-tier factor table (SOP 2.3) — used to back-estimate balances.
# tier letter → (factor_low, factor_high, term_months_low, term_months_high)
# A-grade deals shop to Tier-1 funders, etc. JUNK has no tier.
# ─────────────────────────────────────────────────────────────────────

_TIER_FACTORS: dict[str, tuple[float, float, float, float]] = {
    "A": (1.20, 1.35, 6.0, 12.0),    # Premium / Tier 1
    "B": (1.30, 1.42, 4.0, 9.0),     # Mid
    "C": (1.40, 1.55, 3.0, 6.0),     # Sub-prime / D paper
    "D": (1.45, 1.65, 2.0, 4.0),     # Micro / high-risk
}

# Internal-only label for each tier (NEVER merchant-facing).
_TIER_INTERNAL_LABEL: dict[str, str] = {
    "A": "A-paper / Tier 1 (premium funders)",
    "B": "B-paper / Mid-tier funders",
    "C": "C-paper / Sub-prime funders",
    "D": "D-paper / micro / workout desks",
}


def _round2(x: float) -> float:
    return round(float(x), 2)


# ─────────────────────────────────────────────────────────────────────
# Revenue (SOP 2.1)
# ─────────────────────────────────────────────────────────────────────


def compute_true_monthly_revenue(parser_outputs: list[dict]) -> dict:
    """SOP 2.1: TRUE revenue = gross deposits − Σ excluded_credits.

    Returns {avg, gross, excluded, source, processor_signal} where:
      avg: average TRUE monthly revenue across statements
      gross: average gross deposits per statement (display + transparency)
      excluded: average excluded credits per statement
      source: 'parser_classified' when the parser tagged categories;
              'deposits_unfiltered' when we fell back to raw deposits.
      processor_signal: True when card-processor batch deposits were seen
              (Stripe/Square/etc.) — the most reliable real-revenue signal.
    """
    if not parser_outputs:
        return {
            "avg": 0.0, "gross": 0.0, "excluded": 0.0,
            "source": "deposits_unfiltered", "processor_signal": False,
        }

    deposits_sum = 0.0
    excluded_sum = 0.0
    saw_classified = False
    processor_signal = False

    for stmt in parser_outputs:
        deposits_sum += float(stmt.get("total_deposits") or 0)
        excluded = stmt.get("excluded_credits") or []
        if excluded:
            saw_classified = True
            for entry in excluded:
                category = str(entry.get("category") or "").strip().lower()
                if category in EXCLUDED_CREDIT_CATEGORIES:
                    excluded_sum += float(entry.get("amount") or 0)
        if stmt.get("card_processor_deposits"):
            processor_signal = True

    n = len(parser_outputs)
    avg_gross = deposits_sum / n
    avg_revenue = (deposits_sum - excluded_sum) / n
    avg_excluded = excluded_sum / n
    return {
        "avg": max(0.0, _round2(avg_revenue)),
        "gross": _round2(avg_gross),
        "excluded": _round2(avg_excluded),
        "source": "parser_classified" if saw_classified else "deposits_unfiltered",
        "processor_signal": processor_signal,
    }


# ─────────────────────────────────────────────────────────────────────
# Position verification + stacking + other-debt routing (SOP 2.2)
# ─────────────────────────────────────────────────────────────────────


import re

# Leading payment-rail / channel prefixes that are descriptor noise, not
# part of the biller name (SOP 2.2 step 1 — "strip ACH prefixes").
_DESCRIPTOR_PREFIXES = (
    "ach ", "withdrawal ", "online ", "recurring ", "debit ", "pos ",
    "preauth ", "pre-auth ", "electronic ", "web ", "billpay ", "bill pay ",
)


def _normalize_descriptor(raw: str) -> str:
    """Normalize a biller descriptor for grouping (SOP 2.2 step 1).

    Strips leading payment-rail prefixes, collapses whitespace, and drops
    trailing reference / ID number tokens so "ACH Ford Motor Cr ... 0042"
    and "Ford Motor Credit ..." collapse to the same grouping key. Display
    keeps the first-seen raw descriptor; only the grouping key is normalized.
    """
    s = " ".join((raw or "").lower().split())
    changed = True
    while changed:
        changed = False
        for pre in _DESCRIPTOR_PREFIXES:
            if s.startswith(pre):
                s = s[len(pre):]
                changed = True
    # Drop trailing standalone ref/ID number tokens (e.g. "... id 3006").
    s = re.sub(r"\b(id|ref|acct|account|no|#)\s*\d+\b", "", s)
    s = re.sub(r"\b\d{4,}\b", "", s)
    s = " ".join(s.split())
    # Group on the first few significant tokens — abbreviation tails
    # ("credit" vs "cr") and account-holder names appended to the memo
    # otherwise split one real debt into several rows.
    tokens = [t for t in s.split() if t]
    return " ".join(tokens[:2]) if tokens else (raw or "").lower().strip()


def _amount_bucket(amount: float) -> int:
    """Bucket a payment amount so 'same advance' rows collapse while a
    materially different amount (a separate advance / stack) splits out.
    Rounds to the nearest $10 — daily ACH amounts on one advance are
    identical to the cent, so this is generous slack against OCR noise."""
    return int(round(amount / 10.0)) * 10


def verify_positions(parser_outputs: list[dict]) -> dict:
    """SOP 2.2: a position counts ONLY when the biller is a verified MCA
    funder. Stacking is detected by (lender, payment amount): same lender +
    same amount = one advance; same lender + different amount = a separate
    advance. mca_servicer/collections = DEATH-BLOW. Equipment/auto/loan_other
    route to other_debt. SaaS/processor/utility/insurance ignored. Unknown =
    human-review flag, never counted.

    Returns {
      positions, monthly_burden, collections_flag, collections[],
      other_debt[], equipment_lease_count, unknown_flags[]
    }
    """
    # Key positions by (lender, amount-bucket) so a stack on one lender
    # splits into multiple advances.
    by_advance: dict[tuple[str, int], dict] = {}
    # Collections keyed by (servicer, amount-bucket) so the same servicer
    # seen across statements collapses to one entry, not one per month.
    collections_acc: dict[tuple[str, int], dict] = {}
    other_debt_acc: dict[tuple[str, str], dict] = {}
    equipment_lease_count = 0
    # Keyed on normalized descriptor so the same unverified biller seen
    # across statements / with ACH-prefix variants collapses to one entry.
    unknown_acc: dict[str, str] = {}

    for stmt in parser_outputs:
        for entry in stmt.get("identified_loan_payments") or []:
            lender_hint = str(entry.get("lender_hint") or "unknown").strip()
            category = str(entry.get("category") or "").strip().lower()
            amount = float(entry.get("amount") or 0)
            frequency = entry.get("frequency") or "monthly"
            monthly_eq = _to_monthly(amount, frequency)
            lhint_l = lender_hint.lower()
            norm = _normalize_descriptor(lender_hint)

            # ── Collections / servicer = DEATH-BLOW (SOP 2.2) ──
            if category == "mca_servicer" or "collection" in lhint_l or "servicing" in lhint_l:
                ckey = (norm, _amount_bucket(amount))
                collections_acc.setdefault(ckey, {
                    "servicer": lender_hint,
                    "original_lender": entry.get("original_lender") or None,
                    "payment": _round2(amount),
                    "status": "in_collections",
                })
                continue

            # ── Other debt buckets (NOT positions) ──
            if category in OTHER_DEBT_TYPE_BY_CATEGORY:
                if category == "equipment_lease":
                    equipment_lease_count += 1
                otype = OTHER_DEBT_TYPE_BY_CATEGORY[category]
                key = (norm, otype)
                row = other_debt_acc.setdefault(key, {
                    "vendor": lender_hint, "type": otype,
                    "_monthly": 0.0, "_n": 0,
                })
                row["_monthly"] += monthly_eq
                row["_n"] += 1
                continue

            # ── Operating expense — ignore for debt entirely ──
            if category in _OPEX_CATEGORIES:
                continue

            # ── Unknown / unverified — flag, never count (SOP 2.2) ──
            if category in ("", "unknown"):
                unknown_acc.setdefault(norm, lender_hint)
                continue
            if category != "mca_funder":
                unknown_acc.setdefault(norm, f"{lender_hint} (category={category})")
                continue

            # ── Verified MCA funder — count as a position, split stacks ──
            akey = (norm, _amount_bucket(amount))
            row = by_advance.setdefault(akey, {
                "lender_hint": lender_hint,
                "payment_amount": amount,
                "monthly_estimate": 0.0,
                "occurrences": 0,
                "frequencies": set(),
                "funded_date": entry.get("funded_date") or None,
                "factor_rate": entry.get("factor_rate") or None,
            })
            row["monthly_estimate"] += monthly_eq
            row["occurrences"] += 1
            row["frequencies"].add(frequency)
            if not row["funded_date"] and entry.get("funded_date"):
                row["funded_date"] = entry.get("funded_date")
            if not row["factor_rate"] and entry.get("factor_rate"):
                row["factor_rate"] = entry.get("factor_rate")

    # Average across the statement window so the burden reflects ONE
    # representative month, not the cumulative across the window.
    n = max(1, len(parser_outputs))
    positions: list[dict] = []
    monthly_burden = 0.0
    for row in by_advance.values():
        avg_monthly = row["monthly_estimate"] / n
        monthly_burden += avg_monthly
        positions.append({
            "lender_hint": row["lender_hint"],
            "estimated_monthly_payment": _round2(avg_monthly),
            "observed_in_statements": row["occurrences"],
            "frequencies_observed": sorted(row["frequencies"]),
            "funded_date": row["funded_date"],
            "factor_rate": row["factor_rate"],
        })
    positions.sort(key=lambda r: r["estimated_monthly_payment"], reverse=True)

    other_debt: list[dict] = []
    for row in other_debt_acc.values():
        # Per-occurrence average — robust to the same physical debt being
        # transcribed under several descriptor variants across statements
        # (summing would multiply one payment by the variant count).
        occ = max(1, row["_n"])
        other_debt.append({
            "vendor": row["vendor"],
            "type": row["type"],
            "payment": _round2(row["_monthly"] / occ),
        })
    other_debt.sort(key=lambda r: r["payment"], reverse=True)

    collections = list(collections_acc.values())
    unknown_flags = list(unknown_acc.values())

    return {
        "positions": positions,
        "monthly_burden": _round2(monthly_burden),
        "collections_flag": bool(collections),
        "collections": collections,
        "other_debt": other_debt,
        "equipment_lease_count": equipment_lease_count,
        "unknown_flags": unknown_flags,
    }


# ─────────────────────────────────────────────────────────────────────
# Balance estimation (SOP 2.3)
# ─────────────────────────────────────────────────────────────────────


def estimate_position_balance(position: dict, tier: str) -> dict:
    """Estimate a single position's outstanding balance as a RANGE.

    Without a confirmed funding date + factor we cannot give a hard
    number (SOP Hard Rule). We back-estimate total payback from the
    monthly payment × the tier's typical term, then bracket the
    outstanding balance between an early-life and late-life fraction of
    that payback. Always flagged is_estimated + needs_confirmation.
    """
    monthly = float(position.get("estimated_monthly_payment") or 0)
    factors = _TIER_FACTORS.get(tier or "C", _TIER_FACTORS["C"])
    _flo, _fhi, term_lo, term_hi = factors
    term_mid = (term_lo + term_hi) / 2.0

    funded_date = position.get("funded_date")
    funded_conf = "confirmed" if funded_date else "unknown"

    # Total payback ≈ monthly payment × typical full term for the tier.
    est_total_payback = monthly * term_mid
    # Outstanding: we don't know elapsed time, so bracket 15%-85% of the
    # payback as the plausible remaining balance.
    est_low = est_total_payback * 0.15
    est_high = est_total_payback * 0.85
    est_mid = est_total_payback * 0.50

    return {
        "est_balance": _round2(est_mid),
        "est_balance_low": _round2(est_low),
        "est_balance_high": _round2(est_high),
        "est_balance_is_estimated": True,
        "funded_date": funded_date,
        "funded_date_confidence": funded_conf,
        "balance_note": "needs merchant confirmation (funding date/factor unknown)"
                        if not funded_date else "needs merchant confirmation",
    }


# ─────────────────────────────────────────────────────────────────────
# Grade table (SOP 2.4)
# ─────────────────────────────────────────────────────────────────────


def assign_grade(
    leverage: float,
    nsfs_per_month: float,
    position_count: int,
    collections_flag: bool,
) -> tuple[str, str]:
    """SOP 2.4 grade table. Returns (grade, recommendation).

    Any collections flag overrides leverage/positions and forces JUNK +
    Decline — "no funder touches a merchant in active MCA collections."
    """
    if collections_flag or leverage > 1.0:
        return ("JUNK", "Decline — refer to restructure")

    leverage_grade = _grade_from_leverage(leverage)
    nsf_grade = _grade_from_nsfs(nsfs_per_month)
    pos_grade = _grade_from_positions(position_count)

    # Worst (alphabetically latest letter) of the three dimensions.
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
# Strategic play (SOP 2.5) + merchant-safe positioning
# ─────────────────────────────────────────────────────────────────────


def _build_proposed_play(
    grade: str,
    true_revenue: float,
    monthly_burden: float,
    est_total_balance: float,
    position_count: int,
) -> dict:
    """SOP 2.5: pick + size the play. target_funder_tier_internal is
    INTERNAL only — never surfaced merchant-side."""
    tier_internal = _TIER_INTERNAL_LABEL.get(grade)
    factors = _TIER_FACTORS.get(grade if grade in _TIER_FACTORS else "C", _TIER_FACTORS["C"])
    flo, fhi, tlo, thi = factors
    expected_terms = (
        f"factor {flo:.2f}–{fhi:.2f}, {int(tlo)}–{int(thi)} mo term, daily/weekly remit"
    )

    if grade == "A" or (grade == "B" and position_count <= 1):
        play_type = "Fresh capital"
        target = true_revenue * 1.0
    elif grade == "B":
        play_type = "Renewal / additional position"
        target = true_revenue * 0.75
    elif grade == "C":
        play_type = "Consolidation"
        target = max(est_total_balance * 1.1, true_revenue * 0.5)
    elif grade == "D":
        play_type = "Workout"
        target = 0.0
        expected_terms = "restructure / reduced remit — workout desk only"
    else:  # JUNK
        play_type = "Decline"
        target = 0.0
        tier_internal = None
        expected_terms = "no fundable structure — refer to restructure attorney"

    target = round(target / 500.0) * 500 if target else 0.0  # round to $500
    # Broker commission est — typical ~10 points on funded amount.
    commission_est = _round2(target * 0.10) if target else 0.0

    return {
        "type": play_type,
        "target_amount": _round2(target),
        "target_amount_is_estimated": True,
        "target_funder_tier_internal": tier_internal,
        "expected_terms": expected_terms,
        "commission_est": commission_est,
        "commission_est_is_estimated": True,
    }


def _build_positioning_merchant_safe(grade: str, true_revenue: float) -> str:
    """A single merchant-safe line. SOP Hard Rule: NO lender names, NO
    internal tier names — this can be shown to or paraphrased for the
    merchant."""
    rev = f"${true_revenue:,.0f}/mo" if true_revenue else "your reported"
    if grade == "A":
        return (
            f"Strong, clean cash flow ({rev} revenue) with low existing obligations — "
            "well-positioned for a competitive working-capital offer on standard terms."
        )
    if grade == "B":
        return (
            f"Healthy {rev} revenue with a manageable existing balance — "
            "a good candidate for additional working capital with light conditions."
        )
    if grade == "C":
        return (
            f"Solid {rev} revenue carrying meaningful existing obligations — "
            "best served by a consolidation that simplifies payments and frees up daily cash."
        )
    if grade == "D":
        return (
            "Current obligations are heavy relative to cash flow — the responsible path is "
            "a restructure that lowers the daily burden before taking on anything new."
        )
    # JUNK
    return (
        "Existing obligations currently exceed what the cash flow can support — "
        "the priority is stabilizing and restructuring before any new funding is appropriate."
    )


def _build_grade_justification(
    grade: str,
    leverage: float | None,
    position_count: int,
    nsfs_per_month: float,
    negative_days: int,
    collections_flag: bool,
) -> str:
    """3-4 sentences citing the specific numbers behind the grade."""
    lev_txt = f"{leverage * 100:.0f}%" if leverage is not None else "undefined (no measurable revenue)"
    parts: list[str] = []
    parts.append(
        f"Active MCA leverage is {lev_txt} of true monthly revenue across "
        f"{position_count} verified position(s)."
    )
    parts.append(
        f"The account shows ~{nsfs_per_month:.1f} NSF/return events per month and "
        f"{negative_days} negative-balance day(s) in the review window."
    )
    if collections_flag:
        parts.append(
            "At least one MCA is in collections — a death-blow that forces JUNK regardless "
            "of leverage; no funder will touch active MCA collections."
        )
    elif grade == "JUNK":
        parts.append(
            "Leverage exceeds 100% — total debt service is larger than the revenue that "
            "would service it, so the deal is not fundable as-is."
        )
    elif grade in ("A", "B"):
        parts.append(
            "Leverage, NSF activity, and position count all sit inside the "
            f"{grade}-tier band, supporting a fundable, lower-risk profile."
        )
    else:
        parts.append(
            f"The worst of leverage, NSF activity, and position count lands the deal in "
            f"the {grade}-tier band — fundable only with the structure noted in the play."
        )
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────
# Top-level orchestration
# ─────────────────────────────────────────────────────────────────────


def grade_deal(
    parser_outputs: list[dict],
    debt_summary: dict | None = None,
    *,
    app_data: dict | None = None,
    data_source: str = "upload",
    review_period: dict | None = None,
) -> dict:
    """Run the full SOP grading pipeline on parsed statements.

    Inputs:
      parser_outputs: list of statement_parser JSON outputs (one per
        statement). May carry excluded_credits + category fields
        (SOP-upgraded parser) or the legacy shape.
      debt_summary: optional debt_detector.summarize_debt result — used
        only as a fallback NSF source; positions are re-verified here.
      app_data: optional application record (for time_in_business_months).
      data_source: provenance label for the card (e.g. "upload").
      review_period: optional {months, start, end}; derived from parser
        statement_period when omitted.

    Output: the raw grading dict. Keys feed build_metric_card.
    """
    app_data = app_data or {}
    revenue = compute_true_monthly_revenue(parser_outputs)
    position_data = verify_positions(parser_outputs)

    true_revenue = revenue["avg"]
    monthly_burden = position_data["monthly_burden"]
    leverage = monthly_burden / true_revenue if true_revenue > 0 else float("inf")

    nsf_total = sum(int(s.get("nsf_events") or 0) for s in parser_outputs)
    if nsf_total == 0 and debt_summary:
        nsf_total = int(debt_summary.get("total_nsf_events") or 0)
    nsfs_per_month = nsf_total / max(1, len(parser_outputs))

    negative_days_total = sum(int(s.get("overdraft_days") or 0) for s in parser_outputs)

    # Average daily balance across statements (SOP CRM summary field).
    adb_values = [
        float(s.get("average_daily_balance"))
        for s in parser_outputs
        if s.get("average_daily_balance") is not None
    ]
    avg_daily_balance = _round2(sum(adb_values) / len(adb_values)) if adb_values else None

    grade, recommendation = assign_grade(
        leverage=leverage if leverage != float("inf") else 999.0,
        nsfs_per_month=nsfs_per_month,
        position_count=len(position_data["positions"]),
        collections_flag=position_data["collections_flag"],
    )

    target_tier = None if grade == "JUNK" else grade

    # Per-position balance estimates (range + needs-confirmation).
    positions_out: list[dict] = []
    est_total_balance = 0.0
    for pos in position_data["positions"]:
        bal = estimate_position_balance(pos, target_tier or "C")
        est_total_balance += bal["est_balance"]
        positions_out.append({**pos, **bal})
    est_total_balance = _round2(est_total_balance)

    proposed_play = _build_proposed_play(
        grade=grade,
        true_revenue=true_revenue,
        monthly_burden=monthly_burden,
        est_total_balance=est_total_balance,
        position_count=len(position_data["positions"]),
    )

    positioning_merchant_safe = _build_positioning_merchant_safe(grade, true_revenue)
    grade_justification = _build_grade_justification(
        grade=grade,
        leverage=(round(leverage, 3) if leverage != float("inf") else None),
        position_count=len(position_data["positions"]),
        nsfs_per_month=nsfs_per_month,
        negative_days=negative_days_total,
        collections_flag=position_data["collections_flag"],
    )

    # Review period — prefer explicit, else derive from parser windows.
    if review_period is None:
        review_period = _derive_review_period(parser_outputs)

    # Time in business — from the application record (months).
    tib = app_data.get("time_in_business_months")
    try:
        time_in_business_months = int(tib) if tib is not None else None
    except (TypeError, ValueError):
        time_in_business_months = None

    # ── Red flags (deduped, clean — the dashboard also dedupes) ──
    red_flags: list[str] = []
    if position_data["collections_flag"]:
        red_flags.append("DEATH-BLOW: MCA in collections (defaulted advance)")
    if leverage != float("inf") and leverage > 1.0:
        red_flags.append(f"Leverage {leverage:.0%} exceeds 100% (debt > revenue)")
    if len(position_data["positions"]) >= 3:
        red_flags.append(f"Stacked: {len(position_data['positions'])} active MCA positions")
    if nsfs_per_month > 3:
        red_flags.append(f"{nsfs_per_month:.0f} NSFs/month average — cash-management risk")
    if negative_days_total > 5:
        red_flags.append(f"{negative_days_total} negative-balance days across the window")
    # Roll up unverified billers into ONE glance-surface flag — the full
    # list lives in unknown_biller_flags / confidence_notes for the detail
    # tab. A 30-line red_flags array is wrong for the sales card.
    n_unknown = len(position_data["unknown_flags"])
    if n_unknown:
        sample = ", ".join(position_data["unknown_flags"][:3])
        more = f" (+{n_unknown - 3} more)" if n_unknown > 3 else ""
        red_flags.append(
            f"{n_unknown} unverified recurring biller(s) held for human review — "
            f"not counted as positions: {sample}{more}"
        )
    if revenue["source"] == "deposits_unfiltered":
        red_flags.append(
            "True revenue uses raw deposits (parser hasn't classified excluded credits) — "
            "treat the number as an upper bound"
        )
    red_flags = _dedupe(red_flags)

    # ── Confidence / provenance notes (SOP Part 4 §10) ──
    confidence_notes: list[str] = []
    confidence_notes.append(f"Data source: {data_source}.")
    if revenue["source"] == "parser_classified":
        confidence_notes.append(
            f"True revenue nets ${revenue['excluded']:,.0f}/mo of excluded credits from "
            f"${revenue['gross']:,.0f}/mo gross deposits."
        )
    else:
        confidence_notes.append(
            "Excluded credits not yet classified — revenue shown is gross deposits (upper bound)."
        )
    if revenue["processor_signal"]:
        confidence_notes.append("Card-processor batch deposits present — strong real-revenue signal.")
    if position_data["positions"]:
        confidence_notes.append("All position balances are estimated ranges — need merchant confirmation.")
    if position_data["unknown_flags"]:
        confidence_notes.append(
            f"{len(position_data['unknown_flags'])} biller(s) unverified — held for human review, not counted."
        )

    return {
        # ── existing contract fields (do not rename) ──
        "grade": grade,
        "recommendation": recommendation,
        "target_lender_tier": target_tier,
        "true_monthly_revenue": true_revenue,
        "excluded_credits_monthly": revenue["excluded"],
        "revenue_estimation": revenue["source"],
        "active_mca_positions": len(position_data["positions"]),
        "mca_monthly_burden": monthly_burden,
        "mca_leverage": round(leverage, 3) if leverage != float("inf") else None,
        "estimated_total_mca_balance": est_total_balance,
        "estimate_quality": "range_needs_confirmation",
        "nsfs_window_total": nsf_total,
        "nsfs_per_month_avg": round(nsfs_per_month, 2),
        "negative_balance_days": negative_days_total,
        "collections_flag": position_data["collections_flag"],
        "equipment_lease_count": position_data["equipment_lease_count"],
        "positions_verified": positions_out,
        "red_flags": red_flags,
        "unknown_biller_flags": position_data["unknown_flags"],
        # ── new SOP fields ──
        "gross_deposits_total": revenue["gross"],
        "positioning_merchant_safe": positioning_merchant_safe,
        "grade_justification": grade_justification,
        "proposed_play": proposed_play,
        "collections": position_data["collections"],
        "other_debt": position_data["other_debt"],
        "avg_daily_balance": avg_daily_balance,
        "time_in_business_months": time_in_business_months,
        "data_source": data_source,
        "review_period": review_period,
        "confidence_notes": confidence_notes,
    }


def _derive_review_period(parser_outputs: list[dict]) -> dict:
    """Build {months, start, end} from the parsed statement_period windows."""
    starts: list[str] = []
    ends: list[str] = []
    for s in parser_outputs:
        period = s.get("statement_period") or {}
        if period.get("start"):
            starts.append(str(period["start"]))
        if period.get("end"):
            ends.append(str(period["end"]))
    return {
        "months": len(parser_outputs),
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
    }


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving dedupe (the dashboard also dedupes for display,
    but we emit clean per the contract)."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def build_metric_card(grading: dict) -> dict:
    """SOP metric card — the dashboard-facing surface. Keeps every existing
    field name AND adds the new SOP fields (Parts 3-5). The dashboard reads
    debt_analysis.metric_card; do not rename anything here."""
    return {
        # ── existing fields (load-bearing — do NOT rename/retype) ──
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
        # ── new SOP fields (Parts 3-5) ──
        "gross_deposits_total": grading["gross_deposits_total"],
        "positioning_merchant_safe": grading["positioning_merchant_safe"],
        "grade_justification": grading["grade_justification"],
        "proposed_play": grading["proposed_play"],
        "collections": grading["collections"],
        "other_debt": grading["other_debt"],
        "avg_daily_balance": grading["avg_daily_balance"],
        "time_in_business_months": grading["time_in_business_months"],
        "data_source": grading["data_source"],
        "review_period": grading["review_period"],
        "confidence_notes": grading["confidence_notes"],
    }
