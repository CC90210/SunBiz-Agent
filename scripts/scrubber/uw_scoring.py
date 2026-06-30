"""scrubber/uw_scoring.py — score ONE parsed Breeze UW Sheet deal.

Operates on uw_sheet_parser.parse_uw_sheet() output (the per-deal FORM model),
NOT the legacy row-table scorer in scoring.py. Returns the same ScoreResult
shape so the candidate/push path is unchanged.

CC's rules (2026-06-30; validated against Eagle Metal + Metrocity):
  HARD DECLINES → tier 'bad' (any one):
    - True Revenue (avg monthly) < min_true_revenue_monthly  (default $80k)
    - active leverage % >= max_active_leverage_pct           (default 40%)
      where active leverage = sum of daily/weekly funders' per-funder leverage,
      EXCLUDING paid-off positions and the Breeze Advance new-advance row.
    - > max_active_positions active funders AND not under the leverage cap
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


def score_uw_deal(parsed: dict[str, Any], cfg: dict[str, Any]) -> ScoreResult:
    uw = cfg.get("uw", {})
    min_rev = float(uw.get("min_true_revenue_monthly", 80000))
    max_lev = float(uw.get("max_active_leverage_pct", 40))
    max_pos = int(uw.get("max_active_positions", 4))
    restricted = [s.lower() for s in uw.get("restricted_industries", [])]
    blocked_iso = [s.lower() for s in uw.get("blocked_iso", [])]
    tiers = uw.get("funder_tiers", {})

    true_rev = parsed.get("true_revenue_monthly")
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

    # ── revenue ──
    if true_rev is None:
        unknowns.append("true revenue unknown")
    elif true_rev < min_rev:
        declines.append(f"true revenue ${int(true_rev):,}/mo < ${int(min_rev):,}")
    else:
        reasons.append(f"true revenue ${int(true_rev):,}/mo")

    # ── industry (often blank — only declines when present + restricted) ──
    if _has_any(industry, restricted):
        declines.append(f"restricted industry: {industry}")
    elif industry:
        reasons.append(f"industry: {industry}")

    # ── ISO / broker ──
    if _has_any(iso, blocked_iso):
        declines.append(f"blocked ISO/broker: {iso}")
    elif iso:
        reasons.append(f"ISO: {iso}")

    # ── data merge ──
    if not dm:
        unknowns.append("data merge unknown")
    elif dm.lower() == "clean":
        reasons.append("data merge clean")
    else:
        declines.append(f"data merge flagged: {dm}")

    # ── leverage (active daily/weekly funders) ──
    if lev is None:
        unknowns.append("active leverage unknown")
    elif lev >= max_lev:
        declines.append(f"active leverage {lev}% >= {int(max_lev)}%")
    else:
        reasons.append(f"active leverage {lev}% on {pos} active funder(s)")

    # ── position count (>max allowed ONLY if under the leverage cap) ──
    if pos is not None and pos > max_pos:
        if lev is not None and lev < max_lev:
            reasons.append(f"{pos} active funders but under {int(max_lev)}% (exception)")
        else:
            declines.append(f">{max_pos} active funders and not under {int(max_lev)}%")

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
