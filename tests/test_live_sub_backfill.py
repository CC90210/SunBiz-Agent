from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scrubber.backfill_live_sub_applications import select_leads  # noqa: E402


def test_default_backfill_only_selects_leads_without_application() -> None:
    rows = [
        {"id": "missing", "application_id": None, "transferred_at": None},
        {"id": "visible", "application_id": "app-1", "transferred_at": None},
        {
            "id": "hidden", "application_id": "app-2",
            "created_at": "2026-07-29T16:07:35+00:00",
            "transferred_at": "2026-07-29T16:07:36.8+00:00",
        },
    ]
    assert [r["id"] for r in select_leads(rows, repair_hidden=False)] == ["missing"]


def test_hidden_repair_requires_both_link_and_transfer_marker() -> None:
    rows = [
        {"id": "missing", "application_id": None, "transferred_at": None},
        {"id": "visible", "application_id": "app-1", "transferred_at": None},
        {
            "id": "hidden", "application_id": "app-2",
            "created_at": "2026-07-29T16:07:35+00:00",
            "transferred_at": "2026-07-29T16:07:36.8+00:00",
        },
        {
            "id": "manual", "application_id": "app-3",
            "created_at": "2026-07-29T16:07:35+00:00",
            "transferred_at": "2026-07-29T17:00:00+00:00",
        },
    ]
    assert [r["id"] for r in select_leads(rows, repair_hidden=True)] == ["hidden"]
