# Audio pipeline reliability — 2026-10-04

Implemented on `codex/audio-pipeline-reliability`, based on `f537cb5`.

## Addressed issues

| Issue | Result |
| --- | --- |
| [#184](https://github.com/SuperCatQR/bilibili-asr-archive/issues/184) | ASR acquisition runs finish before their connections close. The CLI records complete, partial or failed results, including interruption; pilot and coordinator write-back sources also finish their runs. |
| [#185](https://github.com/SuperCatQR/bilibili-asr-archive/issues/185) | `asr --bvid` stores the requested selector target. Queue selection stays `pending` with a null target; the requested limit is retained. |
| [#186](https://github.com/SuperCatQR/bilibili-asr-archive/issues/186) | Successful transcription retains the engine's detected language in provenance and transcript storage. Multiple languages use `mul`; without detection, the configured language is used, with `und` as the store's final fallback. Failed calls clear previous detection. |
| [#196](https://github.com/SuperCatQR/bilibili-asr-archive/issues/196) | The verified bundle and archived manifest state precede supplementary store write-back. Conversion of cues and write-back exceptions cannot turn a published bundle into an archive failure. |

The GitHub issue state has not been changed.

## Additional audio fixes

- Explicit FLAC input is converted to ALAC in M4A. The output format is supplied explicitly because descriptor paths have no extension. This also avoids attempting to copy a FLAC codec into the M4A muxer. Child stdin is disabled and ffmpeg error payloads remain out of diagnostics.
- The downloader tries primary and unique backup CDN addresses, supporting both API field spellings and protocol-relative addresses. A failed prefix is truncated before retrying; an empty response can fall through to a backup.
- Empty downloads and conversions are rejected before publication. Failed operations remove their owned staging files and leave the row retryable.
- The coordinator reuses available audio before checking the download budget. Online processing downloads again when an `audio_ok` file has disappeared; offline processing keeps its missing-input behavior.

## Verification

Environment: Ubuntu 24.04 under WSL, Python 3.12.3, system ffmpeg, fresh isolated development environment. No live Bilibili requests or model downloads were used. Inference uses offline model doubles; the codecs, audio reads, filesystem publication, manifest writes and SQLite writes are real.

The final focused run selected 322 cases across audio, ASR, queue-source, coordinator, pilot, retention, reclaim, artifact-root writes and CLI help:

- **321 passed, 1 failed.** The failure is the existing `test_cli_help.py::test_module_coverage_formats_and_diagnostic_exit`, which assumes a manifest snapshot exists after a journal-only write. It also fails on the unchanged base.
- **All 19 new regression cases passed**, including real 16-bit and 24-bit FLAC → M4A → decoded-sample equality → ASR, partial/empty download fallback, conversion cleanup, successful/failed/interrupted run close-out, scope/limit storage, language reset, multilingual detection, archive preservation, and local-audio recovery.
- All five isolated installed-entrypoint cases passed after providing the Linux `uv` executable and its cached build backend. This resolves the five environment setup errors in the earlier full run.
- `git diff --check` passed.

The whole existing suite was run both against the change and a separate unchanged checkout of `f537cb5`:

| Run | Passed | Failed | Skipped | Setup errors |
| --- | ---: | ---: | ---: | ---: |
| Unchanged base | 2066 | 32 | 51 | 0 |
| Changed tree, before the last four regression cases were added | 2076 | 32 | 51 | 5 |

Comparison of the full JUnit failure identities found **zero added or removed failures**. The five setup errors were caused by the first invocation lacking the installed-entrypoint tool override and passed in the final focused run. The full suite therefore remains red because of baseline problems; this result is not a claim that the whole suite is green.

The 32 baseline failures group as follows:

| Module | Count | Cause family |
| --- | ---: | --- |
| `test_cli_artifact_root` | 3 | Snapshot/authority expectations |
| `test_cli_derive_manifest` | 4 | Snapshot assumptions after journal writes |
| `test_cli_help` | 1 | Snapshot assumption in coverage fixture |
| `test_cli_publish_transcripts` | 4 | Snapshot assumptions after journal writes |
| `test_harness_state` | 10 | `mstar` executable absent in this Linux environment |
| `test_long_live` | 5 | Store-route scheduler/long-duration expectations |
| `test_mixed_outcome_contract` | 3 | Snapshot and store-route expectations |
| `test_raw_characters` | 1 | An old test double rejects `bust_cache` |
| `test_scheduler` | 1 | Bounded store-queue scope expectation |

Local, gitignored evidence is retained under `.test-tmp/`: `audio-pipeline-full.xml`, `audio-pipeline-baseline.xml`, `audio-pipeline-focused.xml`, `audio-pipeline-regressions.xml`, and `audio-pipeline-comparison.json`. The final standalone regression run also passed all 19 cases after independently injecting cue-conversion and store-writer failures.

Real Qwen checkpoint inference and GPU execution were not exercised. Existing transcripts are not backfilled with language, and historic running acquisition rows are not rewritten. A supplementary store write can still fail independently of successful file publication; this batch preserves the archive rather than repairing those historical gaps.

## Reproduce the focused run

From the product directory, using a Python 3.12 environment installed with `.[dev]`, ffmpeg on PATH and a working Linux `uv` for the isolated installation tests:

```sh
BILI_ASR_UV=/path/to/uv python -m pytest -q --tb=short \
  tests/test_audio_pipeline_reliability.py tests/test_audio.py \
  tests/test_asr_qwen.py tests/test_cli_asr.py tests/test_cli_queue_source.py \
  tests/test_coordinator.py tests/test_cli_pilot.py tests/test_storage_queue_writes.py \
  tests/test_audio_budget.py tests/test_audio_retention_policy.py \
  tests/test_artifact_root_writes.py tests/test_audio_reclaim.py tests/test_cli_help.py
```
