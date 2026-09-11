### Task 3: Prove distinct artifacts and reruns

- [ ] Assert two-page raw/SRT/audio/transcript paths cannot collide.
- [ ] Assert a completed or failed p0 does not suppress p1.
- [ ] Document legacy migration and page-aware resume behavior.

## Acceptance Criteria

- Two-page fixture produces `bvid:p0` and `bvid:p1` rows with distinct `cid` values and independent outcomes.
- Subtitle/audio requests use each page's cid; no automatic path selects only page zero.
- Artifact paths are distinct and stable across reruns.
- Legacy single-page rows migrate deterministically or remain explicitly unresolved; unresolved rows/artifacts are unchanged, visible to the operator, and never automatically assigned to a page.
- Full Python 3.12 test suite passes; no live HTTP or model downloads.

## STOP Conditions

- Missing stable cid/page identity in pagelist response (`list_pages` must not invent cid).
- Ambiguous legacy row ownership (preserve; do not assign `work_id`).
- Migration would overwrite an existing `{bvid}.pN` artifact or another `work_id` row.
- Multi-part `probe_subs`/`fetch_playurl_audio` without cid (must raise `AmbiguousPageError`, not `pages[0]`).
- A required interface change would break the frozen single-page compatibility surface without a Prepare revision.

## Prepare → Execute Handoff

After PM lock and specialist edits, execute tasks serially: migration tests, page-aware pipeline, then artifact/rerun tests. Plan QC is mandatory tri-review and QA is mandatory/full.
