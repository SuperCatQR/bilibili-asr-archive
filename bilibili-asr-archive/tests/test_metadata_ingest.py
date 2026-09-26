"""Offline ingestor contract tests: resumable normalized metadata collection.

Every test runs :class:`MetadataIngestor` against the shared fake
``BilibiliGateway`` protocol double from ``tests/fixtures/fake_bilibili_gateway.py``
(scripted pages, parts, and completions; no ``bilibili_api`` import, no
network) and a real Plan-1 repository over a temporary SQLite database, so
each test observes the normalized rows a collection run leaves behind.
Unexpected gateway fetches fail loudly instead of returning script-free
data.  The package-seam tests at the end drive the real product adapter
(:class:`~bili_asr.sources.bilibili_api_gateway.BilibiliApiGateway`) over
the same module's fake ``bilibili_api`` package seam, still fully offline.
"""

from __future__ import annotations

import importlib

import pytest

from bili_asr.services.metadata_ingest import (
    PAGE_SIZE,
    SOURCE_PACKAGE,
    IngestionRunResult,
    MetadataIngestor,
)
from bili_asr.sources.models import (
    GatewayRateLimited,
    GatewayTransportError,
    UserVideoPage,
    VideoPart,
    VideoSummary,
)
from bili_asr.storage.database import MetadataRepository, open_database
from fixtures.fake_bilibili_gateway import (
    NO_LEAK_MARKERS,
    RAW_JSON_BODY_MARKER,
    RAW_UPSTREAM_EXCEPTION_MARKER,
    SESSDATA_BOUNDARY_VALUE,
    SIGNED_URL_MARKER,
    UPSTREAM_ERROR_TEXT,
    FakeResponseCodeException,
    FakeGateway,
    assert_leaks_no_markers,
    assert_only_documented_metadata_calls,
    bilibili_api_seam,
    make_detail_response,
    make_part_item,
    make_videos_response,
    make_vlist_item,
    persisted_row_text,
)

MID = 23191782
PACKAGE_VERSION = "17.4.2"
PUBDATE = 1_725_859_200


def _page(
    page_number: int,
    *summaries: VideoSummary,
    observed_total: int | None = None,
) -> UserVideoPage:
    """Build one validated page DTO owned by the requested user."""

    return UserVideoPage(
        mid=MID, page_number=page_number, videos=summaries, observed_total=observed_total
    )


def _summary(
    bvid: str,
    *,
    aid: int | None = 1001,
    title: str = "未明子讲座",
    owner_mid: int | None = None,
    author: str | None = "未明子",
) -> VideoSummary:
    """Build one validated summary DTO owned by the requested user.

    ``author`` defaults to the uploader name the fixture pages carry, so a run
    built from these summaries observes one and records it.  Passing ``None``
    is how a case exercises the ingestor's owner-mid fallback — the arm the
    field's absence is for — and the cross-run cases below are where that
    matters: they are the only callers that pass it.
    """

    return VideoSummary(
        bvid=bvid,
        aid=aid,
        title=title,
        pubdate=PUBDATE,
        mid=MID if owner_mid is None else owner_mid,
        author=author,
    )


def _part(
    bvid: str,
    page_index: int,
    *,
    cid: int = 2222,
    title: str = "第一部分",
    duration_ms: int = 12_000,
) -> VideoPart:
    """Build one normalized part DTO."""

    return VideoPart(
        bvid=bvid,
        page_index=page_index,
        cid=cid,
        title=title,
        duration_ms=duration_ms,
    )


def _ingestor(gateway: FakeGateway, repository: MetadataRepository) -> MetadataIngestor:
    return MetadataIngestor(gateway, repository)


