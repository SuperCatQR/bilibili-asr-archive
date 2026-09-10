# Live Metadata Path Fix — transport, proxy, and risk-control-safe page call

> Post-delivery defect fix for the metadata stack shipped by iteration
> `iter-2026-09-bilibili-api-sqlite`. Standalone plan (no iteration); branch from
> `main`, PR back to `main`.

**Goal:** Make the shipped live metadata path actually work end-to-end against the real
Bilibili API: declare an HTTP client backend, make the proxy configurable, and issue the
user-video page call in a shape that passes upstream risk control — then prove it with a
bounded live smoke.

**Architecture:** All changes stay inside the Plan-2 gateway boundary
(`bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`) plus packaging
(`pyproject.toml` / `uv.lock`) and operator docs. The typed DTOs, `BilibiliGateway`
protocol, bounded error taxonomy, ingestor, repository, schema, and CLI command surface
are unchanged. The adapter owns the third-party transport shape: it resolves a proxy,
applies it to the pinned package, and issues the one-page user-video call through the
package's WBI-signed `Api` with the device-fingerprint (`dm`) parameters disabled and an
explicitly present (possibly empty) `w_webid`.

**Tech Stack:** Python 3.12, `bilibili-api-python==17.4.2` (pin retained), `curl_cffi`
(new runtime dependency), pytest, existing fake-`bilibili_api` seam.

**Execution:** mstar-sdd

## Status

