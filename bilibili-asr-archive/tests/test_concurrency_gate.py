from __future__ import annotations

import bili_asr.cli.concurrency as _module_cli_concurrency


import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bili_asr import cli
from bili_asr.cli.main import main
from bili_asr.concurrency_gate import ConcurrencyGate


@pytest.fixture
def thresholds() -> dict[str, object]:
    return {
        "min_campaign_item_count": 100,
        "max_evidence_age_seconds": 3600,
        "min_throughput_items_per_hour": 4,
        "max_api_risk_rate": 0.02,
        "max_peak_disk_bytes": 10_000,
        "min_reclaim_rate": 0.8,
        "max_duplicate_work_count": 0,
        "max_owner_count": 1,
    }


@pytest.fixture
def evidence() -> dict[str, object]:
    return {
        "schema_version": "concurrency-gate-evidence-v1",
        "campaign_snapshot_id": "snapshot-20260828",
        "campaign_item_count": 100,
        "campaign_denominator": 100,
        "reconciliation_denominator": 100,
        "age_seconds": 30,
        "throughput_items_per_hour": 5,
        "api_risk_rate": 0.01,
        "peak_disk_bytes": 9_000,
        "reclaim_rate": 0.9,
        "crash_restart_passed": True,
        "duplicate_work_count": 0,
        "max_owner_count": 1,
        "checkpoint_reconciled": True,
        "risk_taxonomy_unchanged": True,
        "write_isolation": {
            "manifest": True,
            "sidecars": True,
            "attempts": True,
            "index": True,
            "artifacts": True,
        },
    }


def reason_codes(evidence: object, thresholds: object) -> list[str]:
    return ConcurrencyGate.evaluate(evidence, thresholds).to_dict()["reason_codes"]


def test_complete_evidence_passes_without_mutation_or_enablement(evidence, thresholds) -> None:
    original_evidence = copy.deepcopy(evidence)
    original_thresholds = copy.deepcopy(thresholds)

    payload = ConcurrencyGate.evaluate(evidence, thresholds).to_dict()

    assert payload == {
        "decision": "go",
        "ok": True,
        "operating_mode": "sequential-no-daemon",
        "reason_codes": [],
        "schema_version": "concurrency-gate-report-v1",
    }
    assert evidence == original_evidence
    assert thresholds == original_thresholds


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "evidence_missing_campaign_snapshot_id"),
        ("", "evidence_empty_campaign_snapshot_id"),
        ("   ", "evidence_empty_campaign_snapshot_id"),
        ("x" * 257, "evidence_malformed_campaign_snapshot_id"),
        ("快照", "evidence_malformed_campaign_snapshot_id"),
        (3, "evidence_malformed_campaign_snapshot_id"),
    ],
)
def test_campaign_identity_validation(evidence, thresholds, value, reason) -> None:
    if value is None:
        evidence.pop("campaign_snapshot_id")
    else:
        evidence["campaign_snapshot_id"] = value
    assert reason in reason_codes(evidence, thresholds)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("campaign_item_count", 0, "evidence_zero_campaign_item_count"),
        ("campaign_item_count", -1, "evidence_malformed_campaign_item_count"),
        ("campaign_item_count", 1.5, "evidence_malformed_campaign_item_count"),
        ("campaign_item_count", float("inf"), "evidence_malformed_campaign_item_count"),
        ("campaign_denominator", 0, "evidence_zero_campaign_denominator"),
        ("campaign_denominator", -1, "evidence_malformed_campaign_denominator"),
        ("campaign_denominator", 1.5, "evidence_malformed_campaign_denominator"),
        ("reconciliation_denominator", 0, "evidence_zero_reconciliation_denominator"),
        ("reconciliation_denominator", -1, "evidence_malformed_reconciliation_denominator"),
        ("reconciliation_denominator", 1.5, "evidence_malformed_reconciliation_denominator"),
        ("max_owner_count", 0, "evidence_zero_max_owner_count"),
        ("max_owner_count", -1, "evidence_malformed_max_owner_count"),
        ("max_owner_count", 1.5, "evidence_malformed_max_owner_count"),
        ("age_seconds", -1, "evidence_malformed_age_seconds"),
        ("age_seconds", 1.5, "evidence_malformed_age_seconds"),
        ("peak_disk_bytes", -1, "evidence_malformed_peak_disk_bytes"),
        ("duplicate_work_count", -1, "evidence_malformed_duplicate_work_count"),
        ("duplicate_work_count", 1.5, "evidence_malformed_duplicate_work_count"),
    ],
)
def test_evidence_integer_semantics(evidence, thresholds, field, value, reason) -> None:
    evidence[field] = value
    assert reason in reason_codes(evidence, thresholds)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("duplicate_work_count", "evidence_missing_duplicate_work_count"),
        ("max_owner_count", "evidence_missing_max_owner_count"),
    ],
)
def test_duplicate_and_owner_fields_are_required(evidence, thresholds, field, reason) -> None:
    evidence.pop(field)
    assert reason in reason_codes(evidence, thresholds)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (0, "throughput_breach"),
        (0.5, "throughput_breach"),
        (-1, "evidence_malformed_throughput_items_per_hour"),
        (float("nan"), "evidence_malformed_throughput_items_per_hour"),
        (float("inf"), "evidence_malformed_throughput_items_per_hour"),
    ],
)
def test_throughput_allows_zero_structurally_then_applies_threshold(evidence, thresholds, value, reason) -> None:
    evidence["throughput_items_per_hour"] = value
    reasons = reason_codes(evidence, thresholds)
    assert reason in reasons
    if value == 0:
        assert "evidence_malformed_throughput_items_per_hour" not in reasons


