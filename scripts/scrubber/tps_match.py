"""scrubber/tps_match.py — record-scoped matching for people-search results.

WHY THIS MODULE EXISTS
uw_lead_enricher._extract_contacts() regexes the ENTIRE results page and takes
phones[0] — the first phone-shaped string anywhere on it. A people-search query
for a common name returns MANY individuals, so that is whichever person happens
to sort first. Worse, _confidence() awards MEDIUM whenever the owner name and
city appear in the text, which is guaranteed because the query terms are echoed
back on the page. Net effect: on any multi-result page the pipeline would attach
a STRANGER's phone number to a merchant and label it MEDIUM confidence.

That is a data-integrity bug, not a matching inefficiency — a wrong number on a
funded merchant's file is worse than no number. This module replaces
page-scoped scraping with RECORD-scoped matching:

    parse_records(text) -> [PersonRecord]          split the page into people
    select_record(records, merchant) -> MatchResult  pick THE merchant, or none

The selection rules, in order:
  1. Name must match. Records that don't are discarded outright.
  2. One survivor -> that's the match (confidence from address agreement).
  3. Several survivors -> disambiguate by DATE OF BIRTH (the collision filter).
  4. DOB missing/unusable (older applications) -> fall back to address, then to
     an explicit NEEDS_REVIEW outcome.

Rule 5 is the one that matters most: when the set stays ambiguous we return NO
phone and flag for manual review. We never guess between people.

LAYOUT CAVEAT: the record splitter reads the plain-text rendering produced by
research_fetch, keyed on the "Name, Age NN" header each result card starts with.
That shape is pinned by the fixtures in tests/test_tps_match.py. It has NOT been
validated against a live page — as of 2026-07-21 TruePeopleSearch serves an HTTP
403 captcha interstitial to this host, so no live result page can be obtained
(see scripts/tps_probe.py). Treat parse_records() as the tunable layer: the
selection logic below is provider-agnostic and does not change if the splitter
is retargeted at a different provider's JSON.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

# ── outcomes ────────────────────────────────────────────────────────────────

NO_RECORDS = "no_records"            # nothing came back / nothing named right
UNIQUE = "unique"                    # exactly one candidate after name+address
DOB_MATCH = "dob_match"              # collision resolved by date of birth
DOB_NO_MATCH = "dob_no_match"        # DOB known, matched nobody -> review
ADDRESS_MATCH = "address_match"      # collision resolved by address (no DOB)
NEEDS_REVIEW = "needs_review"        # still ambiguous -> human or CLEAR

#: Outcomes that carry a usable phone number.
RESOLVED = frozenset({UNIQUE, DOB_MATCH, ADDRESS_MATCH})

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}
_MONTHS.update({m[:3].lower(): i for m, i in list(_MONTHS.items())})

_PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-]?)?(?:\(([2-9]\d{2})\)|([2-9]\d{2}))[\s.\-]?(\d{3})[\s.\-]?(\d{4})\b"
)
# "Dana Rivera, 41" / "Dana Rivera, Age 41" / "Dana Rivera Age: 41"
# Name tokens allow a SINGLE character so middle initials ("Dana M Rivera") are
# kept — they are ubiquitous on people-search pages, and dropping those records
# silently shrinks the candidate set, which is exactly how a collision gets
# mis-resolved.
_HEADER_RE = re.compile(
    r"^\s*(?P<name>[A-Z][A-Za-z'\-.]*(?:\s+[A-Z][A-Za-z'\-.]*){1,3})\s*,?\s*"
    r"(?:age\s*:?\s*)?(?P<age>\d{1,3})\s*$",
    re.I | re.M,
)
_AGE_RE = re.compile(r"\bage\s*:?\s*(\d{1,3})\b", re.I)
_DOB_LINE_RE = re.compile(
    r"\b(?:dob|d\.o\.b\.?|date of birth|born)\b\s*:?\s*(?P<val>[A-Za-z0-9 ,/.\-]{4,20})", re.I
)
_LIVES_RE = re.compile(r"\b(?:lives in|current address|address)\b\s*:?\s*(?P<val>.+)", re.I)
_STATE_RE = re.compile(r"\b([A-Z]{2})\b")
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


# ── dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class PersonRecord:
    """One individual from a people-search result page."""
    name: str = ""
    age: Optional[int] = None
    dob_iso: Optional[str] = None          # full date, when the page gives one
    dob_year: Optional[int] = None         # year alone (from "Born 1985" or age)
    dob_month: Optional[int] = None
    city: str = ""
    state: str = ""
    zip_code: str = ""
    street: str = ""
    phones: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def phone(self) -> Optional[str]:
        return self.phones[0] if self.phones else None


@dataclass
class MatchResult:
    outcome: str
    record: Optional[PersonRecord] = None
    confidence: str = LOW
    reason: str = ""
    considered: int = 0
    name_matched: int = 0

    @property
    def resolved(self) -> bool:
        return self.outcome in RESOLVED and self.record is not None

    @property
    def phone(self) -> Optional[str]:
        return self.record.phone if self.resolved and self.record else None

    @property
    def needs_manual_review(self) -> bool:
        return self.outcome in (NEEDS_REVIEW, DOB_NO_MATCH)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "confidence": self.confidence,
            "reason": self.reason,
            "considered": self.considered,
            "name_matched": self.name_matched,
            "phone": self.phone,
            "matched_name": self.record.name if self.record else None,
        }


# ── normalization ───────────────────────────────────────────────────────────

def normalize_phone_digits(raw: str) -> Optional[str]:
    """A US phone as bare 10 digits, or None. Drops a leading country code."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01" or digits[3] in "01":
        return None
    return digits


