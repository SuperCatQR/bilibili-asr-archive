"""Damaged optional history stays recoverable when stderr disappears."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from bili_asr.run_ledger import RunLedger, build_run_record


_READ_WITH_CLOSED_STDERR = """
import json
import os
import sys
from bili_asr.run_ledger import RunLedger

os.close(2)
value = getattr(RunLedger(sys.argv[1]), sys.argv[2])()
print(json.dumps(value))
"""

_READ_SIDECAR_WITH_CLOSED_STDERR = """
import json
import os
import sys
from bili_asr.meta_cursor import MetaCursorStore
from bili_asr.scheduler import SchedulerStore

stores = {"meta-cursor": MetaCursorStore, "scheduler": SchedulerStore}
os.close(2)
print(json.dumps(stores[sys.argv[2]](sys.argv[1]).load()))
"""


def _child(root, script, *args):
    package_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-c", script, str(root), *args],
        cwd=package_root, env=dict(os.environ, PYTHONPATH=os.pathsep.join(
            str(package_root / folder) for folder in ("src", "tests"))),
        capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("method", ["load", "latest"])
def test_corrupt_lines_keep_valid_records_and_exit_zero_with_closed_stderr(tmp_root, method):
    ledger = RunLedger(tmp_root)
    first = ledger.append(build_run_record(command="run", started_at="2026-10-05T00:00:00Z", exit_code=0))
    with Path(ledger.path).open("a", encoding="utf-8") as stream:
        stream.write("{broken}\n")
        stream.write(json.dumps({"SESSDATA": "cookie=SECRET", "url": "https://signed.example/"}) + "\n")
    last = ledger.append(build_run_record(command="schedule", started_at="2026-10-05T00:01:00Z", exit_code=0))
    result = _child(tmp_root, _READ_WITH_CLOSED_STDERR, method)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stderr == ""
    assert json.loads(result.stdout) == ([first, last] if method == "load" else last)
    assert "SECRET" not in result.stdout
    assert "signed.example" not in result.stdout


@pytest.mark.parametrize("kind", ["meta-cursor", "scheduler"])
@pytest.mark.parametrize("content", ["{broken}", "[]", '{"SESSDATA":"cookie=SECRET"}', b"\xff"])
def test_corrupt_sidecar_remains_optional_with_closed_stderr(tmp_root, kind, content):
    Path(tmp_root, kind + ".json").write_bytes(
        content if isinstance(content, bytes) else content.encode("utf-8")
    )
    result = _child(tmp_root, _READ_SIDECAR_WITH_CLOSED_STDERR, kind)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == "null\n"
    assert result.stderr == ""


_CLI_WITH_CLOSED_STDERR = """
import json
import os
import sys
from bili_asr import cli

os.close(2)
argv = json.loads(sys.argv[2])
try:
    code = cli.main([*argv, "--archive-root", sys.argv[1]])
except SystemExit as exc:
    code = exc.code
print("completed=" + str(code))
raise SystemExit(code)
"""


@pytest.mark.parametrize("argv", [
    ["run", "--scope", "pending", "--limit", "0"],
    ["schedule", "--scope", "pending", "--limit", "0"],
    ["campaign", "--offline", "--scope", ",", "--limit", "1"],
    ["pilot", "--n", "1", "--queue-source", "manifest"],
    ["asr", "--queue-source", "manifest"],
    ["download-audio", "--queue-source", "manifest"],
    ["fetch-meta", "--resume"],
    ["probe-subs"],
    ["harvest-subs", "--limit-parts", "0"],
    ["publish-transcripts", "--limit-parts", "0"],
    ["proofread", "--bvid", "BVmissing"],
    ["export", "--format", "json", "--status", "unsupported"],
])
def test_cli_error_returns_its_chosen_code_after_stderr_is_closed(tmp_root, argv):
    result = _child(tmp_root, _CLI_WITH_CLOSED_STDERR, json.dumps(argv))
    assert result.returncode == 1, (argv, result.stdout, result.stderr)
    assert result.stdout.splitlines()[-1] == "completed=1", result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("argv", [
    ["run"],
    ["schedule", "--scope", "pending"],
    ["asr", "--unknown-option"],
])
def test_parser_usage_error_preserves_exit_contract_with_closed_stderr(tmp_root, argv):
    result = _child(tmp_root, _CLI_WITH_CLOSED_STDERR, json.dumps(argv))
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stdout == "completed=1\n"
    assert result.stderr == ""
    assert not list(Path(tmp_root).iterdir())


_PROCESS_ROWS_WITH_CLOSED_STDERR = """
import os
import sys
from bili_asr import asr, cli
from test_batch_hotwords_record import VerdictRunner, RiskOnceRunner

class FailedFirstRunner(VerdictRunner):
    def transcribe(self, path, **kwargs):
        if self.calls == 0:
            self.calls += 1
            raise RuntimeError("SESSDATA cookie=SECRET https://signed.example/")
        return super().transcribe(path, **kwargs)

mode = sys.argv[2]
runner = FailedFirstRunner() if mode == "continue" else RiskOnceRunner()
asr.ASRRunner = lambda config: runner
argv = (["asr", "--pending", "--queue-source", "manifest"] if mode == "continue"
        else ["campaign", "--offline", "--scope", "BVhotword:p0,BVhotword:p1", "--limit", "2"])
os.close(2)
code = cli.main([*argv, "--archive-root", sys.argv[1]])
assert runner.calls == 2
assert runner.released == 1
print("completed=" + str(code))
raise SystemExit(code)
"""


@pytest.mark.parametrize("mode,exit_code", [("continue", 1), ("risk", 2)])
def test_real_rows_continue_or_stop_at_risk_without_stderr_changing_the_exit(tmp_root, mode, exit_code):
    from bili_asr.manifest import ManifestStore
    from test_batch_hotwords_record import _seed_audio

    store, rows = _seed_audio(tmp_root, 2)
    result = _child(tmp_root, _PROCESS_ROWS_WITH_CLOSED_STDERR, mode)
    assert result.returncode == exit_code, (result.stdout, result.stderr)
    assert result.stdout.splitlines()[-1] == f"completed={exit_code}"
    assert result.stderr == ""
    assert "SECRET" not in result.stdout
    loaded = ManifestStore(tmp_root).load()
    assert loaded[rows[0][0]]["status"] == ("audio_ok" if mode == "continue" else "archived")
    assert loaded[rows[1][0]]["status"] == ("archived" if mode == "continue" else "audio_ok")
