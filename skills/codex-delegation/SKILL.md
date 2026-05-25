---
name: codex-delegation
description: Intelligent routing between Solara and Codex — decides when to delegate backend tasks to Codex vs handle internally.
tags: [skill]
triggers:
  - "codex delegation"
  - "use codex delegation"
  - "run codex delegation"
tier: stable
---

# Codex Delegation — Dual-AI Routing for SunBiz-Agent

> **Purpose:** Solara and Codex are complementary. This skill determines WHEN and HOW to delegate
> work to Codex for maximum leverage.

## The Dual-AI Split

```
Solara (Claude)                        Codex (GPT-5.4)
├── Funding workflow orchestration      ├── Backend API implementation
├── Lender intelligence synthesis       ├── Deep debugging with stack traces
├── Operator handoff + comms            ├── Adversarial code review
├── Memory / state management           ├── Parallel backend tasks
├── CASL compliance judgment            ├── Root-cause analysis
└── Call sheet + daily ops              └── Write-capable rescue tasks
```

## Delegation Decision Matrix

### Auto-Delegate to Codex (No Ezra approval needed)

| Task Type | Why Codex |
|-----------|-----------|
| Pre-ship code review of API changes | Second pair of eyes catches blind spots |
| Backend bug with stack trace in logs | Codex excels at systematic root-cause |
| Implementing a new API endpoint | Runs in background while Solara works on ops |
| Test suite debugging | Codex is strong at test diagnosis |
| Database query optimization | Codex handles SQL + performance analysis well |

### Keep in Solara (Never delegate)

| Task Type | Why Solara |
|-----------|-----------|
| Funding workflow decisions | Requires domain context + operator relationship |
| CASL compliance judgment calls | Regulatory + business context needed |
| Lender relationship intelligence | Solara has the historical context |
| Operator handoff messages | Must match Ezra's communication style |
| Memory/state/context files | Solara's domain — Codex has no access |
| Simple fixes (< 3 files) | Delegation overhead > task effort |

## How to Delegate

```bash
export CLAUDE_PLUGIN_ROOT="/c/Users/User/.claude/codex-plugin"
node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" task --write \
  "Context: SunBiz-Agent — Next.js 14 App Router, Supabase, TypeScript.
   Stack: scripts/integrations/send_gateway.py is the single outbound send path.
   Task: [specific task description]
   Constraint: [any constraints]"
```

Always inject context: stack, file paths, constraints, what Solara has already done.

## Pre-Flight Check

Before delegating, verify Codex CLI is operational:
```bash
codex --version 2>&1 | head -1
```
If command not found: `npm i -g @openai/codex@latest`
If version is stale (symptoms: every model alias rejected, companion loops with no progress): upgrade first.

## Failure Recovery — 3-Strike Rule

1. **First failure:** Retry with more context (inject file contents, narrow scope)
2. **Second failure:** Switch to `--model spark` (simpler tasks) or `--model gpt-5.4-mini` (faster)
3. **Third failure:** Solara takes over. Log to `memory/MISTAKES.md` with what Codex struggled with.

Never retry the same prompt 3 times unchanged.

## End-of-Task Audit (MANDATORY for big tasks)

After any task with ≥3 commits, ≥5 files touched, or any user-facing change:

```bash
node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" review --wait
```

Present both reviews verbatim to Ezra — Solara's self-review first, then Codex's audit under a clear header. Do not paraphrase or soften Codex findings.

## Commands Quick Reference

```bash
# Standard review
node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" review --wait

# Adversarial design challenge
node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" adversarial-review --wait "challenge the lender-match scoring logic"

# Delegate a task
node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" task --write "<context + task>"

# Check status
node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" status

# Get results
node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" result
```

## Obsidian Links
- [[skills/systematic-debugging/SKILL.md]] | [[skills/operator-handoff/SKILL.md]]
- [[memory/MISTAKES]] | [[memory/PATTERNS]]
