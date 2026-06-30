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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

bootstrap_bravo_path()

_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")
_API = "https://api.telegram.org/bot{token}/{method}"


def load_env() -> dict[str, str]:
    try:
        from lib.secret_loader import load_env as _le  # type: ignore
        return _le()
    except Exception:  # noqa: BLE001
        import os
        return dict(os.environ)


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
        lines.append(f"📊 Leverage: {d['leverage_ratio']}% · {d.get('mca_positions', '?')} active funder(s)")
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


def _sample_candidate() -> dict[str, Any]:
    return {
        "tier": "good", "score": 91,
        "data": {
            "business_name": "EAGLE METAL LLC", "state": "Florida",
            "true_revenue_monthly": 106779, "leverage_ratio": 5.72, "mca_positions": 1,
            "previously_submitted": True, "iso_broker": "USC",
            "scrub_reasons": ["true revenue $106,779/mo", "active leverage 5.72% on 1 funder",
                              "data merge clean", "PREVIOUSLY SUBMITTED = Yes"],
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Ezra Telegram approval bridge (send/helper half)")
    p.add_argument("mode", choices=["getchats", "testsend"], nargs="?", default="getchats")
    args = p.parse_args(argv)
    env = load_env()

    me = api(env, "getMe")
    print(f"bot: @{me.get('result', {}).get('username')} (ok={me.get('ok')})")
    if not me.get("ok"):
        print(f"  error: {me.get('error')}", file=sys.stderr)
        return 1

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
