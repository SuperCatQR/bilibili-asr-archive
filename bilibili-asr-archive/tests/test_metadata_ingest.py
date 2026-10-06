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
import itertools

import pytest

from bili_asr.services.metadata_ingest import (
    PAGE_SIZE,
    SOURCE_PACKAGE,
    IngestionRunResult,
    MetadataIngestor,
)
from bili_asr.sources.models import (
    GatewayRateLimited,
    GatewayShapeError,
    GatewayTransportError,
    UserVideoPage,
    VideoPart,
    VideoSummary,
    VideoTag,
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
    make_tag_item,
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
    pic: str | None = "http://i1.hdslb.com/bfs/archive/cover.jpg",
    desc: str | None = "哲学讲座简介",
    tid: int | None = 124,
) -> VideoSummary:
    """Build one validated summary DTO owned by the requested user.

    ``author`` defaults to the uploader name the fixture pages carry, so a run
    built from these summaries observes one and records it.  Passing ``None``
    is how a case exercises the ingestor's owner-mid fallback — the arm the
    field's absence is for — and the cross-run cases below are where that
    matters: they are the only callers that pass it.

    ``pic``/``desc``/``tid`` mirror that arrangement for the same reason: a run
    built from these summaries has observed the three detail fields, so the D15
    guard is satisfied and a row is written.  The all-``None`` arm is what the
    D15 cases exercise, and they are the only callers that pass ``None``.
    """

    return VideoSummary(
        bvid=bvid,
        aid=aid,
        title=title,
        pubdate=PUBDATE,
        mid=MID if owner_mid is None else owner_mid,
        author=author,
        pic=pic,
        desc=desc,
        tid=tid,
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


@pytest.fixture
def _ingest_clock(monkeypatch: pytest.MonkeyPatch):
    """Deterministic monotonic clock for ingestor-produced records.

    Patching the ingestor module's clock keeps run and page timestamps strictly
    increasing, so the D11 "``observed_at`` advanced" assertion is satisfiable
    without a real sleep: two collections inside the same wall-clock second
    would otherwise leave the stamp identical.  The same fixture exists in
    ``tests/test_metadata_cli.py`` and ``tests/test_metadata_e2e.py``.
    """

    counter = itertools.count(1)
    monkeypatch.setattr(
        "bili_asr.services.metadata_ingest._now", lambda: next(counter)
    )


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
        assert tuple(part_row) == ("BV1SINGLE", 0, 2222, "第一部分", 12_000, "metadata_collected")
        discovery_row = connection.execute(
            "SELECT run_id, page_number, bvid, source_position FROM ingestion_discoveries"
        ).fetchone()
        assert tuple(discovery_row) == (result.run_id, 1, "BV1SINGLE", 0)
        assert repository.list_pending_parts() == []
        # Metadata completion is independent of caption acquisition: the
        # part still enters the subtitle queue after its metadata is known.
        assert [row[0] for row in connection.execute(
            "SELECT work_id FROM v_pending_subtitles"
        )] == ["BV1SINGLE:p0"]

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
            ("BV1MULTI", 0, 3001, "上篇", 12_000, "metadata_collected"),
            ("BV1MULTI", 1, 3002, "下篇", 10_500, "metadata_collected"),
        ]
        assert (result.page_count, result.video_count, result.part_count) == (2, 1, 2)
        assert result.outcome == "complete"
        assert repository.list_pending_parts() == []
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


