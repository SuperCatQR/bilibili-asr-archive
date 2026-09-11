# Task 1 Implementation Report — Replace metadata CLI construction and commands

**Plan**: `20260909-metadata-cli-smoke` · **Task**: 1 of 3 · **Branch**: `feature/20260909-metadata-cli-smoke`
**Commit**: `849c046` (base `18b6353`) · **Report date**: 2026-09-10
**Retry note**: this is a **retry after a crashed prior attempt**. The attempt left two untracked files
(`tests/test_metadata_cli.py`, `src/bili_asr/config.py`), treated as untrusted input and audited against the
brief/spec before anything was reused (see "Crashed-attempt audit" below).

## Status

**DONE_WITH_CONCERNS** — implementation complete, full offline suite green, committed on the Working branch only.
Two scope decisions were made non-interactively because `ask_user_question` was unavailable to this subagent
("human interaction is unavailable while the calling agent is owned by another live agent"); both are flagged for
PM confirmation below.

## Implemented

- **`src/bili_asr/config.py` (new)** — `MetadataConfig` (frozen dataclass; `sessdata` excluded from `repr`),
  `load_metadata_config` (validates `--mid`/`--start-page`/`--limit-pages` positivity, enforces
  `--resume`/`--start-page` mutual exclusion, applies the documented default page bound), `resolve_sessdata`
  (flag → `BILI_SESSDATA` → None), `redact_sessdata` (presence-only labels `present`/`absent`), and
  `ARCHIVE_DATABASE_NAME = "archive.db"` (the file name read commands existence-check before opening).
- **`src/bili_asr/cli.py`** — `fetch-meta` rewired as a thin composition root:
  - Parser: added `--start-page`; `--resume`/`--start-page` in an argparse mutually-exclusive group (usage
    error → `SystemExit(1)` via the existing `_UsageErrorArgumentParser`); `--limit-pages` help documents the
    default bound `10`.
  - Handler: config validation (`MetadataConfigError` → exit 1) → resume preconditions (`--resume` requires the
    fresh database to exist and a stored cursor; both fail exit 1 without creating anything) →
    `open_database({archive_root}/archive.db)` → `MetadataRepository` → `BilibiliApiGateway(sessdata=...)`
    (imported lazily from `bili_asr.sources.bilibili_api_gateway`, per the Plan-2 C6 note) →
    `MetadataIngestor.collect_user_pages(mid, start_page, page_limit)`.
  - Exit taxonomy (documented in the handler docstring): `0` complete/limited, `1` usage/configuration error,
    `2` risk_interrupted/failed run outcomes with a bounded stderr line (`… gateway failure (<code>); cursor
    unchanged at page <N> — re-run fetch-meta to resume.`). Unexpected non-gateway exceptions exit `2` with the
    fixed string `fetch-meta: unexpected error` — never a traceback or payload text (C5).
  - `--limit-pages` defaults to `DEFAULT_PAGE_LIMIT = 10` (C1): full-collection runs always terminate on a
    bounded resumable slice, never unbounded.
  - Success stdout: `sessdata: <present|absent>` (redacted), `fetch-meta: collected N page(s) for mid=… (outcome=…)`,
    `cursor: next_page=… state=…`.
  - Legacy sidecar I/O removed from the new path: deleted `fetch-meta`-only helpers `_cached_page_lister`,
    `_merge_page_rows`, `_persist_cursor`, `_interrupt_cursor`, `_persist_partial`; `_resolve_sessdata` now
    delegates to `config.resolve_sessdata`. The manifest/meta-cursor/run-ledger **modules** are untouched and
    remain for the future subtitle/audio/ASR and scheduler/coordinator flows.
  - `status` reads the fresh database only: user/video/part counts, `processing:` groups by
    `processing_status`, `pending:` count + `v_pending_metadata` work_ids (display-capped at 20 with a
    `+ N more` line), and stored cursor rows per user (state rendered exactly as stored — never implies cursor
    advancement on a failed run, C3; no new display-name source, C4). Missing/corrupt DB → exit 1, bounded
    message, nothing created.
  - `runs` reads `v_ingestion_run_stats` (`repository.run_stats()`), sorted newest-first
    (`started_at DESC, run_id DESC`), renders non-terminal `running` rows (C2), one bounded scalar
    `error=<code>` per run from recorded page evidence, `--limit N` after ordering; non-positive `--limit` →
    exit 1. Missing DB → exit 1 (`runs: empty` only for an existing run-less database).
