"""underwriting_orchestrator.py — automatic underwriting daemon.

2026-05-25 second SunBiz product meeting expansion + migration 069.

Polls application_underwriting rows at status='pending', runs the
three-stage pipeline (parse → debt analysis → sales angle), and
persists the full output + computed metrics back to the same row.

Architecture:
  - One tick = one row claimed atomically via UPDATE...RETURNING
    (prevents double-claim if the daemon is restarted mid-run).
  - Each stage is a direct module import — no subprocess overhead, since
    all three submodules live in scripts/underwriting/ and are importable.
  - Metrics + risk flags are derived here from the two structured outputs,
    not inside the submodules, so the submodules stay single-responsibility.
  - Re-runs are append-only: the operator hits "Retry" on the dashboard
    which inserts a NEW pending row; this daemon never flips status back
    to 'pending' itself.

CLI:
  python scripts/underwriting_orchestrator.py once
  python scripts/underwriting_orchestrator.py loop --interval 30
  python scripts/underwriting_orchestrator.py tail
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent  # SunBiz-Agent root
STATE_DIR = REPO_ROOT / "state"
LOG_PATH = STATE_DIR / "underwriting_orchestrator.log"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

# CEO-Agent runtime probe — see _bravo_bootstrap.py. Adds
# CEO-Agent/scripts/ to sys.path so lib.secret_loader resolves.
# Local SunBiz submodules (underwriting/*) stay on REPO_ROOT path.
BRAVO_ROOT = bootstrap_bravo_path()

# How long a 'pending' row must sit before this daemon claims it.
# Gives the dashboard's INSERT time to commit and the operator a
# moment to cancel before processing starts.
PENDING_GRACE_SECONDS = 5

# Bucket prefix for Supabase Storage — mirrors shop_out_sender.py
STORAGE_BUCKET = "lead-documents"


# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────


def _log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    print(line.rstrip())


# ─────────────────────────────────────────────────────────────────────
# Supabase client — mirrors sequence_runner.py pattern
# ─────────────────────────────────────────────────────────────────────


def _supabase():
    """Service-role Supabase client. Returns None on any failure.
    lib.secret_loader lives in CEO-Agent/scripts/ (added to sys.path
    at module load via BRAVO_ROOT bootstrap)."""
    try:
        from lib.secret_loader import load_env  # type: ignore
    except Exception:
        return None
    try:
        env = load_env()
    except Exception:
        return None
    url = (env.get("BRAVO_SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client
    except ImportError:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# Submodule imports (lazy; adapted to whatever the modules expose)
# ─────────────────────────────────────────────────────────────────────


def _import_submodules() -> tuple[Any, Any, Any, Any, Any]:
    """Import the underwriting submodules.

    Returns (parse_statement, summarize_debt, generate_sales_angle,
             grade_deal, build_metric_card). All callables that raise on
    failure; the orchestrator wraps each in try/except so a single-module
    failure becomes status='error'.

    2026-06-11: added grader.py (Adon MCA SOP §6/§7 grading + metric card).
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

    from underwriting.statement_parser import parse_statement  # type: ignore
    from underwriting.debt_detector import summarize_debt      # type: ignore
    from underwriting.sales_angle import generate_sales_angle  # type: ignore
    from underwriting.grader import grade_deal, build_metric_card  # type: ignore

    return parse_statement, summarize_debt, generate_sales_angle, grade_deal, build_metric_card


# ─────────────────────────────────────────────────────────────────────
# Document classification heuristic
# ─────────────────────────────────────────────────────────────────────

# Positive tokens that mark a filename as a bank statement; negative tokens
# that mark it as a different KYC doc (so a mis-filed driver's license / void
# cheque never gets parsed as a statement). Used only as a FALLBACK when no
# canonically-typed (bank_statements_3mo / bank_statement) docs exist.
_STATEMENT_NAME_TOKENS = ("statement", "stmt", "checking", "savings", "bank")
_NON_STATEMENT_NAME_TOKENS = (
    "license", "licence", "driver", "void", "cheque", "check_", "id_card",
    "passport", "voidcheque", "dl_", "_dl", "ein", "articles",
)


