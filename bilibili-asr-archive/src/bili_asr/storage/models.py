"""Validated internal records used by the SQLite metadata repository.

These dataclasses are deliberately independent of third-party API response
objects.  They represent the scalar facts that may be persisted by the
normalized metadata schema.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


ProcessingStatus = Literal["discovered", "metadata_collected", "gone"]
RunOutcome = Literal["running", "complete", "limited", "risk_interrupted", "failed"]
PageOutcome = Literal["ok", "empty", "risk_interrupted", "failed"]
CursorState = Literal["ready", "complete", "limited", "risk_interrupted"]

_ALLOWED_PROCESSING_STATUS = frozenset({"discovered", "metadata_collected", "gone"})
_ALLOWED_RUN_OUTCOMES = frozenset(
    {"running", "complete", "limited", "risk_interrupted", "failed"}
)
_ALLOWED_PAGE_OUTCOMES = frozenset({"ok", "empty", "risk_interrupted", "failed"})
_ALLOWED_CURSOR_STATES = frozenset({"ready", "complete", "limited", "risk_interrupted"})
_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _integer(value: object, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
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

    ``video_part_id`` is optional for new rows because SQLite allocates the
    local surrogate key.  ``work_id`` is intentionally computed and is never
    persisted as a column.
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


__all__ = [
    "CursorRecord",
    "DiscoveryRecord",
    "IngestionPageRecord",
    "IngestionRunRecord",
    "PageOutcome",
    "ProcessingStatus",
    "RunOutcome",
    "UserRecord",
    "VideoPartRecord",
    "VideoRecord",
]


# Internal validation helpers are intentionally not part of the public model API.
validate_error_code = _error_code
ALLOWED_PAGE_OUTCOMES = _ALLOWED_PAGE_OUTCOMES
ALLOWED_RUN_OUTCOMES = _ALLOWED_RUN_OUTCOMES
ALLOWED_CURSOR_STATES = _ALLOWED_CURSOR_STATES
ALLOWED_PROCESSING_STATUS = _ALLOWED_PROCESSING_STATUS

__all__ += [
    "ALLOWED_CURSOR_STATES",
    "ALLOWED_PAGE_OUTCOMES",
    "ALLOWED_PROCESSING_STATUS",
    "ALLOWED_RUN_OUTCOMES",
    "validate_error_code",
]
