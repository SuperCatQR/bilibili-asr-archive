"""Real archive bundles pin quality/verify agreement on undeclared raw paths."""
from __future__ import annotations

import bili_asr.cli.main as _module_cli_main


import json
from pathlib import Path

import pytest

from bili_asr import cli
from bili_asr.archive import archive_bundle_complete, write_archive
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.integrity import IntegrityVerifier
from bili_asr.manifest import ManifestStore
from bili_asr.quality import QualityAnalyzer


def _archive(root: Path, artifact_root: Path | None = None) -> dict:
    root.mkdir()
    write_base = artifact_root or root
    if write_base != root:
        write_base.mkdir()
    row = {
        "work_id": "BVrawcheck:p0", "bvid": "BVrawcheck", "page_index": 0,
        "cid": 10, "title": "Raw containment", "status": "archived",
        "source": "asr", "duration_s": 3,
    }
    paths = write_archive(write_base, row, [
        {"start": 0, "end": 1, "text": "first complete cue"},
        {"start": 1, "end": 2, "text": "second complete cue"},
    ], source="asr")
    assert archive_bundle_complete(write_base, paths)
    row.update(paths)
    ManifestStore(root).upsert(row)
    return row


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def _quality_payload(root: Path, capsys, *, artifact_root: Path | None = None) -> tuple[int, dict]:
    argv = ["coverage", "--archive-root", str(root), "--quality", "--format", "json"]
    if artifact_root is not None:
        argv.extend(["--artifact-root", str(artifact_root)])
    code = _module_cli_main.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_complete_declared_bundle_needs_no_caption_raw_and_counts_cues_once(tmp_path: Path, capsys):
    root = tmp_path / "archive"
    row = _archive(root)

    result = QualityAnalyzer().analyze(row, root)

    assert result.reasons == ()
    assert result.cue_count == 2
    assert result.artifact_count == 4
    assert IntegrityVerifier().verify(root).defects == []
    code, payload = _quality_payload(root, capsys)
    assert code == 0
    assert payload["rows"][0]["cue_count"] == 2
    assert payload["rows"][0]["reasons"] == []


@pytest.mark.parametrize("link_kind", ["directory", "file"])
@pytest.mark.parametrize("target_exists", [True, False])
def test_declared_bundle_cannot_hide_outside_caption_raw(
    tmp_path: Path, capsys, link_kind: str, target_exists: bool,
):
    root = tmp_path / "archive"
    row = _archive(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "BVrawcheck.p0.json"
    if target_exists:
        # Content would be malformed if either reader followed the escape.
        target.write_text("outside sentinel", encoding="utf-8")
    if link_kind == "directory":
        _symlink(root / "subtitles" / "raw", outside, directory=True)
    else:
        _symlink(root / "subtitles" / "raw" / target.name, target)
    before = {path.name: path.read_bytes() for path in outside.iterdir()}

    result = QualityAnalyzer().analyze(row, root)
    integrity = IntegrityVerifier().verify(root)

    assert result.reasons == ("identity_unconfined",)
    assert result.cue_count == 2
    assert result.artifact_count == 4
    assert {item.code for item in integrity.defects} == {"identity_path_mismatch"}
    assert _module_cli_main.main(["verify", "--archive-root", str(root), "--format", "json"]) == 1
    capsys.readouterr()
    code, payload = _quality_payload(root, capsys)
    assert code == 1
    assert payload["rows"][0]["reasons"] == ["identity_unconfined"]
    assert payload["rows"][0]["cue_count"] == 2
    assert {path.name: path.read_bytes() for path in outside.iterdir()} == before


@pytest.mark.parametrize("escape_all_bases", [True, False])
def test_raw_containment_uses_each_read_base_without_adding_missing_alternatives(
    tmp_path: Path, capsys, escape_all_bases: bool,
):
    root = tmp_path / "archive"
    artifact_root = tmp_path / "artifacts"
    row = _archive(root, artifact_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink(artifact_root / "subtitles" / "raw", outside, directory=True)
    if escape_all_bases:
        _symlink(root / "subtitles" / "raw", outside, directory=True)
    roots = ArtifactRoots.of(root, artifact_root)

    result = QualityAnalyzer().analyze(row, root, artifact_roots=roots)
    integrity = IntegrityVerifier().verify(root, artifact_roots=roots)

    expected = ("identity_unconfined",) if escape_all_bases else ()
    assert result.reasons == expected
    assert result.cue_count == 2
    assert result.artifact_count == 4
    assert {item.code for item in integrity.defects} == (
        {"identity_path_mismatch"} if escape_all_bases else set()
    )
    code, payload = _quality_payload(root, capsys, artifact_root=artifact_root)
    assert code == int(escape_all_bases)
    assert payload["rows"][0]["reasons"] == list(expected)


def test_declared_srt_cannot_hide_an_escaping_archive_raw_candidate(tmp_path: Path):
    root = tmp_path / "archive"
    archived = _archive(root)
    outside = tmp_path / "outside.json"
    outside.write_text("outside sentinel", encoding="utf-8")
    raw = root / archived["raw_path"]
    raw.unlink()
    _symlink(raw, outside)
    # An in-flight row names its usable SRT while the archive raw route escapes.
    row = {
        key: value for key, value in archived.items()
        if key not in {"raw_path", "txt_path", "md_path"}
    }
    row["status"] = "needs_audio"
    ManifestStore(root).upsert(row)

    result = QualityAnalyzer().analyze(row, root)

    assert result.reasons == ("identity_unconfined",)
    assert result.cue_count == 2
    assert result.artifact_count == 1
    assert {item.code for item in IntegrityVerifier().verify(root).defects} == {
        "identity_path_mismatch", "retryable_incomplete",
    }
    assert outside.read_text(encoding="utf-8") == "outside sentinel"
