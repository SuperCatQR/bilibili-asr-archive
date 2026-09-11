# Task 1 Review — Replace metadata CLI construction and commands

**Plan**: `20260909-metadata-cli-smoke` · **Task**: 1 of 3 · **Reviewer**: code-reviewer (Mode A, L2, diff-first)
**Base → Head**: `18b6353` → `849c046` · **Branch**: `feature/20260909-metadata-cli-smoke`
**Reviewed**: diff file `review/task-1-diff.md` (read once), implementer report, brief, spec `specs/metadata-cli-contract.md`; worktree source spot-checks (read-only, no git, no tests executed).

## Spec Compliance

- ✅ **Spec compliant** — all checked contract points verified against the diff and the worktree source:

| Contract point (spec / brief / global constraints) | Evidence |
|---|---|
| Existing `bili-asr` entrypoint only; no `bili-asr-v2` | `pyproject.toml:18` unchanged — `bili-asr = "bili_asr.cli:main"`; no new executable |
| `fetch-meta` writes `{archive_root}/archive.db` through the repository | `_cmd_fetch_meta` → `open_database` → `MetadataRepository` → `MetadataIngestor.collect_user_pages` (per-page transactions via repository); CLI itself never writes rows directly; test pins `archive.db` creation (`test_fetch_meta_creates_fresh_database_and_completes`) |
| Never writes `manifest.jsonl` / `meta-cursor.json` / `run-ledger.jsonl` | New handler imports only `storage`/`services`/`sources`; legacy fetch-meta-only helpers (`_cached_page_lister`, `_merge_page_rows`, `_persist_cursor`, `_interrupt_cursor`, `_persist_partial`) deleted, no remaining references (grepped); `test_fetch_meta_never_writes_legacy_sidecars` (success + failure) |
| `status` reads the same SQLite DB, derived counts, no sidecars | `_cmd_status` → `_open_read_repository`; counts via SQL over `bilibili_users`/`videos`/`video_parts`; pending via `repository.list_pending_parts()` → `v_pending_metadata` (verified in `storage/database.py:533-550`); `test_status_ignores_legacy_sidecar_rows` asserts legacy rows unread and files untouched |
| `runs` reads normalized run/page queries; non-terminal `running` rendered (C2) | `_cmd_runs` → `repository.run_stats()` → `v_ingestion_run_stats` (view columns `run_id/mid/started_at/finished_at/outcome/page_count/video_count` match `_format_run_line` exactly); newest-first ordering; `test_runs_lists_newest_first_and_renders_running_rows` stubs a `running` row and asserts it renders |
| Read commands fail clearly when DB missing | `_open_read_repository` exits 1 with bounded message before any write-capable call (`open_database` is only called after the `isfile` guard, so reads never create the DB — confirmed against `storage/database.py` mkdir/create semantics); tests for status/runs missing-DB (exit 1, empty stdout) |
| `--mid`, `--start-page`, `--limit-pages`, `--archive-root`, optional `--sessdata` wired | Parser verified; help test pins all five + `--resume`; mutually exclusive `--resume`/`--start-page` group → usage exit 1 (`_UsageErrorArgumentParser`, QC2-2 convention preserved) |
| Cursor behavior (resume default / `--resume` requires cursor / `--start-page` overrides) | `config.start_page=None` → ingestor resumes from stored cursor or page 1 (ingestor docstring + tests: `--start-page` override test, no-flag resume test, `--resume` without DB (nothing created) and without cursor row both exit 1) |
| Exit taxonomy 0/1/2 | `0` complete/limited; `1` `MetadataConfigError`, non-positive page args, `--resume` preconditions, missing DB, `runs --limit < 1`; `2` bounded gateway failure (`risk_interrupted`/`failed`, cursor unchanged) and C5 unexpected exceptions — all pinned by tests |
| Failed page never advances cursor | `test_fetch_meta_upstream_failure_exits_two_with_cursor_unchanged` (-412 and -400): cursor row byte-identical, failed page outcome recorded, stderr says "cursor unchanged" (C3; status renders stored state verbatim) |
| No SESSDATA / signed URLs / raw bodies / raw exception text in output or records | `redact_sessdata` presence labels; `MetadataConfig` repr excludes sessdata; gateway constructed with `sessdata=` from `bili_asr.sources.bilibili_api_gateway` (not package-re-exported — verified, C6); `assert_leaks_no_markers` covers SESSDATA/signed-URL/raw-JSON/raw-exception sentinels over stdout+stderr and `persisted_row_text`; `runs` shows bounded scalar `error=<code>` only |
| Bounded page limits, no unbounded retries | `DEFAULT_PAGE_LIMIT = 10` applied when `--limit-pages` omitted (C1), documented in `--help` and pinned by test; gateway is fail-fast per page (no retry/sleep/backoff found in `bilibili_api_gateway.py`) |
| No migration/deletion/rewriting of old archive data | New path never touches sidecar modules for metadata; `test_status_ignores_legacy_sidecar_rows` asserts legacy files still exist and unread |
| Credentials redacted from any display path | Presence-only `sessdata: <present|absent>`; error paths print fixed strings or `type(exc).__name__` only; no credential in any fixture row or output |

