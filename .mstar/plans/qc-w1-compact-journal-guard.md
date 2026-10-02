---
plan_id: qc-w1-compact-journal-guard
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# QC W1 — compact() keep journal when snapshot absent
## Status
- **Priority**: P2 · **Effort**: XS · **Risk**: LOW · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: QC finding; `src/bili_asr/manifest.py:354-363` — `compact()` calls `_remove_journal()` outside the `if current:` guard.
## Problem
`compact()` deletes `manifest.journal.jsonl` even when `manifest.jsonl` is absent/empty, losing the only durable copy of journaled rows.
## Approach
Guard `_remove_journal()` behind `if current:` (mirror `migrate_legacy_rows`), OR write the snapshot unconditionally whenever the journal is non-empty. Prefer the guard (smallest).
## Files: `src/bili_asr/manifest.py`; test in `tests/test_manifest.py`.
## Verification: a test where only a journal exists → compact() must not unlink it; `pytest tests/test_manifest.py -q` green.
## Done: guard in place; new test passes; full test_manifest.py green.
