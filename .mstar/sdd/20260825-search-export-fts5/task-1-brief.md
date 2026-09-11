### Task 1: Index build + search

- [ ] `SearchIndex.build(manifest)` indexes only **completed transcript** rows: `archived` or `subtitle_done` **with transcript/archive paths present**. `audio_ok` without transcripts is not searchable as complete.
- [ ] `bili-asr search` queries FTS5 with ranking; bounded `--limit`; no results → exit 1 with clear message.
- [ ] Rebuild idempotent; stale detection documented.

Run: focused `tests/test_search_index.py` passes (stdlib sqlite3 FTS5 available; skip-if-unavailable handled explicitly, not silently).

