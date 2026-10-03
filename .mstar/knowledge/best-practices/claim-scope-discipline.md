---
module: bili-asr plan and doc authoring
date: 2026-09-19
last_updated: 2026-09-19
problem_type: best_practice
category: best-practices
severity: medium
plan_id: 20260919-artifact-root
applies_when:
  - writing a plan step, example or acceptance claim
  - editing a README, spec or knowledge sentence that describes behaviour
  - reviewing a fix delta, including the sentences it adds
  - stating a limit, guarantee or invariant on a published surface
  - writing an operator-facing message for a refusal or a skip
  - patching a sentence someone else (or an earlier round) wrote
tags:
  - claim-discipline
  - plan-authoring
  - documentation
  - review
  - invariants
  - operator-messages
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

The class was measured a second time, in the artifact-root iteration, and it scaled with the size of the
surface rather than shrinking: **four** instances landed in the shipped or contract text — the fourth is a
self-contradiction inside the same operator page, listed beside the first — and **two** were written by the
coordinator rather than by an implementer.

| Instance | The claim, and the mechanism it outran |
|---|---|
| **Operator migration advice, false in both halves** | the artifact-root page told an operator that new downloads land in the archive root's audio directory and that the cap mixes both roots' usage. Neither is true: with a root configured, every write resolves on `write_base`, and the cap measures the configured root's audio directory only. The same page said the opposite nineteen lines later, and the command's own `--help` said the opposite too (`{SDD_DIR}/20260919-artifact-root/task-4-review.md`, I1; corrected at `bilibili-asr-archive/docs/artifact-root.md:122`, `:141`) |
| **A parenthetical that named the wrong error** | the contract said a symlinked root is refused with `ELOOP`; the measured errno is `ENOTDIR`, because `O_DIRECTORY` is set as well as `O_NOFOLLOW`. The claim's *direction* was right and its mechanism wrong — the kind of sentence a reader quotes as fact (`.mstar/iterations/iter-2026-09-artifact-root/specs/artifact-root-contract.md:295`) |
| **A docstring claiming a refusal the code did not implement** | the module documented a symlinked configured root as refused while validation used `is_dir()`, which follows links: writes raised a raw `OSError`, reads silently fell back to the archive root, and the named refusal never fired. The root cause was a **spec contradiction** between two sections, not a coding slip (`{SDD_DIR}/20260919-artifact-root/task-1-review.md`, I2; the refusal now exists at `bilibili-asr-archive/src/bili_asr/artifact_root.py:245` and is pinned by `bilibili-asr-archive/tests/test_artifact_root.py:124`) |
| **A page contradicting itself one paragraph apart** | the same page stated the correct rule and then the false one, which is why a reviewer reading it in order could stop at the first paragraph and pass it (the instance above; both halves are now one sentence in the corrected text) |
| **An inferred consequence registered as fact** | the coordinator recorded that a 0-byte audio stub would make a row fail closed. Two seats disproved it by probe: the downloader's existing-audio path is validity-aware (`bilibili-asr-archive/src/bili_asr/audio.py:109-131`), so the stub is skipped and the valid legacy copy is returned; the real cost is one extra fast-path call. The correction is recorded beside the inference rather than absorbed (`.mstar/plans/20260919-artifact-root.md`, Review Gate Summary) |
| **An amendment applied twice against a stale assumption** | a correction was written into a sentence whose current text had already moved, because the patcher worked from its memory of the file instead of reading it; the second application had to be reconciled against the shipped surface (`{SDD_DIR}/20260919-artifact-root/progress.md`, Task 4) |

