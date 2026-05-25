---
name: MISTAKES
description: Failure log with root cause and prevention for every SunBiz-Agent error. Append-only. New entries at top.
last_updated: 2026-05-25
---

# MISTAKES — Error Log & Root Cause Analysis

> Append-only. New entries at the top. Every mistake is logged once — never repeated.
> Format: failure (observable) → root cause (actual) → prevention (concrete rule or system change).
>
> If the prevention is regex-detectable, add to `memory/ANTI_PATTERNS.json` so the hook flags future occurrences.

---

*No mistakes logged yet. This section will populate as operations begin.*

## Entry Template

```markdown
## YYYY-MM-DD — [Short Title]

**Failure:** What happened (1-2 sentences, observable).

**Root cause:** The actual underlying cause — not the symptom.

**Prevention:** A concrete rule or guardrail added to prevent recurrence. Be specific — name the skill, the file, or the check.

**Tag:** [compliance | workflow | lender | data | communication | architecture]

**Related:** [[skills/X/SKILL.md]] | [[memory/DECISIONS]]
```

## Obsidian Links
- [[memory/PATTERNS]] | [[memory/DECISIONS]] | [[memory/ACTIVE_TASKS]]
- [[skills/systematic-debugging/SKILL.md]] | [[skills/memory-journaling/SKILL.md]]
