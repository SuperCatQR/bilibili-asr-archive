# SDD Progress — 20260909-metadata-cli-smoke

Task 1: complete (`18b6353..849c046`, review Approved — Critical 0 / Important 0 / Minor 5)

- Implementer commit: `849c046 feat(cli): wire metadata commands to sqlite stack` (RETRY after a
  crashed prior attempt; crashed attempt's two files audited, kept/repaired — disclosed in report)
- Task reviewer: `review/task-1-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: focused `31 passed`; full offline suite `854 passed, 1 skipped` (baseline
  857+1 reconciles exactly: 34 superseded legacy tests retired + 31 added); `git diff --check` clean
- Scope: config.py (new), cli.py (metadata commands rewired; 5 fetch-meta-only JSONL helpers deleted),
  tests (new test_metadata_cli.py + legacy test retirement); subtitle/audio/ASR modules untouched
- PM adjudication of implementer decisions: ① accepted — 34 legacy JSONL-contract CLI tests retired/
  rewritten (plan acceptance criterion explicitly anticipates intentional contract changes); arithmetic
  reconciles, no coverage gutting (reviewer-verified); ② accepted — pyproject.toml audited but NOT edited
  (Plans 1-2 landed schema package-data + dependency pin; isolated-install tests prove packaging; brief's
  "Modify" list is a superset expectation, actual edits follow requirements)
- PM disposition of reviewer ⚠️ items: full-suite/isolated-install evidence implementer-reported →
  deferred to the mandatory QA gate re-run; worktree cleanliness → verified by PM at package construction;
  spec exit-2 clause "after bounded retry" is stale vs Plan-2 fail-fast gateway → carried to plan QC as a
  spec-note candidate; live-smoke bound → Task 3 scope.

## Minor (for plan QC) — Task 1 (code-reviewer)

1. Stale help text: cli.py status "manifest status summary" / runs "from the ledger" (behavior now SQLite-only).
2. CLI-layer raw SQL (`_run_error_codes`, status counts) bypasses the repository boundary.
3. config.py duplicates storage's private `_ARCHIVE_DATABASE_NAME` (comment-guarded drift risk, fail-safe direction).
4. Blank `--sessdata ""` falls through to `BILI_SESSDATA` (docstring "blank = anonymous" only holds when env also blank).
5. "collected N page(s)" wording prints before the failure line on failed runs (inline outcome= keeps it honest).

## Next

Task 2: offline metadata E2E verification (BASE `849c046`).

## Task 1 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Implementer decisions ①② adjudicated by PM (both accepted)
- [x] Reviewer ⚠️ items dispositioned by PM (QA re-run deferrals + spec-note carry recorded above)
- [x] Ready to proceed to Task 2

## End of Task 1

Task 2: complete (`849c046..cf490ff`, review Approved — Critical 0 / Important 0 / Minor 2)

- Implementer commit: `cf490ff test(cli): add offline metadata e2e verification`
- Task reviewer: `review/task-2-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: focused E2E `3 passed in 0.34s`; fixture-consumer regression `183 passed, 1 skipped`;
  full offline suite `857 passed, 1 skipped` (854 Task-1 baseline + 3 new); `git diff --check` clean
- Scope: tests/test_metadata_e2e.py (new, 3 full-stack tests) + additive fixture scripting capability
  (`script_parts_by_bvid`); product source unchanged; test_metadata_ingest.py untouched (PM-accepted)
- PM disposition of reviewer ⚠️ items: live-smoke acceptance evidence → Task 3 + QA gate (tracked);
  implementer test counts → deferred to the mandatory QA gate re-run; `observed_total` fake/live semantic
  note (fake reports per-page count; live records upstream global total; completion keys off empty item
  list — offline evidence valid) → carry as a docs note for Task 3's `docs/metadata-storage.md`.
- PM disposition of implementer flagged items: run-scoped discovery idempotency pinned per locked
  Plan-1 PK (accepted; zero-new-rows-across-runs structurally impossible without a schema change);
  helper duplication with Task-1's file → plan QC (lint-level).

## Minor (for plan QC) — Task 2 (code-reviewer)

1. Test-local duplication of Task-1 helpers (`LEGACY_SIDECAR_PATHS`, `_ingest_clock`, `_newest_run_id`,
   `_cursor_row`) — deliberate scope-respect; consolidation candidate.
2. Test 2's output leak scan lacks a local non-vacuity assertion (relies on render path pinned by test 1).

## Next

Task 3: bounded live API smoke test + operator notes (BASE `cf490ff`).

## Task 2 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Reviewer ⚠️ items dispositioned by PM (Task-3 routing + QA re-run deferral + docs note recorded above)
- [x] Ready to proceed to Task 3

## End of Task 2

Task 3: complete (`cf490ff..c86daa7`, review Approved — Critical 0 / Important 0 / Minor 3)

- Implementer commit: `c86daa7 test(metadata): add bounded live smoke and operator notes`
- Task reviewer: `review/task-3-review.md` (fresh code-reviewer, Mode A, L2, diff-first)
- Runtime evidence: focused `1 passed, 1 skipped` (reviewer independently re-ran the sanctioned
  command; live smoke skips by default, offline rehearsal passes); full offline suite
  `858 passed, 2 skipped` (857+1 baseline + 1 new test; both skips = Plan-2 + Task-3 opt-in
  live smokes); `git diff --check` clean
- Scope: tests/test_live_metadata_smoke.py (new) + docs/metadata-storage.md (new) + README.md
  (fresh-start section + accuracy fixes for claims made false by Task 1); product source unchanged
- Adjudicated spec reading implemented as stated: anonymous exit-2 (response_error) →
  verified-then-clearly-reasoned skip (documented expected no-credential behavior per Plan-2 QA note);
  credential-in-play or unexpected error → loud fail. Live smoke NOT executed (QA gate owns it).
- PM disposition of reviewer ⚠️ items: opted-in live-network execution → mandatory QA gate (owns it);
  full-suite 858+2 skip implementer-reported → QA re-run; README Workflow status/runs lines predate
  this diff (accurate, not authored here) → no action.

## Minor (for plan QC) — Task 3 (code-reviewer)

1. README.md internal anchor misses the hyphen in `fetch-meta` (won't resolve under GitHub-style slugs; cosmetic).
2. Anonymous-skip branch is broader than the adjudicated response_error instance (skips on any bounded
   anonymous exit-2) — defensible breadth; confirm intended (PM: ACCEPT as safe-by-design).
3. The `complete` sub-branch of `_assert_collected_page_rows` is not exercised by the offline rehearsal
   (only reachable live on an empty page 1); seam could script it (coverage polish).

## Next

All 3 tasks complete → branch review package (`18b6353..c86daa7`) → plan QC tri (N=3) →
QA gate (mandatory; executes the live smoke) → InReview/merge.

## Task 3 Gate

- [x] Implementation committed on assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] Reviewer ⚠️ items dispositioned by PM (live-smoke execution → QA gate; suite re-run deferral)
- [x] All plan tasks complete — proceed to plan QC tri

## End of Task 3

## Plan Gate

- [x] All 3 tasks implemented, reviewed (L2 Approved), ledgered (Task 1 was a retry after a crashed attempt — audited and repaired)
- [x] Plan QC tri (N=3) — 3×Request Changes (docs-contract Warnings deduped to W1+W2) → docs fix wave 1a99751 + PM spec edit → targeted re-review N=3 (seats 2/3 Approve; seat 1 no open defects, ⚪-floor) — consolidated: QC converged
- [x] Mandatory QA gate — Approve (review/qa-gate.md): U1 fresh re-runs exact (861+2 / 38+1); U2 anonymous live bounded-failure path executed live (scalar response_error → clearly-reasoned skip; BILI_SESSDATA unset = explicit live-network blocker, nothing fabricated); U3 isolated-install verified (wheel build → offline install → CLI import → schema.sql present; scratch cleaned); U4 no package side-effects outside temp root; DoD 9/9 mapped
- [x] zero-residual confirmed (no open R#); next-iteration carries in plan Durable Roadmap (TOCTOU remainder, ingestion_runs metadata-scope note, test-helper consolidation polish)
- [x] Serial integration merge — merge commit 1307f924f2b2353a6551c3217063efd7a5bab23a (18b6353..1a99751, 13 files +2509/−1195) into iteration/iter-2026-09-bilibili-api-sqlite
- [x] Plan Done (PM); execution_lease + integration_merge_lease released

Plan 20260909-metadata-cli-smoke closed at merge 1307f92. ALL THREE PLANS DONE — Phase 3 iteration-close next.
