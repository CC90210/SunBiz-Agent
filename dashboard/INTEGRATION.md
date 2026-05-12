# Sun Biz Agent Dashboard Integration

This folder is the contract between the Sun Biz Agent repo and the shared Agent Command Center.

## Current architecture

- Sun Biz Agent is a separate client product, not a permanent row-level tenant inside CC's internal ops app.
- Client operational data is Turso/libSQL-first.
- The shared Agent Command Center may still render the Sun profile/sidebar shell while the dedicated runtime comes online.
- Shared infra can stay in Business-Empire-Agent where it adds leverage: V6 state sync, event bus registration, dashboard chrome, and onboarding rails.

## Command Center contract

- Profile id: `sun`
- Tenant slug: `sun`
- Brand: `Sun Biz Funding`
- Subtitle: `Operations Command`
- Data backend: `turso`
- SMS transport: hosted agent first, local script fallback only in non-production dev

## Dashboard env vars

Set these on the command-center deployment that will call the Sun Biz backend:

- `SUNBIZ_AGENT_API_URL`
- `SUNBIZ_AGENT_HMAC_SECRET`

The shared command center now reads these through `apps/command-center/lib/client-profiles.ts` and `apps/command-center/lib/client-agent.ts`.

## Hosted agent endpoints

The Sun Biz backend should expose:

- `POST /sms/send`
- `GET /health`
- `GET /status`
- `POST /webhook/jotform`

The dashboard already sends `tenant_slug` and `client_profile` with hosted SMS requests. If `SUNBIZ_AGENT_HMAC_SECRET` is present, it also sends:

- `x-oasis-timestamp`
- `x-oasis-signature`
- `x-oasis-tenant-slug`
- `x-oasis-client-profile`

Signature format:

- HMAC-SHA256 over `{timestamp}.{raw_json_body}`

## Next implementation steps

1. Stand up the hosted Sun Biz agent runtime and wire `SUNBIZ_AGENT_API_URL`.
2. Replace the temporary shared-shell Supabase fallback readers with a Turso/libSQL adapter for Sun business data.
3. Add onboarding scripts in this repo for Turso provisioning, credential wiring, and health checks.
4. Push to `CC90210/SunBiz-Agent` only after CC approves the remote state and deployment target.
