---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260909-metadata-cli-smoke"
verdict: "Approve"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: DeepSeek route (harness-assigned; exact provider/model id not introspectable from this leaf session)
- Review Perspective: performance / reliability (QC3 seat), whole-branch L3 plan QC: logic, contracts, docs accuracy, risk lens (single metadata source of truth, credential redaction, live-smoke filesystem bound, legacy-test retirement integrity), next-iteration contract readiness
- Report Timestamp: 2026-09-10T15:10Z

## Scope
- plan_id: 20260909-metadata-cli-smoke
- Review range / Diff basis: `18b6353..c86daa7` (merge-base `18b6353` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-metadata-cli-smoke` (HEAD = `c86daa7`; worktree clean — `git status --porcelain` empty, verified first-hand)
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke`
- Files reviewed: 13 (matches `git diff --stat 18b6353..c86daa7` = 13 files, +2317/−1189; identical to `review/branch-diff.md`)
- Commit range (if not identical to Review range line, explain): identical (`18b6353..c86daa7`; commits 849c046, cf490ff, c86daa7)
- Analysis methods: branch-diff.md (read in full), read, grep, first-hand read-only git checks (`git rev-parse`/`branch`/`log`/`diff --stat`/`diff --check`), worktree source inspection (`cli.py`, `config.py`, `storage/database.py`, `storage/schema.sql` refs, `sources/bilibili_api_gateway.py`, `coordinator.py`, README) — no test/build/lint runs, no worktree mutation
- Deep review: triggered (S1: +2317/−1189 lines / 13 files; S6: diff spans cli/config + storage + services + sources + tests/fixtures ≥3 module boundaries)
- Lenses applied: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership / Derived-State Lens (QC3 defaults); Contract Lens applied ad hoc to the docs/exit-taxonomy findings
- Input-safety: all inputs treated as data; no input attempted to redirect the review or break leaf boundaries; nothing to report

## Findings

### 🔴 Critical

None. The whole-branch diff preserves the plan's hard invariants verified from source: single `bili-asr` entrypoint (no `pyproject.toml` change, no second executable), fresh-SQLite-only metadata path (5 legacy fetch-meta JSONL helpers deleted with no remaining references; sidecar absence asserted in success/failure/read paths), credential redaction enforced structurally (`field(repr=False)`, presence-only labels, sentinel scans over stdout+stderr and all persisted objects), live smoke bound to one page/UID 23191782/temp root (`--start-page 1 --limit-pages 1`, function-scoped `tmp_root`; CLI writes — including the `coordinator/archive-writer.lock` — stay inside the archive root), and no migration/deletion of legacy data.

### 🟡 Warning

- **[F-001] Exit-2 contract drift is undocumented: unexpected internal errors exit 2, but both docs exit tables promise "terminal gateway failure with a bounded scalar code … the cursor remains unchanged".** The handler maps any exception escaping the ingestor to exit 2 (`cli.py:567-572`, adjudicated C5, test-pinned) — but on that path no scalar code is printed, the cursor holds the last committed page (may have advanced mid-run), and the run row may be left non-terminal `running`. The new README exit table (`README.md:512-516`) and `docs/metadata-storage.md` fetch-meta exit table (`docs/metadata-storage.md:271-279`) list exit 2 only as gateway failure with a scalar code, and both dropped the old README's "1 | Usage/config **or unexpected error**" clause (branch-diff old line: `| 1 | Usage/config or unexpected error (no traceback). |`) without absorbing it anywhere. The handler docstring itself (`cli.py:517-519`, "2 terminal gateway failure with the cursor unchanged") contradicts its own code path. The spec's exit-2 clause is additionally stale on a second axis — "Gateway failure **after bounded retry**" vs the Plan-2 fail-fast gateway (already PM-carried as a spec-note candidate). -> Fix: one paragraph in README + `docs/metadata-storage.md` exit tables documenting the unexpected-error→exit-2 outcome (no scalar code; run row may stay `running`; cursor holds the last committed page and resume stays safe), align the handler docstring, and add the fail-fast/unexpected-error clarification to the spec note PM already carries.
  - Verification: diff/read anchor — `cli.py:551-574` (except-Exception → `return 2`, finally closes), `cli.py:517-519` (docstring), `README.md:514-516`, `docs/metadata-storage.md:271-279`, spec `metadata-cli-contract.md:29-34`; test pin `test_fetch_meta_unexpected_error_is_bounded_exit_two_no_traceback` (branch-diff ~2740-2761); run row left `running` is structurally implied by `MetadataRepository.start_run` committing independently of `finish_run` (storage/database.py:114-122) and is rendered by `_cmd_runs` by design (C2).
  - Expected vs observed: docs/spec promise exit 2 ⟺ terminal gateway failure carrying a bounded scalar code with an unchanged cursor vs observed: an unexpected internal error also exits 2 with a generic fixed message, no scalar code, and a possibly-advanced cursor / non-terminal run row — an operator scripting exit-2 + parsing `error=` output has an undocumented failure shape.
  - Source Type: git-diff / read
  - Confidence: High

- **[F-002] The implicit `DEFAULT_PAGE_LIMIT = 10` page bound is missing from README and `docs/metadata-storage.md`, so the documented primary workflow command silently behaves as a bounded limited run.** `load_metadata_config` substitutes `DEFAULT_PAGE_LIMIT = 10` when `--limit-pages` is omitted (`config.py` C1 comment; pinned by `requested_page_limit == DEFAULT_PAGE_LIMIT` in tests). The README fresh-start section's primary command (`bili-asr fetch-meta --mid 23191782 --archive-root archive`, `README.md:496`) and its exit-0 row ("empty page reached or explicit `--limit-pages` bound", `README.md:514`) — likewise `docs/metadata-storage.md`'s exit-0 row (`docs/metadata-storage.md:275-277`) — describe only the explicit/empty-page terminations. The pre-branch CLI enumerated until the upstream empty page, so an operator following README expects full collection and instead gets the first 10 pages (≤1000 items at ps=100) ending `limited` with exit 0 and no doc hint that further collection requires re-running to resume. No data loss and `status`/`runs` report cursor state honestly, but the plan's docs acceptance criterion ("describe the actual fresh-start workflow with accurate commands and exit code meanings") is unmet for the default case. -> Fix: one sentence in README's fresh-start section + the exit-0 rows in both docs stating the default 10-page bound, that such a run ends `limited` (exit 0, never claimed complete), and that re-running continues from the stored cursor; optionally cross-link the documented `observed_total`/completion semantics.
  - Verification: diff/read anchor — `config.py` `DEFAULT_PAGE_LIMIT` block + `load_metadata_config` default substitution (branch-diff ~930-940, ~1004-1005); `README.md:496-514`; `docs/metadata-storage.md:240-248, 271-277`; test pin in `test_fetch_meta_creates_fresh_database_and_completes` (branch-diff ~2522-2527).
  - Expected vs observed: README/docs describe the primary command as full collection bounded only by explicit flags vs observed: an implicit 10-page bound ends the run `limited` (exit 0) and is documented only in `--help` and the config comment.
  - Source Type: read / doc-rule
  - Confidence: High

### 🟢 Suggestion

- **[F-003] Stale help text on the rewritten read commands** (Task-1 Minor 1, re-verified at HEAD): `cli.py:77` status help "Print manifest status summary" and `cli.py:81` runs help "List recent operational runs from the ledger" pin the retired manifest/ledger contracts; both commands now read `archive.db` only. The new help test pins `fetch-meta` only, so nothing catches this drift. -> one-line help updates (+ optionally extend the help test).
  - Verification: read anchor `src/bili_asr/cli.py:77,80-82`.
  - Expected vs observed: help describes the manifest/ledger contract the task removed vs actual SQLite-only reads.
  - Source Type: read
  - Confidence: High

- **[F-004] Blank `--sessdata ""` cannot force anonymous access when `BILI_SESSDATA` is set** (Task-1 Minor 4, re-verified): `resolve_sessdata` uses truthiness (`flag_value or environment_value or None`, `config.py`), so an empty flag falls through to the environment while the docstring's "blank values mean public (anonymous) access" holds only when the env is also blank; a whitespace-only value is treated as a credential. -> strip and use explicit `is not None` semantics, or scope the docstring.
  - Verification: read anchor `config.py` `resolve_sessdata` (branch-diff ~1019-1028) + `_resolve_sessdata` rewire (`cli.py`).
  - Expected vs observed: documented blank→anonymous rule vs actual env-fallthrough for a blank flag.
  - Source Type: read
  - Confidence: High

- **[F-005] CLI-layer raw SQL bypasses the repository and scans full error-code history per `runs` call** (Task-1 Minor 2 + Performance Lens): `_run_error_codes` (`cli.py:601-611`) queries `ingestion_pages` directly via `repository.connection` and fetches every error-code row across all runs on each `runs` invocation (output is bounded per run, but the scan grows unboundedly with run history), and `_cmd_status` issues direct count/group SQL (`cli.py:904-915`) while the same file otherwise routes through repository methods (`list_pending_parts`, `read_cursor`, `run_stats`). Fine at current scale; a schema/view rename would require CLI edits. -> move small repository accessors (per-run first error code, entity counts) behind `MetadataRepository`, optionally join error codes into `v_ingestion_run_stats`/`run_stats` to remove the second pass.
  - Verification: read anchor `src/bili_asr/cli.py:601-611, 898-927`; contrast with repository-routed calls in the same handlers.
  - Expected vs observed: repository-boundary pattern (docs position the repository as the SSOT accessor) vs CLI-owned raw SQL with an unbounded history scan.
  - Source Type: read / deep-lens: Performance Lens
  - Confidence: High

- **[F-006] Read commands never close the database connection; transient SQLite contention renders as a permanent configuration error** (Reliability Lens): `_cmd_status` (`cli.py:898-938`) and `_cmd_runs` (`cli.py:1126-1151`) never close the connection opened by `_open_read_repository` (rely on process exit), inconsistent with `_cmd_fetch_meta`'s `finally: connection.close()` (`cli.py:573-574`); and `_open_read_repository` catches `sqlite3.Error` around `open_database` only, so a transient `SQLITE_BUSY` (reader vs concurrent `fetch-meta` writer, after Python's default 5 s busy timeout) maps to "unreadable archive database … (OperationalError)" exit 1 with no retry. Harmless for one-shot sequential use, observable under concurrent operation. -> close via try/finally/context manager in the read handlers; consider a distinct bounded message for lock-class errors.
  - Verification: read anchor `cli.py:484-511, 573-574, 898-903, 1126-1137`; `storage/database.py:99-107` (connect without WAL/busy_timeout override; Python default timeout applies).
  - Expected vs observed: uniform connection lifecycle across the three metadata handlers vs read-path leak-by-reliance-on-exit; transient lock contention presented as a static configuration error.
  - Source Type: read / deep-lens: Reliability Lens
  - Confidence: Medium

