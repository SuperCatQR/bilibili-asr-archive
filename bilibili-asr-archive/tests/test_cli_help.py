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


def test_installed_console_script_status_fails_without_database(isolated_cli, tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    proc = run_installed(isolated_cli, ["status", "--archive-root", str(archive_root)])
    assert proc.returncode == 1, proc.stdout
    assert "no archive database" in proc.stderr
    assert proc.stdout == ""
    assert_redacted(proc)


def test_recover_requires_explicit_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import main
    assert main(["recover", "--archive-root", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "recovery_requires_explicit_target"


def test_recover_help_describes_limit_contract(capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["recover", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--limit" in help_text
    assert "positive" in help_text
    assert "100" in help_text


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


def test_module_status_fails_without_database(tmp_path: Path) -> None:
    proc = run_module(["status", "--archive-root", str(tmp_path)])
    assert proc.returncode == 1, proc.stdout
    assert "no archive database" in proc.stderr
    assert_redacted(proc)


def test_installed_console_script_status_ignores_legacy_manifest(isolated_cli, tmp_path: Path) -> None:
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({"work_id": "BV1test_inst:p1", "bvid": "BV1test_inst", "status": "archived"})
    store.upsert({"work_id": "BV1test_meta:p1", "bvid": "BV1test_meta", "status": "meta_ok"})

    proc = run_installed(isolated_cli, ["status", "--archive-root", str(tmp_path)])
    # status reads only the fresh SQLite database: with no archive.db the
    # legacy manifest rows are neither read nor rewritten (exit 1).
    assert proc.returncode == 1, proc.stdout
    assert "BV1test_inst" not in proc.stdout
    assert "no archive database" in proc.stderr
    assert_redacted(proc)


def test_module_runs_fails_without_database(tmp_path: Path) -> None:
    proc = run_module(["runs", "--archive-root", str(tmp_path)])
    assert proc.returncode == 1, proc.stdout
    assert "no archive database" in proc.stderr
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

def test_evaluate_concurrency_help_is_evidence_only(capsys: pytest.CaptureFixture[str]) -> None:
    from bili_asr.cli import build_parser

    parser = build_parser()
    top_level_help = parser.format_help().lower()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["evaluate-concurrency", "--help"])
    assert exc.value.code == 0

    command_help = capsys.readouterr().out.lower()
    assert "evaluate-concurrency" in command_help
    assert "--evidence" in command_help
    assert "--thresholds" in command_help
    assert "evidence only" in top_level_help
    assert "sequential" in top_level_help
    assert "no daemon" in top_level_help
    combined_help = top_level_help + command_help
    for enablement_phrase in (
        "start worker",
        "enable worker",
        "start daemon",
        "enable daemon",
        "install service",
        "enable service",
        "concurrent manifest writer",
    ):
        assert enablement_phrase not in combined_help


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
    # Inverted: this half used to double the manifest and assert that the
    # duplicated rows made `coverage` exit 1 with the code in stdout. A repeated
    # work_id is ordinary append-only history, so the code must now be ABSENT and
    # the denominator available. Note what the doubling actually builds: the
    # fixture upserts one `archived` row and the file is then repeated verbatim,
    # so the two rows are byte-identical and this exercises the duplicate
    # *shape*, not a `needs_audio` -> `archived` transition. Consequently the
    # unique work_id count stays 1. The non-zero half moves to real damage: a
    # status outside VALID_STATUSES is still malformed.
    manifest_path.write_text(manifest_path.read_text() + manifest_path.read_text(), encoding="utf-8")
    diagnostic = run_module(["coverage", "--archive-root", str(tmp_path), "--format", "json"])
    assert "manifest_duplicate_work_id" not in diagnostic.stdout
    assert json.loads(diagnostic.stdout)["denominator"]["count"] == 1
    assert json.loads(diagnostic.stdout)["denominator"]["state"] == "available"
    assert_redacted(diagnostic)

    manifest_path.write_text(
        manifest_path.read_text()
        + json.dumps({"work_id": "BV1broken:p1", "bvid": "BV1broken",
                      "status": "no_such_status"})
        + "\n",
        encoding="utf-8",
    )
    malformed = run_module(["coverage", "--archive-root", str(tmp_path), "--format", "json"])
    assert malformed.returncode == 1
    assert "manifest_invalid_status" in malformed.stdout
    assert_redacted(malformed)


def test_module_verify_accepts_append_only_history(tmp_path: Path) -> None:
    """CLI-level pin: real state history → `verify` exit 0; real damage → exit 1.

    `cli.py` returns `0 if not payload["defects"] and not payload["diagnostics"]`,
    so the exit code is the contract, not the report's shape. The attempts sidecar
    must exist or `missing_attempts_sidecar` keeps the exit at 1 for an unrelated
    reason.
    """
    from bili_asr.archive import write_archive
    from bili_asr.manifest import ManifestStore

    row = {"work_id": "BV1hist:p1", "bvid": "BV1hist", "cid": 7, "page_index": 1,
           "pubdate_str": "20260828", "title": "A", "status": "needs_audio"}
    paths = write_archive(tmp_path, {**row, "status": "archived"},
                          [{"start": 0, "end": 1, "text": "ok"}], source="cc")
    store = ManifestStore(root=str(tmp_path))
    store.upsert(row)
    store.upsert({**row, "status": "audio_ok"})
    store.upsert({**row, "status": "archived", **paths})
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir(parents=True, exist_ok=True)
    attempts.write_text(json.dumps({
        "stage": "archive", "work_id": "BV1hist:p1", "attempt": 1, "outcome": "ok",
        "error_code": None, "artifact_paths": [],
        "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:01Z",
    }) + "\n", encoding="utf-8")

    healthy = run_module(["verify", "--archive-root", str(tmp_path), "--format", "json"])
    assert healthy.returncode == 0, healthy.stdout
    payload = json.loads(healthy.stdout)
    assert payload["defects"] == []
    assert payload["diagnostics"] == []
    assert_redacted(healthy)

    # Negative control: a status outside VALID_STATUSES is still malformed and
    # still fails the same command closed. It is appended to the file directly —
    # `ManifestStore.upsert` refuses an unknown status, and a corrupt row is
    # exactly what this half simulates.
    manifest_path = tmp_path / "manifest" / "manifest.jsonl"
    manifest_path.write_text(
        manifest_path.read_text()
        + json.dumps({"work_id": "BV1broke:p1", "bvid": "BV1broke",
                      "status": "no_such_status"})
        + "\n",
        encoding="utf-8",
    )
    assert run_module(["verify", "--archive-root", str(tmp_path),
                       "--format", "json"]).returncode == 1


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


def _reference_archive(tmp_path: Path, transcript: str = "Hello world") -> str:
    """One archived ASR row plus its SRT; returns the SRT's text for reference use."""

    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({
        "work_id": "BV1ref:p0",
        "bvid": "BV1ref",
        "page_index": 0,
        "cid": 900,
        "title": "Reference Video",
        "status": "archived",
        "duration_s": 30,
        "source": "asr",
    })
    srt_path = tmp_path / "transcripts" / "srt" / "BV1ref.p0.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text(
        f"1\n00:00:00,000 --> 00:00:04,000\n{transcript}\n", encoding="utf-8"
    )
    return transcript


def test_cli_main_coverage_quality_projects_content_reasons(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A3: content reasons appear per row and in the summary, advisory only."""

    from bili_asr import cli

    _reference_archive(tmp_path)

    exit_code = cli.main(["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    # No defect reason anywhere: the exit status and the validity count still
    # read the defect codes alone.
    assert exit_code == 0
    assert payload["summary"]["valid_work_items"] == 1
    assert payload["rows"][0]["reasons"] == []

    # The content-code counts are surfaced in the summary even at zero, which is
    # what makes the surface project the vocabulary rather than omit it.
    from bili_asr.quality import CONTENT_REASON_CODES, DEFECT_REASON_CODES

    for code in (*DEFECT_REASON_CODES, *CONTENT_REASON_CODES):
        assert code in payload["summary"], code
        assert payload["summary"][code] == 0


def test_cli_main_coverage_quality_reference_agreement_above_floor(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Agreement at or above the floor is reported without the reason."""

    from bili_asr import cli

    text = _reference_archive(tmp_path)
    reference = tmp_path / "second.srt"
    reference.write_text(f"1\n00:00:00,000 --> 00:00:04,000\n{text}\n", encoding="utf-8")

    exit_code = cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "json",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["reference"]["reference"] == "second.srt"
    assert payload["reference"]["agreement"] == 1.0
    assert payload["reference"]["floor"] == 0.95
    assert payload["reference"]["work_id"] == "BV1ref:p0"
    assert payload["reference"]["compared_chars"] == {"transcript": 10, "reference": 10}
    assert "reference_disagreement" not in payload["rows"][0]["reasons"]
    assert payload["summary"]["reference_disagreement"] == 0


def test_cli_main_coverage_quality_reference_disagreement_below_floor(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A contested reference emits the reason but still exits 0 — it is advisory."""

    from bili_asr import cli

    _reference_archive(tmp_path)
    reference = tmp_path / "other.srt"
    reference.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\n完全不同的另一份转写内容在此\n", encoding="utf-8"
    )

    exit_code = cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "json",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["rows"][0]["reasons"] == ["reference_disagreement"]
    assert payload["summary"]["reference_disagreement"] == 1
    # Advisory: the row is still valid because it has no defect.
    assert payload["summary"]["valid_work_items"] == 1
    assert payload["reference"]["agreement"] < payload["reference"]["floor"]


def test_cli_main_coverage_quality_reference_requires_exactly_one_row(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Zero or many selected rows is a diagnostic, never a traceback."""

    from bili_asr import cli
    from bili_asr.manifest import ManifestStore

    _reference_archive(tmp_path)
    reference = tmp_path / "second.srt"
    reference.write_text("1\n00:00:00,000 --> 00:00:04,000\nHello world\n", encoding="utf-8")

    # Two rows: the whole manifest plus one more row.
    ManifestStore(root=str(tmp_path)).upsert({
        "work_id": "BV1ref2:p0", "bvid": "BV1ref2", "cid": 901,
        "title": "Second", "status": "archived", "source": "asr",
    })
    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "json",
    ]) == 1
    captured = capsys.readouterr()
    assert "needs exactly one selected row" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err

    # Zero rows via an unknown scope.
    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality", "--scope", "BV1nope",
        "--reference", str(reference), "--format", "json",
    ]) == 1
    captured = capsys.readouterr()
    assert "needs exactly one selected row (got 0)" in captured.err
    assert "Traceback" not in captured.err


def test_cli_main_coverage_quality_reference_unreadable_is_a_diagnostic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing or text-free reference fails as a usage error, not a traceback."""

    from bili_asr import cli

    _reference_archive(tmp_path)

    # Absent path: caught before any row is analyzed.
    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(tmp_path / "absent.srt"), "--format", "json",
    ]) == 1
    captured = capsys.readouterr()
    assert "reference unreadable" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err

    # Present but with nothing to compare: refused, and named as such.
    blank = tmp_path / "blank.txt"
    blank.write_text("  \n\n", encoding="utf-8")
    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(blank), "--format", "json",
    ]) == 1
    captured = capsys.readouterr()
    assert "reference has no comparable text" in captured.err
    assert "Traceback" not in captured.err
    # The diagnostic names no path.
    assert str(tmp_path) not in captured.err


def test_cli_main_coverage_quality_reference_never_serializes_the_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Only the basename leaves the report — never the operator's path."""

    from bili_asr import cli

    _reference_archive(tmp_path)
    nested = tmp_path / "secret-dir" / "nested"
    nested.mkdir(parents=True)
    reference = nested / "second.srt"
    reference.write_text("1\n00:00:00,000 --> 00:00:04,000\nHello world\n", encoding="utf-8")

    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "json",
    ]) == 0
    out = capsys.readouterr().out

    assert json.loads(out)["reference"]["reference"] == "second.srt"
    # Neither the directory nor the absolute path may appear anywhere.
    assert "secret-dir" not in out
    assert str(nested) not in out


