"""
SunBiz Funding — JotForm Lead Tracker
======================================
Production lead tracking via the JotForm REST API (https://api.jotform.com/).
Fetches submissions from the SunBiz Funding lead capture form, parses field
values, detects duplicates, and generates formatted conversion reports so the
marketing team can tie ad spend directly to qualified form fills.

Credentials loaded from .env.agents at the project root:
  JOTFORM_API_KEY  — JotForm API key (Settings → API → Create New Key)
  JOTFORM_FORM_ID  — Form ID (default: 253155026259254)

Rate limiting: 1-second delay between every API call (JotForm free tier).
Retry policy:  3 attempts, exponential backoff (5 s, 10 s, 20 s) on
               transient errors (network failures, HTTP 429/500/502/503/504).

Default form: 253155026259254 — "Sunbiz Funding First Form"
Fields: legalcorporateName, businessPhone, emailAddress,
        corporateOfficerowner71, typeA (always "Sunbiz Funding")
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("jotform_tracker")

# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------

env_path = os.path.join(os.path.dirname(__file__), '..', '.env.agents')
load_dotenv(env_path)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOTFORM_BASE_URL = "https://api.jotform.com"

RATE_LIMIT_DELAY = 1           # seconds between every API call
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 5         # seconds; doubles each attempt (5, 10, 20)

# HTTP status codes considered transient/retryable
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

# Known field slugs for the SunBiz Funding First Form.
# These are the 'name' values JotForm assigns to each question.
_FIELD_BUSINESS_NAME = "legalcorporateName"
_FIELD_PHONE = "businessPhone"
_FIELD_EMAIL = "emailAddress"
_FIELD_OWNER = "corporateOfficerowner71"
_FIELD_TYPE = "typeA"

# UTM tracking hidden fields (added 2026-03-22)
_FIELD_UTM_SOURCE = "utm_source"
_FIELD_UTM_MEDIUM = "utm_medium"
_FIELD_UTM_CAMPAIGN = "utm_campaign"
_FIELD_UTM_CONTENT = "utm_content"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _api_call(
    api_key: str,
    endpoint: str,
    params: Optional[dict[str, str]] = None,
) -> dict:
    """
    Execute a GET request against the JotForm REST API with retry logic.

    Appends apiKey to every request. Retries on network failures and transient
    HTTP error codes. Raises RuntimeError on non-transient errors.

    Args:
        api_key:  JotForm API key.
        endpoint: Path after the base URL, e.g. "form/253155026259254/submissions".
        params:   Optional additional query parameters.

    Returns:
        Parsed JSON response body as a dict.
    """
    url = f"{JOTFORM_BASE_URL}/{endpoint}"
    request_params: dict[str, str] = {"apiKey": api_key}
    if params:
        request_params.update(params)

    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(url, params=request_params, timeout=30)

            if resp.status_code in _TRANSIENT_STATUS_CODES:
                log.warning(
                    "Transient HTTP %s (attempt %d/%d): %s",
                    resp.status_code, attempt, RETRY_ATTEMPTS, url,
                )
                last_error = RuntimeError(f"HTTP {resp.status_code}")
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            if not resp.ok:
                raise RuntimeError(
                    f"JotForm API error HTTP {resp.status_code} for {endpoint}\n"
                    f"Response: {resp.text[:400]}"
                )

            body: dict = resp.json()

            # JotForm wraps all responses: {"responseCode": 200, "content": ...}
            response_code = body.get("responseCode", resp.status_code)
            if response_code not in (200, 201):
                raise RuntimeError(
                    f"JotForm API returned responseCode {response_code} "
                    f"for {endpoint}: {body.get('message', 'unknown error')}"
                )

            return body

        except requests.RequestException as exc:
            log.warning("Network error (attempt %d/%d): %s", attempt, RETRY_ATTEMPTS, exc)
            last_error = exc
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))

    raise RuntimeError(
        f"All {RETRY_ATTEMPTS} attempts failed for GET {endpoint}. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# Field parsing helpers
# ---------------------------------------------------------------------------

def _extract_answer(answers: dict, field_slug: str) -> str:
    """
    Extract the answer value for a specific field slug from a submission's
    answers dict.

    JotForm answers are keyed by question number. Each value has a 'name'
    (the field slug) and an 'answer' (the submitted value).

    Returns an empty string if the field is not present or has no answer.
    """
    for answer_obj in answers.values():
        if not isinstance(answer_obj, dict):
            continue
        if answer_obj.get("name", "") == field_slug:
            value = answer_obj.get("answer", "")
            if isinstance(value, dict):
                # Full-name compound fields: {"first": "...", "last": "..."}
                return " ".join(filter(None, [
                    value.get("first", ""),
                    value.get("last", ""),
                ])).strip()
            return str(value).strip() if value else ""
    return ""


def _parse_submission_date(created_at: str) -> Optional[datetime]:
    """
    Parse a JotForm created_at timestamp ("YYYY-MM-DD HH:MM:SS" UTC) into
    a timezone-aware datetime. Returns None if parsing fails.
    """
    try:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None


def _parse_since_date(since_date: Optional[str]) -> Optional[datetime]:
    """
    Parse a since_date string ("YYYY-MM-DD") into a timezone-aware datetime
    at midnight UTC. Returns None if input is None or blank.

    Raises ValueError if the string is non-None but cannot be parsed.
    """
    if not since_date:
        return None
    return datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Formatting helpers (match performance_reporter.py style)
# ---------------------------------------------------------------------------

def _divider(width: int = 55) -> str:
    return "-" * width


def _header(title: str, width: int = 60) -> str:
    return f"{'=' * width}\n  {title}\n{'=' * width}"


def _fmt_currency(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_pct(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}%"


# ---------------------------------------------------------------------------
# JotFormTracker
# ---------------------------------------------------------------------------

class JotFormTracker:
    """
    High-level client for tracking SunBiz Funding leads via the JotForm REST API.

    The form ID and API key are loaded once at construction time from .env.agents.
    All public methods return clean Python primitives — no raw response objects.

    Usage:
        tracker = JotFormTracker()
        tracker.generate_report(ad_spend=500.00, link_clicks=582, since_date='2026-03-19')
    """

    def __init__(self) -> None:
        """
        Load API key and form ID from .env.agents (already loaded by dotenv at
        module import time). Exits with a clear message if either is missing.
        """
        self.api_key: str = os.getenv("JOTFORM_API_KEY", "")
        self.form_id: str = os.getenv("JOTFORM_FORM_ID", "253155026259254")

        if not self.api_key or self.api_key.startswith("INSERT_"):
            log.error(
                "JOTFORM_API_KEY not set in .env.agents. "
                "Get your key at: https://www.jotform.com/myaccount/api"
            )
            sys.exit(1)

        if not self.form_id or self.form_id.startswith("INSERT_"):
            log.error("JOTFORM_FORM_ID not set in .env.agents.")
            sys.exit(1)

        log.info("JotFormTracker ready — form: %s", self.form_id)

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _call(self, endpoint: str, params: Optional[dict[str, str]] = None) -> dict:
        """Rate-limited wrapper around the module-level _api_call."""
        time.sleep(RATE_LIMIT_DELAY)
        return _api_call(self.api_key, endpoint, params=params)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_form_info(self) -> dict:
        """
        Return high-level metadata for the configured form.

        Returns:
            dict with keys:
              - title (str): Form title as set in JotForm.
              - status (str): "ENABLED", "DISABLED", etc.
              - total_count (int): All-time submission count.
              - new_count (int): Submissions since last check (JotForm "new" flag).
        """
        log.info("Fetching form info for %s ...", self.form_id)
        body = self._call(f"form/{self.form_id}")
        content: dict = body.get("content", {})
        return {
            "title": content.get("title", ""),
            "status": content.get("status", ""),
            "total_count": int(content.get("count", 0)),
            "new_count": int(content.get("new", 0)),
        }

    def get_submissions(
        self,
        since_date: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """
        Fetch all submissions, optionally filtered to on/after a given date.

        Paginates automatically through all available submissions in batches of
        up to 1000 (JotForm maximum per request).

        Args:
            since_date: ISO date string "YYYY-MM-DD". Only returns submissions
                        created on or after this date (UTC midnight). If None,
                        all submissions are returned.
            limit:      Maximum number of submissions to return in total.

        Returns:
            List of dicts, each with:
              - id (str): JotForm submission ID.
              - created_at (str): "YYYY-MM-DD HH:MM:SS" UTC timestamp.
              - business_name (str): Legal corporate name from the form.
              - owner_name (str): Corporate officer / owner name.
              - phone (str): Business phone number.
              - email (str): Email address.
              - status (str): JotForm submission status (e.g. "ACTIVE").
        """
        cutoff: Optional[datetime] = _parse_since_date(since_date)

        results: list[dict] = []
        offset = 0
        batch_size = min(limit, 1000)

        while len(results) < limit:
            log.info(
                "Fetching submissions (offset=%d, batch=%d) ...",
                offset, batch_size,
            )
            body = self._call(
                f"form/{self.form_id}/submissions",
                params={
                    "limit": str(batch_size),
                    "offset": str(offset),
                    "orderby": "created_at",
                    "direction": "DESC",
                },
            )
            batch: list[dict] = body.get("content", [])
            if not batch:
                break

            for raw in batch:
                created_raw = raw.get("created_at", "")
                created_dt = _parse_submission_date(created_raw)

                if created_dt is None:
                    log.warning("Could not parse created_at '%s' — skipping.", created_raw)
                    continue

                # If applying a date filter, stop once we reach older submissions.
                # Results are DESC by date, so the first item is newest.
                if cutoff and created_dt < cutoff:
                    # Signal outer loop to stop
                    offset = limit  # break outer while
                    break

                answers: dict = raw.get("answers", {})
                results.append({
                    "id": raw.get("id", ""),
                    "created_at": created_raw,
                    "business_name": _extract_answer(answers, _FIELD_BUSINESS_NAME),
                    "owner_name": _extract_answer(answers, _FIELD_OWNER),
                    "phone": _extract_answer(answers, _FIELD_PHONE),
                    "email": _extract_answer(answers, _FIELD_EMAIL),
                    "status": raw.get("status", ""),
                    "utm_source": _extract_answer(answers, _FIELD_UTM_SOURCE),
                    "utm_medium": _extract_answer(answers, _FIELD_UTM_MEDIUM),
                    "utm_campaign": _extract_answer(answers, _FIELD_UTM_CAMPAIGN),
                    "utm_content": _extract_answer(answers, _FIELD_UTM_CONTENT),
                })

                if len(results) >= limit:
                    break

            if len(batch) < batch_size:
                # Last page — no more data
                break

            offset += batch_size

        log.info("Fetched %d submission(s).", len(results))
        return results

    def get_daily_breakdown(self, since_date: Optional[str] = None) -> dict[str, int]:
        """
        Return the number of submissions per calendar day (UTC).

        Args:
            since_date: ISO date string "YYYY-MM-DD" to filter from. If None,
                        uses all submissions fetched (up to the default limit).

        Returns:
            Dict of {date_str: count} sorted chronologically, e.g.:
              {"2026-03-19": 12, "2026-03-20": 8, "2026-03-21": 15}
        """
        submissions = self.get_submissions(since_date=since_date)

        counts: dict[str, int] = defaultdict(int)
        for sub in submissions:
            date_str = sub["created_at"][:10]  # "YYYY-MM-DD"
            if date_str:
                counts[date_str] += 1

        # Sort chronologically
        return dict(sorted(counts.items()))

    def get_recent_leads(self, count: int = 10) -> list[dict]:
        """
        Return the N most recent submissions.

        Args:
            count: Number of recent submissions to return (default 10).

        Returns:
            List of submission dicts (see get_submissions for field reference),
            ordered newest first.
        """
        log.info("Fetching %d most recent lead(s) ...", count)
        return self.get_submissions(limit=count)

    def get_ad_submissions(
        self,
        since_date: Optional[str] = None,
    ) -> list[dict]:
        """
        Return only submissions that came from Meta ad campaigns (utm_source=meta).

        Args:
            since_date: ISO date "YYYY-MM-DD" filter.

        Returns:
            Filtered list of submission dicts where utm_source == "meta".
        """
        all_subs = self.get_submissions(since_date=since_date)
        return [s for s in all_subs if s.get("utm_source", "").lower() == "meta"]

    def get_campaign_breakdown(
        self,
        since_date: Optional[str] = None,
    ) -> dict[str, int]:
        """
        Break down ad-attributed submissions by campaign name (utm_campaign).

        Args:
            since_date: ISO date "YYYY-MM-DD" filter.

        Returns:
            Dict of {campaign_name: submission_count}, e.g.:
              {"social_proof": 8, "growth_capital": 3, "consolidation": 2}
        """
        ad_subs = self.get_ad_submissions(since_date=since_date)
        counts: dict[str, int] = defaultdict(int)
        for sub in ad_subs:
            campaign = sub.get("utm_campaign", "") or "unknown"
            counts[campaign] += 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def get_conversion_metrics(
        self,
        ad_spend: float,
        link_clicks: int,
        since_date: Optional[str] = None,
    ) -> dict:
        """
        Calculate conversion metrics by combining JotForm leads with ad data.

        Args:
            ad_spend:    Total ad spend in USD for the period.
            link_clicks: Total link clicks reported by the ad platform.
            since_date:  ISO date string "YYYY-MM-DD" to filter submissions.

        Returns:
            dict with:
              - total_leads (int): Number of form submissions in the period.
              - cost_per_lead (float): ad_spend / total_leads (0.0 if no leads).
              - conversion_rate (float): leads / link_clicks as a percentage
                                        (0.0 if no clicks).
              - daily_avg_leads (float): total_leads / number of active days.
        """
        submissions = self.get_submissions(since_date=since_date)
        total_leads = len(submissions)

        cost_per_lead = (ad_spend / total_leads) if total_leads > 0 else 0.0
        conversion_rate = (total_leads / link_clicks * 100) if link_clicks > 0 else 0.0

        # Calculate active days in the window
        if since_date:
            cutoff_dt = _parse_since_date(since_date)
            assert cutoff_dt is not None  # guaranteed by non-None since_date
            today = datetime.now(tz=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            active_days = max((today - cutoff_dt).days + 1, 1)
        else:
            # Derive from actual submission date range
            dates = sorted(
                sub["created_at"][:10]
                for sub in submissions
                if sub["created_at"]
            )
            if len(dates) >= 2:
                first = datetime.strptime(dates[0], "%Y-%m-%d")
                last = datetime.strptime(dates[-1], "%Y-%m-%d")
                active_days = max((last - first).days + 1, 1)
            else:
                active_days = 1

        daily_avg = total_leads / active_days

        return {
            "total_leads": total_leads,
            "cost_per_lead": round(cost_per_lead, 2),
            "conversion_rate": round(conversion_rate, 4),
            "daily_avg_leads": round(daily_avg, 2),
        }

    def generate_report(
        self,
        ad_spend: Optional[float] = None,
        link_clicks: Optional[int] = None,
        since_date: Optional[str] = None,
    ) -> None:
        """
        Print a formatted lead and conversion report to stdout.

        Combines form metadata, daily breakdown, recent leads, conversion
        metrics (if ad data is provided), and duplicate detection.

        Args:
            ad_spend:    Total ad spend in USD. Optional — omit to skip CPL calc.
            link_clicks: Total link clicks. Optional — omit to skip CVR calc.
            since_date:  ISO date string "YYYY-MM-DD" for the report window.
                         Defaults to all time if None.
        """
        now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        window_label = since_date if since_date else "all time"

        lines: list[str] = []
        lines.append(_header("SUNBIZ FUNDING — LEAD TRACKER REPORT"))
        lines.append(f"  Generated : {now_str}")
        lines.append(f"  Form ID   : {self.form_id}")
        lines.append(f"  Window    : {window_label} → today")
        lines.append("")

        # --- Form info ---
        try:
            info = self.get_form_info()
            lines.append(_divider())
            lines.append("  FORM STATUS")
            lines.append(_divider())
            lines.append(f"  Title         : {info['title']}")
            lines.append(f"  Status        : {info['status']}")
            lines.append(f"  Total (all time): {info['total_count']:,}")
            lines.append(f"  New (unseen)  : {info['new_count']:,}")
            lines.append("")
        except RuntimeError as exc:
            lines.append(f"  [WARNING] Could not fetch form info: {exc}")
            lines.append("")

        # --- Conversion metrics ---
        if ad_spend is not None and link_clicks is not None:
            try:
                metrics = self.get_conversion_metrics(
                    ad_spend=ad_spend,
                    link_clicks=link_clicks,
                    since_date=since_date,
                )
                lines.append(_divider())
                lines.append("  CONVERSION METRICS")
                lines.append(_divider())
                lines.append(f"  Ad Spend       : {_fmt_currency(ad_spend)}")
                lines.append(f"  Link Clicks    : {link_clicks:,}")
                lines.append(f"  Total Leads    : {metrics['total_leads']:,}")
                cpl = metrics['cost_per_lead']
                lines.append(
                    f"  Cost Per Lead  : {_fmt_currency(cpl) if cpl > 0 else 'N/A'}"
                )
                lines.append(
                    f"  Conversion Rate: {_fmt_pct(metrics['conversion_rate'])} "
                    f"(leads / clicks)"
                )
                lines.append(f"  Daily Avg Leads: {metrics['daily_avg_leads']:.1f}")
                lines.append("")
            except RuntimeError as exc:
                lines.append(f"  [WARNING] Could not calculate conversion metrics: {exc}")
                lines.append("")

        # --- Ad-attributed leads (UTM tracking) ---
        try:
            ad_subs = self.get_ad_submissions(since_date=since_date)
            campaign_breakdown = self.get_campaign_breakdown(since_date=since_date)
            all_subs_count = len(self.get_submissions(since_date=since_date))
            lines.append(_divider())
            lines.append("  AD-ATTRIBUTED LEADS (UTM Tracking)")
            lines.append(_divider())
            lines.append(f"  Total submissions (all sources): {all_subs_count}")
            lines.append(f"  From Meta Ads (utm_source=meta): {len(ad_subs)}")
            lines.append(f"  From other sources:              {all_subs_count - len(ad_subs)}")
            if campaign_breakdown:
                lines.append("")
                lines.append("  By Campaign:")
                for cname, cnt in campaign_breakdown.items():
                    lines.append(f"    {cname:.<30} {cnt:>4} leads")
            if not ad_subs:
                lines.append("")
                lines.append("  NOTE: UTM tracking was enabled on 2026-03-22.")
                lines.append("  Only new submissions from ad clicks will be tagged.")
                lines.append("  Pre-existing submissions cannot be retroactively tagged.")
            lines.append("")
        except RuntimeError as exc:
            lines.append(f"  [WARNING] Could not fetch ad-attributed leads: {exc}")
            lines.append("")

        # --- Daily breakdown ---
        try:
            daily = self.get_daily_breakdown(since_date=since_date)
            lines.append(_divider())
            lines.append("  DAILY SUBMISSIONS")
            lines.append(_divider())
            if daily:
                max_count = max(daily.values())
                bar_scale = max(max_count, 1)
                for date_str, cnt in daily.items():
                    bar_len = int(cnt / bar_scale * 30)
                    bar = "#" * bar_len
                    lines.append(f"  {date_str}  {cnt:>4}  {bar}")
            else:
                lines.append("  No submissions in this window.")
            lines.append("")
        except RuntimeError as exc:
            lines.append(f"  [WARNING] Could not fetch daily breakdown: {exc}")
            lines.append("")

        # --- Recent leads ---
        try:
            recent = self.get_recent_leads(count=10)
            lines.append(_divider())
            lines.append("  RECENT LEADS (last 10)")
            lines.append(_divider())
            if recent:
                for i, lead in enumerate(recent, start=1):
                    lines.append(f"  [{i:>2}] {lead['created_at']}")
                    lines.append(f"       Business : {lead['business_name'] or '(not provided)'}")
                    lines.append(f"       Owner    : {lead['owner_name'] or '(not provided)'}")
                    if lead["phone"]:
                        lines.append(f"       Phone    : {lead['phone']}")
                    if lead["email"]:
                        lines.append(f"       Email    : {lead['email']}")
                    lines.append(f"       Status   : {lead['status']}")
                    if lead.get("utm_source"):
                        lines.append(f"       Source   : {lead['utm_source']} / {lead.get('utm_campaign', '?')}")
                    else:
                        lines.append(f"       Source   : organic / direct / email")
                    lines.append(f"       Sub ID   : {lead['id']}")
                    lines.append("")
            else:
                lines.append("  No recent leads found.")
                lines.append("")
        except RuntimeError as exc:
            lines.append(f"  [WARNING] Could not fetch recent leads: {exc}")
            lines.append("")

        # --- Duplicates ---
        try:
            dupes = self.detect_duplicates()
            lines.append(_divider())
            lines.append("  DUPLICATE DETECTION")
            lines.append(_divider())
            email_dupes = dupes.get("by_email", {})
            phone_dupes = dupes.get("by_phone", {})
            if email_dupes:
                lines.append("  Duplicate emails:")
                for email, ids in email_dupes.items():
                    lines.append(f"    {email}  ({len(ids)} submissions: {', '.join(ids)})")
            if phone_dupes:
                lines.append("  Duplicate phones:")
                for phone, ids in phone_dupes.items():
                    lines.append(f"    {phone}  ({len(ids)} submissions: {', '.join(ids)})")
            if not email_dupes and not phone_dupes:
                lines.append("  No duplicates detected.")
            lines.append("")
        except RuntimeError as exc:
            lines.append(f"  [WARNING] Could not run duplicate detection: {exc}")
            lines.append("")

        lines.append("=" * 60)
        print("\n".join(lines))

    def detect_duplicates(self) -> dict[str, dict[str, list[str]]]:
        """
        Find duplicate submissions by email address or phone number.

        Fetches all submissions and groups submission IDs by normalised email
        and phone values. Only groups with 2+ submissions are flagged.

        Returns:
            dict with two keys:
              - "by_email": {email: [submission_id, ...]} for duplicated emails.
              - "by_phone": {phone: [submission_id, ...]} for duplicated phones.
        """
        log.info("Running duplicate detection for form %s ...", self.form_id)
        submissions = self.get_submissions()

        email_map: dict[str, list[str]] = defaultdict(list)
        phone_map: dict[str, list[str]] = defaultdict(list)

        for sub in submissions:
            sub_id = sub["id"]

            email = sub["email"].strip().lower()
            if email:
                email_map[email].append(sub_id)

            # Normalise phone: strip all non-digit characters for comparison
            phone_raw = sub["phone"]
            phone_digits = "".join(c for c in phone_raw if c.isdigit())
            if phone_digits:
                phone_map[phone_digits].append(sub_id)

        by_email = {k: v for k, v in email_map.items() if len(v) > 1}
        by_phone = {k: v for k, v in phone_map.items() if len(v) > 1}

        total_dupe_emails = len(by_email)
        total_dupe_phones = len(by_phone)
        log.info(
            "Duplicates found — emails: %d, phones: %d",
            total_dupe_emails, total_dupe_phones,
        )
        return {"by_email": by_email, "by_phone": by_phone}


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tracker = JotFormTracker()
    tracker.generate_report(
        ad_spend=None,
        link_clicks=None,
        since_date="2026-03-19",
    )
