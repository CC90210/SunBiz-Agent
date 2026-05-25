---
name: shop-out-routing
description: When operator says "shop this deal," route the application to the right lenders, surface the dry-run plan with warnings, and queue the actual threads.
triggers:
  - "shop this deal"
  - "send to lenders"
  - "find lenders for this app"
  - "which lenders should we hit"
  - "shop out"
  - "shop [applicant name]"
tier: stable
disable_model_invocation: false
argument_hint: "Which application ID (or applicant name) should I shop out?"
requires:
  - env:SUNBIZ_SUPABASE_URL
  - env:SUNBIZ_SUPABASE_ANON_KEY
---

# Shop-Out Routing

## Purpose

Route a specific application to the optimal lender set. Never blast indiscriminately — always dry-run first, surface the plan to Ezra, then execute on explicit approval.

## How-To-Run

### Step 1 — Identify the application

If Ezra says a name (e.g., "shop out Jordan's deal"), resolve it to an application ID:
```
GET /api/applications?name=Jordan&status=pending_shop
```
Confirm the correct row before proceeding.

### Step 2 — Dry-run the shop-out

```
POST /api/applications/[id]/shop-out
{ "dry_run": true }
```

The response contains:
- `matched_lenders[]` — list of lenders with `score`, `match_reason`, `risk_level` (`high_risk | warning | info`)
- `warnings[]` — structural issues (e.g., "NSF count may trigger auto-decline at Funder X")
- `declined_lenders[]` — lenders explicitly filtered out and why
- `narrative` — human-readable summary of the strategy

### Step 3 — Filter and surface the plan

From `matched_lenders`, select the **top 5–8** by score. Exclude any with `risk_level: high_risk` unless Ezra explicitly overrides.

Present to Ezra as:
```
Shop-out plan for [Applicant Name] — [Date]

RECOMMENDED LENDERS (5)
1. [Funder Name] — Score 94 — reason: clean revenue, no NSFs, A-paper profile
2. ...

WARNINGS
- Funder X: NSF count (7) may trigger auto-decline; include only if Ezra approves
- Funder Y: Currently paused on this industry vertical

STRATEGY
[paste narrative from API]

Approve this plan? (yes / modify / cancel)
```

**Wait for Ezra's confirmation before Step 4.**

### Step 4 — Execute the shop-out

On approval:
```
POST /api/applications/[id]/shop-out
{ "dry_run": false, "lender_ids": [id1, id2, ...] }
```

Log the response (`thread_ids[]`, `sent_at`, `submission_count`) to `memory/SESSION_LOG.md`.

### Step 5 — Set follow-up task

After shop-out fires, create a follow-up task for each lender with a 48-hour SLA:
- Check thread status at 48h
- If no response: flag for call or nudge email
- If offer received: route to `skills/underwriting-flow` for term comparison

## Guardrails

- NEVER shop an application with `status = draft` or `status = incomplete`. Verify status is `ready_to_shop` or `pending_shop` first.
- If Ezra is unavailable and an application is time-sensitive, surface in dashboard chat — do not auto-fire without approval.
- Never shop the same application to the same lender within 30 days without Ezra's explicit re-approval.

## Related Skills

- [[skills/underwriting-flow/SKILL.md]] — parse lender offers once they come back
- [[skills/operator-handoff/SKILL.md]] — if Ezra needs to approve a borderline lender inclusion
- [[skills/lender-intelligence/SKILL.md]] — to supplement match scores with historical approval data
- [[skills/follow-up-discipline/SKILL.md]] — post-shop tracking
