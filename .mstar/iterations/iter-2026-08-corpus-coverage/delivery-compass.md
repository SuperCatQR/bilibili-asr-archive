---
iteration_id: iter-2026-08-corpus-coverage
start_date: 2026-08-28
status: completed
end_date: 2026-08-30
iteration_base_branch: iteration/iter-2026-08-corpus-operations
target_branch: main
plans:
  - 20260828-controlled-corpus-campaign
  - 20260828-coverage-telemetry-reconciliation
  - 20260828-subtitle-quality-campaign
  - 20260828-transcript-explorer
  - 20260828-archive-integrity-recovery
  - 20260828-concurrency-safety-gate
---

# iter-2026-08-corpus-coverage Delivery Compass

## Direction lock (autonomous)

**Locked direction:** convert the shipped bounded, sequential scheduler into measured corpus production: reconcile coverage evidence, maximize subtitle-first archival, safely process selected ASR work, make completed transcripts searchable and integrity-reviewable, and define an evidence-gated path before any concurrency or daemonization.

**User value:** the archive operator can tell what is genuinely enumerated, processed, searchable, and integrity-reviewed; request bounded recovery evidence without state mutation; rerun bounded work without duplicate ownership; and use transcripts without mistaking a limited batch or a missing reclaimed audio file for corpus failure.

**Evidence basis:** the prior corpus-operations compass explicitly deferred measured production and concurrency until telemetry exists; the product README documents `fetch-meta`, subtitle-first processing, `run`, `schedule`, JSONL manifest/cursor/ledger sidecars, FTS5 search/export, audio budgeting, and reclaim behavior. The product PLAN still records M0/M1/M3/M4 as incomplete. No slice may claim more than these shipped seams support.

**Selection:** all six evidence-backed business slices are selected. Harness review/edit, SDD, QC, QA, compound, close, PR, and merge-ready work are process gates and do not consume the six-plan XL business budget.

**XL budget:** exactly six business plans; all six plans completed their own SDD, QC, QA, and serial integration lifecycle.

## Plans

| plan_id | Name | Status | Integration evidence |
|---|---|---|---|
| `20260828-controlled-corpus-campaign` | Controlled corpus campaign execution | Done | `11db5da` |
| `20260828-coverage-telemetry-reconciliation` | Coverage telemetry and reconciliation | Done | `6a3e86b` |
| `20260828-subtitle-quality-campaign` | Subtitle coverage and transcript quality campaign | Done | `383cbf6` |
| `20260828-transcript-explorer` | Transcript explorer search and export completion | Done | `22fd0bd` |
| `20260828-archive-integrity-recovery` | Archive integrity verification and recovery | Done | `7af7500` |
| `20260828-concurrency-safety-gate` | Concurrency and daemon safety gate | Done | `69b9530` |

## Specify / clarify decisions

- **True problem:** operational corpus coverage is not yet measurable or safely repeatable at production scale, despite shipped sequential primitives.
- **Success判据:** all six contracts have deterministic inputs/outputs, explicit denominators and boundaries, fixture-only verification, and no false-complete or semantic-correctness claims.
- **Non-goals:** public service/UI, redistribution, unbounded scheduling, concurrency/daemon enablement, schema/status-taxonomy migration, semantic correction, diarization, credential acquisition, and live traffic in tests.
- **Concurrency boundary:** sequential production remains the only default. A go decision may produce evidence and architecture only; it cannot silently enable workers, services, or automatic startup.
- **Roadmap boundary:** this iteration supplies the evidence spine and safety decision. A later iteration may implement only the concurrency mode explicitly allowed by the gate and only after the documented exit conditions pass.

## Scope and sequencing