- Brief decision ① (retire ~34 superseded legacy CLI-contract tests): **verified genuine supersession, not coverage gutting**. Counted exactly 34 removed tests from the diff (14 `test_fetch_meta`, 10 `test_meta_cursor`, 10 `test_run_ledger`), and the arithmetic reconciles: 857 − 34 + 31 = 854, matching the reported full-suite result. Each retired behavior maps to a new-path test (manifest write → DB rows; env-sessdata no-echo → marker scan; resume dedupe → resume tests; budget/API errors → -412/-400 exit-2 tests; pages limit → limited-outcome test; ledger wiring → normalized run rows; status/runs redaction → no-leak assertions). The retired `test_cli_unexpected_error_exit_1_no_traceback` pinned exit 1 — superseded per adjudicated C5 (exit 2). Sidecar **modules** (`manifest`, `meta_cursor`, `run_ledger`, `bili_client`) untouched with their store/transport-level tests kept; their remaining `cli.py` imports belong to unrelated commands (pilot/schedule/coordinator/export) — surgical-scope verified.
- Brief decision ② (pyproject audited, not edited): **verified no packaging gap** — single entry point present, `bilibili-api-python==17.4.2` pin present (Plan 2), `schema.sql` package-data present (Plan 1); `config.py` is an ordinary in-package module needing no packaging change. Simplicity-first acceptance is sound.
- Crashed-attempt repair claims verified: config docstring now scoped to fetch-meta only; `ARCHIVE_DATABASE_NAME` present; all 18 BV literals in the new test file pass the adapter's `^BV[a-zA-Z0-9]{10}$` shape; multipart fixture uses `page=index + 1`; `_ingest_clock` fixture present; `_collect_once` asserts `main(...) == 0`; oldest-run assertion and `pn=1`-once pins match the report; no `_seam_gateway` remnant. 26 test functions + 5 parametrized extras = 31 test items as reported.

### ⚠️ Cannot verify from diff (for PM)

