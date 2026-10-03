# Plan 015 — Resolve the write-back's page identity from the row, and pin the write-back end to end

## Status
- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Confidence**: MED
- **Fingerprint**: audit-2026-10-02r2/05-writeback-page-identity-witness
- **Depends on**: plans/013-*.md
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py:366-372` — the `(bvid, page_index)` resolver; the four `or 0` call sites below
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issues**: `I-000171` (page identity), `I-000176` (missing witness)

## Problem

Two related gaps on the store write-back that the R14 work landed.

### 1. `page_index` is fabricated as 0 at every call site

The write-back resolves the store's part by `(bvid, page_index)`, and every caller supplies the page
index with `int(entry.get("page_index") or 0)`:

| call site | line |
|---|---|
| `coordinator.py` (`_record_subtitle_transcript`) | `:759` |
| `coordinator.py` (`_record_asr_transcript`) | `:798` |
| `cli/asr.py` | `:294` |
| `cli/pilot.py` | `:605` |

For a legacy or unresolved row — one without a `work_id` — the archive is written under the **bare
`bvid` stem** (`archive.archive_stem` `:50-54` returns `bvid` when `work_id` is absent or
`unresolved`). The write-back then resolves `(bvid, 0)` and stamps the produced transcript onto the
**p0** `video_part_id`. The part the archive actually belongs to is not the part the store is told
about: `v_missing_transcript` keeps the true part, p0's row gains a transcript it did not produce,
and the `acquisition_attempts` evidence names the wrong part.

The `or 0` is defensible as "the default page" for a single-part video — but for a *bare-bvid row*
the page identity is genuinely unknown, and guessing is worse than skipping: the archive on disk is
already complete and the gap row is supplementary evidence.

### 2. Nothing asserts the write-back at CLI level

The write-back fires only under a compound guard
(`not use_manifest and queue_source is not None and source == "asr" and asr_run_id is not None`,
`cli/asr.py:284-296`; the mirror is `coordinator.py:780-805`). Today's tests call
`record_local_transcript(...)` **directly** (`tests/test_storage_queue_writes.py:718-861`), and the
chain's ASR arm asserts only ledger/attempts (`tests/test_derived_queue_chain.py:399-408`).

So a regression in the guard or the wiring is invisible to every CLI and chain test, while the
observable the operator cares about — `v_missing_transcript` draining — stays broken. This is the
missing-witness half of `I-000067`.

## Current state (excerpts — verify against live code before editing)

`bilibili-asr-archive/src/bili_asr/services/queue_source.py:360-372` (the resolver):

```python
        connection = queue_source.connection
        part = connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, int(page_index)),
        ).fetchone()
        if part is None:
            return
        video_part_id = int(part["video_part_id"])
```

`bilibili-asr-archive/src/bili_asr/coordinator.py:755-763` (one call site):

```python
        qs.record_caption_transcript(
            source,
            run_id=run_id,
            bvid=str(entry.get("bvid") or ""),
            page_index=int(entry.get("page_index") or 0),
            source_kind=source_kind,
            language=language,
            segments=_caption_transcript_segments(segments),
        )
```

`bilibili-asr-archive/src/bili_asr/archive.py:50-54` (why the archive and the store disagree):

```python
def archive_stem(entry: dict[str, Any]) -> str:
    bvid = str(entry["bvid"])
    if entry.get("unresolved") or not entry.get("work_id") or entry.get("cid") is None:
        return bvid
    return artifact_stem(page_identity(bvid, int(entry.get("page_index") or 0), int(entry["cid"]), page_label=str(entry.get("page_label") or "")))
```

The guard the witness must exercise — `bilibili-asr-archive/src/bili_asr/cli/asr.py:284-296`.

## Conventions to follow

- The write-back's contract is "best-effort, never disturb the archive": a part the store does not
  hold fails this row only, and the caller keeps going. Skipping an unresolvable page identity is
  consistent with that contract; raising is not.
- `parse_work_id` (`manifest.py`) already exists and is the repo's canonical `work_id` → `(bvid,
  page)` parser — use it rather than re-splitting the string.
- Match the existing test idiom for a seeded store: `tests/_archive_database.py`'s
  `_seed_archive_database` plus the ASR fakes in `tests/_asr_fakes.py`.

## Tasks

### Task 1 — Resolve the page from the row, or skip (Effort: S)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/services/queue_source.py` (both write-back helpers'
  signatures + the two resolvers, ~`:329-372`, `:391-460`)
- Modify: `bilibili-asr-archive/src/bili_asr/coordinator.py` (two call sites, `:759`, `:798`)
- Modify: `bilibili-asr-archive/src/bili_asr/cli/asr.py` (`:294`)
- Modify: `bilibili-asr-archive/src/bili_asr/cli/pilot.py` (`:605`; also check `:357`/`:367`)

