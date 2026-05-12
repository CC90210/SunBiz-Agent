# Sun Biz Agent (Solara + Suga Sean)

> A digital-employee operating stack for Sun Biz Funding. Solara is the lead digital employee inside the client's Command Center. Suga Sean keeps outreach moving. Local-first, audit-everything, zero silent magic.

```bash
# Mac / Linux
curl -fsSL https://raw.githubusercontent.com/CC90210/CEO-Agent/main/install.sh | bash
```

```powershell
# Windows
irm https://raw.githubusercontent.com/CC90210/CEO-Agent/main/install.ps1 | iex
```

After bootstrap:

```bash
bravo setup --profile=sunbiz
```

That setup path now onboards Solara like a digital employee: it pairs the Command Center, walks the operator through JotForm and Text Torrent credentials in plain English, sets up Solara's Local Brain, and provisions the Sun Biz workspace with both agents enabled.

---

## What the client experiences

Sun Biz Agent runs as a two-agent stack inside the OASIS Agent Command Center, but the client should experience it as one clean digital employee handoff:

- **Conversational onboarding** through `bravo setup --profile=sunbiz`, framed as onboarding Solara instead of installing infrastructure.
- **Plain-English credential handoff** for JotForm and Text Torrent, followed by a live pulse check once credentials are saved.
- **Welcome to your Command Center** as the first post-pairing landing page.
- **Unified Onboarding Manual** front-and-center so the client knows how to work with Solara on day one.
- **Proactive Solara greeting** in chat: once JotForm is healthy, Solara opens by saying she is connected and ready to process the funding pipeline.
- **Hosted dashboard transport** via a real FastAPI runtime in this repo, with SMS, email, and JotForm intake behind the scenes.

This repo is now honest about what ships today, what the client should see, and what is still Phase 2.

---

## Behind the scenes

This build is meant to run two agents in tandem:

- **Solara ("Solar")** owns the backend/admin lane: operational oversight, system-of-record discipline, SMS transport, and the Sun Biz runtime contract.
- **Suga Sean** owns the outreach lane: text blasts, email follow-up, reply triage, and meeting-setting.

The split matters because backend ops and front-of-house outreach move at different speeds. Solara protects the rails. Suga Sean keeps pipeline motion high. Client-facing copy should still treat Solara as the primary digital employee and keep technical split details in the background unless the operator needs them.

---

## Local Brain

The setup wizard asks one important question:

> **Where should Solara's Local Brain live?**
>
> 1. **Local Machine (Recommended)** - Solara's Local Brain stays on the operator machine.
> 2. **Cloud (OASIS-hosted Supabase)** - managed multi-tenant hosting.

For funding operations, local is still the recommended default. The shared dashboard should know your machine is alive. It should not need raw merchant records living in a third-party cloud unless the operator explicitly chooses that tradeoff.

Internal note for builders: the current adapter key is still `turso` / libSQL in the shared OASIS runtime. Client-facing copy should say **Local Brain**.

---

## The Digital Employee onboarding

This is the operator-facing path for the actual client setup.

### Step 1 - Bootstrap

```bash
curl -fsSL https://raw.githubusercontent.com/CC90210/CEO-Agent/main/install.sh | bash
```

This installs the shared runtime, Python, Node, Git, and the `bravo` shim if needed.

### Step 2 - Launch Solara's onboarding

```bash
bravo setup --profile=sunbiz
```

Important setup answers:

| Step | What it asks | What to use |
|---|---|---|
| Identity | Name + email | The client operator's real business identity |
| Brand | Business context | **Sun Biz Funding** |
| Text Torrent | SMS credentials | Live Twilio SID, auth token, and sending number |
| Local Brain | Local or cloud | **Local** for production funding ops |
| Dashboard pairing | 9-char code | Generated from `/settings/devices` |

Expected wizard moments:

- "Onboarding your new agent, Solara..."
- "Setting up Solara's Local Brain..."
- "Checking Solara's pulse..."
- "Solara is connected to JotForm. She is ready to receive leads."

### Step 3 - Pair the Command Center

The wizard opens the Devices page, the operator mints the pairing code, and the CLI stores the bridge token after `/api/auth/pair-code/redeem`.

### Step 4 - Verify the shared runtime

```bash
bravo doctor
```

That checks the shared OASIS install.

### Step 5 - Pulse check Solara's tools

Inside the cloned `SunBiz-Agent` repo:

```bash
python scripts/setup.py
python scripts/doctor.py --deep
python scripts/api_server.py
```

