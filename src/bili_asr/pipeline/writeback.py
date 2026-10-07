"""Writeback implementation."""

from __future__ import annotations

import bili_asr.asr.coverage as _module_asr_coverage
import bili_asr.asr.provenance as _module_asr_provenance


from dataclasses import field
from typing import Any
from bili_asr import asr as asr_module
from bili_asr.persistence import utc_now_iso
import bili_asr.pipeline.attempts as _dependency_attempts


def _caption_source_kind_from_entry(entry: dict[str, Any]) -> str | None:
    """The stored caption ``source_kind`` one archived row's subtitle names.

    The harvested track's language code carries the machine ``ai-`` prefix
    when the caption is machine-generated, so ``'subtitle-ai'`` /
    ``'subtitle-cc'`` derive from the row's own subtitle metadata — never
    from a caller-invented literal.  A row that names no subtitle language at
    all is the plan's documented STOP-condition answer: ``None``, and the
    part's write-back is skipped rather than guessing the caption kind.  (The
    newer typed subtitle-arm resolves the kind from the selected track's
    ``is_ai`` flag instead, through the caption writer's own validation.)
    """

    language = _caption_language_from_entry(entry)
    if language is None:
        return None
    return "subtitle-ai" if language.startswith("ai-") else "subtitle-cc"


def _caption_language_from_entry(entry: dict[str, Any]) -> str | None:
    """The caption language one archived row names, trimmed, or ``None``.

    ``sub_lan``/``sub_lan_doc`` is what the subtitle harvest seam records for
    the track it chose; the typed arm's projection keys it the same identity
    under ``subtitle_language``.  A blank or missing value is answered with
    ``None`` so the caller skips the write-back instead of storing an empty
    language the caption writer would refuse.
    """

    if not isinstance(entry, dict):
        return None
    for key in ("sub_lan", "subtitle_language", "sub_lan_doc"):
        value = entry.get(key)
        if not isinstance(value, str):
            continue
        language = value.strip()
        if language:
            return language
    return None


def _caption_transcript_segments(
    segments: list[dict[str, Any]],
) -> tuple:
    """Convert archived subtitle cues to ``TranscriptSegmentRecord``s.

    Archived subtitle cues carry second-float ``start``/``end`` times exactly
    like the ASR cues the sibling write-back converts; the storage side wants
    whole milliseconds.  One cue that cannot convert (a non-numeric time)
    fails this part's write-back only — the helper is called inside the
    best-effort boundary, so the archive on disk stands.
    """

    from bili_asr.storage import TranscriptSegmentRecord

    records = []
    for cue in segments:
        start_ms = int(round(float(cue.get("start", 0.0)) * 1000))
        end_ms = int(round(float(cue.get("end", 0.0)) * 1000))
        records.append(
            TranscriptSegmentRecord(
                start_ms=start_ms, end_ms=end_ms, text=str(cue.get("text", ""))
            )
        )
    return tuple(records)


def queue_source_for_writeback(coordinator):
    """This batch's lazily-opened queue source, or ``None``.

    The source opens at most once per batch: the first archived row pays
    the open, a root whose store cannot be opened (or refuses to open)
    records the miss and every later write-back skips without re-probing.
    The caller closes the connection when the batch's rows are done. Run
    refusal diagnostics share a coordinator latch across reopened sources;
    the open-failure latch separately prevents repeated connection probes.
    """

    if coordinator._writeback_source is not None:
        return coordinator._writeback_source
    if coordinator._writeback_source_failed:
        return None
    from bili_asr.services import queue_source as qs

    source = qs.open_queue_source(coordinator.root)
    if source is None:
        coordinator._writeback_source_failed = True
        return None
    coordinator._writeback_source = source
    source._asr_run_refusal_reported = coordinator._writeback_refusal_reported
    return source


def close_writeback_source(coordinator, *, outcome: str | None = None) -> None:
    """Close the write-back source, if the batch ever opened one."""

    source = coordinator._writeback_source
    coordinator._writeback_source = None
    if source is not None:
        coordinator._writeback_refusal_reported |= getattr(
            source, "_asr_run_refusal_reported", False
        )
        try:
            source.finish_asr_run(outcome=outcome)
        except Exception:
            pass
        finally:
            try:
                source.connection.close()
            except Exception:
                pass


def record_transcript_writeback_failure(
    coordinator, entry: dict[str, Any], exc: BaseException | str
) -> None:
    """Leave a repairable signal when transcript evidence could not be stored.

    The archive row has already been published when this helper runs.  A
    scalar code and timestamp on that row let a later coordinator pass
    retry the caption path without treating the durable archive as failed.
    If the manifest itself is unavailable, the diagnostic still identifies
    the work item while preserving the published outcome.
    """

    work_id = str(entry.get("work_id") or entry.get("bvid") or "unknown")
    raw_error_code = (
        str(exc) if isinstance(exc, str) else _dependency_attempts._safe_error_code(exc)
    )
    error_code = _dependency_attempts._sanitize_code_str(str(raw_error_code))
    try:
        updated = coordinator._current_entry(work_id, entry)
    except Exception:
        # The marker exists for store failures too; keep the published
        # outcome repairable even when the manifest cannot be read now.
        updated = dict(entry)
    updated["transcript_writeback_error"] = error_code
    updated["transcript_writeback_failed_at"] = utc_now_iso()
    try:
        coordinator.store.upsert(updated)
    except Exception:
        pass
    from bili_asr.diagnostics import write_stderr

    write_stderr(
        f"{coordinator.command}: transcript write-back failed for {work_id} "
        f"({error_code}); archived row retained"
    )


