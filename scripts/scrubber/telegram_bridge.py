"""scrubber/telegram_bridge.py — Ezra's Telegram approval bridge for Breeze UW deals.

Flow: a qualifying scrubbed deal is sent to Ezra's Telegram as a packet with
inline Approve / Deny buttons. Approve → the deal is injected into the SunBiz
Command Centre at the uw_sheet stage; Deny → it stops. Ezra is the gate.

  scrubber stages candidate ──▶ send_deal() ──▶ Ezra's Telegram (Approve/Deny)
                                                   │
                                  approve ─────────┤────────── deny
                                  (inject lead)    │     (mark declined)

Config (.env.agents):
  EZRA_TELEGRAM_BOT_TOKEN   the bot token (bot: @Dolphin2005_bot)
  EZRA_TELEGRAM_CHAT_ID     Ezra's chat id (he must message the bot once first)

This module is the SEND + helper half. The callback poller + approval wiring
(poll getUpdates → approve/deny → inject) is built on top of these helpers.

CLI:
  python scripts/scrubber/telegram_bridge.py getchats   # who has messaged the bot (find chat ids)
  python scripts/scrubber/telegram_bridge.py testsend    # send a sample packet to EZRA_TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

bootstrap_bravo_path()

from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402

_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")
_API = "https://api.telegram.org/bot{token}/{method}"


def load_env() -> dict[str, str]:
    try:
        from lib.secret_loader import load_env as _le  # type: ignore
        return _le()
    except Exception:  # noqa: BLE001
        import os
        return dict(os.environ)


def supabase(env: dict[str, str]):
    """Service-role Supabase client (or None)."""
    url = (env.get("BRAVO_SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:  # noqa: BLE001
        return None


def get_token(env: dict[str, str]) -> Optional[str]:
    """EZRA_TELEGRAM_BOT_TOKEN, or the first token-shaped value as a fallback."""
    t = (env.get("EZRA_TELEGRAM_BOT_TOKEN") or "").strip()
    if _TOKEN_RE.match(t):
        return t
    for k, v in env.items():
        if isinstance(v, str) and "ezra" in k.lower() and _TOKEN_RE.match(v.strip()):
            return v.strip()
    return None


def api(env: dict[str, str], method: str, params: Optional[dict] = None,
        token: Optional[str] = None) -> dict[str, Any]:
    """Call the Telegram Bot API. Returns the parsed JSON (or {ok:False,error})."""
    tok = token or get_token(env)
    if not tok:
        return {"ok": False, "error": "EZRA_TELEGRAM_BOT_TOKEN not set"}
    url = _API.format(token=tok, method=method)
    data = json.dumps(params).encode("utf-8") if params else None
    headers = {"content-type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # noqa: PERF203
        return {"ok": False, "error": e.read().decode("utf-8")[:300]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def known_chats(env: dict[str, str]) -> dict[int, str]:
    """Chat ids that have messaged the bot (from getUpdates)."""
    out: dict[int, str] = {}
    upd = api(env, "getUpdates")
    for u in upd.get("result", []) or []:
        m = u.get("message") or u.get("edited_message") or u.get("channel_post") or {}
        ch = m.get("chat") or {}
        if ch.get("id"):
            out[ch["id"]] = ch.get("first_name") or ch.get("title") or ch.get("username") or "?"
    return out


def _money(v: Any) -> Optional[str]:
    try:
        return f"${int(float(v)):,}" if v is not None else None
    except (TypeError, ValueError):
        return None


_CADENCE_ABBR = {"daily": "day", "weekly": "wk", "monthly": "mo"}


def _md(s: Any) -> str:
    """Strip Markdown-breaking chars from a dynamic value (legacy parse_mode)."""
    return re.sub(r"[_*`\[\]]", " ", str(s)).strip()


def _is_counted(p: dict[str, Any]) -> bool:
    """An ACTIVE position under CC's rule: daily/weekly, not paid off, not the
    Breeze Advance row. These are the funders the leverage/position count uses."""
    return (
        p.get("cadence") in ("daily", "weekly")
        and not p.get("paid_off")
        and not p.get("is_breeze_advance")
    )


def _funder_lines(d: dict[str, Any]) -> list[str]:
    """Render the FULL funder stack so Ezra sees every position — active,
    paid-off, and monthly — not just the one counted toward leverage. Prefers
    the complete `uw_all_positions`; falls back to `current_funders` (active
    only) for older candidates that didn't carry the full stack."""
    stack = d.get("uw_all_positions") or d.get("current_funders") or []
    # Drop the Breeze Advance row (the NEW advance offered, not a stack position)
    # and any empty/zero placeholder rows.
    funders = [p for p in stack if p.get("funder") and not p.get("is_breeze_advance")]
    if not funders:
        return []
    active = sum(1 for p in funders if _is_counted(p))
    header = f"🏦 *Funder stack — {len(funders)} total · {active} active:*"
    lines = [header]
    for p in funders[:15]:
        if _is_counted(p):
            marker, tag = "✅", "active"
        elif p.get("paid_off"):
            marker, tag = "💤", "paid off"
        elif p.get("cadence") == "monthly":
            marker, tag = "📅", "monthly"
        else:
            marker, tag = "•", (p.get("cadence") or "")
        if str(p.get("status") or "").strip().lower() == "previous":
            tag = (tag + " · prior").strip(" ·")
        lev = p.get("leverage_pct")
        cad = _CADENCE_ABBR.get(p.get("cadence") or "", p.get("cadence") or "")
        bits = []
        if lev is not None:
            bits.append(f"{lev}%")
        if cad:
            bits.append(cad)
        meta = (" — " + " ".join(bits)) if bits else ""
        suffix = f"  _({tag})_" if tag else ""
        lines.append(f"  {marker} {_md(p.get('funder'))}{meta}{suffix}")
    if len(funders) > 15:
        lines.append(f"  …+{len(funders) - 15} more")
    return lines


