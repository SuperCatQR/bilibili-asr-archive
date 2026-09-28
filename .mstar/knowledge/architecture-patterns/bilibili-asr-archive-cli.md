---
module: bilibili-asr-archive CLI
date: 2026-08-23
last_updated: 2026-09-19
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: iter-2026-08-wmz-asr-mvp
tags:
  - bilibili-api
  - resumable-cli
  - optional-asr
  - risk-control
  - transport-seam
  - page-identity
  - meta-cursor
  - audio-budget
---

# Bilibili archive CLI architecture

## Context

A personal Bilibili archive has two very different workloads: metadata and
short-lived API/CDN requests, plus local transcript generation that may require
large model dependencies. The workflow must survive API risk control and be
safe to resume after a partial run. Multi-part videos need collision-free
per-part identity, and metadata enumeration must resume after risk stops
without misreading a deliberately bounded run as complete. Repeated full-visible-
corpus batches also need an explicit sequential scheduler whose progress is
separate from the manifest state machine. Production coverage, artifact quality,
integrity, and future concurrency decisions therefore use bounded derived
evidence rather than inferred completion or a second write owner.

## Guidance

Keep `bili_client` as the only module that opens sockets. Expose transport
protocols and a binary-stream seam so API, CDN, and retry behavior can be
unit-tested without live media requests. Keep subtitle conversion, ASR
normalization, archive writers, and manifest updates pure or filesystem-only.
`BiliClient` never imports the cursor module; cursor I/O lives in the CLI /
`MetaCursorStore` seam.

Use a JSONL manifest keyed by `work_id` as the state machine SSOT. For
multi-part videos `work_id = bvid:p<zero-based-page-index>` and the
filesystem stem is `{bvid}.p{page_index}` (never put `:` in paths). State
machine: `pending -> meta_ok -> {subtitle_done | needs_audio -> audio_ok} ->
archived`, with `gone` as a per-video terminal state. Persist terminal state
atomically; write partial metadata after a risk ceiling so `--resume` can
continue. That state machine is the legacy archival flow's, still owned by
`manifest.jsonl`: the metadata commands enumerated above keep their SQLite
replacements, and the ASR/pilot chain still runs on it — but the subtitle path was
**cut over at `iter-2026-09-subtitle-transcript-sqlite`**, so the two subtitle
commands neither read nor write manifest state and no longer produce the
`needs_audio` status (see `### Subtitle acquisition commands (SQLite path)`).

### Resumable metadata enumeration (meta-cursor.json sidecar)

- Sidecar at archive root, keyed by `mid`: `next_page`, `total`, `state`,
  `last_api_error_code`, `updated_at`. Atomic same-directory temp file plus
  os.replace (matching ManifestStore.save).
- `state` enum: `risk_interrupted` (the only state `--resume` consumes,
  mid must match) | `limited` (deliberate cap; not full enumeration) |
  `complete` (visible archive fully enumerated) | `running` (in-memory only,
  never persisted).
- Advance rule: persist cursor after the corresponding manifest JSONL merge
  for each successful archive-list page; mid-run stays `risk_interrupted`
  with `next_page = last merged pn + 1`; terminal `complete`/`limited` only
  after the crawl returns. Risk exhaustion persists `next_page =
  last_failed_page` and exits 2.
- Without `--resume`, a new run replaces a stale cursor after the first
  successful page but never truncates the JSONL to a page-1 prefix (merge
  prior rows last-write-wins).
- `known_bvids` (seeding the no-new-bvid completion stop) is passed only on
  `--resume`; a full recrawl must walk to the last catalog page rather than
  stop on the first overlapping page.
- `--limit-pages N` counts pages fetched in the current call, not an absolute
  `pn` ceiling.
- Forbidden sidecar contents: cookies, SESSDATA, signed URLs, raw exception
  messages, request dumps.

Treat API risk ceilings as batch-stop conditions (exit 2), but treat CDN stream
failures as per-video failures so one flaky media request does not discard the
whole batch. Check non-empty `.m4a`/`.flac` artifacts before API probes, and
pace sequential video work between requests.

