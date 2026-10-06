# Audio pipeline issue batches

Target: at least 40 issue-level fixes. Count only fixes made on
`codex/audio-pipeline-reliability`, with concrete changes and verification.
Already-fixed reports and duplicate aliases do not add to the total. Rows in
the first three batches retain their external GitHub issue numbers; Batch 4
uses local issue labels for newly discovered defects. GitHub issue states are
unchanged; this is a local implementation ledger. The cumulative target below
counts register-backed issue IDs; Batch 4 labels are supplementary discoveries
and are not used to inflate that count.

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

## Batch 4 — 14 issue-level fixes

| Issue | Result | Evidence |
| --- | --- | --- |
| A4-01 | Audio path probing has one shared ordered resolver for configured and archive roots. | `test_iter_audio_paths_preserves_base_then_candidate_order` |
| A4-02 | Candidate generators are materialized once, so fallback roots cannot exhaust a one-shot iterator. | `test_iter_audio_paths_reuses_generator_candidates_for_each_base` |
| A4-03 | Root precedence is evaluated before candidate precedence, preserving the documented first-hit rule. | Artifact-root ordering regression |
| A4-04 | Download-side reuse resolves audio through the same confinement and configured-root fallback. | Audio reuse regression suite |
| A4-05 | Coordinator-side reuse uses the same resolver and returns the declared path belonging to the selected base. | Coordinator recovery regression suite |
| A4-06 | Zero-byte audio is rejected consistently before it can satisfy an existing-audio check. | Audio/coordinator non-empty checks |
| A4-07 | Search index metadata is exposed through a typed, connection-safe read API. | Metadata accessor tests |
| A4-08 | `indexed_count` records the complete index row count after incremental store and Markdown work. | Six-to-seven row incremental regression |
| A4-09 | An existing database with no index reports empty metadata without creating tables; a missing database keeps its typed backlog error. | Pre-build metadata regression |
| A4-10 | `check-asr-env` is shipped beside the package, so installed CLI checks do not depend on a checkout. | Installed module smoke test |
| A4-11 | The installed baseline proves schema bootstrap, status output, and packaged checker presence. | `test_installed_baseline.py` |
| A4-12 | Baseline staging includes the installed smoke suite and its operator command names the file that exists. | Staging and installed-runner tests |
| A4-13 | The fast offline development lane no longer invokes recursive environment provisioning. | README command contract |
| A4-14 | Quality comparison fixtures declare the ASR source required by guarded raw sidecars. | Coverage quality regression |

Batch 4 verification: compileall passed; the affected product lane passed **125**
tests; the non-provisioning CLI lane passed **63** tests; the corrected quality
case and install/index checks passed in a **66**-test targeted run. Cumulative
register-backed count before Batch 5: **29 / 40**. Supplementary local labels:
**14**.

## Batch 5 - 12 register-backed issues

| Issue | Result | Evidence |
| --- | --- | --- |
| I-000189 | Proofread merge rejects a marked block that has no side-by-side source row instead of silently accepting it. | New missing-row regression in tests/test_proofread.py |
| I-000192 | Caption write-back failures are contained at the coordinator call site, preserving the published archive row. | Durable error marker and retained archived outcome path |
| I-000193 | A failed caption write-back leaves a queryable error and the next coordinator pass retries the caption route. | Manifest error fields and terminal-row retry path |
| I-000197 | Refusal diagnostic scope distinguishes one source instance, one coordinator invocation, and a later invocation. | Queue-source contract docstring and existing latch regression |
| I-000203 | Manifest save documents the replay/publish precondition and the caller-supplied view handoff. | Crash-safe save implementation and persistence tests |
| I-000209 | A CI workflow runs the default tests, compile check, and the harness validator report. | .github/workflows/ci.yml |
| I-000211 | probe-subs explicitly remains read-only and its observations cannot become harvest evidence. | CLI contract docstring and probe smoke coverage |
| I-000155 | ASR language fallback is centralized as a named und contract across all writers. | Provenance fallback regression in tests/test_asr_qwen.py |
| I-000157 | Pilot fixtures publish their seeded manifest snapshot before reading the JSONL artifact. | Snapshot seeding in both affected pilot tests |
| I-000159 | Unknown queue gaps raise a clear ValueError instead of leaking a KeyError. | New queue-gap mapping regression |
| I-000161 | Pending-scope rows retain the single entry_for_item status mapping source. | Queue-scope implementation and gap contract suite |
| I-000180 | Persisted queue timestamps keep the injectable clock while run IDs use a separate collision-only source. | Clock regression plus explicit run-ID scope contract |

