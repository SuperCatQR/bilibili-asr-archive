"""Offline tests for the media queue acquisition write path."""

from __future__ import annotations

import sqlite3
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_asr.storage import (
    ALLOWED_CAPTION_SOURCE_KINDS,
    AcquisitionRunRecord,
    MediaQueueRepository,
    TranscriptRepository,
    TranscriptSegmentRecord,
    open_database,
)
from bili_asr.services.queue_source import (
    QueueSource,
    mark_audio_acquired,
    mark_transcript_stored,
    record_caption_transcript,
    record_local_transcript,
)


# Two real content hashes: ``sha256`` is validated as a content hash (64
# lowercase hex), so a placeholder cannot drive the reuse/repoint branches.
_SHA_A = "a" * 64
_SHA_B = "b" * 64


def test_audio_writeback_hashes_with_bounded_reads(monkeypatch):
    payload = b"audio" * 500_000
    reads = []
    captured = []

    class BoundedReader(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(
        "bili_asr.services.queue_source.open",
        lambda *args, **kwargs: BoundedReader(payload),
        raising=False,
    )
    source = SimpleNamespace(repository=SimpleNamespace(
        mark_audio_acquired=lambda **kwargs: captured.append(kwargs),
    ))
    mark_audio_acquired(
        source, bvid="BV1TEST", page_index=0,
        audio_path="audio/example.flac", declared_relative="audio/example.flac",
    )
    assert len(reads) >= 3
    assert captured[0]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert captured[0]["byte_size"] == len(payload)
    assert captured[0]["format"] == "flac"


@pytest.mark.parametrize("operation", ["audio", "transcript"])
def test_supplementary_writeback_cannot_fail_completed_stage(tmp_root, operation):
    connection = open_database(tmp_root)
    source = QueueSource(connection)
    connection.close()
    if operation == "audio":
        path = Path(tmp_root) / "completed.m4a"
        path.write_bytes(b"completed audio")
        mark_audio_acquired(
            source, bvid="BV1TEST", page_index=0,
            audio_path=str(path), declared_relative=path.name,
        )
        assert path.read_bytes() == b"completed audio"
    else:
        mark_transcript_stored(
            source, bvid="BV1TEST", page_index=0,
            transcript_id=1, run_id="closed-store",
        )


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
        ") VALUES (?, ?, 'pending', NULL, NULL, ?, 100, 300, 'complete')",
        (run_id, kind, int(kind == "subtitle")),
    )


