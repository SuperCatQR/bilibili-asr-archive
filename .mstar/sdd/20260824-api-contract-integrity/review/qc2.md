---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260824-api-contract-integrity"
verdict: "Approve"
generated_at: "2026-08-24T15:30:00Z"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: openai/gpt-5.6-sol
- Review Perspective: Security and correctness risk
- Report Timestamp: 2026-08-24T00:00:00Z

## Scope
- plan_id: 20260824-api-contract-integrity
- Review range / Diff basis: ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2
- Working branch (verified): plan/005-bilibili-api-contract-integrity
- Review cwd (verified): /root/workspace/bilibili-asr-archive
- Files reviewed: 6 changed files plus related current source, manifest implementation, plan, spec, local API reference, and SDD evidence
- Commit range: ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2
- Analysis methods: review-package, git-diff, git-log, read, grep; no tests/builds/lint/live requests
- Deep review: triggered (S1: 314 additions / 47 deletions, S6: HTTP client + CLI + audio + tests)
- Lenses applied: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens, Input Validation Lens, Testing Lens
- External L1 evidence only: SDD ledger records PC WSL `107 passed`, then `109 passed` plus four focused Task 2 tests; not re-executed by QC

## Findings
### Critical
- None.

### Warning
- [F-001] CLI error reporting can still print raw exception payloads, including credentials or short-lived signed URLs, which contradicts the plan's absolute no-leak constraint. -> Replace exception interpolation on user-facing paths with fixed redacted summaries and safe scalar codes/types; ensure `RiskBudgetExhausted.last_code` never carries an exception object into output. Add real CLI-entry tests using transport exceptions whose messages contain a sentinel SESSDATA value and a signed URL, and assert neither appears in stdout/stderr or the manifest.
  - Verification: `bilibili-asr-archive/src/bili_asr/bili_client.py:237-243,263-292,313-345` stores transport exceptions in `RiskBudgetExhausted.last_code`; `bilibili-asr-archive/src/bili_asr/cli.py:173-183,212-216,248-264,296-318,366-394` interpolates `last_code` or arbitrary `exc` into stderr. The only new leak assertions (`tests/test_audio.py:380-405,408-437`; `tests/test_subtitles.py:340-366`) use numeric API errors, so they cannot exercise this channel.
  - Expected vs observed: Expected no SESSDATA value, signed URL, or raw credential is ever printed, regardless of the originating exception. Observed an injected/real transport exception message is propagated as an object and formatted directly into CLI output; a message such as `timeout fetching https://...?...token=...` or `Cookie: SESSDATA=...` would be disclosed.

### Suggestion
- None.

### Unconfirmed
- [U-001] Direct unknown-BVID `probe-subs --bvid` API-error persistence is implemented but has no dedicated real-entry-path test.
  - Channel gap: `cli.py:252-257` creates the `meta_ok` row through `_record_api_error`, but `tests/test_subtitles.py` has no API-error case for `probe-subs`; the SDD ledger explicitly records this gap. Needs L4/QA verification of exit 1, minimal valid row, preserved existing status, numeric code, and redacted output.
- [U-002] Explicit MIME-based FLAC detection is not covered by the changed tests.
  - Channel gap: `audio.py:109-111` accepts `mimeType`/`mime_type` containing `flac`, but `tests/test_audio.py:239-292` covers only `.m4s` and `.flac` URL suffixes. Needs L4/QA or implementer coverage for an extensionless/m4s URL with explicit FLAC MIME and for a non-FLAC MIME containing ID 30232.
- [U-003] CDN cookie isolation is visible in source but not asserted by tests.
  - Channel gap: `bili_client.py:513-517` passes `cookies=None`, while `tests/test_audio.py:166-186` asserts URL and headers but not `stream_calls[0]["cookies"] == {}`. Needs L4/QA or implementer assertion that SESSDATA reaches pagelist/playurl as a cookie and is absent from the CDN call.

## Contract Cross-Check
- Gone classification: `classify_risk` reserves gone for HTTP 404, API -404, and API -62002; other non-retryable responses raise `APIResponseError`.
- Resumable rows: `_record_api_error` preserves existing status and creates direct-operation rows with valid `meta_ok`/`needs_audio` starting states for numeric API codes.
- WBI playurl: `fetch_playurl_audio` signs exactly `bvid`, `cid`, `fnval=16`, and `qn=0`, then adds `wts`/`w_rid`; SESSDATA is not a query parameter.
- 30232 semantics: FLAC selection is based on URL suffix or explicit MIME metadata, not ID 30232.
- Atomicity: audio remains staged through `.part` and promoted with `os.replace`; manifest remains staged through `.tmp` and promoted with `os.replace`. No regression is introduced by this diff.
- Signed URL persistence: audio manifests store only `audio_path`; subtitle manifests store language/path metadata, not the signed URL.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Security Lens / Error Handling Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/bili_client.py:237-243,263-292,313-345`; `bilibili-asr-archive/src/bili_asr/cli.py:173-183,212-216,248-264,296-318,366-394`; leak-test gaps in changed tests
- Confidence: High
- Note: Direct dataflow from transport exception -> `last_code`/generic `exc` -> f-string stderr violates the locked redaction invariant.

- Finding ID: U-001
- Source Type: deep-lens: Real-Entry-Path Lens / Testing Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:240-257`; `bilibili-asr-archive/tests/test_subtitles.py:243-380`; `.mstar/sdd/20260824-api-contract-integrity/progress.md:12-14`
- Confidence: Medium
- Note: Behavior is statically coherent, but acceptance evidence is absent for the shipped CLI path.

