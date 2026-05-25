# SunBiz Agent — Architecture

> Developer-facing. Describes the three-repo split, data flow, and the path a request takes from Ezra through to Supabase.
>
> Created: 2026-05-25. Mirrors the system state after migration 069 + V6.8 cognitive substrate upgrade.

---

## The three-repo split

Sun Biz Funding's AI stack lives across three GitHub repositories. Each owns a distinct layer. They share one Supabase project and one PM2 runtime.

| Repo | Local path | What it owns |
|---|---|---|
| `CEO-Agent` | `~/Business-Empire-Agent` | Empire substrate: state DB, guards, event bus, memory retrieval, PM2 ecosystem, send_gateway, cross-agent event router |
| `SunBiz-Agent` | `~/SunBiz-Agent` | SunBiz business logic: daemons, migrations 042-069, Solara's brain, skills |
| `oasis-command-center` | `~/APPS/oasis-command-center` | Dashboard UI: Next.js 14 App Router, Vercel deployment, all frontend routes |

**The hard rule:** never duplicate a substrate component. If it belongs to CEO-Agent (send_gateway, exec_guard, sequence_runner source), reference it — do not copy it into SunBiz-Agent.

---

## System overview

```
┌─────────────────────────────────────────────────────┐
│  Ezra (operator)                                    │
│  Telegram / Dashboard browser                       │
└───────────────────┬─────────────────────────────────┘
                    │
          ┌─────────▼──────────┐
          │  OASIS Command     │
          │  Center            │
          │  (oasis-command-   │
          │   center repo)     │
          │  Next.js 14        │
          │  Vercel            │
          └─────────┬──────────┘
                    │
         ┌──────────▼───────────────────────┐
         │  Supabase (shared OASIS project) │
         │  PostgreSQL + RLS                │
         │  Tables: tenant_records,         │
         │  drip_sequences, sequence_state, │
         │  application_lender_threads,     │
         │  agent_events, cron_jobs,        │
         │  + 14 migration-069 tables       │
         └──────────┬───────────────────────┘
                    │  LISTEN/NOTIFY + REST
          ┌─────────▼──────────────────────┐
          │  CEO-Agent (PM2 runtime)        │
          │  Business-Empire-Agent repo     │
          │                                │
          │  PM2 processes:                │
          │  - event-router (event bus)    │
          │  - sequence-runner (drip)      │
          │  - lender-response-classifier  │
          │  - claude-bridge-ping (cron)   │
          │  - claude-bridge (HTTP server) │
          └─────────┬──────────────────────┘
                    │  imports SunBiz logic
          ┌─────────▼──────────────────────┐
          │  SunBiz-Agent (this repo)      │
          │                                │
          │  scripts/:                     │
          │  - shop_out_sender             │
          │  - underwriting_orchestrator   │
          │  - renewal_reminder            │
          │  - follow_up_generator         │
          │  - cold_outreach_runner        │
          │  - daily_plan_generator        │
          │  database/: migrations 042-069 │
          │  brain/: Solara's substrate    │
          └────────────────────────────────┘
```

---

## Request flow — Ezra makes a decision in the dashboard

Walking through the full path for a common action: Ezra clicks "Shop Out" on an application.

```
1. Ezra clicks "Shop Out" on /t/sun/applications/[id]
   └─ Dashboard POST /api/applications/[id]/shop-out
      └─ Validates operator session (Supabase auth)
      └─ Reads lender list, renders body_template per lender
      └─ Inserts rows into application_lender_threads
         (status='pending', body_template+attachments stored per migration 065)
      └─ Returns 200 to dashboard — operator sees "Queued"

2. claude-bridge-ping (PM2 daemon) polls /api/cron-jobs/poll every 60s
   └─ Finds cron_job with action_type='script', manifest_key='shop_out_sender_loop'
   └─ Calls bridge_tools to execute shop_out_sender.py

3. shop_out_sender.py runs
   └─ SELECT ... FOR UPDATE SKIP LOCKED on application_lender_threads
      WHERE status='pending'  (atomic claim — prevents double-send on crash)
   └─ Updates claimed rows to status='sending'
   └─ For each thread:
      a. Fetches operator-approved body_template + attachments from Supabase
      b. Sends via smtplib SMTP_SSL (Gmail credentials from .env.agents)
      c. Updates status='sent', records gmail_thread_id
   └─ On any SMTP error: status='error', error_message recorded

4. lender-response-classifier (PM2 daemon, 5-min tick)
   └─ Queries application_lender_threads WHERE status='sent'
   └─ Fetches Gmail thread via google_tool.py
   └─ Classifies reply via Claude Haiku:
      approved | declined | info_requested | unclear
   └─ Updates application_lender_threads.status + last_response_summary

5. Ezra opens /t/sun/applications/[id]
   └─ Dashboard reads application_lender_threads
   └─ Renders per-lender status: Approved / Declined / Info Requested / Awaiting
   └─ No Gmail access needed — Solara surfaced the result
```

---

## Request flow — lead stage change triggers a drip sequence

```
1. Ezra (or dashboard automation) updates a lead's stage
   └─ Dashboard PATCH /api/records/[id] sets data->>'stage' = 'hot_lead'
   └─ Route calls send_gateway._emit_record_status_changed
   └─ Inserts row into agent_events:
      type='BRAVO_RECORD_STATUS_CHANGED'
      payload={entity:'lead', from:'new', to:'hot_lead', tenant_id:'...'}

2. sequence-runner (PM2 daemon, 10s tick)
   ENROLLMENT phase:
   └─ Reads agent_events since cursor
   └─ Matches event against drip_sequences WHERE trigger='lead_stage_hot_lead'
   └─ Inserts sequence_state row: (lead_id, sequence_id, step=1, due_at=now())

   EXECUTION phase (same tick):
   └─ Reads sequence_state WHERE due_at <= now() AND status='pending'
   └─ For each due row:
      a. Resolves message template from drip_sequences.steps[step]
      b. Calls send_gateway.send(channel='sms', to=lead.phone, body=rendered)
         └─ send_gateway enforces: CASL consent, cooldown, daily cap, DNS rep
      c. Updates sequence_state: step++, due_at = now() + delay, status='sent'
```

