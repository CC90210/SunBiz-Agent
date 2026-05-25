---
tags: [reasoning, protocol]
---

# BRAIN LOOP — 10-Step Reasoning Protocol (SunBiz V6.x)

> Every significant action passes through this loop. For trivial tasks (status lookups, single-field updates), steps 1-3 and 6 suffice.
> Adapted from CEO-Agent V5.5 BRAIN_LOOP. Funding-domain examples replace empire examples throughout.

## The Loop

### Step 1: ORIENT
Ground the task before touching anything:
- **Which entity is this about?** Lead ID / Application ID / Deal ID / Merchant name.
- **Where in the lifecycle?** Lead → Applied → In-Shop-Out → Offer-Presented → Funded → Renewal-Window → Closed.
- **What is Ezra's actual ask?** Distinguish "show me status" from "take action."
- Load: `brain/SOUL.md` (who I am) → `brain/USER.md` (operator) → `brain/STATE.md` (live queue state).

### Step 2: RECALL (Activation-Scored Retrieval)
Before acting, check prior context:
- `memory/MISTAKES.md` — Did a similar shop-out fail before? Why?
- `memory/PATTERNS.md` — Is there a `[VALIDATED]` lender match pattern for this paper profile?
- `memory/SOP_LIBRARY.md` — Is there a shop-out SOP for this deal type?
- `memory/SELF_REFLECTIONS.md` — Prior reflections on declined deal profiles.
- Supabase `memories` — Semantic search for lender-behavior patterns, deal-profile clusters.
- Supabase `skill_activation` — Which shop-out patterns are most active for this merchant category?

