---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260911-subtitle-cli-cutover"
verdict: "Approve"
original_verdict: "Request Changes"
revalidation_range: "8373817..7e57eb6"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist (seat 1 of 3)
- Runtime Agent ID: qc-specialist
- Runtime Model: standard tier (DSH-delegated subagent route; provider/model id not exposed to this session)
- Review Perspective: spec compliance of the operator surface, the legacy cutover's
  completeness, and documentation accuracy
- Report Timestamp: 2026-09-11T17:32:50+08:00

## Scope

- plan_id: `20260911-subtitle-cli-cutover`
- Review range / Diff basis: `c5a9b82..8373817` (base = the iteration integration branch at feature cut; 4 commits)
- Working branch (verified): `feature/20260911-subtitle-cli-cutover`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover`
  (`git rev-parse --show-toplevel` = that path; `HEAD` = `8373817`; `git diff --stat c5a9b82..8373817`
  = 13 files, +4597/−574; the review-package's 13 `diff --git` headers match one-for-one)
- Files reviewed: 13 changed files (whole-branch package) + 20 supporting read-only files
  (plan, CLI spec §1–§8, SDD ledger, 3 L2 task reviews, `storage/database.py`,
  `storage/models.py`, `storage/schema-transcripts.sql`, `sources/models.py`,
  `sources/bilibili_api_gateway.py`, `subtitles.py`, `page_identity.py`, `config.py`,
  `tests/conftest.py`, the retained legacy test modules, the residual register)
- Commit range: `8ec992b` (service + CLI cutover) · `c501d9a` (offline E2E + F3 + M3) ·
  `d5c0f9e` (live smoke) · `8373817` (docs) — identical to the Review range
- Analysis methods: `git diff` / `git show` / file read / grep over shipped source, tests and docs;
  static code-path tracing; no test, build, lint, network or git-mutating command was run
- Deep review: **triggered** (S1: 4597 insertions / 13 files ≥ thresholds; S6: the diff crosses
  `src/bili_asr/services/`, `src/bili_asr/` (cli), `tests/` and `docs/` boundaries)
- Lenses applied: **Contract Lens** (docs-match-code is this seat's emphasis), **Modularity Lens**,
  plus a Bounds/Input-Validation sweep of the two argument surfaces, a Testing-Lens read of the
  legacy replacement mapping, and a Real-Entry-Path read of the cutover

## Findings

### 🔴 Critical

None.

### 🟡 Warning

- **F-001 — a blank or control-character `--bvid` value is reported as an *unexpected internal
  error* with exit `2`, instead of the documented `unknown --bvid` configuration error with exit
  `1`.** → Validate the selector value before the repository call (reject a blank/whitespace
  `--bvid` — and ideally any value carrying `\n`/`\r`/`\x00` — as a usage error in
  `_cmd_probe_subs` / `_cmd_harvest_subs` next to the existing selector/bound checks), or catch the
  `ValueError` around the `list_selected_parts` guard and report the fixed
  `<command>: unknown --bvid <value>` line with exit `1`.
  - Verification: input–output comparison by static code-path trace + diff/read/grep anchors.
    Trigger form: `bili-asr probe-subs --bvid "$BVID" --archive-root archive` with `BVID` unset, or
    `harvest-subs --bvid "" --limit-parts 5 …`, or any value carrying a newline.
    1. `cli.py:584-600` `_subtitle_selector`: `parse_work_id("")` raises `ValueError`, which is
       deliberately swallowed → the value is kept verbatim as a bare bvid (`("", None)`).
    2. `cli.py:770-777` (probe) / `cli.py:857-872` (harvest): the "unknown `--bvid`" guard calls
       `repository.list_selected_parts(bvid, page_index)` **because `bvid is not None`** — an empty
       string passes that test.
    3. `storage/database.py:1147` `bvid = _text(bvid, "bvid")` → `storage/models.py:65-72` raises
       `ValueError("bvid must not be empty")` (or the control-character branch for `\n`/`\r`/`\x00`).
    4. That `ValueError` is caught by the handler's broad `except Exception` at `cli.py:793-797`
       (probe) / `cli.py:890-894` (harvest) → `<command>: unexpected error`, exit `2`.
  - Expected vs observed: expected the documented fixed line `unknown --bvid <value>` with exit `1`
    — the CLI spec §2 (`subtitle-cli-contract.md:78-79`) pins *"a selector that resolves to zero rows
    in `video_parts` is a configuration error (exit `1`, fixed message `unknown --bvid <value>`), never
    an empty result"*; §2.1/§2.2 (`:119-123`, `:164-170`) reserve exit `2` for "failed on every
    attempted part" / "unexpected internal error"; §7 (`:327-330`) requires *"every usage error exits
    `1`, never `2`"*. The docs repeat the same promise — `docs/metadata-storage.md:99-101` ("A selector
    that resolves to no stored part is a configuration error — exit `1`, `unknown --bvid <value>`"),
    `docs/metadata-storage.md:161` and `README.md:603-607` (exit-`1` row lists "an unknown `--bvid`").
    Observed: exit `2` with `probe-subs: unexpected error` / `harvest-subs: unexpected error`, i.e. a
    documented configuration error presented as a system failure and a doc sentence that contradicts
    shipped behaviour. Contained blast radius: no write, no lock, no traceback, nothing leaked; the
    impact is the misreported taxonomy (an operator script branching on `$?` takes the terminal-failure
    branch for a fixable typo).
  - Confidence: High (deterministic three-file trace; no branch can absorb the `ValueError` earlier —
    `_subtitle_selector` catches only `parse_work_id`'s own `ValueError`, and both handlers' guards run
    outside any narrower `except`). Runtime reproduction for the acceptance record belongs to L4/QA:
    `bili-asr probe-subs --bvid "" --archive-root <root>` should print the `unknown --bvid` line and
    exit `1`.
  - Coverage gap in the same change: `tests/test_subtitle_cli.py:218-242`
    (`test_subtitle_usage_errors_exit_one_never_two`) parametrizes ten usage cases — including
    `--language ""` and `--limit-parts not-a-number` — but not a blank/whitespace `--bvid`, which is
    exactly why the deviation is not pinned red. Add the case to that table (or to
    `test_unknown_bvid_is_configuration_and_opens_no_run:309-340`).

### 🟢 Suggestion

- **F-002 — the docs present the schema-guard line as two lines; the command prints one line.**
  → Render the block as a single code line (or mark the wrap explicitly as a continuation), and state
  that the line goes to **stderr** while the probe/harvest output blocks are stdout.
  - Verification: diff/read/grep anchor. `docs/metadata-storage.md:243-244` shows
    `<command>: archive database predates the transcript schema; rebuild it` / `(delete
    <archive-root>/archive.db and re-run fetch-meta)` inside one `text` block; the shipped line is
    composed as one string (`cli.py:552-556`) and the test pins it byte-exactly on `captured.err`
    (`tests/test_subtitle_cli.py:1068-1071`).
  - Expected vs observed: expected the operator documentation to quote the locked line verbatim (the
    plan's Task-3 bullet calls it "the fixed rebuild line", and the spec §5 requires the composed
    line); observed a wrapped form, which fails a line-based `grep`/copy of the "fixed" line. Wording
    is otherwise correct, and the `<archive-root>/archive.db` placeholder is the real path shape.
  - Confidence: High (pure text comparison).

- **F-003 — `SubtitleTrack.label` (upstream `lan_doc`) is printed verbatim into the line-oriented
  probe surface; the DTO does not reject control characters, so a malformed upstream label would
  break the locked one-line-per-track shape.** → Harden `sources/models.py` `_text` (or
  `SubtitleTrack.__post_init__`) the same way the storage twin does — reject `\x00`/`\r`/`\n` — so the
  adapter answers `shape_error` at the boundary instead of injecting a line into the operator surface.
  - Verification: diff/read/grep anchors. `cli.py:810-812` prints
    `f"  track {track.language} {kind} {track.label}"`; `sources/models.py:34-39` `_text` checks only
    "non-empty after strip" (no control-character branch) and `SubtitleTrack` (`:97-118`) uses it for
    both `language` and `label`; the adapter only trims (`bilibili_api_gateway.py:281-300`); the
    storage-side twin `storage/models.py:65-72` **does** reject `\x00`/`\r`/`\n`, so the two validation
    helpers disagree about the same class of input.
  - Expected vs observed: the spec pins the exact probe line shapes (`subtitle-cli-contract.md:100-118`)
    and forbids upstream message text in output (`:118`, honesty rule set §1); observed a DTO that
    accepts an embedded newline that the probe then prints, and no test that could notice (this is the
    same surface the recorded Task-3 Minor 2 touches from the *scanning* side — see the notes below;
    this item is the *validation* side). Reachability requires an upstream/mocked label carrying a
    control character: defence-in-depth, not an observed defect.
  - Confidence: Medium (reachability), High that the validation asymmetry exists.

### ⚪ Unconfirmed

None. Every evidence channel needed for this seat was intact: the checkout, the assigned range, the
plan, the primary spec, the review package (13 files, matching the range) and every referenced
supporting file were readable, and `HEAD` contains all four in-scope commits. Runtime evidence
(test counts, the live acquisition) is *not* an evidence-channel failure but an L1/L4 boundary — see
the Summary's `Needs L4/QA verification` lines.

## Source Trace

| Finding | Source Type | Source Reference | Confidence |
|---|---|---|---|
| F-001 | manual-reasoning + git-diff + read | `cli.py:584-600,770-782,793-797,857-876,890-894`; `storage/database.py:1147`; `storage/models.py:65-72`; spec `subtitle-cli-contract.md:78-79,119-123,164-170,327-330`; `docs/metadata-storage.md:99-101,161`; `README.md:603-607`; test gap `tests/test_subtitle_cli.py:218-242` | High |
| F-002 | deep-lens: Contract Lens (docs-match-code) | `docs/metadata-storage.md:243-244` vs `cli.py:552-556`, `tests/test_subtitle_cli.py:1068-1071` | High |
| F-003 | deep-lens: Bounds/Input-Validation (read/grep) | `cli.py:810-812`; `sources/models.py:34-39,97-118`; `sources/bilibili_api_gateway.py:281-300`; `storage/models.py:65-72`; spec `subtitle-cli-contract.md:100-118` | Medium (reachability) |

## Independent judgement on the L2 verdicts

- **Task 1 — Approved (0 C / 0 I / 4 Minor): concur.** I re-derived the load-bearing claims from
  source rather than from the review: the two consumed row shapes are normalized in one place
  (`subtitle_ingest.py:251-275`; 12-col `v_pending_subtitles` incl. `bvid`/`cid` at
  `schema-transcripts.sql:122-141` vs 11-col `v_video_parts` reached through `_selected_work_item`,
  which supplies the caller's `bvid`); both written vocabularies are validated against the published
  enums (`_choice` → `ALLOWED_ACQUISITION_KINDS` / `ALLOWED_CAPTION_SOURCE_KINDS`,
  `subtitle_ingest.py:76-97,343`); the rebuild line is composed by the CLI with prefix **and** path
  (`cli.py:545-581`) exactly as the carry obligation demands; `probe-subs` is out of
  `_ARCHIVE_WRITER_COMMANDS` while `harvest-subs` stays in (`cli.py:2435-2445`), so the lock boundary
  is structural. My F-001 is a *new* deviation inside that task's scope (both L2 and the new suite
  parametrization missed the blank-selector value); it does not overturn the task verdict, whose
  remaining Minors I also find correctly classified.
- **Task 2 — Approved (0 / 0 / 3): concur.** The E2E genuinely drives the shipped entry
  (`bili_asr.cli.main`, `tests/test_subtitle_e2e.py:1-30` docstring and every case), asserts exact
  printed line lists (`:315`, `:523`, `:665`) and reads rows straight from the database; the seam change is
  surgical (`fake_bilibili_gateway.py:388-403,860-889` add the two protocol methods plus the
  `fake_gateway_seam` fixture; the `importlib` resolution is explained where it is needed), and the
  folded M3 assertion is non-vacuous (env → adapter value → run row → printed line,
  `:756-811`). No regression found in the retained legacy coverage.
- **Task 3 — Approved (0 / 0 / 6): concur.** Every doc claim I spot-checked (below) holds, including
  the two hardest: the legacy-shape bootstrap decision (`storage/database.py:121-137` skips the
  transcript script for a pre-contract database, so *"nothing half-applies, the metadata path keeps
  working"* is literally true) and the `not_found` asymmetry (`cli.py:803-805,813-822` vs
  `subtitle_ingest.py:457-460,473-476`). My F-002 refines one doc block; the recorded Minors stay
  correctly classified as non-blocking.

## Documentation accuracy spot-check (lens emphasis)

Checked against shipped code; **all hold** except the F-001/F-002 items above.

| # | Claim (docs) | Code anchor | Verdict |
|---|---|---|---|
| 1 | Bounds: `probe-subs` requires exactly one of `--bvid`/`--limit-parts`; `harvest-subs` requires the bound unless a single `bvid:pN`; "no unbounded runs" | `cli.py:758-769,858-865`; spec §2 | ✅ |
| 2 | Exit taxonomy 0/1/2 incl. "`attempted=0` still exits 0" and "partial failure stays in the counts" | `cli.py:820-822,915-917`; tests pin both | ✅ (except the F-001 case) |
| 3 | Locked output shapes (`sessdata:`, `probe … tracks=n`, `  (no subtitles visible)`, `  track <lan> <ai\|cc> <label>`, `probe-subs: probed=… failed=…`, `harvest <work_id> stored\|unchanged <kind> <lang> v<n>`, `harvest-subs: run_id=… remaining_without_transcript=…`) | `cli.py:801-819,898-914`; pinned line-for-line at `tests/test_subtitle_cli.py:446-455,477-481,525-536` | ✅ |
| 4 | Preference rule: family ranking `zh`,`en`,rest + CC-before-AI, derived from `language`+`is_ai`, `ai-` prefix stripped, primary subtag; `--language` exact match, `ai-zh` reachable | `subtitle_ingest.py:100-167` (function is verbatim the spec's §3 pseudocode); `cli.py:842-850` trims entries | ✅ |
| 5 | Legacy AI-first order replaced, and `--language` keeps the other track reachable | `subtitles._LAN_PREFERENCE` still ships for the legacy path (`subtitles.py:27-37`); new service does not import it | ✅ |
| 6 | Credential: `--sessdata`/`BILI_SESSDATA` flag-wins, presence-only, value reaches the cookie only, `harvest-subs` records presence in its run row, probe records nothing | `config.py:128-151`; `cli.py:771,786,866,880,801,898`; rows asserted in tests | ✅ |
| 7 | Guard + rebuild: fixed line with command prefix **and** the real `archive.db` path; exit `1`; `fetch-meta`/`status`/`runs` keep working on the same database | `cli.py:545-581`; `tests/test_subtitle_cli.py:1047-1074` asserts the byte-exact line **and** `status` returning 0 | ✅ (F-002: line-wrap presentation) |
| 8 | Two schema resources, and a pre-contract database keeps its shape (transcript script skipped) | `storage/database.py:63-137`; `schema-transcripts.sql` is fully `IF NOT EXISTS` (idempotent re-run) | ✅ |
| 9 | Writer lock: `harvest-subs` holds `coordinator/archive-writer.lock`, a second mutator exits `1` with `harvest-subs: archive_busy`, `probe-subs` takes none; only the DB + lock are left behind | `cli.py:2435-2501`; `tests/test_subtitle_cli.py:1023-1044` asserts the exact file set | ✅ |
| 10 | `not_found` asymmetry stated for both readings (probe → `failed not_found`, can exit 2; harvest → `no-subtitle`, exits 0) | `cli.py:803-805,820-822` vs `subtitle_ingest.py:457-460,473-476` + `record_subtitle_attempt`'s `not_found` allowance | ✅ |
| 11 | ASR boundary: `asr`/`pilot`/`run`/`schedule` never read `archive.db`; `harvest-subs` no longer produces `needs_audio`; `download-audio --missing-subs` gains nothing from the SQLite path | only `fetch-meta`/`status`/`runs`/`probe-subs`/`harvest-subs` touch the database (`cli.py:619,637,1057,1296,570,570`); new handlers never import `ManifestStore`; `needs_audio` still produced by `subtitles.harvest_subtitle` (`subtitles.py:82-124`) for `pilot`/coordinator | ✅ |
| 12 | `v_pending_subtitles` = "every part that is not `gone` and has no stored transcript, ordered never-attempted first, carrying the newest attempt's outcome/timestamp/credential presence" | `schema-transcripts.sql:106-141` (view) + `list_pending_subtitle_parts` imposing the locked ORDER BY | ✅ |
| 13 | `audio_objects`/`part_audio_objects`/`asr_models` still empty | no Python writer references them (grep over `src/`) | ✅ |
| 14 | Live-smoke section: bounds, the four `BILI_LIVE_SMOKE`-gated tests, recorded blocker codes vs loud failures, "archive root holds only `archive.db` + lock" | `tests/test_live_subtitle_cli_smoke.py:122-158,675-689,1191-1213`; `grep -c BILI_LIVE_SMOKE` = 4 modules | ✅ |
| 15 | README anchors survive the two heading renames | all three `#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs` links match `README.md:577`; the renamed `#fresh-start-sqlite-archive-fetch-meta--status--runs` link matches its heading and no stale anchor to the old name remains | ✅ |
| 16 | README's mixed-outcome section no longer claims `harvest-subs` aggregates manifest outcomes | `README.md:740-746`; the repo's own doc-lock test `test_mixed_outcome_contract.py:717-733` still passes on the rewritten text (its asserted strings are preserved) | ✅ |