def test_undercounted_total_does_not_truncate_metadata_walk(tmp_root):
    gateway = FakeGateway()
    for page_number, bvid in [(1, "BV1TOTALA"), (2, "BV1TOTALB")]:
        gateway.script_page(
            page_number,
            _page(page_number, _summary(bvid, aid=1000 + page_number), observed_total=1),
        )
        gateway.script_parts(bvid, (_part(bvid, 0, cid=2222 + page_number),))
    gateway.script_page(3, _page(3, observed_total=1))
    connection = open_database(tmp_root)
    try:
        result = _ingestor(gateway, MetadataRepository(connection)).collect_user_pages(
            MID, start_page=1
        )

        assert result.outcome == "complete"
        assert (result.page_count, result.video_count, result.part_count) == (3, 2, 2)
        assert result.next_cursor.next_page == 3
        assert [row[0] for row in connection.execute(
            "SELECT bvid FROM videos ORDER BY bvid"
        )] == ["BV1TOTALA", "BV1TOTALB"]
        assert gateway.page_calls == [(MID, page, PAGE_SIZE) for page in [1, 2, 3]]
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
        assert repository.list_pending_parts() == []
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
        assert tuple(part_row) == ("BV1SEAMRUNAA", 0, 2222, "第一部分", 12_000, "metadata_collected")
        assert repository.list_pending_parts() == []
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

        # The pinned adapter drove exactly the four documented upstream
        # calls: one page fetch, the aid completion, one parts fetch, and the
        # per-video tag fetch.
        assert script.calls == [
            "space.arc.search(pn=1, ps=30)",
            "video.get_info",
            "video.get_pages",
            "video.tags",
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


# ------------------------------------------------------------- video tags


def test_tags_are_fetched_once_per_video_not_once_per_part(tmp_root):
    """Three parts of one video must produce exactly ONE tag call.

    The regression is cheap to write and expensive to miss: the tag set is a
    property of the VIDEO, so a fetch inside the per-part loop pays 3x on this
    fixture and O(parts) on a long multipart series.
    """
    gateway = FakeGateway()
    gateway.script_page(1, _page(1, _summary("BV1MULTI"), observed_total=1))
    gateway.script_parts(
        "BV1MULTI",
        (_part("BV1MULTI", 0, cid=11), _part("BV1MULTI", 1, cid=22),
         _part("BV1MULTI", 2, cid=33)),
    )
    gateway.script_tags("BV1MULTI", (
        VideoTag(tag_id=943, tag_name="爱情", tag_type="old_channel"),
        VideoTag(tag_id=11128717, tag_name="人类解放", tag_type="old_channel"),
    ))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)

        assert gateway.tag_calls == ["BV1MULTI"]
        rows = connection.execute(
            "SELECT tag_id, tag_name FROM video_tags WHERE bvid = ? ORDER BY tag_id",
            ("BV1MULTI",),
        ).fetchall()
        assert [tuple(row) for row in rows] == [(943, "爱情"), (11128717, "人类解放")]
    finally:
        connection.close()


def test_tag_calls_are_one_per_distinct_video_across_pages(tmp_root):
    """A video on two pages still costs one tag call, not one per page.

    The bounded cache reuses recent observations within one run.
    A resumed run deliberately starts a fresh observation cache.
    """

    gateway = FakeGateway()
    gateway.script_page(1, _page(1, _summary("BV1REPEAT"), observed_total=2))
    gateway.script_page(2, _page(2, _summary("BV1REPEAT"), observed_total=2))
    gateway.script_page(3, _page(3, observed_total=2))
    gateway.script_parts("BV1REPEAT", (_part("BV1REPEAT", 0),))
    gateway.script_tags(
        "BV1REPEAT",
        (VideoTag(tag_id=943, tag_name="爱情", tag_type="old_channel"),),
    )
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)

        assert gateway.tag_calls == ["BV1REPEAT"]
        # The second page observed the same single tag, so the replacement
        # converged instead of accumulating a duplicate row.
        rows = connection.execute(
            "SELECT tag_id, tag_name FROM video_tags WHERE bvid = ?",
            ("BV1REPEAT",),
        ).fetchall()
        assert [tuple(row) for row in rows] == [(943, "爱情")]
    finally:
        connection.close()


