"""mca_lead_scrubber.py — the "Breeze UW Entry Sheet" automation.

A Solara-owned backend operations daemon for SunBiz (no separate agent
identity — this is Solara's automation; "Sift" is just the internal code
name for the scrubber engine). Surfaced in the Command Centre Automations
tab as "Breeze UW Entry Sheet" (Background Workers + Modules board).

Watches the shared Breeze/SunBiz Google Drive folder for new MCA web-form
lead sheets, scrubs each lead against config-driven underwriting criteria,
and writes the good ones to the `scrub_candidates` queue for Ezra's
approval. On approval (handled by the dashboard) a lead is created in the
SunBiz Command Centre at the `uw_sheet` stage via the bridge API, which
fires the autonomous follow-up lifecycle.

  Drive sheets ──discover──▶ parse (reuse import_mca_leads) ──scrub (scoring)
              ──stage──▶ scrub_candidates (pending_review) ──▶ [Ezra approves]
              ──▶ bridge create lead @uw_sheet ──▶ drip + stale-lead nurture

This daemon does NOT auto-push to the pipeline and does NOT send messages —
Ezra is the gate, and the drip engine owns sends.

CLI (mirrors extraction_consumer.py):
    python scripts/mca_lead_scrubber.py once     # one pass over new Drive sheets, exit
    python scripts/mca_lead_scrubber.py once --source-path X.xlsx --dry-run  # local test
    python scripts/mca_lead_scrubber.py loop --interval 120   # poll Drive forever
    python scripts/mca_lead_scrubber.py doctor   # creds / Drive / config check, exit

PM2 (Linux/VPS only — see ecosystem.config.js, IS_LINUX-gated):
    mca-lead-scrubber → loop --interval 120
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Bootstrap CEO-Agent shared infra onto sys.path (secret_loader, etc.).
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()

from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402

# Reuse the importer's parse/normalize machinery — do NOT re-implement.
from import_mca_leads import read_rows, map_row_to_lead_data  # noqa: E402

from scrubber import scoring, state as st, columns as cols  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Discovery is OWNER-based. The REAL source (verified 2026-06-30 as the Breeze
# identity) is per-deal "UW Sheet_<id>_<business>" Google Sheets owned by
# Breeze's submissions account — NOT bulk MCA_Webforms tables. Each file is ONE
# deal's underwriting workbook (tabs: "UW Sheet 2.5"/2.0/1.0 + Guidelines).
SHEET_OWNER = os.environ.get("SIFT_SHEET_OWNER", "Submissions@breezeadvance.com")
# Only the per-deal underwriting sheets (excludes the supporting PDFs/credit pulls).
SHEET_TITLE_HINT = os.environ.get("SIFT_SHEET_TITLE_HINT", "UW Sheet")

# ── PARSER READINESS GATE ────────────────────────────────────────────────
# The per-deal UW Sheet parser is PENDING CC's underwriting SOP, which defines
# the tab/version (e.g. "UW Sheet 2.5"), the field→metric map, and the scoring
# thresholds. Until that lands, tick() DISCOVERS sheets but REFUSES to parse or
# score them: the legacy row-table path (scrub_rows / columns / import_mca_leads)
# was built for bulk MCA_Webforms tables and does NOT fit the per-deal UW Sheet
# FORM — running it would silently produce garbage candidates. Flip to True only
# when the SOP-driven per-deal parser replaces that path. (doctor + discovery +
# the local --source-path test path are unaffected.)
UW_SHEET_PARSER_READY = os.environ.get("SIFT_PARSER_READY", "0") == "1"


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[breeze-uw {ts}] {msg}")


def _load_env() -> dict[str, str]:
    try:
        from lib.secret_loader import load_env  # type: ignore
        return load_env()
    except Exception as e:  # noqa: BLE001
        print(f"[sift] secret_loader failed, using os.environ: {e}", file=sys.stderr)
        return dict(os.environ)


def _client(env: dict[str, str]):
    url = (env.get("BRAVO_SUPABASE_URL") or env.get("SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        print("[sift] BRAVO_SUPABASE_URL / SERVICE_ROLE_KEY missing", file=sys.stderr)
        return None
    try:
        from supabase import create_client  # type: ignore
    except ImportError:
        print("[sift] supabase-py not installed (pip install supabase)", file=sys.stderr)
        return None
    try:
        return create_client(url, key)
    except Exception as e:  # noqa: BLE001
        print(f"[sift] supabase client error: {e}", file=sys.stderr)
        return None


# ── core: parse + scrub a list of raw rows ──────────────────────────────

def scrub_rows(
    rows: list[dict[str, Any]],
    cfg: dict[str, Any],
    source_tag: str,
    source_date_range: str = "",
    sb=None,
    state_obj: Optional[dict[str, Any]] = None,
    dedup_existing=None,
) -> list[dict[str, Any]]:
    """Map each raw row → normalized lead, score it, and return a list of
    scored-candidate dicts: {data, score_result, row_hash}. Rows already in
    the ledger (state_obj) or too sparse to map are skipped.

    `dedup_existing`, when provided as (emails,phones,businesses) sets,
    flags previously_submitted (crm_derived) and is used by push.py to skip
    leads already in the tenant. Here it only sets the prev-submitted flag."""
    out: list[dict[str, Any]] = []
    ps_cfg = cfg.get("previously_submitted", {})
    ps_source = (ps_cfg.get("source") or "off").lower()
    ps_aliases = [a.lower() for a in (ps_cfg.get("sheet_column_aliases") or [])]

    for raw in rows:
        raw = cols.normalize_row(raw)  # live-sheet schema → importer keys
        data = map_row_to_lead_data(raw, source_tag, source_date_range)
        if not data:
            continue
        data["stage"] = "uw_sheet"  # importer hardcodes hot_lead; Sift overrides

        # Resolve previously_submitted per config.
        prev = False
        if ps_source == "sheet_column":
            for k, v in raw.items():
                if str(k).lower() in ps_aliases and str(v).strip().lower() in ("yes", "y", "true", "1"):
                    prev = True
                    break
        elif ps_source == "crm_derived" and dedup_existing is not None:
            emails, phones, businesses = dedup_existing
            e = (data.get("email") or "").strip().lower()
            p = (data.get("phone") or "").strip()
            c = (data.get("company") or data.get("business_name") or "").strip().lower()
            s = (data.get("state") or "").strip().lower()
            if (e and e in emails) or (p and p in phones) or (c and f"{c}|{s}" in businesses):
                prev = True
        if prev:
            data["previously_submitted"] = True

        h = st.row_hash(data)
        if state_obj is not None and st.is_row_seen(state_obj, h):
            continue

        result = scoring.score_lead(data, cfg)
        # Stamp scrub output onto the lead data (audit trail).
        data["score"] = result["score"]
        data["scrub_tier"] = result["tier"]
        data["scrub_reasons"] = result["reasons"]
        data["scrub_decline_reason"] = result["decline_reason"]
        if result.get("leverage_pct") is not None:
            data["leverage_ratio"] = result["leverage_pct"]
        data["scrubbed_at"] = datetime.now(timezone.utc).isoformat()
        data["scoring_config_version"] = cfg.get("version")

        out.append({"data": data, "score_result": result, "row_hash": h})
    return out


def _histogram(candidates: list[dict[str, Any]]) -> str:
    by_tier = Counter(c["score_result"]["tier"] for c in candidates)
    n = len(candidates) or 1
    parts = []
    for tier in ("good", "review", "bad"):
        c = by_tier.get(tier, 0)
        parts.append(f"{tier}={c} ({100*c//n}%)")
    return "  ".join(parts)


# ── tick (loop mode — Drive discovery) ──────────────────────────────────

def tick(sb, env: dict[str, str], cfg: dict[str, Any], state_obj: dict[str, Any]) -> int:
    """One pass: discover new Drive sheets, scrub, stage candidates for Ezra.
    Returns the number of candidates staged. Drive ingest + candidate push
    are wired in Phase 2/3 (ingest.py / push.py); imported lazily so the
    local-file path and `doctor` work before they land."""
    try:
        from scrubber import ingest  # Phase 2
    except Exception as e:  # noqa: BLE001
        _log(f"ingest module not available yet ({e}) — Drive discovery skipped")
        return 0

    sheets = ingest.discover_sheets(env, owner=SHEET_OWNER, title_hint=SHEET_TITLE_HINT)

    # PARSER READINESS GATE — discovery works, but the per-deal UW Sheet parser
    # is pending the SOP (see UW_SHEET_PARSER_READY). Refuse to parse/score here
    # rather than silently mis-parse a per-deal FORM with the legacy row-table
    # path. doctor + discovery still prove auth/access; this just stops garbage.
    if not UW_SHEET_PARSER_READY:
        _log(
            f"discovered {len(sheets)} UW Sheet(s) — per-deal parser is PENDING the SOP; "
            "not parsing/scoring (set SIFT_PARSER_READY=1 once the SOP parser lands)."
        )
        return 0

    staged_total = 0
    for ref in sheets:
        if st.is_file_processed(state_obj, ref["id"], ref.get("modified_time")):
            continue
        try:
            rows = ingest.fetch_rows(env, ref)
        except Exception as e:  # noqa: BLE001
            _log(f"fetch failed for {ref.get('name', ref['id'])}: {e}")
            continue

        dedup_existing = _existing_keys(sb)
        source_tag = f"sift_scrub_{ref.get('name', ref['id'])}"
        candidates = scrub_rows(
            rows, cfg, source_tag, sb=sb, state_obj=state_obj, dedup_existing=dedup_existing
        )

        push_result = _stage_candidates(sb, env, cfg, ref, candidates, dedup_existing)
        staged = len(push_result["inserted"])
        staged_total += staged
        # Mark seen ONLY rows fully handled this tick: inserted, dedup-skipped,
        # or classified bad. Rows whose INSERT failed stay unseen so the next
        # tick retries them — never silently drop a lead on a transient DB error.
        bad_hashes = {c["row_hash"] for c in candidates if c["score_result"]["tier"] == "bad"}
        for h in (push_result["inserted"] | push_result["skipped"] | bad_hashes):
            st.mark_row_seen(state_obj, h)
        # Mark the FILE processed only when nothing failed; otherwise leave it so
        # the next tick re-scans and retries the failed rows (row-level dedup
        # skips the already-done ones).
        if not push_result["failed"]:
            st.mark_file_processed(state_obj, ref["id"], ref.get("modified_time"), len(rows), staged)
        st.save_state(st.strip_runtime(state_obj))
        failed_note = f" (FAILED {len(push_result['failed'])} — will retry)" if push_result["failed"] else ""
        _log(f"sheet {ref.get('name', ref['id'])}: {len(rows)} rows → {_histogram(candidates)} → staged {staged}{failed_note}")
    return staged_total


def _existing_keys(sb):
    """Reuse the importer's dedup keyset read for crm_derived prev-submitted
    + push dedup. Returns (emails, phones, businesses) or None on failure."""
    if sb is None:
        return None
    try:
        from import_mca_leads import fetch_existing_keys
        return fetch_existing_keys(sb, SUNBIZ_TENANT_ID)
    except Exception as e:  # noqa: BLE001
        _log(f"existing-keys read failed: {e}")
        return None


def _stage_candidates(sb, env, cfg, ref, candidates: list[dict[str, Any]], dedup_existing=None) -> int:
    """Write good/review candidates to scrub_candidates for Ezra's approval."""
    from scrubber import push
    return push.stage_candidates(sb, env, cfg, ref, candidates, dedup_existing=dedup_existing)


