---
module: bili-asr change and review practice
date: 2026-09-19
problem_type: best_practice
category: best-practices
severity: medium
plan_id: 20260919-artifact-root
applies_when:
  - a piece of behaviour moves to a new place, base or owner
  - fixing a defect where two readers (or a reader and a writer) disagree about one value
  - reviewing or re-verifying a fix wave
  - deciding whether a fix's own invariant holds in the configurations it newly enables
tags:
  - defect-families
  - fix-waves
  - pairing-rule
  - verification
  - reader-writer-agreement
---

# A moved behaviour must carry its pairing rule

## Context

A behaviour that used to be implicit can become configurable: an archive had **one** root, and every reader
and writer therefore agreed by construction about which base a recorded relative path belonged to. Making a
second root possible moved that agreement out of the code's shape and into a *rule* — which base holds this
recorded value — that every site has to apply for itself
([artifact-root-split.md](../architecture-patterns/artifact-root-split.md)). The implementation round produced one such rule, and the review waves then found
three defects of a single family, each in a different place:

| Instance | What disagreed | Observable symptom |
|---|---|---|
| A reader graded a whole row at **one** base, then probed only there (`bilibili-asr-archive/src/bili_asr/integrity.py:195-212` at the reviewed revision) | reader vs the files on disk | for a legacy harvested-caption row: `verify` without the root reported `['malformed_artifact','missing_transcript']`, with the root `['missing_raw_subtitle','missing_transcript']` — **a true defect hidden and a false one invented**, and `recover --defect-code` follows the same wrong set |
| The fix's new locating gate compared a **resolved candidate** against a **lexical base** (`integrity.py:627-640` is the repaired form) | reader vs reader, inside one invocation | with the configured root behind a symlinked ancestor (legal: only a symlinked root *itself* is refused) `verify` reported `missing_transcript` while `coverage` reported the same bundle present |
| The same family survived one branch away: the recorded branch re-confined at the holding base, the **download** branch still measured `download_audio`'s returned absolute path against the write base (`cli.py:2054-2098`, `coordinator.py:432-471`) | writer/command vs command | `pilot` raised `ValueError("invalid audio path")` for a legacy row whose audio sits at the archive root — while `run` paired the same value correctly through `coordinator._declared_audio` |

None of the three crashed, and none failed an existing test: the first two changed a *verdict*, the third a
*row outcome*, and all three lived in code that was written by the same round that introduced the rule.

## Guidance

1. **When a behaviour moves, move the pairing rule with it — explicitly and everywhere.** Enumerate the
   readers and writers that pair the value with its context, and say for each which side of the pair it
   resolves (write base, ordered bases, "the base that holds it"). Sites left on the old implicit rule do
   not fail loudly; they answer a different question.
2. **Make reader/writer agreement the acceptance criterion, not the absence of a crash.** The durable
   phrasing that catches this family is *"the same verdict with and without the configured root"* and *"one
   invocation, two readers, one answer"*. An invariant of that shape is checkable, and the check is the thing
   that fails when a pairing site is forgotten.
3. **A fix is a behaviour change, so re-check the invariant it claims — in the configurations it newly
   enables.** The fix for instance 1 made a previously untested configuration (a lexical configured root
   behind a symlinked ancestor) reachable, and the gate it added was written one-sided: the *fix* introduced
   instance 2. The generalisation: after a fix, ask which inputs the old code refused or never reached and
   the new code now accepts, then test those, not the ones the fix was written for.
4. **After fixing one branch, walk the sibling branches of the same function and the other commands that
   pair the same value.** Instance 3 was one branch away from instance 1's repair, in the same function, and
   the corroborating evidence was internal: the `run` path already paired the value correctly, and its own
   docstring named the legacy case. **Two commands disagreeing about one value is a defect report**; a
   residual framed as "the rule is duplicated in five modules" does not disclose the reachable failure.
5. **Verify the fix by reproducing it, not by accepting it.** Extract the pre-fix revision into a scratch
   tree, run the same probe shape against both trees, and keep a negative control
   that moves the bytes to the other base — so the observed difference is attributable to the fix and the
   base is *chosen*, not inverted. A reviewer who runs the pair over both commits can close a blocker with
   evidence rather than with the wave's word; the same probes are what make the "same inventory at either
   root" claim testable.
