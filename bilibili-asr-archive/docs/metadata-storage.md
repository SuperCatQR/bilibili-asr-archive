# Metadata storage (`archive.db`)

Normalized SQLite storage for the video metadata collected by
`bili-asr fetch-meta`. This document describes the database the metadata CLI
creates and reads. The legacy JSONL manifest pipeline
(`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) is a
separate, untouched state: the metadata commands never read it, and no
command migrates old data into the new database.

## Fresh-start behavior (no migration)

- `fetch-meta` creates `{archive_root}/archive.db` when it does not exist and
  initializes the checked-in schema (`src/bili_asr/storage/schema.sql`).
- `status` and `runs` are read-only. When the database is missing they fail
  with a clear configuration error and exit `1`; they never create it.
- There is no migration, import, reset, or rewrite path. Deleting
  `archive.db` is the only way to restart a collection from page 1; old
  archive data is never discovered, read, or modified by any command.
- A failed page never advances the cursor: resume is always safe, and no
  partially written page payload survives a failure.

## Database layout

One SQLite file at `{archive_root}/archive.db`. Foreign keys are enforced
(`PRAGMA foreign_keys = ON`).

### Normalized entity tables

| Table | Key | Contents |
|-------|-----|----------|
| `bilibili_users` | `mid` | The collected user and its current display label. |
| `videos` | `bvid` | One row per video: `aid`, owner `mid` (FK to `bilibili_users`), `title`, `pubdate`. |
| `video_parts` | `(bvid, page_index)` | One row per part: `cid`, part `title`, `duration_ms`, zero-based `page_index` (`{bvid}:p{page_index}` is the derived `work_id`, computed, never stored), `processing_status` (`discovered`, `metadata_collected`, `gone`), FK to `videos`. |

### Ingestion process tables

| Table | Key | Contents |
|-------|-----|----------|
| `ingestion_runs` | `run_id` | One row per collection run: target `mid`, source package and version, requested start page and page limit, `started_at` / `finished_at`, terminal `outcome` (`complete`, `limited`, `risk_interrupted`, `failed`). |
| `ingestion_pages` | `(run_id, page_number)` | One evidence row per requested page: `outcome` (`ok`, `empty`, `risk_interrupted`, `failed`) and a bounded scalar `error_code` on failure. |
| `ingestion_cursors` | `mid` | The resumable one-based cursor: `next_page`, `state` (`ready`, `complete`, `limited`, `risk_interrupted`), `observed_total`. |
| `ingestion_discoveries` | `(run_id, page_number, bvid)` | Run-scoped discovery evidence linking a run page to a discovered video. |

### Reserved media boundary (empty in this plan)

`audio_objects`, `part_audio_objects`, `asr_models`, `transcripts`, and
`transcript_segments` are created now so later media and transcript plans
attach through these foreign keys instead of reintroducing sidecars. They
stay empty in this plan; no media bytes or transcripts are written yet.

### Views

| View | Contents |
|------|----------|
| `v_video_parts` | Every part with its derived `work_id` and the joined user/video context. |
| `v_ingestion_run_stats` | Per-run page and video counts (the `runs` command's source). |
| `v_pending_metadata` | Parts with `processing_status = 'discovered'` (the `status` command's pending work). |

## No-JSONL contract

`fetch-meta`, `status`, and `runs` never read or write `manifest.jsonl`,
`meta-cursor.json`, or `run-ledger.jsonl`. All persisted run/page evidence
is scalar: `error_code` values are bounded strings of at most 64 characters
from a restricted character set. Credentials, signed URLs, raw response
bodies, and raw exception text never enter CLI output, logs, or any
persisted row.

## Credential boundary

The optional SESSDATA credential comes from `--sessdata` or the
`BILI_SESSDATA` environment variable (flag wins). It is passed to the
gateway's cookie object only: never echoed, logged, persisted, or rendered —
CLI output shows presence only (`sessdata: present|absent`). Omitting it
means anonymous access.

## `observed_total` semantics

- `ingestion_cursors.observed_total` records the upstream video total
  reported by the page response (`page.count`) when it is present; it is
  provenance about the upstream snapshot, not a completion proof.
- The fake test gateway reports a per-page count (its scripted responses
  carry the scripted page size); live runs record the upstream global total.
- Run completion keys off the empty item list: the first page that returns
  no videos ends the run `complete` (bounded, spec-defined). An explicit
  `--limit-pages` bound ends the run `limited` instead — never claimed as
  complete.

## Exact bounded live smoke command

```
cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v
```

- Opt-in only (`BILI_LIVE_SMOKE=1`); default pytest runs skip it without
  failure. An opted-in run without the pinned `bilibili-api-python==17.4.2`
  distribution fails loudly with install guidance instead of skipping.
- Bound: exactly one public metadata page for UID 23191782
  (`--start-page 1 --limit-pages 1`) into a temporary archive root; no
  subtitle/playback/audio/ASR code is invoked and nothing outside the
  temporary root is written.
- Anonymous (no-credential) access is currently rejected by upstream
  anti-bot control: the smoke then verifies the bounded-failure evidence
  (terminal run row, one scalar page row, no entity growth, no cursor row)
  and reports the case as the expected no-credential behavior — not a
  defect. Happy-path collection requires a credential from the operator's
  own environment (`--sessdata` or `BILI_SESSDATA`); a bounded failure
  despite a credential is a loud failure.

## Exit codes

### `fetch-meta`

| Exit | Meaning |
|------|---------|
| 0 | Successful collection: completed on an empty page, or stopped at the explicit `--limit-pages` bound. |
| 1 | Usage/configuration error: non-positive page arguments, `--resume` with no stored cursor, or an unreadable archive root. |
| 2 | Terminal gateway failure with a bounded scalar code (for example `response_error`, `rate_limited`); the cursor remains unchanged. |

### `status` / `runs`

| Exit | Meaning |
|------|---------|
| 0 | Database read and displayed. An empty database prints `runs: empty`. |
| 1 | Configuration error: the database does not exist (or a non-positive `runs --limit`). |

`runs` lists runs newest-first and includes non-terminal `running` rows: a
crash can leave a stale run behind, and hiding it would hide real state.
