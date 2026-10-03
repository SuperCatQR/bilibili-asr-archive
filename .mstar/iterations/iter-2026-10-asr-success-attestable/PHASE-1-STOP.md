# Phase 1 STOP — record at the integration-worktree step (2026-10-03)

Phase 1 is complete through the PM lock; it **cannot** execute the integration-worktree step.
This note records why, so the next session does not re-derive it.

## Where it stopped

`mstar-iteration/references/phase-2-worktree-lease.md` §2.3
「Integration worktree (Phase 2 entry) + control root」**step 2**, which reads:

> Resolve the **control root** = the **primary checkout** (main worktree) via Git
> (`readMainWorktree`); verify its attached branch equals the recorded **`Main worktree branch`**
> from the main plan header and is not owned by any non-terminal workflow — mismatch → **STOP**
> (never switch main; never substitute `branch.base`).

## The mismatch (measured, not inferred)

| | value |
|---|---|
| Observed main-worktree branch | **`main`** |
| Recorded in both plan headers | **`dev`** |

Both plan headers record `dev` because that was the correct observation when the Phase 1 draft was
written. The control root has since been switched by the **parallel session** — its reflog shows
`dev → e2e → main → thinking`, and it now sits on `main`.

The second half of step 2 **passes**: neither active iteration's integration branch is `main`
(`iteration/iter-2026-10-ledger-integrity`, `iteration/iter-2026-10-asr-success-attestable`), so the
control root is not owned by a non-terminal workflow.

## Why this is a real STOP and not a bookkeeping annoyance

1. The contract is explicit, and its prohibition — *never switch main, never substitute
   `branch.base`* — rules out the two convenient fixes.
2. The control root is **shared with a live parallel session** (`iter-2026-10-ledger-integrity`,
   plan `journal-compaction-lifecycle` is `InProgress` with an active lease). That session switches
   this checkout's branch mid-run; creating an integration worktree against a control root someone
   else is moving is how the earlier `status.json` cross-contamination happened in this very repo
   (an earlier commit here accidentally carried the other session's register row, and had to be
   stripped).
3. The engine already reports the consequence directly:
   `workflow.selection.unbound-multi-active` — *2 active lifecycles in status.json workflows[] —
   this session has no lease, is not inside a workflow worktree and has no stored selection; pick
   one for this session (writes pause until then)*. Binding is by lease holder, cwd inside a lease
   worktree, or cwd inside `integration_worktree_path` — all of which require the step that stopped.

## State that is complete and safe

- Phase 1 review chain: **three seats, in order, all delivered** (product-manager → architect →
  writing-specialist).
- The one blocking open question (Q6) is **converged by operator ruling** into D11.
- Compass `status: locked`; both plan rows registered; snapshot `running` / `phase-1-prepare`.
- `I-000188` deferred by operator ruling, registered as `I-000201`; `asr-coverage-attestation`
  is `Blocked` in the compass.

## The remedy (two paths, neither of which this session may take unilaterally)

**A. Re-record the observation.** Update `Main worktree branch` in both plan headers from `dev` to
`main`, with an explicit note that the observation changed because the parallel session moved the
control root — then re-enter §2.3. This is honest *provided* the change is recorded as a
re-observation, never as a silent edit, and *provided* the control root has stopped moving.

**B. Wait** for `iter-2026-10-ledger-integrity` to reach its terminal state, so this iteration is
the only active lifecycle and the shared control root no longer has a live competitor.

**Recommendation: B, then A if the root is still on `main`.** Proceeding under path A while a live
parallel session is switching this checkout buys a registration that the next switch can clobber —
which is exactly the failure this STOP exists to prevent.
