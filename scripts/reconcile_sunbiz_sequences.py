"""
Reconcile drip_sequences in the live Sun Biz tenant against the
post-migration-064 seed in lib/sunbiz-default-sequences.ts.

The seed file is the source of truth for NEW tenants. Existing Sun Biz
tenant rows were seeded earlier (pre-064) and don't get touched when the
seed file is edited. This script reads the seed, then upserts each
sequence into the live drip_sequences table for Sun Biz — inserting
when missing, updating trigger_filter/steps when name matches but
content drifted, leaving untouched when already correct.

The seed list is hardcoded here (mirrors lib/sunbiz-default-sequences.ts)
because we don't run a Node interpreter from BEA. Keep in sync — if the
TS file gains a new sequence, add it here too.

Idempotent. Safe to re-run.

Usage:
  python scripts/reconcile_sunbiz_sequences.py            # apply changes
  python scripts/reconcile_sunbiz_sequences.py --dry-run  # report only
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from apply_migration import load_env  # noqa: E402


# Mirror of SUNBIZ_DEFAULT_SEQUENCES in lib/sunbiz-default-sequences.ts.
# Names are the upsert key — change carefully.
SEQUENCES: list[dict] = [
    {
        "name": "Follow-up sequence",
        "description": "Fires when a lead reaches the follow_up stage. 3-touch SMS+email cadence to get them on a call.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "follow_up"},
        "one_per_lead": True,
        "enabled": True,
        "steps": [
            {
                "channel": "sms",
                "delay_minutes": 10,
                "from_label": "Solara",
                "body": "Hi {{lead.contact_name}} — this is Solara at SunBiz Funding. Saw your business {{lead.business_name}} and wanted to see if you're looking at funding options for growth or working capital this quarter. Reply YES if you'd like options.",
            },
            {
                "channel": "email",
                "delay_minutes": 60 * 24,
                "from_label": "Solara",
                "subject": "Quick funding options for {{lead.business_name}}",
                "body": "Hi {{lead.contact_name}},\n\nFollowing up on yesterday's note — we work with operators like you to surface 3-5 lender offers in under 48h, no commitment to take any of them.\n\nWhat does your monthly revenue look like right now? If it's in the {{lead.monthly_revenue}} range we can almost certainly get you offers worth reviewing.\n\nReply with a good time today or tomorrow.\n\n— Solara, SunBiz Funding",
            },
            {
                "channel": "sms",
                "delay_minutes": 60 * 24 * 3,
                "from_label": "Solara",
                "body": "{{lead.contact_name}} — last note from me on funding. Send a 1-line reply (yes / not now / never) and I'll match the cadence. Otherwise I'll close out the thread on my end.",
            },
        ],
    },
    {
        "name": "Viewed application nudge",
        "description": "Fires when a lead opens their personalized application link. Nudges them through the form.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "viewed_application"},
        "one_per_lead": True,
        "enabled": True,
        "steps": [
            {
                "channel": "sms",
                "delay_minutes": 30,
                "from_label": "Solara",
                "body": "Hi {{lead.contact_name}} — saw you opened the application. Anything I can clarify? It's 3 quick steps — basic info, the app itself, then 3 months of bank statements at the end.",
            },
            {
                "channel": "email",
                "delay_minutes": 60 * 24,
                "from_label": "Solara",
                "subject": "Heads up on the application for {{lead.business_name}}",
                "body": "Hi {{lead.contact_name}},\n\nWanted to follow up — when you finish the application, the lenders we work with usually return 3-5 offers within 24-48h. The bank statements at step 3 are the gating piece; without them no underwriting can fire.\n\nIf anything's holding you up, reply here and I'll help.\n\n— Solara, SunBiz Funding",
            },
        ],
    },
    {
        # UW Sheet first-touch — mirrors "UW Sheet — qualified-deal first touch"
        # in lib/sunbiz-default-sequences.ts. Fires when Solara's scrubber lands
        # a qualified MCA deal in uw_sheet (post-Ezra approval).
        "name": "UW Sheet — qualified-deal first touch",
        "description": "Fires when a scrubbed MCA deal lands in uw_sheet (post-Ezra approval). 3-touch SMS+email first-contact cadence to book a call and collect bank statements.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "uw_sheet"},
        "one_per_lead": True,
        "enabled": True,
        "steps": [
            {
                "channel": "sms",
                "delay_minutes": 10,
                "from_label": "Solara",
                "body": "Hi {{lead.contact_name}} — Solara at SunBiz Funding. Your deal for {{lead.business_name}} pre-qualified with our lender network. Next step is a quick call plus 3 months of bank statements so we can price real offers. Reply with a good time today.",
            },
            {
                "channel": "email",
                "delay_minutes": 60 * 24,
                "from_label": "Solara",
                "subject": "{{lead.business_name}} pre-qualified — next step",
                "body": "Hi {{lead.contact_name}},\n\nFollowing up on my text — your file pre-qualified for funding options with our lender network. To turn that into real offers (usually 3-5 within 48h) I need two things: a 5-minute call and 3 months of bank statements (PDF exports from online banking).\n\nReply with a good time today or tomorrow and I'll take it from there.\n\n— Solara, SunBiz Funding",
            },
            {
                "channel": "sms",
                "delay_minutes": 60 * 24 * 3,
                "from_label": "Solara",
                "body": "{{lead.contact_name}} — last note on the pre-qualified funding for {{lead.business_name}}. Reply yes / not now / never and I'll match the cadence. Otherwise I'll close the file on my end.",
            },
        ],
    },
    # Drift RESOLVED 2026-07-06 (CC decision during the drip-repair session):
    #   - `submitted` stage was removed 2026-06-18 and has never enrolled a
    #     single lead → sequence kept but PAUSED (enabled=False). Body kept
    #     valid so the dashboard editor can open it.
    #   - `declined` still fires in production (48 live enrollments on
    #     2026-07-06) even though the TS seed retargeted new tenants to
    #     `ghost` → keep to:declined here, with the Ghost check-back copy.
    {
        "name": "Submitted — underwriting wait",
        "description": "Fires when a lead's application is fully submitted. Sets expectations + asks them to stay reachable.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "submitted"},
        "one_per_lead": True,
        "enabled": False,  # dead stage — paused per CC 2026-07-06
        "steps": [
            {
                "channel": "sms",
                "delay_minutes": 15,
                "from_label": "Solara",
                "body": "Hi {{lead.contact_name}} — your application is fully in. Underwriting usually returns offers within 24-48h. Keep your phone handy and I'll reach out the moment there's news. — Solara, SunBiz Funding",
            },
        ],
    },
    {
        "name": "Declined — 1-month check-back",
        "description": "Professional 1-month re-engagement for leads declined after bank-statement review. Doesn't burn the bridge.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "declined"},
        "one_per_lead": True,
        "enabled": True,
        "steps": [
            {
                "channel": "email",
                "delay_minutes": 60 * 24 * 30,
                "from_label": "Solara",
                "subject": "Checking in on {{lead.business_name}}",
                "body": "Hi {{lead.contact_name}},\n\nIt's been about a month since we last talked. Funding markets shift — what didn't fit last month sometimes does this month, especially if revenue's trending up or you've added new business.\n\nIf you're open to another look, send me an updated month of bank statements and I'll re-shop the file. No pressure — just want to keep the door open.\n\n— Solara, SunBiz Funding",
            },
        ],
    },
    {
        "name": "Missing info — chase + book call",
        "description": "Fires when a lead lands in missing_info. Two-touch cadence to request the outstanding info and book a call.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "missing_info"},
        "one_per_lead": True,
        "enabled": True,
        "steps": [
            {
                "channel": "sms",
                "delay_minutes": 30,
                "from_label": "Solara",
                "body": "Hi {{lead.contact_name}} — your file is one step from underwriting but we're missing a couple things. Reply here and I'll list what's outstanding, or text me a good time to call.",
            },
            {
                "channel": "email",
                "delay_minutes": 60 * 24 * 2,
                "from_label": "Solara",
                "subject": "Quick info to unblock {{lead.business_name}}",
                "body": "Hi {{lead.contact_name}},\n\nFollowing up — your file is sitting in our queue waiting on a couple data points before lenders can price it. Easiest path: reply here with a good time today or tomorrow for a 5-min call and we'll knock it out together.\n\n— Solara, SunBiz Funding",
            },
        ],
    },
    {
        "name": "Sent application — 24h reminder",
        "description": "Fires when an application link goes out. If the lead hasn't clicked through, send a soft 24h reminder.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "sent_application"},
        "one_per_lead": True,
        "enabled": True,
        "steps": [
            {
                "channel": "sms",
                "delay_minutes": 60 * 24,
                "from_label": "Solara",
                "body": "Hi {{lead.contact_name}} — quick reminder, your SunBiz application link is still active. Takes about 5 minutes. Reply if anything's blocking you and I'll help.",
            },
        ],
    },
    {
        "name": "Signed application — bank statements nag",
        "description": "Fires when a lead signs the application but hasn't uploaded bank statements yet.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "signed_application"},
        "one_per_lead": True,
        "enabled": True,
        "steps": [
            {
                "channel": "sms",
                "delay_minutes": 60 * 12,
                "from_label": "Solara",
                "body": "Nice — your application is signed. Last step is 3 months of bank statements (PDFs from your bank's online portal). Without them no lender can price the deal. Upload at the same link.",
            },
            {
                "channel": "email",
                "delay_minutes": int(60 * 24 * 1.5),
                "from_label": "Solara",
                "subject": "Last step for {{lead.business_name}} — bank statements",
                "body": "Hi {{lead.contact_name}},\n\nYour signed application is in. To unlock offers from our lender network, I need 3 months of bank statements (PDF exports from your online banking work great).\n\nUpload at the same application link. Underwriting fires automatically once they land.\n\n— Solara, SunBiz Funding",
            },
        ],
    },
    {
        "name": "Default — 60-day soft check-in (DISABLED by default)",
        "description": "Sensitive: fires 60 days after a lead's funded_deal defaults. Soft check-in only.",
        "trigger_event": "BRAVO_RECORD_STATUS_CHANGED",
        "trigger_filter": {"entity": "lead", "field": "stage", "to": "default"},
        "one_per_lead": True,
        "enabled": False,  # sensitive — operator must opt in
        "steps": [
            {
                "channel": "email",
                "delay_minutes": 60 * 24 * 60,
                "from_label": "Solara",
                "subject": "Checking in on {{lead.business_name}}",
                "body": "Hi {{lead.contact_name}},\n\nIt's been a while. I wanted to reach out and see how things are going on your end — no pitch attached, just a check-in.\n\nIf the business is back on its feet and you'd ever want to talk again, I'm here. If not, no harm done — just close out the thread and I'll respect that.\n\n— Solara, SunBiz Funding",
            },
        ],
    },
]


def validate_steps(steps: list) -> list[str]:
    """Guard added 2026-07-06 after the content-less-seed incident: this
    mirror once dropped body/subject from every step, and reconcile wrote
    those gutted steps into the live tenant — the runner then fired blanks
    for six weeks (941 enrollments, zero sent). Refuse to write any step
    the dashboard validator (lib/drips/types.ts) would reject."""
    problems = []
    if not isinstance(steps, list) or not steps:
        return ["steps must be a non-empty array"]
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            problems.append(f"$[{i}] not an object")
            continue
        if s.get("channel") not in ("sms", "email"):
            problems.append(f"$[{i}].channel invalid: {s.get('channel')!r}")
        if not isinstance(s.get("delay_minutes"), (int, float)):
            problems.append(f"$[{i}].delay_minutes invalid")
        body = s.get("body")
        if not isinstance(body, str) or not body.strip():
            problems.append(f"$[{i}].body empty/missing")
        if s.get("channel") == "email":
            subject = s.get("subject")
            if not isinstance(subject, str) or not subject.strip():
                problems.append(f"$[{i}].subject empty/missing")
    return problems


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    bad = {seq["name"]: validate_steps(seq["steps"]) for seq in SEQUENCES}
    bad = {name: probs for name, probs in bad.items() if probs}
    if bad:
        for name, probs in bad.items():
            print(f"[reconcile] INVALID mirror entry '{name}': {probs}")
        print("[reconcile] ABORT — refusing to write content-less steps to the live tenant.")
        return 1

    env = load_env()
    from supabase import create_client
    client = create_client(env["BRAVO_SUPABASE_URL"], env["BRAVO_SUPABASE_SERVICE_ROLE_KEY"])

    # Resolve Sun Biz tenant via tenant_manifests first, fall back to slug='submissions'.
    tm = client.table("tenant_manifests").select("tenant_id").eq("slug", "sun").maybe_single().execute()
    sun_tenant_id = (tm.data or {}).get("tenant_id") if tm else None
    if not sun_tenant_id:
        t = client.table("tenants").select("id").eq("slug", "submissions").maybe_single().execute()
        sun_tenant_id = (t.data or {}).get("id") if t else None
    if not sun_tenant_id:
        print("[reconcile] Sun Biz tenant not found — nothing to reconcile.")
        return 0
    print(f"[reconcile] tenant_id={sun_tenant_id}  dry_run={args.dry_run}")

    existing = (
        client.table("drip_sequences")
        .select("id, name, trigger_event, trigger_filter, steps, enabled, one_per_lead")
        .eq("tenant_id", sun_tenant_id)
        .execute()
    )
    by_name = {row["name"]: row for row in (existing.data or [])}
    print(f"[reconcile] {len(by_name)} existing sequence(s) on Sun Biz")

    inserted = updated = unchanged = 0
    for seq in SEQUENCES:
        existing_row = by_name.get(seq["name"])
        payload = {
            "tenant_id": sun_tenant_id,
            "name": seq["name"],
            "description": seq["description"],
            "trigger_event": seq["trigger_event"],
            "trigger_filter": seq["trigger_filter"],
            "steps": seq["steps"],
            "enabled": seq["enabled"],
            "one_per_lead": seq["one_per_lead"],
        }
        if not existing_row:
            print(f"  + INSERT  {seq['name']}")
            if not args.dry_run:
                client.table("drip_sequences").insert(payload).execute()
            inserted += 1
            continue
        drift = (
            existing_row.get("trigger_event") != seq["trigger_event"]
            or json.dumps(existing_row.get("trigger_filter"), sort_keys=True) != json.dumps(seq["trigger_filter"], sort_keys=True)
            or json.dumps(existing_row.get("steps"), sort_keys=True) != json.dumps(seq["steps"], sort_keys=True)
        )
        if drift:
            print(f"  ~ UPDATE  {seq['name']}")
            if not args.dry_run:
                client.table("drip_sequences").update(payload).eq("id", existing_row["id"]).execute()
            updated += 1
        else:
            unchanged += 1

    print(f"[reconcile] DONE — inserted={inserted}  updated={updated}  unchanged={unchanged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
