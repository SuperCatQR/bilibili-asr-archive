"""Production publication, projection and consumer identities stay consistent."""

from __future__ import annotations

import json

import pytest

from bili_asr.coverage_report import CoverageReport
from bili_asr.export import export_records
from bili_asr.integrity import IntegrityVerifier
from bili_asr.services import workflow_projection
from bili_asr import workflow_runtime
from bili_asr.storage import TranscriptRepository, WorkflowRepository, open_database
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.support.transcript_repository import _record, _run, _video_with_parts


def _caption(connection, part_id, source_kind, language, text):
    repository = TranscriptRepository(connection)
    index = int(connection.execute("SELECT COUNT(*) + 1 FROM acquisition_runs").fetchone()[0])
    run_id = _run(repository, index)
    result = _record(
        repository, part_id, run_id=run_id, source_kind=source_kind,
        language=language, body=((0, 1000, text),), created_at=400 + index,
    )
    repository.finish_acquisition_run(run_id, 300)
    return result


def _publish(connection, root, part_id, requested_id):
    repository = WorkflowRepository(connection)
    repository.request_publication(video_part_id=part_id, transcript_id=requested_id, force=True)
    job = repository.claim("identity-publisher")
    assert job is not None
    handlers = ArchiveWorkflowHandlers(connection, repository, archive_root=root, sessdata=None)
    try:
        result = handlers.publish(job)
    finally:
        handlers.close()
    repository.finish(
        job.job_id, worker_id="identity-publisher", result=result,
        expected_attempt_count=job.attempt_count,
    )
    return result


@pytest.mark.parametrize("captions,winner_index", [
    ((('subtitle-cc', 'en-US'), ('subtitle-cc', 'fr-FR')), 0),
    ((('subtitle-cc', 'en-US'), ('subtitle-cc', 'fr-FR'), ('subtitle-cc', 'fr-FR')), 0),
    ((('subtitle-cc', 'zh-CN'), ('subtitle-cc', 'zh-Hans'), ('subtitle-cc', 'zh-Hans')), 0),
    ((('subtitle-cc', 'zh-CN'), ('subtitle-cc', 'zh-CN')), 1),
    ((('subtitle-ai', 'ai-zh'), ('subtitle-cc', 'en-US')), 1),
])
def test_publication_preference_is_shared_by_projection_coverage_and_export(
    tmp_path, captions, winner_index,
):
    connection = open_database(tmp_path)
    try:
        part_id = _video_with_parts(connection, "BVpolicy", (1201,))[0]
        versions = [
            _caption(connection, part_id, kind, language, f"caption {index} {language}")
            for index, (kind, language) in enumerate(captions)
        ]
        expected = versions[winner_index]
        before = workflow_projection.workflow_records(tmp_path, with_text=True)["BVpolicy:p0"]
        assert before["preferred_transcript_id"] == before["transcript_id"] == expected.transcript_id
        assert before["published_transcript_id"] is None
        # Request the last acquisition rather than assuming that it won.
        published = _publish(connection, tmp_path, part_id, versions[-1].transcript_id)
        assert published["transcript_id"] == expected.transcript_id
    finally:
        connection.close()

    row = workflow_projection.workflow_records(tmp_path, with_text=True)["BVpolicy:p0"]
    expected_text = f"caption {winner_index} {captions[winner_index][1]}"
    assert row["status"] == "archived"
    assert row["transcript_id"] == row["preferred_transcript_id"] == row["published_transcript_id"] == expected.transcript_id
    assert row["publication_current"] is True
    assert row["language"] == row["published_language"] == captions[winner_index][1]
    assert row["version"] == expected.version
    assert row["transcript_text"] == expected_text
    assert (tmp_path / row["txt_path"]).read_text("utf-8").strip() == expected_text
    assert CoverageReport.build(tmp_path).data["cumulative"]["complete"] == 1
    exported = json.loads(export_records(tmp_path, "json", with_text=True))[0]
    assert exported["language"] == row["language"]
    assert exported["transcript_text"] == expected_text
    assert IntegrityVerifier().verify(tmp_path).defect_count == 0


