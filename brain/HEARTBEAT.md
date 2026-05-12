# HEARTBEAT - Health Check Procedures

> Run on `/health`, `python scripts/doctor.py`, or session start.

---

## Health Check Sequence

### 1. Repo surface
```
[ ] .env.agents.template exists?
[ ] scripts/setup.py exists?
[ ] scripts/doctor.py exists?
[ ] scripts/api_server.py exists?
[ ] Email templates + dashboard contract files present?
```

### 2. Core runtime dependencies
```
[ ] python-dotenv installed?
[ ] requests installed?
[ ] jinja2 installed?
[ ] twilio installed?
[ ] fastapi + uvicorn installed?
```

### 3. Production credentials
```
[ ] SUNBIZ_TWILIO_* configured?
[ ] GMAIL_ADDRESS + GMAIL_APP_PASSWORD configured?
[ ] JOTFORM_API_KEY + JOTFORM_FORM_ID configured?
[ ] SUNBIZ_AGENT_HMAC_SECRET configured?
```

### 4. Live probes (`--deep`)
```
[ ] Gmail SMTP login succeeds?
[ ] JotForm form metadata fetch succeeds?
[ ] sms_engine.py reports twilio configured + SDK installed?
```

### 5. Optional sub-capabilities
```
[ ] Google Ads credentials present?
[ ] Meta Ads credentials present?
[ ] Gemini image-generation key present?
[ ] Phase 2 SMS failover keys present?
```

---

## Health Report Format

```
=== Sun Biz Agent Doctor ===
Verdict: HEALTHY | DEGRADED | UNHEALTHY

Required:
- repo surface
- env file
- sms env
- gmail env
- jotform env
- api security env

Optional:
- lead-gen keys
- phase-2 failover keys
```
