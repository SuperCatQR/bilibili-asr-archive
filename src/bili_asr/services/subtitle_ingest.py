"""Bounded subtitle acquisition between source ports and transcript storage.

:class:`SubtitleIngestor` owns candidate enumeration, track selection, per-part
transactions, run records and bounded outcome mapping.  Runtime callers can
inject the application-owned ``SubtitleSource`` port.  Existing Bilibili
gateway callers use a compatibility adapter resolved from already-read part
rows, with no additional database lookup or raw upstream response dictionaries.

The surface is synchronous and runs the source's asynchronous calls on one
event loop per operation.  ``probe`` writes no run, attempt, transcript or file.
``harvest`` creates one acquisition run, records one attempt per part in a
separate transaction, and finishes with the attempts' aggregate outcome.

An empty selection or a listing's bounded ``not_found`` yields ``no-subtitle``;
only an observed credentialed verification can establish trusted absence for
the current Bilibili policy.  A fetched body yields ``stored`` or ``unchanged``.
Unrepresentable timelines yield one part's bounded ``shape_error`` failure.
Other gateway failures yield ``failed`` with their scalar error code.  A body
that disappears after listing remains a failure rather than absence evidence.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
import sqlite3
from typing import Callable
import uuid

from bili_asr.services._common import _now
from bili_asr.transcript_selection import LANGUAGE_FAMILY_ORDER, language_family

from bili_asr.page_identity import format_work_id
from bili_asr.platform_identity import ContentRef
from bili_asr.sources.bilibili_source import BilibiliSubtitleSource
from bili_asr.sources.models import (
    BilibiliGateway,
    GatewayError,
    GatewayNotFound,
    GatewayResponseError,
    GatewayShapeError,
    SubtitleSegment,
    SubtitleTrack,
)
from bili_asr.sources.protocols import SubtitleSource
from bili_asr.storage.transcripts import TranscriptRepository
from bili_asr.storage.models import (
    ALLOWED_ACQUISITION_KINDS,
    ALLOWED_CAPTION_SOURCE_KINDS,
    AcquisitionRunRecord,
    TranscriptSegmentRecord,
)

#: The acquisition kind every run of this service records.
_ACQUISITION_KIND = "subtitle"
#: The stored source kind of one selected track, by its machine-generated flag.
_SOURCE_KIND_BY_AI = {True: "subtitle-ai", False: "subtitle-cc"}
#: The attempt outcomes this service records, as the storage vocabulary spells
#: them.  ``stored``/``unchanged`` come back from the transcript write; the other
#: two are the outcomes of an attempt that produced no transcript, and ``failed``
#: is also the outcome a run unfinished by an unexpected error is closed with.
_OUTCOME_STORED = "stored"
_OUTCOME_UNCHANGED = "unchanged"
_OUTCOME_NO_SUBTITLE = "no-subtitle"
_OUTCOME_FAILED = "failed"
#: The default language family order the selection preference ranks by.
_DEFAULT_LANGUAGE_FAMILY_ORDER = LANGUAGE_FAMILY_ORDER


def _choice(value: str, field: str, allowed: frozenset[str]) -> str:
    """Return ``value`` when the published storage vocabulary admits it.

    The service derives the two vocabulary values it writes — the caption
    ``source_kind`` of one selected track and the acquisition ``kind`` of one
    run — instead of passing storage literals through, and validates each of them
    against the enum the storage contract publishes.  A drift between the two
    vocabularies therefore fails here with a bounded message instead of
    surfacing as a SQLite ``CHECK`` violation in the middle of a run.
    """

    if value not in allowed:
        raise ValueError(f"{field} is not part of the storage vocabulary: {value}")
    return value


def _caption_source_kind(is_ai: bool) -> str:
    """Return the stored source kind of one selected track, validated."""

    return _choice(
        _SOURCE_KIND_BY_AI[is_ai], "source_kind", ALLOWED_CAPTION_SOURCE_KINDS
    )


def _family_rank(family: str) -> int:
    """Return one family's rank in the default order; the rest share the last."""

    try:
        return _DEFAULT_LANGUAGE_FAMILY_ORDER.index(family)
    except ValueError:
        return len(_DEFAULT_LANGUAGE_FAMILY_ORDER)


