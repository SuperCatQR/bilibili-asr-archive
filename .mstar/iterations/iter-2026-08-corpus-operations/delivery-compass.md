---
iteration_id: iter-2026-08-corpus-operations
start_date: 2026-08-26
status: completed
end_date: 2026-08-29
iteration_base_branch: iteration/iter-2026-08-live-pc-pilot
target_branch: main
plans:
  - 20260826-full-corpus-scheduler
  - 20260826-cli-verification-baseline
  - 20260826-mixed-outcome-contract
---

# iter-2026-08-corpus-operations Delivery Compass

## Scope

### Autonomous direction lock

**Locked direction:** turn the proven bounded pilot into a resumable, full-visible-corpus operation while tightening release verification and mixed-outcome reporting.

**Rationale:** the preceding live PC iteration explicitly defers full-visible-corpus scheduling and the long-live proof to the next iteration (`.mstar/iterations/iter-2026-08-live-pc-pilot/delivery-compass.md:66-70`). The preceding pilot-ops compass separately identifies installed-entrypoint CI / verification baseline and mixed per-video exit-code characterization as following slices (`.mstar/iterations/iter-2026-08-pilot-ops/delivery-compass.md:84-88`). The audit README retains BUG-01/02 for complete multipart/cursor-resumability and its deferred verification/mixed-exit follow-ups (`.mstar/plans/audit-2026-08-24/README.md:9-19,59`). `PLAN.md` still defines M3 as a full ledger and M4 as searchable output (`bilibili-asr-archive/PLAN.md:108-116`), while the current CLI already exposes the pilot, run coordinator, ledger, FTS5, and offline surfaces (`bilibili-asr-archive/README.md:23-37`). These are the highest-leverage credible candidates after the two-branch pilot is green.

**Candidate trade-offs considered:**

1. **Full-visible-corpus scheduler + long-live campaign (selected):** closes the explicit next-iteration product gap and exercises the existing cursor, manifest, coordinator, budget, and reclaim boundaries. Trade-off: highest operational blast radius and requires conservative resumability rather than one-shot automation.
2. **Installed CLI verification baseline:** improves clean-install confidence and catches packaging/entrypoint regressions. Trade-off: mostly delivery infrastructure and cannot by itself advance corpus coverage.
3. **Mixed per-item outcome contract:** makes partial failures and exit codes honest and resumable. Trade-off: narrower user-visible scope, but it protects the scheduler from silently claiming success.

**Selection decision:** exactly three M-scale business plans are selected. Verification is a separate delivery-support product slice, while review/QC/QA/compound/close/PR work remains harness process and consumes no business-plan budget. The scheduler is first; outcome and verification contracts support it. Overflow (parallel scheduling, full automation, and any public-facing service) remains outside this iteration.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260826-full-corpus-scheduler | Full-visible-corpus resumable scheduler | Done | c74fc4e QA PASS; serially merged | Includes one explicit opt-in long-live proof path; bounded batches remain resumable |
| 20260826-cli-verification-baseline | Installed CLI verification baseline | Done | ad5253d post-merge QA PASS | Console-script, supported-environment, dependency/security, and no-index checks |
| 20260826-mixed-outcome-contract | Mixed per-item outcome and exit contract | Done | 482c54e QA PASS; serially merged | Characterize and correct partial-batch reporting without changing frozen risk taxonomy |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Autonomous direction lock + package | 2026-08-26 | done |
| Review chain + PM lock | 2026-08-26 | done; product/architect/writing seats PASS |
| Mixed outcome contract | 2026-08-27 | done |
| Full-visible-corpus scheduler + long-live bounded proof | 2026-08-28 | done; QA PASS and merged |
| Installed CLI verification baseline | 2026-08-28 | done; post-merge QA PASS and merged |
| Iteration close | 2026-08-29 | done; close commit `33b0a37`; PR #5 merged to `main` as `e0c1cb0` |

## Acceptance Criteria

1. **Full-visible-corpus operation:** a bounded, resumable command can process the visible manifest in repeatable batches, preserve cursor/manifest progress across risk interruption, and report whether the run is complete, limited, or interrupted without claiming more coverage than it has proved.
2. **Long-live safety:** one explicit opt-in multi-hour livestream fixture/live acceptance path is covered by the same audio budget, duration policy, post-archive reclaim, and retry semantics; no audio download is started when the conservative peak estimate would exceed the configured cap.
3. **Mixed outcomes:** successful rows remain committed when other rows fail; the command returns the documented nonzero result for unprocessed work, preserves retryable rows, and emits redacted actionable summaries without changing the frozen risk taxonomy or manifest schema.
4. **Release verification:** the supported Python 3.12 environment can exercise the installed `bili-asr` console script, and a repeatable verification baseline covers package metadata, tests, and dependency/security checks without live Bilibili traffic or model downloads.
5. **Safety and integrity:** SESSDATA, cookies, signed URLs, and raw exception text remain absent from manifest, cursor, ledger, coordinator, index, diagnostics, and committed artifacts; all declared tests pass.

## Non-Goals

