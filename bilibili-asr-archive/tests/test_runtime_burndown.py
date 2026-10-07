"""Direct regressions for runtime issue acceptance boundaries."""
import os

import pytest

from bili_asr import archive
from bili_asr.artifact_root import ArtifactRoots, usable_audio_path, usable_audio_for_path
from bili_asr.cli.pilot import _audio_base_holding, _audio_base_for_path
from bili_asr.manifest import ManifestStore


@pytest.mark.parametrize("key", archive._REQUIRED_ARTIFACT_KEYS)
@pytest.mark.parametrize("target_kind", ["symlink", "directory"])
def test_publication_refuses_nonregular_artifact_before_any_bundle_change(tmp_path, key, target_kind):
    row = {"bvid": "BVrefuse", "work_id": "BVrefuse:p0", "page_index": 0, "cid": 1}
    paths = archive.write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "old"}], source="asr")
    target = tmp_path / paths[key]
    marker = archive.bundle_marker_path(tmp_path / paths["srt_path"])
    marker_before = marker.read_bytes()
    others = {name: (tmp_path / value).read_bytes() for name, value in paths.items() if name != key}
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside untouched")
    if target_kind == "symlink":
        try:
            target.symlink_to(outside)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                pytest.skip("Windows process lacks symlink privilege")
            raise
    else:
        target.mkdir()
    with pytest.raises(OSError, match="target is not a regular file"):
        archive.write_archive(tmp_path, row, [{"start": 0, "end": 1, "text": "new"}], source="asr")
    assert outside.read_bytes() == b"outside untouched"
    assert marker.read_bytes() == marker_before
    assert all((tmp_path / paths[name]).read_bytes() == content for name, content in others.items())
    assert target.is_symlink() if target_kind == "symlink" else target.is_dir()


def test_empty_configured_stub_does_not_shadow_usable_legacy_audio(tmp_path):
    state, products = tmp_path / "state", tmp_path / "products"
    for base in (state, products):
        (base / "audio").mkdir(parents=True)
    (products / "audio/a.m4a").write_bytes(b"")
    legacy = state / "audio/a.m4a"
    legacy.write_bytes(b"real audio")
    roots = ArtifactRoots.of(state, products)
    assert usable_audio_path(roots, ("audio/a.m4a",)) == (state, "audio/a.m4a", legacy)
    assert _audio_base_holding(roots, "audio/a.m4a") == state
    assert usable_audio_for_path(roots, legacy) == (state, "audio/a.m4a", legacy)
    assert _audio_base_for_path(roots, legacy) == state
    assert usable_audio_for_path(roots, products / "audio/a.m4a") is None


@pytest.mark.parametrize("stage", ["subtitle_done", "writeback_error"])
def test_publication_recovery_requires_a_store_part_and_ignores_manifest_only(tmp_root, stage):
    from tests.support.archive_database import _seed_archive_database
    from bili_asr.cli.run import _store_pending_rows
    store = ManifestStore(root=tmp_root)
    def row(bvid):
        return {"bvid": bvid, "work_id": bvid + ":p0", "page_index": 0, "cid": 1,
                "status": "subtitle_done", "title": bvid, "duration_s": 1}
    store.upsert(row("BVknown"))
    store.upsert(row("BVgone"))
    _seed_archive_database(tmp_root)
    from bili_asr.storage import open_database
    connection = open_database(tmp_root)
    try:
        connection.execute("UPDATE video_parts SET processing_status = 'gone' WHERE bvid = ?", ("BVgone",))
        connection.commit()
    finally:
        connection.close()
    if stage == "writeback_error":
        for bvid in ("BVknown", "BVgone"):
            entry = row(bvid)
            entry.update(status="archived", transcript_writeback_error="injected retry")
            store.upsert(entry)
    store.upsert(row("BVmanifestonly"))
    rows, error = _store_pending_rows(tmp_root, "run")
    assert error is None
    assert [key for key, _ in rows] == ["BVknown:p0"]
    assert rows[0][1]["status"] == ("subtitle_done" if stage == "subtitle_done" else "archived")


@pytest.mark.parametrize("status", ["meta_ok", "subtitle_done"])
def test_malformed_manifest_page_does_not_abort_store_pending_selection(tmp_root, status):
    from tests.support.archive_database import _seed_archive_database
    from bili_asr.cli.run import _store_pending_rows
    store = ManifestStore(root=tmp_root)
    # Replay accepts this row shape; pending recovery must validate the page
    # before hashing it, including rows outside the recovery stage.
    store.upsert({"bvid": "BVknown", "work_id": "BVknown:p0",
                  "status": "subtitle_done", "page_index": 0, "cid": 1,
                  "title": "known", "duration_s": 1})
    _seed_archive_database(tmp_root)
    store.upsert({"bvid": "BVmalformed", "work_id": "BVmalformed:p0",
                  "status": status, "page_index": []})
    rows, error = _store_pending_rows(tmp_root, "run")
    assert error is None
    assert [key for key, _ in rows] == ["BVknown:p0"]
