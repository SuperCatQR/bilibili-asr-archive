# Task 2 review — Offline subtitle E2E over the fake seam

- Plan: `20260911-subtitle-cli-cutover` (task 2 of 3), SDD per-task review (L2)
- Reviewer: code-reviewer (fresh, read-only), Mode A / diff-first
- Review round: 1
- Base → head: `8ec992b` → `c501d9a` on `feature/20260911-subtitle-cli-cutover`
- Worktree reviewed: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover` (package root `bilibili-asr-archive/`)
- Diff: `.mstar/sdd/20260911-subtitle-cli-cutover/review/task-2-diff.md` (3 files, +921/−77: `test_subtitle_e2e.py` new +812, `fixtures/fake_bilibili_gateway.py` +80/−4, `test_subtitle_cli.py` +29/−73)
- Implementer report: `.mstar/sdd/20260911-subtitle-cli-cutover/implementer-task-2-report.md`
- Verdict: **Approved** — 0 Critical, 0 Important, 3 Minor

## Review basis (what was actually checked)

Read once, no git mutation, no source mutation. The brief (carrying the folded M3 block), the authoritative
spec (`subtitle-cli-contract.md`), the plan (Task 2 + Global Constraints + STOP Conditions + the
`Carried from …` block), the Task-1 L2 review, the implementer report and the diff — then the shipped
sources the claims depend on, so the review checks the code rather than the diff's own comments:

- `src/bili_asr/cli.py` — `_open_read_connection:502`, `_subtitle_schema_rebuild_line:545`,
  `_open_subtitle_connection:559`, `_subtitle_selector:584`, `_cmd_probe_subs:740`, `_cmd_harvest_subs:825`,
  `_ARCHIVE_WRITER_COMMANDS:2435`, `main:2486`.
- `src/bili_asr/services/subtitle_ingest.py` — `select_subtitle_track:128` (the `min` key at `:160-167` and
  the `--language` branch at `:150-158`), `SubtitleIngestor.__init__:303` (`clock: Callable[[], int] = _now:309`),
  `harvest:325`, `_selector:278`, `_candidate_items:389`.
- `src/bili_asr/storage/database.py` — `_segment_content_sha256:705`, `_canonical_segments:1208`,
  `record_acquired_transcript:840` (the hash-match `:895-903`, `_next_transcript_version` branch `:904-940`),
  `read_transcript:1015`, `list_pending_subtitle_parts:1091` (locked order `:1114`), `_run_outcome_from_attempts:1263`,
  `open_database:186` (default journal mode — no WAL side files).
- `src/bili_asr/storage/models.py:468-476` (`frozenset` vocabularies), `schema-transcripts.sql:106` (`v_pending_subtitles`),
  `tests/conftest.py:19` (`tmp_root`).
- Test side: `tests/test_subtitle_cli.py` (the rewritten `install_gateway`, the credential test, the parametrized
  `not_found` case), `tests/fixtures/fake_bilibili_gateway.py` (`_scripted:411`, `NO_LEAK_MARKERS`,
  `persisted_row_text:802`, `assert_leaks_no_markers:835`, `fake_gateway_seam:864`), and the package-seam coverage
  of the same two gateway methods in `tests/test_bilibili_api_gateway.py` (30+ subtitle cases).

One focused run only, exactly the sanctioned command:
`tests/test_subtitle_e2e.py -q` → **10 passed in 0.84s** — confirms the reported focused count and the green state.

Read-only scope probes (no diff re-run, no mutation): `git status --short` → clean; `git diff --name-only
8ec992b..c501d9a` → exactly `tests/fixtures/fake_bilibili_gateway.py`, `tests/test_subtitle_cli.py`,
`tests/test_subtitle_e2e.py` — **nothing outside `tests/` changed**.

The pair run (`75 passed`), the isolation rerun (`422 passed, 1 skipped`) and the full suite
(`1261 passed, 3 skipped`) were **not** re-run — see ⚠️1.

## Spec Compliance

✅ **Spec compliant.** Every brief bullet, plus the folded F3 and M3 obligations, is discharged with evidence I
verified against the shipped code (not only against the new file's own comments):

| Requirement | Evidence |
|---|---|
| E2E drives the shipped CLI, not the service in isolation | Every case calls `bili_asr.cli.main([...argv])` (`test_subtitle_e2e.py:273`); only `BilibiliApiGateway` is replaced, at its own module (`fake_gateway_seam:864-888`), which is the seam `cli.py` imports inside each handler body (`cli.py:755, 839`) |
| CC part + AI-only part: normalized rows, language, `source_kind`, v1, content hash, run/attempt evidence | `test_harvest_stores_normalized_rows_…:273` — exact `transcripts` tuples (`subtitle-cc`/`zh-CN` and `subtitle-ai`/`ai-zh`, `model_id` NULL, v1, recomputed sha256 at `:176`), exact `transcript_segments`, exact attempt rows with the linked `transcript_id` and the run's id, run row `(kind, kind∈enum, pending, NULL, 2, 0, complete)` (`:303-311`) |
| Re-run `unchanged`, no new version, no duplicate segments; changed body → v2 with v1 readable | `test_reacquiring_…:375` (one version, identical segment set, both attempts on one `transcript_id`) and `test_a_revised_caption_…:439` (versions `[1, 2]` with both hashes; v1 read back through `TranscriptRepository.read_transcript(part_id, "subtitle-cc", "zh-CN", 1)` — signature verified at `database.py:1015`) |
| Captionless + body-failure parts: bounded evidence, no success claim, counts visible, exit 0 | `test_captionless_and_failing_parts_…:501` — exact stdout, attempt rows (`no-subtitle`/NULL code/NULL transcript; `failed`/`rate_limited`/NULL), run outcome `partial`, zero transcripts/segments, and the captionless part never reaching the body fetch (`body_cids == [FAILING_CID]`) |
| Honesty and progress | `test_a_captionless_part_stores_one_later_and_never_attempted_parts_go_first:548` — `remaining_without_transcript` 2 → 1 → 0 pins the *post-run* read of `count_pending_subtitle_parts`; listing order `[captionless, cc, captionless]` pins the never-attempted-first rule; attempt history `no-subtitle → stored → stored` pins that `no-subtitle` is not terminal |
| Printed summary: four counts incl. zeros, run id, credential presence, remaining; `attempted=0` exits 0 | `test_the_summary_prints_every_count_…:601` — two whole-stdout comparisons, printed `run_id` equal to the persisted row's, distinct ids, both runs `complete` |
| Probe surface + zero writes | `test_probe_subs_prints_the_locked_lines_…:638` — the exact 8-line stdout; missing DB → exit 1 with the shipped line and `_archive_files == []`; after a seeded probe, `_archive_files == ["archive.db"]`, `body_cids == []`, and all four evidence tables empty |
| No sidecar, no projection, no-leak scans | `test_neither_command_leaves_a_sidecar_…:692` (probe first, then harvest = exactly `archive.db` + the lock; the four named legacy sidecars and both projection prefixes absent) and `test_no_credential_or_upstream_text_…:717` (sentinel-bearing failure detail in flight, scanned over stdout+stderr and over `persisted_row_text`, with positive controls) |
| **F3** — the shared `FakeGateway` double gains the two subtitle methods and the CLI tests script through it, with no existing assertion weakened | `get_subtitle_tracks:391` / `fetch_subtitle_segments:399` + `script_subtitle_tracks` / `script_subtitle_segments` + `listing_cids`/`body_cids`, loud on an unscripted fetch via the shared `_scripted:411`; `test_subtitle_cli.py` re-imports the shared helpers, deletes `_ScriptedSubtitleGateway`, and `install_gateway:108` forwards to the double |
| **M3** — env credential present/absent composed into the run row and the printed line, value nowhere | `test_the_env_sourced_credential_…:756` — harvest with `BILI_SESSDATA` → printed `sessdata: present`, `run row credential_present=1` (`pending`); without → printed `sessdata: absent`, `credential_present=0` (`bvid`/`BV1SubE2e:p1`); the env value reached the adapter (`fake_gateway_seam.sessdata`); probe with the credential → printed `present`, still two run rows and the same file set |

**F3's constraint, verified mechanically from the diff.** The fixture's deletions are docstring lines only
(4 lines: 3 in the module docstring, 1 in the class docstring); `_scripted`, `DOCUMENTED_METADATA_CALLS`,
`assert_only_documented_metadata_calls`, `FakeUpstreamScript`, `Api` and `bilibili_api_seam` are byte-identical,
so the seam's metadata call-list strictness is untouched. In `test_subtitle_cli.py`, 74 diff lines start with `-`
(73 real deletions + the `---` header) and **none** of them is an `assert`, a `def test_`, a `pytest.mark` or a
non-docstring decorator; the only deleted `class`/`def` lines are `_ScriptedSubtitleGateway`, its two async
methods, and the old `install_gateway` body that is rewritten in place. Test inventory is unchanged (29 test defs),
so the 65-case Task-1 baseline still holds (`65 + 10 = 75`, matching the reported pair count), and `importlib` is
genuinely unused in that file after the removal (no `NameError` risk).

**Non-vacuity spot-check (reconstructed by inspection — no mutation was run, read-only seat).** 6 of the 8
claimed mutations were traced through the shipped code to the named failing case; all six are consistent:

- **A** (default preference flipped to AI-first, i.e. `select_subtitle_track`'s `min` key at
  `subtitle_ingest.py:160-167` negating `is_ai`) → `test_harvest_stores_normalized_rows_…` reddens: for the
  `(AI_ZH, CC_ZH)` script the run would store `subtitle-ai ai-zh` with the AI body hash, contradicting the exact
  stdout and the `transcripts` tuple.
- **B** (the content-hash condition dropped from the `existing_row` query, `database.py:895-903`) →
  `test_a_revised_caption_appends_version_two_and_keeps_version_one_readable` reddens: the revised body would
  match the v1 row by `(part, source_kind, language)` alone, be recorded `unchanged`, and `versions == [1]` would
  fail its `[1, 2]` expectation. (The `unchanged` re-check test would still pass, so "1 failed" is the right count.)
- **C** (always append, `:904`) → `test_reacquiring_an_unchanged_caption_adds_no_version_and_no_segment`: two
  versions where the test requires `versions == [1]` and both attempts on one `transcript_id`.
- **D** (`credential_present=False` in `cli.py:786/880`) → `test_the_env_sourced_credential_…`: the printed line
  is computed independently (`redact_sessdata(sessdata)`, `cli.py:898`), so only the run-row assertion catches it —
  `[(1, "pending", None), …]` becomes `[(0, …)]`, and the M3 test is the only case that asserts the `pending` row's
  credential bit.
- **G** (`list_pending_subtitle_parts` order reversed, `database.py:1114`) →
  `test_a_captionless_part_stores_one_later_and_never_attempted_parts_go_first`: run 2 would attempt the
  already-attempted captionless part and print `no-subtitle` instead of `stored subtitle-cc zh-CN v1`.
- **H** (printed credential line always `absent`) → exactly two cases assert a `present` line
  (`test_the_env_sourced_credential_…:756` and `test_no_credential_or_upstream_text_…:717`), while the other
  cases assert `absent` and keep passing — matching the reported "2 failed".

E/F (probe forced through `open_database`; `probe-subs` back in the writer set) also reconstruct to their named
cases: the probe test is the only one that probes a root with no database, and it plus the sidecar test are the
two cases that pin the file set the writer lock would violate.

## Strengths

- The evidence layer is exactly where the acceptance gate needs it. The rows asserted are the *normalized* ones
  (identity, language, `source_kind`, version, hash) plus run/attempt evidence, and the content hash is recomputed
  from the contract in the test (`_expected_content_sha256:176`) rather than read back out of the repository — the
  storage algorithm (`database.py:705-708`) and the test's restatement agree independently, and the test data
  carries no whitespace, so text trimming cannot make the two coincide by accident.
- The E2E's assertions pin *behaviour* the lower layers cannot: the post-run read of the remaining count
  (2 → 1 → 0), the never-attempted-first rule observed through the gateway's own call recorder, the captionless
  part never reaching the body fetch, and `no-subtitle` staying re-attemptable.
- The probe's read-only promise is proven structurally, not asserted by inspection: the missing-database phase
  leaves an empty root, and the seeded phase pins exactly `archive.db` with all four evidence tables empty and no
  body fetch. The shipped reason holds up: `probe-subs` is absent from `_ARCHIVE_WRITER_COMMANDS`
  (`cli.py:2435-2445`) and the read guard (`cli.py:502-518`) precedes `open_database`, which uses the default
  journal mode — no `-wal`/`-shm` artifacts can appear behind the assertion.
- No-leak evidence is non-vacuous by construction: the failing part is scripted with a detail carrying every
  seam sentinel, and the persisted scan carries positive controls (`subtitle-cc`, `第一句`) so an empty blob
  cannot pass it, while the attempt row keeps only the bounded `transport_error` code.
- F3 was done as a real consolidation, not a copy: one double, one loud-on-unscripted discipline (`_scripted`),
  one install fixture shared by two modules, and the deleted private double's exact keyword signature preserved
  (`tracks`/`segments`/`listing_failures`/`body_failures`), so a typo is still a `TypeError`.
- The regression lens is clean: nothing outside `tests/` changed, no test or assertion line was deleted, and the
  three converted setup lines are the only non-assertion edits in `test_subtitle_cli.py`.
- Disclosures 2, 4 and 5 are honest and minimal: the extra `fake_gateway_seam` fixture is purely additive and
  lives in the module that already owns the seam fixtures; the writer-lock file set is pinned as exact behaviour
  (making Task 3's documentation obligation verifiable rather than rhetorical); M4 is left alone because the
  plan's recorded-nit block proposes no rework and the brief folded only F3 and M3.

## Issues

#### Critical

None.

#### Important

None.

#### Minor

1. **Report disclosure 3's supporting claim about the metadata clock fixture is factually wrong** (implementer
   report §Design decisions 3, parenthetical). The subtitle half is right and I verified it:
   `SubtitleIngestor.__init__` binds `clock: Callable[[], int] = _now` as a **default argument**
   (`subtitle_ingest.py:309`), so patching `bili_asr.services.subtitle_ingest._now` cannot reach an instance
   built by the CLI — the bounds-based assertions are the honest option here. But the metadata contrast does not
   hold: `MetadataIngestor.__init__` takes no clock parameter (`metadata_ingest.py:147`) and the class calls the
   module-global `_now()` at call time (`metadata_ingest.py:207, 226, 260, 267, 315`), so `_ingest_clock`
   (`tests/test_metadata_cli.py:76-87`) is **effective**, not "latently ineffective". No product or test change is
   needed; the finding is that this claim must not be propagated into the QC/knowledge record as if the metadata
   test clock were broken.
2. **`_archive_files` is blind to directories** (`tests/test_subtitle_e2e.py:166-173`): it walks `os.walk`'s file
   names only, so the probe's "leaves nothing behind" assertions would not notice a newly created *empty*
   directory under the archive root (`coordinator/`, `subtitles/`). This matches the spec's literal wording
   ("creates no file"), and no shipped path creates one, so this is a strength-of-assertion nit only; asserting
   the directory listing as well would close the stronger "writes nothing at all" reading.
3. **M3's probe-absent branch is pinned in a different test than M3's own case** (informational, no action):
   `test_the_env_sourced_credential_…:756` exercises the probe with the credential **present**; the
   `sessdata: absent` probe line is asserted in `test_probe_subs_prints_the_locked_lines_…` via the autouse
   `_anonymous_environment` deletion. The M3 letter ("both commands", present and absent) is satisfied across the
   file rather than inside one case — worth knowing when the QC seats read the coverage, but nothing is unverified.

## ⚠️ Cannot verify from diff / for PM to check

1. **The wider test counts are implementer-reported only.** I confirmed the focused file (`10 passed in 0.84s`).
   The pair (`75 passed`), the isolation rerun (`422 passed, 1 skipped`) and the full suite
   (`1261 passed, 3 skipped`, baseline `1251/3`) were not re-run (reviewer budget; full suite explicitly out of
   scope). PM: take these as implementer evidence for the plan's "offline suites green" Done criterion. The
   arithmetic is internally consistent (65 + 10 = 75; +10 over the baseline — exactly the new file).
2. **The 8-mutation non-vacuity table is not reproducible from a read-only seat.** My spot-check (6 of 8) was a
   code-level reconstruction that reproduced each named failure; E and F were reconstructed as well. PM: treat the
   table as implementer evidence in the QC bundle, with this reconstruction as the independent corroboration.
3. **Disclosure 1 — "the fake seam" read as the shared protocol double, not the package seam.** My call: the
   reading is correct for this task. F3's wording names the `FakeGateway` protocol double as the thing to extend,
   the plan's Task 2 file list contains no gateway module (so the real adapter is not this plan's to drive), and
   the package seam is not left uncovered: both subtitle routes are exercised over `bilibili_api_seam` in
   `tests/test_bilibili_api_gateway.py` (listing, document fetch, signed-URL and protocol-relative normalization,
   bounded failure mapping, the documented call surface), and Task 3's opt-in live smoke covers the real adapter.
   If PM wanted a package-seam subtitle E2E instead, that is a *larger* new task — recommend recording it as a
   follow-up decision rather than reopening Task 2.
4. **The writer lock is now pinned as expected behaviour.** `test_neither_command_leaves_a_sidecar_…:692` asserts
   exactly `archive.db` + `coordinator/archive-writer.lock` after a harvest. That converts the Task-1 ⚠️2 reading
   (spec §6 sentence vs the shipped writer set) into a tested contract; Task 3's docs bullet must still name the
   lock, and the plan must not reach Done on docs that claim "no file" without it.
5. **The credential's reach is proven up to the adapter boundary, not to a transport.** M3's
   `fake_gateway_seam.sessdata` assertion proves env → `resolve_sessdata` → the `BilibiliApiGateway(sessdata=…)`
   construction site; the value's use inside the real adapter is covered separately by the gateway suite. PM:
   awareness only — an offline E2E cannot do better, and the deleted legacy test's claim is thereby re-established
   at the right layer.
6. **`ProbeResult.credential_present` is not asserted anywhere** (Task-1 production surface, out of this diff's
   scope): the CLI prints the probe's credential line from its own `redact_sessdata(sessdata)`
   (`cli.py:801`) and never uses the service field. Nothing in the plan's acceptance requires it, so no action —
   flagged only so the record is not misread as "probe credential composition is covered by the service surface".

## Assessment

**Task quality: Approved**

The offline E2E is real evidence, not ceremony: it drives `bili_asr.cli.main` with plain argv over the shared
protocol double, asserts the normalized rows and the run/attempt evidence down to the recomputed content hash,
reads v1 back through the repository's own read path, and proves the probe's zero-write promise structurally
(missing database leaves an empty root; a seeded probe leaves exactly `archive.db` and no evidence rows). The
captionless and body-failure paths keep bounded evidence and never claim success while the exit code stays `0`,
and the no-leak scans carry positive controls so they cannot pass vacuously.

F3 landed as a real consolidation — the shared double gains the two methods with the same loud-on-unscripted
discipline, the private duplicate is gone, and the fixture's metadata call-list strictness is byte-identical —
and the zero-assertion-change claim verified mechanically. M3 genuinely composes the env credential into the run
row and the printed line for both commands with the value absent from output and rows.

The three Minor findings are non-blocking: #1 is a report-accuracy correction (do not propagate the metadata-clock
claim), #2 and #3 are assertion-strength/coverage-split notes with no shipped-behaviour implication. Nothing found
justifies a fix round before Task 3 starts.

- Critical: 0 · Important: 0 · Minor: 3
- ⚠️ items for PM: 6 (unre-run broader counts, the non-reproducible mutation table, the disclosure-1 seam reading,
  the writer-lock documentation obligation carried into Task 3, the credential's reach boundary, and the unused
  `ProbeResult.credential_present` field)