@pytest.mark.parametrize("field", ["api_risk_rate", "reclaim_rate"])
@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf")])
def test_rates_are_finite_unit_interval(evidence, thresholds, field, value) -> None:
    evidence[field] = value
    assert f"evidence_malformed_{field}" in reason_codes(evidence, thresholds)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("min_campaign_item_count", 0, "threshold_zero_min_campaign_item_count"),
        ("min_campaign_item_count", -1, "threshold_malformed_min_campaign_item_count"),
        ("min_campaign_item_count", 1.5, "threshold_malformed_min_campaign_item_count"),
        ("max_evidence_age_seconds", -1, "threshold_malformed_max_evidence_age_seconds"),
        ("max_evidence_age_seconds", 1.5, "threshold_malformed_max_evidence_age_seconds"),
        ("min_throughput_items_per_hour", 0, "threshold_zero_min_throughput_items_per_hour"),
        ("min_throughput_items_per_hour", -1, "threshold_malformed_min_throughput_items_per_hour"),
        ("min_throughput_items_per_hour", float("inf"), "threshold_malformed_min_throughput_items_per_hour"),
        ("max_api_risk_rate", 1.01, "threshold_malformed_max_api_risk_rate"),
        ("min_reclaim_rate", -0.01, "threshold_malformed_min_reclaim_rate"),
        ("max_peak_disk_bytes", -1, "threshold_malformed_max_peak_disk_bytes"),
        ("max_duplicate_work_count", -1, "threshold_malformed_max_duplicate_work_count"),
        ("max_owner_count", 0, "threshold_zero_max_owner_count"),
        ("max_owner_count", 1.5, "threshold_malformed_max_owner_count"),
    ],
)
def test_threshold_type_and_range_semantics(evidence, thresholds, field, value, reason) -> None:
    thresholds[field] = value
    assert reason in reason_codes(evidence, thresholds)


def test_campaign_count_must_fit_denominator_and_minimum(evidence, thresholds) -> None:
    evidence["campaign_item_count"] = 99
    assert reason_codes(evidence, thresholds) == ["campaign_item_count_below_minimum"]

    evidence["campaign_item_count"] = 101
    assert reason_codes(evidence, thresholds) == ["campaign_item_count_exceeds_denominator"]

    evidence["campaign_item_count"] = 100
    evidence["reconciliation_denominator"] = 101
    assert reason_codes(evidence, thresholds) == ["reconciliation_denominator_mismatch"]


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("evidence", "evidence_unknown_fields"),
        ("thresholds", "threshold_unknown_fields"),
        ("write_isolation", "write_isolation_unknown_fields"),
    ],
)
def test_unknown_fields_are_rejected_independently(evidence, thresholds, location, reason) -> None:
    if location == "evidence":
        evidence["unexpected"] = 1
    elif location == "thresholds":
        thresholds["unexpected"] = 1
    else:
        evidence["write_isolation"]["unexpected"] = True
    assert reason in reason_codes(evidence, thresholds)


@pytest.mark.parametrize(
    "value",
    [
        {"credential": "x"},
        {"cookie": "x"},
        {"SESSDATA": "x"},
        {"password": "x"},
        {"secret": "x"},
        "authorization: Basic abc",
        "Authorization=Bearer abc",
        "token=abc",
        "https://example.test/a?x-amz-signature=abc",
        "https://example.test/a?sig=abc",
        "https://example.test/a?signature=abc",
        "signed URL: https://example.test/a",
        "raw exception: OSError",
        "Traceback (most recent call last):",
        {"nested": [{"client_secret": "x"}]},
    ],
)
def test_sensitive_marker_families_are_rejected_in_keys_and_values(evidence, thresholds, value) -> None:
    evidence["diagnostic"] = value
    assert "sensitive_evidence_marker" in reason_codes(evidence, thresholds)


