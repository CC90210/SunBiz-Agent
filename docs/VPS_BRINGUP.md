# SunBiz VPS bring-up runbook

> Cold-start a Linux VPS to run the SunBiz daemon stack. Eight steps, ~30 minutes once the VPS exists.
> Last updated: 2026-05-25 (mirrors CEO-Agent commit `3e3c917`; matches the playbook at
> `oasis-command-center/content/playbooks/08-sunbiz-production-pre-flight.md` § Section 9).

## What you're deploying

Five long-running processes that own the SunBiz operator workflow:

| Process | Owner | What it does |
|---|---|---|
| `event-router` | CEO-Agent (mirrored here as scripts/_archive) | Tails `agent_events` from Postgres into `state/event_router.log`; feeds the dashboard's `/feed` page |
| `sequence-runner` | This repo + CEO-Agent | Drip-campaign enrolment + execution; routes every send through `send_gateway` (CASL + cooldown + daily-cap) |
| `lender-response-classifier` | This repo + CEO-Agent | Polls Gmail for replies on shop-out threads; Claude Haiku classifies into approved/declined/info_requested |
| `claude-bridge-ping` | CEO-Agent | Heartbeats `/api/bridge/ping` so the dashboard knows the VPS is online + polls tenant cron-jobs and dispatches them |
| `shop_out_sender` (cron-driven) | This repo | Bridge-side SMTP sender that drains `application_lender_threads` rows at `status='pending'`. Not a PM2 daemon — fires through the tenant cron poller using manifest key `shop_out_sender_loop` |

You're NOT deploying `bravo-telegram` (the Telegram bridge stays on Bravo's Windows workstation — same bot token from two hosts = random message routing), `bravo-scheduler` (empire-only), or `dashboard-email-consumer` (empire-only, gated by `IS_WIN`).

---

## Step 1 — Clone both repos

```bash
sudo apt update && sudo apt install -y git python3.12 python3.12-venv python3-pip nodejs npm
cd ~
git clone https://github.com/CC90210/SunBiz-Agent.git
git clone https://github.com/CC90210/CEO-Agent.git business-empire-agent
```

The CEO-Agent repo is required because `ecosystem.config.js` lives there and the PM2 daemons (`event-router`, `sequence-runner`, `lender-response-classifier`, `claude-bridge-ping`) run from there. SunBiz-Agent is the authoritative storage for SunBiz-specific business logic per the 2026-05-15 policy (commit `7d34f2e`); the runtime copies are in CEO-Agent.

## Step 2 — Run the SunBiz setup wizard

```bash
cd ~/SunBiz-Agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/setup.py
```

Wizard creates `.env.agents.template`, scaffolds local directories, and prints what's missing.

## Step 3 — Populate `.env.agents` from the template

Copy `.env.agents.template` to `.env.agents` and fill in:

**Required (the doctor will refuse to declare green without these):**

