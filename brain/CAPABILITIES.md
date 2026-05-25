---
tags: [capabilities, tools]
---

# CAPABILITIES — Tool & Integration Registry (SunBiz V6.x)

> Complete inventory of what Solara can do. Last reviewed: 2026-05-25 (V6.x cognitive upgrade).
> Single-tenant deployment. All Supabase data scoped to `tenant_id = 'sunbiz'`.
> Counts are live — do not hardcode. For live truth: `python scripts/doctor.py --json`.
>
> **Verification footer:** Every command in this registry MUST resolve. Verified 2026-05-25
> against `scripts/` (SunBiz-local) and `~/Business-Empire-Agent/scripts/` (CEO-Agent substrate).
> Re-verify whenever you add or remove a script.

---

## Where Dashboard API Endpoints Live

> **IMPORTANT — read before calling any `/api/...` URL.**
>
> All `/api/...` routes referenced in this file and in `skills/` playbooks are routes served by the
> **OASIS Command Center dashboard** (repo: `CC90210/oasis-command-center`, deployed at
> https://agent-dashboard-sigma-eight.vercel.app). They are **NOT** served by this repo's local
> `scripts/api_server.py`, which only exposes `/health`, `/status`, `/sms/send`, and
> `/webhook/jotform`.
>
> Solara's bridge makes authenticated `fetch` calls into the dashboard's API surface; the dashboard
> then writes to Supabase, queues threads, and dispatches the 8 daemons in this repo.

---

## CEO-Agent V6 Substrate Touchpoints

Solara uses components of Bravo's V6 stack via sanctioned interfaces. These scripts live in
`~/Business-Empire-Agent/scripts/` (CEO-Agent) — NOT in this repo. Read from these; do not write
to CEO-Agent files directly.

| Component | Interface | Purpose |
|-----------|-----------|---------|
| **state_sync** | `python ~/Business-Empire-Agent/scripts/state/state_sync.py --note "<summary>"` | State sync dispatch — writes heartbeat + session log to `empire_state.db` |
| **state_manager** | `python ~/Business-Empire-Agent/scripts/state/state_manager.py {heartbeat,log,task,status}` | Programmatic V6 state mutations — heartbeats, session log entries, active task rows |
| **memory_retriever** | `python ~/Business-Empire-Agent/scripts/core/memory_retriever.py query "<question>"` | FTS5 index of all brain/memory/skills files — <10ms retrieval |
| **send_gateway** | `python ~/Business-Empire-Agent/scripts/integrations/send_gateway.py send --channel {email,sms} ...` | Enforces TCPA/CASL/cooldown/caps before any outbound send |
| **agent_inbox** | `python ~/Business-Empire-Agent/scripts/core/agent_inbox.py {list,post} --to {solara,helios,bravo}` | Cross-agent messaging — Solara → Helios for sales handoffs |
| **supabase_tool** | `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py {select,insert,update,upsert,rpc} <table>` | Tenant-scoped DB access (always passes `tenant_id=sunbiz`) |

---

## SunBiz-Specific Daemons

These scripts live in this repo's `scripts/` directory and are Solara's primary execution layer.
All are CLI-first; secrets read from `.env.agents`. All daemons follow the canonical
`once / loop / tail` subcommand pattern unless noted.

| Daemon / Script | Command | Purpose |
|----------------|---------|---------|
| **shop_out_sender** | `python scripts/shop_out_sender.py {once,loop,tail}` | Packages application + docs, routes to ranked lender(s), logs submission. `once` processes one batch and exits; `loop` runs continuously; `tail` prints recent log lines. |
| **sequence_runner** | `python scripts/sequence_runner.py {once,loop,tail} [--lead-id <id>] [--sequence <name>]` | Drip cadence engine — merchant follow-up sequences. |
| **lender_response_classifier** | `python scripts/lender_response_classifier.py {once,loop,tail}` | Parses lender portal responses → approved/declined/more-info-needed + reason code. |
| **renewal_reminder** | `python scripts/renewal_reminder.py {once,loop,tail} [--window 30] [--json]` | Finds funded deals within renewal window; outputs ranked list. |
| **follow_up_generator** | `python scripts/follow_up_generator.py {once,loop,tail} [--lead-id <id>]` | Generates next merchant touch (email/SMS) based on lifecycle stage. |
| **cold_outreach_runner** | `python scripts/cold_outreach_runner.py {once,loop,tail} [--dry-run] [--list <csv>]` | TCPA-gated cold outreach to imported leads (operator-initiated only). Always `--dry-run` first. |
| **daily_plan_generator** | `python scripts/daily_plan_generator.py {once,loop,tail} [--json]` | Assembles Jordan's call sheet + Solara's shop-out queue for the day. |
| **underwriting_orchestrator** | `python scripts/underwriting_orchestrator.py {once,loop,tail}` | Pre-screens application against lender appetite matrix before submission. |
| **sms_engine** | `python scripts/sms_engine.py {send,status,providers} ...` | Multi-provider SMS (Twilio primary, Telnyx/Plivo failover). Note: uses `send/status/providers`, NOT `once/loop/tail`. |
| **email_blast** | `python scripts/email_blast.py --template <name> --csv <path> --name <campaign> --subject "<line>" [--dry-run]` | Gmail SMTP campaign blast, thread-safe, CAN-SPAM compliant. Uses flags, not subcommands. |

**Daemon subcommand reference (`once / loop / tail`):**
- `once` — process one batch (or one tick) and exit. Use for on-demand runs and cron.
- `loop` — run continuously with a configurable `--interval` (seconds between ticks). PM2-managed.
- `tail` — print the last N log lines for observability. Does not invoke the daemon logic.

---

## Solara's Tool Palette (What Solara Can Use Directly)

Solara has access to these; Helios has a separate, outreach-focused palette.

| Tool | Purpose | Notes |
|------|---------|-------|
| `shop_out_sender.py` | Submit applications to lenders | Requires Ezra confirmation before `once` |
| `underwriting_orchestrator.py` | Pre-screen applications | Fully autonomous |
| `lender_response_classifier.py` | Parse lender responses | Fully autonomous |
| `renewal_reminder.py` | Scan renewal window | Fully autonomous |
| `daily_plan_generator.py` | Build daily brief | Fully autonomous |
| `follow_up_generator.py` | Draft next touch | Fully autonomous |
| `cold_outreach_runner.py` | Cold outreach (dry-run first) | Operator-initiated only |
| `sequence_runner.py` | Drip sequence engine | Fully autonomous |
| `sms_engine.py` | Single SMS send | CASL gate must pass first |
| `email_blast.py` | Campaign blast | CASL gate must pass first; `--dry-run` first |
| `~/Business-Empire-Agent/scripts/supabase_tool.py` | Read/write deal state, lender profiles, merchant records | Always pass `--tenant sunbiz`; script lives in CEO-Agent |
| `~/Business-Empire-Agent/scripts/send_gateway.py` | Compliant email/SMS send | Gateway enforces TCPA/CASL — do not bypass; script lives in CEO-Agent |
| `~/Business-Empire-Agent/scripts/core/agent_inbox.py` | Handoffs to Helios or messages to Bravo | Read freely; post requires confirmation; script lives in CEO-Agent |
| `~/Business-Empire-Agent/scripts/state/state_bridge.py` | Heartbeat to V6 substrate | Autonomous (session start/end); script lives in CEO-Agent |
| `~/Business-Empire-Agent/scripts/core/memory_retriever.py` | Search brain/memory files | Autonomous; script lives in CEO-Agent |

**What Solara does NOT use directly:**
- Raw `send_sms` without CASL gate — always routed through `send_gateway.py` (CEO-Agent).
- Raw bash subprocess calls in daemon-spawned code — use `safe_run()` from `_subprocess_helpers.py`.
- Helios-specific tools (outbound cold call scripts, meeting-setter sequences).

---

## MCP Servers

| Server | Purpose | Status |
|--------|---------|--------|
| **Playwright** | Browser automation, visual lender portal verification | Available |
| **Context7** | Live library documentation lookup | Available |
| **Memory** | Persistent knowledge graph | Available |
| **Sequential Thinking** | Multi-step reasoning | Available |

Note: Google Ads MCP and Meta Ads MCP are available as lead-gen sub-capability but are Helios/outreach lane tools.

---

## Supabase Project

| Project | Purpose |
|---------|---------|
| **sunbiz** (scoped under Bravo's project) | All deal state, lender profiles, merchant records, agent traces — all `tenant_id = 'sunbiz'` |

Tables used: `leads`, `applications`, `deals`, `offers`, `lenders`, `agent_traces`, `session_logs`, `memories`, `agent_state`, `sops`, `self_modification_log`, `renewal_pipeline`.

---

## MCA-Domain Tool Chain (End-to-End Flow)

```
Lead Intake (JotForm webhook → dashboard /api/leads → Supabase)
  ↓
Pre-Screen (underwriting_orchestrator.py once --deal-id <id>)
  ↓
Shop-Out (shop_out_sender.py once → lender_response_classifier.py once)
  ↓
Offer Presentation (follow_up_generator.py once → send_gateway.py send to merchant)
  ↓
Funded (dashboard /api/deals PATCH --status funded → daily_plan_generator.py)
  ↓
Renewal (renewal_reminder.py once → sequence_runner.py once renewal_sequence)
```

---

## Compliance Enforcement Points

| Gate | Enforced By | Blocks On |
|------|-------------|-----------|
| TCPA opt-in check | `send_gateway.py` (CEO-Agent) | SMS to any number without verified opt-in |
| CASL consent check | `send_gateway.py` (CEO-Agent) | Email to CA-based merchant without consent |
| CAN-SPAM footer | `email_blast.py` | Any email missing unsubscribe mechanism |
| Quiet hours | `send_gateway.py` (CEO-Agent) | Outbound outside 8am-9pm merchant local time |
| "Loan" language gate | Draft critic in `send_gateway.py` (CEO-Agent) | Any outbound using banned terminology |
| Stacking risk flag | `underwriting_orchestrator.py` | Submission when position count exceeds lender threshold |

## Obsidian Links
- [[brain/AGENTS]] | [[brain/AGENT_ROUTER]] | [[brain/INTENTS]]
- [[brain/SOUL]] | [[brain/STATE]]