@pytest.mark.parametrize("next_language", ["en-US", "zh-CN"])
def test_new_preference_preserves_the_published_identity_until_republication(tmp_path, next_language):
    connection = open_database(tmp_path)
    try:
        part_id = _video_with_parts(connection, "BVpendingversion", (1211,))[0]
        previous = _caption(connection, part_id, "subtitle-cc", "en-US", "published English")
        _publish(connection, tmp_path, part_id, previous.transcript_id)
        latest = _caption(connection, part_id, "subtitle-cc", next_language, "new preferred content")
        row = workflow_projection.workflow_records(tmp_path, with_text=True)["BVpendingversion:p0"]
        assert row["status"] == "archived"
        assert row["preferred_transcript_id"] == latest.transcript_id
        assert row["published_transcript_id"] == row["transcript_id"] == previous.transcript_id
        assert row["publication_current"] is False
        assert row["transcript_text"] == "published English"
        assert CoverageReport.build(tmp_path).data["cumulative"]["complete"] == 1
        assert json.loads(export_records(tmp_path, "json", with_text=True))[0]["transcript_text"] == "published English"
        result = _publish(connection, tmp_path, part_id, latest.transcript_id)
        assert result["transcript_id"] == latest.transcript_id
    finally:
        connection.close()
    row = workflow_projection.workflow_records(tmp_path, with_text=True)["BVpendingversion:p0"]
    assert row["published_transcript_id"] == row["preferred_transcript_id"] == latest.transcript_id
    assert row["transcript_text"] == "new preferred content"
    assert row["publication_current"] is True


@pytest.mark.parametrize("damage", ["missing-vtt", "empty-paths", "invalid-json"])
def test_corrupt_published_bundle_remains_a_defect_after_new_acquisition(tmp_path, damage):
    connection = open_database(tmp_path)
    try:
        part_id = _video_with_parts(connection, "BVdamaged", (1221,))[0]
        stored = _caption(connection, part_id, "subtitle-cc", "en-US", "published")
        result = _publish(connection, tmp_path, part_id, stored.transcript_id)
        _caption(connection, part_id, "subtitle-cc", "zh-CN", "unpublished")
        if damage == "missing-vtt":
            (tmp_path / result["vtt_path"]).unlink()
        else:
            with connection:
                connection.execute(
                    "UPDATE workflow_publications SET artifact_json = ?",
                    ('{}' if damage == 'empty-paths' else '{',),
                )
    finally:
        connection.close()

    declared = workflow_projection.workflow_records(tmp_path, verify_artifacts=False)["BVdamaged:p0"]
    assert declared["status"] == "archived"
    assert declared["published_transcript_id"] == stored.transcript_id
    assert workflow_projection.workflow_records(tmp_path)["BVdamaged:p0"]["status"] == "subtitle_done"
    coverage = CoverageReport.build(tmp_path).data
    assert coverage["cumulative"]["complete"] == 0
    assert {item["code"] for item in coverage["diagnostics"]} == {"terminal_missing_artifact"}
    integrity = IntegrityVerifier().verify(tmp_path)
    assert integrity.defect_count == 1
    assert integrity.backlog_count == 0


def test_projection_queries_are_batched_and_preserve_existing_row_order(tmp_path, monkeypatch):
    connection = open_database(tmp_path)
    try:
        older = _video_with_parts(connection, "BVolder", tuple(range(1231, 1242)), pubdate=100)
        newest = _video_with_parts(connection, "BVnewer", (1242,), pubdate=200)
        for part_id in (*older.values(), *newest.values()):
            _caption(connection, part_id, "subtitle-cc", "fr-FR", "French")
            _caption(connection, part_id, "subtitle-cc", "en-US", "English")
    finally:
        connection.close()

    statements = []
    connect = workflow_projection.open_archive_connection

    def traced_connect(*args, **kwargs):
        result = connect(*args, **kwargs)
        result.set_trace_callback(statements.append)
        return result

    monkeypatch.setattr(workflow_projection, "_PART_READ_BATCH_SIZE", 4)
    monkeypatch.setattr(workflow_projection, "open_archive_connection", traced_connect)
    records = workflow_projection.workflow_records(tmp_path, with_text=True, verify_artifacts=False)
    assert list(records) == ["BVnewer:p0", *(f"BVolder:p{i}" for i in range(11))]
    assert {row["language"] for row in records.values()} == {"en-US"}
    assert {row["transcript_text"] for row in records.values()} == {"English"}
    selects = [sql for sql in statements if sql.lstrip().upper().startswith(("SELECT", "WITH"))]
    # Three sets of 4 data queries, end detection and one contract-marker read.
    assert len(selects) == 14
    assert sum("FROM sqlite_master WHERE type='table' AND name='archive_contract'" in sql for sql in selects) == 1
    assert sum("FROM transcripts WHERE video_part_id IN" in sql for sql in selects) == 3
    assert sum("FROM transcript_segments" in sql for sql in selects) == 3


