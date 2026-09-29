---
plan_id: 20260929-derive-manifest-retirement
iteration: iter-2026-09-queue-ssot-closeout
iteration_compass: .mstar/iterations/iter-2026-09-queue-ssot-closeout/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
status: registered
gate_decision: pass
gate_decision_reason: >-
  Prepare satisfied — compass D2/D5/D6 fix the scope and the removal criterion. The intent
  source is the roadmap's own P0 tail (the `derive-manifest` deletion was named in
  `20260927-archive-db-queue-cutover` Task 4 / D-3 and left undone when that iteration closed
  with the command still shipped). Clarify converged on removal-by-consumer, not
  removal-by-filename: the module holds one symbol the shipping projection path still imports.
gate_decided_at: 2026-09-29
registered_at: 2026-09-29
planned_at_sha: ed291be
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# Retire `derive-manifest` and delete the manifest queue module

**Main worktree branch**: `main`

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Checkbox syntax.
>
> **Why this is live work and not cleanup theatre.** `derive-manifest` writes `needs_audio`
> rows into `manifest.jsonl`. Since `iter-2026-09-ops-readiness`, `download-audio` / `asr` /
> `pilot` / `run` all default to `--queue-source store`, which reads `archive.db` gap views
> and **never** consults the manifest to decide work. So the command's output is inert: an
> operator who runs it sees rows appear and no stage consume them. That is worse than a
> missing feature — it is a queue producer with no consumer.

## Current state (evidence — re-read before dispatch)

Measured on `main` = `ed291be` (2026-09-29), control root
`/root/workspace/bilibili-asr-archive`:

- **The command ships.** `cli.py:297` registers `derive-manifest`; `cli.py:4494` lists it in
  the archive-writer command set; `cli.py:4532` dispatches it; `cli.py:1412` is its handler.
- **The module ships.** `src/bili_asr/services/manifest_derivation.py` is 173 lines.
- **The flag that made it redundant ships too.** `--queue-source` appears at
  `cli.py:165` (→ `asr`), `:207` (→ `pilot`), `:289` (→ `download-audio`), `:451`
  (→ `run`), all with `default="store"`. Verified by mapping each flag line to the
  preceding `add_parser` call, not by reading prose.
- **`schedule` and `campaign` parse no `--queue-source`** and call
  `_store_pending_rows` (`cli.py:3636`), whose docstring states the store is the sole
  queue input for the pending scope. They are already store-only; the plan's assertion
  covers them by calling that helper rather than by adding a flag.
- **The consumer map is the whole point of this plan.** Every symbol in the module, with
  every live consumer on `main`:

  | Symbol | Live consumers outside the module | Verdict |
  |---|---|---|
  | `derive_rows` | `cli.py:1442,1455` only (the `derive-manifest` handler) | retire with the command |
  | `QUEUE_STATUS` | `cli.py:1438,1510` (handler) + `tests/test_archive_md.py:9,407` | retire; the test takes its own literal |
  | `SKIP_ALREADY_DERIVED` / `SKIP_CHAIN_OWNED` / `SKIP_IDENTITY_MISMATCH` | `cli.py:1439-1441,1470-1472,1512-1514` (handler) | retire with the command |
  | `row_for_part` | **tests only** (`test_manifest_derivation.py`, and docstring prose in `test_archive_md.py`) | retire; the prose reference is a docstring, not an import |
  | `duration_s_from_ms` | **`cli.py:1691,1789` and `services/transcript_projection.py:47,269`** — the published-projection path | **KEEP — this symbol has a shipping consumer** |

- **The duplication fact that constrains the fix.** `services/queue_source.py:51` has its own
  private `_duration_s_from_ms` with the same floor/clamp policy and its own docstring. So
  after this plan the policy exists twice, which is a *pre-existing* condition (it is already
  recorded as a residual about copy-pasted helpers) and **not** this plan's target. This plan
  must not "unify" them: `queue_source`'s copy is private and the projection's is public, and
  merging them is a separate refactor with its own review obligations.
- **The test surface is larger than the module.** `tests/test_manifest_derivation.py` (211
  lines), `tests/test_cli_derive_manifest.py` (508 lines), and
  `tests/test_derived_queue_chain.py` (657 lines) exist to exercise the command and the
  bridge. Scattered references also live in `test_cli_help.py:1160`,
  `test_audio_inventory.py` (17 hits, mostly docstring parity claims about
  `derive-audio-inventory`), `test_persistence_scale.py` (3), `test_cli_artifact_root.py` (1),
  `test_published_projection_readers.py` (13).

## Goal (intent gate)

