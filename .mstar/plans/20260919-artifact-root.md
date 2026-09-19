---
plan_id: 20260919-artifact-root
iteration: iter-2026-09-artifact-root
iteration_compass: .mstar/iterations/iter-2026-09-artifact-root/delivery-compass.md
primary_spec: .mstar/iterations/iter-2026-09-artifact-root/specs/artifact-root-contract.md
iteration_refs:
  - .mstar/iterations/iter-2026-09-artifact-root/specs/artifact-root-contract.md
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# Where the artifacts go: `--artifact-root` / `BILI_ARTIFACT_ROOT`

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the location of the pipeline's **products** (audio, transcript bundles, harvested subtitle
documents) configurable per invocation — CLI flag first, `BILI_ARTIFACT_ROOT` second, unset = today's paths —
while the repository, the worktrees and every piece of project **state** (`manifest/`, `archive.db`,
`coordinator/`, sidecars, `search.db`) stay at the archive root; audio becomes retained by default; and the
confinement guard is re-based onto whichever root an artifact is read or written under, with every existing
guarantee intact. No migration.

**Closes:** **nothing.** This is a new capability (compass `D1`–`D6`), not a register item. The
retained-audio × `--max-audio-gb` interaction is **spec §12 Q1**, escalated to the user; it is not closed by
this plan, and the PM records its disposition at iteration close.

**Architecture:** Today one `--archive-root` holds everything, and the audio location is pinned in code — the
writer asserts the audio directory **is** `<archive_root>/audio` (`audio.py:186-188`) and derives its root from
`store.root`/the path prefix (`audio.py:127-154`). This plan splits that single root into a **state root**
(unchanged) and an **artifact root** (new, defaults to the state root). The recorded manifest paths do **not**
change: they stay artifact-root-relative (`audio/{stem}.m4a`, `transcripts/srt/{stem}.srt`), which is both what
the guards already require (`path_policy._audio_parts:16-29`, `archive._owned_bundle_parts:155-168`) and what
makes an existing manifest keep working with no migration. Readers resolve a recorded path over an ordered pair
of bases — configured artifact root first, then the archive root — each validated at its own base. Full
contract, every claim anchored to `file:line`: `{ITERATION_DIR}/iter-2026-09-artifact-root/specs/artifact-root-contract.md`
(cited below as **spec §N**).

**Tech Stack:** Python 3.12, stdlib only (`os`, `pathlib`, `dataclasses`, `argparse`), pytest 9
(`bilibili-asr-archive/.venv/bin/python`). **No new dependency.**

**Execution:** mstar-sdd

**Main worktree branch**: `main` (the control root stays on `main`; the plan's feature work happens on
`fix/20260919-artifact-root` in the worktree named in Global Constraints).

## Global Constraints

- **Two roots, and every command names its working directory.** The **repository root** is
  `/root/workspace/bilibili-asr-archive` (holds `.git`, `.mstar/`, `.worktrees/`, and the package directory
  `bilibili-asr-archive/`); the **package root** is `<repo-root>/bilibili-asr-archive` (holds `.venv/`, `src/`,
  `tests/`). Python and pytest always run from a **package root**.
- **Where the code under test lives (this plan runs in a linked worktree).** Phase 2 executes on
  `fix/20260919-artifact-root` in the worktree
  `/root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root` (created by the PM per
  `mstar-branch-worktree`; path shape matches the three existing worktrees). That worktree has **no `.venv`**
  (gitignored, so `git worktree add` does not carry it) and the control root's venv is an *editable* install
  whose `.pth` points `bili_asr` at the **control root** `src` — so an unpinned run silently grades the
  unmodified tree. Every task therefore runs exactly:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v
  ```

  and before trusting any result confirms the tree:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -c \
       "import bili_asr, pathlib; print(pathlib.Path(bili_asr.__file__).resolve())"
  ```

  The printed path must be under the worktree. A report that records only "N passed", without the pinned
  `PYTHONPATH` and the resolved `bili_asr.__file__`, has not recorded which code it tested
  (`.mstar/knowledge/testing-patterns/worktree-test-invocation.md`). Verification commands inside a task run
  from the package root of that worktree.
- **D1 / D2 / D3 (user-locked, do not re-open):** one **artifact root** covering audio + transcripts +
  subtitles; **CLI flag + environment variable, the flag wins**; unset reproduces today's behaviour
  byte-for-byte; names are exactly `--artifact-root` and `BILI_ARTIFACT_ROOT` (collision-checked, spec §3.1).
- **D4 (user-locked):** the confinement guard is **re-based**, never dropped — each configured root is opened
  descriptor-anchored with `O_NOFOLLOW`, a symlinked root or target directory is still refused, and a path
  escaping its own root is still refused. `path_policy.py` is **not modified**; only which root the callers
  pass to it changes (spec §6).
- **D5 (user-locked):** audio retention is a first-class flag **defaulting to retain**; `BILI_KEEP_AUDIO=1`
  stays honoured (`audio_reclaim.py:46` today). The resolved decision is a **value passed into** the library —
  `reclaim_audio` must stop reading `os.environ` (spec §7, D15).
- **D6 (user-locked):** **no migration.** Unset = today's paths; an existing archive root keeps working; legacy
  relative `audio_path` values keep being honoured by every reader, which is why reads probe **two bases** and
  writes use exactly one (spec §5, D8).
- **D7–D18 (architect-locked this pass, recorded in the spec, do not re-open without the PM):** recorded paths
  stay root-relative (D7); two-base ordered reads, per-base validation (D8); precedence and lexical rules (D9);
  validation and the identity case (D10); different filesystem legal, no EXDEV path (D11); nothing durable is
  recorded (D12); products only — state stays (D13); no second writer lock (D14); retention resolved once at
  the boundary (D15); the cap measures the artifact root (D16); an unusable root is a refusal, never an empty
  report (D17); the flag exists only where it is honoured (D18).
- **The operator surface is fixed** (spec §9): `--artifact-root` on `asr`, `pilot`, `download-audio`,
  `coverage`, `verify`, `recover`, `export`, `search`, `run`, `schedule`, `campaign`; **not** on `fetch-meta`,
  `status`, `runs`, `probe-subs`, `harvest-subs`, `derive-manifest`. `--keep-audio/--no-keep-audio` on `asr`,
  `pilot`, `run`, `schedule`, `campaign` only. Resolution happens **once, in `main()`, before the writer
  lock**; the two refusal lines are exactly:
  `<command>: artifact root does not exist (<path>)` and
  `<command>: artifact root is not a directory (<path>)`, both exit **1** — no new exit-code value
  (`{SPECS_DIR}/asr-archive-cli.md:97-101`).
- **Layering.** `artifact_root.py` is a shared policy leaf like `path_policy.py`: stdlib + `path_policy` only,
  and it imports no manifest/storage/artifact-writer module. No library module resolves configuration itself;
  the CLI builds the one `ArtifactRoots` value (spec §3.4, §11).
- **Library defaults are the identity case.** Every new library parameter is keyword-only with default `None`
  → `ArtifactRoots.of(archive_root)`, i.e. today's single-root behaviour. This is what lets the library tasks
  land with a green tree before `cli.py` is wired (Task 4) and keeps each layer unit-testable; its cost is
  disclosed in spec §11 and Task 4 is what removes the ambiguity in the product path.
