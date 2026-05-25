---
name: memory-journaling
description: Structured decision and pattern logging. Guides Solara through writing high-quality entries to memory/DECISIONS.md, memory/PATTERNS.md, or memory/MISTAKES.md with proper frontmatter, cross-links, and version tags.
tags: [skill, memory, journaling, decisions, patterns]
triggers:
  - "log a decision"
  - "journal this"
  - "memory journal"
  - "log this pattern"
  - "record this"
  - "save this learning"
  - "memory-journaling"
owner: solara
tier: stable
risk: low
---

# Memory Journaling — Structured Decision + Pattern Logging

## Overview

Memory drifts when entries are written ad-hoc — bullet here, paragraph there, no cross-links, no `last_updated` field, dates omitted. This skill enforces structure: every journal entry has a category, a date, a body shape per category, wiki-links to related files, and a freshness tag.

**When to invoke:**
- Ezra says "log this" / "journal that" / "save this learning"
- After a non-obvious decision is made (lender strategy, compliance call, architectural, business commitment)
- After a pattern proves itself in the SunBiz workflow (used successfully multiple times)
- After a mistake (root cause + prevention, not just "it went wrong")

**Trigger:** `/journal <category>`, "log a decision", "save this pattern"

## Category Routing

Pick the right file. If unsure, ask Ezra.

| Category | File | Use for |
|----------|------|---------|
| **Decision** | `memory/DECISIONS.md` | Lender strategy choices, compliance calls, product bets, scope cuts |
| **Pattern** | `memory/PATTERNS.md` | Validated approaches that worked — repeat-worthy workflows |
| **Mistake** | `memory/MISTAKES.md` | Failure modes — what went wrong, why, prevention |
| **Client Context** | `memory/CLIENT_CONTEXT.md` | New facts about Ezra's team, lender book, deal volume |

## Entry Shapes

### Decision entry

```markdown
## YYYY-MM-DD — <one-line title>

**Context:** What was the situation? Constraints?

**Decision:** What we chose. Be specific — names, numbers, lender names, deal IDs.

**Why:** The reasoning. Tradeoffs accepted.

**Alternatives rejected:** What else was on the table + why we passed.

**Related:** [[memory/CLIENT_CONTEXT]] | [[skills/lender-intelligence/SKILL.md]] | (commit or deal ID if applicable)
```

### Pattern entry

```markdown
## [P] / [V] — <pattern name>

**Pattern:** One sentence — what the pattern is.

**When:** The trigger condition.

**How:** The step-by-step.

**Why it works:** The mechanism.

**Uses:** N (increment per re-use; promote [P] → [V] at 3)

**First seen:** YYYY-MM-DD | **Last validated:** YYYY-MM-DD

**Related:** [[skills/X/SKILL.md]]
```

Probationary `[P]` → validated `[V]` after 3 successful re-uses. Track the count in the body.

### Mistake entry

```markdown
## YYYY-MM-DD — <short title>

**Failure:** What happened (1-2 sentences, observable).

**Root cause:** Why it happened — the actual cause, not the symptom.

**Prevention:** Concrete rule or system change that prevents recurrence.

**Tag:** [compliance | workflow | lender | data | communication]
```

If the mistake is a workflow gap (e.g., "forgot to run CASL check before sending"), add a check to the relevant skill's guardrails section.

## Execution Protocol

1. **Classify.** Decision / Pattern / Mistake / Client Context. Ask Ezra if ambiguous — never guess.
2. **Compose the entry** per the matching shape above. Always include today's date (compute it — never quote from context).
3. **Cross-link.** Every entry MUST link to at least 2 related files via `[[wiki-link]]` syntax.
4. **Append, don't overwrite.** Insert at the TOP of the target file (newest first), below the frontmatter.
5. **Update `memory/MEMORY.md` index** if the entry is high-leverage (something future-Solara needs without grepping). One-line pointer: `- [Title](file.md) — one-line hook`.
6. **Confirm in chat.** "Logged <category> to memory/<file>.md: '<title>'. <N> wiki-links added."

## Anti-Patterns

- Quoting today's date from a system reminder instead of computing it. Always compute.
- One-line entries with no Why. Future-Solara won't understand the decision context.
- Zero wiki-links. Disconnected entries decay into orphan trivia.
- Writing a mistake without a prevention. Identifying failure without fixing it is theatre.
- Editing an old entry to update facts. Append a new entry that supersedes it; keep the original for the audit trail.

## When NOT to Journal

- Trivial fixes (typo, wrong field in a form) — git log covers it
- Conversational context that's only useful in the current session — that's plan/todo territory, not memory
- Anything the system already logs automatically (API responses, follow-up task creation)

## Integration

- **memory/DECISIONS.md / PATTERNS.md / MISTAKES.md** — the target files
- **memory/MEMORY.md** — the index pointing to high-leverage entries
- **memory/CLIENT_CONTEXT.md** — client-specific facts that evolve over time

## Obsidian Links
- [[memory/DECISIONS]] | [[memory/PATTERNS]] | [[memory/MISTAKES]] | [[memory/CLIENT_CONTEXT]]
- [[skills/operator-handoff/SKILL.md]] | [[skills/systematic-debugging/SKILL.md]]
