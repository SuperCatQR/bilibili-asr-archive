# Task 2 report — Resolve and apply proxy configuration in the gateway

**Status:** DONE_WITH_CONCERNS

The single concern is **procedural, not technical**: the change also touches
`bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` (the offline package
seam), which the Assignment's scope list did not name. It is unavoidable and minimal
(+30/−8); see §Scope disclosure for the proof and the rejected alternatives. Everything
else is exactly the assigned surface, verified green.

- Working branch: `fix/20260911-live-metadata-path-fix` (worktree
  `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix`)
- Implementer commit: **`0a2e2f5`** `fix(gateway): resolve and apply the proxy for the
  pinned package` (BASE `cc56e46`, Task 1)
- Branch probe at start: `pwd` = control root, worktree `HEAD` =
  `fix/20260911-live-metadata-path-fix` → matched the Assignment, so no BLOCKED.
- Diff basis check: `git diff --check cc56e46..HEAD` exit 0; working tree clean.

## Implemented

### 1. `src/bili_asr/config.py` — pure proxy configuration (third-party-free)

- `PROXY_ENV_VAR = "BILI_HTTP_PROXY"` — the documented operator knob (parallels the
  existing `SESSDATA_ENV_VAR`).
- `PROXY_ENV_VARS` — the complete **locked precedence chain**, in order:
  `BILI_HTTP_PROXY`, `HTTPS_PROXY`, `https_proxy`, `ALL_PROXY`, `all_proxy`.
- `resolve_proxy(argument_value, environ) -> str | None` — pure helper, no
  `bilibili_api` import, no I/O:
  - argument first, then `PROXY_ENV_VARS` in declared order;
  - a blank/whitespace-only value counts as **unset** and never blocks the next level
    (so an empty `BILI_HTTP_PROXY` cannot shadow a real `HTTPS_PROXY`);
  - the returned value is stripped of surrounding whitespace;
  - `None` when nothing resolves.
- Module docstring and `__all__` updated.

### 2. `src/bili_asr/sources/bilibili_api_gateway.py` — resolve and apply once

- `BilibiliApiGateway(sessdata=None, proxy=None)` (was `sessdata` only); records
  `self.resolved_proxy`.
- At construction: `self.resolved_proxy = resolve_proxy(proxy, os.environ)`; **only when
  it is not `None`** → `request_settings.set_proxy(self.resolved_proxy)`. Nothing
  resolved ⇒ the library's own default is left completely untouched.
- Import surface grows by exactly one name: `from bilibili_api import Credential,
  request_settings` (the AST import-boundary test still proves the gateway is the only
  module importing `bilibili_api`, and `config.py` stays third-party-free).

**Surface choice (documented in the code docstring): `request_settings.set_proxy`.**
Verified against the installed pin `bilibili-api-python==17.4.2`:

- `bilibili_api/clients/CurlCFFIClient.py:52-57` builds
  `AsyncSession(headers=..., proxies={"all": proxy}, ..., trust_env=trust_env)` and
  `bilibili_api/utils/network.py:1079-1083` fills `proxy` from `request_settings.get(
  "proxy")` in `get_client()`. That is D2 exactly: the explicit `{"all": ""}` entry
  defeats `trust_env`. `set_proxy` is the setting the client reads at session build.
- `Credential(proxy=...)` also exists (network.py:1161-1194) but is deliberately **not**
  used: `Api` swaps the same global setting around every credentialed request
  (network.py:2331-2349) instead of configuring it, which is not request-isolation-safe
  under concurrency. Neither surface is set twice.
- `RequestSettings.set` also queues the value in `lazy_settings`, so `get_client()`
  applies it via `session.set_proxy(...)` on the next request — construction-time
  application is therefore effective even if a session already existed in-process, and
  it always precedes this adapter's first call.

### 3. Tests — `tests/test_bilibili_api_gateway.py` (+19 tests)

Helper level (`resolve_proxy`): each of the 5 chain levels resolves alone
(parametrized); the full precedence ladder proven level-by-level by clearing the higher
levels one at a time; argument outranks the whole chain; blank/whitespace (`""`, `"   "`,
`"\t\n"`) = unset and never shadows a lower level; whitespace stripping; nothing set →
`None`, and `HTTP_PROXY` deliberately not consulted (the two upstream endpoints are
HTTPS).

Gateway level (over the offline seam, no network):

- applied **exactly once, at construction, before the first call**
  (`applied_proxies == [value]` while `calls == []`, still one entry after a real page
  call);
- resolved from `BILI_HTTP_PROXY` when no argument; argument outranks the environment;
  a blank `BILI_HTTP_PROXY` falls through to `HTTPS_PROXY`;
- **no proxy default**: `resolved_proxy is None` and `applied_proxies == []`, before and
  after a page call (library setting untouched);
- no-leak: the proxy and the credential stay out of DTO `repr`/`str`, the adapter's
  debug `repr`, mapped exception `str`/`repr`, `IngestionResult` renders, and the full
  persisted-row blob after a real ingestor+repository run.

