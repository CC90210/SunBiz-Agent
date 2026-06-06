"""
SunBiz Funding — Production Meta Ads Engine
============================================
Reusable Meta Marketing API client (Graph API v21.0) built on the
requests library. Designed to be imported by other scripts or run
standalone for quick diagnostics.

Credentials loaded from (in priority order):
  1. .long_lived_token.txt  — long-lived user/system-user token
  2. META_ACCESS_TOKEN in .env.agents — fallback token

All other credentials (ad account, page, app) come from .env.agents.

Rate limiting: 2-second delay between every API call.
Retry policy:  3 attempts, exponential backoff (5s, 10s, 20s) on
               transient errors (network failures, Meta codes 1/2/4/17/32/613).

Compliance:
  - Default special_ad_category: FINANCIAL_PRODUCTS_SERVICES
  - No age/gender/zip targeting in credit-category campaigns
  - All CTAs link to JotForm lead capture
  - No "loan" language anywhere in this module
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
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
log = logging.getLogger("meta_ads_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
_JOTFORM_FORM_ID = os.environ.get("JOTFORM_FORM_ID", "253155026259254")
JOTFORM_URL = f"https://form.jotform.com/{_JOTFORM_FORM_ID}"

RATE_LIMIT_DELAY = 2          # seconds between every API call
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 5        # seconds; doubles each attempt (5, 10, 20)

# Meta API codes considered transient/retryable
_TRANSIENT_CODES = {1, 2, 4, 17, 32, 613}

# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

def _load_env_agents() -> dict[str, str]:
    """
    Parse KEY=VALUE pairs from .env.agents at the project root.
    Skips blank lines and comment lines.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env.agents"
    if not env_path.exists():
        raise FileNotFoundError(
            f".env.agents not found at {env_path}. "
            "Copy .env.agents.template and fill in your credentials."
        )
    creds: dict[str, str] = {}
    with env_path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            creds[key.strip()] = value.strip()
    return creds


def _load_long_lived_token() -> str:
    """
    Read token from .long_lived_token.txt at the project root.
    Returns empty string if the file does not exist.
    """
    token_path = Path(__file__).resolve().parent.parent / ".long_lived_token.txt"
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    return ""


