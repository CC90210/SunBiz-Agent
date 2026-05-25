# SKILL: Google Ads Management

> Complete Google Ads API operations for SunBiz Funding — MCA campaign lifecycle from creation to optimization.

---

## Overview
This skill covers all Google Ads API operations using the `google-ads` Python SDK (v29.2.0, API v23.1) or Google Ads MCP server for SunBiz Funding's MCA consolidation and growth capital search campaigns.

## Prerequisites
- Developer token (Test/Basic/Standard access)
- OAuth2 credentials (client_id, client_secret, refresh_token)
- Customer ID (Google Ads account ID)
- `google-ads` Python package installed
- Configuration in `google-ads.yaml` or `.env.agents`
- Google Financial Services certification (required for MCA ads)

## Campaign Types for MCA
| Type | Best For | Ad Formats |
|------|----------|------------|
| Search | High-intent MCA consolidation queries | Responsive Search Ads |
| Display | Retargeting JotForm visitors | Responsive Display Ads, Image Ads |
| Performance Max | Full automation across Google properties | All formats, Google decides placement |

## Campaign Creation Flow
```
1. Create CampaignBudget (daily amount in micros)
   └─ amount_micros = dollars x 1,000,000

2. Create Campaign
   ├─ name: "SunBiz - MCA Consolidation - Search"
   ├─ type, status (PAUSED)
   ├─ budget → link to CampaignBudget
   ├─ bidding_strategy (MAXIMIZE_CONVERSIONS for MCA)
   └─ network_settings (search network)

3. Create AdGroup(s)
   ├─ "High Intent - Consolidation" (exact + phrase match)
   ├─ "Medium Intent - Alternatives" (broad + phrase match)
   └─ "Educational" (broad match, lower bids)

4. Add Keywords (MCA-specific)
   ├─ "MCA consolidation" [EXACT]
   ├─ "merchant cash advance consolidation" [PHRASE]
   ├─ "consolidate MCA positions" [EXACT]
   ├─ "MCA buyout" [EXACT]
   └─ Negative: "jobs", "certification", "personal loan", "payday"

5. Create Responsive Search Ads (MCA-compliant copy)
   ├─ headlines[] (15, max 30 chars each — NO "loan" language)
   ├─ descriptions[] (4, max 90 chars each)
   └─ final_urls[] → JotForm with UTM parameters

6. Add Extensions
   ├─ Sitelinks: "Free Analysis", "How It Works", "Case Studies"
   ├─ Callouts: "No Equity Required", "24-Hour Decisions", "MCA Experts"
   └─ Structured Snippets: "Services: Consolidation, Buyout, Growth Capital"

7. Enable Campaign (set status → ACTIVE)
```

## MCA RSA Templates
```
Headlines (max 30 chars each):
"Consolidate Your MCA Today"        | "Cut Daily Payments in Half"
"From 4 Positions to 1"             | "Stop the Daily Drain"
"See If You Qualify Now"            | "Free Cash Flow Analysis"
"MCA Consolidation Experts"         | "Reduce Your Daily Burden"
"One Payment. One Funder."          | "Smart Capital Solutions"
"SunBiz Funding"                    | "Fast Business Funding"
"No Equity Required"                | "Revenue-Based Financing"
"Get Your Free Analysis"

Descriptions (max 90 chars each):
"Overleveraged? We consolidate your MCA positions into one manageable payment."
"See if you qualify for our multi-phase consolidation strategy. Free analysis."
"Cut your daily MCA payments. We buy out your existing positions. Apply today."
"Fast business funding with no equity required. Funded in as little as 24 hours."
```

## Key GAQL Queries

### Campaign Performance
```sql
SELECT campaign.name, campaign.status,
       metrics.impressions, metrics.clicks, metrics.ctr,
       metrics.average_cpc, metrics.conversions,
       metrics.cost_micros, metrics.cost_per_conversion
FROM campaign
WHERE segments.date DURING LAST_7_DAYS
  AND campaign.status != 'REMOVED'
ORDER BY metrics.cost_micros DESC
```

### MCA Keyword Performance
```sql
SELECT ad_group_criterion.keyword.text,
       ad_group_criterion.keyword.match_type,
       metrics.impressions, metrics.clicks, metrics.ctr,
       metrics.average_cpc, metrics.conversions,
       metrics.cost_per_conversion,
       ad_group_criterion.quality_info.quality_score
FROM keyword_view
WHERE segments.date DURING LAST_30_DAYS
ORDER BY metrics.cost_micros DESC
LIMIT 50
```

### Search Terms (What Merchants Actually Search)
```sql
SELECT search_term_view.search_term,
       metrics.impressions, metrics.clicks,
       metrics.conversions, metrics.cost_micros
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.impressions > 10
ORDER BY metrics.impressions DESC
```

## MCA Keywords
```
High intent: "MCA consolidation", "consolidate MCA positions", "MCA buyout",
             "reverse consolidation", "MCA debt relief"
Medium intent: "MCA alternatives", "reduce daily MCA payments", "business funding options",
               "revenue based financing"
Educational: "what is MCA consolidation", "leverage ratio calculator",
             "merchant cash advance explained"
Negative: "jobs", "certification", "course", "broker jobs", "personal loan",
          "student loan", "payday", "mortgage", "MCA medical", "MCA artery"
```

## Bidding Strategies for MCA
| Strategy | When to Use | Notes |
|----------|------------|-------|
| Maximize Conversions | Starting out, need data | Let Google optimize for JotForm submissions |
| Target CPA | Know your target CPQL | Set target to 80% of current CPL |
| Maximize Clicks | Building data, low budget | Get traffic to learn |
| Manual CPC | Full control needed | Labor-intensive but precise |

## Optimization Checklist
- [ ] Review search terms weekly — add negatives for irrelevant queries
- [ ] Verify NO "loan" language appears in any ads or extensions
- [ ] Check Quality Score — improve ad relevance for MCA terms
- [ ] Adjust bids by device (mobile vs. desktop conversion rates)
- [ ] Adjust bids by time of day (peak: 9AM-11AM, 1PM-4PM EST)
- [ ] Test new ad copy every 2 weeks
- [ ] Review budget pacing daily
- [ ] Pause keywords with high spend and zero conversions
- [ ] ALL final URLs verified pointing to JotForm with UTM parameters
- [ ] MCA disclaimers in ad extensions