def normalize_dob(value: Any) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Normalize any DOB representation to (iso_or_None, year, month).

    Both sides of the comparison go through this, which is the whole point:
    the underwriting sheet gives an ISO date (mca_lead_scrubber._dob_iso), while
    a people-search page may give a full date, a month+year ("Born June 1985"),
    or nothing but an age. Reducing both to the same triple lets us compare at
    whatever precision is actually available instead of failing on format.

    Returns (None, None, None) for anything unusable — never raises.
    """
    if value in (None, ""):
        return None, None, None
    if isinstance(value, datetime):
        d = value.date()
        return d.isoformat(), d.year, d.month
    if isinstance(value, date):
        return value.isoformat(), value.year, value.month

    s = str(value).strip()
    if not s:
        return None, None, None

    # Full dates, most specific first.
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m.%d.%Y",
                "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.isoformat(), d.year, d.month
        except ValueError:
            continue
    # ISO with a time component.
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return d.isoformat(), d.year, d.month
    except ValueError:
        pass

    # Month + year, no day ("June 1985", "Jun 1985", "06/1985").
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{4})", s)
    if m and m.group(1).lower() in _MONTHS:
        return None, int(m.group(2)), _MONTHS[m.group(1).lower()]
    m = re.fullmatch(r"(\d{1,2})[/-](\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return None, int(m.group(2)), int(m.group(1))

    # Bare year.
    m = re.fullmatch(r"(19|20)\d{2}", s)
    if m:
        return None, int(s), None
    return None, None, None


def year_from_age(age: Optional[int], today: Optional[date] = None) -> Optional[int]:
    """Approximate birth year from an age. Ambiguous by one year — whether the
    birthday has passed this year is unknown — so callers must treat it as a
    +/-1 band, which dob_matches() does."""
    if age is None or not (0 < age < 120):
        return None
    today = today or datetime.now(timezone.utc).date()
    return today.year - age


def dob_matches(record: PersonRecord, dob_iso: str, today: Optional[date] = None) -> bool:
    """Does this person's DOB agree with the merchant's, at the best precision
    both sides support? Compares exact date when both have one, else year+month,
    else year, else an age-derived year with a +/-1 tolerance.

    Deliberately strict-by-precision: it never upgrades a coarse agreement into
    a match at a precision the data doesn't support, but it also never rejects a
    person merely because the page gave less detail than the sheet."""
    want_iso, want_y, want_m = normalize_dob(dob_iso)
    if want_y is None:
        return False

    if record.dob_iso and want_iso:
        return record.dob_iso == want_iso
    if record.dob_year is not None:
        if record.dob_year != want_y:
            return False
        if record.dob_month is not None and want_m is not None:
            return record.dob_month == want_m
        return True
    # Only an age is available — a one-year band, since the birthday may not
    # have passed yet this year.
    approx = year_from_age(record.age, today)
    if approx is None:
        return False
    return abs(approx - want_y) <= 1


# ── name / address comparison ───────────────────────────────────────────────

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "md", "dds", "esq"}


def _name_tokens(name: str) -> list[str]:
    toks = re.findall(r"[a-z]+", (name or "").lower())
    return [t for t in toks if t not in _SUFFIXES and len(t) > 1]


def name_matches(record_name: str, merchant_name: str) -> bool:
    """First and last name must both be present. Middle names/initials are
    ignored so "Dana M Rivera" still matches "Dana Rivera"."""
    r, m = _name_tokens(record_name), _name_tokens(merchant_name)
    if len(r) < 2 or len(m) < 2:
        return False
    return m[0] == r[0] and m[-1] == r[-1]


def _norm_street(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def address_score(record: PersonRecord, merchant: dict[str, Any]) -> int:
    """0-3: how strongly this person's address agrees with the merchant's.
    street=2 (nearly decisive), city=1, state=1, mismatched state=-1."""
    score = 0
    street = str(merchant.get("street") or "")
    city = str(merchant.get("city") or "").strip().lower()
    state = str(merchant.get("state") or "").strip().upper()
    zip_code = str(merchant.get("zip") or "").strip()[:5]

    if street and record.street:
        a, b = _norm_street(street), _norm_street(record.street)
        if a and b and (a in b or b in a):
            score += 2
    if city and record.city and city == record.city.strip().lower():
        score += 1
    if state and record.state:
        score += 1 if state == record.state.strip().upper() else -1
    if zip_code and record.zip_code and zip_code == record.zip_code[:5]:
        score += 1
    return score


# ── parsing ─────────────────────────────────────────────────────────────────

def parse_records(text: str) -> list[PersonRecord]:
    """Split a people-search results page into one PersonRecord per individual.

    Segments on the "Name, Age NN" header each card opens with; everything up to
    the next header belongs to that person. This is the layout-sensitive part —
    see the module docstring.
    """
    if not text or not text.strip():
        return []
    headers = list(_HEADER_RE.finditer(text))
    if not headers:
        return []

    records: list[PersonRecord] = []
    for i, h in enumerate(headers):
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]
        rec = PersonRecord(name=h.group("name").strip(), raw=block)

        try:
            rec.age = int(h.group("age"))
        except (TypeError, ValueError):
            rec.age = None
        if rec.age is None:
            m = _AGE_RE.search(block)
            if m:
                rec.age = int(m.group(1))

        m = _DOB_LINE_RE.search(block)
        if m:
            iso, y, mo = normalize_dob(m.group("val").strip().rstrip(".,"))
            rec.dob_iso, rec.dob_year, rec.dob_month = iso, y, mo
        if rec.dob_year is None and rec.age is not None:
            rec.dob_year = None  # age stays an approximation; see dob_matches

        m = _LIVES_RE.search(block)
        if m:
            loc = m.group("val").strip()
            rec.street = loc
            zm = _ZIP_RE.search(loc)
            if zm:
                rec.zip_code = zm.group(1)
            sm = _STATE_RE.search(loc)
            if sm:
                rec.state = sm.group(1)
            parts = [p.strip() for p in loc.split(",") if p.strip()]
            if len(parts) >= 2:
                rec.city = re.sub(r"\s+[A-Z]{2}\b.*$", "", parts[-1]).strip() or parts[-2]
                if len(parts) >= 3:
                    rec.city = parts[-2]
            if rec.city:
                rec.city = re.sub(r"\s*\d{5}(-\d{4})?$", "", rec.city).strip()

        seen: set[str] = set()
        for pm in _PHONE_RE.finditer(block):
            digits = normalize_phone_digits(pm.group(0))
            if digits and digits not in seen:
                seen.add(digits)
                rec.phones.append(digits)
        records.append(rec)
    return records


# ── selection ───────────────────────────────────────────────────────────────

def select_record(
    records: list[PersonRecord],
    merchant: dict[str, Any],
    today: Optional[date] = None,
) -> MatchResult:
    """Pick THE merchant out of a result set, or decline to guess.

    `merchant` keys: name (required), dob (ISO or any parseable form, optional),
    street, city, state, zip.
    """
    considered = len(records)
    if not records:
        return MatchResult(NO_RECORDS, reason="no records on the page", considered=0)

    merchant_name = str(merchant.get("name") or "")
    named = [r for r in records if name_matches(r.name, merchant_name)]
    if not named:
        return MatchResult(
            NO_RECORDS, reason=f"no record matched the name {merchant_name!r}",
            considered=considered)

    # Only people with a phone can resolve anything.
    withphone = [r for r in named if r.phones]
    pool = withphone or named
    name_matched = len(named)

    if len(pool) == 1:
        rec = pool[0]
        score = address_score(rec, merchant)
        conf = HIGH if score >= 2 else (MEDIUM if score >= 1 else LOW)
        return MatchResult(
            UNIQUE, rec, conf,
            f"single name match (address score {score})", considered, name_matched)

    # ---- collision ----
    dob_iso = merchant.get("dob")
    if dob_iso:
        hits = [r for r in pool if dob_matches(r, str(dob_iso), today)]
        if len(hits) == 1:
            rec = hits[0]
            score = address_score(rec, merchant)
            return MatchResult(
                DOB_MATCH, rec, HIGH if score >= 1 else MEDIUM,
                f"{len(pool)} name matches narrowed to 1 by DOB", considered, name_matched)
        if len(hits) > 1:
            # Same name AND same DOB — break the tie on address, else decline.
            best = _best_by_address(hits, merchant)
            if best is not None:
                return MatchResult(
                    DOB_MATCH, best, MEDIUM,
                    f"{len(hits)} shared a DOB; resolved on address", considered, name_matched)
            return MatchResult(
                NEEDS_REVIEW, None, LOW,
                f"{len(hits)} records share the name AND DOB — cannot separate",
                considered, name_matched)
        # DOB known and matched nobody: the right person is probably not on this
        # page. Returning any of these would be a guess.
        return MatchResult(
            DOB_NO_MATCH, None, LOW,
            f"{len(pool)} name matches, none agreed with DOB {dob_iso}",
            considered, name_matched)

    # ---- collision, no DOB (older applications) ----
    best = _best_by_address(pool, merchant)
    if best is not None:
        return MatchResult(
            ADDRESS_MATCH, best, MEDIUM,
            f"no DOB on file; {len(pool)} name matches resolved on address",
            considered, name_matched)
    return MatchResult(
        NEEDS_REVIEW, None, LOW,
        f"no DOB on file and {len(pool)} name matches are indistinguishable",
        considered, name_matched)


def _best_by_address(records: list[PersonRecord], merchant: dict[str, Any]) -> Optional[PersonRecord]:
    """The single clear address winner, or None. Requires a positive score AND a
    strict lead over the runner-up — a tie is not a resolution."""
    scored = sorted(((address_score(r, merchant), r) for r in records),
                    key=lambda t: t[0], reverse=True)
    if not scored or scored[0][0] <= 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


# ── merchant view + throttling ──────────────────────────────────────────────

def merchant_from_lead(data: dict[str, Any]) -> dict[str, Any]:
    """Project a lead_data record onto the keys select_record expects. Prefers
    the OWNER's personal address — people-search indexes individuals, so the
    home address discriminates better than the business one."""
    return {
        "name": data.get("owner_name") or data.get("contact_name") or data.get("name"),
        "dob": data.get("owner_dob") or data.get("dob"),
        "street": data.get("owner_address_line1") or data.get("home_address")
                  or data.get("business_address_line1") or data.get("address"),
        "city": data.get("owner_address_city") or data.get("home_city")
                or data.get("business_city") or data.get("city"),
        "state": data.get("owner_address_state") or data.get("home_state")
                 or data.get("business_state_code") or data.get("state_code"),
        "zip": data.get("owner_address_zip") or data.get("home_zip")
               or data.get("business_zip") or data.get("zip"),
    }


class RateLimiter:
    """Minimum spacing between outbound calls, for when disambiguation needs to
    open per-record detail pages. Process-local and deliberately simple — the
    enricher is a single-process loop, so a token bucket would be overkill."""

    def __init__(self, min_interval_s: float = 2.0, max_calls: int = 8) -> None:
        self.min_interval_s = min_interval_s
        self.max_calls = max_calls
        self._last = 0.0
        self._count = 0

    @property
    def exhausted(self) -> bool:
        return self._count >= self.max_calls

    def acquire(self) -> bool:
        """Block until the next call is allowed. False when the per-lookup
        budget is spent, so callers degrade to NEEDS_REVIEW instead of hammering
        a provider (or burning paid lookups) on one ambiguous merchant."""
        if self.exhausted:
            return False
        wait = self.min_interval_s - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self._count += 1
        return True
