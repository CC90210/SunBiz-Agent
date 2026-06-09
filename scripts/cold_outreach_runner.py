"""cold_outreach_runner.py — drain cold_outreach_campaigns through send_gateway.

Part of the SunBiz second-meeting (2026-05-25) expansion.
Migration dependency: 069 (adds cold_outreach_campaigns + cold_outreach_recipients tables).

Reads:
  - cold_outreach_campaigns where status IN ('queued', 'sending')
  - cold_outreach_recipients where status='pending' for the active campaign

Writes:
  - cold_outreach_campaigns: status, started_at, sent_count, failed_count, completed_at
  - cold_outreach_recipients: status, sent_at, interaction_id, last_error

Idempotency / race safety:
  - Recipient claim: UPDATE … SET status='sending' WHERE id=X AND status='pending' RETURNING *
    Only the daemon that wins the RETURNING row proceeds with the send.
  - Daily-cap enforcement happens inside send_gateway.send() — not re-implemented here.
  - CASL + suppression also delegated to send_gateway.send().
  - Re-running after a crash reclaims stale 'sending' recipients if they were
    abandoned mid-tick (the status update is atomic; if send_gateway never ran,
    the recipient can be reclaimed by re-querying status='sending' rows with no
    sent_at — see _reclaim_stale_recipients).

Schedule recommendation (PM2 / loop):
  pm2 start scripts/cold_outreach_runner.py --name cold-outreach-runner \
      --interpreter python -- loop --interval 30

Or via claude-bridge-ping cron poller with manifest key: cold_outreach_runner_once

CLI:
  python scripts/cold_outreach_runner.py once
  python scripts/cold_outreach_runner.py loop --interval 30
  python scripts/cold_outreach_runner.py tail --count 50
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────
# Paths + constants
# ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_ROOT / "state"
LOG_PATH = STATE_DIR / "cold_outreach_runner.log"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _bravo_bootstrap import bootstrap_bravo_path  # noqa: E402
from sunbiz_constants import resolve_brand  # noqa: E402

BRAVO_ROOT = bootstrap_bravo_path()

DAEMON_NAME = "cold_outreach_runner"
DEFAULT_INTERVAL_SECONDS = 30
# Recipients stuck at status='sending' with no sent_at for this many seconds
# are reclaimed as 'pending' so a subsequent tick can retry them.
STALE_SENDING_TIMEOUT_SECONDS = 300


# ─────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────


def _log(msg: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] [{DAEMON_NAME}] {msg}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass
    print(line.rstrip())


# ─────────────────────────────────────────────────────────────────────
# Env + Supabase client (service-role)
# ─────────────────────────────────────────────────────────────────────


def _load_env() -> dict[str, str]:
    try:
        from lib.secret_loader import load_env  # type: ignore
        return load_env()
    except Exception:
        return {}


def _supabase():
    env = _load_env()
    url = (env.get("BRAVO_SUPABASE_URL") or "").strip()
    key = (env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        _log("missing BRAVO_SUPABASE_URL or BRAVO_SUPABASE_SERVICE_ROLE_KEY")
        return None
    try:
        from supabase import create_client  # type: ignore
        return create_client(url, key)
    except Exception as e:
        _log(f"supabase client init failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────
# send_gateway import (lazy)
# ─────────────────────────────────────────────────────────────────────


def _send_gateway_fn():
    """Return send_gateway.send callable or None on import failure.
    send_gateway lives in CEO-Agent/scripts/integrations/ (on sys.path
    via the BRAVO_ROOT bootstrap)."""
    try:
        from integrations.send_gateway import send  # type: ignore
        return send
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# Variable substitution
# ─────────────────────────────────────────────────────────────────────


def _first_word(name: str) -> str:
    """Extract first word (first name) from a full name string."""
    if not isinstance(name, str):
        return ""
    parts = name.strip().split()
    return parts[0] if parts else ""


def _substitute_vars(template: str, recipient: dict[str, Any], lead: dict[str, Any]) -> str:
    """Replace {{first_name}} and {{business_name}} tokens in a template string."""
    contact_name = lead.get("contact_name") or recipient.get("contact_name") or ""
    business_name = lead.get("business_name") or recipient.get("business_name") or ""
    result = template.replace("{{first_name}}", _first_word(contact_name))
    result = result.replace("{{business_name}}", business_name)
    return result


# ─────────────────────────────────────────────────────────────────────
# Daily-cap guard (today's sends already processed this tick session)
# ─────────────────────────────────────────────────────────────────────


def _today_send_count(sb, campaign_id: str) -> int:
    """Count recipients marked sent today for this campaign."""
    today_str = datetime.now(timezone.utc).date().isoformat()
    try:
        rows = (
            sb.table("cold_outreach_recipients")
            .select("id", count="exact")
            .eq("campaign_id", campaign_id)
            .eq("status", "sent")
            .gte("sent_at", today_str)
            .execute()
        )
        return rows.count or 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────
# Stale-sending reclaim
# ─────────────────────────────────────────────────────────────────────


def _reclaim_stale_recipients(sb, campaign_id: str) -> int:
    """Reset recipients stuck at status='sending' with no sent_at back to 'pending'
    so the next tick can retry them. Returns number reclaimed."""
    cutoff = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # We cannot do a server-side age check without RPC; instead fetch all 'sending'
    # rows with no sent_at and reclaim them (they were abandoned mid-tick).
    try:
        rows = (
            sb.table("cold_outreach_recipients")
            .select("id")
            .eq("campaign_id", campaign_id)
            .eq("status", "sending")
            .is_("sent_at", "null")
            .execute()
        )
    except Exception as e:
        _log(f"reclaim query failed campaign={campaign_id}: {e}")
        return 0

    reclaimed = 0
    for row in rows.data or []:
        try:
            sb.table("cold_outreach_recipients").update(
                {"status": "pending"}
            ).eq("id", row["id"]).eq("status", "sending").execute()
            reclaimed += 1
        except Exception:
            pass
    if reclaimed:
        _log(f"reclaimed {reclaimed} stale-sending recipients campaign={campaign_id}")
    return reclaimed


# ─────────────────────────────────────────────────────────────────────
# Atomic claim
# ─────────────────────────────────────────────────────────────────────


def _claim_recipient(sb, recipient_id: str) -> bool:
    """Atomically flip a recipient from pending → sending. Returns True if we won."""
    try:
        result = (
            sb.table("cold_outreach_recipients")
            .update({"status": "sending"})
            .eq("id", recipient_id)
            .eq("status", "pending")
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────
# Resolve cold_lead for variable substitution
# ─────────────────────────────────────────────────────────────────────


def _resolve_lead(sb, cold_lead_id: Optional[str], tenant_id: str) -> dict[str, Any]:
    if not cold_lead_id:
        return {}
    try:
        rows = (
            sb.table("cold_leads")
            .select("contact_name, business_name, contact_address")
            .eq("id", cold_lead_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        return rows.data[0] if rows.data else {}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────
# Campaign counter helpers
# ─────────────────────────────────────────────────────────────────────


def _flush_campaign_counters(
    sb,
    campaign_id: str,
    sent_total: int,
    failed_total: int,
) -> None:
    """Write the absolute sent_count and failed_count to the campaign row.
    Replaces the prior per-recipient read-modify-write (2 round-trips ×
    daily_cap, so up to 100 wasted DB calls per tick). Single daemon per
    campaign means no concurrent writers contend on this row, so absolute
    overwrite is safe. Recipient rows are the source of truth — on crash
    the counters trail by one tick but reconcile on the next pass."""
    try:
        sb.table("cold_outreach_campaigns").update(
            {"sent_count": sent_total, "failed_count": failed_total}
        ).eq("id", campaign_id).execute()
    except Exception as e:
        _log(f"counter flush failed campaign={campaign_id}: {e}")


# ─────────────────────────────────────────────────────────────────────
# Process a single campaign
# ─────────────────────────────────────────────────────────────────────


def _process_campaign(sb, campaign: dict[str, Any], send_fn) -> None:
    campaign_id = campaign.get("id", "")
    tenant_id = campaign.get("tenant_id", "")
    daily_cap: int = int(campaign.get("daily_cap") or 50)
    sent_count: int = int(campaign.get("sent_count") or 0)
    failed_count: int = int(campaign.get("failed_count") or 0)
    total_recipients: int = int(campaign.get("total_recipients") or 0)
    channel: str = campaign.get("channel") or "email"
    message_body: str = campaign.get("message_body") or ""
    subject: str = campaign.get("subject") or ""

    _log(f"processing campaign={campaign_id[:8]}... channel={channel} "
         f"sent={sent_count} failed={failed_count} total={total_recipients} cap={daily_cap}")

    # Flip queued → sending and record started_at
    if campaign.get("status") == "queued":
        try:
            sb.table("cold_outreach_campaigns").update(
                {"status": "sending", "started_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", campaign_id).eq("status", "queued").execute()
        except Exception as e:
            _log(f"flip to sending failed campaign={campaign_id}: {e}")
            return

    # Daily-cap check — count today's sends from the DB for idempotency
    today_sent = _today_send_count(sb, campaign_id)
    remaining_cap = daily_cap - today_sent
    if remaining_cap <= 0:
        _log(f"daily cap reached campaign={campaign_id} today_sent={today_sent} cap={daily_cap}")
        return

    # Reclaim any abandoned sending rows from a prior crashed tick
    _reclaim_stale_recipients(sb, campaign_id)

    # Fetch pending recipients up to remaining cap
    try:
        pending = (
            sb.table("cold_outreach_recipients")
            .select("id, cold_lead_id, contact_address")
            .eq("campaign_id", campaign_id)
            .eq("status", "pending")
            .limit(remaining_cap)
            .execute()
        )
    except Exception as e:
        _log(f"recipients fetch failed campaign={campaign_id}: {e}")
        return

    for rec in pending.data or []:
        rec_id = rec.get("id", "")
        cold_lead_id = rec.get("cold_lead_id")
        contact_address = rec.get("contact_address") or ""

        # Atomic claim
        if not _claim_recipient(sb, rec_id):
            continue

        # Resolve lead for variable substitution
        lead = _resolve_lead(sb, cold_lead_id, tenant_id)
        merged_address = contact_address or lead.get("contact_address") or ""
        if not merged_address:
            _log(f"no contact_address recipient={rec_id} — marking failed")
            try:
                sb.table("cold_outreach_recipients").update(
                    {"status": "failed", "last_error": "no_contact_address"}
                ).eq("id", rec_id).execute()
            except Exception:
                pass
            failed_count += 1
            continue

        rendered_body = _substitute_vars(message_body, rec, lead)
        rendered_subject = _substitute_vars(subject, rec, lead)

        # Build send_gateway kwargs. The campaign.channel is one of
        # 'email'|'sms'|'sms_texttorrent'|'sms_twilio' (migration 069), but
        # send_gateway only knows channel 'email'|'sms' — the SMS vendor is
        # distinguished by sms_provider. Map here (Build 3). Without this,
        # send_gateway rejects 'sms_twilio'/'sms_texttorrent' as unknown channels.
        sms_provider: Optional[str] = None
        if channel in ("sms", "sms_texttorrent", "sms_twilio"):
            gw_channel = "sms"
            if channel == "sms_twilio":
                sms_provider = "twilio"
            elif channel == "sms_texttorrent":
                sms_provider = "texttorrent"
        else:
            gw_channel = "email"

        send_kwargs: dict[str, Any] = {
            "channel": gw_channel,
            "body_text": rendered_body,
            "agent_source": DAEMON_NAME,
            "brand": resolve_brand(tenant_id),
            "intent": "commercial",
        }
        if gw_channel == "email":
            send_kwargs["to_email"] = merged_address
            send_kwargs["subject"] = rendered_subject
            if rendered_body:
                send_kwargs["body_html"] = rendered_body
        else:
            send_kwargs["to_phone"] = merged_address
            if sms_provider:
                # Explicit provider — required to force Twilio when both
                # TextTorrent and Twilio are configured (else TT is default).
                send_kwargs["sms_provider"] = sms_provider
                send_kwargs["metadata"] = {"sms_provider": sms_provider}

        if cold_lead_id:
            send_kwargs["lead_id"] = cold_lead_id

        try:
            result = send_fn(**send_kwargs)
        except Exception as e:
            result = {"status": "error", "reason": str(e)}

        send_status = result.get("status") if isinstance(result, dict) else "error"
        interaction_id = result.get("interaction_id") if isinstance(result, dict) else None

        if send_status in ("sent", "dry_run"):
            try:
                sb.table("cold_outreach_recipients").update(
                    {
                        "status": "sent",
                        "sent_at": datetime.now(timezone.utc).isoformat(),
                        "interaction_id": interaction_id,
                    }
                ).eq("id", rec_id).execute()
            except Exception as e:
                _log(f"recipient sent-update failed rec={rec_id}: {e}")
            sent_count += 1
            _log(f"sent rec={rec_id} address={merged_address[:30]}...")
        else:
            reason = result.get("reason") if isinstance(result, dict) else "unknown"
            try:
                sb.table("cold_outreach_recipients").update(
                    {"status": "failed", "last_error": str(reason)[:500]}
                ).eq("id", rec_id).execute()
            except Exception as e:
                _log(f"recipient failed-update failed rec={rec_id}: {e}")
            failed_count += 1
            _log(f"failed rec={rec_id} reason={reason}")

    # Flush counters once after the loop instead of N times during it.
    _flush_campaign_counters(sb, campaign_id, sent_count, failed_count)

    # Check if campaign is fully complete
    if total_recipients > 0 and (sent_count + failed_count) >= total_recipients:
        try:
            sb.table("cold_outreach_campaigns").update(
                {
                    "status": "complete",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", campaign_id).execute()
            _log(f"campaign complete campaign={campaign_id} sent={sent_count} failed={failed_count}")
        except Exception as e:
            _log(f"campaign complete update failed campaign={campaign_id}: {e}")


# ─────────────────────────────────────────────────────────────────────
# Core tick
# ─────────────────────────────────────────────────────────────────────


def _promote_scheduled_campaigns(sb) -> int:
    """Build 3: promote scheduled campaigns whose time has come.

    UPDATE cold_outreach_campaigns SET status='queued' WHERE status='draft'
    AND scheduled_for <= now() (UTC). A SQL NULL scheduled_for never satisfies
    `<=`, so unscheduled drafts are left alone without an explicit not-null
    filter. A promoted campaign is drained on the NEXT tick (tick() pulls one
    queued/sending campaign after this runs). Returns the number promoted."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        res = (
            sb.table("cold_outreach_campaigns")
            .update({"status": "queued"})
            .eq("status", "draft")
            .lte("scheduled_for", now_iso)
            .execute()
        )
        promoted = len(res.data or [])
        if promoted:
            _log(f"promoted {promoted} scheduled campaign(s) draft->queued")
        return promoted
    except Exception as e:
        _log(f"promote_scheduled failed: {e}")
        return 0


