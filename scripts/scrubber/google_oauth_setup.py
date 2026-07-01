"""google_oauth_setup.py — one-time: mint a Drive refresh token for the
Breeze identity (aiscrubbing@breezeadvance.com).

Run this ON A MACHINE WITH A BROWSER (your laptop) — it opens the Google
consent screen, you approve as aiscrubbing@breezeadvance.com, and it prints
the refresh token to paste into .env.agents. The VPS never needs a browser;
it just uses the printed token.

PREREQ in .env.agents (set these first):
    BREEZE_GOOGLE_CLIENT_ID=...
    BREEZE_GOOGLE_CLIENT_SECRET=...

INSTALL (one-time):
    <ceo-agent-venv>/bin/python -m pip install google-auth-oauthlib

RUN:
    <ceo-agent-venv>/bin/python scripts/scrubber/google_oauth_setup.py
    # → approve in the browser → copy the printed BREEZE_GOOGLE_REFRESH_TOKEN
    #   line into .env.agents (laptop AND VPS).

Scope: drive.readonly — enough to list + download/export the lead sheets.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

bootstrap_bravo_path()

# Read-only Drive access: covers files.list AND export/download of Google
# Sheets to .xlsx (what the scrubber's ingest does). No write scope needed.
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def main() -> int:
    from lib.secret_loader import load_env  # type: ignore

    env = load_env()
    cid = (env.get("BREEZE_GOOGLE_CLIENT_ID") or "").strip()
    csec = (env.get("BREEZE_GOOGLE_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        print(
            "ERROR: set BREEZE_GOOGLE_CLIENT_ID and BREEZE_GOOGLE_CLIENT_SECRET "
            "in .env.agents first, then re-run.",
            file=sys.stderr,
        )
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "ERROR: google-auth-oauthlib not installed. Run:\n"
            "  python -m pip install google-auth-oauthlib",
            file=sys.stderr,
        )
        return 1

    client_config = {
        "installed": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # access_type=offline + prompt=consent guarantees a refresh_token is issued
    # (Google omits it on re-auth unless you force consent).
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print(
            "No refresh token returned. Revoke the prior grant at "
            "https://myaccount.google.com/permissions and re-run.",
            file=sys.stderr,
        )
        return 1

    print("\n================ SUCCESS ================")
    print("Add this line to .env.agents (laptop AND VPS):\n")
    print(f"BREEZE_GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("\n========================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
