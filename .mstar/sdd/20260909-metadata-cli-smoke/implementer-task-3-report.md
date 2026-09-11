# Task 3 Implementation Report — Bounded live API smoke test and operator notes

## Status: DONE

- Commit: `c86daa7` on `feature/20260909-metadata-cli-smoke` (parent `cf490ff`, Task 2).
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke` — verified at start (`pwd`, branch `feature/20260909-metadata-cli-smoke`, HEAD `cf490ff`, clean tree). No mismatch.
- Product source (`src/`, `pyproject.toml`): **untouched** — tests + docs only.

## Implemented

1. **`tests/test_live_metadata_smoke.py`** (new, 2 tests):
   - `test_live_smoke_fetch_meta_one_page_lands_normalized_rows` — the opt-in
     live smoke. Runtime `pytest.skip` unless `BILI_LIVE_SMOKE=1` (default
     runs skip cleanly, never fail). Loud-fail guard (Plan-2 precedent): an
     opted-in run whose environment lacks the pinned
     `bilibili-api-python==17.4.2` distribution fails loudly with `uv sync`
     guidance instead of silently skipping. When opted in, it runs the REAL
     CLI `fetch-meta --mid 23191782 --start-page 1 --limit-pages 1
     --archive-root <tmp_root>` (temporary archive root only), then:
     - exit 0 (happy path): asserts the normalized relationships — exactly
       one user row for the bound mid; every `videos` row joins its
       `bilibili_users` row through `mid`; every `video_parts` row joins its
       `videos` row through `bvid`; one terminal run row
       (`requested_start_page=1`, `requested_page_limit=1`, `finished_at`);
       exactly one page row (`(1,'ok',None)` on the limited path, or
       `(1,'empty',None)` when page 1 completed the run); the fresh cursor
       row exists and advanced (`(2,'limited')` or `(1,'complete')`);
       `observed_total >= video_count` when present; stdout/stderr stay
       clean (`err == ""`, outcome line present).
     - exit 2 (bounded failure): asserts the scalar-only failure evidence —
       terminal run row (`risk_interrupted`/`failed` with `finished_at`),
       exactly one bounded page row with a scalar `error_code`, the user row
       that was committed with the run start, zero video/part/discovery
       rows, zero cursor rows (fresh DB, first-page failure), stderr carries
       the bounded code and `metadata gateway failure` — and then reports
       the outcome (see "Spec reading" below).
   - Hygiene scans in both outcome branches: persisted rows scanned for
     `("sessdata", "pssign", "bilivideo.com")`; CLI output scanned for
     `("pssign", "bilivideo.com")` (the bare word `sessdata` is excluded from
     output scanning because the CLI prints the redacted presence label
     `sessdata: present|absent` by design); when the operator env carries
     `BILI_SESSDATA`, its VALUE is scanned on both surfaces and must never
     appear. Legacy sidecars (`manifest/manifest.jsonl`, `meta-cursor.json`,
     `run-ledger.jsonl`) asserted absent.
   - `test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam` —
     offline rehearsal (runs in every default suite): drives the SAME real
     CLI path over the fake `bilibili_api` seam (shared fixture from
     Plan 2) with the same bounded argv, exercising BOTH outcome branches of
     the live smoke's assertion helpers, with seam sentinels riding the
     payloads and a positive control (`BV1REHEARSE1` in persisted rows) so
     the no-leak scans are non-vacuous. Rationale: the live smoke's SQL
     assertions are the task's non-trivial logic; without this rehearsal
     they would have zero runnable checks in the default suite and would
     first execute at the QA gate's live run.
2. **`docs/metadata-storage.md`** (new): fresh database layout
   (`{archive_root}/archive.db`; normalized entity/run/page/cursor/discovery
   tables with their FK relationships; reserved empty media-boundary tables;
   the three views), no-migration behavior (read-only commands fail exit 1
   on a missing DB; deleting `archive.db` is the only restart path; no
   migration/import/rewrite), no-JSONL contract (bounded scalar
   `error_code` only), credential boundary (`--sessdata` env-resolved,
   cookie-only, never echoed/logged/persisted, presence label),
   `observed_total` semantics (fake = per-page count, live = upstream
   global total; completion keys off the empty item list — never inferred),
   the exact bounded smoke command, and per-command exit code tables
   (including non-terminal `running` rows visible in `runs`).
3. **`README.md`** — added the "Fresh-start metadata collection
   (`fetch-meta` / `status` / `runs`)" section (layout pointer to
   `docs/metadata-storage.md`, no-migration, resume semantics, credential
   boundary, exit-code table, opt-in bounded live smoke with the exact
   command and the anonymous-rejection operational note). Accuracy fixes for
   claims that Task 1's CLI replacement made false: the Workflow block's
   `fetch-meta --resume` line (would exit 1 on a fresh archive; now
   `fetch-meta --mid 23191782 --archive-root archive`), the run-ledger
   section (`fetch-meta` no longer appends `run-ledger.jsonl`; it records
   runs in `archive.db`), the ledger `command` field values, the
   `bili-asr status` inspection bullet (now describes the SQLite read
   surface), and the `harvest-subs`/`download-audio`/`asr` ledger note.

## Spec reading reported for PM/QA (live-smoke bounded-failure semantics)

The assignment delegated the bounded-failure question to the primary spec
(`metadata-cli-contract.md`). My reading, applied:

- The spec's live-smoke section pins the bound (temporary root, UID
  23191782, `--limit-pages 1`, no subtitle/playback/audio/ASR code) and its
  acceptance says "Live smoke creates the expected user/video/part/run/page
  rows in a temporary database" — a success-shape assertion. The spec also
  documents exit 2 as a **valid CLI outcome** ("Gateway failure after
  bounded retry (cursor remains unchanged)"), not a smoke defect.
- Plan-2's QA operational note (recorded in
  `.mstar/sdd/20260909-bilibili-api-ingestion/review/qa-gate.md`, U3)
  documents that anonymous (no-credential) access is currently rejected by
  upstream anti-bot → bounded `response_error`/exit 2, and routes the
  happy-path demonstration to this plan's credential-supporting CLI.
- Therefore: an anonymous exit-2 outcome is treated as the **documented,
  expected no-credential behavior** — after its bounded-failure assertions
  ran, the smoke reports it via `pytest.skip` with a reason naming the error
  code and the credential requirement (clearly-reported skip, not a silent
  pass and not a red failure). A bounded failure when an operator credential
  IS in play is a loud `pytest.fail` (matches the Plan-2 precedent's
  loud-on-real-failure spirit), as is exit 2 with `unexpected error`
  (internal failure without a bounded run record) or any unexpected exit
  code. An anonymous exit-0 success is asserted fully and passes.
- Consequence for the QA gate: running the smoke anonymously yields
  `1 skipped` with the documented reason (valid); running it with
  `BILI_SESSDATA`/`--sessdata` yields either full success assertions or a
  loud failure on a real problem.

## Tests

| # | Command (from the worktree's `bilibili-asr-archive/`) | Output |
|---|---|---|
| 1 | `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v` | `1 passed, 1 skipped in 0.18s` — `test_live_smoke_fetch_meta_one_page_lands_normalized_rows SKIPPED` (live smoke opt-in gate), `test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam PASSED` |
| 2 | Baseline before changes: same interpreter, `pytest -q` | `857 passed, 1 skipped in 48.81s` (pre-change baseline) |
| 3 | Full suite before commit: same interpreter, `pytest -q` | `858 passed, 2 skipped in 46.53s` (both skips are the two opt-in live smokes, Plan-2's and Task-3's) |
| 4 | `git diff --check` | exit 0, clean |
| 5 | `py_compile tests/test_live_metadata_smoke.py` | OK |

- The live smoke itself was NOT executed (assignment boundary: it stays
  skipped by default; the QA gate owns its execution). Its opted-in behavior
  is covered by code review + the offline rehearsal of both branches.
- TDD note: the new tests are verification-only (no product change to drive
  red/green); the skip-by-default gate and the offline rehearsal are the
  runnable checks for the new logic. Both ran green before commit.

## Files changed

- `bilibili-asr-archive/tests/test_live_metadata_smoke.py` (new)
- `bilibili-asr-archive/docs/metadata-storage.md` (new)
- `bilibili-asr-archive/README.md` (modified: +64 / −31)

## Self-review notes

- **`git diff --check`**: clean (run before staging and again after).
- **Docs claims vs actual commands/exit codes**: every documented exit row
  traced to `cli.py` (`_cmd_fetch_meta` 0/1/2; `_cmd_status`/`_cmd_runs`
  exit 1 on missing DB; `runs: empty`; newest-first; non-terminal `running`
  rows rendered; `runs --limit` positivity). The documented smoke command is
  verbatim the brief's Run line. `observed_total` doc matches
  `fake_bilibili_gateway.make_videos_response` (per-page `count`) vs the
  gateway's live `page.count`. Credential boundary matches
  `config.resolve_sessdata` (flag wins) and the redacted presence label.
- **Product source untouched**: `git diff cf490ff..HEAD --name-only` shows no
  `src/` or `pyproject.toml` paths.
- **No credentials/signed URLs/raw JSON/traces**: the test file contains no
  credential values or real URLs; it references the shared fixture's fake
  sentinel constants by name (placeholders like `SESSDATA-VALUE-THAT-MUST-
  NOT-LEAK`, committed in Plan 2) and scans live surfaces for the operator
  env value. Report and docs contain no raw payload shapes.
- **Live smoke bound (STOP condition)**: one page (`--limit-pages 1`), UID
  23191782 (literal `LIVE_SMOKE_MID`, independent of the config default so a
  default change cannot silently widen the bound), temporary archive root
  only (conftest `tmp_root`, gitignored, removed in teardown), no
  subtitle/playback/audio/ASR imports on the test path.
- **Naming**: all new names chosen via the naming-analyzer pass (self-
  explanatory, snake_case, boolean/state clarity): `LIVE_SMOKE_MID`,
  `LIVE_OUTPUT_HYGIENE_TOKENS`, `_pinned_package_version`,
  `_assert_no_credential_or_playback_leaks`, `_assert_collected_page_rows`,
  `_assert_bounded_failure_rows`, `_bounded_live_argv`, and the two test
  names above. Reused Plan-2 precedent names verbatim where the pattern is
  shared: `LIVE_SMOKE_ENV`, `LIVE_HYGIENE_TOKENS`, `_live_smoke_requested`,
  `LEGACY_SIDECAR_PATHS`.
- **Scope decisions flagged for review**:
  1. The offline rehearsal test is an addition beyond the brief's single
     checkbox but within the brief's file list; it exists so the live smoke's
     assertion logic has a runnable check in every default run
     (mstar-coding-behavior §5 minimal-check rule).
  2. Replacing the README's stale "`fetch-meta --resume` and exit 2" section
     (which described the removed `meta-cursor.json` behavior) with the
     fresh-start section, plus the four smaller accuracy fixes — required by
     the acceptance criterion "README ... describe the actual fresh-start
     workflow with accurate commands and exit code meanings"; every other
     README section (manifest SSOT for search/export, pilot/run/schedule,
     coverage/verify) was left untouched.
- **Questions round**: no blocking questions — the assignment resolved the
  one material ambiguity by delegating to the spec (reading documented
  above); everything else was specified by the brief + primary spec +
  Plan-2 precedent.
- **Zero residual**: working tree clean after commit; `.test-tmp` scratch
  from verification runs removed; harness artifacts (briefs/plans/review)
  untouched; no pushes, no cross-branch mutations.

## Attempted / not needed

- Nothing attempted and abandoned. No STOP condition triggered.
