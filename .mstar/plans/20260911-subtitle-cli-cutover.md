# Subtitle CLI Cutover and Bounded Verification

> Iteration: `iter-2026-09-subtitle-transcript-sqlite`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P0 (iteration-critical, serial 3/3 and the only plan whose result the operator
  can see; every operator-visible acceptance criterion of the iteration lands here)
- Task category: backend / CLI verification
- Status: Todo
- Depends on: `20260911-subtitle-gateway`, `20260911-transcript-storage`
- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/subtitle-cli-contract.md`
- Owner: fullstack-dev
- QA gate: mandatory

## Goal

Make the existing `bili-asr` executable the operator surface for subtitle acquisition on
the SQLite archive: `probe-subs` (read-only track listing) and `harvest-subs` (bounded
acquisition into normalized transcripts), with a service layer that owns selection
preference and transactional boundaries — and with the new path reading/writing **no**
JSONL sidecar.

**What the operator gets from this plan.** This is the only plan with a surface the operator
touches, so it owns the iteration's operator-visible promises: a probe that shows what a part
exposes (and says so explicitly when nothing is visible), a bounded harvest that always
reports what happened — every outcome count including zeros, the run id, whether a credential
was in effect, and how many parts still have no transcript — and a selection rule that is
documented, deterministic, and overridable. No output of either command is ever presented as
coverage of the corpus or as a quality judgement on the captions.

## Architecture

`src/bili_asr/services/subtitle_ingest.py` defines `SubtitleIngestor`, which owns the
candidate enumeration, the selection preference, the per-part transaction, the run-record
lifecycle, and the outcome mapping; it depends on the `BilibiliGateway` protocol and
`TranscriptRepository` only. `cli.py` gains the two commands as thin composition roots
(`--archive-root` → the shipped read-path missing-database guard → `open_database` →
`require_subtitle_schema` → `TranscriptRepository` → concrete gateway → service → print),
reusing the shipped helpers `_resolve_sessdata`, `redact_sessdata`,
`page_identity.parse_work_id`, and the read commands' shipped missing-database line and
exit-`1` discipline (`<command>: no archive database at <root>; run fetch-meta to create it`).
Neither command constructs `MetadataRepository` — the read guard is reproduced without it —
and neither touches a metadata write path. No `config.py` change is needed: the subtitle
commands take their inputs from `argparse` + `BILI_SESSDATA`.

Two boundary decisions are part of this plan:

- **`probe-subs` is a read command.** It is removed from `_ARCHIVE_WRITER_COMMANDS`, so it
  takes no `coordinator/archive-writer.lock`, writes nothing, and never creates `archive.db` —
  the "read-only" promise is then structurally true, not just documented. `harvest-subs` stays
  a writer command.
- **The subtitle commands require the transcript schema.** After opening the database they call
  `require_subtitle_schema`; on a database that predates the transcript contract they print
  `harvest-subs: archive database predates the transcript schema; rebuild it (delete
  <root>/archive.db and re-run fetch-meta)` (same line with `probe-subs:` as the prefix) and
  exit `1`. The metadata commands keep working on that database unchanged.

Selection preference lives in the service and is locked in the CLI spec §3: language families
(`ai-` prefix stripped for AI tracks, then the lowercase primary subtag) ranked by the default
order `zh`, `en`, then the rest in upstream order, with CC before AI inside a family; and
`--language` matched exactly against the code `probe-subs` prints. The legacy
`subtitles._LAN_PREFERENCE` (AI first) is deliberately not reused.

The legacy manifest path and its ASR/pilot commands are untouched; the spec records that
boundary.

## Tech Stack

Python 3.12, argparse CLI, SQLite, asyncio bridge for the synchronous entrypoint, pytest,
the fake-gateway seam, optional live network.

## Global Constraints

- No parallel executable: the existing `bili-asr` entrypoint gains the (already named)
  `probe-subs` / `harvest-subs` commands; the legacy manifest semantics of those names are
  replaced, and the replacement is documented.
- The new path never reads or writes `manifest.jsonl`, `meta-cursor.json`, or
  `run-ledger.jsonl`.
- Command surface: `--bvid` accepts the archive's own part vocabulary (`bvid`, or `bvid:pN`
  for one part) and `--limit-parts N` bounds every run. A single explicit `bvid:pN` target is
  bounded by construction and needs no `--limit-parts`; in every other case the bound is
  required — no unbounded runs. `probe-subs` requires exactly one of `--bvid` / `--limit-parts`.
- Selection: without `--bvid`, the candidate set is the pending enumeration
  (`v_pending_subtitles`, never-attempted parts first); with `--bvid`, the named part(s) are
  selected explicitly, including parts that already have a transcript. That explicit path is how
  the operator refreshes a caption upstream has since added or revised — the re-acquisition then
  reports `unchanged` or appends a new version. The `cid` always comes from `video_parts`.
- Enumeration must advance across repeated bounded runs: the locked order
  (`attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`) puts a never-attempted part
  before a previously attempted one, so a bounded run cannot stall forever on the same
  captionless parts.
- Outcome mapping (product semantics): zero visible tracks or `not_found` → `no-subtitle`; an
  upstream block or a transport/shape/response failure → `failed` with its bounded scalar code;
  content matching a stored version → `unchanged`; otherwise `stored`. `no-subtitle` is never
  counted as a failure, and never as a success with empty content.
- Every run summary prints all four outcome counts including zeros, the run id, credential
  presence (never the value), and the number of parts still without a transcript; the exact
  `probe` / `harvest` / summary line shapes are fixed by the CLI spec §2 and asserted by tests.
- Exit taxonomy reuses the delivered convention: `0` bounded success/read, `1` usage/config
  (including a missing database — neither subtitle command creates `archive.db` — an unknown
  `--bvid`, a missing bound, and the schema guard), `2` bounded terminal failure with a fixed
  message. Partial per-part failure stays visible in the printed counts rather than in the exit
  code, and the docs say so.
- `SESSDATA` is presence-only in every display path; signed URLs, raw bodies, and
  credentials never reach output, logs, or rows.
- Selection preference is documented and deterministic (CC before AI for the same language
  family; `--language` overrides the order by exact `lan` match) and lives in the service, not
  the gateway. Rationale to state in the docs: AI tracks carry a different `lan` than the
  uploader track for the same language (`ai-zh` vs `zh-CN`), so the default is defined on the
  language family rather than on a fixed list of codes; the legacy harvest's AI-first order is
  replaced, and `--language` keeps the other track reachable.
- Docs (`README.md`, `docs/metadata-storage.md`) must match shipped behaviour: the two
  commands, their bounds, the exit codes, the preference rule, the SQLite-only projection
  boundary, the rebuild procedure for a pre-iteration database, and the fact that the legacy
  ASR/pilot/audio path still reads the manifest and is no longer fed `needs_audio` by
  `harvest-subs`.
- All tests offline; the live smoke stays opt-in, bounded, temporary-root only.

## Interfaces

- Consumes: the gateway's subtitle methods, `TranscriptRepository`, `require_subtitle_schema`,
  `AcquisitionRunRecord` and the storage vocabulary, and the shipped CLI helpers.
- Produces: `SubtitleIngestor` with `probe` / `harvest` and the `SubtitleSelection`,
  `SubtitleProbePart`, `ProbeResult`, `SubtitlePartOutcome`, `HarvestResult` dataclasses; the
  `probe-subs` / `harvest-subs` handlers; offline E2E evidence; and one bounded live-smoke
  result for the iteration acceptance gate.

## Tasks

### Task 1: Subtitle ingest service and CLI commands

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py`
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Test: `bilibili-asr-archive/tests/test_subtitle_cli.py`

