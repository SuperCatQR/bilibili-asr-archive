# Task 2 report — TranscriptRepository writes with content-based idempotency

- Plan: `.mstar/plans/20260911-transcript-storage.md` (task 2 of 3)
- Working branch: `feature/20260911-transcript-storage`
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage`
- Commit: `f3cd735` — `feat(storage): write transcripts idempotently with acquisition process records`
- Base: `d4cae24` (Task 1, review Approved)
- Status: **DONE**
- Delegation: none (leaf executor; no subagent dispatched). Harness files written: this report only.

## Implemented / attempted

### 1. `start_acquisition_run(run: AcquisitionRunRecord) -> None` — `database.py`

Inserts the run with `credential_present` as the table's `0/1`, then commits **its own**
insert (the `start_run` discipline): a part that fails later rolls back without losing its
run parent. A duplicate `run_id` raises `sqlite3.IntegrityError` and leaves the stored row.

### 2. `finish_acquisition_run(run_id, finished_at, *, outcome=None) -> str` — `database.py`

- Arguments validated first (`run_id` → `_text`; `finished_at` → `_integer(minimum=0)`; an
  explicit `outcome` → `_choice` over `{complete, partial, failed}`), then DB state:
  unknown run → `sqlite3.IntegrityError("unknown run_id: …")`; stored outcome not
  `'running'` → `sqlite3.IntegrityError("run … already finished with outcome …")`;
  `finished_at` below the **stored** `started_at` → `ValueError` and no write.
- **Terminal outcomes cannot be regressed**: both the pre-check and the guarded
  `UPDATE … WHERE run_id = ? AND outcome = 'running'` (with a `changes() != 1` post-check)
  refuse to move a finished run, and neither outcome nor `finished_at` changes.
- **Derivation** when no explicit outcome is given (`_run_outcome_from_attempts`, one
  `GROUP BY outcome` query): `failed` when every attempt of a non-empty set failed;
  `partial` when failed and non-failed attempts coexist; `complete` otherwise, including a
  run with **zero** attempts (empty bounded work set). An explicit outcome wins over the
  derivation. The commit closes the single terminal transition; the resolved outcome is
  returned.

### 3. `record_acquired_transcript(...) -> TranscriptWriteResult` — one transaction

Order inside the single transaction: `_require_video_part` → `_require_acquisition_run` →
content-identity lookup → (append `version = COALESCE(MAX(version), 0) + 1` + its segments |
nothing) → attempt row → commit, or roll back wholly.

- **Hash**: `sha256(json.dumps([[start_ms, end_ms, text], …], ensure_ascii=False,
  separators=(",", ":"))).encode("utf-8")).hexdigest()` — spec §2.2 verbatim, over the
  trimmed text, and **not** over the identity key (part id / source kind / language).
- **Idempotency**: a version of `(video_part_id, source_kind, language)` that already
  carries the hash means *write nothing*; the attempt is `'unchanged'` and references that
  existing version. Otherwise the next version is appended (`'stored'`). Reverting to older
  content is therefore `'unchanged'` against the older version, and the attempt row still
  records that the acquisition happened and when.
- **Argument validation before any SQL**: `run_id` (`_text`), `video_part_id ≥ 1`,
  `source_kind ∈` caption kinds, `language` trimmed and non-empty, non-empty `segments`
  tuple of `TranscriptSegmentRecord`, non-negative clocks, `finished_at ≥ started_at`.
- **Normalization at this boundary** (`_canonical_segments`): text and language stored and
  hashed **trimmed**; per-segment re-validation of `start_ms ≥ 0`, `end_ms > start_ms`, and
  the `MAX_TIMELINE_MS` ceiling; ordinals assigned by position so upstream order is
  preserved verbatim, overlaps included.
- **Immutability**: the method only ever `INSERT`s; no `UPDATE`/`DELETE` against
  `transcripts` / `transcript_segments` exists in the module, and a re-acquisition leaves the
  earlier version byte-identical.

### 4. `record_subtitle_attempt(...) -> None` — one transaction

`'no-subtitle'` / `'failed'` only, with the CHECK matrix enforced in Python as well:
`failed` requires a bounded `error_code` (`validate_error_code`); `no-subtitle` carries
`NULL` or exactly `'not_found'`; neither references a transcript (the method has no such
parameter and always binds `NULL`). Append-only per `(run_id, video_part_id)`; the run's
`credential_present` stays the run's fact. No terminal per-part state exists, so the part is
re-attemptable in a later run.

### 5. Supporting deltas

- `storage/models.py`: `MAX_TIMELINE_MS = 10**12` (documented ceiling),
  `ALLOWED_CAPTION_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS - {"asr-local"}`, `_integer` gained
  an optional `maximum` (additive; every existing caller unchanged), and the two docstrings
  M1 concerns were corrected (see *Carried items*). Both new names are exported from
  `bili_asr.storage` (package root) and `bili_asr.storage.models`.
- `storage/database.py`: `TranscriptRepository` with the class docstring carrying the
  commit-boundary matrix and the "do not compose these methods inside
  `MetadataRepository.transaction()`" rule; module docstring now names both repositories;
  `TranscriptRepository` added to `database.__all__`.
- New tests: `tests/test_transcript_repository.py` (23 test functions, 48 collected cases,
  1132 lines).

## Carried items settled

### M1 (Task-1 review) — the trimming site: **the repository, not the caller**

**Decision: `TranscriptRepository` strips.** `record_acquired_transcript` stores *and*
hashes `segment.text.strip()`, and stores `language.strip()`; only the leading/trailing
whitespace is removed, the string inside is kept byte-for-byte (control characters included,
as Task 1 shipped it).

Why this route and not "name the gateway as the trimming site":

- The alternative is a spec edit, which this task may not write (harness artifact), and it
  would make §5's "`text` is stored trimmed" true only for callers that happen to trim.
  Stripping at the storage boundary makes it true for every caller, which is what §5 says.
- It keeps content identity stable where it matters: `"  第一句\t"` and `"第一句"` are one
  caption, so a caller's whitespace can never append a duplicate version of content the
  archive already holds (pinned by
  `test_text_is_stored_and_hashed_trimmed_but_kept_verbatim_inside`).
- Both readings are now dead: `_caption_text`'s docstring no longer claims "stored as
  upstream returned it" (it now names the repository as the trimming site), and
  `TranscriptSegmentRecord`'s docstring says the record carries the caller's text while the
  storage boundary stores/hashes the trimmed form.

### S11 (folded into the brief) — the converted-timeline ceiling

- **Ceiling: `MAX_TIMELINE_MS = 10**12` ms** (10⁹ s ≈ **31.7 years**). A segment is rejected
  when `start_ms > MAX_TIMELINE_MS` or `end_ms > MAX_TIMELINE_MS`; a value exactly at the
  ceiling is accepted.
- **Site: `TranscriptRepository`** (the SQL boundary), via the documented constant in
  `storage/models.py`. The segment DTO deliberately still accepts an unbounded integer —
  that site decision is asserted by the test, so moving the bound into the DTO is a visible
  change, not a silent one.
- **Error: bounded `ValueError`** — `segments[i].end_ms must be at most 1000000000000`
  (same for `start_ms`), raised before any SQL. No `OverflowError` can escape: with the
  guard removed, `10**19` reaches SQLite and raises
  `OverflowError: Python int too large to convert to SQLite INTEGER` (proved red, see
  *Tests → red evidence*), and `10**12 + 1` would be stored silently as a nonsense
  timestamp.
- Pinned by `test_timeline_ceiling_is_the_storage_boundarys_rejection`.
- **Spec wording handoff (not mine to write):** plan Task 2 asks for the ceiling to be
  recorded in the spec's normalization section (§5). The iteration spec is a harness
  artifact this task may not edit, so the value lives in the report, in `MAX_TIMELINE_MS`
  and in its docstring; see *Handoffs*.

## Transaction boundaries and idempotency semantics

| Method | Transaction | Commit | Rollback | Touches |
|---|---|---|---|---|
| `start_acquisition_run` | single insert | own commit (run parent survives later failures) | — | `acquisition_runs` |
| `finish_acquisition_run` | single read + guarded update | own commit | nothing written on a rejected call | `acquisition_runs` |
| `record_acquired_transcript` | **one** group: part/run checks → identity lookup → version + segments → attempt row | one commit at the end of the group | any failure (FK/CHECK/PK, e.g. an attempt row for the same `(run_id, video_part_id)`) rolls back the whole call, so no version exists without its attempt evidence | `transcripts`, `transcript_segments`, `acquisition_attempts` |
| `record_subtitle_attempt` | one group: part/run checks → attempt row | own commit | rolled back wholly on failure | `acquisition_attempts` |

- One shared discipline: the module-level `_transaction(connection)` contextmanager (commit
  on success, rollback + re-raise on any exception). `MetadataRepository.transaction()`
  delegates to it — behaviour-identical de-duplication, disclosed below.
- Idempotency is content-based: the hash covers the ordered `[start_ms, end_ms, text]`
  triples only; identical normalized content under one identity writes **no** row and records
  `'unchanged'` pointing at the existing version; changed content appends `MAX(version) + 1`;
  reverted content is `'unchanged'` against the earlier version. The DB enforces the same
  fact independently through `UNIQUE(video_part_id, source_kind, language, version)` and the
  partial unique index `ux_transcripts_subtitle_content`.
- Attempt evidence is append-only and never terminal: `PRIMARY KEY (run_id, video_part_id)`
  bounds it to one outcome per part per run, and a later run records the same part again.
- Never recomputed: appending an attempt to a run that already finished leaves the run's
  outcome and `finished_at` untouched (precedented by the metadata path's late-page
  discipline; pinned by `test_finish_records_an_abnormal_failure_without_recomputing_it`).

## Tests

```bash
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_transcript_repository.py -v   # focused
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q                                      # full offline suite
```

| Command | Result |
|---|---|
| focused `tests/test_transcript_repository.py` | **48 passed in 2.43s** |
| focused + `tests/test_metadata_repository.py` + `tests/test_storage_schema.py` | **105 passed in 3.22s** |
| full suite, before any change (baseline) | **1120 passed, 3 skipped in 45.24s** |
| full suite, after the change | **1168 passed, 3 skipped in 45.89s** |

`+48` tests, all in the new `tests/test_transcript_repository.py`; the 3 skips are the
pre-existing ones. No existing test was modified, relaxed, skipped or deleted (the diff
touches no test file other than the new one).

### What the new assertions pin

| Test (cases) | Pinned assertion |
|---|---|
| `test_first_write_stores_version_one_with_ordinal_segments_and_its_attempt` | `stored`, version 1, exact `transcripts` row tuple (kind/language/`model_id IS NULL`/hash/`created_at`), exact segment rows with ordinals `0..N-1`, exact attempt row, `ingestion_runs`/`ingestion_pages` counts `0`, `PRAGMA foreign_key_check` empty |
| `test_repeat_with_identical_content_writes_nothing_and_reports_unchanged` | `unchanged` + same `transcript_id`/version/hash, one `transcripts` row, no duplicate segments, and one attempt row per run (`stored`, then `unchanged`) |
| `test_text_is_stored_and_hashed_trimmed_but_kept_verbatim_inside` (M1) | padded text is stored trimmed, its hash equals the trimmed body's hash, and the trimmed repeat is `unchanged` |
| `test_content_hash_is_the_sha256_of_the_canonical_segment_json` | hash equals an independently computed §2.2 digest, is 64 lowercase hex, equals the stored column, differs from three looser JSON spellings, and is **independent of the identity key** (same body on another part → same hash, own version 1) |
| `test_changed_content_appends_version_two_and_leaves_version_one_untouched` | version 2 + own segments; version 1's row tuple and segments byte-identical; `created_at` of v2 stored |
| `test_content_that_reverts_to_an_earlier_version_is_unchanged_and_points_at_it` | revert → `unchanged` at version 1 / v1 `transcript_id`; still 2 versions; reverting to the newest is `unchanged` at version 2 |
| `test_content_identity_is_scoped_to_the_identity_key` | `" zh-CN "` stored as `zh-CN`; same body under `subtitle-ai`/`ai-zh` is a separate identity (own version 1, same hash); padded language collides onto the trimmed identity; a changed body advances only that identity |
| `test_invalid_write_arguments_are_rejected_without_writing` (11 cases) | empty segments, non-`TranscriptSegmentRecord` member, `video_part_id = 0`, `video_part_id = True`, `source_kind = "asr-local"`, unknown `source_kind`, blank language, `language = None`, blank `run_id`, `finished_at < started_at`, negative `created_at` → `ValueError`/`TypeError` and `(0, 0, 0)` rows |
| `test_unknown_part_and_unknown_run_fail_the_whole_write` | `IntegrityError` matching `unknown video_part_id` / `unknown run_id`, nothing written, and the run parent still `('running', None)` |
| `test_attempt_conflict_rolls_back_the_version_it_would_have_stored` | duplicate `(run_id, video_part_id)` → `IntegrityError`, no version 2, v1 row+segments unchanged, exactly one attempt row; a later run then stores version 2 normally (no poisoned state) |
| `test_schema_foreign_keys_reject_orphans_and_restrict_deletes` | attempt → unknown transcript rejected; `DELETE` of the transcript / the part / the run rejected (RESTRICT) with all rows intact |
| `test_finish_derives_the_run_outcome_from_its_attempts` (7 cases) | `complete` for 0 / `stored` / `no-subtitle` / `stored+no-subtitle`; `partial` for `stored+failed` and `no-subtitle+failed`; `failed` for `failed+failed`; stored `('outcome', 500)` |
| `test_finish_honours_an_explicit_outcome_and_never_regresses_a_terminal_one` | explicit `complete` over an all-failed run; re-finish (explicit or derived) → `IntegrityError` matching `already finished`; row unchanged at `('complete', 500)` |
| `test_run_outcome_derivation_reads_only_its_own_attempts` | a failed attempt in run 2 does not make run 1 (zero attempts) anything but `complete` |
| `test_finish_records_an_abnormal_failure_without_recomputing_it` | zero-attempt run finished explicitly `failed`; later stored evidence does not rewrite `('failed', 500)` |
| `test_finish_validates_its_arguments_and_the_run_it_targets` | unknown run → `IntegrityError`; `outcome="running"`/`"unknown"` → `ValueError`; `finished_at=True` → `TypeError`; blank `run_id` → `ValueError`; `finished_at <` stored `started_at` → `ValueError` with the run still `('running', None)`; zero-attempt run at exactly `started_at` → `complete` |
| `test_start_acquisition_run_rejects_a_duplicate_run_id` | duplicate → `IntegrityError`; the full stored run tuple (selector pair, `credential_present` 0, clocks) is unchanged |
| `test_no_subtitle_is_evidence_and_the_part_stays_reattemptable` | exact `no-subtitle` rows (`NULL` and `not_found`), still no transcript, `v_pending_subtitles` shows `attempted = 1` with the newest outcome/code/`credential_present`; a later run stores a transcript normally under a new run and the part leaves the pending set; all three attempt rows preserved |
| `test_subtitle_attempt_rejects_every_illegal_outcome_and_code` (10 cases) | `stored`/`unchanged`/unknown outcome, `failed` without a code, 65-char code, raw JSON code, `no-subtitle` + `timeout`, non-string code, `video_part_id = 0`, bad clock → `ValueError`/`TypeError`, no row |
| `test_subtitle_attempt_is_append_only_per_part_and_run` | duplicate `(run, part)` → `IntegrityError` with the first row intact; the same evidence is accepted under a later run |
| `test_timeline_ceiling_is_the_storage_boundarys_rejection` (S11) | `MAX_TIMELINE_MS == 10**12`; a segment at the ceiling is stored; `end_ms = ceiling + 1` → `ValueError` matching `must be at most 1000000000000`; `start_ms = ceiling + 1` and `end_ms = 10**19` → `ValueError`; no row written; and the DTO still accepts `10**19` (the bound's documented site) |
| `test_constructor_requires_the_open_database_connection_state` | non-connection → `TypeError`; missing `sqlite3.Row` row factory → `TypeError`; `PRAGMA foreign_keys` off → `ValueError` (same contract as `MetadataRepository`) |
| `test_committed_writes_are_visible_outside_the_writing_connection` | a second connection sees the run after `start_acquisition_run`, the version + 2 segments + attempt after one transcript write, the `no-subtitle` row after `record_subtitle_attempt`, and `('complete', 400)` after `finish_acquisition_run` — i.e. each documented own-commit is real |

### Red evidence (non-vacuity)

Seven deliberate mutations, each applied to the committed file, run against the focused
module, then reverted with `git checkout --` (tree verified clean afterwards):

| Mutation | Focused result |
|---|---|
| remove `maximum=MAX_TIMELINE_MS` (2 call sites) | `1 failed` — `DID NOT RAISE ValueError` (the out-of-bound value would be stored silently) |
| drop `separators=(",", ":")` from the canonical JSON | `1 failed` — the canonical-hash test |
| `text = segment.text.strip()` → `text = segment.text` | `1 failed` — the M1 trimming test |
| `if existing_row is None:` → `if True:` (skip content identity) | `1 failed` — the idempotent-repeat test (a second version appears) |
| `if failed and failed == attempts:` → `if False:` | `1 failed` — the `failed`-derivation case (`partial`/`complete` still hold, as expected) |
| `with _transaction(...)` → `if True:` in the transcript write | `1 failed` — the rollback test (the would-be version 2 survives the attempt-conflict failure) |
| `if run_row["outcome"] != "running":` → `if False:` (this literal line also occurs in the shipped `MetadataRepository.finish_run`, so the mutation touched both; both were reverted) | `1 failed` — the terminal-regression test (the guard's own bounded message is pinned) |

Direct probe of the S11 failure mode with the ceiling removed (same temporary mutation, then
reverted):

```
raised OverflowError: Python int too large to convert to SQLite INTEGER
```

versus the committed behaviour, where the same call raises the bounded `ValueError`.

## Files changed

- `bilibili-asr-archive/src/bili_asr/storage/database.py` (+481/−18)
- `bilibili-asr-archive/src/bili_asr/storage/models.py` (+38/−8)
- `bilibili-asr-archive/src/bili_asr/storage/__init__.py` (+6)
- `bilibili-asr-archive/tests/test_transcript_repository.py` (**new**, 1132 lines)
- Commit `f3cd735` on `feature/20260911-transcript-storage` only; no push, no other branch,
  no harness artifact other than this report.

## Decisions disclosed (with the alternative I rejected)

1. **`source_kind` is restricted to the two caption kinds.** `asr-local` raises `ValueError`
   ("must be one of: subtitle-ai, subtitle-cc"), and `ALLOWED_CAPTION_SOURCE_KINDS` names
   exactly the kinds the partial content index covers. Rationale: spec §2.7 keeps
   `asr-local` (and its model identity) with the audio/ASR iteration, the method carries no
   `model_id`, and the index is deliberately caption-scoped — writing a NULL-model
   `asr-local` row here would pre-empt that decision and would not be content-protected by
   the index. Rejected alternative: accept `ALLOWED_SOURCE_KINDS` and let the caller decide;
   that leaves a half-specified write path reachable.
2. **The run's `kind` is not checked.** `record_acquired_transcript` /
   `record_subtitle_attempt` accept any acquisition run (FK-scoped to `acquisition_runs`);
   the spec's §4 signature takes a bare `run_id` and scopes nothing by kind, and any
   wrong-kind evidence is still bounded and visible (the pending view filters
   `kind = 'subtitle'`, so it cannot leak into the subtitle backlog). Disclosed so the
   reviewer can ask for a `kind = 'subtitle'` precondition if the plan wants one.
3. **Attempt evidence may still be appended to a finished run**, and the run's outcome is
   then *not* recomputed. Precedent: the shipped metadata path persists a late failed page
   while the run stays terminal. The run outcome is a fact recorded at finish time; the
   evidence is append-only per run. Pinned by a test.
4. **Behaviour-preserving de-duplication of shipped code.** `MetadataRepository.__init__`
   now calls the new shared `_validate_connection`, and `MetadataRepository.transaction()`
   delegates to the new shared `_transaction` contextmanager. Same checks, same messages,
   same commit/rollback semantics (all metadata tests green; `storage/` still imports
   nothing from `sources/`). Rationale: one connection contract and one transaction
   discipline for the module instead of two copies; the diff is exactly the moved body.
5. **`_integer` gained an optional `maximum`.** Additive keyword; every existing caller and
   message is unchanged, and the ceiling reuses the module's one integer validator ("same
   validation helpers", spec §4). The repository imports the shipped private validators
   (`_text`, `_integer`, `_choice`, `_error_code`) from `storage.models` on purpose: the
   storage package validates against one contract, and no second copy of those rules exists.
6. **The shape re-checks at the DB boundary are defence in depth.** `end_ms > start_ms >= 0`
   and "text non-empty after trimming" cannot be triggered through a validated
   `TranscriptSegmentRecord` (its `__post_init__` rejects them first); they are kept because
   spec §5 mandates the repository re-validate rather than trust the caller. The reachable
   half of that same loop — the ceiling — is what the S11 test pins. Nothing else in
   `_canonical_segments` is unreachable: the non-DTO `TypeError`, the empty-tuple
   `ValueError`, and the ceiling `ValueError` all have passing tests.
7. **Immutability mechanism 1 is not pinned by a source scan.** I did not add a
   "no `UPDATE`/`DELETE` in the source" test: the guarantee is pinned behaviourally (v1 row
   and segments byte-identical after a v2 write; rollback leaves nothing behind;
   transcript/part/run deletes RESTRICTed). Task 1's review already treats the code-path
   property as an inspected invariant; a grep-style test would be a new, brittle test class.

## Self-review notes

- `git diff --check` clean; `git status --porcelain` empty before the commit and after all
  mutation runs; the tree is byte-identical to `f3cd735`.
- Transaction boundaries are disclosed above per method and restated in the class docstring
  together with the "do not compose inside `MetadataRepository.transaction()`" rule.
- Every new assertion is listed in the *What the new assertions pin* table, including the
  assertions that go beyond the brief's checklist (pending-view evidence, no metadata-table
  writes, commit visibility from a second connection, the constructor contract,
  `MAX_TIMELINE_MS`'s value and site, explicit-outcome precedence, abnormal failure,
  cross-run derivation isolation).
- No `UPDATE`/`DELETE` statement against `transcripts` / `transcript_segments` was added;
  the only writes are `INSERT`s plus the acquisition run's own guarded `UPDATE`.
- Offline and deterministic: caller-supplied clocks only (199/300/400-style literals), no
  network, no wall clock, no randomness; `PRAGMA foreign_keys = ON` on every connection and
  every new FK is `ON DELETE RESTRICT`.
- Naming: every public name is spec-locked (`TranscriptRepository`,
  `start_acquisition_run`, `finish_acquisition_run`, `record_acquired_transcript`,
  `record_subtitle_attempt`). Before adding anything I ran the `naming-analyzer` check over
  the new names; the additions are `MAX_TIMELINE_MS` (unit-suffixed, positive, not
  mistakable for a duration), `ALLOWED_CAPTION_SOURCE_KINDS` (mirrors the shipped
  `ALLOWED_*` surface), `_validate_connection`, `_transaction`, `_language_code`,
  `_segment_content_sha256` (deliberately *not* `_content_sha256`, which is the models'
  field validator), `_TERMINAL_ACQUISITION_OUTCOMES`,
  `_NO_TRANSCRIPT_ATTEMPT_OUTCOMES`, `_require_video_part`, `_require_acquisition_run`,
  `_canonical_segments`, `_next_transcript_version`, `_run_outcome_from_attempts` — no
  abbreviation, no ambiguity, each mirroring an existing sibling.
- STOP conditions: none triggered. The single-transaction write satisfies the FK order
  (parent rows exist first, the attempt row last) and immutability; the process-record shape
  records bounded evidence without touching `ingestion_runs` (asserted); idempotency uses
  content hashes only, no raw payload; no migration/`ALTER TABLE` code was added; the
  metadata tests stay green (`105 passed` focused, full suite green).
- Scope discipline: no plan / snapshot / status / compass / spec / iteration file was
  written; the only file outside the worktree is this report. No residual, no TODO, no
  `simplify:` marker, no dead import was left behind.

## Handoffs (not mine to execute)

1. **Spec §5 wording (owner: PM / architect).** Plan Task 2 asks for the ceiling to be
   recorded in the spec's normalization section; harness artifacts are outside this task's
   write scope. Please record: "the repository rejects a `start_ms`/`end_ms` above
   `MAX_TIMELINE_MS` (`10**12` ms, ≈31.7 years) with a bounded `ValueError`". The value and
   its rationale are in `storage/models.py` and this report.
2. **M1's documentation half (owner: PM / architect, optional).** The trimming rule is now
   implemented at the storage boundary and both docstrings say so; §5's existing sentence
   ("`text` is stored trimmed") is already true and needs no edit — flagged only in case the
   reviewer prefers §5 to name the repository explicitly.
3. **Task 3** owns the read paths and the pending-enumeration order; this task's tests
   deliberately touch the view only where the write path's evidence lands in it.
4. `docs/metadata-storage.md` remains the CLI plan's deliverable (Task 1's known staleness);
   untouched here.
