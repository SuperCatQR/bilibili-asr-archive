"""Seed ``archive.db`` for the CLI fixtures whose rows live in the manifest.

``archive.db`` is the sole queue input since the ``--queue-source`` cutover:
``download-audio`` / ``asr`` / ``pilot`` / ``run --scope pending`` read the store
gap views, and ``services/queue_source.py`` answers a root with no database by
returning ``None`` — the command then prints its own ``no archive database``
line and exits 1 at its precondition.  A fixture that seeds only
``ManifestStore`` therefore cannot drive those commands at all.

This module is the one place that bridges the two stores for a test: it reads
the manifest rows a fixture already wrote and records the equivalent store
facts, through the repositories' own writers (the same discipline
``tests/test_cli_queue_source.py`` states for its fixture), so the queue views
answer with the parts the manifest names.

Usage, from a fixture that has just written its manifest rows::

    from _archive_database import _seed_archive_database

    _seed_archive_database(root)

What it records per manifest row, keyed on the row's own ``status``:

- every row with a resolvable ``(bvid, page_index, cid)`` becomes a
  ``videos`` / ``video_parts`` pair (``processing_status`` follows the row: a
  ``gone`` row is stored ``gone``, so the gap views' own filter applies), and
  the part is selectable at all;
- a row whose declared ``audio_path`` exists on disk gets its ``audio_objects``
  / ``part_audio_objects`` evidence — the sole positive audio probe (§4d) — and
  therefore sits in ``v_missing_transcript`` (the ASR queue);
- a row that neither holds a caption nor has audio bytes on disk gets the
  ``no-subtitle`` attempt ``v_missing_audio`` requires, which is what puts a
  captionless part in the download queue;
- a row already holding a caption (``subtitle_done`` / ``archived``) gets **no
  attempt history**: the manifest's caption is not store state, and the store
  does express "this part still owes a subtitle" — ``v_missing_subtitle``.  A
  fabricated ``no-subtitle`` attempt would instead claim the caption route was
  tried and came back empty, which is the reverse of what the row says.

The ``no-subtitle`` attempt is recorded for ``meta_ok`` rows as well: several
fixtures harvest the row to ``needs_audio`` *after* seeding, and the store has
to describe the part the command will actually meet.  A ``meta_ok`` row is in
``v_missing_subtitle`` either way, so its harvest queue membership is unchanged.

Deliberately minimal (YAGNI): no caller here needs a stored caption row, an
attempt history beyond the one ``no-subtitle`` fact the audio queue's own
predicate reads, or a stored transcript.  What this mapping cannot bridge: a
caption the store does not hold is not reachable by any gap view — the two
caption queues require a transcript's *absence*, and the audio queue requires
the caption route to look exhausted.  A fixture that seeds a ``subtitle_done``
row is therefore asking for a state the store route cannot select, and no
amount of seeding changes that.
"""

from __future__ import annotations

import hashlib
import os

from bili_asr.manifest import ManifestStore
from bili_asr.storage import (
    AcquisitionRunRecord,
    MediaQueueRepository,
    MetadataRepository,
    TranscriptRepository,
    UserRecord,
    VideoPartRecord,
    VideoRecord,
    open_database,
)

#: The archive's single owner mid, as every other fixture in the suite uses it.
_MID = 23191782

#: One run id for the whole seed: the ``no-subtitle`` attempts below are
#: per-``(run_id, video_part_id)``, so a second call for the same part is a
#: write the repository refuses rather than a duplicate fact.
_RUN_ID = "seed-archive-database"