## Legacy cutover completeness (574 deletions, branch scale)

16 test functions were removed from the range (3 `test_cli_asr.py` *renamed in place* are excluded
from that count; 1 deleted there, 11 in `test_subtitles.py`, 2 in `test_mixed_outcome_contract.py`,
2 in `test_page_pipeline.py`). I mapped **every** one to a named replacement, not just the Task-1
sample:

| Deleted case (file) | Replacement (branch) |
|---|---|
| `test_cli_harvest_risk_exhaustion_preserves_last_stable_status` (cli_asr) | bounded taxonomy instead of the manifest risk ceiling: `test_bounded_gateway_failures_map_to_failed_with_their_code` (exit 2 + run row `failed`), `test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts` (success preserved), E2E row-evidence cases |
| `test_cli_probe_subs_empty` / `…_lists_entries` (subtitles) | `test_probe_subs_prints_track_lines_the_zero_track_marker_and_the_summary` (exact line list, incl. the marker) |
| `…_unknown_bvid_api_error_does_not_create_row` (subtitles) | `test_unknown_bvid_is_configuration_and_opens_no_run` (exit 1, no run row, no gateway call) |
| `…_transport_error_redacts_exception_message` (subtitles) | same probe test + `test_probe_subs_exits_two_when_every_selected_part_failed` + `assert_leaks_no_markers` |
| `…_marks_needs_audio` / `…_downloads_and_marks_done` (subtitles) | `test_harvest_subs_prints_every_outcome_and_the_complete_summary` + `tests/test_cli_asr.py:95-112` `_legacy_subtitle_state()` driving the still-shipped legacy producer |
| `…_sessdata_env_not_echoed` (subtitles) | `test_credential_is_reported_as_presence_only` + the folded M3 E2E case `…env_sourced_credential_is_reported_as_presence_and_composed_into_the_run_row` |
| `…_api_error_preserves_status_and_mixed_batch_fails` / `…_budget_exhausted_exit_2` (subtitles) | `test_bounded_gateway_failures_map_to_failed_with_their_code`, `test_partial_failure_keeps_exit_zero…`, `test_unexpected_error_exits_two_finishes_the_run_and_leaks_nothing` |
| `…_skips_done_and_needs_audio` (subtitles) | `test_harvest_subs_reports_an_empty_pending_selection_as_complete` + `test_bounded_pending_runs_advance_through_the_captionless_backlog` |
| `…_bvid_filter` (subtitles) | `test_explicit_bvid_selects_every_stored_part_including_a_stored_one`, `test_a_single_named_part_needs_no_bound_and_records_its_selector` |
| `test_harvest_subs_mixed_success_and_api_failure_is_retryable` / `…_success_then_risk_exit_2_keeps_success` (mixed_outcome) | the three new partial-failure/exit-2 cases above; the file's other commands' mixed-outcome contract is untouched |
| `test_cli_harvest_skips_unresolved_and_processes_other_page` / `test_cli_harvest_subs_bvid_unresolved_stops` (page_pipeline) | the explicit-selection and unknown-`--bvid` cases; the equivalent `download-audio` unresolved/STOP cases remain in the same file |

