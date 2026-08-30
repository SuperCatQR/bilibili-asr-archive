---
iteration: iter-2026-08-corpus-coverage
plan_id: 20260828-coverage-telemetry-reconciliation
status: implemented
---
# Coverage telemetry and reconciliation contract

## Specify
**Value:** distinguish batch progress from cumulative corpus coverage and expose contradictions before operators act. **Target:** a read-only deterministic report over existing manifest/cursor/scheduler/ledger/attempt/artifact evidence. **Non-goals:** mutating sidecars, inferring unavailable denominators, or changing schemas.

## Clarify
- Denominator is visible manifest rows for a selected snapshot or explicit scope; unavailable denominators are reported, never guessed.
- `limited` and `risk_interrupted` remain distinct from `complete`.
- Reports are projections only and use bounded aggregates, stable ordering, explicit units, and redacted fields.

## Architect review

`CoverageReport.build(archive_root: Path, *, scope: str | None = None)` reads `ManifestStore`, cursor, scheduler, run ledger, attempts, and artifacts without writes. The denominator is the selected manifest snapshot; unavailable scope is an explicit diagnostic. Output ordering is work ID then category, with stable JSON keys/CSV columns. Drift (unparseable sidecar, conflicting terminal evidence, or missing denominator) is named nonzero and cannot become complete. Rollback is none because the operation is read-only. Verify: `PYTHONPATH=. uv run --with pytest pytest -q tests/test_coverage_report.py tests/test_cli_help.py`.

## Plan and acceptance
- Interface: `CoverageReport.build(archive_root: Path, *, scope: str | None = None) -> CoverageReport`; JSON/CSV serializers have stable key/column order and deterministic bytes.
- `coverage --archive-root <temporary-local-root> [--scope <scope>] --format json|csv` is read-only and fixture-only for verification; it performs no live traffic and does not mutate sidecars or artifacts.
- The denominator is the selected manifest snapshot in `work_items` units. If the manifest snapshot or requested scope cannot be established, denominator `state: unavailable`, `count: null`, and named diagnostic `denominator_unavailable`/`unknown_scope` are emitted; no denominator is inferred.
- `cumulative` covers every selected manifest row, while `batch` covers only the latest scheduler/ledger batch; both expose explicit totals and states and must not be conflated.
- Evidence states include `complete`, `limited`, `risk_interrupted`, `incomplete`, and `unavailable`; `limited` or `risk_interrupted` evidence and risk/limited diagnostics can never become `complete`.
- Reconciliation compares work-id sets and categorizes missing, duplicate, contradictory, stale, and terminal-but-missing-artifact evidence. Named diagnostics are nonzero (including malformed sidecars, scheduler/ledger mismatch, and retryable attempts); raw exception text, credentials, signed URLs, models, and media are redacted.
- Fixture covers complete, limited, interrupted, retryable, duplicate, and reclaimed-audio rows; repeated JSON/CSV bytes are identical and source mtimes/content remain unchanged.
- Exit `0` means a clean report; exit `1` means named diagnostics or usage/configuration failure (the global argparse usage taxonomy maps invalid options to 1). Stop if denominator cannot be defined or a report would rewrite any sidecar.
- Reconciliation compares work-id sets and categorizes missing, duplicate, contradictory, stale, and terminal-but-missing-artifact evidence.
- Fixture covers complete, limited, interrupted, retryable, duplicate, and reclaimed-audio rows; repeated bytes are identical and source mtimes/content remain unchanged.
- Contradictions produce named nonzero diagnostics; no report may claim full corpus completion from bounded evidence.
- Stop if denominator cannot be defined or a report would rewrite any sidecar.