def test_single_part_run_completes_with_normalized_rows(tmp_root):
    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1SINGLE", aid=1001), observed_total=1)
    )
    gateway.script_parts("BV1SINGLE", (_part("BV1SINGLE", 0),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)

        assert isinstance(result, IngestionRunResult)
        assert result.outcome == "complete"
        assert result.error_code is None
        assert (result.page_count, result.video_count, result.part_count) == (2, 1, 1)

        # The cursor advanced exactly once, into completion state, and
        # observed_total came from the page response.
        assert result.next_cursor is not None
        assert (result.next_cursor.next_page, result.next_cursor.state) == (2, "complete")
        assert result.next_cursor.observed_total == 1
        assert result.next_cursor.last_error_code is None

        run_row = connection.execute(
            "SELECT mid, source_package, source_version, requested_start_page,"
            " requested_page_limit, started_at, finished_at, outcome"
            " FROM ingestion_runs WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
        assert run_row is not None
        assert tuple(run_row)[:5] == (MID, SOURCE_PACKAGE, PACKAGE_VERSION, 1, None)
        assert run_row["finished_at"] >= run_row["started_at"]
        assert run_row["outcome"] == "complete"

        page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ? ORDER BY page_number",
            (result.run_id,),
        ).fetchall()
        assert [tuple(row) for row in page_rows] == [(1, "ok", None), (2, "empty", None)]

        user_row = connection.execute(
            "SELECT mid, display_name FROM bilibili_users"
        ).fetchone()
        # The observed uploader name, not the owner-mid placeholder: the run
        # read ``author`` off the page it collected.
        assert tuple(user_row) == (MID, "未明子")
        video_row = connection.execute("SELECT bvid, aid, mid, title FROM videos").fetchone()
        assert tuple(video_row) == ("BV1SINGLE", 1001, MID, "未明子讲座")
        part_row = connection.execute(
            "SELECT bvid, page_index, cid, title, duration_ms, processing_status FROM video_parts"
        ).fetchone()
        assert tuple(part_row) == ("BV1SINGLE", 0, 2222, "第一部分", 12_000, "discovered")
        discovery_row = connection.execute(
            "SELECT run_id, page_number, bvid, source_position FROM ingestion_discoveries"
        ).fetchone()
        assert tuple(discovery_row) == (result.run_id, 1, "BV1SINGLE", 0)
        assert [row["work_id"] for row in repository.list_pending_parts()] == ["BV1SINGLE:p0"]

        # Exactly one bounded page fetch per requested page, no detail calls.
        assert gateway.page_calls == [(MID, 1, PAGE_SIZE), (MID, 2, PAGE_SIZE)]
        assert gateway.parts_calls == ["BV1SINGLE"]
        assert gateway.completion_calls == []
    finally:
        connection.close()


def test_multipart_video_persists_zero_based_parts_in_milliseconds(tmp_root):
    gateway = FakeGateway()
    gateway.script_page(
        1,
        _page(1, _summary("BV1MULTI", aid=1002, title="多集视频"), observed_total=1),
    )
    gateway.script_parts(
        "BV1MULTI",
        (
            _part("BV1MULTI", 0, cid=3001, title="上篇", duration_ms=12_000),
            _part("BV1MULTI", 1, cid=3002, title="下篇", duration_ms=10_500),
        ),
    )
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID)

        part_rows = connection.execute(
            "SELECT bvid, page_index, cid, title, duration_ms, processing_status"
            " FROM video_parts ORDER BY page_index"
        ).fetchall()
        assert [tuple(row) for row in part_rows] == [
            ("BV1MULTI", 0, 3001, "上篇", 12_000, "discovered"),
            ("BV1MULTI", 1, 3002, "下篇", 10_500, "discovered"),
        ]
        assert (result.page_count, result.video_count, result.part_count) == (2, 1, 2)
        assert result.outcome == "complete"
        assert [row["work_id"] for row in repository.list_pending_parts()] == [
            "BV1MULTI:p0",
            "BV1MULTI:p1",
        ]
    finally:
        connection.close()


