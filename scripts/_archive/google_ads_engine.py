"""
SunBiz Funding — Production Google Ads Engine
=============================================
Reusable Google Ads API client (google-ads SDK v29+) that mirrors the
structure and quality of meta_ads_engine.py. Designed to be imported by
other scripts or run standalone for quick diagnostics.

Credentials loaded from .env.agents at the project root:
  GOOGLE_ADS_DEVELOPER_TOKEN
  GOOGLE_ADS_CLIENT_ID
  GOOGLE_ADS_CLIENT_SECRET
  GOOGLE_ADS_REFRESH_TOKEN
  GOOGLE_ADS_CUSTOMER_ID

Graceful degradation: if the google-ads SDK is not installed or credentials
are missing/placeholder, every public method returns a clear error dict
instead of raising an unhandled exception.

Rate limiting: 1-second delay between every mutate/query call.
Retry policy:  3 attempts, exponential backoff (5s, 10s, 20s) on transient
               errors (TRANSIENT_ERROR, INTERNAL_ERROR, DEADLINE_EXCEEDED,
               RESOURCE_EXHAUSTED).

Compliance:
  - No "loan" language — use "advance", "funding", or "capital".
  - All final URLs default to the JotForm lead capture destination.
  - Customer ID normalised (strips hyphens) before every API call.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("google_ads_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOTFORM_FORM_ID = os.environ.get("JOTFORM_FORM_ID", "253155026259254")
JOTFORM_URL = f"https://form.jotform.com/{_JOTFORM_FORM_ID}"

RATE_LIMIT_DELAY = 1            # seconds between every API call
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 5          # seconds; doubles each attempt (5, 10, 20)

# gRPC/Google Ads status codes considered transient/retryable (string names)
_TRANSIENT_STATUSES = {
    "TRANSIENT_ERROR",
    "INTERNAL_ERROR",
    "DEADLINE_EXCEEDED",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
}

# Micros conversion factor
_MICROS = 1_000_000

# ---------------------------------------------------------------------------
# Credential loading (mirrors meta_ads_engine._load_env_agents)
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


def _is_placeholder(value: str) -> bool:
    """Return True if the credential value is an unfilled placeholder."""
    return not value or value.upper().startswith("INSERT_")


def _normalise_customer_id(customer_id: str) -> str:
    """Strip hyphens from customer ID (e.g. '123-456-7890' -> '1234567890')."""
    return customer_id.replace("-", "").strip()


# ---------------------------------------------------------------------------
# SDK availability guard
# ---------------------------------------------------------------------------

_SDK_AVAILABLE: bool = False
_SDK_IMPORT_ERROR: str = ""

try:
    from google.ads.googleads.client import GoogleAdsClient  # type: ignore[import]
    from google.ads.googleads.errors import GoogleAdsException  # type: ignore[import]
    _SDK_AVAILABLE = True
except ImportError as _e:
    _SDK_IMPORT_ERROR = str(_e)


def _sdk_error_dict(method: str) -> dict:
    """Return a standardised error dict when the SDK is unavailable."""
    return {
        "error": True,
        "method": method,
        "reason": "google-ads SDK not installed",
        "fix": "pip install google-ads",
        "detail": _SDK_IMPORT_ERROR,
    }


def _creds_error_dict(method: str, missing_key: str) -> dict:
    """Return a standardised error dict when a credential is missing."""
    return {
        "error": True,
        "method": method,
        "reason": f"Missing or placeholder credential: {missing_key}",
        "fix": f"Add {missing_key} to .env.agents",
    }


# ---------------------------------------------------------------------------
# GoogleAdsEngine
# ---------------------------------------------------------------------------


class GoogleAdsEngine:
    """
    High-level client for the Google Ads API (google-ads SDK v29+).

    All public methods:
      - Enforce a rate-limit delay before every API call.
      - Return clean Python dicts (never raw proto-plus objects).
      - Return an error dict (instead of raising) when the SDK is absent or
        credentials are missing, so callers can check for the "error" key.
      - Raise GoogleAdsException (re-wrapped as RuntimeError) on hard API
        failures once all retries are exhausted.

    Google Ads concepts used:
      - CampaignBudgetService  — daily budget creation
      - CampaignService        — campaign CRUD
      - AdGroupService         — ad group CRUD
      - AdGroupAdService       — responsive search ad CRUD
      - AdGroupCriterionService — keyword / negative keyword CRUD
      - GoogleAdsService       — GAQL search_stream queries
      - RecommendationService  — optimization recommendations
    """

    def __init__(
        self,
        developer_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> None:
        """
        Initialise the engine.  All arguments are optional — they fall back
        to .env.agents values.  If the SDK is absent or any required
        credential is missing, self._ready is set to False and every public
        method returns an error dict rather than crashing.
        """
        self._ready: bool = False
        self._client: Optional[object] = None  # GoogleAdsClient when ready
        self.customer_id: str = ""
        self._missing_key: str = ""

        if not _SDK_AVAILABLE:
            log.warning(
                "google-ads SDK not installed — GoogleAdsEngine in degraded mode. "
                "Run: pip install google-ads"
            )
            return

        try:
            creds = _load_env_agents()
        except FileNotFoundError as exc:
            log.warning("GoogleAdsEngine: %s", exc)
            return

        def _resolve(override: Optional[str], key: str) -> str:
            val = override or creds.get(key, "")
            if _is_placeholder(val):
                return ""
            return val

        dev_token = _resolve(developer_token, "GOOGLE_ADS_DEVELOPER_TOKEN")
        c_id = _resolve(client_id, "GOOGLE_ADS_CLIENT_ID")
        c_secret = _resolve(client_secret, "GOOGLE_ADS_CLIENT_SECRET")
        r_token = _resolve(refresh_token, "GOOGLE_ADS_REFRESH_TOKEN")
        cust_id = _resolve(customer_id, "GOOGLE_ADS_CUSTOMER_ID")

        for key, val in [
            ("GOOGLE_ADS_DEVELOPER_TOKEN", dev_token),
            ("GOOGLE_ADS_CLIENT_ID", c_id),
            ("GOOGLE_ADS_CLIENT_SECRET", c_secret),
            ("GOOGLE_ADS_REFRESH_TOKEN", r_token),
            ("GOOGLE_ADS_CUSTOMER_ID", cust_id),
        ]:
            if not val:
                log.warning(
                    "GoogleAdsEngine: missing credential %s — engine in degraded mode. "
                    "Add it to .env.agents to enable Google Ads operations.",
                    key,
                )
                self._missing_key = key
                return

        self.customer_id = _normalise_customer_id(cust_id)

        google_ads_config = {
            "developer_token": dev_token,
            "client_id": c_id,
            "client_secret": c_secret,
            "refresh_token": r_token,
            "login_customer_id": self.customer_id,
            "use_proto_plus": True,
        }

        try:
            self._client = GoogleAdsClient.load_from_dict(google_ads_config)
            self._ready = True
            log.info(
                "GoogleAdsEngine ready — customer ID: %s", self.customer_id
            )
        except Exception as exc:
            log.warning("GoogleAdsEngine: failed to initialise SDK client: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _guard(self, method: str) -> Optional[dict]:
        """
        Return an error dict if the engine is not ready, else None.
        Callers should check: err = self._guard(method); if err: return err
        """
        if not _SDK_AVAILABLE:
            return _sdk_error_dict(method)
        if not self._ready or self._client is None:
            key = self._missing_key or "GOOGLE_ADS_*"
            return _creds_error_dict(method, key)
        return None

    def _gaql(self, query: str) -> list[dict]:
        """
        Execute a GAQL query via search_stream, collect all rows, and return
        them as a list of raw proto-plus Row objects wrapped in a list.

        Internal only — callers convert rows to dicts themselves.
        """
        # Returns the raw iterator; callers iterate batches
        ga_service = self._client.get_service("GoogleAdsService")  # type: ignore[union-attr]
        time.sleep(RATE_LIMIT_DELAY)
        return ga_service.search_stream(
            customer_id=self.customer_id, query=query
        )

    def _mutate_with_retry(self, service_name: str, mutate_fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        """
        Call a mutate function with retry logic for transient errors.

        Args:
            service_name: Human-readable name for log messages.
            mutate_fn: Callable that performs the actual SDK mutate call.
            *args / **kwargs: Forwarded to mutate_fn.

        Returns:
            The MutateResponse from the SDK call.

        Raises:
            RuntimeError wrapping GoogleAdsException on non-transient failures
            or after all retries are exhausted.
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                time.sleep(RATE_LIMIT_DELAY)
                return mutate_fn(*args, **kwargs)

            except GoogleAdsException as exc:  # type: ignore[possibly-undefined]
                # Inspect errors for transient status codes
                is_transient = any(
                    err.error_code.WhichOneof("error_code") in _TRANSIENT_STATUSES
                    or "TRANSIENT" in str(err.error_code).upper()
                    or "INTERNAL" in str(err.error_code).upper()
                    for err in exc.failure.errors
                )
                error_details = "; ".join(
                    f"{e.message} ({e.error_code})" for e in exc.failure.errors
                )
                if is_transient:
                    log.warning(
                        "Transient Google Ads error on %s (attempt %d/%d): %s",
                        service_name,
                        attempt,
                        RETRY_ATTEMPTS,
                        error_details,
                    )
                    last_error = RuntimeError(
                        f"Google Ads transient error: {error_details}"
                    )
                    if attempt < RETRY_ATTEMPTS:
                        time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue

                # Non-transient: fail immediately
                raise RuntimeError(
                    f"Google Ads API error in {service_name}: {error_details}\n"
                    f"Request ID: {exc.request_id}"
                ) from exc

            except Exception as exc:
                log.warning(
                    "Unexpected error on %s (attempt %d/%d): %s",
                    service_name,
                    attempt,
                    RETRY_ATTEMPTS,
                    exc,
                )
                last_error = exc
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_BASE * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"All {RETRY_ATTEMPTS} attempts failed for {service_name}. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Campaign operations
    # ------------------------------------------------------------------

    def create_search_campaign(
        self,
        name: str,
        budget_amount: float,
        bidding_strategy: str = "MAXIMIZE_CONVERSIONS",
        status: str = "PAUSED",
    ) -> dict:
        """
        Create a Search campaign with a daily budget.

        Creates the budget resource first, then the campaign.  Always defaults
        to PAUSED so the operator can review before going live.

        Args:
            name: Display name for the campaign.
            budget_amount: Daily budget in US dollars (e.g. 50.0 for $50/day).
            bidding_strategy: One of MAXIMIZE_CONVERSIONS, MAXIMIZE_CLICKS,
                              TARGET_CPA, MANUAL_CPC.
            status: PAUSED or ENABLED.

        Returns:
            dict with id, name, status, budget_usd, bidding_strategy,
            budget_resource_name, campaign_resource_name.
        """
        err = self._guard("create_search_campaign")
        if err:
            return err

        log.info(
            "Creating search campaign '%s' (budget=$%.2f/day, bidding=%s)",
            name,
            budget_amount,
            bidding_strategy,
        )

        # --- 1. Budget ---
        budget_service = self._client.get_service("CampaignBudgetService")  # type: ignore[union-attr]
        budget_op = self._client.get_type("CampaignBudgetOperation")  # type: ignore[union-attr]
        budget = budget_op.create
        budget.name = f"{name} Budget"
        budget.amount_micros = int(budget_amount * _MICROS)
        budget.delivery_method = (
            self._client.enums.BudgetDeliveryMethodEnum.STANDARD  # type: ignore[union-attr]
        )
        budget.explicitly_shared = False

        budget_response = self._mutate_with_retry(
            "CampaignBudgetService",
            budget_service.mutate_campaign_budgets,
            customer_id=self.customer_id,
            operations=[budget_op],
        )
        budget_resource = budget_response.results[0].resource_name
        log.info("Budget created: %s", budget_resource)

        # --- 2. Campaign ---
        campaign_service = self._client.get_service("CampaignService")  # type: ignore[union-attr]
        campaign_op = self._client.get_type("CampaignOperation")  # type: ignore[union-attr]
        campaign = campaign_op.create
        campaign.name = name
        campaign.advertising_channel_type = (
            self._client.enums.AdvertisingChannelTypeEnum.SEARCH  # type: ignore[union-attr]
        )
        campaign.campaign_budget = budget_resource
        campaign.status = getattr(
            self._client.enums.CampaignStatusEnum, status.upper()  # type: ignore[union-attr]
        )

        # Network settings — Google Search + Search Partners
        campaign.network_settings.target_google_search = True
        campaign.network_settings.target_search_network = True
        campaign.network_settings.target_content_network = False

        # Bidding strategy
        strategy = bidding_strategy.upper()
        if strategy == "MAXIMIZE_CONVERSIONS":
            campaign.maximize_conversions.target_cpa_micros = 0
        elif strategy == "MAXIMIZE_CLICKS":
            campaign.maximize_clicks.cpc_bid_ceiling_micros = 0
        elif strategy == "MANUAL_CPC":
            campaign.manual_cpc.enhanced_cpc_enabled = False
        elif strategy == "TARGET_CPA":
            campaign.target_cpa.target_cpa_micros = 0
        else:
            log.warning(
                "Unknown bidding strategy '%s' — defaulting to MAXIMIZE_CONVERSIONS",
                bidding_strategy,
            )
            campaign.maximize_conversions.target_cpa_micros = 0

        campaign_response = self._mutate_with_retry(
            "CampaignService",
            campaign_service.mutate_campaigns,
            customer_id=self.customer_id,
            operations=[campaign_op],
        )
        campaign_resource = campaign_response.results[0].resource_name
        # Extract numeric campaign ID from resource name (customers/X/campaigns/Y)
        campaign_id = campaign_resource.split("/")[-1]

        log.info("Campaign created: %s (ID: %s)", name, campaign_id)
        return {
            "id": campaign_id,
            "name": name,
            "status": status.upper(),
            "budget_usd": budget_amount,
            "bidding_strategy": bidding_strategy,
            "budget_resource_name": budget_resource,
            "campaign_resource_name": campaign_resource,
        }

    def pause_campaign(self, campaign_id: str) -> dict:
        """
        Set campaign status to PAUSED.

        Args:
            campaign_id: Numeric campaign ID (string).

        Returns:
            dict with id, status.
        """
        err = self._guard("pause_campaign")
        if err:
            return err

        log.info("Pausing campaign: %s", campaign_id)
        campaign_service = self._client.get_service("CampaignService")  # type: ignore[union-attr]
        campaign_op = self._client.get_type("CampaignOperation")  # type: ignore[union-attr]
        campaign = campaign_op.update
        campaign.resource_name = campaign_service.campaign_path(
            self.customer_id, campaign_id
        )
        campaign.status = self._client.enums.CampaignStatusEnum.PAUSED  # type: ignore[union-attr]
        campaign_op.update_mask.paths.append("status")

        self._mutate_with_retry(
            "CampaignService (pause)",
            campaign_service.mutate_campaigns,
            customer_id=self.customer_id,
            operations=[campaign_op],
        )
        log.info("Campaign %s paused.", campaign_id)
        return {"id": campaign_id, "status": "PAUSED"}

    def resume_campaign(self, campaign_id: str) -> dict:
        """
        Set campaign status to ENABLED.

        Args:
            campaign_id: Numeric campaign ID (string).

        Returns:
            dict with id, status.
        """
        err = self._guard("resume_campaign")
        if err:
            return err

        log.info("Resuming campaign: %s", campaign_id)
        campaign_service = self._client.get_service("CampaignService")  # type: ignore[union-attr]
        campaign_op = self._client.get_type("CampaignOperation")  # type: ignore[union-attr]
        campaign = campaign_op.update
        campaign.resource_name = campaign_service.campaign_path(
            self.customer_id, campaign_id
        )
        campaign.status = self._client.enums.CampaignStatusEnum.ENABLED  # type: ignore[union-attr]
        campaign_op.update_mask.paths.append("status")

        self._mutate_with_retry(
            "CampaignService (resume)",
            campaign_service.mutate_campaigns,
            customer_id=self.customer_id,
            operations=[campaign_op],
        )
        log.info("Campaign %s resumed (ENABLED).", campaign_id)
        return {"id": campaign_id, "status": "ENABLED"}

    def get_all_campaigns(self) -> list[dict] | dict:
        """
        Return all non-removed campaigns for the account.

        Returns:
            List of dicts with id, name, status, budget_usd, bidding_strategy,
            channel_type.  Returns error dict if not ready.
        """
        err = self._guard("get_all_campaigns")
        if err:
            return err  # type: ignore[return-value]

        log.info("Fetching all campaigns for customer %s ...", self.customer_id)
        query = """
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign.bidding_strategy_type,
                campaign_budget.amount_micros
            FROM campaign
            WHERE campaign.status != 'REMOVED'
            ORDER BY campaign.name ASC
        """
        campaigns = []
        for batch in self._gaql(query):
            for row in batch.results:
                campaigns.append({
                    "id": str(row.campaign.id),
                    "name": row.campaign.name,
                    "status": row.campaign.status.name,
                    "channel_type": row.campaign.advertising_channel_type.name,
                    "bidding_strategy": row.campaign.bidding_strategy_type.name,
                    "budget_usd": round(
                        row.campaign_budget.amount_micros / _MICROS, 2
                    ),
                })
        log.info("Found %d campaigns.", len(campaigns))
        return campaigns

    # ------------------------------------------------------------------
    # Ad Group operations
    # ------------------------------------------------------------------

    def create_ad_group(
        self,
        campaign_id: str,
        name: str,
        cpc_bid: float = 2.0,
        status: str = "ENABLED",
    ) -> dict:
        """
        Create an ad group within a campaign.

        Args:
            campaign_id: Numeric campaign ID.
            name: Display name for the ad group.
            cpc_bid: Default CPC bid in US dollars (e.g. 2.0 for $2.00).
            status: ENABLED or PAUSED.

        Returns:
            dict with id, name, campaign_id, status, cpc_bid_usd.
        """
        err = self._guard("create_ad_group")
        if err:
            return err

        log.info(
            "Creating ad group '%s' in campaign %s (cpc=$%.2f)",
            name,
            campaign_id,
            cpc_bid,
        )
        ad_group_service = self._client.get_service("AdGroupService")  # type: ignore[union-attr]
        campaign_service = self._client.get_service("CampaignService")  # type: ignore[union-attr]

        ad_group_op = self._client.get_type("AdGroupOperation")  # type: ignore[union-attr]
        ag = ad_group_op.create
        ag.name = name
        ag.campaign = campaign_service.campaign_path(self.customer_id, campaign_id)
        ag.status = getattr(
            self._client.enums.AdGroupStatusEnum, status.upper()  # type: ignore[union-attr]
        )
        ag.type_ = self._client.enums.AdGroupTypeEnum.SEARCH_STANDARD  # type: ignore[union-attr]
        ag.cpc_bid_micros = int(cpc_bid * _MICROS)

        response = self._mutate_with_retry(
            "AdGroupService",
            ad_group_service.mutate_ad_groups,
            customer_id=self.customer_id,
            operations=[ad_group_op],
        )
        resource_name = response.results[0].resource_name
        ad_group_id = resource_name.split("/")[-1]

        log.info("Ad group created: %s (ID: %s)", name, ad_group_id)
        return {
            "id": ad_group_id,
            "name": name,
            "campaign_id": campaign_id,
            "status": status.upper(),
            "cpc_bid_usd": cpc_bid,
            "resource_name": resource_name,
        }

    def get_all_ad_groups(self, campaign_id: str) -> list[dict] | dict:
        """
        Return all non-removed ad groups within a campaign.

        Args:
            campaign_id: Numeric campaign ID.

        Returns:
            List of dicts with id, name, campaign_id, status, cpc_bid_usd.
        """
        err = self._guard("get_all_ad_groups")
        if err:
            return err  # type: ignore[return-value]

        log.info("Fetching ad groups for campaign %s ...", campaign_id)
        query = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group.status,
                ad_group.cpc_bid_micros,
                ad_group.type
            FROM ad_group
            WHERE campaign.id = {campaign_id}
              AND ad_group.status != 'REMOVED'
            ORDER BY ad_group.name ASC
        """
        ad_groups = []
        for batch in self._gaql(query):
            for row in batch.results:
                ad_groups.append({
                    "id": str(row.ad_group.id),
                    "name": row.ad_group.name,
                    "campaign_id": campaign_id,
                    "status": row.ad_group.status.name,
                    "cpc_bid_usd": round(row.ad_group.cpc_bid_micros / _MICROS, 2),
                    "type": row.ad_group.type_.name,
                })
        log.info("Found %d ad groups.", len(ad_groups))
        return ad_groups

    # ------------------------------------------------------------------
    # Responsive Search Ad operations
    # ------------------------------------------------------------------

    def create_responsive_search_ad(
        self,
        ad_group_id: str,
        headlines: list[str],
        descriptions: list[str],
        final_url: str = JOTFORM_URL,
        path1: str = "",
        path2: str = "",
        status: str = "ENABLED",
    ) -> dict:
        """
        Create a Responsive Search Ad (RSA) in an ad group.

        Google requires at least 3 headlines and 2 descriptions.
        Maximum: 15 headlines, 4 descriptions.

        Args:
            ad_group_id: Numeric ad group ID.
            headlines: List of headline strings (3–15). Each max 30 chars.
            descriptions: List of description strings (2–4). Each max 90 chars.
            final_url: Landing page URL. Defaults to JotForm.
            path1: First URL display path (max 15 chars). Optional.
            path2: Second URL display path (max 15 chars). Optional.
            status: ENABLED or PAUSED.

        Returns:
            dict with id, ad_group_id, headlines, descriptions, final_url,
            status, resource_name.
        """
        err = self._guard("create_responsive_search_ad")
        if err:
            return err

        if len(headlines) < 3:
            return {
                "error": True,
                "method": "create_responsive_search_ad",
                "reason": f"At least 3 headlines required, got {len(headlines)}",
            }
        if len(descriptions) < 2:
            return {
                "error": True,
                "method": "create_responsive_search_ad",
                "reason": f"At least 2 descriptions required, got {len(descriptions)}",
            }

        # Enforce maximums per Google spec
        headlines = headlines[:15]
        descriptions = descriptions[:4]

        log.info(
            "Creating RSA in ad group %s (%d headlines, %d descriptions)",
            ad_group_id,
            len(headlines),
            len(descriptions),
        )

        ad_group_service = self._client.get_service("AdGroupService")  # type: ignore[union-attr]
        ad_group_ad_service = self._client.get_service("AdGroupAdService")  # type: ignore[union-attr]

        ad_group_ad_op = self._client.get_type("AdGroupAdOperation")  # type: ignore[union-attr]
        ad_group_ad = ad_group_ad_op.create
        ad_group_ad.ad_group = ad_group_service.ad_group_path(
            self.customer_id, ad_group_id
        )
        ad_group_ad.status = getattr(
            self._client.enums.AdGroupAdStatusEnum, status.upper()  # type: ignore[union-attr]
        )

        # Build RSA
        rsa = ad_group_ad.ad.responsive_search_ad
        for text in headlines:
            asset = self._client.get_type("AdTextAsset")  # type: ignore[union-attr]
            asset.text = text
            rsa.headlines.append(asset)

        for text in descriptions:
            asset = self._client.get_type("AdTextAsset")  # type: ignore[union-attr]
            asset.text = text
            rsa.descriptions.append(asset)

        if path1:
            rsa.path1 = path1
        if path2:
            rsa.path2 = path2

        ad_group_ad.ad.final_urls.append(final_url)

        response = self._mutate_with_retry(
            "AdGroupAdService (RSA)",
            ad_group_ad_service.mutate_ad_group_ads,
            customer_id=self.customer_id,
            operations=[ad_group_ad_op],
        )
        resource_name = response.results[0].resource_name
        ad_id = resource_name.split("/")[-1]

        log.info("RSA created: %s", resource_name)
        return {
            "id": ad_id,
            "ad_group_id": ad_group_id,
            "headlines": headlines,
            "descriptions": descriptions,
            "final_url": final_url,
            "path1": path1,
            "path2": path2,
            "status": status.upper(),
            "resource_name": resource_name,
        }

    # ------------------------------------------------------------------
    # Keyword operations
    # ------------------------------------------------------------------

    def add_keywords(
        self,
        ad_group_id: str,
        keywords: list[str],
        match_type: str = "BROAD",
        cpc_bid: Optional[float] = None,
    ) -> dict:
        """
        Add positive keywords to an ad group.

        Args:
            ad_group_id: Numeric ad group ID.
            keywords: List of keyword strings (without match type brackets).
            match_type: BROAD, PHRASE, or EXACT.
            cpc_bid: Optional keyword-level CPC bid in dollars. If None,
                     the ad group default bid applies.

        Returns:
            dict with added_count, ad_group_id, match_type, keywords.
        """
        err = self._guard("add_keywords")
        if err:
            return err

        match_type_upper = match_type.upper()
        valid_match_types = {"BROAD", "PHRASE", "EXACT"}
        if match_type_upper not in valid_match_types:
            return {
                "error": True,
                "method": "add_keywords",
                "reason": f"Invalid match_type '{match_type}'. Must be one of {valid_match_types}",
            }

        log.info(
            "Adding %d %s-match keywords to ad group %s",
            len(keywords),
            match_type_upper,
            ad_group_id,
        )

        ad_group_criterion_service = self._client.get_service(  # type: ignore[union-attr]
            "AdGroupCriterionService"
        )
        ad_group_service = self._client.get_service("AdGroupService")  # type: ignore[union-attr]

        operations = []
        for kw_text in keywords:
            op = self._client.get_type("AdGroupCriterionOperation")  # type: ignore[union-attr]
            criterion = op.create
            criterion.ad_group = ad_group_service.ad_group_path(
                self.customer_id, ad_group_id
            )
            criterion.status = (
                self._client.enums.AdGroupCriterionStatusEnum.ENABLED  # type: ignore[union-attr]
            )
            criterion.keyword.text = kw_text
            criterion.keyword.match_type = getattr(
                self._client.enums.KeywordMatchTypeEnum, match_type_upper  # type: ignore[union-attr]
            )
            if cpc_bid is not None:
                criterion.cpc_bid_micros = int(cpc_bid * _MICROS)
            operations.append(op)

        response = self._mutate_with_retry(
            "AdGroupCriterionService (keywords)",
            ad_group_criterion_service.mutate_ad_group_criteria,
            customer_id=self.customer_id,
            operations=operations,
        )
        added_count = len(response.results)
        log.info("Added %d keywords.", added_count)
        return {
            "added_count": added_count,
            "ad_group_id": ad_group_id,
            "match_type": match_type_upper,
            "keywords": keywords,
        }

    def add_negative_keywords(
        self,
        campaign_id: str,
        keywords: list[str],
        match_type: str = "BROAD",
    ) -> dict:
        """
        Add campaign-level negative keywords.

        Args:
            campaign_id: Numeric campaign ID.
            keywords: List of negative keyword strings.
            match_type: BROAD, PHRASE, or EXACT.

        Returns:
            dict with added_count, campaign_id, match_type, keywords.
        """
        err = self._guard("add_negative_keywords")
        if err:
            return err

        match_type_upper = match_type.upper()
        log.info(
            "Adding %d negative keywords to campaign %s (%s match)",
            len(keywords),
            campaign_id,
            match_type_upper,
        )

        campaign_criterion_service = self._client.get_service(  # type: ignore[union-attr]
            "CampaignCriterionService"
        )
        campaign_service = self._client.get_service("CampaignService")  # type: ignore[union-attr]

        operations = []
        for kw_text in keywords:
            op = self._client.get_type("CampaignCriterionOperation")  # type: ignore[union-attr]
            criterion = op.create
            criterion.campaign = campaign_service.campaign_path(
                self.customer_id, campaign_id
            )
            criterion.negative = True
            criterion.keyword.text = kw_text
            criterion.keyword.match_type = getattr(
                self._client.enums.KeywordMatchTypeEnum, match_type_upper  # type: ignore[union-attr]
            )
            operations.append(op)

        response = self._mutate_with_retry(
            "CampaignCriterionService (negative keywords)",
            campaign_criterion_service.mutate_campaign_criteria,
            customer_id=self.customer_id,
            operations=operations,
        )
        added_count = len(response.results)
        log.info("Added %d negative keywords.", added_count)
        return {
            "added_count": added_count,
            "campaign_id": campaign_id,
            "match_type": match_type_upper,
            "keywords": keywords,
        }

    def pause_keyword(self, keyword_id: str, ad_group_id: str) -> dict:
        """
        Pause a specific keyword within an ad group.

        Args:
            keyword_id: Numeric criterion ID for the keyword.
            ad_group_id: Numeric ad group ID containing the keyword.

        Returns:
            dict with keyword_id, ad_group_id, status.
        """
        err = self._guard("pause_keyword")
        if err:
            return err

        log.info("Pausing keyword %s in ad group %s", keyword_id, ad_group_id)
        ad_group_criterion_service = self._client.get_service(  # type: ignore[union-attr]
            "AdGroupCriterionService"
        )
        op = self._client.get_type("AdGroupCriterionOperation")  # type: ignore[union-attr]
        criterion = op.update
        criterion.resource_name = (
            ad_group_criterion_service.ad_group_criterion_path(
                self.customer_id, ad_group_id, keyword_id
            )
        )
        criterion.status = (
            self._client.enums.AdGroupCriterionStatusEnum.PAUSED  # type: ignore[union-attr]
        )
        op.update_mask.paths.append("status")

        self._mutate_with_retry(
            "AdGroupCriterionService (pause keyword)",
            ad_group_criterion_service.mutate_ad_group_criteria,
            customer_id=self.customer_id,
            operations=[op],
        )
        log.info("Keyword %s paused.", keyword_id)
        return {"keyword_id": keyword_id, "ad_group_id": ad_group_id, "status": "PAUSED"}

    def update_keyword_bid(
        self, keyword_id: str, ad_group_id: str, new_bid: float
    ) -> dict:
        """
        Update the CPC bid for a specific keyword.

        Args:
            keyword_id: Numeric criterion ID for the keyword.
            ad_group_id: Numeric ad group ID containing the keyword.
            new_bid: New CPC bid in US dollars.

        Returns:
            dict with keyword_id, ad_group_id, new_bid_usd.
        """
        err = self._guard("update_keyword_bid")
        if err:
            return err

        log.info(
            "Updating bid for keyword %s to $%.2f", keyword_id, new_bid
        )
        ad_group_criterion_service = self._client.get_service(  # type: ignore[union-attr]
            "AdGroupCriterionService"
        )
        op = self._client.get_type("AdGroupCriterionOperation")  # type: ignore[union-attr]
        criterion = op.update
        criterion.resource_name = (
            ad_group_criterion_service.ad_group_criterion_path(
                self.customer_id, ad_group_id, keyword_id
            )
        )
        criterion.cpc_bid_micros = int(new_bid * _MICROS)
        op.update_mask.paths.append("cpc_bid_micros")

        self._mutate_with_retry(
            "AdGroupCriterionService (update bid)",
            ad_group_criterion_service.mutate_ad_group_criteria,
            customer_id=self.customer_id,
            operations=[op],
        )
        log.info("Keyword %s bid updated to $%.2f.", keyword_id, new_bid)
        return {
            "keyword_id": keyword_id,
            "ad_group_id": ad_group_id,
            "new_bid_usd": new_bid,
        }

    # ------------------------------------------------------------------
    # Performance reporting
    # ------------------------------------------------------------------

    def get_campaign_performance(
        self, date_range: str = "LAST_7_DAYS"
    ) -> list[dict] | dict:
        """
        Retrieve campaign-level performance metrics via GAQL.

        Args:
            date_range: Google Ads date range constant, e.g. TODAY, YESTERDAY,
                        LAST_7_DAYS, LAST_30_DAYS, THIS_MONTH, LAST_MONTH,
                        ALL_TIME.

        Returns:
            List of dicts with campaign_id, campaign_name, status, impressions,
            clicks, ctr_pct, avg_cpc_usd, conversions, cost_usd,
            cost_per_conversion_usd.
        """
        err = self._guard("get_campaign_performance")
        if err:
            return err  # type: ignore[return-value]

        log.info("Fetching campaign performance for %s ...", date_range)
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.conversions,
                metrics.cost_micros,
                metrics.cost_per_conversion
            FROM campaign
            WHERE campaign.status != 'REMOVED'
              AND segments.date DURING {date_range}
            ORDER BY metrics.cost_micros DESC
        """
        results = []
        for batch in self._gaql(query):
            for row in batch.results:
                cost_usd = round(row.metrics.cost_micros / _MICROS, 2)
                conv = row.metrics.conversions
                cost_per_conv = (
                    round(row.metrics.cost_per_conversion / _MICROS, 2)
                    if conv > 0
                    else None
                )
                results.append({
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "status": row.campaign.status.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "ctr_pct": round(row.metrics.ctr * 100, 2),
                    "avg_cpc_usd": round(row.metrics.average_cpc / _MICROS, 2),
                    "conversions": round(conv, 1),
                    "cost_usd": cost_usd,
                    "cost_per_conversion_usd": cost_per_conv,
                })
        log.info("Retrieved performance for %d campaigns.", len(results))
        return results

    def get_keyword_performance(
        self, campaign_id: str, date_range: str = "LAST_7_DAYS"
    ) -> list[dict] | dict:
        """
        Retrieve keyword-level performance including Quality Score.

        Args:
            campaign_id: Numeric campaign ID to filter by.
            date_range: Google Ads date range constant.

        Returns:
            List of dicts per keyword with text, match_type, quality_score,
            impressions, clicks, avg_cpc_usd, conversions, cost_usd.
        """
        err = self._guard("get_keyword_performance")
        if err:
            return err  # type: ignore[return-value]

        log.info(
            "Fetching keyword performance for campaign %s (%s) ...",
            campaign_id,
            date_range,
        )
        query = f"""
            SELECT
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.quality_info.search_predicted_ctr,
                ad_group_criterion.quality_info.ad_relevance,
                ad_group_criterion.quality_info.landing_page_experience,
                metrics.impressions,
                metrics.clicks,
                metrics.average_cpc,
                metrics.conversions,
                metrics.cost_micros
            FROM keyword_view
            WHERE campaign.id = {campaign_id}
              AND ad_group_criterion.status != 'REMOVED'
              AND segments.date DURING {date_range}
            ORDER BY metrics.impressions DESC
        """
        results = []
        for batch in self._gaql(query):
            for row in batch.results:
                qi = row.ad_group_criterion.quality_info
                results.append({
                    "criterion_id": str(row.ad_group_criterion.criterion_id),
                    "keyword": row.ad_group_criterion.keyword.text,
                    "match_type": row.ad_group_criterion.keyword.match_type.name,
                    "status": row.ad_group_criterion.status.name,
                    "quality_score": qi.quality_score if qi.quality_score else None,
                    "predicted_ctr": qi.search_predicted_ctr.name
                    if qi.search_predicted_ctr
                    else None,
                    "ad_relevance": qi.ad_relevance.name
                    if qi.ad_relevance
                    else None,
                    "landing_page_experience": qi.landing_page_experience.name
                    if qi.landing_page_experience
                    else None,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "avg_cpc_usd": round(row.metrics.average_cpc / _MICROS, 2),
                    "conversions": round(row.metrics.conversions, 1),
                    "cost_usd": round(row.metrics.cost_micros / _MICROS, 2),
                })
        log.info("Retrieved %d keyword rows.", len(results))
        return results

    def get_search_terms_report(
        self, campaign_id: str, date_range: str = "LAST_7_DAYS"
    ) -> list[dict] | dict:
        """
        Retrieve the search terms report — actual queries that triggered ads.

        Useful for discovering new negative keywords and expanding keyword lists.

        Args:
            campaign_id: Numeric campaign ID.
            date_range: Google Ads date range constant.

        Returns:
            List of dicts with search_term, match_type, impressions, clicks,
            ctr_pct, avg_cpc_usd, conversions, cost_usd.
        """
        err = self._guard("get_search_terms_report")
        if err:
            return err  # type: ignore[return-value]

        log.info(
            "Fetching search terms report for campaign %s (%s) ...",
            campaign_id,
            date_range,
        )
        query = f"""
            SELECT
                search_term_view.search_term,
                search_term_view.status,
                segments.keyword.info.match_type,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.conversions,
                metrics.cost_micros
            FROM search_term_view
            WHERE campaign.id = {campaign_id}
              AND segments.date DURING {date_range}
            ORDER BY metrics.impressions DESC
        """
        results = []
        for batch in self._gaql(query):
            for row in batch.results:
                results.append({
                    "search_term": row.search_term_view.search_term,
                    "status": row.search_term_view.status.name,
                    "match_type": row.segments.keyword.info.match_type.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "ctr_pct": round(row.metrics.ctr * 100, 2),
                    "avg_cpc_usd": round(row.metrics.average_cpc / _MICROS, 2),
                    "conversions": round(row.metrics.conversions, 1),
                    "cost_usd": round(row.metrics.cost_micros / _MICROS, 2),
                })
        log.info("Retrieved %d search term rows.", len(results))
        return results

    def get_quality_score_report(self) -> list[dict] | dict:
        """
        Retrieve quality scores for all active keywords across all campaigns.

        Quality Score (1–10) is a diagnostic metric reflecting ad relevance,
        expected CTR, and landing page experience.

        Returns:
            List of dicts sorted by quality_score ascending (lowest first
            for optimisation priority) with keyword, campaign, ad_group,
            quality_score, predicted_ctr, ad_relevance, landing_page_experience.
        """
        err = self._guard("get_quality_score_report")
        if err:
            return err  # type: ignore[return-value]

        log.info("Fetching quality score report ...")
        query = """
            SELECT
                campaign.id,
                campaign.name,
                ad_group.id,
                ad_group.name,
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.quality_info.search_predicted_ctr,
                ad_group_criterion.quality_info.ad_relevance,
                ad_group_criterion.quality_info.landing_page_experience
            FROM keyword_view
            WHERE ad_group_criterion.status = 'ENABLED'
              AND campaign.status = 'ENABLED'
              AND ad_group.status = 'ENABLED'
            ORDER BY ad_group_criterion.quality_info.quality_score ASC
        """
        results = []
        for batch in self._gaql(query):
            for row in batch.results:
                qi = row.ad_group_criterion.quality_info
                results.append({
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "criterion_id": str(row.ad_group_criterion.criterion_id),
                    "keyword": row.ad_group_criterion.keyword.text,
                    "match_type": row.ad_group_criterion.keyword.match_type.name,
                    "quality_score": qi.quality_score if qi.quality_score else None,
                    "predicted_ctr": qi.search_predicted_ctr.name
                    if qi.search_predicted_ctr
                    else None,
                    "ad_relevance": qi.ad_relevance.name
                    if qi.ad_relevance
                    else None,
                    "landing_page_experience": qi.landing_page_experience.name
                    if qi.landing_page_experience
                    else None,
                })
        log.info("Retrieved quality scores for %d keywords.", len(results))
        return results

    def get_recommendations(self) -> list[dict] | dict:
        """
        Retrieve Google's automated optimization recommendations for the account.

        Returns:
            List of dicts with type, impact, campaign_id, description.
        """
        err = self._guard("get_recommendations")
        if err:
            return err  # type: ignore[return-value]

        log.info("Fetching Google Ads recommendations ...")
        query = """
            SELECT
                recommendation.type,
                recommendation.impact.base_metrics.impressions,
                recommendation.impact.potential_metrics.impressions,
                recommendation.campaign,
                recommendation.resource_name
            FROM recommendation
        """
        results = []
        for batch in self._gaql(query):
            for row in batch.results:
                base_impr = (
                    row.recommendation.impact.base_metrics.impressions
                    if row.recommendation.impact
                    else None
                )
                potential_impr = (
                    row.recommendation.impact.potential_metrics.impressions
                    if row.recommendation.impact
                    else None
                )
                impression_uplift = (
                    potential_impr - base_impr
                    if base_impr is not None and potential_impr is not None
                    else None
                )
                campaign_resource = row.recommendation.campaign
                campaign_id = (
                    campaign_resource.split("/")[-1]
                    if campaign_resource
                    else None
                )
                results.append({
                    "type": row.recommendation.type_.name,
                    "campaign_id": campaign_id,
                    "base_impressions": base_impr,
                    "potential_impressions": potential_impr,
                    "impression_uplift": impression_uplift,
                    "resource_name": row.recommendation.resource_name,
                })
        log.info("Found %d recommendations.", len(results))
        return results

    # ------------------------------------------------------------------
    # Composite / end-to-end helpers
    # ------------------------------------------------------------------

    def create_full_search_campaign(
        self,
        name: str,
        budget: float,
        keywords: list[str],
        headlines: list[str],
        descriptions: list[str],
        final_url: str = JOTFORM_URL,
        negative_keywords: Optional[list[str]] = None,
        match_type: str = "BROAD",
        bidding_strategy: str = "MAXIMIZE_CONVERSIONS",
        cpc_bid: float = 2.0,
        status: str = "PAUSED",
    ) -> dict:
        """
        End-to-end campaign creation: campaign + ad group + RSA + keywords +
        optional negative keywords — all in one call.

        Always creates in PAUSED status by default for review before going live.

        Args:
            name: Campaign display name.
            budget: Daily budget in US dollars.
            keywords: Positive keyword list.
            headlines: RSA headline list (3–15 items, each max 30 chars).
            descriptions: RSA description list (2–4 items, each max 90 chars).
            final_url: Landing page. Defaults to JotForm.
            negative_keywords: Optional campaign-level negative keyword list.
            match_type: Keyword match type — BROAD, PHRASE, or EXACT.
            bidding_strategy: Bidding strategy for the campaign.
            cpc_bid: Default ad group CPC bid in dollars.
            status: Initial status — PAUSED (default) or ENABLED.

        Returns:
            dict with campaign, ad_group, ad, keywords, negative_keywords keys,
            each containing the result dict from the individual create calls.
        """
        err = self._guard("create_full_search_campaign")
        if err:
            return err

        log.info("=== create_full_search_campaign: '%s' ===", name)

        # 1. Campaign
        campaign_result = self.create_search_campaign(
            name=name,
            budget_amount=budget,
            bidding_strategy=bidding_strategy,
            status=status,
        )
        if campaign_result.get("error"):
            return {"error": True, "step": "campaign", "detail": campaign_result}
        campaign_id = campaign_result["id"]

        # 2. Ad Group
        ad_group_result = self.create_ad_group(
            campaign_id=campaign_id,
            name=f"{name} — Ad Group 1",
            cpc_bid=cpc_bid,
        )
        if ad_group_result.get("error"):
            return {"error": True, "step": "ad_group", "detail": ad_group_result}
        ad_group_id = ad_group_result["id"]

        # 3. Responsive Search Ad
        ad_result = self.create_responsive_search_ad(
            ad_group_id=ad_group_id,
            headlines=headlines,
            descriptions=descriptions,
            final_url=final_url,
            status=status,
        )
        if ad_result.get("error"):
            return {"error": True, "step": "rsa", "detail": ad_result}

        # 4. Keywords
        kw_result = self.add_keywords(
            ad_group_id=ad_group_id,
            keywords=keywords,
            match_type=match_type,
        )
        if kw_result.get("error"):
            return {"error": True, "step": "keywords", "detail": kw_result}

        # 5. Negative keywords (optional)
        neg_result: Optional[dict] = None
        if negative_keywords:
            neg_result = self.add_negative_keywords(
                campaign_id=campaign_id,
                keywords=negative_keywords,
            )

        log.info(
            "=== Full campaign '%s' created (ID: %s) ===", name, campaign_id
        )
        return {
            "campaign": campaign_result,
            "ad_group": ad_group_result,
            "ad": ad_result,
            "keywords": kw_result,
            "negative_keywords": neg_result,
        }


