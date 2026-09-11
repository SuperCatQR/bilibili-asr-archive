# Task 1 report — Subtitle ingest service and CLI commands

- Plan: `.mstar/plans/20260911-subtitle-cli-cutover.md` (task 1 of 3)
- Working branch: `feature/20260911-subtitle-cli-cutover`
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover`
- Commit: `8ec992b` — `feat(cli): cut probe-subs and harvest-subs over to the SQLite subtitle path`
- Status: **DONE_WITH_CONCERNS** — the contract is implemented and the whole offline suite is green;
  the concerns are two interpretation decisions (below, §Self-review 1–2) and the required legacy
  test churn (§Disclosures), each disclosed rather than silently absorbed.

## Implemented (per brief item)

1. **Service** — `src/bili_asr/services/subtitle_ingest.py` (new, 595 lines) defines
   `SubtitleIngestor` plus the five locked dataclasses (`SubtitleSelection`, `SubtitleProbePart`,
   `ProbeResult`, `SubtitlePartOutcome`, `HarvestResult`), the spec-locked `language_family`, and
   the selection helper `select_subtitle_track`.
   - **Candidate enumeration** (`_candidate_items`): `--bvid` → `list_selected_parts` (every stored
     part of the video, already-transcribed included, `limit`-truncated when given); otherwise
     `list_pending_subtitle_parts(limit)`.
   - **Row-shape normalization** (carry item): the two selections answer different shapes — the
     pending view carries `bvid`/`cid`, `v_video_parts` carries no `bvid` — so each is normalized by
     its own constructor (`_pending_work_item`, `_selected_work_item`) into one private
     `_SubtitleWorkItem(work_id, bvid, cid, video_part_id)` before any gateway call.
   - **Per part**: `get_subtitle_tracks(bvid, cid)` → `select_subtitle_track` → `fetch_subtitle_segments`
     → `SubtitleSegment` → `TranscriptSegmentRecord` → `record_acquired_transcript`; the captionless
     and failed paths call `record_subtitle_attempt`.
   - **`probe`** writes nothing (no run, attempt, transcript, or file).
   - **`harvest`** opens exactly one `acquisition_runs` row (`kind='subtitle'`, selector, limit,
     credential presence, `started_at`) and finishes it with the repository-derived outcome
     (`complete | partial | failed`, including `complete` for an empty selection).
2. **Outcome mapping** — empty listing **or** `GatewayNotFound` on the listing **or** on the body →
   `no-subtitle` (attempt row carries `not_found` when upstream signalled it); `GatewayRateLimited` /
   `GatewayTransportError` / `GatewayResponseError` / `GatewayShapeError` → `failed` with that scalar
   code; a stub-free `stored` vs `unchanged` comes from the write result.
3. **`probe-subs`** — read-only; exactly one of `--bvid` / `--limit-parts`; missing database → the
   shipped read-command line + exit 1; unknown `--bvid` → `unknown --bvid <value>` + exit 1 (decided
   **before** anything is probed, and before a run row for harvest); `bvid:pN` via
   `page_identity.parse_work_id`; zero-track parts printed with their `(no subtitles visible)`
   marker and `tracks=0`; a failed listing printed as `probe <work_id> failed <error_code>` and
   counted in `failed=`; exit 2 only when every selected part failed; removed from
   `_ARCHIVE_WRITER_COMMANDS` (so: no writer lock, no file, no database creation).
4. **`harvest-subs`** — `--limit-parts` required unless a single `bvid:pN` is named; `--bvid`
   selects explicitly (stored parts included); missing database → the shipped
   `<command>: no archive database at <root>; run fetch-meta to create it` line + exit 1;
   `--language` parsed with empty entries rejected as usage errors; both commands call
   `require_subtitle_schema` after opening the database and print the fixed rebuild line with exit 1
   on `SchemaContractError`.
5. **Locked output** — `sessdata: <present|absent>`, one `probe`/`harvest` line per selected or
   attempted part in order, then the summary lines
   (`probe-subs: probed=… with_tracks=… without_tracks=… failed=…` /
   `harvest-subs: run_id=… attempted=… stored=… unchanged=… no-subtitle=… failed=… remaining_without_transcript=…`).
   All four counts print including zeros; nothing is printed on stdout for a usage/config error.
6. **Legacy manifest path removed from these two commands only** — both handlers no longer import
   `bili_client`, `subtitles`, or `ManifestStore`; every other command is untouched (see
   §Legacy behaviour replaced and §Disclosures).
7. **Tests** — `tests/test_subtitle_cli.py` (new, 65 offline cases, see §Tests); the legacy cases the
   two commands owned are updated in five existing test files (§Disclosures).

## Service composition and transaction boundary

```
cli handler:  usage checks → _open_subtitle_connection (existence check → open_database →
              require_subtitle_schema, with the composed rebuild line) → TranscriptRepository
              → BilibiliApiGateway(sessdata=…) → SubtitleIngestor → print
