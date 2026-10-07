"""Actual process supervision, phase deadlines and writer-owned locking."""
import importlib
import sys
import time

import pytest

from bili_asr.cli import main
from bili_asr.coordinator import archive_writer
from bili_asr.manifest import ManifestStore
from bili_asr.services import publication_supervisor as service
from test_cli_publish_transcripts import _seed_archive, _store_caption, FRESH_BVID


def _argv(root, timeout="5"):
    return ["publish-transcripts", "--archive-root", root,
            "--io-timeout-seconds", timeout]


def _injected_worker(monkeypatch, code):
    # Faults are installed inside a real exec child, never assumed to cross fork.
    monkeypatch.setattr(service, "_command", lambda port, token, argv: [
        sys.executable, "-c", code, str(port), token, *argv,
    ])


def test_real_worker_publishes_and_preserves_output(tmp_root, capfd):
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    assert main(_argv(tmp_root)) == 0
    output = capfd.readouterr()
    assert f"{FRESH_BVID}:p0: published" in output.out
    assert "candidates=1 published=1" in output.out
    assert ManifestStore(root=tmp_root).load()[f"{FRESH_BVID}:p0"]["status"] == "archived"


@pytest.mark.parametrize("phase", ["setup", "candidate", "final"])
def test_real_stalled_io_returns_within_deadline(tmp_root, monkeypatch, capfd, phase):
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    code = "import importlib,time; from bili_asr.services import publication_supervisor as s; "
    if phase == "setup":
        code += "m=importlib.import_module('bili_asr.cli.main'); m.roots_for=lambda *a,**kw: time.sleep(60); "
    elif phase == "candidate":
        code += "from bili_asr import archive; archive.write_archive=lambda *a,**kw: time.sleep(60); "
    else:
        code += "from bili_asr.manifest import ManifestStore; ManifestStore.save=lambda *a,**kw: time.sleep(60); "
    code += "raise SystemExit(s._worker())"
    _injected_worker(monkeypatch, code)
    started = time.monotonic()
    assert main(_argv(tmp_root, "0.7")) == 1
    assert time.monotonic() - started < 3
    assert "publication I/O deadline exceeded" in capfd.readouterr().err
    # A normally killable worker is reaped; only it ever owned this lock.
    with archive_writer(tmp_root):
        pass


def test_candidate_phase_resets_deadline_but_stdout_does_not(tmp_root, monkeypatch, capfd):
    code = (
        "import socket,sys,time; "
        "s=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); "
        "s.sendall(sys.argv[2].encode()+b'\\n'); "
        "time.sleep(.3); s.sendall(b'C'); time.sleep(.3); s.sendall(b'C'); "
        "time.sleep(.3); print('complete',flush=True)"
    )
    _injected_worker(monkeypatch, code)
    assert main(_argv(tmp_root, "0.5")) == 0
    assert "complete" in capfd.readouterr().out
    code = "import time\nfor i in range(100):\n print('ordinary output',flush=True)\n time.sleep(.05)"
    _injected_worker(monkeypatch, code)
    started = time.monotonic()
    assert main(_argv(tmp_root, "0.4")) == 1
    assert time.monotonic() - started < 2
    assert "deadline exceeded" in capfd.readouterr().err


def test_real_worker_respects_another_writer_lock(tmp_root, capfd):
    _seed_archive(tmp_root)
    with archive_writer(tmp_root):
        assert main(_argv(tmp_root)) == 1
    assert "archive_busy" in capfd.readouterr().err


def test_parent_does_not_resolve_roots_or_own_worker_lock(tmp_root, monkeypatch, capfd):
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    main_module = importlib.import_module("bili_asr.cli.main")
    monkeypatch.setattr(main_module, "roots_for", lambda *a, **kw: pytest.fail("parent resolved roots"))
    assert main(_argv(tmp_root)) == 0
    assert "published" in capfd.readouterr().out


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_invalid_deadline_is_refused_before_worker(tmp_root, timeout, capsys):
    assert main(_argv(tmp_root, timeout)) == 1
    assert "finite and positive" in capsys.readouterr().err


@pytest.mark.parametrize("phases", ["FF", "FC", "X"])
def test_invalid_phase_protocol_stops_worker(tmp_root, monkeypatch, capfd, phases):
    code = (
        "import socket,sys,time; "
        "s=socket.create_connection(('127.0.0.1',int(sys.argv[1]))); "
        "s.sendall(sys.argv[2].encode()+b'\\n'+" + repr(phases.encode()) + "); "
        "time.sleep(60)"
    )
    _injected_worker(monkeypatch, code)
    assert main(_argv(tmp_root)) == 1
    output = capfd.readouterr()
    assert "publication supervisor failed" in output.err
    assert "Traceback" not in output.err


def test_unreapable_worker_keeps_ownership_and_cleanup_is_bounded(monkeypatch, capfd):
    import subprocess
    class Stuck:
        pid = 123456789
        def poll(self):
            return None
        def kill(self):
            pass
        def wait(self, timeout):
            assert timeout <= .2
            raise subprocess.TimeoutExpired("stuck", timeout)
    worker = Stuck()
    monkeypatch.setattr(service, "_UNREAPED", [])
    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **kw: worker)
    monkeypatch.setattr(service.os, "killpg", lambda *a: None, raising=False)
    assert service.supervise_publication([], timeout_seconds=.02) == 1
    assert worker in service._UNREAPED
    assert "worker-owned locks may remain" in capfd.readouterr().err


def test_windows_missing_tree_killer_still_kills_worker(monkeypatch):
    calls = []
    class Worker:
        pid = 123
        def kill(self):
            calls.append("kill")
        def wait(self, timeout):
            calls.append("wait")
    monkeypatch.setattr(service.os, "name", "nt")
    monkeypatch.setattr(service.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    def unavailable(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(service.subprocess, "Popen", unavailable)
    service._terminate(Worker())
    assert calls == ["kill", "wait"]
