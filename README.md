# Sun Biz Agent (Solara + Suga Sean)

> A dual-agent operating stack for Sun Biz Funding. Solara runs admin operations in the backend; Suga Sean runs outbound text blasts, email outreach, and meeting-setting in the client-facing lane. Local-first, audit-everything, zero data leaving your machine.

```bash
# Mac / Linux (one-liner)
curl -fsSL https://raw.githubusercontent.com/CC90210/CEO-Agent/main/install.sh | bash
```

```powershell
# Windows
irm https://raw.githubusercontent.com/CC90210/CEO-Agent/main/install.ps1 | iex
```

After the bootstrap finishes:

```bash
bravo setup --profile=sunbiz
```

One command. Twelve minutes. The wizard asks where your data should live, opens your dashboard to claim a pair code, and hands you a Sun Biz workspace with two cooperating agents: Solara for backend ops and Suga Sean for outreach execution.

---

## What you get (V6.2)

**Sun Biz Agent** works as a two-agent stack inside the **OASIS Agent Command Center** — a dashboard rendered in a "Sun Biz Funding" shell with its own sidebar, branding, and routes. From day one you can:

- **Run the morning lead review** — Solara ranks today's leads by recency × status × renewal proximity and tells you who to call first, in what order, and why.
- **Send compliant SMS at scale** — Twilio (Phase 1), Telnyx + Plivo failover (Phase 2). Every message ships with "Reply STOP to unsubscribe" hard-coded. Opt-out is enforced at the engine layer — Solara refuses to send to revoked contacts even if you ask.
- **Run outbound follow-up and meeting-setting** — Suga Sean handles text blast sequencing, email outreach, reply triage, and booking flow handoff so sales follow-up is not trapped in the ops queue.
- **Track every application end-to-end** — JotForm intake → lender assignment → offer presentation → funded deal → renewal scheduler. Each step emits a `SUNBIZ_*` event into the cross-agent bus so the dashboard updates live.
- **See real commissions** — funded deals book commission rows the moment money hits. The dashboard renders P&L without you exporting a single CSV.
- **Invite your team** — owner generates a single-use invite link from `/team`. Loan officers, processors, and read-only viewers each get role-scoped access. Owner machine pairings are trigger-protected; an employee cannot revoke them.

---

## The two-agent stack

This build is meant to run **two different agents that work in tandem**:

- **Solara ("Solar")** — the backend/admin operator. Owns lead review, lender fit, application flow, funded deals, renewals, commissions, and compliance rails.
- **Suga Sean** — the front-of-house outreach operator. Owns text blasts, email follow-up, response handling, and meeting-setting.

The split matters because ops and outreach move at different speeds. Solara protects the record system; Suga Sean keeps pipeline motion high without muddying the funding ledger.

---

## Data sovereignty — the choice that actually matters

The setup wizard asks you one question that matters more than any API key:

> **Where should your client data live?**
>
> 1. **Local Machine (Recommended)** — libSQL file at `~/.bravo/sunbiz.db` on this device. Loan applications, merchant tax IDs, bank-statement uploads, renewal commissions — never leave your hardware.
> 2. **Cloud (OASIS-hosted Supabase)** — managed multi-tenant, RLS-isolated, OASIS-managed backups.

For funding ops, **always pick Local**. The compliance posture is cleaner — if a merchant's lawyer ever asks where their data is, the answer is *"on the broker's premises,"* not *"on a third-party cloud."*

