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
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable

from bili_asr.storage import MediaQueueRepository, QueueGapItem
from bili_asr.storage.database import open_database
from bili_asr.diagnostics import write_stderr
from bili_asr.formatting import pubdate_utc
from . import _common

#: The deprecation line printed once to stderr when the operator pins the
#: pre-cutover manifest queue with ``--queue-source manifest``.
MANIFEST_SOURCE_DEPRECATION = (
    "queue-source manifest is deprecated; archive.db is the sole queue"
)

# The ASR supervisor installs these hooks only in the isolated worker.  Keeping
# them here avoids making the queue layer depend on the supervisor module while
# still allowing the parent to identify the run and part it must recover after
# a hard worker termination.
_ASR_RUN_HOOK: Callable[[str], None] | None = None
_ASR_PART_HOOK: Callable[[int], None] | None = None


def set_asr_supervision_hooks(
    run_hook: Callable[[str], None] | None,
    part_hook: Callable[[int], None] | None,
) -> None:
    """Install or clear callbacks used by the process-level ASR supervisor."""

    global _ASR_RUN_HOOK, _ASR_PART_HOOK
    _ASR_RUN_HOOK = run_hook
    _ASR_PART_HOOK = part_hook


def _notify_asr_run(run_id: str) -> None:
    hook = _ASR_RUN_HOOK
    if hook is not None:
        hook(run_id)


