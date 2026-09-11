# Task 2 report — Offline subtitle E2E over the fake seam

- Plan: `20260911-subtitle-cli-cutover` (task 2 of 3), SDD, leaf implementer (no subagents dispatched)
- Branch: `feature/20260911-subtitle-cli-cutover` @ `c501d9a` (base `8ec992b`, Task 1 review Approved)
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover` (package root `bilibili-asr-archive/`)
- Test interpreter: `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` (control venv; the worktree has none)
- **Status: DONE**

The offline subtitle end-to-end evidence is in place: `tests/test_subtitle_e2e.py` (10 cases) drives
`bili_asr.cli.main` with plain argv over the shared `FakeGateway` protocol double installed at the adapter
seam, and pins every locked evidence item of the brief. F3 (the double's two missing subtitle methods) and the
folded M3 (env-sourced credential path) both land. No production file was touched; no push; nothing outside the
working branch was modified.

## Implemented (per brief item + F3 + M3)

| Brief item | Where it is pinned |
|---|---|
| CC track part + AI-only part: normalized `transcripts`/`transcript_segments` rows, language, `source_kind`, version 1, content hash, acquisition-run/attempt evidence | `test_harvest_stores_normalized_rows_for_a_cc_and_an_ai_part` — exact `transcripts` rows (`video_part_id`, `subtitle-cc`/`subtitle-ai`, `zh-CN`/`ai-zh`, `model_id` NULL, version 1, independently recomputed sha256), exact segment rows (ordinal/start_ms/end_ms/text), the persisted-run shape (`kind=subtitle`, `selector_kind=pending`, `selector_target` NULL, `requested_limit=2`, `credential_present=0`, outcome `complete`), and the exact attempt rows with the linked `transcript_id`, the run's own id, and timestamps bounded by the run's lifetime |
| Re-run: `unchanged`, no new version, no duplicate segments; then changed body → version 2 with version 1 still readable | `test_reacquiring_an_unchanged_caption_adds_no_version_and_no_segment` (explicit `--bvid` re-check: `unchanged` line, one version, segment set unchanged, both attempts pointing at one `transcript_id`) and `test_a_revised_caption_appends_version_two_and_keeps_version_one_readable` (versions [1, 2] with their two distinct hashes, both versions' segments verbatim, and version 1 read back through `TranscriptRepository.read_transcript(..., version=1)`) |
| No-subtitle part + body-fetch failure: bounded evidence rows, no success claim, counts show the partial failure, exit 0 | `test_captionless_and_failing_parts_keep_bounded_evidence_and_exit_zero` — exact stdout lines (`no-subtitle`, `failed rate_limited`), exact attempt rows (`no-subtitle`/NULL code/NULL transcript, `failed`/`rate_limited`/NULL transcript), run outcome `partial`, zero transcripts and zero segments, and the captionless part never reaching the body fetch (`body_cids == [FAILING_CID]`) |
| Honesty and progress: a `no-subtitle` part stores later; a never-attempted part is attempted first | `test_a_captionless_part_stores_one_later_and_never_attempted_parts_go_first` — three bounded runs, `remaining_without_transcript` 2 → 1 → 0, listing order `[captionless, cc, captionless]` (the never-attempted part really goes first), attempt history `no-subtitle` → `stored` … `stored` with transcript links |
| Printed run summary: four counts incl. zeros, run id, credential presence, remaining count; `attempted=0` exits 0 | `test_the_summary_prints_every_count_and_an_empty_selection_exits_zero` (two exact whole-stdout comparisons, the printed `run_id` equal to the persisted run row's id, distinct ids, both runs `complete`, `credential_present=0`) plus the `sessdata: absent` line asserted in every case |
| Probe surface: `probe`/`track`/`tracks=0` lines, per-part `failed <code>`, `probe-subs: probed=… with_tracks=… without_tracks=… failed=…`; a probe leaves no database, no run row, no file | `test_probe_subs_prints_the_locked_lines_and_leaves_nothing_behind` — the exact 8-line stdout, `_archive_files == ["archive.db"]` (no lock, no projection), `body_cids == []`, and zero rows in `acquisition_runs`/`acquisition_attempts`/`transcripts`/`transcript_segments`; phase 1 runs the probe against a root with no database → exit 1, the shipped line, `_archive_files == []` |
| No legacy sidecar in the archive root; `probe-subs` leaves no new file and does not create a missing database; no-leak scans over output + all persisted rows | `test_neither_command_leaves_a_sidecar_or_a_transcript_projection` (probe first: only `archive.db`; then harvest: exactly `archive.db` + `coordinator/archive-writer.lock`; no `manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`, `coordinator/attempts.jsonl`, no `subtitles/raw/`, no `transcripts/srt/`) and `test_no_credential_or_upstream_text_reaches_output_or_a_persisted_row` (env credential + a body failure whose detail carries `UPSTREAM_ERROR_TEXT`; `assert_leaks_no_markers` over stdout+stderr and over `persisted_row_text` — every table and view — with positive controls that a normalized row really persisted and that the attempt kept only `transport_error`) |
| **F3** — the shared `FakeGateway` protocol double gains the two subtitle methods; the plan's tests script subtitle calls through it; every existing exact assertion stays intact | `tests/fixtures/fake_bilibili_gateway.py`: `get_subtitle_tracks` / `fetch_subtitle_segments` + `script_subtitle_tracks(cid, …)` / `script_subtitle_segments(cid, …)` + `listing_cids` / `body_cids` recorders in issue order, loud on an unscripted fetch (reuses `_scripted`), and the new `fake_gateway_seam` fixture that installs the double as `BilibiliApiGateway`. `tests/test_subtitle_cli.py` now scripts through that double (its private duplicate is deleted). `DOCUMENTED_METADATA_CALLS`, `assert_only_documented_metadata_calls`, `FakeUpstreamScript`, `Api`, `bilibili_api_seam` and every metadata call-list check are untouched |
| **M3 (folded)** — env-sourced credential: present and absent, `credential_present` composed into the run row, printed `sessdata: <present\|absent>` line, presence-only | `test_the_env_sourced_credential_is_reported_as_presence_and_composed_into_the_run_row` — `BILI_SESSDATA` set → printed `sessdata: present`, the value reached the adapter (`fake_gateway_seam.sessdata == SESSDATA_BOUNDARY_VALUE`), run row `credential_present=1` with `selector_kind=pending`; `BILI_SESSDATA` deleted → printed `sessdata: absent`, adapter credential `None`, run row `credential_present=0` with `selector_kind=bvid`/`selector_target=BV1SubE2e:p1`; neither output nor `persisted_row_text` carries the value; then `probe-subs` with the credential set prints `sessdata: present` and opens no run row |

## Design decisions and disclosures (read before reviewing)

1. **"The fake seam" read as the shared protocol double.** The brief and the assignment both name it: F3 says
   the shared `FakeGateway` protocol double "lacks the two subtitle methods … so this plan scripts subtitle
   calls through it". So the E2E drives the real CLI/service/repository/storage/SQLite chain with the *adapter*
   replaced by that double (the same install technique Task 1 used, now shared via `fake_gateway_seam`), and
   not the real adapter over the `bilibili_api_seam` package seam (the style of `test_metadata_e2e.py`). The
   module docstring states this boundary explicitly: the adapter and the package seam below it are covered by
   the gateway plan's suite (`tests/test_bilibili_api_gateway.py`) and the opt-in live smoke. If PM intended the
   package seam here instead, that is a different (larger) test and should come back as a follow-up rather than
   be assumed — flagging it because "E2E" can be read both ways.
2. **One addition beyond F3's two methods: the `fake_gateway_seam` fixture** (fixtures module). Rationale: F3's
   purpose is that the plan scripts subtitle calls through the shared double, and both test modules need the
   same install-at-the-adapter-seam plumbing (including the `importlib.import_module` compensation the Task-1
   review verified, because the package-seam fixture drops the adapter module from `sys.modules`). Putting it
   twice would be worse than putting it once in the module that already owns the seam fixtures. It is purely
   additive: no existing fixture or double behaviour changed.
3. **`FakeGateway.sessdata`** (initialised to `None`, set by the fixture's factory) is what keeps Task 1's
   existing `assert gateway.sessdata == SESSDATA_BOUNDARY_VALUE` working unchanged and is what makes M3's
   "the env value really reached the adapter" assertable. Documented in the class docstring.
4. **`test_subtitle_cli.py`: zero assertion lines changed** (verified mechanically: `git diff -U0 | grep -cE
   '^[-+].*assert '` → `0`). Deleted: the private `_ScriptedSubtitleGateway` (48 lines). Rewritten:
   `install_gateway`, which keeps its exact keyword signature (`tracks`, `segments`, `listing_failures`,
   `body_failures` — a typo is still a `TypeError`) and now forwards to `fake_gateway_seam`'s scripting methods.
   Changed: the 3 setup lines that mutated the old public script dicts now call `script_subtitle_*` (setup, not
   assertions).
5. **Timestamps are bounds-based, deliberately.** A counter-clock patch is not available on this path: the
   service binds `_now` as a *default argument* (`clock: Callable[[], int] = _now`), so patching the module
   attribute does not change the instance default (the metadata tests' same-named fixture has the same latent
   ineffectiveness; their assertions are loose enough not to notice). I found this while writing the file
   (a strict `finished_at > started_at` assertion reddened on the real second-granular clock) and replaced it
   with honest bounds: `run.started_at <= attempt.started_at <= attempt.finished_at <= run.finished_at`, plus
   `finished_at IS NOT NULL`. Run/attempt *ordering* is read by insertion order (`rowid`), which is deterministic.
6. **The writer lock is disclosed, not hidden.** `harvest-subs` is an archive-writer command, so a harvest
   leaves `coordinator/archive-writer.lock` behind; the E2E asserts exactly that file set and asserts that the
   probe leaves none. This matches the plan's `⚠️2` item that Task 3's docs must name the lock.

## Tests

### Commands and output

```
$ cd .worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
$ …/.venv/bin/python -m pytest tests/test_subtitle_e2e.py -q
..........                                                               [100%]
10 passed in 0.92s

