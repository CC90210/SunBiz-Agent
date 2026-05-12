# DECISIONS — Architectural Decision Log

---

### 2026-05-12 — Sun Biz deploys as a tandem workspace, not a single-agent shell
**Decision:** Treat Sun Biz as a two-agent deployment: `sunbiz` / Solara for backend admin operations and `suga_sean` / Suga Sean for outreach and meeting-setting.
**Reason:** The client workflow naturally splits into system-of-record ops and high-velocity outbound. Keeping both in one workspace preserves handoff speed without forcing one persona to own contradictory responsibilities.
**Implementation note:** Command center should keep `primary_agent="sunbiz"` while enabling both agents on the tenant profile.

### 2026-03-10 — Use Google Ads API (not Google Ad Manager)
**Decision:** Use Google Ads API for all campaign management
**Reason:** Google Ad Manager is for publishers (supply side). Google Ads API is for advertisers (demand side) — which is what we need for creating and managing ad campaigns.
**Alternatives:** Google Ad Manager API (rejected — wrong use case)

### 2026-03-10 — Meta Ads MCP: pipeboard-co/meta-ads-mcp
**Decision:** Use pipeboard-co/meta-ads-mcp as primary Meta MCP server
**Reason:** Most actively maintained (v1.0.20, Jan 2026), full campaign lifecycle support, works with Claude
**Alternatives:** brijr/meta-mcp (25 tools), amekala/ads-mcp (cross-platform, 100+ tools)
**Note:** May switch to amekala/ads-mcp if cross-platform unification is needed

### 2026-03-10 — Python SDK as Fallback Layer
**Decision:** Use google-ads and facebook-business Python SDKs as fallback when MCP fails
**Reason:** MCP servers can have bugs. Direct SDK gives us full API access as backup.
**Packages:** google-ads v29.2.0 (API v23.1), facebook-business v22.0 (Graph API v22.0)

### 2026-03-10 — Agent Architecture Inspired by Business Empire Agent
**Decision:** Mirror the Business Empire Agent's file structure (brain/memory/agents/skills/workflows)
**Reason:** Proven architecture with self-healing, self-improving capabilities. User is familiar with it.
**Adaptations:** Marketing-specific agents, skills, and workflows. Lending compliance built-in.
