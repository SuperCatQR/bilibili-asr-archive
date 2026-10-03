# Plan 014 — Make journal compaction reachable and order `save()` like its siblings

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/04-manifest-journal-compaction
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/manifest.py:295-315` — the compaction gate; `:380-392` — `save()`'s unlink-before-write order; thresholds at `:51-54`
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issues**: `I-000167` (compaction), `I-000170` (`save()` ordering)

## Problem

Two defects in the manifest journal ledger, one structural and one an ordering window.

### 1. The journal never compacts on any in-repo path

`_maybe_compact_locked` requires **both** clauses to hold:

```python
        if not (
            self._appends_since_compact >= _JOURNAL_COMPACT_THRESHOLD
            and journal_bytes >= max(1, _JOURNAL_WRAP_BYTES_FACTOR * snapshot_bytes)
        ):
            return
```

`_JOURNAL_COMPACT_THRESHOLD = 256` counts appends **by this process instance**
(`self._appends_since_compact += 1` per append, reset to `0` at construction). Normal invocation
shapes — `run --limit N`, `asr`, `pilot`, or any bounded batch — append far fewer than 256 rows in
one process, so the counter resets before the byte clause can even be evaluated. And a whole-tree
grep shows **no `src/` caller invokes `save()` or `compact()`** (only tests do).

Net effect: the journal is never folded. Every fresh process and every projection pays
`O(snapshot bytes + journal bytes)` of parse-and-validate, and the cost grows with the number of
transitions ever recorded — not with corpus size. The deterministic snapshot, whose whole purpose is
to bound the read, is never refreshed.

Readers paying the full replay:
- `ManifestStore.load()` → `_replay_latest()` (`:222-266`);
- `sidecar_projection.replay_journal_records` (`sidecar_projection.py:193-218`) → used by
  `project_manifest_records`, i.e. `integrity`, `coverage_report`, `cli/status_cmd`;
- `SearchIndex.is_stale` (`search_index.py:527-533`) — on **every `search`** (see plan 019's sibling
  finding `I-000172`).

### 2. `save()` unlinks the journal before rewriting the snapshot

`save()` is the only one of the three rewrite paths with the inverted order:

| method | order |
|---|---|
| `save()` `:380-392` | `_replay_latest()` → **`_remove_journal()`** → `if not current: return` → `_replace_snapshot(current)` |
| `compact()` `:396-407` | `_replace_snapshot(current)` → `_remove_journal()` |
| `migrate_legacy_rows()` `:597-603` | `_replace_snapshot(next_entries)` → `_remove_journal()` |

A crash, `SIGKILL`, or a raised `OSError` (e.g. ENOSPC on the temp write) between the unlink and the
`os.replace` loses every row that lived only in the journal — they were in `current`, an in-memory
dict that dies with the process — while the stale snapshot stays in place. Combined with defect 1
(the journal is where new rows actually live), that window is wider than the code implies.

**Interaction with `I-000138`**: that registered row covers `compact()` deleting the journal when the
snapshot is absent. The fix here must **preserve** the invariant it established: never unlink a
journal whose rows were not successfully folded into a snapshot.

## Current state (excerpts — verify against live code before editing)

`bilibili-asr-archive/src/bili_asr/manifest.py:51-54`:

```python
#: Rewrite the snapshot once an appending store holds this many journal rows.
_JOURNAL_COMPACT_THRESHOLD = 256

#: Wrap the journal when its byte size exceeds the snapshot's by this factor.
_JOURNAL_WRAP_BYTES_FACTOR = 2
```

`bilibili-asr-archive/src/bili_asr/manifest.py:295-315`:

```python
    def _maybe_compact_locked(
        self, entries: dict[str, dict[str, Any]], *, journal_bytes: int
    ) -> None:
        """Fold the journal into the snapshot once append history is dominant.
        ...
        """
        snapshot_bytes = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        if not (
            self._appends_since_compact >= _JOURNAL_COMPACT_THRESHOLD
            and journal_bytes >= max(1, _JOURNAL_WRAP_BYTES_FACTOR * snapshot_bytes)
        ):
            return
        self._replace_snapshot(entries)
        self._remove_journal()
        self._appends_since_compact = 0
        self._journal_bytes = 0
```

`bilibili-asr-archive/src/bili_asr/manifest.py:380-393`:

```python
        requested = dict(entries) if entries is not None else None
        with self._manifest_lock(create=True):
            current, _journal_bytes = self._replay_latest()
            if requested is not None:
                current.update(requested)
            self._remove_journal()
            self._appends_since_compact = 0
            self._journal_bytes = 0
            self._journal_signature = self._journal_stat_signature()
            if not current:
                self._entries = {}
                self._loaded = True
                return
            self._replace_snapshot(current)
```

Note the `journal_bytes` passed into `_maybe_compact_locked` is `self._journal_bytes`, which counts
only what **this instance** appended — a second process appending to the same journal never advances
it. That is a second reason the trigger is per-instance rather than per-file.

## Conventions to follow

- The module's own docstrings already state the intended shape: compaction "rewrites the deterministic
  snapshot (byte-stable by construction, since it sorts keys and serializes with fixed separators) and
  atomically resets the journal". Match that; do not invent a new format.
- All three rewrite methods hold `self._manifest_lock`; any new trigger must too.
- `_replace_snapshot` writes a temp file + `os.replace` + directory `fsync`; reuse it, do not
  hand-roll persistence.

## Tasks

### Task 1 — Make the trigger file-based (Effort: S)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/manifest.py` (`_maybe_compact_locked` ~`:295-315`,
  constants ~`:51-54`)

