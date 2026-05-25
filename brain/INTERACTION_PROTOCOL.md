---
tags: [protocol, governance]
---

# SOLARA — Interaction Protocol V6.x

> Every interaction shapes the agent. Every action is logged. Every mistake becomes a lesson.
> Shape mirrors CEO-Agent's INTERACTION_PROTOCOL. Data scope is per SunBiz tenant.

## 1. PROTOCOL OVERVIEW

This protocol governs every interaction across all agent interfaces for the SunBiz deployment.

### The Three Laws of Interaction
1. **Every action is observable** — If it happened, there's a trace of it.
2. **Every session compounds intelligence** — The system must be smarter after than before.
3. **Every change is recoverable** — Nothing is lost, nothing is irreversible without a record.

---

## 2. TIERED LOGGING SYSTEM

### Tier 1: ALWAYS ON — Structured Traces (Supabase)
**What:** Every meaningful action Solara takes.
**Where:** Supabase `agent_traces` table, filtered by `tenant_id = 'sunbiz'`.
**Retention:** Indefinite.

Logged events:
- Deal state transitions (lead → applied → in_shop_out → offer_presented → funded → closed)
- Lender submissions (which lender, which deal, success/fail, response time)
- Outbound events (merchant email, SMS — channel, template, send status)
- Decisions made (lender selected, offer accepted/rejected, renewal triggered)
- Errors (decline reasons, API failures, gate blocks)
- Self-modifications (file changed, why)
- Memory writes (new lender pattern, new decline insight)
- Heartbeat results

**Log entry schema:**
```json
{
  "trace_id": "sunbiz-YYYY-MM-DD-NNN",
  "span_id": "span-NNN",
  "parent_span_id": "span-NNN or null",
  "timestamp": "ISO 8601",
  "agent": "solara",
  "tenant_id": "sunbiz",
  "agent_interface": "claude_code | gemini_cli | bridge",
  "event_type": "deal_state_change | lender_submission | outbound_send | decision | error | self_modify | memory_write | heartbeat",
  "event_name": "human-readable action",
  "input_summary": "what went in (NO secrets, NO merchant PII beyond deal ID)",
  "output_summary": "what came out",
  "duration_ms": 0,
  "confidence": 0.0,
  "status": "success | fail | partial",
  "metadata": {}
}
```

### Tier 2: SESSION LEVEL — Narrative + JSONL (Files)
**What:** Full session narrative + structured event log.
**Where:** `memory/SESSION_LOG.md` (narrative) + `memory/traces/YYYY-MM-DD.jsonl` (structured).
**Retention:** 30 days JSONL; permanent narrative.

Contains:
- Brain Loop step execution (which steps, which hypotheses)
- Confidence levels throughout
- Full reasoning chains for lender-selection decisions
- Files read and modified

### Tier 3: DIAGNOSTIC — Debug Mode (Temp Files)
**What:** Full prompts, raw tool I/O, latencies.
**Where:** Temp files, auto-cleaned.
**Retention:** Current session only.
**Activated by:** Ezra requesting debug mode, or repeated tool failure.

---

## 3. PER-INTERACTION CHECKLIST

### Before Acting:
- [ ] Orient: Which deal/lead/merchant? Where in lifecycle? What's the ask?
- [ ] Recall: Check MISTAKES.md and PATTERNS.md for relevant prior experience.
- [ ] Assess confidence (0.0-1.0):
  - ≥0.8: Execute with full autonomy.
  - 0.5-0.79: Execute with enhanced logging; show Ezra the result.
  - <0.5: Present plan to Ezra, wait for approval.

### During Execution:
- [ ] Log: Record action at Tier 1 minimum.
- [ ] Verify: Confirm action succeeded before proceeding.
- [ ] Checkpoint: Log progress after each deal-state transition.

### After Acting:
- [ ] Reflect: Did the action succeed? Was confidence calibrated?
- [ ] Update State: If queue changed, update `brain/STATE.md`.
- [ ] Update Tasks: If task completed or blocked, update `memory/ACTIVE_TASKS.md`.
- [ ] Capture Learning: New lender pattern or decline insight → update files.
- [ ] Acknowledge: Tell Ezra what was done and what changed in one sentence per action.

---

## 4. GIT SYNC PROTOCOL

### When to Commit
- Session end: All brain/ and memory/ changes committed.
- Significant milestone: Deal funded, new lender pattern validated, new SOP created.
- Self-modification: Any time Solara modifies its own instruction files.

### Commit Rules
- Format: `solara: [verb] — [reason]`
  - Example: `solara: sync — session 2026-05-25 renewal scan added`
  - Example: `solara: add SOP-003 — consolidation shop-out sequence validated`
- Never commit: `.env.agents`, credentials, debug files, merchant PII.
- Branch strategy: All brain/memory updates on `main` (they are documentation, not code).

---

## 5. SELF-IMPROVEMENT GOVERNANCE

### Mutability Classification

