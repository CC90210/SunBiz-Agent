/**
 * PM2 Ecosystem Config — SunBiz Funding Operations
 *
 * Hosts SunBiz-specific background daemons. Run from this repo:
 *   cd ~/SunBiz-Agent
 *   pm2 start ecosystem.config.js
 *   pm2 save
 *
 * Boundary: CEO-Agent's ecosystem.config.js runs Bravo / OASIS-platform
 * daemons (scheduler, telegram, bridge, event-router, dashboard-email-
 * consumer). SunBiz tenant-specific daemons live HERE so per-tenant
 * pause/restart doesn't cycle Bravo.
 *
 * All daemons here connect to the SAME Supabase project as CEO-Agent
 * (multi-tenant), reading SunBiz-tenant rows via tenant_id scoping.
 * The .env.agents loader is symlinked / shared across the two repos
 * (see scripts/lib/secret_loader.py in CEO-Agent — universal loader).
 */

const os = require('os');
const path = require('path');

const IS_MAC = process.platform === 'darwin';
const IS_WIN = process.platform === 'win32';
const IS_LINUX = process.platform === 'linux';

// SunBiz-Agent root per machine.
const PROJECT_ROOT = IS_MAC
    ? path.join(os.homedir(), 'SunBiz-Agent')
    : (IS_WIN
        ? 'C:\\Users\\User\\SunBiz-Agent'
        : (IS_LINUX
            ? '/srv/sunbiz/sunbiz-agent'
            : path.join(os.homedir(), 'SunBiz-Agent')));

// Python interpreter — SunBiz-Agent reuses CEO-Agent's venv (sibling
// repo) because they share the same Python deps (supabase, anthropic,
// etc.). If SunBiz-Agent ever needs its own venv, change this to
// .venv inside this repo.
const BRAVO_ROOT = IS_MAC
    ? path.join(os.homedir(), 'CEO-Agent')
    : (IS_WIN
        ? 'C:\\Users\\User\\Business-Empire-Agent'
        : (IS_LINUX
            ? '/srv/sunbiz/ceo-agent'
            : path.join(os.homedir(), 'CEO-Agent')));

