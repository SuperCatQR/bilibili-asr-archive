---
plan_id: 20260919-sqlite-queue-bridge
iteration: iter-2026-09-queue-bridge
iteration_compass: .mstar/iterations/iter-2026-09-queue-bridge/delivery-compass.md
iteration_refs:
  - .mstar/iterations/iter-2026-09-queue-bridge/specs/sqlite-queue-bridge-contract.md
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
---

# Derive the ASR/audio work queue from `archive.db` (`bili-asr derive-manifest`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one command, `bili-asr derive-manifest --archive-root <archive-root>`, that reads the work queue the
store already records (`archive.db`: every part with no transcript and not `gone`) and appends the manifest rows
the unchanged ASR/audio chain needs (`status: needs_audio`, page-qualified `work_id`, seconds duration), so a
corpus run no longer needs a hand-built `manifest/manifest.jsonl`.

**Closes:** **nothing.** This plan discharges the **queue half** of register row
`e2e-23191782-season-7686105 · R1` (medium); the row stays open for the SRT/TXT/MD projection rebuild, and the
PM records the partial discharge at iteration close (compass Acceptance Criterion 5). The rotation loss the
first slice cannot avoid is stated in the spec §5 decision 4 and is **the PM's residual to register**.

**Architecture:** The bridge is a one-way derivation SQLite → manifest, composed in `cli.py` like every other
command (cross-layer rule: only `cli.py` composes layers). It reads the store through a `mode=ro` connection
(the write direction is structurally impossible), computes rows with a pure service function, and appends them
through `ManifestStore.upsert`. It is **additive**: a `work_id` the chain already holds is never rewritten, so
an archived row cannot be re-queued and a live `subtitle_done` row cannot be clobbered. Derived rows are
**only** `needs_audio`, because every part in the queue is captionless by construction — which is exactly why
the archive stage's filesystem trap (`missing_subtitle_raw`) cannot fire for a derived row. The chain
(`coordinator.py`, `audio.py`, `asr.py`) is not touched. Full contract, with every claim's file:line:
`.mstar/iterations/iter-2026-09-queue-bridge/specs/sqlite-queue-bridge-contract.md` (cited below as **spec §N**).

**Tech Stack:** Python 3.12, stdlib `sqlite3`, pytest 9 (`bilibili-asr-archive/.venv/bin/python`), the repo's own
`ManifestStore` / `TranscriptRepository` / `page_identity` modules. No new dependency.

**Execution:** mstar-sdd

**Main worktree branch**: `main` (the control root stays on `main`; the plan's feature work happens on
`fix/20260919-sqlite-queue-bridge` in the worktree named in Global Constraints).

## Global Constraints

- **Two roots, and every command names its working directory.** The **repository root** is
  `/root/workspace/bilibili-asr-archive` (holds `.git`, `.mstar/`, `.worktrees/`, and the package directory
  `bilibili-asr-archive/`); the **package root** is `<repo-root>/bilibili-asr-archive` (holds `.venv/`, `src/`,
  `tests/`). Python and pytest always run from a **package root**.
- **Where the code under test lives (this plan runs in a linked worktree).** Phase 2 executes on
  `fix/20260919-sqlite-queue-bridge` in the worktree `/root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge`
  (created by the PM per `mstar-branch-worktree`; path shape matches the two existing worktrees). That
  worktree has **no `.venv`** (gitignored, so `git worktree add` does not carry it) and the control root's venv
  is an *editable* install whose `.pth` points `bili_asr` at the **control root** `src` — so an unpinned run
  silently grades the unmodified tree. Every task therefore runs exactly:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v
  ```

  and before trusting any result confirms the tree:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -c \
       "import bili_asr, pathlib; print(pathlib.Path(bili_asr.__file__).resolve())"
  ```

  The printed path must be under the worktree. A report that records only "N passed", without the pinned
  `PYTHONPATH` and the resolved `bili_asr.__file__`, has not recorded which code it tested
  (`.mstar/knowledge/testing-patterns/worktree-test-invocation.md`; both forms verified runnable on this host
  on 2026-09-19). Verification gates inside a task run from the package root of that worktree.
