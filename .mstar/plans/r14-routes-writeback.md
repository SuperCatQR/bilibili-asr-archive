---
plan_id: r14-routes-writeback
project: _default
status: draft
created_at: 2026-10-02
execution_mode: sdd
plan_parallelism: serial
---
# R14 routes — coordinator/run + subtitle-arm transcript write-back
## Status
- **Priority**: P1 · **Effort**: L · **Risk**: HIGH · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: R14 (F7, high) implemented the asr+pilot store routes in iter-2026-10-followup; the coordinator/run-batch ASR path and the subtitle-arm remain unwired, so `v_missing_transcript` still diverges there.
## Problem
The ASR path archives artifacts but only the asr+pilot store routes record a `transcripts` row. The coordinator/run-batch ASR path and the subtitle-arm (harvest-subs) do NOT, so the gap view keeps listing those parts.
## Approach
Reuse the `queue_source.record_local_transcript` helper + lazy write-back source pattern from iter-2026-10-followup. Wire: (1) the coordinator/run-batch ASR archive stage; (2) the subtitle-arm (a subtitle-sourced transcript also owes a `transcripts` row, source_kind='subtitle-ai'/'subtitle-cc', through the CAPTION writer — NOT the asr-local singleton). One invocation = one run; best-effort (store failures swallowed, archive never lost).
## Files: src/bili_asr/coordinator.py, src/bili_asr/cli/run.py (or the run-batch archive seam), src/bili_asr/services/subtitle_ingest.py (subtitle-arm), tests (extend test_storage_queue_writes.py + the cli_queue pinning tests to cover the new routes).
## Verification: the gap view converges for coordinator/run-archived and subtitle-archived parts; existing asr+pilot pinning tests still pass; scoped storage/coordinator/queue tests green.
## STOP conditions: if the subtitle-arm's source_kind cannot be determined (caption kind ambiguous), STOP + report; if the run-batch archive seam has no clean write-back point, STOP + report.
## Done: all routes record transcripts rows; F7 closed; gap view converges on every route.
