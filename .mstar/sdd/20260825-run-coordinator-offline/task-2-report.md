# Task 2 Report: Offline reprocessing + operator surfaces + docs

- **Status: DONE**
- Plan: `20260825-run-coordinator-offline` (Task 2 of 2, final)
- Branch: `plan/20260825-run-coordinator-offline` (worktree), base 6827180

## Implemented

1. **Offline reprocessing** (`coordinator.py` `process_row`)
   - `--offline` (or `client=None`) now performs full offline semantics:
     never invokes `harvest_subtitle` / `download_audio` (both always
     HTTP). Routing per plan §Interfaces:
     - subtitle raw `{archive_root}/subtitles/raw/{stem}.json` exists →
       archive-from-subtitle (`source="subtitle"`, no ASR);
     - else on-disk audio (`audio/{stem}.m4a`, `.flac` sibling, or the
       manifest's `audio_path`) exists → `transcribe` + archive
       (`source="asr"`);
     - `pending/meta_ok/sub_checked` row with nothing on disk →
       `harvest/skipped/offline`;
     - `subtitle_done` without raw → `archive/skipped/missing_subtitle_raw`;
       `needs_audio`/`audio_ok` without audio → `asr/skipped/missing_audio`.
   - Subtitle raw is preferred over audio when both exist (deterministic,
     avoids unnecessary ASR).
   - The now-unreachable offline branch in `_stage_download` was removed
     (offline rows are routed in `process_row` before any live stage);
     the Task-1 inline harvest-offline check was likewise superseded.
   - `RowResult.skip_reason` added; every skip surface carries a reason
     (`offline`, `missing_subtitle_raw`, `missing_audio`,
     `already_terminal`).

2. **Failure summary + exit semantics** (`cli.py` `_cmd_run`)
   - Per-run failure summary: one stderr line per failed row with its
     redacted code(s) (`run: <work_id>: failed (ASRModelError)`), one
     stdout line per skipped row with its reason.
   - Exit 0 only when the scope is fully processed (`RunSummary.
     fully_processed`: every row ok, no risk interruption; empty selection
     is vacuously complete — rerun-idempotence preserved). Any per-item
     failure or missing-input skip → exit 1. Risk ceiling → exit 2
     (unchanged).
   - **M2 (reviewer)**: scope-resolution errors stay in exit family 1,
     consistent with `_cmd_harvest_subs`/`_cmd_download_audio`/`_cmd_asr`
     (all exit 1 for unresolved/multi-part selectors; only the spec's
     terminal-API taxonomy uses 2). Distinguished behaviorally and
     documented in README: scope errors print **before** any batch output
     and write **no** run-ledger record.

3. **Reviewer Minor fixes in scope**
   - **M1**: `failure_codes` deduplicated — `process_row`'s re-raise catch
     and `run_batch`'s handlers now append each code only once (stderr no
     longer shows "(ASRModelError, ASRModelError)").
   - **M2**: see above.
   - **M4**: dead `broken`/`outcomes` vars removed from
     `test_cli_run_per_item_failure_batch_continues` (replaced with a
     real assertion that the summary line appears exactly once — also
     covers M1).

4. **README** (`bilibili-asr-archive/README.md`)
   - New "Run coordinator (`bili-asr run`)" section: four stages, scope
     semantics, stage-attempt sidecar ledger fields and redaction rules,
     failure summary, exit codes, and a dedicated "Offline mode and the
     live-vs-deterministic boundary" subsection. `run` documented as
     complementing frozen `pilot`. Workflow block gained three `run`
     examples. Style matches existing sections (tables/bullets kept
     concise).

## Tests

```
PYTHONPATH=src:tests …/.venv-pm/bin/python -m pytest tests/test_coordinator.py -q
→ 16 passed
PYTHONPATH=src:tests …/.venv-pm/bin/python -m pytest -q
→ 271 passed, 0 failed   (266 at HEAD + 5 new − 0 removed)
```