- **`tests/test_metadata_cli.py` (new, 31 tests)** — parser help/arguments/mutual exclusion, non-positive page
  args → exit 1 bounded, SESSDATA resolution/redaction/repr-hiding, default-bound constant, fresh-database
  creation + normalized rows + completing cursor (single- and multipart), `--limit-pages` → limited outcome
  (exit 0, never claims complete), `--start-page` cursor override, no-flag resume from stored cursor,
  `--resume` requires DB/cursor (nothing created), upstream `-412`/`-400` → exit 2 with cursor byte-identical
  and bounded page/run outcomes, unexpected ingestor exception → exit 2 bounded, legacy-sidecar non-creation
  and no-secret/no-leak assertions over output and persisted rows (real adapter over the fake `bilibili_api`
  seam; all offline).
- **`pyproject.toml` — audited, no edit** (see Decision 2).

## Tests

Commands (worktree has no `.venv`; control-checkout interpreter used as instructed):

1. **Red (TDD)**: `cd bilibili-asr-archive && /root/workspace/.../.venv/bin/python -m pytest tests/test_metadata_cli.py -x -q`
   → `1 failed` — `test_fetch_meta_help_documents_contract_arguments_and_default_bound`: `--start-page` absent
   from the parser (old CLI). Red state confirmed before implementation.
   *Note*: the unfiltered red run was terminated (timeout) because the OLD handler drives `bili_client` against
   live HTTP with real backoff sleeps — the seam only backs the new path. This is also positive evidence the
   new path's tests stay offline.
2. **Green (focused)**: `pytest tests/test_metadata_cli.py -q` → `31 passed`.
3. **Full offline suite (final state)**: `pytest -q` → `854 passed, 1 skipped` (42.7s). Baseline was
   `857 + 1 skipped`; arithmetic reconciles exactly: 34 superseded legacy tests retired, 31 new tests added
   (857 − 34 + 31 = 854). Re-run after the last code edit to confirm.
4. `git diff --check` → clean. `compileall` on src/tests → ok.

## Files changed (commit `849c046`)

- `bilibili-asr-archive/src/bili_asr/cli.py` (modified)
- `bilibili-asr-archive/src/bili_asr/config.py` (new)
- `bilibili-asr-archive/tests/test_metadata_cli.py` (new)
- `bilibili-asr-archive/tests/test_fetch_meta.py` (superseded CLI-contract tests retired; client transport tests kept)
- `bilibili-asr-archive/tests/test_meta_cursor.py` (CLI-driven sidecar tests retired; store tests kept)
- `bilibili-asr-archive/tests/test_run_ledger.py` (fetch-meta ledger wiring + status/runs CLI tests retired; ledger/pilot tests kept)
- `bilibili-asr-archive/tests/test_cli_help.py` (4 status/runs install tests rewritten to the SQLite contract)
- `bilibili-asr-archive/tests/test_persistence_scale.py` (busy-writer test seeds the fresh DB so read-only `status` succeeds under a busy writer lock)

## Crashed-attempt audit (kept vs rewritten)

- **`config.py` — kept with two edits**: the implementation core (config dataclass, validation, resolution,
  redaction, `DEFAULT_PAGE_LIMIT = 10` with rationale) was sound and is reused verbatim. Edits: (a) module
  docstring corrected — it claimed all three commands load config through the module, but `status`/`runs` take
  no credential or page arguments; (b) added `ARCHIVE_DATABASE_NAME` so the CLI read commands can
  existence-check without touching the storage layer's private constant.
