# SKILL: Campaign Creation

> End-to-end MCA campaign setup flow — from strategy to launch for SunBiz Funding.

---

## The 8-Step Campaign Creation Process

### Step 1: Define Objective & Angle
- **Objective:** Almost always **Lead Generation** for MCA
  - Google: `LEAD_GENERATION` or `MAXIMIZE_CONVERSIONS`
  - Meta: `OUTCOME_LEADS`
- **Angle:** Consolidation (primary, 70% of spend) or Growth Capital (secondary, 30%)
- **Target CPQL:** <$100

### Step 2: Set Budget
- Recommended minimum: $30-50/day per platform for MCA
- Start conservative, scale winners based on CPQL (not just CPL)
- Budget split: Consolidation 70% / Growth Capital 30%
- Meta's algorithm needs 50+ conversions/week per ad set to optimize

### Step 3: Define Audience (CREDIT Category Compliant)
- **Google:** MCA keywords + national targeting + in-market audiences
- **Meta:** National targeting + business owner interests (NO age/gender/zip)
- Use ad copy for self-qualification: "If your business does $15K+/month..."
- Create 2-3 audience segments for testing
- Custom conversions with "Other" event to avoid algorithmic bias

### Step 4: Create Ad Copy
- Follow content-creator agent MCA language rules
- NEVER use "loan," "lender," "lending," "borrower," "interest rate"
- 3-5 headline variants for A/B testing
- 2-3 primary text variants
- Front-load message in first 125 characters (before "See More")
- Clear CTA: "See If You Qualify" / "Get Your Consolidation Plan" / "Check Your Options"
- Include MCA disclaimers

### Step 5: Prepare Creative Assets
- **Minimum:** 10-15 conceptually distinct creatives (Andromeda optimization)
- Formats: Static images (1080x1080, 1200x628), Video (<30 sec), Carousel
- Creative concepts: before/after, roadmap, payment table, testimonial, educational
- Visual style: Navy blue (#001F54) primary, orange (#FF6B35) CTAs, green (#28A745) for savings
- NO cheesy stock photos — clean, analytical, financial advisor aesthetic

### Step 6: Build Campaign Structure
- **Google:** Campaign → Ad Group → Keywords + RSA
- **Meta:** Campaign → Ad Set → Ad + Creative
- Create in PAUSED state first
- Meta: `special_ad_categories: ['CREDIT']` — MANDATORY

### Step 7: Review & Compliance Check
- [ ] `special_ad_categories: ['CREDIT']` set on all campaigns?
- [ ] No prohibited targeting (age, gender, zip, lookalike)?
- [ ] No "loan," "lender," "lending," "borrower" in any copy?
- [ ] No guaranteed approval language?
- [ ] MCA disclaimers present? ("Merchant Cash Advance products are not loans.")
- [ ] TCPA consent language on all lead forms?
- [ ] All CTAs link to JotForm?
- [ ] UTM parameters configured? (`utm_source=meta&utm_medium=paid&utm_campaign=[name]`)
- [ ] Campaign structure matches strategy?

### Step 8: Launch
- Get user approval
- Set status to ACTIVE
- Monitor first 24-48 hours closely (spend pacing, ad approvals)
- Verify JotForm submissions are flowing
- Speed-to-lead: ensure call team is ready (call within 5-15 minutes)
- Log to CAMPAIGN_TRACKER.md

---

## Quick Launch Template (MCA Consolidation)

```
Campaign Name: SunBiz - Consolidation - [Date]
Platform: Meta Ads
Objective: OUTCOME_LEADS
Special Ad Category: CREDIT
Budget: $50/day
Duration: Ongoing (optimize weekly)
Target CPQL: <$100
Angle: Consolidation
Audience: National US, broad (CREDIT restrictions)
Ad Copy: "Overleveraged? We build a multi-phase path to financial health."
Creative: Before/after consolidation (4 positions → 1), navy blue, orange CTA
CTA: "See If You Qualify" → JotForm [URL]
UTM: ?utm_source=meta&utm_medium=paid&utm_campaign=sunbiz_consolidation_q1
Disclaimers: "Merchant Cash Advance products are not loans. Subject to underwriting approval."
Compliance: CREDIT category, no restricted targeting, MCA language verified
```

## Quick Launch Template (Growth Capital)

```
Campaign Name: SunBiz - Growth Capital - [Date]
Platform: Meta Ads
Objective: OUTCOME_LEADS
Special Ad Category: CREDIT
Budget: $25/day
Duration: Ongoing (optimize weekly)
Target CPQL: <$80
Angle: Growth Capital
Audience: National US, broad (CREDIT restrictions)
Ad Copy: "Smart capital for growing businesses. Funded in 24-48 hours."
Creative: Clean white/gray design, professional business imagery, green accents
CTA: "See If You Qualify" → JotForm [URL]
UTM: ?utm_source=meta&utm_medium=paid&utm_campaign=sunbiz_growth_q1
Disclaimers: "Merchant Cash Advance products are not loans. Subject to underwriting approval."
Compliance: CREDIT category, no restricted targeting, MCA language verified
```
