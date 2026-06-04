# SunBiz VPS bring-up runbook

> Cold-start a Linux VPS to run the SunBiz daemon stack.
> Last updated: 2026-06-03 — **corrected to the `/srv/sunbiz` layout** that both
> `ecosystem.config.js` files hardcode for Linux and that the live VPS uses. The
> prior `~/business-empire-agent` / `~/SunBiz-Agent` layout was wrong: the
> ecosystems' Linux branch pins `PROJECT_ROOT=/srv/sunbiz/{ceo-agent,sunbiz-agent}`
> and the interpreter `/srv/sunbiz/ceo-agent/.venv/bin/python`, so home-dir clones
> would crash. `scripts/vps_bootstrap.sh` in CEO-Agent automates Steps 1–3.

## What you're deploying

**5 PM2 processes** (2 from CEO-Agent's ecosystem, 3 from SunBiz-Agent's) plus
**cron-driven jobs** that fire through the bridge poller:

| Process | PM2 name | Ecosystem | What it does |
|---|---|---|---|
| Event router | `event-router` | CEO-Agent | Tails `agent_events` into `state/event_router.log`; feeds the dashboard `/feed` |
| Bridge ping + cron poller | `claude-bridge-ping` | CEO-Agent | Heartbeats `/api/bridge/ping`; polls tenant cron-jobs and dispatches the cron-driven daemons |
| Sequence runner | `sunbiz-sequence-runner` | SunBiz-Agent | Drip enrolment + execution; every send via `send_gateway` (CASL + cooldown + cap) |
| Lender reply classifier | `sunbiz-lender-response-classifier` | SunBiz-Agent | Polls Gmail for shop-out replies; Haiku classifies approved/declined/info_requested |
| Cold outreach runner | `sunbiz-cold-outreach-runner` | SunBiz-Agent | Cold-outreach send loop (registered as `cold_outreach_runner` agent_source) |

**Cron-driven (NOT PM2 apps — fire via `claude-bridge-ping`'s poller after pairing + seed):**
`shop_out_sender` (manifest `shop_out_sender_loop`), `renewal_reminder`,
`follow_up_generator`, `daily_plan_generator`, `underwriting_orchestrator`.

You're NOT deploying `bravo-telegram` (Telegram stays on Bravo's Windows host — same
bot token from two hosts = random routing), `bravo-scheduler` (empire-only), or
`dashboard-email-consumer` (empire-only, `IS_WIN`-gated).

---

## Step 1 — Provision + clone both repos into `/srv/sunbiz`

Fastest path: run `sudo bash scripts/vps_bootstrap.sh` from a CEO-Agent checkout —
it installs packages, creates the `bravo` user, clones both repos to
`/srv/sunbiz/{ceo-agent,sunbiz-agent}`, builds both `.venv`s, and writes the
`.env.agents` placeholder. To do it by hand:

```bash
sudo apt update && sudo apt install -y git python3.12 python3.12-venv python3-pip nodejs npm
sudo install -d -o "$USER" -g "$USER" /srv/sunbiz
git clone https://github.com/CC90210/CEO-Agent.git    /srv/sunbiz/ceo-agent
git clone https://github.com/CC90210/SunBiz-Agent.git /srv/sunbiz/sunbiz-agent
```

The CEO-Agent repo is required: `ecosystem.config.js` lives there, the PM2
interpreter is `/srv/sunbiz/ceo-agent/.venv/bin/python`, and the SunBiz daemons
resolve `send_gateway` + the shared substrate from it.

## Step 2 — Virtualenvs (`.venv` in BOTH repos)

CEO's `.venv` is the interpreter for ALL daemons (the SunBiz PM2 apps point at it,
and the cron poller execs SunBiz scripts with it), so it must carry BOTH repos'
deps. SunBiz's own `.venv` is for manual `doctor.py` / `cron_registry.py` runs.

```bash
# CEO-Agent venv — both repos' requirements
cd /srv/sunbiz/ceo-agent
python3.12 -m venv .venv && . .venv/bin/activate
pip install -U pip wheel && pip install -r requirements.txt -r /srv/sunbiz/sunbiz-agent/requirements.txt
deactivate

# SunBiz-Agent venv + setup wizard
cd /srv/sunbiz/sunbiz-agent
python3.12 -m venv .venv && . .venv/bin/activate
pip install -U pip wheel && pip install -r requirements.txt
python scripts/setup.py     # creates .env.agents.template, prints what's missing
```

