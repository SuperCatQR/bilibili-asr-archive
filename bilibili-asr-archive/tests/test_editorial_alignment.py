"""Tests for the pure editorial alignment service.

The load-bearing property is that alignment is a *partition*: every input unit is
counted exactly once, on either the attached or the unattached side. The 2026-09-22
proofread wave lost 251 of 9607 cues because a midpoint landing in an ASR VAD gap
matched no block and was skipped silently; these tests make that failure loud.
"""

from __future__ import annotations

import json

import pytest

from bili_asr.services.editorial_alignment import (
    GAP_MS,
    accounting_line,
    align_transcripts,
    alignment_jsonl_lines,
    assign_blocks,
    normalize_segments,
    render_alignment_jsonl,
)

# --- fixtures, inline by design (no shared fixtures) -------------------------

CLEAN_SEGMENTS = [(0, 1000, "first"), (1000, 2000, "second"), (2000, 3000, "third")]
CLEAN_CUES = [(100, 900, "甲"), (1100, 1900, "乙"), (2100, 2900, "丙")]

#: Two ASR segments separated by a gap much wider than ``GAP_MS``.
GAPPY_SEGMENTS = [(0, 1000, "opening"), (5000, 6000, "later")]
GAPPY_CUES = [(2000, 3000, "orphan in the void")]


def forty_cues_a_third_in_gaps() -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]]]:
    """40 cues on a 1000 ms lattice; ASR blocks cover every cue whose index % 3 != 2."""
    segments: list[tuple[int, int, str]] = []
    for pair in range(13):  # covers cues 0/1, 3/4, ... 36/37
        base = pair * 3000
        segments.append((base, base + 1200, f"seg{pair}"))
    segments.append((39000, 39200, "seg-last"))  # covers cue 39
    cues = [(index * 1000, index * 1000 + 200, f"cue{index}") for index in range(40)]
    return segments, cues


# --- 1. the clean case -------------------------------------------------------


def test_accounting_is_a_partition_on_a_clean_pair() -> None:
    alignment = align_transcripts("BV1CLEAN", CLEAN_SEGMENTS, CLEAN_CUES)
    accounting = alignment.accounting

    assert accounting.segments_in == accounting.segments_attached + accounting.segments_unattached
    assert accounting.cues_in == accounting.cues_attached + accounting.cues_unattached
    assert accounting.segments_in == 3
    assert accounting.cues_in == 3
    assert accounting.segments_attached == 3
    assert accounting.cues_attached == 3
    assert accounting.cues_unattached == 0
    assert accounting.blocks == 1
    assert accounting.blocks == len(alignment.blocks)
    assert alignment.unattached_cues == ()
    assert alignment.unattached_segments == ()


# --- 2. R2: the midpoint-in-gap cue that the old wave lost -------------------


def test_a_cue_whose_midpoint_falls_in_an_asr_gap_is_unattached_and_counted() -> None:
    alignment = align_transcripts("BV1GAP", GAPPY_SEGMENTS, GAPPY_CUES)
    accounting = alignment.accounting

    # the two ASR segments are more than GAP_MS apart, so they open two blocks ...
    assert accounting.blocks == 2
    assert accounting.segments_attached == 2
    assert accounting.segments_unattached == 0

    # ... and the cue's midpoint (2500 ms) sits in the void between them.
    assert accounting.cues_unattached == 1
    assert accounting.cues_attached == 0
    assert accounting.cues_in == 1
    assert accounting.cues_in == accounting.cues_attached + accounting.cues_unattached

    # it is reported, not dropped.
    assert [unit.index for unit in alignment.unattached_cues] == [1]
    assert alignment.unattached_cues[0].text == GAPPY_CUES[0][2]
    assert len(alignment.cues) == 1


# --- 3. no cue is ever dropped ----------------------------------------------


def test_no_cue_is_ever_dropped() -> None:
    segments, cues = forty_cues_a_third_in_gaps()

    alignment = align_transcripts("BV1FORTY", segments, cues)
    accounting = alignment.accounting

    assert accounting.cues_in == 40
    assert len(alignment.cues) == 40
    assert accounting.cues_unattached == 13  # every index % 3 == 2 lands in a gap
    assert accounting.cues_attached == 27
    assert accounting.cues_in == accounting.cues_attached + accounting.cues_unattached
    assert len(alignment.unattached_cues) == accounting.cues_unattached
    assert accounting.segments_in == len(segments)
    assert accounting.segments_in == accounting.segments_attached + accounting.segments_unattached


# --- 4. ASR segments partition into blocks ----------------------------------


