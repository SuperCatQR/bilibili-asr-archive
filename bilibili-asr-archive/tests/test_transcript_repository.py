"""Offline repository contract tests for transcript and acquisition writes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3

import pytest

from bili_asr.storage import (
    MAX_TIMELINE_MS,
    AcquisitionRunRecord,
    MetadataRepository,
    TranscriptRepository,
    TranscriptSegmentRecord,
    TranscriptWriteResult,
    open_database,
)
from fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)


BODY = ((0, 1_200, "第一句"), (1_200, 2_400, "第二句"))
CHANGED_BODY = ((0, 1_200, "第一句"), (1_200, 2_400, "改写后的第二句"))


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


def _caption_run(
    run_id: str = "caption-run-1",
    *,
    selector_kind: str = "pending",
    selector_target: str | None = None,
    requested_limit: int | None = None,
    credential_present: bool = False,
    started_at: int = 101,
    outcome: str = "running",
    finished_at: int | None = None,
) -> AcquisitionRunRecord:
    """Build one acquisition run record for the caption path."""
    return AcquisitionRunRecord(
        run_id=run_id,
        kind="subtitle",
        selector_kind=selector_kind,
        selector_target=selector_target,
        requested_limit=requested_limit,
        credential_present=credential_present,
        started_at=started_at,
        outcome=outcome,
        finished_at=finished_at,
    )


def _run(repository: TranscriptRepository, index: int, **overrides) -> str:
    """Start one numbered acquisition run and return its id."""
    run_id = f"caption-run-{index}"
    fields: dict[str, object] = {"started_at": 100 + index}
    fields.update(overrides)
    repository.start_acquisition_run(_caption_run(run_id, **fields))
    return run_id


def _segments(body=BODY) -> tuple[TranscriptSegmentRecord, ...]:
    """Build the segment tuple for one caption body of ``(start, end, text)``."""
    return tuple(TranscriptSegmentRecord(*triple) for triple in body)


def _write_kwargs(video_part_id: int, *, body=BODY, **overrides) -> dict:
    """Build one valid ``record_acquired_transcript`` argument set."""
    kwargs: dict[str, object] = {
        "run_id": "caption-run-1",
        "video_part_id": video_part_id,
        "source_kind": "subtitle-cc",
        "language": "zh-CN",
        "segments": _segments(body),
        "started_at": 200,
        "finished_at": 300,
        "created_at": 400,
    }
    kwargs.update(overrides)
    return kwargs


def _record(
    repository: TranscriptRepository, video_part_id: int, **overrides
) -> TranscriptWriteResult:
    """Record one caption body and return what the write did."""
    return repository.record_acquired_transcript(
        **_write_kwargs(video_part_id, **overrides)
    )


def _expected_content_sha256(body) -> str:
    """Compute the contract's content hash independently of the repository."""
    canonical = json.dumps(
        [[start_ms, end_ms, text] for start_ms, end_ms, text in body],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