- **[F-007] README internal anchor missing a hyphen** (Task-3 Minor 1, re-verified): `README.md:256` links `#fresh-start-metadata-collection-fetchmeta--status--runs`; the heading at `README.md:485` slugifies to `...-fetch-meta--status--runs` — the anchor won't resolve on GitHub-class renderers. -> `fetchmeta` → `fetch-meta`.
  - Verification: read anchor `README.md:256` vs `README.md:485`.
  - Expected vs observed: resolvable in-document link vs broken slug.
  - Source Type: read
  - Confidence: High

- **[F-008] "collected N page(s)" wording on failed runs** (Task-1 Minor 5, re-verified): on `risk_interrupted`/`failed` outcomes stdout prints `fetch-meta: collected N page(s) … (outcome=…)` before the stderr failure line (`cli.py:576-592`); the inline `outcome=` and "cursor unchanged" keep it honest, but the verb reads inaccurately when the last page fetch failed. -> "touched/attempted" (or reorder) on non-success outcomes.
  - Verification: read anchor `cli.py:576-592`; e2e failure test asserts stderr content only (branch-diff ~3462-3465), leaving the stdout wording unpinned.
  - Expected vs observed: success-verb on a failed run vs failure-honest phrasing.
  - Source Type: read
  - Confidence: High

