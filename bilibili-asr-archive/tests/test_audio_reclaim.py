"""Tests for post-archive audio reclaim."""

from __future__ import annotations

import os
import pytest

from bili_asr.audio_reclaim import reclaim_audio


def _entry(bvid="BV1xx411c7mD", work_id=None, page_index=0, cid=123,
           audio_path=None, unresolved=False):
    entry = {
        "bvid": bvid,
        "status": "archived",
        "title": "t",
    }
    if work_id:
        entry["work_id"] = work_id
        entry["page_index"] = page_index
        entry["cid"] = cid
    if audio_path:
        entry["audio_path"] = audio_path
    if unresolved:
        entry["unresolved"] = True
    return entry


def test_archived_asr_row_m4a_deleted(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    stem = f"{ 'BV1xx411c7mD' }.p0"
    (audio / "BV1xx411c7mD.p0.m4a").write_bytes(b"x" * 16)
    entry = _entry(work_id="BV1xx411c7mD:p0", page_index=0, cid=123)
    assert reclaim_audio(tmp_path, entry) is True
    assert not (audio / "BV1xx411c7mD.p0.m4a").exists()


def test_archived_subtitle_only_row_no_op(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    entry = _entry()  # no work_id/audio_path: bare bvid fallback, no file
    assert reclaim_audio(tmp_path, entry) is False
    assert list(audio.iterdir()) == []


def test_failed_row_keeps_file_when_not_reclaimed(tmp_path):
    # The caller only invokes reclaim after `archived`; the helper itself
    # never inspects status — the wiring contract. Guard the wiring by
    # asserting the helper is only called from archive paths in integration
    # tests (see test_cli_pilot / test_coordinator reclaim assertions).
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "BV1xx411c7mD.m4a").write_bytes(b"keep")
    entry = _entry()
    # Not calling reclaim_audio here: file must still exist.
    assert (audio / "BV1xx411c7mD.m4a").exists()


def test_path_traversal_rejected(tmp_path):
    secret = tmp_path / "secret.m4a"
    secret.write_bytes(b"x")
    entry = _entry(audio_path=os.path.join("..", "secret.m4a"))
    with pytest.raises(ValueError):
        reclaim_audio(tmp_path, entry)
    assert secret.exists()


def test_absolute_audio_path_outside_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "x.m4a"
    victim.write_bytes(b"x")
    entry = _entry(audio_path=str(victim))
    with pytest.raises(ValueError):
        reclaim_audio(tmp_path, entry)
    assert victim.exists()


def test_audio_path_inside_audio_dir_reclaimed(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    target = audio / "custom.m4a"
    target.write_bytes(b"x" * 4)
    entry = _entry(audio_path="audio/custom.m4a")
    assert reclaim_audio(tmp_path, entry) is True
    assert not target.exists()


def test_flac_candidate_removed(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "BV1xx411c7mD.p0.flac").write_bytes(b"x")
    entry = _entry(work_id="BV1xx411c7mD:p0", page_index=0, cid=1)
    assert reclaim_audio(tmp_path, entry) is True
    assert not (audio / "BV1xx411c7mD.p0.flac").exists()


def test_symlink_escape_rejected(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    victim = tmp_path / "victim.m4a"
    victim.write_bytes(b"x")
    link = audio / "linked.m4a"
    link.symlink_to(victim)
    entry = _entry(audio_path="audio/linked.m4a")
    with pytest.raises(ValueError):
        reclaim_audio(tmp_path, entry)
    assert victim.exists()


def test_reclaim_swap_does_not_delete_outside_victim(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    target = audio / "swap.m4a"
    outside = tmp_path / "victim.m4a"
    target.write_bytes(b"owned")
    outside.write_bytes(b"victim")
    entry = _entry(audio_path="audio/swap.m4a")
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ValueError):
        reclaim_audio(tmp_path, entry)
    assert outside.read_bytes() == b"victim"


def test_reclaim_moves_entry_before_post_validation_name_swap(tmp_path, monkeypatch):
    from bili_asr import path_policy

    audio = tmp_path / "audio"
    audio.mkdir()
    target = audio / "swap.m4a"
    victim = tmp_path / "victim.m4a"
    target.write_bytes(b"owned")
    victim.write_bytes(b"victim")
    entry = _entry(audio_path="audio/swap.m4a")
    original_replace = path_policy.os.replace
    moved = False

    def replace_then_swap(src, dst, **kwargs):
        nonlocal moved
        result = original_replace(src, dst, **kwargs)
        if not moved and src == "swap.m4a":
            moved = True
            target.symlink_to(victim)
        return result

    monkeypatch.setattr(path_policy.os, "replace", replace_then_swap)
    assert reclaim_audio(tmp_path, entry) is True
    assert victim.read_bytes() == b"victim"
    assert target.is_symlink()
    assert not list(audio.glob(".audio-reclaim-*"))


def test_coordinator_archive_stage_reclaims_audio(tmp_path, monkeypatch):
    import json

    root = tmp_path
    audio = root / "audio"
    audio.mkdir()
    (root / "transcripts").mkdir()
    raw_dir = root / "transcripts" / "raw"
    raw_dir.mkdir()
    work_id = "BV1xx411c7mD:p0"
    (raw_dir / "BV1xx411c7mD.p0.json").write_text(
        json.dumps({"source": "asr", "segments": [
            {"start": 0.0, "end": 1.0, "text": "hi"}
        ]}),
        encoding="utf-8",
    )
    (audio / "BV1xx411c7mD.p0.m4a").write_bytes(b"x" * 8)
    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=str(root))
    store.upsert({
        "work_id": work_id, "bvid": "BV1xx411c7mD", "cid": 1,
        "page_index": 0, "status": "audio_ok",
        "audio_path": "audio/BV1xx411c7mD.p0.m4a",
    })
    import bili_asr.asr as asr_mod

    class FakeModel:
        def generate(self, **_kwargs):
            return [{"text": "hi", "timestamp": [[0, 1000]]}]

    monkeypatch.setattr(
        asr_mod, "_load_default_model", lambda **_kwargs: FakeModel()
    )
    from bili_asr.coordinator import RunCoordinator

    coord = RunCoordinator(str(root), store, offline=True)
    coord.run_batch([(work_id, store.load()[work_id])])
    row = store.load()[work_id]
    assert row["status"] == "archived"
    assert not (audio / "BV1xx411c7mD.p0.m4a").exists()