def _looks_like_bank_statement(name: str) -> bool:
    """True when an UNCLASSIFIED filename looks like a bank statement.

    Filename-only heuristic (we never download to inspect here). Negative
    tokens win — a name that mentions a license/cheque is excluded even if it
    also contains a statement token.
    """
    n = (name or "").lower()
    if not n:
        return False
    if any(tok in n for tok in _NON_STATEMENT_NAME_TOKENS):
        return False
    return any(tok in n for tok in _STATEMENT_NAME_TOKENS)


# ─────────────────────────────────────────────────────────────────────
# Storage path resolution
# ─────────────────────────────────────────────────────────────────────


def _resolve_storage_path_to_local(sb, storage_path: str, tenant_id: str) -> Path | None:
    """Download a Supabase Storage file to a temp location.

    Returns a Path pointing to the local temp file, or None on failure.
    The caller is responsible for cleanup — underwriting runs are
    short-lived, so we leave the tmp/ dir as the system-level drain.
    """
    try:
        path = storage_path.replace("\\", "/").strip()
        if path.startswith(f"{STORAGE_BUCKET}/"):
            path = path[len(STORAGE_BUCKET) + 1:]
        parts = [p for p in path.split("/") if p]
        # Basic tenant isolation check — never cross tenant paths.
        if not parts or ".." in parts:
            _log(f"storage: unsafe path rejected: {storage_path!r}")
            return None
        normalized = "/".join(parts)
        data = sb.storage.from_(STORAGE_BUCKET).download(normalized)
    except Exception as exc:
        _log(f"storage: download failed {storage_path!r}: {exc}")
        return None

    if not isinstance(data, (bytes, bytearray)):
        return None

    tmp_dir = REPO_ROOT / "tmp" / "underwriting"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    # Name the file by the last two path segments to avoid collisions.
    safe_name = "_".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    local_path = tmp_dir / safe_name
    try:
        local_path.write_bytes(bytes(data))
    except OSError as exc:
        _log(f"storage: write to tmp failed: {exc}")
        return None
    return local_path


# ─────────────────────────────────────────────────────────────────────
# Metrics derivation
# ─────────────────────────────────────────────────────────────────────


def _derive_metrics(
    parser_outputs: list[dict],
    debt_analysis: dict,
) -> dict[str, Any]:
    """Compute the scalar metrics columns from the raw submodule outputs.

    All values are None-safe — missing keys in the submodule output
    produce None, which is the correct DB value (not zero).
    """
    statement_count = max(1, len(parser_outputs))

    # Average monthly revenue = avg of total_deposits across statements.
    revenue_values = [
        float(s.get("total_deposits") or 0) for s in parser_outputs if s.get("total_deposits")
    ]
    avg_monthly_revenue: float | None = (
        sum(revenue_values) / len(revenue_values) if revenue_values else None
    )

    # Average daily balance across statements.
    balance_values = [
        float(s.get("average_daily_balance") or 0)
        for s in parser_outputs
        if s.get("average_daily_balance") is not None
    ]
    avg_daily_balance: float | None = (
        sum(balance_values) / len(balance_values) if balance_values else None
    )

    # NSF count — sum across all statements in the window.
    nsf_count = int(debt_analysis.get("total_nsf_events") or 0)

    # Deposit consistency: fraction of months where deposit_count >= 5
    # (i.e. there was meaningful activity, not a single lump).
    deposit_counts = [s.get("deposit_count") for s in parser_outputs]
    active_months = sum(1 for d in deposit_counts if d is not None and int(d) >= 5)
    deposit_consistency_pct: float | None = (
        round(active_months / statement_count * 100, 2) if statement_count > 0 else None
    )

    debt_service_monthly: float | None = debt_analysis.get("monthly_debt_service")
    debt_to_revenue_ratio: float | None = debt_analysis.get("debt_to_revenue_ratio")
    lender_count: int = int(debt_analysis.get("lender_count") or 0)

    return {
        "avg_monthly_revenue": avg_monthly_revenue,
        "avg_daily_balance": avg_daily_balance,
        "nsf_count": nsf_count,
        "deposit_consistency_pct": deposit_consistency_pct,
        "debt_service_monthly": debt_service_monthly,
        "debt_to_revenue_ratio": debt_to_revenue_ratio,
        "lender_count": lender_count,
    }


