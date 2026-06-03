"""
SunBiz Funding — Production-Grade Gmail Email Blast Engine
===========================================================
Thread-safe, rate-limited bulk email sender with CAN-SPAM compliance,
unsubscribe management, campaign tracking, and exponential-backoff retries.

Credentials (from .env.agents):
    GMAIL_ADDRESS           — the Gmail account used to send
    GMAIL_APP_PASSWORD      — Google App Password (not account password)
    EMAIL_FROM_NAME         — display name, default "SunBiz Funding"
    EMAIL_UNSUBSCRIBE_BASE_URL — base URL for unsubscribe links

Usage:
    from scripts.email_blast import send_campaign
    result = send_campaign(
        template_name="sunbiz_funding",
        recipient_csv="data/email_lists/merchants.csv",
        campaign_name="march_growth_blast",
        subject="{{first_name}}, funding for {{business_name}}",
        dry_run=False,
    )

Rate limits:
    Gmail personal/G Suite: ~500 emails/day (free), ~2000/day (Workspace).
    This engine defaults to 15 emails/minute with configurable batching so
    you stay comfortably within Gmail's 20 emails/second burst cap.

CAN-SPAM compliance:
    - Physical address in every email footer
    - Functional unsubscribe link in every email
    - Unsubscribe list checked before every send
    - Opt-outs honoured immediately (written to CSV on receipt)

MCA compliance:
    - NEVER use "loan" — always "advance", "funding", or "capital"
    - No guarantee language
"""

from __future__ import annotations

import csv
import logging
import os
import re
import smtplib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env.agents")

# ---------------------------------------------------------------------------
# Logging — file + console, no raw print() calls
# ---------------------------------------------------------------------------

