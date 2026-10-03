---
plan_id: caption-writeback-guard
project: _default
status: draft
created_at: 2026-10-03
execution_mode: inline
plan_parallelism: serial
---
# Plan caption-writeback-guard — Hoist the caption write-back out of the archive success guard

**Main worktree branch**: `dev`（control root 驻留分支；本 plan 不切换。记录于 2026-10-03，Phase 1 lock 轮）

## Status
- **Priority**: P1
- **Effort**: XS
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/01-caption-writeback-guard
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/coordinator.py:850` — `_record_subtitle_transcript` runs inside the try opened at `:845`; the failure record is `:856-859`, `_mark_archived` is `:861`
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issue**: `I-000165`

## Problem

`_stage_archive_from_subtitle` publishes the four-artifact bundle, then runs the store write-back
**inside** the same `try` that guards the publication. The write-back is documented best-effort and
is swallowed by the callee — but only *inside* the callee's frame. Its argument
(`segments=_caption_transcript_segments(segments)`, `coordinator.py:762`) is evaluated in
`_record_subtitle_transcript`'s frame **before** `qs.record_caption_transcript`'s swallow tuple can
see it, so an argument-time raise escalates into the caller's `archive:` handler.

Result: a bundle that is already published on disk gets `archive: failed` in the attempt ledger, and
`_mark_archived` (`:861`) is skipped, so the manifest row never becomes `archived`. A rerun
republishes the same bundle, and the operator is shown a failure for a complete archive.

**Scope of this plan's claim (PM ruling, 2026-10-03, after the plan-QC tri-review).** All three QC
seats returned 0 Critical / 0 Warning and asked the PM to rule on one thing: this Problem paragraph
argues from the *operator-visible* symptom, while the Invariant commits only the *record* layer — so
the two sections are not the same width. Ruling: this plan is **scoped to the record half, and that
half is closed** — after the fix a published bundle is recorded `archived` with `archive: ok`,
convergent on rerun, instead of `archive: failed` with the row stuck non-terminal. What remains open,
deliberately and out of this plan's declared scope, is the *operator* half: for the reachable cue
class the write-back still raises at the call site, so the CLI reports `run: <work_id>: failed
(<codes>)` + `exit 1` on a row that is durably `archived`, and that part never gets its `transcripts`
row and stays in the gap views. Neither half of that is silent: both are registered as tracked
residuals — `I-000192` (no call-site swallow boundary; the CLI success signal is the part that is
missing) and `I-000193` (terminal row + failed best-effort write-back is unrepairable and
unattributed). Unifying the swallow boundary, `_caption_transcript_segments`' validation and
`_record_subtitle_transcript`'s body is **audit plan 015's** surface and stays out of scope here —
the plan's STOP conditions already say so. Read this plan's Done as "the record tells the truth",
**not** as "the operator stops seeing a failure".

The ASR sibling deliberately places its write-back **outside** the guard (`:990`, after
`_mark_archived`) and documents exactly why.

### Reachability (verified, not hypothesised)

The pre-fix reproduction (`python3` with `PYTHONPATH=bilibili-asr-archive/src`):

| cue shape | `segments_to_srt` (write path) | `_caption_transcript_segments` (write-back) |
|---|---|---|
| `{"start":"abc"}` | raises `ValueError` | raises `ValueError` |
| `{"start":None}` | raises `TypeError` | raises `TypeError` |
| `{"start":1.0,"end":2.0,"text":""}` | **OK** | **raises `ValueError`** |
| `{"text":"   "}` (whitespace only) | **OK** | **raises `ValueError`** |
| `{"start":5.0,"end":1.0}` | **OK** | **raises `ValueError`** |
| `{"start":-1.0,"end":2.0}` | **OK** | **raises `ValueError`** |

Rows 3–6 are the reachable class: `write_archive` succeeds (so the bundle lands), then the
write-back raises on `TranscriptSegmentRecord` validation. Ordinary caption data produces these
shapes — e.g. an empty or whitespace-only cue and an inverted time pair.

**目标与非目标（一行）**：目标是「已发布即记为已发布」——一个已落盘的 bundle 其 `archive` 记录
是 `ok`、manifest 行是 `archived`；非目标是**不改** `_record_subtitle_transcript` 的吞错面、不改
`_caption_transcript_segments` 的校验、也不修 cue 形状本身（写出仍容忍的形状不因本 plan 变严）。
代价限定在记录层：一个完好的归档不得被 store 侧的问题报成失败。

## Current state (excerpts — verify against live code before editing)

`bilibili-asr-archive/src/bili_asr/coordinator.py:843-862`:

```python
        try:
            if not archive_module.archive_bundle_complete(
                self.artifact_roots.write_base, paths
            ):
                raise OSError("archive bundle incomplete")
            self._record_subtitle_transcript(entry=entry, raw=raw, segments=segments)
            self._record(
                "archive", work_id, "ok",
                artifact_paths=sorted(paths.values()), started_at=started,
            )
        except Exception as exc:
            self._record(
                "archive", work_id, "failed",
                error_code=_safe_error_code(exc), started_at=started,
            )
            raise
        self._mark_archived(key, entry, paths)
        result.ok = True
        result.final_status = "archived"