def test_segments_partition_into_blocks_without_loss() -> None:
    raw = [
        (0, 500, "s1"),
        (500, 1000, "s2"),  # joins the opening block (gap 0)
        (4000, 4500, "s3"),  # gap 3000 > GAP_MS => new block
        (13000, 13500, "s4"),  # gap 8500 => new block
        (13500, 14000, "s5"),  # joins it
    ]
    segments = normalize_segments(raw)
    assert len(segments) == 5

    blocks = assign_blocks(segments, ())
    assert [block.index for block in blocks] == [1, 2, 3]
    assert sum(len(block.segment_indexes) for block in blocks) == len(segments)

    alignment = align_transcripts("BV1BLOCKS", raw, [(0, 500, "c")])
    assert alignment.accounting.segments_in == sum(
        len(block.segment_indexes) for block in alignment.blocks
    )
    assert alignment.accounting.segments_in == (
        alignment.accounting.segments_attached + alignment.accounting.segments_unattached
    )


# --- 5. block ordering -------------------------------------------------------


def test_blocks_are_ordered_and_non_overlapping() -> None:
    segments, cues = forty_cues_a_third_in_gaps()
    alignment = align_transcripts("BV1ORDER", segments, cues)

    indexes = [block.index for block in alignment.blocks]
    assert indexes == list(range(1, len(indexes) + 1))

    starts = [block.start_ms for block in alignment.blocks]
    assert starts == sorted(starts)

    for earlier, later in zip(alignment.blocks, alignment.blocks[1:]):
        assert earlier.end_ms <= later.start_ms
        assert later.start_ms - earlier.end_ms > GAP_MS


# --- 6. every attached index resolves ---------------------------------------


def test_every_attached_unit_points_at_an_existing_block() -> None:
    segments, cues = forty_cues_a_third_in_gaps()
    alignment = align_transcripts("BV1RESOLVE", segments, cues)

    segment_by_index = {unit.index: unit for unit in alignment.segments}
    cue_by_index = {unit.index: unit for unit in alignment.cues}

    for block in alignment.blocks:
        for index in block.segment_indexes:
            assert segment_by_index[index].kind == "segment"
        for index in block.cue_indexes:
            assert cue_by_index[index].kind == "cue"

    attached_segments = [index for block in alignment.blocks for index in block.segment_indexes]
    attached_cues = [index for block in alignment.blocks for index in block.cue_indexes]
    assert len(attached_segments) == len(set(attached_segments))
    assert len(attached_cues) == len(set(attached_cues))
    assert len(attached_segments) == alignment.accounting.segments_attached
    assert len(attached_cues) == alignment.accounting.cues_attached


# --- 7. bad intervals --------------------------------------------------------


def test_bad_interval_raises_value_error_with_the_index() -> None:
    with pytest.raises(ValueError) as degenerate:
        normalize_segments([(0, 1000, "ok"), (5000, 5000, "zero length")])
    assert "2" in str(degenerate.value)

    with pytest.raises(ValueError) as reversed_interval:
        normalize_segments([(6000, 5000, "backwards")])
    assert "1" in str(reversed_interval.value)


# --- 8. the accounting line --------------------------------------------------


def test_accounting_line_shape() -> None:
    alignment = align_transcripts("BV1GAP", GAPPY_SEGMENTS, GAPPY_CUES)
    accounting = alignment.accounting
    line = accounting_line(alignment.work_id, accounting)

    assert not line.endswith("\n")
    assert line.startswith("BV1GAP: aligned blocks=")
    assert line == (
        "BV1GAP: aligned blocks=2 segments_in=2 segments_attached=2 segments_unattached=0 "
        "cues_in=1 cues_attached=0 cues_unattached=1"
    )
    for pair in (
        f"blocks={accounting.blocks}",
        f"segments_in={accounting.segments_in}",
        f"segments_attached={accounting.segments_attached}",
        f"segments_unattached={accounting.segments_unattached}",
        f"cues_in={accounting.cues_in}",
        f"cues_attached={accounting.cues_attached}",
        f"cues_unattached={accounting.cues_unattached}",
    ):
        assert pair in line


# --- 9-11. the JSONL sidecar (compass D16) -----------------------------------


def test_jsonl_header_is_line_one_and_carries_blocks_plus_six_counts() -> None:
    segments, cues = forty_cues_a_third_in_gaps()
    alignment = align_transcripts("BV1JSONL", segments, cues)
    accounting = alignment.accounting

    lines = alignment_jsonl_lines(alignment)
    header = json.loads(lines[0])

    assert list(header.keys()) == [
        "kind",
        "work_id",
        "blocks",
        "segments_in",
        "segments_attached",
        "segments_unattached",
        "cues_in",
        "cues_attached",
        "cues_unattached",
    ]
    assert header["kind"] == "header"
    assert header["work_id"] == "BV1JSONL"
    assert header["blocks"] == len(alignment.blocks)
    assert header["segments_in"] == accounting.segments_in
    assert header["segments_attached"] == accounting.segments_attached
    assert header["segments_unattached"] == accounting.segments_unattached
    assert header["cues_in"] == accounting.cues_in
    assert header["cues_attached"] == accounting.cues_attached
    assert header["cues_unattached"] == accounting.cues_unattached


