# QA Report — Plan A mandatory/full

- Role: `qa-engineer`
- plan_id: `20260825-executable-pilot-workflow`
- Working branch: `plan/20260825-executable-pilot-workflow`
- Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow`
- Review range: `559dfcb54816a8e275e5d162ab27f86cde187476..c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3`
- Diff basis: plan A start vs final HEAD
- HEAD verified: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3` (`c4ce9bb Fix pilot QC warnings R1-R3`)
- Ancestor check: `559dfcb` is ancestor of HEAD (exit 0)
- Findings cleanup: zero-residual
- QC input: `{SDD_DIR}/review/qc-consolidated.md` verdict Approve; open Critical/Warning none
- Worktree mutation: none (no git writes)

## Verdict

**PASS / Recommend Done**

Checkout alignment matches the Assignment and locked QC pack. Full suite and focused pilot suite both exit 0. No open residuals to close.

## Scope tested

Acceptance mapped to live pytest on product root
`/root/workspace/bilibili-asr-archive/.worktrees/20260825-executable-pilot-workflow/bilibili-asr-archive`
using injected fakes (no live HTTP).

| AC | Evidence |
| --- | --- |
| Fresh `meta_ok` drives bounded `pilot --n N` to both branch outcomes | `test_cli_pilot_mixed_meta_ok_archives_both_branches` |
| Subtitle rows archived without ASR; audio only after transcript write | mixed-branch test + `test_cli_pilot_missing_asr_dependency_does_not_archive` |
| Missing ASR → nonzero + install hint; row not archived | `test_cli_pilot_missing_asr_dependency_does_not_archive` |
| Unavailable branch coverage → nonzero naming what's missing | `test_cli_pilot_missing_subtitle_branch_exits_nonzero` |
| Completed rerun idempotent | `test_cli_pilot_completed_rerun_skips_archived` |
| Multi-part bvid every `work_id` processed or failed | `test_cli_pilot_multipart_processes_every_page` |
| Focused + full suite pass; no live HTTP | commands below; tests use fake transport / stub ASR |

QC R1–R3 revalidation coverage also present: resume-after-partial-ASR, empty-n skip, named `ASRModelError`, risk-budget summary.

## Commands

Cwd: worktree product root. Interpreter:
`/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python`

### Focused

```text
PYTHONPATH=src …/python -m pytest tests/test_pilot_select.py tests/test_cli_pilot.py -q
.............                                                            [100%]
13 passed in 0.07s
```

### Full (Assignment)

```text
PYTHONPATH=src …/python -m pytest -q
........................................................................ [ 40%]
........................................................................ [ 80%]
....................................                                     [100%]
180 passed in 0.49s
```

## Findings

None.

## Not tested

- Live Bilibili HTTP / real FunASR (out of plan; fakes only).
- README prose walkthrough (AC mentions docs; not re-executed as a user).

## Recommended owners

PM: mark plan `Done` after this L4 PASS. No R# to register.
