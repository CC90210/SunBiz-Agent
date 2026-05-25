# SunBiz Agent — Solara + Helios

> Bridge-side funding operations agent for Sun Biz Funding. Solara runs underwriting, shop-out, renewal, and follow-up. Helios drives the cold outreach and ghosted-deal revival. Together they power the Sun Biz Funding tenant in the OASIS Agent Command Center.

This repo is the bridge side of a three-repo stack. It owns SunBiz-specific Python daemons, SunBiz database migrations (042 through 069), Solara's cognitive substrate (`brain/`), and Solara's skills. The dashboard UI lives in `oasis-command-center`. The empire substrate (state DB, guards, retrieval, event bus) lives in `CEO-Agent`.

---

## What is in this repo

- **`scripts/`** — Python daemons, tooling, and utilities. Eight daemons own the SunBiz operator workflow; the rest are setup, diagnostics, and legacy ad tooling.
- **`database/`** — Nine migrations (042, 043, 044, 064–069) that create and evolve the SunBiz schema on the shared OASIS Supabase project.
- **`brain/`** — Solara's cognitive substrate: SOUL, CLIENT profile, CAPABILITIES, CHANGELOG, BRAIN_LOOP, STATE, USER.
- **`skills/`** — Operator-facing skill playbooks Solara can invoke.
- **`docs/`** — Operator and developer reference docs (VPS bringup, architecture, daemon playbook, migration history, quickstarts).
- **`dashboard/`** — Integration contract between this repo's hosted API and the Command Center.

## What is NOT in this repo

- **The dashboard UI** — lives in `oasis-command-center` at `~/APPS/oasis-command-center`. Never edit dashboard code here.
- **The empire substrate** — `state/empire_state.db`, `memory_retriever.py`, `exec_guard.py`, `secret_guard.py`, the event bus, and the cross-agent state sync all live in `CEO-Agent` (`~/Business-Empire-Agent`). This repo calls into that substrate; it does not duplicate it.
- **The PM2 runtime** — `ecosystem.config.js` lives in CEO-Agent. VPS deploys run `pm2 start ecosystem.config.js --only event-router,sequence-runner,lender-response-classifier,claude-bridge-ping` from the CEO-Agent directory.
- **`send_gateway.py`** — the empire-wide outbound chokepoint (CASL, cooldowns, daily caps, DNS reputation, critic, bounce circuit breaker). Lives in CEO-Agent. SunBiz daemons call it; they do not duplicate it.

---

## Quickstart — for Ezra

Five steps to get Solara running on a fresh machine.

**Step 1 — Clone**

```bash
git clone https://github.com/CC90210/SunBiz-Agent.git
cd SunBiz-Agent
```

**Step 2 — Install Python dependencies**

```bash
python3.12 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/setup.py
```

**Step 3 — Configure credentials**

```bash
cp .env.agents.template .env.agents
# Open .env.agents and fill in every value marked REQUIRED
```

The template groups every key by purpose and marks which ones are required vs optional. The minimum set for production: Supabase service-role key, Twilio credentials, Gmail app password, and the HMAC secret. See `docs/VPS_BRINGUP.md` for the complete credential guide.

**Step 4 — Doctor**

```bash
python scripts/doctor.py --json
```

Every check must show `"status": "ok"`. Fix anything that fails before continuing.

**Step 5 — Run**

```bash
# Start the hosted API (dashboard calls this)
python scripts/api_server.py

# Or: start a specific daemon manually for testing
python scripts/sequence_runner.py loop --interval 10
```

For the full VPS production bringup (PM2 + all daemons + migrations), see `docs/VPS_BRINGUP.md`.

---

## Quickstart — for a developer joining the stack

You need three repos, migrations applied, and PM2 running.