def format_packet(cand: dict[str, Any]) -> str:
    """Render a scored deal as the Telegram message Ezra reviews. `cand` is a
    {data, score_result} candidate, or a scrub_candidates row (lead_data + tier)."""
    d = cand.get("data") or cand.get("lead_data") or {}
    r = cand.get("score_result") or {}
    tier = (r.get("tier") or cand.get("tier") or "").upper()
    score = r.get("score", cand.get("score", ""))
    biz = d.get("business_name") or d.get("company") or "(unnamed business)"
    icon = "🟢" if tier == "GOOD" else "🟡"
    lines = [f"{icon} *UW Deal — {tier}*  (score {score})", f"*{biz}*"]
    if d.get("state"):
        lines.append(f"📍 {d['state']}" + (f" · {d['industry']}" if d.get("industry") else ""))
    tr = _money(d.get("true_revenue_monthly") or d.get("monthly_revenue"))
    if tr:
        lines.append(f"💰 True revenue: {tr}/mo")
    if d.get("leverage_ratio") is not None:
        lines.append(f"📊 Active leverage: {d['leverage_ratio']}% · {d.get('mca_positions', '?')} active funder(s)")
    # Full funder stack — Ezra needs EVERY position (active, paid-off, monthly),
    # not just the one counted toward leverage. (uw_all_positions carries them.)
    lines.extend(_funder_lines(d))
    if d.get("previously_submitted"):
        lines.append("🔁 *Previously Submitted = Yes*")
    if d.get("iso_broker"):
        lines.append(f"🏷 ISO: {d['iso_broker']}")
    reasons = r.get("reasons") or d.get("scrub_reasons") or []
    if reasons:
        lines.append("\n_" + " · ".join(str(x) for x in reasons[:5]) + "_")
    return "\n".join(lines)


