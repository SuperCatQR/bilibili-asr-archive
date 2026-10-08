"""Offline regressions for issues #240 through #246, including real processes."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
from pathlib import Path
import sqlite3
import subprocess
import time

import pytest

from bili_asr import archive, cli
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.editorial import EditorialConfig
from bili_asr.editorial_runtime import EditorialWorkflowHandlers
from bili_asr.reading_publication import export_reading_site
from bili_asr.storage import AsrPolicy, JobKind, WorkflowRepository, open_database
from bili_asr.storage.database import SchemaContractError
from bili_asr.storage.editorial import EditorialRepository
from bili_asr.workflow import WorkflowExecutor
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_ai_editorial import FakeClient, insert_record, record
from tests.test_workflow_control_plane import _profile, _seed_part


@pytest.mark.parametrize("configured", [False, True])
def test_relative_archive_audio_records_a_relative_key(tmp_path, monkeypatch, configured):
    monkeypatch.chdir(tmp_path)
    root = Path("archive")
    connection = open_database(root)
    try:
        _seed_part(connection)
        repository = WorkflowRepository(connection)
        repository.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=_profile(repository))
        job = repository.claim("audio-worker", kinds=[JobKind.AUDIO])
        products = tmp_path / "products"
        products.mkdir()
        roots = ArtifactRoots.of(root, products if configured else None)
        handlers = ArchiveWorkflowHandlers(connection, repository, archive_root=root,
                                           sessdata=None, artifact_roots=roots)

        def download(client, identity, target, **kwargs):
            staging_roots = kwargs["artifact_roots"]
            assert staging_roots.write_base.is_relative_to(roots.write_base / "audio")
            assert staging_roots.write_base.name.startswith(".workflow-audio-")
            assert target.parent == staging_roots.write_base / "audio"
            assert not (roots.write_base / "audio" / target.name).exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"offline audio")
            return str(target.absolute())

        monkeypatch.setattr("bili_asr.audio.download_audio", download)
        monkeypatch.setattr("bili_asr.workflow_runtime.subprocess.run", lambda *a, **kw:
                            subprocess.CompletedProcess(a[0], 0, '{"format":{"duration":"1"}}', ""))
        try:
            result = handlers.audio(job)
        finally:
            handlers.close()
        # Derive the actual stable stem from the produced file instead of
        # coupling this regression to unrelated stem formatting.
        produced = next((roots.write_base / "audio").glob("*.m4a"))
        expected = produced.relative_to(roots.write_base).as_posix()
        assert result["storage_key"] == expected
        assert not Path(result["storage_key"]).is_absolute()
        assert connection.execute("SELECT storage_key FROM audio_objects").fetchone()[0] == expected
        assert result["sha256"] == hashlib.sha256(b"offline audio").hexdigest()
        if configured:
            assert not (tmp_path / "archive" / "audio").exists()
    finally:
        connection.close()


def test_symlink_root_reaches_the_publication_guard(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    connection = open_database(real)
    try:
        _seed_part(connection)
        insert_record(connection, record(source="subtitle-ai"))
        repository = WorkflowRepository(connection)
        repository.request_publication(video_part_id=1, transcript_id=1)
        job = repository.claim("publisher")
        original = archive._lexical_archive_root
        observed = []

        def guard(root):
            observed.append(root)
            assert root == link and root.is_symlink()
            return original(root)

        monkeypatch.setattr(archive, "_lexical_archive_root", guard)
        handlers = ArchiveWorkflowHandlers(connection, repository, archive_root=link, sessdata=None)
        try:
            with pytest.raises(OSError, match="unsafe"):
                handlers.publish(job)
        finally:
            handlers.close()
        assert observed == [link]
        assert not (real / "transcripts").exists()
    finally:
        connection.close()


def test_configured_publication_is_complete_in_read_projections(tmp_path):
    from bili_asr.coverage_report import CoverageReport
    from bili_asr.export import export_records
    from bili_asr.integrity import IntegrityVerifier
    from bili_asr.services.workflow_projection import workflow_records

    root, products = tmp_path / "archive", tmp_path / "products"
    products.mkdir()
    roots = ArtifactRoots.of(root, products)
    connection = open_database(root)
    try:
        _seed_part(connection)
        insert_record(connection, record(source="subtitle-ai"))
        repository = WorkflowRepository(connection)
        repository.request_publication(video_part_id=1, transcript_id=1)
        handlers = ArchiveWorkflowHandlers(connection, repository, archive_root=root,
                                           sessdata=None, artifact_roots=roots)
        try:
            result = WorkflowExecutor(repository, worker_id="publisher", handlers=handlers.handlers()).run()
        finally:
            handlers.close()
        assert result.succeeded == 1
        assert not (root / "transcripts").exists()
        assert workflow_records(root, artifact_roots=roots)["BVtest:p0"]["status"] == "archived"
        report = CoverageReport.build(root, artifact_roots=roots).data
        assert report["cumulative"]["complete"] == 1
        assert report["rows"][0]["artifact_present"] is True
        assert IntegrityVerifier().verify(root, scope="incomplete", artifact_roots=roots).checked == 0
        assert "archived" in export_records(root, "json", status_filter={"archived"}, artifact_roots=roots)
    finally:
        connection.close()


@pytest.mark.parametrize("via_env", [False, True])
def test_cli_editorial_run_writes_configured_root_and_export_verifies_hash(tmp_path, monkeypatch, via_env):
    root, products = tmp_path / "archive", tmp_path / "products"
    products.mkdir()
    connection = open_database(root)
    try:
        _seed_part(connection)
        insert_record(connection, record())
        repository = WorkflowRepository(connection)
        editorial = EditorialRepository(connection)
        prepared = editorial.prepare(1, None, EditorialConfig())
        proof_id, _, _, _ = repository.request_editorial(video_part_id=1, input_id=prepared["input_id"])
        handler = EditorialWorkflowHandlers(editorial, repository, archive_root=root, client=FakeClient())
        assert WorkflowExecutor(repository, worker_id="proofreader", handlers=handler.handlers(),
                                kinds=(JobKind.PROOFREAD,)).run().succeeded == 1
        revision = editorial.revision_for_job(proof_id)
        args = ["workflow", "run", "--archive-root", str(root), "--only-editorial"]
        if via_env:
            monkeypatch.setenv("BILI_ARTIFACT_ROOT", str(products))
        else:
            monkeypatch.delenv("BILI_ARTIFACT_ROOT", raising=False)
            args += ["--artifact-root", str(products)]
        assert cli.main(args) == 0
        assert not (root / "documents").exists()
        artifacts = list(connection.execute("SELECT * FROM document_artifacts"))
        assert {row["artifact_name"] for row in artifacts} == {"reading.md", "review.md"}
        for row in artifacts:
            relative = Path(row["relative_path"])
            assert not relative.is_absolute()
            assert hashlib.sha256((products / relative).read_bytes()).hexdigest() == row["content_sha256"]
        output = tmp_path / "content"
        export_args = ["reading-export", "--archive-root", str(root), "--out", str(output)]
        if not via_env:
            export_args += ["--artifact-root", str(products)]
        assert cli.main(export_args) == 0
        assert json.loads((output / "catalog.json").read_text())[0]["revisionId"] == revision
        reading = next(row for row in artifacts if row["artifact_name"] == "reading.md")
        (products / reading["relative_path"]).write_text("tampered", encoding="utf-8")
        with pytest.raises(ValueError, match="哈希"):
            export_reading_site(connection, artifact_roots=(products, root), output=output)
    finally:
        connection.close()


def test_failed_dependency_explanation_and_targeted_retry(tmp_path, capsys):
    connection = open_database(tmp_path)
    try:
        _seed_part(connection)
        repo = WorkflowRepository(connection)
        repo.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=_profile(repo))
        subtitle = repo.claim("w", kinds=[JobKind.SUBTITLE])
        audio = repo.claim("w", kinds=[JobKind.AUDIO])
        repo.fail(subtitle.job_id, worker_id="w", error_code="auth_failed")
        repo.fail(audio.job_id, worker_id="w", error_code="download_failed")
        asr = next(job for job in repo.list_jobs() if job.kind == JobKind.ASR)
        info = repo.explain_job(asr.job_id)
        assert info["blocked"] and not info["ready"]
        assert info["blockers"] == [{"job_id": audio.job_id, "kind": "audio", "status": "failed",
                                     "error_code": "download_failed"}]
        assert cli.main(["workflow", "explain", "--archive-root", str(tmp_path), "--job-id", asr.job_id]) == 0
        assert json.loads(capsys.readouterr().out)["blockers"] == info["blockers"]
        assert repo.requeue_failed(job_ids=[audio.job_id], kinds=[JobKind.SUBTITLE]) == 0
        assert cli.main(["workflow", "retry", "--archive-root", str(tmp_path), "--job-id", audio.job_id,
                         "--kind", "audio", "--part-id", "1"]) == 0
        assert repo.explain_job(subtitle.job_id)["status"] == "failed"
        assert repo.explain_job(asr.job_id)["blockers"][0]["status"] == "queued"
        retry = repo.claim("w", kinds=[JobKind.AUDIO])
        assert retry.attempt_count == 2
        assert repo.explain_job(asr.job_id)["blockers"][0]["status"] == "running"
        repo.finish(retry.job_id, worker_id="w", result={})
        assert repo.explain_job(asr.job_id)["ready"]
        assert repo.claim("w", kinds=[JobKind.ASR]).job_id == asr.job_id
        assert [row[0] for row in connection.execute(
            "SELECT outcome FROM workflow_attempts WHERE job_id = ? ORDER BY rowid", (audio.job_id,)
        )] == ["failed", "succeeded"]
        assert cli.main(["workflow", "status", "--archive-root", str(tmp_path), "--details"]) == 0
        assert '"blockers"' in capsys.readouterr().out
    finally:
        connection.close()


def test_incompatible_database_cli_fails_before_modifying_schema(tmp_path, capsys):
    path = tmp_path / "archive.db"
    with sqlite3.connect(path) as old:
        old.execute("CREATE TABLE transcripts(transcript_id INTEGER PRIMARY KEY)")
    before = path.read_bytes()
    with pytest.raises(SchemaContractError, match="discarded"):
        open_database(tmp_path)
    assert cli.main(["workflow", "status", "--archive-root", str(tmp_path)]) == 1
    assert "delete archive.db" in capsys.readouterr().err
    assert path.read_bytes() == before


def _claim_process(root, barrier, queue):
    connection = open_database(root)
    try:
        repo = WorkflowRepository(connection)
        barrier.wait(timeout=30)
        job = repo.claim(str(multiprocessing.current_process().pid))
        queue.put(None if job is None else job.job_id)
    finally:
        connection.close()


def test_four_processes_never_claim_the_same_job(tmp_path):
    connection = open_database(tmp_path)
    try:
        _seed_part(connection)
        repo = WorkflowRepository(connection)
        # Three independent jobs; the fourth worker must observe idle.
        repo.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=_profile(repo))
        repo.request_publication(video_part_id=1, transcript_id=1)
        ctx = multiprocessing.get_context("spawn")
        queue, barrier = ctx.Queue(), ctx.Barrier(4)
        workers = [ctx.Process(target=_claim_process, args=(str(tmp_path), barrier, queue)) for _ in range(4)]
        try:
            for worker in workers:
                worker.start()
            results = [queue.get(timeout=45) for _ in workers]
            for worker in workers:
                worker.join(timeout=10)
                assert worker.exitcode == 0
            claimed = [job for job in results if job is not None]
            assert len(claimed) == len(set(claimed)) == 3
            assert connection.execute("SELECT COUNT(*) FROM workflow_attempts").fetchone()[0] == 3
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=5)
            queue.close()
    finally:
        connection.close()


def _hold_write_lock(path, ready):
    connection = sqlite3.connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ready.set()
        time.sleep(0.4)
        connection.commit()
    finally:
        connection.close()


def test_heartbeat_inherits_timeout_and_survives_process_write_contention(tmp_path, monkeypatch):
    monkeypatch.setenv("BILI_SQLITE_BUSY_TIMEOUT_MS", "2000")
    connection = open_database(tmp_path)
    try:
        _seed_part(connection)
        repo = WorkflowRepository(connection)
        repo.request_publication(video_part_id=1, transcript_id=1)
        job = repo.claim("heartbeat", lease_seconds=10)
        monkeypatch.setenv("BILI_SQLITE_BUSY_TIMEOUT_MS", "1")
        heartbeat = repo.open_lease_repository()
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 2000
        assert heartbeat.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 2000
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        writer = ctx.Process(target=_hold_write_lock, args=(str(tmp_path / "archive.db"), ready))
        try:
            writer.start()
            assert ready.wait(timeout=30)
            heartbeat.renew_lease(job, lease_seconds=30)
            writer.join(timeout=10)
            assert writer.exitcode == 0
            expiration = connection.execute("SELECT lease_expires_at FROM workflow_jobs").fetchone()[0]
            assert expiration >= int(time.time()) + 25
            repo.finish(job.job_id, worker_id="heartbeat", result={"requested_transcript_id": 1})
        finally:
            heartbeat.connection.close()
            if writer.is_alive():
                writer.terminate()
                writer.join(timeout=5)
    finally:
        connection.close()


def test_cli_reports_bounded_contention_instead_of_traceback(tmp_path, monkeypatch, capsys):
    connection = open_database(tmp_path)
    _seed_part(connection)
    repo = WorkflowRepository(connection)
    profile = _profile(repo)
    repo.plan(part_ids=[1], policy=AsrPolicy.ALL, profile_id=profile)
    monkeypatch.setenv("BILI_SQLITE_BUSY_TIMEOUT_MS", "10")
    try:
        connection.execute("BEGIN IMMEDIATE")
        assert cli.main(["workflow", "run", "--archive-root", str(tmp_path), "--only-editorial"]) == 1
        assert "SQLite contention timeout exceeded" in capsys.readouterr().err
    finally:
        connection.rollback()
        connection.close()
