---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260911-subtitle-cli-cutover"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: DeepSeek Harness leaf seat (provider/model id is not exposed to this session; Model tier: standard)
- Review Perspective: service correctness and contracts; run/transaction integrity through the CLI; operator-level
  idempotency; test non-vacuity at branch scale (plan QC L3, whole branch, seat 2 of 3)
- Report Timestamp: 2026-09-11

## Scope

- plan_id: 20260911-subtitle-cli-cutover
- Review range / Diff basis: `c5a9b82..8373817` (4 commits)
- Working branch (verified): `feature/20260911-subtitle-cli-cutover` (`git branch --show-current`)
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover`
  (`git rev-parse --show-toplevel`; package root `bilibili-asr-archive/`)
- Commit range (identical to the review range): `8373817` docs → `d5c0f9e` live smoke → `c501d9a` offline E2E →
  `8ec992b` feat cli, on base `c5a9b82`
- Files reviewed: 13 files, +4597/−574 (`git diff --numstat`): `cli.py` (+262/−127),
  `services/subtitle_ingest.py` (+595 new), `tests/test_subtitle_cli.py` (+1074 new),
  `tests/test_subtitle_e2e.py` (+812 new), `tests/test_live_subtitle_cli_smoke.py` (+1303 new),
  `tests/fixtures/fake_bilibili_gateway.py` (+80/−4), `tests/test_cli_asr.py`, `tests/test_subtitles.py`,
  `tests/test_mixed_outcome_contract.py`, `tests/test_page_pipeline.py`, `tests/test_persistence_scale.py`,
  `docs/metadata-storage.md`, `README.md`
- Deep review: **triggered** (S1: 4597 changed lines / 13 files ≥ 200 lines & ≥ 8 files; S3: no `{KNOWLEDGE_DIR}`
  document names the subtitle CLI or its service module — `grep` over `.mstar/knowledge/` finds no
  `probe-subs`/`harvest-subs`/`SubtitleIngestor`; S6: `src/bili_asr/services/` + `src/bili_asr/cli.py` + `tests/` +
  `tests/fixtures/` + `docs/` ≥ 3 module boundaries)
- Lenses applied: Correctness Lens, Bounds Lens, Error Handling Lens, Testing Lens, Real-Entry-Path Lens,
  Enforcement-Path Lens, Ownership / Derived-State Lens, Reliability Lens
- Analysis methods: `git diff` / `git log` / `git show`, `read`, `grep`, schema and helper cross-reads against the
  shipped sources. **No test, build, lint, or live-network run** (role NEVER rules; `BILI_LIVE_SMOKE` never set,
  no credential file sourced). No worktree mutation, no commit, no checkout.

## Independently verified at branch scale

Everything below was re-derived from the shipped sources and tests, not restated from the L2 reports.

### 1. Service correctness (`src/bili_asr/services/subtitle_ingest.py`)

| Claim | Evidence |
|---|---|
| Candidate selection + two row shapes normalized into one work item | `_candidate_items:389-414` (`list_selected_parts` when `bvid` is set, else `list_pending_subtitle_parts`, `rows[:limit]` for the explicit path); `_pending_work_item:251-259` reads 12-col `v_pending_subtitles` (`bvid`,`cid`), `_selected_work_item:262-275` reads 11-col `v_video_parts` (no `bvid`) and takes the caller's selector. View column lists confirmed against `schema.sql` (v_video_parts) and `schema-transcripts.sql:122-141`. |
| `cid` always from `video_parts` | Both normalizers read `row["cid"]`; `_SubtitleWorkItem` carries `(work_id, bvid, cid, video_part_id)`; the only two gateway calls are `get_subtitle_tracks(item.bvid, item.cid)` (`:427`, `:456`) and `fetch_subtitle_segments(track, item.bvid, item.cid)` (`:470-472`). No pagelist call exists on this path. |
| Track selection: family + CC-before-AI; exact `--language` order; unmatched valid preference → `no-subtitle` | `language_family:100-116`, `_DEFAULT_LANGUAGE_FAMILY_ORDER = ("zh","en")` (`:67`), `select_subtitle_track:128-167` (`min` over `(family_rank, is_ai, upstream_index)`; the `languages` branch matches `track.language == preference` exactly, first matching preference wins, then `(is_ai, index)`); `_acquire_part:463-468` maps `track is None` to `_record_captionless_part(..., None, ...)` → attempt `no-subtitle` with a NULL code, never `failed`. |
| One repository call per part | `_acquire_part:446-479` ends in exactly one of `_record_caption` (`:502-518` → `record_acquired_transcript`), `_record_captionless_part` (`:542-549` → `record_subtitle_attempt`), `_record_failed_part` (`:568-575` → `record_subtitle_attempt`). No partial-write group spans two repository methods. |
| Run lifecycle: one row, `kind='subtitle'`, selector, bound, credential, derived outcome | `harvest:325-372`: `_selector:278-290` (`("pending", None)` / `("bvid", target)`, `bvid:pN` formatted with `format_work_id`), `start_acquisition_run` with `_choice(_ACQUISITION_KIND, "kind", ALLOWED_ACQUISITION_KINDS)`, `requested_limit=selection.limit`, `credential_present=self._credential_present`, `started_at=self._clock()`; then the derived `finish_acquisition_run(run_id, self._clock())` (`:358`). Derivation lives in `database.py:1263-1283` (`failed` iff failed == attempts > 0, else `partial` iff any failed, else `complete`) — matches spec §5 and the empty-selection case. `schema-transcripts.sql:62-65` enforces the selector/target pairing at DB level. |
| `failed` closure when an error escapes the per-part loop | `harvest:351-357` wraps the whole `asyncio.run(self._acquire_parts(...))` in `try/except BaseException: self._finish_failed_run(run_id); raise`; `_finish_failed_run:374-387` finishes with the explicit `failed` outcome and deliberately swallows its own failure so it cannot mask the escaping exception (verified: `finish_acquisition_run(outcome="failed")` is accepted because `_TERMINAL_ACQUISITION_OUTCOMES` admits it). |
| "Write nothing at all on probe" | `probe:316-323` → `_probe_parts`/`_probe_part` only; no repository write is reachable (`_probe_part:423-432` catches `GatewayError` into `error_code`). E2E pins the observables: `test_subtitle_e2e.py:638-687` (empty root when no database; after seeding exactly `["archive.db"]`, `body_cids == []`, all four evidence tables at 0) and `:692-714`. |
| Vocabulary validation (carried obligation) | `_choice:76-89` + `_caption_source_kind:92-97` validate `subtitle-cc`/`subtitle-ai` against `ALLOWED_CAPTION_SOURCE_KINDS` and `subtitle` against `ALLOWED_ACQUISITION_KINDS` — drift fails with a bounded `ValueError` before SQLite. |

### 2. Transaction / integrity through the CLI

- **Nothing half-written.** `record_acquired_transcript` (`database.py:892-956`) does the version insert, the
  segment `executemany`, and the attempt insert inside one `with _transaction(self.connection)` — commit on
  success, `rollback()` + re-raise on any exception (`_transaction:224-237`), with the attempt row written last.
  `record_subtitle_attempt` (`:1002-...`) is the same single-transaction shape. `start_acquisition_run`
  commits independently (`:787`) so an aborted part cannot delete the run parent — and cannot leave a transcript
  without its attempt evidence either way.
- **No wrongly-terminal attempt.** `schema-transcripts.sql:86-94` is a DB-level CHECK matrix: `failed` ⇒
  `error_code IS NOT NULL AND transcript_id IS NULL`; `no-subtitle` ⇒ code `NULL|'not_found'` and
  `transcript_id IS NULL`; `stored`/`unchanged` ⇒ code NULL and `transcript_id NOT NULL`. `PRIMARY KEY
  (run_id, video_part_id)` plus append-only attempts mean a part is re-attemptable after `no-subtitle`
  (pinned by `test_subtitle_cli.py:833-864` and `test_subtitle_e2e.py:548-598`).
- **A failing part does not abort the rest.** `_acquire_part` resolves `GatewayNotFound` → `no-subtitle` and any
  other `GatewayError` → `failed` *as a value*, never as an exception, so the sequential loop in
  `_acquire_parts:434-444` always runs the whole bounded set; the CLI prints the counts and exits `0` on partial
  failure (`cli.py:915-917`, `test_subtitle_cli.py:933-956`). See QC2-001 for the one direction the tests do not pin.
- **The probe never creates a write surface that persists.** `cli.py:559-581` checks the file before
  `open_database`, and `probe-subs` is absent from `_ARCHIVE_WRITER_COMMANDS` (`cli.py:2435-2445`), pinned by an
  equality assertion in `test_persistence_scale.py:424-437`. See QC2-003 for the connection-mode nuance.
- **Exit taxonomy through the CLI is coherent with the data.** `probe` exits `2` only when every selected part
  failed (`cli.py:820-822`), never on a partial `failed=`; `harvest` exits `2` only when
  `attempted > 0 and failed == attempted` (`:915-917`); both print `""` on stdout for every exit-1 path
  (`test_subtitle_cli.py:235-241` asserts `captured.out == ""` for the whole usage matrix).
- **Unexpected error path.** `cli.py:793-797` / `:890-894` print the fixed `<command>: unexpected error` line and
  return `2`; `test_subtitle_cli.py:959-981` additionally asserts the run row is closed `failed` with
  `finished_at` set, zero attempts written, and no sentinel leakage.

### 3. Idempotency at the operator level

- The E2E re-run assertion is real and complete (`test_subtitle_e2e.py:375-436`): after a second
  `harvest-subs --bvid BVID --limit-parts 5` it pins the printed `unchanged subtitle-cc zh-CN v1`, `versions == [1]`,
  the *exact* two-row segment set, both attempts pointing at **one** `transcript_id`
  (`len({attempt[3]}) == 1`), and both runs `complete`.
- **Would the hash comparison being removed be caught?** Precisely: dropping the `content_sha256` predicate from
  the `existing_row` lookup (`database.py:895-903`) leaves this test green (`unchanged` is still the answer), but it
  reddens `test_a_revised_caption_appends_version_two_and_keeps_version_one_readable` (`:439-496`), which requires
  `versions == [1, 2]` for the revised body — that is the non-vacuous half. Removing the *whole* lookup (always
  append) reddens the unchanged test as well. The pair covers both directions; neither is a substring check.
- Version-1 readability after a revision is asserted through the repository's own read path
  (`read_transcript(part_id, "subtitle-cc", "zh-CN", 1)`, `:484`), not by re-querying raw columns.
- Nuance worth recording (not a defect): the *pending* path is not the idempotent one — a second identical
  `--limit-parts N` run advances to the next pending parts by the locked enumeration
  (`test_subtitle_cli.py:772-791`), which is the spec §4 design. The `unchanged` guarantee is asserted on the
  explicit `--bvid` re-check path, which is exactly the operator workflow the plan's Done criterion names.

### 4. Non-vacuity of the high-value guards (guard → the case that fails on revert)

| Guard introduced by this plan | Test that fails on revert | My reconstruction of the revert |
|---|---|---|
| Default preference = CC before AI in the same family | `test_default_preference_picks_the_uploader_caption_for_chinese_pairs` (`test_subtitle_cli.py:367-383`, 16 params = 4 CC codes × 2 AI codes × both upstream orders) + `test_default_preference_stores_the_uploader_caption_when_both_are_visible:584-597` | M1/A: flipping the `min` key at `subtitle_ingest.py:160-167` to AI-first fails the property table in both orders. Reconstructed from the key, no run. |
| Family ranking `zh` → `en` → rest | `test_default_preference_ranks_known_families_then_falls_back_to_upstream_order:386-409` | Changing `_DEFAULT_LANGUAGE_FAMILY_ORDER` (`:67`) or dropping the family term reorders `(AI_ZH, CC_EN)` and `(french, english_ai)`. |
| Exact `--language` order + unmatched → `no-subtitle` | `test_explicit_language_matches_exactly_and_first_preference_wins:412-425`; `test_language_preference_reaches_the_ai_track:600-631`; `test_unmatched_language_preference_is_no_subtitle_with_no_fetch:634-671` | Prefix/`in` matching instead of `==` (`:152-158`) selects the wrong track or `[]`→ wrong outcome; the unmatched case also pins `body_cids == []` and a NULL-code `no-subtitle` attempt. |
| Outcome mapping (4 bounded codes → `failed <code>`; `not_found` → `no-subtitle`) | `test_bounded_gateway_failures_map_to_failed_with_their_code:869-906` (4 params) and `test_not_found_is_recorded_no_subtitle_with_its_code:909-930` (listing + body stages) | Mapping `not_found` to `failed`, or `GatewayError` to `no-subtitle`, fails both the printed line and the attempt-row tuple. |
| Exit taxonomy | `test_subtitle_usage_errors_exit_one_never_two:233-241` (10 argv params), `test_probe_subs_exits_two_when_every_selected_part_failed:466-481`, `test_partial_failure_keeps_exit_zero...:933-956`, `test_harvest_subs_reports_an_empty_pending_selection_as_complete:674-697` | Making any usage error exit 2, or `failed=1` of 2 decide the exit code, fails a named case. |
| Guard line composition (CLI composes prefix + root) | `test_both_commands_print_the_fixed_rebuild_line_for_a_legacy_database:1047-1074` — whole-`err` equality including the absolute `<archive.db>` path, while `SchemaContractError` (`database.py:169-178`) carries neither prefix nor root | M3: `print(f"{command}: {exc}")` cannot pass, because the raised message says literally `delete archive.db` and the test demands `delete {database_path}`. |
| Writer-set membership (`probe-subs` out) | `test_persistence_scale.py:424-437` (exact frozenset equality) + `test_neither_command_writes_a_sidecar_or_a_transcript_projection` (probe → exactly `["archive.db"]`, `test_subtitle_cli.py:1023-1044`, E2E `:692-714`) | F: putting `probe-subs` back makes the writer lock appear and both tests fail. |
| Probe zero-write boundary | E2E `test_probe_subs_prints_the_locked_lines_and_leaves_nothing_behind:638-687` (missing DB ⇒ `_archive_files == []`; seeded ⇒ `["archive.db"]`, `body_cids == []`, four tables empty) + `test_subtitle_cli.py:296-306` (absent root is not created) | E: routing the probe through `open_database` without the file guard creates `archive.db` in the empty root and fails both. |
| Credential presence composition (`--sessdata` and env, printed line + run row) | `test_credential_is_reported_as_presence_only:986-1020` and E2E `test_the_env_sourced_credential_is_reported_as_presence_and_composed_into_the_run_row:756-812` (both assert `sessdata: present|absent` **and** `credential_present`/`=1`/`=0` in the run rows, plus `fake_gateway_seam.sessdata`) | D/H: hard-coding `credential_present=False` at `cli.py:786/880` or always printing `absent` fails at least these two cases. |
| F3 seam strictness | `test_bilibili_api_gateway.py` (untouched: `git diff --stat` over it is empty) + shared `_scripted:411-417` (AssertionError on an unscripted fetch) reused by the two new subtitle methods | See §5. |

That is 6 of the 8+5 mutation claims spot-checked by inspection (M1/A, M3, C-adjacent always-append, D, F, G via
the enumeration test, H) — all consistent with the implementer's table without being able to execute it.

### 5. F3's integrity (the shared `FakeGateway` double)

- **`tests/test_bilibili_api_gateway.py` is not in this branch at all** — `git diff --stat c5a9b82..8373817` over
  that path is empty, so the package-seam suite (30+ subtitle cases) is byte-identical.
- The fixture's deletions are **exactly four lines, all docstrings** (verified verbatim:
  3 lines of the module bullet and 1 line of the class docstring, both rewritten); `_scripted`,
  `DOCUMENTED_METADATA_CALLS`, `assert_only_documented_metadata_calls`, `FakeUpstreamScript`, `Api`, and
  `bilibili_api_seam` are untouched. The new `get_subtitle_tracks:391-396` / `fetch_subtitle_segments:399-405`
  go through the same shared `_scripted` loud-fail helper, and the new `fake_gateway_seam:863-888` fixture is
  additive (one new `__all__` entry). So the metadata call-list strictness is provably not weakened.
- The two recordings the CLI tests rely on (`listing_cids`, `body_cids`) are appended by the double itself, which is
  what makes "the body was never fetched" and selection order assertable (`test_subtitle_e2e.py:295-296`,
  `:518-519`).

### 6. Blast radius outside the two commands

- Only two production files changed: `src/bili_asr/cli.py` and the new
  `src/bili_asr/services/subtitle_ingest.py` (`git diff --name-only ... -- src/`). The
  `_open_read_connection` extraction (`cli.py:502-527`) is behaviour-preserving for its only consumers, `status`
  (`:1057`) and `runs` (`:1296`): same guard, same two messages, same `MetadataRepository` wrap.
- The legacy subtitle producer is still reached by the untouched chain, so the cutover cannot have moved the
  ASR/pilot path: `subtitles.harvest_subtitle` is called from `coordinator.py:636` and `cli.py:1683`, and the two
  rewritten command handlers are reachable only from argparse dispatch (`cli.py:2465-2468`). The risk-ceiling
  behaviour that the deleted command-level test covered is still covered on its live path
  (`test_cli_pilot.py:454`, `test_scheduler.py:599`, `test_long_live.py`).
- The deleted legacy tests are all of behaviour that no longer exists: 19 deleted `def`s are the legacy
  `probe-subs`/`harvest-subs` command cases plus the `_cli_routes` helper (whose only users were deleted), and the
  `unresolved` / `excluded_from_page_processing` vocabulary they asserted has no counterpart in the SQLite model
  (`_ALLOWED_PROCESSING_STATUS = {"discovered","metadata_collected","gone"}`, `models.py:24`). No `pytest.mark` or
  fixture line was deleted anywhere, so no surviving test lost a parametrization.
- No stale caller of the two commands remains in shipped code or docs (grep over `src/`, `README.md`,
  `docs/`: only the archived `docs/archive/pre-iteration-2026-09/*` historical plans still show the old
  `harvest-subs --limit` form). The parser's replacement of `--limit` by `--limit-parts` (`cli.py:129-167`) is the
  documented semantic replacement the plan mandates.

## Findings

### 🔴 Critical

None. No security, data-loss, or wrong-terminal-state defect found: the attempt/transcript consistency is enforced
by a DB CHECK matrix, the per-part boundary is a single transaction, and no display path carries a credential,
signed URL, or raw body (verified against `NO_LEAK_MARKERS` + `persisted_row_text`, which render **every** table and
view, with the failing part scripted to carry four sentinels at once).

### 🟡 Warning

None. Nothing found is reachable in normal operation with operator-visible wrongness; the numeric and integrity
contracts of spec §1/§2.2/§5 hold in the shipped code and are pinned by whole-output assertions.

### 🟢 Suggestion

- **[QC2-001]** A bounded run's "a failing part does not abort the remaining set" property is only pinned with the
  failing part **last** — no case scripts a per-part failure *before* a part that still succeeds in the same run.
  -> Script the failure on the first part (or order the parts so a failed part precedes a stored one) in
  `test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts`; a regression that aborted the loop on the
  first non-stored outcome would then redden instead of passing.
  - Source Type: deep-lens: Testing Lens
  - Verification: read/grep anchor — `test_subtitle_cli.py:933-956` (parts `101`=p0 stored, `102`=p1 with
    `listing_failures`), `test_subtitle_e2e.py:501-545` (`FAILING_CID` = p1, last), and
    `test_subtitle_cli.py:869-906` (both parts fail). `_acquire_parts:434-444` is structurally correct:
    `_acquire_part:446-479` returns `failed` as a value.
  - Expected vs observed: expected a case proving the loop continues *past* a failed part into a later success;
    observed failure-last (or all-failed) only, so early-abort is not excluded by assertion.
  - Confidence: High
- **[QC2-002]** The gateway bounds only the lower side of a caption timestamp, so the one per-row anomaly that
  escapes the bounded `failed` ladder aborts the **whole** run instead of one part.
  -> Either bound `to` at the gateway (a future touch — the adapter is outside this plan's file list) or map a
  store-side timeline rejection to a bounded per-part outcome; today's behaviour is exit `2` +
  `harvest-subs: unexpected error` with the run closed `failed`.
  - Source Type: deep-lens: Bounds Lens
  - Verification: read anchor chain — `bilibili_api_gateway.py:454-469` (`_read_caption_milliseconds` has no upper
    bound, only finiteness) → `:431-451` (drops only `start_ms < 0`, `end_ms <= start_ms`, empty text) →
    `storage/models.py:44` (`MAX_TIMELINE_MS = 10**12`) → `database.py:1227-1242` (`maximum=MAX_TIMELINE_MS`
    raises `ValueError`) → `subtitle_ingest.py:502-518` (`_record_caption` does not catch it) →
    `subtitle_ingest.py:351-357` (the run is finished `failed` and the error propagates to `cli.py:890-894`).
  - Expected vs observed: expected every per-part data anomaly to stay inside the bounded
    `rate_limited|transport_error|response_error|shape_error` → per-part `failed` contract; observed a
    finite-but-absurd upstream `to` (>1e9 s) is passed by the gateway and rejected by storage, taking the run down.
    Trigger is implausible for real data, hence Suggestion.
  - Confidence: Medium
- **[QC2-003]** "The probe never opens a write connection" is not literally true: `probe-subs` opens the same
  connection as `status`/`runs`, and `open_database` executes both idempotent schema scripts and commits.
  -> Either open the probe connection read-only (`file:...?mode=ro`) or leave the wording as the docs already have
  it (an enumerated, testable list); no observable promise is broken today.
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: read anchor — `cli.py:559-581` (`_open_subtitle_connection`) → `cli.py:502-527` →
    `database.py:186-200` (`open_database` → `initialize_schema`) → `database.py:148-166` (both `executescript`
    calls, then `connection.commit()`), and `_accepts_transcript_script:130-138` returns True for a healthy
    current database, so the transcript script runs too. Contrast the observables that **are** pinned:
    `test_subtitle_e2e.py:651/678/686`, `:703-705` (no new file, no lock, four evidence tables empty).
  - Expected vs observed: expected the strict reading (a read-only connection); observed idempotent DDL executed
    and committed on the probe path, with the file set/rows unchanged — the shipped `status`/`runs` discipline the
    spec deliberately reuses, and the docs' enumerated promise ("no database creation, no transcript row, no run or
    attempt row, no lock file", `docs/metadata-storage.md:190-194`) is accurate.
  - Confidence: High
- **[QC2-004]** The probe's stdout is the only place this CLI prints an upstream free-text field
  (`track <lan> <ai|cc> <label>`, `cli.py:810-812`, label = the upstream `lan_doc`), and the probe's sentinel scan
  is vacuous for that field — its scripted labels are benign, so no test would catch a leaked marker arriving
  through it. The docs sentence at `docs/metadata-storage.md:153` ("No output carries ... upstream message text")
  reads stronger than the line shape documented 20 lines above it.
  -> Script one marker-bearing label in the probe rehearsal and add
  `assert_leaks_no_markers(probe_out + probe_err, ...)` there, or scope the docs sentence to the error/evidence
  paths. Concordant with the Task-3 L2 review (its Minor 2); I re-judged it and agree it is a
  strength-of-assertion item, not a defect (the gateway deliberately never reads `subtitle_url`).
  - Source Type: deep-lens: Security Lens
  - Verification: read anchor — `cli.py:802-812` vs `test_subtitle_cli.py:430-456` (`assert_leaks_no_markers` runs
    on probe output, but the scripted labels are `中文（简体）`/`中文（自动生成）`), and
    `bilibili_api_gateway.py:279-295` (label trimmed and printed as-is; `subtitle_url` not read).
  - Expected vs observed: expected a no-leak scan that can fire on the field actually printed; observed a scan
    whose only probe-side input cannot carry a sentinel.
  - Confidence: High
- **[QC2-005]** The run record stores the selector but not the `--language` preference, so a preference-scoped
  `no-subtitle` is indistinguishable afterwards from "nothing was visible".
  -> Decide the disposition in a future touch (the run table belongs to the storage contract; a `languages`
  column or a bounded selector annotation would close it). Today the printed line and the docs state the reading,
  and re-attemptability is unaffected because the part stays pending.
  - Source Type: deep-lens: Ownership / Derived-State Lens
  - Verification: read anchor — `schema-transcripts.sql:50-67` (no language column),
    `subtitle_ingest.py:278-290` (`_selector` returns only `(kind, target)`), `:340-350` (`AcquisitionRunRecord`
    fields), `cli.py:842-850/882-889` (`languages` only travels into `SubtitleSelection`).
  - Expected vs observed: expected the persisted evidence to explain a `no-subtitle` attempt that was caused by the
    requested language rather than by an empty inventory; observed no persisted field can carry that fact.
  - Confidence: High
- **[QC2-006]** `finish_acquisition_run` sits outside the interrupted-run guard (`subtitle_ingest.py:358`), so the
  narrow path Task-1 recorded as M2 can leave a run row `running` while the CLI prints the bounded
  unexpected-error line. -> If the "a run is never left `running`" invariant is wanted literally, move the derived
  finish inside the `try`; otherwise keep it recorded as the Task-1 L2 review proposed.
  - Source Type: manual-reasoning (re-judged from the Task-1 L2 finding)
  - Verification: read anchor — `subtitle_ingest.py:351-358` (`try/except BaseException` ends before the finish
    call), `database.py:789-838` (`finished_at must not precede started_at`, re-finish rejected by
    `sqlite3.IntegrityError`), `cli.py:890-894`.
  - Expected vs observed: expected a closed run for every non-completing path; observed that only a backwards clock
    step or an I/O failure in that single call (plus a microseconds-wide Ctrl-C window) can leave `running` —
    hence Suggestion, not Warning. Concordant with the Task-1 L2 review's Minor 2 (also recorded in the plan).
  - Confidence: High
- **[QC2-007]** `_archive_files` walks file names only, so the "leaves nothing behind" assertions would not notice a
  newly created empty directory under the archive root. -> Assert the directory listing too if the stronger
  "writes nothing at all" reading is wanted; matches the spec's literal "no file" wording today.
  - Source Type: deep-lens: Testing Lens
  - Verification: read anchor — `test_subtitle_e2e.py:166-173` (`os.walk` `names` only, `_directories` discarded)
    used at `:651/678/703-714`, `:810-812`; `test_subtitle_cli.py:190-197` same helper. Concordant with the Task-2
    L2 review's Minor 2.
  - Expected vs observed: expected "no artifact at all" coverage; observed file-level coverage only.
  - Confidence: High
- **[QC2-008]** `tests/test_subtitle_cli.py:58` imports the private helper `_write_pre_iteration_database` from
  another test module, coupling two test files through a private name. -> Cosmetic; promote it to
  `tests/fixtures/` if a third consumer appears. Concordant with the Task-1 L2 review's Minor 4 and the plan's
  recorded M4 (no rework proposed).
  - Source Type: read
  - Verification: read anchor — `test_subtitle_cli.py:58` and its only use at `:1053`.
  - Expected vs observed: expected shared test scaffolding under `tests/fixtures/`; observed a cross-module private
    import. Harmless and offline.
  - Confidence: High
- **[QC2-009]** In the live smoke, three parsed evidence fields are re-emitted without an assertion tying them to
  their source (`with_tracks`, `stored`, and the printed `run_id`), and the live test body itself is never executed
  offline (the rehearsals duplicate its assertions rather than driving the same function), so its summary assembly
  and its `outcome not in ("stored","unchanged")` skip branch rest on the single recorded run. -> One-line
  strengthening (`assert harvest.stored == 1`, the printed `run_id` against the persisted row) and a sentence in
  the smoke's documented outcomes for the `sessdata=absent` skip. Concordant with the Task-3 L2 review (Minors 4-5).
  - Source Type: deep-lens: Testing Lens
  - Verification: read anchor — `test_live_subtitle_cli_smoke.py:832-846` (the evidence line),
    `:913-940` (the offline rehearsals, none of which calls the live test body), `:728-746` (the gate and the
    skip path).
  - Expected vs observed: expected every printed live field to be required by an assertion; observed three fields
    printed from parsed values that nothing asserts live.
  - Confidence: High

### ⚪ Unconfirmed

None. Every evidence channel this seat needs (review range reproducibility, readable diff, readable sources and
tests) was intact, and every finding above is anchored in shipped source. The two items that cannot be settled from
a read-only seat are **evidence gaps for L4/PM, not findings** — recorded in the ⚠️ section below.

## Source Trace

| Finding | Source Type | Source Reference | Confidence |
|---|---|---|---|
| QC2-001 | deep-lens: Testing Lens | `tests/test_subtitle_cli.py:933-956`, `tests/test_subtitle_e2e.py:501-545`, `services/subtitle_ingest.py:434-479` | High |
| QC2-002 | deep-lens: Bounds Lens | `sources/bilibili_api_gateway.py:431-469`, `storage/models.py:44`, `storage/database.py:1227-1242`, `services/subtitle_ingest.py:351-357,502-518` | Medium |
| QC2-003 | deep-lens: Enforcement-Path Lens | `cli.py:502-527,559-581`, `storage/database.py:148-166,186-200`, `tests/test_subtitle_e2e.py:651,678,686,703-714` | High |
| QC2-004 | deep-lens: Security Lens | `cli.py:802-812`, `tests/test_subtitle_cli.py:430-456`, `sources/bilibili_api_gateway.py:279-295`, `docs/metadata-storage.md:153` | High |
| QC2-005 | deep-lens: Ownership / Derived-State Lens | `storage/schema-transcripts.sql:50-67`, `services/subtitle_ingest.py:278-290,340-350`, `cli.py:842-850,882-889` | High |
| QC2-006 | manual-reasoning (Task-1 L2 Minor 2 re-judged) | `services/subtitle_ingest.py:351-358`, `storage/database.py:789-838`, `cli.py:890-894` | High |
| QC2-007 | deep-lens: Testing Lens | `tests/test_subtitle_e2e.py:166-173,703-714`, `tests/test_subtitle_cli.py:190-197` | High |
| QC2-008 | read | `tests/test_subtitle_cli.py:58,1053` | High |
| QC2-009 | deep-lens: Testing Lens | `tests/test_live_subtitle_cli_smoke.py:728-746,832-846,913-940` | High |

## L2 severity re-judgment (independent)

- **Task-1 Minor 1** (probe reads a listing `not_found` as `failed`, can exit 2): re-judged **no action** — this is
  the locked contract (plan M1 + brief), documented in `docs/metadata-storage.md:170-180` and rehearsed offline on
  both sides in `tests/test_live_subtitle_cli_smoke.py:1121`. Not a defect.
- **Task-1 Minor 2** (finish outside the guard): re-judged **Suggestion** → QC2-006. Not escalated; the reachable
  triggers are a backwards clock step or an I/O failure in one call.
- **Task-1 Minor 3** (env credential path unasserted for these commands): **verified discharged** by Task 2 —
  `tests/test_subtitle_e2e.py:756-812` asserts the env value reaching the adapter and the run row's
  `credential_present` in both directions. No residual.
- **Task-1 Minor 4** (private cross-module test import): re-judged **Suggestion** → QC2-008 (cosmetic).
- **Task-2 Minor 1** (the implementer's metadata-clock claim is wrong): **verified** —
  `MetadataIngestor.__init__` takes no clock and calls the module-global `_now()`, so the metadata fixture is
  effective; the plan's recorded-nit block already carries the correction. Not to be propagated into the durable
  summary as "the metadata test clock is broken".
- **Task-2 Minor 2** (`_archive_files` blind to directories): re-judged **Suggestion** → QC2-007.
- **Task-2 Minor 3** (M3's probe-absent branch in another test): informational, no action.
- **Task-3 Minors 1-6**: all re-judged as **Suggestion / informational**, none escalatable. Minors 2, 4, 5 are
  carried as QC2-004 and QC2-009 (with my own anchors); Minor 3 (the docs' live line omits `run_id=`) and Minor 6
  (module organisation) stay cosmetic; Minor 1 (the report overstates README coverage of M1) is a report-accuracy
  note, and I confirmed the README defers to `docs/metadata-storage.md` for the full contract
  (`README.md:585-588`).
- **No blocker found in any L2 finding or in the branch as a whole**, so nothing is escalated.

## ⚠️ Needs L4/QA verification or a PM decision (not findings)

1. **`Needs L4/QA verification: the offline suite counts`** — `1251 → 1261 → 1279 passed`, `3 → 4 skipped`, and
   `git diff --check` clean are implementer-reported only; this seat is forbidden to run pytest/build/lint. The
   arithmetic is internally consistent (65 + 10 = 75 for the focused pair; +18 for the live module's offline
   rehearsals) and the deletions are accounted for above, but the plan's "Offline suites green" Done criterion
   should be accepted on QA evidence, not on my read.
2. **`Needs L4/QA verification: the live smoke run`** — the recorded `live subtitle CLI smoke evidence:` line and
   the three-invocation ledger (one bounded run was budgeted) cannot be reproduced from a read-only seat and the
   committed range contains a single test commit (17:16:27, after all three attempts), so the aborted attempts'
   file states are unrecoverable. The disclosed fix shapes are visible in the final file
   (non-autouse credential fixture `:861-871`, `_flush_output:873-881`) and I found no acceptance-carrying fact in
   the evidence line that the module's assertions do not require, but the run's *occurrence* is the operator's
   evidence. PM: record the deviation rather than normalizing it (concordant with the Task-3 L2 review).
3. **PM decision, already flagged by two seats:** the spec's §6 sentence "neither command creates a file under the
   archive root except `harvest-subs`'s database writes" versus the shipped writer lock. The lock is now documented
   in both docs and pinned as exact behaviour by `tests/test_subtitle_e2e.py:710`, so the gap is only the spec's own
   wording, which this plan does not own. No action needed for this plan's Done gate.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 9 |
| ⚪ Unconfirmed | 0 |

Plus 3 ⚠️ items for L4/PM (suite counts, live-run reproducibility + invocation ledger, the spec §6 writer-lock
wording). Every Suggestion is either an assertion-strength/coverage item or a recorded-nit disposition with no
shipped-behaviour defect, so none of them blocks the plan's Done path under `zero-residual`: each has a named
disposition (fix in a later touch, accept and record, or verify-and-close).

**Verdict**: Approve

Rationale: the two command handlers are thin composition roots over a service that owns selection, the per-part
transaction, the run lifecycle, and the outcome mapping exactly as the locked spec requires; the integrity chain is
enforced twice (service + DB CHECK matrix) with a single transaction per part and a monotonic run lifecycle whose
only weak point is a microsecond window on an I/O or clock anomaly; the iteration's operator-visible promises
(four counts including zeros, run id, credential presence, remaining count, no coverage claim, probe writes
nothing, exit taxonomy, documented preference) are each pinned by whole-output assertions that fail on a revert;
the E2E's idempotency and versioning assertions are real rather than ceremonial (the hash-comparison revert reddens
the revised-caption case while the unchanged case still passes, and the always-append revert reddens the unchanged
case); F3 consolidated the double without weakening the seam (four docstring-only deletions, `test_bilibili_api_gateway.py`
untouched, the shared loud-on-unscripted helper reused); and nothing outside the two commands moved, with every
deleted test belonging to behaviour that no longer exists. Zero Critical and zero Warning means the tri can clear
this seat without a fix round; the Suggestions are for the zero-residual register.

## Revalidation

Targeted re-review of the plan-QC fix wave (`8373817..7e57eb6`) — seat 2 of 3, appended to this report; no new file
was created and `qc1.md` / `qc3.md` were not touched.

### Scope and method

- Fix review range: `8373817..7e57eb6`, 9 files, **+899/−92**, re-read from `qc-fix-diff.md` and confirmed against
  `git diff --numstat` (read-only): `README.md` 34/10, `docs/metadata-storage.md` 49/15, `cli.py` 100/7,
  `services/subtitle_ingest.py` 38/18, `sources/bilibili_api_gateway.py` 14/7, `sources/models.py` 34/1,
  `tests/test_bilibili_api_gateway.py` 80/0, `tests/test_live_subtitle_cli_smoke.py` 232/24,
  `tests/test_subtitle_cli.py` 318/10. No `storage/` file and no `tests/test_subtitle_e2e.py` in the wave.
- Checkout verified read-only: `HEAD` = `7e57eb62d35d33b8effee6b21bac8b0b8f4d70c1`, branch
  `feature/20260911-subtitle-cli-cutover`, `git status --porcelain` empty. No commit, checkout, or push by this seat.
- Exactly one command was run, the sanctioned offline one:
  `pytest tests/test_subtitle_cli.py tests/test_subtitle_e2e.py -q` → **91 passed in 2.90s** (81 + 10 collected per
  file), 0 failed, 0 skipped. No live gate: `BILI_LIVE_SMOKE` unset, `BILI_SESSDATA` unset, no credential file
  sourced, no credential value printed or inferred. `tests/test_live_subtitle_cli_smoke.py` was **not** executed
  (outside the sanctioned command); its new rehearsals are verified by inspection (see Observation 3).
- Method: the fix diff read once, then every claim checked against the post-fix sources in the worktree
  (`cli.py`, `services/subtitle_ingest.py`, `sources/models.py`, `sources/bilibili_api_gateway.py`,
  `storage/database.py`, `storage/models.py`, both test modules, both docs) plus the deletion inventory below. No
  subagent, no delegation, no network.

### Per-item verification

#### QC2-001 — Closed (test named; the ordering is now pinned in the non-vacuous direction)

- Test: `tests/test_subtitle_cli.py::test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts:1063-1125`.
  The failure is now scripted on the **first** selected part (`listing_failures={101: GatewayRateLimited()}`, p0) and
  the **second** part still succeeds (`segments={102: BODY}`, p1).
- All four required assertions exist and are discriminating: exit 0 (`main(...) == 0:1082`); call order
  `gateway.listing_cids == [101, 102]` and `gateway.body_cids == [102]:1099-1100`; the attempt rows in part order
  `[("failed","rate_limited",False), ("stored",None,True)]` (`:1114-1122`); the stored transcript identity
  `(cid, page_index) == (102, 1)` with `("subtitle-cc","zh-CN",1)` (`:1103-1113`); plus exact whole-stdout equality
  including `harvest BV1SubA:p1 stored subtitle-cc zh-CN v1` (`:1090-1096`), run outcome `partial:1123`,
  `transcripts == 1` and `transcript_segments == 2:1124-1125`.
- What fails if the loop aborted early on a failure: **(a) abort-by-raise** — the exception reaches `harvest`'s
  `except BaseException` → `_finish_failed_run` → CLI exit `2`, so `:1082` reddens first and the run row reads
  `failed` instead of `partial`; **(b) abort-by-stop** — p1 is never listed, so `listing_cids == [101]`, the exact
  stdout list has no p1 line, the attempt-row list has one element, and `transcripts` is 0 — four independent
  assertions redden. The deleted version of this test scripted the failure **last**, which is precisely the
  direction where an early abort could still read green; the E2E's `FAILING_CID` case keeps the failure-last
  direction, so both orders are now pinned.

#### QC2-002 — Closed (the anomalous part alone fails; the run continues; the row carries the bounded code)

- `_record_caption` wraps its single repository call in `try/except ValueError:527-538` and answers with
  `self._record_failed_part(run_id, item, GatewayShapeError(), started_at)`; `GatewayShapeError().code` is
  `"shape_error"` (`sources/models.py:257`, admitted by `validate_error_code`) and `_record_failed_part:579-599`
  persists exactly that scalar code with outcome `failed`.
- Test: `tests/test_subtitle_cli.py::test_a_body_the_storage_boundary_refuses_is_one_parts_bounded_failure:1128-1199`.
  It scripts part 101 (first) with `SubtitleSegment(start_ms=0, end_ms=MAX_TIMELINE_MS + 1)` — a value the DTO and
  the segment record accept but the storage boundary rejects — and part 102 with a normal body. Confirmed as
  specified: exit `0` with `stderr == ""`; exact stdout `p0 failed shape_error`, `p1 stored subtitle-cc zh-CN v1`,
  summary `attempted=2 stored=1 unchanged=0 no-subtitle=0 failed=1 remaining_without_transcript=1`; attempt rows
  `[("failed","shape_error",False), ("stored",None,True)]`; run outcome `partial`; `transcripts == [(102, 1)]` so the
  refused part stored no transcript and no segment; and `remaining_without_transcript=1` proves the part stayed
  pending for a later attempt. On revert (no catch) the `ValueError` escapes → exit `2` +
  `harvest-subs: unexpected error` → several assertions redden.
- The corrected comment is accurate: the ceiling is enforced **pre-transaction** — `record_acquired_transcript`
  validates and canonicalizes at `storage/database.py:875-890` (`_canonical_segments:1208-1247`, `maximum=MAX_TIMELINE_MS`
  at `:1231/:1237`) and only then opens `with _transaction(self.connection):892`. "Nothing was written and nothing
  needs rolling back" is literally true for this path; and were a `ValueError` raised inside the transaction,
  `_transaction:224-237` rolls back before the catch, so fail-then-record-attempt stays consistent either way.
- Bound width checked: only `ValueError` is caught, so a genuine `TypeError` still escapes, and the pre-call
  vocabulary validation (`_caption_source_kind` at `subtitle_ingest.py:507`) sits outside the `try`, so schema
  vocabulary drift still fails loudly. The new bound is no wider than "data the storage boundary itself refuses".

#### QC2-003 — Closed (the read-only connection cannot write; proven, not asserted by convention)

- `probe-subs` now opens `_open_read_only_connection:542-578`: `sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro",
  uri=True)`, sets `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON` (client-side and per-connection, no
  file write), and takes its first read (`PRAGMA schema_version:568`) inside the bounded handler so a
  not-a-database file is reported as the shipped `unreadable archive database` line rather than crashing.
  `_open_subtitle_connection(read_only=True):628-632` is the only caller, and `probe-subs` is still absent from
  `_ARCHIVE_WRITER_COMMANDS:2528-2538` (no lock).
- Write-proof, in two independent halves
  (`test_subtitle_cli.py::test_the_probe_opens_the_archive_read_only_and_cannot_write:1266-1328`): the test asserts
  the probe opened **exactly one** connection with `keywords == {"uri": True}` and the exact
  `…as_uri() + "?mode=ro"` URI (`:1294-1301`); it then re-opens that identical URI and shows `CREATE TABLE`,
  `DELETE FROM transcripts`, and `INSERT INTO acquisition_runs` each raise `sqlite3.OperationalError` (`:1315-1316`),
  so a future edit that wrote on the probe path would fail inside SQLite instead of reaching the file. The probe
  run's observables are then re-asserted unchanged (`_archive_files == ["archive.db"]`, all four evidence tables 0,
  `:1321-1328`).
- The connection is also sufficient for the repository contract it is handed to: `_validate_connection:208-220`
  requires only the `sqlite3.Row` factory and `foreign_keys = 1`, both established here, and
  `require_subtitle_schema:169-183` only reads. `archive.db` is in the default rollback-journal mode (no
  `journal_mode` pragma anywhere in `storage/`), so a read-only open needs no `-shm`/`-wal` write; the legacy-database
  case inside the 91 (`test_both_commands_print_the_fixed_rebuild_line_for_a_legacy_database:1355-1382`) exercises
  the read-only path against a pre-iteration file as well. The fix changed the mechanism rather than the wording,
  which is the stronger reading of QC2-003.

#### QC2-004 — Closed (the probe surface is scanned, and the scan is shown to fire there)

- Live call site: `tests/test_live_subtitle_cli_smoke.py:871`
  `assert_leaks_no_markers(probe_out + probe_err, context="live probe output")`, placed immediately after
  `_read_probe_output` and before the harvest, so a sentinel arriving through the printed label fails the smoke.
- The scan's ability to fire on that surface is rehearsed offline rather than assumed:
  `test_the_probe_surface_scan_catches_a_sentinel_arriving_as_a_track_label:1139-1183` scripts
  `SIGNED_SUBTITLE_URL_MARKER` as the track label, asserts the marker really reaches stdout (`:1173`), asserts
  `assert_leaks_no_markers` raises on that output (`:1176-1177`), and asserts the same scan is silent with the
  sentinel replaced (`:1180-1183`) — neither vacuous nor a blanket failure. `assert_leaks_no_markers` raises
  `AssertionError` (`tests/fixtures/fake_bilibili_gateway.py:835-840`), which is what the rehearsal expects; the
  marker itself carries no control character, so it still passes the new DTO rule and really reaches the print path.
- Docs scoped as specified: `docs/metadata-storage.md:153-159` now reads "The error and evidence paths carry no
  credential, a signed URL, a raw body, or raw upstream message text: a bounded scalar code stands in for whatever
  upstream said", then names the one printed upstream **metadata** value (`lan_doc` on the `track` lines), its
  trimming, and the new bounded `shape_error` rejection that keeps the one-line-per-track shape intact. The README's
  live section carries the matching sentence (`README.md:707`).
- Still an assertion-strength item, not a defect: the gateway never reads `subtitle_url`
  (`bilibili_api_gateway.py:293-294`); it is now pinned in both directions.

#### QC2-009 — Closed (fields tied to their source; an opted-in run cannot silently skip)

- Probe counts derived from the part line: `with_tracks == (1 if track_count else 0)`,
  `without_tracks == (1 if track_count == 0 else 0)`, `failed == (1 if error_code is not None else 0)`, and
  `probed == with_tracks + without_tracks + failed` (`:437-448`).
- Harvest counts tied to the single part line: the four counts must equal the 1-of-4 vector implied by the outcome
  and must partition `attempted` (`:499-519`), and the stored/unchanged pair is additionally asserted against the
  outcome in the live body (`:908-910`).
- Printed `run_id` tied to the persisted row: `_assert_stored_rows(run_id=…)` asserts `run["run_id"] == run_id`
  (`:648-650`) and `_assert_no_transcript_rows` the same (`:735-737`), with every call site passing the **printed**
  id (live body `:911-915`, `:931-936`; rehearsals `:1052-1057`, `:1065`, `:1074-1078`, `:1088-1092`). A printed id
  that did not name the persisted run cannot pass.
- **The credential precondition cannot silently skip an opted-in run.** The live body's first statement is
  `_live_preconditions():846`, whose only `pytest.skip` is gated on `not _live_smoke_requested():270-274`; past that
  gate `_require_live_credential:236-257` calls `pytest.fail` (not `skip`), and its expectation comes from the same
  shipped rule the command uses (`resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR)):233`, where a blank value
  resolves to `None` — `config.py:139-141`). The only way to skip is therefore to not have opted in at all; the
  ambiguous `sessdata=absent tracks=0` reading is unreachable for an opted-in run. The new offline gate test
  `test_the_live_preconditions_gate_in_the_documented_order:1052-1091` drives exactly that: default → `skip` naming
  `BILI_LIVE_SMOKE=1`; opted in without the variable → `fail` naming it and refusing the "benign skip"; a blank value
  → refused; a resolvable credential → returns `None` and proceeds. The remaining `_record_and_skip` calls in the live
  body are the documented bounded-observation path (a `rate_limited`/`not_found`/no-caption reading printed with its
  evidence), not a credential shortcut — and with the credential made mandatory, such a reading can no longer be an
  artefact of anonymous access.
- Layer judgment: the precondition lives in the smoke, which is correct — the command's anonymous mode is the
  shipped contract, and it was the live gate's *reading* of it that was ambiguous.

#### QC2-005 — Verified recorded (durable plan entry, no code change in this wave)

`.mstar/plans/20260911-subtitle-cli-cutover.md:342-344` carries it verbatim: "Recorded (QC2-005, storage-side decision
for a later owner): the acquisition run row does not persist the `--language` preference, so a preference-scoped
`no-subtitle` outcome is indistinguishable from a generic one after the fact. Persisting it would be a schema column
decision (a storage owner's), not a CLI change." No schema or storage change was attempted in this wave (no `storage/`
file in the 9-file diff), which is the disposition the consolidation chose. PM-only note: like Q3-06, the entry names
the decision class rather than a concrete owner/trigger — plan-text precision, not a QC residual.

#### QC2-006 / QC2-007 / QC2-008 — unchanged recorded nits

No rework proposed and none attempted: `finish_acquisition_run` is still outside the interrupted-run guard
(`subtitle_ingest.py:362`), `_archive_files` is still file-only (`test_subtitle_cli.py:187-194`), and the private
cross-module test import is still at `test_subtitle_cli.py:62`.

### Regression lens — the 92 deleted lines and the integrity chain

I enumerated every `-` line of the fix diff from `qc-fix-diff.md`, per file, and checked each against the post-fix
source. **No existing assertion was weakened**; the deletions are all moves, re-indentations, prose reflows, or
replacements that are strictly stronger:

| File | − | What the deleted lines were | Finding |
|---|---|---|---|
| `README.md` | 10 | prose reflow of the preference rule, the schema-guard paragraph, the lock sentence, the live paragraph | reflowed and strengthened (family-blind CC clause, stderr + `DEFAULT_PAGE_LIMIT`, lock-before-check, loud credential) |
| `docs/metadata-storage.md` | 15 | prose reflow + the quoted live line | replaced by the scoped no-leak sentence (`:153-159`), the lock paragraph (`:195-201`), the credential bullet (`:519-529`) and the `run_id=`-bearing evidence line |
| `src/bili_asr/cli.py` | 7 | the missing-DB guard body, `_open_subtitle_connection`'s signature, the probe's call | moved into `_archive_database_exists:502-516` (same line, same exit) and the probe call now passes `read_only=True` |
| `src/bili_asr/services/subtitle_ingest.py` | 18 | the `record_acquired_transcript(...)` block | pure re-indentation into `try:`; all 9 keyword arguments present at `:510-526` |
| `src/bili_asr/sources/bilibili_api_gateway.py` | 7 | the `return VideoSummary(...)` block | re-indented into `try:`; all 5 arguments present at `:179-185` |
| `src/bili_asr/sources/models.py` | 1 | `_text(self.text, "text")` in `SubtitleSegment` | re-pointed at the mirrored caption validator, not dropped |
| `tests/test_live_subtitle_cli_smoke.py` | 24 | the live preamble (skip + pin assert), eight inline `int(summary[...])` reads, three helper signatures/docstrings | preamble moved verbatim into `_live_preconditions` (skip `:271`, pin assert `:275`); the reads became locals that are now *also* asserted; call sites pass `run_id` |
| `tests/test_subtitle_cli.py` | 10 | the old partial-failure body | replaced by exact whole-stdout equality plus per-row evidence; the `transcripts == 1` scalar is kept |
| `tests/test_bilibili_api_gateway.py` | 0 | — | additive only |

- The deletion audit is corroborated by test-count arithmetic rather than resting on it: the focused pair collects
  `81 + 10 = 91` at HEAD, and this seat's pre-fix report recorded the implementer's `65 + 10 = 75`. The growth of 16
  is exactly the new material (7 params of `test_an_unstorable_bvid_is_answered_as_unknown_bvid` + 1
  `…outranks_the_missing_database_guard` + 1 `…cc_before_ai…rest_families` + 1 storage-ceiling case + 1 read-only
  probe case + 5 new usage params), i.e. no existing parametrization was lost. Both files are green at HEAD:
  **91 passed**, 0 failed, 0 skipped.
- The previously-verified integrity chain is untouched by the new per-part exception handling:
  - **Per-part transaction** — no `storage/` file is in the fix range; `record_acquired_transcript`'s single
    `with _transaction(...)`, the version/segment/attempt write order and the rollback discipline
    (`storage/database.py:892-956`, `:224-237`) are unchanged, and the new `except ValueError` sits strictly around
    the call without introducing a write path of its own.
  - **Run always closed** — `harvest`'s `try/except BaseException → _finish_failed_run`
    (`subtitle_ingest.py:355-361`) and `_finish_failed_run:378-391` are unchanged; the new catch only shrinks the set
    of escapes reaching that guard.
  - **CHECK matrix** — `storage/schema-transcripts.sql` is untouched (same no-`storage/` argument), and the refused
    part's evidence `("failed","shape_error", transcript_id NULL)` is exactly the matrix's `failed` row, asserted
    through the joined attempt query.
  - **Idempotency** — `tests/test_subtitle_e2e.py` is not in the fix range at all (10 tests, byte-identical); its
    `unchanged` / version-2 / single-`transcript_id` / both-runs-`complete` assertions are unchanged and green.
  - **Writer set / probe writes nothing** — `tests/test_persistence_scale.py` untouched, `probe-subs` still outside
    `_ARCHIVE_WRITER_COMMANDS`, and the probe's read-only path is additionally pinned by the new test.
  - The one deliberate behaviour change on an existing path is the probe no longer running the two idempotent schema
    scripts; the only other new strictness is the operator-facing text rule, whose metadata path stays bounded via
    `metadata_ingest.py:251` (`except GatewayError` → recorded page outcome).

### F-003 judgment — does the caption vs `lan_doc` split preserve the storage layer's verbatim-caption contract?

Yes, and the split is directional in the safe way:

- **Caption bodies accept exactly what they accepted before.** `SubtitleSegment.text` now calls
  `sources/models.py::_caption_text:46-60`, whose rule is identical to `storage/models.py::_caption_text:99-112` — a
  string, non-empty after stripping, control characters **kept**. Pre-fix it called `_text`, which also kept control
  characters, so no caption that used to be accepted is now refused, and none that used to be refused is now
  accepted. The gateway's multi-line case is pinned by the additive
  `test_caption_text_keeps_interior_control_characters_as_one_row`, which requires a cue containing `\n` and `\r` to
  survive as one row; the adapter trims the cue (`bilibili_api_gateway.py:455`) and the boundary stores and hashes
  the trimmed text verbatim (`storage/database.py:1243-1246`, `_segment_content_sha256`), which is the contract the
  split now mirrors at the DTO.
- **The new rejection is confined to fields the storage layer already rejects.** `VideoSummary.bvid/title`,
  `VideoPart.bvid/title`, `SubtitleTrack.language` and `SubtitleTrack.label` all have storage twins validated
  through `storage/models.py::_text:65-72` (bvid `:154/:186`, title `:158/:189`, language `:374` and
  `database.py:695-702`). Nothing the store would accept is refused by the DTO; the DTO merely fails earlier, with
  the bounded vocabulary. `track_id` (`sources/models.py:152`) is the one field with no storage twin (upstream
  identity, never persisted) — over-strictness there can only reject a pathological id, and the adapter already
  rejects non-integer ids before the DTO sees one.
- **The metadata side stays bounded.** The new
  `except (TypeError, ValueError) → GatewayShapeError(detail="video item is not normalizable")`
  (`bilibili_api_gateway.py:178-191`) is caught by `metadata_ingest.py:251`'s `except GatewayError` and recorded as a
  bounded page outcome, exactly like the sibling item-level shape errors that already existed; the additive
  `test_get_user_video_page_rejects_a_title_with_control_characters` pins the code and the call shape.
- The presentational consequence is the intended one: an upstream `lan_doc` carrying a control character now costs
  the listing (`shape_error` on that part) instead of splitting the locked one-line-per-track shape — which is what
  F-003 asked for, and what `docs/metadata-storage.md:153-159` now states.

### Observations (not findings; no action requested)

1. `unknown --bvid <value>` echoes the operator's own argv verbatim, so a selector carrying `\n`/`\r`/`\x00` renders
   raw on stderr (a `\n` splits the printed line). It is not a leak channel — the value is the operator's argument,
   carries no upstream or credential data, and the fixed line shape is exactly what F-001 required, pinned
   byte-for-byte by `test_an_unstorable_bvid_is_answered_as_unknown_bvid:258-307`. No action.
2. The QC2-005 entry names the decision class ("a storage owner") rather than a concrete owner/trigger; the
   consolidation gives Q3-06 the same PM-text treatment. No QC residual.
3. **Evidence boundary for this seat**: the two new offline rehearsals in `tests/test_live_subtitle_cli_smoke.py`
   (`test_the_live_preconditions_gate_in_the_documented_order`, `test_the_probe_surface_scan_catches_a_sentinel_arriving_as_a_track_label`)
   were verified by inspection, not executed — the sanctioned command covers only the two files above. Their
   execution, the full-suite count, and the re-taken live run remain the QA hand-off items already listed in
   `qc-consolidated.md`. Nothing in my items rests on them: QC2-004's guard and QC2-009's credential gate are
   verified at their call sites, and each expectation the gate test names was checked against the definition it
   relies on (`pytest.skip.Exception`, `pytest.fail.Exception`, `assert_leaks_no_markers` → `AssertionError`).

### Updated counts

| Severity | Pre-fix (this seat) | Post-revalidation |
|----------|--------------------|-------------------|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 0 | 0 |
| 🟢 Suggestion | 9 | **5 closed** (QC2-001/002/003/004/009 — each with a named assertion or mechanism that fails on revert), **4 dispositioned by record** (QC2-005 in the plan's durable roadmap; QC2-006/007/008 recorded nits) → **0 items without a disposition** |
| ⚪ Unconfirmed | 0 | 0 |
| 🆕 New findings raised by this re-review | — | **0** (Critical 0 / Warning 0 / Suggestion 0) |

The fix wave's own changes were each checked for a widened failure surface — a read-only connection, a per-part
`ValueError` bound, an operator-facing text rule, a loud live precondition, and the assertion strengthening — and
none was found; the three observations above are presentational or evidence-boundary notes, not defects.

### Verdict (post-revalidation): **Approve**

All five fix-wave items attributed to this seat are closed **as specified** rather than merely present: QC2-001's
ordering case reddens on both early-abort shapes, QC2-002's refusal is one part's bounded `shape_error` with the run
continuing and the anomaly's silence proven by `remaining_without_transcript=1`, QC2-003's connection is functionally
write-proof through the very URI the probe used, QC2-004's scan is exercised on the surface it guards, and QC2-009's
printed fields are tied to the rows they claim while an opted-in run without a credential can only fail. QC2-005 is
durably recorded in the plan and QC2-006/007/008 keep their recorded-nit dispositions. The 92 deleted lines contain no
weakened assertion, and the integrity chain this seat verified at branch scale — per-part transaction, run always
closed, CHECK matrix, idempotency, writer set — is untouched by the new per-part exception handling; the F-003 split
preserves the storage layer's verbatim-caption contract. Zero Critical, zero Warning, zero new findings: the seat
clears the fix wave. Frontmatter verdict remains `Approve`.
