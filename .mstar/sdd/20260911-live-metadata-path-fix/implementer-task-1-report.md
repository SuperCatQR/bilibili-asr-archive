# Task 1 Report — Declare the HTTP backend and prove the packaging contract

**Plan:** `20260911-live-metadata-path-fix`
**Working branch:** `fix/20260911-live-metadata-path-fix` (worktree `.worktrees/20260911-live-metadata-path-fix`)
**Commit:** `cc56e46` — `fix(deps): declare curl_cffi as the runtime HTTP backend` (no push; `main` untouched)
**Status:** DONE

---

## Implemented

Defect D1: `bilibili-api-python==17.4.2` publishes **no** HTTP client in `Requires-Dist`
and no extra carrying one, so a fresh install raises
`ArgsException("尚未安装第三方请求库或未注册自定义第三方请求库")` on every request. The pin is
spec-locked, so the application must declare the backend itself.

1. **Declaration** — `bilibili-asr-archive/pyproject.toml`: added `"curl_cffi>=0.16"` to
   `[project].dependencies` (one added line; no other dependency touched, pin retained).
   Floor `>=0.16` matches the transport generation verified live in the diagnosis (0.16.3);
   exact reproducibility comes from the lockfile, which is uv's job.
2. **Lockfile** — `bilibili-asr-archive/uv.lock` regenerated with `/root/.local/bin/uv lock`
   (`Resolved 99 packages … Added curl-cffi v0.16.3`). Diff is **purely additive**
   (111 insertions, 1 deletion across the whole commit; 35 insertions, 0 deletions in the lock):
   the `bili-asr` dependency row, the `requires-dist` row (`specifier = ">=0.16"`), and one new
   `[[package]] curl-cffi 0.16.3` block. Its two dependencies (`certifi`, `cffi`) were already
   locked, so no other package block moved or was re-pinned.
3. **Offline contract test** — `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`:
   `test_http_backend_declared_and_absent_from_pinned_package_requirements` asserts both sides
   of the packaging contract, with no network and no live call:
   - `[project].dependencies` still declares the backend (parsed with `tomllib`, requirement
     names canonicalised with `packaging.requirements.Requirement` +
     `packaging.utils.canonicalize_name`, so `curl_cffi` ≡ `curl-cffi`);
   - the installed pinned distribution's `Requires-Dist` carries **no** HTTP client
     (`curl_cffi` / `httpx` / `aiohttp`) — i.e. the declaration is load-bearing, not transitive;
   - the docstring records the pinned-package rationale (the `ArgsException` failure mode and
     why no version bump may paper over it).

New names introduced (checked with the `naming-analyzer` skill and against this file's
conventions): `PINNED_PACKAGE_DISTRIBUTION_NAME`, `HTTP_BACKEND_CANONICAL_NAME`,
`PACKAGE_HTTP_CLIENT_CANONICAL_NAMES`, and the test function above. The `CANONICAL` suffix is
deliberate: it says the value is the PEP 503 form, removing the `curl_cffi`/`curl-cffi`
ambiguity ("见名之意").

## Tests (TDD triple)

Test file: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**RED — before the `pyproject.toml` change** (test written first):

```
$ cd bilibili-asr-archive && <venv>/python -m pytest tests/test_bilibili_api_gateway.py -v -k http_backend
>       assert HTTP_BACKEND_CANONICAL_NAME in declared_names, (
E       AssertionError: the runtime HTTP backend must stay declared in [project].dependencies (curl-cffi missing)
E       assert 'curl-cffi' in {'bilibili-api-python', 'requests'}
tests/test_bilibili_api_gateway.py:708: AssertionError
========================= 1 failed, 105 deselected in 0.15s =========================
```

**GREEN — focused file, after the declaration + `uv lock`:**

```
$ cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v
tests/test_bilibili_api_gateway.py::test_http_backend_declared_and_absent_from_pinned_package_requirements PASSED
…
======================== 105 passed, 1 skipped in 0.43s ========================
```

Focused baseline before this task was `104 passed, 1 skipped` → **+1 test, nothing else moved**
(the skip is the opt-in live smoke).

**Full offline suite:**

