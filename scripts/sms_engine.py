"""Sun Biz Agent — Multi-Provider SMS Engine (V1).

Phase 1: Twilio provider only.
Phase 2 (this week): Telnyx + Plivo failover under the same send_sms() API.

The send_sms() entry point is provider-pluggable. `provider="auto"` is the
intended default once Phase 2 lands; today it routes to Twilio. Switching
providers without touching the call sites is the point.

CLI:
    python scripts/sms_engine.py send --to +14165551212 --body "..." --json
    python scripts/sms_engine.py status --json
    python scripts/sms_engine.py providers --json

Behavior:
- Loads credentials from .env.agents (SUNBIZ_TWILIO_ACCOUNT_SID,
  SUNBIZ_TWILIO_AUTH_TOKEN, SUNBIZ_TWILIO_FROM_NUMBER). Never prints them.
- Phase 1 hard-blocks empty bodies, bodies > 1600 chars (concat-MMS upper
  bound), and obviously malformed E.164 numbers. Real TCPA consent checks
  land Phase 2 once the Supabase contacts.sms_consent column exists.
- Each successful send appends a row to tmp/sms_log.jsonl AND emits a
  SUNBIZ_SMS_SENT event to Bravo's V6 bus (best-effort; failures never
  break the send).
- Returns structured JSON on --json: {ok, provider, sid|error, to_hash,
  status, body_len, ts}.

Module API (for callers like deal_tracker, blast workers):
    from sms_engine import send_sms, SendResult
    result = send_sms(to="+14165551212", body="Hi {first_name}",
                     provider="twilio", merge_vars={"first_name": "Sun"})
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env.agents"
LOG_DIR = PROJECT_ROOT / "tmp"
LOG_PATH = LOG_DIR / "sms_log.jsonl"

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
MAX_BODY = 1600  # concat-MMS upper bound; single-segment SMS is 160

PROVIDERS = ("twilio",)  # Phase 2: ("twilio", "telnyx", "plivo")


# ── Env loading (defer to secret_loader if Bravo's lib is reachable) ────────

def _load_env() -> dict[str, str]:
    """Read .env.agents into a flat dict. Returns {} if the file is absent.

    Mirrors the lightweight pattern Bravo's event_bus.py uses — we don't
    want to require the secret_loader dep be importable here because the
    Marketing-Agent repo doesn't share its lib/ dir with Business-Empire-Agent.
    """
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


# ── Result shape ────────────────────────────────────────────────────────────

@dataclass
class SendResult:
    ok: bool
    provider: str
    to_hash: str  # sha256[:16] of E.164 — never log raw number in events
    status: str
    body_len: int
    sid: Optional[str] = None
    error: Optional[str] = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return asdict(self)


# ── Provider protocol + implementations ─────────────────────────────────────

class SMSProvider(Protocol):
    name: str
    def send(self, to: str, body: str) -> SendResult: ...  # pragma: no cover


class TwilioProvider:
    name = "twilio"

    def __init__(self, sid: str, auth_token: str, from_number: str) -> None:
        self.sid = sid
        self.auth_token = auth_token
        self.from_number = from_number

    def send(self, to: str, body: str) -> SendResult:
        to_hash = hashlib.sha256(to.encode("utf-8")).hexdigest()[:16]
        try:
            # Lazy import — twilio SDK is optional until Sun's account is wired
            from twilio.rest import Client  # type: ignore
        except ImportError:
            return SendResult(
                ok=False, provider=self.name, to_hash=to_hash,
                status="missing_dependency", body_len=len(body),
                error="twilio package not installed — run: pip install twilio",
            )
        try:
            client = Client(self.sid, self.auth_token)
            msg = client.messages.create(to=to, from_=self.from_number, body=body)
            return SendResult(
                ok=True, provider=self.name, to_hash=to_hash,
                status=msg.status or "queued", body_len=len(body), sid=msg.sid,
            )
        except Exception as exc:  # noqa: BLE001 — surface any provider error
            return SendResult(
                ok=False, provider=self.name, to_hash=to_hash,
                status="provider_error", body_len=len(body), error=str(exc)[:500],
            )


def _build_twilio(env: dict[str, str]) -> Optional[TwilioProvider]:
    sid = env.get("SUNBIZ_TWILIO_ACCOUNT_SID") or os.environ.get("SUNBIZ_TWILIO_ACCOUNT_SID")
    tok = env.get("SUNBIZ_TWILIO_AUTH_TOKEN") or os.environ.get("SUNBIZ_TWILIO_AUTH_TOKEN")
    frm = env.get("SUNBIZ_TWILIO_FROM_NUMBER") or os.environ.get("SUNBIZ_TWILIO_FROM_NUMBER")
    if not (sid and tok and frm):
        return None
    return TwilioProvider(sid, tok, frm)


# ── Validation ──────────────────────────────────────────────────────────────

def _validate(to: str, body: str) -> Optional[str]:
    if not to or not E164_RE.match(to):
        return f"to must be E.164 (e.g. +14165551212), got: {to!r}"
    if not body or not body.strip():
        return "body is empty"
    if len(body) > MAX_BODY:
        return f"body too long: {len(body)} chars (max {MAX_BODY})"
    return None


def _apply_merge_vars(body: str, merge_vars: Optional[dict]) -> str:
    if not merge_vars:
        return body
    out = body
    for k, v in merge_vars.items():
        out = out.replace("{" + str(k) + "}", str(v))
    return out


# ── Logging + event emission ────────────────────────────────────────────────

def _append_log(result: SendResult) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result.to_dict()) + "\n")
    except Exception:
        pass  # logging is best-effort — never break the send


def _emit_sms_sent_event(result: SendResult) -> None:
    """Emit SUNBIZ_SMS_SENT through Bravo's V6 event bus. Best-effort."""
    if not result.ok:
        return
    bravo_scripts = Path("C:/Users/User/Business-Empire-Agent/scripts")
    if not bravo_scripts.exists():
        return
    try:
        sys.path.insert(0, str(bravo_scripts))
        from event_bus import publish  # type: ignore
        idem = f"sunbiz:sms:{result.sid or result.to_hash}:{result.ts}"
        publish(
            "SUNBIZ_SMS_SENT",
            {
                "send_id": result.sid,
                "provider": result.provider,
                "to_hash": result.to_hash,
                "status": result.status,
            },
            source="sunbiz",
            idempotency_key=idem,
        )
    except Exception:
        pass


