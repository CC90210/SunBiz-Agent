-- Repair 1: revoke Emily's typo'd invite (emliy@) so it can't be used by accident.
-- The corrected invite will be created via the dashboard /api/team/invites POST
-- route so the token is generated server-side (raw form shown exactly once).

BEGIN;

UPDATE public.tenant_invites
   SET revoked_at = now()
 WHERE email = 'emliy@sunbizfunding.com'
   AND revoked_at IS NULL
   AND redeemed_at IS NULL;

COMMIT;
