"""scrubber/ingest.py — Drive ingestion for the Breeze UW Entry Sheet automation.

Google Drive is the ONLY source (confirmed with CC 2026-06-30: there is no
email-notification path). New MCA web-form lead sheets land at random times,
so the daemon polls Drive on a tight loop.

Auth: the scrubber authenticates AS the Breeze identity
(aiscrubbing@breezeadvance.com) using an OAuth refresh token stored in
.env.agents — NOT the operator's personal account, and NOT a Gmail app
password (which is IMAP/SMTP-only). Required keys:
    BREEZE_GOOGLE_CLIENT_ID
    BREEZE_GOOGLE_CLIENT_SECRET
    BREEZE_GOOGLE_REFRESH_TOKEN     (mint once via scripts/scrubber/google_oauth_setup.py)
The refresh token is exchanged for short-lived access tokens automatically, so
the VPS never needs a browser or a keyring.

Discovery: query by OWNER (admin@sunbizfunding.com) — returns only
SunBiz-originated sheets and excludes our own copies/outputs. The Breeze
identity must have READ access to those sheets (SunBiz shares the folder with
aiscrubbing@breezeadvance.com) or discovery returns nothing.

Fetch: export Google Sheets to .xlsx (or download a native .xlsx), then parse
with import_mca_leads.read_rows() so column handling stays identical.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any, Optional

from import_mca_leads import read_rows

SHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Cache the built Drive client across calls within one process (one refresh).
_DRIVE_SERVICE = None


def _missing_creds(env: dict[str, Any]) -> list[str]:
    keys = ["BREEZE_GOOGLE_CLIENT_ID", "BREEZE_GOOGLE_CLIENT_SECRET", "BREEZE_GOOGLE_REFRESH_TOKEN"]
    return [k for k in keys if not (env.get(k) or "").strip()]


def drive_service(env: dict[str, Any], force: bool = False):
    """Build (and cache) a read-only Drive client authed as the Breeze
    identity from BREEZE_GOOGLE_* in .env.agents. Raises RuntimeError with a
    clear message if creds are missing or a lib is absent."""
    global _DRIVE_SERVICE
    if _DRIVE_SERVICE is not None and not force:
        return _DRIVE_SERVICE
    missing = _missing_creds(env)
    if missing:
        raise RuntimeError(
            "missing Breeze Google credentials in .env.agents: " + ", ".join(missing)
            + " (mint the refresh token via scripts/scrubber/google_oauth_setup.py)"
        )
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            f"Google client libs not installed ({e}). "
            "pip install google-auth google-api-python-client"
        )
    creds = Credentials(
        token=None,
        refresh_token=(env.get("BREEZE_GOOGLE_REFRESH_TOKEN") or "").strip(),
        client_id=(env.get("BREEZE_GOOGLE_CLIENT_ID") or "").strip(),
        client_secret=(env.get("BREEZE_GOOGLE_CLIENT_SECRET") or "").strip(),
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    _DRIVE_SERVICE = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _DRIVE_SERVICE


def discover_sheets(
    env: dict[str, Any],
    owner: str,
    title_hint: str = "",
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Return new candidate sheets from the SunBiz account, newest first.
    Each item: {id, name, modified_time, mime_type}. Owner is the primary
    discriminator; title_hint + mimetype narrow to lead sheets."""
    svc = drive_service(env)
    q = f"'{owner}' in owners and trashed = false"
    hint = (title_hint or "").lower()
    refs: list[dict[str, Any]] = []
    page_token: Optional[str] = None
    fetched = 0
    while True:
        resp = (
            svc.files()
            .list(
                q=q,
                orderBy="modifiedTime desc",
                fields="nextPageToken, files(id,name,mimeType,modifiedTime)",
                pageSize=100,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = resp.get("files", []) or []
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
        fetched += len(files)
        page_token = resp.get("nextPageToken")
        if not page_token or fetched >= max_results:
            break
    return refs


def _download_xlsx(env: dict[str, Any], ref: dict[str, Any]) -> bytes:
    """Download a Drive file as .xlsx bytes. Google Sheets are EXPORTED to
    .xlsx; a native .xlsx is downloaded as-is."""
    from googleapiclient.http import MediaIoBaseDownload

    svc = drive_service(env)
    file_id = ref["id"]
    mime = ref.get("mime_type", "")
    if mime == SHEET_MIME:
        request = svc.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
    else:
        request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    return buf.getvalue()


def fetch_workbook(env: dict[str, Any], ref: dict[str, Any]):
    """Download a per-deal UW Sheet and return an openpyxl workbook (data_only)
    for uw_sheet_parser.parse_uw_sheet(). This is the PRIMARY path now (the
    source is per-deal FORM workbooks, not row tables)."""
    import openpyxl
    data = _download_xlsx(env, ref)
    return openpyxl.load_workbook(io.BytesIO(data), data_only=True)


def fetch_rows(env: dict[str, Any], ref: dict[str, Any]) -> list[dict[str, Any]]:
    """LEGACY row-table path (bulk MCA_Webforms exports). Kept for the
    --source-path test affordance; the live UW Sheet path uses fetch_workbook."""
    data = _download_xlsx(env, ref)
    with tempfile.TemporaryDirectory(prefix="sift_dl_") as td:
        out_path = Path(td) / "sheet.xlsx"
        out_path.write_bytes(data)
        return read_rows(out_path)
