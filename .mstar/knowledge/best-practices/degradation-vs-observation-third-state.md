---
module: bili-asr metadata ingest (gateway → ingestor boundary)
date: "2026-09-27"
problem_type: best_practice
category: best-practices
severity: medium
plan_id: 20260926-video-metadata-enrichment
applies_when:
  - a fetch can fail and its caller writes what it fetched
  - an empty result and a failed fetch are both legal return values
  - a write path replaces a stored set rather than appending to it
  - designing a degradation protocol for an upstream call
tags:
  - degradation-protocol
  - third-state
  - none-vs-empty
  - silent-erasure
  - upsert-semantics
  - fetch-failure
---

# "Could not read" is not "read, and it is empty": the third state a degradation protocol must represent

## Context

The metadata ingestor fetches a video's tags per `bvid` and stores the result with a
replace-set write (`upsert_video_tags` deletes the video's rows and inserts what it was
given). The gateway's degradation rule — "catch the risk-control and transport failures,
return an empty tuple, do not fail the run" — made `()` the answer to two different
questions: "this video carries no tags" and "this call degraded". Because the write
replaces the set unconditionally, one degraded fetch erased the tags a previous run
stored: run 1 stores `[943, 11128717]`, run 2 degrades, and the table reads `[]`.
`DELETE` followed by zero inserts leaves no trace the way a wrong value does, so the
store could not tell "upstream no longer lists these tags" from "we failed to ask". No
test in the plan could see the loss, because it exists only across two runs with a
degradation in the second, and the only degradation test ran on a fresh database.

## Guidance

**The return type carries the distinction; the write protocol must never have to guess.**
The fix is `get_video_tags -> tuple[VideoTag, ...] | None`, where `None` means "could not
read this time" (risk control `-352` / `412`, transport failure) and `()` means "read it,
and there are none". The ingestor maps `None` to **omitting the `bvid` key** from the
payload it hands the repository — a write path that iterates `(tag_sets or {}).items()`
already treats an absent key as non-destructive, so nothing is written for that video and
its stored rows survive. A genuine empty observation (key present, empty iterable) still
clears the set, which is exactly what "a second run replaces the set rather than
appending" pins.

Three rules generalise:

1. **Represent the third state at the source, while the information still exists.**
   Once a failed fetch is flattened to an empty value, no layer below can recover the
   distinction; the choice belongs at the gateway's return, not in a conditional delete
   inside the write method. (The rejected alternative — "never delete on empty" inside
   `upsert_video_tags` — inverts the pinned genuine-clear test and destroys the replace
   semantics; the distinction can only be made where the information still exists.)
2. **A degradation test that runs on a fresh database cannot observe erasure.** The loss
   needs two runs — populate, then degrade — so the pin is a two-run test on a seeded
   store: run 1 stores a non-empty set, run 2 degrades, the stored set is byte-identical.
   The genuine clear keeps its own two-run pin (run 2 observes an empty set and the rows
   disappear), so both directions are guarded and the pair discriminates exactly the
   intended behaviour: flattening the `None` branch back to `()` fails both degradation
   pins while the genuine-clear pin still passes.
3. **This is the same defect class as the "last successful collection" stamp.** A write
   path that cannot tell "I observed nothing" from "I did not observe" will eventually
   record the fiction that nothing was true at time T — whether it blank-stamps a row
   whose observation carried no values, or clears a set its caller never read. The
   mechanism differs (an advance condition on one column vs a return protocol plus an
   absent-key rule); the fiction is the same.

**Why the return protocol and not a sentinel value or an error_code column:** the
write path already keys its behaviour on key presence (`(tag_sets or {}).items()`), so
the absent-key rule is free; a sentinel would need every consumer to agree on its
meaning; a new column widens a pinned schema for a distinction the caller no longer
needs once the key is omitted.

## Why This Matters

The tags are a side table, not the artifact, and the next successful collection
re-observes the truth — which is why the review graded this Important rather than
Critical, and why "bounded, not benign" is the honest label. But the shape recurs
everywhere a replace-set write meets a degradable fetch: stored author names, cover
URLs, any per-entity side table refreshed from an unreliable source. The failure is
silent by construction — no exception, no log line, no trace in the store — and it
compounds: each degraded run erases what the previous run established, so the archive
drifts toward emptiness exactly on the videos most likely to be re-fetched (the ones
whose tags changed, the ones an operator re-runs after a risk-control interruption).

## When to Apply

- Designing any fetch-then-store path where the fetch can degrade and the store replaces
  a set or refreshes a row: give the return a `None` (or equivalent) arm for "could not
  read", and make the write path treat key-absence as non-destructive.
- Reviewing a degradation rule that maps every failure to an empty value: ask what a
  replace-set write will do with it on the second run.
- Writing a degradation test: seed the store in run 1; degrade in run 2; assert the
  stored rows survive. A fresh-DB degradation test proves the run did not fail, nothing
  more.
- Comparing two stored rows over time: an empty set after a silent-erasure bug is
  indistinguishable from a genuine empty observation — which is why the fix belongs at
  the boundary, where the distinction still exists.

## Examples

```python
# Gateway: the third state is representable.
def get_video_tags(self, bvid: str) -> tuple[VideoTag, ...] | None:
    """None = could not read this time (risk control, transport); () = read, none."""
    try:
        payload = self._request(...)
    except (RiskControlError, TransportError):
        return None
    return tuple(VideoTag(...) for item in payload)

# Ingestor: absent key = do not touch this video's rows.
tag_sets: dict[str, tuple[VideoTag, ...]] = {}
for bvid in page_videos:
    tags = gateway.get_video_tags(bvid)
    if tags is not None:          # None -> omit the key -> non-destructive
        tag_sets[bvid] = tags
...
record_page(..., tag_sets=tag_sets)
```

The load-bearing pins: `test_a_degraded_second_run_leaves_the_stored_tag_set_untouched`
(run 1 stores, run 2 degrades, rows survive) and
`test_observed_empty_tag_set_clears_the_stored_rows` (run 2 observes `()`, rows clear) —
flattening the `None` branch to `()` fails the first while the second still passes.

## Evidence

- Iteration `iter-2026-09-metadata-audio-layout`; plan `20260926-video-metadata-enrichment`.
- Ruling: `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/delivery-compass.md`
  decision D16; landed in the plan's Task 3 and the gateway/ingestor sources
  (`a8670a3` + `7470ef0`).
- The pre-review state that carried the defect (the plan's own instruction "return an
  empty tuple on those errors"): `{SDD_DIR}/20260926-video-metadata-enrichment/progress.md`,
  "Task 3 — review, the D16 ruling, and the fix round".
- The same defect class measured earlier on a different surface (the
  `video_details.observed_at` advance condition): compass decision D15,
  `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/specs/metadata-coverage-contract.md`
  preamble.

## See also

- [normalized-metadata-stack.md](../architecture-patterns/normalized-metadata-stack.md)
  — the gateway boundary and the bounded exception taxonomy this return protocol extends.
- [claim-scope-discipline.md](claim-scope-discipline.md) — the plan-text side: the
  instruction that created the defect lived in the plan, not the implementer; a claim
  about what a return value means must be checked against every consumer's write.
