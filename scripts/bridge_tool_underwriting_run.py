"""bridge_tool_underwriting_run.py — SunBiz underwriting bridge-tool body.

The OASIS local bridge daemon (CEO-Agent/bravo_cli/bridge_chat_server.py)
registers `underwriting_run` as a callable tool. The bridge ITSELF is
shared infra used by every agent (Bravo, Solara, Helios). The
underwriting domain knowledge — table names, daemon contract, polling
loop, dual-write to data.underwriting_jsonb — is SunBiz-specific and
lives HERE so the boundary is explicit.

The bridge file `bravo_cli/bridge_tools.py:_tool_underwriting_run` is a
thin shim that imports `underwriting_run` from this module and forwards
the payload. The shim adds `SunBiz-Agent/scripts/` to sys.path at call
time, controlled by env var `SUNBIZ_AGENT_ROOT` (defaults to
`~/SunBiz-Agent`).

Behaviour (unchanged from the 2026-05-28 rewrite that unified on the
application_underwriting table):
  1. Verify application_id resolves to a real tenant_records row.
  2. 409-guard against double-enqueue when a pending/parsing row exists.
  3. INSERT into application_underwriting at status='pending'.
  4. Poll the row until status='complete' or 'error', or timeout.
  5. On complete: dual-write data.underwriting_jsonb so legacy consumers
     (/api/applications/[id]/match-lenders, ApplicationCardActions.tsx)
     keep working.

The underwriting_orchestrator.py daemon (also in SunBiz-Agent/scripts/)
is the worker that flips pending→parsing→complete. This tool only
enqueues and polls.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def underwriting_run(
    payload: dict,
    _ok: Callable[[str], dict],
    _err: Callable[[str], dict],
) -> dict:
    """Bridge-tool body. The bridge daemon passes its own _ok/_err helpers
    so result framing matches the rest of the tool surface."""
    application_id = str(payload.get("application_id") or "").strip()
    triggered_by = str(payload.get("triggered_by") or "manual").strip()
    wait_for_complete = bool(payload.get("wait_for_complete", True))
    poll_interval_s = max(1, min(int(payload.get("poll_interval_s") or 5), 60))
    poll_timeout_s = max(60, min(int(payload.get("poll_timeout_s") or 1800), 3600))
    if not application_id:
        return _err("missing 'application_id'")
    if triggered_by not in {"manual", "rerun", "chat", "automatic"}:
        triggered_by = "manual"

    # Resolve CEO-Agent runtime root via the shared bootstrap helper.
    # bootstrap_bravo_path also adds CEO-Agent/scripts/ to sys.path so
    # the cross-repo import below resolves.
    sunbiz_scripts = str(Path(__file__).resolve().parent)
    if sunbiz_scripts not in sys.path:
        sys.path.insert(0, sunbiz_scripts)
    from _bravo_bootstrap import bootstrap_bravo_path  # type: ignore
    bravo_root = bootstrap_bravo_path()
    if bravo_root is None:
        return _err(
            "CEO-Agent runtime not found. Set BRAVO_AGENT_ROOT or clone "
            "CEO-Agent at ~/CEO-Agent (Mac/Linux) or "
            "C:\\Users\\User\\Business-Empire-Agent (Windows)."
        )
    try:
        from supabase import create_client  # type: ignore
    except ImportError:
        return _err("supabase python client not installed in bridge env")
    try:
        from lib.secret_loader import load_env  # type: ignore
        env = load_env([
            "BRAVO_SUPABASE_URL",
            "BRAVO_SUPABASE_SERVICE_ROLE_KEY",
        ])
        sb = create_client(env["BRAVO_SUPABASE_URL"], env["BRAVO_SUPABASE_SERVICE_ROLE_KEY"])
    except Exception as e:
        return _err(f"supabase init failed: {e}")

    app_row = (
        sb.table("tenant_records")
        .select("id, tenant_id, data")
        .eq("id", application_id)
        .eq("entity_type", "application")
        .maybeSingle()
        .execute()
    )
    if not app_row.data:
        return _err(f"application_id {application_id} not found in tenant_records")
    tenant_id = app_row.data.get("tenant_id")
    if not tenant_id:
        return _err(f"application {application_id} has no tenant_id — corrupt row")

    in_flight = (
        sb.table("application_underwriting")
        .select("id, status, run_at")
        .eq("tenant_id", tenant_id)
        .eq("application_id", application_id)
        .in_("status", ["pending", "parsing"])
        .limit(1)
        .maybeSingle()
        .execute()
    )
    if in_flight.data:
        existing_run_id = in_flight.data["id"]
        if not wait_for_complete:
            return _ok(json.dumps({
                "ok": True,
                "run_id": existing_run_id,
                "application_id": application_id,
                "enqueued": False,
                "reused_existing": True,
                "status": in_flight.data["status"],
            }))
        run_id = existing_run_id
    else:
        ins = (
            sb.table("application_underwriting")
            .insert({
                "tenant_id": tenant_id,
                "application_id": application_id,
                "status": "pending",
                "triggered_by": triggered_by,
                "run_at": datetime.now(timezone.utc).isoformat(),
            })
            .execute()
        )
        if not ins.data or not ins.data[0].get("id"):
            return _err(f"failed to enqueue underwriting run: {getattr(ins, 'error', 'unknown')}")
        run_id = ins.data[0]["id"]

    if not wait_for_complete:
        return _ok(json.dumps({
            "ok": True,
            "run_id": run_id,
            "application_id": application_id,
            "enqueued": True,
            "status": "pending",
            "message": "Run enqueued. Check application_underwriting/latest for results.",
        }))

    start = time.time()
    last_status = "pending"
    while time.time() - start < poll_timeout_s:
        time.sleep(poll_interval_s)
        try:
            row = (
                sb.table("application_underwriting")
                .select(
                    "id, status, run_at, readiness_score, risk_flags, sales_angle, "
                    "avg_monthly_revenue, avg_daily_balance, nsf_count, "
                    "deposit_consistency_pct, debt_service_monthly, "
                    "debt_to_revenue_ratio, lender_count, error_message"
                )
                .eq("id", run_id)
                .maybeSingle()
                .execute()
            )
        except Exception:
            continue
        if not row.data:
            return _err(f"underwriting row {run_id} disappeared mid-poll — DB inconsistency")
        last_status = row.data.get("status") or last_status
        if last_status == "complete":
            risk_flags = row.data.get("risk_flags") or []
            sales_angle = row.data.get("sales_angle") or ""
            # Best-effort dual-write into application.data.underwriting_jsonb
            # so legacy consumers (/api/applications/[id]/match-lenders,
            # ApplicationCardActions display, /api/applications/[id]/underwrite)
            # keep working. Once underwriting_orchestrator.py does this itself
            # the block becomes idempotent overlap.
            try:
                legacy_jsonb = {
                    "monthly_revenue": row.data.get("avg_monthly_revenue"),
                    "monthly_debt_service": row.data.get("debt_service_monthly"),
                    "loan_count": row.data.get("lender_count"),
                    "nsf_events_90d": row.data.get("nsf_count"),
                    "lenders_identified": [],
                    "sales_angle": sales_angle,
                    "generated_at": row.data.get("run_at"),
                }
                app_now = (
                    sb.table("tenant_records")
                    .select("data")
                    .eq("id", application_id)
                    .eq("tenant_id", tenant_id)
                    .maybeSingle()
                    .execute()
                )
                current_data = (app_now.data or {}).get("data") or {}
                merged = {**current_data, "underwriting_jsonb": legacy_jsonb}
                sb.table("tenant_records").update({
                    "data": merged,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", application_id).eq("tenant_id", tenant_id).execute()
            except Exception:
                pass
            return _ok(json.dumps({
                "ok": True,
                "run_id": run_id,
                "application_id": application_id,
                "status": "complete",
                "readiness_score": row.data.get("readiness_score"),
                "risk_flags": risk_flags,
                "risk_flag_count": len(risk_flags) if isinstance(risk_flags, list) else 0,
                "avg_monthly_revenue": row.data.get("avg_monthly_revenue"),
                "avg_daily_balance": row.data.get("avg_daily_balance"),
                "nsf_count": row.data.get("nsf_count"),
                "deposit_consistency_pct": row.data.get("deposit_consistency_pct"),
                "debt_service_monthly": row.data.get("debt_service_monthly"),
                "debt_to_revenue_ratio": row.data.get("debt_to_revenue_ratio"),
                "lender_count": row.data.get("lender_count"),
                "sales_angle_len": len(sales_angle),
                "sales_angle_preview": sales_angle[:400],
                "elapsed_s": int(time.time() - start),
            }))
        if last_status == "error":
            return _err(
                f"underwriting failed: {row.data.get('error_message') or 'unknown error'} "
                f"(run_id={run_id})"
            )

    return _err(
        f"underwriting timed out after {poll_timeout_s}s while waiting for daemon "
        f"(last_status={last_status}, run_id={run_id}). "
        "Check that underwriting_orchestrator.py is running on the bridge VPS. "
        "The run is still enqueued — re-fetch /api/applications/{id}/underwriting/latest later."
    )