def _insert_attempt(
    connection, *, run_id: str, video_part_id: int, outcome: str, error_code: str | None,
    credential_verified: bool = False,
) -> None:
    connection.execute(
        "INSERT INTO acquisition_attempts("
        "run_id, video_part_id, outcome, error_code, transcript_id, "
        "started_at, finished_at, credential_verified"
        ") VALUES (?, ?, ?, ?, NULL, 100, 200, ?)",
        (run_id, video_part_id, outcome, error_code, int(credential_verified)),
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


def _acquire(repository, **overrides) -> int:
    """Call ``mark_audio_acquired`` with one valid shape, overridable per field."""
    arguments: dict[str, object] = {
        "bvid": "BV1TEST",
        "page_index": 0,
        "audio_path": "audio/BV1TEST-p0.m4a",
        "sha256": _SHA_A,
        "byte_size": 4_096,
        "format": "m4a",
        "duration_ms": 1_234,
        "acquisition_source": "download",
        "acquired_at": 500,
    }
    arguments.update(overrides)
    return repository.mark_audio_acquired(**arguments)


def _audio_object_rows(connection):
    return connection.execute(
        "SELECT audio_id, sha256, byte_size, format, duration_ms, storage_key, "
        "created_at FROM audio_objects ORDER BY audio_id"
    ).fetchall()


def _part_audio_rows(connection):
    return connection.execute(
        "SELECT video_part_id, audio_id, acquired_at, acquisition_source "
        "FROM part_audio_objects ORDER BY video_part_id, audio_id"
    ).fetchall()


def test_mark_audio_acquired_inserts_reuses_and_rejects_unknown_parts(tmp_root):
    connection = open_database(tmp_root)
    try:
        part_id = _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        audio_id = repository.mark_audio_acquired(
            bvid="BV1TEST",
            page_index=0,
            audio_path="audio/BV1TEST-p0.m4a",
            sha256=_SHA_A,
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
        assert objects[0]["sha256"] == _SHA_A
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
            sha256=_SHA_A,
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
                sha256=_SHA_B,
                byte_size=1,
                format="m4a",
                duration_ms=1,
                acquisition_source="download",
                acquired_at=1_000,
            )
    finally:
        connection.close()


def test_mark_audio_acquired_rekeys_reuse_on_path_not_sha256(tmp_root):
    """Same path + different sha256 must not raise, and reuses the path's row.

    Pre-fix: ``sqlite3.IntegrityError: UNIQUE constraint failed:
    audio_objects.storage_key`` on the second call.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        original = _acquire(repository)
        # A re-download / repaired decode: same archived location, new bytes.
        # Content is ``_SHA_A`` at 4_096 bytes, so only ``sha256`` differs and
        # the remaining columns must keep their first-writer values.
        redownloaded = _acquire(repository, sha256=_SHA_B)

        assert redownloaded == original
        rows = _audio_object_rows(connection)
        assert len(rows) == 1
        object_row = rows[0]
        assert object_row["sha256"] == _SHA_B
        assert object_row["byte_size"] == 4_096
        assert object_row["format"] == "m4a"
        assert object_row["duration_ms"] == 1_234
        assert object_row["storage_key"] == "audio/BV1TEST-p0.m4a"
        assert object_row["created_at"] == 500
        assert len(_part_audio_rows(connection)) == 1
    finally:
        connection.close()


def test_mark_audio_acquired_reuse_refreshes_only_differing_columns(tmp_root):
    """Reuse refreshes the object row in place and keeps ``created_at``.

    Pre-fix: the reuse branch updated nothing, so the corrected ``byte_size`` /
    ``format`` / ``duration_ms`` silently kept their first-writer values and the
    assertions below failed on stale data (no exception was raised).
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        audio_id = _acquire(repository)
        again = _acquire(
            repository,
            byte_size=8_192,
            format="opus",
            duration_ms=9_999,
            acquisition_source="cache_hit",
            acquired_at=900,
        )

        assert again == audio_id
        rows = _audio_object_rows(connection)
        assert len(rows) == 1
        object_row = rows[0]
        assert object_row["audio_id"] == audio_id
        assert object_row["sha256"] == _SHA_A
        assert object_row["byte_size"] == 8_192
        assert object_row["format"] == "opus"
        assert object_row["duration_ms"] == 9_999
        assert object_row["storage_key"] == "audio/BV1TEST-p0.m4a"
        # ``created_at`` is first-writer state and must survive the refresh.
        assert object_row["created_at"] == 500
        # The link is the first writer's, so the second call's source/time do
        # not overwrite it and no second link appears.
        links = _part_audio_rows(connection)
        assert len(links) == 1
        assert links[0]["acquired_at"] == 500
        assert links[0]["acquisition_source"] == "download"
    finally:
        connection.close()


def test_mark_audio_acquired_repoints_a_row_that_holds_the_content(tmp_root):
    """Same content at a new path reuses the row and repoints ``storage_key``.

    Contract §4c option (a).  Pre-fix: the hash lookup reused the row but left
    ``storage_key`` stale, so the path column never moved to the new location.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        audio_id = _acquire(repository)
        moved = _acquire(repository, audio_path="audio/BV1TEST-p0-moved.m4a")

        assert moved == audio_id
        rows = _audio_object_rows(connection)
        assert len(rows) == 1
        assert rows[0]["storage_key"] == "audio/BV1TEST-p0-moved.m4a"
        assert rows[0]["sha256"] == _SHA_A
        assert rows[0]["created_at"] == 500
        assert len(_part_audio_rows(connection)) == 1
    finally:
        connection.close()


def test_mark_audio_acquired_rejects_a_rekey_that_would_merge_two_rows(tmp_root):
    """A path re-recorded with another row's content is refused, not collapsed.

    Two archived locations each own a row; pointing the first at the second's
    content cannot be represented, because ``sha256`` is ``UNIQUE``.  The call
    is refused as a bounded ``ValueError`` naming both paths rather than
    surfacing a raw ``IntegrityError`` or silently rewriting either row.

    Pre-fix: no update ran at all, so this call raised no error and left the
    first row's ``sha256`` stale.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        first = _acquire(repository)
        second = _acquire(
            repository, audio_path="audio/BV1TEST-p0-b.m4a", sha256=_SHA_B
        )
        assert first != second

        with pytest.raises(ValueError) as refusal:
            _acquire(repository, sha256=_SHA_B)

        message = str(refusal.value)
        assert "audio/BV1TEST-p0.m4a" in message
        assert "audio/BV1TEST-p0-b.m4a" in message

        # The refused call wrote nothing: both rows are exactly as they were.
        rows = _audio_object_rows(connection)
        assert [row["storage_key"] for row in rows] == [
            "audio/BV1TEST-p0.m4a",
            "audio/BV1TEST-p0-b.m4a",
        ]
        assert [row["sha256"] for row in rows] == [_SHA_A, _SHA_B]
    finally:
        connection.close()


def test_mark_audio_acquired_rejects_a_bad_page_index(tmp_root):
    """``page_index=True`` must not silently link a different part.

    Pre-fix: SQLite compares ``page_index = 1``, so the call succeeded and
    linked the object to the part at page 1 instead of page 0.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        _insert_video_part_under_video(connection)
        repository = MediaQueueRepository(connection)

        with pytest.raises(TypeError):
            _acquire(repository, page_index=True)
        with pytest.raises(TypeError):
            _acquire(repository, page_index="0")

        # Nothing was written, and in particular the page-1 part gained no link.
        assert _audio_object_rows(connection) == []
        assert _part_audio_rows(connection) == []
    finally:
        connection.close()


def test_mark_audio_acquired_bounds_its_scalars(tmp_root):
    """Malformed scalars are refused as bounded errors, not IntegrityError.

    Pre-fix: ``byte_size=-1`` / ``duration_ms=-5`` surfaced as a ``CHECK
    constraint failed`` and ``format=None`` / ``acquired_at=None`` /
    ``sha256=None`` as a ``NOT NULL constraint failed``, each a raw
    ``sqlite3.IntegrityError`` from inside the transaction.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        with pytest.raises(ValueError):
            _acquire(repository, byte_size=-1)
        with pytest.raises(ValueError):
            _acquire(repository, duration_ms=-5)
        with pytest.raises(ValueError):
            _acquire(repository, acquired_at=-1)
        # ``_text`` / ``_integer`` separate "wrong type" from "out of range",
        # so a missing or non-string scalar is a TypeError the same way the
        # sibling write paths report one.
        with pytest.raises(TypeError):
            _acquire(repository, format=None)
        with pytest.raises(TypeError):
            _acquire(repository, sha256=None)
        with pytest.raises(TypeError):
            _acquire(repository, acquired_at=None)
        with pytest.raises(ValueError):
            _acquire(repository, audio_path="   ")
        with pytest.raises(ValueError):
            _acquire(repository, bvid="")

        assert _audio_object_rows(connection) == []
        assert _part_audio_rows(connection) == []
    finally:
        connection.close()


def test_mark_audio_acquired_validates_sha256_as_a_content_hash(tmp_root):
    """A placeholder cannot drive the clash/repoint branch.

    Contract §4d: ``sha256`` arrives from the acquisition path as a content
    hash, but the write path's clash lookup and repoint branch trust it.  A
    free-text value there could make the call rewrite another object's
    ``storage_key`` — the archive's file pointer — on a non-hash match.

    Pre-fix: ``_text`` accepted ``"hash-1"``, so the first call below succeeded
    and wrote an ``audio_objects`` row whose ``sha256`` was not a content hash.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        repository = MediaQueueRepository(connection)

        for bad in ("hash-1", "A" * 64, "a" * 63, "a" * 65, "g" * 64, " " + "a" * 63):
            with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
                _acquire(repository, sha256=bad)

        assert _audio_object_rows(connection) == []
        assert _part_audio_rows(connection) == []
    finally:
        connection.close()


def test_mark_audio_acquired_rejects_a_part_that_exists_at_another_page(tmp_root):
    """The unknown-pair guard covers a wrong page, not just an absent video.

    Pre-fix result: already correct — this pins the guard's message and the
    fact that no row is written, which the existing test only covered for a
    wholly absent bvid.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection)
        _insert_video_part_under_video(connection)
        repository = MediaQueueRepository(connection)

        with pytest.raises(ValueError, match="unknown video part"):
            _acquire(repository, page_index=7)

        assert _audio_object_rows(connection) == []
        assert _part_audio_rows(connection) == []
    finally:
        connection.close()