def select_subtitle_track(
    tracks: tuple[SubtitleTrack, ...], languages: tuple[str, ...] = ()
) -> SubtitleTrack | None:
    """Select exactly one track of a part, or ``None`` when none is usable.

    Without ``languages`` the default preference applies: the default language
    family order first (``zh``, then ``en``, then every other family in upstream
    order), and inside one family an uploader caption before a machine-generated
    one.  That is the total order ``(family rank, is_ai, upstream index)`` taken
    at its minimum — the first track a stable sort on the same key would yield —
    so the shipped legacy preference (AI first) is deliberately replaced and the
    uploader caption wins whenever both are visible.

    With ``languages`` each entry is matched exactly against a track's
    ``language`` code — the code ``probe-subs`` prints — the first preference
    that matches anything wins, and the tracks it matches are ranked the same
    way (CC before AI, then upstream order).  ``None`` then means nothing usable
    for any requested language was visible, never a failure.
    """

    if not tracks:
        return None
    if languages:
        for preference in languages:
            matching = [
                (index, track)
                for index, track in enumerate(tracks)
                if track.language == preference
            ]
            if matching:
                return min(matching, key=lambda pair: (pair[1].is_ai, pair[0]))[1]
        return None
    return min(
        enumerate(tracks),
        key=lambda pair: (
            _family_rank(language_family(pair[1].language, pair[1].is_ai)),
            pair[1].is_ai,
            pair[0],
        ),
    )[1]


@dataclass(frozen=True, slots=True)
class SubtitleSelection:
    """One bounded selection of archive parts to inspect or acquire.

    ``bvid`` alone selects every part of that video already in the database
    (including parts that already hold a transcript — that is how a caption
    upstream has since added or revised is re-checked); ``bvid`` together with
    ``page_index`` selects exactly that part, using the archive's own
    ``bvid:pN`` vocabulary; ``bvid=None`` selects the pending enumeration.
    ``limit`` bounds the selection and is required unless ``page_index`` names
    one part, which is bounded by construction.  ``languages`` is empty for the
    default preference and otherwise the exact preference order.
    """

    bvid: str | None = None
    page_index: int | None = None
    limit: int | None = None
    languages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SubtitleProbePart:
    """What one probed part exposed: its tracks, or the bounded failure code."""

    work_id: str
    tracks: tuple[SubtitleTrack, ...]
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """The read-only probe's evidence: credential presence and one entry per part."""

    credential_present: bool
    parts: tuple[SubtitleProbePart, ...]


@dataclass(frozen=True, slots=True)
class SubtitlePartOutcome:
    """The one outcome one attempted part produced, with its bounded evidence."""

    work_id: str
    outcome: str
    error_code: str | None
    source_kind: str | None
    language: str | None
    version: int | None


@dataclass(frozen=True, slots=True)
class HarvestResult:
    """One run's counting evidence: every number the summary line prints."""

    run_id: str
    attempted: int
    stored: int
    unchanged: int
    no_subtitle: int
    failed: int
    credential_present: bool
    remaining_without_transcript: int
    parts: tuple[SubtitlePartOutcome, ...]


@dataclass(frozen=True, slots=True)
class _SubtitleWorkItem:
    """One normalized unit of subtitle work.

    The two repository selections answer two different row shapes — the pending
    view carries ``bvid`` and ``cid``, the selected-parts view carries neither
    ``bvid`` — so the service normalizes both into this one shape before any
    gateway call: the gateway needs ``(bvid, cid)``, the transcript write needs
    ``video_part_id``, and ``work_id`` is the identity every printed line uses.
    """

    work_id: str
    bvid: str
    cid: int
    video_part_id: int
    page_index: int

    @property
    def content_ref(self) -> ContentRef:
        return ContentRef("bilibili", self.bvid, self.page_index)


def _pending_work_item(row: sqlite3.Row) -> _SubtitleWorkItem:
    """Normalize one ``v_pending_subtitles`` row, which carries ``bvid``/``cid``."""

    return _SubtitleWorkItem(
        work_id=str(row["work_id"]),
        bvid=str(row["bvid"]),
        cid=int(row["cid"]),
        video_part_id=int(row["video_part_id"]),
        page_index=int(row["page_index"]),
    )


