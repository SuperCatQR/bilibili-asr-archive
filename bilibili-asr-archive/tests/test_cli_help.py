"""Integration tests for installed console script and module entrypoints."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
ENV_WITH_PYTHONPATH = dict(os.environ, PYTHONPATH=os.path.abspath(SRC_DIR))


def _find_installed_bili_asr() -> str | None:
    """Locate the installed `bili-asr` console script executable."""
    # Check in the same bin/Scripts directory as the running Python interpreter
    venv_bin_dir = os.path.dirname(sys.executable)
    exe_candidate = shutil.which("bili-asr", path=venv_bin_dir)
    if exe_candidate and os.path.isfile(exe_candidate):
        return exe_candidate

    # Check in PATH
    exe_candidate = shutil.which("bili-asr")
    if exe_candidate and os.path.isfile(exe_candidate):
        return exe_candidate

    return None


@pytest.fixture
def installed_bili_asr() -> str:
    """Fixture providing the path to the installed `bili-asr` executable.

    Skips if not found in the environment with clear prerequisite instructions.
    """
    exe = _find_installed_bili_asr()
    if not exe:
        pytest.skip(
            "Installed 'bili-asr' console script not found in environment. "
            "Prepare environment with: pip install -e '.[asr,dev]' or pip install ."
        )
    return exe


def _run_installed(exe: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the installed console script without forcing PYTHONPATH."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [exe, *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _run_module(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run `python -m bili_asr` with PYTHONPATH configured."""
    return subprocess.run(
        [sys.executable, "-m", "bili_asr", *args],
        capture_output=True,
        text=True,
        env=ENV_WITH_PYTHONPATH,
    )


# --- Installed Console Script Entrypoint Tests ---


def test_installed_entrypoint_help_exits_zero(installed_bili_asr: str) -> None:
    proc = _run_installed(installed_bili_asr, ["--help"])
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "bili-asr" in proc.stdout
    assert "fetch-meta" in proc.stdout
    assert "status" in proc.stdout
    assert "asr" in proc.stdout
    assert "pilot" in proc.stdout


def test_installed_entrypoint_status_empty_archive(
    installed_bili_asr: str, tmp_path: pytest.TempPathFactory
) -> None:
    proc = _run_installed(
        installed_bili_asr, ["status", "--archive-root", str(tmp_path)]
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "manifest: empty" in proc.stdout


def test_installed_entrypoint_status_with_manifest_records(
    installed_bili_asr: str, tmp_path: pytest.TempPathFactory
) -> None:
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({"work_id": "BV1test_inst:p1", "bvid": "BV1test_inst", "status": "archived"})
    store.upsert({"work_id": "BV1test_meta:p1", "bvid": "BV1test_meta", "status": "meta_ok"})

    proc = _run_installed(
        installed_bili_asr, ["status", "--archive-root", str(tmp_path)]
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "archived: 1" in proc.stdout
    assert "meta_ok: 1" in proc.stdout


# --- Module Entrypoint Tests (python -m bili_asr) ---


def test_module_entrypoint_help_exits_zero() -> None:
    proc = _run_module(["--help"])
    assert proc.returncode == 0, proc.stderr
    assert "bili-asr" in proc.stdout


def test_module_entrypoint_help_mentions_subcommands() -> None:
    proc = _run_module(["--help"])
    assert proc.returncode == 0, proc.stderr
    assert "fetch-meta" in proc.stdout
    assert "status" in proc.stdout
    assert "runs" in proc.stdout
    assert "asr" in proc.stdout
    assert "pilot" in proc.stdout


def test_module_entrypoint_status_empty_archive(tmp_path: pytest.TempPathFactory) -> None:
    proc = _run_module(["status", "--archive-root", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    assert "manifest: empty" in proc.stdout


def test_module_entrypoint_runs_empty_archive(tmp_path: pytest.TempPathFactory) -> None:
    proc = _run_module(["runs", "--archive-root", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    assert "runs: empty" in proc.stdout


# --- Direct Python API Tests ---


def test_cli_main_help_direct(capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "bili-asr" in out
    assert "fetch-meta" in out
    assert "status" in out
    assert "runs" in out


def test_cli_main_importable() -> None:
    from bili_asr.cli import main as _  # noqa: F401