**Change.** Give the resolvers an explicit "unknown page" path:

```python
def record_local_transcript(
    queue_source: QueueSource,
    *,
    run_id: str,
    bvid: str,
    page_index: int | None,      # None -> the row has no resolvable page; skip
    ...
) -> None:
```

and return early when `page_index is None` (same best-effort semantics as a missing part). At the
four call sites, derive the page from the row's `work_id` via `parse_work_id`, falling back to `None`
rather than `0` when the row carries no `work_id`:

```python
page_index = int(entry["page_index"]) if entry.get("work_id") and entry.get("page_index") is not None else None
```

(Keep the exact expression idiomatic to each site — `cli/pilot.py:357` may already have a resolved
page in hand; read it before changing.)

**In scope**: the four sites listed above, the two resolver helpers, and the tests for them.

**Out of scope**: `mark_audio_acquired` / `mark_transcript_stored` (different call sites and
semantics), `archive.archive_stem`, the `ensure_asr_run` guard (plan 013), and the store schema.

### Task 2 — Add the missing end-to-end witness (Effort: M, same round)

**Files**
- Modify: `bilibili-asr-archive/tests/test_cli_asr.py` (extend the store-route audio branch), or
  `tests/test_derived_queue_chain.py:399-408` if it already drives the whole route

**Change.** Two cases:

1. **Success path** — drive one store-route `asr` row to `archived` and assert its own part's
   transcript count is 1 (`_part_transcript_count(tmp_root, QUEUED_BVID, QUEUED_PAGE_INDEX) == 1`,
   matching the helper the caption part already uses at `tests/test_derived_queue_chain.py:327,452`).
   Assert against the **part**, not the bvid, so a future p0-fabrication regression turns this test
   red.
2. **Best-effort path** — with the store refusing the run (`ensure_asr_run` returning `None`), assert
   the archive still reaches `archived` and records no transcript row. This pins the guard's
   tolerance, so a later "fix" cannot turn a store problem into an archive failure.

**Split point.** Task 1 and Task 2 are one round for a normal-sized repo; if the store-route fixture
turns out not to exist, split Task 2 out and land Task 1 alone (its own unit test can assert the
`None` skip), reporting the fixture gap.

## STOP conditions

- If `int(entry.get("page_index") or 0)` no longer appears at those sites (a merge changed them), STOP
  and re-locate the write-back callers before editing.
- **Measure the population before choosing strictness**: if the target root's unresolved/bare-bvid
  row count is non-zero, the skip silently shrinks write-back coverage for those rows. Run the count
  query first (`SELECT COUNT(*) FROM video_parts vp WHERE NOT EXISTS (SELECT 1 FROM transcripts t
  WHERE t.video_part_id = vp.video_part_id)`) and report the number in the task report. If it is large,
  STOP and return to PM — the right fix may be to resolve the page at archive time instead.
- If the store-route ASR fixture would require live network or a GPU, STOP: use the existing fakes
  (`_asr_fakes.py`, `mock_torch`) — this plan must stay offline.
- If plan 013 has not landed and the same-second collision makes the witness flaky, STOP and land 013
  first rather than adding a sleep.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/services/queue_source.py bilibili-asr-archive/src/bili_asr/coordinator.py bilibili-asr-archive/src/bili_asr/cli/asr.py bilibili-asr-archive/src/bili_asr/cli/pilot.py
```

If any changed, re-read the write-back call sites against the excerpts.

## Done criteria

- [ ] No write-back call site fabricates a page index with `or 0`; the page comes from the row's
      `work_id` or is explicitly `None`
- [ ] A `None` page skips that part's write-back and does not raise
- [ ] Store-route ASR witness asserts the archived part has exactly one transcript row
- [ ] Best-effort witness asserts the archive still reaches `archived` when the store refuses the run
- [ ] Both new tests fail before the change and pass after (record the red/green pair)
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_cli_asr.py tests/test_storage_queue_writes.py` passes; record the command and result
- [ ] The unresolved-row population query result is recorded in the task report
- [ ] `git diff --check` exits 0; `git status --short` shows no out-of-scope file

## Verification notes

Run from the package root with the absolute source path pinned; never run the live/GPU markers. The
witness must assert store state (`transcripts` rows / `v_missing_transcript`), not log lines — the
repo's own `testing-patterns/absence-assertion-negative-control.md` requires the fixture to be able to
reach the producer, and here the producer is the write-back itself.

## Engine lifecycle ownership

Source-only repair, no lifecycle claim. Advanced by PM through the normal per-plan flow; no delivery
tail promised.
