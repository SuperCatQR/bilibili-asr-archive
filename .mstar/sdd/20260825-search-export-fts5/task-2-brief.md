### Task 2: Export + integration

- [ ] `bili-asr export --format json|csv` writes manifest-derived rows (no transcript bodies by default).
- [ ] `--with-text` includes transcript text; never includes credentials/signed URLs.
- [ ] README documents search/export, rebuild, and manifest-as-SSOT boundary.

Run: focused tests + full suite exit 0.

## Acceptance Criteria

- `bili-asr search <query>` returns ranked matches from completed transcript metadata only; no hits → exit 1 with a clear message.
- `bili-asr export --format json|csv` writes manifest-derived metadata; `--with-text` is opt-in for transcript bodies.
- Rebuild is idempotent; stale detection is documented; search/export never modify the manifest.
- No credentials/signed URLs/raw exceptions in index or output. Meilisearch is out of scope.
- Full Python 3.12 suite passes; no live HTTP. If FTS5 is missing in stdlib, fail with an environment prerequisite (no silent skip of core behavior).

## STOP Conditions

- FTS5 unavailable in target stdlib build → STOP and document environment prerequisite (no silent skip of core behavior).
- Search requires manifest changes to be useful → STOP, keep manifest SSOT.

## Prepare → Execute Handoff

Index coverage is locked to completed transcript rows (`archived` / `subtitle_done` with archive paths). Execute index build first, then search/export surfaces (`--with-text` opt-in; stale detection as specified).

## Durable Review Summary

(Filled after QC/QA.)
