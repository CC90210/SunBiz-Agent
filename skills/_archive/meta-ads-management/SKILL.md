# SKILL: Meta Ads Management

> Complete Meta Marketing API operations for SunBiz Funding — Facebook & Instagram MCA ad lifecycle.

---

## Overview
This skill covers all Meta Marketing API operations using the `facebook-business` Python SDK (v22.0) or Meta Ads MCP server for SunBiz Funding's MCA consolidation and growth capital campaigns.

## Prerequisites
- Meta Business App with `ads_management` + `ads_read` permissions (approved via App Review)
- System User access token (non-expiring, from Business Manager)
- Ad Account ID (format: `act_XXXXXXXXX`)
- Facebook Page connected to ad account
- `facebook-business` Python package installed

## CRITICAL: MCA Compliance
```python
# EVERY MCA campaign MUST include:
special_ad_categories = ['CREDIT']

# Targeting restrictions for CREDIT:
# CANNOT use: age, gender, zip code, multicultural affinity, lookalike audiences
# MINIMUM radius: 15 miles for location targeting
# MUST comply: ECOA, FTC, TCPA, state-specific disclosure laws
# NEVER use: "loan," "lender," "lending," "borrower," "interest rate"
```

## Campaign Structure
```
Campaign (objective + special_ad_categories: ['CREDIT'])
  └─ Ad Set (CREDIT-compliant targeting + budget + schedule + placements)
       └─ Ad (creative + CTA → JotForm)
            └─ AdCreative (image/video + MCA-compliant text + headline)
```

## Campaign Objectives (2026)
| Objective | Use For | Optimization |
|-----------|---------|-------------|
| OUTCOME_LEADS | Lead generation (PRIMARY for MCA) | JotForm submissions |
| OUTCOME_TRAFFIC | Drive JotForm visits | Landing page views |
| OUTCOME_AWARENESS | Brand awareness | Reach, impressions |
| OUTCOME_ENGAGEMENT | Post engagement | Likes, comments, shares |

## Campaign Creation Flow
```python
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.adimage import AdImage

# 1. Initialize API
FacebookAdsApi.init(app_id, app_secret, access_token)
account = AdAccount('act_XXXXXXXXX')

# 2. Create Campaign
campaign = account.create_campaign(params={
    'name': 'SunBiz - MCA Consolidation - Q1 2026',
    'objective': 'OUTCOME_LEADS',
    'status': 'PAUSED',
    'special_ad_categories': ['CREDIT'],  # MANDATORY
})

# 3. Upload Image
image = AdImage(parent_id='act_XXXXXXXXX')
image[AdImage.Field.filename] = '/path/to/consolidation_ad.jpg'
image.remote_create()
image_hash = image[AdImage.Field.hash]

# 4. Create Ad Creative (MCA-Compliant)
creative = account.create_ad_creative(params={
    'name': 'SunBiz - Consolidation Before/After v1',
    'object_story_spec': {
        'page_id': 'PAGE_ID',
        'link_data': {
            'image_hash': image_hash,
            'link': 'JOTFORM_URL?utm_source=meta&utm_medium=paid&utm_campaign=consolidation_q1',
            'message': 'Overleveraged? We build a multi-phase path to financial health. See if you qualify for our consolidation strategy.',
            'name': 'Cut Your Daily MCA Payments',  # headline
            'description': 'From multiple funders to one. Subject to underwriting approval.',
            'call_to_action': {'type': 'LEARN_MORE'},
        }
    }
})

# 5. Create Ad Set (CREDIT-compliant targeting)
ad_set = campaign.create_ad_set(params={
    'name': 'National - Broad - Consolidation',
    'daily_budget': 5000,  # $50.00 in cents
    'billing_event': 'IMPRESSIONS',
    'optimization_goal': 'LEAD_GENERATION',
    'targeting': {
        'geo_locations': {'countries': ['US']},
        # NO age, gender, zip targeting for CREDIT category
    },
    'status': 'PAUSED',
})

# 6. Create Ad
ad = ad_set.create_ad(params={
    'name': 'SunBiz - Consolidation Ad v1',
    'creative': {'creative_id': creative['id']},
    'status': 'PAUSED',
})
```

## Conversions API (CAPI) Setup
```python
# Server-side tracking alongside browser pixel
# Run BOTH browser pixel AND CAPI with matching Event IDs for deduplication
# This ensures tracking works despite iOS privacy + cookie deprecation

# Custom conversions: use "Other" event category
# This avoids Special Ad Category algorithmic demographic bias
# while maintaining conversion optimization
```

## Insights API Patterns
```python
# Campaign insights with CPQL-relevant metrics
insights = Campaign(campaign_id).get_insights(
    fields=[
        'impressions', 'clicks', 'ctr', 'cpc',
        'spend', 'conversions', 'cost_per_action_type',
        'actions', 'reach', 'frequency'
    ],
    params={
        'date_preset': 'last_7d',
        'breakdowns': ['placement', 'device_platform'],
        # Note: age/gender breakdowns not available for CREDIT category
    }
)
```

## Ad Formats for MCA
| Format | Best For | Specs |
|--------|---------|-------|
| Single Image | Before/after consolidation, payment comparison | 1080x1080 or 1200x628 |
| Video (<30 sec) | UGC-style testimonials, multi-phase explainer | 1080x1080 (feed), 1080x1920 (stories) |
| Carousel | Multi-phase roadmap (Phase 1→2→3→4) | 2-10 cards, 1080x1080 each |
| Lead Form | In-platform lead capture (backup to JotForm) | Higher Intent form type |

## Andromeda-Optimized Creative Strategy
- Upload 10-15 conceptually distinct creatives per campaign
- Mix formats: static images, carousel, video
- Distinct angles: before/after, roadmap, payment table, testimonial, educational
- Avoid "fake diversity" (Andromeda treats slight variations as identical)
- Use Advantage+ Creative for auto-generated variations

## Rate Limits
- GET requests: 1 point each
- POST requests: 3 points each
- Standard tier: ~100,000 points/hour + 40 points per active ad
- On 429 error: Wait 60 seconds, implement exponential backoff

## Optimization Checklist
- [ ] Monitor Learning Phase (need ~50 conversions/week per ad set)
- [ ] Test creative variants (10-15 distinct concepts per campaign)
- [ ] Review placement performance (Feed vs. Stories vs. Reels)
- [ ] Check frequency (<5 target; >5 = refresh creative)
- [ ] Track CPQL alongside CPL (qualify rate matters more than volume)
- [ ] Review lead score distribution (>30% COLD = targeting problem)
- [ ] Adjust budget based on pacing and CPQL trends
- [ ] Creative refresh every 2-3 weeks
- [ ] ALL CTAs verified linking to JotForm with correct UTM parameters
