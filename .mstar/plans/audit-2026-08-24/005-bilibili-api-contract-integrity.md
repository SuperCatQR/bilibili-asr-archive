# Bilibili API Contract Integrity Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. This audit plan is a candidate for the normal Prepare -> Execute flow; it does not register or execute itself.

**Goal:** Correct the Bilibili API contract handling so non-gone terminal API errors remain resumable and authenticated audio playurl requests use the documented WBI/SESSDATA contract, with focused regression tests.

**Architecture:** Keep `bili_client.py` as the HTTP and risk-classification owner, and keep CLI state transitions in `cli.py`. Preserve the frozen distinction between a permanently unavailable video and a transient or permission/authentication API failure. Define the playurl request contract from the local reference and existing session construction, then pin it with transport-level tests without live requests.

**Tech Stack:** Python 3.12+, `requests`, pytest, existing `Transport` protocol and CLI manifest.

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `ab3cd97`, 2026-08-24
- **State**: TODO

## Finding and current state

- `bili_client.classify_risk()` maps unknown negative API codes to `RISK_GONE` (`bilibili-asr-archive/src/bili_asr/bili_client.py:106-108`). CLI video paths then persist `status='gone'`, which can permanently suppress videos that should be retried or explicitly surfaced as non-gone terminal API errors.
- The local API reference distinguishes `-101` not logged in, `-400` request error, and `-403` permission from gone semantics (`bilibili-asr-archive/references/bilibili-API-collect/docs/misc/risk-and-stream.md:17-27`). The frozen spec reserves gone for `-404` and `-62002`, while `bilibili-asr-archive/tests/test_fetch_meta.py:105-125` currently pins `-101` incorrectly as gone.
- `PLAYURL_URL` is `/x/player/playurl`, and `fetch_playurl_audio()` currently builds the request without WBI signing or forwarding `self._sessdata` (`bilibili-asr-archive/src/bili_asr/bili_client.py:24,471-490`). This conflicts with the local API reference (`risk-and-stream.md:30-35`), `bilibili-asr-archive/PLAN.md:38`, and the README's SESSDATA claim.
- The local reference identifies audio qualities as `30216=64K`, `30232=132K`, `30280=192K`, `30250=Dolby`, and `30251=Hi-Res`; this plan must not substitute 30232 as FLAC.

## Interfaces

Preserve the public client and manifest seams where possible:

- `classify_risk(code: int) -> str` must return gone only for the frozen gone codes and a distinct non-gone classification for unknown/auth/request/permission failures.
- CLI video paths must persist a resumable/non-gone error state or equivalent terminal API-error state for non-gone codes, retain actionable diagnostics, and avoid treating those rows as permanently unavailable.
- `fetch_playurl_audio()` must send the documented WBI-signed `/x/player/playurl` request, including the required stable parameters and `SESSDATA` cookie/session forwarding, while keeping signed URLs transient.
- Keep quality selection explicit and aligned with the local contract; do not call 30232 FLAC.

The exact non-gone state name, retry policy, WBI parameter set, and cookie plumbing must be locked during Prepare against the current manifest state machine and existing session builder.

## In scope

- `bilibili-asr-archive/src/bili_asr/bili_client.py`
- `bilibili-asr-archive/src/bili_asr/cli.py` only where non-gone API errors are persisted or summarized
- `bilibili-asr-archive/tests/test_fetch_meta.py`
- Focused client/CLI tests under `bilibili-asr-archive/tests/` as needed
- `bilibili-asr-archive/README.md` and `.mstar/specs/asr-archive-cli.md` only if the documented contract needs synchronization during execution

## Out of scope

- Multi-part media identity and all-page enumeration, which belong to plan 001.
- Metadata pagination cursor persistence, which belongs to plan 002 and is independent of media-part identity.
- Calling live Bilibili APIs, installing dependencies, changing quality constants outside the documented contract, or invoking model/ffmpeg work.
- Changing 30216/30232/30280/30250/30251 meanings; tests must encode the reference values instead.

## Conventions and exemplars

