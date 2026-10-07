"""Processing implementation."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr


class _AsrItemCount:
    """The printed reuse line's ASR-item denominator (D2.5).

    A one-field box, not an ``int``, because the in-process loops count the
    row at two different call depths: ``_cmd_asr`` counts inline, while
    ``pilot`` counts inside ``_pilot_archive_asr``, which has to report the
    increment to its caller.  Every path increments at the same event — the
    row's ASR stage produced a transcript — which is what ``RunCoordinator``
    counts at its own ``asr: ok`` attempt, so ``asr``/``pilot`` and ``run``
    state the same denominator for the same input.
    """

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = 0


def _asr_transcript_segments(segments: list) -> tuple:
    """Convert ASR cues to ``TranscriptSegmentRecord``s, best-effort.

    One cue the record refuses (an empty text, an ``end`` not after its
    ``start``) is answered as *this part's* failure — a ``ValueError`` the
    caller reports for the row — never as an escaping error that ends the
    batch, and never by silently dropping the segment.  Cue times are seconds
    floats on the ASR side and whole milliseconds on the storage side.
    """

    from bili_asr.storage import TranscriptSegmentRecord

    records = []
    for cue in segments:
        start_ms = int(round(float(cue.get("start", 0.0)) * 1000))
        end_ms = int(round(float(cue.get("end", 0.0)) * 1000))
        records.append(
            TranscriptSegmentRecord(start_ms=start_ms, end_ms=end_ms, text=str(cue.get("text", "")))
        )
    return tuple(records)


def _ensure_asr_run(
    queue_source, command: str, *, selector_target: str | None = None,
    requested_limit: int | None = None,
) -> None:
    """Create this invocation's one ``kind='asr'`` acquisition run, best-effort.

    One invocation is one run scope (the same shape the audio half names): the
    run is the lifecycle parent the transcript write-back's attempt rows are
    keyed to.  The created id is remembered on the ``QueueSource`` as
    ``asr_run_id``; a store that refuses the run leaves it ``None`` so the row
    loop's per-part write-back is skipped — the archive on disk is never lost
    to a store problem.
    """

    queue_source.ensure_asr_run(
        command, selector_target=selector_target, requested_limit=requested_limit,
    )


def _print_in_process_constructions(
    command: str, runner: object, asr_items: int
) -> None:
    """State one in-process ASR loop's constructions, once, on stderr (D2.6).

    ``RunCoordinator.run_batch`` prints this for the coordinator path; ``asr``
    and ``pilot`` never enter it, so they print through the same shared string
    for their own command label.  ``runner`` is ``None`` when the selection
    needed no model.

    The guard is "nothing was paid", not "no ASR items" — the same rule the
    coordinator applies: a loop that built the model and then failed every
    transcription still states ``… for 0 asr item(s)``, while a subtitle-only
    selection (no construction, no transcript) prints nothing at all.  Stderr
    keeps every command's stdout contract intact; when fd 2 is closed
    ``sys.stderr`` is ``None`` and ``print(..., file=None)`` would fall back to
    stdout, so a missing stream prints nothing rather than breaking it.
    """
    from bili_asr.pipeline.models import model_constructions_line
    from bili_asr.diagnostics import write_stderr

    constructions = (
        int(getattr(runner, "model_constructions", 0)) if runner is not None else 0
    )
    if asr_items <= 0 and constructions <= 0:
        return
    write_stderr(model_constructions_line(command, constructions, asr_items))
