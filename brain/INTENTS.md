---
name: INTENTS
description: Verb-by-verb playbook for Solara's most common funding-shop actions.
mutability: SEMI-MUTABLE
tags: [brain, agent-only, playbook]
last_updated: 2026-05-25
---

# INTENTS — Verb-by-Verb Playbook (SunBiz V6.x)

> Reached from `brain/AGENT_ROUTER.md` when an intent needs more than a one-line answer.
> Each playbook: trigger → preconditions → action → verification.

---

## "Enroll [lead] in drip sequence"

**Trigger:** "Start the drip for [merchant]" / "Enroll [lead ID] in follow-up sequence" / "Add [merchant] to nurture."

**Preconditions:**
1. Lead exists in `leads` table. Run: `python scripts/supabase_tool.py select leads --eq '{"id":"<lead_id>"}' --limit 1`
2. Merchant has valid opt-in state. Check `opted_in` field in the lead row. If NULL or false → STOP. Cannot enroll without consent.
3. Sequence name is valid. Check `scripts/sequence_runner.py list-sequences` for available cadences.

**Action:**
1. Confirm sequence name and lead ID with Ezra (one turn: "Starting [sequence] for [merchant] — confirm?").
2. After yes: `python scripts/sequence_runner.py start --lead-id <id> --sequence <name>`
3. Log the event to `agent_traces` (Tier 1).
4. Post handoff to Helios: `python scripts/agent_inbox.py post --to helios --message "Drip started: lead <id>, sequence <name>. First touch in [N]h."`

**Verification:**
- `python scripts/sequence_runner.py status --lead-id <id>` → confirms sequence is active.
- First scheduled touch appears in Supabase `sequence_events` with status `pending`.

**Confirmation to Ezra:** "Enrolled [merchant] in [sequence]. First touch scheduled [datetime]. Helios notified."

---

## "Queue shop-out for [application]"

**Trigger:** "Shop this deal" / "Submit [deal ID] to lenders" / "Start the shop-out on [merchant]."

**Preconditions:**
1. Application exists and is complete. Run: `python scripts/deal_tracker.py list --deal-id <id> --json` — check `status=applied` and required docs present.
2. Pre-screen passes. Run: `python scripts/underwriting_orchestrator.py score --deal-id <id>` — review TAR band and stacking risk score.
3. Stacking risk is within threshold (position count ≤ lender tolerance). If score flags stacking risk → escalate to Ezra before proceeding.

**Action:**
1. Run underwriting score if not already done.
2. Present ranked lender list to Ezra: `python scripts/shop_out_sender.py plan --deal-id <id>` — shows recommended lenders, estimated approval probability, relationship cost.
3. Ezra confirms target lender(s) in same turn.
4. After confirmation: `python scripts/shop_out_sender.py send --deal-id <id> --lenders "<lender1>,<lender2>"`
5. Update deal state: `python scripts/deal_tracker.py update --deal-id <id> --status in_shop_out`
6. Log submission to `agent_traces`.

**Verification:**
- `python scripts/deal_tracker.py list --deal-id <id>` → status = `in_shop_out`.
- `python scripts/shop_out_sender.py status --deal-id <id>` → submission timestamp confirmed per lender.

**Confirmation to Ezra:** "Deal <id> submitted to [lenders] at [timestamp]. Expecting response within [lender's typical window]. Tracking."

---

## "Score [application] for shop-out"

**Trigger:** "Is this fundable?" / "Pre-screen [application]" / "What's the paper grade on [merchant]?" / "Score this deal."

**Preconditions:**
- Application data is present (revenue, TIB, position count, NSF count, industry).
- Deal ID exists in `applications` table.

**Action:**
1. `python scripts/underwriting_orchestrator.py score --deal-id <id> --json`
2. `python scripts/funding_intel.py tar-band --deal-id <id> --json`
3. Compose score summary:
   - TAR band (A/B/C/D)
   - Stacking risk (position count vs. lender tolerance)
   - Recommended lender tier
   - Confidence: HIGH/MEDIUM/LOW
   - Any red flags (NSF count, industry excluded by top lenders, leverage ratio)

**Verification:**
- Score output includes `confidence`, `tar_band`, `stacking_risk_flag`, `recommended_lenders[]`.

**Output to Ezra:**
```
Score: [TAR Band] | Stacking risk: [LOW/MEDIUM/HIGH — N positions]
Recommended: [Lender tier(s)]
Flags: [NSF count=X | Leverage=Y% | Industry=Z]
Confidence: [score]
Ready to shop: [YES / NO — reason if no]
```

---

## "Draft offer acceptance for [deal]"

**Trigger:** "Write up the offer for [merchant]" / "Format this offer" / "Merchant-facing offer summary for deal [ID]."

