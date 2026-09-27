"""Offline tests for the media queue acquisition write path."""

from __future__ import annotations

import pytest

from bili_asr.storage import MediaQueueRepository, open_database


def _insert_user_video_part(connection, *, bvid: str = "BV1TEST", page_index: int = 0) -> int:
    connection.execute(
        "INSERT INTO bilibili_users(mid, display_name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (23191782, "未明子", 100, 100),
    )
    connection.execute(
        "INSERT INTO videos(bvid, aid, mid, title, pubdate, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (bvid, 1001, 23191782, "视频", 1_700_000_000, 101, 101),
    )
    cursor = connection.execute(
        """
        INSERT INTO video_parts(
            bvid, page_index, cid, title, duration_ms, processing_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bvid, page_index, 2001, "第一段", 1_234, "discovered", 102, 102),
    )
    return int(cursor.lastrowid)


def _insert_video_part_under_video(
    connection, *, bvid: str = "BV1TEST", page_index: int = 1, cid: int = 2002
) -> int:
    """Insert one more part under a video the store already holds."""
    cursor = connection.execute(
        """
        INSERT INTO video_parts(
            bvid, page_index, cid, title, duration_ms, processing_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bvid, page_index, cid, "第二段", 1_234, "discovered", 102, 102),
    )
    return int(cursor.lastrowid)


def _insert_acquisition_run(connection, *, run_id: str, kind: str = "asr") -> None:
    connection.execute(
        "INSERT INTO acquisition_runs("
        "run_id, kind, selector_kind, selector_target, requested_limit, "
        "credential_present, started_at, finished_at, outcome"
        ") VALUES (?, ?, 'pending', NULL, NULL, 0, 100, 300, 'complete')",
        (run_id, kind),
    )


def _insert_attempt(
    connection, *, run_id: str, video_part_id: int, outcome: str, error_code: str | None
) -> None:
    connection.execute(
        "INSERT INTO acquisition_attempts("
        "run_id, video_part_id, outcome, error_code, transcript_id, "
        "started_at, finished_at"
        ") VALUES (?, ?, ?, ?, NULL, 100, 200)",
        (run_id, video_part_id, outcome, error_code),
    )


def _insert_transcript(
    connection, *, video_part_id: int, digest: str = "0" * 64
) -> int:
    cursor = connection.execute(
        "INSERT INTO transcripts("
        "video_part_id, source_kind, language, model_id, version, content_sha256, "
        "created_at"
        ") VALUES (?, 'asr-local', 'zh', NULL, 1, ?, 250)",
        (video_part_id, digest),
    )
    return int(cursor.lastrowid)


def test_mark_audio_acquired_inserts_reuses_and_rejects_unknown_parts(tmp_root):
    connection = open_database(tmp_root)
    try:
        part_id = _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        audio_id = repository.mark_audio_acquired(
            bvid="BV1TEST",
            page_index=0,
            audio_path="audio/BV1TEST-p0.m4a",
            sha256="hash-1",
            byte_size=4_096,
            format="m4a",
            duration_ms=1_234,
            acquisition_source="download",
            acquired_at=500,
        )

        objects = connection.execute(
            "SELECT audio_id, sha256, byte_size, format, duration_ms, storage_key, "
            "created_at FROM audio_objects"
        ).fetchall()
        assert len(objects) == 1
        assert objects[0]["audio_id"] == audio_id
        assert objects[0]["sha256"] == "hash-1"
        assert objects[0]["storage_key"] == "audio/BV1TEST-p0.m4a"
        assert objects[0]["created_at"] == 500

        links = connection.execute(
            "SELECT video_part_id, audio_id, acquired_at, acquisition_source "
            "FROM part_audio_objects"
        ).fetchall()
        assert len(links) == 1
        assert links[0]["video_part_id"] == part_id
        assert links[0]["audio_id"] == audio_id
        assert links[0]["acquired_at"] == 500
        assert links[0]["acquisition_source"] == "download"

        # Same sha256 (different path) reuses the object and the link.
        again = repository.mark_audio_acquired(
            bvid="BV1TEST",
            page_index=0,
            audio_path="audio/BV1TEST-p0-renamed.m4a",
            sha256="hash-1",
            byte_size=4_096,
            format="m4a",
            duration_ms=1_234,
            acquisition_source="cache_hit",
            acquired_at=900,
        )

        assert again == audio_id
        assert (
            connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0] == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0]
            == 1
        )

        with pytest.raises(ValueError):
            repository.mark_audio_acquired(
                bvid="BVUNKNOWN",
                page_index=0,
                audio_path="audio/unknown.m4a",
                sha256="hash-2",
                byte_size=1,
                format="m4a",
                duration_ms=1,
                acquisition_source="download",
                acquired_at=1_000,
            )
    finally:
        connection.close()


