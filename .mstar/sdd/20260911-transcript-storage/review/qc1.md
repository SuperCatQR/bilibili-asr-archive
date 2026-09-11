---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260911-transcript-storage"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist | @qc-specialist-2 | @qc-specialist-3
- Runtime Agent ID: qc-specialist (seat 1 of 3)
- Runtime Model: not exposed to this leaf session (dsh leaf executor, standard tier)
- Review Perspective: architecture / maintainability (Modularity + Contract), with this seat's assignment emphasis on **schema/contract fidelity, bootstrap safety, and the storage layer's boundaries**
- Report Timestamp: 2026-09-11T07:57:49Z

## Scope
- plan_id: 20260911-transcript-storage
- Review range / Diff basis: `6ee7c6a..5f93e05` (base = the iteration integration branch at feature cut; 4 commits)
- Working branch (verified): `feature/20260911-transcript-storage`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage`
- Files reviewed: 8 of 8 in range (`pyproject.toml`, `storage/__init__.py`, `storage/database.py`, `storage/models.py`, `storage/schema-transcripts.sql`, `storage/schema.sql`, `tests/test_storage_schema.py`, `tests/test_transcript_repository.py`); +4028 / −58
- Commit range: identical to Review range — `d4cae24` (schema contract), `f3cd735` (write path), `1019000` (reads/enumeration, resumed), `5f93e05` (Minor-1 test strength)
- Analysis methods: git-diff / git-show / git-rev-parse (read-only), `read`, `grep`, plus an **independent textual extraction** of the spec's SQL blocks vs the shipped SQL resources (Python stdlib string comparison, no project code imported). No test/build/lint/install command was run; no git mutation; no network.
- Deep review: **triggered** (S1: 4028 lines / 8 files; S2+S4: `schema.sql` / `schema-transcripts.sql` DDL; S3: first implementation of this storage area; S6: `src` + `tests` + packaging boundaries)
- Lenses applied: **Modularity Lens**, **Contract Lens** (defaults), **Data Migration Lens** (S4), **Testing Lens** + **Standards Lens** (S3)

## Verification Performed (independent, evidence channel)

1. **Package fidelity.** The fenced diff in `review/branch-diff.md` is byte-identical to `git diff 6ee7c6a..5f93e05` (175 516 chars, 8 files); `6ee7c6a` is an ancestor of `5f93e05`; branch and cwd match the Assignment. All four commits match the package header.
2. **Spec ↔ DDL fidelity (re-derived, not read from the reviews).** All five locked statements of spec §2.4 and the §2.5 view are present **verbatim** (whitespace-normalized) in `schema-transcripts.sql` (`:12-28`, `:33-35`, `:50-67`, `:72-96`, `:98-99`, `:106-141`). The `transcript_segments` block is byte-identical to the block removed from `schema.sql` at the base commit; `schema.sql` is otherwise equal to base minus that block → **the metadata script carries no accidental edit**.
3. **Legacy fixture fidelity.** `LEGACY_TRANSCRIPT_TABLES_DDL` (`test_storage_schema.py:322-346`) is byte-identical to the base-commit transcript block, so the pre-iteration database the bootstrap test builds is a faithful reproduction, not an approximation of it.
4. **Bootstrap matrix.** `_accepts_transcript_script` (`database.py:130-138`) encodes §3.2 exactly (`not columns or {language, content_sha256} <= columns`); `initialize_schema` (`:148-166`) keeps the PRAGMA gate, the metadata script first, the conditional transcript script, one commit. Tested on fresh (`:1023-1031`), current (`:1033-1084`, incl. a DROP-heal cycle) and pre-iteration (`:1087-1143`, incl. metadata **read and write** on the legacy DB and the bounded raise).
5. **Boundaries.** `storage/*.py` imports only stdlib + `.models` (no `bili_asr.sources`, no gateway DTOs); no module outside `storage/` issues SQL against `transcripts` / `transcript_segments` / `acquisition_*` / `v_pending_subtitles` (`grep` over `src/`); the metadata repository's bodies are unchanged apart from the extracted `_validate_connection` / `_transaction` helpers.
6. **Immutability by code path.** Six write statements exist in `TranscriptRepository`: five INSERTs (transcripts, segments, attempts ×2, runs) and one `UPDATE acquisition_runs` (the run's own terminal transition). No `UPDATE` / `DELETE` / `INSERT OR REPLACE` against `transcripts` or `transcript_segments`.
7. **Interrupted-run resume (assignment focus 4).** The committed state carries every audit fix: D1's coincidence assertion is gone (`grep` finds no `transcript_id == rows[0][...]`; the replacement at `test_transcript_repository.py:1578-1581` is a real claim); D2's intercept is **armed** (`:1894-1897` proves it fires, then `:1920` requires an empty record); D3 parametrizes all four `run_id`-carrying methods (`:1819-1837`); D5's drop-the-view proof is present (`:1643-1651`); D4 is cosmetic. The unverifiable piece is the WIP genesis claim (Task-3 review ⚠️4) — but all five defects are test-side, and the committed artifact is reviewable on its own, so trust does not rest on that claim.
8. **Residual discipline (assignment focus 5).** `projects/_default/residuals.json` holds exactly one entry, `R1` for the **previous** plan (`defer`, retargeted, `lifecycle_id` set) — this plan registered none. Its remaining items are recorded: the pending-order nit in the plan's Durable Roadmap (`20260911-transcript-storage.md:272-276`) and the ledger (`progress.md:150-151`); the docs staleness in the plan Drift Check (`:280-284`), the ledger (⚠️3) and the CLI plan's Task-3 file list; and the ⚠️ sections of all three task reviews.
9. **L2 severity re-judged independently.** Concur with `Approved` on all three tasks (0 Critical / 0 Important each). `Minor-1` is closed by `5f93e05` — I re-derived the discrimination claim from the committed fixture by hand (all four never-attempted rows tie on `attempted`/`last_attempt_at`, and the pair `(BV0Z,1)`/`(BV1A,0)` makes `bvid ASC, page_index ASC` differ from the swap at index 1, matching the asserted list at `:1378-1385`). No escalation.

## Findings

### 🔴 Critical

None. No defect was found that breaks a locked contract, corrupts or loses stored data, defeats the bootstrap guarantee, or cross-plan breaks the CLI plan.

### 🟡 Warning

None. The candidate risks I examined and rejected as Warnings, with why:

- *Bootstrap half-apply on mid-script failure* — not reachable: the transcript script is only entered for a fresh or already-current database, every statement is `IF NOT EXISTS`, and a failure re-raises while the next `initialize_schema` heals the missing objects (tested at `:1074-1084`). No state is silently accepted.
- *Evidence written into an already-finished run* (`database.py:836-959`, mirrored contract note in the Task-2 review) — deliberate and **tested as intended** (`test_finish_records_an_abnormal_failure_without_recomputing_it:812-837` asserts the run keeps `failed` after a later `stored` write). It is not an oversight; only the ordering obligation for the CLI remains, which is already recorded cross-plan (see Suggestion QC1-003).
- *Content identity vs. the `asr-local` reservation* — the partial index excludes the kind (`schema-transcripts.sql:33-35`) and the write path refuses it (`models.py:472-476`, `ALLOWED_CAPTION_SOURCE_KINDS`), so the audio/ASR iteration cannot collide with caption identity. Locked and tested (`test_subtitle_content_index_is_partial_over_the_caption_kinds:1156-1224`).

### 🟢 Suggestion

- **[QC1-001] The pending relation's "not pending" rule is "any `transcripts` row", which the audio/ASR iteration will read as "has a subtitle" — record that consequence in the Durable Roadmap handoff.**
  - Source Type: deep-lens: Contract Lens
  - Verification: diff/read anchor — `schema-transcripts.sql:139-141` (`NOT EXISTS (SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id)`, no kind scoping) vs the spec rule "a part with any `transcripts` row does not appear (it has a caption)" (spec §2.5, `transcript-storage.md:272`) vs the plan's handoff, which records the model-key widening but not this (`20260911-transcript-storage.md:257-270`).
  - Expected vs observed: expected — the next iteration inherits the *stated* boundary that a part whose only transcript is `asr-local` will disappear from `v_pending_subtitles`; observed — that consequence is stated only in the spec, and the plan-level handoff names the version-key widening alone. The implementation is faithful to the locked spec; the gap is the recorded handoff, not the code.
  - Confidence: High. Fix: one Durable Roadmap line ("once `asr-local` rows exist, `v_pending_subtitles` drops those parts; the audio/ASR iteration decides whether its own pending relation is view-cloned with a kind filter") — no code change in this plan.

- **[QC1-002] The structural guard omits `transcript_segments`, so the one object whose absence makes writes fail is not part of the capability check.**
  - Source Type: deep-lens: Data Migration Lens
  - Verification: diff/read anchor — `database.py:55-59` (`_SUBTITLE_SCHEMA_OBJECTS = acquisition_attempts, acquisition_runs, v_pending_subtitles`) and `:141-145` (`_has_subtitle_schema`) vs the spec's literal scope (spec §3.3) and the healing path `:161-164`. Reachability: the shipped entry path (`open_database` → `initialize_schema` → guard) re-applies the transcript script whenever the columns are present, so a missing `transcript_segments` is recreated before the guard runs — the gap is therefore only reachable through a same-session manual DROP or an interrupted initialization.
  - Expected vs observed: expected — every object a subtitle command needs is either present or reported as the bounded `SchemaContractError`; observed — a database missing only `transcript_segments` passes `require_subtitle_schema` and then fails a write with a raw `sqlite3.OperationalError`. Spec §3.3 is implemented verbatim, so this is a *hardening* suggestion, not a contract violation.
  - Confidence: High (source-level); impact low. Fix: add `"transcript_segments"` to `_SUBTITLE_SCHEMA_OBJECTS` (one token, the existing test at `:1146-1153` already has the drop-a-table pattern).

- **[QC1-003] Three CLI-facing notes exist only inside the review bundle or the ledger and are not yet carried into the CLI plan text; also, the two candidate readers return different row shapes.**
  - Source Type: deep-lens: Modularity Lens
  - Verification: diff/read/grep anchors — (a) `grep ALLOWED_CAPTION_SOURCE_KINDS .mstar/plans/ .mstar/iterations/` returns **no hit**, while the Task-2 review ⚠️5(c) asks the CLI to validate against it; (b) Task-1 review ⚠️6 ("confirm guard scope at CLI task review") appears in no plan or ledger line; (c) the pending reader returns the 12-column work item including `cid` (`test_transcript_repository.py:1435-1448`, pinned in `test_storage_schema.py:284-297`), while `list_selected_parts` returns the 11 `v_video_parts` columns and **no `bvid`** (`:1563-1575`; `database.py:1129-1158` documents the join but the CLI plan speaks of a single "work item", `20260911-subtitle-cli-cutover.md:146-147`).
  - Expected vs observed: expected — every cross-plan obligation the L2 reviews raised is present in the consumer plan before it is dispatched; observed — the CLI plan already covers `kind='subtitle'`, "finish once per run", "use `list_pending_subtitle_parts`", "`[]` ⇒ exit 1" and the 12-column set (its own lines 87-88, 146-169, 215-216), but it does not mention the write-side source-kind vocabulary, the guard-scope confirmation, or that the explicit selection's rows lack `bvid` (the service must supply it from `--bvid`).
  - Confidence: High for (a) and (c); High for (b) as an absence-in-text claim. Fix: three lines in the CLI plan's brief/Interfaces block — no change to this branch.

- **[QC1-004] Recurring, low: the new class inherits the shipped "commit without rollback on a failed insert" pattern in a second place.**
  - Source Type: deep-lens: Standards Lens (recurring pattern)
  - Verification: diff/read anchor — `database.py:762-783` (`start_acquisition_run` INSERT then an unconditional `commit()`; a duplicate `run_id` propagates with the implicit transaction still open) vs the shipped `MetadataRepository.start_run` (`:387-408`, identical shape) vs the Task-2 review's ⚠️4 for `finish_acquisition_run`'s `changes() != 1` path. Bounded by evidence: `test_start_acquisition_run_rejects_a_duplicate_run_id:872-904` shows the stored row is unchanged, and the class documents one connection per use.
  - Expected vs observed: expected — every failing write of the new aggregate leaves the connection in the same state as the shipped metadata discipline; observed — it does (deliberately), which is why this is recorded as a pattern note rather than a defect: a future caller that catches the `IntegrityError` and keeps writing joins the aborted transaction.
  - Confidence: Medium (behavioural impact depends on future callers). Fix: optional — wrap the insert in `_transaction`, or state the requirement in the class docstring; do not change it inside this plan's gate if the team prefers mirroring `MetadataRepository`.

### ⚪ Unconfirmed

None — every finding above carries an intact diff/read/grep channel, and the review-package diff was verified byte-identical to the real range.

## Source Trace

| Finding | Source Type | Source Reference | Confidence | Note |
|---|---|---|---|---|
| QC1-001 | deep-lens: Contract Lens | `schema-transcripts.sql:139-141`; `specs/transcript-storage.md:272`; `.mstar/plans/20260911-transcript-storage.md:257-270` | High | Verification = diff/read; Expected vs observed as stated in the finding |
| QC1-002 | deep-lens: Data Migration Lens | `storage/database.py:55-59,141-145,148-166`; `specs/transcript-storage.md:330-342`; `tests/test_storage_schema.py:1146-1153` | High | Verification = diff/read |
| QC1-003 | deep-lens: Modularity Lens | `tests/test_transcript_repository.py:1435-1448,1563-1575`; `tests/test_storage_schema.py:284-297`; `grep` over `.mstar/plans/`, `.mstar/iterations/`; `review/task-1-review.md:52`; `review/task-2-review.md:86` | High | Verification = diff/read/grep |
| QC1-004 | deep-lens: Standards Lens | `storage/database.py:762-783` vs `:387-408`; `tests/test_transcript_repository.py:872-904`; `review/task-2-review.md:85` | Medium | Verification = diff/read; recurring (same class as the Task-2 ⚠️4 note) |

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 4 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Rationale: the locked transcript contract is present in the schema resource **verbatim**, the bootstrap split is the honest reading of its constraint (legacy databases are skipped and proven untouched, metadata read/write keeps working, the capability guard is structural and bounded), the storage layer keeps its boundaries (no gateway imports, no SQL against the new tables outside `storage/`, no `UPDATE`/`DELETE` on immutable rows), the interrupted Task-3 run's five inherited defects are all verifiably closed in the committed artifact, and the plan's remaining items are recorded where they belong. The four suggestions are hardening and cross-plan-carry items; none changes a locked contract, and none is a defect in the diff.

### Needs L4/QA verification (not self-executed by this seat)

- **Full offline suite green** (`1201 passed, 3 skipped`, baseline `1168/3`) is implementer-reported at every task (Task-1 ⚠️1, Task-2 ⚠️1, Task-3 ⚠️1). Independent mitigations exist (each seat reproduced its focused module; the per-task delta arithmetic reconciles; no pre-existing test file is modified), but the accepted full-suite evidence must be produced at the plan's mandatory QA gate.
- **Red-evidence mutation runs** (Task 1: 2, Task 2: 7, Task 3: 8, fix wave: 3) are self-reported; this seat verified that each targeted assertion exists and is discriminating, not that the mutations were executed. QA can sample if the gate needs it.
- **Wheel content** (`schema-transcripts.sql` ships): packaging is pinned by declaration + resource test (`test_storage_schema.py:366-388`); no wheel was built (instructed). A wheel-content check belongs to the QA gate.

### ⚠️ Items for PM (recorded, not silently dropped)

1. Cross-plan carry before plan `20260911-subtitle-cli-cutover` is dispatched: `ALLOWED_CAPTION_SOURCE_KINDS`, the guard-scope confirmation, the two reader row shapes, and the existing `kind='subtitle'` / finish-after-the-loop obligations (QC1-003; Task-1 ⚠️6; Task-2 ⚠️5).
2. `docs/metadata-storage.md` is stale in two sentences this plan made wrong (single schema resource; transcript tables "stay empty"). Owned by the CLI plan's Task 3 file list per the plan's Drift Check — **must land before that plan's Done** (Task-1 ⚠️3; ledger).
3. Pending-order nit (dropping only `page_index ASC` still passes; `bvid ASC` is pinned): recorded in this plan's Durable Roadmap and the ledger as a **nit, not a residual** — the next owner of pending enumeration may add the static key-list assertion (plan `:272-276`).
4. No new residual is registered by this plan; `R1` remains the only open entry and belongs to `20260911-subtitle-gateway` (`defer`, retargeted, executable target).
