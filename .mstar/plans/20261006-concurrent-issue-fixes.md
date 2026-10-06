# Concurrent issue fixes — 2026-10-06

Integration branch: `iteration/iter-2026-10-issue-concurrency`; eventual PR target: `main`.

## Scope and lanes

- #216: centralize CLI command handler, mutation, lock and artifact-root policies; retain command behavior and package monkeypatch seams; test registry completeness and refusal policies.
- #217: add a concise repository-root README linking installation, offline tests, verification and operational documentation.
- #218: define durable and archive-eligible harness evidence, measurable archival triggers and a checksum/pointer procedure that preserves tracked references.
- Review #210 against current authenticated corroboration filters and regression tests; do not claim an already-landed change as new work.

Each lane uses its own feature branch/worktree based on this committed plan. Stage only lane-owned paths, commit reviewed changes and merge into the integration branch. Preserve existing worktrees, untracked runtime data and engine-owned registers.

## Validation and delivery

Run focused CLI/registry and harness checks, then the complete offline product suite under the existing Python 3.12 WSL development environment. Confirm source compilation and whitespace checks. Record actual results and skips in a tracked verification report. No real-model/GPU or live upstream result is implied by offline tests. GitHub issue closure and publication are separate from local implementation; report reviewable local commits and remaining issues.