**Interfaces:**
- Consumes: `TranscriptRepository`, `BilibiliGateway`, `MetadataIngestor`'s synchronous
  conventions, the shipped CLI helpers.
- Produces: `SubtitleIngestor` (enumeration + bounded per-part acquisition + outcome mapping +
  run lifecycle) and the two command handlers.

- [ ] Implement the service: select candidates (`list_selected_parts` for `--bvid`;
      `list_pending_subtitle_parts` otherwise), map `video_parts.cid` → gateway calls, select a
      track with the family/CC-before-AI rule (or the exact `--language` order), fetch segments,
      convert `SubtitleSegment` → `TranscriptSegmentRecord`, and write the transcript + attempt
      evidence through `record_acquired_transcript` / `record_subtitle_attempt` — one
      transaction per part; open and finish exactly one `acquisition_runs` row
      (`kind='subtitle'`, selector, bound, credential presence, derived outcome); write nothing
      at all on `probe`.
- [ ] Map outcomes exactly: empty listing or `GatewayNotFound` → `no-subtitle` (with
      `not_found` recorded when upstream signalled it); `GatewayRateLimited` /
      `GatewayTransportError` / `GatewayResponseError` / `GatewayShapeError` → `failed` with
      that code; a write with unchanged content → `unchanged`; else `stored`.
