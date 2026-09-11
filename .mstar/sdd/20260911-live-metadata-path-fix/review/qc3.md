---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260911-live-metadata-path-fix"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: standard tier (concrete provider/model id is not exposed inside the leaf session; Assignment `Model tier: standard`)
- Review Perspective: performance/reliability, packaging-installability realism, risk/operational honesty (L3 whole-branch)
- Report Timestamp: 2026-09-11T08:24:59+08:00

## Scope
- plan_id: `20260911-live-metadata-path-fix`
- Review range / Diff basis: `25a11fe..5667844` (base = `main` when the branch was cut; 6 commits)
- Working branch (verified): `fix/20260911-live-metadata-path-fix`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix` (`git rev-parse --show-toplevel` + `git branch --show-current`; `HEAD` = `5667844747f6f146744589f0dce13411f884d5dd`)
- Files reviewed: 15 changed files / +1206 −122 (complete `review/branch-diff.md`, 1988 lines) plus plan, pinned spec, SDD ledger, 5 L2 task reviews (2 with `## Revalidation`), 7 implementer reports and the workflow snapshot; cross-checked against the installed `bilibili-api-python 17.4.2` / `curl_cffi 0.16.3` sources and the control `.venv` (read-only)
- Commit range: `25a11fe..5667844` — identical to the Review range (verified: `cc56e46`, `0a2e2f5`, `3a96dd1`, `f4af1aa`, `f44066c`, `5667844`)
- Analysis methods: git-diff / git-log / `git diff --check` (read-only; no git mutation), read, grep, glob, deep-lens analysis — **no** test/build/lint/install run, **no** live network run, `BILI_LIVE_SMOKE` never set
- Deep review: triggered (S1 — 1206 changed lines / 15 files ≥ 200 / ≥ 8; S6 — ≥ 3 module boundaries: packaging+lock, `config`, gateway, `services`/`models`, tests/fixtures, docs)
- Lenses applied: **Reliability Lens**, **Enforcement-Path Lens**, **Ownership / Derived-State Lens** (qcs-3 defaults) + **Testing Lens** (Assignment focus 4) + packaging/installability sweep (focus 1) + operational-honesty sweep (focus 2)

## Independent verification performed (not taken from L1/L2 reports)

