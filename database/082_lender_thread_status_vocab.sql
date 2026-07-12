-- 082_lender_thread_status_vocab.sql   (SunBiz-Agent repo migration series)
--
-- ⚠️ NUMBER COLLISION: business-empire-agent also has a database/082 (the RLS
--    lockdown). These are two independent series on the SAME Supabase project
--    — apply THIS one by its topic name (lender_thread_status_vocab), not by
--    the bare number.
-- ⚠️ AFTER APPLYING: restart the daemon —
--       pm2 restart sunbiz-lender-response-classifier
--    The classifier holds an in-memory "constraint-rejected statuses" backoff
--    set (stops the pre-082 write storm). Applying this migration does NOT
--    clear that set in a running process, so SLA flips stay suppressed until
--    the daemon restarts.
--
-- Purpose: Re-add the terminal thread statuses that migration 068 dropped but
-- that live code still writes + reads.
--
-- Background (audit 2026-07-12): migration 068 replaced the original 044
-- status vocabulary with ('pending','sending','sent','replied',
-- 'offer_received','declined','error'). But two producers still write values
-- outside that set, and every such write is rejected by the CHECK constraint:
--   * lender_response_classifier.sla_sweep writes 'no_response' when a sent
--     thread passes its SLA with no reply (~462 rejected writes/tick = the
--     "302k-write storm"). daily_plan_generator.py reads the literal
--     'no_response' (treats it as a still-no-response state), so it cannot be
--     remapped without breaking the operator's daily plan.
--   * bridge_tools.py writes 'suppressed' when a shop-out send is CASL-blocked.
-- The classifier's other pre-068 words (approved/info_requested/responded) were
-- remapped in code onto the legal set (approved->offer_received,
-- info_requested/unclear->replied), so they are NOT re-added here — only the
-- two values that are semantically distinct AND read downstream by literal.
--
-- Idempotent + safe: metadata-only ALTER. The new list is a strict superset of
-- the current one, so it validates against all existing rows (live set is
-- sent/declined/error only as of 2026-07-12).

ALTER TABLE public.application_lender_threads
  DROP CONSTRAINT IF EXISTS application_lender_threads_status_check;

ALTER TABLE public.application_lender_threads
  ADD CONSTRAINT application_lender_threads_status_check
  CHECK (status IN (
    'pending', 'sending', 'sent', 'replied', 'offer_received',
    'declined', 'error',
    'no_response',   -- sla_sweep: sent past SLA, lender never replied
    'suppressed'     -- bridge_tools: shop-out send CASL-suppressed
  ));

COMMENT ON COLUMN public.application_lender_threads.status IS
  'Shop-out lifecycle. pending -> sending -> sent, then replied/offer_received/declined/error/no_response by the response classifier, or suppressed when a send is CASL-blocked.';
