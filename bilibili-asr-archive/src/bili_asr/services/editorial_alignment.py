"""Pure alignment service: pair ASR segments with caption cues, and count everything.

What it decides: which ASR segments form an aligned block, and which block (if any) each
caption cue belongs to, by attaching a cue to the block whose span contains the cue's
midpoint. It decides nothing about text: no normalization, no fuzzy matching, no editing,
no I/O. Lists go in, dataclasses come out.

What it refuses to decide: whether an unattached cue is an error. A cue may legitimately
land in an ASR VAD gap (silence the recognizer never emitted a segment for), so this module
reports such cues in ``Alignment.unattached_cues`` and counts them rather than choosing a
block for them.

The one invariant worth defending: the result is a *partition*. Every input unit lands in
exactly one bucket -- attached or unattached -- and every count is obtained by counting the
actual tuples, never by subtracting one input count from another. The 2026-09-22 proofread
wave used this same midpoint idea and silently dropped 251 of 9607 cues, because a cue whose
midpoint fell in a VAD gap matched no block and was skipped without a word. A reported empty
bucket is the difference between a partition and a subtraction, so the unattached buckets
exist even when they are empty.

Nothing outside the standard library is imported, and nothing outside these lists is touched:
no database, no paths, no child processes. It is importable anywhere and testable with plain
lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

#: Two consecutive ASR segments belong to the same block while the later segment starts
#: within this many milliseconds of the block's current end. A larger separation means the
#: recognizer went quiet long enough that the run of speech is over.
GAP_MS = 1500

SEGMENT = "segment"
CUE = "cue"


@dataclass(frozen=True)
class Unit:
    """One input unit on one side of the alignment."""

    kind: str  # "segment" | "cue"
    index: int  # 1-based order within its own side
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Block:
    """One aligned block: a maximal run of ASR segments plus the cues that fell inside it."""

    index: int  # 1-based
    start_ms: int
    end_ms: int
    segment_indexes: tuple[int, ...]  # ASR units attached
    cue_indexes: tuple[int, ...]  # caption units attached


@dataclass(frozen=True)
class AlignmentAccounting:
    """How many units went in, and into which bucket each of them went."""

    blocks: int
    segments_in: int
    segments_attached: int
    segments_unattached: int
    cues_in: int
    cues_attached: int
    cues_unattached: int


@dataclass(frozen=True)
class Alignment:
    """A complete alignment, with both sides of the partition kept explicit."""

    work_id: str
    blocks: tuple[Block, ...]
    segments: tuple[Unit, ...]  # every ASR unit in order
    cues: tuple[Unit, ...]  # every caption unit in order
    unattached_segments: tuple[Unit, ...]
    unattached_cues: tuple[Unit, ...]
    accounting: AlignmentAccounting


def normalize_segments(raw: Sequence[tuple[int, int, str]]) -> tuple[Unit, ...]:
    """Wrap ``(start_ms, end_ms, text)`` triples as ASR :class:`Unit` objects.

    Drops nothing and reorders nothing: ``index`` is the input position, 1-based, and ``text``
    is kept verbatim. An interval with ``end_ms <= start_ms`` raises :class:`ValueError`
    naming the offending index, because a degenerate interval cannot carry a midpoint.
    """
    units: list[Unit] = []
    for position, (start_ms, end_ms, text) in enumerate(raw, start=1):
        start = int(start_ms)
        end = int(end_ms)
        if end <= start:
            raise ValueError(
                f"segment index {position} has a degenerate interval: "
                f"start_ms={start} end_ms={end} (end_ms must be greater than start_ms)"
            )
        units.append(Unit(kind=SEGMENT, index=position, start_ms=start, end_ms=end, text=text))
    return tuple(units)


def _normalize_cues(raw: Sequence[tuple[int, int, str]]) -> tuple[Unit, ...]:
    """Same contract as :func:`normalize_segments`, on the caption side."""
    units: list[Unit] = []
    for position, (start_ms, end_ms, text) in enumerate(raw, start=1):
        start = int(start_ms)
        end = int(end_ms)
        if end <= start:
            raise ValueError(
                f"cue index {position} has a degenerate interval: "
                f"start_ms={start} end_ms={end} (end_ms must be greater than start_ms)"
            )
        units.append(Unit(kind=CUE, index=position, start_ms=start, end_ms=end, text=text))
    return tuple(units)


def assign_blocks(segments: Sequence[Unit], cues: Sequence[Unit]) -> tuple[Block, ...]:
    """Group ASR segments into blocks and attach cues to them by midpoint.

    Blocks come from the ASR side alone:

    * the first segment opens the first block;
    * a later segment joins the block in progress when its ``start_ms`` is within
      :data:`GAP_MS` of that block's current ``end_ms``, and otherwise opens a new block;
    * ``block.start_ms`` is the first member's start, ``block.end_ms`` the last member's end.

    A cue attaches to the block whose span contains its midpoint, tested against the closed
    interval ``block.start_ms <= mid <= block.end_ms``. Because blocks are ordered and
    separated by more than :data:`GAP_MS`, at most one block can contain a given midpoint.

    A cue whose midpoint lands in no block is *not* dropped: it is simply absent from every
    ``Block.cue_indexes``, which makes it unattached and lets the caller count it. Every
    segment, by construction, is attached to the block it opened or joined.
    """
    starts: list[int] = []
    ends: list[int] = []
    member_segments: list[list[int]] = []
    member_cues: list[list[int]] = []

    for segment in segments:
        if not ends or segment.start_ms - ends[-1] > GAP_MS:
            starts.append(segment.start_ms)
            ends.append(segment.end_ms)
            member_segments.append([])
            member_cues.append([])
        else:
            ends[-1] = segment.end_ms
        member_segments[-1].append(segment.index)

    for cue in cues:
        midpoint = (cue.start_ms + cue.end_ms) // 2
        for position, block_start in enumerate(starts):
            if block_start > midpoint:
                break  # blocks are ordered: no later block can contain the midpoint either
            if midpoint <= ends[position]:
                member_cues[position].append(cue.index)
                break
        # Falling out of the loop without a match is a legitimate outcome, not a skip:
        # the cue stays out of every block and is reported as unattached by the caller.

    return tuple(
        Block(
            index=position,
            start_ms=block_start,
            end_ms=ends[position - 1],
            segment_indexes=tuple(member_segments[position - 1]),
            cue_indexes=tuple(member_cues[position - 1]),
        )
        for position, block_start in enumerate(starts, start=1)
    )


def align_transcripts(
    work_id: str,
    asr_segments: Sequence[tuple[int, int, str]],
    caption_cues: Sequence[tuple[int, int, str]],
) -> Alignment:
    """Normalize both sides, assign blocks, and report the resulting partition.

    Every accounting figure is obtained by counting the real tuples -- attached units are
    counted out of the blocks that hold them, unattached units out of the buckets that hold
    them -- so ``*_in == *_attached + *_unattached`` on both sides by construction rather
    than by arithmetic on the inputs.
    """
    segments = normalize_segments(asr_segments)
    cues = _normalize_cues(caption_cues)
    blocks = assign_blocks(segments, cues)

    attached_segment_indexes = {
        index for block in blocks for index in block.segment_indexes
    }
    attached_cue_indexes = {index for block in blocks for index in block.cue_indexes}
    unattached_segments = tuple(
        unit for unit in segments if unit.index not in attached_segment_indexes
    )
    unattached_cues = tuple(unit for unit in cues if unit.index not in attached_cue_indexes)

    accounting = AlignmentAccounting(
        blocks=len(blocks),
        segments_in=len(segments),
        segments_attached=sum(len(block.segment_indexes) for block in blocks),
        segments_unattached=len(unattached_segments),
        cues_in=len(cues),
        cues_attached=sum(len(block.cue_indexes) for block in blocks),
        cues_unattached=len(unattached_cues),
    )

    return Alignment(
        work_id=work_id,
        blocks=blocks,
        segments=segments,
        cues=cues,
        unattached_segments=unattached_segments,
        unattached_cues=unattached_cues,
        accounting=accounting,
    )


def accounting_line(work_id: str, accounting: AlignmentAccounting) -> str:
    """Render the one-line alignment summary, without a trailing newline."""
    return (
        f"{work_id}: aligned blocks={accounting.blocks}"
        f" segments_in={accounting.segments_in}"
        f" segments_attached={accounting.segments_attached}"
        f" segments_unattached={accounting.segments_unattached}"
        f" cues_in={accounting.cues_in}"
        f" cues_attached={accounting.cues_attached}"
        f" cues_unattached={accounting.cues_unattached}"
    )


def alignment_jsonl_lines(alignment: Alignment) -> tuple[str, ...]:
    """Render the alignment as JSONL: a header object, then one record per input unit.

    The header is line 1 and carries ``blocks`` plus the six counts. Each following record is
    one ASR unit (input order) then one caption unit (input order), carrying its interval and
    the index of the block it attached to, or ``null`` when it attached to none. Records carry
    structure only: **no transcript text is ever written**, so the sidecar can be shared
    without leaking the transcript it indexes.
    """
    accounting = alignment.accounting
    lines = [
        json.dumps(
            {
                "kind": "header",
                "work_id": alignment.work_id,
                "blocks": accounting.blocks,
                "segments_in": accounting.segments_in,
                "segments_attached": accounting.segments_attached,
                "segments_unattached": accounting.segments_unattached,
                "cues_in": accounting.cues_in,
                "cues_attached": accounting.cues_attached,
                "cues_unattached": accounting.cues_unattached,
            },
            ensure_ascii=False,
        )
    ]

    block_of_segment = {
        index: block.index for block in alignment.blocks for index in block.segment_indexes
    }
    block_of_cue = {
        index: block.index for block in alignment.blocks for index in block.cue_indexes
    }

    for unit in alignment.segments:
        lines.append(
            json.dumps(
                {
                    "kind": unit.kind,
                    "index": unit.index,
                    "start_ms": unit.start_ms,
                    "end_ms": unit.end_ms,
                    "block": block_of_segment.get(unit.index),
                },
                ensure_ascii=False,
            )
        )
    for unit in alignment.cues:
        lines.append(
            json.dumps(
                {
                    "kind": unit.kind,
                    "index": unit.index,
                    "start_ms": unit.start_ms,
                    "end_ms": unit.end_ms,
                    "block": block_of_cue.get(unit.index),
                },
                ensure_ascii=False,
            )
        )
    return tuple(lines)


def render_alignment_jsonl(alignment: Alignment) -> str:
    """Render :func:`alignment_jsonl_lines` as one newline-terminated document."""
    return "\n".join(alignment_jsonl_lines(alignment)) + "\n"
