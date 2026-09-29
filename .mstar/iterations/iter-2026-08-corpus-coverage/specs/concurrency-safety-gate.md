---
iteration: iter-2026-08-corpus-coverage
plan_id: 20260828-concurrency-safety-gate
status: implemented
---
# Concurrency and daemon safety gate contract

## Purpose and non-enablement boundary

The shipped gate makes a future parallelism decision from measured evidence,
not hardware assumptions. It is a deterministic, machine-checkable report and
not a concurrency switch. A `go` report is evidence only for a future,
separately approved plan. Production remains `sequential-no-daemon`.

No worker, daemon, service unit, automatic startup, concurrent manifest writer,
distributed queue, default-mode change, manifest/sidecar schema change, manifest
status change, or risk-taxonomy change is introduced by this plan. Thresholds
are explicit reviewed configuration and are never guessed from CPU, memory, or
disk capacity.

## Public API and CLI

The exact public Python surface is:

```python
ConcurrencyGate.evaluate(
    evidence: Mapping[str, object],
    thresholds: Mapping[str, object],
) -> GateResult
GateResult.to_dict() -> dict[str, object]
```

The evaluator is pure and does not mutate either input. The operator surface is:

```text
bili-asr evaluate-concurrency --evidence <path> --thresholds <path>
```

Both paths must contain JSON objects. Each file is bounded to 1 MiB before UTF-8
decoding and JSON parsing. Unknown top-level fields and unknown nested
`write_isolation` fields fail closed.

## Required evidence object

The evidence object contains exactly these required fields:

| Field | Contract |
|---|---|
| `schema_version` | Exact string `concurrency-gate-evidence-v1`. |
| `campaign_snapshot_id` | Non-empty ASCII string, maximum 256 characters. |
| `campaign_item_count` | Positive integer; no greater than `campaign_denominator` and at least the explicit minimum threshold. |
| `campaign_denominator` | Positive integer. |
| `reconciliation_denominator` | Positive integer exactly equal to `campaign_denominator`. |
| `age_seconds` | Nonnegative integer freshness age. |
| `throughput_items_per_hour` | Finite nonnegative number. Zero is structurally valid but breaches a positive minimum threshold. |
| `api_risk_rate` | Finite number in `[0,1]`. |
| `peak_disk_bytes` | Nonnegative integer. |
| `reclaim_rate` | Finite number in `[0,1]`. |
| `crash_restart_passed` | Boolean; must be `true` for `go`. |
| `duplicate_work_count` | Nonnegative integer. |
| `max_owner_count` | Positive integer observed owner maximum. |
| `checkpoint_reconciled` | Boolean; must be `true` for `go`. |
| `risk_taxonomy_unchanged` | Boolean; must be `true` for `go`. |
| `write_isolation` | Object with exactly `manifest`, `sidecars`, `attempts`, `index`, and `artifacts`; every value must be strictly `true`. |

## Required threshold object

The threshold object contains exactly these required fields:

| Field | Contract |
|---|---|
| `min_campaign_item_count` | Positive integer. |
| `max_evidence_age_seconds` | Nonnegative integer. |
| `min_throughput_items_per_hour` | Finite positive number. |
| `max_api_risk_rate` | Finite number in `[0,1]`. |
| `max_peak_disk_bytes` | Nonnegative integer. |
| `min_reclaim_rate` | Finite number in `[0,1]`. |
| `max_duplicate_work_count` | Nonnegative integer. |
| `max_owner_count` | Positive integer. |

## Safe fixture examples

These are synthetic fixture values, not hardware-derived recommendations. They
contain no credentials or real URLs.

```json
{"schema_version":"concurrency-gate-evidence-v1","campaign_snapshot_id":"fixture-campaign-001","campaign_item_count":10,"campaign_denominator":10,"reconciliation_denominator":10,"age_seconds":30,"throughput_items_per_hour":5.0,"api_risk_rate":0.01,"peak_disk_bytes":1000,"reclaim_rate":0.9,"crash_restart_passed":true,"duplicate_work_count":0,"max_owner_count":1,"checkpoint_reconciled":true,"risk_taxonomy_unchanged":true,"write_isolation":{"manifest":true,"sidecars":true,"attempts":true,"index":true,"artifacts":true}}
```

```json
{"min_campaign_item_count":10,"max_evidence_age_seconds":3600,"min_throughput_items_per_hour":4.0,"max_api_risk_rate":0.02,"max_peak_disk_bytes":2000,"min_reclaim_rate":0.8,"max_duplicate_work_count":0,"max_owner_count":1}
```

## Report, reasons, and exit contract

`GateResult.to_dict()` uses schema `concurrency-gate-report-v1` and returns the
deterministic keys `decision`, `ok`, `operating_mode`, `reason_codes`, and
`schema_version`. `decision` is `go` only when `reason_codes` is empty;
otherwise it is `no-go`. `operating_mode` is always
`sequential-no-daemon`. Reason codes are stable, sorted, and unique. They cover
missing/malformed/zero fields, unknown fields, campaign contradictions,
threshold breaches, failed recovery/ownership/isolation/taxonomy evidence,
sensitive-data markers, and bounded-input access/complexity failures.

CLI exit `0` means `go`. Exit `1` means gate `no-go`, invalid input, or
evaluation failure. Input/evaluation failures are compact JSON on stderr with
`operating_mode: sequential-no-daemon` and a stable `error_code`:

- `input_file_missing`
- `input_file_unreadable`
- `input_file_not_regular`
- `input_file_oversized`
- `input_invalid_utf8`
- `input_malformed_json`
- `input_non_object_json`
- `evaluation_failure`

The CLI never includes a path, exception, or input value in that error output.
Credentials, cookies/SESSDATA, passwords/secrets, authorization or token
assignments, signed URLs/signatures, raw exceptions, and tracebacks are rejected
from evidence rather than persisted or echoed.

## Acceptance

- Missing, stale, malformed, contradictory, sensitive, or threshold-breaching
  evidence is deterministic no-go.
- Duplicate ownership, crash/restart, disk/risk, checkpoint, denominator, and
  exact write-isolation cases have dedicated fixtures.
- Help text states that evaluation is evidence-only and production remains
  sequential with no daemon.
- A later implementation can proceed only after a passing report and a separate
  approved implementation plan; this gate itself enables nothing.
