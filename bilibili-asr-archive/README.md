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

## Deterministic verification baseline

Run the supported baseline from `bilibili-asr-archive/` with Python 3.12. The
repository supplies a reviewed empty snapshot fixture; before an operator run,
prepare the reviewed, curated local wheel directory (`/path/to/reviewed-wheels`) containing exactly the complete dependency closure (one compatible wheel per distribution, including build, runtime, and `dev` requirements):

    python3.12 scripts/prepare_offline_baseline_fixture.py --wheel-source /path/to/reviewed-wheels --output .offline-baseline
    python3.12 scripts/verify_baseline.py --offline-packages .offline-baseline --advisory-snapshot tests/fixtures/advisories-empty.json

The baseline creates a disposable isolated virtual environment, installs the
local package with its declared `dev` extras using only the specified local
package source (`PIP_NO_INDEX=1`), runs the installed `bili-asr --help` proof,
then runs the complete product pytest suite from a staged test and documentation tree; installer self-tests (`test_cli_help.py`, `test_installed_cli.py`, and `test_verify_baseline.py`) are intentionally excluded because they provision the verifier and would recurse. During pytest it installs a process-level Python socket API deny guard: calls through `socket.create_connection`, `socket.socket.connect`, or `connect_ex` in that pytest interpreter raise before reaching the OS. This is not a host or kernel firewall, and it does not claim to block non-Python processes or every possible networking mechanism.
It also strips `PYTHONPATH`, proxy variables, and `BILI_SESSDATA`; it never
calls Bilibili, downloads a model, transfers media, or prints environment
values. Its compact machine-readable result is
written to `verification-results/baseline.json` and is deliberately gitignored.

### Security-audit policy

Security inspection is deliberately offline and fails closed. The baseline uses
only a reviewed, versioned local advisory snapshot; it does not invoke
`pip-audit` or query a live advisory database. Each advisory's PEP 440
`specifier` is checked against the installed distribution version. Unsupported
specifiers and missing required inputs return exit `2` with
`status: prerequisite_failed` in the JSON result. Audit findings fail the
baseline and must be evaluated in a separate remediation plan with evidence—this
baseline does not upgrade dependencies merely to silence an audit.

For a deterministic repository proof, the guarded developer command constructs
the disposable local offline package set and runs the exact command above:

    python3.12 scripts/prepare_offline_baseline_fixture.py --wheel-source /path/to/reviewed-wheels --output .offline-baseline --run

Generated output is redacted and bounded: no credentials, signed URLs, raw
exceptions, model artifacts, media, archive data, or environment dumps belong
in committed files or CI artifacts.

## Workflow

    bili-asr fetch-meta --mid 23191782 --resume
    bili-asr harvest-subs --archive-root archive
    bili-asr download-audio --missing-subs --archive-root archive
    bili-asr asr --pending --archive-root archive
    bili-asr status --archive-root archive
    bili-asr runs --limit 10 --archive-root archive
    bili-asr pilot --n 20 --archive-root archive
    bili-asr search "黑格尔 辩证法" --archive-root archive
    bili-asr export --format json --out archive/manifest.json --archive-root archive
    bili-asr coverage --archive-root archive
    bili-asr coverage --quality --archive-root archive
    bili-asr run --scope pending --archive-root archive
    bili-asr run --scope pending --offline --archive-root archive
    bili-asr run --scope failed --limit 5 --archive-root archive
    bili-asr schedule --scope pending --limit 20 --archive-root archive
    bili-asr schedule --scope pending --limit 20 --resume --archive-root archive

### Audio reclaim and bounded-disk campaigns

Once a row reaches `archived`, its local audio file under
`{archive-root}/audio/` is deleted automatically (failed and in-progress
rows keep their audio for retry; the manifest may still record the
relative `audio_path` — consumers treat the file as absent).

`pilot` and `run` honor a bounded-disk campaign cap:

    bili-asr pilot --n 20 --max-audio-gb 10 --max-duration-min 45 --archive-root archive
    bili-asr run --scope pending --max-audio-gb 10 --archive-root archive
    bili-asr schedule --scope pending --limit 20 --max-audio-gb 10 --archive-root archive

- `--max-audio-gb` (default 10, `0` = unlimited): before each audio
  download, current `audio/` usage plus a conservative estimate
  (`duration_s` × 64 kbps) is checked; a candidate that would breach the
  cap is **skipped with reason `audio_budget`** and the batch continues.
- `--max-duration-min` (pilot only, default 45, `0` = unlimited):
  excludes long items (e.g. multi-hour livestreams) from selection.

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

