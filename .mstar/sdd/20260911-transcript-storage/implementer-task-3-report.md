# Task 3 report — Reads, pending enumeration, and contract evidence

- Plan: `.mstar/plans/20260911-transcript-storage.md` (task 3 of 3)
- Working branch: `feature/20260911-transcript-storage`
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage`
- Commit: `1019000` — `feat(storage): read transcripts and enumerate the captionless backlog`
- Base: `f3cd735` (Task 2, 116 focused tests green; the WIP carried by this resume)
- Status: **DONE** — implementation complete on the working branch. State transitions
  (`InReview` → `Done` after QC tri + the mandatory QA gate) remain the PM's.
- Delegation: none. Leaf executor; no subagent dispatched, no plan/snapshot/status/spec
  write, no push, no work outside the feature branch. Harness file written: this report only.

## Resume context (why this report starts with an audit)

Two prior runs of this task were killed mid-flight, leaving **uncommitted WIP** at `f3cd735`.
Nothing in it was trusted on the strength of its own docstrings or of the "116 passed" figure:
the diff was read line by line, each brief item was located in the code, and the behavioural
claims that a green test *could* have been passing vacuously were probed by deliberate
mutation (see **Non-vacuity evidence**). Four defects and one coverage gap surfaced (D1–D5);
they are listed below with the fix. Everything else in the inherited WIP was found genuinely
implemented and was kept unchanged.

## Audit of the inherited WIP

| Brief item | Located in the WIP | Audit verdict |
|---|---|---|
| `read_transcript` — latest by default, explicit version on request, `None` when absent | `database.py:1011` | **genuine** — `ORDER BY version DESC LIMIT 1` on the default path, exact-match on the explicit one; `None` for an absent version, identity (`en-US`), kind (`subtitle-ai`), part (`9999`) and for the `asr-local` reservation; language trimmed exactly as the write path trims it |
| `list_transcript_versions` — oldest first, empty for an absent identity | `database.py:1065` | **genuine** — `ORDER BY version`, all stored columns, identity-scoped |
| `list_selected_parts(bvid, page_index=None)` — over `v_video_parts`, zero rows for an unknown selector | `database.py:1129` | **genuine, one test defect fixed (D1)** — `SELECT vvp.*` with the `bvid` join the view does not carry; `[]` for an unknown bvid and for an unknown `bvid:pN`; not filtered by `processing_status` |
| `list_pending_subtitle_parts(limit=None)` / `count_pending_subtitle_parts()` over `v_pending_subtitles`, locked order, shipped argument-validation discipline | `database.py:1087` / `:1121` | **genuine** — the view is read, the locked key list is verbatim, `limit` reuses the shipped `TypeError`/`ValueError` messages (pinned against `MetadataRepository.list_pending_parts`) |
| Locked ordering pinned by a test | `test_transcript_repository.py:1360` | **genuine and non-vacuous** — insertion order differs from work order; mutation A confirms it fails when the order is dropped |
| E2E evidence (two languages + two versions; stored part excluded; metadata-only part `attempted = 0`; `no-subtitle` part with outcome/timestamp/credential; never-attempted before attempted; re-attempt stores normally under a new run) | tests `:1208`, `:1401`, `:1474` | **genuine** — every listed fact asserted, including `not_found` + `credential_present = 1` and the part leaving the backlog only after a later run stores it |
| `work_id` stays view/computed (no base-table column) | `:1717` | **genuine** — all three views compute it; `UPDATE … SET work_id` against the four transcript tables is rejected |
| No sidecar file read or written by any storage path | `:1851` | **genuine claim, defective evidence — fixed (D2)**: the Python-level open intercept was never armed (nothing below the archive root is opened through Python; SQLite uses its C library), so the recorded-open assertion passed on an empty list |
| Task-1 structural guards stay exact (extend, never weaken) | `test_storage_schema.py` | **genuine** — the WIP only *added* to `EXPECTED_CHECK_ENUMERATIONS` (a `transcript_segments` entry: `ordinal >= 0`, `start_ms >= 0`, `end_ms > start_ms`) and added one test; no existing expectation was relaxed, renamed or deleted |
| M3 — non-monotonic/overlapping body pinned | `:1750` | **genuine and non-vacuous** — reversed, overlapping body; raw ordinal/segment rows asserted, the sorted-body digest asserted different, and the read path asserted to answer the caller order; mutations B1/B2 confirm both halves fail on a sort regression |
| M2 — `run_id` through the common path | `database.py:804` (was the hand-rolled check) | **genuine** — `_text(run_id, "run_id")` in `finish_acquisition_run`, matching `record_acquired_transcript` (`:871`) and `record_subtitle_attempt` (`:983`); **one test gap fixed (D3)** |

## Defects found and fixed

1. **D1 — a coincidence assertion** in `test_list_selected_parts_selects_explicitly_or_returns_no_rows`:
   `assert stored.transcript_id == rows[0]["video_part_id"]` compared two unrelated ids (both
   happened to be `1` in a fresh database) and could never fail for the reason the comment
   claims. Replaced with `stored.version == 1` plus
   `repository.read_transcript(parts[0], "subtitle-cc", "zh-CN") is not None`, which is what
   the comment actually asserts: the explicitly selected part already holds its transcript.
2. **D2 — the sidecar guard was unarmed, so its final assertion was vacuous.** The inherited
   test intercepted `io.open`/`builtins.open` below the archive root and then asserted the
   recorded list was a subset of `{archive.db, archive.db-journal}`. Probed directly (a
   throwaway script monkeypatching the same two names, running `open_database` +
   `TranscriptRepository`): **the recorded list is `[]`** — SQLite opens the database in C, so
   no Python-level open below the archive root ever happens and an empty list satisfies the
   subset check. Fixed by making the guard self-proving before trusting it: the test now
   asserts the intercept *rejects* a deliberate sidecar open (`meta-cursor.json`, recorded as
   exactly that basename) and only then requires the record to be empty for the whole storage
   path, with the write-side evidence (exact file set under the archive root, poison bytes
   unchanged) kept as it was. Mutations D/F1/F2 confirm all three layers now fail on a real
   sidecar read, stray file creation and sidecar rewrite.
3. **D3 — the M2 test did not cover the class's own run-creation entry point.** The test is
   named "…across the class" but only exercised `finish_acquisition_run`,
   `record_acquired_transcript` and `record_subtitle_attempt`. `start_acquisition_run`'s
   `run_id` validation (via `AcquisitionRunRecord.__post_init__` → the same `_text`) is now in
   the same parametrized loop, so all four run_id-carrying methods are pinned to one message
   per failure mode.
4. **D4 — one 108-character line** in the new `test_read_arguments_follow_the_module_validation_discipline`
   parametrization. The project has no linter, but that line was an outlier in its own file
   (the shipped `database.py` and the transcript repository tests both max out at 93
   characters), so it was wrapped to the surrounding style.
5. **D5 — coverage added for finish criterion 2's "never re-derived".** New
   `test_read_paths_consume_the_views_instead_of_re_deriving_them`: after the backlog and the
   explicit selection are shown to answer, `v_pending_subtitles` and `v_video_parts` are
   dropped and the four read methods are required to raise `sqlite3.OperationalError` naming
   the missing view — a re-derived query over the base tables would keep answering. Mutation G
   confirms the pin is live.

No defect required rewriting repository behaviour; the inherited production code was kept
byte-identical except for the M2 line it was already carrying (`deb5a3db…` before and after
the audit), and every test edit above is additive or a strict strengthening.

## Final state of the delivered contract

- `read_transcript(video_part_id, source_kind, language, version=None) -> TranscriptRecord | None`
  — typed record with the whole row plus its segments in ordinal order (verbatim as stored,
  never re-sorted); `source_kind` validated against the full column vocabulary, language
  trimmed, `version` validated before the query.
- `list_transcript_versions(...) -> list[sqlite3.Row]` — one identity, oldest first.
- `list_pending_subtitle_parts(limit=None)` / `count_pending_subtitle_parts() -> int` — read
  `v_pending_subtitles` (`COUNT(*)` over the view, no Python-side re-derivation) with
  `ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC` on both the bounded
  and unbounded paths.
- `list_selected_parts(bvid, page_index=None) -> list[sqlite3.Row]` — `v_video_parts` rows for
  an explicit selection, `[]` for an unknown selector, never status-filtered.
- All five are read-only (no write, no commit) and are documented as such in the
  `TranscriptRepository` commit-boundary docstring beside the write matrix.
- `TranscriptRecord` added to `storage/models.py` (validated dataclass) and exported from
  `bili_asr.storage` / `models.__all__`.

## Tests

```bash
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_transcript_repository.py tests/test_storage_schema.py -q   # focused
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q                                                                    # full offline suite
```

| Command | Result |
|---|---|
| focused, inherited WIP (before the audit) | **116 passed in 3.95s** |
| focused, final (`tests/test_transcript_repository.py` 80 + `tests/test_storage_schema.py` 37) | **117 passed in 3.87s** |
| full offline suite, baseline (stated by the brief, unchanged environment) | 1168 passed, 3 skipped |
| full offline suite, final | **1201 passed, 3 skipped in 47.34s** |

`+33` tests over the baseline: the 32 Task-3 tests the WIP carried (11 plain + 14 + 6
parametrized cases in the repository module, 1 in the schema module) plus the one test added
by D5. The 3 skips are the pre-existing ones (no network/live smoke test was enabled); no
existing test was relaxed, skipped or deleted — every edit in this commit is inside the new
Task-3 test region, and the schema file's existing expectations were only extended.

### What the new assertions pin

| Test (cases) | Pinned assertion |
|---|---|
| `test_read_transcript_returns_the_latest_version_and_keeps_an_older_one_readable` | default read = version 2 with its hash/`created_at`/segments; the same part's `subtitle-ai`/`ai-zh` identity read separately; explicit version 1 still readable byte-identically after v2; padded language reads the trimmed identity; read paths leave the store counts and `connection.in_transaction` untouched |
| `test_list_transcript_versions_lists_one_identitys_versions_oldest_first` | `[1, 2]` versions with their ids/hashes/`created_at`/kind/language, the full stored column set, another identity not mixed in, padded language trims |
| `test_reads_of_absent_versions_identities_and_parts_are_empty` | absent version / language / kind / part → `None`; `asr-local` is a legal empty read; store counts unchanged `(1, 2, 1)` |
| `test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt` | the exact work order `BV0Z:p0, BV1A:p0, BV1A:p1, BV1A:p3, BV1A:p2` (never-attempted first by bvid then page, then oldest attempt first) with insertion order deliberately different; `gone` part absent; `count == 5`; `limit=1/2/5` take the head of that order |
| `test_pending_enumeration_carries_the_last_attempt_evidence_and_excludes_stored_parts` | the stored part excluded, the metadata-only part present with `attempted = 0` and all four last-attempt columns `NULL`, the probed part present with `no-subtitle` / `not_found` / timestamp / `credential_present = 1`; the exact 12-column work-item set incl. `cid` |
| `test_a_part_recorded_no_subtitle_leaves_the_pending_set_when_a_later_run_stores_it` | `no-subtitle` and `failed` both keep their part in the backlog with the never-attempted part ahead; a later run stores v1 and the part leaves; all three attempt rows survive with their run/outcome/code/transcript/timestamps |
| `test_list_selected_parts_selects_explicitly_or_returns_no_rows` | whole-video and single-page selection with the exact `v_video_parts` key set; a part that already holds a transcript is still selected (and does hold it); a `gone` video is selectable although the pending enumeration excludes it; unknown bvid / page → `[]` |
| `test_pending_enumeration_reuses_the_shipped_limit_validation` | identical exception type **and message** to `MetadataRepository.list_pending_parts` for `0, -1, True, "2", 1.5` |
| `test_read_arguments_follow_the_module_validation_discipline` (14 cases) | `TypeError`/`ValueError` per argument on every read path (id, kind, language, version, bvid, page_index, limit) |
| `test_read_paths_consume_the_views_instead_of_re_deriving_them` (D5) | dropping `v_pending_subtitles` / `v_video_parts` makes the reads raise naming the view |
| `test_work_id_is_computed_by_the_views_and_never_stored` | `v_pending_subtitles`, `v_video_parts` and both read methods yield the same computed `work_id`; no transcript-contract table has a `work_id` column |
| `test_segments_keep_the_callers_order_and_overlaps_verbatim` (M3) | a reversed, overlapping body stores ordinals `0,1,2` in the caller's order with the caller's intervals; the sorted body has a different digest; the identical repeat is `unchanged` and the read path returns the caller order |
| `test_run_id_is_validated_by_one_shared_path_across_the_class` (M2, 6 cases) | all four run_id-carrying methods raise the same type and message for `""`, `"   "`, `"r\n1"`, `"r\x001"`, `None`, `7`; a rejected identifier writes nothing and leaves the run `('running', None)` |
| `test_storage_paths_never_read_or_write_a_legacy_sidecar` (D2) | the intercept provably rejects a sidecar open; no Python-level open below the archive root during the whole storage path (all five reads, both writes, run start/finish); the archive root contains exactly `archive.db` + the planted poison files; the poison bytes are unchanged |
| `test_pending_subtitles_view_is_scoped_to_subtitle_attempts` (schema) | an `audio`-kind attempt does not mark a part attempted and is never reported as its subtitle evidence; the same part's `subtitle` attempt does |
| `EXPECTED_CHECK_ENUMERATIONS["transcript_segments"]` (schema) | the segment table's DDL carries `ordinal >= 0`, `start_ms >= 0`, `end_ms > start_ms` |

### Non-vacuity evidence (deliberate mutations)

Each mutation was applied to the committed source, the affected tests were run, then the file
was restored from a `/tmp` copy and verified with `sha256sum -c` (final hashes match the
pre-mutation state: `database.py deb5a3db…`, `models.py 177dcce7…`, `__init__.py ccecbc3b…`,
`test_storage_schema.py 7c20b734…`).

| # | Mutation | Observed result |
|---|---|---|
| A | drop the locked `ORDER BY` (leave `bvid, page_index`) | **2 failed** — `…orders_never_attempted_before_the_oldest_attempt`, `…no_subtitle_leaves_the_pending_set…` |
| B1 | read path `ORDER BY ordinal` → `ORDER BY start_ms` | **1 failed** — M3 body pin (read half) |
| B2 | write path inserts `sorted(canonical, key=start_ms)` | **1 failed** — M3 body pin (raw segment/ordinal rows) |
| C | `finish_acquisition_run` back to the hand-rolled `run_id` check | **4 failed** — M2 message/type cases (empty and control-character variants) |
| D | `read_transcript` opens `meta-cursor.json` next to the database | **1 failed** — the sidecar intercept |
| F1 | a storage path creates `stray.json` via `os.open` (bypasses the guard) | **1 failed** — the archive-root file-set assertion |
| F2 | a storage path appends to the planted `run-ledger.jsonl` via `os.open` | **1 failed** — the poison-bytes assertion |
| G | `count_pending_subtitle_parts` re-derived from `video_parts` | **1 failed** — the D5 view-consumption pin |

The inherited WIP's own tests were not smoke-tested by mutation in bulk; the eight above cover
the four brief items that a green suite can pass vacuously (locked ordering, verbatim body,
shared validation path, sidecar absence) plus the view-consumption claim added by D5.

## Files changed (commit `1019000`)

- `bilibili-asr-archive/src/bili_asr/storage/database.py` (+180/−4)
- `bilibili-asr-archive/src/bili_asr/storage/models.py` (+44)
- `bilibili-asr-archive/src/bili_asr/storage/__init__.py` (+2)
- `bilibili-asr-archive/tests/test_storage_schema.py` (+69)
- `bilibili-asr-archive/tests/test_transcript_repository.py` (+794)
- `git diff --check` clean; `git status --untracked-files=all` clean after the commit; commit
  on `feature/20260911-transcript-storage` only, no push, no other branch touched, no harness
  artifact written other than this report.

## Decisions disclosed

1. **`TranscriptRecord` is a new DTO.** Spec §4's signature says
   `read_transcript(...) -> TranscriptRecord | None`, but the §4 DTO list enumerates only
   `TranscriptSegmentRecord`, `TranscriptWriteResult` and `AcquisitionRunRecord`. The type was
   therefore added to `storage/models.py` as a validated frozen dataclass (non-empty segment
   tuple, vocabulary-checked `source_kind`, hash shape) and exported. Alternative rejected:
   returning a raw `sqlite3.Row` — that would contradict the locked signature and push row
   unpacking into every caller.
2. **The M2 message for a blank `run_id` changed for `finish_acquisition_run`.** It was
   `"run_id must be a non-empty string"` (hand-rolled); it is now `"run_id must not be empty"`,
   the `_text` message the other two methods already produced — which is what "keep the
   messages byte-identical" means for this class. The committed Task-2 test only asserted the
   exception *type* for that case, so nothing regressed; the new M2 test asserts the message
   for all four methods.
3. **`list_selected_parts` joins `video_parts` to reach `bvid`.** `v_video_parts` carries the
   computed `work_id` but not `bvid`, so the selector joins the part row and still selects
   `vvp.*`; the returned column set is exactly the view's (asserted by key-set equality).
   `page_index` is the 0-based index `parse_work_id` returns, matching `work_id`'s `:pN`.
4. **Read-path validation follows the write discipline.** Reads reject a malformed argument
   (`video_part_id = 0`, unknown `source_kind`, blank language, `version = 0`, blank bvid,
   negative/fractional `limit`) instead of quietly returning `None`/`[]`; only a *well-formed*
   identity the archive does not hold answers empty. The `asr-local` reservation is a legal
   read for the same reason it is a legal column value.

## Environment note for QC/QA

The control interpreter's editable install (`.venv/.../__editable__.bili_asr-0.1.0.pth`)
points at the **control** checkout's `src`, so a bare `python -c "import bili_asr"` resolves to
`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/src` (which has no
`TranscriptRepository` at all). The test runs above are unaffected: `tests/conftest.py` inserts
the *worktree's* `src` at `sys.path[0]`, which is why `pytest` from the worktree package root
exercises the committed code. Verification for this task was done exclusively through that
pytest invocation; a check that bypasses the conftest would read the wrong tree.

## STOP conditions

None triggered. No constraint was weakened, no `ALTER TABLE`/backfill/migration code exists, no
raw payload is stored, the process-record pair records only bounded evidence, and the metadata
suites stay green (1201 passed overall, 0 failures).

## Handoffs

- The CLI plan (`20260911-subtitle-cli-cutover`) consumes `list_selected_parts` /
  `list_pending_subtitle_parts` / `count_pending_subtitle_parts` / `read_transcript` exactly as
  spec §4/§6 lock them; the D5 pin is the guard that keeps a future CLI-side re-derivation from
  quietly replacing the view.
- `docs/metadata-storage.md` ("Fresh-start behavior", "Reserved media boundary") is **not**
  updated here — the drift check assigns that to the CLI plan.
- Reviewers: the two resolved-in-flight items worth re-reading are the sidecar test (D2 — the
  guard's self-check is what makes the empty record evidence) and the M2 message change
  (disclosed above as decision 2).
