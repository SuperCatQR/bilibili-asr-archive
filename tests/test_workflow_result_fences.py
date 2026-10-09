"""A worker loses all authoritative results when its commit fence fails."""

from __future__ import annotations

import pytest

from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.sources.models import SubtitleSegment, SubtitleTrack
from bili_asr.storage import AcquisitionRunRecord, TranscriptRepository, TranscriptSegmentRecord
from bili_asr.storage.job_commit import JobCommitGuard
from bili_asr.storage.workflow import WorkflowRepository
from bili_asr.workflow_models import AsrPolicy, AsrProfile, JobCancelledError, JobKind, LeaseLostError
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_archive_sessions import _exclusive_available
from tests.test_workflow_control_plane import _seed_part


@pytest.fixture
def session(tmp_path):
    with ArchiveSession(tmp_path, mode=ArchiveAccessMode.BOOTSTRAP) as opened:
        _seed_part(opened.connection)
        yield opened


def _claim(session, kind=JobKind.SUBTITLE):
    repository = WorkflowRepository(session.connection)
    repository.plan_with_profile(part_ids=[1], policy=AsrPolicy.ALL,
        profile=AsrProfile("result-fence", "offline-model", device="cuda"))
    if kind is JobKind.ASR:
        audio = repository.claim("audio-worker", kinds=(JobKind.AUDIO,))
        repository.finish(audio.job_id, worker_id="audio-worker", result={"storage_key": "audio/offline.m4a"})
    job = repository.claim("result-worker", kinds=(kind,))
    expiry = session.connection.execute(
        "SELECT lease_expires_at FROM workflow_jobs WHERE job_id = ?", (job.job_id,)).fetchone()[0]
    now = [expiry - 1]
    repository.commit_guard = JobCommitGuard(session.connection, clock=lambda: now[0])
    return repository, job, now, expiry


def _start(repository, kind="subtitle"):
    repository.start_acquisition_run(AcquisitionRunRecord(
        run_id="result-run", kind=kind, selector_kind="bvid", selector_target="BVtest",
        requested_limit=1, credential_present=False, started_at=1))


def _assert_no_result(connection):
    for table in ("transcripts", "transcript_segments", "acquisition_attempts", "asr_models",
                  "transcript_asr_evidence", "transcript_coverage_attestations"):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert not connection.in_transaction


@pytest.mark.parametrize("guard", ["callback", "shared_transaction"])
@pytest.mark.parametrize("result", ["subtitle", "asr", "absence", "finish_run"])
def test_exact_expiry_inside_result_transaction_rolls_back_all_facts(session, guard, result):
    connection = session.connection
    workflow, job, now, expiry = _claim(session, JobKind.ASR if result == "asr" else JobKind.SUBTITLE)
    options = {"write_guard": lambda: workflow.assert_lease(job)} if guard == "callback" else {
        "write_transaction": lambda: workflow.owned_transaction(job)}
    repository = TranscriptRepository(connection, **options)
    _start(repository, "asr" if result == "asr" else "subtitle")
    prefix = "UPDATE acquisition_runs" if result == "finish_run" else "INSERT INTO acquisition_attempts"

    def expire_on_last_write(sql):
        if sql.lstrip().startswith(prefix):
            now[0] = expiry

    connection.set_trace_callback(expire_on_last_write)
    try:
        with pytest.raises(LeaseLostError):
            if result == "subtitle":
                repository.record_acquired_transcript(run_id="result-run", video_part_id=1,
                    source_kind="subtitle-ai", language="zh-CN",
                    segments=(TranscriptSegmentRecord(0, 900, "must not commit"),),
                    started_at=1, finished_at=2, created_at=2)
            elif result == "asr":
                repository.record_local_transcript(run_id="result-run", video_part_id=1,
                    language="zh-CN", segments=(TranscriptSegmentRecord(0, 900, "must not commit"),),
                    model_name="offline-model", model_revision="fixed", started_at=1, finished_at=2, created_at=2,
                    coverage={"decoded_s": 1.0, "produced_s": .9, "coverage": .9,
                              "coverage_min": .8, "coverage_short": False},
                    asr_evidence={"schema_version": 1, "diagnostics": {"source": "offline"}})
            elif result == "absence":
                repository.record_subtitle_attempt(run_id="result-run", video_part_id=1,
                    outcome="no-subtitle", error_code=None, started_at=1, finished_at=2,
                    credential_verified=True)
            else:
                repository.finish_acquisition_run("result-run", 2, outcome="complete")
    finally:
        connection.set_trace_callback(None)
    assert now[0] == expiry
    _assert_no_result(connection)
    assert connection.execute("SELECT outcome FROM acquisition_runs").fetchone()[0] == "running"
    # Failure cleanup remains possible after the fence rejects success.
    repository.finish_acquisition_run("result-run", 2, outcome="failed")
    assert connection.execute("SELECT outcome FROM acquisition_runs").fetchone()[0] == "failed"


