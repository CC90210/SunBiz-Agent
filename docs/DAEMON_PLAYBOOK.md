# SunBiz Daemon Playbook

> Developer-facing ops reference. One section per daemon: what it does, when it fires, how to monitor it, and common failure modes.
>
> Created: 2026-05-25. Covers all 8 SunBiz daemons.

---

## General monitoring commands

```bash
# All daemon status (run from CEO-Agent directory)
pm2 status

# Logs for a specific daemon
pm2 logs sequence-runner --lines 50

# Follow logs live
pm2 logs lender-response-classifier

# Restart one
pm2 restart shop_out_sender  # or the cron approach below

# Restart all SunBiz-relevant daemons
pm2 restart sequence-runner lender-response-classifier event-router claude-bridge-ping
```

For the cron-driven daemons (`shop_out_sender`, `renewal_reminder`, `daily_plan_generator`, `follow_up_generator`, `cold_outreach_runner`, `underwriting_orchestrator`): they fire through `claude-bridge-ping`'s tenant cron poller. Check their status via the dashboard at `/t/sun/automations` — each cron job shows last-fired time and last-result.

---

## 1. shop_out_sender

**What it does:** Drains `application_lender_threads` rows where `status='pending'`. Atomically claims each row (flips to `status='sending'` with a `SELECT ... FOR UPDATE SKIP LOCKED`) before sending, which prevents double-sends on crash-restart. Sends via Gmail SMTP, records the `gmail_thread_id`, then marks `sent` or `error`.

**When it fires:** Cron-driven via `claude-bridge-ping`'s tenant cron poller. Default interval: every 60 seconds. Manifest key: `shop_out_sender_loop`. Not a standalone PM2 daemon — it relies on `claude-bridge-ping` being healthy.

