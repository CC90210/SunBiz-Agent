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
| **Position** | READY FOR VPS DEPLOY | Dolphin's expanded Ezra selection protocol is implemented and locally verified; production workers are not yet updated |
| **Confidence** | 0.90 | 12 focused tests pass; parser/scorer/Telegram boundary and packet rendering are covered |
| **Focus Area** | Dolphin production rollout | Commit/push, then execute `docs/DOLPHIN_VPS_PRODUCTION_UPDATE_2026-07-21.md` on the VPS without sending a test deal |
| **Memory Health** | ACTIVE | Session log refreshed with 2026-07-22 Dolphin protocol work |

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

- **Date:** 2026-07-02
- **Agent:** BRAVO/Codex live verification from Windows, using SunBiz CLI tools
- **Result:** Breeze UW extraction path verified: Drive discovery OK, VPS bridge heartbeat fresh, recent UW candidates staged, Telegram approval path has approved/declined history.

*Last updated: 2026-07-02*

## Obsidian Links
- [[brain/SOUL]] | [[brain/USER]] | [[brain/AGENTS]] | [[brain/CAPABILITIES]]
- [[brain/BRAIN_LOOP]] | [[brain/GROWTH]] | [[brain/CHANGELOG]]
- [[brain/INTERACTION_PROTOCOL]] | [[brain/HEARTBEAT]]
- [[memory/ACTIVE_TASKS]] | [[memory/SESSION_LOG]]
