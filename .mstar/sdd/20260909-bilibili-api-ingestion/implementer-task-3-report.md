# Task 3 Implementation Report — Verify third-party API behavior at the package seam

- **Plan**: `20260909-bilibili-api-ingestion` (iteration `iter-2026-09-bilibili-api-sqlite`)
- **Task**: 3 (final task of the plan)
- **Implementer**: fullstack-dev (leaf executor, no delegation)
- **Working branch**: `feature/20260909-bilibili-api-ingestion`
- **Worktree**: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion`
- **Commits**: `6359e7d` (task body), `783986a` (live-smoke guard fix)
- **Status**: **DONE**

## 1. Implemented

All brief items implemented; product source untouched (tests + shared fixture only).

1. **Shared fixture `tests/fixtures/fake_bilibili_gateway.py`** (created) — the single
   deterministic offline fake for the package seam, hosting:
   - `FakeUpstreamScript` / `build_fake_package` / fixture `bilibili_api_seam` — the fake
     `bilibili_api` package (moved verbatim from `test_bilibili_api_gateway.py`), mirroring
     only the documented import surface (`Credential`, `user.User.get_videos`,
     `video.Video.get_info`/`get_pages`, the 5-exception taxonomy). Added: scripted
     responses may be callables receiving `(pn, ps)` so multi-page runs can be scripted
     (needed by the end-to-end seam tests). No playback/subtitle/audio/download methods
     exist on it — silent use of other package APIs fails loudly.
   - `FakeGateway` — the scripted `BilibiliGateway` protocol double (moved verbatim from
     `test_metadata_ingest.py`, reported package version now a constructor default).
   - Raw payload factories `make_vlist_item`, `make_videos_response`, `make_part_item`,
     `make_detail_response` (moved from the gateway test file; renamed to the public
     `make_*` style of the sibling `fixtures/metadata_records.py`).
   - `DOCUMENTED_METADATA_CALLS` + `assert_only_documented_metadata_calls` — the exact
     upstream call names the adapter may issue (`user.get_videos`, `video.get_info`,
     `video.get_pages`) and the scanner proving recorded calls stay on them.
   - No-secret sentinels `SESSDATA_BOUNDARY_VALUE`, `SIGNED_URL_MARKER`,
     `RAW_JSON_BODY_MARKER`, `RAW_UPSTREAM_EXCEPTION_MARKER` (realistic-looking SESSDATA
     value / signed playback URL / raw JSON body / raw upstream exception text), the
     composite `UPSTREAM_ERROR_TEXT`, `NO_LEAK_MARKERS`, scanner
     `assert_leaks_no_markers`, and `persisted_row_text(connection)` which renders every
     persisted row of every table and view as one text blob for the scans.

2. **`tests/test_bilibili_api_gateway.py`** (modified):
   - Consumes the shared fixture (removed the moved seam builder, exception mirrors, and
     raw factories; the composite sentinel text strengthens all 22 pre-existing
     upstream-failure parametrized cases). All Task-1 tests pass unchanged.
   - `test_gateway_source_never_names_forbidden_seam_methods` — AST scan of the adapter
     source: no attribute name contains a playback/subtitle/audio/ASR/export token;
     positive control asserts the scan sees `get_videos`/`get_pages`/`get_info`.
   - `test_fake_seam_exposes_only_documented_metadata_surface` — structural assertion that
     the offline seam offers exactly `User.get_videos`, `Video.get_info`/`get_pages`, the
     exception taxonomy, and a bare `Credential`; every playback/subtitle name raises
     `AttributeError` on both objects.
   - `test_gateway_dto_drops_unknown_upstream_payload_fields` — payloads carry the
     sentinels in unknown extra keys; DTOs (repr/str) drop them all; recorded calls are
     exactly the three documented ones.
   - **Opt-in live smoke** `test_live_smoke_single_public_page_for_archive_owner` — skipped
     unless `BILI_LIVE_SMOKE=1`; one bounded page for UID 23191782 into a fresh temporary
     SQLite DB; no credential; bounded upstream failure fails loudly with the scalar code;
     hygiene scan over persisted rows + result repr for `sessdata`/`pssign`/`bilivideo.com`.

3. **`tests/test_metadata_ingest.py`** (modified):
   - Consumes the shared `FakeGateway` (removed the test-local double). All Task-2 tests
     pass unchanged.
   - `test_bilibili_api_gateway_run_persists_normalized_rows` — real product adapter
     (`BilibiliApiGateway`) over the fake package seam drives a full single-page run
     through `MetadataIngestor` into the real repository: exact normalized user/video/part
     rows, work_id, page evidence, cursor state, plus the exact upstream call sequence
     (`get_videos` → `get_info` → `get_pages`) and the documented-calls assertion.
   - `test_bilibili_api_gateway_run_persists_no_upstream_payload_markers` — sentinels
     embedded in unknown payload keys on page/parts/detail responses; nothing persists
     (rows blob, result repr/str, captured logs all scanned; non-vacuity guarded by
     asserting a real row persisted).
   - `test_bilibili_api_gateway_upstream_failure_persists_scalar_code_only` — page 1
     commits and the cursor is stored; page 2 raises a `-412` response-code exception
     carrying every sentinel: run ends `risk_interrupted` with scalar `rate_limited`, the
     prior cursor is preserved exactly, the page row holds only the scalar code, and no
     sentinel reaches persisted rows, the run result, or captured logs.
   - `test_bilibili_api_gateway_foreign_owner_page_requests_no_parts` — **D3 end-to-end at
     the seam** (echo of the Task-2 protocol-double pin, now with the real adapter): a page
     with one owned item + one foreign-owner item fails at the adapter's normalization
     boundary (`shape_error`), and the recorded upstream calls are exactly one
     `user.get_videos` — zero parts fetches and zero detail calls even for the owned
     summary on the same page; zero video/part/discovery rows; no cursor.
   - `test_no_leak_marker_scan_catches_contamination` — permanent non-vacuity guard for
     the leak scanner.

## 2. Tests (commands, output, red/green evidence)

Baseline before changes (focused): `114 passed in 0.63s`.

Focused (the brief's Run line, with the control interpreter because the worktree has no
`.venv`):

```
cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v
→ 122 passed, 1 skipped in 0.81s
```

(the 1 skip is the opt-in live smoke; baseline 114 = 114 existing all-green, +8 new passing
tests, +1 skipped live smoke).

Full offline suite before commit:

```
cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest
→ 848 passed, 1 skipped in ~41s
```

(expectation "840 baseline green + new tests" holds: 840 + 8 = 848 passed, 1 skipped.)

**Red/green evidence** (no-secret assertions actually bite):

- RED: temporarily injected the signed-URL sentinel into a persisted field
  (`title=SIGNED_URL_MARKER` in the no-secret happy-path payload) and ran
  `test_bilibili_api_gateway_run_persists_no_upstream_payload_markers`:

  ```
  AssertionError: persisted rows leaked seam payload sentinels:
  ['https://upos.example.com/upyun/ssl/part.m4s?sign=SIGNED-URL-THAT-MUST-NOT-LEAK']
  FAILED .../test_metadata_ingest.py::test_bilibili_api_gateway_run_persists_no_upstream_payload_markers
  ```

- GREEN: reverted the injection; the same test passes. Permanent non-vacuity guard:
  `test_no_leak_marker_scan_catches_contamination`.

`git diff --check` clean.

## 3. Recorded live-smoke entry point (for the CLI plan `20260909-metadata-cli-smoke`)

Test: `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner`.
Default: **skipped** (`1 skipped` in every default run). Opt-in env: `BILI_LIVE_SMOKE=1`.

Exact command as invocable in this environment (worktree + control interpreter):

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion/bilibili-asr-archive \
  && BILI_LIVE_SMOKE=1 /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
  -m pytest tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner -v
```