# ─────────────────────────────────────────────────────────────────────
# Risk flags
# ─────────────────────────────────────────────────────────────────────


def _compute_risk_flags(
    metrics: dict[str, Any],
    parser_outputs: list[dict],
) -> list[str]:
    """Populate risk_flags from computed metrics per the scoring rubric.

    2026-05-25: five flag types defined at the meeting:
      stacked           — ≥2 active lenders in the stack
      declining_revenue — MoM revenue trend declining >5%
      high_nsf          — >3 NSF events in the 3-month window
      high_dsr          — debt_to_revenue_ratio > 0.30
      low_balance_buffer — avg_daily_balance < 10% of avg_monthly_revenue
    """
    flags: list[str] = []

    lender_count = metrics.get("lender_count") or 0
    if lender_count >= 2:
        flags.append("stacked")

    # Revenue trend: compare most recent month's deposits to earliest.
    # Only evaluate when at least 2 statements are present.
    revenue_by_month = [
        float(s.get("total_deposits") or 0)
        for s in parser_outputs
        if s.get("total_deposits") is not None
    ]
    if len(revenue_by_month) >= 2:
        earliest = revenue_by_month[0]
        latest = revenue_by_month[-1]
        if earliest > 0 and (earliest - latest) / earliest > 0.05:
            flags.append("declining_revenue")

    nsf_count = metrics.get("nsf_count") or 0
    if nsf_count > 3:
        flags.append("high_nsf")

    dsr = metrics.get("debt_to_revenue_ratio")
    if dsr is not None and dsr > 0.30:
        flags.append("high_dsr")

    avg_bal = metrics.get("avg_daily_balance")
    avg_rev = metrics.get("avg_monthly_revenue")
    if avg_bal is not None and avg_rev is not None and avg_rev > 0:
        if avg_bal < 0.10 * avg_rev:
            flags.append("low_balance_buffer")

    return flags


# ─────────────────────────────────────────────────────────────────────
# Readiness score
# ─────────────────────────────────────────────────────────────────────


def _compute_readiness_score(
    risk_flags: list[str],
    metrics: dict[str, Any],
) -> int:
    """0-100 score. Deductions per the 2026-05-25 rubric.

    Start at 100; subtract per flag + low-revenue penalty; clamp [0, 100].
    Lower = more underwriting risk; higher = cleaner deal.
    """
    score = 100
    if "stacked" in risk_flags:
        score -= 20
    if "declining_revenue" in risk_flags:
        score -= 15
    if "high_nsf" in risk_flags:
        score -= 10
    if "high_dsr" in risk_flags:
        score -= 25
    if "low_balance_buffer" in risk_flags:
        score -= 15
    avg_rev = metrics.get("avg_monthly_revenue")
    if avg_rev is not None and avg_rev < 20_000:
        score -= 10
    return max(0, min(100, score))


# ─────────────────────────────────────────────────────────────────────
# Data-only underwriting (no parsable statements) — CC 2026-06-18
# ─────────────────────────────────────────────────────────────────────


def _num(v: Any) -> float:
    """Parse a possibly-string currency/number to float; 0.0 on failure."""
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except Exception:
        return 0.0