```

The sibling that gets it right, `coordinator.py:984-989`:

```python
        self._mark_archived(key, current, paths)
        # Store write-back (plan r14-routes-writeback): the locally-produced
        # transcript owes a ``transcripts`` row taking the part out of
        # ``v_missing_transcript``.  Best-effort: the archive already
        # succeeded on disk, so a store failure must not disturb the row's
        # archived outcome.
        self._record_asr_transcript(current, segments)
```

## Invariant restored (target state, not the line moved)

**A published bundle is recorded as published.** The durable half is the manifest row reaching
`status: archived`; the operator-visible half is the attempt ledger's `archive` record staying `ok`.
The change makes the caption path structurally identical to the ASR sibling
(`coordinator.py:984-989`) — both put the store write-back **after** publication and after
`_mark_archived`, because store evidence must never be able to revise an on-disk outcome. What moves
is one call site; what is restored is the rule that publication is the terminal fact for the row.
Any future third write-back path must copy the same shape, or this defect returns with a new caller.

## Contracts to preserve (name these in the task report)

- **The attempt-ledger record is the operator's only per-row truth.** `_record("archive", ...)` with
  `outcome: "ok"` + `artifact_paths` is what a reader outside the process uses to decide whether the
  bundle exists; the manifest row's `status` is the resumable half. Both are asserted by AC 1 — do not
  replace either with a mock-call-order assertion (the plan's Done criteria already forbid it).
- **The best-effort write-back contract itself is unchanged.** `_record_subtitle_transcript`
  (`coordinator.py`) and `queue_source.record_caption_transcript` keep their own swallow tuple; the
  repair moves the *call site*, and the callee's documented best-effort intent is what the ASR sibling
  (`coordinator.py:984-989` region) demonstrates. Do not "fix" it by widening or narrowing that tuple
  — that is a different plan's surface (`I-000176` / audit 015 covers page identity, not this).
- **`write_archive`'s tolerance for degenerate cues stays as it is.** The publish path deliberately
  accepts empty-text / whitespace-only / inverted-time cues (see the reachability table). This plan
  must not make the writer stricter; the class is closed by not letting the write-back's stricter
  validator reach the `archive:` handler.
- **The ASR sibling is the reference, not a co-edit target.** Task 1 copies its shape; it does not
  modify it. If the sibling also needs to change, STOP (see below) — that would be a second defect.

## Conventions to follow

- Match the ASR sibling exactly: write-back after `_mark_archived`, with the same comment shape
  explaining that store evidence must not disturb the archive outcome.
- Keep `_record_subtitle_transcript` itself unchanged — it already returns early when the row names
  no subtitle language or the store cannot open.

## Tasks

### Task 1 — Move the call site (Effort: XS)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/coordinator.py` (`_stage_archive_from_subtitle`, ~`:843-862`)

**Change.** Remove the `self._record_subtitle_transcript(...)` line from inside the `try`, and place
it after `self._mark_archived(key, entry, paths)` (and after the `archive: ok` record stays where it
is), mirroring `_stage_asr_archive`.

**Interfaces (verbatim, unchanged):**

```python
def _record_subtitle_transcript(
    self,
    *,
    entry: dict[str, Any],
    raw: dict[str, Any],
    segments: list[dict[str, Any]],
) -> None: ...
```

