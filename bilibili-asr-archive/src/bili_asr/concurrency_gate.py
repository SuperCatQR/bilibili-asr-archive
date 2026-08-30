"""Pure evidence gate for any separately approved future concurrency work."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_REPORT_SCHEMA_VERSION = "concurrency-gate-report-v1"
_EVIDENCE_SCHEMA_VERSION = "concurrency-gate-evidence-v1"
_WRITE_TARGETS = ("manifest", "sidecars", "attempts", "index", "artifacts")
_NUMERIC_EVIDENCE = (
    "age_seconds",
    "campaign_denominator",
    "reconciliation_denominator",
    "throughput_items_per_hour",
    "api_risk_rate",
    "peak_disk_bytes",
    "reclaim_rate",
    "duplicate_work_count",
    "max_owner_count",
)
_NUMERIC_THRESHOLDS = (
    "max_evidence_age_seconds",
    "min_throughput_items_per_hour",
    "max_api_risk_rate",
    "max_peak_disk_bytes",
    "min_reclaim_rate",
)
_BOOLEAN_EVIDENCE = (
    "crash_restart_passed",
    "checkpoint_reconciled",
    "risk_taxonomy_unchanged",
)
_SENSITIVE_MARKERS = (
    "credential",
    "password",
    "secret",
    "sessdata",
    "signed_url",
    "signed-url",
    "raw_exception",
    "raw-exception",
    "traceback",
)


@dataclass(frozen=True)
class GateResult:
    """Deterministic decision report; a pass never changes runtime behavior."""

    reason_codes: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.reason_codes

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": "go" if self.ok else "no-go",
            "ok": self.ok,
            "operating_mode": "sequential-no-daemon",
            "reason_codes": list(self.reason_codes),
            "schema_version": _REPORT_SCHEMA_VERSION,
        }


class ConcurrencyGate:
    """Evaluate immutable mappings without enabling workers or daemonization."""

    @staticmethod
    def evaluate(
        evidence: Mapping[str, object], thresholds: Mapping[str, object]
    ) -> GateResult:
        reasons: set[str] = set()
        if not isinstance(evidence, Mapping):
            reasons.add("evidence_malformed")
            evidence = {}
        if not isinstance(thresholds, Mapping):
            reasons.add("thresholds_malformed")
            thresholds = {}

        if _contains_sensitive_marker(evidence):
            reasons.add("sensitive_evidence_marker")
        if _contains_sensitive_marker(thresholds):
            reasons.add("sensitive_threshold_marker")

        if evidence.get("schema_version") != _EVIDENCE_SCHEMA_VERSION:
            reasons.add("evidence_schema_invalid")

        valid_evidence: dict[str, float] = {}
        for field in _NUMERIC_EVIDENCE:
            _validate_number(evidence, field, "evidence", reasons, valid_evidence)

        valid_thresholds: dict[str, float] = {}
        for field in _NUMERIC_THRESHOLDS:
            _validate_number(thresholds, field, "threshold", reasons, valid_thresholds)

        valid_booleans: dict[str, bool] = {}
        for field in _BOOLEAN_EVIDENCE:
            value = evidence.get(field)
            if field not in evidence:
                reasons.add(f"evidence_missing_{field}")
            elif not isinstance(value, bool):
                reasons.add(f"evidence_malformed_{field}")
            else:
                valid_booleans[field] = value

        write_isolation = evidence.get("write_isolation")
        if not isinstance(write_isolation, Mapping):
            reasons.add("evidence_malformed_write_isolation")
            write_isolation = {}
        for target in _WRITE_TARGETS:
            proof = write_isolation.get(target)
            if proof is not True:
                reasons.add(f"write_isolation_missing_{target}")

        _compare_upper(valid_evidence, "age_seconds", valid_thresholds,
                       "max_evidence_age_seconds", "evidence_stale", reasons)
        _compare_lower(valid_evidence, "throughput_items_per_hour", valid_thresholds,
                       "min_throughput_items_per_hour", "throughput_breach", reasons)
        _compare_upper(valid_evidence, "api_risk_rate", valid_thresholds,
                       "max_api_risk_rate", "api_risk_breach", reasons)
        _compare_upper(valid_evidence, "peak_disk_bytes", valid_thresholds,
                       "max_peak_disk_bytes", "disk_peak_breach", reasons)
        _compare_lower(valid_evidence, "reclaim_rate", valid_thresholds,
                       "min_reclaim_rate", "reclaim_breach", reasons)

        if (
            "campaign_denominator" in valid_evidence
            and "reconciliation_denominator" in valid_evidence
            and valid_evidence["campaign_denominator"]
            != valid_evidence["reconciliation_denominator"]
        ):
            reasons.add("denominator_mismatch")
        if valid_evidence.get("duplicate_work_count", 0) > 0:
            reasons.add("duplicate_work_detected")
        if valid_evidence.get("max_owner_count", 1) > 1:
            reasons.add("multiple_owners_detected")
        if valid_booleans.get("crash_restart_passed") is False:
            reasons.add("crash_restart_failed")
        if valid_booleans.get("checkpoint_reconciled") is False:
            reasons.add("checkpoint_unreconciled")
        if valid_booleans.get("risk_taxonomy_unchanged") is False:
            reasons.add("risk_taxonomy_changed")

        return GateResult(tuple(sorted(reasons)))


def _validate_number(
    source: Mapping[str, object],
    field: str,
    prefix: str,
    reasons: set[str],
    valid_values: dict[str, float],
) -> None:
    if field not in source:
        reasons.add(f"{prefix}_missing_{field}")
        return
    value = source[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reasons.add(f"{prefix}_malformed_{field}")
        return
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value < 0:
        reasons.add(f"{prefix}_malformed_{field}")
        return
    valid_values[field] = numeric_value


def _compare_upper(
    evidence: Mapping[str, float], evidence_field: str,
    thresholds: Mapping[str, float], threshold_field: str,
    reason: str, reasons: set[str],
) -> None:
    if (
        evidence_field in evidence
        and threshold_field in thresholds
        and evidence[evidence_field] > thresholds[threshold_field]
    ):
        reasons.add(reason)


def _compare_lower(
    evidence: Mapping[str, float], evidence_field: str,
    thresholds: Mapping[str, float], threshold_field: str,
    reason: str, reasons: set[str],
) -> None:
    if (
        evidence_field in evidence
        and threshold_field in thresholds
        and evidence[evidence_field] < thresholds[threshold_field]
    ):
        reasons.add(reason)


def _contains_sensitive_marker(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            normalized_key = str(key).strip().lower()
            if any(marker in normalized_key for marker in _SENSITIVE_MARKERS):
                return True
            if _contains_sensitive_marker(nested_value):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_sensitive_marker(item) for item in value)
    return False