OASIS reads a **pulse** from your machine (a heartbeat that tells us your agent is alive and how it's performing). OASIS cannot read your loan data. That separation is enforced at the schema layer: shared substrate writes to Supabase; tenant business data writes to your libSQL file.

If your Mac Mini ever drops offline, the dashboard tells you within 15 minutes. Nightly Time Machine handles backup. A one-time SQL export-import migrates Local ↔ Cloud if you ever change your mind.

---

## The Mac Mini onboarding (12 minutes)

This is the canonical playbook your OASIS operator will walk you through on the kickoff call. Here it is in writing so you can re-run any step solo.

### Step 1 — Bootstrap (90 seconds)

```bash
curl -fsSL https://raw.githubusercontent.com/CC90210/CEO-Agent/main/install.sh | bash
```

This clones the agent runtime, installs Python 3.10+ / Node 18+ / Git if missing, builds a virtualenv, and drops a `bravo` shim onto your PATH.

### Step 2 — Launch the wizard with the SunBiz profile preselected

```bash
bravo setup --profile=sunbiz
```

The wizard walks ~15 steps. The ones that matter for you:

| Step | What it asks | What to type |
|---|---|---|
| Identity | Your full name + email | The email you used on the agreement. |
| Business context | Brand name | **Sun Biz Funding** (exact spelling — this brand string is what routes you to the Sun shell). |
| AI keys | Anthropic / OpenAI | OASIS supplies these on the shared tier; you supply them on dedicated. |
| Stripe | Stripe secret key | From your Stripe dashboard → API keys → Restricted, scoped to read-only. |
| Twilio | Account SID + auth token + sender number | Your existing Twilio account or one OASIS provisioned for you. Confirm the number is **A2P 10DLC registered** (US clients only — unregistered numbers get throttled). |
| **Data sovereignty** | Local libSQL or Cloud Supabase | **Local.** Non-negotiable for funding ops. |
| **Dashboard pairing** | Paste 9-char code | See Step 3. |

### Step 3 — Dashboard pairing (60 seconds)

The wizard auto-opens your browser to your dashboard's `/settings/devices`. You'll see a button: **"Install Claude Code CLI bridge"**.

1. Click it. The dashboard mints a single-use 9-character code (`XXX-XXX-XXX`, 15-minute TTL).
2. Copy the code. Paste it back into the terminal where the wizard is waiting.
3. The wizard exchanges the code via `/api/auth/pair-code/redeem`, saves a long-lived bridge token to `~/.oasis/bridge_token`, and prints "Bridge token saved."

If the browser doesn't auto-open (headless install, locked-down kiosk), the wizard prints the URL — visit it manually. Set `BRAVO_NO_BROWSER=1` to disable the auto-open entirely.

### Step 4 — Verify (30 seconds)

```bash
bravo doctor
```

Exit code 0 + verdict `HEALTHY` means you're shipped. Anything else, the doctor names the missing piece (most often a Twilio config or an unverified A2P registration) and you fix it inline.

### Step 5 — First chat

Open your dashboard. Click **Agents** in the sidebar. You should see both Solara and Suga Sean available in the workspace switcher. Start with:

> *Show me the leads you'd contact today and tell me why.*

Solara should name specific leads from your CRM, rank them by some combination of recency / status / renewal proximity, and explain the call-order. If the response is vague — *"I would prioritize the most promising leads"* — your data import didn't land; call OASIS support.

---

## What this repo owns

Sun Biz Agent is a **client product** — separate from OASIS's internal CEO agent. This repo contains:

- **Agent identities + routing contract** (`brain/`) — Solara's backend role, the tandem-agent operating model, and Sun Biz-specific rules
- **Capability registry** (`brain/CAPABILITIES.md`) — every skill + script + integration this agent knows about
- **Backend runtime** (`scripts/`) — SMS engine, funding intel, deal tracker, renewal scanner, email blast
- **Dashboard integration contract** (`dashboard/`) — tenant manifest, tandem-agent contract, SMS HMAC contract, event names
- **Skills** (`skills/`) — operator playbooks the agent loads on demand

This repo does **not** contain:
- The OASIS V6 substrate (state DB, event bus, retrieval index, guard hooks). That lives in [Business-Empire-Agent](https://github.com/CC90210/CEO-Agent) and is the canonical source — Solara consumes it via path lookups, not duplication.
- The Command Center dashboard chrome (sidebar, agent registry, multi-tenant auth). Same — that's a shared multi-tenant surface in BEA.

---

## V6 architecture (how this fits the OASIS substrate)

The Sun Biz Agent runtime is the *agent*. The OASIS substrate is the *operating system*. Three concrete touchpoints:

1. **State** — Solara heartbeats every 15 seconds via `scripts/state_bridge.py` into the shared V6 state DB at `<BEA>/state/empire_state.db` under `agent="sunbiz"`. The dashboard's `/agents` page reads this and the `state_api:8500/status` endpoint.

2. **Events** — Solara emits the `SUNBIZ_*` family into the cross-agent event bus:
   - `SUNBIZ_LEAD_SOURCED` — JotForm / import / manual
   - `SUNBIZ_SMS_SENT` — payload includes sha256-truncated `to_hash`, never raw phone
   - `SUNBIZ_APPLICATION_SUBMITTED`, `SUNBIZ_OFFER_PRESENTED`, `SUNBIZ_DEAL_FUNDED`
   - `SUNBIZ_RENEWAL_DUE` — cron-driven, 30-day window
   - `SUNBIZ_COMMISSION_BOOKED`, `SUNBIZ_EMAIL_BLAST_DISPATCHED`, `SUNBIZ_SESSION_LOG_APPENDED`

3. **Data** — when the operator picks Local libSQL, the dashboard's `lib/turso-queries.ts` reads `daily_plans`, `leads`, `pipelineBreakdown`, and `streak` from the local file. When they pick Cloud, the same queries hit Supabase. The dispatch is env-driven (`EMPIRE_DATA_BACKEND=turso_local`), set during the wizard's data-sovereignty step.

Full spec: [`brain/AGENTS.md` §19](https://github.com/CC90210/CEO-Agent/blob/main/brain/AGENTS.md) in Business-Empire-Agent.

---

## Hosted agent contract

When the Sun Biz operator runs in dedicated mode, the agent exposes a FastAPI service that the dashboard talks to via HMAC.

```text
GET  /health
GET  /status
POST /sms/send
POST /webhook/jotform
```

SMS requests are sent from the Command Center with:

```json
{
  "to": "+14165551212",
  "body": "Message body",
  "tenant_slug": "sun",
  "client_profile": "sun"
}
```

If `SUNBIZ_AGENT_HMAC_SECRET` is configured, every request is signed:

```text
x-oasis-timestamp
x-oasis-signature: HMAC-SHA256("{timestamp}.{raw_json_body}")
x-oasis-tenant-slug
x-oasis-client-profile
```

Replay protection: timestamps older than 60 seconds are rejected.

---

## Demo mode

The Command Center can show a safe Sun Biz demo *before* a real client account exists. Useful for prospect calls.

1. OASIS operator logs into the Command Center.
2. Open `/demo/sun`.
3. Shell switches into Sun Biz demo mode with sample leads, renewals, SMS history.
4. Sidebar shows a demo banner with an exit link.

Demo mode does not mutate OASIS's profile, does not show OASIS tenant data, and live SMS sends stay disabled.

---

## Production status (V6.2 Apex)

- ✅ Shared Command Center profile (`sun` shell + SUN_NAV sidebar)
- ✅ Local SMS engine (Twilio Phase 1)
- ✅ Demo mode (cookie-driven, no tenant mutation)
- ✅ Dashboard pairing flow (9-char pair codes, 15-min TTL, single-use)
- ✅ Data sovereignty wizard step (Local libSQL recommended)
- ✅ Multi-user team access (invites + roles + owner-pairing protection)
- ✅ Turso adapters wired for `getTodayPlan`, `recentLeads`, `pipelineBreakdown`, `getStreak`
- ✅ Verbatim customer-onboarding script + 5-phase deployment runbook (`/playbook`)
- ⏳ Hosted FastAPI service (Phase 2)
- ⏳ Turso schema bootstrap (`bravo db init --backend=turso`)
- ⏳ Telnyx + Plivo SMS failover (Phase 2)
- ⏳ `funded_deals` table (migration 041, unblocks renewals + P&L Turso reads)

---

## Support

- Operator playbook (verbatim): `/playbook/05-customer-onboarding-script` on your dashboard
- Deployment runbook: `/playbook/06-sunbiz-runbook`
- Architecture spec: [`brain/AGENTS.md` §19](https://github.com/CC90210/CEO-Agent/blob/main/brain/AGENTS.md) in Business-Empire-Agent
- Event contract: [`brain/EVENT_BUS_CONTRACT.md`](https://github.com/CC90210/CEO-Agent/blob/main/brain/EVENT_BUS_CONTRACT.md) in Business-Empire-Agent
- Issues: https://github.com/CC90210/SunBiz-Agent/issues

[MIT licensed](LICENSE) · Built by [Conaugh McKenna](https://oasisai.work) (CC) — founder, [OASIS AI Solutions](https://oasisai.work)