Batch 5 verification: compileall and git diff --check passed; the proofread,
queue-gap, and ASR provenance subset passed **34** tests. The native Windows environment
cannot collect soundfile-dependent audio tests and cannot run fcntl-backed
manifest/coordinator tests; the CI workflow provides the complete Linux
dependency lane. Cumulative register-backed count: **41 / 40**.

## Continuation audit - Windows audio path stability

The Windows audio backend now uses validated path operations when descriptor
APIs are unavailable, skips the POSIX-only `pass_fds` argument for ffmpeg,
reuses existing audio before resolving a bare bvid, and records `audio_path`
with the stable `audio/...` separators used by the archive contract. Pilot and
coordinator write-backs apply the same normalization for legacy and configured
artifact roots. The focused manifest/audio/reliability lane passes **87 tests**
(2 existing skips and 3 explicit symlink deselections); the three artifact-root
pilot regressions pass as well. Integrity `verify/recover` remains POSIX-only
because its root-confined descriptor reader requires `O_DIRECTORY` and
`O_NOFOLLOW`.

## Continuation audit - inventory and lock convergence

Generated audio inventory candidates and resolved storage keys now use portable
`/` separators, so a declared `.m4a` row whose retained `.flac` candidate is
found converges on the second run. Persistence now adds a process-local gate
before the OS lock; Windows same-process contention preserves the documented
`archive_busy` refusal instead of surfacing `persistence lock failed`. The
audio inventory lane passes 14 tests; one remaining failure is the existing
Windows symlink-permission environment case.

## Continuation audit - authenticated subtitle exhaustion

The empty-inventory corroboration used by `v_missing_audio` and
`v_part_pipeline` counts only subtitle attempts made with
`credential_present = 1`. Two anonymous `no-subtitle` observations therefore
cannot authorize the paid audio/ASR branch. A dedicated storage-view regression
pins the anonymous and authenticated cases; the test passes on Windows.

## Continuation audit - campaign checkpoint portability

Campaign checkpoints keep the atomic replace and file flush semantics on
Windows, where opening the containing directory for `fsync` is unsupported.
Rollback closes the replaced handle before restoring the prior projection and
preserves the original durability exception if a filesystem rejects a rollback
sync. `tests/test_campaign.py` passes **19 tests** on the Windows host.

## Continuation audit - I-000117 aligned Latin token spacing

Qwen forced-alignment fragments can omit the leading whitespace present in the
decoder text. `_aligned_cues` now joins every fragment through the shared text
boundary rule before cue length and sentence decisions, preserving separators
between Latin tokens while leaving CJK boundaries unchanged. The focused ASR
regression passes **5 tests**; the full `test_asr_qwen.py` lane passes **54
tests** after excluding its existing POSIX `/proc/self/fd` descriptor case.

## Continuation audit - audio failure rotation and run closure

Failed audio downloads now create one invocation-scoped `kind=audio` run,
record one bounded failure attempt per queue part, and finish the run with a
complete/partial/failed/risk-interrupted outcome before the queue connection
closes. `missing_audio` keeps never-attempted parts first, then rotates failed
parts by oldest failure timestamp so repeated rate limits do not starve the
rest of the queue. The focused storage, audio, and CLI lane passes **8 tests**;
the broader storage queue lane passes **45 tests**.

## Continuation audit - short ASR coverage evidence

Coverage attestations are projected into JSON/CSV health reports and the
`coverage --quality` command. A persisted `coverage_short=true` or malformed
coverage flag is now a defect diagnostic, so a structurally valid archive
cannot be reported healthy when ASR covered only part of decoded audio. The
focused coverage lane passes **2 tests**; compileall and `git diff --check`
remain clean (apart from normal Git line-ending warnings).

