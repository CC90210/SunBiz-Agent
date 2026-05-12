# Sun Biz Agent Dashboard Integration

This folder is the contract between the Sun Biz Agent repo and the shared Agent Command Center.

## Current architecture

- Sun Biz Agent is a separate client product, not a permanent row-level tenant inside CC's internal ops app.
- Client operational data is Turso/libSQL-first.
- The shared Agent Command Center renders the Sun profile/sidebar shell while the dedicated runtime lives in this repo.
- Shared infra can stay in Business-Empire-Agent where it adds leverage: V6 state sync, event bus registration, dashboard chrome, and onboarding rails.

## Command Center contract

- Profile id: `sun`
- Tenant slug: `sun`
- Brand: `Sun Biz Funding`
- Subtitle: `Operations Command`
- Data backend: `turso`
- SMS transport: hosted agent first, local script fallback only in non-production dev
- Hosted runtime entrypoint: `python scripts/api_server.py`
- Repo-local health check: `python scripts/doctor.py --deep`

## Dual-agent deployment

Sun Biz is intended to provision as a two-agent workspace:

- `sunbiz` / **Solara**: backend admin operations, deal lifecycle, renewals, commissions
- `suga_sean` / **Suga Sean**: text blasts, email outreach, reply handling, meeting-setting

The command center should keep `primary_agent="sunbiz"` so Solara anchors the record system, while `agents_enabled` includes both `sunbiz` and `suga_sean` so the operator can switch between them in the `/agent` view.

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

## Repo-local production commands

Run these inside the cloned SunBiz-Agent repo on the operator machine:

1. `python scripts/setup.py`
2. `python scripts/doctor.py --deep`
3. `python scripts/api_server.py`

## Next implementation steps

1. Replace the shared-shell fallback readers with a Turso/libSQL adapter for Sun business data.
2. Add Phase 2 SMS failover (Telnyx + Plivo) behind the existing `sms_engine.py` interface.
3. Add the deal-lifecycle ledger (`applications -> offers -> funded deals -> renewals`) so Solara's backend roadmap moves from contract to shipped code.
4. Keep the Sun Biz tenant manifest aligned with the two-agent model above.
