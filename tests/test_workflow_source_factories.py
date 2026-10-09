"""Injected acquisition dependencies execute through real workflow handlers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_asr.asr.config import ASRConfig
from bili_asr.sources.models import SubtitleSegment, SubtitleTrack
from bili_asr.storage import open_database
from bili_asr.storage.workflow import AsrPolicy, AsrProfile, JobKind, WorkflowRepository
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_workflow_control_plane import _seed_part


@pytest.fixture
def database(tmp_path):
    connection = open_database(tmp_path)
    _seed_part(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_injected_gateway_creates_transcript_and_publication_job(database, tmp_path):
    calls = []

    class Gateway:
        async def get_subtitle_tracks(self, bvid, cid):
            calls.append(("tracks", bvid, cid))
            return (SubtitleTrack("zh-CN", "中文", False, "track-1"),)

        async def fetch_subtitle_segments(self, track, bvid, cid):
            calls.append(("body", track.track_id, bvid, cid))
            return (SubtitleSegment(0, 1000, "注入网关产生的字幕"),)

    def factory(*, sessdata):
        calls.append(("gateway", sessdata))
        return Gateway()

    repository = WorkflowRepository(database)
    profile_id = repository.register_profile(AsrProfile("gateway", "offline", device="cpu"))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile_id)
    job = repository.claim("factory-test", kinds=(JobKind.SUBTITLE,))
    handlers = ArchiveWorkflowHandlers(database, repository, archive_root=tmp_path,
                                       sessdata=None, gateway_factory=factory)
    try:
        result = handlers.subtitle(job)
    finally:
        handlers.close()
    assert result["outcome"] == "stored"
    assert result["publication_job_id"] is not None
    assert calls == [("gateway", None), ("tracks", "BVtest", 1), ("body", "track-1", "BVtest", 1)]
    assert database.execute("SELECT text FROM transcript_segments").fetchone()[0] == "注入网关产生的字幕"


def test_injected_audio_client_downloads_real_staged_bytes(database, tmp_path, monkeypatch):
    calls = []

    class Client:
        def fetch_playurl_audio(self, bvid, *, cid):
            calls.append(("streams", bvid, cid))
            return [{"id": 30216, "baseUrl": "https://offline.invalid/audio.m4a", "mimeType": "audio/mp4"}]

        def download_audio_stream(self, url, destination):
            calls.append(("download", url, Path(destination), Path(destination).resolve()))
            Path(destination).write_bytes(b"injected audio bytes")

    def factory(*, sessdata):
        calls.append(("client", sessdata))
        return Client()

    repository = WorkflowRepository(database)
    profile_id = repository.register_profile(AsrProfile("factory", "offline", device="cpu"))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile_id)
    job = repository.claim("factory-test", kinds=(JobKind.AUDIO,))
    monkeypatch.setattr("bili_asr.workflow_runtime.subprocess.run", lambda *args, **kwargs:
                        SimpleNamespace(stdout=json.dumps({"format": {"duration": "1.25"}})))
    handlers = ArchiveWorkflowHandlers(database, repository, archive_root=tmp_path,
                                       sessdata=None, audio_client_factory=factory)
    try:
        result = handlers.audio(job)
    finally:
        handlers.close()
    assert calls[:2] == [("client", None), ("streams", "BVtest", 1)]
    assert calls[2][0:2] == ("download", "https://offline.invalid/audio.m4a")
    assert ".workflow-audio-" in str(calls[2][3])
    assert (tmp_path / result["storage_key"]).read_bytes() == b"injected audio bytes"
    assert result["duration_ms"] == 1250
    assert database.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0] == 1


def test_injected_cpu_runner_executes_and_releases_once(database, tmp_path):
    calls = []

    class Runner:
        def set_hotword_evidence(self, **kwargs):
            calls.append(("evidence", kwargs))

        def transcribe(self, path):
            calls.append(("transcribe", path))
            return [{"start": 0, "end": 1, "text": "注入模型产生的转录"}]

        def rebuild_hotwords_from_first_pass(self, text):
            return []

        def provenance(self):
            return {"language": "Chinese"}

        def transcribed_coverage(self):
            return None

        def release(self):
            calls.append(("release",))

    def factory(config):
        assert isinstance(config, ASRConfig)
        calls.append(("runner", config.model_name, config.chunk_seconds))
        return Runner()

    repository = WorkflowRepository(database)
    profile_id = repository.register_profile(AsrProfile("factory", "offline", device="cpu", chunk_seconds=60))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile_id)
    audio_path = tmp_path / "audio" / "BVtest.p0.m4a"
    audio_path.parent.mkdir()
    audio_path.write_bytes(b"offline audio")
    job = repository.claim("factory-test", kinds=(JobKind.AUDIO,))
    repository.finish(job.job_id, worker_id="factory-test", result={"storage_key": "audio/BVtest.p0.m4a"})
    job = repository.claim("factory-test", kinds=(JobKind.ASR,))
    handlers = ArchiveWorkflowHandlers(database, repository, archive_root=tmp_path,
                                       sessdata=None, runner_factory=factory)
    try:
        result = handlers.local_asr(job)
        assert handlers._runner(profile_id) is handlers._runner(profile_id)
    finally:
        handlers.close()
    assert calls[0] == ("runner", "offline", 60)
    assert calls[1] == ("evidence", {"evidence_text": None, "paired_subtitle_text": None})
    assert calls[2] == ("transcribe", str(audio_path))
    assert calls[3] == ("release",)
    assert len(calls) == 4
    assert result["source_kind"] == "asr-local"
    assert result["publication_job_id"] is not None
    assert database.execute("SELECT text FROM transcript_segments").fetchone()[0] == "注入模型产生的转录"


def test_injected_timeout_transcriber_executes_gpu_profile_without_cpu_factory(database, tmp_path):
    calls = []

    def cpu_factory(config):
        pytest.fail("GPU workflow must use the bounded timeout transcriber")

    def transcribe(config, path, *, paired_subtitle_text, timeout_seconds, diagnostics_sink):
        calls.append((config.model_name, path, paired_subtitle_text, timeout_seconds))
        diagnostics_sink.update({"quality": {"status": "not-evaluable", "flags": []}})
        return [{"start": 0, "end": 1, "text": "受控子进程转录"}], {"language": "Chinese"}, None

    repository = WorkflowRepository(database)
    profile_id = repository.register_profile(AsrProfile("timeout", "offline", device="cuda", inference_timeout_seconds=72))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile_id)
    audio_path = tmp_path / "audio" / "BVtest.p0.m4a"
    audio_path.parent.mkdir()
    audio_path.write_bytes(b"offline audio")
    job = repository.claim("factory-test", kinds=(JobKind.AUDIO,))
    repository.finish(job.job_id, worker_id="factory-test", result={"storage_key": "audio/BVtest.p0.m4a"})
    job = repository.claim("factory-test", kinds=(JobKind.ASR,))
    handlers = ArchiveWorkflowHandlers(database, repository, archive_root=tmp_path,
                                       sessdata=None, runner_factory=cpu_factory, timeout_transcriber=transcribe)
    try:
        result = handlers.local_asr(job)
    finally:
        handlers.close()
    assert calls == [("offline", str(audio_path), None, 72)]
    assert result["source_kind"] == "asr-local"
    assert database.execute("SELECT text FROM transcript_segments").fetchone()[0] == "受控子进程转录"


@pytest.mark.parametrize("violation", ["outside", "suffix", "symlink", "stem"])
def test_audio_return_path_is_validated_before_probe_or_install(database, tmp_path, monkeypatch, violation):
    from bili_asr import audio

    outside = tmp_path / "outside.m4a"
    outside.write_bytes(b"outside sentinel")

    def download(client, identity, target, *, artifact_roots):
        if violation == "outside":
            return outside
        if violation == "suffix":
            final = target.with_suffix(".wav")
        elif violation == "stem":
            final = target.with_name("another-video.m4a")
        else:
            target.symlink_to(outside)
            return target
        final.write_bytes(b"unacceptable media")
        return final

    def unexpected_probe(*args, **kwargs):
        pytest.fail("unconfined source result reached ffprobe")

    repository = WorkflowRepository(database)
    profile_id = repository.register_profile(AsrProfile("path-guard", "offline", device="cpu"))
    repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile_id)
    job = repository.claim("factory-test", kinds=(JobKind.AUDIO,))
    monkeypatch.setattr(audio, "download_audio", download)
    monkeypatch.setattr("bili_asr.workflow_runtime.subprocess.run", unexpected_probe)
    handlers = ArchiveWorkflowHandlers(database, repository, archive_root=tmp_path,
                                       sessdata=None, audio_client_factory=lambda **kwargs: object())
    try:
        with pytest.raises((OSError, ValueError, RuntimeError), match="audio|staging"):
            handlers.audio(job)
    finally:
        handlers.close()
    assert outside.read_bytes() == b"outside sentinel"
    assert not (tmp_path / "audio" / "BVtest.p0.m4a").exists()
    assert database.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 0
