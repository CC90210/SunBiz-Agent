"""scrubber/uw_scoring.py — score ONE parsed Breeze UW Sheet deal.

Operates on uw_sheet_parser.parse_uw_sheet() output (the per-deal FORM model),
NOT the legacy row-table scorer in scoring.py. Returns the same ScoreResult
shape so the candidate/push path is unchanged.

CC's rules (2026-06-30; validated against Eagle Metal + Metrocity):
  HARD DECLINES → tier 'bad' (any one):
    - True Revenue (avg monthly) < min_true_revenue_monthly  (default $80k)
    - UW Sheet Column I monthly leverage >= max_active_leverage_pct (default 40%)
    - > max_active_positions active funders (default 5)
    - industry in restricted list
    - ISO/broker in blocked list (Nationwide Advance)
    - data merge notes present and != "Clean" (a report/flag)
  TIERS (when no hard decline):
    - review  → passes but has UNKNOWNS (revenue/leverage/data-merge missing)
    - good    → clean pass
  Previously Submitted = Yes is CC's #1 signal: a strong score bonus + a
  definite-take reason (it never overrides the 40% leverage cap).
"""

from __future__ import annotations

from typing import Any

from scrubber.scoring import ScoreResult


def _has_any(text: Any, needles: list[str]) -> bool:
    t = (text or "")
    if not isinstance(t, str):
        return False
    t = t.lower()
    return any(n in t for n in needles)


