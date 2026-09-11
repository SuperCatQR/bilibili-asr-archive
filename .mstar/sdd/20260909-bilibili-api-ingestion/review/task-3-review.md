# Task 3 Review — Verify third-party API behavior at the package seam

- **Reviewer**: code-reviewer (leaf, L2, Mode A diff-first; delegation forbidden; no delegation performed)
- **Plan**: `20260909-bilibili-api-ingestion`
- **Range**: `0c2c379..783986a` (task body `6359e7d` + live-smoke guard fix `783986a`)
- **Diff**: `.mstar/sdd/20260909-bilibili-api-ingestion/review/task-3-diff.md` (read once; no git re-runs, no checkout mutation)
- **Report reviewed**: `.mstar/sdd/20260909-bilibili-api-ingestion/implementer-task-3-report.md`
- **Scope check**: diff touches exactly `tests/fixtures/fake_bilibili_gateway.py` (new), `tests/test_bilibili_api_gateway.py`, `tests/test_metadata_ingest.py` — matching the brief's file list. No product source changed; `storage/database.py` unmodified; `git diff --check` clean (verified).

---

## Spec Compliance

**✅ Spec compliant** (against `iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md` + plan Global Constraints + brief Task-3 checks)

| Brief / spec requirement | Evidence in diff | Verdict |
|---|---|---|
| Adapter calls only documented user/video metadata methods; never playback/subtitle | `test_gateway_source_never_names_forbidden_seam_methods` (AST scan over adapter attributes against `FORBIDDEN_SEAM_METHOD_TOKENS`, with positive control asserting `get_videos`/`get_pages`/`get_info` are seen); `test_fake_seam_exposes_only_documented_metadata_surface` (structural surface = exactly `Credential`, `user.User.get_videos`, `video.Video.get_info`/`get_pages`, 5-exception taxonomy; forbidden names raise `AttributeError`); `assert_only_documented_metadata_calls` used in both end-to-end seam tests | ✅ |
| No persisted row or test output contains SESSDATA, signed URL text, raw JSON, raw exception text | Sentinels (`SESSDATA_BOUNDARY_VALUE`, `SIGNED_URL_MARKER`, `RAW_JSON_BODY_MARKER`, `RAW_UPSTREAM_EXCEPTION_MARKER`) injected into unknown payload keys and into upstream failure text (`UPSTREAM_ERROR_TEXT`); `persisted_row_text` renders every table/view row; scans over persisted rows + run result repr/str + `caplog.text` in `test_bilibili_api_gateway_run_persists_no_upstream_payload_markers` and `test_bilibili_api_gateway_upstream_failure_persists_scalar_code_only` | ✅ |
| Live smoke: opt-in, UID 23191782, one page, temporary DB, skips cleanly | `test_live_smoke_single_public_page_for_archive_owner`: gate `BILI_LIVE_SMOKE=1` (default `pytest.skip`), `page_limit=1` → one `user.get_videos(pn=1, ps=100)`, writes `live-smoke.sqlite` under the workspace-local `tmp_root` (removed in teardown), no credential. Default-run skip verified in this review's focused run (`1 skipped`) | ✅ |
| Live smoke command + bounded expectations recorded for the CLI plan | Implementer report §3: exact invocable command, plan-style command, prerequisite (pin installed; loud fail with guidance when `BILI_LIVE_SMOKE=1` but dist missing — commit `783986a`), bounded call/page/row expectations | ✅ |
| Scope: tests + `tests/fixtures/fake_bilibili_gateway.py` only | `git diff --stat 0c2c379..783986a`: 3 files, all under `tests/` | ✅ |
| Only `sources/bilibili_api_gateway.py` imports `bilibili_api` | Re-verified by grep in the worktree: `sources/__init__.py` / `models.py` mention the name only in docstrings; adapter unchanged in this range | ✅ (unchanged invariant) |
| One bounded page per call; cursor advances only after page transaction commits | `test_bilibili_api_gateway_upstream_failure_persists_scalar_code_only`: page 1 commits (cursor stored), page 2 fails → `risk_interrupted`, `read_cursor(MID)` preserved exactly, page row holds only the scalar code | ✅ |
| One-based `page` → zero-based `page_index`; `work_id` only at view boundary | Normalization tests preserved (`page_index = page - 1`, `duration_ms = floor(seconds*1000)`); `work_id` `BV1SEAMRUNAA:p0` asserted only via `repository.list_pending_parts()` view | ✅ |
| Bounded scalar error codes; raw text/URLs/cookies/JSON process-local | Taxonomy parametrized tests preserved and strengthened (`UPSTREAM_ERROR_TEXT not in str(caught.value)`); ingest-level tests pin scalar persistence | ✅ |
| SESSDATA never serialized/logged/returned | Adapter passes value only into `Credential`; `test_shape_failure_does_not_expose_credential` preserved; sentinel never reaches DTO repr/str, rows, result, logs | ✅ |
| No network in fake-gateway tests; live smoke is the only networked test | Fake seam installs fake `bilibili_api` on `sys.modules`; offline tests re-verified green without dist (control interpreter lacks it: offline suite cannot import real package) | ✅ |
| Prior invariants D1 (non-speculative `get_info`) | `test_completed_summary_short_circuits_when_aid_present` + `test_completed_summary_fills_only_missing_aid` preserved; seam run asserts `get_info` runs exactly when vlist `aid=None` | ✅ |
| Prior invariant D3 (foreign-owner page: zero parts/detail calls, persists nothing) — end-to-end | `test_bilibili_api_gateway_foreign_owner_page_requests_no_parts`: real adapter, page with owned+foreign item → `failed`/`shape_error`, recorded calls exactly `["user.get_videos(pn=1, ps=100)"]`, 0 video/part/discovery rows, no cursor | ✅ |
| Pin `bilibili-api-python==17.4.2` + reproducible `uv.lock` | Re-verified in worktree: `pyproject.toml` pin, `uv.lock` `version = "17.4.2"` (not modified by this task) | ✅ |

