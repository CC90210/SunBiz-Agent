# SKILL: A/B Testing

> Systematic split testing for ads, audiences, and landing pages.

---

## A/B Testing Framework

### What to Test (Priority Order)
1. **Ad Creative** (images/videos) — Biggest impact on CTR
2. **Ad Copy** (headlines, descriptions) — Second biggest impact
3. **Audiences** (targeting segments) — Impacts CPL significantly
4. **Bidding Strategies** — Impacts CPC and delivery
5. **Placements** (feed vs. stories vs. search) — Impacts reach and cost
6. **Landing Pages** — Impacts conversion rate

### Test Design Rules
1. **Test ONE variable at a time** — If testing headlines, keep everything else identical
2. **Equal budget split** — Each variant gets same budget
3. **Minimum sample size** — 500+ impressions per variant before declaring winner
4. **Minimum duration** — Run for at least 7 days (captures day-of-week effects)
5. **Statistical significance** — Need 95% confidence before declaring winner

### Google Ads A/B Testing
- Create multiple ads within same ad group (Google auto-rotates)
- Use "Ad Rotation: Do not optimize" setting for true A/B
- After test period, let Google optimize to winner or manually pause loser
- For campaign-level tests: create duplicate campaigns with one change

### Meta Ads A/B Testing
- Use native A/B Test feature (campaign-level)
- Or create multiple ad sets with different variables
- Meta's built-in split test ensures no audience overlap
- Variables: Creative, Audience, Placement, Delivery Optimization

## Test Template
```
Test Name: [descriptive name]
Variable: [what's being tested]
Hypothesis: [what we expect and why]
Variant A: [control — current/original]
Variant B: [challenger — the change]
Success Metric: [CTR / CPL / CVR]
Budget: $X per variant per day
Duration: 7-14 days
Minimum Sample: 500 impressions per variant
Start Date: YYYY-MM-DD
End Date: YYYY-MM-DD

RESULTS (fill after test)
Variant A: [metric] = X.XX%
Variant B: [metric] = X.XX%
Winner: [A/B]
Confidence: XX%
Action: [implement winner / run follow-up test]
```

## Common A/B Tests for Lending
1. **Headline:** "Apply for a Loan" vs. "Check Your Rate" vs. "Get Funded Fast"
2. **CTA:** "Apply Now" vs. "Get a Quote" vs. "Learn More"
3. **Image:** Person smiling vs. abstract financial graphic vs. lifestyle image
4. **Copy approach:** Benefits-focused vs. trust-focused vs. urgency-focused
5. **Audience:** Broad vs. interest-based vs. lookalike