def test_cli_main_coverage_quality_reference_redacts_a_credential_like_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A reference named after a credential is reported as ``[redacted]``."""

    from bili_asr import cli

    _reference_archive(tmp_path)
    reference = tmp_path / "sessdata-backup.srt"
    reference.write_text("1\n00:00:00,000 --> 00:00:04,000\nHello world\n", encoding="utf-8")

    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["reference"]["reference"] == "[redacted]"
    assert "sessdata-backup" not in json.dumps(payload)


def test_cli_main_coverage_quality_reference_needs_quality_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--reference without --quality is a usage error, not a silent no-op."""

    from bili_asr import cli

    _reference_archive(tmp_path)
    reference = tmp_path / "second.srt"
    reference.write_text("1\n00:00:00,000 --> 00:00:04,000\nHello world\n", encoding="utf-8")

    assert cli.main([
        "coverage", "--archive-root", str(tmp_path),
        "--reference", str(reference), "--format", "json",
    ]) == 1
    captured = capsys.readouterr()
    assert "--reference requires --quality" in captured.err
    assert "Traceback" not in captured.err


def test_cli_main_coverage_quality_reference_keeps_csv_columns_frozen(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CSV keeps its frozen columns; the ratio goes to stderr instead."""

    from bili_asr import cli

    _reference_archive(tmp_path)
    reference = tmp_path / "second.srt"
    reference.write_text("1\n00:00:00,000 --> 00:00:04,000\nHello world\n", encoding="utf-8")

    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "csv",
    ]) == 0
    captured = capsys.readouterr()

    header = captured.out.splitlines()[0]
    assert "reference" not in header
    assert header.startswith("schema_version,scope,denominator_unit")
    assert "reference agreement 1.0000" in captured.err
    assert "second.srt" in captured.err


def test_cli_main_coverage_quality_reference_ignores_the_md_bundle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A published .md bundle never becomes the row's transcript for comparison.

    The row's artifacts are the bundle and the cue sidecar, in that manifest
    order — the shape in which the bundle used to win and report a fabricated
    disagreement against its own frontmatter.
    """

    from bili_asr import cli
    from bili_asr.manifest import ManifestStore

    text = "Hello world"
    raw = tmp_path / "transcripts" / "raw" / "BV1ref.p0.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(
        json.dumps(
            {"segments": [{"start": 0.0, "end": 4.0, "text": text, "confidence": 0.9}]}
        ),
        encoding="utf-8",
    )
    md = tmp_path / "transcripts" / "md" / "2026-01-02_BV1ref.p0_demo.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        '---\nbvid: "BV1ref"\ntitle: "Reference Video"\n'
        'url: "https://www.bilibili.com/video/BV1ref"\n---\n\n' + text + "\n",
        encoding="utf-8",
    )
    ManifestStore(root=str(tmp_path)).upsert({
        "work_id": "BV1ref:p0",
        "bvid": "BV1ref",
        "page_index": 0,
        "cid": 900,
        "title": "Reference Video",
        "status": "archived",
        "duration_s": 30,
        "source": "asr",
        "md_path": "transcripts/md/" + md.name,
        "raw_path": "transcripts/raw/" + raw.name,
    })
    reference = tmp_path / "second.srt"
    reference.write_text(f"1\n00:00:00,000 --> 00:00:04,000\n{text}\n", encoding="utf-8")

    exit_code = cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "json",
    ])
    payload = json.loads(capsys.readouterr().out)

    # The cue sidecar is the comparison source even though the bundle is named
    # first, so the exact match scores 1.0 and no reason is fabricated.
    assert exit_code == 0
    assert payload["reference"]["agreement"] == 1.0
    assert payload["reference"]["compared_chars"] == {"transcript": 10, "reference": 10}
    assert payload["rows"][0]["reasons"] == []
    assert payload["summary"]["reference_disagreement"] == 0
    assert payload["summary"]["valid_work_items"] == 1