def test_mark_transcript_stored_clears_the_queue_and_is_idempotent(tmp_root):
    connection = open_database(tmp_root)
    try:
        captionless_id = _insert_user_video_part(connection)
        audio_only_id = _insert_video_part_under_video(connection)
        repository = MediaQueueRepository(connection)

        _insert_acquisition_run(connection, run_id="run-subtitle", kind="subtitle")
        _insert_acquisition_run(connection, run_id="run-asr")
        _insert_attempt(
            connection,
            run_id="run-subtitle",
            video_part_id=captionless_id,
            outcome="no-subtitle",
            error_code=None,
        )
        # The two parts sit in different queues: the captionless one waits for
        # a subtitle re-attempt and then audio, while the second part has no
        # subtitle attempt at all and waits only for audio -- its arrival in
        # the transcript queue is the audio evidence below.
        assert repository.count_queue_gaps() == {
            "missing_subtitle": 2,
            "missing_audio": 1,
            "missing_transcript": 0,
        }
        repository.mark_audio_acquired(
            bvid="BV1TEST",
            page_index=1,
            audio_path="audio/BV1TEST-p1.m4a",
            sha256="hash-1",
            byte_size=4_096,
            format="m4a",
            duration_ms=1_234,
            acquisition_source="download",
            acquired_at=500,
        )
        # The audio object leaves the second part out of ``missing_audio``,
        # but the captionless part still holds that queue: it has a
        # ``no-subtitle`` attempt and no audio evidence, so it has not left
        # the audio route yet.  Both parts now await a transcript.
        assert repository.count_queue_gaps() == {
            "missing_subtitle": 2,
            "missing_audio": 1,
            "missing_transcript": 1,
        }
        assert {
            (item.bvid, item.page_index)
            for item in repository.list_queue_gaps(gap="missing_audio")
        } == {("BV1TEST", 0)}

        first_transcript = _insert_transcript(
            connection, video_part_id=captionless_id, digest="a" * 64
        )
        second_transcript = _insert_transcript(
            connection, video_part_id=audio_only_id, digest="b" * 64
        )

        repository.mark_transcript_stored(
            bvid="BV1TEST",
            page_index=0,
            transcript_id=first_transcript,
            run_id="run-asr",
            started_at=300,
            finished_at=400,
        )
        repository.mark_transcript_stored(
            bvid="BV1TEST",
            page_index=1,
            transcript_id=second_transcript,
            run_id="run-asr",
            started_at=300,
            finished_at=400,
        )

        # A stored transcript is the evidence: every gap view excludes both
        # parts because the transcript exists, not because a status changed.
        assert repository.count_queue_gaps() == {
            "missing_subtitle": 0,
            "missing_audio": 0,
            "missing_transcript": 0,
        }

        attempts = connection.execute(
            "SELECT run_id, video_part_id, outcome, error_code, transcript_id, "
            "started_at, finished_at FROM acquisition_attempts "
            "WHERE run_id = 'run-asr' ORDER BY video_part_id"
        ).fetchall()
        assert len(attempts) == 2
        assert attempts[0]["video_part_id"] == captionless_id
        assert attempts[0]["outcome"] == "stored"
        assert attempts[0]["error_code"] is None
        assert attempts[0]["transcript_id"] == first_transcript
        assert attempts[0]["started_at"] == 300
        assert attempts[0]["finished_at"] == 400

        # The same call again leaves the attempt row alone.
        repository.mark_transcript_stored(
            bvid="BV1TEST",
            page_index=0,
            transcript_id=first_transcript,
            run_id="run-asr",
            started_at=300,
            finished_at=400,
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM acquisition_attempts WHERE run_id = 'run-asr'"
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM acquisition_attempts "
                "WHERE run_id = 'run-asr' AND video_part_id = ?",
                (captionless_id,),
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_mark_transcript_stored_rejects_bad_parts_transcripts_runs_and_times(tmp_root):
    connection = open_database(tmp_root)
    try:
        part_id = _insert_user_video_part(connection)
        _insert_video_part_under_video(connection)
        _insert_acquisition_run(connection, run_id="run-asr")
        transcript_id = _insert_transcript(connection, video_part_id=part_id)
        repository = MediaQueueRepository(connection)

        # Unknown part pair: resolution fails before any transaction opens.
        with pytest.raises(ValueError):
            repository.mark_transcript_stored(
                bvid="BVUNKNOWN",
                page_index=0,
                transcript_id=transcript_id,
                run_id="run-asr",
                started_at=100,
                finished_at=200,
            )

        # A transcript that belongs to a different part is not this part's
        # evidence.
        with pytest.raises(ValueError):
            repository.mark_transcript_stored(
                bvid="BV1TEST",
                page_index=1,
                transcript_id=transcript_id,
                run_id="run-asr",
                started_at=100,
                finished_at=200,
            )

        # A transcript_id that names no row at all.
        with pytest.raises(ValueError):
            repository.mark_transcript_stored(
                bvid="BV1TEST",
                page_index=0,
                transcript_id=99_999,
                run_id="run-asr",
                started_at=100,
                finished_at=200,
            )

        # The caller supplies an existing run; an unknown one is refused
        # rather than surfacing as a raw foreign-key error.
        with pytest.raises(ValueError):
            repository.mark_transcript_stored(
                bvid="BV1TEST",
                page_index=0,
                transcript_id=transcript_id,
                run_id="run-unknown",
                started_at=100,
                finished_at=200,
            )

        # finished_at must not precede started_at.
        with pytest.raises(ValueError):
            repository.mark_transcript_stored(
                bvid="BV1TEST",
                page_index=0,
                transcript_id=transcript_id,
                run_id="run-asr",
                started_at=400,
                finished_at=300,
            )

        assert (
            connection.execute(
                "SELECT COUNT(*) FROM acquisition_attempts"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
