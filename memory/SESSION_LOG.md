---
name: SESSION_LOG
description: Append-only session history for SunBiz-Agent. Add new sessions at the top.
last_updated: 2026-07-22
---

# SESSION LOG

> Append-only. New sessions at the top. Each entry: date, duration estimate, actions, decisions, next session.

---

## 2026-07-22 - Dolphin Ezra selection protocol + VPS system message

**Actions:**
- Expanded the Dolphin UW eligibility gate with Texas/Utah/Virginia restrictions, the previously-submitted exception to the 2-position minimum, a 5-position maximum, Column I monthly leverage under 40%, and known payoff amounts of at least $15,000 while allowing blanks.
- Added Ezra's preferred-funder force-surface list with Nationwide retained as the absolute veto; the final Telegram boundary re-runs the same deterministic gate.
- Parsed Date Funded and Payoff Amount from the UW position table and added both numbers to Ezra's complete Telegram funder-stack packet.
- Rewrote `docs/DOLPHIN_VPS_PRODUCTION_UPDATE_2026-07-21.md` as the paste-ready VPS system message and deployment/verification protocol.

**Proof:**
- `python -m pytest tests/test_dolphin_eligibility.py tests/test_uw_enrichment_mapping.py -q` passed: 12 tests.
- `python -m compileall -q scripts/scrubber` passed.
- `git diff --check` passed. Local `scripts/doctor.py --json` still reports the known Windows-only missing local `.env.agents`/Gmail/HMAC configuration; production verification remains explicitly gated in the VPS system message.

**Open Items:**
- Commit/push these changes, then paste the system message into the VPS agent to fast-forward, re-evaluate stale pending candidates, restart only Dolphin's two PM2 workers, and prove production health without sending a test deal.

---

## 2026-07-02 - Breeze UW enrichment + missing-field repair

**Actions:**
- Reproduced the Frozen Ropes Live Subs gap: the approved lead row was stale/incomplete, while the source UW Sheet could still provide owner/business address, SSN-last4, TIB/start date, entity, DBA, EIN, revenue, positions, and leverage. The sheet itself had blank email/phone and no visible DOB/citizenship/credit value for that deal.
- Updated `scripts/scrubber/uw_sheet_parser.py` to tolerate label variants/colons and parse optional DOB, citizenship, and credit-score labels when a UW Sheet contains them.
- Updated `scripts/mca_lead_scrubber.py` so parsed UW data lands under the Command Centre's displayed keys: `legal_name`, `business_legal_name`, `owner_name`, `owner_ssn_last4`, `owner_address_*`, `business_address_line1`, `business_start_date`, `time_in_business`, `business_state_code`, and credit/citizenship aliases.
- Added `scripts/uw_lead_enricher.py`: a new `once|loop|doctor` worker that re-reads source Google Sheets for approved Live Subs leads, fill-only backfills missing fields, uses Firecrawl/TruePeopleSearch research for blank contact channels, notifies Ezra for verification when a contact is newly sourced, re-emits the status-change event, and revives only failed sequence rows whose error was missing email/phone.
- Added Drive discovery exclusions in `scripts/scrubber/ingest.py` via `SIFT_SHEET_EXCLUDE` defaulting to `contracts sent,notification,do not`.
- Registered `uw-lead-enricher` in `ecosystem.config.js` as an IS_LINUX PM2 singleton at 300s, and added `mca-lead-scrubber`, `ezra-telegram-bridge`, and `uw-lead-enricher` to the Command Centre worker registry.

**Proof:**
- `python -m py_compile scripts\scrubber\uw_sheet_parser.py scripts\scrubber\ingest.py scripts\mca_lead_scrubber.py scripts\uw_lead_enricher.py tests\test_uw_enrichment_mapping.py` passed.
- `python -m pytest tests\test_uw_enrichment_mapping.py` passed: 2 tests.
- `python scripts\uw_lead_enricher.py doctor` passed: Supabase OK, Breeze Drive creds all set, Drive discovery OK with 93 candidate sheets, Firecrawl/research_fetch present, Ezra Telegram token/chat set, 12 UW leads sampled, 12 missing contact, 12 needing sheet refresh.
- `python scripts\uw_lead_enricher.py once --dry-run --force-refresh --skip-web --limit 20` passed: 12/12 UW leads would be sheet-refreshed, including Frozen Ropes, with 0 writes and 0 errors.
- `python scripts\uw_lead_enricher.py once --dry-run --force-refresh --limit 2` passed after the pagination and LOW-confidence suppression fixes: 2 leads seen, 2 sheet-refreshed, 1 MEDIUM contact candidate, Frozen Ropes' LOW contact candidate suppressed, 0 writes.
- `python scripts\mca_lead_scrubber.py once --dry-run --limit 5` passed: scored 5 live Drive sheets, staged nothing.
- `npm run typecheck` passed in `oasis-command-center`.

**Open Items:**
- Production VPS still needs the code deployed/restarted: `pm2 start ecosystem.config.js --only uw-lead-enricher && pm2 save` after pulling the commit on `/srv/sunbiz/sunbiz-agent`.
- First live `uw_lead_enricher.py once` should be run on a small batch from the VPS terminal after Ezra/CC accept that sourced contacts may revive previously failed missing-channel sequence rows.

---

