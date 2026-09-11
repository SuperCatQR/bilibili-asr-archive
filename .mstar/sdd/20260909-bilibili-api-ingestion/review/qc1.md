---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260909-bilibili-api-ingestion"
verdict: "Unconfirmed"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: deepseek — dsh default route (standard tier; exact provider/model id not introspectable from this leaf session)
- Review Perspective: whole-branch plan QC (L3) — spec compliance, contract readiness for Batch 3, cross-task boundary risks, recorded-L2-Minor severity re-judgment; architecture/maintainability seat
- Report Timestamp: 2026-09-10T12:27:11Z

## Scope

- plan_id: 20260909-bilibili-api-ingestion
- Review range / Diff basis: `e62280a..783986a` (merge-base `e62280a` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-bilibili-api-ingestion`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion` (`git rev-parse --show-toplevel`; HEAD `783986a` contains all four in-scope commits `dfb66ba`, `0c2c379`, `6359e7d`, `783986a`)
- Files reviewed: 10 diff files (+5700, incl. generated `uv.lock` 2617 lines) via `review/branch-diff.md`; plus Plan-1 context sources read for composition checks (`storage/database.py`, `storage/models.py`, `storage/schema.sql`) and all listed review inputs (plan, spec, 3 L2 task reviews, 3 implementer reports, progress ledger)
- Commit range (if not identical to Review range line, explain): identical — `e62280a..783986a`
- Analysis methods: git-diff (branch-diff package + read-only `git log`/`git diff --check` re-runs), read, grep — **no test/build/lint runs, no worktree mutation, no commits** (git `diff --check` is read-only diff inspection)
- Deep review: triggered (S1: 5700 lines / 10 files; S3: new domain — `sources/` gateway + `services/` ingestor absent from `{KNOWLEDGE_DIR}`; S6: spans `sources/`, `services/`, `storage/` boundary, `tests/`)
- Lenses applied: Modularity Lens, Contract Lens (seat defaults), Standards Lens, Testing Lens (S3)
- Branch policy: read-only review honored — no commits, no checkout, no push, no worktree mutation (verified `git status` clean at review end; only this report file written)

## Whole-branch spec compliance (Assignment focus 1)

Checked against `specs/bilibili-api-gateway.md` + plan Global Constraints + Done criteria, from the diff and targeted worktree reads:

| # | Constraint | Verdict | Anchor |
|---|-----------|---------|--------|
| 1 | Pin `bilibili-api-python==17.4.2`; `uv.lock` reproducible | ✅ diff-verified / ⚪ lock-check | `pyproject.toml` adds exactly one dependency line; `uv.lock` new file pins `bilibili-api-python 17.4.2` (hash recorded), `requires-dist` matches pyproject incl. `dev`/`asr` extras, no unrelated dep changes. `uv lock --check` no-op is implementer-reported → F-006 |
| 2 | Only `sources/bilibili_api_gateway.py` imports `bilibili_api` | ✅ | Worktree grep: adapter-only import surface in `src/` (`bilibili_api_gateway.py:19-28`); AST tests scan all of `src/bili_asr` recursively and assert the import set equals the allowed metadata surface exactly (`tests/test_bilibili_api_gateway.py`, `ALLOWED_PACKAGE_IMPORTS`) |
| 3 | One bounded page per gateway call | ✅ | One `User.get_videos(pn, ps)` per call (adapter); ingestor issues exactly one `get_user_video_page(mid, page_number, PAGE_SIZE)` per iteration (`metadata_ingest.py:224-227`, FakeGateway `page_calls` asserts one call per page) |
| 4 | Cursor advances only after commit | ✅ structural | All gateway fetches complete before any page transaction opens; `record_page(..., cursor=...)` applies cursor+page outcome inside one committed transaction (`database.py:407-418`); failure path writes no cursor (`_record_failed_page`, `database.py:420-450`) |
| 5 | Zero-based `page_index`; one-based API `page - 1` | ✅ | `bilibili_api_gateway.py` `_normalize_video_part_item` (`page_index=api_page - 1`, one-based ≥1 enforced first); `duration_ms=floor(seconds*1000)` for int/float; DTO `__post_init__` re-validates |
| 6 | `work_id` view-boundary only | ✅ | `work_id` exists only as schema-view concatenation (`schema.sql:147,178`); ingestor never computes it; tests assert it only via `repository.list_pending_parts()` view reads |
| 7 | No subtitle/playback/audio/ASR/export APIs | ✅ | Adapter import surface locked by AST equality test; AST attribute-token scan with positive control; fake seam structurally exposes only `Credential`, `user.User.get_videos`, `video.Video.get_info`/`get_pages` (forbidden names raise `AttributeError`) |
| 8 | Bounded scalar error codes; raw text/URLs/cookies/JSON process-local | ✅ | Five-exception taxonomy with per-class codes validated via Plan-1 `validate_error_code`; mapped messages carry code + operation name only; sentinel machinery (`NO_LEAK_MARKERS`, `persisted_row_text` over every table/view) proves no-leak over persisted rows, run result, and captured logs; non-vacuity guard `test_no_leak_marker_scan_catches_contamination` |
| 9 | SESSDATA never serialized/logged/persisted | ✅ | Value passes only `BilibiliApiGateway(sessdata=...)` → package `Credential`; absent from DTO repr/str, mapped errors, shape errors, rows, logs (sentinel-scanned); ingestor has no credential surface at all |
| 10 | Display-labels-only updates; no metadata history | ✅ | Ingestor writes only current-state upserts (users/videos/parts) + per-run discovery/page/run evidence; no history tables, no raw response documents; `display_name=str(mid)` isolated in `_user_record` helper |
| 11 | No network in fake-gateway tests | ✅ | Fake protocol double + fake `bilibili_api` package on `sys.modules`; the only networked test is the opt-in live smoke (`BILI_LIVE_SMOKE=1`, skips by default — verified `1 skipped` at L2) |
| 12 | Plan-1 canonical forms composed correctly; storage unmodified | ✅ | Zero `storage/*` hunks in the branch diff; ingestor composes `transaction+upsert_user` (bootstrap; `ingestion_runs.mid` FK), `start_run` (independent commit), `record_page` payload/empty/failure forms, `finish_run`, `read_cursor`; locked order and terminal-run guards come from Plan-1 code read directly |
| 13 | Outcome taxonomy honesty | ✅ | `complete` set only on an empty page; `limited` never claims completion (cursor state `limited`, pinned by test); empty page at the limit boundary completes because nothing was cut short (dedicated test); `risk_interrupted` only on `GatewayRateLimited`; failed pages keep the prior cursor byte-for-byte (typed `CursorRecord` equality) |
| 14 | D3 transitive ownership end-to-end | ✅ | Gateway page boundary rejects foreign-owner items; ingestor re-guards each summary (`_completed_summary`, `metadata_ingest.py:319`) **before** any parts/detail fetch; Task-3 seam test asserts the real adapter issues exactly one `user.get_videos` and persists nothing on a foreign-owner page |
| 15 | D1 non-speculative `get_info` | ✅ | Aid-present short-circuit asserted with zero upstream calls; ingestor calls `get_completed_video_summary` exactly when `summary.aid is None` (`test_missing_aid_is_completed_through_the_gateway_without_speculation`: one completion call with an aid-carrying summary present) |
| 16 | `git diff --check` clean | ✅ | Independently re-run read-only on `e62280a..783986a`: clean |

Spec-vs-code divergence (intentional, PM-adjudicated): the spec's protocol block lists 3 methods; the implementation carries the PM-adjudicated 4th method `get_completed_video_summary` (D1). Recorded here for the iteration-close spec refresh; not a finding.

## Contract readiness for Batch 3 (`20260909-metadata-cli-smoke`, Assignment focus 2)

**Sufficient and unambiguous.** The CLI plan's Interfaces ("Consumes: `MetadataIngestor`, `MetadataRepository`, `BilibiliGateway`, configuration from Plans 1–2") are all delivered with explicit semantics:

- **`BilibiliGateway` protocol (4 methods, D1-adjudicated)** — `sources/models.py:95-108`; concrete adapter import path is deliberately excluded from `bili_asr.sources.__init__` and documented there ("import explicitly from `bili_asr.sources.bilibili_api_gateway`"). `sessdata` constructor param + env name `BILI_SESSDATA` fixed by plan Global Constraints. No guessing required.
- **`MetadataIngestor.collect_user_pages(mid, start_page=None, page_limit=None)`** — argument-validation contract is explicit (`TypeError`/`ValueError` before any gateway call, `metadata_ingest.py:214-233`); **every bounded gateway failure becomes an outcome, never an exception** (the page loop catches `GatewayError`; `GatewayError` cannot escape `collect_user_pages`); non-gateway exceptions propagate unchanged per the documented contract. Maps cleanly onto `--mid/--start-page/--limit-pages`; sync facade via `asyncio.run` fits the sync argparse CLI (must not be called inside a running loop — CLI is sync, fine).
- **`IngestionRunResult`** — 8 fields with documented count semantics (incl. the honest `part_count` = "upsert coverage" nuance, no view equivalent); `next_cursor=None` possible (e.g., failed first page); `error_code` only for `risk_interrupted`/`failed`. `runs`/`status` read needs are covered by Plan-1 `read_cursor`/`run_stats`/`list_pending_parts` + `v_pending_metadata`.
- **Recorded live-smoke command** — invocable command + bounded expectations live in `implementer-task-3-report.md` §3 and the progress ledger ("Live smoke recorded for Plan 3"). Plan 3 creates its own CLI-level smoke (`tests/test_live_metadata_smoke.py`), so this is prior seam-level evidence, not a dropped deliverable. Note: the command lives in SDD runtime docs, not the locked plan file — PM may copy it into Batch-3 plan references for discoverability (process note, not a defect).
- **Conscious decisions Batch 3 must make (documented seams, not guessing hazards):** (a) `display_name=str(mid)` — a real display label needs a new gateway capability decision (single change point named in `_user_record` docstring); (b) non-gateway exception → exit-code mapping must be specified in CLI Task 1 (see F-001).

## Findings

### 🔴 Critical

None.

### 🟡 Warning

None.

### 🟢 Suggestion

- **[F-001] Dangling-`running`-run windows (Task-2 Minor 4) — plan-level adjudication: accept as a bounded, disclosed design limit; do not escalate.** Three windows exist: (a) a non-gateway exception after `start_run` (e.g. repository write error mid-page, or a caller-argument-style `ValueError` from a gateway method — see F-002) propagates by design and leaves the run row `outcome='running'` forever; (b) the `risk_interrupted` finish spans two committed transactions (`record_page` page-row commit, then `finish_run`) — a crash between them leaves the run `running`; (c) same two-commit shape on the `complete`/`limited` finishes (page+cursor commit, then `finish_run`). -> Fix/accept: no storage change in this plan (Plan-1 commit matrix unchanged is a verified property); the exception-propagation contract is documented in `collect_user_pages`; resumability and cursor integrity are unaffected (cursor untouched in all windows; a later run works normally). Carry-forward to Batch 3: CLI Task 1 must specify how non-gateway exceptions map to the exit taxonomy, and `runs` output must tolerate/render non-terminal run rows. PM may register as residual if it prefers tracking over acceptance.
  - Source Type: manual-reasoning + deep-lens: Modularity Lens
  - Verification: diff/read anchor — `metadata_ingest.py:199-241` (`start_run` at 210; page loop catches `GatewayError` only at 241; `if outcome != "failed"` at 293 skips `finish_run` for the failed path because `_record_failed_page` already transitions atomically, `database.py:420-450` guarded `WHERE outcome='running'`); `database.py:290-324` (`finish_run` = separate committed transaction)
  - Expected vs observed: expected every started run to reach a terminal row under any termination vs observed abnormal termination (non-gateway exception / crash between the two risk_interrupted commits) leaves `outcome='running'` with no terminal transition — SQLite stays consistent, cursor preserved, later runs unaffected
  - Confidence: High (mechanism) / Low (real-world trigger frequency)

- **[F-002] Boundary-strictness asymmetry on `bvid`: a malformed-but-nonempty upstream bvid escapes the bounded-failure path.** `_normalize_video_summary_item` validates bvid as non-empty string only (`bilibili_api_gateway.py:123-124`), while `get_video_parts` enforces `^BV[a-zA-Z0-9]{10}$` (`bilibili_api_gateway.py:53,272`) and raises a raw `ValueError` for a malformed caller bvid. If upstream ever returned such a bvid, the summary passes the page boundary, the parts fetch raises `ValueError` inside the ingestor's fetch phase, which catches `GatewayError` only (`metadata_ingest.py:241`) — the exception propagates: page unrecorded, run left dangling (`running`), no bounded `shape_error` evidence. -> Fix (one line + test): apply the same BV pattern at the summary normalization boundary so the anomaly surfaces as a bounded `GatewayShapeError` failed page; or have the ingestor fold unexpected gateway-call exceptions onto the failure path (rejected here: it would mask contract errors and contradicts the documented propagation contract). Low likelihood (upstream vlist bvids are well-formed), bounded impact, resumable — Suggestion, not Warning.
  - Source Type: deep-lens: Contract Lens
  - Verification: diff/read anchors above; test `test_get_video_parts_rejects_invalid_bvid_argument` raises `ValueError` by design for caller arguments
  - Expected vs observed: expected every malformed upstream scalar to become a bounded `shape_error` page record vs observed the single bvid pattern checked only at the parts boundary, escaping as a raw `ValueError`
  - Confidence: High (mechanism) / Low (upstream likelihood)

- **[F-003] Recorded L2 Minors re-judged (independent severity pass): none escalate to plan-level blockers.** (a) Dead imports — `tests/test_metadata_ingest.py:17` `sqlite3` and `tests/test_bilibili_api_gateway.py:47` `FakeApiException` (introduced by the Task-3 refactor), plus pre-existing `GatewayShapeError` (`test_metadata_ingest.py:29`) and Task-2's unused `UserVideoPage` (`metadata_ingest.py:29`) — lint-level, fold into the next fix round on this branch if one opens (per Task-3 review recommendation; not worth a dedicated round). (b) Version-test mocks the installed distribution with the same `17.4.2` as the pinned fallback (`test_package_version_reports_installed_distribution`) — test cannot distinguish the installed path; benign under the pin (PM-dispositioned), pin the precedence with a distinct mocked value if `get_package_version` semantics are ever revisited. (c) Prefix-based `assert_only_documented_metadata_calls` — negligible: call strings are fabricated by the shared fake seam itself; tighten to exact-name matching only if the format changes. (d) Unpinned cross-page/cross-run duplicate-discovery flavor — structurally idempotent (upsert keys + discovery PK `(run_id, page_number, bvid)`); Batch-3 E2E Task 2 already plans "re-run the same page and assert no duplicate entity or discovery rows", covering the cross-run dimension. (e) Unreachable `except GatewayError: raise` (`bilibili_api_gateway.py:335`) — dead defensive branch; keep-or-drop per Simplicity First. (f) Task-2 Minor 2/3 (dead `_page` helper `owner_mid` param + misleading docstring; report-arithmetic parenthetical) — report/test-cosmetic. (g) Task-1 Minor 3 error-mapping discretion rows (429/WBI→rate_limited, catch-all→transport_error) — sound evidence-driven choices within the taxonomy requirement; record as decisions, not defects.
  - Source Type: deep-lens: Testing Lens + Standards Lens (consolidated L2 re-judgment)
  - Verification: diff/read/grep anchors as cited; worktree greps confirm each dead import at the cited lines
  - Expected vs observed: expected a recorded Minor to be either escalated (genuine plan-level blocker) or dispositioned with evidence vs observed all seven are lint/coverage-polish/report-only with no plan criterion touched
  - Confidence: High

### ⚪ Unconfirmed

- **[F-004] Real-wheel response-shape claims** — the adapter's normalization assumes `User.get_videos` returns the inner arc/search `data` (`list.vlist` items + `page.count`), that `Video.get_pages` makes no internal `get_info` call, and the exact shapes of the mapped exception classes (`NetworkException.status`, `ResponseCodeException.code`, `WbiRetryTimesExceedException` subclassing). — channel gap: the offline fake seam mirrors these claims by construction, so the diff cannot confirm them; they are implementer wheel-inspection claims (Task-1 report Drift Check). Failure mode if wrong is a bounded `GatewayShapeError`/`GatewayTransportError`. Owned by: Task-3 opt-in live smoke + mandatory QA gate (PM disposition known; listed per zero-residual discipline).
- **[F-005] Live smoke never executed** — `test_live_smoke_single_public_page_for_archive_owner` is opt-in (`BILI_LIVE_SMOKE=1`), requires network, and was intentionally not run. Only the skip path (`1 skipped`, L2-verified) and the loud-fail guard when opted-in with the dist missing (commit `783986a`, statically reviewed) are verified. — channel gap: live-network execution belongs to Plan 3 / QA per PM disposition; not QC-executable.
- **[F-006] Implementer-reported runtime evidence routed to the mandatory QA gate** — (a) full-suite counts (97 / 823 / 840 / 848 passed, 1 skipped): implementer-reported; the L2 reviewers independently re-ran only the sanctioned focused pairs (97-task file, then 122 passed + 1 skipped for the pair — both green); (b) `uv.lock` reproducibility (`uv lock --check` no-op): implementer-reported; structural consistency (pins, hashes, `requires-dist` ↔ pyproject) is diff-verified. — channel gap: suite/lock re-runs are the QA gate's mandated evidence; QC does not execute suites.

## Source Trace

- F-001: Source Type: manual-reasoning + deep-lens: Modularity Lens — Source Reference: `src/bili_asr/services/metadata_ingest.py:199-312`, `src/bili_asr/storage/database.py:290-324,420-450` — Confidence: High
- F-002: Source Type: deep-lens: Contract Lens — Source Reference: `src/bili_asr/sources/bilibili_api_gateway.py:53,118-131,272`, `metadata_ingest.py:241` — Confidence: High (mechanism), Low (likelihood)
- F-003: Source Type: deep-lens: Testing Lens + Standards Lens (L2 re-judgment) — Source Reference: ledger §Minor blocks ×3 + worktree grep anchors per item — Confidence: High
- F-004: Source Type: manual-reasoning (runtime-only claim) — Source Reference: `implementer-task-1-report.md` Drift Check vs `tests/fixtures/fake_bilibili_gateway.py` (seam-by-construction) — Confidence: Low (unverifiable offline by design)
- F-005: Source Type: assignment-ci-note (policy routing) — Source Reference: `tests/test_bilibili_api_gateway.py` live-smoke block; `implementer-task-3-report.md` §3 — Confidence: High (that it is unexecuted; by design)
- F-006: Source Type: assignment-ci-note — Source Reference: implementer reports' test sections; `uv.lock` head + `bili-asr` entry (read in branch-diff) — Confidence: Medium (structural parts verified; run claims not)
- Note: every finding carries `Verification` + `Expected vs observed` — see the Findings entries above.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 3 |
| ⚪ Unconfirmed | 3 |

**Verdict**: Unconfirmed

**Verdict rationale.** The evidence channels for the diff review itself were fully intact (range reproduced, all package files readable, Plan-1 composition sources readable) and the whole-branch diff review is clean: 0 Critical, 0 Warning. The verdict is `Unconfirmed` — not `Approve` — solely because the branch's acceptance evidence includes runtime claims that cannot be verified from the diff and were not executed by design: the opt-in live one-page smoke (owned by Plan 3 / QA), the real-wheel response-shape claims behind the fake seam (bounded by a `shape_error` failure mode if wrong), and the implementer-reported full-suite / `uv lock --check` numbers (all pre-dispositioned by PM to the mandatory QA gate). Per the report-template verdict rules, any ⚪ Unconfirmed entry forces `Unconfirmed`; none of the ⚪ items is a defect finding, and all have named owners and commands.

**Dangling-run adjudication (requested):** accepted as bounded/disclosed (Suggestion F-001) — no plan acceptance criterion requires terminal run rows under abnormal termination; cursor integrity and resumability hold in every window; a storage-contract fix would fall outside this plan's verified "storage unmodified" property. Carry the exception-contract and `runs`-rendering notes into Batch 3 Task 1.

**Recorded-L2-Minor adjudication (requested):** no escalations — all seven recorded Minors re-judged as lint/coverage-polish/report-only (F-003).

**Needs L4/QA verification:** (1) `BILI_LIVE_SMOKE=1` one-page smoke for UID 23191782 (command in implementer-task-3-report §3); (2) full offline suite re-run (`pytest` → expect 848 passed, 1 skipped); (3) `uv lock --check` no-op; (4) optionally, a one-shot wheel inspection of the pinned dist's `get_videos` inner-data shape to close F-004 early (confidence Medium/Low until then).

## Revalidation

- Revalidated: 2026-09-10T12:46:22Z — targeted QC fix-wave re-review, seat qc-specialist (N=2 re-review with qc-specialist-2)
- Fix range: `783986a..3dcc51b` (commit `3dcc51b`, 4 files, +278/−30; base = originally reviewed implementation head `783986a`)
- Inputs: this initial report; `review/qc-consolidated.md` (gate Request Changes; W1 + S-fix-1…8 dispositions; U1–U4 QA routings); `implementer-qc-fix-1-report.md` (claims treated as unverified until diff-checked); `review/fix-1-diff.md` (read once); targeted read-only worktree reads/greps for anchor spot-checks
- Analysis methods: diff review of `fix-1-diff.md`, read, grep — no test/build/lint runs, no git re-runs, no worktree mutation, no commits (branch policy honored)

### Per-finding verification

| ID | Initial | Revalidation result | Evidence |
|----|---------|---------------------|----------|
| F-002 (→ consolidated W1) | 🟢 Suggestion | **Resolved** (fixed + verified) | Diff + worktree anchors below |
| F-001 | 🟢 Suggestion | Closed by disposition — accepted as bounded design limit; carried to Batch 3 (C2 stale-run sweep / C5 exit mapping) | `qc-consolidated.md` §Accepted-as-bounded + §Carried-to-Batch-3; no code change required or made |
| F-003 | 🟢 Suggestion | Closed by disposition — code-actionable parts implemented as S-fix-1/2/6 (verified); remainder accepted-with-rationale (prefix assertion, Task-1 mapping rows, Task-2 cosmetics) or covered downstream (cross-run duplicate flavor → Batch-3 E2E) | `qc-consolidated.md` §Suggestions; S-fix-1/2/6 anchors below |
| F-004 | ⚪ | Open — unchanged routing (mandatory QA gate); slightly extended by S-fix-4: the new identity anchor adds one real-wheel shape claim (detail body carries a top-level `bvid`), bounded failure mode (`GatewayShapeError` → failed page), same class as F-004 | See ⚪ note below |
| F-005 | ⚪ | Open — unchanged routing (QA gate owns live-smoke execution); still opt-in-skipped, never executed | `fix-1-diff.md` contains no live-smoke hunks; implementer reports `1 skipped` in both runs |
| F-006 | ⚪ | Open — unchanged routing (QA gate owns suite re-run + `uv lock --check`); implementer-reported numbers updated and internally consistent (122→131 focused +1 skipped, 848→857 full +1 skipped = baseline + 9 new tests) | Implementer report §Tests; counts consistent, still implementer-reported |

**F-002 → W1 — RESOLVED, verified from the diff and worktree anchors:**

- `_normalize_video_summary_item` now enforces the BV pattern as its **first** scalar check (before title/owner): `if not isinstance(bvid, str) or _BVID_PATTERN.fullmatch(bvid) is None: raise GatewayShapeError(detail="video item has no valid bvid")` — message honest for both missing and malformed shapes. `_BVID_PATTERN` is the same `^BV[a-zA-Z0-9]{10}$` object the parts boundary uses (verified at `bilibili_api_gateway.py:52,123,274` — summary normalization line 123 is the new use, parts boundary line 274 pre-existing).
- **Both aid paths symmetric:** the check sits at page-boundary normalization, aid-agnostic; every vlist item is pattern-checked before `get_completed_video_summary` or `get_video_parts` can consume the id. Adapter test `test_get_user_video_page_rejects_malformed_upstream_bvid` parametrizes `("BV1SHORT", 111) / ("BV1SHORT", None) / ("av170001", 111)` → `GatewayShapeError` code `shape_error`, "bvid" in the bounded message, exactly one upstream call (`user.get_videos(pn=1, ps=100)`).
- **Ingestor end-to-end, both aid flavors** (`test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_cursor`): page 1 collects `limited`; resume page 2 carries the malformed bvid → run `failed` with `error_code="shape_error"`, page row `(2, "failed", "shape_error")`, terminal run row with `finished_at`, zero new payload rows (1 video / 1 part / 1 discovery — all from page 1), prior cursor preserved byte-for-byte (`repository.read_cursor(MID) == cursor_before`), and `script.calls == calls_after_first + ["user.get_videos(pn=2, ps=100)"]` — **the malformed id never reached the parts or detail fetches**.
- Bounded-failure contract intact: both fetch loops (completion + parts) sit inside the single `try` catching `GatewayError` (`metadata_ingest.py:227-247`); the implementer's reported red mode — raw `ValueError` escaping `collect_user_pages` from `get_video_parts` on the aid-carrying path — matches exactly the mechanism F-002 described.
- The genuine-caller-argument contract is preserved: `get_video_parts`' malformed-caller-bvid raw `ValueError` test is unchanged (absent from the diff); post-W1 the ingestor can no longer route an upstream-shaped malformed bvid into that path (the page boundary rejects first). Exactly the fix the consolidated table prescribed (one-line + tests, no ingestor catch-widening).

**Fold-in dispositions (S-fix-1…8) — spot-checked per the consolidated table; detailed re-verification belongs to the seats that raised them:**

- S-fix-1: all four dead imports removed (grep-verified: no `sqlite3`/`GatewayShapeError` left in `test_metadata_ingest.py`; `FakeApiException` gone from the gateway tests; `UserVideoPage` gone from `metadata_ingest.py`); `_page` helper dead `owner_mid` param + dead `mid` local removed, docstring corrected (`_summary`'s `owner_mid` kept — used by the D3 foreign-owner test); the two dead `first =` assignments removed, both remaining ones genuinely consumed (`assert first.outcome == "limited"` at lines 777/879). ✅
- S-fix-2: unreachable `except GatewayError: raise` removed from `_await_upstream` (chain now ends NetworkException → … → ApiException → Exception → `GatewayTransportError`); the implementer's unreachability reasoning is sound (wrapped lambdas call only package objects; application `GatewayError` classes live in `bili_asr.sources.models`, outside the package's reach; no seam test scripts one); no regression — scripted non-`GatewayError` exceptions map through `except Exception` exactly as before. Dead `GatewayError` import removed (grep: zero references left in the adapter). ✅
- S-fix-3: bvid-keyed `completed_by_video` dedup mirrors the existing parts-dedup; `summaries` keeps one entry per page item, so discovery `source_position` enumeration and entity upsert coverage are unchanged; test pins one completion call for two identical aid-less entries (`completion_calls == ["BV1DUPLICATE"]`). ✅
- S-fix-4: identity anchor `detail_bvid == summary.bvid` after the owner-mid check (`bilibili_api_gateway.py:230-232`), docstring updated. The two disclosed fixture adjustments verified sound: `test_bilibili_api_gateway_run_persists_normalized_rows` page item and detail both `BV1SEAMRUNAA` (lines 657/662); `…no_upstream_payload_markers` both `BV1SEAMLEAKS` (721/734) with the no-leak scan still proving the row persists. Pre-fix these fabricated details named a different video than the page item — exactly what the new anchor correctly rejects; each test's original assertions (normalized rows / no-leak evidence) are intact. ✅
- S-fix-5: `_record_collected_page` docstring documents last-wins `(run_id, page_number, bvid)`; test pins `{"BV1DUPPOS": 2, "BV1INTERVAL": 1}` — distinctly last-wins, not first-wins; behavior unchanged. ✅
- S-fix-6: version test mocks the installed distribution as `"9.9.9"` ≠ pinned `"17.4.2"` and asserts precedence — the installed branch is now provable, not the constant. ✅
- S-fix-7: parts-stage failure ingestor test — bounded failure with zero payload rows, `read_cursor is None`, exactly one parts call, terminal run row with `finished_at`. ✅
- S-fix-8: `:memory:` connection in `test_collect_arguments_are_validated` opened once per case, closed in `try/finally`. ✅

### Regression lens (fix diff)

- The fix diff touches exactly 4 files (`sources/bilibili_api_gateway.py`, `services/metadata_ingest.py`, and the two test files). **No `storage/*`, `pyproject.toml`, or `uv.lock` hunks** → Plan-1 canonical composition unchanged; the verified storage-unmodified property holds; dependency surface untouched.
- Bounded-failure contract intact and now symmetric: the fetch phase still completes entirely before any page transaction opens; `_record_failed_page` (failure path writes no cursor) untouched; the `except GatewayError` catch in the page loop unchanged.
- D1 (non-speculative `get_info`) and D3 (owner boundary) invariants unchanged — the D3 foreign-owner tests and `_normalize_video_summary_item`'s owner check are untouched; W1 adds the bvid shape check ahead of them in the same function.
- Offline-only intact: the live smoke is still opt-in-skipped (untouched; no networked test in the diff); implementer reports `1 skipped` in both the focused run (`131 passed, 1 skipped`) and the full run (`857 passed, 1 skipped`) — counts internally consistent with the 9 new tests on the L2-verified baselines (122/848). Counts remain implementer-reported → F-006.
- Zero-residual honored: every hunk maps to W1 or S-fix-1…8; out-of-scope items (dangling-`running` windows, `page_limit` bounding, `risk_interrupted` cursor producer, display-name capability, non-gateway-exception exit mapping) untouched per the consolidated carry list (C1–C6).

### Updated severity counts (revalidation snapshot; open findings)

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 0 (initial F-001/F-002/F-003 all closed: F-002 fixed + verified; F-001/F-003 dispositioned per consolidated) |
| ⚪ Unconfirmed | 3 (F-004, F-005, F-006 — unchanged PM-pre-dispositioned QA-gate routings) |

**Verdict**: Unconfirmed

**Revalidation verdict rationale.** The fix wave is verified clean in this seat's scope: consolidated W1 (= my F-002) is resolved exactly as prescribed — the BV pattern now guards the summary normalization boundary, both aid paths are symmetric and bounded, the malformed id provably never reaches parts/detail, and the prior cursor is preserved byte-for-byte; all eight fold-in dispositions landed with anchors verified; the regression lens found no deviation (storage/dependencies untouched, bounded-failure contract intact, offline-only intact, the two disclosed fixture adjustments are sound corrections of cross-video fixture details). No new Critical/Warning/Suggestion emerged.

The verdict remains **`Unconfirmed`** — per the template rule ("Any `Unconfirmed` finding → verdict `Unconfirmed`, never `Approve`"), the three ⚪ entries are still open at this moment: F-004/F-005/F-006 are the same PM-pre-dispositioned runtime-evidence routings (real-wheel shape claims, live-smoke execution, full-suite + `uv lock --check` re-runs) that the consolidated gate explicitly sequences to the immediate mandatory QA gate. Nothing in the fix wave could close them, and nothing in the fix wave invalidated them. This is the same routed-evidence-only effect the consolidated gate already characterized — not a defect signal, and explicitly **not** Request Changes: 0 Critical, 0 Warning, 0 open Suggestions in this seat's scope. Once the QA gate closes U1–U4 with fresh evidence, this seat has no remaining objection to plan-level Approve.

**Needs L4/QA verification (updated):** (1) full offline suite re-run (implementer reports 857 passed, 1 skipped); (2) `uv lock --check` no-op; (3) `BILI_LIVE_SMOKE=1` one-page smoke for UID 23191782 (command in implementer-task-3-report §3); (4) one-shot wheel inspection of the pinned dist — now also covering the S-fix-4 identity anchor's assumption that the real `get_info` body carries a top-level `bvid` (bounded failure mode: `GatewayShapeError` → failed page, same class as F-004).
