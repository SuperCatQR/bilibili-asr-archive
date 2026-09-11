# SDD Progress — 20260909-bilibili-api-ingestion

Task 1: complete (`e62280a..dfb66ba`, review Approved — Critical 0 / Important 0 / Minor 3)

- Implementer commit: `dfb66ba feat(sources): add pinned bilibili-api gateway boundary`
- Task reviewer: `review/task-1-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: focused `97 passed in 0.35s`; full offline suite `823 passed in 40.66s`
  (726 baseline + 97 new; fake package seam, zero network); `git diff --check` clean
- Scope: pyproject pin + uv.lock + sources/ package (DTOs, protocol, taxonomy, adapter) + offline tests;
  Plan-1 storage untouched; control-checkout prototypes not imported
- PM adjudication of implementer decisions D1–D3 (recorded in report + verified by reviewer):
  D1 accepted — 4th protocol method `get_completed_video_summary` (spec Required-upstream-calls #2
  requires get_info capability at the gateway boundary; services consume protocol only; ingestor decides when);
  D2 accepted — canonical per-class codes match spec taxonomy verbatim; D3 accepted — transitive part
  ownership enforced ingestor-side (adapter signature carries no owner); **Task 2 must preserve the
  ownership invariant; Task 3 asserts it end-to-end**.
- Reviewer ⚠️ items dispositioned by PM: real-package wheel response-shape claims → covered by Task 3
  live/wheel smoke scope; `get_package_version` installed-vs-pinned precedence → benign under the pin
  (coincide; diverge only on mis-config); live one-page smoke → Task 3 scope.

## Minor (for plan QC) — Task 1 (code-reviewer)

1. Unreachable `except GatewayError: raise` in `_await_upstream` (`sources/bilibili_api_gateway.py`).
2. Version test mocks installed distribution with the same `17.4.2` as the pinned fallback —
   installed branch indistinguishable from fallback in the test.
3. Three error-mapping rows are implementer discretion within the taxonomy requirement
   (429/WBI-retry→rate_limited, catch-all→transport_error) — decisions, not spec-verbatim.

## Next

Task 2: resumable normalized metadata ingestion (services/metadata_ingest.py; consumes protocol +
Plan-1 repository; preserve D3 ownership invariant; record_page canonical forms from Plan 1).

## Task 1 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Implementer decisions D1–D3 adjudicated by PM (accepted; D1/D3 constraints carried to Task 2)
- [x] Ready to proceed to Task 2

## End of Task 1

Task 2: complete (`dfb66ba..0c2c379`, review Approved — Critical 0 / Important 0 / Minor 5)

- Implementer commit: `0c2c379 feat(services): add resumable normalized metadata ingestor`
- Task reviewer: `review/task-2-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: focused `17 passed` (red 11 failed/5 passed first — root-caused); full offline
  suite `840 passed in 41.62s` (823 baseline + 17 new); neighbors 147 passed; `git diff --check` clean
- Scope: services/ package (`MetadataIngestor`, `IngestionRunResult`) + tests only; storage/database.py
  NOT modified (verified: zero hunks — everything composes Plan-1 canonical forms)
- PM disposition of reviewer ⚠️ items: full-suite/neighbor counts implementer-reported → deferred to
  the mandatory QA gate re-run; commit subject/cleanliness verified by PM at package construction
  (worktree clean, commit 0c2c379); live one-page smoke → Task 3 scope (tracked in its checklist).
- Implementer decisions verified by reviewer: D3 ingestor-side (zero parts calls on foreign owner),
  D1 non-speculative completion, byte-for-byte cursor preservation, honest outcome taxonomy incl.
  empty-page-at-limit edge, display_name=str(mid) isolated helper.

## Minor (for plan QC) — Task 2 (code-reviewer)

1. Unused imports (metadata_ingest.py).
2. Dead `owner_mid` param + misleading docstring in the test `_page` helper; unused `first` locals.
3. Report-arithmetic parenthetical error (cosmetic).
4. Disclosed dangling-`running`-run windows for PM disposition (run left `running` when pages are
   never attempted / between failures — bounded evidence semantics).
