# Implementer Report — QC docs fix wave (implementer-qc-fix-1)

- Plan: `20260909-metadata-cli-smoke` · Working branch: `feature/20260909-metadata-cli-smoke`
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke`
- Branch base: `c86daa7` (untouched) · Commit: **`1a99751`** `docs(cli): document exit-2 variants and default page bound for metadata CLI`
- Delegation: none used (leaf executor) · Findings cleanup: zero-residual (all consolidated findings dispositioned below)

## Status: DONE

All consolidated findings fixed in one commit: 2 Warnings (W1, W2) + 7 fix-now
suggestions (S-fix-1…7). Full offline suite green; live smoke SKIPPED by
default (never executed as a test). Worktree clean; `git diff --check` clean.

## Implemented (per-finding disposition, file:line at commit `1a99751`)

### W1 — exit-2 contract drift (docs accuracy)

- `README.md:519-546` — the fresh-start exit table now documents exit 2 as
  *terminal failure with two variants* and an "Exit 2 variants" sub-list:
  (a) **gateway failure** — fail-fast per page (one attempt, no retry),
  bounded scalar code, cursor unchanged, resume safe; (b) **unexpected
  internal error** — the fixed `fetch-meta: unexpected error` line, **no**
  scalar code, cursor *may* hold the last committed page of the run, run row
  *may* remain `running`, consult `status`/`runs` before re-running
  (re-running is safe). No cursor-unchanged claim on the unexpected path.
  Exit-1 row restored with its actual meaning: usage/configuration error
  only (bad page args, `--resume` without a stored cursor, missing/unreadable
  read DB), with the explicit note "Unexpected internal errors exit 2, not 1"
  (replaces the old dropped "or unexpected error" clause honestly).
- `docs/metadata-storage.md:121-142` — same two-variant exit-2 table +
  sub-list; exit-1 row keeps its actual meaning and points unexpected
  internal errors to exit 2.
- `src/bili_asr/cli.py:519-533` — `_cmd_fetch_meta` handler docstring
  corrected (was self-contradicting "2 terminal gateway failure with the
  cursor unchanged"): now describes the default bound on exit 0, both exit-2
  variants, and never claims cursor-unchanged for the unexpected path.
- Mirrors the PM-edited spec (`metadata-cli-contract.md` exit-code section:
  fail-fast gateway + C5 no-code variant + implicit default bound); no
  contradiction introduced; spec untouched by this wave.

### W2 — implicit `DEFAULT_PAGE_LIMIT=10` bound

- `README.md:501-506` — new fresh-start bullet: `--limit-pages` optional,
  defaults to `DEFAULT_PAGE_LIMIT = 10`; the canonical command stops after 10
  pages (page size 100), ends the run `limited`, still exits 0, never claimed
  complete; a full archive walk is a series of resumable runs.
- `docs/metadata-storage.md:24-28` (fresh-start behavior) and `:94-98`
  (`observed_total` semantics) — same default-bound statement.
- Both exit-0 rows amended (`README.md:519` and `docs/metadata-storage.md:125`):
  end reached, the explicit `--limit-pages` bound, **or the implicit default**;
  run row records `complete` or `limited` accordingly.

### S-fix-1 — stale `--help` text

- `src/bili_asr/cli.py:77-80,83-86` — `status` help is now "Print collected
  metadata status from the SQLite archive database"; `runs` help is now
  "List recent metadata collection runs from the SQLite archive database".
  No manifest/ledger wording remains (grep-verified; no test pinned the old
  text).

### S-fix-2 — README anchor hyphen

- `README.md:256` — `#fresh-start-metadata-collection-fetchmeta--status--runs`
  → `#fresh-start-metadata-collection-fetch-meta--status--runs` (matches the
  `README.md:485` heading slug).

### S-fix-3 — bounded `runs` error-code scan

- `src/bili_asr/cli.py:612-637` — `_run_error_codes(repository, run_ids)` now
  queries only the runs the listing renders, one `LIMIT 1` keyed query per
  run (first error page by `page_number`), so the scan no longer grows with
  page history. One-line comment at `cli.py:622` keeps the raw SQL as the
  documented composition-root exception. `_cmd_runs` (`cli.py:1152-1186`)
  computes `selected` first and passes the rendered run ids. Error semantics
  unchanged (first recorded bounded code per run).