**Change.** Replace the per-instance clause with a per-file one: compact when the journal has grown
past the snapshot, e.g.

```python
        if journal_bytes < max(_JOURNAL_MIN_COMPACT_BYTES, _JOURNAL_WRAP_BYTES_FACTOR * snapshot_bytes):
            return
```

where `journal_bytes` is the size **read from the file** (the value `_replay_latest` already returns
and the call site has in `self._journal_bytes` after a replay — pass the on-disk size, not the
per-instance appends counter). Keep a floor so a tiny ledger does not rewrite constantly (a snapshot
of a few hundred bytes would otherwise compact on every row).

Preserve: the snapshot-absent case must not delete a journal it did not fold (`I-000138`), and the
`_JOURNAL_COMPACT_THRESHOLD` constant may be kept as the floor or deleted with the counter — if you
delete it, delete `_appends_since_compact` with it rather than leaving it unused.

**In scope**: `bilibili-asr-archive/src/bili_asr/manifest.py`,
`bilibili-asr-archive/tests/test_manifest.py`, and (if a maintenance command is added in Task 3)
`bilibili-asr-archive/src/bili_asr/cli/*.py` for that one command plus its test file.

**Out of scope**: the journal's format, `_append_record`'s durability (write + `fsync` + directory
`fsync` — do not weaken), `_replay_latest`'s split rule (that is plan 012's fix; if 012 has not
landed, do not duplicate it here), `search_index.py`.

### Task 2 — Order `save()` like its siblings (Effort: XS, same round)

**Change.** In `save()`, move `_remove_journal()` to **after** the successful `_replace_snapshot(...)`,
and leave both artifacts untouched when `current` is empty:

```python
        with self._manifest_lock(create=True):
            current, _journal_bytes = self._replay_latest()
            if requested is not None:
                current.update(requested)
            if not current:
                self._entries = {}
                self._loaded = True
                return
            self._replace_snapshot(current)
            self._remove_journal()
            self._appends_since_compact = 0
            self._journal_bytes = 0
            self._journal_signature = self._journal_stat_signature()
```

This also fixes the empty-`current` early return that currently unlinks first — the `I-000138`
hazard in its `save()` form.

### Task 3 (only if the trigger alone does not close it) — Expose compaction (Effort: S)

If a bytes-only trigger still leaves a long-lived archive unable to fold (e.g. the journal only ever
grows during readers' processes, which never append and so never compact), add a bounded maintenance
surface: a `bili-asr` subcommand that opens the store and calls `compact()` under the lock, printing
the before/after snapshot and journal sizes. Route it through the existing CLI module for the archive
root (`cli/queue.py` or a new small module — check which module already owns manifest maintenance
before choosing). Do **not** add it to an unrelated command.

**Split point.** Task 1+2 are one round. Task 3 is a separate round if the trigger proves
insufficient — the split boundary is the CLI surface, not the trigger.

## STOP conditions

- If `_maybe_compact_locked` or `save()` no longer matches the excerpts, STOP and re-read.
- If making compaction file-based would compact on **every** append for a small archive (snapshot
  absent or tiny), STOP and pick the floor with the measured sizes from the live root
  (`/srv/bili-asr-archive/manifest/manifest.jsonl` is 9032 bytes over 34 rows) rather than guessing —
  the cost of a wrong floor is a snapshot rewrite per row.
- If a test asserts the journal survives a specific `save()` sequence, STOP and read it: the ordering
  change is exactly what such a test would pin.
- If the journal is absent on the target root (the live root has none today), do not fabricate a
  trigger from it — the byte arithmetic must hold for the snapshot-only case too.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/src/bili_asr/sidecar_projection.py
```

If `manifest.py` changed, re-read both methods against the excerpts before editing.

## Done criteria

- [ ] A normal append path (not just tests) can fold the journal: a test drives N cross-process
      appends and asserts the journal shrank and the snapshot holds every row
- [ ] `save()` writes the snapshot before unlinking the journal; the empty-`current` case touches
      neither artifact
- [ ] The `I-000138` invariant holds: with no snapshot and journal rows present, no path deletes the
      journal
- [ ] A failure injected between the snapshot write and the journal unlink leaves the journal
      recoverable (record the injected failure and the observable)
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_manifest.py` passes; record the command and result
- [ ] `git diff --check` exits 0; `git status --short` shows no out-of-scope file
- [ ] Record the on-disk before/after sizes for snapshot and journal in the task report

## Verification notes

Run from the package root with the absolute source path pinned. Do not run the full suite. Any
timing/ordering assertion must be deterministic — no sleeps. If the compaction test needs a journal
larger than a floor, construct it by appending rows through `upsert`, not by writing the file by hand
(the point is to exercise the real path).

## Engine lifecycle ownership

Source-only repair, no lifecycle claim. Advanced by PM through the normal per-plan flow; no delivery
tail promised. If Task 3 adds a CLI surface, that is still a plan-local change — no new workflow
registration.
