# SDD Progress — 20260911-subtitle-cli-cutover

Task 1: complete + review **Approved** (`c5a9b82..8ec992b`)

- Implementer commit: `8ec992b feat(cli): cut probe-subs and harvest-subs over to the SQLite subtitle path`
  (DONE_WITH_CONCERNS)
- Evidence: focused `65 passed`; full offline suite `1251 passed, 3 skipped` (baseline 1202/3; +65 new, −16
  legacy cases whose subject was removed); an isolation rerun (`test_metadata_cli.py` + `test_subtitle_cli.py`
  → `98 passed`) caught and fixed a real seam/fixture interaction (the fixture drops the adapter module from
  `sys.modules`, so the gateway fixture now resolves it via `importlib.import_module`); five mutations each
  reverted (AI-first preference restored → 18 failed; probe terminal code → 1; degraded guard line → 1;
  `probe-subs` back in the writer set → 4; `not_found` → `failed` → 1); `git diff --check` clean.
- Delivered: `services/subtitle_ingest.py` (`SubtitleIngestor`, family/CC-before-AI preference, one repository
  call per part, run lifecycle with derived outcome and `failed` closure) and both commands in `cli.py`
  (argparse, read-path DB guard, `require_subtitle_schema` + the **composed** rebuild line, locked output
  lines, `probe-subs` removed from `_ARCHIVE_WRITER_COMMANDS`), plus `tests/test_subtitle_cli.py`.
- Task reviewer: `review/task-1-review.md` — **Approved** (0 Critical / 0 Important / 4 Minor). It verified the
  carry obligations against shipped sources (11-col `v_video_parts` vs 12-col `v_pending_subtitles`; the
  published enums; `SchemaContractError` carrying neither root nor prefix), spot-checked M1/M3 non-vacuity by
  name, and judged the **legacy replacement sound**: the diff deletes 16 test functions and every one maps to a
  named, stronger replacement, with `subtitles.harvest_subtitle` still shipping and exercised; the only
  production change is `cli.py` + the new service (the `_open_read_connection` extraction is behaviour-preserving).
- PM dispositions: the two disclosures accepted (`credential_present` keyword-only ctor arg, noted beside R1;
  `selector_target`/unknown-`bvid` handled pre-run). **M3** (lost env-credential assertion) and the
  documentation follow-ups **M1** (probe vs harvest `not_found` asymmetry) / **⚠️2** (the writer lock) /
  **⚠️6** (`download-audio --missing-subs` gains nothing) are folded into Tasks 2–3; **M2** (finish outside the
  interrupted-run guard) and **M4** (cross-test private helper import) are recorded nits.

## Next

Task 2 (offline subtitle E2E over the fake seam) — incl. the folded M3 assertion and the F3 double extension.

Task 2: complete + review **Approved** (`8ec992b..c501d9a`)

- Implementer commit: `c501d9a test(subs): land the offline subtitle E2E and script it through the shared seam`
- Evidence: focused `tests/test_subtitle_e2e.py` → `10 passed`; pair with the CLI module → `75 passed`; an
  isolation rerun with `test_metadata_cli.py` + `test_bilibili_api_gateway.py` → `422 passed, 1 skipped`; full
  offline suite **`1261 passed, 3 skipped`** (baseline 1251/3, +10); 8 mutations of shipped code each reddening
  the intended case(s); `git diff --check` clean.
- Delivered: `tests/test_subtitle_e2e.py` (10 cases driving `bili_asr.cli.main` over the shared double:
  normalized rows + run/attempt evidence for a CC part and an AI-only part, idempotent re-acquisition, v2 with
  v1 readable, captionless + body-failure parts keeping bounded evidence without claiming success, enumeration
  progress, complete summaries incl. `attempted=0`, the probe's zero-write boundary incl. the missing-DB
  refusal, no sidecar/projection, no-leak scans over output and all rows); **F3** the `FakeGateway` double gained
  the two subtitle methods + a `fake_gateway_seam` install fixture, with `test_subtitle_cli.py` scripted through
  it (private double deleted, **zero assertion lines changed**); **M3** env-sourced credential asserted present
  and absent (value reaches the adapter, `credential_present` 1/0 in the run row, printed line, value nowhere).
