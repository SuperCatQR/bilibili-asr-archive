---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260911-live-metadata-path-fix"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: standard tier (per Assignment); the concrete provider/model id is not exposed to this leaf session
- Review Perspective: **correctness of the upstream interaction and error handling** — WBI call shape, bounded error mapping, proxy resolution, page-size propagation, test non-vacuity (QC2 default lenses)
- Report Timestamp: 2026-09-11T08:27+08:00

## Scope

- plan_id: `20260911-live-metadata-path-fix`
- Review range / Diff basis: `25a11fe..5667844` (base = `main` when the branch was cut; 6 commits)
- Working branch (verified): `fix/20260911-live-metadata-path-fix` (`git branch --show-current` in the Review cwd)
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix` (`git rev-parse --show-toplevel`); `HEAD = 5667844747f6f146744589f0dce13411f884d5dd`; `git status --porcelain` empty
- Files reviewed: 15 (`+1206 / −122`); the review-package file list is identical to `git diff --name-only 25a11fe..5667844`
- Commit range (identical to Review range): `cc56e46`, `0a2e2f5`, `3a96dd1`, `f4af1aa`, `f44066c`, `5667844`
- Analysis methods: read-only `git diff` / `git show` / `git log` / `git status` / `git diff --check` (exit 0), `read`, `grep`; read-only inspection of the **installed pinned package source** (`bilibili_api` 17.4.2 in the control venv) and of the recorded live artifact `/tmp/task5-live-run.log`. No test / build / lint / network run; `BILI_LIVE_SMOKE` never set; no git mutation. Only file written: this report.
- Deep review: **triggered** (S1: 1206 insertions / 15 files; S6: `src/config.py` + `src/services/` + `src/sources/` + `tests/` + packaging/docs ≥ 3 boundaries). S2/S4/S5 not triggered.
- Lenses applied: **Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens**

## Findings

### 🔴 Critical

None. No merge-blocking defect found: the four focus areas (upstream call shape, error-mapping completeness, proxy resolution, test non-vacuity) are each verified against the *installed* pin, not only against the seam — see § Verified correct.

### 🟡 Warning

None.

Considered for escalation and deliberately kept at Suggestion: **F-001** (live-smoke anonymous arm accepts any bounded code — the same docs-vs-code family as the plan's own Task-4 I1 finding). Not escalated because the affected arm is *not* the plan's acceptance path (acceptance = credential + proxy; the credentialed arm is strict and calls `pytest.fail`), the bounded code is printed in the evidence line, and the plan text explicitly says to keep "the anonymous bounded-failure branch". The one-line tightening is still recommended before the QA gate.

### 🟢 Suggestion

- **[F-001] The live-smoke anonymous arm reports a reasoned skip for *any* bounded code, while its own documentation enumerates only `rate_limited` / `response_error`.** A `transport_error` (the exact D2 symptom: no proxy on a blocked egress) or a `shape_error` (normalization regression) in an uncredentialed run is therefore classified as "documented bounded anonymous rejection" and yields a SKIP instead of a failure. Fix: restrict the skip to the documented upstream-rejection set (e.g. `error_code in {"rate_limited", "response_error"}`) and fail loudly otherwise; factor the classification into a small helper so the existing offline rehearsal (`test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam`, which already scripts an `-400` → `response_error` failure) can cover it — or, if the broad branch is intended, say so explicitly in the plan so the docs and the code agree.
  - Source Type: deep-lens: Correctness Lens
  - Verification: diff/read/grep anchor — `tests/test_live_metadata_smoke.py:233-257` (`_assert_bounded_failure_rows` returns whatever scalar code the page row carries, no set check) and `:333-350` (`assert error_code in err` → `if not os.environ.get(SESSDATA_ENV_VAR): pytest.skip(...)` with the message "upstream rejects some anonymous metadata access"); `docs/metadata-storage.md:201-206` and `README.md:593-597` name only `rate_limited` / `response_error`; the rehearsal at `tests/test_live_metadata_smoke.py:444-461` proves the branch is otherwise covered offline.
  - Expected vs observed: expected an uncredentialed run whose failure is *not* an upstream anonymous rejection (transport/shape/not-found) to fail loudly vs observed it is skipped as the documented no-credential outcome (the printed evidence line does carry `error_code=…`, and the CLI prints the code at `src/bili_asr/cli.py:598-602`, so diagnosability is preserved but the pytest result is a skip).
  - Confidence: High

- **[F-002] `.env.example:14` still asserts a single anonymous-failure code (`response_error`) that the branch's own docs corrected.** The line reads "匿名会被上游风控拦截，元数据采集返回有界 response_error", while README/docs (both edited in this branch) describe the anonymous outcome as `rate_limited` **or** `response_error`, and the plan's §Problem D1 declares the iteration evidence behind that single-code claim invalid (the request never left the process). Fix: align the parenthetical with the README/docs wording (or point at them). Doc/comment only — no behaviour impact.
  - Source Type: manual-reasoning (grep-anchored)
  - Verification: `grep -n` anchors — `.env.example:14` (unchanged pre-existing line inside a file this branch edits) vs `bilibili-asr-archive/docs/metadata-storage.md:201-206` and `bilibili-asr-archive/README.md:593-597` (both enumerate the two codes) vs plan §Problem D1 ("This also invalidates the iteration's recorded live evidence").
  - Expected vs observed: expected the one operator-facing env template to state the same (two-code) anonymous expectation as the docs shipped in the same change set vs observed it still promises `response_error` alone.
  - Confidence: High

- **[F-003] `page_size` has no upper bound (or documented ceiling) at the adapter boundary, so an over-large explicit override is reported as an upstream code rather than a caller error.** `_require_positive_argument(page_size, …)` only enforces `≥ 1`; passing e.g. `100` reaches upstream and returns `-400`/HTTP 412 → `response_error`/`rate_limited`, i.e. a caller-argument mistake is rendered as upstream risk control. No in-tree caller is affected (`PAGE_SIZE = 30`; no CLI flag), so this is a latent contract/observability point: document the accepted ceiling next to the protocol default (the pin documents `ps` as `const int: 30`) or validate it. Related nit in the same area: the invalid-argument parametrization still names `100` as the nominal page size (`tests/test_bilibili_api_gateway.py:312-326`) — inert (the case fails on `mid`/`page_number` first and asserts `calls == []`), but it reads as if 100 were an accepted value after Task 5.
  - Source Type: deep-lens: Bounds Lens
  - Verification: `src/bili_asr/sources/bilibili_api_gateway.py:294` (`_require_positive_argument(page_size, "page_size")`) vs `src/bili_asr/sources/models.py:98-103` (documents 30 as the accepted value and `ps=100` as rejected); `grep -n "page_size" src/bili_asr/cli.py` → no CLI surface; `tests/test_bilibili_api_gateway.py:314`.
  - Expected vs observed: expected the documented upstream ceiling to be enforced or at least named at the only place that accepts an override vs observed an unbounded positive int forwarded as `ps`.
  - Confidence: High

- **[F-004] The fake endpoint mirror is the sole offline oracle for the call shape and is never checked against the installed distribution.** `FAKE_USER_VIDEO_PAGE_ENDPOINT` claims to mirror `bilibili_api.user.API["info"]["video"]` "literally — including `dm: True`", and every shape assertion rides on that claim, but nothing compares it to the pin (nor asserts that the pin's `Api` accepts the exact keyword set the adapter uses). A pin bump that renames a key or flips `dm`/`wbi` would stay green offline and only surface live. Fix (cheap, mirrors the Task-1 packaging-parity pattern that already reads the installed distribution's metadata): one offline test asserting the mirror against `importlib.import_module("bilibili_api.user").API["info"]["video"]` (`url`/`method`/`verify`/`wbi`/`dm` + the documented param names) and, if desired, `dataclasses.fields(Api)` ⊇ the keywords the adapter passes.
  - Source Type: deep-lens: Real-Entry-Path Lens
  - Verification: `tests/fixtures/fake_bilibili_gateway.py:65-87` (mirror literal, `"dm": True`) vs the installed pin's real dict (read directly from `bilibili_api/data/api/user.json`: keys `comment, dm, method, params, url, verify, wbi`; `dm: True`, `wbi: True`, `method: GET`, `url = https://api.bilibili.com/x/space/wbi/arc/search`); `grep -rn "FAKE_USER_VIDEO_PAGE_ENDPOINT" tests/*.py` shows it is only compared against *itself* (`test_bilibili_api_gateway.py:559-565`).
  - Expected vs observed: expected the offline oracle for a risk-control-critical call shape to be pinned to the distribution it mirrors vs observed it is a hand-maintained copy verified only by comment.
  - Confidence: High