`ALLOWED_PACKAGE_IMPORTS` and the seam-surface assertion were updated for the new
`request_settings` module; the seam's public surface is asserted as
`["get_proxy", "set_proxy"]`.

## Scope disclosure (the one concern)

Changed files vs `cc56e46` (+324/−15):

```
 bilibili-asr-archive/src/bili_asr/config.py                   |  53 ++++-
 bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py |  25 ++-
 bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py  |  30 ++-
 bilibili-asr-archive/tests/test_bilibili_api_gateway.py       | 231 +++++++++++++++-
```

`tests/fixtures/fake_bilibili_gateway.py` (out of the literal scope list) gained:
`FakeUpstreamScript.applied_proxies`, a `bilibili_api.request_settings` mirror module
with `set_proxy` (records the value) / `get_proxy`, its registration in
`build_fake_package`'s module map, and the fixture module docstring. None of these change
product behavior; all four lines exist so the fake mirrors the adapter's documented import
surface.

Why it is unavoidable: the Assignment's own Context directs "monkeypatch/stub
`set_proxy` **in the seam**", and the fake package must expose the adapter's documented
import surface or the adapter cannot import at all. Every alternative fails:

- `from bilibili_api import request_settings` with an unmodified fake ⇒
  `AttributeError` at adapter import;
- patching `sys.modules["bilibili_api"]` from inside `test_bilibili_api_gateway.py` only
  ⇒ leaves `test_metadata_ingest.py`, `test_metadata_cli.py`, and `test_metadata_e2e.py`
  broken, because they build the **real** adapter over the same shared seam fixture;
- a dynamic `importlib.import_module("bilibili_api.request_settings")` inside the gateway
  ⇒ would evade the AST import-surface test, which is exactly the kind of test-evasion a
  reviewer must reject;
- `Credential(proxy=...)` ⇒ still needs the fake `Credential` signature extended
  (a fixture change too), plus the concurrency downside above.

Undisclosed scope: none. DTOs, the `BilibiliGateway` protocol, the exception taxonomy,
the ingestor, the repository, `schema.sql`, `pyproject.toml`, `uv.lock`, the CLI
(`src/bili_asr/cli.py`) and `tests/test_metadata_cli.py` are untouched — the CLI still
constructs `BilibiliApiGateway(sessdata=config.sessdata)` and its display stays
presence-only, unchanged. No `--proxy` flag was added (out of scope for this task);
`BILI_HTTP_PROXY`/`HTTPS_PROXY` resolve inside the gateway, so the CLI needs no change.

## Tests (TDD triple)

Test files: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`,
`bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` (seam).

### Red (two stages, tests written first)

1. After adding the tests + seam, before any implementation:
   `python -m pytest tests/test_bilibili_api_gateway.py -q` →
   `ERROR collecting tests/test_bilibili_api_gateway.py ... ImportError: cannot import
   name 'PROXY_ENV_VAR' from 'bili_asr.config'` (no proxy surface existed).
2. After adding only the config constants/helper (gateway still untouched):
   `89 failed, 35 passed, 1 skipped`, first failure
   `TypeError: BilibiliApiGateway.__init__() got an unexpected keyword argument 'proxy'`
   — i.e. the D2 surface did not exist at all, and the new gateway tests asserted
   `applied_proxies`/`resolved_proxy` behavior that the old constructor could not produce.

### Green (exact command from the brief)

```
cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_cli.py -v
======================== 158 passed, 1 skipped in 2.34s ========================
```

(baseline before this task: `139 passed, 1 skipped`; all 19 new tests PASSED, e.g.
`test_gateway_applies_the_resolved_proxy_once_before_the_first_call PASSED`,
`test_gateway_leaves_the_package_setting_untouched_without_a_proxy PASSED`.)

### Full offline suite

```
cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
885 passed, 2 skipped in 49.56s
```

Baseline after Task 1 was `866 passed, 2 skipped` → +19 new tests, **0 regressions**,
0 new skips.

### Non-vacuity (mutation checks, each reverted with the file verified byte-identical)

| mutation | caught by |
|---|---|
| always call `set_proxy`, even with nothing resolved | `test_gateway_leaves_the_package_setting_untouched_without_a_proxy` (1 failed) |
| apply the proxy per request instead of once | `..._applies_the_resolved_proxy_once_before_the_first_call` + untouched test (2 failed) |
| reverse precedence (environment before argument) | `test_resolve_proxy_argument_outranks_the_whole_environment_chain` + `test_gateway_argument_outranks_the_environment` (2 failed) |
| drop blank/whitespace handling | 4 failed (blank, whitespace, gateway fall-through) |
| leak the proxy into a mapped error message | `test_gateway_proxy_stays_out_of_dtos_and_mapped_errors` (1 failed) |
| leak the proxy into a DTO field that gets persisted | `test_gateway_proxy_stays_out_of_persisted_rows` (+2) |

### Real-package verification (offline, no network)

All suite tests use the fake seam, so the import name and the actual application were
separately proven against the **real** pin via `PYTHONPATH=<worktree>/src`:

- `from bilibili_api import Credential, request_settings` works;
  `request_settings` is `bilibili_api.utils.network.RequestSettings` with
  `get_proxy`/`set_proxy` (and `Credential` does accept `proxy` — the unused option).
- nothing resolved (all five vars unset) → `resolved_proxy=None` and
  `request_settings.get_proxy()` stays `''`.
- `BILI_HTTP_PROXY=http://127.0.0.1:7890` (all others unset) → `resolved_proxy` and
  `request_settings.get_proxy()` both that value.
