"""Queue selection at the CLI surface: the store gap views, not the manifest.

``archive.db`` is the sole work queue.  The three gap views
(``v_missing_audio`` / ``v_missing_transcript``) declare which parts need
audio and which need transcription; this module maps one queued part onto the
manifest row shape the downstream stages (downloader, ASR, archive writer)
already consume, and exposes the two write-backs that record the evidence a
successful stage produces (:meth:`MediaQueueRepository.mark_audio_acquired`
and :meth:`MediaQueueRepository.mark_transcript_stored`).

The mapping never invents identity: a part is keyed by ``(bvid, page_index)``
(contract §4c) and a queued part carries its own ``cid``, so the row it maps
to is page-resolved without a live pagelist call.  Selection is read-only and
delegates the locked work order (``pubdate DESC, bvid ASC, page_index ASC``)
to the repository; nothing here re-sorts.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any

from bili_asr.storage import MediaQueueRepository, QueueGapItem
from bili_asr.storage.database import open_database

#: The deprecation line printed once to stderr when the operator pins the
#: pre-cutover manifest queue with ``--queue-source manifest``.
MANIFEST_SOURCE_DEPRECATION = (
    "queue-source manifest is deprecated; archive.db is the sole queue"
)


@dataclass(frozen=True)
class QueueSelection:
    """One command's work list, sourced from the store gap views.

    ``entries`` is keyed by the store-native ``work_id`` (``"{bvid}:pN"``) —
    a legacy bare-bvid row never reaches the queue (contract §3) — and each
    value is the manifest row shape the downstream stages consume.  ``items``
    keeps the typed :class:`QueueGapItem` per key so a caller renders attempt
    evidence without a second read.
    """

    entries: dict[str, dict[str, Any]]
    items: dict[str, QueueGapItem]


def _duration_s_from_ms(duration_ms: int | None) -> int:
    """Whole seconds one stored duration covers, at least one.

    Mirrors the queue bridge's floor/clamp: the audio budget reads ``0`` as
    *unknown* and fail-closes, so a sub-second or absent duration is recorded
    as the smallest usable second.
    """

    if duration_ms is None:
        return 1
    return max(1, int(duration_ms) // 1000)


def entry_for_item(item: QueueGapItem) -> dict[str, Any]:
    """Map one queued part onto the manifest row shape the chain consumes.

    The row is keyed by the store-native ``work_id`` and carries the part's
    own ``bvid``/``page_index``/``cid``, so it is page-resolved without a
    pagelist call — ``download-audio`` keeps its documented skip of the live
    identity round-trip.  ``duration_s`` follows the store's millisecond
    vocabulary converted to the manifest's seconds; ``pubdate``/``pubdate_str``
    render publication the way the archive writer's frontmatter reads it.
    ``video_title`` and the part's own title travel as the title pair the
    writer records.  The queued part's ``gap`` names the route it drains, so
    the row records the status that route starts from.
    """

    status = "audio_ok" if item.gap == "missing_transcript" else "needs_audio"
    return {
        "bvid": item.bvid,
        "work_id": item.work_id,
        "page_index": item.page_index,
        "cid": item.cid,
        "page_label": "",
        "status": status,
        "title": item.video_title,
        "duration_s": _duration_s_from_ms(item.duration_ms),
        "pubdate": item.pubdate,
        "pubdate_str": time.strftime("%Y-%m-%d", time.gmtime(item.pubdate)),
        "video_title": item.video_title,
    }


class QueueSource:
    """Read one archive root's work queues and record the evidence a stage produced.

    The connection is opened through :func:`open_database` on demand and
    closed by the caller's context; every read is the repository's gap view,
    every write is one of the two ``mark_*`` methods — the repository API is
    frozen, this class only composes it with the CLI's row shape.
    """

    def __init__(self, connection):
        self.connection = connection
        self.repository = MediaQueueRepository(connection)

    # ------------------------------------------------------------------ read

    def select_audio_queue(self, *, bvid: str | None = None, page: int | None = None,
                           limit: int | None = None) -> QueueSelection:
        """The parts that need audio acquisition (``v_missing_audio``)."""

        return self._select("missing_audio", bvid=bvid, page=page, limit=limit)

    def select_transcript_queue(self, *, bvid: str | None = None, page: int | None = None,
                                limit: int | None = None) -> QueueSelection:
        """The parts that have audio evidence and need transcription."""

        return self._select("missing_transcript", bvid=bvid, page=page, limit=limit)

    def select_subtitle_queue(self, *, bvid: str | None = None, page: int | None = None,
                              limit: int | None = None) -> QueueSelection:
        """The parts that still need a subtitle (the harvest route)."""

        return self._select("missing_subtitle", bvid=bvid, page=page, limit=limit)

    def select_pending_scope(self, *, limit: int | None = None) -> "dict[str, dict[str, Any]]":
        """Every queued part, keyed by work_id, in the coordinator's row shape.

        The three gap views are not disjoint (contract §4), so a part is
        deduplicated by its store-native ``work_id``; the first queue that
        claims it wins, in the fixed order 字幕 → 音频 → 转写.  Each row's
        ``status`` names the stage route the coordinator drives it down:
        ``meta_ok`` (harvest), ``needs_audio`` (download→ASR), or ``audio_ok``
        (ASR).  A part holding subtitles is never in any queue.
        """

        merged: dict[str, dict[str, Any]] = {}
        # missing_subtitle holds both never-attempted (harvest) and
        # caption-exhausted parts; the latter also sit in missing_audio.  The
        # audio queue's newest-attempt evidence distinguishes them, so drain
        # audio and transcript first and let the subtitle queue contribute
        # only what those left behind — the genuinely harvest-needed parts.
        for select in (
            self.select_audio_queue(limit=limit),
            self.select_transcript_queue(limit=limit),
        ):
            for key, entry in select.entries.items():
                merged.setdefault(key, entry)
        for key, entry in self.select_subtitle_queue(limit=limit).entries.items():
            if key not in merged:
                row = dict(entry)
                row["status"] = "meta_ok"
                merged[key] = row
        return merged

    def _select(self, gap: str, *, bvid: str | None, page: int | None,
                limit: int | None) -> QueueSelection:
        items = self.repository.list_queue_gaps(
            gap=gap, bvid=bvid, page=page, limit=limit
        )
        entries: dict[str, dict[str, Any]] = {}
        item_by_key: dict[str, QueueGapItem] = {}
        for item in items:
            entries[item.work_id] = entry_for_item(item)
            item_by_key[item.work_id] = item
        return QueueSelection(entries=entries, items=item_by_key)


def open_queue_source(archive_root: str | os.PathLike[str]) -> "QueueSource | None":
    """Open one archive root's queue source; ``None`` when the store is absent.

    A missing ``archive.db`` is the documented configuration error: the
    caller prints the command's own line and exits 1, exactly as the other
    store-backed commands do.  A store that predates the transcript schema is
    answered with the bounded rebuild line rather than a raw SQLite error.
    """

    import sqlite3
    import sys

    from bili_asr.storage import SchemaContractError, require_subtitle_schema

    db_path = os.path.join(os.fspath(archive_root), "archive.db")
    if not os.path.isfile(db_path):
        return None
    try:
        connection = open_database(archive_root)
    except (OSError, sqlite3.Error):
        return None
    try:
        require_subtitle_schema(connection)
    except SchemaContractError:
        connection.close()
        return None
    return QueueSource(connection)


def print_manifest_deprecation() -> None:
    """Print the one rollback deprecation line to stderr."""

    import sys

    print(MANIFEST_SOURCE_DEPRECATION, file=sys.stderr)


def mark_audio_acquired(
    queue_source: QueueSource,
    *,
    bvid: str,
    page_index: int,
    audio_path: str,
    declared_relative: str,
) -> None:
    """Record that a part's audio was acquired into the store.

    ``audio_path`` is the absolute location the bytes landed (the storage_key
    identity, contract §4c); ``declared_relative`` is the root-relative string
    the manifest row records.  The evidence the gap views probe is the
    ``part_audio_objects`` link this writes — never an attempts row (§4d).
    Best-effort: a store that refuses the evidence must not fail a download
    the bytes already completed.
    """

    try:
        with open(audio_path, "rb") as fh:
            payload = fh.read()
        queue_source.repository.mark_audio_acquired(
            bvid=bvid,
            page_index=page_index,
            audio_path=audio_path,
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            format=os.path.splitext(audio_path)[1].lstrip(".") or "m4a",
            duration_ms=0,
            acquisition_source="download",
            acquired_at=int(time.time()),
        )
    except (OSError, ValueError):
        # The download already completed; store evidence is supplementary.
        pass


def mark_transcript_stored(
    queue_source: QueueSource,
    *,
    bvid: str,
    page_index: int,
    transcript_id: int,
    run_id: str,
) -> None:
    """Record that a stored transcript now answers for this part.

    The attempt row is the evidence; scoped to the caller's existing run so
    the write is idempotent per (run_id, video_part_id) (contract §4c/§4d).
    Best-effort, same rationale as :func:`mark_audio_acquired`.
    """

    try:
        now = int(time.time())
        queue_source.repository.mark_transcript_stored(
            bvid=bvid,
            page_index=page_index,
            transcript_id=transcript_id,
            run_id=run_id,
            started_at=now,
            finished_at=now,
        )
    except (OSError, ValueError, KeyError):
        pass


__all__ = [
    "MANIFEST_SOURCE_DEPRECATION",
    "QueueSelection",
    "QueueSource",
    "entry_for_item",
    "mark_audio_acquired",
    "mark_transcript_stored",
    "open_queue_source",
    "print_manifest_deprecation",
]
