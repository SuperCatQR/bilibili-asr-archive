# Task 3 review — Bounded live smoke and operator documentation

- Plan: `20260911-subtitle-cli-cutover` (task 3 of 3, final), SDD per-task review (L2)
- Reviewer: code-reviewer (fresh, read-only), Mode A / diff-first
- Review round: 1
- Base → head: `c501d9a` → `8373817` on `feature/20260911-subtitle-cli-cutover`
- Worktree reviewed: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover` (package root `bilibili-asr-archive/`)
- Diff: `.mstar/sdd/20260911-subtitle-cli-cutover/review/task-3-diff.md` (3 files, +1722/−37)
- Implementer report: `.mstar/sdd/20260911-subtitle-cli-cutover/implementer-task-3-report.md`
- Verdict: **Approved** — 0 Critical, 0 Important, 6 Minor

## Review basis (what was actually checked)

Read once, no live network, no worktree mutation: the task brief (carrying M1 / ⚠️2 / ⚠️6 and the folded
`ProbeResult.credential_present` item), the plan (Global Constraints, STOP Conditions, the `Carried from …`
block, Acceptance/Done), the Task-1 and Task-2 L2 reviews, the implementer report, the diff, then the shipped
sources the claims depend on — so the review checks the code rather than the diff's own comments:

- `src/bili_asr/cli.py` — `_ARCHIVE_WRITER_COMMANDS:2435`, `main:2486` (the writer-lock wrap and
  `archive_busy`), `_open_read_connection:502`, `_subtitle_schema_rebuild_line:545`,
  `_open_subtitle_connection:559`, `_subtitle_selector:584`, `_cmd_probe_subs:740` (prints at `:801/:802-812/:813-819`,
  exit at `:820`), `_cmd_harvest_subs:825` (prints at `:898-912`, exit at `:913`), the subtitle subparsers
  `:121-170`, `download-audio --missing-subs:947`.
- `src/bili_asr/coordinator.py:57` (`ARCHIVE_WRITER_LOCK`), `src/bili_asr/config.py:128-151`
  (`resolve_sessdata` / `redact_sessdata`), `src/bili_asr/subtitles.py:27` (`_LAN_PREFERENCE`),
  `src/bili_asr/services/subtitle_ingest.py:57/:67/:100/:128-177/:200-204/:423-470`,
  `src/bili_asr/storage/database.py:141-160/:163-178/:1133-1162`,
  `src/bili_asr/storage/schema-transcripts.sql:106-141`, `src/bili_asr/sources/bilibili_api_gateway.py:273-305`.
- Test side: the new module's readers/assertions/helpers, `tests/conftest.py:19` (`tmp_root`),
  `tests/fixtures/fake_bilibili_gateway.py:177-194/:802-841`, and the metadata smoke's precedent for the
  evidence-line shape (`tests/test_live_metadata_smoke.py:350-364`).

Read-only scope probes: `git diff --stat/--name-only c501d9a..HEAD` → exactly `README.md`,
`docs/metadata-storage.md`, `tests/test_live_subtitle_cli_smoke.py`, +1722/−37; `git status --porcelain` → clean;
`git log c501d9a..HEAD` → the two disclosed commits.

One focused run only, exactly the sanctioned command:
`tests/test_live_subtitle_cli_smoke.py -q` → **18 passed, 1 skipped in 0.75s** (confirms the reported offline
count and green state; no `BILI_*` variable is exported in this session, so the live gate stayed closed and no
network call was made). The focused group (`116 passed, 3 skipped`), the full suite (`1279 passed, 4 skipped`,
baseline `1261/3`) and the live run itself were **not** re-run — see ⚠️.

## Spec Compliance

✅ **Spec compliant.** Every brief bullet, the three folded documentation follow-ups, and the folded
`credential_present` item are discharged; the documentation obligations were checked against the shipped code,
not against the docs' own prose (seven claims verified, listed below).

| Requirement | Evidence |
|---|---|
| Opt-in live smoke, temporary root, bounded `--limit-parts`, credential + proxy from the documented environment, skip by default, loud-fail without the pin, metadata smoke's bounded structure | `tests/test_live_subtitle_cli_smoke.py:728` (the live test), `:197` (`_live_smoke_requested`), `:203` (`_pinned_package_version` → `pytest.fail` + `uv sync` guidance), `:235/:247` (`--limit-parts 1` on both commands), `:259` (`_seed_probe_part` into `tmp_root`), `:861` (the credential fixture is explicitly **not** autouse) |
| Part provenance disclosed as authored, with only the identity real | `:259-292` (seeded through the shipped repository), `:124-137` (`SAMPLE_BVID`/`SAMPLE_CID`/`PART_SOURCE`), the live test's part-preamble print; the reviewer's check that the identity is real: the live run itself answered a listing and a document for that bvid+cid |
| Run once, record the outcome, never print URLs/bodies/credentials | The recorded line and the assertion structure below; credential value scanned at `:777`, `:796-798`, `:829` |
| Docs: two commands, bounds, exit codes, output shapes, preference rule + family rationale, credential handling, guard + rebuild, two schema resources, legacy manifest boundary, `needs_audio` gone | `docs/metadata-storage.md` §"Subtitle acquisition" (`:80-269`) + §"Exit codes → `probe-subs`/`harvest-subs`" (`:555-560`); `README.md` §"Subtitle acquisition on SQLite" (`:577-659`), §"Fresh-start SQLite archive", §"Operational run ledger" (`:258-265`), §"Mixed batch outcomes", §"Opt-in bounded live smokes" (`:661-690`) |
| **QC3-003** — the false "no … transcripts are written yet" sentence replaced | `docs/metadata-storage.md:58-69` (§"Media and transcript tables"); the old heading + paragraph are gone (`grep` for `written yet` / `Reserved media boundary` → none), replaced rather than appended |
| **M1** — the probe-vs-harvest `not_found` asymmetry, both readings | `docs/metadata-storage.md:170-180` (dedicated §"A `not_found` listing is read differently…" with both exit codes) + the outcome table at `:148`; rehearsed offline on **both** sides (`tests/test_live_subtitle_cli_smoke.py:1121`, second half) |
| **⚠️2** — the writer lock, and `probe-subs` lock-free | `docs/metadata-storage.md:182-194` (§"Archive writer lock": what, where, `archive_busy`) + `README.md:655-659`; the writer-isolation list in `README.md:186-195` no longer names `probe-subs` |
| **⚠️6** — ASR/pilot reads the manifest; `download-audio --missing-subs` gains nothing | `docs/metadata-storage.md:252-269` (§"Boundary with the legacy manifest path") + `README.md:647-654` + the `run` four-stage paragraph at `README.md:348-352` |
| `ProbeResult.credential_present` pinned against the printed line | `tests/test_live_subtitle_cli_smoke.py:1257-1303` — the real `SubtitleIngestor.probe` is wrapped, two CLI runs pin `[False]` / `[False, True]` against `sessdata: absent` / `sessdata: present`, and `fake_gateway_seam.sessdata` pins the value reaching the adapter |
| Base brief list: bounds/exit codes/output shapes, preference rule, credential, guard + rebuild, two schema resources, `needs_audio` gone | Same doc sites; each verified against code below |
| `git diff --check` clean, only the three declared paths changed | `git diff --name-only c501d9a..HEAD` (3 paths, no production file); `git status --porcelain` empty |

**Documentation claims spot-checked against the shipped code** (seven, not restated from the docs):

1. `_ARCHIVE_WRITER_COMMANDS` (`cli.py:2435-2445`) contains `harvest-subs` and **not** `probe-subs`, and
   `main()` (`:2492-2500`) prints `<command>: archive_busy` and exits `1` — matches the docs' writer-lock
   section and the README's corrected writer/read-only lists.
2. `coordinator.py:57` → `os.path.join("coordinator", "archive-writer.lock")` — exactly the path both docs
   name and the path the smoke asserts (`ARCHIVE_WRITER_LOCK_PATH`).
3. `subtitles.py:27` → `_LAN_PREFERENCE = ("ai-zh", "zh-CN", "zh-Hans", "en")` — exactly the tuple the docs
   quote as the replaced legacy AI-first order.
4. `subtitle_ingest.py:57/:67/:150-177` → `_SOURCE_KIND_BY_AI = {True: "subtitle-ai", False: "subtitle-cc"}`,
   `_DEFAULT_LANGUAGE_FAMILY_ORDER = ("zh", "en")`, and `min` over `(family_rank, is_ai, upstream_index)` /
   exact-match first-preference-wins — matches the docs' preference section verbatim in behaviour.
5. `database.py:141-160` → `initialize_schema` runs `schema.sql` and then `schema-transcripts.sql` **only when
   `_accepts_transcript_script`**; `_open_read_connection:520` returns `open_database(...)` for read commands —
   matches the docs' "always runs both scripts … the transcript script is skipped for a pre-contract database".
6. `database.py:163-178` → the `SchemaContractError` message carries neither the `<command>:` prefix nor the
   root, and `cli.py:545-557` composes the printed line — the docs' quoted fixed line is the composed one.
7. `schema-transcripts.sql:106-141` → `v_pending_subtitles` carries `work_id` (`bvid || ':p' || page_index`),
   `cid`, `attempted`, and excludes parts that have a transcript and parts `gone` — exactly the docs' view row
   and exactly the smoke's read-only pending assertion (`tests/test_live_subtitle_cli_smoke.py:479-499`).

**Regression lens on the 37 deleted lines.** README 16 + docs 21. Extracted and mapped each deletion: the H1,
the intro sentences, the fresh-start schema bullet, the §"Reserved media boundary" heading + paragraph
(QC3-003), the §"No-JSONL contract" three-command list, the credential-boundary last sentence, the workflow
command line (now a *usage error* — verified: `harvest-subs` without a bound exits `1` at `cli.py:858-864`),
the writer/read-only lists, the run-ledger sentence, the renamed heading + its anchor, the ⚠️6 sentence, the
mixed-outcome paragraph, and the smoke heading/count line. Every deletion is a replaced or renamed
sentence/section; no content is lost, and the replacements are strictly more accurate (all seven spot-checks
above pass). The heading anchors the README uses (`#fresh-start-sqlite-archive-fetch-meta--status--runs`,
`#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs`) match the headings actually shipped.

