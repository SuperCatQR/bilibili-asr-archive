---
title: "Reachability is measured, not argued: what a change makes reachable, and whether a finding's attribution holds"
module: bili-asr change review
date: 2026-10-03
problem_type: best_practice
category: best-practices
severity: medium
plan_id: journal-compaction-lifecycle
applies_when:
  - reviewing a trigger, threshold, guard, retry or ordering whose own tests are green
  - a finding claims a change newly made a path reachable
  - judging whether a defect is pre-existing, and therefore in scope or not
  - adding a guard and deciding what the guard does not protect
tags:
  - reachability
  - change-review
  - refutation
  - twin-probe
  - pre-existing-defects
---

# Reachability is measured, not argued

## Context

Three review rounds in iteration `iter-2026-10-ledger-integrity` turned on the same question, and each time the
answer came from a measurement rather than from reading the diff:

- **A change widened an existing hole without touching it.** The manifest journal's torn-tail hole (a crash
  fragment before complete rows makes those rows unreachable to every reader) was pre-existing but effectively
  unreachable: the old fold trigger required a per-instance counter, `_appends_since_compact >= 256`, from the
  instance that folded. The replacement trigger is a function of bytes on disk
  (`journal_bytes >= max(_JOURNAL_MIN_COMPACT_BYTES, 2 × snapshot_bytes)`), so a handful of appends by *other*
  handles reaches the same state: an out-of-band fragment plus 3 + 3 appends from two handles, and the pre-fix
  fold unlinked a journal holding three fsynced rows (twin probe: 0/3 surviving pre-fix; journal retained at
  628 B with the rows byte-present at the fix). The change was correct by its own contract and made a latent
  durable-deletion path reachable.
- **A pre-existing exception class became reachable one level deeper.** `RecursionError` from a deeply nested
  journal line was already fatal for a line of its own; once the stranding scan began *parsing* the lines behind
  a fragment, it became reachable there too — so the commit that widened the exposure had to carry the fix.
- **A finding's attribution was wrong, and the probe said so.** A reviewer reported that widening the
  `migrate_legacy_rows` rewrite base *newly* made a collision path reachable (the journal-only destination row
  becoming visible to `dest_occupied`). Byte-identical twins of the pre-fix and post-fix modules, driven through
  the public API with the same ledger, refused identically at both bases — the change alters which row *wins*
  for keys present in both views, not the key set the collision check examines. The finding was refuted and
  recorded, not "fixed".

## Guidance

1. **Ask what a change makes reachable, not only whether it is correct.** For a trigger, guard, threshold,
   retry or ordering, the review question is *which paths the new condition admits that the old one did not*.
   Three axes cover most of it: **frequency** (256 appends → a handful), **actor** (own instance → any handle),
   **depth** (a line of its own → lines behind a fragment). Correctness of the new behaviour is necessary and
   not sufficient.
2. **Answer with a probe, not with reasoning.** Extract the pre-fix module to a scratch tree, build the same
   ledger through the public API against both bases, and record a two-column outcome table. Hash both source
   files so the only variable is the change — a twin that differs in a comment is still a different input to
   the reviewer's eye.
3. **A finding's attribution is a claim with a direction.** "This change newly made X reachable" is falsifiable
   in one probe; run it before acting. When the probe refutes it, record the refutation where the finding was
   raised, with the table, or the refuted story is carried forward as history and the same "fix" is proposed
   again later.
4. **Pre-existing + more reachable is a decision, recorded.** Fix it in this round or route it, and say which.
   Routed here into the live sibling plan on the same file and invariant rather than deferred, because a later
   round would re-open the same module a third time; the compass decision carries the rationale.
5. **A guard changes the reachability of the property it does not own.** The refuse-to-unlink guard closed
   deletion and created unbounded growth plus unreadability while the fragment stayed: the frontier moved from
   "rows are deleted" to "rows are unreachable and the residue is unbounded". Enumerate what the new guard does
   not protect and check none of it got worse; the settlement that publishes stranded records before the
   discard is what moved it back.

## Why This Matters

Reachability is invisible in a diff. Both changes here passed their own tests, a review of their own contract,
and each plan's own QA — between them they moved a durable-data-loss path from "needs 256 appends" to "a handful
of appends from any handle". The cost of not asking is paid by whoever reaches the new path. The cost of not
probing an attribution is paid twice: once implementing a fix for a defect that did not exist, and again when
the refutation is missing from the record.

## When to Apply

- Reviewing any change to a trigger, threshold, guard, retry or ordering — especially when its own tests are green.
- A sentence claims "newly reachable", "no longer possible", "now always" (see
  [claim-scope-discipline.md](claim-scope-discipline.md)).
- A defect is judged pre-existing: the judgement needs the *reachability* comparison, not only the blame comparison.
- A guard is added to correct one failure mode: name the modes it leaves open.

## Examples

```bash
# The twin-probe shape: both bases, same fixture, public API only
git show <prefix>~1:path/to/module.py > /tmp/pre/module.py
git show <prefix>:path/to/module.py  > /tmp/post/module.py
sha256sum /tmp/pre/module.py /tmp/post/module.py   # record both hashes
# build the same ledger by save()/upsert() in each tree, then compare the outcome tables
```

The two measured outcomes worth recognising by shape: pre-fix **journal unlinked, 0/3 rows surviving** vs head
**retained at 628 B with the rows byte-present**; and the refutation table — pre and post bases both
`RAISED ManifestMigrationCollision` when the journal-only destination row was seeded, and both `migrated` when
it was not.

## Evidence

- Iteration `iter-2026-10-ledger-integrity`; plans `journal-compaction-lifecycle` and `journal-replay-integrity`
  (SDD consolidation for the compaction plan carries the two Criticals, the `RecursionError` widening and the
  refuted attribution; the replay plan's consolidation carries the routing finding).
- The plan's own records of the routing decision and the refutation, including the four-row probe table:
  `{PLAN_DIR}/journal-compaction-lifecycle.md` (the PM ruling on Task 4's flagged concern and the refutation
  section).