def _seed_archive_database(root: str, *, audio_base: str | None = None) -> None:
    """Create ``archive.db`` at ``root`` holding the manifest's rows as store facts.

    Idempotent per root: a second call re-reads the manifest and re-records the
    same facts, and the repository's own conflict handling makes every write a
    no-op.  A row the manifest cannot place (no ``bvid``, no ``cid``, or an
    unresolved page) is skipped rather than guessed at — an invented
    ``video_parts`` row would be a queue entry no operator asked for.

    ``audio_base`` is the directory a row's root-relative ``audio_path`` is
    resolved against when the fixture kept the bytes somewhere other than
    ``root``: the ``--artifact-root`` cases write products under the configured
    root while the row records the shipped relative spelling (D7).  It defaults
    to ``root``, the single-base layout every other fixture uses.
    """
    base = root if audio_base is None else audio_base
    connection = open_database(root)
    try:
        entries = ManifestStore(root=root).load()
        metadata = MetadataRepository(connection)
        parts: list[tuple[str, int, dict]] = []
        with metadata.transaction():
            metadata.upsert_user(
                UserRecord(mid=_MID, display_name="未明子", created_at=1, updated_at=1)
            )
            for entry in entries.values():
                placed = _placeable(entry)
                if placed is None:
                    continue
                bvid, page_index, cid = placed
                metadata.upsert_video(
                    VideoRecord(
                        bvid=bvid,
                        aid=None,
                        mid=_MID,
                        title=str(entry.get("video_title") or entry.get("title") or bvid),
                        pubdate=int(entry.get("pubdate") or 0),
                        created_at=2,
                        updated_at=2,
                    )
                )
                metadata.upsert_part(
                    VideoPartRecord(
                        bvid=bvid,
                        page_index=page_index,
                        cid=cid,
                        title=str(entry.get("title") or ""),
                        duration_ms=max(1, int(entry.get("duration_s") or 1) * 1000),
                        processing_status=(
                            "gone" if entry.get("status") == "gone" else "discovered"
                        ),
                        created_at=3,
                        updated_at=3,
                    )
                )
                parts.append((bvid, page_index, entry))
        connection.commit()
        queue = MediaQueueRepository(connection)
        transcripts = TranscriptRepository(connection)
        for bvid, page_index, entry in parts:
            if _record_audio_evidence(queue, base, bvid, page_index, entry):
                continue
            if _holds_a_caption(entry):
                continue
            _record_no_subtitle(connection, transcripts, bvid, page_index)
        connection.commit()
    finally:
        connection.close()


def _placeable(entry: dict) -> tuple[str, int, int] | None:
    """The row's ``(bvid, page_index, cid)``, or ``None`` when it has no page."""

    bvid = entry.get("bvid")
    cid = entry.get("cid")
    if not bvid or cid is None or entry.get("unresolved"):
        return None
    return str(bvid), int(entry.get("page_index") or 0), int(cid)


def _record_audio_evidence(
    queue: MediaQueueRepository, root: str, bvid: str, page_index: int, entry: dict
) -> bool:
    """Record the row's audio as store evidence; report whether the bytes were there.

    The row's own ``audio_path`` is the location: a row that declares audio the
    fixture never wrote is *not* given evidence, because the queue would then
    select a part whose bytes the ASR stage cannot open — the fixture would be
    asserting a state the archive cannot be in.
    """

    audio_path = entry.get("audio_path")
    if not audio_path:
        return False
    absolute = os.path.join(root, os.fspath(audio_path))
    try:
        with open(absolute, "rb") as handle:
            payload = handle.read()
    except OSError:
        return False
    queue.mark_audio_acquired(
        bvid=bvid,
        page_index=page_index,
        audio_path=os.fspath(audio_path),
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
        format=os.path.splitext(os.fspath(audio_path))[1].lstrip(".") or "m4a",
        duration_ms=max(1, int(entry.get("duration_s") or 1) * 1000),
        acquisition_source="download",
        acquired_at=4,
    )
    return True


def _holds_a_caption(entry: dict) -> bool:
    """Whether the row's own status says a subtitle is already in hand.

    ``subtitle_done`` is the harvested-caption state and ``archived`` the
    terminal one; both mean the caption route produced a subtitle.  Such a row
    gets no attempt history at all, so the store answers "this part still owes a
    subtitle" (``v_missing_subtitle``) rather than the opposite.  A
    ``no-subtitle`` attempt here would tell the download queue that the caption
    route came back empty for a part the manifest says holds captions.
    """

    return entry.get("status") in {"subtitle_done", "archived"}


def _record_no_subtitle(connection, transcripts, bvid: str, page_index: int) -> None:
    """Record the part's newest caption attempt as ``no-subtitle``.

    ``v_missing_audio`` admits a part only when its newest subtitle attempt
    outcome is ``no-subtitle`` or ``failed``, so this is the fact that makes a
    caption-exhausted row selectable for audio.  Both writes are guarded by an
    existence check rather than by catching the repository's refusal: a second
    seed of the same root re-uses the run and the attempt it already recorded,
    and any *other* failure stays visible instead of being silently absorbed.
    """

    if connection.execute(
        "SELECT 1 FROM acquisition_runs WHERE run_id = ?", (_RUN_ID,)
    ).fetchone() is None:
        transcripts.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=_RUN_ID,
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=10,
                finished_at=12,
                outcome="complete",
            )
        )
    row = connection.execute(
        "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
        (bvid, page_index),
    ).fetchone()
    if row is None:  # pragma: no cover - the caller just wrote it
        return
    video_part_id = int(row["video_part_id"])
    if connection.execute(
        "SELECT 1 FROM acquisition_attempts WHERE run_id = ? AND video_part_id = ?",
        (_RUN_ID, video_part_id),
    ).fetchone() is not None:
        return
    transcripts.record_subtitle_attempt(
        run_id=_RUN_ID,
        video_part_id=video_part_id,
        outcome="no-subtitle",
        error_code=None,
        started_at=11,
        finished_at=12,
    )
