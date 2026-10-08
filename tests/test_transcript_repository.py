"""Offline repository contract tests for transcript and acquisition writes."""

from __future__ import annotations

import builtins
from dataclasses import replace
import hashlib
import io
import json
import os
import re
import sqlite3

import pytest

from bili_asr.storage import (
    MAX_TIMELINE_MS,
    AcquisitionRunRecord,
    MetadataRepository,
    SchemaContractError,
    TranscriptRecord,
    TranscriptRepository,
    TranscriptSegmentRecord,
    TranscriptWriteResult,
    open_database,
)
from bili_asr.storage.database import _PUBDATE_CHUNK
from tests.fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)
from tests.support.metadata_e2e import LEGACY_SIDECAR_PATHS
from tests.support.storage_schema import _write_pre_iteration_database
from tests.support.transcript_repository import BODY, CHANGED_BODY, _caption_run, _record, _run, _segments, _video_with_parts, _write_kwargs


#: The statement-parameter ceiling ``read_video_pubdates``' chunking exists for:
#: SQLite builds before 3.32.0 allow 999 host parameters per statement, and the
#: read keeps headroom under it.  Pinned on the test's own connection, because
#: this host's driver raises its ceiling to 250,000.
_STATEMENT_PARAMETER_CAP = 900


def _captioned_part(connection: sqlite3.Connection, bvid: str = "BV1CAPTION") -> int:
    """Store one video part through the metadata repository and return its id."""
    metadata = MetadataRepository(connection)
    with metadata.transaction():
        metadata.upsert_user(make_user_record())
        # ``aid`` stays NULL: the schema keeps aids unique and these fixtures
        # only need the part the transcript contract hangs from.
        metadata.upsert_video(
            make_video_record(bvid, aid=None, title="字幕测试视频")
        )
        metadata.upsert_part(
            make_part_record(
                bvid, cid=2001, title="第一集", processing_status="metadata_collected"
            )
        )
    row = connection.execute(
        "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = 0",
        (bvid,),
    ).fetchone()
    return int(row["video_part_id"])








def _probe(
    repository: TranscriptRepository,
    video_part_id: int,
    *,
    index: int,
    finished_at: int,
    error_code: str | None = None,
    credential_present: bool = False,
) -> str:
    """Record one ``no-subtitle`` probe of a part in its own acquisition run."""
    run_id = _run(
        repository,
        index,
        credential_present=credential_present,
        started_at=finished_at - 10,
    )
    repository.record_subtitle_attempt(
        run_id=run_id,
        video_part_id=video_part_id,
        outcome="no-subtitle",
        error_code=error_code,
        started_at=finished_at - 10,
        finished_at=finished_at,
    )
    return run_id








