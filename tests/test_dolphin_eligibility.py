from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scrubber.scoring import load_config  # noqa: E402
from scrubber.telegram_bridge import send_deal  # noqa: E402
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
    }
    deal.update(overrides)
    return deal


def test_dolphin_blocks_every_nationwide_iso_variant() -> None:
    cfg = load_config()
    for iso in ("Nationwide", "Nationwide Advance", "The Nationwide ISO Shop"):
        result = score_uw_deal(_deal(iso_broker=iso), cfg)
        assert result["tier"] == "bad"
        assert "blocked ISO/broker" in result["decline_reason"]


def test_dolphin_requires_two_known_active_lender_positions() -> None:
    cfg = load_config()
    for positions in (None, 0, 1):
        result = score_uw_deal(_deal(position_count=positions), cfg)
        assert result["tier"] == "bad"
        assert "active lender positions" in result["decline_reason"]
    assert score_uw_deal(_deal(position_count=2), cfg)["tier"] == "good"


def test_telegram_boundary_blocks_stale_ineligible_candidate(monkeypatch) -> None:
    called = False

    def fake_api(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr("scrubber.telegram_bridge.api", fake_api)
    candidate = {"lead_data": _deal(position_count=1), "tier": "good", "score": 99}
    result = send_deal({"EZRA_TELEGRAM_CHAT_ID": "123"}, candidate, "candidate-id")
    assert not result["ok"]
    assert "active lender positions 1 < 2" in result["error"]
    assert not called
