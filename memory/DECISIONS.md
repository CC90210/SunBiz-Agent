---
name: DECISIONS
description: Architectural and business decisions for SunBiz-Agent. Append-only. New entries at top.
last_updated: 2026-05-25
---

# DECISIONS — Architectural Decision Log

> Append-only. New entries at top. Include context, decision, why, and alternatives rejected.
> For high-stakes decisions, link to the skill or system it affects.

---

## 2026-05-25 — SunBiz-Agent forked to V6.x cognitive substrate shape

**Context:** CC directed that SunBiz-Agent's `skills/` and `memory/` directories be upgraded to match CEO-Agent's V6.8 shape, tailored for Solara's funding-shop operations.

**Decision:** Adopted CEO-Agent's V6.x structure: V6.8 frontmatter conventions on all skills, memory index (MEMORY.md), CLIENT_CONTEXT.md, PATTERNS/MISTAKES/DECISIONS with proper templates, and the three universal cognitive scaffolding skills (memory-journaling, systematic-debugging, codex-delegation).

**Why:** Consistent architecture across all CC agents reduces context-switching cost and ensures Solara inherits the same improvement loops (self-healing, memory journaling, Codex delegation) that make CEO-Agent effective.

**Authoritative storage policy (inherited):** SunBiz-Agent business logic lives here (skills, memory, brain/). Runtime infrastructure (send_gateway.py, DB migrations, API routes) lives in the application code base. CEO-Agent is the CEO's agent; Solara is the client's operator agent — separate concerns.

**Related:** [[memory/ACTIVE_TASKS]] | [[skills/memory-journaling/SKILL.md]] | [[skills/codex-delegation/SKILL.md]]

---

## 2026-05-12 — SunBiz deploys as a tandem workspace, not a single-agent shell

**Context:** SunBiz Funding's workflow splits into system-of-record ops and high-velocity outbound meeting-setting.

**Decision:** Two-agent deployment: `sunbiz` / Solara for backend admin operations; `suga_sean` / Suga Sean for outreach and meeting-setting.

**Why:** Keeping both in one workspace preserves handoff speed without forcing one persona to own contradictory responsibilities.

**Implementation note:** Command center keeps `primary_agent="sunbiz"` while enabling both agents on the tenant profile.

---

## 2026-03-10 — Agent architecture mirrors Business Empire Agent

**Decision:** Mirror Business Empire Agent's file structure (brain/memory/agents/skills/workflows)

**Why:** Proven architecture with self-healing, self-improving capabilities. CC is familiar with it. Adaptations: marketing-specific agents, skills, workflows, lending compliance built-in.

---

## 2026-03-10 — Python SDK as fallback when MCP fails

**Decision:** Use google-ads and facebook-business Python SDKs as fallback when MCP fails.

**Why:** MCP servers can have bugs. Direct SDK gives full API access as backup.

**Packages:** google-ads v29.2.0 (API v23.1), facebook-business v22.0 (Graph API v22.0)

> Note (2026-05-25): The Google/Meta ads infrastructure is now archived to `skills/_archive/`. This decision is historical context for that era.

---

## Obsidian Links
- [[memory/PATTERNS]] | [[memory/MISTAKES]] | [[memory/CLIENT_CONTEXT]]
- [[skills/operator-handoff/SKILL.md]] | [[skills/memory-journaling/SKILL.md]]