def _expected_content_sha256(body) -> str:
    """Compute the contract's content hash independently of the repository."""
    canonical = json.dumps(
        [[start_ms, end_ms, text] for start_ms, end_ms, text in body],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _triples(segments) -> list[tuple[int, int, str]]:
    """Return a stored record's segments as plain ``(start_ms, end_ms, text)``."""
    return [(segment.start_ms, segment.end_ms, segment.text) for segment in segments]


def _transcript_rows(connection: sqlite3.Connection, video_part_id: int) -> list[tuple]:
    """Return the stored versions of one part, oldest first."""
    return [
        tuple(row)
        for row in connection.execute(
            """
            SELECT version, source_kind, language, model_id, content_sha256, created_at
            FROM transcripts WHERE video_part_id = ? ORDER BY version
            """,
            (video_part_id,),
        ).fetchall()
    ]


def _segment_rows(connection: sqlite3.Connection, transcript_id: int) -> list[tuple]:
    """Return the stored segments of one version, in ordinal order."""
    return [
        tuple(row)
        for row in connection.execute(
            """
            SELECT ordinal, start_ms, end_ms, text FROM transcript_segments
            WHERE transcript_id = ? ORDER BY ordinal
            """,
            (transcript_id,),
        ).fetchall()
    ]


def _attempt_rows(
    connection: sqlite3.Connection, run_id: str | None = None
) -> list[tuple]:
    """Return the attempt evidence rows, optionally restricted to one run."""
    query = (
        "SELECT run_id, video_part_id, outcome, error_code, transcript_id, "
        "started_at, finished_at FROM acquisition_attempts"
    )
    if run_id is None:
        return [
            tuple(row)
            for row in connection.execute(
                query + " ORDER BY run_id, video_part_id"
            ).fetchall()
        ]
    return [
        tuple(row)
        for row in connection.execute(
            query + " WHERE run_id = ? ORDER BY video_part_id", (run_id,)
        ).fetchall()
    ]


def _empty_store(connection: sqlite3.Connection) -> tuple[int, int, int]:
    """Return the transcript, segment, and attempt counts of the store."""
    return (
        connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM acquisition_attempts").fetchone()[0],
    )


def test_first_write_stores_version_one_with_ordinal_segments_and_its_attempt(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)

        result = _record(repository, part_id)

        assert result.outcome == "stored"
        assert result.version == 1
        assert result.transcript_id >= 1
        assert result.content_sha256 == _expected_content_sha256(BODY)
        assert _transcript_rows(connection, part_id) == [
            (1, "subtitle-cc", "zh-CN", None, result.content_sha256, 400)
        ]
        assert _segment_rows(connection, result.transcript_id) == [
            (0, 0, 1_200, "第一句"),
            (1, 1_200, 2_400, "第二句"),
        ]
        assert _attempt_rows(connection) == [
            (run_id, part_id, "stored", None, result.transcript_id, 200, 300)
        ]
        # Subtitle process records live beside the metadata-scoped run tables,
        # never inside them.
        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_repeat_with_identical_content_writes_nothing_and_reports_unchanged(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        first_run = _run(repository, 1)
        first = _record(repository, part_id, run_id=first_run)

        second_run = _run(repository, 2)
        second = _record(
            repository, part_id, run_id=second_run, started_at=210, finished_at=310
        )

        assert second.outcome == "unchanged"
        assert second.transcript_id == first.transcript_id
        assert second.version == 1
        assert second.content_sha256 == first.content_sha256
        assert len(_transcript_rows(connection, part_id)) == 1
        assert _segment_rows(connection, first.transcript_id) == [
            (0, 0, 1_200, "第一句"),
            (1, 1_200, 2_400, "第二句"),
        ]
        # The acquisition itself is still recorded, and it points at the
        # version the operator already holds.
        assert _attempt_rows(connection) == [
            (first_run, part_id, "stored", None, first.transcript_id, 200, 300),
            (second_run, part_id, "unchanged", None, first.transcript_id, 210, 310),
        ]
    finally:
        connection.close()


def test_text_is_stored_and_hashed_trimmed_but_kept_verbatim_inside(tmp_root):
    """M1: trimming happens at the storage boundary, not only in the gateway."""
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        padded_body = ((0, 1_200, "  第一句\t"), (1_200, 2_400, "\n第二句  "))
        run_id = _run(repository, 1)

        padded = _record(repository, part_id, run_id=run_id, body=padded_body)

        assert padded.outcome == "stored"
        assert _segment_rows(connection, padded.transcript_id) == [
            (0, 0, 1_200, "第一句"),
            (1, 1_200, 2_400, "第二句"),
        ]
        # The hash covers the trimmed text, so the caller's whitespace cannot
        # invent a second version of a caption the archive already holds.
        assert padded.content_sha256 == _expected_content_sha256(BODY)

        trimmed_run = _run(repository, 2)
        trimmed = _record(
            repository, part_id, run_id=trimmed_run, body=BODY
        )
        assert trimmed.outcome == "unchanged"
        assert trimmed.version == 1
        assert trimmed.transcript_id == padded.transcript_id
    finally:
        connection.close()


def test_content_hash_is_the_sha256_of_the_canonical_segment_json(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)

        result = _record(repository, part_id, run_id=run_id)

        assert result.content_sha256 == _expected_content_sha256(BODY)
        assert re.fullmatch(r"[0-9a-f]{64}", result.content_sha256) is not None
        assert (
            connection.execute(
                "SELECT content_sha256 FROM transcripts WHERE transcript_id = ?",
                (result.transcript_id,),
            ).fetchone()[0]
            == result.content_sha256
        )
        # The canonical form is part of the contract: looser JSON spellings of
        # the same caption are a different digest, so the hash is not a
        # coincidental match of a nearby encoding.
        triples = [[0, 1_200, "第一句"], [1_200, 2_400, "第二句"]]
        looser_encodings = {
            hashlib.sha256(
                json.dumps(triples, ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
            hashlib.sha256(
                json.dumps(triples, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            hashlib.sha256(
                json.dumps(
                    triples, ensure_ascii=False, separators=(", ", ": ")
                ).encode("utf-8")
            ).hexdigest(),
        }
        assert result.content_sha256 not in looser_encodings

        # The identity key is not hashed: the same caption on another part
        # carries the same content hash.
        other_part_id = _captioned_part(connection, "BV1SAMEBODY")
        other_run = _run(repository, 2)
        other = _record(repository, other_part_id, run_id=other_run)
        assert other.content_sha256 == result.content_sha256
        assert other.version == 1
    finally:
        connection.close()


def test_changed_content_appends_version_two_and_leaves_version_one_untouched(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        first_run = _run(repository, 1)
        first = _record(repository, part_id, run_id=first_run)
        version_one_rows = _transcript_rows(connection, part_id)
        version_one_segments = _segment_rows(connection, first.transcript_id)

        second_run = _run(repository, 2)
        second = _record(
            repository,
            part_id,
            run_id=second_run,
            body=CHANGED_BODY,
            started_at=210,
            finished_at=310,
            created_at=410,
        )

        assert second.outcome == "stored"
        assert second.version == 2
        assert second.transcript_id != first.transcript_id
        assert second.content_sha256 == _expected_content_sha256(CHANGED_BODY)
        # Version 1 is byte-identical: nothing was rewritten or deleted.
        assert _transcript_rows(connection, part_id)[:1] == version_one_rows
        assert _segment_rows(connection, first.transcript_id) == version_one_segments
        assert _segment_rows(connection, second.transcript_id) == [
            (0, 0, 1_200, "第一句"),
            (1, 1_200, 2_400, "改写后的第二句"),
        ]
        assert _transcript_rows(connection, part_id)[1] == (
            2,
            "subtitle-cc",
            "zh-CN",
            None,
            second.content_sha256,
            410,
        )
        assert _attempt_rows(connection, second_run) == [
            (second_run, part_id, "stored", None, second.transcript_id, 210, 310)
        ]
    finally:
        connection.close()


def test_content_that_reverts_to_an_earlier_version_is_unchanged_and_points_at_it(
    tmp_root,
):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        first_run = _run(repository, 1)
        first = _record(repository, part_id, run_id=first_run)
        second_run = _run(repository, 2)
        second = _record(repository, part_id, run_id=second_run, body=CHANGED_BODY)

        revert_run = _run(repository, 3)
        reverted = _record(
            repository, part_id, run_id=revert_run, started_at=220, finished_at=320
        )

        assert reverted.outcome == "unchanged"
        assert reverted.version == 1
        assert reverted.transcript_id == first.transcript_id
        assert len(_transcript_rows(connection, part_id)) == 2
        assert _segment_rows(connection, second.transcript_id) == [
            (0, 0, 1_200, "第一句"),
            (1, 1_200, 2_400, "改写后的第二句"),
        ]
        # Reverting to the newest content is equally a no-op.
        newest_run = _run(repository, 4)
        newest = _record(
            repository,
            part_id,
            run_id=newest_run,
            body=CHANGED_BODY,
            started_at=230,
            finished_at=330,
        )
        assert newest.outcome == "unchanged"
        assert newest.version == 2
        assert newest.transcript_id == second.transcript_id
        assert _attempt_rows(connection, revert_run) == [
            (revert_run, part_id, "unchanged", None, first.transcript_id, 220, 320)
        ]
    finally:
        connection.close()


def test_content_identity_is_scoped_to_the_identity_key(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        cc_run = _run(repository, 1)
        cc = _record(repository, part_id, run_id=cc_run, language=" zh-CN ")

        # The stored language is the trimmed one, and it is the identity.
        assert _transcript_rows(connection, part_id) == [
            (1, "subtitle-cc", "zh-CN", None, cc.content_sha256, 400)
        ]

        # The same content under another source kind and language is a
        # different transcript identity with its own version history.
        ai_run = _run(repository, 2)
        ai = _record(
            repository,
            part_id,
            run_id=ai_run,
            source_kind="subtitle-ai",
            language="ai-zh",
        )
        assert ai.outcome == "stored"
        assert ai.version == 1
        assert ai.content_sha256 == cc.content_sha256

        # A padded language names the same identity as the trimmed stored one.
        repeat_run = _run(repository, 3)
        repeat = _record(repository, part_id, run_id=repeat_run, language="zh-CN")
        assert repeat.outcome == "unchanged"
        assert repeat.version == 1
        assert repeat.transcript_id == cc.transcript_id

        # A changed body advances only its own identity.
        changed_run = _run(repository, 4)
        changed = _record(
            repository,
            part_id,
            run_id=changed_run,
            language="zh-CN",
            body=CHANGED_BODY,
        )
        assert changed.version == 2
        assert changed.transcript_id != cc.transcript_id
        assert len(_transcript_rows(connection, part_id)) == 3
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"segments": ()}, ValueError),
        ({"segments": (TranscriptSegmentRecord(0, 1_200, "ok"), "not-a-record")}, TypeError),
        ({"video_part_id": 0}, ValueError),
        ({"video_part_id": True}, TypeError),
        ({"source_kind": "asr-local"}, ValueError),
        ({"source_kind": "unknown"}, ValueError),
        ({"language": "   "}, ValueError),
        ({"language": None}, TypeError),
        ({"run_id": "   "}, ValueError),
        ({"started_at": 301, "finished_at": 300}, ValueError),
        ({"created_at": -1}, ValueError),
    ],
)
def test_invalid_write_arguments_are_rejected_without_writing(
    tmp_root, override, error
):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        _run(repository, 1)
        kwargs = _write_kwargs(part_id)
        kwargs.update(override)

        with pytest.raises(error):
            repository.record_acquired_transcript(**kwargs)

        assert _empty_store(connection) == (0, 0, 0)
    finally:
        connection.close()


def test_unknown_part_and_unknown_run_fail_the_whole_write(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        _run(repository, 1)

        with pytest.raises(sqlite3.IntegrityError, match="unknown video_part_id"):
            _record(repository, 9_999)
        assert _empty_store(connection) == (0, 0, 0)

        with pytest.raises(sqlite3.IntegrityError, match="unknown run_id"):
            _record(repository, part_id, run_id="caption-run-missing")
        assert _empty_store(connection) == (0, 0, 0)

        # The run parent committed on its own survives both failures.
        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM acquisition_runs "
                "WHERE run_id = 'caption-run-1'"
            ).fetchone()
        ) == ("running", None)
    finally:
        connection.close()


def test_attempt_conflict_rolls_back_the_version_it_would_have_stored(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)
        stored = _record(repository, part_id, run_id=run_id)

        # One outcome per attempted part per run: the attempt row is written
        # last, so its rejection must take the new version down with it.
        with pytest.raises(sqlite3.IntegrityError):
            _record(
                repository,
                part_id,
                run_id=run_id,
                body=CHANGED_BODY,
                started_at=210,
                finished_at=310,
            )

        assert _transcript_rows(connection, part_id) == [
            (1, "subtitle-cc", "zh-CN", None, stored.content_sha256, 400)
        ]
        assert _segment_rows(connection, stored.transcript_id) == [
            (0, 0, 1_200, "第一句"),
            (1, 1_200, 2_400, "第二句"),
        ]
        assert _attempt_rows(connection, run_id) == [
            (run_id, part_id, "stored", None, stored.transcript_id, 200, 300)
        ]

        # The rolled-back call leaves no poisoned state behind: the same
        # content lands as version 2 under the next run.
        next_run = _run(repository, 2)
        appended = _record(
            repository, part_id, run_id=next_run, body=CHANGED_BODY
        )
        assert appended.outcome == "stored"
        assert appended.version == 2
    finally:
        connection.close()


def test_schema_foreign_keys_reject_orphans_and_restrict_deletes(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)
        stored = _record(repository, part_id, run_id=run_id)

        # An attempt cannot reference a transcript that does not exist.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO acquisition_attempts(
                    run_id, video_part_id, outcome, error_code, transcript_id,
                    started_at, finished_at
                ) VALUES (?, ?, 'stored', NULL, 9999, 200, 300)
                """,
                (run_id, part_id),
            )

        # A stored version is held by its segments and its attempt evidence.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM transcripts WHERE transcript_id = ?",
                (stored.transcript_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM video_parts WHERE video_part_id = ?", (part_id,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM acquisition_runs WHERE run_id = ?", (run_id,)
            )

        assert _transcript_rows(connection, part_id) == [
            (1, "subtitle-cc", "zh-CN", None, stored.content_sha256, 400)
        ]
        assert _segment_rows(connection, stored.transcript_id) == [
            (0, 0, 1_200, "第一句"),
            (1, 1_200, 2_400, "第二句"),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("attempt_outcomes", "expected"),
    [
        ((), "complete"),
        (("stored",), "complete"),
        (("no-subtitle",), "complete"),
        (("stored", "no-subtitle"), "complete"),
        (("stored", "failed"), "partial"),
        (("no-subtitle", "failed"), "partial"),
        (("failed", "failed"), "failed"),
    ],
)
def test_finish_derives_the_run_outcome_from_its_attempts(
    tmp_root, attempt_outcomes, expected
):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        run_id = _run(repository, 1)
        for index, attempt_outcome in enumerate(attempt_outcomes):
            part_id = _captioned_part(connection, f"BV1ATTEMPT{index}")
            if attempt_outcome == "stored":
                _record(
                    repository,
                    part_id,
                    run_id=run_id,
                    started_at=200 + index,
                    finished_at=300 + index,
                    created_at=400 + index,
                )
            else:
                repository.record_subtitle_attempt(
                    run_id=run_id,
                    video_part_id=part_id,
                    outcome=attempt_outcome,
                    error_code="timeout" if attempt_outcome == "failed" else None,
                    started_at=200 + index,
                    finished_at=300 + index,
                )

        assert repository.finish_acquisition_run(run_id, 500) == expected
        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        ) == (expected, 500)
    finally:
        connection.close()


def test_finish_honours_an_explicit_outcome_and_never_regresses_a_terminal_one(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)
        repository.record_subtitle_attempt(
            run_id=run_id,
            video_part_id=part_id,
            outcome="failed",
            error_code="timeout",
            started_at=200,
            finished_at=300,
        )

        # The explicit outcome is the operator's call; the derivation is only
        # the default.
        assert repository.finish_acquisition_run(run_id, 500, outcome="complete") == (
            "complete"
        )
        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        ) == ("complete", 500)

        with pytest.raises(sqlite3.IntegrityError, match="already finished"):
            repository.finish_acquisition_run(run_id, 600, outcome="failed")
        with pytest.raises(sqlite3.IntegrityError, match="already finished"):
            repository.finish_acquisition_run(run_id, 600)
        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        ) == ("complete", 500)
    finally:
        connection.close()


def test_run_outcome_derivation_reads_only_its_own_attempts(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        failing_part = _captioned_part(connection, "BV1FAILING")
        empty_run = _run(repository, 1)
        failing_run = _run(repository, 2)
        repository.record_subtitle_attempt(
            run_id=failing_run,
            video_part_id=failing_part,
            outcome="failed",
            error_code="timeout",
            started_at=200,
            finished_at=300,
        )

        assert repository.finish_acquisition_run(empty_run, 500) == "complete"
        assert repository.finish_acquisition_run(failing_run, 501) == "failed"
    finally:
        connection.close()


def test_finish_records_an_abnormal_failure_without_recomputing_it(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)

        # A run the service aborts before a single part was probed: the
        # operator's `failed` is the recorded truth, not the `complete` the
        # attempt derivation would have produced.
        assert repository.finish_acquisition_run(run_id, 500, outcome="failed") == (
            "failed"
        )
        stored = _record(
            repository, part_id, run_id=run_id, started_at=510, finished_at=520
        )
        assert stored.outcome == "stored"
        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        ) == ("failed", 500)
    finally:
        connection.close()


def test_finish_validates_its_arguments_and_the_run_it_targets(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        run_id = _run(repository, 1, started_at=100)

        with pytest.raises(sqlite3.IntegrityError, match="unknown run_id"):
            repository.finish_acquisition_run("caption-run-missing", 500)
        with pytest.raises(ValueError):
            repository.finish_acquisition_run(run_id, 500, outcome="running")
        with pytest.raises(ValueError):
            repository.finish_acquisition_run(run_id, 500, outcome="unknown")
        with pytest.raises(TypeError):
            repository.finish_acquisition_run(run_id, True)
        with pytest.raises(ValueError):
            repository.finish_acquisition_run("   ", 500)
        with pytest.raises(ValueError):
            repository.finish_acquisition_run(run_id, 99)

        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        ) == ("running", None)

        # The stored started_at is the ordering baseline, and a run with no
        # attempts at all is a complete run of an empty work set.
        assert repository.finish_acquisition_run(run_id, 100) == "complete"
    finally:
        connection.close()


def test_start_acquisition_run_rejects_a_duplicate_run_id(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        _run(repository, 1, selector_kind="bvid", selector_target="BV1CAPTION")

        with pytest.raises(sqlite3.IntegrityError):
            repository.start_acquisition_run(
                _caption_run("caption-run-1", started_at=999)
            )

        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT run_id, kind, selector_kind, selector_target, requested_limit, "
                "credential_present, started_at, finished_at, outcome "
                "FROM acquisition_runs"
            ).fetchall()
        ] == [
            (
                "caption-run-1",
                "subtitle",
                "bvid",
                "BV1CAPTION",
                None,
                0,
                101,
                None,
                "running",
            )
        ]
    finally:
        connection.close()


def test_no_subtitle_is_evidence_and_the_part_stays_reattemptable(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        first_run = _run(repository, 1, credential_present=False)
        repository.record_subtitle_attempt(
            run_id=first_run,
            video_part_id=part_id,
            outcome="no-subtitle",
            error_code=None,
            started_at=200,
            finished_at=300,
        )
        assert _attempt_rows(connection, first_run) == [
            (first_run, part_id, "no-subtitle", None, None, 200, 300)
        ]
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
        assert tuple(
            connection.execute(
                "SELECT attempted, last_attempt_at, last_attempt_outcome, "
                "last_attempt_error_code, last_attempt_credential_present "
                "FROM v_pending_subtitles WHERE video_part_id = ?",
                (part_id,),
            ).fetchone()
        ) == (1, 300, "no-subtitle", None, 0)

        # Upstream signalled "not visible" on the next probe: the run's
        # credential flag travels with the recorded code.
        second_run = _run(repository, 2, credential_present=True, started_at=310)
        repository.record_subtitle_attempt(
            run_id=second_run,
            video_part_id=part_id,
            outcome="no-subtitle",
            error_code="not_found",
            started_at=320,
            finished_at=330,
        )
        assert _attempt_rows(connection, second_run) == [
            (second_run, part_id, "no-subtitle", "not_found", None, 320, 330)
        ]
        assert tuple(
            connection.execute(
                "SELECT attempted, last_attempt_outcome, last_attempt_error_code, "
                "last_attempt_credential_present FROM v_pending_subtitles "
                "WHERE video_part_id = ?",
                (part_id,),
            ).fetchone()
        ) == (1, "no-subtitle", "not_found", 1)

        # Nothing was ever terminal: a later successful acquisition of the
        # same part stores a transcript normally.
        third_run = _run(repository, 3, started_at=340)
        stored = _record(
            repository,
            part_id,
            run_id=third_run,
            started_at=350,
            finished_at=360,
            created_at=370,
        )
        assert stored.outcome == "stored"
        assert stored.version == 1
        assert _attempt_rows(connection) == [
            (first_run, part_id, "no-subtitle", None, None, 200, 300),
            (second_run, part_id, "no-subtitle", "not_found", None, 320, 330),
            (third_run, part_id, "stored", None, stored.transcript_id, 350, 360),
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM v_pending_subtitles WHERE video_part_id = ?",
            (part_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"outcome": "stored"}, ValueError),
        ({"outcome": "unchanged"}, ValueError),
        ({"outcome": "unknown"}, ValueError),
        ({"outcome": "failed", "error_code": None}, ValueError),
        ({"outcome": "failed", "error_code": "e" * 65}, ValueError),
        ({"outcome": "failed", "error_code": '{"code": -403}'}, ValueError),
        ({"outcome": "no-subtitle", "error_code": "timeout"}, ValueError),
        ({"outcome": "no-subtitle", "error_code": 101}, TypeError),
        ({"absence_verified": 1}, TypeError),
        ({"absence_verified": "true"}, TypeError),
        ({"absence_verified": None}, TypeError),
        ({"absence_verified": True}, ValueError),
        ({"outcome": "failed", "error_code": "not_found", "absence_verified": True}, ValueError),
        ({"outcome": "no-subtitle", "error_code": None, "absence_verified": True}, ValueError),
        ({"video_part_id": 0}, ValueError),
        ({"started_at": 301, "finished_at": 300}, ValueError),
    ],
)
def test_subtitle_attempt_rejects_every_illegal_outcome_and_code(
    tmp_root, override, error
):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)
        kwargs: dict = {
            "run_id": run_id,
            "video_part_id": part_id,
            "outcome": "failed",
            "error_code": "timeout",
            "started_at": 200,
            "finished_at": 300,
        }
        kwargs.update(override)

        with pytest.raises(error):
            repository.record_subtitle_attempt(**kwargs)

        assert _attempt_rows(connection) == []
    finally:
        connection.close()


def test_subtitle_attempt_is_append_only_per_part_and_run(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        first_run = _run(repository, 1)
        repository.record_subtitle_attempt(
            run_id=first_run,
            video_part_id=part_id,
            outcome="failed",
            error_code="timeout",
            started_at=200,
            finished_at=300,
        )

        with pytest.raises(sqlite3.IntegrityError):
            repository.record_subtitle_attempt(
                run_id=first_run,
                video_part_id=part_id,
                outcome="no-subtitle",
                error_code=None,
                started_at=310,
                finished_at=320,
            )
        assert _attempt_rows(connection, first_run) == [
            (first_run, part_id, "failed", "timeout", None, 200, 300)
        ]

        # A later run records its own evidence for the same part.
        second_run = _run(repository, 2, started_at=330)
        repository.record_subtitle_attempt(
            run_id=second_run,
            video_part_id=part_id,
            outcome="no-subtitle",
            error_code=None,
            started_at=340,
            finished_at=350,
        )
        assert _attempt_rows(connection) == [
            (first_run, part_id, "failed", "timeout", None, 200, 300),
            (second_run, part_id, "no-subtitle", None, None, 340, 350),
        ]
    finally:
        connection.close()


def test_timeline_ceiling_is_the_storage_boundarys_rejection(tmp_root):
    """S11: an unrepresentable millisecond value is a bounded ValueError."""
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        assert MAX_TIMELINE_MS == 10**12
        # The bound belongs to the storage boundary, not to the segment
        # record, which validates the shape of one row.
        assert (
            TranscriptSegmentRecord(start_ms=0, end_ms=10**19, text="越界").end_ms
            == 10**19
        )

        boundary_part = _captioned_part(connection, "BV1BOUNDARY")
        beyond_part = _captioned_part(connection, "BV1BEYOND")
        boundary_run = _run(repository, 1)
        beyond_run = _run(repository, 2)

        at_ceiling = _record(
            repository,
            boundary_part,
            run_id=boundary_run,
            body=((0, MAX_TIMELINE_MS, "边界"),),
        )
        assert at_ceiling.outcome == "stored"
        assert _segment_rows(connection, at_ceiling.transcript_id) == [
            (0, 0, MAX_TIMELINE_MS, "边界")
        ]

        with pytest.raises(
            ValueError, match=f"segments\\[0\\]\\.end_ms must be at most {MAX_TIMELINE_MS}"
        ):
            _record(
                repository,
                beyond_part,
                run_id=beyond_run,
                body=((0, MAX_TIMELINE_MS + 1, "越界"),),
            )
        # A start above the ceiling is rejected as well, and so is a value
        # beyond the 64-bit integer SQLite binds: the guard is the only thing
        # between an upstream JSON integer and an OverflowError.
        for beyond_body in (
            ((MAX_TIMELINE_MS + 1, MAX_TIMELINE_MS + 2, "越界"),),
            ((0, 10**19, "越界"),),
        ):
            with pytest.raises(ValueError):
                _record(
                    repository, beyond_part, run_id=beyond_run, body=beyond_body
                )

        assert _transcript_rows(connection, beyond_part) == []
        assert _attempt_rows(connection, beyond_run) == []
    finally:
        connection.close()


def test_constructor_requires_the_open_database_connection_state(tmp_root):
    with pytest.raises(TypeError):
        TranscriptRepository("not a connection")

    connection = sqlite3.connect(os.path.join(tmp_root, "bare.db"))
    try:
        with pytest.raises(TypeError):
            TranscriptRepository(connection)
        connection.row_factory = sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        with pytest.raises(ValueError):
            TranscriptRepository(connection)
    finally:
        connection.close()


def test_constructor_refuses_a_legacy_database_with_the_bounded_error(tmp_root):
    """The schema guard holds at the boundary, not only in the caller.

    ``require_subtitle_schema`` is the CLI's obligation, but a caller that
    skips it must not meet a raw ``OperationalError`` from the first query:
    constructing the repository on a database that predates the transcript
    contract raises the same bounded rebuild error the guard raises.
    """
    database_path = os.path.join(tmp_root, "archive.db")
    _write_pre_iteration_database(database_path)

    # Bypass bootstrap deliberately: normal opens now refuse this entire old
    # database. A repository constructed on a raw handle must also diagnose it.
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(SchemaContractError) as refused:
            TranscriptRepository(connection)
        message = str(refused.value)
        assert "transcript schema contract missing" in message
        assert "delete archive.db and re-run fetch-meta" in message
        assert "discarded" in message and "recollected" in message
    finally:
        connection.close()


def test_committed_writes_are_visible_outside_the_writing_connection(tmp_root):
    database_path = os.path.join(tmp_root, "archive.db")
    connection = open_database(database_path)
    observer = sqlite3.connect(database_path)
    observer.row_factory = sqlite3.Row
    try:
        repository = TranscriptRepository(connection)
        part_id = _captioned_part(connection)
        assert observer.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1

        # start_acquisition_run commits its own insert.
        run_id = _run(repository, 1)
        assert (
            observer.execute("SELECT COUNT(*) FROM acquisition_runs").fetchone()[0]
            == 1
        )

        # record_acquired_transcript commits the version, its segments, and its
        # attempt row as one transaction.
        stored = _record(repository, part_id, run_id=run_id)
        assert tuple(
            observer.execute(
                "SELECT version, content_sha256 FROM transcripts"
            ).fetchone()
        ) == (1, stored.content_sha256)
        assert (
            observer.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
            == 2
        )
        assert (
            observer.execute("SELECT COUNT(*) FROM acquisition_attempts").fetchone()[0]
            == 1
        )

        # record_subtitle_attempt commits its own evidence transaction.
        other_part = _captioned_part(connection, "BV1PROBED")
        empty_run = _run(repository, 2)
        repository.record_subtitle_attempt(
            run_id=empty_run,
            video_part_id=other_part,
            outcome="no-subtitle",
            error_code=None,
            started_at=200,
            finished_at=300,
        )
        assert tuple(
            observer.execute(
                "SELECT outcome, transcript_id FROM acquisition_attempts "
                "WHERE run_id = ?",
                (empty_run,),
            ).fetchone()
        ) == ("no-subtitle", None)

        # finish_acquisition_run commits its own terminal transition.
        assert repository.finish_acquisition_run(empty_run, 400) == "complete"
        assert tuple(
            observer.execute(
                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
                (empty_run,),
            ).fetchone()
        ) == ("complete", 400)
    finally:
        observer.close()
        connection.close()


def test_read_transcript_returns_the_latest_version_and_keeps_an_older_one_readable(
    tmp_root,
):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        cc_v1 = _record(repository, part_id, run_id=_run(repository, 1))
        cc_v2 = _record(
            repository,
            part_id,
            run_id=_run(repository, 2),
            body=CHANGED_BODY,
            started_at=210,
            finished_at=310,
            created_at=410,
        )
        ai_v1 = _record(
            repository,
            part_id,
            run_id=_run(repository, 3),
            source_kind="subtitle-ai",
            language="ai-zh",
            started_at=220,
            finished_at=320,
            created_at=420,
        )
        stored_counts = _empty_store(connection)

        latest = repository.read_transcript(part_id, "subtitle-cc", "zh-CN")

        assert isinstance(latest, TranscriptRecord)
        assert latest.transcript_id == cc_v2.transcript_id
        assert latest.version == 2
        assert latest.video_part_id == part_id
        assert latest.source_kind == "subtitle-cc"
        assert latest.language == "zh-CN"
        assert latest.model_id is None
        assert latest.content_sha256 == cc_v2.content_sha256
        assert latest.created_at == 410
        assert _triples(latest.segments) == list(CHANGED_BODY)

        # One part carries several languages, each with its own version history.
        ai = repository.read_transcript(part_id, "subtitle-ai", "ai-zh")
        assert ai is not None
        assert (ai.transcript_id, ai.version) == (ai_v1.transcript_id, 1)
        assert ai.content_sha256 == ai_v1.content_sha256
        assert _triples(ai.segments) == list(BODY)

        # An explicit older version stays readable after the newer one landed.
        first = repository.read_transcript(part_id, "subtitle-cc", "zh-CN", 1)
        assert first is not None
        assert (first.transcript_id, first.version) == (cc_v1.transcript_id, 1)
        assert first.content_sha256 == cc_v1.content_sha256
        assert first.created_at == 400
        assert _triples(first.segments) == list(BODY)

        # The read names the identity the write stored: the same trimming.
        padded = repository.read_transcript(part_id, "subtitle-cc", " zh-CN ")
        assert padded is not None and padded.version == 2

        # Read paths never write and never commit.
        assert _empty_store(connection) == stored_counts
        assert connection.in_transaction is False
    finally:
        connection.close()


def test_list_transcript_versions_lists_one_identitys_versions_oldest_first(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        cc_v1 = _record(repository, part_id, run_id=_run(repository, 1))
        cc_v2 = _record(
            repository,
            part_id,
            run_id=_run(repository, 2),
            body=CHANGED_BODY,
            created_at=410,
        )
        _record(
            repository,
            part_id,
            run_id=_run(repository, 3),
            source_kind="subtitle-ai",
            language="ai-zh",
        )

        versions = repository.list_transcript_versions(part_id, "subtitle-cc", "zh-CN")

        assert [row["version"] for row in versions] == [1, 2]
        assert [row["transcript_id"] for row in versions] == [
            cc_v1.transcript_id,
            cc_v2.transcript_id,
        ]
        assert [row["content_sha256"] for row in versions] == [
            cc_v1.content_sha256,
            cc_v2.content_sha256,
        ]
        assert [row["created_at"] for row in versions] == [400, 410]
        assert {row["source_kind"] for row in versions} == {"subtitle-cc"}
        assert {row["language"] for row in versions} == {"zh-CN"}
        # The rows are the stored rows: every transcript column is readable.
        assert {
            "transcript_id",
            "video_part_id",
            "source_kind",
            "language",
            "model_id",
            "version",
            "content_sha256",
            "created_at",
        } <= set(versions[0].keys())

        # Another identity's versions are not mixed in, and the language is
        # trimmed before the lookup exactly as the write path trims it.
        other = repository.list_transcript_versions(part_id, "subtitle-ai", " ai-zh ")
        assert [row["version"] for row in other] == [1]
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 3
    finally:
        connection.close()


def test_reads_of_absent_versions_identities_and_parts_are_empty(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        stored = _record(repository, part_id, run_id=_run(repository, 1))

        assert repository.read_transcript(part_id, "subtitle-cc", "zh-CN", 2) is None
        assert repository.read_transcript(part_id, "subtitle-cc", "en-US") is None
        assert repository.read_transcript(part_id, "subtitle-ai", "zh-CN") is None
        assert repository.read_transcript(9_999, "subtitle-cc", "zh-CN") is None
        assert repository.list_transcript_versions(part_id, "subtitle-cc", "en-US") == []
        assert repository.list_transcript_versions(part_id, "subtitle-ai", "zh-CN") == []

        # The asr-local reservation is a legal read that holds no row yet: the
        # read accepts the vocabulary the column's CHECK accepts.
        assert repository.read_transcript(part_id, "asr-local", "zh-CN") is None
        assert repository.list_transcript_versions(part_id, "asr-local", "zh-CN") == []

        versions = repository.list_transcript_versions(part_id, "subtitle-cc", "zh-CN")
        assert [row["version"] for row in versions] == [1]
        assert versions[0]["transcript_id"] == stored.transcript_id
        assert versions[0]["content_sha256"] == stored.content_sha256
        assert _empty_store(connection) == (1, 2, 1)
    finally:
        connection.close()


def test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt(tmp_root):
    """The locked order: attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC."""
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        # Insertion order deliberately differs from the work order, so a
        # missing ORDER BY cannot pass by accident. Both captionless videos
        # hold page 0 and page 1, so the never-attempted set is a case where
        # ``bvid`` first and ``page_index`` first interleave differently: the
        # lock's last two keys are falsifiable, not merely spelled out.
        first_video = _video_with_parts(connection, "BV1A", (3001, 3002, 3003, 3004))
        _video_with_parts(connection, "BV0Z", (4001, 4002))
        _video_with_parts(connection, "BV1GONE", (5001,), processing_status="gone")
        # Page 5 is stored *before* its page 4 sibling — ``_video_with_parts``
        # writes one ascending page per position, so this pair goes through the
        # parts write path directly. Insertion order and page order therefore
        # disagree inside this bvid, which is what makes the final key
        # falsifiable on its own: without ``page_index ASC`` this pair comes
        # back as p5, p4 (rowid order) instead.
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            for page_index, cid in ((5, 3006), (4, 3005)):
                metadata.upsert_part(
                    make_part_record(
                        "BV1A",
                        page_index=page_index,
                        cid=cid,
                        title=f"第{page_index + 1}集",
                        processing_status="metadata_collected",
                    )
                )
        _probe(repository, first_video[2], index=1, finished_at=500)
        _probe(repository, first_video[3], index=2, finished_at=300)

        work_ids = [row["work_id"] for row in repository.list_pending_subtitle_parts()]

        assert work_ids == [
            "BV0Z:p0",  # never attempted: lowest bvid, then lowest page index,
            "BV0Z:p1",  # so this block is BV0Z's two pages and then BV1A's four;
            "BV1A:p0",  # ordering by page_index first would interleave it as
            "BV1A:p1",  # BV0Z:p0, BV1A:p0, BV0Z:p1, BV1A:p1 instead, and
            "BV1A:p4",  # dropping page_index ASC would return BV1A:p5 first.
            "BV1A:p5",
            "BV1A:p3",  # oldest attempt first
            "BV1A:p2",
        ]
        # A part upstream reported as gone is not work: the enumeration is
        # bounded to what can still yield a caption.
        assert "BV1GONE:p0" not in work_ids
        assert repository.count_pending_subtitle_parts() == len(work_ids) == 8

        # The bound takes the head of the locked order.
        assert [
            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=1)
        ] == ["BV0Z:p0"]
        assert [
            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=2)
        ] == ["BV0Z:p0", "BV0Z:p1"]
        assert [
            row["work_id"] for row in repository.list_pending_subtitle_parts(limit=8)
        ] == work_ids
    finally:
        connection.close()


def test_pending_enumeration_carries_the_last_attempt_evidence_and_excludes_stored_parts(
    tmp_root,
):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        parts = _video_with_parts(connection, "BV1EVID", (6001, 6002, 6003))
        metadata_only, probed, captioned = parts[0], parts[1], parts[2]
        stored = _record(repository, captioned, run_id=_run(repository, 1))
        _probe(repository, probed, index=2, finished_at=300)
        _probe(
            repository,
            probed,
            index=3,
            finished_at=500,
            error_code="not_found",
            credential_present=True,
        )

        rows = repository.list_pending_subtitle_parts()

        # The part holding a transcript is not pending work any more; the part
        # with metadata only and the probed part both are.
        assert [row["work_id"] for row in rows] == ["BV1EVID:p0", "BV1EVID:p1"]
        assert {row["video_part_id"] for row in rows}.isdisjoint({captioned})
        assert repository.count_pending_subtitle_parts() == len(rows) == 2
        assert stored.version == 1

        # The work item is complete: the gateway call needs the cid, and the
        # subtitle path never re-fetches a pagelist.
        assert set(rows[0].keys()) == {
            "video_part_id",
            "work_id",
            "bvid",
            "page_index",
            "cid",
            "part_title",
            "duration_ms",
            "attempted",
            "last_attempt_at",
            "last_attempt_outcome",
            "last_attempt_error_code",
            "last_attempt_credential_present",
        }

        fresh = rows[0]
        assert fresh["video_part_id"] == metadata_only
        assert fresh["bvid"] == "BV1EVID"
        assert fresh["page_index"] == 0
        assert fresh["cid"] == 6001
        assert fresh["part_title"] == "第1集"
        assert fresh["duration_ms"] == 1_234
        assert fresh["attempted"] == 0
        assert fresh["last_attempt_at"] is None
        assert fresh["last_attempt_outcome"] is None
        assert fresh["last_attempt_error_code"] is None
        assert fresh["last_attempt_credential_present"] is None

        # "No caption was visible" is evidence, not a terminal state: the part
        # stays in the backlog with its newest attempt, its code, and the
        # credential presence of the run that probed it.
        retried = rows[1]
        assert retried["video_part_id"] == probed
        assert retried["cid"] == 6002
        assert retried["attempted"] == 1
        assert retried["last_attempt_at"] == 500
        assert retried["last_attempt_outcome"] == "no-subtitle"
        assert retried["last_attempt_error_code"] == "not_found"
        assert retried["last_attempt_credential_present"] == 1
    finally:
        connection.close()


def test_a_part_recorded_no_subtitle_leaves_the_pending_set_when_a_later_run_stores_it(
    tmp_root,
):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        parts = _video_with_parts(connection, "BV1RETRY", (7001, 7002, 7003))
        probed, untouched, failing = parts[0], parts[1], parts[2]
        probe_run = _probe(
            repository,
            probed,
            index=1,
            finished_at=300,
            error_code="not_found",
            credential_present=True,
        )
        failed_run = _run(repository, 2, started_at=340)
        repository.record_subtitle_attempt(
            run_id=failed_run,
            video_part_id=failing,
            outcome="failed",
            error_code="timeout",
            started_at=340,
            finished_at=350,
        )
        assert repository.finish_acquisition_run(probe_run, 310) == "complete"
        assert repository.finish_acquisition_run(failed_run, 360) == "failed"

        # Both kinds of evidence keep their part in the backlog, and the
        # never-attempted part is enumerated before both.
        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
            "BV1RETRY:p1",
            "BV1RETRY:p0",
            "BV1RETRY:p2",
        ]

        harvest_run = _run(repository, 3, started_at=400)
        stored = _record(
            repository,
            probed,
            run_id=harvest_run,
            started_at=410,
            finished_at=420,
            created_at=430,
        )

        assert stored.outcome == "stored"
        assert stored.version == 1
        # The run is finished after its part loop, so the outcome stays a
        # function of the attempts it holds.
        assert repository.finish_acquisition_run(harvest_run, 440) == "complete"
        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
            "BV1RETRY:p1",
            "BV1RETRY:p2",
        ]
        assert repository.count_pending_subtitle_parts() == 2

        # Every probe stays readable as run-scoped evidence.
        assert _attempt_rows(connection, probe_run) == [
            (probe_run, probed, "no-subtitle", "not_found", None, 290, 300)
        ]
        assert _attempt_rows(connection, failed_run) == [
            (failed_run, failing, "failed", "timeout", None, 340, 350)
        ]
        assert _attempt_rows(connection, harvest_run) == [
            (harvest_run, probed, "stored", None, stored.transcript_id, 410, 420)
        ]
        reread = repository.read_transcript(probed, "subtitle-cc", "zh-CN")
        assert reread is not None and reread.version == 1
    finally:
        connection.close()


def test_list_selected_parts_selects_explicitly_or_returns_no_rows(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        parts = _video_with_parts(connection, "BV1SELECT", (8001, 8002))
        stored = _record(repository, parts[0], run_id=_run(repository, 1))
        _video_with_parts(connection, "BV1GONEVID", (8101,), processing_status="gone")

        rows = repository.list_selected_parts("BV1SELECT")

        assert [row["work_id"] for row in rows] == ["BV1SELECT:p0", "BV1SELECT:p1"]
        assert [row["cid"] for row in rows] == [8001, 8002]
        assert set(rows[0].keys()) == {
            "video_part_id",
            "work_id",
            "user_name",
            "video_title",
            "page_index",
            "cid",
            "part_title",
            "duration_ms",
            "processing_status",
            "created_at",
            "updated_at",
        }
        # Explicit means explicit: the part that already holds a transcript is
        # selected, which is how the operator re-checks a video.
        assert rows[0]["video_part_id"] == parts[0]
        assert rows[0]["work_id"] == f"BV1SELECT:p{rows[0]['page_index']}"
        assert stored.version == 1
        assert repository.read_transcript(parts[0], "subtitle-cc", "zh-CN") is not None

        one = repository.list_selected_parts("BV1SELECT", 1)
        assert [row["work_id"] for row in one] == ["BV1SELECT:p1"]
        assert one[0]["video_part_id"] == parts[1]

        # An explicit selection is not filtered by status, while the pending
        # enumeration leaves a gone part out.
        assert [
            row["work_id"] for row in repository.list_selected_parts("BV1GONEVID")
        ] == ["BV1GONEVID:p0"]
        assert repository.list_selected_parts("BV1GONEVID")[0]["processing_status"] == (
            "gone"
        )
        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
            "BV1SELECT:p1"
        ]

        # An unknown selector yields no rows rather than an invented selection.
        assert repository.list_selected_parts("BV1UNKNOWN") == []
        assert repository.list_selected_parts("BV1UNKNOWN", 0) == []
        assert repository.list_selected_parts("BV1SELECT", 9) == []
    finally:
        connection.close()


def test_pending_enumeration_reuses_the_shipped_limit_validation(tmp_root):
    """The bound is validated exactly like ``MetadataRepository.list_pending_parts``."""
    connection = open_database(tmp_root)
    try:
        metadata = MetadataRepository(connection)
        transcripts = TranscriptRepository(connection)

        for bad_limit in (0, -1, True, "2", 1.5):
            with pytest.raises((TypeError, ValueError)) as shipped:
                metadata.list_pending_parts(bad_limit)
            with pytest.raises(type(shipped.value)) as pending:
                transcripts.list_pending_subtitle_parts(bad_limit)
            assert str(pending.value) == str(shipped.value)
        assert transcripts.list_pending_subtitle_parts(None) == []
    finally:
        connection.close()


def test_read_paths_consume_the_views_instead_of_re_deriving_them(tmp_root):
    """The backlog and the explicit selection are view reads, not re-derivations.

    Dropping the relation a method claims to read is the cheapest way to prove
    the claim: a re-derived query over the base tables would keep answering.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        _video_with_parts(connection, "BV1VIEW", (9001,))
        assert [row["work_id"] for row in repository.list_pending_subtitle_parts()] == [
            "BV1VIEW:p0"
        ]
        assert repository.count_pending_subtitle_parts() == 1
        assert [row["work_id"] for row in repository.list_selected_parts("BV1VIEW")] == [
            "BV1VIEW:p0"
        ]

        connection.execute("DROP VIEW v_pending_subtitles")
        with pytest.raises(sqlite3.OperationalError, match="v_pending_subtitles"):
            repository.list_pending_subtitle_parts()
        with pytest.raises(sqlite3.OperationalError, match="v_pending_subtitles"):
            repository.count_pending_subtitle_parts()

        connection.execute("DROP VIEW v_video_parts")
        with pytest.raises(sqlite3.OperationalError, match="v_video_parts"):
            repository.list_selected_parts("BV1VIEW")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("method", "kwargs", "error"),
    [
        (
            "read_transcript",
            {"video_part_id": 0, "source_kind": "subtitle-cc", "language": "zh-CN"},
            ValueError,
        ),
        (
            "read_transcript",
            {"video_part_id": True, "source_kind": "subtitle-cc", "language": "zh-CN"},
            TypeError,
        ),
        (
            "read_transcript",
            {"video_part_id": 1, "source_kind": "unknown", "language": "zh-CN"},
            ValueError,
        ),
        (
            "read_transcript",
            {"video_part_id": 1, "source_kind": "subtitle-cc", "language": "   "},
            ValueError,
        ),
        (
            "read_transcript",
            {"video_part_id": 1, "source_kind": "subtitle-cc", "language": None},
            TypeError,
        ),
        (
            "read_transcript",
            {
                "video_part_id": 1,
                "source_kind": "subtitle-cc",
                "language": "zh-CN",
                "version": 0,
            },
            ValueError,
        ),
        (
            "list_transcript_versions",
            {"video_part_id": 0, "source_kind": "x", "language": "y"},
            ValueError,
        ),
        ("list_selected_parts", {"bvid": "   "}, ValueError),
        ("list_selected_parts", {"bvid": None}, TypeError),
        ("list_selected_parts", {"bvid": "BV1SELECT", "page_index": -1}, ValueError),
        ("list_selected_parts", {"bvid": "BV1SELECT", "page_index": True}, TypeError),
        ("list_pending_subtitle_parts", {"limit": 0}, ValueError),
        ("list_pending_subtitle_parts", {"limit": True}, TypeError),
        ("list_pending_subtitle_parts", {"limit": "2"}, TypeError),
    ],
)
def test_read_arguments_follow_the_module_validation_discipline(
    tmp_root, method, kwargs, error
):
    """Read-path arguments raise ``TypeError``/``ValueError`` as the writes do."""
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        with pytest.raises(error):
            getattr(repository, method)(**kwargs)
    finally:
        connection.close()


def test_work_id_is_computed_by_the_views_and_never_stored(tmp_root):
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        _run(repository, 1)

        # The read rows carry the work identifier the views compute; the
        # transcript contract stores no such column.
        assert [
            row["work_id"] for row in repository.list_pending_subtitle_parts()
        ] == ["BV1CAPTION:p0"]
        assert [
            row["work_id"] for row in repository.list_selected_parts("BV1CAPTION")
        ] == ["BV1CAPTION:p0"]
        assert connection.execute(
            "SELECT work_id FROM v_video_parts WHERE video_part_id = ?", (part_id,)
        ).fetchone()[0] == "BV1CAPTION:p0"

        for table in (
            "transcripts",
            "transcript_segments",
            "acquisition_runs",
            "acquisition_attempts",
        ):
            with pytest.raises(
                sqlite3.OperationalError, match="no such column: work_id"
            ):
                connection.execute(f"UPDATE {table} SET work_id = 'BV1CAPTION:p0'")
    finally:
        connection.close()


def test_segments_keep_the_callers_order_and_overlaps_verbatim(tmp_root):
    """§5: upstream order is preserved verbatim, overlaps included."""
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        # Reversed and overlapping on purpose: the write must neither sort the
        # body nor reject an interval that starts before the previous one ends.
        body = (
            (1_200, 2_400, "第二句"),
            (600, 1_800, "与第二句重叠"),
            (0, 1_200, "第一句"),
        )

        result = _record(repository, part_id, run_id=_run(repository, 1), body=body)

        assert result.outcome == "stored"
        assert result.content_sha256 == _expected_content_sha256(body)
        assert _segment_rows(connection, result.transcript_id) == [
            (0, 1_200, 2_400, "第二句"),
            (1, 600, 1_800, "与第二句重叠"),
            (2, 0, 1_200, "第一句"),
        ]

        # Sorting or de-overlapping the body on write would change the digest as
        # well as the ordinals, so either regression fails here.
        sorted_body = tuple(sorted(body, key=lambda triple: triple[0]))
        assert sorted_body != body
        assert result.content_sha256 != _expected_content_sha256(sorted_body)

        # The same body is still content-identical, and the read path answers
        # the order the caller supplied.
        repeat_run = _run(repository, 2)
        repeat = _record(repository, part_id, run_id=repeat_run, body=body)
        assert repeat.outcome == "unchanged"
        assert repeat.version == 1
        stored = repository.read_transcript(part_id, "subtitle-cc", "zh-CN")
        assert stored is not None
        assert _triples(stored.segments) == list(body)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("bad_run_id", "error", "message"),
    [
        ("", ValueError, "run_id must not be empty"),
        ("   ", ValueError, "run_id must not be empty"),
        ("r\n1", ValueError, "run_id contains invalid control characters"),
        ("r\x001", ValueError, "run_id contains invalid control characters"),
        (None, TypeError, "run_id must be a string"),
        (7, TypeError, "run_id must be a string"),
    ],
)
def test_run_id_is_validated_by_one_shared_path_across_the_class(
    tmp_root, bad_run_id, error, message
):
    """M2: every method answers a malformed ``run_id`` with the same message."""
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)
        stored_counts = _empty_store(connection)

        calls = {
            "start_acquisition_run": lambda: repository.start_acquisition_run(
                _caption_run(bad_run_id)
            ),
            "finish_acquisition_run": lambda: repository.finish_acquisition_run(
                bad_run_id, 500
            ),
            "record_acquired_transcript": lambda: _record(
                repository, part_id, run_id=bad_run_id
            ),
            "record_subtitle_attempt": lambda: repository.record_subtitle_attempt(
                run_id=bad_run_id,
                video_part_id=part_id,
                outcome="no-subtitle",
                error_code=None,
                started_at=200,
                finished_at=300,
            ),
        }
        for name, call in calls.items():
            with pytest.raises(error) as raised:
                call()
            assert str(raised.value) == message, name

        # A rejected identifier never reaches a write.
        assert _empty_store(connection) == stored_counts
        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM acquisition_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        ) == ("running", None)
    finally:
        connection.close()


