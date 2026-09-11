---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260825-run-coordinator-offline"
review_range: "5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..2abf3e45ec560266c304a7d7d03438a5b7f137a0"
verdict: "Approve"
generated_at: "2026-08-25"
review_range_note: "initial review 5b392cc..2abf3e4; revalidation fix diff 2abf3e4..d665034 (qc-fix.diff)"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2 (seat 2 of 3)
- Runtime Agent ID: qc-specialist-2
- Runtime Model: glm-5.3
- Review Perspective: Security and correctness risk — redaction guarantees, offline network-freedom structural guarantees, atomicity/crash-safety, state-machine correctness (frozen VALID_STATUSES untouched; terminal-row idempotence), error-code handling, exit-code correctness.
- Report Timestamp: 2026-08-25T22:05:00Z

## Scope
- plan_id: 20260825-run-coordinator-offline
- Review range / Diff basis: 5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..2abf3e45ec560266c304a7d7d03438a5b7f137a0 (merge-base = integration branch HEAD)
- Working branch (verified): plan/20260825-run-coordinator-offline
- Review cwd (verified): /root/workspace/bilibili-asr-archive/.worktrees/20260825-run-coordinator-offline (`git rev-parse --show-toplevel` + `git branch --show-current` both match)
- Files reviewed: 4 (branch-review.diff read once, 1356 added lines: `src/bili_asr/coordinator.py` +585, `src/bili_asr/cli.py` +171 run paths, `tests/test_coordinator.py` +545, `README.md` +51; commit range equals Review range: 6827180, 2abf3e4)
- Analysis methods: git-diff, read, grep — no test/build/lint runs (L3 read-only)

## Findings

### 🔴 Critical
(none)

### 🟡 Warning

- **F-001: `download` and `archive` stage failures are not persisted to the attempt ledger.** `RunCoordinator._stage_download` (coordinator.py:415–436) has no try/except: when `audio_module.download_audio` raises (`StreamDownloadError`, `NoAudioStreamError`, `APIResponseError`, …), the exception propagates without any `download`-stage record. Likewise `write_archive` calls in `_stage_archive_from_subtitle` (coordinator.py:352) and `_stage_asr_archive` (coordinator.py:398) are unwrapped, so an `archive`-stage failure leaves no `archive` record. Only `harvest` and `asr` failures get `("…", "failed", error_code=…)` attempt rows. This violates the plan's locked interface "Stage failures recorded" and Task-1 checkbox "per-item failures recorded" / acceptance criterion "Stage attempts persisted for every executed stage": a download or archive stage that executed and failed is absent from `attempts.jsonl`, so `run --scope failed` (cli.py:1308–1324, which selects rows *from* the attempt ledger) can never reselect rows whose only failures were download/archive-stage failures — they silently drop out of the failed-scope retry loop.
  -> Fix: wrap the seam call in each stage helper in try/except that records `outcome="failed"` with `_safe_error_code(exc)` and re-raises (mirroring the existing `harvest` and `asr` wrappers), and add one test asserting a `StreamDownloadError` and an archive-write failure each leave a `failed` attempt row.
  - Verification: diff/read anchor — `_stage_download` contains a single `_record` call on the ok path only (coordinator.py:433–435); no `except` block in the function body; contrast `_stage_asr_archive`'s `except Exception … self._record("asr", work_id, "failed", …)` (coordinator.py:390–395). `process_row`'s outer catch (coordinator.py:516–526) only appends to `result.failure_codes` and explicitly comments that stage wrappers do the recording.
  - Expected vs observed: expected — every executed stage that fails leaves one `outcome="failed"` record in the sidecar; observed — download and archive stage failures leave zero attempt records (only the in-memory failure summary sees the code).

- **F-002: explicit-scope rerun of an already-terminal row exits 1 ("scope not fully processed") although nothing remains to process.** `_run_scope_rows` selector paths via `_todo_for_bvid` (cli.py:241–265) do not filter terminal statuses, so `run --scope <work_id>` on an `archived`/`gone` row selects it; `process_row` then returns the idempotent skip (`skipped=True, ok=False`, coordinator.py:444–447), and `RunSummary.fully_processed` is `all(r.ok …)` (coordinator.py:209–214), so `_cmd_run` exits 1 (cli.py:1404–1407) for a row that is in fact fully processed. This misreports terminal idempotence on the exit-code surface: the acceptance criterion "Reruns skip already-terminal rows (idempotent…)" holds for artifacts/manifest (proven byte-identical in `test_cli_run_rerun_skips_terminal_rows`) but the exit code contradicts it for explicit scopes. Note `--scope pending` masks the bug because it excludes terminal rows up front (cli.py:1303); the explicit-work_id terminal path is untested.
  -> Fix: treat `skip_reason == "already_terminal"` as processed in `RunSummary.fully_processed` (e.g. exclude `already_terminal` skips from the not-fully-processed condition), and add a test: rerun `run --scope <archived work_id>` → exit 0, manifest/attempts byte-identical.
  - Verification: diff/read anchor — `_todo_for_bvid` has no status filter (cli.py:254–265); `RowResult` for terminal rows sets `ok=False` (coordinator.py:444–447); `fully_processed` requires `r.ok` for every result (coordinator.py:214); exit mapping at cli.py:1404–1407.
  - Expected vs observed: expected — rerun over terminal rows is a no-op success (exit 0); observed — exit 1 with "scope not fully processed" for explicitly requested already-archived/gone rows.