**真实目标**：manifest 不再是一个队列生产者——`archive.db` 是唯一队列真相源，且这一点
由代码断言而不是由文档声明。**成功判据**：DoD 1–5。**非目标**：删除 manifest 文件格式、
删除 `--queue-source manifest` 回滚读路径、统一两份 duration 实现、改动已发布投影路径。

## Task 1: Retire the `derive-manifest` command

- [ ] Remove the subparser registration (`cli.py:297`), the handler (`cli.py:1412`
  `_cmd_derive_manifest`), the dispatch arm (`cli.py:4532`), and the entry in the
  archive-writer command set (`cli.py:4494`). The last one is not optional: leaving the
  name in that set would make the lock-writer logic keep answering for a command that
  no longer exists.
- [ ] **Relocate or delete `duration_s_from_ms` by consumer, not by file.** It has two
  live consumers on the published-projection path (`cli.py:1691`, and
  `transcript_projection.py:47` as a module-level import). Move it into a module those two
  consumers already import — state which one in the report — or keep the module and delete
  everything else in it. Either is acceptable; deleting the symbol is **not**, because it
  breaks a shipping reader. Update the `:func:` cross-reference at
  `transcript_projection.py:34` so no docstring points at a symbol that moved.
- [ ] Delete every other symbol in the module (see the consumer map) and the module itself
  if the relocation emptied it.
- [ ] Files: `src/bili_asr/cli.py`, `src/bili_asr/services/manifest_derivation.py`,
  `src/bili_asr/services/transcript_projection.py` (import + docstring only).

## Task 2: Retire the tests of the retired command, keep the policy tests that still bind

- [ ] Delete `tests/test_cli_derive_manifest.py` and `tests/test_derived_queue_chain.py` —
  both exist to assert the bridge's behaviour, and the bridge is what this plan removes.
  Their helper `_archive_connection` / `_derive` / `_seed_archive` imports must go with
  them.
- [ ] Re-home `tests/test_manifest_derivation.py`'s surviving assertions. Its
  `duration_s_from_ms` cases (`:93-102`, including the `None`→1 and `0`→1 arms) must move
  beside the symbol's new home with the same values; the `derive_rows` / `row_for_part` /
  `QUEUE_STATUS` cases retire with what they test. **Do not** delete a passing assertion
  because its file is being deleted — that silently retires a policy.
- [ ] Repair the scattered references so the suite has no dangling name: `test_cli_help.py:1160`
  (the command inventory list), **`tests/test_archive_md.py`** (its module-level import of
  `QUEUE_STATUS` makes the whole file fail collection — 34 tests stop running — as measured on
  `126630a` at the Task-1 review), **`tests/test_export.py:270`** (a docstring citing
  `row_for_part`; prose only, so it breaks nothing at runtime, but DoD-5 covers dangling
  citations and no other task owns the file), `test_audio_inventory.py`'s docstring parity
  claims (17 hits — re-read each; the parity claim about `derive-audio-inventory`'s
  empty-result behaviour may be worth re-pointing at a still-shipping command rather than
  deleting), `test_persistence_scale.py`, `test_cli_artifact_root.py`,
  `test_published_projection_readers.py`.
- [ ] Files: the seven test files above, plus the new home of the `duration_s_from_ms` cases.

## Task 3: Assert the queue is manifest-free, and that the rollback survives

- [ ] Add the queue-independence assertion: for `download-audio`, `asr`, `pilot`, and `run`,
  a queue decision under the default source must not consult the manifest. Assert it on
  behaviour the code owns — the store-sourced entry set is produced without a manifest
  read — rather than by grepping for an import, which a rename would defeat.
- [ ] Add the `schedule` / `campaign` leg by asserting they route through
  `_store_pending_rows` with the store as the input, since neither parses a
  `--queue-source` flag and that is correct, not a gap.
- [ ] Assert the invocation-level retirement: `main(["derive-manifest", ...])` is an
  argparse `invalid choice` error, exiting non-zero, with nothing created. This is the
  DoD-1 negative control.
- [ ] Assert the rollback still works: `--queue-source manifest` remains a valid choice for
  all four commands and still selects the manifest read path. A retirement that also
  removed the operator's escape hatch would be a scope error, and this test is what makes
  that visible.
- [ ] Files: the new assertions belong with the queue-source tests they extend; state the
  file in the report.

## Task 4: Correct the operator-facing documentation (added 2026-09-29, PM)