### Non-vacuity of the new module's rehearsals

I re-ran the module offline (`18 passed, 1 skipped`) and reconstructed the failing test for each of the
branches the brief asked to name (read-only reconstruction, no mutation run):

1. **Opt-in gate** — loosen `_live_smoke_requested()` (`:197`) from `== "1"` to truthiness →
   `test_the_live_smoke_switch_is_opt_in` (`:932`) fails: it is the only case pinning `""`, `"0"`, `"true"`,
   `"yes"`, `"2"` as *not* opted in.
2. **Missing-pin loud-fail** — make `_pinned_package_version()` (`:203`) return a fallback or `pytest.skip` →
   `test_missing_pinned_distribution_fails_loudly` (`:1214`) fails: it requires `pytest.fail.Exception` and
   the distribution name, the pinned version and `uv sync` in the message.
3. **Bounded-blocker path** — widen the recordable set (add `transport_error`) →
   `test_every_other_bounded_code_fails_loudly[transport_error]` (+ the three sibling params, `:1207`) fails;
   conversely, drop `not_found` from `RECORDED_BLOCKER_CODES` →
   `test_the_documented_bounded_codes_are_recorded[not_found]` (`:1192`) fails, because those parameters are
   literal codes rather than derived from the frozenset (the deliberate design the docstring names).
