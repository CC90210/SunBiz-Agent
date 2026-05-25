---
tags: [capabilities, tools]
---

# CAPABILITIES — Tool & Integration Registry (SunBiz V6.x)

> Complete inventory of what Solara can do. Last reviewed: 2026-05-25 (V6.x cognitive upgrade).
> Single-tenant deployment. All Supabase data scoped to `tenant_id = 'sunbiz'`.
> Counts are live — do not hardcode. For live truth: `python scripts/doctor.py --json`.

---

## CEO-Agent V6 Substrate Touchpoints

Solara uses components of Bravo's V6 stack via sanctioned interfaces. Read from these; do not write to CEO-Agent files directly.

| Component | Interface | Purpose |
|-----------|-----------|---------|
| **state_bridge** | `python scripts/state_bridge.py {status,heartbeat,sync}` | Heartbeats to `empire_state.db`; emits `SUNBIZ_*` events to `agent_events` bus |
| **memory_retriever** | `python scripts/memory_retriever.py query "<question>"` | FTS5 index of all brain/memory/skills files — <10ms retrieval |
| **send_gateway** | `python scripts/send_gateway.py send --channel {email,sms} ...` | Enforces TCPA/CASL/cooldown/caps before any outbound send |
| **agent_inbox** | `python scripts/agent_inbox.py {list,post} --to {solara,helios,bravo}` | Cross-agent messaging — Solara → Helios for sales handoffs |
| **supabase_tool** | `python scripts/supabase_tool.py {select,insert,update,upsert,rpc} <table>` | Tenant-scoped DB access (always passes `tenant_id=sunbiz`) |

---

## SunBiz-Specific Daemons

These scripts are Solara's primary execution layer. All are CLI-first; secrets read from `.env.agents`.

| Daemon / Script | Command | Purpose |
|----------------|---------|---------|
| **shop_out_sender** | `python scripts/shop_out_sender.py {send,status,retry} --deal-id <id>` | Packages application + docs, routes to ranked lender(s), logs submission |
| **sequence_runner** | `python scripts/sequence_runner.py {start,pause,resume} --lead-id <id> --sequence <name>` | Drip cadence engine — merchant follow-up sequences |
| **lender_response_classifier** | `python scripts/lender_response_classifier.py classify --deal-id <id> --response "<text>"` | Parses lender portal responses → approved/declined/more-info-needed + reason code |
| **renewal_reminder** | `python scripts/renewal_reminder.py scan --window 30 --json` | Finds funded deals within 30-day renewal window; outputs ranked list |
| **follow_up_generator** | `python scripts/follow_up_generator.py draft --lead-id <id> --context "<context>"` | Generates next merchant touch (email/SMS) based on lifecycle stage |
| **cold_outreach_runner** | `python scripts/cold_outreach_runner.py {dry-run,send} --list <csv>` | TCPA-gated cold outreach to imported leads (operator-initiated only) |
| **daily_plan_generator** | `python scripts/daily_plan_generator.py run --date today --json` | Assembles Jordan's call sheet + Solara's shop-out queue for the day |
| **underwriting_orchestrator** | `python scripts/underwriting_orchestrator.py score --deal-id <id>` | Pre-screens application against lender appetite matrix before submission |
| **deal_tracker** | `python scripts/deal_tracker.py {list,update,add} --status <status>` | CRUD for deal lifecycle (lead→funded→closed) |
| **funding_intel** | `python scripts/funding_intel.py {factor-rate,commission,tar-band} --deal-id <id>` | Factor rate lookup, commission math, TAR-band classification |
| **sms_engine** | `python scripts/sms_engine.py {send,status,blast} ...` | Multi-provider SMS (Twilio primary, Telnyx/Plivo failover) |
| **email_blast** | `python scripts/email_blast.py {send,preview,status} ...` | Gmail SMTP, thread-safe, CAN-SPAM compliant |

---

## Solara's Tool Palette (What Solara Can Use Directly)

Solara has access to these; Helios has a separate, outreach-focused palette.

| Tool | Purpose | Notes |
|------|---------|-------|
| `supabase_tool.py` | Read/write deal state, lender profiles, merchant records | Always pass `--tenant sunbiz` |
| `shop_out_sender.py` | Submit applications to lenders | Requires Ezra confirmation before send |
| `underwriting_orchestrator.py` | Pre-screen applications | Fully autonomous |
| `lender_response_classifier.py` | Parse lender responses | Fully autonomous |
| `renewal_reminder.py` | Scan renewal window | Fully autonomous |
| `daily_plan_generator.py` | Build daily brief | Fully autonomous |
| `funding_intel.py` | Factor rate / commission math | Fully autonomous |
| `deal_tracker.py` | Update deal state | Requires confirmation for funded-deal marking |
| `send_gateway.py` | Compliant email/SMS send | Gateway enforces TCPA/CASL — do not bypass |
| `agent_inbox.py` | Handoffs to Helios or messages to Bravo | Read freely; post requires confirmation |
| `state_bridge.py` | Heartbeat to V6 substrate | Autonomous (session start/end) |
| `memory_retriever.py` | Search brain/memory files | Autonomous |

**What Solara does NOT use directly:**
- Raw `send_sms` without TCPA gate — always routed through `send_gateway.py`.
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
Lead Intake (JotForm webhook → deal_tracker add)
  ↓
Pre-Screen (underwriting_orchestrator score)
  ↓
Shop-Out (shop_out_sender send → lender_response_classifier classify)
  ↓
Offer Presentation (follow_up_generator draft → send_gateway send to merchant)
  ↓
Funded (deal_tracker update --status funded → funding_intel commission)
  ↓
Renewal (renewal_reminder scan → sequence_runner start renewal_sequence)
```

---

## Compliance Enforcement Points

| Gate | Enforced By | Blocks On |
|------|-------------|-----------|
| TCPA opt-in check | `send_gateway.py` | SMS to any number without verified opt-in |
| CASL consent check | `send_gateway.py` | Email to CA-based merchant without consent |
| CAN-SPAM footer | `email_blast.py` | Any email missing unsubscribe mechanism |
| Quiet hours | `send_gateway.py` | Outbound outside 8am-9pm merchant local time |
| "Loan" language gate | Draft critic in `send_gateway.py` | Any outbound using banned terminology |
| Stacking risk flag | `underwriting_orchestrator.py` | Submission when position count exceeds lender threshold |

## Obsidian Links
- [[brain/AGENTS]] | [[brain/AGENT_ROUTER]] | [[brain/INTENTS]]
- [[brain/SOUL]] | [[brain/STATE]]
