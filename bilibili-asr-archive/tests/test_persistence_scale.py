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
from bili_asr.persistence import PersistenceError, file_lock, replace_file_atomically
from bili_asr.sidecar_projection import (
    ReaderPolicy,
    iter_jsonl_records,
    project_attempt_records,
    project_manifest_records,
)
from bili_asr.path_policy import confined_audio_file, confined_audio_path



#: The trusted-scale probe builds tens of thousands of manifest/attempt rows and
#: then runs the integrity/coverage readers over them, so it is slow by
#: construction (~100s).  It stays in the suite but runs only when the operator
#: opts in with ``BILI_SCALE=1`` (the same opt-in shape as the live smokes); a
#: default run skips it so the fast unit baseline stays fast.
SCALE_ENV_VAR = "BILI_SCALE"

#: The default-run skip text; the central gate (conftest ``opt_in_gate``) reuses
#: it byte-identically.
_SCALE_SKIP_REASON = f"scale probe is opt-in: set {SCALE_ENV_VAR}=1 to run it"


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


def _child_env() -> dict[str, str]:
    """Environment for spawned children: the tree under test's ``src`` first.

    ``sys.executable`` inherits the venv, whose editable ``.pth`` resolves
    ``bili_asr`` to whatever checkout it was installed from — for a feature
    worktree that is the CONTROL checkout, not the tree under test.  Children
    would then exercise the wrong code and the assertions in this module would
    report a false signal.  Prepending this test file's own ``src`` makes the
    child import exactly the code the parent runs.
    """

    src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}{os.pathsep}{existing}" if existing else src
    return env


def _run_children(tmp_path: Path, script: str, *child_args: tuple[str, ...]) -> None:
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    release = tmp_path / "release"
    env = _child_env()
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
            ],
            env=env,
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


@pytest.mark.scale(skip_reason=_SCALE_SKIP_REASON)
def test_trusted_scale_fixture_exposes_current_record_limits(
    tmp_path: Path, capsys, opt_in_gate
) -> None:
    env_var, _marker = opt_in_gate
    assert env_var == SCALE_ENV_VAR
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

    from bili_asr.cli import main

    assert main(["coverage", "--archive-root", str(tmp_path)]) == 1
    bounded_cli = json.loads(capsys.readouterr().out)
    assert bounded_cli["denominator"]["count"] is None

    assert main([
        "coverage", "--archive-root", str(tmp_path), "--trusted-local",
    ]) == 1
    trusted_cli = json.loads(capsys.readouterr().out)
    assert trusted_cli["denominator"]["count"] == 10001

    # Exit contract §2: every row here is `pending` — backlog, not damage —
    # so the trusted run reaches exit 0 and `--strict` keeps the old gate at 1.
    assert main([
        "verify", "--archive-root", str(tmp_path), "--trusted-local",
    ]) == 0
    trusted_verify = json.loads(capsys.readouterr().out)
    assert trusted_verify["authoritative"] is True
    assert trusted_verify["checked"] == 10001

    assert main([
        "verify", "--archive-root", str(tmp_path), "--trusted-local", "--strict",
    ]) == 1
    capsys.readouterr()

    # Same split on the coverage reader: 10001 in-flight rows, no damage.
    assert main([
        "coverage", "--quality", "--archive-root", str(tmp_path),
        "--trusted-local",
    ]) == 0
    trusted_quality = json.loads(capsys.readouterr().out)
    assert trusted_quality["denominator"]["count"] == 10001
    assert trusted_quality["summary"]["artifact_missing"] == 10001

    assert main([
        "coverage", "--quality", "--archive-root", str(tmp_path),
        "--trusted-local", "--strict",
    ]) == 1
    capsys.readouterr()


