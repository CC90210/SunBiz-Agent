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
| **Position** | DASHBOARD LIVE / VPS REPAIR PENDING | Corrected CRM lifecycle is live in Vercel production; VPS must pull SunBiz main and run the gated repair |
| **Confidence** | 0.98 | Full dashboard SunBiz suite, typecheck/mapping/lint, 25 SunBiz tests, and independent audit passed |
| **Focus Area** | Complete VPS repair | Run the fingerprint-gated VPS handoff without a synthetic deal, then verify repaired lead/application markers |
| **Memory Health** | ACTIVE | Session log refreshed with 2026-07-30 root-cause and deployment handoff |

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

- **Date:** 2026-07-30
- **Agent:** Codex implementation + independent Codex review
- **Result:** Dashboard production is Ready and both repos are pushed; targeted VPS repair remains.

*Last updated: 2026-07-30*

## Obsidian Links
- [[brain/SOUL]] | [[brain/USER]] | [[brain/AGENTS]] | [[brain/CAPABILITIES]]
- [[brain/BRAIN_LOOP]] | [[brain/GROWTH]] | [[brain/CHANGELOG]]
- [[brain/INTERACTION_PROTOCOL]] | [[brain/HEARTBEAT]]
- [[memory/ACTIVE_TASKS]] | [[memory/SESSION_LOG]]
