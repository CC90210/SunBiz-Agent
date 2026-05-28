"""sunbiz_guards.py — SunBiz-specific outbound-guard configuration.

The universal send_guards module (CEO-Agent/scripts/integrations/
send_guards.py) ships with no default quiet window — tenants opt in by
writing their window to tenants.custom_fields.quiet_window. This module
holds the SunBiz Funding window as a code-side constant so SunBiz daemons
can fall back when the DB lookup misses (fresh tenant row, network blip,
custom_fields cleared) and so the policy is visible in source review.

The window is intentionally wide enough to cover sundown variance plus a
buffer on both sides — Adon (SunBiz principal) does not want outbound to
merchants or lenders going out during the Shabbat observance.

  Friday  18:00 ET → Saturday 20:30 ET
"""

from __future__ import annotations

from typing import Any, Optional


SUNBIZ_QUIET_WINDOW: dict[str, Any] = {
    "tz": "America/New_York",
    "start_weekday": 4,   # 0=Mon, 4=Fri
    "start_hour": 18,
    "start_minute": 0,
    "end_weekday": 5,     # 5=Sat
    "end_hour": 20,
    "end_minute": 30,
}


def ensure_sunbiz_quiet_window(db: Any, tenant_id: str) -> bool:
    """Idempotent: write SUNBIZ_QUIET_WINDOW into tenants.custom_fields if
    that tenant row has no quiet_window configured yet. Returns True when
    a write happened, False when it was already set."""
    res = (
        db.table("tenants")
        .select("custom_fields")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    cf = (res.data or {}).get("custom_fields") or {}
    if isinstance(cf.get("quiet_window"), dict):
        return False
    cf["quiet_window"] = SUNBIZ_QUIET_WINDOW
    db.table("tenants").update({"custom_fields": cf}).eq("id", tenant_id).execute()
    return True


def apply_sunbiz_default_to_send_guards() -> Optional[dict[str, Any]]:
    """Optional: install the SunBiz window as the module-level default in
    the universal send_guards module. Call once at SunBiz daemon startup
    so any tenant without a DB-configured quiet_window still inherits the
    SunBiz observance. Returns the previous DEFAULT_QUIET_WINDOW so the
    caller can restore on shutdown if needed."""
    from send_guards import DEFAULT_QUIET_WINDOW  # type: ignore
    import send_guards  # type: ignore

    previous = DEFAULT_QUIET_WINDOW
    send_guards.DEFAULT_QUIET_WINDOW = SUNBIZ_QUIET_WINDOW
    return previous
