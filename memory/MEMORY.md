---
name: MEMORY
description: Index of all SunBiz-Agent memory files. One-line hook per file. Read this first; Read individual files only when the snippet is insufficient.
last_updated: 2026-05-25
---

# MEMORY — Index

> One-line entry per file. Keep entries under 200 chars. Move detail into topic files.
> When adding a new high-leverage memory entry, add a pointer here.

## Operational State

- [ACTIVE_TASKS.md](ACTIVE_TASKS.md) — rolling priority queue; current blockers and next actions for Solara + SunBiz ops
- [SESSION_LOG.md](SESSION_LOG.md) — append-only session history; what shipped, what changed, what was decided
- [OPERATIONAL_STATE.md](OPERATIONAL_STATE.md) — campaign tracker, active deals, pipeline snapshot (legacy from AdVantage era, review before using)

## Decision Log

- [DECISIONS.md](DECISIONS.md) — architectural and business decisions; lender strategy calls; compliance overrides with context
- [PATTERNS.md](PATTERNS.md) — validated + probationary workflow patterns; promote [P] → [V] after 3 uses
- [MISTAKES.md](MISTAKES.md) — failure log with root cause + prevention; every mistake logged once, never repeated

## Client & Domain Context

- [CLIENT_CONTEXT.md](CLIENT_CONTEXT.md) — SunBiz Funding operator details (Ezra, Jordan, Ethan, Emily), lender book, deal volume, notable relationships
- [SOP_LIBRARY.md](SOP_LIBRARY.md) — standard operating procedures inherited from AdVantage era; audit before relying on

## Legacy AdVantage Era Files (lower signal for funding-shop ops)

- [AD_PERFORMANCE.md](AD_PERFORMANCE.md) — ad campaign metrics from the advertising era; archived context
- [CAMPAIGN_TRACKER.md](CAMPAIGN_TRACKER.md) — campaign records from March 2026; legacy
- [PROPOSED_CHANGES.md](PROPOSED_CHANGES.md) — staging area for semi-mutable file changes
- [SELF_REFLECTIONS.md](SELF_REFLECTIONS.md) — agent introspection and growth observations
- [LONG_TERM.md](LONG_TERM.md) — long-term strategic goals and vision

## Notes on Index Discipline

- Each new session that produces a high-leverage memory (decision, pattern, mistake) should add a 1-line pointer here.
- Keep entries under 200 chars — move detail into the target file.
- Files not listed here are either ephemeral or low-signal; check the `memory/` directory directly.