def test_same_second_republication_updates_the_actual_bundle_identity(tmp_path, monkeypatch):
    """Replay an older selected identity through the real producer upsert.

    Selection is injected to represent replay of an earlier selection/legacy
    publication. The writer, ownership transaction, upsert and every consumer
    remain production code; request_publication does not itself force a loser.
    """
    monkeypatch.setattr(workflow_runtime.time, "time", lambda: 1_800_000_000)
    choose = workflow_runtime.ordered_candidates
    replay_id = None

    def replay_selected_identity(rows):
        return choose(row for row in rows if int(row["transcript_id"]) == replay_id)

    monkeypatch.setattr(workflow_runtime, "ordered_candidates", replay_selected_identity)
    connection = open_database(tmp_path)
    try:
        part_id = _video_with_parts(connection, "BVrepublication", (1251,))[0]
        earlier = _caption(connection, part_id, "subtitle-cc", "en-US", "English publication")
        later = _caption(connection, part_id, "subtitle-cc", "zh-CN", "Chinese publication")
        replay_id = earlier.transcript_id
        _publish(connection, tmp_path, part_id, earlier.transcript_id)
        replay_id = later.transcript_id
        _publish(connection, tmp_path, part_id, later.transcript_id)
        replay_id = earlier.transcript_id
        result = _publish(connection, tmp_path, part_id, earlier.transcript_id)
        assert (tmp_path / result["txt_path"]).read_text("utf-8").strip() == "English publication"
    finally:
        connection.close()
    row = workflow_projection.workflow_records(tmp_path, with_text=True)["BVrepublication:p0"]
    assert row["published_transcript_id"] == row["transcript_id"] == earlier.transcript_id
    assert row["preferred_transcript_id"] == later.transcript_id
    assert row["publication_current"] is False
    assert row["transcript_text"] == "English publication"
    assert row["status"] == "archived"
    assert CoverageReport.build(tmp_path).data["cumulative"]["complete"] == 1
    assert json.loads(export_records(tmp_path, "json", with_text=True))[0]["transcript_text"] == "English publication"


@pytest.mark.parametrize("damage", ["missing", "wrong-part"])
def test_corrupt_published_transcript_relation_stays_visible_as_a_defect(tmp_path, damage):
    connection = open_database(tmp_path)
    try:
        part_id = _video_with_parts(connection, "BVdamagedrelation", (1261,))[0]
        original = _caption(connection, part_id, "subtitle-cc", "en-US", "published English")
        _publish(connection, tmp_path, part_id, original.transcript_id)
        preferred = _caption(connection, part_id, "subtitle-cc", "zh-CN", "unpublished Chinese")
        if damage == "missing":
            broken_id, code = 999_999, "published_transcript_missing"
        else:
            other_part = _video_with_parts(connection, "BVunrelated", (1262,))[0]
            unrelated = _caption(connection, other_part, "subtitle-cc", "fr-FR", "unrelated French")
            broken_id, code = unrelated.transcript_id, "published_transcript_part_mismatch"
        # Simulate external corruption while keeping a real intact bundle on
        # disk; byte-only validation cannot prove the stored identity relation.
        connection.execute("PRAGMA foreign_keys = OFF")
        with connection:
            connection.execute(
                "UPDATE workflow_publications SET transcript_id = ? WHERE video_part_id = ?",
                (broken_id, part_id),
            )
    finally:
        connection.close()

    declared = workflow_projection.workflow_records(
        tmp_path, with_text=True, verify_artifacts=False,
    )["BVdamagedrelation:p0"]
    assert declared["status"] == "archived"
    assert declared["transcript_id"] == declared["published_transcript_id"] == broken_id
    assert declared["preferred_transcript_id"] == preferred.transcript_id
    assert declared["publication_current"] is False
    assert declared["publication_error"] == code
    assert declared["transcript_text"] == ""
    if damage == "missing":
        assert declared["published_source"] is None
        assert declared["published_language"] is None
        assert declared["published_version"] is None
    verified = workflow_projection.workflow_records(tmp_path, with_text=True)["BVdamagedrelation:p0"]
    assert verified["publication_error"] == code
    assert verified["status"] != "archived"
    assert verified["transcript_text"] == ""
    coverage = CoverageReport.build(tmp_path).data
    assert {item["code"] for item in coverage["diagnostics"]} == {code}
    assert coverage["cumulative"]["complete"] == 0
    affected = next(row for row in coverage["rows"] if row["work_id"] == "BVdamagedrelation:p0")
    assert affected["artifact_present"] is True
    assert affected["category"] == "defect"
    integrity = IntegrityVerifier().verify(tmp_path, scope="BVdamagedrelation:p0")
    assert integrity.defect_count == 1
    assert integrity.backlog_count == 0
    assert integrity.defects[0].code == code
    exported = next(row for row in json.loads(export_records(tmp_path, "json", with_text=True))
                    if row["work_id"] == "BVdamagedrelation:p0")
    assert exported["publication_error"] == code
    assert exported["transcript_text"] == ""
