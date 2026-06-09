"""sunbiz_constants.py — single source of truth for SunBiz tenant identity.

The SunBiz tenant_id UUID was previously hardcoded as a string literal in
6+ files (backfill_sunbiz_stages, core/cron_registry, import_mca_leads,
populate_sunbiz_lender_catalog, sentinel, sequence_runner with the variant
name SUNBIZ_TENANT — inconsistent). Consolidated 2026-06-08 because:
  - If the UUID ever changed (multi-tenant migration, etc.), 6 places
    would need to be updated.
  - The inconsistent naming (SUNBIZ_TENANT vs SUNBIZ_TENANT_ID) made
    grep-based audits unreliable.
  - Future daemons that fire commercial sends need the brand-resolution
    helper too; this module is where it lives now.

Callers import:

    from sunbiz_constants import SUNBIZ_TENANT_ID, resolve_brand

    if record.tenant_id == SUNBIZ_TENANT_ID:
        # SunBiz-specific path

    brand = resolve_brand(record.tenant_id)   # "sunbiz" | "oasis"

Module-level constants only — no side effects, no I/O, no logging. Safe
to import from anywhere including hot paths.
"""

from __future__ import annotations

# Canonical SunBiz tenant UUID. Matches:
#   - tenants.id where slug='submissions' (database canonical)
#   - tenants.custom_fields.command_center_profile_slug='sun'
#   - the value used by every SunBiz pm2 daemon + the dashboard's
#     /t/sun/* tenant-scoped routes.
SUNBIZ_TENANT_ID: str = "aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110"


def resolve_brand(tenant_id: str | None) -> str:
    """Map a tenant_id to the send_gateway BRAND_IDENTITY key.

    Used by every daemon that calls send_gateway.send(brand=...). Keeping
    this in one place means a new tenant onboarding only touches THIS
    file — not every cold-outreach / sequence / blast script.

    Returns "sunbiz" for the SunBiz tenant, "oasis" for everything else
    (OASIS is the empire-default brand for owned-by-CC outbound).
    """
    return "sunbiz" if tenant_id == SUNBIZ_TENANT_ID else "oasis"
