"""
SunBiz Funding — Meta Ads Campaign Builder
===========================================
Completes setup of 5 existing Meta ad campaigns by creating ad sets,
ad creatives, and ads for each. Campaigns already exist and are ACTIVE.

This script is IDEMPOTENT — if a campaign already has ad sets, it skips
creation for that campaign and reports the existing state.

Credentials (from .env.agents, two directories up from scripts/):
    META_ACCESS_TOKEN   — system user or page access token
    META_AD_ACCOUNT_ID  — e.g. act_123456789
    META_PAGE_ID        — Facebook Page ID for object_story_spec

Usage:
    python scripts/meta_campaign_builder.py

API version: v21.0
Rate limiting: 2-second delay between all API calls
Retry policy: up to 3 attempts on transient (5xx / rate-limit) errors,
              5-second back-off between retries.

Compliance:
    - Special Ad Category: FINANCIAL_PRODUCTS_SERVICES (set at campaign level)
    - No age/gender/zip targeting — US-only broad targeting
    - CTAs link to JotForm lead capture
    - No "loan" language — uses "capital", "funding", "advance"
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("meta_campaign_builder")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
_JOTFORM_FORM_ID = os.environ.get("JOTFORM_FORM_ID", "253155026259254")
JOTFORM_URL = f"https://form.jotform.com/{_JOTFORM_FORM_ID}"

LIFETIME_BUDGET_CENTS = 10000  # $100.00
AD_DELAY_SECONDS = 2
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5

# ---------------------------------------------------------------------------
# Credentials loader (no external dependencies — plain file parsing)
# ---------------------------------------------------------------------------

def _load_env_agents() -> dict[str, str]:
    """
    Parse KEY=VALUE pairs from .env.agents.
    Skips blank lines and lines starting with '#'.
    Raises FileNotFoundError if the file does not exist.
    """
    # .env.agents lives one level above the scripts/ directory
    env_path = Path(__file__).resolve().parent.parent / ".env.agents"
    if not env_path.exists():
        raise FileNotFoundError(
            f".env.agents not found at {env_path}. "
            "Copy .env.agents.template and fill in your credentials."
        )

    creds: dict[str, str] = {}
    with env_path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()

    return creds


def _require(creds: dict[str, str], key: str) -> str:
    """Return credential value or abort with a clear message."""
    val = creds.get(key, "")
    if not val or val.startswith("INSERT_"):
        log.error("Missing credential: %s — add it to .env.agents", key)
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# HTTP helper with retry logic
# ---------------------------------------------------------------------------

def _api_call(
    method: str,
    endpoint: str,
    token: str,
    payload: Optional[dict] = None,
    params: Optional[dict] = None,
) -> dict:
    """
    Thin wrapper around requests that:
      - Injects access_token into every request
      - Retries on 5xx / rate-limit responses (error code 17 / 32 / 613)
      - Raises RuntimeError on unrecoverable API errors
    """
    url = f"{BASE_URL}/{endpoint}"
    base_params = {"access_token": token}
    if params:
        base_params.update(params)

    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            if method.upper() == "GET":
                response = requests.get(url, params=base_params, timeout=30)
            elif method.upper() == "POST":
                response = requests.post(
                    url, params=base_params, data=payload, timeout=30
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            body = response.json()

            # Meta returns HTTP 200 even for some errors — inspect body
            if "error" in body:
                err = body["error"]
                code = err.get("code", 0)
                msg = err.get("message", str(err))

                # Transient / rate-limit codes — retry
                transient_codes = {1, 2, 4, 17, 32, 613}
                if response.status_code >= 500 or code in transient_codes:
                    log.warning(
                        "Transient error on attempt %d/%d (code %s): %s",
                        attempt, RETRY_ATTEMPTS, code, msg,
                    )
                    last_error = RuntimeError(msg)
                    if attempt < RETRY_ATTEMPTS:
                        time.sleep(RETRY_BACKOFF_SECONDS)
                    continue

                # Non-transient API error — fail immediately
                raise RuntimeError(
                    f"Meta API error {code}: {msg}\n"
                    f"Endpoint: {endpoint}\n"
                    f"Payload: {json.dumps(payload, indent=2) if payload else 'N/A'}"
                )

            return body

        except requests.RequestException as exc:
            log.warning("Network error on attempt %d/%d: %s", attempt, RETRY_ATTEMPTS, exc)
            last_error = exc
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS)

    raise RuntimeError(
        f"All {RETRY_ATTEMPTS} attempts failed for {method} {endpoint}. "
        f"Last error: {last_error}"
    )


def _pause() -> None:
    """Rate-limit guard — 2 seconds between all API calls."""
    time.sleep(AD_DELAY_SECONDS)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CampaignSpec:
    """Definition of a campaign and all objects to create beneath it."""
    campaign_id: str
    theme: str                  # Short human-readable name used in object names
    image_hash: str
    message: str
    headline: str
    description: str

    # Populated at runtime
    ad_set_id: Optional[str] = field(default=None, repr=False)
    creative_id: Optional[str] = field(default=None, repr=False)
    ad_id: Optional[str] = field(default=None, repr=False)
    skipped: bool = field(default=False, repr=False)
    error: Optional[str] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Campaign specs — one entry per existing campaign
# ---------------------------------------------------------------------------

def _build_campaign_specs() -> list[CampaignSpec]:
    return [
        CampaignSpec(
            campaign_id="120241441622900086",
            theme="Growth Capital",
            image_hash="e82162a8151eb37fcee8afd876070096",
            message=(
                "Your business deserves the capital to grow. "
                "Get $5K\u2013$250K in working capital with no credit pull "
                "and weekly payments. Funded in as fast as 24 hours.\n\n"
                "See if you qualify \u2014 takes less than 3 minutes."
            ),
            headline="Business Funding, Simplified",
            description="SunBiz Funding \u2014 $5K to $250K. No Credit Pull. Fast Approval.",
        ),
        CampaignSpec(
            campaign_id="120241441624860086",
            theme="Consolidation",
            image_hash="70bee2ae5c872ec998a7eb2255cc549f",
            message=(
                "Multiple daily payments draining your cash flow? "
                "You\u2019re not stuck.\n\n"
                "Consolidate into one simple weekly payment and keep more of what you earn. "
                "Business owners are saving thousands per month.\n\n"
                "See if you qualify today."
            ),
            headline="One Payment. Lower Amount. More Cash Flow.",
            description="SunBiz Funding \u2014 Consolidate Multiple Payments Into One.",
        ),
        CampaignSpec(
            campaign_id="120241441625290086",
            theme="Fast Funding",
            image_hash="2e95b524210ff0f70d1e63ecf6ce0115",
            message=(
                "When your business needs capital, every hour counts.\n\n"
                "\u2192 3 minutes to apply\n"
                "\u2192 4 hours to approve\n"
                "\u2192 24 hours to fund\n\n"
                "No credit pull. No collateral. No waiting weeks for a decision.\n\n"
                "See if you qualify now."
            ),
            headline="Funded in 24 Hours",
            description="SunBiz Funding \u2014 Fast Capital When You Need It Most.",
        ),
        CampaignSpec(
            campaign_id="120241441625510086",
            theme="Industry Targeted",
            image_hash="37b852cacaa62a918d368bf33275f6ef",
            message=(
                "Restaurant owners, contractors, and retail business owners "
                "\u2014 this is for you.\n\n"
                "Whether you need capital for equipment, inventory, staffing, "
                "or materials, we fund businesses like yours every day.\n\n"
                "$5K\u2013$250K. No credit pull. Weekly payments.\n\n"
                "See if you qualify."
            ),
            headline="Capital Built for Your Industry",
            description="SunBiz Funding \u2014 Industry-Specific Business Capital.",
        ),
        CampaignSpec(
            campaign_id="120241441625670086",
            theme="Social Proof",
            image_hash="223d0465b18486198de238b808d52d2f",
            message=(
                "500+ businesses funded. $50M+ deployed. "
                "Here\u2019s what owners are saying:\n\n"
                "\u2b50\u2b50\u2b50\u2b50\u2b50 "
                "\u201cSunBiz got me $85K in 24 hours. No credit pull, no hassle.\u201d "
                "\u2014 Restaurant owner, Miami\n\n"
                "\u2b50\u2b50\u2b50\u2b50\u2b50 "
                "\u201cConsolidated 4 daily payments into 1 weekly. "
                "Saving $2,800/month.\u201d \u2014 Contractor, Dallas\n\n"
                "See if you qualify today."
            ),
            headline="Trusted by 500+ Business Owners",
            description="SunBiz Funding \u2014 Join Hundreds of Funded Businesses.",
        ),
    ]


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

def _campaign_has_ad_sets(campaign_id: str, token: str) -> Optional[str]:
    """
    Returns the first existing ad set ID if the campaign already has ad sets,
    otherwise returns None. Used to skip already-completed campaigns.
    """
    log.info("Checking for existing ad sets on campaign %s ...", campaign_id)
    _pause()
    body = _api_call(
        "GET",
        f"{campaign_id}/adsets",
        token,
        params={"fields": "id,name,status", "limit": "5"},
    )
    data = body.get("data", [])
    if data:
        ids = [s["id"] for s in data]
        log.info(
            "  Campaign %s already has %d ad set(s): %s — skipping.",
            campaign_id, len(data), ", ".join(ids),
        )
        return ids[0]
    return None


# ---------------------------------------------------------------------------
# Creation helpers
# ---------------------------------------------------------------------------

def _create_ad_set(
    campaign_id: str,
    theme: str,
    account_id: str,
    token: str,
) -> str:
    """Create ad set and return its ID."""
    now = datetime.now(tz=timezone.utc)
    end = now + timedelta(days=10)

    # ISO 8601 format Meta expects: YYYY-MM-DDTHH:MM:SS+0000
    def _fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")

    targeting = {
        "geo_locations": {"countries": ["US"]},
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed"],
        "instagram_positions": ["stream", "story", "reels"],
    }

    payload = {
        "name": f"SunBiz - {theme} - Ad Set 1",
        "campaign_id": campaign_id,
        "lifetime_budget": str(LIFETIME_BUDGET_CENTS),
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "LINK_CLICKS",
        "start_time": _fmt(now),
        "end_time": _fmt(end),
        "targeting": json.dumps(targeting),
        "status": "ACTIVE",
    }

    log.info("  Creating ad set for campaign %s (%s) ...", campaign_id, theme)
    _pause()
    body = _api_call("POST", f"{account_id}/adsets", token, payload=payload)
    ad_set_id = body["id"]
    log.info("  Ad set created: %s", ad_set_id)
    return ad_set_id


def _validate_ad_set(ad_set_id: str, token: str) -> None:
    """Read back the ad set to confirm it exists and is ACTIVE."""
    _pause()
    body = _api_call(
        "GET",
        ad_set_id,
        token,
        params={"fields": "id,name,status,lifetime_budget"},
    )
    status = body.get("status", "UNKNOWN")
    if status not in ("ACTIVE", "PAUSED"):
        raise RuntimeError(
            f"Ad set {ad_set_id} has unexpected status '{status}' after creation."
        )
    log.info("  Validated ad set %s — status: %s", ad_set_id, status)


def _create_creative(
    spec: CampaignSpec,
    account_id: str,
    page_id: str,
    token: str,
) -> str:
    """Create ad creative and return its ID."""
    object_story_spec = {
        "page_id": page_id,
        "link_data": {
            "link": JOTFORM_URL,
            "message": spec.message,
            "name": spec.headline,
            "description": spec.description,
            "image_hash": spec.image_hash,
            "call_to_action": {
                "type": "LEARN_MORE",
                "value": {"link": JOTFORM_URL},
            },
        },
    }

    payload = {
        "name": f"SunBiz - {spec.theme} - Creative 1",
        "object_story_spec": json.dumps(object_story_spec),
    }

    log.info("  Creating creative for %s ...", spec.theme)
    _pause()
    body = _api_call("POST", f"{account_id}/adcreatives", token, payload=payload)
    creative_id = body["id"]
    log.info("  Creative created: %s", creative_id)
    return creative_id


def _validate_creative(creative_id: str, token: str) -> None:
    """Read back the creative to confirm it exists."""
    _pause()
    body = _api_call(
        "GET",
        creative_id,
        token,
        params={"fields": "id,name,status"},
    )
    log.info(
        "  Validated creative %s — name: %s",
        creative_id,
        body.get("name", "?"),
    )


def _create_ad(
    ad_set_id: str,
    creative_id: str,
    theme: str,
    account_id: str,
    token: str,
) -> str:
    """Create ad linking the ad set and creative, return its ID."""
    payload = {
        "name": f"SunBiz - {theme} - Ad 1",
        "adset_id": ad_set_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status": "ACTIVE",
    }

    log.info("  Creating ad for %s ...", theme)
    _pause()
    body = _api_call("POST", f"{account_id}/ads", token, payload=payload)
    ad_id = body["id"]
    log.info("  Ad created: %s", ad_id)
    return ad_id


def _validate_ad(ad_id: str, token: str) -> None:
    """Read back the ad to confirm it exists and is not rejected."""
    _pause()
    body = _api_call(
        "GET",
        ad_id,
        token,
        params={"fields": "id,name,status,effective_status"},
    )
    effective = body.get("effective_status", "UNKNOWN")
    # PENDING_REVIEW is normal immediately after creation
    acceptable = {"ACTIVE", "PAUSED", "PENDING_REVIEW", "WITH_ISSUES"}
    if effective not in acceptable:
        log.warning(
            "  Ad %s has effective_status '%s' — may need review.",
            ad_id, effective,
        )
    else:
        log.info(
            "  Validated ad %s — effective_status: %s", ad_id, effective
        )


# ---------------------------------------------------------------------------
# Main orchestration loop
# ---------------------------------------------------------------------------

def run() -> None:
    log.info("=" * 60)
    log.info("SunBiz Meta Ads Campaign Builder — starting")
    log.info("=" * 60)

    # --- Load credentials ---
    creds = _load_env_agents()
    TOKEN = _require(creds, "META_ACCESS_TOKEN")
    ACCOUNT_ID = _require(creds, "META_AD_ACCOUNT_ID")
    PAGE_ID = _require(creds, "META_PAGE_ID")

    # Ensure account ID has act_ prefix
    if not ACCOUNT_ID.startswith("act_"):
        ACCOUNT_ID = f"act_{ACCOUNT_ID}"

    log.info("Account: %s", ACCOUNT_ID)
    log.info("Page:    %s", PAGE_ID)
    log.info("API:     %s", API_VERSION)
    log.info("")

    specs = _build_campaign_specs()
    total = len(specs)

    for idx, spec in enumerate(specs, start=1):
        log.info("-" * 60)
        log.info(
            "[%d/%d] Campaign: %s  (ID: %s)",
            idx, total, spec.theme, spec.campaign_id,
        )

        try:
            # ---- IDEMPOTENCY CHECK ----
            existing_ad_set_id = _campaign_has_ad_sets(spec.campaign_id, TOKEN)
            if existing_ad_set_id:
                spec.ad_set_id = existing_ad_set_id
                spec.skipped = True
                log.info("  Skipped — ad sets already exist.")
                continue

            # ---- AD SET ----
            spec.ad_set_id = _create_ad_set(
                spec.campaign_id, spec.theme, ACCOUNT_ID, TOKEN
            )
            _validate_ad_set(spec.ad_set_id, TOKEN)

            # ---- CREATIVE ----
            spec.creative_id = _create_creative(spec, ACCOUNT_ID, PAGE_ID, TOKEN)
            _validate_creative(spec.creative_id, TOKEN)

            # ---- AD ----
            spec.ad_id = _create_ad(
                spec.ad_set_id, spec.creative_id, spec.theme, ACCOUNT_ID, TOKEN
            )
            _validate_ad(spec.ad_id, TOKEN)

            log.info("  [OK] All objects created and validated.")

        except RuntimeError as exc:
            spec.error = str(exc)
            log.error("  [FAILED] %s", exc)

    # ---------------------------------------------------------------------------
    # Summary report
    # ---------------------------------------------------------------------------
    _print_summary(specs)


def _print_summary(specs: list[CampaignSpec]) -> None:
    budget_per_campaign_dollars = LIFETIME_BUDGET_CENTS / 100
    created_count = sum(1 for s in specs if not s.skipped and not s.error)
    skipped_count = sum(1 for s in specs if s.skipped)
    failed_count = sum(1 for s in specs if s.error)

    print()
    print("=" * 43)
    print("  SUNBIZ META ADS — LAUNCH REPORT")
    print("=" * 43)

    for spec in specs:
        print()
        print(f"Campaign: SunBiz \u2014 {spec.theme}")
        print(f"  Campaign ID : {spec.campaign_id}")

        if spec.skipped:
            print(f"  Ad Set ID   : {spec.ad_set_id}  [pre-existing, skipped]")
            print(f"  Creative ID : (not created — campaign already had ad sets)")
            print(f"  Ad ID       : (not created — campaign already had ad sets)")
            print(f"  Status      : SKIPPED (idempotency guard)")
        elif spec.error:
            print(f"  Ad Set ID   : {spec.ad_set_id or 'NOT CREATED'}")
            print(f"  Creative ID : {spec.creative_id or 'NOT CREATED'}")
            print(f"  Ad ID       : {spec.ad_id or 'NOT CREATED'}")
            print(f"  Status      : FAILED")
            print(f"  Error       : {spec.error}")
        else:
            print(f"  Ad Set ID   : {spec.ad_set_id}")
            print(f"  Creative ID : {spec.creative_id}")
            print(f"  Ad ID       : {spec.ad_id}")
            print(f"  Budget      : ${budget_per_campaign_dollars:.2f} lifetime")
            print(f"  Status      : ACTIVE")

    print()
    print("-" * 43)
    active_budget = created_count * budget_per_campaign_dollars
    print(f"Campaigns processed : {len(specs)}")
    print(f"  Created           : {created_count}")
    print(f"  Skipped           : {skipped_count}")
    print(f"  Failed            : {failed_count}")
    print(f"Total new budget    : ${active_budget:.2f}")
    print(f"Lead destination    : {JOTFORM_URL}")
    print("=" * 43)
    print()

    if failed_count:
        log.warning(
            "%d campaign(s) failed. Review errors above and re-run — "
            "the script is idempotent and will skip already-completed campaigns.",
            failed_count,
        )
        sys.exit(1)
    else:
        log.info("All campaigns processed successfully.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
