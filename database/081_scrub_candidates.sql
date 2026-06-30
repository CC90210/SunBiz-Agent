-- ============================================================================
-- Migration 081 — scrub_candidates (Breeze UW Entry Sheet review queue)
--
-- Backing store for Solara's "Breeze UW Entry Sheet" automation
-- (scripts/mca_lead_scrubber.py). The scrubber pulls MCA lead sheets off the
-- shared Breeze/SunBiz Google Drive, scores each deal, and writes the
-- qualified ones HERE as `pending_review` rows. Nothing enters the lead
-- pipeline until Ezra approves a candidate in the Command Centre — approval
-- creates the lead at the `uw_sheet` stage (via createRecord, which emits
-- BRAVO_RECORD_STATUS_CHANGED so the follow-up lifecycle fires).
--
-- Mirrors the 069 convention: tenant-scoped table, gen_random_uuid() PK,
-- conservative indexes, NO RLS toggle here (service-role writes from the VPS
-- daemon + service-role reads from the dashboard API route, which enforces
-- operator auth + tenant scoping — same access pattern as follow_up_tasks).
--
-- Apply: python scripts/apply_migration.py database/081_scrub_candidates.sql
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.scrub_candidates (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL,
    -- review lifecycle
    status          text NOT NULL DEFAULT 'pending_review',  -- 'pending_review' | 'approved' | 'declined'
    -- scrub output
    tier            text NOT NULL,                           -- 'good' | 'review' (bad-tier is never stored)
    score           int  NOT NULL DEFAULT 0,                 -- 0-100
    reasons         jsonb NOT NULL DEFAULT '[]'::jsonb,      -- ["leverage 12% (+20)", "1 position (+15)", ...]
    decline_reason  text,                                    -- set if a pre-filter tripped (rare for stored rows)
    previously_submitted boolean NOT NULL DEFAULT false,     -- CC's #1 signal (when resolvable)
    leverage_pct    numeric(8,2),
    monthly_revenue numeric(14,2),
    -- the normalized lead payload (tenant_records.data shape, stage='uw_sheet').
    -- On approval this is handed verbatim to createRecord(entity='lead').
    lead_data       jsonb NOT NULL,
    -- provenance + idempotency
    source_file     text,                                    -- sheet display name
    source_file_id  text,                                    -- Drive file id
    row_hash        text NOT NULL,                           -- scrubber/state.row_hash(lead_data)
    scoring_config_version text,
    scrubbed_at     timestamptz,
    -- review result
    reviewed_by     text,                                    -- Ezra's email / operator id
    reviewed_at     timestamptz,
    review_note     text,
    created_lead_id uuid,                                    -- tenant_records.id created on approval
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Idempotency: one candidate per (tenant, normalized-lead identity). The
-- daemon's ledger is the first guard; this is the DB backstop so a ledger
-- loss can't create duplicate review items for the same merchant.
CREATE UNIQUE INDEX IF NOT EXISTS scrub_candidates_tenant_rowhash_uniq
    ON public.scrub_candidates(tenant_id, row_hash);

-- Queue query: pending review items newest-first.
CREATE INDEX IF NOT EXISTS scrub_candidates_tenant_status_idx
    ON public.scrub_candidates(tenant_id, status, created_at DESC);

-- Trace an approved candidate to the lead it created.
CREATE INDEX IF NOT EXISTS scrub_candidates_created_lead_idx
    ON public.scrub_candidates(tenant_id, created_lead_id)
    WHERE created_lead_id IS NOT NULL;

COMMENT ON TABLE public.scrub_candidates IS
    '081 — Breeze UW Entry Sheet review queue. Solara''s scrubber writes pending_review rows from Drive sheets; Ezra approves → createRecord lead @uw_sheet. bad-tier leads are not stored.';

-- RLS backstop (security review 2026-06-30). lead_data can carry PII
-- (ssn_last4 / dob / ein when a source sheet includes them). Enable RLS with NO
-- permissive policy so anon / authenticated clients get ZERO rows by default.
-- The service-role key — used by BOTH the VPS daemon (writes) and the dashboard
-- API route (reads, via getServiceSupabase) — has BYPASSRLS, so the real access
-- paths are unaffected. This is stricter than the 069 sibling tables, and
-- intentional given the PII surface. (ENABLE, not FORCE, so owner-connected
-- admin/migration tooling still works.)
ALTER TABLE public.scrub_candidates ENABLE ROW LEVEL SECURITY;

COMMIT;

-- ============================================================================
-- VERIFY:
--   SELECT to_regclass('public.scrub_candidates');   -- expect non-null
--   \d public.scrub_candidates
-- ============================================================================