def test_storage_paths_never_read_or_write_a_legacy_sidecar(tmp_root, monkeypatch):
    """No storage path opens or creates a file in the archive root but ``archive.db``.

    The legacy sidecars are planted with content no reader could accept, so a
    path that consulted one would change its outcome or rewrite the file.  Every
    Python-level open below the archive root is intercepted and recorded as well,
    and the intercept is proven armed inside the test before it is trusted: SQLite
    reaches the database through its own C library, so without that proof the
    recorded list could stay empty and prove nothing about reads.
    """
    poison = {
        os.path.join("manifest", "manifest.jsonl"): "poison: manifest\n",
        "meta-cursor.json": "poison: cursor\n",
        "run-ledger.jsonl": "poison: ledger\n",
    }
    assert set(poison) == set(LEGACY_SIDECAR_PATHS)
    for relative, payload in poison.items():
        path = os.path.join(tmp_root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)

    archive_root = os.path.realpath(tmp_root)
    real_open = io.open
    opened: list[str] = []

    def guarded_open(file, *args, **kwargs):
        target = os.path.realpath(os.fspath(file))
        if target.startswith(archive_root + os.sep):
            opened.append(target)
            if os.path.basename(target) not in {"archive.db", "archive.db-journal"}:
                raise AssertionError(f"a storage path opened the sidecar {target}")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(builtins, "open", guarded_open)

    # The intercept fires on exactly the opens it must reject, so an empty
    # record below is evidence and not an unarmed guard.
    with pytest.raises(AssertionError, match="opened the sidecar"):
        open(os.path.join(tmp_root, "meta-cursor.json"), encoding="utf-8")
    assert [os.path.basename(path) for path in opened] == ["meta-cursor.json"]
    opened.clear()

    connection = open_database(tmp_root)
    try:
        repository = TranscriptRepository(connection)
        part_id = _captioned_part(connection)
        run_id = _run(repository, 1)
        stored = _record(repository, part_id, run_id=run_id)

        # Every read path runs too, so nothing is proven only about the writes.
        assert repository.read_transcript(part_id, "subtitle-cc", "zh-CN") is not None
        assert repository.list_transcript_versions(part_id, "subtitle-cc", "zh-CN")
        assert repository.list_pending_subtitle_parts() == []
        assert repository.count_pending_subtitle_parts() == 0
        assert repository.list_selected_parts("BV1CAPTION")
        assert repository.finish_acquisition_run(run_id, 500) == "complete"
        assert stored.outcome == "stored"
    finally:
        connection.close()

    # No storage path opened anything below the archive root through Python:
    # the database itself is reached by SQLite's C library, so a sidecar read
    # could only have come through this intercept, and it recorded nothing.
    assert opened == []
    # The archive root holds the database and exactly the files already there.
    discovered = sorted(
        os.path.relpath(os.path.join(folder, name), tmp_root)
        for folder, _, names in os.walk(tmp_root)
        for name in names
    )
    assert discovered == sorted(["archive.db", *poison])
    for relative, payload in poison.items():
        with real_open(os.path.join(tmp_root, relative), encoding="utf-8") as handle:
            assert handle.read() == payload


