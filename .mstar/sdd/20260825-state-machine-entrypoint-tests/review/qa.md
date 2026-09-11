# QA Report — Plan B mandatory/full

- Role: `qa-engineer`
- plan_id: `20260825-state-machine-entrypoint-tests`
- Working branch: `plan/20260825-state-machine-entrypoint-tests`
- Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
- Review range: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3..79652889e7e7b7a6c8419a4bf30badf6f73ee757`
- Diff basis: plan B start (plan A merge) vs final HEAD
- HEAD verified: `79652889e7e7b7a6c8419a4bf30badf6f73ee757` (`7965288 Add installed console-script and module entrypoint integration tests`)
- Ancestor check: `c4ce9bb` is ancestor of HEAD (exit 0)
- Findings cleanup: zero-residual
- QC input: `{SDD_DIR}/review/qc-consolidated.md` verdict Approve; open Critical/Warning none
- Worktree mutation: none (no git writes)

## Verdict

**PASS / Recommend Done**

Checkout alignment matches the Assignment and locked QC pack (`qc-consolidated.md` verdict Approve). Full test suite (189 passed) and focused transition/entrypoint suites pass with 0 failures and no live network/model dependencies. No open residuals to close.

## Scope tested

Acceptance mapped to live pytest on product root
`/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests/bilibili-asr-archive`
using injected fakes (no live HTTP or model downloads).

| AC | Evidence |
| --- | --- |
| Audio-ASR terminal path `meta_ok -> needs_audio -> audio_ok -> archived` covered through `cli.main` | `test_cli_asr.py::test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived` |
| Subtitle terminal path `meta_ok -> subtitle_done -> archived` covered through `cli.main` with ASR skipped | `test_cli_asr.py::test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr` |
| Risk exhaustion → exit 2 with last stable manifest `status` preserved and resumable summary | `test_cli_asr.py::test_cli_harvest_risk_exhaustion_preserves_last_stable_status` |
| Missing optional ASR extra → exit 1 and record non-archived | `test_cli_asr.py::test_cli_asr_missing_optional_asr_exits_1_non_archived` |
| Reruns idempotent; no duplicate JSONL rows; unrelated rows untouched | `test_cli_asr.py::test_cli_asr_rerun_idempotent_leaves_unrelated_rows` |
| Installed console script `bili-asr --help` & `status` exercised as subprocess without PYTHONPATH forcing | `test_cli_help.py::test_installed_entrypoint_help_exits_zero`, `test_cli_help.py::test_installed_entrypoint_status_empty_archive`, `test_cli_help.py::test_installed_entrypoint_status_with_manifest_records` |
| Module entrypoint `python -m bili_asr` tested separately and not treated as install proof | `test_cli_help.py::test_module_entrypoint_help_exits_zero`, `test_cli_help.py::test_module_entrypoint_status_empty_archive` |
| Mixed per-video exit-code contract preserved without modification | Checked: no out-of-scope CLI contract mutations |
| Git status clean; only in-scope test files modified in range | `git status --short` clean; diff limited to `test_cli_asr.py` & `test_cli_help.py` |

## Commands

Cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests/bilibili-asr-archive`  
Interpreter: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python`

### Focused (Task 1 & Task 2)

```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_cli_asr.py tests/test_cli_pilot.py tests/test_manifest.py tests/test_cli_help.py -q
.........................................                                [100%]
41 passed in 3.56s
```

### Full (Assignment)

```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest -q
........................................................................ [ 38%]
........................................................................ [ 76%]
.............................................                            [100%]
189 passed in 3.77s
```

## Findings

None. Non-blocking suggestions from QC1–QC3 (timeout guards, type annotations, unused import) were cosmetic and do not impact contract compliance or test suite health.

## Not tested

- Live Bilibili HTTP / real FunASR model download (out of plan scope; strictly fakes/stubs).
- Full live corpus operations (reserved for operations iteration).

## Recommended owners

PM: mark plan `20260825-state-machine-entrypoint-tests` as `Done` after this L4 PASS. No R# residuals to register.
