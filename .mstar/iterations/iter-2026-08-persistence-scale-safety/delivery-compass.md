---
iteration_id: iter-2026-08-persistence-scale-safety
start_date: 2026-08-31
status: locked
iteration_base_branch: iteration/iter-2026-08-corpus-coverage
target_branch: main
plans:
  - 20260831-persistence-scale-safety
  - 20260831-asr-reproducibility
---

# iter-2026-08-persistence-scale-safety Delivery Compass

## Direction lock (autonomous)

**Direction lock mode:** `autonomous`
**Locked direction:** make the existing sequential archive trustworthy at larger local scale by hardening persistence/read projections first and making local SenseVoice runs reproducible, while keeping live production and concurrency evidence-gated.

**Scale budget:** `M` — exactly two business delivery plans. The product review confirms that persistence/read-scale safety and reproducible local ASR are separately valuable, code-first outcomes; neither is a process-only plan. Review/edit, SDD task reviews, QC/QA, compound, close, PR, merge-ready, compass/status/snapshot maintenance, and branch/worktree process are mandatory harness gates and do not consume the two-plan budget.

**Rationale:**

1. The completed coverage compass records that the next operational decision is measured sequential corpus production, but a current code review found that manifest and ledger writes are read-all/rewrite-all, readers stop at 10,000 records, archive publication is not bundle-atomic, and `audio_path` has no shared confinement invariant. Evidence: `.mstar/plans/20260831-persistence-scale-safety.md`, `bilibili-asr-archive/src/bili_asr/manifest.py`, `coordinator.py`, `run_ledger.py`, `coverage_report.py`, `integrity.py`, and `archive.py`.
2. The ASR boundary currently constructs `AutoModel` inside every `transcribe` call, enables `trust_remote_code`, accepts an environment-selected model without revision/provenance, and has no model-lifecycle characterization. Evidence: `bilibili-asr-archive/src/bili_asr/asr.py:86-122` and the existing `asr` optional dependency in `pyproject.toml`.
3. These two code-first slices reduce the risk of the next authorized sequential campaign without claiming that a bounded campaign is the full corpus and without enabling workers or daemons.

## Scope

- Locked manifest/ledger persistence with durable atomic replacement, single-writer protection, append/replay/compaction behavior, and failure-injection tests.
- Shared streaming manifest/attempt projections with distinct trusted-local and bounded hostile-input policies.
- Atomic transcript bundle publication and one confined `audio_path` invariant across lookup, ASR, and reclaim.
- Reusable ASR model lifecycle, explicit local/offline configuration, provenance without secrets/media/model bytes, and fixture-only reproducibility/benchmark contracts.

## Plans

| `20260831-persistence-scale-safety` | Persistence scale and archive safety | Todo | first serial business plan; coordinator/persistence seam must be stable before ASR plan | plan + [`specs/persistence-scale-safety.md`](specs/persistence-scale-safety.md) |
| `20260831-asr-reproducibility` | Reproducible local ASR execution | Todo | second serial business plan; starts only after persistence plan integration seam is stable | plan + [`specs/asr-reproducibility.md`](specs/asr-reproducibility.md) |

## Specify / clarify decisions

- **True problem:** sequential archive state is not durable or scalable enough for restart-safe production evidence, and ASR behavior is not reproducible enough to compare runs or diagnose local failures.
- **Success criteria:** both plans pass fixture-only tests and mandatory QA; valid synthetic archives above 10,000 rows remain authoritative in trusted-local mode; bounded inspection remains fail-closed; ASR model construction is reusable/injectable and provenance is explicit and redacted; no existing status/risk or credential contract changes.
- **State SSOT:** `work_id`-keyed manifest JSONL remains the only item-state SSOT. Any journal history, projections, caches, or provenance are derived or storage mechanics and cannot become a second state machine.
- **Reader boundary:** trusted-local is explicit for a local operator-controlled archive; bounded-input is explicit for hostile/untrusted inspection. Removing a total-record ceiling from trusted-local must not remove per-record validation or symlink/path protections.
- **Execution boundary:** production remains `sequential-no-daemon`; the archive-root writer lock rejects overlap but does not authorize workers, services, startup tasks, or concurrent manifest writers.
- **ASR boundary:** tests fake the FunASR import and model; no test downloads a model, opens Bilibili traffic, handles credentials, or stores audio/transcript payloads.
- **Roadmap boundary:** measured WSL campaign execution is next after this iteration and an operator-approved fresh denominator; conditional concurrency remains a separate plan only after the existing evidence gate returns `go`.

## Milestones

| Milestone | Target date | Status |
|---|---|---|
| Autonomous direction lock + initial package | 2026-08-31 | completed |
| Review & Edit chain + Prepare lock | 2026-08-31 | completed |
| Persistence plan implementation/QC/QA | 2026-09-02 | pending |
| ASR plan implementation/QC/QA | 2026-09-03 | pending |
| Iteration close + compound | 2026-09-04 | pending |
| PR merge-ready | 2026-09-05 | pending |

## Acceptance Criteria

