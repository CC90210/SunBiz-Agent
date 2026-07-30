# Dolphin CRM visibility repair — VPS system message

Use this message on `srv1723601` after the OASIS dashboard production deployment
contains dashboard commits `b96caa0` and `096ba7c`.

```text
Deploy and verify the Dolphin CRM visibility repair.

Scope:
- SunBiz-Agent commit with the repair runner: 731a2e9
- Dashboard production must already contain commits b96caa0 and 096ba7c.
- Do not modify eligibility/underwriting rules.
- Do not create a sample deal or send a Telegram test.
- Do not touch unrelated PM2 workers.

Procedure:
1. In the SunBiz-Agent checkout, prove the worktree is clean and fetch origin.
2. Fast-forward only to origin/main and confirm commit 731a2e9 is present.
3. Run:
   python -m pytest tests/test_live_sub_backfill.py tests/test_dolphin_eligibility.py tests/test_uw_enrichment_mapping.py -q
   python -m py_compile scripts/scrubber/telegram_bridge.py scripts/scrubber/backfill_live_sub_applications.py
4. Confirm the dashboard internal live-subs endpoint is reachable and running the
   deployed version before making any repair writes.
5. Preview only:
   python scripts/scrubber/backfill_live_sub_applications.py --repair-hidden --dry-run
   Report the exact candidate IDs/count. The selector must include only
   breeze_uw_sheet + live_sub_auto records whose transferred_at was written
   within 10 seconds of lead creation.
6. Run the one-time repair:
   python scripts/scrubber/backfill_live_sub_applications.py --repair-hidden
7. Run the same dry-run again. It must report zero remaining repair candidates.
8. Restart only ezra-telegram-bridge, save PM2 state, and observe one full polling
   interval. Confirm the process stays online with no new traceback.
9. Read-only verify repaired records:
   - lead has application_id
   - lead stage is uw_sheet
   - lead transferred_at is null
   - linked application promoted_at is null
   - full lead/application payload remains present
   Do not expose merchant PII in the report.

Stop and report instead of mutating if the dashboard version is not live, the
worktree is dirty, tests fail, or the dry-run selects any row outside the exact
incident fingerprint.
```
