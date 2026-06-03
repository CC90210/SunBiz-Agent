---
name: AGENT ROUTER
description: Solara's routing-by-intent table. Loaded after the entry point. Tells Solara which file to read for each kind of operator request.
mutability: SEMI-MUTABLE
tags: [brain, router, agent-only]
last_updated: 2026-05-25
---

# AGENT ROUTER — How to Decide What to Read

> Loaded by Solara after the entry point. Everything else is lazy-loaded via Read based on what the operator asks for.
> Stay under ~200 lines so it fits in the boot context.

---

## How to use this file

Every operator turn, do this in order:

1. **Read the message.** Identify intent — one of: check status, take action on a deal, send something, look up a lender, escalate, configure a daemon.
2. **Match against the tables below.** Each row tells you which file(s) to read for context, in priority order.
3. **Read only what the intent needs.** Token budget is real. Never bulk-load.
4. **Execute yourself if you have the tool.** Never tell Ezra to run a command you can run. See `brain/EXECUTION_RULES.md`.
5. **Confirm what you did.** State the change, the source, and the next-action queued.

---

## Operator-Specific Facts

Ezra's profile (role, team, priorities, comm channels) lives in `brain/USER.md`. Read it once on the first operational turn of a session. After that, trust your prompt unless Ezra says something changed.

---

## Intent → Which File to READ

| If Ezra asks about... | Read first | Then if needed |
|---|---|---|
| Who Solara is / identity / values | (already in prompt) | `brain/SOUL.md` |
| Ezra's profile / team | `brain/USER.md` | — |
| SunBiz business profile / ICP / compliance rules | `brain/CLIENT.md` | — |
| What tools/scripts Solara has | `brain/CAPABILITIES.md` | — |
| Which sub-agent owns a task | `brain/AGENTS.md` | — |
| Today's plan / deal queue | `brain/STATE.md` | `memory/ACTIVE_TASKS.md` |
| What just happened / recent sessions | `memory/SESSION_LOG.md` | `memory/DECISIONS.md` |
| Past mistakes to avoid | `memory/MISTAKES.md` | — |
| Validated lender patterns | `memory/PATTERNS.md` | — |
| Which skill to use | `brain/WHEN_TO_USE_SKILLS.md` | `skills/<name>/SKILL.md` |
| Specific action verb (enroll, queue, score, draft, kick-off, escalate) | `brain/INTENTS.md` | — |
| What Solara may write / what requires Ezra confirmation | `brain/EXECUTION_RULES.md` | — |
| Reasoning protocol / multi-hypothesis | `brain/BRAIN_LOOP.md` | — |
| Lender portfolio / lender appetite profiles | `memory/LONG_TERM.md` (lender facts) | `memory/PATTERNS.md` (validated match patterns) |
| Shop-out status on a specific deal | Query Supabase: `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py query "SELECT id, data->>'status' as status FROM tenant_records WHERE entity_type='application' AND id='<id>'"` | `brain/STATE.md` |
| Renewal pipeline | (run `python scripts/renewal_reminder.py --window 30 --json`) | `brain/STATE.md` |
| Commission calculation | Query `application_lender_threads` where `status='offer_received'` — see `brain/EXECUTION_RULES.md` §11. `(tenant_records via supabase_tool).py` + `(commission/renewal projections — Phase 6.6).py` are **Phase 6.6 — not yet implemented**. | — |
| How the logging / audit trail works | `brain/INTERACTION_PROTOCOL.md` | — |
| Capability growth / new skill candidates | `brain/GROWTH.md` | — |
| What changed in this agent | `brain/CHANGELOG.md` | — |
| Heartbeat schedule / monitoring | `brain/HEARTBEAT.md` | — |

---

## Intent → Which TOOL to Call (When to Act, Not Just Read)

| Ezra wants... | Tool / Script | Confirm Required? |
|---|---|---|
| Deal status / queue check | `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py query "SELECT id, data->>'status' as status, data->>'business_name' as name FROM tenant_records WHERE entity_type='application' AND data->>'status'='<status>'"` | No |
| Pre-screen an application | `python scripts/underwriting_orchestrator.py score --deal-id <id>` | No |
| Submit application to lender(s) | `python scripts/shop_out_sender.py send --deal-id <id>` | **Yes — same turn** |
| Mark deal funded | Update `tenant_records` via `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py update tenant_records --eq '{"id":"<id>"}' --data '{"data":{"status":"funded"}}'` | **Yes — same turn** |
| Renewal scan | `python scripts/renewal_reminder.py --window 30 --json` | No |
| Commission calculation | Query `application_lender_threads` directly — `(commission/renewal projections — Phase 6.6).py` is **Phase 6.6 — not yet implemented**. Use `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py query "SELECT funded_amount, buy_rate FROM application_lender_threads WHERE status='offer_received' AND deal_id='<id>'"` | No |
| Daily brief / call sheet | `python scripts/daily_plan_generator.py run --date today --json` | No |
| Read Supabase table | `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py query "SELECT * FROM <table> WHERE tenant_id='sunbiz' LIMIT 10"` | No |
| Write to Supabase | `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py insert <table> --data '...'` | **Yes — mutating** |
| Send email to merchant | `python ~/Business-Empire-Agent/scripts/integrations/send_gateway.py send --channel email --to <addr> --cc <assigned_rep_email> --subject "..." --body-html "..." --brand sunbiz --agent-source solara` — this is the ONLY email path. It sends FROM the shared submissions@sunbizfunding.com identity and CCs the assigned rep. **Do NOT glob/grep for email_blast or SMTP scripts** (that path sends from the wrong identity and is guarded). | **Yes — outbound** |
| Send SMS to merchant | `python ~/Business-Empire-Agent/scripts/integrations/send_gateway.py send --channel sms --to <e164> --body "..." --brand sunbiz --agent-source solara` | **Yes — outbound** |
| Start drip sequence | `python scripts/sequence_runner.py start --lead-id <id> --sequence <name>` | **Yes — outbound** |
| Generate follow-up draft | `python scripts/follow_up_generator.py draft --lead-id <id> --context "<context>"` | No (draft only) |
| Post handoff to Helios | `python scripts/agent_inbox.py post --to helios --message "<msg>"` | No |
| Check agent inbox | `python scripts/agent_inbox.py list --to solara` | No |
| Heartbeat to V6 substrate | `python ~/Business-Empire-Agent/scripts/state/state_sync.py --agent solara --note "heartbeat"` | No |

---

## Agent Delegation

| Delegate to | When |
|-------------|------|
| **Helios** | Merchant outbound, follow-up calls, meeting booking, sequence execution |
| **Ezra (escalate)** | Irreversible actions, lender contract decisions, compliance-sensitive copy, stacking-risk threshold exceeded |
| **Atlas (CFO-Agent)** | Budget approvals above threshold, commission tax modeling (via Bravo's agent_inbox) |

---

## How to Keep This Router Fresh

When a new high-frequency file or tool lands:
1. Add a row to the right table.
2. Keep descriptions to one line. Bodies live in their own files.
3. Bump `last_updated:`.
4. Remove obsolete rows.

If the table grows past ~200 lines, split intents into `brain/INTENTS.md`.
