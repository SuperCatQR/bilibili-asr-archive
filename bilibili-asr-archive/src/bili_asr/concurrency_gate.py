"""Pure evidence gate for any separately approved future concurrency work."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_REPORT_SCHEMA_VERSION = "concurrency-gate-report-v1"
_EVIDENCE_SCHEMA_VERSION = "concurrency-gate-evidence-v1"
_WRITE_TARGETS = ("manifest", "sidecars", "attempts", "index", "artifacts")
_INT_EVIDENCE = ("age_seconds", "campaign_item_count", "campaign_denominator", "reconciliation_denominator", "peak_disk_bytes", "duplicate_work_count", "max_owner_count")
_RATE_EVIDENCE = ("api_risk_rate", "reclaim_rate")
_EVIDENCE_FIELDS = {"schema_version", "campaign_snapshot_id", "campaign_item_count", *_INT_EVIDENCE, *_RATE_EVIDENCE, "throughput_items_per_hour", "crash_restart_passed", "checkpoint_reconciled", "risk_taxonomy_unchanged", "write_isolation"}
_THRESHOLD_FIELDS = {"max_evidence_age_seconds", "min_throughput_items_per_hour", "max_api_risk_rate", "max_peak_disk_bytes", "min_reclaim_rate", "max_duplicate_work_count", "max_owner_count"}
_SENSITIVE_MARKERS = ("cookie", "auth", "token", "password", "secret", "credential", "sessdata", "signed_url", "signed-url", "raw_exception", "raw-exception", "traceback")
_MAX_DEPTH = 64
_MAX_NODES = 10000
_MAX_CONTAINER = 1000
_MAX_STRING = 4096


@dataclass(frozen=True)
class GateResult:
    reason_codes: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.reason_codes

    def to_dict(self) -> dict[str, object]:
        return {"decision": "go" if self.ok else "no-go", "ok": self.ok, "operating_mode": "sequential-no-daemon", "reason_codes": list(self.reason_codes), "schema_version": _REPORT_SCHEMA_VERSION}


class _UnsafeInput(Exception):
    pass


def _safe_items(value: object, depth: int = 0, state: list[int] | None = None) -> list[tuple[object, object]]:
    if state is None:
        state = [0]
    if depth > _MAX_DEPTH or state[0] >= _MAX_NODES:
        raise _UnsafeInput("complexity")
    state[0] += 1
    if isinstance(value, Mapping):
        try:
            items = list(value.items())
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise _UnsafeInput("access") from None
            raise
        if len(items) > _MAX_CONTAINER:
            raise _UnsafeInput("complexity")
        return items
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            items = list(enumerate(value))
        except BaseException as exc:
            if isinstance(exc, Exception):
                raise _UnsafeInput("access") from None
            raise
        if len(items) > _MAX_CONTAINER:
            raise _UnsafeInput("complexity")
        return items
    return []


def _contains_sensitive_marker(value: object) -> bool:
    seen: set[int] = set()
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_DEPTH:
            raise _UnsafeInput("complexity")
        if isinstance(current, str):
            if len(current) > _MAX_STRING:
                raise _UnsafeInput("complexity")
            if any(marker in current.strip().lower() for marker in _SENSITIVE_MARKERS):
                return True
            continue
        if not isinstance(current, (Mapping, Sequence)) or isinstance(current, (bytes, bytearray, str)):
            continue
        identity = id(current)
        if identity in seen:
            raise _UnsafeInput("cycle")
        seen.add(identity)
        nodes += 1
        if nodes > _MAX_NODES:
            raise _UnsafeInput("complexity")
        for key, nested in _safe_items(current, depth, [nodes]):
            if isinstance(key, str) and any(marker in key.strip().lower() for marker in _SENSITIVE_MARKERS):
                return True
            stack.append((nested, depth + 1))
    return False


def _mapping_copy(source: Mapping[str, object]) -> dict[str, object]:
    try:
        return dict(source)
    except BaseException as exc:
        if isinstance(exc, Exception):
            raise _UnsafeInput("access") from None
        raise


def _finite_number(source: Mapping[str, object], field: str, prefix: str, reasons: set[str], integer: bool = False, rate: bool = False, positive: bool = False) -> float | int | None:
    if field not in source:
        reasons.add(f"{prefix}_missing_{field}")
        return None
    try:
        value = source[field]
    except BaseException as exc:
        if isinstance(exc, Exception):
            reasons.add(f"{prefix}_malformed_{field}"); return None
        raise
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        reasons.add(f"{prefix}_malformed_{field}"); return None
    if integer and (not isinstance(value, int) or value < 0):
        reasons.add(f"{prefix}_malformed_{field}"); return None
    if not integer and (value < 0 or (positive and value <= 0) or (rate and not 0 <= value <= 1)):
        reasons.add(f"{prefix}_malformed_{field}"); return None
    return value


class ConcurrencyGate:
    @staticmethod
    def evaluate(evidence: Mapping[str, object], thresholds: Mapping[str, object]) -> GateResult:
        reasons: set[str] = set()
        try:
            if not isinstance(evidence, Mapping): reasons.add("evidence_malformed"); evidence = {}
            if not isinstance(thresholds, Mapping): reasons.add("thresholds_malformed"); thresholds = {}
            evidence = _mapping_copy(evidence); thresholds = _mapping_copy(thresholds)
            if _contains_sensitive_marker(evidence): reasons.add("sensitive_evidence_marker")
            if _contains_sensitive_marker(thresholds): reasons.add("sensitive_threshold_marker")
        except _UnsafeInput as exc:
            reasons.add(f"input_{exc}"); evidence = {}; thresholds = {}
        if set(evidence) - _EVIDENCE_FIELDS: reasons.add("evidence_unknown_fields")
        if set(thresholds) - _THRESHOLD_FIELDS: reasons.add("threshold_unknown_fields")
        if evidence.get("schema_version") != _EVIDENCE_SCHEMA_VERSION: reasons.add("evidence_schema_invalid")
        snapshot = evidence.get("campaign_snapshot_id")
        if not isinstance(snapshot, str) or not snapshot.strip() or len(snapshot) > 256 or not snapshot.isascii(): reasons.add("evidence_malformed_campaign_snapshot_id")
        values: dict[str, float | int] = {}
        for field in _INT_EVIDENCE: values[field] = _finite_number(evidence, field, "evidence", reasons, integer=True)  # type: ignore[assignment]
        for field in _RATE_EVIDENCE: values[field] = _finite_number(evidence, field, "evidence", reasons, rate=True)  # type: ignore[assignment]
        values["throughput_items_per_hour"] = _finite_number(evidence, "throughput_items_per_hour", "evidence", reasons, positive=True)  # type: ignore[assignment]
        threshold_values: dict[str, float | int] = {}
        for field in ("max_evidence_age_seconds", "max_peak_disk_bytes", "max_duplicate_work_count", "max_owner_count"): threshold_values[field] = _finite_number(thresholds, field, "threshold", reasons, integer=True)  # type: ignore[assignment]
        threshold_values["min_throughput_items_per_hour"] = _finite_number(thresholds, "min_throughput_items_per_hour", "threshold", reasons, positive=True)  # type: ignore[assignment]
        for field in ("max_api_risk_rate", "min_reclaim_rate"): threshold_values[field] = _finite_number(thresholds, field, "threshold", reasons, rate=True)  # type: ignore[assignment]
        for field in ("crash_restart_passed", "checkpoint_reconciled", "risk_taxonomy_unchanged"):
            if field not in evidence: reasons.add(f"evidence_missing_{field}")
            elif not isinstance(evidence[field], bool): reasons.add(f"evidence_malformed_{field}")
            elif not evidence[field]: reasons.add({"crash_restart_passed":"crash_restart_failed", "checkpoint_reconciled":"checkpoint_unreconciled", "risk_taxonomy_unchanged":"risk_taxonomy_changed"}[field])
        if values.get("campaign_item_count") != values.get("campaign_denominator") or values.get("campaign_denominator") != values.get("reconciliation_denominator"): reasons.add("denominator_mismatch")
        isolation = evidence.get("write_isolation")
        if not isinstance(isolation, Mapping): reasons.add("evidence_malformed_write_isolation"); isolation = {}
        else:
            try:
                if set(isolation) - set(_WRITE_TARGETS): reasons.add("write_isolation_unknown_fields")
            except Exception: reasons.add("input_access")
        for target in _WRITE_TARGETS:
            if isolation.get(target) is not True: reasons.add(f"write_isolation_missing_{target}")
        comparisons = (("age_seconds","max_evidence_age_seconds","evidence_stale"),("throughput_items_per_hour","min_throughput_items_per_hour","throughput_breach"),("api_risk_rate","max_api_risk_rate","api_risk_breach"),("peak_disk_bytes","max_peak_disk_bytes","disk_peak_breach"),("reclaim_rate","min_reclaim_rate","reclaim_breach"))
        for left, right, code in comparisons:
            left_value = values.get(left)
            right_value = threshold_values.get(right)
            if left_value is not None and right_value is not None and ((left in ("age_seconds", "api_risk_rate", "peak_disk_bytes") and left_value > right_value) or (left in ("throughput_items_per_hour", "reclaim_rate") and left_value < right_value)):
                reasons.add(code)
        if values.get("duplicate_work_count", 0) > threshold_values.get("max_duplicate_work_count", 0): reasons.add("duplicate_work_detected")
        if values.get("max_owner_count", 0) > threshold_values.get("max_owner_count", 1): reasons.add("multiple_owners_detected")
        return GateResult(tuple(sorted(reasons)))
