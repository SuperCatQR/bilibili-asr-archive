# Task 2 Review — Offline reprocessing + operator surfaces + docs

Reviewer: code-reviewer (L2 SDD task reviewer)
Base 6827180 → Head 2abf3e4 (`review/task-2.diff`, 506 lines)
Sources verified: diff + worktree read of `coordinator.py` (process_row / stage helpers / `_record`) and `cli.py` `_cmd_run`. No checkout mutation, no suite re-run (no specific doubt requiring one).

## Spec Compliance

✅ **Spec compliant** — all brief bullets and dispatch-scope items satisfied:

- `--offline` network-free, per plan §Interfaces:
  - `process_row` routes offline rows entirely before any live stage (`coordinator.py:~451-476` worktree); `harvest_subtitle` / `download_audio` are structurally unreachable in offline mode. The now-dead offline branch in `_stage_download` was removed (reaching it would require a client, and offline rows never route there).
  - Subtitle raw preferred over audio (deterministic, avoids ASR); `.m4a`/`.flac`/manifest `audio_path` all honored via `_existing_audio` (with size>0 and OSError-safe checks).
  - `pending/meta_ok/sub_checked` with nothing on disk → `harvest/skipped/offline`; `subtitle_done` without raw → `missing_subtitle_raw`; `needs_audio`/`audio_ok` without audio → `missing_audio`. Matches plan §Interfaces exactly.
  - Every offline test asserts `transport.calls == []`; two of them also assert `transcribe_calls == []` where ASR must not run. Network-free is proven, not assumed.
- Failure summary + exit semantics: `RunSummary.fully_processed` (`not risk_interrupted and all(r.ok)`) drives exit 1 for any per-item failure or missing-input skip; risk ceiling stays exit 2; empty selection vacuously complete (rerun idempotence preserved). Per-row stderr failure lines with redacted codes, per-row stdout skip lines with reasons.
- Stage attempts sidecar-only; `_record` shape unchanged; no manifest schema migration; `VALID_STATUSES` / `classify_risk` untouched anywhere in the diff.
- No credentials/signed URLs/raw exception text persisted — skip reasons are fixed short strings; existing forbidden-marker validation still guards appends (unchanged from Task 1).
- `run` complements `pilot`; README explicitly states this and documents stages, ledger fields, exit codes, and the offline live-vs-deterministic boundary.
- Dispatch scope: **M1** fixed (dedup in `process_row` re-raise catch and via `_fail` closure in `run_batch`, with a `count == 1` test assertion); **M2** fixed (scope-resolution errors exit 1 before batch output, no ledger record, behavior documented in README exit-code bullet + code comment); **M4** fixed (`broken`/`outcomes` dead vars removed, replaced by a real summary-line assertion). M3/M5 correctly untouched.

## Strengths

- Offline routing is centralized at the top of `process_row` — a single choke point guarantees no live seam can be reached, which is what makes `transport.calls == []` a meaningful proof.
- `_fail` closure in `run_batch` deduplicates codes across four exception handlers without repeating the guard; `r: RowResult = result` default-arg binding correctly captures the pre-call `result` (whose `failure_codes` stage wrappers may already have populated).
- Tests assert operator surfaces precisely (exact attempts sequences, summary-line counts, `"selected" not in out` for the scope-error path) rather than just exit codes.
- Test coverage maps 1:1 onto each acceptance criterion, including the updated Task-1 placeholder test (`rc==0` → `rc==1` + reason surface) rather than deleting it.

## Issues

#### Critical

None.

#### Important

None.

#### Minor

1. **Offline routing double-reads on-disk artifacts** — `process_row` offline branch calls `_subtitle_segments` / `_existing_audio` to decide routing, then `_stage_archive_from_subtitle` / `_stage_asr_archive` re-derive the same data internally (file re-read + JSON re-parse). Correct but wasteful; a pass-the-data refactor would remove it. Cosmetic; fine to leave for plan QC alongside M3.
2. **Offline `harvest/skipped/offline` record omits `started_at`** (`process_row`, `self._record("harvest", work_id, "skipped", error_code="offline")`) — other skips pass the pre-computed `started`; here `_record`'s default fills it, so field shape is identical, only the started/finished timestamps collapse to the same instant. No contract impact.

Both are non-blocking polish notes; neither contradicts the brief, plan constraints, or frozen surfaces.

### Assessment

**Task quality: Approved**

- Critical: 0 · Important: 0 · Minor: 2
