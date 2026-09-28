---
module: mstar lifecycle (iteration-close, acceptance criteria, residual registers)
date: "2026-09-28"
problem_type: best_practice
category: best-practices
severity: high
plan_id: 20260926-video-metadata-enrichment; 20260926-audio-inventory
applies_when:
  - a completion state was written by a session other than the one that produced the work
  - an acceptance criterion or plan row reads Done and the close gate is about to be entered
  - a stored claim (a plan row, a compass row, a report) is being used as the reason to proceed
  - reconciling a register, snapshot or compass against the tree it describes
  - an iteration or plan is found to be already closed by someone else
tags:
  - completion-claims
  - evidence-pointer
  - register-truth
  - iteration-close
  - external-writer
  - unearned-done
  - close-gate
---

# A completion claim is only as good as the evidence pointer beside it

## Context

Two independent instances in one iteration, both found by the same act — reading the *evidence pointer* a
completion row cited instead of the row's own status word:

1. **A compass acceptance criterion was recorded as met for a command that never existed.** Compass AC 6 read
   "`derive-audio-inventory` reports `recorded`/`already`/`missing`/`unlinked` … and exits 0 on a zero-row
   reconciliation", and the row carried this as its evidence: *"the command's own test over both a populated and
   an empty root"*. The command did not exist in **any** commit:

   ```
   $ grep -o 'add_parser("[a-z-]*"' src/bili_asr/cli.py | wc -l
   23                                    # none of them named *inventory*
   $ git log --all -S"derive-audio-inventory" --oneline
   ...                                   # matches plan and contract PROSE only, never code
   ```

   The cited test file (`tests/test_audio_inventory.py`) had never existed either.

2. **A plan row read `Done` with 0 of 15 task steps checked.** Its own frontmatter said
   `status: registered`, and the compass carried it as `Done` at `progress: 0` — with a note attributing the
   completion to *another* lifecycle's PRs. The attributable part was real (two of its acceptance criteria *were*
   satisfied, by work shipped elsewhere); the plan's own three tasks had never been executed.

Both states had been written by a **different session** than the one that owned the work. Neither was a lie
about the code — each was a claim whose supporting pointer had never been resolved, and in the second case a
substitution of *someone else's* finished work for the plan's own unfinished work.

## Guidance

1. **Resolve the pointer, not the status word.** A row that says `Done` is a claim; the evidence column beside
   it is the claim's basis. Before a close gate accepts it, run the thing the evidence names — the file, the
   test id, the command — and check it exists and passes. A pointer to a file that has never existed is the
   cheapest possible detection, and it is the one this iteration actually caught the defect with.

2. **`git log -S"<symbol>"` over all refs is the decisive probe for "was this ever built".** Prose and code
   leave different traces: a command, class or column that appears only in plan/contract/spec text and never in
   a diff was *specified*, not *delivered*. `--all` matters — a branch that was never merged still counts as
   never shipped.

3. **Distinguish "the criterion holds" from "this plan delivered it".** A criterion can be satisfied by work
   that arrived through another lifecycle. That is a legitimate state, but it must be recorded as such — *AC 4
   holds (asserted at `test_storage_queue_writes.py:174-177`), earned by PR #21* — rather than folded into the
   owning plan's `Done`. Read the `plan_id`/`PR` provenance on the evidence, not just its pass/fail.

4. **Treat an externally written completion state as a hypothesis to test, not an inherited fact.** When a
   session finds a plan or iteration already closed by someone else, the question is not "may I proceed?" but
   "does the closure survive its own evidence?" Here the answer was no, and the close gate was the thing that
   asked.

5. **Reset the state you found false, and record how it arose.** The compass frontmatter was moved back from
   `completed` to `active` and the plan from `Done` to `InProgress` at its real progress. Register the
   *mechanism* (residual A-R3: "an external writer recorded completion that was not earned") so the close-out
   carries the cause, not only the correction — a corrected number with no recorded cause comes back.

6. **Ask what a green suite can and cannot prove here.** None of this was hidden by a test failure: the suite
   was green throughout, because a criterion whose subject does not exist has no test to fail. Coverage of a
   *specified* surface is not coverage of a *delivered* one.

