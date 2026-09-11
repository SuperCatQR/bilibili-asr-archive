# Fix-2 implementer report — QC tri actionable findings (tests + docs wave)

- **Status: DONE** — all 9 assigned findings fixed offline; behaviour-free (docs, comments, tests only: no
  product logic, no constant, no assertion loosened). Targeted suite `143 passed, 2 skipped`; full offline
  suite **`903 passed, 2 skipped`** (baseline `894 passed, 2 skipped`; +9 new tests = 6 anonymous-arm
  parameters + 3 parity/signature tests).
- Plan: `.mstar/plans/20260911-live-metadata-path-fix.md` (fix round 2 after the QC tri)
- Working branch: `fix/20260911-live-metadata-path-fix` (dedicated worktree
  `.worktrees/20260911-live-metadata-path-fix`), commit **`a898fdf`**
  `test(metadata): pin the seam mirrors, anonymous codes, and the pin version` (parent `5667844` = fix wave 1)
- No push, no `main` mutation (`main` still at `c29a87a`), no other branch touched, working tree clean.
  No subagent dispatched (delegation forbidden). The only harness file written is this report; no plan /
  snapshot / status / compass / spec / knowledge edit.
- No live network run: `BILI_LIVE_SMOKE` was verified **unset** in every run (`BILI_LIVE_SMOKE=[unset]`
  printed before the targeted run), the two live tests stayed `SKIPPED`, no credential value was read,
  echoed, or written; no `--sessdata` flag was ever passed.
- Interpreter (as instructed): `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`,
  cwd = the worktree package root (`conftest.py` puts the worktree `src/` on `sys.path`).

## 1. Implemented — per-finding disposition

### 1. QC2 F-001 — live-smoke anonymous arm accepted *any* bounded code — FIXED (code + 6 offline pins)

- `tests/test_live_metadata_smoke.py:61-68` — new `ANONYMOUS_BOUNDED_ERROR_CODES = frozenset({"rate_limited", "response_error"})`
  with the docstring naming `README.md` / `docs/metadata-storage.md` as the source of the two codes.
- `tests/test_live_metadata_smoke.py:293-310` — new `_assert_anonymous_error_code_is_documented(error_code)`:
  a one-line set check that calls `pytest.fail(...)` for any code outside the set.
- `tests/test_live_metadata_smoke.py:370-373` — the live arm now calls the guard **before** `pytest.skip(...)`,
  so only the two documented codes take the reasoned-skip path; every other bounded code now fails loudly
  (including with no credential in the environment). The credentialed `pytest.fail` branch is unchanged.
- `tests/test_live_metadata_smoke.py:24-33` — module docstring updated to state the restricted skip path and
  that any other bounded code (e.g. `transport_error` from a dead proxy) fails loudly, credential or not.
- Pins (offline, no network):
  - `:506-524` — the existing fake-seam rehearsal gained **branch four**: `FakeNetworkException(503, ...)`
    through the real CLI → exit 2 → `_assert_bounded_failure_rows(...) == "transport_error"` → the anonymous
    arm must reject that code (`pytest.raises(pytest.fail.Exception)`). This is the seam-level pin.
  - `:490-495` — branch three's positive control: the `-400` rejection the real CLI composition produces is
    `response_error`, which the arm accepts.
  - `:528-551` — `test_anonymous_arm_accepts_the_documented_bounded_codes[rate_limited|response_error]` and
    `test_anonymous_arm_fails_loudly_on_every_undocumented_code[transport_error|not_found|shape_error|unknown_failure]`.
    The accept-side parameters are **literals**, deliberately not derived from the constant (see §4).
- Docs/code agreement completed: `docs/metadata-storage.md:231-233` and `README.md:603` now also say that any
  other bounded code fails the smoke loudly.

### 2. QC2 F-002 — `.env.example` promised `response_error` alone — FIXED

- `.env.example:14-15` — the credential line now reads: anonymous metadata collection intercepted by upstream
  risk control ends with the bounded `rate_limited`; other upstream failures are the bounded `response_error`;
  wording aligned with `README` / `docs/metadata-storage.md`. Comment only, no variable change.

