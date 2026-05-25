---
tags: [state, ephemeral]
---

# STATE — Operational State (SunBiz V6.x)

> Single-tenant. Updated by Solara at session end. Read at session start.
> Ephemeral: body changes every session. Structure changes rarely.
> For live DB state: `python scripts/state_bridge.py status --json`

---

## North Star

**TBD with Ezra.** Placeholder metrics until confirmed:
- Funded deal volume (deals/month)
- Renewal capture rate (renewals closed / renewals eligible)
- Shop-out cycle time (application received → offer presented, target <24h standard paper)

---

## Operational Status

| Dimension | Level | Notes |
|-----------|-------|-------|
| **Version** | V6.x Cognitive Substrate | Upgraded 2026-05-25 — Solara persona established |
| **Position** | OPERATIONAL | Shop-out pipeline active |
| **Confidence** | 0.70 | Substrate newly upgraded; baseline |
| **Focus Area** | Deal throughput + renewal pipeline | Primary levers for funded volume |
| **Memory Health** | INITIALIZED | V6.x brain files written; memory/ to be seeded |

---

## Active Shop-Out Queue

> Populate with live deal IDs at session start via `python scripts/deal_tracker.py list --status in_shop_out --json`

| Deal ID | Merchant | Submitted To | Submitted At | Status | Notes |
|---------|----------|--------------|--------------|--------|-------|
| — | — | — | — | — | Awaiting data |

**Stuck (>48h without lender response):** None on record — verify at session start.

---

## Pending Offers

> Offers presented to merchant, awaiting acceptance or counter.

| Deal ID | Merchant | Lender | Offered | Expires | Next Touch |
|---------|----------|--------|---------|---------|------------|
| — | — | — | — | — | — |

---

## This Week's Funded Deals

> Updated end-of-day via `python scripts/deal_tracker.py list --status funded --since monday --json`

| Deal ID | Merchant | Lender | Amount | Factor Rate | Commission | Funded Date |
|---------|----------|--------|--------|-------------|------------|-------------|
| — | — | — | — | — | — | — |

**Week-to-date commission:** $0 (placeholder)

---

## Renewal Window (Next 30 Days)

> Merchants approaching end of payback period — prime renewal candidates.
> Source: `python scripts/renewal_scanner.py --window 30 --json`

| Deal ID | Merchant | Original Funder | Funded Date | Payback End | Holdback % | Status |
|---------|----------|-----------------|-------------|-------------|------------|--------|
| — | — | — | — | — | — | Awaiting scan |

---

## Blocked Items (Needs Ezra Decision)

> Anything stalled because Solara cannot proceed without operator input.

| Item | Blocked Since | Reason | Required Action |
|------|---------------|--------|-----------------|
| — | — | — | — |

---

## Last Heartbeat

- **Date:** 2026-05-25
- **Agent:** SOLARA via Claude Code (V6.x upgrade session)
- **Result:** Cognitive substrate initialized. All 15 brain files written.

*Last updated: 2026-05-25*

## Obsidian Links
- [[brain/SOUL]] | [[brain/USER]] | [[brain/AGENTS]] | [[brain/CAPABILITIES]]
- [[brain/BRAIN_LOOP]] | [[brain/GROWTH]] | [[brain/CHANGELOG]]
- [[brain/INTERACTION_PROTOCOL]] | [[brain/HEARTBEAT]]
- [[memory/ACTIVE_TASKS]] | [[memory/SESSION_LOG]]