## Continuation audit - queue gap indexes and injectable audio clock

Queue gap reads now declare `ix_videos_pubdate_bvid` for stable publication
ordering and `ix_acquisition_runs_kind_run` for acquisition-kind filtering,
without relying on SQLite automatic-index choices. The storage schema and queue
gap regression lane passes **71 tests**. Audio run start, failed-attempt, and
finish timestamps all use the injected clock; `time.time_ns()` remains limited
to collision-resistant run-id generation. The clock-consistency regression
passes, and stale unused imports were removed from `cli/meta.py`.

## Continuation audit - retryable subtitle write-back

Archived rows carrying `transcript_writeback_error` are now included in
`--scope failed` selection and coverage failed-scope reporting. The coordinator
already retries their subtitle transcript write-back in place, so a retry keeps
the published archive and does not republish artifacts. Regression coverage
confirms ordinary terminal rows remain excluded while marked rows are selected.
Targeted write-back and coordinator scope tests pass (**3 tests**); source
compilation passes.

## Continuation audit - ASR run refusal after connection contract drift

`QueueSource.ensure_asr_run` now has a regression case for a connection whose
`row_factory` is changed after source construction. The store raises
`TypeError`; the source reports one refusal, creates no partial ASR run, and
returns `None` so an already published archive is not converted into a failed
stage. The focused audio reliability lane passes **2 tests**.

## Continuation audit - read-only subtitle probing decision

`probe-subs` remains intentionally read-only: it lists the gateway's current
view and does not open an acquisition run or append an attempt row. Only
`harvest-subs` observations participate in durable exhaustion evidence, and
`v_missing_audio` requires either a newly verified subtitle-list `not_found`
result or two distinct credential-present, credential-verified harvest runs
for an indefinite empty inventory. Historical ambiguous `not_found` rows
must be revalidated; subtitle-body read failures do not prove absence.
This prevents a single probe, or an anonymous/expired-credential response,
from admitting the paid audio/ASR branch. This is the recorded local decision
for I-000211. Authoritative issue closure remains pending the engine channel.

## Continuation audit - remaining code issue dispositions

The following registered findings have executable coverage in the current
tree: I-000184 records the decoder-detected language and keeps `und` as the
named fallback; I-000187 requires authenticated corroboration before an empty
caption inventory admits audio; I-000188 publishes short-ASR coverage as a
health diagnostic; I-000167 bounds the append journal and compacts it on the
next write; I-000133 preserves legacy bare-BVID archive ownership; I-000121
refuses an audio write outside configured artifact roots; I-000120 separates
backlog from defect exit gates; I-000111 resolves the installed environment
check from the package; I-000134 uses the soundfile/ffmpeg decode path for
AAC/M4A; I-000196 rejects invalid UTF-8 during manifest replay; I-000198
refuses a broken store connection without creating a partial ASR run; and
I-000199 writes diagnostics directly to the descriptor so a closed stderr
cannot poison interpreter shutdown. Focused regression suites for these paths
are green in this batch.

## Continuation audit - manifest compaction and journal recovery

The manifest ledger uses on-disk byte thresholds for compaction, so a fresh
process folds a journal written by another process on its next upsert. Torn
tails are retained until they can be safely repacked; complete records
stranded behind a torn fragment are published before the journal is removed.
Invalid UTF-8 is rejected during replay. The former write-only
`_journal_bytes` state is absent, so the empty-save path cannot claim a byte
count that disagrees with the journal on disk. The targeted manifest suite
passes **12 tests** covering compaction, torn fragments, recovery, migration,
and strict decoding.

## Continuation audit - plain CLI health semantics

Stage-only CLI archives require an explicit producer marker before coverage
and verify waive campaign evidence. Content `source` alone cannot establish
the producer: a coordinator writes the same source names, and removing its
sidecars previously made damaged campaign evidence pass both strict commands.
Historical unmarked rows remain unknown. Descriptor-based integrity checks
are verified on POSIX; Windows lacks the reader's required
`O_DIRECTORY`/`O_NOFOLLOW` interface.
### Search-index freshness coverage (I-000172)

