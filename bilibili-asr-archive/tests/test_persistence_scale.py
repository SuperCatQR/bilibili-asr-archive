"""Task 1 persistence characterization: local scale, crash, and isolation probes.

These tests intentionally describe the current behavior and expose races that
later tasks are expected to fix.  All inputs are synthetic and local-only.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bili_asr.coverage_report import CoverageReport
from bili_asr.integrity import IntegrityVerifier, STRUCTURAL_INPUT_ERROR
from bili_asr.manifest import ManifestStore
from bili_asr.coordinator import AttemptLedger, ArchiveBusyError, archive_writer
from bili_asr.persistence import replace_file_atomically
from bili_asr.sidecar_projection import ReaderPolicy, iter_jsonl_records, project_attempt_records
from bili_asr.path_policy import confined_audio_path



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


def _run_children(tmp_path: Path, script: str, *child_args: tuple[str, ...]) -> None:
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    release = tmp_path / "release"
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path),
                str(ready_dir / f"{i}.ready"),
                str(release),
                *args_for_child,
            ]
        )
        for i, args_for_child in enumerate(child_args)
    ]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(list(ready_dir.glob("*.ready"))) < len(processes):
        time.sleep(0.01)
    assert len(list(ready_dir.glob("*.ready"))) == len(processes)
    release.touch()
    for process in processes:
        try:
            assert process.wait(timeout=5) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_two_process_manifest_disjoint_writes_are_not_lost(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from bili_asr.manifest import ManifestStore
root, ready, release, work_id = sys.argv[1:]
Path(ready).touch()
while not Path(release).exists():
    pass
store = ManifestStore(root)
store.upsert({"work_id": work_id, "bvid": work_id.split(":")[0], "status": "pending"})
"""
    _run_children(tmp_path, script, ("BVA:p0",), ("BVB:p0",))
    assert set(ManifestStore(tmp_path).load()) == {"BVA:p0", "BVB:p0"}


