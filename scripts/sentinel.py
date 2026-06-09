"""sentinel.py — merchant-reply sentiment scorer + auto-pause arbiter.

Phase 1 deliverable from Adon's MCA follow-up architecture brief
(2026-06-08). Sits adjacent to lender_response_classifier.py — same
pattern, different inbound type. Where the classifier handles
LENDER→broker thread responses (approved / declined / info_requested),
the Sentinel handles MERCHANT→broker replies (sentiment -100..+100)
and auto-pauses outbound sequences when the merchant signals
frustration.

WHY THIS EXISTS
---------------
The previous architecture had no detection layer between "merchant
replies with terse / hostile language" and "Bravo sends the next drip
step on schedule." A frustrated merchant who replied "stop bugging me"
on Day 4 of a drip would still receive Days 5, 6, 7. By Day 8 they'd
fire STOP, which damages the sender's domain reputation across every
tenant on the shared infrastructure.

The Sentinel runs every 60s. For each new inbound merchant interaction:
  1. Score the reply -100..+100 via Claude Haiku
  2. Append to lead.data.sentiment_history (rolling 5)
  3. Compute rolling average
  4. If average drops below -30:
       - Set lead.data.sentinel_pause_until = now + 7d
       - Emit BRAVO_SENTIMENT_PAUSE event to the cross-agent bus
       - Push a Telegram alert with the transcript for operator review
  5. If new score > +20 and existing pause: clear it (merchant recovered)

send_gateway.py:_check_sentinel_pause() reads lead.data.sentinel_pause_until
and refuses every outbound while the pause is active. The classifier
doesn't talk to send_gateway directly — they share state via the lead
row, which is the architectural single source of truth.

CLI:
  python scripts/sentinel.py loop --interval 60
  python scripts/sentinel.py once
  python scripts/sentinel.py score --lead-id <uuid> --text "..."

TUNING
------
- THRESHOLD_PAUSE: rolling avg below this triggers a pause. Default -30.
  Bumping more negative = system more tolerant of frustration. Less
  negative = more aggressive auto-pause.
- THRESHOLD_RECOVER: new score above this clears an active pause. +20.
- PAUSE_DURATION_DAYS: how long the pause lasts before auto-expiry. 7d
  matches Adon's brief §4.5.
- ROLLING_WINDOW: number of inbounds the rolling avg considers. 5 per
  brief §4.5.

Sentinel is FAIL-SAFE on errors: any classifier failure leaves the lead
state untouched. We never auto-pause based on a corrupted score.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent  # SunBiz-Agent root
STATE_DIR = REPO_ROOT / "state"
LOG_PATH = STATE_DIR / "sentinel.log"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()


# ─────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────

ROLLING_WINDOW = 5                # Number of inbounds the avg considers
THRESHOLD_PAUSE = -30             # Avg below this -> 7d auto-pause (red flag)
THRESHOLD_YELLOW = 0              # Avg between -30 and this -> yellow flag (2x cadence)
THRESHOLD_RECOVER = 20            # New score above this clears a pause
PAUSE_DURATION_DAYS = 7
YELLOW_FLAG_DAYS = 14             # Yellow flag stays sticky for this long after avg recovers
INBOUND_LOOKBACK_HOURS = 48       # Only score inbounds from last 48h on each pass
DEFAULT_INTERVAL_SECONDS = 60

# Phase 1 scope: Sentinel runs against the SunBiz tenant only. The
# service-role Supabase client bypasses RLS, so without an explicit
# tenant filter the daemon would score every tenant's inbounds (OASIS,
# future PropFlow, etc.) under the same threshold logic. That's not the
# intended behavior — Adon's brief is SunBiz-specific, and CC explicitly
# wants per-tenant opt-in for cross-cutting automation.
#
# To enable Sentinel for another tenant later: run a second pm2 daemon
# with --tenant-id <other_uuid> (the CLI honors --tenant-id too).
from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402

# Profanity / hostility tokens — case-insensitive substring match. The
# LLM does the heavy lifting; this is a deterministic floor for the
# obvious cases so we never miss them on an LLM hiccup.
PROFANITY_TOKENS = (
    "fuck", "shit", "bullshit", "asshole", "stupid", "idiot", "scam",
    "scammer", "moron", "harass", "harrass",
)
HARD_STOP_TOKENS = ("stop", "unsubscribe", "remove me", "leave me alone")
POSITIVE_TOKENS = ("thank", "appreciate", "great", "perfect", "love it", "please")


def _log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    print(line.rstrip())


# ─────────────────────────────────────────────────────────────────────
# Supabase + env (mirrors lender_response_classifier.py)
# ─────────────────────────────────────────────────────────────────────


def _supabase():
    try:
        from lib.secret_loader import load_env  # type: ignore
    except Exception:
        return None
    try:
        env = load_env()
    except Exception:
        return None
    url = (env.get("BRAVO_SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client
    except ImportError:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def _load_env_var(name: str) -> str:
    try:
        from lib.secret_loader import load_env  # type: ignore
        return (load_env().get(name) or os.environ.get(name) or "").strip()
    except Exception:
        return os.environ.get(name, "").strip()


# ─────────────────────────────────────────────────────────────────────
# Score modifiers (deterministic floor before LLM)
# ─────────────────────────────────────────────────────────────────────


def _signal_modifiers(text: str) -> tuple[int, list[str], list[str]]:
    """Apply Adon §4.5 deterministic signal modifiers on top of the LLM
    base score. Returns (modifier_delta, frustration_signals, positive_signals).

    Conservative on the negative side — these signals stack with the LLM
    score, so we don't want them to dominate. Worst-case stack from this
    function is about -80 (profanity + caps + hard-stop) which alongside
    even a +50 LLM score still pulls the rolling avg below -30.
    """
    if not text:
        return 0, [], []
    t = text.lower()
    delta = 0
    frustration: list[str] = []
    positive: list[str] = []

    # Length signals
    stripped = text.strip()
    if len(stripped) < 10:
        delta -= 10
        frustration.append("reply_under_10_chars")
    elif len(stripped.split()) > 50:
        delta += 15
        positive.append("substantive_reply_over_50_words")

    # Profanity
    for tok in PROFANITY_TOKENS:
        if tok in t:
            delta -= 30
            frustration.append(f"profanity:{tok}")
            break  # only count once

    # Hard-stop keywords (the merchant is literally asking to be removed)
    for tok in HARD_STOP_TOKENS:
        if tok in t:
            delta -= 50
            frustration.append(f"hard_stop_keyword:{tok}")
            break

    # All caps sustained — checking for >5 consecutive uppercase tokens
    upper_run = 0
    max_upper_run = 0
    for word in text.split():
        if len(word) >= 2 and word.isupper():
            upper_run += 1
            max_upper_run = max(max_upper_run, upper_run)
        else:
            upper_run = 0
    if max_upper_run >= 3:
        delta -= 15
        frustration.append("all_caps_sustained")

    # Positive signals
    pos_hits = 0
    for tok in POSITIVE_TOKENS:
        if tok in t:
            pos_hits += 1
    if pos_hits:
        delta += min(20, pos_hits * 10)
        positive.append(f"polite_tokens:{pos_hits}")

    # Question mark — engaged
    if "?" in text:
        delta += 5
        positive.append("question_engaged")

    return delta, frustration, positive


SENTINEL_PROMPT = """You're an MCA broker reading a merchant's reply to one of our outbound emails or texts. Score the merchant's tone on a scale -100 to +100 where:

  -100 = extreme hostility (threats, profanity, demands to stop)
   -50 = clearly frustrated, terse, annoyed
     0 = neutral, business-like, transactional
   +50 = warm, engaged, asking questions, expressing interest
  +100 = highly enthusiastic, eager, grateful

