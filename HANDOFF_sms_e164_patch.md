# HANDOFF → Bravo: normalize SMS to_phone to E.164 in send_gateway

**Found 2026-06-09 (VPS health audit).** All 400 SunBiz leads store `data.phone`
as a bare 10-digit US number (e.g. `7634218229`); send_gateway's SMS gate
requires E.164 (`+1...`). Result: **every SMS sequence step fails** with
`sms channel requires to_phone (E.164)` / `sms to_phone must be E.164 starting
with '+'`. The 2 stuck `sequence_state` rows (status=failed) are this; it
affects every lead. Email is unaffected.

The VPS operator did NOT commit this (per "Bravo owns code commits"). Please
land it. Data was NOT mutated — fixing at the send boundary covers existing AND
future leads, so no backfill is needed.

## Patch — `ceo-agent/scripts/integrations/send_gateway.py`

`re` is already imported (line 91). The SMS dispatch sends the `to_phone`
variable downstream, so reassigning it here is sufficient. Insert the
normalization between the strip (current line 2424) and the E.164 gate (2425):

```diff
         normalized_phone = to_phone.strip()
+        # Normalize North-American numbers to E.164 so callers that store a
+        # bare 10-digit ("7634218229") or "1XXXXXXXXXX" number don't fail the
+        # gate below. SunBiz leads are stored un-normalized; without this every
+        # SMS sequence step errors "must be E.164". (2026-06-09)
+        if not normalized_phone.startswith("+"):
+            _digits = re.sub(r"\D", "", normalized_phone)
+            if len(_digits) == 10:
+                normalized_phone = "+1" + _digits
+            elif len(_digits) == 11 and _digits.startswith("1"):
+                normalized_phone = "+" + _digits
+        to_phone = normalized_phone  # send the normalized number downstream
         if not normalized_phone.startswith("+") or len(normalized_phone) < 8:
             return {"status": "error",
                     "reason": f"sms to_phone must be E.164 starting with '+', got '{to_phone}'",
                     ...}
```

Conservative: only auto-prefixes unambiguous NANP shapes (10 digits, or 11
starting with 1). Anything else still fails the gate (no silent mis-send to a
malformed number).

## After it lands
1. Retry the 2 stuck sequences for lead `2925b28b-3e66-4711-9844-5523c6936aea`.
2. `scripts/sunbiz_health_check.py` (new, on the VPS — please commit it too)
   will drop from 1 HIGH to 0 HIGH once SMS resolves.

## Also handed off (latent, fix before a 2nd tenant onboards)
F1 `resolve_brand` fails open to oasis (sunbiz_constants.py:55); F2
cold_outreach_runner drains campaigns with no tenant filter (:490-504); F3
lender_response_classifier unscoped (:902-908); F4 sentinel pause fails open on
LLM outage (:287,334); F5 renewal_reminder Telegram empire-chat fallback
(:251); F6 follow_up/daily_plan default to all-tenants when slug unset. Detail
in the operator's audit notes.
