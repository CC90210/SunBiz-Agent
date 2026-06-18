-- ============================================================================
-- 079 — application_lender_threads: persist the CC'd-agent signer identity
-- ============================================================================
-- The dashboard's POST /api/applications/[id]/shop-out resolves the deal's
-- single CC'd roster agent → that operator's name / email / phone, and passes
-- them so the outbound lender email signs as THAT agent (signature "— {name}",
-- footer "receiving this from {name} at SunBiz Funding", body {{agent.first_name}}).
--
-- The chat-triggered bridge tool already injected these via env overrides
-- (bravo_cli.bridge_tools._signer_env_overrides). But the LIVE send path is the
-- cron daemon shop_out_sender.py, which calls send_gateway.send() directly and
-- never set the signer env — so queued AND retried lender emails reverted to the
-- brand default signer ("Ezra" / "SunBiz Submissions"). Mirroring the owner_phone
-- precedent (migration 069), we resolve the signer at QUEUE time and store it on
-- the thread, so reassignment after queue doesn't silently change the signer and
-- the cron path can apply it deterministically.
--
-- All three columns are nullable: a thread without a resolved single agent (or a
-- legacy thread) falls back to the brand default exactly as before.
ALTER TABLE public.application_lender_threads
    ADD COLUMN IF NOT EXISTS signer_name  text,
    ADD COLUMN IF NOT EXISTS signer_email text,
    ADD COLUMN IF NOT EXISTS signer_phone text;

COMMENT ON COLUMN public.application_lender_threads.signer_name IS
    '079 — CC''d-agent display name snapshot, applied by shop_out_sender.py as BRAVO_FROM_DISPLAY_<BRAND> at send time so the signature/footer/body read this agent (not the brand default). Resolved at queue time, like owner_phone.';
COMMENT ON COLUMN public.application_lender_threads.signer_email IS
    '079 — CC''d-agent from-email snapshot (BRAVO_FROM_EMAIL_<BRAND>). Nullable; falls back to brand default.';
COMMENT ON COLUMN public.application_lender_threads.signer_phone IS
    '079 — CC''d-agent phone snapshot (BRAVO_FROM_PHONE_<BRAND>) for the signature phone line. Nullable; line omitted when empty (Adon spec §6).';
