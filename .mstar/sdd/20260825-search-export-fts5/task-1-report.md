# Task 1 Report: Index build + search

- Status: DONE
- Working branch: `plan/20260825-search-export-fts5`
- Base SHA: `cffe0f1de6ecc8a9d75060ebebb6db0b3a9fb2ce`
- Commit: `cb7ff6069c76b443e682bb2b64cfcd03daedad99` (`feat(search): implement SQLite FTS5 SearchIndex and bili-asr search command`)

## Implemented / Attempted

1. **`SearchIndex(root)` (`src/bili_asr/search_index.py`)**:
   - Manages `{archive_root}/search.db` with SQLite FTS5 virtual table `transcripts_fts` over columns: `work_id`, `title`, `status`, `transcript_text`, `archive_paths`, `duration_s`.
   - `build(manifest)` filters and indexes **only completed transcript rows**: status in `{"archived", "subtitle_done"}` with transcript/archive paths present (`srt_path`, `txt_path`, `md_path`, `raw_path` in metadata or on disk). Non-completed rows (`audio_ok`, `needs_audio`, `meta_ok`, `pending`, `gone`) and rows without transcript artifacts are excluded from indexing.
   - Text extraction supports text files (`transcripts/txt/{stem}.txt`), subtitle files (`transcripts/srt/{stem}.srt` with timestamp/index filtering), and raw JSON structures (`subtitles/raw/{stem}.json` and `transcripts/raw/{stem}.json`).
   - Atomic and idempotent rebuild using SQLite temporary file (`search.db.tmp` -> `os.replace`).
   - Stale detection in `is_stale()` comparing `search.db` existence, `manifest/manifest.jsonl` mtime vs `search.db` mtime, and completed transcript count vs indexed row count.
   - SQLite FTS5 availability prerequisite check with `FTS5UnavailableError` (no silent skip of core indexing behavior).
   - Zero network / HTTP imports in `search_index.py` (strict module boundary preserved).

2. **CLI `bili-asr search <query>` (`src/bili_asr/cli.py`)**:
   - Subcommand `search` added to `build_parser()`.
   - Flags supported: `<query>`, `--limit N`, `--rebuild`, `--archive-root PATH`.
   - Automatically builds search index if missing or stale; `--rebuild` forces a complete rebuild.
   - Queries FTS5 with BM25 ranking (`ORDER BY rank`) and safe query syntax fallback.
   - Outputs matching rows: `{work_id}: {title} [{status}] (score: {score:.4f}, path: {path})` and exits 0.
   - Returns exit 1 with clear stderr message (`search: no matching transcripts found for ...`) when no results are found.
   - Returns exit 1 with clear environment prerequisite error if SQLite lacks FTS5.

3. **Focused Test Suite (`tests/test_search_index.py`)**:
   - 23 focused unit and integration tests covering: FTS5 prerequisite check, uninitialized index behavior, filtering of completed vs uncompleted rows (`audio_ok`/`needs_audio`/`meta_ok` excluded), idempotent rebuilds, manifest immutability during search/build, search by transcript text / title / work_id, BM25 ranking, limit bounding, syntax error safety, CJK / Chinese query matching, raw subtitle / ASR JSON fallback extraction, legacy bare-bvid support, stale detection transitions, CLI search exit codes (0 on hits, 1 on no hits, 1 on missing args), auto-build, `--rebuild`, and explicit FTS5 unavailability error handling.

## Tests

### Commands & Results

1. Focused tests:
```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_search_index.py -q
# Output: 23 passed in 0.36s
```

2. Full test suite:
```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
# Output: 241 passed in 4.53s
```

### Red / Green Evidence
- Initial test run demonstrated collection and mock execution failure handling.
- Final test run passed 23/23 tests in `tests/test_search_index.py` and 241/241 tests in the full suite with 0 failures, 0 regressions.

## Files Changed

- `src/bili_asr/search_index.py` (new): `SearchIndex`, `SearchResult`, `FTS5UnavailableError`, `check_fts5_available`
- `src/bili_asr/cli.py`: added `search` subcommand parser, `_cmd_search`, and dispatch in `main()`
- `tests/test_search_index.py` (new): comprehensive unit and CLI integration tests for indexing and search

## Self-Review Notes

- Manifest remains SSOT: `ManifestStore` is read-only during build and search; no `upsert` or modification to `manifest.jsonl` occurs.
- No new runtime dependencies: uses stdlib `sqlite3` only.
- No credentials, signed URLs, or raw stack traces in index or CLI output.
- Surgical changes: only Task 1 deliverables implemented; Task 2 (export + README) untouched.
