---
tags: [vps, sunbiz, breeze-uw, deploy, enricher, paste-prompt, task]
last_updated: 2026-07-03
---

# VPS Deploy — Breeze UW: extraction fix + Live Subs enricher (with dry-run gate)

Paste the fenced block below into a **Claude Code session running ON the SunBiz
production VPS**. It deploys the finished UW-sheet extraction fix and the new
`uw-lead-enricher` worker, backfills the existing Live Subs leads from their
source sheets (safe, no web calls), then **stops for CC's approval** before
turning on live web-enrichment (TruePeopleSearch/Firecrawl) + Ezra notifications.

**Context Bravo verified on Windows before handing this over (2026-07-02):**
- Extraction is fixed and mapped to every Command-Centre key. Proven against 36
  live filled sheets + a dry-run backfill of the 12 real leads (0 errors).
- **DOB, citizenship, and a numeric credit score are NOT on the UW Sheet 2.5
  template** — the "Credit" row is blank and credit is only an Experian report
  *link*. Those three dashboard fields will stay blank from the sheet; they can
  only come from enrichment. This is expected, not a bug.
- **Email/phone are blank on the UW sheets** (0/36 filled deals had them) — that
  is exactly what the enricher sources externally.

Do not paste secret values into Claude chat. If a key is missing, pause and have
CC enter it via `scripts/set_secret.py` (hidden input), which updates
`/srv/sunbiz/ceo-agent/.env.agents` safely.