### Sequential scheduler contract

Use `schedule` as a bounded orchestration layer over the existing client,
manifest, cursor, coordinator, budget, and reclaim seams. It owns neither HTTP
nor a second item state machine. Every call has an explicit finite limit and a
scope; **scheduler.json** records whether that batch is `complete`, `limited`,
or `risk_interrupted`. Resume only a matching-scope risk interruption. Keep
short-video selection as the default, and require `--allow-long-live` plus a
positive audio cap for multi-hour work. A bounded batch must never claim full
corpus completion merely because its local limit was reached.

### Evidence-gated corpus operations

Build the production evidence spine as additive, bounded surfaces:

- `campaign` wraps a finite sequential coordinator batch and atomically records
  aggregate scope/policy/selection evidence in `{archive-root}/campaign.json`; per-row ownership
  remains with the manifest, scheduler, and attempt ledger.
- `coverage [--quality]` reads local evidence without writes, uses an explicit
  manifest-snapshot denominator, separates cumulative from latest-batch counts,
  and reports contradictions or structural artifact defects with stable codes.
- `search`/`export` remain bounded manifest-derived read models. `verify` confines
  reads to authoritative archive paths and accepts reclaimed audio when required
  transcript outputs exist.
- `recover` is intentionally audit-only: exact work-ID or authoritative defect
  selection, maximum 100 targets, redacted append-only audit evidence under a
  process lock, and no requeue/status/artifact mutation.
- `evaluate-concurrency` accepts only exact bounded evidence/threshold schemas and
  produces deterministic sorted reasons. Its report always says
  `sequential-no-daemon`; `go` is input to a future approved plan, never a switch.

This ordering is deliberate: bounded execution produces evidence; reconciliation
establishes the denominator; local quality/integrity checks validate artifacts;
only then may an explicit concurrency gate evaluate reviewed ownership, recovery,
API-risk, disk, reclaim, throughput, freshness, and write-isolation thresholds.
No threshold is inferred from available hardware.

Make heavy ASR dependencies optional and import them lazily. The base CLI must
still expose help/status/subtitle workflows, while `transcribe()` returns an
actionable install hint. Keep model weights outside the repository and support
a local model path for offline runs.

### Bounded transient-audio policy

Audio is **retained by default**; the cap is what bounds it. Before downloading a
`needs_audio` row, estimate its peak footprint as
`duration_s * 8_000` bytes (a conservative 64 kbps ceiling) plus current audio-directory usage. `pilot`, live `run`, and `schedule` skip the
item with `audio_budget` if that would exceed `--max-audio-gb`; the default is
10 GiB and `0` disables the cap except on `--allow-long-live`, which refuses a
disabled cap. A retaining operator therefore keeps downloading with
`--max-audio-gb 0`, and the run/pilot skip line names that flag. The pilot's `--max-duration-min` default of 45 excludes long rows,
including pagelist siblings, from bounded selection. `schedule` pending/failed
uses the same 45-minute short-video policy unless the operator passes
`--allow-long-live`; an explicit multi-hour `work_id` without that flag is a
usage error. The long-live summary prints the conservative estimate, measured
audio-directory peak, and post-archive usage after reclaim.

When an archive write completes, the resolved retention policy decides whether the
filesystem-only reclaim helper removes the row's `.m4a` or `.flac`: `--keep-audio` on
`asr`/`pilot`/`run`/`schedule`/`campaign` retains, `--no-keep-audio` reclaims, and
`BILI_KEEP_AUDIO=1`/`=0` keep their meanings as the environment escape hatch. Reclaim
probes each candidate under every base the artifacts may live under — the configured
artifact root and the archive root — and a candidate that escapes its own base is
refused; it is never resolved against one root while the file sits under the other. Reclaim must be best-effort:
the transcript and `archived` state remain valid if a local deletion fails.
Failed, `needs_audio`, and `audio_ok` rows retain audio for retry. For an
`audio_ok` row with a non-empty local file, ASR reuses that file directly and
must not apply the pre-download budget or make a second HTTP download; the reuse
path finds a legacy copy at the archive root as well as one under a configured
artifact root. The SQLite
subtitle path produces no `needs_audio` rows, so this policy now applies only to
rows the legacy manifest path or an explicit selection supplies.