`setup.py` installs the repo dependencies. `doctor.py` verifies the Sun Biz runtime. `api_server.py` starts the hosted API the dashboard contract expects.

When the shared Command Center is live, the client should land on:

- `Welcome to your Command Center`
- `Unified Onboarding Manual`
- Solara's chat welcome
- JotForm, Text Torrent, and Local Brain health states

---

## Repo-local production commands

Use these when operating the dedicated Sun Biz runtime directly:

```bash
python scripts/setup.py
python scripts/doctor.py
python scripts/doctor.py --deep
python scripts/api_server.py
python scripts/sms_engine.py status --json
```

`bravo doctor` is the shared-platform health check. `python scripts/doctor.py` is the SunBiz-Agent health check.

---

## What this repo owns

Sun Biz Agent is a client product, separate from OASIS's internal CEO agent. This repo contains:

- **Agent identities and routing contract** in `brain/`
- **Backend runtime** in `scripts/` - setup, doctor, hosted API, SMS engine, email blast engine, JotForm tracker
- **Dashboard integration contract** in `dashboard/`
- **Dual-agent product docs** in `docs/`
- **Skills and operating playbooks** in `skills/`

For the client-facing Command Center experience, see:

- [`docs/UNIFIED_ONBOARDING_MANUAL.md`](docs/UNIFIED_ONBOARDING_MANUAL.md)
- [`dashboard/INTEGRATION.md`](dashboard/INTEGRATION.md)

This repo does **not** contain the full shared OASIS substrate. The command center shell, global wizard, pair-code flow, shared state substrate, and shared multi-tenant dashboard live in [Business-Empire-Agent](https://github.com/CC90210/CEO-Agent).

---

## How this fits the OASIS substrate

The Sun Biz runtime is the agent. OASIS is the operating system around it. The integration points that are live now are:

1. **Provisioning** - `bravo setup --profile=sunbiz` provisions the Sun workspace and enables both `sunbiz` and `suga_sean`.
2. **Transport** - `scripts/api_server.py` exposes the hosted API the shared command center calls.
3. **Events** - `sms_engine.py` emits `SUNBIZ_SMS_SENT`, and the webhook route can emit `SUNBIZ_LEAD_SOURCED`, when the shared Business-Empire-Agent substrate is present beside this repo.

The deeper business-data adapter and full deal-lifecycle ledger remain roadmap work, not hidden assumptions.

---

## Hosted agent contract

When the Sun Biz operator runs in dedicated mode, this repo now exposes:

```text
GET  /health
GET  /status
POST /sms/send
POST /webhook/jotform
```

Dashboard-originated SMS requests look like:

```json
{
  "to": "+14165551212",
  "body": "Message body",
  "tenant_slug": "sun",
  "client_profile": "sun"
}
```

If `SUNBIZ_AGENT_HMAC_SECRET` is configured, requests are validated with:

```text
x-oasis-timestamp
x-oasis-signature
x-oasis-tenant-slug
x-oasis-client-profile
```

Signature format:

- HMAC-SHA256 over `{timestamp}.{raw_json_body}`

Replay protection:

- requests older than 60 seconds are rejected

Launch locally with:

```bash
python scripts/api_server.py
```

---

## Production status

### Shipped now

- Shared Command Center profile (`sun` shell + dual-agent workspace)
- Dashboard pairing flow
- Repo-local setup script
- Repo-local runtime doctor
- Hosted FastAPI runtime
- Twilio-backed SMS engine
- Gmail outreach engine
- JotForm lead tracker and webhook capture
- Dual-agent contract for Solara + Suga Sean

### Still Phase 2 / roadmap

- Turso business-data adapter for Sun-specific records
- Telnyx + Plivo SMS failover
- Full deal-lifecycle ledger (`applications -> offers -> funded deals -> renewals`)
- Commission / P&L tables for the Solara backend lane

---

## Support

- Unified onboarding manual: [`docs/UNIFIED_ONBOARDING_MANUAL.md`](docs/UNIFIED_ONBOARDING_MANUAL.md)
- Operator playbook: `/playbook/05-customer-onboarding-script`
- Deployment runbook: `/playbook/06-sunbiz-runbook`
- Event contract: [`brain/EVENT_BUS_CONTRACT.md`](https://github.com/CC90210/CEO-Agent/blob/main/brain/EVENT_BUS_CONTRACT.md)
- Issues: https://github.com/CC90210/SunBiz-Agent/issues

[MIT licensed](LICENSE) · Built by [Conaugh McKenna](https://oasisai.work) and OASIS AI Solutions
