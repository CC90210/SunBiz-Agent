---
tags: [growth, evolution]
---

# GROWTH — Learning & Capability Evolution (SunBiz V6.x)

> Tracks Solara's journey from a scripted ops agent to a funding-domain intelligence system.
> Voyager-inspired: skills are compositional, validated through use, and retired when superseded.

## Capability Timeline

| Date | Tier | Capability | Evidence |
|------|------|------------|----------|
| 2026-03-10 | 1 | Basic marketing automation | AdVantage V1.0 — Google/Meta Ads pipeline |
| 2026-05-11 | 2 | Full backend operations | SunBiz V1.0 — SMS engine, deal lifecycle, funding intel |
| 2026-05-12 | 2 | Production hardening | Doctor, API server, HMAC, setup wizard |
| 2026-05-25 | 3 | V6.x cognitive substrate | Brain loop, self-improvement governance, Reflexion, tiered logging |

## Active Skills (Cumulative)

| Skill | Acquired | Uses | Status | Composites |
|-------|----------|------|--------|------------|
| MCA compliance gating | 2026-05-11 | 3+ | `[VALIDATED]` | TCPA check + CASL check + language filter |
| Deal lifecycle CRUD | 2026-05-11 | 3+ | `[VALIDATED]` | supabase_tool (direct `tenant_records` queries — `(tenant_records via supabase_tool).py` is Phase 6.6) |
| Lender response classification | 2026-05-12 | 1 | `[PROBATIONARY]` | lender_response_classifier + decision tree |
| Renewal window scanning | 2026-05-12 | 1 | `[PROBATIONARY]` | renewal_reminder + sequence_runner |
| V6 substrate heartbeat | 2026-05-25 | 0 | `[PROBATIONARY]` | `~/Business-Empire-Agent/scripts/state/state_sync.py` + agent_events bus |
| Brain-first reasoning loop | 2026-05-25 | 0 | `[PROBATIONARY]` | BRAIN_LOOP 10-step + Reflexion protocol |

## Skill Compositionality (Voyager Pattern)

Complex skills are built from simpler ones:
```
Shop-Out Flow = underwriting_orchestrator + shop_out_sender + lender_response_classifier + (tenant_records via supabase_tool)
Renewal Pipeline = renewal_reminder + follow_up_generator + send_gateway + sequence_runner
Merchant Drip = sequence_runner + follow_up_generator + send_gateway (TCPA gate)
Daily Brief = daily_plan_generator + renewal_reminder + supabase_tool (in_shop_out filter — (tenant_records via supabase_tool).py is Phase 6.6)
```

When building new skills, check whether existing scripts can be composed before writing new ones.

## Skill Candidates — Next Cycle

These are skill gaps that have surfaced but are not yet built or validated:

| Candidate Skill | Description | Priority | Depends On |
|----------------|-------------|----------|------------|
| **known-funder pattern learning** | Per-lender appetite profile that updates after each approval/decline — industry, revenue band, position count tolerance, preferred paper type | HIGH | lender_response_classifier (needs 10+ decisions to train) |
| **deal-profile clustering** | Groups funded deals by profile similarity to predict which lender tier fits next application | MEDIUM | supabase_tool (query funded `tenant_records`) — Phase 6.6, depends on commission projection rollout |
| **drip-cadence A/B** | Tracks which follow-up sequence (timing, channel, copy template) produces higher application-to-funded rate | MEDIUM | sequence_runner + supabase_tool (outcome join on `tenant_records`) |
| **lender-portal scrape adapters** | Per-lender portal DOM scrapers for submission status checks (for lenders without email confirmations) | LOW | Playwright MCP + lender_response_classifier |
| **stacking-risk scorer** | Given merchant's existing positions (count, total daily obligations), score the stacking risk before any submission | HIGH | underwriting_orchestrator extension |

## Capability Frontier

| Current Limit | Next Level | Plan | Priority |
|---------------|------------|------|----------|
| Lender selection is manual | Ranked lender recommendation | known-funder pattern learning → auto-rank | HIGH |
| Renewal tracking is batch scan | Proactive renewal alerts | renewal_reminder → daily brief integration | HIGH |
| No deal-profile memory | Clustering on funded history | deal-profile clustering skill | MEDIUM |
| Drip sequences are fixed | A/B optimized cadences | drip-cadence A/B skill | MEDIUM |
| Lender status polling is manual | Automated portal checks | lender-portal scrape adapters | LOW |

## Growth Metrics (Track Per Session)

- **Skills promoted to `[VALIDATED]` this month:** [count]
- **SOPs created:** [count]
- **Lender patterns logged:** [count]
- **Decline insights captured:** [count]
- **Reflexion entries generated:** [count]
- **Average confidence calibration:** [predicted vs actual approval rate]

*Last updated: 2026-05-25*

## Obsidian Links
- [[brain/BRAIN_LOOP]] | [[brain/CAPABILITIES]] | [[memory/PATTERNS]]
- [[memory/MISTAKES]] | [[memory/SOP_LIBRARY]]
