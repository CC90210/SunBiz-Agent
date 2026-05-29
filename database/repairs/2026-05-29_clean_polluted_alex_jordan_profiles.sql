-- Clean up Alex + Jordan's profiles. brand is NOT NULL so we use the
-- canonical SunBiz value (matches the owner's row).

BEGIN;

UPDATE public.user_profiles
   SET full_name    = 'Alex',
       display_name = COALESCE(NULLIF(display_name, ''), 'Alex'),
       brand        = 'SunBiz'
 WHERE email = 'alex@sunbizfunding.com';

UPDATE public.user_profiles
   SET full_name    = 'Jordan',
       display_name = COALESCE(NULLIF(display_name, ''), 'Jordan'),
       brand        = 'SunBiz'
 WHERE email = 'jordan@sunbizfunding.com';

COMMIT;
