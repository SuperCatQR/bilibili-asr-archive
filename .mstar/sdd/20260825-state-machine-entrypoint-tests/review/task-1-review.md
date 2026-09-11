# Task 1 L2 review — Cover command-level state transitions

Range: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3..10ebd0238e73efe35e0d7a4adaaabfc58a37d470`
Diff: `.mstar/sdd/20260825-state-machine-entrypoint-tests/review/task-1.diff`
Tests: not re-run (PM: 185 passed on `10ebd02`).

### Spec Compliance

- ✅ Spec compliant
- ⚠️ Cannot verify from diff:
  - PM pytest 185 passed on `10ebd02` (Assignment claim; not re-run).
  - Task 2 owns installed entrypoint verification (`bili-asr` console script subprocess execution).

### Strengths

- **Exact state transition coverage**: `test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived` exercises the multi-stage pipeline `meta_ok -> needs_audio -> audio_ok -> archived` through `harvest-subs`, `download-audio`, and `asr --pending`, verifying artifact generation and single transcription invocation.
- **Subtitle bypass path**: `test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr` verifies that `subtitle_done` moves to `archived` without triggering `asr.transcribe`.
- **Fault injection & recovery boundary**: `test_cli_harvest_risk_exhaustion_preserves_last_stable_status` tests risk budget exhaustion (-412) mid-batch, verifying exit code 2, error messaging on stderr (`risk-control ceiling`, `re-run to resume`), preservation of the first item's `subtitle_done` status, and uncorrupted `meta_ok` on the failed row.
- **Dependency boundary**: `test_cli_asr_missing_optional_asr_exits_1_non_archived` simulates missing SenseVoice optional extra, verifying exit code 1, stderr notification, and that manifest entries remain in `audio_ok` rather than falsely marking `archived`.
- **Idempotency & ledger integrity**: `test_cli_asr_rerun_idempotent_leaves_unrelated_rows` checks that consecutive runs do not append redundant rows or mutate untouched/already-archived entries, maintaining exact file and work ID integrity.
- **Clean seam isolation**: Strictly limits monkeypatching to `build_default_transport`, `default_sleeper`, and `asr.transcribe` without touching production business logic or inventing unapproved intermediate statuses.

### Issues

#### Critical

None.

#### Important

None.

#### Minor

- `bilibili-asr-archive/tests/test_cli_asr.py:18`: `artifact_stem` is imported from `bili_asr.page_identity` but not directly referenced in the test functions (harmless unused import).

### Assessment

**Task quality:** Approved
