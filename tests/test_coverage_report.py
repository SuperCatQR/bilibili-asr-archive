"""Fixture-driven behavioral coverage for the read-only coverage projection."""
from __future__ import annotations

import bili_asr.cli.main as _module_cli_main
import bili_asr.cli.status_cmd as _module_cli_status_cmd


import csv
import json
from pathlib import Path

import pytest

from bili_asr.archive import write_archive
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.coverage_report import CoverageReport
from bili_asr.sidecar_projection import is_plain_cli_archive
from tests.support.coverage_report import NOW, cursor, ledger, scheduler



def test_plain_cli_archive_requires_an_explicit_completed_stage_producer() -> None:
    assert is_plain_cli_archive({
        "BVasr:p1": {"status": "archived", "source": "asr", "archive_producer": "stage-cli"},
        "BVcc:p1": {"status": "archived", "source": "subtitle", "archive_producer": "stage-cli"},
    })
    assert not is_plain_cli_archive({
        "BVpending:p1": {"status": "audio_ok", "source": "asr", "archive_producer": "stage-cli"},
    })
    assert not is_plain_cli_archive({
        "BVpublished:p1": {"status": "archived", "source": "unknown", "archive_producer": "stage-cli"},
    })


def manifest_row(work_id: str, status: str = "archived", *, bvid: str | None = None) -> dict:
    return {
        "work_id": work_id, "bvid": bvid or work_id.split(":")[0], "page_index": 1,
        "page_label": "Part 1", "cid": 101, "title": "Marker", "status": status,
        "pubdate_str": "2026-01-01", "duration_s": 1,
    }








def attempt(work_id: str, outcome: str = "ok", number: int = 1, stage: str = "archive") -> dict:
    return {"stage": stage, "work_id": work_id, "attempt": number, "outcome": outcome,
            "error_code": None, "artifact_paths": [], "started_at": NOW, "finished_at": NOW}