Also verified at branch scale: the legacy producer and its helpers survive and stay exercised
(`subtitles.py:27-124`; module-level tests `tests/test_subtitles.py:179-264`,
`tests/test_page_pipeline.py:107-241`), the manifest readers/writers are untouched for
`asr`/`pilot`/`download-audio`/`run`/`schedule`/`coverage`/`verify`/`recover`/`search`/`export`, no
helper was orphaned by the cutover (`_todo_for_bvid`, `_record_api_error`, `_is_excluded`,
`_identity_from_entry` all still have live callers), and the `_open_read_connection` extraction is
behaviour-preserving (`status`/`runs` still build `MetadataRepository` through
`_open_read_repository` and print the same two bounded lines). `needs_audio` is no longer produced by
`harvest-subs` (the handler touches no manifest), and nothing else on the path was changed to
compensate.

## Known / folded Minors — verified, deliberately **not** double-counted

I confirmed each of the Task-3-recorded items is really present in the shipped code, and they remain
PM-owned fix-round work rather than new findings of mine: probe stdout is sentinel-scanned in
`test_subtitle_cli.py:456` but not in the E2E probe case (label vs "no upstream message text");
the docs' quoted live line omits the `run_id` the module prints (`test_live_subtitle_cli_smoke.py:838`
vs `docs/metadata-storage.md:510-517`); `with_tracks`/`stored`/printed `run_id` are emitted and
read but not each asserted; the live body only ever runs live while its 18 offline rehearsals cover
its logic; and a forgotten credential in the live smoke conforms to `sessdata=absent` and reads as a
legitimate bounded skip. Nothing above re-reports them.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 2 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

