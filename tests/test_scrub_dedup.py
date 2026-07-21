"""test_scrub_dedup.py — one review card per DEAL, refreshed in place.

Guards the 2026-07-21 fix. A Breeze UW Sheet is a LIVE document: the underwriter
fills funder rows in over minutes, and the scrubber re-reads it every tick. The
old row_hash keyed on `mca_positions`, so every edit minted a new card — 163 of
476 pending cards were redundant, one deal staged 6 times from a single sheet.

Run: /srv/sunbiz/ceo-agent/.venv/bin/python -m pytest tests/test_scrub_dedup.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scrubber import push, state as st  # noqa: E402


def _deal(**over: Any) -> dict[str, Any]:
    d = {
        "business_name": "SHOAL CREEK TAVERN LLC",
        "company": "SHOAL CREEK TAVERN LLC",
        "state": "Texas",
        "source_file_id": "drive-file-abc123",
        "mca_positions": 0,
        "monthly_revenue": 228423.0,
        "scrubbed_at": "2026-07-21T16:00:00+00:00",
    }
    d.update(over)
    return d


# ── identity ────────────────────────────────────────────────────────────────

def test_same_sheet_stable_across_underwriter_edits():
    """THE regression. Positions and revenue change as the sheet is worked;
    the deal is still the same deal."""
    base = st.row_hash(_deal())
    assert st.row_hash(_deal(mca_positions=3)) == base
    assert st.row_hash(_deal(mca_positions=7, monthly_revenue=461703.72)) == base
    assert st.row_hash(_deal(scrubbed_at="2026-07-21T17:30:00+00:00")) == base
    # The exact live sequence that produced 6 cards for nexgen networks corp 720.
    hashes = {st.row_hash(_deal(mca_positions=p)) for p in (0, 1, 2, 5, 6, 7)}
    assert len(hashes) == 1, "one deal must produce exactly one identity"


def test_different_sheets_are_different_deals():
    assert st.row_hash(_deal(source_file_id="file-A")) != st.row_hash(_deal(source_file_id="file-B"))


def test_same_business_resubmitted_as_a_new_sheet_is_a_new_deal():
    """A genuine re-submission arrives as a NEW Drive file and must surface
    again — dedup must not swallow real repeat business."""
    assert st.row_hash(_deal(source_file_id="file-jan")) != st.row_hash(_deal(source_file_id="file-jun"))


def test_non_uw_lead_falls_back_to_field_identity():
    """CSV-imported leads have no source file; identity stays field-based and
    must NOT vary with position count (the old bug)."""
    csv_lead = {"business_name": "ACME LLC", "state": "TX", "email": "a@b.com"}
    h = st.row_hash(csv_lead)
    assert st.row_hash({**csv_lead, "mca_positions": 4}) == h
    assert st.row_hash({**csv_lead, "email": "other@b.com"}) != h


def test_structured_funders_fingerprint():
    """current_funders_text is a dead key on the UW shape; the structured list
    must still contribute a stable fingerprint for the CSV path."""
    a = {"business_name": "ACME", "current_funders": [{"funder": "Bizfund"}, {"funder": "Forward"}]}
    b = {"business_name": "ACME", "current_funders": [{"funder": "Forward"}, {"funder": "Bizfund"}]}
    assert st.row_hash(a) == st.row_hash(b), "funder order must not change identity"
    c = {"business_name": "ACME", "current_funders": [{"funder": "Bizfund"}]}
    assert st.row_hash(a) != st.row_hash(c)


# ── staging behaviour ───────────────────────────────────────────────────────

class FakeTable:
    def __init__(self, store: dict, log: list):
        self.store, self.log = store, log
        self._op = None
        self._payload = None
        self._id = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def eq(self, col, val):
        if col == "id":
            self._id = val
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def execute(self):
        if self._op == "select":
            return type("R", (), {"data": list(self.store.values())})()
        if self._op == "insert":
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for r in rows:
                rid = f"id-{len(self.store) + 1}"
                rec = {**r, "id": rid}
                self.store[rid] = rec
                out.append(rec)
                self.log.append(("insert", r.get("row_hash")))
            return type("R", (), {"data": out})()
        if self._op == "update":
            self.store[self._id].update(self._payload)
            self.log.append(("update", self._id))
            return type("R", (), {"data": [self.store[self._id]]})()
        raise AssertionError("unexpected op")


class FakeSB:
    def __init__(self, store=None):
        self.store = store or {}
        self.log: list = []

    def table(self, _name):
        return FakeTable(self.store, self.log)


def _candidate(positions: int, h: str) -> dict[str, Any]:
    return {
        "data": _deal(mca_positions=positions),
        "score_result": {"tier": "good", "score": 80, "reasons": ["ok"],
                         "leverage_pct": 12.0, "monthly_revenue": 228423.0},
        "row_hash": h,
    }


REF = {"id": "drive-file-abc123", "name": "UW Sheet_1_Shoal Creek"}
CFG = {"version": "test", "gate": {"mode": "require_ezra"}}


def test_first_scrape_inserts(monkeypatch):
    monkeypatch.setattr(push, "_notify_ezra", lambda *a, **k: None)
    sb = FakeSB()
    h = st.row_hash(_deal())
    res = push.stage_candidates(sb, {}, CFG, REF, [_candidate(0, h)])
    assert res["inserted"] == {h}
    assert [op for op, _ in sb.log] == ["insert"]


def test_rescrape_refreshes_in_place_without_renotifying(monkeypatch):
    """The core fix: same deal, newer data -> UPDATE, no second card, no ping."""
    notifies: list = []
    monkeypatch.setattr(push, "_notify_ezra", lambda env, rows: notifies.append(rows))
    sb = FakeSB()
    h = st.row_hash(_deal())
    push.stage_candidates(sb, {}, CFG, REF, [_candidate(0, h)])
    notifies.clear()

    res = push.stage_candidates(sb, {}, CFG, REF, [_candidate(7, h)])
    assert res["refreshed"] == {h}
    assert res["inserted"] == set()
    assert len(sb.store) == 1, "still exactly one card for the deal"
    assert not notifies, "a refresh must not re-ping Ezra"
    only = next(iter(sb.store.values()))
    assert only["lead_data"]["mca_positions"] == 7, "card carries the newest data"


@pytest.mark.parametrize("decided", ["approved", "declined"])
def test_decided_cards_are_never_touched(monkeypatch, decided):
    """A deal Ezra already ruled on must not be resurrected or rewritten."""
    monkeypatch.setattr(push, "_notify_ezra", lambda *a, **k: None)
    h = st.row_hash(_deal())
    sb = FakeSB({"id-1": {"id": "id-1", "row_hash": h, "status": decided,
                          "lead_data": _deal(mca_positions=2)}})
    res = push.stage_candidates(sb, {}, CFG, REF, [_candidate(7, h)])
    assert res["skipped"] == {h}
    assert res["refreshed"] == set()
    assert sb.log == [], "no write of any kind against a decided card"
    assert sb.store["id-1"]["lead_data"]["mca_positions"] == 2


def test_refresh_preserves_reviewer_columns(monkeypatch):
    """The refresh patch must not clobber identity or reviewer state."""
    monkeypatch.setattr(push, "_notify_ezra", lambda *a, **k: None)
    h = st.row_hash(_deal())
    sb = FakeSB({"id-1": {"id": "id-1", "row_hash": h, "status": "pending_review",
                          "tenant_id": "t1", "created_at": "2026-07-21T16:00:00Z",
                          "lead_data": _deal()}})
    push.stage_candidates(sb, {}, CFG, REF, [_candidate(7, h)])
    row = sb.store["id-1"]
    assert row["status"] == "pending_review"
    assert row["row_hash"] == h
    assert row["tenant_id"] == "t1"
    assert row["created_at"] == "2026-07-21T16:00:00Z"
    for forbidden in ("reviewed_by", "reviewed_at", "created_lead_id"):
        assert forbidden not in row, f"refresh must not write {forbidden}"


def test_refresh_failure_is_reported_for_retry(monkeypatch):
    """A failed refresh must land in `failed` so the caller leaves it unseen."""
    monkeypatch.setattr(push, "_notify_ezra", lambda *a, **k: None)
    monkeypatch.setattr(push, "_refresh_candidate", lambda *a, **k: False)
    h = st.row_hash(_deal())
    sb = FakeSB({"id-1": {"id": "id-1", "row_hash": h, "status": "pending_review"}})
    res = push.stage_candidates(sb, {}, CFG, REF, [_candidate(7, h)])
    assert res["failed"] == {h}
    assert res["refreshed"] == set()


def test_bad_tier_never_surfaces(monkeypatch):
    monkeypatch.setattr(push, "_notify_ezra", lambda *a, **k: None)
    sb = FakeSB()
    c = _candidate(0, "h")
    c["score_result"]["tier"] = "bad"
    res = push.stage_candidates(sb, {}, CFG, REF, [c])
    assert res == {"inserted": set(), "skipped": set(), "failed": set(), "refreshed": set()}
    assert sb.log == []
