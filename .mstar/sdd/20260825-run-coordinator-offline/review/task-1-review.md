# Task 1 Review — Stage-attempt ledger + coordinator core

Reviewer: code-reviewer (L2 SDD task reviewer)
Range: 5b392cc..6827180 (diff file read once; checkout not mutated)

## Spec Compliance

**✅ Spec compliant** — all three brief items and all global constraints verified against the diff:

- **Atomic append-only ledger** ✅ — `AttemptLedger` at `{root}/coordinator/attempts.jsonl`; tmp file + fsync + `os.replace`; tmp removed on failure; per-(work_id, stage) monotonic attempt counter rehydrated from disk on init (test `test_attempt_counter_increments_across_instantiations`).
- **Stage execution by manifest status; failures recorded, batch continues** ✅ — `_HARVEST_STATUSES` → harvest; `subtitle_done` → archive-from-raw; `needs_audio` → download → asr → archive; `audio_ok` → asr → archive. Per-item exceptions recorded via `_safe_error_code` (scalar codes / class names only) and the loop continues; `RiskBudgetExhausted` → exit 2 with `risk_interrupted`; `GoneResponse` → terminal `gone` + continue.
- **Bounded `--limit`; rerun skips terminal rows** ✅ — `TERMINAL_STATUSES` skip in both scope resolution and `process_row`; `test_cli_run_rerun_skips_terminal_rows` asserts manifest, attempts, HTTP calls, and transcribe are byte-identical/unchanged on rerun.
- **Seam composition, no forks** ✅ — `harvest_subtitle(client, identity, store, root)`, `download_audio(client, identity, out_path, store=store)`, `transcribe(audio_path)` (`model_name=None` default), `write_archive(root, entry, segments, *, source, raw)`. No second HTTP client (`bili_client.BiliClient` remains the only owner).
- **No probe split; `probe-subs` absent** ✅.
- **Sidecar only; `VALID_STATUSES` / `classify_risk` / manifest schema untouched** ✅ (diff touches only cli.py, coordinator.py, tests).
- **Redaction** ✅ — two layers: `_safe_error_code` (scalar/class-name only, 64-char cap) and `_validate_attempt` forbidden-marker scan (SESSDATA/cookie/http(s)/Traceback) + absolute-path rejection; test asserts raw exception text not persisted.
- **No live HTTP in tests** ✅ — `RouterTransport`/`CidRouterTransport` fake transports + monkeypatched `transcribe`.
- **`--offline` (Task-1 scope)** ✅ — harvest/download guarded by `self.offline or self.client is None`, recorded `skipped/offline`, never invoked; test asserts `transport.calls == []`. Full offline semantics correctly deferred to Task 2.
- **`run` complements frozen `pilot`** ✅ — `_cmd_pilot` untouched; `run` is a new subcommand.

⚠️ Cannot verify from diff: the implementer's claim of 11/266 passing tests (venv lives in a sibling worktree). No specific doubt found that warrants a focused re-run.

## Strengths

- The self-reported stale-upsert bug fix (`_stage_asr_archive` mutating `audio_path` before the single archived upsert) is real and correctly resolved in the final code.
- `CidRouterTransport` routing `player/wbi/v2` by cid (and playurl via an explicit queue to avoid substring collision) is a well-reasoned test harness that keeps row-order independence honest.
- Redaction is enforced at write time (validation raises before any byte hits disk — the reject test asserts the file is not created).
- Scope resolution reuses `_todo_for_bvid` instead of duplicating selector logic.

## Issues

### Critical
None.

### Important
None.

### Minor
1. **Duplicated failure codes** — `coordinator.py` `process_row` (~line 676) appends `_safe_error_code(exc)` then re-raises; `run_batch`'s generic `except Exception` (~line 726) appends the same code again. A failed ASR row ends with `failure_codes == ["ASRModelError", "ASRModelError"]`, so stderr prints `failed (ASRModelError, ASRModelError)`. Cosmetic but misleading.
2. **Exit-code conflation** — `cli.py` `_cmd_run`: a scope-resolution error (`unresolved selector`, multi-part needs page) returns 1, the same code as per-item failures. A distinct code (or 2-family) would be friendlier to scripting; the implementer already flagged exit-code polish as a Task-2 follow-up.
3. **O(n²) ledger appends** — each `append` re-reads and rewrites the whole JSONL via tmp+replace. Correct and atomic, but a large ledger will slow every stage attempt. Fine at current scale; worth noting before any long archive run.
4. **Dead test code** — `test_coordinator.py` `test_cli_run_per_item_failure_batch_continues`: `broken` set and `outcomes` dict are built then `del`eted unused; leftovers from an earlier iteration of the test.
5. **Sleep between skipped live rows** — `run_batch` sleeps 3s after a `skipped` offline/disabled row when `live` was computed from status only. Harmless (offline runs pass `sleep` default; CLI path only sleeps for non-offline), just slightly imprecise.

## Assessment

**Task quality: Approved**

Minor issues only; none block Task 2. Counts: Critical 0 / Important 0 / Minor 5.
