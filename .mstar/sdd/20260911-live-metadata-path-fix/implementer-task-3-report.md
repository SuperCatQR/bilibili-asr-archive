# Task 3 report — Issue the user-video page call in a risk-control-safe shape

**Status:** DONE_WITH_CONCERNS

The single concern is **procedural, not technical**: the Assignment's scope list allows
another test file "only if an exact assertion legitimately must change". The page-call
label recorded by the seam is an exact-assertion string, so **three** additional test
files carry a mechanical label rename (`tests/test_metadata_ingest.py`,
`tests/test_metadata_cli.py`, `tests/test_metadata_e2e.py`). Every one of those
assertions keeps its original strictness (exact list equality / exact count); §Disclosed
assertion changes lists each one. A second, minor concern: a token-route failure is
swallowed by design (documented in the docstring) — see §Self-review notes.

- Working branch: `fix/20260911-live-metadata-path-fix` (worktree
  `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix`)
- Implementer commit: **`3a96dd1`** `fix(gateway): issue the user-video page call in a
  risk-control-safe shape` (BASE `0a2e2f5`, Task 2)
- Branch probe at start: `pwd` = control root, worktree `HEAD` =
  `fix/20260911-live-metadata-path-fix` → matched the Assignment, so no BLOCKED.
- Diff basis check: `git diff --check 0a2e2f5..HEAD` exit 0; working tree clean after the
  commit; no push, no other branch touched.

## The call shape now issued

```
GET https://api.bilibili.com/x/space/wbi/arc/search      (url/method from the package)
    verify=False, wbi=True, dm=False, credential=<Credential>   (dm overridden; rest from the package)
    params: mid=<uid>, ps=<page_size>, tid=0, pn=<page_number>, keyword="",
            order="pubdate" (user.VideoOrder.PUBDATE.value),
            order_avoided=True, platform="web", w_webid=<access_id or "">
```

The request is awaited through `Api(...).update_params(...).result` (the package signs
`w_rid`/`wts`/`web_location` itself because `wbi=True`), inside the existing
`self._await_upstream("get_user_video_page", ...)` wrapper, and its response is handed to
the **unchanged** `_normalize_user_video_page(...)`.

## Implemented

### 1. `src/bili_asr/sources/bilibili_api_gateway.py`

- Import surface changed from `from bilibili_api.user import User` to
  `from bilibili_api import Credential, request_settings, user` plus
  `from bilibili_api.utils.network import Api`. The adapter now reads the package's own
  endpoint description through `user.API["info"]["video"]`, so `User`, `VideoOrder` and
  the config are reached through the `user` submodule (one import, no ambiguous bare
  `API`/`User` names).
- New module constant `_USER_VIDEO_PAGE_ENDPOINT = user.API["info"]["video"]` — the
  package's own description; `url`/`method`/`verify`/`wbi` are read from it so the
  adapter cannot drift from the pinned package.
- `__init__`: added `self._w_webid_by_mid: dict[int, str] = {}` (per-user token memo).
- `get_user_video_page`: the `User(...).get_videos(...)` delegate is replaced by
  `lambda: self._fetch_user_video_page(mid, page_number, page_size)` — still inside
  `_await_upstream`, so the mapping is untouched.
- New `_fetch_user_video_page(mid, page_number, page_size)`: resolves `w_webid`, builds
  the `Api` request from the package description with `dm=False`, sends the package's
  parameter set (`mid`, `ps`, `tid`, `pn`, `keyword`, `order`, `order_avoided`,
  `platform`, `w_webid`) and awaits `.result`. Docstring records **why** each of the two
  adapter-owned fields exists (`dm` → HTTP 412 with device-fingerprint parameters;
  missing `w_webid` → HTTP 412).
- New `_resolve_w_webid(mid)`: best-effort, memoized `User.get_access_id()`; a non-empty
  string is used, anything else (including a raising route) degrades to `""`. Memoized
  **per user** for the adapter's lifetime, so pages 2..N never re-scrape. Docstring
  documents the cost (one extra page fetch), the fallback, and the once-per-user bound.
