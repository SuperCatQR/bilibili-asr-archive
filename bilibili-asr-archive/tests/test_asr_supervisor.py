"""Process-bound ASR deadline and lock-ownership tests."""

from __future__ import annotations

import sys
import time

import pytest

from bili_asr.coordinator import archive_writer
from bili_asr.services import asr_supervisor as service
from bili_asr.storage.database import open_database


def _injected_worker(monkeypatch, code: str) -> None:
    monkeypatch.setattr(
        service,
        "_command",
        lambda port, token, argv: [sys.executable, "-c", code, str(port), token, *argv],
    )


def test_stalled_inference_is_killed_within_deadline(monkeypatch, capfd):
    code = (
        "import socket,sys,time; "
        "s=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); "
        "s.sendall(sys.argv[2].encode()+b'\\nD\\n'); time.sleep(60)"
    )
    _injected_worker(monkeypatch, code)
    started = time.monotonic()
    assert service.supervise_asr([], timeout_seconds=0.2) == 1
    assert time.monotonic() - started < 3
    assert "inference deadline exceeded" in capfd.readouterr().err


def test_worker_heartbeat_extends_deadline(monkeypatch, capfd):
    code = (
        "import socket,sys,time; "
        "s=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); "
        "s.sendall(sys.argv[2].encode()+b'\\nD\\n'); time.sleep(.12); "
        "s.sendall(b'A\\n'); time.sleep(.12)"
    )
    _injected_worker(monkeypatch, code)
    assert service.supervise_asr([], timeout_seconds=0.2) == 0
    assert capfd.readouterr().err == ""


def test_timeout_does_not_leave_the_worker_archive_lock_held(
    tmp_path, monkeypatch, capfd
):
    code = (
        "import socket,sys,time; "
        "from bili_asr.coordinator import archive_writer; "
        "s=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); "
        "s.sendall(sys.argv[2].encode()+b'\\nD\\n'); "
        "with archive_writer(sys.argv[3]): time.sleep(60)"
    )
    _injected_worker(monkeypatch, code)
    assert service.supervise_asr([str(tmp_path)], timeout_seconds=0.2) == 1
    capfd.readouterr()
    with archive_writer(tmp_path):
        pass


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "bad"])
def test_invalid_environment_deadline_is_refused(monkeypatch, value, capfd):
    monkeypatch.setenv(service.ASR_TIMEOUT_ENV_VAR, value)
    assert service.supervise_asr([]) == 1
    assert "finite and positive" in capfd.readouterr().err


def test_worker_failure_returns_nonzero(monkeypatch):
    code = "raise SystemExit(7)"
    _injected_worker(monkeypatch, code)
    assert service.supervise_asr([], timeout_seconds=1) == 7


def test_timeout_recovery_finishes_run_and_records_retryable_failure(tmp_path, capfd):
    connection = open_database(tmp_path)
    connection.execute(
        "INSERT INTO bilibili_users(mid, display_name, created_at, updated_at) "
        "VALUES (23191782, '未明子', 1, 1)"
    )
    connection.execute(
        "INSERT INTO videos(bvid, aid, mid, title, pubdate, created_at, updated_at) "
        "VALUES ('BVtimeout', 1, 23191782, '视频', 1, 1, 1)"
    )
    part = connection.execute(
        "INSERT INTO video_parts(bvid, page_index, cid, title, duration_ms, "
        "processing_status, created_at, updated_at) "
        "VALUES ('BVtimeout', 0, 2, '第一段', 1000, 'discovered', 1, 1)"
    ).lastrowid
    connection.execute(
        "INSERT INTO acquisition_runs(run_id, kind, selector_kind, selector_target, "
        "requested_limit, credential_present, started_at, finished_at, outcome) "
        "VALUES ('asr-timeout', 'asr', 'pending', NULL, NULL, 0, 1, NULL, 'running')"
    )
    connection.commit()
    connection.close()

    service._finalize_timed_out_run(tmp_path, "asr-timeout", int(part))
    service._finalize_timed_out_run(tmp_path, "asr-timeout", int(part))

    connection = open_database(tmp_path)
    run = connection.execute(
        "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = 'asr-timeout'"
    ).fetchone()
    attempt = connection.execute(
        "SELECT outcome, error_code FROM acquisition_attempts "
        "WHERE run_id = 'asr-timeout' AND video_part_id = ?",
        (part,),
    ).fetchone()
    assert run["outcome"] == "failed"
    assert run["finished_at"] is not None
    assert (attempt["outcome"], attempt["error_code"]) == (
        "failed",
        "inference_timeout",
    )
    assert capfd.readouterr().err == ""
    connection.close()
