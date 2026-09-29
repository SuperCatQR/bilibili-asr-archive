---
iteration: iter-2026-08-corpus-coverage
plan_id: 20260828-subtitle-quality-campaign
status: implemented
---
# Subtitle coverage and transcript quality contract

## Specify
**Value:** quantify subtitle-first savings and expose deterministic artifact defects without judging meaning. **Target:** stable source/language/status counts and explainable cue/artifact reason codes. **Non-goals:** semantic correction, new ASR engine, diarization, concurrency, or automatic rewrite.

## Clarify
- Coverage uses the reconciled denominator and manifest status/source fields; no inferred language or semantic score is required.
- Checks may flag/report and may route only clearly unusable existing stage input to retryable work; they do not silently promote invalid artifacts.
- Reclaimed audio is not a defect when required transcript artifacts are present.

## Architect review

`QualityAnalyzer.analyze(row: Mapping[str, object], archive_root: Path)` is a pure projection over existing subtitle/archive artifacts; it must not call network or ASR. Reason codes are bounded and stable (`empty`, `malformed`, `non_monotonic`, `overlap`, `out_of_range`, `identity_mismatch`, `artifact_missing`). Reclaimed audio is accepted when required transcript outputs exist. Findings never mutate status/risk. Drift or normalization demand is STOP. Verify: `PYTHONPATH=. uv run --with pytest pytest -q tests/test_quality.py tests/test_cli_help.py`.

## Plan and acceptance
- Interface: `QualityAnalyzer.analyze(row: Mapping[str, object], archive_root: Path) -> QualityResult`; result keys and reason codes are stable.
- `coverage --archive-root <temporary-local-root> [--scope <scope>] [--format json|csv] [--quality]` provides deterministic read-only artifact quality and coverage reporting without network, model, or mutation; clean artifacts exit 0, defects or diagnostics exit 1.
- Validate empty/malformed/non-monotonic/overlapping/out-of-range cues, identity and artifact consistency, with bounded diagnostics.
- Fixture covers valid subtitle, malformed/empty subtitle, ordering defects, ASR output, and reclaimed audio; repeated output is stable and read-only.
- No report stores credentials, signed URLs, raw exceptions, models, or media; no semantic correctness claim is emitted.
- Stop if a finding requires frozen status/risk changes or content normalization without explicit policy.
