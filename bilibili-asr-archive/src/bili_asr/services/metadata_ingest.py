"""Resumable normalized metadata ingestion between gateway and repository.

:class:`MetadataIngestor` owns pagination, the resumable cursor, and the
run/page transaction flow.  Every page is fetched through the typed
:class:`BilibiliGateway` protocol and persisted through the Plan-1
repository's canonical methods in exactly one committed transaction per
page: upsert user (when the run has observed a name to write), upsert
videos, upsert parts, insert discoveries, update the cursor, record the
page outcome, commit.

The service is synchronous on its surface (the CLI calls it directly) and
runs the async gateway page calls on one event loop per collection run.
Gateway failures roll the failed page back completely and persist only its
bounded scalar error code.  The previous cursor is preserved so a later run
can resume from the same page — with one opt-in exception:
``--skip-failed-page`` commits it one page past a failed page so the next
``--resume`` can progress, leaving the failed page row and its code in place
so the gap stays visible.  It skips every non-rate-limit gateway failure,
transient ones included; a rate limit is never skipped.
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
    VideoTag,
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
    VideoDetailRecord,
    VideoPartRecord,
    VideoRecord,
    VideoTagRecord,
)

SOURCE_PACKAGE = "bilibili-api-python"
#: Shipped page size of the user-video page call.  Upstream answers ``ps=100``
#: with its bounded ``-400``/HTTP 412 rejection while 30 — the pinned
#: package's own documented value — returns ``code=0``, so the shipped default
#: stays inside the bound upstream accepts.
PAGE_SIZE = 30


def _now() -> int:
    """Return the current Unix second used for all persisted clocks."""

    return int(time.time())


def _observed_tag_sets(
    summaries: list[VideoSummary],
    tags_by_video: dict[str, tuple[VideoTag, ...] | None],
) -> dict[str, list[VideoTagRecord]]:
    """Return this page's observed tag sets, keyed by bvid.

    Only the videos on *this* page are written, even though the cache is
    run-scoped: a page's transaction persists that page's observations.  A
    bvid repeated on the page collapses to one set, the same way its parts and
    its video row do.

    **The two empty answers are kept apart here, which is where it matters**
    (compass **D16**, 2026-09-27).  ``tags_by_video`` maps a bvid to ``None``
    when the tag call could not read this time (risk control, transport
    failure) and to a tuple — possibly empty — when it did read.  A ``None``
    entry **omits the bvid key** rather than contributing an empty list: the
    absent key is what ``record_page`` treats as "no news", so nothing is
    written for that video and the rows a previous run stored survive.  A
    present key with an empty list is the *observation* that the video carries
    no tags, and still replaces the stored set with nothing — that is AC 3's
    "a second run of the same bvid replaces the set rather than appending",
    and ``upsert_video_tags``' own docstring is the contract for it.

    The distinction cannot be made one layer down: once both answers have been
    flattened into an empty list, ``upsert_video_tags`` has nothing left to
    tell them apart, and "never delete on an empty set" would destroy the
    genuine clear instead of protecting it.
    """

    sets: dict[str, list[VideoTagRecord]] = {}
    for summary in summaries:
        observed = tags_by_video.get(summary.bvid)
        if observed is None:
            # The call could not read this time: write nothing for this video
            # rather than clearing a set a previous run observed.  ``continue``
            # leaves the key out, which is the shape ``record_page`` reads as
            # "no news" (D16).
            continue
        sets[summary.bvid] = [
            VideoTagRecord(
                bvid=summary.bvid,
                tag_id=tag.tag_id,
                tag_name=tag.tag_name,
                tag_type=tag.tag_type,
            )
            for tag in observed
        ]
    return sets


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


def _user_record(mid: int, moment: int, author: str | None) -> UserRecord:
    """Build the collected user's current display label.

    ``author`` is the uploader name the caller observed upstream; ``None`` is
    the explicit "this run observed no name" case and resolves to the owner-mid
    placeholder.  The parameter is required — not defaulted — so every call
    site has to say which of the two it is: a default would let a call that
    observed nothing look identical to one that forgot to pass the name it
    holds, which is exactly the call-site confusion that let the opening write
    overwrite an established label (see :meth:`MetadataIngestor._collect`).

    The placeholder is honest — the archive knows the account it collected and
    nothing else — while inventing a label the page never carried would not be.
    """

    return UserRecord(
        mid=mid,
        display_name=str(mid) if author is None else author,
        created_at=moment,
        updated_at=moment,
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
        *,
        skip_failed_page: bool = False,
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
            self._collect(
                mid=mid,
                start_page=start_page,
                page_limit=page_limit,
                skip_failed_page=skip_failed_page,
            )
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
        self,
        mid: int,
        start_page: int | None,
        page_limit: int | None,
        skip_failed_page: bool = False,
    ) -> IngestionRunResult:
        """Fetch and persist pages until completion, a limit, or a failure."""

        started_at = _now()
        with self._repository.transaction():
            # Establish the user row the run and cursor foreign keys need,
            # without rewriting one: this write happens before any page is
            # fetched, so it has observed no name, and the owner-mid placeholder
            # it carries may only ever be the value a row is *created* with.
            # The name a page does carry reaches the row through the page
            # transaction below, which upserts and overwrites.
            self._repository.ensure_user(_user_record(mid, started_at, author=None))
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
        # The run's own observation of the uploader's display name, taken from
        # the first summary that carries one.  Run-scoped rather than
        # page-scoped: a later page that omits the author must not reset a label
        # an earlier page already answered.  A run that observed none writes no
        # user row at all, so the stored label keeps the value the last
        # observing run gave it (or the placeholder the row was created with).
        observed_author: str | None = None
        # The run's tag observations, keyed by bvid.  Run-scoped rather than
        # page-scoped, because the tag set is a property of the video: a video
        # that somehow appears on two pages must not pay for the same call
        # twice, and the fetch is deliberately per video rather than per part.
        # A value of ``None`` is the gateway's "could not read this time" and
        # is cached as such: a page whose payload is built from it omits the
        # bvid's tag set rather than writing an empty one, so a degraded fetch
        # cannot clear tags an earlier run stored (compass D16).  An empty
        # tuple is a *different* answer — read, and the video carries none —
        # and does replace the stored set with nothing.
        tags_by_video: dict[str, tuple[VideoTag, ...] | None] = {}
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
                if observed_author is None:
                    observed_author = next(
                        (
                            summary.author
                            for summary in summaries
                            if summary.author is not None
                        ),
                        None,
                    )
                parts_by_video: dict[str, tuple[VideoPart, ...]] = {}
                for summary in summaries:
                    # One parts fetch per distinct video: a duplicated page
                    # entry is the same video, so the identical fetch would
                    # only repeat upstream work.
                    if summary.bvid not in parts_by_video:
                        parts_by_video[summary.bvid] = (
                            await self._gateway.get_video_parts(summary.bvid)
                        )
                for summary in summaries:
                    # One tag fetch per distinct VIDEO, run-scoped: the tag set
                    # belongs to the video, so a per-part fetch would pay once
                    # per part and a repeated bvid would pay again.  The call
                    # itself degrades inside the gateway rather than raising,
                    # so a risk-controlled tag fetch cannot fail the page; it
                    # answers ``None`` for that case and the payload builder
                    # omits the bvid rather than writing an empty set (D16).
                    if summary.bvid not in tags_by_video:
                        tags_by_video[summary.bvid] = (
                            await self._gateway.get_video_tags(summary.bvid)
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
                if skip_failed_page and page_outcome == "failed":
                    # The escape hatch (D-3).  A page whose outcome mapped to
                    # 'failed' is skipped: for the shape errors that motivated
                    # this flag the failure is deterministic and resuming at it
                    # would fail identically on every later run, and for the
                    # transport/response classes the same mapping applies even
                    # though they can be transient (recovery from a hasty skip
                    # is --start-page or a cursor reset).  The run's own outcome
                    # is untouched — it really did fail, and
                    # ``_record_failed_page`` has already made it terminal with
                    # the page row above as its evidence.  Only the *next* run's
                    # starting point changes, which is what makes the wedge
                    # escapable rather than permanent.
                    #
                    # ``risk_interrupted`` is excluded on purpose: a rate limit is
                    # transient and the existing behaviour (stop, keep the cursor)
                    # is the correct one for it.
                    previous = self._repository.read_cursor(mid)
                    # The cursor write is its own committed transaction, the
                    # module's one write-group discipline: ``write_cursor`` does
                    # not commit on its own, and the CLI closes the connection
                    # (``cli/meta.py`` ``finally``) as soon as the command
                    # returns, which would roll an uncommitted cursor back and
                    # leave the very wedge this flag exists to escape.
                    with self._repository.transaction():
                        self._repository.write_cursor(
                            CursorRecord(
                                mid=mid,
                                next_page=page_number + 1,
                                observed_total=(
                                    previous.observed_total
                                    if previous is not None
                                    else None
                                ),
                                state="ready",
                                last_error_code=error.code,
                                updated_at=_now(),
                            )
                        )
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
                observed_author,
                _observed_tag_sets(summaries, tags_by_video),
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
        author: str | None,
        tags: dict[str, list[VideoTagRecord]],
    ) -> None:
        """Record one collected page with its payload in the locked order.

        The repository's ``record_page`` applies the Plan-1 order — user,
        videos, parts, tag sets, details, discoveries, cursor, page outcome —
        inside one transaction and commits it.  Duplicate summary entries
        collapse into their existing entity rows through the upsert keys, and a
        bvid duplicated within one page keeps the last occurrence's
        ``source_position``: the discovery primary key
        ``(run_id, page_number, bvid)`` makes the later entry overwrite the
        earlier one.  ``author`` is the run's observed uploader name and only
        feeds the user row: it is not a video fact, so it never reaches a
        summary or a part record.  ``None`` means this run has not observed a
        name, and then no user row is written at all — the run-start
        ``ensure_user`` already satisfies the run and cursor foreign keys, so a
        page carrying no observation leaves the stored label and its stamp
        alone rather than restamping the placeholder over them.

        Every summary contributes a ``VideoDetailRecord``, including the ones
        that observed none of ``pic``/``desc``/``tid``: those carry three
        ``None``s, and the D15 rule that decides what to do with them lives in
        ``upsert_video_details``, so the "observed nothing" case stays one rule
        in one place rather than being re-derived by filtering here.
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
        detail_records = [
            VideoDetailRecord(
                bvid=summary.bvid,
                pic=summary.pic,
                desc=summary.desc,
                tid=summary.tid,
                observed_at=finished_at,
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
        # A page whose run has observed no name yet writes no user row at all:
        # ``record_page`` upserts, so handing it the owner-mid placeholder would
        # replace a stored label with a value this run never saw.  The run-start
        # write already established the row the run and cursor foreign keys
        # need, so nothing else has to.  Compass D15's rule, applied to this
        # column: a collection that observed nothing moves neither the row nor
        # its ``updated_at`` stamp.
        user_record = None if author is None else _user_record(mid, finished_at, author)
        self._repository.record_page(
            IngestionPageRecord(
                run_id=run_id,
                page_number=page_number,
                outcome="ok",
                error_code=None,
                started_at=started_at,
                finished_at=finished_at,
            ),
            user=user_record,
            videos=video_records,
            parts=part_records,
            discoveries=discovery_records,
            tags=tags,
            details=detail_records,
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
