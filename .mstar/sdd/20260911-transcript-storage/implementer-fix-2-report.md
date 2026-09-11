# Implementer Fix Report 2 — plan-QC seat 3 (QC3-001 Warning, QC3-002 Suggestion)

- Plan: `20260911-transcript-storage` · Iteration: `iter-2026-09-subtitle-transcript-sqlite`
- Wave: plan QC fix round 2, dispatched from `review/qc-consolidated.md` ("Request Changes → one test-only fix wave, then targeted re-review")
- Role: `fullstack-dev` (leaf executor; no subagents dispatched)
- Working branch: `feature/20260911-transcript-storage` · Worktree `/root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage`
- Commit: **`4dcbf5d`** `fix(storage): guard the repository boundary and pin the page_index key` (parent `5f93e05`)
- Control interpreter (worktree has no `.venv`): `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`

## Status

**DONE** — both dispatched findings are closed with opposite-direction (mutation) evidence. No query
change, no behaviour change beyond QC3-002's constructor guard, and no pre-existing assertion was
weakened (two were widened, disclosed in §6).

## 1. Per-finding disposition

| ID | Sev. | Disposition | Files (after the fix) | Anchor |
|----|------|-------------|-----------------------|--------|
| QC3-001 | Warning (blocking) | **Closed — test/fixture only**; `page_index ASC` is now falsifiable in both guarded queries; the two `ORDER BY` key lists are byte-unchanged | `bilibili-asr-archive/tests/test_transcript_repository.py:1388-1450` (fixture `:1401-1418`, expectations `:1424-1448`) | product anchors `src/bili_asr/storage/database.py:1114` (LIMIT spelling) and `:1121` (unbounded spelling) — untouched |
| QC3-002 | Suggestion | **Closed — fail-fast guard + new test**; a direct caller can no longer bypass the schema contract and meet raw SQLite text | `bilibili-asr-archive/src/bili_asr/storage/database.py:744-755` (docstring `:744-749`, `require_subtitle_schema(connection)` at `:754`), `bilibili-asr-archive/tests/test_transcript_repository.py:1144-1167` (import `:32`) | guard helper unchanged at `database.py:169-183`; `MetadataRepository.__init__` (`:276-278`) deliberately untouched |

Not acted on (already dispositioned by the consolidated gate): QC3-003 / QC3-005 (CLI-plan readiness),
QC3-004 (performance record), QC1-002 / QC2-S2 (deferred hardening nits), QC1-001 / QC2-S1
(audio/ASR-iteration backlog rotation). No file under `.mstar/plans`, `.mstar/specs`,
`.mstar/status.json`, the workflow snapshot, or the iteration package was written by this wave.

## 2. QC3-001 — what the fixture carries now, and both required mutation states