def write_fixture(root: Path, rows: list[dict], *, cur=None, sched=None, ledgers=None, attempts=None):
    (root / "manifest").mkdir(parents=True)
    (root / "manifest" / "manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    if cur is not None:
        (root / "meta-cursor.json").write_text(json.dumps(cur), encoding="utf-8")
    if sched is not None:
        (root / "scheduler.json").write_text(json.dumps(sched), encoding="utf-8")
    if ledgers is not None:
        (root / "run-ledger.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in ledgers), encoding="utf-8")
    if attempts is not None:
        (root / "coordinator").mkdir()
        (root / "coordinator" / "attempts.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in attempts), encoding="utf-8")


def codes(report):
    return {item["code"] for item in report.data["diagnostics"]}


def _archived_rows(root: Path, *work_ids: str) -> list[dict]:
    """Manifest rows for archived work_ids, each carrying a real state history.

    Every returned work_id contributes two rows (`needs_audio` → `archived`) and
    a complete transcript bundle, so the append-only shape — not the single-row
    shape — is what a caller's fixture exercises. `write_fixture` rewrites only
    the manifest, so the bundles survive the caller's `write_fixture(...)` call.
    """
    rows: list[dict] = []
    for work_id in work_ids:
        row = manifest_row(work_id, "needs_audio")
        paths = write_archive(root, {**row, "status": "archived"},
                              [{"start": 0, "end": 1, "text": "marker"}], source="cc")
        rows += [row, {**row, "status": "archived", **paths}]
    return rows


def test_bvid_only_legacy_manifest_row_remains_checkable(tmp_path: Path):
    row = manifest_row("BVlegacy:p1")
    row.pop("work_id")
    write_fixture(tmp_path, [row])

    report = CoverageReport.build(tmp_path)

    assert report.data["denominator"]["count"] == 1
    assert report.data["rows"][0]["work_id"] == "BVlegacy"
    assert "manifest_invalid_bvid" not in codes(report)


def test_short_transcript_coverage_is_a_health_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A published row with a measured shortfall cannot read as clean coverage."""

    row = manifest_row("BVshort:p1")
    row.update({
        "coverage": 0.802,
        "coverage_min": 0.97,
        "coverage_short": True,
    })
    monkeypatch.setattr(
        "bili_asr.coverage_report.project_manifest_records",
        lambda *_args, **_kwargs: ({row["work_id"]: row}, "available", set()),
    )

    report = CoverageReport.build(tmp_path)

    assert "transcript_coverage_short" in codes(report)
    projected = report.data["rows"][0]
    assert projected["coverage"] == pytest.approx(0.802)
    assert projected["coverage_short"] is True
    assert report.to_csv().splitlines()[0].endswith(
        ",coverage,coverage_short,evidence_summary,diagnostic_summary"
    )


def test_complete_evidence_has_stable_cumulative_and_batch_totals(tmp_path: Path):
    rows = [manifest_row("BVone:p1"), manifest_row("BVtwo:p1")]
    for row in rows:
        path = tmp_path / "transcripts" / "BVone.p1" / "bundle.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker", encoding="utf-8")
        break
    write_fixture(tmp_path, rows, cur=cursor(), sched=scheduler(),
                  ledgers=[ledger()], attempts=[attempt("BVone:p1"), attempt("BVtwo:p1")])
    report = CoverageReport.build(tmp_path)
    assert report.data["denominator"] == {"unit": "work_items", "count": 2,
        "state": "available", "source": "manifest_snapshot"}
    assert report.data["cumulative"]["total"] == 2
    assert report.data["batch"]["total"] == 2
    assert report.data["batch"]["complete"] <= 2
    assert [r["work_id"] for r in report.data["rows"]] == ["BVone:p1", "BVtwo:p1"]


@pytest.mark.parametrize("state,code", [("limited", "scheduler_noncomplete"),
                                         ("risk_interrupted", "scheduler_noncomplete")])
def test_limited_and_risk_interrupted_are_preserved(tmp_path: Path, state: str, code: str):
    write_fixture(tmp_path, [manifest_row("BVone:p1")], cur=cursor(state),
                  sched=scheduler(state, ["BVone:p1"]), ledgers=[ledger(["BVone:p1"])])
    report = CoverageReport.build(tmp_path)
    assert report.data["evidence"]["scheduler"]["state"] == "available"
    assert code in codes(report)
    assert report.data["cumulative"]["state"] != "complete"


def test_cumulative_differs_from_latest_batch(tmp_path: Path):
    rows = [manifest_row("BVone:p1"), manifest_row("BVtwo:p1", "meta_ok")]
    write_fixture(tmp_path, rows, cur=cursor(), sched=scheduler(ids=["BVone:p1"]),
                  ledgers=[ledger(["BVone:p1"])])
    report = CoverageReport.build(tmp_path)
    assert report.data["cumulative"]["total"] == 2
    assert report.data["batch"]["total"] == 1


def test_latest_retryable_failed_and_skipped_attempts_diagnose(tmp_path: Path):
    rows = [manifest_row("BVone:p1", "meta_ok"), manifest_row("BVtwo:p1", "meta_ok")]
    attempts = [attempt("BVone:p1", "failed", 1), attempt("BVone:p1", "ok", 2),
                attempt("BVtwo:p1", "skipped", 3)]
    write_fixture(tmp_path, rows, attempts=attempts)
    report = CoverageReport.build(tmp_path)
    assert "retryable_attempt" in codes(report)
    assert report.data["rows"][0]["status"] == "meta_ok"


def test_append_only_manifest_history_keeps_denominator_available(tmp_path: Path):
    """A repeated work_id is ordinary history, NOT a failure.

    Inverted: this test used to be `test_duplicate_manifest_makes_denominator_unavailable`
    and pinned the old contract by asserting `count is None` plus the code's
    presence. Append-only state history is the store's normal encoding, so the
    same input must now reach the opposite verdict.
    """
    write_fixture(tmp_path, [manifest_row("BVone:p1", "needs_audio"),
                            manifest_row("BVone:p1", "audio_ok"),
                            manifest_row("BVone:p1")])
    report = CoverageReport.build(tmp_path)
    assert report.data["denominator"]["count"] == 1
    assert report.data["denominator"]["state"] == "available"
    assert "manifest_duplicate_work_id" not in codes(report)


@pytest.mark.parametrize("name,relative,payload", [
    ("cursor", "meta-cursor.json", "{}"), ("scheduler", "scheduler.json", "{}"),
    ("ledger", "run-ledger.jsonl", "{bad"), ("attempts", "coordinator/attempts.jsonl", "{bad")])
def test_malformed_sidecars_are_named(tmp_path: Path, name: str, relative: str, payload: str):
    write_fixture(tmp_path, [manifest_row("BVone:p1")])
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    report = CoverageReport.build(tmp_path)
    assert "sidecar_malformed" in codes(report)
    assert report.data["denominator"]["state"] == "available"


def test_stale_and_contradictory_sidecar_ids(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")], cur=cursor(),
        sched=scheduler(ids=["BVone:p1", "BVstale:p1"]),
        ledgers=[ledger(["BVother:p1"])])
    report = CoverageReport.build(tmp_path)
    assert {"stale_evidence", "scheduler_ledger_mismatch"} <= codes(report)


def test_attempt_absent_from_manifest_is_diagnostic(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")], attempts=[attempt("BVmissing:p1")])
    assert "attempt_not_in_manifest" in codes(CoverageReport.build(tmp_path))


def test_terminal_archived_without_transcript_is_not_complete(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")])
    report = CoverageReport.build(tmp_path)
    assert "terminal_missing_artifact" in codes(report)
    assert report.data["rows"][0]["cumulative_complete"] is False


def test_reclaimed_audio_uses_page_aware_artifact_path(tmp_path: Path):
    row = manifest_row("BVone:p1")
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "marker"}], source="asr")
    row.update(paths)
    write_fixture(tmp_path, [row])
    report = CoverageReport.build(tmp_path)
    assert report.data["rows"][0]["artifact_present"] is True
    assert report.data["rows"][0]["reclaimed_audio"] is True


@pytest.mark.parametrize("scope,expected", [("pending", {"BVone:p1"}),
    ("failed", {"BVone:p1"}), ("BVone:p1", {"BVone:p1"}), ("BVone", {"BVone:p1"})])
def test_supported_scopes(tmp_path: Path, scope: str, expected: set[str]):
    rows = [manifest_row("BVone:p1", "meta_ok"), manifest_row("BVtwo:p1")]
    write_fixture(tmp_path, rows, attempts=[attempt("BVone:p1", "failed")])
    assert {r["work_id"] for r in CoverageReport.build(tmp_path, scope=scope).data["rows"]} == expected


def test_archived_audio_symlink_and_unsupported_extension_are_not_reclaimed(tmp_path: Path):
    row = manifest_row("BVone:p1")
    paths = write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "marker"}], source="asr")
    row.update(paths)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    outside = tmp_path / "outside.m4a"
    outside.write_bytes(b"audio")
    (audio_dir / "bad.m4a").symlink_to(outside)
    row["audio_path"] = "audio/bad.m4a"
    write_fixture(tmp_path, [row])
    report = CoverageReport.build(tmp_path)
    assert report.data["rows"][0]["reclaimed_audio"] is True
    report = CoverageReport.build(tmp_path)
    assert report.data["rows"][0]["reclaimed_audio"] is True


def test_unknown_scope_is_unavailable(tmp_path: Path):
    write_fixture(tmp_path, [manifest_row("BVone:p1")])
    report = CoverageReport.build(tmp_path, scope="no-such-work")
    assert report.data["denominator"]["state"] == "unavailable"
    assert "unknown_scope" in codes(report)


def test_json_csv_bytes_and_empty_summary_are_exact(tmp_path: Path):
    write_fixture(tmp_path, [])
    report = CoverageReport.build(tmp_path)
    assert report.to_json().encode() == report.to_json().encode()
    assert report.to_csv().encode() == report.to_csv().encode()
    parsed = list(csv.DictReader(report.to_csv().splitlines()))
    assert len(parsed) == 1 and parsed[0]["category"] == "summary"


def test_ordinary_history_diagnostics_membership_is_pinned():
    """The set that subtracts a diagnostic inside three exit rules is frozen.

    `ORDINARY_HISTORY_DIAGNOSTICS` is consumed by name at the three readers
    (`coverage_report`, `integrity`, `cli`) and again in the exit rules those
    readers gate, so widening it here would silently neutralise a fourth code
    everywhere at once — the failure mode this plan closed. Pinned like the
    repo's other frozen vocabularies.
    """
    from bili_asr.sidecar_projection import ORDINARY_HISTORY_DIAGNOSTICS

    assert ORDINARY_HISTORY_DIAGNOSTICS == frozenset({"manifest_duplicate_work_id"})


def test_all_evidence_bytes_and_mtimes_remain_unchanged(tmp_path: Path):
    files = {}
    write_fixture(tmp_path, [manifest_row("BVone:p1")], cur=cursor(), sched=scheduler(),
                  ledgers=[ledger()], attempts=[attempt("BVone:p1")])
    for path in (tmp_path / "manifest/manifest.jsonl", tmp_path / "meta-cursor.json",
                 tmp_path / "scheduler.json", tmp_path / "run-ledger.jsonl",
                 tmp_path / "coordinator/attempts.jsonl"):
        files[path] = (path.read_bytes(), path.stat().st_mtime_ns)
    CoverageReport.build(tmp_path)
    assert all(path.read_bytes() == data and path.stat().st_mtime_ns == mtime
               for path, (data, mtime) in files.items())




def test_cli_returns_diagnostic_exit(tmp_path: Path):
    """`coverage` still exits non-zero, but only for real damage.

    Inverted: this case used to double the manifest (an ordinary append-only
    history transition) and assert that made `coverage` non-zero. The duplicate
    is no longer a failure; a materially malformed input still is.
    """
    from bili_asr import cli

    # The archive must be otherwise healthy or an unrelated `terminal_missing_artifact`
    # keeps the exit at 1 and masks the assertion being pinned.
    rows = _archived_rows(tmp_path, "BVone:p1")
    write_fixture(tmp_path, rows, cur=cursor(), sched=scheduler(ids=["BVone:p1"]),
                  ledgers=[ledger(["BVone:p1"])], attempts=[attempt("BVone:p1")])
    assert _module_cli_main.main(["coverage", "--archive-root", str(tmp_path), "--format", "json"]) == 0

    # An unknown manifest status is outside the vocabulary and names no verdict
    # other than malformed, so it keeps the command failing closed. It is
    # appended to the file directly: `ManifestStore.upsert` refuses to write an
    # unknown status, and a corrupt row is exactly what is being simulated.
    manifest_path = tmp_path / "manifest" / "manifest.jsonl"
    unknown = manifest_row("BVtwo:p1")
    unknown["status"] = "no_such_status"
    manifest_path.write_text(
        manifest_path.read_text() + json.dumps(unknown) + "\n", encoding="utf-8")
    assert _module_cli_main.main(["coverage", "--archive-root", str(tmp_path), "--format", "json"]) == 1


def test_healthy_append_only_archive_reaches_exit_zero(tmp_path: Path):
    """Two-way pin: healthy state history → exit 0 with a resolved denominator.

    The exit-0 half needs every sidecar valid — an absent cursor, scheduler or
    run-ledger reports `evidence_missing` and keeps the exit at 1 for a reason
    unrelated to the manifest definition. Both work_ids carry a real state
    history so the target of the pin is the append-only shape, not a single row.
    """
    from bili_asr import cli

    rows = _archived_rows(tmp_path, "BVone:p1", "BVtwo:p1")
    write_fixture(tmp_path, rows, cur=cursor(), sched=scheduler(),
                  ledgers=[ledger()], attempts=[attempt("BVone:p1"), attempt("BVtwo:p1")])
    report = CoverageReport.build(tmp_path)

    assert report.data["denominator"] == {"unit": "work_items", "count": 2,
        "state": "available", "source": "manifest_snapshot"}
    assert report.data["cumulative"]["state"] == "complete"
    assert "manifest_duplicate_work_id" not in codes(report)   # no exit-driving code
    assert _module_cli_main.main(["coverage", "--archive-root", str(tmp_path), "--format", "json"]) == 0

    # Negative control: the same archive with one genuinely malformed row still
    # fails closed — the fix is bidirectional, not a blanket silence. Appended
    # directly, since `ManifestStore.upsert` refuses an unknown status and a
    # corrupt row is what this half simulates.
    manifest_path = tmp_path / "manifest" / "manifest.jsonl"
    malformed = manifest_row("BVthree:p1")
    malformed["status"] = "no_such_status"
    manifest_path.write_text(
        manifest_path.read_text() + json.dumps(malformed) + "\n", encoding="utf-8")
    assert _module_cli_main.main(["coverage", "--archive-root", str(tmp_path), "--format", "json"]) == 1


def test_coverage_quality_accepts_append_only_history(tmp_path: Path):
    """`coverage --quality` reaches the same verdict on the same archive (§3.3).

    `--quality` reads the row's own artifacts, so the archive needs a real
    transcript bundle rather than a manifest row alone — otherwise the row
    reports `artifact_missing` and the exit stays 1 for a reason unrelated to
    the manifest definition.
    """
    from bili_asr import cli

    rows = _archived_rows(tmp_path, "BVone:p1")
    write_fixture(tmp_path, rows, cur=cursor(), sched=scheduler(ids=["BVone:p1"]),
                  ledgers=[ledger(["BVone:p1"])], attempts=[attempt("BVone:p1")])
    assert _module_cli_main.main(["coverage", "--archive-root", str(tmp_path), "--quality",
                     "--format", "json"]) == 0

    # Fail-closed half: `--quality` is the third changed reader and spec §3.3
    # requires a genuinely malformed row to still fail it. Both the archive and
    # the extra row are the ones `test_cli_returns_diagnostic_exit` uses, so the
    # two readers are pinned against the same healthy input and the same damage.
    manifest_path = tmp_path / "manifest" / "manifest.jsonl"
    malformed = manifest_row("BVtwo:p1")
    malformed["status"] = "no_such_status"
    manifest_path.write_text(
        manifest_path.read_text() + json.dumps(malformed) + "\n", encoding="utf-8")
    assert _module_cli_main.main(["coverage", "--archive-root", str(tmp_path), "--quality",
                     "--format", "json"]) == 1


def test_a_configured_artifact_root_is_reported_as_present(tmp_path: Path):
    """A row's bundle is found at whichever base holds it (contract §5/§10, D8).

    The recorded strings never change (D7), so the only thing deciding whether a
    row's artifacts are visible is the base list the reader walks. One row is
    written under the archive root (the legacy case D6 protects) and one under the
    configured root; both must report `artifact_present`.
    """
    archive = tmp_path / "state"
    artifact = tmp_path / "artifacts"
    archive.mkdir(parents=True)
    artifact.mkdir(parents=True)
    legacy = _archived_rows(archive, "BVlegacy:p1")
    moved = _archived_rows(artifact, "BVmoved:p1")
    write_fixture(archive, legacy + moved, cur=cursor(), sched=scheduler(),
                  ledgers=[ledger()], attempts=[attempt("BVlegacy:p1"), attempt("BVmoved:p1")])
    moved_srt = moved[-1]["srt_path"]

    report = CoverageReport.build(archive, artifact_roots=ArtifactRoots.of(archive, artifact))

    assert {row["work_id"]: row["artifact_present"] for row in report.data["rows"]} == {
        "BVlegacy:p1": True, "BVmoved:p1": True,
    }
    assert "terminal_missing_artifact" not in codes(report)
    # Nothing was copied between the bases: the configured row's bundle is only there.
    assert not (archive / moved_srt).exists()
    assert (artifact / moved_srt).is_file()

    # Control: with the roots omitted the configured row is graded against the archive
    # root alone — today's single-base behaviour, unchanged (D6, §11).
    single = CoverageReport.build(archive)
    assert {row["work_id"]: row["artifact_present"] for row in single.data["rows"]} == {
        "BVlegacy:p1": True, "BVmoved:p1": False,
    }