1. **Checkout/range alignment**: `git rev-parse --show-toplevel`, `git branch --show-current`, `git log --oneline 25a11fe..5667844` reproduce the Assignment's worktree, branch and 6 commits exactly; working tree clean.
2. **`git diff --check 25a11fe..5667844` → clean (exit 0, no output)** — the plan's AC "`git diff --check` is clean" is confirmed by me at the reviewed head, not inherited.
3. **Lock delta has no hidden re-pins and no hash gaps**: the range's diff contains **zero** `-` lines for `bilibili-asr-archive/uv.lock` (additive only, 99 packages). The new `curl-cffi 0.16.3` block carries a sha256 sdist + 21 sha256 wheels covering linux x86_64 / **aarch64** / i686 / armv7l / riscv64, musllinux x86_64+aarch64, macOS x86_64+arm64, Windows amd64+arm64 — and this host is `aarch64` (`manylinux2014_aarch64` present ✓). Root `dependencies` and `requires-dist` both carry `{ name = "curl-cffi", specifier = ">=0.16" }`; `curl-cffi`'s own deps `cffi>=2.0.0` / `certifi>=2024.2.2` are already satisfied in-lock (`cffi 2.1.1`, `certifi 2026.7.22`), which is why no other package version moved.
4. **D1 premise reproduced from installed metadata**: `bilibili_api_python-17.4.2.dist-info/METADATA` has 12 `Requires-Dist`, **0** `Provides-Extra`, and no `curl_cffi`/`httpx`/`aiohttp` — the docs' "declares no HTTP client of its own … and no extras" claim holds; `get_client()` really raises `ArgsException` with no client registered (`utils/network.py:1060-1070`), i.e. the documented "fails in-process → bounded `response_error`" path is real.
5. **D2 mechanism verified in the pinned source**: `clients/CurlCFFIClient.py` builds `requests.AsyncSession(..., proxies={"all": proxy}, trust_env=True)` with `proxy=""` by default; `utils/network.py:1060-1092` builds a loop-scoped session from `DEFAULT_SETTINGS` (which includes `proxy`) and replays later `set_proxy` calls onto already-created sessions via `lazy_settings`. The adapter's apply-at-construction therefore lands in **both** cases (session exists / does not exist yet) — the fix is mechanically sound, not just plausible.
6. **D3 call shape verified field-by-field against the installed pin**: `data/api/user.json["info"]["video"]` = {`url`, `method` GET, `verify` false, `wbi` true, `dm` true, `params{mid,ps,tid,pn,keyword,w_webid}`, `comment`} — byte-identical to the seam's `FAKE_USER_VIDEO_PAGE_ENDPOINT`; `user.py:429-468 get_videos` sends exactly {`mid`,`ps`,`tid`,`pn`,`keyword`,`order="pubdate"`,`order_avoided=True`,`platform="web"`,`w_webid`}; `Api` is a dataclass (`dm: bool = False`) whose `_prepare_request` injects `_enc_dm` **only** `if self.dm` (`:2227-2228`) and drops `None` values — so the package's own `w_webid=None` genuinely leaves the parameter absent upstream while the adapter's `""` is present. Both fields the adapter owns are exactly the two diagnosed defects, and nothing else in the parameter set drifts.
7. **Bounded taxonomy reachable and ordered correctly**: `NetworkException`/`ResponseCodeException`/`WbiRetryTimesExceedException`/`ResponseException` all subclass `ApiException` and `NetworkException.status` exists, so the `_await_upstream` ladder (`gateway:411-432`) maps 412/429 → `rate_limited`, `-412/-352/-799` → `rate_limited`, `-404/-62002` → `not_found`, other upstream codes → `response_error` as the plan locks.
8. **Transport selection**: `bilibili_api/__init__.py::__register_all_clients` iterates `ALL_PROVIDED_CLIENTS[::-1]` and `register_client` calls `select_client(...)` per registration, so **curl_cffi wins when installed**, including in a full `.[asr]` install where `httpx` arrives anyway (`uv.lock`: funasr → huggingface-hub → httpx).
9. **Test hermetics reviewed from source**: the apply-once and no-proxy tests are guarded by `empty_proxy_environment` (`tests/test_bilibili_api_gateway.py:944`); the seam fixture deletes/re-imports only the adapter module per test; no new test reads the clock, the network, a diagnosis-time local install (the packaging test's installed-distribution dependence is disclosed at `:17`), or depends on ordering.
10. **No new leak surface**: the added smoke evidence line is count-only (`test_live_metadata_smoke.py:321,332`), the docs' commands print no credential, and the new sentinel-based no-leak assertions cover DTO/`repr`/mapped-error/persisted-row surfaces for both the proxy value and the `access_id` token.
11. **Residual stale-page-size sweep**: no shipped `src/`, docs or README site still describes 100 as the current page size (only the dated historical mentions remain), and `PAGE_SIZE = 30` is the value the shipped ingestor passes (`services/metadata_ingest.py:50,229`; single construction site `cli.py:571`).
12. **Ledger arithmetic**: 865→866→885→892→894 test deltas are consistent with the per-task new-test counts (Task 4 adds assertions, +0 functions; Task 5 adds 2).

## Findings

### 🔴 Critical
- (none)

### 🟡 Warning
- (none — see the Summary for why the docs-completeness and proxy-global items below are Suggestions rather than blockers)

### 🟢 Suggestion

- **[S-001] The operator-facing live-observation record stops one step short of the branch's own strongest evidence.** `docs/metadata-storage.md:208-226` records (a) "the live run was refused by upstream risk control" (Task-4 observation, `ps=100`) and (b) probe-level success (`ps=30` → `code=0`, 30 items). The same day's **end-to-end** result after the Task-5 fix — CLI exit 0, `outcome=limited videos=30 parts=33 discoveries=30 page_rows=1 cursor_next_page=2 cursor_state=limited observed_total=1691` (`progress.md:146-148`, `implementer-task-5-report.md:186`) — is absent from the SSOT operators and the QA gate will read, while the surviving sentence "a loud live-smoke failure means the bounded page was refused upstream, not that the database or the CLI is broken" is the only interpretation guidance for a QA-time failure. → Add one dated, count-only bullet recording the achieved happy path (and keep the intermittency caveat).
  - Source Type: deep-lens: Reliability Lens (operational honesty sweep)
  - Verification: diff/read anchor — `docs/metadata-storage.md:208-226` vs `.mstar/sdd/20260911-live-metadata-path-fix/progress.md:146-148` and `implementer-task-5-report.md:186`; `grep -rn 'videos=3\|parts=33\|exit 0' docs/ README.md` returns no achieved-run record (only the smoke's *requirement* text at `docs:188`, `README:585`)
  - Expected vs observed: expected the dated live-observation section to reflect the latest observed state of the **shipped** path at HEAD (the run that met AC #5); observed it ends at probe-level evidence plus an earlier refusal, so a reader cannot learn from the docs that the shipped path completed a page
  - Confidence: High

- **[S-002] The applied proxy is process-global and sticky, while the documented wording is per-instance.** `request_settings` is a process-wide singleton (`utils/network.py:238-241, 430`) whose `set_proxy` mutates the shared per-loop sessions through `lazy_settings` (`:272-308`); the adapter applies at construction (`gateway:277-279`) and never clears. A second gateway in the same process that resolves **no** proxy therefore inherits the first one's value, so "when nothing resolves, the library default is left untouched" (`docs/metadata-storage.md:131-132`, adapter docstring `gateway:270-273`) is true of the adapter's *action* but not of the effective transport. Trigger: any second `BilibiliApiGateway` in-process (a future multi-stage command, or tests run against the real pin) with a different or absent proxy. → Apply per instance around its own calls, reset when nothing resolves, or state the global explicitly in the operator docs. Note: the shipped CLI has exactly one construction site (`cli.py:571`) and a second same-env gateway would resolve the identical value, hence Suggestion (L2 Task-2 Minor #3 re-judged, not escalated).
  - Source Type: deep-lens: Ownership / Derived-State Lens
  - Verification: read anchor — `utils/network.py:238-241` (`session_pool`/`lazy_settings` globals), `:272-308` (`set`/`set_proxy` propagation), `:1060-1092` (`get_client` builds/reuses per-loop sessions), `gateway:277-279`, `docs/metadata-storage.md:131-132`; single production construction site `cli.py:571`
  - Expected vs observed: expected a per-instance proxy decision to be visible in the effective transport state; observed a process-global setting outliving the instance that set it
  - Confidence: High

- **[S-003] The new transport specifier is unbounded while the docs also offer a non-lock install path.** `pyproject.toml:14` declares `curl_cffi>=0.16` and `docs/metadata-storage.md:96-100` presents `pip install -e ".[dev]"` as equivalent to `uv sync`. The pinned client imports concrete curl_cffi APIs at module import (`curl_cffi.requests`, `CurlHttpVersion`, `CurlMime`, `CurlInfo`, `curl_cffi.aio`, `WebSocketError`) inside `__register_all_clients()`, which only tolerates `ModuleNotFoundError`; a future 0.17/1.0 rename would make `import bilibili_api` raise, surfacing to the operator as the fixed `fetch-meta: unexpected error` exit 2 with no code. The lock (`0.16.3`) protects the `uv sync` path only. → Bound the specifier (`>=0.16,<0.17`) or mark the lock as the supported install path in the docs.
  - Source Type: deep-lens: Reliability Lens (installability realism)
  - Verification: read/diff anchor — `pyproject.toml:14`, `uv.lock:484-491` (0.16.3), `clients/CurlCFFIClient.py:15-16,52-60`, `bilibili_api/__init__.py::__register_all_clients`, `cli.py:578-582` (`except Exception` → fixed "unexpected error")
  - Expected vs observed: expected the load-bearing transport version to be as bounded as the library it drives (`bilibili-api-python==17.4.2`); observed an open-ended `>=0.16`
  - Confidence: Medium

- **[S-004] Nothing in the branch asserts *which* transport the library actually selects, and one test constant overstates what is checked.** The plan locks `curl_cffi` as the transport ("the library's recommended transport for risk control"), but the enforcement is only the declaration plus the pinned package's registration order. In the project's own full install (`.[asr]` → funasr → huggingface-hub → httpx) two candidate clients are present, and the winner is decided inside the dependency. I verified the outcome is correct today (curl_cffi registers last ⇒ selected), but a package-side reorder would silently move the app to httpx with no local failure. Separately, the constant's docstring (`tests/test_bilibili_api_gateway.py:1007-1010`) claims "None of them may arrive through the application's dependency closure on its own", while the assertion inspects only the **pinned distribution's** `Requires-Dist`; httpx does arrive through the app's `asr` extra. → Add one offline assertion/QA step for `get_selected_client() == "curl_cffi"`, and narrow the constant's wording to what is checked. (Extras-blindness is L2 Task-1 Minor #2; the missing selection guard is a new, adjacent gap.)
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: read anchor — `bilibili_api/__init__.py::__register_all_clients` + `utils/network.py:961-981` (`select_client` per registration, reverse order), `uv.lock:642-651` (funasr → huggingface-hub → httpx), test constants at `tests/test_bilibili_api_gateway.py:80-87`
  - Expected vs observed: expected the plan's locked transport choice to be enforced or asserted somewhere in-repo; observed it rests on third-party registration order and is not asserted
  - Confidence: Medium-High

- **[S-005] The packaging contract test never asserts that the *installed* pinned distribution is the pin.** `tests/test_bilibili_api_gateway.py:888-925` reads `importlib.metadata.distribution("bilibili-api-python").requires` but not `.version`, so its "the pinned package declares no HTTP client" conclusion can be drawn from a non-pinned installation (the module-level constant `PINNED_PACKAGE_VERSION = "17.4.2"` is already in scope). L2 Task-1 Minor #1 — independently confirmed still open at HEAD. → Add `assert pinned_distribution.version == PINNED_PACKAGE_VERSION` so the premise is exact and the failure message stops being ambiguous.
  - Source Type: deep-lens: Testing Lens
  - Verification: diff/read anchor — `tests/test_bilibili_api_gateway.py:905-925` (uses `.requires` only) vs `:75-76` (`PINNED_PACKAGE_DISTRIBUTION_NAME` / `PINNED_PACKAGE_VERSION`)
  - Expected vs observed: expected the tripwire to fail only when the *pin* changes its requirements; observed it also fires (or stays silent) on whatever version happens to be installed
  - Confidence: High

- **[S-006] The fake seam is slightly more permissive than the real package in two places.** (a) `request_settings.set_proxy(proxy: str = "")` (`tests/fixtures/fake_bilibili_gateway.py:297`) has a default the real `RequestSettings.set_proxy(self, proxy: str)` lacks (`utils/network.py:301`), so a future no-argument call would pass offline and fail live (L2 Task-2 Minor #1 — still open). (b) The fake's `Api` records `order_avoided=True` as a bool while the real `_prepare_request` converts bools to `int` before sending, so the "exact parameters" assertion is exact about the adapter's dict, not about the wire payload — inert today, but it means the seam cannot detect a bool/`None` normalisation regression. → Mirror the real signature (no default) and, if cheap, the bool→int normalisation.
  - Source Type: deep-lens: Testing Lens
  - Verification: read anchor — fixture `:297-305` vs `utils/network.py:301` and `:2202-2216` (bool→int, `None` dropped)
  - Expected vs observed: expected the seam to fail where the real package would; observed two named divergences that are permissive rather than strict
  - Confidence: High

- **[S-007] The `w_webid` degradation is silent by construction, and the token route cannot currently succeed.** `_resolve_w_webid` (`gateway:376-399`) swallows every `Exception`, memoises the result per mid, and leaves no observable trace (no flag, no debug line); the route (`utils/user_render_data.py:24-38`) returns `None` while the dynamic page stays SSR-less, so the run spends one extra credentialed fetch of `space.bilibili.com/{mid}/dynamic` per process and then sends `w_webid=""`. If that empty value were ever refused, the operator would see `rate_limited` (412 mapping) rather than anything pointing at the token shape. Plan-locked and documented in the adapter docstring, so diagnosability only (L2 Task-3 Minor #2 — recurring). → Expose a presence-only signal (e.g. a boolean on the gateway or a debug-level note) without ever surfacing the token value, and note the extra fetch in the operator docs.
  - Source Type: deep-lens: Reliability Lens
  - Verification: read anchor — `gateway:376-399`, `utils/user_render_data.py:24-38` (`return None` when no `__RENDER_DATA__`), `utils/network.py:2227-2228` + `:2202-2216` (absent vs empty parameter), taxonomy `gateway:413-418`
  - Expected vs observed: expected degradation to be observable when it happens; observed a silent fallback with no signal outside the docstring
  - Confidence: High

- **[S-008] The page-size change silently remaps page numbers for any pre-existing cursor.** The cursor contract is page-based (`services/metadata_ingest.py:200,375,458`), and `PAGE_SIZE` moved 100 → 30, so a stored `next_page` written by an archive collected at `ps=100` no longer names the same offset on resume (duplicate/gap risk in the collected set). The plan states "cursor semantics are page-based and therefore unchanged", which is true syntactically but glosses the offset remapping. Impact today is nil: no `archive.db` exists anywhere in this workspace (glob: none) and the diagnosis shows the shipped path could never commit a page at `ps=100`. → Add one line to the resume/cursor docs (or a cursor-invalidating note) so a locally patched pre-fix archive is not silently re-sliced.
  - Source Type: deep-lens: Ownership / Derived-State Lens
  - Verification: diff/read anchor — `services/metadata_ingest.py:44-50` (`PAGE_SIZE` 100→30), cursor semantics `:200,375,458`, plan §Locked decisions "Cursor semantics are page-based and therefore unchanged"; workspace-wide `**/archive.db` → no files
  - Expected vs observed: expected the derived cursor state to be tied to a declared page size; observed a page-size change with no invalidation note (harmless only because no cursor was ever written)
  - Confidence: Medium

- **[S-009] The live smoke's happy path asserts an upstream page composition, not the code path.** `test_live_metadata_smoke.py:210` requires `part_count >= 1` in aggregate. The same suite (fix-wave re-review) accepts that `_normalize_video_parts` may legitimately return `()` for a video with an empty pagelist, so a legitimate page whose collected videos all have empty pagelists would fail the opt-in smoke **loudly** — exactly the instrument the QA gate must trust on a risk-controlled endpoint where each re-run costs requests. → Assert that the parts *call* ran (recorded call surface) or keep the count assertion with an explicit upstream assumption noted in the docstring.
  - Source Type: deep-lens: Testing Lens
  - Verification: read anchor — `test_live_metadata_smoke.py:205-215` (`assert part_count >= 1`), `progress.md:181` (fix-wave rationale that empty pagelists are legitimate)
  - Expected vs observed: expected the live instrument to fail only on behaviour regressions; observed it can also fail on a valid upstream payload shape
  - Confidence: Medium

- **[S-010] Plan status field has drifted from the workflow snapshot.** `.mstar/plans/20260911-live-metadata-path-fix.md:30` reads `Status: InProgress` while `{WORKFLOW_DIR}/20260911-live-metadata-path-fix/snapshot.json` (`plans[0].status`) reads `InReview`, and the plan's own `## Review Gate Summary` (`:335-342`) says the QC tri is in flight. Durable-artifact consistency only (PM-owned). → Update the plan's `## Status` block to `InReview` when the QC round closes.
  - Source Type: manual-reasoning (doc-rule) + read anchor
  - Verification: read anchor — plan `:30` vs `snapshot.json` `plans[0].status` vs plan `:337`
  - Expected vs observed: expected the plan's Status block to mirror the workflow snapshot through the InReview phase; observed a stale `InProgress`
  - Confidence: High

### ⚪ Unconfirmed
- (none) — every evidence channel this seat owns (branch diff, source, plan/spec/ledger, L2 reports, installed-pin sources) was intact and reproducible. The runtime gaps that remain are **QA-owned by the plan** and are therefore recorded as hand-offs in the Summary, not as unverifiable findings.

## Source Trace

| Finding | Source Type | Source Reference | Confidence |
|---------|-------------|------------------|------------|
| S-001 | deep-lens: Reliability Lens | `docs/metadata-storage.md:208-226` vs `progress.md:146-148`, `implementer-task-5-report.md:186` | High |
| S-002 | deep-lens: Ownership / Derived-State Lens | `utils/network.py:238-241,272-308,1060-1092`; `bilibili_api_gateway.py:277-279`; `cli.py:571` | High |
| S-003 | deep-lens: Reliability Lens | `pyproject.toml:14`; `clients/CurlCFFIClient.py:15-16,52-60`; `bilibili_api/__init__.py` (`__register_all_clients`); `cli.py:578-582` | Medium |
| S-004 | deep-lens: Enforcement-Path Lens | `bilibili_api/__init__.py`; `utils/network.py:961-981`; `uv.lock:642-651`; `tests/test_bilibili_api_gateway.py:80-87` | Medium-High |
| S-005 | deep-lens: Testing Lens | `tests/test_bilibili_api_gateway.py:888-925`, `:75-76` | High |
| S-006 | deep-lens: Testing Lens | `tests/fixtures/fake_bilibili_gateway.py:297-305`; `utils/network.py:301,2202-2216` | High |
| S-007 | deep-lens: Reliability Lens | `bilibili_api_gateway.py:376-399`; `utils/user_render_data.py:24-38`; `utils/network.py:2202-2228` | High |
| S-008 | deep-lens: Ownership / Derived-State Lens | `services/metadata_ingest.py:44-50,200,375,458`; plan §Locked decisions; workspace `**/archive.db` → none | Medium |
| S-009 | deep-lens: Testing Lens | `tests/test_live_metadata_smoke.py:205-215`; `progress.md:181` | Medium |
| S-010 | manual-reasoning + read | plan `:30`, `:337`; `.mstar/workflows/20260911-live-metadata-path-fix/snapshot.json` | High |

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 10 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

**Blocking rationale.** No Critical and no Warning is unresolved: the four diagnosed defects are fixed by the diff (D1 declaration + additive lock, D2 proxy resolution/appliance with the locked precedence, D3 risk-control-safe call shape, D4 upstream-accepted page size on the shipped constant), and I independently confirmed each mechanism against the installed `bilibili-api-python 17.4.2` / `curl_cffi 0.16.3` sources rather than from the reports (items 4–8 above). The two items that came closest to Warning were deliberately kept as Suggestions, with reasons: the docs omission (S-001) understates rather than overstates, every dated statement in it remains true, and the plan's own AC #5 explicitly allows a recorded upstream blocker — so it is a completeness fix, not a false claim or a merge blocker; the process-global proxy (S-002) is latent with exactly one production construction site in the shipped CLI. No overstatement of what the branch proves was found: the README/docs claims about the missing backend, the `proxies={"all": ""}` mechanism, the proxy precedence ladder, the 412 behaviour and the page-size rejection all match the pinned sources and the recorded observations, and `docs/metadata-storage.md:96-100`'s "a bare `pip install bilibili-api-python==17.4.2` alone is not enough" is correct.

**Hand to L4/QA (plan-owned; QC did not execute these).**
- `Needs L4/QA verification`: a clean `uv sync` (or `uv lock --check` no-op plus a fresh-venv install) proving AC #1's "a fresh install can import an HTTP backend". The branch proves the *structure* (declaration present, lock additive and platform-complete for this `aarch64` host, client auto-registration path); it does not execute an install, and the L1 evidence used a hand-provisioned control venv.
- `Needs L4/QA verification`: one real request through that freshly synced environment (proves transport selection + proxy application on the real client, not only through the fake seam).
- `Needs L4/QA verification`: the full offline suite's `894 passed / 2 skipped` claim (QC does not run suites) and the bounded live smoke re-run with `-s` (the branch's exit-0 happy path rests on `implementer-task-5-report.md:186` and the `/tmp/task5-live-run.log` artifact, read verbatim by the Task-5 reviewer but not independently reproduced).
- Done by this seat instead: `git diff --check 25a11fe..5667844` → clean (exit 0), plus full re-derivation of the four defect mechanisms from the pinned sources.

**Recurring items (already raised at L2, independently re-judged here as Suggestions, none escalated):** S-005 (Task-1 Minor #1), S-006 (Task-2 Minor #1), S-007 (Task-3 Minor #2), S-002 (Task-2 Minor #3). No L2 `Important`/`Critical` finding is open at HEAD: Task-4's I1 (docs page-size narrative) and M1–M5 are resolved in `5667844` per the two `## Revalidation` sections, and I re-checked their subjects at HEAD (docs `:208-226` no longer claims 100 is current; the `-s`/`-rP` rationale and the `BILI_SESSDATA`-only credential channel are documented).