- Task reviewer: `review/task-2-review.md` — **Approved** (0 Critical / 0 Important / 3 Minor). It reproduced
  the focused run, mechanically proved F3 left the seam's strict assertions byte-identical (fixture deletions
  are 4 docstring lines; no deleted line in `test_subtitle_cli.py` is an assert/test/mark), verified the probe's
  zero-write structure against the shipped writer-set and guard ordering, and reconstructed 6 of 8 mutations to
  their **named** failing cases.
- PM dispositions: disclosures 1/2/4/5 accepted; disclosure 3's justification corrected (Minor 1 — the report's
  claim about the metadata clock fixture is factually wrong; only the subtitle path cannot take a clock because
  `_now` is bound as a default argument). Minor 2/3 recorded as nits. The **seam follow-up decision** and the
  **`ProbeResult.credential_present` assertion** are recorded/folded into Task 3, which also owns the writer-lock
  and asymmetry documentation.

## Next

Task 3 (bounded live smoke + operator documentation) — the final task of the plan.

Task 3: complete + review **Approved** (`c501d9a..8373817`)

- Commits: `d5c0f9e test(subs): add the bounded live CLI smoke with its offline rehearsals`,
  `8373817 docs(subs): document the SQLite subtitle path and the live smoke`
- Evidence: new module offline `18 passed, 1 skipped`; focused group `116 passed, 3 skipped`; full offline
  suite **1279 passed, 4 skipped** (baseline 1261/3; +18 rehearsals, +1 opt-in gate); `git diff --check` clean.
- **The iteration's acceptance evidence — a real live acquisition through the shipped CLI + storage chain**
  (pytest exit 0, credential sourced and never printed, 0 occurrences in the log, temp root):
  `part_source=fixed-sample work_id=BV1S8hA6MEvy:p0 sessdata=present probe_exit=0 probed=1 with_tracks=1
  without_tracks=0 probe_failed=0 track_count=1 tracks=ai-zh:ai harvest_exit=0 run_id=… attempted=1 stored=1
  unchanged=0 no_subtitle=0 failed=0 remaining_without_transcript=0 source_kind=subtitle-ai language=ai-zh
  version=1 segments=2913 transcripts=1 attempts=1 pending_after=0`; the temporary root held only
  `archive.db` + `coordinator/archive-writer.lock`.
- Documentation: `docs/metadata-storage.md` 292→560 and `README.md` 677→791 — the subtitle path, both commands
  with bounds/exit codes/output shapes, the family-based preference rule, credential handling, the guard +
  rebuild procedure, the two schema resources, the legacy manifest boundary + `needs_audio`, and the folded
  **QC3-003** (the now-false sentence replaced in place), **M1** (probe-vs-harvest `not_found` asymmetry),
  **⚠️2** (the writer lock, `probe-subs` lock-free), **⚠️6** (`download-audio --missing-subs` gains nothing).
  The folded `ProbeResult.credential_present` assertion also landed.
- Task reviewer: `review/task-3-review.md` — **Approved** (0 Critical / 0 Important / 6 Minor). It re-ran the
  module offline (`18 passed, 1 skipped`), checked seven doc claims against shipped code, mapped all 37 doc
  deletions to replacements, named the failing test for six rehearsed branches, and judged the live evidence
  carefully: the evidence line is test-composed (the house pattern) but every field is parsed from the shipped
  CLI's stdout or read from the rows, each with an assertion that would fail if the fact were absent.
- **Invocation ledger (disclosed deviation)**: three live invocations instead of one + one retry; the first two
  exposed defects in the smoke file itself (the first was aborted by an autouse fixture that stripped the
  operator credential → anonymous `tracks=0`; no evidence claimed from either), the third confirmed after a
  presentation-only change. The reviewer judged the ledger complete and honest — the fixes leave visible traces
  (the credential fixture is now explicitly non-autouse with a docstring naming the trap) — and recommended
  recording the deviation rather than normalizing it. PM records it here and in the plan's durable summary.
