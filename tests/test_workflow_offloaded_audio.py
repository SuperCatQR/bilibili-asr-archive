from __future__ import annotations

import hashlib
from contextlib import closing
from types import SimpleNamespace

import pytest

from bili_asr.artifact_root import ArtifactRoots
from bili_asr.platform_identity import ContentRef
from bili_asr.services.source_workflow import compose_source_handlers
from bili_asr.services.workflow_audio_access import retained_audio, verified_local_audio
from bili_asr.storage.archive_contracts import _resource, bootstrap_contract
from bili_asr.storage.artifact_catalog import ArtifactCatalog
from bili_asr.storage.database import connect_database
from bili_asr.storage.sources import SourceRepository, SourceVideoMetadata
from bili_asr.storage.workflow import AsrPolicy, AsrProfile, JobKind, WorkflowRepository
from bili_asr.workflow import WorkflowExecutor
from bili_asr.workflow_errors import JobExecutionError
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_workflow_control_plane import _seed_part


@pytest.fixture(params=["bilibili", "youtube"])
def retained_worker(tmp_path, request):
    with closing(connect_database(tmp_path / "archive.db")) as connection:
        bootstrap_contract(connection)
        connection.executescript(_resource("schema-artifact-storage.sql"))
        if request.param == "bilibili":
            part_id = _seed_part(connection)
        else:
            with connection:
                part_id = SourceRepository(connection).upsert_video(SourceVideoMetadata(ContentRef("youtube", "abcdefghijk"), "video", 1000))
        workflow = WorkflowRepository(connection)
        profile = workflow.register_profile(AsrProfile("offload-cpu", "offline", device="cuda"))
        workflow.plan(part_ids=[part_id], policy=AsrPolicy.ALL, profile_id=profile)
        audio_job = workflow.claim("test", kinds=(JobKind.AUDIO,))
        content = b"retained original audio bytes"
        identity = hashlib.sha256(content).hexdigest()
        key = "audio/retained.m4a"
        with connection:
            connection.execute("INSERT INTO audio_objects VALUES (1,?,?, 'm4a',1000,?,1)", (identity, len(content), key))
            connection.execute("INSERT INTO part_audio_objects VALUES (?,1,1,'workflow')", (part_id,))
            catalog = ArtifactCatalog(connection)
            catalog.register_object(identity, len(content))
            catalog.bind_audio(1, identity)
            catalog.register_target("local", kind="local")
            catalog.register_target("cold-disc")
            catalog.record_package("package", "cold-disc", "packages/audio.zip", sha256="a" * 64, byte_size=100, manifest_sha256="b" * 64)
            catalog.record_verified_replica(identity, "cold-disc", "packages/audio.zip", sha256=identity, byte_size=len(content), package_id="package", member_key=f"objects/{identity}")
        result = {"storage_key": key, "sha256": identity, "duration_ms": 1000}
        workflow.finish(audio_job.job_id, worker_id="test", result=result)
        def no_download(**kwargs):
            pytest.fail("bound offloaded audio must not download another generation")
        def no_model(*args, **kwargs):
            pytest.fail("unavailable retained input must be refused before model inference")
        handlers = ArchiveWorkflowHandlers(connection, workflow, archive_root=tmp_path, sessdata=None,
                                            audio_client_factory=no_download, timeout_transcriber=no_model)
        try:
            yield connection, workflow, handlers, part_id, audio_job, content, identity, key
        finally:
            handlers.close()


def test_offloaded_input_is_refused_before_asr_acquisition_without_rewriting_success(retained_worker):
    connection, workflow, handlers, _, audio_job, _, identity, _ = retained_worker
    original = [tuple(row) for row in connection.execute("SELECT rowid,* FROM workflow_attempts WHERE job_id=?", (audio_job.job_id,))]
    job = workflow.claim("test", kinds=(JobKind.ASR,))
    with pytest.raises(JobExecutionError, match="artifact_input_unavailable") as failure:
        handlers.local_asr(job)
    assert failure.value.safe_details == {"object_id": identity, "action": "artifacts-restore", "reason": "local-copy-unavailable"}
    assert connection.execute("SELECT COUNT(*) FROM acquisition_runs WHERE kind='asr'").fetchone()[0] == 0
    assert connection.execute("SELECT status FROM workflow_jobs WHERE job_id=?", (audio_job.job_id,)).fetchone()[0] == "succeeded"
    assert [tuple(row) for row in connection.execute("SELECT rowid,* FROM workflow_attempts WHERE job_id=?", (audio_job.job_id,))] == original


def test_new_audio_job_reuses_bound_identity_or_requires_explicit_restore(retained_worker):
    connection, workflow, handlers, _, audio_job, content, identity, key = retained_worker
    # A new acquisition recipe, e.g. an explicit retry, must retain the existing
    # binding rather than replacing the succeeded generation with a download.
    with connection:
        connection.execute("UPDATE workflow_jobs SET status='queued' WHERE job_id=?", (audio_job.job_id,))
    job = workflow.claim("test", kinds=(JobKind.AUDIO,))
    audio_handler = compose_source_handlers(handlers)[JobKind.AUDIO]
    with pytest.raises(JobExecutionError, match="artifact_input_unavailable"):
        audio_handler(job)
    path = handlers.archive_root / key
    path.parent.mkdir()
    path.write_bytes(content)
    returned = audio_handler(job)
    assert returned["sha256"] == returned["object_id"] == identity
    assert connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 1


