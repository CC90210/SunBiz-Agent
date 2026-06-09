"""cron_registry.py — canonical SunBiz tenant cron schedule.

This is the source-of-truth registry for every SunBiz-owned scheduled job.
Rows live in `public.tenant_cron_jobs` (scoped to the SunBiz tenant_id) and
are dispatched by `claude-bridge-ping`'s tenant cron poller — NOT by the
empire `bravo-scheduler` and NOT in the empire `public.cron_jobs` table.

Why this file exists
--------------------
Before 2026-05-28 the three SunBiz daemon crons (Follow-up Generator,
Daily Plan Generator, Renewal Reminder) were seeded into CEO-Agent's
`scripts/core/cron_engine.py` SEED_JOBS array. That put them in the
empire `cron_jobs` table where they:

  1. Showed up on CC's OASIS `/automations` tab under the "Bravo (CEO)"
     group — a visible cross-tenant leak.
  2. Pointed at script paths (`scripts/follow_up_generator.py`) that
     no longer existed in CEO-Agent after the multi-root manifest
     cleanup (commits 6b9cefc8, 8c959e8d, a10b6abd, f025952d, fdf141a5)
     relocated SunBiz daemons here.

The fix (this file is the new home) routes them through
`tenant_cron_jobs` for `tenant_id = SUNBIZ_TENANT_ID` so they:

  - Appear on `/t/sun/automations` (correct tenant view).
  - Get polled + dispatched by `claude-bridge-ping` when the SunBiz
    VPS / Bravo's PC is online — using PROJECT_ROOT = SunBiz-Agent
    so the scripts resolve correctly.
  - Never leak into the empire operator's view (the OASIS dashboard
    API also filters empire rows through EMPIRE_AGENT_ALLOWLIST as
    defense-in-depth).

Companion docs
--------------
- ../docs/DAEMON_PLAYBOOK.md — per-daemon ops + manifest_key map.
- ../docs/VPS_BRINGUP.md — full cold-start runbook.
- CEO-Agent/scripts/core/cron_engine.py — empire-only SEED_JOBS
  (any new SunBiz row must NOT go there).
- oasis-command-center/app/api/cron-jobs/route.ts —
  EMPIRE_AGENT_ALLOWLIST defense-in-depth filter.

Seeding
-------
Re-seeding from a fresh DB:

    python scripts/core/cron_registry.py seed

This is idempotent (skip-by-name) so re-running is safe.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sunbiz_constants import SUNBIZ_TENANT_ID  # noqa: E402

SUNBIZ_TENANT_SLUG = "submissions"  # routed as "sun" by resolveClientProfileSlug


# Every entry below corresponds to one `tenant_cron_jobs` row. agent_key
# values must match the SunBiz manifest's agent palette (solara / helios)
# so the CronJobsManager groups them under the right header on
# /t/sun/automations.
#
# action_payload.script paths are repo-relative inside SunBiz-Agent.
# action_payload.root = "sunbiz" tells the bridge's cron_runner to
# resolve scripts against the SunBiz-Agent root (via agent_roots.DEFAULTS
# or the SUNBIZ_AGENT_ROOT / BRAVO_AGENT_ROOT_SUNBIZ env vars), NOT
# against CEO-Agent. Without the root field the bridge defaults to
# bravo and the cron fails with "script not found" every tick.
SEED_JOBS: list[dict] = [
    {
        "agent_key": "solara",
        "name": "SunBiz Follow-up Generator",
        "description": (
            "Daily 6am ET: generates follow_up_tasks for stuck / "
            "missing-info / no-response SunBiz leads. Operator drains "
            "via the dashboard Follow-Up Machine queue."
        ),
        "schedule": "0 6 * * *",
        "action_type": "script_run",
        "action_payload": {
            "script": "scripts/follow_up_generator.py",
            "args": ["once"],
            "root": "sunbiz",
        },
        "enabled": True,
    },
    {
        "agent_key": "solara",
        "name": "SunBiz Daily Plan Generator",
        "description": (
            "Daily 6:30am ET (after Follow-up Generator): six category "
            "passes (priority_call / missing_info / stuck / new_offer / "
            "shop_today / renewal_eligible) populate daily_plan_items "
            "for Solara's Daily Plan tab."
        ),
        "schedule": "30 6 * * *",
        "action_type": "script_run",
        "action_payload": {
            "script": "scripts/daily_plan_generator.py",
            "args": ["once"],
            "root": "sunbiz",
        },
        "enabled": True,
    },
    {
        "agent_key": "solara",
        "name": "SunBiz Renewal Reminder",
        "description": (
            "Daily 9am ET: scans funded deals at 40-50% through term, "
            "pushes Telegram alert + writes "
            "daily_plan_items.category=renewal_eligible. Honors per-tenant "
            "renewal_eligibility_threshold_pct manifest setting (default 40)."
        ),
        "schedule": "0 9 * * *",
        "action_type": "script_run",
        "action_payload": {
            "script": "scripts/renewal_reminder.py",
            "args": ["once"],
            "root": "sunbiz",
        },
        "enabled": True,
    },
]


def _load_env(repo_root: Path) -> dict[str, str]:
    env_path = repo_root / ".env.agents"
    if not env_path.exists():
        print(f"ERROR: {env_path} not found", file=sys.stderr)
        sys.exit(1)
    out: dict[str, str] = {}
    with env_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip()
    return out


def _get_client(env: dict[str, str]):
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: pip install supabase", file=sys.stderr)
        sys.exit(1)
    url = env.get("BRAVO_SUPABASE_URL")
    key = env.get("BRAVO_SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print(
            "ERROR: BRAVO_SUPABASE_URL / BRAVO_SUPABASE_SERVICE_ROLE_KEY "
            "missing from .env.agents",
            file=sys.stderr,
        )
        sys.exit(1)
    return create_client(url, key)


def cmd_seed(client) -> None:
    existing = client.table("tenant_cron_jobs").select("name").eq(
        "tenant_id", SUNBIZ_TENANT_ID
    ).execute()
    existing_names = {r["name"] for r in (existing.data or [])}

    inserted: list[dict] = []
    skipped: list[str] = []

    for spec in SEED_JOBS:
        if spec["name"] in existing_names:
            skipped.append(spec["name"])
            continue
        payload = {**spec, "tenant_id": SUNBIZ_TENANT_ID}
        result = client.table("tenant_cron_jobs").insert(payload).execute()
        if result.data:
            inserted.append(result.data[0])

    print(json.dumps({"inserted_count": len(inserted), "skipped": skipped}, indent=2))


def cmd_list(client) -> None:
    result = client.table("tenant_cron_jobs").select(
        "id, name, schedule, enabled, last_run_at, run_count"
    ).eq("tenant_id", SUNBIZ_TENANT_ID).order("name").execute()
    print(json.dumps(result.data or [], indent=2, default=str))


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    repo_root = Path(__file__).resolve().parents[2]
    env = _load_env(repo_root)
    client = _get_client(env)
    if cmd == "seed":
        cmd_seed(client)
    elif cmd == "list":
        cmd_list(client)
    else:
        print(f"Unknown command: {cmd}. Use 'seed' or 'list'.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