```
$ cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
866 passed, 2 skipped in 60.96s (0:01:00)
```

Plan baseline was `865 passed, 2 skipped` → exactly the one added test; no regression.

**Non-vacuous guard check** (the upstream-absence half really discriminates):

```
bilibili-api-python ∩ clients = []            # pinned package declares none
curl_cffi (declares httpx under an extra) ∩ clients = ['httpx']
guard trips on the control distribution: True
```

`importlib.metadata.distribution("bilibili-api-python")`: `Provides-Extra: None`, 12
`Requires-Dist` entries, none of them an HTTP client — matches the docstring's rationale.

**Lock reproducibility:**

```
$ uv lock --check          → exit 0 (no-op)
$ uv lock                  → Resolved 99 packages in 1.73s / Added curl-cffi v0.16.3
$ sha256 before == after   → 4cf305d699a386e10302d84cc3aa45de24a28b96c6e094bf1f44f690e5d3da32 (identical)
$ uv lock --check (post-commit) → exit 0
```

## Files changed

| File | Change |
|---|---|
| `bilibili-asr-archive/pyproject.toml` | +1 line: `"curl_cffi>=0.16"` in `[project].dependencies` |
| `bilibili-asr-archive/uv.lock` | +35 lines, 0 deletions (curl-cffi 0.16.3 block + project dependency rows) |
| `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` | +76/-1: module docstring note, 2 stdlib + 2 `packaging` imports, 3 constants, 1 contract test |

`git status` clean after the commit; `git diff --check` clean; nothing outside the three
declared files was touched (gateway adapter, config, DTOs, ingestor, repository, CLI, docs and
`.env.example` are untouched — Tasks 2–4 own them).

## Self-review notes

- **Scope guard honoured.** Only the three briefed files changed. No plan/snapshot/status/compass
  or spec edit; the only harness file written is this report. No push, no `main` mutation.
- **No install performed** (per instruction): `uv lock` only. So the "fresh install can import an
  HTTP backend" criterion is evidenced by the declaration plus the lock entry
  (`curl-cffi 0.16.3`, wheels hashed) and a reproducible `uv lock --check` no-op — **not** by an
  executed `uv sync`. The `curl_cffi 0.16.3` already present in the control venv is the
  diagnosis install and is *not* claimed as delivery evidence.
- **Loud-fail, not silent skip**, when the pinned distribution is absent: mirrors the repo's
  existing Plan-2 live-smoke precedent (`test_live_metadata_smoke.py::_pinned_package_version`),
  and the module docstring was amended with one sentence so its
  "the real package is never needed" claim stays truthful.
- **`packaging` reused, not reimplemented**: it is already a declared `dev` dependency of this
  project, and it parses requirement strings (extras, markers) correctly — no hand-rolled name
  parser was added.
- **No YAGNI drift**: the test covers the two-sided contract the brief specifies. The lockfile is
  verified by command evidence (`uv lock --check` + byte-identical re-lock) rather than by a
  second test that would couple the suite to `uv.lock`'s revision format.
- **Deliberate non-assertion:** the test does not assert that `curl_cffi` is importable in the
  current interpreter — that would couple an offline packaging test to whether a developer has
  run `uv sync`, and the lockfile is the real guarantee.
- **Line lengths** in the added code (max 100) stay inside this file's existing envelope
  (max 103 before the change).
- **Branch base (informational):** the worktree sits on `25a11fe` (last product commit) while
  local `main` has one further **harness-only** commit `c29a87a` ("chore(plan): open
  20260911-live-metadata-path-fix"); the review diff basis is therefore product-only.
- **Handoff to Task 2:** `curl_cffi` is now declared, so the gateway can call
  `request_settings.set_proxy(...)` against the `CurlCFFIClient` the package auto-selects. The
  D2 behaviour observed in diagnosis is unchanged by this task (the package still builds
  `proxies={"all": ""}` by default).

## Status

DONE — declaration landed, lockfile additive and reproducible, contract pinned by an offline
test with red/green evidence, focused file `105 passed, 1 skipped`, full suite
`866 passed, 2 skipped`, `uv lock --check` exit 0, committed as `cc56e46`.
