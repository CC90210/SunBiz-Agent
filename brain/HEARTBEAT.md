# HEARTBEAT — Health Check Procedures

> Run on `/health` command or session start.

---

## Health Check Sequence

### 1. API Connectivity
```
[ ] Google Ads API — Can authenticate and list campaigns?
[ ] Meta Marketing API — Can authenticate and list campaigns?
[ ] MCP Servers — All configured servers responding?
```

### 2. Token Validity
```
[ ] Google OAuth2 refresh token — Valid? (refresh tokens don't expire unless revoked)
[ ] Meta access token — Valid? (system user tokens don't expire; user tokens expire in 60 days)
[ ] Developer token — Active? (check access level: Test/Basic/Standard)
```

### 3. Campaign Health
```
[ ] Any rejected ads? → Surface rejection reason + fix
[ ] Any campaigns stuck in "Learning"? → Check if sufficient conversions
[ ] Any campaigns with $0 spend today? → Investigate delivery
[ ] Any campaigns over budget? → Check pacing
[ ] Any ads with CTR < 0.5%? → Flag for creative refresh
[ ] Any campaigns with CPL > 2x target? → Flag for optimization
```

### 4. Budget Health
```
[ ] Total daily spend across platforms = $X
[ ] Remaining monthly budget = $X
[ ] Pacing: On track / Underspending / Overspending
```

### 5. Infrastructure Health
```
[ ] .env.agents file exists and has required keys?
[ ] MCP wrapper scripts exist and are executable?
[ ] Python virtual environment active with required packages?
[ ] Git repo clean? Any uncommitted changes?
[ ] Memory files consistent? No contradictions?
```

### 6. Compliance Check
```
[ ] All Meta lending ads using special_ad_categories: ['CREDIT']?
[ ] All Google lending ads have required disclosures?
[ ] No restricted targeting on credit ads?
[ ] Landing pages have required lending disclosures?
```

---

## Health Report Format

```
=== Sun Biz Agent Health Report ===
Date: YYYY-MM-DD HH:MM

APIs:        [OK/WARN/FAIL] Google Ads | [OK/WARN/FAIL] Meta Ads
Tokens:      [OK/WARN/FAIL] Valid for X more days
Campaigns:   X active | X paused | X rejected
Budget:      $X/day spent | $X/month remaining
Performance: Avg CPL $X.XX | Avg CTR X.X%
Compliance:  [OK/WARN] All ads compliant
Infrastructure: [OK/WARN/FAIL] All systems operational

Issues Found: X
[list any issues with severity and recommended action]
```