Report `pilot batch branches` separately from `pilot coverage branches`.
Batch counts describe the invocation; coverage counts include earlier archived
rows and only decide whether the cumulative two-branch contract is satisfied.

### Subtitle acquisition commands (SQLite path)

`probe-subs` (read-only track listing) and `harvest-subs` (bounded acquisition into
normalized transcripts) are the caption commands. Both address parts already stored
in `archive.db` and take the `cid` from `video_parts` — the path never fetches a
pagelist and never calls upstream for a part that is not in the database. Neither
command reads or writes `manifest.jsonl`, `meta-cursor.json`, or `run-ledger.jsonl`.

- **Bounds and selectors.** `probe-subs` requires exactly one of `--bvid` /
  `--limit-parts N`; `harvest-subs` requires the bound unless the selection is a
  single `bvid:pN` part, which is bounded by construction. `--bvid BVID` selects
  every part of that video already in the database — for a harvest that includes
  parts that already have a transcript, the deliberate re-check path after upstream
  adds or revises a caption — and `bvid:pN` selects exactly one part in the archive's
  zero-based part vocabulary. A selector that resolves to no stored part is a
  configuration error (exit `1`, fixed `unknown --bvid <value>`), never an empty
  result; a selector that can never name a stored part at all — empty once stripped,
  or carrying NUL/CR/LF — is answered the same way from the argument alone, before
  the database is opened, instead of surfacing as an unexpected internal error from
  the storage layer's identifier validation.
- **Exit taxonomy.** `0` bounded success/read: a probe whose parts exposed no track,
  a harvest whose every attempted part had nothing visible, and a selection that
  resolved to no part (`attempted=0`) all exit `0`. `1` usage/config: a missing
  `archive.db`, an unknown `--bvid`, a missing or non-positive bound, neither or both
  probe selectors, an empty `--language` entry, the schema guard below, and the
  unreadable-database line below. `2` every attempted part failed, or an unexpected
  internal error (the fixed line `<command>: unexpected error`, no traceback).
  Usage errors always exit `1`, never `2`, and partial per-part failure stays visible
  in the printed counts without by itself deciding the exit code.
- **Run reporting is part of the contract.** A harvest summary always prints all four
  outcome counts including zeros, the run id, credential presence, and how many parts
  still lack a transcript; a zero-track probe part is printed with its explicit
  `(no subtitles visible)` marker rather than omitted, so "no tracks" cannot be read
  as "not attempted". No count here is presented as coverage of the corpus.
- **Schema guard.** Both commands call `require_subtitle_schema` after opening the
  database; when the database predates the transcript contract they print one composed
  line to stderr and exit `1`:

  ```text
  <command>: archive database predates the transcript schema; rebuild it
  (delete {archive_root}/archive.db and re-run fetch-meta)
  ```

  It is one line at runtime; the wrap here is the page's. The CLI composes the command
  prefix and the resolved database path because `SchemaContractError` carries only a
  connection. On a zero-byte `archive.db` the asymmetry is real and intended:
  `harvest-subs` opens through the schema-initializing `open_database` and runs, while
  `probe-subs` writes nothing at all and therefore answers with the rebuild line.
- **Damaged database.** A file that exists but cannot be read — not a SQLite database
  at all, truncated, or a damaged image whose header still opens — is answered with
  one bounded line on stderr and exit `1`:

  ```text
  <command>: unreadable archive database at {archive_root} (<ErrorType>)
  ```

  That is the same line `status` and `runs` print for such a file, and no command
  repairs or rewrites it. Only `(OSError, sqlite3.Error)` is bounded here, and the
  first read is taken inside that handler, because a damaged file fails on its first
  statement rather than on connect.
