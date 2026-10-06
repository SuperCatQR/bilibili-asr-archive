# Issues 115 and 167 evidence review

Date: 2026-10-06. Fresh code/tests reviewed at runtime commit `31979d69a30d535f2e7314951e0f08503d7c7613`; primary tree during inspection was `8d568536c282f6ea0ba715aaf4b0e7bb9c65737c`. No network media/model downloads, real inference, remote connection or GPU work was performed during this review.

## #167: acceptance met by current code and fresh regressions

`src/bili_asr/coordinator.py:919-951` (`_stage_subtitle_archive`) publishes and verifies the complete bundle, records `archive: ok`, and calls `_mark_archived` before `_record_subtitle_transcript`. Caption store conversion/write-back failures are caught separately and recorded as durable supplementary write-back failures. They do not turn the completed archive into `archive: failed`.

Fresh WSL command, cwd `/mnt/c/wt/bd-r/bilibili-asr-archive`, `PYTHONPATH=src`, Python `/home/chosenecho/.venvs/bili-asr-pipeline/bin/python`:

```text
python -m pytest tests/test_coordinator.py::test_run_batch_subtitle_archive_records_published_bundle_when_writeback_fails tests/test_coordinator.py::test_run_batch_subtitle_route_records_the_caption_transcript -q --tb=short
2 passed in 3.38s
```

`tests/test_coordinator.py:1785` defines the failure witness; `:1728` defines the positive control. The failure case uses a reachable empty-caption cue: bundle publication accepts the shape while transcript record validation raises `ValueError`. Fresh readers observe exactly one `archive: ok` attempt, all four products and an archived manifest row with `transcript_writeback_error=ValueError`. The positive control produces stored AI and CC transcript rows and drains the queue gaps. These are offline regression tests with real files and SQLite writes, not live ASR evidence. **#167 is ready to close.**

## #115: original live evidence gap was later exercised; current rerun is unavailable

The issue describes subtitle-first admission as intentional and accepts `defer`. Its impact says the only live audio evidence predates artifact-root and queue-bridge iterations. That statement is superseded by committed historical reports, found in this review:

1. `.mstar/workflows/e2e-23191782-asr-vs-subtitle-webdav/reports/e2e.md`, Results at line 106; exact scenario rows A1/A2/A3/A4 at **118/119/120/121**, executed **2026-09-22** on the remote WSL2 host `DESKTOP-HHFROLO`, build `37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030`. A1 uses a fresh store with zero captions and admits six genuine parts through derive-manifest. A2 records six successful audio acquisitions under `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle`, total 145,596,128 bytes. A3 records six real GPU ASR completions, 26,282 seconds of source audio, 4,166 seconds GPU wall time, and nonzero cues. A4 records all four families and completion markers at that artifact root, 24/24 recomputed product hashes matching, and the separate AI reference root unchanged. This was Fun-ASR, not the current Qwen engine. A6 and A8 have recorded failures on comparison limits/reader source and attempt-sidecar diagnostics; this review does not relabel the overall run as all passed.
2. `.mstar/workflows/e2e-23191782-love-items-dual-route/reports/e2e.md`, checkpoint round 2 **2026-09-30** at line **447**, B3/B4/B5/B6 at **476/477/478/479**, C1 at **482**, build `be28369` plus the disclosed R10 hot-fix. B1-B3 use a separate caption-free root and no-subtitle admission, B4 records four real downloaded audio objects under `/mnt/e/bili-e2e/love-dual-route`, 97,767,322 bytes, and B5 records four real Qwen ASR completions with 2,237 seconds GPU wall time. B6 records four-family consistency. C1 verifies writable root and directory sync on drvfs. B7 still finds no ASR store transcript writer on that historical build; later fixes are independently tested elsewhere. This report did **not** use `/mnt/123pan` and is not a WebDAV performance result.

These reports are historical evidence reviewed from repository files; their remote raw logs, current products and recorded hashes were **not** re-read or recomputed in this session. They demonstrate that a fresh caption-free store exercised the originally missing real audio-to-ASR/artifact-root scenarios without changing the subtitle-first policy. They do not establish that the current build or native transformers migration has passed a fresh live inference run. The earlier audit's categorical claim that no post-iteration live audio evidence exists should be corrected.

### Current local availability probe

- Linux ffmpeg is present at `/usr/bin/ffmpeg`.
- `/home/chosenecho/.venvs/bili-asr-pipeline/bin/python` and the project's `.venv-wsl/bin/python` have soundfile but lack torch, transformers, accelerate and qwen_asr. `/home/chosenecho/asr-env/bin/python` also lacks these ASR dependencies and soundfile.
- The inspected WSL cache/workspace/asr-env locations contain no discovered project real recording or Qwen ASR checkpoint. The inspected Windows Hugging Face cache contains a forced-aligner cache directory and faster-whisper cache, but no discovered complete Qwen ASR checkpoint. `BILI_ASR_MODEL`, `BILI_ASR_ALIGNER_MODEL`, `HF_HOME` and `HUGGINGFACE_HUB_CACHE` are unset in the inspected WSL runtimes.
- `/mnt/123pan` is absent from the current WSL namespace; mount output has only drvfs `C:` and system mounts relevant to this check. Historical `/mnt/e` products and `/root/e2e-asr` belong to the recorded remote host and are not present in the inspected local namespace.
- An ignored-inclusive search of this repository outside pytest output, temporary tests, tests and virtual environments found no live audio files. Located `.test-tmp`/pytest files are test-generated audio and cannot satisfy live evidence. Unrelated personal recordings were not used.

