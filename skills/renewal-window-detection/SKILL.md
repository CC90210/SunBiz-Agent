---
name: renewal-window-detection
description: Identifies funded deals that have crossed the renewal eligibility threshold (default 40% paid back) and drafts targeted renewal outreach for each.
triggers:
  - "who's up for renewal"
  - "what's at 40%"
  - "renewal window"
  - "renewal opportunities"
  - "who can we renew"
  - "check renewals"
  - "renewal list"
tier: stable
disable_model_invocation: false
requires:
  - env:SUNBIZ_SUPABASE_URL
  - env:SUNBIZ_SUPABASE_ANON_KEY
---

# Renewal Window Detection

## Purpose

Funded deals become renewable once a merchant has paid back enough of the advance. Proactive renewal outreach is the highest-margin activity in the funding business — no new underwriting cost, existing relationship. Never let a renewal window expire uncontested.

## Renewal Eligibility Threshold

Default: **40% of the advance paid back**.

This is configurable per-deal via `renewal_eligibility_threshold` on the `funded_deals` table. If a lender requires 50%, that overrides the default.

## How-To-Run

### Step 1 — Query funded deals

```
GET /api/funded-deals?status=active
```

The response includes `advance_amount`, `total_payback`, `amount_paid_to_date`, `factor_rate`, `lender_id`, `lender_contact`, `funded_at`, `last_contact_date`.

### Step 2 — Compute renewal eligibility

For each deal:
```
progress_pct = amount_paid_to_date / total_payback
eligible = progress_pct >= renewal_eligibility_threshold (default 0.40)
```

Also compute:
```
payback_remaining = total_payback - amount_paid_to_date
days_since_funded = today - funded_at
days_since_last_contact = today - last_contact_date
```

### Step 3 — Rank eligible deals

Sort by priority:
1. `progress_pct` highest first (closest to full payback = most urgent — they may go elsewhere)
2. `days_since_last_contact` descending (longest without contact = most likely to have drifted)

### Step 4 — Surface the renewal report

```
Renewal Window Report — [Date]

ELIGIBLE FOR RENEWAL (4 deals)

1. [Merchant Name]
   Advance: $60,000 | Paid back: $28,400 (47%) | Remaining: $31,600
   Lender: Funder A | Contact: [name] | Last contacted: 22 days ago
   Suggested renewal: $50,000–$70,000 depending on current revenue
   Action: Call merchant this week — at 47% they're in the sweet spot.

2. [Merchant Name]
   Advance: $25,000 | Paid back: $11,800 (47%) | Remaining: $13,200
   Lender: Funder B | Contact: [name] | Last contacted: 8 days ago
   ...

APPROACHING WINDOW (2 deals — not yet eligible but worth monitoring)
- [Merchant Name]: 34% paid — eligible in ~3 weeks at current pace
- [Merchant Name]: 29% paid — eligible in ~5 weeks
```

### Step 5 — Draft renewal outreach

For each eligible deal, draft a personal outreach (not a blast):

```
Subject: How things going, [First Name]?

Hey [First Name],

Just checking in — wanted to see how business has been since we got you funded in [Month].

If you're looking for additional working capital or want to discuss refinancing into
a lower-rate product now that you've got a track record with the lender, I'd love
to connect for 10 minutes this week.

Any time work for you?

[Ezra's name]
SunBiz Funding
```

Customize based on:
- How long ago they were funded (feel free to reference it)
- Their industry (if it's seasonal, tie to the season)
- Whether they've had contact recently (if yes, reference it; if no, keep it warm/casual)

### Step 6 — Queue or surface for Ezra

If Ezra says "send it" — route through `skills/casl-compliance/SKILL.md` first, then `skills/email-outbound/SKILL.md`.

If Ezra wants to call instead — add to today's call sheet via `skills/daily-call-sheet-workflow/SKILL.md`.

## Guardrails

- Never send a renewal email to a merchant who is delinquent or has filed a complaint — check `funded_deals.flags` first.
- If `last_contact_date` is < 7 days ago, flag it — Ezra may have already initiated renewal outreach manually.
- Renewal outreach is personal, not a blast. Route through `skills/email-outbound` with personalization, not `skills/cold-outreach-blast`.

## Related Skills

- [[skills/casl-compliance/SKILL.md]] — compliance check before any outreach
- [[skills/lender-intelligence/SKILL.md]] — check if the current lender has renewal terms or prefers full payback first
- [[skills/daily-call-sheet-workflow/SKILL.md]] — add renewal calls to today's sheet
- [[skills/follow-up-discipline/SKILL.md]] — general follow-up queue
