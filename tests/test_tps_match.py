"""test_tps_match.py — record-scoped people-search matching + DOB collision filter.

The live fetch is captcha-blocked (see scripts/tps_probe.py), so these fixtures
ARE the contract for the page shape. The selection logic under test is
provider-agnostic: retargeting parse_records() at another provider should leave
every assertion below valid.

The bug this guards against: the previous implementation regexed the whole page
and took the first phone, so a search for a common name returned a STRANGER's
number labelled MEDIUM confidence.

Run: /srv/sunbiz/ceo-agent/.venv/bin/python -m pytest tests/test_tps_match.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scrubber import tps_match as T  # noqa: E402

TODAY = date(2026, 7, 21)

# Three different Dana Riveras — the collision this module exists to resolve.
COLLISION_PAGE = """
Dana Rivera, 41
Lives in 100 Example St, Austin, TX 78701
Phone Numbers: (512) 555-0142
Email: dana.rivera@example.com

Dana Rivera, 67
Lives in 900 Other Rd, Dallas, TX 75201
Phone Numbers: (214) 555-0188

Dana M Rivera, 29
Lives in 55 Third Ave, Houston, TX 77002
Phone Numbers: (713) 555-0155
"""

SINGLE_PAGE = """
Dana Rivera, 41
Lives in 100 Example St, Austin, TX 78701
Phone Numbers: (512) 555-0142
"""

DOB_PAGE = """
Dana Rivera, 41
Date of Birth: June 15, 1985
Lives in 100 Example St, Austin, TX 78701
Phone Numbers: (512) 555-0142

Dana Rivera, 41
Date of Birth: March 2, 1985
Lives in 900 Other Rd, Dallas, TX 75201
Phone Numbers: (214) 555-0188
"""

MERCHANT = {
    "name": "Dana Rivera",
    "street": "100 Example St",
    "city": "Austin",
    "state": "TX",
    "zip": "78701",
}


# ── parsing ─────────────────────────────────────────────────────────────────

def test_parse_splits_into_people():
    recs = T.parse_records(COLLISION_PAGE)
    assert len(recs) == 3
    assert [r.age for r in recs] == [41, 67, 29]
    # Each person's phone stays with that person — the core fix.
    assert recs[0].phones == ["5125550142"]
    assert recs[1].phones == ["2145550188"]
    assert recs[2].phones == ["7135550155"]


def test_parse_extracts_location():
    r = T.parse_records(SINGLE_PAGE)[0]
    assert r.state == "TX"
    assert r.zip_code == "78701"
    assert "100 Example St" in r.street


def test_parse_extracts_explicit_dob():
    recs = T.parse_records(DOB_PAGE)
    assert recs[0].dob_iso == "1985-06-15"
    assert recs[1].dob_iso == "1985-03-02"


def test_parse_empty_and_garbage():
    assert T.parse_records("") == []
    assert T.parse_records("   ") == []
    assert T.parse_records("no people here, just prose") == []


# ── DOB normalization: both sides reduced to a comparable form ──────────────

@pytest.mark.parametrize(
    "raw,expected_iso",
    [
        ("1985-06-15", "1985-06-15"),
        ("06/15/1985", "1985-06-15"),
        ("6/15/1985", "1985-06-15"),
        ("June 15, 1985", "1985-06-15"),
        ("Jun 15, 1985", "1985-06-15"),
        ("15 June 1985", "1985-06-15"),
        ("06.15.1985", "1985-06-15"),
    ],
)
def test_normalize_dob_full_dates(raw, expected_iso):
    assert T.normalize_dob(raw)[0] == expected_iso


def test_normalize_dob_partial_precision():
    """A page may give only month+year or a bare year; keep what's there rather
    than discarding the record."""
    assert T.normalize_dob("June 1985") == (None, 1985, 6)
    assert T.normalize_dob("06/1985") == (None, 1985, 6)
    assert T.normalize_dob("1985") == (None, 1985, None)


@pytest.mark.parametrize("raw", [None, "", "   ", "n/a", "not a date", "555-1234"])
def test_normalize_dob_rejects_garbage(raw):
    assert T.normalize_dob(raw) == (None, None, None)


def test_dob_matches_by_age_band():
    """With only an age, allow +/-1 year — the birthday may not have passed."""
    r = T.PersonRecord(name="Dana Rivera", age=41)
    assert T.dob_matches(r, "1985-06-15", today=TODAY)   # 2026-41 = 1985
    assert T.dob_matches(r, "1984-06-15", today=TODAY)   # within the band
    assert not T.dob_matches(r, "1975-06-15", today=TODAY)


def test_dob_matches_prefers_exact_when_both_full():
    r = T.PersonRecord(name="Dana Rivera", age=41, dob_iso="1985-06-15",
                       dob_year=1985, dob_month=6)
    assert T.dob_matches(r, "1985-06-15", today=TODAY)
    assert not T.dob_matches(r, "1985-03-02", today=TODAY)


# ── selection ───────────────────────────────────────────────────────────────

def test_single_match_resolves_high():
    res = T.select_record(T.parse_records(SINGLE_PAGE), MERCHANT, today=TODAY)
    assert res.outcome == T.UNIQUE
    assert res.confidence == T.HIGH      # street + city + state + zip agree
    assert res.phone == "5125550142"


def test_collision_resolved_by_dob():
    merchant = {**MERCHANT, "dob": "1985-06-15"}   # -> age 41
    res = T.select_record(T.parse_records(COLLISION_PAGE), merchant, today=TODAY)
    assert res.outcome == T.DOB_MATCH
    assert res.phone == "5125550142", "must pick the 41-year-old, not the first on the page"
    assert res.name_matched == 3


def test_collision_resolved_by_exact_dob_when_ages_tie():
    """Both are 41; only the explicit date separates them."""
    merchant = {**MERCHANT, "dob": "1985-03-02", "street": "", "city": "", "zip": ""}
    res = T.select_record(T.parse_records(DOB_PAGE), merchant, today=TODAY)
    assert res.outcome == T.DOB_MATCH
    assert res.phone == "2145550188"


def test_dob_matching_nobody_declines():
    """DOB known but agreeing with no one: the merchant isn't on this page.
    Returning any of these numbers would be a guess."""
    merchant = {**MERCHANT, "dob": "1950-01-01"}
    res = T.select_record(T.parse_records(COLLISION_PAGE), merchant, today=TODAY)
    assert res.outcome == T.DOB_NO_MATCH
    assert res.phone is None
    assert res.needs_manual_review


# ── backward compatibility: applications with no DOB ────────────────────────

def test_collision_without_dob_falls_back_to_address():
    res = T.select_record(T.parse_records(COLLISION_PAGE), MERCHANT, today=TODAY)
    assert res.outcome == T.ADDRESS_MATCH
    assert res.phone == "5125550142"
    assert res.confidence == T.MEDIUM, "address-only agreement is not HIGH"


@pytest.mark.parametrize("dob", [None, "", "n/a", "unknown"])
def test_null_dob_variants_do_not_crash(dob):
    """Older applications carry null/garbage DOB — must degrade, never raise."""
    res = T.select_record(T.parse_records(COLLISION_PAGE), {**MERCHANT, "dob": dob}, today=TODAY)
    assert res.outcome in (T.ADDRESS_MATCH, T.NEEDS_REVIEW, T.DOB_NO_MATCH)


def test_collision_without_dob_or_address_needs_review():
    """No DOB and nothing to separate them: refuse to guess."""
    bare = {"name": "Dana Rivera"}
    res = T.select_record(T.parse_records(COLLISION_PAGE), bare, today=TODAY)
    assert res.outcome == T.NEEDS_REVIEW
    assert res.phone is None
    assert res.needs_manual_review


def test_ambiguous_address_tie_declines():
    """A tie is not a resolution."""
    page = """