- **Verification scope** (`mstar-harness-core` § 定向执行与验证边界): only the changed behaviour and its direct
  contracts. **No local full-suite run** — the suites named in the four tasks are the whole local evidence
  budget; the full suite is CI's. Reuse unaffected evidence with its original range; do not re-run checks
  because HEAD moved. **Never assign real-browser/device/installed-deployment E2E evidence as a task or a gate
  of this plan**: two cases in `tests/test_cli_help.py` (`test_installed_*`) error in this sandbox because
  `/root/.cache/uv` is read-only, so that file is always selected with `-k "not installed"`. No test in this
  plan touches a real mount, a real `--archive-root archive/`, or the network.
- **Do not edit:** `{KNOWLEDGE_DIR}/**` (Phase 1/2 never add knowledge), `{SPECS_DIR}/asr-archive-cli.md`
  (frozen; the revision this iteration owes is spec §12 D19 and is the PM's), `{HARNESS_DIR}/workflows/**`,
  `status.json`, the register, the compass or any other plan. Documentation edits are limited to Task 4's
  three files.
- **Task dependency and ordering.** Task 1 is a prerequisite for Tasks 2 and 3; Tasks 2 and 3 are
  **independent of each other** (disjoint files) and may be dispatched in parallel; Task 4 consumes both and
  is dispatched last. **No task's Files list overlaps another's** — this is the reason `cli.py` is a single
  task (Task 4) rather than split across the write and read work.
- **Drift check before Task 1** (plan written at `5961800`):

  ```bash
  git -C /root/workspace/bilibili-asr-archive diff --stat 5961800..HEAD -- \
    bilibili-asr-archive/src/bili_asr/audio.py bilibili-asr-archive/src/bili_asr/coordinator.py \
    bilibili-asr-archive/src/bili_asr/subtitles.py bilibili-asr-archive/src/bili_asr/audio_reclaim.py \
    bilibili-asr-archive/src/bili_asr/audio_budget.py bilibili-asr-archive/src/bili_asr/campaign.py \
    bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/src/bili_asr/coverage_report.py \
    bilibili-asr-archive/src/bili_asr/integrity.py bilibili-asr-archive/src/bili_asr/export.py \
    bilibili-asr-archive/src/bili_asr/quality.py bili-asr-archive/src/bili_asr/search_index.py \
    bilibili-asr-archive/src/bili_asr/path_policy.py bilibili-asr-archive/src/bili_asr/cli.py
  ```

  If any in-scope file changed, re-read the current-state excerpts below before proceeding; on a mismatch that
  moves an anchor this plan rests on (in particular `path_policy`'s signatures, `audio.py:186-188`, or
  `cli.py`'s `main()`), STOP and report.

## Engine lifecycle

Who advances this plan row's engine state, and what records each transition:

- **Scoped sequence** — one engine verb per transition; never a hand-edited snapshot: `bind --coordinator` →
  `prepare` → `bind` → `progress` → `handoff` → `accept` → `integration-start` → Git merge →
  `integration-accept` → `complete`.
- **Evidence order** — `compound` disposition, PR identity and merge evidence are recorded **after** the row is
  `Done`; the engine refuses those writes while any plan row is not `Done`. The delivery tail runs on a
  completed row, never ahead of it. This plan's row is the iteration's only row, and the iteration closes once.
- **Snapshot declares integration anchors** (`branch.base = main`, `branch.integration =
  iteration/iter-2026-09-artifact-root`, `branch.target = main`): the row can reach `Done` through the sequence
  above. The merge into the integration branch is `integration-start` → Git merge → `integration-accept`.

Semantics and failure behaviour → `mstar-artifacts/references/plan-workflow-lifecycle-contract.md`; PM step
sequence → `mstar-roles/references/project-manager/plan-management.md`.

---

### Task 1: The resolution core — precedence, validation, ordered bases

**Effort (agent-oriented):** S

**Split point:** If the module and its cases do not close in one round, split at the pure/impure boundary:
(1) `resolve_artifact_root` + `resolve_keep_audio` + `ArtifactRoots.of` (pure, no filesystem) and their cases,
then (2) `roots_for` + `resolve_audio_path` + `ArtifactRoots.read_bases` (filesystem-touching). Slice (1)
exports the same names, so nothing is re-derived at the split.

**Files:**
- Create: `src/bili_asr/artifact_root.py`
- Create: `tests/test_artifact_root.py`
- Out of scope: **every other file in the repository.** This task has no caller; it must not touch `cli.py`,
  `path_policy.py`, or any artifact writer/reader.

**Interfaces:**
- Consumes: `path_policy.confined_audio_path` (unchanged, `path_policy.py:78-111`) — the only non-stdlib
  import.
- Produces (verbatim, for Tasks 2–4): the API of spec §3.4 —
  `ARTIFACT_ROOT_ENV_VAR = "BILI_ARTIFACT_ROOT"`, `KEEP_AUDIO_ENV_VAR = "BILI_KEEP_AUDIO"`,
  `KEEP_AUDIO_DEFAULT = True`, `ArtifactRootError`, `ArtifactRoots` (`of`, `configured`, `write_base`,
  `read_bases`), `resolve_artifact_root(value, environ)`, `resolve_keep_audio(flag_value, environ)`,
  `roots_for(archive_root, *, flag_value=None, environ=None)`, `resolve_audio_path(roots, declared, *,
  require_exists=True)`.

**Current state to read before writing**

- The precedence idiom to follow — `config.resolve_proxy` (`config.py:154-175`: candidate order, blank counts
  as unset and never blocks the next level, value stripped) and `config.resolve_sessdata`
  (`config.py:128-141`: the blank-blocks-fallthrough rule this design deliberately does **not** copy — spec
  §3.2 says why).
- The env-var naming convention — `config.SESSDATA_ENV_VAR`/`PROXY_ENV_VAR` (`config.py:35`, `:40`) and
  `asr.ASR_MODEL_ENV_VAR` (`asr.py:106`): `<THING>_ENV_VAR` module constants, no literal scattered at use sites.
- The guard the resolver wraps — `path_policy.confined_audio_path` (`:78-111`) with `_audio_parts` (`:16-29`);
  note that `require_exists=True` returns `None` for *both* "missing" and "refused", which is exactly why spec
  §5's rule is "probe each base, first hit wins" rather than "distinguish refusal".
- The shipped confinement cases that must keep passing untouched — `tests/test_persistence_scale.py:527-556`.

- [ ] **Step 1: Write the failing unit tests** in `tests/test_artifact_root.py` (pure, `tmp_path` only, no CLI,
      no monkeypatched `os.environ` — every environment is passed as a mapping):

  ```python
  # names are the selectors the task later runs
  # test_flag_wins_over_environment_and_unset_is_none
  # test_a_blank_value_at_either_level_counts_as_unset            "", "   " -> fall through (resolve_proxy rule)
  # test_the_value_is_stripped_and_tilde_is_expanded              "  ~/artifacts  " -> $HOME/artifacts
  # test_a_relative_value_resolves_against_the_current_directory  abspath, and == archive root when equal
  # test_an_explicit_value_equal_to_the_archive_root_is_the_identity_case
  #        configured is False, read_bases() == (archive,), write_base == archive, no isdir check performed
  # test_a_missing_or_non_directory_root_is_a_refusal             ArtifactRootError, message names the path
  # test_read_bases_are_ordered_and_deduplicated                  (artifact, archive); a configured root inside
  #        the archive root is two distinct bases in that order
  # test_resolve_audio_path_prefers_the_artifact_root_then_the_archive_root
  #        one stem present in both roots -> the artifact-root file; present only in the archive root -> that one
  # test_resolve_audio_path_rejects_an_escaping_or_wrong_shaped_value_at_every_base
  #        "audio/../x.m4a", "/tmp/x.m4a", "audio/x.wav", "audio/sub/x.m4a", a symlinked entry -> None
  # test_keep_audio_precedence_table
  #        flag True/False wins; env "1"/"0"; env "yes"/""/absent -> KEEP_AUDIO_DEFAULT (True)
  ```

  Assertions to pin: `ArtifactRootError` is a `ValueError` (so the CLI's config-error path is the existing
  one); `read_bases()` never returns a base twice; the refusal happens for a **configured** value only (the
  identity case is never validated — spec §3.3).

- [ ] **Step 2: Run the new tests — expect FAIL**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_artifact_root.py -v
  ```

  Expected: collection error (`bili_asr.artifact_root` does not exist).

- [ ] **Step 3: Implement `src/bili_asr/artifact_root.py`** with the module docstring from spec §3 (the split
  it encodes, the precedence with its `file:line` reasons, the two-base read rule and the `O_NOFOLLOW`
  consequence), then the constants, the exception, the frozen dataclass and the four functions. House style:
  module docstring → constants → `ArtifactRootError` → `ArtifactRoots` → pure resolvers → filesystem-touching
  helpers, matching `config.py`'s shape. `resolve_audio_path` loops `roots.read_bases()` and wraps
  `path_policy.confined_audio_path`; it must not re-implement any part of `_audio_parts`.

- [ ] **Step 4: Run the same tests — expect PASS**, then the confinement regression:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_artifact_root.py tests/test_persistence_scale.py -k "confined_audio or artifact" -v
  ```

- [ ] **Step 5: Commit** the two files with a Conventional-Commits message scoped to the task
  (`feat(artifact-root): resolve and validate the configurable artifact root`).

**STOP conditions:** if `path_policy.confined_audio_path` no longer takes its root as its first parameter, STOP —
the guard this task wraps has moved and the re-basing in Tasks 2–3 would be built on a false premise. If
`path_policy._audio_parts` no longer rejects absolute paths and `..` components, STOP — spec §5's "recorded
paths stay root-relative" argument collapses and the contract must be re-opened, not the test relaxed.

---

### Task 2: The pipeline writes to the artifact root; retention becomes a value

**Effort (agent-oriented):** L

**Split point:** If the write path does not close in one round, split at the module-family boundary (both
halves are disjoint and neither re-derives the other's work): (1) the **audio family** — `audio.py`,
`audio_reclaim.py` and the two test files this task edits (`tests/test_audio_reclaim.py`,
`tests/test_audio_retention_policy.py`), which is where the `audio_path` shape and the retention value are
produced; then (2) the **chain family** — `coordinator.py`, `subtitles.py`, `campaign.py`, `manifest.py` and
the new cross-module test file, which consumes (1)'s `download_audio(..., artifact_roots=)` signature as spec
§11 fixes it.

**Files:**
- Modify: `src/bili_asr/audio.py` — `download_audio` (`:156-161`) and `_mark_audio_ok` (`:257-280`) gain the
  roots; `_archive_root_for_download` (`:127-154`) takes the artifact root when one is given; `_existing_audio`
  (`:108-124`) probes both bases. **`audio.py:186-188`'s shape assertion is kept as an assertion about the
  *artifact* root** — the local variable it compares against is the root the write is anchored to; the line is
  not deleted.
- Modify: `src/bili_asr/coordinator.py` — `RunCoordinator.__init__` (`:316-350`) gains `artifact_roots=None`
  and holds it; then the artifact-touching sites inside: `_subtitle_segments` (`:396-413`), `_existing_audio`
  (`:415-433`), `_stage_archive_from_subtitle` (`:454-456`), `_reclaim_audio` (`:497-505`),
  `_stage_asr_archive` (`:528`, `:542-545`, `:553`, `:566-570`), `_stage_download` (`:586`, `:597`, `:599-601`,
  `:613-620`), `_batch_needs_asr` (`:725`).
- Modify: `src/bili_asr/subtitles.py` — `harvest_subtitle` (`:82-158`) gains `artifact_roots=None`; the raw/srt
  writes (`:136-147`) and the recorded `srt_path` (`:152`) use the artifact root; the
  `store.migrate_legacy_rows(...)` call (`:101-105`) passes the artifact root **positionally** as its second
  argument (see `manifest.py` below).
- Modify: `src/bili_asr/audio_reclaim.py` — `reclaim_audio` (`:40-65`) becomes
  `reclaim_audio(archive_root, entry, *, artifact_roots=None, keep: bool)`; the `os.environ` read (`:44-47`) is
  **deleted**; the candidate loop runs per base.
- Modify: `src/bili_asr/manifest.py` — `migrate_legacy_rows`'s second parameter (`:332-343`, today
  `archive_root=`) is renamed `artifact_roots` and `_foreign_page_stems` (`:418-437`) scans **both** bases
  (a foreign page stem in either root keeps a bare-`bvid` row frozen, `:387-401`).
- Modify: `src/bili_asr/campaign.py` — `CampaignRunner.__init__` (`:95-106`) gains `artifact_roots=None` and
  forwards it to `RunCoordinator` (`:324`). Nothing else in the file: `campaign.json`, `SchedulerStore` and
  `ManifestStore` stay archive-root-scoped (spec §2.2).
- Modify: `tests/test_audio_reclaim.py` (11 call sites), `tests/test_audio_retention_policy.py` (4 cases) —
  `keep` is now a required keyword, so every call site is updated. The retention file's four cases keep their
  exact intent with the environment read moved to `resolve_keep_audio`: `=1` keeps (`:11-39`), no variable →
  the new default keeps (`:43-70`, whose assertion **inverts** — the resolved policy is retain, which is D5),
  `=0` reclaims (`:73-101`), and `test_coordinator_respects_keep_audio_policy` (`:104-147`) becomes a real
  coordinator case: today it imports `RunCoordinator` and then calls `reclaim_audio` directly
  (`:135-139`), which is the boundary D15 removes — it must construct the coordinator with
  `keep_audio=False` (and `keep_audio=True`) and assert the audio is removed/kept after the row is archived.
  Weakening it back to a bare `reclaim_audio` call would leave the "resolved once, passed down" rule unproved.
- Modify: `tests/test_manifest.py` — the renamed parameter at the seven call sites (`:63`, `:199`, `:219`,
  `:247`, `:263`, `:278`, `:295`) plus one new case: a foreign page stem present only under a configured
  artifact root still freezes the bare row.
- Create: `tests/test_artifact_root_writes.py` — the cross-module cases (Step 3).
- Out of scope: `cli.py` (Task 4), every reader module (Task 3), `audio_budget.py` and `long_live.py`
  (root-parameterized already — their **callers** pass the artifact root), `path_policy.py` (spec D4: not
  modified), README/docs (Task 4).

**Interfaces:**
- Consumes: Task 1's `ArtifactRoots` (`of`, `write_base`, `read_bases`), `resolve_audio_path`,
  `resolve_keep_audio`, `KEEP_AUDIO_ENV_VAR`.
- Produces (verbatim, for Task 4): `audio.download_audio(client, target, out_path, store=None, *,
  artifact_roots: ArtifactRoots | None = None) -> str`;
  `RunCoordinator(archive_root, store, *, ..., artifact_roots=None, keep_audio=True)`;
  `subtitles.harvest_subtitle(client, target, store, archive_root, *, artifact_roots=None) -> str`;
  `reclaim_audio(archive_root, entry, *, artifact_roots=None, keep: bool) -> bool`;
  `ManifestStore.migrate_legacy_rows(pages_for, artifact_roots=None, only_bvid=None, *,
  coalesce_existing_page=False)`;
  `campaign.CampaignRunner(archive_root, *, ..., artifact_roots=None)`.
  **A recorded `audio_path` remains exactly `audio/<stem>.m4a` (or `.flac`) with the artifact root outside the
  archive root** — the string is the interface, and Task 4's end-to-end case asserts it.

**Current state to read before writing**

- The silent-failure trap this task exists to fix — `audio._mark_audio_ok` (`audio.py:271-280`): today it
  computes `os.path.relpath(final_path, Path(store.root).resolve())`, and with the file outside `store.root`
  that yields a `..`-bearing string which `confined_audio_path` rejects (`:276-278`) — the function then
  **returns without upserting**, so the row never reaches `audio_ok` and the next run re-downloads. Spec §15
  correction 7 records that this is the real failure mode (the `OSError("audio path outside archive")` at
  `coordinator.py:566-568` is only reachable on Windows).
- The write path's shape assertion — `audio.download_audio` (`:186-188`) and the staged publish
  (`:203-252`), all anchored on one directory fd; the flac fallback rebuilds its path at `:233`.
- The chain's own roots — `RunCoordinator.__init__` (`:316-350`), `_existing_audio` (`:415-433`: it joins
  `entry["audio_path"]` with `self.root` at `:420` and re-confines at `:428`), `_stage_download` (`:575-624`),
  `_stage_asr_archive` (`:507-573`), `_reclaim_audio` (`:497-505`).
- The retention seam — `audio_reclaim.reclaim_audio` (`:40-65`) with its `BILI_KEEP_AUDIO` read at `:46` and the
  `_candidate_paths` builders (`:20-37`); the shipped policy cases in
  `tests/test_audio_retention_policy.py:11-95` and `tests/test_audio_reclaim.py:35-149`.
- The legacy probe — `manifest._ARTIFACT_REL_DIRS` (`:408-415`) and `_foreign_page_stems` (`:418-437`), called
  once from `migrate_legacy_rows` (`:360`).
- The campaign composition — `campaign.py:292-330` (`ManifestStore(self.root)`, then
  `RunCoordinator(self.root, store, ...)`).

- [ ] **Step 1: Write the failing cross-module cases** in `tests/test_artifact_root_writes.py`. Build the
      fixture the way `tests/test_coordinator.py` builds its root, with `tmp_path / "state"` and
      `tmp_path / "artifacts"` (two distinct directories, and one case with the artifact root *inside* the
      archive root):

  ```python
  # test_download_audio_publishes_into_the_artifact_root_and_records_a_root_relative_path
  #        the file exists at {artifact}/audio/{stem}.m4a; the manifest row's audio_path == "audio/{stem}.m4a";
  #        nothing was created under {archive}/audio/ ; the row reached audio_ok
  # test_an_existing_legacy_copy_at_the_archive_root_is_honoured_and_not_duplicated
  #        with the same relative path present only under the archive root: no second download, no copy,
  #        audio_path unchanged
  # test_the_coordinator_archives_with_bundles_at_the_artifact_root
  #        after a run over a needs_audio row: transcripts/{srt,txt,md,raw} exist under {artifact},
  #        srt_path/txt_path/md_path/raw_path are the shipped relative strings, manifest/ and coordinator/
  #        are under {archive}
  # test_retention_leaves_the_audio_in_place_by_default
  #        the row is archived and the audio file still exists (with keep_audio=True)
  # test_reclaim_removes_the_audio_when_it_is_asked_for
  #        keep=False removes the confined entries under both bases; nothing outside them is touched
  # test_harvest_subtitle_writes_raw_and_srt_into_the_artifact_root
  #        subtitles/raw/{stem}.json and transcripts/srt/{stem}.srt under {artifact}; srt_path relative
  # test_a_foreign_page_stem_under_the_artifact_root_freezes_a_legacy_bare_row
  #        the manifest migration report lists the bvid as unresolved
  # test_the_identity_default_reproduces_todays_paths
  #        artifact_roots omitted -> every file lands under the archive root, exactly as today
  ```

- [ ] **Step 2: Run the new tests — expect FAIL**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_artifact_root_writes.py -v
  ```

  Expected: `TypeError` on the new keyword arguments.

- [ ] **Step 3: Implement the write path**, module by module, in this order (each keeps the tree green because
  every new parameter is keyword-only and defaulted to the identity case):
  1. `audio.py` — thread `artifact_roots` from `download_audio` into `_archive_root_for_download` and
     `_mark_audio_ok`; `_existing_audio` takes the roots and returns the first existing candidate across
     `read_bases()`. Keep the `:186-188` assertion, comparing against the artifact root's `audio/`.
  2. `audio_reclaim.py` — new signature, no `os.environ`; per-base candidates.
  3. `coordinator.py` — hold `self.artifact_roots` (default `ArtifactRoots.of(self.root)`), and pass
     `write_base` where the write goes and `read_bases()`/`resolve_audio_path` where a read happens. Every
     recorded value keeps its shipped string.
  4. `subtitles.py` and `manifest.py` — the artifact root for the two writes and for the legacy scan; the
     `migrate_legacy_rows` call passes it positionally.
  5. `campaign.py` — forward the value to `RunCoordinator`.
  6. Update the four existing test files named in **Files** (the `keep` keyword and the renamed manifest
     parameter), keeping every existing case's intent.

- [ ] **Step 4: Run the new tests and the direct-impact suites — expect PASS**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
       tests/test_artifact_root_writes.py tests/test_audio.py tests/test_audio_reclaim.py \
       tests/test_audio_retention_policy.py tests/test_audio_budget.py -v
  ```

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
       tests/test_coordinator.py tests/test_manifest.py tests/test_campaign.py tests/test_subtitles.py \
       tests/test_long_live.py -v
  ```

- [ ] **Step 5: Commit** the task's files with a Conventional-Commits message
  (`feat(artifact-root): publish audio and bundles to the configured artifact root`).

**STOP conditions:** if `tests/test_audio.py`'s existing positional calls (`tests/test_audio.py:242-472`)
cannot keep passing unmodified, STOP — the new parameter is not keyword-only and the interface has drifted from
spec §11. If a recorded `audio_path` comes out as anything other than `audio/<name>.<ext>` for an artifact root
outside the archive root, STOP and re-read spec §5 — a `..`-bearing value is the silent failure this task
exists to prevent, and it must fail loudly here rather than be worked around. If `_publish_bundle`'s fixed
staging directory name (`archive.py:228-230`) throws while a second archive root is not in play, STOP — the
artifact root is not being used as a single write base.

---

### Task 3: The readers resolve artifact paths over both bases

**Effort (agent-oriented):** L

**Split point:** If the readers do not close in one round, split into (1) the **inventory readers** —
`coverage_report.py` and `quality.py` (both walk bundles/audio and both are reached from `coverage`), then
(2) the **verification and export readers** — `integrity.py`, `export.py`, `search_index.py`. Each half has its
own test file and neither consumes the other's symbols.

**Files:**
- Modify: `src/bili_asr/coverage_report.py` — `CoverageReport.build` (`:56-63`) gains
  `artifact_roots=None`; `_transcript_evidence` (`:446-468`) probes both bases; `_contained_path` (`:471-478`)
  keeps its `resolve`-based check, applied per base. Sidecar reads (`:66`, `:77`, `:80`, `:83`, `:95`) stay at
  the archive root.
- Modify: `src/bili_asr/quality.py` — `QualityAnalyzer.analyze` (`:212-236`) gains `artifact_roots=None`;
  `_artifact_paths` (`:339-390`), including the inferred `transcripts/md` glob (`:369-380`), walks both bases;
  `_contained` (`:392-396`) applied per base.
- Modify: `src/bili_asr/integrity.py` — `IntegrityVerifier.verify` (`:185-200`) gains `artifact_roots=None`;
  `_required_paths`/`_canonical_required_paths` (`:465-479`), the bundle probe (`:280`) and the
  `subtitles/raw` probe (`:282`) walk both bases through `_safe_path` (`:532-533`); `verify`'s
  `authoritative` judgement stays a function of the **state** reads (manifest `:206`, attempts `:209`/`:235`);
  `recover` (`:300-330`) forwards the value into its internal `verify` call (`:330`) and keeps its audit
  sidecar under `coordinator/` (`:349`).
- Modify: `src/bili_asr/export.py` — `export_manifest` (`:394-402`) gains `artifact_roots=None`;
  `sanitize_export_entry` (`:163-210`) uses it as the containment base for the artifact path fields
  (`_safe_contained_relpath`, `:108-139`) and for `extract_transcript_text` (`:205`); the five path keys are
  the ones at `:31`. `ManifestStore(archive_root)` (`:411`) stays the state read.
- Modify: `src/bili_asr/search_index.py` — the module entry point `search(archive_root, query)`
  (`:823-835`, which builds `SearchIndex(archive_root)` at `:833`) and `SearchIndex.__init__` (`:352-355`) gain
  `artifact_roots=None` (`search.db` stays at `self.root`, `:354`); the on-disk probes (`:440-463`) and
  `extract_transcript_text` (`:138-235`, including the `subtitles/raw` fallback `:212`) walk both bases.
- Modify: `tests/test_coverage_report.py`, `tests/test_quality.py`, `tests/test_integrity.py`,
  `tests/test_export.py`, `tests/test_search_index.py` — one new case each (Step 1), existing cases unchanged.
- Create: `tests/test_artifact_root_readers.py` — the cross-reader inventory case (Step 3).
- Out of scope: `cli.py` (Task 4), every writer module (Task 2), `manifest.py`, `sidecar_projection.py`
  (state readers), `path_policy.py`, `archive.py` (its guard is already root-parameterized and is consumed
  per base).

**Interfaces:**
- Consumes: Task 1's `ArtifactRoots` (`of`, `read_bases`) and `resolve_audio_path`; the shipped guards
  (`archive.archive_bundle_complete`, `archive_stem`, `path_policy.confined_audio_path`) applied per base.
- Produces (verbatim, for Task 4): `CoverageReport.build(archive_root, *, scope=None, policy=None,
  artifact_roots=None)`; `QualityAnalyzer.analyze(entry, archive_root, reference_path=None, *,
  artifact_roots=None)`; `IntegrityVerifier.verify(archive_root, *, scope=None, policy=None,
  artifact_roots=None)` and `IntegrityVerifier.recover(archive_root, *, work_ids=None, defect_codes=None,
  limit=100, artifact_roots=None)`; `export_manifest(archive_root=..., *, artifact_roots=None, ...)`;
  `SearchIndex(root, *, artifact_roots=None)` and `search(archive_root, query, *, artifact_roots=None)`.

**Current state to read before writing**

- The audio-side reader that already probes a candidate list — `coordinator._existing_audio` (`:415-433`) — is
  the shape to mirror for `coverage`/`quality` inference, with `resolve_audio_path` replacing the hand-rolled
  `relpath` + `confined_audio_path` pair.
- The two mechanisms that must **not** be unified — `coverage_report._contained_path` (`:471-478`) and
  `quality._contained` (`:392-396`) use `resolve()` + `relative_to`, while the audio side uses the
  descriptor-anchored guard; spec §5/§6 fix this as "shared base list, per-family guard".
- The `recover` path that hides a second reader — `integrity.recover` calls `verify` internally
  (`integrity.py:330`), so a `recover` that does not forward the root silently grades artifacts against the
  wrong base.
- The export containment contract — `_safe_contained_relpath` (`export.py:108-139`) returns `None` for a value
  that escapes its base, and `sanitize_export_entry` strips such a field to `""` (`:187-195`): with the wrong
  base, a configured root turns five populated path fields into empty strings, which is the export-side
  version of "reports a live archive as broken".
- The search index's dual role — `SearchIndex.__init__` (`search_index.py:352-355`) derives both `db_path` and
  the artifact probes from one `self.root`, and the CLI reaches it only through the module function
  `search()` (`:823-835`, index built at `:833`) called from `cli.py:2941`.

- [ ] **Step 1: Write the failing per-reader cases** — one in each of the five existing test files, each with an
      artifact root distinct from the archive root holding the artifact and the archive root holding nothing:

  ```python
  # tests/test_coverage_report.py  test_a_configured_artifact_root_is_reported_as_present
  # tests/test_quality.py          test_the_quality_analyzer_reads_the_artifact_root
  # tests/test_integrity.py        test_verify_grades_artifacts_at_the_artifact_root
  #                                and test_recover_forwards_the_artifact_root_into_its_verification
  # tests/test_export.py           test_export_keeps_the_path_fields_of_a_configured_artifact_root
  # tests/test_search_index.py     test_the_index_reads_transcripts_from_the_artifact_root
  ```

- [ ] **Step 2: Run them — expect FAIL** (unexpected keyword argument), each selector named explicitly:

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
       tests/test_coverage_report.py tests/test_quality.py tests/test_integrity.py tests/test_export.py \
       tests/test_search_index.py -k "artifact_root" -v
  ```

- [ ] **Step 3: Implement the reader threading**, then write `tests/test_artifact_root_readers.py` — the case
      that proves the compass criterion "the same inventory with and without a configured root":

  ```python
  # test_the_same_fixture_reports_the_same_inventory_at_either_root
  #        one archived row whose artifacts live at {archive} and one whose artifacts live at {artifact}:
  #        CoverageReport.build(..., artifact_roots=...) reports both rows' artifact_present True,
  #        IntegrityVerifier().verify(..., artifact_roots=...) reports zero defects,
  #        export_manifest(..., artifact_roots=...) keeps all five path fields non-empty,
  #        and each of the four calls with artifact_roots omitted reports exactly what it reports today
  # test_a_configured_root_that_is_absent_is_a_refusal_not_an_empty_inventory
  #        this file asserts the reader-level behaviour; the CLI-level refusal line is Task 4's
  ```

- [ ] **Step 4: Run the readers and the directly affected suites — expect PASS**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
       tests/test_artifact_root_readers.py tests/test_coverage_report.py tests/test_quality.py \
       tests/test_integrity.py tests/test_export.py tests/test_search_index.py -v
  ```

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
       tests/test_verify_baseline.py tests/test_persistence_scale.py -v
  ```

- [ ] **Step 5: Commit** the task's files (`feat(artifact-root): resolve artifact paths over both roots in the readers`).

**STOP conditions:** if `CoverageReport.build`'s signature no longer accepts `archive_root` first, STOP — the
readers' contract has moved and every selector in this task would grade a different call shape. If
`integrity.verify`'s `authoritative` flag can be flipped by an artifact-root condition in the code you are
writing, STOP — spec §10 requires it to remain a function of the state reads only. If a reader needs a *third*
base to pass its case, STOP — that is a contract defect (spec §5 fixes exactly two), not a test to widen.

---

### Task 4: The CLI surface, the end-to-end proof, and the operator documentation

**Effort (agent-oriented):** M

**Split point:** If the task does not close in one round, split as (1) `cli.py` + `tests/test_cli_artifact_root.py`
(the surface and the refusals), then (2) the three documentation files. The docs half has no code dependency on
the first half beyond the flag names spec §9 fixes.

**Files:**
- Modify: `src/bili_asr/cli.py` — the eleven `--artifact-root` arguments (beside the existing `--archive-root`
  lines at `:103`, `:122`, `:198`, `:251`, `:294`, `:335`, `:381`, `:388`, `:413`, `:424`, `:472`), the five
  `--keep-audio/--no-keep-audio` arguments (`:103`, `:122`, `:251`, `:294`, `:335`), one resolution step in
  `main()` (`:3255-3270`) between `parse_args` and the `archive_writer` block, and the artifact-root call
  sites inside the handlers of those commands.
- Create: `tests/test_cli_artifact_root.py`
- Modify: `README.md` — the command table (`:348-370`) gains the new flags on the commands that carry them, and
  a short "Where the artifacts go" section (the two roots, the precedence, the unmounted-mount caveat, the
  no-migration transition, and the `--max-audio-gb` interaction with retention as spec §12 Q1 states it).
- Modify: `docs/audio-retention-policy.md` — the default flips to retain; `--keep-audio/--no-keep-audio` and the
  `BILI_KEEP_AUDIO` truth table (`1` keep, `0` reclaim, other/absent → default) replace the current
  "set BILI_KEEP_AUDIO=1" framing.
- Create: `docs/artifact-root.md` — the operator guide: pointing the pipeline at a mount, what stays at the
  archive root and why, how an existing archive keeps working, how to move historical artifacts (the
  operator's own `mv`/`rclone`), the refusal lines, and the one-archive-root-per-artifact-root boundary.
- Modify: `tests/test_cli_help.py` — the new flags' presence on the eleven/five commands and their absence on
  the other six (always run with `-k "not installed"`, Global Constraints).
- Out of scope: every other source file (Tasks 1–3 own them), `{SPECS_DIR}` (frozen; spec §12 D19 records the
  revision the PM owes), `{KNOWLEDGE_DIR}`, the harness trees.

**Interfaces:**
- Consumes: Task 1's `roots_for`, `resolve_keep_audio`, `ArtifactRootError`; Task 2's and Task 3's keyword
  parameters verbatim (spec §11).
- Produces: `args.artifact_roots: ArtifactRoots` and `args.keep_audio: bool` on the namespaces of the commands
  that declare the flags; the two refusal lines of spec §9 with exit 1; the operator documentation.

**Current state to read before writing**

- The lock ordering the resolution step must sit inside — `main()` (`cli.py:3255-3270`): `parse_args` →
  (`_ARCHIVE_WRITER_COMMANDS` → `archive_writer(args.archive_root)`) → `_dispatch_command`. Resolution goes
  **between** the first two, so a refused invocation never creates `{archive_root}/coordinator/`.
- The command's own config-error style — `download-audio`'s missing selector (`cli.py:1200-1203`, prose +
  `return 1`) and `archive_busy` (`:3267-3269`, `<command>: <token>`): the refusal lines follow the second.
- The broad `except Exception` that must not swallow the refusal — `_cmd_coverage` (`:1634-1638`), which turns
  anything raised inside its try into `coverage: diagnostic coverage_report_unavailable`.
- The five reclaim sites that consume `keep_audio` — `_cmd_asr` (`:1925`), `_reclaim_after_archive`
  (`:1951-1958`), `_pilot_archive_subtitle` (`:1975`), `_pilot_archive_asr` (`:2061`), plus the coordinator's
  own `_reclaim_audio` (Task 2).
- The artifact-root call sites per handler — `download-audio` (`:1246-1248`, `:1253-1255`, `:1260-1272`),
  `asr` (`:1891`, `:1905-1911`, `:1915-1919`), `pilot` (`:2190-2196`, `:2212-2214`, `:2225-2228`),
  `run` (`:2571`), `schedule` (`:2744`, `:2766`, `:2782`), `campaign` (`:2398-2405`), `coverage` (`:1397`,
  `:1404-1417`, `:1464`, `:1634`), `verify` (`:3097`), `recover` (`:3113`), `export` (`:3077-3083`),
  `search` (`:2941` → `search_index.search`).
- Task 1/2/3 test files, for the fixture style the CLI cases reuse (`tests/test_coordinator.py` root building,
  `tests/test_coverage_report.py:85-110`).

- [ ] **Step 1: Write the failing CLI cases** in `tests/test_cli_artifact_root.py` (drive `cli.main([...])` and
      capture exit code + stdout/stderr, the style of `tests/test_cli_asr.py`):

  ```python
  # test_every_flag_carrying_command_uses_the_configured_artifact_root
  #        one parametrized case per command of spec §9: the artifact lands at the configured root
  # test_a_missing_configured_root_is_refused_with_the_pinned_line_and_exit_one
  #        "<command>: artifact root does not exist (<path>)" and nothing was created, for one writer and one
  #        reader command; the {archive_root}/coordinator/ directory is NOT created by the refusal
  # test_a_file_as_the_artifact_root_is_refused                     "… is not a directory (…)"
  # test_the_flag_wins_over_the_environment_variable                env points at a second root; the flag's wins
  # test_the_environment_variable_alone_is_enough                   no flag, env set -> artifacts there
  # test_unset_reproduces_todays_layout_byte_for_byte               no flag, no env -> every artifact under the
  #        archive root, and the same manifest lines as the identity case
  # test_an_explicit_flag_equal_to_the_archive_root_is_not_refused  the identity case (spec §3.3)
  # test_keep_audio_defaults_to_retain_and_no_keep_audio_reclaims
  #        archived row: audio still there; with --no-keep-audio: removed
  # test_keep_audio_env_precedence_table
  #        --keep-audio/--no-keep-audio > BILI_KEEP_AUDIO=1/0 > default retain
  # test_the_flag_is_absent_from_the_commands_that_do_not_touch_artifacts
  #        status/runs/fetch-meta/probe-subs/harvest-subs/derive-manifest --help does not list it
  # test_coverage_reports_the_same_inventory_with_and_without_the_root
  #        the Task 3 fixture, driven through the CLI, exits 0 both ways
  ```

- [ ] **Step 2: Run them — expect FAIL**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_cli_artifact_root.py -v
  ```

  Expected: `error: unrecognized arguments: --artifact-root`.

- [ ] **Step 3: Implement the CLI surface** — the arguments, the single resolution step in `main()`, and the
  call-site threading in each handler. The retention value is resolved once (`args.keep_audio`) and passed to
  every reclaim site; no handler reads the environment itself.

- [ ] **Step 4: Run the CLI cases and the shipped CLI regressions — expect PASS**

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
       tests/test_cli_artifact_root.py -v
  ```

  ```bash
  cd /root/workspace/bilibili-asr-archive/.worktrees/20260919-artifact-root/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
       tests/test_cli_help.py tests/test_cli_asr.py tests/test_cli_pilot.py tests/test_cli_derive_manifest.py \
       -k "not installed" -v
  ```

- [ ] **Step 5: Write the three documentation files** (`README.md`, `docs/audio-retention-policy.md`,
  `docs/artifact-root.md`) against spec §3–§9 and §12 Q1. `docs/artifact-root.md` must state plainly: the two
  roots and what lives in each; the precedence; that a configured root must already exist (and why an
  unmounted mount point is the operator's responsibility, spec §13); that an existing archive keeps working and
  that moving the historical artifacts is the operator's `mv`/`rclone`; the two refusal lines; the
  one-archive-root-per-artifact-root boundary; and Q1's `--max-audio-gb` interaction with retention. It must
  **not** claim a migration tool, a sync, or any state relocation.

- [ ] **Step 6: Verify the docs are self-consistent with the code** — re-read the three files against the
  shipped `--help` output for the affected commands and against spec §9's command table; a command list that
  disagrees with `--help` is a defect, not a wording preference.

- [ ] **Step 7: Commit** the task's files (`feat(artifact-root): add --artifact-root/--keep-audio and document the split`).

**STOP conditions:** if `main()` no longer wraps dispatch in the `_ARCHIVE_WRITER_COMMANDS` lock block, STOP —
the ordering "resolve before lock" is part of the operator contract (spec §9) and must be re-agreed, not
improvised. If a handler cannot pass the resolved roots without reading the environment itself, STOP — that
would put configuration resolution back into the library, which D15 forbids. If driving a command end-to-end
requires a real mount, a network call, or an installed (non-editable) package, STOP and report: that evidence
belongs to the separate E2E workflow, never to this plan (Global Constraints).

---

## PM rulings after Task 2 (2026-09-19) — plan gaps found by the implementer

**R1 — `CampaignRunner` needs `keep_audio`; accepted as a strict superset.** The task's `Produces` list named
`campaign.CampaignRunner(archive_root, *, ..., artifact_roots=None)` and "nothing else in the file", but
`cli._cmd_campaign` builds that runner and the runner is the only path to `RunCoordinator._reclaim_audio` — taken
literally, `campaign`'s own `--keep-audio/--no-keep-audio` (spec §7, D18) would have been **inert**. The
implementer added `keep_audio: bool = True` and forwarded it (two lines). **Ruling: accepted**, because a
documented flag that silently does nothing is worse than a two-line superset of a plan's interface list.
**T4 must pass `keep_audio=args.keep_audio` at `cli.py:2398-2405`.**

**R2 — the D5 flip's test blast radius was under-specified; T4 owns the repair.** `reclaim_audio`'s `keep` is
keyword-only and **required**, so `cli._reclaim_after_archive` (`cli.py:1956`) raises `TypeError` until T4 wires
it: measured `pytest tests/test_cli_asr.py tests/test_cli_pilot.py -q` → **13 failed, 21 passed**. Neither file is
in any task's `Files` list although both sit in T4's selector set, and `tests/test_long_live.py` (in T2's selector
set, owned by no task) asserted post-archive reclaim in two cases — the implementer **inverted those two
expectations minimally with an inline comment** because no CLI flag exists yet to express their intent.

**Rulings:**
- The inversion is accepted **as a mid-plan state only**. **T4's Files list gains `tests/test_cli_asr.py`,
  `tests/test_cli_pilot.py` and `tests/test_long_live.py`**, with the instruction to add `"--no-keep-audio"` to the
  two `main([...])` calls in `test_long_live.py`, **restore** the reclaim assertions there, and treat
  `tests/test_cli_pilot.py:156-157` the same way once the CLI wiring exists.
- Until T4 lands, `tests/test_cli_asr.py` and `tests/test_cli_pilot.py` are **known-red**: the failures are all
  `archive failed (TypeError)` from the unwired CLI, they are **not** T3's to fix, and the plan QC must read them
  as this ruling's consequence rather than as an unexplained regression.
- The budget **skip line is `cli.py:2217-2221`**, i.e. T4's Q1 clause (the implementing round confirmed it is not in
  T2's files).

---

## PM rulings after Task 3 (2026-09-19)

**R3 — `verify`'s grading base must probe BOTH bases per path (Important; fix loop on T3's slice).**
`integrity.py`'s `_graded_base` picked **one** base per row (the configured root, since `read_bases()` is
artifact-first) and probed the required paths and the raw document only there, while §10 requires probing both.
Reachable on the legacy harvested-caption shape: the identity run reports `['malformed_artifact',
'missing_transcript']` and the configured run reports `['missing_raw_subtitle','missing_transcript']` — **a true
defect hidden and a false one invented**, which is worse than either alone. It is not a clean→broken flip, which
is why the seat graded it Important rather than Critical. **Ruling: fix in T3's slice** (`integrity.py` plus
`tests/test_integrity.py` and `tests/test_artifact_root_readers.py`), because the defect is in the reader's
grading logic, not in the boundary.