Focused verification (the one sanctioned run, control interpreter):
`cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v`
→ **122 passed, 1 skipped in 0.78s** — matches the implementer's claimed numbers exactly (114 baseline + 8 new + live-smoke skip).

**⚠️ Cannot verify from diff:**
1. Full-suite result (848 passed, 1 skipped) — implementer evidence trusted; I re-ran only the sanctioned focused pair (green).
2. The live smoke against the real network — intentionally never executed here (not requested, per policy); its skip path is verified by the default run and the loud-fail guard was reviewed statically. Plan 3 / QA owns the actual live run.
3. `uv sync` reproducibility of `uv.lock` (not part of this task's write set; pin values verified in place).

---

## Strengths

- **D3 finally has seam-level end-to-end proof**: the Task-2 protocol-double pin is echoed with the real adapter, so "a foreign-owner item blocks the whole page before any parts/detail call" is no longer only a fake-protocol claim — the exact one-call upstream sequence is asserted.
- **The negative-assertion machinery is proven non-vacuous twice**: a temporary red demonstration (sentinel injected into a persisted field → scan fails with the leaked value in the message) plus a permanent guard test (`test_no_leak_marker_scan_catches_contamination`).
- **Scanner breadth is right**: `persisted_row_text` renders *every* table and view from `sqlite_master`, so the no-leak scan is not tied to hand-picked tables and keeps working as the schema grows.
- **The fake seam is a structural trap, not just a behavioral one**: it exposes only the documented surface, so silently switching to a playback/subtitle API fails at import/attribute time even before the AST scanner runs.
- **Follow-up guard fix (`783986a`) is the correct failure mode**: opted-in live smoke with a missing pinned dist now fails with install guidance instead of silently skipping — preserves the plan's "bounded expectations for the CLI plan" without a false-green.
- **Verbatim moves kept Task-1/Task-2 behavior stable**: fake package and protocol double moved with no semantic drift; only the scripted-callable support (used by multi-page seam tests) was added.

## Issues

### Critical
None.

### Important
None.

### Minor
1. **Two dead imports introduced by the refactor** (lint-level only; no behavior impact):
   - `tests/test_metadata_ingest.py:17` — `import sqlite3` is unused at HEAD (added in this diff, zero references).
   - `tests/test_bilibili_api_gateway.py:47` — `FakeApiException` is imported from the shared fixture but never referenced (its base-version uses were the local class definitions that this task moved out).
2. **Pre-existing unused import, not attributable to this task** (for plan-QC awareness only): `tests/test_metadata_ingest.py:29` — `GatewayShapeError` was already import-only at base `0c2c379`; per surgical rules leaving it untouched is correct, but it is dead code now that the fixture owns the seam.
3. **`assert_only_documented_metadata_calls` uses prefix matching** (`call.startswith(DOCUMENTED_METADATA_CALLS)`): a hypothetical recorded name like `user.get_videos_xxx` would pass. Exposure is negligible because call strings are constructed by the shared fake seam itself; optional tightening to exact-name matching only if the recorded-name format ever changes.

---

## Assessment

**Task quality: Approved**

All four brief items are implemented and evidenced; scope is exactly the sanctioned test surface; all Task-3 checks (documented-calls-only, no-leak sentinels, opt-in bounded live smoke, recorded command + bounded expectations) and prior invariants (D1, D3 end-to-end) hold. The Minor findings are lint-level and do not block; they are reported to PM for disposition (zero-residual cleanup: disposition owned by PM, not by this review).

**Recommended follow-up for PM**: fold Minor 1 into the next fix dispatch on this branch if one is opened for any other reason (do not dispatch a dedicated fix round for these alone); Minor 2/3 are optional notes for plan QC.
