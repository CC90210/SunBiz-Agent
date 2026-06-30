"""scrubber/state.py — idempotency ledger for the Sift MCA Lead Scrubber.

Three layers of "don't do this twice", persisted to a single JSON ledger
under SunBiz-Agent/state/ (atomic write: temp file + os.replace):

  1. File-level  — processed Drive file IDs keyed to their modifiedTime.
                   A Google Sheet that hasn't changed since we last scanned
                   it is skipped entirely (no fetch, no parse). An EDITED
                   sheet (newer modifiedTime) re-scans — but row-level dedup
                   below stops already-seen rows from being re-staged.
  2. Row-level   — sha256 of each normalized lead's identity. Guards against
                   a sheet that grows between runs (appended rows) and the
                   same merchant appearing across multiple sheets.
  3. (Lead-level dedup vs existing tenant leads lives in push.py — it reuses
      import_mca_leads.fetch_existing_keys; it is NOT duplicated here.)

The ledger is intentionally simple/local — Sift runs as a single PM2
instance that owns the queue (mirrors the extraction-consumer rule), so a
file lock is unnecessary for the common case. A coarse claim flag is still
written so a second accidental instance refuses to run concurrently.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ledger lives in the SunBiz-Agent repo's state/ dir (same convention as
# import_mca_leads.*.json and sequence_runner.cursor).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_DIR = _REPO_ROOT / "state"
LEDGER_PATH = _STATE_DIR / "scrubber_ledger.json"

# Cap the row-hash history so the ledger can't grow without bound. 200k
# covers many months of sheets at ~600 rows each; oldest entries roll off.
_MAX_ROW_HASHES = 200_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state(path: Path = LEDGER_PATH) -> dict[str, Any]:
    """Load the ledger, returning a fresh skeleton if absent/corrupt.

    A corrupt ledger is NEVER fatal — Sift logs and starts clean rather
    than crash-looping. The worst case of a lost ledger is re-scanning
    sheets, which row-level + lead-level dedup absorb harmlessly."""
    skeleton: dict[str, Any] = {
        "version": 1,
        "files": {},          # file_id -> {modified_time, processed_at, rows_seen, rows_staged}
        "row_hashes": [],     # list[str] (rolling window, newest at end)
        "updated_at": None,
    }
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return skeleton
        # Defensive: ensure required keys exist (forward/backward compat).
        for k, v in skeleton.items():
            data.setdefault(k, v)
        return data
    except FileNotFoundError:
        return skeleton
    except Exception as exc:  # noqa: BLE001
        print(f"[scrubber.state] ledger unreadable ({exc}) — starting clean", file=sys.stderr)
        return skeleton


def save_state(state: dict[str, Any], path: Path = LEDGER_PATH) -> None:
    """Atomically persist the ledger (temp file + os.replace)."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Roll off oldest row hashes beyond the cap.
    rh = state.get("row_hashes") or []
    if len(rh) > _MAX_ROW_HASHES:
        state["row_hashes"] = rh[-_MAX_ROW_HASHES:]
    state["updated_at"] = _now_iso()
    fd, tmp = tempfile.mkstemp(prefix="scrubber_ledger.", suffix=".tmp", dir=str(_STATE_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── file-level ────────────────────────────────────────────────────────

def is_file_processed(state: dict[str, Any], file_id: str, modified_time: Optional[str]) -> bool:
    """True when this exact (file_id, modifiedTime) was already processed.

    A new modifiedTime (the sheet was edited) returns False so the file is
    re-scanned; row-level dedup then skips rows we've already staged."""
    rec = (state.get("files") or {}).get(file_id)
    if not rec:
        return False
    # No modifiedTime available (non-Drive source) → treat presence as done.
    if modified_time is None:
        return True
    return rec.get("modified_time") == modified_time


def mark_file_processed(
    state: dict[str, Any],
    file_id: str,
    modified_time: Optional[str],
    rows_seen: int,
    rows_staged: int,
) -> None:
    files = state.setdefault("files", {})
    files[file_id] = {
        "modified_time": modified_time,
        "processed_at": _now_iso(),
        "rows_seen": rows_seen,
        "rows_staged": rows_staged,
    }


# ── row-level ─────────────────────────────────────────────────────────

def row_hash(data: dict[str, Any]) -> str:
    """Stable identity hash for a NORMALIZED lead (post map_row_to_lead_data).

    Uses the dedup-relevant identity fields only, so the same merchant with
    the same sheet data yields the same hash regardless of cell formatting
    or column order. Volatile fields (stage, score, timestamps) are excluded."""
    identity = {
        "email": (data.get("email") or "").strip().lower(),
        "phone": (data.get("phone") or "").strip(),
        "company": (data.get("company") or data.get("business_name") or "").strip().lower(),
        "state": (data.get("state") or "").strip().lower(),
        "revenue": data.get("annual_revenue"),
        "positions": data.get("mca_positions"),
        "funders_text": (data.get("current_funders_text") or "").strip().lower(),
    }
    blob = json.dumps(identity, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def is_row_seen(state: dict[str, Any], h: str) -> bool:
    # O(n) over a list would be slow; build a set lazily on first use.
    seen = state.get("_row_set")
    if seen is None:
        seen = set(state.get("row_hashes") or [])
        state["_row_set"] = seen
    return h in seen


def mark_row_seen(state: dict[str, Any], h: str) -> None:
    seen = state.get("_row_set")
    if seen is None:
        seen = set(state.get("row_hashes") or [])
        state["_row_set"] = seen
    if h not in seen:
        seen.add(h)
        state.setdefault("row_hashes", []).append(h)


def strip_runtime(state: dict[str, Any]) -> dict[str, Any]:
    """Drop the lazy `_row_set` before serialization (sets aren't JSON)."""
    return {k: v for k, v in state.items() if not k.startswith("_")}


# ── coarse single-instance claim ──────────────────────────────────────

def claim_path() -> Path:
    return _STATE_DIR / "scrubber.claim"


def acquire_claim(stale_seconds: int = 600) -> bool:
    """Best-effort single-instance guard. Writes a claim file with this
    PID + timestamp. Returns False if a FRESH claim by another PID exists
    (another Sift instance is running). A claim older than stale_seconds is
    considered crashed and reclaimed."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = claim_path()
    try:
        if p.exists():
            rec = json.loads(p.read_text(encoding="utf-8"))
            ts = rec.get("ts")
            age = None
            if ts:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
                except Exception:  # noqa: BLE001
                    age = None
            other_pid = rec.get("pid")
            if other_pid != os.getpid() and (age is None or age < stale_seconds):
                return False
    except Exception:  # noqa: BLE001
        pass  # unreadable claim → take it
    try:
        p.write_text(json.dumps({"pid": os.getpid(), "ts": _now_iso()}), encoding="utf-8")
        return True
    except OSError:
        return True  # can't write claim → don't block work


def refresh_claim() -> None:
    """Re-stamp the claim timestamp (call each loop tick so a long-running
    instance isn't mistaken for crashed)."""
    try:
        claim_path().write_text(json.dumps({"pid": os.getpid(), "ts": _now_iso()}), encoding="utf-8")
    except OSError:
        pass
