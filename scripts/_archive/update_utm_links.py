"""
Update Meta Ads with UTM-Tagged URLs
=====================================
Since Meta ad creatives are immutable, this script:
1. Gets all campaigns and matches them to UTM slugs
2. For each campaign → ad sets → ads, reads the current creative
3. Creates a NEW creative with the UTM-tagged JotForm URL
4. Updates the ad to point to the new creative

UTM format:
  https://form.jotform.com/253155026259254?utm_source=meta&utm_medium=paid&utm_campaign=SLUG&utm_content=AD_ID

Campaign slug mapping:
  Growth Capital    → growth_capital
  Consolidation     → consolidation
  Fast Funding      → fast_funding
  Industry Targeted → industry_targeted
  Social Proof      → social_proof
"""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.meta_ads_engine import MetaAdsEngine

_JOTFORM_FORM_ID = os.environ.get("JOTFORM_FORM_ID", "253155026259254")
JOTFORM_BASE = f"https://form.jotform.com/{_JOTFORM_FORM_ID}"

CAMPAIGN_SLUGS: dict[str, str] = {
    "growth capital":     "growth_capital",
    "consolidation":      "consolidation",
    "fast funding":       "fast_funding",
    "industry targeted":  "industry_targeted",
    "social proof":       "social_proof",
}


def match_slug(campaign_name: str) -> str | None:
    name_lower = campaign_name.lower()
    for keyword, slug in CAMPAIGN_SLUGS.items():
        if keyword in name_lower:
            return slug
    return None


def build_utm_url(slug: str, ad_id: str) -> str:
    return (
        f"{JOTFORM_BASE}"
        f"?utm_source=meta"
        f"&utm_medium=paid"
        f"&utm_campaign={slug}"
        f"&utm_content={ad_id}"
    )


