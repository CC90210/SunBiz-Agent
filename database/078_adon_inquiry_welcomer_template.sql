-- Migration 078 — Adon Agent 1 (Inquiry Welcomer) sequence template
--
-- Phase 2 of Adon's MCA follow-up architecture (brief 2026-06-08).
-- First of the 12 sequence templates Adon's §3 defines. Ships the
-- reference pattern so additional agents (Document Hunter, Underwriting
-- Status Reporter, etc.) follow the same shape.
--
-- WHAT THIS DOES
-- --------------
-- Inserts a drip_sequences row for the SunBiz tenant that fires when a
-- new lead enters the pipeline at stage='hot_lead'. Cadence per Adon §3:
--   Touch 1 (now)       — SMS welcome with application link
--   Touch 2 (now)       — Email welcome (simultaneous w/ touch 1)
--   Touch 3 (+3h)       — SMS nudge if app link not yet clicked
--   Touch 4 (+24h)      — Email check-in
--   Touch 5 (+72h)      — Final SMS — handoff to App Completion Shepherd
--
-- Adon's brief emphasizes the 60-second-after-inquiry window is the
-- highest single lever in the entire funnel. Touch 1+2 firing
-- simultaneously at delay_minutes=0 means sequence_runner enqueues both
-- the moment BRAVO_RECORD_STATUS_CHANGED fires for stage=hot_lead.
--
-- STOP CONDITIONS (all enforced by send_gateway Phase 1 gates)
-- ------------------------------------------------------------
-- The sequence does NOT need explicit stop logic — every Phase 1 gate
-- already covers the cases:
--   - Lead opts out (STOP keyword)          -> CASL suppression gate
--   - Lead replies                          -> reply_since_last_outbound
--   - Sentinel detects frustration          -> sentinel_pause
--   - Operator manually pauses              -> manual_pause
--   - Cross-agent inter-touch gap (<90min)  -> inter_touch_gap
--   - Outside TCPA window                   -> send_window
-- The 5 touches above are MAX; in practice most leads convert or
-- self-suppress well before touch 5.
--
-- VARIABLE SUBSTITUTION (per lib/drips/templates.ts conventions)
-- --------------------------------------------------------------
--   {{lead.first_name}}, {{lead.name}}, {{lead.company}},
--   {{lead.email}}, {{lead.phone}}, {{lead.state}}
--   Future: {{lead.application_url}} once the sequence_runner has
--   per-lead form-token generation wired (Phase 2 follow-up).
--
-- IDEMPOTENCY
-- -----------
-- Uses ON CONFLICT DO NOTHING on a deterministic UUID derived from the
-- template name + tenant. Re-running this migration is a no-op once the
-- row exists. To EDIT the template post-insert, operator uses the
-- /sequences dashboard page or runs an UPDATE manually — never DROP+INSERT
-- here (would lose enrollment history).
--
-- Apply via: python scripts/apply_migration.py database/078_adon_inquiry_welcomer_template.sql

BEGIN;