### 3. QC2 F-003 — page-size bound undocumented — FIXED (docs only, **no runtime validation added**)

- `docs/metadata-storage.md:115-127` — new `### Page size` section: adapter + protocol default **30**, shipped
  `PAGE_SIZE = 30` (also the pinned package's own documented `ps`); larger values are **not** guaranteed
  (`ps=30`/`ps=50` → `code=0`; `ps=100` → HTTP 412 on probes, JSON `-400` on production runs); the adapter
  forwards an explicit override unchanged (neither clamps nor rejects it), so an over-large override surfaces
  as the upstream bounded code rather than a caller error; no CLI flag exists.
- `README.md:507-515` — the "Default page bound" bullet gained the same bound in one sentence (30 is the
  upstream-accepted default; larger sizes are not guaranteed; an explicit programmatic override is forwarded,
  not clamped/rejected; no CLI flag).
- No code change: `_require_positive_argument(page_size, ...)` still only enforces `>= 1` as the plan requires.

### 4. QC2 F-004 — fake endpoint mirror never checked against the pin — FIXED (3 offline parity tests)

- `tests/fixtures/fake_bilibili_gateway.py:61-67` — the mirror's docstring now states the parity test exists
  (the mirror is no longer taken on trust).
- `tests/fixtures/fake_bilibili_gateway.py:85-90` — new `MIRRORED_ENDPOINT_FIELDS = ("url", "method", "verify", "wbi")`
  (exported in `__all__`) naming the fields the adapter takes from the description, with `dm` the one it overrides.
- `tests/test_bilibili_api_gateway.py:119-186` — import-time probes + `_require_installed(...)`:
  `_probe_installed_pinned_endpoint()` reads `bilibili_api.user.API["info"]["video"]` **once at module import**,
  before any seam fixture can put the fake on `sys.modules` (a lazy import inside a seam test would read the
  fake and compare the mirror against itself); a failed probe returns a reason string that
  `_require_installed` turns into `pytest.fail` with install guidance (the packaging-test precedent).
- `tests/test_bilibili_api_gateway.py:655-685` — `test_fake_endpoint_mirror_matches_the_installed_pinned_description`:
  the mirror equals the installed pin on `url`/`method`/`verify`/`wbi`, `dm` is mirrored literally as `True` on
  both sides, and the mirrored `params` name set equals the pin's.
- `tests/test_bilibili_api_gateway.py:688-714` — `test_adapter_overrides_only_dm_of_the_installed_pinned_endpoint`:
  scripts the seam with the **pin's own** values and runs the real adapter; the issued request reproduces every
  pin transport field and differs only in `dm` (`False`). Deterministic, offline, fails loudly when the pin is absent.

### 5. QC1 F-002 / QC2 F-008 / QC3 S-00x — stale import-set test docstring — FIXED

- `tests/test_bilibili_api_gateway.py:1440-1448` — `test_gateway_imports_stay_on_metadata_surface`'s docstring
  (was "The adapter imports only Credential, User, Video, and exceptions.") now names the set the assertion
  enforces: `Credential` + the `request_settings`/`user` modules from the package root, the WBI-signed
  `utils.network.Api`, `video.Video`, and the five exception names, plus the explicit note that `User` is not
  imported (no `user.User` delegate; the page call goes through the `user` module's description and the package
  `Api`). Prose only; the assertion (`imports == ALLOWED_PACKAGE_IMPORTS`) is untouched.

### 6. QC1 F-005 / QC3 S-006(a) — fake `set_proxy` more permissive than the real method — FIXED (+ parity pin)

- `tests/fixtures/fake_bilibili_gateway.py:307-316` — `def set_proxy(proxy: str = "")` → `def set_proxy(proxy: str)`,
  matching the pin's `RequestSettings.set_proxy(self, proxy: str)` (verified in the installed pin:
  `utils/network.py:301-308`, no default), with the docstring recording why the double must not add one.
  Nothing in the tree calls it without an argument (grep: only the adapter's `set_proxy(self.resolved_proxy)`),
  so the change is offline-neutral — proven by the green suites.
- `tests/test_bilibili_api_gateway.py:717-748` — `test_fake_request_settings_double_is_no_more_permissive_than_the_pin`
  compares the mirrored `set_proxy`/`get_proxy` parameter name/kind/default triples with the pin's bound methods
  (probe `:147-172`). Small, disclosed scope addition beyond the brief's enumerated pins: it
  converts "aligned by hand" into a parity assertion, in the same pattern as F-004.

### 7. QC1 F-006 / QC2 F-005 — no documented way to force direct access — FIXED (docs only)

- `docs/metadata-storage.md:149-158` — two troubleshooting consequences: the resolved value goes to the
  package's **process-global** request settings (effective for every gateway in the process, not only the
  instance that resolved it), and a blank value counts as *unset*, so `BILI_HTTP_PROXY=""` cannot override a
  host-level `HTTPS_PROXY`/`ALL_PROXY`; forcing direct access means unsetting all five variables for the process
  (no in-app switch).
