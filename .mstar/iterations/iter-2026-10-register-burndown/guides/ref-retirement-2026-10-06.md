# Ref retirement — 2026-10-06 (operator ruling, in place)

> Carrier for the deletion of the three long-lived refs, so no later reader re-forecasts them.
> The pre-delete map with recovery commands is `.tmp/worktree-cleanup-20261006.txt` (same convention as
> `.tmp/branch-cleanup-20260930.txt` / `.tmp/ref-retirement-20260930.txt`).

## Ruling

Operator instruction: **"就地删除，然后提交合并"** — delete the refs in place, then commit the result.
This supersedes the I-000208 "permanent residual" ruling of 2026-10-04 (which said *not* to bypass the
cleanup guard by hand). The exception is recorded here as an operator decision; the guard itself was not
changed and continues to return `cleanup.refuse.unmerged` for what it can no longer see.

## Deleted

| Ref | Tip | Merge evidence | Deleted |
|---|---|---|---|
| local + `origin` `iteration/iter-2026-10-asr-success-attestable` | `d154ef0` | PR #212 → squash `ff11351`; `git diff ff11351 d154ef0` **empty** (tree-identical) | `git branch -D`; remote `--force-with-lease=…:d154ef0…` |
| local + `origin` `iteration/iter-2026-10-ledger-integrity` | `ec9d3d2` | PR #35 → squash `1de04c5`; `git patch-id` identical, scoped diff of the branch's own 6 files **empty** | `git branch -D`; remote `--force-with-lease=…:ec9d3d2…` |
| `origin` `codex/audio-pipeline-reliability` | `f8d795f` | PR #214 merged as `dc1e78e` — two-parent merge, `f8d795f` is parent 2 | remote `--force-with-lease=…:f8d795f…` |
| `refs/remotes/pr/214` (local PR fetch ref) | `88dbea3` | already an ancestor of `main`; superseded by `origin/codex/…` | `git update-ref -d` |
| local only `dev#1` | `a508d34` | identical to `main`, zero unique commits | `git branch -d` |
| `/tmp/refresh-mut-9rifyqig` | — | stale linked checkout (`gitdir: …/.git/worktrees/r2head`, registration long gone); no unique file content | `rm -rf` |

Every deletion used a compare-and-delete lease (deletion refused if the remote moved) or was preceded by
`merge-base --is-ancestor` / tree comparison. Both squash merges were *proved* to carry the branch content
before deletion, so deleting lost no commit reachable from `main`.

## Recovery — still live server-side (re-verified after deletion)

```bash
git fetch origin refs/pull/212/head:refs/heads/asr-success-attestable    # d154ef0
git fetch origin refs/pull/35/head:refs/heads/ledger-integrity         # ec9d3d2
git fetch origin refs/pull/214/head:refs/heads/audio-pipeline-reliability  # f8d795f
git fetch origin refs/pull/17/head:refs/heads/transcript-proofread     # 55f846c (untouched, editorial track)
```

## What did NOT change

- `main` and `origin/main` are untouched by this retirement; the only local branch left is `main`.
- The engine-side gap I-000208 describes (`remoteEvidence` never populates `prMerged`, so a squash-merged
  ref is refused forever) is **still real and still belongs upstream** in `@mstar-harness/cli`'s cleanup
  guard. This page records an operator exception, not a repair.
- `HANDOFF.md`'s §9 ref-retirement record and the 2026-09-30 maps are unrelated and were not edited.