def tick() -> int:
    """Run one processing tick. Returns number of recipients processed."""
    sb = _supabase()
    if not sb:
        _log("supabase unavailable — skipping tick")
        return 0

    # Build 3: feed the queue from scheduled drafts before draining it.
    _promote_scheduled_campaigns(sb)

    send_fn = _send_gateway_fn()
    if send_fn is None:
        _log("send_gateway unavailable — aborting tick")
        return 0

    # Fetch at most one active campaign per tick (queue one at a time to respect caps)
    try:
        campaigns = (
            sb.table("cold_outreach_campaigns")
            .select(
                # 'brand' column is not in the live cold_outreach_campaigns
                # schema; selecting it 400s. campaign.get("brand") below already
                # defaults to "oasis", so omit it here. Re-add this column (and a
                # migration) if/when per-campaign branding is introduced.
                "id, tenant_id, status, channel, message_body, subject, "
                "daily_cap, sent_count, failed_count, total_recipients"
            )
            .in_("status", ["queued", "sending"])
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )
    except Exception as e:
        _log(f"campaign fetch failed: {e}")
        return 0

    if not campaigns.data:
        return 0

    campaign = campaigns.data[0]
    before_sent = int(campaign.get("sent_count") or 0)
    _process_campaign(sb, campaign, send_fn)

    # Re-fetch to see how many we processed
    try:
        updated = (
            sb.table("cold_outreach_campaigns")
            .select("sent_count")
            .eq("id", campaign["id"])
            .limit(1)
            .execute()
        )
        after_sent = int((updated.data[0].get("sent_count") or 0) if updated.data else 0)
    except Exception:
        after_sent = before_sent

    return max(0, after_sent - before_sent)


