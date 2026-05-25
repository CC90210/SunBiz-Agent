---
tags: [tasks, active]
last_updated: 2026-05-25
freshness_threshold_days: 7
---

# ACTIVE TASKS

> FRESHNESS CHECK: This file's `last_updated` is in the frontmatter above. If older than 7 days,
> treat contents as archived context — ask Ezra for the current priority rather than inferring.
>
> NEVER state the day of the week unless you computed it.
> Run: `python -c "from datetime import date; print(date.today().strftime('%A %Y-%m-%d'))"`

## P0 — Critical (Do Now)

- [ ] Apply migration 069 to production and smoke-test the new dashboard tabs
- [ ] Confirm the 4 new daemon cron seeds are correctly scheduled (Ezra to verify schedules)
- [ ] Get Ezra's explicit signoff on cron schedules before enabling in production

## P1 — High Priority (This Week)

- [ ] Populate `memory/CLIENT_CONTEXT.md` — team phone numbers, lender book, deal volume (Ezra to provide)
- [ ] Verify `skills/casl-compliance/SKILL.md` is wired into all outbound paths (send_gateway check)
- [ ] First run of `skills/daily-call-sheet-workflow/SKILL.md` to validate data sources are live
- [ ] First run of `skills/renewal-window-detection/SKILL.md` against funded_deals table

## P2 — Normal Priority (Next Steps)

- [ ] Populate lender_feedback table with historical outcomes from Ezra's memory
- [ ] Test `skills/shop-out-routing/SKILL.md` dry-run against a real application
- [ ] Test `skills/underwriting-flow/SKILL.md` end-to-end on a test application
- [ ] Set up `skills/lender-intelligence/SKILL.md` — requires 5+ lender_feedback rows to be useful

## Completed

- [x] Full agent infrastructure built — AdVantage V2.0 era (2026-03-10)
- [x] SunBiz second-meeting expansion shipped (2026-05-25)
- [x] V6.x cognitive substrate upgrade — skills + memory + brain/ expanded to match CEO-Agent shape (2026-05-25)
- [x] Legacy AdVantage marketing skills archived to `skills/_archive/` (2026-05-25)
- [x] 10 new funding-shop skills created (2026-05-25)
- [x] 3 cognitive scaffolding skills mirrored/upgraded from CEO-Agent (2026-05-25)

## Obsidian Links
- [[memory/SESSION_LOG]] | [[memory/DECISIONS]] | [[memory/CLIENT_CONTEXT]]
