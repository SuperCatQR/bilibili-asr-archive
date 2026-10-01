---
title: "Parallel-lane file contamination: when concurrent subagents share a file, dedup at merge, not by hand"
module: bili_asr.search_index + tests/test_manifest.py + tests/test_search_index.py
date: 2026-10-02
problem_type: testing_pattern
category: testing-patterns
severity: medium
status: active
---
# Parallel-lane file contamination

## Context
iter-2026-10-followup ran 9 implementer subagents on 9 isolated worktrees. Two pairs touched the SAME file (`search_index.py` in 005+W2; `test_manifest.py` in W1+W3). A foreign uncommitted hunk from one lane appeared in another's worktree mid-edit.

## Guidance
- **Isolation is per-worktree, not per-file** — distinct worktrees can still converge on the same source file. When two lanes legitimately edit one file, expect the foreign hunk to surface.
- **Preserve, don't discard** — the affected lane saved the foreign diff to /tmp, restored its own tree with `git checkout -- .`, re-applied, and committed immediately. Both lanes' work survived.
- **Dedup at merge, not by hand** — if the foreign hunk is byte-identical to an already-merged change (W2's `is_stale`), git merge sees those lines as already-present and silently drops the duplicate; only the genuinely-new hunk (005's anti-join) lands. Do NOT hand-revert the "duplicate" — let merge resolve it.
- **Assign conflicting-file lanes to the same reviewer/merge batch** so the conflict is resolved once, with both tests kept.

## Why this matters
Hand-reverting a "duplicate" hunk risks losing real work; letting merge dedup is safe only because the duplicate is byte-identical. The contamination is a signal that two lanes own one file — record it and merge them adjacently.

## When to apply
Any parallel multi-lane dispatch where >1 lane may touch the same source/test file.

## Examples
- iter-2026-10-followup: 005 (search-index anti-join) + W2 (is_stale journal-aware) both touched `search_index.py`; W2's hunk appeared uncommitted in 005's worktree. Merge dedup'd the identical W2 lines; 005's anti-join landed clean.
- W1 + W3 both appended to `test_manifest.py` → git conflict at merge; resolved by keeping both tests.

## Related
- `verify-knobs-through-production-callers.md` — the prior iteration's QC-C1 lesson.
- `worktree-test-invocation.md` — the venv-binding / wrong-tree hazard.
