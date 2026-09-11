# QA Report — 20260825-run-coordinator-offline

- **plan_id**: `20260825-run-coordinator-offline`
- **QA gate**: mandatory, mode **acceptance-only** (evidence reuse + one full-suite runtime confirmation; no business-code changes made)
- **Working branch / Review cwd**: `plan/20260825-run-coordinator-offline` @ `/root/workspace/bilibili-asr-archive/.worktrees/20260825-run-coordinator-offline`
- **Review range / Diff basis**: `5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..d665034` (verified identical to Assignment; branch HEAD = `d665034`, commits 6827180 → 2abf3e4 → d665034)
- **Date**: 2026-08-25

## Verdict: **Pass**

## Runtime verification (owned by QA, run once)

```
cd .worktrees/20260825-run-coordinator-offline/bilibili-asr-archive
PYTHONPATH=src:tests …/.venv-pm/bin/python -m pytest -q
→ 277 passed in 4.70s   (0 failed, 0 errors, 0 skipped)
```

Matches the implementer-reported count exactly (255 baseline + 22 coordinator). Expected 277 / actual **277**.

## Acceptance Criteria → evidence

| # | AC | Status | Evidence |
|---|----|--------|----------|
| 1 | Stage attempts persisted for every executed stage; crash leaves no partial record | **Pass** | `task-1-report.md` (atomic tmp+fsync+`os.replace` ledger, test `test_attempt_ledger_append_is_atomic_no_partial_lines`); QC fix round qc2-F-003 added parent-dir fsync; runtime 277 ✓ |
| 2 | `run --offline` never issues HTTP; missing input → skipped with reason; per-run failure summary | **Pass** | `task-2-report.md` (offline tests all assert `transport.calls == []`; skip reasons `offline`/`missing_subtitle_raw`/`missing_audio`; stderr summary lines); verified statically — offline tests assert empty transport calls (lines 371, 419, 446, 476, 544, 716) |
| 3 | Nonzero exit when scope not fully processed; per-item failures don't stop batch | **Pass** | `task-2-report.md` (`fully_processed`, exit 1 failures/skips, exit 2 risk ceiling; `test_run_failure_summary_and_exit_when_scope_not_processed`); F-002 fix: terminal-row explicit-scope rerun exit 0 (`test_run_explicit_scope_rerun_of_terminal_row_is_idempotent_zero`) |
| 4 | Reruns skip already-terminal rows (idempotent) | **Pass** | `task-1-report.md` (`test_cli_run_rerun_skips_terminal_rows` — manifest/attempts/HTTP/transcribe unchanged); byte-identical rerun test from fix round |
| 5 | `run` does not change `pilot` semantics or frozen risk taxonomy | **Pass** | Static: `git diff 5b392cc..d665034` touches only README/cli/coordinator/page_identity/tests; the sole `_cmd_pilot` match is a diff hunk-context line — new code is appended after it (`_cmd_run`); all 277 (incl. pilot) tests pass |
| 6 | Full Python 3.12 suite passes; no live HTTP | **Pass** | 277 passed, 0 failed (QA-run); network-marker grep of `tests/test_coordinator.py`: only fake transport (`_patch_cli` swaps `build_default_transport`), monkeypatched `transcribe`/`download_audio`/`write_archive`; the two `https://` string hits are redaction-fixture payloads (signed-URL rejection + hostile-code sanitization), never fetched |

## Static checks

- **STOP 1 (no manifest schema change)**: `git diff 5b392cc..d665034 --stat -- bilibili-asr-archive/src/bili_asr/manifest.py` → **empty**; `VALID_STATUSES`/`classify_risk` appear nowhere in the diff (grep exit 1). Not triggered.
- **STOP 2 (offline network-free provable)**: test seam exists — fake transport with `transport.calls` assertion; offline tests prove zero HTTP. Not triggered.
- **STOP 3 (status-machine conflict)**: manifest/status machine untouched (see STOP 1); coordinator routes *by* status, never redefines it. Not triggered.
- **No live HTTP in `tests/test_coordinator.py`**: confirmed — fake transport + stubs only; no `requests`/`urllib`/`httpx`/`aiohttp`/`socket` usage.
- **Surgical scope**: diff = 5 files (coordinator.py new, cli.py +187, page_identity.py +18 extracted seam, README +54, test_coordinator.py new). `bili_client.py` untouched — remains sole HTTP owner.

## Residuals

None. QC consolidated = Approve ×3, zero open findings; engine status reports `residuals: none open`; no register entries needed (M3 carried in-code `simplify:` marker per plan convention).

## Notes

- QA made no business-code changes and committed nothing.
- One behavioral note from implementer (intentional, documented in README): an offline run over rows still needing harvest exits 1 with per-row `skipped (offline)` reasons — consistent with AC #3 wording.