Every `fetch-meta` execution (exit 0 or 2) and every `pilot` / `run` /
`schedule` run atomically appends an inspectable run record to
`{archive-root}/run-ledger.jsonl`.
The ledger is a sidecar file that records execution history and coverage
without altering manifest row schemas or the transport layer.

#### Ledger record schema

Each JSONL line represents one immutable record with the following schema:

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Opaque identifier (`run-YYYYMMDDHHMMSS-<token>`). |
| `command` | `str` | Command executed (`fetch-meta`, `pilot`, `run`, `schedule`). |
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
- **`bili-asr coverage [--quality]`** is a read-only reconciliation and artifact quality report over fixture/local archive evidence. Use a temporary local root and optional scope; it never performs network traffic, model invocation, audio transcoding, or writes to source sidecars:

      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --scope pending --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --format csv
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --quality --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --quality --format csv

  `--format json|csv` is deterministic (stable keys/columns and work-id ordering). The denominator is the selected manifest snapshot in work-item units; if the manifest or scope is unavailable, the report says `unavailable` and does not infer a count. `cumulative` describes all selected manifest rows, while `batch` describes only the latest scheduler/ledger batch; they are not interchangeable. `limited` and `risk_interrupted` evidence remains non-complete. Named diagnostics (for example `denominator_unavailable`, `scheduler_ledger_mismatch`, `sidecar_malformed`, or `terminal_missing_artifact`) make contradictions explicit and produce exit `1`; exit `0` means no diagnostics, while usage/configuration errors also exit `1`. Reports redact credentials, signed URLs, media, models, and raw exceptions. Use only reviewed local fixtures or a disposable temporary archive root; coverage is an inspection projection and does not mutate any source sidecar.

  **Subtitle and transcript artifact quality signals (`--quality`)**:
  - Subtitle-first quality provides **deterministic artifact validation only**; it explicitly makes **no claim of semantic correctness**, grammar correctness, or language fluency.
  - Reason codes are bounded and frozen: `empty` (empty artifact body/lines), `malformed` (unparseable SRT/JSON structure or non-finite timestamp), `non_monotonic` (out-of-order cue timestamps), `overlap` (overlapping cue intervals), `out_of_range` (negative time or cues exceeding known duration), `identity_mismatch` (work_id/bvid mismatch between manifest and artifact stem/frontmatter), and `artifact_missing` (referenced or inferred transcript files missing on disk or outside archive root).
  - **Reclaimed audio acceptance**: When valid transcript artifacts (`.srt`, `.txt`, `.md`, or `.json`) exist on disk for an `archived` entry, absent audio files under `audio/` are recognized as expected post-archive reclaimed disk state and are **not reported as defects**.
  - **Read-only boundary**: Quality inspection never mutates manifest row status, risk tokens, sidecars, or transcript files. It executes zero live network requests and requires no ASR model.
  - **Exit semantics**: Exits `0` when all scoped artifacts pass validation without defects or diagnostics; exits `1` when any artifact defect reason or telemetry diagnostic is present, or on configuration/usage error.


`bili-asr run` coordinates manifest rows through four stages — `harvest`
(probe + download subtitles), `download` (fetch audio), `asr` (local
SenseVoice), `archive` (write `srt`/`txt`/`md`) — composing the same live
seams as the single-purpose commands. It **complements** the frozen
`bili-asr pilot` MVP-proof command; it does not replace it.

    bili-asr run --scope pending|failed|<work_id>... [--offline] [--limit N] [--archive-root <root>]

- **Scope**: `pending` selects all non-terminal processable rows; `failed`
  re-selects rows with a recorded failed stage attempt; otherwise one or
  more `work_id`/bvid selectors (comma- or space-separated). Reruns skip
  already-terminal rows (`archived` / `gone`).
- **Stage-attempt ledger**: every executed stage atomically appends a
  record to `{archive-root}/coordinator/attempts.jsonl` (sidecar JSONL;
  the manifest schema is untouched). Fields: `stage`, `work_id`,
  `attempt` (per work/stage counter), `outcome` (`ok` / `failed` /
  `skipped`), `error_code` (redacted scalar only), `artifact_paths`
  (relative), `started_at` / `finished_at`. Credentials, signed URLs, and
  raw exception text are never persisted; a crash leaves no partial line.
  Note: `skipped` records carry their skip reason in `error_code` (e.g.
  `offline`, `missing_audio`) — the field set is locked, so `error_code`
  doubles as the skip-reason channel.
- **Failure summary**: each run prints one line per failed row (with its
  redacted error code) to stderr and one `skipped (reason)` line per
  skipped row to stdout. Per-item CDN/ASR failures are recorded and the
  batch continues.
