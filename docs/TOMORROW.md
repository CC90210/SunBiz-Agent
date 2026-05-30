---
title: SunBiz turnkey — tomorrow's plan
status: actionable
last_updated: 2026-05-30
audience: empire-operator
---

# SunBiz turnkey — tomorrow's plan

State as of today (2026-05-30 commit window):

- Three users provisioned on the SunBiz tenant: **Submissions@ (owner)**, **alex@**, **jordan@**
- All three have `agents_enabled: [solara, helios]`
- Tier 1 setup ergonomics shipped today (Settings → SetupReadinessCard, `setup_check.py` per-user audit, lead_interactions audit trail)
- Live setup_check.py says: **6 PASS · 2 WARN · 1 FAIL**

## What Ezra needs to do TOMORROW MORNING (60 minutes total)

These are operator actions — no engineering required:

| # | Step | Where | ETA |
|---|---|---|---|
| 1 | Sign into `/t/sun/settings` as Submissions@ | dashboard | 1 min |
| 2 | Read the **Setup readiness** card at the top — it lists exactly what's missing | dashboard | 2 min |
| 3 | Wire the 4 required tenant-shared keys (Anthropic, SMTP, Stripe, JotForm) under Integration keys | dashboard | 15 min |
| 4 | Add 2-3 more lenders under `/lenders → + New lender` | dashboard | 10 min |
| 5 | Mint a pair code under Settings → Devices, install bridge on the VPS (`python scripts/bridge_setup.py pair <code>`) | VPS | 15 min |
| 6 | Forward a Gmail OAuth link to Alex + Jordan: `/settings#integrations`, click "Connect Gmail" | comms | 2 min |
| 7 | Re-run `python scripts/setup_check.py` from SunBiz-Agent — should show **8 PASS · 0 WARN · 0 FAIL** when complete | terminal | 1 min |

Then SunBiz is **live**: drips fire, daily plan generates, follow-ups
queue, renewals scan, lender shop-out works, every email send carries
the right "from" address.

## What I (engineering) plan to ship next — pick before I start

These are the Tier 2 items from the readiness report. Each one has a
**product question** I need answered before I write code. Pick the
ones you want and answer the questions.

### Item #5 — Role-based agents_enabled defaults

**Current state**: every SunBiz user has `[solara, helios]` regardless of role.

**Product question**: Should agents per role differ? My guess:

| Role | Default agents | Rationale |
|---|---|---|
| `owner` | solara + helios | Full visibility |
| `admin` | solara + helios | Same as owner minus billing actions |
| `loan_officer` | solara + helios | Outreach + funding ops |
| `processor` | solara only | Funding ops, not sales outreach |
| `read_only` | solara (read-only mode) | Surface only |
| `member` | solara only | Conservative default |

**Decision needed**: agree with the table above, or specify your own
per-role agent palette. Then I'll add it to `lib/manifest/seeds.ts`
`SUN_SEED` and the invite-redemption flow.

### Item #6 — Per-employee phone/SMS (your "personal text or number")

**Current state**: Twilio is shared at the tenant level. Every SMS goes through one number.

**Three design options** — pick one:

| Option | Description | Pro | Con |
|---|---|---|---|
| A | **Personal cell as display only** — store each employee's personal cell in `user_profiles.personal_phone`, agents can read it ("Alex's cell is …") but outbound still uses tenant Twilio | Trivial to ship | Outbound still says "from the SunBiz line" |
| B | **Twilio sub-account per employee** — each employee gets a Twilio number SunBiz pays for | True per-employee identity | $1/mo per number + Twilio plumbing |
| C | **Operator's personal Twilio key per employee** (mirror of Gmail OAuth) — each employee adds their own Twilio account | Maximum personalization | Employees need their own Twilio billing |

**Decision needed**: A / B / C. My recommendation: **A** for v1 (display only), **B** later (true per-user lines once volume justifies the spend).

### Item #7 — Seat limit enforcement

**Current state**: `tenants.plan_tier` exists but nothing prevents Ezra from inviting a 4th, 5th, 10th user.

**Product question**: Do we want hard enforcement, soft warning, or none?

| Option | Behavior |
|---|---|
| Hard | API refuses invite when seat count reached. Operator sees a "upgrade your plan" CTA. |
| Soft | API allows invite; dashboard banner says "you are at N/M seats — billing will adjust next cycle." |
| None | Honor system; Stripe metered billing handles the rest. |

**Decision needed**: which option. If Hard/Soft, also specify the seat
cap per plan_tier (`free` / `starter` / `growth` / `pro`?).

## Tier 3 — Security hardening (defer until usage is real)

These don't block SunBiz going live but should land in a dedicated
hardening sprint:

| Item | Severity | Owner |
|---|---|---|
| `redeem_tenant_invite` `expires_at` on retry path | MEDIUM | engineering |
| `webhook_post` DNS-rebinding (bridge-side) | LOW | engineering |
| `/api/bridge` rate limiting | HIGH | engineering |

## How to use this document

When you read this tomorrow:

1. Run `python scripts/setup_check.py` from SunBiz-Agent — see live state
2. Run through Ezra's 7-step list above — get to **0 FAIL · 0 WARN**
3. Answer the 3 product questions on items #5/#6/#7 — paste decisions
   inline in this doc or just reply in chat
4. I'll ship the Tier 2 items based on your decisions

The Tier 1 work (Setup readiness card, audit trail column, extended
setup_check) is already live in dashboard + scripts — no work needed
from you, just verify it on /settings.