**In scope**: `bilibili-asr-archive/src/bili_asr/coordinator.py`,
`bilibili-asr-archive/tests/test_coordinator.py` (or the file that already exercises
`_stage_archive_from_subtitle`; confirm before editing).

**Out of scope**: `_record_subtitle_transcript`'s body, `_caption_transcript_segments`,
`queue_source.record_caption_transcript`, and the ASR sibling — all already correct.

### Task 2 — Pin the behaviour (Effort: XS, same round)

Add a regression test that drives the caption archive path with a cue shape from the reachable class
(an empty-text cue is the cheapest) and asserts:
- the row's attempt ledger records `archive: ok`;
- the manifest row's `status` is `archived`.

A second assertion for the best-effort intent: the store write-back may create no transcript row,
and that must not change either of the above.

## STOP conditions

- If `_stage_archive_from_subtitle` no longer matches the excerpt above (a merge moved the write-back
  or the guard), STOP — re-read before editing; another plan may have landed.
- If the write-back turns out to be required **before** the `archive: ok` record by some reader
  (grep `_record("archive"` consumers first), STOP and report — that would make this a design change,
  not a move.
- If the failing cue shape turns out to be rejected earlier by `write_archive` (the bundle never
  publishes), STOP — the reported reachability would be wrong and the plan needs a new trigger.
- **Contract-breaking (irreversible) — STOP, do not implement around it:**
  - If the fix is proposed as "wrap the write-back in another `try/except`" **inside** the existing
    `try` (rather than hoisting the call site out of it), STOP and report to PM. That hides the
    failure class behind a second swallow instead of restoring the invariant (a published bundle is
    recorded as published); it also leaves `_mark_archived` reachable only when the write-back
    happens to succeed, which is the defect.
  - If the fix requires changing `_record_subtitle_transcript`'s signature, the
    `_caption_transcript_segments` validation, or `record_caption_transcript`'s swallow tuple, STOP —
    that is audit plan 015's / a separate plan's surface, and the compass Non-Goals record that
    `(bvid, page_index)` semantics are deliberately not in this iteration.
  - If making the caption path correct requires the ASR sibling to change too (i.e. it is also
    wrong), STOP and report — the plan's premise (the sibling is already correct) would be false and
    the blast radius is then process-wide, not one call site.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/coordinator.py
git log --oneline 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/coordinator.py
sed -n '835,870p;975,995p' bilibili-asr-archive/src/bili_asr/coordinator.py
```

Re-read before editing when any of these is non-empty:

1. `coordinator.py` changed — compare **both** bodies (caption at ~`:843-862`, ASR sibling at
   ~`:984-989`) against the excerpts; the fix is defined as "make the first match the second".
2. The `sed` excerpt no longer shows the write-back inside the caption `try` — either the defect
   landed fixed by another plan, or the excerpt drifted. Distinguish before editing; do not re-apply.
3. The ASR sibling moved its write-back **inside** its `try` — then both paths are wrong and this
   plan's premise (a correct sibling to copy) is gone; STOP and report.
4. Another plan in this iteration touched `coordinator.py` (`git log --oneline`): the other three
   plans are `manifest.py` / `queue_source.py` scoped, so a `coordinator.py` commit here means
   unrecorded interference — read it before proceeding.

## Done criteria

- [ ] `_record_subtitle_transcript` is called after `_mark_archived`, outside the archive `try`
- [ ] **Observable, outside the process that implements it** — after one caption archive call on a
      reachable cue shape, `{archive_root}/coordinator/attempts.jsonl` holds that `work_id`'s
      `archive` record with `"outcome": "ok"` (the record whose `error_code` is `null` and whose
      `artifact_paths` lists the four published artifacts), **and** the manifest row for that key
      reads `status: archived`. A reader that only opens those files must be able to check both;
      asserting a mock's call order is not sufficient.
      **Drift corrected 2026-10-03 (implementer finding, verified in the worktree):** this criterion
      originally named `manifest/manifest.jsonl` for the second observable, which is wrong about the
      store's own lifecycle — a run's write lands in `manifest/manifest.journal.jsonl`; the snapshot
      `manifest.jsonl` is only materialized by a fold, which happens (a) in `save()` / `compact()`
      (**no product caller of either**), or (b) inside `upsert` via `_maybe_compact_locked`
      (`manifest.py:462` → `:295-315`) once **both** hold — that store instance has appended
      `_JOURNAL_COMPACT_THRESHOLD` (256) records since its last fold (`_appends_since_compact`,
      init `:128`, increment `:291`; a per-instance **counter**, not a row count) **and** the
      journal's bytes are at least `_JOURNAL_WRAP_BYTES_FACTOR` (2)× the snapshot's (`:54`,
      `:308-312`). It is a conjunction, not an alternative. So a short run never writes `manifest.jsonl`;
      the row is observable in the journal immediately, and in the snapshot only after a fold.
      **Correction 2026-10-03 (L2 review R1):** the first version of this note claimed only
      `save()`/`compact()` could fold, i.e. that `manifest.jsonl` was unreachable from a run at all.
      That overreached — `upsert`'s threshold fold is reachable without either, and the reviewer
      reproduced it at append #256. The criterion above is unaffected (accept either observation
      point), but do not repeat the absolute form. Accept **either** observation
      point as satisfying this criterion (the journal is where a run's write lands), and do not read
      its absence from `manifest.jsonl` as a regression from this plan. That store-lifecycle gap is
      pre-existing (`I-000167`/`I-000170` territory, plan `journal-compaction-lifecycle`) and this
      plan neither creates nor closes it.
- [ ] The same call may create **no** `transcripts` row, and neither of the two observables above
      changes because of that (best-effort intent pinned)
- [ ] New regression test fails before the change and passes after (record the red/green pair)
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_coordinator.py -k "subtitle and archive"` passes; record the command and result
- [ ] `git diff --check -- bilibili-asr-archive/src/bili_asr/coordinator.py` exits 0
- [ ] No files outside the in-scope list are modified (`git status --short`)