@pytest.mark.parametrize(
    "invalid",
    [
        {"work_id": "BVsame:p0", "bvid": "BVsame", "status": "bogus"},
        {"work_id": "BVsame:p0", "bvid": "BVother", "status": "pending"},
    ],
)
def test_invalid_manifest_revision_never_replaces_prior_valid_evidence(
    tmp_path: Path, invalid: dict[str, object]
) -> None:
    manifest = tmp_path / "manifest" / "manifest.jsonl"
    manifest.parent.mkdir()
    prior = _row("BVsame:p0")
    later = _row("BVlater:p0")
    manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in (prior, invalid, later)),
        encoding="utf-8",
    )
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        ManifestStore(tmp_path).load()

    projected, state, diagnostics = project_manifest_records(manifest)
    assert state == "malformed"
    assert projected["BVsame:p0"] == prior
    assert projected["BVlater:p0"] == later
    assert projected["BVsame:p0"]["status"] == "pending"
    assert "manifest_invalid" in diagnostics

    coverage = CoverageReport.build(tmp_path)
    integrity = IntegrityVerifier().verify(tmp_path)
    assert coverage.data["denominator"]["state"] == "unavailable"
    assert integrity.authoritative is False
    assert integrity.checked == 2
    assert {"BVsame:p0", "BVlater:p0"} == {
        defect.work_id
        for defect in integrity.defects
        if defect.code == "retryable_incomplete"
    }


def test_bounded_record_limit_ignores_blank_lines_and_preserves_physical_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text('{"value": 1}\n\n{"value": 2}\n', encoding="utf-8")
    records = list(iter_jsonl_records(path, policy=ReaderPolicy(max_records=2), name="records"))
    assert [(record.line, record.value) for record in records] == [(1, {"value": 1}), (3, {"value": 2})]



#: Failure-injection operations for the manifest snapshot.  ``write`` is not
#: a case since the journal-append rework (plan 003, ``ae88b4e``): a per-row
#: upsert no longer opens ``manifest.jsonl`` for writing (it appends to the
#: journal and compacts lazily), so the write-injection seam has nothing to
#: catch and is removed rather than patched around.
@pytest.mark.parametrize("operation", ["fsync", "replace", "directory_fsync"])
def test_manifest_failure_injection_preserves_unrelated_file(tmp_path: Path, monkeypatch, operation: str) -> None:
    store = ManifestStore(tmp_path)
    store.upsert(_row("prior:p0"))
    # Materialize the snapshot: every operation below targets
    # ``manifest.jsonl`` itself, and a journal-only upsert never writes it.
    store.save()
    marker = tmp_path / "unrelated.txt"
    marker.write_text("keep", encoding="utf-8")
    manifest_path = Path(store.path)
    manifest_before = manifest_path.read_bytes()
    manifest_mtime_before = manifest_path.stat().st_mtime_ns
    directory_fsync_injected = False

    if operation == "fsync":
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


