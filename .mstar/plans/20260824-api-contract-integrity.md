# Bilibili API Contract Integrity

> Candidate source: audit `BUG-04` (`.mstar/plans/audit-2026-08-24/README.md`).
> This locked implementation plan is for the normal Prepare -> Execute flow.

**Goal:** Correct Bilibili API error classification and authenticated audio playurl requests without changing the manifest state machine or leaking credentials.

**Architecture:** `bili_client.py` remains the only HTTP owner and owns risk classification, WBI signing, and cookie forwarding. Non-gone API failures remain attached to the existing resumable manifest row through `last_api_error_code`; only the existing gone codes become `gone`. Audio quality selection remains in `audio.py`, with container detection based on response metadata rather than codec ID.

**Tech Stack:** Python 3.12+, `requests`, pytest, existing injectable `Transport` and JSONL `ManifestStore`.

**Execution:** mstar-sdd

## Global Constraints

- Base install remains Python 3.12+ with the existing `requests` dependency; do not add dependencies.
- `RISK_GONE` is reserved for HTTP 404, API `-404`, and API `-62002` only.
- API `-101`, `-400`, `-403`, and unknown negative codes must not become `gone`; they remain resumable and preserve an actionable numeric `last_api_error_code`. If a direct `probe-subs --bvid` or `download-audio --bvid` request has no existing row, create the minimal valid row with the operation's resumable starting status.
- No SESSDATA value, cookie header, signed URL, raw exception traceback, or model output may be persisted or printed.
- Audio playurl uses `/x/player/wbi/playurl`, WBI-signed query parameters, and the existing `Transport.get_json(..., cookies=...)` channel. Signed CDN URLs remain transient.
- Per the repository reference `references/bilibili-API-collect/risk-and-stream.md:30-35`, quality IDs are 30216=64K, 30232=132K, 30280=192K, 30250=Dolby, 30251=Hi-Res. ID 30232 must not be treated as FLAC.
- Preserve existing retry budgets, buvid refresh behavior, single HTTP-owner layering, exit 2 for exhausted risk budget, and exit 1 for mixed per-video failures.

## Locked decisions

- New names: `RISK_API_ERROR`, `APIResponseError`, and manifest field `last_api_error_code`.
- `APIResponseError` is raised for non-gone, non-retryable API codes. CLI catches it separately, leaves an existing status unchanged, or creates a minimal resumable row for a direct unknown-BVID operation; it stores the integer code, prints a redacted summary, and continues the batch.
- `-403` is classified directly as `RISK_API_ERROR` for generic request helpers; the signed playurl operation adds its own bounded recovery: on the first playurl `-403`, re-fetch WBI keys, re-sign with the current timestamp, retry once, then raise `APIResponseError(-403)`.
- `last_api_error_code` is an active diagnostic: successful subtitle/audio manifest transitions remove it, while failed resumable rows retain it.
- User-facing exception diagnostics are redacted to fixed safe types/codes; raw transport exception messages never reach output or manifest data.
- `fetch-meta` persists already fetched pages and exits 2 for an API response that stops enumeration, but it does not mark any record gone unless the response is a frozen gone code.
- `fetch_playurl_audio()` signs `bvid`, `cid`, `fnval=16`, and `qn=0` with the existing `sign_wbi` helper and sends `SESSDATA` when configured.
- FLAC handling is selected only by a `.flac` URL or explicit `mimeType` containing `flac`; codec ID 30232 alone never triggers FLAC handling.

## Task 1: Risk classification and resumable CLI handling

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/bili_client.py`
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Modify: `bilibili-asr-archive/tests/test_fetch_meta.py`
- Modify: `bilibili-asr-archive/tests/test_subtitles.py` if API-error row coverage belongs there
- Modify: `bilibili-asr-archive/tests/test_audio.py` if API-error row coverage belongs there

**Interfaces:**
- Preserve `classify_risk(status: int, body: dict[str, Any] | None) -> str`.
- Add `RISK_API_ERROR` and `APIResponseError(code: int | str)`.
- Preserve all existing public `BiliClient` methods and `ManifestStore` methods.

- [x] Add failing classification tests for `-101`, `-400`, `-403`, and an unknown negative code; retain gone assertions for HTTP 404, `-404`, and `-62002`.
- [x] Add a failing CLI test proving a non-gone API error does not write `status=gone`, preserves the row's previous status, records `last_api_error_code`, and returns 1 when mixed with a successful item.
- [x] Add a failing direct-`--bvid` test proving an unknown BVID creates a minimal resumable row with the operation's starting status and numeric `last_api_error_code`.
- [x] Implement the new classification and exception path in both `_request` and `_request_with_cookies`.
- [x] Catch `APIResponseError` in fetch, subtitle, and audio CLI loops; keep rows resumable and correct the mixed-failure return conditions without echoing secrets.
- [x] Add retry-after-error coverage proving successful subtitle/audio transitions clear `last_api_error_code`.
- [x] Add CLI transport-exception redaction coverage for sentinel cookie and signed-URL text.

Run: `python -m pytest bilibili-asr-archive/tests/test_fetch_meta.py bilibili-asr-archive/tests/test_subtitles.py bilibili-asr-archive/tests/test_audio.py -q` -> exit 0; final PC WSL evidence: `116 passed`; no non-gone row is marked `gone`.

## Task 2: WBI/SESSDATA playurl contract and quality semantics

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/bili_client.py`
- Modify: `bilibili-asr-archive/src/bili_asr/audio.py`
- Modify: `bilibili-asr-archive/tests/test_audio.py`
- Modify: `bilibili-asr-archive/tests/test_subtitles.py` only if shared WBI/cookie assertions need a focused extension

