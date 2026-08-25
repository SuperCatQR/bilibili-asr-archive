# bilibili-asr-archive

Personal archival CLI for Bilibili UP 未明子 (UID 23191782) ASR transcripts.

Enumerates videos, harvests AI/CC subtitles first, downloads audio only when
needed, runs local SenseVoice ASR, and archives `srt` / `txt` / `md` with a
resumable JSONL manifest.

## Install (editable)

Base metadata/subtitle/audio workflows:

    py -3.12 -m pip install -e ".[dev]"

Local SenseVoice support is optional because it downloads model weights on first
use:

    py -3.12 -m pip install -e ".[asr]"

Set `BILI_ASR_MODEL` to a pre-populated local model directory for offline use;
the default is `iic/SenseVoiceSmall`. No model weights are vendored.

## Workflow

    bili-asr fetch-meta --mid 23191782 --resume
    bili-asr harvest-subs --archive-root archive
    bili-asr download-audio --missing-subs --archive-root archive
    bili-asr asr --pending --archive-root archive
    bili-asr status --archive-root archive
    bili-asr runs --limit 10 --archive-root archive
    bili-asr pilot --n 20 --archive-root archive

Subtitle access that requires login can use `BILI_SESSDATA` or the
`--sessdata` flag (cookie **value**, not a file path). Credentials are sent as
API cookies only and are never echoed or written to the manifest or output
files.

`bili-asr pilot --n N` (default 20) selects a bounded mix from `meta_ok` (and
still-processable `subtitle_done` / `needs_audio` / `audio_ok` for resume),
preferring short `duration_s` and reserving both branches when those statuses
already exist. Each selected row harvests subtitles first: a subtitle hit is
archived with `source=subtitle` and no ASR; a miss downloads audio, runs local
SenseVoice, and archives with `source=asr`. Multi-part bvids include every
pagelist `work_id`. The summary prints branch counts and terminal states.
Missing subtitle or audio-asr coverage exits 1 and names the missing branch.
A completed rerun skips work already `archived`. Missing optional ASR exits
non-zero with `pip install -e "bilibili-asr-archive/[asr]"` and does not mark
the row archived.

### Operational run ledger (`run-ledger.jsonl`), `status`, and `runs`

Every `fetch-meta` execution (exit 0 or 2) and every `pilot` run atomically
appends an inspectable run record to `{archive-root}/run-ledger.jsonl`.
The ledger is a sidecar file that records execution history and coverage
without altering manifest row schemas or the transport layer.

#### Ledger record schema

Each JSONL line represents one immutable record with the following schema:

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Opaque identifier (`run-YYYYMMDDHHMMSS-<token>`). |
| `command` | `str` | Command executed (`fetch-meta`, `pilot`, `run`). |
| `started_at` | `str` | ISO-8601 UTC start timestamp. |
| `finished_at` | `str` | ISO-8601 UTC completion timestamp. |
| `exit_code` | `int` | Process exit code (`0`, `1`, or `2`). |
| `mid` | `int \| null` | Target Bilibili mid (if applicable). |
| `work_ids` | `list[str] \| null` | Processed work identifiers (if applicable). |
| `pages_fetched` | `int \| null` | Number of pagination pages fetched. |
| `records_fetched` | `int \| null` | Number of records fetched in the run. |
| `records_existing` | `int \| null` | Number of pre-existing records before run. |
| `last_api_error_code` | `int \| str \| null` | Scalar API response code on failure (never exception text). |
| `coverage_summary` | `dict[str, int]` | Snapshot of manifest `status` counts (`archived`, `meta_ok`, etc.). |
| `cursor_snapshot` | `dict \| null` | Snapshot of `meta-cursor.json` state at run completion. |

Like `meta-cursor.json`, the ledger strictly forbids credentials (`SESSDATA`,
cookies), signed streaming URLs, and raw exception stack traces.

#### Operator inspection

- **`bili-asr status [--archive-root <root>]`** displays current per-status
  manifest row counts, unresolved legacy identifiers, total run count, and
  latest run details (run ID, exit code, cursor snapshot, and coverage
  summary). For `limited` enumeration runs, it reports cursor state honestly
  without claiming complete enumeration.
- **`bili-asr runs [--limit N] [--archive-root <root>]`** lists recent
  operational runs in chronological order with exit codes, cursor state,
  coverage snapshots, and completion timestamps.

### `fetch-meta --resume` and exit 2

`bili-asr fetch-meta` writes `{archive-root}/meta-cursor.json` after each
successful archive-list page merge. The sidecar holds only `mid`, `next_page`,
`total`, `state`, `last_api_error_code`, and `updated_at` — never cookies,
`SESSDATA`, signed URLs, or exception text.

| Exit | Meaning |
|------|---------|
| 0 | Run finished without risk exhaustion. Cursor `state` is `complete` (full visible archive) or `limited` (intentional `--limit-pages` cap). `--resume` does **not** auto-continue these. |
| 1 | Usage/config or unexpected error (no traceback). |
| 2 | Risk budget or terminal API failure. Cursor `state` is `risk_interrupted`; `next_page` is the 1-based `pn` that was **not** merged. Re-run `fetch-meta --resume` with the same `--mid` to start at that page. |

`--resume` auto-continues **only** an exit-2 `risk_interrupted` cursor whose
`mid` matches. `complete` and `limited` are not auto-resumable. JSONL upsert
stays last-write-wins per `work_id`; a failed page is never marked complete.
Without `--resume`, a new run starts at page 1, merges the existing JSONL
(does not shrink it to a page-1 prefix), and replaces a leftover cursor after
the first successful page. Mid-run sidecar writes stay `risk_interrupted`
with `next_page` = last merged `pn+1`; terminal `complete`/`limited` is
written only when the run finishes without exit 2.

Exit codes for other commands: 0 ok / 1 usage-config or per-video failure / 2
terminal API failure.

## Multipart pages and legacy rows

Automatic enumeration writes one manifest row per page (`work_id` =
`{bvid}:p{page_index}`). Filesystem names use `artifact_stem`
(`{bvid}.p{page_index}`) so raw/SRT/audio/transcripts never collide across
pages. Public URLs for `page_index` > 0 include `?p=` (1-based).

Legacy single-page rows migrate only when ownership is unambiguous. Ambiguous
bare-bvid rows stay `unresolved` / `excluded_from_page_processing`: they keep
their original key and files, stay visible in `bili-asr status`, and are never
auto-assigned a page. `download-audio --bvid` / `asr --bvid` STOP on those
rows instead of fabricating a `needs_audio` page. Resume is per `work_id`: a
completed or failed p0 does not skip p1.

No media redistribution; personal archival only.