// Linux (VPS) uses the POSIX venv layout (.venv/bin/python), same as Mac.
const PYTHON = IS_WIN
    ? path.join(BRAVO_ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(BRAVO_ROOT, '.venv', 'bin', 'python');

// pythonw.exe — Windows GUI variant. No console window even on crash
// loops. Mac/Linux have no console concept here so fall back to python.
const PYTHONW = IS_WIN
    ? path.join(BRAVO_ROOT, '.venv', 'Scripts', 'pythonw.exe')
    : PYTHON;

const apps = [];

// ============================================================================
// sequence-runner — drip-campaign engine (SunBiz CRM Phase 4)
// ============================================================================
//
// Two responsibilities in one daemon, alternated each tick:
//   1. Enrollment: reads new agent_events rows since last cursor, matches
//      against drip_sequences, inserts sequence_state rows for matching
//      (lead, sequence) pairs.
//   2. Execution: polls sequence_state for due rows, fires via
//      send_gateway.send (SMS/email), updates status, enqueues next step.
//
// CASL/cooldown/daily-cap enforcement is automatic because all sends
// route through send_gateway (the single outbound chokepoint, in
// CEO-Agent/scripts/integrations/). Tenant isolation is at the row
// level (tenant_id match on sequence_state + drip_sequences); the
// daemon connects as service-role.
//
// 10s tick interval matches the typical operator expectation that a
// stage-change drip fires "within a couple seconds" without slamming
// agent_events with a poll storm. Cursor in state/sequence_runner.cursor
// so restarts don't re-enroll.
apps.push({
    name: "sunbiz-sequence-runner",
    script: "scripts/sequence_runner.py",
    args: ["loop", "--interval", "10"],
    interpreter: PYTHONW,
    cwd: PROJECT_ROOT,
    watch: false,
    autorestart: true,
    max_restarts: 20,
    restart_delay: 10000,
    windowsHide: true,
    env: {
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
        BRAVO_AGENT_ROOT: BRAVO_ROOT,
    },
    log_date_format: "YYYY-MM-DD HH:mm:ss",
    error_file: "tmp/pm2-sequence-runner-error.log",
    out_file: "tmp/pm2-sequence-runner-out.log",
    merge_logs: true,
    max_size: "10M",
});

// ============================================================================
// lender-response-classifier — Gmail label monitor for shop-out replies
// ============================================================================
//
// Phase 6.4 of SunBiz CRM. Polls application_lender_threads rows where
// status=sent + gmail_thread_id is non-null, fetches the latest message
// via CEO-Agent/scripts/integrations/google_tool.py, classifies via
// Claude Haiku 4.5 into approved/declined/info_requested/unclear, and
// updates status + last_response_summary. Operators see the funding-
// pipeline state on the application detail page without ever opening
// Gmail.
//
// Also runs an SLA sweep each tick: threads at status=sent older than
// the lender's sla_response_days auto-flip to no_response (no
// classifier call needed).
//
// 5-min default tick. Cheap-but-non-trivial because each tick does a
// Gmail thread fetch + Claude classification per pending thread.
// Operators can run with --interval 60 for tighter responsiveness
// during a busy submission day.
apps.push({
    name: "sunbiz-lender-response-classifier",
    script: "scripts/lender_response_classifier.py",
    args: ["loop", "--interval", "300"],
    interpreter: PYTHONW,
    cwd: PROJECT_ROOT,
    watch: false,
    autorestart: true,
    max_restarts: 20,
    restart_delay: 30000,
    windowsHide: true,
    env: {
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
        BRAVO_AGENT_ROOT: BRAVO_ROOT,
    },
    log_date_format: "YYYY-MM-DD HH:mm:ss",
    error_file: "tmp/pm2-lender-classifier-error.log",
    out_file: "tmp/pm2-lender-classifier-out.log",
    merge_logs: true,
    max_size: "10M",
});

// ============================================================================
// cold-outreach-runner — scheduled outbound blast scheduler (Build 3)
// ============================================================================
//
// Promotes scheduled cold_outreach_campaigns (draft -> queued when
// scheduled_for <= now UTC) and drains queued campaigns through send_gateway
// (email + SMS via TextTorrent/Twilio; provider derived from the campaign
// channel). daily-cap enforced in BOTH the runner and send_gateway (defense
// in depth). 30s tick; restart_delay 30000ms so a crash-loop backs off.
apps.push({
    name: "sunbiz-cold-outreach-runner",
    script: "scripts/cold_outreach_runner.py",
    args: ["loop", "--interval", "30"],
    interpreter: PYTHONW,
    cwd: PROJECT_ROOT,
    watch: false,
    autorestart: true,
    max_restarts: 20,
    restart_delay: 30000,
    windowsHide: true,
    env: {
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
        BRAVO_AGENT_ROOT: BRAVO_ROOT,
    },
    log_date_format: "YYYY-MM-DD HH:mm:ss",
    error_file: "tmp/pm2-cold-outreach-error.log",
    out_file: "tmp/pm2-cold-outreach-out.log",
    merge_logs: true,
    max_size: "10M",
});

// ============================================================================
// mca-lead-scrubber — "Breeze UW Entry Sheet" (Solara backend automation)
// ============================================================================
//
// Watches the shared Breeze/SunBiz Google Drive for new MCA web-form lead
// sheets, scrubs each deal against config-driven underwriting criteria
// (scrubber/scoring_config.yaml — SOP-tunable), and writes the qualified ones
// to scrub_candidates as pending_review for Ezra to approve in the Command
// Centre (/uw-sheet). Approval creates the lead at the uw_sheet stage.
//
// IS_LINUX-GATED ON PURPOSE: discovery polls Drive and must be a SINGLE owner.
// Running it on CC's Mac AND the VPS would double-process every sheet. It runs
// ONLY on the Linux VPS. (Surfaced in the dashboard Automations tab as a
// background worker via lib/automations/sunbiz-workers.ts → "pm2.mca-lead-scrubber".)
//
// 120s tick (within CC's 15-30 min target, well under the "5 min is too slow"
// bar). Detection is cheap; the heavy scrub only runs on newly-seen sheets.
// Reaches Drive via google_tool.py (gws OAuth) — verify with `doctor` that the
// VPS has gws auth + openpyxl before relying on it.
if (IS_LINUX) {
    apps.push({
        name: "mca-lead-scrubber",
        script: "scripts/mca_lead_scrubber.py",
        args: ["loop", "--interval", "120"],
        interpreter: PYTHON,
        cwd: PROJECT_ROOT,
        watch: false,
        autorestart: true,
        max_restarts: 20,
        restart_delay: 30000,
        env: {
            PYTHONIOENCODING: "utf-8",
            PYTHONUNBUFFERED: "1",
            BRAVO_AGENT_ROOT: BRAVO_ROOT,
        },
        log_date_format: "YYYY-MM-DD HH:mm:ss",
        error_file: "tmp/pm2-mca-lead-scrubber-error.log",
        out_file: "tmp/pm2-mca-lead-scrubber-out.log",
        merge_logs: true,
        max_size: "10M",
    });
}

// ============================================================================
// ezra-telegram-bridge — Ezra's approve/deny poller for the UW deals
// ============================================================================
//
// Long-polls Telegram for Ezra's Approve/Deny taps on the deal packets the
// scrubber sends him. Approve → injects the lead at the uw_sheet ("Live Subs")
// stage (createRecord-equivalent: tenant_records insert + BRAVO_RECORD_STATUS_CHANGED
// event, so the follow-up drip fires) + flips the candidate to approved. Deny →
// marks it declined and stops. Reads EZRA_TELEGRAM_BOT_TOKEN + EZRA_TELEGRAM_CHAT_ID.
//
// IS_LINUX-gated single instance (one poller owns the getUpdates offset — two
// would fight over updates). Pairs with mca-lead-scrubber.
if (IS_LINUX) {
    apps.push({
        name: "ezra-telegram-bridge",
        script: "scripts/scrubber/telegram_bridge.py",
        args: ["poll"],
        interpreter: PYTHON,
        cwd: PROJECT_ROOT,
        watch: false,
        autorestart: true,
        max_restarts: 20,
        restart_delay: 15000,
        env: {
            PYTHONIOENCODING: "utf-8",
            PYTHONUNBUFFERED: "1",
            BRAVO_AGENT_ROOT: BRAVO_ROOT,
        },
        log_date_format: "YYYY-MM-DD HH:mm:ss",
        error_file: "tmp/pm2-ezra-telegram-bridge-error.log",
        out_file: "tmp/pm2-ezra-telegram-bridge-out.log",
        merge_logs: true,
        max_size: "10M",
    });
}

module.exports = { apps };
