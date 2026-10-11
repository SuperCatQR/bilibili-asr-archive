"""Explicit metadata republishing preserves the old transcript and evidence."""
from pathlib import Path
import hashlib
import json
from types import SimpleNamespace

import pytest

from bili_asr import archive, cli
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.services.workflow_application import WorkflowApplication
from bili_asr.storage import open_database
from bili_asr.storage.workflow import JobKind, WorkflowRepository
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_workflow_control_plane import _seed_part
from tests.test_workflow_publication import _store_transcript


@pytest.fixture
def fixture(tmp_path):
    connection = open_database(tmp_path)
    _seed_part(connection)
    connection.executescript((Path(__file__).parents[1] / "src/bili_asr/storage/schema-artifact-storage.sql").read_text("utf-8"))
    session = SimpleNamespace(connection=connection, artifact_roots=ArtifactRoots.of(tmp_path), archive_root=tmp_path)
    yield session
    connection.close()


def run_publication(session):
    repository = WorkflowRepository(session.connection)
    job = repository.claim("refresh-worker", kinds=(JobKind.PUBLISH,))
    assert job is not None
    handlers = ArchiveWorkflowHandlers(session.connection, repository, archive_root=session.archive_root, sessdata=None)
    try:
        result = handlers.publish(job)
    finally:
        handlers.close()
    repository.finish(job.job_id, worker_id=job.lease_owner, result=result,
                      expected_attempt_count=job.attempt_count)
    return result


def publish_initial(session, source="subtitle-ai"):
    _store_transcript(session.connection, source=source)
    WorkflowApplication(session).publish([1])
    return run_publication(session)


def test_metadata_refresh_pins_old_caption_and_preserves_old_bytes(fixture):
    first = publish_initial(fixture)
    old = {key: (fixture.archive_root / first[key]).read_bytes()
           for key in ("srt_path", "vtt_path", "txt_path", "md_path", "raw_path")}
    with fixture.connection:
        fixture.connection.execute("INSERT INTO video_details VALUES ('BVtest',NULL,?,NULL,22)",
                                   ('中文\n链接 https://example.org/ref ":" \\末尾',))
    _store_transcript(fixture.connection, transcript_id=2, source="subtitle-cc")
    # Preview is genuinely read-only and binds the old caption despite a new preferred one.
    before = fixture.connection.total_changes
    preview = WorkflowApplication(fixture).publish([1], preserve_transcript=True, dry_run=True)
    assert preview[0]["transcript_id"] == 1
    assert fixture.connection.total_changes == before
    WorkflowApplication(fixture).publish([1], preserve_transcript=True)
    second = run_publication(fixture)
    assert second["transcript_id"] == 1
    assert archive.archive_bundle_complete(fixture.archive_root, {key: second[key] for key in old})
    for key in ("srt_path", "vtt_path", "txt_path", "raw_path"):
        assert (fixture.archive_root / second[key]).read_bytes() == old[key]
    md = (fixture.archive_root / second["md_path"]).read_text("utf-8")
    assert 'video_details_observed_at: 22' in md
    assert json.loads(next(line.split(": ", 1)[1] for line in md.splitlines() if line.startswith("video_description:"))) == '中文\n链接 https://example.org/ref ":" \\末尾'
    for value in old.values():
        assert (fixture.archive_root / "documents/artifact-objects" / hashlib.sha256(value).hexdigest()).read_bytes() == value
    sidecar = fixture.archive_root / Path(second["raw_path"]).parent / "source-metadata.json"
    assert json.loads(sidecar.read_bytes())["description"].startswith("中文")
    assert fixture.connection.execute("SELECT COUNT(*) FROM artifact_groups").fetchone()[0] == 2


@pytest.mark.parametrize("source", ["subtitle-ai", "subtitle-cc", "asr-local"])
def test_real_publish_carries_shared_video_description_for_every_part(fixture, source):
    with fixture.connection:
        fixture.connection.execute("INSERT INTO video_parts VALUES (2,'BVtest',1,2,'p1',1000,'metadata_collected',1,1)")
        fixture.connection.execute("INSERT INTO video_details VALUES ('BVtest',NULL,'Shared description',NULL,33)")
    _store_transcript(fixture.connection, source=source)
    _store_transcript(fixture.connection, source=source, transcript_id=2, part_id=2)
    WorkflowApplication(fixture).publish([1, 2])
    results = [run_publication(fixture), run_publication(fixture)]
    snapshots = [json.loads((fixture.archive_root / Path(result["raw_path"]).parent / "source-metadata.json").read_bytes())
                 for result in results]
    assert {item["description"] for item in snapshots} == {"Shared description"}
    assert {item["partIndex"] for item in snapshots} == {0, 1}
    assert {item["partTitle"] for item in snapshots} == {"p0", "p1"}
    for result in results:
        md = (fixture.archive_root / result["md_path"]).read_text("utf-8")
        assert 'video_description: "Shared description"' in md
        assert 'video_details_observed_at: 33' in md


