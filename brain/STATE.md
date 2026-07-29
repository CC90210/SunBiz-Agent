---
tags: [state, ephemeral]
---

# STATE — Operational State (SunBiz V6.x)

> Single-tenant. Updated by Solara at session end. Read at session start.
> Ephemeral: body changes every session. Structure changes rarely.
> For live DB state: `python ~/Business-Empire-Agent/scripts/state/state_manager.py status --json`

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
| **Position** | LIVE / VERIFIED | Dolphin month-level underwriting and two-account limit are deployed on VPS `srv1723601` at `a4ac8e8` |
| **Confidence** | 0.98 | VPS tests passed (23 Dolphin/UW + 92 send-gateway), both PM2 workers stayed stable through a full poll, and logs were clean |
| **Focus Area** | Normal production monitoring | No deployment action pending; observe the next real UW deal without sending a synthetic test |
| **Memory Health** | ACTIVE | Session log refreshed with 2026-07-29 VPS deployment proof |

---

## Active Shop-Out Queue

> Populate with live deal IDs at session start via `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py query \"SELECT id, data->>'business_name' AS name, data->>'status' AS status FROM tenant_records WHERE tenant_id = (SELECT id FROM tenants WHERE slug='submissions') AND entity_type IN ('application', 'funded_deal') AND data->>'status'='in_shop_out'\" --json`

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

> Updated end-of-day via `python ~/Business-Empire-Agent/scripts/integrations/supabase_tool.py query \"SELECT id, data->>'business_name' AS name FROM tenant_records WHERE tenant_id = (SELECT id FROM tenants WHERE slug='submissions') AND entity_type IN ('application', 'funded_deal') AND data->>'status'='funded'\" --since monday --json`

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

- **Date:** 2026-07-29
- **Agent:** VPS deployment agent + Codex cross-check
- **Result:** Commit `a4ac8e8` is live; Dolphin and Telegram workers are stable, 115 VPS tests passed, and stale pending candidates were safely reconciled.

*Last updated: 2026-07-29*

## Obsidian Links
- [[brain/SOUL]] | [[brain/USER]] | [[brain/AGENTS]] | [[brain/CAPABILITIES]]
- [[brain/BRAIN_LOOP]] | [[brain/GROWTH]] | [[brain/CHANGELOG]]
- [[brain/INTERACTION_PROTOCOL]] | [[brain/HEARTBEAT]]
- [[memory/ACTIVE_TASKS]] | [[memory/SESSION_LOG]]