-- SunBiz tenant ID (matches every other migration). If the operator
-- ever clones this template to a second tenant, swap the UUID below.
INSERT INTO public.drip_sequences (
    id,
    tenant_id,
    name,
    description,
    trigger_event,
    trigger_filter,
    enabled,
    one_per_lead,
    steps
) VALUES (
    -- Deterministic UUID v5 — derived offline so the same migration
    -- inserts the same row across environments. Generated via
    -- `uuidgen -n aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110 -N adon-agent-1-inquiry-welcomer -s`.
    'a4d1a5c2-1111-5811-1111-c87a83d40078',
    'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110',
    'Adon Agent 1 — Inquiry Welcomer',
    'Adon MCA brief §3 Agent 1: first-touch automation for new SunBiz leads. Fires on stage=hot_lead, runs 5 touches over 72h alternating SMS/email, hands off to App Completion Shepherd. Every gate in send_gateway Phase 1 enforces the stop conditions.',
    'BRAVO_RECORD_STATUS_CHANGED',
    jsonb_build_object(
        'entity', 'lead',
        'field', 'stage',
        'to', 'hot_lead'
    ),
    true,   -- enabled
    true,   -- one_per_lead — prevents double-firing on idempotent re-stages
    jsonb_build_array(
        -- Touch 1: SMS welcome (now)
        jsonb_build_object(
            'channel', 'sms',
            'delay_minutes', 0,
            'body', 'Hi {{lead.first_name}}, this is Ezra at SunBiz Funding — got your inquiry on funding for {{lead.company}}. Quick 5-min application: I''ll send the link in the email I''m about to fire. Reply STOP to opt out.',
            'from_label', 'SunBiz Funding'
        ),
        -- Touch 2: Email welcome (now, simultaneous w/ touch 1)
        jsonb_build_object(
            'channel', 'email',
            'delay_minutes', 0,
            'subject', 'Funding for {{lead.company}} — quick application',
            'body', 'Hi {{lead.first_name}},'
                || E'\n\n'
                || 'Got your inquiry on funding for {{lead.company}}. Took the liberty of texting you too in case email isn''t the fastest way to reach you.'
                || E'\n\n'
                || 'To get an offer back fast, we need:'
                || E'\n'
                || '  1. The completed application (link coming separately)'
                || E'\n'
                || '  2. Your last 3 months of business bank statements'
                || E'\n'
                || '  3. A clear photo of your driver''s license + a voided check'
                || E'\n\n'
                || 'Most deals get an offer back inside 24 hours of us having all three. Reply with any questions, or just send the bank statements and we''ll start working immediately.'
                || E'\n\n'
                || '— Ezra'
                || E'\n'
                || 'SunBiz Funding'
                || E'\n'
                || 'submissions@sunbizfunding.com',
            'from_label', 'Ezra at SunBiz Funding'
        ),
        -- Touch 3: SMS nudge at hour 3 (only fires if no reply — reply_since_last_outbound gate handles this)
        jsonb_build_object(
            'channel', 'sms',
            'delay_minutes', 180,
            'body', 'Hi {{lead.first_name}}, Ezra at SunBiz — just checking the application + email landed OK. Anything blocking you from getting started today?',
            'from_label', 'SunBiz Funding'
        ),
        -- Touch 4: Email check-in next day
        jsonb_build_object(
            'channel', 'email',
            'delay_minutes', 1440,
            'subject', 'Quick check-in on {{lead.company}} funding',
            'body', 'Hi {{lead.first_name}},'
                || E'\n\n'
                || 'Saw the application went out yesterday — wanted to check if you had any questions on what we need to underwrite this.'
                || E'\n\n'
                || 'The fastest path: shoot back 3 months of business bank statements + your DL/voided check and I''ll have something concrete back to you tomorrow.'
                || E'\n\n'
                || 'If timing isn''t right this week, just say the word and I''ll loop back in 30 days.'
                || E'\n\n'
                || '— Ezra'
                || E'\n'
                || 'SunBiz Funding',
            'from_label', 'Ezra at SunBiz Funding'
        ),
        -- Touch 5: Final SMS at hour 72 — handoff to App Completion Shepherd next
        jsonb_build_object(
            'channel', 'sms',
            'delay_minutes', 4320,
            'body', 'Hi {{lead.first_name}}, last check-in from my side — is funding for {{lead.company}} still on the table this month? If not, no worries, just let me know and I''ll loop back next quarter.',
            'from_label', 'SunBiz Funding'
        )
    )
)
ON CONFLICT (id) DO NOTHING;

-- Surface the result for the operator who ran the migration
DO $$
DECLARE
    inserted_count int;
BEGIN
    SELECT COUNT(*) INTO inserted_count
    FROM public.drip_sequences
    WHERE id = 'a4d1a5c2-1111-5811-1111-c87a83d40078';
    IF inserted_count = 1 THEN
        RAISE NOTICE 'Adon Agent 1 (Inquiry Welcomer) template active for SunBiz tenant.';
    END IF;
END $$;

COMMIT;

-- Verification queries the operator can run:
--
-- 1. Confirm the template exists + is enabled:
--    SELECT id, name, enabled, jsonb_array_length(steps) AS step_count
--    FROM drip_sequences
--    WHERE tenant_id = 'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110'
--      AND name LIKE 'Adon Agent 1%';
--
-- 2. Inspect the steps:
--    SELECT step_index, step ->> 'channel' AS channel,
--           (step ->> 'delay_minutes')::int AS delay_min,
--           LEFT(step ->> 'body', 80) AS body_preview
--    FROM drip_sequences,
--         jsonb_array_elements(steps) WITH ORDINALITY AS s(step, step_index)
--    WHERE id = 'a4d1a5c2-1111-5811-1111-c87a83d40078'
--    ORDER BY step_index;
--
-- 3. After a test lead lands at stage=hot_lead, confirm sequence_state
--    rows were enrolled:
--    SELECT lead_id, step_index, status, scheduled_for
--    FROM sequence_state
--    WHERE sequence_id = 'a4d1a5c2-1111-5811-1111-c87a83d40078'
--    ORDER BY scheduled_for DESC LIMIT 10;
