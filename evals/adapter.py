"""SunBiz-Agent eval adapter — exercises the repo's REAL code paths in dry-run.

Five suites, four wired to real SunBiz functions (the fifth is the honest
mistakes backlog). None of these are reimplementations — they import and call
the same functions the live daemons (sequence-runner, underwriting orchestrator,
email blast) call.

  underwriting → scripts/underwriting/debt_detector.summarize_debt
                 Pure cross-statement aggregation: groups identified_loan_payments
                 by lender, normalizes by frequency, computes debt-to-revenue ratio
                 and the stack-classification one-liner. No network, no LLM, no DB.

  templating   → scripts/sequence_runner.render_template
                 The mustache {{token}} renderer that produces every drip email/SMS
                 body before send_gateway ships it. Pure; the module-level
                 _bravo_bootstrap probe returns None offline and is harmless.

  routing      → scripts/sunbiz_constants.resolve_brand
                 tenant_id -> send_gateway BRAND_IDENTITY key. The function that
                 decides whether outbound carries the SunBiz CASL footer
                 (submissions@sunbizfunding.com) or the OASIS one. Pure.

  compliance   → scripts/email_blast._personalise + check_unsubscribe
                 CAN-SPAM footer injection (unsubscribe URL + physical address) and
                 the suppression-list gate. The CSV is repointed at a fixture path so
                 check_unsubscribe runs deterministically offline — same network-
                 boundary patch the CEO send_policy adapter uses.

  mistakes     → mined from memory/MISTAKES.md (source: mistake). Until each is
                 wired to a deterministic check, it scores rubric->needs-model
                 (honest pending, never a fake pass).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ── module loaders (by path so subpackage + hyphen-free import is reliable) ──

def _load(mod_name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(mod_name, str(REPO / rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _meta(cd: Path) -> dict:
    m, f = {}, cd / "meta.yaml"
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ":" in ln and not ln.strip().startswith("#"):
                k, _, v = ln.partition(":")
                m[k.strip()] = v.strip()
    return m


def _read_fixture_json(cd: Path, name: str):
    p = cd / "fixtures" / name
    return json.loads(p.read_text(encoding="utf-8"))


# ── underwriting: debt_detector.summarize_debt (pure) ──

def _underwriting(cd: Path) -> dict:
    dd = _load("_sb_debt_detector", "scripts/underwriting/debt_detector.py")
    statements = _read_fixture_json(cd, "statements.json")
    out = dd.summarize_debt(statements)
    # Classify the D/R band the same way the function's own summary string does,
    # so a case can assert the underwriter-facing call without string matching.
    dr = out.get("debt_to_revenue_ratio")
    if dr is None:
        band = "unknown"
    elif dr > 0.5:
        band = "heavy"
    elif dr > 0.2:
        band = "moderate"
    else:
        band = "light"
    return {
        "lender_count": out["lender_count"],
        "monthly_debt_service": out["monthly_debt_service"],
        "debt_to_revenue_ratio": dr,
        "dr_band": band,
        "total_nsf_events": out["total_nsf_events"],
        "summary": out["summary"],
        "top_lender": out["lenders"][0]["lender_hint"] if out["lenders"] else None,
    }


# ── templating: sequence_runner.render_template (pure) ──

def _templating(cd: Path) -> dict:
    sr = _load("_sb_sequence_runner", "scripts/sequence_runner.py")
    spec = _read_fixture_json(cd, "render.json")
    kwargs = {}
    if "default" in spec:
        kwargs["default"] = spec["default"]
    rendered = sr.render_template(spec["template"], spec.get("ctx") or {}, **kwargs)
    return {"rendered": rendered}


# ── routing: sunbiz_constants.resolve_brand (pure) ──

def _routing(cd: Path) -> dict:
    import sunbiz_constants as sc  # local to scripts/, already on sys.path
    tenant_id = (cd / "task.md").read_text(encoding="utf-8").strip() or None
    if tenant_id in ("none", "null", ""):
        tenant_id = None
    return {"brand": sc.resolve_brand(tenant_id)}


# ── compliance: email_blast footer injection + suppression gate ──

def _compliance(cd: Path) -> dict:
    eb = _load("_sb_email_blast", "scripts/email_blast.py")
    # FS-boundary patch: pre-seed the process-wide suppression cache directly
    # from the fixture CSV (if any) and mark it loaded, so check_unsubscribe
    # never touches disk or auto-creates a CSV. Same idea as the CEO
    # send_policy adapter's offline patch — but read-only, no side effects.
    import csv as _csv
    seeded: set[str] = set()
    fixture_csv = cd / "fixtures" / "unsubscribes.csv"
    if fixture_csv.exists():
        with fixture_csv.open(newline="", encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                e = (row.get("email") or "").strip().lower()
                if e:
                    seeded.add(e)
    eb._unsub_cache = seeded
    eb._unsub_cache_loaded = True  # short-circuits _load_unsub_cache → no disk I/O

    task = (cd / "task.md").read_text(encoding="utf-8")
    lines = [l for l in task.splitlines() if not l.strip().startswith("#")]
    email = (lines[0] if lines else "").strip()

    # Suppression gate (deterministic against the fixture CSV).
    suppressed = eb.check_unsubscribe(email) if email else False

    # CAN-SPAM footer injection on a template body that uses the real tokens.
    template_html = (
        "Hi {{first_name}} at {{business_name}}. "
        "<a href=\"{{unsubscribe_url}}\">Unsubscribe</a> {{physical_address}}"
    )
    rendered = eb._personalise(
        template_html,
        {"email": email or "lead@example.test", "first_name": "Owner", "business_name": "Acme LLC"},
        "eval_campaign",
    )
    low = rendered.lower()
    return {
        "action": "suppress" if suppressed else "send",
        "has_unsubscribe_url": "unsubscribe?" in low and "email=" in low,
        "has_physical_address": "miami" in low and "fl" in low,
        "no_loan_word": "loan" not in low,  # MCA compliance: never say "loan"
        "rendered": rendered,
    }


# ── mistakes: mined backlog (honest needs-model until each is wired) ──

def _mistakes(_cd: Path) -> dict:
    return {"verdict": "needs-model"}


DISPATCH = {
    "underwriting": _underwriting,
    "templating": _templating,
    "routing": _routing,
    "compliance": _compliance,
    "mistakes": _mistakes,
}


def run_case(case_dir) -> dict:
    cd = Path(case_dir)
    suite = _meta(cd).get("suite") or cd.parent.name
    fn = DISPATCH.get(suite)
    if fn is None:
        raise NotImplementedError(f"no adapter wired for suite {suite!r}")
    return fn(cd)