**The meta-observation, which is the reason this doc exists.** In both measured rounds, **review caught every
instance and the author caught none** — including the instances the coordinator wrote. The class is not
detected by care in the act of writing; it is detected by someone else reading the sentence against the
mechanism. That makes two things the author's job: keep each claim falsifiable enough that a reviewer can
check it quickly, and treat "I already know what this file says" as the failure mode rather than as
efficiency.

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
8. **A message is a claim about the input that produces it.** Before a refusal line, a skip reason or an
   error tail is printed — or documented — name the input and check that the sentence is true of *that*
   input. When nothing in the existing vocabulary is true, **add a vocabulary item rather than reuse a false
   one**: the artifact-root refusal set has four members because the first three are all false of "a
   directory that exists and the process cannot open it", and each of the four is pinned per input
   ([artifact-root-split.md](../architecture-patterns/artifact-root-split.md), "the four refusal lines"). Two corollaries: an advice clause that is true in
   one mode and false in another belongs only on the surface where the mode is known (a `--help` string, not
   a shared runtime line), and where no honest clause exists, absent advice beats false advice — a hint that
   is false for the input that produces the message is worse than silence.
9. **Read the file before patching the sentence; memory of it is a stale source.** The author-side check is a
   pair of questions, asked before the edit and not after: *what would falsify this sentence?* and *am I
   reading the current file, or my memory of it?* The second question has its own failure mode — an amendment
   written against a remembered version rather than the shipped text — and the same discipline covers
   inferences: "this input will fail closed" is a claim, so probe it or label it as an inference with the
   probe that would settle it.
10. **Write so a reviewer can falsify the sentence in one pass, and expect the detection to come from
    review.** Name the input, the mechanism and the bound inside the sentence itself; a claim whose falsifier
    is visible gets caught, and a claim that reads as background does not. The measured record is blunt:
    review found every instance of this class in both rounds, the author found none — including the
    coordinator's own two.

## Why This Matters

A claim wider than the code survives every test, because tests check code. It then becomes the premise the
next plan, task brief and implementation are built on — and the cost is paid later, by someone reading the
guarantee as fact. The class was measured rather than hypothesised: it appeared in three different
surfaces of one plan — including one instance introduced while another was being fixed — and the narrowing
decision (claim narrowed, behaviour registered, exposure measured at zero) was the one that
kept the plan's queue-authority principle intact. Claim discipline is also what keeps a review honest: a
reviewer who cannot tell a disclosure from a guarantee cannot size the risk.

The second measurement put the cost somewhere worse than a plan's internal prose: **operator-facing
migration advice**. A false sentence there does not merely mislead a reviewer — it sends an operator to move
files that were fine, or explains a budget skip as something the code does not do, and the correction
arrives only after the move. It also multiplies: the same false claim was found on the operator page and
repeated by the surrounding surfaces, so the fix had to make the page, the README and the `--help` text agree
in one direction. That is the shape of the class worth remembering — a claim wider than the code does not
stay in one file, and the surfaces that repeat it are the ones an operator trusts most.

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

### Before — an operator sentence that is false about both halves

```text
(artifact-root operator page, migration section)
Note: the archive root's audio/ is where new downloads go, so do not leave it
behind when you move — otherwise --max-audio-gb will mix both sides' usage
together.
```

