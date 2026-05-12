# CHANGELOG

## V1.2 (Production Hardening) - 2026-05-12

Context: the repo-level setup flow was not yet production-grade. `README.md` and the dashboard contract promised a hosted API, an install path, and a health path, but the actual repo still had legacy marketing-agent scaffolding. This pass makes the shipped runtime real and makes the docs honest about what is live versus still Phase 2.

### Added
- `scripts/doctor.py` - repo-local production doctor covering env, dependencies, SMS readiness, Gmail/JotForm config, and hosted API security
- `scripts/api_server.py` - FastAPI hosted surface implementing `GET /health`, `GET /status`, `POST /sms/send`, and `POST /webhook/jotform`

### Changed
- `scripts/setup.py` rewritten to install from `requirements.txt`, prepare runtime directories, optionally seed `.env.agents`, and run the doctor
- `.env.agents.template` rewritten around the actual Sun Biz runtime (Twilio, Gmail, JotForm, HMAC, optional lead-gen keys)
- `package.json` now exposes `doctor`, `health`, `api`, and `sms:status`
- `requirements.txt` now includes `twilio`, `fastapi`, and `uvicorn`
- `README.md`, `dashboard/INTEGRATION.md`, `dashboard/tenant.manifest.json`, and entry docs synced to the real shipped runtime

### Notes
- Hosted SMS transport is now implemented in-repo; HMAC remains fail-closed when `SUNBIZ_AGENT_HMAC_SECRET` is configured
- The full deal-lifecycle ledger, Turso business-data adapter, and Phase 2 failover providers remain roadmap items, not silent assumptions

---

## V1.1 (Dual-Agent Clarification) — 2026-05-12

Context: the live GitHub repo correctly contained the Sun Biz runtime, but the product documentation still read like a Solara-only system. The intended build is a tandem deployment: Solara for backend admin operations, Suga Sean for outreach and meeting-setting.

### Changed
- `README.md` now describes the two-agent operating model explicitly
- `dashboard/tenant.manifest.json` now records the paired-agent contract (`sunbiz` + `suga_sean`)
- `dashboard/INTEGRATION.md` now states that Sun tenants should provision with both agents enabled while keeping `primary_agent="sunbiz"`
- `brain/AGENTS.md` now starts with the top-level Solara/Suga Sean split before dropping into internal sub-agent routing

### Notes
- This is a product-contract clarification and GitHub sync, not a rebrand
- Solara remains the primary system-of-record agent
- Suga Sean remains the outreach operator layered on top of the same Sun Biz workspace

## V1.0 (Sun Biz Agent) — 2026-05-11

**Major Release — Repositioning from "AdVantage V2.0 — AI Marketing Director" to "Sun Biz Agent V1.0 — Full Backend Operations Agent"**

Context: Client (Sun Biz Funding) coming out of a high-stakes pitch; CC is delivering a personalized AI operations system as the differentiator. Scope expanding from "ads only" to "full backend operations" — outbound SMS (Twilio Phase 1, Telnyx + Plivo failover Phase 2), high-volume email blasts, deal lifecycle (application → offer → funded → renewal), funding intelligence (factor rates, commission math, TAR-band classification), lender CRM, CSV lead import. Meta Ads + Google Ads engines preserved as lead-gen sub-capabilities under the new umbrella.

### Changed (BREAKING)
- **Identity:** "AdVantage V2.0 — AI Marketing Director" → **"Sun Biz Agent V1.0 — Full Backend Operations Agent"**
- **package.json `name`:** `marketing-agent` → `sun-biz-agent`
- **package.json `description`:** updated to reflect ops scope (SMS, email blasts, deal lifecycle, funding intel, commissions)
- **CLAUDE.md:** Fully rewritten — new identity, new tool-routing table (CLI-first with sms_engine.py at the top), new compliance section (TCPA for SMS), new workflow command list (/sms-blast, /deal-status, /renewal-scan, /commission-report)
- **ANTIGRAVITY.md:** Mirror of CLAUDE.md changes for the Gemini/Antigravity runtime
- **brain/SOUL.md:** Rewritten under explicit user direction (sanctioned mission-pivot — see top of file for "Amended 2026-05-11" note; this is not a self-modification of an IMMUTABLE file, it is a CC-authorized re-scoping)
- **brain/CAPABILITIES.md:** Header annotated with scope expansion note
- **First-message greeting:** "AdVantage online." → "Sun Biz Agent online."
- **Git commit prefix:** `advantage:` → `sunbiz:`

