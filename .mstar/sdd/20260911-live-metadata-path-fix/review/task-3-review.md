# Task 3 Review — Issue the user-video page call in a risk-control-safe shape

**Verdict: Approved** — 0 Critical, 0 Important, 3 Minor.

| Field | Value |
|---|---|
| Plan | `20260911-live-metadata-path-fix` (plan's core defect fix, D3) |
| Review mode | Mode A, L2, diff-first |
| Base → Head | `0a2e2f5` → `3a96dd1` |
| Branch / worktree | `fix/20260911-live-metadata-path-fix` @ `.worktrees/20260911-live-metadata-path-fix` (read-only; nothing written there) |
| Diff artifact | `.mstar/sdd/20260911-live-metadata-path-fix/review/task-3-diff.md` (6 files, 37 hunks) |
| Implementer report | `.mstar/sdd/20260911-live-metadata-path-fix/implementer-task-3-report.md` |
| Tree state at review | `HEAD = 3a96dd1…`, `git status --porcelain` empty, `git diff --check 0a2e2f5..3a96dd1` exit 0 |

---

## Spec Compliance

**✅ Spec compliant.**

### Locked call shape (verbatim requirement vs. code)

| Requirement | Implementation | Verdict |
|---|---|---|
| `GET x/space/wbi/arc/search` | `url`/`method` read from `user.API["info"]["video"]` (`bilibili_api_gateway.py:61`, `:346-350`) — real values verified as `https://api.bilibili.com/x/space/wbi/arc/search` / `GET` | ✅ |
| through the package's WBI-signed `Api` (`wbi=True`) | `wbi=_USER_VIDEO_PAGE_ENDPOINT["wbi"]` (`:352`) — real value `True`; `_enc_wbi` runs when `wbi` is true (`utils/network.py`, source-verified) | ✅ |
| `dm=False` | `dm=False` (`:354`) — only field the adapter overrides | ✅ |
| library's parameter set (`mid`, `ps`, `tid`, `pn`, `keyword`, `order`, `order_avoided`, `platform`, `w_webid`) | `update_params(...)` (`:356-366`) — exactly those 9 keys, values identical to the real `User.get_videos` (`user.py:455-465`: `order=order.value`, `order_avoided=True`, `platform="web"`) | ✅ |
| routed through existing normalization/validation | `_normalize_user_video_page(response, …)` unchanged (`:294`); helpers absent from diff | ✅ |
| `w_webid` = non-empty package `access_id` when available, else `""` | `_resolve_w_webid` (`:371-394`): `isinstance(access_id, str)` else `""` | ✅ |
| no retries / no fingerprint spoofing / no alternate endpoints | one `Api` request, no loop, no fabricated `dm_*`/`buvid` values, endpoint taken from the package | ✅ |

### Global Constraints

| Constraint | Evidence | Verdict |
|---|---|---|
| DTOs, protocol (4 methods), bounded taxonomy + scalar codes, page/cursor semantics, ingestor, repository, schema unchanged | `git diff --name-status 0a2e2f5..3a96dd1` = exactly 6 files: adapter, seam fixture, `test_bilibili_api_gateway.py`, and the 3 disclosed metadata test files. No `models.py`, `services/`, `storage/`, `schema.sql`, `cli.py`, `config.py` change | ✅ |
| Only `sources/bilibili_api_gateway.py` imports `bilibili_api` | `test_only_the_gateway_module_imports_bilibili_api` (AST over all `src/bili_asr/**/*.py`, asserts `offenders == ["bilibili_api_gateway.py"]`) passes unmodified | ✅ |
| Error taxonomy unchanged, including the WBI-retry case | `_await_upstream` body untouched by the diff; the 14-case `test_user_page_failures_map_onto_bounded_taxonomy` is **absent from the diff** (byte-identical) and now receives its scripted failures raised from the fake `Api.result` — i.e. from the new transport path | ✅ |
| No credential/proxy leakage into DTOs, messages, logs, fixtures, rows | token is a request parameter only; new `ACCESS_ID_BOUNDARY_VALUE` sentinel asserted absent from DTO repr (`test_…_prefers_the_package_access_id`); adapter has no logging; `_await_upstream` messages carry `detail=operation` only | ✅ |
| All tests offline; live smoke opt-in | no test-visible network; `test_live_metadata_smoke.py` untouched; focused run reports `1 skipped` (skip-by-default gate intact) | ✅ |
| No new retry/backoff; no risk-control evasion | single request, `dm` disabled (not spoofed), package endpoint used | ✅ |
| Retain pin `bilibili-api-python==17.4.2` | no dependency file in the diff; adapter behavior probed against the installed 17.4.2 | ✅ |

### Independent verification performed (not taken from the report)

1. **Real pinned package probed offline** with the control interpreter: endpoint dict keys are exactly `comment, dm, method, params, url, verify, wbi` — so every key the adapter indexes exists (no import-time `KeyError`), `dm` is `True`, and the adapter's override is the only deviation.
2. **`update_params` replaces** (`utils/network.py:2179`, `self.params = kwargs`) — the fake's "replaces the parameters" docstring is accurate, and `__post_init__`'s blanking of default params cannot affect the request.
3. **`dm` gating is real**: `utils/network.py:2227` `if self.dm: self.params = _enc_dm(self.params)`; `_enc_dm` (`:1940`) injects exactly `dm_img_list`, `dm_img_str`, `dm_cover_img_str`, `dm_img_inter` — **the same four names** the fake mirrors (`fake_bilibili_gateway.py:161`). The "no `dm_*` parameter" assertion is therefore a genuine detector, not a restatement of the flag.
4. **`w_webid` survives as a present empty parameter**: `_prepare_request` filters only `None`; `_enc_wbi` pops only `w_rid` and keeps every other key, so `""` stays present and is signed.
5. **`Api.result` is an awaitable property** (`getattr_static` → `property`, fget is a coroutine function; `network.py:2389`) and the `await Api(...).update_params(...).result` idiom is the package's own (`user.py:466`).
6. **`asyncio.CancelledError` is `BaseException`-only** (`issubclass(…, Exception) is False`) → both `_resolve_w_webid`'s `except Exception` (`:389`) and `_await_upstream`'s `except Exception` leave cancellation propagating. **Disclosure 2 upheld.**
7. **Focused suite reproduced**: `pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -q` → **158 passed, 1 skipped** (matches the report).
8. **Memoization bound**: `cli.py:571` constructs exactly one `BilibiliApiGateway` per `fetch-meta` run → `_w_webid_by_mid` (`:280`) bounds the token scrape to ≤1 per user per run; keyed by validated `mid` (positive-int checked at `:288`) → no cross-user reuse.
9. **Hunk accounting**: gateway `+75/-5` (6 hunks), fixture `+179/-20` (8), gateway tests `+175/-15` (13), cli `+6/-6` (4), e2e `+7/-7` (3), ingest `+3/-3` (3).

### Non-vacuity of the new shape tests (explicit check requested)

| If this regressed… | It would fail because |
|---|---|
| `dm` re-enabled (e.g. `Api(**endpoint)` like the library) | exact-dict assertion in `test_user_video_page_request_carries_the_documented_parameter_set` gains the 4 mirrored `dm_*` keys, and `[k for k in params if k.startswith("dm_")] == []` fails |
| `w_webid` omitted | the same exact-dict equality is missing a key (`params == {… 9 keys …}`) |
| non-empty `access_id` preference dropped | `test_user_video_page_request_prefers_the_package_access_id` asserts the sent token reaches `params["w_webid"]` |
| a transport field hard-coded | `test_user_video_page_request_follows_a_changed_package_endpoint` rewrites the package description to a sentinel URL / `wbi=False` before the adapter module is re-imported and asserts the issued request followed |
| memo not keyed per user (global value) | `test_user_video_page_resolves_the_access_id_per_user` requires two distinct `get_access_id(uid=…)` scrapes |
| regression to `user.get_videos` | the fake `User` no longer exposes the delegate; `test_fake_seam_exposes_only_documented_metadata_surface` asserts `pytest.raises(AttributeError): user.get_videos` |

All five requested non-vacuity conditions hold. The fixture deletes the adapter module from `sys.modules` before each test (`fake_bilibili_gateway.py:583`) and `_load_gateway()` re-imports it, so module-level `_USER_VIDEO_PAGE_ENDPOINT` is re-read after the sentinel mutation — the drift test is not self-fulfilling.

---

## Strengths

- **The seam defect is mirrored, not described.** The fake reproduces `_enc_dm`'s real parameter names (verified 1:1 against `utils/network.py:1940`), so `dm` re-enablement is detected structurally rather than by echoing the recorded flag. This is the difference between a real regression test and a tautology.
- **Drift protection is two-sided**: the fake's `Api` *requires* `url`/`method`/`verify`/`wbi`/`dm` (stricter than the real dataclass defaults, which would silently accept omission), and the sentinel-endpoint test proves the values are read from the package description, not baked in.
- **The removed delegate is a positive control.** Deleting `User.get_videos` from the fake plus an explicit `AttributeError` assertion converts an accidental regression into a loud, local failure — stronger than the positive-control name it replaced.
- **Red→green evidence is coherent**: 7 new tests failing against the unchanged adapter with `GatewayTransportError(transport_error)` (the correct bounded mapping for a missing seam method), then green after the adapter change; full-suite delta (+7) equals exactly the new tests.
- **Shortest durable slice**: the adapter issues the request directly, re-implements no signing/cookie/retry logic, and adds no abstraction — the offset (`dm=False`, present `w_webid`) is exactly the diagnosed defect with the rest delegated to the pinned package.
- **Docstrings carry the "why"** (412 with `dm` parameters; 412 when `w_webid` is missing; token route cost and fallback), so the two adapter-owned fields cannot be mistaken for arbitrary choices later.
- **No scope creep**: diff is exactly 6 files, no spec/doc/dependency/config drift, `git diff --check` clean.

---

## Issues

### Critical

None.

### Important

None.

### Minor

1. **Stale test docstring** — `tests/test_bilibili_api_gateway.py:1220` still reads *"The adapter imports only Credential, User, Video, and exceptions."* The enforced set (`ALLOWED_PACKAGE_IMPORTS`, line 90) is now `Credential`, `request_settings`, `user` (module), `Api`, `Video`, and the exception names. The assertion itself is strict and fail-closed (exact `==` on the import map, so an added or removed module key fails); only the prose is now inaccurate — and it was already incomplete before this task (`request_settings`). Non-blocking.
2. **`_resolve_w_webid`'s blanket `except Exception`** (`bilibili_api_gateway.py:389`) makes every non-cancellation failure of the token route — including a *programming* error such as a future package renaming `User.get_access_id` — indistinguishable from "token unavailable", silently degrading to `w_webid=""`. The consequence would then surface upstream as a 412 → `rate_limited`, which is a diagnosably misleading code for a version-drift problem. Mitigations already in place: it is the plan-locked semantic ("when available, else `""`"), documented in the docstring, and covered by a test. Non-blocking; worth remembering if the pin is ever bumped.
3. **The token route sits outside the seam's documented-call allow-list.** `assert_only_documented_metadata_calls` filters `script.calls` (`fake_bilibili_gateway.py:554`), and the `access_id` scrape is recorded separately in `script.access_id_calls` (`:337`) while the page request is the only entry appended to `calls` (`:403`). The exclusion is deliberate, documented in the fixture header, and asserted by three tests, so nothing is hidden — but note that the "every recorded call is a documented call" invariant no longer covers literally every request the adapter issues.

**Observation (no action required):** the token route costs one extra upstream request per run per user for a token the route currently never yields (memoized afterwards). The plan's Durable Roadmap already defers real `w_webid` derivation to upstream; this is a bounded footprint, not a defect. Likewise, the fake deliberately does not mirror WBI signing/cookies (documented on the fake `Api`) — a boundary that is honest but means signature well-formedness is only provable live.

---

## Disclosure adjudication

**Disclosure 1 — page-call label rename across four test files: ACCEPTED.** Verified line by line. All four files preserve strictness exactly:

- `test_metadata_ingest.py` (3 hunks, `+3/-3`): exact list equality (`script.calls == [...]`), exact concatenation (`calls_after_first + [...]`), `assert_only_documented_metadata_calls` still invoked in both tests that carry it.
- `test_metadata_cli.py` (4 hunks, `+6/-6`): exact list equality, prefix-filter equality (`[… if call.startswith("space.arc.search")] == [one element]`), exact `.count(...) == 2` / `== 1` cursor assertions.
- `test_metadata_e2e.py` (3 hunks, `+7/-7`): exact 4-entry and 6-entry ordered list equality (including the duplicated failed-resume page), exact `.count(...) == 2`, allow-list call preserved.
- `test_bilibili_api_gateway.py`: 6 label renames inside exact list equality; `ALLOWED_PACKAGE_IMPORTS` still compared with `==`; `_public_names` still `==` exact lists; the forbidden-name positive control is still a non-vacuous `<=` subset assertion, now over `{"get_access_id", "update_params", "get_pages", "get_info"}` (4 names, including the two new call-path names) instead of the obsolete `get_videos`.

Every hunk in those files is accounted for by the disclosure list; no assertion was loosened from equality to membership, no count was relaxed, no order assertion was dropped, **and the forbidden-name positive control remains non-vacuous while `get_videos` regression detection is now stronger (fake delegate removal + explicit `AttributeError` assertion). PM position upheld.**

**Disclosure 2 — `except Exception` in `_resolve_w_webid`: UPHELD.** `except Exception` cannot catch `asyncio.CancelledError` (verified `BaseException`-only), the outer `_await_upstream` handler is likewise `except Exception`, and the memo is written only after the handler, so cancellation never caches a degraded value.

**Disclosure 3 — live acceptance deferred to Task 4 / QA gate: ACCEPTED as a ⚠️ item, not a blocker.** Consistent with the plan's egress-cooldown note and the `Run:` command owned by Task 4.

---

## ⚠️ Cannot verify from diff (PM/QA to resolve)

1. **Upstream live acceptance of the new shape** (`code=0` vs 412/`-352`). Only the plan's Prepare reproduction is on record; the implementer's evidence is necessarily offline (construction-level). Task 4 + the mandatory QA gate own the bounded live request.
2. **PM-owned spec annotation is outstanding.** Task 3 checklist item 5 requires `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md` §"Required upstream calls" #1 to record the superseded transport clause (discovered 2026-09-11). The file is **unmodified** (mtime Sep 9, line 59 still reads `user.User(uid=mid).get_videos(pn=page_number, ps=100)`). The implementer correctly left it alone (brief: PM-owned, implementers must not edit the spec), so this is an open PM action, not an implementer defect — but the task's checkbox 5 is not satisfiable from the diff.
3. **Full-suite claim (892 passed, 2 skipped) not re-run** — out of scope by instruction. The focused command was independently reproduced, and the diff touches no module outside the focused files' import closure.
4. **WBI signing / cookie / buvid behavior is not mirrored by the seam**, so the signed request's well-formedness rests on source inspection (`_enc_wbi`, `_prepare_request`) plus live evidence rather than on a test.

---

## Assessment

**Task quality: Approved**

The implementation is a faithful, minimal realization of the locked call shape: the transport fields come from the pinned package's own endpoint description, exactly one field is deliberately overridden (`dm=False`), `w_webid` is unconditionally present (empty allowed, non-empty preferred), the response still flows through the untouched normalization path, and the bounded taxonomy still covers the new call site — proven by the unmodified 14-case mapping test now exercising errors raised inside `.result`. All Global Constraints hold with independent evidence: unchanged DTO/protocol/taxonomy/ingestor/repository/schema surface, single-module import boundary, no credential or token leakage, offline-only tests, no retries or risk-control evasion. The three Minor items are documentation/diagnosability polish and a deliberate, disclosed recording boundary — none blocks the task, and the two ⚠️ items are PM/QA-owned follow-ups already assigned by the plan.

No product, test, plan, or harness file was modified during this review; the only artifact written is this report.