@pytest.mark.parametrize(
    "value",
    [
        "authentication succeeded",
        "tokenized corpus",
        "authorization model reviewed",
        "bearer capacity estimate",
        "signature algorithm name",
        "secretary notes",
        {"authentication_method": "oauth-like label only"},
        {"tokenized_count": 100},
    ],
)
def test_sensitive_scanner_allows_benign_near_misses(evidence, thresholds, value) -> None:
    evidence["diagnostic"] = value
    assert reason_codes(evidence, thresholds) == ["evidence_unknown_fields"]


class HostileMapping(Mapping[str, object]):
    def __iter__(self):
        raise RuntimeError("hostile iterator")

    def __len__(self) -> int:
        raise RuntimeError("hostile length")

    def __getitem__(self, key: str) -> object:
        raise RuntimeError("hostile item")


class HostileSequence(Sequence[object]):
    def __getitem__(self, index: int) -> object:
        raise RuntimeError("hostile item")

    def __len__(self) -> int:
        raise RuntimeError("hostile length")


def test_hostile_top_level_mapping_is_stable_no_go(thresholds) -> None:
    assert reason_codes(HostileMapping(), thresholds) == ["evidence_access_error"]


def test_hostile_nested_mapping_and_sequence_are_stable_no_go(evidence, thresholds) -> None:
    evidence["diagnostic"] = HostileMapping()
    assert reason_codes(evidence, thresholds) == ["evidence_access_error"]

    evidence["diagnostic"] = HostileSequence()
    assert reason_codes(evidence, thresholds) == ["evidence_access_error"]


def test_hostile_write_isolation_access_is_stable_no_go(evidence, thresholds) -> None:
    evidence["write_isolation"] = HostileMapping()
    assert reason_codes(evidence, thresholds) == ["evidence_access_error"]


def test_depth_container_string_cycle_and_shared_reference_bounds(evidence, thresholds) -> None:
    nested: object = "safe"
    for _ in range(66):
        nested = [nested]
    evidence["diagnostic"] = nested
    assert reason_codes(evidence, thresholds) == ["evidence_complexity_limit"]

    evidence["diagnostic"] = ["safe"] * 1001
    assert reason_codes(evidence, thresholds) == ["evidence_complexity_limit"]

    evidence["diagnostic"] = "x" * 4097
    assert reason_codes(evidence, thresholds) == ["evidence_complexity_limit"]

    cycle: list[object] = []
    cycle.append(cycle)
    evidence["diagnostic"] = cycle
    assert reason_codes(evidence, thresholds) == ["evidence_complexity_or_cycle"]

    shared = ["safe"]
    evidence["diagnostic"] = [shared, shared]
    assert reason_codes(evidence, thresholds) == ["evidence_complexity_or_cycle"]


def test_shared_node_budget_counts_every_popped_node(evidence, thresholds) -> None:
    evidence["diagnostic"] = [[str(index) for index in range(1000)] for _ in range(10)]
    assert reason_codes(evidence, thresholds) == ["evidence_complexity_limit"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda item: item.pop("age_seconds"), "evidence_missing_age_seconds"),
        (lambda item: item.__setitem__("age_seconds", 3601), "evidence_stale"),
        (lambda item: item.__setitem__("throughput_items_per_hour", 3), "throughput_breach"),
        (lambda item: item.__setitem__("api_risk_rate", 0.03), "api_risk_breach"),
        (lambda item: item.__setitem__("peak_disk_bytes", 10_001), "disk_peak_breach"),
        (lambda item: item.__setitem__("reclaim_rate", 0.7), "reclaim_breach"),
        (lambda item: item.__setitem__("crash_restart_passed", False), "crash_restart_failed"),
        (lambda item: item.__setitem__("duplicate_work_count", 1), "duplicate_work_detected"),
        (lambda item: item.__setitem__("max_owner_count", 2), "multiple_owners_detected"),
        (lambda item: item.__setitem__("checkpoint_reconciled", False), "checkpoint_unreconciled"),
        (lambda item: item.__setitem__("risk_taxonomy_unchanged", False), "risk_taxonomy_changed"),
        (lambda item: item["write_isolation"].__setitem__("manifest", False), "write_isolation_missing_manifest"),
    ],
)
def test_gate_breach_reasons_are_stable_and_sorted(evidence, thresholds, mutation, reason) -> None:
    mutation(evidence)
    reasons = reason_codes(evidence, thresholds)
    assert reason in reasons
    assert reasons == sorted(set(reasons))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def run_cli(evidence_path: Path, thresholds_path: Path, capsys) -> tuple[int, dict[str, object]]:
    exit_code = main([
        "evaluate-concurrency",
        "--evidence",
        str(evidence_path),
        "--thresholds",
        str(thresholds_path),
    ])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.endswith("\n")
    return exit_code, json.loads(captured.err)