> **Why this task exists.** Task 1's implementer disclosed that `README.md` (21 hits, including
> a `#### Derived audio queue` section) and `docs/{artifact-root,metadata-storage}.md` still
> document `derive-manifest` as a shipped command. Leaving that in place recreates the exact
> trap this plan removes — an operator reads the README, runs a command that no longer exists,
> and gets an `invalid choice` error. The iteration compass already assigns this file to plan A
> ("Both share one target — `bilibili-asr-archive/README.md`'s CLI reference — and **only plan A
> writes it**"), so this is plan A's surface, not new scope.

- [ ] Remove or rewrite every `derive-manifest` reference in `README.md`, including the
  `#### Derived audio queue` section and its command example. Where the section explained why
  the manifest carried the audio queue, replace it with the current truth: the store is the
  queue, and `--queue-source manifest` is the documented rollback read path.
- [ ] Remove or rewrite the references in `docs/artifact-root.md` and
  `docs/metadata-storage.md`. `metadata-storage.md`'s `§Boundary` claim is the one that
  matters most — it names the manifest's role, and its current text predates the cutover.
- [ ] **Do not** rewrite historical records: `.mstar/` iteration contracts, knowledge notes and
  plan files that cite the retired module path are the record of what those plans said when
  they were written. They are out of scope, as established for the frozen spec.
- [ ] Verification is a real scoped check, not a test file: `grep -rn "derive-manifest"`
  over `README.md`, `docs/artifact-root.md` and `docs/metadata-storage.md` returns zero hits,
  and the quoted before/after counts are recorded. **Scope the grep to those three files, not
  to `docs/` as a directory** — `docs/archive/deletion-records-20260925/` is a historical
  record this task must not edit, and it legitimately contains the string. The measured
  before-state is **16 hits in `README.md`** and **4 in `docs/` (1 + 3)**, i.e. 20 in the
  three in-scope files. Do not manufacture a test for prose.
- [ ] Files: `bilibili-asr-archive/README.md`,
  `bilibili-asr-archive/docs/artifact-root.md`,
  `bilibili-asr-archive/docs/metadata-storage.md`.

## Global Constraints

- **Removal by consumer.** `duration_s_from_ms` stays. Any further removal decision must cite
  the consumer that made it necessary, in the report — not the file it happened to live in.
- **No backward-compatibility shim.** No alias command, no deprecation warning, no
  `derive-manifest` stub that prints "removed". Per `mstar-harness-core` § 核心研发守则.
- **Do not touch the manifest file format, its readers, or the `--queue-source manifest`
  rollback.** The manifest remains the attempt ledger.
- **Do not unify the two duration helpers.** Pre-existing duplication, separate concern.
- **Do not edit `{SPECS_DIR}/asr-archive-cli.md`** — it is frozen; this plan removes surface
  the spec never enumerated.
- New names via `naming-analyzer`.
- Test invocation from the feature worktree MUST pin the interpreter and source path:
  `PYTHONPATH=$PWD/src <repo>/bilibili-asr-archive/.venv/bin/python -m pytest <selector>`,
  and quote the resolved `bili_asr.__file__` in the report. An unpinned run grades the
  primary checkout and is false evidence.

## Definition of Done

1. `bili-asr derive-manifest` is an `invalid choice` error; `cli.py` has no handler, no
   dispatch arm, and no archive-writer entry for it.
2. `duration_s_from_ms` still resolves for both published-projection consumers; its
   cross-reference docstrings name its real home; its floor/clamp cases still pass with
   their original expected values.
3. No queue decision reads the manifest under the default source, asserted for
   `download-audio` / `asr` / `pilot` / `run` and for `schedule` / `campaign`.
4. `--queue-source manifest` still parses and still selects the rollback path for all four
   commands.
5. The suite carries no dangling reference to the retired module or command.

## Verification

- Task-scoped RED-before / GREEN-after per SDD brief.
- The `invalid choice` assertion (Task 3) is its own negative control: it must fail before
  the removal and pass after.
- At the end: `PYTHONPATH=$PWD/src <repo>/bilibili-asr-archive/.venv/bin/python -m pytest`
  over the affected selectors, with the resolved-source line quoted. **Not** the full suite
  locally — the complete run belongs to CI.

## Open Questions (owned, non-blocking)

| # | Question | Owner | Blocking? |
|---|---|---|---|
| Q1 | Which module receives `duration_s_from_ms` — `transcript_projection.py` (a consumer that is not the shared home) or a small shared module both consumers import? The implementer decides from the import graph and records the call and its reason in the report. | architect | No |

## Engine lifecycle

Registered as a plan row of `iter-2026-09-queue-ssot-closeout`. Implementation happens in the
plan's feature worktree on its own branch cut from
`iteration/iter-2026-09-queue-ssot-closeout`; QC and QA review the single merged `HEAD` of that
branch. `Done` is set only after the integration merge succeeds.
