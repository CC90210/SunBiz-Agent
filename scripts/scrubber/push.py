"""scrubber/push.py — stage scrubbed candidates for Ezra's approval.

IMPORTANT — the daemon does NOT create leads. It only writes `pending_review`
rows to scrub_candidates (service-role insert). The actual push into the lead
pipeline happens when EZRA approves a candidate in the Command Centre: the
dashboard approval route calls createRecord(entity='lead', stage='uw_sheet'),
which emits BRAVO_RECORD_STATUS_CHANGED so the follow-up lifecycle fires. This
keeps Ezra as the gate (gate.mode='require_ezra') and means no bridge bearer
token is needed in the daemon.

Dedup, two layers:
  1. vs existing tenant leads — skip a candidate whose merchant is already a
     lead (reuses the importer's email→phone→(company+state) keysets).
  2. vs existing scrub_candidates — one card per DEAL (state.row_hash keys
     UW-sheet deals on source_file_id; the unique (tenant_id, row_hash) index is
     the DB backstop).

REFRESH-IN-PLACE (2026-07-21). A UW Sheet is a live document the underwriter
keeps filling in, and the daemon re-reads it every tick. A hash that is already
queued as `pending_review` is therefore not "handled" — it is the SAME deal with
better data, so its card is UPDATED in place (and Ezra is NOT re-notified).
A hash that is already `approved`/`declined` is skipped: a decided deal must
never be resurrected or silently rewritten under the reviewer.


Only `good`/`review` tier candidates are stored; `bad` ones are counted by the
daemon but never surfaced (keeps Ezra's queue clean).
"""

from __future__ import annotations

import sys
from typing import Any, Optional

from sunbiz_constants import SUNBIZ_TENANT_ID

CANDIDATE_TABLE = "scrub_candidates"


