# QA Report (Report-only) — `20260911-live-metadata-path-fix` (L4 acceptance gate)

- **Seat**: `qa-engineer` (L4, acceptance) · **Delegation**: forbidden · **QA gate**: mandatory
- **QA mode**: `acceptance-only` + the five QC-routed fresh-evidence items (`qc-consolidated.md` § Hand-off)
- **Review cwd**: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix`
- **Working branch**: `fix/20260911-live-metadata-path-fix` · **HEAD**: `a898fdf`
- **Review range / Diff basis**: `25a11fe..a898fdf` (7 commits)
- **Run at**: 2026-09-11 ≈08:52–08:56 UTC · **Verdict**: **Approve — recommend merge to `main`**
- **Findings cleanup**: `zero-residual` (register absent/empty; no new residual opened)

---

## 1. Scope tested

In scope: the QC hand-off list — (1) checkout alignment, (2) clean-install / lockfile proof,
(3) full offline suite at HEAD, (4) opt-in live smoke re-run, (5) `curl-cffi` lock/hash sanity — plus
(6) DoD mapping over the plan's 8 acceptance criteria, (7) residual check, (8) plan `## QA Gate Summary`.

Out of scope by assignment: business-code edits, commits/checkout/push, control-venv mutation, plan `Done`.

## 2. Checkout alignment (read-only probes, no mutations)

| Field | Assignment | Observed | Match |
|---|---|---|---|
| Review cwd | `…/.worktrees/20260911-live-metadata-path-fix` | same (`pwd`) | ✅ |
| Working branch | `fix/20260911-live-metadata-path-fix` | `fix/20260911-live-metadata-path-fix` | ✅ |
| HEAD | `a898fdf` | `a898fdfc138022dcacf9c24077f07826be9bfbc8` | ✅ |
| Commit count from branch cut | 7 | `git rev-list --count 25a11fe..HEAD` = 7 | ✅ |
| Tree state | clean | `git status --porcelain` empty (tracked **and** untracked/all) | ✅ |
| Diff basis | `25a11fe..a898fdf` | `git merge-base HEAD main` = `25a11fe` | ✅ |
| `plan_id` | `20260911-live-metadata-path-fix` | matches plan file, SDD dir, workflow snapshot row | ✅ |

Identical, text-for-text, to the metadata every QC seat verified (`qc-consolidated.md` header) — no re-baselining.

Note (not a mismatch): local `main` has advanced past the branch cut with four harness/plan-bookkeeping
commits (`c29a87a`, `c9f820c`, `94eaee9`, `0819b91`); `25a11fe` is confirmed an ancestor of `main`, and the
merge base with HEAD is exactly `25a11fe`, so the declared review range remains exact.

## 3. Fresh-run evidence (all produced at this gate)

### 3.1 Lockfile reproducibility + clean-install proof *(QC item 1, new)*

| Check | Result |
|---|---|
| `uv lock --check` (cwd `…/bilibili-asr-archive`) | **exit 0, no-op** — "Using CPython 3.12.13 / Resolved 99 packages in 4ms" |
| Scratch env `uv venv /tmp/qa-fresh-live-metadata-path-fix` + `UV_PROJECT_ENVIRONMENT=… uv sync --frozen --no-install-project` | **exit 0**, 24 packages installed from the lockfile only |
| Import from that scratch interpreter | `curl_cffi` **0.16.3** OK; `bilibili_api` **17.4.2** OK; `request_settings` proxy surface present; `bilibili_api.clients.CurlCFFIClient` present |
| Installed artefact architecture | `curl_cffi/_wrapper.abi3.so` = *ELF 64-bit LSB shared object, ARM aarch64* → host arch served by the locked wheel |
| Full fresh **project** install (copy of the HEAD tree in `/tmp`, `uv sync --frozen`) | exit 0 → `bili-asr 0.1.0`, `import bili_asr` resolves to the copied `src`, console script `bili-asr --help` works, `BilibiliApiGateway(sessdata=None, proxy=None)` |
| Control venv / worktree after both | untouched; `git status --porcelain` empty |

Scratch envs and the `/tmp` copy were deleted afterwards; nothing scratch was or could be committed.

### 3.2 Full offline suite at HEAD *(QC item 2, new)*

```
cd …/.worktrees/20260911-live-metadata-path-fix/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q -rs
→ 903 passed, 2 skipped in 51.51s   [exit 0]   (905 collected)
```