## Why This Matters

The cost of an unearned `Done` is not the missing work — it is that everything downstream treats the surface as
present. Here the compass's own close gate was about to pass on AC 6, and the missing thing was the second half
of the operator's original request ("a queryable audio inventory in the DB"): the tables and their writer had
shipped, so the store could *record* audio that nothing could *read back*. A register that cannot be trusted
makes every later "done" expensive to believe, and the repair cost is paid twice — once to build the missing
piece, once to re-establish that the rest of the register is real.

## When to Apply

- Before entering an iteration-close or any phase-transition gate whose precondition is a set of completion
  states.
- When a plan row, compass row or report was written by a session other than the one that did the work.
- Whenever a stored claim is about to become a *premise* (a scope, a target shape, a branch decision) rather
  than a description of the past.
- When a criterion's evidence names a file, test or command — resolve it before citing it.
- When reconciling any register against the tree: the compass `## Plans` row, the workflow snapshot
  `plans[]` row, the plan's own `status` frontmatter and its checkboxes can each disagree, and the one that
  disagrees is the one nobody read.

## Examples

### Before — the status word is consumed as the fact

```
| 6 | derive-audio-inventory reports recorded/already/missing/unlinked ... | audio |
    the command's own test over both a populated and an empty root |
```

Read as: AC 6 is met. The next step is to close the iteration. Nothing in the flow asks whether
`derive-audio-inventory` exists, and the cited test is a path, not a check that has been run.

### After — the pointer is resolved, and the three registers are compared

```
$ grep -o 'add_parser("[a-z-]*"' src/bili_asr/cli.py   # 23 subcommands; grep -c inventory → 0
$ ls tests/test_audio_inventory.py                      # No such file
$ git log --all -S"derive-audio-inventory" --oneline    # prose only
```

Compass says `Done`; the plan frontmatter says `registered`; the plan body says 0/15 steps. Three registers,
one claim, and the claim is the only one that is wrong. AC 6 is reopened, the command is built (`678b376`),
and the close gate is re-run — this time on a criterion whose subject exists.

The same shape, second instance: a plan row's `Done` carried a note attributing completion to another
lifecycle's PRs. Splitting the claim into *"AC 4/5 hold, earned by PR #21 `2696711`"* and *"this plan's own
tasks were never executed"* is what made the remaining work visible — the single word `Done` had been hiding a
0/15.

## Evidence

- `.mstar/iterations/iter-2026-09-metadata-audio-layout/delivery-compass.md` — the AC 6 row as found (with its
  unresolvable evidence pointer) and as corrected; the `## Plans` row carrying `**Done**` at 0% with its
  attribution note; frontmatter `status: completed` → `active`.
- `.mstar/plans/20260926-audio-inventory.md` — `status: registered`, `execution_mode: sdd`, 0 of 15 task steps
  checked, while the compass and snapshot both carried it as `Done`.
- `git log --all -S"derive-audio-inventory"` vs `src/bili_asr/cli.py`'s 23 `add_parser` calls — the
  prose-versus-code divergence that decides "specified, not delivered".
- The repaired state: `feat/20260928-audio-inventory` `678b376` + `bda9465`, 8 tests, end-to-end
  `derive-audio-inventory: recorded=1 already=0 missing=0 unlinked=0` with `exit 0`.
- Residuals recording the *mechanism* rather than only the fix: `A-R3` (unearned completion), and on the
  sibling plan `R4` (an unattributed external commit and merge on the plan's own branch).

## See also

- `best-practices/premise-freshness-before-lock.md` — the same discipline one step earlier: a stored artifact
  is evidence of the past, not a premise for a scope.
- `best-practices/degradation-vs-observation-third-state.md` — "could not read" is not "read, and it is
  empty": the write-side twin of treating an absence as a fact.
- `testing-patterns/absence-assertion-negative-control.md` — a test that cannot reach the producer proves
  nothing, which is why a green suite did not detect a criterion whose subject was missing.
