"""Cross-reader cases for the configured artifact root (plan Task 3, spec §5/§10/§15).

One fixture, two archived rows: one whose bundle was published under the archive
root — the legacy case D6 promises to keep working — and one whose bundle lives under
the configured root.  Every reader that resolves a recorded artifact path must agree
with the writers about where that artifact lives, and must report the same inventory
as the single-base call that wrote the row; this file is the place where a silent
split between the two would show up.

Readers driven here: ``coverage_report.CoverageReport.build``,
``quality.QualityAnalyzer.analyze``, ``integrity.IntegrityVerifier.verify``,
``export.export_manifest`` and ``search_index.SearchIndex`` / ``search``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bili_asr.archive import write_archive
from bili_asr.artifact_root import ArtifactRootError, ArtifactRoots, roots_for
from bili_asr.coverage_report import CoverageReport
from bili_asr.export import STANDARD_CSV_COLUMNS, export_manifest
from bili_asr.integrity import MISSING_TRANSCRIPT, IntegrityVerifier
from bili_asr.quality import QualityAnalyzer
from bili_asr.search_index import SearchIndex, check_fts5_available, search

#: The word every fixture transcript carries; the title deliberately does not
#: contain it, so a hit proves the transcript text was really read.
MARKER_TEXT = "inventory"
PATH_KEYS = [key for key in STANDARD_CSV_COLUMNS if key.endswith("_path")]


def _row(bvid: str) -> dict:
    return {
        "work_id": f"{bvid}:p1", "bvid": bvid, "page_index": 1, "page_label": "Part 1",
        "cid": 101, "title": "Fixture", "status": "needs_audio", "duration_s": 1,
        "pubdate_str": "2026-01-01", "pubdate": 1600000000, "source": "cc",
    }


def _archived_row(root: Path, bvid: str, *, audio_at: Path | None = None) -> dict:
    """One archived row whose bundle is published under ``root``.

    Both products are real files, and the recorded strings are the shipped
    root-relative ones (`transcripts/srt/{stem}.srt`, `audio/{stem}.m4a`) — the
    fixture is exactly what the writers of Task 2 leave behind, so a reader that
    resolves either product against the wrong base is visible here.  ``audio_at``
    places the audio under a different base, which is the half-migrated state §5
    describes: each product is judged at the base that holds it, independently.
    """
    row = _row(bvid)
    paths = write_archive(
        root, {**row, "status": "archived"},
        [{"start": 0, "end": 1, "text": MARKER_TEXT}], source="cc",
    )
    audio = (root if audio_at is None else audio_at) / "audio" / f"{bvid}.p1.m4a"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"audio")
    return {
        **row, "status": "archived", "audio_path": f"audio/{bvid}.p1.m4a", **paths,
    }


def _attempt(work_id: str) -> dict:
    return {"stage": "archive", "work_id": work_id, "attempt": 1, "outcome": "ok",
            "error_code": None, "artifact_paths": [],
            "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:01Z"}


def _write_state(archive: Path, rows: list[dict]) -> None:
    """Write the manifest and the attempts ledger — both state, both at the archive root (D13)."""
    manifest = archive / "manifest" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    attempts = archive / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir(parents=True, exist_ok=True)
    attempts.write_text(
        "".join(json.dumps(_attempt(str(row["work_id"]))) + "\n" for row in rows),
        encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, ArtifactRoots, dict, dict, dict]:
    """``{archive}/state`` + ``{artifact}/artifacts`` and the three rows the readers must agree on.

    ``legacy`` was archived before the switch, ``moved`` after it, and ``split`` keeps
    its bundle at the archive root with its audio under the configured root — the
    half-migrated state §5 says each base answers for independently.
    """
    archive = tmp_path / "state"
    artifact = tmp_path / "artifacts"
    archive.mkdir(parents=True)
    artifact.mkdir(parents=True)
    legacy = _archived_row(archive, "BVlegacy")
    moved = _archived_row(artifact, "BVmoved")
    split = _archived_row(archive, "BVsplit", audio_at=artifact)
    _write_state(archive, [legacy, moved, split])
    return archive, artifact, ArtifactRoots.of(archive, artifact), legacy, moved, split


def test_the_same_fixture_reports_the_same_inventory_at_either_root(tmp_path: Path):
    """Every row is seen with the roots configured, each at the base that holds it.

    The recorded strings are identical in shape (`transcripts/srt/{stem}.srt`, D7),
    so only the ordered base list can tell the rows apart — which is exactly what
    "`coverage`, `verify`, `export`, `search` agree with the writers" means.
    """
    archive, artifact, roots, legacy, moved, split = _fixture(tmp_path)
    all_rows = ("BVlegacy:p1", "BVmoved:p1", "BVsplit:p1")

    coverage = CoverageReport.build(archive, artifact_roots=roots)
    assert {row["work_id"]: row["artifact_present"] for row in coverage.data["rows"]} == {
        "BVlegacy:p1": True, "BVmoved:p1": True, "BVsplit:p1": True,
    }
    # The audio probe walks the same ordered bases, so the half-migrated row's audio is
    # found under the configured root while its bundle stays at the archive root.
    assert {row["work_id"]: row["reclaimed_audio"] for row in coverage.data["rows"]} == {
        "BVlegacy:p1": False, "BVmoved:p1": False, "BVsplit:p1": False,
    }

    integrity = IntegrityVerifier().verify(archive, artifact_roots=roots)
    assert integrity.checked == 3
    assert integrity.defects == []

    exported = {
        row["work_id"]: row
        for row in json.loads(
            export_manifest(str(archive), "json", with_text=True, artifact_roots=roots)
        )
    }
    assert set(exported) == set(all_rows)
    for row in exported.values():
        # All five artifact path fields survive, and `--with-text` read the transcript.
        assert all(row[key] for key in PATH_KEYS)
        assert MARKER_TEXT in row["transcript_text"]

    analyzer = QualityAnalyzer()
    for row in (legacy, moved, split):
        assert "artifact_missing" not in analyzer.analyze(
            row, archive, artifact_roots=roots
        ).reasons

    assert check_fts5_available(), "SQLite FTS5 must be available in the test environment"
    index = SearchIndex(str(archive), artifact_roots=roots)
    assert index.build() == 3
    # `search.db` is state and never leaves the archive root (D13).
    assert index.db_path == str(archive / "search.db")
    assert not (artifact / "search.db").exists()
    assert {hit["work_id"] for hit in search(str(archive), MARKER_TEXT, artifact_roots=roots)} == set(
        all_rows
    )

    # With the roots omitted each reader reports what today's single-base call reports:
    # the rows whose bundles sit at the archive root resolve, the moved one does not.
    single_coverage = CoverageReport.build(archive)
    assert {row["work_id"]: row["artifact_present"] for row in single_coverage.data["rows"]} == {
        "BVlegacy:p1": True, "BVmoved:p1": False, "BVsplit:p1": True,
    }
    # The audio probe is only reached once a row's bundle resolves, and the archive
    # root does not hold the split row's audio — so `reclaimed_audio` turns true there.
    assert {row["work_id"]: row["reclaimed_audio"] for row in single_coverage.data["rows"]} == {
        "BVlegacy:p1": False, "BVmoved:p1": False, "BVsplit:p1": True,
    }
    single_defects = IntegrityVerifier().verify(archive).defects
    assert {defect.work_id for defect in single_defects} == {"BVmoved:p1"}
    assert {defect.code for defect in single_defects} == {MISSING_TRANSCRIPT}
    single_export = {
        row["work_id"]: row
        for row in json.loads(export_manifest(str(archive), "json", with_text=True))
    }
    assert MARKER_TEXT in single_export["BVlegacy:p1"]["transcript_text"]
    assert single_export["BVmoved:p1"]["transcript_text"] == ""
    assert "artifact_missing" not in analyzer.analyze(legacy, archive).reasons
    assert "artifact_missing" in analyzer.analyze(moved, archive).reasons
    # Rebuilt against the archive root alone, so only the rows whose transcripts are
    # there carry text — `search.db` is a cache and is not stale after the rebuild.
    assert SearchIndex(str(archive)).build() == 3
    assert {hit["work_id"] for hit in search(str(archive), MARKER_TEXT)} == {
        "BVlegacy:p1", "BVsplit:p1",
    }


def test_a_configured_root_that_is_absent_is_a_refusal_not_an_empty_inventory(tmp_path: Path):
    """An unusable configured root never becomes a usable empty base (spec §10, D17).

    The reader-side half of D17 is the ordered probe: a base that cannot be opened
    cannot hold an artifact, so the archive base still answers and the inventory is
    the legacy one — never empty.  The refusal line itself is rendered at the command
    boundary (§9, plan Task 4), which is why no reader has to interpret the state.
    """
    archive = tmp_path / "state"
    archive.mkdir(parents=True)
    legacy = _archived_row(archive, "BVlegacy")
    _write_state(archive, [legacy])
    absent = tmp_path / "unmounted"  # a mount point that was never mounted
    roots = ArtifactRoots.of(archive, absent)

    coverage = CoverageReport.build(archive, artifact_roots=roots)
    assert [row["artifact_present"] for row in coverage.data["rows"]] == [True]
    assert IntegrityVerifier().verify(archive, artifact_roots=roots).defects == []
    assert all(
        row[key]
        for row in json.loads(export_manifest(str(archive), "json", artifact_roots=roots))
        for key in PATH_KEYS
    )
    assert "artifact_missing" not in QualityAnalyzer().analyze(
        legacy, archive, artifact_roots=roots
    ).reasons
    assert check_fts5_available(), "SQLite FTS5 must be available in the test environment"
    assert [hit["work_id"] for hit in search(str(archive), MARKER_TEXT, artifact_roots=roots)] == [
        "BVlegacy:p1"
    ]

    # The refusal is the command boundary's: resolving the same absent root is rejected
    # before any reader runs, so a reader is never asked to interpret it (contract §9).
    with pytest.raises(ArtifactRootError):
        roots_for(archive, flag_value=str(absent), environ={})
