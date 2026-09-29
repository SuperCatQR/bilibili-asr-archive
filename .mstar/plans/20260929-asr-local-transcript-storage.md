---
plan_id: 20260929-asr-local-transcript-storage
iteration: iter-2026-09-queue-ssot-closeout
iteration_compass: .mstar/iterations/iter-2026-09-queue-ssot-closeout/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
status: registered
gate_decision: pass
gate_decision_reason: >-
  Prepare satisfied — compass D7 fixes the shape (a real `transcripts` row, not a bare attempt
  flip) and the two scope questions are owned. Intent source is the roadmap P2.5 entry
  `asr-local transcript storage`, itself the remaining half of D-1 "the transcript queue drains
  end to end" that `iter-2026-09-ops-readiness` recorded as unfinished when it closed.
gate_decided_at: 2026-09-29
registered_at: 2026-09-29
planned_at_sha: ed291be
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# ASR transcript write-back so `v_missing_transcript` converges

**Main worktree branch**: `main`

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Checkbox syntax.
>
> **The defect in one sentence.** The ASR path archives `srt`/`txt`/`md` artifacts to disk and
> writes a manifest row, but it **never writes a `transcripts` row**, so the store keeps
> reporting that same part as missing a transcript and `v_missing_transcript` never drains.

## Current state (evidence — re-read before dispatch)

Measured on `main` = `ed291be` (2026-09-29):

- **The write-back has no caller.** `services/queue_source.py:244` defines
  `mark_transcript_stored` and `:279` exports it; `grep -n mark_transcript_stored
  src/bili_asr/cli.py` returns **nothing**. The audio half of the same pattern **is**
  wired: `cli.py:2087` calls `qs.mark_audio_acquired(...)` right after a successful
  download, with the comment naming contract §4c/§4d. So the asymmetry is real and
  localised: audio writes back, transcript does not.
- **The ASR path is the `else` arm of `_cmd_asr`.** At `cli.py:2820-2890` the row loop
  archives via `archive.write_archive(...)`, marks the manifest row `archived`, and
  calls `_reclaim_after_archive(...)`. There is no store write between those steps.
- **Two different guards would refuse an `asr-local` write, and only one is the real gate.**
  - `TranscriptRepository.record_acquired_transcript` (`database.py:1051`) validates
    `source_kind` against **`ALLOWED_CAPTION_SOURCE_KINDS`**, and
    `models.py:572` defines that as `_ALLOWED_SOURCE_KINDS - {"asr-local"}`. This is
    the shipping refusal the roadmap means by "the caption-only writer refuses
    `source_kind='asr-local'`".
  - The **schema** does not refuse it: `schema-transcripts.sql:15-16` admits
    `asr-local` in the `CHECK`, and the content-uniqueness index at `:34-35` is
    `WHERE source_kind IN ('subtitle-ai','subtitle-cc')` — deliberately excluding
    `asr-local`, because a local transcript's identity is not a caption's identity.
    `models.py:569`'s comment says the reservation "keeps its own" rule.
  - So the schema was built for this work and the service boundary was not yet widened.
    **Widening `ALLOWED_CAPTION_SOURCE_KINDS` is therefore a service-layer change with a
    schema-level consequence** and is the plan's central judgement call — see Task 1.
- **The attempt row needs a run that exists.** `record_acquired_transcript` calls
  `self._require_acquisition_run(run_id)` (`database.py:1067`) and writes an
  `acquisition_attempts` row keyed `(run_id, video_part_id)`. `kind='asr'` is already
  legal (`models.py:31`), so the run kind is not a new vocabulary item. Whatever
  creates the run must do so before the first write of a batch.
- **`v_missing_transcript`** (`schema-transcripts.sql:228-240`) joins `video_parts` to
  `videos` and selects parts with **no** stored transcript. It is the view the ASR
  queue is built from (`_store_transcript_todo`, `cli.py:845`), so an un-converging view
  is not cosmetic: it re-serves the same work on every run.
- **The queue entry carries the identity the write needs.** `entry_for_item`
  (`queue_source.py:64`) returns `bvid`, `work_id`, `page_index`, `cid` — the entry is
  page-resolved without a live call — but **not** `video_part_id`, which is the
  repository's key. Resolving `work_id` → `video_part_id` is part of the work and its
  failure mode must be stated, not assumed.

## Goal (intent gate)

**真实目标**：本地 ASR 产出的转写进入规范化转写存储，于是 `v_missing_transcript` 对
ASR 归档过的 part 收敛，`asr` 队列不会反复把同一 part 端上来。
**成功判据**：DoD 1–5。**非目标**：字幕路的 outcome 映射（那是 `20260925-archive-db-review · R1`，
需要活凭证）、`asr-local` 的语言学身份规则、证明双路合校、改动 `srt/txt/md` 的磁盘产物。

## Task 1: Widen the transcript write boundary to admit `asr-local`

- [ ] Decide and record **how the boundary admits `asr-local` without weakening the caption
  guarantee.** `ALLOWED_CAPTION_SOURCE_KINDS` exists so that the *caption* writer cannot
  claim an `asr-local` identity. The honest options are: (a) give the repository a second,
  explicitly-named entry point for local transcripts that validates against
  `_ALLOWED_SOURCE_KINDS`; or (b) parameterize the existing call's accepted-kind set with a
  named argument so each caller states which identity it may claim. **State the choice and
  its reason in the report.** A silent widening of the shared constant is the one outcome
  this task forbids, because it removes the caption guard for every existing caller.
- [ ] Keep the schema untouched unless a real refusal forces a change. `asr-local` is already
  in the `CHECK` and already excluded from the content-uniqueness index. If you believe a
  schema change is needed, stop and report — a schema change is a different plan.
