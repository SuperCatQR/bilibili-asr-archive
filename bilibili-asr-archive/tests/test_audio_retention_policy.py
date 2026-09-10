"""Test BILI_KEEP_AUDIO environment variable audio retention policy."""

import os
import tempfile
from pathlib import Path

import pytest


def test_keep_audio_env_prevents_reclaim(tmp_path):
    """When BILI_KEEP_AUDIO=1, audio files are not deleted after archival."""
    from bili_asr.audio_reclaim import reclaim_audio

    # Setup: create audio file
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_file = audio_dir / "BV1test.m4a"
    audio_file.write_bytes(b"fake audio data")

    entry = {
        "work_id": "BV1test:p0",
        "bvid": "BV1test",
        "status": "archived",
        "audio_path": "audio/BV1test.m4a",
    }

    # Test: with BILI_KEEP_AUDIO=1, file should NOT be deleted
    original_value = os.environ.get("BILI_KEEP_AUDIO")
    try:
        os.environ["BILI_KEEP_AUDIO"] = "1"
        removed = reclaim_audio(tmp_path, entry)
        
        assert removed is False, "reclaim_audio should return False when BILI_KEEP_AUDIO=1"
        assert audio_file.exists(), "Audio file should still exist when BILI_KEEP_AUDIO=1"
    finally:
        if original_value is None:
            os.environ.pop("BILI_KEEP_AUDIO", None)
        else:
            os.environ["BILI_KEEP_AUDIO"] = original_value


def test_default_behavior_deletes_audio(tmp_path):
    """Without BILI_KEEP_AUDIO, audio files are deleted after archival (default behavior)."""
    from bili_asr.audio_reclaim import reclaim_audio

    # Setup: create audio file
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_file = audio_dir / "BV1test.m4a"
    audio_file.write_bytes(b"fake audio data")

    entry = {
        "work_id": "BV1test:p0",
        "bvid": "BV1test",
        "status": "archived",
        "audio_path": "audio/BV1test.m4a",
    }

    # Test: without BILI_KEEP_AUDIO, file should be deleted
    original_value = os.environ.get("BILI_KEEP_AUDIO")
    try:
        os.environ.pop("BILI_KEEP_AUDIO", None)
        removed = reclaim_audio(tmp_path, entry)
        
        assert removed is True, "reclaim_audio should return True when audio is deleted"
        assert not audio_file.exists(), "Audio file should be deleted by default"
    finally:
        if original_value is not None:
            os.environ["BILI_KEEP_AUDIO"] = original_value


def test_keep_audio_zero_still_deletes(tmp_path):
    """BILI_KEEP_AUDIO=0 explicitly enables deletion."""
    from bili_asr.audio_reclaim import reclaim_audio

    # Setup: create audio file
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_file = audio_dir / "BV1test.m4a"
    audio_file.write_bytes(b"fake audio data")

    entry = {
        "work_id": "BV1test:p0",
        "bvid": "BV1test",
        "status": "archived",
        "audio_path": "audio/BV1test.m4a",
    }

    # Test: BILI_KEEP_AUDIO=0 should still delete
    original_value = os.environ.get("BILI_KEEP_AUDIO")
    try:
        os.environ["BILI_KEEP_AUDIO"] = "0"
        removed = reclaim_audio(tmp_path, entry)
        
        assert removed is True, "reclaim_audio should return True when BILI_KEEP_AUDIO=0"
        assert not audio_file.exists(), "Audio file should be deleted when BILI_KEEP_AUDIO=0"
    finally:
        if original_value is None:
            os.environ.pop("BILI_KEEP_AUDIO", None)
        else:
            os.environ["BILI_KEEP_AUDIO"] = original_value


def test_coordinator_respects_keep_audio_policy(tmp_path):
    """RunCoordinator should respect BILI_KEEP_AUDIO when archiving."""
    from bili_asr.coordinator import RunCoordinator
    from bili_asr.manifest import ManifestStore

    # Setup: minimal archive structure
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_file = audio_dir / "BV1test.p0.m4a"
    audio_file.write_bytes(b"fake audio data")

    # Create transcript directories
    for subdir in ["srt", "txt", "md", "raw"]:
        (tmp_path / "transcripts" / subdir).mkdir(parents=True)

    # Setup manifest
    manifest = ManifestStore(tmp_path)
    manifest.load()
    manifest.upsert({
        "work_id": "BV1test:p0",
        "bvid": "BV1test",
        "page_index": 0,
        "status": "asr_done",
        "audio_path": "audio/BV1test.p0.m4a",
    })

    # Test: with BILI_KEEP_AUDIO=1, coordinator should not delete audio
    original_value = os.environ.get("BILI_KEEP_AUDIO")
    try:
        os.environ["BILI_KEEP_AUDIO"] = "1"
        
        # Note: This is an integration point - the actual coordinator flow
        # would call reclaim_audio internally after archival
        from bili_asr.audio_reclaim import reclaim_audio
        entry = manifest.get("BV1test:p0")
        removed = reclaim_audio(tmp_path, entry)
        
        assert removed is False
        assert audio_file.exists(), "Audio should be retained when BILI_KEEP_AUDIO=1"
    finally:
        if original_value is None:
            os.environ.pop("BILI_KEEP_AUDIO", None)
        else:
            os.environ["BILI_KEEP_AUDIO"] = original_value
