---
iteration: iter-2026-08-corpus-coverage
plan_id: 20260828-transcript-explorer
status: implemented
---
# Transcript explorer search/export contract

## Specify
**Value:** research completed transcripts through predictable local search/export. **Target:** bounded stable FTS5 read model with explicit filters, diagnostics, and coverage explanation. **Non-goals:** GUI, remote search, semantic ranking, manifest changes, and archive repair.

## Clarify
- Search/export remain projections; manifest JSONL is SSOT and is never rewritten.
- Filters use fields that already exist; no ambiguous new manifest field is introduced.
- Incomplete rows are explained as excluded, not represented as searchable completed transcripts.

## Architect review

The explorer composes `SearchIndex` and existing export seams; `SearchQuery` filters only existing manifest fields and always enforces a positive bounded limit plus deterministic `(work_id, path)` tie-break. Search/export are read-only projections and never rebuild the manifest; stale-index handling is an explicit diagnostic or separately named rebuild action. Paths are archive-root-relative and snippets are bounded/redacted. FTS5 absence, stale index, and no-hit are distinct diagnostics. Verify: `PYTHONPATH=. uv run --with pytest pytest -q tests/test_search_index.py tests/test_export.py tests/test_cli_help.py`.

## Plan and acceptance
- `SearchQuery` carries explicit status/source/date/duration filters, query text, limit, and deterministic tie-break ordering.
- Search returns bounded path-safe metadata/snippets; no-hit, stale/missing index, and FTS5 absence have named nonzero diagnostics.
- JSON/CSV export has stable field order and coverage summary; repeated output is byte-stable.
- Fixture covers archived/subtitle-only/ASR/incomplete/gone/reclaimed rows, all filters, stale rebuild, no-hit, and read-only manifest behavior without network/model/media.
- Stop if a filter requires a new manifest field or if read-only guarantees fail.