The em-dash clause corrected the first half of its own sentence and contradicted the page nineteen lines
below it: with a root configured, writes resolve on the configured root's audio directory
(`bilibili-asr-archive/src/bili_asr/cli.py:3490-3503`, `audio.py:133-172`), and the cap measures that root
alone (`coordinator.py:625-640`, `cli.py:2392-2399`'s per-row budget check). The guidance could drive an unnecessary
move and mis-explain a budget skip.

### After — one direction, the mechanism named, the advice demoted

```text
After a root is configured, new bytes go only to the configured root's audio/;
legacy audio at the archive root stops growing but stays readable (reads probe
both roots in order), and --max-audio-gb counts only the configured root's audio/.
Moving the old files is optional tidying, not a precondition for reads or for the cap.
```

### Before — a refusal vocabulary that had no true member for one input

```text
(candidate lines, none of which is true of an existing directory the process cannot open)
artifact root does not exist (<path>)
artifact root is not a directory (<path>)
```

### After — a fourth item, each pinned against its own input

```text
artifact root does not exist (<path>)          # nothing at that path
artifact root is not a directory (<path>)      # a file, socket or device
artifact root is a symlink (<path>)            # a symlink at the final component
artifact root cannot be opened (<path>)        # exists, and the open fails
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
- Second measurement, iteration `iter-2026-09-artifact-root` (plan `20260919-artifact-root`): the four
  instances in the Context table are grounded in
  `{SDD_DIR}/20260919-artifact-root/task-4-review.md` (I1, the operator migration sentence),
  `{SDD_DIR}/20260919-artifact-root/task-1-review.md` (I2, the docstring/refusal contradiction),
  `.mstar/iterations/iter-2026-09-artifact-root/specs/artifact-root-contract.md:295` (the errno
  parenthetical) and `{SDD_DIR}/20260919-artifact-root/progress.md` (the coordinator's two). The corrected
  surfaces: `bilibili-asr-archive/docs/artifact-root.md:57-86`, `:122`, `:136-151`,
  `bilibili-asr-archive/README.md:391-433`, `bilibili-asr-archive/src/bili_asr/artifact_root.py:224-270`.
- The constructive counterpart — the four refusal lines and the rule that each is true of its input —
  is stated with its code anchors in
  [artifact-root-split.md](../architecture-patterns/artifact-root-split.md) ("The operator surface, and the
  four refusal lines").


## Instances added 2026-09-20 (iter-2026-09-transcript-projections)

The class repeated in surfaces a review round had already touched, which is why the rule keeps
earning its place:

- **A register/summary sentence wider than the register.** The QC consolidation closed with
  "everything else is registered below … not waived"; a seat then showed that four Suggestions
  existed only as ruling text with no register row — the sentence was **false**, and the fix was to
  create the missing row (`R9`) rather than to soften the sentence. *A completeness claim about a
  register must be checked against the register.*
- **A row that asserted a claim its own source later withdrew.** Residual `R4` recorded a "docstring
  overclaims" half; on re-reading, the docstring scoped its claim correctly and the raising seat
  withdrew that half. The row's title and scope were narrowed rather than left standing. *A register
  is also a written surface: it inherits the discipline.*
- **A help sentence that named two write sites while the code had three** (the archive-writer lock).
  Because the sentence was **new text in the diff**, "pre-existing wording" was not available as a
  defence — exactly the trap this document exists for.
- **An acceptance criterion phrased over a field of the wrong type** ("`summary.valid_work_items`
  includes it" — the field is an integer count). Unevaluable criteria read as met; the gate had to
  restate it as "the count covers the row".
- **A published claim's identity clause outliving its context**: the contract's "no `audio_path` — no
  audio exists for a caption" was true of the *decision* and false of the *row* once replacement
  semantics were in play (see `architecture-patterns/row-merge-on-terminal-transition.md`).

The author-side check that would have caught all five in one pass: **state the range of the claim,
then test the sentence against the widest input it can receive** — a register row against the
register, a help line against the write sites, a criterion against the field's type.

## Instances added 2026-10-03 (iter-2026-10-ledger-integrity)

- **A fix's honest contract has two halves, and both must be written — by the seat that knows the
  mechanism.** The repair that stopped the journal fold from deleting stranded rows does *not* make
  those rows readable: while the fragment stays, they are retained and invisible to every reader. The
  published sentence names both ("no record is discarded — … remain unreadable to every reader until
  …"), and the repair a stranded tail needs is registered as its own surface. The half left out is
  the half a later reader mistakes for done.
- **A repair can falsify a sentence written one section above it.** The motivation paragraph bounded
  the journal residue as "≤ 2× snapshot" from the append path alone; that bound holds only while a
  fold can complete. Once a strand refuses the discard, the residue is unbounded and grows with the
  journal. The correction was **appended as an amendment beside the false sentence** (stating the
  measured counter-case and that the unqualified property must not be carried away) instead of being
  quietly rewritten — a bounded-residue claim that later readers treat as a guarantee costs more than
  the sentence.