4. **Probe is read-only** — put `probe-subs` back into `_ARCHIVE_WRITER_COMMANDS` →
   `test_the_seeded_root_survives_the_probe_with_no_new_file` (`:944`) fails at
   `_archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]`: the lock would appear.
5. **Folded `credential_present`** — hardcode `credential_present=False` at the probe construction site
   (`cli.py:786`) → `test_probe_result_carries_the_credential_presence_the_cli_observed` (`:1257`) fails on
   `[False, True]`; the printed line cannot mask it, because the CLI computes that line independently from
   `redact_sessdata(sessdata)` (`cli.py:801`).
6. **M1 asymmetry** — map the harvest's `GatewayNotFound` to `failed` → the second half of
   `test_a_refused_listing_is_read_from_the_probe_and_never_harvested` (`:1169-1188`) fails (it asserts exit
   `0` and `no-subtitle` for the same bounded answer the probe reports as `failed not_found` with exit `2`).

The rehearsals are also environment-independent in the right direction: the four CLI rehearsals request the
non-autouse `anonymous_environment` fixture, and if they were dropped while the operator's shell carried a
credential, the `expect_credential_present=False` line assertion would **fail** rather than pass quietly.

## What the live evidence does and does not prove

**How the recorded line is produced (the focus's "not synthesized" question).** The line
`live subtitle CLI smoke evidence: …` is printed by the *test* (`:847`, and `:719` on the skip path), as the
metadata smoke already does (`tests/test_live_metadata_smoke.py:353`). That is the house pattern, and no field
is fabricated: `part_source` is the smoke's documented provenance constant; `work_id`, `probe_exit`,
`probed/with_tracks/without_tracks/probe_failed`, `track_count`, `tracks`, `harvest_exit`, `run_id` and the
harvest counts are **parsed out of the shipped CLI's stdout** by full-match regexes
(`_read_probe_output:340`, `_read_harvest_output:398`) that fail on any shape drift, and `sessdata` is the
presence token that the same run's own `sessdata:` line is asserted against (`:329-338`); `source_kind`,
`language`, `version`, `segments`, `transcripts`, `attempts` and `pending_after` come from the **rows the CLI
wrote**, each asserted (`_assert_stored_rows:501-593`). Nothing is hardcoded except the constant
`work_id`/`part_source` labels, both cross-checked against the CLI's printed line (`:383`, `:432`) and against
the seeded pending row (`:479-499`).

**Assertions that require the recorded facts (not just print them).** `probe_exit=0` →
`assert probe_exit == 0` (`:788`); `harvest_exit=0` → `assert harvest_exit == 0` (`:803`);
`attempted=1` → `:349` (probe) and `:412` (harvest); `stored=1` → implied by `outcome == "stored"` plus
`assert (harvest.failed, harvest.no_subtitle) == (0, 0)` (`:804`) and `attempted == 1` (`:412`);
`remaining_without_transcript=0` → `:805`; `segments=2913` → the segment sweep at `:541-552` (ordinal order,
non-decreasing starts, non-empty intervals — the count itself is correctly not pinned); `transcripts=1`,
`attempts=1`, `pending_after=0` → `:523`, `:576`, `:583-586`; `source_kind`/`language`/`version` → `:525-531`
(allowed enum, non-empty language, version 1, 64-char hash); `sessdata=present` → the printed line
(`:329-338`) **and** the run row (`:557-573`, `credential_present` against `int(expect_credential_present)`);
`track_count=1`/`tracks=ai-zh:ai` → `:378` (one track line per visible track) and `:383`
(`work_id == SAMPLE_WORK_ID`); `run_id` → parsed from the summary and equal to nothing else asserted live
(see Minor 4); the root file set → the exact-set assertion `:675-689` (`archive.db` + the lock only, no
sidecar, no projection).

**So the run proves**: the shipped CLI + gateway + storage chain really does acquire a machine caption for a
real public part end to end, in the locked call shape, inside a temporary root, with one run row and one
attempt row, and leaves an archive root containing only the database and the writer lock. It also proves the
`-s -v` observation was taken through the operator's credential (the run row's `credential_present=1` is part
of the asserted set), that the probe took no lock, and that no credential value reached stdout, stderr or any
persisted row.