- [ ] Wire `probe-subs`: read-only, exactly one of `--bvid` / `--limit-parts`, missing database
      → the shipped read-command line and exit `1`, unknown `--bvid` (zero rows) → exit `1`,
      `bvid:pN` via `parse_work_id`, zero-track parts printed with their explicit marker, a
      part whose listing failed printed as `probe <work_id> failed <error_code>` (counted in
      `failed=`), no run/attempt/transcript write, and exit `2` only when every selected part
      failed or an internal error aborted the probe; remove `probe-subs` from
      `_ARCHIVE_WRITER_COMMANDS`.
- [ ] Wire `harvest-subs`: `--limit-parts` required unless a single `bvid:pN` is named;
      `--bvid` selects explicitly (already-stored parts included); a missing database → the
      shipped `<command>: no archive database at <root>; run fetch-meta to create it` line and
      exit `1`; `--language` parsed with empty entries rejected as usage errors; both commands
      call `require_subtitle_schema` after opening the database and print the fixed rebuild line
      with exit `1` on `SchemaContractError`.
- [ ] Print the locked output: `sessdata: <present|absent>`, one `probe`/`harvest` line per
      selected or attempted part in order (including `probe <work_id> tracks=0` with its
      explicit marker and `probe <work_id> failed <error_code>`), and the summary lines
      (`probe-subs: probed=… with_tracks=… without_tracks=… failed=…`,
      `harvest-subs: run_id=… attempted=… stored=… unchanged=… no-subtitle=… failed=… remaining_without_transcript=…`).
- [ ] Remove the legacy manifest reads/writes from these two commands only; leave every
      other command's behaviour untouched and disclose the semantic replacement in the report.
- [ ] Tests: parser/usage (bound required, exactly one probe selector, missing DB → exit `1`,
      unknown `--bvid` → exit `1`, empty `--language` entry → exit `1`, usage errors never exit
      `2`), preference selection (CC-before-AI property table, family ranking, exact
      `--language` match, unmatched valid preference → `no-subtitle`), explicit `--bvid`
      selection including an already-stored part, enumeration progress across two runs, summary
      content and line shapes, outcome mapping, exit codes, and no-old-file assertions.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_subtitle_cli.py -v`

### Task 2: Offline subtitle E2E over the fake seam

**Files:**
- Create: `bilibili-asr-archive/tests/test_subtitle_e2e.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` — scripting only, **plus**
  the deferred Task-1 finding F3: add the two subtitle methods to the shared `FakeGateway`
  protocol double (absent today) so this plan can script subtitle calls through it
- Modify: `bilibili-asr-archive/tests/test_subtitle_cli.py`

**Interfaces:**
- Consumes: the Task-1 CLI/service, the storage plan's repository, the fake seam.
- Produces: deterministic E2E evidence for the iteration acceptance gate.

- [ ] Script a part with a CC track and a part with only an AI track; assert normalized
      `transcripts`/`transcript_segments` rows, language, `source_kind`, version 1, the content
      hash, and the acquisition-run/attempt evidence.
- [ ] Re-run the same bounded harvest and assert `unchanged`, no new version, and no duplicate
      segments; then change the scripted body and assert version 2 with version 1 and its
      segments still readable.
- [ ] Script a part with no subtitles and a part whose body fetch fails; assert bounded evidence
      rows (`no-subtitle`, and `failed` with the mapped code), that the run does not claim
      success for them, and that the printed counts make the partial failure visible while the
      exit code stays `0`.
- [ ] Assert honesty and progress: a part left `no-subtitle` in one run can store a transcript
      in a later run once the caption is available; with both a never-attempted and a previously
      attempted part in the candidate set, the never-attempted part is attempted first.
- [ ] Assert the printed run summary: all four outcome counts including zeros, the run id,
      credential presence, and the remaining count of parts without a transcript; assert the
      `attempted=0` empty-selection run exits `0`.
- [ ] Assert the probe surface: the `probe`/`track`/`tracks=0` line shapes, the per-part
      `failed <code>` line, the `probe-subs: probed=… with_tracks=… without_tracks=… failed=…`
      summary, and that a probe leaves no database, no run row, and no file behind.
- [ ] Assert no legacy sidecar file appears in the temporary archive root, that `probe-subs`
      leaves no new file (including no writer lock) and does not create a missing database, and
      run no-leak scans over output and all persisted rows (credential + signed-URL sentinels).

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_subtitle_e2e.py -v`