| Order | Plan | User value | Depends on | Target state / acceptance anchor |
|---|---|---|---|---|
| 1 | `20260828-controlled-corpus-campaign` | Repeatable bounded production | shipped scheduler/coordinator seams | Atomic redacted checkpoint; valid risk-only resume; no batch-as-corpus claim; exit 0/1/2 preserved |
| 2 | `20260828-coverage-telemetry-reconciliation` | Honest cumulative coverage | campaign sidecars and existing manifest/cursor/ledger | Read-only stable report with explicit denominator, batch/cumulative distinction, and named contradictions |
| 3 | `20260828-subtitle-quality-campaign` | Lower ASR cost and expose defects | reconciled denominator and subtitle/archive seams | Source/language/status counts plus deterministic cue/artifact reason codes; no semantic verdict |
| 4 | `20260828-transcript-explorer` | Research completed transcripts | coverage and quality vocabulary | Bounded stable FTS5 search/export, filters and diagnostics; manifest remains immutable |
| 5 | `20260828-archive-integrity-recovery` | Find damage and produce bounded recovery evidence | status/artifact/reclaim semantics | Idempotent read-only verify; explicit bounded audit-only recovery selection and redacted append-only evidence; reclaimed audio accepted when archive outputs exist |
| 6 | `20260828-concurrency-safety-gate` | Decide whether future parallelism is safe | campaign, telemetry, integrity evidence | Deterministic go/no-go report; default no-go on missing/contradictory evidence; no concurrent production enabled by this slice |

Plans 1 and 2 form the production evidence spine. Plans 3 and 4 may be developed after their contracts are stable, but their production claims consume the reconciled vocabulary. Plan 5 shares artifact semantics and must not erase valid prior evidence. Plan 6 is last and is architecture/evaluation only unless every threshold is evidenced.

## Milestones

| Milestone | Target date | Status |
|---|---|---|
| Autonomous direction lock + package | 2026-08-28 | completed |
| Review & Edit chain + Prepare lock | 2026-08-28 | completed |
| Telemetry/reconciliation contract | 2026-08-29 | completed |
| Controlled campaign + subtitle quality slices | 2026-08-30 | completed |
| Explorer + archive integrity slices | 2026-08-31 | completed |
| Concurrency safety gate | 2026-09-01 | completed |
| Iteration close | 2026-09-02 | completed |

## Acceptance criteria

1. Each plan has a named interface, deterministic fixture proof, stop conditions, and a checkbox checklist tied to its target state.
2. Campaign evidence is bounded, atomic, redacted, resumable only for valid risk interruption, and never represents limited work as full corpus completion.
3. Coverage reports reconcile manifest, cursor, scheduler, ledger, attempts, and artifacts with explicit denominator and contradiction categories; reports are read-only.
4. Subtitle quality reports quantify source/language/status and deterministic cue/artifact defects without semantic correctness claims.
5. Search/export is bounded, stable, filtered, coverage-aware, read-only against manifest, and redacted.
6. Integrity verification distinguishes required archive outputs from intentionally reclaimed audio; recovery is audit-only and emits bounded redacted candidate evidence without mutating manifest status or requeueing work.
7. Concurrency evaluation rejects missing/contradictory evidence and leaves sequential mode unchanged; no daemon/worker is enabled by this iteration.
8. Python 3.12 fake-only tests and declared local verification pass; tests perform no live Bilibili traffic, model download, or media transfer.

## Non-goals

- Public API/service, GUI, remote search, media redistribution, or automatic publishing.
- Unbounded scheduling, distributed workers, daemon/service deployment, or silent concurrency.
- Manifest JSONL schema migration or changes to `VALID_STATUSES` / frozen risk taxonomy.
- Semantic transcript correctness, automatic editorial correction, diarization, or LLM cleanup.
- Automatic credential acquisition or storing/reproducing cookie values, signed URLs, raw exceptions, models, or media in committed artifacts.
- Declaring the visible corpus archived merely because a bounded campaign completes.

## Roadmap Position

