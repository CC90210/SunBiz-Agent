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
    """Stable identity hash for a NORMALIZED lead.

    DEAL IDENTITY, not snapshot identity. A Breeze UW Sheet is a LIVE working
    document: the underwriter fills in funder rows and bank months over minutes
    or days, and the scrubber re-reads it every tick. The hash must therefore
    identify the DEAL, so re-reading a half-finished sheet updates the existing
    review card instead of minting a new one.

    For UW-sheet deals that identity is `source_file_id` — one sheet IS one
    deal, and the file id is immune to in-progress edits.

    Why this changed (2026-07-21): the previous identity tuple keyed on
    `mca_positions`, which increments as funder rows are typed, so ONE deal
    staged 4-6 times (`nexgen networks corp 720` staged 6 times from a single
    sheet; 163 of 476 pending cards were redundant). Two of its three intended
    stability fields — `annual_revenue` and `current_funders_text` — are dead
    keys that the UW-sheet parser never emits (they belong to the older CSV
    importer shape), so the effective identity had collapsed to
    company+state+positions: entirely volatile.

    Non-UW leads (the CSV importer) keep a field-based identity, with those two
    dead keys corrected to the ones actually emitted so the fallback is stable
    rather than accidentally position-keyed.
    """
    source_file_id = (data.get("source_file_id") or "").strip()
    if source_file_id:
        blob = json.dumps({"source_file_id": source_file_id}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    identity = {
        "email": (data.get("email") or "").strip().lower(),
        "phone": (data.get("phone") or "").strip(),
        "company": (data.get("company") or data.get("business_name") or "").strip().lower(),
        "state": (data.get("state") or "").strip().lower(),
        # Revenue/funders are identity here only to separate two same-named
        # businesses in one import; they are NOT read from the UW-sheet shape
        # (that path returns above). Accept either schema's key.
        "revenue": data.get("annual_revenue") or data.get("monthly_revenue"),
        "funders_text": (
            data.get("current_funders_text")
            or _funders_fingerprint(data.get("current_funders"))
        ).strip().lower(),
    }
    blob = json.dumps(identity, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _funders_fingerprint(funders: Any) -> str:
    """Stable text for a structured funder list, so the CSV-importer identity
    survives a schema that stores funders as dicts rather than a raw string."""
    if not isinstance(funders, list):
        return ""
    names = sorted(
        str(f.get("funder") or "").strip().lower()
        for f in funders
        if isinstance(f, dict) and f.get("funder")
    )
    return ",".join(names)


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


def _pid_alive(pid: Any) -> bool:
    """True only if `pid` is a live process. Lets us reclaim a claim the instant
    the holder dies, instead of waiting out the whole stale TTL — otherwise every
    `pm2 restart` blacks the worker out for up to stale_seconds."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except Exception:  # noqa: BLE001
        return False


def acquire_claim(stale_seconds: int = 600) -> bool:
    """Best-effort single-instance guard. Writes a claim file with this
    PID + timestamp. Returns False only if another instance is BOTH still
    alive AND fresh. A claim whose holder PID is dead is reclaimed immediately;
    a claim older than stale_seconds (hung holder) is also reclaimed."""
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
            fresh = age is None or age < stale_seconds
            if other_pid != os.getpid() and _pid_alive(other_pid) and fresh:
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