```bash
# 1. Clone all three repos
git clone https://github.com/CC90210/CEO-Agent.git          ~/Business-Empire-Agent
git clone https://github.com/CC90210/SunBiz-Agent.git        ~/SunBiz-Agent
git clone https://github.com/CC90210/oasis-command-center.git ~/APPS/oasis-command-center

# 2. Install deps in each
cd ~/Business-Empire-Agent && pip install -r requirements.txt
cd ~/SunBiz-Agent && pip install -r requirements.txt
cd ~/APPS/oasis-command-center && npm install

# 3. Apply migrations (in order, idempotent)
cd ~/SunBiz-Agent
for migration in 042 043 044 064 065 066 067 068 069; do
  python scripts/apply_migration.py database/${migration}_*.sql
done

# 4. Pair the bridge (follow the dashboard Devices page flow)
mkdir -p ~/.oasis && echo "<pairing-token>" > ~/.oasis/bridge_token

# 5. Start PM2 selective (VPS — never start bravo-telegram on the VPS)
cd ~/Business-Empire-Agent
pm2 start ecosystem.config.js --only event-router,sequence-runner,lender-response-classifier,claude-bridge-ping
pm2 save
```

Architecture, data flow, and troubleshooting: `docs/ARCHITECTURE.md`.

---

## What Solara does

Solara is the backend/admin agent for Sun Biz Funding's funding operations. Typical operator workflows she handles:

1. **Review today's call sheet** — pulls daily_plan_items ranked by priority, surfaces which leads need calls today and why.
2. **Run underwriting on an incoming application** — triggers the underwriting orchestrator (bank statement parsing, debt detection, sales angle generation, readiness score), presents the output as a funding recommendation.
3. **Shop out a deal** — queues per-lender email threads in `application_lender_threads`, attaches the operator-approved body and bank statements, fires via `shop_out_sender`.
4. **Monitor lender offers** — polls Gmail threads for lender replies, classifies them as approved / declined / info-requested via Claude Haiku, surfaces the result on the Applications page.
5. **Trigger the right drip sequence** — when a lead's stage changes, enrolls them in the matching sequence and fires step 1 via `send_gateway` (SMS or email, CASL-compliant, rate-limited).
6. **Push renewal campaigns** — identifies upcoming renewal candidates, drafts outreach, queues for operator approval before sending.
7. **Blast a cold list** — takes an uploaded CSV, creates a cold outreach campaign, runs step-by-step through NEPQ-style messaging with compliance gating.
8. **Log a manual follow-up** — accepts a natural-language note from Ezra, creates a `follow_up_tasks` row with the right due date and priority.
9. **Escalate stuck deals to Ezra** — surfaces applications idle for more than N days with a diagnosis and recommended action.
10. **Generate the daily plan** — each morning, `daily_plan_generator` reads the pipeline state and writes prioritized daily_plan_items for the operator.

## What Helios does

Helios is the outreach-side counterpart. He operates in the front-of-house lane while Solara protects the rails.

1. **Cold outreach cadences** — runs multi-step cold campaigns from imported lists using NEPQ-style discovery sequencing.
2. **Ghosted-deal revival** — identifies applications stuck in the pipeline, drafts revival messages with pattern-interrupt hooks, queues for send.
3. **Reply triage** — classifies inbound SMS/email replies, routes hot responses to Ezra immediately, queues warm ones for follow-up.
4. **NEPQ discovery questions** — generates tailored discovery scripts based on the merchant's industry, revenue band, and current position count.
5. **A/B sequence testing** — runs parallel outreach variants, surfaces which hooks get responses.

---

## Architecture overview

```
Ezra (operator)
    │
    ▼
OASIS Command Center  (oasis-command-center repo)
  Next.js 14 + Supabase  ←──→  Supabase (Postgres + RLS)
    │                                   │
    │  bridge API calls                 │  event bus (agent_events)
    ▼                                   │
CEO-Agent (Business-Empire-Agent repo)  │
  PM2 daemons: event-router,            │
  sequence-runner,                      │
  lender-response-classifier,           │
  claude-bridge-ping                    │
    │                                   │
    │  SunBiz-specific logic ───────────┘
    ▼
SunBiz-Agent (this repo)
  scripts/: shop_out_sender, renewal_reminder,
            underwriting_orchestrator, cold_outreach_runner,
            follow_up_generator, daily_plan_generator
  database/: migrations 042-069
  brain/: Solara's cognitive substrate
```

