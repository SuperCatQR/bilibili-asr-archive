---
iteration_id: iter-2026-09-queue-ssot-closeout
start_date: 2026-09-29
status: active
iteration_base_branch: main
target_branch: main
spec_integration_branch: iteration/iter-2026-09-queue-ssot-closeout
enforcement: soft
plans:
  - 20260929-derive-manifest-retirement
  - 20260929-asr-local-transcript-storage
---

# iter-2026-09-queue-ssot-closeout Delivery Compass

## Scope

Two locked outcomes, both "finish what the last four iterations started and left half-done".
This iteration is deliberately **small and serial-first**: the previous four iterations each
landed the store layer of a cutover and deferred its tail, and the tails are now the densest
concentration of open work in the repository.

1. **The manifest stops being a queue input at all.** `derive-manifest` is still a shipped
   subcommand and `services/manifest_derivation.py` still exists, even though
   `download-audio` / `asr` / `pilot` / `run` have all defaulted to `--queue-source store`
   since `iter-2026-09-ops-readiness`. The command is a trap: it writes `needs_audio` rows
   that the default queue path no longer reads, so an operator who runs it sees work appear
   and nothing consume it. This plan retires the command, deletes the module, and proves by
   test that no queue decision reads the manifest any more.

2. **An ASR-produced transcript reaches the store, so `v_missing_transcript` converges.**
   `mark_transcript_stored` is wired and tested but **has no caller in `cli.py`** — the ASR
   path writes artifact files only. The store therefore keeps reporting every ASR-archived
   part as missing a transcript, which is the standing defect behind the `asr-local` half of
   `v_missing_transcript` never draining. This plan gives the ASR path its write-back so the
   queue the operator reads agrees with the archive on disk.

**Boundary a reader can use from this paragraph alone.** Plan A owns the **manifest-as-queue
retirement** (command, module, its readers, its tests). Plan B owns the **ASR→store
transcript write-back** (the write site, the `source_kind` handling, the view converging).
They are disjoint: plan A removes a queue producer, plan B adds a queue consumer's write-back.
Neither plan edits the other's surface. Both share one target — `bilibili-asr-archive/README.md`'s
CLI reference — and **only plan A writes it**.

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Iteration id is `iter-2026-09-queue-ssot-closeout`; base `main`, target `main`, integration `iteration/iter-2026-09-queue-ssot-closeout`. | Follows the repository's own naming shape for a tail-closing iteration; both anchors are the recorded default in the root `AGENTS.md` branch policy. | user instruction (2026-09-29) + `AGENTS.md` |
| D2 | Scope is exactly the two roadmap P0/P2.5 tails named in `## Scope`; nothing is added. | The roadmap's own P0 block (archive.db as sole queue input) is delivered except these two tails; both are "the last named step" of a cutover the previous iterations declared done. | roadmap `_default` P0 / P2.5 |
| D3 | **Serial-first.** Both plans are implemented one after the other, not concurrently. | The two plans touch adjacent CLI surface (`cli.py` command table) and plan A deletes a module plan B's tests may reach through shared fixtures. Serial is the honest default and removes a merge-conflict class for zero throughput cost at this size. | user instruction (2026-09-29) — "先串行跑通一轮再放开" |
| D4 | `Execution mode: sdd` for both plans. | Multi-task plans; the harness default, and dispatch is verified working in this session (smoke-tested this turn, not inferred). | `mstar-harness-core` + this session |
| D5 | Plan A **retires** `derive-manifest` rather than leaving it as a deprecated alias. | `mstar-harness-core` § 核心研发守则: do not preserve backward compatibility; remove obsolete paths instead of adding compatibility layers. `--queue-source manifest` stays as the documented rollback for the *read* path, which is a different concern and is not this plan's target. | `mstar-harness-core` |
| D6 | Plan A keeps `duration_s_from_ms` alive if it has consumers outside the retirement set. | Verified live at drafting: `services/transcript_projection.py:47` and `cli.py:1691` both import it, and the published-projection path is **not** what this plan retires. Deleting the module wholesale would break a shipping reader — the removal set is commands + queue-production symbols, decided by consumer, not by filename. | live-code read 2026-09-29 |
| D7 | Plan B writes a real `transcripts` row with `source_kind='asr-local'` rather than only flipping an attempt row. | The frozen view `v_missing_transcript` converges on a stored transcript; marking an attempt without a row would leave the view unchanged and make the plan's own DoD unreachable. The schema already reserves `asr-local` (`schema-transcripts.sql:15-16`) and its content-uniqueness index explicitly excludes that kind, so the reservation was left for exactly this work. | `schema-transcripts.sql` + roadmap P2.5 |
| D8 | Both plans run `QA gate: mandatory` / `qa_mode: targeted`. | The repository's own convention for product-code plans; both change CLI-observable behaviour with a test surface. | recent plans (20260928-*) |
| D9 | This iteration does **not** reopen the parked `iter-2026-09-transcript-editorial-stages` gates. | Those gates are real and documented in `HANDOFF.md` §3, but they belong to a different lifecycle with its own branch, and its iteration package was deleted from disk by operator decision on 2026-09-25. Folding them in would silently re-open a parked iteration through the back door. | `HANDOFF.md` §3/§9 |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| Q1 | Does `duration_s_from_ms` (and any other symbol in `manifest_derivation.py`) keep a home after the module is deleted — moved to the consuming module, or re-exported? Plan A decides this from the live import graph at implementation time and records the call in its report. | architect | No |
| Q2 | Does the `asr-local` transcript row need a `language` value, and if so what is honest for a single-language local model? Plan B owns this and must state the value it writes rather than leaving it implicit. | architect | No |

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260929-derive-manifest-retirement | Retire `derive-manifest` and delete the manifest queue module | Todo | Plan A — queue producer removal |
| 20260929-asr-local-transcript-storage | ASR transcript write-back so `v_missing_transcript` converges | Todo | Plan B — queue consumer write-back |

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze | 2026-09-29 | pending |
| Dev complete | 2026-09-29 | pending |
| QC complete | 2026-09-29 | pending |
| Iteration close | 2026-09-29 | pending |