def _provisional_grade_from_self_report(
    monthly_rev: float, app_data: dict
) -> tuple[str | None, str]:
    """A conservative, clearly-UNVERIFIED grade from self-reported signals only
    (no statements). Real grading needs statements; this keeps the deal movable
    and honestly labeled."""
    if monthly_rev <= 0:
        return None, (
            "No bank statements AND no stated monthly revenue on file — add a "
            "revenue figure or upload statements to assess."
        )
    tib = _num(app_data.get("time_in_business_months"))
    fico = _num(app_data.get("applicant_fico") or app_data.get("fico"))
    pts = 0
    pts += 2 if monthly_rev >= 50_000 else 1 if monthly_rev >= 15_000 else 0
    pts += 1 if tib >= 24 else 0
    pts += 1 if fico >= 650 else 0
    grade = "B" if pts >= 3 else "C" if pts >= 1 else "D"
    return grade, (
        "PROVISIONAL (self-reported, unverified) — upload 3 months of bank "
        "statements to confirm revenue, NSF, debt + positions before shopping."
    )


def _data_only_grading(
    app_data: dict, reason: str, build_metric_card
) -> tuple[dict, dict]:
    """Build (grading, metric_card) from SELF-REPORTED application data when no
    parsable statements exist. Same shape as grader.grade_deal so
    build_metric_card + the dashboard render it identically; flagged
    data_only/unverified so underwriting is never a dead-end."""
    monthly_rev = _num(app_data.get("monthly_revenue") or app_data.get("avg_monthly_revenue"))
    positions = int(_num(app_data.get("position_count")))
    tib_raw = app_data.get("time_in_business_months")
    try:
        tib = int(tib_raw) if tib_raw is not None else None
    except (TypeError, ValueError):
        tib = None
    grade, recommendation = _provisional_grade_from_self_report(monthly_rev, app_data)
    banner = (
        "DATA-ONLY: no bank statements parsed — revenue + risk are merchant "
        "SELF-REPORTED and UNVERIFIED. Upload 3 months of statements for a "
        "verified analysis (true revenue, NSF, debt, positions)."
    )
    grading = {
        "grade": grade,
        "recommendation": recommendation,
        "target_lender_tier": None,
        "true_monthly_revenue": monthly_rev,
        "excluded_credits_monthly": 0.0,
        "revenue_estimation": "self_reported_unverified",
        "active_mca_positions": positions,
        "mca_monthly_burden": 0.0,
        "mca_leverage": None,
        "estimated_total_mca_balance": 0.0,
        "estimate_quality": "self_reported",
        "nsfs_window_total": 0,
        "nsfs_per_month_avg": 0.0,
        "negative_balance_days": 0,
        "collections_flag": False,
        "equipment_lease_count": 0,
        "positions_verified": [],
        "red_flags": [banner],
        "unknown_biller_flags": [],
        "gross_deposits_total": monthly_rev,
        "positioning_merchant_safe": None,
        "grade_justification": "Graded on self-reported application data only (no bank statements).",
        "proposed_play": None,
        "collections": [],
        "other_debt": [],
        "avg_daily_balance": None,
        "time_in_business_months": tib,
        "data_source": "self_reported_no_statements",
        "review_period": {"months": 0},
        "confidence_notes": [banner, f"Reason: {reason}."],
        "data_only": True,
        "data_only_reason": reason,
    }
    metric_card = build_metric_card(grading)
    metric_card["data_only"] = True
    metric_card["revenue_note"] = "self-reported (no statements) — unverified"
    return grading, metric_card


def _data_only_metrics(app_data: dict) -> dict[str, Any]:
    """Scalar metric columns for the data-only path — self-reported revenue,
    everything statement-derived left None/0 (honest about what's unknown)."""
    monthly_rev = _num(app_data.get("monthly_revenue") or app_data.get("avg_monthly_revenue"))
    return {
        "avg_monthly_revenue": monthly_rev if monthly_rev > 0 else None,
        "avg_daily_balance": None,
        "nsf_count": 0,
        "deposit_consistency_pct": None,
        "debt_service_monthly": None,
        "debt_to_revenue_ratio": None,
        "lender_count": int(_num(app_data.get("position_count"))),
    }


