---
report_kind: qa
role: qa-engineer
plan_id: "20260824-api-contract-integrity"
qa_gate: mandatory
qa_mode: full
verdict: "Approve"
generated_at: "2026-08-24T15:45:00+08:00"
review_cwd: "/root/workspace/bilibili-asr-archive"
working_branch: "plan/005-bilibili-api-contract-integrity"
review_range: "ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2"
final_commit: "62d91f2433da1f0d052e2a8e40231338e98fa1c1"
execution_host: "PC WSL via chosenecho@192.168.1.21"
findings_cleanup: zero-residual
---

# QA Acceptance Report

## Metadata Alignment

- Control checkout: `/root/workspace/bilibili-asr-archive`.
- PC WSL checkout: `/root/workspace/bilibili-asr-archive` with package root `/root/workspace/bilibili-asr-archive/bilibili-asr-archive`.
- Both checkouts reported branch `plan/005-bilibili-api-contract-integrity`, HEAD `62d91f2433da1f0d052e2a8e40231338e98fa1c1`, and clean `git status --short --branch` output containing only the branch header.
- Both final-range diffs contain the same seven files: `src/bili_asr/audio.py`, `bili_client.py`, `cli.py`, `subtitles.py`, and `tests/test_audio.py`, `test_fetch_meta.py`, `test_subtitles.py`.
- Diff basis matches the consolidated QC package: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2`.
- QC input: `qc-consolidated.md` final verdict `Approve`; final finding counts Critical 0, Warning 0, Suggestion 0, Unconfirmed 0; no residual R#.

## Commands And Exact PC WSL Outputs

### Metadata and final source/test diff

Command:

```bash
ssh chosenecho@192.168.1.21 "wsl -d Ubuntu --cd /root/workspace/bilibili-asr-archive -- bash -c \"pwd; git branch --show-current; git rev-parse HEAD; git status --short --branch; git diff --stat ab3cd97ca7e166fc6dea65b3785beaef7de597aa..HEAD; git diff --name-status ab3cd97ca7e166fc6dea65b3785beaef7de597aa..HEAD\""
```

Output:

```text
/root/workspace/bilibili-asr-archive
plan/005-bilibili-api-contract-integrity
62d91f2433da1f0d052e2a8e40231338e98fa1c1
## plan/005-bilibili-api-contract-integrity
 bilibili-asr-archive/src/bili_asr/audio.py       |  22 +-
 bilibili-asr-archive/src/bili_asr/bili_client.py |  90 ++++---
 bilibili-asr-archive/src/bili_asr/cli.py         |  86 +++++--
 bilibili-asr-archive/src/bili_asr/subtitles.py   |   2 +
 bilibili-asr-archive/tests/test_audio.py         | 287 +++++++++++++++++++++--
 bilibili-asr-archive/tests/test_fetch_meta.py    |  97 +++++++-
 bilibili-asr-archive/tests/test_subtitles.py     |  98 +++++++-
 7 files changed, 593 insertions(+), 89 deletions(-)