- **D9 (product-locked, do not re-open):** the literal invocation is
  `bili-asr derive-manifest --archive-root <archive-root>`; exit `0` includes "nothing to derive"; exit `1`
  only for usage/config (missing/unreadable `archive.db`, the schema-rebuild line, `archive_busy`); **no new
  exit-code value** in the frozen `0/1/2` taxonomy (`{SPECS_DIR}/asr-archive-cli.md:97-101`). The command takes
  no selector and no `--limit` (spec §2, §8).
- **D2 / D4 (user-locked, do not re-open):** a new command that derives rows; the ASR/audio chain's code is
  **unchanged** — `coordinator.py`, `audio.py`, `asr.py` gain no storage import and no behaviour change. No
  migration, no importer, no compatibility reader, no live-database schema widening (`CREATE TABLE/VIEW IF NOT
  EXISTS` cannot widen or replace; `schema-transcripts.sql:4-10`, `:106`).
- **D8 (product-locked):** the bridge writes recorded store facts and the one state they entail
  (`needs_audio`); it never writes a state that asserts an artifact (`subtitle_done`, `audio_ok`, `asr_done`,
  `archived`, `gone`), never copies manifest state back into the store, and never overrules a chain-held row.
  Restated next to the contract at spec §10, because a reviewer will otherwise read
  `.mstar/knowledge/architecture-patterns/operational-sidecars.md:234-236` ("None of these projections may
  back-write an inferred truth into the manifest") against this bridge.
- **Single entrypoint, cross-layer composition, single-writer lock.** One executable, `bili-asr`
  (`__main__.py`/console script); only `cli.py` composes layers
  (`{SPECS_DIR}/asr-archive-cli.md:61`). `derive-manifest` joins `_ARCHIVE_WRITER_COMMANDS`
  (`cli.py:3075-3085`), so `main()` takes `coordinator/archive-writer.lock` before dispatch
  (`cli.py:3134-3142`) — no new lock code, and a busy archive exits `1` with `derive-manifest: archive_busy`.
- **`upsert` semantics are the identity contract:** a new automatic row must carry a page-qualified `work_id`
  whose bvid parses back to the row's `bvid` (`manifest.py:266-272`, `:281-290`); `needs_audio` is in
  `VALID_STATUSES` (`manifest.py:24-36`).
- **Verification scope** (`mstar-harness-core` § 定向执行与验证边界): only the changed behaviour and its direct
  contracts. **No local full-suite run** — the four suites named in the tasks are the whole local evidence
  budget; the full suite is CI's. Reuse unaffected evidence with its original range; do not re-run checks
  because HEAD moved. Never assign real-browser/device/installed-deployment E2E evidence as a task or a gate of
  this plan (two cases in `tests/test_cli_help.py` — `test_installed_*` — error in this sandbox because
  `/root/.cache/uv` is read-only; they are **not** part of any gate here).
- **Do not edit:** `{KNOWLEDGE_DIR}/**` (Phase 1/2 never add knowledge), `{SPECS_DIR}/asr-archive-cli.md`
  (frozen; the revision it owes is named in spec §7/§11 and is the PM's, Q6), `{HARNESS_DIR}/workflows/**`,
  `status.json`, the register, any other plan or compass. Documentation edits are limited to Task 4's two files.
- **Drift check before Task 1** (plan written at `cf3f779`):
  `git -C /root/workspace/bilibili-asr-archive diff --stat cf3f779..HEAD -- bilibili-asr-archive/src/bili_asr/cli.py bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/src/bili_asr/storage/database.py bilibili-asr-archive/src/bili_asr/coordinator.py bilibili-asr-archive/README.md`.
  If any in-scope file changed, re-read the current-state excerpts below before proceeding; on a mismatch,
  STOP and report.

## Engine lifecycle

Who advances this plan row's engine state, and what records each transition:

- **Scoped sequence** — one engine verb per transition; never a hand-edited snapshot: `bind --coordinator` →
  `prepare` → `bind` → `progress` → `handoff` → `accept` → `integration-start` → Git merge →
  `integration-accept` → `complete`.
- **Evidence order** — `compound` disposition, PR identity and merge evidence are recorded **after** the row is
  `Done`; the engine refuses those writes while any plan row is not `Done`. The delivery tail runs on a completed
  row, never ahead of it. This plan's row is the iteration's only row, and the iteration closes once (compass
  `## Milestones`).
- **Snapshot declares integration anchors** (`branch.base = main`, `branch.integration =
  iteration/iter-2026-09-queue-bridge`, `branch.target = main`): the row can reach `Done` through the sequence
  above. The merge into the integration branch is `integration-start` → Git merge → `integration-accept`.

Semantics and failure behaviour → `mstar-artifacts/references/plan-workflow-lifecycle-contract.md`; PM step
sequence → `mstar-roles/references/project-manager/plan-management.md`.

---

### Task 1: The pure derivation — row mapping, duration conversion, additive conflict policy

**Effort (agent-oriented):** S

**Split point:** If the module cannot close its Files and gates in one round, split at the conflict-policy
boundary: (1) `duration_s_from_ms` + `row_for_part` (the mapping of spec §3.1/§3.2) and their cases, then
(2) `derive_rows` (the three-way policy of spec §3.4/§3.6) and its cases. The `DerivationOutcome` type stays
with slice (2); slice (1) exports `row_for_part` unchanged, so nothing is re-derived at the split.

**Files:**
- Create: `src/bili_asr/services/manifest_derivation.py`
- Create: `tests/test_manifest_derivation.py`
- Out of scope: `cli.py`, `storage/**`, `manifest.py`, and every chain module — this task imports none of them
  writing-side. `services/` may import stdlib + `bili_asr.page_identity` only (its precedent imports storage;
  this module needs no storage, and must not import `manifest.py` — `cli.py` composes the write, spec §8).

**Interfaces:**
- Consumes: nothing from an earlier task. Inputs are plain mappings, so the module is testable without a
  database: `parts` are the queue rows of spec §2 converted with `dict(row)` by the caller (keys:
  `video_part_id`, `work_id`, `bvid`, `page_index`, `cid`, `part_title`, `duration_ms`, plus the relation's attempt-evidence columns), `existing` is
  `ManifestStore.load()`'s mapping.
- Produces (verbatim, for Task 2 and the tests):

  ```python
  QUEUE_STATUS = "needs_audio"
  SKIP_ALREADY_DERIVED = "already_derived"
  SKIP_CHAIN_OWNED = "chain_owned"
  SKIP_IDENTITY_MISMATCH = "identity_mismatch"

  def duration_s_from_ms(duration_ms: Any) -> int: ...
  def row_for_part(part: Mapping[str, Any], pubdate: int) -> dict[str, Any]: ...
  def derive_rows(
      parts: Sequence[Mapping[str, Any]],
      pubdates: Mapping[str, int],
      existing: Mapping[str, Mapping[str, Any]],
  ) -> DerivationOutcome: ...

  @dataclass(frozen=True)
  class DerivationOutcome:
      appended: tuple[dict[str, Any], ...]        # rows to append, in the order given
      already_derived: tuple[str, ...]
      chain_owned: tuple[str, ...]
      identity_mismatch: tuple[str, ...]
  ```

  `row_for_part` writes exactly the nine fields of spec §3.1 and no others; `derive_rows` looks `pubdate` up by
  `part["bvid"]` — the `videos` foreign key (`schema.sql:33`, `PRAGMA foreign_keys = ON` at `schema.sql:1`)
  makes the lookup total, and a miss is a corrupt store, so it is a `KeyError` and never swallowed.

**Current state to read before writing** (the policy's two anchors):

- `manifest.py:150-176` — `load()`/`_read_latest()`: last write wins per key, and a row without `work_id` is
  keyed by its `bvid` (`manifest.py:55-62`). That is the "effective row" spec §3.4 means.
- `page_identity.py:19-27` — `format_work_id` is the Python identity SSOT; `manifest.py:266-272` re-validates
  the same form on write.

- [ ] **Step 1: Write the failing unit tests** in `tests/test_manifest_derivation.py`, using plain dicts (no
      database, no CLI):

  ```python
  # exact cases to pin — names are the selectors the task later runs
  # test_duration_s_is_floor_seconds_clamped_to_one          3600_500 -> 3600; 999 -> 1; 1000 -> 1000
  # test_a_queue_row_becomes_a_page_qualified_needs_audio_row  the nine fields of spec §3.1, verbatim set
  # test_a_part_whose_store_work_id_disagrees_is_skipped       identity_mismatch, nothing appended
  # test_an_existing_needs_audio_row_is_not_appended           already_derived, nothing appended
  # test_a_chain_owned_row_is_never_regressed                  archived/subtitle_done/audio_ok rows untouched
  ```

  Assertions to pin: `set(row)` equals exactly the nine field names of spec §3.1 (not a superset);
  `row["status"] == "needs_audio"`;
  `row["duration_s"]` for the three duration cases; the returned tuples for the two skip reasons; and that
  `appended` preserves the input order.

- [ ] **Step 2: Run the new tests — expect FAIL**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_manifest_derivation.py -v
  ```

  Expected: import error / collection error (`bili_asr.services.manifest_derivation` does not exist).

- [ ] **Step 3: Minimal implementation** in `src/bili_asr/services/manifest_derivation.py`: the three constants,
  `duration_s_from_ms`, `row_for_part`, `DerivationOutcome`, `derive_rows`. Module docstring states the one-way
  direction and cites spec §3. Match the house docstring style of
  `src/bili_asr/services/subtitle_ingest.py` (module docstring then constants then pure functions).

- [ ] **Step 4: Run the same tests — expect PASS** (same command as Step 2).

- [ ] **Step 5: Commit** the two files with a Conventional-Commits message scoped to the task
  (`feat(queue-bridge): derive manifest rows for the stored audio queue (pure mapping)`).

**STOP conditions:** if `manifest.py:281-290` no longer rejects a row without a page-qualified `work_id`, STOP —
the identity contract this mapping rests on has moved. If `page_identity.format_work_id` no longer produces
`<bvid>:p<n>`, STOP — the row shape is wrong, not the test.

### Task 2: The store read and the CLI command (`derive-manifest`)

**Effort (agent-oriented):** M

**Split point:** If the wiring and the CLI test file do not close in one round, split: (1)
`TranscriptRepository.read_video_pubdates` + its repository cases in `tests/test_transcript_repository.py`
(XS), then (2) the `cli.py` subparser/handler/dispatch + `tests/test_cli_derive_manifest.py` (`test_cli_derive_manifest.py`
depends on the command, never on how the pubdate map is produced).

**Files:**
- Modify: `src/bili_asr/storage/database.py` — add one read method to `TranscriptRepository` (class at
  `:711`), beside `list_pending_subtitle_parts` (`:1091-1123`); touch **nothing** else in the file.
- Modify: `src/bili_asr/cli.py` — the subparser (`build_parser`, beside the `download-audio` subparser at `cli.py:184-208`)
  at `:184-208`), the handler `_cmd_derive_manifest` (beside `_cmd_download_audio` at `:1072`), one line in
  `_ARCHIVE_WRITER_COMMANDS` (`:3075-3085`), one branch in `_dispatch_command` (`:3088-3123`).
- Test: `tests/test_cli_derive_manifest.py` (create), plus two cases appended to
  `tests/test_transcript_repository.py`.
- Out of scope: `coordinator.py`, `audio.py`, `asr.py`, `subtitles.py`, `services/subtitle_ingest.py`,
  `manifest.py`, `{SPECS_DIR}/**`, README/docs (Task 4). No new subcommand flag beyond `--archive-root`.

**Interfaces:**
- Consumes: `derive_rows` / `DerivationOutcome` / `SKIP_*` (Task 1, verbatim signatures above);
  `TranscriptRepository.list_pending_subtitle_parts()` (`database.py:1091-1123`);
  `_open_subtitle_connection(command, root, read_only=True)` (`cli.py:648-704`) → `mode=ro`, existing file
  only, transcript-schema guard; `ManifestStore(root=...)` (`manifest.py:98-106`) `load()` + `upsert()`.
- Produces: `TranscriptRepository.read_video_pubdates(self, bvids: Sequence[str]) -> dict[str, int]` — the
  stored `videos.pubdate` per bvid, `{}` for an empty input (never execute `IN ()`), each value validated with
  the module's existing `_text` helper; and the CLI command of spec §8, whose printed lines and summary the
  tests pin.

**Current state to read before writing**

- The composition pattern to copy, line for line — `_cmd_harvest_subs` (`cli.py:971-1071`):
  `connection = _open_subtitle_connection("harvest-subs", args.archive_root)`, `if connection is None: return 1`,
  a `try:` block closed by `finally: connection.close()`, then per-item print lines and one summary line,
  then the exit code.
- The empty-queue-is-success precedent — `_cmd_download_audio` (`cli.py:1103-1105`
  `print("download-audio: no needs_audio entries in the manifest"); return 0`).
- The dispatch and lock anchors — `_ARCHIVE_WRITER_COMMANDS` (`cli.py:3075-3085`), `main()`'s lock wrapper
  (`cli.py:3134-3142`), `_dispatch_command`'s command chain (`cli.py:3088-3123`).
- The store fixture pattern for the new test file — `tests/test_subtitle_cli.py:146-180` (`_seed_parts` builds
  `archive.db` through `open_database` + `MetadataRepository` with `tests/fixtures/metadata_records.py`
  factories), `:176-205` (`_archive_connection`, `_scalar`, `_exit_code`).

- [ ] **Step 1: Write the failing repository cases** in `tests/test_transcript_repository.py`
      (`test_read_video_pubdates_returns_stored_seconds`, `test_read_video_pubdates_of_no_bvid_is_empty`), run
      them, expect FAIL:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_transcript_repository.py -k read_video_pubdates -v
  ```

- [ ] **Step 2: Implement `read_video_pubdates`** on `TranscriptRepository` (same command — expect PASS).

- [ ] **Step 3: Write the failing CLI cases** in `tests/test_cli_derive_manifest.py`. Build `archive.db` with
      `_seed_parts`-style seeding: one part with no transcript, one part holding a `subtitle-ai` transcript
      (seed it through `TranscriptRepository.record_acquired_transcript`, as
      `tests/test_transcript_repository.py` does), one part with `processing_status="gone"`. Cases:

  ```python
  # test_derive_manifest_exits_zero_with_nothing_to_derive      a fixture whose every part holds a transcript
  #        (an empty queue) -> exit 0, and the summary line carries zeros
  # test_derive_manifest_appends_one_page_qualified_needs_audio_row_per_queue_part
  #        set(manifest work_ids) == set(SELECT bvid||':p'||page_index FROM v_pending_subtitles) on this fixture,
  #        every row status needs_audio, duration_s == max(1, duration_ms // 1000), cid == the part's stored cid
  # test_derive_manifest_is_idempotent_and_leaves_the_effective_state_unchanged
  #        second run: effective last-row-per-work_id map identical, and no new line appended
  # test_derive_manifest_never_regresses_a_row_the_chain_advanced
  #        pre-append an archived row for a part still in the store queue -> untouched, counted chain_owned
  # test_derive_manifest_missing_database_is_a_configuration_error
  #        exit 1 and the shipped line from cli.py:540-556; nothing created
  # test_derive_manifest_help_names_the_queue_not_the_metadata_backlog
  #        --help exits 0, names "no transcript", and does not print the bare label "pending:"
  # test_derive_manifest_holds_the_archive_writer_lock
  #        lock file exists; a pre-held lock makes the command exit 1 with "derive-manifest: archive_busy"
  ```

  Read the effective-map check the way Acceptance Criterion 1 states it (last row per `work_id`), e.g. through
  `ManifestStore(root=...).load()` rather than by comparing raw file bytes.

- [ ] **Step 4: Run the CLI cases — expect FAIL** (`invalid choice: 'derive-manifest'`):

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_cli_derive_manifest.py -v
  ```

- [ ] **Step 5: Implement the command** in `cli.py`: subparser with `--archive-root` and a `help=`/`description=`
  that names the queue (spec §2/§8); `_cmd_derive_manifest` following `_cmd_harvest_subs`'s shape and spec §8's
  output contract; add `"derive-manifest"` to `_ARCHIVE_WRITER_COMMANDS`; add the dispatch branch. No other
  flag, no other behaviour.

- [ ] **Step 6: Run the same CLI cases — expect PASS**, then the repository cases again (Step 1's command).

- [ ] **Step 7: Commit** the task's files.

**STOP conditions:** if `_open_subtitle_connection` no longer accepts `read_only=True`, or `cli.py` no longer
routes the lock through `_ARCHIVE_WRITER_COMMANDS`, STOP — the composition pattern this task copies has moved;
report instead of inventing a second pattern. If a fixture row cannot be seeded through the repository APIs,
STOP — do not write raw SQL into `archive.db` in a test.

### Task 3: The chain accepts what the bridge writes (end-to-end over a fixture)

**Effort (agent-oriented):** M

**Split point:** If the three cases do not close in one round, split (1) the selection case + the rotation case
(both need the scripted HTTP transport) from (2) the offline archive case (needs the stubbed ASR runner), each
with its own case list in the same file; the file itself stays one artifact per task review.

**Files:**
- Test: `tests/test_derived_queue_chain.py` (create).
- Out of scope: every product file. **If the chain rejects a derived row, the defect is in
  `specs/sqlite-queue-bridge-contract.md`, not in this test** — STOP and report to the PM (compass Risk
  Register row 1).

**Interfaces:**
- Consumes: the `derive-manifest` command (Task 2) and the fixture patterns of `tests/test_page_pipeline.py`
  (scripted transport: `_patch_cli`-style monkeypatching of `bili_client.build_default_transport` +
  `RouterTransport`, `tests/test_page_pipeline.py:174-209`) and `tests/test_coordinator.py`
  (`_row`, `_patch_cli`, `_stub_asr` at `:40-74`; the offline audio→archive case at `:1124-1148`).
- Produces: no product surface; the evidence for compass Acceptance Criteria 2, 3 and 6.

- [ ] **Step 1: Write the three cases** in `tests/test_derived_queue_chain.py`, each starting from a store-seeded
      fixture plus a `derive-manifest` run:

  ```python
  # test_a_derived_row_is_selected_by_missing_subs_and_attempts_that_work_id
  #        stubbed transport; `download-audio --missing-subs --limit 1` does not print
  #        "no needs_audio entries in the manifest"; the attempt targets the derived work_id and no other row
  # test_a_derived_queue_runs_to_archived_without_missing_subtitle_raw
  #        audio file present on disk + stubbed ASR; `run --scope pending --offline` reaches "archived"
  #        for the derived work_id, and coordinator/attempts.jsonl carries no missing_subtitle_raw record
  # test_a_second_bounded_selection_rotates_past_the_attempted_part
  #        two captionless parts; the first `--missing-subs --limit 1` advances part A, the second attempts B
  ```

- [ ] **Step 2: Run them — the honest expectation is PASS** (Task 2 already shipped the command, so this task
      adds evidence rather than a red step; a failure here is a contract defect in spec §4, not a missing test),
      **plus one negative control that proves the `missing_subtitle_raw` assertion can fail**: the same fixture
      with a hand-written `subtitle_done` row whose `subtitles/raw/{stem}.json` does not exist must record a
      `missing_subtitle_raw` attempt and must not reach `archived`. A check that cannot fail is not evidence:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_derived_queue_chain.py -v
  ```

- [ ] **Step 3: Fix only within the plan's scope** — a failure that needs a change to `coordinator.py`,
  `audio.py`, `asr.py` or `manifest.py` is out of scope by D2/D4: STOP and report it as a contract defect.

- [ ] **Step 4: Run the four suites of this plan together once** as the task's closing evidence (same
      working directory and interpreter as above):

      `tests/test_manifest_derivation.py tests/test_cli_derive_manifest.py tests/test_derived_queue_chain.py tests/test_transcript_repository.py`

- [ ] **Step 5: Commit** the test file.

**STOP conditions:** a derived row producing `missing_subtitle_raw`, or failing to reach `archived`, STOP —
spec §4 is wrong and the plan must not be adjusted to make the test green. If the rotation case cannot be made
to discriminate (both selections attempt the same part) while §3.4's additive policy is honoured, STOP: that is
the rotation loss spec §5 decision 4 declares, and it must be reported, not papered over.

### Task 4: Publish the new boundary (README + storage doc)

**Effort (agent-oriented):** XS

**Split point:** the two files are independent; if one round cannot hold both, land `README.md` first (it
carries the operator sequence), then `docs/metadata-storage.md`.

**Files:**
- Modify: `bilibili-asr-archive/README.md` — the boundary paragraph at `:332-340`, the command sequence at
  `:342-353`, the archive-writer list at `:435-441`, and the exit-code/command surfaces the new command appears in.
- Modify: `bilibili-asr-archive/docs/metadata-storage.md` — `### Boundary with the legacy manifest path`
  (`:288-305`).
- Out of scope: `{SPECS_DIR}/asr-archive-cli.md` (frozen — spec §7/§11 names the revision it owes, owner PM),
  `{KNOWLEDGE_DIR}/**`, `{ITERATION_DIR}/**` (the compass and this iteration's package are the PM's and the
  chain's artifacts), any other doc.

**Interfaces:**
- Consumes: the shipped behaviour of Task 2 and the wording rules of the compass Acceptance Criteria 4 and 5.
- Produces: `Verification mode: scoped-check` evidence — the greps below, with expected and observed output
  recorded verbatim; no test file is created for documentation.

**Current state to change** (both sentences are true today and must stop being the whole truth):

- `README.md:332-333` — "The `probe-subs` / `harvest-subs` pair writes to `archive.db`, not to the manifest, so
  it feeds nothing below it." — after this plan the chain's queue is derived from that database, so the
  paragraph must state what now flows (the audio queue, via `derive-manifest`) and what still does not
  (the SRT/TXT/MD projections).
- `docs/metadata-storage.md:301-305` — "the two paths do not feed each other yet. Rebuilding the SRT/TXT/MD
  projections from the stored transcripts, and enumerating the audio work queue from SQLite — including the
  parts recorded `no-subtitle`, which are that queue — belong to the next iteration." — the second half
  shipped; the first half did not.

- [ ] **Step 1: Edit `README.md`** — replace the paragraph's opening claim with what now flows and what still
      does not; add `bili-asr derive-manifest --archive-root archive` to the documented operator sequence
      between `harvest-subs` and `download-audio --missing-subs` (`:342-353`); add `derive-manifest` to the
      archive-writer command list (`:435-441`).

- [ ] **Step 2: Edit `docs/metadata-storage.md`** — rewrite the boundary section's last two bullets so they name
      the shipped bridge (the queue is now derived from the store) and the projection rebuild as the remaining
      gap. Keep the no-migration and no-importer statements untouched.

- [ ] **Step 3: Run the scoped checks from the package root and record actual output**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-sqlite-queue-bridge/bilibili-asr-archive
  grep -n "feeds nothing below it" README.md                                   # expect: no match (exit 1)
  grep -n "the two paths do not feed each other yet" docs/metadata-storage.md  # expect: no match (exit 1)
  grep -n "derive-manifest" README.md                                          # expect: the sequence + writer list + exit table
  grep -rn "from \.storage\|import storage\|archive\.db" src/bili_asr/coordinator.py src/bili_asr/audio.py src/bili_asr/asr.py  # expect: no match
  git -C /root/workspace/bilibili-asr-archive diff --stat cf3f779..HEAD -- .mstar/specs/asr-archive-cli.md   # expect: empty
  ```

- [ ] **Step 4: Commit** the two files and record the `Verification mode: scoped-check` fields (trigger =
  the sentence that is no longer true; expected vs observed; command; outcome).

**STOP conditions:** if `README.md` no longer contains the boundary sentence at `:332-340`, STOP — the published
surface moved and Acceptance Criteria 4/5's grep targets must be re-derived by the PM, not guessed. If a
doc edit would require restating the frozen spec, STOP — that is the PM's revision (spec §7).

## Recall receipt (Prepare input, per `mstar-phase-gates` §A)

**Reused** — `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md` (exit taxonomy :177-190,
read-only probe :225-230, writer-lock ordering :231-236, projection/feeder boundary :236-250): the command's
surface, its lock and its read-only connection are modelled on `harvest-subs`.
`.mstar/knowledge/architecture-patterns/normalized-transcript-storage.md` (:237-262, the pending-work relation
and its ordering): the queue contract and the reason per-part audio evidence has no store home.
`.mstar/knowledge/architecture-patterns/operational-sidecars.md:234-236` (no back-write of an inferred truth,
restated as spec §10) and §3's stage-attempt ledger (the per-part audio/ASR evidence of record).
`.mstar/knowledge/testing-patterns/worktree-test-invocation.md` (the pinned invocation and the resolved-path
probe every Run line above obeys). `{SPECS_DIR}/asr-archive-cli.md` (:61 composition rule, :97-101 exits,
:118-122 state machine).

**Rejected** — `download-audio --from-sqlite` (D2/D9 fix a standalone command); an authoritative bridge
(regresses archived rows and clobbers a live `subtitle_done`); materializing `subtitles/raw/{stem}.json` from
stored segments (piece 2, lossy re-encoding, and the store holds neither seconds nor the document's metadata);
a source-kind filter on the queue (correct for the caption backlog, wrong for the audio queue);
folding `20260918-operational-record-coverage · R3` in (touches the run-ledger timestamp comparison, not this
command — it would widen the review surface the register's `target` does not ask for).

## Done criteria

- [ ] Task 1: `pytest tests/test_manifest_derivation.py -v` passes; the row's field set is asserted as an exact
      set; the three duration cases and both skip reasons are asserted (red→green recorded).
- [ ] Task 2: `pytest tests/test_cli_derive_manifest.py tests/test_transcript_repository.py -v` passes; the
      derived set equals the store queue on the fixture; the second run appends nothing; an `archived` row is
      not regressed; a missing `archive.db` exits `1`; `--help` names the queue; `archive_busy` exits `1`.
- [ ] Task 3: `pytest tests/test_derived_queue_chain.py -v` passes: a derived row is selected by
      `download-audio --missing-subs`, reaches `archived` under `run --scope pending --offline`, produces no
      `missing_subtitle_raw` attempt record, and the second bounded selection rotates to the other part.
- [ ] Task 4: the scoped greps of Task 4 Step 3 return the stated results, recorded with actual output
      (`Verification mode: scoped-check`).
- [ ] `git diff --stat cf3f779..HEAD -- bilibili-asr-archive/src/bili_asr/coordinator.py bilibili-asr-archive/src/bili_asr/audio.py bilibili-asr-archive/src/bili_asr/asr.py bilibili-asr-archive/src/bili_asr/manifest.py` is empty (D2/D4).
- [ ] `grep -rn "derive-manifest" src/bili_asr/cli.py` matches the subparser, the handler, the writer-lock set
      and the dispatch branch, and nothing else in `src/` mentions the command name.
- [ ] `git diff --check` exits 0; no files outside the tasks' Files lists are modified (`git status --short`).

## Plan self-review (PM before locked)

1. **Spec coverage:** spec §2 → Task 2 (queue + naming); §3.1/§3.2 → Task 1; §3.4/§3.6 → Task 1 + Task 2's
   regression/idempotency cases; §4 → Task 3; §5 → Task 3's rotation case + the disclosed loss; §6/§7 → no code
   (naming duty in Task 2's help case; the frozen-spec revision is the PM's Q6); §8 → Task 2; §9 → Task 2;
   §10 → Tasks 1-3 by construction; §13 → the Done criteria.
2. **Placeholder check:** every File path, selector and command above is concrete; no `TBD`, no unowned marker.
3. **Type consistency:** `derive_rows` / `DerivationOutcome` / `SKIP_*` / `read_video_pubdates` /
   `duration_s_from_ms` / `row_for_part` are spelled the same in Tasks 1, 2 and 3.
4. **Capacity (task shape / session fit):** every task declares its Effort band, names its split point, and
   closes its own Files and verification gates in one round; budget pressure never shortens an assigned scoped
   check (`mstar-artifacts/references/plan-quality-bar.md` item 7).

## SDD runtime (ephemeral)

`{SDD_DIR}/20260919-sqlite-queue-bridge/` — per-task briefs, implementer reports (`task-N-report.md`), L2 task
reviews (`task-N-review.md`), and the plan-QC/QA bundle (`review/qc1..3.md`, `review/qa.md`). Gitignored; do not
paste bundle contents into this file. `QA gate: mandatory` (`qa_mode: targeted`) — behaviour change plus open
`R#`s.