def test_malformed_tail_written_after_construction_fails_closed(tmp_path: Path) -> None:
    """A malformed foreign tail raises on the collision path, not just at seeding.

    The construction-time malformed flag only covers the history read at
    construction.  A corruption that lands after the ledger was built (the
    tail-replay path) must also fail closed before anything is written.
    """

    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("x:p0")) + "\n", encoding="utf-8")
    ledger = AttemptLedger(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{bad}\n")
    with pytest.raises(ValueError, match="malformed attempt history"):
        ledger.append(_attempt("x:p0", 2))
    assert path.read_text(encoding="utf-8") == json.dumps(_attempt("x:p0")) + "\n{bad}\n"


def test_foreign_append_between_construction_read_and_fingerprint_is_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A foreign append landing inside the constructor's window is not lost.

    The window is real: ``__init__`` reads the sidecar and fingerprints its
    size.  When the fingerprint was captured AFTER the read, an append
    landing between the two steps was absorbed into the observed size — the
    next append saw no delta, trusted a stale map, and wrote a duplicate
    attempt number.  Simulated deterministically by performing the foreign
    append on the first ``_file_size`` call (the worst moment: just before
    the fingerprint), which is exactly the interleave the window allows.
    """

    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("same:p0", 1)) + "\n", encoding="utf-8")

    real_file_size = AttemptLedger._file_size
    injected = False

    def racing_file_size(ledger: AttemptLedger) -> int | None:
        nonlocal injected
        if not injected:
            injected = True
            # The concurrent writer's append lands here — after the seeding
            # read, before (old code) / after (fixed code) the fingerprint.
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_attempt("same:p0", 2)) + "\n")
        return real_file_size(ledger)

    monkeypatch.setattr(AttemptLedger, "_file_size", racing_file_size)
    ledger = AttemptLedger(tmp_path)
    stored = ledger.append(_attempt("same:p0", 1))
    monkeypatch.setattr(AttemptLedger, "_file_size", real_file_size)
    assert stored["attempt"] == 3
    numbers = [record["attempt"] for record in AttemptLedger(tmp_path).load()]
    assert numbers == [1, 2, 3]
    assert len(numbers) == len(set(numbers))


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


def test_file_lock_does_not_relabel_body_io_errors(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="body failure") as captured:
        with file_lock(tmp_path / "body-error"):
            raise OSError("body failure")

    assert not isinstance(captured.value, PersistenceError)


def test_archive_writer_does_not_relabel_chained_body_io_errors(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="body failure") as captured:
        with archive_writer(tmp_path):
            try:
                raise BlockingIOError("acquisition-like cause")
            except BlockingIOError as cause:
                raise OSError("body failure") from cause

    assert not isinstance(captured.value, ArchiveBusyError)


def test_archive_writer_preserves_context_manager_exit_behavior(tmp_path: Path, monkeypatch) -> None:
    from contextlib import contextmanager
    import bili_asr.coordinator as coordinator

    seen = []

    @contextmanager
    def suppressing_lock(*_args, **_kwargs):
        try:
            yield
        except RuntimeError as exc:
            seen.append(exc)

    monkeypatch.setattr(coordinator, "file_lock", suppressing_lock)
    with archive_writer(tmp_path):
        raise RuntimeError("body failure")
    assert [str(exc) for exc in seen] == ["body failure"]


def test_windows_file_lock_uses_matching_release_api(tmp_path: Path, monkeypatch) -> None:
    import types
    import bili_asr.persistence as persistence

    calls: list[tuple[int, int]] = []
    fake_msvcrt = types.SimpleNamespace(
        LK_LOCK=1,
        LK_NBLCK=2,
        LK_UNLCK=3,
        locking=lambda _fd, mode, length: calls.append((mode, length)),
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(persistence.os, "name", "nt")

    lock_target = os.fspath(tmp_path / "windows-lock")
    for _ in range(2):
        with file_lock(lock_target):
            pass

    assert calls == [
        (fake_msvcrt.LK_LOCK, 1),
        (fake_msvcrt.LK_UNLCK, 1),
        (fake_msvcrt.LK_LOCK, 1),
        (fake_msvcrt.LK_UNLCK, 1),
    ]
    assert os.path.getsize(lock_target + ".lock") == 1


def test_cli_dispatch_locks_every_archive_mutation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from contextlib import contextmanager
    from bili_asr import cli, coordinator

    assert cli._ARCHIVE_WRITER_COMMANDS == {
        "fetch-meta",
        "recover",
        "asr",
        "pilot",
        "derive-manifest",
        # It writes audio_objects / part_audio_objects, so it is a store-writing
        # command like derive-manifest beside it (added 2026-09-28 with the
        # command itself; the earlier omission made its documented archive_busy
        # refusal unreachable).
        "derive-audio-inventory",
        "adopt-transcripts",
        "publish-transcripts",
        "harvest-subs",
        "download-audio",
        "run",
        "campaign",
        "schedule",
    }
    # ``probe-subs`` reads the SQLite transcript path and writes nothing, so it
    # is a reader like ``status``: no writer lock, no file, no new database.
    assert "probe-subs" not in cli._ARCHIVE_WRITER_COMMANDS

    @contextmanager
    def busy_writer(_root):
        raise ArchiveBusyError()
        yield

    monkeypatch.setattr(coordinator, "archive_writer", busy_writer)
    # status is a read command: it never takes the writer lock, so it
    # succeeds against an existing fresh database while the writer lock
    # stays busy.
    from bili_asr.storage import open_database

    open_database(os.fspath(tmp_path)).close()
    assert cli.main(["status", "--archive-root", os.fspath(tmp_path)]) == 0
    capsys.readouterr()
    assert cli.main([
        "fetch-meta",
        "--mid",
        "23191782",
        "--archive-root",
        os.fspath(tmp_path),
    ]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "fetch-meta: archive_busy\n"
    assert cli.main([
        "adopt-transcripts", "--archive-root", os.fspath(tmp_path),
    ]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "adopt-transcripts: archive_busy\n"


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
    manifest_path = manifest_dir / "manifest.jsonl"
    manifest_path.symlink_to(outside)

    with pytest.raises(OSError):
        ManifestStore(tmp_path).load()
    with pytest.raises(OSError):
        ManifestStore(tmp_path).upsert(_row("inside:p0"))
    assert outside.read_text(encoding="utf-8") == json.dumps(_row("outside:p0")) + "\n"

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
    assert link.is_symlink()
    assert confined_audio_path(tmp_path, "audio/link.m4a", require_exists=True) is None


def test_confined_audio_file_keeps_open_descriptor_across_path_swap(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    original = audio / "swap.m4a"
    outside = tmp_path / "outside.m4a"
    original.write_bytes(b"original")
    outside.write_bytes(b"outside")
    with confined_audio_file(tmp_path, "audio/swap.m4a") as opened:
        original.unlink()
        original.symlink_to(outside)
        assert Path(opened).read_bytes() == b"original"
    assert outside.read_bytes() == b"outside"


@pytest.mark.parametrize("marker_value", [[], None, "marker"])
def test_archive_bundle_complete_rejects_non_object_marker(tmp_path: Path, marker_value) -> None:
    from bili_asr.archive import bundle_marker_path, write_archive, archive_bundle_complete
    row = {"bvid": "BVmarker", "work_id": "BVmarker:p0", "cid": 1, "page_index": 0, "title": "t"}
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "ok"}], source="asr")
    bundle_marker_path(tmp_path / paths["srt_path"]).write_text(json.dumps(marker_value), encoding="ascii")
    assert archive_bundle_complete(tmp_path, paths) is False


def test_write_archive_rejects_symlinked_transcript_directory(tmp_path: Path) -> None:
    from bili_asr.archive import write_archive
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "transcripts").mkdir()
    # Shape A: the work's own directory is what the writer must refuse to follow.
    # Under the four-kind-dir shape the swapped directory was transcripts/srt; the
    # attack surface moved with the layout, so the assertion has to move with it.
    (tmp_path / "transcripts" / "BVdir.p0").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        write_archive(tmp_path, {"bvid": "BVdir", "work_id": "BVdir:p0", "cid": 1}, [], source="asr")


def test_write_archive_rejects_destination_symlink_swap(tmp_path: Path) -> None:
    from bili_asr import archive
    row = {"bvid": "BVswap", "work_id": "BVswap:p0", "cid": 1, "page_index": 0}
    outside = tmp_path / "outside.srt"
    outside.write_text("keep", encoding="utf-8")
    target = tmp_path / "transcripts" / "BVswap.p0" / "bundle.srt"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    paths = archive.write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "x"}], source="asr")
    assert outside.read_text(encoding="utf-8") == "keep"
    assert archive.archive_bundle_complete(tmp_path, paths)


def test_valid_journal_with_fingerprint_inside_a_record_is_not_accused(tmp_path: Path) -> None:
    """A fingerprint landing mid-record must not accuse a valid journal (QC C1).

    The size fingerprint is taken without the flock, so it can land inside a
    record or inside a multi-byte character.  The replay must snap to the last
    record boundary; otherwise it parses a fragment and latches the instance
    against every later append (base and pre-006 accept the same bytes).
    """

    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    first, second = _attempt("same:p0", 1), _attempt("same:p0", 2)
    blob = json.dumps(first) + "\n" + json.dumps(second) + "\n"
    path.write_text(blob, encoding="utf-8")
    ledger = AttemptLedger(tmp_path)
    ledger._last_seen_size = len(json.dumps(first).encode("utf-8")) // 2
    stored = ledger.append(_attempt("same:p0", 1))
    assert stored["attempt"] == 3
    assert [r["attempt"] for r in AttemptLedger(tmp_path).load()] == [1, 2, 3]


def test_valid_journal_with_u2028_in_a_detail_is_not_accused(tmp_path: Path) -> None:
    """U+2028 inside a JSON string is legal and must not split a journal line.

    ``str.splitlines()`` breaks on U+2028/U+2029/U+0085; the repo's own writer
    emits them raw (``ensure_ascii=False``), so a replay that splits on them
    accuses a VALID FOREIGN TAIL and latches the instance.  The U+2028-bearing
    record is the foreign append, so the replayed tail is what carries it.
    """

    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("u:p0", 1)) + "\n", encoding="utf-8")
    ledger = AttemptLedger(tmp_path)
    foreign = _attempt("u:p0", 2)
    foreign["error_code"] = "E\u2028X"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(foreign, ensure_ascii=False) + "\n")
    stored = ledger.append(_attempt("u:p0", 1))
    assert stored["attempt"] == 3
    assert [r["attempt"] for r in AttemptLedger(tmp_path).load()] == [1, 2, 3]


def test_invalid_bytes_in_tail_fail_closed(tmp_path: Path) -> None:
    """A tail carrying invalid UTF-8 is corruption, not a substitution surface.

    ``errors="replace"`` would let the mutated line pass strict validation with
    the bad byte silently rewritten to U+FFFD — and, when the byte sits in
    ``work_id``, silently change the map key.  The tail must decode strictly.
    """

    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("c:p0", 1)) + "\n", encoding="utf-8")
    ledger = AttemptLedger(tmp_path)
    # A lone 0xFF inside the foreign record's work_id: substitution would make
    # it a valid (but wrong) key instead of corruption.
    line = json.dumps(_attempt("c:p0", 2)).encode("utf-8").replace(b'"c:p0"', b'"c\xff:p0"', 1)
    with path.open("ab") as fh:
        fh.write(line + b"\n")
    with pytest.raises(ValueError, match="malformed attempt history"):
        ledger.append(_attempt("c:p0", 1))


def test_torn_tail_does_not_latch_the_instance_after_healing(tmp_path: Path) -> None:
    """A transient torn tail heals; the instance must recover (QC W2).

    Pre-006 re-validated per append, so a healed journal recovered.  A
    lifetime latch would leave the run unable to record any later evidence.
    """

    path = tmp_path / "coordinator" / "attempts.jsonl"
    path.parent.mkdir()
    path.write_text(json.dumps(_attempt("t:p0", 1)) + "\n", encoding="utf-8")
    ledger = AttemptLedger(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"stage":"archive","work_id":"t:p0","att')  # torn record
    with pytest.raises(ValueError, match="malformed attempt history"):
        ledger.append(_attempt("t:p0", 2))
    # The foreign writer finishes its record: the journal is valid again.
    with path.open("a", encoding="utf-8") as fh:
        fh.write('empt":2,"outcome":"ok","error_code":null,"artifact_paths":[],'
                 '"started_at":"2026-08-31T00:00:00Z","finished_at":"2026-08-31T00:00:01Z"}\n')
    stored = ledger.append(_attempt("t:p0", 1))
    assert stored["attempt"] == 3
    assert [r["attempt"] for r in AttemptLedger(tmp_path).load()] == [1, 2, 3]


def test_deleted_journal_self_heals_like_base(tmp_path: Path) -> None:
    """A journal deleted between appends must not fail the writer.

    Base performed no read on append, so a deleted sidecar (external cleanup /
    integrity recovery) simply got recreated; the tail-replay path must treat
    it as absent-on-disk rather than raising, and must agree with integrity.py
    (which classes a missing sidecar as valid).
    """

    path = tmp_path / "coordinator" / "attempts.jsonl"
    ledger = AttemptLedger(tmp_path)
    first = ledger.append(_attempt("d:p0", 1))
    assert first["attempt"] == 1
    path.unlink()
    second = ledger.append(_attempt("d:p0", 2))
    assert second["attempt"] == 2
    assert path.exists()
    assert AttemptLedger(tmp_path).load() == [_attempt("d:p0", 2)]
