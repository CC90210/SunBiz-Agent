# SunBiz Migration History

> Numbered record of every database migration this repo carries. Applied to the shared OASIS Supabase project in numeric order. All migrations are idempotent and transactional unless noted.
>
> Created: 2026-05-25. Range: 042–069.

---

## How to apply

```bash
# Apply a single migration
python scripts/apply_migration.py database/069_sunbiz_meeting2_expansion.sql

# Apply all SunBiz migrations in order (idempotent — safe to re-run)
cd ~/SunBiz-Agent
for migration in 042 043 044 064 065 066 067 068 069; do
  python scripts/apply_migration.py database/${migration}_*.sql
done
```

Note: migrations 045–063 belong to the CEO-Agent repo (empire-wide schema). SunBiz migrations pick up from 064 after the SunBiz CRM phase began in earnest. Migrations 042–044 were SunBiz-specific early additions.

---

## Migration 042 — Tenant-defined forms + submissions

**File:** `042_tenant_forms.sql`
**Date:** 2026-05-15
**Phase:** SunBiz CRM Phase 3

Replaces third-party JotForm intake with first-party forms that operators design in the dashboard. Two tables: `forms` (definitions — field schema, step structure, slug) and `form_submissions` (one row per step completion, keyed to the lead). Personalized per-lead links are HMAC-signed via `lib/form-links.ts` and drop the prospect into a branded multi-step funnel. Submissions trigger lead stage transitions via `BRAVO_RECORD_STATUS_CHANGED` and feed the Phase 4 drip engine. JotForm remained running in parallel through Phase 4 to prevent intake loss during cutover.

---

## Migration 043 — Drip campaign sequence engine

**File:** `043_drip_sequences.sql`
**Date:** 2026-05-15
**Phase:** SunBiz CRM Phase 4

Closes the loop on pipeline-status work shipped in Phase 2. When a lead or application stage changes, the `sequence_runner` daemon matches the event against `drip_sequences` definitions and enqueues the first step into `sequence_state`. The daemon then executes due steps on a 10-second tick, firing via `send_gateway` (SMS or email). Two tables: `drip_sequences` (campaign definitions — trigger conditions, step array, channels) and `sequence_state` (in-flight enrollment rows — current step, due_at, status). The split between definitions and state means operators can edit a sequence without losing in-progress enrollments.

---

## Migration 044 — Lender shop-out: extended fields + thread tracking

**File:** `044_lender_shopout.sql`
**Date:** 2026-05-15
**Phase:** SunBiz CRM Phase 6

Two changes in one migration. First: extends the lender catalog with match-fitness fields (`min_revenue`, `max_funded`, `time_in_business`, `fico_floor`) so the shop-out UI can pre-rank lenders against a deal's profile instead of operators eyeballing a 50-lender spreadsheet. Second: adds `application_lender_threads` — one row per (application, lender) shop-out email, tracking `gmail_thread_id`, status enum, and per-lender response state. The `lender_response_classifier` daemon polls these rows and classifies replies as `approved / declined / info_requested / unclear` as they arrive.

---

## Migration 064 — SunBiz Agent Command Center restructure

**File:** `064_sunbiz_restructure.sql`
**Date:** 2026-05-25
**Phase:** Jordan/Oasis 2026-05 restructure

Major data restructure scoped to `tenant_slug='sun'` only — all other tenants untouched. Collapses the Lead pipeline from 8 stages to 5 (removing `imported`, `not_interested`, `approved` from the active funnel; remapping existing rows). Collapses Application status from 17 stages to 9 (retiring `submitted_to_underwriting`, `approved`, `approved_open_offers`, `selling`, `approved_never_funded`, `no_offers_available`, `contracts_ordered`, `follow_ups` in favour of cleaner labels). Pure data remaps — no DDL on `tenant_records` itself (all fields are JSONB). Note: this migration had a tenant-resolution bug (queried `slug='sun'` but the correct resolver is `custom_fields.command_center_profile_slug='sun'`). The bug caused a silent no-op on first apply — fixed by migrations 066 and 067.

---

## Migration 065 — Persist send-context on application_lender_threads

**File:** `065_shop_out_thread_send_context.sql`
**Date:** 2026-05-25
**Phase:** SunBiz CRM Phase 6.3-bis