---

## Security boundaries

**Supabase RLS** — every table used by the dashboard is RLS-enabled. Operators can only see rows where `tenant_id` matches their session. The PM2 daemons connect as service-role (bypasses RLS) because they process all tenants' rows — but they always scope writes to the resolved `tenant_id` from the event payload.

**send_gateway chokepoint** — all outbound SMS and email from any daemon passes through `scripts/send_gateway.py` in CEO-Agent. It enforces: CASL compliance check, per-recipient cooldown, daily cap, hourly cap, domain cap, DNS reputation check, draft critic, bounce circuit breaker, reservation guard. No daemon may call smtplib or Twilio directly without going through this gate. The only exception is `shop_out_sender` which uses smtplib directly for lender emails (lender-facing, not prospect-facing, no CASL applicability).

**exec_guard** — every Bash command in the agent runtime passes through `scripts/state/exec_guard.py` in CEO-Agent. Blocks: DROP TABLE, TRUNCATE, DELETE without WHERE, rm -rf outside tmp, git push --force to main. The block is the protection — no approval queue.

**secret_guard** — `.env.agents` and all credential files are blocked from Read and Bash access. Credentials are only accessible via CLI wrappers that load via `scripts/lib/secret_loader.py`.

**HMAC-signed bridge requests** — dashboard-to-VPS API calls are signed with `SUNBIZ_AGENT_HMAC_SECRET`. The `api_server.py` validates the signature and rejects requests older than 60 seconds (replay protection).

---

## Database schema overview

All SunBiz records live in the shared OASIS Supabase project under the tenant identified by `tenant_manifests.slug = 'sun'` (or equivalently `tenants.custom_fields.command_center_profile_slug = 'sun'`). The two namespace identifiers are decoupled — always resolve via `custom_fields.command_center_profile_slug`, not `tenants.slug`.

Core tables (empire-wide, shared with all tenants):

- `tenants` — tenant registry
- `tenant_manifests` — per-tenant config (nav, features, cron_jobs)
- `tenant_records` — universal JSONB record store (leads, applications, offers, lenders all live here as typed rows)
- `agent_events` — cross-agent event bus (Postgres LISTEN/NOTIFY)
- `lead_interactions` — interaction timeline (calls, SMS, emails, notes)
- `cron_jobs` — operator-configured scheduled jobs

SunBiz-specific tables (added by migrations 042-069):

- `forms`, `form_submissions` (042)
- `drip_sequences`, `sequence_state` (043)
- `application_lender_threads` (044, extended by 065, 068)
- 14 tables from migration 069 — see `docs/MIGRATION_HISTORY.md`

---

## Where each daemon runs

| Daemon | Process manager | Host | Source repo |
|---|---|---|---|
| `event-router` | PM2 | VPS or Windows workstation | CEO-Agent |
| `sequence-runner` | PM2 | VPS or Windows workstation | CEO-Agent (calls SunBiz scripts) |
| `lender-response-classifier` | PM2 | VPS or Windows workstation | CEO-Agent (calls SunBiz scripts) |
| `claude-bridge-ping` | PM2 | VPS or Windows workstation | CEO-Agent |
| `claude-bridge` | PM2 | Windows workstation only | CEO-Agent |
| `bravo-telegram` | PM2 | Windows workstation only | CEO-Agent |
| `shop_out_sender` | Cron via bridge-ping | VPS or Windows | SunBiz-Agent |
| `renewal_reminder` | Cron via bridge-ping | VPS or Windows | SunBiz-Agent |
| `underwriting_orchestrator` | On-demand / cron | VPS or Windows | SunBiz-Agent |
| `daily_plan_generator` | Cron via bridge-ping | VPS or Windows | SunBiz-Agent |
| `follow_up_generator` | Cron via bridge-ping | VPS or Windows | SunBiz-Agent |
| `cold_outreach_runner` | Cron via bridge-ping | VPS or Windows | SunBiz-Agent |

---

## Key files by concern

| Concern | File |
|---|---|
| Daemon runtime config | `~/Business-Empire-Agent/ecosystem.config.js` |
| Outbound send chokepoint | `~/Business-Empire-Agent/scripts/send_gateway.py` |
| Exec safety gate | `~/Business-Empire-Agent/scripts/state/exec_guard.py` |
| Credential guard | `~/Business-Empire-Agent/scripts/state/secret_guard.py` |
| Event bus tail | `~/Business-Empire-Agent/scripts/core/event_router.py` |
| Bridge heartbeat + cron poller | `~/Business-Empire-Agent/bravo_cli/local_bridge.py` |
| SunBiz shop-out sender | `~/SunBiz-Agent/scripts/shop_out_sender.py` |
| SunBiz underwriting | `~/SunBiz-Agent/scripts/underwriting_orchestrator.py` |
| SunBiz drip/sequence | `~/SunBiz-Agent/scripts/sequence_runner.py` |
| Dashboard API routes | `~/APPS/oasis-command-center/app/api/` |
| Dashboard SunBiz pages | `~/APPS/oasis-command-center/app/t/sun/` |
