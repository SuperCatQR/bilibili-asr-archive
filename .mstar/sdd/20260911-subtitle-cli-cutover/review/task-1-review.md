# Task 1 review — Subtitle ingest service and CLI commands

- Plan: `20260911-subtitle-cli-cutover` (task 1 of 3), SDD per-task review (L2)
- Reviewer: code-reviewer (fresh, read-only), Mode A / diff-first
- Review round: 1
- Base → head: `c5a9b82` → `8ec992b` on `feature/20260911-subtitle-cli-cutover`
- Worktree reviewed: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover`
- Diff: `.mstar/sdd/20260911-subtitle-cli-cutover/review/task-1-diff.md` (8 files, +2027/−533)
- Implementer report: `.mstar/sdd/20260911-subtitle-cli-cutover/implementer-task-1-report.md`
- Verdict: **Approved** — 0 Critical, 0 Important, 4 Minor

## Review basis (what was actually checked)

Read once, no git re-run, no worktree mutation: the task brief, the authoritative spec
(`subtitle-cli-contract.md`), the plan (Global Constraints + the `Carried from …` block), the
implementer report and the diff; then the shipped sources the diff depends on, to check the
claims rather than the diff's own comments:

- `src/bili_asr/storage/database.py` — `TranscriptRepository.__init__` (guards the schema),
  `start_acquisition_run`, `finish_acquisition_run` (derivation), `record_acquired_transcript`
  (one transaction), `record_subtitle_attempt`, `list_pending_subtitle_parts`,
  `list_selected_parts`, `count_pending_subtitle_parts`, `_run_outcome_from_attempts`,
  `initialize_schema` / `_accepts_transcript_script` / `require_subtitle_schema`.
- `src/bili_asr/storage/models.py` — `ALLOWED_*` vocabularies, `AcquisitionRunRecord` invariants.
- `src/bili_asr/storage/schema.sql:125` (`v_video_parts`, 11 columns, no `bvid`) and
  `schema-transcripts.sql:106` (`v_pending_subtitles`, 12 columns incl. `bvid`/`cid`).
- `src/bili_asr/sources/models.py` — the `BilibiliGateway` protocol and the `GatewayError` codes.
- `src/bili_asr/page_identity.py` — `parse_work_id` / `format_work_id`.
- `src/bili_asr/cli.py` — the two handlers, the read-connection refactor, the writer set, dispatch.
- Test-side: the deleted legacy cases in the diff, the remaining CLI references (grep), the writer-set
  test body, the seam fixture's `sys.modules` handling.

One focused run only, exactly the sanctioned command:
`tests/test_subtitle_cli.py -q` → **65 passed in 1.89s** (confirms the reported focused count and
green state). The full-suite claim (`1251 passed, 3 skipped`) and the mixed-ordering rerun
(`98 passed`) were **not** re-run — see ⚠️.

- Non-vacuity spot-check (the two asked for): **M1** (AI-first preference restored) fails
  `test_default_preference_picks_the_uploader_caption_for_chinese_pairs` (16 params) plus
  `test_default_preference_stores_the_uploader_caption_when_both_are_visible` and
  `test_harvest_subs_prints_every_outcome_and_the_complete_summary` (both script `(AI_ZH, CC_ZH)`
  and assert `subtitle-cc zh-CN`) = the reported 18 by inspection; **M3** (guard line degraded to
  `print(f"{command}: {exc}")`) fails
  `test_both_commands_print_the_fixed_rebuild_line_for_a_legacy_database`, whose assertion is the
  whole `err` line including the absolute `archive.db` path — and
  `require_subtitle_schema` (`database.py:181-184`) raises a message with **neither** the root nor
  the command prefix, so the composed line is genuinely load-bearing. M2/M4/M5 name real tests
  (`test_probe_subs_exits_two_when_every_selected_part_failed`, the no-lock/no-file assertions,
  `test_not_found_is_recorded_no_subtitle_with_its_code[listing]`) and are consistent with the diff.

## Spec Compliance

✅ **Spec compliant.** Every locked item of the brief and spec §2/§3/§5/§6 verified against the
shipped code and the new tests:

| Requirement | Evidence |
|---|---|
| `--bvid` → `list_selected_parts`; otherwise `list_pending_subtitle_parts` | `subtitle_ingest.py:389-414` |
| `cid` always from `video_parts`; no pagelist call | `_pending_work_item`/`_selected_work_item` take `cid` from the view; only two gateway calls exist (`:423`, `:446`) |
| family / CC-before-AI default, exact `--language` order, first preference wins | `language_family:100`, `select_subtitle_track:128-177` (stable key `(family_rank, is_ai, upstream_index)`), `_DEFAULT_LANGUAGE_FAMILY_ORDER = ("zh","en")` |
| one transaction per part, one repository call per part | `_record_caption:481-518` → `record_acquired_transcript` (own transaction); `_record_captionless_part:528`, `_record_failed_part` → `record_subtitle_attempt` (own transaction) |
| run lifecycle: exactly one row, `kind='subtitle'`, selector, bound, credential, derived outcome | `harvest:325-372` (`start_acquisition_run:342-352`, derived `finish_acquisition_run:358`, `Counter` counts), `_selector:298` |
| `failed` closure when an error escapes | `except BaseException: _finish_failed_run(run_id); raise` (`:355-357`, `:374-387`) |
| probe writes nothing at all | `probe:316-323` → `_probe_parts` only; no repository write on the probe path |
| outcome mapping (empty listing / `GatewayNotFound` → `no-subtitle`, `not_found` recorded; 4 bounded codes → `failed <code>`; unchanged/stored from the write) | `_acquire_part:446-479`; `record_acquired_transcript` returns `stored`/`unchanged`; `record_subtitle_attempt` requires `failed`⇒code and `no-subtitle`⇒`None|not_found` (`database.py:965-1005`) |
| `probe-subs` read-only, exactly one selector, missing DB line + exit 1, unknown `--bvid` + exit 1, zero-track marker, `failed <code>` counted in `failed=`, exit 2 only on a whole-probe failure or internal abort | `cli.py:740-821`, `_open_subtitle_connection:559-582`, `_subtitle_selector:584-601` |
| removed from `_ARCHIVE_WRITER_COMMANDS` | `cli.py:2435-2445` (no longer lists `probe-subs`); `test_persistence_scale.py:437` asserts it |
| `harvest-subs` bound rules, explicit `--bvid` incl. stored parts, `--language` empty entry ⇒ usage error, schema guard, locked summary | `cli.py:825-916`, `_subtitle_schema_rebuild_line:545-557` |
| carried obligation — two row shapes normalized | `_pending_work_item` / `_selected_work_item` (12-col vs 11-col verified in the two schema files) |
| carried obligation — `source_kind` (and `kind`) validated against the published enum | `_choice` + `ALLOWED_CAPTION_SOURCE_KINDS`/`ALLOWED_ACQUISITION_KINDS` (`:343`, `:500`, `_caption_source_kind:84`) |
| carried obligation — the CLI composes the guard line (never `str(exc)` alone) | `cli.py:545-557`, whole-line test at `test_subtitle_cli.py` tail |
| honesty rules: 4 counts incl. zeros, run id, credential presence, remaining count, no coverage claim | `cli.py:816-819`, `:910-914`; asserted line-exactly in the new file |
| no sidecar / no projection / no `needs_audio` from the new path | handlers import no `ManifestStore`/`bili_client`/`subtitles`; `test_neither_command_writes_a_sidecar_or_a_transcript_projection` |
| schema guard reaches the pre-iteration database (not silently migrated) | `initialize_schema` skips the transcript script when `transcripts` predates the contract (`database.py:130-168`); the rebuild-line test passes |

### ⚠️ Cannot verify from diff / for PM to check

1. **Full-suite and mixed-order evidence is implementer-reported only.** I confirmed the focused
   file (`65 passed`); `1251 passed, 3 skipped` and the `test_metadata_cli.py + test_subtitle_cli.py
   → 98 passed` isolation rerun were not re-run (out of the reviewer budget by instruction). PM: take
   these as implementer evidence for the plan's "offline suites green" Done criterion.
2. **Spec §6 sentence vs the shipped writer lock.** Spec §6 says "neither command creates a file under
   the archive root except `harvest-subs`'s database writes"; `harvest-subs` is still in
   `_ARCHIVE_WRITER_COMMANDS`, so `main()` (`cli.py:2492-2500`) puts it inside `archive_writer` and it
   leaves `coordinator/archive-writer.lock`. The plan's Architecture section explicitly keeps
   `harvest-subs` a writer command and the implementer disclosed the reading (report §Self-review 6),
   and the boundary test pins exactly `archive.db` + lock. PM: confirm the intended reading and make
   Task 3's docs name the lock; otherwise this is the only place the spec text and the implementation
   are not verbatim aligned.
3. **Disclosure (a), `credential_present` as a keyword-only `__init__` argument** (`subtitle_ingest.py:303-315`).
   Verified there is no other way inside this plan's file list: the `BilibiliGateway` protocol has no
   credential accessor (`sources/models.py:146-177`) and the concrete adapter is out of scope (residual
   R1). It adds no adapter dependency and stays presence-only. PM: accept, or note it next to R1.
4. **Disclosure (b), `selector_target` records the operator's selector** (`_selector:298-311`, using
   `page_identity.format_work_id`). Verified consistent with the storage invariants
   (`_ALLOWED_SELECTOR_KINDS = {"pending","bvid"}`; a `pending` run must carry no target, a `bvid` run
   must carry one — `AcquisitionRunRecord.__post_init__`). `"BV1SubA"` vs `"BV1SubA:p1"` is exactly what
   §2.2's "from the selector" can mean. PM: no action.
5. **Known handoff, not a defect:** `README.md` and `docs/metadata-storage.md` still describe the legacy
   surface (disclosed as handoff #9) — the plan assigns both to Task 3. PM must not let the plan reach
   Done before Task 3 lands, and Task 3 must carry QC3-003's `docs/metadata-storage.md:51-56` fix.
6. **Coverage shape after the legacy churn (regression lens).** No production behaviour outside the two
   commands changed (only `cli.py` + the new service module appear in the diff; the
   `_open_read_connection` extraction is behaviour-preserving — both printed read-command messages are
   byte-identical and `status`/`runs` are untouched). `subtitles.harvest_subtitle` still ships
   (`subtitles.py:82`) and is exercised: `tests/test_subtitles.py` keeps its helper-layer section and
   `tests/test_cli_asr.py`'s new `_legacy_subtitle_state()` drives it directly. PM: the ASR/audio and
   pilot chains are now proven from a *pre-cutover* manifest state, which is the honest shape once
   `harvest-subs` stops writing the manifest — Task 3's docs must state that `download-audio
   --missing-subs` gains nothing from the SQLite path.

## Strengths

- The service is a faithful, well-documented realisation of the locked surface: probe is structurally
  write-free, harvest owns exactly one run row, and the per-part boundary is one repository call.
- Selection is a real property, not a table: `min` over `(family_rank, is_ai, upstream_index)` with
  `language_family` derived from the DTO's two normalized facts, and the new tests pin CC-before-AI as
  a 4×2×2 property table in both upstream orders — the M1 mutation reddens 18 cases.
- Outcome mapping is enforced twice: the service maps bounded codes, and the repository's CHECK matrix
  (`failed`⇒code, `no-subtitle`⇒`None|not_found`, stored/unchanged⇒transcript) makes an inconsistent
  attempt unwritable.
- The two carried obligations that could have been cosmetic are load-bearing: the two views' different
  row shapes are normalized in the service (`bvid` supplied by the caller's selector for
  `v_video_parts`), and the guard line is composed by the CLI because `SchemaContractError` cannot name
  the root — with a whole-line assertion that a substring/degraded line cannot pass.
- Honest failure posture: an error escaping the part loop is finished as `failed` before it propagates,
  stdout stays empty on usage/internal errors, and the unexpected-error path asserts zero attempt rows
  and no sentinel leakage.
- The legacy removal is disclosed at a granularity I could check independently: the diff deletes exactly
  16 test functions (18 deletions minus the 2 renames the report calls out) and the report's table maps
  each one to a named replacement; the grep for `harvest-subs`/`probe-subs` across `tests/` shows no
  stale caller left behind, and the helpers the legacy handlers used (`_todo_for_bvid`,
  `_identity_from_entry`, `_is_excluded`, `_record_api_error`) are all still used by the other
  commands — no dead code was left in `cli.py`.
- Test isolation: the `install_gateway` fixture resolves the adapter through `importlib.import_module`
  and the docstring names the cause (the seam fixture drops the adapter module from `sys.modules` at
  `tests/fixtures/fake_bilibili_gateway.py:810-815`). Verified — the compensation is correct, not a
  papering-over, and the naive form's failure mode (passes alone, fails in the full suite) is disclosed.

## Issues

#### Critical

None.

#### Important

None.

#### Minor

1. **Probe classifies a listing `not_found` as `failed`, which can drive exit 2**
   (`subtitle_ingest.py:423-433` catches all `GatewayError`; `cli.py:820-821`). Spec §1 says a
   `not_found` answer means "no usable track was visible" and is *never* a failure, while spec §2.1's
   probe block has no `no-subtitle` bucket, so a `not_found` must appear either as `tracks=0` or as
   `failed <code>`. The brief resolves it the implementer's way ("a part whose listing failed printed
   as `probe <work_id> failed <error_code>` … counted in `failed=`"), so this is compliant with the
   task's authority — but note the operator-visible asymmetry: the same part probed alone exits `2`
   with `failed not_found`, while harvesting it exits `0` with `no-subtitle`. Disposition: either keep
   (and let Task 3's docs say a `not_found` probe line is not an operational failure) or, if PM wants
   §1 to win at probe time too, it is a one-line change plus one test. Not blocking.
2. **The interrupted-run guard does not cover the finishing call itself.** `finish_acquisition_run`
   (`subtitle_ingest.py:358`) sits *after* the `try/except BaseException` block, so an error raised by
   that call (a locked/IO-failing database, or a clock that moved backwards into
   `finished_at < started_at`) escapes to `cli.py:893-894` leaving the row `running` — the one path
   where the report's "a run is never left running" invariant does not hold. Narrow and unlikely (the
   writer lock is held), but if PM wants the invariant literal, moving the derived finish inside the
   guarded region is the fix. Not blocking.
3. **The env-sourced credential path is no longer directly asserted for these two commands.** The
   removed `test_cli_harvest_sessdata_env_not_echoed` verified that a `BILI_SESSDATA` credential
   actually reached the transport and never appeared in output/files; its named replacement
   (`test_credential_is_reported_as_presence_only`) exercises `--sessdata` only. The shared
   `_resolve_sessdata` precedence is covered for the metadata commands
   (`tests/test_metadata_cli.py:221-242`), so nothing behavioural is unverified — but the redaction of
   an *environment*-sourced credential through the subtitle path is now untested. Natural home: Task 2's
   offline E2E. Not blocking.
4. **`tests/test_subtitle_cli.py` imports a private helper from another test module**
   (`from test_storage_schema import _write_pre_iteration_database`). Legitimate and offline, but it
   couples two test modules through a private name; a `tests/fixtures/` home would be cleaner and Task 2
   already touches the fixture seam. Cosmetic.

## Assessment

**Task quality: Approved**

The service and the two command handlers implement the locked contract, the carried obligations are
discharged where they bite (two row shapes, enum validation, CLI-composed guard line), the removed
legacy behaviour is confined to the two commands and is replaced case-for-case by named, stronger
tests, and the two disclosures are honest, minimal, and defensible within the plan's file list. The
four Minor findings are non-blocking: #1 and #2 are judgement calls for the PM, #3 and #4 are cheap
follow-ups that fit Task 2. Nothing found justifies a fix round before Task 2 starts.

- Critical: 0 · Important: 0 · Minor: 4
- ⚠️ items for PM: 6 (evidence scope, spec §6/writer-lock reading, disclosure a, disclosure b, the
  README/docs handoff to Task 3, and the pre-cutover-state shape of the ASR-path coverage)
