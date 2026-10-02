---
title: "A venv editable install resolves to the CONTROL checkout: worktree test runs silently exercise the wrong code"
module: bilibili-asr-archive/tests + any git-worktree test run
date: 2026-10-02
problem_type: testing_pattern
category: testing-patterns
severity: high
status: active
---
# venv editable `.pth` hides the tree under test

## Context
`bilibili-asr-archive/.venv` was installed editable (`__editable__.bili_asr-0.1.0.pth` →
`bilibili-asr-archive/src`). Feature worktrees under `.worktrees/<plan>/` have no venv of their
own, so every worktree test run borrows the control-root venv. `PYTHONPATH` is inserted AFTER
site-packages' `.pth` entries are processed for a plain `python -m pytest`, so a *wrong or
relative* `PYTHONPATH` leaves `bili_asr` resolving to the CONTROL checkout.

## Symptoms
- Tests pass/fail inconsistently depending on the caller's shell environment; the same suite is
  green in one terminal and red in another.
- A regression test for a fix that IS present in the worktree still fails ("assert [1, 1] == [1, 2]").
- Subprocess-spawning tests (children run via `sys.executable`) are the most exposed: they
  inherit the parent's env, so they can exercise code from a different checkout entirely.
- Longer sessions show "subagent failures" that are actually environment mis-resolution.

## Guidance
1. Always pass an ABSOLUTE `PYTHONPATH=<worktree>/bilibili-asr-archive/src` (note: the product
   root is `<worktree>/bilibili-asr-archive/`, NOT `<worktree>/`; `<wt>/src` does not exist).
2. Prove resolution before trusting a run:
   `python -c "import bili_asr; print(bili_asr.__file__)"` must print a path under the worktree.
3. In tests that spawn children, build the child env explicitly (prepend the tree's own `src`)
   rather than relying on inheritance — see `_child_env()` in `tests/test_persistence_scale.py`.
4. When a worktree test result contradicts a reviewed commit, suspect resolution first: check
   `bili_asr.__file__` before investigating the code.

## Why this matters
Every conclusion drawn from the run — "the fix doesn't work", "the subagent failed", "base and
head differ" — is invalid if the interpreter loaded a different tree. This cost hours of
misattribution in iter-2026-10-converge and produced a false regression report.

## When to apply
Any multi-worktree / editable-install project, especially when subagents or subprocess tests
are involved.

## Related
- `worktree-test-invocation.md` (venv binding / wrong-tree hazard)
- `parallel-lane-file-contamination.md` (another multi-lane isolation trap)