- ambient `HTTPS_PROXY` only → same value resolved and applied (proxied hosts need no
  extra configuration).
- **wire-level probe** (`get_client().get_wrapped_session()`, no request sent):

| case | `CurlCFFIClient` session |
|---|---|
| no proxy resolved | `proxies={'all': ''}, trust_env=True` (library default preserved) |
| `BILI_HTTP_PROXY` | `proxies={'all': 'http://127.0.0.1:7890'}, trust_env=True` |
| ambient `HTTPS_PROXY` | `proxies={'all': 'http://127.0.0.1:7890'}, trust_env=True` |

The middle/right rows are precisely the `{"all": ""}` entry that caused D2 being
replaced by the operator's proxy; the left row proves the no-proxy default is untouched.

## Self-review notes

- `git diff --check` (both working tree and `cc56e46..HEAD`): exit 0, no whitespace
  errors; no line in the diff exceeds the file's 88-column style.
- Leak paths re-checked by hand: the gateway has no logging, no `__repr__`, and no
  message construction that interpolates configuration; `resolved_proxy` is a plain
  attribute (configuration, not a credential) and never reaches a DTO, an exception
  `detail`, or a persisted row — proven by the two no-leak tests plus two leak
  mutations.
- Blank semantics decided from the locked wording ("empty/blank values are unset"):
  a blank value — argument **or** environment — falls through rather than acting as an
  explicit "no proxy". This differs from `resolve_sessdata`'s blank-flag rule, which is
  deliberate: `BILI_SESSDATA` has a `--sessdata ""` escape hatch on the CLI, while the
  proxy has no CLI surface in this task. Recorded in the docstring; no operator-visible
  path is affected.
- `naming-analyzer` run before introducing names (user preference 见名之意). Chosen:
  `PROXY_ENV_VAR` / `PROXY_ENV_VARS` (consistent with the existing `SESSDATA_ENV_VAR`,
  chain order stated in the docstring), `resolve_proxy(argument_value, environ)`
  (mirrors `resolve_sessdata(flag_value, environment_value)`), `resolved_proxy` (per
  brief), `applied_proxies` (records values, not call shapes, so it does not collide
  with the seam's `calls`). A first candidate name for the clearing test fixture,
  `no_proxy_environment`, was rejected because it collides visually with the unrelated
  `NO_PROXY` bypass-list variable; `empty_proxy_environment` is used instead.
- Surgical check: every hunk maps to the locked precedence, the apply-once rule, the
  no-proxy default, or a required test/seam assertion; no adjacent refactoring, no
  doc/CLI/config-field changes.
- Commit metadata: the first commit on this branch was authored with the ambient global
  identity; I amended it (metadata only — `git diff f62eded..HEAD` empty, same tree) so
  the plan branch carries the same implementer identity as Task 1
  (`fullstack-dev <fullstack-dev@mstar.local>`). No push; no other branch touched.
- Noticed, not fixed (no action needed, recorded for reviewers): `request_settings` is
  process-global, so two simultaneously live gateways with different proxies would
  overwrite each other. In this product exactly one gateway is constructed per process
  (`src/bili_asr/cli.py:571` is the only construction site), so the limitation is
  latent; containing it would need a library-side per-client setting.

## Not done here (owned elsewhere)

- Operator docs (`.env.example`, `docs/metadata-storage.md`, README) and the bounded live
  smoke belong to Task 4; `uv.lock`/`pyproject.toml` were Task 1. No live network call
  was made by this task.

## Evidence index

- Diff: `git diff cc56e46..HEAD` (worktree
  `.worktrees/20260911-live-metadata-path-fix`, package root `bilibili-asr-archive/`)
- Adapter: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
  (`__init__`, lines ~247-275)
- Config: `bilibili-asr-archive/src/bili_asr/config.py` (`PROXY_ENV_VAR`,
  `PROXY_ENV_VARS`, `resolve_proxy`)
- Tests: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
  (section "proxy resolution and application")
- Seam: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Pin evidence: `.venv/lib/python3.12/site-packages/bilibili_api/clients/CurlCFFIClient.py:52-57`,
  `bilibili_api/utils/network.py:1079-1083`, `:2331-2349`
