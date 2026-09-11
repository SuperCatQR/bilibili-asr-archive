# Task 2 Diff — 20260909-bilibili-api-ingestion

Base: `dfb66ba`
Head: `0c2c379`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/services/__init__.py b/bilibili-asr-archive/src/bili_asr/services/__init__.py
new file mode 100644
index 0000000..ec8fe49
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/services/__init__.py
@@ -0,0 +1,8 @@
+"""Application services over normalized storage and typed gateways."""
+
+from bili_asr.services.metadata_ingest import (
+    IngestionRunResult,
+    MetadataIngestor,
+)
+
+__all__ = ["IngestionRunResult", "MetadataIngestor"]
diff --git a/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
new file mode 100644
index 0000000..5efea0b
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py
@@ -0,0 +1,453 @@
+"""Resumable normalized metadata ingestion between gateway and repository.
+
+:class:`MetadataIngestor` owns pagination, the resumable cursor, and the
+run/page transaction flow.  Every page is fetched through the typed
+:class:`BilibiliGateway` protocol and persisted through the Plan-1
+repository's canonical methods in exactly one committed transaction per
+page: upsert user, upsert videos, upsert parts, insert discoveries, update
+the cursor, record the page outcome, commit.
+
+The service is synchronous on its surface (the CLI calls it directly) and
+runs the async gateway page calls on one event loop per collection run.
+Gateway failures roll the failed page back completely; only a bounded scalar
+error code is persisted afterwards, and the previous cursor is preserved
+exactly so a later run can resume from it.
+"""
+
+from __future__ import annotations
+
+import asyncio
+import time
+import uuid
+from dataclasses import dataclass
+
+from bili_asr.sources.models import (
+    BilibiliGateway,
+    GatewayError,
+    GatewayRateLimited,
+    GatewayShapeError,
+    UserVideoPage,
+    VideoPart,
+    VideoSummary,
+)
+from bili_asr.storage.database import MetadataRepository
+from bili_asr.storage.models import (
+    CursorRecord,
+    DiscoveryRecord,
+    IngestionPageRecord,
+    IngestionRunRecord,
+    PageOutcome,
+    RunOutcome,
+    UserRecord,
+    VideoPartRecord,
+    VideoRecord,
+)
+
+SOURCE_PACKAGE = "bilibili-api-python"
+PAGE_SIZE = 100
+
+
+def _now() -> int:
+    """Return the current Unix second used for all persisted clocks."""
+
+    return int(time.time())
+
+
+def _page_and_run_outcomes(error: GatewayError) -> tuple[PageOutcome, RunOutcome]:
+    """Map a bounded gateway failure onto page and run outcomes.
+
+    Upstream rate control is a bounded risk signal: the page is recorded
+    ``risk_interrupted`` and the run ends ``risk_interrupted``, still
+    resumable from the untouched cursor.  Every other gateway failure is
+    terminal for the run and the page.
+    """
+
+    if isinstance(error, GatewayRateLimited):
+        return "risk_interrupted", "risk_interrupted"
+    return "failed", "failed"
+
+
+def _run_record(
+    run_id: str,
+    mid: int,
+    source_version: str,
+    requested_start_page: int,
+    requested_page_limit: int | None,
+    started_at: int,
+    outcome: RunOutcome = "running",
+    finished_at: int | None = None,
+) -> IngestionRunRecord:
+    """Build the run record used for one collection run's start or finish."""
+
+    return IngestionRunRecord(
+        run_id=run_id,
+        mid=mid,
+        source_package=SOURCE_PACKAGE,
+        source_version=source_version,
+        requested_start_page=requested_start_page,
+        requested_page_limit=requested_page_limit,
+        started_at=started_at,
+        outcome=outcome,
+        finished_at=finished_at,
+    )
+
+
+def _user_record(mid: int, moment: int) -> UserRecord:
+    """Build the collected user's current display label.
+
+    The gateway DTO contract carries no display-name field, so the current
+    label is the owner mid; a gateway method that exposes the display name
+    changes only this helper.
+    """
+
+    return UserRecord(
+        mid=mid, display_name=str(mid), created_at=moment, updated_at=moment
+    )
+
+
+@dataclass(frozen=True, slots=True)
+class IngestionRunResult:
+    """Terminal evidence of one metadata collection run.
+
+    ``outcome`` is the run's terminal outcome (never ``running``) and
+    ``error_code`` carries the bounded scalar failure code when the run ended
+    ``risk_interrupted`` or ``failed``.  ``next_cursor`` is the cursor as it
+    is stored after the run.  ``page_count`` counts the page-evidence rows the
+    run wrote, including interrupted or failed pages, matching
+    ``v_ingestion_run_stats``; ``video_count`` counts the distinct videos the
+    run discovered; ``part_count`` counts the distinct parts the run upserted
+    (part rows are not run-scoped, so this count reflects upsert coverage).
+    """
+
+    run_id: str
+    mid: int
+    outcome: RunOutcome
+    next_cursor: CursorRecord | None
+    page_count: int
+    video_count: int
+    part_count: int
+    error_code: str | None
+
+
+class MetadataIngestor:
+    """Collect one user's video pages into normalized repository records.
+
+    The ingestor starts from the caller's ``start_page`` when given, else
+    from the stored cursor's ``next_page``, else from page 1, and stops at
+    the first empty page (natural completion), the explicit ``page_limit``
+    (outcome ``limited`` — never claimed as complete), or a bounded gateway
+    failure (outcome ``risk_interrupted`` or ``failed``).  An empty page
+    completes the collection even when it happens to be the page that an
+    explicit limit would have stopped on, because nothing was cut short.
+    """
+
+    def __init__(self, gateway: BilibiliGateway, repository: MetadataRepository) -> None:
+        self._gateway = gateway
+        self._repository = repository
+
+    def collect_user_pages(
+        self,
+        mid: int,
+        start_page: int | None = None,
+        page_limit: int | None = None,
+    ) -> IngestionRunResult:
+        """Run one resumable metadata collection for ``mid``.
+
+        ``start_page`` overrides the stored cursor's ``next_page`` when given
+        (a run may also move the cursor backwards by explicit request);
+        ``page_limit`` bounds how many pages this run may collect.  The run
+        row carries the resolved bounds and the gateway's package version.
+
+        Any exception that is not a bounded gateway failure (for example a
+        caller-argument ``ValueError`` raised by the gateway) propagates
+        unchanged: those are programming or contract errors, not collection
+        evidence.
+        """
+
+        self._validate_arguments(mid, start_page, page_limit)
+        return asyncio.run(
+            self._collect(mid=mid, start_page=start_page, page_limit=page_limit)
+        )
+
+    @staticmethod
+    def _validate_arguments(
+        mid: int, start_page: int | None, page_limit: int | None
+    ) -> None:
+        """Reject caller-argument violations before any gateway call."""
+
+        if isinstance(mid, bool) or not isinstance(mid, int):
+            raise TypeError("mid must be an integer")
+        if mid < 1:
+            raise ValueError("mid must be a positive integer")
+        if start_page is not None:
+            if isinstance(start_page, bool) or not isinstance(start_page, int):
+                raise TypeError("start_page must be an integer or None")
+            if start_page < 1:
+                raise ValueError("start_page must be a positive integer")
+        if page_limit is not None:
+            if isinstance(page_limit, bool) or not isinstance(page_limit, int):
+                raise TypeError("page_limit must be a positive integer or None")
+            if page_limit < 1:
+                raise ValueError("page_limit must be a positive integer")
+
+    def _resume_page(self, mid: int) -> int:
+        """Return the stored cursor's next page, or page 1 when absent."""
+
+        cursor = self._repository.read_cursor(mid)
+        return 1 if cursor is None else cursor.next_page
+
+    async def _collect(
+        self, mid: int, start_page: int | None, page_limit: int | None
+    ) -> IngestionRunResult:
+        """Fetch and persist pages until completion, a limit, or a failure."""
+
+        started_at = _now()
+        with self._repository.transaction():
+            self._repository.upsert_user(_user_record(mid, started_at))
+        first_page = start_page if start_page is not None else self._resume_page(mid)
+        source_version = self._gateway.get_package_version()
+        run_id = uuid.uuid4().hex
+        self._repository.start_run(
+            _run_record(
+                run_id, mid, source_version, first_page, page_limit, started_at
+            )
+        )
+
+        page_count = 0
+        discovered_videos: set[str] = set()
+        upserted_parts: set[tuple[str, int]] = set()
+        outcome: RunOutcome = "complete"
+        error_code: str | None = None
+        page_number = first_page
+        while True:
+            page_started_at = _now()
+            try:
+                page = await self._gateway.get_user_video_page(
+                    mid, page_number, PAGE_SIZE
+                )
+                summaries = [
+                    await self._completed_summary(summary, mid)
+                    for summary in page.videos
+                ]
+                parts_by_video: dict[str, tuple[VideoPart, ...]] = {}
+                for summary in summaries:
+                    # One parts fetch per distinct video: a duplicated page
+                    # entry is the same video, so the identical fetch would
+                    # only repeat upstream work.
+                    if summary.bvid not in parts_by_video:
+                        parts_by_video[summary.bvid] = (
+                            await self._gateway.get_video_parts(summary.bvid)
+                        )
+            except GatewayError as error:
+                page_outcome, run_outcome = _page_and_run_outcomes(error)
+                self._repository.record_page(
+                    IngestionPageRecord(
+                        run_id=run_id,
+                        page_number=page_number,
+                        outcome=page_outcome,
+                        error_code=error.code,
+                        started_at=page_started_at,
+                        finished_at=_now(),
+                    )
+                )
+                outcome = run_outcome
+                error_code = error.code
+                page_count += 1
+                break
+            page_finished_at = _now()
+            if not summaries:
+                self._record_empty_page(
+                    run_id,
+                    mid,
+                    page_number,
+                    page_started_at,
+                    page_finished_at,
+                    page.observed_total,
+                )
+                page_count += 1
+                outcome = "complete"
+                break
+            limit_reached = page_limit is not None and page_count + 1 >= page_limit
+            self._record_collected_page(
+                run_id,
+                mid,
+                page_number,
+                summaries,
+                parts_by_video,
+                page_started_at,
+                page_finished_at,
+                page.observed_total,
+                limit_reached,
+            )
+            page_count += 1
+            discovered_videos.update(summary.bvid for summary in summaries)
+            for parts in parts_by_video.values():
+                upserted_parts.update(
+                    (part.bvid, part.page_index) for part in parts
+                )
+            if limit_reached:
+                outcome = "limited"
+                break
+            page_number += 1
+
+        if outcome != "failed":
+            # The failed run already finished atomically inside record_page.
+            # Every other outcome finishes here as its own terminal commit.
+            self._repository.finish_run(
+                _run_record(
+                    run_id,
+                    mid,
+                    source_version,
+                    first_page,
+                    page_limit,
+                    started_at,
+                    outcome=outcome,
+                    finished_at=_now(),
+                )
+            )
+        return IngestionRunResult(
+            run_id=run_id,
+            mid=mid,
+            outcome=outcome,
+            next_cursor=self._repository.read_cursor(mid),
+            page_count=page_count,
+            video_count=len(discovered_videos),
+            part_count=len(upserted_parts),
+            error_code=error_code,
+        )
+
+    async def _completed_summary(self, summary: VideoSummary, mid: int) -> VideoSummary:
+        """Return the summary with its aid filled when the page omitted it.
+
+        The gateway validates every summary's owner mid against the requested
+        user at the page boundary; this second guard keeps transitive part
+        ownership enforced ingestor-side even if a gateway implementation
+        ever returned a foreign summary, and it fires before any detail
+        fetch so no call is ever made for a video that failed the ownership
+        check.
+        """
+
+        if summary.mid != mid:
+            raise GatewayShapeError(
+                detail="summary owner does not match the requested user"
+            )
+        if summary.aid is None:
+            return await self._gateway.get_completed_video_summary(summary)
+        return summary
+
+    def _record_empty_page(
+        self,
+        run_id: str,
+        mid: int,
+        page_number: int,
+        started_at: int,
+        finished_at: int,
+        observed_total: int | None,
+    ) -> None:
+        """Record the empty page and the completing cursor in one commit.
+
+        The cursor keeps ``next_page`` at the empty page itself: nothing was
+        cut short, and a later resume from this page would re-verify the
+        completion idempotently.
+        """
+
+        self._repository.record_page(
+            IngestionPageRecord(
+                run_id=run_id,
+                page_number=page_number,
+                outcome="empty",
+                error_code=None,
+                started_at=started_at,
+                finished_at=finished_at,
+            ),
+            cursor=CursorRecord(
+                mid=mid,
+                next_page=page_number,
+                observed_total=observed_total,
+                state="complete",
+                last_error_code=None,
+                updated_at=finished_at,
+            ),
+        )
+
+    def _record_collected_page(
+        self,
+        run_id: str,
+        mid: int,
+        page_number: int,
+        summaries: list[VideoSummary],
+        parts_by_video: dict[str, tuple[VideoPart, ...]],
+        started_at: int,
+        finished_at: int,
+        observed_total: int | None,
+        limit_reached: bool,
+    ) -> None:
+        """Record one collected page with its payload in the locked order.
+
+        The repository's ``record_page`` applies the Plan-1 order — user,
+        videos, parts, discoveries, cursor, page outcome — inside one
+        transaction and commits it.  Duplicate summary entries collapse into
+        their existing entity rows through the upsert keys.
+        """
+
+        video_records = [
+            VideoRecord(
+                bvid=summary.bvid,
+                aid=summary.aid,
+                mid=summary.mid,
+                title=summary.title,
+                pubdate=summary.pubdate,
+                created_at=finished_at,
+                updated_at=finished_at,
+            )
+            for summary in summaries
+        ]
+        part_records = [
+            VideoPartRecord(
+                bvid=part.bvid,
+                page_index=part.page_index,
+                cid=part.cid,
+                title=part.title,
+                duration_ms=part.duration_ms,
+                processing_status="discovered",
+                created_at=finished_at,
+                updated_at=finished_at,
+            )
+            for parts in parts_by_video.values()
+            for part in parts
+        ]
+        discovery_records = [
+            DiscoveryRecord(
+                run_id=run_id,
+                page_number=page_number,
+                bvid=summary.bvid,
+                source_position=position,
+                discovered_at=finished_at,
+            )
+            for position, summary in enumerate(summaries)
+        ]
+        self._repository.record_page(
+            IngestionPageRecord(
+                run_id=run_id,
+                page_number=page_number,
+                outcome="ok",
+                error_code=None,
+                started_at=started_at,
+                finished_at=finished_at,
+            ),
+            user=_user_record(mid, finished_at),
+            videos=video_records,
+            parts=part_records,
+            discoveries=discovery_records,
+            cursor=CursorRecord(
+                mid=mid,
+                next_page=page_number + 1,
+                observed_total=observed_total,
+                state="limited" if limit_reached else "ready",
+                last_error_code=None,
+                updated_at=finished_at,
+            ),
+        )
+
+
+__all__ = ["IngestionRunResult", "MetadataIngestor", "PAGE_SIZE", "SOURCE_PACKAGE"]
diff --git a/bilibili-asr-archive/tests/test_metadata_ingest.py b/bilibili-asr-archive/tests/test_metadata_ingest.py
new file mode 100644
index 0000000..41c0fdc
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_metadata_ingest.py
@@ -0,0 +1,541 @@
+"""Offline ingestor contract tests: resumable normalized metadata collection.
+
+Every test runs :class:`MetadataIngestor` against a fake
+``BilibiliGateway`` protocol double (plain dataclasses, no ``bilibili_api``
+import, no network) and a real Plan-1 repository over a temporary SQLite
+database, so each test observes the normalized rows a collection run leaves
+behind.  Unexpected gateway fetches fail loudly instead of returning
+script-free data.
+"""
+
+from __future__ import annotations
+
+import pytest
+
+from bili_asr.services.metadata_ingest import (
+    PAGE_SIZE,
+    SOURCE_PACKAGE,
+    IngestionRunResult,
+    MetadataIngestor,
+)
+from bili_asr.sources.models import (
+    GatewayRateLimited,
+    GatewayShapeError,
+    GatewayTransportError,
+    UserVideoPage,
+    VideoPart,
+    VideoSummary,
+)
+from bili_asr.storage.database import MetadataRepository, open_database
+
+MID = 23191782
+PACKAGE_VERSION = "17.4.2"
+PUBDATE = 1_725_859_200
+
+
+class FakeGateway:
+    """Scripted protocol double; unexpected fetches fail the test loudly."""
+
+    def __init__(self) -> None:
+        self.package_version = PACKAGE_VERSION
+        self.page_calls: list[tuple[int, int, int]] = []
+        self.parts_calls: list[str] = []
+        self.completion_calls: list[str] = []
+        self._pages: dict[int, object] = {}
+        self._parts: dict[str, object] = {}
+        self._completions: dict[str, object] = {}
+
+    def script_page(self, page_number: int, page: object) -> None:
+        self._pages[page_number] = page
+
+    def script_parts(self, bvid: str, parts: object) -> None:
+        self._parts[bvid] = parts
+
+    def script_completion(self, bvid: str, completed: object) -> None:
+        self._completions[bvid] = completed
+
+    async def get_user_video_page(
+        self, mid: int, page_number: int, page_size: int = 100
+    ) -> UserVideoPage:
+        self.page_calls.append((mid, page_number, page_size))
+        return self._scripted(self._pages, page_number, "user-video-page")
+
+    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]:
+        self.parts_calls.append(bvid)
+        return self._scripted(self._parts, bvid, "video-parts")
+
+    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary:
+        self.completion_calls.append(summary.bvid)
+        return self._scripted(self._completions, summary.bvid, "completed-summary")
+
+    def get_package_version(self) -> str:
+        return self.package_version
+
+    @staticmethod
+    def _scripted(script: dict, key: object, what: str) -> object:
+        if key not in script:
+            raise AssertionError(f"unexpected {what} fetch: {key!r}")
+        value = script[key]
+        if isinstance(value, BaseException):
+            raise value
+        return value
+
+
+def _page(
+    page_number: int,
+    *summaries: VideoSummary,
+    observed_total: int | None = None,
+    owner_mid: int | None = None,
+) -> UserVideoPage:
+    """Build one validated page DTO; owner_mid overrides the requested mid."""
+
+    mid = MID if owner_mid is None else owner_mid
+    return UserVideoPage(
+        mid=MID, page_number=page_number, videos=summaries, observed_total=observed_total
+    )
+
+
+def _summary(
+    bvid: str,
+    *,
+    aid: int | None = 1001,
+    title: str = "未明子讲座",
+    owner_mid: int | None = None,
+) -> VideoSummary:
+    """Build one validated summary DTO owned by the requested user."""
+
+    return VideoSummary(
+        bvid=bvid,
+        aid=aid,
+        title=title,
+        pubdate=PUBDATE,
+        mid=MID if owner_mid is None else owner_mid,
+    )
+
+
+def _part(
+    bvid: str,
+    page_index: int,
+    *,
+    cid: int = 2222,
+    title: str = "第一部分",
+    duration_ms: int = 12_000,
+) -> VideoPart:
+    """Build one normalized part DTO."""
+
+    return VideoPart(
+        bvid=bvid,
+        page_index=page_index,
+        cid=cid,
+        title=title,
+        duration_ms=duration_ms,
+    )
+
+
+def _ingestor(gateway: FakeGateway, repository: MetadataRepository) -> MetadataIngestor:
+    return MetadataIngestor(gateway, repository)
+
+
+def test_single_part_run_completes_with_normalized_rows(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_page(
+        1, _page(1, _summary("BV1SINGLE", aid=1001), observed_total=1)
+    )
+    gateway.script_parts("BV1SINGLE", (_part("BV1SINGLE", 0),))
+    gateway.script_page(2, _page(2, observed_total=1))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)
+
+        assert isinstance(result, IngestionRunResult)
+        assert result.outcome == "complete"
+        assert result.error_code is None
+        assert (result.page_count, result.video_count, result.part_count) == (2, 1, 1)
+
+        # The cursor advanced exactly once, into completion state, and
+        # observed_total came from the page response.
+        assert result.next_cursor is not None
+        assert (result.next_cursor.next_page, result.next_cursor.state) == (2, "complete")
+        assert result.next_cursor.observed_total == 1
+        assert result.next_cursor.last_error_code is None
+
+        run_row = connection.execute(
+            "SELECT mid, source_package, source_version, requested_start_page,"
+            " requested_page_limit, started_at, finished_at, outcome"
+            " FROM ingestion_runs WHERE run_id = ?",
+            (result.run_id,),
+        ).fetchone()
+        assert run_row is not None
+        assert tuple(run_row)[:5] == (MID, SOURCE_PACKAGE, PACKAGE_VERSION, 1, None)
+        assert run_row["finished_at"] >= run_row["started_at"]
+        assert run_row["outcome"] == "complete"
+
+        page_rows = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ? ORDER BY page_number",
+            (result.run_id,),
+        ).fetchall()
+        assert [tuple(row) for row in page_rows] == [(1, "ok", None), (2, "empty", None)]
+
+        user_row = connection.execute(
+            "SELECT mid, display_name FROM bilibili_users"
+        ).fetchone()
+        assert tuple(user_row) == (MID, str(MID))
+        video_row = connection.execute("SELECT bvid, aid, mid, title FROM videos").fetchone()
+        assert tuple(video_row) == ("BV1SINGLE", 1001, MID, "未明子讲座")
+        part_row = connection.execute(
+            "SELECT bvid, page_index, cid, title, duration_ms, processing_status FROM video_parts"
+        ).fetchone()
+        assert tuple(part_row) == ("BV1SINGLE", 0, 2222, "第一部分", 12_000, "discovered")
+        discovery_row = connection.execute(
+            "SELECT run_id, page_number, bvid, source_position FROM ingestion_discoveries"
+        ).fetchone()
+        assert tuple(discovery_row) == (result.run_id, 1, "BV1SINGLE", 0)
+        assert [row["work_id"] for row in repository.list_pending_parts()] == ["BV1SINGLE:p0"]
+
+        # Exactly one bounded page fetch per requested page, no detail calls.
+        assert gateway.page_calls == [(MID, 1, PAGE_SIZE), (MID, 2, PAGE_SIZE)]
+        assert gateway.parts_calls == ["BV1SINGLE"]
+        assert gateway.completion_calls == []
+    finally:
+        connection.close()
+
+
+def test_multipart_video_persists_zero_based_parts_in_milliseconds(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_page(
+        1,
+        _page(1, _summary("BV1MULTI", aid=1002, title="多集视频"), observed_total=1),
+    )
+    gateway.script_parts(
+        "BV1MULTI",
+        (
+            _part("BV1MULTI", 0, cid=3001, title="上篇", duration_ms=12_000),
+            _part("BV1MULTI", 1, cid=3002, title="下篇", duration_ms=10_500),
+        ),
+    )
+    gateway.script_page(2, _page(2, observed_total=1))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID)
+
+        part_rows = connection.execute(
+            "SELECT bvid, page_index, cid, title, duration_ms, processing_status"
+            " FROM video_parts ORDER BY page_index"
+        ).fetchall()
+        assert [tuple(row) for row in part_rows] == [
+            ("BV1MULTI", 0, 3001, "上篇", 12_000, "discovered"),
+            ("BV1MULTI", 1, 3002, "下篇", 10_500, "discovered"),
+        ]
+        assert (result.page_count, result.video_count, result.part_count) == (2, 1, 2)
+        assert result.outcome == "complete"
+        assert [row["work_id"] for row in repository.list_pending_parts()] == [
+            "BV1MULTI:p0",
+            "BV1MULTI:p1",
+        ]
+    finally:
+        connection.close()
+
+
+def test_duplicate_summaries_in_one_page_collapse_into_single_rows(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_page(
+        1,
+        _page(
+            1,
+            _summary("BV1DUP", aid=333, title="重复条目"),
+            _summary("BV1DUP", aid=333, title="重复条目"),
+            observed_total=1,
+        ),
+    )
+    gateway.script_parts("BV1DUP", (_part("BV1DUP", 0, cid=4444),))
+    gateway.script_page(2, _page(2, observed_total=1))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID)
+
+        assert result.video_count == 1
+        assert result.part_count == 1
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        assert (
+            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
+            == 1
+        )
+        assert connection.execute("SELECT title FROM videos").fetchone()[0] == "重复条目"
+        # The duplicated video is a single distinct target: one parts fetch.
+        assert gateway.parts_calls == ["BV1DUP"]
+    finally:
+        connection.close()
+
+
+def test_page_limit_ends_run_as_limited_and_resume_completes(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_page(
+        1, _page(1, _summary("BV1PAGE1", aid=501), observed_total=2)
+    )
+    gateway.script_page(
+        2, _page(2, _summary("BV1PAGE2", aid=502, title="第二页视频"), observed_total=2)
+    )
+    gateway.script_page(3, _page(3, observed_total=2))
+    gateway.script_parts("BV1PAGE1", (_part("BV1PAGE1", 0, cid=511),))
+    gateway.script_parts("BV1PAGE2", (_part("BV1PAGE2", 0, cid=512),))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        ingestor = _ingestor(gateway, repository)
+        stopped = ingestor.collect_user_pages(MID, page_limit=1)
+
+        assert stopped.outcome == "limited"
+        assert stopped.error_code is None
+        assert stopped.next_cursor is not None
+        # The explicit limit stops collection: never claimed complete.
+        assert (stopped.next_cursor.next_page, stopped.next_cursor.state) == (2, "limited")
+        stopped_run = connection.execute(
+            "SELECT requested_start_page, requested_page_limit FROM ingestion_runs"
+            " WHERE run_id = ?",
+            (stopped.run_id,),
+        ).fetchone()
+        assert tuple(stopped_run) == (1, 1)
+
+        # A fresh run resumes from the stored cursor's next page.
+        resumed = ingestor.collect_user_pages(MID)
+
+        assert resumed.outcome == "complete"
+        assert resumed.run_id != stopped.run_id
+        assert resumed.next_cursor is not None
+        assert (resumed.next_cursor.next_page, resumed.next_cursor.state) == (3, "complete")
+        resumed_run = connection.execute(
+            "SELECT requested_start_page FROM ingestion_runs WHERE run_id = ?",
+            (resumed.run_id,),
+        ).fetchone()
+        assert resumed_run["requested_start_page"] == 2
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 2
+        assert [row["work_id"] for row in repository.list_pending_parts()] == [
+            "BV1PAGE1:p0",
+            "BV1PAGE2:p0",
+        ]
+        # Each run keeps its own page evidence for the pages it collected.
+        page_rows = connection.execute(
+            "SELECT run_id, page_number, outcome FROM ingestion_pages"
+            " ORDER BY page_number"
+        ).fetchall()
+        assert [tuple(row) for row in page_rows] == [
+            (stopped.run_id, 1, "ok"),
+            (resumed.run_id, 2, "ok"),
+            (resumed.run_id, 3, "empty"),
+        ]
+    finally:
+        connection.close()
+
+
+def test_empty_page_completes_even_when_it_reaches_the_page_limit(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_page(1, _page(1, observed_total=0))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID, page_limit=1)
+
+        # The limit did not cut anything short: the first page was already
+        # empty, so the run is complete, never limited.
+        assert result.outcome == "complete"
+        assert result.page_count == 1
+        assert result.next_cursor is not None
+        assert (result.next_cursor.next_page, result.next_cursor.state) == (1, "complete")
+    finally:
+        connection.close()
+
+
+def test_gateway_failure_rolls_back_page_and_preserves_cursor_for_resume(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_page(
+        1, _page(1, _summary("BV1KEPT", aid=601), observed_total=2)
+    )
+    gateway.script_page(2, GatewayTransportError(detail="get_user_video_page"))
+    gateway.script_parts("BV1KEPT", (_part("BV1KEPT", 0, cid=601),))
+    gateway.script_parts("BV1LOST", (_part("BV1LOST", 0, cid=602),))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        ingestor = _ingestor(gateway, repository)
+        first = ingestor.collect_user_pages(MID, page_limit=1)
+        cursor_before_failure = repository.read_cursor(MID)
+        assert cursor_before_failure is not None
+
+        failed = ingestor.collect_user_pages(MID)
+
+        assert failed.outcome == "failed"
+        assert failed.error_code == "transport_error"
+        assert failed.page_count == 1
+        assert failed.video_count == 0
+        assert failed.part_count == 0
+        # The prior cursor is preserved exactly — byte-for-byte record.
+        assert repository.read_cursor(MID) == cursor_before_failure
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0] == 1
+        failed_run = connection.execute(
+            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
+            (failed.run_id,),
+        ).fetchone()
+        assert failed_run["outcome"] == "failed"
+        assert failed_run["finished_at"] is not None
+        failed_page_rows = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ? ORDER BY page_number",
+            (failed.run_id,),
+        ).fetchall()
+        assert [tuple(row) for row in failed_page_rows] == [
+            (2, "failed", "transport_error")
+        ]
+
+        # The upstream recovers; a fresh run resumes from the preserved
+        # cursor and completes the collection.
+        gateway.script_page(
+            2, _page(2, _summary("BV1LOST", aid=602, title="恢复后视频"), observed_total=2)
+        )
+        gateway.script_page(3, _page(3, observed_total=2))
+
+        resumed = ingestor.collect_user_pages(MID)
+
+        assert resumed.outcome == "complete"
+        assert resumed.run_id != failed.run_id
+        assert resumed.next_cursor is not None
+        assert (resumed.next_cursor.next_page, resumed.next_cursor.state) == (3, "complete")
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
+        resumed_run = connection.execute(
+            "SELECT requested_start_page FROM ingestion_runs WHERE run_id = ?",
+            (resumed.run_id,),
+        ).fetchone()
+        assert resumed_run["requested_start_page"] == 2
+    finally:
+        connection.close()
+
+
+def test_rate_limited_page_keeps_cursor_and_ends_run_risk_interrupted(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_page(
+        1, _page(1, _summary("BV1KEPT", aid=701), observed_total=2)
+    )
+    gateway.script_page(2, GatewayRateLimited(detail="get_user_video_page"))
+    gateway.script_parts("BV1KEPT", (_part("BV1KEPT", 0, cid=701),))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        ingestor = _ingestor(gateway, repository)
+        first = ingestor.collect_user_pages(MID, page_limit=1)
+        cursor_before = repository.read_cursor(MID)
+        assert cursor_before is not None
+
+        interrupted = ingestor.collect_user_pages(MID)
+
+        assert interrupted.outcome == "risk_interrupted"
+        assert interrupted.error_code == "rate_limited"
+        assert interrupted.page_count == 1
+        assert interrupted.video_count == 0
+        assert interrupted.part_count == 0
+        assert repository.read_cursor(MID) == cursor_before
+        interrupted_run = connection.execute(
+            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
+            (interrupted.run_id,),
+        ).fetchone()
+        assert interrupted_run["outcome"] == "risk_interrupted"
+        assert interrupted_run["finished_at"] is not None
+        page_row = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ? ORDER BY page_number",
+            (interrupted.run_id,),
+        ).fetchone()
+        assert tuple(page_row) == (2, "risk_interrupted", "rate_limited")
+    finally:
+        connection.close()
+
+
+def test_foreign_owner_summary_fails_the_page_before_parts_are_requested(tmp_root):
+    """D3: part requests only target summaries owned by the requested mid."""
+
+    gateway = FakeGateway()
+    gateway.script_page(
+        1, _page(1, _summary("BV1FOREIGN", aid=801, owner_mid=MID + 1))
+    )
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID)
+
+        assert result.outcome == "failed"
+        assert result.error_code == "shape_error"
+        # No parts request and no detail call for a foreign-owned summary.
+        assert gateway.parts_calls == []
+        assert gateway.completion_calls == []
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
+        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
+        assert (
+            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
+            == 0
+        )
+        assert repository.read_cursor(MID) is None
+        page_row = connection.execute(
+            "SELECT page_number, outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ? ORDER BY page_number",
+            (result.run_id,),
+        ).fetchone()
+        assert tuple(page_row) == (1, "failed", "shape_error")
+    finally:
+        connection.close()
+
+
+def test_missing_aid_is_completed_through_the_gateway_without_speculation(tmp_root):
+    gateway = FakeGateway()
+    gateway.script_completion("BV1NEEDS", _summary("BV1NEEDS", aid=901))
+    gateway.script_page(
+        1,
+        _page(
+            1,
+            _summary("BV1NEEDS", aid=None),
+            _summary("BV1HAS", aid=912, title="已有编号视频"),
+            observed_total=2,
+        ),
+    )
+    gateway.script_page(2, _page(2, observed_total=2))
+    gateway.script_parts("BV1NEEDS", (_part("BV1NEEDS", 0, cid=911),))
+    gateway.script_parts("BV1HAS", (_part("BV1HAS", 0, cid=912),))
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        result = _ingestor(gateway, repository).collect_user_pages(MID)
+
+        # Only the aid-less summary is completed; the known aid is never
+        # refetched (zero speculative detail calls).
+        assert gateway.completion_calls == ["BV1NEEDS"]
+        stored = dict(connection.execute("SELECT bvid, aid FROM videos").fetchall())
+        assert stored == {"BV1NEEDS": 901, "BV1HAS": 912}
+        assert result.outcome == "complete"
+        assert result.video_count == 2
+    finally:
+        connection.close()
+
+
+@pytest.mark.parametrize(
+    ("kwargs", "expected"),
+    [
+        ({"mid": 0}, ValueError),
+        ({"mid": True}, TypeError),
+        ({"mid": "23191782"}, TypeError),
+        ({"mid": MID, "start_page": 0}, ValueError),
+        ({"mid": MID, "start_page": True}, TypeError),
+        ({"mid": MID, "page_limit": 0}, ValueError),
+        ({"mid": MID, "page_limit": -1}, ValueError),
+        ({"mid": MID, "page_limit": True}, TypeError),
+    ],
+)
+def test_collect_arguments_are_validated(kwargs, expected):
+    with pytest.raises(expected):
+        MetadataIngestor(FakeGateway(), MetadataRepository(open_database(":memory:"))).collect_user_pages(
+            **kwargs
+        )
```
