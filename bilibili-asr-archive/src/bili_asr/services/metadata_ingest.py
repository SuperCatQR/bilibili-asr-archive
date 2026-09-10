"""Resumable normalized metadata ingestion between gateway and repository.

:class:`MetadataIngestor` owns pagination, the resumable cursor, and the
run/page transaction flow.  Every page is fetched through the typed
:class:`BilibiliGateway` protocol and persisted through the Plan-1
repository's canonical methods in exactly one committed transaction per
page: upsert user, upsert videos, upsert parts, insert discoveries, update
the cursor, record the page outcome, commit.

The service is synchronous on its surface (the CLI calls it directly) and
runs the async gateway page calls on one event loop per collection run.
Gateway failures roll the failed page back completely; only a bounded scalar
error code is persisted afterwards, and the previous cursor is preserved
exactly so a later run can resume from it.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from bili_asr.sources.models import (
    BilibiliGateway,
    GatewayError,
    GatewayRateLimited,
    GatewayShapeError,
    VideoPart,
    VideoSummary,
)
from bili_asr.storage.database import MetadataRepository
from bili_asr.storage.models import (
    CursorRecord,
    DiscoveryRecord,
    IngestionPageRecord,
    IngestionRunRecord,
    PageOutcome,
    RunOutcome,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
)

SOURCE_PACKAGE = "bilibili-api-python"
PAGE_SIZE = 100


def _now() -> int:
    """Return the current Unix second used for all persisted clocks."""

    return int(time.time())


def _page_and_run_outcomes(error: GatewayError) -> tuple[PageOutcome, RunOutcome]:
    """Map a bounded gateway failure onto page and run outcomes.

    Upstream rate control is a bounded risk signal: the page is recorded
    ``risk_interrupted`` and the run ends ``risk_interrupted``, still
    resumable from the untouched cursor.  Every other gateway failure is
    terminal for the run and the page.
    """

    if isinstance(error, GatewayRateLimited):
        return "risk_interrupted", "risk_interrupted"
    return "failed", "failed"


def _run_record(
    run_id: str,
    mid: int,
    source_version: str,
    requested_start_page: int,
    requested_page_limit: int | None,
    started_at: int,
    outcome: RunOutcome = "running",
    finished_at: int | None = None,
) -> IngestionRunRecord:
    """Build the run record used for one collection run's start or finish."""

    return IngestionRunRecord(
        run_id=run_id,
        mid=mid,
        source_package=SOURCE_PACKAGE,
        source_version=source_version,
        requested_start_page=requested_start_page,
        requested_page_limit=requested_page_limit,
        started_at=started_at,
        outcome=outcome,
        finished_at=finished_at,
    )


def _user_record(mid: int, moment: int) -> UserRecord:
    """Build the collected user's current display label.

    The gateway DTO contract carries no display-name field, so the current
    label is the owner mid; a gateway method that exposes the display name
    changes only this helper.
    """

    return UserRecord(
        mid=mid, display_name=str(mid), created_at=moment, updated_at=moment
    )


@dataclass(frozen=True, slots=True)
class IngestionRunResult:
    """Terminal evidence of one metadata collection run.

    ``outcome`` is the run's terminal outcome (never ``running``) and
    ``error_code`` carries the bounded scalar failure code when the run ended
    ``risk_interrupted`` or ``failed``.  ``next_cursor`` is the cursor as it
    is stored after the run.  ``page_count`` counts the page-evidence rows the
    run wrote, including interrupted or failed pages, matching
    ``v_ingestion_run_stats``; ``video_count`` counts the distinct videos the
    run discovered; ``part_count`` counts the distinct parts the run upserted
    (part rows are not run-scoped, so this count reflects upsert coverage).
    """

    run_id: str
    mid: int
    outcome: RunOutcome
    next_cursor: CursorRecord | None
    page_count: int
    video_count: int
    part_count: int
    error_code: str | None