- `README.md:539-544` — one-line pointer with the same content.
- Both claims were independently re-verified against the installed pin (`utils/network.py:236-241` module-global
  `session_pool`/`lazy_settings`; `:282-290` `set()` propagating into every pooled session) and against the
  shipped CLI (single construction site `src/bili_asr/cli.py:571`, `BilibiliApiGateway(sessdata=config.sessdata)`
  — no proxy flag, no force-direct switch). No code change (the package-global behaviour is a PM-accepted item).

### 8. QC3 S-001 — docs understated the achieved live result — FIXED (count-only, dated)

- `docs/metadata-storage.md:253-258` — new bullet **"Achieved on 2026-09-11 (same day, after the page-size fix)"**:
  CLI exit 0, one collected page, `outcome=limited videos=30 parts=33 discoveries=30`, `observed_total=1691`,
  cursor advanced to `next_page=2` with state `limited`; explicitly count-only (no credential, no proxy, no
  collected metadata value) and the run-to-run intermittency caveat retained.
- Figures independently re-read from the ledger/report (`progress.md:147-149`, `implementer-task-5-report.md:186,192-193`),
  not copied from the QC text.

### 9. QC3 S-005 — packaging test never asserted the pin — FIXED

- `tests/test_bilibili_api_gateway.py:1096-1100` — the HTTP-backend packaging test now asserts
  `pinned_distribution.version == PINNED_PACKAGE_VERSION` **before** reading `Requires-Dist`, so a drifted
  environment fails loudly instead of drawing the "the pin declares no HTTP client" conclusion from another
  release; docstring at `:1065-1067` records why.

### Accepted, not acted (per the Assignment)

