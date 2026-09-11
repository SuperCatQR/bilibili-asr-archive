# QA Gate Report — 20260909-bilibili-api-ingestion (L4 acceptance)

- **Role**: qa-engineer (leaf executor, delegation forbidden; report-only + plan `## QA Gate Summary`)
- **Iteration**: `iter-2026-09-bilibili-api-sqlite` · **Plan**: `20260909-bilibili-api-ingestion` (SDD, Batch 2)
- **QA gate**: mandatory · **QA mode**: acceptance-only (evidence reuse first; QC bundle routed four fresh-evidence items U1–U4 to this gate)
- **Review cwd**: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion`
- **Working branch**: `feature/20260909-bilibili-api-ingestion` · **HEAD**: `3dcc51b` (`3dcc51bba0ae3a871c37eb31d22ddaccd488b25c`)
- **Review range / Diff basis**: `e62280a..3dcc51b` (5 commits: `dfb66ba`, `0c2c379`, `6359e7d`, `783986a`, `3dcc51b`)
- **Findings cleanup**: zero-residual
- **Date**: 2026-09-10

## Verdict

**Approve (recommend merge).**

QC's final gate decision (qc-consolidated.md `## Final gate decision`) was "Approve conditional on the mandatory QA gate closing the routed runtime evidence U1–U4". This gate executed all four routed items at HEAD `3dcc51b`:

| Item | Routed ask | Fresh outcome |
|------|-----------|---------------|
| U1 | Re-run pass counts at post-fix baseline | ✅ Focused pair **131 passed, 1 skipped** (0.95s); full suite **857 passed, 1 skipped** (41.64s) — both exactly the expected post-fix baseline |
| U2 | Re-run `uv lock --check` | ✅ Exit 0, "Resolved 98 packages", no lock mutation (reproducible no-op) |
| U3 | Execute the opt-in live smoke | ⚠️ Executed (attempt + one mandated retry). Both runs ended in the **designed bounded failure** `response_error`: the upstream is reachable but rejects the anonymous (credential-free) metadata chain. Failure path verified live (atomic terminal run, scalar-only evidence); happy-path page collection not demonstrable from this environment — recorded honestly, not a plan-code defect (see U3 section) |
| U4 | Real-wheel shape inspection incl. `get_info` top-level `bvid` | ✅ All seam assumptions confirmed from the pinned 17.4.2 wheel (see U4 section) |

No new Critical/Warning/Suggestion arose from this gate. Zero open residuals. Recommend merge; PM owns the integration merge and the `Done` transition.

## Scope tested

Plan scope only: the pinned `bilibili-api-python==17.4.2` gateway boundary (`src/bili_asr/sources/*`), the resumable normalized metadata ingestor (`src/bili_asr/services/*`), the seam contract tests + shared fake fixture (`tests/test_bilibili_api_gateway.py`, `tests/test_metadata_ingest.py`, `tests/fixtures/fake_bilibili_gateway.py`), `pyproject.toml`/`uv.lock` dependency pin, and the opt-in live smoke. Plan-1 storage modules, the JSONL `bili_client` fallback path, and CLI wiring (Batch 3) are outside this plan's diff.

## Checkout alignment

- Review cwd, working branch, HEAD, and cumulative range all match the Assignment **and** the locked QC pack (qc-consolidated.md: same cwd/branch; final reviewed head `3dcc51b`; range `e62280a..3dcc51b`). `git status` clean at start; worktree unmutated throughout (read-only except harness report files).
- Interpreter note: the worktree has no `.venv`; all test commands ran with the control venv interpreter (`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`, CPython 3.12.13), exactly as the implementer/L2/QC evidence did. `tests/conftest.py:12` inserts the **worktree** `src` at `sys.path[0]`, so every run exercised the worktree code under review, not the control checkout's editable install (verified: editable `.pth` still points at the control `src`; worktree `src` wins during pytest).

## Evidence reuse (read before re-running)

| Source | What was reused |
|--------|-----------------|
| `implementer-task-1/2/3-report.md`, `implementer-qc-fix-1-report.md` | L1 evidence: TDD red/green triples, commands, per-checklist dispositions, D1–D3 decisions, live-smoke bounded expectations, fix-wave per-finding dispositions |
| `review/task-1/2/3-review.md` (L2) | All three Approved; each item-by-item spec-compliance table; L2's own focused re-runs (17 passed; 122+1sk); "cannot verify from diff" flags (wheel claims, full-suite counts, live smoke) — the same flags the QC bundle routed here |
| `review/qc1.md`, `qc2.md`, `qc3.md`, `qc-consolidated.md` | Findings, not a test log: W1 (bvid boundary asymmetry, fixed in `3dcc51b`), S-fix-1…8 dispositions, seat verdicts (qc1 Unconfirmed→no-objection, qc2 Approve after revalidation, qc3 Approve), U1–U4 routings with pre-dispositioned owners |
| `review/fix-1-diff.md`, `branch-diff.md` | Fix-wave diff (4 files, +278/−30; storage/pyproject/uv.lock untouched) and whole-branch diff package |