- Finding ID: U-002
- Source Type: deep-lens: Correctness Lens / Testing Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/audio.py:109-111`; `bilibili-asr-archive/tests/test_audio.py:239-292`
- Confidence: Medium
- Note: The new MIME branch is unexercised by the changed tests.

- Finding ID: U-003
- Source Type: deep-lens: Security Lens / Testing Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/bili_client.py:504-529`; `bilibili-asr-archive/tests/test_audio.py:166-186`
- Confidence: Medium
- Note: Source passes no cookies, but the security invariant lacks a regression assertion.

## Summary
| Severity | Count |
|----------|-------|
| Critical | 0 |
| Warning | 1 |
| Suggestion | 0 |
| Unconfirmed | 3 |

**Verdict**: Request Changes

The warning is fixable within the current zero-residual review wave. After remediation, targeted QC2 revalidation should update this same report. QA remains mandatory and should cover the three explicitly unconfirmed acceptance paths.

## Revalidation
- Revalidation scope: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2`; static review of `branch.diff`, current `bili_client.py`, `cli.py`, `audio.py`, and changed tests. No tests, builds, lint, installs, or live requests were run by QC. External PC evidence (`116 passed`, six focused passed) was treated as supplied evidence only.
- F-001: **Resolved.** Transport exceptions are reduced through `_safe_error_code` to the exception type name before entering `RiskBudgetExhausted.last_code`; CLI unexpected, stream, and ASR handlers now use fixed summaries. The added fetch-meta, download-audio, and probe-subs sentinel cases exercise CLI entry points and assert that SESSDATA and signed URL material do not appear in output; manifests persist only numeric API codes or normal statuses. The fixed `finger/spi` bootstrap message also excludes the originating exception payload.
- U-001: **Resolved.** `test_cli_probe_subs_unknown_bvid_api_error_creates_minimal_row` covers direct `probe-subs --bvid` with an unknown API code, exit 1, minimal `meta_ok` row, numeric code, preserved cookie secrecy, and no URL in output/manifest.
- U-002: **Resolved.** `test_download_audio_mime_only_flac_remuxes` covers an extensionless/m4s URL with `mimeType: audio/flac`; the adjacent 30232 m4s test confirms ID alone does not trigger FLAC remux.
- U-003: **Resolved.** `test_download_audio_prefers_30216_and_sends_referer_ua` asserts SESSDATA is present on the API playurl call and `stream_calls[0]["cookies"] == {}` for the CDN request.
- New security/correctness scan: no additional Warning found in the assigned diff. WBI playurl parameters exclude SESSDATA, signed CDN URLs are not persisted, stream transport wraps exception messages in a fixed `StreamDownloadError`, and API error rows preserve resumable status.

## Revalidated Summary
| Severity | Count |
|----------|-------|
| Critical | 0 |
| Warning | 0 |
| Suggestion | 0 |
| Unconfirmed | 0 |

Verdict: Approve

## Revalidation
- Timestamp: 2026-08-24T15:30:00Z
- Scope: targeted L3 security/correctness re-review of `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2` using the final `review/branch.diff`, current source, and changed tests only. No tests, builds, installs, lint, or live requests were run; PC evidence remains external only.
- F-001 remains **Resolved**: `_safe_error_code` reduces transport exceptions to exception-type scalar labels before `RiskBudgetExhausted.last_code`; stream errors and generic CLI handlers expose fixed summaries. `_record_api_error` rejects non-integer values, so exception messages and signed URLs cannot enter manifest error fields. Fetch-meta, probe-subs, and download-audio CLI sentinel assertions cover output and manifest non-disclosure.
- U-001 remains **Resolved**: direct unknown `probe-subs --bvid` coverage asserts exit 1, a minimal resumable `meta_ok` row, numeric `last_api_error_code`, and no cookie/URL disclosure.
- U-002 remains **Resolved**: MIME-only FLAC coverage supplies `mimeType: audio/flac` on an `.m4s` URL and asserts remux; the explicit 30232 `.m4s` case asserts that quality ID alone does not imply FLAC.
- U-003 remains **Resolved**: playurl assertions confirm SESSDATA uses the API cookie channel, while the CDN stream assertion requires `cookies == {}`.
- New security/correctness scan: no new Warning. Signed stream URLs are consumed transiently and manifests retain only `audio_path`; raw transport exception messages have no output or manifest sink in the reviewed paths.

## Revalidated Summary
| Severity | Count |
|----------|-------|
| Critical | 0 |
| Warning | 0 |
| Suggestion | 0 |
| Unconfirmed | 0 |

Verdict: Approve