# ── once / local-file path ──────────────────────────────────────────────

def run_local_file(source_path: Path, cfg: dict[str, Any], dry_run: bool, limit: Optional[int]) -> int:
    """Phase-1 testable path: scrub a local xlsx/csv and print the tier
    histogram. With --dry-run, performs no writes."""
    rows = read_rows(source_path)
    if limit:
        rows = rows[:limit]
    _log(f"parsed {len(rows)} rows from {source_path.name}")
    candidates = scrub_rows(rows, cfg, source_tag=f"sift_local_{source_path.stem}")
    _log(f"scrubbed {len(candidates)} mappable leads → {_histogram(candidates)}")
    # Show a few examples per tier for eyeballing.
    shown = Counter()
    for c in candidates:
        tier = c["score_result"]["tier"]
        if shown[tier] >= 3:
            continue
        shown[tier] += 1
        r = c["score_result"]
        name = c["data"].get("company") or c["data"].get("name") or "(no name)"
        why = r["decline_reason"] if r.get("prefilter_decline") else ", ".join(r["reasons"][:5])
        _log(f"  [{tier:6}] score={r['score']:>3} {name[:40]:40} :: {why}")
    if dry_run:
        _log("DRY RUN — no writes performed")
    return len(candidates)


# ── doctor ───────────────────────────────────────────────────────────────