QC reports were used as findings/verdict inputs only; every runtime number below is a fresh L4 execution, not a transcription.

## U1 — pass-count re-runs (fresh)

Commands (worktree product root, control venv interpreter — same form as all prior evidence):

```
cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v
→ 131 passed, 1 skipped in 0.95s     (skip = test_live_smoke_single_public_page_for_archive_owner, the opt-in live smoke — confirmed by name in the -v listing)

cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
→ 857 passed, 1 skipped in 41.64s
```

Both exactly match the expected post-fix baseline (131+1sk focused; 857+1sk full). Zero regressions; the AST import-boundary tests, W1 malformed-bvid tests (both aid flavors, adapter + ingestor e2e), S-fix-1…8 pins, sentinel no-leak scans, and the loud-fail live-smoke guard all ran green inside these suites.

## U2 — `uv.lock` reproducibility (fresh)

```
cd bilibili-asr-archive && uv lock --check
→ exit 0; "Resolved 98 packages in 2ms"; lock file unmodified
```

Static consistency (already diff-verified by QC, re-spot-checked here): `uv.lock` pins `bilibili-api-python` `17.4.2` from `registry = "https://pypi.org/simple"`; `pyproject.toml` adds exactly one dependency line; no path dependencies.

## U3 — live smoke execution (opt-in, bounded, no credential)

**Execution (fresh, this gate):**

1. Environment prep per the consolidated gate: the pinned dist was not in the control venv. Installed it with
   `UV_PROJECT_ENVIRONMENT=/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv uv sync --frozen --no-install-project --inexact`
   from the worktree product root — i.e. the worktree's `pyproject.toml`+`uv.lock` (with the pin) targeted at the **control venv**, matching the gate's "installs the pinned dist into the control venv". Protective flags (all documented in the command record): `--frozen` never touches any lock; `--no-install-project` leaves the control venv's editable `bili_asr` binding (pointing at the control `src`) untouched; `--inexact` removes nothing pre-existing. No `.venv` was created inside the worktree. Verified: `importlib.metadata.version("bilibili-api-python") == 17.4.2`; package imports from the control venv's site-packages; editable `.pth` unchanged.
2. Command (exact, as routed):
   `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner -v`

**Outcome (recorded honestly):**

- **Attempt 1**: the smoke ran the real bounded flow and ended in a **bounded upstream failure, scalar code `response_error`** (pytest `Failed: live one-page smoke ended in a bounded upstream failure (code='response_error')`).
- **Retry** (one, after an 8s pause, per the dispatch instruction): **identical bounded outcome** (`response_error`). Deterministic upstream rejection, not transient.
- What each attempt proved before the explicit `pytest.fail` (test lines 933–948): `get_package_version() == "17.4.2"` (pinned dist live), the ingestor started a run, fetched through the real adapter, and finished **atomically with exactly one page-evidence row** (`result.page_count == 1` asserted), a terminal bounded outcome, and a structured `IngestionRunResult` carrying only the scalar code — no raw exception text, URLs, cookies, or response JSON escaped the process. Persisted-rows summary for the failed runs (derived from the ingestor's fetch-phase failure mechanism + the test's own assertions; the fixture tears the temp DB down): one `ingestion_runs` row (terminal, scalar `response_error`), one page row (page 1, scalar `response_error`), zero user/video/part/discovery rows, cursor untouched (absent on a first-page failure).

**Classification:** upstream/environment condition, **not a plan-code defect**.

