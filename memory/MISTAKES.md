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

### 2026-07-12 — Verified a daemon "fixed" from a shell whose env didn't match the daemon's
- **Failure:** Ported sentinel + classifier LLM calls to `from lib.claude_cli import run_claude_cli` and "proved" it with `classify_sentiment` returning `source=llm`. An independent review then showed the import raises `ModuleNotFoundError` in the REAL pm2 daemon — the LLM path was silently falling back to deterministic scoring the whole time.
- **Root cause:** The pm2 daemons run with `BRAVO_AGENT_ROOT=/srv/sunbiz/ceo-agent` set, so `bootstrap_bravo_path()` inserts CEO-Agent/scripts at `sys.path[0]` and the `lib` package binds to CEO-Agent's lib (which has no `claude_cli.py`). My verification shell did NOT export `BRAVO_AGENT_ROOT`, so bootstrap found no CEO-Agent, `lib` resolved to SunBiz's own lib, and the import succeeded — a false pass. Two `scripts/lib/` packages with the same name = whichever is first on `sys.path` wins (regular packages don't merge).
- **Prevention:** (1) When verifying a daemon behavior, replicate the daemon's EXACT runtime — interpreter (`pm2 describe` → the venv), cwd, AND env vars (`BRAVO_AGENT_ROOT`, etc. from the ecosystem `env:` block). A green result from a mismatched shell is not proof. (2) For cross-repo shared modules that exist under a shadowed package name, load by absolute path via `importlib.util.spec_from_file_location`, never `from lib.X`. (3) Same latent shadow still exists in `agent_sleep.py:~153` (`from lib.claude_cli`) — fix when touched.

*(older: no mistakes were logged before this date.)*

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
