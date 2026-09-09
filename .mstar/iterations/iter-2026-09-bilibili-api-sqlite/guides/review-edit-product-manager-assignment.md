# Review & Edit Assignment — product-manager

**IDENTITY**

- Execute as: `product-manager`
- Delegation: forbidden
- Who runs this turn: the dispatched product-manager role
- Task category: product-definition / prepare review
- Working branch: current Phase 1 control checkout; do not create a branch
- Branch policy: base `main`; integration `iteration/iter-2026-09-bilibili-api-sqlite`; target `main`

**You are a leaf executor. You MUST NOT:**

- invoke another role or subagent;
- implement application code or tests;
- mark an overall plan or iteration Done;
- add new documents under `.mstar/knowledge/`;
- commit or push;
- silently widen the locked scope.

## Assignment

Review and edit the Phase 1 preparation package for iteration
`iter-2026-09-bilibili-api-sqlite` from the product-definition perspective.

### Read first

- `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/delivery-compass.md`
- `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/README.md`
- all three files under `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/`
- all three plans under `.mstar/plans/20260909-*.md`
- `AGENTS.md` and `.mstar/AGENTS.md`

### Required review questions

1. Does the package preserve the user-confirmed intent: fresh redesign,
   no migration, bilibili-api gateway, 3NF structured SQLite, metadata/schema
   first, and bounded fake/live verification?
2. Are the product scope, non-goals, deferred roadmap, and final completion
   definition explicit enough to prevent subtitle/audio/ASR scope creep?
3. Are acceptance criteria observable and free of claims that the metadata-only
   iteration cannot prove?
4. Are the three plan dependencies and user-facing CLI boundary coherent?
5. Are credential, raw-response, and no-migration constraints visible to a
   future operator?

### Allowed edits

Edit only the compass, the three iteration specs, the three plans, and this
iteration package. Tighten product language, acceptance criteria, roadmap,
non-goals, and user-facing command descriptions. Keep iteration-only drafts in
this package; do not add shared knowledge.

### Completion requirements

Return a structured completion report in the final response using the shared
leaf template. State changed paths, validation performed, open product risks,
and whether the Prepare gate is `go` or `blocked`. Do not claim implementation
or QA completion.

## Evidence request

Run only read-only checks needed to verify cross-links and plan consistency. Do
not access live Bilibili or credentials.

## Handoff

After this role returns, PM will re-read the edited files and then dispatch the
architect role. This assignment is complete only when the edits are on disk.

## Status

Pending product-manager review.

## End

The PM lock remains owned by the parent project-manager.

## Agent Completion Report

The dispatched role must provide:

- Agent
- Task
- Status
- Scope Delivered
- Artifacts
- Validation
- Issues/Risks
- Plan Update
- Handoff
- Git

## No Knowledge Additions

Any reusable knowledge candidate should be reported to PM for iteration-close
compound; it must not be written here during iteration-start.

## No Product Code

Application source and test implementation are Phase 2 work and are not part of
this review-and-edit assignment.

## End of Assignment

Review the current disk state, edit surgically, and return the report.

## PM Decision Context

The user has already answered the direction-lock questions interactively; do not
reopen settled choices unless a contradiction is found in the files.

## Final Guard

If a material ambiguity blocks a truthful Prepare package, return `Blocked` to PM
with the exact file and decision needed; do not invent a default.

## Assignment Closed

No further dispatch is authorized from this role.

## End

This document is an assignment record, not a product specification.

## Audit Trail

Created by project-manager before the first sequential review invoke.

## End of File

Return only after the disk edits and validation are complete.

## Role Binding

The host invoke target must be exactly `product-manager`.

## Review Chain Order

This is seat 1 of 3.

## Contract

No parallel review is allowed for this seat.

## Close

Await parent PM consolidation.

## Final

Do not commit.

## End.

## Assignment Digest

Scope: product clarity, acceptance, roadmap, no implementation.

## End.

## Handoff Marker

Next role: architect, dispatched only by parent PM after this report.

## End.

## Truthfulness

Do not claim files or tests you did not inspect.

## End.

## Completion

Use shared completion report format.

## End.

## Final line

product-manager review pending.
