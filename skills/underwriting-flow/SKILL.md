---
name: underwriting-flow
description: Trigger and interpret underwriting on an application — parse bank statements, read risk flags, produce a readiness score, and recommend the next action.
triggers:
  - "run underwriting"
  - "parse these statements"
  - "what's the readiness on this deal"
  - "underwrite this"
  - "run the UW"
  - "pull the underwriting"
  - "what does underwriting say"
tier: stable
disable_model_invocation: false
argument_hint: "Which application ID should I run underwriting on?"
requires:
  - env:SUNBIZ_SUPABASE_URL
  - env:SUNBIZ_SUPABASE_ANON_KEY
---

# Underwriting Flow

## Purpose

Run or retrieve underwriting on a specific application. Interpret the structured output into a plain-English recommendation for Ezra.

## How-To-Run

### Step 1 — Trigger underwriting

If bank statements have been uploaded and the application is in `pending_uw` or `ready_for_uw` status:

```
POST /api/applications/[id]/underwriting/run
```

This kicks off the underwriting agent. Response includes a `job_id` and estimated completion time (typically 60–120 seconds).

**If underwriting was already run:** skip to Step 2 — don't re-trigger unless Ezra asks for a re-run.

### Step 2 — Poll for results

```
GET /api/applications/[id]/underwriting/latest
```

Response shape:
```json
{
  "readiness_score": 72,
  "paper_grade": "B",
  "revenue_monthly_avg": 38500,
  "nsf_count": 3,
  "position_count": 2,
  "leverage_pct": 31,
  "risk_flags": [
    { "level": "warning", "code": "nsf_elevated", "detail": "3 NSFs in 90 days" },
    { "level": "info", "code": "multi_position", "detail": "2 existing positions" }
  ],
  "recommended_advance": 45000,
  "recommended_factor_rate": 1.38,
  "recommended_term_days": 120,
  "notes": "B-paper candidate. Good revenue, manageable leverage. NSFs are the primary risk."
}
```

### Step 3 — Interpret and surface

Translate the JSON into a plain-English summary:

```
Underwriting Summary — [Applicant Name]

READINESS SCORE: 72/100 — B-Paper

Revenue: $38,500/mo avg (sufficient)
Existing positions: 2 (moderate)
Leverage: 31% (within B-paper threshold)
NSFs: 3 in 90 days (elevated — flagged)

RECOMMENDED OFFER
Advance: $45,000
Factor rate: 1.38x
Term: 120 days (daily payment: ~$519)

RISK FLAGS
- NSFs (warning): 3 in 90 days. Some lenders auto-decline at 5+.
- Multi-position (info): 2 existing. Include in shop-out notes.

RECOMMENDATION: Ready to shop. Lead with B-paper funders.
Restrict to lenders with NSF tolerance ≥ 3.
```

### Step 4 — Next-action routing

| Readiness Score | Recommendation |
|-----------------|---------------|
| 80–100 | Shop immediately — A-paper, wide lender pool |
| 60–79 | Shop with caveats — B-paper, filter lender set |
| 40–59 | Conditional — address risk flags before shopping |
| < 40 | Do not shop — escalate to Ezra for restructure plan |

For scores below 60, surface the specific flags and ask Ezra whether to proceed, defer, or seek additional docs.

### Step 5 — Update application status

After review, update status appropriately:
- Score 60+: `status = ready_to_shop`
- Score < 60: `status = needs_review`, add note with flag summary

## Guardrails

- Never interpret underwriting without reading ALL `risk_flags` — a 72 score with a `high_risk` flag is not the same as a clean 72.
- If `paper_grade` is D, escalate to `skills/operator-handoff/SKILL.md` before taking any action.
- Do not share raw JSON with Ezra — always translate to the plain-English summary format.

## Related Skills

- [[skills/shop-out-routing/SKILL.md]] — what happens after underwriting passes
- [[skills/lender-intelligence/SKILL.md]] — cross-reference risk flags with lender tolerance data
- [[skills/operator-handoff/SKILL.md]] — D-paper and ambiguous situations
- [[skills/funding-vocabulary/SKILL.md]] — terminology reference when explaining flags to Ezra
