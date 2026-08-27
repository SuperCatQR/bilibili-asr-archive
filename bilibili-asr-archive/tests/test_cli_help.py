"""Integration tests for the package's isolated console-script installation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from installed_cli import (
    SENTINEL_COOKIE,
    assert_redacted,
    provision_isolated_cli,
    run_installed,
    run_module,
)


@pytest.fixture(scope="module")
def isolated_cli(tmp_path_factory: pytest.TempPathFactory):
    """Provision a fresh local-only install; missing prerequisites fail clearly."""
    return provision_isolated_cli(str(tmp_path_factory.mktemp("isolated-cli") / "venv"))


def test_installed_console_script_help(isolated_cli) -> None:
    proc = run_installed(isolated_cli, ["--help"])
    assert proc.returncode == 0, proc.stderr
    assert "bili-asr" in proc.stdout
    for command in ("fetch-meta", "status", "runs", "asr", "pilot"):
        assert command in proc.stdout
    assert_redacted(proc)


def test_installed_console_script_status_uses_temp_archive_root(isolated_cli, tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    proc = run_installed(isolated_cli, ["status", "--archive-root", str(archive_root)])
    assert proc.returncode == 0, proc.stderr
    assert "manifest: empty" in proc.stdout
    assert str(archive_root) not in proc.stdout
    assert_redacted(proc)


def test_installed_script_is_not_path_or_checkout_source(isolated_cli) -> None:
    assert Path(isolated_cli.executable).parent == Path(isolated_cli.venv_dir) / "bin"
    probe = run_installed(isolated_cli, ["--help"])
    assert probe.returncode == 0
    assert "PYTHONPATH" not in probe.stdout
    assert_redacted(probe)


def test_module_help_is_supplemental_coverage() -> None:
    proc = run_module(["--help"])
    assert proc.returncode == 0, proc.stderr
    assert "bili-asr" in proc.stdout
    assert "status" in proc.stdout
    assert_redacted(proc)


def test_module_status_uses_temp_archive_root(tmp_path: Path) -> None:
    proc = run_module(["status", "--archive-root", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    assert "manifest: empty" in proc.stdout
    assert_redacted(proc)


def test_sentinel_never_appears_in_cli_output(isolated_cli) -> None:
    proc = run_installed(isolated_cli, ["--help"], extra_env={"BILI_SESSDATA": SENTINEL_COOKIE})
    assert SENTINEL_COOKIE not in (proc.stdout + proc.stderr)
    assert_redacted(proc)
