---
plan_id: 20260920-transcript-projections
iteration: iter-2026-09-transcript-projections
iteration_compass: .mstar/iterations/iter-2026-09-transcript-projections/delivery-compass.md
iteration_refs:
  - .mstar/iterations/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md
primary_spec: .mstar/iterations/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
---

# Publish stored transcripts as archive bundles (`bili-asr` projection command)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add one command that reads the transcripts `archive.db` already holds and publishes them as
complete archive bundles — the four artifact families (`srt`, `txt`, `md`, `raw`) plus the bundle
marker under the archive's configured artifact root — recording the row's state so the archive's own
readers (`archive_bundle_complete`, `verify --trusted-local`, `coverage`) agree it is done. Today the
caption path collects text and publishes nothing: `harvest-subs` stores segments and no command can
turn them into products, which is exactly why no row could reach `archived` in the 2026-09-20 live E2E.

**Closes:** **nothing on its own.** The charter row `e2e-23191782-season-7686105 · R1` (medium) is
discharged in its **projection half** by this plan; the live re-verification of the pair and the
register's other medium rows stay open (compass `## Roadmap Position`, and Acceptance Criterion 6). The
plan also carries the small folded-in fix for `e2e-23191782-longform-pair-webdav · R1` (the
`check-asr-env` anchor), which it **does** close when **Task 7** lands.

**Architecture:** A new command composed in `cli.py` (the repo's cross-layer rule: only `cli.py`
composes layers). It reads stored transcripts through a **read-only** connection, turns the store's
`transcript_segments` (`start_ms`/`end_ms`/`text`) into the `segments` shape the existing writer
consumes, and publishes through the **existing** `write_archive()` / `_publish_bundle()` path under
the archive's configured artifact root (`--artifact-root`, the `ArtifactRoots` value object). It is
**additive and idempotent**: a bundle the chain already published is never rewritten, a second run
changes nothing, and nothing is written back into `archive.db`. The ASR/audio chain
(`coordinator.py`, `audio.py`, `asr.py`) and its manifest contract are **not** touched — this
publishes what the store has; it does not move the chain onto the store.

