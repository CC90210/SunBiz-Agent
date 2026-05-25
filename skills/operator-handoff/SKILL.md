---
name: operator-handoff
description: Pause cleanly at a decision boundary, surface the decision to Ezra via Telegram or dashboard chat, and wait for explicit confirmation before proceeding.
triggers:
  - "pause and check with Ezra"
  - "wait for operator"
  - "need approval"
  - "decision boundary"
  - "irreversible action"
  - "escalate to Ezra"
  - "ambiguous lender response"
tier: stable
disable_model_invocation: false
---

# Operator Handoff

> **Where these endpoints live:** All `/api/...` URLs below are routes on
> the OASIS Command Center dashboard (repo: `CC90210/oasis-command-center`,
> deployed at https://agent-dashboard-sigma-eight.vercel.app). They are NOT
> served by this repo's local `scripts/api_server.py` (which only exposes
> `/health`, `/status`, `/sms/send`, `/webhook/jotform`). Solara's bridge
> makes authenticated `fetch` calls into the dashboard's API surface, and
> the dashboard then writes to Supabase / queues threads / dispatches the
> 8 daemons in this repo.

## Purpose

Solara operates autonomously but has hard boundaries. When a decision is irreversible, involves a sensitive client interaction, is legally ambiguous, or would commit resources Ezra hasn't explicitly approved — STOP and hand off. Autonomous action on the wrong side of a judgment call causes real damage. A short pause costs nothing.

## When to Trigger This Skill

**Always pause and hand off when:**

1. **Irreversible actions** — sending an offer to a merchant, declining a lender's counter, firing a bulk blast, cancelling a funded deal
2. **Sensitive merchant interactions** — a merchant is upset, confused, or has raised a complaint
3. **Ambiguous lender response** — lender countered with unusual terms, asked for additional stipulations, or their message is unclear
4. **D-paper escalation** — underwriting returned paper_grade D — Solara does not route D-paper without Ezra's explicit direction
5. **Compliance gray area** — CASL check surfaced a borderline consent status; Ezra must own the call
6. **Commitment above threshold** — any action that could commit SunBiz Funding to > $10,000 in exposure
7. **Conflict between systems** — shop-out API score and lender_intelligence history disagree significantly on a lender

**Do not pause for:**
- Routine data pulls and summaries
- Generating follow-up task lists
- Drafting emails for Ezra to review
- Underwriting reads that return clean A/B paper

## How-To-Run

### Step 1 — Pause immediately

Stop the current workflow. Do not proceed to the next action in the sequence. Log the pause point:
```
POST /api/operator-handoffs
{
  "triggered_by": "operator-handoff skill",
  "context": "[one paragraph: what was happening, what the decision is, what options exist]",
  "blocking_action": "[what Solara cannot do until Ezra responds]",
  "urgency": "low | medium | high | urgent"
}
```

### Step 2 — Surface the decision

**Via dashboard chat** (preferred — leaves a paper trail):
```
Surface the handoff to the SunBiz Command Center chat:
POST /api/dashboard-chat
{
  "message": "[see template below]",
  "requires_response": true,
  "handoff_id": "[id from step 1]"
}
```

**Via Telegram** (when urgency is high or urgent):
Send a structured message to Ezra's Telegram chat.

**Handoff message template:**
```
SOLARA PAUSE — [Urgency: HIGH]

Situation: [1-2 sentences on what's happening]

Decision needed: [One clear question with options]
  Option A: [Action + consequence]
  Option B: [Alternative + consequence]
  Option C: Hold / do nothing [always an option]

Context: [Any data Ezra needs — deal name, amounts, lender name]

Blocking: [What Solara cannot do until this is answered]

Reply with A, B, C, or a specific instruction.
```

### Step 3 — Wait for response

Do not proceed. Do not guess. Do not "use best judgment" on irreversible actions.

If Ezra has not responded within:
- **Urgent**: 15 minutes → send Telegram follow-up
- **High**: 2 hours → send reminder in dashboard chat
- **Medium/Low**: next business day check-in during daily briefing

### Step 4 — Execute on explicit response

When Ezra responds, confirm the instruction back before executing:
"Got it — I'll [action]. Proceeding now." Then execute.

Log the decision and Ezra's response:
```
PATCH /api/operator-handoffs/[id]
{
  "operator_response": "[Ezra's exact response]",
  "resolved_at": "[timestamp]",
  "action_taken": "[what was executed]"
}
```

Also log to `memory/DECISIONS.md` if this is an architectural or policy-level decision.

## What This Skill Is NOT

- Not a crutch for every ambiguous situation — Solara should use judgment on low-stakes reversible actions
- Not a way to avoid work — if the answer is obvious, act; if it's genuinely unclear, pause
- Not required for informational queries — data pulls, summaries, and drafts don't need operator approval

## Guardrails

- The handoff message MUST be plain English — no JSON, no raw API responses. Ezra reads these on his phone.
- Always include "Option C: Hold / do nothing" — never force a binary choice on a decision boundary.
- Never describe the pause as a failure — it's a feature. Solara pausing > Solara guessing wrong.

## Related Skills

- [[skills/casl-compliance/SKILL.md]] — compliance gray areas escalate here
- [[skills/underwriting-flow/SKILL.md]] — D-paper results escalate here
- [[skills/shop-out-routing/SKILL.md]] — borderline lender inclusions escalate here
- [[skills/funding-vocabulary/SKILL.md]] — to ensure the handoff message uses correct terminology
