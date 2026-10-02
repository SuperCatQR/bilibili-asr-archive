# Plan 005 — Skip already-stamped parts before the filesystem probe in `search-index` build

## Status
- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Confidence**: HIGH
- **Evidence**: `src/bili_asr/search_index.py:1392-1412` — the `stamped_part_ids` check precedes only the text read, not the candidate materialization + filesystem probe
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

Every `bili-asr search-index` build re-walks every published-markdown candidate. For each candidate it
probes up to 3 relative paths × N read bases with `os.path.isfile` before the `stamped_part_ids` check,
then reads the file. On an audio-only archive (residual R14: ASR never writes `transcripts` rows), the
candidate set is the **whole corpus every build** — so a build with zero new transcripts still performs
hundreds of filesystem probes and full markdown reads for already-indexed parts. Build time scales with
corpus size even when there is nothing new to index.

## Current state (excerpt)

`src/bili_asr/search_index.py:1399-1408`:
```python
for part in self._published_md_candidates(conn):
    part_id = int(part["video_part_id"])
    if part_id in stamped_part_ids:
        continue
    text = self._published_md_text_for(       # filesystem probe + full md read
        str(part["bvid"]), int(part["page_index"])
    )
    if not text:
        continue
    stamped_part_ids.add(part_id)
```

`stamped_part_ids` is computable from the index table alone (the query at `:1392-1398`), so the check does
**not** need to materialize the candidate or touch the filesystem.

## Approach

Filter the candidate set by `stamped_part_ids` **before** the per-candidate filesystem probe. Either:

- Push the anti-join into the candidate query (exclude already-stamped `video_part_id`s in
  `_published_md_candidates`'s SQL), so the loop body only sees genuinely-new parts; **or**
- Keep the loop but make the `stamped_part_ids` membership test the first thing inside it (it already is at
  `:1401`, but `_published_md_candidates` itself does filesystem-path work to *produce* the candidate —
  confirm and, if so, move the anti-join into SQL).

The preferred fix is the SQL anti-join: it avoids materializing already-stamped candidates at all.

## Files

- **Modify**: `src/bili_asr/search_index.py` — add the `stamped_part_ids` anti-join to
  `_published_md_candidates` (or its caller) so already-stamped parts are never probed.
- **Test**: `tests/test_search_index.py` — add the skip-before-probe assertion below.

## Out of scope

- Residual O-R5 (`transcript_fts_index_meta` written but never read) — a separate register row; this plan
  does not try to consume that meta.
- Residual R14 (ASR→transcripts bridge) — the correctness leg; this plan is the perf leg only.
- Changing the FTS schema or the index content.

## Verification gates

- **Skip-before-probe test** in `tests/test_search_index.py`: build the index once over a fixture with some
  already-indexed parts, run a second build, and assert the per-candidate filesystem probe / md read is
  **not** invoked for the already-stamped parts (e.g. monkeypatch `_published_md_text_for` to record calls
  and assert it is not called for stamped parts on the second build).
  - Run: `python3.12 -m pytest tests/test_search_index.py -k skip_stamped -v` → passes.
- Existing index-build behaviour unchanged:
  - Run: `python3.12 -m pytest tests/test_search_index.py -q` → the incremental/idempotent-build tests
    still pass (a rebuild changes nothing).

## STOP conditions

- If `_published_md_candidates` does **not** actually do filesystem work to produce candidates (i.e. the
  probe is already only in `_published_md_text_for`), then the fix is purely moving the `:1401` membership
  test earlier is pointless — instead push the anti-join into the SQL. If you cannot express the anti-join
  in the existing query without changing its other consumers, STOP and report the candidate query's shared
  callers.

## Done criteria

- [ ] `python3.12 -m pytest tests/test_search_index.py -k skip_stamped -v` passes.
- [ ] `python3.12 -m pytest tests/test_search_index.py -q` passes.
- [ ] A second build with zero new transcripts performs no filesystem probe for already-stamped parts
      (evidenced by the skip_stamped test).
- [ ] `git diff --check -- src/bili_asr/search_index.py tests/test_search_index.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/search_index.py tests/test_search_index.py` — if either file changed, re-open the excerpt and confirm the candidate/probe shape still matches.