def _require(creds: dict[str, str], key: str) -> str:
    """Return credential value or exit with a clear message."""
    val = creds.get(key, "")
    if not val or val.startswith("INSERT_"):
        log.error("Missing credential: %s — add it to .env.agents", key)
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _api_call(
    method: str,
    endpoint: str,
    token: str,
    payload: Optional[dict] = None,
    params: Optional[dict] = None,
) -> dict:
    """
    Execute a Graph API call with retry logic.

    - Injects access_token into every request.
    - Retries on network failures and transient Meta error codes.
    - Raises RuntimeError on non-transient API errors.
    """
    url = f"{BASE_URL}/{endpoint}"
    base_params: dict[str, str] = {"access_token": token}
    if params:
        base_params.update(params)

    last_error: Optional[Exception] = None

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            if method.upper() == "GET":
                resp = requests.get(url, params=base_params, timeout=30)
            elif method.upper() == "POST":
                resp = requests.post(url, params=base_params, data=payload, timeout=30)
            elif method.upper() == "DELETE":
                resp = requests.delete(url, params=base_params, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            body: dict = resp.json()

            if "error" in body:
                err = body["error"]
                code = err.get("code", 0)
                msg = err.get("message", str(err))

                if resp.status_code >= 500 or code in _TRANSIENT_CODES:
                    log.warning(
                        "Transient error (attempt %d/%d) code=%s: %s",
                        attempt, RETRY_ATTEMPTS, code, msg,
                    )
                    last_error = RuntimeError(msg)
                    if attempt < RETRY_ATTEMPTS:
                        time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue

                raise RuntimeError(
                    f"Meta API error {code}: {msg}\n"
                    f"Endpoint: {endpoint}\n"
                    f"Payload: {json.dumps(payload, indent=2) if payload else 'N/A'}"
                )

            return body

        except requests.RequestException as exc:
            log.warning("Network error (attempt %d/%d): %s", attempt, RETRY_ATTEMPTS, exc)
            last_error = exc
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))

    raise RuntimeError(
        f"All {RETRY_ATTEMPTS} attempts failed for {method} {endpoint}. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# MetaAdsEngine
# ---------------------------------------------------------------------------

class MetaAdsEngine:
    """
    High-level client for the Meta Marketing API.

    All public methods:
      - Enforce a 2-second rate-limit delay before every API call.
      - Return clean Python dicts (never raw facebook SDK objects).
      - Raise RuntimeError with descriptive messages on failure.
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        ad_account_id: Optional[str] = None,
        page_id: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
    ) -> None:
        creds = _load_env_agents()

        # Token: prefer .long_lived_token.txt, then env
        self.token: str = (
            access_token
            or _load_long_lived_token()
            or _require(creds, "META_ACCESS_TOKEN")
        )
        raw_account = ad_account_id or _require(creds, "META_AD_ACCOUNT_ID")
        self.ad_account_id: str = (
            raw_account if raw_account.startswith("act_") else f"act_{raw_account}"
        )
        self.page_id: str = page_id or _require(creds, "META_PAGE_ID")
        self.app_id: str = app_id or creds.get("META_APP_ID", "")
        self.app_secret: str = app_secret or creds.get("META_APP_SECRET", "")

        log.info("MetaAdsEngine ready — account: %s", self.ad_account_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(
        self,
        method: str,
        endpoint: str,
        payload: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Rate-limited wrapper around _api_call."""
        time.sleep(RATE_LIMIT_DELAY)
        return _api_call(method, endpoint, self.token, payload=payload, params=params)

    def _paginate(self, endpoint: str, params: Optional[dict] = None) -> list[dict]:
        """
        Follow Meta's cursor-based pagination and collect all results.
        Enforces the rate-limit delay on each page request.
        """
        results: list[dict] = []
        next_url: Optional[str] = None

        while True:
            if next_url:
                # Subsequent pages use the full URL returned by Meta
                time.sleep(RATE_LIMIT_DELAY)
                resp = requests.get(next_url, timeout=30)
                body: dict = resp.json()
            else:
                body = self._call("GET", endpoint, params=params)

            results.extend(body.get("data", []))
            paging = body.get("paging", {})
            next_url = paging.get("next")
            if not next_url:
                break

        return results

    # ------------------------------------------------------------------
    # Campaign operations
    # ------------------------------------------------------------------

    def create_campaign(
        self,
        name: str,
        objective: str = "OUTCOME_LEADS",
        special_ad_categories: Optional[list[str]] = None,
        status: str = "PAUSED",
    ) -> dict:
        """
        Create a campaign. Defaults to PAUSED so you can review before going live.

        Args:
            name: Campaign display name.
            objective: Meta campaign objective, e.g. OUTCOME_LEADS, OUTCOME_TRAFFIC.
            special_ad_categories: Defaults to ["FINANCIAL_PRODUCTS_SERVICES"].
            status: ACTIVE or PAUSED.

        Returns:
            dict with id, name, status.
        """
        categories = special_ad_categories or ["FINANCIAL_PRODUCTS_SERVICES"]
        payload = {
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": json.dumps(categories),
        }
        log.info("Creating campaign: %s (objective=%s)", name, objective)
        body = self._call("POST", f"{self.ad_account_id}/campaigns", payload=payload)
        log.info("Campaign created: %s", body["id"])
        return {"id": body["id"], "name": name, "status": status, "objective": objective}

    def pause_campaign(self, campaign_id: str) -> dict:
        """Set campaign status to PAUSED."""
        log.info("Pausing campaign: %s", campaign_id)
        self._call("POST", campaign_id, payload={"status": "PAUSED"})
        return {"id": campaign_id, "status": "PAUSED"}

    def resume_campaign(self, campaign_id: str) -> dict:
        """Set campaign status to ACTIVE."""
        log.info("Resuming campaign: %s", campaign_id)
        self._call("POST", campaign_id, payload={"status": "ACTIVE"})
        return {"id": campaign_id, "status": "ACTIVE"}

    def get_all_campaigns(self) -> list[dict]:
        """
        Return all campaigns on the ad account.

        Returns:
            List of dicts with id, name, status, objective, daily_budget, lifetime_budget.
        """
        log.info("Fetching all campaigns for %s ...", self.ad_account_id)
        rows = self._paginate(
            f"{self.ad_account_id}/campaigns",
            params={"fields": "id,name,status,objective,daily_budget,lifetime_budget"},
        )
        campaigns = []
        for row in rows:
            daily_raw = row.get("daily_budget")
            lifetime_raw = row.get("lifetime_budget")
            campaigns.append({
                "id": row["id"],
                "name": row.get("name", ""),
                "status": row.get("status", ""),
                "objective": row.get("objective", ""),
                "daily_budget_usd": (
                    round(int(daily_raw) / 100, 2) if daily_raw else None
                ),
                "lifetime_budget_usd": (
                    round(int(lifetime_raw) / 100, 2) if lifetime_raw else None
                ),
            })
        log.info("Found %d campaigns.", len(campaigns))
        return campaigns

    def duplicate_campaign(self, campaign_id: str, new_name: str) -> dict:
        """
        Duplicate a campaign for scaling. Uses Meta's copy endpoint.

        Args:
            campaign_id: ID of the source campaign.
            new_name: Name for the new campaign copy.

        Returns:
            dict with copied_campaign_id, name.
        """
        log.info("Duplicating campaign %s as '%s' ...", campaign_id, new_name)
        payload = {
            "campaign_id": campaign_id,
            "name": new_name,
            "status": "PAUSED",
        }
        body = self._call(
            "POST",
            f"{self.ad_account_id}/campaigns/copies",
            payload=payload,
        )
        new_id = body.get("copied_campaign_id") or body.get("id", "")
        log.info("Duplicated campaign: %s", new_id)
        return {"id": new_id, "name": new_name, "status": "PAUSED", "source_campaign_id": campaign_id}

    # ------------------------------------------------------------------
    # Ad Set operations
    # ------------------------------------------------------------------

    def create_adset(
        self,
        campaign_id: str,
        name: str,
        budget: int,
        targeting: Optional[dict] = None,
        bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        budget_type: str = "lifetime",
    ) -> dict:
        """
        Create an ad set.

        Args:
            campaign_id: Parent campaign ID.
            name: Ad set display name.
            budget: Budget in US dollars (converted to cents internally).
            targeting: Targeting spec dict. Defaults to US-only broad targeting
                       (required for FINANCIAL_PRODUCTS_SERVICES category — no
                       age/gender/zip restrictions allowed).
            bid_strategy: Meta bid strategy constant.
            start_time: ISO 8601 string, e.g. "2025-01-01T00:00:00+0000".
                        Defaults to now.
            end_time: ISO 8601 string. Required for lifetime budgets.
            budget_type: "lifetime" or "daily".

        Returns:
            dict with id, name, campaign_id, status.
        """
        # Credit-compliant default targeting: US only, no age/gender/zip
        default_targeting: dict = {
            "geo_locations": {"countries": ["US"]},
            "publisher_platforms": ["facebook"],
            "facebook_positions": ["feed"],
        }
        resolved_targeting = targeting or default_targeting

        budget_cents = budget * 100
        payload: dict[str, str] = {
            "name": name,
            "campaign_id": campaign_id,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LEAD_GENERATION",
            "bid_strategy": bid_strategy,
            "targeting": json.dumps(resolved_targeting),
            "status": "PAUSED",
        }

        if budget_type == "lifetime":
            payload["lifetime_budget"] = str(budget_cents)
        else:
            payload["daily_budget"] = str(budget_cents)

        if start_time:
            payload["start_time"] = start_time
        if end_time:
            payload["end_time"] = end_time

        log.info("Creating ad set: %s (campaign=%s)", name, campaign_id)
        body = self._call("POST", f"{self.ad_account_id}/adsets", payload=payload)
        log.info("Ad set created: %s", body["id"])
        return {
            "id": body["id"],
            "name": name,
            "campaign_id": campaign_id,
            "status": "PAUSED",
            "budget_usd": budget,
            "budget_type": budget_type,
        }

    def get_all_adsets(self, campaign_id: Optional[str] = None) -> list[dict]:
        """
        Return all ad sets, optionally filtered to a single campaign.

        Returns:
            List of dicts with id, name, campaign_id, status, daily_budget, lifetime_budget.
        """
        if campaign_id:
            endpoint = f"{campaign_id}/adsets"
            log.info("Fetching ad sets for campaign %s ...", campaign_id)
        else:
            endpoint = f"{self.ad_account_id}/adsets"
            log.info("Fetching all ad sets for account %s ...", self.ad_account_id)

        rows = self._paginate(
            endpoint,
            params={"fields": "id,name,campaign_id,status,daily_budget,lifetime_budget"},
        )
        adsets = []
        for row in rows:
            daily_raw = row.get("daily_budget")
            lifetime_raw = row.get("lifetime_budget")
            adsets.append({
                "id": row["id"],
                "name": row.get("name", ""),
                "campaign_id": row.get("campaign_id", ""),
                "status": row.get("status", ""),
                "daily_budget_usd": (
                    round(int(daily_raw) / 100, 2) if daily_raw else None
                ),
                "lifetime_budget_usd": (
                    round(int(lifetime_raw) / 100, 2) if lifetime_raw else None
                ),
            })
        log.info("Found %d ad sets.", len(adsets))
        return adsets

    # ------------------------------------------------------------------
    # Creative operations
    # ------------------------------------------------------------------

    def create_creative(
        self,
        name: str,
        page_id: Optional[str] = None,
        image_hash: Optional[str] = None,
        message: str = "",
        headline: str = "",
        description: str = "",
        link: str = JOTFORM_URL,
        cta_type: str = "LEARN_MORE",
    ) -> dict:
        """
        Create an ad creative with a link and optional image.

        Args:
            name: Creative display name.
            page_id: Facebook Page ID. Defaults to engine's page_id.
            image_hash: Hash of a previously uploaded image. Optional.
            message: Primary ad copy (body text).
            headline: Bold headline below the image.
            description: Smaller description text.
            link: Destination URL. Defaults to JotForm.
            cta_type: Meta CTA type constant, e.g. LEARN_MORE, APPLY_NOW, GET_QUOTE.

        Returns:
            dict with id, name.
        """
        resolved_page_id = page_id or self.page_id

        link_data: dict = {
            "link": link,
            "message": message,
            "name": headline,
            "description": description,
            "call_to_action": {
                "type": cta_type,
                "value": {"link": link},
            },
        }
        if image_hash:
            link_data["image_hash"] = image_hash

        object_story_spec = {
            "page_id": resolved_page_id,
            "link_data": link_data,
        }

        payload = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
        }

        log.info("Creating creative: %s", name)
        body = self._call("POST", f"{self.ad_account_id}/adcreatives", payload=payload)
        log.info("Creative created: %s", body["id"])
        return {"id": body["id"], "name": name}

    # ------------------------------------------------------------------
    # Ad operations
    # ------------------------------------------------------------------

    def create_ad(
        self,
        adset_id: str,
        creative_id: str,
        name: str,
        status: str = "PAUSED",
    ) -> dict:
        """
        Create an ad linking an ad set to a creative.

        Args:
            adset_id: Parent ad set ID.
            creative_id: Creative to attach.
            name: Ad display name.
            status: ACTIVE or PAUSED.

        Returns:
            dict with id, name, adset_id, status.
        """
        payload = {
            "name": name,
            "adset_id": adset_id,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": status,
        }
        log.info("Creating ad: %s (adset=%s)", name, adset_id)
        body = self._call("POST", f"{self.ad_account_id}/ads", payload=payload)
        log.info("Ad created: %s", body["id"])
        return {"id": body["id"], "name": name, "adset_id": adset_id, "status": status}

    def get_all_ads(self, adset_id: Optional[str] = None) -> list[dict]:
        """
        Return all ads, optionally filtered to a single ad set.

        Returns:
            List of dicts with id, name, adset_id, status, effective_status.
        """
        if adset_id:
            endpoint = f"{adset_id}/ads"
            log.info("Fetching ads for ad set %s ...", adset_id)
        else:
            endpoint = f"{self.ad_account_id}/ads"
            log.info("Fetching all ads for account %s ...", self.ad_account_id)

        rows = self._paginate(
            endpoint,
            params={"fields": "id,name,adset_id,status,effective_status"},
        )
        ads = [
            {
                "id": row["id"],
                "name": row.get("name", ""),
                "adset_id": row.get("adset_id", ""),
                "status": row.get("status", ""),
                "effective_status": row.get("effective_status", ""),
            }
            for row in rows
        ]
        log.info("Found %d ads.", len(ads))
        return ads

    # ------------------------------------------------------------------
    # Image upload
    # ------------------------------------------------------------------

    def upload_image(self, image_path: str) -> dict:
        """
        Upload a local image file to the ad account and return its hash.

        Args:
            image_path: Absolute or relative path to the image file.

        Returns:
            dict with hash, url (if available).
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        log.info("Uploading image: %s", path.name)
        url = f"{BASE_URL}/{self.ad_account_id}/adimages"
        time.sleep(RATE_LIMIT_DELAY)

        last_error: Optional[Exception] = None
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                with open(path, "rb") as fh:
                    resp = requests.post(
                        url,
                        params={"access_token": self.token},
                        files={"filename": (path.name, fh, "image/jpeg")},
                        timeout=60,
                    )
                body: dict = resp.json()

                if "error" in body:
                    err = body["error"]
                    code = err.get("code", 0)
                    msg = err.get("message", str(err))
                    if resp.status_code >= 500 or code in _TRANSIENT_CODES:
                        last_error = RuntimeError(msg)
                        if attempt < RETRY_ATTEMPTS:
                            time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
                        continue
                    raise RuntimeError(f"Image upload failed (code {code}): {msg}")

                # Meta wraps image data in an "images" key keyed by filename
                images_map: dict = body.get("images", {})
                image_data = next(iter(images_map.values()), {})
                img_hash = image_data.get("hash", "")
                img_url = image_data.get("url", "")
                log.info("Image uploaded — hash: %s", img_hash)
                return {"hash": img_hash, "url": img_url}

            except requests.RequestException as exc:
                log.warning("Network error on upload attempt %d/%d: %s", attempt, RETRY_ATTEMPTS, exc)
                last_error = exc
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"Image upload failed after {RETRY_ATTEMPTS} attempts. Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Insights / reporting
    # ------------------------------------------------------------------

    def get_insights(
        self,
        object_id: str,
        date_preset: str = "last_7d",
        fields: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Fetch performance insights for a campaign, ad set, or ad.

        Args:
            object_id: Campaign, ad set, or ad ID.
            date_preset: Meta date preset, e.g. today, yesterday, last_7d, last_30d.
            fields: List of insight field names. Defaults to a standard set.

        Returns:
            List of insight dicts (one per breakdown row, usually one).
        """
        default_fields = [
            "impressions", "reach", "frequency",
            "clicks", "ctr", "cpc", "cpm",
            "spend", "actions", "cost_per_action_type",
        ]
        resolved_fields = fields or default_fields

        rows = self._paginate(
            f"{object_id}/insights",
            params={
                "fields": ",".join(resolved_fields),
                "date_preset": date_preset,
            },
        )
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def refresh_token(self) -> dict:
        """
        Exchange the current token for a long-lived token (60-day expiry).
        Writes the new token to .long_lived_token.txt.

        Requires META_APP_ID and META_APP_SECRET to be configured.

        Returns:
            dict with access_token, token_type, expires_in.
        """
        if not self.app_id or not self.app_secret:
            raise RuntimeError(
                "META_APP_ID and META_APP_SECRET must be set in .env.agents "
                "to exchange for a long-lived token."
            )

        log.info("Exchanging token for long-lived version ...")
        time.sleep(RATE_LIMIT_DELAY)
        resp = requests.get(
            f"{BASE_URL}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": self.token,
            },
            timeout=30,
        )
        body: dict = resp.json()

        if "error" in body:
            err = body["error"]
            raise RuntimeError(
                f"Token exchange failed (code {err.get('code')}): {err.get('message')}"
            )

        new_token: str = body.get("access_token", "")
        if not new_token:
            raise RuntimeError("Token exchange returned no access_token.")

        # Persist new token
        token_path = Path(__file__).resolve().parent.parent / ".long_lived_token.txt"
        token_path.write_text(new_token, encoding="utf-8")
        self.token = new_token
        log.info("Long-lived token saved to %s", token_path)

        return {
            "access_token": new_token,
            "token_type": body.get("token_type", "bearer"),
            "expires_in": body.get("expires_in"),
        }


# ---------------------------------------------------------------------------
# Standalone diagnostic
# ---------------------------------------------------------------------------

def _run_diagnostics() -> None:
    """Quick health check — list campaigns and show account status."""
    engine = MetaAdsEngine()
    campaigns = engine.get_all_campaigns()
    print()
    print("=" * 50)
    print(f"  SunBiz Meta Ads — Account {engine.ad_account_id}")
    print(f"  {len(campaigns)} campaign(s) found")
    print("=" * 50)
    for c in campaigns:
        budget = (
            f"${c['daily_budget_usd']:.2f}/day"
            if c.get("daily_budget_usd")
            else f"${c['lifetime_budget_usd']:.2f} lifetime"
            if c.get("lifetime_budget_usd")
            else "No budget set"
        )
        print(f"  [{c['status']:<8}] {c['name']}")
        print(f"             ID: {c['id']}  Budget: {budget}")
    print("=" * 50)
    print()


if __name__ == "__main__":
    _run_diagnostics()
