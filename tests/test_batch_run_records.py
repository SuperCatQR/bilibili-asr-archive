"""Command-level records survive early and repeated batch interruptions."""

import bili_asr.cli.main as _module_cli_main
import bili_asr.cli.run_state as _module_cli_run_state
import bili_asr.cli.signals as _module_cli_signals


from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from bili_asr import cli
from bili_asr.archive import archive_stem
from bili_asr.pipeline.attempts import AttemptLedger
from bili_asr.pipeline.models import RowResult, RunSummary
from bili_asr.manifest import ManifestStore
from bili_asr.meta_cursor import MetaCursorStore
from bili_asr.page_identity import page_identity
from bili_asr.run_ledger import RunLedger


COMMANDS = ("run", "schedule", "campaign", "pilot")


def _seed(root):
    identity = page_identity("BVrecord", 0, 7, "p0")
    row = {
        "work_id": identity.work_id, "bvid": identity.bvid,
        "page_index": 0, "cid": 7, "page_label": "p0",
        "title": "record", "date": "2026-10-05", "duration_s": 1,
        "status": "subtitle_done", "source": "cc",
    }
    raw = Path(root) / "subtitles" / "raw" / f"{archive_stem(row)}.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"body": [{"from": 0, "to": 1, "content": "record"}]}), encoding="utf-8")
    row["subtitle_path"] = str(raw.relative_to(root)).replace(os.sep, "/")
    ManifestStore(root).upsert(row)
    return identity.work_id


def _argv(root, command, work_id):
    result = [command, "--archive-root", str(root)]
    if command == "pilot":
        result += ["--n", "1", "--queue-source", "manifest"]
    else:
        result += ["--scope", work_id, "--limit", "1"]
    if command == "campaign":
        result.append("--offline")
    return result






_CLOSED_STDERR_RECORD = '''import json
import os
import sys
from types import SimpleNamespace
from bili_asr.cli.run_record import recorded_command
from bili_asr.manifest import ManifestStore
from bili_asr.run_ledger import RunLedger

root, failure, outcome = sys.argv[1:]
cleaned = False
private_error = type("SESSDATA_cookie_error", (OSError,), {})

def fail(*args, **kwargs):
    raise private_error("https://signed.example/?cookie=SECRET")

if failure == "projection":
    ManifestStore.load = fail
else:
    RunLedger.append = fail

@recorded_command("run")
def command(args):
    global cleaned
    os.close(2)
    try:
        if outcome == "interrupted":
            raise KeyboardInterrupt
        if outcome == "primary-error":
            raise RuntimeError("original failure")
        return 0
    finally:
        cleaned = True

try:
    code = command(SimpleNamespace(archive_root=root))
except RuntimeError as exc:
    assert str(exc) == "original failure"
    code = 7
print(json.dumps({"code": code, "cleaned": cleaned}))
sys.exit(code)
'''


@pytest.mark.parametrize("failure", ("projection", "write"))
@pytest.mark.parametrize("outcome, expected", (("normal", 0), ("interrupted", 130), ("primary-error", 7)))
def test_closed_stderr_preserves_cleanup_primary_error_and_exit_status(tmp_root, failure, outcome, expected):
    """Real stderr buffering must not replace a command status with exit 120."""
    package_root = Path(__file__).resolve().parents[1]
    child = subprocess.run(
        [sys.executable, "-c", _CLOSED_STDERR_RECORD, str(tmp_root), failure, outcome],
        cwd=package_root, env=dict(os.environ, PYTHONPATH=str(package_root / "src")),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
    )
    assert child.returncode == expected, (child.stdout, child.stderr)
    assert json.loads(child.stdout) == {"code": expected, "cleaned": True}
    assert child.stderr == ""
    records = RunLedger(tmp_root).load()
    if failure == "projection":
        record, = records
        assert record["exit_code"] == (1 if outcome == "primary-error" else expected)
        assert record["coverage_summary"] == {}
    else:
        assert records == []


