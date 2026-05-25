---
name: cold-outreach-blast
description: Queue a cold outreach campaign to a segmented lead list via the cold_outreach_campaigns endpoint, with CASL compliance enforced before any send.
triggers:
  - "blast this list"
  - "send a campaign"
  - "cold outreach"
  - "run the blast"
  - "queue the campaign"
  - "send to this list"
  - "outreach campaign"
tier: stable
disable_model_invocation: false
argument_hint: "Which cold lead list (by name or ID) and what message template should I use?"
requires:
  - env:SUNBIZ_SUPABASE_URL
  - env:SUNBIZ_SUPABASE_ANON_KEY
  - env:SUNBIZ_SENDGRID_API_KEY
---

# Cold Outreach Blast

## Purpose

Execute a structured email campaign to a segmented cold lead list. This skill covers list selection, template validation, CASL compliance enforcement, and campaign queueing — not individual follow-ups (use `skills/follow-up-discipline/SKILL.md` for those).

## How-To-Run

### Step 1 — Select the list

```
GET /api/cold-lead-lists
```

Choose the right list by name, segment, or Ezra's instruction. Check:
- `recipient_count` — how many contacts
- `last_used_at` — when it was last blasted (avoid re-blasting within 14 days)
- `segment_criteria` — confirm it matches Ezra's intent

### Step 2 — Select or compose the template

```
GET /api/outreach-templates?type=cold
```

If an existing template fits, use it. If composing new copy:
- Keep it under 150 words — cold emails that read long get deleted
- Subject line: curiosity or pattern interrupt, not a pitch
- Body: one pain point, one question, one CTA — no more
- No factor rates, no pricing in cold email — get the conversation first
- Personalization variables: `{{first_name}}`, `{{business_name}}`, `{{industry}}` minimum

### Step 3 — CASL compliance check (MANDATORY before queuing)

**This step is never optional.** Route through `skills/casl-compliance/SKILL.md` before proceeding:

1. Confirm list has valid consent records or falls under implied consent (B2B exception, < 2 years)
2. Confirm CASL footer is in template (unsubscribe link + physical address)
3. Confirm list was last scrubbed for opt-outs within the current week
4. Confirm you are within the send window (9am–6pm recipient local time, Mon–Fri)
5. Confirm daily cap is not exceeded (check `campaigns.sent_today` counter)

If ANY check fails, surface the issue to Ezra — do not queue.

### Step 4 — Validate template variables

Before queuing, verify that every personalization variable in the template exists in the list's data:
```
POST /api/outreach-templates/[id]/validate
{ "list_id": "[id]" }
```

Response will flag any records with missing variables. Resolve or exclude before proceeding.

### Step 5 — Queue the campaign

```
POST /api/cold-outreach-campaigns
{
  "list_id": "[id]",
  "template_id": "[id]",
  "send_window_start": "09:00",
  "send_window_end": "18:00",
  "timezone": "America/Toronto",
  "daily_cap": 50,
  "scheduled_start_at": "[ISO timestamp or null for immediate]"
}
```

Response includes `campaign_id`, `estimated_send_duration`, `total_recipients`.

### Step 6 — Monitor delivery

```
GET /api/cold-outreach-campaigns/[id]/recipients?status=failed
```

Check for failed sends after the first batch. Common failures:
- Invalid email (bounce) — remove from list
- Unsubscribe triggered mid-campaign — campaign auto-pauses, normal behavior
- Daily cap hit — resumes automatically next business day

### Step 7 — Log and set follow-up cadence

Log the campaign launch in `memory/SESSION_LOG.md`. After 48–72h, check open rates and bounce rates:
```
GET /api/cold-outreach-campaigns/[id]/stats
```

If open rate < 10%: flag for template review.
If bounce rate > 3%: pause campaign, scrub list.

## Guardrails

- NEVER bypass `scripts/integrations/send_gateway.py` — all sends route through it for audit logging and bounce handling.
- NEVER blast a list that hasn't been opt-out-scrubbed in the current week.
- NEVER include pricing, factor rates, or advance amounts in cold email — only in follow-up after prospect engagement.
- If Ezra is not available and a campaign is ready to fire, queue it but DO NOT set `scheduled_start_at` to immediate — set to next business day and notify Ezra.

## Related Skills

- [[skills/casl-compliance/SKILL.md]] — mandatory compliance check (Step 3)
- [[skills/email-outbound/SKILL.md]] — individual email sends (not blast)
- [[skills/follow-up-discipline/SKILL.md]] — post-campaign follow-up on engaged contacts
- [[skills/operator-handoff/SKILL.md]] — if Ezra needs to approve a non-standard send
