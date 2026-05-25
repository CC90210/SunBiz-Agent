---
name: funding-vocabulary
description: Domain literacy for MCA and alternative business funding. Reference glossary and clarifying-question guide for when operators use ambiguous terms.
triggers:
  - "what does X mean"
  - "funding vocabulary"
  - "what is a factor rate"
  - "what is holdback"
  - "explain the terms"
  - "what does stacking mean"
  - "MCA glossary"
tier: stable
disable_model_invocation: false
---

# Funding Vocabulary

## Purpose

Shared language between Solara and the SunBiz team. When Ezra, Jordan, Ethan, or Emily use an ambiguous term, ask the right clarifying question. When surfacing data to the team, use precise industry language — never generic finance terms.

## Core Glossary

### Deal Economics

| Term | Definition |
|------|-----------|
| **Factor rate** | Cost multiplier on an MCA. A $50K advance at 1.38 = $69K total payback. Not an interest rate. Never call it one. |
| **Buy rate** | The factor rate at which the funder purchases the receivables (what SunBiz pays the lender). The spread between buy rate and sell rate (the merchant-facing rate) is SunBiz's margin. |
| **Holdback** | The percentage of daily revenue deducted for repayment (e.g., 15% holdback means 15% of each day's revenue goes to payback). Used in revenue-based repayment MCAs. |
| **Fixed daily ACH** | A fixed daily dollar amount debited from the merchant's bank account, regardless of revenue. More common than holdback in practice. |
| **Payback period** | Estimated duration to repay the advance at the daily payment rate. Not contractually fixed in revenue-based MCAs. |
| **RTR (Right to Receive)** | The receivables that SunBiz / the funder has purchased. The advance is the purchase price; the RTR is the future revenue stream purchased. |
| **Total payback** | `advance_amount × factor_rate`. This is what the merchant owes in total. |
| **ISO commission** | The broker fee paid to SunBiz Funding by the funder upon closing. Typically 8–15% of the advance amount depending on funder relationship. |

### Products

| Term | Definition |
|------|-----------|
| **MCA (Merchant Cash Advance)** | Purchase of future receivables. NOT a loan. SunBiz's primary product. |
| **LOC (Line of Credit)** | A revolving credit facility. The Phase 4 goal in SunBiz's multi-phase consolidation strategy — lower cost, more flexibility than MCA. |
| **Term loan** | Fixed repayment schedule, fixed interest, fixed term. More traditional; requires stronger credit profile. |
| **SBA loan** | Government-backed loan. Long process (weeks to months), best terms. Usually not a fit for SunBiz's merchant profile. |
| **Revenue-based financing** | Repayment tied to a % of revenue, not a fixed daily amount. True holdback model. |

### Deal Risk & Position

| Term | Definition |
|------|-----------|
| **Position** | One active MCA advance on a merchant. A merchant with 3 active advances has 3 positions. |
| **Stacking** | A merchant taking a new MCA on top of existing ones without the existing funder's knowledge. Violation of most MCA contracts. Funders check for this. |
| **Syndication** | Multiple funders sharing a single advance. SunBiz may participate as a syndicator on larger deals. |
| **Leverage %** | `(total_daily_payments / daily_revenue) × 100`. A merchant paying $800/day with $2,000/day revenue is at 40% leverage. Above 40–45% = overleveraged. |
| **NSF (Non-Sufficient Funds)** | A failed bank transaction due to insufficient balance. NSF count is the primary risk signal funders look at. More than 5 NSFs in 90 days = near-automatic decline at most funders. |
| **Default** | Merchant stops making payments on the advance. Can trigger UCC lien enforcement, collections, or legal action. |
| **UCC (Uniform Commercial Code) lien** | A security interest filed against the merchant's assets by the funder. Most MCAs file a UCC-1 as collateral. |

### Underwriting

| Term | Definition |
|------|-----------|
| **Paper grade** | A/B/C/D classification of the deal risk. A = clean, strong; D = death spiral. See `skills/underwriting-flow/SKILL.md` for grading criteria. |
| **Readiness score** | Solara's 0–100 composite score reflecting the deal's shopability. Combines revenue, leverage, NSF, positions. |
| **Bank statements** | 3–4 months of merchant's business bank statements. Primary underwriting document. Funders require them to calculate revenue, NSF count, and existing payment obligations. |
| **Voided check** | Required to verify the merchant's bank account for ACH setup. |
| **Stipulations (stips)** | Additional documents or conditions a funder requires before approving. Examples: tax returns, proof of ownership, lease agreement, driver's license. |

### Lender Relationship

| Term | Definition |
|------|-----------|
| **Submission** | Sending a deal package to a funder for review. |
| **Approval** | Funder agrees to fund the deal, usually with specific terms. |
| **Counter** | Funder offers different terms than requested (lower advance, higher rate, shorter term). |
| **Decline** | Funder passes on the deal. Always log the reason in `lender_feedback`. |
| **Lockbox** | A dedicated bank account controlled by the funder, through which the merchant routes all revenue. Used for revenue-based MCAs as the holdback mechanism. |

## Clarifying Questions

When Ezra uses an ambiguous term, ask the right question instead of guessing:

| Ezra says... | Right clarifying question |
|-------------|--------------------------|
| "They want better terms" | "Better in which direction — lower factor rate, longer term, or higher advance amount?" |
| "The deal is stacking" | "Do you mean the merchant has undisclosed existing positions, or we're considering placing on top of an existing advance?" |
| "The funder wants more" | "More what — more documents (stips), a higher payback amount, or a larger advance?" |
| "Clean the file up" | "Clean in which sense — remove old NSFs from the narrative, restructure the submission package, or address a specific lender question?" |
| "It's not moving" | "Not moving at which stage — underwriting, submission to lenders, or merchant decision?" |

## Language Rules (Compliance)

Always use correct language with merchants and in any external communication:

| Say this | Not this |
|----------|---------|
| Advance | Loan |
| Funding / capital | Money / debt |
| Factor rate | Interest rate / APR |
| Funder / capital partner | Lender |
| Merchant | Borrower |
| Remittance | Repayment |
| Purchase of receivables | Loan repayment |

## Related Skills

- [[skills/underwriting-flow/SKILL.md]] — uses paper grade and readiness score terms
- [[skills/lender-intelligence/SKILL.md]] — uses decline reason codes and lender relationship terms
- [[skills/shop-out-routing/SKILL.md]] — uses submission, approval, counter, decline flow
- [[skills/lending-industry/SKILL.md]] — broader regulatory and compliance context