```text
SYSTEM — VPS CLAUDE CODE TASK: deploy Breeze UW extraction fix + Live Subs enricher

You are Claude Code on the SunBiz production VPS. Deploy the merged UW pipeline
work and prove it live. The pipeline:

  Google Drive UW sheets -> mca-lead-scrubber -> Ezra Telegram approval ->
  Live Subs lead -> uw-lead-enricher (sheet backfill + contact enrichment).

SCOPE (work only here):
  - /srv/sunbiz/ceo-agent  and  /srv/sunbiz/sunbiz-agent
  - /srv/sunbiz/ceo-agent/.env.agents  (only via scripts/set_secret.py)
  - SunBiz tenant only: aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110
  - PM2: mca-lead-scrubber, ezra-telegram-bridge, uw-lead-enricher

DO NOT:
  - Do not print/cat/echo/paste secret values or merchant PII.
  - Do not modify .env.agents except through scripts/set_secret.py after CC confirms.
  - Do not push code from the VPS. Do not run destructive commands.
  - Do not send merchant messages.
  - Do NOT start uw-lead-enricher's live loop until CC has reviewed the dry-run
    and explicitly says: "enable the enricher".
  - Do not send a Telegram test packet unless CC explicitly says: "send the Telegram test packet".

STEP 1 — Pull the deployed code (no push)
  cd /srv/sunbiz/ceo-agent    && git fetch origin --prune && git status --short --branch && git log --oneline -1
  cd /srv/sunbiz/sunbiz-agent && git fetch origin --prune && git status --short --branch && git log --oneline -1
  If a repo has unexpected local changes, STOP and report them. If clean and behind
  main: git pull --ff-only. Confirm the SunBiz repo HEAD now includes the commit
  titled "sunbiz(uw): finish extraction fix + Live Subs enricher".

STEP 2 — Dependencies (ensures openpyxl etc.)
  PY=/srv/sunbiz/ceo-agent/.venv/bin/python
  cd /srv/sunbiz/sunbiz-agent && $PY -m pip install -r requirements.txt

STEP 3 — Redacted env audit (prints SET/MISSING + length only, never values)
  cd /srv/sunbiz/ceo-agent
  python3 - <<'PY'
  from pathlib import Path
  env_path = Path("/srv/sunbiz/ceo-agent/.env.agents")
  required = [
      "BRAVO_SUPABASE_URL","BRAVO_SUPABASE_SERVICE_ROLE_KEY","BRAVO_SUPABASE_ANON_KEY",
      "BRIDGE_BEARER_TOKEN","ANTHROPIC_API_KEY","GMAIL_USER","GMAIL_APP_PASSWORD",
      "SUNBIZ_AGENT_HMAC_SECRET","OASIS_OUTBOUND_HMAC_SECRET",
      "BREEZE_GOOGLE_CLIENT_ID","BREEZE_GOOGLE_CLIENT_SECRET","BREEZE_GOOGLE_REFRESH_TOKEN",
      "EZRA_TELEGRAM_BOT_TOKEN","EZRA_TELEGRAM_CHAT_ID","SIFT_PARSER_READY",
  ]
  optional = ["SIFT_SHEET_OWNER","SIFT_SHEET_TITLE_HINT","SIFT_SHEET_EXCLUDE",
              "UW_ENRICH_MAX_NOTIFY","UW_ENRICH_READY","FIRECRAWL_API_KEY"]
  def parse_env(p):
      d={}
      if not p.exists(): return d
      for raw in p.read_text(encoding="utf-8",errors="replace").splitlines():
          s=raw.strip()
          if not s or s.startswith("#") or "=" not in s: continue
          k,v=s.split("=",1); d[k.strip()]=v.strip().strip('"').strip("'")
      return d
  env=parse_env(env_path); missing=[]
  print("env_path_exists:",env_path.exists())
  for k in required:
      v=env.get(k,""); missing.append(k) if not v else None
      print(f"  {k}: {'SET' if v else 'MISSING'} len={len(v)}")
  print("optional:")
  for k in optional:
      v=env.get(k,""); print(f"  {k}: {'SET' if v else 'MISSING'} len={len(v)}")
  print("missing_required_csv:", ",".join(missing) if missing else "NONE")
  PY
  If any required key is MISSING, STOP and have CC run (values hidden):
    cd /srv/sunbiz/ceo-agent && .venv/bin/python scripts/set_secret.py
  then rerun this audit. Note: FIRECRAWL_API_KEY / UW_ENRICH_MAX_NOTIFY are optional
  (enricher defaults to a 5-notify/pass cap; TruePeopleSearch works without Firecrawl).

STEP 4 — Read-only doctors (must be green)
  PY=/srv/sunbiz/ceo-agent/.venv/bin/python
  cd /srv/sunbiz/sunbiz-agent
  $PY scripts/uw_lead_enricher.py doctor
  $PY scripts/mca_lead_scrubber.py doctor
  $PY scripts/scrubber/telegram_bridge.py getchats
  Expect: supabase OK; Breeze Drive creds all set; Drive discovery > 0; Firecrawl +
  research_fetch present; Ezra token/chat set; a "UW leads sampled / missing contact
  / needs sheet refresh" count. Report the counts (numbers only, no PII).

STEP 5 — LIVE safe backfill (fills sheet data on existing leads; NO web, NO Ezra)
  This repopulates the blank Live Subs detail panels (Frozen Ropes et al.) directly
  from each lead's source UW Sheet. It never calls the web and never messages Ezra.
  PY=/srv/sunbiz/ceo-agent/.venv/bin/python
  cd /srv/sunbiz/sunbiz-agent
  $PY scripts/uw_lead_enricher.py once --skip-web --force-refresh --limit 500
  Expect stats like: seen=N sheet_refreshed=N updated=N errors=0. Report the stats.

STEP 6 — Read-only DB proof (no PII values)
  PY=/srv/sunbiz/ceo-agent/.venv/bin/python
  cd /srv/sunbiz/sunbiz-agent
  $PY - <<'PY'
  import os
  from lib.secret_loader import load_env; load_env()
  from supabase import create_client
  sb=create_client(os.environ["BRAVO_SUPABASE_URL"], os.environ["BRAVO_SUPABASE_SERVICE_ROLE_KEY"])
  tid="aa04fa1f-ad6a-44b0-ac4b-2ff5d1067110"
  rows=(sb.table("tenant_records").select("id,data").eq("tenant_id",tid)
        .eq("entity_type","lead").order("created_at",desc=True).limit(50).execute().data or [])
  uw=[r for r in rows if (r.get("data") or {}).get("stage")=="uw_sheet"]
  def has(d,k): return bool((d or {}).get(k))
  print("uw_leads:",len(uw))
  for r in uw[:12]:
      d=r.get("data") or {}
      print("  lead", "biz="+("Y" if has(d,"business_name") else "n"),
            "ssn4="+("Y" if has(d,"owner_ssn_last4") else "n"),
            "tib="+("Y" if has(d,"time_in_business") else "n"),
            "industry="+("Y" if has(d,"industry") else "n"),
            "rev="+("Y" if has(d,"avg_monthly_revenue") else "n"),
            "pos="+("Y" if has(d,"open_mca_positions") else "n"),
            "email="+("Y" if has(d,"email") else "n"),
            "phone="+("Y" if has(d,"phone") else "n"))
  PY
  Expect: biz/ssn4/tib/industry/rev/pos now mostly "Y"; email/phone still "n" (the
  enricher fills those next). Report the row of Y/n flags (no names, no values).

STEP 7 — Dry-run web enrichment → SHOW CC, then PAUSE
  Shows the email/phone the enricher WOULD source for contact-less leads, with
  confidence + source, WITHOUT writing anything and WITHOUT messaging Ezra.
  (Dry runs show the FULL candidate set — the notify cap applies to live passes only.)
  PY=/srv/sunbiz/ceo-agent/.venv/bin/python
  cd /srv/sunbiz/sunbiz-agent
  $PY scripts/uw_lead_enricher.py once --dry-run --limit 500
  Present the dry-run lines to CC (they are masked previews). Then STOP and wait.
  Do NOT proceed to STEP 8 until CC says: "enable the enricher".

STEP 8 — Enable the live loop (ONLY after CC says: "enable the enricher")
  The loop is approval-gated: it IDLES as a no-op until UW_ENRICH_READY=1 exists in
  .env.agents. Starting the PM2 app without the flag is safe but does nothing.
  1. Have CC set the flag in the VPS terminal (hidden input; enter UW_ENRICH_READY
     with value 1):
       cd /srv/sunbiz/ceo-agent && .venv/bin/python scripts/set_secret.py
  2. Then:
       cd /srv/sunbiz/sunbiz-agent
       pm2 start ecosystem.config.js --only uw-lead-enricher
       pm2 restart uw-lead-enricher --update-env
       pm2 save
       pm2 status
       pm2 logs uw-lead-enricher --lines 30 --nostream
  Expect: uw-lead-enricher online, not crash-looping; a loop tick with a stats line
  (NOT "live loop DISABLED — idling"). Live-pass behavior: per-pass Ezra notify cap
  defaults to 5 (UW_ENRICH_MAX_NOTIFY); leads past the cap are DEFERRED whole to the
  next pass (never written without a verification notice), and web-sourced contacts
  revive failed drip steps only after the Ezra notice actually sends.

STEP 9 — Autonomy proof
  cd /srv/sunbiz/sunbiz-agent
  pm2 describe mca-lead-scrubber   >/dev/null || pm2 start ecosystem.config.js --only mca-lead-scrubber
  pm2 describe ezra-telegram-bridge>/dev/null || pm2 start ecosystem.config.js --only ezra-telegram-bridge
  pm2 restart mca-lead-scrubber ezra-telegram-bridge --update-env
  pm2 save && pm2 status
  Confirm mca-lead-scrubber, ezra-telegram-bridge, uw-lead-enricher are all online.
  These push status to integrations_health, so the Command-Centre Automations tab
  will flip pm2.uw-lead-enricher from DOWN to healthy.

STEP 10 — Final report to CC (exact shape)
  Changed: ...
  Why: ...
  Proof: each command run + the important non-secret output lines (stats, Y/n flags,
         pm2 status).
  Needs from CC: "nothing" or the specific missing keys/actions.
  State plainly whether the pipeline is fully live and autonomous, or which check
  blocked it and what CC must do next.
```

## Related
- [[docs/breeze-uw-enrichment-resume-message]]
- [[docs/VPS_BRINGUP]]
- [[brain/STATE]]
