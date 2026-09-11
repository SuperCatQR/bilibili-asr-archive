---
plan_id: 20260825-run-coordinator-offline
reviewer: qc-specialist (seat 1 of 3; reviewer_index=1; focus: Architecture coherence and maintainability risk)
review_range: 5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..2abf3e45ec560266c304a7d7d03438a5b7f137a0
task_category: review (L3, read-only)
---

# QC Report — Architecture Coherence & Maintainability

## Reviewer Metadata

- Seat: 1 of 3 (focus: architecture coherence, module boundaries, seam composition vs locked Interfaces, duplication, coupling, test architecture)
- Diff basis: `branch-review.diff` (read in full, 1407 lines) + targeted source cross-checks in the review worktree
- Task category: review — no test/build/lint executed (L3 read-only)

## Scope

- `bilibili-asr-archive/src/bili_asr/cli.py` — new `run` subcommand + `_run_scope_rows`
- `bilibili-asr-archive/src/bili_asr/coordinator.py` — new `RunCoordinator`, `AttemptLedger`, validation/redaction layer
- `bilibili-asr-archive/tests/test_coordinator.py` — 20 tests (fake transport, stubbed ASR)
- `bilibili-asr-archive/README.md` — coordinator / offline-mode documentation

## Findings

### 🔴 Critical

None.

### 🟡 Warning

#### W1: `download` and `archive` stage failures are never recorded in the attempt ledger

- **File/lines**: `src/bili_asr/coordinator.py` — `_stage_download` (diff L686–707), `_stage_archive_from_subtitle` (L605–632), `_stage_asr_archive` archive half (L668–675)
- **Verification**: Read the diff and cross-checked the seam modules in the worktree. Only `harvest` (L749–761) and `asr` (L659–666) wrap their live seam in `try/except` that calls `self._record(stage, work_id, "failed", ...)`. `_stage_download` calls `audio_module.download_audio(...)` with **no** failure recording; neither archive path wraps `archive_module.write_archive(...)` with a failure record. The `process_row` catch-all (L787–797) explicitly delegates failure recording to "the stage wrappers" — which do not exist for these two stages — and `run_batch`'s generic `except Exception` (L844–845) only mutates `RowResult.failure_codes` in memory. Signature cross-check confirms `download_audio` raises `NoAudioStreamError / StreamDownloadError / GoneResponse` and `write_archive` can raise on local IO — none of these reach `attempts.jsonl`.
- **Expected vs observed**: Plan locked Interfaces: "Stage failures recorded; batch continues per `work_id`" and the ledger `outcome` enum includes `failed` for all four stages (`harvest|download|asr|archive`). Observed: a `NoAudioStreamError` (a routine per-item CDN failure the README explicitly promises is "recorded and the batch continues") produces exit 1 and a stderr failure line, but **no** `{"stage": "download", "outcome": "failed"}` record. Consequence on my lens: `--scope failed` (cli.py `_run_scope_rows` L131–147) re-selects rows from `AttemptLedger ... outcome == "failed"` — so download/archive failures silently drop out of the failed-scope retry mechanism, and the `attempt` counter for those stages never advances across retries. This is an incoherence between the ledger design and the feature built directly on top of it.
- **Suggested fix**: wrap `download_audio` and both `write_archive` call sites in the same `try/except → _record(stage, work_id, "failed", error_code=_safe_error_code(exc)) → raise` pattern already used for harvest/asr (three small wrappers; no signature changes). Tests: extend `test_run_failure_summary_and_exit_when_scope_not_processed` with a download failure asserting a `("download", "failed")` record and a subsequent `--scope failed` re-selection.

### 🟢 Suggestion

#### S1: `_identity_for` duplicates `_identity_from_entry` verbatim

- **File/lines**: `coordinator.py` `_identity_for` (diff L552–563) vs pre-existing `cli.py` `_identity_from_entry` (cli.py L272–287) — byte-for-byte the same body.
- **Verification**: read both side by side in the worktree.
- **Expected vs observed**: single identity-conversion seam expected (page_identity is the identity module); observed two copies. Extract `identity_from_entry(entry, key)` into `page_identity.py` and have both callers use it. Low urgency — no behavioral divergence today.

#### S2: dead public method `RunCoordinator.failed_work_ids` duplicates the CLI's failed-scope logic

