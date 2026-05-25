---
name: PATTERNS
description: Validated and probationary workflow patterns for SunBiz-Agent. Promote [P] → [V] after 3 successful uses.
last_updated: 2026-05-25
---

# PATTERNS — Validated Approaches

> Tag new patterns as `[PROBATIONARY]`. Promote to `[VALIDATED]` after 3+ successful uses.
> Track use count in each entry body.

---

## [PROBATIONARY] Dry-Run Before Every Shop-Out

- **Pattern:** Always POST with `dry_run: true` before the live shop-out. Surface the plan to Ezra before executing.
- **When:** Operator says "shop this deal" or "send to lenders"
- **Why it works:** Prevents unsanctioned submissions, surfaces warnings before they become problems, builds operator trust.
- **Uses:** 0 (new — 2026-05-25)
- **Related:** [[skills/shop-out-routing/SKILL.md]]

## [PROBATIONARY] Compliance Gate Always Before Outbound

- **Pattern:** Route through `skills/casl-compliance/SKILL.md` before ANY email, SMS, or blast — no exceptions.
- **When:** Any outbound action is queued
- **Why it works:** CASL violations are $10M+ fines. The check is cheap; the violation is not.
- **Uses:** 0 (new — 2026-05-25)
- **Related:** [[skills/casl-compliance/SKILL.md]] | [[skills/cold-outreach-blast/SKILL.md]]

## [PROBATIONARY] Operator Handoff on D-Paper

- **Pattern:** When underwriting returns paper_grade D, always escalate to Ezra via `skills/operator-handoff/SKILL.md` before any further action.
- **When:** `GET /api/applications/[id]/underwriting/latest` returns `paper_grade: "D"`
- **Why it works:** D-paper deals require human judgment on whether to decline, hold, or restructure — Solara does not have enough context to make this call unilaterally.
- **Uses:** 0 (new — 2026-05-25)
- **Related:** [[skills/operator-handoff/SKILL.md]] | [[skills/underwriting-flow/SKILL.md]]

---

## Pre-V6 Patterns (From AdVantage Era — Review Before Using)

## [PROBATIONARY] Meta MCA Ad Category

- **Pattern:** ALL MCA/funding ads on Meta MUST include `special_ad_categories: ['CREDIT']`
- **Why:** Meta requires this for any ad related to credit, funding, or financial services
- **Impact:** Ads without this will be rejected. Targeting restricted (no age, gender, zip, lookalike)
- **Source:** Meta Advertising Standards, research 2026-03-10
- **Uses:** 0 (inherited — not yet validated in current Solara ops context)

## [PROBATIONARY] MCA Language Compliance

- **Pattern:** NEVER use "loan," "lender," "lending," "borrower," "interest rate" in any MCA communication
- **Why:** MCA is a purchase of future receivables, NOT a loan. Legal/compliance distinction.
- **Use instead:** "advance," "funding," "capital," "funder," "merchant," "factor rate"
- **Source:** SunBiz Funding SOP, FTC enforcement actions
- **Related:** [[skills/funding-vocabulary/SKILL.md]]

## [PROBATIONARY] Windows MCP Env Variable Fix

- **Pattern:** Use `.cmd` wrapper scripts to inject environment variables for MCP servers on Windows
- **Why:** JSON `env` blocks in MCP configs don't reliably pass vars to subprocesses on Windows
- **How:** Create `scripts/xxx-mcp-wrapper.cmd` that sets vars then launches the server
- **Source:** Inherited from Business Empire Agent (VALIDATED there)

## [PROBATIONARY] Multi-Hypothesis Approach

- **Pattern:** For moderate+ tasks, generate 2-3 candidate approaches, rank, execute best
- **Why:** Prevents getting stuck on one bad approach
- **Max attempts:** 3 total across all approaches, then escalate
- **Source:** Inherited from Business Empire Agent (VALIDATED there)
- **Related:** [[skills/systematic-debugging/SKILL.md]]

## Obsidian Links
- [[memory/DECISIONS]] | [[memory/MISTAKES]] | [[memory/ACTIVE_TASKS]]
- [[skills/memory-journaling/SKILL.md]]