def test_rerun_replaces_the_tag_set_instead_of_appending(tmp_root):
    """A re-run converges on what upstream says now (AC 3).

    The second run observes one renamed tag and one new one; the stored set
    must be exactly those two rows, with the first run's extra row gone.
    """

    gateway = FakeGateway()
    gateway.script_parts("BV1TAGS", (_part("BV1TAGS", 0),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    ingestor = _ingestor(gateway, repository)
    try:
        gateway.script_page(1, _page(1, _summary("BV1TAGS"), observed_total=1))
        gateway.script_page(2, _page(2, observed_total=1))
        gateway.script_tags(
            "BV1TAGS",
            (
                VideoTag(tag_id=1, tag_name="旧名", tag_type="old_channel"),
                VideoTag(tag_id=2, tag_name="将被移除", tag_type="old_channel"),
            ),
        )
        ingestor.collect_user_pages(MID, start_page=1)

        gateway.script_page(3, _page(3, _summary("BV1TAGS"), observed_total=1))
        gateway.script_page(4, _page(4, observed_total=1))
        gateway.script_tags(
            "BV1TAGS",
            (
                VideoTag(tag_id=1, tag_name="新名", tag_type="old_channel"),
                VideoTag(tag_id=3, tag_name="新增", tag_type="old_channel"),
            ),
        )
        ingestor.collect_user_pages(MID, start_page=3)

        rows = connection.execute(
            "SELECT tag_id, tag_name FROM video_tags WHERE bvid = ? ORDER BY tag_id",
            ("BV1TAGS",),
        ).fetchall()
        assert [tuple(row) for row in rows] == [(1, "新名"), (3, "新增")]
    finally:
        connection.close()


def test_observed_empty_tag_set_clears_the_stored_rows(tmp_root):
    """An empty observation is a real answer and replaces the stored set.

    Live-probed: a well-formed bvid answers ``code=0`` with ``data: []`` when
    the video carries no tags.  That observation must clear rows a previous run
    stored, otherwise the archive would keep tags upstream no longer lists.
    """

    gateway = FakeGateway()
    gateway.script_parts("BV1EMPTY", (_part("BV1EMPTY", 0),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    ingestor = _ingestor(gateway, repository)
    try:
        gateway.script_page(1, _page(1, _summary("BV1EMPTY"), observed_total=1))
        gateway.script_page(2, _page(2, observed_total=1))
        gateway.script_tags(
            "BV1EMPTY",
            (VideoTag(tag_id=943, tag_name="爱情", tag_type="old_channel"),),
        )
        ingestor.collect_user_pages(MID, start_page=1)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM video_tags WHERE bvid = 'BV1EMPTY'"
            ).fetchone()[0]
            == 1
        )

        gateway.script_page(3, _page(3, _summary("BV1EMPTY"), observed_total=1))
        gateway.script_page(4, _page(4, observed_total=1))
        gateway.script_tags("BV1EMPTY", ())
        ingestor.collect_user_pages(MID, start_page=3)

        assert (
            connection.execute(
                "SELECT COUNT(*) FROM video_tags WHERE bvid = 'BV1EMPTY'"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_degraded_tag_fetch_does_not_fail_the_run(tmp_root, bilibili_api_seam):
    """A risk-controlled tag fetch records no tags and lets the run finish.

    Driven through the real adapter on the package seam, because the
    degradation lives there rather than in the protocol double: upstream
    answers the tag call with the risk-control code, the adapter turns that
    into ``None``, and the page's other payload must still land.  A test
    against ``FakeGateway`` alone would only be asserting the double's own
    behavior.
    """

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(bvid="BV1DEGRADED0"), count=1
    )
    bilibili_api_seam.parts_response = [make_part_item(cid=2222)]
    # The real adapter maps -352 onto GatewayRateLimited and degrades on it.
    bilibili_api_seam.tags_error = FakeResponseCodeException(-352, UPSTREAM_ERROR_TEXT)
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        assert result.outcome == "limited"
        assert result.error_code is None
        assert bilibili_api_seam.tag_calls == ["BV1DEGRADED0"]
        assert bilibili_api_seam.calls == [
            "space.arc.search(pn=1, ps=30)",
            "video.get_pages",
            "video.tags",
        ]
        assert connection.execute("SELECT COUNT(*) FROM video_tags").fetchone()[0] == 0
        # The rest of the page's payload is intact: the degraded call took
        # nothing else down with it.
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
    finally:
        connection.close()


def test_malformed_tag_payload_is_best_effort_for_page(tmp_root):
    """A malformed optional tag payload leaves the page's core rows intact."""

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1SHAPETAG"), observed_total=1)
    )
    gateway.script_page(2, _page(2, observed_total=1))
    gateway.script_parts("BV1SHAPETAG", (_part("BV1SHAPETAG", 0),))
    gateway.script_tags(
        "BV1SHAPETAG",
        GatewayShapeError(detail="tag response is not an array"),
    )
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        result = _ingestor(gateway, repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        assert result.outcome == "limited"
        assert result.error_code is None
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM video_tags").fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_degraded_tag_fetch_leaves_tags_a_previous_run_stored(tmp_root):
    """One degraded tag fetch must not erase the set a normal run stored.

    **This is the pin for compass D16, and it needs two runs.**  Every other
    degradation case in this file runs on a fresh database, where "wrote
    nothing" and "erased everything" are the same observation — which is
    exactly how the erasure shipped un-observed.  Here run 1 establishes a
    stored set and run 2's tag call degrades, so the two outcomes separate: the
    rows must still be there afterwards.

    The scripted ``None`` is the degraded answer (D16's "could not read this
    time"), not the empty tuple — the empty tuple is the *observation* that
    clears, and that arm is pinned by the neighbouring
    ``test_observed_empty_tag_set_clears_the_stored_rows``.
    """

    gateway = FakeGateway()
    gateway.script_parts("BV1DEGRADEDK", (_part("BV1DEGRADEDK", 0),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    ingestor = _ingestor(gateway, repository)
    try:
        # Run 1: a normal observation stores the set.
        gateway.script_page(1, _page(1, _summary("BV1DEGRADEDK"), observed_total=1))
        gateway.script_page(2, _page(2, observed_total=1))
        gateway.script_tags(
            "BV1DEGRADEDK",
            (
                VideoTag(tag_id=943, tag_name="爱情", tag_type="old_channel"),
                VideoTag(
                    tag_id=11128717, tag_name="人类解放", tag_type="old_channel"
                ),
            ),
        )
        ingestor.collect_user_pages(MID, start_page=1)

        stored = connection.execute(
            "SELECT tag_id FROM video_tags WHERE bvid = 'BV1DEGRADEDK'"
            " ORDER BY tag_id"
        ).fetchall()
        assert [row[0] for row in stored] == [943, 11128717]

        # Run 2: the tag call degrades (risk control, transport failure — the
        # adapter answers None for both) while the page's other payload lands.
        gateway.script_page(3, _page(3, _summary("BV1DEGRADEDK"), observed_total=1))
        gateway.script_page(4, _page(4, observed_total=1))
        gateway.script_tags("BV1DEGRADEDK", None)
        result = ingestor.collect_user_pages(MID, start_page=3)

        assert result.outcome == "complete"
        assert gateway.tag_calls == ["BV1DEGRADEDK", "BV1DEGRADEDK"]
        # The observation that failed wrote nothing: the two rows survive.
        surviving = connection.execute(
            "SELECT tag_id, tag_name FROM video_tags WHERE bvid = 'BV1DEGRADEDK'"
            " ORDER BY tag_id"
        ).fetchall()
        assert [tuple(row) for row in surviving] == [
            (943, "爱情"),
            (11128717, "人类解放"),
        ]
    finally:
        connection.close()


def test_degraded_tag_fetch_leaves_tag_rows_through_the_pinned_adapter(
    tmp_root, bilibili_api_seam
):
    """The same two-run pin, driven through the real adapter's degradation.

    The protocol-double case above asserts the ingestor's mapping; this one
    asserts that the *adapter's* degradation reaches that mapping, because the
    erasure was only reachable if the adapter turned a failed call into an
    observation.  Run 2's tag call answers the risk-control code the plan's
    Global Constraints measured, and run 1's rows must survive it.
    """

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(bvid="BV1DEGRADEDP"), count=1
    )
    bilibili_api_seam.parts_response = [make_part_item(cid=2222)]
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        # Run 1: the adapter reads the tags and the table gets them.
        bilibili_api_seam.tags_response = [
            make_tag_item(tag_id=943, tag_name="爱情"),
            make_tag_item(tag_id=11128717, tag_name="人类解放"),
        ]
        MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )
        assert [
            row[0]
            for row in connection.execute(
                "SELECT tag_id FROM video_tags WHERE bvid = 'BV1DEGRADEDP'"
                " ORDER BY tag_id"
            ).fetchall()
        ] == [943, 11128717]

        # Run 2: -352 on the tag call, the page's other payload intact.
        bilibili_api_seam.tags_response = None
        bilibili_api_seam.tags_error = FakeResponseCodeException(
            -352, UPSTREAM_ERROR_TEXT
        )
        MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=2, page_limit=1
        )

        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT tag_id, tag_name FROM video_tags WHERE bvid = 'BV1DEGRADEDP'"
                " ORDER BY tag_id"
            ).fetchall()
        ] == [(943, "爱情"), (11128717, "人类解放")]
    finally:
        connection.close()


