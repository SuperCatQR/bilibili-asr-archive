# bilibili-asr-archive

Personal archival CLI for Bilibili UP 未明子 (UID 23191782) ASR transcripts.

Enumerates videos, harvests AI/CC subtitles first, downloads audio only when
needed, runs local FunASR-Nano ASR, and archives `srt` / `txt` / `md` with a
resumable JSONL manifest.

## Install (editable)

Base metadata/subtitle/audio workflows (Linux or Windows WSL, Python 3.12+):

    python3.12 -m pip install -e ".[dev]"

Local FunASR support is optional because it downloads model weights on first
use:

    python3.12 -m pip install -e ".[asr]"

### GPU Requirements (AMD 7800XT with ROCm)

Ask the host instead of trusting a command list. Run this from
`bilibili-asr-archive/` — the product directory, not the repository root above
it — with the **same interpreter that holds torch**, which is the venv the
recipe installs into (a `python3.12` probe of the system interpreter reports
`torch-present FAIL` on a correctly built host):

    export VENV=~/.venvs/bili-asr   # the venv that runs bili-asr
    "$VENV/bin/python" scripts/check_asr_env.py

It exits `0` iff all five stages of the verified AMD/WSL recipe hold together,
`1` when any stage fails (printing the fix for each), and `2` for a usage error
(an unrecognised argument; `-h`/`--help` exits `0`):

| # | Stage | Invariant it asserts |
|---|-------|----------------------|
| 1 | `dxg-detection` | `/dev/dxg` exists **and** `HSA_ENABLE_DXG_DETECTION=1` |
| 2 | `rocm-loader-path` | a `/opt/rocm-*/lib` directory is reachable by the dynamic loader |
| 3 | `torch-present` | torch is importable and is a ROCm build (`torch.version.hip`) |
| 4 | `hsa-runtime` | the `libhsa-runtime64.so` in the venv's `torch/lib` is the WSL-compatible system runtime |
| 5 | `device-probe` | a subprocess reports a visible device and its `gcnArchName` (`gfx1101`) |

That check is the only entry point named for "is my GPU usable for ASR". The
verified recipe it asserts — ROCm runtime, ROCDXG transport, the
**repo.radeon.com** torch wheel, the userspace libraries, the loader path, the
WSL-compatible HSA runtime, and `HSA_ENABLE_DXG_DETECTION=1` — plus the three
failure modes measured on 2026-09-12 are in
[docs/wsl-rocm-gpu.md](docs/wsl-rocm-gpu.md). This README deliberately does not
repeat the install commands: the recipe is environment surgery that `docs/`
owns.