Three repos, one Supabase project, one PM2 runtime. The dashboard is the operator surface. The bridge (CEO-Agent PM2 daemons) is the execution layer. SunBiz-Agent is the business-logic layer for the Sun Biz Funding tenant.

---

## The 8 daemons

Each daemon runs inside the CEO-Agent PM2 ecosystem (on the operator's machine or VPS). SunBiz-Agent owns the Python source; CEO-Agent's `ecosystem.config.js` owns the runtime configuration.

| Daemon | Script | What it does |
|---|---|---|
| `shop_out_sender` | `scripts/shop_out_sender.py` | Drains `application_lender_threads` rows at `status='pending'`, atomically claims each as `sending`, fires the SMTP email to the lender, then marks `sent` or `error`. Cron-driven via the bridge-ping poller (`manifest_key=shop_out_sender_loop`). |
| `sequence_runner` | `scripts/sequence_runner.py` | Two-phase loop: enrollment (matches `agent_events` stage-change rows against `drip_sequences`) then execution (fires due `sequence_state` rows through `send_gateway`). 10s tick. All sends go through the CASL chokepoint. |
| `lender_response_classifier` | `scripts/lender_response_classifier.py` | Polls Gmail for replies on active lender threads, classifies each reply as `approved / declined / info_requested / unclear` via Claude Haiku, updates `application_lender_threads`. Also SLA-sweeps threads overdue per `lender.sla_response_days`. 5-min tick. |
| `renewal_reminder` | `scripts/renewal_reminder.py` | Identifies funded deals approaching renewal windows, drafts renewal outreach, queues for operator approval. Sends Telegram alert to Ezra when a renewal is due within the configured window. |
| `follow_up_generator` | `scripts/follow_up_generator.py` | Reads the `follow_up_tasks` queue, generates contextual follow-up messages based on application history and lender response, surfaces draft to operator before sending. |
| `cold_outreach_runner` | `scripts/cold_outreach_runner.py` | Works through `cold_outreach_campaigns` and `cold_outreach_recipients`, fires each step of the NEPQ-style sequence, respects campaign-level daily caps and CASL consent. |
| `daily_plan_generator` | `scripts/daily_plan_generator.py` | Runs each morning, reads the full pipeline state, writes prioritized `daily_plan_items` for the operator (calls to make, follow-ups due, renewals approaching, stuck applications). |
| `underwriting_orchestrator` | `scripts/underwriting_orchestrator.py` | Orchestrates the three-step underwriting pipeline: (1) `statement_parser` extracts metrics from bank statement PDFs via Claude vision, (2) `debt_detector` identifies existing MCA positions, (3) `sales_angle` generates the lender pitch. Writes results to `application_underwriting`. |

---

## Database migrations (042–069)

Nine migrations ship in this repo, applied in numeric order. All are idempotent and transactional.

| Migration | Purpose |
|---|---|
| `042_tenant_forms.sql` | First-party intake forms replacing JotForm: `forms` (definitions) + `form_submissions` (one row per step completion). Personalized per-lead links via HMAC token. |
| `043_drip_sequences.sql` | Drip campaign sequence engine: `drip_sequences` (definitions) + `sequence_state` (in-flight rows). Sequences trigger on lead/application stage changes via `agent_events`. |
| `044_lender_shopout.sql` | Extended lender catalog (match-fitness fields: `min_revenue`, `max_funded`, `fico_floor`) + `application_lender_threads` table tracking per-lender email status. |
| `064_sunbiz_restructure.sql` | Jordan/Oasis 2026-05 restructure: collapses lead stages from 8 to 5, application statuses from 17 to 9. Pure data remaps + new `offers` entity. Scoped to `tenant_slug='sun'` only. |
| `065_shop_out_thread_send_context.sql` | Adds `body_template` and `attachments` columns to `application_lender_threads` so the bridge-side sender faithfully reproduces what the operator approved instead of falling back to defaults. |
| `066_sunbiz_remap_stuck_records.sql` | Fixes migration 064's tenant-resolution bug (queried wrong slug), remaps the 10 application rows still carrying retired status values, and grants Ezra the `owner` role. |
| `067_sunbiz_stage_remap_fix.sql` | Second-pass cleanup for 064's no-op: re-resolves tenant via the correct `custom_fields.command_center_profile_slug` path, re-runs application and lead stage remaps idempotently. |
| `068_shop_out_sender_claim_state.sql` | Adds `sending` to the `application_lender_threads` status constraint (atomic claim state) + `send_interaction_id` column to prevent ghost sends on crash-restart. |
| `069_sunbiz_meeting2_expansion.sql` | Second-meeting expansion: 14 new tables for underwriting, follow-up machine, daily planning, cold outreach, shop-out warnings, lender intelligence, personalized links, and agent memory notes. |

### The 14 tables added by migration 069

| Table | Purpose |
|---|---|
| `application_underwriting` | Append-only underwriting run output: parser metrics, debt analysis, sales angle, readiness score. |
| `follow_up_tasks` | Follow-Up Machine queue: due-date, priority, assigned agent, completion state. |
| `daily_plan_items` | Per-day prioritized action queue surface for the operator dashboard. |
| `cold_lead_lists` | Imported cold lists (separate from the warm pipeline). |
| `cold_leads` | Members of a cold list; tracks consent, status, and per-lead delivery history. |
| `cold_outreach_campaigns` | Multi-channel blast campaign definitions (sequence of messages, channels, timing). |
| `cold_outreach_recipients` | Per-recipient delivery state within a campaign. |
| `shop_out_warnings` | Severity-flagged warnings raised during shop-out (e.g. stacking risk), with operator override notes. |
| `known_funding_companies` | MCA company registry for the underwriting debt-detector (name variants, typical terms). |
| `offer_sources` | Offer attribution tracking: email vs portal vs manual entry. |
| `email_thread_monitors` | Cursor state per tenant for the Gmail scanner daemon. |
| `lender_feedback` | Intelligence learning tuples: lender decision + deal profile pairs for improving match fitness. |
| `personalized_form_links` | Token-backed per-lead form links with expiry and audit trail. |
| `agent_memory_notes` | Tenant/lead-scoped operator notes that Solara reads as context when working a deal. |

---

## Production status

**V6.8 cognitive substrate — shipped.** Solara runs on the same V6.8 substrate as Bravo (SOUL, BRAIN_LOOP, skill governance, capability graph conventions). The second-meeting expansion (migration 069 + all 8 daemons) is also shipped.

**Awaiting before full production:**

- Cron seeds in the dashboard for `daily_plan_generator` and `renewal_reminder` (cron jobs need to be seeded via the tenant manifest's cron_jobs array or the dashboard's automations page)
- VPS bringup (see `docs/VPS_BRINGUP.md` — the runbook is complete, waiting on Ezra to provision the VPS)
- Ezra signoff on the day-1 workflow walkthrough

---

## Where to go next

| What you need | Where to look |
|---|---|
| Solara's identity and values | `brain/SOUL.md` |
| What Solara can do (full capability list) | `brain/CAPABILITIES.md` |
| Skills and operator playbooks | `skills/` |
| "Get the most out of Solara" | `MAXIMIZATION_GUIDE.md` |
| VPS bringup (production deploy) | `docs/VPS_BRINGUP.md` |
| System architecture (3-repo split) | `docs/ARCHITECTURE.md` |
| Per-daemon ops reference | `docs/DAEMON_PLAYBOOK.md` |
| Migration history (one-para per migration) | `docs/MIGRATION_HISTORY.md` |
| Solara cheat sheet | `docs/SOLARA_QUICKSTART.md` |
| Helios cheat sheet | `docs/HELIOS_QUICKSTART.md` |
| Ezra's onboarding manual | `docs/UNIFIED_ONBOARDING_MANUAL.md` |

---

## License + contact

[MIT licensed](LICENSE) · Built by [Conaugh McKenna](https://oasisai.work) and [OASIS AI Solutions](https://oasisai.work)

Issues: https://github.com/CC90210/SunBiz-Agent/issues
