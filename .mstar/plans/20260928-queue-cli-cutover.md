---
plan_id: 20260928-queue-cli-cutover
iteration: iter-2026-09-ops-readiness
iteration_compass: .mstar/iterations/iter-2026-09-ops-readiness/delivery-compass.md
primary_spec: .mstar/iterations/iter-2026-09-coverage-truth/specs/queue-cutover-contract.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: inline
execution_mode_reason: >-
  CORRECTED 2026-09-28. The original note claimed the host refused delegation on that session.
  That was wrong: `subagent` was available and four implementers DID run, each reporting DONE
  (they committed on their own worktrees; an early worktree check in the coordinating thread read
  "no commits yet" and wrongly concluded dispatch had failed, so the PM then re-implemented inline
  in parallel — the duplicate files later mistaken for phantom work came from those live
  implementers). The honest record: implementation was split between the dispatched implementers
  and the PM's parallel inline work on the same plans. `inline` is kept as the declared mode
  because the per-task SDD artifacts (brief/report/diff under {SDD_DIR}) are absent by
  construction — the implementer worktrees carry no `.mstar/` (gitignored) — so the SDD trail
  cannot be reconstructed from disk. The QC tri-review ran as a full N=3 read-only fan-out and is
  unaffected. For this new iteration, dispatch works and the Review chain is dispatched per spec.
status: registered
gate_decision: pass
gate_decision_reason: Prepare inherited — Deferred tables D-1..D-5 (queue-cutover) and B-D1/B-D2 (evidence-dashboard) were locked in the prior iteration's plans and re-confirmed by the ops-readiness compass D1
gate_decided_at: 2026-09-27
registered_at: 2026-09-27
planned_at_sha: main
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# Queue SSOT at the CLI surface + the operator's queue view

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Steps use checkbox (`- [ ]`) syntax.
>
> **Scope source.** This plan executes the deferred tails of two locked plans:
> `20260927-archive-db-queue-cutover` `## Deferred` (D-1..D-5) and
> `20260927-evidence-dashboard` `## Deferred` (B-D1, B-D2). The library layer
> (`MediaQueueRepository`, gap views, contract §4/§4c/§4d) is **already merged** into
> `iteration/iter-2026-09-coverage-truth` — verify it is on this iteration's integration
> branch first (it merges to `main` ahead of or with this iteration's PR; the code targets
> current `main` which carries the same storage layer after that PR).

## Current state (evidence — re-read before dispatch)

- `src/bili_asr/cli.py` is **3,763 lines on `main` as of 2026-09-28** (spot-checked);
  `download-audio` / `asr` / `pilot` still build their queues from the manifest bridge
  (`_todo_for_bvid` at `cli.py:624`, `services/manifest_derivation.py`), while
  `fetch-meta` writes `archive.db`.
- `MediaQueueRepository` (storage layer) exposes gap views + `mark_audio_acquired` /
  `mark_transcript_stored`; it is merged on
  `iteration/iter-2026-09-coverage-truth` (**not yet on `main`** as of 2026-09-28 —
  verify presence after that branch merges, per Engine lifecycle below). Contract rulings
  live in `.mstar/iterations/iter-2026-09-coverage-truth/specs/queue-cutover-contract.md`
  (§4b/§4c/§4d already written; extend, do not contradict).
- A part holding AI subtitles never reaches the audio→ASR branch today
  (roadmap P0 root cause; see knowledge `architecture-patterns/` if indexed).

## Goal (intent gate)

**真实目标**：`archive.db` 成为唯一队列真相源——operator 不需要懂 manifest 就能完成
"下载音频 → 转写" 全链，且任何时刻 `status` 能回答"下一个该做什么、为什么"。
**成功判据**：见下方 DoD（fresh-root 链路 + status 视图 + 回滚 flag）。
**非目标**：coordinator 内部重设计、manifest 文件格式的删除（文件保留，仅降级为
attempt ledger）、跨主机队列。

## Task 1 (D-1): download-audio / asr / pilot queue input cutover

- [x] Modify `cli.py`: `_todo_for_bvid` and the queue-assembly paths for `download-audio`,
  `asr`, `pilot` read pending work from `MediaQueueRepository` gap views
  (`v_missing_audio`, `v_missing_subtitle`, `v_missing_transcript`) instead of the
  manifest derivation.
- [x] Add `--queue-source {store,manifest}` (default `store`); `manifest` preserves today's
  behaviour as the rollback path. When `--queue-source manifest` is used, print one
  deprecation line to stderr.
- [x] Write-back: successful audio acquisition calls `mark_audio_acquired`; successful
  transcript storage calls `mark_transcript_stored` (idempotent per contract §4c/§4d).
- [x] A part with AI subtitles is **skipped** by download-audio (no audio needed) and the
  transcript-queue view treats it as satisfied — the exact inversion of today's root cause.
- Files: `src/bili_asr/cli.py`, `src/bili_asr/services/` (thin orchestration only — the
  repository API is frozen), `tests/test_cli_queue_source.py` (new).

## Task 2 (D-2): coordinator / scheduler / campaign stage inputs

- [x] Switch stage-input assembly in `coordinator.py` / `scheduler.py` / `campaign` path to
  the store views; manifest reads removed (manifest **writes** stay as the attempt ledger).
- [x] Manifest read removal is mechanical: delete every `derive`/`load` call site for queue
  purposes; keep `append attempt` writers untouched.
- Files: `src/bili_asr/coordinator.py`, scheduler/campaign modules, their unit tests.

## Task 3 (D-4): subtitle_ingest outcome mapping — the dead-SESSDATA false negative (high)