def _notify_asr_part(video_part_id: int) -> None:
    hook = _ASR_PART_HOOK
    if hook is not None:
        hook(video_part_id)


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
    the row records the status that route starts from: ``audio_ok`` for the
    transcription queue, ``meta_ok`` for the subtitle queue.  The subtitle
    queue holds parts whose caption route is not exhausted but whose audio
    route may also be open, so the row must name the harvest route
    (``meta_ok``) — relabeling it ``needs_audio`` would collapse the harvest
    branch, which is the R13/R15 drift.
    """

    try:
        status = {
            "missing_transcript": "audio_ok",
            "missing_audio": "needs_audio",
            "missing_subtitle": "meta_ok",
        }[item.gap]
    except KeyError as exc:
        raise ValueError(f"unsupported queue gap {item.gap!r}") from exc
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
        "pubdate_str": pubdate_utc(item.pubdate),
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
        # The ``kind='asr'`` acquisition run this source's transcript
        # write-backs key to, created lazily by :meth:`ensure_asr_run` (the
        # run-scoping contract: one invocation is one run).  ``None`` when the
        # store refuses the run — every per-part write-back then skips.
        self.asr_run_id: str | None = None
        self._asr_run_finished = False
        # The refusal diagnostic is latched per instance: the refusal happens
        # before any row is recorded and skips the whole scope, and a store
        # that keeps refusing retries on every call, so an unlatched line
        # would degrade into per-row noise (D8).
        self._asr_run_refusal_reported = False
        self.audio_run_id: str | None = None
        self._audio_run_finished = False

    def ensure_audio_run(
        self, command: str, *, selector_target: str | None = None,
        requested_limit: int | None = None,
    ) -> str | None:
        """Open one invocation-scoped audio acquisition run."""
        import sqlite3
        from bili_asr.storage import AcquisitionRunRecord, TranscriptRepository

        if self.audio_run_id is not None:
            return self.audio_run_id
        try:
            run_id = f"{command}-{time.time_ns()}"
            TranscriptRepository(self.connection).start_acquisition_run(
                AcquisitionRunRecord(
                    run_id=run_id,
                    kind="audio",
                    selector_kind="bvid" if selector_target else "pending",
                    selector_target=selector_target,
                    requested_limit=requested_limit,
                    credential_present=False,
                    started_at=_common._now(),
                )
            )
            self.audio_run_id = run_id
        except (sqlite3.Error, OSError, ValueError, TypeError):
            self.audio_run_id = None
        return self.audio_run_id

    def record_audio_failed(
        self, *, bvid: str, page_index: int, error_code: str,
    ) -> None:
        """Best-effort negative evidence for one failed audio download."""
        if self.audio_run_id is None:
            return
        from bili_asr.storage import TranscriptRepository
        try:
            part = self.connection.execute(
                "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
                (bvid, page_index),
            ).fetchone()
            if part is None:
                return
            now = _common._now()
            TranscriptRepository(self.connection).record_audio_attempt(
                run_id=self.audio_run_id,
                video_part_id=int(part["video_part_id"]),
                error_code=error_code,
                started_at=now,
                finished_at=now,
            )
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return

    def finish_audio_run(self, *, outcome: str | None = None) -> None:
        """Finish the invocation's audio run before closing its connection."""
        import sqlite3
        from bili_asr.storage import TranscriptRepository

        if self.audio_run_id is None or self._audio_run_finished:
            return
        try:
            TranscriptRepository(self.connection).finish_acquisition_run(
                self.audio_run_id, _common._now(), outcome=outcome,
            )
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return
        self._audio_run_finished = True

    def ensure_asr_run(
        self, command: str, *, selector_target: str | None = None,
        requested_limit: int | None = None,
    ) -> str | None:
        """Open this source's ``kind='asr'`` acquisition run, best-effort.

        One source lifetime is one run scope: the run is the lifecycle
        parent the transcript write-back's attempt
        rows are keyed to.  A store that refuses the run leaves
        ``self.asr_run_id`` ``None`` so the row loop's per-part write-back is
        skipped — the archive on disk is never lost to a store problem.
        Idempotent per source: the first created id is reused, so a caller
        opening the source once per invocation records exactly one run.
        A coordinator that opens a source for each batch records a run for
        each batch; the diagnostic refusal latch still belongs to its invocation.

        The id is minted from ``time.time_ns()``, not the whole second
        ``run_id`` used to be: the key is a ``TEXT PRIMARY KEY``, and the
        coordinator re-opens the source at every batch boundary, so a second
        same-command run inside one wall-clock second collided with the first
        — the store's refusal was swallowed and the scope's write-backs were
        silently skipped while stdout still reported each row as archived.
        ``started_at`` keeps the second resolution the schema stores.

        The ``except`` names the classes the store actually raises, so a
        programming error is no longer reported as a refused run.  A genuine
        refusal is stated once per instance on stderr (silently dropped when
        fd 2 is closed, never rerouted to stdout); see
        :meth:`_report_refused_asr_run`.
        """

        import sqlite3 as _sqlite3

        from bili_asr.storage import AcquisitionRunRecord, TranscriptRepository

        if self.asr_run_id is not None:
            return self.asr_run_id
        try:
            now = _common._now()
            # The injectable clock owns persisted timestamps; this is only a
            # collision-resistant row identity and must not become evidence.
            run_id = f"{command}-{time.time_ns()}"
            TranscriptRepository(self.connection).start_acquisition_run(
                AcquisitionRunRecord(
                    run_id=run_id,
                    kind="asr",
                    selector_kind="bvid" if selector_target else "pending",
                    selector_target=selector_target,
                    requested_limit=requested_limit,
                    credential_present=False,
                    started_at=now,
                )
            )
            self.asr_run_id = run_id
            _notify_asr_run(run_id)
        except (_sqlite3.Error, OSError, ValueError, TypeError) as exc:
            self.asr_run_id = None
            self._report_refused_asr_run(command, exc)
        return self.asr_run_id

    def note_asr_part(self, *, bvid: str, page_index: int) -> None:
        """Publish the current ASR part to the worker supervisor, if present."""

        if self.asr_run_id is None or _ASR_PART_HOOK is None:
            return
        row = self.connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, page_index),
        ).fetchone()
        if row is not None:
            _notify_asr_part(int(row["video_part_id"]))

    def finish_asr_run(self, *, outcome: str | None = None) -> None:
        """Finish this source's run once, before closing its connection.

        Callers supply failed/partial when processing failed or was interrupted;
        otherwise the repository derives the outcome from stored attempts.
        A failed bookkeeping write cannot invalidate a published archive.
        """
        import sqlite3

        from bili_asr.storage import TranscriptRepository

        if self.asr_run_id is None or self._asr_run_finished:
            return
        try:
            TranscriptRepository(self.connection).finish_acquisition_run(
                self.asr_run_id, _common._now(), outcome=outcome,
            )
        except (sqlite3.Error, OSError, ValueError, TypeError):
            return
        self._asr_run_finished = True

    def _report_refused_asr_run(self, command: str, exc: BaseException) -> None:
        """State a refused run once per source, using an unbuffered diagnostic.

        The latch is per source instance for in-process CLI loops. The
        coordinator carries the same source-level latch across its per-batch
        source objects, so it reports once per coordinator invocation even
        when creation is retried next batch; a later coordinator invocation
        deliberately gets a fresh diagnostic.
        """
        if self._asr_run_refusal_reported:
            return
        self._asr_run_refusal_reported = True
        write_stderr(
            f"{command}: acquisition run refused by the store "
            f"({type(exc).__name__}); transcript write-backs are skipped "
            "for this run"
        )

    # ------------------------------------------------------------------ read

    def select_audio_queue(self, *, bvid: str | None = None, page: int | None = None,
                           limit: int | None = None) -> QueueSelection:
        """The parts that need audio acquisition (``v_missing_audio``)."""

        return self._select("missing_audio", bvid=bvid, page=page, limit=limit)

    def select_transcript_queue(self, *, bvid: str | None = None, page: int | None = None,
                                limit: int | None = None) -> QueueSelection:
        """The parts that have audio evidence and need transcription."""

        return self._select("missing_transcript", bvid=bvid, page=page, limit=limit)

    def select_asr_subtitle_queue(self, *, bvid: str | None = None,
                                  page: int | None = None,
                                  limit: int | None = None) -> QueueSelection:
        """Select captioned parts whose local ASR transcript is still absent."""
        items = self.repository.list_asr_subtitle_candidates(
            bvid=bvid, page=page, limit=limit
        )
        entries: dict[str, dict[str, Any]] = {}
        item_by_key: dict[str, QueueGapItem] = {}
        audio_parts: set[tuple[str, int]] = set()
        if items:
            identities = [(item.bvid, item.page_index) for item in items]
            predicate = " OR ".join(
                "(vp.bvid = ? AND vp.page_index = ?)" for _ in identities
            )
            parameters = [value for identity in identities for value in identity]
            audio_parts = {
                (str(row["bvid"]), int(row["page_index"]))
                for row in self.connection.execute(
                    "SELECT DISTINCT vp.bvid, vp.page_index "
                    "FROM video_parts AS vp "
                    "JOIN part_audio_objects AS pa "
                    "ON pa.video_part_id = vp.video_part_id "
                    f"WHERE {predicate}",
                    parameters,
                ).fetchall()
            }
        for item in items:
            entry = entry_for_item(item)
            has_audio = (item.bvid, item.page_index) in audio_parts
            entry["status"] = "audio_ok" if has_audio else "subtitle_done"
            entry["asr_required"] = True
            entry["source"] = "subtitle"
            entries[item.work_id] = entry
            item_by_key[item.work_id] = item
        return QueueSelection(entries=entries, items=item_by_key)

    def select_subtitle_queue(self, *, bvid: str | None = None, page: int | None = None,
                              limit: int | None = None) -> QueueSelection:
        """The parts that still need a subtitle (the harvest route)."""

        return self._select("missing_subtitle", bvid=bvid, page=page, limit=limit)

    def select_pending_scope(self, *, limit: int | None = None,
                             asr_with_subtitles: bool = True) -> "dict[str, dict[str, Any]]":
        """Every queued part, keyed by work_id, in the coordinator's row shape.

        The three gap views are not disjoint (contract §4), so a part is
        deduplicated by its store-native ``work_id``; the first queue that
        claims it wins, in the fixed order 字幕 → 音频 → 转写.  Each row's
        ``status`` names the stage route the coordinator drives it down:
        ``meta_ok`` (harvest), ``needs_audio`` (download→ASR), ``audio_ok``
        (ASR), or ``subtitle_done`` (captioned part awaiting audio).  When
        ``asr_with_subtitles`` is enabled, captioned parts are included in the
        ASR queue regardless of whether their subtitle raw is already present.
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
        if asr_with_subtitles:
            for key, entry in self.select_asr_subtitle_queue(limit=limit).entries.items():
                merged.setdefault(key, entry)
        for key, entry in self.select_subtitle_queue(limit=limit).entries.items():
            if key not in merged:
                # ``entry_for_item`` already names the harvest-eligible
                # ``meta_ok`` route; retain that single mapping source.
                merged[key] = entry
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

    write_stderr(MANIFEST_SOURCE_DEPRECATION)


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
        digest = hashlib.sha256()
        byte_size = 0
        with open(audio_path, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                digest.update(chunk)
                byte_size += len(chunk)
        queue_source.repository.mark_audio_acquired(
            bvid=bvid,
            page_index=page_index,
            audio_path=audio_path,
            sha256=digest.hexdigest(),
            byte_size=byte_size,
            format=os.path.splitext(audio_path)[1].lstrip(".") or "m4a",
            duration_ms=0,
            acquisition_source="download",
            acquired_at=_common._now(),
        )
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
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
        now = _common._now()
        queue_source.repository.mark_transcript_stored(
            bvid=bvid,
            page_index=page_index,
            transcript_id=transcript_id,
            run_id=run_id,
            started_at=now,
            finished_at=now,
        )
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        pass


def record_local_transcript(
    queue_source: QueueSource,
    *,
    run_id: str,
    bvid: str,
    page_index: int,
    language: str,
    segments: tuple,
    model_name: str,
    model_revision: str | None,
    coverage: dict | None = None,
) -> None:
    """Write one locally-produced transcript back into the store (best-effort).

    The transcript half of the audio write-back: after the ASR path archives a
    part, this records the ``transcripts`` row that takes the part out of
    ``v_missing_transcript`` (plan 20260929-asr-local-transcript-storage,
    Task 2).  The transcript row and its attempt evidence are written in one
    transaction through the repository's own
    :meth:`TranscriptRepository.record_local_transcript` — never the caption
    entry point, whose accepted-kind set stays exactly as strict.

    ``video_part_id`` is resolved through the store from ``(bvid, page_index)``
    here — never fabricated from a page index.  A part the store does not hold
    fails this row only.  Best-effort in the same sense as
    :func:`mark_audio_acquired`: every store failure — a missing part, a
    refused segment, a full store — is swallowed, because the archive the row
    would record already succeeded on disk and must not be lost to a store
    problem.  What is **not** swallowed is the caller's own work: the archive
    itself, which this helper never touches.
    """

    import sqlite3 as _sqlite3

    from bili_asr.storage import TranscriptRepository

    try:
        connection = queue_source.connection
        part = connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, int(page_index)),
        ).fetchone()
        if part is None:
            return
        video_part_id = int(part["video_part_id"])
        now = _common._now()
        repository = TranscriptRepository(connection)
        try:
            repository.record_local_transcript(
                run_id=run_id,
                video_part_id=video_part_id,
                language=language,
                segments=segments,
                model_name=model_name,
                model_revision=model_revision,
                started_at=now,
                finished_at=now,
                created_at=now,
                coverage=coverage,
            )
        except ValueError:
            # Coverage is supplementary evidence.  A malformed/overrun
            # alignment must not discard the durable transcript row or leave
            # the part permanently visible in v_missing_transcript.
            if coverage is None:
                raise
            repository.record_local_transcript(
                run_id=run_id,
                video_part_id=video_part_id,
                language=language,
                segments=segments,
                model_name=model_name,
                model_revision=model_revision,
                started_at=now,
                finished_at=now,
                created_at=now,
                coverage=None,
            )
    except (_sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        # The archive already succeeded on disk; a store write-back problem
        # must not turn that into a failure.
        pass


def record_caption_transcript(
    queue_source: QueueSource,
    *,
    run_id: str,
    bvid: str,
    page_index: int,
    source_kind: str,
    language: str,
    segments: tuple,
) -> bool:
    """Write one subtitle-sourced transcript back into the store (best-effort).

    The caption-arm sibling of :func:`record_local_transcript`: a caption
    harvested or archived from a subtitle source also owes a ``transcripts``
    row (source_kind ``'subtitle-ai'``/``'subtitle-cc'``), taking the part out
    of every gap view (plan r14-routes-writeback).  The write goes through the
    CAPTION writer — :meth:`TranscriptRepository.record_acquired_transcript`,
    whose accepted-kind set stays exactly the two caption kinds — never the
    ``'asr-local'`` singleton, and its attempt evidence rides the same one
    transaction the caption writer already owns.

    ``source_kind`` and ``language`` are the *stored* vocabulary values the
    caller already resolved (a gateway track's ``is_ai`` → ``subtitle-ai`` /
    ``subtitle-cc``; the track language trimmed), never a caller-invented
    literal.  ``video_part_id`` is resolved through the store from
    ``(bvid, page_index)`` here — never fabricated from a page index.
    Best-effort in exactly :func:`record_local_transcript`'s sense: every
    store failure — a missing part, a caption kind the caption writer refuses,
    a full store — is swallowed, because the archive the row would record
    already succeeded on disk and must not be lost to a store problem.
    """

    import sqlite3 as _sqlite3

    from bili_asr.storage import TranscriptRepository

    try:
        connection = queue_source.connection
        part = connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, int(page_index)),
        ).fetchone()
        if part is None:
            return False
        video_part_id = int(part["video_part_id"])
        now = _common._now()
        TranscriptRepository(connection).record_acquired_transcript(
            run_id=run_id,
            video_part_id=video_part_id,
            source_kind=source_kind,
            language=language,
            segments=segments,
            started_at=now,
            finished_at=now,
            created_at=now,
        )
        return True
    except (_sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        # The archive already succeeded on disk; a store write-back problem
        # must not turn that into a failure.
        return False


__all__ = [
    "MANIFEST_SOURCE_DEPRECATION",
    "QueueSelection",
    "QueueSource",
    "entry_for_item",
    "mark_audio_acquired",
    "mark_transcript_stored",
    "open_queue_source",
    "print_manifest_deprecation",
    "record_caption_transcript",
    "record_local_transcript",
]