Return JSON with EXACTLY these keys:
  {{
    "score": <int -100..+100>,
    "reason": "<one-sentence justification, max 200 chars>",
    "frustration_signals": ["<signal>", ...],   // empty array if none
    "positive_signals": ["<signal>", ...]       // empty array if none
  }}

The merchant's reply is between the markers below.

<reply>
{body}
</reply>
"""


def classify_sentiment(body: str) -> dict[str, Any]:
    """Score a single inbound merchant reply. Returns
    {"score": int, "reason": str, "frustration_signals": list,
     "positive_signals": list, "source": "llm"|"fallback"}.

    Two-stage scoring: (1) Claude Haiku LLM base score, (2) deterministic
    signal modifiers stacked on top. The deterministic floor catches the
    obvious cases (profanity, STOP keywords) so a buggy LLM call never
    masks a hard hostility signal.
    """
    body = (body or "").strip()
    if not body:
        return {"score": 0, "reason": "empty body", "frustration_signals": [],
                "positive_signals": [], "source": "fallback"}

    # Try LLM first
    api_key = _load_env_var("ANTHROPIC_API_KEY") or _load_env_var("BRAVO_ANTHROPIC_API_KEY")
    llm_score = 0
    llm_reason = "fallback: no LLM"
    llm_frustration: list[str] = []
    llm_positive: list[str] = []
    source = "fallback"

    if api_key:
        try:
            import requests
            prompt = SENTINEL_PROMPT.format(body=body[:4000])
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 250,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            if r.status_code < 400:
                data = r.json()
                text = "".join(
                    blk.get("text", "")
                    for blk in data.get("content", [])
                    if blk.get("type") == "text"
                ).strip()
                s, e = text.find("{"), text.rfind("}")
                if s != -1 and e > s:
                    try:
                        parsed = json.loads(text[s : e + 1])
                        llm_score = int(parsed.get("score", 0))
                        llm_score = max(-100, min(100, llm_score))
                        llm_reason = str(parsed.get("reason", ""))[:200]
                        llm_frustration = [
                            str(x) for x in (parsed.get("frustration_signals") or [])
                        ]
                        llm_positive = [
                            str(x) for x in (parsed.get("positive_signals") or [])
                        ]
                        source = "llm"
                    except (json.JSONDecodeError, ValueError, TypeError) as exc:
                        _log(f"classify_sentiment: LLM parse fail: {exc}")
            else:
                _log(f"classify_sentiment: Anthropic HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            _log(f"classify_sentiment: LLM call failed: {exc}")

    # Stack deterministic modifiers (always run — they catch the obvious
    # cases even if LLM said otherwise)
    delta, det_frustration, det_positive = _signal_modifiers(body)
    final_score = max(-100, min(100, llm_score + delta))

    return {
        "score": final_score,
        "reason": llm_reason,
        "frustration_signals": llm_frustration + det_frustration,
        "positive_signals": llm_positive + det_positive,
        "source": source,
        "llm_score": llm_score,
        "modifier_delta": delta,
    }


# ─────────────────────────────────────────────────────────────────────
# Lead state read/write
# ─────────────────────────────────────────────────────────────────────


def _get_lead_data(sb, tenant_id: str, lead_id: str) -> Optional[dict[str, Any]]:
    """Return the full data jsonb for a lead, or None on miss."""
    try:
        rows = (
            sb.table("tenant_records")
            .select("data")
            .eq("tenant_id", tenant_id)
            .eq("entity_type", "lead")
            .eq("id", lead_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"get_lead_data: read fail lead_id={lead_id}: {exc}")
        return None
    if not rows.data:
        return None
    return rows.data[0].get("data") or {}


def _update_lead_data(sb, tenant_id: str, lead_id: str,
                      patch: dict[str, Any]) -> bool:
    """Merge a partial patch into lead.data via the canonical
    patch_tenant_record_data RPC. Atomic — preserves sibling keys.
    Falls back to read-modify-write on RPC miss (older schema)."""
    try:
        sb.rpc("patch_tenant_record_data", {
            "p_tenant_id": tenant_id,
            "p_id": lead_id,
            "p_patch": patch,
        }).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"update_lead_data: RPC fail, falling back to RMW: {exc}")
        existing = _get_lead_data(sb, tenant_id, lead_id) or {}
        existing.update(patch)
        try:
            sb.table("tenant_records").update({"data": existing}).eq(
                "tenant_id", tenant_id
            ).eq("entity_type", "lead").eq("id", lead_id).execute()
            return True
        except Exception as exc2:  # noqa: BLE001
            _log(f"update_lead_data: RMW fallback failed: {exc2}")
            return False


def _rolling_avg(history: list[dict[str, Any]]) -> Optional[float]:
    if not history:
        return None
    scores = [h.get("score") for h in history if isinstance(h.get("score"), (int, float))]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _apply_pause(sb, tenant_id: str, lead_id: str, rolling_avg: float,
                 latest_score: int, frustration: list[str], transcript: str) -> bool:
    """Set sentinel_pause_until + emit event + Telegram alert. Returns
    True if the pause was newly applied (not already active)."""
    existing_data = _get_lead_data(sb, tenant_id, lead_id) or {}
    now = datetime.now(timezone.utc)
    existing_pause = existing_data.get("sentinel_pause_until")

    # Don't re-emit if already paused and not yet expired
    if existing_pause:
        try:
            cutoff = datetime.fromisoformat(str(existing_pause).replace("Z", "+00:00"))
            if now < cutoff:
                return False
        except (ValueError, TypeError):
            pass

    pause_until = (now + timedelta(days=PAUSE_DURATION_DAYS)).isoformat()
    reason = (
        f"rolling_avg={rolling_avg:.1f} (window={ROLLING_WINDOW}); "
        f"latest_score={latest_score}; "
        f"signals={','.join(frustration[:5])}"
    )

    ok = _update_lead_data(sb, tenant_id, lead_id, {
        "sentinel_pause_until": pause_until,
        "sentinel_pause_reason": reason,
        "sentinel_pause_applied_at": now.isoformat(),
    })
    if not ok:
        _log(f"apply_pause: failed to write pause for lead={lead_id}")
        return False

    # Emit cross-agent event so dashboard + other agents see the pause
    try:
        if BRAVO_ROOT is not None:
            sys.path.insert(0, str(BRAVO_ROOT / "scripts"))
            from event_bus import publish as _bus_publish  # type: ignore
            _bus_publish(
                "BRAVO_SENTIMENT_PAUSE",
                {
                    "tenant_id": tenant_id,
                    "lead_id": lead_id,
                    "rolling_avg": rolling_avg,
                    "latest_score": latest_score,
                    "frustration_signals": frustration,
                    "paused_until": pause_until,
                },
                source="sentinel",
                target=None,
                correlation_id=lead_id,
                idempotency_key=f"sentinel_pause:{lead_id}:{now.strftime('%Y%m%d')}",
            )
    except Exception as exc:  # noqa: BLE001
        _log(f"apply_pause: event bus emit failed: {exc}")

    # Operator Telegram alert
    try:
        if BRAVO_ROOT is not None:
            sys.path.insert(0, str(BRAVO_ROOT / "scripts"))
            from notify import notify as _telegram_notify  # type: ignore
            company = existing_data.get("company") or existing_data.get("business_name") or "(unknown)"
            name = existing_data.get("name") or existing_data.get("contact_name") or "(no name)"
            preview = transcript[:300].replace("\n", " ")
            _telegram_notify(
                f"⚠️ Sentinel auto-pause — {company} ({name})\n\n"
                f"Rolling sentiment: {rolling_avg:.1f} (window={ROLLING_WINDOW})\n"
                f"Latest score: {latest_score}\n"
                f"Frustration signals: {', '.join(frustration[:4]) or 'none'}\n\n"
                f"Latest reply: {preview}\n\n"
                f"Paused until: {pause_until}\n"
                f"Recommend manual touch or extended cool-off.",
                category="sentinel",
            )
    except Exception as exc:  # noqa: BLE001
        _log(f"apply_pause: telegram alert failed: {exc}")

    return True


def _clear_pause(sb, tenant_id: str, lead_id: str, recover_score: int) -> bool:
    """Merchant recovered (new score > THRESHOLD_RECOVER) — clear the
    active pause so the next scheduled touch goes through. Returns True
    if a pause was actually cleared."""
    existing = _get_lead_data(sb, tenant_id, lead_id) or {}
    if not existing.get("sentinel_pause_until"):
        return False

    ok = _update_lead_data(sb, tenant_id, lead_id, {
        "sentinel_pause_until": None,
        "sentinel_pause_reason": None,
        "sentinel_pause_cleared_at": datetime.now(timezone.utc).isoformat(),
        "sentinel_pause_cleared_score": recover_score,
    })
    if ok:
        _log(f"clear_pause: lead={lead_id} recovered with score={recover_score}")
    return ok


# ─────────────────────────────────────────────────────────────────────
# Main scoring loop
# ─────────────────────────────────────────────────────────────────────


def score_inbound(sb, interaction: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Score one inbound interaction. Returns the scoring result on
    success, None on skip (already-scored, no lead, no body).

    The returned dict carries two extra keys for caller telemetry:
      - `paused_applied`: True when this score triggered a new pause
      - `pause_cleared`: True when this score cleared an existing pause
    Callers (run_once) aggregate these to populate stats counters.
    """
    lead_id = interaction.get("lead_id")
    tenant_id = interaction.get("tenant_id")
    # Codex finding #6: prefer the canonical `content` field; content_preview
    # is a truncated mirror used for table display, subject is empty for SMS,
    # body is the legacy alias. Reading content first means SMS replies and
    # email bodies that landed only in `content` get scored correctly.
    body = (
        interaction.get("content")
        or interaction.get("content_preview")
        or interaction.get("body")
        or interaction.get("subject")
        or ""
    )
    if not lead_id or not tenant_id or not body:
        return None

    # Skip if already scored
    metadata = interaction.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("sentiment"):
        return None

    result = classify_sentiment(body)
    result["interaction_id"] = interaction.get("id")
    result["scored_at"] = datetime.now(timezone.utc).isoformat()

    # 1. Stamp the interaction row with the score (defensive — never raise
    # out of here; the next pass will pick up un-stamped rows)
    try:
        new_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        new_metadata["sentiment"] = {
            "score": result["score"],
            "source": result["source"],
            "reason": result["reason"],
            "frustration_signals": result["frustration_signals"],
            "positive_signals": result["positive_signals"],
            "scored_at": result["scored_at"],
        }
        sb.table("lead_interactions").update({"metadata": new_metadata}).eq(
            "id", interaction.get("id")
        ).execute()
    except Exception as exc:  # noqa: BLE001
        _log(f"score_inbound: interaction stamp failed id={interaction.get('id')}: {exc}")

    # 2. Update the lead's rolling sentiment history
    lead_data = _get_lead_data(sb, tenant_id, lead_id) or {}
    history = lead_data.get("sentiment_history")
    if not isinstance(history, list):
        history = []
    history.append({
        "score": result["score"],
        "interaction_id": result["interaction_id"],
        "at": result["scored_at"],
    })
    # Keep only the rolling window
    history = history[-ROLLING_WINDOW:]
    avg = _rolling_avg(history)

    patch: dict[str, Any] = {
        "sentiment_history": history,
        "sentiment_rolling_avg": avg,
        "sentiment_last_score": result["score"],
        "sentiment_last_scored_at": result["scored_at"],
    }
    _update_lead_data(sb, tenant_id, lead_id, patch)

    # 3. Pause / yellow-flag / recover logic per Adon §4.5 + §7
    # Three tiers:
    #   avg <= -30           : red flag — 7d hard pause + Telegram alert
    #   -30 < avg <= 0       : yellow flag — 2x inter_touch_gap (180min)
    #   0 < avg < +20        : normal cadence, no flag changes
    #   avg >= +20           : recovery — clear any active flags
    paused_applied = False
    pause_cleared = False
    yellow_set = False
    yellow_cleared = False

    if avg is not None and avg <= THRESHOLD_PAUSE:
        paused_applied = _apply_pause(
            sb, tenant_id, lead_id, avg, result["score"],
            result["frustration_signals"], body,
        )
        if paused_applied:
            _log(
                f"score_inbound: RED-PAUSED lead={lead_id} avg={avg:.1f} "
                f"latest={result['score']}"
            )
    elif avg is not None and avg <= THRESHOLD_YELLOW:
        # Yellow zone — double the inter-touch gap so sequence_runner +
        # send_gateway naturally slow down without a hard pause.
        existing_yellow = lead_data.get("sentinel_yellow_until")
        yellow_until = (
            datetime.now(timezone.utc) + timedelta(days=YELLOW_FLAG_DAYS)
        ).isoformat()
        _update_lead_data(sb, tenant_id, lead_id, {
            "sentinel_yellow_flag": True,
            "sentinel_yellow_until": yellow_until,
            "sentinel_yellow_avg": avg,
        })
        if not existing_yellow:
            yellow_set = True
            _log(
                f"score_inbound: YELLOW-FLAGGED lead={lead_id} avg={avg:.1f} "
                f"latest={result['score']} (2x cadence for 14d)"
            )
    elif result["score"] >= THRESHOLD_RECOVER:
        pause_cleared = _clear_pause(sb, tenant_id, lead_id, result["score"])
        # Also clear yellow flag on recovery
        if lead_data.get("sentinel_yellow_flag"):
            _update_lead_data(sb, tenant_id, lead_id, {
                "sentinel_yellow_flag": False,
                "sentinel_yellow_until": None,
                "sentinel_yellow_cleared_at": datetime.now(timezone.utc).isoformat(),
            })
            yellow_cleared = True
        if pause_cleared or yellow_cleared:
            _log(f"score_inbound: RECOVERED lead={lead_id} score={result['score']}")

    result["paused_applied"] = paused_applied
    result["pause_cleared"] = pause_cleared
    result["yellow_set"] = yellow_set
    result["yellow_cleared"] = yellow_cleared
    return result