**Blocking rationale.** No Critical finding, and nothing in the cutover's data path is unsound: the
writes are transactional per part, the run row is always closed, no sidecar or projection is touched,
the credential stays presence-only, and the locked output shapes/summary discipline are pinned
byte-exactly by the new suites. The single Warning (F-001) is an unresolved deviation from the plan's
own locked exit taxonomy and from three shipped doc sentences, on the very surface this plan exists
to deliver; it is a small, well-bounded fix (validate the selector value, or map the repository's
`ValueError` to the fixed `unknown --bvid` line) that fits the already-scheduled plan-QC fix round
together with the folded Minors, and should land with a test case in the usage parametrization so the
taxonomy cannot regress.

**Needs L4/QA verification** (not executable from this read-only seat — no test/build/network runs):
(a) the full offline suite and the focused counts reported by the implementer
(`1279 passed, 4 skipped`, +18 over the storage plan's `1261/3`; `git diff --check` clean) — treat as
L1 evidence until the QA gate re-runs them; (b) one runtime reproduction of F-001: with an existing
archive root, `probe-subs --bvid ""` (and `harvest-subs --bvid "" --limit-parts 1`) currently exit `2`
with `<command>: unexpected error`, and after the fix must print the fixed `unknown --bvid ` line and
exit `1`; (c) the pre-iteration-database case (`tests/test_subtitle_cli.py:1047-1074`) re-run green
after the fix so the schema-guard line and `status` are unchanged.

**Cost/benefit note for the fix round:** F-001 is ~5 lines plus one parametrized case; F-002 is a
doc-block edit; F-003 is a two-line validation hardening whose only cost is a possible new
`shape_error` path for malformed upstream labels (already the documented outcome for unnormalizable
inventories). None of the three requires touching the service's transaction or run lifecycle.

## Revalidation

- **Seat**: @qc-specialist (seat 1 of 3, the seat that raised F-001) · **Round**: plan-QC targeted
  re-review (L3 fix-wave revalidation)
- **Re-review basis**: fix range `8373817..7e57eb6`, read from `review/qc-fix-diff.md` (read once;
  the diff was not re-derived and no git mutation was run)
- **Checkout verified (read-only `git rev-parse`/`status`)**: `HEAD` = `7e57eb6`, branch
  `feature/20260911-subtitle-cli-cutover`, toplevel = the assigned review cwd; the worktree was
  clean before and after this review (`git status --porcelain --untracked-files=all` → 0 entries, so
  this seat left nothing behind)
- **Diff inventory re-checked from the package**: 9 files, **+899/−92** — `cli.py` +100/−7,
  `tests/test_subtitle_cli.py` +318/−10, `tests/test_live_subtitle_cli_smoke.py` +232/−24,
  `tests/test_bilibili_api_gateway.py` +80/−0, `docs/metadata-storage.md` +49/−15, `README.md`
  +34/−10, `services/subtitle_ingest.py` +38/−18, `sources/models.py` +34/−1,
  `sources/bilibili_api_gateway.py` +14/−7 — identical to the assigned range's stat
- **Methods**: file reads + grep over the fix-wave HEAD; one permitted focused pytest run
  (`tests/test_subtitle_cli.py` → **81 passed in 2.93s**); two focused offline node runs for F-003's
  own tests (4 nodes → **46 passed in 0.43s**, `-p no:cacheprovider`); one in-memory counterfactual
  probe (no file written); one manual CLI invocation of the F-001 trigger against a non-existent
  `/tmp` archive root (removed afterwards). No live-network command was executed, `BILI_LIVE_SMOKE`
  was never set, and no credential file was sourced or read
- **Source-identity control for the run evidence**: the shared venv resolves `bili_asr` to the
  *control* checkout by default (which is at `c5a9b82` and contains 0 occurrences of
  `_selector_cannot_name_a_part` / `_open_read_only_connection`), while `tests/conftest.py:12`
  prepends the *worktree* `src`. The new F-001 cases cannot pass against the control source (they
  assert exit `1` on the fixed line), so the green run is evidence about `7e57eb6`; the in-memory
  probe printed the loaded path and confirmed the worktree `sources/models.py`

### F-001 (Warning — unstorable `--bvid` reported as an internal error) — **CLOSED**

Verified at the taxonomy level, not papered over.

1. **Placement before the database open** — `cli.py:851-856` (probe) and `cli.py:945-949`
   (harvest) call the new `_selector_cannot_name_a_part` immediately after `_subtitle_selector`
   and before `_resolve_sessdata` and the only `_open_subtitle_connection` call on each path
   (`cli.py:857-859`, `cli.py:951`). Nothing before the guard touches a database: probe's pre-guard
   work is the two argument checks, harvest's is argument parsing, the `--limit-parts` check and
   the selector split (the archive-writer lock is taken by `main()` around the whole dispatch,
   `cli.py:2582-2592`, and is not a database open).
2. **The rule is the storage contract's own, so the guard cannot diverge from what the store can
   hold** — `_selector_cannot_name_a_part` (`cli.py:662-676`) is
   `not bvid.strip() or any(mark in bvid for mark in "\x00\r\n")`, exactly the two branches of
   `storage/models.py:64-72` `_text` that raise (`must not be empty` after stripping,
   `contains invalid control characters`). A value the guard rejects is therefore one no
   `video_parts` row can carry, in any database.
3. **Exit code and printed line** — both handlers print the fixed
   `<command>: unknown --bvid {args.bvid}` to **stderr** and `return 1`
   (`cli.py:853-856`, `cli.py:946-949`), i.e. the message and code the spec pins (§2 `:78-79`, §7
   `:327-330`) and that `docs/metadata-storage.md` / `README.md` promise. The echoed value is
   `args.bvid`, byte-identical to the pre-existing unknown-bvid guard two lines below it
   (`cli.py:867`, `cli.py:956`) — no second message style was introduced.
4. **Coverage actually added** — the usage parametrization
   (`test_subtitle_usage_errors_exit_one_never_two`, `tests/test_subtitle_cli.py:218-248`) grew from
   10 to **15** collected cases with `probe-subs --bvid ""`, `"   "`, `f"{BVID_A}\x00"` and
   `harvest-subs --bvid "  " / f"{BVID_A}\np0"`; the dedicated
   `test_an_unstorable_bvid_is_answered_as_unknown_bvid` (`:251-330`) parametrizes **7** values
   (`""`, `" "`, `"   "`, `"\t"`, `f"{BVID_A}\x00"`, `f"{BVID_A}\n"`, `f"  {BVID_A}\x00  "`) over
   **both** commands and asserts `captured.out == ""`, the **byte-exact** stderr
   `f"{command}: unknown --bvid {value}\n"` and exit `1` — plus, in the same case, no gateway call
   (`gateway.listing_cids == []`), zero run/attempt rows, and for the probe the one-file root
   assertion. This is non-vacuous by construction: at `8373817` the same inputs produced
   `<command>: unexpected error` with exit `2`, so every one of these assertions fails on the
   pre-fix source (the case would not even be reachable without the guard).
5. **No over-rejection of a valid selector** — the predicate is false for any value with non-space
   content and no `\x00`/`\r`/`\n`; a padded-but-addressable value is explicitly *not* rejected
   (docstring `cli.py:672-675`) and `test_an_unstorable_bvid_outranks_the_missing_database_guard`
   (`:333-361`) pins that it reaches the database and is answered there as an unknown bvid, while
   `test_unknown_bvid_is_configuration_and_opens_no_run` (`:403`),
   `test_explicit_bvid_selects_every_stored_part_including_a_stored_one` (`:832`) and
   `test_a_single_named_part_needs_no_bound_and_records_its_selector` (`:872`) stay green in the
   81-passed run. A valid `--bvid`/`bvid:pN` therefore still takes the normal path.
6. **Runtime (offline, re-taken by this seat)** — `probe-subs --bvid "" --archive-root
   <non-existent temp root>` printed exactly `probe-subs: unknown --bvid ` (trailing space, empty
   value) on stderr and returned **1**, and created nothing; `harvest-subs --bvid "   "
   --limit-parts 2` printed `harvest-subs: unknown --bvid    ` and returned **1**, leaving only the
   documented pre-dispatch `<root>/coordinator/archive-writer.lock` (Q3-05) with no database and no
   run row. No gateway could be reached on either branch (the gateway is constructed only after a
   successful connection), so these invocations are network-free by construction.
7. **One deliberate precedence change, pinned by a test** — the selector check now outranks the
   missing-database guard (`test_an_unstorable_bvid_outranks_the_missing_database_guard`): an
   unstorable selector on a root with no `archive.db` answers `unknown --bvid` instead of
   `no archive database at …`. Both are exit `1` usage errors, the new answer is the more precise
   one, and the case is asserted byte-exactly, so I do not treat it as a taxonomy break.

### F-002 (rebuild line shown wrapped; stderr unstated) — **CLOSED**

`docs/metadata-storage.md` now shows the composed line as **one** code line inside the `text` block
and states the transport explicitly: *"they print the fixed message below on **stderr** (their part
and summary output is stdout, and this path prints nothing there) and exit `1`. It is one line; the
wrap below is the page's, not the command's"*; `README.md` carries the same sentence ("print one
line on stderr — `<command>: archive database predates the transcript schema; rebuild it (delete
<archive-root>/archive.db and re-run fetch-meta)`"). The quoted line still matches the shipped
composition (`cli.py:596-605`, prefix + real `archive.db` path) and remains pinned byte-exactly
against `captured.err` by `tests/test_subtitle_cli.py` (that case is inside the 81-passed run). A
line-based `grep`/copy of the fixed line now works.