def doctor(env: dict[str, str]) -> None:
    _log("── Breeze UW Entry Sheet (Solara) doctor ──")
    sb = _client(env)
    print(f"  supabase client:            {'ok' if sb else 'MISSING'}")
    print(f"  SunBiz tenant_id:           {SUNBIZ_TENANT_ID}")
    print(f"  CEO-Agent root (BRAVO):     {BRAVO_ROOT or 'NOT FOUND'}")

    # scoring config
    cfg = scoring.load_config()
    print(f"  scoring config version:     {cfg.get('version')}  (gate={cfg.get('gate', {}).get('mode')})")

    # bridge push creds (Phase 3 push path)
    hmac_ok = bool((env.get("OASIS_OUTBOUND_HMAC_SECRET") or "").strip())
    base_url = (env.get("OASIS_DASHBOARD_URL") or env.get("PUBLIC_APP_URL") or "https://oasisai.work").rstrip("/")
    print(f"  bridge HMAC secret:         {'yes' if hmac_ok else 'NO (push will fail)'}")
    print(f"  dashboard base URL:         {base_url}")

    # Breeze email identity (IMAP/SMTP) — OPTIONAL, unused in v1 (Drive-only
    # ingest; the daemon never sends). Presence only, never the address.
    gmail_user = (env.get("GMAIL_USER_BREEZE") or env.get("AISCRUBBING_GMAIL_USER") or "").strip()
    gmail_pw = bool((env.get("GMAIL_APP_PASSWORD_BREEZE") or env.get("AISCRUBBING_GMAIL_APP_PASSWORD") or "").strip())
    print(f"  Breeze email (optional):    user={'set' if gmail_user else 'unset'}  app_pw={'yes' if gmail_pw else 'no'}")

    # Breeze Drive identity (aiscrubbing@breezeadvance.com) — THE ingestion auth.
    from scrubber import ingest as _ingest
    breeze_missing = _ingest._missing_creds(env)
    print(f"  Breeze Drive creds:         {'all set' if not breeze_missing else 'MISSING: ' + ', '.join(breeze_missing)}")
    print(f"  Drive source owner:         {SHEET_OWNER}")
    print(f"  sheet title hint:           {SHEET_TITLE_HINT}")
    if breeze_missing:
        print("  Drive access:               SKIPPED — set BREEZE_GOOGLE_* in .env.agents "
              "(refresh token via scripts/scrubber/google_oauth_setup.py)", file=sys.stderr)
    else:
        try:
            found = _ingest.discover_sheets(env, owner=SHEET_OWNER, title_hint=SHEET_TITLE_HINT, max_results=100)
            print("  Drive access:               OK (authed as Breeze)")
            print(f"  candidate sheets found:     {len(found)}")
            for r in found[:5]:
                print(f"      • {r['name']}  ({r.get('modified_time')})")
            if not found:
                print("  ⚠️  0 sheets found — confirm SunBiz shared the lead-sheet folder with "
                      "aiscrubbing@breezeadvance.com.", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  Drive access:               FAIL — {e}", file=sys.stderr)

    print(f"  ledger path:                {st.LEDGER_PATH}")


# ── main ─────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sift — MCA lead scrubber")
    parser.add_argument("mode", choices=["once", "loop", "doctor"], nargs="?", default="once")
    parser.add_argument("--interval", type=int, default=120, help="seconds between Drive polls (loop)")
    parser.add_argument("--source-path", help="local .xlsx/.csv to scrub (test path; bypasses Drive)")
    parser.add_argument("--dry-run", action="store_true", help="no writes (with --source-path)")
    parser.add_argument("--limit", type=int, default=None, help="cap rows (smoke testing)")
    args = parser.parse_args(argv)

    env = _load_env()
    cfg = scoring.load_config()

    if args.mode == "doctor":
        doctor(env)
        return 0

    # Local-file test path (works without Drive/push — Phase 1).
    if args.source_path:
        src = Path(args.source_path).expanduser().resolve()
        if not src.exists():
            print(f"ERROR: source not found: {src}", file=sys.stderr)
            return 2
        run_local_file(src, cfg, args.dry_run, args.limit)
        return 0

    sb = _client(env)
    if sb is None:
        return 1

    state_obj = st.load_state()

    if args.mode == "once":
        n = tick(sb, env, cfg, state_obj)
        _log(f"once: staged {n} candidate(s)")
        return 0

    # loop
    if not st.acquire_claim():
        print("[sift] another Sift instance holds the claim — exiting", file=sys.stderr)
        return 1
    _log(f"loop: polling Drive every {args.interval}s (gate={cfg.get('gate', {}).get('mode')})")
    while True:
        try:
            st.refresh_claim()
            tick(sb, env, cfg, state_obj)
        except Exception as e:  # noqa: BLE001
            print(f"[sift] tick error: {e}", file=sys.stderr)
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    sys.exit(main())
