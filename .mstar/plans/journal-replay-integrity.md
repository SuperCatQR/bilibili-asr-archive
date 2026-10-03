---
plan_id: journal-replay-integrity
project: _default
status: draft
created_at: 2026-10-03
execution_mode: inline
plan_parallelism: serial
---
# Plan journal-replay-integrity — Split the manifest journal replay on `"\n"`, not `str.splitlines()`

**Main worktree branch**: `dev`（control root 驻留分支；本 plan 不切换。记录于 2026-10-03，Phase 1 lock 轮）

## Status
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/02-manifest-journal-splitlines
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/manifest.py:253` — `_replay_latest` iterates `raw.decode(...).splitlines()` with `except ValueError:` at `:259` and the `break` at `:262`
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issue**: `I-000164`

## Problem

`ManifestStore._replay_latest` reads the append journal and splits it with
`str.splitlines()`. Python's `str.splitlines()` breaks on U+2028 (LINE SEPARATOR),
U+2029 (PARAGRAPH SEPARATOR) and U+0085 (NEL) in addition to `\n` — and this repo's writer
emits those code points **raw**, because `_json_line` and `_snapshot_bytes` both serialise with
`ensure_ascii=False`.

So one journaled row whose text carries such a character splits into fragments; the first fragment
fails `validate_manifest_record`, and the `except ValueError: break` (intended for a torn tail)
**stops the replay entirely**. Every journaled row appended after that byte offset disappears from
`_entries`, from `load()` and from `get()` — for the lifetime of the store instance.

The consequence is not only a stale read: `save()`, `compact()`, `migrate_legacy_rows()` and
`_maybe_compact_locked` all write `_replace_snapshot(...)` from that same truncated view, so the rows
after the break are **durably deleted** from the ledger that is the resumable SSOT. Meanwhile the
sibling readers (`sidecar_projection.iter_jsonl_records` and `project_manifest_records`, used by
`verify`/`coverage`/`status`) replay by newline and still see the rows — the two readers of one
ledger disagree, and the one that writes is the one that is wrong.

**Reproduced** (2-row payload, second row is the one that must survive):

```
splitlines() rows replayed: 0 []
split('\n')  rows replayed: 2 ['BV1', 'BV2']
```

The same defect class was already fixed on the other side of the fence: `AttemptLedger` documents
that its tail is split on `"\n"` only, "never `str.splitlines()`, which also breaks on U+2028/U+2029/
U+0085 — legal inside a JSON string and written raw by this repo's own writer
(`ensure_ascii=False`)". `manifest.py` never received the same treatment.

**目标与非目标（一行）**：目标是「已写入的行不丢」——journal 里的每一行在 `load()` 可见，
且一次 `save()` 之后仍留在 `{root}/manifest/manifest.jsonl`；非目标是**不改** torn-tail 的
`break` 语义（真正的尾部截断仍停止回放，不改成 skip-and-continue）、不改 journal 磁盘格式、
也不在 validator 上加码点检查。

**Scope of this plan's claim (PM ruling, 2026-10-03, after the plan-QC tri-review).** This plan closes the
**split-rule** cause of durable deletion. It does **not** close the class: during QC, seat 3 found and
reproduced a *separate* path with the same consequence — `migrate_legacy_rows` uses the snapshot-only
`_read_latest()` as its rewrite base, over-writes journaled rows only for absent or bare-legacy keys, and then
unlinks the journal, durably deleting a journaled supersede of an existing page-qualified row. That is captured
as **`I-000195`** (high) and routed into plan `journal-compaction-lifecycle` as an added task. Read this plan's
Done as "the replay no longer truncates and no rewrite here deletes a row the replay saw", **not** as "the
ledger can no longer lose a row on any rewrite path".

## Current state (excerpt — verify against live code before editing)

`bilibili-asr-archive/src/bili_asr/manifest.py:252-262`:

```python
        journal_bytes = len(raw)
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = validate_manifest_record(json.loads(line))
            except ValueError:
                # Torn write at the tail: nothing after it was fully appended
                # either, so stop replaying rather than skip mid-stream.
                break
            entries[_entry_key(entry)] = entry
        return entries, journal_bytes
```

The sibling that already documents the rule — `bilibili-asr-archive/src/bili_asr/coordinator.py:311-312`:

```python
        * the tail is split on ``"\\n"`` only, never ``str.splitlines()``, which
          also breaks on U+2028/U+2029/U+0085 — legal inside a JSON string and
          written raw by this repo's own writer (``ensure_ascii=False``).