### F-003 (`lan_doc` printed verbatim; DTO accepted control characters) — **CLOSED**

- **Rejected at the DTO, surfaced as the bounded `shape_error`**: `sources/models.py:25-43` `_text`
  now mirrors `storage/models.py:64-72` verbatim (non-empty after strip **and** no `\x00`/`\r`/`\n`),
  and `SubtitleTrack.__post_init__` uses it for `language`, `label` and `track_id`
  (`sources/models.py:142-152`). The inventory normalizer wraps DTO construction
  (`bilibili_api_gateway.py:306-313`), so a malformed `lan_doc` is a page-level
  `GatewayShapeError` — pinned by the new rows in
  `test_get_subtitle_tracks_rejects_an_unreadable_inventory` (which asserts
  `caught.value.code == "shape_error"` and that no extra call happened) and by the 9 new rows in
  `test_subtitle_track_rejects_invalid_fields`. The locked one-line-per-track stdout shape
  (`cli.py:896-899`) can therefore no longer be split by upstream label text; the docs sentence
  that promised "no upstream message text" was rescoped in the same wave to name the label as the
  one printed metadata value and to state the rejection (QC2-004/Q3-02).
- **The audit finding is correct, and the split is the right one.** Caption **body** text is now
  validated by `sources/models.py:46-60` `_caption_text`, a faithful mirror of
  `storage/models.py:130-146` `_caption_text` (verified line by line in the storage source: unlike
  `_text`, control characters are kept, and the store remains the boundary that trims and hashes the
  stripped form). The split is right because the two surfaces have opposite requirements: a track
  label is *operator-facing* and printed one line per record, while a caption body is *stored
  verbatim* and a cue may legitimately span two lines. The strictness was then applied to
  `SubtitleSegment.text` only where it is safe — and the one normalizer with **no** `try/except`
  around the DTO is exactly `_normalize_subtitle_segment` (`bilibili_api_gateway.py:438-458`), so
  without this split a two-line cue would have escaped `fetch_subtitle_segments` as a **raw
  `ValueError`, not a `GatewayError`**, and ended a whole harvest run on ordinary upstream data.
  That is a real, high-value catch.
