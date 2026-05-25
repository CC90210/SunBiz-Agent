---
name: CLIENT_CONTEXT
description: SunBiz Funding business context — operator, team, lender book, deal volume. Source of truth for all client-specific facts.
last_updated: 2026-05-25
---

# CLIENT CONTEXT — SunBiz Funding

> This file is the source of truth for all facts about SunBiz Funding as a business.
> When Ezra shares new information (new lender relationships, deal volume updates, team changes),
> log it here immediately via `skills/memory-journaling/SKILL.md`.

---

## The Business

**Name:** SunBiz Funding
**Business type:** ISO / MCA broker and direct funder
**Primary product:** Merchant Cash Advance (purchase of future receivables)
**Multi-phase strategy:** Consolidation → Sole funder position → Line of Credit transition
**Geographic focus:** Canada (CASL applies to all outbound)

---

## The Team

| Name | Role | Phone | Notes |
|------|------|-------|-------|
| **Ezra** | Owner / Primary operator | TBD | Main contact for Solara; approves all irreversible actions |
| **Jordan** | TBD | TBD | Team member — role to be confirmed by Ezra |
| **Ethan** | TBD | TBD | Team member — role to be confirmed by Ezra |
| **Emily** | TBD | TBD | Team member — role to be confirmed by Ezra |

> **All four phone numbers are TBD.** Ezra to provide. Never hardcode or guess contact info.

---

## Lender Book

| Lender Name | Relationship Status | Typical Products | Notes |
|-------------|--------------------|--------------------|-------|
| TBD | TBD | TBD | Ezra to populate |

**Lender book size:** TBD — Ezra to confirm number of active funder relationships.

> As lender relationships are established and outcomes logged, the `lender_feedback` table becomes the authoritative source. This file stores qualitative relationship notes that don't fit in structured DB rows.

---

## Deal Volume & Economics

| Metric | Current Value | Notes |
|--------|--------------|-------|
| Monthly deal volume | TBD | Ezra to confirm |
| Average deal size | TBD | Ezra to confirm |
| Average factor rate (sell) | TBD | |
| Average ISO commission % | TBD | |
| Renewal rate | TBD | % of funded merchants who renew |

---

## Pipeline & Application Stages

Applications move through these stages (per migrations 064 + 067):

1. `draft` — application started, not yet complete
2. `pending_info` — waiting on documents from merchant (bank statements, voided check, etc.)
3. `pending_uw` / `ready_for_uw` — docs received, underwriting not yet run
4. `uw_complete` — underwriting done; readiness score assigned
5. `ready_to_shop` — approved for shop-out
6. `pending_shop` — shop-out queued or in progress
7. `offer_received` — one or more lenders have responded with terms
8. `funded` — deal closed and funded
9. `declined` — merchant declined or no lender match
10. `dead` — deal will not proceed

---

## Notable Lender Relationships

> To be populated by Ezra. Format:
> **[Lender Name]** — [relationship quality: strong/neutral/cautious] | [specialty: A-paper, B-paper, restaurants, etc.] | [primary contact if known] | [last deal closed: date]

---

## Compliance Notes

- All outbound (email, SMS, voice) governed by CASL — see `skills/casl-compliance/SKILL.md`
- MCA language rules apply to all merchant-facing communications — see `skills/funding-vocabulary/SKILL.md`
- Renewal eligibility default: 40% of total payback — configurable per deal

---

## Obsidian Links
- [[memory/DECISIONS]] | [[memory/ACTIVE_TASKS]] | [[skills/lender-intelligence/SKILL.md]]
- [[skills/funding-vocabulary/SKILL.md]] | [[skills/casl-compliance/SKILL.md]]