@pytest.mark.parametrize(
    "broken_tags",
    [{"tags": []}, [make_tag_item(tag_name="first\nsecond")]],
    ids=["wrong-envelope", "multiline-tag"],
)
def test_malformed_tag_rerun_keeps_tags_and_updates_core_metadata(
    tmp_root, bilibili_api_seam, broken_tags
):
    script = bilibili_api_seam
    bvid = "BV1SHAPETAG0"
    script.videos_response = make_videos_response(
        make_vlist_item(bvid=bvid, title="before", description="old detail"), count=1
    )
    script.parts_response = [make_part_item(cid=2222)]
    script.tags_response = [make_tag_item(tag_id=943, tag_name="stored tag")]
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        initial = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )
        assert initial.outcome == "limited"

        script.videos_response = make_videos_response(
            make_vlist_item(bvid=bvid, title="after", description="new detail"), count=1
        )
        script.parts_response = [make_part_item(cid=2222, duration=14)]
        script.tags_response = broken_tags
        rerun = MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=2, page_limit=1
        )

        assert rerun.outcome == "limited"
        assert rerun.error_code is None
        assert rerun.next_cursor.next_page == 3
        assert connection.execute(
            "SELECT title FROM videos WHERE bvid = ?", (bvid,)
        ).fetchone()[0] == "after"
        assert connection.execute(
            "SELECT desc FROM video_details WHERE bvid = ?", (bvid,)
        ).fetchone()[0] == "new detail"
        assert connection.execute(
            "SELECT duration_ms FROM video_parts WHERE bvid = ?", (bvid,)
        ).fetchone()[0] == 14_000
        assert [tuple(row) for row in connection.execute(
            "SELECT tag_id, tag_name FROM video_tags WHERE bvid = ?", (bvid,)
        )] == [(943, "stored tag")]
        assert connection.execute(
            "SELECT outcome FROM ingestion_pages WHERE run_id = ?", (rerun.run_id,)
        ).fetchone()[0] == "ok"
    finally:
        connection.close()


