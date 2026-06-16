-- Migration 080 — Inquiry Welcomer: rename + de-hardcode the agent name
--
-- Follows up 078 (Adon Agent 1 — Inquiry Welcomer). Two changes CC asked for
-- (2026-06-16):
--   1. RENAME "Adon Agent 1 — Inquiry Welcomer" -> "Inquiry Welcomer". The
--      "Adon Agent 1" label confused operators on /sequences; the sequence is
--      just the interest->application welcome drip. (Adon authored the template;
--      that lineage lives in this migration history, not the operator UI.)
--   2. DE-HARDCODE the signer: every "Ezra" in the copy becomes
--      {{lead.assigned_agent_name}}, so a lead routed to Jordan signs "Jordan",
--      Alex signs "Alex", etc. The dashboard now stamps lead.data.assigned_agent_name
--      on every interest-form lead (per-agent ?rep routing), and sequence_runner
--      _build_context spreads lead.data into the drip context, so the token
--      resolves with no runner change.
--
-- ALSO NOW WIRED (the 078 activation blocker): {{lead.application_url}}. The
-- dashboard mints a per-lead FULL application form link on interest-lead
-- creation and stores it on lead.data.application_url (commit 9581e4d). The
-- placeholder in the copy now resolves to a real link.
--
-- STILL DISABLED (enabled=false) — intentional. Before flipping enabled=true
-- via /sequences, the operator MUST:
--   1. Confirm a "full-application" form exists + is enabled for the SunBiz
--      tenant (so application_url mints a real link; otherwise it's unset and
--      the touch ships without a link). Create it from the Forms tab if missing.
--   2. Confirm the SunBiz CASL business_address in send_gateway BRAND_IDENTITY
--      is non-placeholder for brand="sunbiz".
--   3. Send yourself a test: create a test lead at stage=hot_lead with
--      assigned_agent_name + application_url set, confirm the SMS + email
--      render the agent's name + a working link, THEN enable.
--
-- Apply via: python scripts/apply_migration.py database/080_inquiry_welcomer_dehardcode.sql
-- Enable via: the /sequences UI (toggle), or a one-line UPDATE ... SET enabled=true.

BEGIN;

DO $$
DECLARE
    sunbiz_tenant uuid := 'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110';
    template_uuid uuid := 'a4d1a5c2-1111-5811-1111-c87a83d40078';
    existing_id   uuid;
