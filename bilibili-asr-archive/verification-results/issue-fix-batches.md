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

## Batch 2 — 11 issues — commit 3575990

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

## Batch 3 — 14 issues

| Issue | Result | Evidence |
| --- | --- | --- |
| #198 | Invalid UTF-8 journal bytes fail closed and cannot become substituted durable keys. | Corrupt-byte load/save fault regression |
| #204 | Removed the write-only journal byte counter and unused replay return value. | Manifest persistence/compaction suite |
| #205 | Explicit save publishes the desired replay view before its snapshot, closing stale-journal crash recovery. | Snapshot-publication and journal-discard fault injection |
| #122 | Quality counts one preferred transcript's cues instead of summing raw and SRT duplicates. | Published bundle and coverage summary count regressions |
| #95 | Quality coverage applies the same backlog diagnostic exit policy as plain coverage. | Default success and strict-failure regression |
| #46 | Bundle path keys have one shared lightweight declaration across writers/readers. | Bundle, projection, integrity and CLI checks |
| #47 | Publication date rendering has one UTC implementation. | Existing zone-independent date regressions updated to the shared seam |
| #106 | Compact raw JSON reduces character-sidecar size without rounding away timing precision. | Exact character timings and measured serialization reduction |
| #109 | Empty ASR/caption input roots are rejected at the proofread boundary. | Four CLI cases covering empty and whitespace roots |
| #91 | Transcript writes validate scalars before looking up a part. | Invalid transcript id reports its own type error |
| #136 | Derivation honors archived legacy video-level ownership rather than scheduling another paid pass. | Bare-bvid ownership regression |
| #108 | ASR quality/integrity reject wrong-source or unattributed raw sidecars; integrity validates cue shape. | Source/shape controls plus integrity suite |
| #150 | Removed the unreachable stamped-part membership guard from the filtered rebuild loop. | Store search rebuild tests |
| #111 | Long reference comparisons return bounded, explicitly windowed agreement. | Endpoint sampling, full lengths, offsets and disagreement checks |

Verification: 140 passed on affected quality/projection/CLI surfaces; a cross
check of recovery, integrity, search, proofread, store writes and all pipeline
regressions passed **186 with 2 existing skips**. The pre-existing raw-character
test double was updated for the current decode signature and now passes.
Cumulative confirmed count: **29 / 40**. #98 overlaps #95 and is not counted.
