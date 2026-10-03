---
module: bili-asr verification
date: 2026-09-19
last_updated: 2026-09-27
problem_type: testing_pattern
category: testing-patterns
severity: medium
plan_id: 20260919-artifact-root; 20260927-aac-decode-contract
applies_when:
  - asserting that something never happens in a run
  - asserting that two readers, roots or modes agree about one value
  - asserting on a filtered subset of a record list
  - citing one case as the proof of a file-level invariant
  - pinning a new refusal, message or exit code
  - a test skips when a prerequisite is missing and the run still reports success
  - a test double accepts ``*args, **kwargs`` and therefore cannot see its arguments change
tags:
  - negative-control
  - absence-assertion
  - fixtures
  - evidence
  - chain-test
  - mutation-control
---

# An absence assertion is evidence only if the fixture can reach the producer

## Context

The chain test for the derived queue asserts spec §4's invariant directly: after a
`run --scope pending --offline` over a derived row, no attempt record may carry `missing_subtitle_raw`
(`bilibili-asr-archive/tests/test_derived_queue_chain.py:409`). The fixture it runs on cannot
produce that record. Every row in the run is `needs_audio`; in `--offline` mode the routing takes a
`needs_audio` row whose audio is already on disk to `_stage_asr_archive` (`coordinator.py:648`,
`:663`), while the only producer of the code is `_stage_archive_from_subtitle`
(`coordinator.py:435-449`), reachable from `:646` (a subtitle raw document exists) or `:661` (a
`subtitle_done` row). Neither branch is reachable from the fixture, so the filtered absence is true
for reasons the case does not exercise — the real work in that case is the whole-ledger equality at
`:402-405` and the `archived` readback at `:399`.

The file-level invariant is still proven, by a **negative control** in the same file: a hand-written
`subtitle_done` row for the part whose caption the store holds, with no
`{archive_root}/subtitles/raw/{stem}.json` on disk, makes the chain record exactly `missing_subtitle_raw`
and exit `1` while the derived row in the same run reaches `archived`
(`bilibili-asr-archive/tests/test_derived_queue_chain.py:412-476`). The control is what makes the filter
in the case above live rather than vacuous — and it is a *different case*, which is exactly why the two
claims have to be worded separately.

## Guidance

**Rule: for every `assert <nothing of kind K>`, name the producer of K (`file:line`) and show that the
fixture reaches it — or say that the case does not, and let a control case carry the proof.** The general
form, which covers the two shapes in the section below: **an assertion is evidence only if its fixture can
reach the falsifier** — for an absence, the producer; for an agreement between two readers or modes, the
shape on which the two would differ.

1. **Name the falsifier.** The producer of the negated thing is a specific code path, not a vibe. Write it
   down (file:line) and check the fixture's route against it: which statuses does the run visit, which
   branch does each take, and is the producer among them?
2. **Add the control that fires it.** Same fixture family, one input changed so the producer runs, asserting
   the record that must *appear* — and, where one run can carry both, the contrast in the same run (here:
   the chain-held row skips, the derived row archives). A control that only proves the code exists
   somewhere is weaker than one proving it inside the same run.
3. **Say exactly what the pair proves.** The control proves the code is *producible* and the filter
   *live*; it does not prove that the earlier assertion is falsified by the control's fixture, because that
   case cannot reach the producer at all. Calling such an assertion *falsifiable* is a claim wider than the
   evidence — the same defect class as a comment that describes behaviour its branch does not have (see
   [claim-scope-discipline.md](../best-practices/claim-scope-discipline.md)).
4. **Prefer the strongest available form.** Whole-collection equality
   (`[(r["stage"], r["outcome"]) for r in attempts] == [...]`) fails on any unexpected record, while a
   filtered absence fails only on the one predicate it names. When the ledger is small and the run is
   bounded, assert the whole list and let the absence fall out of it.
5. **A reachable-falsifier check is not a coverage claim.** Case-level reachability and file-level
   non-vacuity are different properties; label which case earns which claim in the test file's module
   docstring, not only in the assertion's comment.

