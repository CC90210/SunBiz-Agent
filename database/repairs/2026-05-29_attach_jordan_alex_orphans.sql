-- Repair 2: attach Jordan + Alex to SunBiz tenant.
--
-- Both have auth.users records (email-confirmed) but no user_profiles row
-- linking them to a tenant. Their invites are pinned to their correct
-- emails and still unredeemed. This runs the same logic the
-- redeem_tenant_invite RPC would have run during signup, but atomically
-- and idempotently.

BEGIN;

DO $$
DECLARE
  _sunbiz_id  uuid;
  _attached   int := 0;
  _redeemed   int := 0;
BEGIN
  SELECT id INTO _sunbiz_id FROM public.tenants WHERE name = 'SunBiz' LIMIT 1;
  IF _sunbiz_id IS NULL THEN
    RAISE EXCEPTION 'SunBiz tenant not found - aborting';
  END IF;

  RAISE NOTICE 'SunBiz tenant: %', _sunbiz_id;

  -- Attach orphan users (Jordan + Alex) to the SunBiz tenant via
  -- user_profiles. ON CONFLICT covers the case where a profile row
  -- already exists with NULL tenant_id (would be a redo-safe upsert).
  WITH attached AS (
    INSERT INTO public.user_profiles
      (auth_user_id, email, full_name, tenant_id, team_role, joined_at, is_owner)
    SELECT
      u.id,
      u.email,
      COALESCE(u.raw_user_meta_data->>'full_name', u.email),
      _sunbiz_id,
      'member',
      now(),
      false
    FROM auth.users u
    WHERE u.email IN ('jordan@sunbizfunding.com', 'alex@sunbizfunding.com')
      AND NOT EXISTS (
        SELECT 1 FROM public.user_profiles p
         WHERE p.auth_user_id = u.id AND p.tenant_id IS NOT NULL
      )
    ON CONFLICT (auth_user_id) DO UPDATE
      SET tenant_id  = EXCLUDED.tenant_id,
          team_role  = EXCLUDED.team_role,
          joined_at  = COALESCE(public.user_profiles.joined_at, now())
    RETURNING id
  )
  SELECT count(*) INTO _attached FROM attached;

  -- Mark the corresponding invites redeemed so the audit trail reflects
  -- reality. redeemed_by is set to the auth user whose email matches.
  WITH marked AS (
    UPDATE public.tenant_invites ti
       SET redeemed_at = now(),
           redeemed_by = u.id
      FROM auth.users u
     WHERE ti.email = u.email
       AND ti.email IN ('jordan@sunbizfunding.com', 'alex@sunbizfunding.com')
       AND ti.redeemed_at IS NULL
       AND ti.revoked_at IS NULL
       AND ti.tenant_id = _sunbiz_id
    RETURNING ti.id
  )
  SELECT count(*) INTO _redeemed FROM marked;

  RAISE NOTICE 'Repair complete: % profiles attached, % invites marked redeemed', _attached, _redeemed;
END $$;

COMMIT;
