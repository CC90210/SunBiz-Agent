# SunBiz Agent — CHANGELOG

> Tracks significant releases and architectural milestones for this repo.
> Tactical business decisions live in `memory/DECISIONS.md`. This file tracks code and schema changes.

---

## [V6.8] — 2026-05-25

### V6.8 cognitive substrate upgrade + second-meeting expansion

**Cognitive substrate (brain/):**
- Upgraded Solara's cognitive substrate to V6.8 quality: SOUL.md, BRAIN_LOOP.md, INTERACTION_PROTOCOL.md, USER.md, CAPABILITIES.md all brought to current schema and persona conventions.
- Solara now carries the full V6.8 vocabulary layer and skill governance conventions (frontmatter `requires:`, `disable_model_invocation`, `argument_hint`) matching CEO-Agent's shape.

**Schema (database/):**
- Applied migration 064 (SunBiz Command Center restructure — Jordan/Oasis 2026-05): collapsed Lead stages 8→5, Application statuses 17→9, scoped to `tenant_slug='sun'`.
- Applied migration 065 (persist send-context on `application_lender_threads`): added `body_template` and `attachments` columns for faithful bridge-side shop-out reproduction.
- Applied migration 066 (tenant-resolution hotfix + Ezra owner role): fixed 064's silent no-op caused by wrong slug resolver.
- Applied migration 067 (stage remap second pass): idempotent cleanup for 064/066.
- Applied migration 068 (shop-out claim state): added `sending` status + `send_interaction_id` for atomic double-send prevention.
- Applied migration 069 (second-meeting expansion): 14 new tables — underwriting, follow-up machine, daily planning, cold outreach, shop-out warnings, lender intelligence, personalized links, agent memory notes.

**Daemons (scripts/):**
- `shop_out_sender.py` — bridge-side SMTP sender for shop-out threads (atomic claim, crash-safe).
- `underwriting_orchestrator.py` — three-phase underwriting pipeline (statement_parser + debt_detector + sales_angle via Claude vision).
- `renewal_reminder.py` — renewal window detection + Telegram alert + draft generation.
- `follow_up_generator.py` — contextual follow-up drafts from the `follow_up_tasks` queue.
- `cold_outreach_runner.py` — multi-step NEPQ-style cold campaign execution.
- `daily_plan_generator.py` — morning priority queue generator writing to `daily_plan_items`.
- `lender_response_classifier.py` — Gmail reply classifier (Claude Haiku, 5-min tick).
- `sequence_runner.py` — drip enrollment + execution (10s tick, CASL-gated via send_gateway).

**Docs (docs/):**
- Created `docs/VPS_BRINGUP.md` — production VPS bringup runbook (8 steps).
- Created `docs/ARCHITECTURE.md` — three-repo split + full request flow diagrams.
- Created `docs/DAEMON_PLAYBOOK.md` — per-daemon ops reference (all 8 daemons).
- Created `docs/MIGRATION_HISTORY.md` — numbered migration log (042–069).
- Created `docs/SOLARA_QUICKSTART.md` — operator cheat sheet for Solara.
- Created `docs/HELIOS_QUICKSTART.md` — operator cheat sheet for Helios.
- Created `docs/CHANGELOG.md` — this file.

**Config:**
- `README.md` — full rewrite: V6.8 architecture, 8-daemon table, 14-table migration-069 reference, Quickstart for Ezra and developers, production status.
- `MAXIMIZATION_GUIDE.md` — full rewrite: morning ritual, day workflows, Helios prompts, feedback protocol, power-user techniques.
- `requirements.txt` — audited and expanded: added `anthropic`, `supabase`, `pdfplumber`, `PyMuPDF`, `google-auth-*`, `google-api-python-client`, `httpx`, `pydantic`, `python-dateutil`, `pytz`.
- `package.json` — bumped to v1.1.0, added npm run scripts for all 8 daemons.
- `.claude/mcp.json` — aligned to CEO-Agent V6.8 MCP set: added `knowledge-graph`, `github`, `firecrawl`, `obsidian`, `filesystem`; updated `playwright` to `--headless` flag.
- `.vscode/mcp.json` — aligned to `.claude/mcp.json`.
- `.claude/settings.local.json` — aligned to CEO-Agent: added `PreToolUse` hooks for `secret_guard`, `exec_guard`, `state_guard`; added `PostToolUse` hook; set `enableAllProjectMcpServers: true`.
- `.env.agents.template` — added new daemon keys: `ANTHROPIC_API_KEY`, `RENEWAL_REMINDER_CHAT_ID`, `SUNBIZ_TEXTORRENT_*`, `BRAVO_SUPABASE_*`, `SUPABASE_ACCESS_TOKEN`, `BRAVO_FIELD_ENCRYPTION_KEY`; reorganized into labeled sections with REQUIRED / OPTIONAL markers.

**Production status after this release:**
- V6.8 cognitive substrate: shipped.
- Second-meeting expansion (migration 069 + all 8 daemons): shipped.
- Awaiting: cron seeds in dashboard, VPS bringup, Ezra day-1 walkthrough.

---

## [V1.0] — 2026-05-12

### Initial SunBiz Agent release

- Dual-agent stack: Solara (backend/admin) + Suga Sean (outreach).
- Core scripts: `api_server.py`, `sms_engine.py`, `email_blast.py`, `jotform_tracker.py`, `doctor.py`, `setup.py`.
- Ad tooling: `meta_ads_engine.py`, `google_ads_engine.py`, `imagen_generate.py`, `ad_copy_generator.py`.
- Migrations 042, 043, 044 (forms, drip sequences, lender shop-out).
- Brain: SOUL, CAPABILITIES, CLIENT, STATE, BRAIN_LOOP.
- Dashboard integration contract in `dashboard/INTEGRATION.md`.
- Docs: `UNIFIED_ONBOARDING_MANUAL.md`, `DUAL_AGENT_STACK.md`.
- Initial `MAXIMIZATION_GUIDE.md` (ad-focused, pre-restructure).
