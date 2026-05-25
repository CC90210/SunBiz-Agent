# MAXIMIZATION GUIDE — Sun Biz Funding × Solara + Helios

> Get the most out of your AI digital employees. Written for Ezra. Copy-paste the example phrases — Solara and Helios understand plain English.

---

## Get the most out of Solara

Solara is your backend operator. She knows every deal in your pipeline, every lender you work with, every application that's stalled. She does not guess — she reads your live data and tells you what's actually happening and what to do next.

The most important habit: **talk to Solara every morning before you open your pipeline manually.** She will tell you exactly where to focus. You do not need to dig.

---

## Top 10 things to ask Solara every morning

These are high-leverage, high-frequency prompts. Use them to start your day.

| # | What you want | Example phrasing |
|---|---|---|
| 1 | Today's priority call sheet | "What should I focus on today? Show me in order." |
| 2 | Any lender replies overnight | "Did any lenders reply to the shop-outs? What did they say?" |
| 3 | Applications stuck in the pipeline | "Which applications haven't moved in more than 5 days? What's the diagnosis?" |
| 4 | Deals approaching renewal | "Who is coming up for renewal in the next 30 days?" |
| 5 | Any follow-up tasks due today | "What follow-ups are due today? Who do I need to call?" |
| 6 | New leads from overnight | "Did any new leads come in overnight? Summarize them." |
| 7 | Underwriting queue | "Are there any applications waiting for underwriting? Run them." |
| 8 | Cold outreach campaign status | "How is the current cold outreach campaign performing?" |
| 9 | Any system health issues | "Is everything running? Any errors or warnings?" |
| 10 | Daily plan | "Give me the full daily plan." |

---

## Top 10 things to ask Solara during the day

Use these when you are working a specific deal or need to act fast.

| # | What you want | Example phrasing |
|---|---|---|
| 1 | Underwrite an incoming application | "Run underwriting on [Merchant Name]'s application. What does it look like?" |
| 2 | Shop out a deal | "Shop out [Merchant Name]'s application. Use our standard lender list." |
| 3 | Check lender status on a deal | "Where are we with the shop-out for [Merchant Name]? Have any lenders responded?" |
| 4 | Move a lead to the next stage | "Move [Lead Name] to the 'submitted' stage." |
| 5 | Log a manual follow-up reminder | "Remind me to follow up with [Merchant Name] on Friday about their renewal." |
| 6 | Find a specific deal | "Pull up everything on [Merchant Name]." |
| 7 | Get the sales angle on a deal | "What's the best pitch for [Merchant Name]'s situation? What angle should I lead with?" |
| 8 | Check offer status | "What offers have come in for [Merchant Name]? Which looks best?" |
| 9 | Escalate a stuck deal | "I have [Merchant Name] stuck at shopping for 10 days. What should I do?" |
| 10 | Add a note to a deal | "Add a note to [Merchant Name]: spoke with owner, calling back Thursday, positive sentiment." |

---

## Top 5 things to ask Helios for outreach

Helios owns the front-of-house lane. If Solara is the brain, Helios is the voice.

| # | What you want | Example phrasing |
|---|---|---|
| 1 | Start a cold outreach campaign | "We have a new list of 200 merchants. Start a cold outreach campaign — construction industry, $30K+ revenue." |
| 2 | Revival sequence for ghosted deals | "Which deals have gone cold in the last 30 days? Start a revival sequence." |
| 3 | NEPQ discovery script for a specific merchant | "Write me a discovery script for a restaurant owner with 3 MCA positions. NEPQ style." |
| 4 | SMS reply classification | "I got a reply from [number]. It says '[text]'. Is this a hot lead?" |
| 5 | Best hook for a specific situation | "What's the best pattern-interrupt opener for an overleveraged merchant? They have $2,100/day going out." |

---

## How to give Solara feedback

Solara learns from your corrections. If she gets something wrong, tell her directly in the chat — she logs it and adjusts.

**Use these phrases to teach her:**

| You want to | Say |
|---|---|
| Correct a wrong answer | "That's not right. [explain what's actually true]" |
| Stop a behavior | "Don't do that. [describe what to stop]" |
| Confirm something worked | "That's exactly right. Do it like that going forward." |
| Change a preference | "From now on, always [preference]. Remember this." |
| Record a business rule | "Remember: we never touch merchants in [category]. Not our market." |

