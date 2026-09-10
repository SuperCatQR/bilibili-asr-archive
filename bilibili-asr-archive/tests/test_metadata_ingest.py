"""Offline ingestor contract tests: resumable normalized metadata collection.

Every test runs :class:`MetadataIngestor` against a fake
``BilibiliGateway`` protocol double (plain dataclasses, no ``bilibili_api``
import, no network) and a real Plan-1 repository over a temporary SQLite
database, so each test observes the normalized rows a collection run leaves
behind.  Unexpected gateway fetches fail loudly instead of returning
script-free data.
"""

from __future__ import annotations

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
)
from bili_asr.storage.database import MetadataRepository, open_database

MID = 23191782
PACKAGE_VERSION = "17.4.2"
PUBDATE = 1_725_859_200


class FakeGateway:
    """Scripted protocol double; unexpected fetches fail the test loudly."""

    def __init__(self) -> None:
        self.package_version = PACKAGE_VERSION
        self.page_calls: list[tuple[int, int, int]] = []
        self.parts_calls: list[str] = []
        self.completion_calls: list[str] = []
        self._pages: dict[int, object] = {}
        self._parts: dict[str, object] = {}
        self._completions: dict[str, object] = {}

    def script_page(self, page_number: int, page: object) -> None:
        self._pages[page_number] = page

    def script_parts(self, bvid: str, parts: object) -> None:
        self._parts[bvid] = parts

    def script_completion(self, bvid: str, completed: object) -> None:
        self._completions[bvid] = completed

    async def get_user_video_page(
        self, mid: int, page_number: int, page_size: int = 100
    ) -> UserVideoPage:
        self.page_calls.append((mid, page_number, page_size))
        return self._scripted(self._pages, page_number, "user-video-page")

    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]:
        self.parts_calls.append(bvid)
        return self._scripted(self._parts, bvid, "video-parts")

    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary:
        self.completion_calls.append(summary.bvid)
        return self._scripted(self._completions, summary.bvid, "completed-summary")

    def get_package_version(self) -> str:
        return self.package_version

    @staticmethod
    def _scripted(script: dict, key: object, what: str) -> object:
        if key not in script:
            raise AssertionError(f"unexpected {what} fetch: {key!r}")
        value = script[key]
        if isinstance(value, BaseException):
            raise value
        return value


def _page(
    page_number: int,
    *summaries: VideoSummary,
    observed_total: int | None = None,
    owner_mid: int | None = None,
) -> UserVideoPage:
    """Build one validated page DTO; owner_mid overrides the requested mid."""

    mid = MID if owner_mid is None else owner_mid
    return UserVideoPage(
        mid=MID, page_number=page_number, videos=summaries, observed_total=observed_total
    )


def _summary(
    bvid: str,
    *,
    aid: int | None = 1001,
    title: str = "未明子讲座",
    owner_mid: int | None = None,
) -> VideoSummary:
    """Build one validated summary DTO owned by the requested user."""

    return VideoSummary(
        bvid=bvid,
        aid=aid,
        title=title,
        pubdate=PUBDATE,
        mid=MID if owner_mid is None else owner_mid,
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
        assert tuple(user_row) == (MID, str(MID))
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
        first = ingestor.collect_user_pages(MID, page_limit=1)
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
        first = ingestor.collect_user_pages(MID, page_limit=1)
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
    with pytest.raises(expected):
        MetadataIngestor(FakeGateway(), MetadataRepository(open_database(":memory:"))).collect_user_pages(
            **kwargs
        )