def test_two_process_manifest_same_key_has_one_valid_revision(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from bili_asr.manifest import ManifestStore
root, ready, release, title = sys.argv[1:]
Path(ready).touch()
while not Path(release).exists():
    pass
store = ManifestStore(root)
store.upsert({"work_id": "same:p0", "bvid": "same", "title": title, "status": "pending"})
"""
    _run_children(tmp_path, script, ("first",), ("second",))
    loaded = ManifestStore(tmp_path).load()
    assert list(loaded) == ["same:p0"]
    assert loaded["same:p0"]["title"] in {"first", "second"}


def test_two_process_ledger_disjoint_appends_are_not_lost(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from bili_asr.coordinator import AttemptLedger
root, ready, release, work_id = sys.argv[1:]
Path(ready).touch()
while not Path(release).exists():
    pass
AttemptLedger(root).append({"stage": "archive", "work_id": work_id, "attempt": 1,
 "outcome": "ok", "error_code": None, "artifact_paths": [],
 "started_at": "2026-08-31T00:00:00Z", "finished_at": "2026-08-31T00:00:01Z"})
"""
    _run_children(tmp_path, script, ("BVA:p0",), ("BVB:p0",))
    assert {record["work_id"] for record in AttemptLedger(tmp_path).load()} == {"BVA:p0", "BVB:p0"}


def test_two_process_same_attempt_key_numbers_do_not_conflict(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from bili_asr.coordinator import AttemptLedger
root, ready, release = sys.argv[1:]
Path(ready).touch()
while not Path(release).exists():
    pass
AttemptLedger(root).append({"stage": "archive", "work_id": "same:p0", "attempt": 1,
 "outcome": "ok", "error_code": None, "artifact_paths": [],
 "started_at": "2026-08-31T00:00:00Z", "finished_at": "2026-08-31T00:00:01Z"})
"""
    _run_children(tmp_path, script, (), ())
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
    trusted_integrity = IntegrityVerifier().verify(tmp_path, policy=ReaderPolicy(mode="trusted_archive"))
    trusted_coverage = CoverageReport.build(tmp_path, policy=ReaderPolicy(mode="trusted_archive"))
    assert trusted_integrity.authoritative is True
    assert trusted_coverage.data["denominator"]["count"] == 10001
    projected_attempts, attempts_state, attempts_diagnostics = project_attempt_records(
        attempts, policy=ReaderPolicy(mode="trusted_archive")
    )
    assert attempts_state == "available"
    assert attempts_diagnostics == set()
    assert len(projected_attempts) == 40001
    assert projected_attempts[-1]["work_id"] == "BV40000:p0"
    assert len(trusted_coverage.data["rows"]) == 10001
    assert {row["work_id"] for row in trusted_coverage.data["rows"]} == {
        f"BV{i}:p0" for i in range(10001)
    }


def test_bounded_record_limit_ignores_blank_lines_and_preserves_physical_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('{"value": 1}\n\n{"value": 2}\n', encoding="utf-8")
    records = list(iter_jsonl_records(path, policy=ReaderPolicy(max_records=2), name="records"))
    assert [(record.line, record.value) for record in records] == [(1, {"value": 1}), (3, {"value": 2})]



@pytest.mark.parametrize("operation", ["write", "fsync", "replace", "directory_fsync"])
def test_manifest_failure_injection_preserves_unrelated_file(tmp_path: Path, monkeypatch, operation: str) -> None:
    store = ManifestStore(tmp_path)
    store.upsert(_row("prior:p0"))
    marker = tmp_path / "unrelated.txt"
    marker.write_text("keep", encoding="utf-8")
    manifest_path = Path(store.path)
    manifest_before = manifest_path.read_bytes()
    manifest_mtime_before = manifest_path.stat().st_mtime_ns
    directory_fsync_injected = False

    if operation == "write":
        original = open
        def fail_open(path, *args, **kwargs):
            if str(path).endswith("manifest.jsonl") and "ab" in args:
                raise OSError("injected write")
            return original(path, *args, **kwargs)
        monkeypatch.setattr("builtins.open", fail_open)
    elif operation == "fsync":
        original_fsync = os.fsync
        def fail_file_fsync(fd):
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected fsync")
            original_fsync(fd)
        monkeypatch.setattr("bili_asr.manifest.os.fsync", fail_file_fsync)
    elif operation == "replace":
        monkeypatch.setattr("bili_asr.manifest.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("injected replace")))
    else:
        original_fsync = os.fsync
        def fail_directory_fsync(fd: int) -> None:
            nonlocal directory_fsync_injected
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                directory_fsync_injected = True
                raise OSError("injected directory fsync")
            original_fsync(fd)
        monkeypatch.setattr("bili_asr.manifest.os.fsync", fail_directory_fsync)

    with pytest.raises(OSError):
        if operation == "write":
            store.upsert(_row("new:p0"))
        else:
            replace_file_atomically(manifest_path, b"new\n")
    if operation == "directory_fsync":
        assert directory_fsync_injected
    assert manifest_path.read_bytes() == manifest_before
    assert manifest_path.stat().st_mtime_ns == manifest_mtime_before
    assert marker.read_text(encoding="utf-8") == "keep"


def test_malformed_attempt_history_fails_closed_for_authoritative_append(tmp_path: Path) -> None:
    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("x:p0")) + "\n{bad}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed attempt history"):
        AttemptLedger(tmp_path).append(_attempt("x:p0", 2))


def test_public_attempt_load_keeps_valid_records_with_malformed_history(tmp_path: Path) -> None:
    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("x:p0")) + "\n{bad}\n", encoding="utf-8")
    assert AttemptLedger(tmp_path).load() == [_attempt("x:p0")]


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


def test_archive_writer_reenters_same_thread_without_second_lock(tmp_path: Path, monkeypatch) -> None:
    calls = []
    import bili_asr.coordinator as coordinator
    real_lock = coordinator.file_lock

    def tracked_lock(path, **kwargs):
        calls.append(path)
        return real_lock(path, **kwargs)

    monkeypatch.setattr(coordinator, "file_lock", tracked_lock)
    with archive_writer(tmp_path):
        with archive_writer(tmp_path):
            pass
    assert len(calls) == 1


def test_archive_writer_rejects_cross_thread_overlap(tmp_path: Path) -> None:
    import threading
    entered = threading.Event()
    release = threading.Event()
    def owner():
        with archive_writer(tmp_path):
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=owner)
    thread.start()
    assert entered.wait(timeout=2)
    try:
        with pytest.raises(ArchiveBusyError):
            with archive_writer(tmp_path):
                pass
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


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


def test_confined_audio_path_rejects_invalid_and_accepts_valid(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    valid = audio / "ok.m4a"
    valid.write_bytes(b"audio")
    assert confined_audio_path(tmp_path, "audio/ok.m4a", require_exists=True) == valid
    assert confined_audio_path(tmp_path, "/tmp/ok.m4a", require_exists=True) is None
    assert confined_audio_path(tmp_path, "audio/../secret.m4a", require_exists=True) is None
    assert confined_audio_path(tmp_path, "audio/ok.wav", require_exists=True) is None
    assert confined_audio_path(tmp_path, "audio/missing.m4a", require_exists=True) is None
    directory = audio / "dir.m4a"
    directory.mkdir()
    assert confined_audio_path(tmp_path, "audio/dir.m4a", require_exists=True) is None
    outside = tmp_path / "outside.m4a"
    outside.write_bytes(b"outside")
    link = audio / "link.m4a"
    link.symlink_to(outside)
    assert confined_audio_path(tmp_path, "audio/link.m4a", require_exists=True) is None