- Nothing else changed: normalization helpers, DTO construction, ownership validation,
  `observed_total` semantics, and the other three protocol methods are byte-identical.

### 2. `tests/fixtures/fake_bilibili_gateway.py` (offline seam)

- `FAKE_USER_VIDEO_PAGE_ENDPOINT` — literal mirror of the pinned
  `user.API["info"]["video"]`, **including `dm: True`**, so a package-side change to any
  transport field stays visible. Tests may rewrite it via
  `script.user_video_page_endpoint` before the adapter module is imported.
- `FakeApiRequest` + `script.api_requests` — records every page request issued through
  the package `Api`: `url`, `method`, `verify`, `wbi`, `dm`, and the exact `params`
  mapping handed to `update_params`. The fake mirrors the package's `_enc_dm` injection
  when `dm` is on, so "no `dm`-family parameters are sent" is a real detector rather
  than a restatement of the recorded flag. WBI signing is deliberately **not** mirrored
  (it needs the mixin-key request); that boundary is documented on the fake `Api`.
- The fake `Api` requires the flags the adapter must state (`url`, `method`, `verify`,
  `wbi`, `dm`), exposes `update_params` and the async `result` property, and records the
  request when `.result` is awaited (i.e. when the network would happen).
- `user.API` (the endpoint description), `user.VideoOrder` (`PUBDATE`), and the
  `access_id` route (`script.access_id` / `script.access_id_error`, recorded in
  `script.access_id_calls`) were added; the now-unused **`User.get_videos` delegate was
  removed** so a regression to it fails loudly instead of silently passing through the
  fake. `bilibili_api.utils.network` is registered on `sys.modules`.
- `DOCUMENTED_METADATA_CALLS` page entry renamed `user.get_videos` → `space.arc.search`
  (the request the adapter actually issues), with the reason recorded in the comment.
  The `access_id` token route is recorded separately (not in `calls`): it is a
  memoized, best-effort token fetch, not a metadata call.

### 3. `tests/test_bilibili_api_gateway.py` — 7 new tests (the core evidence)

| Test | What it pins |
|---|---|
| `test_user_video_page_request_carries_the_documented_parameter_set` | `dm is False`; **no** `dm_*` parameter; the exact 9-parameter mapping with `w_webid` present (`""`) |
| `test_user_video_page_request_prefers_the_package_access_id` | a non-empty `access_id` is what gets sent; one `get_access_id` call; the token never reaches a DTO |
| `test_user_video_page_request_falls_back_to_empty_w_webid_when_the_route_fails` | a failing token route does not fail the page call; `w_webid=""`; no upstream text leaks |
| `test_user_video_page_resolves_the_access_id_once_per_user` | two pages of one user → exactly one scrape, two requests |
| `test_user_video_page_resolves_the_access_id_per_user` | the memo is bound to the user it was scraped for |
| `test_user_video_page_request_takes_its_transport_from_the_package_endpoint` | `url`/`method`/`verify`/`wbi` equal the package description's values while its `dm: True` is overridden |
| `test_user_video_page_request_follows_a_changed_package_endpoint` | nothing is hard-coded: rewriting the package description changes the issued URL/`wbi` |

## Tests

Focused (Assignment command, verbatim):

```
cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v
...
tests/test_bilibili_api_gateway.py::test_user_video_page_request_carries_the_documented_parameter_set PASSED
tests/test_bilibili_api_gateway.py::test_user_video_page_request_prefers_the_package_access_id PASSED
tests/test_bilibili_api_gateway.py::test_user_video_page_request_falls_back_to_empty_w_webid_when_the_route_fails PASSED
tests/test_bilibili_api_gateway.py::test_user_video_page_resolves_the_access_id_once_per_user PASSED
tests/test_bilibili_api_gateway.py::test_user_video_page_resolves_the_access_id_per_user PASSED
tests/test_bilibili_api_gateway.py::test_user_video_page_request_takes_its_transport_from_the_package_endpoint PASSED
tests/test_bilibili_api_gateway.py::test_user_video_page_request_follows_a_changed_package_endpoint PASSED
======================== 158 passed, 1 skipped in 1.06s ========================
```