_LOG_DIR = _PROJECT_ROOT / "data" / "email_logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger("email_blast")
if not _logger.handlers:
    _logger.setLevel(logging.DEBUG)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    _fh = logging.FileHandler(_LOG_DIR / "email_blast.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    _fh.setLevel(logging.DEBUG)

    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    _ch.setLevel(logging.INFO)

    _logger.addHandler(_fh)
    _logger.addHandler(_ch)

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

# GMAIL_USER is the canonical key used by CEO-Agent send_gateway.py + the
# provision_secrets sync; honor it first, fall back to GMAIL_ADDRESS for
# back-compat. On the SunBiz VPS this resolves to submissions@sunbizfunding.com.
GMAIL_ADDRESS: str = os.getenv("GMAIL_USER") or os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")
FROM_NAME: str = os.getenv("EMAIL_FROM_NAME", "SunBiz Funding")
UNSUBSCRIBE_BASE_URL: str = os.getenv(
    "EMAIL_UNSUBSCRIBE_BASE_URL", "https://sunbizfunding.com/unsubscribe"
)

# Hard sender-identity guard (added 2026-06 after a SunBiz send went out from
# the operator's personal Gmail because the bridge ran on the operator's Mac
# with their local GMAIL_ADDRESS). SunBiz must only ever send as its own
# domain. The guard refuses to authenticate/send when GMAIL_ADDRESS is not on
# the required domain. Set EMAIL_REQUIRE_FROM_DOMAIN="" to opt out (not
# recommended). Canonical SunBiz identity is submissions@sunbizfunding.com.
REQUIRE_FROM_DOMAIN: str = os.getenv("EMAIL_REQUIRE_FROM_DOMAIN", "sunbizfunding.com").strip().lower()


def _assert_sender_identity() -> None:
    """Raise if the configured sender is not on the required domain.

    Prevents the SunBiz agent from ever sending as a non-SunBiz account (e.g.
    the operator's personal Gmail when the bridge runs on their machine).
    """
    if not REQUIRE_FROM_DOMAIN:
        return  # explicitly disabled
    addr = (GMAIL_ADDRESS or "").strip().lower()
    # Exact-domain match (not endswith): require exactly one "@" and the domain
    # part to equal REQUIRE_FROM_DOMAIN exactly. This rejects subdomains
    # (x@mail.sunbizfunding.com), look-alikes (x@evilsunbizfunding.com), and
    # double-"@" malformed senders — closing any ambiguity in the suffix check.
    domain = addr.rsplit("@", 1)[1] if "@" in addr else ""
    if not addr or addr.count("@") != 1 or domain != REQUIRE_FROM_DOMAIN:
        raise RuntimeError(
            "Refusing to send: sender identity '"
            + (GMAIL_ADDRESS or "<unset>")
            + "' is not on the required SunBiz domain @"
            + REQUIRE_FROM_DOMAIN
            + ". The bridge must run with SunBiz's own GMAIL_USER "
            + "(submissions@sunbizfunding.com) + GMAIL_APP_PASSWORD — not the "
            + "operator's personal credentials. Provision the secrets file on "
            + "the VPS from the tenant credential store, or set "
            + "EMAIL_REQUIRE_FROM_DOMAIN to override."
        )

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

TEMPLATES_DIR = _PROJECT_ROOT / "templates" / "email"
EMAIL_LISTS_DIR = _PROJECT_ROOT / "data" / "email_lists"
EMAIL_LOGS_DIR = _LOG_DIR

UNSUBSCRIBE_CSV = EMAIL_LISTS_DIR / "unsubscribes.csv"

# CAN-SPAM physical address (update if company address changes)
PHYSICAL_ADDRESS = "SunBiz Funding | 1234 Business Ave, Suite 100 | Miami, FL 33101"

# Rate-limit defaults
DEFAULT_WORKERS = 4
DEFAULT_BATCH_SIZE = 50        # emails per batch
DEFAULT_BATCH_DELAY_SECS = 5.0 # pause between batches
MAX_EMAILS_PER_SECOND = 20     # hard ceiling per Gmail burst policy
MAX_RETRIES = 3
BASE_RETRY_DELAY_SECS = 2.0    # exponential backoff base

# Regex for basic email validation
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Global unsubscribe cache + lock so concurrent threads share state
_unsub_lock = threading.Lock()
_unsub_cache: set[str] = set()
_unsub_cache_loaded = False

# Per-campaign send-log lock
_log_lock = threading.Lock()

# Token to prevent exceeding MAX_EMAILS_PER_SECOND
_rate_lock = threading.Lock()
_last_send_times: list[float] = []

# ---------------------------------------------------------------------------
# Unsubscribe Management
# ---------------------------------------------------------------------------


def _ensure_unsub_csv() -> None:
    """Create the unsubscribe CSV with headers if it does not exist."""
    if not UNSUBSCRIBE_CSV.exists():
        EMAIL_LISTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(UNSUBSCRIBE_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["email", "unsubscribed_at"])


def _load_unsub_cache() -> None:
    """Load unsubscribe list into memory (once per process)."""
    global _unsub_cache_loaded
    with _unsub_lock:
        if _unsub_cache_loaded:
            return
        _ensure_unsub_csv()
        try:
            with open(UNSUBSCRIBE_CSV, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    _unsub_cache.add(row["email"].strip().lower())
        except Exception as exc:
            _logger.warning("Could not load unsubscribe list: %s", exc)
        _unsub_cache_loaded = True


def check_unsubscribe(email: str) -> bool:
    """Return True if the address is on the unsubscribe list."""
    _load_unsub_cache()
    return email.strip().lower() in _unsub_cache


def add_unsubscribe(email: str) -> None:
    """Add an address to the unsubscribe list (cache + CSV)."""
    _load_unsub_cache()
    normalised = email.strip().lower()
    with _unsub_lock:
        if normalised in _unsub_cache:
            return
        _ensure_unsub_csv()
        try:
            with open(UNSUBSCRIBE_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([normalised, datetime.now(timezone.utc).isoformat()])
            _unsub_cache.add(normalised)
            _logger.info("Unsubscribed: %s", normalised)
        except Exception as exc:
            _logger.error("Failed to write unsubscribe for %s: %s", normalised, exc)


# ---------------------------------------------------------------------------
# Recipient Loading
# ---------------------------------------------------------------------------


def load_recipients(csv_path: str | Path) -> list[dict[str, str]]:
    """
    Load recipients from a CSV file, validate emails, and filter unsubscribes.

    Expected columns (all optional except 'email'):
        email, first_name, last_name, business_name, monthly_revenue, funding_amount

    Returns a list of dicts, one per valid, subscribed recipient.
    """
    path = Path(csv_path)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path

    if not path.exists():
        raise FileNotFoundError(f"Recipient CSV not found: {path}")

    _load_unsub_cache()
    valid: list[dict[str, str]] = []
    skipped_invalid = 0
    skipped_unsub = 0

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("email", "").strip()
            if not email or not _EMAIL_RE.match(email):
                skipped_invalid += 1
                continue
            if check_unsubscribe(email):
                skipped_unsub += 1
                continue
            # Normalise the email, preserve all other fields as-is
            row["email"] = email
            valid.append(dict(row))

    _logger.info(
        "Loaded %d valid recipients from %s (skipped %d invalid, %d unsubscribed)",
        len(valid),
        path.name,
        skipped_invalid,
        skipped_unsub,
    )
    return valid


# ---------------------------------------------------------------------------
# Template Loading & Personalisation
# ---------------------------------------------------------------------------


def _load_template(template_name: str) -> str:
    """Load HTML template by name from templates/email/."""
    # Strip extension if caller included it
    stem = template_name.replace(".html", "")
    path = TEMPLATES_DIR / f"{stem}.html"
    if not path.exists():
        raise FileNotFoundError(f"Email template not found: {path}")
    return path.read_text(encoding="utf-8")


def _personalise(
    html: str,
    recipient: dict[str, str],
    campaign_id: str,
    extra_tokens: Optional[dict[str, str]] = None,
) -> str:
    """
    Replace {{token}} placeholders with recipient data.

    Built-in tokens:
        {{first_name}}, {{last_name}}, {{business_name}},
        {{monthly_revenue}}, {{funding_amount}},
        {{unsubscribe_url}}, {{tracking_pixel}}, {{campaign_id}}
    """
    unsub_url = (
        f"{UNSUBSCRIBE_BASE_URL}?"
        f"email={recipient['email']}&campaign={campaign_id}"
    )
    tracking_pixel = (
        f'<img src="{UNSUBSCRIBE_BASE_URL}/pixel.gif?'
        f'cid={campaign_id}&email={recipient["email"]}" '
        f'width="1" height="1" alt="" style="display:none;" />'
    )

    tokens: dict[str, str] = {
        "first_name": recipient.get("first_name", "Business Owner"),
        "last_name": recipient.get("last_name", ""),
        "business_name": recipient.get("business_name", "your business"),
        "monthly_revenue": recipient.get("monthly_revenue", ""),
        "funding_amount": recipient.get("funding_amount", ""),
        "unsubscribe_url": unsub_url,
        "tracking_pixel": tracking_pixel,
        "campaign_id": campaign_id,
        "physical_address": PHYSICAL_ADDRESS,
        "year": str(datetime.now().year),
    }
    if extra_tokens:
        tokens.update(extra_tokens)

    for key, value in tokens.items():
        html = html.replace(f"{{{{{key}}}}}", value)

    return html


def _personalise_subject(subject: str, recipient: dict[str, str]) -> str:
    """Apply personalisation tokens to the email subject line."""
    return subject.replace(
        "{{first_name}}", recipient.get("first_name", "Business Owner")
    ).replace(
        "{{business_name}}", recipient.get("business_name", "your business")
    ).replace(
        "{{funding_amount}}", recipient.get("funding_amount", "")
    )


# ---------------------------------------------------------------------------
# SMTP Connection Pool (one connection per worker thread)
# ---------------------------------------------------------------------------


_thread_local = threading.local()


def _get_smtp_connection() -> smtplib.SMTP:
    """
    Return a per-thread SMTP connection, creating one if needed.
    Reconnects automatically if the connection has gone stale.
    """
    conn: Optional[smtplib.SMTP] = getattr(_thread_local, "smtp", None)
    try:
        if conn is not None:
            conn.noop()  # ping — raises if dead
            return conn
    except Exception:
        _logger.debug("SMTP connection stale — reconnecting")

    _assert_sender_identity()  # never authenticate as a non-SunBiz account
    smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    smtp.ehlo()
    smtp.starttls()
    smtp.ehlo()
    smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    _thread_local.smtp = smtp
    _logger.debug("SMTP connection established (thread %s)", threading.current_thread().name)
    return smtp


def _close_thread_smtp() -> None:
    """Gracefully close the per-thread SMTP connection."""
    conn: Optional[smtplib.SMTP] = getattr(_thread_local, "smtp", None)
    if conn:
        try:
            conn.quit()
        except Exception:
            pass
        _thread_local.smtp = None


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------


def _throttle() -> None:
    """
    Block the calling thread if the last-second send count would exceed
    MAX_EMAILS_PER_SECOND. Uses a sliding window approach.
    """
    with _rate_lock:
        now = time.monotonic()
        # Drop timestamps older than 1 second
        cutoff = now - 1.0
        while _last_send_times and _last_send_times[0] < cutoff:
            _last_send_times.pop(0)

        if len(_last_send_times) >= MAX_EMAILS_PER_SECOND:
            # Sleep until the oldest timestamp falls outside the window
            sleep_for = 1.0 - (now - _last_send_times[0]) + 0.01
            if sleep_for > 0:
                time.sleep(sleep_for)

        _last_send_times.append(time.monotonic())


# ---------------------------------------------------------------------------
# Single Email Send
# ---------------------------------------------------------------------------


def send_single_email(
    to_email: str,
    subject: str,
    html_body: str,
    from_name: str = FROM_NAME,
    dry_run: bool = False,
    cc_email: Optional[str] = None,
) -> bool:
    """
    Send one HTML email via Gmail SMTP, as SunBiz's own shared identity.

    NOTE: For prospect-facing sends the canonical path is CEO-Agent
    send_gateway.py (CASL/cooldown/caps + assigned-rep CC + audit). This
    helper is the low-level transport; it now refuses to send unless the
    configured sender is on SunBiz's domain (see _assert_sender_identity).

    Args:
        to_email:  Recipient address.
        subject:   Email subject (already personalised).
        html_body: Full HTML body (already personalised).
        from_name: Display name in From header.
        dry_run:   If True, skip the actual send and log only.
        cc_email:  Optional CC (e.g. the assigned rep for the deal).

    Returns:
        True on success, False on failure.
    """
    # Validate identity up front so a misconfigured (non-SunBiz) sender fails
    # loudly even in dry-run, instead of silently sending as the wrong account.
    _assert_sender_identity()

    if dry_run:
        _logger.info(
            "[DRY RUN] Would send as %s to %s%s | subject: %s",
            GMAIL_ADDRESS, to_email, f" (cc {cc_email})" if cc_email else "", subject,
        )
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{GMAIL_ADDRESS}>"
    msg["To"] = to_email
    if cc_email:
        msg["Cc"] = cc_email
    msg["List-Unsubscribe"] = f"<mailto:{GMAIL_ADDRESS}?subject=unsubscribe>"
    msg["X-Mailer"] = "SunBiz-EmailBlast/2.0"

    # Plain-text fallback — strip HTML tags for a minimal plaintext version
    plain_text = re.sub(r"<[^>]+>", "", html_body)
    plain_text = re.sub(r"\s{2,}", " ", plain_text).strip()

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    _throttle()

    recipients = [to_email] + ([cc_email] if cc_email else [])
    smtp = _get_smtp_connection()
    smtp.sendmail(GMAIL_ADDRESS, recipients, msg.as_string())
    return True


# ---------------------------------------------------------------------------
# Campaign Send Log
# ---------------------------------------------------------------------------


def log_send(
    campaign_id: str,
    recipient: dict[str, str],
    status: str,  # "sent" | "failed" | "skipped"
    error: Optional[str] = None,
) -> None:
    """
    Append one row to the campaign's CSV send log in data/email_logs/.

    Thread-safe: uses _log_lock.
    """
    log_path = EMAIL_LOGS_DIR / f"{campaign_id}.csv"
    write_header = not log_path.exists()

    with _log_lock:
        try:
            with open(log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(
                        [
                            "timestamp",
                            "email",
                            "first_name",
                            "last_name",
                            "business_name",
                            "status",
                            "error",
                        ]
                    )
                writer.writerow(
                    [
                        datetime.now(timezone.utc).isoformat(),
                        recipient.get("email", ""),
                        recipient.get("first_name", ""),
                        recipient.get("last_name", ""),
                        recipient.get("business_name", ""),
                        status,
                        error or "",
                    ]
                )
        except Exception as exc:
            _logger.error("Failed to write send log for campaign %s: %s", campaign_id, exc)


# ---------------------------------------------------------------------------
# Campaign Stats
# ---------------------------------------------------------------------------


def get_campaign_stats(campaign_id: str) -> dict[str, int]:
    """
    Read the campaign send log and return summary counts.

    Returns:
        dict with keys: total, sent, failed, skipped
    """
    log_path = EMAIL_LOGS_DIR / f"{campaign_id}.csv"
    if not log_path.exists():
        return {"total": 0, "sent": 0, "failed": 0, "skipped": 0}

    counts: dict[str, int] = {"sent": 0, "failed": 0, "skipped": 0}
    try:
        with open(log_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("status", "").lower()
                counts[status] = counts.get(status, 0) + 1
    except Exception as exc:
        _logger.error("Could not read campaign log %s: %s", campaign_id, exc)

    counts["total"] = sum(counts.values())
    return counts


# ---------------------------------------------------------------------------
# Per-Recipient Worker
# ---------------------------------------------------------------------------


def _send_one(
    recipient: dict[str, str],
    subject_template: str,
    html_template: str,
    campaign_id: str,
    dry_run: bool,
) -> dict[str, str]:
    """
    Personalise and send one email with exponential-backoff retries.
    Returns a result dict: {email, status, error}.
    """
    email = recipient["email"]

    # Double-check unsubscribe at send time (list may have grown mid-campaign)
    if check_unsubscribe(email):
        log_send(campaign_id, recipient, "skipped", "unsubscribed")
        return {"email": email, "status": "skipped", "error": "unsubscribed"}

    subject = _personalise_subject(subject_template, recipient)
    html_body = _personalise(html_template, recipient, campaign_id)

    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            send_single_email(email, subject, html_body, dry_run=dry_run)
            log_send(campaign_id, recipient, "sent")
            return {"email": email, "status": "sent", "error": ""}
        except smtplib.SMTPRecipientsRefused as exc:
            last_error = f"Recipient refused: {exc}"
            _logger.warning("Recipient refused %s — not retrying", email)
            break  # Bounced — no point retrying
        except smtplib.SMTPServerDisconnected:
            # Force reconnect on next attempt
            _close_thread_smtp()
            last_error = "Server disconnected"
        except Exception as exc:
            last_error = str(exc)

        if attempt < MAX_RETRIES:
            delay = BASE_RETRY_DELAY_SECS * (2 ** (attempt - 1))
            _logger.warning(
                "Send attempt %d/%d failed for %s (%s) — retrying in %.1fs",
                attempt,
                MAX_RETRIES,
                email,
                last_error,
                delay,
            )
            time.sleep(delay)

    _logger.error("All %d attempts failed for %s: %s", MAX_RETRIES, email, last_error)
    log_send(campaign_id, recipient, "failed", last_error)
    return {"email": email, "status": "failed", "error": last_error}


# ---------------------------------------------------------------------------
# Main Campaign Entry Point
# ---------------------------------------------------------------------------


def send_campaign(
    template_name: str,
    recipient_csv: str | Path,
    campaign_name: str,
    subject: str,
    dry_run: bool = False,
    workers: int = DEFAULT_WORKERS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_delay: float = DEFAULT_BATCH_DELAY_SECS,
    extra_tokens: Optional[dict[str, str]] = None,
) -> dict[str, int | str]:
    """
    Send an email campaign to all recipients in a CSV file.

    Args:
        template_name:  HTML template filename (without .html) in templates/email/.
        recipient_csv:  Path to the recipient CSV (absolute or relative to project root).
        campaign_name:  Human-readable campaign label (used in log filenames).
        subject:        Email subject line — supports {{first_name}} and {{business_name}}.
        dry_run:        If True, log but do not actually send.
        workers:        Number of concurrent sending threads.
        batch_size:     Emails per batch before pausing.
        batch_delay:    Seconds to sleep between batches.
        extra_tokens:   Additional {{token}} replacements for the template.

    Returns:
        Campaign stats dict: {campaign_id, total, sent, failed, skipped, duration_secs}.
    """
    # Validate credentials before starting
    if not dry_run:
        if not GMAIL_ADDRESS:
            raise RuntimeError("GMAIL_ADDRESS is not set in .env.agents")
        if not GMAIL_APP_PASSWORD:
            raise RuntimeError("GMAIL_APP_PASSWORD is not set in .env.agents")

    campaign_id = f"{campaign_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    _logger.info(
        "Starting campaign '%s' (id=%s, dry_run=%s)",
        campaign_name,
        campaign_id,
        dry_run,
    )

    # Load template and recipients
    html_template = _load_template(template_name)
    recipients = load_recipients(recipient_csv)

    if not recipients:
        _logger.warning("No valid recipients — campaign aborted.")
        return {
            "campaign_id": campaign_id,
            "total": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "duration_secs": 0,
        }

    _logger.info("Sending to %d recipients with %d workers", len(recipients), workers)
    start_time = time.monotonic()

    # Split into batches and process
    batches = [recipients[i:i + batch_size] for i in range(0, len(recipients), batch_size)]
    _logger.info("%d batch(es) of up to %d emails each", len(batches), batch_size)

    for batch_num, batch in enumerate(batches, start=1):
        _logger.info("Processing batch %d/%d (%d emails)", batch_num, len(batches), len(batch))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _send_one,
                    recipient,
                    subject,
                    html_template,
                    campaign_id,
                    dry_run,
                ): recipient
                for recipient in batch
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    _logger.debug(
                        "  [%s] %s",
                        result.get("status", "?").upper(),
                        result.get("email", "?"),
                    )
                except Exception as exc:
                    recipient = futures[future]
                    _logger.error("Unexpected error for %s: %s", recipient.get("email"), exc)
                    log_send(campaign_id, recipient, "failed", str(exc))

        # Pause between batches (but not after the last one)
        if batch_num < len(batches):
            _logger.info("Batch %d complete — pausing %.1fs before next batch", batch_num, batch_delay)
            time.sleep(batch_delay)

    # Close all thread SMTP connections
    # Each thread's connection is cleaned up when its thread exits;
    # nothing further to do for ThreadPoolExecutor threads.

    duration = time.monotonic() - start_time
    stats = get_campaign_stats(campaign_id)
    stats["campaign_id"] = campaign_id
    stats["duration_secs"] = round(duration, 2)

    _logger.info(
        "Campaign '%s' complete in %.1fs — sent: %d, failed: %d, skipped: %d",
        campaign_name,
        duration,
        stats.get("sent", 0),
        stats.get("failed", 0),
        stats.get("skipped", 0),
    )
    return stats


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SunBiz Funding Email Blast Engine")
    parser.add_argument("--template", required=True, help="Template name (e.g. sunbiz_funding)")
    parser.add_argument("--csv", required=True, help="Path to recipient CSV")
    parser.add_argument("--name", required=True, help="Campaign name (no spaces)")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--dry-run", action="store_true", help="Log only — do not send")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--batch-delay", type=float, default=DEFAULT_BATCH_DELAY_SECS)

    args = parser.parse_args()

    result = send_campaign(
        template_name=args.template,
        recipient_csv=args.csv,
        campaign_name=args.name,
        subject=args.subject,
        dry_run=args.dry_run,
        workers=args.workers,
        batch_size=args.batch_size,
        batch_delay=args.batch_delay,
    )
    _logger.info("Final stats: %s", result)