Plan-style equivalent (product-root relative, interpreter with the pinned dist installed):

```
cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v -k live_smoke
```

**Prerequisite**: the interpreter must have `bilibili-api-python==17.4.2` installed
(`uv sync` / install the pin). The control venv used by this worktree currently does NOT
have the dist installed (`import bilibili_api` → `ModuleNotFoundError`); the pin lives in
`pyproject.toml` + `uv.lock` (verified `version = "17.4.2"`). When `BILI_LIVE_SMOKE=1` is
set but the dist is missing, the test **fails loudly** with install guidance instead of
silently skipping (commit `783986a`).

**Bounded expectations (for Plan 3's verification record):**

- UID `23191782` (未明子, archive owner); `start_page=1`, `page_limit=1`, `page_size=100`
  (`PAGE_SIZE`) → exactly ONE upstream page: `user.get_videos(pn=1, ps=100)`.
- Plus, for the videos returned on that page only: at most one `video.get_pages` per
  distinct video and one `video.get_info` per summary lacking `aid` — metadata only. No
  subtitle/playback/audio/ASR/export endpoints (the adapter structurally exposes nothing
  else; pinned by the AST and structural-surface tests).
- Writes ONLY to a fresh temporary SQLite database under the workspace-local test temp
  root (`.test-tmp/…/live-smoke.sqlite`, gitignored), deleted in the fixture teardown;
  nothing is written outside that temporary archive root.
- No credential required: the gateway is built without SESSDATA (public metadata).
- Success: one run row + one page row; outcome `limited` (non-empty first page) or
  `complete` (empty first page); all video rows owned by `23191782` with valid
  `BV…`(12-char) bvids and non-empty titles; part rows with positive cid/duration_ms.
- A bounded upstream failure (`rate_limited`/`transport_error`/`not_found`/
  `response_error`/`shape_error`) fails the smoke with the scalar code shown; rerun when
  upstream recovers. Either way nothing raw (cookies, signed URLs, JSON bodies, exception
  text) persists — offline sentinel tests prove the boundary, live rows are additionally
  scanned for `sessdata`/`pssign`/`bilivideo.com`.
- Requires network — it is the only networked test in the suite.

## 4. Files changed

- Created: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Modified: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
- Modified: `bilibili-asr-archive/tests/test_metadata_ingest.py`

## 5. Naming analysis (naming-analyzer skill, run before naming new items)

原则：见名之意，没有歧义。Decisions:

- Kept moved names for continuity with approved Tasks 1–2: `FakeUpstreamScript`,
  `FakeGateway`, fixture `bilibili_api_seam`, the five `Fake*Exception` mirrors,
  `SESSDATA_BOUNDARY_VALUE`.
- Renamed to public factory style consistent with `fixtures/metadata_records.py`:
  `_build_fake_package`→`build_fake_package`, `_vlist_item`→`make_vlist_item`,
  `_videos_response`→`make_videos_response`, `_part_item`→`make_part_item`,
  `_detail_response`→`make_detail_response`.
- New names: `FAKE_PACKAGE_VERSION` (what the fake reports — deliberately distinct from
  the pinned-version literals), `GATEWAY_ADAPTER_MODULE`, `DOCUMENTED_METADATA_CALLS`,
  `SIGNED_URL_MARKER`, `RAW_JSON_BODY_MARKER`, `RAW_UPSTREAM_EXCEPTION_MARKER`,
  `UPSTREAM_ERROR_TEXT` (one upstream failure text carrying every sentinel),
  `NO_LEAK_MARKERS`, `assert_only_documented_metadata_calls`,
  `assert_leaks_no_markers`, `persisted_row_text`; gateway-file constants
  `ALLOWED_EXCEPTION_NAMES`, `FORBIDDEN_SEAM_METHOD_TOKENS`, `LIVE_SMOKE_ENV`,
  `LIVE_HYGIENE_TOKENS`; helpers `_public_names`, `_live_smoke_requested`,
  `_seam_gateway`; test names self-describe the asserted behavior.
- One correction during the run: the token `"stream"` was removed from
  `FORBIDDEN_SEAM_METHOD_TOKENS` after a false positive on `_await_upstream` ("upstream"
  contains "stream"); the constant's comment documents why only unambiguous names belong.

## 6. Drift check (brief §Drift Check)

- `pyproject.toml`: `bilibili-api-python==17.4.2` pinned; `uv.lock` locked at `17.4.2`
  (verified entry). No unrelated dependency changes made.
- No existing metadata caller left on JSONL by this task: no product module was touched
  (`git diff --stat -- src/` empty); CLI/JSONL wiring is Plan 3's scope.
- Installed-package API: the control interpreter currently does not carry the installed
  dist (`import bilibili_api` → ModuleNotFoundError); offline tests never import it
  (fake seam), and `get_package_version()` falls back to the pinned literal (existing
  test). Recorded as the live-smoke prerequisite above.
- No uncommitted exploratory prototypes imported by the package (working tree clean
  before/after; commit contains only the three listed files).

## 7. STOP conditions — none triggered

- One-page metadata is exposed by the pinned package without playback/subtitle imports ✓
- No response field required retaining raw JSON or changing the 3NF contract ✓
- No signed URL/credential persistence is needed to resume a page ✓
- `get_videos` pagination stays bounded by the cursor contract ✓ (one page per call,
  cursor advances only on commit — re-evidenced at the seam level)
- Live smoke is bounded to one page and writes only inside the temporary test root ✓

## 8. Self-review notes

- `git diff --check` clean; commits only on the working branch; no push; no harness
  process artifacts written except this report.
- Existing Task-1/Task-2 tests were preserved behaviorally (fake package + protocol
  double moved verbatim; only the scripted-response callable support was added to the
  shared fake, used by the new end-to-end tests).
- The negative-assertion machinery is provably non-vacuous (red demo + permanent guard
  test).
- Minor observation (non-blocking, outside this task's write list):
  `tests/fixtures/__init__.py`'s one-line package docstring ("Deterministic record
  factories…") predates the new sibling module; the new module's own docstring documents
  the seam fakes. Left untouched because the file is not in the brief's file list.
