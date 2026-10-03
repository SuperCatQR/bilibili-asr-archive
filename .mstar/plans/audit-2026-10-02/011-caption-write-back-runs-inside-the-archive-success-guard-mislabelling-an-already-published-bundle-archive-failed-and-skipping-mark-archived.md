# Plan 011 — Hoist the caption write-back out of the archive success guard

## Status
- **Priority**: P1
- **Effort**: XS
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/01-caption-writeback-guard
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/coordinator.py:850` — `_record_subtitle_transcript` runs inside the try opened at `:845`; the failure record is `:853-858`, `_mark_archived` is `:860`
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
`_mark_archived` (`:860`) is skipped, so the manifest row never becomes `archived`. A rerun
republishes the same bundle, and the operator is shown a failure for a complete archive.

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

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/coordinator.py
```

If `coordinator.py` changed since `1e756df`, compare the `_stage_archive_from_subtitle` body against
the excerpt above before proceeding.

## Done criteria

- [ ] `_record_subtitle_transcript` is called after `_mark_archived`, outside the archive `try`
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

## Engine lifecycle ownership

No engine lifecycle ownership is claimed by this plan: it is a source-only repair. It is advanced by
PM through the normal per-plan flow (registered row → `InProgress` → QC → QA → `Done`); no delivery
tail is promised here.