def test_read_video_pubdates_returns_stored_seconds(tmp_root):
    """The stored ``videos.pubdate`` per bvid, and no entry for a miss.

    The publication second is a store fact the manifest derivation copies onto
    its rows, so the read answers exactly what ``videos`` holds: one
    distinguishing value per bvid proves the answer is the stored column and not
    a constant, and a bvid the archive does not hold yields no key instead of an
    invented date.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        published = replace(make_video_record("BV1PUB", aid=None), pubdate=1_600_000_000)
        other = replace(make_video_record("BV1OTHER", aid=None), pubdate=1_700_000_000)
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            metadata.upsert_user(make_user_record())
            metadata.upsert_video(published)
            metadata.upsert_video(other)
            metadata.upsert_part(make_part_record("BV1PUB", processing_status="metadata_collected"))
            metadata.upsert_part(make_part_record("BV1OTHER", cid=9001, processing_status="metadata_collected"))

        assert repository.read_video_pubdates(["BV1PUB", "BV1OTHER"]) == {
            "BV1PUB": 1_600_000_000,
            "BV1OTHER": 1_700_000_000,
        }
        assert repository.read_video_pubdates(["BV1OTHER", "BV1PUB"]) == {
            "BV1OTHER": 1_700_000_000,
            "BV1PUB": 1_600_000_000,
        }
        assert repository.read_video_pubdates(["BV1PUB", "BV1UNKNOWN"]) == {
            "BV1PUB": 1_600_000_000
        }
        assert repository.read_video_pubdates(["BV1UNKNOWN"]) == {}
        # A repeated bvid is answered once, not once per occurrence.
        assert repository.read_video_pubdates(["BV1PUB", "BV1PUB"]) == {
            "BV1PUB": 1_600_000_000
        }

        # The keys are validated like every other read argument in this module.
        with pytest.raises(TypeError):
            repository.read_video_pubdates([None])
        with pytest.raises(ValueError):
            repository.read_video_pubdates([""])
    finally:
        connection.close()


def test_read_video_pubdates_answers_the_same_mapping_across_chunks(tmp_root):
    """A key list wider than one statement reads as one mapping.

    The queue's distinct bvid count is bounded by the store, not by the read, so
    the lookup is issued in bounded chunks: SQLite builds before 3.32.0 allow 999
    host parameters per statement.  The answer must not depend on which chunk a
    bvid landed in — including the short final one — so a 905-key read under a
    900-parameter statement cap is compared against single-statement reads of the
    first chunk and of the remainder, and against the stored column with no
    constant substituted.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        keys = [f"BV{index:010d}" for index in range(_STATEMENT_PARAMETER_CAP + 5)]
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            metadata.upsert_user(make_user_record())
            for index, bvid in enumerate(keys):
                metadata.upsert_video(
                    replace(
                        make_video_record(bvid, aid=None),
                        pubdate=1_600_000_000 + index,
                    )
                )

        expected = {bvid: 1_600_000_000 + index for index, bvid in enumerate(keys)}
        # The read is only a multi-chunk read if its own bound stays inside the
        # cap it exists for; a bound that grew past it fails here instead of
        # quietly shrinking this case back to a single statement.
        assert _PUBDATE_CHUNK <= _STATEMENT_PARAMETER_CAP
        # This host's driver raises its own ceiling to 250,000, so the cap the
        # case is about is pinned on the connection instead of inherited.
        connection.setlimit(
            sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, _STATEMENT_PARAMETER_CAP
        )

        assert repository.read_video_pubdates(keys) == expected
        assert repository.read_video_pubdates(keys[:_STATEMENT_PARAMETER_CAP]) == {
            bvid: expected[bvid] for bvid in keys[:_STATEMENT_PARAMETER_CAP]
        }
        assert repository.read_video_pubdates(keys[_STATEMENT_PARAMETER_CAP:]) == {
            bvid: expected[bvid] for bvid in keys[_STATEMENT_PARAMETER_CAP:]
        }
    finally:
        connection.close()


