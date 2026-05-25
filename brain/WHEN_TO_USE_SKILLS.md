---
name: WHEN TO USE SKILLS
description: One-line trigger map per skill. Solara reads this once, knows which skill body to lazy-load when.
mutability: SEMI-MUTABLE
tags: [brain, agent-only, skills-index]
last_updated: 2026-05-25
---

# WHEN TO USE SKILLS (SunBiz V6.x)

> This index is the cheap router: trigger phrase → skill name → when NOT to use.
> Read the skill's own `SKILL.md` body only after deciding it's the right one.
> If a trigger isn't listed here, run `python scripts/capability_query.py resolve "<task>" --json` if available, or check `skills/INDEX.md`.

---

## Deal Lifecycle

| Trigger | Skill | Don't use when |
|---|---|---|
| Pre-screen application, score paper, check TAR band | `deal-scoring` | Simple position-count lookup — query `applications` table directly |
| Shop-out a deal to lenders | `shop-out` (playbook: `brain/INTENTS.md`) | Status check only — `deal_tracker.py list` is enough |
| Format lender offer for merchant | `offer-formatting` | Raw terms review — read `offers` row directly |
| Renewal identification + outreach kickoff | `renewal-pipeline` | Single deal renewal — `brain/INTENTS.md` "kick off renewal" playbook |
| Commission math / factor rate lookup | `funding-intel` (CLI direct: `funding_intel.py`) | Estimating — always compute, never guess |
| All-decline root cause | `decline-analysis` | Single lender decline — classify reason and re-shop |

## Outbound / Comms

| Trigger | Skill | Don't use when |
|---|---|---|
| Send merchant email (compliant) | `outreach-send` (routes through `send_gateway.py`) | Internal note — log to `agent_traces` only |
| Send merchant SMS (compliant) | `outreach-send` (routes through `send_gateway.py`) | Checking SMS status — `sms_engine.py status` |
| Enroll lead in drip sequence | `drip-enrollment` (playbook: `brain/INTENTS.md`) | Single one-off message — `follow_up_generator.py draft` + `send_gateway.py send` |
| Cold outreach blast to imported list | `cold-outreach` (`cold_outreach_runner.py dry-run` first — operator-initiated only) | Warm leads already in sequence — use `sequence_runner.py` |
| Draft next merchant touch | `follow-up-generation` (CLI direct: `follow_up_generator.py draft`) | Full sequence — use `sequence_runner.py start` |

## Lender Intelligence

| Trigger | Skill | Don't use when |
|---|---|---|
| Look up lender appetite for a deal profile | `lender-matching` (reads `memory/PATTERNS.md` + `memory/LONG_TERM.md`) | Formal submission — that's `shop_out_sender.py` |
| Research a new lender (terms, criteria, portal) | `lender-research` (spawns lender-researcher sub-agent) | Known lender — check `memory/LONG_TERM.md` first |
| Track funder approval/decline trends | `lender-intelligence` (weekly report: `brain/HEARTBEAT.md` Friday schedule) | One-deal lookup — check `agent_traces` for that lender |

## Memory / State

| Trigger | Skill | Don't use when |
|---|---|---|
| Log a lender pattern | (write to `memory/PATTERNS.md` directly, tag `[PROBATIONARY]`) | Already `[VALIDATED]` — just reference it |
| Log a decline insight / mistake | (write to `memory/MISTAKES.md` directly) | Success — log to `PATTERNS.md` instead |
| Stale memory scan | `memory-management` | Single file — read it directly |
| Context compaction | `context-optimization` | Conversation is manageable |

## Operations / Reporting

| Trigger | Skill | Don't use when |
|---|---|---|
| Daily brief + call sheet | `daily-plan` (CLI direct: `daily_plan_generator.py`) | Weekly — build manually from deal_tracker + renewal_reminder |
| Funded deal summary | (CLI direct: `deal_tracker.py list --status funded --since today`) | Full report — use `funding_intel.py commission --period month` |
| System / repo health check | `doctor` (CLI: `python scripts/doctor.py`) | Single script check — run the script directly |

## Code / Infrastructure

| Trigger | Skill | Don't use when |
|---|---|---|
| Root cause a script error | `systematic-debugging` | Known error — fix directly |
| Pre-ship review | `code-review` | Post-ship — log to `MISTAKES.md` |
| Scrape a URL (lender portal, public page) | `research-fetch` (auto-escalates Firecrawl→Cloak) | CC's logged-in session — use `browser-harness` |
| Bot-protected lender portal scrape | `cloak-browser` | Simple public page — `research-fetch` handles it |

## Agent Infrastructure

| Trigger | Skill | Don't use when |
|---|---|---|
| Heartbeat to V6 substrate | (CLI direct: `state_bridge.py heartbeat`) | Full state sync — `state_bridge.py sync` |
| Hand off to Helios | (CLI direct: `agent_inbox.py post --to helios`) | Reading Helios updates — `agent_inbox.py list --to solara` |
| New skill needed | `skill-creator` checklist (check `brain/SOUL.md` + compliance before drafting) | Existing skill covers it |
| Debugging reasoning failures | (read `brain/BRAIN_LOOP.md` Reflexion section + `memory/MISTAKES.md`) | — |

---

> Skills directory: `skills/`. Each skill has a `SKILL.md` with trigger map, preconditions, and step-by-step.
> To add a new skill: scaffold via register script (if available) or follow the skill-creator checklist.
> Skills in `skills/_archive/` are retired — do not use. Skills in `skills/in-progress/` are drafts — treat as `[PROBATIONARY]`.
