# SUN BIZ AGENT - GEMINI CLI ENTRY POINT

> Fast layer for Sun Biz Agent. Use the real shipped runtime first: setup, doctor, hosted API, SMS, email, JotForm.

## Best used for
- quick repo-local health checks
- SMS status and diagnostics
- JotForm inspection
- email blast prep
- lightweight reporting

## Route to these tools
- `python scripts/doctor.py`
- `python scripts/api_server.py`
- `python scripts/sms_engine.py`
- `python scripts/email_blast.py`
- `python scripts/jotform_tracker.py`

## Rules
- Never hardcode secrets; use `.env.agents`
- Do not present roadmap items as shipped
- Use "funding," "capital," or "advance" in customer-facing output
- Report failures clearly and stop looping

## Shipped now
- hosted API
- Twilio SMS
- Gmail outreach
- JotForm intake

## Not shipped yet
- failover SMS providers
- full deal-lifecycle ledger
- commission tables
- deeper Turso adapter