A current-build real inference run requires a project recording with known provenance and matching selected store/manifest identity, a compatible native Qwen3-ASR transformers runtime with complete cached ASR and forced-aligner checkpoints, and an existing writable artifact root. Reproducing the specific WebDAV placement also requires the intended mount. CPU on a bounded excerpt can supply new model/publication evidence once those inputs exist, but cannot retroactively claim the complete long-form source passed.

**Disposition:** **#115 is ready to close for its original post-artifact-root / queue-bridge evidence debt**, satisfied by the dated real runs above. Current-build live validation remains unverified in this local environment and is a separate scope. No issue was externally closed by this review.


## Targeted follow-up search: #41 and #61

**#41:** A real later two-arm measurement exists at `.mstar/iterations/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-results.md:10-12` (2026-09-26, remote WSL/GPU). Its term results at **78-96** report `E=7`, equal counts between prompted/unprompted arms, `R=0`, `I=0`; four restored homophone terms occur, while two terms never occur. It explicitly says the small corpus cannot settle list benefit at **175**. Therefore this is later true measurement evidence, but not evidence proving the five original terms' benefit. `bilibili-asr-archive/docs/hotword-measurement-results.md:3` remains PENDING-OPERATOR; **75-89** records empty guarded defaults and why a new guard-admitted measurement differs from the older experiment. Current decision avoids unverified default injection; no new expensive measurement is claimed.

**#61:** Targeted later coverage-provenance reports contain no reproducible 150/1730 rebuild. `.mstar/plans/20260928-ops-docs-and-closeout.md:58-66` explicitly defers headline counts and reproduction; `.mstar/plans/audit-2026-10-02/raw/seat-direction.md:31` reports only pilot-scale live store convergence, not the headline corpus. The 2026-10-06 docs lane qualifies the inherited two numbers (`verification-results/issues-docs-burndown.md:15`) but supplies no copied store or fresh measurement. Host-qualified disclosure is an honest documentation disposition, not new coverage evidence. No later genuine 150/1730 reproduction was found in the targeted sources.

## Final disposition and GitHub close-comment drafts: #41 and #61

Read-only review of the original issue bodies confirms that both acceptance fields say only `defer`; neither requires a new live measurement before the original obligation can be retired. The decisions below address the original product/default and evidence-inheritance risks. They do not turn missing measurements into positive results. Source line references below were verified against the integrated checkout on 2026-10-06.

### #41: superseded default policy

**Ready to close as superseded.** `src/bili_asr/asr.py:160` ships `DEFAULT_HOTWORDS == ()`. None of the old candidates, including 扬弃, is injected by default; the old obligation to establish benefit before retaining five speculative defaults therefore no longer applies to shipped behavior. Source comments at **153-165** and the product README at **270-278** distinguish the historical FunASR 扬弃 measurement from the five unverified terms and explicitly reject using the old result to validate the current Qwen prompt. `docs/hotword-measurement-results.md:75-90` retains the guard-admitted measurement and keep/drop requirement before restoring candidates. Operator configuration and candidate preservation are not proof of benefit.

Exact proposed close comment:

> Closing as superseded by the current hotword governance decision, not as a successful five-term benefit measurement.
>
> The original issue concerned retaining 自在、变易、此在、感性、实存 in the shipped default list without demonstrated benefit, and wording that conflated those terms with the measured 扬弃 result. The shipped default is now `DEFAULT_HOTWORDS == ()` (`src/bili_asr/asr.py:160`), so none of these candidates is injected by default. The source comment and README distinguish the historical FunASR 扬弃 measurement from the other five unverified terms and explicitly state that the old result does not validate the current Qwen prompt (`asr.py:153-165`; `README.md:270-278`).
>
> The five terms' benefit remains unverified. The later 2026-09-26 experiment does not establish that benefit either. Restoring any candidate to the default list requires the guard-admitted measurement and keep/drop decision documented in `docs/hotword-measurement-results.md:75-90`; that work remains pending. Future plans must inherit the empty default and this measurement requirement, not the superseded six-term default or an assumption that all six help.

### #61: documented provenance and inheritance contract

**Ready to close as documented.** The original impact requires coverage inherited by an operator or future plan to name its producing host. `README.md:1520-1532` now discloses that the retained historical record lacks the actual host names, absolute roots, original command output and a fully established denominator selection/unit. It labels both figures historical rather than current and forbids using them to size this checkout's remaining work. It requires new output from the actual archive with host, absolute root, date, selector, numerator and denominator unit before a replacement percentage is published. Missing provenance is disclosed, not reconstructed. Historical plans remain dated records; their old figures are not authority for new planning. Reproduction of the old external archive remains unavailable and is not claimed.

Exact proposed close comment:

> Closing as documented with an explicit coverage provenance contract, not as reproduction of the historical 150/1730 result.
>
> `README.md:1520-1532` now records the 2026-09-25 figures as attributed historical evidence: 150/1730 on another machine and 6/1730 on the reviewed checkout's store. It explicitly discloses that the retained issue lacks the original host names, absolute archive roots and command output, and does not fully establish the denominator's selection/unit. Neither number is presented as current coverage.
>
> These historical figures must not be inherited as current coverage or used to size the remaining work in future plans. A replacement claim requires measurement of the archive actually in use, retaining the command/output plus host, absolute archive root, date, selector, numerator and denominator unit. This documentation change does not copy the external archive or repeat a live corpus measurement.
>
> The original misleading inheritance risk is addressed by that contract. Reproducing the historical external result would still require its original archive and provenance, but that missing material does not justify treating the historical percentage as a current product claim.

Validation for this disposition: original GH bodies and the cited current source/document passages were inspected; no production code changed, new benefit/coverage measurement was performed, or external issue operation was executed by this review.
