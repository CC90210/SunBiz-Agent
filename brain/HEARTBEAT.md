---
tags: [heartbeat, monitoring]
---

# HEARTBEAT — Proactive Monitoring (SunBiz V6.x)

> Unlike a cron that fires blindly, the heartbeat exercises judgment.
> It checks conditions and only surfaces findings that require attention.

## Trigger

Heartbeat runs at session start. Solara checks the queue before engaging with Ezra's request.
Daemon mode available via `python scripts/state_bridge.py heartbeat --loop --interval 300`.

---

## Scheduled Heartbeat Checks

### 08:00 ET — Morning Brief

**Trigger:** Daily, first session of the day (or daemon-dispatched).

```
CHECK: What does the team need to work today?
- Run daily_plan_generator.py → Jordan's call sheet (leads to contact today)
- Run deal_tracker.py list --status in_shop_out → any threads >24h without response?
- Run renewal_reminder.py --window 7 → any renewals due this week?
- Check memory/ACTIVE_TASKS.md → any blocked items needing Ezra decision today?
ACTION: Compose morning brief. Format: [Call Sheet] [Shop-Out Queue] [Renewals Due] [Blocked Items].
Surface only items that need a human. Do not narrate the things that are fine.
```

Brief format (terse):
```
MORNING BRIEF — [DATE]
Call sheet: [N] leads for Jordan | [N] follow-ups for Emily
Shop-out: [N] active | [N] stuck >24h — deal IDs: [...]
Renewals: [N] in 7-day window — deal IDs: [...]
Blocked: [N] items need Ezra decision
```

### 14:00 ET — Shop-Out Queue Health Check

**Trigger:** Afternoon check (daemon or manual `/heartbeat` command).

```
CHECK: Is the shop-out pipeline moving?
- deal_tracker.py list --status in_shop_out → any threads >48h without lender response?
- lender_response_classifier.py --pending → any lender responses received and not yet classified?
- agent_inbox.py list --to solara → any Helios messages about merchant questions on pending offers?
ACTION: Flag stuck threads to Ezra. Classify any unprocessed lender responses. Reply to Helios inbox if pending.
```

### End of Day — Funded Deal Summary

**Trigger:** After 5pm ET, or when Ezra asks for a daily wrap.

```
CHECK: What closed today?
- deal_tracker.py list --status funded --since today
- funding_intel.py commission --period today
- deal_tracker.py list --status declined --since today → any to re-shop?
ACTION: Compose end-of-day summary. Format: [Funded today] [Commission booked] [Declined — re-shop candidates].
```

Summary format:
```
END OF DAY — [DATE]
Funded: [N] deals | Commission: $[X]
Declined: [N] deals | Re-shop candidates: [deal IDs]
Renewal outreach sent: [N]
Tomorrow's queue: [N] applications to process
```

### Weekly — Lender Intelligence Report

**Trigger:** Every Friday end-of-day.

```
CHECK: Which lenders are performing this week?
- Aggregate deal_tracker + lender_response_classifier data for the week:
  - Lenders with highest approval rates
  - Lenders with most declines (and primary decline reasons)
  - Average time-to-response per lender
  - Any lenders that went silent on submissions >72h
ACTION: Generate weekly lender intelligence summary. Flag any lender relationship showing decline-rate spike.
```

---

## Session-Start Heartbeat Checks

### 1. Memory Consistency (Priority: HIGH)
```
CHECK: Are memory files internally consistent?
- ACTIVE_TASKS.md — any tasks "in progress" from prior session?
- SESSION_LOG.md (last 3 entries) — incomplete work?
- MISTAKES.md — recent mistakes that apply to today's deals?
- PATTERNS.md — any new [VALIDATED] patterns to internalize?
- [PROBATIONARY] items past 3 sessions → promote to [VALIDATED]
ACTION: Flag stale tasks. Carry forward or close.
```

### 2. Pipeline Health (Priority: HIGH)
```
CHECK: Is the deal pipeline in a known state?
- In-shop-out count vs. last session
- Any offers that expired since last session
- Any funded deals not yet booked in commission tracker
ACTION: Update STATE.md. Flag anything that moved without Solara's involvement.
```

### 3. Supabase State Sync (Priority: HIGH)
```
CHECK: Is Supabase in sync with brain/STATE.md?
- Query agent_state --tenant sunbiz → compare with STATE.md
- If diverged: files win → update DB via state_bridge.py
ACTION: Sync state. Report any divergence.
```

### 4. Pending Tasks (Priority: MEDIUM)
```
CHECK: What's in memory/ACTIVE_TASKS.md?
- Overdue items
- Blocked items (waiting on Ezra or lender)
ACTION: Present status. Suggest next action per item.
```

### 5. Workspace Health (Priority: LOW)
```
CHECK: Is the repo clean?
- git status — uncommitted changes?
- Temp files in project root?
- memory/SESSION_LOG.md > 200 lines? (compress)
ACTION: Auto-clean junk. Flag compression if needed.
```

---

## Heartbeat Response Format

```
HEARTBEAT COMPLETE (SunBiz V6.x)
Pipeline: [N] in shop-out | [N] offers pending | [N] stuck >48h
Memory: [OK / ISSUES — X probationary items]
Supabase: [IN SYNC / DIVERGED — files win]
Pending Tasks: [N items] ([N] blocked on Ezra)
Workspace: [CLEAN / NEEDS ATTENTION]
Ready, Ezra.
```

## Duplicate Suppression

If the same heartbeat issue was reported in the last session and not acted on:
- Don't repeat verbatim.
- Instead: "Previously flagged: [issue]. Still unresolved. Priority: [level]."
- Prevents alert fatigue while keeping issues visible.

## Obsidian Links
- [[brain/STATE]] | [[brain/CAPABILITIES]] | [[brain/AGENTS]]
- [[memory/ACTIVE_TASKS]] | [[memory/SESSION_LOG]]