- [ ] Map the ingest outcome taxonomy so a dead/expired SESSDATA records  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
  `no-subtitle` + `error_code=not_found` instead of the current silent false negative
  (residual `20260925-archive-db-review · R1`, severity per the live register — this task
  closes it).
- [ ] Converge `processing_status` on the store side for the subtitle-ingest states.  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
- Files: subtitle ingest path (`sources/` + `services/`), `schema.sql` write surface,
  regression test that replays the recorded dead-SESSDATA response shape.

## Task 4 (B-D1): `status` queue view

- [x] `bili-asr status` gains the queue view: three gap groups (missing subtitles / missing
  audio / missing transcripts) in fixed order, top-20 default + `--all`, summary header with
  last-fetch time. **Contract §4: never sum the three group counts — the views are not
  disjoint.**
- [ ] `coverage` gains the provenance note: source row counts + reproduction command (B-D2).  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
- Files: `cli.py` (`_cmd_status`, `_cmd_coverage`), `README.md` section.

## Task 5 (D-3 + D-5): derive-manifest removal + docs

- [ ] Delete the `derive-manifest` command, `manifest_derivation.py`, and its tests.  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
- [ ] Assert the legacy bare-bvid regression shape is gone (regression test on a fresh root).  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
- [x] Docs: `metadata-storage.md` §Boundary rewrite, README three-step chain
  (fetch-meta → download-audio → asr), README/docs section for `--strict` + the two-class
  exit contract — worded per
  `.mstar/iterations/iter-2026-09-coverage-truth/specs/exit-code-contract.md` §1–§2
  (backlog → exit 0;
  defect/malformed → exit 1; `--strict` promotes backlog to exit 1) so this plan and
  20260928-transcript-search phrase the same contract identically. If the evidence-
  dashboard plan's B-D2 tail already landed the same section, deduplicate instead of
  duplicating (tail plan 20260928-ops-docs-and-closeout owns the final README shape).
- Files: `cli.py`, module deletion, `docs/`, README.

### Risk resolution: canonical exit-contract test module (architect, Phase 1 review 2026-09-28)

The exit-code contract lives at
`.mstar/iterations/iter-2026-09-coverage-truth/specs/exit-code-contract.md` (**iteration-scoped
draft**; the bare `specs/exit-code-contract.md` path some plan text used does not exist — this
plan's references are corrected inline here and in `20260928-transcript-search`). Its §1–§2
two-class rule (backlog → exit 0; defect → exit 1; `--strict` promotes backlog) was **shipped for
`verify`/`coverage` by the evidence-dashboard plan on that branch, not on `main`**.

**Resolution — canonical test module `tests/test_exit_contract.py`** (new, owned by this plan's
Task 5): one module pins the §1–§2/§2b class rule as CLI-boundary behaviour — exit 0 with a
`backlog:` section on backlog-only archives, exit 1 on defect-class findings, `--strict`
promoting, `gone` never exit-bearing (§2c). `20260928-transcript-search` **imports and reuses**
the shared fixtures/helpers from this module for its `search`/`search-index` exit tests instead
of re-defining the two-class vocabulary (that was the divergence risk this resolution exists to
kill). `verify`/`coverage` keep their existing per-command test files untouched — this module
adds the contract-level layer, it does not move theirs. Warehouse promotion of the contract
itself is an iteration-close (compound) decision, out of this plan's scope.

## Global Constraints

- `cli.py` is large: prefer thin delegation into `services/` over growing inline blocks;
  no behaviour change under `--queue-source manifest`.
- Every write-back honours contract §4c (storage_key identity) and §4d
  (`part_audio_objects` is the sole positive audio-evidence probe — do NOT reintroduce an
  attempts-based probe).
- Named-before-changed: run `naming-analyzer` for any new module/function/file name.
- Verification per task: scoped unit tests RED-before/GREEN-after recorded in the SDD
  report; full suite is CI's job.
- Contract home (architect, 2026-09-28): this plan's queue-source/cutover semantics extend
  `iter-2026-09-coverage-truth/specs/queue-cutover-contract.md` §5 (§4b/§4c/§4d frozen — extend
  only). Its docs-task exit-contract wording cites
  `iter-2026-09-coverage-truth/specs/exit-code-contract.md` §1–§2 by that full path.
  No new spec file is created by this plan.

## Open questions (owned, non-blocking)

| # | Question | Owner |
|---|---|---|
| MQ1 | ~~Under `--queue-source manifest`, should `status` still read the store (making the flag a queue-input-only rollback)?~~ **RULED YES by product-manager (Phase 1 review 2026-09-27):** `status` is store-native in every mode; `--queue-source` governs queue inputs (`download-audio` / `asr` / `pilot`) only. This matches the deferred dashboard plan's store-first/manifest-never ruling for the query layer — do not revisit without a new product decision. | product-manager (ruled) |

## Definition of Done

1. Fresh archive root containing only `archive.db` completes `download-audio` → `asr`;
   the store is the sole queue input on that path.
2. `--queue-source manifest` reproduces the pre-cutover behaviour (rollback works).
3. `derive-manifest` no longer exists; `pytest` suite green on the integration branch.
4. A replayed dead-SESSDATA ingest records `no-subtitle` + `error_code=not_found`.
5. `status` shows the three gap groups without summed counts; `coverage` carries the
   provenance note.

## Verification

- Task-scoped tests per SDD brief; the fresh-root acceptance script (download-audio → asr)
  is written as a pytest fixture this time (the prior plan's honest gap: "该验收脚本不存在"
  is closed here).
- Full suite + CI on the PR.

## Engine lifecycle

- Scoped sequence — this plan row is advanced by the coordinator only, one engine verb per
  transition. Precondition: `iteration/iter-2026-09-coverage-truth` merged to `main` before
  this plan's integration merge (same storage layer; serial merge order enforced by PM).
