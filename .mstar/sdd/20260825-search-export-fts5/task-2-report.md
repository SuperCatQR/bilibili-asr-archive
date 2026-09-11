# Task 2 Report: Export Command + Integration & Documentation

## Status

DONE

## Working Branch

`plan/20260825-search-export-fts5`

## Implemented / Attempted

1. **Manifest Export Engine (`src/bili_asr/export.py`)**:
   - `export_manifest(archive_root, fmt, out_path, status_filter, with_text)`: High-level entrypoint exporting manifest-derived metadata in JSON (`format_json_export`) or CSV (`format_csv_export`).
   - `export_rows(store_or_entries, status_filter, with_text, archive_root)`: Loads and derives sanitized manifest rows with deterministic sorting (`bvid`, `page_num`, `work_id`).
   - `sanitize_export_entry(entry, with_text, archive_root)`: Strips credentials (`sessdata`, `cookie`, `cookies`, `bili_sessdata`), signed streaming URLs (`url`, `signed_url`, `stream_url`, `audio_url`), and error traces (`traceback`, `exception`, `error_trace`).
   - `--with-text` opt-in: Excludes transcript text bodies by default; attaches full transcript body under `transcript_text` when `--with-text` is specified.
   - Preserves manifest as SSOT: Read-only `ManifestStore.load()`, never rewrites or mutates manifest JSONL.
   - Shared text extraction: Reuses `extract_transcript_text(root, entry)` across `search_index` and `export`.

2. **CLI Integration (`src/bili_asr/cli.py`)**:
   - Added `export` subparser to `build_parser()` with `--format {json,csv}` (required), `--out <path>`, `--status <status>` (repeatable / comma-separated), `--with-text`, and `--archive-root`.
   - Wired `_cmd_export` handling status filter validation against `VALID_STATUSES` with clear error reporting and exit code 1 on invalid filters.
   - Column/flag name is strictly `status` (never cursor `state`).

3. **Documentation (`README.md`)**:
   - Updated CLI workflow with `search` and `export` examples.
   - Added comprehensive documentation section `SQLite FTS5 full-text search and metadata export` covering:
     - Manifest-as-SSOT boundary (manifest never rewritten by search or export).
     - FTS5 full-text search (`bili-asr search <query> [--limit N] [--rebuild]`), BM25 ranking, automated stale detection, idempotent rebuild, and failure taxonomy.
     - Metadata and transcript export (`bili-asr export --format json|csv [--out <path>] [--status <status>] [--with-text]`), output options, and credential security.

4. **Tests (`tests/test_export.py`)**:
   - 12 new comprehensive test cases covering JSON/CSV export formatting, default omission and opt-in `--with-text` transcript bodies, output file writing, single/multi/comma-separated status filtering, invalid status failure (exit 1), manifest immutability, empty manifest handling, credential and signed URL sanitization, legacy bare-bvid export, and invalid format error handling.

## Tests

### Commands
```bash
cd /root/workspace/bilibili-asr-archive/.worktrees/20260825-search-export-fts5/bilibili-asr-archive
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_search_index.py tests/test_export.py -v
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```

### Evidence
- Focused test suite: `35 passed in 0.41s`
- Full test suite: `253 passed in 4.45s`

## Files Changed

- `bilibili-asr-archive/src/bili_asr/export.py` (new): Export module for JSON and CSV formatting, sanitization, and text body attachment.
- `bilibili-asr-archive/src/bili_asr/cli.py`: Added `export` subparser, `_parse_status_filter`, and `_cmd_export`.
- `bilibili-asr-archive/src/bili_asr/search_index.py`: Extracted public `extract_transcript_text` function.
- `bilibili-asr-archive/tests/test_export.py` (new): 12 tests for CLI export surface and formats.
- `bilibili-asr-archive/README.md`: Documented search/export, rebuild, and manifest SSOT boundary.

## Self-Review Notes

- Manifest SSOT: Tested and verified that `bili-asr search` and `bili-asr export` never modify or rewrite `manifest/manifest.jsonl`.
- Data security: All credentials, signed URLs, and exceptions are denied/stripped in export outputs.
- Vocabulary constraint: Uses `status` consistently across arguments, column headers, and docs.
- Commits: Clean commit `2b8dd69` on branch `plan/20260825-search-export-fts5` with no untracked clutter or unapproved lockfiles.

## QC fix round

### Findings addressed

1. **Warning (Connection lifecycle in SearchIndex.count)**:
   - Changed `SearchIndex.count()` from `with sqlite3.connect(...)` context manager to explicit `conn = sqlite3.connect(...)` with `try ... finally: conn.close()` to ensure the SQLite connection is immediately closed.
2. **Suggestion (Redundant manifest JSONL parsing)**:
   - Reordered `SearchIndex.is_stale()` to check `manifest_mtime > db_mtime` first, avoiding parsing/loading the manifest file when stale by mtime.
   - Optimized `cli.py:_cmd_search()` to load manifest once (`manifest = store.load()`) and reuse it across `index.is_stale(manifest)` and `index.build(manifest, force=args.rebuild)`.
3. **Suggestion (Atomic export file write)**:
   - Updated `export.py:export_manifest()` to write to a temporary file (`out_str + ".tmp"`) and atomically commit via `os.replace()`, with exception cleanup removing the `.tmp` file on write or replacement failure.
   - Added unit test `test_export_atomic_out_write_and_cleanup_on_failure` in `tests/test_export.py` and `test_is_stale_mtime_short_circuits_before_load` in `tests/test_search_index.py`.

### Files Changed

- `bilibili-asr-archive/src/bili_asr/search_index.py`: Connection lifecycle in `count()` and mtime short-circuiting in `is_stale()`.
- `bilibili-asr-archive/src/bili_asr/cli.py`: Single-manifest load caching in `_cmd_search()`.
- `bilibili-asr-archive/src/bili_asr/export.py`: Atomic write and failure cleanup in `export_manifest()`.
- `bilibili-asr-archive/tests/test_search_index.py`: Added test for mtime short-circuit without manifest loading.
- `bilibili-asr-archive/tests/test_export.py`: Added test for atomic export output write and failure cleanup.

### Commands & Outputs

```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_search_index.py tests/test_export.py -q
```
```
.....................................                                    [100%]
37 passed in 0.44s
```

```bash
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
```
```
........................................................................ [ 28%]
........................................................................ [ 56%]
........................................................................ [ 84%]
.......................................                                  [100%]
255 passed in 4.40s
```