# ─────────────────────────────────────────────────────────────────────
# Main processing logic for one row
# ─────────────────────────────────────────────────────────────────────


def _process_row(sb, row: dict) -> None:
    """Run the full underwriting pipeline for one claimed row.

    Sets status='complete' with all metrics on success, or
    status='error' with error_message on any exception. Never raises.
    """
    row_id = row["id"]
    application_id = row["application_id"]
    tenant_id = row["tenant_id"]

    # ── 0. Application snapshot — loaded EARLY because BOTH the statement
    # path AND the data-only fallback (no parsable statements) need the
    # merchant's self-reported financials. (2026-06-18, CC: underwriting must
    # always run, even with zero documents.)
    try:
        _app_row = (
            sb.table("tenant_records")
            .select("data")
            .eq("tenant_id", tenant_id)
            .eq("entity_type", "application")
            .eq("id", application_id)
            .maybe_single()
            .execute()
        )
        app_data: dict = (_app_row.data or {}).get("data") or {}
    except Exception:
        app_data = {}

    # ── 1. Find bank statement documents ──────────────────────────────
    # Codex 2026-05-25 P0 finding: prior SELECT omitted application_id/lead_id/parent_id,
    # causing the post-fetch JS-side filter to match nothing and fall back to ALL tenant
    # documents — cross-deal data leak risk. Fix: include FK columns in SELECT and move
    # the scope filter to a server-side WHERE clause. Fail closed — never fall back to
    # all-tenant documents.
    # 2026-06-11: lead_documents has NO application_id / parent_id column —
    # its real schema keys documents off lead_id only (id, tenant_id,
    # lead_id, storage_path, doc_type, ...). The prior SELECT referenced
    # those nonexistent columns, so the query 42703'd and EVERY run failed
    # at doc lookup. Under the shared-id model the dashboard stores an
    # application's bank statements with lead_id == the application's own id,
    # so the primary lookup filters lead_documents.lead_id == application_id.
    # The fallback covers rows stored under the application's distinct
    # data->lead_id (older split-id records).
    parent_lead_id = None
    try:
        # Primary path: docs attached under the application's own id.
        doc_rows = (
            sb.table("lead_documents")
            .select("id, storage_path, doc_type, lead_id")
            .eq("tenant_id", tenant_id)
            .eq("lead_id", application_id)
            .in_("doc_type", ["bank_statements_3mo", "bank_statement"])
            .execute()
        )
        docs = list(doc_rows.data or [])

        if not docs:
            # Fallback path: resolve the application's distinct parent lead_id
            # (split-id records) and look there.
            app_lead_row = (
                sb.table("tenant_records")
                .select("data->lead_id")
                .eq("tenant_id", tenant_id)
                .eq("entity_type", "application")
                .eq("id", application_id)
                .maybe_single()
                .execute()
            )
            parent_lead_id = (app_lead_row.data or {}).get("lead_id") if (app_lead_row and app_lead_row.data) else None
            if parent_lead_id and parent_lead_id != application_id:
                fallback_rows = (
                    sb.table("lead_documents")
                    .select("id, storage_path, doc_type, lead_id")
                    .eq("tenant_id", tenant_id)
                    .eq("lead_id", parent_lead_id)
                    .in_("doc_type", ["bank_statements_3mo", "bank_statement"])
                    .execute()
                )
                docs = list(fallback_rows.data or [])

        # 2026-06-18 (CC): MIS-CLASSIFIED-statement fallback. Operators routinely
        # upload bank statements that land as 'unclassified' (drawer upload
        # without picking the doc-type, or a form field name that didn't map to a
        # canonical doc_type). If NO canonically-typed statement was found above,
        # pull the lead's untyped/unclassified PDFs whose FILENAME looks like a
        # bank statement and underwrite those — so real uploaded statements stop
        # failing "none found". The filename heuristic keeps a misfiled DL / void
        # cheque out of the set, and the query stays scoped to THIS lead's ids
        # (never all-tenant — preserves the Codex P0 fix above).
        if not docs:
            lead_ids = [lid for lid in (application_id, parent_lead_id) if lid]
            if lead_ids:
                untyped_rows = (
                    sb.table("lead_documents")
                    .select("id, storage_path, doc_type, lead_id, filename")
                    .eq("tenant_id", tenant_id)
                    .in_("lead_id", lead_ids)
                    .execute()
                )
                for d in (untyped_rows.data or []):
                    dt = (d.get("doc_type") or "").strip().lower()
                    if dt in ("", "unclassified", "other") and _looks_like_bank_statement(
                        str(d.get("filename") or d.get("storage_path") or "")
                    ):
                        docs.append(d)
                if docs:
                    _log(
                        f"underwriting[{row_id}]: no canonically-typed statements; "
                        f"using {len(docs)} unclassified PDF(s) matched by filename heuristic"
                    )

        # Codex 2026-05-25 P0 finding: do NOT fall back to all-tenant documents.
        # If neither path finds docs, fail closed with a clear error message.
    except Exception as exc:
        _log(f"underwriting[{row_id}]: doc lookup failed: {exc}")
        _fail(sb, row_id, f"Document lookup failed: {exc!s:.400}")
        return

    # No statements found is NOT fatal any more (CC 2026-06-18) — we fall back
    # to a data-only underwriting from the application's self-reported data
    # below. `docs` may be empty here; the parse loop then yields no
    # parser_outputs and the data-only branch runs.

    # ── 2. Import pipeline modules ────────────────────────────────────
    try:
        (
            parse_statement,
            summarize_debt,
            generate_sales_angle,
            grade_deal,
            build_metric_card,
        ) = _import_submodules()
    except Exception as exc:
        _log(f"underwriting[{row_id}]: submodule import failed: {exc}")
        _fail(sb, row_id, f"Submodule import failed: {exc!s:.300}")
        return

    # ── 3. Parse each statement PDF ───────────────────────────────────
    parser_outputs: list[dict] = []
    for doc in docs:
        storage_path = doc.get("storage_path") or ""
        if not storage_path:
            continue
        local_path = _resolve_storage_path_to_local(sb, storage_path, tenant_id)
        if local_path is None:
            _log(f"underwriting[{row_id}]: skipping doc {doc.get('id')} — download failed")
            continue
        try:
            result = parse_statement(local_path)
            parser_outputs.append(result)
        except Exception as exc:
            _log(f"underwriting[{row_id}]: parse failed for {local_path.name}: {exc}")
            # Non-fatal per-file: keep processing other statements.

    # ── 4-8. Underwrite. Statement-based when we have parsed statements;
    # otherwise a DATA-ONLY assessment from the merchant's self-reported
    # application data. CC 2026-06-18: underwriting is ALWAYS functional — 1, 2,
    # or 3 statements, or none. With no parsable statements we still produce a
    # clearly-UNVERIFIED report from stated monthly revenue + form info so the
    # operator is never blocked; uploading statements upgrades it to a verified
    # analysis. app_data was loaded up front (step 0) — both paths use it.
    if parser_outputs:
        # ── Statement-based path (the full SOP pipeline) ──
        try:
            debt_analysis = summarize_debt(parser_outputs)
        except Exception as exc:
            _log(f"underwriting[{row_id}]: debt analysis failed (non-fatal): {exc}")
            debt_analysis = {}
        data_source = "upload"
        # SOP §§3,5,6,7 grading — TRUE revenue, verified positions, leverage,
        # grade + the sales metric card. Best-effort: a {grade: null} stub on
        # any exception so the row still completes.
        try:
            grading = grade_deal(
                parser_outputs,
                debt_analysis,
                app_data=app_data,
                data_source=data_source,
            )
            metric_card = build_metric_card(grading)
        except Exception as exc:
            _log(f"underwriting[{row_id}]: grading failed (non-fatal): {exc}")
            grading = {"grade": None, "recommendation": None, "error": str(exc)[:300]}
            metric_card = {"grade": None, "recommendation": None, "error": str(exc)[:300]}
        debt_analysis = dict(debt_analysis)
        debt_analysis["grading"] = grading
        debt_analysis["metric_card"] = metric_card
        metrics = _derive_metrics(parser_outputs, debt_analysis)
        risk_flags = _compute_risk_flags(metrics, parser_outputs)
        readiness_score = _compute_readiness_score(risk_flags, metrics)
        # SOP-aware risk flag: any JUNK grade is a hard "don't shop" signal.
        if grading.get("grade") == "JUNK":
            risk_flags.append("junk_paper")
        if grading.get("collections_flag"):
            risk_flags.append("mca_collections")
    else:
        # ── Data-only path (no parsable statements — never a dead-end) ──
        reason = "no_documents" if not docs else "all_statements_failed_parse"
        _log(
            f"underwriting[{row_id}]: no parsable statements ({reason}) — "
            f"running DATA-ONLY underwriting from self-reported application data"
        )
        grading, metric_card = _data_only_grading(app_data, reason, build_metric_card)
        debt_analysis = {
            "data_only": True,
            "data_only_reason": reason,
            "grading": grading,
            "metric_card": metric_card,
        }
        metrics = _data_only_metrics(app_data)
        risk_flags = ["data_only_no_statements"]
        readiness_score = _compute_readiness_score(risk_flags, metrics)

    # ── Sales angle (both paths — informed by grading where present) ──
    try:
        sales_angle = generate_sales_angle(app_data, debt_analysis)
    except Exception as exc:
        # Non-fatal: structured analysis still lands; the angle can be regenerated.
        _log(f"underwriting[{row_id}]: sales_angle generation failed (non-fatal): {exc}")
        sales_angle = f"(generation failed: {exc!s:.200})"

    # ── 8. Persist complete row ───────────────────────────────────────
    update_payload: dict[str, Any] = {
        "status": "complete",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "parser_output": parser_outputs,
        "debt_analysis": debt_analysis,
        "sales_angle": sales_angle,
        "risk_flags": risk_flags,
        "readiness_score": readiness_score,
        "error_message": None,
        # Scalar metric columns
        "avg_monthly_revenue": metrics["avg_monthly_revenue"],
        "avg_daily_balance": metrics["avg_daily_balance"],
        "nsf_count": metrics["nsf_count"],
        "deposit_consistency_pct": metrics["deposit_consistency_pct"],
        "debt_service_monthly": metrics["debt_service_monthly"],
        "debt_to_revenue_ratio": metrics["debt_to_revenue_ratio"],
        "lender_count": metrics["lender_count"],
    }
    try:
        sb.table("application_underwriting").update(update_payload).eq("id", row_id).execute()
        _log(
            f"underwriting[{row_id}]: complete — "
            f"score={readiness_score} flags={risk_flags} "
            f"revenue={metrics['avg_monthly_revenue']} "
            f"dsr={metrics['debt_to_revenue_ratio']}"
        )
    except Exception as exc:
        _log(f"underwriting[{row_id}]: final update failed: {exc}")


