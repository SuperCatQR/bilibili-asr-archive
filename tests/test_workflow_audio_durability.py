"""Final installation is durable before any authoritative audio registration."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

import pytest

from bili_asr import file_ops
from bili_asr.storage import AsrPolicy, AsrProfile, JobKind, open_database
from bili_asr.storage.workflow import WorkflowRepository
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_workflow_control_plane import _seed_part


@pytest.fixture
def installation(tmp_path, monkeypatch):
    connection = open_database(tmp_path)
    _seed_part(connection)
    workflow = WorkflowRepository(connection)
    workflow.plan_with_profile(part_ids=[1], policy=AsrPolicy.ALL,
                               profile=AsrProfile("durable", "offline", device="cpu"))
    job = workflow.claim("audio", kinds=(JobKind.AUDIO,))
    target = tmp_path / "audio/BVtest.p0.m4a"
    source = target.parent / ".workflow-audio-install/audio/input.m4a"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"downloaded audio bytes")
    monkeypatch.setattr("bili_asr.workflow_runtime.subprocess.run", lambda *args, **kwargs:
                        type("Probe", (), {"stdout": json.dumps({"format": {"duration": 1}})})())
    handlers = ArchiveWorkflowHandlers(connection, workflow, archive_root=tmp_path, sessdata=None)
    try:
        yield connection, workflow, job, handlers, source, target
    finally:
        handlers.close()
        connection.close()


@pytest.mark.parametrize("same_path", [False, True])
def test_fsync_then_final_replace_then_directory_sync_then_registration(installation, monkeypatch, same_path):
    connection, _workflow, job, handlers, source, target = installation
    if same_path:
        os.replace(source, target)
        source = target
    events = []
    original_sync, original_replace = file_ops.os.fsync, file_ops.os.replace
    def file_sync(fd):
        events.append(("file-sync", connection.in_transaction))
        return original_sync(fd)
    def replace(source, destination):
        events.append(("replace", connection.in_transaction))
        return original_replace(source, destination)
    def directory_sync(path):
        events.append(("directory-sync", path))
    monkeypatch.setattr(file_ops.os, "fsync", file_sync)
    monkeypatch.setattr(file_ops.os, "replace", replace)
    monkeypatch.setattr(file_ops, "fsync_directory", directory_sync)
    connection.set_trace_callback(lambda sql: events.append(("register", True))
                                  if sql.lstrip().startswith("INSERT INTO audio_objects") else None)
    handlers.store_audio(job, handlers._part(job), source, target)
    expected = [("file-sync", False)]
    if not same_path:
        expected.append(("replace", True))
    expected.append(("directory-sync", target.parent))
    if source.parent != target.parent:
        expected.append(("directory-sync", source.parent))
    expected.append(("register", True))
    assert events == expected
    assert connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 1


@pytest.mark.parametrize("failure", ["file-sync", "replace", "target-sync", "source-sync", "commit"])
def test_failed_install_never_registers_success_and_new_attempt_reuses_recoverable_bytes(installation, monkeypatch, failure):
    connection, workflow, job, handlers, source, target = installation
    content = source.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected durability failure")
    with monkeypatch.context() as fault:
        if failure == "file-sync":
            fault.setattr(file_ops.os, "fsync", fail)
        elif failure == "replace":
            fault.setattr(file_ops.os, "replace", fail)
        elif failure in {"target-sync", "source-sync"}:
            original_sync = file_ops.fsync_directory
            def sync(path):
                if path == (target.parent if failure == "target-sync" else source.parent):
                    fail()
                original_sync(path)
            fault.setattr(file_ops, "fsync_directory", sync)
        else:
            original_transaction = workflow.owned_transaction
            @contextmanager
            def failed_commit(job):
                with original_transaction(job):
                    yield
                    raise sqlite3.OperationalError("injected commit failure")
            fault.setattr(workflow, "owned_transaction", failed_commit)
        with pytest.raises((OSError, sqlite3.OperationalError), match="injected"):
            handlers.store_audio(job, handlers._part(job), source, target)
    assert connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0] == 0
    remaining = source if failure in {"file-sync", "replace"} else target
    assert remaining.read_bytes() == content
    workflow.fail(job.job_id, worker_id="audio", error_code="audio_install_failed")
    old_attempt = tuple(connection.execute("SELECT * FROM workflow_attempts WHERE job_id=?", (job.job_id,)).fetchone())
    workflow.requeue_failed(job_ids=[job.job_id])
    retry = workflow.claim("recover", kinds=(JobKind.AUDIO,))
    result = handlers.store_audio(retry, handlers._part(retry), remaining, target)
    workflow.finish(retry.job_id, worker_id="recover", result=result)
    attempts = connection.execute("SELECT * FROM workflow_attempts WHERE job_id=? ORDER BY started_at,rowid", (job.job_id,)).fetchall()
    assert tuple(attempts[0]) == old_attempt
    assert attempts[-1]["outcome"] == "succeeded"
    assert target.read_bytes() == content


def test_installed_but_unregistered_audio_is_reusable_after_reopening_archive(installation, monkeypatch, tmp_path):
    connection, workflow, job, handlers, source, target = installation
    original_sync = file_ops.fsync_directory
    monkeypatch.setattr(file_ops, "fsync_directory", lambda path: (_ for _ in ()).throw(OSError("sync failed")))
    with pytest.raises(OSError, match="sync failed"):
        handlers.store_audio(job, handlers._part(job), source, target)
    workflow.fail(job.job_id, worker_id="audio", error_code="audio_install_failed")
    handlers.close()
    connection.close()
    monkeypatch.setattr(file_ops, "fsync_directory", original_sync)
    reopened = open_database(tmp_path)
    retry_workflow = WorkflowRepository(reopened)
    retry_workflow.requeue_failed(job_ids=[job.job_id])
    retry = retry_workflow.claim("restarted", kinds=(JobKind.AUDIO,))
    retry_handlers = ArchiveWorkflowHandlers(reopened, retry_workflow, archive_root=tmp_path, sessdata=None,
        audio_client_factory=lambda **kwargs: pytest.fail("existing installed audio must not download again"))
    try:
        result = retry_handlers.audio(retry)
        retry_workflow.finish(retry.job_id, worker_id="restarted", result=result)
        assert reopened.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 1
        assert target.read_bytes() == b"downloaded audio bytes"
    finally:
        retry_handlers.close()
        reopened.close()
