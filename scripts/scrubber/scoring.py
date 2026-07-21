"""scrubber/scoring.py — config-driven MCA deal scorer ("scrubber").

⚠️  v1 is a PROVISIONAL placeholder. The real thresholds/weights come from
CC's forthcoming underwriting SOP. This module ships the full FRAMEWORK
(pre-filters → weighted score → tier → optional Claude tie-break) so the
SOP becomes a `scoring_config.yaml` edit with zero code change.

Design:
  - score_lead(data, cfg) is PURE (no I/O) given a loaded config + an
    optional `previously_submitted` already resolved onto `data`.
  - load_config() reads scoring_config.yaml when PyYAML + the file are
    present; otherwise falls back to DEFAULT_CONFIG so the daemon always
    runs.
  - Deterministic pre-filters decide hard declines BEFORE any Claude call
    (cost + auditability + prompt-injection safety: a malicious free-text
    cell can't bypass a numeric gate).

Inputs come from import_mca_leads.map_row_to_lead_data():
  data.annual_revenue, data.mca_positions, data.current_funders (list of
  {funder, frequency, payment}), data.current_funders_text, data.state,
  and optionally data.paper_grade / data.nsf_avg_per_month /
  data.previously_submitted when available.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

CONFIG_PATH = Path(__file__).resolve().parent / "scoring_config.yaml"

# Cadence → payments-per-month. These are factual MCA conventions (≈21.67
# ACH business days/month), not policy, so they live in code not config.
_CADENCE_TO_MONTHLY = {
    "daily": 21.67,
    "weekly": 4.333,
    "biweekly": 2.167,
    "monthly": 1.0,
    "monthly_fee": 1.0,   # the "*" fee rows parsed by import_mca_leads
}

# Built-in defaults — MUST mirror scoring_config.yaml. Used when the YAML
# file or PyYAML is unavailable so the daemon never hard-fails on config.
DEFAULT_CONFIG: dict[str, Any] = {
    "version": "0.1-placeholder-builtin",
    "revenue_basis": "monthly",
    "prefilters": {
        "max_nsf_90d": 5,
        "max_leverage_pct": 45,
        "max_positions": 4,
        "min_monthly_revenue": 15000,
        "declined_states": [],
    },
    "weights": {
        "paper_grade": {"A": 30, "B": 22, "C": 12, "D": 0},
        "leverage_pct": {"lt_20": 20, "lt_35": 12, "lt_45": 4, "gte_45": 0},
        "positions": {"0": 20, "1": 15, "2": 8, "3": 3, "4": 0},
        "monthly_revenue": {"gte_100000": 15, "gte_50000": 10, "gte_25000": 5},
        "previously_submitted": 25,
    },
    "tiers": {"good_min": 70, "review_min": 45},
    "previously_submitted": {
        "source": "crm_derived",
        "sheet_column_aliases": ["previously_submitted", "previously submitted", "prev submitted", "resubmit"],
    },
    "claude": {"enabled": False, "model": "claude-haiku-4-5-20251001", "only_for_tier": ["review"]},
    "gate": {"mode": "require_ezra"},
    # Breeze UW Sheet rules (real, validated) — consumed by uw_scoring.py.
    "uw": {
        "min_true_revenue_monthly": 80000,
        "max_active_leverage_pct": 40,
        "min_active_positions": 2,
        "max_active_positions": 4,
        "restricted_industries": ["trucking", "accounting", "law", "transportation", "cannabis", "auto sales", "solar"],
        "blocked_iso": ["nationwide"],
        "funder_tiers": {"A": ["specialty capital", "altfunding", "alt funding"], "B": ["mulligan"]},
    },
}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load scoring_config.yaml, deep-merged over DEFAULT_CONFIG. Any
    missing key falls back to the built-in default. Never raises — a
    parse error logs and uses defaults so scoring still runs."""
    cfg = _deep_copy(DEFAULT_CONFIG)
    try:
        import yaml  # type: ignore
    except Exception:  # noqa: BLE001
        print("[scrubber.scoring] PyYAML unavailable — using built-in DEFAULT_CONFIG", file=sys.stderr)
        return cfg
    try:
        with path.open("r", encoding="utf-8") as fh:
            override = yaml.safe_load(fh) or {}
        if isinstance(override, dict):
            _deep_merge(cfg, override)
    except FileNotFoundError:
        print(f"[scrubber.scoring] {path.name} not found — using built-in DEFAULT_CONFIG", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[scrubber.scoring] config parse error ({exc}) — using built-in DEFAULT_CONFIG", file=sys.stderr)
    return cfg


def _deep_copy(d: dict[str, Any]) -> dict[str, Any]:
    import copy
    return copy.deepcopy(d)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ── numeric helpers ─────────────────────────────────────────────────────

def monthly_debt_service(funders: Optional[list[dict[str, Any]]]) -> Optional[float]:
    """Sum the existing MCA stack's payments normalized to a monthly figure.
    Returns None when there are no parseable funder payments (so leverage is
    'unknown' rather than falsely 0)."""
    if not funders:
        return None
    total = 0.0
    counted = 0
    for f in funders:
        pay = f.get("payment")
        freq = (f.get("frequency") or "").lower()
        mult = _CADENCE_TO_MONTHLY.get(freq)
        if pay is None or mult is None:
            continue
        try:
            total += float(pay) * mult
            counted += 1
        except (TypeError, ValueError):
            continue
    return total if counted else None


def monthly_revenue_of(data: dict[str, Any], cfg: dict[str, Any]) -> Optional[float]:
    """Resolve the merchant's MONTHLY revenue from the raw sheet value
    per cfg.revenue_basis. import_mca_leads stores the raw column in
    data.annual_revenue (its own naming); we reinterpret per config."""
    raw = data.get("annual_revenue")  # importer stores the raw sheet column here
    if raw is None:
        # No revenue data. Do NOT fall back to data["monthly_revenue"] — the
        # importer sets it to raw/12, whose basis is ambiguous vs cfg.revenue_basis
        # and would 12x-understate a monthly figure (review finding 3). Absent
        # annual_revenue ⟺ absent revenue, so None is correct.
        return None
    try:
        raw = float(raw)
    except (TypeError, ValueError):
        return None
    basis = (cfg.get("revenue_basis") or "monthly").lower()
    return raw if basis == "monthly" else raw / 12.0


def compute_leverage_pct(data: dict[str, Any], cfg: dict[str, Any]) -> Optional[float]:
    """monthly debt service / monthly revenue * 100.

    Returns None ONLY when leverage is genuinely unknown:
      - revenue missing, or
      - a funder stack was reported (current_funders_text present) but NONE
        of it parsed (don't fabricate leverage on a parse miss → route to review).
    A merchant with NO funder data at all has zero existing debt → 0% leverage
    (the healthiest case), NOT 'unknown'."""
    rev = monthly_revenue_of(data, cfg)
    if not rev or rev <= 0:
        return None
    funders = data.get("current_funders")
    funders_text = data.get("current_funders_text")
    if not funders:
        # Text reported but unparseable → unknown. Nothing at all → zero debt.
        if funders_text:
            return None
        return 0.0
    debt = monthly_debt_service(funders)
    if debt is None:
        return None
    return round(debt / rev * 100.0, 1)


# ── scorer ───────────────────────────────────────────────────────────────

class ScoreResult(dict):
    """Plain dict subclass for ergonomics: keys score, tier, reasons,
    decline_reason, leverage_pct, monthly_revenue, prefilter_decline."""


def score_lead(data: dict[str, Any], cfg: dict[str, Any]) -> ScoreResult:
    """Score one normalized lead. Returns a ScoreResult. Pure function."""
    reasons: list[str] = []
    pf = cfg.get("prefilters", {})
    weights = cfg.get("weights", {})

    monthly_rev = monthly_revenue_of(data, cfg)
    leverage = compute_leverage_pct(data, cfg)
    positions = data.get("mca_positions")
    nsf = data.get("nsf_avg_per_month") or data.get("nsf_90d")
    paper_grade = (data.get("paper_grade") or "").upper().strip() or None
    state = (data.get("state") or "").strip().upper()
    prev_submitted = bool(data.get("previously_submitted"))

    # ── pre-filters (hard declines) ──
    declines: list[str] = []
    if nsf is not None:
        try:
            if float(nsf) > float(pf.get("max_nsf_90d", 5)):
                declines.append(f"nsf={nsf} > {pf.get('max_nsf_90d')}")
        except (TypeError, ValueError):
            pass
    if leverage is not None and leverage > float(pf.get("max_leverage_pct", 45)):
        declines.append(f"leverage={leverage}% > {pf.get('max_leverage_pct')}%")
    if positions is not None:
        try:
            if int(positions) > int(pf.get("max_positions", 4)):
                declines.append(f"positions={positions} > {pf.get('max_positions')}")
        except (TypeError, ValueError):
            pass
    if monthly_rev is not None and monthly_rev < float(pf.get("min_monthly_revenue", 0)):
        declines.append(f"monthly_revenue={int(monthly_rev)} < {pf.get('min_monthly_revenue')}")
    if state and state in {s.upper() for s in (pf.get("declined_states") or [])}:
        declines.append(f"state={state} excluded")

    if declines:
        return ScoreResult(
            score=0,
            tier="bad",
            reasons=[],
            decline_reason="; ".join(declines),
            leverage_pct=leverage,
            monthly_revenue=monthly_rev,
            prefilter_decline=True,
        )

    # ── additive weighted score ──
    score = 0.0

    if paper_grade and paper_grade in weights.get("paper_grade", {}):
        pts = weights["paper_grade"][paper_grade]
        score += pts
        reasons.append(f"paper_grade {paper_grade} (+{pts})")

    if leverage is not None:
        lw = weights.get("leverage_pct", {})
        if leverage < 20:
            pts, band = lw.get("lt_20", 0), "<20%"
        elif leverage < 35:
            pts, band = lw.get("lt_35", 0), "20-35%"
        elif leverage < 45:
            pts, band = lw.get("lt_45", 0), "35-45%"
        else:
            pts, band = lw.get("gte_45", 0), ">=45%"
        score += pts
        reasons.append(f"leverage {leverage}% {band} (+{pts})")
    else:
        reasons.append("leverage unknown (unparsed stack)")

    if positions is not None:
        pw = weights.get("positions", {})
        key = "4" if int(positions) >= 4 else str(int(positions))
        pts = pw.get(key, 0)
        score += pts
        reasons.append(f"{positions} position(s) (+{pts})")
    else:
        # Blank positions cell → unknown, NOT assumed zero-debt (a blank could be
        # missing data, not a confirmed first-position deal). Surface it so Ezra
        # sees the gap rather than a silent 0-point under-score. The SOP defines
        # how to treat blanks (review finding 15).
        reasons.append("positions unknown (blank — SOP to define)")

    if monthly_rev is not None:
        mw = weights.get("monthly_revenue", {})
        if monthly_rev >= 100000:
            pts, band = mw.get("gte_100000", 0), ">=100k"
        elif monthly_rev >= 50000:
            pts, band = mw.get("gte_50000", 0), ">=50k"
        elif monthly_rev >= 25000:
            pts, band = mw.get("gte_25000", 0), ">=25k"
        else:
            pts, band = 0, "<25k"
        score += pts
        reasons.append(f"monthly_rev {band} (+{pts})")

    if prev_submitted:
        pts = weights.get("previously_submitted", 0)
        score += pts
        reasons.append(f"previously_submitted (+{pts})")

    score_int = int(round(min(100.0, max(0.0, score))))

    tiers = cfg.get("tiers", {})
    if score_int >= int(tiers.get("good_min", 70)):
        tier = "good"
    elif score_int >= int(tiers.get("review_min", 45)):
        tier = "review"
    else:
        tier = "bad"

    return ScoreResult(
        score=score_int,
        tier=tier,
        reasons=reasons,
        decline_reason=None,
        leverage_pct=leverage,
        monthly_revenue=monthly_rev,
        prefilter_decline=False,
    )
