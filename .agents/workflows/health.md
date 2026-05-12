---
description: Full system diagnostic — API connectivity, token validity, campaign health, compliance, and infrastructure checks.
---

// turbo-all

# /health — Sun Biz Agent System Health Diagnostic

## When to Use
Use `/health` at session start, when something seems off, or for routine checks.

## Steps

1. **API Connectivity** — Test Google Ads (list campaigns) + Meta Ads (read account).

2. **Token Validity** — Google OAuth2 refresh token valid? Meta access token valid/expiry? Developer token active?

3. **MCP Servers** — All 6+ servers responding? (Google Ads, Meta Ads, Playwright, Context7, Memory, Sequential Thinking)

4. **Campaign Health:**
   - Any rejected ads? → Surface reason + fix
   - Stuck in Learning >7 days? → Check conversions
   - $0 spend today? → Investigate delivery
   - CPL >2x target? → Flag for optimization
   - CTR <0.5%? → Flag for creative refresh

5. **Compliance** — All Meta lending ads have CREDIT category? No restricted targeting? Disclosures present?

6. **Infrastructure** — `.env.agents` complete? Python packages installed? Wrapper scripts present? Git clean?

7. **Report:**
   ```
   === Sun Biz Agent Health Report ===
   APIs:        [OK/FAIL] Google | [OK/FAIL] Meta
   Tokens:      [OK/WARN] Valid
   MCP:         X/6 operational
   Campaigns:   X active | X paused | X issues
   Compliance:  [OK/WARN]
   Infrastructure: [OK/FAIL]
   Issues: [count + details]
   ```

## Example Usage
**User:** `/health`
**Agent:** Full health report with any issues highlighted and fix recommendations.