### Added
- **V6 substrate registration** (in sibling Business-Empire-Agent repo):
  - `scripts/state_manager.py::VALID_AGENTS` gained `"sunbiz"`
  - `scripts/state_manager.py::_emit_cross_agent_event()` refactored to accept `source` parameter (default `"bravo"` for backwards compat); session_log emits are now agent-templated (`f"{agent.upper()}_SESSION_LOG_APPENDED"`)
  - `scripts/agent_heartbeat.py::VALID_AGENTS` gained `"sunbiz"` (Supabase mirror)
  - `brain/EVENT_BUS_CONTRACT.md` registry: 9 new `SUNBIZ_*` event types (LEAD_SOURCED, SMS_SENT, APPLICATION_SUBMITTED, OFFER_PRESENTED, DEAL_FUNDED, RENEWAL_DUE, COMMISSION_BOOKED, EMAIL_BLAST_DISPATCHED, SESSION_LOG_APPENDED)
  - `brain/AGENTS.md` §19: Sun Biz Agent registered as a tenant-scoped operations agent alongside Atlas/Maven
- **Compliance:** TCPA section added for outbound SMS (consent check at send time, stop-keyword auto-suppression, quiet-hours enforcement)

### Preserved (functional, unchanged)
- All 16 sub-agents in `agents/` — ads agents now serve the lead-gen sub-capability
- All 19 skills in `skills/`
- `scripts/email_blast.py` (Gmail SMTP, thread-safe, CAN-SPAM) — flagship outreach engine
- `scripts/google_ads_engine.py` + `scripts/meta_ads_engine.py` — lead-gen sub-capability
- 6 HTML email templates in `templates/email/`
- All MCP server wiring (Playwright, Context7, Memory, Sequential Thinking, n8n, Late, plus pending Google/Meta Ads MCPs)
- `brain/CLIENT.md` (Sun Biz Funding ICP profile — same client, same domain)

### Operator follow-up: `.env.agents` additions (Phase 1)
The `.env.agents.template` file is file-guarded from agent edits. Paste this block into `.env.agents` (and the safe template version into `.env.agents.template`) with real values from Sun's Twilio console before the first `/sms-blast`:

```
# Sun Biz Agent — SMS (Phase 1: Twilio)
SUNBIZ_TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SUNBIZ_TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SUNBIZ_TWILIO_FROM_NUMBER=+1XXXXXXXXXX

# Sun Biz Agent — SMS (Phase 2: failover providers)
# SUNBIZ_TELNYX_API_KEY=KEYxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# SUNBIZ_TELNYX_FROM_NUMBER=+1XXXXXXXXXX
# SUNBIZ_PLIVO_AUTH_ID=MAxxxxxxxxxxxxxxxxxxxx
# SUNBIZ_PLIVO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# SUNBIZ_PLIVO_FROM_NUMBER=+1XXXXXXXXXX
```

Once added, `python scripts/sms_engine.py status --json` will show twilio in `providers_configured`, and `pip install twilio` flips `twilio_sdk_installed` to true.

### Coming Phase 2 (this week)
- `scripts/sms_engine.py` — multi-provider failover (Twilio → Telnyx → Plivo)
- `scripts/funding_intel.py` — factor-rate lookup, commission math, TAR-band classifier
- `scripts/deal_tracker.py` — application/offer/funded/renewal lifecycle helpers
- `scripts/renewal_scanner.py` — nightly cron (30-day window)
- `scripts/state_bridge.py` — V6 heartbeat daemon (PM2)
- New skills: sms-outbound, deal-lifecycle, funding-intel, commission-tracking, lender-crm
- Dashboard: tenant-scoped sidebar at `agent-dashboard-cc90210.vercel.app` for Sun-tenant logins

---

## V2.0 — 2026-03-10
**Major Release — SunBiz Funding Identity & MCA Pivot**

### Changed (BREAKING)
- **Client identity:** Generic "Lending Company" → **SunBiz Funding** (MCA consolidation & business funding)
- **Product type:** Business Term Loans → **Merchant Cash Advance (MCA) consolidation + growth capital**
- **Language rules:** "Loan" → NEVER. Now "advance," "funding," "capital" everywhere
- **SOUL.md rewritten:** AdVantage V2.0 with SunBiz philosophy, multi-phase consolidation approach, MCA brand voice
- **CLIENT.md fully rewritten:** SunBiz ICP (consolidation merchants $25K-$500K/mo revenue, 2-5 MCA positions), negative targeting, language rules, objection handling, MCA-specific lead scoring, JotForm integration
- **All CTAs now link to JotForm** — single lead capture destination for every ad
- **North Star Metric:** CPL → CPQL (Cost Per Qualified Lead)

### Rewritten
- `agents/content-creator.md` — MCA copywriting frameworks (PAS, Multi-Phase Education, Before/After, Objection Pre-empt), headline templates, language rules
- `agents/image-generator.md` — 5 MCA prompt templates (before/after, roadmap, payment table, growth capital, stories), analytical/infographic visual direction
- `skills/ad-copywriting/SKILL.md` — MCA terminology, compliance red lines, safe copy patterns, funnel-stage CTAs
- `skills/lead-generation/SKILL.md` — JotForm integration, MCA lead scoring, Higher Intent forms, speed-to-lead automation
- `skills/image-generation/SKILL.md` — Updated API examples for `generate_consolidation_ad()` and `generate_growth_ad()`
- `scripts/imagen_generate.py` — Replaced `generate_lending_ad()` with `generate_consolidation_ad()` (3 styles) + `generate_growth_ad()`
- `CLAUDE.md` — SunBiz identity, MCA compliance rule
- `ANTIGRAVITY.md` — SunBiz identity, MCA language rules, CPQL metric