- **`tests/test_metadata_cli.py` — structure kept, multiple defects fixed** (all were red for wrong reasons):
  1. Eleven scripted bvids violated the adapter's `^BV[a-zA-Z0-9]{10}$` shape check (e.g. `BV1STATUSPROB`,
     `BV1FIRSTPAGE11`, `BV1RUNHISTAA1`) → gateway shape errors; all corrected to valid BV+10 ids.
  2. Multi-part fixture built two `make_part_item` rows both with `page=1` → duplicate `(bvid, page_index)`;
     now `page=index + 1`.
  3. Ordering assertions ran without the monotonic `_ingest_clock` (real wall clock could tie) → fixture added
     to the upstream-failure test.
  4. `test_runs_limit_shows_only_recent_rows` named the *third* (newest) collect "oldest" and asserted it is
     hidden — wrong under both old and new ordering; now the first collect is the hidden oldest.
  5. `_collect_once` returned the run id while tests asserted it `== 0`; helper now asserts `main(...) == 0`
     itself and returns the newest run id.
  6. Page-count pin `1 page(s)` contradicted the consumed contract (page-evidence rows incl. the completing
     empty page, mirroring `v_ingestion_run_stats`) → `2 page(s)`.
  7. Resume pin asserted `pn=2` fetched exactly once, but run 1's own completion check legitimately fetched it
     → now pins `pn=1` count `== 1` (page 1 not refetched).
  8. Legacy-manifest row used an invalid `work_id` (`BV1LEGACYROW` without `:p0`) → manifest validation error.
  9. Dead helper `_seam_gateway` removed.
  Plus two new tests: no-flag resume from stored cursor, and `runs --limit 0` validation.

## PM decisions to confirm (made non-interactively; `ask_user_question` unavailable to this subagent)

1. **Legacy test retirement in Task 1 (recommended, done)**: ~34 CLI-level tests pinning the old
   JSONL metadata contract across `test_fetch_meta.py` (14), `test_meta_cursor.py` (10), `test_run_ledger.py`
   (10) were retired in the same commit, and 4 install tests in `test_cli_help.py`/`test_persistence_scale.py`
   were rewritten to the SQLite contract. Grounded in the plan's acceptance criterion "existing test suite
   remains green or any intentional contract changes are updated in this plan". The sidecar **modules** and
   their non-metadata consumers are untouched.
2. **`pyproject.toml` audit-only, no edit (recommended, done)**: the brief lists it as Modify, but Plans 1–2
   already landed everything this task needs (schema.sql package-data — plan 1 `5f22fc6`; `bilibili-api-python
   ==17.4.2` pin — plan 2 `dfb66ba`). Packaging evidence: the isolated-install tests in `test_cli_help.py`
   provision a fresh venv from staged sources + pyproject and pass. Forcing a cosmetic edit would violate
   simplicity-first.

## Self-review notes

- `git diff --check` clean; compileall clean; no dangling references to deleted helpers (verified by grep — the
  remaining `format_cursor_summary` calls belong to the untouched `_cmd_schedule`).
- Drift check re-verified post-implementation: the control checkout's uncommitted prototypes (`refactor/`,
  `schema-3nf.sql`, `schema-proposal.sql`) do not exist in the feature worktree and no source/test imports them.
- STOP conditions: no legacy metadata sidecar is read/written by any of the three commands (new handlers import
  only `storage`/`services`/`sources`); no second executable (entrypoint stays `bili_asr.cli:main`); no
  subtitle/audio/ASR behavior change; no credentials/signed URLs/raw JSON/traces in any output or fixture.
- Contract nuance recorded for QC: the spec's exit-2 wording "Gateway failure after bounded retry" describes the
  retired client's retry budget; the Plan-2 gateway is deliberately fail-fast per page (anti-bot pressure), so
  the CLI's terminal message claims only "cursor unchanged — re-run to resume" and never promises retries. No
  unbounded retries exist on the new path.
- Carry items applied: C1 (documented 10-page default bound), C2 (running rows rendered), C3 (cursor lines
  render stored state; failure message states unchanged/absent cursor), C4 (`display_name = str(mid)` untouched
  in this layer), C5 (unexpected → exit 2 generic bounded message), C6 (`--sessdata`/`BILI_SESSDATA` → gateway
  only; presence-only rendering; no SESSDATA in output/logs/rows).
- Naming: all new names (`MetadataConfig*`, `load_metadata_config`, `resolve_sessdata`, `redact_sessdata`,
  `ARCHIVE_DATABASE_NAME`, `DEFAULT_PAGE_LIMIT`, `_metadata_database_path`, `_open_read_repository`,
  `_run_error_codes`, `_format_run_line`, `_MAX_DISPLAYED_PENDING_PARTS`) were reviewed against the
  `naming-analyzer` skill before introduction (见名之意: configuration/defaults/redaction/database-name are
  self-explanatory; CLI helpers say what they open/format/collect).
- Findings cleanup: zero-residual — no stray files; the only harness-path file written is this report;
  working tree clean after commit; nothing pushed, nothing outside the Working branch touched.
