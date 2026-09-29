# Phase 1 Review-and-Edit Assignment: product-manager

**IDENTITY**
- Execute as: product-manager
- Who runs this turn: Phase 1 specialist reviewer/editor
- Delegation: forbidden
- Task category: docs / product completeness
- Iteration: `iter-2026-08-archive-foundations`
- Working branch: `main` (Phase 1 documentation draft only; do not commit or create branches)

**You are a leaf executor. You MUST NOT:**
- invoke or delegate to any other agent;
- create commits, branches, worktrees, pull requests, or pushes;
- modify product source, tests, dependency files, `{KNOWLEDGE_DIR}`, or root workflow status JSON;
- mark the compass locked or claim Phase 1 complete.

## Scope

Review and edit only these draft artifacts:

- `.mstar/iterations/iter-2026-08-archive-foundations/delivery-compass.md`
- `.mstar/iterations/iter-2026-08-archive-foundations/README.md`
- `.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- `.mstar/plans/20260824-cursor-based-resume.md`

You may create or edit only iteration-package files under `.mstar/iterations/iter-2026-08-archive-foundations/{guides,specs}/` when it improves the product decision record. Do not write `{KNOWLEDGE_DIR}`.

## Locked user decisions

- Direction: archive completeness foundation, not pilot or test-only scope.
- Current iteration plans: multi-part page-aware pipeline and cursor-based resumable metadata enumeration.
- Canonical part identity: `bvid:p<zero-based-page-index>`.
- Cursor persistence: archive-root atomic `meta-cursor.json` sidecar.
- Delivery branches: `iteration_base_branch=main`, `spec_integration_branch=iteration/iter-2026-08-archive-foundations`, `target_branch=main`.
- Non-goals: pilot execution, installed-entrypoint integration expansion, search/export, full-corpus scheduling, GUI, live Bilibili operations.

## Product review objectives

- Ensure the compass communicates user value, real end-state, measurable success criteria, and explicit non-goals.
- Confirm plan order and roadmap position are understandable to an operator, including why pilot is deferred.
- Ensure migration behavior gives operators a safe outcome for ambiguous legacy rows rather than silently guessing.
- Ensure the metadata resume semantics distinguish risk interruption from completed and deliberately limited enumeration.
- Tighten wording when needed; preserve the locked decisions above.

## Required return

State files edited, product risks corrected, and whether the draft is ready for architect review. Do not mark Phase 1 locked.