New tests (fake transport + stubbed `transcribe`, no live HTTP):
- `test_run_offline_reprocesses_subtitle_raw_on_disk` — archive from
  existing raw JSON; `transport.calls == []` proves network-free.
- `test_run_offline_reprocesses_audio_on_disk` — asr+archive from
  existing `.m4a`; one transcribe call; zero HTTP.
- `test_run_offline_missing_input_skipped_with_reason_zero_http` —
  vanished raw/audio → skipped with `missing_subtitle_raw` /
  `missing_audio` recorded and surfaced; statuses unchanged; exit 1
  ("scope not fully processed"); zero HTTP, zero transcribe calls.
- `test_run_failure_summary_and_exit_when_scope_not_processed` — live
  mode: per-item ASR failure → failed row named once on stderr (M1),
  sibling archived, batch continued, exit 1.
- `test_run_scope_resolution_error_exits_1_before_batch` — unresolved
  selector → exit 1, error on stderr, no batch output, no HTTP.
- Updated `test_cli_run_offline_flag_skips_http_stages` (Task-1
  placeholder expectation rc==0 → rc==1 + skip-reason surface) and
  `test_cli_run_per_item_failure_batch_continues` (M4 + summary
  assertion).

## Files changed

- `bilibili-asr-archive/src/bili_asr/coordinator.py`
- `bilibili-asr-archive/src/bili_asr/cli.py`
- `bilibili-asr-archive/tests/test_coordinator.py`
- `bilibili-asr-archive/README.md`

## Commits

- `2abf3e4` feat(coordinator): offline reprocessing, failure summary, exit semantics + docs (Task 2)

## Self-review notes

- Frozen surfaces untouched: `VALID_STATUSES`, `classify_risk`, manifest
  schema (sidecar JSONL only), seam signatures, `pilot`; `bili_client.py`
  remains the only HTTP owner.
- No credentials/signed URLs/raw exceptions persisted — offline skip
  reasons are fixed short strings; existing `_validate_attempt`
  forbidden-marker scan still guards every append.
- Offline network-free behavior is proven, not assumed: every offline
  test asserts `transport.calls == []` (Task-1 pattern).
- STOP conditions: none triggered — no schema change, test seam existed,
  no status-machine conflict.
- Behavior note: an offline run over rows that still need harvest exits 1
  (scope not fully processed). This is intentional per acceptance
  criterion "nonzero exit when the requested scope is not fully
  processed"; operators see per-row `skipped (offline)` reasons.
- M3 (O(n²) ledger append) and M5 (sleep precision) left as-is per
  instructions (plan-QC notes).

## QC fix round

- **Commit**: `d665034` fix(coordinator): address QC tri findings — stage failure records, terminal-scope exit, hardening
- **Branch**: `plan/20260825-run-coordinator-offline` (single fix commit, on top of `2abf3e4`)
- **Findings cleanup**: zero-residual — all 9 findings fixed in this pass

### Per-finding dispositions