- **[F-009] Test-hygiene bundle for the new suites** (Task-2 Minors 1–2, Task-3 Minor 3, re-verified): (a) `LEGACY_SIDECAR_PATHS`, `_ingest_clock`, `_newest_run_id`, `_cursor_row` are duplicated locals across `tests/test_metadata_cli.py` and `tests/test_metadata_e2e.py` (deliberate scope-respect; consolidation candidate); (b) e2e test 2's leak scan lacks a local non-vacuity content assertion (relies on test 1's render-path pin); (c) the `complete` sub-branch of `_assert_collected_page_rows` (`test_live_metadata_smoke.py:179-183`) is unreachable in every default run (rehearsal scripts a non-empty page 1 → `limited`; only a live empty page 1 would exercise it). -> consolidate helpers into a shared test module, add one content assertion in test 2, and script an empty first page on the seam to rehearse the `complete` branch offline.
  - Verification: read anchor — helper blocks at branch-diff ~2285-2380 (cli tests) vs ~3038-3103 (e2e); e2e test-2 scan at ~3412-3420; rehearsal branch coverage at ~1880-1925.
  - Expected vs observed: single shared home / self-evidently non-vacuous scans / fully rehearsed assertion helpers vs localized duplication, one scan pinned indirectly, and a dead-in-practice live-only sub-branch.
  - Source Type: git-diff / deep-lens: Testing Lens (S6 carry)
  - Confidence: High