### 🟢 Suggestion

- **F-003: `AttemptLedger.append` fsyncs the temp file but not the parent directory after `os.replace`** (coordinator.py:160–170). On some filesystems the rename itself may not be durable across a power loss, weakening the "crash leaves no partial record" guarantee to "crash leaves the previous content" in the worst case. A one-line `os.open(dirname)` + `os.fsync(dirfd)` after `os.replace` closes the gap.
  - Verification: read anchor — only `fh.flush(); os.fsync(fh.fileno())` before `os.replace` (coordinator.py:168–170); no directory fsync anywhere in the file.
  - Expected vs observed: expected — rename durability across power loss; observed — file-content durability only.
- **F-004: `error_code` doubles as the skip-reason channel** (`"offline"`, `"missing_audio"`, `"missing_subtitle_raw"`, coordinator.py:346/382/465). Schema-legal (int | short str | null) and tested, but conflating machine error codes with human skip reasons will bite when a consumer interprets `error_code` strictly. Consider a separate optional `reason` field (still validated scalar) in a follow-up; no schema change is required now.
  - Verification: read anchor — all three skip sites pass `error_code="<reason-string>"`; `_validate_attempt` cannot distinguish the two uses.
  - Expected vs observed: expected — orthogonal code/reason channels; observed — one overloaded field.

### ⚪ Unconfirmed
(none — all findings carry diff/read/grep anchors reproduced above)

## Source Trace
- F-001: Source Type: git-diff + read; Source Reference: `bilibili-asr-archive/src/bili_asr/coordinator.py` `_stage_download` (L415–436), `_stage_archive_from_subtitle` (L352), `_stage_asr_archive` (L398), `process_row` catch (L516–526); `cli.py` `_run_scope_rows` failed scope (L1308–1324); Confidence: High.
- F-002: Source Type: read + grep; Source Reference: `cli.py` `_todo_for_bvid` (L241–265), exit mapping (L1399–1407); `coordinator.py` terminal skip (L444–447), `fully_processed` (L209–214); test coverage gap in `tests/test_coordinator.py` (no explicit-scope terminal case); Confidence: High.
- F-003: Source Type: read; Source Reference: `coordinator.py` `AttemptLedger.append` (L152–178); Confidence: Medium.
- F-004: Source Type: read; Source Reference: `coordinator.py` skip records (L343–349, L379–387, L463–469); Confidence: High (conflation factual; impact low).

Positive security/correctness verification performed (no findings):
- Redaction: `_safe_error_code` persists only `code`/`last_code` scalar attributes or the exception class name, capped at 64 chars (coordinator.py:59–70); `_validate_attempt` rejects `SESSDATA`/`cookie`/`http(s)://`/`Traceback` markers and absolute artifact paths before any write (coordinator.py:39–48, 102–121); test `test_cli_run_per_item_failure_batch_continues` asserts raw exception text absent from the sidecar. `--sessdata` is resolved live and never persisted.
- Offline network-freedom (structural): under `--offline` `_cmd_run` never constructs a `BiliClient` (cli.py:1369–1372); the offline branch of `process_row` (coordinator.py:450–476) only touches `_subtitle_segments` / `_existing_audio` / `transcribe` / `write_archive`; the pacing sleep is suppressed offline (`live = … and not self.offline`, coordinator.py:540, 576–577). Tests assert `transport.calls == []` for all three offline scenarios.
- Atomicity: append = read-existing + tmp write + fsync + `os.replace`, tmp cleaned on failure (coordinator.py:152–178); test `test_attempt_ledger_append_is_atomic_no_partial_lines`.
- Frozen state machine: `manifest.py` is not in the diff — `VALID_STATUSES` and `classify_risk` untouched (grep confirmed no coordinator writes of non-frozen statuses; only `archived`/`gone` transitions through the existing `store.upsert` validation).
- Terminal-row artifact idempotence and RunLedger `command="run"` record verified by tests in the diff.
- Known plan-QC notes (M3 O(n²) append, M5 sleep precision, T2-M1 double-read, T2-M2 started_at omission) re-assessed against this lens: none rises to Warning on security/correctness — M3/M5 are performance/timing, T2-M1's `get() or get_compatible()` fallback only fires when the primary key is absent, T2-M2 affects timestamp fidelity only.

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 2 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

(F-001 and F-002 are small, localized fixes in `coordinator.py`/exit-code mapping plus one test each; redaction, offline network-freedom, atomicity, and frozen-state-machine guarantees all verified clean.)

## Revalidation

