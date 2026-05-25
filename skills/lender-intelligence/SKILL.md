---
name: lender-intelligence
description: Uses historical lender feedback data to recommend the best lenders for a specific deal profile and surfaces typical terms and decline patterns.
triggers:
  - "which lender for this profile"
  - "who approves this kind of deal"
  - "best lender for"
  - "lender recommendation"
  - "who's good for B-paper"
  - "who likes restaurants"
  - "lender history"
  - "who declined last time"
tier: stable
disable_model_invocation: false
argument_hint: "What's the deal profile? (industry, monthly revenue, FICO, position count, NSF count)"
requires:
  - env:SUNBIZ_SUPABASE_URL
  - env:SUNBIZ_SUPABASE_ANON_KEY
---

# Lender Intelligence

> **Where these endpoints live:** All `/api/...` URLs below are routes on
> the OASIS Command Center dashboard (repo: `CC90210/oasis-command-center`,
> deployed at https://agent-dashboard-sigma-eight.vercel.app). They are NOT
> served by this repo's local `scripts/api_server.py` (which only exposes
> `/health`, `/status`, `/sms/send`, `/webhook/jotform`). Solara's bridge
> makes authenticated `fetch` calls into the dashboard's API surface, and
> the dashboard then writes to Supabase / queues threads / dispatches the
> 8 daemons in this repo.

## Purpose

Match a deal profile against historical lender behavior. The `lender_feedback` table accumulates every outcome (approved, declined, countered) across every deal. This skill mines that history to surface which funders are likely to approve, at what terms, and why others have declined.

## How-To-Run

### Step 1 — Collect the deal profile

From the underwriting output or by asking Ezra, gather:
- Industry / SIC code
- Monthly revenue (average, last 3 months)
- FICO range (approximate)
- Position count (number of existing MCAs)
- NSF count (last 90 days)
- Paper grade (A / B / C / D)
- Requested advance amount

### Step 2 — Query lender_feedback

```
GET /api/lender-intelligence/match
{
  "industry": "restaurant",
  "monthly_revenue_min": 30000,
  "monthly_revenue_max": 50000,
  "position_count_max": 2,
  "nsf_count_max": 4,
  "paper_grade": "B"
}
```

Response:
```json
{
  "lenders": [
    {
      "lender_id": "uuid",
      "lender_name": "Funder A",
      "approval_rate": 0.73,
      "avg_factor_rate": 1.36,
      "avg_advance_offered": 42000,
      "typical_term_days": 130,
      "decline_reasons": ["nsf_count > 5", "leverage_pct > 40"],
      "notes": "Prefers restaurants with POS data. Strong on B-paper."
    },
    ...
  ],
  "decline_patterns": [
    { "lender_name": "Funder C", "decline_reason": "industry_restriction", "detail": "Paused on restaurants Q2 2026" }
  ]
}
```

### Step 3 — Synthesize and surface

Present as a ranked recommendation:

```
Lender Intelligence — [Deal Profile Summary]

TOP MATCHES

1. Funder A — Approval rate: 73% | Avg offer: $42K | Factor: 1.36x | Term: ~130 days
   Why: Strong on B-paper restaurants. Tolerates up to 4 NSFs.
   Watch out: If leverage >40%, they typically counter lower.

2. Funder B — Approval rate: 61% | Avg offer: $38K | Factor: 1.42x | Term: ~115 days
   Why: Fast (24h decisions). Accepts 2 positions comfortably.

LIKELY DECLINES
- Funder C: Industry pause on restaurants since Q2 2026. Skip.
- Funder D: NSF tolerance is 0-2. At 3 NSFs, auto-decline likely.

NOTES
- None of the matched lenders require a personal guarantee waiver for this profile.
- Best case terms: Funder A if revenue verifies at $38K+/mo.
```

### Step 4 — Feed into shop-out

The lender IDs from this query feed directly into `skills/shop-out-routing/SKILL.md` Step 3 — use this as the intelligence layer that filters the automated match scores.

When both systems (shop-out API score + lender_feedback history) agree on a lender, prioritize it. When they disagree, surface the disagreement to Ezra.

## Maintaining Lender Intelligence

After every submission and outcome, log the result:
```
POST /api/lender-feedback
{
  "lender_id": "[id]",
  "application_id": "[id]",
  "outcome": "approved | declined | countered | no_response",
  "offered_amount": 40000,
  "factor_rate": 1.38,
  "decline_reason": "nsf_count",
  "notes": "[optional context]"
}
```

The lender_intelligence endpoint learns from every entry. Quality of recommendations improves with volume.

## Guardrails

- Never cite approval rates from fewer than 5 historical data points — mark as `insufficient_data` and weight accordingly.
- Lender programs change. Always check `lender_feedback.last_updated` — if > 60 days, the pattern may be stale. Flag it.
- Never share lender-specific decline rates or internal terms with merchants — that's proprietary business data.

## Related Skills

- [[skills/shop-out-routing/SKILL.md]] — consumes lender recommendations
- [[skills/underwriting-flow/SKILL.md]] — provides the deal profile
- [[skills/renewal-window-detection/SKILL.md]] — lender intelligence helps assess renewal lender preferences
- [[skills/funding-vocabulary/SKILL.md]] — terminology for lender conversations