# ---------------------------------------------------------------------------
# Standalone diagnostic
# ---------------------------------------------------------------------------


def _run_diagnostics() -> None:
    """
    Quick health check — verify credentials, connect to Google Ads,
    and list all campaigns if connected.
    """
    print()
    print("=" * 60)
    print("  SunBiz Google Ads Engine — Diagnostics")
    print("=" * 60)

    # Check .env.agents
    try:
        creds = _load_env_agents()
        print("  [OK]  .env.agents found")
    except FileNotFoundError as exc:
        print(f"  [FAIL] {exc}")
        print("=" * 60)
        return

    # Check SDK
    if not _SDK_AVAILABLE:
        print(f"  [FAIL] google-ads SDK not installed: {_SDK_IMPORT_ERROR}")
        print("         Fix: pip install google-ads")
        print("=" * 60)
        return
    print("  [OK]  google-ads SDK available")

    # Check credentials
    required_keys = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    ]
    all_creds_ok = True
    for key in required_keys:
        val = creds.get(key, "")
        if _is_placeholder(val):
            print(f"  [MISS] {key} — not configured in .env.agents")
            all_creds_ok = False
        else:
            # Show only partial value for security
            preview = val[:6] + "..." if len(val) > 6 else val
            print(f"  [OK]  {key} = {preview}")

    if not all_creds_ok:
        print()
        print("  Google Ads credentials incomplete — fill in .env.agents to connect.")
        print("=" * 60)
        return

    # Attempt connection
    print()
    print("  Connecting to Google Ads API ...")
    engine = GoogleAdsEngine()

    if not engine._ready:
        print("  [FAIL] Engine failed to initialise — check credentials above.")
        print("=" * 60)
        return

    print(f"  [OK]  Connected — Customer ID: {engine.customer_id}")
    print()

    # List campaigns
    campaigns = engine.get_all_campaigns()
    if isinstance(campaigns, dict) and campaigns.get("error"):
        print(f"  [FAIL] Could not retrieve campaigns: {campaigns}")
    else:
        print(f"  {len(campaigns)} campaign(s) found:")  # type: ignore[arg-type]
        for c in campaigns:  # type: ignore[union-attr]
            print(
                f"    [{c['status']:<8}] {c['name']}"
                f"  (ID: {c['id']}  Budget: ${c['budget_usd']:.2f}/day"
                f"  Bidding: {c['bidding_strategy']})"
            )

    print("=" * 60)
    print()


if __name__ == "__main__":
    _run_diagnostics()