Dana Rivera, 41
Lives in 1 Same St, Austin, TX 78701
Phone Numbers: (512) 555-0001

Dana Rivera, 44
Lives in 1 Same St, Austin, TX 78701
Phone Numbers: (512) 555-0002
"""
    res = T.select_record(T.parse_records(page), {"name": "Dana Rivera", "city": "Austin", "state": "TX"}, today=TODAY)
    assert res.outcome == T.NEEDS_REVIEW
    assert res.phone is None


# ── name handling ───────────────────────────────────────────────────────────

def test_middle_name_still_matches():
    assert T.name_matches("Dana M Rivera", "Dana Rivera")
    assert T.name_matches("Dana Rivera Jr", "Dana Rivera")


def test_different_person_does_not_match():
    assert not T.name_matches("Dana Smith", "Dana Rivera")
    assert not T.name_matches("Rivera", "Dana Rivera")


def test_no_name_match_returns_no_records():
    res = T.select_record(T.parse_records(COLLISION_PAGE), {"name": "Marcus Chen"}, today=TODAY)
    assert res.outcome == T.NO_RECORDS
    assert res.phone is None


def test_empty_result_set():
    res = T.select_record([], MERCHANT, today=TODAY)
    assert res.outcome == T.NO_RECORDS
    assert not res.resolved


# ── phone normalization ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [("(512) 555-0142", "5125550142"), ("512-555-0142", "5125550142"),
     ("+1 512 555 0142", "5125550142"), ("1-512-555-0142", "5125550142")],
)
def test_phone_digits(raw, expected):
    assert T.normalize_phone_digits(raw) == expected


@pytest.mark.parametrize("raw", ["123", "", "011-555-0142", "512-555-014"])
def test_phone_digits_rejects_invalid(raw):
    assert T.normalize_phone_digits(raw) is None


# ── merchant projection + rate limiting ─────────────────────────────────────

def test_merchant_from_lead_prefers_owner_address():
    m = T.merchant_from_lead({
        "owner_name": "Dana Rivera",
        "owner_dob": "1985-06-15",
        "owner_address_line1": "100 Example St",
        "owner_address_city": "Austin",
        "owner_address_state": "TX",
        "business_city": "Dallas",
    })
    assert m["name"] == "Dana Rivera"
    assert m["dob"] == "1985-06-15"
    assert m["city"] == "Austin", "owner address must win over the business one"


def test_rate_limiter_budget():
    rl = T.RateLimiter(min_interval_s=0, max_calls=2)
    assert rl.acquire() and rl.acquire()
    assert not rl.acquire(), "budget exhausted -> caller degrades to review"
    assert rl.exhausted