- Minor findings (all non-blocking) and PM disposition: **folded into the plan-QC fix round** (below) rather
  than a separate cycle — (2) the probe's stdout is never sentinel-scanned while a `lan_doc` label can be
  printed, and the docs' "no upstream message text" sentence sits next to that documented line; (3) the docs'
  quoted live line drops the `run_id` the code prints; (4) `with_tracks`/`stored`/printed `run_id` are emitted
  but not asserted; (5) the live test body never runs offline and a forgotten credential reads as a legitimate
  `sessdata=absent` skip; (1)/(6) report-prose and module-organisation nits. Task-1 **⚠️2**, Task-2 **⚠️4** and
  Task-2 **⚠️6** are discharged by this task and can be closed.

Plan QC tri (N=3) — seat 2 landed: **Approve** (0 Critical / 0 Warning / 9 Suggestion)

- Independently verified from source: the two row shapes normalized (caller supplies `bvid` for the 11-column
  selected shape), `cid` always from `video_parts`, the family/CC-before-AI key matching the spec literally,
  exact `--language` first-match-wins, unmatched-valid-preference → `no-subtitle` without fetching the body,
  one repository call per part, the run lifecycle (`kind` validated against the enum, selector kind/target,
  `requested_limit`, `credential_present`, derived outcome, empty selection = `complete`), the
  `except BaseException → finish_failed_run → raise` escape path, and the probe's write-free observables.
- Idempotency precision: dropping the `content_sha256` predicate keeps the *unchanged* case green but reddens
  the revised-caption case (`versions == [1,2]`); always-append reddens the unchanged case. The unchanged
  guarantee is asserted on the explicit `--bvid` re-check path (the pending path advances by design).
- F3 integrity confirmed at branch scale: `test_bilibili_api_gateway.py` is not in this branch; the fixture's
  deletions are exactly 4 docstring lines; the seam's strict helpers are untouched.
- Blast radius: only `cli.py` + the new service changed under `src/`; the `_open_read_connection` extraction is
  behaviour-preserving; the legacy producer is still called by `coordinator.py`/`cli.py`.
- Suggestions and PM disposition (fix round unless noted):
  - **QC2-001** (real coverage gap) → add a test where a failed part precedes a later success in one bounded run
    (a loop-early-abort regression would otherwise escape).
  - **QC2-002** (implausible trigger, bounded ladder escape) → a pathological upstream `to` (>1e9 s) makes the
    storage ceiling raise, which escapes the per-part outcome ladder and aborts the whole run; handle the
    storage validation error per part as a bounded `failed` outcome.
  - **QC2-003** → the probe does not literally open a read-only connection (`open_database` runs both idempotent
    schema scripts and commits) although every tested observable holds; open the probe connection read-only.
  - **QC2-004** → the probe prints upstream free text (`lan_doc`) while its sentinel scan uses benign labels, and
    `docs/metadata-storage.md:153` states a stronger promise than the shipped line; scan the probe output and
    align the sentence (same class as the Task-3 Minor 2).
  - **QC2-005** → the run row does not persist the `--language` preference, so a preference-scoped `no-subtitle`
    is indistinguishable later → **recorded** in the plan's durable roadmap (a schema column decision belongs to
    a storage owner).
  - **QC2-006/007/008** → already recorded nits (M2, `_archive_files` empty dirs, the private cross-module test
    import).
  - **QC2-009** → the live smoke prints `with_tracks`/`stored`/`run_id` without asserting them and the live body
    never runs offline → fold (with Task-3 Minor 4) into the fix round.
- ⚠️ for PM/L4: the suite counts and `git diff --check` remain implementer evidence (QA reproduces); the live
  run + the three-invocation ledger are unreproducible from a review seat → **record the deviation** (done, above)
  and keep the budget note; the spec §6 "no file except its database" sentence vs the shipped writer lock → PM
  aligns the spec wording.