Matches the plan's post-fix-wave expectation exactly. The 2 skips are precisely the two opt-in live-smoke
gates (`tests/test_bilibili_api_gateway.py:1608`, `tests/test_live_metadata_smoke.py:329`) — no unexplained skips.

- **AST import-boundary test**: `test_only_the_gateway_module_imports_bilibili_api`,
  `test_gateway_imports_stay_on_metadata_surface` → both **PASSED** (explicit re-run: 2 passed).
- **No-leak scans**: `test_gateway_proxy_stays_out_of_dtos_and_mapped_errors`,
  `test_gateway_proxy_stays_out_of_persisted_rows`,
  `tests/test_metadata_ingest.py::test_no_leak_marker_scan_catches_contamination` → **PASSED**
  (explicit re-run: 3 passed); the CLI presence-only redaction tests are inside the 903.

### 3.3 Opt-in live smoke re-run *(QC item 3 — the plan's core acceptance, new)*

Run from the **worktree package dir** (so `tests/conftest.py:12`'s `sys.path.insert(0, …/src)` wins over the
control venv's editable install, which still resolves to pre-fix `main`), credential loaded only via
`set -a; source /root/workspace/bilibili-asr-archive/.env; set +a` (no `set -x`), `-s -v` on the first attempt:

```
BILI_HTTP_PROXY=http://127.0.0.1:7890 BILI_LIVE_SMOKE=1 <control-venv-python> -m pytest \
  tests/test_live_metadata_smoke.py -s -v
```

| Field | Observed |
|---|---|
| Exit code | **0** (`8 passed in 2.12s`) |
| Branch that ran | **credentialed happy path** — an operator credential was present (presence-only check), so the anonymous bounded-failure arm did **not** run |
| Evidence line (count-only) | `live smoke evidence: outcome=limited videos=30 parts=33 discoveries=30 page_rows=1 cursor_next_page=2 cursor_state=limited observed_total=1691` |
| Bounded blocker | **none** — no throttle, no retry needed (first attempt succeeded) |
| Credential hygiene | operator-credential occurrences in the captured run log: **0** (counted in-process; value never placed on a command line) |

**Provenance (this is branch code, not `main`):** with the same `sys.path` insert the test session uses,
`bili_asr` resolves to the worktree `src` and `bili_asr.services.metadata_ingest.PAGE_SIZE == 30`, while the
control/main tree still ships `100`. A page of **30** videos with `exit 0` is unreachable through the pre-fix
path (the plan records `ps=100` → HTTP 412 / `-400`, and the pre-fix shape sent `dm=True`), so the observed
happy path is itself proof that the delivered call shape, page-size bound, proxy application and declared
transport all executed. The smoke's own assertions — exactly one page row, user/video/part/discovery join
integrity, cursor advanced past the committed page, no credential/`pssign`/`bilivideo.com` markers — all held.

### 3.4 Lockfile / wheel sanity *(QC item 4, new)*

`git diff 25a11fe a898fdf -- bilibili-asr-archive/uv.lock` → **35 insertions, 0 deletions**.
The entire delta is the new `curl-cffi` block plus its two dependency edges in the `bili-asr` package row
(`{ name = "curl-cffi" }`, specifier `>=0.16`).

| Check | Result |
|---|---|
| `curl-cffi` entry | `version = "0.16.3"`, `source = { registry = "https://pypi.org/simple" }` |
| Hashes | sdist carries `sha256:` + URL; **21/21** wheels carry `sha256:` hashes |
| Host architecture (aarch64) | `curl_cffi-0.16.3-cp310-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl` present (plus cp314t manylinux/musllinux aarch64 variants); the wheel actually used installed as ARM aarch64 |
| Removals | **0** removal lines → no previously locked package removed |
| Downgrades | none — the only added `name =` line is `curl-cffi`; no version line for any existing package changed |
| Other lockfiles in range | none (`git diff --name-only` shows a single `uv.lock`) |
| Lock totals | 99 packages; project deps `bilibili-api-python`, `curl-cffi`, `requests` |

### 3.5 Docs accuracy spot-check (supporting evidence for DoD 7)

Verified the operator-facing claims against the implementation and this gate's live run:
`README.md` (page size 30 / `curl_cffi` requirement / `BILI_HTTP_PROXY` + `HTTPS_PROXY` fallback / live-smoke
command and both outcomes), `docs/metadata-storage.md` (locked precedence, blank-counts-as-unset, explicit
override not clamped, both live outcomes), `.env.example` (`BILI_HTTP_PROXY`, commented, with example and
precedence). Cross-checked against `src/bili_asr/config.py:154-175` (`resolve_proxy`), `metadata_ingest.py:50`
(`PAGE_SIZE = 30`), `sources/models.py:102` (`page_size: int = 30`), `sources/bilibili_api_gateway.py:254-279`
(constructor + `resolved_proxy` + `set_proxy`), and the installed pin
(`bilibili_api/clients/CurlCFFIClient.py:55` `proxies={"all": proxy}`; `RequestSettings.set_proxy(proxy: str)`)
— all consistent. No contradicting statement found.

## 4. DoD mapping — plan § Acceptance / Done Criteria

| # | Acceptance criterion (plan) | Evidence | Source |
|---|---|---|---|
| 1 | `curl_cffi` declared; `uv lock --check` no-op; fresh install can import an HTTP backend | `pyproject.toml` deps; `test_http_backend_declared_and_absent_from_pinned_package_requirements` PASSED; **new**: `uv lock --check` exit 0 + scratch-env sync importing `curl_cffi 0.16.3` / `bilibili_api 17.4.2`; full fresh project install (`bili-asr 0.1.0`, console script) | reused (declaration + test) + **new (install proof)** |
| 2 | Proxy resolved/applied with locked precedence; unset leaves library untouched; no proxy/credential leak into output, logs or rows | 11 proxy tests in `tests/test_bilibili_api_gateway.py::test_resolve_proxy_*` / `test_gateway_*proxy*` (inside the 903); **new**: explicit green re-run of both no-leak tests + `test_no_leak_marker_scan_catches_contamination`; implementation read of `resolve_proxy` confirms argument → `BILI_HTTP_PROXY` → `HTTPS_PROXY`/`https_proxy` → `ALL_PROXY`/`all_proxy`, blank/whitespace = unset, no forced proxy when `None` | reused + **new (targeted re-run)** |
| 3 | Page call with `dm` disabled and `w_webid` present (non-empty preferred); bounded taxonomy unchanged | `test_user_video_page_request_prefers_the_package_access_id`, `…_falls_back_to_empty_w_webid_when_the_route_fails`, `…_resolves_the_access_id_once_per_user`, `…_per_user`, `test_adapter_overrides_only_dm_of_the_installed_pinned_endpoint`; **new**: live happy path returned a real page (only possible with `dm=False` + `w_webid` present) | reused + **new (live)** |
| 4 | Default page size 30 (upstream-accepted); explicit `page_size` override still flows through | `test_get_user_video_page_defaults_to_upstream_accepted_size`, `test_get_user_video_page_explicit_size_override_keeps_normalization`; `PAGE_SIZE = 30` in the shipped ingestor and `page_size: int = 30` in the protocol; **new**: live run collected exactly `videos=30` | reused + **new (live)** |
| 5 | Opt-in live smoke completes one page (real rows, advanced cursor) **or** records a cooled-down bounded blocker with evidence | **new**: QA live run, exit 0, `outcome=limited videos=30 parts=33 discoveries=30 page_rows=1 cursor_next_page=2 cursor_state=limited observed_total=1691`; no blocker, no retry | **new** |
| 6 | Offline suites green (**903 passed / 2 skipped**) incl. AST import-boundary test and no-leak scans | **new**: `pytest -q -rs` → 903 passed, 2 skipped, 51.51s, exit 0; boundary tests 2 passed; no-leak tests 3 passed | **new** |
| 7 | `docs/metadata-storage.md`, README, `.env.example` describe backend, proxy knob, live-smoke expectations accurately | **new**: claim-by-claim spot-check against source, the installed pin, and this gate's live run (§3.5) | **new** |
| 8 | `git diff --check` clean | **new**: `git diff --check 25a11fe a898fdf` → exit 0, no output | **new** |

All 8 criteria are satisfied with reproducible evidence attributable to `25a11fe..a898fdf`.

## 5. Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| Q-01 | Info | Host `.env` carries only the credential key; the proxy is not persisted there, so the documented per-shell `BILI_HTTP_PROXY` export is required for live runs. Docs state this explicitly. | No action |
| Q-02 | Info | `parts=33` for 30 videos — individual videos legitimately have varying part counts; the assertion is deliberately an aggregate `>= 1`, so this is expected, not a partial fetch. | No action |
| Q-03 | Info | Carried from QC (already dropped as cosmetic under the zero-residual nit rule): stale module-docstring phrase in `tests/test_bilibili_api_gateway.py`, an inert `100` literal in an invalid-argument parametrization, and `.env.example` not repeating the blank-as-unset caveat. None touches shipped behaviour or the acceptance surface. | No action at this gate |

No blocking or warning-severity finding. No new residual opened.

## 6. Residual / register check *(QC item 5)*

- No `.mstar/projects/` directory and **no `residuals.json`** anywhere under `.mstar` → register absent ⇒ empty.
- Workflow snapshot `…/workflows/20260911-live-metadata-path-fix/snapshot.json` carries no residual rows
  (only `plans[0].metadata.gates = { "qc": "pending", "qa": "pending" }` and `plans[0].status = "InReview"`).
- QC's 3 open items are cosmetic and were dropped by the consolidation; both fix waves were revalidated Approve.
- Conclusion: **zero-residual holds**; nothing for L4 to close.

## 7. Verdict

**Approve — recommend merge to `main`.**

The branch is checkout-aligned, all 8 plan acceptance criteria are met with reproducible evidence, the
lockfile delta is additive-only and host-installable, the offline suite is green at the expected count, and
the plan's core acceptance — a bounded live one-page collection — was reproduced fresh at this gate on the
first attempt with real normalized rows and an advanced cursor, credential-clean.

The plan remains `InReview`; `Done` and the merge belong to the PM (merge precedes Done).

## 8. Limitations / not tested

- The live smoke ran **once**, on the credentialed happy path; the anonymous bounded-failure arm was not
  exercised live (a credential was present). Its logic is covered offline inside the 903 by the seam
  rehearsal, the documented-code parametrizations, and the loud-fail control for `transport_error`.
- `ps=50` / `ps=100` upstream behaviour was **not** re-probed here (plan evidence stands; the gate deliberately
  added no extra upstream load).
- Point-in-time observation: live upstream/risk-control behaviour can change after 2026-09-11; the recorded
  counts are not a standing guarantee.
- Not covered by this gate: PR creation/merge, `main` integration, the PM-owned snapshot `gates` update, plan
  `Status`/`Done`, and the plan's Acceptance-Criteria checkboxes (outside this assignment's write scope).