def test_read_video_pubdates_of_no_bvid_is_empty(tmp_root):
    """No bvid means no query: an ``IN ()`` list is a syntax error, not a read."""
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        assert repository.read_video_pubdates([]) == {}
        assert repository.read_video_pubdates(()) == {}
    finally:
        connection.close()


def _stored_row(
    *,
    video_part_id: int,
    bvid: str,
    page_index: int,
    cid: int,
    part_title: str,
    pubdate: int,
    transcript_id: int,
    source_kind: str,
    language: str,
    version: int,
    content_sha256: str,
    duration_ms: int = 1_234,
    model_id: int | None = None,
    created_at: int = 400,
    video_title: str = "字幕测试视频",
) -> dict:
    """Build one expected ``list_stored_transcripts`` row as a plain mapping.

    The key set is the read's declared column list: a read that selects a column
    too many, names one differently, or derives one instead of returning the
    stored value fails the mapping equality it is compared against.

    ``video_title`` defaults to the title every fixture in this file seeds its
    video with (``_captioned_part`` and ``_video_with_parts`` both store
    ``字幕测试视频``), so it reads as the video's own fact rather than as a
    repeat of the part's.
    """
    return {
        "video_part_id": video_part_id,
        "bvid": bvid,
        "page_index": page_index,
        "cid": cid,
        "part_title": part_title,
        "duration_ms": duration_ms,
        "pubdate": pubdate,
        "video_title": video_title,
        "transcript_id": transcript_id,
        "source_kind": source_kind,
        "language": language,
        "model_id": model_id,
        "version": version,
        "content_sha256": content_sha256,
        "created_at": created_at,
    }