- **Current iteration — delivered:** `iter-2026-08-corpus-coverage` ships measured, auditable sequential corpus operations, stable search/export, confined integrity verification, audit-only recovery, and a deterministic non-enabling concurrency gate. Integration revision `69b9530` passes 612 tests; production remains `sequential-no-daemon`.
- **Next iteration — measured sequential corpus production:** owner operator + `@project-manager`; trigger: valid login supplied locally, explicit Windows WSL archive root/storage/batch/rate-risk boundaries, and a fresh manifest snapshot denominator; exit: repeated authorized batches reconcile cumulative coverage, structural quality, integrity, retry queues, disk/reclaim, API risk, and crash/restart evidence without false-complete claims.
- **Later — conditional concurrency implementation:** owner `@architect` + `@ops-engineer`; trigger: reviewed campaign/reconciliation/recovery/ownership/isolation measurements satisfy every explicit threshold, `evaluate-concurrency` returns `go`, and a separate implementation plan is approved; exit: any new mode preserves single ownership, manifest/sidecar compatibility, risk taxonomy, and reconciled production evidence under load.
- **Final target:** PLAN M0/M1/M3 full visible-corpus enumeration, subtitle coverage measurement, and archived/missing inventory plus the already delivered M4 searchable transcript archive, bounded and resumable with no unauthorized redistribution.

## Delivery Branch Policy

| Field | Value |
|---|---|
| `iteration_base_branch` | `iteration/iter-2026-08-corpus-operations` |
| `spec_integration_branch` | `iteration/iter-2026-08-corpus-coverage` |
| `target_branch` | `main` |

## Risk register

| Risk | Mitigation |
|---|---|
| API interruption | Sequential bounded scopes, existing risk taxonomy, cursor persistence, redacted telemetry, explicit stop |
| Contradictory totals | One reconciliation algorithm, explicit denominator, corruption fixtures, no false-complete state |
| Quality false skips | Report first; route only clearly empty/malformed input to retryable state |
| Stale/leaky index | Read-only manifest-derived rebuild, deterministic filters, redaction tests |
| Destructive recovery | Read-only verifier; bounded audit-only `recover`; process lock and fail-closed sidecar validation; no requeue/status/artifact mutation; reclaimed-audio semantics preserved |
| Unsafe concurrency | Last slice; deterministic no-go by default; no enablement without measured evidence |

## Iteration package

Package specs remain the implemented iteration snapshot. Reusable architecture guidance was promoted by updating `.mstar/knowledge/architecture-patterns/operational-sidecars.md` and `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md`; the package README records the trace.

| Path | Purpose |
|---|---|
| `specs/` | Six product contracts |
| `README.md` | Package index and boundary |

## Quality Gate Summary

Every plan completed L2 review, distinct-seat mandatory QC tri-review, mandatory QA, and serial integration with no open residual. Counts below are the plan-local final evidence; the final merged integration suite is `612 passed`.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---|---|---|---|---|
| 20260828-controlled-corpus-campaign | Approve | PASS | none | `11db5da` merge; QC consolidated + QA report; 29 focused / 409 full-suite tests |
| 20260828-coverage-telemetry-reconciliation | Approve | PASS | none | `6a3e86b` merge; QC consolidated + QA report; 37 focused / 434 full-suite tests + smoke |
| 20260828-subtitle-quality-campaign | Approve | PASS | none | `383cbf6` merge; QC consolidated + QA report; 51 focused / 77 relevant / 448 full-suite tests + smoke |
| 20260828-transcript-explorer | Approve | PASS | none | `22fd0bd` merge; QC consolidated + QA report; 56 focused / 76 relevant / 470 full-suite tests; post-merge 470 |
| 20260828-archive-integrity-recovery | Approve | PASS | none | `7af7500` merge; exact-range tri-review; 73 focused / 503 full-suite tests; audit-only recovery contract |
| 20260828-concurrency-safety-gate | Approve | PASS | none | `69b9530` merge; exact-range tri-review; 129 focused / 612 full-suite tests + synthetic CLI; post-merge 612 |

## Compound Round Summary