- **The new regression test is non-vacuous — proven, not assumed.** The counterfactual (the split
  removed) was simulated in memory with no file touched: after `sources.models._caption_text =
  sources.models._text`, `SubtitleSegment(start_ms=0, end_ms=1500, text="未明子讲座\n第一讲")` raises
  `ValueError: text contains invalid control characters`, and
  `bilibili_api_gateway._normalize_subtitle_segment({"from": 0.0, "to": 1.5, "content": …})` leaks
  that raw `ValueError` (`isinstance(exc, GatewayError)` → `False`). Because
  `test_caption_text_keeps_interior_control_characters_as_one_row`
  (`tests/test_bilibili_api_gateway.py:2730-2763`) asserts the **exact** three-segment tuple
  including `text="未明子讲座\n第一讲"` and `text="第二行\r第三行"` through the shipped
  `fetch_subtitle_segments`, reverting the one-line split makes that test fail on both rows. The
  whole gateway test file has **0 deletions**, so no pre-existing gateway assertion was relaxed to
  accommodate the new strictness.

### Regression lens — all 92 deleted lines classified

- **Non-test deletions (58)** are all *replaced* lines, every one of them read: `cli.py` 7 (the
  existence-check extraction into `_archive_database_exists`, the `_open_read_connection` body, the
  `_open_subtitle_connection` signature plus its one dispatch line, and the probe's old
  `_open_subtitle_connection("probe-subs", …)` call); `services/subtitle_ingest.py` 18 (the same
  `record_acquired_transcript(...)` call re-indented inside the new `try`); `sources/models.py` 1
  (`_text(self.text, "text")` → `_caption_text(self.text, "text")`);
  `sources/bilibili_api_gateway.py` 7 (the same `return VideoSummary(...)` re-indented inside its
  new `try`); `docs/metadata-storage.md` 15 and `README.md` 10 (prose, incl. the F-002 block, the
  QC2-004/Q3-02 rescope, the Q3-01 family clause, the Q3-04 `run_id` quote and the Q3-05 lock note —
  no requirement sentence was deleted without a replacement sentence). No implementation line was
  deleted without its replacement in the same file.
