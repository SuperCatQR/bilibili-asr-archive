# Task 1 Review — Add the pinned dependency and typed gateway boundary

- **Reviewer**: code-reviewer (leaf, delegation forbidden; read-only — no commits, no branch changes, no worktree mutation)
- **Mode**: A (spec compliance first), L2 (per-task), diff-first
- **Plan**: `20260909-bilibili-api-ingestion` — iteration `iter-2026-09-bilibili-api-sqlite`
- **Branch**: `feature/20260909-bilibili-api-ingestion` (worktree `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion`)
- **Diff range**: `e62280a..dfb66ba` (reviewed via `/root/workspace/bilibili-asr-archive/.mstar/sdd/20260909-bilibili-api-ingestion/review/task-1-diff.md`; no git re-run, no checkout mutation)
- **Implementer report**: `implementer-task-1-report.md` (status DONE_WITH_CONCERNS, D1–D3 flagged; claims treated as unverified until checked against the diff)
- **Verification performed**: full diff read once; independent read-only spot-checks in the feature worktree — grep of `bilibili_api` import surface, grep of `sessdata`/logging surface, read of `storage/models.py` `_error_code`/`_ERROR_CODE_PATTERN` (the `validate_error_code` seam), and worktree line anchors. No tests re-run (implementer evidence trusted; no specific doubt warranted a focused run).

## Spec Compliance

### Primary spec (`specs/bilibili-api-gateway.md`) + plan global constraints

