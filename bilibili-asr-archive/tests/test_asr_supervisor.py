"""Process-bound ASR deadline and lock-ownership tests."""

from __future__ import annotations

import sys
import time

import pytest

from bili_asr.coordinator import archive_writer
from bili_asr.services import asr_supervisor as service


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
        "s.sendall(sys.argv[2].encode()+b'\\nD'); time.sleep(60)"
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
        "s.sendall(sys.argv[2].encode()+b'\\nD'); time.sleep(.12); "
        "s.sendall(b'A'); time.sleep(.12)"
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
        "s.sendall(sys.argv[2].encode()+b'\\nD'); "
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
