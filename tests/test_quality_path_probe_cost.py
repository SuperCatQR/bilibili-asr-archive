"""Quality enumeration is bounded without retaining stale confinement answers."""

from __future__ import annotations

import bili_asr.cli.main as _module_cli_main


from collections import Counter
import json
from pathlib import Path

import pytest

from bili_asr import cli, quality
from bili_asr.artifact_root import ArtifactRoots, resolve_audio_path
from bili_asr.manifest import ManifestStore
from bili_asr.quality import QualityAnalyzer


def _row(index: int = 0) -> dict:
    return {
        "bvid": f"BVcost{index}", "work_id": f"BVcost{index}:p0",
        "page_index": 0, "cid": index + 1, "status": "needs_audio",
    }


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def test_real_quality_cli_does_not_resolve_each_base_for_every_absent_candidate(
    tmp_path: Path, monkeypatch, capsys,
):
    root = tmp_path / "archive"
    artifacts = tmp_path / "artifacts"
    root.mkdir()
    artifacts.mkdir()
    store = ManifestStore(root)
    for index in range(100):
        store.upsert(_row(index))
    store.save()
    counts = Counter()
    original = Path.resolve

    def observed(path, *args, **kwargs):
        counts["base" if path in (root, artifacts) else "candidate"] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", observed)
    assert _module_cli_main.main([
        "coverage", "--archive-root", str(root), "--artifact-root", str(artifacts),
        "--quality", "--format", "json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["rows"]) == 100
    assert all(row["reasons"] == ["artifact_missing"] for row in payload["rows"])
    # The old real CLI did at least 3,000 resolves. Include command setup in
    # the measured budget, and leave room for its unrelated root probes.
    assert sum(counts.values()) < 1_300, counts
    assert counts["base"] < 400, counts


@pytest.mark.parametrize("family", ["caption", "archive"])
@pytest.mark.parametrize("exists", [False, True])
@pytest.mark.parametrize("link_kind", ["file", "directory"])
def test_absent_inferred_raw_still_reports_real_escaping_symlinks(
    tmp_path: Path, family: str, exists: bool, link_kind: str,
):
    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    relative = (
        Path("subtitles/raw/BVcost0.p0.json") if family == "caption"
        else Path("transcripts/BVcost0.p0/bundle.raw.json")
    )
    target = outside / relative.name
    if exists:
        target.write_text("outside sentinel", encoding="utf-8")
    if link_kind == "file":
        _symlink(root / relative, target)
    else:
        _symlink(root / relative.parent, outside, directory=True)

    result = QualityAnalyzer().analyze(_row(), root)

    assert "identity_unconfined" in result.reasons
    assert "malformed" not in result.reasons
    assert result.artifact_count == 0
    if exists:
        assert target.read_text(encoding="utf-8") == "outside sentinel"


def test_same_analyzer_and_roots_recheck_retargeted_root_ancestor(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    txt = first / "transcripts/BVcost0.p0/bundle.txt"
    txt.parent.mkdir(parents=True)
    txt.write_text("the in-flight transcript body", encoding="utf-8")
    # When the archive root moves to second, first's transcript is outside it.
    _symlink(second / "transcripts", first / "transcripts", directory=True)
    alias = tmp_path / "active"
    _symlink(alias, first, directory=True)
    roots = ArtifactRoots.of(alias)
    analyzer = QualityAnalyzer()

    assert analyzer.analyze(_row(), alias, artifact_roots=roots).reasons == ()
    alias.unlink()
    _symlink(alias, second, directory=True)

    result = analyzer.analyze(_row(), alias, artifact_roots=roots)

    assert result.reasons == ("identity_unconfined",)
    assert result.artifact_count == 0


def test_containment_is_fresh_between_enumeration_and_read(tmp_path: Path, monkeypatch):
    root = tmp_path / "archive"
    root.mkdir()
    inside = root / "transcripts/BVcost0.p0"
    inside.mkdir(parents=True)
    (inside / "bundle.txt").write_text("inside body", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "bundle.txt"
    sentinel.write_text("outside sentinel", encoding="utf-8")
    real_paths = quality._artifact_paths
    real_read = Path.read_text

    def swap_parent(*args, **kwargs):
        selected = real_paths(*args, **kwargs)
        inside.rename(root / "held")
        _symlink(inside, outside, directory=True)
        return selected

    def refuse_outside(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(outside)
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(quality, "_artifact_paths", swap_parent)
    monkeypatch.setattr(Path, "read_text", refuse_outside)

    result = QualityAnalyzer().analyze(_row(), root)

    assert result.reasons == ("identity_unconfined",)
    assert result.artifact_count == 0
    assert real_read(sentinel, encoding="utf-8") == "outside sentinel"


@pytest.mark.parametrize("exists", [False, True])
def test_quality_enumeration_keeps_inferred_audio_guard_anchored(
    tmp_path: Path, exists: bool,
):
    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "BVcost0.p0.m4a"
    if exists:
        target.write_bytes(b"outside audio sentinel")
    _symlink(root / "audio", outside, directory=True)
    roots = ArtifactRoots.of(root)

    assert QualityAnalyzer().analyze(_row(), root).reasons == ("artifact_missing",)
    assert resolve_audio_path(roots, "audio/BVcost0.p0.m4a", require_exists=True) is None
    assert resolve_audio_path(roots, "audio/BVcost0.p0.m4a", require_exists=False) is None
    if exists:
        assert target.read_bytes() == b"outside audio sentinel"