def clear_transcript_writeback_failure(coordinator, entry: dict[str, Any]) -> None:
    """Clear a previously recorded write-back failure after a retry succeeds."""

    updated = coordinator._current_entry(str(entry.get("work_id") or ""), entry)
    changed = False
    for field in ("transcript_writeback_error", "transcript_writeback_failed_at"):
        if field in updated:
            updated.pop(field, None)
            changed = True
    if not changed:
        return
    try:
        coordinator.store.upsert(updated)
    except Exception:
        # The transcript row is already durable; stale repair metadata is
        # preferable to turning a successful retry into a failed archive.
        pass


def record_subtitle_transcript(
    coordinator,
    *,
    entry: dict[str, Any],
    raw: dict[str, Any],
    segments: list[dict[str, Any]],
) -> bool:
    """Record a subtitle-sourced transcript row for an archived part.

    A caption archived from the raw document also owes the store a
    ``transcripts`` row (source_kind ``'subtitle-ai'``/``'subtitle-cc'``,
    through the CAPTION writer — never the ``'asr-local'`` singleton), so
    the part leaves every gap view (plan r14-routes-writeback).  The
    caption kind derives from the row's own subtitle metadata, exactly as
    the typed subtitle-arm's ``language_family`` rule derives it from a
    listed track: the harvested track's language code carries the machine
    ``ai-`` prefix when the caption is machine-generated, so
    ``'subtitle-ai'``/``'subtitle-cc'`` follow from ``sub_lan``/``sub_lan_doc``
    — never from a caller-invented literal.  A row that names no subtitle
    language at all is answered by skipping this part's write-back: the
    caption kind is genuinely ambiguous, and the plan's STOP condition
    says the gap-view row is best-effort, never a reason to refuse an
    archive that already succeeded on disk. Write-back runs after
    ``_mark_archived``, outside the archive success guard. Its outcome
    never changes the archived row or the ``archive: ok`` attempt.
    """

    from bili_asr.page_identity import writeback_identity

    identity = writeback_identity(entry)
    if identity is None:
        return True
    source_kind = _caption_source_kind_from_entry(entry)
    if source_kind is None:
        return True
    language = _caption_language_from_entry(entry)
    if language is None:
        return True
    try:
        source = queue_source_for_writeback(coordinator)
        if source is None:
            record_transcript_writeback_failure(coordinator, 
                entry, "queue_source_unavailable"
            )
            return False
        run_id = source.ensure_asr_run(coordinator.command)
        if run_id is None:
            record_transcript_writeback_failure(coordinator, 
                entry, "acquisition_run_refused"
            )
            return False
        from bili_asr.services import queue_source as qs

        stored = qs.record_caption_transcript(
            source,
            run_id=run_id,
            bvid=identity[0],
            page_index=identity[1],
            source_kind=source_kind,
            language=language,
            segments=_caption_transcript_segments(segments),
        )
        if stored is False:
            record_transcript_writeback_failure(coordinator, 
                entry, "caption_store_rejected"
            )
            return False
    except Exception as exc:
        record_transcript_writeback_failure(coordinator, entry, exc)
        return False
    clear_transcript_writeback_failure(coordinator, entry)
    return True


def record_asr_transcript(coordinator, entry: dict[str, Any], segments: list) -> None:
    """Record the locally-produced (ASR) transcript row for an archived part.

    The same write-back the ``asr``/``pilot`` in-process loops own
    (plan 20260929-asr-local-transcript-storage, Task 2), wired onto the
    coordinator/run-batch route so ``v_missing_transcript`` converges on
    every route (plan r14-routes-writeback).  Runs after the archive
    bundle is complete and the ``archive: ok`` attempt is recorded: the
    attempt ledger is the manifest-side evidence the summary reads, while
    the ``transcripts`` row is the store-side evidence the gap views read
    — the two are independent, and the best-effort write-back must never
    disturb the ledger's outcome.
    """

    from bili_asr.page_identity import writeback_identity

    identity = writeback_identity(entry)
    if identity is None:
        return
    source = queue_source_for_writeback(coordinator)
    if source is None:
        return
    run_id = source.ensure_asr_run(coordinator.command)
    if run_id is None:
        return
    from bili_asr.services import queue_source as qs
    from bili_asr.storage import TranscriptSegmentRecord

    runner = coordinator.asr_runner
    try:
        provenance = runner.provenance() if runner is not None else {}
    except Exception:
        provenance = {}
    try:
        qs.record_local_transcript(
            source,
            run_id=run_id,
            bvid=identity[0],
            page_index=identity[1],
            language=_module_asr_provenance.provenance_language(provenance),
            segments=tuple(
                TranscriptSegmentRecord(
                    start_ms=int(round(float(cue.get("start", 0.0)) * 1000)),
                    end_ms=int(round(float(cue.get("end", 0.0)) * 1000)),
                    text=str(cue.get("text", "")),
                )
                for cue in segments
            ),
            model_name=(provenance or {}).get("model_name", ""),
            model_revision=(provenance or {}).get("model_revision"),
            coverage=_module_asr_coverage.transcribed_coverage(runner),
        )
    except Exception as exc:
        # The cue shape that reached the archive writer is not one the
        # store can record; the archive on disk stands and the gap-view
        # row is supplementary evidence.
        record_transcript_writeback_failure(coordinator, entry, exc)
