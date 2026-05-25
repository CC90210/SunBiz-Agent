---
name: CONTEXT
description: Canonical vocabulary for SunBiz-Agent / Solara. Every skill, agent, and entry-point uses these terms with these meanings. When a new domain term needs to enter the codebase, add it here first.
last_updated: 2026-05-25
---

# CONTEXT — Canonical Vocabulary

> Single source of truth for SunBiz Funding / Solara terminology.
> If you find yourself re-deriving what a term means mid-session, the term either belongs here
> or its existing entry needs tightening. Update this file; don't re-derive.

---

## People

- **Ezra** — Owner and primary operator of SunBiz Funding. Solara's operator. All irreversible actions require Ezra's explicit approval via Telegram or dashboard chat.
- **Jordan** — Team member. Role TBD — Ezra to confirm.
- **Ethan** — Team member. Role TBD — Ezra to confirm.
- **Emily** — Team member. Role TBD — Ezra to confirm.
- **Solara** — This agent. Funding-shop ops agent. Handles backend admin: shop-out routing, underwriting interpretation, follow-up discipline, renewal detection, call sheet generation.
- **Suga Sean** — Outreach and meeting-setting agent. High-velocity cold outreach and appointment booking. Separate persona from Solara.
- **CC** — The platform owner (OASIS AI Solutions). Operates Business-Empire-Agent. SunBiz Funding is a client tenant.

## Repos & Boundaries

| Repo | Location | Owns |
|------|----------|------|
| **SunBiz-Agent** | `C:\Users\User\SunBiz-Agent\` | Solara's skills, memory, brain/, agent config. Business logic specific to SunBiz Funding. |
| **Business-Empire-Agent** | `C:\Users\User\Business-Empire-Agent\` | CEO-Agent (Bravo). Empire-wide infrastructure, migration tooling, send_gateway, state DB. |
| **oasis-command-center** | `~/APPS/oasis-command-center` | Dashboard UI, API routes, tenant manifests. SunBiz dashboard lives here under tenant slug `sunbiz`. |

**Rule:** Never edit oasis-command-center code from SunBiz-Agent. Never edit SunBiz business logic from CEO-Agent. Runtime infrastructure (send_gateway.py, DB migrations, API routes) lives in the app code bases; Solara's operational intelligence lives here.

## Application Stages

Per migrations 064 + 067:

| Stage | Meaning |
|-------|---------|
| `draft` | Started, not yet complete |
| `pending_info` | Waiting on docs from merchant |
| `pending_uw` / `ready_for_uw` | Docs in, underwriting not yet run |
| `uw_complete` | Underwriting done, readiness score assigned |
| `ready_to_shop` | Cleared for shop-out |
| `pending_shop` | Shop-out queued or in progress |
| `offer_received` | One or more lenders returned terms |
| `funded` | Deal closed and funded |
| `declined` | No lender match or merchant declined |
| `dead` | Deal will not proceed |

## Lender Match Scoring

The shop-out API returns `risk_level` per matched lender:

| Level | Meaning |
|-------|---------|
| `info` | No concerns — standard match |
| `warning` | Risk factor present but not disqualifying (e.g., 3 NSFs, 2 positions) — include with caveats |
| `high_risk` | Likely decline or adverse terms — exclude unless Ezra explicitly overrides |

## Funding Vocabulary (key terms — full glossary in `skills/funding-vocabulary/SKILL.md`)

| Term | Definition |
|------|-----------|
| **Factor rate** | Cost multiplier. $50K at 1.38x = $69K total payback. NOT an interest rate. |
| **Buy rate** | Factor rate SunBiz pays to the funder. Spread between buy rate and sell rate = SunBiz margin. |
| **Holdback** | % of daily revenue withheld for repayment in revenue-based MCAs. |
| **Fixed daily ACH** | Fixed dollar amount debited daily, regardless of revenue. More common than holdback. |
| **RTR** | Right to Receive — the future receivables purchased by the advance. |
| **NSF** | Non-Sufficient Funds — failed transaction. NSF count > 5 in 90 days = near-automatic decline at most funders. |
| **Stacking** | Merchant taking a new MCA without disclosing existing positions. Violation of most MCA contracts. |
| **Leverage %** | `(total_daily_payments / daily_revenue) × 100`. > 40–45% = overleveraged. |
| **Paper grade** | A/B/C/D risk classification. A = clean; D = death spiral. |
| **Position** | One active MCA advance on a merchant. |
| **Syndication** | Multiple funders sharing a single advance. |
| **Stipulations (stips)** | Additional docs a funder requires before approving. |
| **ISO commission** | Broker fee paid to SunBiz by the funder on close. Typically 8–15% of advance. |

## Paper Grading

| Grade | Revenue | Positions | Leverage | NSFs |
|-------|---------|-----------|----------|------|
| A | $40K+/mo | 0–1 | < 25% | 0–2 |
| B | $25K–$50K/mo | 1–3 | 25–35% | 2–5 |
| C | $25K+/mo | 3–5 | 35–45% | 5–7 |
| D | Any | 5+ | > 45% | > 7 |

## Renewal Eligibility

Default threshold: **40% of total payback repaid**.

Configurable per-deal via `funded_deals.renewal_eligibility_threshold`. When a merchant crosses this threshold, they are eligible for renewal outreach. At 40%, a $50K advance at 1.38x has paid back $27,600 of $69,000 total payback.

## Daily Call Sheet Categories

The six categories Solara uses to organize the daily call sheet, in priority order:

1. **Priority Call** — Expiring offer, hot inbound not yet contacted
2. **Missing Info** — Stalled application waiting on merchant documents
3. **Stuck Deals** — In lender review > 72h or merchant ghosting after offer
4. **New Offer** — Lender returned approval/counter, awaiting merchant decision
5. **Shop Today** — Underwriting complete, not yet shopped
6. **Renewal Eligible** — Funded deals at renewal threshold, not recently contacted

## Compliance

- **CASL** — Canada's Anti-Spam Legislation. Governs all commercial electronic messages to Canadian recipients. Fines up to $10M per violation. All outbound routes through `send_gateway.py` and `skills/casl-compliance/SKILL.md`.
- **Express consent** — Recipient explicitly opted in.
- **Implied consent** — Existing B2B relationship, valid 2 years from last interaction.
- **Opt-out** — Absolute suppression. Honor immediately. No exceptions, no grace period.
- **MCA language rules** — Never use "loan," "lender," "interest rate," "APR" in merchant-facing communications. See `skills/funding-vocabulary/SKILL.md`.

## Skill Conventions (V6.8 Frontmatter)

Every `SKILL.md` must have:
```yaml
---
name: skill-name
description: One-sentence trigger description.
triggers: ["user says this", "operator asks that"]
tier: stable | probationary | archived
disable_model_invocation: false  # true = only fires on /skill-name command
argument_hint: "Question to ask when invoked"  # optional
requires:  # only if hard deps exist
  - env:ENV_VAR_NAME
  - daemon:daemon-name
  - state:state/file
---
```

Skill tiers: `stable` (proven in production), `probationary` (new, < 3 uses), `archived` (deprecated, in `skills/_archive/`).

## Obsidian Links
- [[memory/CLIENT_CONTEXT]] | [[memory/DECISIONS]] | [[memory/ACTIVE_TASKS]]
- [[skills/funding-vocabulary/SKILL.md]] | [[skills/casl-compliance/SKILL.md]]
- [[skills/shop-out-routing/SKILL.md]] | [[skills/underwriting-flow/SKILL.md]]