def _selected_work_item(row: sqlite3.Row, bvid: str) -> _SubtitleWorkItem:
    """Normalize one ``v_video_parts`` row of an explicit selection.

    The selected-parts view carries no ``bvid`` column, so the caller's own
    selector supplies it; the ``work_id`` the view carries is the identity the
    row is already addressed by.
    """

    return _SubtitleWorkItem(
        work_id=str(row["work_id"]),
        bvid=bvid,
        cid=int(row["cid"]),
        video_part_id=int(row["video_part_id"]),
        page_index=int(row["page_index"]),
    )


def _selector(selection: SubtitleSelection) -> tuple[str, str | None]:
    """Return the run's ``(selector_kind, selector_target)`` as selected.

    The pending enumeration carries no target; an explicit selection records the
    operator's own selector — the bare ``bvid``, or the ``bvid:pN`` part that was
    named — so the run row says what was asked for, never more.
    """

    if selection.bvid is None:
        return "pending", None
    if selection.page_index is None:
        return "bvid", selection.bvid
    return "bvid", format_work_id(selection.bvid, selection.page_index)


class SubtitleIngestor:
    """Inspect and acquire one bounded selection of archive subtitle work.

    ``credential_present`` is the composition root's own observation that a
    SESSDATA was in effect for this run.  It is configuration, not a gateway
    dependency: the run row records it so an attempt recorded without a caption
    stays interpretable afterwards, and no display path ever carries the value.
    ``clock`` is the run/attempt timestamp source, in Unix seconds.
    """

    def __init__(
        self,
        gateway: BilibiliGateway | None,
        repository: TranscriptRepository,
        *,
        credential_present: bool = False,
        clock: Callable[[], int] = _now,
        checkpoint: Callable[[], None] | None = None,
        source: SubtitleSource | None = None,
    ) -> None:
        if gateway is None and source is None:
            raise ValueError("subtitle acquisition requires a source or Bilibili gateway")
        self._gateway = gateway
        self._source = source
        self._repository = repository
        self._credential_present = bool(credential_present)
        self._clock = clock
        self._checkpoint = checkpoint or (lambda: None)

    def _source_for(self, item: _SubtitleWorkItem) -> SubtitleSource:
        """Resolve existing Bilibili extensions only at the source boundary.

        The optional source is the explicit runtime port.  Existing callers
        injecting a gateway retain their API while each selected part's real
        cid is supplied by its already-read repository row, with no new query.
        """

        if self._source is not None:
            return self._source
        assert self._gateway is not None
        return BilibiliSubtitleSource(
            self._gateway,
            {item.content_ref: item.cid}.__getitem__,
            credential_present=self._credential_present,
        )

    def probe(self, selection: SubtitleSelection) -> ProbeResult:
        """List what each selected part exposes, writing nothing at all."""

        parts = asyncio.run(self._probe_parts(self._candidate_items(selection)))
        return ProbeResult(
            credential_present=self._credential_present,
            parts=parts,
        )

    def harvest(self, selection: SubtitleSelection) -> HarvestResult:
        """Acquire the selected parts and record one run with its per-part evidence.

        The run row is opened before the first part is attempted and finished
        with the outcome derived from the attempts (``complete`` when nothing
        failed, ``partial`` when failed and non-failed attempts coexist,
        ``failed`` when every attempt failed) — including a selection that
        resolved to no part at all, which is complete because nothing failed.  An
        unexpected error escaping a part finishes the opened run as ``failed``
        before it propagates, so a run is never left ``running``.
        """

        self._checkpoint()
        items = self._candidate_items(selection)
        selector_kind, selector_target = _selector(selection)
        run_id = uuid.uuid4().hex
        self._repository.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=run_id,
                kind=_choice(_ACQUISITION_KIND, "kind", ALLOWED_ACQUISITION_KINDS),
                selector_kind=selector_kind,
                selector_target=selector_target,
                requested_limit=selection.limit,
                credential_present=self._credential_present,
                started_at=self._clock(),
            )
        )
        try:
            outcomes = asyncio.run(
                self._acquire_parts(run_id, items, selection.languages)
            )
            self._repository.finish_acquisition_run(run_id, self._clock())
        except BaseException:
            self._finish_failed_run(run_id)
            raise
        counts = Counter(outcome.outcome for outcome in outcomes)
        return HarvestResult(
            run_id=run_id,
            attempted=len(outcomes),
            stored=counts[_OUTCOME_STORED],
            unchanged=counts[_OUTCOME_UNCHANGED],
            no_subtitle=counts[_OUTCOME_NO_SUBTITLE],
            failed=counts[_OUTCOME_FAILED],
            credential_present=self._credential_present,
            remaining_without_transcript=(
                self._repository.count_pending_subtitle_parts()
            ),
            parts=outcomes,
        )

    def _finish_failed_run(self, run_id: str) -> None:
        """Finish a run an unexpected error escaped, without masking that error.

        The run row must never be left ``running``, and the escaping exception is
        the bounded evidence the caller reports, so a failure to finish the row
        is deliberately not raised over it.
        """

        try:
            self._repository.finish_acquisition_run(
                run_id, self._clock(), outcome=_OUTCOME_FAILED
            )
        except Exception:
            pass

    def _candidate_items(
        self, selection: SubtitleSelection
    ) -> list[_SubtitleWorkItem]:
        """Return the selected parts in the locked enumeration order.

        An explicit ``bvid`` reads ``list_selected_parts`` and keeps every stored
        part of that video, already-transcribed ones included, bounded by
        ``limit`` when one was given.  The pending selection reads
        ``list_pending_subtitle_parts``: never-attempted parts before previously
        attempted ones, oldest attempt first, so successive bounded runs advance
        through the captionless backlog instead of re-attempting its head.
        """

        if selection.bvid is None:
            return [
                _pending_work_item(row)
                for row in self._repository.list_pending_subtitle_parts(
                    selection.limit
                )
            ]
        rows = self._repository.list_selected_parts(
            selection.bvid, selection.page_index
        )
        if selection.limit is not None:
            rows = rows[: selection.limit]
        return [_selected_work_item(row, selection.bvid) for row in rows]

    async def _probe_parts(
        self, items: list[_SubtitleWorkItem]
    ) -> tuple[SubtitleProbePart, ...]:
        """Probe every selected part in selection order."""

        return tuple([await self._probe_part(item) for item in items])

    async def _probe_part(self, item: _SubtitleWorkItem) -> SubtitleProbePart:
        """List one part's inventory; a bounded failure keeps its code on the part."""

        source = self._source_for(item)
        try:
            tracks = await source.list_tracks(item.content_ref)
            if not tracks and self._credential_present:
                await source.verify_access(item.content_ref)
        except GatewayError as error:
            return SubtitleProbePart(
                work_id=item.work_id, tracks=(), error_code=error.code
            )
        return SubtitleProbePart(work_id=item.work_id, tracks=tuple(tracks))

    async def _acquire_parts(
        self,
        run_id: str,
        items: list[_SubtitleWorkItem],
        languages: tuple[str, ...],
    ) -> tuple[SubtitlePartOutcome, ...]:
        """Acquire every selected part in selection order, one transaction each."""

        return tuple(
            [await self._acquire_part(run_id, item, languages) for item in items]
        )

    async def _acquire_part(
        self,
        run_id: str,
        item: _SubtitleWorkItem,
        languages: tuple[str, ...],
    ) -> SubtitlePartOutcome:
        """Acquire one part: list, select, fetch, store, record the attempt."""

        self._checkpoint()
        started_at = self._clock()
        source = self._source_for(item)
        try:
            tracks = await source.list_tracks(item.content_ref)
        except GatewayNotFound:
            return self._record_captionless_part(
                run_id, item, "not_found", started_at, absence_verified=True
            )
        except GatewayError as error:
            return self._record_failed_part(run_id, item, error, started_at)
        self._checkpoint()
        track = select_subtitle_track(tracks, languages)
        if track is None:
            # A cookie being present does not make this an authenticated
            # absence.  A failed login or unreadable validity check must not
            # become the empty-inventory proof used by the audio queue.
            try:
                access = await source.verify_access(item.content_ref)
                self._checkpoint()
            except GatewayError as error:
                return self._record_failed_part(run_id, item, error, started_at)
            return self._record_captionless_part(
                run_id, item, None, started_at,
                credential_verified=(
                    self._credential_present
                    and access.access_context == "credentialed"
                    and access.verified
                ),
            )
        try:
            segments = await source.fetch_segments(track, item.content_ref)
        except GatewayNotFound:
            # A listed track's body may disappear or be empty during retrieval.
            # That does not attest that the player has no usable subtitles.
            return self._record_failed_part(
                run_id, item, GatewayResponseError(code="subtitle_body_unavailable"), started_at
            )
        except GatewayError as error:
            return self._record_failed_part(run_id, item, error, started_at)
        self._checkpoint()
        return self._record_caption(run_id, item, track, segments, started_at)

    def _record_caption(
        self,
        run_id: str,
        item: _SubtitleWorkItem,
        track: SubtitleTrack,
        segments: tuple[SubtitleSegment, ...],
        started_at: int,
    ) -> SubtitlePartOutcome:
        """Store one selected track's body with its attempt evidence, atomically.

        The repository call is the whole per-part transaction: it appends a
        version with its segments when the content is new, records the attempt
        with the resulting ``stored``/``unchanged`` outcome, and commits — or
        rolls the whole call back.  The body is converted field for field, and
        the language is stored trimmed, so the reported language is the identity
        the store holds.  A body the storage boundary refuses with its bounded
        ``ValueError`` (a timeline position it cannot represent) is answered as
        this part's ``failed``/``shape_error`` outcome rather than an escaping
        error, so one anomalous part cannot end a bounded run.
        """

        finished_at = self._clock()
        source_kind = _caption_source_kind(track.is_ai)
        language = track.language.strip()
        try:
            write = self._repository.record_acquired_transcript(
                run_id=run_id,
                video_part_id=item.video_part_id,
                source_kind=source_kind,
                language=language,
                segments=tuple(
                    TranscriptSegmentRecord(
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        text=segment.text,
                    )
                    for segment in segments
                ),
                started_at=started_at,
                finished_at=finished_at,
                created_at=finished_at,
            )
        except ValueError:
            # The storage boundary re-validates the timeline it is handed and
            # rejects a body it cannot represent (a position above
            # ``MAX_TIMELINE_MS``) with a bounded ``ValueError``.  That check runs
            # in the boundary's canonical-segment step, ahead of its transaction,
            # so nothing was written and nothing needs rolling back.  It is one
            # part's data anomaly, not the run's: it is recorded as this part's
            # bounded ``shape_error`` attempt so the remaining parts of the
            # bounded run are still attempted, instead of aborting the whole run.
            return self._record_failed_part(
                run_id, item, GatewayShapeError(), started_at
            )
        return SubtitlePartOutcome(
            work_id=item.work_id,
            outcome=write.outcome,
            error_code=None,
            source_kind=source_kind,
            language=language,
            version=write.version,
        )

    def _record_captionless_part(
        self,
        run_id: str,
        item: _SubtitleWorkItem,
        error_code: str | None,
        started_at: int,
        *,
        credential_verified: bool = False,
        absence_verified: bool = False,
    ) -> SubtitlePartOutcome:
        """Record one attempt that found no usable caption — never a failure.

        An empty listing and a ``not_found`` answer both mean no usable caption
        was visible for this part at this attempt; the attempt row is the whole
        evidence (no transcript), and the part stays eligible for a later run.
        """

        self._repository.record_subtitle_attempt(
            run_id=run_id,
            video_part_id=item.video_part_id,
            outcome=_OUTCOME_NO_SUBTITLE,
            error_code=error_code,
            started_at=started_at,
            finished_at=self._clock(),
            credential_verified=credential_verified,
            absence_verified=absence_verified,
        )
        return SubtitlePartOutcome(
            work_id=item.work_id,
            outcome=_OUTCOME_NO_SUBTITLE,
            error_code=error_code,
            source_kind=None,
            language=None,
            version=None,
        )

    def _record_failed_part(
        self,
        run_id: str,
        item: _SubtitleWorkItem,
        error: GatewayError,
        started_at: int,
    ) -> SubtitlePartOutcome:
        """Record one bounded gateway failure, with its scalar code as evidence."""

        self._repository.record_subtitle_attempt(
            run_id=run_id,
            video_part_id=item.video_part_id,
            outcome=_OUTCOME_FAILED,
            error_code=error.code,
            started_at=started_at,
            finished_at=self._clock(),
        )
        return SubtitlePartOutcome(
            work_id=item.work_id,
            outcome=_OUTCOME_FAILED,
            error_code=error.code,
            source_kind=None,
            language=None,
            version=None,
        )


__all__ = [
    "HarvestResult",
    "ProbeResult",
    "SubtitleIngestor",
    "SubtitlePartOutcome",
    "SubtitleProbePart",
    "SubtitleSelection",
    "language_family",
    "select_subtitle_track",
]
