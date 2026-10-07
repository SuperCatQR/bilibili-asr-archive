"""Media queue implementation."""

from __future__ import annotations

import bili_asr.storage.database as _module_storage_database


import sqlite3
from typing import ClassVar, Iterable, Sequence
from bili_asr.storage.models import ALLOWED_QUEUE_GAPS, QueueGap, QueueGapItem, _choice, _content_sha256, _integer, _text
import bili_asr.storage.database as _dependency_database


class MediaQueueRepository:
    """The archive's queue surface: the three gap reads and the two writers.

    :meth:`list_queue_gaps` and :meth:`count_queue_gaps` return one typed entry
    per queued part, with the context and attempt evidence a caller renders it
    with.  :meth:`mark_audio_acquired` and :meth:`mark_transcript_stored` are
    the write half: each records, in one transaction, the evidence — an audio
    object or a stored transcript — that takes a part out of a queue.

    The relation is each view's own; the order is this class's.  The three gap
    views declare no ``ORDER BY``, so a caller reading them directly would take
    SQLite's row order as it comes — :meth:`list_queue_gaps` appends the locked
    work order ``pubdate DESC, bvid ASC, page_index ASC`` to every read, and
    that order is the only one the CLI may observe.  Membership is never
    re-derived here either: a part is in a queue because the view's predicates
    say so, and no argument to these methods reaches a part the view leaves
    out.

    The connection must come with ``row_factory = sqlite3.Row`` and
    ``PRAGMA foreign_keys`` enabled — exactly the state :func:`open_database`
    establishes — and must carry the transcript-schema contract, which is the
    script the three gap views are defined in: the constructor rejects
    anything else, so a caller that skipped :func:`require_subtitle_schema`
    meets the bounded rebuild error instead of a raw
    ``sqlite3.OperationalError`` from its first query.  The guard is the
    contract's own object set, not this class's views — a database carrying
    the contract but missing one gap view still answers
    ``sqlite3.OperationalError`` for that one queue, which is the honest
    report of a store that must be rebuilt.
    """

    _VIEW_BY_GAP: ClassVar[dict[str, str]] = {
        "missing_subtitle": "v_missing_subtitle",
        "missing_audio": "v_missing_audio",
        "missing_transcript": "v_missing_transcript",
    }
    # The acquisition route each queue drains, and therefore the run kind the
    # entry's ``attempt_count`` counts: a captionless part is re-attempted by a
    # subtitle run, while a part with audio evidence is decoded by an audio
    # run.  Counting one route's attempts while reading the other route's queue
    # would answer a question no caller asked.
    _KIND_BY_GAP: ClassVar[dict[str, str]] = {
        "missing_subtitle": "subtitle",
        "missing_audio": "audio",
        "missing_transcript": "audio",
    }

    def __init__(self, connection: sqlite3.Connection):
        _module_storage_database._validate_connection(connection)
        _module_storage_database.require_subtitle_schema(connection)
        self.connection = connection

    def mark_audio_acquired(
        self,
        *,
        bvid: str,
        page_index: int,
        audio_path: str,
        sha256: str,
        byte_size: int,
        format: str,
        duration_ms: int,
        acquisition_source: str,
        acquired_at: int,
    ) -> int:
        """Record that a part's audio has been acquired.  Returns the ``audio_id``.

        **Reuse is keyed on ``storage_key`` (= the caller's ``audio_path``), not
        on ``sha256``.**  Location is the identity of an archived audio object:
        the CLI derives a deterministic per-part path, so a re-download or a
        repaired decode produces a *new* hash for the *same* archived location
        and must not become a second object.  When a row already sits at that
        path it is reused, and ``sha256`` / ``byte_size`` / ``format`` /
        ``duration_ms`` are refreshed **only when they differ** — a re-run of
        the same acquisition is a no-op, and ``created_at`` keeps first-writer
        semantics.

        Same content at a new path (no row for this path, but another row
        already holds this ``sha256``): the content-holding row is reused and
        its ``storage_key`` is repointed to the caller's path — option (a) of
        contract §4c.  The alternative (a bounded ``ValueError`` naming both
        paths) was rejected because such a part would be permanently
        unrecordable, and ``audio_objects.sha256`` is ``UNIQUE``, so the two
        paths can never own two rows.  A silent third row is never written.

        The part link is inserted with ``ON CONFLICT DO NOTHING``, so it too
        keeps first-writer semantics.  Every scalar is bounded by the module's
        validators before any statement runs, so a malformed field is refused
        instead of surfacing as a raw ``sqlite3.IntegrityError``: ``sha256``
        goes through ``_content_sha256`` (64 lowercase hex), not ``_text`` —
        the value is a content hash the clash/repoint branch below trusts, and
        free text there could rewrite another object's ``storage_key``.  The
        rest are ``_text`` / ``_integer``.  ``storage_key`` is the caller's
        ``audio_path`` verbatim — this layer does not resolve or normalize
        paths.
        """
        bvid = _text(bvid, "bvid")
        page_index = _integer(page_index, "page_index", minimum=0)
        audio_path = _text(audio_path, "audio_path")
        sha256 = _content_sha256(sha256, "sha256")
        byte_size = _integer(byte_size, "byte_size", minimum=0)
        format = _text(format, "format")
        duration_ms = _integer(duration_ms, "duration_ms", minimum=0)
        acquisition_source = _text(acquisition_source, "acquisition_source")
        acquired_at = _integer(acquired_at, "acquired_at", minimum=0)

        part = self.connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, page_index),
        ).fetchone()
        if part is None:
            raise ValueError(
                f"unknown video part: bvid={bvid!r}, page_index={page_index!r}"
            )
        video_part_id = int(part["video_part_id"])

        with _module_storage_database._transaction(self.connection):
            existing = self.connection.execute(
                "SELECT audio_id, sha256, byte_size, format, duration_ms "
                "FROM audio_objects WHERE storage_key = ?",
                (audio_path,),
            ).fetchone()
            repoint = False
            if existing is None:
                # No row at this path: the same content may already be archived
                # under another one.  Reuse that row and move its path column to
                # the location the caller asked to occupy.
                existing = self.connection.execute(
                    "SELECT audio_id, sha256, byte_size, format, duration_ms "
                    "FROM audio_objects WHERE sha256 = ?",
                    (sha256,),
                ).fetchone()
                repoint = existing is not None

            if existing is None:
                cursor = self.connection.execute(
                    """
                    INSERT INTO audio_objects(
                        sha256, byte_size, format, duration_ms, storage_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (sha256, byte_size, format, duration_ms, audio_path, acquired_at),
                )
                audio_id = int(cursor.lastrowid)
            else:
                audio_id = int(existing["audio_id"])
                updates: dict[str, object] = {
                    column: value
                    for column, value in (
                        ("sha256", sha256),
                        ("byte_size", byte_size),
                        ("format", format),
                        ("duration_ms", duration_ms),
                    )
                    if existing[column] != value
                }
                if repoint:
                    updates["storage_key"] = audio_path
                elif "sha256" in updates:
                    # The path keeps its row, but this content is already
                    # archived at another location.  ``sha256`` is UNIQUE, so no
                    # single row can carry both paths: refuse instead of leaking
                    # an IntegrityError from the UPDATE below.
                    clash = self.connection.execute(
                        "SELECT storage_key FROM audio_objects "
                        "WHERE sha256 = ? AND audio_id != ?",
                        (sha256, audio_id),
                    ).fetchone()
                    if clash is not None:
                        raise ValueError(
                            "audio content already archived at "
                            f"{clash['storage_key']!r}: cannot record "
                            f"sha256={sha256!r} at storage_key={audio_path!r}"
                        )
                if updates:
                    assignments = ", ".join(f"{column} = ?" for column in updates)
                    self.connection.execute(
                        f"UPDATE audio_objects SET {assignments} WHERE audio_id = ?",
                        (*updates.values(), audio_id),
                    )

            self.connection.execute(
                """
                INSERT INTO part_audio_objects(
                    video_part_id, audio_id, acquired_at, acquisition_source
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(video_part_id, audio_id) DO NOTHING
                """,
                (video_part_id, audio_id, acquired_at, acquisition_source),
            )
        return audio_id

    def mark_transcript_stored(
        self,
        *,
        bvid: str,
        page_index: int,
        transcript_id: int,
        run_id: str,
        started_at: int,
        finished_at: int,
    ) -> None:
        """Record that a stored transcript now answers for this part.

        The attempt row is the evidence: ``outcome='stored'`` with the transcript
        reference and no error code, scoped to the caller's existing run.  The
        part's gap membership changes because that row exists, not because any
        status column is rewritten.
        """
        bvid = _text(bvid, "bvid")
        page_index = _integer(page_index, "page_index", minimum=0)
        run_id = _text(run_id, "run_id")
        transcript_id = _integer(transcript_id, "transcript_id", minimum=1)
        started_at = _integer(started_at, "started_at", minimum=0)
        finished_at = _integer(finished_at, "finished_at", minimum=0)
        if finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")
        part = self.connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, page_index),
        ).fetchone()
        if part is None:
            raise ValueError(
                f"unknown video part: bvid={bvid!r}, page_index={page_index!r}"
            )
        video_part_id = int(part["video_part_id"])

        transcript = self.connection.execute(
            "SELECT video_part_id FROM transcripts WHERE transcript_id = ?",
            (transcript_id,),
        ).fetchone()
        if transcript is None or int(transcript["video_part_id"]) != video_part_id:
            raise ValueError(
                f"unknown transcript for this part: transcript_id={transcript_id!r}, "
                f"bvid={bvid!r}, page_index={page_index!r}"
            )

        run = self.connection.execute(
            "SELECT 1 FROM acquisition_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"unknown run_id: {run_id!r}")

        with _module_storage_database._transaction(self.connection):
            self.connection.execute(
                """
                INSERT INTO acquisition_attempts(
                    run_id, video_part_id, outcome, error_code, transcript_id,
                    started_at, finished_at
                ) VALUES (?, ?, 'stored', NULL, ?, ?, ?)
                ON CONFLICT(run_id, video_part_id) DO NOTHING
                """,
                (run_id, video_part_id, transcript_id, started_at, finished_at),
            )

    def list_queue_gaps(
        self,
        *,
        gap: QueueGap,
        limit: int | None = None,
        bvid: str | None = None,
        page: int | None = None,
    ) -> list[QueueGapItem]:
        """Return the parts one gap's queue holds, in the locked work order.

        ``gap`` names the queue and is validated against the three the archive
        drains; a fourth name raises ``ValueError`` rather than silently
        reading nothing.  ``limit`` follows the module-wide read rule — a
        non-integer or a ``bool`` raises ``TypeError``, a limit below ``1``
        raises ``ValueError``, and ``None`` means unbounded.  ``bvid`` and
        ``page`` each add one predicate when given, so a caller narrows the
        queue to one video or one part; neither narrows the read when absent.

        The order ``pubdate DESC, bvid ASC, page_index ASC`` is appended by
        this method, not declared by the view: newest video first, and within
        one publication second the bvid then the page index break the tie, so
        the same store always answers the same sequence — page by page, which
        is what makes ``limit`` a stable rotation through a queue instead of a
        fresh sample of it.  ``attempt_count`` is counted per entry by run kind
        (``'subtitle'`` for ``missing_subtitle``, ``'audio'`` for the other
        two) over the returned rows only, in one grouped read per page rather
        than one read per row.  Read-only: no write, no commit.
        """
        gap = _choice(gap, "gap", ALLOWED_QUEUE_GAPS)
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("limit must be an integer or None")
            if limit < 1:
                raise ValueError("limit must be a positive integer")
        where_clauses: list[str] = []
        parameters: list[object] = []
        if bvid is not None:
            where_clauses.append("q.bvid = ?")
            parameters.append(_text(bvid, "bvid"))
        if page is not None:
            where_clauses.append("q.page_index = ?")
            parameters.append(_integer(page, "page_index", minimum=0))
        if gap == "missing_audio":
            # Failed audio attempts are retry evidence, not positive audio
            # evidence. Rotate the oldest attempted part first while keeping
            # never-attempted parts ahead of the retry tail.
            query = f"""
                SELECT q.*
                  FROM {self._VIEW_BY_GAP[gap]} AS q
                  LEFT JOIN (
                        SELECT aa.video_part_id, MAX(aa.finished_at) AS last_attempt
                          FROM acquisition_attempts AS aa
                          JOIN acquisition_runs AS ar ON ar.run_id = aa.run_id
                         WHERE ar.kind = 'audio'
                         GROUP BY aa.video_part_id
                  ) AS audio_attempt
                    ON audio_attempt.video_part_id = q.video_part_id
            """
        else:
            query = f"SELECT * FROM {self._VIEW_BY_GAP[gap]} AS q"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        if gap == "missing_audio":
            query += (
                " ORDER BY (audio_attempt.last_attempt IS NOT NULL) ASC, "
                "audio_attempt.last_attempt ASC, q.pubdate DESC, "
                "q.bvid ASC, q.page_index ASC"
            )
        else:
            query += " ORDER BY q.pubdate DESC, q.bvid ASC, q.page_index ASC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(query, parameters).fetchall()
        counts = self._attempt_counts(
            [int(row["video_part_id"]) for row in rows], self._KIND_BY_GAP[gap]
        )
        return [
            self._gap_item(row, gap, counts.get(int(row["video_part_id"]), 0))
            for row in rows
        ]

    def list_asr_subtitle_candidates(
        self,
        *,
        limit: int | None = None,
        bvid: str | None = None,
        page: int | None = None,
    ) -> list[QueueGapItem]:
        """Return captioned parts that still lack a local ASR transcript.

        Caption transcripts answer the subtitle route, but they do not answer
        the local-ASR route.  This read is deliberately separate from the
        three gap views so the historical subtitle/audio exhaustion rules stay
        intact while the default coordinator can schedule the second pass.
        ``gap='missing_transcript'`` keeps the returned projection compatible
        with the existing queue item shape; callers must treat it as an ASR
        candidate rather than as the legacy audio-only view.
        """
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise TypeError("limit must be an integer or None")
            if limit < 1:
                raise ValueError("limit must be a positive integer")
        clauses = [
            "vp.processing_status <> 'gone'",
            "EXISTS (SELECT 1 FROM transcripts AS caption "
            "WHERE caption.video_part_id = vp.video_part_id "
            "AND caption.source_kind IN ('subtitle-ai', 'subtitle-cc'))",
            "NOT EXISTS (SELECT 1 FROM transcripts AS asr "
            "WHERE asr.video_part_id = vp.video_part_id "
            "AND asr.source_kind = 'asr-local')",
        ]
        parameters: list[object] = []
        if bvid is not None:
            clauses.append("vp.bvid = ?")
            parameters.append(_text(bvid, "bvid"))
        if page is not None:
            clauses.append("vp.page_index = ?")
            parameters.append(_integer(page, "page_index", minimum=0))
        query = """
            SELECT
                vp.video_part_id,
                vp.bvid || ':p' || vp.page_index AS work_id,
                vp.bvid,
                vp.page_index,
                vp.cid,
                vp.title AS part_title,
                vp.duration_ms,
                v.title AS video_title,
                v.pubdate
            FROM video_parts AS vp
            JOIN videos AS v ON vp.bvid = v.bvid
            WHERE """ + " AND ".join(clauses) + " ORDER BY v.pubdate DESC, vp.bvid ASC, vp.page_index ASC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        rows = self.connection.execute(query, parameters).fetchall()
        counts = self._attempt_counts(
            [int(row["video_part_id"]) for row in rows], "asr"
        )
        return [
            self._gap_item(row, "missing_transcript", counts.get(int(row["video_part_id"]), 0))
            for row in rows
        ]

    def count_queue_gaps(self) -> dict[QueueGap, int]:
        """Count the parts each of the three queues holds, all three always.

        **The three values overlap and must never be summed.**  The gaps are not
        a partition: a transcriptless part with a ``no-subtitle``/``failed``
        subtitle attempt and no audio sits in ``missing_audio``, and a part with
        audio evidence and no transcript sits in ``missing_transcript`` — a part
        may be counted by two of these keys, or by one, but ``sum(...)`` answers
        no question about the store.  A backlog total needs its own distinct
        query, not an addition of these three.

        ``0`` is reported rather than omitted: a caller renders three queue
        sizes, and a queue that drained completely is a size, not a missing
        key.  The keys come back in the declaration order of the view table
        above, so a caller iterates the mapping without re-sorting it.
        Read-only: no write, no commit.
        """
        return {
            gap: int(
                self.connection.execute(
                    f"SELECT COUNT(*) FROM {view}"
                ).fetchone()[0]
            )
            for gap, view in self._VIEW_BY_GAP.items()
        }

    def read_audio_objects(self) -> dict[str, tuple[int, str]]:
        """Map every ``audio_objects.storage_key`` to ``(byte_size, sha256)``.

        Both halves make the contract's ``already`` counter ("present **and
        matched**") checkable: a ``stat`` against the size decides the default
        run without reading a byte, so the published cost model ("zero file reads
        for a row that already exists") survives the comparison, and the stored
        digest is what ``--deep`` compares a fresh read against.
        """
        return {
            str(row["storage_key"]): (int(row["byte_size"]), str(row["sha256"]))
            for row in self.connection.execute(
                "SELECT storage_key, byte_size, sha256 FROM audio_objects "
                "ORDER BY audio_id"
            ).fetchall()
        }

    def read_part_durations(self, work_ids: Iterable[str]) -> dict[str, int]:
        """Map page-qualified work ids to the store's own ``duration_ms``.

        The manifest records whole **seconds** (``duration_s``) because its
        writers floor and clamp them, so reconstructing milliseconds from a
        manifest row loses the exact value (``1234567 ms → 1234 s → 1234000 ms``).
        The store holds the exact figure, so the reconciliation reads it here
        rather than trusting the coarser surface.  A work id whose part is absent
        is simply omitted; the caller records the schema's documented "unknown".

        The key set is read straight off the ``video_parts`` rows for the bvids
        named, then emitted in this module's ``<bvid>:p<index>`` spelling, so the
        caller never has to parse or re-derive an identity.
        """
        requested = {str(work_id) for work_id in work_ids}
        if not requested:
            return {}
        bvids = tuple(dict.fromkeys(key.split(":", 1)[0] for key in requested))
        durations: dict[str, int] = {}
        for start in range(0, len(bvids), _module_storage_database._PUBDATE_CHUNK):
            chunk = bvids[start : start + _module_storage_database._PUBDATE_CHUNK]
            placeholders = ", ".join("?" * len(chunk))
            for row in self.connection.execute(
                "SELECT bvid, page_index, duration_ms FROM video_parts "
                f"WHERE bvid IN ({placeholders})",
                chunk,
            ).fetchall():
                key = f"{row['bvid']}:p{int(row['page_index'])}"
                if key in requested:
                    durations[key] = int(row["duration_ms"])
        return durations

    def read_audio_object_keys(self) -> tuple[str, ...]:
        """Every ``audio_objects.storage_key``, the store's recorded locations.

        The reconciliation matches a manifest candidate on this set, because
        ``storage_key`` — not ``sha256`` — is what ``mark_audio_acquired`` uses
        as an object's identity.  Read in one query rather than per candidate so
        the inventory walk pays one store read, not one per file.
        """
        return tuple(
            str(row["storage_key"])
            for row in self.connection.execute(
                "SELECT storage_key FROM audio_objects ORDER BY audio_id"
            ).fetchall()
        )

    def read_audio_object_ids(self) -> tuple[int, ...]:
        """Every ``audio_objects.audio_id``.

        Paired with :meth:`read_linked_audio_ids` this answers the ``unlinked``
        counter: an object row that no ``part_audio_objects`` row attributes to
        a part.
        """
        return tuple(
            int(row["audio_id"])
            for row in self.connection.execute(
                "SELECT audio_id FROM audio_objects ORDER BY audio_id"
            ).fetchall()
        )

    def read_linked_audio_ids(self) -> tuple[int, ...]:
        """Every ``part_audio_objects.audio_id`` — the objects tied to a part.

        A set, not a bag: an object attributed to several parts is still one
        attributed object, and the ``unlinked`` counter is a subtraction over
        objects.
        """
        return tuple(
            int(row["audio_id"])
            for row in self.connection.execute(
                "SELECT DISTINCT audio_id FROM part_audio_objects "
                "ORDER BY audio_id"
            ).fetchall()
        )

    @staticmethod
    def _gap_item(row: sqlite3.Row, gap: str, attempt_count: int) -> QueueGapItem:
        """Map one view row to one typed queue entry, whatever the view holds.

        One mapper serves all three views.  The shared nine-column prefix is
        read by name for every one of them; the newest-attempt evidence is read
        only when the row carries the column at all, which the row's own
        ``keys()`` answers — so the one gap view that exposes the columns
        reports them, and the two that do not report ``None`` instead of
        failing the read that a captionless part must still complete.
        """
        columns = set(row.keys())

        def evidence(column: str) -> str | None:
            """Answer one evidence column's value, or None when absent."""
            if column not in columns:
                return None
            return None if row[column] is None else str(row[column])

        return QueueGapItem(
            work_id=str(row["work_id"]),
            bvid=str(row["bvid"]),
            page_index=int(row["page_index"]),
            cid=int(row["cid"]),
            gap=gap,
            pubdate=int(row["pubdate"]),
            video_title=str(row["video_title"]),
            duration_ms=int(row["duration_ms"]),
            newest_outcome=evidence("newest_outcome"),
            newest_error_code=evidence("newest_error_code"),
            attempt_count=attempt_count,
        )

    def _attempt_counts(
        self, video_part_ids: Sequence[int], kind: str
    ) -> dict[int, int]:
        """Count each named part's attempts on one acquisition route.

        One grouped read for the whole page instead of one read per entry: the
        ids are passed in chunks of at most ``_PUBDATE_CHUNK`` parameters for
        the same reason :meth:`TranscriptRepository.read_video_pubdates` chunks
        its bvids — the queue is bounded by the store rather than by this
        module, and the driver bounds one statement.  A part with no attempt on
        that route is absent from the answer rather than present with ``0``, so
        the caller owns what an unattempted part counts as.  Read-only.
        """
        if not video_part_ids:
            return {}
        counts: dict[int, int] = {}
        for start in range(0, len(video_part_ids), _module_storage_database._PUBDATE_CHUNK):
            chunk = video_part_ids[start : start + _module_storage_database._PUBDATE_CHUNK]
            placeholders = ", ".join("?" * len(chunk))
            counts.update(
                {
                    int(row["video_part_id"]): int(row["attempts"])
                    for row in self.connection.execute(
                        "SELECT aa.video_part_id AS video_part_id, "
                        "COUNT(*) AS attempts "
                        "FROM acquisition_attempts AS aa "
                        "JOIN acquisition_runs AS ar ON ar.run_id = aa.run_id "
                        f"WHERE ar.kind = ? AND aa.video_part_id IN ({placeholders}) "
                        "GROUP BY aa.video_part_id",
                        (kind, *chunk),
                    ).fetchall()
                }
            )
        return counts