def assert_cli_error(payload: dict[str, object], error_code: str) -> None:
    assert payload == {
        "error_code": error_code,
        "operating_mode": "sequential-no-daemon",
    }


def test_cli_outputs_deterministic_json_and_never_enables_concurrency(tmp_path, evidence, thresholds, capsys) -> None:
    evidence_path = tmp_path / "evidence.json"
    thresholds_path = tmp_path / "thresholds.json"
    write_json(evidence_path, evidence)
    write_json(thresholds_path, thresholds)

    exit_code = main([
        "evaluate-concurrency",
        "--evidence",
        str(evidence_path),
        "--thresholds",
        str(thresholds_path),
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == json.dumps(
        ConcurrencyGate.evaluate(evidence, thresholds).to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


@pytest.mark.parametrize(
    ("setup", "error_code"),
    [
        (lambda path: None, "input_file_missing"),
        (lambda path: path.mkdir(), "input_file_not_regular"),
        (lambda path: path.write_bytes(b"x" * 1_048_577), "input_file_oversized"),
        (lambda path: path.write_bytes(b"\xff"), "input_invalid_utf8"),
        (lambda path: path.write_text("not-json", encoding="utf-8"), "input_malformed_json"),
        (lambda path: path.write_text("[]", encoding="utf-8"), "input_non_object_json"),
    ],
)
def test_cli_input_error_categories_are_exact(tmp_path, thresholds, capsys, setup, error_code) -> None:
    evidence_path = tmp_path / "evidence.json"
    thresholds_path = tmp_path / "thresholds.json"
    setup(evidence_path)
    write_json(thresholds_path, thresholds)

    exit_code, payload = run_cli(evidence_path, thresholds_path, capsys)

    assert exit_code != 0
    assert_cli_error(payload, error_code)


def test_cli_unreadable_category_uses_reader_monkeypatch(tmp_path, evidence, thresholds, capsys, monkeypatch) -> None:
    evidence_path = tmp_path / "evidence.json"
    thresholds_path = tmp_path / "thresholds.json"
    write_json(evidence_path, evidence)
    write_json(thresholds_path, thresholds)

    original_reader = _module_cli_concurrency._read_concurrency_json_object

    def unreadable_reader(path: str) -> dict[str, object]:
        if path == str(evidence_path):
            raise _module_cli_concurrency._ConcurrencyInputError("input_file_unreadable")
        return original_reader(path)

    monkeypatch.setattr(_module_cli_concurrency, "_read_concurrency_json_object", unreadable_reader)
    exit_code, payload = run_cli(evidence_path, thresholds_path, capsys)

    assert exit_code != 0
    assert_cli_error(payload, "input_file_unreadable")


def test_cli_evaluation_failure_is_exact_and_does_not_leak(tmp_path, evidence, thresholds, capsys, monkeypatch) -> None:
    evidence_path = tmp_path / "evidence.json"
    thresholds_path = tmp_path / "thresholds.json"
    write_json(evidence_path, evidence)
    write_json(thresholds_path, thresholds)

    def fail_evaluation(*_args: object) -> object:
        raise RuntimeError("secret value and /private/path")

    monkeypatch.setattr(ConcurrencyGate, "evaluate", fail_evaluation)
    exit_code, payload = run_cli(evidence_path, thresholds_path, capsys)

    assert exit_code != 0
    assert_cli_error(payload, "evaluation_failure")


def test_cli_pathological_nested_input_is_no_go_not_evaluation_failure(tmp_path, evidence, thresholds, capsys) -> None:
    evidence_path = tmp_path / "evidence.json"
    thresholds_path = tmp_path / "thresholds.json"
    nested: object = "safe"
    for _ in range(66):
        nested = [nested]
    evidence["diagnostic"] = nested
    write_json(evidence_path, evidence)
    write_json(thresholds_path, thresholds)

    exit_code = main([
        "evaluate-concurrency",
        "--evidence",
        str(evidence_path),
        "--thresholds",
        str(thresholds_path),
    ])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code != 0
    assert captured.err == ""
    assert payload["reason_codes"] == ["evidence_complexity_limit"]
    assert payload["operating_mode"] == "sequential-no-daemon"
