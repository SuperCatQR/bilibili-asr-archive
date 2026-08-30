from __future__ import annotations

import copy
import json

import pytest

from bili_asr.cli import main
from bili_asr.concurrency_gate import ConcurrencyGate


@pytest.fixture
def thresholds() -> dict[str, object]:
    return {
        "max_evidence_age_seconds": 3600,
        "min_throughput_items_per_hour": 4,
        "max_api_risk_rate": 0.02,
        "max_peak_disk_bytes": 10_000,
        "min_reclaim_rate": 0.8,
    }


@pytest.fixture
def evidence() -> dict[str, object]:
    return {
        "schema_version": "concurrency-gate-evidence-v1",
        "age_seconds": 30,
        "campaign_denominator": 100,
        "reconciliation_denominator": 100,
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


def test_complete_evidence_passes_without_mutating_inputs(evidence, thresholds) -> None:
    original_evidence = copy.deepcopy(evidence)
    original_thresholds = copy.deepcopy(thresholds)

    result = ConcurrencyGate.evaluate(evidence, thresholds)

    assert result.to_dict() == {
        "decision": "go",
        "ok": True,
        "operating_mode": "sequential-no-daemon",
        "reason_codes": [],
        "schema_version": "concurrency-gate-report-v1",
    }
    assert evidence == original_evidence
    assert thresholds == original_thresholds


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda e: e.pop("age_seconds"), "evidence_missing_age_seconds"),
        (lambda e: e.__setitem__("age_seconds", 3601), "evidence_stale"),
        (lambda e: e.__setitem__("age_seconds", True), "evidence_malformed_age_seconds"),
        (lambda e: e.__setitem__("api_risk_rate", float("nan")), "evidence_malformed_api_risk_rate"),
        (lambda e: e.__setitem__("peak_disk_bytes", -1), "evidence_malformed_peak_disk_bytes"),
        (lambda e: e.__setitem__("reconciliation_denominator", 99), "denominator_mismatch"),
        (lambda e: e.__setitem__("throughput_items_per_hour", 3), "throughput_breach"),
        (lambda e: e.__setitem__("api_risk_rate", 0.03), "api_risk_breach"),
        (lambda e: e.__setitem__("peak_disk_bytes", 10_001), "disk_peak_breach"),
        (lambda e: e.__setitem__("reclaim_rate", 0.7), "reclaim_breach"),
        (lambda e: e.__setitem__("crash_restart_passed", False), "crash_restart_failed"),
        (lambda e: e.__setitem__("duplicate_work_count", 1), "duplicate_work_detected"),
        (lambda e: e.__setitem__("max_owner_count", 2), "multiple_owners_detected"),
        (lambda e: e.__setitem__("checkpoint_reconciled", False), "checkpoint_unreconciled"),
        (lambda e: e["write_isolation"].__setitem__("manifest", False), "write_isolation_missing_manifest"),
        (lambda e: e.__setitem__("risk_taxonomy_unchanged", False), "risk_taxonomy_changed"),
        (lambda e: e.__setitem__("nested", {"payload": {"signed_url": "x"}}), "sensitive_evidence_marker"),
        (lambda e: e.__setitem__("nested", [{"TraceBack": "x"}]), "sensitive_evidence_marker"),
    ],
)
def test_unsafe_evidence_is_deterministic_no_go(evidence, thresholds, mutation, reason) -> None:
    mutation(evidence)
    result = ConcurrencyGate.evaluate(evidence, thresholds).to_dict()
    assert result["decision"] == "no-go"
    assert result["operating_mode"] == "sequential-no-daemon"
    assert reason in result["reason_codes"]
    assert result["reason_codes"] == sorted(set(result["reason_codes"]))


def test_missing_malformed_and_sensitive_thresholds_are_no_go(evidence, thresholds) -> None:
    thresholds.pop("max_api_risk_rate")
    thresholds["max_peak_disk_bytes"] = False
    thresholds["nested"] = {"credential": "secret"}

    reasons = ConcurrencyGate.evaluate(evidence, thresholds).to_dict()["reason_codes"]

    assert reasons == [
        "sensitive_threshold_marker",
        "threshold_malformed_max_peak_disk_bytes",
        "threshold_missing_max_api_risk_rate",
    ]


def test_cli_outputs_deterministic_json_and_never_enables_concurrency(
    tmp_path, evidence, thresholds, capsys
) -> None:
    evidence_path = tmp_path / "evidence.json"
    thresholds_path = tmp_path / "thresholds.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    thresholds_path.write_text(json.dumps(thresholds), encoding="utf-8")

    exit_code = main([
        "evaluate-concurrency",
        "--evidence", str(evidence_path),
        "--thresholds", str(thresholds_path),
    ])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output == json.dumps(
        ConcurrencyGate.evaluate(evidence, thresholds).to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    assert json.loads(output)["operating_mode"] == "sequential-no-daemon"


def test_cli_rejects_invalid_json_without_traceback(tmp_path, thresholds, capsys) -> None:
    evidence_path = tmp_path / "evidence.json"
    thresholds_path = tmp_path / "thresholds.json"
    evidence_path.write_text("not-json", encoding="utf-8")
    thresholds_path.write_text(json.dumps(thresholds), encoding="utf-8")

    exit_code = main([
        "evaluate-concurrency",
        "--evidence", str(evidence_path),
        "--thresholds", str(thresholds_path),
    ])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "evaluate-concurrency: invalid input; sequential/no-daemon remains active\n"