# ── Public API ──────────────────────────────────────────────────────────────

def get_provider(name: str, env: Optional[dict[str, str]] = None) -> Optional[SMSProvider]:
    env = env if env is not None else _load_env()
    if name == "twilio":
        return _build_twilio(env)
    # Phase 2 hooks:
    # if name == "telnyx": return _build_telnyx(env)
    # if name == "plivo":  return _build_plivo(env)
    return None


def send_sms(to: str, body: str, provider: str = "twilio",
             merge_vars: Optional[dict] = None) -> SendResult:
    """Send a single SMS. Returns SendResult (never raises).

    Phase 1: provider must be 'twilio' (or 'auto', which resolves to twilio).
    Phase 2: provider='auto' will try twilio → telnyx → plivo until one
    returns ok=True or all fail.
    """
    if provider == "auto":
        provider = "twilio"  # Phase 1 — Phase 2 will iterate PROVIDERS

    body = _apply_merge_vars(body, merge_vars)
    err = _validate(to, body)
    to_hash = hashlib.sha256(to.encode("utf-8")).hexdigest()[:16] if to else ""
    if err:
        result = SendResult(ok=False, provider=provider, to_hash=to_hash,
                            status="validation_error", body_len=len(body or ""),
                            error=err)
        _append_log(result)
        return result

    prov = get_provider(provider)
    if not prov:
        result = SendResult(ok=False, provider=provider, to_hash=to_hash,
                            status="provider_not_configured",
                            body_len=len(body),
                            error=f"{provider} credentials missing in .env.agents")
        _append_log(result)
        return result

    result = prov.send(to, body)
    _append_log(result)
    _emit_sms_sent_event(result)
    return result