def send_deal(env: dict[str, str], cand: dict[str, Any], candidate_id: str,
              chat_id: Optional[str] = None) -> dict[str, Any]:
    """Send a deal packet to Ezra with Approve/Deny buttons. callback_data
    carries the action + candidate id for the poller to act on."""
    chat = chat_id or (env.get("EZRA_TELEGRAM_CHAT_ID") or "").strip()
    if not chat:
        return {"ok": False, "error": "EZRA_TELEGRAM_CHAT_ID not set"}
    keyboard = {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"approve:{candidate_id}"},
        {"text": "❌ Deny", "callback_data": f"deny:{candidate_id}"},
    ]]}
    return api(env, "sendMessage", {
        "chat_id": chat,
        "text": format_packet(cand),
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    })


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def inject_lead(sb, lead_data: dict[str, Any]) -> Optional[str]:
    """Create the Command Centre lead at the uw_sheet (Live Subs) stage AND emit
    BRAVO_RECORD_STATUS_CHANGED so the follow-up drip fires — the same effect as
    a dashboard-driven create (shape mirrors lib/manifest/events.publishStatusChange)."""
    data = dict(lead_data)
    data["stage"] = "uw_sheet"  # internal key; UI label is "Live Subs"
    res = sb.table("tenant_records").insert(
        {"tenant_id": SUNBIZ_TENANT_ID, "entity_type": "lead", "data": data}
    ).execute()
    rows = res.data or []
    lead_id = rows[0].get("id") if rows else None
    if not lead_id:
        return None
    sb.table("agent_events").insert({
        "event_type": "BRAVO_RECORD_STATUS_CHANGED",
        "publisher_agent": "ezra-telegram-bridge",
        "severity": "info",
        "payload": {
            "entity": "lead", "record_id": lead_id, "field": "stage",
            "from": None, "to": "uw_sheet", "data": data, "tenant_id": SUNBIZ_TENANT_ID,
        },
        "correlation_id": SUNBIZ_TENANT_ID,
    }).execute()
    return lead_id


def approve_candidate(sb, candidate_id: str, reviewer: str = "ezra-telegram") -> tuple[bool, Optional[str], str]:
    """Approve → inject the lead + flip the candidate. Returns (ok, lead_id, msg)."""
    r = sb.table("scrub_candidates").select("id, status, lead_data").eq("id", candidate_id).maybe_single().execute()
    cand = r.data
    if not cand:
        return False, None, "not found"
    if cand["status"] != "pending_review":
        return False, None, f"already {cand['status']}"
    # optimistic claim (best-effort; the inject is idempotent enough at this scale)
    sb.table("scrub_candidates").update(
        {"status": "approving", "reviewed_by": reviewer, "reviewed_at": _now(), "updated_at": _now()}
    ).eq("id", candidate_id).eq("status", "pending_review").execute()
    try:
        lead_id = inject_lead(sb, cand["lead_data"] or {})
    except Exception as e:  # noqa: BLE001
        sb.table("scrub_candidates").update({"status": "pending_review", "updated_at": _now()}).eq("id", candidate_id).execute()
        return False, None, f"inject failed: {e}"
    sb.table("scrub_candidates").update(
        {"status": "approved", "created_lead_id": lead_id, "updated_at": _now()}
    ).eq("id", candidate_id).execute()
    return True, lead_id, "approved"


def decline_candidate(sb, candidate_id: str, reviewer: str = "ezra-telegram") -> bool:
    upd = sb.table("scrub_candidates").update(
        {"status": "declined", "reviewed_by": reviewer, "reviewed_at": _now(), "updated_at": _now()}
    ).eq("id", candidate_id).eq("status", "pending_review").execute()
    return bool(upd.data is not None)


def poll_loop(env: dict[str, str], sb) -> None:
    """Long-poll getUpdates for Ezra's Approve/Deny taps and act on them.
    callback_data is 'approve:<candidate_id>' / 'deny:<candidate_id>'."""
    me = api(env, "getMe")
    print(f"[ezra-bridge] polling as @{me.get('result', {}).get('username')} (ok={me.get('ok')})")
    offset: Optional[int] = None
    while True:
        upd = api(env, "getUpdates", {"offset": offset, "timeout": 50, "allowed_updates": ["callback_query"]})
        if not upd.get("ok"):
            time.sleep(5)
            continue
        for u in upd.get("result", []) or []:
            offset = u["update_id"] + 1
            cq = u.get("callback_query")
            if not cq:
                continue
            data = cq.get("data", "") or ""
            cqid = cq.get("id")
            msg = cq.get("message", {}) or {}
            chat = (msg.get("chat") or {}).get("id")
            mid = msg.get("message_id")
            if ":" not in data:
                api(env, "answerCallbackQuery", {"callback_query_id": cqid, "text": "unrecognized"})
                continue
            action, cid = data.split(":", 1)
            if action == "approve":
                ok, lead_id, m = approve_candidate(sb, cid)
                api(env, "answerCallbackQuery", {"callback_query_id": cqid, "text": "✅ Approved" if ok else f"⚠ {m}"})
                if ok and chat and mid:
                    api(env, "editMessageText", {"chat_id": chat, "message_id": mid,
                        "text": (msg.get("text") or "") + "\n\n✅ *APPROVED* → injected to Live Subs", "parse_mode": "Markdown"})
                print(f"[ezra-bridge] approve {cid}: ok={ok} lead={lead_id} {m}")
            elif action == "deny":
                ok = decline_candidate(sb, cid)
                api(env, "answerCallbackQuery", {"callback_query_id": cqid, "text": "❌ Denied"})
                if chat and mid:
                    api(env, "editMessageText", {"chat_id": chat, "message_id": mid,
                        "text": (msg.get("text") or "") + "\n\n❌ *DENIED*", "parse_mode": "Markdown"})
                print(f"[ezra-bridge] deny {cid}: ok={ok}")