- Reviewer: @qc-specialist-2 (seat 2 of 3 — security and correctness risk)
- Fix range verified: `2abf3e45ec560266c304a7d7d03438a5b7f137a0..d665034` (review cwd HEAD = `d6650345917d45bcdd24dd96260122ff20e3651a`, branch `plan/20260825-run-coordinator-offline`; `git diff --stat` = 5 files, +297/−49, matches qc-fix.diff)
- Method: fix diff read once + direct read/grep of HEAD source (implementer claims treated as unverified until checked); no test/build runs (L3)
- Timestamp: 2026-08-25T22:40:00Z

### Per-finding revalidation

- **F-001 — RESOLVED.** All three previously unwrapped seams now use the harvest/asr wrapper pattern `try → _record(stage, work_id, "failed", error_code=_safe_error_code(exc), started_at=started) → raise`:
  - `_stage_download` wraps `audio_module.download_audio` (coordinator.py:464–474, verified at HEAD);
  - `_stage_archive_from_subtitle` wraps `write_archive` (qc-fix.diff coordinator.py hunk @@ -349,9 +373);
  - `_stage_asr_archive` wraps `write_archive` (hunk @@ -395,9 +426).
  Wrappers are correct: record-then-**raise** (no exception swallowing — the batch-continue behavior still comes solely from `process_row`'s outer catch, coordinator.py:516–526 region unchanged), redaction preserved via `_safe_error_code(exc)` in the failure path, `started_at` reused from stage start. Tests in qc-fix.diff cover all three failure sites plus `--scope failed` re-selection, and assert raw exception text absent from `attempts.jsonl`. `--scope failed` now routes through `RunCoordinator.failed_work_ids()` (cli.py hunk @@ -1306), so download/archive-failed rows re-enter the retry loop — closing the silent-drop-out path.
- **F-002 — RESOLVED.** `RunSummary.fully_processed` (coordinator.py:239–248, verified at HEAD) now reads `not self.risk_interrupted and all(r.ok or r.skip_reason == "already_terminal" for r in self.results)`; `skip_reason = "already_terminal"` is set only at the terminal-row site (coordinator.py:491; other skip_reasons — `missing_subtitle_raw`:372, `missing_audio`:416, `offline`:512 — still yield not-fully-processed, correctly). `_todo_for_bvid` (cli.py:241–265, verified at HEAD) is byte-untouched by the fix diff — selection semantics preserved as required. Test `test_run_explicit_scope_rerun_of_terminal_row_is_idempotent_zero` asserts exit 0 + byte-identical manifest/attempts, exactly the acceptance I asked for.
- **F-003 — RESOLVED.** `AttemptLedger.append` now fsyncs the parent dir after `os.replace` (coordinator.py:187–196, verified at HEAD): `os.open(dirname, O_RDONLY)` → `os.fsync(dirfd)` in try/finally-close, whole block guarded by `except OSError: pass` — best-effort as suggested, sits **inside** the outer `except BaseException` cleanup scope so tmp-file cleanup semantics are unchanged, and atomic-replace semantics unaffected.
- **F-004 — RESOLVED (doc-only, as dispositioned).** README hunk (@@ -115,6 +115,9) documents that `skipped` records carry their reason in `error_code`; schema untouched, matching my original "no schema change required now".

### New-issue scan (security & correctness lens)

- **Sanitize path (qc3-S2 fix touching my redaction surface) — no bypass found.** `_MARKER_RE` strips all six `_FORBIDDEN_MARKERS` case-insensitively (`re.IGNORECASE` covers the literal `"Cookie"`/`"cookie"` duplication, and lowercase `sessdata`/`https://` variants) before the 64-char cap; `_validate_attempt`'s marker check (coordinator.py:132) remains as a second layer. Redaction bypass check: a hostile `.code` string like `"HTTP://X"` or `"SESSDATA=x"` is neutralized by IGNORECASE + escaped literals; partial-marker deletion (e.g. `"https://" → ""`) leaves only non-URL residue capped at 64 chars — no channel for credentials, signed URLs, or tracebacks. Sanitization moves redaction *earlier* (producer side) while keeping the validator: strict improvement, no bypass.
- **Wrapper exception-swallowing — none.** Every new wrapper re-raises after recording; `except Exception` (not `BaseException`) matches the existing harvest/asr wrappers, so KeyboardInterrupt/SystemExit still propagate unrecorded — consistent with the established pattern.
- **Exit-code changes — the two new exit-1 paths are correct.** `--limit <= 0` now fails fast as a usage error before scope resolution (cli.py hunk @@ -1353 — previously `--limit 0` silently selected zero rows and exited 0); `fully_processed` relaxation is scoped exclusively to `already_terminal` and cannot mask genuine failures or non-terminal skips (verified against all four `skip_reason` assignment sites). No other exit mappings changed in the fix diff.
- No Critical/Warning findings on my lens in the fix diff. (The qc1-S1 `identity_from_entry` extraction is a pure delegation refactor — same logic, single seam; noted, no action on my lens.)

### Verdict

**Approve** — both of my blocking Warnings (F-001, F-002) and both Suggestions (F-003, F-004) are resolved with correct, minimal, pattern-consistent fixes; the new sanitize hardening strengthens rather than weakens my redaction guarantees.

**Remaining open findings on my lens: 0**