Solara writes every correction into her memory. The next session, she starts with the updated rules.

---

## When to escalate to Ezra vs handle directly

Most things Solara handles without asking. When she needs you, she pings via Telegram.

**Solara asks Ezra:**

- Before sending a shop-out to a new lender she has not used before
- When a renewal draft is ready to send (she shows you the message, you approve)
- When an underwriting score is below a confidence threshold she cannot resolve
- When a lender reply is ambiguous and classification is unclear
- When she flags a potential stacking risk (your call whether to proceed)

**Handle directly without Solara:**

- Phone calls (Solara preps you, you dial)
- Offer negotiation (Solara surfaces the terms, you decide)
- Client relationship decisions (Solara gives you the data, you make the call)

---

## Power-user techniques

### Keyboard shortcuts in the dashboard

The SunBiz tenant dashboard (`/t/sun/`) supports these patterns:

- **Lead drawer** — click any lead row to open the detail drawer without leaving the pipeline page
- **Application timeline** — the timeline on each application shows every status change, note, and lender interaction in chronological order
- **Shop-out panel** — from any application, click "Shop Out" to see pre-ranked lenders, confirm the email body, and queue in one step
- **Bulk operations** — on the pipeline page, shift-click rows to select multiple leads for bulk stage moves or sequence enrollment

### Voice notes via Telegram

You do not need to type. Send Solara a voice note on Telegram. She transcribes it, extracts the instruction, and executes. Useful when you are on the road and need to log a call outcome immediately.

Example: "Hey Solara, just spoke with Mike at Metro Bakery. He's interested, wants to call back Monday. Move him to hot lead and set a follow-up for Monday morning."

### Batch operations

Instead of updating records one at a time, tell Solara the batch:

> "Mark all applications that have been at 'shopping' for more than 7 days as 'follow_ups'. Give me a list of who they are."

> "Enroll all leads who came in through JotForm last week and haven't been contacted yet in the cold outreach welcome sequence."

### Ask for the "why" not just the "what"

Solara can explain her own recommendations:

> "Why are you recommending I call [Merchant Name] first today?"

> "What's the reasoning behind this lender ranking?"

> "Why is this application's readiness score low?"

---

## Pro tips

1. **Start every morning with "Give me the full daily plan."** — one prompt, full picture. Do not skip this.
2. **Never say "loan"** — in compliance copy, always use "funding" or "working capital." Solara knows this and enforces it in all generated content, but double-check anything you send manually.
3. **JotForm is still active as intake** — until the first-party form cutover is complete, JotForm remains the primary lead intake. Solara monitors both.
4. **Speed-to-lead wins** — when Solara surfaces a new hot lead, call within 15 minutes. She can't make the call for you, but she can tell you exactly what to say.
5. **One platform, one Twilio number** — the SMS engine sends from your configured number. Do not change the Twilio credentials without updating `.env.agents` on the server.
6. **Refresh Solara's context at the start of long sessions** — if you have been chatting for more than an hour, say "prime" or "reload context" to make sure she has the latest pipeline state.
7. **Track CPQL, not just CPL** — for cold outreach campaigns, a $30 lead who does not qualify is worth less than a $60 lead who funds. Helios reports both.
8. **Check the automations page for daemon health** — `/t/sun/automations` in the dashboard shows which daemons are running, their last tick time, and any errors. If anything shows red, contact your OASIS operator.

---

## Quick reference card

Print this or save it as a phone note.

```
MORNING RITUAL
  "Give me the full daily plan."
  "Did any lenders reply overnight?"
  "Which applications are stuck?"

WORKING A DEAL
  "Run underwriting on [Name]."
  "Shop out [Name]'s application."
  "Pull up everything on [Name]."

GIVING FEEDBACK
  "That's not right. [correct it]"
  "Remember: [rule]"
  "Do it like that going forward."

OUTREACH (HELIOS)
  "Start a cold campaign — [industry, revenue band]."
  "Revival sequence for ghost deals."
  "Write a NEPQ script for [situation]."
```