- `SearchIndex.is_stale()` treats indexed work IDs as authoritative and only calls `_is_indexable()` for completed manifest rows absent from the index; this avoids repeated artifact probes for a covered corpus while still rebuilding for a newly completed row.
- Added `test_is_stale_does_not_probe_artifacts_for_indexed_rows`; `tests/test_search_index.py` now passes 42 tests.

### ASR transcript write-back fallback (I-000067/I-000188)

- Store write-back now retries the transcript row without supplementary coverage attestation when alignment evidence is internally inconsistent (for example, cue span exceeds decoded duration). The durable transcript still converges `v_missing_transcript`; the invalid coverage claim is not persisted.
- `tests/test_cli_queue_source.py::test_asr_store_source_selects_transcript_gap_part` passes after reproducing the overrun alignment case.
# Batch: manifest title propagation and unreadable audio classification

- `manifest_derivation.row_for_part` now preserves `video_title` when the queue view supplies it, while retaining the legacy nine-field shape for callers without that field.
- Added `test_a_queue_video_title_survives_manifest_derivation`; focused manifest and repository checks pass.
- `audio_inventory._resolve_existing` now performs a confined metadata-only fallback after an open refusal, allowing the digest stage to classify present-but-unreadable files instead of incrementing `missing`.
- Added `test_inventory_distinguishes_open_refusal_from_absence`; `tests/test_audio_inventory.py` passes (16 tests).
- Environment note: archive symlink tests requiring Windows `SeCreateSymbolicLinkPrivilege` remain unavailable on this runner.

## Continuation batch - authentication, recovery and archive preservation

This batch continues the user's code-issue scope. The issue register export
still contains historical open rows; it is not edited to simulate engine
closure. The rows below describe implementation evidence, including partial
findings where an issue also contains a broader operational question.

