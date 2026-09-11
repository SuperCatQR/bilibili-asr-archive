# SDD Progress — 20260911-transcript-storage

Task 1: complete + review **Approved** (`6ee7c6a..d4cae24`)

- Implementer commit: `d4cae24 feat(storage): lock the transcript schema contract and split the bootstrap` (DONE)
- Deliverables: `schema-transcripts.sql` (new resource: locked `transcripts` with `language` +
  `content_sha256` + widened unique key + the partial caption-only content index; verbatim-moved
  `transcript_segments`; `acquisition_runs` + `acquisition_attempts` with the full CHECK matrix and
  `PK(run_id, video_part_id)`; `ix_acquisition_attempts_part_time`; `v_pending_subtitles`),
  `schema.sql` (transcript block removed, pointer left), `pyproject.toml` package-data now ships both
  scripts, `database.py` conditional bootstrap + `require_subtitle_schema` / `SchemaContractError`,
  `storage/models.py` + package root enums/records.
- Runtime evidence: focused `36 passed`; full offline suite `1120 passed, 3 skipped` (baseline 1096/3,
  +24 tests); red evidence: dropping the partial index's `WHERE` → 2 failed; making the transcript script
  unconditional → `sqlite3.OperationalError: no such column: language`; weakening the `no-subtitle` CHECK
  arm → 5 failed; `git diff --check` clean.
- Task reviewer: `review/task-1-review.md` — **Approved** (0 Critical / 0 Important / 2 Minor). It
  independently reproduced the focused `36 passed`, the DDL fidelity (6/6 spec statements verbatim), and
  proved the `transcript_segments` move three ways (new script ≡ removed block ≡ the test's legacy DDL
  fixture); named a failing-if-reverted test for every structural guard; regression lens clean (only
  docstring lines removed from `database.py`; all 17 removed test lines are strict supersets).
- PM dispositions carried into later tasks:
  - **M1** (spec §5 "stored trimmed" is currently satisfied by the gateway's trimming; `_caption_text`
    validates without normalizing) → **Task 2 decides**: either strip at the repository boundary or make
    §5 name the gateway as the trimming site. Not a Task-1 rework.
  - **M2** (`SchemaContractError`'s message lacks the spec §3.3 `<command>:` prefix and `{archive_root}`
    path) → correct only if the CLI composes the printed line; **CLI plan verification item**.
  - **⚠️3** `docs/metadata-storage.md:13` bootstrap wording is stale; it is in the CLI plan's Files list and
    must land before that plan's Done.
  - **⚠️4** the locked pending-enumeration order is not asserted yet (correctly deferred) → **Task 3's
    review must pin it**.
  - **⚠️7** `pyproject.toml` and `storage/__init__.py` were touched beyond the brief's file list; both
    minimal and additive (the new resource must ship in the wheel).

## Next

Task 2 (TranscriptRepository writes with content-based idempotency + the S11 millisecond bound).

Task 2: complete + review **Approved** (`d4cae24..f3cd735`)

- Implementer commit: `f3cd735 feat(storage): write transcripts idempotently with acquisition process records`
- Evidence: focused `48 passed` (with the metadata + schema modules `105 passed`); full offline suite
  `1168 passed, 3 skipped` (baseline 1120/3, +48 tests); 7 targeted mutations each failing then reverted;
  `git diff --check` clean
- Delivered: `TranscriptRepository` (`start_acquisition_run` / `finish_acquisition_run` with own commits,
  terminal no-regression and derived `complete|partial|failed`; `record_acquired_transcript` as one
  transaction with canonical-JSON `content_sha256` identity, `unchanged` vs appended version, immutability;
  `record_subtitle_attempt` append-only with the CHECK matrix in code too) and the carried fixes.
- **M1 decided**: trimming happens **at the repository boundary** (stored text = hashed text; interior
  control characters verbatim); the PM recorded this plus the ceiling in spec §5 as dated notes.