1. Both business plans complete `specify → clarify → plan(locked) → tasks → implement → L2 review → mandatory QC tri-review → mandatory QA → serial integration merge` with no open fixable residual.
2. Manifest and ledger updates are durable, lock-protected, restart-safe, and linear append/projection operations; synthetic 10,001-row/40,001-attempt trusted-local inspection is authoritative.
3. Bounded hostile-input inspection retains explicit caps, redacted stable diagnostics, symlink rejection, malformed-line handling, and non-authoritative outcomes.
4. Transcript bundle publication cannot expose an incomplete terminal artifact set, and an escaped or symlinked `audio_path` never reaches ASR or reclaim.
5. Local ASR execution has an injectable/reusable model lifecycle, explicit model/config provenance, deterministic normalization fixtures, and no secrets, model bytes, media, or network in evidence.
6. Existing `VALID_STATUSES`, `classify_risk`, `work_id` identity, subtitle-first behavior, mixed-outcome exit precedence, and `sequential-no-daemon` remain unchanged.
7. Phase 3 close, compound/index work, PR delivery, and Phase 5 exit all complete; final Done means the Phase 5 exit checklist is entirely `[x]`.

## Non-Goals

- Real Bilibili traffic, credentials, WSL campaign execution, or a full-visible-corpus claim.
- Worker pools, daemon/service deployment, automatic startup, distributed locks, or concurrency enablement.
- Manifest schema/status-taxonomy migration, SQLite replacement, public API/service, GUI, or media redistribution.
- ASR semantic quality claims, diarization, editorial correction, LLM cleanup, or replacing SenseVoice.
- Committing generated process state, raw QC/QA bundles, credentials, signed URLs, model/media bytes, or raw exceptions.

## Roadmap Position

- **Current iteration (`iter-2026-08-persistence-scale-safety`):** deliver persistence/read-scale safety and reproducible local ASR execution on top of the latest coverage integration line; current status is `active` until Phase 3 writes `completed`.
- **Next iteration:** measured sequential corpus production, owner `project-manager` + operator; trigger is this iteration's Phase 5 exit, a valid local login, explicit WSL/archive/storage/rate boundaries, and a fresh denominator; exit is repeated reconciled evidence without full-corpus overclaim.
- **Later iteration:** conditional concurrency implementation, owner `architect` + `ops-engineer`; trigger is every threshold in the existing concurrency gate plus a separate approved plan; exit preserves single-writer fallback and all current evidence contracts.
- **Final target:** complete M0/M1/M3 visible-corpus enumeration, subtitle coverage measurement, archived/missing inventory, and searchable M4 transcripts with bounded resumable evidence and no unauthorized redistribution.

## Delivery Branch Policy

| Field | Value |
|---|---|
| `iteration_base_branch` | `iteration/iter-2026-08-corpus-coverage` |
| `spec_integration_branch` | `iteration/iter-2026-08-persistence-scale-safety` |
| `target_branch` | `main` |
| `control_worktree_path` | `/root/workspace/bilibili-asr-archive/.worktrees/iter-2026-08-corpus-coverage-control` |
| `plan_parallelism` | `serial` |
| `worktree_mode` | `control-plus-feature` |
| `push_policy` | `no-pr` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Journal replay changes legacy duplicate semantics | Medium | High | Preserve old compact snapshots, fixture legacy files, specify latest-row projection and stop on schema/status drift. |
| Lock behavior differs on native Windows and WSL | Medium | High | Standard-library platform branches, subprocess tests per available platform, stable busy diagnostic, no process-local-only lock. |
| Trusted reader weakens hostile-input protection | Medium | High | Separate `ReaderPolicy` modes, preserve per-record validation/path checks, bounded-mode regression fixtures. |
| ASR provenance leaks local paths or credentials | Low | High | Record only redacted model/config identifiers and dependency revision; forbidden-marker tests over every serialized value. |
| Phase 5 PR checks are unavailable | Medium | Medium | Keep push cadence evidence explicit; use repository/host check fallback and do not claim merge-ready without required checks settled. |

## Iteration Package

> Start-chain drafts stay in this package. No new `{KNOWLEDGE_DIR}` documents may be created before iteration-close compound.

| Path | Purpose |
|---|---|
| `delivery-compass.md` | Direction lock, scope, plans, gates, roadmap, and close placeholders |
| `README.md` | Package index and promotion trace |
| `specs/persistence-scale-safety.md` | Durable storage/read contract for this iteration |
| `specs/asr-reproducibility.md` | Durable local ASR lifecycle/provenance contract |
| `guides/` | Review/edit assignment snapshots when explicitly requested |

## Quality Gate Summary

> Filled at iteration-close. Per-plan reports stay under their SDD review directories; residual SSOT stays in the project register.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---|---|---|---|---|
| `20260831-persistence-scale-safety` | pending | mandatory | none registered | `.mstar/plans/20260831-persistence-scale-safety.md#review-gate-summary` |
| `20260831-asr-reproducibility` | pending | mandatory | none registered | `.mstar/plans/20260831-asr-reproducibility.md#review-gate-summary` |

## Compound Round Summary

> Filled at iteration-close after package inventory, overlap checks, structured promotion, and knowledge index validation.

- 结晶文档数：pending
- 新增 `CONCEPTS.md` 条目：pending
- 触发 compound-refresh：pending

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- 做得好的：pending
- 可改进的：pending
- 下迭代建议：pending
