# Audio pipeline issue batches

Target: at least 40 distinct GitHub issues. Count only fixes made on
`codex/audio-pipeline-reliability`, with concrete changes and verification.
Already-fixed reports and duplicate aliases do not add to the total.
GitHub issue states are unchanged; this is a local implementation ledger.

## Batch 1 — 4 issues — commit 00a4356

| Issue | Result | Evidence |
| --- | --- | --- |
| #184 | Acquisition runs record the actual selector and limit. | Scope tests in test_audio_pipeline_reliability.py |
| #185 | ASR detects and persists language, clearing it between recordings. | Single/multiple-language and failure-reset regressions |
| #186 | ASR, pilot and coordinator finish their acquisition runs on unwind. | Completed, failed and interrupted-run regressions |
| #196 | Transcript conversion/store failures preserve published bundles and archived status. | Writeback failure regressions |

Additional audio improvements in this batch: real lossless FLAC conversion,
CDN backup retry, empty-download rejection, existing-audio reuse before budget
checks, and recovery after a recorded audio file goes missing.

19 new regressions passed. The broad focused check passed 321 cases with one
pre-existing failure. Full-suite baseline comparison and environment limits:
[audio-pipeline-2026-10-04.md](audio-pipeline-2026-10-04.md).

## Batch 2 — 11 issues

| Issue | Result | Evidence |
| --- | --- | --- |
| #210 | Only authenticated empty observations corroborate caption exhaustion, in both queue views. | Anonymous, mixed and authenticated pairs; reopening existing databases |
| #200 | Connection row-factory violations are handled as refused supplementary writes. | Archive success survives a connection losing its contract |
| #201 | Shared stderr diagnostics avoid dirtying dead buffers. | Four subprocess probes close fd 2 and retain exit 0 |
| #199 | Run-refusal diagnostics remain latched across coordinator batches. | Two batches, one refusal diagnostic |
| #193 | Caption writeback documentation matches publication-before-writeback ordering. | Both coordinator descriptions checked |
| #182 | Queue timestamps use the shared injectable clock; dead CLI imports removed. | Persisted run/attempt/audio timestamps pinned |
| #181 | Both scope filters use the shared terminal status set. | Added-terminal-status regression |
| #154 | Caption language accepts its documented sub_lan_doc fallback. | Fallback and code-priority checks |
| #124 | An audio path confined by no archive base raises instead of silently skipping the manifest write. | Escaped-path rejection leaves needs_audio intact |
| #173 | Transcript/audio writebacks resolve canonical work_id or skip unresolved rows. | Bare-bvid skip and nonzero-page attribution |
| #112 | ASR manifest rows carry source and language in all three archive routes. | Bundle, export, filtered search and authoritative integrity checks |

Final affected-surface check: 70 passed, including all 14 new regression cases.
The broader coordinator/download/path check passed 152 cases; its three fixture
failures were corrected to supply authenticated exhaustion evidence and all
three passed on rerun. Queue-gap and derived-chain checks passed 25 cases with
one existing skip. Cumulative confirmed count: **15 / 40**.

Related #153 local-time alias cleanup is covered by #182 and is not counted
again. #197 was already fixed at the starting commit and is not credited.
