"""Offline repository contract tests for normalized metadata persistence."""

from __future__ import annotations

from dataclasses import fields
import sqlite3

import pytest

from bili_asr.storage.database import MetadataRepository, open_database
from bili_asr.storage.models import (
    CursorRecord,
    DiscoveryRecord,
    IngestionPageRecord,
    IngestionRunRecord,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
)


MID = 23191782


def _user(*, display_name: str = "未明子", updated_at: int = 100) -> UserRecord:
    return UserRecord(mid=MID, display_name=display_name, created_at=100, updated_at=updated_at)


def _run(run_id: str = "run-1") -> IngestionRunRecord:
    return IngestionRunRecord(
        run_id=run_id,
        mid=MID,
        source_package="bilibili-api-python",
        source_version="17.4.2",
        requested_start_page=1,
        requested_page_limit=3,
        started_at=101,
    )


def _video(
    bvid: str = "BV1SINGLE",
    *,
    title: str = "单集视频",
    aid: int | None = 1001,
    updated_at: int = 102,
) -> VideoRecord:
    return VideoRecord(
        bvid=bvid,
        aid=aid,
        mid=MID,
        title=title,
        pubdate=1_700_000_000,
        created_at=102,
        updated_at=updated_at,
    )


def _part(
    bvid: str = "BV1SINGLE",
    *,
    page_index: int = 0,
    cid: int = 2001,
    title: str = "第一集",
    status: str = "discovered",
    updated_at: int = 103,
) -> VideoPartRecord:
    return VideoPartRecord(
        bvid=bvid,
        page_index=page_index,
        cid=cid,
        title=title,
        duration_ms=1_234,
        processing_status=status,
        created_at=103,
        updated_at=updated_at,
    )


def _page(
    run_id: str = "run-1",
    *,
    page_number: int = 1,
    outcome: str = "ok",
    error_code: str | None = None,
    started_at: int = 110,
    finished_at: int = 111,
) -> IngestionPageRecord:
    return IngestionPageRecord(
        run_id=run_id,
        page_number=page_number,
        outcome=outcome,
        error_code=error_code,
        started_at=started_at,
        finished_at=finished_at,
    )


def _cursor(*, next_page: int = 2, updated_at: int = 112) -> CursorRecord:
    return CursorRecord(
        mid=MID,
        next_page=next_page,
        observed_total=2,
        state="ready",
        last_error_code=None,
        updated_at=updated_at,
    )


def _discovery(
    bvid: str,
    *,
    run_id: str = "run-1",
    page_number: int = 1,
    source_position: int = 0,
    discovered_at: int = 104,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        run_id=run_id,
        page_number=page_number,
        bvid=bvid,
        source_position=source_position,
        discovered_at=discovered_at,
    )


def _start_run(repository: MetadataRepository, run_id: str = "run-1") -> None:
    repository.upsert_user(_user())
    repository.start_run(_run(run_id))


def test_models_validate_scalars_and_compute_work_id_without_persisting_it():
    part = _part()
    assert part.work_id == "BV1SINGLE:p0"
    assert "work_id" not in {field.name for field in fields(VideoPartRecord)}

    with pytest.raises(ValueError):
        _part(page_index=-1)
    with pytest.raises(ValueError):
        _part(cid=0)
    with pytest.raises(ValueError):
        _page(outcome="failed", error_code="raw traceback\n")
    with pytest.raises(ValueError):
        UserRecord(mid=MID, display_name="", created_at=1, updated_at=1)


def test_record_page_persists_single_and_multipart_entities_in_locked_order(tmp_root):
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _start_run(repository)
        multipart = _video("BV1MULTI", title="多集视频", aid=1002)
        page = _page()
        repository.record_page(
            page,
            user=_user(),
            videos=[_video(), multipart],
            parts=[
                _part(),
                _part("BV1MULTI", page_index=0, cid=3001, title="上篇"),
                _part("BV1MULTI", page_index=1, cid=3002, title="下篇"),
            ],
            discoveries=[
                _discovery("BV1SINGLE"),
                _discovery("BV1MULTI", source_position=1),
            ],
            cursor=_cursor(),
        )

        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
        assert repository.read_cursor(MID) == _cursor()

        pending = repository.list_pending_parts()
        assert [row["work_id"] for row in pending] == [
            "BV1MULTI:p0",
            "BV1MULTI:p1",
            "BV1SINGLE:p0",
        ]
        stats = repository.run_stats("run-1")
        assert stats is not None
        assert stats["page_count"] == 1
        assert stats["video_count"] == 2
    finally:
        connection.close()