- `SUNBIZ_TWILIO_ACCOUNT_SID`
- `SUNBIZ_TWILIO_AUTH_TOKEN`
- `SUNBIZ_TWILIO_FROM_NUMBER`
- `GMAIL_ADDRESS`
- `GMAIL_APP_PASSWORD` (Gmail App Password, not the account password — see [Google App Passwords](https://myaccount.google.com/apppasswords))
- `EMAIL_FROM_NAME` (display name on outbound)
- `EMAIL_UNSUBSCRIBE_BASE_URL` (CASL footer base)
- `SUNBIZ_AGENT_HMAC_SECRET` (signs dashboard→VPS hosted requests)
- `BRIDGE_BEARER_TOKEN` (matches Vercel env value; bridge auth)
- `ANTHROPIC_API_KEY` (backend automation paths that call Claude server-side)

(JotForm removed 2026-06-06 — SunBiz intake is the dashboard's native
`/forms` designer + `/f/<tenant>/<form>/<lead_token>` public flow.)

**Required for the CEO-Agent daemons (not checked by SunBiz-Agent's doctor; add manually):**

- `BRAVO_SUPABASE_URL`
- `BRAVO_SUPABASE_SERVICE_ROLE_KEY` (the daemons connect as service-role to see all tenants)
- `SUPABASE_ACCESS_TOKEN` (for the migration apply tool)
- `BRAVO_FIELD_ENCRYPTION_KEY` (decrypts per-tenant API keys at rest)

**Optional (Phase 2 / lead-gen):**

- `SUNBIZ_TELNYX_API_KEY`, `SUNBIZ_PLIVO_*` (failover SMS providers)
- `GOOGLE_ADS_DEVELOPER_TOKEN`, `META_ACCESS_TOKEN`, `GEMINI_API_KEY` (Solara's ads stack)

Copy the same file (or the same keys) into `~/business-empire-agent/.env.agents` — the CEO-Agent daemons read from there.

## Step 4 — Doctor

```bash
cd ~/SunBiz-Agent
python scripts/doctor.py --json
```

Every check must be `status="ok"`. If any required check is `fail`, fix the env first — the daemons won't survive boot otherwise.

## Step 5 — Apply migrations

Idempotent in numeric order:

```bash
cd ~/SunBiz-Agent
for f in 042 043 044 064 065 066 067 068; do
  python scripts/apply_migration.py database/${f}_*.sql --supabase-project sunbiz
done
```

If migration 066 raises an exception about the SunBiz tenant being unseeded — that's intentional. It means the SunBiz tenant row doesn't exist in your Supabase yet. Seed it (via the dashboard's onboarding flow or by running the SunBiz CRM bootstrap script) before re-applying.

## Step 6 — Start PM2 (selective)

```bash
cd ~/business-empire-agent
sudo npm install -g pm2
pm2 start ecosystem.config.js --only event-router,sequence-runner,lender-response-classifier,claude-bridge-ping
pm2 save
sudo pm2 startup    # generates a systemd unit; copy-paste the command it prints
```

**Critical:** use `--only`, not the default `pm2 start ecosystem.config.js`. The default would start `bravo-telegram` on Linux too, which conflicts with Bravo's Windows bridge (single-bot-token invariant). The `--only` form makes the conflict impossible.

## Step 7 — Pair the VPS to the dashboard

Generate a bridge pairing token in the dashboard (Settings → Devices → Install bridge), drop it at `~/.oasis/bridge_token` on the VPS, then restart `claude-bridge-ping`:

```bash
mkdir -p ~/.oasis
echo "<pairing-token-from-dashboard>" > ~/.oasis/bridge_token
chmod 600 ~/.oasis/bridge_token
pm2 restart claude-bridge-ping
```

Within 60 seconds the dashboard's bridge-online indicator on the SunBiz `/automations` page should flip green.

## Step 8 — Smoke test

```bash
# 8a. Confirm PM2 is steady (no restart loops).
pm2 status
pm2 logs --lines 50

# 8b. Confirm the event router is consuming events.
tail -n 20 ~/business-empire-agent/state/event_router.log

# 8c. Confirm the dashboard sees this VPS as the SunBiz bridge.
#     In the dashboard: /t/sun/automations → top banner shows
#     "Your computer is connected." with the green Cpu icon.

# 8d. Live test: queue one shop-out from the dashboard at
#     /t/sun/shopping-out, then watch:
tail -f ~/business-empire-agent/tmp/pm2-*.log
#     You should see shop_out_sender claim the thread (status pending→sending→sent)
#     within ~60s (the cron poller's tick interval).
```

Watchpoint: leave `tail -f ~/business-empire-agent/state/event_router.log` running for 10 minutes after first boot. No crash loops, no Postgres connection-refused storms, no Gmail auth retries past the first one.

---

## Daily ops

- Status: `pm2 status` + `pm2 logs --lines 50`
- Restart one: `pm2 restart sequence-runner`
- Restart all: `pm2 restart all`
- Pull updates:
  ```bash
  cd ~/business-empire-agent && git pull && pm2 restart all
  cd ~/SunBiz-Agent && git pull
  # Re-apply any new database/*.sql via Step 5's loop
  ```

## Known follow-ups (not blocking deploy)

1. **Doctor coverage gap** — `scripts/doctor.py` checks SunBiz-Agent's env keys but doesn't validate the CEO-Agent daemon keys (`BRAVO_SUPABASE_URL`, `BRAVO_FIELD_ENCRYPTION_KEY`). Add to doctor in a future pass.
2. **`shop_out_sender` is cron-driven, not a PM2 daemon** — fires through `claude-bridge-ping`'s tenant cron poller using manifest key `shop_out_sender_loop`. If you'd rather have it as a long-running daemon, add an entry to `ecosystem.config.js` (interval 60s is sensible). The cron-driven path is the current default per the bridge-side execution model.
3. **`send_gateway.py` lives canonically in CEO-Agent, not here** — it's an empire-wide chokepoint (oasis + sunbiz brands + CASL + cooldown + daily-cap). This repo stores SunBiz-specific logic only. Don't fork.
4. **`bravo-telegram` is intentionally not on the VPS** — Telegram routing stays single-host on Bravo's Windows workstation. If CC ever wants the VPS to own Telegram, follow the handoff protocol in `ecosystem.config.js` (stop Windows bridge first, then start the VPS one).

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| `pm2 logs` shows `Postgres connection refused` | Wrong Supabase URL or service-role key | Re-check `.env.agents`; the service-role key changes when CC rotates it |
| Migration 066 throws `tenant not found` | SunBiz tenant row missing in Supabase | Seed it via dashboard onboarding before re-running |
| Bridge-online indicator stays red | Pairing token not loaded or `claude-bridge-ping` not running | Check `cat ~/.oasis/bridge_token` exists; `pm2 restart claude-bridge-ping` |
| Shop-out threads stuck at `pending` | `shop_out_sender_loop` cron not seeded or `claude-bridge-ping` not polling | Verify in dashboard /automations that there's a cron job with action_type=script and manifest_key=`shop_out_sender_loop` |
| `lender-response-classifier` 401s on Gmail | App Password expired or 2FA settings changed | Regenerate at [Google App Passwords](https://myaccount.google.com/apppasswords), update `GMAIL_APP_PASSWORD`, `pm2 restart lender-response-classifier` |
| Daemon crash-loops with `ModuleNotFoundError` | venv not activated for PM2 | PM2 entries specify the interpreter explicitly; check `which python3.12` matches `~/business-empire-agent/.venv/bin/python`. If your VPS uses a different layout, edit `ecosystem.config.js`'s `PYTHON` constant for the Linux branch |