@pytest.mark.parametrize("change", ["cancelled", "owner", "attempt"])
def test_result_owner_change_inside_transaction_rolls_back_transcript_and_attempt(session, change):
    connection = session.connection
    workflow, job, _, _ = _claim(session)
    repository = TranscriptRepository(connection, write_transaction=lambda: workflow.owned_transaction(job))
    _start(repository)
    # Inject a change after result writes: a writer lock normally prevents a
    # different SQLite connection from changing these fields concurrently.
    mutation = {"cancelled": "status = 'cancelled'", "owner": "lease_owner = 'other-owner'",
                "attempt": "attempt_count = attempt_count + 1"}[change]
    connection.execute(f"""CREATE TEMP TRIGGER change_result_owner AFTER INSERT ON acquisition_attempts
        BEGIN UPDATE workflow_jobs SET {mutation} WHERE kind = 'subtitle'; END""")
    error = JobCancelledError if change == "cancelled" else LeaseLostError
    with pytest.raises(error):
        repository.record_acquired_transcript(run_id="result-run", video_part_id=1,
            source_kind="subtitle-ai", language="zh-CN", segments=(TranscriptSegmentRecord(0, 900, "late"),),
            started_at=1, finished_at=2, created_at=2)
    _assert_no_result(connection)


@pytest.mark.parametrize("kind", [JobKind.SUBTITLE, JobKind.ASR])
def test_runtime_result_expiry_uses_shared_guard_and_failure_cleanup_releases_session(session, tmp_path, kind):
    connection = session.connection
    workflow, job, now, expiry = _claim(session, kind)

    class Gateway:
        async def get_subtitle_tracks(self, bvid, cid):
            return (SubtitleTrack("zh-CN", "caption", False, "offline"),)

        async def fetch_subtitle_segments(self, track, bvid, cid):
            return (SubtitleSegment(0, 900, "late subtitle"),)

    def transcribe(*args, **kwargs):
        kwargs["diagnostics_sink"].update({"source": "offline"})
        return [{"start": 0, "end": .9, "text": "late ASR"}], {"language": "Chinese"}, None

    if kind is JobKind.ASR:
        (tmp_path / "audio").mkdir()
        (tmp_path / "audio/offline.m4a").write_bytes(b"offline audio")
    handlers = ArchiveWorkflowHandlers(connection, workflow, archive_root=tmp_path, sessdata=None,
        gateway_factory=lambda **kwargs: Gateway(), timeout_transcriber=transcribe)

    def expire_on_insert(sql):
        if sql.lstrip().startswith("INSERT INTO acquisition_attempts"):
            now[0] = expiry

    connection.set_trace_callback(expire_on_insert)
    try:
        with pytest.raises(LeaseLostError):
            (handlers.subtitle if kind is JobKind.SUBTITLE else handlers.local_asr)(job)
    finally:
        connection.set_trace_callback(None)
        handlers.close()
    _assert_no_result(connection)
    run = connection.execute("SELECT outcome, finished_at FROM acquisition_runs").fetchone()
    assert run["outcome"] == "failed" and run["finished_at"] is not None
    assert connection.execute("SELECT COUNT(*) FROM workflow_jobs WHERE kind = 'publish'").fetchone()[0] == 0
    assert not _exclusive_available(tmp_path)
    session.close()
    assert _exclusive_available(tmp_path)


def test_callback_and_transaction_guards_cannot_be_combined(session):
    workflow, job, _, _ = _claim(session)
    with pytest.raises(ValueError, match="one ownership guard"):
        TranscriptRepository(session.connection, write_guard=lambda: workflow.assert_lease(job),
            write_transaction=lambda: workflow.owned_transaction(job))
