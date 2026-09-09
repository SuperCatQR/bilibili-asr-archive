# Metadata CLI Contract

## Commands

### `bili-asr fetch-meta`

Collects video metadata from Bilibili and writes to `{archive_root}/archive.db`.

**Arguments**:
- `--mid INTEGER`: Bilibili user ID to collect (default: `23191782`)
- `--archive-root PATH`: Local archive directory (default: `archive`)
- `--start-page INTEGER`: Explicit one-based page to start from (overrides cursor)
- `--limit-pages INTEGER`: Stop after collecting this many pages (positive integer)
- `--resume`: Explicitly require cursor; fail if no cursor exists (mutually
  exclusive with `--start-page`)
- `--sessdata VALUE`: Optional credential for authenticated requests (never persisted)

**Cursor behavior**:
- When neither `--resume` nor `--start-page` is given: Resume from the database
  cursor if one exists, otherwise start at page 1.
- When `--resume` is given: Require cursor presence; fail if database has no cursor.
- When `--start-page` is given: Ignore any existing cursor and start at the
  specified page.

**What it does**: Fetches one or more pages of video metadata for the specified
user, normalizes the results, and writes to SQLite. Never reads or writes legacy
JSONL, cursor, or ledger files.

**Exit codes**:
- **0**: Successful collection (reached end or explicit `--limit-pages`)
- **1**: Usage error (bad arguments, missing database when `--resume` requires cursor)
- **2**: Gateway failure after bounded retry (cursor remains unchanged)

A failed page never advances the cursor, so resume is always safe.

### `bili-asr status`

Reads the database and reports current metadata state.

**What it shows**:
- How many users, videos, and parts are discovered
- How many parts need further processing (by `processing_status`)
- What ingestion work is pending

**Exit codes**:
- **0**: Successfully read and displayed status
- **1**: Configuration error (database does not exist at expected path)

Never reads legacy `manifest.jsonl` or sidecar files.

### `bili-asr runs`

Shows ingestion run history from the database.

**What it shows**:
- Run start/finish times (ordered newest first)
- Page counts per run
- Run outcomes (completed, limited, failed)
- Bounded scalar error codes only (no raw errors, no credentials)

**Arguments**:
- `--limit INTEGER`: Show only the N most recent runs

**Exit codes**:
- **0**: Successfully read and displayed runs
- **1**: Configuration error (database does not exist)

Never reads legacy run-ledger files.

## Fresh-start behavior

`fetch-meta` initializes a new database at `{archive_root}/archive.db` when no
 database exists. `status` and `runs` are read-only and fail with a clear
configuration error when that database is missing. No command discovers, reads,
imports, or rewrites the old `manifest/`, `meta-cursor.json`,
`run-ledger.jsonl`, or transcript files.

## Live smoke bound

The test invocation uses a temporary archive root, UID 23191782, and
`--limit-pages 1`. It must not invoke subtitle, playback, audio, or ASR code.

## Acceptance

- Fake gateway E2E passes for one single-part and one multipart video.
- Re-running the same scripted page produces no duplicate entities or discovery
  rows.
- Cursor state advances only after a successful page transaction.
- A failed page leaves the previous cursor and records a bounded page outcome.
- Live smoke creates the expected user/video/part/run/page rows in a temporary
  database.

## References

- Primary plan: `.mstar/plans/20260909-metadata-cli-smoke.md`
- Schema spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/structured-metadata-storage.md`
- Gateway spec: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`

## Status

Iteration-scoped draft; becomes locked after Phase 1 review chain and PM lock.