- Upstream reachable: fast HTTP-level responses (whole pytest run ≈0.35s, including the package import).
- Failure surfaced through the package's own API-code/exception check path: per the pinned wheel, non-zero API `code` → `ResponseCodeException` (`utils/network.py:2298–2314`); unmapped codes and package `ApiException`-family errors (e.g. `InitialStateException(ApiException)` from the render-data pre-fetch) map to the adapter's `response_error`. The precise upstream numeric code/message stays process-local by the plan's bounded-failure design — this report intentionally records only the mapped scalar code.
- The pinned 17.4.2 `User.get_videos` internally requires `w_webid`, which it derives by fetching the user's space dynamic page (`utils/user_render_data.py`, `get_user_dynamic_render_data` → `get_initial_state`) before the `x/space/wbi/arc/search` call. From this environment (datacenter, anonymous, no credential), that chain is rejected by upstream anti-bot/risk control. The adapter cannot alter this: its job — translate upstream failures into bounded scalar codes — demonstrably worked, twice, live.
- The plan's smoke constraint is "no credential" by design; adding SESSDATA is explicitly out of the smoke's scope (global constraint: optional SESSDATA via `BILI_SESSDATA`/CLI belongs to the Plan-3 CLI). The Task-3 recorded bounded expectations already list this outcome class ("a bounded upstream failure fails the smoke with the scalar code shown; rerun when upstream recovers").
- No STOP condition triggered: the smoke stayed bounded to one requested page (`page_count == 1`) and wrote only inside the temporary test root (`.test-tmp/…/live-smoke.sqlite`, gitignored, removed in fixture teardown).

## U4 — real-wheel shape inspection (installed 17.4.2 wheel from PyPI)

The dist installed into the control venv **is** the pinned wheel content (`bilibili_api_python-17.4.2.dist-info`, Name/Version verified; `uv.lock` source = `https://pypi.org/simple`). Inspection one-shot, scratch-free (no downloads needed — read from the installed wheel; no artifacts left):

| Fake-seam assumption | Wheel evidence (bilibili_api 17.4.2) | Verdict |
|----------------------|--------------------------------------|---------|
| `User.get_videos` returns the **inner** arc/search `data` (`list.vlist` items, `page.count`) | `user.py:429–468` builds `API["info"]["video"]` = `x/space/wbi/arc/search` (wbi-signed, `verify: false`); `Api._check_response` (`utils/network.py:2276–2321`) raises on HTTP≠200 (`NetworkException`) and on non-zero API `code` (`ResponseCodeException`), else **auto-unwraps `.data`** → callers receive the inner data dict | ✅ Confirmed |
| `Video.get_pages()` makes **no** internal `get_info` call | `video.py:384–395`: `x/player/pagelist` with `aid`/`bvid` params from local attrs; `Video(bvid=…)` → `set_bvid` validates `^BV[a-zA-Z0-9]{10}$` (same pattern the adapter applies) and derives aid **locally** via `bvid2aid(bvid)` (`video.py:187–192`) | ✅ Confirmed |
| `get_info()` detail response carries top-level `bvid` (S-fix-4 identity anchor) | `video.py:237–251`: `x/web-interface/view`, auto-unwrapped detail body. The wheel pins the endpoint; field presence is upstream response shape (stable top-level `bvid` of the view API). Worst case is bounded by construction: a missing/mismatched `detail["bvid"]` is a bounded `GatewayShapeError` (`bilibili_api_gateway.py:230–232`), never a crash or wrong-aid fill | ✅ Endpoint confirmed; dependency bounded either way |
| Exception hierarchy/signatures mirrored by the fake seam | `NetworkException(status, msg)`, `ResponseCodeException(code, msg, raw=None)`, `ResponseException(msg)`, `ApiException(msg)`, `WbiRetryTimesExceedException()` — all present with exactly the signatures the adapter's mapping table assumes | ✅ Confirmed |
| `Credential(sessdata=None, …)` | `utils/network.py:1154–1161` (sessdata default None; extra optional fields unused by the adapter) | ✅ Confirmed |

No wheel download scratch was needed (inspection read the installed wheel); nothing to clean beyond runtime caches (removed; see Hygiene).

## Acceptance / Done Criteria mapping