def test_mark_transcript_stored_clears_the_queue_and_is_idempotent(tmp_root):
    connection = open_database(tmp_root)
    try:
        captionless_id = _insert_user_video_part(connection)
        audio_only_id = _insert_video_part_under_video(connection)
        repository = MediaQueueRepository(connection)

        _insert_acquisition_run(connection, run_id="run-subtitle", kind="subtitle")
        _insert_acquisition_run(connection, run_id="run-subtitle-2", kind="subtitle")
        _insert_acquisition_run(connection, run_id="run-asr")
        _insert_attempt(
            connection,
            run_id="run-subtitle",
            video_part_id=captionless_id,
            outcome="no-subtitle",
            error_code=None,
            credential_verified=True,
        )
        # A second INDEPENDENT empty observation (distinct run).  Exhaustion is
        # attested: an empty inventory carries no error code, which makes it an
        # indefinite negative, and it admits the part only once two distinct
        # runs have seen it empty -- otherwise a single transiently-invisible
        # inventory would route a captioned part into the paid branch.
        _insert_attempt(
            connection,
            run_id="run-subtitle-2",
            video_part_id=captionless_id,
            outcome="no-subtitle",
            error_code=None,
            credential_verified=True,
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
            sha256=_SHA_A,
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


# ---------------------------------------------------------------------------
# R14: the ASR transcript write-back pins v_missing_transcript convergence
# ---------------------------------------------------------------------------

_SHA_AUDIO = "c" * 64


def _audio_backed_part(connection, *, bvid: str = "BVT", page_index: int = 0,
                       cid: int = 3001) -> int:
    """One audio-backed part in v_missing_transcript (audio evidence, no transcript)."""
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
        (bvid, page_index, cid, "第一段", 1_234, "discovered", 102, 102),
    )
    video_part_id = int(cursor.lastrowid)
    connection.execute(
        "INSERT INTO audio_objects("
        "  audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at"
        ") VALUES (1, ?, 4, 'm4a', 1234, ?, 103)",
        (_SHA_AUDIO, f"audio/{bvid}.p{page_index}.m4a"),
    )
    connection.execute(
        "INSERT INTO part_audio_objects("
        "  video_part_id, audio_id, acquired_at, acquisition_source"
        ") VALUES (?, 1, 104, 'download')",
        (video_part_id,),
    )
    connection.commit()
    return video_part_id


def _running_asr_run(connection, *, run_id: str) -> None:
    connection.execute(
        "INSERT INTO acquisition_runs("
        "  run_id, kind, selector_kind, selector_target, requested_limit, "
        "  credential_present, started_at, finished_at, outcome"
        ") VALUES (?, 'asr', 'pending', NULL, NULL, 0, 100, NULL, 'running')",
        (run_id,),
    )
    connection.commit()


