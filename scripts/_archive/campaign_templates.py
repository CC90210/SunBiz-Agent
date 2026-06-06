"""
SunBiz Funding — Campaign Templates
=====================================
Pre-built, MCA-compliant Meta Ads campaign templates for SunBiz Funding.
Import this module to launch full campaigns in one function call.

All templates:
  - Link to JotForm: https://form.jotform.com/253155026259254
  - Target US, ages 18-65, Facebook feed (compliant with FINANCIAL_PRODUCTS_SERVICES)
  - Never use "loan", "MCA", or "merchant cash advance"
  - Default to PAUSED status so you review before activating

Usage:
    from scripts.meta_ads_engine import MetaAdsEngine
    from scripts.campaign_templates import growth_capital_template, launch_from_template

    engine = MetaAdsEngine()
    template = growth_capital_template()
    result = launch_from_template(engine, template)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("campaign_templates")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOTFORM_FORM_ID = os.environ.get("JOTFORM_FORM_ID", "253155026259254")
JOTFORM_URL = f"https://form.jotform.com/{_JOTFORM_FORM_ID}"

# Default US-only targeting (required for FINANCIAL_PRODUCTS_SERVICES category)
# No age/gender/zip restrictions — broad targeting only
_US_BROAD_TARGETING: dict = {
    "geo_locations": {"countries": ["US"]},
    "publisher_platforms": ["facebook"],
    "facebook_positions": ["feed"],
}

# ---------------------------------------------------------------------------
# Template dataclass
# ---------------------------------------------------------------------------


@dataclass
class CampaignTemplate:
    """
    Complete specification for a SunBiz Meta Ads campaign.
    All fields that map to API calls are explicit — no magic.
    """

    # Campaign-level
    name: str
    objective: str = "OUTCOME_LEADS"
    special_ad_categories: list[str] = field(
        default_factory=lambda: ["FINANCIAL_PRODUCTS_SERVICES"]
    )

    # Ad set-level
    budget: int = 100                 # USD (lifetime by default)
    budget_type: str = "lifetime"     # "lifetime" or "daily"
    duration_days: int = 10
    targeting: dict = field(default_factory=lambda: dict(_US_BROAD_TARGETING))
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"

    # Creative-level
    ad_copy_message: str = ""
    ad_copy_headline: str = ""
    ad_copy_description: str = ""
    cta_type: str = "LEARN_MORE"
    link: str = JOTFORM_URL
    image_hash: str = ""              # Leave empty to launch without image

    # Ad-level
    initial_status: str = "PAUSED"   # PAUSED = review before going live


# ---------------------------------------------------------------------------
# Pre-built templates
# ---------------------------------------------------------------------------


def growth_capital_template(image_hash: str = "") -> CampaignTemplate:
    """Working capital / growth funding campaign."""
    return CampaignTemplate(
        name="SunBiz — Growth Capital",
        objective="OUTCOME_LEADS",
        budget=100,
        duration_days=10,
        targeting=dict(_US_BROAD_TARGETING),
        ad_copy_message=(
            "Your business deserves the capital to grow.\n\n"
            "Get $5K\u2013$250K in working capital with no credit pull "
            "and weekly payments. Funded in as fast as 24 hours.\n\n"
            "See if you qualify \u2014 takes less than 3 minutes."
        ),
        ad_copy_headline="Business Funding, Simplified",
        ad_copy_description="SunBiz Funding \u2014 $5K to $250K. No Credit Pull. Fast Approval.",
        cta_type="LEARN_MORE",
        image_hash=image_hash,
    )


def consolidation_template(image_hash: str = "") -> CampaignTemplate:
    """Advance consolidation campaign — targets businesses with multiple daily payments."""
    return CampaignTemplate(
        name="SunBiz — Consolidation",
        objective="OUTCOME_LEADS",
        budget=100,
        duration_days=10,
        targeting=dict(_US_BROAD_TARGETING),
        ad_copy_message=(
            "Multiple daily payments draining your cash flow? "
            "You\u2019re not stuck.\n\n"
            "Consolidate into one simple weekly payment and keep more of what you earn. "
            "Business owners are saving thousands per month.\n\n"
            "See if you qualify today."
        ),
        ad_copy_headline="One Payment. Lower Amount. More Cash Flow.",
        ad_copy_description="SunBiz Funding \u2014 Consolidate Multiple Payments Into One.",
        cta_type="LEARN_MORE",
        image_hash=image_hash,
    )


def fast_funding_template(image_hash: str = "") -> CampaignTemplate:
    """Speed and urgency campaign — highlights 24-hour funding."""
    return CampaignTemplate(
        name="SunBiz — Fast Funding",
        objective="OUTCOME_LEADS",
        budget=100,
        duration_days=10,
        targeting=dict(_US_BROAD_TARGETING),
        ad_copy_message=(
            "When your business needs capital, every hour counts.\n\n"
            "\u2192 3 minutes to apply\n"
            "\u2192 4 hours to approve\n"
            "\u2192 24 hours to fund\n\n"
            "No credit pull. No collateral. No waiting weeks for a decision.\n\n"
            "See if you qualify now."
        ),
        ad_copy_headline="Funded in 24 Hours",
        ad_copy_description="SunBiz Funding \u2014 Fast Capital When You Need It Most.",
        cta_type="LEARN_MORE",
        image_hash=image_hash,
    )


def industry_targeted_template(
    industries: Optional[list[str]] = None,
    image_hash: str = "",
) -> CampaignTemplate:
    """
    Industry-specific campaign. Mention industries in copy without
    adding age/gender/zip targeting (compliance requirement).

    Args:
        industries: List of industry names for copy personalization.
                    Defaults to restaurants, contractors, retail.
        image_hash: Optional uploaded image hash.
    """
    industry_list = industries or ["restaurants", "contractors", "retail businesses"]
    industry_str = ", ".join(industry_list[:-1]) + f" and {industry_list[-1]}"

    return CampaignTemplate(
        name="SunBiz — Industry Targeted",
        objective="OUTCOME_LEADS",
        budget=100,
        duration_days=10,
        targeting=dict(_US_BROAD_TARGETING),
        ad_copy_message=(
            f"Business owners in {industry_str} \u2014 this is for you.\n\n"
            "Whether you need capital for equipment, inventory, staffing, "
            "or materials, we fund businesses like yours every day.\n\n"
            "$5K\u2013$250K. No credit pull. Weekly payments.\n\n"
            "See if you qualify."
        ),
        ad_copy_headline="Capital Built for Your Industry",
        ad_copy_description="SunBiz Funding \u2014 Industry-Specific Business Capital.",
        cta_type="LEARN_MORE",
        image_hash=image_hash,
    )


def social_proof_template(image_hash: str = "") -> CampaignTemplate:
    """Testimonial and social proof campaign — builds trust."""
    return CampaignTemplate(
        name="SunBiz — Social Proof",
        objective="OUTCOME_LEADS",
        budget=100,
        duration_days=10,
        targeting=dict(_US_BROAD_TARGETING),
        ad_copy_message=(
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
        ad_copy_headline="Trusted by 500+ Business Owners",
        ad_copy_description="SunBiz Funding \u2014 Join Hundreds of Funded Businesses.",
        cta_type="LEARN_MORE",
        image_hash=image_hash,
    )


def seasonal_template(season: str, image_hash: str = "") -> CampaignTemplate:
    """
    Seasonal promotion campaign.

    Args:
        season: One of "spring", "summer", "fall", "winter", "holiday", "new_year",
                or any custom string (used in copy and campaign name).
        image_hash: Optional uploaded image hash.
    """
    season_lower = season.lower().strip()

    season_hooks: dict[str, tuple[str, str]] = {
        "spring": (
            "Spring is the season to grow.",
            "Expand inventory, hire staff, or renovate before the busy season hits.",
        ),
        "summer": (
            "Summer slump? Not this year.",
            "Bridge the gap with fast working capital and keep your business moving.",
        ),
        "fall": (
            "Q4 is coming. Is your business ready?",
            "Stock up, staff up, and gear up for the biggest quarter of the year.",
        ),
        "winter": (
            "Don\u2019t let winter slow your business down.",
            "Get the capital you need to stay ahead while others pull back.",
        ),
        "holiday": (
            "The holiday rush is here. Is your business ready?",
            "Fast working capital to help you stock up, staff up, and cash in.",
        ),
        "new_year": (
            "New year. New capital. New growth.",
            "Start strong with working capital to fuel your best year yet.",
        ),
    }

    hook, body_line = season_hooks.get(
        season_lower,
        (
            f"This {season} is your moment to grow.",
            "Fast working capital to keep your business moving forward.",
        ),
    )

    return CampaignTemplate(
        name=f"SunBiz — {season.title()} Seasonal",
        objective="OUTCOME_LEADS",
        budget=100,
        duration_days=14,
        targeting=dict(_US_BROAD_TARGETING),
        ad_copy_message=(
            f"{hook}\n\n"
            f"{body_line}\n\n"
            "$5K\u2013$250K. No credit pull. Funded as fast as 24 hours.\n\n"
            "See if you qualify today."
        ),
        ad_copy_headline=hook,
        ad_copy_description="SunBiz Funding \u2014 Fast Business Capital.",
        cta_type="LEARN_MORE",
        image_hash=image_hash,
    )


def retargeting_template(image_hash: str = "") -> CampaignTemplate:
    """
    Website visitor retargeting campaign.

    Note: The custom audience (website visitors) must be created separately
    and passed as a targeting override when calling launch_from_template.
    This template sets up the copy and budget; update targeting with
    your custom audience ID after creation.
    """
    return CampaignTemplate(
        name="SunBiz — Retargeting",
        objective="OUTCOME_LEADS",
        budget=50,
        duration_days=14,
        targeting=dict(_US_BROAD_TARGETING),  # Override with custom audience externally
        ad_copy_message=(
            "You checked us out \u2014 now let\u2019s make it official.\n\n"
            "Hundreds of business owners have already qualified for $5K\u2013$250K "
            "in working capital through SunBiz Funding.\n\n"
            "No credit pull. No collateral. Funded as fast as 24 hours.\n\n"
            "See if you qualify \u2014 takes less than 3 minutes."
        ),
        ad_copy_headline="Still Thinking About It?",
        ad_copy_description="SunBiz Funding \u2014 Your Capital Is Waiting.",
        cta_type="APPLY_NOW",
        image_hash=image_hash,
    )


# ---------------------------------------------------------------------------
# Launch helpers
# ---------------------------------------------------------------------------


def _iso_now_plus_days(days: int) -> str:
    """Return ISO 8601 timestamp N days from now (UTC)."""
    dt = datetime.now(tz=timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")


def _iso_now() -> str:
    """Return ISO 8601 timestamp for now (UTC)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def launch_from_template(
    engine,  # MetaAdsEngine instance — avoid circular import with type hint
    template: CampaignTemplate,
    targeting_override: Optional[dict] = None,
) -> dict:
    """
    Create a full campaign stack from a template in a single call:
      Campaign → Ad Set → Creative → Ad

    All objects are created in PAUSED status (unless template.initial_status
    is explicitly set to ACTIVE).

    Args:
        engine: A MetaAdsEngine instance.
        template: A CampaignTemplate to launch.
        targeting_override: Optional targeting dict to use instead of template.targeting.
                            Useful for retargeting with custom audiences.

    Returns:
        dict with campaign_id, adset_id, creative_id, ad_id, template_name.
    """
    targeting = targeting_override or template.targeting
    end_time = _iso_now_plus_days(template.duration_days)
    start_time = _iso_now()

    log.info("Launching template: %s", template.name)

    # 1. Campaign
    campaign = engine.create_campaign(
        name=template.name,
        objective=template.objective,
        special_ad_categories=template.special_ad_categories,
        status=template.initial_status,
    )
    campaign_id = campaign["id"]

    # 2. Ad Set
    adset = engine.create_adset(
        campaign_id=campaign_id,
        name=f"{template.name} — Ad Set",
        budget=template.budget,
        targeting=targeting,
        bid_strategy=template.bid_strategy,
        start_time=start_time,
        end_time=end_time,
        budget_type=template.budget_type,
    )
    adset_id = adset["id"]

    # 3. Creative
    creative = engine.create_creative(
        name=f"{template.name} — Creative",
        image_hash=template.image_hash or None,
        message=template.ad_copy_message,
        headline=template.ad_copy_headline,
        description=template.ad_copy_description,
        link=template.link,
        cta_type=template.cta_type,
    )
    creative_id = creative["id"]

    # 4. Ad
    ad = engine.create_ad(
        adset_id=adset_id,
        creative_id=creative_id,
        name=f"{template.name} — Ad",
        status=template.initial_status,
    )
    ad_id = ad["id"]

    result = {
        "template_name": template.name,
        "campaign_id": campaign_id,
        "adset_id": adset_id,
        "creative_id": creative_id,
        "ad_id": ad_id,
        "status": template.initial_status,
        "budget_usd": template.budget,
        "link": template.link,
    }
    log.info(
        "Template '%s' launched — campaign: %s, adset: %s, ad: %s",
        template.name, campaign_id, adset_id, ad_id,
    )
    return result