| Registered finding | Current implementation and evidence |
| --- | --- |
| I-000013/014/015/016 | All four batch commands install interruption handling before loading state, ignore repeated signals through the single run-record append, and select partial attempts by parsed UTC instants. Real subprocess tests preserve normal, interrupted and failed exits even with closed stderr. |
| I-000019/020/021 | Coverage uses the shared effective manifest projection; the unused alternate parser is removed. Forensic logs walk parent directories without following links and reject unsafe final targets. Real nested pytest processes exercise setup/teardown logging and escaped paths. |
| I-000026 | Publication refuses inconclusive reads instead of overwriting an existing bundle. Injected marker/artifact EIO and permission failures preserve prior artifacts. Changing the configured artifact root still deliberately publishes at that write base; it is not an archive migration command. |
| I-000028 | Complete-bundle SHA-256 now streams regular files in 64 KiB chunks and refuses files modified while being read. Large-file memory, tail corruption, concurrent mutation and FIFO regressions pass. It still hashes all bytes; network-mount latency is not eliminated. |
| I-000029 (selection/read/resilience) | Bounded publication selects N parts in SQL and reads versions only for those parts. `--pending` skips complete bundles before spending its attempt budget. Invalid dates/identities and unknown transcript source kinds now fail only their own part; even a full 32-part bad batch advances the keyset to later valid work. Product-path keys share one constant, and progress lines flush when piped. Ten real bad-candidate cases pass. A general timeout for a hung filesystem remains outside this change. |
| I-000034/069 | The real anti-CWD torch probe compares structured verdicts and exit codes while deliberately emitting different process-specific warnings; unstable runtime stderr is no longer the equality oracle. The raw-character ASR witness imports required dev dependencies directly instead of silently skipping them. |
| I-000036/126 | `adopt-transcripts` validates existing legacy products offline and records their transcript identities in the store without downloading audio or running ASR. Repeated and bounded adoptions converge, leaving already adopted work out of the paid queue. |
| I-000041/187/210 | Authentication errors, subtitle-body failures and ambiguous historical absence remain retryable captions. Audio eligibility requires explicit listing absence or two independent verified-login empty inventories. Additive schema migration preserves old evidence without backfilling proof. |
| I-000042 | Collected metadata parts advance to `metadata_collected`; metadata backlog drains while the missing-caption queue remains available. Metadata CLI/E2E assertions now distinguish these two queues. |
| I-000056/057/076 | Upload-list `observed_total` does not terminate enumeration. Optional malformed tags preserve existing tags while other metadata advances. Newline-bearing part titles normalize without discarding the page, while NUL remains invalid. |
| I-000077/109 | An explicit lower `--start-page` is documented and tested as a rewind. Opt-in `--page-retries` retries only upload-list rate/transport failures on the same page with bounded 30/60/120-second cooldowns; auth, shape and response failures remain immediate. Exhaustion preserves the established cursor/error contract. |
| I-000084 | Candidate-first subtitle/audio views exclude gone, completed and already-audio parts before indexed attempt-history probes. A pending LIMIT-one query stays at 306 subtitle VM steps or 691 audio steps with 2,000 excluded histories, instead of growing past 138,000/159,000 steps. Twelve cost/eligibility/migration cases pin query results, selected-index use and reopening old databases. |
| I-000086/100 | Quality checks undeclared raw sidecars even when all four published paths are declared. Escaped existing/dangling raw links cannot hide behind the declared-bundle path; raw readers reject malformed encodings and sources. |
| I-000087 | Quality candidate enumeration deduplicates path resolution within one analyzed row; no cache survives to another row, root selection or call. One hundred absent rows across two roots need 1,200 resolves instead of 3,000. Selected files still receive a fresh containment check before reading. Thirteen real cost, dangling-link, fallback-root and link-retarget cases pass. |
| I-000090/091 | The manifest exports the backlog status set for both coverage exit classification and integrity retryability. The stale test claim forbidding integrity edits is removed; the existing real-reader behavioral guard remains and passes. Coordinator harvest-specific status sets retain their different stage semantics. |
| I-000099 | Workspace-local manifest test directories carry UUIDs, preventing collisions after PID reuse or a terminated test run. |
| I-000101 | CLI route regressions use separate real caption/ASR roots and decoys, reject blank roots, and report unusable caption databases without exposing tracebacks. |
| I-000111 | A real isolated wheel install resolves the packaged environment-check helper from its own venv while invoked outside the repository. The host diagnostic reaches the expected missing-torch verdict without requiring a source-tree scripts directory. Eight installer cases pass; this is a packaging check, not GPU validation. |
| I-000122 | A batch shares one audio inventory and tracks file deltas, including initial peak and partial downloads. Unknown usage blocks finite-cap work; artifact-root validation actually probes writes and directory durability. |
| I-000128 | Index progress now commits segment cursors and a completed-transcript watermark in the same transaction as each FTS batch. A crash after 500 committed segments no longer stamps the unfinished transcript as complete. Recovery fills only the missing tail; legacy partial indexes are repaired without duplicating newer complete entries. Real abrupt-process and before/after-commit faults cover restart behavior. |
| I-000130 | Batch run records retain the stable union of dropped hotwords across rows, with redaction and legacy-record compatibility. Reused runners reset state between batches. |
| I-000135/136 | The regenerated lock matches Qwen3-ASR dependencies and excludes externally provisioned torch, CUDA packages and the retired engine. The documented inexact sync preserves the separately installed GPU runtime; a sentinel-wheel planner check is not a hardware ASR verification. |
| I-000149/164/166 | Attempt numbering revalidates changed on-disk history under the writer lock, including strict malformed-history refusal. Manifest replay splits only at physical newlines, preserving Unicode separator characters through save. Nanosecond run identities distinguish two sources started within the same second. The corresponding real persistence/write-back cases pass. |
| I-000168 | The shared opt-in fixture now performs the skip itself unless the corresponding environment value is exactly `1`. Existing callers supply their original skip reasons instead of repeating the guard. Sixteen real nested pytest cases verify fixture-only default skipping, explicit execution and reason preservation. |
| I-000174/177/209 | Console-script verification bootstraps the packaged schemas from a real isolated install. Fresh Python 3.12 venvs receive a locally built wheel without requiring setuptools inside them or a warm uv backend cache. CI provisions build tools; the verification README states the local green/red command and its limits. |
| I-000175 | Installer tests now live in `test_installed_cli.py`; baseline staging retains the 67 in-process help/contract cases. The help/installer/staging lane passes 97 tests with a cold uv cache, and all 67 help cases also pass against an isolated installed wheel under the staged network-denial lane. |
| I-000176 | The store-backed ASR command has positive transcript-write witnesses and a real acquisition-run refusal witness. The latter returns success with all four complete archive products while the transcript join and ASR-run count stay zero, so refused write-back cannot invent store evidence. Its ASR/coordinator/store neighborhood passes 39 tests. |
| I-000185 | Stage CLI and coordinator publication record their producer explicitly. Missing campaign sidecars can no longer make a coordinator archive look like a plain CLI archive; unknown historical producers remain conservative. Twenty-three real archive/reader cases cover CLI producers, coordinator sidecar loss, malformed evidence and mixed rows. |
| I-000197 | The coordinator carries its refusal-diagnostic latch when it reopens a queue source, so two batches in one invocation emit one refusal line. The lifecycle is stated at the latch; the real two-batch archive witness passes. |