- Priority: P0 (post-delivery defect; the shipped live path cannot complete)
- Task category: backend / external integration fix
- Status: InProgress
- Depends on: `iter-2026-09-bilibili-api-sqlite` (delivered, merged `b62ab88`)
- Primary context: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`
- Owner: fullstack-dev
- QA gate: mandatory

## Problem (reproduced 2026-09-11, evidence on disk)

The metadata stack passes its offline suites, but the live path fails for three
independent, individually reproduced reasons. None of them is a credential problem:
`x/web-interface/nav` returns `code=0, isLogin=True` with the operator's `BILI_SESSDATA`.

1. **D1 — no HTTP backend declared.** `bilibili-api-python==17.4.2` declares no HTTP
   client in `Requires-Dist` (and publishes no extras), yet every request raises
   `ArgsException("尚未安装第三方请求库或未注册自定义第三方请求库")` until `curl_cffi`,
   `httpx`, or `aiohttp` is installed. `pyproject.toml` adds none, so a fresh install can
   never reach the network; our adapter maps that `ArgsException` (an `ApiException`
   subclass) to `response_error`. **This also invalidates the iteration's recorded live
   evidence**: the Plan-2/Plan-3 "bounded `response_error` under anonymous access" notes
   were produced by this in-process failure — the request never left the process.
2. **D2 — the package disables proxies by default.** `bilibili_api.clients.CurlCFFIClient`
   constructs `AsyncSession(..., proxies={"all": proxy})` with `proxy=""` unless the caller
   configures one; the explicit empty entry defeats `trust_env`, so environment proxies
   (`HTTPS_PROXY`/`ALL_PROXY`) are ignored. On this host the direct route to Bilibili is
   blocked → `curl: (28) Connection timed out` for 30 s. With
   `request_settings.set_proxy("http://127.0.0.1:7890")` the same call behaves normally.
3. **D3 — the library's page-call shape trips risk control.** `user.API["info"]["video"]`
   carries `dm: True`, so the library injects device-fingerprint parameters that this
   environment cannot satisfy, and `w_webid = await self.get_access_id()` returns `None`
   because the scraper's source page no longer emits `__RENDER_DATA__`
   (`space.bilibili.com/23191782/dynamic` → HTTP 200, ~10 KB JS shell, no `access_id`).
   Order-swapped reproduction against the same credential:

   | call shape | result |
   |---|---|
   | `Api(..., wbi=True, dm=True)` + `w_webid=""` | **HTTP 412** risk-control page |
   | `Api(..., wbi=True, dm=False)` + `w_webid=""` | **`code=0`**, `vlist=5`, `page.count=1691` |
   | `Api(..., wbi=True, dm=False)` without the `w_webid` parameter | **HTTP 412** |

   With items 1–3 worked around in-process, the typed gateway fetched a real page
   (5 videos, `observed_total=1691`) and real parts (`BV1S8hA6MEvy`, 1 part, positive
   `cid`) and the ingestor/repository composition behaved as designed. After ~25 diagnostic
   requests the upstream began throttling this egress (`-799` on the legacy endpoint, then
   412/-412 on the WBI endpoint), so the final end-to-end run needs a cooldown.

## Global Constraints

- Retain the pin `bilibili-api-python==17.4.2`; do not bump or replace the library in this
  plan (a version bump would need its own spec change).
- Only `sources/bilibili_api_gateway.py` imports `bilibili_api`; the existing AST
  import-boundary test keeps enforcing this.
- DTOs, the `BilibiliGateway` protocol surface (4 methods), the bounded exception
  taxonomy and its scalar codes, page/cursor semantics, the ingestor, the repository, and
  `schema.sql` are **unchanged**.
- Credentials: `SESSDATA` still comes only from `BILI_SESSDATA` or `--sessdata`, and is
  never serialized into DTOs, exception messages, logs, fixtures, rows, or reports. Proxy
  URLs are configuration, not secrets, but must never be logged together with credential
  material.
- Proxy resolution precedence (locked): explicit constructor argument →
  `BILI_HTTP_PROXY` → `HTTPS_PROXY` → `https_proxy` → `ALL_PROXY` → `all_proxy`; when
  none is set, the adapter must not force a proxy (library default behaviour preserved).
- The user-video page call must send `w_webid` as a present string (empty allowed) and must
  not send `dm`-family parameters; if the package ever yields a non-empty `access_id`, that
  value is preferred over the empty fallback.
- All tests stay offline; the live smoke stays opt-in and bounded (UID 23191782, one page,
  temporary archive root, no subtitle/playback/audio/ASR calls, no unbounded retries).
- No new retry/backoff machinery and no attempts to defeat risk control beyond using the
  shape the upstream accepts.

## Locked decisions

- **HTTP backend:** `curl_cffi` (the library's recommended transport for risk control);
  declared as a runtime dependency in `pyproject.toml` with the lockfile regenerated.
- **Proxy surface:** `BilibiliApiGateway(sessdata=None, proxy=None)`; when a proxy
  resolves, the adapter applies it to the pinned package's request settings before the
  first call. `BILI_HTTP_PROXY` is the documented operator knob; standard `HTTPS_PROXY`
  works as a fallback so proxied hosts need no extra configuration.
- **Page call:** the adapter issues `GET x/space/wbi/arc/search` through the package's
  WBI-signed `Api` (`wbi=True`, `dm=False`) with the parameter set the library uses
  (`mid`, `ps`, `tid`, `pn`, `keyword`, `order`, `order_avoided`, `platform`, `w_webid`),
  then feeds the response through the existing normalization/validation path. The pinned
  iteration spec's "Required upstream calls #1" wording is superseded for the transport
  shape only; the spec is annotated, not rewritten.
- **Docs:** `.env.example` gains `BILI_HTTP_PROXY`; `docs/metadata-storage.md` and the
  README record the transport dependency, the proxy knob, and the corrected live-smoke
  expectations (anonymous and credentialed outcomes).

## Interfaces

- Consumes (unchanged): `MetadataRepository` (Plan 1), `MetadataIngestor` (Plan 2),
  `BilibiliGateway` protocol + DTOs, the bounded exception taxonomy.
- Produces: `BilibiliApiGateway(sessdata=None, proxy=None)` with a resolved-proxy
  attribute, a documented `BILI_HTTP_PROXY` knob, a declared `curl_cffi` dependency, and
  a live-verified one-page collection.

## Tasks

### Task 1: Declare the HTTP backend and prove the packaging contract

**Files:**
- Modify: `bilibili-asr-archive/pyproject.toml`
- Modify: `bilibili-asr-archive/uv.lock`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: existing `pyproject.toml` dependency block.
- Produces: a declared runtime HTTP backend (`curl_cffi`) so a fresh install can issue
  requests, plus an offline contract test that fails if the declaration disappears.

- [ ] Add the HTTP backend to the runtime `dependencies` (locked: `curl_cffi`) without
  touching unrelated dependencies; regenerate `uv.lock` and confirm `uv lock --check`
  reports a no-op.
- [ ] Add an offline test asserting the dependency is declared (parity between
  `pyproject.toml` and the installed distribution, mirroring the existing package-data
  parity pattern) — no network in the test.
- [ ] Record the pinned-package rationale in the test docstring: why the backend must be
  declared even though the library does not require it transitively.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

### Task 2: Resolve and apply proxy configuration in the gateway

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Modify: `bilibili-asr-archive/src/bili_asr/config.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: `BilibiliApiGateway` constructor and the pinned package's request settings.
- Produces: `BilibiliApiGateway(sessdata=None, proxy=None)` with locked precedence
  (argument → `BILI_HTTP_PROXY` → `HTTPS_PROXY` → `https_proxy` → `ALL_PROXY` →
  `all_proxy`), a `resolved_proxy` attribute, and the proxy applied to the package before
  the first request.