- **Credential.** `SESSDATA` is presence-only in every display path and is recorded
  per run in `acquisition_runs.credential_present`, so a part recorded without a
  visible caption stays interpretable afterwards — an invisible caption may exist and
  simply be login-gated. An opted-in live run with no resolvable credential fails
  loudly with guidance to source the operator environment, rather than reporting its
  anonymous `sessdata=absent tracks=0` reading as a bounded observation: that reading
  is ambiguous, because a login-gated caption and a part with no caption look
  identical.
- **Read-only probe.** `probe-subs` is deliberately not an archive-writer command,
  and it does not open the database through `open_database` — that path executes both
  idempotent schema scripts and commits them even when nothing changes. It opens the
  existing file through a `mode=ro` URI instead, so "writes nothing at all" is
  structural rather than conventional: a write attempted through that connection
  fails inside SQLite. It never creates `archive.db` and takes no lock file.
- **Writer-lock ordering.** `harvest-subs` is an archive-writer command, and the lock
  at `{archive_root}/coordinator/archive-writer.lock` is taken in the entrypoint
  **before** the database check, so a harvest that then fails still creates
  `{archive_root}/coordinator/`. A second mutating command exits `1` with
  `harvest-subs: archive_busy`.
- **Projection and feeder boundary.** Neither command writes an on-disk projection of
  the transcript — no `subtitles/raw/*.json`, no `transcripts/<stem>/bundle.srt`; the
  normalized transcript lives in `archive.db`. `harvest-subs` no longer produces the
  manifest status `needs_audio`, so the legacy audio feeder
  (`download-audio --missing-subs`) gains no new entries from this path, and the
  ASR/pilot chain is still driven from manifest state rather than from the database.
  Enumerating the audio work queue from SQLite (including the parts recorded without a
  visible caption, which are that queue) has since shipped as its own archive-writer
  command, `derive-manifest` — it appends one `needs_audio` row per stored part that
  holds no transcript and is not `gone`, reads the manifest read-only to avoid
  regressing a row the chain owns, and writes nothing else; the command's contract is
  [queue-derivation-bridge.md](queue-derivation-bridge.md). Rebuilding SRT/TXT/MD
  projections from stored transcripts is still deferred.
- **Live smoke.** The opt-in bounded smoke runs from the package directory of the
  checkout under test, with the credential and proxy present in the environment:

  ```text
  BILI_LIVE_SMOKE=1 <python> -m pytest tests/test_live_subtitle_cli_smoke.py -s -v
  ```

  It authors one public part into a temporary archive root, runs both commands at one
  part, and prints one count-only evidence line (`part_source`, both exit codes, the
  probe/harvest counts, the run id, and the stored source kind / language / version).
  Zero visible tracks, a `not_found` listing, and a `rate_limited` refusal print their
  bounded evidence and skip; a `transport_error` from a dead proxy, `response_error`,
  or `shape_error` fails loudly.

### Installed Python baseline

Verify packaging through the installed `bili-asr` console script rather than
only importing checkout source. The repeatable baseline uses a fresh Python
3.12 environment, a complete locally reviewed wheel fixture, and `--no-index`
plus `--find-links` for both declared build requirements and `.[dev]`. Bootstrap
the declared build backend before a `--no-build-isolation` project install;
check the generated console launcher while the temporary environment still
exists. Record only command names and exit codes in the result, and keep local
advisory audit data separate from live lookups.

When staging tests for an installed distribution, copy only ordinary files
from explicitly required repository input trees. Reject symlinks before copy
to prevent checkout-local paths from escaping into the temporary test tree.
Keep the staged test tree's `src` path injection removed so product imports
resolve from the installed wheel. A missing interpreter prerequisite or
incomplete wheel closure must be a named failure, never a false green.

## Why This Matters

These boundaries make the no-login subtitle-first path useful without a model,
keep credentials and signed URLs out of manifests and cursors, and turn
interrupted long runs into resumable work rather than a restart from zero.
Per-part identity prevents multi-part videos from overwriting each other's
subtitle/audio/transcript artifacts. The evidence spine prevents bounded batch
success, a stale derived index, intentionally reclaimed audio, or a passing gate
from becoming false manifest state or implicit permission for concurrent writes.

## When to Apply