$ …/.venv/bin/python -m pytest tests/test_subtitle_e2e.py tests/test_subtitle_cli.py -q
........................................................................ [ 96%]
...                                                                      [100%]
75 passed in 2.26s

$ …/.venv/bin/python -m pytest tests/test_subtitle_e2e.py tests/test_subtitle_cli.py -v   # shows all 10 E2E names + the 65 CLI cases
75 passed

$ …/.venv/bin/python -m pytest tests/test_metadata_cli.py tests/test_bilibili_api_gateway.py tests/test_subtitle_e2e.py tests/test_subtitle_cli.py -q
422 passed, 1 skipped in 4.45s        # isolation/ordering check (the seam fixtures drop the adapter module)

$ …/.venv/bin/python -m pytest -q     # full offline suite, after the commit
1261 passed, 3 skipped in 47.23s      # baseline 1251 passed, 3 skipped → +10 (exactly the new file)
```

Full-suite baseline confirmed before any change (`tests/test_subtitle_cli.py -q` → `65 passed`, and the plan
baseline `1251 passed, 3 skipped`). No live network command was run; `BILI_LIVE_SMOKE` was never set.

### Red/green and non-vacuity evidence

`tests/test_subtitle_e2e.py` is new (nothing to redden), so non-vacuity was established by mutating *shipped*
production code, running the new file, and reverting (`git checkout -- <file>` after each; worktree confirmed
clean afterwards — `git status --short` shows only the three intended files/commit). Each mutation was chosen so
that a specific brief item must redden:

| # | Mutation (reverted) | Result on `tests/test_subtitle_e2e.py` |
|---|---|---|
| A | `select_subtitle_track` key flips to AI-first (`not pair[1].is_ai`) | 1 failed — `test_harvest_stores_normalized_rows_for_a_cc_and_an_ai_part` (the CC selection / `subtitle-cc zh-CN` assertions) |
| B | `record_acquired_transcript` no longer matches on `content_sha256` | 1 failed — `test_a_revised_caption_appends_version_two_and_keeps_version_one_readable` |
| C | `record_acquired_transcript` always appends (`if True:`) | 1 failed — `test_reacquiring_an_unchanged_caption_adds_no_version_and_no_segment` |
| D | `cli.py` passes `credential_present=False` | 1 failed — `test_the_env_sourced_credential_is_reported_as_presence_and_composed_into_the_run_row` |
| E | probe path forced through `open_database` instead of the read guard | 1 failed — `test_probe_subs_prints_the_locked_lines_and_leaves_nothing_behind` |
| F | `probe-subs` added back to `_ARCHIVE_WRITER_COMMANDS` | 2 failed — the probe test and `test_neither_command_leaves_a_sidecar_or_a_transcript_projection` (the lock file appears) |
| G | pending order reversed (`attempted DESC`) | 1 failed — `test_a_captionless_part_stores_one_later_and_never_attempted_parts_go_first` |
| H | printed credential line no longer reflects the resolved credential | 2 failed — the M3 test and `test_no_credential_or_upstream_text_reaches_output_or_a_persisted_row` |

Every mutation reddened at least one case, and no mutation left the file green. The no-leak scans carry their
own positive controls (a normalized row and the sentinel-bearing failure really were in flight), so they cannot
pass vacuously.

## Files changed

| File | Change |
|---|---|
| `bilibili-asr-archive/tests/test_subtitle_e2e.py` | **new**, 812 lines, 10 tests + local helpers |
| `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` | +80/−4: the two subtitle methods, their scripting methods/recorders, the `sessdata` record, the `fake_gateway_seam` fixture, docstring/`__all__` |
| `bilibili-asr-archive/tests/test_subtitle_cli.py` | +29/−73: private double deleted, `install_gateway` forwards to the shared double, 3 setup lines re-scripted |

Commit: `c501d9a test(subs): land the offline subtitle E2E and script it through the shared seam`
(3 files, +921/−77). `git diff --check` → clean. `git status --short` → clean.

## Self-review notes

- **New assertions, by family** (all inside the new file unless stated): exact whole-stdout comparisons in 5
  cases (the two-outcome run, the captionless/failed run, the two summary runs, the probe, plus exact
  per-part/summary line assertions in the re-acquisition, revision, progress and M3 cases); exact persisted-row
  comparisons for `transcripts`, `transcript_segments`, `acquisition_runs` and `acquisition_attempts`
  (`_stored_versions`, `_stored_segments`, `_attempt_rows`, `_run_rows`); the independently recomputed content
  hash; the repository read path (`read_transcript` v1 vs latest); the file-set/no-sidecar/no-projection
  boundary assertions; the probe's zero-write assertions (`body_cids == []`, four empty tables, file set) and
  its missing-database refusal; the sentinel scans with positive controls; the vocabulary membership checks
  (`kind <= ALLOWED_ACQUISITION_KINDS`, `source_kind <= ALLOWED_CAPTION_SOURCE_KINDS`).
- **Existing assertions touched: none.** No assertion line changed in `test_subtitle_cli.py` (mechanically
  verified) and none in the fixtures module (the diff is additive; the metadata call-list checks and the fake
  package seam are byte-identical). The only non-assertion edits in `test_subtitle_cli.py` are the three
  re-scripting setup lines.
- **Deliberately not covered here** (already pinned by `tests/test_subtitle_cli.py`, so duplicating them would
  only add churn): the usage/exit taxonomy, `--language` override and unmatched-preference mapping, the schema
  guard line, unknown `--bvid`, all-failed exit 2, and the `not_found` → `no-subtitle` mapping.
- **Known duplication (recorded, not fixed):** `_seed_parts`, `_archive_connection`, `_archive_files`,
  `_expected_content_sha256` and the sidecar/projection constants exist per test module. That mirrors the
  existing repo convention (`test_metadata_cli.py` / `test_metadata_e2e.py` / `test_transcript_repository.py`
  each keep their own copies), so I did not promote them into `tests/fixtures/` — that is the same
  "promote when a third consumer appears" call the Task-1 review made for M4.
- **M4 (Task-1 nit) intentionally untouched:** `test_subtitle_cli.py` still imports
  `_write_pre_iteration_database` from `test_storage_schema`; the Task-2 brief lists F3 and M3 only, so
  promoting that helper is left as it was (if PM wants it folded, it is a small fixtures-module move plus two
  import updates).
- No STOP condition was hit: no manifest coupling, no unbounded loop/retry, no signed URL / raw body /
  cookie / traceback in output or rows, no second executable or state source, and `probe-subs` stayed genuinely
  read-only (mutations E and F confirm the shipped boundary is real, not documented-only).
- No credential value was echoed anywhere (presence-only); the sentinel value is used exactly as the shared
  fixture defines it.