def test_repeated_page_is_idempotent_but_a_new_run_keeps_page_evidence(tmp_root):
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _start_run(repository)
        repository.record_page(
            _page(),
            user=_user(),
            video=_video(),
            parts=[_part()],
            discoveries=[_discovery("BV1SINGLE")],
            cursor=_cursor(),
        )

        repository.record_page(
            _page(finished_at=120),
            user=_user(display_name="未明子（更新）", updated_at=119),
            video=_video(title="更新后的标题", updated_at=119),
            parts=[_part(title="更新后的分集标题", updated_at=119)],
            discoveries=[_discovery("BV1SINGLE", discovered_at=119)],
            cursor=_cursor(updated_at=120),
        )
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
        assert connection.execute("SELECT title FROM videos").fetchone()[0] == "更新后的标题"
        assert connection.execute("SELECT aid FROM videos").fetchone()[0] == 1001

        _start_run(repository, "run-2")
        repository.record_page(
            _page("run-2"),
            video=_video(title="同一视频的第二次发现"),
            parts=[_part()],
            discoveries=[_discovery("BV1SINGLE", run_id="run-2")],
            cursor=_cursor(updated_at=130),
        )
        assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 2
        assert repository.run_stats("run-1")["video_count"] == 1
        assert repository.run_stats("run-2")["video_count"] == 1
        assert connection.execute("SELECT title FROM videos").fetchone()[0] == "同一视频的第二次发现"
    finally:
        connection.close()


def test_failed_page_rolls_back_payload_preserves_cursor_and_records_bounded_outcome(tmp_root):
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _start_run(repository)
        repository.record_page(
            _page(),
            video=_video(),
            parts=[_part()],
            discoveries=[_discovery("BV1SINGLE")],
            cursor=_cursor(),
        )
        failed_page = _page(
            page_number=2,
            outcome="failed",
            error_code="foreign_key",
            started_at=200,
            finished_at=201,
        )
        with pytest.raises(sqlite3.IntegrityError):
            repository.record_page(
                failed_page,
                user=_user(display_name="must roll back", updated_at=200),
                video=_video(title="must roll back", updated_at=200),
                parts=[_part("BV-MISSING", title="orphan")],
                cursor=_cursor(next_page=3, updated_at=201),
            )

        assert repository.read_cursor(MID) == _cursor()
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert connection.execute("SELECT display_name FROM bilibili_users").fetchone()[0] == "未明子"
        page_row = connection.execute(
            "SELECT outcome, error_code FROM ingestion_pages WHERE run_id = 'run-1' AND page_number = 2"
        ).fetchone()
        assert tuple(page_row) == ("failed", "foreign_key")
        assert tuple(
            connection.execute(
                "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = 'run-1'"
            ).fetchone()
        ) == ("failed", 201)
        assert connection.execute(
            "SELECT COUNT(*) FROM ingestion_pages WHERE error_code LIKE '%traceback%'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_fk_rejection_and_delete_restriction_apply_to_repository_writes(tmp_root):
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            with repository.transaction():
                repository.upsert_video(_video("BV-ORPHAN"))

        with repository.transaction():
            repository.upsert_user(_user())
            repository.upsert_video(_video())
            repository.upsert_part(_part())

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM bilibili_users WHERE mid = ?", (MID,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM videos WHERE bvid = 'BV1SINGLE'")
    finally:
        connection.close()


def test_cursor_resume_and_pending_limit(tmp_root):
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _start_run(repository)
        repository.record_page(
            _page(),
            video=_video(),
            parts=[_part(), _part(page_index=1, cid=2002, title="第二集")],
            discoveries=[_discovery("BV1SINGLE")],
            cursor=_cursor(next_page=2),
        )
        repository.write_cursor(_cursor(next_page=3, updated_at=130))
        assert repository.read_cursor(MID).next_page == 3
        assert [row["page_index"] for row in repository.list_pending_parts(limit=1)] == [0]

        with repository.transaction():
            repository.upsert_part(_part(page_index=1, cid=2002, title="第二集", status="metadata_collected"))
        assert [row["page_index"] for row in repository.list_pending_parts()] == [0]
    finally:
        connection.close()


def test_finish_run_and_all_run_stats_are_derived_from_normalized_rows(tmp_root):
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _start_run(repository)
        repository.record_page(
            _page(),
            video=_video(),
            parts=[_part()],
            discoveries=[_discovery("BV1SINGLE")],
        )
        repository.finish_run("run-1", "complete", 300)
        stats = repository.run_stats()
        assert len(stats) == 1
        assert stats[0]["outcome"] == "complete"
        assert stats[0]["page_count"] == 1
        assert stats[0]["video_count"] == 1
    finally:
        connection.close()


def test_start_run_requires_a_foreign_key_parent(tmp_root):
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            repository.start_run(_run())
    finally:
        connection.close()