M	bilibili-asr-archive/src/bili_asr/audio.py
M	bilibili-asr-archive/src/bili_asr/bili_client.py
M	bilibili-asr-archive/src/bili_asr/cli.py
M	bilibili-asr-archive/src/bili_asr/subtitles.py
M	bilibili-asr-archive/tests/test_audio.py
M	bilibili-asr-archive/tests/test_fetch_meta.py
M	bilibili-asr-archive/tests/test_subtitles.py
```

### Test discovery

Command:

```bash
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest --collect-only -q
```

Output summary after collecting the exact test identifiers used below:

```text
116 tests collected in 0.02s
```

### Full suite

Command:

```bash
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest -q
```

Output:

```text
........................................................................ [ 62%]
............................................                             [100%]
116 passed in 0.28s
```

### Focused final-range acceptance set

Command:

```bash
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest -q tests/test_fetch_meta.py::test_cli_transport_error_redacts_exception_message tests/test_fetch_meta.py::test_cli_unexpected_error_exit_1_no_traceback tests/test_subtitles.py::test_cli_probe_subs_unknown_bvid_api_error_creates_minimal_row tests/test_subtitles.py::test_cli_probe_subs_transport_error_redacts_exception_message tests/test_subtitles.py::test_harvest_empty_marks_needs_audio tests/test_subtitles.py::test_harvest_downloads_shortlived_url_same_run tests/test_subtitles.py::test_cli_harvest_api_error_preserves_status_and_mixed_batch_fails tests/test_audio.py::test_fetch_playurl_audio_retries_once_with_rotated_wbi_keys tests/test_audio.py::test_fetch_playurl_audio_second_minus_403_is_not_retried tests/test_audio.py::test_download_audio_prefers_30216_and_sends_referer_ua tests/test_audio.py::test_download_audio_30232_m4s_does_not_remux tests/test_audio.py::test_download_audio_mime_only_flac_remuxes tests/test_audio.py::test_download_audio_updates_manifest_audio_ok tests/test_audio.py::test_cli_download_audio_api_error_preserves_status_and_mixed_batch_fails tests/test_audio.py::test_cli_download_audio_transport_error_redacts_exception_message tests/test_audio.py::test_download_audio_atomic_no_partial_on_failure tests/test_fetch_meta.py::test_request_raises_api_response_error_for_non_gone_code tests/test_fetch_meta.py::test_minus_403_directly_raises_api_response_error
```

Output:

```text
....................                                                     [100%]
20 passed in 0.08s
```

### Required clean-status and whitespace gate

Command:

```bash
cd /root/workspace/bilibili-asr-archive && git status --short --branch && git diff --check ab3cd97ca7e166fc6dea65b3785beaef7de597aa..HEAD
```

Output:

```text
## plan/005-bilibili-api-contract-integrity
```

No additional output means `git diff --check` passed.

## Acceptance Mapping

| Plan criterion / acceptance item | Fresh PC WSL evidence | Result |
|---|---|---|
| Frozen gone codes only; `-101`, `-400`, `-403`, unknown negative remain API errors | Full suite plus focused parametrized `test_request_raises_api_response_error_for_non_gone_code` and `test_minus_403_directly_raises_api_response_error`; classification matrix covers `-101/-400/-403/-99999` and gone `404/-404/-62002` | Pass |
| Non-gone errors preserve resumable status, write numeric `last_api_error_code`, never `gone` | Focused mixed subtitle and audio tests assert prior statuses `meta_ok`/`needs_audio`, numeric `-400`/`-101`, successful sibling completion, and no row with `status=gone`; direct probe asserts numeric `-99999` | Pass |
| Direct unknown `probe-subs --bvid` creates minimal valid row | `test_cli_probe_subs_unknown_bvid_api_error_creates_minimal_row`: exit 1 and exact `{bvid, status: meta_ok, last_api_error_code: -99999}` | Pass |
| Successful subtitle/audio recovery clears diagnostic | `test_harvest_empty_marks_needs_audio`, `test_harvest_downloads_shortlived_url_same_run`, and `test_download_audio_updates_manifest_audio_ok` assert `last_api_error_code` removed after `needs_audio`, `subtitle_done`, and `audio_ok` | Pass |
| Transport/generic error diagnostics are redacted and traceback-free | Fetch, probe, and audio sentinel tests assert SESSDATA fragments, signed URL/token text, and `SIGNED` are absent; unexpected fetch test asserts no `Traceback`; manifests are absent or free of sentinels | Pass |
| Playurl uses exact WBI endpoint/signature and API SESSDATA channel | Full suite includes `test_fetch_playurl_audio_uses_signed_wbi_endpoint_and_cookie`; focused CDN isolation test asserts signed API call carries SESSDATA while stream call has empty cookies | Pass |
| Rotated WBI key retries once; repeated `-403` stops after second call | Focused rotated-key test asserts two nav calls, two playurl calls, changed `wts/w_rid`; second-403 test asserts propagated `APIResponseError(-403)` and exactly two playurl calls, proving no third request | Pass |
| MIME-only FLAC and non-FLAC 30232 semantics | Focused MIME-only test asserts FLAC remux from `mimeType: audio/flac`; 30232 `.m4s` test asserts no remux by quality ID alone | Pass |
| Mixed subtitle/audio per-video failures return exit 1 | Focused mixed tests each assert one failure plus one success and command return 1 | Pass |
| Chunked stream failure removes partial/final output | `test_download_audio_atomic_no_partial_on_failure` passes; implementation finalizer removes `<out>.part`, and no final output exists after injected stream failure | Pass |
| No signed URL or SESSDATA persisted | Subtitle recovery test asserts short-lived URL absent from manifest; audio success test asserts no stream host/URL; redaction tests assert sentinel cookie/URL absent from output and manifest | Pass |
| Full repository suite and whitespace gate | `116 passed in 0.28s`; clean PC branch; `git diff --check` produced no output | Pass |

## Security And State Assertions

- No tested error path emitted or persisted a SESSDATA value, signed URL, raw transport exception message, or traceback.
- No manifest row was marked `gone` for `-101`, `-400`, `-403`, or unknown negative codes. The classification matrix reserves `gone` for HTTP 404, API `-404`, and API `-62002`.
- The bounded WBI recovery cannot make a third playurl request: the repeated-403 regression observes exactly two calls before `APIResponseError(-403)` escapes.
- CDN stream calls receive no SESSDATA cookie; authenticated API playurl calls do.

## Findings

- No Critical, Warning, Suggestion, or Unconfirmed finding remains.
- Zero-residual gate satisfied; no R# creation or closure action is required.

## Not Tested Boundaries

- No live Bilibili HTTP request or credential acquisition.
- No real SESSDATA value.
- No model download or ASR inference.
- No real ffmpeg execution; FLAC branches monkeypatch `_run_ffmpeg` to verify dispatch semantics only.
- No real CDN media transfer; all API and stream transports are injectable fakes.
- These exclusions are required by the plan and assignment, not evidence gaps.

## Recommendation

Acceptance evidence supports a PM transition recommendation from `InReview` to `Done`. QA did not change workflow status, source, tests, spec, branch, commits, status JSON, or create/push a PR.

Verdict: Approve