def test_cli_main_coverage_quality_reference_json_without_segments_is_a_diagnostic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A JSON reference carrying no transcript is a usage error, not a ratio."""

    from bili_asr import cli

    _reference_archive(tmp_path)
    reference = tmp_path / "broken.json"
    reference.write_text('{"segments": [', encoding="utf-8")

    assert cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--reference", str(reference), "--format", "json",
    ]) == 1
    captured = capsys.readouterr()
    assert "reference unreadable" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_cli_main_coverage_quality_mixed_row_keeps_defect_reasons_first(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The merged row list is defect codes first, then the advisory ones.

    This is the one contract the merge creates: a consumer reading
    ``rows[].reasons`` sees the defect codes at the head of the list, so a
    defect is never pushed behind an advisory observation.  Swapping the
    projection to content-first leaves every other test green, so the order is
    pinned here on a row that carries both classes at once.
    """

    from bili_asr import cli
    from bili_asr.manifest import ManifestStore
    from bili_asr.quality import CONTENT_REASON_CODES, DEFECT_REASON_CODES

    store = ManifestStore(root=str(tmp_path))
    store.upsert({
        "work_id": "BV1mixed:p0",
        "bvid": "BV1mixed",
        "page_index": 0,
        "cid": 102,
        "title": "Mixed Video",
        "status": "archived",
        "duration_s": 20,
        "source": "asr",
    })
    overlong = (
        "今天的讨论围绕国际劳工仲裁这个主题展开，涉及多个国家的法律资源分配，"
        "以及普通劳动者在遇到纠纷时能够获得的支持方式与成本问题"
    )
    srt_path = tmp_path / "transcripts" / "srt" / "BV1mixed.p0.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    # Out-of-order overlapping cues (defect) carrying an over-long cue (content).
    srt_path.write_text(
        f"1\n00:00:03,000 --> 00:00:04,000\n{overlong}\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nB\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    reasons = payload["rows"][0]["reasons"]

    # Both classes are present, and the defect codes come first in the list.
    assert [r for r in reasons if r in DEFECT_REASON_CODES] == ["non_monotonic", "overlap"]
    assert [r for r in reasons if r in CONTENT_REASON_CODES] == ["overlong_cue"]
    assert reasons == ["non_monotonic", "overlap", "overlong_cue"]
    # The defect still drives validity and the exit status; the content reason
    # changes neither.
    assert exit_code == 1
    assert payload["summary"]["valid_work_items"] == 0
    assert payload["summary"]["overlong_cue"] == 1


def test_cli_main_coverage_quality_reference_without_row_text_reports_no_block(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A `--reference` on a row with no comparable text emits no `reference` block.

    The row here is defect-free — its SRT carries one cue with empty text — so
    it exits 0 with an empty reason list, and the comparison is simply not
    reported: a ratio that was never computed must not be fabricated (D3.6).
    README states this rule; this assertion is what keeps the statement true.
    """

    from bili_asr import cli
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({
        "work_id": "BV1notext:p0",
        "bvid": "BV1notext",
        "page_index": 0,
        "cid": 103,
        "title": "No Text Video",
        "status": "archived",
        "duration_s": 10,
        "source": "asr",
    })
    srt_path = tmp_path / "transcripts" / "srt" / "BV1notext.p0.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text("1\n00:00:00,000 --> 00:00:04,000\n\n", encoding="utf-8")
    reference = tmp_path / "second.txt"
    reference.write_text("hello world\n", encoding="utf-8")

    exit_code = cli.main([
        "coverage", "--archive-root", str(tmp_path), "--quality",
        "--scope", "BV1notext:p0", "--reference", str(reference), "--format", "json",
    ])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    # A clean row: no defect, no diagnostic, so exit 0 — and no invented ratio.
    assert exit_code == 0
    assert payload["rows"][0]["reasons"] == []
    assert payload["summary"]["valid_work_items"] == 1
    assert "reference" not in payload
    assert captured.err == ""
    assert "Traceback" not in captured.err


def test_cli_coverage_reference_help_states_the_plain_text_asymmetry(capsys: pytest.CaptureFixture[str]) -> None:
    """A malformed `.json` reference is refused; `.srt`/`.txt` read as plain text."""

    from bili_asr.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["coverage", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--reference" in help_text
    assert "plain text" in help_text


def test_cli_parser_exposes_reference_but_not_fail_under() -> None:
    """D3.8: the reference input exists; the retired exit knob is not ported."""

    from bili_asr.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["coverage", "--reference", "/tmp/second.srt"])
    assert args.reference == "/tmp/second.srt"
    assert parser.parse_args(["coverage"]).reference is None

    with pytest.raises(SystemExit):
        parser.parse_args(["coverage", "--fail-under", "0.5"])


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


def _low_confidence_archive(tmp_path: Path) -> str:
    """One archived ASR row whose raw sidecar records two doubtful cues.

    The cue at 12.5 s scores 0.30 (below `LOW_CONFIDENCE`), the one at 20.0 s
    scores 0.38 (also below), and the rest score comfortably above — so the
    locations are exactly `[12.5, 20.0]` and their count is 2.
    """

    from bili_asr.manifest import ManifestStore
    from bili_asr import archive as archive_module, asr as asr_module

    store = ManifestStore(root=str(tmp_path))
    store.upsert({
        "work_id": "BV1low:p0",
        "bvid": "BV1low",
        "page_index": 0,
        "cid": 901,
        "title": "Low Confidence Video",
        "status": "archived",
        "duration_s": 30,
        "source": "asr",
    })
    segments = [
        {"start": 0.0, "end": 4.0, "text": "开头这句很清楚", "confidence": 0.91},
        {"start": 12.5, "end": 16.0, "text": "中间这句听不清", "confidence": 0.30},
        {"start": 20.0, "end": 24.0, "text": "后面这句也含糊", "confidence": 0.38},
    ]
    entry = store.get("BV1low:p0")
    archive_module.write_archive(
        tmp_path, entry, segments, source="asr",
        asr_provenance={"model_name": "local-test-model", "device": "cpu"},
    )
    return "low"


def test_cli_main_coverage_quality_keeps_json_frozen_but_locates_the_doubt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R1 (this plan): the doubt's *location* is reachable without touching the contract.

    `specs/03-quality-surface.md` freezes `to_dict`'s keys, the CSV column tuple
    and `schema_version`, so the location list may not appear in the JSON
    document. It must still be *reachable* — a bare `low_confidence` code with no
    position is what the residual complaints about. The JSON half is asserted
    byte-stable here; the stderr half is asserted in the CSV test below.
    """

    from bili_asr import cli

    _low_confidence_archive(tmp_path)

    assert cli.main(
        ["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "json"]
    ) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    # The reason is still reported, and the frozen keys are untouched: no new
    # key anywhere in the document, on any row.
    row = payload["rows"][0]
    assert "low_confidence" in row["reasons"]
    assert payload["summary"]["low_confidence"] == 1
    assert set(row) == {
        "work_id", "source", "language", "status", "cue_count",
        "artifact_count", "reasons", "diagnostics",
    }
    assert set(payload) == {"schema_version", "scope", "denominator", "summary", "rows", "diagnostics"}
    # The machine-readable path stays machine-readable: no extra stderr line.
    assert "low-confidence at" not in captured.err


def test_cli_main_coverage_quality_csv_states_where_the_doubt_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CSV path is where the location reaches the operator, on stderr.

    CSV keeps its frozen columns, so — exactly like the reference-agreement
    ratio — the value goes to stderr beside a `coverage:` prefix. A row with no
    recorded scores emits nothing rather than a fabricated `0.0s`.
    """

    from bili_asr import cli

    _low_confidence_archive(tmp_path)

    assert cli.main(
        ["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "csv"]
    ) == 0
    captured = capsys.readouterr()

    # The header row is unchanged (the frozen column tuple), and the line names
    # the row and both doubtful positions, ascending, in seconds.
    header = captured.out.splitlines()[0]
    assert header.endswith("reasons,diagnostics")
    assert "low_confidence_at" not in header
    assert "coverage: BV1low:p0 low-confidence at 12.5s, 20.0s" in captured.err


def test_cli_main_coverage_quality_says_nothing_when_no_score_is_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No recorded score means no location — not a fabricated one.

    The same rule the reason already follows: an artifact without per-cue scores
    reports neither `low_confidence` nor a position, so an SRT-only row must
    stay silent on the new stderr line.
    """

    from bili_asr import cli

    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(tmp_path))
    store.upsert({
        "work_id": "BV1nos:p0",
        "bvid": "BV1nos",
        "page_index": 0,
        "cid": 902,
        "title": "Subtitle Video",
        "status": "archived",
        "duration_s": 30,
        "source": "subtitle",
    })
    srt_path = tmp_path / "transcripts" / "srt" / "BV1nos.p0.srt"
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\n这句没有分数记录\n", encoding="utf-8"
    )

    assert cli.main(
        ["coverage", "--archive-root", str(tmp_path), "--quality", "--format", "csv"]
    ) == 0
    captured = capsys.readouterr()
    assert "low_confidence" not in captured.out
    assert "low-confidence at" not in captured.err


def test_check_asr_env_runs_the_checkout_script(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented `bili-asr check-asr-env` exists and reaches the check.

    The README and spec 01 D1.2 both publish this invocation, but no subcommand
    implemented it — every documented call answered `invalid choice:
    'check-asr-env'`.  This pins the wiring: the command resolves the checkout's
    `scripts/check_asr_env.py`, runs it, and passes its exit status through.
    (The stages themselves are covered by `tests/test_check_asr_env.py`; here the
    script is replaced so the test asserts the plumbing, not the host.)
    """

    from bili_asr import cli

    script = tmp_path / "check_asr_env.py"
    script.write_text(
        "import sys\n"
        "def main(argv=None):\n"
        "    print('probe ran')\n"
        "    return 7\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BILI_ASR_CHECK_SCRIPT", str(script))

    exit_code = cli.main(["check-asr-env"])
    captured = capsys.readouterr()

    assert exit_code == 7, "the script's exit status passes through unchanged"
    assert "probe ran" in captured.out


def test_check_asr_env_reports_a_missing_script_instead_of_passing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing prerequisite is stated, never simulated as a pass."""

    from bili_asr import cli

    monkeypatch.setenv("BILI_ASR_CHECK_SCRIPT", str(tmp_path / "absent.py"))
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["check-asr-env"])
    captured = capsys.readouterr()

    # It falls back to the checkout script, which exists here, so a real run is
    # reported rather than a fabricated verdict: either way the exit code is the
    # check's own (0 or 1), never a silent success from a missing file.
    assert exit_code in (0, 1)
    assert "Traceback" not in captured.err


def test_check_asr_env_states_absence_when_no_script_exists_anywhere(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no candidate script the command names what it looked for and exits 1."""

    from bili_asr import cli

    monkeypatch.setenv("BILI_ASR_CHECK_SCRIPT", str(tmp_path / "absent.py"))
    monkeypatch.chdir(tmp_path)
    # Hide the checkout candidate by pointing the package at a directory whose
    # repository-relative scripts/ does not exist.
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "src" / "bili_asr" / "cli.py"))

    exit_code = cli.main(["check-asr-env"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "no check script found" in captured.err
    assert "BILI_ASR_CHECK_SCRIPT" in captured.err


# ------------------------------------------- the artifact root and retention flags (§9)


#: The twelve commands that touch an artifact path: spec §9's eleven in the table's
#: order, then the iteration's `publish-transcripts`, which carries the flag and no
#: retention pair (it publishes stored captions; it reclaims no audio).
ARTIFACT_ROOT_COMMANDS = (
    "asr", "pilot", "download-audio", "run", "schedule", "campaign",
    "coverage", "verify", "recover", "export", "search", "publish-transcripts",
)

#: The five that archive rows and therefore reclaim (spec §7).
RETENTION_COMMANDS = ("asr", "pilot", "run", "schedule", "campaign")

#: The six the flag is deliberately not on: none resolves an artifact path, and an
#: accepted-but-ignored flag would be a false statement about the interface (D18).
EXCLUDED_COMMANDS = (
    "fetch-meta", "status", "runs", "probe-subs", "harvest-subs", "derive-manifest",
)


def _command_help(command: str, capsys: pytest.CaptureFixture[str]) -> str:
    """One command's rendered help, whitespace-flattened.

    argparse re-wraps to the terminal width, so a phrase that spans a line break in one
    environment is one space in another; the assertions below are about what the help
    *says*, not about where it happens to wrap.
    """
    from bili_asr.cli import build_parser

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([command, "--help"])
    assert exc.value.code == 0
    return " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("command", ARTIFACT_ROOT_COMMANDS)
def test_artifact_root_is_declared_on_the_commands_that_honour_it(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """§9: the flag names its environment fallback and states its default."""
    help_text = _command_help(command, capsys)

    assert "--artifact-root" in help_text
    assert "BILI_ARTIFACT_ROOT" in help_text
    assert "default: the archive root" in help_text


@pytest.mark.parametrize("command", RETENTION_COMMANDS)
def test_the_retention_pair_is_declared_on_the_five_commands_that_reclaim(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """§7/D15: both spellings exist, and the default they resolve to is stated."""
    help_text = _command_help(command, capsys)

    assert "--keep-audio" in help_text
    assert "--no-keep-audio" in help_text
    assert "BILI_KEEP_AUDIO" in help_text
    assert "default: keep" in help_text


@pytest.mark.parametrize("command", EXCLUDED_COMMANDS)
def test_neither_flag_is_declared_on_the_commands_that_do_not_touch_artifacts(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """D18's exclusion half, from the operator's side: --help cannot promise a flag."""
    help_text = _command_help(command, capsys)

    assert "--artifact-root" not in help_text
    assert "--keep-audio" not in help_text


@pytest.mark.parametrize("command", ("pilot", "run", "schedule", "campaign"))
def test_the_cap_help_names_the_retention_interaction(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Q1(a)'s ruling: the cap keeps its semantics, and both help and skip line say how.

    Retaining audio means `audio/` only grows, so an operator who keeps it must be told
    what the lever is — the alternative the PM rejected was silently changing the shipped
    default.  The interaction itself holds in every mode of all four commands; *which*
    lever each command may name is pinned separately below, because `schedule` has a mode
    that refuses the one the other three accept (W-2/R8).
    """
    help_text = _command_help(command, capsys)

    assert "retained audio counts" in help_text


def test_the_cap_help_is_mode_scoped_for_schedule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """W-2/R8: `schedule` is the one command that refuses `--max-audio-gb 0` in a mode.

    The shared Q1 wording tells a retaining operator that `0` keeps the downloads coming.
    That is refused under `schedule --allow-long-live`
    (`long_live.refuse_disabled_audio_cap`), so `schedule` states the exception instead of
    the advice — a hint that is false in one mode is worse than an absent hint.  The three
    single-mode commands keep the lever, so the scoping is pinned in both directions.

    The anchors are hyphen-free on purpose: argparse re-wraps help, and it breaks a long
    token like `--max-audio-gb` across lines, so a flag literal is not a stable substring.
    """
    schedule_help = _command_help("schedule", capsys)

    assert "raises the cap" in schedule_help
    assert "--allow-long-live" in schedule_help
    assert "keeps downloading" not in schedule_help
    for command in ("pilot", "run", "campaign"):
        assert "keeps downloading" in _command_help(command, capsys)
        assert "raises the cap" not in _command_help(command, capsys)