def dolphin_eligibility_violations(parsed: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Deterministic gates for every deal Dolphin may surface to Ezra."""
    uw = cfg.get("uw", {})
    min_pos = int(uw.get("min_active_positions", 2))
    max_pos = int(uw.get("max_active_positions", 5))
    max_lev = float(uw.get("max_active_leverage_pct", 40))
    min_payoff = float(uw.get("min_payoff_amount", 15000))
    blocked_iso = [str(s).lower() for s in uw.get("blocked_iso", ["nationwide"])]
    restricted_states = [str(s).lower() for s in uw.get("restricted_states", [])]
    preferred_names = [str(s).lower() for s in uw.get("preferred_funders", [])]
    iso = parsed.get("iso_broker") or ""
    raw_pos = parsed.get("position_count", parsed.get("mca_positions"))
    positions = parsed.get("positions") or parsed.get("uw_all_positions") or parsed.get("counted_funders") or []
    violations: list[str] = []
    if _has_any(iso, blocked_iso):
        violations.append(f"blocked ISO/broker: {iso}")
        return violations
    # Preferred funders force the deal through every ordinary selection rule.
    # Nationwide is the sole absolute veto in Ezra's protocol.
    if any(_has_any(p.get("funder"), preferred_names) for p in positions):
        return []
    state = str(parsed.get("state") or "").strip().lower()
    if state and state in restricted_states:
        violations.append(f"restricted state: {parsed.get('state')}")
    try:
        pos = int(raw_pos) if raw_pos is not None else None
    except (TypeError, ValueError):
        pos = None
    if pos is None and not parsed.get("previously_submitted"):
        violations.append("active lender positions unknown")
    elif pos is not None and pos < min_pos and not parsed.get("previously_submitted"):
        violations.append(f"active lender positions {pos} < {min_pos}")
    elif pos is not None and pos > max_pos:
        violations.append(f"active lender positions {pos} > {max_pos}")
    lev = parsed.get("sheet_monthly_leverage")
    if lev is None:
        lev = parsed.get("leverage_pct")
    if lev is not None and float(lev) >= max_lev:
        violations.append(f"monthly leverage {lev}% >= {int(max_lev)}%")
    for p in positions:
        payoff = p.get("payoff_amount")
        if payoff is not None and float(payoff) < min_payoff:
            violations.append(
                f"{p.get('funder') or 'funder'} payoff amount ${float(payoff):,.0f} < ${min_payoff:,.0f}"
            )
    return violations


def score_uw_deal(parsed: dict[str, Any], cfg: dict[str, Any]) -> ScoreResult:
    uw = cfg.get("uw", {})
    min_rev = float(uw.get("min_true_revenue_monthly", 70000))
    industry_floors = {str(k).lower(): float(v) for k, v in (uw.get("industry_min_revenue") or {}).items()}
    max_lev = float(uw.get("max_active_leverage_pct", 40))
    restricted = [s.lower() for s in uw.get("restricted_industries", [])]
    tiers = uw.get("funder_tiers", {})

    true_rev = parsed.get("true_revenue_monthly")
    lev = parsed.get("sheet_monthly_leverage")
    if lev is None:
        lev = parsed.get("leverage_pct")
    pos = parsed.get("position_count")
    industry = parsed.get("industry")
    iso = parsed.get("iso_broker") or ""
    dm = (parsed.get("data_merge_notes") or "").strip()
    prev = bool(parsed.get("previously_submitted"))
    counted = parsed.get("counted_funders") or []

    reasons: list[str] = []
    declines: list[str] = []
    unknowns: list[str] = []

    # ── revenue (industry-specific floor; construction $80k, others $70k) ──
    eff_min_rev = min_rev
    floor_industry = None
    for ind_key, floor in industry_floors.items():
        if _has_any(industry, [ind_key]):
            eff_min_rev, floor_industry = floor, ind_key
            break
    if true_rev is None:
        unknowns.append("true revenue unknown")
    elif true_rev < eff_min_rev:
        tag = f" ({floor_industry} floor)" if floor_industry else ""
        declines.append(f"true revenue ${int(true_rev):,}/mo < ${int(eff_min_rev):,}{tag}")
    else:
        reasons.append(f"true revenue ${int(true_rev):,}/mo")

    # ── industry (often blank — only declines when present + restricted) ──
    if _has_any(industry, restricted):
        declines.append(f"restricted industry: {industry}")
    elif industry:
        reasons.append(f"industry: {industry}")

    # ── ISO / broker ──
    eligibility_declines = dolphin_eligibility_violations(parsed, cfg)
    declines.extend(eligibility_declines)
    if iso and not any("blocked ISO/broker" in reason for reason in eligibility_declines):
        reasons.append(f"ISO: {iso}")

    # ── data merge ──
    if not dm:
        unknowns.append("data merge unknown")
    elif dm.lower() == "clean":
        reasons.append("data merge clean")
    else:
        declines.append(f"data merge flagged: {dm}")

    # ── leverage (UW Sheet Column I monthly average) ──
    if lev is None:
        unknowns.append("active leverage unknown")
    elif lev >= max_lev:
        pass  # centralized in dolphin_eligibility_violations()
    else:
        reasons.append(f"monthly leverage {lev}% on {pos} active funder(s)")

    # ── position count ──
    # Position min/max gates are centralized in dolphin_eligibility_violations().

    # ── funder tier note (A-tier presence is a positive signal) ──
    a_names = [s.lower() for s in tiers.get("A", [])]
    a_hits = [f["funder"] for f in counted if f.get("funder") and _has_any(f["funder"], a_names)]
    if a_hits:
        reasons.append("A-tier funder(s): " + ", ".join(sorted(set(a_hits))))

    # ── previously submitted (CC's #1 signal) ──
    if prev:
        reasons.append("PREVIOUSLY SUBMITTED = Yes (definite-take)")

    if declines:
        return ScoreResult(
            score=0, tier="bad", reasons=[], decline_reason="; ".join(declines),
            leverage_pct=lev, monthly_revenue=true_rev, prefilter_decline=True,
        )

    if unknowns:
        reasons.append("⚠ needs review: " + ", ".join(unknowns))
        tier = "review"
    else:
        tier = "good"

    # additive score for ordering Ezra's queue (rules already decided the tier)
    score = 60
    if prev:
        score += 25
    if true_rev:
        score += min(10, int(true_rev / 100000))
    if lev is not None and lev < 20:
        score += 5
    score = max(0, min(100, score))

    return ScoreResult(
        score=score, tier=tier, reasons=reasons, decline_reason=None,
        leverage_pct=lev, monthly_revenue=true_rev, prefilter_decline=False,
    )
