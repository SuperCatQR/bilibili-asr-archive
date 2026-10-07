"""Alignment implementation."""

from __future__ import annotations

from typing import Any
import bili_asr.asr.constants as _dependency_constants


def _clean_text(text: str) -> str:
    """The recognised text without control markers, in one line."""

    return _dependency_constants._RICH_TAG.sub("", str(text)).strip()


def _body(text: str) -> str:
    """The part of a line that carries meaning, without its closing marks."""

    return str(text).strip(_dependency_constants._CUE_CLOSING_MARKS).strip()


def _join_text(left: str, right: str) -> str:
    """Join two cue texts, keeping a separator between Latin words.

    The decoder does not always carry the space between English words, so absorbing a fragment into
    the cue before it must not glue them together.  Chinese text is unaffected: the space is only
    added between two ASCII alphanumerics.
    """

    if (
        left
        and right
        and left[-1].isascii()
        and left[-1].isalnum()
        and right[0].isascii()
        and right[0].isalnum()
    ):
        return f"{left} {right}"
    return left + right


def _thread_text(text: str, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the recognised text's marks back onto the aligned units.

    The aligner times the units it is given, and for Chinese those are the characters **without
    punctuation**: a mark has no audio to align to, so it never comes back in the unit list.  The
    archive's product is the recognised text, so every character of ``text`` is threaded back here —
    exactly once, in order — with a timeable unit keeping its own timing and a mark inheriting the
    instant of the piece beside it.  This step is what keeps the FunASR-era rule "cue text is the
    recognised text verbatim" true; without it both the marks and the sentence-ending rule that
    closes cues on them are lost (measured: 287 vs ~983 cues on a 47-minute item, and 1 224 marks
    missing).
    """

    pieces: list[dict[str, Any]] = []
    index = 0
    position = 0
    while position < len(text):
        unit = units[index] if index < len(units) else None
        unit_text = _clean_text(unit.get("text", "")) if isinstance(unit, dict) else ""
        if unit_text and text.startswith(unit_text, position):
            pieces.append({
                "text": unit_text,
                "start": float(unit["start_time"]),
                "end": float(unit["end_time"]),
            })
            position += len(unit_text)
            index += 1
            continue
        anchor = pieces[-1]["end"] if pieces else (
            float(units[index]["start_time"]) if index < len(units) else 0.0
        )
        pieces.append({"text": text[position], "start": anchor, "end": anchor})
        position += 1
    # A unit the text does not account for should not exist; if one does it is kept rather than
    # dropped, and naming that case is the audit's job, not this function's.
    for unit in units[index:]:
        if isinstance(unit, dict) and _clean_text(unit.get("text", "")):
            pieces.append({
                "text": _clean_text(unit["text"]),
                "start": float(unit["start_time"]),
                "end": float(unit["end_time"]),
            })
    return pieces


def _aligned_cues(pieces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape threaded pieces into subtitle cues, in one pass.

    This is the FunASR-era state machine (plan §13.2), re-driven by aligned pieces instead of FunASR
    tokens: the rules were measured on this corpus and are product decisions, so only their input
    changed.  A cue closes on a sentence-ending mark, when :data:`_CUE_MAX_CHARS` is reached, or on a
    pause of at least :data:`_CUE_MAX_GAP_SECONDS` **in a cue that can already stand on its own**; a
    cue that is still only marks, or below :data:`_CUE_MIN_CHARS` / :data:`_CUE_MIN_SECONDS`, is
    absorbed by the cue before it; and a closing mark that arrives at a boundary is handed back to
    the cue it closes.  Nothing shapes the text a second time, and nothing is dropped.
    """

    cues: list[dict[str, Any]] = []
    parts: list[str] = []
    start: float | None = None
    last_end: float | None = None
    pending = ""  # text the cue before it could not take

    def formed() -> bool:
        return (
            len(_body("".join(parts))) >= _dependency_constants._CUE_MIN_CHARS
            and (last_end or 0.0) - (start or 0.0) >= _dependency_constants._CUE_MIN_SECONDS
        )

    def reset() -> None:
        nonlocal parts, start, last_end, pending
        parts, start, last_end, pending = [], None, None, ""

    def hand_back(piece: str, end: float) -> None:
        """Give a closing mark to the cue it actually closes."""

        cues[-1]["text"] = _join_text(str(cues[-1]["text"]), piece)
        cues[-1]["end"] = max(float(cues[-1]["end"]), end)

    def close() -> None:
        nonlocal pending
        text = _clean_text(pending + "".join(parts))
        if not text:
            reset()
            return
        span = last_end if last_end is not None else (start or 0.0)
        undersized = len(_body(text)) < _dependency_constants._CUE_MIN_CHARS or (span - (start or 0.0)) < _dependency_constants._CUE_MIN_SECONDS
        if cues and (undersized or not _body(text)):
            # a fragment joins the cue before it: the character ceiling is a readability target,
            # and losing text to it would be worse
            previous = cues[-1]
            previous["text"] = _join_text(str(previous["text"]), text)
            previous["end"] = max(float(previous["end"]), span)
            reset()
            return
        cues.append({"start": start, "end": span, "text": text})
        reset()

    def append_piece(text: str) -> None:
        """Append one aligned fragment, repairing omitted Latin separators at the boundary."""

        if not parts:
            parts.append(text)
        else:
            # Qwen's aligner may return one word per piece without the whitespace that was
            # present in the recognised text.  Apply the same boundary rule used when cues
            # are merged, before length/closing decisions inspect the accumulated text.
            parts[-1] = _join_text(parts[-1], text)

    for piece in pieces:
        if not isinstance(piece, dict):
            continue
        text = str(piece.get("text") or "")
        if not text:
            continue
        begin, end = float(piece["start"]), float(piece["end"])
        mark = text.strip()
        if start is None:
            # a closing mark never opens a cue: it belongs to the cue it closes
            if mark and mark[0] in _dependency_constants._CUE_CLOSING_MARKS:
                if cues:
                    hand_back(text, end)
                else:
                    pending += text
                continue
            start = begin
        elif begin - (last_end if last_end is not None else begin) >= _dependency_constants._CUE_MAX_GAP_SECONDS and formed():
            close()
            if mark and mark[0] in _dependency_constants._CUE_CLOSING_MARKS and cues:
                hand_back(text, end)
                continue
            start = begin
        append_piece(text)
        last_end = end
        if mark in _dependency_constants._SENTENCE_ENDINGS or len(pending + "".join(parts)) >= _dependency_constants._CUE_MAX_CHARS:
            close()
    close()
    return cues


def _characters_from_pieces(
    pieces: list[dict[str, Any]], cues: list[dict[str, Any]]
) -> dict[str, Any]:
    """The character-level record for ``cues`` built from ``pieces``.

    ``_thread_text`` is the last step that still knows which character of the transcript each
    instant belongs to: ``_aligned_cues`` projects that stream onto readable cue text and, in
    doing so, drops the whitespace that sat on a cue boundary (measured on one real 47-minute
    item: 98 characters, and every one of them whitespace).  So the record cannot be a dump of
    the pieces — it is the pieces **projected onto the published cue text**, walked in step so
    every character of that text keeps the instant the aligner gave it.

    A character the cue text carries and the pieces do not — the separator ``_join_text``
    inserts between two Latin words — inherits the instant of the piece beside it, the same
    rule a punctuation mark gets in :func:`_thread_text`.  A character neither stream explains
    raises :class:`ValueError`: the record would be a claim about the cue text that the cue
    text contradicts.

    Seconds, like ``segments``, and three parallel arrays rather than one dict per character.  The
    size argument is in the plan's D-5 correction, not here: the shape choice is not what drives the
    cost (the dominant term is the digit count of the timestamps themselves, and the writer's
    pretty-printing), which is why an earlier version of this docstring quoted a figure the plan has
    since withdrawn.
    """

    text = "".join(str(cue.get("text", "")) for cue in cues)
    stream: list[tuple[str, float, float]] = [
        (character, float(piece["start"]), float(piece["end"]))
        for piece in pieces
        for character in str(piece.get("text", ""))
    ]
    starts: list[float] = []
    ends: list[float] = []
    index = 0
    anchor = stream[0][1] if stream else 0.0
    for position, character in enumerate(text):
        # Whitespace the cue text does not carry: it sat on a cue boundary and was stripped.
        while index < len(stream) and stream[index][0] != character and stream[index][0].isspace():
            index += 1
        if index < len(stream) and stream[index][0] == character:
            start, end = stream[index][1], stream[index][2]
            index += 1
            anchor = end
        elif character.isspace():
            start = end = anchor
        else:
            raise ValueError(
                "the cue text is not a projection of the threaded pieces: "
                f"character {position} is in no piece"
            )
        starts.append(start)
        ends.append(end)
    if any(not character.isspace() for character, *_ in stream[index:]):
        raise ValueError(
            "the cue text is not a projection of the threaded pieces: "
            f"{len(stream) - index} piece characters are not in the cue text"
        )
    return {"text": text, "starts": starts, "ends": ends}
