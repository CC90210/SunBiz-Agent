"""test_phone_lookup_state.py — the verdict a lead carries after a phone lookup.

The operator queue is driven entirely by these keys, so the distinction that
matters most is "the lookup RAN and found nothing" versus "the lookup could not
run". They are opposite instructions to a human: the first means stop looking,
the second means go do it by hand in CLEAR. From this host the captcha
interstitial strips down to the 20-character string "truepeoplesearch.com",
which would otherwise parse to zero records and be reported as "nobody by that
name exists".

Run: /srv/sunbiz/ceo-agent/.venv/bin/python -m pytest tests/test_phone_lookup_state.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uw_lead_enricher as E  # noqa: E402

LEAD = {
    "owner_name": "Dana Rivera",
    "owner_dob": "1985-06-15",
    "owner_address_line1": "100 Example St",
    "owner_address_city": "Austin",
    "owner_address_state": "TX",
}

RESULTS_PAGE = """
Dana Rivera, 41
Lives in 100 Example St, Austin, TX 78701
Phone Numbers: (512) 555-0142

Dana Rivera, 67
Lives in 900 Other Rd, Dallas, TX 75201
Phone Numbers: (214) 555-0188
""" + ("filler to clear the minimum-page-length floor. " * 20)


def verdict(text: str, lead: dict | None = None) -> dict:
    return E._select_tps_contact(text, "https://tps/results", lead if lead is not None else LEAD) or {}


# ── could-not-run vs ran-and-found-nothing ──────────────────────────────────

def test_captcha_page_is_not_a_no_match():
    v = verdict("Captcha Challenge - TruePeopleSearch.com " + "x" * 500)
    assert v["phone_lookup_status"] == "manual_review"
    assert v["phone_lookup_outcome"] == "provider_unavailable"
    assert "captcha" in v["phone_lookup_reason"].lower()


def test_stripped_challenge_page_is_not_a_no_match():
    """The exact live symptom: research_fetch returns just the bare domain."""
    v = verdict("truepeoplesearch.com")
    assert v["phone_lookup_status"] == "manual_review"
    assert v["phone_lookup_outcome"] == "provider_unavailable"


@pytest.mark.parametrize("text", ["", "   ", "short", "a" * 199])
def test_any_too_short_page_routes_to_manual(text):
    assert verdict(text)["phone_lookup_outcome"] == "provider_unavailable"


def test_real_page_with_no_matching_name_is_not_found():
    """A genuine result page that simply lacks this person must NOT be reported
    as 'go look it up by hand' — the lookup did its job."""
    page = "Marcus Chen, 52\nLives in Reno, NV\nPhone Numbers: (775) 555-0100\n" + ("filler. " * 40)
    v = verdict(page)
    assert v["phone_lookup_outcome"] == "no_records"
    assert v["phone_lookup_status"] == "not_found"


# ── resolved + operator hand-off payload ────────────────────────────────────

def test_dob_resolves_and_reports_found():
    v = verdict(RESULTS_PAGE)
    assert v["phone_lookup_status"] == "found"
    assert v["phone"] == "+15125550142"
    assert v["phone_lookup_matched_name"] == "Dana Rivera"


def test_unresolved_carries_everything_a_human_needs():
    v = verdict(RESULTS_PAGE, {"owner_name": "Dana Rivera"})  # no DOB, no address
    assert v["phone_lookup_status"] == "manual_review"
    assert "Dana Rivera" in v["phone_lookup_query"]
    assert "DOB unknown" in v["phone_lookup_query"]
    numbers = {c["number"] for c in v["phone_lookup_candidates"]}
    assert numbers == {"+15125550142", "+12145550188"}
    assert all(c.get("age") for c in v["phone_lookup_candidates"]), "age distinguishes same-name people"


def test_every_verdict_is_stamped_and_queryable():
    for text in ("truepeoplesearch.com", RESULTS_PAGE):
        v = verdict(text)
        assert v.get("phone_lookup_status")
        assert v.get("phone_lookup_checked_at")
        assert v.get("phone_lookup_query")


def test_query_includes_dob_when_known():
    assert "DOB 1985-06-15" in verdict(RESULTS_PAGE)["phone_lookup_query"]


# ── state refresh semantics ─────────────────────────────────────────────────

def test_lookup_state_refreshes_but_notified_at_is_sticky():
    """Verdicts must be allowed to change on a later pass, but the Telegram
    guard must not — refreshing it would re-ping Ezra on every loop."""
    lead = {
        "phone_lookup_status": "manual_review",
        "phone_lookup_reason": "old reason",
        "phone_lookup_notified_at": "2026-07-21T10:00:00+00:00",
    }
    changed = E._refresh_lookup_state(lead, {
        "phone_lookup_status": "found",
        "phone_lookup_reason": "new reason",
        "phone_lookup_notified_at": "2026-07-21T18:00:00+00:00",
    })
    assert lead["phone_lookup_status"] == "found"
    assert lead["phone_lookup_reason"] == "new reason"
    assert lead["phone_lookup_notified_at"] == "2026-07-21T10:00:00+00:00"
    assert "phone_lookup_notified_at" not in changed


def test_refresh_reports_only_actual_changes():
    lead = {"phone_lookup_status": "found"}
    assert E._refresh_lookup_state(lead, {"phone_lookup_status": "found"}) == []


def test_refresh_never_touches_non_lookup_keys():
    lead = {"phone": "+15125550142", "business_name": "Testco"}
    E._refresh_lookup_state(lead, {"phone": "+19999999999", "business_name": "Other",
                                   "phone_lookup_status": "found"})
    assert lead["phone"] == "+15125550142", "an operator-entered phone is never clobbered"
    assert lead["business_name"] == "Testco"