6. **Keep the fix inside the ordering other guarantees depend on.** The repair to instance 1 had to leave
   one writer's write-before-raise order untouched (the row's recorded state is rewritten before anything can
   raise, which is what makes the failed pass self-healing). A fix that relocates *where* a value is resolved
   must not also relocate *when* state is written.
7. **Disclose which predicate the pairing uses, because the candidates differ on the same input.** "First
   base that *holds the file*", "first base that *contains the name*" (lexical, existence-blind) and "first
   base that exists" produce opposite answers for an absent or shadowed base; a lexical containment check
   once let an absent configured base shadow a present legacy copy. State the predicate on the surface an
   operator or the next implementer reads.

## Why This Matters

The cost of this family is not a crash but a **wrong report**: a live archive read as broken, a real defect
hidden, a row that silently never advances, guidance that sends an operator to move files that were fine.
Those symptoms are indistinguishable from data problems, they survive every test that does not exercise the
new configuration, and they arrive in the round that is supposed to be the fix. The pairing rule is also the
cheapest thing to get wrong, because it is invisible while there is one possibility: with a single root the
question never comes up, so the code never had to say what it did. Writing the rule down — and re-asking it
of every site each time the value's context changes — is what keeps a configurable path from becoming a
configurable verdict.

## When to Apply

- Any change that turns an implicit invariant (one root, one writer, one owner, one clock) into a
  configurable or multi-valued one.
- Fixing a defect whose symptom is a disagreement about one value: two readers, a reader and a writer, or
  two commands.
- Reviewing or re-verifying a fix wave: check the sibling branches, the newly reachable inputs, and whether
  the wave inverted a value on one side only.
- Not an argument for centralising every rule into one helper: the pairing *site* is legitimately per-family
  (each family keeps its own guard), while the *rule* and its predicate must be named once and applied
  everywhere.

## Examples

### The symmetric fixture that makes a pairing claim discriminating

One row whose artifacts are broken only at the configured root, one row whose only intact copy is at the
archive root, same fixture, one assertion per row: a reader that unions over bases clears the first row's
defect, a reader that falls through to a parsing copy clears the second, and a reader that resolves one side
only clears neither claim. Two rows, both directions, every time
(`bilibili-asr-archive/tests/test_artifact_root_readers.py:209-241`, `:279-330`).

### The dual-commit probe that closes a blocker

```text
per shape:  git archive <pre-fix-commit> | tar -x -C /tmp/base   # the RED side
            run the same probe shape through cli.main against both trees
            negative control: the same bytes at the other base
```

The evidence that counts is the pair, on the same shape, with the control: pre-fix `rc=1` /
`ValueError` / row left `audio_ok`, post-fix `rc=0` / `archived` / bundle at the configured root, control
`rc=0` with the legacy audio directory never created.

## Evidence

- Iteration `iter-2026-09-artifact-root`, plan `20260919-artifact-root` — findings and fix waves:
  `{SDD_DIR}/20260919-artifact-root/task-3-review.md` (the inherited grading defect and the disagreement the
  fix introduced), `{SDD_DIR}/20260919-artifact-root/review/qc1.md` and `{SDD_DIR}/20260919-artifact-root/review/qc3.md` (the sibling branch, and the
  dual-commit probes), `{SDD_DIR}/20260919-artifact-root/review/qa.md` (the shipped pins re-run).
- Code anchors (post-fix): `bilibili-asr-archive/src/bili_asr/integrity.py:195-232` (per-path, per-base
  location), `:627-640` (resolved-to-resolved containment), `cli.py:2054-2098` (the two pilot branches),
  `coordinator.py:432-471` (`_existing_audio` / `_declared_audio`, the same pairing done right),
  `audio.py:284-322` (the untouched write-before-raise order).
- The rule itself, and the disclosed shadowing:
  [artifact-root-split.md](../architecture-patterns/artifact-root-split.md) (the two-base read rule and what
  the ordered probe costs).
- Registered residual for the unresolved half: the pairing rule is re-implemented in five modules
  (`iter-2026-09-artifact-root · R3` in `.mstar/projects/_default/residuals.json`) — the rule is one, the
  sites are many, and that is the next plan's work rather than this one's.