- **[F-010] Next-iteration contract note: ingestion process records are metadata-collection-scoped — decide where subtitle/transcript process evidence lives before the next plan implements.** `ingestion_runs`/`ingestion_pages`/`ingestion_cursors` are keyed and columned for metadata collection (`mid`, source package/version, requested start page/page limit; `source_package='bilibili-api-python'`), and `docs/metadata-storage.md` § "Reserved media boundary" pre-creates the media/transcript tables but no process-record tables for subtitle acquisition. The next iteration (subtitle acquisition + normalized transcript segments) will need run/page-equivalent evidence and a `video_parts.processing_status` transition rule; nothing in this branch's docs states whether that evidence extends this schema or adds tables. -> record the decision explicitly in the next plan/spec so FK boundaries are extended deliberately rather than guessed.
  - Verification: read anchor `docs/metadata-storage.md:197-211` (process tables + reserved boundary), plan § Durable Roadmap ("Next iteration: add subtitle acquisition and normalized transcript segments"); `schema.sql` untouched by this diff.
  - Expected vs observed: a documented attach point for every next-iteration write family vs media/transcript rows only, process-record shape undecided.
  - Source Type: read / doc-rule / manual-reasoning
  - Confidence: Medium

### ⚪ Unconfirmed

- **[F-011] Full-suite and focused suite counts are implementer-reported, not QC-re-verified** — `31 passed` (Task 1 focused), `854 passed, 1 skipped` (Task 1 full), `3 passed in 0.34s` + `183 passed, 1 skipped` + `857 passed, 1 skipped` (Task 2), `1 passed, 1 skipped` focused + `858 passed, 2 skipped` (Task 3, Task-3 reviewer's own sanctioned re-run of the focused command matches). Arithmetic reconciles exactly (857 − 34 retired + 31 = 854; +3; +1) and the L2 reviews verified each retired test maps to a named replacement — but no QC seat re-ran the full suite. — channel gap: L3 QC is forbidden from running suites; **Needs L4/QA verification: re-run the full offline suite and the three focused commands at the QA gate.** (`git diff --check` cleanliness and clean-worktree claims are no longer implementer-only: verified first-hand by this seat — `git diff --check 18b6353..c86daa7` exit 0; `git status --porcelain` empty.)
- **[F-012] Isolated-install packaging evidence** (fresh-venv console-script/module help tests in `test_cli_help.py`) is implementer-reported; static `pyproject.toml` inspection (single entry point, `bilibili-api-python==17.4.2` pin, `schema.sql` package-data) supports it. — channel gap: same no-suite rule; QA re-run covers the install-path tests.
- **[F-013] Live smoke execution and third-party runtime behavior** — the opted-in live run (happy path with an operator credential; the anonymous bounded-failure skip path) was not executed by design; QA owns it. Additionally, "nothing outside the temporary root is written" is verified for everything this diff's code writes (CLI + writer lock live inside the temp root) but cannot speak for side-effects of the pinned `bilibili-api-python==17.4.2` distribution's own runtime (caching/session behavior) — QA's live execution is the observing channel. Offline rehearsal of both outcome branches through the real `main(argv)` path is verified in the diff and passes in every default run.

## Source Trace
- Finding ID: F-001
- Source Type: git-diff / read
- Source Reference: `src/bili_asr/cli.py:551-574` vs `README.md:512-516` + `docs/metadata-storage.md:271-279` + spec `metadata-cli-contract.md:29-34`; branch-diff old README exit-1 row
- Confidence: High
- Finding ID: F-002
- Source Type: read / doc-rule
- Source Reference: `src/bili_asr/config.py` `DEFAULT_PAGE_LIMIT` block + default substitution; `README.md:496-514`; `docs/metadata-storage.md:240-248,271-277`
- Confidence: High
- Finding ID: F-003
- Source Type: read
- Source Reference: `src/bili_asr/cli.py:77,80-82`
- Confidence: High
- Finding ID: F-004
- Source Type: read
- Source Reference: `src/bili_asr/config.py` `resolve_sessdata` docstring vs truthiness body
- Confidence: High
- Finding ID: F-005
- Source Type: read / deep-lens: Performance Lens
- Source Reference: `src/bili_asr/cli.py:601-611,898-915`
- Confidence: High
- Finding ID: F-006
- Source Type: read / deep-lens: Reliability Lens
- Source Reference: `src/bili_asr/cli.py:484-511,573-574,898-903,1126-1151`; `src/bili_asr/storage/database.py:99-107`
- Confidence: Medium
- Finding ID: F-007
- Source Type: read
- Source Reference: `README.md:256` vs `README.md:485`
- Confidence: High
- Finding ID: F-008
- Source Type: read
- Source Reference: `src/bili_asr/cli.py:576-592`
- Confidence: High
- Finding ID: F-009
- Source Type: git-diff / deep-lens: Testing Lens
- Source Reference: `tests/test_metadata_cli.py` vs `tests/test_metadata_e2e.py` helper blocks; `tests/test_metadata_e2e.py` test-2 scan; `tests/test_live_metadata_smoke.py:179-183` complete sub-branch
- Confidence: High
- Finding ID: F-010
- Source Type: doc-rule / manual-reasoning
- Source Reference: `docs/metadata-storage.md:197-211`; plan § Durable Roadmap
- Confidence: Medium
- Finding ID: F-011 / F-012 / F-013
- Source Type: assignment-ci-note / implementer-report (unverifiable by design at L3)
- Source Reference: `implementer-task-{1,2,3}-report.md` evidence tables; Task-3 reviewer's focused re-run
- Confidence: Medium (static cross-checks consistent; runtime proof deferred)

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 8 |
| ⚪ Unconfirmed | 3 |

**Verdict**: Request Changes

**Rationale**: No Critical findings; the branch's hard invariants (single source of truth, redaction, smoke bound, no-migration, retirement integrity) all check out from the diff and source. Two unresolved 🟡 Warnings remain — both documentation-contract gaps (F-001 undocumented unexpected-error→exit-2 + spec/README/docs exit-table claims violated on that path; F-002 implicit 10-page default bound absent from the primary workflow docs). Both are one-paragraph fixes, but they touch the plan's explicit docs-accuracy acceptance criterion and the spec's exit taxonomy, so they belong in a fix wave before QA sign-off rather than as residuals. The 8 Suggestions are polish (help strings, edge-case resolution rule, repository-boundary/lifecycle hygiene, test-hygiene, next-iteration contract note) — non-blocking, PM-owned disposition per zero-residual cleanup.

**L2 Minor re-judgment (plan level)** — none escalates to a plan-level blocker:
- Task 1: M1 → F-003 (Suggestion); M2 → F-005 (Suggestion, perf lens adds the unbounded history scan); M3 constant duplication → accepted as adjudicated (comment-guarded, fail-safe direction), no finding; M4 → F-004 (Suggestion); M5 → F-008 (Suggestion). PM decisions ①② independently re-checked from the diff: retirement arithmetic and per-test replacement mapping verified; pyproject no-edit is sound (single entry point, pin and package-data already present).
- Task 2: M1/M2 → F-009 (Suggestion); PM-accepted run-scoped discovery idempotency re-checked against the locked `ingestion_discoveries` PK — consistent, no finding.
- Task 3: M1 → F-007 (Suggestion); M2 anonymous-skip breadth → PM accepted as safe-by-design (evidence-before-skip ordering verified in the diff), no finding; M3 → F-009c (Suggestion).
- PM-carried spec note (stale "after bounded retry" clause): absorbed into F-001's fix along with the unexpected-error clarification.

**Verified strengths ( Enforcement-Path Lens / Ownership Lens, no findings)**: the `isfile`-guard-before-`open_database` ordering makes "reads never create the database" structurally true (`cli.py:495-503` before `storage/database.py:99-107`, whose `open_database` mkdirs/creates); `initialize_schema` is idempotent, so an existing-but-schema-less file cannot surface "no such table" tracebacks through the read commands; redaction is enforced on every exit path (fixed strings or `type(exc).__name__` only); the gateway binds SESSDATA to the `Credential` object only (`bilibili_api_gateway.py:245-253`); the writer lock file lives inside the archive root (`coordinator/archive-writer.lock`), keeping the live smoke's filesystem claim intact; `status`/`runs` correctly sit outside `_ARCHIVE_WRITER_COMMANDS` (`cli.py:2264-2275`) while `fetch-meta` holds the writer lock.

**Needs L4/QA verification** (diff-verifiable findings are unaffected): F-011 suite re-runs; F-012 install-path tests; F-013 opted-in live smoke (happy path with credential + anonymous bounded-failure skip) and third-party runtime side-effect observation.

## Revalidation

- Revalidation timestamp: 2026-09-10 (targeted re-review, seat 3 of 3)
- Scope: the QC docs fix wave `c86daa7..1a99751` (commit `1a99751` `docs(cli): document exit-2 variants and default page bound for metadata CLI`; 7 files, +277/−91) plus the PM-edited frozen-spec exit-code section (`metadata-cli-contract.md:29-43`), re-validated against the consolidated gate (`review/qc-consolidated.md`: W1 = qc1 W-001(a,b) · qc2 W-002 · this seat's F-001; W2 = qc1 W-001(c) · qc2 W-001 · this seat's F-002; S-fix-1…7).
- Methods: `review/fix-1-diff.md` read once in full; every claim treated as unverified until cross-checked first-hand by read-only worktree inspection at the new head — `cli.py` (help, docstrings, handler + exact error message, `_run_error_codes` + single caller, `_cmd_status`/`_cmd_runs` lifecycles), `config.py` (`resolve_sessdata`), README (anchor, fresh-start section, exit table + variants), `docs/metadata-storage.md` (fresh-start, `observed_total`, sessdata clause, exit tables, runs tie-break note), the three touched test files, and `_bounded_live_argv`; grep confirmed no stale-help residue (`manifest status summary` / `from the ledger`: zero matches). No git re-run, no test/build/lint execution, no worktree mutation; all inputs treated as data (nothing attempted to redirect the review). Frontmatter verdict updated by this revalidation: Request Changes → **Approve**.

### Per-finding verification

- **F-001 (🟡 → W1) — RESOLVED.** README exit table now documents exit 2 as terminal failure with two variants (README.md:521-537): *gateway failure* (fail-fast per page, one attempt, no retry, bounded scalar code, cursor unchanged, resume safe) and *unexpected internal error* (fixed line, no scalar code, no traceback, cursor *may* hold the last committed page, run row *may* remain `running`, consult `status`/`runs`, re-running safe) — with **no cursor-unchanged claim on the unexpected path**. Exit-1 row restored with its actual meaning plus the explicit "Unexpected internal errors exit 2 (see below), not 1" clause (honest replacement for the dropped old wording). `docs/metadata-storage.md:119-139` mirrors both variants; the handler docstring no longer self-contradicts (cli.py:519-532 — describes the default bound on exit 0, both exit-2 variants, and drops the false cursor-unchanged claim for the unexpected path); the exact message `fetch-meta: unexpected error` verified first-hand at cli.py:582 (`print("fetch-meta: unexpected error", file=sys.stderr)`, `return 2`). The PM-edited spec (`metadata-cli-contract.md:29-43`) folds in the same two variants and drops the stale "after bounded retry" clause in favor of "fail-fast per page (one attempt, no retry budget)". Spec / README / docs / code are now four-way consistent.
- **F-002 (🟡 → W2) — RESOLVED.** New README fresh-start "Default page bound" bullet (README.md:501-507): `--limit-pages` optional, defaults to `DEFAULT_PAGE_LIMIT = 10`, canonical command stops after 10 pages at page size 100, ends the run `limited`, still exits 0, never claimed complete, and a full walk is a series of resumable runs (re-run continues from the stored cursor). `docs/metadata-storage.md:24-27` states the same default bound; `:92-96` extends `observed_total`/completion semantics with the implicit default. Both exit-0 rows amended (README.md:523, docs:125) to cover the implicit-default case with `complete`/`limited` run rows, and the spec's exit-0 row (spec:30-31) includes the implicit 10-page bound. Exactly the fix my F-002 asked for.
- **F-003 (🟢 S-fix-1) — RESOLVED.** `status` help is now "Print collected metadata status from the SQLite archive database" and `runs` help "List recent metadata collection runs from the SQLite archive database" (cli.py:77-86, verified first-hand); grep confirms no "manifest"/"ledger" help wording remains in `cli.py`.
- **F-004 (🟢 S-fix-4) — RESOLVED as dispositioned.** `resolve_sessdata` now branches on `flag_value is not None` → blank flag resolves to `None` (anonymous) and never falls through to `BILI_SESSDATA`; blank env also resolves to `None`; a non-blank flag still wins (config.py:108-121). Both docstrings (`config.py` and `_resolve_sessdata`, cli.py:651-653) mirror the rule. The live-smoke anonymous-skip env check switched `is None` → truthiness (`not os.environ.get(...)`, test_live_metadata_smoke.py:283-293) — verified exactly aligned, because `_bounded_live_argv` (test_live_metadata_smoke.py:219-232) passes no `--sessdata` flag, so env-only truthiness is precisely the credential-in-play rule of `resolve_sessdata(None, env)`. Docs updated (README.md:517-519, docs/metadata-storage.md:100-103). Whitespace-only flag remains treated as a value — consistent with the now-precise "explicitly blank" wording and inside the adjudicated `""` scope. Red→green proof is implementer-reported → QA bucket (F-011 extension below).
- **F-005 (🟢 → S-fix-3 + accepted remainder) — RESOLVED per disposition (split).** The unbounded full-history scan is gone: `_run_error_codes(repository, run_ids)` issues one keyed `LIMIT 1` query per **rendered** run (`ORDER BY page_number LIMIT 1`, cli.py:612-631), so cost no longer grows with page history; per-run semantics are preserved (first bounded error page by page number — equivalent to the old `setdefault` over `ORDER BY run_id, page_number`), `selected` is computed before the query, and `error=` output is unchanged. Single caller `_cmd_runs` verified (grep: 2 matches = def + call site). The raw SQL stays with the composition-root-exception comment (cli.py:622) per the adjudicated remainder.
- **F-006 (🟢 → S-fix-5 + carried remainder) — RESOLVED per disposition (split).** `_cmd_status` (cli.py:924-964) and `_cmd_runs` (cli.py:1163-1186) now close the connection in `finally`, matching `_cmd_fetch_meta`'s lifecycle; `_open_read_repository`'s docstring states the caller owns closing (cli.py:495-496). All rendering happens inside the `try` — **no close-before-render**. The schema-ensure contract is documented as an idempotent no-op on a current-version database with no upgrade in this iteration (docs/metadata-storage.md:14-16). The TOCTOU + lock-class-messaging remainder is carried to the next iteration per the consolidated durable roadmap (qc-consolidated.md:48).
- **F-007 (🟢 S-fix-2) — RESOLVED.** README.md:256 anchor is now `#fresh-start-metadata-collection-fetch-meta--status--runs`, matching the README.md:485 heading slug (verified first-hand).
- **F-008 (🟢 → accepted with rationale) — DISPOSITION HONORED.** No code change: `collected N page(s)` still precedes the stderr failure line with the honest inline `outcome=` and cursor clause (cli.py:587-603 unchanged in this wave). Matches the consolidated acceptance rationale (cosmetic).
- **F-009 (🟢 S-fix-7) — RESOLVED, all four sub-items verified in the diff and worktree:** (a) `test_default_page_bound_applies_when_limit_pages_omitted` now asserts application behavior (`load_metadata_config(...).page_limit == DEFAULT_PAGE_LIMIT`) with the isinstance/positivity pins retained, and the `DEFAULT_MID == 23191782` pin moved to the honestly-named `test_default_mid_is_the_archive_owner` (tests/test_metadata_cli.py:274-289); (b) e2e test-2's leak scans gain two positive controls — persisted rows must contain `SINGLE_PART_BVID` and the scanned output must carry `sessdata: present` (tests/test_metadata_e2e.py:428-441) — killing vacuity; (c) the `complete` sub-branch is now rehearsed offline through the real CLI over the fake seam as rehearsal branch two (empty page 1 → `outcome=complete`, `cursor: next_page=1 state=complete`, sidecar absence, no-leak scans; `_assert_collected_page_rows`' complete sub-branch runs in every default run), with the bounded-failure branch moved to branch three and the docstring updated (tests/test_live_metadata_smoke.py:303-406); (d) `status` output is now directly scanned (`assert_leaks_no_markers(status_out + status_err, context="status output")`, tests/test_metadata_e2e.py:288), restoring the redaction-guarantee coverage on the credential-active surface.
- **F-010 (🟢 → carried to next iteration) — CARRIED, tracked in the consolidated durable roadmap** (qc-consolidated.md:48): the subtitle/transcript process-record schema decision must be explicit in the next plan before FK boundaries are extended. Verified present in the consolidated gate.
- **F-011 / F-012 / F-013 (⚪ → mandatory QA gate) — routing unchanged, evidence extended by this wave.** New implementer-reported counts: focused `38 passed, 1 skipped` (baseline 35+1 +3 new tests: blank-sessdata, default-mid, same-second ordering) and full offline suite `861 passed, 2 skipped` (baseline 858+2 +3; the 2 skips remain the Plan-2 opt-in skip and the Task-3 opt-in live smoke). Arithmetic reconciles exactly; the red/green proof (`test_blank_sessdata_flag_forces_anonymous` failing on the pre-change `config.py` with `assert 'env-cookie' is None`) is likewise implementer-reported. All runtime evidence (old and new) goes to the QA gate re-runs.

