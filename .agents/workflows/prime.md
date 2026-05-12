---
description: Load full agent context — brain, memory, state, and quick health check for session start.
---

// turbo-all

# /prime — Load Full Context

## When to Use
Use `/prime` at the start of every session to load context and get situational awareness.

## Steps

1. **Load Brain (silently):**
   - `brain/SOUL.md` — Identity and values (Sun Biz Agent V1.0)
   - `brain/STATE.md` — Current status
   - `brain/CLIENT.md` — Sun Biz Funding context
   - `brain/AGENTS.md` — Available agents
   - `brain/CAPABILITIES.md` — Tool inventory

2. **Load Memory (silently):**
   - `memory/ACTIVE_TASKS.md` — Pending work
   - `memory/PATTERNS.md` — Known approaches
   - `memory/CAMPAIGN_TRACKER.md` — Current outreach campaigns
   - `memory/MISTAKES.md` — What to avoid

3. **Quick Health Check** — Twilio reachable? Gmail SMTP OK? Google/Meta API tokens valid? V6 state-bridge daemon alive? Renewal scanner cron landed in the last 24h? Any urgent issues?

4. **Report:**
   ```
   Sun Biz Agent online. V1.0 loaded.
   Status: [INITIALIZING/OPERATIONAL/DEGRADED]
   Outreach: SMS [OK/PENDING] | Email [OK/PENDING]
   Ads (sub-cap): Google [OK/PENDING] | Meta [OK/PENDING]
   V6 bridge: [online/offline] · last heartbeat HH:MM
   Pipeline: X applications · Y offers · Z funded MTD
   Renewals due (next 30d): N · est. commission $X
   Pending Tasks: [count]
   Ready for instructions.
   ```

## Example Usage
**User:** `/prime`
**Agent:** "Sun Biz Agent online. OPERATIONAL. SMS+Email green. V6 bridge online (last heartbeat 00:12). 4 funded deals MTD, 7 renewals in 30d window. Ready."