def test_list_stored_transcripts_returns_one_row_per_version_with_part_context(
    tmp_root,
):
    """One row per stored version, carrying its part's and its video's facts.

    The relation is over ``transcripts``, not over parts: a part holding three
    stored versions appears three times and each row repeats the part context,
    which is what lets the projection pick one winner per part without a second
    query.  Two videos with different pubdates make the ``videos`` join
    discriminating — one constant cannot satisfy both rows — and the title is
    the part's, not the video's.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        parts = _video_with_parts(connection, "BV1STORED", (7001,))
        other = _video_with_parts(
            connection, "BV2OTHERPUB", (7101,), pubdate=1_600_000_000
        )
        first = _record(repository, parts[0], run_id=_run(repository, 1))
        second = _record(
            repository, parts[0], body=CHANGED_BODY, run_id=_run(repository, 2)
        )
        ai = _record(
            repository,
            parts[0],
            source_kind="subtitle-ai",
            language="ai-zh",
            run_id=_run(repository, 3),
        )
        elsewhere = _record(repository, other[0], run_id=_run(repository, 4))

        rows = repository.list_stored_transcripts()

        # The declared key set, once: the part context and the transcript
        # identity, and no ``work_id`` — the caller derives that identifier from
        # ``bvid``/``page_index`` rather than reading it here.  ``video_title``
        # belongs to the part context beside ``pubdate``: both are the video's
        # own columns, reached through the read's existing join.
        assert set(rows[0].keys()) == {
            "video_part_id",
            "bvid",
            "page_index",
            "cid",
            "part_title",
            "duration_ms",
            "pubdate",
            "video_title",
            "transcript_id",
            "source_kind",
            "language",
            "model_id",
            "version",
            "content_sha256",
            "created_at",
        }
        assert [dict(row) for row in rows] == [
            _stored_row(
                video_part_id=parts[0],
                bvid="BV1STORED",
                page_index=0,
                cid=7001,
                part_title="第1集",
                pubdate=1_700_000_000,
                transcript_id=ai.transcript_id,
                source_kind="subtitle-ai",
                language="ai-zh",
                version=1,
                content_sha256=ai.content_sha256,
            ),
            _stored_row(
                video_part_id=parts[0],
                bvid="BV1STORED",
                page_index=0,
                cid=7001,
                part_title="第1集",
                pubdate=1_700_000_000,
                transcript_id=second.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=2,
                content_sha256=second.content_sha256,
            ),
            _stored_row(
                video_part_id=parts[0],
                bvid="BV1STORED",
                page_index=0,
                cid=7001,
                part_title="第1集",
                pubdate=1_700_000_000,
                transcript_id=first.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=first.content_sha256,
            ),
            _stored_row(
                video_part_id=other[0],
                bvid="BV2OTHERPUB",
                page_index=0,
                cid=7101,
                part_title="第1集",
                pubdate=1_600_000_000,
                transcript_id=elsewhere.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=elsewhere.content_sha256,
            ),
        ]
    finally:
        connection.close()


def test_list_stored_transcripts_names_the_video_its_part_belongs_to(tmp_root):
    """``video_title`` is the video's own title; ``part_title`` stays the part's.

    Compass **D5**: ``title`` is the specific thing archived and ``video_title``
    the collection it came from.  Measured on the live store, 10 of 63 parts
    diverge, so the fixture is the separating shape — the video is
    ``字幕测试视频`` while its part is ``第1集`` — rather than a pair that happens
    to coincide.  A read that returned the part's title twice, or that dropped
    the video's, fails here.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        parts = _video_with_parts(connection, "BV1VDOTITLE", (7201,))
        _record(repository, parts[0], run_id=_run(repository, 1))

        rows = repository.list_stored_transcripts("BV1VDOTITLE")

        assert len(rows) == 1
        row = rows[0]
        # Asserted separately: conflating the two is exactly what D5 forbids.
        assert row["video_title"] == "字幕测试视频"
        assert row["part_title"] == "第1集"
    finally:
        connection.close()


