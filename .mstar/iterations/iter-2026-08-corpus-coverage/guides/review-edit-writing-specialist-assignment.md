# Phase 1 Review & Edit Assignment — Writing Specialist

**IDENTITY**
- Execute as: `writing-specialist`
- Delegation: forbidden (leaf executor; no subagent dispatch)
- Direction lock mode: autonomous
- Task category: docs / corpus-hygiene
- Skill presets: `mstar-harness-core`, `mstar-roles`, `mstar-conventions`, `mstar-artifacts`, `mstar-iteration`, `mstar-coding-behavior`, `mstar-host`

**Working branch:** `iteration/iter-2026-08-corpus-coverage` (existing integration branch; documentation/spec hygiene only)

## Assignment

Perform the final Phase 1 writing pass after product-manager and architect have completed their sequential reviews.

Assigned paths in the control worktree:

- Compass: `/root/workspace/bilibili-asr-archive/.worktrees/iter-2026-08-corpus-coverage-control/.mstar/iterations/iter-2026-08-corpus-coverage/delivery-compass.md`
- Package: `/root/workspace/bilibili-asr-archive/.worktrees/iter-2026-08-corpus-coverage-control/.mstar/iterations/iter-2026-08-corpus-coverage/`
- Plans: `/root/workspace/bilibili-asr-archive/.worktrees/iter-2026-08-corpus-coverage-control/.mstar/plans/20260828-*.md`
- Existing specs/knowledge for hygiene: `/root/workspace/bilibili-asr-archive/.worktrees/iter-2026-08-corpus-coverage-control/.mstar/specs/` and `/root/workspace/bilibili-asr-archive/.worktrees/iter-2026-08-corpus-coverage-control/.mstar/knowledge/`

Read the completed package, product README/PLAN, all existing `.mstar/specs/` and active `.mstar/knowledge/README.md` entries. Perform corpus hygiene: iteration-specific drafts belong under this package; long-term locked specs belong under `.mstar/specs/`; reusable knowledge is not created or promoted in Phase 1. Fix broken references, stale prose, inconsistent names/status vocabulary, incomplete consumer-facing explanations, and malformed Markdown without changing product behavior. Preserve exact business scope, six-plan XL budget, branch anchors, sequential/no-daemon default, redaction boundary, and machine-checkable acceptance. All references must be resolvable from the current HEAD after Phase 1 commit; do not reference chat, unmerged drafts, or untracked process-only reports as authoritative.

Edit only the assigned compass/package/specs/plans, iteration index if needed, and product README if documentation corrections are necessary. Do not edit implementation source/tests, do not add knowledge documents, do not commit, and never inspect/output credentials or cookie values.

## PM amendment — existing knowledge reference repair

The writing hygiene pass identified stale evidence paths in the already tracked `.mstar/knowledge/architecture-patterns/*.md`. Repair those existing references in place so they resolve from this branch's HEAD; do not add a knowledge document, do not promote iteration content, and do not change the knowledge guidance. Use stable current paths (product source/specs, current package paths only where they exist) or commit identifiers for historical evidence. This is an authorized documentation-only correction before Phase 1 lock.

## Deliverable

Return a Completion Report with changed paths, hygiene fixes, unresolved issues, and evidence. Do not mark plans Done. The project-manager will set compass frontmatter to `locked` only after reviewing your report.