BEGIN
    -- Find the Inquiry Welcomer (deterministic UUID first, then logical key —
    -- covers the case where the operator authored it via /sequences instead of 078).
    SELECT id INTO existing_id
    FROM public.drip_sequences
    WHERE tenant_id = sunbiz_tenant
      AND (id = template_uuid
           OR name ILIKE '%Inquiry Welcomer%'
           OR name ILIKE '%Adon Agent 1%')
    LIMIT 1;

    IF existing_id IS NULL THEN
        RAISE NOTICE 'No Inquiry Welcomer found for SunBiz — run 078 first. Skipping.';
        RETURN;
    END IF;

    UPDATE public.drip_sequences
    SET
        name = 'Inquiry Welcomer',
        description = 'Interest -> application welcome drip. Fires when a lead enters hot_lead '
            || '(interest form submitted). 5 touches over 72h alternating SMS/email, each carrying '
            || 'the per-lead full-application link ({{lead.application_url}}) and signed by the '
            || 'assigned agent ({{lead.assigned_agent_name}}). Stop conditions enforced by '
            || 'send_gateway gates. Enable via /sequences after a test send.',
        steps = jsonb_build_array(
            -- Touch 1: SMS welcome (now)
            jsonb_build_object(
                'channel', 'sms',
                'delay_minutes', 0,
                'body', 'Hi {{lead.first_name}}, {{lead.assigned_agent_name}} at SunBiz Funding — got your inquiry on funding for {{lead.company}}. Apply here: {{lead.application_url}} — takes 5 min. Reply STOP to opt out.',
                'from_label', 'SunBiz Funding'
            ),
            -- Touch 2: Email welcome (now, simultaneous). body_html REQUIRED for commercial sends.
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
                    || 'To get an offer back fast, alongside the application it helps to include:'
                    || E'\n'
                    || '  - Last 3 months of business bank statements (required)'
                    || E'\n'
                    || '  - Optional: a clear photo of your driver''s license + a voided check'
                    || E'\n\n'
                    || 'Most deals get an offer back inside 24 hours once we have your statements. Reply with questions or upload directly via the application form.'
                    || E'\n\n'
                    || '— {{lead.assigned_agent_name}}'
                    || E'\n'
                    || 'SunBiz Funding'
                    || E'\n'
                    || 'submissions@sunbizfunding.com',
                'body_html', '<p>Hi {{lead.first_name}},</p>'
                    || '<p>Got your inquiry on funding for <strong>{{lead.company}}</strong>. Application takes 5 minutes:</p>'
                    || '<p><a href="{{lead.application_url}}" style="background:#1F7A56;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;">Start application</a></p>'
                    || '<p>To get an offer back fast, alongside the application it helps to include:</p>'
                    || '<ul>'
                    || '<li>Last 3 months of business bank statements (required)</li>'
                    || '<li>Optional: a clear photo of your driver''s license + a voided check</li>'
                    || '</ul>'
                    || '<p>Most deals get an offer back inside 24 hours once we have your statements. Reply with questions or upload directly via the application form.</p>'
                    || '<p>&mdash; {{lead.assigned_agent_name}}<br>SunBiz Funding<br><a href="mailto:submissions@sunbizfunding.com">submissions@sunbizfunding.com</a></p>',
                'from_label', '{{lead.assigned_agent_name}} at SunBiz Funding'
            ),
            -- Touch 3: SMS nudge at hour 3
            jsonb_build_object(
                'channel', 'sms',
                'delay_minutes', 180,
                'body', 'Hi {{lead.first_name}}, {{lead.assigned_agent_name}} at SunBiz — just checking the application link landed OK. Anything blocking you from getting started today?',
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
                    || '— {{lead.assigned_agent_name}}'
                    || E'\n'
                    || 'SunBiz Funding',
                'body_html', '<p>Hi {{lead.first_name}},</p>'
                    || '<p>Saw the application went out yesterday &mdash; wanted to check if you had any questions.</p>'
                    || '<p>The fastest path: <a href="{{lead.application_url}}">complete the application</a> + send 3 months of bank statements and I''ll have something concrete back to you tomorrow.</p>'
                    || '<p>If timing isn''t right this week, just say the word and I''ll loop back in 30 days.</p>'
                    || '<p>&mdash; {{lead.assigned_agent_name}}<br>SunBiz Funding</p>',
                'from_label', '{{lead.assigned_agent_name}} at SunBiz Funding'
            ),
            -- Touch 5: Final SMS at hour 72
            jsonb_build_object(
                'channel', 'sms',
                'delay_minutes', 4320,
                'body', 'Hi {{lead.first_name}}, last check-in from my side — is funding for {{lead.company}} still on the table this month? If not, no worries, just let me know and I''ll loop back next quarter.',
                'from_label', 'SunBiz Funding'
            )
        )
    WHERE id = existing_id;

    RAISE NOTICE 'Inquiry Welcomer updated (id=%): renamed + de-hardcoded to {{lead.assigned_agent_name}}. Still DISABLED — enable via /sequences after a test send.', existing_id;
END $$;

COMMIT;

-- Verify:
--   SELECT id, name, enabled FROM drip_sequences
--   WHERE tenant_id = 'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110' AND name = 'Inquiry Welcomer';
--   SELECT step ->> 'channel', LEFT(COALESCE(step->>'body', step->>'body_text'), 90)
--   FROM drip_sequences, jsonb_array_elements(steps) AS s(step)
--   WHERE name = 'Inquiry Welcomer' AND tenant_id = 'aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110';
