"""SunBiz's daemons act on SunBiz's rows only.

These daemons run on SunBiz's VPS with a service-role client that sees every
tenant, so a query without a tenant filter reads (and claims) every company's
rows. Each test pins one place that used to reach past SunBiz:

  - cold_outreach_runner: promote and fetch had no tenant filter, and
    resolve_brand() branded every other tenant's campaign as OASIS.
  - sequence_runner: enrollment acted on every tenant's agent_events, and
    execution claimed every tenant's due rows.
  - lender_response_classifier: an empty tenant constant dropped the filter.
  - shop_out_sender: SunBiz's cron runs `once` with no --tenant-id, and the
    None default claimed every tenant's pending threads.
  - sentinel: the pause event imported a module path that does not exist,
    so pauses were written but never announced.

No network and no database: a recording fake stands in for the client.
"""
from __future__ import annotations

import functools
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sunbiz_constants import SUNBIZ_TENANT_ID, resolve_brand  # noqa: E402

OTHER_TENANT = "00000000-0000-0000-0000-000000000000"


@functools.lru_cache(maxsize=None)
def _mod(name: str):
    """Import a daemon script by path, once, under a private module name."""
    spec = importlib.util.spec_from_file_location(f"_sbonly_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _quiet(monkeypatch, mod) -> list[str]:
    """Keep the daemon's log lines in memory instead of state/*.log."""
    lines: list[str] = []
    monkeypatch.setattr(mod, "_log", lines.append)
    return lines


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records every builder call; execute() returns the canned rows."""

    def __init__(self, fake: "FakeSupabase", name: str):
        self.fake = fake
        self.name = name
        self.calls: list[tuple] = []
        fake.queries.append(self)

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)

        def _record(*args, **_kwargs):
            self.calls.append((attr,) + args)
            return self

        return _record

    @property
    def not_(self):
        self.calls.append(("not_",))
        return self

    def execute(self):
        return _Result(list(self.fake.rows.get(self.name, [])))

    def has(self, *call) -> bool:
        return call in self.calls


class FakeSupabase:
    def __init__(self, rows: dict | None = None):
        self.rows = rows or {}
        self.queries: list[_Query] = []

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, name: str, params: dict) -> _Query:
        q = _Query(self, f"rpc:{name}")
        q.calls.append(("rpc", params))
        return q

    def on(self, table: str) -> list[_Query]:
        return [q for q in self.queries if q.name == table]


def _recorder(log: list, name: str, ret=None):
    def _fn(*args, **_kwargs):
        log.append((name, args))
        return ret

    return _fn


# ── routing ─────────────────────────────────────────────────────────


def test_resolve_brand_names_sunbiz_and_nobody_else():
    assert resolve_brand(SUNBIZ_TENANT_ID) == "sunbiz"
    # It used to answer "oasis" here, which would have mailed another
    # company's leads from SunBiz's box under OASIS's name.
    assert resolve_brand(OTHER_TENANT) is None
    assert resolve_brand(None) is None
    assert resolve_brand("") is None


# ── (a) cold_outreach_runner ────────────────────────────────────────


def test_cold_outreach_promotes_only_sunbiz_drafts(monkeypatch):
    cor = _mod("cold_outreach_runner")
    _quiet(monkeypatch, cor)
    sb = FakeSupabase()
    cor._promote_scheduled_campaigns(sb)
    (promote,) = sb.on("cold_outreach_campaigns")
    assert promote.has("update", {"status": "queued"})
    assert promote.has("eq", "tenant_id", SUNBIZ_TENANT_ID)


def test_cold_outreach_fetches_only_sunbiz_campaigns(monkeypatch):
    cor = _mod("cold_outreach_runner")
    _quiet(monkeypatch, cor)
    sb = FakeSupabase()
    monkeypatch.setattr(cor, "_supabase", lambda: sb)
    monkeypatch.setattr(cor, "_send_gateway_fn", lambda: (lambda *a, **k: None))
    assert cor.tick() == 0
    fetch = [q for q in sb.on("cold_outreach_campaigns")
             if q.has("in_", "status", ["queued", "sending"])]
    assert len(fetch) == 1
    assert fetch[0].has("eq", "tenant_id", SUNBIZ_TENANT_ID)


def test_cold_outreach_refuses_another_tenants_campaign(monkeypatch):
    cor = _mod("cold_outreach_runner")
    lines = _quiet(monkeypatch, cor)
    sb = FakeSupabase()
    sent: list = []
    campaign = {
        "id": "camp-other", "tenant_id": OTHER_TENANT, "status": "queued",
        "channel": "email", "message_body": "Hello", "subject": "Hi",
        "daily_cap": 50, "sent_count": 0, "failed_count": 0, "total_recipients": 1,
    }
    cor._process_campaign(sb, campaign, lambda *a, **k: sent.append((a, k)))
    assert sent == []
    # Refused before touching the campaign row or its recipients.
    assert sb.queries == []
    assert any("refused" in line for line in lines)


# ── (b) sequence_runner ─────────────────────────────────────────────


def _status_event(tenant_id: str, published_at: str, lead_id: str) -> dict:
    # A lead reaching 'submitted' through a form: this one event drives the
    # form hook (cancel drips), underwriting auto-fire and drip enrollment.
    return {
        "id": f"ev-{published_at}",
        "event_type": "BRAVO_RECORD_STATUS_CHANGED",
        "published_at": published_at,
        "payload": {
            "tenant_id": tenant_id,
            "entity": "lead",
            "entity_type": "lead",
            "record_id": lead_id,
            "lead_id": lead_id,
            "field": "stage",
            "to": "submitted",
            "triggering_event": "form_submitted",
        },
    }


def test_sequence_enrollment_ignores_other_tenants_events(monkeypatch):
    sr = _mod("sequence_runner")
    _quiet(monkeypatch, sr)
    acted: list = []
    cursor: dict = {}
    monkeypatch.setattr(sr, "_read_cursor", lambda: "2026-01-01T00:00:00+00:00")
    monkeypatch.setattr(sr, "_write_cursor", lambda ts: cursor.update(ts=ts))
    monkeypatch.setattr(sr, "_cancel_drips_for_lead", _recorder(acted, "cancel", 0))
    monkeypatch.setattr(sr, "_resolve_application_for_lead", _recorder(acted, "resolve_app", "app-1"))
    monkeypatch.setattr(sr, "_fire_underwriting_auto", _recorder(acted, "underwrite", True))
    monkeypatch.setattr(sr, "_has_active_state", _recorder(acted, "active", False))
    monkeypatch.setattr(sr, "_enroll_step", _recorder(acted, "enroll", None))

    sb = FakeSupabase({"agent_events": [
        _status_event(SUNBIZ_TENANT_ID, "2026-01-02T00:00:01+00:00", "lead-sunbiz"),
        _status_event(OTHER_TENANT, "2026-01-02T00:00:02+00:00", "lead-other"),
    ]})
    sr.enrollment_tick(sb)

    tenants_acted_for = {args[1] for name, args in acted
                         if name in ("cancel", "resolve_app", "underwrite")}
    assert tenants_acted_for == {SUNBIZ_TENANT_ID}
    drip_reads = sb.on("drip_sequences")
    assert any(q.has("eq", "tenant_id", SUNBIZ_TENANT_ID) for q in drip_reads)
    assert not any(q.has("eq", "tenant_id", OTHER_TENANT) for q in drip_reads)
    # The cursor still moves past the skipped event, so it is not re-read.
    assert cursor["ts"] == "2026-01-02T00:00:02+00:00"


def test_sequence_execution_claims_only_sunbiz_rows(monkeypatch):
    sr = _mod("sequence_runner")
    _quiet(monkeypatch, sr)
    sb = FakeSupabase()
    assert sr.execution_tick(sb) == 0
    (due,) = sb.on("sequence_state")
    assert due.has("eq", "status", "scheduled")
    assert due.has("eq", "tenant_id", SUNBIZ_TENANT_ID)


def test_sequence_send_step_refuses_another_tenants_row(monkeypatch):
    sr = _mod("sequence_runner")
    _quiet(monkeypatch, sr)
    sent: list = []
    gateway = types.ModuleType("integrations.send_gateway")
    gateway.send = lambda **kw: sent.append(kw) or {"status": "sent"}
    package = types.ModuleType("integrations")
    package.__path__ = []
    package.send_gateway = gateway
    monkeypatch.setitem(sys.modules, "integrations", package)
    monkeypatch.setitem(sys.modules, "integrations.send_gateway", gateway)
    # Refused BEFORE anything about the row is read: this box must not load
    # another company's lead or rep even to reject it. (CodeRabbit, PR #3.)
    monkeypatch.setattr(sr, "_build_context",
                        lambda *a, **k: pytest.fail("read the foreign lead before refusing it"))
    monkeypatch.setattr(sr, "_resolve_assigned_rep_email",
                        lambda *a, **k: pytest.fail("read the foreign rep before refusing it"))

    row = {"tenant_id": OTHER_TENANT, "lead_id": "lead-other", "step_index": 0,
           "context_snapshot": {}}
    sequence = {"id": "seq-1", "name": "drip",
                "steps": [{"channel": "email", "subject": "Hi", "body_text": "Hello"}]}
    fake = FakeSupabase()
    result = sr._send_step(fake, row, sequence)
    assert sent == []
    assert result["outcome"] == "permanent"
    assert fake.queries == [], "the refusal queried the database"


# ── (c) lender_response_classifier ──────────────────────────────────


@pytest.mark.parametrize("command", [["once"], ["loop"]])
def test_classifier_will_not_start_without_a_tenant(monkeypatch, command):
    lrc = _mod("lender_response_classifier")
    _quiet(monkeypatch, lrc)
    ran: list = []
    monkeypatch.setattr(lrc, "SUNBIZ_TENANT_ID", "")
    monkeypatch.setattr(lrc, "tick", lambda: ran.append("tick") or 0)
    monkeypatch.setattr(lrc, "loop", lambda interval: ran.append("loop") or 0)
    assert lrc.main(command) == 2
    assert ran == []


@pytest.mark.parametrize("fn", ["sla_sweep", "classify_tick"])
@pytest.mark.parametrize("tenant", ["", SUNBIZ_TENANT_ID])
def test_classifier_queries_always_carry_the_tenant_filter(monkeypatch, fn, tenant):
    lrc = _mod("lender_response_classifier")
    _quiet(monkeypatch, lrc)
    monkeypatch.setattr(lrc, "SUNBIZ_TENANT_ID", tenant)
    sb = FakeSupabase()
    getattr(lrc, fn)(sb)
    (threads,) = sb.on("application_lender_threads")
    # An empty value matches no row. Dropping the filter matched every row.
    assert threads.has("eq", "tenant_id", tenant)


# ── (d) shop_out_sender ─────────────────────────────────────────────


@pytest.mark.parametrize("command", ["once", "loop"])
def test_shop_out_defaults_to_sunbiz_tenant(monkeypatch, command):
    sos = _mod("shop_out_sender")
    seen: dict = {}

    def fake_once(batch, tenant_id, dry_run):
        seen["tenant_id"] = tenant_id
        return {"ok": True, "processed": 0}

    def fake_loop(batch, tenant_id, interval, dry_run):
        seen["tenant_id"] = tenant_id

    monkeypatch.setattr(sos, "run_once", fake_once)
    monkeypatch.setattr(sos, "run_loop", fake_loop)
    # SunBiz's tenant_cron_jobs row runs exactly `once`, with no --tenant-id.
    monkeypatch.setattr(sys, "argv", ["shop_out_sender.py", command])
    sos.main()
    assert seen["tenant_id"] == SUNBIZ_TENANT_ID


def test_shop_out_tenant_override_still_works(monkeypatch):
    sos = _mod("shop_out_sender")
    seen: dict = {}

    def fake_once(batch, tenant_id, dry_run):
        seen["tenant_id"] = tenant_id
        return {"ok": True, "processed": 0}

    monkeypatch.setattr(sos, "run_once", fake_once)
    monkeypatch.setattr(sys, "argv", ["shop_out_sender.py", "once", "--tenant-id", OTHER_TENANT])
    sos.main()
    assert seen["tenant_id"] == OTHER_TENANT


def test_shop_out_refuses_an_empty_tenant(monkeypatch):
    sos = _mod("shop_out_sender")
    monkeypatch.setattr(sos, "_supabase", lambda: pytest.fail("opened a client with no tenant"))
    out = sos.run_once(5, "", True)
    assert out["ok"] is False
    assert out["error"] == "tenant_id_required"


@pytest.mark.parametrize("command", ["once", "loop"])
@pytest.mark.parametrize("tenant", ["", "   "])
def test_shop_out_main_refuses_a_blank_tenant_before_starting(monkeypatch, command, tenant):
    # run_loop discarded run_once's tenant_id_required and spun forever on a
    # blank tenant. main() now refuses before either starts. (CodeRabbit, PR #3.)
    sos = _mod("shop_out_sender")
    monkeypatch.setattr(sos, "run_once", lambda *a, **k: pytest.fail("started once with a blank tenant"))
    monkeypatch.setattr(sos, "run_loop", lambda *a, **k: pytest.fail("started loop with a blank tenant"))
    monkeypatch.setattr(sys, "argv", ["shop_out_sender.py", command, "--tenant-id", tenant])
    assert sos.main() == 2


def test_daily_plan_counts_one_write_per_plan_item(monkeypatch):
    # Two queued rows for one (tenant, date, lead, category) are one plan
    # item: the tick must report one write, not two. (CodeRabbit, PR #3.)
    dpg = _mod("daily_plan_generator")
    row = {"tenant_id": "aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110", "plan_date": "2026-09-12", "lead_id": "lead-1",
           "category": "priority_call", "status": "open"}
    monkeypatch.setattr(dpg, "_PENDING", [dict(row), dict(row, status="open")])
    written, failed = dpg._flush_upserts(FakeSupabase())
    assert (written, failed) == (1, 0)


# ── (e) sentinel ────────────────────────────────────────────────────


def test_sentinel_pause_publishes_on_the_ceo_agent_bus(monkeypatch, tmp_path):
    sen = _mod("sentinel")
    lines = _quiet(monkeypatch, sen)

    # A stand-in CEO-Agent root laid out like the real one: the bus is
    # scripts/core/event_bus.py inside a regular package, notify is
    # scripts/notify.py. Both record to files instead of doing anything.
    published = tmp_path / "published.txt"
    core = tmp_path / "scripts" / "core"
    core.mkdir(parents=True)
    (core / "__init__.py").write_text("", encoding="utf-8")
    (core / "event_bus.py").write_text(
        "def publish(event_type, payload, **kwargs):\n"
        f"    open({str(published)!r}, 'a', encoding='utf-8').write(event_type + '\\n')\n"
        "    return {'status': 'published'}\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "notify.py").write_text(
        "def notify(*args, **kwargs):\n    return None\n", encoding="utf-8"
    )

    # Only the stand-in root may answer these imports: drop the real
    # CEO-Agent scripts dir from the path and any cached copies.
    real = str(sen.BRAVO_ROOT / "scripts") if sen.BRAVO_ROOT else None
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != real])
    names = ("core", "event_bus", "notify")
    saved = {k: v for k, v in sys.modules.items()
             if k in names or k.startswith("core.")}
    for k in saved:
        del sys.modules[k]
    try:
        monkeypatch.setattr(sen, "BRAVO_ROOT", tmp_path)
        monkeypatch.setattr(sen, "_get_lead_data", lambda *a, **k: {})
        monkeypatch.setattr(sen, "_update_lead_data", lambda *a, **k: True)
        applied = sen._apply_pause(
            FakeSupabase(), SUNBIZ_TENANT_ID, "lead-1", -45.0, -80, ["angry"], "stop texting me"
        )
    finally:
        for k in [k for k in sys.modules if k in names or k.startswith("core.")]:
            del sys.modules[k]
        sys.modules.update(saved)

    assert applied is True
    assert not [line for line in lines if "event bus emit failed" in line]
    assert published.read_text(encoding="utf-8").split() == ["BRAVO_SENTIMENT_PAUSE"]