def test_record_local_transcript_converges_v_missing_transcript(tmp_root):
    """The ASR write-back's deliverable: the part LEAVES v_missing_transcript.

    The before/after assertion is the operator-visible effect (plan
    20260929-asr-local-transcript-storage, Task 3 / DoD-2), not a unit
    assertion on the writer: build a part that is genuinely in the view,
    run the write-back through the queue-source helper, and assert the view
    count drops 1 → 0.
    """
    connection = open_database(tmp_root)
    try:
        repository = MediaQueueRepository(connection)
        video_part_id = _audio_backed_part(connection, bvid="BVconv")
        _running_asr_run(connection, run_id="run-asr-conv")

        # Negative control: the fixture must be able to REACH the producer —
        # the part is genuinely queued before the write.
        assert repository.count_queue_gaps()["missing_transcript"] == 1
        assert [
            (i.bvid, i.page_index)
            for i in repository.list_queue_gaps(gap="missing_transcript")
        ] == [("BVconv", 0)]

        record_local_transcript(
            QueueSource(connection),
            run_id="run-asr-conv",
            bvid="BVconv",
            page_index=0,
            language="zh",
            segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="转写"),),
            model_name="Qwen3-ASR-Toolkit-xxx",
            model_revision="abc123",
        )

        # The changed count: 1 → 0.  The part left the transcript queue.
        assert repository.count_queue_gaps()["missing_transcript"] == 0

        # The stored row is a real asr-local transcript on the real part, with
        # model identity resolved through asr_models (not NULL).
        row = connection.execute(
            "SELECT source_kind, language, model_id FROM transcripts "
            "WHERE video_part_id = ?",
            (video_part_id,),
        ).fetchone()
        assert row["source_kind"] == "asr-local"
        assert row["language"] == "zh"
        assert row["model_id"] is not None
        model = connection.execute(
            "SELECT model_name, revision FROM asr_models WHERE model_id = ?",
            (row["model_id"],),
        ).fetchone()
        assert model["model_name"] == "Qwen3-ASR-Toolkit-xxx"
        assert model["revision"] == "abc123"

        # The attempt row is the companion evidence, written for the same run
        # and pointing at the stored transcript (DoD-3).
        attempt = connection.execute(
            "SELECT outcome, transcript_id FROM acquisition_attempts "
            "WHERE run_id = 'run-asr-conv' AND video_part_id = ?",
            (video_part_id,),
        ).fetchone()
        assert attempt["outcome"] == "stored"
        assert attempt["transcript_id"] is not None
    finally:
        connection.close()


def test_record_local_transcript_drops_invalid_coverage_but_keeps_transcript(tmp_root):
    """A bad alignment measurement must not strand a completed ASR transcript."""
    connection = open_database(tmp_root)
    try:
        video_part_id = _audio_backed_part(connection, bvid="BVcoveragefallback")
        _running_asr_run(connection, run_id="run-asr-coverage-fallback")

        record_local_transcript(
            QueueSource(connection),
            run_id="run-asr-coverage-fallback",
            bvid="BVcoveragefallback",
            page_index=0,
            language="zh",
            segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="保留转录"),),
            model_name="Qwen3-ASR",
            model_revision="rev1",
            coverage={
                "decoded_s": 3.0,
                "produced_s": 4.0,
                "coverage": 1.333,
                "coverage_min": 0.9,
                "coverage_short": False,
            },
        )

        assert connection.execute(
            "SELECT COUNT(*) FROM transcripts WHERE video_part_id = ?",
            (video_part_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM acquisition_attempts "
            "WHERE run_id = ? AND video_part_id = ? AND outcome = 'stored'",
            ("run-asr-coverage-fallback", video_part_id),
        ).fetchone()[0] == 1
        assert TranscriptRepository(connection).read_transcript_coverage(
            "run-asr-coverage-fallback", video_part_id
        ) is None
    finally:
        connection.close()


def test_local_transcript_coverage_is_attested_per_run(tmp_root):
    connection = open_database(tmp_root)
    try:
        part_id = _audio_backed_part(connection, bvid="BVcoverage")
        repository = TranscriptRepository(connection)
        segments = (TranscriptSegmentRecord(start_ms=0, end_ms=800, text="same cues"),)
        first = {"decoded_s": 10.0, "produced_s": 8.0, "coverage": 0.8,
                 "coverage_min": 0.9, "coverage_short": True}
        second = {"decoded_s": 8.0, "produced_s": 8.0, "coverage": 1.0,
                  "coverage_min": 0.9, "coverage_short": False}
        for run_id in ("run-cover-1", "run-cover-2"):
            _running_asr_run(connection, run_id=run_id)
        results = []
        for run_id, evidence in (("run-cover-1", first), ("run-cover-2", second)):
            results.append(repository.record_local_transcript(
                run_id=run_id, video_part_id=part_id, language="zh", segments=segments,
                model_name="Qwen3-ASR", model_revision="rev1", started_at=1,
                finished_at=2, created_at=2, coverage=evidence,
            ))
        assert results[0].transcript_id == results[1].transcript_id
        assert repository.read_transcript_coverage("run-cover-1", part_id)["coverage"] == 0.8
        assert repository.read_transcript_coverage("run-cover-1", part_id)["coverage_short"] == 1
        assert repository.read_transcript_coverage("run-cover-2", part_id)["coverage"] == 1.0
        assert repository.read_transcript_coverage("run-cover-2", part_id)["coverage_short"] == 0
    finally:
        connection.close()


def test_record_local_transcript_does_not_weaken_caption_guard(tmp_root):
    """The caption writer still cannot write asr-local (DoD-4).

    Task 1 widened the boundary with a second, explicitly-named entry point;
    the shared caption path must be provably unchanged — a caption writer
    passing source_kind='asr-local' is refused exactly as before, and the
    caption accepted set is byte-for-byte the original two kinds.
    """
    connection = open_database(tmp_root)
    try:
        part_id = _audio_backed_part(connection, bvid="BVguard")
        transcripts = TranscriptRepository(connection)
        _running_asr_run(connection, run_id="run-asr-guard")

        segments = (TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="字幕"),)
        # The caption entry point refuses asr-local: the caption guard holds.
        with pytest.raises(ValueError):
            transcripts.record_acquired_transcript(
                run_id="run-asr-guard",
                video_part_id=part_id,
                source_kind="asr-local",
                language="zh",
                segments=segments,
                started_at=110,
                finished_at=111,
                created_at=112,
            )
        assert (
            connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
        )

        # The caption accepted set is exactly the two caption kinds, untouched.
        assert ALLOWED_CAPTION_SOURCE_KINDS == frozenset(
            {"subtitle-ai", "subtitle-cc"}
        )
    finally:
        connection.close()