**Interfaces:**
- Preserve `BiliClient.fetch_playurl_audio(bvid: str) -> list[dict[str, Any]]`.
- Preserve `audio.download_audio(...) -> str`.
- Preserve `sign_wbi(params, img_key, sub_key, wts=None) -> dict[str, Any]`.

- [x] Add a failing transport test asserting `/x/player/wbi/playurl`, signed `wts`/`w_rid`, required bvid/cid/fnval/qn parameters, and SESSDATA cookie forwarding.
- [x] Add failing quality tests proving 30232 means 132K and does not trigger FLAC fallback/remux by ID; use explicit FLAC URL/MIME for any FLAC fallback test.
- [x] Implement the WBI-signed playurl request using `_wbi_keys()` and the configured cookie channel.
- [x] Correct audio comments and container detection to use URL/MIME evidence rather than the 30232 ID.
- [x] Add bounded playurl `-403` key re-derivation/re-sign retry coverage.
- [x] Tighten shared audio fixtures to require the exact WBI playurl path.
- [x] Add direct unknown-probe, MIME-only FLAC, and explicit CDN cookie-isolation coverage.

Run: `python -m pytest bilibili-asr-archive/tests -q` -> exit 0 with no live HTTP or model downloads; final PC WSL evidence: `116 passed` plus six focused QC tests.

## Out of Scope

- Multi-part media identity and all-page enumeration (audit plan 001).
- Metadata pagination cursor persistence (audit plan 002).
- Pilot execution (audit plan 003), full entrypoint integration coverage (audit plan 004), search, diarization, model changes, dependency locking, and CI.
- Live Bilibili requests, credential acquisition, ffmpeg execution, or model downloads.

## STOP Conditions

- If the frozen spec and local API reference disagree on gone codes, stop before changing classification.
- If WBI keys cannot be obtained from the existing `nav` response seam, stop instead of adding hardcoded keys or unsigned fallback.
- If preserving old manifest rows requires a schema migration beyond an additive `last_api_error_code` field, stop and revise this plan before implementation.
- If an existing test contradicts the locked quality mapping, update the test only after confirming the local reference and record the contradiction in the implementation report.

## Drift Check

Before execution run:

`git diff --stat ab3cd97..HEAD -- bilibili-asr-archive/src/bili_asr/bili_client.py bilibili-asr-archive/src/bili_asr/cli.py bilibili-asr-archive/src/bili_asr/audio.py bilibili-asr-archive/tests bilibili-asr-archive/README.md .mstar/specs/asr-archive-cli.md`

If any listed file changed, compare the current risk constants, exception paths, playurl URL, WBI helper, cookie plumbing, and audio quality comments with this plan before editing.

## Done Criteria

- [x] Only frozen gone codes classify as `RISK_GONE`; auth/request/unknown codes use `RISK_API_ERROR`.
- [x] Non-gone API errors remain resumable, retain the prior status, record `last_api_error_code`, and never write `gone`.
- [x] Mixed-success subtitle/audio batches return 1 when any per-video item fails.
- [x] Playurl requests use the WBI endpoint, signature, and SESSDATA cookie channel without leaking values.
- [x] Tests encode 30232=132K and prove it is not treated as FLAC.
- [x] `python -m pytest bilibili-asr-archive/tests -q` exits 0.
- [x] `git diff --check` exits 0.
- [x] `git status --short` shows only in-scope implementation/test files plus this plan artifact.

## Review Gate Summary

- Decision: `Approve` after targeted zero-residual re-review.
- Review range / Diff basis: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2`.
- Review bundle: `.mstar/sdd/20260824-api-contract-integrity/review/`.
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`, and `qc-consolidated.md`.
- Blocking result: initial Warnings were fixed in `62d91f2`; all three targeted seats finalized `Approve`.
- Residual findings: none; zero-residual cleanup opened no R#.

## QA Gate Summary

- Decision: `Approve`; QA gate: `mandatory`; QA mode: `full`.
- Fresh L4 PC WSL evidence at final commit `62d91f2433da1f0d052e2a8e40231338e98fa1c1`: full suite `116 passed in 0.28s`; focused final-range acceptance set `20 passed in 0.08s`; clean branch and `git diff --check` pass.
- Acceptance verified: direct unknown probe persistence, transport/generic redaction, successful diagnostic clearing, bounded WBI retry with no third playurl request, MIME-only FLAC and non-FLAC 30232, API/CDN cookie isolation, mixed-batch exit 1, non-gone resumability, and atomic `.part` cleanup.
- QA report: `.mstar/sdd/20260824-api-contract-integrity/review/qa.md`; residual findings: none; recommendation to PM: transition the plan from `InReview` to `Done`.

## Handoff

Implement Task 1 with a fresh SDD implementer and task review, then Task 2 with a fresh implementer and task review. After both tasks, run plan-level QC and QA before merging the feature branch into the project integration branch. No Pull Request is to be created.