**R4 — the §9 refusal does not cover an existing-but-unopenable configured root; T4 owns it.**
`integrity.py` silently dropped such a base (the seat's M1), and the boundary's refusal covers only
symlinked / missing / not-a-directory (`artifact_root.py`). **Ruling: T4's Files list gains
`src/bili_asr/artifact_root.py` for that one clause** — an existing directory the process cannot open is
"unusable" under D17 and must take the named exit-1 refusal rather than degrading to a dropped base — plus a
pin for it. T1's module is otherwise Approved and must not be re-opened beyond this clause.

**M2/M3/M4 — no code change owed; recorded so plan QC can see the reasoning.**
M2 (identity micro-deltas: a new partial declared-bundle `_safe_path` loop; `ArtifactRoots.of` receiving the raw
archive root) changes no legal row's verdict. M3 (unreachable fallbacks in `export.py`/`search_index.py`) and M4
(a lexical-vs-existence base mismatch for a recorded **absolute** value, which §5 already declares illegal) are
cleanup at best. If T4 touches those files for its own reasons it may take them; otherwise they ride to plan QC
as ledger items rather than as new work.

**R5 — the defect report does NOT name the base; the closed vocabulary stands.** The T3 fix round fixed I1 but
declined to add a base-bearing field, correctly flagging it instead of inventing one: the shipped vocabulary is
`IntegrityDefect(work_id, code)` / `to_dict → {"work_id","code"}` (rendered at `cli.py:3105`), and `diagnostics`
is a **closed code set** that feeds `recover --defect-code`. Naming the base would therefore be a report-vocabulary
change with exit-code consequences, not a local improvement. **Ruling: keep the closed vocabulary.** An operator
who needs the base already has both inputs (the row's recorded value and the configured root), and the fix's
observable promise — the *same* verdicts with and without a configured root — is what the criterion needs. If a
future round wants base attribution it must come with the vocabulary change spelled out, as its own plan.

**Also accepted, judged differently from the review and the reviewer should confirm it:** the fix declined the
seat's suggested "bundle-complete base as an ordering hint", on the ground that an ordering hint would mask a
defect that is real at the artifact base behind an intact copy elsewhere — which is exactly what the PM's pin
forbids. Reads follow strict `read_bases()` order and the bundle decides **completeness only**; §5's only disclosed
masking case is a base that *refuses* a candidate, not a regular file that fails to parse.

---

## PM rulings after Task 4 (2026-09-19) - the last task's four questions

**R6 - the refusal vocabulary is FOUR lines; `artifact root cannot be opened (<path>)` is accepted.** R4 required a
refusal for an existing-but-denied directory, and the implementer added a new tail rather than reusing one, on the
ground that neither "does not exist" nor "is not a directory" is true of that input and reusing one would weaken
the pin for the case it names. **Ruling: accepted**, and the spec's section 9 now lists four lines with a disclosure.
A message that is literally false is worse than a fourth vocabulary item, and each of the four names a distinct,
checkable condition.

**R7 - editing `tests/test_campaign.py` was authorised.** Seven of its cases build a fake `argparse` namespace and
call `cli._cmd_campaign` **directly**, bypassing `main()`; four broke once the handler reads the resolved values.
The implementer added the two fields to those namespaces rather than putting `getattr` fallbacks into production
code - **which is the right call**: a silent fallback is precisely the class of defect this iteration keeps removing
(cf. T2's `_mark_audio_ok`). Same precedent as `tests/test_persistence_scale.py` in the previous iteration: a file
the plan did not name, broken *by* the change, repaired minimally and disclosed.

**Accepted reading - section 4 governs writes, D8 governs reads.** The `asr`/`pilot` ASR stage reads a **recorded**
`audio_path` through the ordered bases even though section 4's write map sends the descriptor open to the artifact
root. A single-base read there would break D6 (legacy audio at the archive root), which is the promise the two-base
rule exists to keep. Recorded so plan QC does not read the asymmetry as an oversight.

**Owed by the PM (not by any task).** D19's `{SPECS_DIR}/asr-archive-cli.md` revision, now naming three rows: the CLI
surface gains `--artifact-root`/`--keep-audio`; the Outputs block's "cleanup flag is next-iteration scope" line is
**inverted** by D5's retain-by-default; and the module-boundary block gains `artifact_root.py`. The implementer
correctly recorded rather than wrote it, and correctly declined to put a harness-internal debt note into user docs.

**R8 - the Q1 hint is intentionally NOT added to the schedule path's skip line (PM accepted the implementer's
judgement).** Two sites print an `audio_budget` skip: the run path (`cli.py:2741-2752`, which now carries the clause,
from the shared `_AUDIO_BUDGET_SKIP_HINT`) and the schedule path (`cli.py:3007-3011`). The implementer declined the
second, and the reason is the same claim discipline this iteration has enforced throughout: in schedule's
`--allow-long-live` mode `--max-audio-gb 0` is **refused** by `long_live.refuse_disabled_audio_cap`, so "0 = unlimited"
would be **partly false advice** on that path. A hint that is false in one mode is worse than an absent hint; if an
operator later reports the confusion, the fix is a mode-aware clause, which is its own small change and not this
plan's. `campaign` prints `audio_budget` only inside a JSON `reason_codes` field, not as a skip line.

**Ledger leftovers (same class, not taken - outside the task's write scope, reported so plan QC sees them).**
`src/bili_asr/coordinator.py:533` repeats the "on another device" assumption in `_note_audio_peak`'s docstring (not
operator-facing output); the schedule skip line above. Neither changes behaviour.

---

## Review Gate Summary

**Verdict: approve** - plan QC tri-review (mandatory, N=3) over `cee0b94..2ee3bb5`, then **two** fix waves and two rounds
of re-verification over `2ee3bb5..c72ce43..62a316d`.

All three seats end at `Approve`: qc1 (architecture) and qc3 (reliability) from `Request Changes`, qc2 (correctness) from
the first re-review. The tri-review's **Critical** was reachable and read-only reproduced by qc1: `pilot` could not
archive a legacy row whose audio sat at the archive root once a root was configured (the ASR stage read over both bases
but re-confined against the write base alone) - a break of D6's "an existing archive keeps working". Two seats then
independently confirmed a **second route** to the same family on the download branch; the PM ruled it fixed rather than
registered (two of three seats called it blocking), and the fix preserved the self-heal order qc2 identified
(`_mark_audio_ok` writes before anything can raise - explicitly out of scope, `audio.py` untouched).

Consolidated: `{SDD_DIR}/20260919-artifact-root/review/qc-consolidated.md`; seats `qc1.md`, `qc2.md`, `qc3.md`.

**Two corrections the seats made to the PM's own text are recorded rather than absorbed:** the PM's R3 inference that a
0-byte stub makes the row fail closed was disproved by both re-review seats (the producers are validity-aware; the real
cost is one extra fast-path call), and the QA seat found R1's M3 clause describing pre-fix `reclaim_audio`.

## QA Gate Summary

**Verdict: approve with residuals** (`review/qa.md`, sha256 `ffb6c9e2535e84325bcfcd546e1809f21c4d87e70501276238978635f711a47b`)
- **QA gate: mandatory** (open `R#` on this plan + a behaviour change), **QA mode: targeted**.

All seven acceptance criteria pass on evidence the seat ran itself: **600 passed / 0 failed / 4 deselected** across 21
files (exceeding the implementers' 244-wide set, which it reproduced rather than trusted), plus three probes - the
resolution semantics, the four refusals through the real `cli.main` (with `{archive_root}/coordinator/` confirmed
uncreated), and a 17-command `--help` sweep matching the operator docs exactly (11 + 5, four refusal tails byte-identical,
cap-hint claims naming `run`/`pilot` only).

**Residuals disclosed and kept open:** `iter-2026-09-artifact-root · R1` (low, the write path's latent silent-no-upsert),
`· R2` (medium, the measurement hardening + fixtures + the two unreached `fail-closed` doc lines; must not be closed by
documentation alone), `· R3` (medium, five pairing sites + the validity-vs-existence divergence + S4). None is a
blocker-defer; no unresolved `critical`.

**Carried uncertainties (disclosed, not absorbed):** the existing-but-unopenable refusal rests on a shipped green pin and
a source read because the session runs as root (no EACCES to reproduce); R2's network-mount walk cost is unmeasured (no
mount); S4/S3 are citations only.

**PM owed at close:** the `{SPECS_DIR}/asr-archive-cli.md` revision (D19) - **done 2026-09-19** with this close (the CLI
surface note, the `artifact_root.py` leaf in the module boundary, and the cleanup line that D5 inverted).