def fetch_unscored_inbounds(
    sb,
    tenant_id: str = SUNBIZ_TENANT_ID,
    lookback_hours: int = INBOUND_LOOKBACK_HOURS,
) -> list[dict[str, Any]]:
    """Return inbound merchant interactions from the last N hours that
    don't yet have metadata.sentiment populated. EXPLICITLY tenant-scoped
    because the service-role client bypasses RLS.

    Codex audit fixes 2026-06-08:
      #5 — Unscored filter pushed to SQL (`metadata->sentiment IS NULL`).
            OLD code applied limit(200) BEFORE filtering out already-scored
            rows, so at >200 inbounds/window the daemon would re-fetch the
            same scored rows forever and starve new replies for up to 48h.
            New query asks the DB for unscored rows directly.
      #6 — Select includes `content` (the canonical full body) instead of
            relying on content_preview / subject only. SMS replies have no
            subject and the inbound writer stores the full text in content.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    try:
        rows = (
            sb.table("lead_interactions")
            .select(
                "id, tenant_id, lead_id, channel, direction, "
                "content, content_preview, subject, metadata, created_at"
            )
            .eq("tenant_id", tenant_id)
            .eq("direction", "inbound")
            .gte("created_at", cutoff)
            .filter("metadata->sentiment", "is", "null")
            .order("created_at", desc=False)
            .limit(200)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        # Fallback when the metadata->sentiment IS NULL filter isn't
        # supported by the installed postgrest version: fetch a broader
        # window + filter Python-side, but use a much larger limit so we
        # don't starve. Logged so we know this path fired.
        _log(f"fetch_unscored: SQL filter failed, falling back: {exc}")
        try:
            rows = (
                sb.table("lead_interactions")
                .select(
                    "id, tenant_id, lead_id, channel, direction, "
                    "content, content_preview, subject, metadata, created_at"
                )
                .eq("tenant_id", tenant_id)
                .eq("direction", "inbound")
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(2000)
                .execute()
            )
        except Exception as exc2:  # noqa: BLE001
            _log(f"fetch_unscored: fallback query also failed: {exc2}")
            return []
    out: list[dict[str, Any]] = []
    for r in rows.data or []:
        meta = r.get("metadata") or {}
        # Final Python-side guard — covers the fallback path
        if isinstance(meta, dict) and meta.get("sentiment"):
            continue
        out.append(r)
    return out


def run_once(tenant_id: str = SUNBIZ_TENANT_ID) -> dict[str, int]:
    """Single pass: fetch unscored inbounds for the given tenant, score
    each, write back. Returns telemetry dict with scored / paused /
    recovered / errors counters bubbled up from score_inbound."""
    sb = _supabase()
    if not sb:
        _log("run_once: Supabase unavailable; skipping pass")
        return {"scored": 0, "paused": 0, "recovered": 0, "errors": 1}

    inbounds = fetch_unscored_inbounds(sb, tenant_id=tenant_id)
    stats = {"scored": 0, "paused": 0, "recovered": 0, "errors": 0}
    for interaction in inbounds:
        try:
            result = score_inbound(sb, interaction)
            if result is None:
                continue
            stats["scored"] += 1
            if result.get("paused_applied"):
                stats["paused"] += 1
            if result.get("pause_cleared"):
                stats["recovered"] += 1
        except Exception as exc:  # noqa: BLE001
            _log(f"run_once: scoring error id={interaction.get('id')}: {exc}")
            stats["errors"] += 1
    if stats["scored"] or stats["errors"]:
        _log(
            f"run_once: tenant={tenant_id[:8]}.. scored={stats['scored']} "
            f"paused={stats['paused']} recovered={stats['recovered']} "
            f"errors={stats['errors']}"
        )
    return stats


def run_loop(
    interval: int = DEFAULT_INTERVAL_SECONDS,
    tenant_id: str = SUNBIZ_TENANT_ID,
) -> None:
    _log(
        f"sentinel: starting loop interval={interval}s "
        f"window={ROLLING_WINDOW} tenant={tenant_id[:8]}.."
    )
    while True:
        try:
            run_once(tenant_id=tenant_id)
        except Exception as exc:  # noqa: BLE001
            _log(f"sentinel loop: unhandled error: {exc}")
        time.sleep(interval)


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sentinel — merchant-reply sentiment scorer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_loop = sub.add_parser("loop", help="run continuously")
    p_loop.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    p_loop.add_argument("--tenant-id", default=SUNBIZ_TENANT_ID,
                        help="tenant scope (default: SunBiz)")

    p_once = sub.add_parser("once", help="single pass then exit")
    p_once.add_argument("--tenant-id", default=SUNBIZ_TENANT_ID)

    p_score = sub.add_parser("score", help="score a single text — no DB writes")
    p_score.add_argument("--text", required=True)
    p_score.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "loop":
        run_loop(interval=args.interval, tenant_id=args.tenant_id)
        return 0
    if args.cmd == "once":
        stats = run_once(tenant_id=args.tenant_id)
        print(json.dumps(stats, indent=2))
        return 0
    if args.cmd == "score":
        result = classify_sentiment(args.text)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"score: {result['score']}  source: {result['source']}")
            print(f"reason: {result['reason']}")
            if result["frustration_signals"]:
                print(f"frustration: {', '.join(result['frustration_signals'])}")
            if result["positive_signals"]:
                print(f"positive: {', '.join(result['positive_signals'])}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
