"""Retention is a resolved value: the flag, else BILI_KEEP_AUDIO, else retain (D15).

The policy is decided **once** at the command boundary by
``artifact_root.resolve_keep_audio`` and handed down as ``reclaim_audio``'s
``keep`` value; the library never reads the environment itself.  These cases
resolve the policy exactly as a command does — from the real environment — and
then assert what the value does.
"""

from __future__ import annotations

import os
from pathlib import Path

from bili_asr.artifact_root import KEEP_AUDIO_ENV_VAR, resolve_keep_audio
from bili_asr.audio_reclaim import reclaim_audio

import tests.support.asr_fakes as asr_fakes


def _entry() -> dict[str, str]:
    return {
        "work_id": "BV1test:p0",
        "bvid": "BV1test",
        "status": "archived",
        "audio_path": "audio/BV1test.m4a",
    }


def _audio_file(tmp_path) -> Path:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_file = audio_dir / "BV1test.m4a"
    audio_file.write_bytes(b"fake audio data")
    return audio_file


def test_keep_audio_env_prevents_reclaim(tmp_path, monkeypatch):
    """When BILI_KEEP_AUDIO=1, audio files are not deleted after archival."""
    monkeypatch.setenv(KEEP_AUDIO_ENV_VAR, "1")
    audio_file = _audio_file(tmp_path)

    keep = resolve_keep_audio(None, os.environ)
    removed = reclaim_audio(tmp_path, _entry(), keep=keep)

    assert keep is True
    assert removed is False
    assert audio_file.exists()


def test_unset_variable_defaults_to_retain(tmp_path, monkeypatch):
    """Without BILI_KEEP_AUDIO the resolved policy retains (the D5 flip)."""
    monkeypatch.delenv(KEEP_AUDIO_ENV_VAR, raising=False)
    audio_file = _audio_file(tmp_path)

    keep = resolve_keep_audio(None, os.environ)
    removed = reclaim_audio(tmp_path, _entry(), keep=keep)

    assert keep is True
    assert removed is False
    assert audio_file.exists()


def test_keep_audio_zero_still_deletes(tmp_path, monkeypatch):
    """BILI_KEEP_AUDIO=0 explicitly enables deletion."""
    monkeypatch.setenv(KEEP_AUDIO_ENV_VAR, "0")
    audio_file = _audio_file(tmp_path)

    keep = resolve_keep_audio(None, os.environ)
    removed = reclaim_audio(tmp_path, _entry(), keep=keep)

    assert keep is False
    assert removed is True
    assert not audio_file.exists()


def test_coordinator_respects_keep_audio_policy(tmp_path, monkeypatch):
    """RunCoordinator honours the passed-down value after a row is archived.

    This is the boundary D15 draws: the coordinator receives the resolved
    policy and calls ``reclaim_audio`` with it — nothing here reads the
    environment, and nothing calls ``reclaim_audio`` directly.
    """
    from bili_asr import asr as asr_module
    from bili_asr.coordinator import RunCoordinator
    from bili_asr.manifest import ManifestStore

    asr_fakes.install(monkeypatch)

    def run(keep: bool) -> Path:
        root = tmp_path / ("retained" if keep else "reclaimed")
        audio_dir = root / "audio"
        audio_dir.mkdir(parents=True)
        audio_file = audio_dir / "BV1test.p0.m4a"
        audio_file.write_bytes(b"fake audio data")
        store = ManifestStore(root=root)
        store.upsert(
            {
                "work_id": "BV1test:p0",
                "bvid": "BV1test",
                "page_index": 0,
                "cid": 1,
                "status": "audio_ok",
                "audio_path": "audio/BV1test.p0.m4a",
            }
        )
        coordinator = RunCoordinator(str(root), store, offline=True, keep_audio=keep)
        coordinator.run_batch([("BV1test:p0", store.load()["BV1test:p0"])])
        assert store.load()["BV1test:p0"]["status"] == "archived"
        return audio_file

    assert run(True).exists(), "keep_audio=True retains the audio"
    assert not run(False).exists(), "keep_audio=False reclaims the audio"
