# Task 1 Implementation Report — Pinned Dependency + Typed Gateway Boundary

- Plan: `20260909-bilibili-api-ingestion` (iteration `iter-2026-09-bilibili-api-sqlite`)
- Executor: fullstack-dev (leaf, delegation forbidden)
- Working branch: `feature/20260909-bilibili-api-ingestion` (worktree `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion`)
- Commit: `dfb66ba` — `feat(sources): add pinned bilibili-api gateway boundary` (6 files, +4067)
- Report file: `.mstar/sdd/20260909-bilibili-api-ingestion/implementer-task-1-report.md` (this file; the only harness file written)

## Status

**DONE_WITH_CONCERNS**

Implemented fully and verified offline. Flagged (non-blocking) items are
interpretation decisions taken because human interaction was unavailable to
this delegated leaf (`ask_user_question` rejected: "human interaction is
unavailable while the calling agent is owned by another live agent"); all
three are listed under "Open questions for PM/spec review" below and need a
confirm-or-adjust verdict from the PM before or during QC.

## Implemented

1. **Dependency pin** (`pyproject.toml`): added `bilibili-api-python==17.4.2`
   to runtime `dependencies`; `requests>=2.32` and all other declared
   dependencies unchanged. Generated `uv.lock` with `uv lock` (98 packages
   resolved, CPython 3.12.13); `uv lock --check` re-resolves as a no-op
   (reproducible). `bilibili-api-python` requires-python `>=3.10` is
   compatible with the project's `>=3.12`. `uv.lock` is committable (not
   gitignored) and is committed for reproducibility.
2. **`src/bili_asr/sources/__init__.py`**: re-exports the application-owned
   DTOs, protocol, and bounded exceptions from `models.py`. Deliberately does
   NOT import the adapter, so `import bili_asr.sources` stays importable
   without the third-party package.
3. **`src/bili_asr/sources/models.py`** (application-owned boundary):
   - DTOs, spec-verbatim fields, frozen+slots with `__post_init__`
     validation (mirrors Plan 1 `storage/models.py` style): `VideoSummary`
     (bvid/title non-empty, aid nullable int ≥1, pubdate int ≥0, mid ≥1),
     `VideoPart` (bvid non-empty, page_index ≥0, cid ≥1, title non-empty,
     duration_ms ≥1), `UserVideoPage` (mid ≥1, page_number ≥1 one-based,
     tuple of `VideoSummary`, observed_total None-or-int ≥0).
   - Protocol `BilibiliGateway` (verbatim 3 methods + the added 4th method
     `get_completed_video_summary(summary) -> VideoSummary`, see flagged
     decision D1).
   - Bounded exception taxonomy: base `GatewayError` carrying a persistable
     scalar `code` validated with Plan 1's exported `validate_error_code`
     (same bounded-code contract as storage rows), subclasses
     `GatewayRateLimited("rate_limited")`, `GatewayNotFound("not_found")`,
     `GatewayResponseError("response_error")`,
     `GatewayTransportError("transport_error")`,
     `GatewayShapeError("shape_error")` (see flagged decision D2). Exception
     messages contain only the class code + operation name — never upstream
     text, URLs, cookies, or response content.
