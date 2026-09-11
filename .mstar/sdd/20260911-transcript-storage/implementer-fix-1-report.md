# Implementer Fix Report 1 — Task-3 L2 review Minor-1 (test strength)

- Plan: `20260911-transcript-storage` (task 3, fix round 1)
- Execute as: `@fullstack-dev` — leaf executor, `Delegation: forbidden` (no subagent dispatched, no harness file written but this report)
- Worktree: `.worktrees/20260911-transcript-storage` · Branch: `feature/20260911-transcript-storage`
- Range: base `1019000` → head **`5f93e05`** (one commit; no push; integration branch and `main` untouched)
- Finding fixed: Task-3 review `Minor-1` — the pending-enumeration ordering test could not discriminate the locked `ORDER BY`'s last two keys
- Anchor read first: `review/task-3-review.md` · spec §2.5 row "the repository — not the view — imposes order" / §6 · `task-3-brief.md`

## Status

**DONE**

Test/fixture-only change. No production behaviour touched; the locked `ORDER BY` is byte-identical
to the reviewed commit (hash-verified at every mutation boundary, see §5).

## 1. What changed

One file: `bilibili-asr-archive/tests/test_transcript_repository.py`, test
`test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt` (`+12 / −8`).

| Line (after) | Change |
|---|---|
| `:1371` | `_video_with_parts(connection, "BV0Z", (4001,))` → `(4001, 4002)` — the second captionless video now holds **page 0 and page 1**, overlapping BV1A's page indexes |
| `:1365-1369` | fixture comment now states the property the fixture has to carry (the two orderings interleave differently), not just "insertion order differs" |
| `:1378-1385` | expected list 5 → 6 entries; the four never-attempted parts are now `BV0Z:p0, BV0Z:p1, BV1A:p0, BV1A:p1`, then `BV1A:p3` (oldest attempt) and `BV1A:p2`; the inline comment names the swapped interleave |
| `:1389` | `count_pending_subtitle_parts() == len(work_ids) == 5` → `== 6` |
| `:1395-1397` | `limit=2` expectation `["BV0Z:p0", "BV1A:p0"]` → `["BV0Z:p0", "BV0Z:p1"]` (strengthened, not relaxed — see §3) |
| `:1398-1400` | `limit=5` → `limit=6`, keeping the original intent: an explicit bound must reproduce the unlocked list, at the fixture's new size |

Nothing else moved: the `limit=1`, `"BV1GONE:p0" not in work_ids` and `work_id`-order assertions are untouched.

## 2. Why the old fixture could not discriminate, and what makes it falsifiable now

All four never-attempted parts tie on the lock's first two keys (`attempted = 0`, `last_attempt_at`
is `NULL` for every one of them), so **their order is decided entirely by the last two keys**. The two
spellings disagree exactly when some pair has `bvid_i < bvid_j` **and** `page_i > page_j` — the old
fixture had no such pair:

- old never-attempted set `{(BV0Z,0), (BV1A,0), (BV1A,1)}` — every pair is same-page (broken by `bvid`
  in both spellings: `BV0Z < BV1A`) or same-`bvid` (broken by page in both) → identical lists;
- new set adds `(BV0Z,1)`, which pairs with `(BV1A,0)`: `bvid`-first puts `BV0Z:p1` first,
  `page_index`-first puts `BV1A:p0` first.

Independent probe of the fixture premise (shipped read-only code, throwaway archive root under
`/tmp`, nothing written into the repo) — locked vs swapped keys, straight against
`v_pending_subtitles`:

```text
locked  : ['BV0Z:p0', 'BV0Z:p1', 'BV1A:p0', 'BV1A:p1', 'BV1A:p3', 'BV1A:p2']
swapped : ['BV0Z:p0', 'BV1A:p0', 'BV0Z:p1', 'BV1A:p1', 'BV1A:p3', 'BV1A:p2']
diverge : True | first difference at index 1
count   : 6
limit=2 : ['BV0Z:p0', 'BV0Z:p1']
```

The two attempted parts differ on `last_attempt_at` (500 vs 300), so the third key still orders them —
that half of the lock was already pinned by the review and stays as it is.

## 3. Mutation states (both required states, plus the per-query split)

Each mutation swapped `bvid ASC, page_index ASC` → `page_index ASC, bvid ASC` in
`src/bili_asr/storage/database.py` (`:1110` = the `LIMIT` query, `:1117` = the unbounded query),
run from the worktree package dir with the control interpreter, then restored from a byte backup.

**S1 — only the unbounded query swapped (`:1117`):**

```text
1 failed, 79 passed in 3.04s
FAILED tests/test_transcript_repository.py::test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt
tests/test_transcript_repository.py:1378: AssertionError
E  AssertionError: assert ['BV0Z:p0', '...3', 'BV1A:p2'] == ['BV0Z:p0', '...3', 'BV1A:p2']
E    At index 1 diff: 'BV1A:p0' != 'BV0Z:p1'
```

**S2 — only the `LIMIT` query swapped (`:1110`):** the failing assertion is the bounded-run one, so the
bounded query is pinned independently of the unbounded one.

