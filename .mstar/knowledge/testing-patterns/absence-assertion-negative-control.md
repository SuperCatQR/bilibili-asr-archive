---
module: bili-asr verification
date: 2026-09-19
last_updated: 2026-09-19
problem_type: testing_pattern
category: testing-patterns
severity: medium
plan_id: 20260919-sqlite-queue-bridge
applies_when:
  - asserting that something never happens in a run
  - asserting on a filtered subset of a record list
  - citing one case as the proof of a file-level invariant
tags:
  - negative-control
  - absence-assertion
  - fixtures
  - evidence
  - chain-test
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
fixture reaches it — or say that the case does not, and let a control case carry the proof.**

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
