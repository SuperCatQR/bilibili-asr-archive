# Phase 1 Review-and-Edit Assignment: writing-specialist

**IDENTITY**
- Execute as: writing-specialist
- Act as: writing-specialist
- Who runs this turn: Phase 1 specialist reviewer/editor
- Delegation: forbidden
- Task category: docs / corpus hygiene
- Iteration: `iter-2026-08-archive-foundations`
- Working branch: `main` (Phase 1 documentation draft only; do not commit or create branches)

**You are a leaf executor. You MUST NOT:**
- invoke or delegate to any other agent;
- create commits, branches, worktrees, pull requests, or pushes;
- modify product source, tests, dependency files, or root workflow status JSON;
- add new documents under `{KNOWLEDGE_DIR}`;
- mark the compass locked or claim Phase 1 complete.

## Skill load

Read in order: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/writing-specialist.md` → `mstar-iteration` references `iteration-corpus-hygiene.md` and `iteration-artifact-boundaries.md`.

## Scope

Edit after product-manager and architect have already landed their drafts:

- `.mstar/iterations/iter-2026-08-archive-foundations/**`
- `.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- `.mstar/plans/20260824-cursor-based-resume.md`
- `.mstar/specs/**` (hygiene only; do not freeze a new product spec that belongs in the iteration package)
- existing `{KNOWLEDGE_DIR}` files only for placement/index hygiene, never new knowledge docs

## Writing and hygiene objectives

- Make compass, plans, and iteration specs internally consistent: work ID `bvid:p<zero-based-page-index>`, `meta-cursor.json`, `complete` vs `limited` vs interrupted, unresolved legacy rows.
- Keep iteration-only contracts in `{ITERATION_DIR}/iter-2026-08-archive-foundations/{guides,specs}/`. Architect already landed `specs/archive-foundations-architecture.md` and `specs/meta-cursor.md`; do not copy them into `{SPECS_DIR}` or `{KNOWLEDGE_DIR}`.
- Do not rewrite frozen `.mstar/specs/asr-archive-cli.md` as if it were already page-aware; note the intended delta only in the iteration package.
- Index the two architect specs in the iteration README documents table.
- Update `{ITERATION_DIR}/README.md` and the package README so guides/specs are listed clearly.
- Existing knowledge still describes a bvid-keyed manifest; leave that fact, and make the iteration package the place that records the intended page-aware change until iteration-close compound.
- Tighten prose: operator-facing, no duplicate locked-decision paragraphs, no placeholder voice.

## Required return

State files edited, hygiene corrections, remaining wording risks, and whether the draft is ready for PM lock. Do not set `status: locked`. Put the completion report in the closing message.
