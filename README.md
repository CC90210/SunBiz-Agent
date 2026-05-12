# Sun Biz Agent

Sun Biz Agent is the client operations agent for Sun Biz Funding. It connects the
shared OASIS Agent Command Center to a dedicated funding-ops backend so the
client can run leads, contacts, applications, offers, funded deals, renewals,
commissions, SMS, email blasts, lenders, templates, team access, and embedded
forms from one AI-powered command surface.

## What This Repo Owns

- Backend agent identity and operating instructions for Sun Biz Funding.
- Local SMS engine in `scripts/sms_engine.py` with Twilio Phase 1 support.
- Dashboard integration contract in `dashboard/`.
- Event names emitted into the OASIS V6 event bus, including `SUNBIZ_SMS_SENT`,
  `SUNBIZ_DEAL_FUNDED`, `SUNBIZ_RENEWAL_DUE`, and `SUNBIZ_COMMISSION_BOOKED`.
- The client-side file structure that will be installed on or connected to the
  client's machine when the hosted/local bridge is wired.

## Command Center Relationship

Sun Biz is a separate client profile, not CC's OASIS profile.

- CC/OASIS keeps its own tenant, dashboard, agents, and business data.
- Sun Biz gets its own tenant/profile and the `sun` Command Center profile.
- Sun business data is Turso/libSQL-first for client isolation.
- Shared OASIS infrastructure still provides the shell, auth rails, event bus,
  onboarding flow, and deployment patterns.

When a Command Center account is provisioned with brand `Sun Biz Funding`, the
dashboard tags that tenant with:

```json
{
  "command_center_profile_slug": "sun",
  "data_backend": "turso",
  "deployment_mode": "dedicated"
}
```

That is what makes a Sun login render the Sun Biz navigation and agent context
instead of CC's internal OASIS dashboard.

## Current File Structure

```text
dashboard/
  tenant.manifest.json   # Brand, profile, event, and transport contract
  INTEGRATION.md         # Dashboard/agent interface notes
scripts/
  sms_engine.py          # Local Phase 1 SMS engine
brain/
  SOUL.md                # Agent identity, mission, and operating values
  CAPABILITIES.md        # Capability registry
  CHANGELOG.md           # Agent change history
.agents/workflows/
  health.md              # Health workflow
  prime.md               # Prime workflow
```

## Demo Flow

The Agent Command Center can show a safe Sun Biz demo before the real client
account is created.

1. CC logs into the Command Center.
2. CC opens `/demo/sun`.
3. The shell switches into Sun Biz demo mode with sample leads, renewals, and
   SMS history.
4. The sidebar shows a demo banner with an exit link.

This demo mode does not mutate CC's profile and does not show CC tenant data.
Live SMS sends stay disabled until the hosted Sun Biz backend is connected.

## Production Onboarding Flow

1. Create or invite the Sun Biz operator account in the Agent Command Center.
2. Use brand `Sun Biz Funding` so the tenant is tagged with the Sun profile.
3. Provision the Turso client database from the Sun Biz template.
4. Set dashboard env vars:
   - `SUNBIZ_AGENT_API_URL`
   - `SUNBIZ_AGENT_HMAC_SECRET`
5. Start the hosted Sun Biz agent service.
6. Connect client credentials: Twilio, Gmail/SMTP, JotForm webhook, and any
   lender data sources.
7. Confirm `/health`, `/status`, and the first heartbeat/event are visible.

## Hosted Agent Contract

The hosted Sun Biz backend should expose:

```text
GET  /health
GET  /status
POST /sms/send
POST /webhook/jotform
```

SMS requests are sent from the Command Center with:

```json
{
  "to": "+14165551212",
  "body": "Message body",
  "tenant_slug": "sun",
  "client_profile": "sun"
}
```

If `SUNBIZ_AGENT_HMAC_SECRET` is configured, the dashboard signs requests with:

```text
x-oasis-timestamp
x-oasis-signature
x-oasis-tenant-slug
x-oasis-client-profile
```

The signature is `HMAC-SHA256("{timestamp}.{raw_json_body}")`.

## Status

- Shared Command Center profile: shipped.
- Sun sidebar/navigation: shipped.
- Demo data mode: shipped in Command Center.
- Local SMS engine: shipped.
- Hosted FastAPI service: pending.
- Turso schema and adapter: pending.
- Full Google OAuth to tenant provisioning to local bridge onboarding: pending.