- **Test deletions (34)** are all replaced lines and **no existing assertion was weakened**; three
  were strengthened: `test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts` traded a
  substring check (`assert "attempted=2 …" in captured.out`) for a full `splitlines()` equality,
  gateway call-order/body-call evidence and row-level attempt tuples, with the failure moved
  *first* (QC2-001); the harvest-summary deletions in the live smoke became named locals plus
  partition assertions (`stored+unchanged+no_subtitle+failed == attempted`, and the outcome→counts
  mapping) and a `run_id`-vs-persisted-row assertion (QC2-009/Q3-03); the two-argument
  `_assert_stored_rows`/`_assert_no_transcript_rows` signatures gained `run_id` at both definitions
  and all three call sites. The live smoke's opt-in `pytest.skip` block and pin assert were **moved**
  into `_live_preconditions()` (`tests/test_live_subtitle_cli_smoke.py:260-276`), which is still the
  first statement of the live body (`:846`) and keeps the documented order — opt-in skip first, pin
  assert, then the new loud credential failure — so a default pytest run still skips without needing
  a credential or the pinned distribution. That ordering is itself rehearsed offline by a new
  no-network test (`:1052-1092`).
- **Metadata path**: touched in two bounded edges, not broken. The strict helper now also covers
  `VideoSummary.title` / `VideoPart.title` (`sources/models.py:81,100`), and every DTO constructor on
  that path is wrapped into the bounded `shape_error` — `_normalize_video_summary_item` gained the
  wrap (`bilibili_api_gateway.py:178-191`), while `_normalize_video_part_item`,
  `_normalize_user_video_page` and `_normalize_subtitle_track` already had it. Titles were already
  held to this exact rule by the store (`storage/models.py:158,189` `_text(self.title, "title")`), so
  a control-character title previously escaped as an unbounded write-time `ValueError` and now
  surfaces as a bounded page error; that is a strict improvement and the reason the shared-helper
  strictness needed this companion. No metadata assertion was touched (0 deletions in
  `tests/test_bilibili_api_gateway.py`) and the focused gateway run is green.