def test_missing_description_is_null_in_real_bundle(fixture):
    result = publish_initial(fixture)
    snapshot = json.loads((fixture.archive_root / Path(result["raw_path"]).parent / "source-metadata.json").read_bytes())
    assert snapshot["description"] is None
    assert 'video_description: null' in (fixture.archive_root / result["md_path"]).read_text("utf-8")


@pytest.mark.parametrize("changed", ["publication", "transcript", "segments", "artifact"])
def test_stale_or_unverified_refresh_does_not_replace_old_bundle(fixture, changed):
    first = publish_initial(fixture)
    WorkflowApplication(fixture).publish([1], preserve_transcript=True)
    with fixture.connection:
        if changed == "publication":
            fixture.connection.execute("UPDATE workflow_publications SET published_at=published_at+1")
        elif changed == "transcript":
            fixture.connection.execute("UPDATE transcripts SET content_sha256=?", ("f" * 64,))
        elif changed == "segments":
            fixture.connection.execute("UPDATE transcript_segments SET text='changed'")
        else:
            (fixture.archive_root / first["txt_path"]).write_bytes(b"corrupt")
    before = (fixture.archive_root / first["md_path"]).read_bytes()
    with pytest.raises(ValueError, match="stale|complete_group_unverified"):
        run_publication(fixture)
    assert (fixture.archive_root / first["md_path"]).read_bytes() == before


def test_refresh_rejects_running_job_without_changing_request(fixture):
    publish_initial(fixture)
    application = WorkflowApplication(fixture)
    application.publish([1], preserve_transcript=True)
    repository = WorkflowRepository(fixture.connection)
    job = repository.claim("worker", kinds=(JobKind.PUBLISH,))
    assert job is not None
    with pytest.raises(ValueError, match="idle publication job"):
        application.publish([1], preserve_transcript=True)
    assert repository.explain_job(job.job_id)["status"] == "running"
    repository.finish(job.job_id, worker_id=job.lease_owner,
                      result={"requested_transcript_id": 1, "publication_request_id": job.payload["publication_request_id"]},
                      expected_attempt_count=job.attempt_count)
    assert repository.explain_job(job.job_id)["status"] == "succeeded"


def test_normal_publish_request_during_refresh_requeues_even_for_same_transcript(fixture):
    publish_initial(fixture)
    application = WorkflowApplication(fixture)
    application.publish([1], preserve_transcript=True)
    repository = WorkflowRepository(fixture.connection)
    job = repository.claim("worker", kinds=(JobKind.PUBLISH,))
    assert job is not None
    application.publish([1])
    repository.finish(job.job_id, worker_id=job.lease_owner,
                      result={"requested_transcript_id": 1, "publication_request_id": job.payload["publication_request_id"]},
                      expected_attempt_count=job.attempt_count)
    assert repository.explain_job(job.job_id)["status"] == "queued"


def test_asr_refresh_preserves_raw_character_timing_and_provenance(fixture):
    from bili_asr.artifacts import BUNDLE_MARKER_NAME
    first = publish_initial(fixture, source="asr-local")
    paths = {key: first[key] for key in ("srt_path", "vtt_path", "txt_path", "md_path", "raw_path")}
    raw_path = fixture.archive_root / paths["raw_path"]
    raw = json.loads(raw_path.read_bytes())
    text = raw["segments"][0]["text"]
    raw.update(schema="archive-raw-v2", provenance={"model": "original-model", "revision": "frozen"},
               coverage={"decoded_s": 1, "produced_s": 0.9, "coverage": 0.9},
               characters={"text": text, "starts": [0.01 * i for i in range(len(text))],
                           "ends": [0.01 * i + 0.005 for i in range(len(text))]})
    encoded = (json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    raw_path.write_bytes(encoded)
    marker_path = raw_path.parent / BUNDLE_MARKER_NAME
    marker = json.loads(marker_path.read_bytes())
    marker["artifacts"]["raw_path"]["sha256"] = hashlib.sha256(encoded).hexdigest()
    marker_path.write_text(json.dumps(marker), encoding="ascii")
    WorkflowApplication(fixture).publish([1], preserve_transcript=True)
    second = run_publication(fixture)
    assert (fixture.archive_root / second["raw_path"]).read_bytes() == encoded
    md = (fixture.archive_root / second["md_path"]).read_text("utf-8")
    assert 'asr_model: "original-model"' in md
    assert 'coverage_decoded_s: 1' in md


def test_refresh_requires_catalog_and_cli_preview_never_installs_it(tmp_path, capsys):
    connection = open_database(tmp_path)
    _seed_part(connection)
    _store_transcript(connection)
    try:
        assert cli.main(["workflow", "publish", "--archive-root", str(tmp_path),
                         "--part-id", "1", "--preserve-transcript", "--dry-run"]) == 1
        assert "artifact catalog upgrade" in capsys.readouterr().err
        assert connection.execute("SELECT COUNT(*) FROM workflow_jobs").fetchone()[0] == 0
    finally:
        connection.close()