Other touched suites: `pytest tests/test_metadata_cli.py tests/test_metadata_e2e.py -q`
→ **37 passed**.

Full offline suite (same interpreter, `-q`):

```
892 passed, 2 skipped in 51.26s
```

Baseline was 885 passed / 2 skipped → **+7 = exactly the new tests**, 0 removed, 0
pre-existing failures. `git diff --check 0a2e2f5..HEAD` exit 0.

### Red → green (TDD) evidence

1. Seam extended and the 7 new tests written **before** the adapter change, then run:

```
pytest tests/test_bilibili_api_gateway.py -q -k "user_video_page_request or user_video_page_resolves"
7 failed, 125 deselected in 0.69s
...
E  bili_asr.sources.models.GatewayTransportError: GatewayTransportError(transport_error): get_user_video_page
src/bili_asr/sources/bilibili_api_gateway.py:357: GatewayTransportError
```

   (The adapter still called the removed `User.get_videos` delegate, so the seam raised
   `AttributeError`, which the taxonomy mapped to `transport_error` — the correct
   bounded failure for an unknown call.)

2. Adapter implemented → same selection green, then the focused and full suites above.

### Offline structural check against the **real** pinned package

No network: constructing `Api(...)` and `update_params(...)` performs no request; only
awaiting `.result` does. Run with the control interpreter and the real installed
distribution:

```
real endpoint description: {'url': 'https://api.bilibili.com/x/space/wbi/arc/search', 'method': 'GET', 'verify': False, 'wbi': True, 'dm': True}
real Api flags: {'url': '...arc/search', 'method': 'GET', 'verify': False, 'wbi': True, 'dm': False}
params: {'mid': 23191782, 'ps': 100, 'tid': 0, 'pn': 1, 'keyword': '', 'order': 'pubdate', 'order_avoided': True, 'platform': 'web', 'w_webid': ''}
dm-family keys: []
w_webid present: True value: ''
package version: 17.4.2
```

This proves the real `Api` accepts the exact construction the adapter issues, that
`w_webid` survives as a present empty parameter, and that no `dm_*` parameter exists on
the real object (`_enc_dm` runs only when `dm` is true — source-verified in
`utils/network.py:2227`).

### Not done here (by design)

The bounded **live smoke was deliberately not run**: the plan assigns it to Task 4 and
the mandatory QA gate, and the plan records that this egress needed a cooldown after the
2026-09-11 diagnostics. Upstream acceptance of this shape therefore still rests on the
plan's recorded reproduction (`dm=False` + `w_webid=""` → `code=0`, `vlist=5`,
`page.count=1691`) plus the offline structural check above. Per the Assignment's STOP
conditions, a live 412 would be a Task-4/live concern, not a reason to change the
approach here.

## Files changed

```
bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py      (+80/-11)
bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py          (+201/-23)
bilibili-asr-archive/tests/test_bilibili_api_gateway.py               (+186/-9)
bilibili-asr-archive/tests/test_metadata_cli.py                        (+6/-6)   disclosed
bilibili-asr-archive/tests/test_metadata_e2e.py                        (+7/-7)   disclosed
bilibili-asr-archive/tests/test_metadata_ingest.py                     (+3/-3)   disclosed
```

No DTO, protocol, taxonomy, ingestor, repository, schema, CLI, config, `pyproject.toml`,
lockfile, docs, or spec file was touched. The PM-owned spec annotation in the brief was
**not** made (explicitly out of my scope).

## Disclosed assertion changes (none weakened)

1. `tests/test_bilibili_api_gateway.py::ALLOWED_PACKAGE_IMPORTS` — the AST equality
   assertion is updated to the new surface: `bilibili_api` gains `user`, the
   `bilibili_api.user` entry is dropped (the adapter imports the submodule now), and
   `bilibili_api.utils.network: {"Api"}` is added. Still an exact `==` comparison, so
   any other import still fails.