1. **Full-suite green (854 passed, 1 skipped)** — implementer-reported; reviewer must not execute test suites. Arithmetic and static checks reconcile; QA gate should treat the report's TDD triple as the evidence of record.
2. **Isolated-install packaging evidence** (fresh-venv install tests in `test_cli_help.py`) — implementer-reported; static `pyproject.toml` inspection supports the claim.
3. **Worktree cleanliness / zero-residual claim** — implementer attests working tree clean after commit; `ls` of `src/` and `tests/` shows no stray files, but git status was off-limits in this review, so untracked-file cleanliness is PM-owned disposition (consistent with the retry note).
4. **Spec wording drift (plan-level, not this task's defect)**: spec exit-2 clause says "Gateway failure **after bounded retry**", but the Plan-2 gateway is deliberately fail-fast per page (disclosed by the implementer; verified — no retry loop). The implementation satisfies the adjudicated C-notes and never promises retries in its message; the spec clause text is stale relative to the Plan-2 gateway design. PM may want a one-line spec note at plan QC.
5. **Live smoke bound (UID 23191782, temp root, `--limit-pages 1`)** — Task 3 scope; correctly absent from this diff.

## Strengths

- **Thin composition root**: `fetch-meta` is now config validation → precondition checks → repository → gateway → ingestor, with the exit taxonomy documented in the handler docstring. All business logic stays in the (already-tested) ingestor; the CLI adds only boundary behavior.
- **Redaction is structural, not spot-fixed**: credential excluded from `repr`, presence-only labels on the display path, sentinel-scanned persisted rows, exception paths reduced to fixed strings or exception type names — the leak surface is closed at every exit, not just the happy path.
- **Read-command safety is designed, not accidental**: the `isfile` guard runs *before* `open_database`, which matters because `open_database` mkdirs/creates — reads provably never create the database, and the guard's rationale is documented in `_open_read_repository`.
- **Tests pin behavior, not implementation**: upstream-call transcripts (`user.get_videos(pn=1, ps=100)`), byte-identical cursors after failure, `requested_page_limit == DEFAULT_PAGE_LIMIT` persisted, help text advertises the contract — all offline over the real adapter seam.
- **Retirement discipline**: the 34 removed tests each have a named replacement; superseded modules keep their store/transport coverage; nothing unrelated (subtitle/audio/ASR/scheduler/coordinator) was touched.

## Issues

### Critical

None.

### Important

None.

### Minor

1. **Stale help text on the two rewritten read commands** — `src/bili_asr/cli.py:77` `status` help still reads "Print manifest status summary" and `src/bili_asr/cli.py:81` `runs` help still reads "List recent operational runs from the ledger". Both commands now read SQLite only and never touch the manifest/ledger; the help pins the retired contract the task removed. The new help test covers only `fetch-meta`, so nothing catches this drift. Suggest one-line help updates (no behavior change).
2. **CLI-layer raw SQL bypasses the repository boundary** — `_run_error_codes` (`src/bili_asr/cli.py:601`) queries `ingestion_pages` directly via `repository.connection`, and `_cmd_status` issues direct SQL for entity counts / `processing_status` groups. Works today, but the same file already routes through repository methods (`list_pending_parts`, `read_cursor`, `run_stats`); a schema/view rename would require CLI edits. Consider small repository methods in a later pass — not blocking.
3. **Duplicated database-name constant** — `config.py:37` `ARCHIVE_DATABASE_NAME = "archive.db"` duplicates the storage layer's private `_ARCHIVE_DATABASE_NAME` (`storage/database.py:26`), guarded only by comments on the config side. If they ever drift, read commands would exit 1 against an existing DB (fail-safe direction, but a silent trap). Acceptable as-is; a storage-side public constant or accessor would remove the risk.
4. **Blank `--sessdata` cannot force anonymous access when env is set** — `resolve_sessdata` uses truthiness (`flag_value or environment_value or None`), so `--sessdata ""` falls through to `BILI_SESSDATA`; the docstring's "blank values mean public (anonymous) access" holds only when the env is also blank. Pure edge case; document or use an explicit `is not None` check if forced-anonymous matters.
5. **"collected" wording on a failed run** — on `risk_interrupted`/`failed` outcomes, stdout first prints `fetch-meta: collected N page(s) … (outcome=…)` before the stderr failure line. The inline outcome and the "cursor unchanged" stderr line keep it honest (no C3 violation), but "touched"/"attempted" would read more accurately on failed runs. Wording only.

## Assessment

**Task quality:** Approved

All Task-1 brief items and the verbatim global constraints are implemented and evidence-backed; the two PM-adjudicated decisions (test retirement, pyproject audit-only) independently check out, and the crashed-attempt repair claims are consistent with the shipped content. The five Minor findings are polish-level (help text, layering, constant duplication, an edge-case resolution rule, wording) and do not block the task or the next SDD steps — they are handed to plan QC for disposition.