**Note**: AMD ROCm uses a CUDA-compatible layer (HIP), so PyTorch still uses
`device="cuda"`. A transcript archived on such a host records that in its own
frontmatter — verify it with

    ARCHIVE=/path/to/your/archive    # the archive root you passed to --archive-root
    grep -n '^asr_device:' "$ARCHIVE"/transcripts/md/*.md

which prints `asr_device: "cuda"`. A glob is required: the markdown bundle is
named `{pubdate}_{bvid}.p{page}_<title>.md`, so there is no `<work_id>.md` to
open. Only `"$ARCHIVE"` is quoted — that keeps an archive root containing spaces
in one word — while `*.md` is left unquoted so the shell expands it into the
bundle filenames `grep` searches.

For CPU-only mode, override device: `BILI_ASR_DEVICE=cpu` (slower, not
recommended for large archives). CPU mode needs none of the five invariants.

For other GPU vendors (NVIDIA, Intel), see the
[PyTorch installation guide](https://pytorch.org/get-started/locally/).

The hardened archive/audio path requires POSIX descriptor operations
(`dir_fd`, `O_NOFOLLOW`, and `/proc/self/fd` or `/dev/fd`). Linux and a
WSL-native filesystem are supported. Native Windows `cmd.exe`/PowerShell paths
are not supported for hardened publication or reclaim; run the CLI inside WSL
and keep the archive on a WSL-native path, not `/mnt/c`.

Set `BILI_ASR_MODEL` to a pre-populated local model directory for offline use;
the default is `FunAudioLLM/Fun-ASR-Nano-2512`. No model weights are vendored. The optional
ASR dependency is verified by fixture-only tests; installation and model
availability remain operator responsibilities.

ASR model construction is lazy and reused only within one sequential `run_batch`
scope. `ASRRunner` is not thread-safe and must not be shared by concurrent callers;
the coordinator releases runners it creates when the batch exits, while an injected
runner remains owned by its caller. `BILI_ASR_MODEL` may be a pre-populated local
path at runtime, but paths are never provenance identifiers. Safe slash-qualified
model identifiers such as `FunAudioLLM/Fun-ASR-Nano-2512` are preserved; absolute paths,
URLs, and credential-like model values are redacted. `ASRRunner.provenance()`
exposes deterministic configuration identifiers and an optional declared revision.
It contains no model, media, transcript, or raw exception payloads. Provenance is a
configuration/report surface, not a ledger field and not a semantic-accuracy claim.
Fixture evidence reports only fake model construction count, normalized segment
count, and output shape; run it directly with:

    python3.12 -m pytest -q tests/test_asr_reproducibility.py::test_fixture_benchmark_reports_only_construction_and_shape

This fixture does not establish hardware timing, model-weight pinning, network-free
runtime, or full-corpus coverage.

A per-item `bili-asr asr --bvid <bvid>` loop is one process per video, and the
run-scoped reuse above does not cross a process boundary: every invocation builds
its own model before it transcribes anything. For more than a couple of items,
prefer one bounded batch command (`run`, `schedule`, `campaign`), which holds a
single runner across the items it processes.

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

⚠️ **The `probe-subs` / `harvest-subs` pair writes to `archive.db`, not to the
manifest, so it feeds nothing below it.** The ASR/pilot chain
(`download-audio`, `asr`, `pilot`, `run`, `schedule`, `campaign`) is still driven
from `manifest/manifest.jsonl`, and the new `harvest-subs` no longer marks rows
`needs_audio`: `download-audio --missing-subs` gains no entries from the step
above it, and `asr --pending` does not see the stored transcripts. Run the
subtitle step for the SQLite archive itself; the legacy chain keeps its own
harvest (see the boundary bullet under
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)).

    bili-asr fetch-meta --mid 23191782 --archive-root archive
    bili-asr probe-subs --limit-parts 5 --archive-root archive
    bili-asr harvest-subs --limit-parts 5 --archive-root archive
    bili-asr download-audio --missing-subs --archive-root archive
    bili-asr asr --pending --archive-root archive
    bili-asr status --archive-root archive
    bili-asr runs --limit 10 --archive-root archive
    bili-asr pilot --n 20 --archive-root archive
    bili-asr search "黑格尔 辩证法" --archive-root archive
    bili-asr export --format json --out archive/manifest.json --archive-root archive
    bili-asr coverage --archive-root archive
    bili-asr coverage --trusted-local --archive-root archive
    bili-asr coverage --quality --archive-root archive
    bili-asr run --scope pending --archive-root archive
    bili-asr run --scope pending --offline --archive-root archive
    bili-asr run --scope failed --limit 5 --archive-root archive
    bili-asr schedule --scope pending --limit 20 --archive-root archive
    bili-asr schedule --scope pending --limit 20 --resume --archive-root archive
    bili-asr campaign --scope pending --limit 20 --archive-root archive
    bili-asr verify --archive-root archive
    bili-asr verify --trusted-local --archive-root archive
    bili-asr recover --archive-root archive --work-id <work-id>
    bili-asr evaluate-concurrency --evidence evidence.json --thresholds thresholds.json

Every `--bvid` command example in this README carries a real video id, so those
are paste-ready as they stand. The `<bvid>` placeholder survives in exactly one
place: the `bili-asr asr --bvid <bvid>` form quoted in the reuse note above,
written the way `scripts/check_asr_env.py` prints it. Usage synopsis lines (such
as `run --scope pending|failed|<work_id>...`) are argument grammar, not commands
to paste. A shell reads a bare `<word>` as redirection, so substitute your own
value before running any line that still carries one.

### Concurrency safety evidence gate

`bili-asr evaluate-concurrency --evidence <json> --thresholds <json>` is a
read-only, pure evidence evaluation surface. Its public Python API is
`ConcurrencyGate.evaluate(evidence: Mapping[str, object], thresholds: Mapping[str, object]) -> GateResult`;
`GateResult.to_dict()` returns the report mapping. A `go` decision is evidence
only for a future, separately approved plan. Production remains
`sequential-no-daemon`: this command does not start or enable a worker, daemon,
service, automatic startup, concurrent manifest writer, or alternate scheduler.
It changes no manifest schema, status taxonomy, risk taxonomy, or default.

Both inputs must be JSON objects no larger than 1 MiB. The evidence object has
exactly these required fields:

- `schema_version`: `concurrency-gate-evidence-v1`.
- bounded, non-empty ASCII `campaign_snapshot_id`.
- positive integer `campaign_item_count`, `campaign_denominator`, and
  `reconciliation_denominator`; item count must not exceed the campaign
  denominator, and reconciliation denominator must equal it.
- nonnegative integer `age_seconds`, finite nonnegative
  `throughput_items_per_hour`, `[0,1]` finite `api_risk_rate`, nonnegative
  integer `peak_disk_bytes`, and `[0,1]` finite `reclaim_rate`.
- boolean `crash_restart_passed`, nonnegative integer
  `duplicate_work_count`, positive integer `max_owner_count`, boolean
  `checkpoint_reconciled`, and boolean `risk_taxonomy_unchanged`.
- `write_isolation`, an object containing exactly five keys, each strictly
  `true`: `manifest`, `sidecars`, `attempts`, `index`, and `artifacts`.

The threshold object has exactly these required fields:
`min_campaign_item_count` (positive integer), `max_evidence_age_seconds`
(nonnegative integer), `min_throughput_items_per_hour` (finite positive
number), `max_api_risk_rate` (`[0,1]` finite number),
`max_peak_disk_bytes` (nonnegative integer), `min_reclaim_rate` (`[0,1]`
finite number), `max_duplicate_work_count` (nonnegative integer), and
`max_owner_count` (positive integer). Operators supply measured, reviewed
thresholds; this project does not guess values from CPU, memory, or disk.

Safe fixture shapes (illustrative values only, not recommended production
thresholds) contain no credentials or real URLs:

```json
{"schema_version":"concurrency-gate-evidence-v1","campaign_snapshot_id":"fixture-campaign-001","campaign_item_count":10,"campaign_denominator":10,"reconciliation_denominator":10,"age_seconds":30,"throughput_items_per_hour":5.0,"api_risk_rate":0.01,"peak_disk_bytes":1000,"reclaim_rate":0.9,"crash_restart_passed":true,"duplicate_work_count":0,"max_owner_count":1,"checkpoint_reconciled":true,"risk_taxonomy_unchanged":true,"write_isolation":{"manifest":true,"sidecars":true,"attempts":true,"index":true,"artifacts":true}}
```

```json
{"min_campaign_item_count":10,"max_evidence_age_seconds":3600,"min_throughput_items_per_hour":4.0,"max_api_risk_rate":0.02,"max_peak_disk_bytes":2000,"min_reclaim_rate":0.8,"max_duplicate_work_count":0,"max_owner_count":1}
```

The report schema is `concurrency-gate-report-v1` with deterministic keys:
`decision` (`go` or `no-go`), `ok`, `operating_mode`
(`sequential-no-daemon`), sorted unique `reason_codes`, and `schema_version`.
Schema, field, contradiction, threshold-breach, isolation, sensitive-data, and
input-complexity failures are represented by stable reason codes. Exit `0`
means `go`; exit `1` means `no-go` or input/evaluation failure. CLI failures
are compact JSON on stderr with `operating_mode: sequential-no-daemon` and one
of: `input_file_missing`, `input_file_unreadable`,
`input_file_not_regular`, `input_file_oversized`, `input_invalid_utf8`,
`input_malformed_json`, `input_non_object_json`, or `evaluation_failure`.
Paths, exception text, and input values are never emitted.

### Archive writer isolation

Every archive-mutating command (`fetch-meta`, `recover`, `asr`, `pilot`,
`harvest-subs`, `download-audio`, `run`, `campaign`, and
`schedule`) holds one archive-root writer lock from initial state load through
its final state/sidecar write. A second mutation exits `1` with
`<command>: archive_busy`; it does not wait or partially mutate the archive.
Read-only commands such as `status`, `coverage`, `verify`, `runs`, `search`,
`export`, `probe-subs`, and `evaluate-concurrency` do not claim this writer
lock: `probe-subs` writes nothing at all on the SQLite subtitle path.

### Audio reclaim and bounded-disk campaigns

By default, once a row reaches `archived`, its local audio file under
`{archive-root}/audio/` is deleted automatically to save disk space (failed 
and in-progress rows keep their audio for retry; the manifest may still record 
the relative `audio_path` — consumers treat the file as absent).

**Audio retention policy**: Set `BILI_KEEP_AUDIO=1` to preserve audio files 
after archival. This enables future reprocessing with improved ASR models 
without re-downloading from Bilibili. The manifest continues to track 
`audio_path` for retained files.

Download publication and reclaim are anchored to an opened `audio/` directory 
and use private random stage/quarantine entries; they never follow a swapped 
final-name symlink to an outside victim.

#### Transcript bundle publication

An archive generation is exactly four files: `transcripts/srt/<stem>.srt`,
`transcripts/txt/<stem>.txt`, one `transcripts/md/*.md`, and
`transcripts/raw/<stem>.json`. `<srt>.bundle-ready` is published last and names
those exact four relative paths with their SHA-256 digests. Readers accept only
a complete marker-matched generation; a partial or mixed generation remains
retryable and cannot justify `status=archived`.

Publication precedes the manifest transition. If all four files and the marker
are complete but the manifest append fails, the row stays at its prior status,
the complete bundle stays readable, and the next sequential run republishes or
commits it. Older `archived` rows without `raw_path` or a matching marker are
pre-marker evidence and must be re-archived before they count as complete.

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
FunASR-Nano, and archives with `source=asr`. Multi-part bvids include every
pagelist `work_id`. The summary prints branch counts and terminal states.
Missing subtitle or audio-asr coverage exits 1 and names the missing branch.
A completed rerun skips work already `archived`. Missing optional ASR exits
non-zero with `pip install -e "bilibili-asr-archive/[asr]"` and does not mark
the row archived.

### Operational run ledger (`run-ledger.jsonl`)

Every `pilot` / `run` / `schedule` run atomically appends an inspectable run
record to `{archive-root}/run-ledger.jsonl`. The metadata and subtitle CLI
commands record their runs in the fresh SQLite database instead
(`{archive-root}/archive.db`, see
[the fresh-start SQLite archive](#fresh-start-sqlite-archive-fetch-meta--status--runs)).
The ledger is a sidecar file that records execution history and
coverage without altering manifest row schemas or the transport layer.

#### Ledger record schema

Each JSONL line represents one immutable record with the following schema:

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Opaque identifier (`run-YYYYMMDDHHMMSS-<token>`). |
| `command` | `str` | Command executed (`pilot`, `run`, `schedule`). |
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

- **`bili-asr status [--archive-root <root>]`** reads the fresh SQLite
  metadata database (`archive.db`): counts of collected users, videos, and
  parts, the `processing_status` breakdown, pending work ids from
  `v_pending_metadata`, and each user's stored enumeration cursor. It exits
  `1` when the database does not exist (`fetch-meta` creates it) and never
  reads the legacy manifest sidecar. For `limited` collection runs, it
  reports the cursor state honestly without claiming complete enumeration.
- **`bili-asr coverage [--quality]`** is a read-only reconciliation and artifact quality report over fixture/local archive evidence. Use a temporary local root and optional scope; it never performs network traffic, model invocation, audio transcoding, or writes to source sidecars:

      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --scope pending --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --format csv
      bili-asr coverage --archive-root /owned/archive --trusted-local --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --quality --format json
      bili-asr coverage --archive-root /owned/archive --quality --trusted-local --format json
      bili-asr coverage --archive-root /tmp/bili-asr-coverage-fixture --quality --format csv

  Default `coverage`, `coverage --quality`, and `verify` inspection is
  `bounded_input`: at most 10,000 nonblank JSONL records and 8 MiB total per
  sidecar, with 16 MiB line/object ceilings. Limit breaches are named and make
  the result non-authoritative. `--trusted-local` is an explicit assertion that
  the archive root is operator-owned; it removes only total record/byte ceilings
  and keeps per-record validation, semantic validation, and no-follow path
  checks. It does not make malformed or symlinked input authoritative.

  `bili-asr verify` is the deterministic, read-only integrity check. Recovery is
  an explicit bounded audit request (it does not requeue or execute work):
  `bili-asr recover --archive-root <root> --work-id <work-id>`
  requires an explicit bounded target and writes only redacted audit evidence.
  `--work-id` names exact rows; `--defect-code` selects every currently
  reported row in that defect class. `--limit N` is required to be positive
  and defaults to 100; expansion happens before enforcement, and no command
  may select more than 100 targets (excess selection fails without a write).
  Recovery only appends a bounded, atomically replaced audit sidecar while
  holding a cross-process `fcntl.flock` lock file; it never
  mutates the manifest, attempts, transcripts, or audio. Existing malformed,
  oversized, or full audit evidence fails closed. Exit code 0 means the audit
  was written; exit code 1 means missing/invalid targets, non-authoritative
  source evidence, or any audit-sidecar failure.

The denominator is the selected manifest snapshot in work-item units; if the manifest or scope is unavailable, the report says `unavailable` and does not infer a count. `cumulative` describes all selected manifest rows, while `batch` describes only the latest scheduler/ledger batch; they are not interchangeable. `limited` and `risk_interrupted` evidence remains non-complete. Named diagnostics (for example `denominator_unavailable`, `scheduler_ledger_mismatch`, `sidecar_malformed`, or `terminal_missing_artifact`) make contradictions explicit and produce exit `1`; exit `0` means no diagnostics, while usage/configuration errors also exit `1`. Reports redact credentials, signed URLs, media, models, and raw exceptions. Use only reviewed local fixtures or a disposable temporary archive root; coverage is an inspection projection and does not mutate any source sidecar.

  **Subtitle and transcript artifact quality signals (`--quality`)**:
  - Subtitle-first quality provides **deterministic artifact validation only**; it explicitly makes **no claim of semantic correctness**, grammar correctness, or language fluency.
  - Reason codes are bounded and frozen: `empty` (empty artifact body/lines), `malformed` (unparseable SRT/JSON structure or non-finite timestamp), `non_monotonic` (out-of-order cue timestamps), `overlap` (overlapping cue intervals), `out_of_range` (negative time or cues exceeding known duration), `identity_mismatch` (work_id/bvid mismatch between manifest and artifact stem/frontmatter), and `artifact_missing` (referenced or inferred transcript files missing on disk or outside archive root).
  - **Reclaimed audio acceptance**: When valid transcript artifacts (`.srt`, `.txt`, `.md`, or `.json`) exist on disk for an `archived` entry, absent audio files under `audio/` are recognized as expected post-archive reclaimed disk state and are **not reported as defects**.
  - **Read-only boundary**: Quality inspection never mutates manifest row status, risk tokens, sidecars, or transcript files. It executes zero live network requests and requires no ASR model.
  - **Exit semantics**: Exits `0` when all scoped artifacts pass validation without defects or diagnostics; exits `1` when any artifact defect reason or telemetry diagnostic is present, or on configuration/usage error.


`bili-asr run` coordinates manifest rows through four stages — `harvest`
(probe + download subtitles), `download` (fetch audio), `asr` (local
FunASR-Nano), `archive` (write `srt`/`txt`/`md`) — composing the same live
seams as the single-purpose commands. It **complements** the frozen
`bili-asr pilot` MVP-proof command; it does not replace it.

This chain is driven from the manifest state only: `run`, `pilot`, `asr`, and
`schedule` never read `archive.db`, so transcripts stored by the SQLite
`harvest-subs` do not feed them (and `harvest-subs` no longer marks rows
`needs_audio`). See
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)
for that boundary.

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

### Controlled corpus campaign (`bili-asr campaign`)

`campaign` runs one explicitly bounded sequential coordinator batch and writes
`{archive-root}/campaign.json` as an aggregate audit projection. It does not own
per-row transitions: the manifest, stage-attempt ledger, and `scheduler.json`
remain authoritative for item state and risk-interruption resume.

    bili-asr campaign --scope pending|failed|<work_id>... --limit N [--resume] [--offline] [--max-audio-gb G] [--archive-root <root>]

- `--limit N` is mandatory and positive. The projection records only bounded,
  validated work IDs, a policy fingerprint, stable reason codes, and
  `complete`, `limited`, or `risk_interrupted`.
- `--resume` is accepted only when both the campaign projection and scheduler
  checkpoint describe the same scope, limit, policy, processed IDs, and risk
  interruption. Missing, malformed, mismatched, or deliberately completed or
  limited evidence fails closed rather than guessing work ownership.
- The checkpoint uses a same-directory atomic replace plus file and directory
  durability steps. Credentials, URLs, raw exceptions, request payloads,
  models, and media are forbidden from the projection and summary.
- Exit `0` means the selected bounded scope completed; exit `1` means a
  configuration error, limited/non-terminal outcome, skip, or per-item failure;
  exit `2` means risk interruption. A completed bounded campaign is not a claim
  that the visible corpus is fully archived.

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

### Fresh-start SQLite archive (`fetch-meta` / `status` / `runs`)

`bili-asr fetch-meta` collects video metadata through the pinned
`bilibili-api-python==17.4.2` gateway and writes it to a fresh normalized
SQLite database at `{archive-root}/archive.db`; the layout is described in
[docs/metadata-storage.md](docs/metadata-storage.md). The metadata commands
never read or write the legacy `manifest/manifest.jsonl`,
`meta-cursor.json`, or `run-ledger.jsonl` sidecars, and no command migrates
old archive data: a new database starts empty. Deleting `archive.db` is the
only restart path.

    bili-asr fetch-meta --mid 23191782 --archive-root archive
    bili-asr fetch-meta --mid 23191782 --limit-pages 1 --archive-root archive
    bili-asr status --archive-root archive
    bili-asr runs --limit 10 --archive-root archive

The subtitle commands work on that same fresh database and are described in
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)
below; this subsection covers the metadata and read commands only.

- **Default page bound**: `--limit-pages` is optional and defaults to
  `DEFAULT_PAGE_LIMIT = 10`. The canonical command above therefore stops
  after 10 pages (the ingestor's page size is 30 — the upstream-accepted
  default, `ps=30`; larger page sizes are not guaranteed, and an explicit
  programmatic override is forwarded rather than clamped or rejected: there is
  no CLI flag for it), ends the run `limited`, and still exits 0 — a limited
  run is never claimed as complete. A full archive walk is a series of
  resumable runs: re-run the same command to continue from the stored cursor,
  or pass an explicit `--limit-pages` for a longer slice.
- **Resume semantics**: without `--resume` or `--start-page`, a run continues
  from the stored cursor when one exists and starts at page 1 otherwise.
  `--resume` requires a stored cursor and exits `1` when there is none;
  `--start-page` overrides the cursor. A failed page never advances the
  cursor, so resume is always safe.
- **Credential boundary**: optional SESSDATA comes from `--sessdata` or the
  `BILI_SESSDATA` environment variable (cookie **value**, not a file path).
  It is sent as an API cookie only and is never echoed, logged, persisted,
  or written to the database; CLI output shows presence only
  (`sessdata: present|absent`). Passing `--sessdata ""` explicitly forces
  anonymous access even when `BILI_SESSDATA` is set; a blank environment
  value likewise means anonymous.
- **Runtime HTTP backend**: the pinned
  `bilibili-api-python==17.4.2` distribution declares no HTTP client of its
  own, so `curl_cffi` is a declared runtime dependency of this package and a
  normal install (`pip install -e ".[dev]"` or `uv sync`) provides it.
  Without a backend, every request fails in-process before it leaves the
  process and surfaces as the bounded `response_error`.
- **HTTP proxy**: on a host that needs a proxy, set `BILI_HTTP_PROXY`
  (for example `BILI_HTTP_PROXY=http://127.0.0.1:7890`). The pinned client
  builds its session with an explicitly empty proxy, so the standard
  `HTTPS_PROXY` / `ALL_PROXY` variables alone are ignored by the package; the
  gateway resolves the knob itself in the order constructor argument →
  `BILI_HTTP_PROXY` → `HTTPS_PROXY`/`https_proxy` → `ALL_PROXY`/`all_proxy`,
  treats a blank value as unset, and forces no proxy when nothing resolves.
  The resolved value is applied to the package's process-global settings, and
  a blank value cannot override a host-level variable — forcing direct access
  means unsetting those variables for the process (there is no in-app switch).
  Details: [docs/metadata-storage.md](docs/metadata-storage.md).

| Exit | Meaning |
|------|---------|
| 0 | `fetch-meta`: successful collection — the empty page was reached, or the run stopped at a page bound (the explicit `--limit-pages` or the implicit default of 10 pages); the run row records `complete` or `limited` accordingly. `status` / `runs`: database read and displayed. |
| 1 | Usage/configuration error: bad page arguments, `--resume` without a stored cursor, or a missing/unreadable database for the read commands. Unexpected internal errors exit 2 (see below), not 1. |
| 2 | `fetch-meta` only: terminal failure — two variants, distinguishable by the failure line (see below). |

Exit 2 variants:

- **Gateway failure** (bounded scalar code, e.g. `response_error`,
  `rate_limited`): the gateway is fail-fast per page — one attempt per
  page, no retry. The failed page records its bounded scalar code, the
  cursor remains unchanged, and re-running `fetch-meta` resumes safely.
- **Unexpected internal error** (the fixed line `fetch-meta: unexpected
  error`, no scalar code, no traceback): the cursor may already hold the
  last committed page of the run and the run row may remain `running` —
  check `status` / `runs` before re-running. Re-running is safe: it
  resumes from the stored cursor.

#### Subtitle acquisition on SQLite (`probe-subs` / `harvest-subs`)

`bili-asr harvest-subs` acquires captions for parts already stored in
`archive.db` and keeps the normalized transcript **in that database**: no
`subtitles/raw/*.json` and no `transcripts/srt/*.srt` is written, and no JSONL
sidecar is read or written. `bili-asr probe-subs` lists the tracks the selected
parts expose and writes nothing at all — no database creation, no run or attempt
row, no lock file. The full contract, with the printed line shapes and the
observed live run, is in
[docs/metadata-storage.md](docs/metadata-storage.md).

    bili-asr probe-subs --limit-parts 5 --archive-root archive
    bili-asr probe-subs --bvid BV1S8hA6MEvy:p0 --archive-root archive
    bili-asr harvest-subs --limit-parts 5 --archive-root archive
    bili-asr harvest-subs --bvid BV1S8hA6MEvy:p0 --archive-root archive
    bili-asr harvest-subs --limit-parts 5 --language ai-zh --archive-root archive

- **Bounds**: no unbounded runs. `harvest-subs` requires `--limit-parts N`
  whenever the selection is not a single `bvid:pN` part; `probe-subs` requires
  exactly one of `--bvid` / `--limit-parts`. `--bvid BVID` selects every part of
  that video already in the database — for `harvest-subs` that includes parts
  that already have a transcript, which is how a video is re-checked after
  upstream revises a caption. Neither command fetches a pagelist, and neither
  calls upstream for a part that is not in the database.
- **Exit codes**: `0` the bounded run completed — including a probe whose parts
  exposed no track, and a selection that resolved to no part (`attempted=0`);
  `1` usage/configuration (missing database, unknown `--bvid`, missing or
  non-positive bound, neither/both `probe-subs` selectors, empty `--language`
  entry, or the schema guard below); `2` every attempted part failed, or an
  unexpected internal error (`<command>: unexpected error`, no traceback).
  Partial failure stays visible in the printed counts, not in the exit code.
- **Output shapes**: `probe-subs` prints `sessdata: present|absent`, then one
  line per selected part — `probe <work_id> tracks=<n>` with one
  `track <lan> <ai|cc> <label>` line each, `probe <work_id> tracks=0` with an
  explicit `(no subtitles visible)` marker, or `probe <work_id> failed <code>` —
  and closes with
  `probe-subs: probed=<n> with_tracks=<n> without_tracks=<n> failed=<n>`.
  `harvest-subs` prints one line per attempted part —
  `harvest <work_id> stored|unchanged <source_kind> <language> v<version>`,
  `harvest <work_id> no-subtitle`, or `harvest <work_id> failed <error_code>` —
  and closes with `harvest-subs: run_id=<id> attempted=<n> stored=<n>
  unchanged=<n> no-subtitle=<n> failed=<n>
  remaining_without_transcript=<n>`, carrying all four counts including the
  zeros. Nothing here is a claim about corpus or caption coverage.
- **Preference rule**: the default keeps the **uploader** caption
  (`subtitle-cc`) over the machine one (`subtitle-ai`), with families ranked
  `zh`, then `en`, then the rest in upstream order. That CC-before-AI term is
  family-blind on purpose: the remaining families share one rank, so between two
  **different** non-default families the uploader caption wins even when the
  machine track comes first upstream, and upstream order settles only a tie
  between tracks of the same family and the same kind. The family is derived
  from the `language` + `is_ai` facts the gateway
  already guarantees (strip an `ai-` prefix from a machine code, then take the
  primary subtag), so `zh-CN` / `zh-Hans` / `zh-Hant` / `ai-zh` all rank as
  `zh`: upstream uses different exact codes per caption kind, and a fixed code
  list would silently mis-rank codes upstream adds while a machine↔uploader
  equivalence table would need maintaining. `--language PREF[,PREF...]` matches
  a preference **exactly** against the code `probe-subs` prints, so
  `--language ai-zh` keeps the machine caption reachable. This replaces the
  legacy manifest harvest's AI-first order.
- **Credential**: `--sessdata` or `BILI_SESSDATA` (flag wins), with the same
  resolution and presence-only redaction as the metadata commands
  (`sessdata: present|absent`); the value reaches the gateway's cookie only and
  is never echoed, logged, or persisted. `harvest-subs` records the presence in
  its run row, so a part it recorded `no-subtitle` stays interpretable — an
  invisible caption may exist and simply be login-gated.
- **Schema guard and rebuild**: on a database that predates the transcript
  schema both commands print one line on stderr — `<command>: archive database
  predates the transcript schema; rebuild it (delete <archive-root>/archive.db
  and re-run fetch-meta)` — and exit `1`, while `fetch-meta` / `status` / `runs`
  keep working on it. There is no in-place migration: deleting `archive.db` and
  re-running `fetch-meta` is the rebuild, and a bare `fetch-meta` stops at the
  implicit `--limit-pages` bound (`DEFAULT_PAGE_LIMIT = 10`), so a corpus
  collected beyond page 10 needs `--limit-pages <n>` (or repeated `--resume`
  runs). The database is created from two checked-in
  resources, `src/bili_asr/storage/schema.sql` and
  `src/bili_asr/storage/schema-transcripts.sql`.
- **Legacy manifest boundary**: the ASR/pilot chain is untouched and still reads
  `manifest/manifest.jsonl`, so `asr --pending`, `pilot`, `run`, `schedule`, and
  `campaign` do not see transcripts stored here. In particular the new
  `harvest-subs` no longer produces the manifest status `needs_audio`, so
  `download-audio --missing-subs` gains no new entries from the SQLite subtitle
  path — the two paths do not feed each other yet. Rebuilding the SRT/TXT/MD
  projections from the stored transcripts is deferred work for a later
  iteration.
- **Writer lock**: `harvest-subs` is an archive-writer command and holds
  `{archive-root}/coordinator/archive-writer.lock` for the whole run, so a
  second mutating command exits `1` with `harvest-subs: archive_busy`. Apart
  from `archive.db`, that lock is the only file a bounded harvest leaves behind;
  `probe-subs` deliberately takes none. The lock is taken **before** the
  command's database check, so even a failed or mistyped harvest — a missing
  `--archive-root`, say — creates `<root>/coordinator/` and leaves the lock file
  there while exiting `1`; nothing reaches the database.

#### Opt-in bounded live smokes

Four tests share the one switch (`BILI_LIVE_SMOKE=1`); every default pytest
run skips all four and makes no network call:

- `tests/test_live_metadata_smoke.py` — the real CLI against the real upstream:
  exactly one public metadata page for UID 23191782, into a temporary archive
  root, calling no subtitle/playback/audio/ASR code (detailed below);
- `tests/test_live_subtitle_smoke.py` — the real subtitle adapter against the
  real upstream: one part's track inventory and, when a track is visible, that
  track's caption document. It resolves the part from the operator's archive
  database when one is readable and falls back to a fixed public sample
  otherwise (`part_source=archive-db|fixed-sample`), and it prints bounded
  facts only — counts, language codes, `ai|cc`, segment count, milliseconds,
  and credential presence — never a URL, body, label, or credential. Run it
  from the package directory with the pinned distribution installed:
  `BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_subtitle_smoke.py -s -v`;
- `tests/test_live_subtitle_cli_smoke.py` — the real **CLI + storage** chain
  against the real upstream: one part through `probe-subs` and `harvest-subs`
  in a temporary archive root, asserting the printed line shapes, the stored
  transcript rows, and the archive root's file set. The part both commands
  address is authored into that temporary root — the fixed public sample
  `BV1S8hA6MEvy:p0`, recorded as `part_source=fixed-sample` — because the
  commands only ever address parts the database already stores. Zero visible
  tracks, a `not_found` listing, and a `rate_limited` refusal are recorded as
  bounded evidence and skipped rather than reading green; every other bounded
  code fails loudly. Once opted in it **requires a credential**: with no
  resolvable `BILI_SESSDATA` it fails with source-the-`.env` guidance instead of
  reporting an anonymous `sessdata=absent tracks=0` run as "nothing visible now"
  — an ambiguous reading, since a login-gated caption looks the same. Its one
  count-only evidence line names the seeded part,
  credential presence, both commands' counts, and the stored source
  kind/language/version. Run it from the package directory of the checkout
  under test (the package's `tests/conftest.py` puts that checkout's `src/`
  first on `sys.path`, ahead of the control `.venv`'s editable install):
  `BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_subtitle_cli_smoke.py -s -v`;
- `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner`
  — the adapter-level ancestor of the CLI smoke: one real metadata page for UID
  23191782 ingested into a temporary database through the real gateway.

`tests/test_live_metadata_smoke.py` drives the real CLI against the real
upstream: exactly one public metadata page for UID 23191782
(`--start-page 1 --limit-pages 1`) into a temporary archive root, calling no
subtitle/playback/audio/ASR code. Default pytest runs skip it; the proxy is
part of the command on a proxied host:

    CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
    cd "$CONTROL/bilibili-asr-archive"
    set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
    export BILI_HTTP_PROXY=http://127.0.0.1:7890
    BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
      -m pytest tests/test_live_metadata_smoke.py -s -v

The control checkout owns the `.env` credential file and the `.venv`
interpreter, and a linked feature worktree has neither — a worktree run must
address them by absolute control-checkout path (as above) or provision its own
environment. Keep `-s` (or `-rP`) in the command on the first live attempt:
pytest captures the stdout of a *passing* test, so a plain `-v` run hides the
count-only evidence line on the happy path and would force a second page
request against a risk-controlled endpoint.

The smoke's credential signal is the `BILI_SESSDATA` environment variable alone
(sourced from `.env` above): it builds its own `fetch-meta` argv and passes no
`--sessdata`, so that CLI flag is not a smoke input. With that credential the
smoke requires the happy path: exit 0, `outcome=limited` on the page bound
(or `complete` on an empty first page), and the real normalized rows — user,
videos, their parts, one discovery row per video, a terminal run row, exactly
one page row, and a cursor advanced past the committed page — with no legacy
sidecar and no credential or playback marker in output or rows. It prints one
count-only evidence line (`live smoke evidence: outcome=… videos=… parts=…
discoveries=… page_rows=1 cursor_next_page=… cursor_state=…
observed_total=…`); a bounded failure with a credential present is a loud
failure. Without a credential the run is anonymous: if upstream rejects
anonymous metadata access the smoke verifies the bounded-failure evidence
(terminal run row, one scalar page row with a `rate_limited` /
`response_error` code, no entity or discovery growth, no cursor row) and
reports that bounded no-credential outcome as a reasoned skip rather than a
defect; any other bounded code fails the smoke loudly. Expectations and the
underlying transport/proxy requirements are documented in
[docs/metadata-storage.md](docs/metadata-storage.md).

### Mixed batch outcomes

On the legacy manifest path, when `download-audio`, `asr`, `pilot`, `run`, or
`schedule` processes more than one work item, the process exit code is an
aggregation of per-item outcomes — not a claim that the whole corpus is
complete. `pilot` remains the frozen two-branch proof command; `run` remains
complementary; `schedule` consumes this same taxonomy. The SQLite
`harvest-subs` follows its own bounded taxonomy instead (see
[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)).

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
(that sidecar is `pilot` / `run` / `schedule`; `fetch-meta` records its runs
in `archive.db`). All operator
surfaces carry redacted scalar codes/reasons only.

### Corpus coverage evidence spine

The shipped sequential workflow now includes all six corpus-coverage slices: bounded `campaign` execution, cumulative `coverage` reconciliation, optional deterministic artifact quality signals, filtered local transcript search/export, read-only `verify` plus audit-only `recover`, and the `evaluate-concurrency` safety gate. The manifest remains SSOT; the campaign checkpoint, reports, index, and recovery audit are additive evidence or derived projections.

A bounded campaign never implies full-corpus completion. Coverage reports keep explicit denominators and distinguish cumulative rows from the latest batch. Reclaimed audio is valid after transcript archival, and quality checks make no semantic-correctness claim. `recover` records bounded redacted candidates only—it does not requeue work, change statuses, or execute repair. The concurrency gate remains a pure `go`/`no-go` evaluator whose operating mode is always `sequential-no-daemon`; even a `go` report requires a later separately approved implementation plan.

Future production expansion should consume measured campaign/reconciliation evidence and retain exact ownership, write-isolation, crash/restart, API-risk, disk, reclaim, and throughput thresholds. No worker, daemon, service, autostart, scheduler-default change, concurrent manifest writer, or schema/status/risk-taxonomy change is implied by these surfaces.

## Multipart pages and legacy rows

Automatic enumeration writes one manifest row per page (`work_id` =
`{bvid}:p{page_index}`). Filesystem names use `artifact_stem`
(`{bvid}.p{page_index}`) so raw/SRT/audio/transcripts never collide across
pages. Public URLs for `page_index` > 0 include `?p=` (1-based).

Legacy single-page rows migrate only when ownership is unambiguous. Ambiguous
bare-bvid rows stay `unresolved` / `excluded_from_page_processing`: they keep
their original key and files, stay visible in `bili-asr status`, and are never
auto-assigned a page. Bare-bvid rows remain a compatibility read/update
boundary only; new automatic rows require page-qualified `work_id` plus matching
`bvid`. `download-audio --bvid` / `asr --bvid` STOP on unresolved rows instead
of fabricating a `needs_audio` page. Resume is per `work_id`: a completed or
failed p0 does not skip p1.

No media redistribution; personal archival only.
