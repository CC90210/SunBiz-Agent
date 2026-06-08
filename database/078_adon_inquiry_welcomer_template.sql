-- Migration 078 — Adon Agent 1 (Inquiry Welcomer) sequence template
--
-- Phase 2 of Adon's MCA follow-up architecture (brief 2026-06-08).
-- First of the 12 sequence templates Adon's §3 defines. Ships the
-- reference pattern so additional agents (Document Hunter, etc.) follow
-- the same shape.
--
-- POST-CODEX-REVIEW (2026-06-08, second pass):
--   - SHIPS DISABLED (enabled=false). Operator MUST do two things before
--     flipping enabled=true via /sequences:
--       1. Replace {{lead.application_url}} with a real per-lead form
--          URL (Phase 2 follow-up wires per-lead token generation).
--       2. Confirm the SunBiz CASL business_address in BRAND_IDENTITY
--          is non-placeholder, OR change sequence_runner to use
--          brand="sunbiz" instead of the hardcoded brand="oasis".
--   - Email steps include BOTH body_text AND body_html. send_gateway
--     blocks OASIS commercial sends without body_html (line 2459), so
--     a text-only step would have stalled the whole drip after Touch 1.
--   - Logical-key idempotency: a DO block checks for an existing
--     Inquiry Welcomer for this tenant before insert, not just the
--     deterministic UUID. Prevents accidental double-enrollment if
--     the operator pre-created the template via /sequences UI.
--   - Touch 1 SMS no longer promises a link that isn't in the email
--     (Codex P2-#3). Both touches now self-contain the apply-now CTA.
--
-- WHAT THIS DOES
-- --------------
-- Inserts a drip_sequences row for the SunBiz tenant that fires when a
-- new lead enters the pipeline at stage='hot_lead'. Cadence per Adon §3:
--   Touch 1 (t=0)   — SMS welcome with apply-now CTA
--   Touch 2 (t=0)   — Email welcome (simultaneous w/ touch 1)
--   Touch 3 (t=+3h) — SMS nudge if no reply yet
--   Touch 4 (t=+24h)— Email check-in
--   Touch 5 (t=+72h)— Final SMS — handoff to App Completion Shepherd
--
-- STOP CONDITIONS (all enforced by send_gateway Phase 1 gates — no
-- explicit cancellation needed in the template):
--   - Lead opts out (STOP keyword)        -> CASL suppression
--   - Lead replies                        -> reply_since_last_outbound
--   - Sentinel detects frustration        -> sentinel_pause
--   - Operator manually pauses            -> manual_pause
--   - Cross-agent gap (<90min)            -> inter_touch_gap
--   - Outside TCPA window                 -> send_window (state→tz)
--
-- VARIABLE SUBSTITUTION (per lib/drips/templates.ts):
--   {{lead.first_name}}, {{lead.name}}, {{lead.company}},
--   {{lead.email}}, {{lead.phone}}, {{lead.state}}
--   {{lead.application_url}} — PLACEHOLDER; wire before enabling.
--
-- Apply via: python scripts/apply_migration.py database/078_adon_inquiry_welcomer_template.sql

BEGIN;

-- Logical-key idempotency check first. Skip insert if any enabled OR
-- recently-created Inquiry Welcomer already exists for this tenant +
-- trigger. Prevents this migration from creating a second copy if the
-- operator already authored one via /sequences (or a prior hotfix).
DO $$
DECLARE
    sunbiz_tenant uuid := 'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110';
    template_uuid uuid := 'a4d1a5c2-1111-5811-1111-c87a83d40078';
    existing_id   uuid;
BEGIN
    SELECT id INTO existing_id
    FROM public.drip_sequences
    WHERE tenant_id = sunbiz_tenant
      AND trigger_event = 'BRAVO_RECORD_STATUS_CHANGED'
      AND (trigger_filter->>'entity') = 'lead'
      AND (trigger_filter->>'field')  = 'stage'
      AND (trigger_filter->>'to')     = 'hot_lead'
      AND (name ILIKE '%Inquiry Welcomer%' OR name ILIKE '%Adon Agent 1%')
    LIMIT 1;

    IF existing_id IS NOT NULL AND existing_id <> template_uuid THEN
        RAISE NOTICE 'Skipping insert — an Inquiry Welcomer already exists for SunBiz tenant (id=%). Edit that row via /sequences instead of creating a duplicate.', existing_id;
        RETURN;
    END IF;

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
        template_uuid,
        sunbiz_tenant,
        'Adon Agent 1 — Inquiry Welcomer',
        'Adon MCA brief §3 Agent 1. SHIPS DISABLED — operator must wire {{lead.application_url}} per-lead token + confirm SunBiz CASL address before flipping enabled=true via /sequences. Five touches over 72h alternating SMS/email; stop conditions enforced by send_gateway Phase 1 gates.',
        'BRAVO_RECORD_STATUS_CHANGED',
        jsonb_build_object(
            'entity', 'lead',
            'field', 'stage',
            'to', 'hot_lead'
        ),
        false,   -- DISABLED — see header comment for activation checklist
        true,    -- one_per_lead
        jsonb_build_array(
            -- Touch 1: SMS welcome (now). Self-contained — no promise of
            -- a link arriving separately.
            jsonb_build_object(
                'channel', 'sms',
                'delay_minutes', 0,
                'body', 'Hi {{lead.first_name}}, Ezra at SunBiz Funding — got your inquiry on funding for {{lead.company}}. Apply here: {{lead.application_url}} — takes 5 min. Reply STOP to opt out.',
                'from_label', 'SunBiz Funding'
            ),
            -- Touch 2: Email welcome (now, simultaneous w/ touch 1). Includes
            -- body_html — REQUIRED for commercial sends per send_gateway gate.
            jsonb_build_object(
                'channel', 'email',
                'delay_minutes', 0,
                'subject', 'Funding for {{lead.company}} — quick application',
                'body_text', 'Hi {{lead.first_name}},'
                    || E'\n\n'
                    || 'Got your inquiry on funding for {{lead.company}}. Application takes 5 minutes:'
                    || E'\n\n'
                    || '  {{lead.application_url}}'
                    || E'\n\n'
                    || 'To get an offer back fast, alongside the application we need:'
                    || E'\n'
                    || '  - Last 3 months of business bank statements'
                    || E'\n'
                    || '  - Clear photo of your driver''s license + a voided check'
                    || E'\n\n'
                    || 'Most deals get an offer back inside 24 hours of us having all three. Reply with questions or upload directly via the application form.'
                    || E'\n\n'
                    || '— Ezra'
                    || E'\n'
                    || 'SunBiz Funding'
                    || E'\n'
                    || 'submissions@sunbizfunding.com',
                'body_html', '<p>Hi {{lead.first_name}},</p>'
                    || '<p>Got your inquiry on funding for <strong>{{lead.company}}</strong>. Application takes 5 minutes:</p>'
                    || '<p><a href="{{lead.application_url}}" style="background:#1F7A56;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;">Start application</a></p>'
                    || '<p>To get an offer back fast, alongside the application we need:</p>'
                    || '<ul>'
                    || '<li>Last 3 months of business bank statements</li>'
                    || '<li>Clear photo of your driver''s license + a voided check</li>'
                    || '</ul>'
                    || '<p>Most deals get an offer back inside 24 hours of us having all three. Reply with questions or upload directly via the application form.</p>'
                    || '<p>&mdash; Ezra<br>SunBiz Funding<br><a href="mailto:submissions@sunbizfunding.com">submissions@sunbizfunding.com</a></p>',
                'from_label', 'Ezra at SunBiz Funding'
            ),
            -- Touch 3: SMS nudge at hour 3
            jsonb_build_object(
                'channel', 'sms',
                'delay_minutes', 180,
                'body', 'Hi {{lead.first_name}}, Ezra at SunBiz — just checking the application link landed OK. Anything blocking you from getting started today?',
                'from_label', 'SunBiz Funding'
            ),
            -- Touch 4: Email check-in next day
            jsonb_build_object(
                'channel', 'email',
                'delay_minutes', 1440,
                'subject', 'Quick check-in on {{lead.company}} funding',
                'body_text', 'Hi {{lead.first_name}},'
                    || E'\n\n'
                    || 'Saw the application went out yesterday — wanted to check if you had any questions.'
                    || E'\n\n'
                    || 'The fastest path: complete the application ({{lead.application_url}}) + send 3 months of bank statements and I''ll have something concrete back to you tomorrow.'
                    || E'\n\n'
                    || 'If timing isn''t right this week, just say the word and I''ll loop back in 30 days.'
                    || E'\n\n'
                    || '— Ezra'
                    || E'\n'
                    || 'SunBiz Funding',
                'body_html', '<p>Hi {{lead.first_name}},</p>'
                    || '<p>Saw the application went out yesterday &mdash; wanted to check if you had any questions.</p>'
                    || '<p>The fastest path: <a href="{{lead.application_url}}">complete the application</a> + send 3 months of bank statements and I''ll have something concrete back to you tomorrow.</p>'
                    || '<p>If timing isn''t right this week, just say the word and I''ll loop back in 30 days.</p>'
                    || '<p>&mdash; Ezra<br>SunBiz Funding</p>',
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

    RAISE NOTICE 'Adon Agent 1 (Inquiry Welcomer) template inserted DISABLED. Enable via /sequences after wiring application_url + confirming CASL address.';
END $$;

COMMIT;

-- Operator verification queries:
--
-- 1. Confirm the template exists + is disabled (expected initial state):
--    SELECT id, name, enabled, jsonb_array_length(steps) AS step_count
--    FROM drip_sequences
--    WHERE tenant_id = 'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110'
--      AND name LIKE 'Adon Agent 1%';
--
-- 2. Inspect the steps:
--    SELECT step_index, step ->> 'channel' AS channel,
--           (step ->> 'delay_minutes')::int AS delay_min,
--           LEFT(COALESCE(step ->> 'body', step ->> 'body_text'), 80) AS body_preview
--    FROM drip_sequences,
--         jsonb_array_elements(steps) WITH ORDINALITY AS s(step, step_index)
--    WHERE id = 'a4d1a5c2-1111-5811-1111-c87a83d40078'
--    ORDER BY step_index;
--
-- 3. Before enabling: confirm no duplicate Inquiry Welcomer exists:
--    SELECT id, name, enabled FROM drip_sequences
--    WHERE tenant_id = 'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110'
--      AND trigger_event = 'BRAVO_RECORD_STATUS_CHANGED'
--      AND (trigger_filter->>'to') = 'hot_lead';
