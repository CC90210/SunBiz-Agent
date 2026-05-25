---
tags: [agents, registry]
---

# AGENTS — Sub-Agent Registry (SunBiz V6.x)

> SunBiz is a focused product, not an empire. Keep this registry tight.
> Primary agents: Solara (backend ops) + Helios (sales-facing).
> Specialized sub-agents are lightweight — spawn only when the task warrants it.

---

## Primary Agent Pair

| Agent | Key | Lane | Scope |
|-------|-----|------|-------|
| **Solara** | `sunbiz` | Backend operations | Deal ledger, shop-out logic, lender relationships, renewal pipeline, compliance rails, reporting |
| **Helios** | `helios` | Sales-facing outreach | Merchant outbound (calls, SMS, email), sequence execution, appointment setting, offer presentation delivery |

**Routing rule:**
- If the task touches deal state, lender ops, application data, or compliance → Solara.
- If the task touches merchant outbound, follow-up cadence, or booking meetings → Helios.
- If both are involved: Solara protects the ledger; Helios drives the merchant touch.
- Escalation path: Solara → Ezra (never Helios → Solara directly for deal decisions).

---

## Cross-Agent Posture

| Agent | Relationship | Solara's Posture |
|-------|-------------|-----------------|
| **Bravo** (CEO-Agent) | Parent substrate | Reads V6 substrate from Business-Empire-Agent. Writes only through sanctioned helpers (state_bridge, send_gateway, agent_inbox). Does NOT edit Bravo's files. |
| **Atlas** (CFO-Agent) | Budget authority | Surfaces spend decisions above threshold; Atlas approves. Does not interact directly in day-to-day. |
| **Maven** (CMO-Agent) | CC's content domain | No overlap. SunBiz brand voice is Ezra's domain, not Maven's. |
| **Helios** | Sibling | Solara stages deals and drafts merchant touches; Helios executes them. Handoffs via `agent_inbox.py post --to helios`. |

---

## Specialized Sub-Agents (Spawn On Demand)

These are lighter-weight agents invoked for specific tasks. They are not always running.

| Agent | Purpose | Trigger | Model |
|-------|---------|---------|-------|
| **underwriting-checker** | Deep pre-screen of an application before shop-out — checks against all known lender appetite profiles, flags specific risks | "Pre-screen this application" / "Is this fundable?" | Sonnet |
| **offer-formatter** | Takes raw lender offer terms and formats a clean merchant-facing offer summary (no jargon, compliant language) | "Format this offer for the merchant" | Sonnet |
| **decline-analyst** | After a full shop-out decline (all lenders pass), investigates root cause and generates a structured Reflexion entry | "Why did all lenders decline?" / shop-out complete with zero approvals | Sonnet |
| **debugger** | Root-cause analysis on script errors, API failures, or daemon issues | "X is broken" / script returns unexpected output | Sonnet |
| **lender-researcher** | Research a new lender's appetite, typical terms, and submission requirements | "Add [Lender] to our book" / "What does [Lender] fund?" | Sonnet |

---

## Orchestration Matrix

### Single-Agent Tasks
| Task | Agent |
|------|-------|
| Check deal status | Solara |
| Update deal stage | Solara |
| Scan renewal window | Solara |
| Pre-screen application | Solara + underwriting-checker |
| Draft merchant email | Helios |
| Send follow-up sequence | Helios |

### Multi-Agent Tasks
| Task | Primary | Support |
|------|---------|---------|
| New application → shop-out | Solara | underwriting-checker, (Ezra confirmation) |
| Offer received → merchant presentation | Solara (format) | Helios (deliver), offer-formatter |
| All-decline analysis | Solara | decline-analyst |
| Renewal outreach | Solara (identify, draft) | Helios (send) |
| New lender onboarding | Solara | lender-researcher |

### Escalation Paths
| Situation | Escalation |
|-----------|-----------|
| Stacking-risk threshold exceeded | Solara → Ezra (same turn, explicit confirmation required) |
| All lenders decline | Solara → decline-analyst → Ezra summary |
| Compliance-sensitive copy | Solara flags → Ezra approves → Helios sends |
| Budget above threshold | Solara → Atlas (CFO-Agent) for modeling → Ezra final call |
| Merchant disputes funded deal | Solara → Ezra direct (not automated) |

---

## Dispatch Rules

1. **Route to the most specific agent.** Don't use Solara for copywriting; don't use Helios for deal ledger updates.
2. **Solara protects the ledger.** Only Solara writes deal state. Helios reads it, never writes it.
3. **Escalate irreversibles to Ezra.** Submission to lender, marking funded, blacklisting a funder: Ezra confirms.
4. **Log all agent handoffs.** Every `agent_inbox.py post` is traced.
5. **Spawn sub-agents only when the task justifies it.** For simple lookups, Solara handles directly.

## Obsidian Links
- [[brain/SOUL]] | [[brain/CAPABILITIES]] | [[brain/AGENT_ROUTER]]
- [[brain/INTENTS]] | [[brain/STATE]]