- **Previously reviewed behaviours**: locked output shapes unchanged (the print blocks of both
  handlers are untouched by the wave); exit taxonomy unchanged and now *honoured* (no new code was
  introduced — the unstorable selector stops being a spurious `2`, and the new unreadable-database
  branches print a bounded line and return the same `1` an uncaught exception produced before);
  **probe zero-write strengthened**: `probe-subs` now opens through `_open_read_only_connection`
  (`cli.py:542-583`: `mode=ro` URI, `sqlite3.Row`, `PRAGMA foreign_keys = ON`, first read taken
  inside the bounded handler), `require_subtitle_schema` is structural and read-only, and the archive
  database is not in WAL mode anywhere in `storage/` (no `journal_mode` pragma; connections are plain
  `isolation_level="DEFERRED"`), so a `mode=ro` open cannot create a `-shm`/`-wal` sidecar and the
  "root holds only `archive.db`" assertions stay true. The new probe test
  (`tests/test_subtitle_cli.py:1266-1330`) asserts the exact URI, that only one connection is opened,
  and that DDL and DML through that URI raise `sqlite3.OperationalError`.

### Non-blocking observations (considered; no residual opened by this seat)

- The wave adds two bounded branches — `<command>: unreadable archive database at <root>
  (<ExcType>)` at `cli.py:533-536` and `cli.py:571-574` — that **no test and no doc sentence**
  covers. Judged not a defect: the exit code is the same `1` the previous uncaught exception
  produced, the message shape matches the shipped missing-database line, and no documented promise is
  broken. Recorded here rather than opened as a finding because it sits inside QC2-003's item; the
  seat holding that item and the QA gate may decide whether the branch earns a case.
- The guard echoes `args.bvid` verbatim, so a control-character selector can emit a second stderr
  line (`unknown --bvid ` followed by the injected value). Considered and deliberately **not**
  raised: the spec pins the message as `unknown --bvid <value>`, the sibling guard has always echoed
  the raw argument, the first line stays intact, and stderr is not the locked machine surface
  (stdout is). Sanitizing here would deviate from the locked message and from the sibling's style.

### Updated counts

| Severity | Original | After revalidation |
|----------|----------|--------------------|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 1 | **0** (F-001 closed) |
| 🟢 Suggestion | 2 | **0** (F-002, F-003 closed) |
| ⚪ Unconfirmed | 0 | 0 |
| Residual of mine | — | **0** |

### Verdict

**Approve.**

All three of my findings are closed at `7e57eb6` with evidence that survives the "would it fail
without the fix" test: F-001 by placement (before the DB open), by the storage-mirrored predicate,
by the byte-exact line and exit `1`, by 5 new usage cases plus 7 dedicated values over both
commands, by a no-over-rejection case, and by an offline runtime re-take of the exact trigger form;
F-002 by the single-line code block plus the stderr sentence in both documents; F-003 by the DTO
rejection with the bounded `shape_error` and by the caption/`lan_doc` split whose regression test
demonstrably fails if the split is removed. The 92 deleted lines are all replaced implementation or
prose lines; the 34 deleted test lines are all replaced, several by strictly stronger assertions;
the metadata path, the locked output shapes, the exit taxonomy and the probe's zero-write promise
are intact (the last one now structural). The remaining L4/QA items are unchanged from the original
report and narrowed to the full-suite run and the bounded live smoke at `7e57eb6`; the F-001 runtime
reproduction I had listed as owed to L4 has already been taken here, offline.