| # | Check | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Pin `bilibili-api-python==17.4.2`, no unrelated dependency changes | ✅ | `pyproject.toml` diff adds exactly one line (`bilibili-api-python==17.4.2`); `requests>=2.32` and all other declared deps unchanged; `uv.lock` is a new file pinning `bilibili-api-python 17.4.2` (hash recorded) and otherwise resolves the pre-existing runtime/dev deps plus the new package's transitive deps (98 packages per report; entry scan confirms requests/funasr/pytest/responses/packaging present, no removals implied by an all-additions new file) |
| 2 | Only `sources/bilibili_api_gateway.py` imports `bilibili_api` | ✅ | Diff shows imports confined to the adapter; independent grep over worktree `src/` confirms only `bilibili_api_gateway.py` has `bilibili_api` imports; two AST tests enforce this durably over all of `src/bili_asr` (`test_only_the_gateway_module_imports_bilibili_api`, `test_gateway_imports_stay_on_metadata_surface` — import set asserted equal to the allowed metadata surface) |
| 3 | `get_package_version()` exposes package version for run metadata | ✅ | `bilibili_api_gateway.py:297-303` returns `importlib.metadata.version("bilibili-api-python")` with pinned-literal fallback `"17.4.2"` (offline path); tested both branches. One interpretation note → Minor N2 |
| 4 | Credential construction without SESSDATA exposure | ✅ | Adapter takes `sessdata` only via constructor and passes it solely to `Credential(sessdata=...)` (`bilibili_api_gateway.py:243-251`); independent grep: `sessdata` appears nowhere else in `sources/`; no print/logging modules in `sources/`; tests assert the sentinel value is absent from every DTO repr/str, mapped errors, and shape-error messages |
| 5 | `get_user_video_page`: documented pn/ps, `observed_total`, owner-MID validation via `GatewayShapeError` | ✅ | Forwards `pn=page_number, ps=page_size` on `User(uid=mid, credential=...).get_videos` (test asserts recorded call `user.get_videos(pn=4, ps=50)`); `observed_total` from `page.count` when present, `None` when absent, `GatewayShapeError` when present-but-invalid (`_read_observed_total`); owner-MID must equal requested `mid` else `GatewayShapeError` (foreign-owner and missing-mid tests). Signature matches the spec protocol verbatim (`mid, page_number, page_size=100`) |
| 6 | `get_video_parts`: page-1 zero-based, `floor(seconds*1000)`, no speculative `get_info` | ✅ | `page_index = api_page - 1` (one-based ≥1 enforced first), `duration_ms = math.floor(seconds * 1000)` for int and float seconds (tests assert 12→12000, 10.5→10500); adapter path calls only `Video.get_pages` — no `get_info` anywhere except the D1 gap-fill; BVID format pre-check raises `ValueError` before any upstream call (no raw package `ArgsException` leak) |
| 7 | DTO validation (non-empty BVID/title, page_index ≥0, CID/duration >0) | ✅ | `models.py` DTOs validate in `__post_init__`: `VideoSummary` (bvid/title non-empty-after-trim contract, aid nullable ≥1, pubdate ≥0, mid ≥1), `VideoPart` (bvid, page_index ≥0, cid ≥1, title, duration_ms ≥1), `UserVideoPage` (mid ≥1, page_number ≥1 one-based, tuple-of-summary, observed_total ≥0). Adapter pre-validates the same scalars before constructing DTOs; the adapter-level `ValueError` from a zero duration is re-raised as `GatewayShapeError` (consistent) |
| 8 | Bounded error taxonomy; raw text/URLs/cookies/JSON process-local only | ✅ | Five spec-verbatim classes `GatewayRateLimited/NotFound/ResponseError/TransportError/ShapeError` with canonical per-class codes (`rate_limited`/`not_found`/`response_error`/`transport_error`/`shape_error` — D2, PM-accepted); base `GatewayError` validates `code` through Plan 1's `validate_error_code` (checked: pattern `^[A-Za-z0-9_.:-]+$`, ≤64 — accepts every gateway code including base `gateway_error`); messages contain only class name + code + short operation/field detail; 20 upstream-error mapping cases assert `UPSTREAM_TEXT` absent from every mapped message; exceptions chain upstream via `from exc` (chain stays process-local); `BaseException` (e.g. `CancelledError`) propagates — correct async hygiene |
| 9 | D1 — 4th protocol method honors "only when aid missing", no speculative `get_info` | ✅ | `get_completed_video_summary` short-circuits (`return summary` when `aid is not None`) with a test asserting zero upstream calls; when called, fills ONLY `aid` from the detail response and preserves all other summary fields; foreign detail owner → `GatewayShapeError`; detail without aid / non-mapping detail → `GatewayShapeError`. Capability lives on the application-owned protocol per PM adjudication — implementation honors both stated conditions |
| 10 | D3 — adapter does not claim parts ownership validation it does not perform | ✅ | `get_video_parts(bvid)` shape-validates page items only; no owner check claimed in code or docstrings; transitive ownership (parent video's `mid`) correctly deferred to the ingestor per PM adjudication. Tests on the parts path assert no ownership claims |
| 11 | One bounded page per gateway call; no cursor advancement in gateway | ✅ | `get_videos(pn, ps)` per call; no cursor, no persistence, no state beyond the credential handle |
| 12 | No subtitle/playback/audio/ASR/export API calls | ✅ | Import set = `Credential`, `user.User`, `video.Video`, five exceptions (AST-asserted equality); calls made = `get_videos`, `get_pages`, `get_info` (gap-fill only); the fake seam exposes no other package methods, making silent use impossible |
| 13 | No network calls in fake-gateway tests | ✅ | Tests install a fake `bilibili_api` package on `sys.modules` mirroring only the metadata surface; real package not installed in the interpreter; no HTTP libraries touched in the new test file |
| 14 | Test-seam scenarios achievable (empty page, multipart, rate-limit error, malformed items) | ✅ | All present in Task-1 scope (`duplicate summaries across repeated pages` is an ingestor/dedup scenario — Task 3's fake-gateway fixture, not a Task-1 requirement per brief) |
| 15 | Surgical scope | ✅ | Exactly the 6 brief files; Plan-1 `storage/*` untouched (only reuses its exported `validate_error_code` — reuse, not duplication); no existing caller re-routed; drift check in report is concrete (`cli.py` JSONL path keeps its role until Batch 3, documented not silent) |

**Task quality**: implementation matches the brief item-by-item; all Task-1-specific checks pass.

### ⚠️ Cannot verify from diff (for PM awareness, non-blocking)

1. **Real-package wheel claims** (`bilibili_api_gateway.py` behavior under the true 17.4.2 wheel): the adapter's normalization assumes `User.get_videos` returns the inner arc/search `data` (`list.vlist` items, `page.count`) and that `Video.get_pages` does **not** internally call `get_info`. These are implementer's wheel-inspection claims (recorded in the report); the offline fake seam mirrors the claimed surface by construction, so the diff cannot confirm them. Failure mode if wrong is a bounded `GatewayShapeError`, which Task 3's live one-page smoke for UID 23191782 would surface immediately. Suggest PM keep the wheel smoke evidence requirement in Task 3.
2. **`get_package_version` installed-vs-pinned precedence**: implementation prefers the installed distribution version, falling back to the pinned literal when the distribution is absent. With the dependency pin these coincide; they diverge only in a mis-configured environment. Defensible reading of "expose the package version", flagged here so the PM can confirm the intended semantic (report-only; zero-residual policy — disposition is PM's).
3. **Acceptance-evidence live smoke** (spec §Acceptance evidence): out of Task-1 scope per the plan's task split (implementer explicitly did not run live smoke); confirm Task 3 carries it.

## Strengths

- **D1 implemented with structural proof, not prose**: the aid-present short-circuit makes speculative `get_info` impossible in code, and `test_completed_summary_short_circuits_when_aid_present` asserts `calls == []` — the spec's "do not call it speculatively" is enforced by a test, not a comment.
- **Consistent bool-vs-int exclusion** (`isinstance(value, bool)` guards before every int check) across argument validation, response scalars, and DTO fields — the classic Python `bool`-is-`int` pitfall is handled uniformly, and tests cover it (`created: True`, `cid: True`, `page: True`, `duration: True`, `aid: True`).
- **Error mapping is evidence-driven and bounded**: status/code tables (`-412/-352/-799`, `412/429/404`, `-404/-62002`) come from the pinned package's documented risk-control signals; catch-all maps to `transport_error` while `BaseException` propagates, so task cancellation is never swallowed into a bounded code.
- **Robust fake-seam design**: the fixture re-imports only the adapter module (preserving `models.py` class identity between test imports and adapter imports — the double-import root cause the implementer hit mid-TDD and fixed at one line) and mirrors the real package's import surface with no playback/subtitle methods.
- **Import boundary is a durable guard**: AST inspection scans all of `src/bili_asr`, not just today's files, and asserts the adapter's import set equals the allowed metadata surface exactly (a plain `import bilibili_api` would fail the assertion).
- **DTO double-validation**: adapter normalizes, DTO re-validates; `_normalize_user_video_page` correctly lets `GatewayShapeError` from `_read_observed_total` propagate instead of double-wrapping it.
- **Honest reporting**: DONE_WITH_CONCERNS with all three unconfirmed decisions surfaced for PM adjudication; TDD triple complete (red states recorded, mid-TDD root-cause fix documented, full-suite baseline + post-change 823 passed).

## Issues

### Critical

None.

### Important

None.

### Minor

1. **Unreachable defensive branch** — `bilibili_api_gateway.py:335` (`except GatewayError: raise` inside `_await_upstream`): nothing inside the wrapped `call()` can raise an application `GatewayError` (upstream raises package exceptions; normalization happens outside the wrapper), so this catch is unreachable defensive handling. Harmless today; per Simplicity First it could be dropped, or kept deliberately if a future wrapped call may raise taxonomy errors. Non-blocking.
2. **Version test does not distinguish the installed branch** — `tests/test_bilibili_api_gateway.py:751-757`: the mocked installed version is the same `"17.4.2"` as the pinned fallback, so the test would also pass if `get_package_version` always returned the constant. Using a distinct mocked value would prove the installed-distribution path and pin down the precedence semantic from ⚠️-2 above. Non-blocking.
3. **Interpretation notes for the record (no action required)**: `NetworkException(429)→rate_limited`, `WbiRetryTimesExceedException→rate_limited`, and catch-all `Exception→transport_error` are implementer discretion within the spec's taxonomy requirement ("must translate errors into a small exception taxonomy") — reasonable choices, listed so plan QC sees they are decisions rather than spec-verbatim mappings.

## Assessment

**Task quality:** Approved

- Critical: 0 · Important: 0 · Minor: 3 (all non-blocking; disposition owned by PM under the zero-residual cleanup policy)
- ⚠️ items for PM: (1) real-package wheel claims (inner-`data` shape; `get_pages` makes no internal `get_info`) — verify via Task 3 live/wheel smoke; (2) `get_package_version` installed-vs-pinned precedence semantic; (3) live one-page smoke for UID 23191782 confirmed as Task-3 scope.
- D1/D2/D3 all independently verified against the diff as consistent with the PM adjudications.