```

The writer side, for reference — `bilibili-asr-archive/src/bili_asr/persistence.py:113-116`:

```python
        return (json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
```

## Invariant restored (target state, not the line moved)

**Every fully-appended journal line is visible to every reader, and no rewrite may delete a line the
replay never saw.** Two rules follow: the journal is sliced on the record separator the writer
actually emits (`\n`), and a torn tail still stops the replay (`break`, not skip). After the change
all three journal readers in the repo — `manifest._replay_latest`, `sidecar_projection.iter_jsonl_records`,
`coordinator.AttemptLedger` — slice by the same rule, and the one that *writes* the ledger can no
longer lose more than the one that only reads it. The target state is agreement between readers of
one journal, not a one-character edit.

## Contracts to preserve (name these in the task report)

- **The split rule is a module-wide contract, not a local fix.** `coordinator.py:311-312` states it in
  prose for `AttemptLedger`; `sidecar_projection.iter_jsonl_records` (`sidecar_projection.py:193-218`)
  already implements it. After this plan, the three journal readers in the repo agree by
  construction — that agreement is the deliverable, not the one-character edit.
- **The journal append format + durability are untouched.**
  `persistence.py:113-116` (`ensure_ascii=False`, `separators=(",", ":")`, `allow_nan=False`) and
  `manifest.py:275-288` (`write` → `fsync(fd)` → `fsync(directory_fd)`) define what a "line" is. This
  plan changes only how a reader *slices* those bytes; it must not make the writer safer (e.g. by
  escaping U+2028) — that would be a disk-format change and is out of scope.
- **The torn-tail `break` is a durability guarantee.** A torn trailing line means "everything after it
  was never fully appended"; `break` (not `skip`) is what keeps that honest under
  `_append_record`'s `O_APPEND` + `fsync` ordering. Keep it exactly.
- **`_read_latest` (the snapshot side) and `_replay_latest` must not diverge in a new way.**
  `_read_latest` iterates a text-mode file object (`manifest.py`, `for line in fh`), which splits on
  `\n` only; `_replay_latest` after this fix does the same. Keep the two rules identical — the defect
  was precisely "the two readers of one ledger disagree".
- **`_maybe_compact_locked` / `save()` / `compact()` / `migrate_legacy_rows()` all rewrite the snapshot
  from `_replay_latest`'s output.** This plan is what makes that output complete; the sibling plan
  (`journal-compaction-lifecycle`) is what makes the rewrite reachable. Do not pre-empt its edits here.

## Conventions to follow

- The repo's written rule (above, in `coordinator.py`) is the convention: split on `"\n"` only.
- Keep the torn-tail rule exactly as it is — `break` on the first invalid record; do not switch to
  skip-and-continue (a mid-stream skip would hide real corruption).
- `_read_latest()` (the snapshot side) is **not** affected: it iterates the file in text mode and is
  out of scope.

## Tasks

### Task 1 — Change the split (Effort: S)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/manifest.py` (`_replay_latest`, ~`:252-262`)

**Change.** Decode then split on `"\n"`:

```python
        for line in raw.decode("utf-8", errors="replace").split("\n"):
```

Keep `.strip()`, the empty-line `continue`, the `validate_manifest_record(json.loads(line))` call
and the `except ValueError: break`. No on-disk format change; nothing else in the module reads the
journal by a different rule except the ones already correct.

**In scope**: `bilibili-asr-archive/src/bili_asr/manifest.py`,
`bilibili-asr-archive/tests/test_manifest.py`.

**Out of scope**: `_read_latest` (snapshot text-mode read — already correct),
`sidecar_projection.iter_jsonl_records` (already newline-based), the writer in `persistence.py`
(the raw emission is deliberate), the `AttemptLedger` (already correct).

### Task 2 — Pin the class (Effort: S, same round)

Add a regression test in `tests/test_manifest.py`:

1. Write a journal containing a row whose `title` (or `video_title`) carries `\u2028`, followed by a
   later row with a distinct key.
2. Assert `store.load()` returns **both** rows.
3. Assert the later row survives a `save()` — i.e. the rewritten snapshot still holds it, so the
   durable-loss half is pinned too, not only the read half.

The test must fail on the pre-fix code (row 2 missing after the break) — record the red/green pair.

## STOP conditions

- If `_replay_latest` no longer matches the excerpt (a merge already fixed it), STOP and report —
  do not re-apply.
- If `validate_manifest_record` has grown a code-point check that rejects U+2028 rows, STOP: the
  trigger would then be a *rejected* row, and the fix belongs at the validator, not the split.
- If the torn-tail `break` semantics are load-bearing for a test that asserts a specific truncation
  count, STOP and read that test first — the change must not alter genuine-corruption behaviour.
- **Contract-breaking (irreversible) — STOP, do not implement around it:**
  - If the fix is proposed to be made **safe by escaping** U+2028/U+2029/U+0085 on the write side
    (`persistence.py:_json_line`) instead of fixing the reader, **STOP and report to PM**. That
    changes the on-disk journal format every existing reader and every already-written file depends
    on; `sidecar_projection.iter_jsonl_records` and `AttemptLedger` are newline-based precisely
    because the raw emission is deliberate. The repair is on the reader, and only there.
  - If making `_replay_latest` newline-based requires touching `_append_record`'s durability ordering
    or the `os.fstat` signature capture (`manifest.py:275-288`), STOP — those are the cross-process
    contracts the replay exists to serve.
  - If a reader other than `_replay_latest` inside `manifest.py` still splits with `splitlines()`
    after the change (grep the module, not the file's neighbourhood), STOP: a partially-converted
    ledger module is the failure mode this plan is closing, not a partial win.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/src/bili_asr/persistence.py
git log --oneline 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/manifest.py
grep -rn "splitlines" bilibili-asr-archive/src/bili_asr/ bilibili-asr-archive/tests/ || echo "no splitlines in journal readers"
```

Re-read before editing when any of these is non-empty:

1. `manifest.py` changed — re-read `_replay_latest` against the excerpt and check whether another
   landing already converted the split (its `except ValueError: break` shape is the discriminator).
2. `persistence.py` changed — the writer defines what a journal "line" is; a change there
   (`ensure_ascii`, separators, escaping) changes what this fix has to slice.
3. `splitlines` still appears under `src/` in a **journal reader** — the sibling fix
   (`journal-compaction-lifecycle`) must not be touching this rule, and this plan must not leave a
   second reader on the old rule.
4. `manifest.py`'s own test file (`tests/test_manifest.py`) gained a journal-shaped case written
   before this plan lands — it may already pin a different split rule; reconcile rather than overwrite.

**Ordering note (cross-plan interference, recorded):** this plan lands **first**, then
`journal-compaction-lifecycle` (see that plan's `Depends on`). Both edit `manifest.py`: this one owns
`_replay_latest`, that one owns `_maybe_compact_locked` + `save()`. Neither may edit the other's
region; if a landing needs to, STOP and report rather than racing the sibling.

## Done criteria

- [ ] `_replay_latest` splits on `"\n"`; no `splitlines()` remains in `manifest.py`
- [ ] **Observable, outside the process that implements it** — with a journal carrying a U+2028 row
      followed by a later row, a fresh `ManifestStore(...).load()` returns **both** keys, and after a
      `save()` a reader that only opens `{root}/manifest/manifest.jsonl` finds **both** rows in the
      rewritten snapshot (durable-loss half pinned, not only the read half)
- [ ] New test with a `\u2028`-bearing row fails before and passes after (record red/green)
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_manifest.py` passes; record the command and result
- [ ] `grep -n "splitlines" bilibili-asr-archive/src/bili_asr/manifest.py` returns no match
- [ ] `git diff --check -- bilibili-asr-archive/src/bili_asr/manifest.py` exits 0
- [ ] No files outside the in-scope list are modified (`git status --short`)

## Verification notes

Run from the package root with the absolute source path pinned (the venv editable install can resolve
`bili_asr` to the control checkout). Do not run the full suite; this change needs `test_manifest.py`
plus the read-path tests that already exist.

If a real U+2028 sample is wanted for the fixture, construct it in Python (`"\u2028"`) rather than
pasting the literal character into a source file — the file would then carry the same hazard.

## QA Gate Summary

**`accepted` — 2026-10-03** (`qa-engineer`, `QA gate: mandatory` / `QA mode: acceptance-only`; report
`{SDD_DIR}/journal-replay-integrity/qa-acceptance.md`, range `1e756df..fbe2087`).

All 7 in-scope Done criteria pass, re-derived at range head: `_replay_latest` splits on `"\n"` with no
`splitlines()` left in `manifest.py`; the two-process observable returns both keys from `load()` and from a
snapshot-only reader; the red/green pair was reproduced independently (base twin byte-identical to the
`1e756df` blob → `-k u2028` 1 failed, durable-half-alone 1 failed with the snapshot holding only
`{'BV0aa:p0'}`, and the pre-fix twin printing `load() keys: []`); `tests/test_manifest.py` 29 passed (40 with
`test_manifest_derivation.py`); `git diff --check` exit 0; scope = the two in-scope files.
Open residuals: `I-000164` (this plan's own issue — its acceptance is now evidenced; closure is PM-owned),
`I-000195` (high, pre-existing `migrate_legacy_rows` path — out of this plan's narrowed claim and routed to
plan `journal-compaction-lifecycle` Task 4), `I-000196` (low, decode-policy asymmetry — out of scope).

### Plan QC (tri-review, N=3)

`Approve with residuals` — verdicts `Approve` / `Approve` / `Request Changes`; 0 Critical. The single
Request Changes was a **pre-existing** defect outside this diff (`I-000195`), for which the PM recorded a
disposition (capture + route into plan `journal-compaction-lifecycle` + correct that plan's sibling premise)
rather than a silent pass. Consolidated in `{SDD_DIR}/journal-replay-integrity/review/qc-consolidated.md`
(seat reports `qc1.md`–`qc3.md`, all passing `mstar qc validate-report`). Seat 1's stale-citation finding was
fixed the same round by adding an authoritative re-anchor note to the sibling plan.

### L2 task review

`Approved`, zero findings — `{SDD_DIR}/journal-replay-integrity/task-1-review.md` (independently established
that `splitlines()` breaks on exactly `{U+0085, U+2028, U+2029}` and that the writer emits exactly those raw).

## Engine lifecycle ownership

Source-only repair, no lifecycle claim. Advanced by PM through the normal per-plan flow; no delivery
tail promised.
