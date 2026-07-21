"""tps_probe.py — diagnose the TruePeopleSearch contact-enrichment path.

WHY THIS EXISTS
uw_lead_enricher._truepeople_search() returns None on every failure mode —
no BRAVO_ROOT, missing owner/city, fetch error, captcha page, zero matches — so
the daemon can only ever log `contact_found: 0` with no way to tell which of
those happened. This probe takes that path apart into stages and reports each
one, so "TPS isn't working" becomes an answerable question.

It is READ-ONLY: it never writes to Supabase and never mutates a lead.

Three modes
  --reachability   Can this host talk to TPS at all? Classifies the response as
                   ok / captcha / blocked / http error / timeout. This is the
                   check that matters first: as of 2026-07-21 TPS returns HTTP
                   403 with a "Captcha Challenge" page to this VPS's datacenter
                   IP, which no amount of parsing work can fix.
  --lookup         Run the REAL enricher path end to end for one merchant,
                   printing every stage: the URL built, the fetch result, how
                   much text came back, and what _extract_contacts pulled out.
                   Source the merchant from --lead-id, or pass --name/--city/
                   --state directly.
  --parse-only     Exercise the extraction + confidence logic against saved text
                   (--fixture FILE) or a built-in synthetic TPS result. Proves
                   the parser works independently of network access, so a real
                   lookup returning nothing can be attributed to the fetch
                   rather than the regexes.

Examples
  python scripts/tps_probe.py --reachability
  python scripts/tps_probe.py --parse-only
  python scripts/tps_probe.py --lookup --name "Dana Rivera" --city Austin --state TX
  python scripts/tps_probe.py --lookup --lead-id <uuid>
  python scripts/tps_probe.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()

import uw_lead_enricher as E  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Markers that identify an anti-automation interstitial rather than a real
# result page. TPS serves this with HTTP 403 to datacenter IPs.
CAPTCHA_MARKERS = ("captcha challenge", "px-captcha", "are you a human", "cf-challenge", "just a moment")

OK, WARN, BAD = "PASS", "WARN", "FAIL"


def _mark(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))


def build_url(name: str, city: str = "", state: str = "") -> str:
    """The exact URL uw_lead_enricher._truepeople_search() constructs."""
    city_state = " ".join(p for p in (city, state) if p)
    return (
        "https://www.truepeoplesearch.com/results"
        f"?name={quote_plus(name)}&citystatezip={quote_plus(city_state)}"
    )


# ── mode 1: reachability ────────────────────────────────────────────────────

def reachability(name: str, city: str, state: str, timeout: int = 25) -> str:
    """Classify what TPS actually returns to this host. Returns a verdict slug."""
    url = build_url(name, city, state)
    print("\n== REACHABILITY ==")
    print(f"  url: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    status: Optional[int] = None
    body = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = e.read(400_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
    except Exception as e:  # noqa: BLE001
        _mark(BAD, "network", f"{type(e).__name__}: {e}")
        print("\n  VERDICT: unreachable — DNS/egress/timeout, not an anti-bot block.")
        return "unreachable"

    low = body.lower()
    hit = next((m for m in CAPTCHA_MARKERS if m in low), None)
    print(f"  http status: {status} | body: {len(body):,} chars")

    if hit:
        _mark(BAD, "captcha interstitial", f"matched {hit!r}")
        print(
            "\n  VERDICT: CAPTCHA-BLOCKED.\n"
            "  TPS is serving an anti-automation challenge to this host's IP, not a\n"
            "  result page. The enricher cannot extract numbers from this and never\n"
            "  will from this address — the block is on the network origin, so a\n"
            "  headless browser from this same VPS gets the identical challenge.\n"
            "  Clearing it would require a CAPTCHA-solving service or residential\n"
            "  proxy rotation, i.e. circumventing an access control.\n"
            "  Use a credentialed skip-trace API instead (CLEAR, Endato, BatchData,\n"
            "  Whitepages Pro) — those return structured data under a contract."
        )
        return "captcha"

    if status != 200:
        _mark(BAD, "http error", str(status))
        print(f"\n  VERDICT: HTTP {status} — not a captcha page; inspect the body.")
        return "http_error"

    _mark(OK, "reachable", "no captcha markers")
    has_results = "person" in low or "phone" in low
    _mark(OK if has_results else WARN, "result-page markers",
          "looks like a result page" if has_results else "200 but no result markers — layout may have changed")
    print("\n  VERDICT: REACHABLE — run --lookup to test extraction.")
    return "ok"


# ── mode 2: live lookup through the real enricher path ──────────────────────

SYNTHETIC = """
Dana Rivera, Age 41
Lives in Austin, TX
Phone Numbers: (512) 555-0142 - Wireless
Previous: 512-555-0199
Email: dana.rivera@example.com
Current Address: 100 Example St, Austin, TX 78701
"""


def lookup(data: dict[str, Any], timeout: int = 75) -> str:
    """Run the genuine _truepeople_search path, narrating each stage."""
    print("\n== LIVE LOOKUP (real enricher path) ==")
    owner = data.get("owner_name") or data.get("contact_name") or data.get("name")
    city = data.get("owner_address_city") or data.get("business_city") or data.get("city")
    state = (
        data.get("owner_address_state") or data.get("business_state_code")
        or data.get("state_code") or data.get("state")
    )
    print(f"  merchant: name={owner!r} city={city!r} state={state!r}")

    # Stage 1 — the guard that silently returns None in the daemon.
    if not BRAVO_ROOT:
        _mark(BAD, "BRAVO_ROOT", "unresolved — _truepeople_search returns None immediately")
        return "no_bravo_root"
    _mark(OK, "BRAVO_ROOT", str(BRAVO_ROOT))
    if not owner or not (city or state):
        _mark(BAD, "input guard", "needs an owner name AND a city or state — daemon skips this lead")
        return "insufficient_input"
    _mark(OK, "input guard", "sufficient")

    script = Path(BRAVO_ROOT) / "scripts" / "research_fetch.py"
    if not script.exists():
        _mark(BAD, "research_fetch.py", f"missing at {script}")
        return "no_fetcher"
    _mark(OK, "research_fetch.py", str(script))

    # Stage 2 — the fetch.
    url = build_url(str(owner), str(city or ""), str(state or ""))
    print(f"  url: {url}")
    raw = E._run_json([sys.executable, str(script), url, "--json", "--min-chars", "200"], timeout=timeout)
    if not raw.get("ok"):
        _mark(BAD, "fetch", str(raw.get("error"))[:300])
        print("\n  VERDICT: FETCH FAILED — the daemon would log contact_found: 0 with no reason.")
        return "fetch_failed"
    text = raw.get("text") or ""
    _mark(OK, "fetch", f"{len(text):,} chars from {raw.get('final_url') or url}")
    low = text.lower()
    if any(m in low for m in CAPTCHA_MARKERS):
        _mark(BAD, "content", "captcha interstitial, not results")
        print("\n  VERDICT: CAPTCHA-BLOCKED (see --reachability).")
        return "captcha"

    # Stage 3 — extraction.
    found = E._extract_contacts(text, raw.get("final_url") or url, "truepeoplesearch", data)
    return _report_extraction(found, text)


def _report_extraction(found: dict[str, Any], text: str) -> str:
    phone = found.get("phone")
    email = found.get("email")
    _mark(OK if phone else WARN, "phone",
          f"{phone} (confidence {found.get('phone_confidence')})" if phone else "none extracted")
    _mark(OK if email else WARN, "email",
          f"{email} (confidence {found.get('email_confidence')})" if email else "none extracted")
    all_phones = [m.group(0) for m in E.PHONE_RE.finditer(text)]
    if all_phones:
        print(f"  all phone-shaped matches in text ({len(all_phones)}): {all_phones[:8]}")
    if phone:
        print("\n  VERDICT: NUMBER FOUND — this is the 'most probable number' case.")
        return "found"
    print("\n  VERDICT: NO NUMBER — text came back but carried no usable phone.")
    return "not_found"


# ── mode 3: offline parser test ─────────────────────────────────────────────

def parse_only(fixture: Optional[str]) -> str:
    """Test extraction + confidence WITHOUT the network, so a failing live
    lookup can be blamed on the fetch rather than the regexes."""
    print("\n== PARSE-ONLY (no network) ==")
    if fixture:
        text = Path(fixture).read_text(encoding="utf-8", errors="replace")
        _mark(OK, "fixture", f"{fixture} ({len(text):,} chars)")
    else:
        text = SYNTHETIC
        _mark(OK, "fixture", "built-in synthetic TPS result")
    data = {
        "owner_name": "Dana Rivera",
        "business_name": "Testco LLC",
        "owner_address_city": "Austin",
        "owner_address_state": "TX",
    }
    found = E._extract_contacts(text, "https://www.truepeoplesearch.com/results", "truepeoplesearch", data)
    verdict = _report_extraction(found, text)
    if not fixture:
        # Self-check: the synthetic fixture MUST yield a number. If it doesn't,
        # the extraction layer is broken independently of any network issue.
        ok = found.get("phone") is not None
        _mark(OK if ok else BAD, "self-check",
              "extraction layer healthy" if ok else "extraction layer BROKEN on known-good input")
        if not ok:
            return "parser_broken"
    return verdict


# ── lead sourcing ───────────────────────────────────────────────────────────

def load_lead(lead_id: str) -> dict[str, Any]:
    env = E._load_env()
    sb = E._client(env)
    if sb is None:
        raise SystemExit("supabase client unavailable (check BRAVO_SUPABASE_* secrets)")
    res = sb.table("tenant_records").select("data").eq("id", lead_id).maybe_single().execute()
    if not res or not res.data:
        raise SystemExit(f"lead {lead_id} not found")
    return res.data.get("data") or {}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Diagnose the TruePeopleSearch enrichment path (read-only).")
    ap.add_argument("--reachability", action="store_true", help="can this host reach TPS, or is it captcha-blocked")
    ap.add_argument("--lookup", action="store_true", help="run the real enricher path for one merchant")
    ap.add_argument("--parse-only", action="store_true", help="test extraction against saved/synthetic text")
    ap.add_argument("--all", action="store_true", help="run all three modes")
    ap.add_argument("--lead-id", help="source the merchant from a tenant_records lead")
    ap.add_argument("--name", default="John Smith")
    ap.add_argument("--city", default="Austin")
    ap.add_argument("--state", default="TX")
    ap.add_argument("--fixture", help="file of saved TPS page text for --parse-only")
    ap.add_argument("--timeout", type=int, default=75)
    args = ap.parse_args(argv)

    if not (args.reachability or args.lookup or args.parse_only or args.all):
        ap.print_help()
        return 2

    data: dict[str, Any]
    if args.lead_id:
        data = load_lead(args.lead_id)
        print(f"lead {args.lead_id}: {data.get('business_name') or data.get('owner_name')}")
    else:
        data = {"owner_name": args.name, "owner_address_city": args.city, "owner_address_state": args.state}

    verdicts: dict[str, str] = {}
    if args.parse_only or args.all:
        verdicts["parse"] = parse_only(args.fixture)
    if args.reachability or args.all:
        verdicts["reachability"] = reachability(
            str(data.get("owner_name") or args.name),
            str(data.get("owner_address_city") or args.city or ""),
            str(data.get("owner_address_state") or args.state or ""),
            timeout=min(args.timeout, 30),
        )
    if args.lookup or args.all:
        verdicts["lookup"] = lookup(data, timeout=args.timeout)

    print("\n== SUMMARY ==")
    for k, v in verdicts.items():
        print(f"  {k:14} {v}")
    print(json.dumps({"verdicts": verdicts}))
    # Non-zero when the pipeline cannot deliver a number, so this can gate CI.
    blocked = {"captcha", "unreachable", "fetch_failed", "parser_broken", "no_fetcher", "no_bravo_root"}
    return 1 if any(v in blocked for v in verdicts.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
