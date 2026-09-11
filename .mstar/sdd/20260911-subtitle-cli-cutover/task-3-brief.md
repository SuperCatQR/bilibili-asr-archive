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
- Deferred: retiring `bili_client`'s subtitle methods and migrating the ASR/pilot path.
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
  - **M2** — `finish_acquisition_run` sits outside the interrupted-run guard, the one narrow path that can
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

## Drift Check

Before implementing, inspect the current `harvest-subs`/`probe-subs` handlers, `subtitles.py`
selection rules, `_ARCHIVE_WRITER_COMMANDS`, and the CLI's exit-code conventions; confirm no
other command depends on the handlers being changed, and that no other module imports
`subtitles.pick_subtitle` in a way that must stay aligned with the new default.

## Acceptance / Done Criteria

- [ ] `harvest-subs` requires a bound (or an explicit single `bvid:pN`) and stores normalized
      transcripts — or bounded evidence for parts without subtitles — with idempotent re-runs and
      immutable versions.
- [ ] `probe-subs` prints track metadata only, prints zero-track parts explicitly, writes
      nothing, and never creates the database.
- [ ] The run summary always prints all four outcome counts including zeros, the run id,
      credential presence, and how many parts still lack a transcript; no output claims corpus or
      caption coverage.
- [ ] The selection rule is documented, deterministic, and overridable with `--language`; the
      stored source kind, language, and version are reported per part.
- [ ] Repeated bounded runs make progress, and an explicitly targeted stored part can be
      re-acquired (`unchanged`, or a new version when the caption changed).
- [ ] A database that predates the transcript schema makes both commands exit `1` with the
      fixed rebuild line while the metadata commands keep working.
- [ ] No legacy sidecar is read or written by either command, and neither command writes
      `subtitles/raw/` or `transcripts/srt/`.
- [ ] Exit taxonomy and bounded codes are pinned by tests; docs match behaviour.
- [ ] Offline suites green (baseline for this plan: the storage plan's post-merge count).
- [ ] Bounded live smoke recorded (real transcripts, or an explicit bounded blocker).
- [ ] `git diff --check` clean.

## Prepare → Execute Handoff

Execute Task 1 → Task 2 → Task 3 (serial). Then SDD review package, QC tri, QA gate, merge.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260911-subtitle-cli-cutover/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`
- Blocking result: pending
- Residual findings: pending

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: pending

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