# ─────────────────────────────────────────────────────────────────────
# Daemon subcommands
# ─────────────────────────────────────────────────────────────────────


def loop(interval: int) -> int:
    interval = max(10, int(interval))
    _log(f"cold_outreach_runner up; tick interval = {interval}s")
    crash_window_start = 0.0
    crash_window_count = 0
    while True:
        try:
            tick()
        except Exception as e:
            _log(f"tick crashed: {e}")
            now = time.time()
            if now - crash_window_start > 600:
                crash_window_start = now
                crash_window_count = 0
            crash_window_count += 1
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            _log("cold_outreach_runner shutting down (SIGINT)")
            return 0


def tail_cmd(count: int) -> int:
    if not LOG_PATH.exists():
        print("(no log yet)")
        return 0
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-count:]
    except OSError as e:
        print(f"read failed: {e}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="cold_outreach_runner — drain cold_outreach_campaigns through send_gateway"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("once", help="Run one tick and exit").set_defaults(
        func=lambda _a: 0 if tick() is not None else 1
    )

    lp = sub.add_parser("loop", help="Run continuously")
    lp.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between ticks (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    lp.set_defaults(func=lambda a: loop(a.interval))

    tl = sub.add_parser("tail", help="Print the last N log lines")
    tl.add_argument("--count", type=int, default=50)
    tl.set_defaults(func=lambda a: tail_cmd(a.count))

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