def _sample_candidate() -> dict[str, Any]:
    # Real EAGLE METAL stack (UW Sheet 2.5, 2026-06-30): 8 funders, only Ondeck
    # active (daily/weekly + unpaid). Exercises the full-stack renderer.
    stack = [
        {"status": "Current",  "funder": "Novuscapital",  "cadence": "weekly",  "leverage_pct": 32.90, "paid_off": True},
        {"status": "Current",  "funder": "Ondeck Capital", "cadence": "weekly",  "leverage_pct": 5.72,  "paid_off": False},
        {"status": "Current",  "funder": "Kapitus",        "cadence": "weekly",  "leverage_pct": 10.61, "paid_off": True},
        {"status": "Previous", "funder": "Novuscapital",   "cadence": "weekly",  "leverage_pct": 30.71, "paid_off": True},
        {"status": "Current",  "funder": "Lendingclub",    "cadence": "monthly", "leverage_pct": 0.96,  "paid_off": False},
        {"status": "Current",  "funder": "Headway",        "cadence": "monthly", "leverage_pct": 24.36, "paid_off": False},
        {"status": "Current",  "funder": "Hyg Financial",  "cadence": "monthly", "leverage_pct": 0.94,  "paid_off": False},
        {"status": "Current",  "funder": "P1 Finance",     "cadence": "monthly", "leverage_pct": 2.02,  "paid_off": False},
    ]
    return {
        "tier": "good", "score": 91,
        "data": {
            "business_name": "EAGLE METAL LLC", "state": "Florida",
            "true_revenue_monthly": 106779, "leverage_ratio": 5.72, "mca_positions": 1,
            "previously_submitted": True, "iso_broker": "USC",
            "current_funders": [p for p in stack if _is_counted(p)],
            "uw_all_positions": stack,
            "scrub_reasons": ["true revenue $106,779/mo", "active leverage 5.72% on 1 funder",
                              "data merge clean", "PREVIOUSLY SUBMITTED = Yes"],
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Ezra Telegram approval bridge (send/helper half)")
    p.add_argument("mode", choices=["getchats", "testsend", "poll"], nargs="?", default="getchats")
    args = p.parse_args(argv)
    env = load_env()

    me = api(env, "getMe")
    print(f"bot: @{me.get('result', {}).get('username')} (ok={me.get('ok')})")
    if not me.get("ok"):
        print(f"  error: {me.get('error')}", file=sys.stderr)
        return 1

    if args.mode == "poll":
        sb = supabase(env)
        if sb is None:
            print("  supabase client unavailable (need BRAVO_SUPABASE_URL + SERVICE_ROLE_KEY)", file=sys.stderr)
            return 1
        poll_loop(env, sb)
        return 0

    if args.mode == "getchats":
        chats = known_chats(env)
        if not chats:
            print("No chats yet — have Ezra (and you) send the bot a message, then re-run.")
        for cid, nm in chats.items():
            print(f"  chat_id {cid}  ({nm})")
        cfg_chat = (env.get("EZRA_TELEGRAM_CHAT_ID") or "").strip()
        print(f"EZRA_TELEGRAM_CHAT_ID currently: {cfg_chat or '(not set)'}")
        return 0

    # testsend
    res = send_deal(env, _sample_candidate(), candidate_id="TEST")
    print(f"testsend ok={res.get('ok')} {res.get('error', '')}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