```text
1 failed in 0.15s  (single test, --tb=long)
FAILED tests/test_transcript_repository.py::test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt
>           assert [
>               row["work_id"] for row in repository.list_pending_subtitle_parts(limit=2)
>           ] == ["BV0Z:p0", "BV0Z:p1"]
E           AssertionError: assert ['BV0Z:p0', 'BV1A:p0'] == ['BV0Z:p0', 'BV0Z:p1']
E             At index 1 diff: 'BV1A:p0' != 'BV0Z:p1'
```

**S3 — both queries swapped (a realistic swap regression):**

```text
1 failed, 79 passed in 2.88s
FAILED tests/test_transcript_repository.py::test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt
E             At index 1 diff: 'BV1A:p0' != 'BV0Z:p1'
```

**Restored state:**

```text
$ cp /tmp/database.py.orig …/src/bili_asr/storage/database.py
$ git hash-object …/src/bili_asr/storage/database.py
499164ca322cb94d541a77f3f8f075f3745f3f01     # == git rev-parse HEAD:bilibili-asr-archive/src/bili_asr/storage/database.py
$ git status --porcelain
 M bilibili-asr-archive/tests/test_transcript_repository.py      # nothing else, ever
80 passed in 3.51s
```

So: **swapped → the ordering test fails; restored → green**, in all three granularities.

## 4. Focused and full outputs

Focused — `cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage/bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_transcript_repository.py -q`

```text
before the fix (base 1019000):  80 passed in 3.82s
after the fix (committed):      80 passed in 3.51s
```

Full offline suite (worktree package dir, `-q`, `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider`):

```text
at 5f93e05:  1201 passed, 3 skipped in 47.63s
```

Matches the stated baseline exactly (1201 passed, 3 skipped): the fix strengthens an existing test, it
does not add or remove one, so the expected delta is zero and it is zero.

`git diff --check` → clean (exit 0, no output). The changed file stays inside the file's
93-character line discipline (no line > 93 in it).

## 5. Files changed

- `bilibili-asr-archive/tests/test_transcript_repository.py` (+12 / −8) — committed as
  `5f93e05 test(storage): make the pending order's last two keys falsifiable` on
  `feature/20260911-transcript-storage`.
- **No product file changed.** `src/bili_asr/storage/database.py` blob =
  `499164ca322cb94d541a77f3f8f075f3745f3f01`, identical to `HEAD:` and to the pre-fix tree; the locked
  `ORDER BY attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC` is unchanged in both queries.
- No harness file written but this report; no push; no commit outside the working branch.

## 6. Self-review notes

1. **No assertion relaxed.** Every pre-existing assertion survives with the same or stricter content.
   Two expectations changed by more than the fixture's size, both disclosed: `limit=2` is now
   `["BV0Z:p0", "BV0Z:p1"]` (strictly stronger — it pins the key precedence on the bounded path), and
   `limit=5 == work_ids` became `limit=6 == work_ids` (same intent: an explicit bound must reproduce the
   unlocked list; 6 is now the fixture's full size).
2. **Blast radius checked.** `BV0Z` appears only inside this one test (grep over `tests/`); the other
   four pending-enumeration tests use a single video per store, where the last two keys are not
   reachable as a tie-break, so their expectations are unaffected — confirmed by the untouched 80-test
   focused run and the 1201-test full run.
3. **Discrimination scope, stated honestly.** The never-attempted block is what exercises the last two
   keys; the attempted pair is ordered by `last_attempt_at`. That is sufficient because a swap
   regression is a static edit to the query — the test's failure does not depend on which group reveals
   it — and both queries (`LIMIT` and unbounded) are covered by their own assertion (S1/S2).
4. **Environment.** The worktree has no `.venv`; every run used the control interpreter
   `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` with the worktree
   package dir as cwd, so `tests/conftest.py` puts the worktree `src` first on `sys.path`. `git status
   --porcelain` was empty before and after each run except for the one intended file.
5. **Mutation hygiene — one incident, fully disclosed.** My first mutation helper used a *relative*
   path; two later invocations were launched with the session workspace as cwd, so they read and wrote
   the **control** checkout's `bilibili-asr-archive/src/bili_asr/storage/database.py` — where the
   anchors do not exist, so 0 substitutions were made and the same bytes were written back. Verified
   afterwards: the control file's blob hash equals its own `HEAD` hash
   (`2cd1bf0fa3af8b3dd387a514f200c44b99666158`), i.e. **no bytes changed in the control checkout**. Its
   other three modified paths (`.mstar/plans/20260911-transcript-storage.md`,
   `.mstar/iterations/.../specs/transcript-storage.md`,
   `.mstar/workflows/.../snapshot.json`) are pre-existing PM edits and were not touched by this seat.
   All three mutation runs reported above were re-run with an absolute path (substitution count `1`
   each, printed by the helper), so the evidence in §3 comes only from real knock-outs of the worktree
   query.
6. **Not done, deliberately:** no reviewer-suggested extra (e.g. an `os.open` sidecar intercept,
   Minor-3) was piggybacked — Minor-1 is the assigned finding and the change stays surgical. The
   review's Minor-2 (report/ledger prose "four read methods") is a PM/ledger wording item, not mine to
   edit.

## Evidence index

- Test: `bilibili-asr-archive/tests/test_transcript_repository.py:1360-1402`
- Command: `cd .worktrees/20260911-transcript-storage/bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_transcript_repository.py -q`
- Output: `80 passed`; full suite `1201 passed, 3 skipped`
- Commit: `5f93e05` on `feature/20260911-transcript-storage` (base `1019000`)
