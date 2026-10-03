# Plan 013 — Make the ASR run id unique so a same-second collision cannot silence every write-back

## Status
- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/03-ensure-asr-run-pk-collision
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py:140-157` — `run_id = f"{command}-{int(_time.time())}"` then `start_acquisition_run` inside `try/except Exception` → `asr_run_id = None`
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issue**: `I-000166`

## Problem

`QueueSource.ensure_asr_run` mints this invocation's run id from the command name and the current
wall-clock **second**:

```python
now = int(_time.time())
run_id = f"{command}-{now}"
```

`acquisition_runs.run_id` is a **`TEXT PRIMARY KEY`**, and `start_acquisition_run` is documented to
raise `sqlite3.IntegrityError` on a duplicate. That raise is caught by a deliberately broad
`except Exception:` which sets `self.asr_run_id = None`.

Every transcript write-back is keyed on that id — `coordinator.py:750` and `:782`
(`_record_subtitle_transcript` / `_record_asr_transcript`), `cli/asr.py:287-299`,
`cli/pilot.py:592-611` — and each of those returns early when the id is `None`. So a collision does
not fail loudly; it **silently disables the whole invocation's write-backs**, which is exactly the
R14 / `v_missing_transcript` gap (`I-000067`) that the write-back was landed to close, re-entered at
one-second granularity. The operator sees a successful archive.

### The collision is reachable in-process, not only across invocations

`RunCoordinator._close_writeback_source` (`coordinator.py:702-706`) sets `self._writeback_source =
None` at **every batch boundary** (called from the `finally` at `:1204`). The next batch re-opens the
source, so `asr_run_id` is `None` again and `ensure_asr_run` re-mints the id from the same wall-clock
second whenever a batch boundary falls inside one second — a normal shape for small batches,
fast-failing rows, or a bounded `--limit`.

Cross-process shapes hit the same path: two shells, a scripted retry loop, or `pilot` following `run`
within the same second.

## Current state (excerpt — verify against live code before editing)

`bilibili-asr-archive/src/bili_asr/services/queue_source.py:136-157`:

```python
        if self.asr_run_id is not None:
            return self.asr_run_id
        try:
            now = int(_time.time())
            run_id = f"{command}-{now}"
            TranscriptRepository(self.connection).start_acquisition_run(
                AcquisitionRunRecord(
                    run_id=run_id,
                    kind="asr",
                    selector_kind="pending",
                    selector_target=None,
                    requested_limit=None,
                    credential_present=False,
                    started_at=now,
                )
            )
            self.asr_run_id = run_id
        except Exception:
            self.asr_run_id = None
        return self.asr_run_id
```

The schema fact — `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql:50-51`:

```sql
CREATE TABLE IF NOT EXISTS acquisition_runs (
    run_id TEXT PRIMARY KEY,
```

The repository contract — `bilibili-asr-archive/src/bili_asr/storage/database.py:931-935`:

```python
    def start_acquisition_run(self, run: AcquisitionRunRecord) -> None:
        """...
        ``run_id`` is the primary key and is never reused: a duplicate raises
        ``sqlite3.IntegrityError``.  The run is committed on its own so a
```

## Conventions to follow

- The module's own docstring says the run is best-effort and a store that refuses the run must leave
  `asr_run_id` `None` — that contract stays. What changes is the id, so a **legitimate** retry no
  longer looks like a refusal.
- Match the repo's error-handling pattern in `queue_source.py`: bounded `except` clauses naming the
  concrete classes, not a blanket `Exception` (the neighbouring `record_local_transcript` /
  `record_caption_transcript` both name `(_sqlite3.Error, OSError, ValueError, TypeError, KeyError)`).
- Ids are opaque to every consumer but the store (grep confirms nothing parses them).

## Tasks

### Task 1 — Make the id unique (Effort: S)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/services/queue_source.py` (`ensure_asr_run`, ~`:121-158`)

**Change (pick one, prefer the first):**

1. **Monotonic suffix** — `run_id = f"{command}-{time.time_ns()}"` (keeps the readable
   `command-timestamp` shape, removes the one-second window), or
2. **Suffix bump on collision** — attempt `f"{command}-{now}"`, and on `sqlite3.IntegrityError`
   retry with a disambiguating suffix (e.g. `-{n}` for n in 2..N) before giving up.

Whichever is chosen, narrow the `except Exception:` to the classes the store actually raises
(`sqlite3.Error`, `OSError`, `ValueError`), so a programming error no longer masquerades as
"store refused the run". Keep `started_at=now` (a Unix second is the schema's granularity).

**Interfaces (verbatim, unchanged):**

```python
def ensure_asr_run(self, command: str) -> str | None: ...
```

**In scope**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py`,
`bilibili-asr-archive/tests/test_storage_queue_writes.py` (or the file already covering
`ensure_asr_run`; confirm before editing).

**Out of scope**: `start_acquisition_run` and the schema (`run_id` stays `TEXT PRIMARY KEY`), the
callers' guards, `finish_acquisition_run` (the separate "runs never finished" lead — not this plan).

### Task 2 — Pin the collision (Effort: S, same round)

Add a test that proves the defect class is closed:

1. Open two sources over the same seeded store (or call `ensure_asr_run` twice on two instances)
   **inside the same wall-clock second** — freeze/inject the clock if the module allows, otherwise
   assert the two ids differ rather than relying on timing.
2. Assert both calls return a non-`None` id and that the two ids differ.
3. Assert a `record_local_transcript` through each run id lands its `transcripts` row (the
   end-to-end half matters here — the id being non-`None` is not the observable the operator cares
   about).

Record the red/green pair: pre-fix the second call returns `None` (or both calls return the same id
and the second `start_acquisition_run` raises).

## STOP conditions

- If `ensure_asr_run` no longer matches the excerpt (a merge changed the id scheme), STOP and report.
- If some reader **does** parse the run-id format (grep `run_id` across `src/` and the tests before
  editing — the audit found none), STOP: the id shape would then be a contract, not an implementation
  detail.
- If the clock cannot be controlled in the test harness and the assertion would be timing-dependent,
  STOP and prefer the deterministic assertion (two ids differ) over a flaky one — never add a
  `sleep`.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/services/queue_source.py bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql
```

If either changed, re-read `ensure_asr_run` and the `acquisition_runs` definition before proceeding.

## Done criteria

- [ ] `ensure_asr_run` cannot collide within one second (monotonic id or retry-with-suffix)
- [ ] The `except` names concrete classes rather than bare `Exception`
- [ ] New test fails before and passes after; record the red/green pair and the assertion used
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_storage_queue_writes.py` passes; record the command and result
- [ ] `git diff --check -- bilibili-asr-archive/src/bili_asr/services/queue_source.py` exits 0
- [ ] No files outside the in-scope list are modified (`git status --short`)

## Verification notes

Run from the package root with the absolute source path pinned. Do not run the full suite. The
write-back's own end-to-end witness is **plan 015** — if both plans are in flight, land this one
first and let 015 assert the store-route row; do not duplicate the assertion here.

## Engine lifecycle ownership

Source-only repair, no lifecycle claim. Advanced by PM through the normal per-plan flow; no delivery
tail promised.