@pytest.mark.parametrize("command", ("schedule", "campaign"))
def test_risk_record_preserves_cursor_and_api_code(tmp_root, monkeypatch, command):
    work_id = _seed(tmp_root)
    monkeypatch.setattr("bili_asr.bili_client.BiliClient", lambda **kwargs: object())
    cursor = MetaCursorStore(tmp_root).replace_atomic({
        "mid": 1, "next_page": 2, "total": 5, "state": "limited",
        "last_api_error_code": None, "updated_at": "2026-10-05T00:00:00Z",
    })
    summary = RunSummary(
        results=[RowResult(work_id, "subtitle_done", ok=False, failure_codes=[-412])],
        risk_interrupted=True,
    )
    monkeypatch.setattr("bili_asr.coordinator.RunCoordinator.run_batch", lambda self, rows: summary)
    assert _module_cli_main.main(_argv(tmp_root, command, work_id)) == 2
    record, = RunLedger(tmp_root).load()
    assert record["exit_code"] == 2
    assert record["last_api_error_code"] == -412
    if command == "schedule":
        assert record["cursor_snapshot"] == cursor


@pytest.mark.parametrize("started_at, expected", [
    ("2026-09-18T00:00:00Z", ["whole", "fraction", "offset"]),
    ("2026-09-18T00:00:00.1Z", ["fraction", "offset"]),
])
def test_partial_membership_uses_instants_instead_of_iso_text(tmp_root, started_at, expected):
    attempts = AttemptLedger(tmp_root)
    for work_id, stamp in (
        ("old", "2026-09-17T23:59:59.9Z"),
        ("whole", "2026-09-18T00:00:00Z"),
        ("fraction", "2026-09-18T00:00:00.1Z"),
        ("offset", "2026-09-18T08:00:00.2+08:00"),
        ("invalid", "not-a-time"),
    ):
        attempts.append({
            "stage": "download", "work_id": work_id, "attempt": 1,
            "outcome": "ok", "error_code": None, "artifact_paths": [],
            "started_at": stamp, "finished_at": stamp,
        })
    work_ids, coverage = _module_cli_run_state._partial_run_state(tmp_root, started_at)
    assert work_ids == expected
    assert coverage == {}


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("signum", (signal.SIGTERM, signal.SIGINT))
def test_guard_covers_initial_manifest_load(tmp_root, monkeypatch, command, signum):
    work_id = _seed(tmp_root)
    monkeypatch.setattr("bili_asr.bili_client.BiliClient", lambda **kwargs: object())
    original = ManifestStore.load
    first = True
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    def interrupt_once(self):
        nonlocal first
        if first:
            first = False
            handler = signal.getsignal(signum)
            assert callable(handler)
            handler(signum, None)
        return original(self)

    monkeypatch.setattr(ManifestStore, "load", interrupt_once)
    assert _module_cli_main.main(_argv(tmp_root, command, work_id)) == 128 + signum
    record, = RunLedger(tmp_root).load()
    assert record["command"] == command and record["exit_code"] == 128 + signum
    assert record["records_existing"] is None
    assert record["work_ids"] is None
    assert record["coverage_summary"] == {"subtitle_done": 1}
    assert {sig: signal.getsignal(sig) for sig in previous} == previous


def test_interruption_keeps_minimal_record_when_state_projection_also_fails(tmp_root, monkeypatch, capsys):
    work_id = _seed(tmp_root)
    first = True

    def fail_load(self):
        nonlocal first
        if first:
            first = False
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        raise OSError("SESSDATA=SECRET https://signed.example/")

    monkeypatch.setattr(ManifestStore, "load", fail_load)
    assert _module_cli_main.main(_argv(tmp_root, "run", work_id)) == 143
    record, = RunLedger(tmp_root).load()
    assert record["command"] == "run" and record["exit_code"] == 143
    assert record["records_existing"] is None and record["work_ids"] is None
    assert record["coverage_summary"] == {}
    error = capsys.readouterr().err
    assert error == "run: run-ledger state unavailable\n"