def test_list_stored_transcripts_order_is_locked_and_deterministic(tmp_root):
    """The locked order: bvid, page_index, source_kind, language, version DESC.

    The order lives in the query rather than in the caller, so the fixture is
    inserted in an order that differs from the answer's on every key: the second
    page's rows are stored before the first page's, the version-2 row before two
    version-1 rows of other identities, ``ai-zh`` before ``ai-en``, and the
    lexically-earlier ``source_kind`` last.  Reading twice returns the same
    sequence, so the order is a property of the read and not of insertion order
    or row ids.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        pages = _video_with_parts(connection, "BV2ORDER", (7001, 7002))
        earlier = _video_with_parts(connection, "BV1ORDER", (7101,))

        _record(repository, pages[1], run_id=_run(repository, 1))
        _record(repository, pages[1], body=CHANGED_BODY, run_id=_run(repository, 2))
        _record(
            repository,
            pages[1],
            source_kind="subtitle-ai",
            language="ai-zh",
            run_id=_run(repository, 3),
        )
        _record(
            repository,
            pages[1],
            source_kind="subtitle-ai",
            language="ai-en",
            run_id=_run(repository, 4),
        )
        _record(repository, pages[0], run_id=_run(repository, 5))
        _record(repository, earlier[0], run_id=_run(repository, 6))

        rows = repository.list_stored_transcripts()

        assert [
            (
                row["bvid"],
                row["page_index"],
                row["source_kind"],
                row["language"],
                row["version"],
            )
            for row in rows
        ] == [
            ("BV1ORDER", 0, "subtitle-cc", "zh-CN", 1),
            ("BV2ORDER", 0, "subtitle-cc", "zh-CN", 1),
            ("BV2ORDER", 1, "subtitle-ai", "ai-en", 1),
            ("BV2ORDER", 1, "subtitle-ai", "ai-zh", 1),
            ("BV2ORDER", 1, "subtitle-cc", "zh-CN", 2),
            ("BV2ORDER", 1, "subtitle-cc", "zh-CN", 1),
        ]
        assert [tuple(row) for row in repository.list_stored_transcripts()] == [
            tuple(row) for row in rows
        ]
    finally:
        connection.close()


def test_list_stored_transcripts_includes_a_gone_part_that_holds_a_transcript(
    tmp_root,
):
    """A ``gone`` part holding local text is a row: this read has no status filter.

    The discriminator for that sentence is the second gone part in the same
    store: it holds no transcript and yields no row, so membership is produced by
    the stored transcript and not by the part's upstream state.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        gone = _video_with_parts(
            connection, "BV1GONE", (5001,), processing_status="gone"
        )
        _video_with_parts(
            connection, "BV1GONEEMPTY", (5101,), processing_status="gone"
        )
        stored = _record(repository, gone[0], run_id=_run(repository, 1))

        assert [dict(row) for row in repository.list_stored_transcripts()] == [
            _stored_row(
                video_part_id=gone[0],
                bvid="BV1GONE",
                page_index=0,
                cid=5001,
                part_title="第1集",
                pubdate=1_700_000_000,
                transcript_id=stored.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=stored.content_sha256,
            )
        ]
    finally:
        connection.close()