## Beyond absence: agreement assertions and untested re-bases

The same rule covers two shapes that do not look like an absence assertion at all, and both were measured in
the artifact-root iteration.

**An agreement assertion is evidence only if the fixture contains a shape where the two sides could
differ.** The readers' shared case asserts that one fixture reports the same inventory with and without a
configured root (`bilibili-asr-archive/tests/test_artifact_root_readers.py:106`) — a strong claim, and it
passed while a reader was still grading a whole row at one base. Its fixture held no row with an incomplete
declared bundle, so the identity arm never reached the branch that disagreed; the defect was invisible to the
case that existed to catch it, and the proof came from a purpose-built shape — a legacy harvested-caption row
(srt plus `{root}/subtitles/raw/` at one base, only `srt_path` declared), which reported a true defect hidden and a
false one invented (`{SDD_DIR}/20260919-artifact-root/task-3-review.md`, I1; the pin that now reaches the arm
is `bilibili-asr-archive/tests/test_artifact_root_readers.py:209`). **Count the fixture's shapes, not the assertions**: name, for
each agreement claim, the input on which the two sides would disagree, and put that input in the fixture.

**A pin's teeth are a claim too — earn them with a mutation.** Two refusal pins and one lexical-path pin in
this iteration were demonstrated rather than asserted: the lexical case was run once with `abspath` swapped
for `realpath` (the assertion failed, with the failure text pasted), a reword mutation proved the
exact-equality refusal pins were not substring assertions, and both mutations were reverted before the commit
so the shipped file stayed byte-identical (`{SDD_DIR}/20260919-artifact-root/task-1-report.md:176-193`).
Where a test only tightens an existing one and no RED is available, the mutation control *is* the evidence.

**The degenerate case is a re-based behaviour with no fixture at all.** Making the audio cap and the peak
measure the configured root changed which directory four commands read, and nothing in the suite counted a
walk or placed audio at the configured root: *"the re-base is asserted nowhere and every fixture is a healthy
local filesystem"* (`{SDD_DIR}/20260919-artifact-root/review/qc3.md`, Suggestion S1, registered as
`iter-2026-09-artifact-root · R2`). An untested re-base is not a weaker version of a vacuous pin; it is the
same failure with the evidence removed, and it is worth naming as a gap in the round that makes the change —
the fixtures for it are the follow-up plan's first item, and the residual says so.

## Why This Matters

An absence assertion that cannot fail reads as coverage and consumes the reviewer's attention, while the
regression it nominally guards is caught — if at all — by a neighbouring assertion the reader was not told
about. The cost is not a missed bug (the file as a whole still proves the invariant); it is a mis-labelled
proof: the credit lands on a case whose fixture cannot see the failure, and the next change to the file
(a fixture reshuffle, a status added to the run) can quietly remove the real guard while the tautology stays
green. The pair of cases is also what lets a QA seat call the control "live" rather than assumed.

## When to Apply

- Writing any assertion of the form "no record of kind K", "nothing was printed", "no file was created".
- Reviewing a test file whose Done criterion is an invariant read back from an append-only ledger.
- Any test whose fixture is derived from a fixture builder rather than hand-written: builders make it easy
  to produce a fixture whose routes never include the producer.
- Not a substitute for the opposite direction: a control that fires the producer does not prove the happy
  path's records are the expected ones — that is the whole-ledger assertion's job, and both belong in the
  file.

## Examples

### Before — the assertion has no reachable falsifier

```python
    attempts = _attempts(tmp_root)
    assert [(record["stage"], record["outcome"]) for record in attempts] == [
        ("asr", "ok"),
        ("archive", "ok"),
    ]
    # True on this fixture for reasons the case does not exercise: a needs_audio
    # row with audio on disk routes to the ASR/archive path, never to the
    # subtitle-archive path that produces the code.
    assert [r for r in attempts if r["error_code"] == MISSING_SUBTITLE_RAW] == []
```