### Regression lens (fix wave)

- Diff is surgical: exactly 7 files (README.md, docs/metadata-storage.md, src/bili_asr/cli.py, src/bili_asr/config.py, tests/test_metadata_cli.py, tests/test_metadata_e2e.py, tests/test_live_metadata_smoke.py); `storage/`, `pyproject.toml`, and `uv.lock` are untouched (verified from the diff manifest) — single-entrypoint/pin/package-data invariants unaffected.
- Semantic behavior deltas are **exactly the three disclosed**, each pinned by a test added in this same diff: (1) blank `--sessdata ""` → explicit-anonymous (also at the shared legacy resolution point, disclosed); (2) `runs` error-code query → per-rendered-run `LIMIT 1` (output-identical first-error-per-run semantics; the pre-existing green `test_runs_shows_bounded_error_codes_only` is untouched by the diff); (3) read-command `finally` close (resource hygiene only).
- No new failure modes found: no close-before-render (all prints inside the `try`); the LIMIT query cannot drop a displayed code (per-run first-error semantics preserved; previously-fetched rows outside `--limit` were never rendered); the negative-`--limit` early return now closes cleanly inside the `try`; `_open_read_repository`'s failure shape is unchanged; the live smoke's opt-in skip guard is untouched (default pytest runs skip it — verified in the test file at lines 249-250).
- Process note (disclosed deviation): the implementer ran ONE anonymous bounded manual live `fetch-meta` probe (same bound as the opt-in smoke: `--start-page 1 --limit-pages 1`, temporary root later removed; presence-only output; documented gateway-failure variant). Disclosed; no invariant breached on the diff's evidence; it does **not** discharge QA's U2/U4 obligations (opted-in live smoke + third-party side-effect observation), which remain mandatory.
- Residual-free observation (recorded here; no new finding raised): the legacy README sessdata paragraph (README.md:233-236) predates the blank-flag rule and is not updated by this wave — nothing it states is now false, and the adjudicated S-fix-4 scope was the metadata docs + helper docstrings; a one-line legacy mention would be optional polish for any future docs touch. The shared `_resolve_sessdata` behavior delta on the legacy surface (blank flag previously fell through to the env) was disclosed by the implementer and is covered by the fixed docs at the shared point.

### Updated counts & verdict

| Severity | Before | After re-validation |
|----------|--------|---------------------|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 2 | 0 (F-001, F-002 resolved) |
| 🟢 Suggestion | 8 | 8 — all dispositioned per consolidated: 6 resolved by fix (F-003, F-004, F-005 split, F-006 split, F-007, F-009), 2 accepted with rationale (F-008, F-005 remainder); carried items (F-006 remainder, F-010) tracked in the consolidated durable roadmap |
| ⚪ Unconfirmed | 3 | 3 (F-011/F-012/F-013, extended with the wave's own counts + red/green proof → mandatory QA gate) |

**Verdict: Approve** (updated from Request Changes). Both of this seat's Warnings are resolved and first-hand verified; every suggestion's disposition matches the consolidated gate; the fix wave introduced no new failure mode. Standing condition unchanged from the consolidated gate: plan Done still requires the mandatory QA gate to close U1–U4 (suite re-runs including the three new tests and the red/green proof, isolated-install evidence, the opted-in live smoke, and third-party runtime side-effect observation). This Approve is the QC seat's verdict on the fix wave — it is not the QA gate's sign-off and does not claim the runtime evidence those ⚪ items cover.
