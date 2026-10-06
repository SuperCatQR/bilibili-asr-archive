"""Pin coverage to the effective manifest projection rather than old readers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr.archive import write_archive
from bili_asr.coverage_report import CoverageReport
from bili_asr.manifest import ManifestStore
from bili_asr.sidecar_projection import ReaderPolicy, project_manifest_records


def _row(status: str) -> dict:
    return {
        "work_id": "BVcoverage:p0", "bvid": "BVcoverage", "page_index": 0,
        "cid": 101, "title": "Projection", "status": status, "duration_s": 1,
    }


def _write_snapshot(root: Path, rows: list[dict]) -> Path:
    path = root / "manifest" / "manifest.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _archive_latest(root: Path, *, snapshot: bool) -> Path:
    path = root / "manifest" / "manifest.jsonl"
    if snapshot:
        _write_snapshot(root, [_row("needs_audio"), _row("audio_ok")])
    row = {
        **_row("archived"), "source": "asr", "archive_producer": "stage-cli",
    }
    row.update(write_archive(
        root, row, [{"start": 0, "end": 1, "text": "latest transcript"}], source="asr",
    ))
    store = ManifestStore(root)
    store.load()
    store.upsert(row)
    return path


@pytest.mark.parametrize("snapshot", [True, False])
def test_coverage_uses_latest_journal_row_and_preserves_evidence(tmp_path: Path, snapshot: bool):
    path = _archive_latest(tmp_path, snapshot=snapshot)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    entries, state, _ = project_manifest_records(path)

    report = CoverageReport.build(tmp_path)

    assert state == "available"
    assert report.data["denominator"]["count"] == len(entries) == 1
    assert report.data["rows"][0]["status"] == entries["BVcoverage:p0"]["status"] == "archived"
    assert report.data["rows"][0]["artifact_present"] is True
    assert report.data["cumulative"]["state"] == "complete"
    assert report.data["diagnostics"] == []
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_invalid_journal_row_cannot_hide_behind_ordinary_snapshot_history(tmp_path: Path):
    path = _archive_latest(tmp_path, snapshot=True)
    journal = path.with_name("manifest.journal.jsonl")
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_row("invalid-status")) + "\n")
    _entries, state, diagnostics = project_manifest_records(path)

    report = CoverageReport.build(tmp_path)

    assert state == "malformed"
    assert "manifest_invalid" in diagnostics
    assert report.data["denominator"]["state"] == "unavailable"
    codes = {item["code"] for item in report.data["diagnostics"]}
    assert {"manifest_invalid", "manifest_invalid_status"} <= codes
    assert "manifest_duplicate_work_id" not in codes


def test_report_honors_shared_projection_record_limit(tmp_path: Path):
    _write_snapshot(tmp_path, [_row("needs_audio"), _row("audio_ok")])

    report = CoverageReport.build(tmp_path, policy=ReaderPolicy(max_records=1))

    assert report.data["denominator"]["state"] == "unavailable"
    assert {item["code"] for item in report.data["diagnostics"]} == {"sidecar_record_limit"}