def test_record_local_transcript_is_best_effort_on_store_failure(tmp_root):
    """A store write failure does not raise out of the helper (DoD-5).

    The archive already succeeded on disk before the write-back runs; the
    helper swallows the store failure so the operator keeps the archive.  A
    part the store does not hold is answered by skipping, not by raising.
    """
    connection = open_database(tmp_root)
    try:
        _running_asr_run(connection, run_id="run-asr-be")
        # No video part for BVmissing: the resolution finds nothing and the
        # helper returns without raising and without writing.
        record_local_transcript(
            QueueSource(connection),
            run_id="run-asr-be",
            bvid="BVmissing",
            page_index=0,
            language="zh",
            segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="x"),),
            model_name="m",
            model_revision=None,
        )
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0

        # A store-side refusal (an empty segment tuple the repository rejects)
        # is swallowed by the helper — the archive on disk is kept.
        _audio_backed_part(connection, bvid="BVbe")
        record_local_transcript(
            QueueSource(connection),
            run_id="run-asr-be",
            bvid="BVbe",
            page_index=0,
            language="zh",
            segments=(),
            model_name="m",
            model_revision=None,
        )
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# R14 (plan r14-routes-writeback): the subtitle-arm + run-batch routes converge
# v_missing_transcript through the same best-effort write-back seam.
# ---------------------------------------------------------------------------


def test_record_caption_transcript_converges_every_gap_view(tmp_root):
    """A subtitle-sourced transcript leaves every gap view, through the caption writer.

    The subtitle-arm write-back's deliverable: a part whose transcript came
    from a harvested caption owes a ``transcripts`` row with
    source_kind ``'subtitle-ai'``/``'subtitle-cc'`` — written through the
    CAPTION writer (``TranscriptRepository.record_acquired_transcript``), never
    the ``'asr-local'`` singleton — so the part leaves ``v_missing_subtitle`` /
    ``v_missing_audio`` / ``v_missing_transcript`` together.  The part here has
    no audio evidence, so it starts in the subtitle gap; the caption row alone
    must clear it.
    """
    connection = open_database(tmp_root)
    try:
        repository = MediaQueueRepository(connection)
        video_part_id = _insert_user_video_part(connection, bvid="BVcap")
        _insert_acquisition_run(connection, run_id="run-cap", kind="subtitle")

        # Negative control: the captionless part is genuinely queued first.
        assert repository.count_queue_gaps() == {
            "missing_subtitle": 1,
            "missing_audio": 0,
            "missing_transcript": 0,
        }

        record_caption_transcript(
            QueueSource(connection),
            run_id="run-cap",
            bvid="BVcap",
            page_index=0,
            source_kind="subtitle-ai",
            language="ai-zh",
            segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="字幕"),),
        )

        # The caption row cleared every gap view, not just the transcript one.
        assert repository.count_queue_gaps() == {
            "missing_subtitle": 0,
            "missing_audio": 0,
            "missing_transcript": 0,
        }

        # The stored row is a real caption transcript on the real part.
        row = connection.execute(
            "SELECT source_kind, language, model_id FROM transcripts "
            "WHERE video_part_id = ?",
            (video_part_id,),
        ).fetchone()
        assert row["source_kind"] == "subtitle-ai"
        assert row["language"] == "ai-zh"
        assert row["model_id"] is None  # a caption carries no ASR model identity

        # The attempt row is the companion evidence, keyed to the caption run.
        attempt = connection.execute(
            "SELECT outcome, transcript_id FROM acquisition_attempts "
            "WHERE run_id = 'run-cap' AND video_part_id = ?",
            (video_part_id,),
        ).fetchone()
        assert attempt["outcome"] == "stored"
        assert attempt["transcript_id"] is not None
    finally:
        connection.close()