@pytest.mark.parametrize("command", COMMANDS)
def test_guard_covers_client_construction_before_banner(tmp_root, monkeypatch, capsys, command):
    work_id = _seed(tmp_root)

    def interrupt(**kwargs):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr("bili_asr.bili_client.BiliClient", interrupt)
    argv = _argv(tmp_root, command, work_id)
    if "--offline" in argv:
        argv.remove("--offline")
    assert _module_cli_main.main(argv) == 143
    record, = RunLedger(tmp_root).load()
    assert record["command"] == command and record["exit_code"] == 143
    # Campaign constructs its client before runner/manifest creation.
    assert record["records_existing"] == (None if command == "campaign" else 1)
    assert record["work_ids"] is None
    assert record["coverage_summary"] == {"subtitle_done": 1}
    assert "Traceback" not in capsys.readouterr().err




@pytest.mark.parametrize("first_signal", (signal.SIGTERM, signal.SIGINT))
def test_first_delivery_blocks_reentrant_other_signal(monkeypatch, first_signal):
    # Re-enter during the first handler's ignore operation, before either swap.
    # The second handler must return, otherwise it replaces the first exception.
    import bili_asr.cli.run as run

    original = _module_cli_signals._ignore_interruption_signals
    second_signal = signal.SIGINT if first_signal == signal.SIGTERM else signal.SIGTERM

    def deliver_again():
        signal.getsignal(second_signal)(second_signal, None)
        return original()

    monkeypatch.setattr(_module_cli_signals, "_ignore_interruption_signals", deliver_again)
    with _module_cli_signals._interruptible_run():
        with pytest.raises(_module_cli_signals._RunInterrupted) as interruption:
            signal.getsignal(first_signal)(first_signal, None)
        assert interruption.value.signum == first_signal
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
        assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN




_EARLY_LOAD_HOOK = '''import os
import time
from pathlib import Path
from bili_asr import bili_client
from bili_asr.manifest import ManifestStore

bili_client.BiliClient = lambda **kwargs: object()
original = ManifestStore.load
first = True
marker = Path(os.environ["BILI_RECORD_MARKER"])
cleanup = Path(os.environ["BILI_RECORD_CLEANUP"])
release = Path(os.environ["BILI_RECORD_RELEASE"])

def park_once(self):
    global first
    if first:
        first = False
        marker.write_text("loading", encoding="utf-8")
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            cleanup.write_text("unwinding", encoding="utf-8")
            deadline = time.monotonic() + 15
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
    return original(self)

ManifestStore.load = park_once
'''


def _await_marker(child, marker):
    deadline = time.monotonic() + 10
    while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), f"child stopped before {marker.name}; exit={child.poll()}"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process signals")
@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("first_signal", (signal.SIGTERM, signal.SIGINT))
def test_real_early_signal_and_repeated_signal_during_cleanup(tmp_root, tmp_path, command, first_signal):
    work_id = _seed(tmp_root)
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_EARLY_LOAD_HOOK, encoding="utf-8")
    marker, cleanup, release = (hook / name for name in ("loading", "cleanup", "release"))
    package_root = Path(__file__).resolve().parents[1]
    child = subprocess.Popen(
        [sys.executable, "-u", "-m", "bili_asr", *_argv(tmp_root, command, work_id)],
        cwd=package_root, env=dict(
            os.environ, PYTHONPATH=f"{hook}{os.pathsep}{package_root / 'src'}",
            BILI_RECORD_MARKER=str(marker), BILI_RECORD_CLEANUP=str(cleanup),
            BILI_RECORD_RELEASE=str(release),
        ), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        _await_marker(child, marker)
        child.send_signal(first_signal)
        _await_marker(child, cleanup)
        other_signal = signal.SIGINT if first_signal == signal.SIGTERM else signal.SIGTERM
        child.send_signal(other_signal)
        release.write_text("go", encoding="utf-8")
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 128 + first_signal, (stdout, stderr)
        assert "Traceback" not in stderr
    finally:
        release.write_text("go", encoding="utf-8")
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
    record, = RunLedger(tmp_root).load()
    assert record["command"] == command
    assert record["exit_code"] == 128 + first_signal
    assert record["records_existing"] is None
    assert record["coverage_summary"] == {"subtitle_done": 1}
    # The main writer lock survived the entire record append and was released.
    from bili_asr.pipeline.locks import archive_writer
    with archive_writer(tmp_root):
        pass
