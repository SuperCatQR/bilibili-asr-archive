"""Real offline wheel and isolated console-script installation checks."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.support.installed_cli import (
    SENTINEL_COOKIE, _venv_scripts_dir, assert_redacted, clean_cli_env,
    provision_isolated_cli, run_installed,
)


@pytest.fixture(scope="module")
def isolated_cli(tmp_path_factory: pytest.TempPathFactory):
    """Provision a fresh local-only install; missing prerequisites fail clearly."""
    return provision_isolated_cli(str(tmp_path_factory.mktemp("isolated-cli") / "venv"))

def test_installed_console_script_help(isolated_cli) -> None:
    proc = run_installed(isolated_cli, ["--help"])
    assert proc.returncode == 0, proc.stderr
    assert "bili-asr" in proc.stdout
    for command in (
        "workflow", "fetch-meta", "status", "runs", "search-index",
        "coverage", "verify", "export", "check-asr-env", "publication", "editorial", "snapshot",
    ):
        assert command in proc.stdout
    assert_redacted(proc)

def test_installed_console_script_status_fails_without_database(isolated_cli, tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    proc = run_installed(isolated_cli, ["status", "--archive-root", str(archive_root)])
    assert proc.returncode == 1, proc.stdout
    assert "no archive database" in proc.stderr
    assert proc.stdout == ""
    assert_redacted(proc)

def test_stdlib_venv_install_works_without_uv_or_inherited_backend(monkeypatch, tmp_path: Path) -> None:
    """A fresh Python 3.12 venv installs the locally built wheel offline."""
    import tests.support.installed_cli as helper

    monkeypatch.setattr(helper, "_find_uv", lambda: None)
    isolated = provision_isolated_cli(str(tmp_path / "stdlib-cli"))
    proc = run_installed(isolated, ["--help"])
    assert proc.returncode == 0, proc.stderr
    assert "workflow" in proc.stdout
    backend = subprocess.run(
        [isolated.python, "-c", "import importlib.util; assert importlib.util.find_spec('setuptools') is None"],
        capture_output=True, text=True, check=False,
    )
    assert backend.returncode == 0, backend.stderr

def test_installed_console_script_opens_and_initializes_database(isolated_cli, tmp_path: Path) -> None:
    """The shipped entry point must load both packaged schemas from an empty DB file."""
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    (archive_root / "archive.db").touch()

    proc = run_installed(isolated_cli, ["status", "--archive-root", str(archive_root)])

    assert proc.returncode == 0, proc.stderr
    assert "users: 0" in proc.stdout
    assert "videos: 0" in proc.stdout
    assert "parts: 0" in proc.stdout
    assert "pending: 0" in proc.stdout
    assert_redacted(proc)
    with sqlite3.connect(archive_root / "archive.db") as connection:
        objects = {
            (kind, name)
            for kind, name in connection.execute(
                "SELECT type, name FROM sqlite_master"
            )
        }
    assert ("table", "transcripts") in objects
    assert ("view", "v_missing_audio") in objects
    for name in ("workflow_jobs", "editorial_inputs", "editorial_model_calls",
                 "editorial_chunk_results", "editorial_revisions", "document_artifacts",
                 "manuscript_contract", "publication_editions", "publication_edition_reviews",
                 "publication_releases", "publication_heads", "publication_events"):
        assert ("table", name) in objects


def test_installed_publication_commands_and_removed_aliases(isolated_cli) -> None:
    for command in ("create", "edit", "review", "publish", "withdraw", "show", "export"):
        proc = run_installed(isolated_cli, ["publication", command, "--help"])
        assert proc.returncode == 0, proc.stderr
        assert "--archive-root" in proc.stdout
        assert_redacted(proc)
    internal = run_installed(isolated_cli, ["editorial", "export", "--help"])
    assert internal.returncode == 0, internal.stderr
    assert "--edition-id" in internal.stdout
    for command in ("reading-publish", "reading-export", "reading-verify"):
        removed = run_installed(isolated_cli, [command, "--help"])
        assert removed.returncode == 1
        assert "invalid choice" in removed.stderr


def test_installed_proofread_help_and_workflow_status(isolated_cli, tmp_path: Path) -> None:
    help_result = run_installed(isolated_cli, ["workflow", "proofread", "--help"])
    assert help_result.returncode == 0, help_result.stderr
    assert "--max-input-tokens" in help_result.stdout
    assert "--base-transcript-id" in help_result.stdout
    root = tmp_path / "editorial-archive"
    status = run_installed(isolated_cli, ["workflow", "status", "--archive-root", str(root)])
    assert status.returncode == 0, status.stderr
    assert "queued: 0" in status.stdout
    assert_redacted(status)
    with sqlite3.connect(root / "archive.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM editorial_inputs").fetchone()[0] == 0


def test_installed_snapshot_round_trip_offline(isolated_cli, tmp_path: Path) -> None:
    """The wheel-only console script transfers a store from a foreign cwd."""
    root = tmp_path / "source"
    root.mkdir()
    (root / "archive.db").touch()
    env = {"BILI_ARTIFACT_ROOT": ""}
    initialized = run_installed(isolated_cli, ["status", "--archive-root", str(root)], extra_env=env)
    assert initialized.returncode == 0, initialized.stderr
    audio = b"offline reusable audio"
    (root / "audio").mkdir()
    (root / "audio" / "cached.m4a").write_bytes(audio)
    snapshot = tmp_path / "transfer.zip"

    saved = run_installed(isolated_cli, [
        "snapshot", "save", "--archive-root", str(root), "--out", str(snapshot),
    ], extra_env=env)
    assert saved.returncode == 0, saved.stderr
    report = json.loads(saved.stdout)
    assert report["file_count"] == 2
    root.rename(tmp_path / "source-offline")

    checked = run_installed(isolated_cli, ["snapshot", "check", "--file", str(snapshot)], extra_env=env)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["valid"] is True
    destination = tmp_path / "other-device"
    restored = run_installed(isolated_cli, [
        "snapshot", "restore", "--file", str(snapshot), "--archive-root", str(destination),
    ], extra_env=env)
    assert restored.returncode == 0, restored.stderr
    assert json.loads(restored.stdout)["snapshot_id"] == report["snapshot_id"]
    assert (destination / "audio" / "cached.m4a").read_bytes() == audio
    status = run_installed(isolated_cli, ["status", "--archive-root", str(destination)], extra_env=env)
    assert status.returncode == 0, status.stderr
    assert "videos: 0" in status.stdout
    for result in (initialized, saved, checked, restored, status):
        assert_redacted(result)


def test_installed_script_is_not_path_or_checkout_source(isolated_cli) -> None:
    assert Path(isolated_cli.executable).parent == Path(_venv_scripts_dir(isolated_cli.venv_dir))
    probe = run_installed(isolated_cli, ["--help"])
    assert probe.returncode == 0
    assert "PYTHONPATH" not in probe.stdout
    assert_redacted(probe)

def test_installed_console_script_resolves_its_packaged_host_check(isolated_cli) -> None:
    """A wheel-only venv reaches the host probes from a foreign working directory."""
    package_probe = subprocess.run(
        [isolated_cli.python, "-c", (
            "import pathlib, bili_asr; "
            "print(pathlib.Path(bili_asr.__file__).parent / 'check_asr_env.py')"
        )],
        cwd=isolated_cli.venv_dir, env=clean_cli_env(),
        capture_output=True, text=True, check=False,
    )
    assert package_probe.returncode == 0, package_probe.stderr
    packaged_helper = Path(package_probe.stdout.strip())
    assert packaged_helper.is_file()
    assert packaged_helper.is_relative_to(Path(isolated_cli.venv_dir))
    proc = run_installed(isolated_cli, ["check-asr-env"])
    # This venv deliberately has no torch: a failed hardware verdict is
    # expected, while failure to locate or load the packaged helper is not.
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "check: torch-present FAIL" in proc.stdout
    assert "check: device-probe FAIL" in proc.stdout
    assert "asr-env: not verified" in proc.stdout
    assert "no check script found" not in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert_redacted(proc)


def test_installed_console_script_status_requires_database(isolated_cli, tmp_path: Path) -> None:
    proc = run_installed(isolated_cli, ["status", "--archive-root", str(tmp_path)])
    assert proc.returncode == 1, proc.stdout
    assert "no archive database" in proc.stderr
    assert_redacted(proc)

def test_sentinel_never_appears_in_cli_output(isolated_cli) -> None:
    proc = run_installed(isolated_cli, ["--help"], extra_env={"BILI_SESSDATA": SENTINEL_COOKIE})
    assert SENTINEL_COOKIE not in (proc.stdout + proc.stderr)
    assert_redacted(proc)
