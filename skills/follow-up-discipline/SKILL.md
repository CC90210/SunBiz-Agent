---
name: follow-up-discipline
description: Surfaces overdue follow-ups, prioritizes the call list, and recommends specific outreach actions for each stuck deal or contact.
triggers:
  - "what's stuck"
  - "who needs a follow-up"
  - "queue today's calls"
  - "follow-up list"
  - "what's overdue"
  - "who haven't we heard from"
  - "stuck deals"
tier: stable
disable_model_invocation: false
---

# Follow-Up Discipline

> **Where these endpoints live:** All `/api/...` URLs below are routes on
> the OASIS Command Center dashboard (repo: `CC90210/oasis-command-center`,
> deployed at https://agent-dashboard-sigma-eight.vercel.app). They are NOT
> served by this repo's local `scripts/api_server.py` (which only exposes
> `/health`, `/status`, `/sms/send`, `/webhook/jotform`). Solara's bridge
> makes authenticated `fetch` calls into the dashboard's API surface, and
> the dashboard then writes to Supabase / queues threads / dispatches the
> 8 daemons in this repo.

## Purpose

Enforce consistent follow-up cadence. Nothing kills a deal faster than silence. This skill surfaces what's overdue, prioritizes it, and recommends the right channel for each contact.

## How-To-Run

### Step 1 — Pull open follow-up tasks

```
GET /api/follow-up-tasks?status=open&assigned_to=solara
```

Also pull daily plan items:
```
GET /api/daily-plan-items?date=today&status=pending
```

### Step 2 — Categorize by urgency

Sort into four buckets:

| Bucket | Criteria | Action |
|--------|----------|--------|
| **Hot** | Task overdue > 48h OR lender response waiting > 24h | Call today — no delay |
| **Warm** | Task due today | Outreach today — email or call |
  | **Missing info** | Application stalled waiting on docs from merchant | Personal email + text |
| **Monitor** | Task due in 1–3 days | Flag, don't act yet |

### Step 3 — Recommend channel per contact

For each overdue item, recommend the right channel based on contact history:

| Situation | Recommended Channel |
|-----------|-------------------|
| Merchant hasn't responded in > 72h | Personal email (not drip) + text |
| Lender hasn't responded to submission | Email nudge to lender contact |
| Merchant promised docs, hasn't sent | Text + email with specific doc list |
| Offer received, merchant not responding | Call — offers expire |
| Deal stalled at "thinking about it" > 7 days | Schedule a call, use urgency framing |

### Step 4 — Surface the prioritized list

Format for Ezra:
```
Follow-Up Queue — [Date]

HOT (call today)
1. [Merchant Name] — submitted to 3 lenders 72h ago, no response. Nudge all 3 lenders.
2. [Merchant Name] — offer from Funder X expires today. Call merchant NOW.

WARM (outreach today)
3. [Merchant Name] — bank statements requested 3 days ago. Text + email.
4. [Merchant Name] — follow-up after initial outreach. Email + personal note.

MISSING INFO
5. [Merchant Name] — waiting on voided check + 4th month statement.
   Draft: "Hi [Name], just following up on the checklist from [date]..."

MONITOR (due in 1-3 days)
6. [Merchant Name] — shop-out queued for Thursday. No action yet.
```

### Step 5 — Update task status after action

When Ezra confirms an action was taken (call made, email sent), update the task:
```
PATCH /api/follow-up-tasks/[id]
{ "status": "actioned", "actioned_at": "[timestamp]", "outcome": "[brief note]" }
```

Create the next follow-up task immediately if the situation is still open:
```
POST /api/follow-up-tasks
{ "application_id": "[id]", "due_at": "[+48h]", "type": "follow_up", "notes": "[context]" }
```

## Follow-Up SLAs

| Event | SLA |
|-------|-----|
| New inbound lead | First contact < 5 minutes |
| Application submitted to lender | Follow-up lender at 48h |
| Offer received | Merchant contact within 2h |
| Missing docs requested | Follow-up if not received in 48h |
| "Thinking about it" stage | Max 7 days before call |

## Anti-Patterns

- Do not let items age past 72h without an action note — if Ezra handled it, log it.
- Do not recommend a drip email when a personal message is warranted — stale merchants need personal touch.
- Do not mark tasks "actioned" unless a real action occurred — integrity of the queue matters.

## Related Skills

- [[skills/daily-call-sheet-workflow/SKILL.md]] — the daily structured view of this same data
- [[skills/operator-handoff/SKILL.md]] — when a follow-up requires a judgment call
- [[skills/casl-compliance/SKILL.md]] — verify outbound compliance before sending
- [[skills/cold-outreach-blast/SKILL.md]] — for bulk outreach on cold lists (separate from follow-up)
