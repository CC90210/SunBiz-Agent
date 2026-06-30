"""scrubber — the "Sift" MCA Lead Scrubber package.

Sift watches the shared Breeze/SunBiz Google Drive for new MCA web-form
lead sheets, scores ("scrubs") each lead against config-driven underwriting
criteria, and — after Ezra's approval — injects the good deals into the
SunBiz Agent Command Centre at the `uw_sheet` lead stage.

Modules:
  ingest  — pluggable sheet sources (DriveSource primary). [Phase 2]
  scoring — config-driven deterministic + (optional) Claude scrubber.
  push    — Ezra-approval gate + bridge-API create (emits the lifecycle
            event so the uw_sheet drip + stale-lead nudges fire). [Phase 3]
  state   — idempotency ledger (processed Drive file IDs + row hashes).

Entrypoint daemon: scripts/mca_lead_scrubber.py (once|loop|doctor).

The parsing/dedup machinery is REUSED from scripts/import_mca_leads.py
(map_row_to_lead_data, fetch_existing_keys, parse_current_funders, …) —
this package does NOT re-implement column normalization.
"""
