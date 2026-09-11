---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260824-api-contract-integrity"
verdict: "Approve"
generated_at: "2026-08-24T15:32:00+08:00"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: openai/gpt-5.6-sol
- Review Perspective: performance and reliability risk
- Report Timestamp: 2026-08-24T14:52:00+08:00

## Scope
- plan_id: `20260824-api-contract-integrity`
- Review range / Diff basis: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..d142c33`
- Working branch (verified): `plan/005-bilibili-api-contract-integrity`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive`
- Files reviewed: 6 changed files plus current `manifest.py`, plan, spec, local API reference, and SDD progress evidence
- Commit range: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..d142c337e6f44721443ad88d3968deba84249372` (the assigned abbreviated tip resolves to the verified full HEAD)
- Deep review: triggered (S1: 361 changed lines, S6: HTTP client, CLI/manifest orchestration, audio pipeline, and fixtures)
- Lenses applied: Performance Lens, Reliability Lens, Enforcement-Path Lens, Ownership / Derived-State Lens, Testing Lens, Input Validation Lens
- Analysis methods: supplied branch diff, git diff/stat/log/show, read, grep, manual call-path tracing; no test/build/install/lint/live requests were run

## Findings
### 🔴 Critical
- None.

### 🟡 Warning
- [F-001] The signed playurl path does not perform the required one-time WBI key re-derivation after a signature rejection, so a rotated key can leave every resumed audio attempt failing with the same stale signature. `fetch_playurl_audio()` obtains keys once and sends one signed request (`bili_client.py:492-500`); `_request_with_cookies()` classifies every `-403` as `APIResponseError` immediately (`bili_client.py:319-344`), and neither path fetches nav again or rebuilds `w_rid`. The CLI correctly preserves `needs_audio` and records `last_api_error_code`, but a later process repeats the same sequence and can fail indefinitely until external key state changes. Implement a playurl-specific bounded recovery: on its first `-403`, call `_wbi_keys()` again, re-sign with the new keys/current timestamp, retry exactly once, then raise `APIResponseError(-403)` if it still fails. Keep generic unsigned endpoints on the direct `RISK_API_ERROR` path and add a fixture proving two nav responses, two distinct signed playurl calls, and no backoff-budget loop.
  - Verification: diff/read anchors `bilibili-asr-archive/src/bili_asr/bili_client.py:83-104,294-358,476-502`; spec anchor `.mstar/specs/asr-archive-cli.md:82,90`; grep found no stale-key/rotation retry test or production branch.
  - Expected vs observed: expected a single key refresh and re-signed retry for WBI signature rejection, bounded independently from normal risk retries; observed an immediate resumable error with no key invalidation or re-signing path.

### 🟢 Suggestion
- [F-002] Tighten shared audio fixtures so production-route regressions cannot hide behind substring matching. Most audio and CLI tests register a broad `"playurl"` route (`tests/test_audio.py:166-306,338-448`), and `RouterTransport` accepts any fragment contained in the URL (`tests/test_audio.py:38-50`). Those tests would still pass if production regressed to `/x/player/playurl`; only the focused contract test uses the exact `"/x/player/wbi/playurl"` route. Replace the shared route key with `"/x/player/wbi/playurl"` (or make the router exact for API paths), keeping the focused URL assertion.
  - Verification: read/grep anchors `bilibili-asr-archive/tests/test_audio.py:38-50,133-163,166-306,338-448`.
  - Expected vs observed: expected all production-path audio fixtures to reject the obsolete plain endpoint; observed most fixtures accept either endpoint because both contain `playurl`.

### ⚪ Unconfirmed
- [F-003] Runtime acceptance remains for L4/QA. The SDD ledger cites `109 passed` and four focused Task 2 tests on PC WSL, but this L3 seat did not execute commands. QA should run the acceptance-only targeted suite for the final review range, including the new stale-key retry regression after F-001 is fixed, direct unknown `probe-subs --bvid` persistence (the ledger identifies this missing dedicated test), mixed subtitle/audio batches, chunked stream failure cleanup, explicit FLAC URL and MIME cases, and exact WBI playurl route/cookie assertions.
  - Channel gap: runtime execution belongs to L4 QA; current evidence is an L1/L2 ledger summary rather than output produced by this reviewer.
  - Verification: `.mstar/sdd/20260824-api-contract-integrity/progress.md:9-14`; plan acceptance commands at `.mstar/plans/20260824-api-contract-integrity.md:53,73,97-106`.
  - Expected vs observed: expected final-range runtime acceptance after QC fixes; observed prior reported evidence plus a documented direct-probe coverage gap.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Reliability Lens / Enforcement-Path Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/bili_client.py:83-104,294-358,476-502`; `.mstar/specs/asr-archive-cli.md:82,90`