### Added
- MCA-specific market research (`brain/LENDING_AD_RESEARCH.md`) — 40+ sources
- SunBiz SOP integration — ICP, multi-phase approach, SEO keywords, compliance
- JotForm as universal CTA destination
- Objection handling frameworks in ad copy
- Before/After consolidation visual template system
- Negative targeting rules (exclude <$15K revenue, >7 NSFs, death spiral merchants)

### Counts
- Agents: 15 | Skills: 18 | Workflows: 11 | MCP Servers: 8 | Scripts: 6

---

## V1.2 — 2026-03-10
**Enhancement — AI Image Generation, Lead Generation, Autonomous Posting**

### Added
- Image generator agent (`agents/image-generator.md`) — Gemini Imagen ad creative generation with 3 prompt formulas
- Gemini Imagen script (`scripts/imagen_generate.py`) — Python integration: `generate_lending_ad()`, `generate_ad_variants()`, `generate_all_sizes()`
- Image generation skill (`skills/image-generation/SKILL.md`) — prompt engineering, conversion drivers, quality checklist, iteration process
- Lead generation skill (`skills/lead-generation/SKILL.md`) — Meta Lead Form API, lead scoring, follow-up sequences, tracking/attribution
- `GEMINI_API_KEY` added to `.env.agents.template`
- Autonomous posting schedule in CLIENT.md (Mon/Wed/Fri/Sat)
- Ad creative style guide from competitor research (color psychology, layout patterns, proven CTR drivers)

### Updated
- CLIENT.md extensively rewritten with business lending context, loan tiers ($50K-$500K), ad style guide
- AGENTS.md updated to 15 agents (was 14) — added image-generator
- CAPABILITIES.md updated to 18 skills (was 16), added Gemini Imagen tool section
- CLAUDE.md updated with new agent and skill counts
- ANTIGRAVITY.md updated with image-generator in dispatch table, skill count to 18
- All orchestration matrices updated to include image-generator

### Counts
- Agents: 15 | Skills: 18 | Workflows: 11 | MCP Servers: 8 | Scripts: 6

---

## V1.1 — 2026-03-10
**Enhancement — SEO, Video, Billing, Antigravity Format**

### Added
- SEO specialist agent (`agents/seo-specialist.md`) — keyword research, Quality Score, AEO, landing page audits
- Video editor agent (`agents/video-editor.md`) — FFmpeg pipeline, Whisper captioning, platform formatting
- SEO/AEO skill (`skills/seo-aeo/SKILL.md`) — comprehensive keyword research, schema markup, featured snippet targeting
- Video editing skill (`skills/video-editing/SKILL.md`) — full production pipeline with FFmpeg commands
- Billing & payment documentation in CAPABILITIES.md (how ad spend works via API)
- Proper Antigravity workflow format (YAML front matter + `// turbo-all` on all 11 workflows)

### Updated
- ANTIGRAVITY.md rewritten to match Business Empire Agent format (WHAT/WHY/HOW structure, full rules)
- AGENTS.md updated to 14 agents (was 12)
- CAPABILITIES.md updated to 16 skills (was 14), added video tools + billing docs
- CLAUDE.md updated with new agent and skill counts
- All orchestration matrices updated to include seo-specialist and video-editor
- All workflow files now have proper Antigravity format

### Counts
- Agents: 14 | Skills: 16 | Workflows: 11 | MCP Servers: 8 | Scripts: 5

---

## V1.0 — 2026-03-10
**Initial Release — Full Infrastructure Build**

### Added
- Complete agent file structure (brain, memory, agents, skills, scripts, workflows)
- 3 entry points: CLAUDE.md (Opus), ANTIGRAVITY.md (IDE), GEMINI.md (Speed)
- 12 specialized sub-agents for marketing operations
- 14 skills covering Google Ads, Meta Ads, campaign creation, ad copywriting, audience targeting, optimization, reporting, and more
- 11 Antigravity workflow commands
- 10-step BRAIN_LOOP reasoning protocol (LATS + Reflexion inspired)
- 5-dimension self-healing system
- Lending industry compliance framework (ECOA, TILA, Meta Special Ad Category)
- MCP server configurations for 8 MCP servers
- Python SDK fallback scripts for both platforms
- Memory system with campaign tracking, performance logging, pattern recognition

### Pending
- Google Ads API credential setup
- Meta Marketing API credential setup
- MCP server installation and testing
- First campaign launch
