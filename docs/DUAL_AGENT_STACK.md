# Sun Biz Dual-Agent Stack

This product is intended to run as two cooperating operators inside one Sun Biz workspace.

## Agent roles

### Solara / Solar

Solara is the backend admin operator.

Owns:
- lead review and prioritization
- lender fit and application routing
- funded deals and renewal scheduling
- commission tracking
- compliance rails and record integrity

### Suga Sean

Suga Sean is the outreach operator.

Owns:
- text blasts
- email outreach
- reply triage
- meeting-setting
- keeping follow-up volume moving without contaminating the funding ledger

## Why the split exists

Ops and outreach move at different speeds.

- Solara should be conservative because it protects the source of truth.
- Suga Sean should be fast because it protects pipeline motion.

The system works best when Solara holds the deal state and Suga Sean handles the next touch.

## Client-facing language

When this stack is presented to the client inside the shared dashboard:

- Solara should be framed as the primary digital employee.
- The shell should be called the Command Center.
- The local data store should be called the Local Brain.
- Technical names like `turso` or substrate-level wording should stay in operator docs, not the client UI.

## Command center expectation

The Sun Biz tenant should provision with:

- `primary_agent = "sunbiz"`
- `agents_enabled = ["sunbiz", "suga_sean"]`

That gives the operator one workspace with two specialist agents instead of forcing Sun Biz into a single monolithic persona.
