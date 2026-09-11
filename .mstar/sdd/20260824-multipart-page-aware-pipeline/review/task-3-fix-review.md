# Task 3 L2 re-review

Reviewer: code-reviewer (Mode A, targeted)
Range: `817b5c89597ec2eda2a3ff729f440daa1a8c612a..fa20305bc85db07c7b2667b1d8bf6512705c35c8`
Diff: `review/task-3-fix.diff`
Prior: `review/task-3-review.md` (Needs fixes — archive frontmatter identity)

### Spec Compliance

- ✅ Spec compliant for the open Important finding.
  - `write_archive` now adds `work_id`, `page_index`, and `cid` when `work_id` is present and the row is not `unresolved` (`archive.py:84-87`).
  - Unresolved rows still omit those keys (`test_write_archive_unresolved_keeps_bare_bvid_stem`).
  - Two-page markdown asserts distinct `BV1multi:p0` / `p1`, `page_index` 0/1, `cid` 111/222.
- ⚠️ Cannot verify from diff:
  - Full suite `141 passed` — trust PM re-run on `fa20305`; not re-executed here.

### Strengths

- Guard is the same as stem policy: identity fields only on resolved `work_id` rows, so unresolved archives cannot invent page identity.
- Tests lock both the happy path and the unresolved negative path, not only filenames.

### Issues

#### Critical

None.

#### Important

None remaining from the prior review. Frontmatter contract is closed.

#### Minor

Prior Minors (asr mixed exit, WBI playurl-only refresh, brittle `.p` stem assert) were out of this targeted fix and are unchanged.

### Assessment

**Task quality:** Approved