**Preconditions:**
1. Lender offer received and classified. Check `agent_traces` for `lender_response_classifier` event on this deal.
2. Offer terms are available: advance amount, factor rate, holdback %, payback period, ACH vs lockbox.

**Action:**
1. Pull offer terms: `python scripts/deal_tracker.py list --deal-id <id> --json` → `offers` array.
2. Spawn `offer-formatter` sub-agent: format terms into compliant merchant-facing language (no "loan," no factor rate % as a rate, daily payment + total payback framing).
3. Draft email via `follow_up_generator.py draft --lead-id <id> --context "offer_presented" --offer-id <offer_id>`.
4. Review draft for compliance (no banned language, no approval guarantees).
5. Surface draft to Ezra or route to Helios for delivery.

**Verification:**
- Draft reviewed for: no "loan" / "interest rate" / "guaranteed approval."
- Daily payment amount and total payback amount are explicit.
- Handoff to Helios logged in `agent_inbox`.

**Confirmation to Ezra:** "Offer draft ready for deal <id>. [View draft inline]. Route to Helios to send, or review first?"

---

## "Kick off renewal conversation for [merchant]"

**Trigger:** "Start renewal for [merchant]" / "Renewal outreach for deal [ID]" / "[merchant] is in window — let's go."

**Preconditions:**
1. Deal is in renewal window: `python scripts/renewal_reminder.py --window 30 --json` confirms this merchant.
2. Merchant's opt-in state is valid (check `leads` table).
3. Original deal terms on file (advance amount, factor rate, payback date).

**Action:**
1. Generate renewal proposal parameters: `python scripts/funding_intel.py renewal-estimate --deal-id <id>` (estimates renewal amount based on remaining balance + typical renewal terms).
2. Draft renewal outreach: `python scripts/follow_up_generator.py draft --lead-id <id> --context "renewal"`.
3. Confirm draft with Ezra or route to Helios.
4. After approval: `python scripts/send_gateway.py send --channel email --template renewal_v1 --lead-id <id>` (send_gateway enforces TCPA/CASL).
5. Update deal state: `python scripts/deal_tracker.py update --deal-id <id> --status renewal_outreach_sent`.

**Verification:**
- `send_gateway.py` returns send confirmation (message ID, timestamp).
- Deal status updated to `renewal_outreach_sent`.

**Confirmation to Ezra:** "Renewal outreach sent to [merchant] for deal <id>. Estimated renewal: $[amount]. Following up in [N] days if no response."

---

## "Escalate stuck deal to Ezra"

**Trigger:** "This deal is stuck" / "I can't move deal [ID] forward" / shop-out with no lender response >72h / all lenders declined.

**Preconditions:**
- Deal ID is confirmed in Supabase.
- At least one of these is true: (a) no lender response in >72h, (b) all lenders declined, (c) stacking risk threshold exceeded before submission.

**Action:**
1. Pull full deal context: `python scripts/deal_tracker.py list --deal-id <id> --json`
2. Pull submission history and lender responses from `agent_traces`.
3. If all declined: spawn `decline-analyst` sub-agent to generate root cause analysis.
4. Compose escalation summary for Ezra:
   - Deal ID + merchant name
   - Current status + how long stuck
   - Actions already taken (which lenders contacted, when, what response)
   - Decline analysis (if applicable)
   - 2-3 recommended next actions (re-shop with updated docs / different lender tier / merchant not fundable now)
5. Surface to Ezra with explicit ask: "Do you want Solara to [recommended action A] or [recommended action B]?"

**Verification:**
- Escalation summary is complete (no missing fields).
- Ezra has enough information to make a decision without asking follow-up questions.

**Confirmation:** "Escalation surfaced to Ezra. Waiting on direction before taking further action on deal <id>."

---

## "Apply database migration"

**Trigger:** "Apply migration [N]" / "Run this SQL."

1. Confirm migration file exists at `database/<NNN>_<name>.sql`.
2. Surface the migration content to Ezra for review before running.
3. After Ezra confirms: `python scripts/apply_migration.py database/<NNN>_<name>.sql`.
4. Gate on dangerous patterns (`DROP TABLE`, `TRUNCATE`, naked `DELETE`). If gated, surface the reason.
5. Verify post-apply: `python scripts/supabase_tool.py select <new_table> --limit 1`.
6. Log in `brain/CHANGELOG.md`.

---

## "Find / search / look up"

1. **Code or files:** use Read tool starting from `brain/AGENT_ROUTER.md` index.
2. **Database:** `python scripts/supabase_tool.py select <table> --eq '{"tenant_id":"sunbiz","<field>":"<value>"}' --limit N`
3. **Memory / past sessions:** read `memory/SESSION_LOG.md` (recent) or `memory/ARCHIVES/` (older).
4. **Lender patterns:** `memory/PATTERNS.md` + `memory/LONG_TERM.md`.
