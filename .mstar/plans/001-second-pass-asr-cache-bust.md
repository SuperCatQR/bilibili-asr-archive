---
plan_id: 001-second-pass-asr-cache-bust
project: _default
primary_spec: .mstar/plans/audit-2026-10-02/001-second-pass-asr-cache-bust.md
status: draft
created_at: 2026-10-02
execution_mode: sdd
plan_parallelism: serial
---
# Plan 001 — Second hotword pass re-decodes from a clean model/cache state

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/010-*.md (dedup the shared two-pass helper; land together or 001 → 010)
- **Category**: bug
- **Confidence**: MED
- **Evidence**: `src/bili_asr/coordinator.py:596-603` — two back-to-back `runner.transcribe()` calls with only a pure-string reseed between them
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

The evidence-based hotword contract (governance ruling 2026-09-28, plan
`20260928-hotword-injection-governance`) is a **two-pass** decode:

1. Pass 1 runs unguarded.
2. `rebuild_hotwords_from_first_pass()` re-seeds the prompt with the tokens pass 1 produced.
3. Pass 2 re-decodes **with the new prompt** and the kept tokens are expected to reach the model.

Nothing between the two `transcribe()` calls invalidates the runner/model's cached state. The reseed
(`src/bili_asr/asr.py:1265-1293`) is a pure string guard — it never touches the model. So a runner/model
that caches per-audio state (prefix cache, preprocessor memo) can serve pass 2 partly from pass 1's cache:
the re-seeded hotword vocabulary never reaches the prompt for the cached span, and a kept token stays
unapplied. The archived text then differs **silently** from the text the operator believes the two-pass
contract produced (the run prints no pass marker). This is the exact insertion-error class the evidence
guard exists to prevent, produced by the guard's own repair pass.

This is distinct from residual **O-R1**, which registers only the *duplication* of the orchestration, not
this correctness implication.

## Current state (excerpts — verify against live code before editing)

`src/bili_asr/coordinator.py:593-603`:
```python
runner.set_hotword_evidence(
    evidence_text=None, paired_subtitle_text=paired_subtitle_text
)
with confined_audio_file(audio_base, audio_declared) as safe_audio:
    first_pass = runner.transcribe(safe_audio)
transcript_text = "".join(str(seg.get("text", "")) for seg in first_pass)
if runner.rebuild_hotwords_from_first_pass(transcript_text):  # kept tokens
    with confined_audio_file(audio_base, audio_declared) as safe_audio:
        segments = runner.transcribe(safe_audio)
else:
    segments = first_pass
```

`src/bili_asr/cli/asr.py:216-227` carries the identical sequence (the O-R1 duplication).

`src/bili_asr/asr.py:1084-1086` — `_transcribe_chunk` calls `models.model.generate(**inputs,
max_new_tokens=budget)` with **no** `past_key_values` / cache-control argument, so the transformers
dynamic prefix cache is default-active across both passes.

## Approach

Introduce an explicit cache-busting boundary between the passes and collapse the two duplicated call
sites into one shared helper (this also closes O-R1's duplication half).

1. Add a per-pass cache-control knob to the runner's transcribe path. Concretely: thread an explicit
   `pass_index: int = 1` (or `bust_cache: bool = False`) argument down to `_transcribe_chunk`, and on the
   pass-2 call pass the cache-disabling equivalent for the pinned `transformers>=5.13` generate API
   (e.g. `past_key_values=None`, or the model's documented cache-reset). The exact API must be confirmed
   against the pinned transformers version — see STOP conditions.
2. Extract the two-pass orchestration into one helper, e.g.
   `two_pass_transcribe(runner, audio_path, *, paired_subtitle_text) -> tuple[segments, provenance]`,
   living in `src/bili_asr/asr.py` (or `coordinator.py`). Both `cli/asr.py` and `coordinator.py` call it.
   The helper returns `(segments, provenance)` so both call sites keep their current output shape.
3. The helper performs: `set_hotword_evidence` → pass 1 (cache warm) → `rebuild_hotwords_from_first_pass`
   → if kept tokens: **bust cache** → pass 2. Return pass-2 segments (or pass-1 segments when no tokens
   kept).

## Files

- **Modify**: `src/bili_asr/asr.py` — add the cache-control argument to `transcribe`/`_transcribe_chunk`;
  add `two_pass_transcribe`.
- **Modify**: `src/bili_asr/coordinator.py` — replace the `:593-603` block with a call to
  `two_pass_transcribe`.
- **Modify**: `src/bili_asr/cli/asr.py` — replace the `:216-227` block with the same call.
- **Test**: `tests/test_asr_qwen.py` (the existing fixture-only runner tests) — add the pass-2 cache-bust
  regression below.

## Out of scope

- `tests/_asr_fakes.py` — the canned model double. Do not change its public shape; extend it only if the
  new cache-control argument needs a recording hook (see test).
- Residual O-R1's *tracking* entry (the register row) — PM closes that separately; this plan only removes
  the duplication it names.
- The unmeasured-hotword re-measurement work item (README §"corpus vocabulary") — that is a direction
  decision, not this plan.

## Verification gates

- **New regression test** in `tests/test_asr_qwen.py`: drive `two_pass_transcribe` with a stub model that
  records cache state / the generate kwargs across both `generate()` calls. Assert pass 2's generate call
  observes the re-seeded prompt **and** a cleared/reset cache (i.e. the cache-control argument is present
  and non-warm on pass 2). This is the core gate — it must fail on the pre-fix code (both passes currently
  issue identical generate calls) and pass after.
  - Run: `python3.12 -m pytest tests/test_asr_qwen.py -k two_pass -v` → the new test passes.
- Existing runner contract preserved:
  - Run: `python3.12 -m pytest tests/test_asr_qwen.py -q` → the cue rules, chunker tiling, runner
    construction/attempt, and provenance tests still pass (no behaviour change to the single-pass path).

## STOP conditions

- If the pinned `transformers>=5.13` generate API does not expose a usable cache-control / prefix-reset
  argument, STOP — report the exact API surface you found (and version) instead of guessing a kwarg.
- If `transcribe()`'s signature is consumed by a caller you cannot see in the three files above, STOP and
  list the extra caller before widening the signature.
- If the pass-2 re-decode on the real model is confirmed *not* to cache (i.e. the cache-bust is a no-op),
  STOP — report that the finding is refuted on the pinned engine and PM will downgrade it (the plan still
  removes the O-R1 duplication).

## Done criteria

- [ ] `python3.12 -m pytest tests/test_asr_qwen.py -k two_pass -v` passes; the new test fails before the
      fix and passes after (record the red/green).
- [ ] `python3.12 -m pytest tests/test_asr_qwen.py -q` passes (single-pass path unchanged).
- [ ] `rg -n 'rebuild_hotwords_from_first_pass' src/bili_asr/cli/asr.py src/bili_asr/coordinator.py` → the
      orchestration no longer appears inline in both (it lives in the shared helper).
- [ ] `git diff --check -- src/bili_asr/asr.py src/bili_asr/coordinator.py src/bili_asr/cli/asr.py tests/test_asr_qwen.py` exits 0.
- [ ] No files outside the Files list are modified (`git status --short`).

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/asr.py src/bili_asr/coordinator.py src/bili_asr/cli/asr.py tests/test_asr_qwen.py` — if any in-scope file changed, re-open the "Current state" excerpts above and confirm they still match live code before editing.