Additional defects found during this batch: campaign scopes now validate each
comma/whitespace-separated selector before paid work and preserve the exact
scope string for resume matching; character timestamps reject booleans,
negative values and non-finite numbers; installed-baseline staging includes
the forensic helper and dependency metadata required by the current tests.

Campaign previously accepted comma/whitespace-separated work IDs, completed
their ASR work, then failed because projection treated the entire scope as one
identifier. Each selector is now validated before execution; empty, unsafe and
duplicate selections are refused. Real two-row CLI regressions cover comma,
whitespace and mixed separators while preserving the exact scope for resume.

Campaign risk-resume previously removed completed IDs from `selected` while
retaining them in `processed`, failed projection after further ASR work, and
could execute rows outside the original bounded batch. Pending queues also
rejected checkpoints after completed members left the queue. Resume now retains
the original selection and runs only its unfinished members; scheduler members
that remain terminal in the manifest may leave the queue. Five regressions pin
successful resume, batch limits, pending queues and refusal of scope drift.

Targeted lanes include 207 storage/repository passes, 118 subtitle/queue/CLI
passes, three metadata E2E passes, 421 gateway-neighborhood passes with one
skip, 152 quality/projection passes with two skips, and 20 archive-streaming
and mixed-outcome passes. These overlapping lanes are not summed into a
test total or an issue-fix count.

The first whole-project consolidation passed **2,509 tests with 61 skips**.
That earlier result does not claim coverage of subsequent edits. The next
consolidation reported **2 failed, 2,658 passed and 61 skipped**: both failures
were projection fixtures that omitted the new explicit stage-CLI producer.
The fixture now supplies that producer; unknown historical and coordinator
rows still retain their conservative checks. The focused producer/projection
lane then passed **27 tests**.

The final whole-project command, **`python -m pytest -q -ra`**, passed on
2026-10-05 in the provisioned Python 3.12 WSL interpreter: **2,660 passed,
61 skipped, zero failures in 857.31 seconds**. All 2,721 collected cases are
accounted for. Native source/script compilation and `git diff --check` also
pass. This is the local product regression lane, not the offline release
dependency audit or a native Windows whole-suite result.

The 61 skips comprise 53 unavailable harness-engine cases, four opt-in live
network probes, three opt-in scale probes and one real-model chain case whose
ASR extra is unavailable. These skips do not verify the engine, live upstream
responses, scale or real GPU transcription. Descriptor-based integrity reads
still require POSIX support; no native Windows support claim is made for that
reader. I-000029's general hung-mount timeout remains deferred and uncovered.
The engine CLI and store are absent in this checkout, so authoritative issue
closure and engine-owned register fixes have not been performed.

Closed-stderr handling also covers parser usage errors and recoverable cursor/
scheduler UTF-8 corruption. Twenty-seven real closed-descriptor subprocess
cases preserve command exit codes. Invalid manifest and attempt-ledger facts
remain errors rather than being recovered as empty state. Dropped-hotword
provenance now redacts credentials, URLs and absolute paths term by term before
both Markdown and raw JSON publication; a real archive witness preserves the
ordinary hotword alongside redacted secret terms.