**PM-authorized follow-up (2026-09-11, from the Task-1 L2 review M3):** the env-sourced credential path for
these commands lost its direct assertion when the legacy tests were replaced (only the shared helper in
`test_metadata_cli.py` covers it). Add the assertion here — an E2E case where `BILI_SESSDATA` is present in the
environment (and one where it is absent) must exercise the composition of `credential_present` into the run row
and the printed `sessdata: <present|absent>` line.

**PM-authorized follow-up (2026-09-11, from the Task-2 L2 review):** `ProbeResult.credential_present` is
asserted nowhere — add the assertion to the probe's coverage here (the probe prints the line, so the value must
be pinned too), and while live, record the probe's `sessdata=present|absent` alongside `part_source`.

### Task 3: Bounded live smoke and operator documentation

**Files:**
- Modify: `bilibili-asr-archive/tests/test_live_metadata_smoke.py` (or a sibling opt-in test)
- Modify: `bilibili-asr-archive/docs/metadata-storage.md`
- Modify: `bilibili-asr-archive/README.md`

**Interfaces:**
- Consumes: the delivered CLI + gateway + storage, the operator's credential/proxy env.
- Produces: one bounded live subtitle-acquisition result and operator instructions that
  match reality.

- [ ] Add the opt-in live smoke: temporary archive root, bounded `--limit-parts`, credential
      and proxy from the documented environment; skip by default; loud-fail when opted in
      without the pinned distribution. Reuse the metadata smoke's bounded structure.
- [ ] Run it once and record the outcome (parts attempted, tracks found, transcripts stored,
      or the explicit bounded blocker, including the code when the endpoint refuses the locked
      call shape). Never print URLs, bodies, or credentials.
- [ ] Document in `docs/metadata-storage.md` + README: the subtitle path on SQLite, the two
      commands with their bounds, exit codes and output shapes, the preference rule and why it
      is defined on the language family, the credential handling, the schema guard and rebuild
      procedure (delete `archive.db`, re-run `fetch-meta`), the two schema resources, the fact
      that the legacy ASR/pilot path still reads the manifest, and that `harvest-subs` no longer
      writes the manifest status `needs_audio`.
- [ ] **PM-authorized documentation follow-ups (2026-09-11, from the Task-1 L2 review):**
  - **M1** — document the deliberate asymmetry: a part whose *listing* answers `not_found` is printed by
    `probe-subs` as `probe <work_id> failed <error_code>` (and can make an all-failed probe exit 2), while
    `harvest-subs` records the same part as `no-subtitle` and exits 0 with the counts. State both readings so
    an operator is not surprised.
  - **⚠️2** — the spec's "writes no file except its database" must be read against the shipped writer lock
    that `harvest-subs` takes as an archive-writer command; document the lock (what it is, where it lives, and
    that `probe-subs` deliberately takes none).
  - **⚠️6** — state that after the cutover the ASR/pilot chain is driven from the manifest state, so
    `download-audio --missing-subs` gains nothing from the SQLite subtitle path (the two paths do not feed
    each other yet).

Run: `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -s -v`

## STOP Conditions

- The cutover cannot avoid touching the manifest for ASR/pilot commands → stop; record the
  boundary and reduce scope rather than silently creating a second state machine.
- A bounded harvest cannot be expressed without unbounded retries or loops → stop and
  update the spec.
- Any output or row contains a signed URL, raw JSON body, cookie, or traceback → stop.
- The new path requires a second executable or a second metadata source of truth → stop.
- `probe-subs` cannot be made genuinely read-only (it needs a write to work) → stop and
  escalate the contract gap instead of quietly keeping it in the writer set.

## Durable Roadmap and Dependencies

- Consumed by iteration acceptance (bounded live evidence) and by the next iteration
  (audio/ASR), which reuses the same run-record shape, repository conventions, and CLI output
  discipline.
