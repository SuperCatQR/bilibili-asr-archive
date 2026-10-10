"""Real planners and execution boundaries preserve costly historical results."""
from contextlib import closing
from dataclasses import replace
import json

import pytest

from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.editorial import EditorialConfig
from bili_asr.editorial_runtime import EditorialWorkflowHandlers
from bili_asr.services.archive_upgrade import apply_upgrade, plan_upgrade
from bili_asr.services.workflow_application import WorkflowApplication
from bili_asr.storage.database import connect_database
from bili_asr.storage.editorial import EditorialRepository
from bili_asr.storage.workflow import WorkflowRepository
from bili_asr.workflow import WorkflowExecutor
from bili_asr.workflow_models import AsrPolicy, JobKind
from tests.fixtures.frozen_migration_archive import frozen_archive


class NoPaidCalls:
    def complete(self, *args, **kwargs):
        pytest.fail("completed historical input must not call AI again")


def test_formal_upgrade_reuses_completed_ai_jobs_and_preserves_pending_work(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    expected = frozen_archive(source)
    plan = plan_upgrade(source, target, target_contracts=("universal-v2",), no_external_control_state=True)
    apply_upgrade(plan)
    with ArchiveSession(target, mode=ArchiveAccessMode.WRITE) as session:
        app = WorkflowApplication(session)
        before = [tuple(row) for row in session.connection.execute("SELECT * FROM workflow_jobs ORDER BY rowid")]
        frozen = [dict(row) for row in session.connection.execute("SELECT * FROM editorial_inputs ORDER BY rowid")]
        for row in frozen:
            config = EditorialConfig(**json.loads(row["prepared_json"])["snapshot"]["config"])
            for _ in range(2):
                planned = app.proofread(part_id=None, base_transcript_id=row["base_transcript_id"],
                    reference_transcript_id=row["reference_transcript_id"], no_reference=row["reference_transcript_id"] is None,
                    config=config)
                assert planned["input_id"] == row["input_id"]
        assert [tuple(row) for row in session.connection.execute("SELECT * FROM workflow_jobs ORDER BY rowid")] == before
        editorial = EditorialWorkflowHandlers(EditorialRepository(session.connection), app.repository,
                                               archive_root=target, client=NoPaidCalls())
        summary = WorkflowExecutor(app.repository, worker_id="upgrade-ai-check", handlers=editorial.handlers(),
            kinds=(JobKind.PROOFREAD, JobKind.RENDER_DOCUMENT)).run(limit=5)
        assert summary.idle and summary.succeeded == summary.failed == 0
        # Same producer profile retains jobs and cancellation dependencies.
        profile_bytes = [tuple(row) for row in session.connection.execute("SELECT * FROM workflow_asr_profile_configs")]
        producer = app.repository.plan(part_ids=(1, 3), policy=AsrPolicy.ALL, profile_id=1)
        assert producer.subtitle_jobs == producer.audio_jobs == producer.asr_jobs == 0
        assert [tuple(row) for row in session.connection.execute("SELECT * FROM workflow_asr_profile_configs")] == profile_bytes
        assert expected["ids"]["blocked_job"] in app.repository.blocked_by_cancelled()
        # The genuinely unfinished ASR job still advances through real claim/finish.
        called = []
        def unfinished(job):
            called.append(job.job_id)
            return {"transcript_id": expected["ids"]["asr_v2"]}
        def no_download(job):
            pytest.fail("completed source acquisition must not run again")
        summary = WorkflowExecutor(app.repository, worker_id="upgrade-pending-check",
            handlers={JobKind.ASR: unfinished, JobKind.AUDIO: no_download, JobKind.SUBTITLE: no_download},
            kinds=(JobKind.ASR, JobKind.AUDIO, JobKind.SUBTITLE)).run(limit=5)
        assert summary.succeeded == 1 and summary.failed == 0 and len(called) == 1
        assert app.repository.explain_job(expected["ids"]["cancelled_job"])["status"] == "cancelled"


def test_explicit_refresh_or_changed_configuration_creates_current_input(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    frozen_archive(source)
    apply_upgrade(plan_upgrade(source, target, target_contracts=("universal-v2",)))
    with ArchiveSession(target, mode=ArchiveAccessMode.WRITE) as session:
        row = session.connection.execute("SELECT * FROM editorial_inputs ORDER BY rowid LIMIT 1").fetchone()
        config = EditorialConfig(**json.loads(row["prepared_json"])["snapshot"]["config"])
        app = WorkflowApplication(session)
        options = dict(part_id=None, base_transcript_id=row["base_transcript_id"],
            reference_transcript_id=row["reference_transcript_id"], no_reference=row["reference_transcript_id"] is None)
        refreshed = app.proofread(**options, config=config, refresh_input=True)
        assert refreshed["input_id"] != row["input_id"]
        assert session.connection.execute("SELECT version FROM editorial_input_versions WHERE input_id=?",
                                          (refreshed["input_id"],)).fetchone()[0] == 2
        changed = app.proofread(**options, config=replace(config, max_chunk_chars=config.max_chunk_chars - 1))
        assert changed["input_id"] not in (row["input_id"], refreshed["input_id"])


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_replanning_does_not_revive_terminal_historical_editorial_job(tmp_path, status):
    source, target = tmp_path / "source", tmp_path / "target"
    frozen_archive(source)
    apply_upgrade(plan_upgrade(source, target, target_contracts=("universal-v2",)))
    with closing(connect_database(target / "archive.db")) as connection:
        with connection:
            connection.execute("UPDATE workflow_jobs SET status=? WHERE kind='proofread'", (status,))
    with ArchiveSession(target, mode=ArchiveAccessMode.WRITE) as session:
        row = session.connection.execute("SELECT * FROM editorial_inputs ORDER BY rowid LIMIT 1").fetchone()
        config = EditorialConfig(**json.loads(row["prepared_json"])["snapshot"]["config"])
        planned = WorkflowApplication(session).proofread(part_id=None, base_transcript_id=row["base_transcript_id"],
            reference_transcript_id=row["reference_transcript_id"], no_reference=row["reference_transcript_id"] is None, config=config)
        assert WorkflowRepository(session.connection).explain_job(planned["job_id"])["status"] == status


def test_upgrade_keeps_committed_chunks_and_only_explicit_retry_runs_missing_chunks(tmp_path):
    from tests.test_ai_editorial import FakeClient, record, insert_record
    from bili_asr.storage.transcripts import _segment_content_sha256

    source, target = tmp_path / "source", tmp_path / "target"
    frozen_archive(source)
    config = EditorialConfig(max_chunk_segments=1)
    with ArchiveSession(source, mode=ArchiveAccessMode.WRITE) as session:
        # Add a separate partial-work scenario to the materialized archive;
        # the checked-in historical package and all its existing rows stay fixed.
        additional = record(transcript_id=5)
        additional = replace(additional, version=3, content_sha256=_segment_content_sha256(
            [[s.start_ms, s.end_ms, s.text] for s in additional.segments]))
        insert_record(session.connection, additional)
        repository = EditorialRepository(session.connection)
        workflow = WorkflowRepository(session.connection)
        prepared = repository.prepare(5, None, config)
        assert len(prepared["chunks"]) > 1
        proof_id, _, _, _ = workflow.request_editorial(video_part_id=1, input_id=prepared["input_id"])
        handlers = EditorialWorkflowHandlers(repository, workflow, archive_root=source, client=FakeClient(fail_call=2))
        first = WorkflowExecutor(workflow, worker_id="before-upgrade", handlers=handlers.handlers(),
                                 kinds=(JobKind.PROOFREAD, JobKind.RENDER_DOCUMENT)).run()
        assert first.failed == 1
        saved = [tuple(row) for row in session.connection.execute(
            "SELECT * FROM editorial_chunk_results WHERE input_id=?", (prepared["input_id"],))]
        assert len(saved) == 1
        old_calls = [tuple(row) for row in session.connection.execute("SELECT * FROM editorial_model_calls ORDER BY rowid")]
    apply_upgrade(plan_upgrade(source, target, target_contracts=("universal-v2",)))
    with ArchiveSession(target, mode=ArchiveAccessMode.WRITE) as session:
        app = WorkflowApplication(session)
        assert app.proofread(part_id=None, base_transcript_id=5, reference_transcript_id=None,
                            no_reference=True, config=config)["job_id"] == proof_id
        assert app.repository.explain_job(proof_id)["status"] == "failed"
        repository = EditorialRepository(session.connection)
        client = FakeClient()
        handlers = EditorialWorkflowHandlers(repository, app.repository, archive_root=target, client=client)
        executor = WorkflowExecutor(app.repository, worker_id="after-upgrade", handlers=handlers.handlers(),
                                    kinds=(JobKind.PROOFREAD, JobKind.RENDER_DOCUMENT))
        assert executor.run().idle and not client.requests
        app.repository.requeue_failed(part_ids=[1])
        resumed = executor.run()
        assert resumed.succeeded == 2 and resumed.failed == 0
        assert len(client.requests) == len(prepared["chunks"]) - 1
        assert [tuple(row) for row in session.connection.execute(
            "SELECT * FROM editorial_model_calls ORDER BY rowid LIMIT ?", (len(old_calls),))] == old_calls
        assert [tuple(row) for row in session.connection.execute(
            "SELECT * FROM editorial_chunk_results WHERE input_id=? ORDER BY rowid LIMIT 1",
            (prepared["input_id"],))] == saved
