# MAXIMIZATION GUIDE — Sun Biz Funding × Sun Biz Agent
*(Repositioned 2026-05-11 from "SunBiz Funding × AdVantage" — see `brain/CHANGELOG.md`. Scope expanded from "AI marketing system" to full backend operations agent: SMS, email, deal lifecycle, funding intelligence, commissions.)*

> Your playbook for using the Sun Biz Agent system. Copy-paste these prompts.

---

## Phase 1: Setup (Do This First)

### 1.1 Get Your Credentials
| Platform | What You Need | Where to Get It |
|----------|--------------|-----------------|
| Gemini Imagen | API Key | [Google AI Studio](https://aistudio.google.com/apikey) |
| Meta Ads | Access Token, App ID, App Secret, Ad Account ID, Page ID | [Meta Business Suite](https://business.facebook.com) |
| Google Ads | Developer Token, Client ID/Secret, Refresh Token | [Google Ads API Center](https://ads.google.com) |

### 1.2 Provide JotForm Link
> "Here's our JotForm link: [URL]. Update all systems to use this as the CTA destination for every ad."

### 1.3 First Health Check
> "/prime"

---

## Phase 2: Test Ad Creative Generation (START HERE)

### 2.1 Consolidation Ads (Primary Angle)
> "Generate 3 consolidation ad variants. Before/after style — show going from 4 MCA positions at $2,100/day to 1 position at $850/day. Navy blue background, orange CTA 'See If You Qualify'. 1080x1080 for Meta feed."

> "Generate a multi-phase roadmap ad showing the 4 phases: Consolidate → Buy Out → One Funder → Line of Credit. Navy blue background."

> "Generate a payment comparison table ad — show current vs. after SunBiz consolidation with monthly savings highlighted."

### 2.2 Growth Capital Ads (Secondary Angle)
> "Generate a growth capital ad for clean merchants. White/gray background, 'Smart Capital for Growing Businesses', targeting $40K+ monthly revenue businesses."

### 2.3 Stories/Vertical Format
> "Generate a vertical 1080x1920 stories ad. Dark navy, 'DROWNING IN MCA PAYMENTS?' with before/after comparison."

### 2.4 A/B Test All Variants
> "Generate all platform sizes for the winning consolidation ad: feed square, feed portrait, stories, Google display."

---

## Phase 3: Write Ad Copy

### 3.1 Consolidation Copy
> "Write 5 Meta primary text variants for MCA consolidation. Target: overleveraged merchants with 3+ positions, $25K+ monthly revenue. Use the PAS framework. Keep under 125 characters."

> "Write 5 headline variants for the consolidation angle. Focus on pain relief — daily drain, breathing room, fewer payments."

### 3.2 Growth Capital Copy
> "Write 3 Meta ad copy variants for growth capital. Target: clean merchants, $40K+ revenue, 0-1 positions. Emphasize speed and no equity required."

### 3.3 Educational Content
> "Write a carousel ad script — 4 slides explaining the multi-phase consolidation approach: Phase 1 through Phase 4."

---

## Phase 4: Launch First Campaign

### 4.1 Full Campaign Wizard
> "/campaign-create"

### 4.2 One-Shot Launch
> "Create a Meta lead generation campaign for SunBiz Funding MCA consolidation. Budget: $50/day. Target: business owners (Meta CREDIT category restrictions apply). Use the consolidation before/after ad creative and copy. CTA: 'See If You Qualify' linking to [JotForm URL]."

---

## Phase 5: Daily Operations

### Morning Check
> "/performance"

### Weekly Optimization
> "/optimize"

> "My CPQL is $85 — I need it under $60. Analyze which ad sets are underperforming and suggest changes."

### A/B Testing
> "Set up an A/B test: consolidation angle vs. growth capital angle. Same budget, same audience. Run for 7 days."

### Creative Refresh (Every 2-3 Weeks)
> "Generate a completely new set of consolidation ads — different visual approach. Try a clean data visualization style with charts showing payment reduction."

---

## Power User Prompts

### Quick Wins
| What You Want | Prompt |
|--------------|--------|
| Check ad status | "Are all campaigns active? Any disapprovals?" |
| Quick spend check | "How much have I spent today?" |
| Pause everything | "Pause all active campaigns." |
| Budget change | "Set daily budget to $75 on the consolidation campaign." |

### Strategic
| What You Want | Prompt |
|--------------|--------|
| Full strategy | "I have $2,000/month for Meta ads. Create a complete MCA consolidation campaign strategy." |
| Retargeting | "Set up retargeting for people who clicked but didn't submit the JotForm. Different creative, urgency messaging." |
| Competitor research | "Research what MCA companies are running on Meta right now. Use the Ad Library." |
| Content calendar | "Create a month of educational content about MCA consolidation for organic posting." |

### Troubleshooting
| Problem | Prompt |
|---------|--------|
| Ad rejected | "/debug — My Meta ad was rejected. Error: [paste]. Fix it." |
| High CPQL | "CPQL jumped to $120. Diagnose and fix." |
| No leads | "500 clicks but zero JotForm submissions. What's broken?" |

---

## Ideal Weekly Routine

| Day | Action | Prompt |
|-----|--------|--------|
| **Monday** | Performance check + educational post | "/performance" |
| **Tuesday** | Consolidation ad post | (Autonomous) |
| **Wednesday** | Mid-week optimization | "Any campaigns need attention?" |
| **Thursday** | Case study post | (Autonomous) |
| **Friday** | Weekly report + growth capital post | "/report" |

---

## Pro Tips

1. **Always start with `/prime`** — loads context and catches issues early
2. **Generate 3 variants minimum** — always A/B test creatives
3. **Consolidation angle first** — this is SunBiz's primary differentiator and should be the majority of ad spend
4. **Refresh creatives every 2-3 weeks** — ad fatigue kills performance
5. **Speed-to-lead wins** — when leads come in, call within 15 minutes
6. **End every session with `/sync`** — saves state for next session
7. **Never say "loan"** — the system knows this but always double-check generated content
8. **JotForm is the only CTA destination** — every ad, every platform, every campaign
9. **Use educational content** — "How to calculate your leverage ratio" builds trust before the sell
10. **Track CPQL, not just CPL** — a $30 lead that doesn't qualify is worth less than a $60 lead that funds
