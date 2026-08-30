"""Integration tests for the package's isolated console-script installation."""

from __future__ import annotations

import json
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
    for command in ("fetch-meta", "status", "runs", "asr", "pilot", "coverage", "verify", "recover"):
        assert command in proc.stdout
    assert_redacted(proc)



def test_recover_requires_explicit_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import main
    assert main(["recover", "--archive-root", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "recovery_requires_explicit_target"


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
    assert "coverage" in out
    assert "status" in out

def test_cli_main_importable() -> None:
    from bili_asr.cli import main as _  # noqa: F401


def test_coverage_parser_options_and_status_preserved(capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import build_parser

    parser = build_parser()
    coverage = parser.parse_args([
        "coverage", "--archive-root", "/tmp/fixture", "--scope", "pending", "--format", "csv", "--quality"
    ])
    assert coverage.command == "coverage"
    assert coverage.archive_root == "/tmp/fixture"
    assert coverage.scope == "pending"
    assert coverage.format == "csv"
    assert coverage.quality is True
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
    assert "--quality" in help_text


def test_search_parser_options_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import build_parser

    parser = build_parser()
    search_args = parser.parse_args([
        "search", "Hegel",
        "--archive-root", "/tmp/fixture",
        "--status", "archived",
        "--source", "asr",
        "--language", "ai-zh",
        "--scope", "pending",
        "--work-id", "BV1test:p0",
        "--limit", "10",
        "--format", "json",
        "--rebuild",
    ])
    assert search_args.command == "search"
    assert search_args.query == "Hegel"
    assert search_args.archive_root == "/tmp/fixture"
    assert search_args.status == ["archived"]
    assert search_args.source == ["asr"]
    assert search_args.language == ["ai-zh"]
    assert search_args.scope == "pending"
    assert search_args.work_id == ["BV1test:p0"]
    assert search_args.limit == 10
    assert search_args.format == "json"
    assert search_args.rebuild is True

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["search", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--archive-root" in help_text
    assert "--status" in help_text
    assert "--source" in help_text
    assert "--language" in help_text
    assert "--scope" in help_text
    assert "--work-id" in help_text
    assert "--limit" in help_text
    assert "--format" in help_text
    assert "--rebuild" in help_text


def test_module_coverage_formats_and_diagnostic_exit(tmp_path: Path) -> None:
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({"work_id": "BV1safe:p1", "bvid": "BV1safe", "status": "archived"})
    transcript = tmp_path / "transcripts" / "txt" / "BV1safe.p1.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("local fixture", encoding="utf-8")
    for fmt in ("json", "csv"):
        proc = run_module(["coverage", "--archive-root", str(tmp_path), "--format", fmt])
        assert proc.returncode in (0, 1), proc.stderr
        assert "schema_version" in proc.stdout
        assert_redacted(proc)

    manifest_path = tmp_path / "manifest" / "manifest.jsonl"
    manifest_path.write_text(manifest_path.read_text() + manifest_path.read_text(), encoding="utf-8")
    diagnostic = run_module(["coverage", "--archive-root", str(tmp_path), "--format", "json"])
    assert diagnostic.returncode == 1
    assert "manifest_duplicate_work_id" in diagnostic.stdout
    assert_redacted(diagnostic)


def test_cli_main_coverage_quality_valid_and_reclaimed_audio(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr import cli
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({
        "work_id": "BV1clean:p0",
        "bvid": "BV1clean",
        "page_index": 0,
        "cid": 100,
        "title": "Clean Video",
        "status": "archived",
        "duration_s": 10,
        "source": "subtitle",
        "sub_lan": "ai-zh",
    })
    srt_path = tmp_path / "transcripts" / "srt" / "BV1clean.p0.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    # Clean valid item exits 0
    exit_code = cli.main(["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "coverage-quality-v1"
    assert payload["denominator"]["count"] == 1
    assert payload["denominator"]["state"] == "available"
    assert payload["summary"]["valid_work_items"] == 1
    assert payload["summary"]["total_cues"] == 1
    assert payload["rows"][0]["work_id"] == "BV1clean:p0"
    assert payload["rows"][0]["reasons"] == []

    # CSV format output
    exit_code = cli.main(["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "csv"])
    assert exit_code == 0
    csv_out = capsys.readouterr().out
    assert "coverage-quality-v1" in csv_out
    assert "BV1clean:p0" in csv_out


def test_cli_main_coverage_quality_anomalies_and_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr import cli
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({
        "work_id": "BV1bad:p0",
        "bvid": "BV1bad",
        "page_index": 0,
        "cid": 101,
        "title": "Bad Video",
        "status": "archived",
        "duration_s": 5,
        "source": "subtitle",
        "sub_lan": "ai-zh",
    })
    srt_path = tmp_path / "transcripts" / "srt" / "BV1bad.p0.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    # Non-monotonic cues
    srt_path.write_text("1\n00:00:03,000 --> 00:00:04,000\nA\n\n2\n00:00:01,000 --> 00:00:02,000\nB\n", encoding="utf-8")

    stat_before = (srt_path.read_bytes(), srt_path.stat().st_mtime_ns)

    exit_code = cli.main(["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "json"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"][0]["reasons"] == ["non_monotonic", "overlap"]
    assert payload["summary"]["non_monotonic"] == 1
    assert payload["summary"]["overlap"] == 1
    assert payload["summary"]["valid_work_items"] == 0

    # Read-only check: file content and mtime unmodified
    assert (srt_path.read_bytes(), srt_path.stat().st_mtime_ns) == stat_before


def test_cli_main_coverage_quality_scope_and_redaction(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr import cli
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({"work_id": "BV1one:p0", "bvid": "BV1one", "status": "archived"})
    store.upsert({"work_id": "BV1two:p0", "bvid": "BV1two", "status": "meta_ok"})

    # Scope pending selects only meta_ok
    exit_code = cli.main(["coverage", "--archive-root", str(tmp_path), "--quality", "--scope", "pending", "--format", "json"])
    assert exit_code == 1  # missing artifact on meta_ok
    payload = json.loads(capsys.readouterr().out)
    assert payload["denominator"]["count"] == 1
    assert payload["rows"][0]["work_id"] == "BV1two:p0"

    # Unknown scope
    exit_code = cli.main(["coverage", "--archive-root", str(tmp_path), "--quality", "--scope", "BV1unknown", "--format", "json"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["denominator"]["state"] == "unavailable"
    assert payload["diagnostics"][0]["code"] == "unknown_scope"

    # Module run redaction check
    proc = run_module(["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "json"])
    assert_redacted(proc)


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
