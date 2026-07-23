from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scrubber.scoring import load_config  # noqa: E402
from scrubber.telegram_bridge import format_packet, send_deal  # noqa: E402
from scrubber.uw_scoring import score_uw_deal  # noqa: E402


def _deal(**overrides):
    deal = {
        "true_revenue_monthly": 100_000,
        "leverage_pct": 10,
        "position_count": 2,
        "industry": "Professional Services",
        "iso_broker": "Links Capital Group",
        "data_merge_notes": "Clean",
        "previously_submitted": True,
        "state": "Florida",
        "counted_funders": [
            {"funder": "Generic Capital", "payoff_amount": 20_000},
            {"funder": "Another Funder", "payoff_amount": None},
        ],
    }
    deal.update(overrides)
    return deal


def test_dolphin_blocks_every_nationwide_iso_variant() -> None:
    cfg = load_config()
    for iso in ("Nationwide", "Nationwide Advance", "The Nationwide ISO Shop"):
        result = score_uw_deal(_deal(iso_broker=iso), cfg)
        assert result["tier"] == "bad"
        assert "blocked ISO/broker" in result["decline_reason"]


def test_dolphin_requires_two_positions_unless_previously_submitted() -> None:
    cfg = load_config()
    for positions in (None, 0, 1):
        result = score_uw_deal(_deal(position_count=positions, previously_submitted=False), cfg)
        assert result["tier"] == "bad"
        assert "active lender positions" in result["decline_reason"]
    assert score_uw_deal(_deal(position_count=2), cfg)["tier"] == "good"
    assert score_uw_deal(_deal(position_count=1, previously_submitted=True), cfg)["tier"] == "good"


def test_dolphin_blocks_restricted_states_and_more_than_five_positions() -> None:
    cfg = load_config()
    for state in ("Texas", "UT", "Virginia", "VA"):
        result = score_uw_deal(_deal(state=state), cfg)
        assert result["tier"] == "bad"
        assert "restricted state" in result["decline_reason"]
    result = score_uw_deal(_deal(position_count=6), cfg)
    assert result["tier"] == "bad"
    assert "active lender positions 6 > 5" in result["decline_reason"]


def test_dolphin_uses_sheet_monthly_leverage_and_requires_under_40() -> None:
    cfg = load_config()
    for leverage in (40, 41):
        result = score_uw_deal(_deal(sheet_monthly_leverage=leverage, leverage_pct=10), cfg)
        assert result["tier"] == "bad"
        assert "monthly leverage" in result["decline_reason"]
    assert score_uw_deal(_deal(sheet_monthly_leverage=39.99, leverage_pct=80), cfg)["tier"] == "good"


def test_dolphin_blocks_known_payoff_below_15000_but_allows_blank() -> None:
    cfg = load_config()
    low = _deal(counted_funders=[{"funder": "Generic", "payoff_amount": 14_999}])
    result = score_uw_deal(low, cfg)
    assert result["tier"] == "bad"
    assert "payoff amount" in result["decline_reason"]
    blank = _deal(counted_funders=[{"funder": "Generic", "payoff_amount": None}])
    assert score_uw_deal(blank, cfg)["tier"] == "good"


def test_preferred_funder_forces_review_except_nationwide() -> None:
    cfg = load_config()
    names = [
        "DLP", "CFG", "CFG MS", "FDM", "Forward Financing", "Square Advance",
        "Overton Funding", "Flow Capital", "Can Capital", "Capitas", "Legend",
        "MCA Servicing",
    ]
    for name in names:
        preferred = _deal(
            state="Texas", position_count=1, previously_submitted=False,
            counted_funders=[{"funder": name, "payoff_amount": 5_000}],
        )
        assert score_uw_deal(preferred, cfg)["tier"] in {"good", "review"}
    preferred = _deal(counted_funders=[{"funder": "DLP", "payoff_amount": 5_000}])
    preferred["iso_broker"] = "Nationwide Advance"
    result = score_uw_deal(preferred, cfg)
    assert result["tier"] == "bad"
    assert "blocked ISO/broker" in result["decline_reason"]


def test_telegram_boundary_blocks_stale_ineligible_candidate(monkeypatch) -> None:
    called = False

    def fake_api(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr("scrubber.telegram_bridge.api", fake_api)
    candidate = {"lead_data": _deal(position_count=1, previously_submitted=False), "tier": "good", "score": 99}
    result = send_deal({"EZRA_TELEGRAM_CHAT_ID": "123"}, candidate, "candidate-id")
    assert not result["ok"]
    assert "active lender positions 1 < 2" in result["error"]
    assert not called


def test_telegram_packet_shows_funder_date_and_payoff_numbers() -> None:
    deal = _deal()
    deal["uw_all_positions"] = [{
        "funder": "Generic Capital", "cadence": "weekly", "paid_off": False,
        "leverage_pct": 12.5, "date_funded": "2026-06-01", "payoff_amount": 20_000,
    }]
    packet = format_packet({"lead_data": deal, "tier": "good", "score": 90})
    assert "funded 2026-06-01" in packet
    assert "payoff $20,000" in packet