def test_multiline_part_title_does_not_wedge_a_metadata_page(
    tmp_root, bilibili_api_seam
):
    script = bilibili_api_seam
    bvid = "BV1MULTILIN0"
    script.videos_response = make_videos_response(make_vlist_item(bvid=bvid), count=1)
    script.parts_response = [
        make_part_item(cid=2222, part="first\r\nsecond"),
        make_part_item(cid=3333, page=2, part="sibling"),
    ]
    script.tags_response = []
    connection = open_database(tmp_root)
    try:
        result = MetadataIngestor(
            _seam_gateway(), MetadataRepository(connection)
        ).collect_user_pages(MID, start_page=1, page_limit=1)

        assert result.outcome == "limited"
        assert result.next_cursor.next_page == 2
        assert result.part_count == 2
        assert [tuple(row) for row in connection.execute(
            "SELECT page_index, cid, title FROM video_parts ORDER BY page_index"
        )] == [(0, 2222, "first second"), (1, 3333, "sibling")]
        assert [row[0] for row in connection.execute(
            "SELECT work_id FROM v_pending_subtitles ORDER BY page_index"
        )] == [f"{bvid}:p0", f"{bvid}:p1"]
    finally:
        connection.close()


def test_tag_rows_land_through_the_pinned_adapter(tmp_root, bilibili_api_seam):
    """The seam-driven happy path: the adapter's tags reach the table.

    The scripted inventory is the live-probed upstream shape (``tag_id``,
    ``tag_name``, ``tag_type``, plus the two fields the archive drops), so the
    end-to-end assertion also pins that the stored columns are exactly the
    three the schema declares.
    """

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(bvid="BV1TAGSEAMD0"), count=1
    )
    bilibili_api_seam.parts_response = [make_part_item(cid=2222)]
    bilibili_api_seam.tags_response = [
        make_tag_item(tag_id=943, tag_name="爱情"),
        make_tag_item(tag_id=11128717, tag_name="人类解放"),
    ]
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        rows = connection.execute(
            "SELECT bvid, tag_id, tag_name, tag_type FROM video_tags ORDER BY tag_id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("BV1TAGSEAMD0", 943, "爱情", "old_channel"),
            ("BV1TAGSEAMD0", 11128717, "人类解放", "old_channel"),
        ]
        assert_leaks_no_markers(
            persisted_row_text(connection), context="tag rows through the adapter"
        )
    finally:
        connection.close()


# ---------------------------------------------------------- video details


def _stored_details(connection, bvid: str = "BV1DETAIL") -> tuple | None:
    """Return one details row as a tuple, or ``None`` when the video has none."""

    row = connection.execute(
        'SELECT pic, "desc", tid, observed_at FROM video_details WHERE bvid = ?',
        (bvid,),
    ).fetchone()
    return None if row is None else tuple(row)