**Sealed architecture (architect round 2026-09-20).** Contract: `{ITERATION_DIR}/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md` — every claim below is that contract's, at `file:line`, pinned to `013a507`. The projection composes entirely in `cli.py` (the cross-layer rule, `{SPECS_DIR}/asr-archive-cli.md:61`, the `derive-manifest` shape): a **read-only** store connection (`mode=ro`, `cli.py:680-716`, `:748-802`) → `TranscriptRepository.list_stored_transcripts()` (**new**, contract §2.1: one row per stored transcript version with its part context, **no** `processing_status` predicate, locked order `bvid, page_index, source_kind, language, version DESC`) → a **pure** service `services/transcript_projection.py` (**new**, contract §3: winner selection, ms→s mapping, row builder — no I/O, no archive import, mirroring `services/manifest_derivation.py`) → `TranscriptRepository.read_transcript(...)` for the winner's body (`database.py:1023-1075`) → the **existing** writer path: `archive.bundle_paths()` (**new public extraction of `archive.py:465-471`**, the bundle-name rule's one home), `archive_bundle_complete()` (`archive.py:170-206`), `write_archive(..., source=<stored source_kind>)` (`archive.py:452`, `raw=None`) → `ManifestStore.upsert` (`manifest.py:261-296`).

Identity is `archive_stem`'s `{bvid}.p{page_index}` (`archive.py:34-38`); the winner is the minimum over *(kind rank `subtitle-cc` → `subtitle-ai` → `asr-local`, family `zh` → `en` → other, language code, `version` DESC)* — total by the store's `UNIQUE (video_part_id, source_kind, language, version)` (`schema-transcripts.sql:25`); segments become `{"start": start_ms / 1000, "end": end_ms / 1000, "text": text}`; the recorded row is `status: archived` + the four root-relative `*_path` values + `source`/`language` (fifteen keys, contract §5.1), and a candidate is `already_published` **iff** its effective row declares all four paths and `archive_bundle_complete` confirms them at the write base — then nothing is written at all (contract §5.4). The store is never written; a later transcript version changes no published byte (next-version drift non-goal).

Contract section map: §1 what it fixes · §2 candidates + selector + "unknown `--bvid`" · §3 identity, winner rule, ms→s, `duration_s`/`pubdate_str` · §4 the nine frontmatter keys, the deliberate omissions, the `raw` sidecar · §5 recorded state, the `already_published` predicate, half-written bundles, the readers' agreement · §6 `asr-local` (in range, provenance deferred) · §7 the operator surface and the literal `--help` content · §8 modules, interfaces, affected readers · §9 risks and rollback · §10 the validation plan and Fixture F · §11 disclosures the published surfaces must carry · §12 the F4 anchor fix · §13 what the frozen spec owes (PM) · §14 deferrals.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, pytest 9 (`bilibili-asr-archive/.venv/bin/python`), the
repo's own `TranscriptRepository` / `ManifestStore` / `ArtifactRoots` / `archive.py` modules. No new
dependency.

**Execution:** mstar-sdd

**Main worktree branch**: `main` (the control root stays on `main`; the plan's feature work happens on
the plan's worktree branch created in Phase 2).

## Global Constraints

- **Two roots, and every command names its working directory.** The **repository root** is
  `/root/workspace/bilibili-asr-archive` (holds `.git`, `.mstar/`, `.worktrees/`, and the package
  directory `bilibili-asr-archive/`); the **package root** is `<repo-root>/bilibili-asr-archive`
  (holds `.venv/`, `src/`, `tests/`). Python and pytest always run from a **package root**.
- **Where the code under test lives.** Phase 2 executes in a linked worktree of this repository. That
  worktree has **no `.venv`** (gitignored, so `git worktree add` does not carry it) and the control
  root's `.venv` is an *editable* install whose `.pth` points `bili_asr` at the **control root** `src` —
  so an unpinned run silently grades the unmodified tree (this repo keeps a knowledge doc about
  exactly that trap). Every task therefore runs the pinned form and confirms the resolved path first:

  ```bash
  cd <worktree>/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v
  cd <worktree>/bilibili-asr-archive \
    && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -c \
       "import bili_asr, pathlib; print(pathlib.Path(bili_asr.__file__).resolve())"
  ```

- **No local full-suite run.** The suites named in the tasks are the whole local evidence budget; the
  full suite is CI's. Reuse unaffected evidence with its original range; do not re-run checks because
  HEAD moved. Never assign real-browser/device/installed-deployment E2E evidence as a task or a gate of
  this plan (compass D5); the live re-run is a separate workflow.
- **Do not edit:** `{KNOWLEDGE_DIR}/**` (Phase 1/2 never add knowledge), `{SPECS_DIR}/asr-archive-cli.md`
  **except** for the two mechanical items compass **D15** authorises in Task 6 (the added-command enumeration
  and the `--artifact-root` count; the PM sign-off that file's own change policy requires is recorded in D15 —
  no exit-taxonomy line, no requirement text, no behaviour, and any *wider* revision stays the PM's to raise),
  `{HARNESS_DIR}/workflows/**`,
  `status.json`, the register, any other plan or compass. Documentation edits are limited to the files
  the architecture pass names for the "publish the boundary" task, as widened by D15.
- **Fixtures only, no live network.** Every check runs offline against a disposable archive root built
  in a temp dir (never a real `archive/`). The projection command must not open a socket; if the
  implementation needs network to satisfy a check, the check is wrong.
- **Drift check before Task 1** (plan written at `013a507`):
  `git -C /root/workspace/bilibili-asr-archive diff --stat 013a507..HEAD -- bilibili-asr-archive/src/bili_asr/cli.py bilibili-asr-archive/src/bili_asr/archive.py bilibili-asr-archive/src/bili_asr/storage/ bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/README.md bilibili-asr-archive/docs/metadata-storage.md`.
  If any in-scope file changed, re-read the current-state excerpts the spec pins before proceeding; on
  a mismatch, STOP and report.

## Prepare gates

| Gate | State | Evidence |
|------|-------|----------|
| **specify** | done | The direction is user-locked 2026-09-20 and recorded in the compass `## Scope` + `## Decisions` D1–D8; the register row `e2e-23191782-season-7686105 · R1` is the charter. |
| **clarify** | done (Q1 → compass **D10** by the product-manager round; Q2/Q3 → **D11/D12**, Q4 → **D13** by the architect round; **Q5 → D14** by the writing-specialist round — all five withdrawn from `## Open Questions`) | No row with a chain owner and no chain-owned marker is left. Q5's answer (D14) names the sentences that move in `README.md` and `docs/metadata-storage.md` and the two claims outside the T6 bound; those two are the compass's non-blocking `PM` rows **Q6** (the frozen spec's owed revision) and **Q7** (`docs/artifact-root.md`'s count and lists). |
| **plan** | done (architect round) | `specs/transcript-projection-contract.md` §1–§14 written and sealed; the sealed architecture paragraph above carries the module split, the repository calls and the section map at `file:line`; `## Tasks` holds T1–T7 with Files/Interfaces/Verification/dependency waves; `## Done criteria` filled; compass D11/D12/D13 record the converged answers. |
| **primary_spec** | declared, file landed | `primary_spec` = `.mstar/iterations/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md`; the file exists and is the plan's only spec. |
| **blocked_by / dependencies** | none | `blocked_by: []`; the plan depends only on the store's existing shape (read-only) and the existing archive writer. Task order is fixed by `## Tasks`' dependency waves (A: T1/T2/T3/T7 · B: T4 · C: T5/T6). |

## Operator surface (product — compass D10)

Fixed so no task re-opens it; the full decision, its rationale and the rejected alternatives are compass
**D10**. Everything below is the operator-facing contract of the new command.

```text
bili-asr publish-transcripts [--bvid <bvid[:pN]>] [--limit-parts N]
                             [--archive-root <root>] [--artifact-root <root>]
```

- **Range** — with no selector, every stored part that holds a transcript, whatever its
  `processing_status` (a `gone` part still holds local text). `--bvid` follows the shipped
  `_subtitle_selector` rule: bare `bvid` = every stored part of that video, `bvid:pN` = exactly that part;
  a selector that names no stored part is the configuration error
  `publish-transcripts: unknown --bvid <value>`, exit 1. `--limit-parts N` bounds the run in **parts** and
  must be positive (a non-positive value is exit 1, as in `probe-subs`). "All pending parts" is **not**
  the range: *pending* is the store's word for "holds no transcript" (`v_pending_subtitles`, the derived
  audio queue), and those parts have nothing for this command to publish.
- **Prints** — one line per candidate, in a deterministic order:
  `<work_id>: published (source=<source_kind> lang=<language> version=<v> cues=<n>) <md path>`,
  `<work_id>: already_published`, or `<work_id>: failed (<reason>)`; then the closing counts line
  `publish-transcripts: candidates=<n> published=<n> already_published=<n> failed=<n>`, carrying every
  count including the zeros (`derive-manifest`'s shipped form). The `<md path>` is printed in the
  root-relative form the archive already records; it is the one product name the store cannot derive.
- **Exit** — `0` when every candidate is published or already published, including no candidate at all;
  `1` for a usage/configuration error, a refused archive state (missing/unreadable `archive.db`, a store
  predating the transcript schema, a held writer lock), or a candidate whose bundle could not be
  published (that part is named and the counts line still prints); **`2` is never produced** (no socket
  is opened, and `_UsageErrorArgumentParser` maps usage errors to 1). No new exit value: the compass
  `## Non-Goals` no-new-exit-code entry, and the frozen exit table needs no revision.
- **`--artifact-root`** is carried like the other product-writing commands (flag wins over
  `BILI_ARTIFACT_ROOT`; unset = the archive root).
- **Disclosures the operator surface must carry** (compass criterion 6 checks them): the command publishes
  stored transcripts and fetches nothing; a published product is never replaced when the store later gains
  a newer transcript version; and a row that already carries an earlier manifest state is outside what the
  archive's readers currently agree on (`e2e-23191782-season-7686105 · R2`, high — compass
  readers' append-only-history non-goal).

## Engine lifecycle

Who advances this plan row's engine state, and what records each transition:

- **Intended scoped sequence** (frozen contract): `bind --coordinator` → `prepare` → `bind` → `progress`
  → `handoff` → `accept` → `integration-start` → Git merge → `integration-accept` → `complete`.
- **This environment's substitution (compass D9):** no `mstar` CLI is installed on the control host, so
  each transition is written by hand to the frozen contract's schema **and validated with the engine's
  own validator (`validateWorkflowSnapshot` / `validateWorkflowEntry` / `validateResidual`) before it
  is treated as landed**. A transition is never claimed from prose alone. Installing
  `@mstar-harness/cli` would replace the substitution and is an operator decision.
- **Evidence order** — `compound` disposition, PR identity and merge evidence are recorded **after** the
  row is `Done`; the delivery tail runs on a completed row, never ahead of it.
- The snapshot declares the integration anchors (`branch.base = main`, `branch.integration =
  iteration/iter-2026-09-transcript-projections`, `branch.target = main`).

Semantics and failure behaviour → `mstar-artifacts/references/plan-workflow-lifecycle-contract.md`; PM
step sequence → `mstar-roles/references/project-manager/plan-management.md`.

---

## Tasks

Seven tasks, one business deliverable. **Contract for every task:**
`specs/transcript-projection-contract.md`. Code and test paths below are **package-root-relative**
(`src/…`, `tests/…`, i.e. relative to `bilibili-asr-archive/`); the two documentation files T6 may edit are
written **repo-root-relative**, exactly as compass criterion 6(b)'s check command spells them. **Pinned
invocation for every pytest selector** (Global Constraints; `<selector>` is the file list in the task's
Verification line):

```bash
cd <worktree>/bilibili-asr-archive \
  && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v
```

**Dependency waves** — wave A (all four ready in parallel, no shared write target): **T1, T2, T3, T7**;
wave B: **T4** (needs T1 + T2 + T3); wave C (parallel): **T5, T6** (both need T4). No task holds a gate on a
real-device run (compass D5).

### Task 1: `archive.bundle_paths` — the bundle-name rule gets one home

**Effort (agent-oriented):** XS

**Split point:** not splittable; if the extraction and its case do not close in one round, land the extraction
alone (the existing archive/artifact-root suites are the regression gate) and put the case in the same round as
T4.

**Files:**
- Modify: `src/bili_asr/archive.py` — extract the inline path computation of `write_archive`
  (`archive.py:465-471`) into a public `bundle_paths(root, entry) -> dict[str, Path]` and call it from
  `write_archive`; no behaviour change (`write_archive` still returns the root-relative strings, `archive.py:488`).
- Modify: `tests/test_archive_md.py` — one new case.
- Out of scope: `integrity.py` (its `_canonical_required_paths`, `:567-584`, is the reader's independent
  re-derivation and already imports `_safe_name`, `:14`), `cli.py`, `storage/**`.

**Interfaces:**
- Produces (verbatim, for T4): `def bundle_paths(root: str | os.PathLike[str], entry: dict[str, Any]) -> dict[str, Path]`
  returning the four keys `srt_path`/`txt_path`/`md_path`/`raw_path`.
- Honours: contract §3.1 — stem from `archive_stem`, md name `"{pubdate_str}_{stem}_{_safe_name(title)}.md"`,
  `dirs = root/transcripts/{srt,txt,md,raw}`.

**Verification:** `tests/test_archive_md.py` — new case
`test_bundle_paths_names_the_four_families_and_the_derived_md_name` (the four absolute paths under the given
root; the md name's `{pubdate_str}_{stem}_{safe_title}` form including a title needing `_safe_name`; the
`unresolved`/missing-`cid` stem fallback unchanged). Existing cases in the file must stay green — the extraction
may not change any published name.

**Dependency position:** wave A, ready in parallel with T2/T3/T7. T4 consumes it.

- [ ] **Step 1:** Add the failing case; **Step 2:** run it (expect FAIL: `AttributeError`/import error);
      **Step 3:** extract `bundle_paths` and rewire `write_archive`; **Step 4:** run `tests/test_archive_md.py -v`
      (expect PASS); **Step 5:** commit (`refactor(archive): one home for the bundle's file names`).
- **STOP conditions:** if any published name changes for an existing fixture, STOP — the extraction is a
  behaviour change, not a refactor.

### Task 2: The repository read — the stored-transcript relation

**Effort (agent-oriented):** S

**Split point:** if the read and its cases do not close in one round, split the selector arm (`bvid`/`page_index`)
from the no-selector arm; both arms share the one query and the locked order, so nothing is re-derived at the split.

**Files:**
- Modify: `src/bili_asr/storage/database.py` — add `TranscriptRepository.list_stored_transcripts(bvid=None, page_index=None)`
  beside `list_selected_parts` (`:1174-1203`) and `read_video_pubdates` (`:1133-1164`).
- Modify: `tests/test_transcript_repository.py` — the new cases.
- Out of scope: `cli.py`, `services/**`, `manifest.py`, `archive.py`.

**Interfaces:**
- Produces: `list_stored_transcripts(self, bvid: str | None = None, page_index: int | None = None) -> list[sqlite3.Row]`
  — contract §2.1's query verbatim, one row per stored transcript version, keys `video_part_id`, `bvid`,
  `page_index`, `cid`, `part_title`, `duration_ms`, `pubdate`, `transcript_id`, `source_kind`, `language`,
  `model_id`, `version`, `content_sha256`, `created_at`; **no** `processing_status` predicate; order
  `bvid ASC, page_index ASC, source_kind ASC, language ASC, version DESC`; read-only.
- Consumed by T3 (as mappings) and T4.
- Honours: contract §2, §2.1, §2.2 (validation discipline of the module: `_text`/`_integer`, `database.py:1763`'s
  house pattern).

**Verification:** `tests/test_transcript_repository.py` — new cases:
`test_list_stored_transcripts_returns_one_row_per_version_with_part_context`,
`test_list_stored_transcripts_order_is_locked_and_deterministic`,
`test_list_stored_transcripts_includes_a_gone_part_that_holds_a_transcript`,
`test_list_stored_transcripts_excludes_a_part_without_a_transcript`,
`test_list_stored_transcripts_selector_narrows_to_one_part_or_one_video`,
`test_list_stored_transcripts_of_an_empty_store_is_empty`,
`test_list_stored_transcripts_arguments_follow_the_module_validation_discipline`.

**Dependency position:** wave A, ready in parallel with T1/T3/T7. T4 consumes it.

- [ ] **Steps 1–5** as T1 (write failing cases → run FAIL → implement → run PASS → commit
      `feat(storage): read the stored transcript relation for the projection`).
- **STOP conditions:** if the transcript schema no longer enforces `UNIQUE (video_part_id, source_kind, language,
  version)` (`schema-transcripts.sql:25`), STOP — the winner rule's totality rests on it.

### Task 3: The pure projection service — winner, conversion, row

**Effort (agent-oriented):** S

**Split point:** split at the conversion boundary if needed: (1) `ordered_candidates` + its cases (the winner
rule), then (2) `writer_segments` + `projection_row` + their cases. Both halves are pure and take fabricated
mappings, so nothing is re-derived at the split.

**Files:**
- Create: `src/bili_asr/services/transcript_projection.py` (pure: no I/O, no `archive`/`manifest`/`cli` import).
- Create: `tests/test_transcript_projection.py`.
- Out of scope: every other module. `services/` may import stdlib, `bili_asr.page_identity`,
  `bili_asr.storage.models` (types only, the `subtitle_ingest.py:48-54` precedent) and
  `bili_asr.services.manifest_derivation` (for `duration_s_from_ms`).

**Interfaces:**
- Produces (verbatim, for T4):

  ```python
  ARCHIVED_STATUS = "archived"
  SOURCE_KIND_RANK = {"subtitle-cc": 0, "subtitle-ai": 1, "asr-local": 2}
  LANGUAGE_FAMILY_ORDER = ("zh", "en")          # declared, not imported (§3.2 key 2)

  @dataclass(frozen=True)
  class Candidate:
      work_id: str
      part: Mapping[str, Any]         # the §2.1 part keys
      transcript: Mapping[str, Any]   # the winning identity keys

  def ordered_candidates(rows: Iterable[Mapping[str, Any]], limit: int | None = None) -> tuple[Candidate, ...]
  def writer_segments(segments: Sequence[TranscriptSegmentRecord]) -> list[dict[str, Any]]
  def projection_row(part, transcript, paths) -> dict[str, Any]
  ```
- Honours: contract §3.2 (the total order), §3.3 (`start_ms / 1000`), §3.4 (`duration_s_from_ms`,
  `strftime(..., gmtime(pubdate))`), §5.1 (the fifteen-key row), §6 (no kind filter, no invented provenance).
  `ordered_candidates` validates `limit` like `list_pending_subtitle_parts` (`database.py:1115-1119`);
  `writer_segments` raises `ValueError` on an empty sequence (the contract's `empty_transcript` branch).

**Verification:** `tests/test_transcript_projection.py` — named cases:
`test_the_winner_is_the_uploader_caption_over_the_machine_caption`,
`test_the_winner_is_the_latest_version_of_the_chosen_identity`,
`test_the_language_family_order_ranks_zh_before_en_and_the_code_breaks_the_tie`,
`test_ordered_candidates_yields_one_candidate_per_part_in_the_locked_order`,
`test_limit_parts_bounds_parts_not_transcript_rows`,
`test_writer_segments_convert_ms_to_seconds_and_leave_the_text_alone`,
`test_a_zero_segment_body_is_refused_rather_than_published_empty`,
`test_projection_row_carries_the_declared_fifteen_keys_and_the_derived_field_set`,
`test_the_declared_language_family_order_matches_the_harvesters`,
`test_an_asr_local_row_is_mapped_without_inventing_provenance` (fabricated input).

**Dependency position:** wave A — ready in parallel with T1/T2/T7, because every case takes fabricated mappings
(no database); the row-key list it produces is the contract's (§5.1), so T2 landing does not move it.

- [ ] **Steps 1–5** as T1 (commit `feat(services): decide and shape the transcript projection`).
- **STOP conditions:** if `read_transcript`'s segment type (`TranscriptSegmentRecord`, `database.py:1205-1222`)
  no longer exposes `start_ms`/`end_ms`/`text`, STOP — T4's call and this conversion are pinned to it.

### Task 4: The command — `bili-asr publish-transcripts`

**Effort (agent-oriented):** M

**Split point:** if the wiring and the CLI test file do not close in one round, split (1) argparse + dispatch +
lock membership + the composition loop, (2) the printed/summary shapes and the exit taxonomy cases. The command
name, flags and lines are D10's and are not re-decided at the split.

**Files:**
- Modify: `src/bili_asr/cli.py` — the `publish-transcripts` subparser (name, `description`, the four flags, the
  `--help` substrings of contract §7), `_cmd_publish_transcripts`, the `_dispatch_command` arm
  (`cli.py:3434-3473`), `_ARCHIVE_WRITER_COMMANDS` (`:3420-3431`), and the `_ARTIFACT_ROOT_HELP` comment's
  command count `eleven` → `twelve` (`:38`).
- Create: `tests/test_cli_publish_transcripts.py` (the `tests/test_cli_derive_manifest.py` shape: store built
  through the repository APIs, command driven through `bili_asr.cli.main`).
- Modify: `tests/test_cli_help.py` and `tests/test_cli_artifact_root.py` — the same count and the same list live in
  both files' `--artifact-root` matrices (`test_cli_help.py:1112-1116`, `test_cli_artifact_root.py:53-66`). Both move
  to twelve and `publish-transcripts` joins both tuples, which puts the new command inside the two shipped matrices
  (its help names `--artifact-root`, `BILI_ARTIFACT_ROOT` and "default: the archive root", and it carries no
  retention pair); neither file needs a new case, both matrices are parametrized.
- Out of scope: `archive.py` (T1 owns it), `storage/**` (T2), `services/transcript_projection.py` (T3),
  `manifest.py`, `integrity.py`, the readers.

**Interfaces:**
- Consumes: T1's `bundle_paths`; T2's `list_stored_transcripts` + `list_selected_parts` +
  `read_transcript`; T3's `ordered_candidates`/`writer_segments`/`projection_row`;
  `_open_subtitle_connection(..., read_only=True)` (`cli.py:748-802`); `roots_for` through `main()`'s existing
  resolution (`:3490-3495`); `archive_bundle_complete`, `write_archive`; `ManifestStore.upsert`.
- Produces: contract §7's three per-candidate lines and the summary line; the §5.1 row; the exit stance
  (`0`/`1`, never `2`).
- Honours: contract §5.4 (the `already_published` predicate and its write-base probe), §5.5 (the five states the
  fixture discriminates — the `gone` part of §2 is published too), §5.6 (read-only store, verify-after-publish,
  no row for an unconfirmed publication), §7 (lines, reasons, lock, `--artifact-root`), §11 (disclosures in `--help`).

**Verification:** `tests/test_cli_publish_transcripts.py tests/test_cli_help.py tests/test_cli_artifact_root.py` — named cases:
`test_publish_transcripts_publishes_one_stored_caption_as_a_complete_bundle`,
`test_publish_transcripts_prints_the_summary_with_every_count_including_zeros`,
`test_publish_transcripts_is_idempotent_and_the_second_run_touches_nothing`,
`test_publish_transcripts_leaves_a_chain_archived_bundle_byte_identical`,
`test_publish_transcripts_republishes_a_bundle_whose_marker_is_missing`,
`test_publish_transcripts_reports_failed_and_exits_one_on_a_stale_staging_directory`,
`test_publish_transcripts_opens_the_only_connection_read_only`,
`test_publish_transcripts_unknown_bvid_is_exit_one_and_writes_nothing`,
`test_publish_transcripts_a_known_bvid_holding_no_transcript_is_zero_candidates`,
`test_publish_transcripts_non_positive_limit_parts_is_exit_one`,
`test_publish_transcripts_help_names_the_range_and_the_disclosures`,
`test_publish_transcripts_holds_the_archive_writer_lock`,
`test_publish_transcripts_records_the_fifteen_key_row_the_readers_read`,
`test_publish_transcripts_writes_products_under_the_artifact_root_and_state_at_the_archive_root`.

**Dependency position:** wave B — strictly after T1 + T2 + T3 (it composes all three).

- [ ] **Steps 1–5** as T1 (commit `feat(cli): publish stored transcripts as archive bundles`).
- **STOP conditions:** if `_UsageErrorArgumentParser` (`cli.py:83-93`) no longer maps argparse's `2` to `1`,
  STOP — D10d's "never `2`" would become false.

### Task 5: The readers agree — Fixture F end to end (compass criteria 1–4)

**Effort (agent-oriented):** M

**Split point:** if the fixture and the reader checks do not close in one round, split (1) the fixture builder +
states (i)/(ii)/(v) with criteria 1–2, (2) states (iii)/(iv) with criterion 2's drift and heal cases + criterion 3's
reader checks. The fixture builder stays with slice (1).

**Files:**
- Create: `tests/test_published_projection_readers.py` (the `tests/test_derived_queue_chain.py` shape: an
  integration file over the shipping commands).
- Out of scope: `src/**` — this task proves, it does not change product code; a defect found here returns to the
  owning task's contract section (contract §9).

**Interfaces:**
- Consumes: T4's command, then the shipped readers through `bili_asr.cli.main`: `verify --trusted-local`
  (`cli.py:3310-3328`), `coverage --quality --format json` (`:1466+`), `derive-manifest` (`:1172-1276`).
- Produces: the evidence for compass criteria 1, 2, 3, 4 over **Fixture F** — five states (i)–(v), an **empty
  `F/coordinator/attempts.jsonl`** (contract §5.3: `verify` exits `0` only when defects *and* diagnostics are
  empty), one manifest row per `work_id`, and a caption body carrying no advisory content code (contract §10).

**Verification:** `tests/test_published_projection_readers.py` — named cases:
`test_verify_counts_the_projected_row_complete_and_absent_from_defects` (exit `0`, `defect_count: 0`,
`diagnostics: []`),
`test_coverage_quality_reports_no_reason_for_the_projected_row` (`reasons == []`, `artifact_count == 4`,
`cue_count == 2 × segments`, the row in `summary.valid_work_items`),
`test_the_projected_md_and_sidecar_carry_no_asr_key_and_name_the_stored_source` (criterion 4's inverted check,
on the file's text this time),
`test_derive_manifest_queue_is_unchanged_by_the_projection`,
`test_a_second_stored_version_leaves_the_published_bytes_identical` (state (iii)),
`test_a_gone_part_holding_a_transcript_is_published` (state (v)).

**Dependency position:** wave C — after T4; parallel with T6 (different files, no shared target).

- [ ] **Steps 1–5** as T1 (commit `test(projection): the archive's own readers agree the row is done`).
- **STOP conditions:** if `verify`'s exit still depends on a diagnostic this fixture cannot supply, STOP and
  return to contract §5.3 — do not relax the assertion to make it pass.

### Task 6: Publish the boundary (the only documentation task)

**Effort (agent-oriented):** S

**Split point:** the two files are independent; if one round cannot hold both, land `README.md` first (it is the
operator's entry point), then `docs/metadata-storage.md`.

**Files** (the complete set this iteration may edit — plan Global Constraints and contract §11):
- Modify: `bilibili-asr-archive/README.md` — the `## Workflow` boundary paragraph (`:333-345`), the
  "Legacy manifest boundary" bullet (`:1006-1012`), the derived-audio-queue section's "Does not do" and
  "Limits, stated" bullets (`:1049`, `:1090-1096`), the artifact-path count sentence in the command surface
  (`:374`, "eleven commands" → twelve — D14; the block above it, `:348-371`, is the list that sentence counts, so the
  new command's bracketed line belongs there too), and a new subsection beside the derived audio queue for
  `bili-asr publish-transcripts` (surface, what it reads/writes, what it does not do, the disclosures).
- Modify: `bilibili-asr-archive/docs/metadata-storage.md` — the "still deferred" bullet (`:318-321`) and the
  opening claim that neither subtitle command writes an on-disk projection (`:331`).
- Modify: `bilibili-asr-archive/docs/artifact-root.md` — the same `--artifact-root` command count and the same
  eleven-command list (`:89-103`); **added by compass D15** (PM decision at the lock, resolving Q7).
- Modify: `{SPECS_DIR}/asr-archive-cli.md` — the added-command enumeration (`:42-44`) and the `--artifact-root`
  count (`:45`, `eleven` → `twelve`, naming `derive-manifest` and `publish-transcripts`); **the frozen spec's owed
  revision, authorised by compass D15** under its own change policy (PM sign-off recorded there). Mechanical only:
  no exit-taxonomy line, no requirement text, no behaviour.
- Out of scope: `{KNOWLEDGE_DIR}/**`, every other `docs/` file, any other iteration's package. `{SPECS_DIR}` is in
  scope **only** for the two items D15 names.
- **Q5's answer is compass D14 and the bound is widened by D15**: the four files above are the complete set; D14's
  third claim set (`docs/artifact-root.md`) and the frozen spec's owed revision are now this task's (PM decision at the lock).

**Interfaces:**
- Honours: contract §11's disclosure table (range = stored transcripts, fetches nothing; a complete published
  bundle is never replaced and a newer stored version does not change it; a row carrying an earlier manifest state
  is outside what the readers agree on; one bundle per part; the legacy `subtitle_done` republish; `asr-local`'s
  provenance gap). Every sentence must be no wider than the mechanism it describes
  (`{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md`).

**Verification (non-executable docs — static, no manufactured test):**
`rg -n 'publish-transcripts' bilibili-asr-archive/README.md bilibili-asr-archive/docs/metadata-storage.md` exits
`0` and the matched lines are the moved boundary text (compass criterion 6b, D14): no match may still state that no
SRT/TXT/MD projection exists, and the text must say what stays unpublishable; the `:374` count sentence reads
twelve, and the same count sentence in `docs/artifact-root.md` reads twelve; the frozen spec's enumeration names both
new commands and its count reads twelve. Regression: `README.md` is one of the two published copies `tests/test_check_asr_env.py:124-138`
(`test_the_published_copies_name_the_five_stages_in_the_script_s_order`) pins, so the pinned pytest run over that
file must stay green — the second pinned copy is `docs/wsl-rocm-gpu.md`, **not** `docs/metadata-storage.md`, whose
only check is the static `rg` above.

**Dependency position:** wave C — after T4 (the command must exist to be described); parallel with T5.

- [ ] **Steps (scoped-check, per the plan template's non-executable path):** record
      `Verification mode: scoped-check` with the before/after `rg` outputs and the pinned pytest result in the
      task handoff; **commit** `docs(projection): publish the transcript-projection boundary`.
- **STOP conditions:** if a sentence cannot be made true without changing behaviour, STOP and return it to the
  contract — do not soften the code's claim by editing the doc alone.

### Task 7: The folded-in F4 fix — `check-asr-env` from any working directory

**Effort (agent-oriented):** XS

**Split point:** not splittable; the anchor and its one test are one change.

**Files:**
- Modify: `src/bili_asr/cli.py` — `_cmd_check_asr_env`: `parents[3]` → `parents[2]` (`cli.py:3229`), and the
  comment (`:3228`) and docstring (`:3210-3214`) corrected to the same arithmetic (`src/bili_asr/cli.py` →
  package root → `scripts/`). Candidate order (override → package anchor → cwd) and the exit contract unchanged.
- Modify: `tests/test_check_asr_env.py` — **one** new case.
- Out of scope: `scripts/check_asr_env.py` itself, its stage vocabulary and its remediation text (D6: the anchor
  plus one test, nothing wider).

**Interfaces:**
- Honours: contract §12; compass criterion 5. The test drives the shipped entry point
  (`bili_asr.cli.main(["check-asr-env"])`) with `BILI_ASR_CHECK_SCRIPT` deleted and the cwd set to a directory
  that is neither the package root nor the repo root, and asserts the **located-script** outcome (five `check:`
  lines, one `asr-env:` verdict line, `no check script found` absent, exit `0`/`1` per host) — the assertion the
  pre-fix anchor fails.

**Verification:** `tests/test_check_asr_env.py` — new case
`test_the_cli_finds_the_check_script_from_any_working_directory`, plus the whole file green (its existing
end-to-end case already runs the script on this host).

**Dependency position:** wave A — independent of every other task (different handler, different test file).

- [ ] **Steps 1–5** as T1 (write the failing case → run FAIL → move the anchor → run PASS → commit
      `fix(cli): anchor check-asr-env at the package root so it runs from any cwd`).
- **STOP conditions:** if `scripts/check_asr_env.py` is not at `<package root>/scripts/` in the checkout the test
  runs in, STOP — the anchor's correct value has moved and the contract's §12 arithmetic must be re-derived.

## Done criteria

Filled by the architecture pass, then checked by the PM before `status: locked`.

| # | Done criterion | Where it is checked |
|---|----------------|---------------------|
| 1 | Every task block carries its **Files** (exact paths) and its **Verification** (the pinned pytest invocation + the named cases), and the F4 fix exists as its own small task with a cwd-independent test | T1–T7 above; T7's Verification line |
| 2 | The six compass acceptance criteria map onto named tasks | criteria 1–4 → **T5** (with T1–T4 as their mechanism); criterion 5 → **T7**; criterion 6 → **T4** (`--help` text) + **T6** (the two named doc files) + the compass's own `## Roadmap Position` read (PM) |
| 3 | The contract is sealed, declared as `primary_spec`, and resolves Q2/Q3/Q4 (now D11/D12/D13) with `file:line` evidence | `specs/transcript-projection-contract.md` §3–§6; plan frontmatter `primary_spec`; compass D11/D12/D13 |
| 4 | No task or gate depends on real-browser/device/installed-deployment E2E evidence (compass D5) | every Verification line names a pytest selector or a static doc check; the live re-run stays a separate workflow |
| 5 | Documentation edits are bounded to the files the architecture pass named | plan Global Constraints + T6's Files + contract §11 (exactly `README.md` and `docs/metadata-storage.md`; the two claims D14 places outside that bound — `docs/artifact-root.md`'s count and lists, and the frozen spec's — are PM-owned, Q7/Q6) |
| 6 | The plan's own state rows are honest | `## Prepare gates`: specify/clarify/plan `done`, `primary_spec` declared and landed, `blocked_by` none; `## Recall receipt` and `## Plan self-review` unchanged unless a fact moved |
| 7 | The frozen spec's debt is recorded, not silently paid | contract §13; `{SPECS_DIR}/asr-archive-cli.md` is **not** edited by any task |

## Recall receipt (Prepare input, per `mstar-phase-gates` §A)

| Source consulted | What it contributed |
|---|---|
| `{KNOWLEDGE_DIR}/architecture-patterns/queue-derivation-bridge.md` | The bridge's conflict policy and effective-key limit — the precedent D3 mirrors. |
| `{KNOWLEDGE_DIR}/architecture-patterns/normalized-transcript-storage.md` | The store's transcript identity (language + content hash, version append) and the two-resource bootstrap. |
| `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md` | Command composition rules, exit taxonomy, the transient-audio and projection bullets. |
| `{KNOWLEDGE_DIR}/architecture-patterns/artifact-root-split.md` | `ArtifactRoots` write/read bases and the paths recorded root-relative. |
| `{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md` | The "no back-write of an inferred truth" rule and the manifest-well-formedness judgement. |
| `{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md` | The review lens for criterion 4 (a claim must be no wider than the code). |
| `{KNOWLEDGE_DIR}/testing-patterns/worktree-test-invocation.md` | The pinned worktree invocation in Global Constraints. |
| E2E report `e2e-23191782-longform-pair-webdav` (A3–A8) | The measured consequence that fixes this iteration's premise and the F4 finding. |
| Register `_default/residuals.json` | The charter row, the folded F4 row, and the medium rows deliberately left out. |

## Plan self-review (PM before locked)

| Check | State |
|---|---|
| Direction is single and user-locked | yes — compass D1/D2 |
| Acceptance criteria are third-party checkable | yes — all six now name the operator's command, the expected exit code and the observable line/state (product-manager round, compass `## Acceptance Criteria`); the values they cite (identity/stem, frontmatter keys, recorded status) are the contract's to fix (D11/D12) |
| Non-goals name what a reader would otherwise expect | yes — compass `## Non-Goals` (twelve entries; the product-manager round narrowed the manifest-vocabulary one and added next-version drift, the captionless remainder, and the readers' append-only-history defect) |
| No ownerless placeholder in this plan before lock | enforced by the §1.3(iv) deadline |
| Branch policy recorded and not a silent default | yes — compass D4 (`AGENTS.md` convention) |
| Real-device verification kept out of tasks/gates | yes — compass D5 + Global Constraints |

## SDD runtime (ephemeral)

Filled during Phase 2 (`{SDD_DIR}/20260920-transcript-projections/`): the per-task briefs, the review
package and the progress ledger. Not part of the durable plan.

## Review Gate Summary

**QC gate: `approve with residuals` — 2026-09-20** (initial wave `needs fixes` → fix wave `525841f` → three-seat re-review all approve). Plan QC tri-review (`QC mode: full tri-review`,
N=3) over range `87892a01..d35635d`; full consolidation in
`{SDD_DIR}/20260920-transcript-projections/review/qc-consolidated.md`.

| Seat | Lens | Decision | C / W / S |
|---|---|---|---|
| `qc-specialist` | architecture coherence / maintainability | `needs fixes` | 0 / 4 / 13 |
| `qc-specialist-2` | security / correctness | `needs fixes` | 0 / 1 / 10 |
| `qc-specialist-3` | performance / reliability | `approve with residuals` | 0 / 4 / 3 |

No `Critical` and no `Unconfirmed`; all three seats declared truncated coverage, which is why the gate is
not an `Approve`. **Fix-wave scope (CW-1…CW-3, before the row leaves `InReview`):** CW-1 the projection
must **merge** onto the existing effective manifest row instead of replacing it (seat 2's F-001 — the only
finding that loses information: a pre-existing `audio_path` is dropped and its `.m4a` orphaned); CW-2 the
`cli.py` docstring's unconditional "heals on the next pass" claim (seat 3's F3 docstring half); CW-3 the
`--help` sentence that omits the writer-lock write site (seats 1 and 2). Then a **three-seat** targeted
re-review (each seat updates its own `qcN.md` under `## Revalidation`), then `QA gate: mandatory` /
`QA mode: targeted`.

**Residuals registered (open, `{PROJECT_DIR}/_default/residuals.json` → `entries["20260920-transcript-projections"]`):**
R1 medium (row replacement drops preserved keys — CW-1) · R2 medium (a hard kill leaks the fixed-name stage
dir and wedges the root; the printed error cannot name it) · R3 low (the product-path tuple has three homes,
no binding test) · R4 low (UTC date rendering duplicated) · R5 low (`already_published` base vs root-relative
rows; transient read error re-publishes and opens the marker window) · R6 low (the `--help` claim — CW-3) ·
R7 low (corpus-scale cost: content-read+SHA per candidate, O(N²) manifest upsert) · R8 low (four small
hardening items). Unreviewed by this tri, per the contract: the seven test files (seat 1), two large test
files (seat 2), four test files + the T6 document set + the contract beyond §5.4 (seat 3).

## QA Gate Summary

**`approve with residuals` — 2026-09-20** (`qa-engineer`, `QA gate: mandatory` / `QA mode: targeted`; report
`{SDD_DIR}/20260920-transcript-projections/review/qa.md`).

All six compass acceptance criteria **pass**, each with a witnessed command + result line at range head
`525841f` (the seat re-witnessed every gate-turning claim rather than reusing task reports): AC1
`publish-transcripts: candidates=6 published=5 already_published=1 failed=0` with four families + marker on disk;
AC2 a second run `published=0 already_published=6 failed=0` with all 35 file hashes identical and the store's
counts/`sha256` unchanged; AC3 `verify` exit 0 `defect_count: 0 defects: [] diagnostics: []` plus the coverage
row's `reasons: [] artifact_count: 4 cue_count: 4` and `derive-manifest queue=1` unchanged; AC4 the inverted
`asr_`/`confidence` grep exits 1 (no match) with nine frontmatter keys and the source verbatim; AC5 the self-check
behaves identically from three cwds with zero `no check script found`; AC6 the `--help` disclosures, the stale-claim
sweep and the Roadmap Position section all hold.

Suite evidence: **346 passed, 0 failed**, 4 deselected, 1 error — the error being the pre-existing
`installed_*` fixture failure on this sandbox's read-only `uv` cache, recorded as environment-limited and **not**
a plan failure. Not verified (correctly out of scope per compass D5): the GPU success branch and
installed-deployment behaviour.

Two reconciliation items the seat raised, both PM-owned and both deferred to iteration-close:
(i) the compass is **stale** where its AC3 note and one non-goal call register row
`e2e-23191782-season-7686105 · R2` open — the register records it **resolved 2026-09-18** by
`20260918-verification-surface-truth`, and the fix is present at HEAD (`sidecar_projection.py:190`,
`integrity.py:310`, `coverage_report.py:83`, `cli.py:1742`); no acceptance impact, because the fixture honoured the
one-row-per-`work_id` bound; (ii) AC3's phrasing "`summary.valid_work_items` includes it" is literally
unevaluable — that field is an integer count, and the seat verified the count covers the row.

## Residual register

| Row | State after this plan |
|---|---|
| `e2e-23191782-season-7686105 · R1` (medium) | **projection half discharged**; the row's live re-verification stays open until the separate E2E workflow runs |
| `e2e-23191782-longform-pair-webdav · R1` (low) | **closed by this plan's F4 task (T7)** if it lands (the anchor fix + a cwd-independent test) |
| `e2e-23191782-longform-pair-webdav · R2`/`R3`, `iter-2026-09-artifact-root · R2`/`R3`, readers' debt | untouched, owners and triggers in the compass `## Roadmap Position` |