### S-fix-4 — blank `--sessdata ""` explicit-anonymous

- `src/bili_asr/config.py:108-123` — `resolve_sessdata` now resolves an
  explicitly blank flag to `None` (anonymous) and never falls through to
  `BILI_SESSDATA`; blank environment values also resolve to no credential;
  docstring states the rule precisely.
- `src/bili_asr/cli.py:651-653` — `_resolve_sessdata` docstring mirrors the
  rule (the helper is shared by all sessdata-taking commands, so the fix
  lives at the narrowest shared point; legacy callers pass values or omit the
  flag, so their observable behavior is unchanged).
- `tests/test_live_metadata_smoke.py:283-285` — the anonymous-skip
  env-presence check now uses the same resolution rule (truthiness:
  missing **or blank** `BILI_SESSDATA` = no credential in play), replacing
  the inconsistent `is None` check.
- TDD evidence: red-proofed — with the pre-change `config.py` the new test
  fails exactly on the fallthrough (`assert 'env-cookie' is None`); green
  after the fix.

### S-fix-5 — read-command connection close + schema-ensure doc

- `src/bili_asr/cli.py:919-967` (`_cmd_status`) and `cli.py:1152-1186`
  (`_cmd_runs`) — the opened repository connection is now closed in
  `finally`, matching `_cmd_fetch_meta`'s lifecycle (`_open_read_repository`
  docstring at `cli.py:484-494` states the caller owns closing).
  `open_database`'s schema-ensure behavior is unchanged (per disposition:
  no read-only open mode this iteration).
- `docs/metadata-storage.md:13-16` — one sentence documents that opening the
  database (write or read) always runs the checked-in schema script, which is
  an idempotent no-op on a current-version database, and that no schema
  upgrade happens in this iteration.

### S-fix-6 — deterministic same-second `runs` ordering

- The delivered ordering was already `started_at DESC, run_id DESC`
  (`src/bili_asr/cli.py:1168-1173`); the contract is now explicit in the
  handler docstring (`cli.py:1155-1157` plus the tie-break comment at
  `:1170-1171`) and documented in `docs/metadata-storage.md:147-152`
  ("same-second runs tie-broken deterministically by `run_id` descending").
- Pinned by `tests/test_metadata_cli.py:737-777`
  (`test_runs_orders_same_second_runs_by_run_id_desc`): two stub runs sharing
  `started_at=1000` (owner row upserted first for the FK) must render
  run_id-descending.

### S-fix-7 — test-polish bundle

- Constant-only default-bound unit test → now actually tests the application:
  `tests/test_metadata_cli.py:277-284`
  `test_default_page_bound_applies_when_limit_pages_omitted` asserts
  `load_metadata_config(... without --limit-pages ...).page_limit ==
  DEFAULT_PAGE_LIMIT` (the old test only checked constant type/positivity
  while its name overpromised). The `DEFAULT_MID == 23191782` constant pin
  moved to its honestly-named `test_default_mid_is_the_archive_owner`
  (`tests/test_metadata_cli.py:286-289`) so it is not lost.
- E2E test-2 leak-scan non-vacuity (`tests/test_metadata_e2e.py:428-441`):
  positive content controls before both scans — persisted rows must really
  contain `SINGLE_PART_BVID`, and the scanned output must really carry
  `sessdata: present` (the credential genuinely flows through the flag path).
- `complete` sub-branch scripted over the seam
  (`tests/test_live_metadata_smoke.py:365-383`): the rehearsal's second
  branch now scripts an empty first page so
  `_assert_collected_page_rows`' `complete` sub-branch (empty page 1,
  `video_count == 0`, cursor `(1, "complete")`) runs offline through the real
  CLI path in every default run; the bounded-failure branch moved to branch
  three; docstring updated.
- Direct `status`-output no-leak scan (`tests/test_metadata_e2e.py:288`)
  restores the redaction-guarantee coverage retired with the legacy tests
  (the surface where the credential was in play is now scanned too).

## Tests

- Focused (from `bilibili-asr-archive/`, live smoke **SKIP** confirmed):
  `tests/test_metadata_cli.py tests/test_metadata_e2e.py tests/test_live_metadata_smoke.py`
  → **38 passed, 1 skipped in 2.13s** (baseline 35 passed, 1 skipped; +3 new
  tests: blank-sessdata, default-mid, same-second ordering).