Adds two optional columns to `application_lender_threads`: `body_template` (the rendered per-lender email body the operator approved, with substitutions already applied) and `attachments` (JSONB array of `{filename, storage_path, mime_type, size_bytes}`). Without these columns, the bridge-side `shop_out_sender` would have to re-render using defaults, silently dropping the operator's notes and customizations. This was a "fake-success" failure mode — the send would appear to succeed but would not faithfully reproduce what the operator approved.

---

## Migration 066 — Fix 064's tenant-resolution bug + grant Ezra owner role

**File:** `066_sunbiz_remap_stuck_records.sql`
**Date:** 2026-05-25
**Phase:** Hotfix for migration 064

Diagnoses and fixes the aftermath of migration 064's silent no-op. The bug: 064 queried `tenants WHERE slug = 'sun'` — but the SunBiz tenant's `slug` in the `tenants` table is `submissions`; `sun` is the manifest slug stored in `tenant_manifests.slug`. As a result, 10 application rows kept retired status values (`approved`, `submitted_to_underwriting`) that do not match any post-064 stage and rendered as "HIDDEN" on the Applications page. This migration also grants Ezra the `owner` role on the SunBiz tenant (was missing). Idempotent — safe to re-apply on a clean database.

---

## Migration 067 — Stage remap fix (second pass)

**File:** `067_sunbiz_stage_remap_fix.sql`
**Date:** 2026-05-25
**Phase:** Cleanup for migrations 064 + 066

Second-pass cleanup. Resolves the SunBiz tenant using the same resolver the dashboard uses (`custom_fields.command_center_profile_slug = 'sun'` path, matching `resolveClientProfileSlug` in the Next.js lib). Re-runs both the application status remap and the lead stage remap on any rows still carrying retired values. Fully idempotent — on a clean database after 066, this migration touches zero rows. On a database where 064 or 066 partially applied, it completes the remap safely.

---

## Migration 068 — Shop-out sender claim state

**File:** `068_shop_out_sender_claim_state.sql`
**Date:** 2026-05-25
**Phase:** SunBiz CRM Phase 6.4

Two targeted changes to `application_lender_threads` that support atomic claim semantics in `shop_out_sender`. First: adds `sending` to the status constraint (the sender flips rows from `pending` → `sending` before SMTP, then to `sent` or `error` — the intermediate `sending` state prevents double-sends on crash-restart). Second: adds `send_interaction_id` column (text, nullable, indexed) to record the interaction ID once the email is queued, so the sender can confirm the send happened even if the final status update was lost in a crash.

---

## Migration 069 — Second-meeting expansion (schema foundation)

**File:** `069_sunbiz_meeting2_expansion.sql`
**Date:** 2026-05-25
**Phase:** SunBiz second-meeting expansion

The largest migration in this repo. Adds 14 new tables as the schema foundation for the second-meeting product scope: automated underwriting, follow-up machine, daily planning, cold outreach, shop-out warnings, lender intelligence, email monitoring, personalized links, and agent memory notes. All tables are RLS-ready but RLS is not enabled by this migration (kept as a separate pass for review isolation). Applied atomically — the entire 14-table foundation goes live in one transaction. See `README.md` for the table-by-table purpose list and `docs/DAEMON_PLAYBOOK.md` for the operational details of each daemon that writes to these tables.

**Tables added by this migration:**

1. `application_underwriting` — underwriting run output (append-only)
2. `follow_up_tasks` — Follow-Up Machine queue
3. `daily_plan_items` — per-day operator priority queue
4. `cold_lead_lists` — imported cold lists
5. `cold_leads` — members of a cold list
6. `cold_outreach_campaigns` — multi-channel blast campaign definitions
7. `cold_outreach_recipients` — per-recipient delivery state
8. `shop_out_warnings` — severity-flagged warnings with operator override notes
9. `known_funding_companies` — MCA company registry for debt detection
10. `offer_sources` — offer attribution (email / portal / manual)
11. `email_thread_monitors` — Gmail scanner cursor state per tenant
12. `lender_feedback` — intelligence learning tuples (lender decision + deal profile)
13. `personalized_form_links` — token-backed per-lead form links with expiry
14. `agent_memory_notes` — tenant/lead-scoped operator notes for Solara's context
