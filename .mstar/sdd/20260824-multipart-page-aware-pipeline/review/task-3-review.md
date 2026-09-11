# Task 3 L2 review

Reviewer: code-reviewer (Mode A)
Range: `3b7064a7d1a917e109fd2e412ab2df2c5afcfdb8..817b5c89597ec2eda2a3ff729f440daa1a8c612a`
Diff: `review/task-3.diff` (includes inherited WBI cache `30a12d8` + Task 3 `817b5c8`)

### Spec Compliance

- ❌ Issues found
  - `bilibili-asr-archive/src/bili_asr/archive.py:76-83` — architecture SSOT (`archive-foundations-architecture.md` Harvest / audio / archive): `write_archive` markdown frontmatter must include `work_id`, `bvid`, `page_index`, `cid`. Implementation still writes only `bvid`, `title`, `date`, `duration_s`, `source`, `url`. Tests assert `?p=` and path stems, not those identity fields.
- ✅ Otherwise aligned with Task 3 AC: distinct `{bvid}.pN` stems for page-aware rows; unresolved rows keep bare `{bvid}.*` and no `work_id`; `asr --pending` continues after p0 transcribe failure; README documents migration + per-`work_id` resume; single-page p0 URL has no `?p=`.
- ⚠️ Cannot verify from diff:
  - Full suite `141 passed` — trust PM re-run on `817b5c8`; not re-executed here.
  - Live pagelist / cid identity (`list_pages` must not invent cid) — not in this range; covered by prior tasks if present.
  - Collision STOP when migration would overwrite `{bvid}.pN` artifacts — Task 1 territory; this diff only preserves unresolved stems.

### Strengths

- `archive_stem` / `archive_url` keep unresolved and missing-`work_id` rows on the legacy stem and URL; page-aware rows use `artifact_stem` (no colon in filenames).
- Collision + rerun test writes both pages twice and asserts equal path dicts; p1 markdown gets `?p=2`, p0 does not.
- `asr --pending` iterates non-excluded rows, upserts by `work_id`, and a p0 `RuntimeError` leaves p0 `audio_ok` while p1 archives.
- `download-audio --bvid` no longer fabricates `needs_audio` when `_todo_for_bvid` is empty; unresolved fixture stays unassigned and writes no audio.
- Inherited WBI cache: `_wbi_key_pair` reused; playurl `-403` calls `_wbi_keys(refresh=True)`; harvest/download fixtures drop the extra `nav` response. SESSDATA/signed-URL surfaces untouched.

### Issues

#### Critical

None.

#### Important

1. **Archive frontmatter omits page identity** — `archive.py:76-83` vs architecture line 130. Two-page markdown files can share title/date and only differ by filename/`url`. Operators and later resume tooling cannot recover `work_id`/`cid` from the md document. Tests in `test_archive_md.py` do not lock the required keys.

#### Minor

1. **`asr` exit code treats mixed success as 0** — `cli.py` `return 1 if failed and not ok else 0`. Matches the new p0-fail/p1-ok test (`rc == 0`) but harvest-subs still fails the process if any page fails. Documented resume behavior is fine; process-level failure signaling is inconsistent.
2. **WBI refresh is playurl-only** — `probe_subs` uses cached keys with no `-403` retry. Acceptable for the two-page nav budget, but a rotated img/sub key can fail subtitle harvest without the playurl recovery path.
3. **Unresolved stem assertion is brittle** — `assert ".p" not in paths["srt_path"]` can pass/fail on unrelated path segments; prefer `endswith("BV1legacy.srt")` only (already present) or `artifact_stem` inequality.

### Assessment

**Task quality:** Needs fixes

Fix the `write_archive` frontmatter contract (and a test that two-page md contains distinct `work_id` / `page_index` / `cid`) before treating Task 3 as review-clean. Path collision, unresolved STOP, and p0/p1 independence are otherwise in good shape.
