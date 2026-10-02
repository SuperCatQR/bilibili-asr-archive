---
plan_id: r14-asr-transcript-writeback
project: _default
status: draft
created_at: 2026-10-02
execution_mode: sdd
plan_parallelism: serial
---

# R14 — ASR transcript write-back so `v_missing_transcript` converges

> This plan **implements the high residual R14** by executing the already-authored owning plan
> `.mstar/plans/20260929-asr-local-transcript-storage.md`. That plan is the authoritative spec
> (Prepare already done: `gate_decision: pass`, 2026-09-29). This file is the iteration's
> registration pointer; the executor MUST read and follow the owning plan verbatim.

## Status
- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: none
- **Category**: bug
- **Confidence**: HIGH
- **Planned at**: commit `e50bed6`, 2026-10-02

## The defect (from the owning plan + residual R14)
The ASR path archives `srt`/`txt`/`md` artifacts to disk and writes a manifest row, but never
writes a `transcripts` row, so `v_missing_transcript` (which requires audio evidence AND no
stored transcript) never drops the part and a naive re-run re-selects it (paying the GPU again).

## Approach (per owning plan)
Follow `.mstar/plans/20260929-asr-local-transcript-storage.md` exactly — it defines the
write-back through the repository's own writer (`TranscriptRepository.record_acquired_transcript`
after widening `ALLOWED_CAPTION_SOURCE_KINDS` to admit `asr-local`), the gap-view convergence,
and the two pinning tests (`tests/test_cli_queue_source.py::test_asr_store_source_selects_transcript_gap_part`,
`::test_pilot_store_source_uses_gap_views`).

## Done criteria
- [ ] The two pinning tests pass (they currently fail on `main`).
- [ ] `v_missing_transcript` converges (the ASR-archived part no longer appears).
- [ ] Owning plan's own verification gates hold; scoped storage/cli-queue tests green.
