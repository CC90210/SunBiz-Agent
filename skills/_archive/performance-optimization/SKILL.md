# SKILL: Performance Optimization

> Data-driven campaign optimization for MCA ads — improving CPQL, CTR, and ROAS for SunBiz Funding.

---

## North Star Metric: CPQL (Cost Per Qualified Lead)

CPL alone is misleading for MCA. A $30 lead that doesn't qualify is worthless. A $60 lead that funds is gold. Always optimize for CPQL.

**Targets:**
| Metric | Target | Red Flag |
|--------|--------|----------|
| CPQL | <$100 | >$150 |
| CPL | <$50 | >$80 |
| CTR | >1.5% | <0.8% |
| CPC | <$8 | >$15 |
| JotForm CVR | >15% | <8% |
| Lead-to-Qualify Rate | >30% | <15% |
| Frequency (Meta) | <5 | >5 (creative fatigue) |

---

## Optimization Decision Tree

```
CPQL too high?
├─ CPL is fine but qualify rate low → Lead quality problem → Tighten self-qualification in ad copy
├─ CPL is high → Cost problem → See CPL tree below
└─ Both high → Fundamental targeting/messaging mismatch → Revisit strategy

CPL too high?
├─ CTR low (<1%) → Creative/copy not resonating → Test new ads, refresh creative
├─ CTR good but JotForm CVR low → JotForm friction → Check form length, mobile UX
├─ CPC too high → Competition/targeting → Broaden targeting, test new placements
└─ All metrics okay but CPL high → Conversion tracking issue → Verify pixel/CAPI

CTR too low?
├─ Impressions high, clicks low → Ad not relevant → Test different hooks/angles
├─ Impressions low → Budget/bid too low OR targeting too narrow
└─ Some ads good, some bad → Pause losers, scale winners

No impressions?
├─ Campaign active? → Check status
├─ Budget set? → Verify budget
├─ Ad rejected? → Check compliance (CREDIT category, MCA language)
├─ Targeting too narrow? → Broaden (but stay CREDIT-compliant)
└─ Bid competitive? → Increase bid or switch to automated

Frequency >5?
├─ Creative fatigue → Refresh creatives (2-3 week cycle)
├─ Audience too small → Broaden geographic or interest targeting
└─ Budget too high for audience → Reduce or expand reach
```

---

## Optimization Playbooks

### Playbook 1: Creative Optimization
**When:** CTR < 1.5% or declining, or frequency > 5
**Actions:**
1. Generate 3 new creative concepts (different angles, not just color variants)
2. Test across formats: static image, carousel, video (<30 sec)
3. Ensure 10-15 conceptually distinct assets per campaign (Andromeda optimization)
4. A/B test: before/after vs. roadmap vs. payment table vs. testimonial
5. After 50+ conversions per variant, pick winner by CPQL
6. Pause losers, create new challengers
7. UGC-style video often outperforms polished content (4x higher CTR)

### Playbook 2: Lead Quality Optimization
**When:** CPL is good but CPQL is high (low qualify rate)
**Actions:**
1. Review lead score distribution — if >30% COLD leads, targeting is off
2. Strengthen self-qualification in ad copy ("$25K+/month revenue," "2+ positions")
3. Use "Higher Intent" form type on Meta (adds review step)
4. Add pre-qualifying question to JotForm (monthly revenue range)
5. Test consolidation angle vs. growth capital — compare qualify rates
6. Review which creatives produce highest-quality leads (not just most leads)

### Playbook 3: Budget Optimization
**When:** Some campaigns much better than others
**Actions:**
1. Rank all campaigns by CPQL (lowest = best)
2. Shift 20% of budget from worst to best performer
3. If campaign is spending full budget at good CPQL → increase budget 20%
4. Consolidation angle should get 70% of spend
5. Ensure each ad set gets 50+ conversions/week for algorithm optimization
6. Review weekly, adjust bi-weekly

### Playbook 4: Funnel Optimization
**When:** Clicks are good but JotForm submissions are low
**Actions:**
1. Check JotForm mobile experience (most traffic is mobile)
2. Verify JotForm loads quickly (<3 seconds)
3. Review form length — keep to 5-7 fields max
4. Ensure CTA matches ad promise (consistency reduces drop-off)
5. Check UTM tracking is working
6. Test Meta Instant Forms vs. JotForm (compare CPL and qualify rate)

### Playbook 5: Speed-to-Lead Optimization
**When:** Leads are coming in but not converting to funded deals
**Actions:**
1. Measure time from JotForm submission to first call
2. Target: <5 minutes for HOT (70+ score), <1 hour for WARM (50-69)
3. Set up instant SMS auto-response (within 60 seconds)
4. Implement n8n workflow: JotForm → auto-SMS + CRM + team notification
5. Track speed-to-contact by lead tier and measure impact on conversion

---

## Optimization Cadence
| Timeframe | Actions |
|-----------|---------|
| Daily | Check spend pacing, flag rejected ads, verify JotForm submissions flowing |
| 2x/week | Review CTR, CPC, frequency trends |
| Weekly | Full performance review, CPQL analysis by angle and creative |
| Bi-weekly | Creative refresh, budget reallocation, lead quality review |
| Monthly | Strategy review, audience refresh, competitive intelligence check |

## Red Flags (Immediate Action Required)
| Signal | Action |
|--------|--------|
| Ad rejected | Fix MCA compliance issue (likely "loan" language), resubmit |
| CPQL > 2x target ($200+) | Pause campaign, investigate lead quality |
| CTR < 0.5% | Creative is failing, replace immediately with new concept |
| Budget exhausted by 10 AM | Pacing issue, spread budget or increase daily cap |
| Zero JotForm submissions after $100 spend | Check JotForm link, UTM tracking, form functionality |
| Frequency > 5 | Creative fatigue, refresh all assets in that ad set |
| Qualify rate < 15% | Ad copy attracting wrong audience, tighten self-qualification |
| >30% COLD leads | Targeting too broad, add self-qualification signals to copy |
