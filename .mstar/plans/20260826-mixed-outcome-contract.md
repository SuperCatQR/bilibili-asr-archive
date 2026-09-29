# Mixed Per-item Outcome and Exit Contract

> Iteration: `iter-2026-08-corpus-operations`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P1
- Category: bug / contract
- Status: Todo
- Depends on: none
- Primary spec: `.mstar/iterations/iter-2026-08-corpus-operations/specs/mixed-outcome-contract.md`

## Goal

Make partial batch behavior explicit and resumable. When a bounded command processes multiple work items, successful rows and artifacts must remain committed, failed or skipped rows must retain their retryable state, and the process exit code and summary must accurately distinguish usage errors, risk-control interruption, and incomplete per-item work. This closes the deferred mixed per-video exit-code characterization without changing the frozen manifest schema or risk taxonomy.

## Global Constraints

- Preserve `VALID_STATUSES`, the frozen `classify_risk` taxonomy, the JSONL manifest shape, and the documented exit meanings unless a new spec revision is explicitly created.
- A per-item failure must not roll back unrelated successful rows or erase their artifacts.
- Risk-control/API exhaustion remains exit 2 with cursor/manifest progress preserved; usage/config and missing optional ASR remain exit 1; complete successful work remains exit 0.
- Summaries may include only redacted scalar error codes/reasons. Never print or persist SESSDATA, cookie values, signed URLs, raw exception text, or tracebacks.
- Tests are deterministic: fake transport, temporary archive roots, and stubbed ASR; no live HTTP, model download, or real media transfer.
- `pilot` remains the frozen two-branch proof command and `run` remains complementary; no command is allowed to claim full corpus completion from a limited batch.

## Interfaces

- `cli.main(argv: list[str] | None) -> int` and the installed `bili-asr` entrypoint remain the observable command boundary.
- `RunSummary` / stage-attempt results and `RunLedger` coverage remain the source of batch outcome facts; any new result vocabulary must be documented and bounded.
- Manifest rows keep their existing statuses and `last_api_error_code` boundary. Retryable failures remain visible to `run --scope failed` or the existing command's retry selector.
- Human-facing output distinguishes `processed`, `failed`, `skipped`, `risk_interrupted`, and `scope not fully processed`; exact wording should follow current CLI conventions.

## In scope

- Characterization tests for mixed success/failure in `pilot`, `run`, `harvest-subs`, `download-audio`, and `asr` where current behavior is ambiguous.
- Correcting exit-code and summary aggregation so partial progress is durable and retryable.
- Tests for API/risk interruption versus ordinary per-item failure, optional-ASR failure, offline skip, budget skip, and terminal-row rerun.
- README and iteration-scoped contract documentation synchronized with observed behavior.

## Out of scope

- New scheduling architecture, concurrent workers, daemonization, or full-corpus execution.
- Any manifest JSONL migration, new status name, risk-taxonomy rewrite, or API/WBI redesign.
- Dependency/security upgrades, CI matrix work, search/index changes, or GUI.
- Changing the successful two-branch pilot semantics except to make its result aggregation honest.
- Storing credentials, signed URLs, raw exceptions, or full response bodies.

## Durable Roadmap and Dependencies

- Batch 1 (this plan): characterize existing mixed outcomes, lock the exit contract, and correct aggregation with focused regression coverage.
- Batch 2 (this iteration's scheduler plan): consume this contract for bounded full-visible-corpus scheduling; scheduler implementation must not invent a second exit taxonomy.
- Deferred: any richer operator analytics or per-error remediation workflow belongs in a future telemetry plan after real corpus runs. Final Done definition is a documented, tested, resumable partial-batch contract across all shipped processing commands.

## Tasks

### Task 1: Characterize and lock mixed outcomes

**Files:** CLI/coordinator tests, iteration spec, README as needed.

- [ ] Build fake multi-row scenarios covering one success plus one failure/skip for each shipped batch command.
- [ ] Record the current observable state, output, ledger/coordinator sidecars, and exit code; identify any mismatch with the frozen exit taxonomy.
- [ ] Lock the result aggregation rules, including explicit selectors that resolve only terminal rows and risk interruption precedence.
- [ ] Confirm retryable rows remain eligible and successful rows are not duplicated on rerun.

Run: characterization tests are deterministic and expose any pre-fix mismatch without weakening assertions.

### Task 2: Implement correction and regression guard

**Files:** CLI/coordinator aggregation, focused tests, documentation.

- [ ] Correct the smallest root cause so a mixed batch returns nonzero when requested work is incomplete while preserving successful state.
- [ ] Keep exit 2 reserved for risk/API terminal interruption and keep exit 1 for usage/config, per-item incomplete work, and missing optional ASR as documented.
- [ ] Ensure ledger/coordinator records retain redacted per-item outcomes and coverage snapshots after mixed runs.
- [ ] Add idempotent rerun and no-secret assertions for stdout, stderr, manifest, and sidecars.

Run: focused mixed-outcome tests plus the full suite pass with no live HTTP or model downloads.

## STOP Conditions

- Correct exit behavior requires changing `VALID_STATUSES`, manifest schema, or frozen risk taxonomy.
- Existing documentation/spec and implementation conflict in a way that cannot be resolved by an additive, explicit contract; record the conflict for PM.
- A test can only pass by swallowing a failure, rolling back successful rows, or exposing raw exception/credential data.
- Risk/API exhaustion cannot be distinguished from per-item failure without changing the transport contract; stop before inventing a new code.

## Drift Check

Before execution inspect current `cli.py` command handlers, `coordinator.py` `RunSummary`, `run_ledger.py`, `manifest.py`, README exit-code documentation, and all existing CLI/coordinator tests. Reconcile the prior live-pc and pilot-ops changes before locking any wording. If a command's current contract has already settled differently, update this plan during Prepare and keep the smallest compatible surface.

## Acceptance / Done Criteria

- [ ] Mixed success/failure/skip scenarios are characterized for shipped batch commands.
- [ ] Successful rows and artifacts remain durable; incomplete rows remain retryable and visible.
- [ ] Exit 0/1/2 meanings are explicit, tested, and risk-control exit 2 remains distinct.
- [ ] `pilot` and `run` retain their existing complementary responsibilities.
- [ ] Reruns are idempotent and all summaries/sidecars pass the no-secret boundary.
- [ ] Focused and full Python 3.12 suites pass without live HTTP/model downloads.
- [ ] `git status --short` contains only in-scope changes.

## Prepare → Execute Handoff

Prepare must lock command-by-command aggregation, precedence between risk interruption and per-item failure, explicit terminal selectors, and the no-secret output boundary. Execute Task 1 before Task 2; after all tasks, produce the branch review package, mandatory QC tri-review, and QA gate. The scheduler plan consumes this contract and may not redefine it inline.