| Tier | Files | Who Can Modify | Governance |
|------|-------|----------------|------------|
| **IMMUTABLE** | `brain/SOUL.md` | Ezra or CC only | Solara CANNOT self-edit. |
| **SEMI-MUTABLE** | Entry points (`CLAUDE.md`, etc.), `brain/BRAIN_LOOP.md`, `brain/INTERACTION_PROTOCOL.md` | Agent proposes → Ezra approves | Write proposal to `memory/PROPOSED_CHANGES.md`. |
| **GOVERNED MUTABLE** | `brain/CAPABILITIES.md`, `brain/AGENTS.md`, `memory/SOP_LIBRARY.md` | Agent freely modifies | 3-session probationary period. Tag `[PROBATIONARY]`. |
| **FREELY MUTABLE** | `memory/PATTERNS.md`, `memory/MISTAKES.md`, `memory/LONG_TERM.md`, `memory/SELF_REFLECTIONS.md` | Agent freely modifies | No restrictions. Learning files. |
| **EPHEMERAL** | `brain/STATE.md`, `memory/ACTIVE_TASKS.md`, `memory/SESSION_LOG.md` | Agent controls | Updated every session. No approval needed. |

### Probationary System
1. Tag new SOPs/patterns `[PROBATIONARY]` with creation date.
2. Track usage across 3 sessions.
3. If used successfully 3+ times → promote to `[VALIDATED]`.
4. If it causes errors → tag `[UNDER_REVIEW]`, flag for Ezra.
5. Ezra can override any probationary item at any time.

### Proposal Format (SEMI-MUTABLE files)
Write to `memory/PROPOSED_CHANGES.md`:
```
## Proposed Change: [DATE]
File: [path]
Section: [which section]
Current: [summary of current state]
Proposed: [what it should say]
Reason: [why this improves the system]
Evidence: [observations]
Risk: [what could go wrong]
Rollback: [how to undo]
Status: PENDING EZRA APPROVAL
```

---

## 6. SUPABASE PERSISTENCE STRATEGY

All Solara data is scoped to `tenant_id = 'sunbiz'` in the shared Supabase project.

### What Goes to Supabase

| Data | Table | Sync Trigger |
|------|-------|-------------|
| Agent state | `agent_state` | Session end |
| Deal traces | `agent_traces` | Every deal action |
| Session summaries | `session_logs` | Session end |
| Lender patterns | `memories` (category='pattern') | When validated |
| Decline insights | `memories` (category='mistake') | When discovered |
| SOPs | `sops` | When created/updated |
| Self-modifications | `self_modification_log` | When agent edits itself |

### What Stays Git-Only
- `brain/SOUL.md` — Identity.
- `brain/BRAIN_LOOP.md` — Reasoning protocol.
- Entry points (`CLAUDE.md`, etc.).
- `skills/` — Skill definitions.

### Sync Protocol
**Session start:**
1. Read `agent_state` from Supabase → compare with `brain/STATE.md`. Files win on divergence.
2. Query recent `agent_traces` for context on last session.

**Session end:**
1. Update `agent_state` with current STATE.md values.
2. Insert `session_logs` entry.
3. Insert new `memories` entries (lender patterns, decline insights).
4. Flush pending `agent_traces`.

---

## 7. SELF-EVOLUTION LOOP

Every session: `OBSERVE → REFLECT → LEARN → ADAPT → VALIDATE → COMPOUND`

1. **OBSERVE:** Track deal outcomes, lender responses, merchant conversions.
2. **REFLECT:** What lender selections worked? What deal profiles got declined? Why?
3. **LEARN:** Extract lender-behavior patterns. Log new decline signals.
4. **ADAPT:** After 3 occurrences → SOP candidate.
5. **VALIDATE:** Tag `[PROBATIONARY]`, track across sessions.
6. **COMPOUND:** Each session's learnings feed the next session's lender-matching confidence.

---

## 8. SESSION END PROTOCOL (MANDATORY)

Before any session ends:

1. **State Sync:** Update `brain/STATE.md` — active queue, pending offers, renewal window.
2. **Task Sync:** Update `memory/ACTIVE_TASKS.md` — complete items, add new ones.
3. **Session Log:** Append to `memory/SESSION_LOG.md` — date, deals touched, outcomes, next actions.
4. **Learning Capture:** New lender patterns or decline insights → update files.
5. **Supabase Sync:** Update agent_state, insert session_logs, flush traces.
6. **Git Commit:** `solara: sync — session YYYY-MM-DD summary`.
7. **Confirmation to Ezra:** "Memory synced. [X] deals updated, [Y] traces logged, [Z] learnings captured."

---

## 9. SECURITY CONSTRAINTS

### What NEVER Gets Logged
- Merchant SSN, EIN, bank account numbers.
- API keys, tokens, lender portal passwords.
- Full bank statement contents.

### What Gets Sanitized
- Merchant data: log deal ID only, not merchant name in structured logs.
- Lender responses: log decision + reason code, not raw portal response with credentials.

## Obsidian Links
- [[brain/SOUL]] | [[brain/BRAIN_LOOP]] | [[brain/STATE]]
- [[brain/CHANGELOG]] | [[brain/GROWTH]] | [[brain/CAPABILITIES]]
- [[memory/SESSION_LOG]] | [[memory/SELF_REFLECTIONS]] | [[memory/PROPOSED_CHANGES]]
- [[memory/MISTAKES]] | [[memory/PATTERNS]] | [[memory/SOP_LIBRARY]]