- **Self-check:** Q1 Yes (multi-plan implementation/review took multiple attempts), Q2 Yes (state-ownership, denominator, confined read, audit-only recovery, and non-enablement rules are non-obvious), Q3 Yes, Q4 Yes, Q5 Yes (high overlap with the two active architecture docs), Q6 Yes, Q7 Yes (failed second-SSOT/requeue/optimistic-enablement framings are durable warnings), Q8 Yes. Per Q5, no duplicate knowledge document was created; both existing documents were substantively updated.
- **Package inventory:** 10 Markdown files were examined excluding this compass: package `README.md`, six specs, and three Phase 1 review/edit assignment guides.
- **Promoted by structured update:** all six implemented specs informed `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md`; the campaign, coverage, quality, explorer, integrity, and recovery material also updated `.mstar/knowledge/architecture-patterns/operational-sidecars.md`.
- **Kept as iteration snapshot:** package `README.md` and all six specs remain as as-built trace material with implemented status and promotion mapping. The three assignment guides remain Phase 1 process history; they were not promoted because they add no reusable product guidance beyond the harness skills.
- **Discoverability:** `.mstar/knowledge/README.md` descriptions and source mapping were refreshed; both knowledge documents pass `mstar_compound_validate` with index and reference checks.
- **Vocabulary:** `CONCEPTS.md` now defines `evidence projection`, `audit-only recovery`, and `sequential-no-daemon`; no general programming term was added.
- **Refresh disposition:** no separate compound-refresh is required; the only overlapping active documents were updated in place and validation found no stale repository reference.

## Architect interface and gate invariants

All six slices are additive projections or wrappers over existing seams: `ManifestStore.load() -> dict[str, dict[str, Any]]` and frozen `VALID_STATUSES` are SSOT; `RunCoordinator.run_batch(rows: list[tuple[str, dict[str, Any]]]) -> RunSummary` remains the sequential execution owner; `AttemptLedger.load() -> list[dict[str, Any]]` and `RunLedger` remain append-only evidence readers; `SearchIndex` remains the FTS5 read model. No plan may create a second manifest state machine or HTTP owner.

Dependency order is strict: campaign checkpoint vocabulary → coverage denominator/reconciliation → subtitle quality and explorer projections → integrity verification and audit-only recovery semantics → concurrency evaluation. Each implementation preserves the sequential, no-daemon default and uses explicit archive-root and bounded scope inputs. Any command that writes state is explicit and atomic; reports/verifiers default read-only.

Every plan must include: a fixture-only command that exits nonzero on contract drift; a redaction assertion over serialized output; source mtime/content comparison for read-only paths; and a STOP check for missing/contradictory evidence. Rollback is deletion/restore of only the newly-created additive report/checkpoint/audit file; never rewrite manifest, attempts, ledger, or transcript artifacts. A signature, status, risk-code, path, or sidecar-schema mismatch is a drift failure requiring plan/spec revision before implementation.

## Iteration Retrospective (minimal)

- **What worked:** strict serial plan integration and immutable QC/QA ranges kept six additive slices compatible while the full suite grew from 409 to 612 tests. Explicit denominators, bounded inputs, redacted stable codes, single state ownership, and read-only-first projections prevented false-complete and credential-leak paths.
- **What was difficult:** integrity/recovery semantics required repeated hardening around confined reads, symlinks, malformed/oversized sidecars, selector expansion, cross-process locking, rollback durability, and the critical distinction between recovery evidence and requeue execution. Several review/report agents also required replacement or interruption when they failed to emit the assigned artifact; frozen branches and exact-range checks prevented that process friction from changing product state.
- **What changes next:** future iterations will state audit-only versus execution semantics in the initial spec, keep one product writer per feature worktree, preserve exact immutable review ranges, clean generated Python/uv artifacts after every test wave, and require the final report path before advancing a gate. Phase 5 fixes, if any, will be made directly on the integration branch only after current CI/review waves settle.
- **Next decision:** run authorized measured sequential corpus batches to establish fresh campaign/reconciliation/risk/disk/reclaim/ownership evidence. Do not schedule concurrency implementation unless the explicit gate returns `go` and a separate plan is approved.