- Deferred: retiring `bili_client`'s subtitle methods and migrating the ASR/pilot path —
  owner `project-manager`; trigger: the audio/ASR iteration (it already owns the audio/playurl path);
  done when no shipped command reaches `bili_client`'s subtitle methods and the manifest path no longer
  carries subtitle state (QC3-06, closed 2026-09-11).
- Deferred with a named owner (`project-manager`, trigger "this iteration delivered"):
  rebuilding SRT/TXT/MD projections from SQLite transcripts, enumerating the audio work queue
  from SQLite (including the parts recorded `no-subtitle`, which are its work queue), and
  promoting the iteration's storage/transport contract out of the iteration package. No file is
  written into `{SPECS_DIR}` during Prepare. Consequences the operator sees today and the docs
  must state: the new `harvest-subs` writes no `subtitles/raw/*.json` and no
  `transcripts/srt/*.srt`, and it no longer produces the manifest status `needs_audio`, so
  `download-audio --missing-subs` gains no new entries from the SQLite path.

- Carried from plan `20260911-transcript-storage` (plan QC seat 1, QC1-003) — the service must not guess:
  - **Argument validation**: validate `source_kind` against `storage.models.ALLOWED_CAPTION_SOURCE_KINDS`
    (and `kind` against the acquisition-kind enum) instead of passing literals through.
  - **Guard scope**: `SchemaContractError` is raised by `require_subtitle_schema` when `transcripts`
    lacks `language`/`content_sha256`; its message omits the `<command>:` prefix and `{archive_root}` path, so
    **the CLI composes the printed line** (do not print `str(exc)` alone).
  - **Two row shapes**: `list_pending_subtitle_parts` returns a 12-column work item incl. `bvid`/`cid`, while
    `list_selected_parts` returns the 11 `v_video_parts` columns **without** `bvid` — the service normalizes
    both into one work-item shape before calling the gateway.
- Carried from plan `20260911-subtitle-gateway` (residual R1 + Task-1 finding F3): the `FakeGateway` protocol
  double needs the two subtitle methods, and R1 (whole-`user`-module import) is retargeted to *the next plan
  whose file list includes `src/bili_asr/sources/bilibili_api_gateway.py`* — this plan does not, so R1 stays
  open past it.

- Carried from plan `20260911-transcript-storage` (plan QC seat 3 readiness items):
  - **QC3-002** — `TranscriptRepository` validates its connection in `__init__` but does **not** call
    `require_subtitle_schema`; a caller that skips the guard gets a raw `OperationalError`
    (`no such table: acquisition_runs` / `no such column: language`). This plan's service must guard first
    (and fix wave 2 additionally makes `__init__` fail fast with the bounded error).
  - **QC3-003** — `docs/metadata-storage.md:51-56` ("no … transcripts are written yet") becomes false as soon
    as this plan's storage work lands; this plan's file list owns that doc, so its Task 3 docs bullet must
    update the sentence, not just add new ones.
  - **QC3-005** — `SchemaContractError`'s message cannot carry the archive root (it only has a connection),
    while the promised operator line has `<command>: …` plus the root: the Task 1 test list must assert the
    printed line carries **both**, so `print(f"{command}: {exc}")` cannot pass a substring check.

- Recorded (nits from the Task-1 L2 review, no rework proposed):
  - **M2** — (owner `project-manager`; trigger: the next plan that owns the run lifecycle)
    `finish_acquisition_run` sits outside the interrupted-run guard, the one narrow path that can
    leave a run row `running` on an abrupt terminate; it mirrors the shipped metadata run discipline, so the
    next owner of the run lifecycle decides whether to close it.
  - **M4** — `test_subtitle_cli.py` imports a private helper from `test_storage_schema`; harmless today, worth
    promoting to a shared test fixture if a third consumer appears.