| Finding | Disposition | How | Test |
|---------|-------------|-----|------|
| W1/F-001 (blocking, ×3 seats) | **fixed** | `_stage_download` wraps `audio_module.download_audio`; `_stage_archive_from_subtitle` and `_stage_asr_archive` wrap their `archive_module.write_archive` calls in the same try → `_record(stage, work_id, "failed", error_code=_safe_error_code(exc))` → raise pattern as harvest/asr | `test_run_download_failure_recorded_and_reselected_by_failed_scope` (StreamDownloadError → `("download","failed")` + re-selected by `--scope failed`); `test_run_offline_archive_write_failure_recorded` and `test_run_offline_asr_path_archive_write_failure_recorded` (OSError → `("archive","failed")` on both subtitle and asr paths) |
| F-002 (blocking, qc2) | **fixed** | `RunSummary.fully_processed` now treats `skip_reason == "already_terminal"` as processed; `_todo_for_bvid` filtering untouched | `test_run_explicit_scope_rerun_of_terminal_row_is_idempotent_zero` (rerun `--scope <archived work_id>` → exit 0, manifest/attempts byte-identical) |
| qc1-S1 | **fixed** | extracted `identity_from_entry(entry, key)` into `page_identity.py`; `coordinator._identity_for` delegates, `cli._identity_from_entry` delegates — single seam, no behavior change | covered by the 271 existing tests exercising both callers (all identity paths unchanged) |
| qc1-S2 | **fixed** | `_run_scope_rows` failed-scope branch now calls `RunCoordinator(store.root, store).failed_work_ids()`; method no longer dead, definition lives next to the ledger | exercised by `test_run_download_failure_recorded_and_reselected_by_failed_scope` (second invocation uses `--scope failed` through the wired method) |
| qc1-S3 / qc3-S3 | **fixed** | `_cmd_run` rejects `--limit <= 0` with `run: --limit must be a positive integer` on stderr, exit 1, **before** scope resolution (no HTTP, no batch output) — pattern matches the existing scope-resolution usage-error handling | `test_run_non_positive_limit_is_usage_error` |
| qc2-F-003 | **fixed** | `AttemptLedger.append` fsyncs the parent dir after `os.replace` (`os.open(dirname, O_RDONLY)` → `os.fsync(dirfd)` → close), best-effort `except OSError: pass`; atomic-replace semantics unchanged | covered by `test_attempt_ledger_append_is_atomic_no_partial_lines` (append path now includes the dir fsync) |
| qc3-S1 | **fixed** | `simplify:` comment on `AttemptLedger.append` naming the O(n²) whole-file-rewrite-per-append ceiling and the upgrade path (open-append + flush/fsync, or periodic compaction) | n/a (marker comment per `mstar-coding-behavior`) |
| qc3-S2 | **fixed** | `_safe_error_code` sanitizes string codes through `_MARKER_RE` (case-insensitive strip of all `_FORBIDDEN_MARKERS`) before truncation, so recording never throws and never masks the original stage exception | `test_safe_error_code_sanitizes_forbidden_markers` (hostile `code="https://evil.example/SESSDATA=abc"` → sanitized, recordable, and no marker survives) |
| qc2-F-004 | **fixed (doc-only)** | one README line in the stage-attempt ledger bullet: skipped records carry their reason in `error_code`; schema untouched per plan §Interfaces | n/a (doc-only) |

### Tests

```
cd …/.worktrees/20260825-run-coordinator-offline/bilibili-asr-archive
PYTHONPATH=src:tests …/.venv-pm/bin/python -m pytest tests/test_coordinator.py -q
→ 22 passed
PYTHONPATH=src:tests …/.venv-pm/bin/python -m pytest -q
→ 277 passed, 0 failed   (271 at HEAD + 6 new − 0 removed)
```

### Self-review notes

- Frozen surfaces untouched: `VALID_STATUSES`, `classify_risk`, manifest
  schema, `pilot`, seam signatures; `bili_client.py` sole HTTP owner;
  sidecar only.
- `_todo_for_bvid` filtering untouched for F-002 — the terminal row is
  still *selected* by an explicit scope rerun (visible as
  `selected 1 row(s)` + `skipped (already_terminal)`), it just no longer
  counts as unprocessed in `fully_processed`.
- The unused `page_identity` import left behind in `coordinator.py` after
  the qc1-S1 extraction was removed (kept `PageIdentity` for typing).
- No live HTTP in any new test (download failure monkeypatches
  `bili_asr.audio.download_audio`; archive failures monkeypatch
  `write_archive`; offline tests assert `transport.calls == []`).
- `--scope failed` re-selection test uses the wired
  `failed_work_ids()` path, covering qc1-S2 end-to-end.
- Commit hygiene: no `.egg-info/`, no `uv.lock`, single commit `d665034`.