### After — keep the assertion, add the control, and name the relation between them

```python
    # Spec §4's invariant, read from the ledger the chain itself writes.  Case 3
    # below is the control that makes this filter live: no reachable input makes
    # this assertion fail on its own.
    assert [r for r in attempts if r["error_code"] == MISSING_SUBTITLE_RAW] == []
```

```python
def test_a_chain_held_subtitle_done_row_without_its_raw_document_skips(
    tmp_root, monkeypatch, capsys, fake_gateway_seam
):
    """The negative control: the missing_subtitle_raw code is producible (case 3)."""
    ...
    store.upsert(_row(..., status="subtitle_done", title="stored caption, no raw document"))
    assert _derive(tmp_root) == 0
    assert not os.path.exists(raw_path)          # the trap's precondition

    assert main(["run", "--scope", "pending", "--offline", ...]) == 1
    assert [
        (r["work_id"], r["stage"], r["outcome"], r["error_code"])
        for r in attempts if r["error_code"] == MISSING_SUBTITLE_RAW
    ] == [(CAPTIONED_WORK_ID, "archive", "skipped", MISSING_SUBTITLE_RAW)]
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[CAPTIONED_WORK_ID]["status"] == "subtitle_done"   # held, not advanced
    assert loaded[QUEUED_WORK_ID]["status"] == "archived"           # derived, advanced
```

## Evidence

- Iteration: `iter-2026-09-queue-bridge`; plan `20260919-sqlite-queue-bridge` (Task 3 Step 2 asks for the
  control with the sentence "a check that cannot fail is not evidence").
- Cases: `bilibili-asr-archive/tests/test_derived_queue_chain.py:360-409` (the invariant) and
  `:412-476` (the control).
- Producer and routing: `bilibili-asr-archive/src/bili_asr/coordinator.py:396-400` (filesystem segment
  source), `:435-449` (`missing_subtitle_raw`), `:640-663` (offline routing).
- QA gate: the control was verified as live (`{SDD_DIR}/20260919-sqlite-queue-bridge/review/qa.md`,
  "negative control for the chain test").
- Second measurement, iteration `iter-2026-09-artifact-root` (plan `20260919-artifact-root`): the agreement
  case and the fixture shape that reaches its falsifier — `bilibili-asr-archive/tests/test_artifact_root_readers.py:106`
  (the shared case) against `:209` and `:279-330` (the shapes that discriminate); the fixture gap named by the
  L2 seat in `{SDD_DIR}/20260919-artifact-root/task-3-review.md` (Q7) and the defect in the same report (I1).
  The mutation controls: `{SDD_DIR}/20260919-artifact-root/task-1-report.md:176-193` (the reverted `realpath`
  mutation) and its M1 reword control. The untested re-base: `{SDD_DIR}/20260919-artifact-root/review/qc3.md`
  (S1) and residual `iter-2026-09-artifact-root · R2` in `.mstar/projects/_default/residuals.json`.


## Instances added 2026-09-20 (iter-2026-09-transcript-projections)

The projection's acceptance evidence produced three shapes worth keeping, plus one correction:

- **The inverted check needs a producer for the thing it forbids.** "No `asr_`/`confidence` key in a
  published caption bundle" is only evidence if some bundle *can* carry them: the fixture publishes
  one ASR-shaped bundle through the same writer and asserts the inverted check **matches** it. The
  seat also showed the check's **sidecar half was unfalsifiable** (`json.dumps(indent=2)` can never
  start a line with those keys) — an assertion that cannot fail is not a weaker control, it is a
  false claim about coverage.
- **A reader's zero must be read after the same reader reported the defect.** "`verify` reports zero
  defects on the projected row" was paired with the same reader reporting `missing_transcript` for
  the same part **before** the run — so the zero is a transition, not a constant.
- **A control that mutates no shipped line adds a constraint, it does not test one.** The `gone`-part
  case is killed by exactly one control, and that control (a status filter the read does not have)
  exists only inside the test. The seat's recommended hardening: assert the read's own return for
  that part, so the case rests on the shipped path too.