- Confidence: High
- Note: the retry absence is statically complete across all `-403`, `_wbi_keys`, and playurl call sites.

- Finding ID: F-002
- Source Type: deep-lens: Testing Lens / Real-Entry-Path reasoning
- Source Reference: `bilibili-asr-archive/tests/test_audio.py:38-50,133-163,166-306,338-448`
- Confidence: High
- Note: substring routing demonstrably accepts both `/x/player/playurl` and `/x/player/wbi/playurl`.

- Finding ID: F-003
- Source Type: assignment-ci-note
- Source Reference: `.mstar/sdd/20260824-api-contract-integrity/progress.md:9-14`; `.mstar/plans/20260824-api-contract-integrity.md:53,73,97-106`
- Confidence: High
- Note: this is an explicit L4 evidence handoff, not a claim that the cited runs failed.

## Reliability Checks Without Findings
- Non-gone API errors are separated from `GoneResponse`; the CLI preserves existing status, records numeric `last_api_error_code`, and keeps mixed batches bounded by the finite `todo` list.
- Retryable HTTP/network paths retain the configured finite `max_attempts` budget and one buvid refresh; generic `-403` no longer consumes that budget.
- `fetch-meta` retains already fetched pages on API errors and leaves records resumable.
- Production media transfer remains streaming (`iter_content` chunks), writes to `.part`, and atomically replaces the final file only after success; failure cleanup removes the partial file.
- FLAC detection no longer derives from quality ID 30232 and uses URL/MIME evidence without buffering the media body.

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 1 |
| ⚪ Unconfirmed | 1 |

**Verdict**: Request Changes

## Revalidation

- Re-review scope: targeted L3 reliability re-review of final range `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2` on `plan/005-bilibili-api-contract-integrity`, using the final `review/branch.diff`, source reads, grep, and diff metadata only. No tests, builds, installs, lint, or live requests were run.
- F-001: Resolved. `fetch_playurl_audio()` catches only the first `APIResponseError` whose code is exactly `-403`; it refreshes WBI keys through `_wbi_keys()`, re-signs the same query with the refreshed keys and a new timestamp, then retries signed playurl once. The second request is outside the catch block, so a second `-403` propagates immediately with no third request and no generic risk-backoff loop. Non-`-403` API errors propagate without this recovery. Static anchors: `bilibili-asr-archive/src/bili_asr/bili_client.py:488-520`; regression fixtures: `bilibili-asr-archive/tests/test_audio.py:517-578`.
- F-002: Resolved. Shared audio fixtures register the exact `"/x/player/wbi/playurl"` path fragment, preventing obsolete `/x/player/playurl` production routes from matching. The production constant is also the exact WBI endpoint. Static anchors: `bilibili-asr-archive/tests/test_audio.py:137-230,247-398,435-570`; `bilibili-asr-archive/src/bili_asr/bili_client.py:24`.
- Reliability result: No new Critical or Warning finding in the targeted fixes or final review range. The signed playurl recovery is explicitly bounded to one refresh/re-sign/retry sequence, and the dedicated fixture verifies two playurl calls with two nav responses and no further retry after the second `-403`.
- Runtime evidence: belongs to L4 QA. This remains a static L3 review and does not claim runtime execution; QA should run the acceptance suite for the final range, including the signed-key rotation and second-`-403` stop cases.

**Final Verdict**: Approve
