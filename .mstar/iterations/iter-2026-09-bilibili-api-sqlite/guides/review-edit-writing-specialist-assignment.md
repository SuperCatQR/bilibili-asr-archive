# Review & Edit Assignment — writing-specialist

**IDENTITY**

- Execute as: `writing-specialist`
- Delegation: forbidden
- Who runs this turn: the dispatched writing-specialist role
- Task category: writing / prepare review
- Working branch: current Phase 1 control checkout; do not create a branch

**You are a leaf executor. You MUST NOT:**

- invoke another role or subagent;
- implement application code or tests;
- mark an overall plan or iteration Done;
- add new documents under `.mstar/knowledge/` during iteration-start;
- commit or push.

## Assignment

Review and edit the Phase 1 preparation package for iteration
`iter-2026-09-bilibili-api-sqlite` from the writing and corpus-hygiene perspective.

### Read first

- `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/delivery-compass.md`
- `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/README.md`
- all three files under `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/`
- all three plans under `.mstar/plans/20260909-*.md`
- `.mstar/specs/README.md` (check for draft/locked clarity)
- `.mstar/iterations/README.md` (check row format)

### Required review questions

1. Are terminology and naming consistent across compass/specs/plans?
2. Are cross-references correct and resolvable?
3. Is the iteration package index complete and correctly formatted?
4. Are specs correctly marked as iteration-scoped drafts (not locked warehouse specs)?
5. Are any existing knowledge or specs misplaced or needing archive status?

### Allowed edits

Edit compass, specs, plans, iteration package README, and iteration/specs indexes.
Improve clarity, consistency, cross-references, and corpus hygiene. Do not add new
knowledge documents during iteration-start.

### Completion requirements

Return a structured completion report using the shared leaf template. State changed
paths, validation performed, open writing/hygiene issues, and whether corpus state
is `go` or `blocked`.

## Status

Pending writing-specialist review (seat 3 of 3, final before PM lock).

## End

Return only after the disk edits and validation are complete.