- **[F-005] Proxy state is package-global while `resolved_proxy` is per-instance: a second gateway that resolves nothing inherits the first instance's proxy, and there is no in-app way to force a direct connection when a host exports `HTTPS_PROXY`/`ALL_PROXY` for unrelated tooling.** Both are consequences of the plan-locked design ("blank counts as unset", "apply once, leave the library default untouched") and today the CLI builds exactly one gateway per process (`src/bili_asr/cli.py:571`), so there is no shipped-path impact. Fix: document the consequence (one line in the proxy section: a host-level `HTTPS_PROXY`/`ALL_PROXY` now routes this client too; unset it to force direct) and, if multi-gateway use ever appears, add an explicit reset/force-direct path.
  - Source Type: deep-lens: Correctness Lens (state-transition coherence)
  - Verification: `src/bili_asr/sources/bilibili_api_gateway.py:277-280` (`resolved_proxy` per instance, `request_settings.set_proxy` global, no else-branch) vs `bilibili_api.utils.network.RequestSettings.set` + `get_client` (installed pin: `utils/network.py:272-290`, `1060-1095` — settings are process/loop-global and are pushed onto existing sessions); `grep -rn "BilibiliApiGateway(" src/` → one construction site.
  - Expected vs observed: expected per-instance resolution state to have no cross-instance effect vs observed it mutates a process-global the next instance inherits without a documented reset (independently re-judged from L2 Task-2 Minor #3: severity unchanged, latent).
  - Confidence: High

- **[F-006] The plan's spec correction ("annotated **and** corrected in place") is present only as an uncommitted control-worktree edit; the reviewed tree still prescribes the superseded shape and page size.** This is a *record* gap, not a branch defect: the harness precedent in this repo is that such amendments ride the plan-Done / iteration-close chore commit, so the required action is to make sure it lands and is verified from the tree before the plan is marked Done. Fix: include `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md` in that commit and re-read clause 1 + the protocol block from the committed tree (`page_size: int = 30`, WBI transport amendment); until then, the plan's §Locked decisions and the Task 3/5 checkboxes read as satisfied on evidence no reviewer of the deliverable can see.
  - Source Type: git-diff / manual-reasoning
  - Verification: `git ls-files .mstar/iterations/iter-2026-09-bilibili-api-sqlite/` → the spec **is tracked**; `git log -1 -- <spec>` → `859922f` (2026-09-09, Phase-1 prepare); control-checkout `git status --porcelain` → ` M .mstar/iterations/…/specs/bilibili-api-gateway.md` (uncommitted, alongside the harness's other in-flight files); the branch range contains **no** `.mstar` path (`git diff --name-only 25a11fe..5667844`); the branch tree's copy still reads `page_size: int = 100` (line 48) and `user.User(uid=mid).get_videos(pn=page_number, ps=100)` (line 60); precedent for committing spec corrections: `64c46d8 chore(iter-2026-09-bilibili-api-sqlite): plan-3 metadata-cli-smoke Done (… spec exit-2 contract corrected)`.
  - Expected vs observed: expected the plan-locked spec correction to exist in a commit reachable from the delivered branch/main vs observed it exists only as an uncommitted working-tree edit in the control checkout while the branch tree still names the rejected `get_videos`/`ps=100` shape.
  - Confidence: High

- **[F-007] `_resolve_w_webid`'s blanket `except Exception` (re-judged L2 Task-3 Minor #2).** Every non-cancellation failure of the token route — including a future pin renaming `User.get_access_id` — degrades to `w_webid=""` and would surface upstream as 412 → `rate_limited`, a misleading code for version drift. Plan-locked, documented, and `asyncio.CancelledError` (a `BaseException`) still propagates, so this stays a diagnosability nit: consider narrowing to the pin's exception family (or logging the failure class) if the pin is ever bumped.
  - Source Type: manual-reasoning (read-anchored)
  - Verification: `src/bili_asr/sources/bilibili_api_gateway.py:389-399` (`except Exception` → `""` memo); installed pin: `Credential`/`Api` raise `ApiException` subclasses, `CancelledError` is `BaseException`-only.
  - Expected vs observed: expected a token-route failure to be distinguishable from a programming error vs observed both collapse to "no token".
  - Confidence: High

- **[F-008] Stale test docstring (re-judged L2 Task-3 Minor #1).** `tests/test_bilibili_api_gateway.py:1267` still says "The adapter imports only Credential, User, Video, and exceptions." The enforced allow-list (`ALLOWED_PACKAGE_IMPORTS`) is now `Credential`, `request_settings`, `user` (module), `Api`, `Video`, and the exception names — the assertion is strict and fail-closed; only the prose is wrong. One-line fix.
  - Source Type: manual-reasoning (read-anchored)
  - Verification: `tests/test_bilibili_api_gateway.py:1267` vs the enforced set at `:90-104` (and the adapter's imports at `src/bili_asr/sources/bilibili_api_gateway.py:20-31`).
  - Expected vs observed: expected the docstring to name the set the test asserts vs observed it names a set that no longer exists.
  - Confidence: High

### ⚪ Unconfirmed

None. The evidence channel is intact: the assigned range reproduces exactly (`git diff --stat 25a11fe..5667844` ≡ the review package's 15 files), `HEAD` contains all six commits, and every cited input (plan, spec, L2 reviews, implementer reports, ledger, branch diff, recorded live artifact) was readable. Runtime acceptance items are **not** evidence-channel failures and are listed under "Needs L4/QA verification" below.

## Source Trace

| Finding | Source Type | Source Reference | Confidence |
|---|---|---|---|
| F-001 | deep-lens: Correctness Lens | `tests/test_live_metadata_smoke.py:233-257`, `:333-350`; `docs/metadata-storage.md:201-206`; `README.md:593-597` | High |
| F-002 | manual-reasoning (grep-anchored) | `.env.example:14` vs `docs/metadata-storage.md:201-206` / `README.md:593-597`; plan §Problem D1 | High |
| F-003 | deep-lens: Bounds Lens | `src/bili_asr/sources/bilibili_api_gateway.py:294`; `src/bili_asr/sources/models.py:98-103`; `tests/test_bilibili_api_gateway.py:314` | High |
| F-004 | deep-lens: Real-Entry-Path Lens | `tests/fixtures/fake_bilibili_gateway.py:65-87` vs installed `bilibili_api/user.json` + `user.py` (pin 17.4.2); `tests/test_bilibili_api_gateway.py:559-565` | High |
| F-005 | deep-lens: Correctness Lens | `src/bili_asr/sources/bilibili_api_gateway.py:277-280`; pin `utils/network.py:272-290`, `1060-1095`; `src/bili_asr/cli.py:571` | High |
| F-006 | git-diff / manual-reasoning | `git ls-files` + `git log -1` + control `git status --porcelain` for the pinned spec; `git diff --name-only 25a11fe..5667844`; branch-tree spec lines 48/60; precedent `64c46d8` | High |
| F-007 | manual-reasoning (read-anchored) | `src/bili_asr/sources/bilibili_api_gateway.py:389-399` | High |
| F-008 | manual-reasoning (read-anchored) | `tests/test_bilibili_api_gateway.py:1267` vs `:90-104` | High |

## Verified correct (evidence for the review focus)

**1. Upstream interaction correctness.** The transport fields come from the pin's own endpoint description, and the only deviation is the intended one: the installed 17.4.2 dict for `user.API["info"]["video"]` carries exactly `comment, dm, method, params, url, verify, wbi` — no `no_csrf` / `ignore_code` / `json_body` / `sign` / `data` / `headers` — so building `Api(url=…, method=…, verify=…, wbi=…, dm=False, credential=…)` is behaviour-identical to the pin's own `Api(**api, credential=…)` except for `dm` (dropping `params`/`comment` is inert: `update_params` replaces `params` entirely, `comment` is cosmetic). The parameter set is exactly the pin's `User.get_videos` set (`mid`, `ps`, `tid`, `pn`, `keyword`, `order=VideoOrder.PUBDATE.value`, `order_avoided=True`, `platform="web"`, `w_webid`), and `w_webid` stays present even when empty (`_prepare_request` filters only `None`; `_enc_wbi` pops only `w_rid`). Non-empty `access_id` is preferred, memoized per `mid` for the adapter's lifetime, and the CLI builds one gateway per run (`src/bili_asr/sources/bilibili_api_gateway.py:337-399`, `src/bili_asr/cli.py:571`). The token route's degradation is `Exception`-only, so `asyncio.CancelledError` propagates. Page size 30 is consistent at every site — protocol (`models.py:102`), adapter (`bilibili_api_gateway.py:283`), shipped ingestor constant (`metadata_ingest.py:50`, passed explicitly at `:229`) — with no CLI override; a repo-wide sweep for a current `ps=100`/page-size-100 claim finds only the intentional "former value"/"rejected" mentions (`docs/metadata-storage.md:210,222`, `models.py:99`, `metadata_ingest.py:46`, `test_bilibili_api_gateway.py:219`).

**2. Error-mapping completeness.** Every upstream failure of the redesigned call flows through `_await_upstream` (`bilibili_api_gateway.py:401-432`); the callable it wraps contains the token route (swallowing internally) and nothing else. The only raises outside it are caller-argument `ValueError` (`:292-294`) and shape validation (`GatewayShapeError` from the normalizers, which is itself a taxonomy branch) — both intended, and shape errors are deliberately *not* wrapped. The mapping table is unchanged by the diff and covers 412/429 → `rate_limited`, `-412`/`-352`/`-799` → `rate_limited`, 404 and `-404`/`-62002` → `not_found`, `WbiRetryTimesExceedException` → `rate_limited` (order-safe: it and `NetworkException` are independent `ApiException` siblings), `ResponseException`/`ApiException` → `response_error`, shape → `shape_error`. The final `except Exception` → `transport_error` is load-bearing rather than sloppy: `curl_cffi` raises its own `CurlError`/`RequestsError` (not an `ApiException`), so D2's connect timeout maps to a bounded `transport_error`, and no `GatewayError` can currently be raised inside a wrapped callable (nothing to double-wrap).

**3. Proxy resolution correctness.** Precedence and semantics match the locked chain exactly (`config.py:46-52`, `resolve_proxy` `:154-175`): argument → `BILI_HTTP_PROXY` → `HTTPS_PROXY` → `https_proxy` → `ALL_PROXY` → `all_proxy`, blank/whitespace = unset and never blocks a lower level, value stripped, `None` when nothing resolves (no call into the package → library default untouched). It is applied once, at construction (`bilibili_api_gateway.py:277-280`), and the pin's plumbing confirms it takes effect: `get_client()` builds `CurlCFFIClient(proxy=request_settings.get("proxy"))` → `AsyncSession(proxies={"all": proxy})`, `RequestSettings.set` also pushes a change onto an existing session via the lazy-setting path, and `Credential(proxy=None)` keeps the package's per-credential swap path inert (`utils/network.py:272-290`, `1060-1095`; `clients/CurlCFFIClient.py:52-58`, `:71-72`). Security-lens checks: no logging is configured anywhere in `src/`, the proxy and SESSDATA never enter DTOs, mapped messages, `repr`, or persisted rows (asserted), and TLS verification is untouched.

**4. Test non-vacuity across the branch.** Reverting each fix fails a test: `dm` re-enabled fails twice (`request.dm is False` *and* the injected `dm_*` params — the seam mirrors `_enc_dm`'s four names, so that assertion is a real detector); omitting `w_webid` fails the exact param-set equality; page size reverted fails the protocol-default assertion (`test_bilibili_api_gateway.py:216-231`) plus the shipped-path pins on the ingestor constant (the renamed call-string assertions sit in 10 shipped-path test functions — `test_metadata_cli.py` 4, `test_metadata_e2e.py` 3, `test_metadata_ingest.py` 3 — every one an exact list or a `.count(...) == N`); not applying the proxy fails `applied_proxies == []` vs `[value]`; removing the dependency declaration fails the pyproject assertion (`:888-935`). All task-2/3/5 renames are literal-for-literal substitutions inside exact-equality lists or `.count(...) == N` assertions — nothing loosened; `DOCUMENTED_METADATA_CALLS`, the AST import allow-list, and the forbidden-name scan's positive control were updated consistently; the seam's `user.get_videos` removal (asserted AttributeError) makes a regression to the old delegate fail loudly. The live smoke's happy-path assertions were tightened, not weakened (`cursor.next_page == page_row.page_number + 1`, `error_code IS NULL`, discoveries joined to videos), and its rehearsal runs them offline against the same CLI path.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 8 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Verdict basis: no unresolved Critical or Warning, and no Unconfirmed finding (evidence channel intact). The branch is a faithful, minimal realization of the plan's locked decisions; the four focus areas are verified against the installed pin rather than the seam alone, and the recorded live artifact `/tmp/task5-live-run.log` shows the happy path the plan claims (`outcome=limited videos=30 parts=33 discoveries=30 page_rows=1 cursor_next_page=2 cursor_state=limited observed_total=1691`, `2 passed`). The eight Suggestions are cheap polish (one test-strictness line, one env-template wording, one boundary doc, one parity test, one proxy note, one commit-hygiene action, two re-judged L2 nits) and none of them blocks merge.

**Needs L4/QA verification** (runtime proof I must not produce as L3; carried from the L2 ⚠️ items, matched to the plan's QA gate):

- Fresh-install proof: `uv sync` (or `pip install -e ".[dev]"`) yields an importable HTTP backend, and `uv lock --check` is a no-op at HEAD.
- Full offline suite at HEAD (`894 passed / 2 skipped` claim) plus the AST import-boundary and no-leak scans — not re-run by this seat by instruction.
- The bounded live smoke re-run with `-s` (credential + proxy) — QA owns acceptance; if it is run *without* a credential, F-001 is what makes a non-upstream bounded code read as a reasoned skip.
- Registry/wheel-hash sanity for `curl-cffi 0.16.3` added to `uv.lock` (Task-1 ⚠️), and the plan-Done commit check in F-006.

No product, test, plan, harness, or register file was modified during this review; the only artifact written is this report.

## Revalidation

**Seat:** qc-specialist-2 (seat 2 of N=2) · **Wave re-reviewed:** product fix wave `5667844..a898fdf` (tests + docs only) **and** PM harness commit `c9f820c` (control checkout `main`) · **Timestamp:** 2026-09-11T08:50+08:00
**Review cwd:** `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix` — branch `fix/20260911-live-metadata-path-fix`, `HEAD = a898fdfc138022dcacf9c24077f07826be9bfbc8`, `git status --porcelain` empty. Read-only throughout: no test / build / lint run, no git mutation, no network, `BILI_LIVE_SMOKE` never set; the only file written is this appended section (append-only; frontmatter untouched, and its `verdict: Approve` remains correct).

**Diff-basis integrity (verified, not assumed).** The fix-2 package is faithful: the fenced block of `review/fix-2-diff.md` is **byte-identical** to `git diff 5667844..a898fdf` (mechanical `diff` of the two byte streams, exit 0). Range = 6 files, `+344 / −21`. Commit `a898fdf` is the single commit in the range.

**Behaviour-free claim confirmed.** `git diff --name-only 5667844..a898fdf -- bilibili-asr-archive/src` is **empty**. The wave touches `.env.example`, `bilibili-asr-archive/README.md`, `bilibili-asr-archive/docs/metadata-storage.md`, `tests/fixtures/fake_bilibili_gateway.py`, `tests/test_bilibili_api_gateway.py`, `tests/test_live_metadata_smoke.py` — no production code, so no shipped behaviour changed in this wave.

### Per-finding verification (F-001 … F-008)

| # | Disposition claimed | Re-validated outcome |
|---|---|---|
| F-001 | fixed | **Resolved** |
| F-002 | fixed | **Resolved** |
| F-003 | documented only | **Resolved as dispositioned** (one cosmetic residual noted, non-blocking) |
| F-004 | parity tests added | **Resolved** — and verified to pass against pin 17.4.2 |
| F-005 | documented | **Resolved as dispositioned** (one optional residual noted) |
| F-006 | landed as `c9f820c` | **Resolved / verified from the committed tree** |
| F-007 | accepted, no action | **Confirmed unchanged** (no action expected) |
| F-008 | fixed in product wave | **Resolved** — but the same stale-prose class reappeared elsewhere: see **R-001** |

**F-001 — Resolved.** `ANONYMOUS_BOUNDED_ERROR_CODES = frozenset({"rate_limited", "response_error"})` (`tests/test_live_metadata_smoke.py:68`) and the gate `_assert_anonymous_error_code_is_documented` (`:293`) now guard the skip path; the live arm calls it *before* `pytest.skip` (`:372`) and the credentialed arm still ends in `pytest.fail` (`:383`). Docs/README state the restriction (`README.md:603`, `docs/metadata-storage.md:232-233`). Non-vacuity is real, in three independent directions: a positive control on a code the real CLI path produces (`response_error`, rehearsal `:495`), a negative control on a code the same real CLI path produces for a dead proxy (`transport_error`, rehearsal branch four `:506-523` with `pytest.raises(pytest.fail.Exception)`), and two parametrized unit tests whose parameters are **literal** codes, deliberately not derived from the set (`:529-550`, including `unknown_failure`). Nothing was weakened: the removed `== ("response_error")` assertion (a parenthesized string, not a tuple) is re-expressed as `error_code = …; assert error_code == "response_error"` — equivalent. The helper receives a scalar: `_assert_bounded_failure_rows` returns `str(error_code)` (`:274`).

**F-002 — Resolved.** `.env.example:14-15` now reads "匿名元数据采集被上游风控拦截时以有界 `rate_limited` 结束，其他上游失败为有界 `response_error`；口径与 README、docs/metadata-storage.md 一致" — the same two-code story as `README.md:600-603` and `docs/metadata-storage.md:226-233`. Single root template, matching the `cc556ae` consolidation.

**F-003 — Resolved as dispositioned (docs-only, no runtime validation).** New `### Page size` section (`docs/metadata-storage.md:115-127`: defaults 30, shipped `PAGE_SIZE = 30` passed explicitly, `ps=30`/`ps=50` accepted vs `ps=100` rejected, override "neither clamps nor rejects", no CLI flag) plus the README sentence (`README.md:509-512`). One residual, unchanged and inert: the invalid-argument parametrization still names `100` as the nominal page size (`tests/test_bilibili_api_gateway.py:382-395`, cases `(0,1,100)`, `(MID,0,100)`, `(MID,1,0)`), which after this doc change reads more clearly as a stale literal — the case still fails on `mid`/`page_number` first and asserts `calls == []`, so it is cosmetic only. Not worth another wave.

**F-004 — Resolved, and statically proven green against the pin.** Three offline tests: mirror parity (`:655`), behavioural "`dm` is the only override" (`:688`), and `set_proxy`/`get_proxy` signature parity (`:717`), on top of a tightened packaging test (`:1096`). They pass against the installed pin 17.4.2 because every asserted fact checks out against the distribution itself: `bilibili_api/user.py:22 API = get_api("user")` resolves `API["info"]["video"]` from `data/api/user.json` with `url=https://api.bilibili.com/x/space/wbi/arc/search`, `method=GET`, `verify=False`, `wbi=True`, `dm=True`, and params keys `{keyword, mid, pn, ps, tid, w_webid}` — identical to `FAKE_USER_VIDEO_PAGE_ENDPOINT` (`fixtures/fake_bilibili_gateway.py:68-83`), so the field and param-name-set assertions hold; `MIRRORED_ENDPOINT_FIELDS = ("url","method","verify","wbi")` (`:90`) is a subset of the pin's keys. For the signature test, `request_settings = RequestSettings()` (`utils/network.py:430`) is an *instance*, so `inspect.signature` on the bound `set_proxy(self, proxy: str)` / `get_proxy(self)` yields `(proxy: str)` / `()` — exactly the fake's module-level `set_proxy(proxy: str)` / `get_proxy()` (`fixtures:307-321`). Non-vacuity is sound: the dm-override test mutates the seam dict that the fake's `user.API["info"]["video"]` *shares by identity* (`fixtures:358`), so the in-place `.update(pinned_endpoint)` really re-scripts the seam rather than copying into a dead dict; the probe is captured at module import (`:144`, `:172`) before any seam fixture can shadow `sys.modules`, and the fake's `Api` records exactly the attributes read (`url/method/verify/wbi/dm`, `fixtures:189-203`).

**F-005 — Resolved as dispositioned.** `docs/metadata-storage.md:149-158` (process-global reach; blank cannot override a host-level variable; "no in-app switch", explicit list of all five variables to unset) and `README.md:541-543`. Optional residual: the operator-facing `.env.example:22-23` proxy block still describes only the precedence chain and "均未设置时不强制代理" without the new force-direct caveat — the F-002 precedent (template should match the docs it points operators to) would argue for one added line; it is not part of the accepted disposition and is not required.

**F-006 — Resolved and verified from the committed state.** `c9f820c` is an ancestor of `main` and modifies exactly four files (`git show --numstat`: spec `24/2`, knowledge `21/3`, plan `80/24`, workflow snapshot `16/4`) — no ignored/force-added artifact, and no other file. From the committed tree: the protocol block now reads `page_size: int = 30` and lists the 4th shipped method `get_completed_video_summary`; the page-call clause reads "One bounded page of the user's videos, `ps=30` …, issued through the WBI-signed `Api` shape"; the page-size annotation ("Page-size bound (2026-09-11, same plan)" — `const int: 30`, `ps=100` rejected) is present; no `page_size: int = 100` remains and the only `ps=100` occurrences are the labelled rejected-value evidence. Consistency with shipped code confirmed: `src/bili_asr/sources/models.py:95-111` declares the same four methods with `page_size: int = 30`, `UserVideoPage` is defined in both spec (`:24`) and code (`:75`), and the WBI/`dm=False`/`w_webid` shape matches the adapter. **Nothing here still needs to ride the plan-Done commit** — and the correction cannot be reverted by the delivery: `git diff --name-only 25a11fe..a898fdf -- .mstar` is empty (the branch touches no harness path), while `main` already carries `c9f820c`. What remains for the plan-Done chore is bookkeeping only: the plan's `## Acceptance / Done Criteria` boxes are unchecked by design while Status is `InReview` (8 unchecked boxes, still true at `main` HEAD `0819b91`).

**Late-arriving harness commits observed while this re-review ran (checked at the end, verified at HEAD).** The control checkout advanced past `c9f820c` twice during this seat's work: `94eaee9` ("fold QC re-review follow-ups") corrects the iteration compass's stale anti-bot bullet (QC-1's finding), merges the plan's duplicate Deferred bullets, advances the recorded review range to `a898fdf`, and records the post-fix-wave suite baseline (`903 passed / 2 skipped`); `0819b91` unregisters the delivered iteration lifecycle and records its completed snapshot. The control worktree is clean at `0819b91`. Re-checked at HEAD: the spec still reads `page_size: int = 30` (line 48), the corrected compass bullet is present, the plan row in `.mstar/status.json` is still `active` on integration branch `fix/20260911-live-metadata-path-fix`, and the 8 Acceptance boxes remain unchecked (pending Done). The plan's Deferred list now also carries F-003's substance ("a page-size upper bound *enforced* at the adapter boundary … currently documented only") and mirror-consolidation, so that residual is roadmap-tracked rather than dropped.

**F-007 — Confirmed, no action expected.** The wave touches no `src/` file, so `_resolve_w_webid`'s blanket `except Exception` is unchanged, as accepted.

**F-008 — Resolved.** `test_gateway_imports_stay_on_metadata_surface` now documents the exact enforced set (`tests/test_bilibili_api_gateway.py:1440-1449`), matching `ALLOWED_PACKAGE_IMPORTS` (`:93-104`) and the adapter's imports (`src/bili_asr/sources/bilibili_api_gateway.py:20-31`), including "`User` is deliberately not among them".

### New observation surfaced by this wave

**R-001 (🟢 Suggestion, new, introduced by fix wave 2) — the gateway test module's docstring still claims the installed distribution is needed by exactly one test.** The header says "Every functional test runs against a fake `bilibili_api` package … so neither the real package nor network access is ever required. … **The packaging-contract test is the one exception** to the 'installed distribution never needed' rule" (`tests/test_bilibili_api_gateway.py:14-19`). After this wave there are **four** such tests: the packaging contract (`:1052`, `:1096`) plus the three new F-004 tests, which call `_require_installed` (`:672`, `:701`, `:731`) and fail loudly without pin 17.4.2. Same class as F-008 (prose lagging the code) and self-inflicted by the fix wave that fixed F-008. Trigger: none — a maintainer reading the header may run the module expecting no pin, then meet three loud failures with install guidance; the fix is the header sentence ("the packaging-contract, mirror-parity, and pin-signature tests" / "these parity tests are the exception"). No behaviour, collection, or offline-by-default impact: probes degrade to a reason string and only those tests fail. Prose-only, hence Suggestion, not Warning.

### Regression lens over the fix wave

- **No assertion weakened.** Enumerating every hunk: the only modified existing assertion is the F-001 rehearsal refactor (equivalent, above); everything else is new assertions, prose, a fixture comment, an `__all__` addition, and a *tightening* (`set_proxy` loses its `proxy: str = ""` default so the double can no longer be more permissive than the pin — safe, since the sole call site is `bilibili_api_gateway.py:279` with an argument and no test calls it bare; the packaging test gains a loud version-drift assertion).
- **Offline-by-default preserved.** `tests/test_live_metadata_smoke.py` has no module-level `pytestmark`/`skipif`; only the live test guards itself internally (`:329`), so the new unit tests and the extended rehearsal run in every default run. `pyproject.toml` `[tool.pytest.ini_options]` is `testpaths = ["tests"]` only (no warning filters, no lint config anywhere in the repo), so no gate turns the new code into a spurious failure; no duplicate test names in either modified module.
- **Non-vacuity preserved.** The extended rehearsal keeps its positive control (a real normalized row persisted before the no-leak scans, `:450-455`) and now adds branch four; the live smoke's happy-path tightening from the earlier wave is untouched; `MIRRORED_ENDPOINT_FIELDS` is exercised by both the parity test and the behavioural adapter test.
- **Harness truthfulness.** Diff package faithful, commit topology accurate (`main` is 4 commits ahead: `c29a87a`, `c9f820c`, `94eaee9`, `0819b91`; the branch carries 7), committed spec/knowledge/plan text consistent with the shipped code, knowledge doc's invalidated "anti-bot" note explicitly retracted with the correct root cause, and the iteration compass's matching bullet corrected in `94eaee9`.

### Updated severity counts

| Severity | Open after revalidation | Detail |
|---|---|---|
| 🔴 Critical | 0 | — |
| 🟡 Warning | 0 | — |
| 🟢 Suggestion | 3 | 1 new (**R-001**, test-module docstring); 2 carried cosmetics (**F-003r** inert `100` literal in the invalid-argument parametrization — its substance is now Deferred-tracked in the plan as "page-size bound enforced at the adapter boundary"; **F-005r** `.env.example` proxy block lacks the new force-direct caveat) |
| ⚪ Unconfirmed | 0 | Evidence channel intact: assigned range reproduces exactly, the diff package is byte-identical to `git diff`, and every cited input was readable |

All eight original Suggestions are closed as dispositioned (7 fixed/landed, 1 accepted). None of the three open Suggestions is merge-blocking and none needs an R# registration: R-001 is a one-line test-docstring correction, and F-003r/F-005r are cosmetic docs/test-literal polish the PM may close as "no action" (F-003r's substance already rides the plan's Deferred list).

### Verdict

**Verdict: Approve** (unchanged from the first pass, now on re-validated evidence). The fix wave is a faithful, minimal, behaviour-free response to the tri-review: every disposition is present in the tree, F-006 is committed on `main` and structurally cannot be reverted by the delivered branch, and the new tests are non-vacuous and statically proven green against pinned `bilibili-api-python==17.4.2`. The single new item (R-001) is a one-sentence test-docstring correction.

**Still owned by L4/QA (not re-run by this seat, by instruction):** fresh-install proof (`uv sync` / `uv lock --check`); the full offline suite at `a898fdf` including the three new parity tests and the extended rehearsal; the bounded live smoke with credential + proxy (acceptance path); registry/wheel sanity for `curl-cffi 0.16.3`; and the plan-Done bookkeeping (the 8 Acceptance boxes and the `InReview` → `Done` transition, both still open at `main` HEAD `0819b91`).
