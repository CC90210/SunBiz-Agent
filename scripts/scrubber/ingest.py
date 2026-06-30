"""scrubber/ingest.py — Drive ingestion for the Breeze UW Entry Sheet automation.

Google Drive is the ONLY source (confirmed with CC 2026-06-30: there is no
email-notification path). New MCA web-form lead sheets land at random times
under the SunBiz account, so the daemon polls Drive on a tight loop.

Discovery strategy (verified live 2026-06-30 against gws):
  - Query by OWNER (admin@sunbizfunding.com) — this cleanly returns only
    SunBiz-originated sheets and EXCLUDES our own copies / Bravo outputs
    (those are owned by conaugh@oasisai.work). Folder/parents queries are
    unreliable for shared drives; owner-based is robust.
  - Client-side filter to spreadsheet/xlsx mimetypes whose title contains
    the configured hint (default "MCA_Webforms" — the raw lead-sheet export
    naming, excluding aggregate "1750 MCA apps" / "BA Approvals" artifacts).

Fetch strategy:
  - `google_tool.py drive download <id> --output <tmp>.xlsx` exports a Google
    Sheet to .xlsx and raw-downloads a native .xlsx — both land as one .xlsx.
  - Parse with import_mca_leads.read_rows() (the SAME parser the importer
    uses) so column handling stays identical.

All Drive access goes through the shared `google_tool.py` CLI (gws OAuth),
NOT a direct Google client — so credentials never enter this process.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from _bravo_bootstrap import resolve_bravo_root
from import_mca_leads import read_rows

SHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DRIVE_TIMEOUT = 90


def _google_tool() -> Optional[Path]:
    root = resolve_bravo_root()
    if root is None:
        return None
    p = root / "scripts" / "integrations" / "google_tool.py"
    return p if p.exists() else None


def _run_google_tool(
    tool_args: list[str], timeout: int = _DRIVE_TIMEOUT, cwd: Optional[str] = None
) -> tuple[bool, str, str]:
    """Run google_tool.py with the daemon's interpreter. Returns
    (ok, stdout, stderr). `cwd` matters for `drive download`: gws rejects an
    --output path outside the current directory, so downloads run from inside
    the temp dir with a relative output filename."""
    tool = _google_tool()
    if tool is None:
        return False, "", "google_tool.py not found (CEO-Agent root missing)"
    try:
        proc = subprocess.run(
            [sys.executable, str(tool), *tool_args],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return False, "", "google_tool timed out"
    except Exception as e:  # noqa: BLE001
        return False, "", f"spawn error: {e}"
    return proc.returncode == 0, proc.stdout or "", proc.stderr or ""


def discover_sheets(
    env: dict[str, Any],
    owner: str,
    title_hint: str = "",
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Return new candidate sheets from the SunBiz account, newest first.

    Each item: {id, name, modified_time, mime_type}. Filtering by owner is
    the primary discriminator; title_hint + mimetype narrow to lead sheets.
    Results are modifiedTime-desc, so the newest sheets are always in this
    window — max_results=100 is generous headroom, not a correctness limit
    (review finding 16)."""
    # Drive query `q`. trashed=false avoids re-surfacing deleted sheets.
    q = f"'{owner}' in owners and trashed = false"
    ok, out, err = _run_google_tool(
        ["drive", "list", "--json", "--max", str(max_results), "--query", q]
    )
    if not ok:
        raise RuntimeError(f"drive list failed: {err.strip()[:200]}")
    try:
        files = json.loads(out or "[]")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"drive list returned non-JSON: {e}")

    hint = (title_hint or "").lower()
    refs: list[dict[str, Any]] = []
    for f in files:
        name = f.get("name", "") or ""
        mime = f.get("mimeType", "") or ""
        if mime not in (SHEET_MIME, XLSX_MIME):
            continue
        if hint and hint not in name.lower():
            continue
        refs.append({
            "id": f["id"],
            "name": name,
            "modified_time": f.get("modifiedTime"),
            "mime_type": mime,
        })
    return refs


def fetch_rows(env: dict[str, Any], ref: dict[str, Any]) -> list[dict[str, Any]]:
    """Download a sheet to a temp .xlsx and parse it with the importer's
    read_rows(). Works for both native .xlsx and Google Sheets (exported)."""
    file_id = ref["id"]
    with tempfile.TemporaryDirectory(prefix="sift_dl_") as td:
        # gws rejects an --output path outside the CWD, so run the download
        # FROM the temp dir with a RELATIVE filename. A .xlsx name makes BOTH
        # cases land as sheet.xlsx (native .xlsx → alt=media exact path;
        # Google Sheet → export appends .xlsx only if not already present).
        ok, _stdout, err = _run_google_tool(
            ["drive", "download", file_id, "--output", "sheet.xlsx"], cwd=td
        )
        if not ok:
            raise RuntimeError(f"drive download failed for {file_id}: {err.strip()[:200]}")
        out_path = Path(td) / "sheet.xlsx"
        if not out_path.exists():
            # Defensive: locate the produced .xlsx (newest first), not any
            # sheet* temp artifact the tool may leave behind (review finding 7).
            produced = sorted(
                Path(td).glob("sheet*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            if not produced:
                raise RuntimeError(f"download produced no .xlsx for {file_id}")
            out_path = produced[0]
        return read_rows(out_path)
