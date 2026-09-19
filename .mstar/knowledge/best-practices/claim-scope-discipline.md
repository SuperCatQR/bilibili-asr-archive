---
module: bili-asr plan and doc authoring
date: 2026-09-19
last_updated: 2026-09-19
problem_type: best_practice
category: best-practices
severity: medium
plan_id: 20260919-sqlite-queue-bridge
applies_when:
  - writing a plan step, example or acceptance claim
  - editing a README, spec or knowledge sentence that describes behaviour
  - reviewing a fix delta, including the sentences it adds
  - stating a limit, guarantee or invariant on a published surface
tags:
  - claim-discipline
  - plan-authoring
  - documentation
  - review
  - invariants
---

# Published claims must be no wider than the code

## Context

The queue-bridge plan's review produced one behaviour Warning and a run of documentation-scale findings, and
the class behind them was the same each time: **a sentence that claimed more than the code does, or
something different from it.** Four instances: three are checkable against the shipped artefacts, the
fourth against the review record (its clause was rewritten, so the shipped text no longer shows it):

- **The plan's own example contradicted its own formula.** Task 1's duration case list read
  `1000 -> 1000` while the run line beside it pinned the clamp in `duration_s_from_ms`. Resolving it against the
  contract showed the example was the round-trip case, not a second clamp: the clamp fires only *below* one
  second. Both edges are now pinned in the same test
  (`bilibili-asr-archive/tests/test_manifest_derivation.py:93-102`), so the next reader can see which of the
  two was wrong.
- **The additive promise ranged wider than the mechanism.** The plan and the spec promised that a part the
  chain already archived cannot be re-queued; the code keys that check on the manifest's effective key, and a
  legacy bare-`bvid` row is keyed differently — so such a part *can* be re-queued. The claim was narrowed to
  page-qualified rows, the limit was stated on the published surfaces, and the behaviour question was
  registered (`iter-2026-09-queue-bridge · R2`) instead of improvised at the end of the plan.
- **A published limit named one direction.** The operator surface described which rows the command selects
  but not that the derivation *consults* only page-qualified keys; a reader could therefore conclude the
  bridge is a no-op over an existing manifest. Both directions are now stated side by side.
- **A fix round writes new claims.** The clause added to explain a defensive branch asserted a protection
  that branch cannot perform. A fix delta is a writing delta: the sentences it adds are claims about the
  code, not commentary beside it.

## Guidance

1. **Give every claim its range.** A claim is a testable statement about an artefact; state the set it ranges
   over — "page-qualified rows", "on a host whose zone is not UTC", "for stores the shipped writers
   produce" — and check that range against the *mechanism*, not the intent. The range is usually narrower
   than the surface the sentence sits on.
2. **An inline example is a claim with the force of prose.** When an example contradicts the formula beside
   it, resolve it against the spec or the code — never silently follow the example — pin both edges in a
   test, and correct the text in place with the reason, so nobody re-derives it.
3. **A disclosure is part of the claim, not an apology.** Name the mechanism and the bound together ("the
   row is never rewritten; the cost is repeated work"), and put the limit on the surface the operator reads,
   not only in the code comment.
4. **Narrow the claim or fix the code — deliberately.** When the intent is wider than the mechanism, the two
   honest moves are: narrow the claim *and* register the behaviour gap with a measurable trigger, or change
   the behaviour (which reopens the contract). Doing neither leaves the wider claim standing; doing the
   second at the end of a plan is usually how the wider claim got written.
5. **Review the sentences a fix adds.** The clause written to satisfy one finding is itself a claim about the
   branch, and it is the clause no one has read against the code yet.
6. **Unreachable defence is a claim with a direction.** Say which inputs it covers ("unreachable for stores
   the shipped writers produce"), and pin the branch with fabricated input in a test, so a reader can tell a
   live risk from a defensive branch instead of guessing.
7. **Tests do not check prose.** The check that works is reading the sentence against the code and asking
   *what would have to be true for this sentence to be false?* If the answer is "nothing reachable", the
   sentence is either a disclosure that needs its bound written down, or a claim that is simply false.

## Why This Matters

A claim wider than the code survives every test, because tests check code. It then becomes the premise the
next plan, task brief and implementation are built on — and the cost is paid later, by someone reading the
guarantee as fact. The class was measured rather than hypothesised: it appeared in three different
surfaces of one plan — including one instance introduced while another was being fixed — and the narrowing
decision (claim narrowed, behaviour registered, exposure measured at zero) was the one that
kept the plan's queue-authority principle intact. Claim discipline is also what keeps a review honest: a
reviewer who cannot tell a disclosure from a guarantee cannot size the risk.

## When to Apply

- Writing or editing a plan step, task example, acceptance criterion or Done criterion.
- Editing a README paragraph, a spec section, or a knowledge sentence that describes behaviour.
- Reviewing any fix delta — read the added sentences as claims, not as explanation.
- Whenever a sentence uses *never*, *always*, *cannot*, *only*, *no path*: those are the words whose range
  must be checked against the mechanism.
- Not an argument for hedging: the goal is a claim whose range is exactly the code's range, stated once.

## Examples

### Before — a claim wider than the mechanism

```text
For every queue row the command reads the manifest's effective row; a part the
chain already archived is therefore never re-queued.
```

```python
# plan Task 1 case list
# test_duration_s_is_floor_seconds_clamped_to_one   3600_500 -> 3600; 999 -> 1; 1000 -> 1000
```

### After — the range named, both edges pinned, the gap registered

```text
For every queue row the command reads the manifest's effective row for that
page-qualified work_id; a row the chain already holds under the same key is
therefore left untouched. A legacy bare-`bvid` row is keyed differently and is
not consulted — the part is appended as needs_audio and a bounded run may
re-download it; nothing is overwritten (the artifact stems differ), and the
behaviour question is registered as iter-2026-09-queue-bridge · R2.
```

```python
def test_duration_s_is_floor_seconds_clamped_to_one():
    assert duration_s_from_ms(3_600_500) == 3600
    assert duration_s_from_ms(999) == 1
    # §3.2 clamps only what is *below* one second, and the floor is deliberate:
    # exactly one second is one second, a million milliseconds is a thousand.
    assert duration_s_from_ms(1000) == 1
    assert duration_s_from_ms(1_000_000) == 1000
```

## Evidence

- Iteration: `iter-2026-09-queue-bridge`; plan `20260919-sqlite-queue-bridge`
  (`## Review Gate Summary`, `## QA Gate Summary`); review records:
  `{SDD_DIR}/20260919-sqlite-queue-bridge/review/qc-consolidated.md` (names the "claim wider than the
  code" class) and the seat reports beside it.
- Contract text with the narrowed ranges:
  `.mstar/iterations/iter-2026-09-queue-bridge/specs/sqlite-queue-bridge-contract.md` §3.2 (the conversion
  and the absent-duration decision), §3.4 (additive policy), §3.5 (the bare-`bvid` limit and its disclosed
  note).
- Pinned edges: `bilibili-asr-archive/tests/test_manifest_derivation.py:93-102`.
- Published surfaces the limits had to reach: `bilibili-asr-archive/README.md` (`#### Derived audio queue`,
  "Limits, stated") and `bilibili-asr-archive/docs/metadata-storage.md` (the boundary section).
