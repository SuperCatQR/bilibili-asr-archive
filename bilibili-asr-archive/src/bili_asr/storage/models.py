"""Validated internal records used by the SQLite metadata repository.

These dataclasses are deliberately independent of third-party API response
objects.  They represent the scalar facts that may be persisted by the
normalized metadata schema.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, get_args


ProcessingStatus = Literal["discovered", "metadata_collected", "gone"]
RunOutcome = Literal["running", "complete", "limited", "risk_interrupted", "failed"]
PageOutcome = Literal["ok", "empty", "risk_interrupted", "failed"]
CursorState = Literal["ready", "complete", "limited", "risk_interrupted"]
AcquisitionKind = Literal["subtitle", "audio", "asr"]
AcquisitionOutcome = Literal["running", "complete", "partial", "failed"]
AttemptOutcome = Literal["stored", "unchanged", "no-subtitle", "failed"]
SourceKind = Literal["subtitle-ai", "subtitle-cc", "asr-local"]
QueueGap = Literal["missing_subtitle", "missing_audio", "missing_transcript"]

_ALLOWED_PROCESSING_STATUS = frozenset({"discovered", "metadata_collected", "gone"})
_ALLOWED_RUN_OUTCOMES = frozenset(
    {"running", "complete", "limited", "risk_interrupted", "failed"}
)
_ALLOWED_PAGE_OUTCOMES = frozenset({"ok", "empty", "risk_interrupted", "failed"})
_ALLOWED_CURSOR_STATES = frozenset({"ready", "complete", "limited", "risk_interrupted"})
_ALLOWED_ACQUISITION_KINDS = frozenset({"subtitle", "audio", "asr"})
_ALLOWED_ACQUISITION_OUTCOMES = frozenset({"running", "complete", "partial", "failed"})
_ALLOWED_ATTEMPT_OUTCOMES = frozenset({"stored", "unchanged", "no-subtitle", "failed"})
_ALLOWED_SOURCE_KINDS = frozenset({"subtitle-ai", "subtitle-cc", "asr-local"})
_ALLOWED_SELECTOR_KINDS = frozenset({"pending", "bvid"})
# The three work queues the archive drains, derived from the literal above so
# the enumeration set and the type cannot drift apart.
_ALLOWED_QUEUE_GAPS = frozenset(get_args(QueueGap))
# The two outcomes a transcript write can report; the other attempt outcomes
# record an acquisition that produced no transcript at all.
_ALLOWED_TRANSCRIPT_WRITE_OUTCOMES = frozenset({"stored", "unchanged"})
# The largest millisecond position a stored caption timeline accepts: about 31
# years, far beyond any caption and far below the 64-bit integer SQLite binds,
# so an upstream value that cannot be a caption timestamp is rejected with a
# bounded ``ValueError`` instead of an ``OverflowError``.  The storage
# boundary enforces it (``TranscriptRepository.record_acquired_transcript``),
# not the segment record below, which validates the shape of one row.
MAX_TIMELINE_MS = 10**12
_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _integer(
    value: object,
    field: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field} must be at most {maximum}")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{field} contains invalid control characters")
    return value


def _error_code(value: object, field: str = "error_code") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string or None")
    if not value or len(value) > 64 or _ERROR_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded scalar code")
    return value


def _choice(value: object, field: str, allowed: frozenset[str]) -> str:
    value = _text(value, field)
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{field} must be one of: {choices}")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean")
    return value


def _caption_text(value: object, field: str = "text") -> str:
    """Validate caption text: a string non-empty after stripping.

    Unlike :func:`_text`, control characters inside the string are kept — the
    stored caption is verbatim apart from trimming.  Trimming is the storage
    boundary's job, not this validator's: ``TranscriptRepository`` stores and
    hashes the stripped form, so a caption's content identity never depends on
    the whitespace a caller happens to carry.
    """
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _content_sha256(value: object, field: str = "content_sha256") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if _SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be 64 lowercase hexadecimal characters")
    return value


@dataclass(frozen=True, slots=True)
class UserRecord:
    """Current operational metadata for one Bilibili user."""

    mid: int
    display_name: str
    created_at: int
    updated_at: int

    def __post_init__(self) -> None:
        _integer(self.mid, "mid", minimum=1)
        _text(self.display_name, "display_name")
        _integer(self.created_at, "created_at", minimum=0)
        _integer(self.updated_at, "updated_at", minimum=0)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")


@dataclass(frozen=True, slots=True)
class VideoRecord:
    """Current operational metadata for one Bilibili video."""

    bvid: str
    aid: int | None
    mid: int
    title: str
    pubdate: int
    created_at: int
    updated_at: int

    def __post_init__(self) -> None:
        _text(self.bvid, "bvid")
        if self.aid is not None:
            _integer(self.aid, "aid", minimum=1)
        _integer(self.mid, "mid", minimum=1)
        _text(self.title, "title")
        _integer(self.pubdate, "pubdate", minimum=0)
        _integer(self.created_at, "created_at", minimum=0)
        _integer(self.updated_at, "updated_at", minimum=0)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")


@dataclass(frozen=True, slots=True)
class VideoPartRecord:
    """Normalized metadata for one video part.

    ``video_part_id`` is allocated by the repository: records passed to
    ``MetadataRepository.upsert_part`` must carry ``None``. ``work_id`` is
    intentionally computed and is never persisted as a column.
    """

    bvid: str
    page_index: int
    cid: int
    title: str
    duration_ms: int
    processing_status: ProcessingStatus
    created_at: int
    updated_at: int
    video_part_id: int | None = None

    def __post_init__(self) -> None:
        _text(self.bvid, "bvid")
        _integer(self.page_index, "page_index", minimum=0)
        _integer(self.cid, "cid", minimum=1)
        _text(self.title, "title")
        _integer(self.duration_ms, "duration_ms", minimum=1)
        _choice(self.processing_status, "processing_status", _ALLOWED_PROCESSING_STATUS)
        _integer(self.created_at, "created_at", minimum=0)
        _integer(self.updated_at, "updated_at", minimum=0)
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.video_part_id is not None:
            _integer(self.video_part_id, "video_part_id", minimum=1)

    @property
    def work_id(self) -> str:
        """Return the derived work identifier without storing it."""

        return f"{self.bvid}:p{self.page_index}"


@dataclass(frozen=True, slots=True)
class IngestionRunRecord:
    """Metadata and outcome state for one collection run."""

    run_id: str
    mid: int
    source_package: str
    source_version: str
    requested_start_page: int
    requested_page_limit: int | None
    started_at: int
    finished_at: int | None = None
    outcome: RunOutcome = "running"

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _integer(self.mid, "mid", minimum=1)
        if _text(self.source_package, "source_package") != "bilibili-api-python":
            raise ValueError("source_package must be bilibili-api-python")
        _text(self.source_version, "source_version")
        _integer(self.requested_start_page, "requested_start_page", minimum=1)
        if self.requested_page_limit is not None:
            _integer(self.requested_page_limit, "requested_page_limit", minimum=1)
        _integer(self.started_at, "started_at", minimum=0)
        if self.finished_at is not None:
            _integer(self.finished_at, "finished_at", minimum=0)
            if self.finished_at < self.started_at:
                raise ValueError("finished_at must not precede started_at")
        _choice(self.outcome, "outcome", _ALLOWED_RUN_OUTCOMES)


@dataclass(frozen=True, slots=True)
class IngestionPageRecord:
    """Outcome evidence for one requested page in one run."""

    run_id: str
    page_number: int
    outcome: PageOutcome
    error_code: str | None
    started_at: int
    finished_at: int

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _integer(self.page_number, "page_number", minimum=1)
        _choice(self.outcome, "outcome", _ALLOWED_PAGE_OUTCOMES)
        _error_code(self.error_code)
        _integer(self.started_at, "started_at", minimum=0)
        _integer(self.finished_at, "finished_at", minimum=0)
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")


@dataclass(frozen=True, slots=True)
class CursorRecord:
    """Resumable one-based page cursor for one user."""

    mid: int
    next_page: int
    observed_total: int | None
    state: CursorState
    last_error_code: str | None
    updated_at: int

    def __post_init__(self) -> None:
        _integer(self.mid, "mid", minimum=1)
        _integer(self.next_page, "next_page", minimum=1)
        if self.observed_total is not None:
            _integer(self.observed_total, "observed_total", minimum=0)
        _choice(self.state, "state", _ALLOWED_CURSOR_STATES)
        _error_code(self.last_error_code, "last_error_code")
        _integer(self.updated_at, "updated_at", minimum=0)


@dataclass(frozen=True, slots=True)
class DiscoveryRecord:
    """A normalized relationship between a run page and a discovered video."""

    run_id: str
    page_number: int
    bvid: str
    source_position: int | None
    discovered_at: int

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _integer(self.page_number, "page_number", minimum=1)
        _text(self.bvid, "bvid")
        if self.source_position is not None:
            _integer(self.source_position, "source_position", minimum=0)
        _integer(self.discovered_at, "discovered_at", minimum=0)


@dataclass(frozen=True, slots=True)
class TranscriptSegmentRecord:
    """One caption row of one transcript, on the millisecond timeline.

    The invariant mirrors the gateway's ``SubtitleSegment`` so the service
    maps one DTO onto the other field for field: ``end_ms > start_ms >= 0``
    and ``text`` non-empty after stripping.  ``ordinal`` is positional and is
    assigned by the repository, never carried here.

    The record carries the text a caller supplies; the storage boundary stores
    and hashes its trimmed form, and it rejects a millisecond value above
    :data:`MAX_TIMELINE_MS` — the two normalization rules this record cannot
    state on its own.
    """

    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self) -> None:
        _integer(self.start_ms, "start_ms", minimum=0)
        _integer(self.end_ms, "end_ms", minimum=1)
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        _caption_text(self.text)


@dataclass(frozen=True, slots=True)
class TranscriptWriteResult:
    """What one transcript write did to the store.

    ``outcome`` is ``'stored'`` when the call appended a version and
    ``'unchanged'`` when the store already held that content; either way
    ``transcript_id``, ``version`` and ``content_sha256`` describe the version
    the operator now holds.
    """

    outcome: str
    transcript_id: int
    version: int
    content_sha256: str

    def __post_init__(self) -> None:
        _choice(self.outcome, "outcome", _ALLOWED_TRANSCRIPT_WRITE_OUTCOMES)
        _integer(self.transcript_id, "transcript_id", minimum=1)
        _integer(self.version, "version", minimum=1)
        _content_sha256(self.content_sha256)


@dataclass(frozen=True, slots=True)
class TranscriptRecord:
    """One stored transcript version together with its segment timeline.

    What a default read of a transcript answers: the whole ``transcripts`` row
    — identity, language, version, content hash, creation time — plus its
    segments in ordinal order, which is the caller order the write path stored,
    never re-sorted and never de-overlapped.  ``model_id`` is ``NULL`` for
    caption rows, and ``segments`` is never empty, because a transcript is only
    ever written with at least one segment.
    """

    transcript_id: int
    video_part_id: int
    source_kind: SourceKind
    language: str
    model_id: int | None
    version: int
    content_sha256: str
    created_at: int
    segments: tuple[TranscriptSegmentRecord, ...]

    def __post_init__(self) -> None:
        _integer(self.transcript_id, "transcript_id", minimum=1)
        _integer(self.video_part_id, "video_part_id", minimum=1)
        _choice(self.source_kind, "source_kind", _ALLOWED_SOURCE_KINDS)
        _text(self.language, "language")
        if self.model_id is not None:
            _integer(self.model_id, "model_id", minimum=1)
        _integer(self.version, "version", minimum=1)
        _content_sha256(self.content_sha256)
        _integer(self.created_at, "created_at", minimum=0)
        if not isinstance(self.segments, tuple):
            raise TypeError("segments must be a tuple")
        if not self.segments:
            raise ValueError("a stored transcript carries at least one segment")
        for index, segment in enumerate(self.segments):
            if not isinstance(segment, TranscriptSegmentRecord):
                raise TypeError(
                    f"segments[{index}] must be a TranscriptSegmentRecord"
                )


@dataclass(frozen=True, slots=True)
class AcquisitionRunRecord:
    """One acquisition run of one kind.

    ``selector_kind`` and ``selector_target`` are one fact: a bounded
    ``pending`` run carries no target, an explicit ``bvid`` run must carry
    one.  ``credential_present`` is run-scoped, so an attempt recorded without
    a caption stays interpretable afterwards.
    """

    run_id: str
    kind: AcquisitionKind
    selector_kind: str
    selector_target: str | None
    requested_limit: int | None
    credential_present: bool
    started_at: int
    finished_at: int | None = None
    outcome: AcquisitionOutcome = "running"

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        _choice(self.kind, "kind", _ALLOWED_ACQUISITION_KINDS)
        selector_kind = _choice(
            self.selector_kind, "selector_kind", _ALLOWED_SELECTOR_KINDS
        )
        if selector_kind == "pending":
            if self.selector_target is not None:
                raise ValueError("a pending selector carries no selector_target")
        elif self.selector_target is None:
            raise ValueError("a bvid selector requires a selector_target")
        else:
            _text(self.selector_target, "selector_target")
        if self.requested_limit is not None:
            _integer(self.requested_limit, "requested_limit", minimum=1)
        _boolean(self.credential_present, "credential_present")
        _integer(self.started_at, "started_at", minimum=0)
        if self.finished_at is not None:
            _integer(self.finished_at, "finished_at", minimum=0)
            if self.finished_at < self.started_at:
                raise ValueError("finished_at must not precede started_at")
        outcome = _choice(self.outcome, "outcome", _ALLOWED_ACQUISITION_OUTCOMES)
        if outcome != "running" and self.finished_at is None:
            raise ValueError("a terminal run outcome requires finished_at")


@dataclass(frozen=True, slots=True)
class QueueGapItem:
    """One part that one of the archive's three work queues still holds.

    A read projection, not an input record: every field is a stored fact the
    gap views already carry, so the constructor validates nothing and the
    dataclass only names the row the repository returns.  ``gap`` says which
    queue the row came from — it is not a stored column.  ``newest_outcome``
    and ``newest_error_code`` are the newest subtitle attempt's evidence and
    are ``None`` for a part the subtitle queue has never attempted, so a
    caller distinguishes "not tried" from "tried and failed" without a second
    read.  ``attempt_count`` is the number of ``acquisition_attempts`` rows
    whose run has the kind this gap's route records — ``'subtitle'`` for
    ``missing_subtitle``, ``'audio'`` for ``missing_audio`` and
    ``missing_transcript`` — and is ``0`` for a route never attempted.
    """

    work_id: str
    bvid: str
    page_index: int
    gap: QueueGap
    pubdate: int
    video_title: str
    duration_ms: int
    newest_outcome: str | None
    newest_error_code: str | None
    attempt_count: int


__all__ = [
    "AcquisitionKind",
    "AcquisitionOutcome",
    "AcquisitionRunRecord",
    "AttemptOutcome",
    "CursorRecord",
    "DiscoveryRecord",
    "IngestionPageRecord",
    "IngestionRunRecord",
    "MAX_TIMELINE_MS",
    "PageOutcome",
    "ProcessingStatus",
    "QueueGap",
    "QueueGapItem",
    "RunOutcome",
    "SourceKind",
    "TranscriptRecord",
    "TranscriptSegmentRecord",
    "TranscriptWriteResult",
    "UserRecord",
    "VideoPartRecord",
    "VideoRecord",
]


# Public validation surface: the canonical enumeration sets and the error-code
# validator are exported so gateway and CLI callers validate against the same
# contract the record dataclasses enforce.
validate_error_code = _error_code
ALLOWED_PAGE_OUTCOMES = _ALLOWED_PAGE_OUTCOMES
ALLOWED_RUN_OUTCOMES = _ALLOWED_RUN_OUTCOMES
ALLOWED_CURSOR_STATES = _ALLOWED_CURSOR_STATES
ALLOWED_PROCESSING_STATUS = _ALLOWED_PROCESSING_STATUS
ALLOWED_QUEUE_GAPS = _ALLOWED_QUEUE_GAPS
ALLOWED_ACQUISITION_KINDS = _ALLOWED_ACQUISITION_KINDS
ALLOWED_ACQUISITION_OUTCOMES = _ALLOWED_ACQUISITION_OUTCOMES
ALLOWED_ATTEMPT_OUTCOMES = _ALLOWED_ATTEMPT_OUTCOMES
ALLOWED_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS
# The two source kinds whose content identity the partial index
# ``ux_transcripts_subtitle_content`` enforces.  ``asr-local`` keeps its own
# (per model/run) identity rule and is owned by the audio/ASR iteration, so a
# caption write never accepts it.
ALLOWED_CAPTION_SOURCE_KINDS = _ALLOWED_SOURCE_KINDS - {"asr-local"}

__all__ += [
    "ALLOWED_ACQUISITION_KINDS",
    "ALLOWED_ACQUISITION_OUTCOMES",
    "ALLOWED_ATTEMPT_OUTCOMES",
    "ALLOWED_CAPTION_SOURCE_KINDS",
    "ALLOWED_CURSOR_STATES",
    "ALLOWED_PAGE_OUTCOMES",
    "ALLOWED_PROCESSING_STATUS",
    "ALLOWED_QUEUE_GAPS",
    "ALLOWED_RUN_OUTCOMES",
    "ALLOWED_SOURCE_KINDS",
    "validate_error_code",
]