**How to monitor:**
- Dashboard: `/t/sun/shopping-out` — each lender thread shows current status
- Supabase: `SELECT id, lender_id, status, created_at FROM application_lender_threads WHERE status IN ('pending','sending','error') ORDER BY created_at DESC`
- Logs: `pm2 logs claude-bridge-ping --lines 100 | grep shop_out`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| Threads stuck at `pending` for >5 min | `claude-bridge-ping` not running, or cron job not seeded | `pm2 status` → restart if down; check `/t/sun/automations` for the cron job |
| Threads flipping to `error` | Gmail SMTP auth failure | Regenerate App Password at [Google App Passwords](https://myaccount.google.com/apppasswords), update `GMAIL_APP_PASSWORD` in `.env.agents`, restart `claude-bridge-ping` |
| Threads stuck at `sending` | Crash mid-send | Safe to re-trigger: `SKIP LOCKED` means only abandoned `sending` rows are re-claimed on next run. Check if `send_interaction_id` column is set — if yes, the send happened and Gmail tracking was lost; manually mark `sent`. |
| No threads being claimed | Operator hasn't queued a shop-out yet, or `status` column has unexpected value | Query Supabase directly to confirm row count; check migration 068 was applied (adds `sending` to the status constraint) |

---

## 2. sequence_runner

**What it does:** Two-phase loop. Phase 1 (enrollment): reads `agent_events` since cursor, matches `BRAVO_RECORD_STATUS_CHANGED` events against `drip_sequences` definitions, inserts `sequence_state` rows for matching (lead, sequence) pairs. Phase 2 (execution): polls `sequence_state` for rows where `due_at <= now()`, fires each via `send_gateway.send`, advances to next step. All sends route through `send_gateway` — CASL, cooldowns, and daily caps are enforced automatically.

**When it fires:** PM2 daemon, 10-second tick. Continuous long-running process. Cursor state in `state/sequence_runner.cursor` (CEO-Agent directory) — restarts are lossless.

**How to monitor:**
- `pm2 logs sequence-runner --lines 50`
- Dashboard: `/t/sun/sequences` — active sequence enrollments with step progress
- Supabase: `SELECT lead_id, sequence_id, step, status, due_at FROM sequence_state WHERE tenant_id=<sun_tenant_id> ORDER BY due_at LIMIT 20`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| No sequences firing despite stage changes | `agent_events` not being written | Confirm the dashboard route emits `BRAVO_RECORD_STATUS_CHANGED` on stage update; check `SELECT * FROM agent_events ORDER BY created_at DESC LIMIT 5` |
| Sequence fires but SMS not sent | `send_gateway` cooldown or daily cap hit | Check `state/send_gateway.log` in CEO-Agent; operator may need to wait for cap reset or adjust cap config |
| Cursor stuck (same events replayed) | `state/sequence_runner.cursor` file corrupted | Delete the cursor file and restart — daemon will re-read from `now()` forward (won't replay old events) |
| Daemon crash-loops | Missing Python dep or Supabase connection refused | `pm2 logs sequence-runner --lines 20` — read the traceback; most common: wrong Supabase URL or service-role key |

---

## 3. lender_response_classifier

**What it does:** Polls `application_lender_threads` where `status='sent'` and `gmail_thread_id IS NOT NULL`. For each thread, fetches the latest message via `scripts/integrations/google_tool.py` (Gmail REST API). Classifies the reply using Claude Haiku 4.5 into `approved / declined / info_requested / unclear`. Updates `status` and `last_response_summary`. Also runs an SLA sweep: threads at `status='sent'` older than the lender's `sla_response_days` auto-flip to `no_response` (no classifier call — just a timestamp comparison).

**When it fires:** PM2 daemon, 5-minute tick (300 seconds). Can be run with `--interval 60` on a busy submission day for tighter responsiveness.

**How to monitor:**
- `pm2 logs lender-response-classifier --lines 50`
- Dashboard: `/t/sun/shopping-out` — lender status cards update automatically
- Supabase: `SELECT id, status, last_response_summary, updated_at FROM application_lender_threads WHERE status NOT IN ('pending','sending') ORDER BY updated_at DESC LIMIT 10`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| Daemon 401s on Gmail | App Password expired or revoked | Regenerate App Password, update `GMAIL_APP_PASSWORD`, restart daemon |
| Classifier returns `unclear` for obvious replies | Haiku model context too short or lender reply is in an unusual format | Check `last_response_summary` — if the raw text is garbled HTML, the Gmail fetch may be returning the HTML body rather than plain text; check `google_tool.py`'s text extraction |
| SLA sweep not firing | Lender rows missing `sla_response_days` in their Supabase record | Update the lender record in the dashboard to add `sla_response_days` |
| Daemon fine but no lender updates visible in dashboard | RLS blocking the dashboard query | Confirm dashboard user's session tenant_id matches the lender thread's tenant_id |

---

## 4. renewal_reminder

**What it does:** Identifies funded deals approaching their renewal window. For each approaching renewal, drafts a renewal outreach message and queues it for operator approval. Sends a Telegram notification to Ezra when a deal is within the configured window. Respects quiet days (weekends and stat holidays) before pinging.

**When it fires:** Cron-driven via `claude-bridge-ping`. Default: daily at a configured time. Manifest key: `renewal_reminder_loop`.

**How to monitor:**
- Dashboard: `/t/sun/automations` — last-run time and last result
- Telegram: Ezra receives a Telegram alert when renewals are queued for review
- Supabase: `SELECT id, data->>'merchant_name', data->>'funded_at', data->>'renewal_date' FROM tenant_records WHERE type='funded_deal' AND tenant_id=<sun_id>`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| No renewal pings despite upcoming deals | `renewal_date` not set on funded deal records | Check funded deal records in Supabase — confirm `data->>'renewal_date'` is populated |
| Telegram notification not arriving | `BRAVO_TELEGRAM_CHAT_ID` or `RENEWAL_REMINDER_CHAT_ID` not set in `.env.agents` | Add the key; restart `claude-bridge-ping` |
| Renewal message drafted but not sent | Working as designed — operator must approve before send | Check the dashboard for pending renewal approvals |

---

## 5. follow_up_generator

**What it does:** Reads the `follow_up_tasks` queue (rows where `status='pending'` and `due_at <= now()`). For each task, generates a contextual follow-up message based on the lead's interaction history, application state, and agent memory notes. Surfaces the draft to the operator (via dashboard or Telegram) before sending. Marks the task `draft_ready` or `sent` depending on operator approval flow.

**When it fires:** Cron-driven via `claude-bridge-ping`. Default: every 30 minutes. Manifest key: `follow_up_generator_loop`.

**How to monitor:**
- Dashboard: `/t/sun/pipeline` — follow-up tasks visible in the lead detail drawer
- Supabase: `SELECT id, lead_id, due_at, status, priority FROM follow_up_tasks WHERE tenant_id=<sun_id> ORDER BY due_at`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| Follow-up tasks not appearing in dashboard | `follow_up_tasks` table missing (migration 069 not applied) | Apply migration 069 |
| Generator running but drafts not surfacing | Anthropic API key missing or rate-limited | Check `ANTHROPIC_API_KEY` in `.env.agents`; check Anthropic usage dashboard |
| Duplicate follow-up tasks | `follow_up_generator` running twice (two cron seeds) | Audit `/t/sun/automations` for duplicate cron jobs with the same manifest key |

---

## 6. cold_outreach_runner

**What it does:** Processes `cold_outreach_campaigns` step by step. For each campaign in `active` state, reads `cold_outreach_recipients` where the next step is due, renders the message from the campaign's sequence template, fires via `send_gateway` (SMS) or `smtplib` (email), updates the recipient's step and status. Respects campaign-level daily caps and CASL consent flags. Recipients who opt out are immediately marked `unsubscribed` and excluded from all future steps.

**When it fires:** Cron-driven via `claude-bridge-ping`. Default: every 15 minutes. Manifest key: `cold_outreach_runner_loop`.

**How to monitor:**
- Dashboard: `/t/sun/outreach` — campaign list with step-by-step delivery stats
- Supabase: `SELECT campaign_id, status, COUNT(*) FROM cold_outreach_recipients GROUP BY campaign_id, status`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| Campaign stuck, no sends | `send_gateway` daily cap exhausted | Check cap in CEO-Agent config; consider splitting campaign over multiple days |
| Recipients not advancing past step 1 | Delay between steps not yet elapsed | By design — check `due_at` on recipient rows |
| Opt-out not removing recipient from future steps | `send_gateway` opt-out handler not wired | Confirm `send_gateway.py` opt-out callback updates `cold_outreach_recipients.status='unsubscribed'` |

---

## 7. daily_plan_generator

**What it does:** Runs once each morning. Reads the full pipeline state: pipeline lead counts by stage, applications due for action, follow-up tasks due today, renewal windows approaching, lender threads awaiting response, cold outreach step counts. Synthesizes into a prioritized list of `daily_plan_items` rows with recommended actions. The dashboard's daily plan widget reads these rows.

**When it fires:** Cron-driven via `claude-bridge-ping`. Default: 07:00 local time (America/Toronto). Manifest key: `daily_plan_generator_run`. Skips quiet days (weekends, Ontario stat holidays) via `scripts/schedule_helpers.py`.

**How to monitor:**
- Dashboard: `/t/sun/` home — daily plan widget
- Supabase: `SELECT * FROM daily_plan_items WHERE tenant_id=<sun_id> AND plan_date=CURRENT_DATE ORDER BY priority`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| Daily plan empty | Migration 069 not applied | Apply migration 069 (`daily_plan_items` table) |
| Plan not refreshing | Cron job not seeded or `claude-bridge-ping` down | Check `/t/sun/automations`; restart `claude-bridge-ping` if needed |
| Plan generates but has stale data | Pipeline queries using wrong tenant_id | Confirm the generator resolves tenant via `custom_fields.command_center_profile_slug = 'sun'` not `slug = 'sun'` |

---

## 8. underwriting_orchestrator

**What it does:** Three-phase pipeline per application. Phase 1: `statement_parser` extracts metrics from bank statement PDFs using Claude's vision capability (average monthly revenue, average daily balance, NSF count, deposit consistency). Phase 2: `debt_detector` identifies existing MCA positions from the statements (lender names, estimated daily debits, position count). Phase 3: `sales_angle` generates a lender-pitch narrative based on the metrics and debt profile. Writes all output to `application_underwriting` (append-only — re-runs are preserved). Sets `readiness_score` (0-100) as an agent suggestion, not a binding decision.

**When it fires:** On-demand (operator clicks "Run Underwriting" in the dashboard) and optionally via cron on newly submitted applications. Manifest key when cron-driven: `underwriting_orchestrator_run`.

**How to monitor:**
- Dashboard: `/t/sun/applications/[id]` — underwriting panel shows latest run output
- Supabase: `SELECT application_id, status, readiness_score, run_at FROM application_underwriting ORDER BY run_at DESC LIMIT 10`

**Common failure modes:**

| Symptom | Cause | Fix |
|---|---|---|
| Underwriting stuck at `parsing` | Bank statement PDF not accessible or is password-protected | Check the file in Supabase storage; confirm it's a readable PDF (not a scanned image-only PDF with no text layer) |
| `error` status with `ModuleNotFoundError` | `pdfplumber` or `PyMuPDF` not installed | `pip install pdfplumber PyMuPDF` in the active venv |
| Low readiness score on a clean deal | Unusual bank statement format causing parser miss | Check `parser_output` JSONB column — if revenue is near-zero but deposits look normal, the parser may be reading the wrong columns. Open an issue with the statement format. |
| Vision model rate-limit | Anthropic Claude rate limit hit | Underwriting jobs queue naturally — the next attempt will succeed. Add retry logic if this is frequent. |

---

## VPS-specific notes

On a VPS, the cron-driven daemons (`shop_out_sender`, `renewal_reminder`, `daily_plan_generator`, `follow_up_generator`, `cold_outreach_runner`, `underwriting_orchestrator`) run through `claude-bridge-ping`'s cron poller. That poller calls `/api/cron-jobs/poll` on the dashboard and dispatches jobs via `bridge_tools`. If the bridge token is stale or the VPS is not paired, no cron jobs fire.

**Verify pairing:** Dashboard → Settings → Devices. The VPS machine should show a green "Online" indicator. If it shows offline: `cat ~/.oasis/bridge_token` on the VPS, confirm the file exists, `pm2 restart claude-bridge-ping`.

**Verify cron seeds:** Dashboard → `/t/sun/automations`. Each of the six cron-driven daemons should have a registered cron job. If any are missing, seed them via the automations page or contact OASIS support.
