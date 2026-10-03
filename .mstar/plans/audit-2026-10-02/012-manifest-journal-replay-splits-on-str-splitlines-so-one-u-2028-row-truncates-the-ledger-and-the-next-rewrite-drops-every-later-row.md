# Plan 012 — Split the manifest journal replay on `"\n"`, not `str.splitlines()`

## Status
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/02-manifest-journal-splitlines
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/manifest.py:253` — `_replay_latest` iterates `raw.decode(...).splitlines()` with `except ValueError: break` at `:258-261`
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

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/src/bili_asr/persistence.py
```

If either changed, re-read the replay and the writer against the excerpts above before proceeding.

## Done criteria

- [ ] `_replay_latest` splits on `"\n"`; no `splitlines()` remains in `manifest.py`
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

## Engine lifecycle ownership

Source-only repair, no lifecycle claim. Advanced by PM through the normal per-plan flow; no delivery
tail promised.