def test_duplicate_summaries_in_one_page_collapse_into_single_rows(tmp_root):
    gateway = FakeGateway()
    gateway.script_page(
        1,
        _page(
            1,
            _summary("BV1DUP", aid=333, title="重复条目"),
            _summary("BV1DUP", aid=333, title="重复条目"),
            observed_total=1,
        ),
    )
    gateway.script_parts("BV1DUP", (_part("BV1DUP", 0, cid=4444),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID)

        assert result.video_count == 1
        assert result.part_count == 1
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT title FROM videos").fetchone()[0] == "重复条目"
        # The duplicated video is a single distinct target: one parts fetch.
        assert gateway.parts_calls == ["BV1DUP"]
    finally:
        connection.close()


def test_within_page_duplicate_discovery_keeps_the_last_source_position(tmp_root):
    """A bvid duplicated within one page keeps the last occurrence's position.

    The discovery row's primary key is ``(run_id, page_number, bvid)``, so a
    repeated summary upserts the same row and overwrites ``source_position``
    with the later occurrence.  This pins the kept flavor: last wins.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1,
        _page(
            1,
            _summary("BV1DUPPOS", aid=441, title="重复条目"),
            _summary("BV1INTERVAL", aid=442, title="间隔条目"),
            _summary("BV1DUPPOS", aid=441, title="重复条目"),
            observed_total=2,
        ),
    )
    gateway.script_parts("BV1DUPPOS", (_part("BV1DUPPOS", 0, cid=4441),))
    gateway.script_parts("BV1INTERVAL", (_part("BV1INTERVAL", 0, cid=4442),))
    gateway.script_page(2, _page(2, observed_total=2))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID)

        assert result.video_count == 2
        positions = dict(
            connection.execute(
                "SELECT bvid, source_position FROM ingestion_discoveries"
            ).fetchall()
        )
        assert positions == {"BV1DUPPOS": 2, "BV1INTERVAL": 1}
    finally:
        connection.close()


def test_page_limit_ends_run_as_limited_and_resume_completes(tmp_root):
    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1PAGE1", aid=501), observed_total=2)
    )
    gateway.script_page(
        2, _page(2, _summary("BV1PAGE2", aid=502, title="第二页视频"), observed_total=2)
    )
    gateway.script_page(3, _page(3, observed_total=2))
    gateway.script_parts("BV1PAGE1", (_part("BV1PAGE1", 0, cid=511),))
    gateway.script_parts("BV1PAGE2", (_part("BV1PAGE2", 0, cid=512),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = _ingestor(gateway, repository)
        stopped = ingestor.collect_user_pages(MID, page_limit=1)

        assert stopped.outcome == "limited"
        assert stopped.error_code is None
        assert stopped.next_cursor is not None
        # The explicit limit stops collection: never claimed complete.
        assert (stopped.next_cursor.next_page, stopped.next_cursor.state) == (2, "limited")
        stopped_run = connection.execute(
            "SELECT requested_start_page, requested_page_limit FROM ingestion_runs"
            " WHERE run_id = ?",
            (stopped.run_id,),
        ).fetchone()
        assert tuple(stopped_run) == (1, 1)

        # A fresh run resumes from the stored cursor's next page.
        resumed = ingestor.collect_user_pages(MID)

        assert resumed.outcome == "complete"
        assert resumed.run_id != stopped.run_id
        assert resumed.next_cursor is not None
        assert (resumed.next_cursor.next_page, resumed.next_cursor.state) == (3, "complete")
        resumed_run = connection.execute(
            "SELECT requested_start_page FROM ingestion_runs WHERE run_id = ?",
            (resumed.run_id,),
        ).fetchone()
        assert resumed_run["requested_start_page"] == 2
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 2
        assert [row["work_id"] for row in repository.list_pending_parts()] == [
            "BV1PAGE1:p0",
            "BV1PAGE2:p0",
        ]
        # Each run keeps its own page evidence for the pages it collected.
        page_rows = connection.execute(
            "SELECT run_id, page_number, outcome FROM ingestion_pages"
            " ORDER BY page_number"
        ).fetchall()
        assert [tuple(row) for row in page_rows] == [
            (stopped.run_id, 1, "ok"),
            (resumed.run_id, 2, "ok"),
            (resumed.run_id, 3, "empty"),
        ]
    finally:
        connection.close()


def test_empty_page_completes_even_when_it_reaches_the_page_limit(tmp_root):
    gateway = FakeGateway()
    gateway.script_page(1, _page(1, observed_total=0))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID, page_limit=1)

        # The limit did not cut anything short: the first page was already
        # empty, so the run is complete, never limited.
        assert result.outcome == "complete"
        assert result.page_count == 1
        assert result.next_cursor is not None
        assert (result.next_cursor.next_page, result.next_cursor.state) == (1, "complete")
    finally:
        connection.close()


def test_gateway_failure_rolls_back_page_and_preserves_cursor_for_resume(tmp_root):
    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1KEPT", aid=601), observed_total=2)
    )
    gateway.script_page(2, GatewayTransportError(detail="get_user_video_page"))
    gateway.script_parts("BV1KEPT", (_part("BV1KEPT", 0, cid=601),))
    gateway.script_parts("BV1LOST", (_part("BV1LOST", 0, cid=602),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = _ingestor(gateway, repository)
        ingestor.collect_user_pages(MID, page_limit=1)
        cursor_before_failure = repository.read_cursor(MID)
        assert cursor_before_failure is not None

        failed = ingestor.collect_user_pages(MID)

        assert failed.outcome == "failed"
        assert failed.error_code == "transport_error"
        assert failed.page_count == 1
        assert failed.video_count == 0
        assert failed.part_count == 0
        # The prior cursor is preserved exactly — byte-for-byte record.
        assert repository.read_cursor(MID) == cursor_before_failure
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 1
        failed_run = connection.execute(
            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
            (failed.run_id,),
        ).fetchone()
        assert failed_run["outcome"] == "failed"
        assert failed_run["finished_at"] is not None
        failed_page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ? ORDER BY page_number",
            (failed.run_id,),
        ).fetchall()
        assert [tuple(row) for row in failed_page_rows] == [
            (2, "failed", "transport_error")
        ]

        # The upstream recovers; a fresh run resumes from the preserved
        # cursor and completes the collection.
        gateway.script_page(
            2, _page(2, _summary("BV1LOST", aid=602, title="恢复后视频"), observed_total=2)
        )
        gateway.script_page(3, _page(3, observed_total=2))

        resumed = ingestor.collect_user_pages(MID)

        assert resumed.outcome == "complete"
        assert resumed.run_id != failed.run_id
        assert resumed.next_cursor is not None
        assert (resumed.next_cursor.next_page, resumed.next_cursor.state) == (3, "complete")
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
        resumed_run = connection.execute(
            "SELECT requested_start_page FROM ingestion_runs WHERE run_id = ?",
            (resumed.run_id,),
        ).fetchone()
        assert resumed_run["requested_start_page"] == 2
    finally:
        connection.close()


def test_rate_limited_page_keeps_cursor_and_ends_run_risk_interrupted(tmp_root):
    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1KEPT", aid=701), observed_total=2)
    )
    gateway.script_page(2, GatewayRateLimited(detail="get_user_video_page"))
    gateway.script_parts("BV1KEPT", (_part("BV1KEPT", 0, cid=701),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = _ingestor(gateway, repository)
        ingestor.collect_user_pages(MID, page_limit=1)
        cursor_before = repository.read_cursor(MID)
        assert cursor_before is not None

        interrupted = ingestor.collect_user_pages(MID)

        assert interrupted.outcome == "risk_interrupted"
        assert interrupted.error_code == "rate_limited"
        assert interrupted.page_count == 1
        assert interrupted.video_count == 0
        assert interrupted.part_count == 0
        assert repository.read_cursor(MID) == cursor_before
        interrupted_run = connection.execute(
            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
            (interrupted.run_id,),
        ).fetchone()
        assert interrupted_run["outcome"] == "risk_interrupted"
        assert interrupted_run["finished_at"] is not None
        page_row = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ? ORDER BY page_number",
            (interrupted.run_id,),
        ).fetchone()
        assert tuple(page_row) == (2, "risk_interrupted", "rate_limited")
    finally:
        connection.close()


def test_no_flag_rerun_observing_no_author_keeps_the_stored_display_name(tmp_root):
    """The cross-run pin: an observation-free run must not revert the label.

    The whole point of recording ``author`` is that a reader sees ``未明子``
    rather than ``23191782``; a run that observes nothing may therefore not
    write the placeholder over a name an earlier run established.  The run
    boundary is what makes this a distinct case — each of the two existing name
    assertions runs exactly one collection, so both stay green whether or not
    the opening write reverts.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1NAMED", aid=801), observed_total=1)
    )
    gateway.script_parts("BV1NAMED", (_part("BV1NAMED", 0, cid=801),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = _ingestor(gateway, repository)
        first = ingestor.collect_user_pages(MID, start_page=1)
        assert first.outcome == "complete"
        user_row = connection.execute(
            "SELECT mid, display_name, created_at, updated_at FROM bilibili_users"
        ).fetchone()
        assert tuple(user_row[:2]) == (MID, "未明子")

        # The cursor sits on the empty page, so the plain no-flag re-run
        # observes no item at all and ends complete.
        rerun_gateway = FakeGateway()
        rerun_gateway.script_page(2, _page(2, observed_total=1))
        rerun = _ingestor(rerun_gateway, repository).collect_user_pages(MID)

        assert rerun.outcome == "complete"
        assert rerun.page_count == 1
        # The stored label is byte-for-byte what the observing run left,
        # including its stamp: an empty observation is not a fresh one, so it
        # moves neither the value nor ``updated_at``.
        assert (
            tuple(
                connection.execute(
                    "SELECT mid, display_name, created_at, updated_at"
                    " FROM bilibili_users"
                ).fetchone()
            )
            == tuple(user_row)
        )
    finally:
        connection.close()


def test_risk_interrupted_run_keeps_the_display_name_it_never_observed(tmp_root):
    """A rate-limited run must not replace the label it never read.

    The page transaction rolls back, but the run-start write is its own
    committed transaction — so this arm is reachable even though nothing was
    collected, and ``-412`` upstream is reachable in production.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1KEPT", aid=701), observed_total=2)
    )
    gateway.script_parts("BV1KEPT", (_part("BV1KEPT", 0, cid=701),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, page_limit=1)
        user_row = connection.execute(
            "SELECT mid, display_name, created_at, updated_at FROM bilibili_users"
        ).fetchone()
        assert tuple(user_row[:2]) == (MID, "未明子")

        interrupted_gateway = FakeGateway()
        interrupted_gateway.script_page(
            2, GatewayRateLimited(detail="get_user_video_page")
        )
        interrupted = _ingestor(interrupted_gateway, repository).collect_user_pages(
            MID
        )

        assert interrupted.outcome == "risk_interrupted"
        assert interrupted.error_code == "rate_limited"
        assert (
            tuple(
                connection.execute(
                    "SELECT mid, display_name, created_at, updated_at"
                    " FROM bilibili_users"
                ).fetchone()
            )
            == tuple(user_row)
        )
    finally:
        connection.close()


def test_collected_page_without_an_author_keeps_the_stored_display_name(tmp_root):
    """A collected page with no name writes no user row, so nothing regresses.

    This is the page-writer arm of the same rule: the run observed no name, so
    the owner-mid placeholder it would carry is not written over the stored
    label — the page's videos, parts and cursor still land normally.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1NAMED", aid=801), observed_total=1)
    )
    gateway.script_parts("BV1NAMED", (_part("BV1NAMED", 0, cid=801),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)
        user_row = connection.execute(
            "SELECT mid, display_name, created_at, updated_at FROM bilibili_users"
        ).fetchone()
        assert tuple(user_row[:2]) == (MID, "未明子")

        silent_gateway = FakeGateway()
        silent_gateway.script_page(
            1,
            _page(1, _summary("BV1SILENT", aid=802, author=None), observed_total=1),
        )
        silent_gateway.script_parts("BV1SILENT", (_part("BV1SILENT", 0, cid=802),))
        silent_gateway.script_page(2, _page(2, observed_total=1))
        silent = _ingestor(silent_gateway, repository).collect_user_pages(
            MID, start_page=1
        )

        assert silent.outcome == "complete"
        assert silent.video_count == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM videos WHERE bvid = 'BV1SILENT'"
            ).fetchone()[0]
            == 1
        )
        assert (
            tuple(
                connection.execute(
                    "SELECT mid, display_name, created_at, updated_at"
                    " FROM bilibili_users"
                ).fetchone()
            )
            == tuple(user_row)
        )
    finally:
        connection.close()


