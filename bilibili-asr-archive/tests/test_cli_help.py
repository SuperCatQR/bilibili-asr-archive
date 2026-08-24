import os
import subprocess
import sys

import pytest

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
ENV = dict(os.environ, PYTHONPATH=os.path.abspath(SRC))


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "bili_asr", *args],
        capture_output=True,
        text=True,
        env=ENV,
    )


def test_help_exits_zero():
    proc = _run(["--help"])
    assert proc.returncode == 0, proc.stderr


def test_help_mentions_fetch_meta():
    proc = _run(["--help"])
    assert "fetch-meta" in proc.stdout


def test_main_help_direct(capsys):
    from bili_asr.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "bili-asr" in out
    assert "fetch-meta" in out


def test_cli_main_importable():
    from bili_asr.cli import main as _  # noqa: F401