def test_list_stored_transcripts_excludes_a_part_without_a_transcript(tmp_root):
    """A stored part holding no transcript row is out of the relation.

    The producer of a row here is ``record_acquired_transcript``, and this
    fixture reaches it: the control below stores a transcript for the very part
    the first assertion found absent, and the same read then answers it — so the
    absence is the missing transcript row rather than an inert query.  The part
    left captionless in that video stays out, which is what makes the filter per
    part and not per video.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        mixed = _video_with_parts(connection, "BV1MIXED", (6001, 6002))
        held = _captioned_part(connection, "BV1HELD")
        stored = _record(repository, held, run_id=_run(repository, 1))

        # Whole-collection equality: a read that answered any other part — the
        # captionless ones included — fails here.
        assert [dict(row) for row in repository.list_stored_transcripts()] == [
            _stored_row(
                video_part_id=held,
                bvid="BV1HELD",
                page_index=0,
                cid=2001,
                part_title="第一集",
                pubdate=1_700_000_000,
                transcript_id=stored.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=stored.content_sha256,
            )
        ]

        control = _record(repository, mixed[0], run_id=_run(repository, 2))

        assert [dict(row) for row in repository.list_stored_transcripts()] == [
            _stored_row(
                video_part_id=held,
                bvid="BV1HELD",
                page_index=0,
                cid=2001,
                part_title="第一集",
                pubdate=1_700_000_000,
                transcript_id=stored.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=stored.content_sha256,
            ),
            _stored_row(
                video_part_id=mixed[0],
                bvid="BV1MIXED",
                page_index=0,
                cid=6001,
                part_title="第1集",
                pubdate=1_700_000_000,
                transcript_id=control.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=control.content_sha256,
            ),
        ]
    finally:
        connection.close()


def test_list_stored_transcripts_selector_narrows_to_one_part_or_one_video(
    tmp_root,
):
    """``bvid`` narrows to one video, ``bvid`` with ``page_index`` to one part.

    The selector narrows the relation: it invents no row for a part the store
    holds that holds no transcript, and it drops none of a part's stored
    identities.  An unknown video and an unknown page both answer no row: this
    read reports rows, so which selector the caller calls unknown is not decided
    here.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        selected = _video_with_parts(connection, "BV1SEL", (6001, 6002, 6003))
        other = _video_with_parts(connection, "BV1OTHER", (6101,))
        page_zero = _record(repository, selected[0], run_id=_run(repository, 1))
        page_one = _record(repository, selected[1], run_id=_run(repository, 2))
        page_one_ai = _record(
            repository,
            selected[1],
            source_kind="subtitle-ai",
            language="ai-zh",
            run_id=_run(repository, 3),
        )
        elsewhere = _record(repository, other[0], run_id=_run(repository, 4))

        assert [dict(row) for row in repository.list_stored_transcripts("BV1SEL")] == [
            _stored_row(
                video_part_id=selected[0],
                bvid="BV1SEL",
                page_index=0,
                cid=6001,
                part_title="第1集",
                pubdate=1_700_000_000,
                transcript_id=page_zero.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=page_zero.content_sha256,
            ),
            _stored_row(
                video_part_id=selected[1],
                bvid="BV1SEL",
                page_index=1,
                cid=6002,
                part_title="第2集",
                pubdate=1_700_000_000,
                transcript_id=page_one_ai.transcript_id,
                source_kind="subtitle-ai",
                language="ai-zh",
                version=1,
                content_sha256=page_one_ai.content_sha256,
            ),
            _stored_row(
                video_part_id=selected[1],
                bvid="BV1SEL",
                page_index=1,
                cid=6002,
                part_title="第2集",
                pubdate=1_700_000_000,
                transcript_id=page_one.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=page_one.content_sha256,
            ),
        ]

        # The other video's part keeps its own identity under its own selector.
        assert [
            row["bvid"] for row in repository.list_stored_transcripts("BV1OTHER")
        ] == ["BV1OTHER"]
        assert (
            repository.list_stored_transcripts("BV1OTHER")[0]["transcript_id"]
            == elsewhere.transcript_id
        )

        one_part = repository.list_stored_transcripts("BV1SEL", 1)
        assert [
            (
                row["bvid"],
                row["page_index"],
                row["source_kind"],
                row["language"],
                row["version"],
            )
            for row in one_part
        ] == [
            ("BV1SEL", 1, "subtitle-ai", "ai-zh", 1),
            ("BV1SEL", 1, "subtitle-cc", "zh-CN", 1),
        ]
        assert {row["video_part_id"] for row in one_part} == {selected[1]}
        assert [
            row["bvid"] for row in repository.list_stored_transcripts("BV1SEL", 0)
        ] == ["BV1SEL"]

        # A stored part that holds no transcript, an unknown page and an unknown
        # video all answer no row.
        assert repository.list_stored_transcripts("BV1SEL", 2) == []
        assert repository.list_stored_transcripts("BV1SEL", 9) == []
        assert repository.list_stored_transcripts("BV1UNKNOWN") == []
        assert repository.list_stored_transcripts("BV1UNKNOWN", 0) == []
    finally:
        connection.close()


def test_list_stored_transcripts_of_an_empty_store_is_empty(tmp_root):
    """A store holding no transcript answers no row.

    The same read on the same connection answers a row as soon as the store
    holds one, so the empty answer is the store's emptiness and not a query that
    can never return anything.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        assert repository.list_stored_transcripts() == []
        assert repository.list_stored_transcripts("BV1NONE") == []
        assert repository.list_stored_transcripts("BV1NONE", 0) == []

        part = _captioned_part(connection, "BV1NONE")
        stored = _record(repository, part, run_id=_run(repository, 1))

        assert [dict(row) for row in repository.list_stored_transcripts()] == [
            _stored_row(
                video_part_id=part,
                bvid="BV1NONE",
                page_index=0,
                cid=2001,
                part_title="第一集",
                pubdate=1_700_000_000,
                transcript_id=stored.transcript_id,
                source_kind="subtitle-cc",
                language="zh-CN",
                version=1,
                content_sha256=stored.content_sha256,
            )
        ]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"bvid": "   "}, ValueError),
        ({"bvid": 7}, TypeError),
        ({"bvid": "BV1SEL", "page_index": -1}, ValueError),
        ({"bvid": "BV1SEL", "page_index": True}, TypeError),
        ({"bvid": "BV1SEL", "page_index": "1"}, TypeError),
        ({"bvid": "BV1SEL", "page_index": 1.5}, TypeError),
        ({"page_index": -1}, ValueError),
    ],
)
def test_list_stored_transcripts_arguments_follow_the_module_validation_discipline(
    tmp_root, kwargs, error
):
    """The selector's arguments are validated the way the module's reads are.

    ``None`` is the absent selector rather than a rejected type, so the default
    form answers instead of raising; a malformed ``bvid`` or ``page_index``
    raises the module's ``TypeError``/``ValueError`` instead of reaching SQLite.
    """
    connection = open_database(tmp_root)
    repository = TranscriptRepository(connection)
    try:
        with pytest.raises(error):
            repository.list_stored_transcripts(**kwargs)

        assert repository.list_stored_transcripts() == []
        assert repository.list_stored_transcripts(bvid=None, page_index=None) == []
    finally:
        connection.close()