def test_page_without_an_author_stores_the_owner_mid_placeholder(tmp_root):
    """The fallback is the negative control: no author anywhere → ``str(mid)``.

    A fresh store whose pages carry no name has observed no label, so the
    placeholder is the honest answer and stays the value the row was created
    with.  Pinned at the store — the gateway's own absent-rather-than-invented
    case says only that the DTO leaves ``None``, not what the row ends up
    holding.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1NOAUTH", aid=803, author=None), observed_total=1)
    )
    gateway.script_parts("BV1NOAUTH", (_part("BV1NOAUTH", 0, cid=803),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(
            MID, start_page=1
        )

        assert result.outcome == "complete"
        user_row = connection.execute(
            "SELECT mid, display_name FROM bilibili_users"
        ).fetchone()
        assert tuple(user_row) == (MID, str(MID))
    finally:
        connection.close()


def test_parts_stage_failure_persists_nothing_and_leaves_the_cursor_untouched(tmp_root):
    """A parts-stage fetch failure is bounded with zero persisted payload.

    The page and every summary fetch fine; only ``get_video_parts`` fails.
    No page transaction has opened at that point, so nothing persists
    except the bounded page/run failure evidence.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1PARTFAIL", aid=921), observed_total=2)
    )
    gateway.script_parts(
        "BV1PARTFAIL", GatewayTransportError(detail="get_video_parts")
    )
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID)

        assert result.outcome == "failed"
        assert result.error_code == "transport_error"
        assert result.page_count == 1
        assert result.video_count == 0
        assert result.part_count == 0
        assert repository.read_cursor(MID) is None
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
            == 0
        )
        page_row = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
        assert tuple(page_row) == (1, "failed", "transport_error")
        run_row = connection.execute(
            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
            (result.run_id,),
        ).fetchone()
        assert run_row["outcome"] == "failed"
        assert run_row["finished_at"] is not None
        assert gateway.parts_calls == ["BV1PARTFAIL"]
    finally:
        connection.close()