**It does not prove** (and nothing here claims otherwise): anything about corpus coverage or caption quality;
that the endpoint keeps answering the same way (the sample is dated and replaceable in one line, and the
module documents the `not_found`/`rate_limited`/`tracks=0` brackets as legitimate alternative observations);
that the printed `run_id` matches the persisted row live (only Task 2's E2E pins that pairing); and — because
the live process is not reproducible from this seat — the run's existence beyond the operator's recorded line.
The bounded observations of the two aborted attempts are described but **not** used as evidence.

## Invocation ledger (the disclosed deviation) — reviewer's judgement

Three live invocations instead of one. **The ledger is complete and honest as far as a read-only seat can
judge, and the deviation is acceptable for this task, but it should be recorded rather than waved through.**

- **Completeness/honesty.** All three attempts are stated, with the cause of each, and the report is explicit
  that **no evidence is claimed from attempt 1** (its `sessdata=absent tracks=0` observation is described as
  the documented "nothing visible now" reading of an anonymous bracket, and the acceptance-carrying line is
  attempt 3's). The two claimed test-side defects leave visible traces in the committed file, which
  corroborates the story rather than merely asserting it: the credential fixture is now explicitly
  non-autouse with a docstring naming exactly the trap (`:861-871`), and `_flush_output` exists solely to drop
  the smoke's own preamble before reading command output (`:873-881`, called at `:764`) — the two symptoms
  attempt 1 is said to have produced. The report also states the change between attempts 2 and 3 (probe counts
  folded into the evidence line; the second `capsys` flush removed) and that no assertion changed.
- **What cannot be verified.** The range contains a single test commit (`d5c0f9e`, author = committer =
  17:16:27, i.e. after all three runs), so the attempt-1/attempt-2 states of the file are unrecoverable from
  git; the "presentation-only" claim and the "no assertion changed" claim are structural inferences
  (the final file has exactly one flush call and the line does carry the probe counts), not proof.
- **Cost and blast radius.** Each invocation is two or three upstream calls by the shipped fail-fast gateway
  with no retry and no call-shape change, so the extra load is a handful of bounded calls — not the unbounded
  probing this iteration's constraints forbid. No run was discarded because of an upstream answer, and all
  three are mutually consistent.
- **Judgement.** Not a defect and not a reason for a fix round; the disclosure is exactly what the harness
  asks for. But the plan's live budget was one bounded run, and the extra invocations were avoidable in
  principle (a smoke that asserts the credential expectation before spending a call would have failed
  attempt 1 faster — see Minor 5). PM: record the deviation in the durable plan summary / QC bundle so the
  iteration's live-probe discipline stays auditable, and do not let it be silently normalized for later plans.

## Strengths

- **The live smoke asserts its own honesty rules, including the ones that cost it a pass.** A captionless,
  `not_found` or `rate_limited` outcome prints the bounded facts and **skips** (`_record_and_skip:711`)
  instead of reading green; every other bounded code fails loudly (`_assert_bounded_blocker_is_recordable:653`
  with the regression rationale in its message). A run that stored nothing can never be reported as a
  subtitle acquisition.
- **The offline rehearsals are real coverage of the smoke's own logic, not ceremonial copies.** Both readers,
  all three row assertions, the exact root file set, the refusal ladder, the loud-fail guard, the credential
  expectation rule and the leak scan are exercised through the shipped CLI over the shared seam, so a broken
  query or a loosened assertion fails in a default pytest run rather than first during a live run. The
  documented-codes parametrization is deliberately literal so the frozenset cannot shrink silently.
- **The read-only and credential promises are structural.** `probe-subs` takes no lock, creates no file, opens
  no run row and never creates the database — pinned by `:944` (probe leaves exactly `archive.db`) and
  `:675` (harvest leaves exactly `archive.db` + the lock). The credential is only ever handled as presence,
  and the leak check is an explicit `raise` with a fixed message specifically so pytest's assertion
  introspection cannot render the credential into a failure report (`:692-709`) — a subtlety most tests miss.
- **The docs are behaviour-checked, not aspirational.** They name the lock path, the writer set, the exact
  printed lines, the enum values and the family rule, and every one of the seven claims I spot-checked matches
  the shipped code; the QC3-003 sentence was replaced in place rather than decorated, and the ⚠️6 boundary is
  stated in three places (docs section, README bullet, `run` paragraph) — which is what an operator hitting
  `download-audio --missing-subs` needs.
- **The sample-part choice is disclosed and minimized**: only the identity is real (validated by the live
  listing itself), the scaffolding is written through the shipped repository, `part_source=fixed-sample` is
  recorded, and the fixture removes the temporary root in-process (`git status` stayed clean after my run;
  `.test-tmp/` holds only the pre-existing `audio-outside.m4a` from `test_audio.py`).
- **No production file changed in this range** (three paths: two docs + one new test), so Task 3 cannot have
  moved behaviour, and the smoke exercises the shipped CLI unchanged.

## Issues

#### Critical

None.

#### Important

None.

#### Minor

1. **The report's **M1** row claims a README bullet that does not exist** (implementer report §Implemented,
   M1 row: "`docs` §… + README bullet"). The README names the `probe <work_id> failed <code>` line only inside
   its output-shapes list (`README.md:611`) and never states the two readings; the full M1 statement lives in
   `docs/metadata-storage.md:170-178`. The obligation is met where the plan names it (`docs` + README as
   documents, with the asymmetry documented once and pointed at from the README's "full contract" line), so
   no rework is needed — but the report overstates README coverage. Same class as Task-2's Minor 1: a
   report-accuracy correction, not to be propagated into the QC/knowledge record.
2. **The probe path is never scanned for the seam's URL/body sentinels, and live that scan is vacuous.**
   `assert_leaks_no_markers` runs on the harvest output only (`:795`, and `:1037/:1083/:1118` offline), while
   the probe's stdout is the one place this CLI prints an **upstream free-text field**: `track <lan> <ai|cc>
   <label>` (`cli.py:812`) where `label` is `lan_doc` passed through trimmed from upstream
   (`bilibili_api_gateway.py:273-305` reads the entry and deliberately does not read `subtitle_url`). Live,
   the sentinel scan could not fire anyway (the fake seam is not installed), so the meaningful live scan is
   the credential one — which does cover probe output (`:777`, `:796`). Recommendation for a later touch (not
   a fix round): add `assert_leaks_no_markers(probe_out + probe_err, …)` to the probe rehearsal with a
   marker-bearing scripted label, and scope the docs sentence "No output carries a credential, a signed URL,
   a raw body, or upstream message text" (`docs/metadata-storage.md:153`) to the error/evidence paths, since
   the documented line shape next to it prints `lan_doc`.
3. **The docs' recorded live line is an abridged restatement.** `docs/metadata-storage.md:510-519` quotes the
   observation without `run_id=…`, which the committed code prints (`tests/test_live_subtitle_cli_smoke.py:838`)
   and the implementer report's copy of the same line includes; every other field is byte-identical. Cosmetic,
   but the docs elsewhere promise the run id is always printed, so the quote reads as slightly inconsistent
   with the contract it documents.
4. **Three live-evidence fields are parsed and printed without an assertion tying them to their source.**
   `with_tracks`, `stored` and the printed `run_id` are read by the readers (`:340-455`) and re-emitted in the
   evidence line (`:832-846`) but never asserted live: `stored == 1` follows arithmetically from the stored
   branch plus `failed == no_subtitle == 0` (`:804`) and `attempted == 1` (`:412`), and `run_id` is
   cross-checked against the persisted row only in Task 2's E2E (`test_subtitle_e2e.py`). The substance is
   covered (the DB run row is asserted to be exactly one, terminal, and linked to the attempt at `:555-586`),
   so this is a one-line strengthening (`assert harvest.stored == 1`, and the printed `run_id` against the
   persisted row) rather than a hole.
5. **The live test body itself is never executed offline, and a missing credential reads as a legitimate
   skip.** The rehearsals duplicate the live test's assertions rather than driving the same function, so the
   live-only composition — the `summary` assembly (`:832-846`) and the `if harvest.outcome not in ("stored",
   "unchanged")` skip branch — is covered only by the single 2026-09-11 run. Relatedly, because the smoke
   derives its expectation from the same environment the command reads, an operator who forgot to source the
   credential gets `sessdata=absent` plus `tracks=0` and a *skip*, not a loud "you forgot the credential";
   the evidence line carries the token so the reading is honest, but the operator guidance ("a
   `sessdata=absent` skip says nothing about upstream") deserves a sentence next to the smoke's documented
   outcomes in `docs/metadata-storage.md:501-509`. Informational; no acceptance item is affected.
6. **Cosmetic module organisation.** `_flush_output` (`:873`) is defined inside the "rehearsals" section but is
   used by the live test at `:764`; the live-path helpers and the rehearsal helpers are interleaved
   (`_seed_probe_part:259`, `_rehearsal_tracks:884`). Works fine; a reader would find the live path faster if
   the module kept the two sections contiguous.

## ⚠️ Cannot verify from diff / for PM to check

1. **The live run is not reproducible from this seat** (live network forbidden by the dispatch). I judged the
   recorded facts analytically: the module's assertions genuinely require every fact in the evidence line, and
   the recorded line is internally consistent with them. PM: treat the run itself as the implementer's primary
   evidence and the report's screenshots-free line as its record.
2. **The three-invocation ledger's details are not verifiable from the committed range.** The range has one
   test commit (17:16:27, after the runs), so attempt 1/2 file states are unrecoverable; the "presentation-only"
   change between attempts 2 and 3 is corroborated structurally but not provable. PM: record the deviation and
   its bounded cost in the durable summary (see the ledger judgement above) instead of treating it as routine.
3. **Broader test counts are implementer-reported only.** I confirmed the new module (`18 passed, 1 skipped`,
   re-run) but not the focused group (`116 passed, 3 skipped`), the full suite (`1279 passed, 4 skipped`,
   baseline `1261/3`) or the `git diff --check` output. PM: take these as implementer evidence for the plan's
   "offline suites green" Done criterion; the arithmetic is internally consistent (`1261 + 18 = 1279`,
   skips `3 + 1 = 4`).
4. **Two earlier ⚠️ items are now discharged and can be closed by PM**: Task-1 ⚠️2 (the spec §6 sentence vs the
   shipped writer lock) and Task-2 ⚠️4 (the lock had to be documented) — the lock is now documented in both
   docs and pinned by the smoke's exact-set assertion, so the spec-vs-implementation gap exists only as the
   spec's original wording, which this plan does not own. Task-2 ⚠️6 (`ProbeResult.credential_present` never
   asserted) is likewise discharged by `:1257`.

## Assessment

**Task quality: Approved**

This is the task that carries the iteration's operator-visible acceptance, and it lands both halves. The live
smoke is a real end-to-end exercise of the shipped CLI + gateway + storage chain over one bounded, disclosed
sample part: it asserts the printed line shapes rather than grepping them, asserts the normalized rows, the
run/attempt evidence and the exact archive-root file set, scans stdout, stderr and every persisted row for the
credential value (with the assertion-introspection trap explicitly defused), and refuses to read green on a
run that stored nothing. Its offline rehearsals give the module 18 passing cases that genuinely fail under the
mutations I reconstructed (opt-in gate, missing pin, bounded-blocker permissiveness, probe writer-set
regression, `credential_present` hardcoding, and the M1 asymmetry on both sides), so the live test is not
load-bearing-by-assertion-only. The documentation obligations are met with substance: the QC3-003 false
sentence was replaced in place, M1 / ⚠️2 / ⚠️6 are stated where an operator will look, and every doc claim I
spot-checked (seven) matches the shipped code; the 37 deleted lines are all replacements or renames, and no
production file moved in the range.

The invocation ledger is the one real concern and it is handled the right way: disclosed with its causes, no
evidence claimed from the aborted runs, corroborated by the shape of the committed fix, and bounded in cost —
acceptable, but worth recording in the durable summary rather than normalizing. The six Minor findings are all
report-accuracy, assertion-strength, or cosmetic items with no shipped-behaviour implication; none of them
justifies a fix round, and none touches an acceptance criterion.

- Critical: 0 · Important: 0 · Minor: 6
- ⚠️ items for PM: 4 (the live run itself unreproducible; the ledger's details unverifiable from the range and
  to be recorded; the broader counts implementer-reported; two earlier ⚠️ items now closable)
