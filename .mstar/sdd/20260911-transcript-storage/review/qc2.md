---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260911-transcript-storage"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: not disclosed to this seat (Assignment `Model tier: standard`)
- Review Perspective: write-path correctness, transactional integrity, idempotency, and test non-vacuity
- Report Timestamp: 2026-09-11T07:59Z

## Scope

- plan_id: `20260911-transcript-storage`
- Review range / Diff basis: `6ee7c6a..5f93e05` (base = the iteration integration branch at feature cut; 4 commits)
- Working branch (verified): `feature/20260911-transcript-storage` (`git branch --show-current`)
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage` (`git rev-parse --show-toplevel`); `HEAD = 5f93e05`, worktree clean (`git status --porcelain` empty)
- Files reviewed: 8 (4 source/schema resources, 2 test modules, `pyproject.toml`, `storage/__init__.py`); `+4028 / −58`
- Commit range (if not identical to Review range line, explain): `6ee7c6a..5f93e05` = `d4cae24` (schema contract) → `f3cd735` (write path) → `1019000` (reads/enumeration, resumed) → `5f93e05` (ordering test strength); identical to the Assignment range
- Analysis methods: `git diff` / `git log` (read-only), review-package `branch-diff.md` reconciliation, `read`, `grep`; `git diff --check` (read-only cleanliness probe). No test/build/lint/typecheck run, no checkout or worktree mutation, no network. Peer runtime evidence (`1201 passed, 3 skipped`; the Task-3 revalidation's in-process probes) is cited as **report evidence**, not re-executed.
- Deep review: **triggered** (S1: 4028 lines / 8 files; S2+S4: schema DDL + the storage persistence boundary — `schema.sql`, `schema-transcripts.sql`, `CREATE TABLE/INDEX`; S6: packaging + `src/` + `tests/` boundaries)
- Lenses applied: **Correctness Lens, Bounds Lens, Real-Entry-Path Lens** (seat defaults) + **Data Migration Lens** (S4) + **Input Validation Lens** (S2) — see `Source Type` on each finding

## Verification I performed independently

Everything below was derived from the checked-out source at `5f93e05` and the range diff; nothing rests on an implementer's prose where I could read the artifact myself.

1. **Range/package reconciliation.** `git diff --name-status 6ee7c6a..5f93e05` returns exactly the 8 files the Assignment and `review/branch-diff.md` claim; the package header (`Range`, `Base`, `Head`, `Working branch`, 4 commits) matches `git log`. `git diff --check 6ee7c6a..5f93e05` → clean, so the plan's "`git diff --check` clean" Done criterion holds. Worktree clean, no `.orig/.bak/.rej` strays.
2. **The attempt INSERT is last (Assignment focus 1), read line by line.** In `record_acquired_transcript` (`storage/database.py:836-959`) the `with _transaction(self.connection)` group (888) contains, in order: `_require_video_part` (889), `_require_acquisition_run` (890), the content-identity SELECT (891-899), `INSERT INTO transcripts` (904-920), `executemany` into `transcript_segments` (921-931), and **the `acquisition_attempts` INSERT as the final statement** (937-952). `_transaction` (`:224-237`) commits on success and `rollback()` + re-raise on any `BaseException`. So a `PRIMARY KEY (run_id, video_part_id)` conflict on the attempt row is raised *inside* the group and takes the just-inserted version and its segments with it — the claim is structurally true, not merely asserted. Pinned by `tests/test_transcript_repository.py:608-648`.
3. **No half-written version from any other failure.** All argument validation (`:871-886`, incl. `_canonical_segments` and the digest) happens *before* the group opens, and the only writes are inside it; `TranscriptWriteResult` is constructed after the group (`:954-959`) from values already resolved inside it. `test_unknown_part_and_unknown_run_fail_the_whole_write:582-605` proves the empty store after both rejections **and** that the independently-committed run parent survives (`:598-603`) — i.e. a failed attempt cannot roll back the run parent, and a separate `record_subtitle_attempt` transaction cannot roll back an earlier transcript write (each is its own `_transaction`, `:998`).
4. **Commit-boundary matrix is real, not documentary.** `start_acquisition_run` commits its own insert (`:783`), `finish_acquisition_run` its terminal transition (`:833`), `record_subtitle_attempt` its evidence row (`:998`), and the read paths never call `commit` (five readers, `:1011-1158`). Verified from a **second connection**: `test_committed_writes_are_visible_outside_the_writing_connection:1142-1205` observes each of the four commit points, and `test_read_transcript_…:1270-1271` asserts the read store is unchanged **and** `connection.in_transaction is False`.
5. **Immutability by inspection.** `grep -rn "UPDATE |DELETE FROM|INSERT OR REPLACE|REPLACE INTO" src/` over the whole package returns, for the new tables, exactly one statement: `UPDATE acquisition_runs SET finished_at, outcome … WHERE … AND outcome = 'running'` (`:823-830`, guarded, and `changes() != 1` → `IntegrityError`, `:831-832`). There is **no** `UPDATE`/`DELETE`/`INSERT OR REPLACE` against `transcripts`, `transcript_segments`, or `acquisition_attempts` anywhere in `src/`. Behaviourally: `test_changed_content_appends_version_two_and_leaves_version_one_untouched:405-449` (v1 row + segments byte-identical after v2), `test_schema_foreign_keys_reject_orphans_and_restrict_deletes:651-695` (transcript/part/run deletes RESTRICTed, `PRAGMA foreign_key_check` empty).
6. **Identity and idempotency semantics.** The lookup predicate (`:891-899`) is exactly `(video_part_id, source_kind, language, content_sha256)`; the digest is `sha256(json.dumps(triples, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))` (`:705-708`) — the spec §2.2 canonical form, character for character; `language` is trimmed at the boundary (`_language_code`, `:695-702`) and the stored text is `segment.text.strip()` (`:1239-1241`), so **stored text == hashed text == language identity**. `MAX(version)+1` via `_next_transcript_version` (`:1245-1257`); `unchanged` returns the **existing** row's `transcript_id`/`version` (`:933-936`), so a revert-to-older body points at the version the operator already holds.
7. **Normalization contracts (focus 3).** `MAX_TIMELINE_MS = 10**12` lives in `models.py:44` as documentation + vocabulary, and is enforced **only** at the repository boundary (`database.py:1223-1234`, `minimum=0`/`minimum=1` + `maximum=MAX_TIMELINE_MS`), while `TranscriptSegmentRecord.__post_init__` (`models.py:318-323`) deliberately accepts an unbounded integer — matching spec §5's dated note that moving the bound stays a visible change. Order/overlap: the ordinal is `enumerate` position and there is no sort anywhere (`:1217-1243`), so upstream order is preserved verbatim with overlaps.
8. **Schema/DDL fidelity spot-check against the spec's §2.4/§2.5 text.** `schema-transcripts.sql` reproduces the spec's six statements (widened `UNIQUE (video_part_id, source_kind, language, version)`, `language`/`content_sha256` CHECKs, the caption-scoped partial index, both process tables with the full CHECK matrix, the attempt index, the pending view) and the `transcript_segments` block moved out of `schema.sql` is character-identical to the removed block. `initialize_schema` (`:148-166`) keeps `PRAGMA foreign_keys = ON` + verification and gates the second script on `_accepts_transcript_script` (`:130-138`); `require_subtitle_schema` / `SchemaContractError` (`:169-183`) implement the structural check of spec §3.3.
9. **Cross-plan handoff checks (Durable Roadmap Gate).** (a) The Task-1 ⚠️3 stale-docs carry is genuinely owned: `docs/metadata-storage.md` is listed under Modify in the CLI plan (`20260911-subtitle-cli-cutover.md:229`) with the doc task at `:243`. (b) The Task-1 M2 message carry is genuinely owned: the CLI plan composes the spec-fixed printed line including the `<root>/archive.db` path and the `<command>:` prefix (`:56-58`, `:169-170`) and asserts it at `:299-300`. (c) The explicit-outcome escape hatch on `finish_acquisition_run` is not exploited by the consumer: the CLI plan commits to the **derived** outcome (`:151-152`), so the recorded run outcome will agree with its attempt rows.
10. **Style/consistency of the added lines.** Every line added by the branch is ≤ 93 characters (the two > 93 lines in `test_storage_schema.py`, `:770-771`, are pre-existing context, not added), so the D4 fix generalizes rather than being a one-off. No `print`/`TODO`/`FIXME` in the new storage code.

## High-value guard non-vacuity map (Assignment focus 4)

"Revert fails a named test?" = the assertion values pin the behaviour, so removing/altering the guard makes a *named existing* test fail. Mutation column = the implementer's recorded red proof, which I did not re-run (Task-3's enumeration keys are excluded per Assignment; the Task-3 revalidation already proved them live).

| Guard | Named test (anchor) | Revert fails? | Mutation evidence |
|---|---|---|---|
| Content-identity lookup (no write on identical content; `unchanged` → existing version) | `test_repeat_with_identical_content_writes_nothing_and_reports_unchanged:294` | Yes (one row, same `transcript_id`, attempt `unchanged`) | `if existing_row is None` → `if True` ⇒ 1 failed |
| Canonical JSON form of the digest | `test_content_hash_is_the_sha256_of_the_canonical_segment_json:357` (independent recomputation + three looser encodings asserted unequal) | Yes | drop `separators=(",", ":")` ⇒ 1 failed |
| Trimming at the repository boundary (stored == hashed) | `test_text_is_stored_and_hashed_trimmed_but_kept_verbatim_inside:326` | Yes | `text.strip()` → `text` ⇒ 1 failed |
| Trimmed language as part of identity | `test_content_identity_is_scoped_to_the_identity_key:497` | Yes (stored rows asserted as `zh-CN`) | — (assertion-pinned) |
| `MAX_TIMELINE_MS` site + value (DTO stays unbounded) | `test_timeline_ceiling_is_the_storage_boundarys_rejection:1070` (at-ceiling accepted; `MAX+1` and `10**19` rejected; nothing written) | Yes | remove `maximum=` ⇒ 1 failed (and the raw `OverflowError` reappears) |
| Write atomicity — attempt row last, rollback takes the version | `test_attempt_conflict_rolls_back_the_version_it_would_have_stored:608` (+ `:582`) | Yes (v1 row/segments/attempts intact; the body then lands as v2 next run) | `with _transaction(...)` → `if True` ⇒ 1 failed |
| Derived run outcome `complete\|partial\|failed` (incl. zero attempts) | `test_finish_derives_the_run_outcome_from_its_attempts:710` (7 cases) + `:790` | Yes | all-failed branch → `if False` ⇒ 1 failed |
| Terminal no-regression (explicit and derived paths) | `test_finish_honours_an_explicit_outcome_and_never_regresses_a_terminal_one:749` + `:812` | Yes (both raise `already finished`; stored row asserted unchanged) | guard → `if False` ⇒ 1 failed |
| Per-method commit boundary | `test_committed_writes_are_visible_outside_the_writing_connection:1142` | Yes (a second connection sees each commit; a demoted commit leaves `COUNT(*)` at 0) | — (assertion-pinned) |
| Attempt evidence append-only per `(run_id, part)` / re-attemptable later | `test_subtitle_attempt_is_append_only_per_part_and_run:1024`, `test_no_subtitle_is_evidence_and_the_part_stays_reattemptable:907` | Yes | CHECK in `schema-transcripts.sql:86-95` + PK pinned by `test_one_outcome_per_attempted_part_per_run:1470` |
| Order/overlap preserved verbatim (M3) | `test_segments_keep_the_callers_order_and_overlaps_verbatim:1754` (reversed + overlapping body; ordinals asserted; digest ≠ sorted-body digest; read-back order) | Yes | — (assertion-pinned; double-sided) |
| Enumeration order keys (focus excluded: proved live by the Task-3 revalidation) | `test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt:1360`, strengthened by `5f93e05` | Yes | peer probes: unbounded-only and `LIMIT`-only swaps each fail alone (`:1378`, `:1395`); `drop_bvid` fails at index 0 |
| View-backed reads are never re-derived (D5) | `test_read_paths_consume_the_views_instead_of_re_deriving_them:1625` | Yes (`DROP VIEW` → `OperationalError` on `v_pending_subtitles` ×2 and `v_video_parts`) | — (drop-the-relation proof) |
| Sidecar guard **armed** (D2) | `test_storage_paths_never_read_or_write_a_legacy_sidecar:1855`; arming proof `:1892-1897`; empty record `:1920`; file set + poison bytes `:1922-1930` | Yes (an unarmed guard is caught by the `pytest.raises(AssertionError, match="opened the sidecar")` self-proof) | mutation of a read path caught only for the `open` channel; declared reach note stands |
| Schema contract (partial index scope, CHECK matrix, bootstrap matrix, column/index manifests) | `test_subtitle_content_index_is_partial_over_the_caption_kinds:1156`, `test_attempt_check_matrix_accepts/rejects_*:1432/:1453` (5 legal / 8 illegal), `test_schema_inspection_matches_the_declared_contract:856`, `test_bootstrap_leaves_a_pre_iteration_database_untouched:1087`, `test_bootstrap_reapplies_the_contract_to_a_current_database:1033` | Yes | Task-1 record: dropping the index `WHERE` ⇒ 2 failed; unconditional script ⇒ `no such column: language`; weakening the `no-subtitle` CHECK arm ⇒ 5 failed |
| Immutability mechanism 1 ("no code path issues UPDATE/DELETE") | **no named test** | **No** — inspected invariant only (see Suggestion 2) | — |

Net: 15 of the 16 high-value guards are falsifiable by a named test that exists in the branch; the sixteenth is an inspected code-shape claim whose *observable consequence* (v1 byte-identity, RESTRICTed deletes, rollback) is pinned by tests.

## Assessment of the resumed Task-3 WIP fixes D1–D5 (Assignment focus 5)

Judged from the committed `1019000` / `5f93e05` source, not from the resume report:

- **D2 (the important one) — closed, and the fix is the right shape.** The old guard patched Python's `open` but never proved the patch could fire, so an empty record proved nothing (SQLite reaches the file through its own C library). The committed test now *forces* the intercept to fire on a deliberate sidecar open, asserts the recorded path, clears the record, runs every write and read path, and only then requires `opened == []` (`:1892-1920`). The evidence is therefore self-proving. This is the strongest single improvement in the branch.
- **D1 — closed.** `test_list_selected_parts…:1578-1579` now makes real claims about the explicitly selected part (`rows[0]["video_part_id"] == parts[0]`, cid/order asserted at `:1559-1585`) instead of the accidental `stored.transcript_id == rows[0]["video_part_id"]` coincidence.
- **D3 — closed.** All four `run_id`-carrying methods are parametrized through one shared-path test (`:1797-1852`), including `start_acquisition_run`, with byte-identical messages asserted.
- **D4 — closed, and generalized:** every added line in the branch is ≤ 93 chars (verified across all 8 files).
- **D5 — closed.** The three view-backed readers are proved to read the views by dropping them (`:1643-1651`); the wording correction ("three", not "four") is in the ledger, and the two `transcripts`-table readers are correctly not in that set.
- **Residual weakness after D1–D5, re-judged independently:** nothing in the fix wave is still weak. Two boundary notes remain, both correctly disclosed rather than papered over: (i) the sidecar guard's declared reach is the Python `open` channel plus the file-set/poison-bytes layers for writes — an `os.open`-based *read* would evade it, while the property holds by construction (no file I/O and no sidecar literal in `src/bili_asr/storage/*.py` beyond the two package-resource schema reads, which I re-checked); (ii) the dropped-`page_index` mutation class still passes for the reason the peer revalidation recorded (helper-expressiveness limit) — the locked order is unchanged in both guarded queries (`:1110`, `:1117`).

## Re-judged L2 severity

I independently re-judged the three task reviews' dispositions and agree with all of them, including the two that were *not* code changes: (a) `TranscriptRecord` was a genuine spec §4 omission, now covered by the dated PM note in the spec (`specs/transcript-storage.md:415-416`) — the DTO is required by the §4 signatures, so shipping it is not scope creep; (b) the M2 message tightening loses no pinned contract. No L2 Minor is re-opened. The only L2-shaped item I would raise beyond them is Suggestion 2 below (test strength), which is new to this seat.

## Findings

### 🔴 Critical

None.

### 🟡 Warning

None.

### 🟢 Suggestion

- **[QC2-S1] The write path does not scope an attempt to its run (`kind` / `selector`), so a wrongly-scoped attempt is silently invisible to the backlog.** `record_acquired_transcript` (`database.py:871-890`) and `record_subtitle_attempt` (`:983-1000`) validate the run's *existence* only. A caption attempt recorded under an `acquisition_runs` row whose `kind` is `audio`/`asr` is accepted, and `v_pending_subtitles` filters `ar.kind = 'subtitle'` (`schema-transcripts.sql:120`), so `attempted` stays `0` and the part is enumerated as never-attempted even though an attempt row for it exists — the bounded-run rotation the plan's Done criteria promise (`attempted ASC, last_attempt_at ASC, …`) then cannot advance for that part. The affected write is impossible for today's only caller (the CLI plan commits to `kind='subtitle'` at `20260911-subtitle-cli-cutover.md:151`), and the implementer disclosed the omission (`implementer-task-2-report.md:242-247`), so this is a latent contract looseness, **not** rework. *Fix if wanted:* reject a run whose `kind != 'subtitle'` in both write paths (one SELECT is already there), or record the decision in the spec as an explicit precondition on the CLI service.
  - Verification: diff/read/grep anchor
  - Expected vs observed: expected — the repository that accepts only caption `source_kind`s (`ALLOWED_CAPTION_SOURCE_KINDS`, `:873-875`) binds its evidence to a subtitle run, or documents why it does not; observed — any run id is accepted and the mis-scoped evidence vanishes from the pending relation
  - Source Type: deep-lens: Correctness Lens · Confidence: High (impact), Medium (severity — caller-constrained today)

- **[QC2-S2] Immutability "mechanism 1" (no `UPDATE`/`DELETE` code path) is an inspected invariant with no test that fails if it is reverted.** The plan and spec both count "no code path issues `UPDATE`/`DELETE` against the transcript tables" as one of three independent enforcement mechanisms (plan Global Constraints / spec §2.6), and the implementer deliberately added no source-scan test (`implementer-task-2-report.md:270-274`). I confirmed the claim by `grep` over the whole `src/` tree (the only `UPDATE` touching the new tables is the guarded `acquisition_runs.outcome` transition at `:823-830`), so nothing is currently wrong — but a future contributing `UPDATE`/`DELETE` against `transcripts`/`transcript_segments`/`acquisition_attempts` would fail **no** named test unless it also perturbed an asserted value. *Fix if wanted:* one static assertion over `src/bili_asr/storage/*.py` that the three tables appear in no `UPDATE`/`DELETE`/`INSERT OR REPLACE` statement (the test class already reads source text: `test_schema_sql_is_declared_and_read_as_package_resource:366`).
  - Verification: diff/read/grep anchor
  - Expected vs observed: expected — each of the three stated immutability mechanisms has a named failing test on revert; observed — mechanisms 2 and 3 do, mechanism 1 is review-only
  - Source Type: deep-lens: Correctness Lens · Confidence: High

## Source Trace

| Finding ID | Source Type | Source Reference | Confidence |
|---|---|---|---|
| F-001 (QC2-S1) | deep-lens: Correctness Lens | `src/bili_asr/storage/database.py:871-890`, `:983-1000`; `schema-transcripts.sql:120`; `implementer-task-2-report.md:242-247` | High (impact) / Medium (severity) |
| F-002 (QC2-S2) | deep-lens: Correctness Lens | plan Global Constraints + `specs/transcript-storage.md:287-298`; `database.py:823-830`; `implementer-task-2-report.md:270-274` | High |
| Verification (no finding) | git-diff / read / grep | `6ee7c6a..5f93e05` — 8 files, `+4028/−58`; `git diff --check` clean; `database.py:224-237`, `:836-959`; `tests/test_transcript_repository.py:294,326,357,497,582,608,651,710,749,812,907,1024,1070,1142,1360,1625,1754,1855`; `tests/test_storage_schema.py:856,1033,1087,1156,1432,1453,1470` | High |

Every finding above carries `Verification` + `Expected vs observed`; no finding is reported without an anchor I read myself.

## ⚠️ For PM (process, not evaluation)

Neither item affects the diff, the verdict, or a residual:

1. **The plan file's bookkeeping is stale relative to the ledger.** `.mstar/plans/20260911-transcript-storage.md` still reads `Status: Todo`, all Task checkboxes `- [ ]`, `PM lock: pending`, while the ledger records three implemented + L2-Approved tasks, a revalidated fix wave, and the engine snapshot reports `InReview`. The sibling Done plan (`20260911-subtitle-gateway.md`) carries `Status: Done` with 30/30 boxes ticked, so the convention is to reconcile the file — worth doing before this plan's Done so the Review/QA Gate Summaries are written onto a truthful artifact.
2. **Two recorded carries are correctly owned elsewhere, re-verified rather than taken on trust:** the stale `docs/metadata-storage.md` wording (CLI plan `:229`, `:243`) and the `<command>: … (delete <root>/archive.db …)` rebuild line (CLI plan `:56-58`, `:169-170`, `:299-300`). No action needed now; they must land before the CLI plan's Done.
3. **Handoff note for the next iteration (owner: the plan's Durable Roadmap entry for SRT/TXT/MD projections):** after a re-acquisition whose content *reverts* to an older body, `read_transcript(version=None)` returns `MAX(version)` (`:1032-1037`) while the newest successful acquisition's attempt row references the *older* version the content matched (`:933-936`) — both facts are stored, and spec §2.6/§6 lock "the latest version is what a default read returns". A future projection step must therefore choose deliberately between "newest version" and "newest observation" instead of assuming they coincide.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 2 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

No unresolved Critical or Warning; both Suggestions are optional hardening with a stated "no rework required" disposition, and every evidence channel (range, package, source, tests) was intact, so `Approve` is warranted rather than `Needs Discussion`. Runtime acceptance remains the mandatory QA gate's (L4) — I judged the write path from source and cited the peer-reproduced focused runs as evidence, per the L3 boundary.
