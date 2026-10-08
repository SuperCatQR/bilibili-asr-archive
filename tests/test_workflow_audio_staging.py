"""Exercise the real confined downloader through the cancellation-aware worker."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_asr import audio
from bili_asr.storage import open_database
from bili_asr.storage.workflow import AsrPolicy, AsrProfile, JobCancelledError, JobKind, WorkflowRepository
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_workflow_control_plane import _seed_part


@pytest.fixture
def worker(tmp_path, monkeypatch):
    connection = open_database(tmp_path)
    _seed_part(connection)
    repository = WorkflowRepository(connection)
    profile = repository.register_profile(AsrProfile("staging", "offline", device="cpu"))
    repository.plan(part_ids=[1], profile_id=profile, policy=AsrPolicy.ALL)
    job = repository.claim("audio-test", kinds=(JobKind.AUDIO,))
    handlers = ArchiveWorkflowHandlers(connection, repository, archive_root=tmp_path, sessdata=None)
    monkeypatch.setattr("bili_asr.workflow_runtime.subprocess.run",
                        lambda *a, **kw: SimpleNamespace(stdout=json.dumps({"format": {"duration": "1.25"}})))
    try:
        yield connection, repository, job, handlers
    finally:
        handlers.close()
        connection.close()


class StreamClient:
    def __init__(self, suffix, *, after_download=lambda: None):
        self.suffix = suffix
        self.after_download = after_download
        self.downloads = 0

    def fetch_playurl_audio(self, bvid, *, cid):
        return [{"id": 30216, "baseUrl": f"https://offline.invalid/stream{self.suffix}",
                 "mimeType": "audio/flac" if self.suffix == ".flac" else "audio/mp4"}]

    def download_audio_stream(self, url, destination):
        self.downloads += 1
        Path(destination).write_bytes(b"offline-media-bytes")
        self.after_download()


@pytest.mark.parametrize("suffix", [".m4a", ".flac"])
@pytest.mark.parametrize("cancel", [False, True])
def test_real_downloader_stages_before_guard_and_preserves_media_suffix(worker, tmp_path, monkeypatch, suffix, cancel):
    connection, repository, job, handlers = worker

    def unavailable(*args):
        raise audio.FFmpegUnavailable("offline ffmpeg unavailable")

    monkeypatch.setattr(audio, "_run_ffmpeg", unavailable)
    client = StreamClient(suffix, after_download=lambda: repository.cancel(job_ids=[job.job_id]) if cancel else None)
    handlers._client = client
    if cancel:
        with pytest.raises(JobCancelledError):
            handlers.audio(job)
        assert not list((tmp_path / "audio").iterdir())
        assert connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 0
    else:
        result = handlers.audio(job)
        assert result["storage_key"] == f"audio/BVtest.p0{suffix}"
        assert (tmp_path / result["storage_key"]).read_bytes() == b"offline-media-bytes"
        stored = connection.execute("SELECT * FROM audio_objects").fetchone()
        assert stored["format"] == suffix[1:]
        assert stored["storage_key"] == result["storage_key"]
        assert stored["duration_ms"] == 1250
        assert not list((tmp_path / "audio").glob(".workflow-audio-*"))
    assert client.downloads == 1


@pytest.mark.parametrize("suffix", [".m4a", ".flac"])
def test_existing_audio_is_reused_without_network_or_replacement(worker, tmp_path, suffix):
    connection, _, job, handlers = worker
    target = tmp_path / "audio" / f"BVtest.p0{suffix}"
    target.parent.mkdir()
    target.write_bytes(b"existing-media")
    original_mtime = target.stat().st_mtime_ns
    client = StreamClient(suffix)
    handlers._client = client
    result = handlers.audio(job)
    assert result["storage_key"] == f"audio/BVtest.p0{suffix}"
    assert target.read_bytes() == b"existing-media"
    assert target.stat().st_mtime_ns == original_mtime
    assert client.downloads == 0
    assert connection.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0] == 1
