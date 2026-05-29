-- ============================================================================
-- Migration 076 — SunBiz profile defaults backfill
--
-- Phase 1 of the multi-employee personalization plan (2026-05-29).
--
-- Two backfills against user_profiles for any row attached to the SunBiz
-- tenant:
--
--   1. display_name fallback to first word of full_name. New invitees
--      land with display_name NULL; the welcome wizard would normally
--      ask them to confirm one, but per the May 29 routing decision
--      invitees skip the wizard entirely. Without this backfill they
--      end up displayed as their full email everywhere, which is ugly
--      and a tiny privacy leak (full name visible in team listings).
--
--   2. primary_agent default of 'solara' for any SunBiz member where
--      it's currently 'bravo' (the platform-wide default seeded at
--      provisioning). Bravo is the OASIS lead-architect persona and
--      isn't surfaced inside the SunBiz Command Center — opening a
--      "Chat with Bravo" widget from a SunBiz seat would route to the
--      wrong agent runtime. Solara is SunBiz's operations agent and
--      the correct first-touch for every SunBiz seat.
--
-- Idempotent. Both UPDATEs use COALESCE / WHERE guards that no-op on
-- already-correct rows. Safe to re-run.
-- ============================================================================

BEGIN;

DO $$
DECLARE
  _sunbiz_id uuid;
  _display_updated INT := 0;
  _agent_updated   INT := 0;
BEGIN
  SELECT id INTO _sunbiz_id FROM public.tenants WHERE name = 'SunBiz' LIMIT 1;
  IF _sunbiz_id IS NULL THEN
    RAISE NOTICE 'SunBiz tenant not found — no-op.';
    RETURN;
  END IF;

  -- 1. display_name backfill — split full_name on whitespace, take the
  --    first token. NULLIF guards against an empty full_name (would
  --    leave display_name NULL too, which is fine — wizard can still
  --    fix it via Settings).
  UPDATE public.user_profiles
     SET display_name = NULLIF(split_part(TRIM(full_name), ' ', 1), '')
   WHERE tenant_id = _sunbiz_id
     AND display_name IS NULL
     AND full_name IS NOT NULL
     AND TRIM(full_name) <> '';

  GET DIAGNOSTICS _display_updated = ROW_COUNT;

  -- 2. primary_agent default → solara for SunBiz members currently on
  --    'bravo' (the platform default). Other values (helios, solara
  --    already, custom) are left alone — operator/employee preference.
  UPDATE public.user_profiles
     SET primary_agent = 'solara'
   WHERE tenant_id = _sunbiz_id
     AND primary_agent = 'bravo';

  GET DIAGNOSTICS _agent_updated = ROW_COUNT;

  RAISE NOTICE 'SunBiz profile defaults: % display_name set, % primary_agent → solara',
    _display_updated, _agent_updated;
END $$;

COMMIT;