- [ ] Implement proxy resolution as a pure helper (empty/blank values are "unset";
  precedence exactly as locked) and apply a resolved proxy to the package's request
  settings at construction; when nothing resolves, leave the library default untouched.
- [ ] Keep the credential boundary intact: no proxy value, and never a credential, appears
  in DTOs, exception messages, logs, or persisted rows; the CLI display path stays
  presence-only.
- [ ] Test: precedence order, blank-value handling, no-proxy default (library setting
  untouched), apply-once behaviour, and the no-leak assertions over output and rows.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_cli.py -v`

### Task 3: Issue the user-video page call in a risk-control-safe shape

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
- Modify: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`
  (PM-owned annotation; the task records the superseded transport clause — implementers
  must not edit the spec themselves)

**Interfaces:**
- Consumes: the pinned package's WBI-signed `Api`, the existing normalization helpers.
- Produces: an unchanged `UserVideoPage` result produced by a call shape that passes
  upstream risk control (`dm` disabled, `w_webid` present) with bounded error mapping
  preserved.

- [ ] Replace the `User.get_videos(...)` delegate with the WBI-signed `Api` call shape
  (`dm=False`; `w_webid` = the package's non-empty `access_id` when available, else `""`),
  forwarding the same parameter set and feeding the response into the existing
  normalization/validation path unchanged.
- [ ] Keep the bounded taxonomy mapping identical (412/429 and `-412`/`-352`/`-799` →
  `rate_limited`; `-404`/`-62002` → `not_found`; shape problems → `shape_error`; other
  upstream failures → `response_error`/`transport_error`), including the WBI-retry case.
- [ ] Extend the fake seam to assert the call shape: `dm` is disabled, `w_webid` is always
  present (empty allowed), and a non-empty `access_id` is preferred when the seam provides
  one; assert no `dm`-family parameters are sent.
- [ ] Keep DTO field ownership/validation and `observed_total` semantics unchanged; the
  existing Task-1/Task-2/Task-3 test suites must pass unmodified except for explicitly
  disclosed fixtures.
- [ ] PM annotates the pinned spec's "Required upstream calls #1" with the superseded
  transport clause and the reason (discovered 2026-09-11).

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v`

### Task 4: Bounded live verification and operator documentation

**Files:**
- Modify: `bilibili-asr-archive/tests/test_live_metadata_smoke.py`
- Modify: `bilibili-asr-archive/docs/metadata-storage.md`
- Modify: `bilibili-asr-archive/README.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: the gateway, ingestor, CLI, and the operator's `BILI_SESSDATA` +
  `BILI_HTTP_PROXY`.
- Produces: live evidence of a real one-page collection and operator instructions that
  match reality.

- [ ] Update the opt-in live smoke to assert the happy path (one page, UID 23191782,
  temporary archive root, real rows: user + videos + parts + discovery + run + page and a
  cursor advanced past the committed page) while keeping the anonymous bounded-failure
  branch and the skip-by-default gate.
- [ ] Run the bounded live smoke once with the operator credential and proxy present;
  record the observed outcome, row counts, and any bounded blocker in the report. If
  upstream is still throttling, wait for the cooldown and retry once before recording a
  blocker.
- [ ] Document in `docs/metadata-storage.md` + README: the required HTTP backend, the
  `BILI_HTTP_PROXY` knob (with the standard `HTTPS_PROXY` fallback), the corrected
  live-smoke expectations, and the fact that the library needs an explicit proxy in
  proxied environments.
- [ ] Add `BILI_HTTP_PROXY` (commented, with an example) to `.env.example`.

Run: `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v`

## STOP Conditions

- The corrected call shape (`dm=False`, `w_webid` present) still returns 412/-352 from a
  cooled-down egress → document the bounded blocker with the exact evidence and escalate;
  do not add fingerprint spoofing, retry storms, or alternate credentials.
- The package cannot issue the page call without `dm` parameters in any supported shape →
  stop and escalate (upstream library change needed).
- Satisfying the transport requires changing the pinned library version → stop and ask;
  the pin is spec-locked.
- Any change would require touching the ingestor, repository, schema, or DTO contract →
  stop; that is out of scope for this plan.

## Durable Roadmap and Dependencies

- This plan closes the "live path actually works" gap left by
  `iter-2026-09-bilibili-api-sqlite`; the next iteration (subtitle/transcript) inherits the
  fixed transport.
- Deferred: real `w_webid` derivation once the upstream dynamic page restores SSR data, and
  a first-class `dm` setting if the library adds one; both are upstream-dependent and need
  no local code until then.
- Deferred: the iteration's QA note wording ("anonymous anti-bot rejection") is corrected
  by this plan's problem statement; no further remediation is required.

## Acceptance / Done Criteria

- [ ] `curl_cffi` is declared in `pyproject.toml`, `uv.lock` is reproducible
  (`uv lock --check` no-op), and a fresh install can import an HTTP backend.
- [ ] `BilibiliApiGateway` resolves and applies a proxy with the locked precedence; an
  unset proxy leaves library behaviour untouched; no proxy/credential value leaks into
  output, logs, or rows.
- [ ] The user-video page call is issued with `dm` disabled and `w_webid` present
  (non-empty preferred when available), with the bounded error taxonomy unchanged.
- [ ] The opt-in live smoke completes one page for UID 23191782 into a temporary archive
  root with real normalized rows and an advanced cursor — or records an explicit, cooled-down
  upstream blocker with evidence.
- [ ] Offline suites remain green (baseline: 865 passed, 2 skipped), including the AST
  import-boundary test and the no-leak scans.
- [ ] `docs/metadata-storage.md`, README, and `.env.example` describe the backend, the
  proxy knob, and the live-smoke expectations accurately.
- [ ] `git diff --check` is clean.

## Prepare → Execute Handoff

The diagnosis above is the Prepare input: evidence was produced live on 2026-09-11
(§Problem). Execute Task 1 → Task 2 → Task 3 → Task 4 (serial). After all tasks: SDD branch
review package, mandatory QC tri-review (N=3), mandatory QA gate (which owns the live
re-run), then merge to `main` via PR.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260911-live-metadata-path-fix/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`
- Blocking result: pending
- Residual findings: pending

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance (owns the bounded live smoke re-run)
- Evidence: pending

## Sign-off

- Product intent: pending product-manager review
- Architecture: pending architect review
- Writing/corpus hygiene: pending writing-specialist review
- PM lock: locked (PM, 2026-09-11; Prepare input = live diagnosis §Problem)
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every defect (D1/D2/D3) maps to a task and an acceptance criterion.
2. No task requires changing DTOs, the ingestor, the repository, or the schema.
3. The pinned spec deviation is explicit and annotated, not silent.
4. The live verification is bounded and has an honest blocker path.
5. No new credential surface, retry storm, or risk-control evasion is introduced.

## Evidence Index

- Iteration that shipped the stack:
  `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/delivery-compass.md`
- Pinned gateway spec (transport clause superseded):
  `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`
- Knowledge: `.mstar/knowledge/architecture-patterns/normalized-metadata-stack.md`
- Live diagnosis artifacts: `/tmp/live-*` archive roots from the 2026-09-11 session
  (failure evidence); the corrected-shape success is recorded in this plan's §Problem.

## Status Transition

Starts `Todo`; enters `InProgress` once the feature branch exists; `InReview` after
implementation; `Done` only by `project-manager`/`qa-engineer` after QC and the mandatory
QA gate, then merged to `main` by PR.

## End

The gateway stays the only module that knows the third-party transport; everything below it
keeps the contract it already has.
