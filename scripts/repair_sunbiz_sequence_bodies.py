"""
repair_sunbiz_sequence_bodies.py — one-off repair for the 2026-05-25 seeding
defect that left every SunBiz drip_sequences row without message content.

Root cause: the SEQUENCES mirror in reconcile_sunbiz_sequences.py dropped the
body/subject fields that exist in the true seed
(oasis-command-center/lib/sunbiz-default-sequences.ts). The live rows were
seeded from the gutted mirror, so the sequence-runner fired every step with an
empty body — 941 sequence_state rows, zero ever 'sent'.

This script writes the canonical steps (verbatim copy from
sunbiz-default-sequences.ts) into the live rows, keyed by row id AND name so a
mismatch aborts instead of clobbering the wrong row. Two operator-approved
deviations from the TS seed (CC, 2026-07-06):
  - "Declined — 1-month check-back" keeps its live trigger (stage `declined`
    demonstrably fires — 48 active enrollments) and takes the copy from the
    TS "Ghost — 1-month check-back" step.
  - "Submitted — underwriting wait" targets the removed `submitted` stage
    (zero enrollments ever) → gets a valid body so the editor can open it,
    and is PAUSED (enabled=false).

"Inquiry Welcomer" is intentionally untouched — its steps already carry full
content in the Phase-2 body_text/body_html shape the runner consumes.

Idempotent. Dry-run by default; pass --apply to write.

Usage:
  python scripts/repair_sunbiz_sequence_bodies.py            # report only
  python scripts/repair_sunbiz_sequence_bodies.py --apply    # write + verify
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load_env() -> dict:
    """lib/secret_loader resolves relative to whichever agent root provides it:
    SunBiz-Agent's own scripts/ on the VPS, Business-Empire-Agent's scripts/
    on the Windows operator machine (BRAVO_AGENT_ROOT override respected)."""
    import os
    candidates = [
        REPO_ROOT / "scripts",
        Path(os.environ.get("BRAVO_AGENT_ROOT", "")) / "scripts",
        Path.home() / "Business-Empire-Agent" / "scripts",
    ]
    for root in candidates:
        if (root / "lib" / "secret_loader.py").is_file():
            sys.path.insert(0, str(root))
            from lib.secret_loader import load_env  # type: ignore
            return load_env()
    raise RuntimeError("lib/secret_loader.py not found in any known agent root")

SUNBIZ_TENANT_ID = "aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110"

# Canonical repairs, keyed by live drip_sequences.id (queried 2026-07-06).
# "name" is an integrity check — if the row's name no longer matches, abort.
# Steps are verbatim from lib/sunbiz-default-sequences.ts unless noted.
REPAIRS: list[dict] = [
    {
        "id": "3ecd960f-8293-43c0-9429-18b451f326b2",
        "name": "Follow-up sequence",
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
        "id": "edbe4089-8a8e-449d-98ff-178050abd0ef",
        "name": "Viewed application nudge",
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
        # Dead stage (`submitted` removed 2026-06-18; zero enrollments ever).
        # CC 2026-07-06: pause it. Body kept valid so the editor can open it.
        "id": "91b1c917-acdd-4470-a879-39695eadcfff",
        "name": "Submitted — underwriting wait",
        "enabled": False,
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
        # Live trigger stays to:declined (48 active enrollments). Copy from the
        # TS "Ghost — 1-month check-back" step, which replaced this sequence in
        # the seed on 2026-06-18.
        "id": "11f069a8-f03b-48f3-9709-21d9a39740ba",
        "name": "Declined — 1-month check-back",
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
        "id": "84a81f3b-42d4-4a83-bfe9-e3ec3e9fe106",
        "name": "Missing info — chase + book call",
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
        "id": "8fc506b2-e809-44be-bdf2-2ce0ba575014",
        "name": "Sent application — 24h reminder",
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
        "id": "c2e57dd7-55f5-4123-9766-3e5aab791ea8",
        "name": "Signed application — bank statements nag",
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
        "id": "d127cf7c-e165-44c4-9c9c-7a0268ae9aac",
        "name": "Default — 60-day soft check-in (DISABLED by default)",
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
    """Strict dashboard-schema validation (mirrors lib/drips/types.ts)."""
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
        # Accept both step shapes, matching the runner (body_text || body)
        # and the dashboard parser (lib/drips/types.ts, 2026-07-06).
        body = s.get("body")
        body_text = s.get("body_text")
        has_content = (isinstance(body, str) and body.strip()) or (
            isinstance(body_text, str) and body_text.strip()
        )
        if not has_content:
            problems.append(f"$[{i}].body empty/missing")
        if s.get("channel") == "email":
            subject = s.get("subject")
            if not isinstance(subject, str) or not subject.strip():
                problems.append(f"$[{i}].subject empty/missing")
    return problems


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = p.parse_args()

    # Self-check the payloads before touching anything.
    for rep in REPAIRS:
        probs = validate_steps(rep["steps"])
        if probs:
            print(f"ABORT — repair payload for '{rep['name']}' is itself invalid: {probs}")
            return 1

    env = _load_env()
    from supabase import create_client
    client = create_client(env["BRAVO_SUPABASE_URL"], env["BRAVO_SUPABASE_SERVICE_ROLE_KEY"])

    live = (
        client.table("drip_sequences")
        .select("id, name, enabled, steps")
        .eq("tenant_id", SUNBIZ_TENANT_ID)
        .execute()
    )
    by_id = {row["id"]: row for row in (live.data or [])}
    print(f"[repair] {len(by_id)} live sequence(s) on tenant {SUNBIZ_TENANT_ID}  apply={args.apply}")

    updated = skipped = 0
    for rep in REPAIRS:
        row = by_id.get(rep["id"])
        if not row:
            print(f"  ! MISSING  {rep['name']} ({rep['id']}) — not in live table, skipping")
            continue
        if row["name"] != rep["name"]:
            print(f"  ! NAME MISMATCH for {rep['id']}: live='{row['name']}' expected='{rep['name']}' — ABORT")
            return 1
        payload: dict = {"steps": rep["steps"]}
        if "enabled" in rep:
            payload["enabled"] = rep["enabled"]
        same_steps = json.dumps(row.get("steps"), sort_keys=True) == json.dumps(rep["steps"], sort_keys=True)
        same_enabled = ("enabled" not in rep) or (row.get("enabled") == rep["enabled"])
        if same_steps and same_enabled:
            print(f"  = OK       {rep['name']} (already repaired)")
            skipped += 1
            continue
        n_bodies = sum(1 for s in rep["steps"] if s.get("body"))
        flag = "" if "enabled" not in rep else f" + enabled={rep['enabled']}"
        print(f"  ~ REPAIR   {rep['name']}: {len(rep['steps'])} step(s), {n_bodies} bodies restored{flag}")
        if args.apply:
            client.table("drip_sequences").update(payload).eq("id", rep["id"]).execute()
        updated += 1

    print(f"[repair] {'applied' if args.apply else 'DRY-RUN'} — updated={updated} unchanged={skipped}")

    if args.apply:
        # Post-write verification: re-read and validate every row we manage.
        check = (
            client.table("drip_sequences")
            .select("id, name, steps")
            .eq("tenant_id", SUNBIZ_TENANT_ID)
            .execute()
        )
        failures = 0
        for row in check.data or []:
            probs = validate_steps(row.get("steps") or [])
            if probs:
                print(f"  VERIFY FAIL  {row['name']}: {probs}")
                failures += 1
        print(f"[repair] post-write verification: {'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
        return 0 if failures == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