- Unbounded concurrent scheduling, distributed workers, or a daemon/service.
- Full corpus completion as a claim of this iteration; batches remain bounded and resumable.
- Public API, GUI/search UI, diarization, LLM cleanup, or media redistribution.
- Manifest JSONL schema migration, frozen risk-taxonomy changes, or replacing `pilot` with `run`.
- Automatic PR merge or unattended use of credentials.
- Treating CI/dependency checks as a substitute for live operator acceptance of the long-live path.

## Roadmap Position

- **Current iteration:** delivered on `iteration/iter-2026-08-corpus-operations` at close commit `33b0a37` and merged to `main` by PR #5 as `e0c1cb0`; all three plans passed mandatory QC/QA and serial integration, with the long-live evidence, mixed-outcome contract, and installed baseline retained for release review.
- **Next iteration:** controlled corpus execution and coverage reporting after this iteration's PR has merged to `main`; owner: project-manager + fullstack-dev; trigger: Phase 5 merge-ready exit and scheduler telemetry exists; exit criterion: bounded coverage report reconciles with manifest/cursor without false completion.
- **Later:** concurrent scheduling and daemon/service operation; owner: project-manager + architect; trigger: measured single-worker throughput, disk behavior, and API-risk telemetry; exit criterion: an explicit concurrency plan with write isolation, backpressure, rollback, and a verified risk budget.
- **Final target:** PLAN M3 full ledger and searchable transcript archive, with bounded operations and honest resumability.

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot `workflows/<id>/snapshot.json` branch anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `iteration/iter-2026-08-live-pc-pilot` |
| `spec_integration_branch` | `iteration/iter-2026-08-corpus-operations` |
| `target_branch` | `main` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| A scheduler retries too broadly after a risk stop | Medium | High | Reuse cursor/risk budget, bounded batches, explicit interrupted state and resume evidence |
| Multi-hour audio exceeds local disk before reclaim | Medium | High | Conservative pre-download estimate, configured cap, duration policy, post-archive reclaim, live disk measurement |
| Partial failures are mistaken for complete success | Medium | High | Separate per-row outcome from batch exit, durable failed-stage records, mixed-outcome tests |
| Installed environment differs from development checkout | Medium | Medium | Console-script subprocess checks, Python 3.12 matrix and dependency verification baseline |
| Credentials or signed URLs leak through new summaries | Low | High | Reuse redaction seams and add artifact/diagnostic scans; never echo cookie values |

## Iteration package

| Path | Purpose |
|------|---------|
| `guides/` | Phase 1 review-chain snapshots and later operator runbook |
| `specs/` | New scheduler/outcome/verification contract deltas; frozen warehouse MVP remains `.mstar/specs/asr-archive-cli.md` |
| `README.md` | Package index |

## Quality Gate Summary

> Completed at iteration-close on 2026-08-29.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260826-full-corpus-scheduler | Approve | PASS / Done | none open | Scheduler implementation, WSL long-live acceptance, and evidence accepted; merged at `d84e433`; integration suite 366 passed |
| 20260826-cli-verification-baseline | Approve | PASS / Done | none open | Installed Python 3.12.13 baseline, 14-wheel fixture, 5/5 offline commands, docs/symlink boundary; merged at `ad5253d`; integration suite 392 passed |
| 20260826-mixed-outcome-contract | Approve | PASS / Done | none open | Frozen exit taxonomy and per-item aggregation verified; merged at `5b68423` |

## Compound Round Summary

> Completed at iteration-close on 2026-08-29.

- Two existing architecture-pattern knowledge documents were updated rather than creating duplicates: `bilibili-asr-archive-cli.md` now includes sequential scheduling, bounded transient-audio, and installed Python baseline guidance; `operational-sidecars.md` now includes scheduler sidecar and mixed-outcome precedence.
- Iteration package inventory: three specs were promoted with trace markers into those existing documents; three Phase 1 assignment guides remain retained historical snapshots; this compass remains the close record and was not promoted.
- No new `CONCEPTS.md` vocabulary was warranted. Knowledge index rows and source-plan descriptions were refreshed; both documents passed schema/index validation.
- Non-obvious lessons captured: fresh venvs may lack build backends; bootstrap declared build requirements before offline `--no-build-isolation`; validate console launcher before temporary cleanup; stage ordinary in-tree docs and reject symlinks; preserve redacted sidecars and explicit scope/limit state.

## Iteration Retrospective (minimal)

- **Delivered:** scheduler-first serial integration, honest mixed outcomes, bounded long-live acceptance, and an installed-console Python 3.12 baseline were completed without changing the frozen manifest or risk taxonomy.
- **Worked well:** transport seams and sidecars made failures resumable; explicit QA artifacts exposed cross-plan staging defects before close; post-merge verification caught the missing docs input and confirmed the final integrated package.
- **Friction:** the root checkout and control worktree initially carried divergent snapshots; system Python lacked `ensurepip`; verifier fixes were needed for build-backend bootstrapping, temporary-environment lifetime, and symlink-safe docs staging. These are now documented and tested.
- **Next improvement:** begin controlled corpus execution now that PR #5 is merged, with scheduler telemetry and coverage reconciliation as the first acceptance focus.