| # | Plan criterion | Covered by | Evidence |
|---|----------------|-----------|----------|
| 1 | `bilibili-api-python==17.4.2` pinned, `uv.lock` reproducible | Reuse + **newly executed** | `pyproject.toml` one-line pin + `uv.lock` PyPI entry (QC-verified, re-read here); U2 fresh `uv lock --check` no-op (this gate) |
| 2 | Only `sources/bilibili_api_gateway.py` imports `bilibili_api` | Reuse, re-greened in fresh runs | AST tests (`test_only_the_gateway_module_imports_bilibili_api`, import-set-equality) green inside U1 re-runs; L2 greps (task-1/3 reviews) |
| 3 | DTOs validate required fields, reject malformed responses | Reuse, re-greened in fresh runs | Task-1 normalization/validation tests + W1 malformed-bvid tests (both aid paths) green inside U1 re-runs |
| 4 | Normalized entities + discovery idempotency (repeated pages update, no duplicate rows) | Reuse, re-greened in fresh runs | Task-2 upsert/idempotency tests + Task-3 seam-run tests green inside U1 re-runs (`ON CONFLICT DO UPDATE` pins reviewed by L2-2) |
| 5 | Cursor advances only after page commit; failed pages keep prior cursor | Reuse, re-greened in fresh runs | `test_gateway_failure_…` (byte-for-byte `CursorRecord` equality), rollback + resume tests green inside U1 re-runs |
| 6 | Bounded failure records: scalar codes only (no credentials/signed URLs/raw JSON/stack traces) | Reuse + **newly executed (live)** | Offline sentinel scans green in U1 re-runs (non-vacuity guard included); live U3 run ended in the designed scalar-only bounded failure |
| 7 | Offline tests pass on Python 3.12 without network | **Newly executed** | U1 fresh full suite: 857 passed, 1 skipped, CPython 3.12.13 (the skip is the opt-in live smoke) |
| 8 | Opt-in live smoke bounded: one public page, UID 23191782, temp SQLite, no subtitle/playback/audio/ASR | Reuse (structure verified) + **newly executed** | Structure: default skip + loud-fail guard (L2-3), AST/method-surface pins. Execution: U3 above — bounded flow held (one page, temp DB, scalar failure); happy-path collection not demonstrable anonymously from this environment (upstream rejection), recorded for Plan 3 |
| 9 | `git diff --check` clean | **Newly executed** | Clean on the worktree (unstaged and vs HEAD); tree clean throughout |

## Residual check

- Residual register: no `residuals.json` entries exist for this plan; engine status reports `residuals: none open`; QC consolidated records zero open R#. **Confirmed: zero open residuals (zero-residual satisfied).**
- Known bounded design limits accepted by QC (dangling-`running` windows, two-transaction risk finish) remain accepted, non-blocking; Batch-3 carries C1–C6 per qc-consolidated.md (`page_limit` bounding, stale-run sweep, `risk_interrupted` cursor producer decision, display-name capability, exit-taxonomy mapping, adapter wiring notes).
- New operational observation for Plan 3 (not a defect, no residual opened): the anonymous live-smoke path is rejected by upstream from this environment (see U3). Plan 3's CLI verification — which supports optional SESSDATA (`BILI_SESSDATA` / `--sessdata` → `BilibiliApiGateway(sessdata=…)`, QC3 handoff C6) — is the right place to demonstrate happy-path collection; document the observed bounded `response_error` as the expected no-credential behavior in its verification record.

## Not tested

- Happy-path live page collection (credential-bearing or upstream-tolerant path) — upstream rejects the anonymous chain from this environment; out of the smoke's no-credential bound; Plan 3 owns operational collection runs.
- Subtitle/playback/audio/ASR/export endpoints — out of plan scope by design (structurally impossible through the adapter; AST/structural-seam tests pin it).
- `funasr`/ASR extras, CLI surface (Batch 3 plan `20260909-metadata-cli-smoke`).

## Reproduction steps

1. Alignment: `cd /root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion && git rev-parse HEAD` → `3dcc51b…`.
2. U1: `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v` → 131 passed, 1 skipped; then `… -m pytest -q` → 857 passed, 1 skipped.
3. U2: `cd bilibili-asr-archive && uv lock --check` → exit 0.
4. U3 prep: `cd bilibili-asr-archive && UV_PROJECT_ENVIRONMENT=/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv uv sync --frozen --no-install-project --inexact` (installs the pinned dist into the control venv; `--frozen`/`--no-install-project`/`--inexact` are protective — no lock/project/env-removal side effects).
5. U3 run: `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner -v` (real network; bounded failure `response_error` observed 2/2 from this environment as of 2026-09-10).
6. U4: inspect the installed `bilibili_api` 17.4.2 wheel in the control venv `site-packages` (`user.py` get_videos / `utils/network.py` `_check_response` / `video.py` get_pages/get_info) — matches the table above.

## Hygiene

- No git mutations: no commits, no checkout, no push; `git status` clean before and after; only this report and the plan's `## QA Gate Summary` written.
- Scratch cleanup: `.test-tmp/` (contained only test-generated scratch, incl. a leftover `audio-outside.m4a` that `tests/test_audio.py` recreates on demand) removed; runtime `__pycache__`/`.pytest_cache` removed; no wheel or venv artifacts inside the worktree; the pinned dist remains installed in the gitignored control venv (intended by the gate's U3 prep; never committed).
- No credential material anywhere in this report: the smoke ran with no SESSDATA; no cookie, signed-URL, raw-JSON, or raw-upstream text is recorded (only the mapped scalar code, per the plan's bounded-failure design).
