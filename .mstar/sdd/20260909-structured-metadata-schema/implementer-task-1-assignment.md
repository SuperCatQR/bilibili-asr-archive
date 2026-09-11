# SDD Implementer Assignment — Plan 1 Task 1

**IDENTITY**

- Execute as: `fullstack-dev`
- Track: `primary`
- Delegation: forbidden
- Task category: backend / data persistence implementation
- Execution mode: `sdd`
- Model tier: `standard`
- Working branch: `feature/20260909-structured-metadata-schema`
- Worktree path: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema`
- Control harness root: `/root/workspace/bilibili-asr-archive/.mstar`
- Plan Path: `/root/workspace/bilibili-asr-archive/.mstar/plans/20260909-structured-metadata-schema.md`
- SDD dir: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260909-structured-metadata-schema`
- Task brief: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260909-structured-metadata-schema/task-1-brief.md`
- Report file: `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260909-structured-metadata-schema/implementer-task-1-report.md`

**You are a leaf executor. You MUST NOT:**

- dispatch another agent;
- edit the control checkout or harness SSOT;
- change the plan scope;
- read or migrate old JSONL archive data;
- commit files outside the assigned feature branch.

## Assignment

Implement exactly Task 1 from the task brief. Create a fresh normalized SQLite
schema and bootstrap repository for the new metadata path. Do not implement the
bilibili-api gateway, ingestion service, CLI replacement, media storage, or ASR.

## First steps

1. In a shell, observe `pwd` and `git branch --show-current`.
2. Confirm cwd is exactly the assigned worktree and branch is exactly
   `feature/20260909-structured-metadata-schema`; if not, stop and report BLOCKED.
3. Read the task brief and the primary spec at
   `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/structured-metadata-storage.md`.
4. Inspect nearby package/test conventions in the feature worktree before writing.

## Required deliverables

- `bilibili-asr-archive/src/bili_asr/storage/__init__.py`
- `bilibili-asr-archive/src/bili_asr/storage/schema.sql`
- `bilibili-asr-archive/src/bili_asr/storage/database.py`
- `bilibili-asr-archive/tests/test_storage_schema.py`

## Required behavior

- Use Python stdlib `sqlite3`; no ORM and no network imports.
- Implement `open_database(path)` and enable `PRAGMA foreign_keys = ON` for
  every connection.
- Create the normalized base tables specified in the brief/spec, including
  reserved audio/transcript tables with explicit `ON DELETE RESTRICT` foreign
  keys. Do not persist `work_id`; expose it only through the required view or a
  computed application property.
- Enforce required primary keys, candidate-key uniqueness, status checks,
  non-negative/positive checks, and the three required views.
- Keep current metadata only; no snapshot/history tables in this task.
- Make schema initialization safe for a fresh database and deterministic when
  called repeatedly.
- Add tests for fresh initialization, foreign-key enforcement, duplicate keys,
  derived work ID view, absence of base-table `work_id`, and schema constraints.

## Verification

Run from the feature worktree:

`./.venv/bin/python -m pytest tests/test_storage_schema.py -v`

If the feature worktree has no `.venv`, use the control checkout interpreter
`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` only
for execution while keeping all edits in the assigned worktree. Also run
`git diff --check` and inspect the final diff.

## Commit and report

- Commit the completed Task 1 changes on the assigned branch with a task-scoped
  commit message.
- Write the full report to the assigned report file, including status, files,
  test commands/output, self-review, and worktree path.
- Return a short summary only after the report and commit exist.

## Stop conditions

Report BLOCKED or NEEDS_CONTEXT instead of guessing if the spec conflicts with
existing package conventions, if a required schema relationship cannot be
represented without denormalization, or if the checkout/branch is wrong.

## End

Do not mark the overall plan Done; PM will run the task review and later QC/QA.

## Completion report headings

- Status
- Implemented / attempted
- Tests
- Files changed
- Self-review notes
- Worktree path used
- Git commit

## Handoff

After your report returns, PM will create the SDD review package and dispatch a
fresh code-reviewer for this task.

## Final guard

No knowledge documents, no live API calls, no credentials, no raw API payloads,
and no changes outside the listed implementation/test files.

## End of assignment

This assignment is Task 1 only.

## Assignment digest

Fresh SQLite schema + bootstrap + schema tests, in the Plan 1 feature worktree.

## End.

## Role binding

The host invoke target must match `fullstack-dev`.

## Dispatch binding

One implementer only; no parallel implementation.

## Review binding

Task reviewer follows after commit.

## Close

Return completion report.

## End of file

The parent PM owns plan status and integration merge.

## Truthfulness

Report only checks actually run.

## Final

No commit outside the assigned branch.

## End.

## Scope lock

Do not implement Tasks 2 or 3 in this turn.

## Completion

Write report to the absolute control SDD path.

## End.

## User intent

Fresh redesign; no migration.

## End.

## Safety

No secrets.

## End.

## Finish

Await parent PM.

## End.

## Assignment closed

fullstack-dev Task 1.

## End.

## Final instruction

Implement, test, commit, report.

## End.

## Done

Task-level only; not plan Done.

## End.

## EOF