def test_foreign_owner_summary_fails_the_page_before_parts_are_requested(tmp_root):
    """D3: part requests only target summaries owned by the requested mid."""

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1FOREIGN", aid=801, owner_mid=MID + 1))
    )
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID)

        assert result.outcome == "failed"
        assert result.error_code == "shape_error"
        # No parts request and no detail call for a foreign-owned summary.
        assert gateway.parts_calls == []
        assert gateway.completion_calls == []
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
            == 0
        )
        assert repository.read_cursor(MID) is None
        page_row = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ? ORDER BY page_number",
            (result.run_id,),
        ).fetchone()
        assert tuple(page_row) == (1, "failed", "shape_error")
    finally:
        connection.close()


def test_missing_aid_is_completed_through_the_gateway_without_speculation(tmp_root):
    gateway = FakeGateway()
    gateway.script_completion("BV1NEEDS", _summary("BV1NEEDS", aid=901))
    gateway.script_page(
        1,
        _page(
            1,
            _summary("BV1NEEDS", aid=None),
            _summary("BV1HAS", aid=912, title="已有编号视频"),
            observed_total=2,
        ),
    )
    gateway.script_page(2, _page(2, observed_total=2))
    gateway.script_parts("BV1NEEDS", (_part("BV1NEEDS", 0, cid=911),))
    gateway.script_parts("BV1HAS", (_part("BV1HAS", 0, cid=912),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID)

        # Only the aid-less summary is completed; the known aid is never
        # refetched (zero speculative detail calls).
        assert gateway.completion_calls == ["BV1NEEDS"]
        stored = dict(connection.execute("SELECT bvid, aid FROM videos").fetchall())
        assert stored == {"BV1NEEDS": 901, "BV1HAS": 912}
        assert result.outcome == "complete"
        assert result.video_count == 2
    finally:
        connection.close()


def test_duplicate_aid_less_summaries_trigger_one_completion_call(tmp_root):
    """A duplicated aid-less entry is one video: one detail fetch.

    Same dedup principle as the parts fetches: the second entry reuses the
    completed summary instead of repeating the upstream detail call.
    """

    gateway = FakeGateway()
    gateway.script_completion("BV1DUPLICATE", _summary("BV1DUPLICATE", aid=555))
    gateway.script_page(
        1,
        _page(
            1,
            _summary("BV1DUPLICATE", aid=None, title="无编号重复条目"),
            _summary("BV1DUPLICATE", aid=None, title="无编号重复条目"),
            observed_total=1,
        ),
    )
    gateway.script_page(2, _page(2, observed_total=1))
    gateway.script_parts("BV1DUPLICATE", (_part("BV1DUPLICATE", 0, cid=5556),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(MID)

        assert gateway.completion_calls == ["BV1DUPLICATE"]
        assert gateway.parts_calls == ["BV1DUPLICATE"]
        stored = dict(connection.execute("SELECT bvid, aid FROM videos").fetchall())
        assert stored == {"BV1DUPLICATE": 555}
        assert result.outcome == "complete"
        assert result.video_count == 1
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"mid": 0}, ValueError),
        ({"mid": True}, TypeError),
        ({"mid": "23191782"}, TypeError),
        ({"mid": MID, "start_page": 0}, ValueError),
        ({"mid": MID, "start_page": True}, TypeError),
        ({"mid": MID, "page_limit": 0}, ValueError),
        ({"mid": MID, "page_limit": -1}, ValueError),
        ({"mid": MID, "page_limit": True}, TypeError),
    ],
)
def test_collect_arguments_are_validated(kwargs, expected):
    connection = open_database(":memory:")
    try:
        with pytest.raises(expected):
            MetadataIngestor(
                FakeGateway(), MetadataRepository(connection)
            ).collect_user_pages(**kwargs)
    finally:
        connection.close()


