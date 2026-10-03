# Direction lock record — iter-2026-10-ledger-integrity

> Lock-time record (`autonomous` mode, `autonomous-direction-lock.md` § Lock outputs stage 1). Written **before** the compass draft and **before** the `direction-lock` anchor. All five fields are carried across into the compass unchanged; this file stays in the package as the durable lock-time record.

## Locked direction

Repair the four P1 defects the 2026-10-02 codebase audit confirmed (plans 011–014): the caption write-back
that fails a successfully-published bundle, the manifest journal replay that silently drops ledger rows,
the ASR run-id collision that silently disables transcript write-backs, and the journal that never compacts
while `save()` keeps an inverted crash window — so that every ledger, journal and write-back record states
the truth about the work the archive actually did.

## Rationale

Selected by the caller's explicit direction (`P1`, i.e. the audit's four P1 findings). Grounding:

| Evidence | Path |
|---|---|
| Audit index (vetted findings 011–014, with the four fingerprints) | `.mstar/plans/audit-2026-10-02/README.md` |
| The four plan bodies (self-contained; STOP conditions + done criteria already present) | `.mstar/plans/audit-2026-10-02/011-…md` … `014-…md` |
| Captured issues for each defect | `I-000165` (011), `I-000164` (012), `I-000166` (013), `I-000167`+`I-000170` (014) |
| Confirmed-fixed delta items and rejected leads that must **not** be re-planned | audit index § Findings considered and rejected / § Red-hardening notes |
| Repo's own record that silent ledger loss is the recurring failure class | `{KNOWLEDGE_DIR}/architecture-patterns/journal-ledger-and-projection-replay.md` |

Why these four and not others (candidates considered, ranked by the autonomous heuristics):

1. **Deferred / roadmap next** — the audit's P1 tier *is* the recorded next work: four HIGH-severity issues
   captured the same day, each with a reproduction or a read-verified mechanism.
2. **Product completeness** — three of the four make a *success* report while the durable record says
   otherwise (a published bundle recorded `failed`; journaled rows dropped; write-backs silently skipped).
   The archive's whole value is that its record can be trusted for resumable work.
3. **Risk / blast radius** — all four are small, independently verifiable source changes with existing test
   files; none requires a schema change, a migration, or live network.
4. **Rejected alternatives** — P2/P3 audit items (docs revalidation, installed-lane witness, the editorial-track
   decision, the measured store-route run) stay in the audit index for the next iteration: they are lower
   leverage and/or need an operator input this iteration does not have. The four landed plans 001–010 and the
   `iter-2026-10-converge` work are not re-opened.

## Acceptance criteria (iteration level)

1. The caption archive path records `archive: ok` and marks the row `archived` when a write-back raises after
   the bundle is published (plan 011).
2. The manifest journal replay cannot be truncated by a legal Unicode line separator, and later rows survive a
   snapshot rewrite (plan 012).
3. Two same-command ASR runs inside one wall-clock second each record their transcript row (plan 013).
4. Journal compaction is reachable from a normal path, and `save()` orders snapshot-write before
   journal-unlink while preserving the snapshot-absent invariant (`I-000138`) (plan 014).
5. Each plan's own verification gates pass with recorded evidence; QC runs on the integrated branch head; the
   four captured issues are closed or explicitly re-scoped with their evidence (plan 011–014).
6. Iteration closes with the compound round landed, PR opened and merge-ready, then post-merge closed.

## Non-goals

- **No schema change or migration.** `archive.db` stays rebuildable-by-policy with no in-place migration; the
  four fixes are source-level. (Excluding this keeps the blast radius small and honours the recorded decision.)
- **No docs/contract revalidation pass** (audit plan 017) — deferred to the next iteration; the README's
  journal/append-cost/store-table drift stays registered as `I-000169`/`I-000181`.
- **No measured store-route run** (audit plan 019) — needs an operator-designated root; stays a recorded
  next-iteration candidate.
- **No editorial-track decision** (audit plan 018) — that track's rescue/re-scope/abandon is an operator call,
  not an implementation task.
- **No dependency, lockfile, or `[asr]` extra change** — the torch/ROCm contract is decided (`I-000136` stays a
  registered posture item).
- **No concurrent-CLI manifest work** — `sequential-no-daemon` is by design.

## Scale budget

**`L`** → 3–4 business plans (cap 4).

**Why L and not the command default `M`:** the caller's explicit direction names the audit's **four** P1
findings, and each is a distinct business defect with its own captured issue, its own mechanism, and its own
verification gate. `M` (2–3) cannot hold them; `L`'s cap of 4 holds exactly them. This is a recorded,
user-driven budget choice, **not** a silent expansion past the cap.

**Not counted** (harness process, per the budget rule): Phase 1 Review & Edit chain, per-plan QC (single seat)
and QA dispatches, the serial integration merges, the compound round, iteration-close, the PR, the merge-ready
loop, and the post-merge close. No process-only plan is created to fill or absorb a slot.

**Overflow to next iteration** (recorded, not silently dropped): audit plans 015–019 and the captured
medium/low issues from the same run.