def _existing_candidates(sb, tenant_id: str) -> dict[str, dict[str, Any]]:
    """row_hash -> {id, status} for this tenant's scrub_candidates.

    Status matters: a `pending_review` row is refreshed in place, a decided one
    is left alone (see the module docstring)."""
    out: dict[str, dict[str, Any]] = {}
    try:
        r = (
            sb.table(CANDIDATE_TABLE)
            .select("id,row_hash,status")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        for row in (r.data or []):
            h = row.get("row_hash")
            if h:
                out[h] = {"id": row.get("id"), "status": row.get("status")}
    except Exception as e:  # noqa: BLE001
        print(f"[push] existing-candidate read failed: {e}", file=sys.stderr)
    return out


#: Fields refreshed on a re-scrape of a still-pending deal. Deliberately excludes
#: tenant_id / row_hash / status / created_at (identity + reviewer state) and
#: reviewed_by / reviewed_at / created_lead_id (reviewer decisions).
_REFRESHABLE = (
    "tier", "score", "reasons", "decline_reason", "previously_submitted",
    "leverage_pct", "monthly_revenue", "lead_data", "source_file",
    "source_file_id", "scoring_config_version", "scrubbed_at",
)


def _refresh_candidate(sb, candidate_id: str, row: dict[str, Any]) -> bool:
    """Update a still-pending card with the newest scrape of the same deal."""
    patch = {k: row[k] for k in _REFRESHABLE if k in row}
    try:
        sb.table(CANDIDATE_TABLE).update(patch).eq("id", candidate_id).execute()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[push] refresh failed for {candidate_id}: {e}", file=sys.stderr)
        return False


def _candidate_row(tenant_id: str, ref: dict, data: dict, result: dict, h: str, cfg: dict) -> dict:
    return {
        "tenant_id": tenant_id,
        "status": "pending_review",
        "tier": result["tier"],
        "score": result["score"],
        "reasons": result.get("reasons") or [],
        "decline_reason": result.get("decline_reason"),
        "previously_submitted": bool(data.get("previously_submitted")),
        "leverage_pct": result.get("leverage_pct"),
        "monthly_revenue": result.get("monthly_revenue"),
        "lead_data": data,  # handed verbatim to createRecord(entity='lead') on approval
        "source_file": ref.get("name"),
        "source_file_id": ref.get("id"),
        "row_hash": h,
        "scoring_config_version": cfg.get("version"),
        "scrubbed_at": data.get("scrubbed_at"),
    }


def stage_candidates(
    sb,
    env: dict[str, Any],
    cfg: dict[str, Any],
    ref: dict[str, Any],
    candidates: list[dict[str, Any]],
    dedup_existing: Optional[tuple[set, set, set]] = None,
) -> dict[str, set]:
    """Write qualified (good/review) candidates as pending_review rows.

    Returns {"inserted": set, "skipped": set, "failed": set} of row_hashes so
    the caller can mark ONLY confirmed-handled rows as seen. A row in `failed`
    (a non-duplicate DB error) is deliberately NOT marked seen, so the next
    tick retries it instead of losing the lead forever."""
    tenant_id = SUNBIZ_TENANT_ID
    gate = (cfg.get("gate") or {}).get("mode", "require_ezra")
    if gate != "require_ezra":
        # Auto-push modes would require the createRecord/bridge path (not in the
        # daemon). Until that's built, fail safe to the review queue.
        print(f"[push] gate.mode='{gate}' not implemented in daemon — staging as pending_review (Ezra gate)", file=sys.stderr)

    inserted: set[str] = set()
    skipped: set[str] = set()
    failed: set[str] = set()
    refreshed: set[str] = set()   # still-pending cards updated in place

    surfaceable = [c for c in candidates if c["score_result"]["tier"] in ("good", "review")]
    if not surfaceable:
        return {"inserted": inserted, "skipped": skipped, "failed": failed, "refreshed": refreshed}

    emails, phones, businesses = dedup_existing or (set(), set(), set())
    existing = _existing_candidates(sb, tenant_id)

    pending: list[tuple[str, dict]] = []  # (row_hash, row)
    for c in surfaceable:
        d = c["data"]
        r = c["score_result"]
        h = c["row_hash"]
        prior = existing.get(h)
        if prior:
            # Same DEAL seen again. If Ezra hasn't decided it yet, this scrape is
            # newer and more complete — refresh the card in place and do NOT
            # re-notify. If it's already approved/declined, leave it alone.
            if prior.get("status") == "pending_review":
                row = _candidate_row(tenant_id, ref, d, r, h, cfg)
                if _refresh_candidate(sb, prior["id"], row):
                    refreshed.add(h)
                    skipped.add(h)
                else:
                    failed.add(h)  # leave UNSEEN so the next tick retries
                continue
            skipped.add(h)
            continue
        e = (d.get("email") or "").strip().lower()
        p = (d.get("phone") or "").strip()
        co = (d.get("company") or d.get("business_name") or "").strip().lower()
        s = (d.get("state") or "").strip().lower()
        if (e and e in emails) or (p and p in phones) or (co and f"{co}|{s}" in businesses):
            skipped.add(h)
            continue
        pending.append((h, _candidate_row(tenant_id, ref, d, r, h, cfg)))

    if not pending:
        return {"inserted": inserted, "skipped": skipped, "failed": failed, "refreshed": refreshed}

    # Batch insert; on any error, retry row-by-row so one bad/duplicate row
    # doesn't drop the whole batch and so we can record per-row outcomes.
    try:
        res = sb.table(CANDIDATE_TABLE).insert([row for _h, row in pending]).execute()
        inserted.update(h for h, _row in pending)
        _notify_ezra(env, res.data or [])
    except Exception:  # noqa: BLE001
        for h, row in pending:
            try:
                res = sb.table(CANDIDATE_TABLE).insert(row).execute()
                inserted.add(h)
                _notify_ezra(env, res.data or [])
            except Exception as e:  # noqa: BLE001
                msg = str(e).lower()
                if "duplicate" in msg or "unique" in msg or "23505" in msg:
                    skipped.add(h)  # row_hash conflict → already staged → handled
                else:
                    failed.add(h)   # real error → leave UNSEEN so next tick retries
                    print(f"[push] insert failed for {row.get('source_file')}: {e}", file=sys.stderr)
    return {"inserted": inserted, "skipped": skipped, "failed": failed, "refreshed": refreshed}


def _notify_ezra(env: dict[str, Any], inserted_rows: list[dict]) -> None:
    """Send each newly-staged candidate to Ezra's Telegram for approval. No-op
    if EZRA_TELEGRAM_CHAT_ID isn't set (dashboard-only mode)."""
    if not (env.get("EZRA_TELEGRAM_CHAT_ID") or "").strip() or not inserted_rows:
        return
    try:
        from scrubber import telegram_bridge as TB
    except Exception as e:  # noqa: BLE001
        print(f"[push] telegram_bridge unavailable: {e}", file=sys.stderr)
        return
    for row in inserted_rows:
        cid = row.get("id")
        if not cid:
            continue
        try:
            r = TB.send_deal(env, row, candidate_id=str(cid))
            if not r.get("ok"):
                print(f"[push] telegram send for {cid}: {r.get('error')}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"[push] telegram send failed for {cid}: {e}", file=sys.stderr)