- **File/lines**: `coordinator.py` L274–278 defines `failed_work_ids()`; worktree-wide grep shows zero call sites (only the definition matches; the CLI's `_run_scope_rows` re-implements the same `AttemptLedger(root).load()` + `outcome == "failed"` set inline, diff L131–147).
- **Expected vs observed**: one owner of "what counts as previously failed" expected; observed the logic in two places, one dead. Either delete the method or (better, after W1) have `_run_scope_rows` call it so the failed-scope definition stays next to the ledger that produces it.

#### S3: `--limit <= 0` silently selects zero rows instead of a usage error

- **File/lines**: `cli.py` `_cmd_run` (diff L186–190): `if args.limit <= 0: rows = []`.
- **Verification**: read in diff; no argparse validation on `--limit`.
- **Expected vs observed**: a negative or zero bound is almost certainly operator error; observed it produces `selected 0 row(s)` and exit 0 (vacuously fully processed) with no diagnostic. Suggest rejecting `--limit < 1` at parse time or in `_cmd_run` before scope resolution. Cosmetic; does not affect correct usage.

### ⚪ Unconfirmed

None — all findings above are code-verified against the worktree.

## Known plan-QC notes assessed (per dispatch instructions, not re-flagged)

- **M3 O(n²) ledger append** (full-file rewrite per append): architecture note — the rewrite is the price of the tmp+fsync+replace atomicity contract documented on `AttemptLedger`; growth is one line per stage attempt (≤4 per row per run). On the coherence lens this is a deliberate, documented trade-off, not a boundary violation. Does not rise to Warning on this seat's lens (performance magnitude belongs to seat 3).
- **M5 sleep precision / T2-M1 double-read / T2-M2 started_at omission**: operational/perf/data-completeness notes on other seats' lenses; no architectural impact observed.

## Positive observations (architecture lens)

- Seam composition honors the locked Interfaces exactly: `harvest_subtitle(client, identity, store, root)`, `download_audio(client, identity, out_path, store=store)`, `transcribe(audio_path)`, `write_archive(root, entry, segments, source=, raw=)` all match the verified signatures; no signature forks, no second HTTP client (`bili_client` remains the sole owner; offline passes `client=None`).
- `VALID_STATUSES`, `classify_risk`, and the manifest schema are untouched (sidecar `coordinator/attempts.jsonl` only), per Global Constraints; `_validate_attempt` enforces relative paths, scalar error codes, and the forbidden-marker redaction scan.
- `RunSummary` properties (`failed` / `skipped_rows` / `fully_processed`) keep exit-code policy out of the coordinator and in `_cmd_run` — a clean boundary.
- Test architecture: fake `RouterTransport` + stubbed `transcribe` + `transport.calls == []` assertions prove network-free offline; the new `CidRouterTransport` subclass is well-motivated (sorted-work_id order ≠ queue order) and documented. Cross-module `from test_audio import ...` follows the established repo pattern (also in `test_page_pipeline.py`, `test_cli_pilot.py`, etc.), so no new coupling is introduced.

## Source Trace

- Diff: `.mstar/sdd/20260825-run-coordinator-offline/review/branch-review.diff` (L70–265 cli, L266–856 coordinator, L857–1407 tests, L1–65 README)
- Worktree cross-checks: `src/bili_asr/subtitles.py` L82–95, `src/bili_asr/audio.py` L83–99, `src/bili_asr/archive.py` L49–70, `src/bili_asr/run_ledger.py` L169–206, `src/bili_asr/manifest.py` L21/L141–147, `src/bili_asr/bili_client.py` L85/L109/L128, `src/bili_asr/cli.py` L241–287/L433+
- Plan: `.mstar/plans/20260825-run-coordinator-offline.md` §Global Constraints, §Interfaces

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 3 |
| ⚪ Unconfirmed | 0 |

**Verdict: Request Changes**

Rationale: W1 — `download`/`archive` stage failures bypass the attempt ledger, violating the locked "Stage failures recorded" interface and silently breaking `--scope failed` re-selection for exactly those failure classes. Fix is small and localized (three try/except wrappers + one test). All other observations are suggestions; seam composition, sidecar-schema discipline, and test architecture are otherwise coherent with the plan.

## Revalidation

- **Fix basis**: qc-fix.diff `2abf3e4..d665034` (fix commit `d665034` verified as worktree HEAD); implementer dispositions in task-2-report.md `## QC fix round` checked against source, not taken on claim.
- **W1 (download/archive failure records) — RESOLVED.** All three wrapper sites present and identical to the harvest/asr pattern: `coordinator.py` `_stage_archive_from_subtitle` (write_archive try/except → `("archive","failed")` → re-raise, L374–384), `_stage_asr_archive` archive half (L428–438), `_stage_download` (download_audio try/except → `("download","failed")` → re-raise, L463–473). Re-selection path confirmed: `_run_scope_rows` failed scope now sources from `RunCoordinator.failed_work_ids()` (cli.py L1303), which reads `AttemptLedger.load()` filtered on `outcome == "failed"` — download/archive failures now land in that set. New test `test_run_download_failure_recorded_and_reselected_by_failed_scope` (qc-fix.diff L305–341) asserts the `("download","failed")` record, redaction of raw exception text, and `--scope failed` re-selection; two further tests cover both archive write-failure paths. Locked interface restored.
- **qc1-S1 (`_identity_for` duplication) — RESOLVED.** Single seam `page_identity.identity_from_entry` (page_identity.py L84–99, verbatim body); both callers delegate: `coordinator.py` `_identity_for` L315–316 imports it at module level, `cli.py` `_identity_from_entry` L268–271 (kept as thin alias for its three existing call sites — acceptable). No behavioral divergence possible.
- **qc1-S2 (dead `failed_work_ids`) — RESOLVED.** CLI failed-scope now calls `RunCoordinator(store.root, store).failed_work_ids()` (cli.py L1303, diff L48–56); single owner of the failed-set definition, living next to the ledger. No remaining call-free duplicates.
- **qc1-S3 (`--limit <= 0`) — RESOLVED.** `cli.py` `_cmd_run` L1344–1348: usage error printed to stderr, exit 1, before scope resolution; the silent `rows = []` branch removed (diff L72–80). Test `test_run_non_positive_limit_is_usage_error` asserts rc=1, no transport calls, no selection output.
- **New-issue scan on my lens (fix diff)**: the diff also carries other seats' fixes — F-002 `fully_processed` treating `already_terminal` skips as processed (coherence with the skip semantics is correct and documented), qc3-S2 `_sanitize_code_str` (strip-then-truncate order is right; keeps `_record` from throwing on hostile `.code` strings), qc2-F-003 parent-dir fsync (best-effort, inside the existing atomic-replace path — no boundary change), and a `simplify:` comment on the O(n²) append matching my original M3 assessment. No new Critical/Warning findings on the architecture/maintainability lens.

**Verdict: Approve** (was: Request Changes)

- Remaining open findings on this lens: **0** (W1 resolved; S1–S3 resolved).
- Timestamp: 2026-08-25 (fix round revalidation, seat 1 of 3).