4. **`src/bili_asr/sources/bilibili_api_gateway.py`** (the only module
   importing `bilibili_api`; import surface locked to `Credential`,
   `user.User`, `video.Video`, and five `bilibili_api.exceptions` classes —
   asserted by AST test):
   - `BilibiliApiGateway(sessdata=None)`: builds the package `Credential`
     from the optional value; blank → public access. The value is never
     serialized into DTOs, logged, embedded in exceptions, or persisted.
   - `get_user_video_page(mid, page_number, page_size=100)`: validates
     caller args (ValueError), calls `User(uid=mid, credential=...).get_videos(pn=page_number, ps=page_size)`
     (documented page parameters, verified against the pinned wheel), and
     normalizes the inner arc/search `data` (`list.vlist` dict form, with the
     plain-`list` variant tolerated) into `UserVideoPage`; `observed_total`
     from `page.count` when present, `None` when absent,
     `GatewayShapeError` when present-but-invalid. Every item must carry a
     non-empty `bvid`, non-blank title (trimmed — only surrounding
     whitespace stripped), valid `created`/`pubdate` timestamp, optional aid,
     and an owner `mid` equal to the requested `mid`, else
     `GatewayShapeError` (brief: reject owner-MID mismatch with
     `GatewayShapeError`).
   - `get_video_parts(bvid)`: validates the bvid argument format
     (`^BV[a-zA-Z0-9]{10}$`, same check the package itself applies — done
     before construction so no raw package `ArgsException` leaks), calls
     `Video(bvid=bvid, credential=...).get_pages()` and normalizes each
     pagelist element: one-based `page` → `page_index = page - 1`,
     `duration` seconds → `duration_ms = floor(seconds * 1000)` (mirrors
     Plan 1's millisecond precision rule), `cid`/`part` title validated.
     Unknown extra keys tolerated; empty array → empty tuple.
   - `get_completed_video_summary(summary)`: returns the summary unchanged
     when `aid` is present (structurally no speculative `get_info` — the
     test asserts zero calls); otherwise calls `Video.get_info()` once,
     fills ONLY `aid` (all other fields preserved from the summary), and
     reports a detail response owned by another user as `GatewayShapeError`
     (spec: "a detail response with a different owner is reported as a
     bounded gateway error").
   - `get_package_version()`: returns the installed distribution version
     (`importlib.metadata.version("bilibili-api-python")`), falling back to
     the pinned literal `17.4.2` when the distribution is absent (the
     offline/CI path).
   - `_await_upstream`: maps upstream failures onto the taxonomy —
     `NetworkException(status)` 412/429 → `rate_limited`, 404 → `not_found`,
     else `transport_error`; `ResponseCodeException(code)` in
     {-412, -352, -799} → `rate_limited`, in {-404, -62002} → `not_found`,
     else `response_error`; `WbiRetryTimesExceedException` → `rate_limited`;
     `ResponseException`/other `ApiException` → `response_error`; any other
     `Exception` → `transport_error` (bounded last resort; `BaseException`
     like `CancelledError` propagates). Mapped errors chain the upstream
     exception (`from exc`) — the chain stays process-local; only `.code`
     is persistable.
5. **`tests/test_bilibili_api_gateway.py`** (97 tests, all offline): fake
   package seam installed on `sys.modules` (mirroring the pinned package's
   real import surface, no network, no real import needed); covers DTO
   normalization (`created`→pubdate, title trim, tuple conversion, documented
   pn/ps forwarding, plain-list container, pubdate fallback, observed_total
   presence/absence/malformation), owner-MID validation (mismatch, missing),
   malformed responses (non-mapping, unknown list shape, 15 malformed-item
   cases, malformed total), part conversion (one-based→zero-based, int and
   float seconds floor, cid/title/duration/page rejections, unknown keys,
   empty tuple), argument validation (ValueError before any call), bounded
   error mapping (14 upstream-error cases on the user page + part/info
   cases; raw upstream text asserted absent from mapped messages), the
   credential boundary (SESSDATA value absent from every DTO repr/str and
   from shape-error messages), gap-fill behavior (short-circuit, fill-only
   aid, foreign detail owner, detail without aid, non-mapping detail),
   `get_package_version` (pinned fallback + installed-distribution path),
   direct DTO self-validation, and two AST import-boundary tests (only
   `bilibili_api_gateway.py` imports `bilibili_api`; its import set equals
   the allowed metadata surface).

## Tests (TDD triple)

- Test file: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
- Command: `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v` (per the brief, using the control-interpreter path because the feature worktree has no `.venv`)
- Red (before implementation):
  - `ModuleNotFoundError: No module named 'bili_asr.sources'` (1 collection error) — the boundary did not exist.
  - After first source drop, mid-TDD run: `65 failed, 33 passed` (remaining failures all traced to one root cause, see Self-review).
- Green (final):
  - Focused: `97 passed in 0.35s`
  - Pre-change baseline: full suite green before any edit (726 tests).
  - Post-change full suite: `823 passed in 40.66s` (726 pre-existing + 97 new).
- Full-suite command: `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q` → `823 passed in 40.66s`.
- No network is used by any test (fake seam only; the real package is not
  installed in the interpreter and is not required).

## Files changed (commit dfb66ba)

- `bilibili-asr-archive/pyproject.toml` — added the pinned dependency (only change)
- `bilibili-asr-archive/uv.lock` — generated, reproducible
- `bilibili-asr-archive/src/bili_asr/sources/__init__.py` — created
- `bilibili-asr-archive/src/bili_asr/sources/models.py` — created
- `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` — created
- `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` — created

Plan 1 modules (`src/bili_asr/storage/*`, `tests/test_metadata_repository.py`)
are untouched (verified via `git diff HEAD~1 --name-only`). No harness
process artifacts were modified. Control-checkout exploratory prototypes
(`refactor/`, `schema-3nf.sql`, `schema-proposal.sql`) were inspected only to
confirm they are NOT imported — nothing from them was copied.

## Drift Check evidence

- `src/bili_asr/bili_client.py`: raw-HTTP client with its own WBI signing and
  risk classification; NOT touched and NOT imported by `sources/` (the two
  clients are separate boundaries; `bili_client` remains the pure-API
  fallback path for the archival flow).
- `src/bili_asr/cli.py`: `_cmd_fetch_meta` (line 555) still routes through
  `BiliClient` + `meta_cursor` + JSONL persistence. No existing metadata
  caller was re-routed in this task — Task 2's ingestor is a new consumer and
  the fresh CLI wiring is Plan `20260909-metadata-cli-smoke` (Batch 3), so no
  caller is silently left behind: the JSONL path keeps its explicit role
  until Batch 3 switches the CLI over (documented, not silent).
- `pyproject.toml`: single-dependency addition; no unrelated dependency
  changed.
- Package import paths: new `bili_asr.sources` subpackage; no shadowing
  collisions (`sources` is a new name in the package).
- Installed package API verified against the pinned wheel
  (`bilibili_api_python-17.4.2-py3-none-any.whl` from PyPI): `User.__init__(uid, credential=None)`,
  `async User.get_videos(tid=0, pn=1, ps=30, keyword="", order=VideoOrder.PUBDATE) -> dict`
  (endpoint `x/space/wbi/arc/search`; returns the inner `data` with
  `list.vlist` items and `page.count`), `Video.__init__(bvid=None, aid=None, credential=None)`,
  `async Video.get_info() -> dict` (`x/web-interface/view`; `aid`, `title`,
  `pubdate`, `owner.mid`), `async Video.get_pages() -> List[dict]`
  (`x/player/pagelist`; `page`/`cid`/`part`/`duration`), `Credential.__init__(sessdata=None, ...)`,
  and the exceptions used for mapping (`NetworkException(status, msg)`,
  `ResponseCodeException(code, msg, raw)`, `ResponseException`,
  `ApiException`, `WbiRetryTimesExceedException`). Notably
  `Video.get_pages()` with a bvid does NOT internally call `get_info()`
  (`set_bvid` derives aid locally), so the gateway's `get_pages` usage makes
  no detail call.

## Self-review notes

- `git diff --check`: clean. Working tree clean; nothing untracked.
- Fixed during TDD: (a) the fixture initially dropped ALL `bili_asr.sources*`
  modules, which re-imported `sources/models.py` and broke class identity
  between test imports and adapter imports (`isinstance` false-negative,
  65 failures) — root-caused to a double-import, fixed by dropping ONLY the
  adapter module from the cache (one-line change, all identity-sensitive
  asserts then passed); (b) removed an accidentally valid item from the
  malformed-items parametrize table (it asserted DID NOT RAISE); (c) fixed an
  invalid `del` teardown statement (SyntaxError) into `sys.modules.pop`.
- Credential boundary verified by grep: `sessdata` appears only in the
  adapter constructor and the `Credential(...)` call; no logging/print
  modules in `sources/`; the value never enters any DTO, exception message,
  or persisted row.
- STOP conditions: none triggered. The pinned package exposes one-page
  metadata (`User.get_videos`, `Video.get_pages`) without any
  playback/subtitle import (AST evidence in tests); every normalized field
  derives from scalar values with no raw-JSON retention; the gateway
  persists nothing (no signed URL/credential storage); pagination is bounded
  to one page per call so the Task 2 cursor contract fits; no live smoke was
  run (Task 3's concern).
- Naming (per user profile preference 见名之意): `naming-analyzer` applied
  before introducing names beyond the brief's list. Spec-verbatim names were
  kept exactly (`UserVideoPage`, `VideoSummary`, `VideoPart`,
  `BilibiliGateway`, the five `Gateway*Error` classes, the three protocol
  methods). New names and rationale:
  - `BilibiliApiGateway` (adapter class): mirrors the module file name and
    reads as "the gateway over the Bilibili API via the pinned package",
    distinct from the application-owned protocol `BilibiliGateway`.
  - `get_completed_video_summary(summary)` (4th protocol method): the name
    states the behavior — returns the summary with its required gap filled,
    short-circuiting when nothing is missing.
  - `GatewayError` (taxonomy base): unambiguous base for the five bounded
    exceptions.
  - `PINNED_PACKAGE_VERSION`, `PACKAGE_DISTRIBUTION_NAME` (constants):
    UPPER_SNAKE, self-describing.
  - Private helpers `_await_upstream`, `_extract_page_items`,
    `_read_observed_total`, `_read_pubdate`, `_read_optional_aid`,
    `_normalize_video_summary_item`, `_normalize_video_part_item`,
    `_normalize_video_parts`, `_complete_summary_from_detail`,
    `_require_positive_argument`: verb-first, input→output names.
  - Test seam: `FakeUpstreamScript`, `_build_fake_package`, fixture
    `bilibili_api_seam`, loader `_load_gateway`, factories `_vlist_item`,
    `_videos_response`, `_part_item`, `_detail_response`, `_summary`.
- Deliberate non-goal (YAGNI): no `tid`/`keyword`/`order` parameters exposed
  (spec calls only pn/ps), no retry/backoff in the adapter (the package owns
  request behavior; retry policy is the ingestor/CLI layer's decision), no
  fake-gateway fixture file (that is Task 3's `tests/fixtures/fake_bilibili_gateway.py`).

## Open questions for PM / spec review (decisions taken without human confirmation)

- **D1 — 4th protocol method `get_completed_video_summary`** (the
  recommended option of the unanswerable question): the spec's typed-interface
  block lists 3 methods, but the plan lists `video.Video.get_info` as a
  required upstream API the gateway consumes, the brief binds the
  "only when the summary lacks aid" constraint to Task 1, and Task 2's file
  list does not include the gateway module — so the capability must be
  exposed in Task 1 through the protocol (services consume the protocol, not
  the concrete adapter). If the PM prefers the 3-method protocol verbatim,
  the minimal adjustment is moving the method off the protocol onto the
  adapter only (Task 2 would then consume the concrete class for this one
  capability).
- **D2 — canonical per-class error codes** (`rate_limited`, `not_found`,
  `response_error`, `transport_error`, `shape_error`): chosen over
  upstream-derived codes (e.g. `api_412`) to keep the persisted vocabulary
  small and stable; upstream numeric reasons remain available process-locally
  through the exception chain.
- **D3 — transitive ownership is ingestor-side for parts**: with
  `get_video_parts(bvid)` (spec signature), the adapter has no owner data
  from `get_pages` and must not call `get_info` speculatively, so it
  shape-validates parts only; the ingestor enforces transitivity by
  requesting parts only for summaries already validated against the
  requested `mid`. Task 2's implementer should keep this invariant (and Task
  3 can assert it end-to-end).

All three decisions are implemented consistently with the spec's
normalization/error/credential sections; none changes the persisted data
contract.
