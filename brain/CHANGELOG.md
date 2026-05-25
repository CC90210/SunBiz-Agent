---
tags: [changelog, audit]
---

# CHANGELOG — Self-Modification Audit Trail

> Every significant change to this agent's brain, entry points, or capabilities is logged here.
> Format: date — version — what changed — why.

---

## 2026-05-25 — V6.x Cognitive Substrate Upgrade

**Directive:** CC (parent architect). Upgrade SunBiz-Agent's `brain/` directory to V6.8 cognitive-substrate quality matching CEO-Agent, tailored for Solara.

### Upgraded (Full Rewrites for Solara/SunBiz)
- `brain/SOUL.md` — Solara's identity, personality, and prime directive. Immutable constraints re-established.
- `brain/USER.md` — Ezra's operator profile (replaces CC's profile entirely). Team roster added.
- `brain/BRAIN_LOOP.md` — 10-step reasoning loop rewritten with funding-domain examples (shop-out hypotheses, decline Reflexion, MCA lifecycle grounding).
- `brain/STATE.md` — Operational state restructured for single-tenant SunBiz context: active shop-out queue, pending offers, funded deals, renewal window, blocked items.
- `brain/INTERACTION_PROTOCOL.md` — Tiered logging, self-improvement governance, and session-end protocol rewritten for Solara. Supabase data scoped to `tenant_id = 'sunbiz'`.
- `brain/CAPABILITIES.md` — Full tool registry rewritten: CEO-Agent V6 substrate touchpoints, SunBiz-specific daemons, Solara's tool palette, compliance enforcement points.
- `brain/GROWTH.md` — Voyager-style skill evolution rewritten for funding domain. New skill candidates: known-funder pattern learning, deal-profile clustering, drip-cadence A/B, lender-portal scrape adapters.
- `brain/HEARTBEAT.md` — Proactive monitoring rewritten with SunBiz schedule: 8am morning brief, 2pm shop-out queue health, end-of-day funded summary, weekly lender intelligence report.
- `brain/AGENTS.md` — Sub-agent registry rewritten. Primary pair: Solara (backend ops) + Helios (sales). Specialized sub-agents: underwriting-checker, offer-formatter, decline-analyst, debugger, lender-researcher. Old marketing-era agent list (15 agents) retired.

### Created (New — matching CEO-Agent V6.7+ additions)
- `brain/AGENT_ROUTER.md` — Routing-by-intent table for Solara. Intent → which file to read, intent → which tool to call.
- `brain/EXECUTION_RULES.md` — The iron law for Solara. Self-execute, confirm after mutation, CASL/TCPA gating, V6 Coherence Gate (verify inherited claims).
- `brain/INTENTS.md` — Verb-by-verb playbooks: enroll-lead-in-drip, queue-shop-out, score-application, draft-offer-acceptance, kick-off-renewal, escalate-stuck-deal.
- `brain/WHEN_TO_USE_SKILLS.md` — Skill trigger map for Solara's skill directory.

### Archived
- `brain/LENDING_AD_RESEARCH.md` → `brain/_archive/LENDING_AD_RESEARCH.md` (old marketing-era research; no longer active)

### Preserved (Unchanged)
- `brain/CLIENT.md` — SunBiz Funding business profile, ICP, compliance rules, brand identity. Still fully relevant.
- `brain/research/MCA_MARKETING_DEEP_RESEARCH_2026.md` — Deep research file; preserved for reference.

---

## V1.2 (Production Hardening) — 2026-05-12

- `scripts/doctor.py` — repo-local production doctor
- `scripts/api_server.py` — FastAPI hosted surface (`GET /health`, `GET /status`, `POST /sms/send`, `POST /webhook/jotform`)
- `scripts/setup.py` rewritten
- `.env.agents.template` rewritten for real Sun Biz runtime

---

## V1.1 (Dual-Agent Clarification) — 2026-05-12

- `brain/AGENTS.md` — Solara/Suga Sean split documented
- `dashboard/tenant.manifest.json` — paired-agent contract recorded

---

## V1.0 (Sun Biz Agent) — 2026-05-11

Repositioning from "AdVantage V2.0 — AI Marketing Director" to "Sun Biz Agent V1.0 — Full Backend Operations Agent."

---

## V2.0 (AdVantage Era) — 2026-03-10

Initial SunBiz Funding identity and MCA pivot (now historical context).