def status() -> dict:
    """Quick read-only summary for /health and dashboard polling."""
    env = _load_env()
    out: dict = {
        "providers_configured": [],
        "providers_pending": [],
        "log_path": str(LOG_PATH),
        "log_exists": LOG_PATH.exists(),
        "log_size_kb": round(LOG_PATH.stat().st_size / 1024, 1) if LOG_PATH.exists() else 0,
        "twilio_sdk_installed": False,
    }
    if _build_twilio(env):
        out["providers_configured"].append("twilio")
    else:
        out["providers_pending"].append("twilio")
    try:
        import twilio  # noqa: F401
        out["twilio_sdk_installed"] = True
    except ImportError:
        pass
    # Recent send tally
    if LOG_PATH.exists():
        try:
            lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
            out["total_send_attempts"] = len(lines)
            ok_count = sum(1 for l in lines if '"ok": true' in l)
            out["successful_sends"] = ok_count
            out["failed_sends"] = len(lines) - ok_count
        except Exception:
            pass
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cmd_send(args: argparse.Namespace) -> int:
    merge_vars: Optional[dict] = None
    if args.vars:
        try:
            merge_vars = json.loads(args.vars)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"invalid --vars JSON: {exc}"}), file=sys.stderr)
            return 2
    result = send_sms(args.to, args.body, provider=args.provider, merge_vars=merge_vars)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.ok:
            print(f"[OK] {result.provider} → to_hash={result.to_hash} sid={result.sid} status={result.status}")
        else:
            print(f"[FAIL] {result.provider} → to_hash={result.to_hash} status={result.status} error={result.error}")
    return 0 if result.ok else 1


def _cmd_status(args: argparse.Namespace) -> int:
    s = status()
    if args.json:
        print(json.dumps(s, indent=2))
    else:
        print(f"providers configured: {', '.join(s['providers_configured']) or '(none)'}")
        print(f"providers pending:    {', '.join(s['providers_pending']) or '(none)'}")
        print(f"twilio SDK installed: {s['twilio_sdk_installed']}")
        print(f"log file:             {s['log_path']} ({s['log_size_kb']} KB)")
        if "total_send_attempts" in s:
            print(f"attempts: {s['total_send_attempts']}  ok: {s.get('successful_sends', 0)}  fail: {s.get('failed_sends', 0)}")
    return 0


def _cmd_providers(args: argparse.Namespace) -> int:
    out = {"supported_phase1": list(PROVIDERS),
           "supported_phase2": ["twilio", "telnyx", "plivo"]}
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Phase 1: {', '.join(out['supported_phase1'])}")
        print(f"Phase 2: {', '.join(out['supported_phase2'])}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Sun Biz Agent SMS engine (Phase 1: Twilio)")
    sub = p.add_subparsers(dest="command", required=True)

    snd = sub.add_parser("send", help="Send a single SMS")
    snd.add_argument("--to", required=True, help="E.164 recipient, e.g. +14165551212")
    snd.add_argument("--body", required=True, help="Message body (1-1600 chars)")
    snd.add_argument("--provider", default="twilio",
                     choices=["twilio", "auto"],
                     help="SMS provider (Phase 1: twilio; Phase 2 will add telnyx, plivo)")
    snd.add_argument("--vars", default=None, help="JSON dict of merge vars, e.g. {\"first_name\":\"Sun\"}")
    snd.add_argument("--json", action="store_true")
    snd.set_defaults(func=_cmd_send)

    st = sub.add_parser("status", help="Show provider + log status")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=_cmd_status)

    pv = sub.add_parser("providers", help="List supported providers (Phase 1 + Phase 2)")
    pv.add_argument("--json", action="store_true")
    pv.set_defaults(func=_cmd_providers)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
