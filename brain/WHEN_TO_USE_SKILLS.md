---
name: WHEN TO USE SKILLS
description: One-line trigger map per skill. Solara reads this once, knows which skill body to lazy-load when.
mutability: SEMI-MUTABLE
tags: [brain, agent-only, skills-index]
last_updated: 2026-05-25
---

# WHEN TO USE SKILLS (SunBiz V6.x)

> **Verification note:** Skills listed without a `(CEO-Agent)` tag must exist in `skills/`.
> SunBiz-specific skills: `ls skills/ | grep -v '^_'` — every entry should resolve.
> Cross-agent cognitive skills (marked `(CEO-Agent)`) live in `~/Business-Empire-Agent/skills/`
> and are inherited by Solara at runtime — they do NOT need a local copy.
>
> This index is the cheap router: trigger phrase → skill name → when NOT to use.
> Read the skill's own `SKILL.md` body only after deciding it's the right one.
> If a trigger isn't listed here, consult `brain/AGENT_ROUTER.md` for routing-by-intent.
> Legacy retired skills are in `skills/_archive/` — do not use.

---

## Deal Lifecycle

| Trigger | Skill | Don't use when |
|---|---|---|
| Pre-screen application, score paper, check TAR band | `underwriting-flow` | Simple position-count lookup — query `applications` table directly |
| Shop-out a deal to lenders | `shop-out-routing` (playbook: `brain/INTENTS.md`) | Status check only — query `applications` table directly |
| Format lender offer for merchant | `funding-vocabulary` (terminology reference) | Raw terms review — read `offers` row directly |
| Renewal identification + outreach kickoff | `renewal-window-detection` | Single deal renewal — `brain/INTENTS.md` "kick off renewal" playbook |
| Commission math / factor rate lookup | `funding-vocabulary` (glossary) | Estimating — always compute, never guess |
| All-decline root cause | `lender-intelligence` (approval/decline pattern history) | Single lender decline — classify reason and re-shop |

## Outbound / Comms

| Trigger | Skill | Don't use when |
|---|---|---|
| Send merchant email (compliant) | `email-outbound` (routes through dashboard send gateway) | Internal note — log to `agent_traces` only |
| Send merchant SMS (compliant) | `email-outbound` + `casl-compliance` gate | Checking SMS status — query `sms_engine.py status` directly |
| Enroll lead in drip sequence | (playbook: `brain/INTENTS.md` "drip enrollment") | Single one-off message — `follow_up_generator.py once` |
| Cold outreach blast to imported list | `cold-outreach-blast` (`cold_outreach_runner.py once --dry-run` first — operator-initiated only) | Warm leads already in sequence — use `sequence_runner.py once` |
| Draft next merchant touch | `follow-up-discipline` (CLI assist: `follow_up_generator.py once`) | Full sequence — use `sequence_runner.py once` |

## Lender Intelligence

| Trigger | Skill | Don't use when |
|---|---|---|
| Look up lender appetite for a deal profile | `lender-intelligence` (reads `memory/PATTERNS.md` + `memory/LONG_TERM.md`) | Formal submission — that's `shop_out_sender.py once` |
| Research a new lender (terms, criteria, portal) | `lender-intelligence` (spawns lender-researcher sub-agent) | Known lender — check `memory/LONG_TERM.md` first |
| Track funder approval/decline trends | `lender-intelligence` (weekly report: `brain/HEARTBEAT.md` Friday schedule) | One-deal lookup — check `agent_traces` for that lender |

## Compliance

| Trigger | Skill | Don't use when |
|---|---|---|
| Pre-send compliance gate (CASL, consent, opt-out) | `casl-compliance` | Internal note or draft — only required before actual send |
| MCA / advance terminology clarification | `funding-vocabulary` | Calculating deal math — use `underwriting-flow` |

## Memory / State

| Trigger | Skill | Don't use when |
|---|---|---|
| Log a lender pattern | (write to `memory/PATTERNS.md` directly, tag `[PROBATIONARY]`) | Already `[VALIDATED]` — just reference it |
| Log a decline insight / mistake | (write to `memory/MISTAKES.md` directly) | Success — log to `PATTERNS.md` instead |
| Stale memory scan | `memory-journaling` (CEO-Agent) | Single file — read it directly |
| Context compaction | `context-optimization` (CEO-Agent) | Conversation is manageable |

## Operations / Reporting

| Trigger | Skill | Don't use when |
|---|---|---|
| Daily brief + call sheet | `daily-call-sheet-workflow` (CLI assist: `daily_plan_generator.py once`) | Weekly — build manually from renewal_reminder + lender_response_classifier |
| Funded deal summary | (CLI direct: `renewal_reminder.py once --json`) | Full report — use `lender-intelligence` weekly pattern |
| System / repo health check | `systematic-debugging` (CLI: `python scripts/doctor.py`) | Single script check — run the script directly |
| Operator pause / decision boundary | `operator-handoff` | Routine data pull or reversible action — act autonomously |

## Code / Infrastructure

| Trigger | Skill | Don't use when |
|---|---|---|
| Root cause a script error | `systematic-debugging` | Known error — fix directly |
| Pre-ship review | `code-review` (CEO-Agent) | Post-ship — log to `MISTAKES.md` |
| Scrape a URL (lender portal, public page) | `research-fetch` (CEO-Agent, auto-escalates Firecrawl→Cloak) | CC's logged-in session — use `browser-harness` |
| Bot-protected lender portal scrape | `cloak-browser` (CEO-Agent) | Simple public page — `research-fetch` handles it |

## Agent Infrastructure

| Trigger | Skill | Don't use when |
|---|---|---|
| Heartbeat to V6 substrate | (CLI direct: `~/Business-Empire-Agent/scripts/state/state_sync.py --note "<summary>"`) | Single-field heartbeat only — `state_manager.py heartbeat` |
| Hand off to Helios | (CLI direct: `~/Business-Empire-Agent/scripts/core/agent_inbox.py post --to helios`) | Reading Helios updates — `agent_inbox.py list --to solara` |
| New skill needed | `skill-creator` checklist (CEO-Agent; check `brain/SOUL.md` + compliance before drafting) | Existing skill covers it |
| Debugging reasoning failures | (read `brain/BRAIN_LOOP.md` Reflexion section + `memory/MISTAKES.md`) | — |

---

> Skills directory: `skills/`. Each skill has a `SKILL.md` with trigger map, preconditions, and step-by-step.
> To add a new skill: follow the skill-creator checklist.
> Skills in `skills/_archive/` are retired — do not use.
> For routing-by-intent (when no trigger matches): consult `brain/AGENT_ROUTER.md`.