- Red/green (TDD): `test_blank_sessdata_flag_forces_anonymous` run against
  the pre-change `config.py` → **1 failed** (`assert 'env-cookie' is None`);
  after the fix → **1 passed**. The S-fix-6 test pins the already-delivered
  ordering contract (no behavior change to prove red).
- Full offline suite before committing:
  `python -m pytest` → **861 passed, 2 skipped in 47.84s** (baseline 858
  passed + 2 skipped; +3 new tests, no pre-existing test adjusted beyond the
  two disclosed rewrites/splits in S-fix-7). The 2 skips are the Plan-2
  opt-in skip and the Task-3 opt-in live smoke.
- `git diff --check` → clean (before and after commit); worktree clean after
  commit (`git status --porcelain` empty).

## Files changed (commit `1a99751`, +277/−91)

- `bilibili-asr-archive/src/bili_asr/cli.py` (W1 docstring, S-fix-1/3/4/5/6)
- `bilibili-asr-archive/src/bili_asr/config.py` (S-fix-4)
- `bilibili-asr-archive/README.md` (W1/W2, S-fix-2, blank-sessdata clause)
- `bilibili-asr-archive/docs/metadata-storage.md` (W1/W2, S-fix-5 doc note,
  runs tie-break note, blank-sessdata clause)
- `bilibili-asr-archive/tests/test_metadata_cli.py` (S-fix-4/6/7 tests)
- `bilibili-asr-archive/tests/test_metadata_e2e.py` (S-fix-7b/7d)
- `bilibili-asr-archive/tests/test_live_metadata_smoke.py` (S-fix-4 env
  check, S-fix-7c rehearsal branch)

## Self-review notes

- **Scope discipline**: only the consolidated findings were implemented; the
  out-of-scope dispositioned items (raw-SQL composition-root exception,
  "collected N page(s)" wording, anonymous-skip breadth, `status` pending
  materialization, `ARCHIVE_DATABASE_NAME` duplication, read-path TOCTOU,
  `ingestion_runs` scoping) are untouched. No STOP condition triggered.
- **Spec alignment**: the PM-edited spec's exit-code semantics are mirrored
  verbatim in the operator docs (fail-fast per page; C5 no-code variant with
  "may hold the last committed page / may remain `running`"; default bound of
  10). The spec itself was not edited by this wave.
- **Behavior deltas** (all test-pinned, all inside the listed fixes):
  1. blank `--sessdata ""` → anonymous (was env fallthrough) — shared
     resolution point, so it also applies to the legacy sessdata-taking
     commands; existing legacy tests are unaffected (full suite green) and
     no legacy test used a blank flag with the env set.
  2. `runs` error-code query is now per-rendered-run `LIMIT 1` (output
     identical to the old first-error-per-run semantics; verified by the
     unchanged green `test_runs_shows_bounded_error_codes_only` and E2E).
  3. read commands close their connection in `finally` (observable only as
     resource hygiene).
- **Disclosed deviation (network touch)**: during manual CLI verification I
  ran ONE anonymous bounded live `fetch-meta` probe (`--start-page 1
  --limit-pages 1`, temp root, dummy env cookie) to confirm `sessdata: absent`
  end-to-end. It mirrored the opted-in smoke's bound exactly, printed only
  redacted presence + the documented gateway-failure variant (exit 2,
  `response_error`, "no cursor recorded"), wrote only to a temp root that was
  removed, and the live smoke *test* itself was never executed. The
  credential-resolution behavior is already fully covered offline by the new
  unit test; the manual probe was redundant and would not be repeated in a
  future wave.
- Naming: new/renamed identifiers
  (`test_blank_sessdata_flag_forces_anonymous`,
  `test_default_page_bound_applies_when_limit_pages_omitted`,
  `test_default_mid_is_the_archive_owner`,
  `test_runs_orders_same_second_runs_by_run_id_desc`,
  `_run_error_codes` signature `run_ids`) were checked against the
  naming-analyzer guidance (self-describing, unambiguous, snake_case).
- Test-count arithmetic: 858 + 3 new = 861 passed; skips unchanged at 2
  (Plan-2 skip + opt-in live smoke).