### Step 3: ASSESS (+ Task Routing)
- What do I know with high confidence? (verified application data, lender appetite on file)
- What am I uncertain about? (merchant's current position count, hidden NSFs, stacking exposure)
- What are the risks? Is this action irreversible? (sending to lender, marking funded, outbound to merchant)
- **Classify complexity:** TRIVIAL / MODERATE / COMPLEX / ARCHITECTURAL
- Confidence level: HIGH (>0.8) / MEDIUM (0.5-0.8) / LOW (<0.5)
- If LOW on critical deal data → surface the gap to Ezra before proceeding.

### Step 4: PLAN (Multi-Hypothesis — Funding Decisions)
For MODERATE+ tasks, generate 2-3 candidate approaches and rank:

**Shop-out hypothesis examples:**
- A: Submit to Lender X (highest approval rate for this TAR band) with full package — estimated approval 72h
- B: Submit to Lenders X + Y simultaneously (parallel shops) — faster offers, higher stacking transparency risk
- C: Pre-screen with Lender X underwriter via phone before formal submission — slower but protects relationship if paper is borderline

**Declined deal re-shop hypotheses:**
- A: Address the specific decline reason (NSF count, position count) — request updated bank statements
- B: Re-shop to a different lender tier that accepts higher-risk paper at adjusted buy rate
- C: Escalate to Ezra — this merchant may not be fundable at current leverage ratio

Rank approaches by: approval probability, funder-relationship cost, time-to-funded, merchant outcome.
Select best approach; track alternatives for backtracking.

For COMPLEX (multi-lender, multi-position, stacking-risk) decisions: present ranked options to Ezra before executing.
For LOW confidence (<0.5): always present plan to Ezra first.

### Step 5: VERIFY
Before executing any shop-out or state mutation:
- Does this violate any SOUL.md compliance constraints? (TCPA, CASL, no "loan" language, no approval guarantees)
- Does this match a `[VALIDATED]` lender pattern in memory?
- Does this avoid known mistakes (e.g., submitting to Lender X when position count >3)?
- Have I read the application data I'm acting on? (Never act on remembered values.)
- Is the merchant's opt-in state verified for any outbound SMS or email?

### Step 6: EXECUTE (+ Anti-Drift Monitoring)
- One action at a time. Confirm each result before proceeding.
- Log each meaningful action to Supabase `agent_traces`.
- Anti-drift checkpoint every 5 steps: validate alignment with original intent. If scope has drifted (e.g., touched 3 deals when Ezra asked about 1), pause and check.
- If a step fails: try alternative approach from Step 4 before retrying.
- If 2 consecutive steps fail → stop, report findings to Ezra.
- Protect secrets. Confirm before any outbound action (submit to lender, send to merchant).

### Step 7: REFLECT (Reflexion Protocol — Especially for Failed Shop-Outs)
When all lenders decline a package:
1. What was submitted? (deal profile: revenue, positions, NSFs, TIB, industry)
2. Which lenders declined? What were the stated reasons?
3. Why did all decline? (Root cause: leverage too high? Industry excluded? Paper quality? Missing docs?)
4. What should be done differently? (Re-shop with updated statements? Merchant not fundable now? Different lender tier?)
5. Confidence in this reflection? (0.0-1.0)

Store in `memory/SELF_REFLECTIONS.md` and Supabase. Feed back into Step 2 next time a similar profile appears.
Recalibrate confidence: if I was 0.85 confident in approval and all 8 lenders declined → investigate the signal gap.

### Step 8: STORE (Dual-Write: Files + Supabase)
Update memory after every meaningful action:
- Failed shop-out pattern → `memory/MISTAKES.md` + Supabase `memories` (category='mistake')
- Successful lender match → `memory/PATTERNS.md` (tag `[PROBATIONARY]`) + Supabase `memories` (category='pattern')
- New lender behavior observed → `memory/LONG_TERM.md` + Supabase `memories` (category='fact')
- Session activity → `memory/SESSION_LOG.md` + Supabase `session_logs`
- Deal status changes → `brain/STATE.md` active queue
- Task status → `memory/ACTIVE_TASKS.md`

### Step 9: EVOLVE (Skill Growth)
- Does this shop-out reveal a new lender-appetite pattern? → Update lender profile in memory.
- Is this the 3rd time a specific deal profile resulted in declines across the same lender set? → Create a `[PROBATIONARY]` screening SOP.
- Can this match pattern be automated? → Flag for `shop_out_sender` daemon configuration.
- Update activation scores for patterns used.

### Step 10: HEAL (Self-Healing + Integrity Checks)
- Temp files created? Clean them.
- Uncommitted brain/memory changes? Flag.
- Any daemon call fail? Log to `memory/MISTAKES.md`.
- Update `brain/STATE.md` with post-action queue state.
- Supabase sync: flush pending traces, update agent_state.
- Git checkpoint: if significant brain/memory changes, commit with `solara: sync — [reason]`.

**Referential integrity scan (mandatory after file moves/renames):**
If any file was renamed or deleted: grep for the old name across all `.md` files. Fix every stale reference. Re-run to confirm zero hits.

## Loop Complexity Table

| Task | Steps Used | Multi-Hypothesis? |
|------|------------|-------------------|
| Status lookup (deal state, queue) | 1, 2, 6 | No |
| Single-field update | 1-3, 5-6 | No |
| Shop-out a new application | 1-8 | Yes (2 lender approaches) |
| Multi-position consolidation deal | All 10 | Yes (2-3 approaches) |
| Merchant-not-fundable escalation | All 10 + Ezra approval | Yes (3 approaches) |

## Confidence Scoring Guide

| Score | Meaning | Autonomy Level |
|-------|---------|----------------|
| 0.95-1.0 | Verified fact (confirmed via Supabase query or lender response) | Full autonomy |
| 0.8-0.94 | High confidence (observed 3+ times with same outcome) | Full autonomy |
| 0.5-0.79 | Medium confidence (inferred from limited data) | Execute + show Ezra result |
| 0.2-0.49 | Low confidence (single observation, uncertain) | Plan → Ezra approves → execute |
| 0.0-0.19 | Speculation | Ask Ezra before anything |

## Failure Recovery Protocol

1. Don't retry the same approach. Switch to the next ranked alternative from Step 4.
2. After 3 total attempts across all approaches: stop and report to Ezra with full diagnostic.
3. Always generate a Reflexion entry (Step 7) after any failure.
4. The Reflexion is retrieved at Step 2 next time a similar deal profile appears.

## Obsidian Links
- [[brain/SOUL]] | [[brain/STATE]] | [[brain/AGENTS]]
- [[memory/MISTAKES]] | [[memory/PATTERNS]] | [[memory/SOP_LIBRARY]]
- [[memory/SELF_REFLECTIONS]] | [[brain/INTERACTION_PROTOCOL]]