- [ ] Files: `src/bili_asr/storage/database.py`, `src/bili_asr/storage/models.py`.

## Task 2: Wire the ASR path's write-back

- [ ] After a successful archive in `_cmd_asr`'s ASR arm — the same place the audio half
  calls `mark_audio_acquired` — write the transcript row and then the attempt mark. Order
  matters: the attempt is evidence *for* a stored transcript, so a mark without the row
  would be false evidence.
- [ ] Resolve the entry's identity to `video_part_id`. The entry carries `bvid` /
  `page_index` / `cid` but not `video_part_id`. Use an existing resolver from the storage
  layer if one exists; if it does not, add the narrowest one that does and state where it
  lives. **Do not** fabricate a `video_part_id` from a page index without a store lookup —
  that is the class of assumption this repository's residual register keeps recording.
- [ ] Create or reuse the `kind='asr'` acquisition run for the batch. One invocation is one
  run scope in this codebase (`cli.py`'s own comment at the ASR setup names the shared
  `runner` per selection), so follow that shape rather than inventing a per-row run.
- [ ] Convert `runner.transcribe(...)`'s segments into `TranscriptSegmentRecord`s — the
  record's own invariants (`end_ms > start_ms >= 0`, non-empty trimmed text) must hold
  for real model output. A segment the record refuses must be answered as this part's
  failure, not an escaping error that ends the batch. State how a refused segment is
  handled.
- [ ] Keep it best-effort in the same sense as `mark_audio_acquired`: a store write failure
  must not lose an archive that already succeeded on disk. State explicitly which failures
  are swallowed and which are not.
- [ ] Files: `src/bili_asr/cli.py`, `src/bili_asr/services/queue_source.py` (if the
  write-back helper needs a sibling for the transcript half), and the storage modules
  Task 1 touched.

## Task 3: Pin the convergence with a queue-level test

- [ ] **The before/after assertion is the deliverable, not a unit assertion on the writer.**
  On a fixture store, build a part that is in `v_missing_transcript`, run the ASR write-back
  path, and assert the part **leaves** the view. Name the count that changes. A test that
  only asserts a row was inserted does not show the operator-visible effect and does not
  satisfy DoD-4.
- [ ] Add the negative control the repository's own absence-assertion rule requires: the
  fixture must be able to *reach* the producer. Assert the part is genuinely in the view
  before the write — if the fixture never queued it, "it left the view" is vacuous.
- [ ] Assert the caption guard still holds: an `asr-local` write must not be possible through
  whatever path the caption writer uses, so Task 1's widening is provably confined.
- [ ] State the `language` value written for a local transcript and pin it in the test
  (compass Q2). Do not leave it implicit in a helper.
- [ ] Files: the queue/transcript test module that already exercises
  `v_missing_transcript`; name it in the report.

## Global Constraints

- **Do not weaken the caption guarantee.** Whatever admits `asr-local` must leave the caption
  writer's accepted set exactly as strict as it is now, and a test must show that.
- **No schema change** unless a real refusal forces one, and then stop and report.
- **Do not touch the ASR engine, its checkpoint handling, or the hotword guard.** This plan
  adds a store write beside an existing archive step.
- **Do not invent a `video_part_id`.** Resolve it through the store or fail that part.
- **The disk artifacts are unchanged.** `srt`/`txt`/`md` continue to be written by
  `archive.write_archive`; the store row is additional evidence, not a replacement.
- **Do not edit `{SPECS_DIR}/asr-archive-cli.md`** (frozen). If this work needs durable
  contract text, it belongs in the plan report or a later spec revision, not a back-edit.
- New names via `naming-analyzer`.
- Test invocation from the feature worktree MUST pin the interpreter and source path:
  `PYTHONPATH=$PWD/src <repo>/bilibili-asr-archive/.venv/bin/python -m pytest <selector>`,
  and quote the resolved `bili_asr.__file__` in the report.

## Definition of Done

1. The ASR path writes a `transcripts` row with `source_kind='asr-local'` for a part it
   archived, and the row's identity fields resolve to the real stored part.
2. That part leaves `v_missing_transcript`, demonstrated before/after on a fixture store
   with the changed count named.
3. The companion attempt row is written **after** the transcript row, so no attempt claims a
   transcript that was not stored.
4. The caption writer's accepted `source_kind` set is provably unchanged — a caption path
   still cannot write `asr-local`.
5. A store write failure does not lose an archive already written to disk; the failure mode
   is stated, not implied.

## Verification

- Task-scoped RED-before / GREEN-after per SDD brief. The RED for Task 3 is the part
  sitting in `v_missing_transcript` after the write-back — a state a correct pre-fix run
  must exhibit.
- Before/after evidence recorded with both counts, produced through the pinned interpreter
  from the feature worktree.
- At the end: the affected selectors under the pinned invocation with the resolved-source
  line quoted. **Not** the full suite locally.

## Open Questions (owned, non-blocking)

| # | Question | Owner | Blocking? |
|---|---|---|---|
| Q1 | Which `language` value a locally-produced transcript records — a real code from the model's own configuration, or `.strip()`ed configured value? State the value and its source; do not default silently. | architect | No |
| Q2 | Does the write-back belong inside `queue_source`'s existing helper family (a `record_local_transcript` sibling to `mark_transcript_stored`), or in the CLI handler? Decide from the layering rules the storage module's own docstrings state, and record the call. | architect | No |

## Engine lifecycle

Registered as a plan row of `iter-2026-09-queue-ssot-closeout`. Implementation happens in the
plan's feature worktree on its own branch cut from
`iteration/iter-2026-09-queue-ssot-closeout`; QC and QA review the single merged `HEAD` of that
branch. `Done` is set only after the integration merge succeeds.