Plan QC tri — seat 3 landed: **Approve** (0 Critical / 0 Warning / 6 Suggestion) + the A1–A12 mapping

- **Iteration acceptance mapping (seat 3, compass A1–A12)**: all twelve satisfied, none falsified — A1/A2 (live
  one-track probe + rows; zero/multi-track shapes offline), A3/A4 (offline v2 + v1 readable), A5 (mapping
  offline/P1-pinned; the live run carried no failure code), A6 (P2 + live rows), A7 (strongest: the live file
  set), A8 (structural, caveat Q3-02), A9 (E2E incl. `attempted=0`), A10 (offline E2E + schema view/order),
  A11 (primary branch taken — no fallback; both counts implementer-reported → QA), A12 (with precision items
  Q3-01/04/05). **Unproven-live by design**: A3, A4, A5's mapping, A10.
- Evidence-honesty verdict: the recorded live line is test-composed (house pattern) but every field is derived
  from the shipped CLI's stdout or the rows it wrote, each with an assertion that would fail if the fact were
  absent; no autouse fake seam exists, so the live test used the real adapter. It proves one real part
  end-to-end; it does **not** prove corpus/coverage/quality, the offline-only paths, endpoint stability, the
  `run_id` pairing live, or its own existence. The **invocation ledger is complete and honest** as far as a
  read-only seat can judge; the PM records the deviation in the durable summary/compound (not a register entry,
  which would need a defect and a closure condition — the only machine-trackable residue is Q3-03's slow-fail).
- Closure obligations verified: F3 ✅, R1 correctly open and retargeted ✅, QC3-003 ✅ (the false sentence replaced
  in place; the old phrases grep to zero), QC3-005 ✅ (composed line + exact-line test), QC3-002 ✅ (guard was
  already at the base commit), M1/M3/⚠️2/⚠️6 ✅, the legacy deletions all map to replaced manifest semantics with
  `subtitles.harvest_subtitle` still exercised from four modules, and nothing in the range invalidates a closed
  plan's claims.
- Suggestions (all documentation-precision/assertion-strength/process; PM disposition → **fix round**):
  - **Q3-01** — `_family_rank` collapses every non-`zh`/`en` family to rank 2, so CC-before-AI decides across
    distinct rest-families while the docs/plan prose say "inside the same family"; the code matches the locked
    spec key, so the prose is the imprecise artifact → add one docs clause **and** a pinning test.
  - **Q3-02** (= Task-3 Minor 2) — the probe's stdout is the only surface printing upstream free text
    (`lan_doc`) and is never sentinel-scanned, while `docs/metadata-storage.md:153` promises "no … upstream
    message text" → scan the probe output and scope the sentence.
  - **Q3-03** (= Task-3 Minors 4/5, QA-facing hazard) — the live line prints `with_tracks`/`stored`/`run_id`
    without assertions tying them to their source, and a forgotten credential reads as a *skip* rather than a
    failure → assert the fields and make a missing credential loud when the operator intended a live run.
  - **Q3-04** (= Task-3 Minor 3) — `docs:510-519` quotes the live line without the `run_id=` the code prints.
  - **Q3-05** — `harvest-subs` takes the writer lock **before** the DB check, so a failed/mistyped harvest still
    creates `<root>/coordinator/` (the spec's "no file … except the database writes" clause is thereby
    qualified — the PM has already appended a dated clarification to it); the rebuild step omits the default
    10-page `fetch-meta` bound; the README Workflow block places `harvest-subs` above
    `download-audio --missing-subs` with no ⚠️6 pointer.
  - **Q3-06** — Durable Roadmap Gate: the "retiring `bili_client` subtitle methods" deferral and the recorded
    nit M2 lack an owner/trigger → give them both in the plan text.

Plan-QC fix wave (`8373817..7e57eb6`, revalidation in flight)

- Dispatch note: the first fix-wave dispatch failed at the harness level and left uncommitted WIP (6 files,
  focused-green at `406 passed, 1 skipped`); a fresh implementer resumed, audited it, and completed the wave.
- Commit `7e57eb6 fix(subs): answer an unstorable --bvid as unknown and bound every per-part anomaly`.
- Evidence: focused (subtitle CLI + E2E + live smoke + gateway) `438 passed, 2 skipped`; full offline suite
  **1311 passed, 4 skipped** (baseline 1279/4; +32 = 28 cases from the inherited WIP + 4 here); 9 mutations
  each reddening its named test with files restored byte-identically; runtime checks offline: `probe-subs
  --bvid ""` → `probe-subs: unknown --bvid ` + exit 1, and `harvest-subs` on a missing root → exit 1 with only
  `coordinator/archive-writer.lock` created (the F-001 taxonomy and the Q3-05 lock-ordering claim, both
  reproduced); `git diff --check` clean; the control checkout untouched.
- **The audit caught a real regression in the inherited WIP**: F-003's strict DTO `_text` was shared, so it also
  rejected interior control characters in caption **body** text — a two-line cue would have ended a whole
  harvest. Fixed by mirroring the storage layer's `_caption_text` (`sources/models.py:46-60/:176`) plus the
  regression test `test_caption_text_keeps_interior_control_characters_as_one_row`.
- Items landed: F-001 (selector guard before the DB open + the 7-selector parametrization), F-002 (the rebuild
  message shown as one line and stated to go to stderr), F-003 (reject control characters in `lan_doc` at the
  DTO; captions keep interior control characters), QC2-001 (failed-part-first ordering case), QC2-002 (per-part
  ceiling `ValueError` → bounded `failed`/`shape_error`), QC2-003 (the probe opens `mode=ro` with a write-proof
  test), QC2-004 (+ the docs sentence scoped to the error/evidence paths and the probe stdout now
  sentinel-scanned with an offline rehearsal), QC2-009 first half (the live readers now assert
  `with_tracks`/`without_tracks`/`failed`, the four harvest counts and the printed `run_id` against the row),
  QC2-009 second half (opted-in without a resolvable credential now **fails loudly**, default still skips),
  Q3-01 (prose fixed in both docs + the across-two-rest-families pinning test), Q3-04 (the quoted live line
  carries the real `run_id`), Q3-05 (the lock-before-DB-check behaviour, the rebuild's implicit 10-page
  `fetch-meta` bound, and the README Workflow ⚠️ pointer).

Plan-QC fix wave revalidation — seat 1 (the Warning raiser) landed: **Approve** (was Request Changes)

- **F-001 CLOSED at the taxonomy level**: the guard sits in both handlers immediately after `_subtitle_selector`
  and before `_resolve_sessdata` and the only DB open; its predicate mirrors the storage rule byte-for-byte
  (`not bvid.strip() or any(mark in bvid for mark in "\x00\r\n")` vs `storage/models.py:64-72`), so it cannot
  over-reject a storable value; the answer is byte-exact `"<command>: unknown --bvid {args.bvid}"` on stderr with
  exit 1. The usage parametrization grew 10 → 15 cases plus a dedicated 7-value × 2-command case asserting
  byte-exact stderr, empty stdout, exit 1, no gateway call and zero run/attempt rows — all failing on the pre-fix
  source (non-vacuous). The seat re-took the runtime reproduction itself offline (`probe-subs --bvid ""` →
  `probe-subs: unknown --bvid ` + exit 1 + nothing created; `harvest-subs --bvid "   " --limit-parts 2` → the
  same line + exit 1 with only the documented pre-dispatch lock left). One deliberate precedence change (selector
  check now outranks the missing-DB guard; both exit 1) is pinned by a new test.
- **F-002 CLOSED** (one code line in the docs + the stderr transport stated in both docs).
- **F-003 + the audit finding CONFIRMED CORRECT**: caption bodies go through the new `_caption_text` (a faithful
  mirror of the storage layer's, verified line by line) while `language`/`label`/`track_id` use the strict
  `_text`; the seat proved non-vacuity by simulating the revert **in memory** (`models._caption_text = models._text`)
  → the DTO raises `ValueError` and `_normalize_subtitle_segment` (the only normalizer with no try/except) leaks
  it raw, ending a whole harvest — so the new regression test fails if the split is removed.
- Regression lens (−92): all 92 deletions classified (58 replaced implementation/prose lines; 34 replaced test
  lines with no assertion weakened, three strictly strengthened); the live smoke's opt-in skip + pin moved into
  `_live_preconditions()` still called first, so a default run still skips; the metadata path's assertions are
  untouched (0 deletions in its gateway test file); probe zero-write is now structural (`mode=ro`, no WAL).
- Two non-blocking observations recorded as durable nits with owner/trigger (the two new
  `unreadable archive database` branches have no test/doc sentence → QA exercises them at runtime and a future
  plan pins them; the `unknown --bvid` guard echoes the raw selector so a control-character value adds a second
  stderr line → accepted, stderr is not the locked machine surface).

Plan-QC fix wave revalidation: **all three seats Approve** → gate closed

- Seat 2 (Approve): five items closed as specified with named tests and revert paths; four dispositioned by
  record; the 92 deleted lines classified with no assertion weakened (test arithmetic +16 corroborates);
  F-003's split judged to preserve the storage layer's verbatim-caption contract.
- Seat 3 (Approve, with one open item): Q3-01/02/03/04/05 closed and verified (the Q3-01 pin fails under the
  old prose's reading); **A7 and A8 strengthened**; A1–A12 re-checked with no criterion falsified and A9's
  precision flag lifted. It flagged that Q3-06 was only partially closed — the legacy-retirement bullet still
  lacked owner/trigger — which the PM has now written in full (owner, trigger, done-definition), closing it.
  Bookkeeping note it raised: the fix report lists the spec §6 errata as open, but the PM's dated clarification
  to §6 landed earlier, so that item is closed at the spec.
- PM dispositions applied during the round: the two seat-1 observations (untested `unreadable archive database`
  branches → durable nit with owner/trigger + a QA-gate runtime check; the raw-echo of `--bvid` → accepted nit)
  and the QC2-005 owner/trigger tightening.

## Next

Mandatory QA gate (L4) on `7e57eb6`, then the integration merge and plan Done.

QA gate round 2 (re-verification): **Approve (recommend merge)** — plan ready for the integration merge

- **F-QA-001 closed and independently revert-proofed** by the QA gate itself: damaged-but-openable database →
  `probe-subs: unreadable archive database at <root> (DatabaseError)`, one byte-exact line, exit 1, no
  traceback (round 1's 23 lines → 1); the neighbouring cases re-checked (61/69 behaviour checks across
  not-a-database, truncated, missing, healthy, pre-iteration schema, zero-byte) with the shipped `status`
  printing the same line apart from the prefix; the fix's scope is bounded to `(OSError, sqlite3.Error)` (a
  `TypeError` injection still escapes); solutions-only diff (+151/−0).
- **DoD 11/11** (box 8 was the partial one, now fully evidenced: the `unreadable archive database` branch is
  pinned for both commands in both damage variants, the zero-byte asymmetry is pinned, and the new doc
  paragraphs match runtime).
- **Live evidence stands** (not re-run, and the gate agreed it need not be): the added handler executes only when
  the guard raises; the healthy path is byte-for-byte the one round 1 exercised at `7e57eb6`.
- **F-QA-002** (Suggestion: the new docstring's claim about out-of-class failures was false) → corrected by
  `d742fc2` (docstring-only, +4/−2): the implementer re-measured the injection (18-line traceback, exit 1)
  before editing, the corrected text states the real behaviour, an AST comparison confirms the executable tree
  is unchanged after docstring stripping, and both suite counts are unchanged (focused 84; full 1314/4). Closure
  recorded on that evidence plus the QA gate's own statement that a comment-only change needs no re-verification.
- PM artifact note: the `qa-fix-diff.md` header (truncated scope line, missing fence) was regenerated cleanly.