## Verification notes

Run the focused test from the worktree root with the absolute source path (the repo's own
`{KNOWLEDGE_DIR}/testing-patterns/venv-editable-pth-hides-tree-under-test.md` records that a venv
editable install resolves `bili_asr` to the control checkout):

```
cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_coordinator.py -k "subtitle"
```

Do not run the full suite (CI-owned); this change needs only its own regression plus the touched
tests.

## QA Gate Summary

**`accepted with open issues` — 2026-10-03** (`qa-engineer`, `QA gate: mandatory` / `QA mode: acceptance-only`;
report `{SDD_DIR}/caption-writeback-guard/qa-acceptance.md`, range `1e756df..2b34bba`).

All 7 in-scope Done criteria pass at range head `2b34bba`: the call site sits after `_mark_archived` and outside
the archive guard (`coordinator.py:860`/`:866`, AST-verified); the regression test asserts both observables from
raw JSONL on disk (`tests/test_coordinator.py:1797-1834`) with a recorded RED/GREEN pair; the focused selector
(`-k "subtitle and archive"`) collects exactly that test and passes (`1 passed, 44 deselected`, exit 0,
re-witnessed at range head); `git diff --check` exit 0; no file outside the two in-scope paths changed.
The operator half (CLI failure signal + missing `transcripts` row / gap views) is **not claimed** by this plan
per the ruling at `plan:38-53` and stays open as `I-000192`/`I-000193`; `I-000191`/`I-000194` are correctly
out of scope. `I-000165`'s acceptance is record-half-only and is evidenced, its closure is PM-owned.
Open residuals: `I-000191` (low), `I-000192` (low), `I-000193` (medium), `I-000194` (medium).

### Plan QC (tri-review, N=3)

`Approve with residuals` — seats `qc-specialist` / `qc-specialist-2` / `qc-specialist-3` each returned
**0 Critical / 0 Warning**; consolidated in `{SDD_DIR}/caption-writeback-guard/review/qc-consolidated.md`
(seat reports `qc1.md`–`qc3.md`, all passing `mstar qc validate-report`). All three seats confirmed the move
restores the invariant with no new manifest/bundle inconsistency. Both Suggestion-level findings were closed by
fix round 2 (`2b34bba`); the residual class findings are captured above.

### L2 task review

`Approved`, 1 Minor (comment-only, closed by fix round 1 `48f3c7c`) — `{SDD_DIR}/caption-writeback-guard/task-1-review.md`.

## Engine lifecycle ownership

No engine lifecycle ownership is claimed by this plan: it is a source-only repair. It is advanced by
PM through the normal per-plan flow (registered row → `InProgress` → QC → QA → `Done`); no delivery
tail is promised here.
