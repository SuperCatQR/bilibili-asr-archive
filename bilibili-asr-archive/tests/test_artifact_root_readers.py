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

from bili_asr.archive import archive_stem, write_archive
from bili_asr.artifact_root import ArtifactRootError, ArtifactRoots, roots_for
from bili_asr.coverage_report import CoverageReport
from bili_asr.export import STANDARD_CSV_COLUMNS, export_manifest
from bili_asr.integrity import (
    MALFORMED_ARTIFACT, MISSING_RAW_SUBTITLE, MISSING_TRANSCRIPT, IntegrityVerifier,
)
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
    root-relative ones (`transcripts/{stem}/bundle.srt`, `audio/{stem}.m4a`) — the
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

    The recorded strings are identical in shape (`transcripts/{stem}/bundle.srt`, D7),
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


def _legacy_caption_row(root: Path, bvid: str) -> dict:
    """The harvested-caption row §5's legacy case describes (`subtitles.py:143-165`).

    `harvest_subtitle` publishes exactly two files — the caption document under
    ``subtitles/raw/`` and the srt under ``transcripts/srt/`` — records ``srt_path``
    alone and marks the row ``subtitle_done``.  There is no txt, no md and no bundle
    marker, so no base can call this row's bundle complete: where it is graded is
    decided by the per-path probe alone, which is what makes it the shape to pin.
    """
    row = _row(bvid)
    stem = archive_stem(row)
    caption = root / "subtitles" / "raw" / f"{stem}.json"
    caption.parent.mkdir(parents=True, exist_ok=True)
    caption.write_text(json.dumps({"body": []}), encoding="utf-8")
    srt = root / "transcripts" / f"{stem}" / "bundle.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    # `json_to_srt` of an empty caption body: present, regular, and not a transcript.
    srt.write_text("", encoding="utf-8")
    return {**row, "status": "subtitle_done", "srt_path": f"transcripts/{stem}/bundle.srt"}


def test_a_legacy_caption_row_keeps_its_verdict_when_the_roots_are_configured(tmp_path: Path):
    """§10 `verify`: both bases are probed per recorded path, so no verdict moves with the flag.

    The reference run is the identity one, because that is the run this row was
    published under — `subtitles.py` wrote both files at the archive root.  Grading the
    row at the empty configured root alone would hide the defect that is really there
    (the empty caption) and invent one that is not (`missing_raw_subtitle` for a caption
    document that is present at the base that holds it).
    """
    archive = tmp_path / "state"
    artifact = tmp_path / "artifacts"
    artifact.mkdir(parents=True)  # an existing configured root, holding nothing
    archive.mkdir(parents=True)
    row = _legacy_caption_row(archive, "BVlegacy")
    _write_state(archive, [row])

    identity = IntegrityVerifier().verify(archive)
    configured = IntegrityVerifier().verify(
        archive, artifact_roots=ArtifactRoots.of(archive, artifact)
    )

    assert identity.checked == configured.checked == 1
    # The row is defective at the base that holds it, and the identity run says so.
    assert {(defect.work_id, defect.code) for defect in identity.defects} == {
        ("BVlegacy:p1", MALFORMED_ARTIFACT), ("BVlegacy:p1", MISSING_TRANSCRIPT),
    }
    assert MISSING_RAW_SUBTITLE not in {defect.code for defect in identity.defects}
    # Configuring a root cannot change which base answers for a recorded path.
    assert {(defect.work_id, defect.code) for defect in configured.defects} == {
        (defect.work_id, defect.code) for defect in identity.defects
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


def test_a_configured_root_behind_a_symlinked_ancestor_grades_the_same_rows(tmp_path: Path):
    """A symlinked *ancestor* is a legal configuration, and every reader must agree on it.

    `roots_for` refuses a symlinked root *itself* and nothing else (§3.2/§6), and the
    configured value is never `resolve()`d (D9) — so a root whose ancestor is a link
    reaches the readers exactly as the operator wrote it.  The containment probe is a
    different question from that identity comparison, and it has to be asked the way the
    sibling readers ask it: otherwise `verify` reads a bundle that is present at the base
    holding it as `missing_transcript` while `coverage` reports the same row present, in
    the same invocation, from the same roots.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    artifact = link / "artifacts"  # the configured root; its ancestor `link` is a symlink
    artifact.mkdir(parents=True)
    archive = tmp_path / "state"
    archive.mkdir(parents=True)
    assert not artifact.is_symlink() and artifact.is_dir()
    assert artifact.resolve() != artifact, "the fixture must exercise a symlinked ancestor"

    moved = _archived_row(artifact, "BVmoved")   # bundle + audio under the configured root
    legacy = _archived_row(archive, "BVlegacy")  # the mirror: both under the archive root
    _write_state(archive, [moved, legacy])

    # The boundary accepts the root and passes the lexical value on unchanged (§3.2/D9).
    roots = roots_for(archive, flag_value=str(artifact), environ={})
    assert str(roots.artifact_root) == str(artifact)

    coverage = {
        row["work_id"]: row["artifact_present"]
        for row in CoverageReport.build(archive, artifact_roots=roots).data["rows"]
    }
    assert coverage == {"BVmoved:p1": True, "BVlegacy:p1": True}
    # One invocation, one inventory: neither row is missing a transcript, whichever side
    # of the symlink its base is named from — and no other code is invented either.
    report = IntegrityVerifier().verify(archive, artifact_roots=roots)
    assert report.checked == 2
    assert MISSING_TRANSCRIPT not in {defect.code for defect in report.defects}
    assert report.defects == []