- **Exit codes**: 0 all selected rows processed; 1 scope-resolution error
  (printed before any batch output; no run-ledger record is written),
  per-item failure, or scope not fully processed (e.g. offline skip from
  missing on-disk input); 2 risk-control ceiling (re-run to resume).

#### Offline mode and the live-vs-deterministic boundary

`--offline` splits live-risk operations from deterministic local
processing. It **never issues HTTP**: the `harvest` and `download` stages
(always network) are not invoked. Only what already exists on disk is
reprocessed:

- a row with subtitle raw JSON at
  `{archive-root}/subtitles/raw/{stem}.json` is re-archived with
  `source=subtitle` (no ASR);
- a row with audio at `{archive_root}/audio/{stem}.m4a` (or a `.flac`
  sibling, or the manifest's `audio_path`) runs local `transcribe` and
  archives with `source=asr`;
- any other row is `skipped` with a reason (`offline` for rows that still
  need harvest, `missing_subtitle_raw` / `missing_audio` for rows whose
  artifact vanished) and the run exits 1 because the scope was not fully
  processed. Nothing is silently re-downloaded.

### Bounded corpus scheduler (`bili-asr schedule`)

`bili-asr schedule` walks the existing manifest sequentially in explicit
batches. It composes `RunCoordinator`, `ManifestStore`, `MetaCursorStore`,
and `RunLedger`; it does not open sockets itself and does not replace
`pilot` or `run`.

    bili-asr schedule --scope pending|failed|<work_id>... --limit N [--resume] [--max-audio-gb G] [--allow-long-live] [--archive-root <root>]

- **`--limit N` is required.** A bounded call never infers that the visible
  corpus is fully archived.
- **Scope** matches `run`: `pending` (non-terminal rows), `failed` (rows
  with a recorded failed stage attempt), or explicit `work_id`/bvid
  selectors. Terminal `archived` / `gone` selectors skip with
  `already_terminal` and exit 0.
- **Batch state** is persisted at `{archive-root}/scheduler.json` as
  `complete` (this call visited every currently matching scope row
  after the default duration filter), `limited` (the explicit limit
  **or** a default long-duration hold left matching rows unselected),
  or `risk_interrupted`. `complete` is requested-scope completion, not
  corpus completion; held multi-hour rows stay pending and keep the
  batch `limited` until `--allow-long-live`. The summary always prints
  the meta-cursor enumeration state so a `limited` crawl cannot
  masquerade as done.
- **`--resume`** consumes only a matching-scope `risk_interrupted`
  sidecar whose long-live policy matches. The sidecar stores
  `allow_long_live`; resume without that flag refuses and leaves a valid
  risk token untouched. Deliberate `limited` / `complete` states, a
  missing sidecar, or a corrupt sidecar are ignored with a stderr reason
  and are not auto-resumed. `processed_work_ids` keeps only `ok` /
  `already_terminal` rows so budget/offline/missing-artifact skips stay
  retryable. Persist failure prints a redacted error and does not tell
  the operator to `--resume`.
- **Exit codes** follow the mixed-outcome contract: 0 requested rows
  processed or already terminal; 1 usage/config, per-item failure, or
  non-risk skip; 2 risk/API interruption (re-run with `--resume`).
- **Long-live opt-in.** Default `pending` / `failed` selection keeps the
  same 45-minute short-video policy as `pilot`. A multi-hour row is
  processed only with `--allow-long-live` and a configured
  `--max-audio-gb` (default 10; `0` is refused on this path). The summary
  prints the conservative 64 kbps estimate, measured `audio/` peak, and
  post-archive usage after reclaim. Operator steps for Windows WSL,
  archive-root placement, cookie boundary, `du` measurement, and redacted
  evidence are in `docs/wsl-long-live.md` and
  `docs/wsl-long-live-evidence.md`. Do not raise `pilot --max-duration-min`
  to sneak livestreams into the short-video campaign.

### SQLite FTS5 full-text search and metadata export

The JSONL manifest (`{archive-root}/manifest/manifest.jsonl`) remains the single source of truth (SSOT). Both `search` and `export` are read-only commands that never modify or rewrite the manifest ledger.

#### Full-text search (`bili-asr search`)

`bili-asr search <query>` queries a lightweight local SQLite FTS5 read index (`{archive-root}/search.db`) built on demand from completed transcript metadata (`archived` or `subtitle_done` with archive paths present). Incomplete entries (`meta_ok`, `needs_audio`, `audio_ok`) are not searchable as complete transcripts.

    bili-asr search <query> [--limit N] [--rebuild] [--archive-root <root>]

- **Ranking**: Matches are ranked by BM25 relevance score over `work_id`, `title`, `status`, and full transcript text.
- **Stale detection**: Automatically verifies whether `search.db` is missing, older than `manifest.jsonl`, or has row count mismatch, rebuilding on demand.
- **Idempotent rebuild**: `--rebuild` forces a clean atomic index rebuild.
- **No hits**: Exits `1` with a clear message when no matching records are found.
- **Environment**: Uses standard library `sqlite3` FTS5; fails with a clear message if SQLite in the environment lacks FTS5 extension support.

#### Metadata and transcript export (`bili-asr export`)

`bili-asr export` serializes manifest-derived records into structured JSON or CSV format without touching the manifest or calling external APIs.

    bili-asr export --format json|csv [--out <path>] [--status <status>] [--with-text] [--archive-root <root>]

- **Deterministic read projection**: JSON and CSV output is 100% byte-stable across repeated invocations, sorting stably by `(bvid, page_index, work_id)` with standard column ordering (`STANDARD_CSV_COLUMNS`).
- **Formats**: `--format json` (formatted JSON array) or `--format csv` (standard CSV with UTF-8 encoding).
- **Transcript bodies**: By default, exported rows contain metadata only (no transcript bodies). Specify `--with-text` to include full transcript text bodies under `transcript_text`.
- **Status filtering & coverage explanation**: `--status <status>` filters records by manifest status (repeatable or comma-separated, e.g. `--status archived,subtitle_done`). Incomplete records (`meta_ok`, `needs_audio`, `audio_ok`, `pending`, `gone`) retain their honest manifest status and have empty `transcript_text` rather than claiming false completion or being silently omitted.
- **Output destination**: Writes to standard output by default, or to `--out <path>` (creating parent directories if needed and writing atomically).
- **Security & path safety**: Credentials (`SESSDATA`, cookies, auth tokens), signed streaming URLs, raw exceptions/tracebacks, and sensitive URL query parameters are strictly excluded and redacted. Filepath fields are validated against `archive_root` to prevent directory traversal or outside-root path exposure.
- **Vocabulary**: Consistently uses manifest `status` (never cursor `state`).
- **Decoupled from search index**: Export operates directly over the JSONL manifest SSOT and does not require, query, or mutate `search.db`.

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

### Mixed batch outcomes

When `harvest-subs`, `download-audio`, `asr`, `pilot`, `run`, or `schedule`
processes more than one work item, the process exit code is an aggregation of
per-item outcomes — not a claim that the whole corpus is complete. `pilot`
remains the frozen two-branch proof command; `run` remains complementary;
`schedule` consumes this same taxonomy.

| Exit | Meaning |
|------|---------|
| 0 | Requested work processed, or every selected row is already terminal (`archived` / `gone`). |
| 1 | Usage/config error, missing optional ASR, per-item failure, or incomplete scope from a non-risk skip (`offline`, `audio_budget`, missing on-disk input). |
| 2 | Risk/API terminal interruption. Successful rows and artifacts stay; retry the remaining work. |

Risk interruption takes precedence over per-item failure: a batch that
archived some rows and then hit the risk ceiling still exits 2.

Successful rows stay in their last stable status. Retryable failures remain
selectable by the same command or by `run --scope failed`. Explicit `run
--scope` work_id selectors of already-terminal rows skip with
`already_terminal` and exit 0; they are not duplicated.

`harvest-subs`, `download-audio`, and `asr` do not append `run-ledger.jsonl`
(that sidecar is `fetch-meta` / `pilot` / `run` / `schedule`). All operator
surfaces carry redacted scalar codes/reasons only.

### Corpus coverage iteration contracts

The iteration package at `.mstar/iterations/iter-2026-08-corpus-coverage/` defines six business slices: bounded campaign execution, cumulative coverage reconciliation, subtitle/artifact quality signals, local transcript exploration, integrity/recovery, and a concurrency safety gate. These are product contracts and plans, not claims that the corresponding future behavior is already shipped.

The target state is an auditable sequential workflow: the manifest remains SSOT; reports are read-only projections; bounded batches never imply full-corpus completion; reclaimed audio is valid after transcript archival; and semantic transcript correctness is out of scope. The concurrency slice is a no-go-by-default evidence gate and does not enable workers or a daemon. Any later implementation must satisfy the plan's fixture-only verification, redaction, explicit denominator, stable output, and frozen exit/status boundaries.

The roadmap is explicit: first establish campaign and telemetry evidence, then quality, explorer, and integrity contracts, and finally evaluate concurrency. A later iteration may implement only a mode allowed by a passing safety gate and a separately approved plan.

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