def test_configured_corruption_does_not_shadow_correct_retained_fallback(retained_worker, tmp_path):
    connection, _, handlers, part_id, _, content, identity, key = retained_worker
    good = tmp_path / key
    good.parent.mkdir()
    good.write_bytes(content)
    configured = tmp_path.parent / f"{tmp_path.name}-configured"
    configured.mkdir()
    (configured / "audio").mkdir()
    (configured / key).write_bytes(b"incorrect bytes at preferred root")
    roots = ArtifactRoots.of(tmp_path, configured)
    retained = retained_audio(connection, part_id, {"storage_key": key, "sha256": identity})
    assert verified_local_audio(connection, roots, retained) == good
    good.write_bytes(b"overwritten generation")
    with pytest.raises(JobExecutionError, match="artifact_input_unavailable"):
        verified_local_audio(connection, roots, retained)
    assert handlers.artifact_roots.archive_root == tmp_path


def test_restored_same_sha_allows_new_profile_with_unchanged_previous_attempts(retained_worker):
    connection, workflow, handlers, part_id, audio_job, content, identity, key = retained_worker
    old_attempts = [tuple(row) for row in connection.execute("SELECT rowid,* FROM workflow_attempts WHERE job_id=?", (audio_job.job_id,))]
    path = handlers.archive_root / key
    path.parent.mkdir()
    path.write_bytes(content)
    inference = []
    def transcribe(config, audio_path, **kwargs):
        inference.append(audio_path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity
        return [{"start": 0, "end": 1, "text": "same retained input"}], {"language": "English"}, None
    handlers.timeout_transcriber = transcribe
    profile = workflow.register_profile(AsrProfile("new-profile", "offline-v2", device="cuda"))
    workflow.plan(part_ids=[part_id], policy=AsrPolicy.ALL, profile_id=profile)
    # Select the newly planned profile explicitly; the old queued consumer is
    # still a legitimate independent job and may also use the restored input.
    with connection:
        connection.execute("UPDATE workflow_jobs SET priority=10 WHERE kind='asr' AND profile_id=?", (profile,))
    job = workflow.claim("test", kinds=(JobKind.ASR,))
    assert job.profile_id == profile
    result = handlers.local_asr(job)
    workflow.finish(job.job_id, worker_id="test", result=result)
    assert inference == [str(path)]
    assert connection.execute("SELECT text FROM transcript_segments WHERE transcript_id=?", (result["transcript_id"],)).fetchone()[0] == "same retained input"
    assert [tuple(row) for row in connection.execute("SELECT rowid,* FROM workflow_attempts WHERE job_id=?", (audio_job.job_id,))] == old_attempts


def test_dependency_sha_mismatch_cannot_fall_back_to_mutable_filename(retained_worker):
    connection, _, handlers, part_id, _, content, _, key = retained_worker
    path = handlers.archive_root / key
    path.parent.mkdir()
    path.write_bytes(content)
    with pytest.raises(JobExecutionError, match="artifact_input_identity_mismatch"):
        retained_audio(connection, part_id, {"storage_key": key, "sha256": "f" * 64})


def test_worker_records_only_new_consumer_input_failure_and_retains_acquisition_success(retained_worker):
    connection, workflow, handlers, _, audio_job, _, _, _ = retained_worker
    previous = [tuple(row) for row in connection.execute("SELECT rowid,* FROM workflow_attempts WHERE job_id=?", (audio_job.job_id,))]
    executor = WorkflowExecutor(workflow, worker_id="consumer", handlers=handlers.handlers(), kinds=(JobKind.ASR,))
    result = executor.run(limit=1)
    assert result.failed == 1 and result.succeeded == result.cancelled == 0
    row = connection.execute("SELECT status,last_error_code FROM workflow_jobs WHERE kind='asr'").fetchone()
    assert tuple(row) == ("failed", "artifact_input_unavailable")
    assert connection.execute("SELECT status FROM workflow_jobs WHERE job_id=?", (audio_job.job_id,)).fetchone()[0] == "succeeded"
    assert [tuple(row) for row in connection.execute("SELECT rowid,* FROM workflow_attempts WHERE job_id=?", (audio_job.job_id,))] == previous
    assert connection.execute("SELECT COUNT(*) FROM acquisition_runs WHERE kind='asr'").fetchone()[0] == 0


@pytest.mark.parametrize("configured", [True, False])
def test_new_acquisition_registers_stable_object_and_exact_local_target(tmp_path, monkeypatch, configured):
    with closing(connect_database(tmp_path / "archive.db")) as connection:
        bootstrap_contract(connection)
        connection.executescript(_resource("schema-artifact-storage.sql"))
        _seed_part(connection)
        workflow = WorkflowRepository(connection)
        profile = workflow.register_profile(AsrProfile("new-acquisition", "offline", device="cpu"))
        workflow.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile)
        job = workflow.claim("store", kinds=(JobKind.AUDIO,))
        media = tmp_path.parent / f"{tmp_path.name}-media" if configured else tmp_path
        media.mkdir(exist_ok=True)
        roots = ArtifactRoots.of(tmp_path, media)
        path = media / "audio/new.m4a"
        path.parent.mkdir()
        path.write_bytes(b"new acquired bytes")
        monkeypatch.setattr("bili_asr.workflow_runtime.subprocess.run", lambda *args, **kwargs: SimpleNamespace(stdout='{"format":{"duration":1}}'))
        handlers = ArchiveWorkflowHandlers(connection, workflow, archive_root=tmp_path, artifact_roots=roots, sessdata=None)
        try:
            result = handlers.store_audio(job, SourceRepository(connection).part(1), path, path)
        finally:
            handlers.close()
        catalog = ArtifactCatalog(connection)
        assert result["object_id"] == result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert catalog.audio_object(1) == result["object_id"]
        replicas = catalog.replicas_for_object(result["object_id"])
        assert len(replicas) == 1 and replicas[0]["target_id"] == ("local-artifacts" if configured else "local")
        assert replicas[0]["relative_key"] == "audio/new.m4a"
