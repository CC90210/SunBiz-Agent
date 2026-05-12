# AGENTS — Sub-Agent Registry & Orchestration Matrix

> 15 specialized agents. Route tasks by type and complexity.

---

## Top-Level Operator Pair

Before routing into the 15 internal sub-agents, treat the Sun Biz deployment itself as a two-operator system:

| Layer | Agent Key | Purpose |
|---|---|---|
| Backend ops | `sunbiz` | **Solara / Solar** owns admin operations: lead review, lender routing, applications, funded deals, renewals, commissions, and compliance rails. |
| Outreach ops | `suga_sean` | **Suga Sean** owns text blasts, email outreach, reply triage, and meeting-setting. |

Rule of thumb:

- If the task touches the source of truth, deal state, lender ops, or compliance, Solara leads.
- If the task touches outbound motion, follow-up cadence, or booking meetings, Suga Sean leads.
- If both are involved, Solara protects the ledger and Suga Sean drives the next touch.

---

## Agent Registry

| # | Agent | File | Role | Model | Trigger |
|---|-------|------|------|-------|---------|
| 1 | architect | `agents/architect.md` | System design, infrastructure | Opus | "design", "architecture", "infrastructure" |
| 2 | ad-strategist | `agents/ad-strategist.md` | Campaign strategy, A/B testing, optimization | Opus | "strategy", "optimize", "A/B test", "campaign plan" |
| 3 | content-creator | `agents/content-creator.md` | Ad copy, headlines, descriptions, CTAs | Sonnet | "write ad", "headline", "copy", "CTA" |
| 4 | media-manager | `agents/media-manager.md` | Image/video upload, creative management | Sonnet | "upload", "image", "creative" |
| 5 | google-ads-specialist | `agents/google-ads-specialist.md` | Google Ads API CRUD operations | Opus | "google", "search ads", "display ads", "GAQL" |
| 6 | meta-ads-specialist | `agents/meta-ads-specialist.md` | Meta Marketing API CRUD operations | Opus | "facebook", "instagram", "meta", "ad set" |
| 7 | analytics-analyst | `agents/analytics-analyst.md` | Performance reporting, ROAS analysis | Opus | "performance", "metrics", "report", "ROAS", "CTR" |
| 8 | audience-builder | `agents/audience-builder.md` | Custom audiences, lookalikes, targeting | Sonnet | "audience", "targeting", "lookalike", "demographic" |
| 9 | seo-specialist | `agents/seo-specialist.md` | SEO, AEO, keyword research, Quality Score | Opus | "SEO", "keywords", "quality score", "AEO", "ranking" |
| 10 | video-editor | `agents/video-editor.md` | Video production, captioning, formatting | Sonnet | "video edit", "trim", "caption", "thumbnail", "reels" |
| 11 | debugger | `agents/debugger.md` | Root cause analysis, API error resolution | Opus | "error", "bug", "fix", "broken", "failed" |
| 12 | explorer | `agents/explorer.md` | Codebase navigation, research | Sonnet | "find", "search", "where is", "show me" |
| 13 | documenter | `agents/documenter.md` | Documentation, SOPs, memory management | Sonnet | "document", "SOP", "update docs" |
| 14 | workflow-builder | `agents/workflow-builder.md` | n8n automation, scheduled tasks | Sonnet | "automate", "workflow", "schedule", "n8n" |
| 15 | image-generator | `agents/image-generator.md` | AI ad creative generation (Gemini Imagen) | Opus | "generate ad", "create image", "ad creative", "imagen" |

---

## Orchestration Matrix

### Single-Agent Tasks (Simple)
| Task | Agent |
|------|-------|
| Check campaign status | google-ads-specialist OR meta-ads-specialist |
| Write ad headline | content-creator |
| Upload image | media-manager |
| Generate ad creative image | image-generator |
| Pull performance report | analytics-analyst |
| Debug API error | debugger |

### Multi-Agent Tasks (Moderate)
| Task | Primary | Support |
|------|---------|---------|
| Create new campaign | ad-strategist | seo-specialist, content-creator, audience-builder |
| Launch ads with creative | media-manager | image-generator, video-editor, content-creator, google-ads-specialist |
| Optimize underperforming campaign | analytics-analyst | ad-strategist, seo-specialist, audience-builder |
| Cross-platform campaign | ad-strategist | google-ads-specialist, meta-ads-specialist |
| SEO + ad copy optimization | seo-specialist | content-creator, google-ads-specialist |
| Video ad production | video-editor | media-manager, content-creator |

### Full Orchestration Tasks (Complex)
| Task | Agents Involved |
|------|----------------|
| Full campaign strategy + launch | ad-strategist → seo-specialist → content-creator → image-generator → video-editor → media-manager → audience-builder → google-ads-specialist + meta-ads-specialist → analytics-analyst |
| Performance review + optimization | analytics-analyst → ad-strategist → seo-specialist → content-creator (new copy) → audience-builder (refined targeting) |
| Video ad campaign | ad-strategist → content-creator (script) → video-editor (production) → media-manager (upload) → platform specialists (launch) |
| System health + recovery | debugger → architect → workflow-builder |

---

## Dispatch Rules

1. **Always route to the most specific agent** — Don't use architect for ad copy
2. **Chain agents for multi-step tasks** — Output of one feeds input of next
3. **Parallel execution when independent** — Google and Meta operations can run simultaneously
4. **Escalate to Opus for ambiguity** — When task is unclear, use ad-strategist (Opus) to interpret
5. **Log all agent dispatches** — Track which agents handled which tasks for pattern learning