## Acceptance Criteria

1. `bili-asr derive-manifest` no longer exists as a command: invoking it is an argparse
   `invalid choice` error, and no `src/bili_asr/` module named for manifest derivation is
   importable.
2. No queue decision reads the manifest: a test asserts the queue-building path is
   manifest-free for `download-audio` / `asr` / `pilot` / `run` under the default source.
3. `--queue-source {store,manifest}` still exists and its `manifest` value still selects the
   documented rollback read path — proof that the retirement removed a producer, not the
   operator's escape hatch.
4. Running the ASR path over a part with no captions results in a `transcripts` row with
   `source_kind='asr-local'`, and that part leaves `v_missing_transcript`.
5. The store's queue view before/after the plan B write-back is recorded as before/after
   evidence on a fixture store — the count that changes is named, not asserted in prose.
6. Full validation at the end: `mstar status validate` clean, `mstar worktree check` green
   for both plan rows while they are active, and both plans' QC tri + QA gate complete.

## Non-Goals

- **Reopening the parked editorial-stages iteration** — different lifecycle, package deleted
  by operator decision; see D9.
- **Deleting the manifest file format or its readers** — the manifest stays as an attempt
  ledger and `--queue-source manifest` stays as the rollback; only the *queue producer* goes.
- **The `uv.lock` / torch regeneration** (`iter-2026-09-qwen3-asr-closeout · R7`) — needs a
  resolution against `repo.radeon.com` that this host cannot verify; touching it blind is the
  documented destructive outcome.
- **The dead-SESSDATA outcome mapping** (`20260925-archive-db-review · R1`) — a live-corpus
  credential question, not a code change; it needs a session that can reach the network.
- **Any product-code change to the published-projection path** — plan A's D6 keeps it intact.
- **Cross-plan parallel implement** — see D3; this iteration is the serial first round.

## Roadmap Position

- **Current iteration（iter-2026-09-queue-ssot-closeout）**：close the two named tails of the
  archive.db queue SSOT cutover — the manifest stops being a queue producer, and the ASR path
  starts writing the transcript row the store's queue view is waiting for.
- **Next iteration**：the roadmap's P0 "coverage/dashboard" remainder and the P2 correctness
  block (interruption journal, large-input protection, artifact-root path normalisation),
  trigger = this iteration's merge to `main`, owner = PM.
- **最终目标**：为 UP 主 23191782 的全量稿件建立本机可复现、可增量、可校对的字幕归档，
  且操作者能在任何时刻从 `status` 回答"下一个该做什么、为什么"。

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-09-queue-ssot-closeout` |
| `target_branch` | `main` |
| `Main worktree branch` | `main` (recorded before lifecycle writes; never switched) |

Mirror of the frontmatter; kept in sync with workflow snapshot
`{WORKFLOW_DIR}/iter-2026-09-queue-ssot-closeout/snapshot.json` `branch` anchors.

## Roadmap Position (long form)

The repository's roadmap `_default` ranks the archive.db queue SSOT cutover as P0 because it is
the single change that removes the most residual findings per unit of work. Four iterations have
now landed its store layer (`iter-2026-09-queue-bridge`, `iter-2026-09-coverage-truth`,
`iter-2026-09-ops-readiness`, and the `--queue-source` flag in `20260928-queue-cli-cutover`).
What remains is not new design: it is the removal of the old producer and the completion of the
last consumer's write-back. This iteration finishes both so the queue has exactly one authority.