def test_video_details_are_recorded_without_a_second_http_call(tmp_root):
    """``pic``/``desc``/``tid`` come from the page item the run already parses.

    The no-extra-call half is asserted on the recorded call list, not inferred:
    a run whose ``page_calls`` grew would be paying for these fields twice.
    """

    gateway = FakeGateway()
    gateway.script_page(1, _page(1, _summary("BV1DETAIL"), observed_total=1))
    gateway.script_parts("BV1DETAIL", (_part("BV1DETAIL", 0),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)

        # No second call: the same two page fetches the run already made.
        assert [call[1] for call in gateway.page_calls] == [1, 2]

        assert _stored_details(connection) is not None
        pic, desc, tid, observed_at = _stored_details(connection)
        assert (pic, desc, tid) == (
            "http://i1.hdslb.com/bfs/archive/cover.jpg",
            "哲学讲座简介",
            124,
        )
        assert observed_at > 0
    finally:
        connection.close()


def test_video_details_are_refreshed_not_appended(tmp_root, _ingest_clock):
    """Compass D11: one row per video, overwritten by the next collection.

    This is the test that makes the ruling observable.  An implementer who
    reaches for an INSERT history (an obvious "improvement" while adding
    ``observed_at``) passes the case above and fails this one — which is the
    point, because the schema must not offer a reader what D11 says it does not
    promise.  The assertion is on the COUNT as well as the value: a timestamped
    series would also move the newest value.
    """

    gateway = FakeGateway()
    gateway.script_parts("BV1DETAIL", (_part("BV1DETAIL", 0),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    ingestor = _ingestor(gateway, repository)
    try:
        gateway.script_page(1, _page(1, _summary("BV1DETAIL"), observed_total=1))
        gateway.script_page(2, _page(2, observed_total=1))
        ingestor.collect_user_pages(MID, start_page=1)
        first = _stored_details(connection)

        gateway.script_page(3, _page(3, _summary("BV1DETAIL"), observed_total=1))
        gateway.script_page(4, _page(4, observed_total=1))
        ingestor.collect_user_pages(MID, start_page=3)
        second = _stored_details(connection)

        assert (
            connection.execute(
                "SELECT COUNT(*) FROM video_details WHERE bvid = ?",
                ("BV1DETAIL",),
            ).fetchone()[0]
            == 1
        )
        assert first is not None and second is not None
        assert second[3] > first[3], "observed_at must advance on a real observation"
        assert second[:3] == first[:3]
    finally:
        connection.close()


def test_all_null_observation_leaves_the_row_and_its_stamp_untouched(
    tmp_root, _ingest_clock
):
    """Compass D15: the stamp means "last *successful* collection".

    The three value columns are nullable, so an unconditional
    ``DO UPDATE SET`` would blank a populated row and stamp it as fresh —
    recording "nothing was true at T" where the collection established no such
    thing.  The second run below observes none of ``pic``/``desc``/``tid``; the
    row must survive it verbatim, ``observed_at`` included.
    """

    gateway = FakeGateway()
    gateway.script_parts("BV1DETAIL", (_part("BV1DETAIL", 0),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    ingestor = _ingestor(gateway, repository)
    try:
        gateway.script_page(1, _page(1, _summary("BV1DETAIL"), observed_total=1))
        gateway.script_page(2, _page(2, observed_total=1))
        ingestor.collect_user_pages(MID, start_page=1)
        observed = _stored_details(connection)

        # The same video, observed again with none of the three values.
        gateway.script_page(
            3,
            _page(
                3,
                _summary("BV1DETAIL", pic=None, desc=None, tid=None),
                observed_total=1,
            ),
        )
        gateway.script_page(4, _page(4, observed_total=1))
        ingestor.collect_user_pages(MID, start_page=3)

        assert observed is not None
        assert _stored_details(connection) == observed
    finally:
        connection.close()


def test_all_null_observation_writes_no_row_for_a_video_that_has_none(tmp_root):
    """D15's second half: "untouched" may not be satisfied by a row of NULLs.

    A bvid whose only observation carries none of the three values has had
    nothing written about it, so the table must hold no row at all.  Without
    this case, "leaves the row untouched" would pass for an implementation
    that inserts an all-``NULL`` row with a fresh stamp and never updates it.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1,
        _page(
            1,
            _summary("BV1NOFIELDS", pic=None, desc=None, tid=None),
            observed_total=1,
        ),
    )
    gateway.script_parts("BV1NOFIELDS", (_part("BV1NOFIELDS", 0),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)

        assert (
            connection.execute(
                "SELECT COUNT(*) FROM video_details WHERE bvid = ?",
                ("BV1NOFIELDS",),
            ).fetchone()[0]
            == 0
        )
        # The video row itself still landed: the absence is the details row's,
        # not a page that failed to persist.
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM videos WHERE bvid = ?", ("BV1NOFIELDS",)
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_partial_observation_refreshes_only_the_values_it_carried(
    tmp_root, _ingest_clock
):
    """One observed value is enough to refresh the row, NULLs included (D15).

    The guard's condition is "observed **at least one** of the three", not "all
    three": an item carrying only ``pic`` is a successful observation and the
    row is refreshed to exactly what it carried, so a field upstream really did
    drop does not survive as a stale value.  This is the arm that keeps D15
    from being read as "never overwrite a populated column".

    The stamp is asserted too, because a partial observation is an observation
    (D11's "a later collection overwrites it"): a guard that advanced
    ``observed_at`` only on a *full* observation would satisfy every value
    assertion above while leaving the row claiming the older collection.
    """

    gateway = FakeGateway()
    gateway.script_parts("BV1DETAIL", (_part("BV1DETAIL", 0),))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    ingestor = _ingestor(gateway, repository)
    try:
        gateway.script_page(1, _page(1, _summary("BV1DETAIL"), observed_total=1))
        gateway.script_page(2, _page(2, observed_total=1))
        ingestor.collect_user_pages(MID, start_page=1)
        first = _stored_details(connection)

        gateway.script_page(
            3,
            _page(
                3,
                _summary(
                    "BV1DETAIL", pic="http://i1.hdslb.com/bfs/archive/new.jpg",
                    desc=None, tid=None,
                ),
                observed_total=1,
            ),
        )
        gateway.script_page(4, _page(4, observed_total=1))
        ingestor.collect_user_pages(MID, start_page=3)

        stored = _stored_details(connection)
        assert stored is not None
        assert first is not None
        assert stored[:3] == (
            "http://i1.hdslb.com/bfs/archive/new.jpg",
            None,
            None,
        )
        assert stored[3] > first[3], (
            "a partial observation is still an observation: the stamp moves"
        )
    finally:
        connection.close()


def test_video_details_land_through_the_pinned_adapter(tmp_root, bilibili_api_seam):
    """The seam-driven path: the adapter's own keys reach the details table.

    The scripted item is built by ``make_vlist_item``, so the three literal
    defaults this table reads are the fixture's documented vlist shape rather
    than values the test wrote next to the assertion.  The item carries **no
    aid**, so the run takes the ``get_completed_video_summary`` rebuild between
    the page boundary and the repository — the same path Task 1's ``author``
    regression travelled — and the fields must survive it.
    """

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(
            bvid="BV1DETAILSD0",
            aid=None,
            typeid=124,
            pic="http://i1.hdslb.com/bfs/archive/cover.jpg",
            description="哲学讲座简介",
        ),
        count=1,
    )
    bilibili_api_seam.info_response = make_detail_response(bvid="BV1DETAILSD0")
    bilibili_api_seam.parts_response = [make_part_item(cid=2222)]
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        row = connection.execute(
            'SELECT bvid, pic, "desc", tid FROM video_details'
        ).fetchone()
        assert tuple(row) == (
            "BV1DETAILSD0",
            "http://i1.hdslb.com/bfs/archive/cover.jpg",
            "哲学讲座简介",
            124,
        )
        # The rebuild really ran: the aid it filled is stored, so the row above
        # is the post-rebuild one rather than a page that never took that path.
        assert tuple(
            connection.execute(
                "SELECT aid FROM videos WHERE bvid = 'BV1DETAILSD0'"
            ).fetchone()
        ) == (111,)
        assert "video.get_info" in bilibili_api_seam.calls
    finally:
        connection.close()


def test_video_details_land_from_the_fixture_defaults(tmp_root, bilibili_api_seam):
    """The case above overrides the three; this one reads them un-overridden.

    ``test_video_details_land_through_the_pinned_adapter`` passes its own
    ``typeid``/``pic``/``description``, so deleting the fixture's literal
    defaults would leave it — and the whole suite — green, and the brief's
    "otherwise the test proves only that the normalizer can read a dictionary
    the test itself invented" would be satisfied on paper rather than in the
    store.  Here the item is ``make_vlist_item`` with **no** override of the
    three, and the assertion is on the literal defaults themselves, so the
    fixture's documented vlist shape is what the row must hold: dropping a
    default from the fixture turns this red.
    """

    bilibili_api_seam.videos_response = make_videos_response(
        make_vlist_item(bvid="BV1DEFAULTS0", aid=None),
        count=1,
    )
    bilibili_api_seam.info_response = make_detail_response(bvid="BV1DEFAULTS0")
    bilibili_api_seam.parts_response = [make_part_item(cid=2222)]
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        MetadataIngestor(_seam_gateway(), repository).collect_user_pages(
            MID, start_page=1, page_limit=1
        )

        row = connection.execute(
            'SELECT bvid, pic, "desc", tid FROM video_details'
        ).fetchone()
        assert tuple(row) == (
            "BV1DEFAULTS0",
            "http://i1.hdslb.com/bfs/archive/367e793f720ea124722f970965a2db1ba3a733a7.jpg",
            "哲学讲座简介",
            124,
        )
    finally:
        connection.close()


def test_tag_cache_eviction_preserves_page_answers_and_refetches_old_video(tmp_root, monkeypatch):
    monkeypatch.setattr("bili_asr.services.metadata_ingest.TAG_CACHE_SIZE", 2)
    gateway = FakeGateway()
    videos = ("BV1A", "BV1B", "BV1C")
    gateway.script_page(1, _page(1, *(_summary(bvid, aid=1001 + index) for index, bvid in enumerate(videos)), _summary("BV1A")))
    gateway.script_page(2, _page(2, _summary("BV1A")))
    gateway.script_page(3, _page(3))
    for index, bvid in enumerate(videos):
        gateway.script_parts(bvid, (_part(bvid, 0),))
        gateway.script_tags(bvid, (VideoTag(tag_id=index + 1, tag_name=bvid, tag_type="old_channel"),))
    connection = open_database(tmp_root)
    try:
        _ingestor(gateway, MetadataRepository(connection)).collect_user_pages(MID, start_page=1)
        assert gateway.tag_calls == ["BV1A", "BV1B", "BV1C", "BV1A"]
        assert connection.execute("SELECT COUNT(*) FROM video_tags").fetchone()[0] == 3
    finally:
        connection.close()


def test_later_named_page_updates_author_and_nameless_page_preserves_it(tmp_root):
    gateway = FakeGateway()
    for page_number, author in enumerate(("first", "latest", None), 1):
        bvid = f"BV1NAME{page_number}"
        gateway.script_page(page_number, _page(page_number, _summary(bvid, aid=1000 + page_number, author=author)))
        gateway.script_parts(bvid, (_part(bvid, 0),))
    gateway.script_page(4, _page(4))
    connection = open_database(tmp_root)
    try:
        _ingestor(gateway, MetadataRepository(connection)).collect_user_pages(MID, start_page=1)
        assert connection.execute("SELECT display_name FROM bilibili_users").fetchone()[0] == "latest"
    finally:
        connection.close()


def test_resumed_run_refreshes_tags_for_relisted_video(tmp_root):
    gateway = FakeGateway()
    gateway.script_parts("BV1RESUME", (_part("BV1RESUME", 0),))
    gateway.script_page(1, _page(1, _summary("BV1RESUME")))
    gateway.script_tags("BV1RESUME", (VideoTag(tag_id=1, tag_name="old", tag_type="old_channel"),))
    gateway.script_page(2, GatewayTransportError("transport_error"))
    connection = open_database(tmp_root)
    try:
        ingestor = _ingestor(gateway, MetadataRepository(connection))
        assert ingestor.collect_user_pages(MID, start_page=1).outcome == "failed"
        gateway.script_page(2, _page(2, _summary("BV1RESUME")))
        gateway.script_page(3, _page(3))
        gateway.script_tags("BV1RESUME", ())
        ingestor.collect_user_pages(MID)
        assert gateway.tag_calls == ["BV1RESUME", "BV1RESUME"]
        assert connection.execute("SELECT COUNT(*) FROM video_tags").fetchone()[0] == 0
    finally:
        connection.close()