# ----------------------------------------- real adapter over the package seam


def _seam_gateway(sessdata: str | None = None):
    """Build the real product adapter against the installed offline seam."""

    module = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
    return module.BilibiliApiGateway(sessdata=sessdata)


def test_bilibili_api_gateway_run_persists_normalized_rows(tmp_root, bilibili_api_seam):
    """One real-adapter page run lands the exact normalized repository rows."""

    script = bilibili_api_seam
    script.videos_response = make_videos_response(
        make_vlist_item(bvid="BV1SEAMRUNAA", aid=None, title="  无编号视频  "), count=1
    )
    script.parts_response = [
        make_part_item(cid=2222, page=1, part="  第一部分  ", duration=12)
    ]
    script.info_response = make_detail_response(bvid="BV1SEAMRUNAA")
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        assert result.outcome == "limited"
        assert result.error_code is None
        assert (result.page_count, result.video_count, result.part_count) == (1, 1, 1)
        assert result.next_cursor is not None
        assert (result.next_cursor.next_page, result.next_cursor.state) == (2, "limited")
        assert result.next_cursor.observed_total == 1
        assert result.next_cursor.last_error_code is None

        video_row = connection.execute(
            "SELECT bvid, aid, mid, title FROM videos"
        ).fetchone()
        assert tuple(video_row) == ("BV1SEAMRUNAA", 111, MID, "无编号视频")
        part_row = connection.execute(
            "SELECT bvid, page_index, cid, title, duration_ms, processing_status"
            " FROM video_parts"
        ).fetchone()
        assert tuple(part_row) == ("BV1SEAMRUNAA", 0, 2222, "第一部分", 12_000, "discovered")
        assert [row["work_id"] for row in repository.list_pending_parts()] == [
            "BV1SEAMRUNAA:p0"
        ]
        page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ?",
            (result.run_id,),
        ).fetchall()
        assert [tuple(row) for row in page_rows] == [(1, "ok", None)]
        user_row = connection.execute(
            "SELECT mid, display_name FROM bilibili_users"
        ).fetchone()
        # The real adapter read ``author`` off the vlist item the fixture built
        # and the name survived the aid-completion rebuild between the page
        # boundary and this row.
        assert tuple(user_row) == (MID, "未明子")

        # The pinned adapter drove exactly the three documented upstream
        # calls: one page fetch, the aid completion, one parts fetch.
        assert script.calls == [
            "space.arc.search(pn=1, ps=30)",
            "video.get_info",
            "video.get_pages",
        ]
        assert_only_documented_metadata_calls(script.calls)
    finally:
        connection.close()


