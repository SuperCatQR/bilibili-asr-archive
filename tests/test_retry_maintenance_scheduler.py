"""Exercise the container scheduler as an independent operating-system process."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.skipif(os.name == "nt", reason="container process supervision is POSIX")
RUNNER = Path(__file__).parents[1] / "scripts/deployment/run_retry_maintenance.py"


def wait_for(predicate, process, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert process.poll() is None, "scheduler exited prematurely"
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("scheduler did not produce the expected durable evidence")


def test_failed_pass_continues_and_sigterm_stops_without_touching_state(tmp_path):
    calls = tmp_path / "calls.jsonl"
    fake = tmp_path / "fake-cli"
    fake.write_text(
        f"#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\n"
        f"p = Path({str(calls)!r})\n"
        "prior = p.read_text().splitlines() if p.exists() else []\n"
        "with p.open('a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(1 if not prior else 0)\n", encoding="utf-8")
    fake.chmod(0o700)
    policy = tmp_path / "policy.json"
    policy.write_text('{"interval_seconds":1}')
    state = tmp_path / "state.json"
    original = b'{"retry_holds":{"held":"keep"},"retry_ledger":{"spent":{"retries":2}}}'
    state.write_bytes(original)
    command = [sys.executable, str(RUNNER), "--bin", str(fake), "--archive-root", str(tmp_path / "archive"),
               "--policy", str(policy), "--state", str(state), "--lock", str(tmp_path / "retry.lock"),
               "--health", str(tmp_path / "health.json")]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for(lambda: calls.exists() and len(calls.read_text().splitlines()) >= 2, process)
        process.terminate()
        stdout, stderr = process.communicate(timeout=8)
        assert process.returncode == 0, stderr
        records = [json.loads(line) for line in stdout.splitlines()]
        assert records[0]["pass"] == "failed"
        assert any(record["pass"] == "completed" for record in records[1:])
        first = json.loads(calls.read_text().splitlines()[0])
        assert first[:2] == ["retry-maintenance", "tick"]
        assert first[first.index("--state") + 1] == str(state)
        assert state.read_bytes() == original
        stopped_count = len(calls.read_text().splitlines())
        time.sleep(1.1)
        assert len(calls.read_text().splitlines()) == stopped_count
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_hung_pass_is_terminated_and_scheduler_records_timeout(tmp_path):
    child_pid = tmp_path / "child.pid"
    fake = tmp_path / "hung-cli"
    fake.write_text(f"#!{sys.executable}\nimport os, time\nfrom pathlib import Path\n"
                    f"Path({str(child_pid)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n")
    fake.chmod(0o700)
    policy = tmp_path / "policy.json"
    policy.write_text('{"interval_seconds":60}')
    log = tmp_path / "scheduler.log"
    command = [sys.executable, str(RUNNER), "--bin", str(fake), "--archive-root", str(tmp_path / "archive"),
               "--policy", str(policy), "--state", str(tmp_path / "state.json"),
               "--lock", str(tmp_path / "retry.lock"), "--health", str(tmp_path / "health.json"),
               "--tick-timeout-seconds", "1"]
    with log.open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.PIPE, text=True)
        try:
            wait_for(lambda: '"timeout"' in log.read_text(), process)
            pid = int(child_pid.read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            process.terminate()
            process.communicate(timeout=8)
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