def test_jsonl_has_one_line_per_input_unit_plus_the_header() -> None:
    segments, cues = forty_cues_a_third_in_gaps()
    alignment = align_transcripts("BV1LINES", segments, cues)
    accounting = alignment.accounting

    lines = alignment_jsonl_lines(alignment)
    assert len(lines) == 1 + accounting.segments_in + accounting.cues_in

    records = [json.loads(line) for line in lines[1:]]
    assert [record["kind"] for record in records] == (
        ["segment"] * accounting.segments_in + ["cue"] * accounting.cues_in
    )

    attached = {
        "segment": [index for block in alignment.blocks for index in block.segment_indexes],
        "cue": [index for block in alignment.blocks for index in block.cue_indexes],
    }
    unattached = {
        "segment": [unit.index for unit in alignment.unattached_segments],
        "cue": [unit.index for unit in alignment.unattached_cues],
    }
    for record in records:
        kind = record["kind"]
        header_keys = ["kind", "index", "start_ms", "end_ms", "block"]
        assert list(record.keys()) == header_keys
        if record["index"] in attached[kind]:
            assert record["block"] is not None
        elif record["index"] in unattached[kind]:
            assert record["block"] is None
        else:  # pragma: no cover - a unit in neither bucket is the bug this task exists for
            raise AssertionError(f"{kind} {record['index']} is in neither bucket")

    assert [record["index"] for record in records[: accounting.segments_in]] == list(
        range(1, accounting.segments_in + 1)
    )
    assert [record["index"] for record in records[accounting.segments_in :]] == list(
        range(1, accounting.cues_in + 1)
    )


def test_jsonl_carries_no_transcript_text() -> None:
    secret_texts = [
        "ZQTOKENONE",
        "ZQTOKENTWO",
        "ZQTOKENTHREE",
        "ZQTOKENFOUR",
        "ZQTOKENFIVE",
    ]
    alignment = align_transcripts(
        "BV1PURE",
        [(0, 1000, secret_texts[0]), (1000, 2000, secret_texts[1]), (9000, 10000, secret_texts[2])],
        [(500, 1500, secret_texts[3]), (3000, 4000, secret_texts[4])],
    )

    output = render_alignment_jsonl(alignment)
    for text in secret_texts:
        assert text not in output
    assert output.endswith("\n")
    assert output.count("\n") == len(alignment_jsonl_lines(alignment))
    assert render_alignment_jsonl(alignment) == "\n".join(alignment_jsonl_lines(alignment)) + "\n"


# --- 12. the interval convention is pinned at the boundary -------------------
# The docstring says the midpoint test is the CLOSED interval
# block.start_ms <= mid <= block.end_ms. Without this test the ``<=`` could drift to
# ``<`` (a half-open convention) and all the other tests would still pass.


def test_a_cue_midpoint_on_a_block_end_attaches_and_one_ms_past_falls_out() -> None:
    segments = [(0, 2000, "opening")]
    cues = [
        (1800, 2200, "midpoint exactly on the block end"),  # mid = 2000
        (1801, 2201, "midpoint one ms past the block end"),  # mid = 2001
    ]

    alignment = align_transcripts("BV1BOUNDARY", segments, cues)
    accounting = alignment.accounting

    assert accounting.blocks == 1
    assert accounting.cues_in == 2
    assert accounting.cues_attached == 1
    assert accounting.cues_unattached == 1
    assert accounting.cues_in == accounting.cues_attached + accounting.cues_unattached

    # the cue whose midpoint lands exactly on block.end_ms is in the block ...
    assert alignment.blocks[0].end_ms == 2000
    assert alignment.blocks[0].cue_indexes == (1,)
    # ... and the cue one millisecond past it is not, it is bucketed as unattached.
    assert [unit.index for unit in alignment.unattached_cues] == [2]
    assert alignment.unattached_cues[0].text == cues[1][2]


# --- 13-14. time order is an enforced input contract -------------------------
# Out-of-order input used to be an undocumented assumption: an inverted block span would
# mis-attach cues silently (the partition bar still held, so nothing was lost, but the
# mis-attachment is the defect class this module exists to expose). The contract is now
# enforced at the boundary -- rejected, never silently sorted.


def test_out_of_order_segments_are_rejected_with_the_index() -> None:
    with pytest.raises(ValueError) as rejected:
        normalize_segments([(0, 1000, "first"), (5000, 6000, "second"), (3000, 4000, "earlier")])
    message = str(rejected.value)
    assert "index 3" in message
    assert "time order" in message
    assert "3000" in message and "5000" in message

    # the rule is non-decreasing, not strictly increasing: coincident starts are legitimate
    units = normalize_segments([(0, 1000, "a"), (0, 1200, "b"), (1500, 2000, "c")])
    assert [unit.index for unit in units] == [1, 2, 3]


def test_out_of_order_cues_are_rejected_with_the_index() -> None:
    with pytest.raises(ValueError) as rejected:
        align_transcripts(
            "BV1UNSORTED",
            [(0, 1000, "opening")],
            [(0, 500, "first"), (4000, 5000, "later"), (2000, 3000, "earlier")],
        )
    message = str(rejected.value)
    assert "cue index 3" in message
    assert "time order" in message
    assert "2000" in message and "4000" in message