- Inject transport through `BiliClient(transport=...)` and assert request method, path, query parameters, and cookies using the existing fake transports (`tests/test_fetch_meta.py:20-42` and related client tests).
- Preserve retry and risk-budget behavior in `bili_client.py:225-228,395-399`; correcting classification must not erase partial progress or convert a retryable error into a success.
- Do not persist cookies, signed URLs, or raw credential values in manifests, logs, or artifacts. Tests may assert that a cookie header is forwarded without printing its value.

## Tasks

### Task 1: Correct risk classification and resumable CLI handling

**Files:** Modify `bilibili-asr-archive/src/bili_asr/bili_client.py` and, if required, `cli.py`; test `bilibili-asr-archive/tests/test_fetch_meta.py` and focused CLI tests.

- [ ] Replace the unknown-negative fallback to `RISK_GONE` with a distinct non-gone API-error classification, preserving gone only for `-404` and `-62002`.
- [ ] Update the incorrect `-101` expectation and add coverage for `-400`, `-403`, unknown negative, `-404`, and `-62002`.
- [ ] Define and implement the non-gone terminal API-error path so affected video rows remain resumable and are not permanently suppressed as gone.
- [ ] Assert that mixed success plus a non-gone API error preserves successful rows, records an actionable non-gone state, and returns the documented nonzero result without claiming permanent disappearance.

Run: `python -m pytest bilibili-asr-archive/tests/test_fetch_meta.py bilibili-asr-archive/tests/test_cli_asr.py -q` -> risk and CLI tests pass with no non-gone error row marked `gone`.

### Task 2: Restore the WBI/SESSDATA playurl contract

**Files:** Modify `bilibili-asr-archive/src/bili_asr/bili_client.py`; test focused playurl/client tests; update local documentation only if needed.

- [ ] Define the required WBI-signed query parameters for `/x/player/playurl`, including the current `bvid`/`cid`/quality inputs and timestamp/signature behavior used by the client.
- [ ] Forward `self._sessdata` through the existing session/cookie mechanism without persisting or logging the credential.
- [ ] Add transport assertions that the playurl request path, signed parameters, and cookie forwarding match the local reference contract.
- [ ] Encode the documented quality mapping in tests and select a contract-valid quality; explicitly assert that 30232 is treated as 132K, never as FLAC.

Run: `python -m pytest bilibili-asr-archive/tests -q` -> all tests pass without live HTTP or model downloads.

## STOP conditions

- If the frozen spec and local API reference disagree on which codes are gone, STOP and escalate the contract conflict rather than broadening gone semantics.
- If WBI signing requires a key source or session behavior not present in the repository, STOP and document the missing dependency; do not hardcode secrets or make unsigned fallback the default.
- If preserving resumability requires a manifest migration that conflicts with plan 001's page identity migration, STOP and coordinate the two schemas during Prepare.

## Drift check

Before execution run:

`git diff --stat ab3cd97..HEAD -- bilibili-asr-archive/src/bili_asr/bili_client.py bilibili-asr-archive/src/bili_asr/cli.py bilibili-asr-archive/tests bilibili-asr-archive/README.md .mstar/specs/asr-archive-cli.md`

Compare the cited risk constants, CLI persistence path, playurl request, session construction, and quality mapping with the current checkout. Update the plan only through Prepare clarification if any contract has drifted.

## Done criteria

- [ ] Only `-404` and `-62002` classify as gone; `-101`, `-400`, `-403`, and unknown negative codes use the non-gone API-error path.
- [ ] A non-gone API error is resumable, remains visible in manifest/status output, and does not permanently suppress the video.
- [ ] Tests prove the corrected classification and mixed-success CLI behavior.
- [ ] Playurl requests use the documented WBI signature and forward SESSDATA through the session/cookie mechanism without leaking it.
- [ ] Tests prove the documented quality mapping, including `30232=132K` and no 30232-as-FLAC behavior.
- [ ] `python -m pytest bilibili-asr-archive/tests -q` exits 0.
- [ ] `git status --short` shows only in-scope files changed.

## Prepare -> Execute handoff

During Prepare, lock the non-gone manifest state and retry/resume semantics, the exact WBI signing inputs, and the session cookie boundary against the frozen spec and local reference. During Execute, land classification tests first, then playurl request-contract tests, and finally run the full declared suite without live API calls.
