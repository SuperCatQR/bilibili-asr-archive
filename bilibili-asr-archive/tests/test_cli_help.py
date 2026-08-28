"""Integration tests for the package's isolated console-script installation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from installed_cli import (
    SENTINEL_COOKIE,
    _redact_diagnostics,
    _summarize,
    _venv_scripts_dir,
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
    assert Path(isolated_cli.executable).parent == Path(_venv_scripts_dir(isolated_cli.venv_dir))
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


def test_installed_console_script_status_with_manifest_records(isolated_cli, tmp_path: Path) -> None:
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({"work_id": "BV1test_inst:p1", "bvid": "BV1test_inst", "status": "archived"})
    store.upsert({"work_id": "BV1test_meta:p1", "bvid": "BV1test_meta", "status": "meta_ok"})

    proc = run_installed(isolated_cli, ["status", "--archive-root", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    assert "archived: 1" in proc.stdout
    assert "meta_ok: 1" in proc.stdout
    assert_redacted(proc)


def test_module_runs_empty_archive(tmp_path: Path) -> None:
    proc = run_module(["runs", "--archive-root", str(tmp_path)])
    assert proc.returncode == 0, proc.stderr
    assert "runs: empty" in proc.stdout
    assert_redacted(proc)


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


def test_coverage_parser_options_and_status_preserved(capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import build_parser

    parser = build_parser()
    coverage = parser.parse_args([
        "coverage", "--archive-root", "/tmp/fixture", "--scope", "pending", "--format", "csv"
    ])
    assert coverage.command == "coverage"
    assert coverage.archive_root == "/tmp/fixture"
    assert coverage.scope == "pending"
    assert coverage.format == "csv"
    status = parser.parse_args(["status", "--archive-root", "/tmp/fixture"])
    assert status.command == "status"
    assert status.archive_root == "/tmp/fixture"

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["coverage", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--archive-root" in help_text
    assert "--scope" in help_text
    assert "{json,csv}" in help_text


def test_install_failure_diagnostics_redact_signed_urls_and_credentials() -> None:
    diagnostic = _redact_diagnostics(
        "ERROR: https://user:secret@example.test/pkg?token=abc&signature=sig&deadline=123 "
        "SESSDATA=leak " + SENTINEL_COOKIE
    )
    assert diagnostic == "ERROR: [redacted-url] [redacted] [redacted]"


def test_install_failure_summary_redacts_output() -> None:
    proc = subprocess.CompletedProcess(
        ["pip"],
        1,
        "",
        "error: https://signed.example.test/pkg?token=abc&signature=sig " + SENTINEL_COOKIE,
    )
    summary = _summarize(proc)
    assert "https://" not in summary
    assert "token=abc" not in summary
    assert SENTINEL_COOKIE not in summary


def test_sentinel_never_appears_in_cli_output(isolated_cli) -> None:
    proc = run_installed(isolated_cli, ["--help"], extra_env={"BILI_SESSDATA": SENTINEL_COOKIE})
    assert SENTINEL_COOKIE not in (proc.stdout + proc.stderr)
    assert_redacted(proc)