- **Correction to the general form**: a fixture can be *faithful* and still not exercise the shipped
  call. The reader fixture builds bundles by calling `write_archive(..., source="subtitle")` without
  `raw=`; the shipped command does the same, so the reconstruction is faithful — but a fixture that
  built the *other* call shape (with `raw=`) would have looked equally plausible and proved nothing
  about the shipped path. Name the shipped call the fixture reproduces.

## Instances added 2026-09-27 (PR #20, R5's own test suite)

Four mechanisms, one outcome: a suite that reports success while the surface it names goes
unexercised. All four were found by mutation — each was reproduced by changing product code and
watching the suite stay green — not by reading the tests.

- **A skip is a third state, and a summary line hides which surface went dark.** With `ffmpeg` off
  `PATH`, the ASR suite reported `43 passed, 3 skipped` and **exit 0**; the three skips were precisely
  the tests exercising the decode path the work existed to fix. The repository had already answered
  this question, in the opposite direction, in an adjacent file: `bilibili-asr-archive/tests/installed_cli.py`
  says *"fail the test (never pytest.skip / xfail) with a named prerequisite. Automated verification
  must not go green because a console script was absent."* When a repo has a written policy for a
  class of dependency, consistency with that policy beats a locally reasonable preference — skipping
  is right for an optional library, wrong for a declared requirement, and the difference must be
  decided once rather than per test.
- **A test double that accepts `*args, **kwargs` cannot see its arguments change.** The surviving
  check of the primary reader replaced the soundfile read call with `lambda *args, **kwargs: (known, 16000)` — which
  discards every read option, so a `frames=1000` truncation and a `dtype="int16"` regression both left
  the suite green at **46 passed**. A stubbed reader proves the *shape* of what callers do with a
  result; it can never prove the read itself, so one test per reader has to touch a real file.
- **Set membership is the wrong assertion for an ordered argv.** `assert ("-rf64", "auto") in pairs`
  passed while a later `-rf64 never` re-selected the RIFF muxer — the two are last-wins, so the
  override silently restored the 4 GiB truncation the test existed to prevent. When asserting a flag
  in a command line, assert its **count**, its **position relative to the thing it qualifies**, and
  the **absence of a later override**.
- **A new exception class with no test is a claim, not a contract.** Replacing `AudioDecodeError`'s
  `raise` with a bare `RuntimeError`, and deleting the entire non-zero-exit guard around it, both left
  **46 passed** — while the class docstring asserted that its name is what an operator sees in the run
  ledger. Introducing a type for callers or operators to branch on obliges one `pytest.raises` assertion for it.

## Instances added 2026-10-03 (iter-2026-10-ledger-integrity, journal fold)

Two shapes where the assertion named the wrong property:

- **Assert recoverability, not an artifact's existence.** A new test for "the fold must not discard rows a
  torn fragment stranded" first asserted that the journal file still exists — and it was **green pre-fix**:
  the pre-fix bug *unlinks* the journal, and later appends recreate the file, so existence passes while the
  rows are already gone. The corrected form asserts recoverability (a fresh `load()` sees the row, or its
  bytes remain in the journal) and was red pre-fix. *When the bug under test deletes-and-recreates, any
  existence check can be satisfied by the recreation.*
- **A fold-bound assertion fitted to its loop length is not a guard.** A test asserting "journal bytes stay
  under `max(2 × snapshot, 512)`" passed at its fixture's loop count and failed at a larger n although the
  code was correct — the assertion had encoded the fixture, not the property. Where a bound is asserted, name
  the term that should be binding and construct the fixture so that it is.

**What generalised.** The doc's original rule covers an absence assertion with no reachable producer.
These four extend it to *presence* assertions whose fixture cannot see the value change — the same
failure mode wearing the other sign. The diagnostic is identical and cheap: **name the mutation that
would have to fail, then apply it.** If no single-line change to product code turns the test red, the
test is documentation rather than verification.
