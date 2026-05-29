-- Repair onboarding state for Alex + Jordan so the middleware gate
-- (already fixed in code to skip when tenant_id is set) ALSO caches
-- the "onboarded=1" cookie on their next page load. Without this,
-- their pages keep paying the per-request DB query until they manually
-- complete the wizard via Settings.
--
-- Also stamps invited_by on their rows so the audit trail reflects
-- reality — they were attached via invite, not via fresh-tenant
-- provisioning. created_by on the matching tenant_invites row is the
-- person who issued the invite (CC's submissions@ owner account).

BEGIN;

UPDATE public.user_profiles up
   SET onboarding_completed_at = COALESCE(up.onboarding_completed_at, now()),
       invited_by = COALESCE(up.invited_by, ti.created_by)
  FROM public.tenant_invites ti
 WHERE up.email = ti.email
   AND up.email IN ('alex@sunbizfunding.com', 'jordan@sunbizfunding.com')
   AND ti.redeemed_at IS NOT NULL;

COMMIT;