- Recorded (follow-up decision, Task-2 review disclosure 1): the offline E2E exercises the **protocol double**
  (F3's wording) and the package-level seam stays covered by `test_bilibili_api_gateway.py`'s subtitle routes
  plus this plan's live smoke. A package-seam subtitle E2E would be a larger, separate task — decide it in a
  future plan rather than reopening Task 2.
- Recorded (nits, Task-2 review): the report's note that the metadata clock fixture shares the subtitle
  path's clock limitation is **wrong** (the metadata ingestor calls the module-global `_now()` directly, so its
  fixture is effective; only the subtitle path binds `_now` as a default argument). `_archive_files` is blind to
  empty directories (matches the spec's "no file" wording). M3's probe-absent branch lives in the probe test.

- Recorded (**QC2-005**; owner `project-manager`; trigger: the next plan that owns the transcript schema —
  expected the audio/ASR iteration, which will add its own run rows): the acquisition run row does not persist the
  `--language` preference, so a preference-scoped `no-subtitle` outcome is indistinguishable from a generic
  one after the fact. Persisting it would be a schema column decision (a storage owner's), not a CLI change.

- Recorded (nits, seat-1 fix-wave revalidation; owner `project-manager`; trigger: the next plan that
  touches `cli.py`'s archive-opening paths):
  - the two `<command>: unreadable archive database at …` branches the fix wave introduced have neither a
    test nor a doc sentence (the exit code stays 1); the QA gate exercises them at runtime, and a future
    plan adds the pinned cases.
  - the `unknown --bvid` guard echoes the operator's raw selector, so a control-character value injects a
    second stderr line (the spec pins `<value>` and the sibling guard has always echoed it; stderr is not
    the locked machine surface) — accepted as-is, sanitise only if stderr ever becomes machine-read.

## Drift Check

Before implementing, inspect the current `harvest-subs`/`probe-subs` handlers, `subtitles.py`
selection rules, `_ARCHIVE_WRITER_COMMANDS`, and the CLI's exit-code conventions; confirm no
other command depends on the handlers being changed, and that no other module imports
`subtitles.pick_subtitle` in a way that must stay aligned with the new default.

## Acceptance / Done Criteria

- [x] `harvest-subs` requires a bound (or an explicit single `bvid:pN`) and stores normalized
      transcripts — or bounded evidence for parts without subtitles — with idempotent re-runs and
      immutable versions.
- [x] `probe-subs` prints track metadata only, prints zero-track parts explicitly, writes
      nothing, and never creates the database.
- [x] The run summary always prints all four outcome counts including zeros, the run id,
      credential presence, and how many parts still lack a transcript; no output claims corpus or
      caption coverage.
- [x] The selection rule is documented, deterministic, and overridable with `--language`; the
      stored source kind, language, and version are reported per part.
- [x] Repeated bounded runs make progress, and an explicitly targeted stored part can be
      re-acquired (`unchanged`, or a new version when the caption changed).
- [x] A database that predates the transcript schema makes both commands exit `1` with the
      fixed rebuild line while the metadata commands keep working.
- [x] No legacy sidecar is read or written by either command, and neither command writes
      `subtitles/raw/` or `transcripts/srt/`.
- [x] Exit taxonomy and bounded codes are pinned by tests; docs match behaviour.
- [x] Offline suites green (baseline for this plan: the storage plan's post-merge count).
- [x] Bounded live smoke recorded (real transcripts, or an explicit bounded blocker).
- [x] `git diff --check` clean.

## Prepare → Execute Handoff

Execute Task 1 → Task 2 → Task 3 (serial). Then SDD review package, QC tri, QA gate, merge.

## Review Gate Summary

- Decision: **Approve** (plan QC tri N=3 → seat 1 Request Changes on one Warning, seats 2/3 Approve; a merged
  fix wave closed the Warning plus eleven Suggestions, and the N=3 targeted re-review returned Approve from all
  three seats with no open item — Q3-06 was closed by the PM after seat 3 flagged it as the last open item)
- Review range / Diff basis: `c5a9b82..d742fc2` (6 commits: `8ec992b` service + CLI cutover, `c501d9a` offline
  E2E + F3 + M3, `d5c0f9e` live smoke, `8373817` docs, `7e57eb6` QC fix wave, `0e0ea81` QA fix, `d742fc2`
  docstring correction)
- Review bundle: `.mstar/sdd/20260911-subtitle-cli-cutover/review/` (`qc-consolidated.md` carries the gate)
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md` (each with `## Revalidation`)
- Blocking result: none at the final gate — 0 Critical / 0 Warning / 0 open Suggestion
- Residual findings: **none registered by this plan**; `R1` (plan 1, `low`, `defer`) stays open and correctly
  retargeted (this branch touches no `sources/bilibili_api_gateway.py` import surface)
- QA gate: **Approve** after one round of **Needs fixes** (`review/qa-gate.md` + its `## Re-verification`):
  round 1 reproduced `1311 passed, 4 skipped` and re-took the bounded live smoke successfully (a fresh
  `run_id`, all other fields identical: `part_source=fixed-sample`, `sessdata=present`, `tracks=ai-zh:ai`,
  `stored=1 source_kind=subtitle-ai language=ai-zh version=1 segments=2913 pending_after=0`), found **F-QA-001**
  (a damaged-but-openable database escaped as a 23-line raw traceback); the narrow fix `0e0ea81` bounded it to
  the byte-exact `unreadable archive database at <root> (DatabaseError)` line and the re-verification returned
  **Approve with DoD 11/11** (the branch now pins the unreadable branch for both commands in both damage
  variants and the zero-byte asymmetry). `F-QA-002` (a false docstring claim) was corrected by `d742fc2`
  (docstring-only; AST-verified no executable change; suite counts unchanged)
- Merged into the iteration branch as `d1a0b7e` (2026-09-11)

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: **Approve (recommend merge)** — round-2 re-verification of the `F-QA-001` fix wave (qa-engineer,
  2026-09-11; report `.mstar/sdd/20260911-subtitle-cli-cutover/review/qa-gate.md` → `## Re-verification`).
  Round 1 returned **Needs fixes** on `F-QA-001`; `0e0ea81 fix(subs): bound the probe's damaged-database answer`
  (`+151/−0`, 3 files, additions only) is **verified closed** at checkout `feature/20260911-subtitle-cli-cutover`
  HEAD `0e0ea81` (= round-1 HEAD `7e57eb6` + the fix wave) / integration base `c5a9b82`, tree clean, HEAD
  unmoved. `review/qa-fix-diff.md`'s fenced body is **byte-identical** to the live `7e57eb6..0e0ea81` diff
  (9697 bytes, 195 lines, all 3 files; `git diff --check` clean) — its only flaw is the artifact's own truncated
  `Scope:` header line, whose opening fence was lost (content complete; artifact hygiene only). Runtime
  re-reproduction on a freshly built damaged-but-openable database (intact header, corrupted page 1, asserted
  `SQLite format 3`): **both** commands now print the byte-exact
  `<command>: unreadable archive database at <root> (DatabaseError)` line on stderr, stdout empty, exit 1 — one
  line instead of round 1's 23-line traceback, no SQLite internals, file not repaired (probe root holds
  `archive.db` only; harvest adds only the writer lock), and **identical to what shipped `status`/`runs` print
  for the same file** (parity promise verified, not assumed). Neighbouring states unregressed and byte-exact
  (not-a-database, truncated, missing, healthy, pre-iteration schema, zero-byte asymmetry; exits 0/1 unchanged;
  69/69 behaviour checks over the real CLI, offline, network canary set). **Revert-proof run independently**
  against a copy of the package whose `cli.py` is `7e57eb6`'s (diff-verified to differ only by the fix hunk):
  the new `damaged-page-1` case **fails pre-fix** at `require_subtitle_schema` → `_transcripts_columns`
  (`database.py:116`) with `sqlite3.DatabaseError: database disk image is malformed` (83 passed / 1 failed), and
  passes post-fix (84 passed) — the wave's only behavioural delta in that module. Scope: the sole source change
  is that bounded handler + its docstring paragraph; it catches only `(OSError, sqlite3.Error)` (a `TypeError`
  from the guard still escapes — probed by injection), no `except Exception`, the exit taxonomy and every locked
  output shape are untouched, and the two doc paragraphs match observed behaviour. Fresh offline suite at the
  new HEAD: **1314 passed, 4 skipped**, exit 0 (round-1 1311 + the 3 new pinned cases; skips are still exactly
  the 4 opt-in live gates). **One Suggestion, non-blocking — `F-QA-002`:** the new docstring sentence "anything
  outside that class escapes as the unexpected internal error the command handlers report" is false at runtime
  (the guard is called before the command handlers' `try`, and `main` catches nothing broad, so such an
  exception prints a raw traceback and exits 1); unreachable without a Python-level bug, no behaviour change,
  no DoD box falsified — one-line correction recorded in the report for the merge commit or a durable note.
  **Bounded live smoke not re-taken** and not needed: the added handler runs only when the schema guard raises,
  the healthy path is byte-for-byte the one round 1 exercised, and the fix has no credential/live dependency —
  round 1's re-take at `7e57eb6` (one invocation, exit 0, 21 passed, `stored=1 segments=2913
  sessdata=present`) **stands** for the unchanged live path; A1–A12 untouched. Round-1 detail, reused where
  the fix cannot reach it: checkout `feature/20260911-subtitle-cli-cutover` HEAD `7e57eb6` / base `c5a9b82`,
  tree clean; `review/branch-diff.md` + `review/qc-fix-diff.md` are
  byte-identical to the live `c5a9b82..8373817` and `8373817..7e57eb6` diffs and their union is exactly the
  live 16-file full-range diff. Fresh offline suite at HEAD from the worktree package dir: **1311 passed,
  4 skipped** (exit 0; the 4 skips are exactly the opt-in live gates; plan-2 baseline 1202/3 + 109 tests) with
  the AST import-boundary scans (4 passed) and the no-leak scans green. Bounded live smoke **re-taken**
  (one invocation, exit 0, 21 passed): `part_source=fixed-sample work_id=BV1S8hA6MEvy:p0 sessdata=present
  probe_exit=0 probed=1 with_tracks=1 track_count=1 tracks=ai-zh:ai harvest_exit=0
  run_id=f483460e60ea45dea71a2b41a9e284de attempted=1 stored=1 unchanged=0 no_subtitle=0 failed=0
  remaining_without_transcript=0 source_kind=subtitle-ai language=ai-zh version=1 segments=2913 transcripts=1
  attempts=1 pending_after=0`; run log carries no credential/URL sentinel (three-invocation deviation kept as
  recorded, not normalized). F-001 re-verified at runtime (`probe-subs`/`harvest-subs` × `--bvid ""` /
  whitespace / `\x01` → the byte-exact `unknown --bvid` line + exit 1, no rows, nothing created); the
  pre-iteration-database case exits 1 with the composed rebuild line for both commands while `status` still
  exits 0; the missing-database guard leaves a probe-only root empty. DoD was **10/11 boxes** at round 1, with
  box 8 partial **solely** because of `F-QA-001`; box 8 is now **fully evidenced** (the `unreadable archive
  database` branch is pinned for both commands in both damage variants — the `damaged-page-1` pin is
  revert-proofed — plus the zero-byte asymmetry, and the two new doc paragraphs match observed runtime
  behaviour) → **DoD 11/11 boxes fully evidenced** at `0e0ea81`. Residual register correct: only plan 1's `R1`
  (`low`, `defer`) is open, target unchanged, this plan holds none, and the plan may proceed to Done with `R1`
  open. A1–A12 re-confirmed at `7e57eb6`, none falsified, and this wave touches no A1–A12 surface.
  **`F-QA-001` closed** (round-1 Warning: the new `mode=ro` path let `require_subtitle_schema` fail outside its
  bounded handler, so `probe-subs` printed a 23-line raw SQLite traceback instead of the bounded line its own
  docstring promised — now one byte-exact line + exit 1 on both commands, with the pinned regression case the
  branch lacked). Verdict: **Approve (recommend merge)**; no blocking item remains, `F-QA-002` is a
  non-blocking comment-accuracy Suggestion with a recorded one-line correction. Plan not marked Done (the merge
  precedes Done; PM owns the merge and the boxes).

## Sign-off

- Product intent: reviewed (product-manager, 2026-09-11)
- Architecture: reviewed (architect, 2026-09-11)
- Writing/corpus hygiene: reviewed (writing-specialist, 2026-09-11)
- PM lock: pending
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every CLI requirement maps to a task and an offline assertion, including the exact output
   shapes and exit codes.
2. The service owns selection/transaction boundaries; the CLI stays a composition root.
3. The manifest boundary is explicit, not silent.
4. The live smoke is bounded and has an honest blocker path, including a refused call shape.
5. No audio/ASR or export scope leaks into this plan.
6. What the operator sees — probe lines, outcome counts, credential presence, remaining
   parts without a transcript, the stored source kind/language/version — matches what the
   iteration promises, and no output reads as coverage or as caption quality.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/subtitle-cli-contract.md`
- Tests: `tests/test_subtitle_cli.py`, `tests/test_subtitle_e2e.py`, `tests/test_live_metadata_smoke.py`
- SDD runtime: `.mstar/sdd/20260911-subtitle-cli-cutover/`

## Status Transition

Starts `Todo`; `InProgress` after the Phase 2 lease; `InReview` after implementation;
`Done` only after QC + the mandatory QA gate and the integration merge.

## End

The CLI is a thin composition root; the gateway and transcript repository carry the contract.
