# CAPABILITIES — Complete Tool Inventory

> All tools available to Sun Biz Agent across all interfaces.
> *Repositioned 2026-05-11: scope expanded from "AdVantage — Marketing Director (Meta + Google Ads only)" to "Sun Biz Agent — Full Backend Operations Agent". The 8 MCP servers + Python SDKs below remain — they now cover the lead-gen sub-capability while new CLI scripts (sms_engine, funding_intel, deal_tracker, renewal_scanner, state_bridge) drive ops.*

---

## MCP Servers (8 Total)

### 1. Google Ads MCP
- **Status:** PENDING SETUP
- **Server:** `google-ads-mcp` (community: grantweston/google-ads-mcp-complete or custom)
- **Capabilities:** Campaign CRUD, Ad Group CRUD, Ad CRUD, Keyword management, GAQL reporting, Budget management, Asset upload
- **Auth:** Developer token + OAuth2 (client_id, client_secret, refresh_token) + customer_id
- **Fallback:** Direct `google-ads` Python SDK (v29.2.0)

### 2. Meta Ads MCP
- **Status:** PENDING SETUP
- **Server:** `meta-ads-mcp` (pipeboard-co/meta-ads-mcp or custom)
- **Capabilities:** Campaign CRUD, Ad Set CRUD, Ad CRUD, Creative management, Audience management, Insights/reporting, Media upload
- **Auth:** System user access token + app_id + app_secret + ad_account_id
- **Fallback:** Direct `facebook-business` Python SDK (v22.0)

### 3. Playwright MCP
- **Status:** AVAILABLE
- **Server:** `@playwright/mcp@latest`
- **Capabilities:** Browser navigation, screenshots, form filling, clicking, JavaScript evaluation
- **Use:** Fallback for operations not supported by APIs, visual verification of ads

### 4. Context7 MCP
- **Status:** AVAILABLE
- **Server:** `@upstash/context7-mcp@latest`
- **Capabilities:** Library documentation lookup, code examples
- **Use:** Look up Google Ads API or Meta API documentation on demand

### 5. Memory MCP
- **Status:** AVAILABLE
- **Server:** `@modelcontextprotocol/server-memory`
- **Capabilities:** Knowledge graph CRUD (entities, relations, observations)
- **Use:** Persistent campaign knowledge, audience insights, optimization learnings

### 6. Sequential Thinking MCP
- **Status:** AVAILABLE
- **Server:** `@modelcontextprotocol/server-sequential-thinking`
- **Capabilities:** Structured multi-step reasoning
- **Use:** Complex campaign strategy, budget allocation, optimization decisions

### 7. n8n MCP
- **Status:** AVAILABLE (if n8n instance running)
- **Server:** `n8n-mcp` (via wrapper script)
- **Capabilities:** Workflow search, execution, details
- **Use:** Automated reporting, scheduled campaign checks, alert workflows

### 8. Late MCP
- **Status:** AVAILABLE (if configured)
- **Server:** `late-sdk[mcp]` (via wrapper script)
- **Capabilities:** Social media posting, account management, cross-posting
- **Use:** Organic social media content alongside paid ads

---

## Python SDK Tools (Fallback Layer)

### Google Ads Python SDK
- **Package:** `google-ads` (v29.2.0)
- **API Version:** v23.1 (latest)
- **Key Services:**
  - `CampaignService` — Campaign CRUD
  - `AdGroupService` — Ad Group CRUD
  - `AdGroupAdService` — Ad CRUD
  - `AdGroupCriterionService` — Keyword/targeting CRUD
  - `CampaignBudgetService` — Budget management
  - `GoogleAdsService.SearchStream` — GAQL reporting
  - `AssetService` — Media asset management
  - `BatchJobService` — Bulk operations
  - `BiddingStrategyService` — Bid strategy management

### Meta Marketing Python SDK
- **Package:** `facebook-business` (v22.0)
- **API Version:** Graph API v22.0
- **Key Classes:**
  - `AdAccount` — Account-level operations
  - `Campaign` — Campaign CRUD
  - `AdSet` — Ad Set CRUD
  - `Ad` — Ad CRUD
  - `AdCreative` — Creative management
  - `AdImage` — Image upload/management
  - `AdVideo` — Video upload/management
  - `CustomAudience` — Audience management
  - `AdsInsights` — Performance reporting

---

## Native IDE/CLI Tools

### Claude Code (Opus 4.6)
- Read, Write, Edit, Glob, Grep, Bash
- Agent (sub-agent orchestration)
- TodoWrite (task tracking)
- WebSearch, WebFetch

### Antigravity IDE
- All Claude Code tools + IDE-specific features
- Workflow commands (`.agents/workflows/`)
- Rules and customization

### Gemini CLI
- File operations, web search
- Speed-optimized for quick tasks

---

## AI Image Generation Tools

### Gemini Imagen (Nano Banana)
- **Status:** Requires API key
- **Package:** `google-genai`
- **Models:** `gemini-2.0-flash-exp` (native image gen), `imagen-3.0-generate-002` (dedicated)
- **Use:** Generate professional ad creative images from text prompts — business lending ads, A/B test variants, all platform sizes
- **Script:** `scripts/imagen_generate.py`
- **Install:** `pip install google-genai Pillow`
- **API Key:** Get from https://aistudio.google.com/apikey → set `GEMINI_API_KEY` in `.env.agents`

---

## Video Production Tools

### FFmpeg
- **Status:** Requires installation
- **Use:** Video trimming, resizing, compression, caption burning, thumbnail extraction
- **Install:** `winget install ffmpeg` or download from ffmpeg.org

### Whisper (OpenAI)
- **Status:** Requires installation
- **Package:** `openai-whisper`
- **Use:** Auto-captioning / speech-to-text for video ads
- **Install:** `pip install openai-whisper`

---

## Billing & Payment (Ad Spend)

### Google Ads Billing
- **How it works:** Google bills the linked payment method (credit card, bank account) in the Google Ads account
- **API access:** `BillingSetupService` for viewing billing info, `InvoiceService` for invoice data
- **Budget control:** Set daily budgets via `CampaignBudgetService` — Google charges the payment method on file
- **Reporting:** `metrics.cost_micros` in GAQL gives exact spend data
- **Note:** The API does NOT process payments directly — it controls budgets, Google handles billing

### Meta Ads Billing
- **How it works:** Meta bills the payment method linked in Business Manager (credit card, PayPal, bank)
- **API access:** Read billing info via `/act_{id}/billing_events`, payment methods via `/act_{id}/payment_methods`
- **Budget control:** Set daily/lifetime budgets on campaigns and ad sets — Meta charges the payment method
- **Reporting:** `spend` field in Insights API gives exact spend data
- **Note:** The API does NOT process payments directly — it controls budgets, Meta handles billing

### Budget Management via API
Both platforms work the same way:
1. **Set budget** via API → Platform delivers ads up to that budget
2. **Platform bills** the payment method on file in the ad account
3. **We monitor** spend via reporting APIs (GAQL / Insights)
4. **We control** by adjusting budgets, pausing campaigns, or setting rules

---

## Tool Counts
- **MCP Servers:** 8 (2 pending setup, 6 available)
- **Python SDK Services:** 19 (Google: 9, Meta: 10)
- **AI Image Generation:** 1 (Gemini Imagen)
- **Video Tools:** 2 (FFmpeg, Whisper)
- **Native Tools:** 12+
- **Agents:** 15
- **Skills:** 18
- **Workflows:** 11