2. Page-call label rename (`"user.get_videos(pn=N, ps=100)"` →
   `"space.arc.search(pn=N, ps=100)"`) in the exact call-list assertions of
   `test_get_user_video_page_normalizes_documented_fields`,
   `test_get_user_video_page_forwards_requested_page_and_size`,
   `test_get_user_video_page_rejects_malformed_upstream_bvid`,
   `test_gateway_applies_the_resolved_proxy_once_before_the_first_call`,
   `test_gateway_leaves_the_package_setting_untouched_without_a_proxy`,
   `test_gateway_dto_drops_unknown_upstream_payload_fields`; and in the
   count/prefix assertions of `tests/test_metadata_ingest.py` (3),
   `tests/test_metadata_cli.py` (4), `tests/test_metadata_e2e.py` (3). Reason: the seam
   records the request the adapter actually issues; keeping the old label would make the
   assertion describe a call that is no longer made. Counts, order, and list equality are
   unchanged.
3. `test_gateway_source_never_names_forbidden_seam_methods` positive control:
   `{"get_videos", "get_pages", "get_info"}` → `{"get_access_id", "update_params",
   "get_pages", "get_info"}` (the adapter no longer names `get_videos`).
   `test_fake_seam_exposes_only_documented_metadata_surface`: user module surface
   `["User"]` → `["API", "User", "VideoOrder"]`, new
   `bilibili_api.utils.network == ["Api"]` assertion, plus an assertion that the removed
   `User.get_videos` delegate now raises `AttributeError`.
4. `DOCUMENTED_METADATA_CALLS` (fixture allow-list) page entry renamed to
   `space.arc.search` — the allow-list still rejects anything outside the documented
   surface.
5. Untouched and still passing, as evidence that the mapping is preserved: the 14-case
   `test_user_page_failures_map_onto_bounded_taxonomy`, `test_shape_failure_does_not_expose_credential`,
   all parts/completion taxonomy cases, the import-boundary tests, the no-leak scans, and
   the packaging parity test — all byte-identical to `0a2e2f5` (absent from the diff).

## Self-review notes

- `git diff --check` clean; `grep` over the adapter source finds no `dm`-family parameter
  other than the explicit `dm=False`; `w_webid` is unconditionally present in
  `update_params`.
- Naming: `naming-analyzer` was loaded before introducing names.
  `_USER_VIDEO_PAGE_ENDPOINT` (what the package publishes), `_fetch_user_video_page`
  (transport only — distinct from the public `get_user_video_page`, which normalizes),
  `_resolve_w_webid`/`_w_webid_by_mid` (named after the `w_webid` parameter they serve),
  `FakeApiRequest`/`api_requests` (recorded request shapes, distinct from `calls`, the
  call labels), `access_id`/`access_id_calls`/`access_id_error` (the package's own
  vocabulary), `space.arc.search` (mirrors the endpoint path).
- **Concern (documented, not hidden):** `_resolve_w_webid` catches `Exception` from the
  token route and degrades to `""`. This follows the locked decision ("the package's
  non-empty `access_id` when available, else `""`") and keeps an optional token scrape
  from failing the metadata call, but it means a genuine token-route failure is invisible
  apart from the empty parameter. It is documented in the docstring and covered by a test.
  `asyncio.CancelledError` (a `BaseException`) is deliberately *not* swallowed.
- The `access_id` scrape still costs one extra page fetch per adapter instance per user
  (memoized afterwards, verified by test). This is the package's own route; the plan's
  Durable Roadmap already defers real `w_webid` derivation to upstream.
- `Any` return on `_fetch_user_video_page` matches the existing `_await_upstream`
  contract (the package's `result` is untyped).
- No retry, fingerprint-spoofing, extra cookie plumbing, or alternative endpoint was
  added; no credential value is stored, logged, or mapped into an error.

## Remaining risk for the reviewer

The only unverified link is upstream acceptance of this exact transport shape — it needs
one cooled-down live request, which belongs to Task 4 and the QA gate, not to this task.