## 2026-07-02 - Breeze UW Entry Sheet live verification

**Actions:**
- Created `docs/breeze-uw-vps-env-system-message.md`, a paste-ready VPS Claude Code task prompt for safe `.env.agents` auditing, missing-secret entry via `scripts/set_secret.py`, PM2 restart, and live Breeze UW/Telegram proof checks. No secret values were included.
- Verified `scripts/mca_lead_scrubber.py doctor`: Supabase client OK, Breeze Drive OAuth keys present, Drive access OK as the Breeze identity, and 97 candidate `UW Sheet` files discoverable.
- Verified `scripts/setup_check.py --json`: SunBiz tenant setup passed 8 checks with 1 warning; bridge pairing is live. Direct read-only DB check showed the paired Linux bridge `srv1723601` with a fresh heartbeat and all tenant cron jobs enabled with latest runs successful.
- Verified Telegram approval path without sending a test packet: `EZRA_TELEGRAM_BOT_TOKEN` and `EZRA_TELEGRAM_CHAT_ID` are set, Telegram `getMe` succeeded, and live DB rows show recent UW candidates plus prior approved/declined Telegram decisions.
- Ran `python scripts/mca_lead_scrubber.py once --dry-run --limit 5`: parsed/scored five live Drive sheets successfully, staged nothing, and sent nothing because it was dry-run.

**Findings:**
- Breeze UW extraction is out of sandbox in code/config: `ecosystem.config.js` runs `mca-lead-scrubber` and `ezra-telegram-bridge` only on Linux/VPS, with `SIFT_PARSER_READY=1`.
- Live data proves the scrubber is actively staging deals: latest pending review candidates were created on 2026-07-02, and approved candidates from 2026-07-01 created `uw_sheet` / Live Subs leads.
- Remaining process-level proof requires checking PM2 logs on the VPS itself; repo memory says not to SSH from Windows, so use the VPS terminal/paste-prompt path for `pm2 status` and `pm2 logs mca-lead-scrubber ezra-telegram-bridge`.

**Open Items:**
- The legacy `scripts/doctor.py --json` still reports local `.env.agents`/Gmail/HMAC missing on Windows, while the scrubber doctor correctly uses the shared Business-Empire-Agent env and passes. Treat that as a doctor false red for this workflow unless the VPS doctor also fails.

---

## 2026-05-25 — V6.x Cognitive Substrate Upgrade

**Actions:**
- Audited existing skills/ — 19 skills found, 8 legacy AdVantage marketing skills identified for archival
- Moved 8 legacy skills to `skills/_archive/`: a-b-testing, ad-copywriting, audience-targeting, budget-optimization, campaign-creation, google-ads-management, meta-ads-management, performance-optimization
- Created 10 new SunBiz funding-shop skills: shop-out-routing, underwriting-flow, follow-up-discipline, renewal-window-detection, lender-intelligence, cold-outreach-blast, casl-compliance, operator-handoff, funding-vocabulary, daily-call-sheet-workflow
- Created 3 cognitive scaffolding skills: memory-journaling (new), codex-delegation (new), systematic-debugging (upgraded from AdVantage-era version to CEO-Agent V6.x standard)
- Created CONTEXT.md at repo root with SunBiz-specific vocabulary glossary
- Created 7 memory files: MEMORY.md (index), CLIENT_CONTEXT.md (team/lender context), updated ACTIVE_TASKS.md, SESSION_LOG.md, MISTAKES.md, PATTERNS.md, DECISIONS.md

**Key Decisions:**
- Legacy skills preserved in `_archive/`, not deleted — Obsidian graph integrity maintained
- All new skills use V6.8 frontmatter convention (name, description, triggers, tier, disable_model_invocation, optional requires/argument_hint)
- CONTEXT.md goes at repo root (not in a subdir) per CEO-Agent pattern
- CLIENT_CONTEXT.md initialized with TBD placeholders — Ezra to populate

**Open Items (carry to next session):**
- Apply migration 069 to production
- Ezra to confirm cron schedules for 4 new daemons
- Ezra to populate CLIENT_CONTEXT.md with team phones, lender book, deal volume

---

## 2026-03-10 — Initial Setup

**Duration:** Full session

**Actions:**
- Built complete Marketing Agent (AdVantage V2.0) file structure from scratch
- Created 3 entry points (CLAUDE.md, ANTIGRAVITY.md, GEMINI.md)
- Created 10 brain files (SOUL, STATE, AGENTS, BRAIN_LOOP, CAPABILITIES, CLIENT, INTERACTION_PROTOCOL, HEARTBEAT, GROWTH, CHANGELOG)
- Created memory system (8 files)
- Created 12 agent definitions
- Created 14 skill files (AdVantage marketing era)
- Created 11 Antigravity workflow commands
- Created MCP configurations and wrapper scripts
- Researched Google Ads API and Meta Marketing API capabilities
- Documented lending industry compliance requirements

**Key Decisions:**
- Use Google Ads API (not Ad Manager) for campaign management
- Use pipeboard-co/meta-ads-mcp as primary Meta MCP server
- Use grantweston/google-ads-mcp-complete or custom for Google MCP
- Special Ad Category: CREDIT required for all Meta lending ads
- Python SDK fallback for both platforms when MCP fails

**Next Session:**
- Await API credentials from client
- Install MCP servers