Apply this pattern to archive or ingestion CLIs that combine rate-limited HTTP,
large binary downloads, optional local ML, and durable per-item progress with
multi-part sources and resumable enumeration. Use the evidence-gate extension
when operators need honest cumulative coverage, confined local recovery review,
or a measured decision before any concurrency/service implementation.

## Evidence

- Iteration: `iter-2026-08-wmz-asr-mvp`, `iter-2026-08-archive-foundations`
- Source specs: `.mstar/specs/asr-archive-cli.md` (page-aware identity and cursor contract); historical implementation evidence is anchored by commit `33b0a37`.
- Implementation: `bilibili-asr-archive/src/bili_asr/` (incl.
  `bilibili-asr-archive/src/bili_asr/meta_cursor.py`)
- Verification: 96 unit tests on Python 3.12 (MVP); 147 passed (plan 001);
  168 passed (plan 002), no live HTTP.
- Operational layer (ledger / FTS5 / coordinator) is documented in
  [operational-sidecars.md](operational-sidecars.md); 277 passed at
  `iter-2026-08-pilot-ops` close.
- Bounded PC pilot: `iter-2026-08-live-pc-pilot`, source revision `4e00fb3`;
  299 tests passed and staged Windows WSL N=5 / N=20 observed subtitle and
  ASR branches, named budget skipping, and post-archive reclaim.
- Corpus-operations update: `.mstar/specs/asr-archive-cli.md` and commit `ad5253d` (scheduler and verification-baseline changes); integration revision `ad5253d` passed 392 tests, and the managed Python 3.12.13 no-index baseline passed with five zero-exit commands and 14 hash-validated fixture artifacts.
- Corpus-coverage update: the six implemented contracts under `.mstar/iterations/iter-2026-08-corpus-coverage/specs/` are reflected in the current product README and this pattern. Integration revision `69b9530` passes 612 Python 3.12 tests and ships the sequential campaign/coverage/quality/explorer/integrity/recovery/concurrency evidence chain without enabling a worker, daemon, service, autostart, or concurrent manifest writer.
- Subtitle cutover at `iter-2026-09-subtitle-transcript-sqlite` (integration revision `d1a0b7e`):
  `probe-subs` and `harvest-subs` run on `archive.db` only, store normalized, content-idempotent
  transcripts, and write no sidecar or projection file. Suite at the cutover: 1314 passed,
  4 skipped (the skips are the opt-in live gates), with the bounded live smoke recorded (one
  public part, `stored=1`, `segments=2913`). Contract detail:
  [normalized-transcript-storage.md](normalized-transcript-storage.md) — the store, the process
  records, and the bootstrap guard — and
  [subtitle-acquisition-contract.md](subtitle-acquisition-contract.md) — the pin-verified
  acquisition boundary and the track preference.
- Queue-bridge update at `iter-2026-09-queue-bridge` (plan `20260919-sqlite-queue-bridge`):
  `derive-manifest` joins the archive-writer command family and the projection/feeder boundary bullet
  above now states the shipped enumeration instead of the deferral it used to record. The bridge's
  contract — additive conflict policy, the single derived status, the effective-key limit — is
  [queue-derivation-bridge.md](queue-derivation-bridge.md). Suite at the plan's gate: 110 passed /
  1 skipped over the bridge's four test files (QA `approve`, targeted).
- Artifact-root update at `iter-2026-09-artifact-root` (plan `20260919-artifact-root`): the product tree
  (`audio/`, `transcripts/{srt,txt,md,raw}/`, `subtitles/raw/`) is relocatable with
  `--artifact-root`/`BILI_ARTIFACT_ROOT` on the eleven commands that resolve an artifact path, while
  `manifest/`, `archive.db`, `coordinator/` and the sidecars stay at the archive root; audio is retained by
  default, with `--keep-audio/--no-keep-audio` on the five archiving commands. The split, the two-base
  ordered read rule, the re-based confinement guard and the four refusal lines are
  [artifact-root-split.md](artifact-root-split.md); the operator surfaces are
  `bilibili-asr-archive/README.md:391-433` and `bilibili-asr-archive/docs/artifact-root.md`.
