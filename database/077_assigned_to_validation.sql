-- ============================================================================
-- Migration 077 — assigned_to JSONB validation + name→UUID migration
--
-- Phase 3 of the multi-employee personalization plan (2026-05-29).
--
-- Soft-ownership model: tenant_records.data.assigned_to is the
-- auth_user_id (uuid string) of the employee responsible for surfacing
-- that lead/application/funded_deal/renewal on their personal dashboard.
-- The field is a presentation hint — anyone can still act on any record
-- regardless of who's assigned. No row-level authorization gate; just a
-- preference for where it renders in the dashboard hierarchy.
--
-- The SunBiz import process historically wrote DISPLAY NAMES ("jordan
-- Colleson", "Alex johnson", or comma-separated combos) into the
-- assigned_to field. Phase 3 of the personalization plan locks the
-- contract on UUIDs because the "my deals" widget needs to query
-- against auth_user_id, not free-text. This migration:
--
--   1. Maps existing name-string values → auth_user_id by joining the
--      first comma-separated name (case-insensitive) against
--      user_profiles.full_name and display_name. Unmatched name strings
--      get set to NULL (logged via RAISE NOTICE so the operator can
--      see what fell through).
--
--   2. Adds a CHECK constraint forcing future writes to be UUID-shaped
--      or NULL.
--
--   3. Adds a partial GIN index on (tenant_id, assigned_to) for the
--      relevant entity types so the personal-dashboard query is
--      index-backed.
--
-- Idempotent. Re-runnable.
-- ============================================================================

BEGIN;

DO $$
DECLARE
  _migrated INT := 0;
  _nulled   INT := 0;
BEGIN
  -- 1. Map name strings → UUIDs. The first comma-separated token is
  --    the primary owner; trailing tokens (co-assignments) are dropped
  --    because the schema is single-assignee. ILIKE match against
  --    full_name or display_name catches case + minor whitespace
  --    differences. NULLIF + TRIM defends against leading/trailing
  --    whitespace in the source.
  WITH name_to_uuid AS (
    SELECT
      tr.id,
      up.auth_user_id::text AS matched_uuid
    FROM public.tenant_records tr
    LEFT JOIN public.user_profiles up
      ON LOWER(TRIM(SPLIT_PART(tr.data->>'assigned_to', ',', 1)))
       = LOWER(TRIM(COALESCE(NULLIF(up.full_name, ''), up.display_name)))
    WHERE tr.entity_type IN ('lead', 'application', 'funded_deal', 'renewal')
      AND (tr.data->>'assigned_to') IS NOT NULL
      AND (tr.data->>'assigned_to') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  )
  UPDATE public.tenant_records tr
     SET data = jsonb_set(tr.data, '{assigned_to}', to_jsonb(ntu.matched_uuid))
    FROM name_to_uuid ntu
   WHERE tr.id = ntu.id
     AND ntu.matched_uuid IS NOT NULL;

  GET DIAGNOSTICS _migrated = ROW_COUNT;

  -- 2. Anything still not a UUID after the join (unmappable names like
  --    "Joe Morgan" who has no user profile) gets NULLed so the CHECK
  --    constraint doesn't reject it. We use jsonb_set with a NULL value
  --    cast through 'null'::jsonb to actually REMOVE the field rather
  --    than store the literal string "null".
  WITH unmapped AS (
    SELECT id
    FROM public.tenant_records
    WHERE entity_type IN ('lead', 'application', 'funded_deal', 'renewal')
      AND (data->>'assigned_to') IS NOT NULL
      AND (data->>'assigned_to') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  )
  UPDATE public.tenant_records tr
     SET data = tr.data - 'assigned_to'
    FROM unmapped u
   WHERE tr.id = u.id;

  GET DIAGNOSTICS _nulled = ROW_COUNT;

  RAISE NOTICE 'assigned_to migration: % rows mapped to UUID, % rows nulled (unmappable names)',
    _migrated, _nulled;
END $$;

-- 3. CHECK constraint. Now that no bad rows remain, we can add this
--    without NOT VALID — but the IF NOT EXISTS guard makes it
--    idempotent for re-runs.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_name = 'tenant_records'
      AND constraint_name = 'tenant_records_assigned_to_uuid_shape'
  ) THEN
    ALTER TABLE public.tenant_records
      ADD CONSTRAINT tenant_records_assigned_to_uuid_shape
      CHECK (
        entity_type NOT IN ('lead', 'application', 'funded_deal', 'renewal')
        OR (data->>'assigned_to') IS NULL
        OR (data->>'assigned_to') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      );
  END IF;
END $$;

-- 4. Partial index keyed on the assigned_to JSONB field. The personal-
--    dashboard query filters by (tenant_id, assigned_to); this index
--    makes that filter O(log n) instead of full scan.
CREATE INDEX IF NOT EXISTS idx_tenant_records_assigned_to
  ON public.tenant_records (tenant_id, (data->>'assigned_to'))
  WHERE entity_type IN ('lead', 'application', 'funded_deal', 'renewal')
    AND (data->>'assigned_to') IS NOT NULL;

COMMIT;