## Step 3 — Populate `.env.agents`

Copy `.env.agents.template` → `.env.agents` and fill in:

**Required (the doctor refuses green without these):**

- `SUNBIZ_TWILIO_ACCOUNT_SID`, `SUNBIZ_TWILIO_AUTH_TOKEN`, `SUNBIZ_TWILIO_FROM_NUMBER`
- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (App Password, not the account password — [Google App Passwords](https://myaccount.google.com/apppasswords))
- `EMAIL_FROM_NAME`, `EMAIL_UNSUBSCRIBE_BASE_URL` (CASL footer base)
- `JOTFORM_API_KEY`, `JOTFORM_FORM_ID`
- `SUNBIZ_AGENT_HMAC_SECRET` (signs dashboard→VPS hosted requests)

**Required for the CEO-Agent daemons (not checked by SunBiz's doctor; add manually):**

- `BRAVO_SUPABASE_URL`
- `BRAVO_SUPABASE_SERVICE_ROLE_KEY` (daemons connect as service-role to see all tenants)
- `SUPABASE_ACCESS_TOKEN` (migration apply tool)
- `BRAVO_FIELD_ENCRYPTION_KEY` (decrypts per-tenant API keys at rest)

**Production safety (keep until CC approves live outbound):**

- `BRAVO_FORCE_DRY_RUN=1`
- `EMAIL_REQUIRE_FROM_DOMAIN=sunbizfunding.com`
- `CASL_FAIL_CLOSED=1` (Supabase suppressions authoritative; fail-closed if no source reachable)

**Optional (Phase 2 / lead-gen):** `SUNBIZ_TELNYX_API_KEY`, `SUNBIZ_PLIVO_*`,
`GOOGLE_ADS_DEVELOPER_TOKEN`, `META_ACCESS_TOKEN`, `GEMINI_API_KEY`.

The CEO-Agent daemons read **CEO's** `.env.agents`. The bootstrap symlinks
`/srv/sunbiz/sunbiz-agent/.env.agents → /srv/sunbiz/ceo-agent/.env.agents` so the
two stay identical; if you set them up by hand, copy the same keys into both.

## Step 4 — Doctor

```bash
cd /srv/sunbiz/sunbiz-agent
.venv/bin/python scripts/doctor.py --json
```

Every check must be `status="ok"`. Fix the env first — the daemons won't survive boot otherwise.

## Step 5 — Apply migrations (idempotent, numeric order)

```bash
cd /srv/sunbiz/sunbiz-agent
for f in $(ls database/*.sql | sort); do
  .venv/bin/python scripts/apply_migration.py "$f" --supabase-project sunbiz
done
```

Applies every SunBiz migration in order through the current high-water mark
(**077** as of 2026-06-02). If migration 066 raises "SunBiz tenant unseeded" —
that's intentional; seed the tenant via the dashboard onboarding flow first, then
re-apply. (CEO-Agent migrations, incl. the new **093**/**094**, apply against the
shared project with `--supabase-project bravo`.)

## Step 6 — Start PM2 (TWO ecosystems, selective)

The daemons live in two ecosystems — start each from its own repo:

```bash
sudo npm install -g pm2

# CEO-Agent: event bus + the bridge ping/cron poller ONLY.
cd /srv/sunbiz/ceo-agent
pm2 start ecosystem.config.js --only event-router,claude-bridge-ping

# SunBiz-Agent: the three sunbiz-* daemons (all Linux-safe; no telegram here).
cd /srv/sunbiz/sunbiz-agent
pm2 start ecosystem.config.js

pm2 save
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u "$USER" --hp "$HOME"   # run the command it prints
```

**Critical:** from CEO-Agent use `--only event-router,claude-bridge-ping`, never the
bare `pm2 start` — the default would start `bravo-telegram` on Linux, conflicting
with Bravo's Windows bridge (single-bot-token invariant). `sequence-runner` /
`lender-response-classifier` do NOT exist in CEO's ecosystem — they're
`sunbiz-sequence-runner` / `sunbiz-lender-response-classifier` in SunBiz's, started
from `/srv/sunbiz/sunbiz-agent` above. `pm2 save` AFTER starting both, or nothing
resurrects on reboot.

## Step 7 — Pair the VPS to the dashboard

Generate a pairing token in the dashboard (Settings → Devices → Install bridge),
drop it on the VPS, then restart the ping loop:

```bash
mkdir -p ~/.oasis
echo "<pairing-token-from-dashboard>" > ~/.oasis/bridge_token
chmod 600 ~/.oasis/bridge_token
pm2 restart claude-bridge-ping
```

Within 60s the dashboard's bridge-online indicator on SunBiz `/automations` flips green.

## Step 8 — Smoke test

```bash
# 8a. PM2 steady (no restart loops).
pm2 status && pm2 logs --lines 50

# 8b. Event router consuming.
tail -n 20 /srv/sunbiz/ceo-agent/state/event_router.log

# 8c. Dashboard sees this VPS: /t/sun/automations → "Your computer is connected."

# 8d. Live test: queue one shop-out at /t/sun/shopping-out, then watch:
tail -f /srv/sunbiz/ceo-agent/tmp/pm2-*.log
#     shop_out_sender should claim the thread (pending→sending→sent) within ~60s.
```

Watchpoint: leave `tail -f /srv/sunbiz/ceo-agent/state/event_router.log` running for
10 minutes after first boot. No crash loops, no Postgres connection-refused storms,
no Gmail auth retries past the first.

---

## Daily ops

- Status: `pm2 status` + `pm2 logs --lines 50`
- Restart one: `pm2 restart sunbiz-sequence-runner`
- Restart all: `pm2 restart all`
- Pull updates:
  ```bash
  cd /srv/sunbiz/ceo-agent    && git pull && pm2 restart all
  cd /srv/sunbiz/sunbiz-agent && git pull
  # Re-apply any new database/*.sql via Step 5's loop
  ```

## Known follow-ups (not blocking deploy)

1. **Doctor coverage gap** — `scripts/doctor.py` checks SunBiz's env keys but not the
   CEO-Agent daemon keys (`BRAVO_SUPABASE_URL`, `BRAVO_FIELD_ENCRYPTION_KEY`). Add later.
2. **`shop_out_sender` is cron-driven, not a PM2 daemon** — fires via `claude-bridge-ping`'s
   poller using manifest key `shop_out_sender_loop`. Seed it + `underwriting_orchestrator`
   in `cron_registry.py` (only `follow_up_generator`/`daily_plan_generator`/`renewal_reminder`
   ship seeded today).
3. **`send_gateway.py` lives canonically in CEO-Agent** — empire-wide chokepoint. Don't fork.
4. **`bravo-telegram` is intentionally not on the VPS** — Telegram stays single-host on
   Bravo's Windows workstation.

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| `pm2 logs` shows `Postgres connection refused` | Wrong Supabase URL or service-role key | Re-check `.env.agents`; the service-role key changes when CC rotates it |
| Migration 066 throws `tenant not found` | SunBiz tenant row missing in Supabase | Seed via dashboard onboarding before re-running |
| Bridge-online indicator stays red | Pairing token not loaded or `claude-bridge-ping` down | `cat ~/.oasis/bridge_token` exists; `pm2 restart claude-bridge-ping` |
| Shop-out threads stuck at `pending` | `shop_out_sender_loop` cron not seeded or poller down | Verify in /automations there's a cron job with action_type=script, manifest_key=`shop_out_sender_loop` |
| `sunbiz-lender-response-classifier` 401s on Gmail | App Password expired / 2FA changed | Regenerate at [Google App Passwords](https://myaccount.google.com/apppasswords), update `GMAIL_APP_PASSWORD`, `pm2 restart sunbiz-lender-response-classifier` |
| Daemon crash-loops with `ModuleNotFoundError` | CEO `.venv` missing SunBiz deps | Re-run Step 2's CEO-venv install (both requirements). PM2 interpreter is `/srv/sunbiz/ceo-agent/.venv/bin/python` |
| `pm2 start --only sequence-runner` starts nothing | Wrong name/repo | Those are `sunbiz-*` in SunBiz's ecosystem — start from `/srv/sunbiz/sunbiz-agent` |
