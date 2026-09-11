---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260909-metadata-cli-smoke"
verdict: "Unconfirmed"  # revalidated 2026-09-10 (fix wave c86daa7..1a99751): W-001 resolved, fix-wave scope clean; verdict floor = the 3 ⚪ QA-gate routings (template rule: any Unconfirmed finding bars Approve)
generated_at: "2026-09-10"
revalidated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: not exposed by this runtime (DSH subagent; harness-default DeepSeek route)
- Review Perspective: plan QC seat 1 — whole-branch spec compliance, cross-plan contract composition (C1–C6), legacy-retirement audit, maintainability (Modularity + Contract deep lenses)
- Report Timestamp: 2026-09-10

## Scope
- plan_id: 20260909-metadata-cli-smoke
- Review range / Diff basis: `18b6353..c86daa7` (merge-base `18b6353` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-metadata-cli-smoke`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke` (`git rev-parse --show-toplevel`; `git branch --show-current` matches; HEAD `c86daa7` contains all three in-scope commits `849c046`, `cf490ff`, `c86daa7`)
- Files reviewed: 13 (branch-diff.md: README.md, docs/metadata-storage.md, src/bili_asr/cli.py, src/bili_asr/config.py, tests/fixtures/fake_bilibili_gateway.py, test_cli_help.py, test_fetch_meta.py, test_live_metadata_smoke.py, test_meta_cursor.py, test_metadata_cli.py, test_metadata_e2e.py, test_persistence_scale.py, test_run_ledger.py; +2317/−1189) plus read-only worktree spot-checks (cli.py, config.py, storage/database.py, services/metadata_ingest.py, README.md, spec)
- Commit range: `18b6353..c86daa7` (identical to Review range — no discrepancy)
- Analysis methods: branch review package diff, `git diff --stat` / `git diff --check` (read-only), read, grep, deep-lens: Modularity Lens + Contract Lens — **no test/build/lint runs** (per L3 seat contract; runtime proof belongs to implementer evidence and the QA gate)
- Deep review: triggered (S1: 13 files / +2317−1189; S6: ≥3 module boundaries — CLI+config source, docs, README, 8 test files)
- Lenses applied: Modularity Lens, Contract Lens (QC1 defaults; signal-specific lens triggers S2–S5 not present in this diff)
- Tri alignment: plan_id and Review range copied verbatim from the PM pack — same range as peer seats

## Findings

### 🔴 Critical

None. The three in-scope behaviors verified clean at whole-branch level:

- **Single existing entrypoint**: `pyproject.toml` untouched (not in the diff file list); dispatch stays `bili_asr.cli:main`; no parallel executable; `_ARCHIVE_WRITER_COMMANDS` (cli.py:2264) and the dispatch-level `archive_writer` wrapper (cli.py:2318–2329) are unchanged and still cover `fetch-meta` — README "Archive writer isolation" remains accurate.
- **No sidecar I/O on the new path**: the rewritten `_cmd_fetch_meta` / `_cmd_status` / `_cmd_runs` import only `storage` / `services` / `sources`; the five fetch-meta-only JSONL helpers are deleted with no dangling references; remaining `manifest`/`meta_cursor`/`run_ledger` imports in cli.py (lines 637–2140) belong exclusively to unrelated commands (probe-subs, harvest-subs, pilot, run, schedule, export) — surgical scope verified.
- **Exit taxonomy, bounds, redaction**: 0/1/2 pinned by tests incl. cursor-byte-identical failure (-412/-400), non-positive page args, `--resume` preconditions; `DEFAULT_PAGE_LIMIT = 10` bound (C1); fail-fast gateway with no retry loops (call-trace pinned); SESSDATA excluded from `MetadataConfig` repr, presence-only labels, sentinel scans over output and every persisted row/view.

### 🟡 Warning

- **[QC1-W1] Exit-2 contract text lags the adjudicated implementation in the primary spec, README, and docs/metadata-storage.md → one text-only spec-note/README/docs edit wave**
  - Three concrete gaps in the written contract for a reachable exit shape:
    1. Spec `metadata-cli-contract.md:32` defines exit 2 as "Gateway failure **after bounded retry**", but the Plan-2 gateway is deliberately fail-fast per page — no retry budget, sleep, or backoff exists on the new path (verified: no retry loop in `bilibili_api_gateway.py`; call-trace tests pin a single attempt per failed page). The clause describes the retired `bili_client` retry budget.
    2. The adjudicated C5 shape is undocumented: a non-gateway/unexpected exception exits **2** with the fixed bounded message `fetch-meta: unexpected error` and **no** bounded scalar code (cli.py:571–572, pinned by `test_fetch_meta_unexpected_error_is_bounded_exit_two_no_traceback`). None of the three exit tables (spec:29–34, README:514–516, docs/metadata-storage.md:273–279) covers "exit 2 without a scalar code", so an operator who hits an internal error cannot map the outcome to a documented meaning — the tables say exit 2 always carries a bounded gateway code.
    3. Spec `metadata-cli-contract.md:13` (`--limit-pages`) does not state the applied C1 default bound 10 that the CLI documents in `--help` (cli.py:74) and pins in tests (config.py:29).
  - Fix: one-line spec note (fail-fast wording replacing "after bounded retry"; an unexpected-error row for exit 2; the C1 default on `--limit-pages`) plus one sentence in the README/docs exit tables ("exit 2 without a code = unexpected internal error; retrying is safe, cursor unchanged" or equivalent). Behavior needs no change — the implementation is self-consistent and test-pinned.
  - Verification: read anchors — cli.py:571–572 vs metadata-cli-contract.md:29–34, README.md:514–516, docs/metadata-storage.md:271–279; task-1-review §⚠️4 and implementer-task-1-report "Contract nuance" disclose the same drift (PM already carried it to plan QC as a spec-note candidate).
  - Expected vs observed: expected the written contract to cover every reachable exit-2 shape and the applied default bound; observed a reachable exit-2 shape (unexpected internal error, no code) missing from all three tables and a stale retry clause.
  - Confidence: High

### 🟢 Suggestion

- **[QC1-S1] Stale `--help` text on the two rewritten read commands** — cli.py:77 `status` help still reads "Print manifest status summary" and cli.py:81 `runs` help still reads "List recent operational runs from the ledger"; both commands now read SQLite only and never touch those files. The help-drift test covers only `fetch-meta` (test_metadata_cli.py `test_fetch_meta_help_documents_contract_arguments_and_default_bound`), so nothing catches this. One-line help edits.
  - Verification: read anchor cli.py:77,81 vs the rewritten `_cmd_status` (cli.py:898) / `_cmd_runs` (cli.py:1126).
  - Expected vs observed: expected operator-facing help to describe the SQLite read surface; observed help pinning the retired manifest/ledger contract.
  - Source Type: deep-lens: Contract Lens (docs-match-code) · Confidence: High

- **[QC1-S2] CLI-layer raw SQL bypasses the repository boundary** — `_run_error_codes` (cli.py:601–613) queries `ingestion_pages` directly via `repository.connection`, and `_cmd_status` (cli.py:898–937) issues direct entity-count/`processing_status` SQL; the same file already routes other reads through repository methods (`list_pending_parts`, `read_cursor`, `run_stats`). A schema/view rename would force CLI edits. Suggest thin repository read methods in a later pass — not blocking.
  - Verification: read anchor cli.py:601–613, 905–922 vs storage/database.py:533–572 (existing repository read API).
  - Expected vs observed: expected one data-access boundary (repository) for all reads; observed two layers of SQL in the CLI composition root.
  - Source Type: deep-lens: Modularity Lens · Confidence: High

- **[QC1-S3] Duplicated database-name constant** — config.py:37 `ARCHIVE_DATABASE_NAME = "archive.db"` duplicates the storage layer's private `_ARCHIVE_DATABASE_NAME` (storage/database.py:26), guarded only by a comment. Drift would make read commands exit 1 against an existing database (fail-safe direction, but a silent trap). Suggest a storage-side public constant or accessor.
  - Verification: read anchors config.py:37 + storage/database.py:26.
  - Expected vs observed: expected a single source of truth for the archive database name; observed two independently maintained constants.
  - Source Type: deep-lens: Contract Lens · Confidence: High

- **[QC1-S4] Blank `--sessdata ""` cannot force anonymous access when the environment is set** — `resolve_sessdata` (config.py:108–117) uses truthiness (`flag_value or environment_value or None`), so a blank flag falls through to `BILI_SESSDATA`; the docstring's "blank values mean public (anonymous) access" holds only when the environment is also blank. Edge case; document the precedence explicitly or use `is not None` semantics if forced-anonymous matters.
  - Verification: read anchor config.py:108–117 + docstring wording.
  - Expected vs observed: expected the documented blank-means-anonymous rule to hold unconditionally; observed env precedence over an explicitly blank flag.
  - Source Type: manual-reasoning · Confidence: High

- **[QC1-S5] "collected" wording prints before the failure line on failed runs** — on `risk_interrupted`/`failed` outcomes, stdout first prints `sessdata: …` and `fetch-meta: collected N page(s) … (outcome=…)` (cli.py:576–579) before the stderr `metadata gateway failure` line. The inline `outcome=` and the "cursor unchanged" stderr keep it honest (no C3 violation), but "attempted/touched" would read more accurately on failed runs. Wording only.
  - Verification: read anchor cli.py:576–592 (print order: success lines → failure branch → return 2).
  - Expected vs observed: expected failure-path stdout to avoid claiming collection completed; observed "collected" phrasing ahead of the failure line (bounded by the honest inline outcome).
  - Source Type: manual-reasoning · Confidence: High

- **[QC1-S6] Test-local helper duplication across the three new test files** — `LEGACY_SIDECAR_PATHS` (test_metadata_cli.py, test_metadata_e2e.py, test_live_metadata_smoke.py), `_ingest_clock` and `_newest_run_id` and `_cursor_row` (duplicated in test_metadata_cli.py and test_metadata_e2e.py), and near-identical `_script_upstream` helpers are file-local copies. Deliberate scope-respect (each task's file list was closed); consolidation into a shared test helper touching Task-1's file is a plan-level follow-up, not a task defect.
  - Verification: grep anchors for the duplicated symbols across `bilibili-asr-archive/tests/`.
  - Expected vs observed: expected shared helpers to live in one test-support module; observed three local copies with a documented rationale.
  - Source Type: read · Confidence: High

- **[QC1-S7] Leak-scan self-evidence gaps in the new suite** — (a) `test_fetch_meta_persists_no_secret_markers` (test_metadata_cli.py) has no positive control and its scripted payload carries no seam sentinels, so the persisted-row half of that scan is vacuous-by-construction there (the output half is non-vacuous — the sentinel SESSDATA genuinely flows through the CLI flag path); (b) e2e test 2's output scan relies on the render path pinned by test 1 rather than a local content assertion (task-2 review Minor 2); (c) `status` output has no direct no-leak scan anywhere in the new suite — the retired `test_cli_status_and_runs_redaction_guarantees` covered both status and runs, while the new tests scan runs output (test_metadata_cli.py, test_metadata_e2e.py) but not status output. Risk is indirect (persisted rows are sentinel-scanned at write time; status renders only normalized scalars), so one-line additions (positive control in (a); `assert_leaks_no_markers` on status output in (c)) would restore parity cheaply.
  - Verification: read anchors test_metadata_cli.py (no-secret test + status tests), test_metadata_e2e.py (test 2 scan, no local positive control), retired test in branch-diff.md.
  - Expected vs observed: expected every rendered leak-susceptible surface to carry a locally self-evident scan; observed three scans depending on adjacent tests or vacuous surfaces.
  - Source Type: manual-reasoning · Confidence: Medium

- **[QC1-S8] README internal anchor misses the hyphen of `fetch-meta`** — README.md:256 links `#fresh-start-metadata-collection-fetchmeta--status--runs`; the heading at README.md:485 ("Fresh-start metadata collection (`fetch-meta` / `status` / `runs`)") slugs to `...fetch-meta--status--runs` on GitHub-class renderers (internal hyphens are preserved). Cosmetic broken link; one-word fix.
  - Verification: grep anchor README.md:256 vs README.md:485.
  - Expected vs observed: expected the link slug to match the heading slug; observed `fetchmeta` vs `fetch-meta`.
  - Source Type: deep-lens: Contract Lens (docs-match-code) · Confidence: High

- **[QC1-S9] Anonymous-skip breadth is wider than the adjudicated instance** — the live smoke skips on *any* bounded anonymous exit-2 (test_live_metadata_smoke.py:283–291), not only the adjudicated anonymous `response_error`. Independently re-judged as safe-by-design: the failure-shape assertions run before the skip decision, the skip reason names the observed code, and pinning to a single code would make the smoke brittle to upstream anti-bot code changes. PM's recorded ACCEPT stands; optional polish: a differentiated note when the code is not `response_error`.
  - Verification: read anchor test_live_metadata_smoke.py:283–291 (assertions → skip branch order).
  - Expected vs observed: expected skip breadth to match the adjudicated instance; observed generic bounded-failure breadth with assertions-first ordering (defensible).
  - Source Type: manual-reasoning · Confidence: High

- **[QC1-S10] `complete` sub-branch of `_assert_collected_page_rows` is not exercised offline** — the rehearsal covers `limited` happy path + bounded failure only (test_live_metadata_smoke.py:302–381); the `complete` branch (empty first page) executes only in a live run where upstream returns no videos on page 1 — practically never for UID 23191782. The seam could script an empty page 1 to rehearse it offline; coverage polish, not a defect.
  - Verification: read anchor test_live_metadata_smoke.py:179–183 vs the rehearsal's scripted pages (non-empty pn=1).
  - Expected vs observed: expected every branch of the smoke's assertion helper to have a runnable offline check; observed one defensive branch reachable only live.
  - Source Type: manual-reasoning · Confidence: High

- **[QC1-S11] Read commands: connection lifecycle + open-time schema initialization** — `_cmd_status` / `_cmd_runs` never explicitly close the SQLite connection (only `_cmd_fetch_meta` closes in `finally`; process exit closes it — no leak in a single-shot CLI, but asymmetric), and `open_database` runs `initialize_schema` (PRAGMA foreign-keys check + idempotent schema script) on **every** open (storage/database.py:77–94) — so a "read-only" command performs a schema-write attempt on the database. Today the script is a no-op (same schema), but across a future schema-forward CLI a read command would silently upgrade an older database, and a genuinely read-only database file may be rejected as "unreadable" (bounded exit 1), contradicting the docs' "status and runs are read-only" promise (docs/metadata-storage.md:57–59). Suggest try/finally close for symmetry and a read-only open mode (or a docs wording caveat) in a later pass.
  - Verification: read anchors cli.py:898–937/1126–1160 (no close) vs cli.py:569–570 (`finally: connection.close()` in fetch-meta); storage/database.py:75–92.
  - Expected vs observed: expected read commands to be side-effect-free at the connection level; observed schema initialization executed on every read-command open.
  - Source Type: deep-lens: Modularity Lens · Confidence: Medium (upgrade-on-read is certain from source; the read-only-file rejection shape needs a runtime probe — QA may confirm opportunistically)

- **[QC1-S12] `runs` same-second ordering tie-break is arbitrary** — `_cmd_runs` sorts by `(started_at, run_id)` reverse (cli.py:1143–1147); `started_at` is second-resolution (`_now` returns int, metadata_ingest.py:49) and `run_id` is unordered uuid hex, so two runs recorded in the same second render in arbitrary relative order. Low operator impact; consider a `finished_at`/insertion-order tie-break or microsecond clock if deterministic history matters later.
  - Verification: read anchors cli.py:1143–1147 + metadata_ingest.py:49 + run_id generation (uuid hex).
  - Expected vs observed: expected newest-first ordering to be total; observed a tie window resolved by an unordered key.
  - Source Type: manual-reasoning · Confidence: High

### ⚪ Unconfirmed

- **Full offline suite counts (`854 → 857 → 858 passed`; `1 → 2 skipped`)** — implementer-reported; the arithmetic reconciles exactly (857 baseline − 34 retired + 31 new = 854; +3 E2E; +1 smoke rehearsal; skips = Plan-2 + Task-3 opt-in live smokes) and `git diff --check` was independently re-verified clean. — channel gap: test execution is excluded from the QC seat. Needs L4/QA verification: `pytest -q` re-run at the mandatory QA gate.
- **Actual live-network smoke execution** (especially the credential happy path) — by design skipped in every default run; the offline rehearsal covers both outcome branches of the smoke's assertion helpers over the real CLI path. — channel gap: network execution is excluded from QC by the plan's verification boundary. Needs L4/QA verification: `BILI_LIVE_SMOKE=1 pytest tests/test_live_metadata_smoke.py` (with an operator credential for the happy path).
- **Isolated-install packaging evidence** (fresh-venv install tests in test_cli_help.py) — implementer-reported; static `pyproject.toml` inspection supports the claim (single entry point unchanged, `bilibili-api-python==17.4.2` pin present from Plan 2, `schema.sql` package-data present from Plan 1). — channel gap: install/test execution excluded from the QC seat. Needs L4/QA re-run.

## Source Trace

- Finding ID: QC1-W1
  - Source Type: read | doc-rule
  - Source Reference: `src/bili_asr/cli.py:571-572` vs `metadata-cli-contract.md:29-34,13` · `README.md:514-516` · `docs/metadata-storage.md:271-279`
  - Confidence: High
- Finding ID: QC1-S1
  - Source Type: deep-lens: Contract Lens (read)
  - Source Reference: `src/bili_asr/cli.py:77,81` vs `:898,:1126`
  - Confidence: High
- Finding ID: QC1-S2
  - Source Type: deep-lens: Modularity Lens (read/grep)
  - Source Reference: `src/bili_asr/cli.py:601-613,905-922` vs `src/bili_asr/storage/database.py:533-572`
  - Confidence: High
- Finding ID: QC1-S3
  - Source Type: deep-lens: Contract Lens (read/grep)
  - Source Reference: `src/bili_asr/config.py:37` vs `src/bili_asr/storage/database.py:26`
  - Confidence: High
- Finding ID: QC1-S4
  - Source Type: manual-reasoning (read)
  - Source Reference: `src/bili_asr/config.py:108-117`
  - Confidence: High
- Finding ID: QC1-S5
  - Source Type: manual-reasoning (read)
  - Source Reference: `src/bili_asr/cli.py:576-592`
  - Confidence: High
- Finding ID: QC1-S6
  - Source Type: read (grep)
  - Source Reference: `tests/test_metadata_cli.py` / `tests/test_metadata_e2e.py` / `tests/test_live_metadata_smoke.py` duplicated locals
  - Confidence: High
- Finding ID: QC1-S7
  - Source Type: manual-reasoning (read)
  - Source Reference: `tests/test_metadata_cli.py` (no-secret test + status tests), `tests/test_metadata_e2e.py` test 2 scan
  - Confidence: Medium
- Finding ID: QC1-S8
  - Source Type: deep-lens: Contract Lens (grep)
  - Source Reference: `README.md:256` vs `README.md:485`
  - Confidence: High
- Finding ID: QC1-S9
  - Source Type: manual-reasoning (read)
  - Source Reference: `tests/test_live_metadata_smoke.py:283-291`
  - Confidence: High
- Finding ID: QC1-S10
  - Source Type: manual-reasoning (read)
  - Source Reference: `tests/test_live_metadata_smoke.py:179-183,302-381`
  - Confidence: High
- Finding ID: QC1-S11
  - Source Type: deep-lens: Modularity Lens (read)
  - Source Reference: `src/bili_asr/cli.py:898-937,1126-1160` (no close) vs `:569-570` (fetch-meta finally); `src/bili_asr/storage/database.py:75-94` (initialize_schema on open)
  - Confidence: Medium
- Finding ID: QC1-S12
  - Source Type: manual-reasoning (read)
  - Source Reference: `src/bili_asr/cli.py:1143-1147`; `src/bili_asr/services/metadata_ingest.py:49`
  - Confidence: High

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 12 |
| ⚪ Unconfirmed | 3 |

**Verdict**: Request Changes

**Basis.** The whole-branch diff satisfies every checkable spec and plan constraint at the source level: single entrypoint preserved (writer-lock dispatch intact), `fetch-meta`/`status`/`runs` cleanly separated from the legacy sidecar path with the five JSONL helpers deleted and no dangling references, storage/services layers unmodified, C1–C6 carry items all applied with anchors (C1 default bound 10 documented+tested; C2 `running` rows rendered; C3 cursor rendered as stored with "cursor unchanged" failure wording; C4 `display_name = str(mid)` pinned in E2E; C5 unexpected→exit-2 bounded, no traceback; C6 direct adapter import + presence-only SESSDATA redaction), live smoke opt-in and hard-bounded (env gate, UID literal, `--start-page 1 --limit-pages 1`, temporary root, no subtitle/playback/audio/ASR code), and the legacy retirement is genuine supersession, not coverage gutting (38 removed test defs = 34 retired + 4 rewritten; arithmetic 857−34+31=854→857→858 reconciles; sidecar modules and their non-metadata consumers untouched).

The single Warning is documentation debt, not a code defect: the adjudicated exit-2 behavior (unexpected internal error → exit 2 without a scalar code) and the fail-fast gateway wording are not yet reflected in the primary spec, README, or `docs/metadata-storage.md` exit tables — a text-only fix wave (spec note + one sentence in each exit table) resolves it. The 12 Suggestions are polish (help text, layering, constant duplication, wording, test hygiene, lifecycle) and are handed to the PM for zero-residual disposition. The 3 ⚪ items are runtime evidence the QC seat cannot produce (suite re-run, live smoke execution, isolated install) — all pre-dispositioned by PM to the mandatory QA gate, which follows this tri-review.

---

## Revalidation

- Reviewer: @qc-specialist (seat 1, targeted re-review)
- Revalidation timestamp: 2026-09-10
- Fix range verified: `c86daa7..1a99751` (7 files, +277/−91; commit `1a99751` "docs(cli): document exit-2 variants and default page bound for metadata CLI") — read from `review/fix-1-diff.md` once, cross-checked with read-only worktree spot-checks; **no git re-runs, no test/build/lint runs** (L3 seat contract unchanged)
- Inputs: `review/qc-consolidated.md` (gate: Request Changes; W1/W2 dedup + S-fix-1…7 dispositions) · `implementer-qc-fix-1-report.md` (claims treated as unverified until diff-checked — all checked claims verified) · PM-edited spec `metadata-cli-contract.md` exit-code section (spec untouched by the implementer wave, as claimed — no spec file in the fix diff)
- Re-validation scope: my own W-001, my 12 Suggestions' dispositions, my 3 ⚪ routings; Modularity/Contract regression lenses over the 7-file diff

### Per-finding verification

**QC1-W1 (exit-2 contract drift + spec:13 default bound) — RESOLVED.** All four sub-surfaces verified in the diff, mutually consistent, and consistent with the code behavior I verified in the initial wave (cli.py:571–572, pinned by `test_fetch_meta_unexpected_error_is_bounded_exit_two_no_traceback`):
- (a) Stale "Gateway failure **after bounded retry**" replaced — spec:34–36 now states the fail-fast-per-page gateway (one attempt, no retry budget), matching the verified no-retry implementation; README + docs gateway-variant bullets state the same ("one attempt per page, no retry").
- (b) The C5 no-code unexpected variant is now documented in all three artifacts (spec:37–40; README "Exit 2 variants" sub-list; docs/metadata-storage.md same sub-list): fixed message `fetch-meta: unexpected error`, no scalar code, no traceback, cursor *may* hold the last committed page, run row *may* remain non-terminal `running`, consult `status`/`runs` before re-running — and **no cursor-unchanged claim on the unexpected path** (verified: none of the three artifacts nor the corrected handler docstring makes that claim on this variant; the cursor-unchanged/resume-safe wording is confined to the gateway variant). Handler docstring (cli.py:520–533) no longer self-contradicts — this closes consolidated-W1's docstring sub-item. Cross-seat W1 sub-item (qc2 W-002) also resolved: the README/docs exit-1 rows keep their actual usage/config meaning and explicitly state "Unexpected internal errors exit 2 (see below), not 1" — the dropped "or unexpected error" clause is honestly replaced, not silently restored.
- (c) The implicit 10-page default bound now appears in all three artifacts: spec exit-0 row ("or the implicit default bound of 10 pages when the flag is omitted" — placed in the exit-0 semantics rather than the `--limit-pages` argument line; defensible and factually complete), README fresh-start "Default page bound" bullet (page size 100 cross-checked against the e2e `ps=100` call trace), docs fresh-start + `observed_total` sections.
- Verification: diff anchors README.md @@−253/−498/−507, docs/metadata-storage.md @@−112/−122, cli.py @@−515 (docstring), spec:29–42; expected: every reachable exit-2 shape and the applied default bound documented; observed: exactly that, in three mutually consistent tables.
- Residual nuance checked and found consistent, not a finding: spec:42 "A failed page never advances the cursor, so resume is always safe" coexists with the unexpected variant's "cursor may hold the last committed page" — the cursor advances only through atomically committed pages (spec acceptance bullet), so resume-from-stored-cursor is safe on both variants; the README/docs unexpected-variant wording ("Re-running is safe: it resumes from the stored cursor") matches.

**QC1-S1 (stale `--help`) — FIXED** (S-fix-1). `status` help now "Print collected metadata status from the SQLite archive database", `runs` help "List recent metadata collection runs from the SQLite archive database" (cli.py:77–86). Worktree grep for "manifest status summary" / "from the ledger": no matches. No test pinned the old text; none required by the disposition. Verification: diff @@−74 + grep. Expected: help describes the SQLite read surface; observed: yes.

**QC1-S2 (CLI raw SQL bypass) — dispositioned accepted-with-rationale, unchanged.** The composition-root exception is now explicitly documented in-code (comment at cli.py:622 per diff). No regression: `_run_error_codes` and `_cmd_status` keep the same raw-SQL seam; no new SQL added outside it.

**QC1-S3 (ARCHIVE_DATABASE_NAME duplication) — dispositioned accepted, unchanged** (not in the fix diff; comment-guarded as adjudicated).

**QC1-S4 (blank `--sessdata ""` env fallthrough) — FIXED** (S-fix-4), and the disclosed behavior delta is verified as exactly the disclosed one:
- `resolve_sessdata` (config.py:108–123) now: `flag_value is not None` → `flag_value or None` (blank flag → anonymous, never env fallthrough); else `environment_value or None` (blank env → no credential). Docstrings updated at both the config function and the shared CLI helper (cli.py:651–653); README + docs state the rule (blank flag and blank env both mean anonymous).
- Blast radius verified by grep: `resolve_sessdata` has exactly two consumers — the metadata config path (config.py:102, fetch-meta) and the CLI `_resolve_sessdata` helper with 7 call sites (legacy sessdata-taking commands). All nine `--sessdata` argparse definitions use `default=None`, so an **omitted** flag behaves identically to before; the semantic delta is confined to an explicitly passed blank flag — exactly the disclosed change ("shared resolution point… legacy callers pass values or omit the flag"). No undisclosed legacy-command delta.
- Redaction unchanged: `redact_sessdata` presence-only labels untouched; blank → None → `sessdata: absent` is correct.
- Live-smoke env-presence check aligned (`is None` → truthiness with a rule comment, test_live_metadata_smoke.py:283–285): a blank `BILI_SESSDATA` now correctly counts as "no credential in play" for the anonymous-rejection skip — this tightens the S9-adjacent consistency rather than regressing it.
- Implementer's TDD red→green claim (pre-change `config.py` fails `assert 'env-cookie' is None`) is implementer-reported runtime evidence — rides U1/QA re-run; the diff itself confirms the test would exercise exactly that path.

**QC1-S5 ("collected" wording) — dispositioned accepted (cosmetic), unchanged.**

**QC1-S6 (test-local helper duplication) — NOT DISPOSITIONED (PM action needed, non-blocking).** qc1-S6 appears in none of the consolidated disposition buckets (fix-now / accepted-with-rationale / carried). The fix wave does not touch it (no shared helper module; the new tests add file-local helpers only where required by their files). Per the consolidated layer's own coverage rule (未提及 = 未审查), I record it as still-open polish: consolidate `LEGACY_SIDECAR_PATHS` / `_ingest_clock` / `_newest_run_id` / `_cursor_row` / `_script_upstream` into a shared test-support module in a later pass. Suggestion-severity; does not gate the verdict.

**QC1-S7 (leak-scan self-evidence) — SUBSTANTIALLY FIXED (S-fix-7); one sub-item outside the bundle.**
- (b) E2E test-2 non-vacuity: FIXED — positive content controls precede both scans (`assert SINGLE_PART_BVID in persisted` before the persisted-rows scan; `assert "sessdata: present" in out` before the output scan) — test_metadata_e2e.py:425–441 per diff.
- (c) `status`-output no-leak scan: FIXED — `assert_leaks_no_markers(status_out + status_err, context="status output")` in E2E test 1 (test_metadata_e2e.py:288), restoring the retired redaction-guarantee coverage on the credential-in-play surface.
- (a) Positive control in `test_fetch_meta_persists_no_secret_markers` (test_metadata_cli.py): NOT included — the consolidated S-fix-7 enumeration lists only the four delivered items; sub-item (a) is not among them. Risk unchanged from my original assessment (indirect: persisted rows are sentinel-scanned at the repository write boundary; the output half of that test is non-vacuous). Recorded as an open polish sub-item for PM disposition; suggestion-level.

**QC1-S8 (README anchor hyphen) — FIXED** (S-fix-2): `#fresh-start-metadata-collection-fetch-meta--status--runs` now matches the heading slug. Verification: diff @@−253.

**QC1-S9 (anonymous-skip breadth) — dispositioned accepted, unchanged**; S-fix-4's env-check alignment improves the noted inconsistency without changing the adjudicated breadth.

**QC1-S10 (unrehearsed `complete` sub-branch) — FIXED** (S-fix-7c): the offline rehearsal now scripts an empty first page over the fake seam (branch two: `outcome=complete`, `cursor: next_page=1 state=complete`, `_assert_collected_page_rows` + leak scan + sidecar-absence on a fresh root); the bounded-failure branch moved to branch three; docstring updated. Every default run now exercises the `complete` sub-branch through the real CLI path. Verification: diff @@−304/−357. Expected: a runnable offline check for the branch; observed: yes.

**QC1-S11 (connection lifecycle + open-time schema-ensure) — FIXED to the dispositioned scope** (S-fix-5): `_cmd_status` (cli.py:921–964) and `_cmd_runs` (cli.py:1154–1186) now close the repository connection in `finally` — worktree grep confirms exactly three `connection.close()` sites (585 fetch-meta pre-existing, 964, 1186); `_open_read_repository`'s docstring states caller-owns-closing. Correctness checked: both `finally` blocks sit after the `repository is None` early return, so no close-on-None; error paths (`--limit < 1`) now also close — hygiene improvement with identical output; `runs: empty` early-return is output-identical to the old fall-through. The schema-ensure no-op is now documented (docs/metadata-storage.md:13–16: schema script always runs on open, idempotent no-op on a current-version DB, no schema upgrade this iteration). The read-only open mode remains explicitly out-of-scope → next-iteration roadmap carrier per PM disposition (recorded in consolidated "Carried").

**QC1-S12 (same-second `runs` ordering) — FIXED** (S-fix-6): ordering was already deterministic `(started_at, run_id)` reverse in the delivered code; the contract is now stated in the handler docstring + tie-break comment and in docs ("same-second runs tie-broken deterministically by `run_id` descending"), and pinned by `test_runs_orders_same_second_runs_by_run_id_desc` (two stub runs at `started_at=1000`, FK-safe owner upsert first, run_id-descending render asserted). Verification: diff @@−1128 + test @@−704.

**⚪ routings (3) — unchanged, all remain → mandatory QA gate (consolidated U1–U3):**
1. Full offline suite counts: initial-wave claim (858 + 2 skipped) now superseded by the fix-wave claim **861 passed, 2 skipped** (+3 net new tests; arithmetic reconciles with the diff: +3 tests from the blank-sessdata test, the default-bound rewrite/split net +1, and the same-second ordering test). Implementer-reported; QA re-runs.
2. Opted-in live smoke execution (anonymous bounded-failure skip and the credential happy path): still by design skipped in every default run; offline rehearsal now covers three branches incl. `complete`. Note for QA: the implementer disclosed one manual anonymous live `fetch-meta` probe outside pytest (smoke-equivalent bounds, temp root removed, the live smoke *test* never executed) — a disclosed process deviation, acceptable; it does not substitute for the QA-gate-owned opted-in run.
3. Isolated-install packaging evidence: untouched by this wave (`pyproject.toml` not in the fix diff); the initial-wave static analysis stands; QA re-run or verifies the existing isolated-install tests.

### Regression lens (7-file surgical diff `c86daa7..1a99751`)

- **File set exact**: README.md, docs/metadata-storage.md, src/bili_asr/cli.py, src/bili_asr/config.py, tests/test_metadata_cli.py, tests/test_metadata_e2e.py, tests/test_live_metadata_smoke.py. `storage/`, `pyproject.toml`, `uv.lock`, test fixtures — untouched. ✅
- **Live smoke still opt-in-skipped**: the `BILI_LIVE_SMOKE` gating is untouched; the wave only edits the env-presence check inside the bounded-failure branch and adds a branch to the *offline* fake-seam rehearsal (which never touches the network). ✅
- **Disclosed behavior deltas = exactly the delivered set (3), each test-pinned**: (1) blank `--sessdata` → anonymous (config.py + shared helper + smoke env check; blast radius verified above); (2) `runs` error-code scan bounded per-rendered-run `LIMIT 1` — output-identical first-error-per-run semantics (`_run_error_codes` has exactly one call site, updated; old all-runs scan discarded non-rendered rows identically); (3) read-command `finally` close (resource hygiene only). Scanning the full diff for anything else: help text, docstrings, docs, and test additions are text/assertion-only; the `--limit < 1` and `runs: empty` control-flow moves are output-identical. **No undisclosed deltas.** ✅
- **Contract/Modularity lenses**: docs/help/docstrings now match code (fail-fast wording, two exit-2 variants, default bound, deterministic ordering, blank-sessdata rule all match the verified implementation); no new layering violation (raw SQL remains confined to the adjudicated composition-root seam with an explicit comment); C1–C6 carries untouched; C3 cursor-rendering comment preserved verbatim inside the restructured `_cmd_status`.
- **Test adjustments sound**: module docstrings updated to the two-variant taxonomy; the one rewritten existing test is the disclosed default-bound rewrite/split (old name overpromised; new names honest; DEFAULT_MID pin preserved); e2e/smoke changes are strictly additive assertions; no coverage gutting. Test-count arithmetic reconciles (858 + 3 = 861; skips unchanged at 2).

### Updated severity counts (revalidation state)

| Severity | Count | Notes |
|----------|-------|-------|
| 🔴 Critical | 0 | unchanged |
| 🟡 Warning (unresolved) | 0 | W-001 verified resolved (spec PM-edit + README + docs + docstring) |
| 🟢 Suggestion | 12 inventoried | 7 fixed & verified (S1, S4, S8, S10, S11-to-scope, S12, S7 b+c); 4 dispositioned accepted-with-rationale by PM (S2, S3, S5, S9); 2 open polish notes for PM disposition, non-blocking (S6 unmentioned in consolidated; S7(a) outside the S-fix-7 bundle) |
| ⚪ Unconfirmed | 3 | unchanged QA-gate routings (suite re-run / live smoke execution / isolated install) |

### Verdict: **Unconfirmed**

**Basis.** The fix wave verified clean in my entire review scope: W-001 is resolved across all four artifacts (PM-edited spec, README, docs, handler docstring) with mutually consistent exit-2 variants and the default bound documented; S-fix-1…7 are delivered as dispositioned; the three disclosed behavior deltas are exactly the delivered set with no undisclosed delta (verified down to the argparse defaults and the single `_run_error_codes` call site); the 7-file diff is surgical; no new Critical/Warning found. Per the report-template verdict rules, the three pre-existing ⚪ findings (runtime evidence: full-suite re-run at the new counts, the opted-in live smoke execution, isolated-install packaging) remain and bar `Approve` — this Unconfirmed is that ⚪-floor, **not** an evidence-channel failure of the fix diff (the fix-diff package was complete and every checked claim verified). It matches the consolidated gate's own sequencing: targeted re-review (this report) → mandatory QA gate closes U1–U3 → only then gate Approve. QC1-W1's blockers are cleared; no further fix wave is required from this seat.