def test_record_caption_transcript_is_best_effort_and_keeps_caption_guard(tmp_root):
    """Store failures are swallowed, and the caption accepted set is unchanged.

    The write-back is best-effort exactly like the ASR sibling: a part the
    store does not hold is skipped, and a body the caption writer refuses (an
    empty segment tuple) is swallowed — the archive on disk stands.  The
    caption writer's accepted-kind set stays exactly the two caption kinds:
    this entry point cannot widen it, and an asr-local caption is still refused
    here exactly as through every other caption caller.
    """
    connection = open_database(tmp_root)
    try:
        _insert_acquisition_run(connection, run_id="run-capbe", kind="subtitle")

        # Unknown part: resolution finds nothing, no write, no raise.
        record_caption_transcript(
            QueueSource(connection),
            run_id="run-capbe",
            bvid="BVmissing",
            page_index=0,
            source_kind="subtitle-cc",
            language="zh-CN",
            segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="x"),),
        )
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0

        # A caption body the caption writer refuses (empty segments) is swallowed.
        _insert_user_video_part(connection, bvid="BVcapbe")
        record_caption_transcript(
            QueueSource(connection),
            run_id="run-capbe",
            bvid="BVcapbe",
            page_index=0,
            source_kind="subtitle-cc",
            language="zh-CN",
            segments=(),
        )
        assert connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0

        # The caption writer still refuses asr-local through this entry point:
        # the accepted set is unchanged.
        part_id = _insert_video_part_under_video(connection, bvid="BVcapbe")
        transcripts = TranscriptRepository(connection)
        with pytest.raises(ValueError):
            transcripts.record_acquired_transcript(
                run_id="run-capbe",
                video_part_id=part_id,
                source_kind="asr-local",
                language="zh",
                segments=(TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="字幕"),),
                started_at=110,
                finished_at=111,
                created_at=112,
            )
        assert (
            connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
        )
        assert ALLOWED_CAPTION_SOURCE_KINDS == frozenset(
            {"subtitle-ai", "subtitle-cc"}
        )
    finally:
        connection.close()


