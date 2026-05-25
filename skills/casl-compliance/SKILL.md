---
name: casl-compliance
description: Mandatory compliance gate before any outbound (email, SMS, blast). Verifies consent, opt-out status, CASL footer, send window, and daily cap.
triggers:
  - "casl check"
  - "compliance check before send"
  - "is this CASL compliant"
  - "check opt-out"
  - "can we send this"
tier: stable
disable_model_invocation: false
requires:
  - env:SUNBIZ_SUPABASE_URL
  - env:SUNBIZ_SUPABASE_ANON_KEY
---

# CASL Compliance

## Purpose

Canada's Anti-Spam Legislation (CASL) applies to every commercial electronic message sent to a Canadian recipient. Non-compliance carries fines up to $10 million per violation for organizations. This skill is the mandatory gate before ANY outbound — no exceptions.

**All sends route through `scripts/integrations/send_gateway.py`. This skill provides the pre-flight checklist that runs before the gateway is invoked.**

## CASL Basics

| Concept | Rule |
|---------|------|
| Express consent | Recipient explicitly opted in to receive messages from SunBiz Funding |
| Implied consent | Existing business relationship (client, prospect who inquired) — valid for 2 years from last interaction |
| No consent | Cold contact to a business email found via UCC list, LinkedIn, etc. — requires implied consent exemption only if the email is publicly listed for commercial contact |
| Opt-out | If recipient unsubscribed, they cannot receive ANY commercial message, even under implied consent |

## Pre-Send Checklist

Run all five checks. If ANY fails, stop and surface to Ezra — do not send.

### Check 1 — Consent status

```
GET /api/compliance/consent?recipient_email=[email]
```

- `status: express` → proceed
- `status: implied` → verify `consent_expires_at` > today; if expired, do not send
- `status: none` → only proceed if the email is publicly listed for commercial contact on the recipient's own website/LinkedIn AND the message is relevant to their stated business purpose
- `status: opted_out` → **HARD STOP. Never send.**

### Check 2 — Opt-out list scrub

```
GET /api/compliance/opt-out-check?email=[email]
```

This is separate from the consent table — it's the global suppression list. If `suppressed: true`, do not send regardless of consent status.

### Check 3 — CASL footer in message

Every commercial email must contain:
1. **Sender identification**: "SunBiz Funding, [physical address]"
2. **Unsubscribe mechanism**: A working one-click unsubscribe link
3. **Footer language**: "You're receiving this because [consent reason]. To unsubscribe, click here."

Check that the template includes all three. If any are missing, refuse to queue until the template is fixed.

### Check 4 — Send window

Canadian business recipients:
- Acceptable window: **Monday–Friday, 9:00am–6:00pm recipient's local time**
- Never send on statutory Canadian holidays
- Never send on weekends (even if technically legal — it reads as spam)

Current statutory holidays to check:
- New Year's Day, Family Day (ON), Good Friday, Victoria Day, Canada Day, Civic Holiday (ON), Labour Day, Thanksgiving, Remembrance Day, Christmas Day, Boxing Day

If the current time is outside the window, schedule for the next business day opening — do not force-send.

### Check 5 — Daily send cap

```
GET /api/compliance/daily-send-stats?date=today
```

Check `emails_sent_today` against the configured `daily_cap` (default: 100 per sending domain, 50 per individual campaign).

If cap is reached: do not send today. Queue for tomorrow.

## For SMS / Text Messages

Additional requirements for SMS:
- Express consent required (implied consent does not cover SMS in Canada)
- Must include "Reply STOP to unsubscribe" in every message
- No promotional SMS before 9am or after 9pm recipient local time
- Character limit per message: 160 chars (split if longer, each part must be CASL-compliant)

Check `scripts/integrations/send_gateway.py` for the SMS compliance wrapper — it handles the STOP keyword listener automatically.

## Handling Opt-Out Requests

When a recipient replies "unsubscribe," "stop," "remove me," or similar:

1. Log immediately to the global suppression list:
   ```
   POST /api/compliance/opt-out
   { "email": "[email]", "source": "email_reply", "opted_out_at": "[timestamp]" }
   ```
2. Confirm to the recipient within 10 business days (automated via send_gateway)
3. Never contact them again — not even for transactional messages unless they re-consent

**There is no grace period on opt-outs. Honor immediately.**

## Guardrails

- NEVER bypass this skill because a campaign is "just B2B" or "just one email" — CASL applies regardless of audience size.
- NEVER route around `send_gateway.py` — it's the single enforcement point for all outbound compliance logging.
- If Ezra says "just send it, it's fine" — surface the specific compliance risk and ask again with context. If Ezra still overrides, log the override decision in `memory/DECISIONS.md` and send only if you are confident the legal risk is Ezra's explicit call to make.

## Related Skills

- [[skills/cold-outreach-blast/SKILL.md]] — calls this skill as Step 3
- [[skills/email-outbound/SKILL.md]] — calls this skill before individual sends
- [[skills/renewal-window-detection/SKILL.md]] — renewal outreach also requires compliance check
- [[skills/operator-handoff/SKILL.md]] — escalate compliance ambiguity to Ezra