```

- The composition root is the CLI, exactly as the spec locks it: `MetadataRepository` is never
  constructed by these handlers, no metadata write path is touched, and the service never sees the
  concrete adapter or a response dictionary.
- **Transaction boundary**: one repository call per part — `record_acquired_transcript` (version +
  segments + the `stored`/`unchanged` attempt row in one transaction) or `record_subtitle_attempt`
  (one transaction for one captionless/failed attempt). Run start and run finish are their own
  commits, owned by the service; `finish_acquisition_run` derives the outcome from the attempt rows.
- **Interrupted-run invariant**: an unexpected error escaping the part loop finishes the opened run
  as `failed` before it propagates, so a run is never left `running` (pinned by a test).
- The gateway's async calls run on one `asyncio.run` per `probe`/`harvest` operation.
- **Vocabulary validation** (carry item QC1-003): the two storage literals the service writes — the
  caption `source_kind` of a selected track and the acquisition `kind` of a run — are derived through
  the private `_choice(value, field, allowed)` helper and checked against
  `ALLOWED_CAPTION_SOURCE_KINDS` / `ALLOWED_ACQUISITION_KINDS`, so a drift fails with a bounded
  message instead of a SQLite CHECK violation mid-run.
- **Guard-line ownership** (carry item QC3-005): `_subtitle_schema_rebuild_line(command, archive_root)`
  composes `<command>: archive database predates the transcript schema; rebuild it (delete
  <root>/archive.db and re-run fetch-meta)`; the test asserts the **whole** line, so
  `print(f"{command}: {exc}")` cannot pass.

## Legacy behaviour replaced (disclosure)

| Command | Before (removed) | After |
|---|---|---|
| `probe-subs` | `BiliClient.probe_subs(bvid)` against the manifest-era client; printed `<bvid>: <lan> — <lan_doc>` and, when empty, `<bvid>: no subtitles visible at this auth tier -> needs_audio (run harvest-subs to record it)`; exit 2 on a risk/terminal API answer; archive-writer command. | Read-only SQLite probe of one video's stored parts or the first N pending parts; `sessdata:` line, per-part `probe`/`track`/`tracks=0`/`failed <code>` lines and a four-count summary; no writes, no lock, no database creation; not an archive-writer command. |
| `harvest-subs` | `subtitles.harvest_subtitle` per `meta_ok` manifest row: AI-first `_LAN_PREFERENCE = ("ai-zh","zh-CN","zh-Hans","en")`, signed-URL download, `subtitles/raw/<stem>.json` + `transcripts/srt/<stem>.srt`, manifest status `subtitle_done`/`needs_audio`, `last_api_error_code`, `3.0s` inter-part sleep, `--limit N`, `risk-control ceiling` → exit 2. | Bounded SQLite acquisition: default preference is the language family (`zh`, then `en`, then the rest), CC before AI inside a family; `--language` matches upstream codes exactly (`ai-zh` keeps the AI track reachable); transcripts go to `archive.db` only; per-part attempt evidence; `--limit-parts` (required unless a single `bvid:pN`); partial failure stays in the counts with exit 0, exit 2 only for a whole-run failure or an unexpected internal error. |

Consequences recorded for the operator (docs are Task 3's deliverable): the new `harvest-subs`
writes no `subtitles/raw/*.json` and no `transcripts/srt/*.srt`, and it no longer produces the
manifest status `needs_audio`, so `download-audio --missing-subs` gains no new entries from the
SQLite path. The legacy ASR/pilot/run/coordinator path and `subtitles.pick_subtitle` keep the
AI-first order; nothing else imports them (drift check re-run, see §Self-review 8).

## Tests

Command (worktree, control interpreter — the worktree has no `.venv`):

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_subtitle_cli.py -v
```

Focused output (green):

```
65 passed in 1.89s
```

Full offline suite (same interpreter, worktree, after the change):

```
1251 passed, 3 skipped in 45.79s
```

Baseline was `1202 passed, 3 skipped`: **+65 new cases** in `tests/test_subtitle_cli.py`,
**−16 legacy cases** whose subject no longer exists (§Disclosures). `1202 + 65 − 16 = 1251` ✔

The suite was also run green in the mixed ordering that first exposed a test-isolation defect:
`pytest tests/test_metadata_cli.py tests/test_subtitle_cli.py` → `98 passed` (the package-seam
fixtures drop `bili_asr.sources.bilibili_api_gateway` from `sys.modules`; the fixture now resolves
the adapter through `importlib.import_module` instead of a stale parent-package attribute — recorded
because the naive form passed alone and failed in the full suite).

### New cases (65)

- Usage/exit taxonomy: `--limit-parts` required unless a single `bvid:pN`; exactly one probe
  selector; missing database → exit 1 with the shipped line for both commands; an absent archive
  root is not created; unknown `--bvid` (bare and `:pN` forms) → exit 1 with no upstream call and no
  run row; empty `--language` entry → exit 1; ten usage shapes asserted to exit 1, never 2.
- Preference: `language_family` derivation table (9); the CC-before-AI property for 4 Chinese CC
  codes × 2 AI codes × 2 upstream orders (16); family ranking (`zh` > `en` > rest, upstream order
  settles ties, `zh`-AI still beats `en`-CC); exact `--language` matching, first-preference-wins,
  CC-before-AI inside one preference, unmatched → `None`; CLI-level `--language ai-zh` reaches the
  AI track and an unmatched valid preference is `no-subtitle` with no body fetch.
- Output shapes: the exact `probe` line list (tracks lines with the label last, `tracks=0` +
  marker, `failed <code>`, summary) and the exact `harvest` line list (stored/unchanged/no-subtitle
  + the full summary); probe of an empty pending set → `probed=0 … failed=0` exit 0; harvest of an
  empty pending set → `attempted=0 … ` exit 0 with a `complete` run row.
- Persisted evidence: `acquisition_runs` shape (kind/selector/limit/credential/outcome/finished_at),
  the four attempt rows with their codes and timestamps, transcript versions, source kinds,
  segment count.
- Enumeration/re-acquisition: four successive `--limit-parts 1` runs attempt `[101, 102, 201, 101]`
  (never-attempted first, then the oldest attempt); explicit `--bvid` re-runs stored parts as
  `unchanged`; a single `bvid:pN` needs no bound and records `selector_target="BV1SubA:p1"`;
  `stored` → `unchanged` → `v2` with v1 still stored; a captionless part stores a transcript in a
  later run.
- Outcome mapping/exit codes: the four bounded failures → `failed <code>` (attempt row + `failed`
  run) with exit 2 when all parts fail; `not_found` from the listing and from the body →
  `no-subtitle` + `not_found`; one stored + one failed → exit 0 with `partial` run; an unexpected
  `RuntimeError` → stdout empty, `harvest-subs: unexpected error`, exit 2, run finished `failed`,
  no sentinel leaked.
- Boundaries: credential presence only (adapter received the value, output/rows carry none);
  `probe-subs` leaves exactly `archive.db` (no lock) and `harvest-subs` leaves exactly `archive.db` +
  `coordinator/archive-writer.lock`, with no `manifest/manifest.jsonl`, `meta-cursor.json`,
  `run-ledger.jsonl`, `coordinator/attempts.jsonl`, `subtitles/raw/…`, or `transcripts/srt/…`; the
  exact rebuild line for a pre-iteration database with `status` still working.

### Red/green (non-vacuity) evidence

Five deliberate mutations, each applied to the shipped source, run against the focused file, then
reverted (`64 passed` again after each revert; final state `65 passed`, `git diff --check` clean):

| # | Mutation | Result |
|---|---|---|
| M1 | default preference restored to the legacy AI-first order (`pair[1].is_ai` → `not …`) | `18 failed, 46 passed` — the property table and every default-selection CLI case |
| M2 | `probe-subs` never returns the terminal code (`return 2` → `return 0`) | `1 failed` — `test_probe_subs_exits_two_when_every_selected_part_failed` |
| M3 | guard line degrades to `print(f"{command}: {exc}")` | `1 failed` — the rebuild-line test asserts the whole line incl. the root path |
| M4 | `"probe-subs"` re-added to `_ARCHIVE_WRITER_COMMANDS` | `4 failed` — the no-file/no-lock assertions |
| M5 | listing `GatewayNotFound` mapped to `failed` | `1 failed` — `test_not_found_is_recorded_no_subtitle_with_its_code[listing]` |

## Files changed

- `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py` (new, 595 lines)
- `bilibili-asr-archive/src/bili_asr/cli.py` (+262/−127) — parser for the two commands, the
  read-connection extraction, the subtitle composition helpers, both handlers, the writer-set change
- `bilibili-asr-archive/tests/test_subtitle_cli.py` (new, 1118 lines, 65 cases)
- `bilibili-asr-archive/tests/test_subtitles.py` (+7/−236) — legacy CLI section removed, docstring
  points at the new file
- `bilibili-asr-archive/tests/test_page_pipeline.py` (−54) — the two legacy `harvest-subs` cases removed
- `bilibili-asr-archive/tests/test_mixed_outcome_contract.py` (−72) — the two legacy `harvest-subs`
  cases removed; the download-audio/asr/pilot/run halves untouched
- `bilibili-asr-archive/tests/test_cli_asr.py` (+42/−43, 6 → 5 cases) — rewritten setup
- `bilibili-asr-archive/tests/test_persistence_scale.py` (+3/−1) — writer set + one negative assertion

## Disclosures — legacy behaviour replacement and every changed assertion

**Removed with their replaced behaviour (16 cases; each superseded by a named new case):**

| Removed case | Was asserting (legacy) | Superseded by |
|---|---|---|
| `test_subtitles.py::test_cli_probe_subs_empty` | `<bvid>: no subtitles visible … -> needs_audio` | `test_probe_subs_prints_track_lines_the_zero_track_marker_and_the_summary` (`tracks=0` + marker) |
| `::test_cli_probe_subs_unknown_bvid_api_error_does_not_create_row` | API error → exit 1, no manifest row | `test_unknown_bvid_is_configuration_and_opens_no_run` |
| `::test_cli_probe_subs_transport_error_redacts_exception_message` | transport error → exit 2, redacted | `test_probe_subs_exits_two_when_every_selected_part_failed`, `::test_credential_is_reported_as_presence_only` |
| `::test_cli_probe_subs_lists_entries` | `ai-zh` printed from the client entries | `test_probe_subs_prints_track_lines_…` (track lines) |
| `::test_cli_harvest_subs_marks_needs_audio` | manifest `needs_audio` written by harvest | `test_unmatched_language_preference_is_no_subtitle_with_no_fetch` (the new "nothing visible" outcome), §Legacy behaviour replaced |
| `::test_cli_harvest_subs_downloads_and_marks_done` | `subtitle_done` + raw/srt files written | `test_default_preference_stores_the_uploader_caption_when_both_are_visible` (transcript row instead) |
| `::test_cli_harvest_sessdata_env_not_echoed` | env credential used, never echoed | `test_credential_is_reported_as_presence_only` |
| `::test_cli_harvest_api_error_preserves_status_and_mixed_batch_fails` | mixed API failure → exit 1 + `last_api_error_code` | `test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts` |
| `::test_cli_harvest_budget_exhausted_exit_2` | risk ceiling → exit 2, statuses preserved | `test_bounded_gateway_failures_map_to_failed_with_their_code[rate_limited]` |
| `::test_cli_harvest_skips_done_and_needs_audio` | manifest status filters | `test_bounded_pending_runs_advance_through_the_captionless_backlog` (pending-set semantics) |
| `::test_cli_harvest_bvid_filter` | manifest bvid filter → `needs_audio` | `test_explicit_bvid_selects_every_stored_part_including_a_stored_one` |
| `test_page_pipeline.py::test_cli_harvest_skips_unresolved_and_processes_other_page` | `unresolved` manifest rows skipped | `test_unknown_bvid_is_configuration_and_opens_no_run` (no manifest is read at all) |
| `::test_cli_harvest_subs_bvid_unresolved_stops` | unresolved bvid → exit 1 | ditto |
| `test_mixed_outcome_contract.py::test_harvest_subs_mixed_success_and_api_failure_is_retryable` | retryable mixed failure, exit 1, no ledger/attempts sidecar | `test_partial_failure_keeps_exit_zero_…`, `::test_neither_command_writes_a_sidecar_or_a_transcript_projection` |
| `::test_harvest_subs_success_then_risk_exit_2_keeps_success` | risk interruption → exit 2 with durable success | `test_bounded_gateway_failures_map_to_failed_with_their_code` (exit 2 = every part failed) |
| `test_cli_asr.py::test_cli_harvest_risk_exhaustion_preserves_last_stable_status` | harvest risk ladder preserved the last stable manifest status | ditto |

**Changed, not removed (assertions rewritten minimally):**

- `test_cli_asr.py`: the module docstring now says the ASR/audio path starts from a pre-cutover
  manifest state; a new `_legacy_subtitle_state()` helper drives the still-shipped
  `subtitles.harvest_subtitle` directly (the producer `harvest-subs` no longer is). The harvest
  **assertions** in the four remaining cases were replaced by that helper's return value
  (`== "needs_audio"` / `== "subtitle_done"`) plus the same status/artifact assertions as before;
  two case names lost the `meta_ok_` prefix (`test_cli_audio_branch_needs_audio_audio_ok_archived`,
  `test_cli_subtitle_branch_subtitle_done_archived_skips_asr`) because that transition is no longer
  part of what they drive. Their download-audio/asr assertions are byte-identical.
- `test_persistence_scale.py::test_cli_dispatch_locks_every_archive_mutation`: `"probe-subs"`
  removed from the expected `_ARCHIVE_WRITER_COMMANDS` set, plus one new assertion
  `"probe-subs" not in cli._ARCHIVE_WRITER_COMMANDS` (the brief's explicit requirement).
- `test_subtitles.py`: docstring gained a pointer to `tests/test_subtitle_cli.py`; the now-unused
  `import pytest`, `from bili_asr.cli import main` and `_cli_routes` helper were removed with the
  deleted section.

No assertion in an untouched module was weakened, and no test was deleted without a named
replacement above.

## Self-review notes

1. **`credential_present` on the constructor — interpretation, disclosed.** The spec's §5 surface
   block locks `probe`/`harvest` and the dataclasses but shows `__init__(self, gateway, repository,
   *, clock=…)` with a pseudocode `...`. `HarvestResult.credential_present` / `ProbeResult.credential_present`
   and the run row's `credential_present` have to come from somewhere, and the spec also says the
   service "depends on the `BilibiliGateway` protocol and `TranscriptRepository` only — never on the
   concrete adapter". The protocol has no credential accessor, and the adapter file
   (`sources/bilibili_api_gateway.py`) is **not** in this plan's file list (it is where residual R1
   lives), so reading adapter state from the service was not an option. The credential presence is
   therefore a keyword-only constructor argument with a default, exactly like `clock`; the CLI
   passes `sessdata is not None`. Flagged for the reviewer rather than silently diverging.
2. **`selector_target` records the operator's own selector** (`"BV1SubA"` or `"BV1SubA:p1"`,
   reconstructed with the archive's `page_identity.format_work_id`) because §2.2 says the run row
   carries "`selector_kind`/`selector_target` **from the selector**". A `bvid:pN` run is therefore
   distinguishable from a whole-video run in the row. Also disclosed: the service imports
   `page_identity.format_work_id` (archive vocabulary, no third-party dependency) instead of
   re-spelling `f"{bvid}:p{page_index}"`.
3. **`unknown --bvid` is decided in the CLI before the run opens** — it reads
   `list_selected_parts` once for the emptiness check and the service then enumerates the same view.
   The double read is deliberate: a configuration error must not open (and finish) an empty run row,
   and the fixed message is a CLI concern. Both reads are read-only on a bounded join.
4. **`--limit-parts` truncates an explicit `--bvid BVID` selection** in the service
   (`list_selected_parts` takes no limit), so "every run is bounded" holds on that path too.
5. **Output is printed after the service call**, so a usage/config error or an unexpected error
   leaves stdout empty (fetch-meta's discipline). The spec fixes the *order* of the lines, not
   whether `sessdata:` precedes the work.
6. **`harvest-subs` stays a writer command**, so `main()` wraps it in `archive_writer` and exactly
   `coordinator/archive-writer.lock` may appear besides `archive.db` — asserted exactly, and
   contrasted with `probe-subs`, which leaves only `archive.db`. Every other writer command
   (`fetch-meta`, `asr`, `run`, …) behaves identically; the spec's "no file except its database
   writes" is read as the transcript-projection boundary (no `subtitles/raw/`, no `transcripts/srt/`,
   no sidecar), which the tests pin.
7. **The service relies on the gateway contract that a body fetch never returns an empty tuple**
   (`fetch_subtitle_segments` raises `GatewayNotFound` instead). Should a gateway ever return `()`,
   the repository's `ValueError` surfaces as the bounded `unexpected error` / exit 2 with the run
   finished `failed` — an honest failure instead of a silent `no-subtitle`.
8. **Drift check re-run**: no other module imports `subtitles.pick_subtitle`/`_LAN_PREFERENCE`
   (only `subtitles.harvest_subtitle`, which the untouched pilot/run/coordinator paths call), no
   other command depends on the two changed handlers, and no other command's behaviour was touched.
9. **Handoff, not a residual**: `README.md` (e.g. line 103's `harvest-subs` example, the writer-set
   list, and the `need_audio`/projection wording) and `docs/metadata-storage.md` still describe the
   legacy surface. The plan assigns both files to **Task 3**, so they were left untouched here —
   they are wrong until Task 3 lands, and `docs/metadata-storage.md:51-56` (QC3-003) is Task 3's own
   bullet. `--help` text for the two commands **was** updated here (it lives in `cli.py`) and states
   the bound requirement and the CC-before-AI default.
10. **STOP conditions**: none triggered. The manifest is untouched for ASR/pilot; every run is
    bounded (no retries or loops were added — one call per part, at most one extra listing inside
    the delivered adapter's own expiry handling); no output or row carries a URL, raw body,
    cookie, or traceback (sentinel scans over stdout+stderr and over every persisted row);
    the path needs no second executable (same `bili-asr` entrypoint) and no second metadata source
    of truth (`archive.db` only); and `probe-subs` is genuinely read-only — it is out of
    `_ARCHIVE_WRITER_COMMANDS`, so the read-only promise is structural and pinned by tests.
11. **Scope discipline**: no plan, snapshot, status, spec, compass, or docs file was written; the
    only file outside the worktree I wrote is this report. Commit `8ec992b` is on
    `feature/20260911-subtitle-cli-cutover` only; nothing was pushed; no live-network command ran
    (`BILI_LIVE_SMOKE` was never set).
