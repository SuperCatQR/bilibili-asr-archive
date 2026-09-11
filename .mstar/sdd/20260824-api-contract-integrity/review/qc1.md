---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260824-api-contract-integrity"
verdict: "Approve"
generated_at: "2026-08-24T15:20:00+08:00"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: openai/gpt-5.6-sol
- Review Perspective: Architecture coherence and maintainability risk
- Report Timestamp: 2026-08-24T14:40:00+08:00

## Scope
- plan_id: `20260824-api-contract-integrity`
- Review range / Diff basis: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..d142c33`
- Working branch (verified): `plan/005-bilibili-api-contract-integrity`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive`
- Files reviewed: 6 changed files, plus current `manifest.py`, `subtitles.py`, plan, spec, and local API reference
- Commit range: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..d142c337e6f44721443ad88d3968deba84249372`
- Analysis methods: supplied branch diff, git metadata/diff inspection, read, grep, deep-lens: Modularity Lens, Contract Lens, Testing Lens
- Deep review: triggered (S1: 361 changed lines across 6 files; S6: client, CLI, audio, manifest orchestration, and three test modules)
- External evidence note: PC WSL `109 passed` and four focused Task 2 tests were treated as L1/QA evidence only; no tests, builds, installs, lint, or live requests were run in this review.

## Findings
### Critical
- None.

### Warning
- [F-001] `last_api_error_code` has no lifecycle invalidation, so a later successful retry leaves the manifest in a contradictory state (`status=subtitle_done|needs_audio|audio_ok` while retaining the prior API error). Clear this diagnostic at the shared successful manifest-transition owners, and add retry-after-error coverage for subtitle and audio paths.
  - Verification: `cli.py:128-141` adds the field on API failure; `subtitles.py:71-101` and `audio.py:99-149` copy the existing row and update status without removing it. Repository grep found no other clearing path or success-after-error assertion.
  - Expected vs observed: the additive field should describe the row's current actionable failure and disappear after recovery vs successful transitions preserve stale error metadata indefinitely.
  - Source Type: deep-lens: Contract Lens / Ownership & Derived-State reasoning
  - Confidence: High
  - Impact: status remains resumable, but operators and future automation cannot distinguish an active API failure from a recovered historical failure; the new cross-layer diagnostic contract therefore becomes ambiguous immediately after the intended resume succeeds.

### Suggestion
- [F-002] Add the plan-required direct unknown-BVID `probe-subs` API-error regression instead of relying on the audio command as indirect coverage.
  - Verification: `cli.py:240-257` creates a `meta_ok` row through `_record_api_error(..., starting_status="meta_ok")`, while changed tests cover only direct unknown `download-audio` (`tests/test_audio.py:380-405`); `progress.md:12-14` records the same gap.
  - Expected vs observed: each command-specific starting-status contract should be pinned at its real CLI entry path and preserve explicit route overrides vs the probe-specific `meta_ok` creation path is implemented but untested.
  - Source Type: deep-lens: Testing Lens
  - Confidence: High

### Unconfirmed
- None.

## Architecture Assessment
- HTTP ownership remains coherent: WBI key retrieval, signing, cookie forwarding, JSON requests, and stream GETs stay in `bili_client.py`; neither CLI nor `audio.py` opens sockets.
- The WBI/cookie seam is reused rather than duplicated: `fetch_playurl_audio()` follows the existing `_wbi_keys()` + `sign_wbi()` + `_request_with_cookies()` path used by subtitle probing, and SESSDATA remains in the cookie channel.
- Risk taxonomy is materially clearer: frozen gone codes are separated from resumable API errors in both request helpers, and CLI batch exit behavior is consistent for subtitle/audio mixed failures.
- Audio quality/container boundaries are explicit: quality selection remains in `audio.py`, while FLAC detection uses URL/MIME evidence rather than ID 30232. No hidden schema migration is introduced; `ManifestStore` accepts additive fields.
- Fixture overrides remain explicit: added `setdefault("nav", ...)` defaults do not replace caller-provided `nav` routes. The remaining maintainability gap is command-specific probe coverage, not route override masking.

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Contract Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:128-141`; `bilibili-asr-archive/src/bili_asr/subtitles.py:71-101`; `bilibili-asr-archive/src/bili_asr/audio.py:99-149`
- Confidence: High
- Note: grep for `last_api_error_code` found writes and assertions only, with no invalidation path.

- Finding ID: F-002
- Source Type: deep-lens: Testing Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py:240-257`; `bilibili-asr-archive/tests/test_audio.py:380-405`; `.mstar/sdd/20260824-api-contract-integrity/progress.md:12-14`
- Confidence: High
- Note: verify through a direct `probe-subs --bvid` API-error test using an explicit `pagelist` failure route and asserting the minimal `meta_ok` row.

## Summary
| Severity | Count |
|----------|-------|
| Critical | 0 |
| Warning | 1 |
| Suggestion | 1 |
| Unconfirmed | 0 |

Verdict: Request Changes

## Revalidation
- Re-review type: targeted L3 re-review of the final frozen package.
- Final review range / Diff basis: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2`
- Working branch: `plan/005-bilibili-api-contract-integrity`
- Evidence reviewed: existing findings and final `review/branch.diff`; external PC evidence was treated only as cited L1/QA evidence. No tests, builds, installs, lint, live requests, or Git mutations were performed.
- F-001 resolved: `subtitles.py` removes `last_api_error_code` before both successful manifest transitions (`needs_audio` and `subtitle_done`), and `audio.py` removes it before `audio_ok`. The changed tests statically assert invalidation on all three transitions.
- F-002 resolved: `test_cli_probe_subs_unknown_bvid_api_error_creates_minimal_row` invokes the shipped `probe-subs --bvid` entry path for an unknown BVID and asserts the exact minimal row `{bvid, status: "meta_ok", last_api_error_code: -99999}`; the API code is numeric.
- Architecture re-check: no new Warning. Invalidation remains at the existing successful transition owners, and direct-operation row creation remains centralized in `_record_api_error`; no new dependency direction, duplicated client boundary, or schema migration was introduced.
- Original findings above are preserved as the initial review record; both are closed by this revalidation.

Verdict: Approve
