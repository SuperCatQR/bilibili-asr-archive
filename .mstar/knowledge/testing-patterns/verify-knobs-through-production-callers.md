---
title: "Verify knobs through production callers, not the API they expose"
problem_type: testing_pattern
category: testing-patterns
date: 2026-10-02
source_plans:
  - 001-second-pass-asr-cache-bust
  - iter-2026-10-audit-burndown
severity: medium
module: bili_asr.asr two-pass hotword path
status: active
---

# Verify knobs through production callers, not the API they expose

## Context

Plan 001 (iter-2026-10-audit-burndown) added a `bust_cache: bool = False` keyword to `ASRRunner.transcribe` so the second pass of the two-pass hotword re-decode could pass `use_cache=False` to `model.generate` and not reuse pass 1's transformers prefix cache. The accompanying regression test drove the runner directly — `transcribe(bust_cache=True)` — and passed.

## Guidance

- **A knob is not wired until a production call site passes it.** The unit test proved the flag *plumbs through* the runner, but **zero** production callers passed it: both pass-2 re-decode sites (`cli/asr.py`, `coordinator.py`) still called plain `transcribe(safe_audio)`. The fix the plan existed to deliver was **inert in production** while its own test was green.
- **Test the wiring, not just the capability.** Add a test that drives the *production caller* (or the shared helper the callers route through) and asserts the knob reaches the low-level call. The wiring test must fail in exactly the regression class "knob unwired from the call site" — a direct-API test cannot catch that class.
- **Prefer extracting the shared helper the call sites duplicate.** Both call sites had hand-rolled, near-identical two-pass blocks. Extracting `two_pass_transcribe(...)` into the module and routing both callers through it (a) makes the knob wiring a single point of truth, (b) closes the duplication residual the plan had deferred, and (c) gives the wiring test one obvious target.
- **Reviewers: grep for the call, not just the definition.** The defect survived because review confirmed `bust_cache=True` reaches `generate` *inside the runner* — but never checked that any caller passes `True`. The cheapest catch is `grep -rn '<knob>=True' src/` returning **zero** non-test hits.

## Why this matters

This is the "dead code in production" failure shape: a correct, well-tested mechanism that nothing invokes. It is invisible to the mechanism's own tests and to capability-focused review. The iteration's QC tri caught it only because a seat grepped for who actually passes the flag — and all three seats independently converged on it as the Critical.

## When to apply

- Any plan that adds a toggle / flag / option to a lower layer and expects upper layers to opt in.
- When a fix's acceptance is "behaviour X now happens in production" — the test must reach production through a real caller, not shortcut the layer under test.
- When two or more call sites duplicate the orchestration a knob belongs to.

## Examples

- **The defect (plan 001):** `bust_cache` knob threaded through `asr.py`, but both pass-2 sites called `transcribe(safe_audio)` without it → the two-pass hotword fix was a no-op in production.
- **The fix:** extracted `two_pass_transcribe` (sets evidence → pass 1 warm → re-seed → pass 2 `bust_cache=True` iff tokens kept), routed both `cli/asr.py` and `coordinator.py` through it, and added two wiring tests that drive the helper and assert pass 2 reaches `generate` with `use_cache is False`.
- **The re-review catch (same round, QC C1):** the second-pass wiring was itself initially left unverified; the QC seat's grep for `bust_cache=True` in `src/` (zero hits) is what surfaced it.

## Related

- `absence-assertion-negative-control.md` — a test is evidence only if its fixture can reach the falsifier; a direct-API knob test cannot reach "the call site didn't pass it".
- `claim-scope-discipline.md` — a claim ("pass 2 busts the cache") must be checked against the mechanism, not the intent.