**The gap (seat's finding, re-derived).** The old fixture inserted every part of a `bvid` in ascending
page order, so within one `bvid` SQLite's rowid order *was* page order; the `drop page_index ASC`
mutation therefore passed while `plans/20260911-transcript-storage.md` claimed the order was
"pinned by tests".

**The fix (test-only, `tests/test_transcript_repository.py:1401-1418`).** `BV1A` now stores **page 5
before its page 4 sibling** through the parts write path (`MetadataRepository.upsert_part`, inside one
`metadata.transaction()`), so `video_part_id` rowid order and `page_index` order disagree inside one
`bvid`. Expected list extended 6 → 8 entries (`:1424-1433`), `count_pending_subtitle_parts() == len(work_ids) == 8`
(`:1437`), and the bound assertion moved to `limit=8` (`:1446-1448`). The mutation must now fail on the
first flipped pair — and does, in every spelling.

### State A — key dropped (`1 failed`)

| Mutation (planted in the worktree, restored with `git checkout --`) | Result | Failing assertion |
|---|---|---|
| `page_index ASC` removed from the **unbounded** query only (`database.py:1121`) | `1 failed, 80 deselected in 0.16s` | `tests/test_transcript_repository.py:1424: AssertionError` — `At index 4 diff: 'BV1A:p5' != 'BV1A:p4'` (log `/tmp/mstar-qc-fix2/mutation-unlimited.txt`) |
| `page_index ASC` removed from the **LIMIT** query only (`database.py:1114`) | `1 failed, 80 deselected in 0.17s` | `tests/test_transcript_repository.py:1446: AssertionError` — same `BV1A:p5` / `BV1A:p4` flip (log `/tmp/mstar-qc-fix2/mutation-limit-clean.txt`) |
| removed from **both** queries (the seat's original probe) | `1 failed, 80 deselected in 0.16s` | `tests/test_transcript_repository.py:1424: AssertionError` — same flip (log `/tmp/mstar-qc-fix2/mutation-both-clean.txt`) |

Failing test name in all three states: `test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt`.

### State B — key restored (`green`)

```
$ cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage/bilibili-asr-archive
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_transcript_repository.py \
    -q -k "test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt"
1 passed, 80 deselected in 0.09s          # and after every restore: git status --porcelain == ''

$ # both named tests, restored state
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_transcript_repository.py \
    -q -k "test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt or test_constructor_refuses_a_legacy_database_with_the_bounded_error"
2 passed, 79 deselected in 0.14s
```

The two guarded key lists are unchanged: the mutation was the only edit to `database.py` in these runs
and it was reverted between runs (`porcelain: ''` printed after each).

## 3. QC3-002 — mutation state for the new guard

`TranscriptRepository.__init__` now runs `_validate_connection(connection)` **then**
`require_subtitle_schema(connection)` (order matters: the connection-state `TypeError` / `ValueError`
assertions in `test_constructor_requires_the_open_database_connection_state:1128-1141` keep passing).

| State | Evidence |
|---|---|
| Guard removed (mutation) | `test_constructor_refuses_a_legacy_database_with_the_bounded_error` → `1 failed, 80 deselected in 0.13s`, `tests/test_transcript_repository.py:1157: Failed: DID NOT RAISE SchemaContractError` (log `/tmp/mstar-qc-fix2/mutation-no-guard.txt`). A direct caller on a pre-iteration database then hit the pre-fix failure mode live: `pre-fix behaviour -> OperationalError: no such table: v_pending_subtitles` (same class as the seat's `no such table: acquisition_runs` / `no such column: language`) |
| Guard restored | the same test passes, and the bounded message is asserted verbatim: `"predates the transcript schema"` and `"delete archive.db and re-run fetch-meta"` (`:1160-1161`) |

The new test builds the legacy database with the canonical `_write_pre_iteration_database` helper from
`tests/test_storage_schema.py` (the same fixture `test_bootstrap_leaves_a_pre_iteration_database_untouched`
uses), so "pre-iteration database" has exactly one definition in the suite. It also asserts
`MetadataRepository(connection)` still constructs on that database (`:1165`) — the guard belongs to the
transcript boundary, not to the archive.

**No existing caller breaks:** `grep -rn "TranscriptRepository(" --include=*.py src tests` finds zero
constructions outside `tests/test_transcript_repository.py` (the CLI does not exist yet), and every
construction there sits on an `open_database` database. The one test that deliberately removes schema
objects (`test_read_paths_consume_the_views_instead_of_re_deriving_them`, `:1673-1701`) drops the views
*after* constructing the repository and still expects the raw `OperationalError` from the read call —
unchanged and passing.

## 4. Focused and full outputs (control interpreter, final committed state)

```
# focused (fix wave 2 gate command)
$ cd .worktrees/20260911-transcript-storage/bilibili-asr-archive
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
    tests/test_transcript_repository.py tests/test_storage_schema.py -q
118 passed in 4.24s           # baseline at 5f93e05: 117 passed (this wave adds exactly 1 test)

# full offline suite
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
1202 passed, 3 skipped in 47.99s     # baseline 1201 passed, 3 skipped → +1 new test, same 3 skips
```

TDD triple: test files `tests/test_transcript_repository.py` (+ `tests/test_storage_schema.py` for the
pre-iteration fixture), commands above, outputs above and in §2/§3.

## 5. Files changed

| File | Change |
|------|--------|
| `bilibili-asr-archive/tests/test_transcript_repository.py` | +1 test (`:1144-1167`), +1 import (`:32`), fixture + expectations for the pending-order test (`:1401-1418`, `:1424-1448`), `SchemaContractError` added to the existing `bili_asr.storage` import block (`:19`) |
| `bilibili-asr-archive/src/bili_asr/storage/database.py` | +1 statement `require_subtitle_schema(connection)` in `TranscriptRepository.__init__` (`:754`) and the matching class-docstring sentence (`:744-749`) — one diff hunk, nothing else in the module |

Net: `2 files changed, 57 insertions(+), 5 deletions(-)`; `git diff --check` clean; commit `4dcbf5d`
on `feature/20260911-transcript-storage`, no push, integration branch and `main` untouched.

## 6. Self-review notes (disclosures)

1. **Mechanism differs from the seat's suggested route (disclosed).** QC3-001's fix was suggested as a
   direct `INSERT INTO video_parts(...)`. The parts are instead stored through `MetadataRepository.upsert_part`
   (`:1409-1418`) because it produces the identical property (auto-assigned `video_part_id` rowid order
   ≠ page order) without hand-copying `video_parts` literal column values. The seat's requirement —
   "rowid order ≠ page order inside one `bvid`" — is what the mutation runs prove, not the SQL spelling.
2. **Cross-module test import (disclosed).** `tests/test_transcript_repository.py:32` imports the private
   helper `_write_pre_iteration_database` from `tests/test_storage_schema.py`. Precedent exists in the same
   file (`from test_metadata_e2e import LEGACY_SIDECAR_PATHS`, `:31`); the alternative was duplicating the
   legacy DDL, i.e. a second definition of "pre-iteration database" that could drift.
3. **Two assertions widened, none relaxed.** `count_pending_subtitle_parts() == len(work_ids) == 6 → 8` and
   `limit=6 → limit=8`; the expected list gained two entries and the inline comment now names the mutation
   the pair catches. Every other assertion, including the `bvid`-before-`page_index` interleave claim, is
   untouched.
4. **Mutation mis-plant discarded (honesty note).** The first `LIMIT`-query mutation dropped the
   separator space (`... bvid ASC" "LIMIT ?"` → `ASCLIMIT`) and "failed" for a syntax error, not for the
   ordering. That evidence was rejected and the mutation re-planted faithfully (keeping the space); only
   `mutation-limit-clean.txt` is cited in §2. The two other spellings never had this defect.
5. **QC3-002 is a product-code change, as instructed** ("no query/behaviour change beyond item 2"). The
   added guard makes the documented CLI guard redundant rather than conflicting (the CLI guards *before*
   construction), and the read/write paths, schema, and contracts are untouched.
6. **Plan/status files not touched.** `plans/20260911-transcript-storage.md` already carries the QC3-001
   closure and the QC3-004 record in its Durable Roadmap (written by the PM); the DoD claim "the pending
   view's order … pinned by tests" becomes true for all four keys with this commit, and the evidence is
   per-query as the seat asked (both `ORDER BY` spellings exercised).
7. **Deferred items stay deferred.** QC3-003 / QC3-005 and the CLI-plan readiness items were not touched
   here; nothing in this wave changes the CLI plan's obligations.

## 7. Mutation hygiene and final state

- All mutation edits were made in the feature worktree only and reverted with
  `git -C <worktree> checkout -- bilibili-asr-archive/src/bili_asr/storage/database.py`; after each
  restore `git status --porcelain` printed empty.
- Scratch and logs live **outside both checkouts**, under absolute paths: `/tmp/mstar-qc-fix2/`
  (`mutation-*.txt`, plus the throwaway `legacy-root/` database used for the QC3-002 reproduction).
  Nothing was planted in `/root/workspace/bilibili-asr-archive` or in the worktree; the only worktree
  artifacts after the runs are the gitignored, runner-generated `.pytest_cache/`, `.test-tmp/`, and
  `__pycache__/` (`.test-tmp` is empty and gitignored at `.gitignore:25`).
- Final: HEAD `4dcbf5d` on `feature/20260911-transcript-storage`, worktree clean, `git diff --check`
  clean, no push, control checkout not written by this wave.

## Evidence index

| Claim | Artifact |
|---|---|
| Focused baseline (pre-fix) `117 passed` | §4 (run at `5f93e05`, kept in this report only) |
| Focused post-fix `118 passed in 4.24s` | §4 |
| Full suite `1202 passed, 3 skipped in 47.99s` | §4 (job `bash-35`, exit 0) |
| QC3-001 states A/B (unbounded / LIMIT / both) | §2, logs `/tmp/mstar-qc-fix2/mutation-{unlimited,limit-clean,both-clean}.txt` |
| QC3-002 states A/B | §3, log `/tmp/mstar-qc-fix2/mutation-no-guard.txt` |
| Restored-state greens after each mutation | §2/§3 (`git status --porcelain` empty; `1 passed` / `2 passed`) |
| Commit | `4dcbf5d` |