def main() -> None:
    engine = MetaAdsEngine()
    page_id = engine.page_id

    # 1. Get all campaigns
    campaigns = engine.get_all_campaigns()
    print(f"\nFound {len(campaigns)} campaign(s)\n")

    updated = 0
    skipped = 0
    errors = 0

    for campaign in campaigns:
        cname = campaign["name"]
        cid = campaign["id"]
        slug = match_slug(cname)

        if not slug:
            print(f"  SKIP  campaign '{cname}' (ID {cid}) - no slug match")
            skipped += 1
            continue

        print(f"  MATCH campaign '{cname}' -> slug '{slug}'")

        # 2. Get ad sets for this campaign
        adsets = engine.get_all_adsets(campaign_id=cid)
        if not adsets:
            print(f"         No ad sets found")
            continue

        for adset in adsets:
            asid = adset["id"]
            asname = adset["name"]

            # 3. Get ads for this ad set
            ads = engine.get_all_ads(adset_id=asid)
            if not ads:
                print(f"         No ads in ad set '{asname}'")
                continue

            for ad in ads:
                ad_id = ad["id"]
                ad_name = ad["name"]
                print(f"         Processing ad '{ad_name}' (ID {ad_id}) ...")

                # 4. Read current ad's creative details
                try:
                    ad_detail = engine._call(
                        "GET", ad_id,
                        params={"fields": "id,name,creative{id,name,object_story_spec}"},
                    )
                except Exception as exc:
                    print(f"           FAILED to read ad: {exc}")
                    errors += 1
                    continue

                creative_data = ad_detail.get("creative", {})
                creative_id = creative_data.get("id")
                if not creative_id:
                    print(f"           No creative found on ad {ad_id}")
                    errors += 1
                    continue

                # 5. Read full creative details
                try:
                    creative_detail = engine._call(
                        "GET", creative_id,
                        params={"fields": "id,name,object_story_spec,url_tags"},
                    )
                except Exception as exc:
                    print(f"           FAILED to read creative {creative_id}: {exc}")
                    errors += 1
                    continue

                old_name = creative_detail.get("name", "")
                oss = creative_detail.get("object_story_spec", {})

                # Extract link_data from the object_story_spec
                link_data = oss.get("link_data", {})
                if not link_data:
                    print(f"           No link_data in creative {creative_id} - skipping")
                    skipped += 1
                    continue

                old_link = link_data.get("link", "")
                old_message = link_data.get("message", "")
                old_headline = link_data.get("name", "")  # "name" = headline in link_data
                old_description = link_data.get("description", "")
                old_image_hash = link_data.get("image_hash", "")
                old_cta = link_data.get("call_to_action", {})
                old_cta_type = old_cta.get("type", "LEARN_MORE") if old_cta else "LEARN_MORE"

                # Build UTM-tagged URL
                utm_url = build_utm_url(slug, ad_id)

                print(f"           Old link: {old_link}")
                print(f"           New link: {utm_url}")

                # 6. Create NEW creative with UTM-tagged URL
                new_link_data: dict = {
                    "link": utm_url,
                    "message": old_message,
                    "call_to_action": {
                        "type": old_cta_type,
                        "value": {"link": utm_url},
                    },
                }
                if old_headline:
                    new_link_data["name"] = old_headline
                if old_description:
                    new_link_data["description"] = old_description
                if old_image_hash:
                    new_link_data["image_hash"] = old_image_hash

                # Copy over any attachment (multi-image carousel, etc)
                for extra_key in ("child_attachments", "caption", "picture"):
                    if extra_key in link_data:
                        new_link_data[extra_key] = link_data[extra_key]

                new_oss = {
                    "page_id": oss.get("page_id", page_id),
                    "link_data": new_link_data,
                }

                new_creative_name = f"{old_name} [UTM]" if old_name else f"Ad {ad_id} Creative [UTM]"

                try:
                    new_creative = engine._call(
                        "POST",
                        f"{engine.ad_account_id}/adcreatives",
                        payload={
                            "name": new_creative_name,
                            "object_story_spec": json.dumps(new_oss),
                        },
                    )
                    new_creative_id = new_creative.get("id")
                    print(f"           Created new creative: {new_creative_id}")
                except Exception as exc:
                    print(f"           FAILED to create new creative: {exc}")
                    errors += 1
                    continue

                # 7. Update the ad to use the new creative
                try:
                    update_result = engine._call(
                        "POST",
                        ad_id,
                        payload={"creative": json.dumps({"creative_id": new_creative_id})},
                    )
                    if update_result.get("success"):
                        print(f"           Ad {ad_id} updated to use new creative")
                        updated += 1
                    else:
                        print(f"           Ad update response: {update_result}")
                        updated += 1
                except Exception as exc:
                    print(f"           FAILED to update ad: {exc}")
                    errors += 1
                    continue

    # Summary
    print(f"\n{'='*55}")
    print(f"  UTM Creative Update Summary")
    print(f"  Ads updated with UTM creatives:  {updated}")
    print(f"  Skipped:                         {skipped}")
    print(f"  Errors:                          {errors}")
    print(f"{'='*55}")

    # 8. Verify - read back ads and check their creative links
    if updated > 0:
        print(f"\nVerification - checking updated ad creatives ...\n")
        for campaign in campaigns:
            slug = match_slug(campaign["name"])
            if not slug:
                continue

            adsets = engine.get_all_adsets(campaign_id=campaign["id"])
            for adset in adsets:
                ads = engine.get_all_ads(adset_id=adset["id"])
                for ad in ads:
                    try:
                        detail = engine._call(
                            "GET", ad["id"],
                            params={"fields": "id,name,creative{id,name,object_story_spec}"},
                        )
                        cr = detail.get("creative", {})
                        oss = cr.get("object_story_spec", {})
                        link = oss.get("link_data", {}).get("link", "(none)")
                        print(f"  {ad['name']}: {link}")
                    except Exception as exc:
                        print(f"  {ad['name']}: verification failed - {exc}")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