5. Unpinned cross-page/cross-run duplicate-discovery flavor (behavior under duplicate
   discovery keys across pages/runs not pinned by a dedicated test).

## Next

Task 3: verify third-party API behavior at the package seam (BASE `0c2c379`).

## Task 2 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Reviewer ⚠️ items dispositioned by PM (QA re-run deferrals + Task 3 routing recorded above)
- [x] Ready to proceed to Task 3

## End of Task 2

Task 3: complete (`0c2c379..783986a`, review Approved — Critical 0 / Important 0 / Minor 3)

- Implementer commits: `6359e7d test(sources): pin package-seam contract evidence and opt-in live smoke`
  + `783986a test(sources): fail loudly when requested live smoke lacks the pinned dist`
- Task reviewer: `review/task-3-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: focused `122 passed, 1 skipped` (reviewer independently re-ran the sanctioned pair;
  matches implementer); full offline suite `848 passed, 1 skipped` (840 baseline + 8 new + 1 skipped
  live smoke, implementer-reported → deferred to the mandatory QA gate re-run); `git diff --check` clean
- Scope: tests + `tests/fixtures/fake_bilibili_gateway.py` only; product source unmodified
- Live smoke recorded for Plan 3 (not executed; skips by default): `BILI_LIVE_SMOKE=1 ... pytest
  tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner -v` —
  bounded to one page (ps=100), tmp SQLite DB, UID 23191782, no credential; loud-fail guard when
  opted-in but dist missing (uv sync guidance).
- PM disposition of reviewer ⚠️ items: full-suite 848 implementer-reported → mandatory QA gate re-run;
  real-network live smoke → owned by Plan 3 / QA (opt-in only, never executed in QC); uv lock
  reproducibility → QA re-runs `uv lock --check` (Task-1 evidence: no-op).

## Minor (for plan QC) — Task 3 (code-reviewer)

1. Dead imports introduced by the refactor: `tests/test_metadata_ingest.py` (`sqlite3`),
   `tests/test_bilibili_api_gateway.py` (`FakeApiException`).
2. Pre-existing unused import `GatewayShapeError` (tests/test_metadata_ingest.py, dead at base).
3. `assert_only_documented_metadata_calls` is prefix-based (negligible exposure — fake seam
   constructs the call strings).

## Next

All 3 tasks complete → branch review package (`e62280a..783986a`) → plan QC tri (N=3) →
QA gate (mandatory, acceptance) → InReview/merge.

## Task 3 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Reviewer ⚠️ items dispositioned by PM (QA re-run deferrals + Plan-3 routing recorded above)
- [x] All plan tasks complete — proceed to plan QC tri

## End of Task 3

## Plan Gate

- [x] All 3 tasks implemented, reviewed (L2 Approved), ledgered
- [x] Plan QC tri (N=3) — initial Unconfirmed/Request Changes/Approve → fix wave (3dcc51b: W1 bvid boundary + 8 fold-ins) → targeted re-review N=2 (seat 2 Approve; seat 1 no open defects) — consolidated: QC converged
- [x] Mandatory QA gate — Approve (review/qa-gate.md): U1 fresh re-runs (131 focused +1 skip / 857 full +1 skip); U2 uv lock --check no-op; U3 live smoke executed (bounded response_error under anonymous anti-bot; failure path verified live); U4 wheel inspection incl. detail bvid; DoD 9/9 mapped
- [x] zero-residual confirmed (no open R#); Batch-3 carries C1–C6 in plan Durable Roadmap
- [x] Serial integration merge — merge commit 5ccc9c80ba315b94e659c23d452a96abce4f47d9 (e62280a..3dcc51b, 10 files +5948) into iteration/iter-2026-09-bilibili-api-sqlite
- [x] Plan Done (PM); execution_lease + integration_merge_lease released

Plan 20260909-bilibili-api-ingestion closed at merge 5ccc9c8. Batch-3 carries: C1 page_limit bounding, C2 stale-run sweep, C3 risk_interrupted cursor decision, C4 display-name capability, C5 non-gateway-exception exit mapping, C6 adapter wiring (import path + BILI_SESSDATA).