class MetadataIngestor:
    """Collect one user's video pages into normalized repository records.

    The ingestor starts from the caller's ``start_page`` when given, else
    from the stored cursor's ``next_page``, else from page 1, and stops at
    the first empty page (natural completion), the explicit ``page_limit``
    (outcome ``limited`` — never claimed as complete), or a bounded gateway
    failure (outcome ``risk_interrupted`` or ``failed``).  An empty page
    completes the collection even when it happens to be the page that an
    explicit limit would have stopped on, because nothing was cut short.
    """

    def __init__(self, gateway: BilibiliGateway, repository: MetadataRepository) -> None:
        self._gateway = gateway
        self._repository = repository

    def collect_user_pages(
        self,
        mid: int,
        start_page: int | None = None,
        page_limit: int | None = None,
    ) -> IngestionRunResult:
        """Run one resumable metadata collection for ``mid``.

        ``start_page`` overrides the stored cursor's ``next_page`` when given
        (a run may also move the cursor backwards by explicit request);
        ``page_limit`` bounds how many pages this run may collect.  The run
        row carries the resolved bounds and the gateway's package version.

        Any exception that is not a bounded gateway failure (for example a
        caller-argument ``ValueError`` raised by the gateway) propagates
        unchanged: those are programming or contract errors, not collection
        evidence.
        """

        self._validate_arguments(mid, start_page, page_limit)
        return asyncio.run(
            self._collect(mid=mid, start_page=start_page, page_limit=page_limit)
        )

    @staticmethod
    def _validate_arguments(
        mid: int, start_page: int | None, page_limit: int | None
    ) -> None:
        """Reject caller-argument violations before any gateway call."""

        if isinstance(mid, bool) or not isinstance(mid, int):
            raise TypeError("mid must be an integer")
        if mid < 1:
            raise ValueError("mid must be a positive integer")
        if start_page is not None:
            if isinstance(start_page, bool) or not isinstance(start_page, int):
                raise TypeError("start_page must be an integer or None")
            if start_page < 1:
                raise ValueError("start_page must be a positive integer")
        if page_limit is not None:
            if isinstance(page_limit, bool) or not isinstance(page_limit, int):
                raise TypeError("page_limit must be a positive integer or None")
            if page_limit < 1:
                raise ValueError("page_limit must be a positive integer")

    def _resume_page(self, mid: int) -> int:
        """Return the stored cursor's next page, or page 1 when absent."""

        cursor = self._repository.read_cursor(mid)
        return 1 if cursor is None else cursor.next_page

    async def _collect(
        self, mid: int, start_page: int | None, page_limit: int | None
    ) -> IngestionRunResult:
        """Fetch and persist pages until completion, a limit, or a failure."""

        started_at = _now()
        with self._repository.transaction():
            self._repository.upsert_user(_user_record(mid, started_at))
        first_page = start_page if start_page is not None else self._resume_page(mid)
        source_version = self._gateway.get_package_version()
        run_id = uuid.uuid4().hex
        self._repository.start_run(
            _run_record(
                run_id, mid, source_version, first_page, page_limit, started_at
            )
        )

        page_count = 0
        discovered_videos: set[str] = set()
        upserted_parts: set[tuple[str, int]] = set()
        outcome: RunOutcome = "complete"
        error_code: str | None = None
        page_number = first_page
        while True:
            page_started_at = _now()
            try:
                page = await self._gateway.get_user_video_page(
                    mid, page_number, PAGE_SIZE
                )
                completed_by_video: dict[str, VideoSummary] = {}
                summaries: list[VideoSummary] = []
                for summary in page.videos:
                    # One detail fetch per distinct video: a duplicated page
                    # entry is the same video, so the identical fetch would
                    # only repeat upstream work.
                    if summary.bvid not in completed_by_video:
                        completed_by_video[summary.bvid] = (
                            await self._completed_summary(summary, mid)
                        )
                    summaries.append(completed_by_video[summary.bvid])
                parts_by_video: dict[str, tuple[VideoPart, ...]] = {}
                for summary in summaries:
                    # One parts fetch per distinct video: a duplicated page
                    # entry is the same video, so the identical fetch would
                    # only repeat upstream work.
                    if summary.bvid not in parts_by_video:
                        parts_by_video[summary.bvid] = (
                            await self._gateway.get_video_parts(summary.bvid)
                        )
            except GatewayError as error:
                page_outcome, run_outcome = _page_and_run_outcomes(error)
                self._repository.record_page(
                    IngestionPageRecord(
                        run_id=run_id,
                        page_number=page_number,
                        outcome=page_outcome,
                        error_code=error.code,
                        started_at=page_started_at,
                        finished_at=_now(),
                    )
                )
                outcome = run_outcome
                error_code = error.code
                page_count += 1
                break
            page_finished_at = _now()
            if not summaries:
                self._record_empty_page(
                    run_id,
                    mid,
                    page_number,
                    page_started_at,
                    page_finished_at,
                    page.observed_total,
                )
                page_count += 1
                outcome = "complete"
                break
            limit_reached = page_limit is not None and page_count + 1 >= page_limit
            self._record_collected_page(
                run_id,
                mid,
                page_number,
                summaries,
                parts_by_video,
                page_started_at,
                page_finished_at,
                page.observed_total,
                limit_reached,
            )
            page_count += 1
            discovered_videos.update(summary.bvid for summary in summaries)
            for parts in parts_by_video.values():
                upserted_parts.update(
                    (part.bvid, part.page_index) for part in parts
                )
            if limit_reached:
                outcome = "limited"
                break
            page_number += 1

        if outcome != "failed":
            # The failed run already finished atomically inside record_page.
            # Every other outcome finishes here as its own terminal commit.
            self._repository.finish_run(
                _run_record(
                    run_id,
                    mid,
                    source_version,
                    first_page,
                    page_limit,
                    started_at,
                    outcome=outcome,
                    finished_at=_now(),
                )
            )
        return IngestionRunResult(
            run_id=run_id,
            mid=mid,
            outcome=outcome,
            next_cursor=self._repository.read_cursor(mid),
            page_count=page_count,
            video_count=len(discovered_videos),
            part_count=len(upserted_parts),
            error_code=error_code,
        )

    async def _completed_summary(self, summary: VideoSummary, mid: int) -> VideoSummary:
        """Return the summary with its aid filled when the page omitted it.

        The gateway validates every summary's owner mid against the requested
        user at the page boundary; this second guard keeps transitive part
        ownership enforced ingestor-side even if a gateway implementation
        ever returned a foreign summary, and it fires before any detail
        fetch so no call is ever made for a video that failed the ownership
        check.
        """

        if summary.mid != mid:
            raise GatewayShapeError(
                detail="summary owner does not match the requested user"
            )
        if summary.aid is None:
            return await self._gateway.get_completed_video_summary(summary)
        return summary

    def _record_empty_page(
        self,
        run_id: str,
        mid: int,
        page_number: int,
        started_at: int,
        finished_at: int,
        observed_total: int | None,
    ) -> None:
        """Record the empty page and the completing cursor in one commit.

        The cursor keeps ``next_page`` at the empty page itself: nothing was
        cut short, and a later resume from this page would re-verify the
        completion idempotently.
        """

        self._repository.record_page(
            IngestionPageRecord(
                run_id=run_id,
                page_number=page_number,
                outcome="empty",
                error_code=None,
                started_at=started_at,
                finished_at=finished_at,
            ),
            cursor=CursorRecord(
                mid=mid,
                next_page=page_number,
                observed_total=observed_total,
                state="complete",
                last_error_code=None,
                updated_at=finished_at,
            ),
        )

    def _record_collected_page(
        self,
        run_id: str,
        mid: int,
        page_number: int,
        summaries: list[VideoSummary],
        parts_by_video: dict[str, tuple[VideoPart, ...]],
        started_at: int,
        finished_at: int,
        observed_total: int | None,
        limit_reached: bool,
    ) -> None:
        """Record one collected page with its payload in the locked order.

        The repository's ``record_page`` applies the Plan-1 order — user,
        videos, parts, discoveries, cursor, page outcome — inside one
        transaction and commits it.  Duplicate summary entries collapse into
        their existing entity rows through the upsert keys, and a bvid
        duplicated within one page keeps the last occurrence's
        ``source_position``: the discovery primary key
        ``(run_id, page_number, bvid)`` makes the later entry overwrite the
        earlier one.
        """

        video_records = [
            VideoRecord(
                bvid=summary.bvid,
                aid=summary.aid,
                mid=summary.mid,
                title=summary.title,
                pubdate=summary.pubdate,
                created_at=finished_at,
                updated_at=finished_at,
            )
            for summary in summaries
        ]
        part_records = [
            VideoPartRecord(
                bvid=part.bvid,
                page_index=part.page_index,
                cid=part.cid,
                title=part.title,
                duration_ms=part.duration_ms,
                processing_status="discovered",
                created_at=finished_at,
                updated_at=finished_at,
            )
            for parts in parts_by_video.values()
            for part in parts
        ]
        discovery_records = [
            DiscoveryRecord(
                run_id=run_id,
                page_number=page_number,
                bvid=summary.bvid,
                source_position=position,
                discovered_at=finished_at,
            )
            for position, summary in enumerate(summaries)
        ]
        self._repository.record_page(
            IngestionPageRecord(
                run_id=run_id,
                page_number=page_number,
                outcome="ok",
                error_code=None,
                started_at=started_at,
                finished_at=finished_at,
            ),
            user=_user_record(mid, finished_at),
            videos=video_records,
            parts=part_records,
            discoveries=discovery_records,
            cursor=CursorRecord(
                mid=mid,
                next_page=page_number + 1,
                observed_total=observed_total,
                state="limited" if limit_reached else "ready",
                last_error_code=None,
                updated_at=finished_at,
            ),
        )


__all__ = ["IngestionRunResult", "MetadataIngestor", "PAGE_SIZE", "SOURCE_PACKAGE"]