- **S11 done**: `MAX_TIMELINE_MS = 10**12` enforced at the SQL boundary (bounded `ValueError`, nothing
  written); the DTO stays deliberately unbounded with a test asserting so (moving the bound breaks a test);
  red proof: removing the guard yields the claimed `OverflowError`.
- Task reviewer: `review/task-2-review.md` — **Approved** (0 Critical / 0 Important / 3 Minor). It
  independently re-derived the diff census, proved the test run exercised the feature source (the shared
  venv's editable install points at the control worktree; `conftest.py:12` prepends the feature `src`),
  confirmed no UPDATE/DELETE/INSERT-OR-REPLACE against the transcript tables and that the rollback proof is
  real (the attempt INSERT is last, and the same content lands as v2 on the next run).
- PM dispositions: **M3** (spec §5's order/overlap rule unpinned) and **M2** (`run_id` validated two ways)
  are folded into Task 3 as a recorded authorization block; the report's line-count mismatch is cosmetic;
  the `changes() != 1` race path mirrors the shipped `finish_run` and is accepted (single-connection).

## Next

Task 3 (reads, pending enumeration, contract evidence) — incl. the folded M2/M3.

Task 3: implementer run **cancelled mid-task** (harness interruption, 2026-09-11) → audited + relaunched

- The cancelled run left uncommitted WIP in the feature worktree (5 files, +1041/−4): `storage/database.py`
  (+184), `storage/models.py` (+44), `storage/__init__.py` (+2), `tests/test_storage_schema.py` (+69),
  `tests/test_transcript_repository.py` (+746) — no commit, no report.
- PM audit before relaunch: the four read/enumeration methods exist (`read_transcript:1011`,
  `list_transcript_versions:1065`, `list_pending_subtitle_parts:1087`,
  `count_pending_subtitle_parts:1121`); the folded **M3** pin exists
  (`test_segments_keep_the_callers_order_and_overlaps_verbatim:1714`, reversed + overlapping body asserting
  the digest is order-sensitive); the folded **M2** is applied inside the new class (`run_id` normalized via
  `_text` at 804/871/983; the remaining hand-rolled check at 689 belongs to the pre-existing metadata
  `run_stats`, out of this task's scope); focused run on the partial tree: `116 passed` (transcript
  repository + schema tests).
- Missing when cancelled: the full offline suite run, the commit, and the implementer report. A fresh
  implementer was dispatched to audit the partial tree and finish (keep the core, close gaps, run the full
  suite, commit, report) — the same disposition used for the earlier interrupted implementer.

Task 3: resumed after two harness-interrupted runs → complete (`f3cd735..1019000`, review in flight)

- Resume implementer commit: `1019000 feat(storage): read transcripts and enumerate the captionless backlog`
  (focused `117 passed`; full offline suite `1201 passed, 3 skipped`, baseline 1168/3 → +33; `git diff --check`
  clean; 8 mutations each reverted and hash-verified)
- **The audit paid off** — the interrupted run's WIP carried five defects the resume found and fixed:
  - **D1** a coincidence assertion (`stored.transcript_id == rows[0]["video_part_id"]`, true by accident) →
    replaced with a real claim about the explicitly selected part;
  - **D2** the sidecar guard was **unarmed, making its assertions vacuous** (SQLite opens the DB in C, not
    through Python, so the intercepted-open list was always empty): the test now proves the intercept
    rejects a deliberate sidecar open and then requires an empty record for the whole storage path;
  - **D3** the M2 test skipped `start_acquisition_run` → all four run_id-carrying methods now parametrized;
  - **D4** a 108-char line wrapped to the file's 93-char style;
  - **D5** coverage added proving the enumeration is never re-derived (dropping `v_pending_subtitles` /
    `v_video_parts` makes the three view-backed readers fail).
- Delivered: `read_transcript` (latest default / explicit version / absent), `list_transcript_versions`,
  `list_selected_parts`, `list_pending_subtitle_parts` / `count_pending_subtitle_parts` over
  `v_pending_subtitles` with the locked `ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC,
  page_index ASC`, and the contract evidence (multi-language/version reads, RESTRICT both ways, `work_id`
  view-only, sidecar-free storage paths, Task-1 guards extended).
- Disclosures for the reviewer: `TranscriptRecord` is a DTO the spec's §4 signature requires but its DTO
  list omits (added + exported) — a spec gap the PM records; M2 made `finish_acquisition_run`'s blank-`run_id`
  message the class's single `_text` message (the committed Task-2 test asserted only the exception type).

Task 3: review **Approved** — 0 Critical / 0 Important / 3 Minor

- Reviewer independently reproduced the focused suite (`117 passed`), re-derived the per-file diff census
  (exact match), and judged all five audit fixes **real**; it called **D2** (the unarmed sidecar guard made
  self-proving) the audit's best catch, and confirmed M3 is double-sided non-vacuous and M2 is a strict
  improvement that loses no contract.
- Dispositions: **(a)** `TranscriptRecord` is a genuine spec gap → PM recorded it in the spec's §4 with a
  dated note (no code change); **(b)** the M2 message change loses no contract (§4 pins no message text).
- **Minor-1 (actionable, test strength):** the ordering fixture cannot discriminate the locked order's last
  two keys (with one page on the second video, `bvid ASC, page_index ASC` and its swap yield the same
  asserted list) → dispatched as a fix wave (second video gets ≥2 pages; expected list + count updated).
- Minor-2 (report/ledger wording) fixed by the PM; Minor-3 (an `os.open` *read* could evade the three
  sidecar layers) is informational — the property holds by construction (no file I/O or sidecar literal in
  `src/bili_asr/storage/*.py` beyond the two package-resource schema reads).

Plan-2 fix wave 1 (`1019000..5f93e05`, revalidation in flight): Task-3 review Minor-1

- Commit `5f93e05 test(storage): make the pending order's last two keys falsifiable` (test-only, 1 file, +12/−8).
- Fixture: the second video now holds two pages with page indexes overlapping the first video's, so all four
  never-attempted parts tie on `attempted`/`last_attempt_at` and the locked `bvid ASC, page_index ASC` order
  diverges from the swapped spelling (they differ at index 1); the expected list and the `count` (5 → 6) and
  the bounded-run assertions were updated accordingly.
- Three mutation states reproduced: unbounded query swapped → 1 failed; `LIMIT` query swapped → 1 failed;
  both swapped → 1 failed; restored → focused `80 passed`, full suite `1201 passed, 3 skipped`; `git diff --check` clean.
- Disclosure handled: the implementer's first mutation helper used a relative path and rewrote the **control**
  checkout's `database.py` with identical bytes; PM verified independently that the control file is unchanged
  (`git status` clean, `git diff HEAD -- src/` empty, worktree blob ≠ control blob only because plan-2's
  changes live in the worktree). No action needed.

Plan-2 fix wave 1: revalidated **Approve** (0 open Minor) — Task-3 review `## Revalidation`

- The seat re-derived the expected order by hand from the committed fixture and confirmed the swapped
  spelling diverges at index 1, then proved it empirically with four in-process probes (a `sqlite3.Connection`
  subclass rewriting only the guarded SQL text — no file written, no checkout mutation): control neutral and
  green, unbounded-query swap fails at `:1378`, `LIMIT`-query swap fails at `:1395`, both swapped fails; the
  focused suite stays `80 passed`. Count/bounded assertions consistent (`6 = 4 + 2`).
- Regression lens: 1 test file in the diff, +12/−8, all 8 deleted lines re-added in updated form, **0 deleted
  assertion lines**, no cross-test coupling on the changed fixture.
- Mutation-hygiene incident cleared: the control `database.py` contains neither `TranscriptRepository` nor the
  `ORDER BY` anchor, so the mis-targeted helper substituted 0 occurrences and wrote back identical bytes; no
  stray `.orig/.bak/.rej` in either checkout; the seat independently reproduced the failures on the worktree
  code, so the evidence does not rest on that harness.
- Informational note (dropping only `page_index ASC` still passes; `bvid` is pinned) → PM judgement: **nit,
  not a residual**; recorded in the plan's durable roadmap for the next owner of pending enumeration.

Plan QC tri (N=3): seat1 **Approve** (0C/0W/4S) · seat2 **Approve** (0C/0W/2S) · seat3 **Request Changes** (0C/1W/4S)

Plan-QC fix wave 2 (`5f93e05..4dcbf5d`, revalidated **Approve**): QC3-001 (Warning) + QC3-002

- Both Approving seats independently re-derived the evidence channel (seat 1: the package diff is byte-identical
  to the live diff, 175 516 chars; seat 2: the atomicity/commit-matrix/immutability claims proved from a second
  connection and a grep over all of `src/`), re-derived the schema contract from the shipped artifacts, and
  concurred with the L2 severities. Seat 2 also flagged the stale plan file (PM reconciled: `Status: InReview`,
  19 task boxes `[x]`, PM lock set, acceptance left for QA).
- **QC3-001 (the only Warning — closed by fix wave 2)**: the pending order's last key `page_index ASC` was not
  falsifiable (the fixture inserted a `bvid`'s parts in ascending page order, so rowid order coincided with page
  order and the `drop page_index` mutation passed) while the plan's DoD claimed the order is pinned by tests.
  Fix: the fixture now stores `BV1A` page 5 **before** its page 4 sibling through the shipped parts write path
  (measured ids p0..p3=1..4, p5=8, p4=9), expectations widened 6→8 with `count == 8`; three mutation states each
  fail the named test (`At index 4 diff: 'BV1A:p5' != 'BV1A:p4'`) and restore green. Correction (QA finding QAF-1):
  `attempted ASC` itself remains unfalsifiable by any test, but it is provably order-equivalent (`attempted = 1 ⟺
  last_attempt_at IS NOT NULL`, measured `locked == mutated`) and documented in the code docstring — so the fix-wave
  report's "all four keys" phrasing is overstated; the QA gate re-proved the other keys. The seat re-proved the
  discrimination structurally (`EXPLAIN QUERY PLAN` → `SCAN vp`, i.e. rowid order, not an autoindex), and
  confirmed both guarded `ORDER BY` lists in `src/` are byte-unchanged.
- **QC3-002 closed here** as well: `TranscriptRepository.__init__` now calls `require_subtitle_schema` after
  `_validate_connection`, with a test asserting the bounded `SchemaContractError` on the **canonical**
  pre-iteration database (the seat byte-compared the fixture's legacy DDL against `git show 6ee7c6a:…/schema.sql`)
  and that `MetadataRepository` still constructs there.
- Recorded (durable roadmap, this plan): QC1-001 + QC2-S1 (backlog rotation vs future `asr-local` and mis-kinded
  attempts — the audio/ASR iteration decides), QC1-002 + QC2-S2 (hardening nits: guard omits
  `transcript_segments`; immutability's "no UPDATE/DELETE code path" mechanism is inspection-only), QC3-004
  (pending-view O(attempts) growth characteristic), QC2's projections handoff (revert-to-older-content: default
  read returns `MAX(version)` while the newest attempt references the older matched version).
- Recorded (CLI plan carry block): QC3-002 (guard obligation), QC3-003 (`docs/metadata-storage.md:51-56` becomes
  false on merge — that plan owns the doc), QC3-005 (the printed contract line must carry both the command prefix
  and the archive root, with an assertion).
- Suite progression for this plan: 1120 → 1168 → 1201 (fix wave 1) → **1202 passed / 3 skipped** (fix wave 2,
  implementer evidence; the QA gate reproduces it).
