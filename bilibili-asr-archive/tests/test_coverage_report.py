"""Fixture-driven behavioral coverage for the read-only coverage projection."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bili_asr.coverage_report import CoverageReport

NOW = "2026-08-28T12:00:00Z"


def manifest_row(work_id: str, status: str = "archived", *, bvid: str | None = None) -> dict:
    return {
        "work_id": work_id, "bvid": bvid or work_id.split(":")[0], "page_index": 1,
        "page_label": "Part 1", "cid": 101, "title": "Marker", "status": status,
        "pubdate_str": "2026-01-01", "duration_s": 1,
    }


def cursor(state: str = "complete") -> dict:
    return {"mid": 23191782, "next_page": 3, "total": 2,
            "state": state, "last_api_error_code": None, "updated_at": NOW}


def scheduler(state: str = "complete", ids: list[str] | None = None) -> dict:
    return {"scope": "all", "limit": 20, "state": state,
            "processed_work_ids": ids or ["BVone:p1", "BVtwo:p1"],
            "last_api_error_code": None, "allow_long_live": False, "updated_at": NOW}


def ledger(ids: list[str] | None = None, *, exit_code: int = 0) -> dict:
    return {"run_id": "run-1", "command": "schedule", "started_at": NOW,
            "finished_at": NOW, "exit_code": exit_code, "mid": 23191782,
            "work_ids": ids or ["BVone:p1", "BVtwo:p1"], "pages_fetched": 1,
            "records_fetched": 2, "records_existing": 0, "last_api_error_code": None,
            "coverage_summary": {"archived": 2}, "cursor_snapshot": cursor()}


def attempt(work_id: str, outcome: str = "ok", number: int = 1, stage: str = "archive") -> dict:
    return {"stage": stage, "work_id": work_id, "attempt": number, "outcome": outcome,
            "error_code": None, "artifact_paths": [], "started_at": NOW, "finished_at": NOW}


def write_fixture(root: Path, rows: list[dict], *, cur=None, sched=None, ledgers=None, attempts=None):
    (root / "manifest").mkdir(parents=True)
    (root / "manifest" / "manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    if cur is not None:
        (root / "meta-cursor.json").write_text(json.dumps(cur), encoding="utf-8")
    if sched is not None:
        (root / "scheduler.json").write_text(json.dumps(sched), encoding="utf-8")
    if ledgers is not None:
        (root / "run-ledger.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in ledgers), encoding="utf-8")
    if attempts is not None:
        (root / "coordinator").mkdir()
        (root / "coordinator" / "attempts.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in attempts), encoding="utf-8")


def codes(report):
    return {item["code"] for item in report.data["diagnostics"]}


def test_bvid_only_legacy_manifest_row_remains_checkable(tmp_path: Path):
    row = manifest_row("BVlegacy:p1")
    row.pop("work_id")
    write_fixture(tmp_path, [row])

    report = CoverageReport.build(tmp_path)

    assert report.data["denominator"]["count"] == 1
    assert report.data["rows"][0]["work_id"] == "BVlegacy"
    assert "manifest_invalid_bvid" not in codes(report)


def test_complete_evidence_has_stable_cumulative_and_batch_totals(tmp_path: Path):
    rows = [manifest_row("BVone:p1"), manifest_row("BVtwo:p1")]
    for row in rows:
        path = tmp_path / "transcripts" / "txt" / "BVone.p1.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker", encoding="utf-8")
        break
    write_fixture(tmp_path, rows, cur=cursor(), sched=scheduler(),
                  ledgers=[ledger()], attempts=[attempt("BVone:p1"), attempt("BVtwo:p1")])
    report = CoverageReport.build(tmp_path)
    assert report.data["denominator"] == {"unit": "work_items", "count": 2,
        "state": "available", "source": "manifest_snapshot"}
    assert report.data["cumulative"]["total"] == 2
    assert report.data["batch"]["total"] == 2
    assert report.data["batch"]["complete"] <= 2
    assert [r["work_id"] for r in report.data["rows"]] == ["BVone:p1", "BVtwo:p1"]


@pytest.mark.parametrize("state,code", [("limited", "scheduler_noncomplete"),
                                         ("risk_interrupted", "scheduler_noncomplete")])
def test_limited_and_risk_interrupted_are_preserved(tmp_path: Path, state: str, code: str):
    write_fixture(tmp_path, [manifest_row("BVone:p1")], cur=cursor(state),
                  sched=scheduler(state, ["BVone:p1"]), ledgers=[ledger(["BVone:p1"])])
    report = CoverageReport.build(tmp_path)
    assert report.data["evidence"]["scheduler"]["state"] == "available"
    assert code in codes(report)
    assert report.data["cumulative"]["state"] != "complete"


def test_cumulative_differs_from_latest_batch(tmp_path: Path):
    rows = [manifest_row("BVone:p1"), manifest_row("BVtwo:p1", "meta_ok")]
    write_fixture(tmp_path, rows, cur=cursor(), sched=scheduler(ids=["BVone:p1"]),
                  ledgers=[ledger(["BVone:p1"])])
    report = CoverageReport.build(tmp_path)
    assert report.data["cumulative"]["total"] == 2
    assert report.data["batch"]["total"] == 1


def test_latest_retryable_failed_and_skipped_attempts_diagnose(tmp_path: Path):
    rows = [manifest_row("BVone:p1", "meta_ok"), manifest_row("BVtwo:p1", "meta_ok")]
    attempts = [attempt("BVone:p1", "failed", 1), attempt("BVone:p1", "ok", 2),
                attempt("BVtwo:p1", "skipped", 3)]
    write_fixture(tmp_path, rows, attempts=attempts)
    report = CoverageReport.build(tmp_path)
    assert "retryable_attempt" in codes(report)
    assert report.data["rows"][0]["status"] == "meta_ok"


def test_duplicate_manifest_makes_denominator_unavailable(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1"), manifest_row("BVone:p1")])
    report = CoverageReport.build(tmp_path)
    assert report.data["denominator"]["count"] is None
    assert "manifest_duplicate_work_id" in codes(report)


@pytest.mark.parametrize("name,relative,payload", [
    ("cursor", "meta-cursor.json", "{}"), ("scheduler", "scheduler.json", "{}"),
    ("ledger", "run-ledger.jsonl", "{bad"), ("attempts", "coordinator/attempts.jsonl", "{bad")])
def test_malformed_sidecars_are_named(tmp_path: Path, name: str, relative: str, payload: str):
    write_fixture(tmp_path, [manifest_row("BVone:p1")])
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    report = CoverageReport.build(tmp_path)
    assert "sidecar_malformed" in codes(report)
    assert report.data["denominator"]["state"] == "available"


def test_stale_and_contradictory_sidecar_ids(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")], cur=cursor(),
        sched=scheduler(ids=["BVone:p1", "BVstale:p1"]),
        ledgers=[ledger(["BVother:p1"])])
    report = CoverageReport.build(tmp_path)
    assert {"stale_evidence", "scheduler_ledger_mismatch"} <= codes(report)


def test_attempt_absent_from_manifest_is_diagnostic(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")], attempts=[attempt("BVmissing:p1")])
    assert "attempt_not_in_manifest" in codes(CoverageReport.build(tmp_path))


def test_terminal_archived_without_transcript_is_not_complete(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")])
    report = CoverageReport.build(tmp_path)
    assert "terminal_missing_artifact" in codes(report)
    assert report.data["rows"][0]["cumulative_complete"] is False


def test_reclaimed_audio_uses_page_aware_artifact_path(tmp_path: Path):
    row = manifest_row("BVone:p1")
    transcript = tmp_path / "transcripts" / "txt" / "BVone.p1.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("marker", encoding="utf-8")
    write_fixture(tmp_path, [row])
    report = CoverageReport.build(tmp_path)
    assert report.data["rows"][0]["artifact_present"] is True
    assert report.data["rows"][0]["reclaimed_audio"] is True


@pytest.mark.parametrize("scope,expected", [("pending", {"BVone:p1"}),
    ("failed", {"BVone:p1"}), ("BVone:p1", {"BVone:p1"}), ("BVone", {"BVone:p1"})])
def test_supported_scopes(tmp_path: Path, scope: str, expected: set[str]):
    rows = [manifest_row("BVone:p1", "meta_ok"), manifest_row("BVtwo:p1")]
    write_fixture(tmp_path, rows, attempts=[attempt("BVone:p1", "failed")])
    assert {r["work_id"] for r in CoverageReport.build(tmp_path, scope=scope).data["rows"]} == expected


def test_unknown_scope_is_unavailable(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")])
    report = CoverageReport.build(tmp_path, scope="no-such-work")
    assert report.data["denominator"]["state"] == "unavailable"
    assert "unknown_scope" in codes(report)


def test_json_csv_bytes_and_empty_summary_are_exact(tmp_path: Path):
    write_fixture(tmp_path, [])
    report = CoverageReport.build(tmp_path)
    assert report.to_json().encode() == report.to_json().encode()
    assert report.to_csv().encode() == report.to_csv().encode()
    parsed = list(csv.DictReader(report.to_csv().splitlines()))
    assert len(parsed) == 1 and parsed[0]["category"] == "summary"


def test_all_evidence_bytes_and_mtimes_remain_unchanged(tmp_path: Path):
    files = {}
    write_fixture(tmp_path, [manifest_row("BVone:p1")], cur=cursor(), sched=scheduler(),
                  ledgers=[ledger()], attempts=[attempt("BVone:p1")])
    for path in (tmp_path / "manifest/manifest.jsonl", tmp_path / "meta-cursor.json",
                 tmp_path / "scheduler.json", tmp_path / "run-ledger.jsonl",
                 tmp_path / "coordinator/attempts.jsonl"):
        files[path] = (path.read_bytes(), path.stat().st_mtime_ns)
    CoverageReport.build(tmp_path)
    assert all(path.read_bytes() == data and path.stat().st_mtime_ns == mtime
               for path, (data, mtime) in files.items())


def test_cli_formats_and_status_sentinel(tmp_path: Path, monkeypatch, capsys):
    from bili_asr import cli
    transcript = tmp_path / "transcripts" / "txt" / "BVone.p1.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("marker", encoding="utf-8")
    write_fixture(tmp_path, [manifest_row("BVone:p1")], cur=cursor(),
                  sched=scheduler(ids=["BVone:p1"]), ledgers=[ledger(["BVone:p1"])])
    assert cli.main(["coverage", "--archive-root", str(tmp_path), "--format", "json"]) != 0
    assert json.loads(capsys.readouterr().out)["schema_version"]
    assert cli.main(["coverage", "--archive-root", str(tmp_path), "--format", "csv"]) != 0
    assert "schema_version" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_cmd_status", lambda args: 7)
    assert cli.main(["status", "--archive-root", str(tmp_path)]) == 7


def test_cli_returns_diagnostic_exit(tmp_path: Path):
    from bili_asr import cli
    write_fixture(tmp_path, [manifest_row("BVone:p1"), manifest_row("BVone:p1")])
    assert cli.main(["coverage", "--archive-root", str(tmp_path), "--format", "json"]) != 0
