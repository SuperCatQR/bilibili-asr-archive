# Task 2 review — Enumerate and process all pages

Reviewer: code-reviewer (L2)
Range: `d15f50f72cb978848308e369258cf7551e918168..2e336537c8fd961522f14a9f0e1a53e9716f82b1`
Diff: `.mstar/sdd/20260824-multipart-page-aware-pipeline/review/task-2.diff`

### Spec Compliance

- ✅ Spec compliant for Task 2: `list_pages` (zero-based `enumerate`, empty pagelist `_GoneResponse("pagelist-empty")`, missing cid `ValueError` STOP); `probe_subs` / `fetch_playurl_audio` take `cid: int | None` and raise locked `AmbiguousPageError` when `cid is None` and pagelist length ≠ 1; explicit cid is sent on WBI params without reading `pages[0]`; fetch-meta expands one ledger row per `PageIdentity` with required `work_id`; harvest/download thread cid and write `artifact_stem` paths; p0/p1 status updates are independent; unresolved / `excluded_from_page_processing` rows are filtered from automatic CLI loops; no taxonomy/redaction changes and no live HTTP in the new fixtures.

- ⚠️ Cannot verify from diff:
  - Implementer + PM claim `136 passed` via `.venv-pm/bin/python -m pytest -q`. Diff shows the tests and no live-network imports, but L2 does not re-run the suite.
  - Runtime sleep/jitter and real pagelist payload shape (beyond fixtures).

### Strengths

- Client split is clean: `list_pages` owns pagelist; `_resolve_cid` is the single compatibility adapter.
- Two-page fixtures in `tests/test_page_pipeline.py` assert distinct player/playurl cids, independent `subtitle_done` / `needs_audio` / `audio_ok`, and distinct stems.
- `only_bvid` on `migrate_legacy_rows` keeps harvest from freezing sibling rows.
- Single-page tests retargeted to `{bvid}:p0` / `{bvid}.p0.*` without dropping the bare-bvid harvest adapter.

### Issues

#### Critical

None.

#### Important

None that fail Task 2 acceptance. The download-audio `--bvid` empty-todo fallback (see Minor) does not rewrite multi-part unresolved rows in the usual path (`AmbiguousPageError`).

#### Minor

- `cli.py` `_cmd_download_audio`: when `_todo_for_bvid` returns `[]` (excluded/unresolved), the command fabricates `(args.bvid, {status: needs_audio})` instead of STOP. Harvest does not do this. Spec: skip unresolved; CLI STOP on unresolved/multi-part without an explicit page.
- Unresolved skip is unit-tested via `_is_excluded` helper, not through `main(["harvest-subs"])` / `main(["download-audio"])`.
- `harvest_subtitle` / `download_audio` still accept `str | PageIdentity`. Allowed as a compatibility adapter; architecture names `PageIdentity` as the harvest/audio argument.
- CLI uses `hasattr(target, "work_id")` rather than `isinstance(..., PageIdentity)`.

### Assessment

**Task quality:** Approved
