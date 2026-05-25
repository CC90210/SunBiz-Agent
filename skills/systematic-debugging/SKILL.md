---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior in SunBiz-Agent systems — before proposing any fix.
triggers:
  - "bug"
  - "error"
  - "failure"
  - "crash"
  - "broken"
  - "not working"
  - "debug"
  - "stack trace"
  - "API returning wrong data"
tier: stable
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue in SunBiz-Agent:
- API errors (shop-out, underwriting, follow-up endpoints)
- Send gateway failures (email/SMS not delivered)
- Underwriting agent not returning results
- Database query returning unexpected data
- Integration failures (Supabase, SendGrid, Twilio)
- Build failures, test failures, unexpected behavior

**Use especially when under time pressure or when a deal is at risk.**

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read error messages completely** — stack trace, status code, error body, all of it
2. **Reproduce consistently** — can you trigger it reliably? What are the exact inputs?
3. **Check recent changes** — what changed that could cause this? `git log -10`, recent migrations
4. **Gather evidence in multi-component systems**

   For SunBiz-Agent's layered architecture (Next.js → API route → Supabase → send_gateway):
   ```
   For EACH component boundary:
     - Log what data enters the component
     - Log what data exits
     - Check env vars are set at each layer
     - Verify the DB row state at each step
   ```

5. **Trace data flow** — where does the bad value originate? Trace backward to the source.

### Phase 2: Pattern Analysis

1. Find working examples — does the same endpoint work with different inputs?
2. Compare against the API contract — what does the endpoint spec say?
3. Identify differences — what's different between working and broken?
4. Understand dependencies — is send_gateway healthy? Is Supabase responding?

### Phase 3: Hypothesis and Testing

1. **Form a single hypothesis** — "I think X is the root cause because Y"
2. **Test minimally** — smallest possible change to test the hypothesis, one variable at a time
3. **Verify before continuing** — if it works, proceed to Phase 4; if not, form a new hypothesis
4. **When you don't know** — say "I don't understand X" — ask Ezra or escalate to Codex

### Phase 4: Implementation

1. **Create a failing test case** — reproduce the bug with a test before fixing
2. **Implement a single fix** — address the root cause, not the symptom
3. **Verify the fix** — does the test pass? No other behavior broken?
4. **If 3+ fixes failed** — question the architecture. Discuss with Ezra before attempting more.

## 5 Whys Template

```
Problem: [one specific sentence]

Why 1: Why did [problem] occur? → [cause]
Why 2: Why did [cause] occur? → [deeper cause]
Why 3: Why did [deeper cause] occur? → [system issue]
Why 4: Why did [system issue] occur? → [process/design gap]
Why 5: Root cause.

Fix: [addresses root cause, not symptoms]
Prevention: [added to skill guardrails or memory/MISTAKES.md]
```

## Red Flags — STOP and Return to Phase 1

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run and see"
- "It's probably X" without tracing data flow
- "One more fix attempt" when you've already tried 2+
- Each fix reveals a new problem in a different place

## Log Every Bug

After resolution, log to `memory/MISTAKES.md`:
- What happened (observable)
- Root cause (actual)
- Prevention (concrete rule)

If the bug revealed a gap in a skill's guardrails, add the check to that skill's **Guardrails** section.

## Related Skills

- [[skills/codex-delegation/SKILL.md]] — delegate complex backend bugs to Codex
- [[skills/operator-handoff/SKILL.md]] — if a bug affects a live deal or merchant interaction
- [[memory/MISTAKES]] — log all resolved bugs here