def _fail(sb, row_id: str, message: str) -> None:
    """Mark a row as error. Best-effort — log on failure."""
    try:
        sb.table("application_underwriting").update({
            "status": "error",
            "error_message": message[:500],
            "run_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row_id).execute()
    except Exception as exc:
        _log(f"underwriting[{row_id}]: could not write error status: {exc}")
    _log(f"underwriting[{row_id}]: ERROR — {message[:200]}")


# ─────────────────────────────────────────────────────────────────────
# Tick — claim one pending row and process it
# ─────────────────────────────────────────────────────────────────────


def tick(sb) -> bool:
    """Claim and process one pending row. Returns True if a row was found.

    The 5-second grace window ensures the dashboard's INSERT has committed
    before the daemon's first poll can snatch it (operators occasionally
    cancel in that window).
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=PENDING_GRACE_SECONDS)
    ).isoformat()

    # Atomic claim: UPDATE...RETURNING ensures only one concurrent daemon
    # instance can claim the same row even under a PM2 restart overlap.
    try:
        result = sb.rpc(
            "claim_underwriting_row",
            {"cutoff_ts": cutoff},
        ).execute()
        claimed = result.data or []
    except Exception:
        # claim_underwriting_row RPC may not exist yet — fall back to
        # SELECT-then-UPDATE (acceptable until the migration ships the RPC).
        try:
            pending = (
                sb.table("application_underwriting")
                .select("id, tenant_id, application_id, triggered_by")
                .eq("status", "pending")
                .lt("created_at", cutoff)
                .order("created_at", desc=False)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            _log(f"tick: read failed: {exc}")
            return False
        if not pending.data:
            return False
        row_id = pending.data[0]["id"]
        try:
            claim = (
                sb.table("application_underwriting")
                .update({"status": "parsing"})
                .eq("id", row_id)
                .eq("status", "pending")  # optimistic lock
                .execute()
            )
        except Exception as exc:
            _log(f"tick: claim failed row={row_id}: {exc}")
            return False
        if not claim.data:
            # Another worker claimed it first — no work this tick.
            return False
        claimed = claim.data

    if not claimed:
        return False

    row = claimed[0]
    _log(f"underwriting: claimed row={row['id']} app={row.get('application_id')} tenant={row.get('tenant_id')}")
    try:
        _process_row(sb, row)
    except Exception as exc:
        _fail(sb, row["id"], str(exc)[:500])
    return True


# ─────────────────────────────────────────────────────────────────────
# Daemon loop
# ─────────────────────────────────────────────────────────────────────


def run_once() -> int:
    sb = _supabase()
    if not sb:
        _log("supabase unavailable — aborting")
        return 1
    tick(sb)
    return 0


def run_loop(interval: int) -> int:
    interval = max(5, int(interval))
    _log(f"underwriting-orchestrator up; tick interval = {interval}s")
    crash_window_start = 0.0
    crash_window_count = 0
    CRASH_ALERT_LIMIT = 2
    CRASH_ALERT_WINDOW_SEC = 600
    while True:
        try:
            sb = _supabase()
            if not sb:
                _log("supabase unavailable — will retry next tick")
            else:
                tick(sb)
        except Exception as exc:
            _log(f"tick crashed: {exc}")
            now = time.time()
            if now - crash_window_start > CRASH_ALERT_WINDOW_SEC:
                crash_window_start = now
                crash_window_count = 0
            if crash_window_count < CRASH_ALERT_LIMIT:
                crash_window_count += 1
                try:
                    from notify import notify_daemon_crash  # type: ignore
                    notify_daemon_crash("underwriting-orchestrator", str(exc))
                except Exception:
                    pass
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            _log("underwriting-orchestrator shutting down (SIGINT)")
            return 0


def run_tail(count: int) -> int:
    if not LOG_PATH.exists():
        print("(no log yet)")
        return 0
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-count:]
    except OSError as exc:
        print(f"read failed: {exc}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Underwriting orchestrator — polls pending rows and runs the pipeline"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("once", help="Run one tick and exit").set_defaults(
        func=lambda _a: run_once()
    )

    lp = sub.add_parser("loop", help="Run continuously")
    lp.add_argument("--interval", type=int, default=30, help="seconds between ticks (default: 30)")
    lp.set_defaults(func=lambda a: run_loop(a.interval))

    tl = sub.add_parser("tail", help="Print the last N log lines")
    tl.add_argument("--count", type=int, default=50)
    tl.set_defaults(func=lambda a: run_tail(a.count))

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