def test_queue_source_ensure_asr_run_creates_one_run_per_source(tmp_root):
    """The lazy run-scope helper is idempotent per source and best-effort.

    Every transcript write-back keys to one ``kind='asr'`` run per invocation;
    ``ensure_asr_run`` opens it lazily (only when a row actually records a
    transcript) and reuses the one id across calls, so a batch records exactly
    one run no matter how many parts it archives.  A store that refuses the
    run leaves the id ``None`` so every write-back skips.
    """
    connection = open_database(tmp_root)
    try:
        source = QueueSource(connection)

        # Lazily created on first use, not before.
        assert source.asr_run_id is None
        first = source.ensure_asr_run("run")
        assert first is not None
        assert source.asr_run_id == first

        # Idempotent per source: the same id comes back, no second run row.
        assert source.ensure_asr_run("run") == first
        assert source.ensure_asr_run("run") == first
        runs = connection.execute(
            "SELECT run_id, kind, outcome FROM acquisition_runs WHERE run_id = ?",
            (first,),
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["kind"] == "asr"
        assert runs[0]["outcome"] == "running"
    finally:
        connection.close()


def test_queue_source_ensure_asr_run_is_best_effort_on_store_failure(tmp_root, monkeypatch):
    """A store that refuses the run leaves the id ``None`` (write-backs skip)."""
    connection = open_database(tmp_root)
    try:
        from bili_asr.storage import TranscriptRepository

        source = QueueSource(connection)

        def refuse(*args, **kwargs):
            raise sqlite3.Error("store refused")

        monkeypatch.setattr(TranscriptRepository, "start_acquisition_run", refuse)
        assert source.ensure_asr_run("run") is None
        assert source.asr_run_id is None
        # A refused run stays refused: the id stays None and no run row exists.
        assert source.ensure_asr_run("run") is None
        assert (
            connection.execute("SELECT COUNT(*) FROM acquisition_runs").fetchone()[0]
            == 0
        )
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# asr-run-id-uniqueness (plan asr-run-id-uniqueness): the run id must not
# collide inside one wall-clock second, and a genuine store refusal must be
# visible — once per source instance — instead of silently disabling the scope.
# ---------------------------------------------------------------------------


def test_queue_source_ensure_asr_run_two_same_second_sources_both_write_back(
    tmp_root, monkeypatch
):
    """Two same-command runs inside one second each get a usable run id.

    The defect class: ``ensure_asr_run`` minted ``f"{command}-{int(time())}"``
    against ``acquisition_runs.run_id`` — a ``TEXT PRIMARY KEY`` — so a second
    run inside the same wall-clock second collided, the store's
    ``IntegrityError`` was swallowed by a blanket ``except``, the id stayed
    ``None`` and every transcript write-back of that scope was skipped while
    stdout still reported each row as archived.  A batch boundary re-opens the
    source (``RunCoordinator._close_writeback_source``), so the collision is
    reachable in-process: two connections over one store are that shape.

    The clock is injected rather than slept on: the whole test runs inside one
    frozen wall-clock second while the nanosecond clock advances one
    nanosecond per read, so the pre-fix id (the whole second) collides
    deterministically and the assertion is that the two ids differ — never
    that they differ *because* of timing.  The end-to-end half is deliberate:
    an id being non-``None`` is not the observable the operator cares about,
    the ``transcripts`` row each run id writes is.
    """
    import itertools
    import time as time_module

    connection_a = open_database(tmp_root)
    connection_b = open_database(tmp_root)
    try:
        first_part_id = _audio_backed_part(connection_a, bvid="BVcollide", page_index=0)
        second_part_id = _insert_video_part_under_video(
            connection_a, bvid="BVcollide", page_index=1, cid=3002
        )
        connection_a.commit()

        nanoseconds = itertools.count(1_700_000_000_000_000_000)
        monkeypatch.setattr(time_module, "time", lambda: 1_700_000_000.0)
        monkeypatch.setattr(time_module, "time_ns", lambda: next(nanoseconds))

        source_a = QueueSource(connection_a)
        source_b = QueueSource(connection_b)

        first = source_a.ensure_asr_run("asr")
        second = source_b.ensure_asr_run("asr")

        # The collision: pre-fix both calls mint the same key, the second
        # insert is refused and ``second`` comes back ``None``.
        assert first is not None
        assert second is not None
        assert first != second

        rows = connection_a.execute(
            "SELECT run_id FROM acquisition_runs"
        ).fetchall()
        assert sorted(str(row["run_id"]) for row in rows) == sorted([first, second])

        segments = (TranscriptSegmentRecord(start_ms=0, end_ms=1_000, text="转写"),)
        record_local_transcript(
            source_a,
            run_id=first,
            bvid="BVcollide",
            page_index=0,
            language="zh",
            segments=segments,
            model_name="m",
            model_revision=None,
        )
        record_local_transcript(
            source_b,
            run_id=second,
            bvid="BVcollide",
            page_index=1,
            language="zh",
            segments=segments,
            model_name="m",
            model_revision=None,
        )

        # Each run id landed its own transcript row: the write-backs the
        # collision would have silently disabled are recorded in the store.
        stored = connection_a.execute(
            "SELECT video_part_id, source_kind FROM transcripts"
        ).fetchall()
        assert {int(row["video_part_id"]) for row in stored} == {
            first_part_id,
            second_part_id,
        }
        assert {str(row["source_kind"]) for row in stored} == {"asr-local"}
        attempts = connection_a.execute(
            "SELECT run_id, outcome FROM acquisition_attempts"
        ).fetchall()
        assert {(str(row["run_id"]), str(row["outcome"])) for row in attempts} == {
            (first, "stored"),
            (second, "stored"),
        }
    finally:
        connection_a.close()
        connection_b.close()


def test_queue_source_ensure_asr_run_reports_refusal_once_per_instance(
    tmp_root, monkeypatch, capsys
):
    """A refused run is stated once per source instance, on stderr only.

    D8 (product-manager ruling): the refusal happens before any row is
    recorded and skips the whole scope, so the diagnostic names the command,
    the refusing exception class and the skipped transcript write-backs — once
    per ``QueueSource`` instance, because a persistently failing store retries
    on every call and a per-call line would degrade into per-row noise.  stdout
    stays empty: it still reports each row as archived, and the refusal must
    not read as a clean success.
    """
    connection = open_database(tmp_root)
    try:
        from bili_asr.storage import TranscriptRepository

        def refuse(*args, **kwargs):
            raise sqlite3.IntegrityError("run_id already used")

        monkeypatch.setattr(TranscriptRepository, "start_acquisition_run", refuse)

        source = QueueSource(connection)
        assert source.ensure_asr_run("asr") is None
        captured = capsys.readouterr()
        lines = captured.err.splitlines()
        assert len(lines) == 1, captured.err
        assert "asr" in lines[0]
        assert "IntegrityError" in lines[0]
        assert "write-back" in lines[0]
        assert "skipped" in lines[0]
        assert captured.out == ""

        # Latched per instance: the retry is refused again, and stays silent.
        assert source.ensure_asr_run("asr") is None
        assert capsys.readouterr().err == ""

        # A new instance is a new scope and earns its own single line.
        other = QueueSource(connection)
        assert other.ensure_asr_run("asr") is None
        assert len(capsys.readouterr().err.splitlines()) == 1
    finally:
        connection.close()


def test_queue_source_ensure_asr_run_refusal_is_silent_with_stderr_closed(
    tmp_root, monkeypatch, capsys
):
    """With fd 2 closed the refusal returns ``None`` without printing or raising.

    CPython sets ``sys.stderr`` to ``None`` when fd 2 is closed, and
    ``print(..., file=None)`` falls back to stdout — where the diagnostic would
    land inside the caller's own output (the ``archived`` lines, or
    ``campaign``'s single JSON document).  A stream that is gone means the
    diagnostic has nowhere to go: the rule
    ``coordinator._print_model_constructions`` already follows.
    """
    import sys

    connection = open_database(tmp_root)
    try:
        from bili_asr.storage import TranscriptRepository

        def refuse(*args, **kwargs):
            raise sqlite3.Error("store refused")

        monkeypatch.setattr(TranscriptRepository, "start_acquisition_run", refuse)
        monkeypatch.setattr(sys, "stderr", None)

        source = QueueSource(connection)
        assert source.ensure_asr_run("asr") is None
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
    finally:
        connection.close()


def test_queue_source_ensure_asr_run_refusal_survives_a_dead_stderr_stream(
    tmp_root, monkeypatch, capsys
):
    """A stream that dies after startup cannot raise out of the refusal report.

    The ``sys.stderr is None`` guard only covers fd 2 closed *before* the
    interpreter starts.  When fd 2 dies later (``os.close(2)``, a broken pipe),
    ``sys.stderr`` is still a live ``TextIOWrapper`` whose writes fail with
    ``OSError``; an unguarded ``print`` would then raise that out of
    ``ensure_asr_run``, whose documented contract is to return ``None`` when
    the store refuses the run.  A present stream that is unusable in another
    way fails with a class that is not an ``OSError`` at all — a closed
    wrapper or one whose buffer was detached raises ``ValueError``, and a
    byte-oriented stream raises ``TypeError`` — so the guard must name those
    classes too.

    The stubs are built without closing fd 2 of the test session, which
    pytest's capture replaces anyway (and the house pattern of the test above
    stubs ``sys.stderr`` rather than closing the real fd).  A read-only fd
    fails every write with ``EBADF`` and can never be reused, so that write
    really is attempted and really fails; the closed/detached wrappers and the
    binary stream fail deterministically for the same reason.  Each stream's
    failures are counted: the latch must keep the line from being retried on a
    later refusal.
    """
    import contextlib
    import io
    import os
    import sys

    class DeadStderr(io.TextIOWrapper):
        """A stderr-shaped stream whose fd or wrapper state refuses writes."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.writes = 0

        def write(self, text):
            self.writes += 1
            return super().write(text)

    class DeadBinary(io.BufferedWriter):
        """A byte-oriented stream: ``print`` hands it ``str``, it wants bytes."""

        def __init__(self, raw):
            super().__init__(raw)
            self.writes = 0

        def write(self, data):
            self.writes += 1
            return super().write(data)

    def _wrapper():
        return DeadStderr(
            open(os.devnull, "wb"),
            encoding="utf-8",
            write_through=True,
            line_buffering=True,
        )

    # A present-but-unusable stream is wider than the ``OSError`` of a dead fd:
    # a wrapper that is closed (``ValueError: I/O operation on closed file.``)
    # or whose buffer was detached (``ValueError: underlying buffer has been
    # detached``), and a byte-oriented stream (``TypeError``).  None of those
    # classes is an ``OSError``, and each shape gets its own instance below,
    # because the latch is per instance.
    closed = _wrapper()
    closed.close()
    detached = _wrapper()
    detached_buffer = detached.detach()
    binary = DeadBinary(open(os.devnull, "wb", buffering=0))

    connection = open_database(tmp_root)
    dead = DeadStderr(
        os.fdopen(os.open(os.devnull, os.O_RDONLY), "wb", buffering=0),
        encoding="utf-8",
        write_through=True,
        line_buffering=True,
    )
    try:
        from bili_asr.storage import TranscriptRepository

        def refuse(*args, **kwargs):
            raise sqlite3.Error("store refused")

        monkeypatch.setattr(TranscriptRepository, "start_acquisition_run", refuse)

        # Every present-but-unusable shape is exercised on its own instance,
        # because the latch is per instance: a dead fd (``OSError``), a closed
        # wrapper and a detached wrapper (both ``ValueError``), and a
        # byte-oriented stream (``TypeError``).  None of the latter three is an
        # ``OSError``, so a guard naming only ``OSError`` lets them escape.
        for label, stream in (
            ("dead fd", dead),
            ("closed wrapper", closed),
            ("detached wrapper", detached),
            ("binary stream", binary),
        ):
            monkeypatch.setattr(sys, "stderr", stream)
            source = QueueSource(connection)
            assert source.ensure_asr_run("asr") is None, label

            # Text wrappers bypass their buffer so a failed write cannot be
            # retried at interpreter shutdown. Custom binary writers get one
            # guarded call. Neither path redirects diagnostics to stdout.
            expected_writes = int(label == "binary stream")
            assert stream.writes == expected_writes, label

            # An unusable stream is not a transient condition: the latch
            # stays set and the line is not retried on the next refusal.
            assert source.ensure_asr_run("asr") is None, label
            assert stream.writes == expected_writes, label
            assert source._asr_run_refusal_reported is True, label

        # stderr only: the failed writes must not fall back to stdout.
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
    finally:
        # Restore the session's stderr before pytest's capture unwinds (the
        # fixture would do this later, but the dead stream must not stay
        # installed if an assertion above raised).
        monkeypatch.undo()
        # A detached wrapper cannot be closed again (``ValueError``); its
        # buffer is released explicitly instead.
        with contextlib.suppress(ValueError):
            detached.close()
        detached_buffer.close()
        for stream in (dead, closed, binary):
            stream.close()
