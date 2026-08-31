"""Task 1 persistence characterization: local scale, crash, and isolation probes.

These tests intentionally describe the current behavior and expose races that
later tasks are expected to fix.  All inputs are synthetic and local-only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bili_asr.coverage_report import CoverageReport
from bili_asr.integrity import IntegrityVerifier, STRUCTURAL_INPUT_ERROR
from bili_asr.manifest import ManifestStore
from bili_asr.coordinator import AttemptLedger


ROOT = Path(__file__).resolve().parents[1]


def _row(work_id: str, status: str = "pending") -> dict[str, object]:
    bvid = work_id.split(":", 1)[0]
    return {
        "work_id": work_id,
        "bvid": bvid,
        "page_index": 0,
        "cid": 1,
        "page_label": "p0",
        "title": "synthetic",
        "status": status,
    }


def _attempt(work_id: str, number: int = 1, *, stage: str = "archive") -> dict[str, object]:
    return {
        "stage": stage,
        "work_id": work_id,
        "attempt": number,
        "outcome": "ok",
        "error_code": None,
        "artifact_paths": [],
        "started_at": "2026-08-31T00:00:00Z",
        "finished_at": "2026-08-31T00:00:01Z",
    }


def test_two_process_manifest_disjoint_writes_are_not_lost(tmp_path: Path) -> None:
    script = """
import sys
from bili_asr.manifest import ManifestStore
root = sys.argv[1]
store = ManifestStore(root)
store.upsert({"work_id": sys.argv[2], "bvid": sys.argv[2].split(":")[0], "status": "pending"})
"""
    first = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), "BVA:p0"])
    second = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), "BVB:p0"])
    assert first.wait() == 0
    assert second.wait() == 0
    assert set(ManifestStore(tmp_path).load()) == {"BVA:p0", "BVB:p0"}


def test_two_process_manifest_same_key_has_one_valid_revision(tmp_path: Path) -> None:
    script = """
import sys
from bili_asr.manifest import ManifestStore
root = sys.argv[1]
store = ManifestStore(root)
store.upsert({"work_id": "same:p0", "bvid": "same", "title": sys.argv[2], "status": "pending"})
"""
    first = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), "first"])
    second = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), "second"])
    assert first.wait() == 0
    assert second.wait() == 0
    loaded = ManifestStore(tmp_path).load()
    assert list(loaded) == ["same:p0"]
    assert loaded["same:p0"]["title"] in {"first", "second"}


def test_two_process_ledger_disjoint_appends_are_not_lost(tmp_path: Path) -> None:
    script = """
import sys
from bili_asr.coordinator import AttemptLedger
ledger = AttemptLedger(sys.argv[1])
ledger.append({"stage": "archive", "work_id": sys.argv[2], "attempt": 1,
 "outcome": "ok", "error_code": None, "artifact_paths": [],
 "started_at": "2026-08-31T00:00:00Z", "finished_at": "2026-08-31T00:00:01Z"})
"""
    first = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), "BVA:p0"])
    second = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), "BVB:p0"])
    assert first.wait() == 0
    assert second.wait() == 0
    assert {record["work_id"] for record in AttemptLedger(tmp_path).load()} == {"BVA:p0", "BVB:p0"}


def test_two_process_same_attempt_key_numbers_do_not_conflict(tmp_path: Path) -> None:
    script = """
import sys
from bili_asr.coordinator import AttemptLedger
ledger = AttemptLedger(sys.argv[1])
ledger.append({"stage": "archive", "work_id": "same:p0", "attempt": 1,
 "outcome": "ok", "error_code": None, "artifact_paths": [],
 "started_at": "2026-08-31T00:00:00Z", "finished_at": "2026-08-31T00:00:01Z"})
"""
    first = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)])
    second = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)])
    assert first.wait() == 0
    assert second.wait() == 0
    numbers = [record["attempt"] for record in AttemptLedger(tmp_path).load()]
    assert sorted(numbers) == [1, 2]


def test_trusted_scale_fixture_exposes_current_record_limits(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest" / "manifest.jsonl"
    manifest.parent.mkdir()
    manifest.write_text("".join(json.dumps(_row(f"BV{i}:p0")) + "\n" for i in range(10001)), encoding="utf-8")
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text("".join(json.dumps(_attempt(f"BV{i}:p0")) + "\n" for i in range(40001)), encoding="utf-8")
    integrity = IntegrityVerifier().verify(tmp_path)
    coverage = CoverageReport.build(tmp_path)
    assert integrity.authoritative is False
    assert "manifest_row_limit_exceeded" in integrity.diagnostics
    assert any(item["code"] == "sidecar_record_limit" for item in coverage.data["diagnostics"])


@pytest.mark.parametrize("operation", ["write", "fsync", "replace", "directory_fsync"])
def test_manifest_failure_injection_preserves_unrelated_file(tmp_path: Path, monkeypatch, operation: str) -> None:
    store = ManifestStore(tmp_path)
    store.upsert(_row("prior:p0"))
    marker = tmp_path / "unrelated.txt"
    marker.write_text("keep", encoding="utf-8")
    manifest_before = store.path and Path(store.path).read_bytes()

    if operation == "write":
        original = open
        def fail_open(path, *args, **kwargs):
            if str(path).endswith("manifest.jsonl.tmp"):
                raise OSError("injected write")
            return original(path, *args, **kwargs)
        monkeypatch.setattr("builtins.open", fail_open)
    elif operation == "fsync":
        monkeypatch.setattr("bili_asr.manifest.os.fsync", lambda _fd: (_ for _ in ()).throw(OSError("injected fsync")))
    elif operation == "replace":
        monkeypatch.setattr("bili_asr.manifest.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("injected replace")))
    else:
        pytest.skip("manifest has no parent-directory fsync hook in baseline")

    with pytest.raises(OSError):
        store.upsert(_row("new:p0"))
    assert Path(store.path).read_bytes() == manifest_before
    assert marker.read_text(encoding="utf-8") == "keep"


def test_malformed_middle_and_truncated_final_lines_are_structural(tmp_path: Path) -> None:
    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("x:p0")) + "\n{bad}\n{truncated", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert STRUCTURAL_INPUT_ERROR in report.diagnostics


def test_invalid_utf8_and_redaction_never_serialize_sensitive_context(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest" / "manifest.jsonl"
    manifest.parent.mkdir()
    manifest.write_bytes(b"\xff\xfe")
    report = IntegrityVerifier().verify(tmp_path)
    payload = json.dumps(report.to_dict())
    assert STRUCTURAL_INPUT_ERROR in report.diagnostics
    for marker in ("SESSDATA", "https://", "Traceback", str(tmp_path)):
        assert marker not in payload


def test_symlinked_manifest_and_duplicate_journal_are_not_authoritative(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps(_row("outside:p0")) + "\n", encoding="utf-8")
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.jsonl").symlink_to(outside)
    report = IntegrityVerifier().verify(tmp_path)
    assert report.authoritative is False
    assert STRUCTURAL_INPUT_ERROR in report.diagnostics

    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir(exist_ok=True)
    attempts.write_text(json.dumps(_attempt("outside:p0")) + "\n" + json.dumps(_attempt("outside:p0")) + "\n", encoding="utf-8")
    assert "duplicate_attempt" in {item["code"] for item in CoverageReport.build(tmp_path).data["diagnostics"]}
