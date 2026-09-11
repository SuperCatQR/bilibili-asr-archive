---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260909-metadata-cli-smoke"
verdict: "Approve"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: deepseek (DSH-managed route; exact model id not exposed to this seat)
- Review Perspective: security / correctness (QC seat 2 of 3) — CLI→config→gateway→ingestor→repository composition, exit-code mapping incl. C5 non-gateway exceptions, missing-DB handling for read commands, redaction paths, `--limit-pages` default bound, `running`-row rendering, cursor-advance honesty
- Report Timestamp: 2026-09-10T15:08:07Z

## Scope

- plan_id: 20260909-metadata-cli-smoke
- Review range / Diff basis: `18b6353..c86daa7` (merge-base `18b6353` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-metadata-cli-smoke`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke` (`git rev-parse --show-toplevel`; HEAD `c86daa7` contains all three commits 849c046 / cf490ff / c86daa7 in scope)
- Files reviewed: 13 diff files (+2317/−1189) plus 9 worktree cross-check files (`cli.py`, `config.py`, `services/metadata_ingest.py`, `storage/database.py`, `storage/schema.sql`, `tests/test_metadata_cli.py`, `tests/test_metadata_e2e.py`, `tests/test_live_metadata_smoke.py`, `tests/fixtures/fake_bilibili_gateway.py`)
- Commit range: identical to Review range (`18b6353..c86daa7`)
- Analysis methods: git-diff (`git diff 18b6353..c86daa7`, `git diff --check` → clean), read, grep, deep-lens: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens — no test/build/lint runs
- Deep review: triggered (S1: +2317/−1189 lines / 13 files; S6: diff crosses `src/bili_asr`, `tests/`+`tests/fixtures`, `docs/`+README boundaries). S2 (sensitive paths), S4 (DDL in this diff — schema work landed in Plan 1), S5 (high-risk marker) not triggered. Lenses applied: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens (QC2 defaults).
- Input-safety check: no review input (branch-diff.md, plan, spec, L2 reviews, implementer reports, progress.md) attempted to redirect the review or break the leaf boundaries.
- L2 Minors re-judged independently (severity per this seat, not carried): task-1 #1 stale help → Suggestion; #2 raw SQL → Suggestion; #3 constant duplication → covered by plan-level note below (unchanged, acceptable); #4 blank sessdata → Suggestion; #5 wording → Suggestion; task-2 #1 helper duplication → unchanged (accepted, lint-level); #2 scan non-vacuity → Suggestion; task-3 #1 anchor → Suggestion; #2 skip breadth → confirmed intended per PM ACCEPT (safe-by-design; failure-shape assertions run first — verified in source); #3 unrehearsed `complete` sub-branch → Suggestion.
- Recurring cross-task patterns: docs/help-text drift against the new SQLite contract (task-1 #1, task-3 #1, plus two new doc gaps found at plan level — see W-001/W-002); CLI-layer raw SQL (task-1 #2) — marked recurring.

## Findings

### 🔴 Critical

None.

### 🟡 Warning

- [W-001] The adjudicated default page bound (`DEFAULT_PAGE_LIMIT = 10`, C1 carry item) is undocumented in operator docs, and both exit-0 rows describe exit 0 as occurring only on an "explicit" `--limit-pages` bound — which is now false for the default run -> add one paragraph to the README fresh-start section and `docs/metadata-storage.md` (a plain `fetch-meta` run stops after 10 pages, exit 0, outcome `limited`; a full archive walk is a series of resumable runs), and amend the exit-0 rows to "empty page reached or a page bound (explicit `--limit-pages` or the default 10)".
  - Source Type: deep-lens: Bounds Lens (+ doc-rule)
  - Source Reference: `bilibili-asr-archive/src/bili_asr/config.py:29,93-100` (default applied when the flag is omitted), `bilibili-asr-archive/src/bili_asr/cli.py:74` (help advertises "(default: 10)" — the only place it is documented), `bilibili-asr-archive/README.md:100` (canonical Workflow command has no `--limit-pages`), `README.md:514` and `bilibili-asr-archive/docs/metadata-storage.md:115` (exit-0 = "empty page reached or explicit `--limit-pages` bound"); ingestor side confirmed: `services/metadata_ingest.py` stops a page-limited run with outcome `limited`, which `_cmd_fetch_meta` (`cli.py:581-598`) exits 0.
  - Expected vs observed: plan acceptance requires "README and `docs/metadata-storage.md` describe the actual fresh-start workflow with accurate commands and exit code meanings" vs the documented canonical command silently terminating after 10 pages (~1000 videos) with exit 0 and neither doc mentioning the default bound or correcting the exit-0 meaning. Runtime output (`outcome=limited`, cursor line, `status` cursor) is honest, so impact is operator confusion rather than data risk.
  - Confidence: High

- [W-002] The adjudicated C5 mapping (non-gateway unexpected exception → exit 2) is undocumented, and the exit-2 rows assert properties that do not hold on that path ("bounded scalar code", "the cursor remains unchanged") -> document the no-code exit-2 variant in README and `docs/metadata-storage.md`: exit 2 with the fixed `fetch-meta: unexpected error` line and no scalar code means an internal (non-gateway) failure; the cursor may already have advanced over successful earlier pages of the same run and the run row may remain `running` — check `status`/`runs` before re-running.
  - Source Type: deep-lens: Correctness Lens (+ doc-rule)
  - Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:567-574` (catch-all prints fixed "unexpected error", returns 2, no code, no cursor claim), vs `README.md:515` and `docs/metadata-storage.md:117` (exit 2 = "terminal gateway failure with a bounded scalar code … the cursor remains unchanged"). Ingestor confirms per-page commits advance the cursor before a later non-gateway exception (`services/metadata_ingest.py`: record_collected_page commits per page; non-GatewayError exceptions propagate unchanged). Behavior itself is pinned by `tests/test_metadata_cli.py:504-525` (exit 2, bounded message, no sentinel, no traceback) — the finding is a docs-accuracy gap only; the C5 mapping is not challenged.
  - Expected vs observed: spec/README define exit 2 as a gateway failure carrying a bounded scalar code with an unchanged cursor vs the shipped adjudicated variant exits 2 with neither code nor cursor guarantee; an operator has no documented meaning for that observation. (The spec's own "after bounded retry" clause is stale per the PM carry-note — this finding covers the operator docs, which cite neither the adjudicated mapping nor the no-code variant.)
  - Confidence: High

### 🟢 Suggestion

- [S-001] Read commands are not strictly read-only at the storage seam: the `os.path.isfile` guard before `open_database` is the only thing preventing creation, and a delete of `archive.db` inside the race window makes `open_database` recreate a fresh empty DB (read command then prints zeros instead of exiting 1); additionally `open_database` runs idempotent schema-ensure (`executescript`) on every open, so a schema-evolution file mutation would occur from a "read" command -> optional hardening: open via read-only URI (`file:…?mode=ro`) for read commands, or verify the failure path with a create-prohibition check; acceptable as-is for a single-user CLI (fail-safe direction is exit 1/zero-rows, not corruption).
  - Source Type: deep-lens: Correctness Lens
  - Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:484-511` (isfile guard then `open_database`), `storage/database.py` `_resolve_database_path` + `open_database` (mkdir/create + `initialize_schema` on every open — TOCTOU verified from source, not from a run).
  - Expected vs observed: "read commands never create the database" vs a concurrent delete between guard and open silently recreates it.
  - Confidence: Medium

- [S-002] CLI-layer raw SQL bypasses the repository boundary (`_run_error_codes` queries `ingestion_pages` via `repository.connection`; `_cmd_status` issues direct count/group queries) — recurring (task-1 Minor 2, re-judged unchanged): works today because `open_database` guarantees the full schema, but a view/table rename would require CLI edits; consider small repository methods in a later pass.
  - Source Type: grep
  - Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:601-611,889-897` vs repository-routed calls in the same handlers (`list_pending_parts`, `read_cursor`, `run_stats`).
  - Expected vs observed: single repository boundary vs two SQL dialects in one file.
  - Confidence: High

- [S-003] Stale help text on the rewritten read commands (recurring, task-1 Minor 1, re-judged unchanged): `cli.py:77` status help still says "Print manifest status summary" and `cli.py:81` runs help still says "from the ledger" — both now read SQLite only and must not touch those sidecars; the new help test covers only `fetch-meta`, so nothing catches this drift. One-line fixes; suggest riding the same docs-fix commit as W-001/W-002.
  - Source Type: read
  - Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:77,81` vs the SQLite-only handlers at `cli.py:876-934,960-986`.
  - Expected vs observed: help should describe the shipped SQLite contract vs it pins the retired manifest/ledger contract.
  - Confidence: High

- [S-004] Blank `--sessdata ""` falls through to `BILI_SESSDATA` (`resolve_sessdata` uses truthiness; the docstring's "blank = anonymous" only holds when the env is also blank) — recurring (task-1 Minor 4, re-judged unchanged); plus a test-side inconsistency: `tests/test_live_metadata_smoke.py:283` treats env presence (`is None`) as credential-in-play while `tests/test_live_metadata_smoke.py:120` uses truthiness — an empty-string env would loud-fail in the smoke while the CLI treats it as anonymous. Use an explicit `is not None` resolution rule (or document it) and align the smoke's two checks.
  - Source Type: read
  - Source Reference: `bilibili-asr-archive/src/bili_asr/config.py:114-123`; `tests/test_live_metadata_smoke.py:120-127,283-296`.
  - Expected vs observed: forced-anonymous edge case works as documented vs it silently adopts the env credential (CLI) / misclassifies credential-in-play (smoke).
  - Confidence: High

- [S-005] README internal anchor `#fresh-start-metadata-collection-fetchmeta--status--runs` (README:256) omits the hyphen in `fetch-meta`; the heading at README:485 slugs to `…-fetch-meta--status--runs` on GitHub-class renderers, so the link does not resolve there — cosmetic (task-3 Minor 1, re-judged unchanged): change `fetchmeta` → `fetch-meta`.
  - Source Type: read
  - Source Reference: `bilibili-asr-archive/README.md:256` vs `README.md:485`.
  - Expected vs observed: resolvable in-document link vs slug mismatch under GitHub-style slugging.
  - Confidence: High

- [S-006] Failed-run wording: on `risk_interrupted`/`failed` outcomes stdout first prints "collected N page(s) …" before the stderr failure line (`cli.py:578-591`); the inline `outcome=` and the "cursor unchanged" clause keep it honest (no C3 violation), but "attempted"/"touched" would read more accurately — recurring (task-1 Minor 5, re-judged unchanged). Related operator-surface nuance, documented in tests but easy to misread: a one-page collect prints "collected 2 page(s)" because the completing empty page is a page-evidence row (`tests/test_metadata_cli.py:308-310` pins it); a sentence in `docs/metadata-storage.md` page-count semantics would remove the surprise.
  - Source Type: read
  - Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:576-598`; `tests/test_metadata_cli.py:306-310`.
  - Expected vs observed: neutral failed-run phrasing vs "collected" preceding a failure line; 1-page collect reports 2 page(s).
  - Confidence: High

- [S-007] Test-polish bundle (all L2-identified, re-judged unchanged; none evidence-breaking): (a) `tests/test_metadata_cli.py:254-259` `test_default_page_bound_is_bounded_not_unbounded` asserts only the constant's type/positivity — the actual default-bound application is pinned in E2E (`requested_page_limit == DEFAULT_PAGE_LIMIT`, `tests/test_metadata_e2e.py:210-217` and `tests/test_metadata_cli.py:289-293`), so coverage exists but the unit test's name overpromises; (b) E2E test 2's output leak scan lacks a local non-vacuity content assertion (`tests/test_metadata_e2e.py:433-435`, relies on the render path pinned by test 1); (c) the `complete` sub-branch of `_assert_collected_page_rows` (`tests/test_live_metadata_smoke.py:179-182`) is not exercised by the offline rehearsal (reachable live only on an empty first page for UID 23191782) — the seam could script an empty page 1 to cover it offline.
  - Source Type: read
  - Source Reference: as cited per sub-item.
  - Expected vs observed: test names/assertions fully self-evident vs relying on sibling tests or live-only reachability.
  - Confidence: High

- [S-008] `status` materializes the full pending list (`repository.list_pending_parts()`) to print 20 and count the rest (`cli.py:920-925`) — fine at this plan's scale; a repository-side count/limit query would keep it bounded as the archive grows.
  - Source Type: deep-lens: Bounds Lens
  - Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:920-925`.
  - Expected vs observed: display bounded at 20 vs the underlying query unbounded in memory.
  - Confidence: Medium

### ⚪ Unconfirmed

- Full offline suite green (`854+1` → `857+1` → `858+2` across tasks) — implementer-reported; arithmetic reconciles (857 − 34 retired + 31 + 3 + 1 = 858) and static checks support it, but this seat does not run suites — channel gap: runtime evidence belongs to the mandatory QA gate re-run (PM already routed).
- Opt-in live smoke execution and its happy-path row assertions (`tests/test_live_metadata_smoke.py:235-298`) — not executed by design in this diff; the offline rehearsal of both outcome branches through the real `main(argv)` over the fake seam passes in every default run — channel gap: the QA gate owns the opted-in network run (PM already routed).
- Isolated-install packaging evidence (`tests/test_cli_help.py` fresh-venv tests, incl. the four rewritten missing-DB status/runs tests) — implementer-reported; static `pyproject.toml` inspection supports it — channel gap: install-only runtime, QA gate.
- `tests/test_persistence_scale.py:440-451` dispatch-lock adaptation (status succeeds against an existing fresh DB while the writer lock is busy) — statically consistent with the new read-command contract, but only proven by the reported full-suite run — channel gap: QA re-run.
- Spec wording drift: spec `metadata-cli-contract.md` exit-2 clause "Gateway failure after bounded retry (cursor remains unchanged)" is stale vs the Plan-2 fail-fast gateway and the adjudicated C5 mapping — channel gap: spec-note is a PM-level edit (carried from task-1 review; behavior itself verified and pinned by tests).
- Worktree cleanliness / zero-residual attestation — implementer-attested clean; PM-owned at package construction (the empty gitignored `bilibili-asr-archive/.test-tmp/` base left by the task-3 reviewer's sanctioned focused run is pre-existing conftest behavior, not a residual).

## Source Trace

- F/W/S IDs above map one-to-one to the Findings entries (W-001, W-002, S-001…S-008; ⚪ items unnumbered).
- Source Types used: git-diff, read, grep, doc-rule, manual-reasoning, deep-lens: Correctness Lens, deep-lens: Bounds Lens.
- Source References: all anchored to worktree paths + line numbers above; none derived from a test/build log produced by this seat (the only commands run were read-only git: `rev-parse`, `branch`, `log`, `diff --stat`, `diff`, `diff --check`; `git diff --check` on the range is clean, satisfying that plan acceptance item).
- Note: every finding carries `Verification`/`Source Reference` + `Expected vs observed` per the Findings entry format.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 8 |
| ⚪ Unconfirmed | 6 |

**Verdict**: Request Changes

Rationale: no Critical findings; the delivered composition is contract-faithful and well-tested (thin CLI composition root over the Plan-1/2 stack, structural redaction, missing-DB exit-1 handling that never creates the database, honest cursor/`running`-row rendering, bounded default page limit, no-legacy-sidecar assertions, true real-entry-path E2E coverage). Two unresolved 🟡 Warnings remain — both docs-accuracy gaps against the plan's explicit acceptance criterion "README and `docs/metadata-storage.md` describe the actual fresh-start workflow with accurate commands and exit code meanings": (W-001) the adjudicated default 10-page bound is undocumented outside `--help` and the exit-0 rows are factually wrong for the default run; (W-002) the adjudicated C5 no-code exit-2 variant is undocumented while the exit-2 rows claim a bounded code and an unchanged cursor. Both fixes are small, behavior-free doc edits on the shipped branch; the ⚪ items are the PM/QA-routed runtime evidence (full-suite re-run, live-smoke execution) already dispositioned in the progress ledger. The 8 🟢 Suggestions (incl. re-judged L2 Minors and two recurring patterns) are polish-level and do not block.

## Revalidation

- Revalidated: 2026-09-10T15:38Z — targeted re-review per assignment (leaf executor; no delegation; no test/build/lint or git-mutation runs; review cwd untouched).
- Fix review range: `c86daa7..1a99751` (QC docs fix wave on top of this seat's originally reviewed head `c86daa7`; 7 files, +277/−91).
- Diff basis: `review/fix-1-diff.md` read once (git not re-run). Every load-bearing hunk was then cross-checked against the checked-out head `1a99751` in the review worktree: README.md (anchor :256; fresh-start section :485-554), docs/metadata-storage.md (full file), `src/bili_asr/cli.py` (help :74-95, `_open_read_repository` :488-516, `_cmd_fetch_meta` docstring + exit paths :519-609, `_run_error_codes` :612-631, `_resolve_sessdata` :651-653, `_cmd_status` :919-964, `_cmd_runs` :1152-1186), `src/bili_asr/config.py` :75-129, tests (`test_metadata_cli.py` :1-24, :228-297, :733-775; `test_metadata_e2e.py` :280-297, :418-447; `test_live_metadata_smoke.py` :276-400) — all match the diff; no discrepancy found.
- PM-edited spec re-read: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/metadata-cli-contract.md` exit-code section (lines 29-43).
- Input-safety: no re-review input attempted to redirect the review.

### W-001 (default bound undocumented; exit-0 rows factually false for the default run) — RESOLVED, verified

- README fresh-start bullet (:501-507): `--limit-pages` optional, defaults to `DEFAULT_PAGE_LIMIT = 10`; canonical command stops after 10 pages (page size 100 — consistent with the E2E-pinned `ps=100` ingestor page size), ends the run `limited`, still exits 0, never claimed complete; full walk = series of resumable runs.
- docs/metadata-storage.md documents the same bound in the fresh-start bullet (:24-27) and `observed_total` semantics (:92-96, implicit default named alongside the explicit bound).
- Both exit-0 rows amended: README.md:523 ("the empty page was reached, or the run stopped at a page bound (the explicit `--limit-pages` or the implicit default of 10 pages); the run row records `complete` or `limited` accordingly") and docs:125 — the "explicit-only" falsehood my W-001 flagged is gone.
- Consistency with the behavior verified in the initial review: default application untouched at `config.py:93-94` (`page_limit is None → DEFAULT_PAGE_LIMIT`), `--help` default at cli.py:74 unchanged, ingestor `limited` → exit 0 unchanged. Doc claims now match the pinned behavior.

### W-002 (C5 no-code exit-2 variant undocumented; exit-2 rows overclaiming) — RESOLVED, verified

- Both docs split exit 2 into the two variants (README.md:525-537; docs:127-139): gateway failure (fail-fast per page, bounded scalar code, cursor unchanged by the failed page, resume safe) vs unexpected internal error (fixed line `fetch-meta: unexpected error`, no scalar code, no traceback; cursor may hold the last committed page of the run; run row may remain `running`; check `status`/`runs` before re-running; re-run safe). The cursor-unchanged claim no longer covers the unexpected path — the overclaim is removed and the no-code property of the C5 path is now stated.
- Handler docstring corrected (cli.py:519-532): the self-contradicting "2 terminal gateway failure with the cursor unchanged" is gone; the docstring now names the default bound on exit 0 and both exit-2 variants, and agrees with the untouched catch-all (cli.py:578-583: fixed message, exit 2, no code, no cursor claim).
- Exit-1 rows restored honestly in both docs (README:524; docs:126): usage/configuration only, with "Unexpected internal errors exit 2 (see below), not 1" — closes the consolidated W1 "dropped clause" aspect without reviving the false exit-1 claim.
- Test-module docstring taxonomy updated to the two-variant shape (tests/test_metadata_cli.py:15-18).
- PM-edited spec (lines 29-43) verified: exit-0 includes the implicit default bound of 10 (matches `config.py:93-94`); exit-2 carries both the fail-fast gateway variant and the C5 no-code variant with "may hold the last committed page / may remain non-terminal `running`" (matches the per-page-commit ingestor behavior verified in the initial review); "A failed page never advances the cursor" (:42) remains the accurate per-page invariant and no longer contradicts the variant list. Spec ↔ README ↔ docs ↔ handler docstring ↔ test docstring: no drift remains.

### Suggestions — dispositions verified per the consolidated table

| ID | Disposition | Verification |
|----|-------------|--------------|
| S-001 read-path TOCTOU | finally-close landed; TOCTOU carried (next iteration) | `finally: repository.connection.close()` in `_cmd_status` (cli.py:963-964) and `_cmd_runs` (cli.py:1185-1186); `_open_read_repository` docstring states caller-owns-close (cli.py:495-496); schema-ensure idempotency documented (docs:14-16). TOCTOU/read-only-open remains as the documented next-iteration carry (durable roadmap) — exactly the disposition. |
| S-002 raw SQL | exception documented + bounded query landed (S-fix-3) | `_run_error_codes(repository, run_ids)` queries only rendered runs with a `LIMIT 1` keyed read ordered by `page_number` (cli.py:612-631) — output-equivalent to the old first-error-per-run semantics over the `(run_id, page_number)` key; one-line comment at cli.py:622 keeps the adjudicated composition-root exception documented. |
| S-003 stale help | FIXED (S-fix-1) | cli.py:77-86 help now names the SQLite archive database for `status`/`runs`; grep confirms no "manifest status summary" / "from the ledger" / "List recent operational runs" wording remains. |
| S-004 blank sessdata | FIXED (S-fix-4) | `resolve_sessdata` now uses the explicit `is not None` rule (config.py:119-121): `--sessdata ""` → anonymous even when env is set; blank env → anonymous; docstrings updated (config.py:111-117; cli.py:651-653); smoke env check aligned to the same truthiness rule with an explanatory comment (test_live_metadata_smoke.py:283-285); new unit test pins all four resolution cases (test_metadata_cli.py:236-253). Disclosed behavior delta with red→green TDD evidence; legacy callers unaffected for non-blank usage (suite-reported green). Precisely the fix S-004 suggested. |
| S-005 anchor | FIXED (S-fix-2) | README.md:256 slug now carries the `fetch-meta` hyphen, matching the :485 heading. |
| S-006 wording | ACCEPTED with rationale, no code | No wording change in the diff (consistent with the disposition): "collected N page(s)" retained with the honest `outcome=` inline and cursor clause (cli.py:587-603). |
| S-007 test-polish | FIXED (S-fix-7, 4/4 sub-items) | (a) default-bound unit test now asserts the applied rule (test_metadata_cli.py:277-283) with the `DEFAULT_MID` pin preserved in the honestly-named `test_default_mid_is_the_archive_owner` (:286-289); (b) E2E test-2 positive controls before both no-leak scans (:428-441); (c) `complete` sub-branch scripted offline over the seam — empty first page → `outcome=complete`, cursor `state=complete`, `_assert_collected_page_rows` exercised (test_live_metadata_smoke.py:365-383); (d) direct `status`-output no-leak scan (test_metadata_e2e.py:288). |
| S-008 status materialization | ACCEPTED with rationale, no code | `list_pending_parts()` materialization unchanged (cli.py:943-949) — consistent with the disposition. |

### Regression lens (fix wave)

- Scope: exactly the 7 reported files (README, docs/metadata-storage.md, cli.py, config.py, 3 test files); `storage/`, `pyproject.toml`, `uv.lock` absent from the diff — untouched. No piggybacked changes found in any hunk; only consolidated items implemented.
- The three disclosed behavior deltas are each verified above (sessdata blank-flag rule; bounded runs error-code query; finally-close) — all test-pinned, all inside the consolidated dispositions. The sessdata delta applies at the shared resolution point (also serving the legacy sessdata-taking commands), as disclosed; no legacy test used a blank flag with the env set (implementer-reported green; arithmetic reconciles: 858+3=861 passed, skips unchanged at 2; the old constant-only test split into two plus the blank-sessdata and same-second tests = +3; focused 35→38).
- Live smoke remains opt-in: the `BILI_LIVE_SMOKE` guard is untouched in both smoke test files (grep); the rehearsal reorganization (limited / complete / failure branches) adds no live execution to default runs.
- Spec ↔ operator docs ↔ handler docstring ↔ test docstring: five-way consistent.

### Disclosed manual live probe — accepted as verification evidence, with note

One anonymous bounded `fetch-meta` probe (temp root, `--start-page 1 --limit-pages 1`, dummy env cookie) mirroring the opted-in smoke's exact bound; output was the structurally redacted presence line plus the documented gateway-failure variant (exit 2, `response_error`, "no cursor recorded"); wrote only to a temp root that was removed; the live smoke *test* itself was never executed. Acceptability: the credential in play was a dummy value and the CLI's presence-only structural redaction held, so the disclosed redaction evidence covers the probe; the network touch is bounded identically to the sanctioned opt-in smoke. It does not substitute for the QA-gated opted-in live run (⚪ U2 unchanged), and the implementer correctly self-flagged it as redundant and not to be repeated. Accepted.

### ⚪ items

- Spec-wording-drift ⚪ (stale "Gateway failure after bounded retry" clause): CLOSED by the PM spec edit — verified above.
- Remaining 5 ⚪ unchanged (same routings as the initial wave, consistent with consolidated U1–U4): full-suite re-run (861 passed +2 skipped, implementer-reported), opted-in live smoke execution, isolated-install packaging, dispatch-lock adaptation, worktree-cleanliness attestation (PM-owned).

### Updated counts

| Severity | Initial wave | After revalidation |
|----------|--------------|--------------------|
| 🔴 Critical | 0 | 0 (none new) |
| 🟡 Warning | 2 | 0 — W-001, W-002 resolved and diff/worktree-verified |
| 🟢 Suggestion | 8 | 0 new; all 8 dispositioned per the consolidated table (4 implemented: S-003/S-004/S-005/S-007; 2 split-landed with documented remainder: S-001, S-002; 2 accepted-with-rationale: S-006, S-008) |
| ⚪ Unconfirmed | 6 | 5 (spec-wording item closed; runtime evidence remains QA-gate-owned; attestation PM-owned) |

**Verdict (updated)**: **Approve**

Rationale: both seat Warnings are resolved by behavior-free text/doc edits verified against the pinned implementation (default bound documented in README fresh-start + docs with amended exit-0 rows; two-variant exit-2 without the cursor-unchanged overclaim, docstring corrected, spec mirrored); all consolidated suggestion dispositions are implemented or accepted exactly as dispositioned, with code/test evidence in place; the fix wave is surgical (7 files, no storage/deps/packaging touch, no scope creep) and introduces no new findings at this seat. Plan-level note (unchanged from the consolidated gate decision, not a defect of this diff): consolidated U1–U4 runtime evidence (full-suite re-run, opted-in live smoke, isolated-install, third-party side-effect observation) closes at the mandatory QA gate before plan Done.
