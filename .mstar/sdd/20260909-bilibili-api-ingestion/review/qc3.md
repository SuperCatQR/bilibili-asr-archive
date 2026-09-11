---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260909-bilibili-api-ingestion"
verdict: "Approve"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: deepseek (DeepSeek Harness-managed route; exact model id not exposed to this session)
- Review Perspective: QC seat 3 of 3 — performance / reliability / enforcement-path / ownership-derived-state on the whole-branch SDD diff (L3, plan-level gate; L2 task reviews are inputs, not substitutes)
- Report Timestamp: 2026-09-10

## Scope

- plan_id: 20260909-bilibili-api-ingestion
- Review range / Diff basis: `e62280a..783986a` (merge-base `e62280a` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-bilibili-api-ingestion`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion` (`git rev-parse --show-toplevel`; HEAD = `783986a` contains all 4 in-scope commits `dfb66ba`/`0c2c379`/`6359e7d`/`783986a`; working tree clean)
- Files reviewed: 10 (`pyproject.toml`, `uv.lock`, `sources/{__init__,models,bilibili_api_gateway}.py`, `services/{__init__,metadata_ingest}.py`, `tests/fixtures/fake_bilibili_gateway.py`, `tests/test_bilibili_api_gateway.py`, `tests/test_metadata_ingest.py`; `uv.lock` (generated, +2617) reviewed by entry inspection: `bilibili-api-python==17.4.2` pinned with hash, `requires-dist` mirrors pyproject incl. dev/asr extras, no dependency removals)
- Commit range (if not identical to Review range line, explain): identical — `e62280a..783986a`; diff reproduced via the authoritative review package `review/branch-diff.md` plus read/grep spot-checks against the worktree (per-file line counts match the package stat exactly)
- Analysis methods: git-diff (review package), read, grep, deep-lens reasoning — no test/build/lint runs (L3; runtime proof belongs to implementer evidence and the QA gate)
- Deep review: triggered (S1: +5700 lines / 10 files ≥ both thresholds; S6: diff spans ≥3 module boundaries — `sources/`, `services/`, `tests/`(+fixtures); S3 arguable: new external-integration module absent from `{KNOWLEDGE_DIR}`)
- Lenses applied: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership/Derived-State Lens (QC3 defaults) + Testing Lens, Bounds Lens, Contract Lens, Security/Correctness baseline — findings below cite the lens that produced each; lenses without findings are not listed
- Branch policy honored: read-only review; no commits, no checkout, no push, no worktree mutation; no subagents dispatched (delegation forbidden); only this report file written

## Whole-branch spec compliance (primary spec + plan Global Constraints)

| # | Constraint (spec + plan) | Verdict | Diff evidence |
|---|--------------------------|---------|---------------|
| 1 | Pin `bilibili-api-python==17.4.2`; version exposed in run metadata; no credentials/raw bodies persisted | ✅ | `pyproject.toml` adds exactly one dep line; `uv.lock` pins 17.4.2 (hash recorded); `get_package_version()` (`bilibili_api_gateway.py:297-303`) feeds `IngestionRunRecord.source_version` (`metadata_ingest.py:208,250`); nothing sensitive in run rows |
| 2 | Only `sources/bilibili_api_gateway.py` imports `bilibili_api`; services consume protocol/DTOs | ✅ | Grep: zero `bilibili_api` references in `services/` and `sources/` outside the adapter; durable AST guard scans all of `src/bili_asr` recursively and asserts the adapter import set equals the allowed metadata surface exactly (`test_bilibili_api_gateway.py:203-236`) |
| 3 | One bounded page per gateway call; cursor advances only after page transaction commits | ✅ | `PAGE_SIZE=100` passed to `get_videos(pn, ps)` per call; cursor is written only inside the repository's committed `record_page` transaction (`_record_collected_page` → `cursor=next_page+1`, state `ready`/`limited`); fetch failures open no page transaction at all (fetch phase precedes any write) |
| 4 | One-based → zero-based `page_index`; `work_id` only at view boundary | ✅ | `page_index = api_page - 1` with one-based ≥1 enforced first (`bilibili_api_gateway.py:712-731`); ingestor never touches page indexes; `work_id` asserted only via `list_pending_parts()` view |
| 5 | No subtitle/playback/audio/ASR/export API calls | ✅ | AST token scan over adapter attribute names with positive control; fake seam structurally exposes only `Credential`/`User.get_videos`/`Video.get_info`/`get_pages` + exception taxonomy — silent use of other package APIs fails at attribute/import time |
| 6 | Bounded scalar error codes; raw text/URLs/cookies/JSON process-local | ✅ | `GatewayError.code` validated through Plan-1 `validate_error_code` at construction (pattern `^[A-Za-z0-9_.:-]+$`, ≤64 — all six codes pass); messages carry class name + code + operation/field only; exceptions chain upstream via `from exc` (chain stays in-process); sentinel scans cover persisted rows (every table/view via `sqlite_master`), run-result repr/str, and `caplog.text` |
| 7 | SESSDATA from `BILI_SESSDATA` or CLI value, never serialized/logged/returned | ✅ (this branch's surface) | Adapter takes `sessdata` only via constructor and passes it solely to `Credential(sessdata=...)`; grep: `sessdata` appears nowhere in `sources/`/`services/` outside the adapter constructor; env/CLI wiring is Batch 3 scope (see Contract-readiness note below) |
| 8 | Display labels only; no metadata history or full upstream documents | ✅ | Current-state upserts only (`ON CONFLICT DO UPDATE`); `display_name=str(mid)` isolated helper; DTOs carry scalars only — unknown payload keys provably dropped (sentinel tests) |
| 9 | No network in fake-gateway tests | ✅ | Fake `bilibili_api` installed on `sys.modules`; `FakeGateway` is a plain scripted double; only networked test is the opt-in live smoke (`BILI_LIVE_SMOKE=1`) |
| 10 | Ingestion outcomes / idempotency / failure rollback (plan Task-2 items) | ✅ | Outcomes `complete`/`limited`/`risk_interrupted`/`failed` with honest `limited` semantics (empty-page-at-limit edge pinned); entity upserts on Plan-1 keys; failure path = no-payload `record_page` → `_record_failed_page` atomically persists page evidence + run failure transition (verified against `database.py:419-457`); prior cursor preserved byte-for-byte (asserted via `CursorRecord` equality) |

Whole-branch integration checks this seat added beyond L2: (a) the ingestor's skip of `finish_run` for `outcome == "failed"` is correct against the Plan-1 repository — `_record_failed_page` transitions the run inside the failure transaction, and `finish_run` would raise on a terminal run; (b) the `risk_interrupted` two-transaction sequence (page row, then `finish_run`) is exactly the repository's documented commit matrix — no competing transaction is opened by the ingestor; (c) cross-task invariants D1 (non-speculative `get_info`) and D3 (ownership before parts/detail) hold end-to-end at the seam with negative assertions (zero calls recorded).

## Findings

### 🔴 Critical

None.

### 🟡 Warning

None.

### 🟢 Suggestion

- [F-001] With `page_limit=None` the page loop is unbounded: termination relies solely on the upstream returning an empty page past the collection end; a pathological upstream pagination behavior (e.g., an endpoint cap that keeps returning a non-empty page for increasing `pn`) would loop indefinitely, growing discovery/entity writes without bound. -> Plan 3's CLI should bound full-collection runs (`page_limit`) as its default policy, or the ingestor could add a defensive stop keyed on `observed_total`; no code change required to satisfy the current spec (termination = first empty page is the spec-defined contract).
  - Source Type: deep-lens: Reliability Lens
  - Verification: diff/read anchor `services/metadata_ingest.py:264-333` — `while True` exits only on `GatewayError`, empty page, or `limit_reached`; no page cap when `page_limit=None`
  - Expected vs observed: expected a run that terminates (or is explicitly bounded) under all upstream pagination behaviors; observed termination depends on documented upstream "empty vlist past the end" behavior that the offline seam cannot falsify
  - Confidence: Medium

- [F-002] No ingestor-level test drives a parts-stage failure (page fetch succeeds, `get_video_parts` raises a `GatewayError`). The fetch-phase `try` block is exercised only via page-level and summary-level failures, so "a failure after a partial fetch persists nothing" is pinned structurally but not end-to-end, although `FakeGateway._scripted` supports scripting an exception on parts. -> Optional strengthening: script `script_parts(bvid, GatewayTransportError(...))` in one test and assert zero rows/cursor preserved.
  - Source Type: deep-lens: Testing Lens
  - Verification: grep anchor `tests/test_metadata_ingest.py:120-483` — every `script_parts` call receives part tuples; both failure tests script errors at the page level (`script_page(2, Gateway...Error)`)
  - Expected vs observed: expected the parts-fetch failure path to have an end-to-end test at ingestor level; observed coverage is structural (fetch phase precedes any transaction) plus page-level equivalents
  - Confidence: High

- [F-003] Dead-code set accumulated across tasks (lint-level, recurring pattern — dead imports appeared at every task boundary): `metadata_ingest.py:29` `UserVideoPage` unused; `tests/test_metadata_ingest.py` `sqlite3` (added by Task 3, zero references) and `GatewayShapeError` (dead since Task 2); `tests/test_bilibili_api_gateway.py` `FakeApiException` unused after the fixture refactor; test-local dead params/locals (`_page`'s `owner_mid` + misleading docstring, `first` locals in the failure tests). -> Fold into the next fix dispatch on this branch if one opens for any other reason; do not open a dedicated round.
  - Source Type: manual-reasoning (re-judged from L2 ledger Minors against the diff)
  - Verification: diff/read anchor — imports present but unreferenced in the branch diff; `_page` helper builds `UserVideoPage(mid=MID)` regardless of `owner_mid`
  - Expected vs observed: expected imports/params to reflect actual use; observed a small dead-code set with no behavior impact
  - Confidence: High

- [F-004] `except GatewayError: raise` in `_await_upstream` (`bilibili_api_gateway.py:876-877`) is unreachable in production (nothing inside the wrapped upstream call can raise an application `GatewayError`); reachable only if a scripted double raises a `GatewayError` inside `call()`. -> Drop per Simplicity First, or keep deliberately as a re-raise guard for future wrapped calls; non-blocking either way.
  - Source Type: manual-reasoning (re-judged L2 Task-1 Minor 1)
  - Verification: diff anchor — the three wrapped lambdas call package objects only; normalization happens outside `_await_upstream`
  - Expected vs observed: expected exception mapping to contain no dead branches; observed one defensive branch that cannot fire under real upstream calls
  - Confidence: High

- [F-005] `test_package_version_reports_installed_distribution` mocks the installed version as the same `"17.4.2"` as the pinned fallback, so the test would also pass if `get_package_version` always returned the constant. -> Use a distinct mocked value to prove the installed-distribution branch and pin the precedence semantic (PM-dispositioned benign under the pin; divergence only in a mis-configured environment).
  - Source Type: manual-reasoning (re-judged L2 Task-1 Minor 2)
  - Verification: diff anchor `tests/test_bilibili_api_gateway.py:2086-2094` vs `PINNED_PACKAGE_VERSION = "17.4.2"`
  - Expected vs observed: expected the installed branch to be distinguishable from the fallback; observed identical values in both branches of the test
  - Confidence: High

- [F-006] `assert_only_documented_metadata_calls` uses prefix matching (`call.startswith(DOCUMENTED_METADATA_CALLS)`) — a hypothetical recorded name like `user.get_videos_xxx` would pass. Exposure is negligible because the fake seam itself constructs the call strings. -> Optional exact-name tightening if the recorded-name format ever changes.
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: diff anchor `tests/fixtures/fake_bilibili_gateway.py:1414-1422`
  - Expected vs observed: expected the documented-surface scanner to match whole call names; observed prefix-based matching with no realistic bypass path in the seam
  - Confidence: Medium

- [F-007] Live-smoke hygiene token `"bilivideo.com"` scans lowercased persisted-row text; a video title legitimately containing the string would false-fail the smoke. Negligible likelihood; note only.
  - Source Type: manual-reasoning
  - Verification: diff anchor `tests/test_bilibili_api_gateway.py:2337-2339` (token list) and `2386-2389` (scan)
  - Expected vs observed: expected hygiene tokens to be unambiguous leak markers; observed one token that could in principle appear in legitimate metadata
  - Confidence: Low

- [F-008] `test_collect_arguments_are_validated` opens a `:memory:` connection per parametrized case and never closes it (validation raises before any repository use). Lint-level test hygiene.
  - Source Type: manual-reasoning
  - Verification: diff anchor `tests/test_metadata_ingest.py:2923-2927`
  - Expected vs observed: expected test resources to be closed or omitted when unused; observed unclosed per-case connections (validation precedes any DB use, so no functional impact)
  - Confidence: High

- [F-009] Dangling `running`-run windows (already disclosed; re-judged non-blocking): (a) a non-gateway exception after `start_run` (e.g., repository write error mid-page) leaves the run row `running` with no terminal transition; (b) the `risk_interrupted` finish spans two transactions (page row commit, then `finish_run`), so a crash between them leaves the run `running`. Both are inherent to the Plan-1 commit matrix, leave SQLite consistent and resumable, and never regress a terminal outcome (`_record_failed_page`/`finish_run` guards). -> Accept as bounded evidence semantics; Plan 3's CLI should surface stale `running` runs in its status view.
  - Source Type: deep-lens: Ownership/Derived-State Lens
  - Verification: diff/read anchor `services/metadata_ingest.py:241-359` + `database.py:297-457` (terminal-run guards)
  - Expected vs observed: expected every started run to reach a terminal outcome even on non-gateway failures; observed two bounded windows where the run row stays `running` (documented in the implementer report and ledger)
  - Confidence: High

- [F-010] Cross-page/cross-run duplicate-discovery idempotency is structurally sound (entity upsert keys + discovery PK `(run_id, page_number, bvid)` + `COALESCE` aid backfill) but is not pinned by a dedicated test for the same bvid discovered on two pages of one run (or re-discovered across runs). -> Optional coverage polish.
  - Source Type: deep-lens: Testing Lens
  - Verification: diff/read anchor — `test_duplicate_summaries_in_one_page_collapse_into_single_rows` covers within-page duplicates only; `test_page_limit_ends_run_as_limited_and_resume_completes` covers separate runs with distinct pages
  - Expected vs observed: expected the idempotency flavor (same bvid across pages/runs → single entity row, per-run/page discovery evidence) to have a direct pin; observed structural argument only
  - Confidence: Medium

### ⚪ Unconfirmed

- [F-011] Live smoke never executed against the real network (outcome, row shapes, hygiene scan under real payloads remain runtime claims; default-run skip path and the `783986a` loud-fail guard verified statically) — channel gap: runtime/network execution is outside the L3 channel by assignment; owned by Plan 3 / QA per recorded PM disposition (progress.md Task 3).
- [F-012] Real-wheel behavior claims mirrored by the offline seam (inner arc/search `data` shape; `get_pages` makes no internal `get_info`; exception class hierarchy and attribute surface, incl. `NetworkException.status` and `WbiRetryTimesExceedException` mapping position) — channel gap: requires the pinned wheel at runtime; the fake seam mirrors the claims by construction, so the diff cannot falsify them; a wrong claim surfaces quickly as a bounded `GatewayShapeError`/mapping crash in the Plan-3 live smoke.
- [F-013] Implementer-reported pass counts (focused 122 passed + 1 skipped; full suite 848 passed + 1 skipped; neighbors 147 passed; `git diff --check` clean; `uv lock --check` no-op) — channel gap: test/lock execution is forbidden for this seat; QA re-runs per recorded PM disposition.

## Source Trace

| Finding ID | Source Type | Source Reference | Confidence |
|---|---|---|---|
| F-001 | deep-lens: Reliability Lens | `src/bili_asr/services/metadata_ingest.py:264-333` (while-loop exits) | Medium |
| F-002 | deep-lens: Testing Lens | `tests/test_metadata_ingest.py:120-483` (`script_parts` uses) | High |
| F-003 | manual-reasoning | `metadata_ingest.py:29`; `tests/test_metadata_ingest.py:17,29,84-92`; `tests/test_bilibili_api_gateway.py:47` | High |
| F-004 | manual-reasoning | `src/bili_asr/sources/bilibili_api_gateway.py:876-877` | High |
| F-005 | manual-reasoning | `tests/test_bilibili_api_gateway.py:2086-2094` vs `:1551` | High |
| F-006 | deep-lens: Enforcement-Path Lens | `tests/fixtures/fake_bilibili_gateway.py:1414-1422` | Medium |
| F-007 | manual-reasoning | `tests/test_bilibili_api_gateway.py:2337-2339,2386-2389` | Low |
| F-008 | manual-reasoning | `tests/test_metadata_ingest.py:2923-2927` | High |
| F-009 | deep-lens: Ownership/Derived-State Lens | `services/metadata_ingest.py:241-359` + `storage/database.py:297-457` | High |
| F-010 | deep-lens: Testing Lens | `tests/test_metadata_ingest.py:229-247` vs PK/upsert keys | Medium |
| F-011 | manual-reasoning / assignment-ci-note | `tests/test_bilibili_api_gateway.py:2346-2404`; progress.md Task 3 | High (routing) |
| F-012 | manual-reasoning | `src/bili_asr/sources/bilibili_api_gateway.py:560-575,846-879`; fixture mirrors | Medium |
| F-013 | assignment-ci-note | implementer reports §Tests; progress.md ledger | High (routing) |

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 10 |
| ⚪ Unconfirmed | 3 |

**Verdict**: Approve

**Verdict rationale.** All whole-branch spec-compliance checks (table above) pass on the diff; my QC3-lens review (performance, reliability, enforcement path, ownership/derived state, bounds, contract) found no Critical or Warning finding: the ingestor composes the Plan-1 repository without competing transactions, failure paths persist only validated scalar codes, the credential/raw-payload boundary has both structural (no serialization surface, no logging) and behavioral (non-vacuous sentinel scans over every persisted table/view, run result, and logs) enforcement, and the import/method surface is pinned by AST + structural-seam tests that fail loudly on drift. All findings above are Suggestions (lint-level, coverage polish, or forward-routing notes) and every evidence channel of this review was intact.

The ⚪ items are runtime-proof routings pre-dispositioned by PM (live smoke → Plan 3/QA; pass counts, `git diff --check`, `uv lock --check` → QA re-run; wheel-shape claims → falsified or confirmed by the Plan-3 live smoke) — not new unresolved channel failures within this seat's diff scope, so they do not degrade the verdict below Approve; if the PM prefers the strict template reading, the verdict degrades to Unconfirmed solely on those routed items. **Needs L4/QA verification:** the three ⚪ items.

**Contract readiness for Batch 3 (`20260909-metadata-cli-smoke`)** — sufficient and unambiguous; no gaps that would force the CLI plan to guess:

1. `BilibiliGateway` protocol: 4 methods including the PM-adjudicated `get_completed_video_summary(summary) -> VideoSummary` (aid-gap fill; short-circuits when aid present) — exported from `bili_asr.sources`; the concrete `BilibiliApiGateway(sessdata=...)` is deliberately NOT re-exported at package level and must be imported from `bili_asr.sources.bilibili_api_gateway` (documented in the `sources/__init__.py` docstring).
2. `MetadataIngestor.collect_user_pages(mid, start_page=None, page_limit=None) -> IngestionRunResult` — semantics fully documented in docstrings: `start_page` overrides (and may move backwards from) the stored cursor; `page_limit=None` means "until empty page" (see F-001 — Plan 3 should default to bounding runs); terminal outcomes `complete`/`limited`/`risk_interrupted`/`failed` with `error_code` carrying the scalar code on the latter two.
3. `IngestionRunResult` field semantics pinned: `page_count` counts page-evidence rows incl. interrupted/failed pages (matches `v_ingestion_run_stats`); `video_count` counts distinct discovered bvids; `part_count` counts distinct `(bvid, page_index)` upserts (no view equivalent — documented); `next_cursor` is the cursor as stored after the run (a `complete` cursor points at the empty page; a `limited` cursor points at the next uncollected page; failure leaves the prior cursor untouched; the `risk_interrupted` cursor state is intentionally unused — documented in the Task-2 report).
4. Live-smoke entry point recorded for Plan 3 (progress.md Task 3 + implementer-task-3-report §3): `BILI_LIVE_SMOKE=1 ... pytest tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner -v` with prerequisites (pinned dist installed via `uv sync`; loud fail with guidance when missing), bounded expectations (one `user.get_videos(pn=1, ps=100)` page for UID 23191782, ≤1 `get_pages` per distinct video + ≤1 `get_info` per aid-less summary, fresh temp SQLite only, no credential, outcome `limited`/`complete` on success, bounded failure → scalar code).
5. Credential wiring note for Plan 3: the adapter accepts `sessdata` as a constructor kwarg only; the plan constraint's `BILI_SESSDATA`-env/CLI source surface does not exist on this branch by design (Batch 3 wires `--sessdata`/env → `BilibiliApiGateway(sessdata=...)`; the old client's `_resolve_sessdata` pattern in `cli.py:765-767` is the established precedent).

**L2 Minor re-judgment (ledger context)**: all 11 ledger Minors re-checked against the diff; none escalates — they map to F-003, F-004, F-005, F-006, F-008, F-009, F-010 above (dead code / coverage polish / disclosed design limits), and the Task-2 "storage/database.py NOT modified" deviation from the plan's Modify list is verified correct (zero hunks; every ingestor need composes existing canonical methods — no genuine gap existed). Disposition of all Suggestion items belongs to PM under the zero-residual policy; this seat reports only.
