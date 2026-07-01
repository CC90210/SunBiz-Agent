SYSTEM — VPS DEPLOY AGENT: "Breeze UW Entry Sheet" + Ezra Telegram Approvals

OBJECTIVE
Deploy and run the complete Breeze UW deal automation on this VPS: a scrubber that
scores Breeze's per-deal UW Sheets and sends the qualifiers to Ezra's Telegram, and
a bridge that turns Ezra's Approve tap into a lead in the SunBiz Agent Command Centre
at the "Live Subs" pipeline stage. Two always-on PM2 workers. Solara owns this.

THE FLOW (end to end)
  Breeze Google Drive — per-deal "UW Sheet" workbooks, owned by Submissions@breezeadvance.com
   └─ WORKER 1 · mca-lead-scrubber (every ~120s):
        discover new UW Sheets (authed as aiscrubbing@breezeadvance.com, read-only)
        → parse the "UW Sheet 2.5" tab (one deal per file)
        → SCORE per CC's rules:
             • True Revenue (avg) ≥ $80,000/mo
             • active leverage < 40%  (sum of DAILY/WEEKLY funders only; excludes
               paid-off positions + the Breeze Advance row; monthly lenders are not positions)
             • 2-4 active funders  (>4 allowed only if leverage < 40%)
             • industry NOT in {trucking, accounting, law, transportation, cannabis, auto sales, solar}
             • ISO/broker is NOT "Nationwide Advance"
             • Data Merge Notes == "Clean"  (a report/flag = decline)
             • Previously Submitted = Yes → strong positive (does NOT override the 40% cap)
        → stage qualifying deals to scrub_candidates
        → SEND each to Ezra's Telegram (deal packet incl. lender names + Approve/Deny buttons)
   └─ WORKER 2 · ezra-telegram-bridge (long-poll):
        watches Ezra's Approve/Deny taps
          Approve → create the lead at the "Live Subs" (internal key: uw_sheet) stage +
                    emit BRAVO_RECORD_STATUS_CHANGED → autonomous follow-up drip fires
          Deny    → mark the candidate declined, stop
  No deal enters the Command Centre without Ezra's approval. The daemons never send
  merchant messages (the follow-up drip does that, through send_gateway).

ALREADY DONE (verify only — do NOT redo)
  - DB migration 081 (scrub_candidates) is APPLIED to the bravo Supabase.
  - Backend code is MERGED TO main (SunBiz-Agent) — pull main, no feature branch needed.
  - Frontend is LIVE (deployed 2026-06-30, oasis-command-center main → Vercel): the
    "Live Subs" (uw_sheet) stage renders in the Lead Pipeline above Hot Lead, and both
    workers are registered in the Automations tab. Nothing to deploy on the frontend.

PATHS
  - Repo:  /srv/sunbiz/sunbiz-agent
  - PY:    /srv/sunbiz/ceo-agent/.venv/bin/python
  - Agent env file: /srv/sunbiz/ceo-agent/.env.agents
  - PM2 workers: mca-lead-scrubber, ezra-telegram-bridge  (both IS_LINUX-gated, single-instance)

REQUIRED ENV (CC has these on the Mac — copy the SAME values into the agent env file here)
  BREEZE_GOOGLE_CLIENT_ID / BREEZE_GOOGLE_CLIENT_SECRET / BREEZE_GOOGLE_REFRESH_TOKEN   (Drive auth)
  EZRA_TELEGRAM_BOT_TOKEN / EZRA_TELEGRAM_CHAT_ID                                        (Telegram)
  (BRAVO_SUPABASE_URL / BRAVO_SUPABASE_SERVICE_ROLE_KEY already present)

STEPS
  1. cd /srv/sunbiz/sunbiz-agent
     git fetch --all && git checkout main && git pull   # backend is merged to main
  2. PY=/srv/sunbiz/ceo-agent/.venv/bin/python
     $PY -m pip install -r requirements.txt
     # installs: openpyxl, google-auth, google-api-python-client, google-auth-oauthlib
  3. Confirm the REQUIRED ENV keys above are present in the agent env file.
  4. DOCTOR (read-only — proves Drive auth as Breeze + sheet discovery):
     $PY scripts/mca_lead_scrubber.py doctor
     REQUIRED: supabase ok · Breeze Drive creds all set · Drive access OK · candidate sheets found N (>0)
  5. TELEGRAM check:
     $PY scripts/scrubber/telegram_bridge.py getchats
     REQUIRED: bot @Dolphin2005_bot ok=True · Ezra's chat_id listed · EZRA_TELEGRAM_CHAT_ID set
  6. DRY-RUN the spread (read-only — no writes, no Telegram, gate-bypassed):
     $PY scripts/mca_lead_scrubber.py once --dry-run --limit 25
     Expect a sensible good/review/bad split. Sanity-check with CC BEFORE going live.
  7. GO-LIVE — flip the gate: add this one line to the agent env file →  SIFT_PARSER_READY=1
  8. Start both workers:
     cd /srv/sunbiz/sunbiz-agent
     pm2 start ecosystem.config.js --only mca-lead-scrubber --only ezra-telegram-bridge
     pm2 save
  9. Watch:
     pm2 logs ezra-telegram-bridge --lines 20 --nostream   # expect "polling as @Dolphin2005_bot"
     pm2 logs mca-lead-scrubber   --lines 30 --nostream     # expect "staged [good] <business>"
     The first qualifying deal should arrive on Ezra's Telegram with Approve/Deny.
 10. END-TO-END TEST: have Ezra tap Approve on one deal → confirm a lead appears in the
     Command Centre at Pipeline → Live Subs, and the Telegram message edits to "✅ APPROVED".
 11. Record: /srv/sunbiz/ceo-agent/.venv/bin/python /srv/sunbiz/ceo-agent/scripts/state/state_sync.py \
       --note "Breeze UW Entry Sheet + Ezra Telegram approvals LIVE on VPS"

AUTOMATIONS TAB (Command Centre — what CC will see after deploy)
  Automations → Background Workers (status flows from the VPS bridge heartbeat):
    • "Breeze UW Entry Sheet"   (pm2.mca-lead-scrubber)
    • "Ezra Telegram Approvals" (pm2.ezra-telegram-bridge)
  Plus "Breeze UW Entry Sheet" in the Agents & Modules board, and the new "Live Subs"
  stage in the Lead Pipeline (Pipeline → Live Subs).

GUARDRAILS
  - Both workers are single-instance + IS_LINUX-gated — NEVER run on CC's Mac (double-processing).
  - The system reads Drive + scores + queues + (only on Ezra's approval) creates a lead.
    No money movement, no merchant sends from these daemons.
  - Scoring is config-driven: scripts/scrubber/scoring_config.yaml  [uw] section. CC tunes
    thresholds there (edit the YAML, bump `version`) — no code change.
  - NOT YET BUILT: the live funder-research layer (identify each funder → research typical
    terms/length → match to the merchant's stack). Funder A/B tiers are seeded in the config
    and used as a scoring signal; the deep research is a follow-on, NOT required for go-live.

STOP / ROLLBACK (zero data impact — read Drive + queue only)
  pm2 stop mca-lead-scrubber ezra-telegram-bridge && pm2 save        # halt both
  # or set SIFT_PARSER_READY=0 in the agent env file → scrubber discovers but stops scoring/sending

ESCALATE TO CC IF: Drive access FAIL · 0 sheets found (sharing not set) · bot getMe not ok ·
  supabase MISSING · either worker crash-loops (report the pm2 traceback verbatim).