- No quantitative coverage run was performed (not part of the DoD).
- Pre-existing gitignored caches (`.pytest_cache/`, `__pycache__/`) remain in the worktree; regenerable, and
  never committed. All scratch environments/artefacts created by this gate were removed.

## 9. Reproduction steps

```bash
WT=/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix
CTRL_PY=/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python

# alignment
cd "$WT" && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && git status --porcelain

# lockfile + fresh install (scratch; never the control venv)
cd "$WT/bilibili-asr-archive" && /root/.local/bin/uv lock --check
UV_PROJECT_ENVIRONMENT=/tmp/qa-scratch /root/.local/bin/uv sync --frozen --no-install-project
/tmp/qa-scratch/bin/python -c "import curl_cffi, bilibili_api, importlib.metadata as m; \
print(m.version('curl-cffi'), m.version('bilibili-api-python'))"

# offline suite at HEAD
cd "$WT/bilibili-asr-archive" && "$CTRL_PY" -m pytest -q -rs

# opt-in live smoke (from the worktree package dir; credential via .env only)
cd "$WT/bilibili-asr-archive" && set -a && source /root/workspace/bilibili-asr-archive/.env && set +a \
  && BILI_HTTP_PROXY=http://127.0.0.1:7890 BILI_LIVE_SMOKE=1 "$CTRL_PY" -m pytest tests/test_live_metadata_smoke.py -s -v

# lock sanity
cd "$WT" && git diff 25a11fe a898fdf -- bilibili-asr-archive/uv.lock && git diff --check 25a11fe a898fdf
```

## 10. Recommended owners

| Item | Owner | Note |
|---|---|---|
| Merge PR `fix/20260911-live-metadata-path-fix` → `main`; set plan `Done`; update snapshot `metadata.gates.qa` | `project-manager` | QA gate satisfied; merge precedes Done |
| (optional, cosmetic) stale docstring / inert literal / `.env.example` caveat in `tests/test_bilibili_api_gateway.py` + `.env.example` | next touch of those files | Not a residual; dropped per the zero-residual nit rule |