def test_bilibili_api_gateway_run_persists_no_upstream_payload_markers(
    tmp_root, bilibili_api_seam, caplog
):
    """Realistic raw payloads normalize away before anything persists."""

    script = bilibili_api_seam
    script.videos_response = make_videos_response(
        make_vlist_item(
            bvid="BV1SEAMLEAKS",
            aid=None,
            sessdata_note=SESSDATA_BOUNDARY_VALUE,
            frame_url=SIGNED_URL_MARKER,
            raw_note=RAW_JSON_BODY_MARKER,
            upstream_note=RAW_UPSTREAM_EXCEPTION_MARKER,
        ),
        count=1,
    )
    script.parts_response = [
        make_part_item(cid=2222, player_note=SESSDATA_BOUNDARY_VALUE)
    ]
    script.info_response = make_detail_response(
        bvid="BV1SEAMLEAKS", raw_body=RAW_JSON_BODY_MARKER, frame_url=SIGNED_URL_MARKER
    )
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        assert result.outcome == "limited"
        # The scan is not vacuous: a normalized video row really persisted.
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert "BV1SEAMLEAKS" in persisted_row_text(connection)

        persisted = persisted_row_text(connection)
        assert_leaks_no_markers(persisted, context="persisted rows")
        assert_leaks_no_markers(repr(result) + str(result), context="run result")
        assert_leaks_no_markers(caplog.text, context="captured logs")
    finally:
        connection.close()


def test_bilibili_api_gateway_upstream_failure_persists_scalar_code_only(
    tmp_root, bilibili_api_seam, caplog
):
    """Raw upstream failure text stays process-local; only the code persists."""

    script = bilibili_api_seam

    def scripted_page(pn: int, ps: int) -> object:
        if pn == 1:
            return make_videos_response(
                make_vlist_item(bvid="BV1SEAMFAILA", aid=1001), count=2
            )
        return make_videos_response(count=2)

    script.videos_response = scripted_page
    script.parts_response = [make_part_item(cid=2222)]
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = MetadataIngestor(_seam_gateway(), repository)
        first = ingestor.collect_user_pages(MID, start_page=1, page_limit=1)
        assert first.outcome == "limited"
        cursor_before_failure = repository.read_cursor(MID)
        assert cursor_before_failure is not None

        script.videos_error = FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT)
        interrupted = ingestor.collect_user_pages(MID)  # resumes page 2

        assert interrupted.outcome == "risk_interrupted"
        assert interrupted.error_code == "rate_limited"
        assert interrupted.page_count == 1
        assert interrupted.video_count == 0
        assert interrupted.part_count == 0
        # The prior cursor is preserved exactly across the failed page.
        assert repository.read_cursor(MID) == cursor_before_failure
        second_page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ?",
            (interrupted.run_id,),
        ).fetchall()
        assert [tuple(row) for row in second_page_rows] == [
            (2, "risk_interrupted", "rate_limited")
        ]

        assert_leaks_no_markers(
            persisted_row_text(connection), context="persisted rows"
        )
        assert_leaks_no_markers(
            repr(interrupted) + str(interrupted), context="run result"
        )
        assert_leaks_no_markers(caplog.text, context="captured logs")
    finally:
        connection.close()


