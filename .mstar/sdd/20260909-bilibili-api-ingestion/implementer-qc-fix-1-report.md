# Implementer Report — QC Fix Wave 1 (plan 20260909-bilibili-api-ingestion)

- Role: fullstack-dev (leaf executor, delegation forbidden)
- Working branch: `feature/20260909-bilibili-api-ingestion` · Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion`
- Base: `783986a` (reviewed HEAD) → Commit: **`3dcc51b`** `fix(sources): enforce BVID shape at summary normalization (plan QC fix wave)`
- Scope: all consolidated QC findings (W1 + S-fix-1…8); zero-residual; surgical only
- Findings cleanup: zero-residual (no finding left unimplemented; out-of-scope items untouched)

## Status: DONE

## Implemented — per-finding disposition

### W1 — bvid boundary asymmetry (Warning; qc2 W-001 / qc1 F-002) — FIXED

- **Change** (`src/bili_asr/sources/bilibili_api_gateway.py:122-125`): `_normalize_video_summary_item` now enforces the same `_BVID_PATTERN` the parts boundary applies — `if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None: raise GatewayShapeError(detail="video item has no valid bvid")` (replaces the non-empty-only check; message wording updated to stay honest for the malformed case). One-line fix as prescribed by qc2.
- **Effect**: a malformed-but-nonempty upstream bvid is now a bounded `GatewayShapeError` at the page boundary on **both** aid paths, before `get_completed_video_summary`/`get_video_parts` can consume it; the ingestor's `except GatewayError` machinery then records the page/run failure evidence and finishes the run atomically (no raw `ValueError` escape, no dangling `running` run). The classification is now symmetric: the same defect is bounded the same way regardless of `aid` presence.
- **Tests** (all new):
  - Adapter boundary, both aid flavors + a second malformed shape (`tests/test_bilibili_api_gateway.py:331-361`, `test_get_user_video_page_rejects_malformed_upstream_bvid`, parametrized `("BV1SHORT", 111) / ("BV1SHORT", None) / ("av170001", 111)`): asserts `GatewayShapeError` with code `shape_error`, "bvid" in the bounded message, and exactly one upstream page call (nothing downstream).
  - Ingestor end-to-end, both aid flavors (`tests/test_metadata_ingest.py:858-920`, `test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_cursor`, ids `aid-carrying`/`aid-less`): page 1 collects (limited), resume page 2 carries the malformed bvid → run outcome `failed`, `error_code="shape_error"`, page row `(2, "failed", "shape_error")`, run row terminal `failed` with `finished_at`, zero payload rows beyond page 1, prior cursor preserved byte-for-byte (`CursorRecord` equality), and the adapter made exactly one additional upstream call (the page fetch — the malformed id never reached the parts or detail fetches).
- **TDD**: red→green verified. Red (product unchanged): adapter test failed (no rejection, page normalized fine); aid-carrying ingestor test failed with the raw `ValueError("bvid must be a BV-prefixed 10-character id")` escaping `collect_user_pages` from `get_video_parts` (`bilibili_api_gateway.py:273`) — the exact defect; aid-less ingestor test failed on the calls assertion (`video.get_info` was reached and consumed the malformed id pre-fix). After the one-line fix: all green.

### S-fix-1 — dead/unused imports sweep — FIXED

- `tests/test_metadata_ingest.py`: removed dead `import sqlite3` (was line 17) and pre-existing dead `GatewayShapeError` import (was line 29).
- `tests/test_bilibili_api_gateway.py`: removed unused `FakeApiException` import (was line 47).
- `src/bili_asr/services/metadata_ingest.py`: removed unused `UserVideoPage` import (was line 29).
- Test `_page` helper (`tests/test_metadata_ingest.py:59-68`): removed the dead `owner_mid` parameter and the dead `mid` local it fed (the helper always built `UserVideoPage(mid=MID, …)`); docstring rewritten from the misleading "owner_mid overrides the requested mid" to the accurate "Build one validated page DTO owned by the requested user." (`_summary`'s `owner_mid` stays — it is used by the D3 foreign-owner test.)
- Unused `first` locals: `test_gateway_failure_rolls_back_page_and_preserves_cursor_for_resume` and `test_rate_limited_page_keeps_cursor_and_ends_run_risk_interrupted` now call `ingestor.collect_user_pages(MID, page_limit=1)` without the dead assignment. The two remaining `first = …` occurrences are genuinely used (`assert first.outcome == "limited"`).

### S-fix-2 — unreachable `except GatewayError: raise` in `_await_upstream` — FIXED (verified unreachable, then removed)

- **Verification**: the three wrapped lambdas call only package objects (`User.get_videos`, `Video.get_pages`, `Video.get_info`); `Credential` is constructed in `__init__` outside the wrapper; all normalization happens after `_await_upstream` returns; the application `GatewayError` classes live in `bili_asr.sources.models` which the package cannot know; and no seam test scripts an application `GatewayError` into `videos_error`/`parts_error`/`info_error` (grep: only package-family fakes and `RuntimeError`). So the branch could fire only from a scripted double raising a `GatewayError` inside `call()` — unreachable in production.
- **Change** (`src/bili_asr/sources/bilibili_api_gateway.py`): dropped the `except GatewayError: raise` branch; the catch chain is now NetworkException → ResponseCodeException → WbiRetryTimesExceedException → ResponseException → ApiException → Exception. Also removed the now-dead `GatewayError` import (was line 31) — no other reference remains in the adapter. Per Simplicity First (drop dead defensive branch), as adjudicated by qc1 F-003(e)/qc3 F-004.

### S-fix-3 — dedup aid-less completion fetches — FIXED

- **Change** (`src/bili_asr/services/metadata_ingest.py:227-237`): the summary loop now fills through a `completed_by_video: dict[str, VideoSummary]` map keyed by bvid — one detail fetch per distinct video per page (comment mirrors the existing parts-dedup rationale); duplicate entries reuse the completed summary. The `summaries` list keeps one entry per page item (duplicates included), so discovery `source_position` enumeration and entity upsert behavior are unchanged.
- **Test** (`tests/test_metadata_ingest.py:583-614`, `test_duplicate_aid_less_summaries_trigger_one_completion_call`): two identical aid-less entries on one page → `completion_calls == ["BV1DUPLICATE"]` (pre-fix: two calls), `parts_calls` one fetch, persisted aid 555, `video_count == 1`. Red→green verified (red: two completion calls).

### S-fix-4 — detail identity anchor (`detail.bvid == summary.bvid`) — FIXED

- **Change** (`src/bili_asr/sources/bilibili_api_gateway.py:230-232`): `_complete_summary_from_detail` now checks the detail's `bvid` after the owner-mid check — `if not isinstance(detail_bvid, str) or detail_bvid != summary.bvid: raise GatewayShapeError(detail="detail bvid does not match the summary")`; docstring updated ("A detail owned by another user, or one naming another video, is a bounded shape error."). The filled aid now provably belongs to the video the summary names.
- **Test** (`tests/test_bilibili_api_gateway.py:597-614`, `test_completed_summary_rejects_detail_for_another_video`): detail body for another video → `GatewayShapeError` code `shape_error`, "bvid" in the message, and the `get_info` call was the only upstream call. Red→green verified (red: aid filled from the cross-video detail).

### S-fix-5 — pin within-page duplicate-discovery flavor — FIXED (documents last-wins)

- **Change** (`src/bili_asr/services/metadata_ingest.py:391-400`, `_record_collected_page` docstring): now states the flavor — "a bvid duplicated within one page keeps the last occurrence's `source_position`: the discovery primary key `(run_id, page_number, bvid)` makes the later entry overwrite the earlier one."
- **Test** (`tests/test_metadata_ingest.py:247-283`, `test_within_page_duplicate_discovery_keeps_the_last_source_position`): a page with `BV1DUPPOS` at positions 0 and 2 interleaved with `BV1INTERVAL` at position 1 → persisted positions `{"BV1DUPPOS": 2, "BV1INTERVAL": 1}` (last wins, distinctly not first-wins). Behavior unchanged; test pins the existing flavor (qc2 S-002's "either flavor is fine — the gap is that it's unpinned").

### S-fix-6 — installed-vs-pinned `get_package_version` distinguishable — FIXED

- **Change** (`tests/test_bilibili_api_gateway.py:646-662`, `test_package_version_reports_installed_distribution`): the mocked installed distribution now returns the **different** version string `"9.9.9"` (was the same `"17.4.2"` as the pinned fallback) and asserts `get_package_version() == "9.9.9"` — the installed-distribution branch is proven, not the constant; docstring states why. The pinned-fallback test (`test_package_version_falls_back_to_pinned_literal`) kept unchanged.

### S-fix-7 — ingestor-level parts-stage failure test — FIXED (coverage pin)

- **Test** (`tests/test_metadata_ingest.py:469-516`, `test_parts_stage_failure_persists_nothing_and_leaves_the_cursor_untouched`): page fetch + summary fetch fine, `script_parts(bvid, GatewayTransportError(...))` → run `failed` with `error_code="transport_error"`, page row `(1, "failed", "transport_error")`, run row terminal with `finished_at`, zero entity/discovery rows, cursor untouched (`read_cursor is None` — no prior cursor existed on the first page), exactly one parts call. Green at introduction (it pins the existing bounded fetch-phase behavior end-to-end, per qc3 F-002).

### S-fix-8 — close the unclosed `:memory:` test connections — FIXED

- **Change** (`tests/test_metadata_ingest.py:631-641`, `test_collect_arguments_are_validated`): the per-parametrized-case `:memory:` connection is now opened once, wrapped in `try/finally: connection.close()`. The other `:memory:` connections in the suite (`tests/test_storage_schema.py`) already close in `finally` — verified, untouched.

## Tests

- **Commands** (from the feature worktree, control-worktree venv interpreter):
  - Focused red (new tests before product fixes): `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py::test_get_user_video_page_rejects_malformed_upstream_bvid tests/test_bilibili_api_gateway.py::test_completed_summary_rejects_detail_for_another_video tests/test_metadata_ingest.py::test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_cursor tests/test_metadata_ingest.py::test_duplicate_aid_less_summaries_trigger_one_completion_call … -q`
    - Output: `7 failed, 10 passed` — red exactly on W1 (both aid flavors), S-fix-3, S-fix-4 (the 10 passes are the behavior-pinning tests for S-fix-5/7/8 plus the adjusted `test_collect_arguments_are_validated`). Aid-carrying red mode confirmed as `ValueError: bvid must be a BV-prefixed 10-character id` escaping out of `collect_user_pages`; aid-less red mode confirmed as the extra `video.get_info` call consuming the malformed id.
  - Focused green: `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v`
    - Output: `131 passed, 1 skipped in 0.99s` (baseline 122 + 9 new tests; live smoke still opt-in → 1 skipped, never executed)
  - Full offline suite: `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest`
    - Output: `857 passed, 1 skipped in 41.38s` (baseline 848 + 9 new; zero regressions; live smoke skipped by default)
- **Hygiene**: `git diff --check` clean pre-commit and post-commit; worktree clean after commit.

## Files changed (commit `3dcc51b`, 4 files, +278/−30)

- `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` (W1 + S-fix-2 + S-fix-4)
- `bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py` (S-fix-1 + S-fix-3 + S-fix-5)
- `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` (W1 + S-fix-1 + S-fix-4 + S-fix-6)
- `bilibili-asr-archive/tests/test_metadata_ingest.py` (W1 + S-fix-1/3/5/7/8 tests)

`storage/` untouched; `pyproject.toml`/`uv.lock` untouched; no networked test executed.

## Disclosed test adjustments (fix legitimately changed tested behavior)

1. `test_bilibili_api_gateway_run_persists_normalized_rows` — `make_detail_response()` → `make_detail_response(bvid="BV1SEAMRUNAA")`.
2. `test_bilibili_api_gateway_run_persists_no_upstream_payload_markers` — detail gains `bvid="BV1SEAMLEAKS"`.
   Reason: both fabricated detail responses whose `bvid` (fixture default `BV1AbCdEfGhJ`) names a **different video** than the page item the run was completing — a cross-video detail the pre-fix code wrongly accepted. The S-fix-4 identity anchor correctly rejects it; the fixture detail now names the same video, preserving each test's original intent (normalized rows / no-leak evidence).
3. `test_package_version_reports_installed_distribution` — mock value changed `17.4.2` → `9.9.9` (that adjustment IS S-fix-6).

## Self-review notes

- **Surgical scope**: only the 4 files listed; every hunk maps to W1 or S-fix-1…8; product behavior beyond the listed fixes unchanged (dedup completions is S-fix-3 itself; the W1 message wording is part of W1). The two adjusted seam tests keep their original assertions; only the fixture's detail-bvid consistency changed.
- **No STOP condition triggered**: no playback/subtitle/audio/ASR surface touched; no raw JSON retention; no credential exposure (SESSDATA surface untouched; no-leak sentinel scans still green in the full suite); pagination/cursor contract untouched; storage contract untouched.
- **Out-of-scope items untouched**: dangling-`running` windows (accepted design limit — the W1 fix removes the one instance of that class the seats judged worth a code fix), `page_limit` bounding, stale-run sweep, `risk_interrupted` cursor producer, display-name capability, non-gateway-exception exit mapping (Batch 3 carries C1–C6).
- **Naming**: new identifiers run through the `naming-analyzer` discipline (见名之意): `completed_by_video` (parallel to the existing `parts_by_video`), `detail_bvid`, and the five new test names mirror the existing descriptive style (`…_rejects_malformed_upstream_bvid` mirrors `test_get_video_parts_rejects_invalid_bvid_argument`).
- **Contract readiness for Batch 3**: unchanged surfaces — `collect_user_pages` still never lets `GatewayError` escape; the documented "caller-argument `ValueError` propagates unchanged" contract still holds for genuine caller arguments (`get_video_parts`' malformed-caller-bvid `ValueError` test unchanged and green). Post-W1 the ingestor itself can no longer route an upstream-shaped malformed bvid into that path.
- **Note for re-review**: qc anchors in qc2/qc3 use branch-diff-package line numbers; the in-file anchors in this report are current post-commit line numbers.
