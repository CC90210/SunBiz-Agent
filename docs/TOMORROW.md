---
title: SunBiz turnkey — operator action list
status: actionable
last_updated: 2026-05-31
audience: empire-operator
---

# SunBiz turnkey — what's left for Ezra

State as of 2026-05-31 commit window:

- All three Tier 2 product questions (#5/#6/#7) shipped — see `docs/TOMORROW_ARCHIVE_2026-05-30.md` if you want to see the original deferred-decision shape.
- Migrations 074-087 applied to live Supabase.
- Dashboard auto-deployed to Vercel; sigma-eight serving the latest.
- Three SunBiz users live (Submissions@ owner, alex member, jordan member).

## Engineering: DONE

| # | Item | Where it landed |
|---|---|---|
| Day-1 | Setup readiness card | `/settings` top-of-page panel |
| Day-1 | Per-user Gmail OAuth | `/settings#integrations` → Connect Gmail |
| Day-1 | `setup_check.py` CLI | `python scripts/setup_check.py` |
| #5 | Role-based agent defaults | `lib/role-agent-defaults.ts` wired into `/api/auth/redeem-invite` |
| #6 | Personal phone field | `lib/setup-readiness.ts` + `ProfileEditor.tsx` + migration 085 column |
| #7 | Soft seat warning | `lib/seat-warning.ts` wired into `/team` page (starter plan = 3 seats) |

## What's left for Ezra (~60 minutes total)

These are operator actions — no engineering required:

| # | Step | Where | ETA |
|---|---|---|---|
| 1 | Sign into `/t/sun/settings` as Submissions@ | dashboard | 1 min |
| 2 | Read the Setup readiness card at the top | dashboard | 2 min |
| 3 | Wire the 4 required tenant-shared keys (Anthropic, SMTP, Stripe, JotForm) under Integration keys | dashboard | 15 min |
| 4 | Add 2-3 more lenders under `/lenders → + New lender` | dashboard | 10 min |
| 5 | Mint a pair code under Settings → Devices, install bridge on the VPS (`python scripts/bridge_setup.py pair <code>`) | VPS | 15 min |
| 6 | Forward a Gmail OAuth link to Alex + Jordan: `/settings#integrations`, click "Connect Gmail" | comms | 2 min |
| 7 | Re-run `python scripts/setup_check.py` from SunBiz-Agent — should show **8 PASS · 0 WARN · 0 FAIL** when complete | terminal | 1 min |

After step 7, SunBiz is **operationally live**: drips fire, daily plan generates, follow-ups queue, renewals scan, lender shop-out works, every email send carries the right "from" address.

## What the Tier 2 ships actually do for Ezra

### Role-based agent defaults (#5)

Today: every SunBiz profile has `agents_enabled = [solara, helios]` because all three users were pre-provisioned manually.

Going forward: a new hire's profile comes through `/api/auth/redeem-invite`, which reads their team_role from the invite and stamps the right agent palette via `defaultAgentsForRole(slug, role, manifest)`:

| Role | Default agents |
|---|---|
| owner | solara + helios |
| admin | solara + helios |
| loan_officer | solara + helios |
| processor | solara only |
| read_only | solara only |
| member | solara only |

The defaults only land on rows where `agents_enabled IS NULL` so an explicit user choice is never overwritten.

### Personal phone (#6 — Option A)

Each user can set their personal cell or DID in `/settings → Profile → Personal phone`. Stored on `user_profiles.personal_phone` (migration 085). **Display-only** — outbound SMS still goes through the tenant's shared Twilio number. Agents quote the field when a lead asks "what's the direct number to reach Alex" without exposing the shared line.

Phase B (true per-employee Twilio sub-accounts) is deferred until volume justifies the per-line spend.

### Soft seat warning (#7 — Option B)

Plan limits (default sizing):

| Plan tier | Seat limit |
|---|---|
| free | 1 |
| starter | 3 |
| growth | 10 |
| pro | 25 |
| enterprise | no cap |

SunBiz is currently on `starter` (3 seats) and has 3 users — so the `/team` page now shows an "approaching" banner: "3 of 3 seats used. One more invite puts you over your plan — billing will adjust next cycle."

Inviting a 4th user is not blocked — Stripe metered billing reconciles the overage on the next cycle. To remove the banner, upgrade the plan_tier to `growth` (or set to `enterprise` to remove the cap entirely).

## Tier 3 — Security hardening (shipped)

These don't change Ezra's daily flow but make the deploy production-safe:

| Item | Where it landed |
|---|---|
| RLS lockdown on 13 wide-open tables (incl `agent_events`) | Migrations 081 + 082 |
| `redeem_tenant_invite` retry path checks `expires_at` | Migration 083 |
| DNS-rebinding defense on `webhook_post` (bridge-side) | `bravo_cli/cron_runner.py` |
| `/api/bridge/*` + `/api/cron-jobs/poll` rate limiting | IP-keyed token bucket BEFORE the bearer check |
| `OPERATOR_EMAIL` fallback gated | env opt-in only |
| Dependabot vulnerabilities | 0 remaining (was 3) |

## How to use this document

1. Run `python scripts/setup_check.py` from SunBiz-Agent — see live state
2. Run through Ezra's 7-step list above — get to **0 FAIL · 0 WARN**
3. Once #5 banner shows on /team, you'll know SunBiz is at seat limit; decide plan upgrade timing

The engineering side is complete. The only path to "fully live" is the 7 operator steps.