def test_bilibili_api_gateway_foreign_owner_page_requests_no_parts(
    tmp_root, bilibili_api_seam
):
    """D3 at the seam: a foreign-owner summary blocks parts and completion.

    Echoes the Task-2 protocol-double pin with the real adapter: one owned
    item plus one foreign item fail the whole page at the adapter's
    normalization boundary, so no parts or detail call is ever issued even
    for the owned summary on the same page.
    """

    script = bilibili_api_seam
    script.videos_response = make_videos_response(
        make_vlist_item(),
        make_vlist_item(mid=MID + 1, aid=1002),
        count=2,
    )
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(MID)

        assert result.outcome == "failed"
        assert result.error_code == "shape_error"
        assert repository.read_cursor(MID) is None
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM ingestion_discoveries"
            ).fetchone()[0]
            == 0
        )
        page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ?",
            (result.run_id,),
        ).fetchall()
        assert [tuple(row) for row in page_rows] == [(1, "failed", "shape_error")]

        # Exactly one page fetch: no parts, no detail, nothing else.
        assert script.calls == ["space.arc.search(pn=1, ps=30)"]
        assert_only_documented_metadata_calls(script.calls)
    finally:
        connection.close()


@pytest.mark.parametrize("aid", [1001, None], ids=["aid-carrying", "aid-less"])
def test_malformed_upstream_bvid_page_fails_bounded_and_preserves_the_prior_cursor(
    tmp_root, bilibili_api_seam, aid
):
    """A malformed-but-nonempty upstream bvid stays inside the taxonomy.

    The page boundary rejects the item as a bounded shape error on both aid
    paths, records the page/run failure evidence, never reaches the parts
    or detail fetches, and leaves the prior cursor byte-for-byte untouched.
    """

    script = bilibili_api_seam
    script.videos_response = make_videos_response(
        make_vlist_item(bvid="BV1KEPTPAGEX", aid=1001), count=2
    )
    script.parts_response = [make_part_item(cid=2222)]
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = MetadataIngestor(_seam_gateway(), repository)
        first = ingestor.collect_user_pages(MID, start_page=1, page_limit=1)
        assert first.outcome == "limited"
        cursor_before = repository.read_cursor(MID)
        assert cursor_before is not None
        calls_after_first = list(script.calls)

        script.videos_response = make_videos_response(
            make_vlist_item(bvid="BV1MALFORMD", aid=aid), count=2
        )
        failed = ingestor.collect_user_pages(MID)

        assert failed.outcome == "failed"
        assert failed.error_code == "shape_error"
        assert failed.page_count == 1
        assert failed.video_count == 0
        assert failed.part_count == 0
        # The prior cursor is preserved exactly across the failed page.
        assert repository.read_cursor(MID) == cursor_before
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
            == 1
        )
        failed_run = connection.execute(
            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
            (failed.run_id,),
        ).fetchone()
        assert failed_run["outcome"] == "failed"
        assert failed_run["finished_at"] is not None
        failed_page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ?",
            (failed.run_id,),
        ).fetchall()
        assert [tuple(row) for row in failed_page_rows] == [
            (2, "failed", "shape_error")
        ]
        # The malformed bvid never reached the parts or detail fetches.
        assert script.calls == calls_after_first + ["space.arc.search(pn=2, ps=30)"]
    finally:
        connection.close()


def test_no_leak_marker_scan_catches_contamination():
    """The persistence hygiene scanner is not vacuous."""

    for marker in NO_LEAK_MARKERS:
        with pytest.raises(AssertionError) as caught:
            assert_leaks_no_markers("persisted: " + marker, context="demo row")
        assert marker in str(caught.value)