def launch_batch(
    engine,  # MetaAdsEngine instance
    templates: list[CampaignTemplate],
) -> list[dict]:
    """
    Launch multiple campaign templates sequentially.

    Args:
        engine: A MetaAdsEngine instance.
        templates: List of CampaignTemplate objects to launch.

    Returns:
        List of result dicts from launch_from_template. Failed launches are
        included with an "error" key instead of object IDs.
    """
    results: list[dict] = []
    total = len(templates)

    for idx, template in enumerate(templates, start=1):
        log.info("[%d/%d] Launching: %s", idx, total, template.name)
        try:
            result = launch_from_template(engine, template)
            results.append(result)
        except RuntimeError as exc:
            log.error("Failed to launch '%s': %s", template.name, exc)
            results.append({"template_name": template.name, "error": str(exc)})

    successful = sum(1 for r in results if "error" not in r)
    failed = total - successful
    log.info(
        "Batch complete: %d/%d launched successfully, %d failed.",
        successful, total, failed,
    )
    return results


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    templates = [
        growth_capital_template(),
        consolidation_template(),
        fast_funding_template(),
        industry_targeted_template(),
        social_proof_template(),
        seasonal_template("spring"),
        retargeting_template(),
    ]

    print()
    print("=" * 50)
    print("  SunBiz Campaign Templates — Preview")
    print("=" * 50)
    for t in templates:
        print(f"\n  [{t.name}]")
        print(f"  Objective : {t.objective}")
        print(f"  Budget    : ${t.budget} ({t.budget_type}, {t.duration_days} days)")
        print(f"  Headline  : {t.ad_copy_headline}")
        print(f"  CTA       : {t.cta_type} -> {t.link}")
    print()
    print(f"  {len(templates)} templates ready. Import launch_from_template to deploy.")
    print("=" * 50)
    print()