Untouched, confirmed by `git diff --name-only`: `_resolve_w_webid`'s blanket `except Exception`; the token route
outside the seam's documented-call allow-list; `curl_cffi>=0.16` breadth; package-global proxy vs per-instance
`resolved_proxy` (documented in #7, no code change); live-smoke `part_count >= 1` as an upstream-composition
assumption; page-size remap for pre-existing cursors.

## 2. Tests — commands and output

All commands from `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix/bilibili-asr-archive`
with the control interpreter, on the committed tree (`a898fdf`), `BILI_LIVE_SMOKE` unset.

1. `$VENV/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_live_metadata_smoke.py -v`
   → **`143 passed, 2 skipped in 0.98s`**
   - both live tests are `SKIPPED` (`test_live_smoke_single_public_page_for_archive_owner`,
     `test_live_smoke_fetch_meta_one_page_lands_normalized_rows`) — the smoke stayed off;
   - new: `test_fake_endpoint_mirror_matches_the_installed_pinned_description`,
     `test_adapter_overrides_only_dm_of_the_installed_pinned_endpoint`,
     `test_fake_request_settings_double_is_no_more_permissive_than_the_pin`,
     `test_anonymous_arm_accepts_the_documented_bounded_codes[rate_limited|response_error]`,
     `test_anonymous_arm_fails_loudly_on_every_undocumented_code[transport_error|not_found|shape_error|unknown_failure]`.
2. `$VENV/bin/python -m pytest -q` → **`903 passed, 2 skipped in 61.77s`**
   (baseline measured on the same tree before any edit: `894 passed, 2 skipped in 46.71s`; delta `+9` = 6 + 3 new tests).
3. `git diff --check` → clean; `git show --check HEAD` → clean; `git status --short` → clean tree on
   `fix/20260911-live-metadata-path-fix`.

### Non-vacuity evidence (mutation probes, run on throwaway copies under `/tmp/nv/…`; the worktree was never mutated)

| Guard | Mutation applied in the copy | Result |
|---|---|---|
| Anonymous code set check (§1.1) | `if error_code not in ANONYMOUS_BOUNDED_ERROR_CODES:` → `if not error_code:` (the pre-fix "any bounded code" behaviour) | **5 failed** — rehearsal branch four (`DID NOT RAISE Failed`, `test_live_metadata_smoke.py:522`) + all 4 `fails_loudly_on_every_undocumented_code` params (`:549`); the 2 accept params still pass |
| Anonymous set vs docs, other direction | `ANONYMOUS_BOUNDED_ERROR_CODES` → `frozenset({"rate_limited"})` | **1 failed** — `test_anonymous_arm_accepts_the_documented_bounded_codes[response_error]` (`assert 'response_error' in frozenset({'rate_limited'})`) |
| Endpoint mirror parity — `url` (§1.4) | mirror `"url"` → `https://drifted.example.invalid/...` | **1 failed** — `test_fake_endpoint_mirror_matches_the_installed_pinned_description` (`:649`) |
| Endpoint mirror parity — `verify` | mirror `"verify": False` → `True` | **1 failed** — same test (`:649`) |
| Endpoint mirror parity — `dm` | mirror `"dm": True` → `False` | **1 failed** — same test (`:654`) |
| "`dm` is the only field the adapter overrides" | adapter `verify=_USER_VIDEO_PAGE_ENDPOINT["verify"]` → `verify=True` (an extra override) | **1 failed** — `test_adapter_overrides_only_dm_of_the_installed_pinned_endpoint` (`:682`) |
| same | adapter `dm=False` → `dm=True` (drops the override) | **2 failed** — `…overrides_only_dm…` (`:684`) + the pre-existing `test_user_video_page_request_takes_its_transport_from_the_package_endpoint` |
| Pin-version assertion (§1.9) | `PINNED_PACKAGE_VERSION = "17.4.2"` → `"17.4.1"` (simulated environment drift) | **1 failed** — `assert '17.4.1' == '17.4.2'` at `test_bilibili_api_gateway.py:1033` |
| same, proving the assertion is the load-bearing part | same drift **and** the new `assert pinned_distribution.version …` block removed (= the pre-fix test) | **1 passed** — the drift is invisible without the new assertion |
| `set_proxy` signature parity (§1.6) | mirror `def set_proxy(proxy: str)` → `def set_proxy(proxy: str = "")` (the re-introduced default) | **1 failed** — `test_fake_request_settings_double_is_no_more_permissive_than_the_pin` (`:745`), while the pre-existing `test_fake_seam_exposes_only_documented_metadata_surface` **still passes** under the same mutation (i.e. the new test is the only guard) |

## 3. Files changed (commit `a898fdf`, 6 files, +340/−16)

| File | Change |
|---|---|
| `bilibili-asr-archive/tests/test_live_metadata_smoke.py` | +101/−6 — anonymous code set + guard, live-arm wiring, module docstring, rehearsal branch four + positive control, 6 offline pins |
| `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` | +184/−2 — import-time pin probes/helpers, 3 parity tests, pin-version assertion, import-set docstring |
| `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` | +23/−2 — `MIRRORED_ENDPOINT_FIELDS`, strict `set_proxy` signature, docstring, `__all__` |
| `bilibili-asr-archive/docs/metadata-storage.md` | +34/−2 — page-size section, proxy consequences/force-direct, anonymous-arm clause, dated live result |
| `bilibili-asr-archive/README.md` | +16/−5 — page-size bound, process-global proxy/force-direct, anonymous-arm clause |
| `.env.example` | +3/−1 — anonymous outcome codes aligned with the docs |

## 4. Self-review notes

- **Surgical scope.** Every edit traces to one of the 9 assigned findings. No product file is touched
  (`git diff --name-only` = the 6 files above; `src/`, `pyproject.toml`, and `uv.lock` untouched). No assertion
  was loosened; the only restructure of an existing assertion is in the rehearsal branch three
  (`assert _assert_bounded_failure_rows(...) == ("response_error")` → `error_code = …; assert error_code == "response_error"`),
  which is equivalent and was disclosed here.
- **Deviations disclosed (2):**
  1. **Extra test beyond the brief's enumerated pins** — `test_fake_request_settings_double_is_no_more_permissive_than_the_pin`
     (§1.6). Justification: finding 6 asked only for the fixture alignment, but "the double is more permissive than
     the dependency" is precisely the drift class finding 4 pins for the endpoint mirror; the added assertion is
     offline, deterministic, and shares the same installed-pin probe. The probe shows the pre-existing seam test
     does *not* catch the re-introduced default.
  2. **Strength correction found by my own probe** — the accept-side parametrization was first written as
     `sorted(ANONYMOUS_BOUNDED_ERROR_CODES)`; probe A2 showed that narrowing the constant then shrinks the test
     instead of failing it, so it now uses the literal documented codes plus `assert error_code in ANONYMOUS_BOUNDED_ERROR_CODES`
     (`tests/test_live_metadata_smoke.py:528-539`). Recorded because it is the one place where a first version of
     this wave was weaker than it looked.
- **Doc claims independently verified, not copied from the QC seats:** the two anonymous codes against the
  adapter's mapping (`_RATE_LIMITED_*` → `rate_limited`; other `ResponseCodeException`/`ApiException` →
  `response_error`); the process-global proxy against the installed pin's source (`utils/network.py:236-241,
  282-290`) and the single CLI construction site (`cli.py:571`, no proxy flag); the live figures against
  `progress.md:147-149` and `implementer-task-5-report.md:186,192-193`; the page-size bound against the plan's D4
  evidence and the pin's own `params: {"ps": "const int: 30"}` (read directly from the installed distribution).
- **No runtime validation added** (F-003 explicitly forbids it): `_require_positive_argument` is untouched; the
  bound is documented only.
- **Determinism / no network.** The new parity tests read the installed distribution's data/signatures at module
  import time; nothing opens a socket. They fail loudly with install guidance when the pin is absent (packaging
  precedent), and the reason string distinguishes an absent distribution from a renamed key or unexpected shape.
- **Count-only hygiene.** The new dated docs bullet carries no credential, proxy, bvid, title, or payload — only
  the six counts/state fields already published in `progress.md`; nothing was added to any persisted surface.
- **Left for the PM (not in this wave's brief, untouched):** QC2 F-006 (pinned-spec correction riding the
  plan-Done chore commit), QC3 S-003 (`curl_cffi` specifier — listed accepted), S-004 (transport-selection
  assertion + the "arrive through the dependency closure" wording of `PACKAGE_HTTP_CLIENT_CANONICAL_NAMES`),
  S-007 (`w_webid` degradation signal — listed accepted), S-008 (cursor remap note — listed accepted),
  S-009 (`part_count >= 1` — listed accepted), S-010 (plan `## Status` block drift vs the snapshot). QC2 F-003's
  optional "related nit" about `tests/test_bilibili_api_gateway.py:313-326` naming `page_size=100` in the
  invalid-argument parametrization was **not** touched: the assignment scoped F-003 to documentation, and the case
  is inert (it fails on `mid`/`page_number` first and pins `calls == []`).
- **Style.** No reformatting; long lines (>88 chars) match the surrounding file style (the repo has 284 such lines
  in `src/` alone); no new dependency, no new harness artifact.
