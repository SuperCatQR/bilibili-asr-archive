"""Unit contract for the pure transcript projection.

``bili_asr.services.transcript_projection`` decides one winner per part and
shapes the two things the command passes on: the ``segments`` list the archive
writer consumes, and the fifteen-key manifest row.  Every case here is a mapping
in and a mapping (or tuple) out — no database, no CLI, no filesystem — because
the read belongs to ``TranscriptRepository`` and the write to the composition
root (contract §8).  Anchors are
``{ITERATION_DIR}/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md``:
§3.2 the total order, §3.3 the ms→s conversion, §3.4 the two rendered store
facts, §5.1 the row's key set, §6 ``asr-local``.

Which case earns which claim: the winner rule is cases 1–3 against the read's
own row order, the row's key set is case 8.  Case 12 is the one place the
mirrored family rule is compared with its home instead of with a literal, and
case 13 is the order claim case 4 cannot separate from a re-sort (both added by
the L2 fix round; per-case notes below).  The provenance absence in case 10
is earned inside that case — its fabricated ``asr-local`` row carries the
non-null ``model_id`` an invented ``asr_*`` key would read, and it is published
beside a caption row, so the case fails both on an invented key and on a row
dropped by kind.  No case here covers the repository read or the CLI.
"""

import time

import pytest

from bili_asr.services import subtitle_ingest
from bili_asr.services import transcript_projection
from bili_asr.services.transcript_projection import (
    ARCHIVED_STATUS,
    LANGUAGE_FAMILY_ORDER,
    SOURCE_KIND_RANK,
    ordered_candidates,
    projection_row,
    writer_segments,
)
from bili_asr.storage.models import TranscriptSegmentRecord

#: §2.1's part context: what a candidate carries out of the read, and no more.
#: ``pubdate`` and ``video_title`` are the video's own columns, carried beside
#: the part's because the read joins ``videos`` for them and a caller holding
#: only a candidate could not recover them.
PART_KEYS = {
    "video_part_id",
    "bvid",
    "page_index",
    "cid",
    "part_title",
    "duration_ms",
    "pubdate",
    "video_title",
}
#: §2.1's identity columns: the winning transcript's own keys.
IDENTITY_KEYS = {
    "transcript_id",
    "source_kind",
    "language",
    "model_id",
    "version",
    "content_sha256",
    "created_at",
}
#: §5.1's fifteen keys, verbatim: the bridge's nine, this publication's four
#: products, and the published identity in the readers' vocabulary.
ROW_FIELDS = {
    "work_id",
    "bvid",
    "page_index",
    "cid",
    "title",
    "duration_s",
    "pubdate",
    "pubdate_str",
    "status",
    "srt_path",
    "vtt_path",
    "txt_path",
    "md_path",
    "raw_path",
    "source",
    "language",
}

PUBDATE = 1_700_000_000
#: ``1_700_000_000`` is ``2023-11-14T22:13:20Z``, whose **local** day on this
#: ``+08:00`` host is the 15th.  The literal therefore discriminates against a
#: ``localtime`` rendering here; case 11 supplies both clocks so the check does
#: not depend on where this file runs.
PUBDATE_STR = "2023-11-14"
#: ``86_399`` is ``1970-01-01T23:59:59Z`` — the second case 11 pins its stubs to.
PUBDATE_UTC_DAY_EDGE = 86_399

CONTENT_SHA = "9f" * 32

#: The four root-relative names ``write_archive`` returns (``archive.py:503``),
#: plus a fifth key of the kind a caller may hold: §5.1's key set admits the four.
PATHS = {
    "srt_path": "transcripts/BV1xx4y1zz.p2/bundle.srt",
    "vtt_path": "transcripts/BV1xx4y1zz.p2/bundle.vtt",
    "txt_path": "transcripts/BV1xx4y1zz.p2/bundle.txt",
    "md_path": "transcripts/BV1xx4y1zz.p2/bundle.md",
    "raw_path": "transcripts/BV1xx4y1zz.p2/bundle.raw.json",
    "bundle_marker_path": "transcripts/BV1xx4y1zz.p2/bundle.srt.bundle-ready",
}


def _row(
    *,
    video_part_id=41,
    bvid="BV1xx4y1zz",
    page_index=2,
    cid=987_654,
    part_title="第一部分：开场",
    duration_ms=1_800_000,
    pubdate=PUBDATE,
    transcript_id=1,
    source_kind="subtitle-cc",
    language="zh-CN",
    model_id=None,
    version=1,
    created_at=PUBDATE - 60,
    video_title="哲学视频",
):
    """One ``dict(row)`` of the §2.1 relation, attempt columns excluded."""
    return {
        "video_part_id": video_part_id,
        "bvid": bvid,
        "page_index": page_index,
        "cid": cid,
        "part_title": part_title,
        "duration_ms": duration_ms,
        "pubdate": pubdate,
        "video_title": video_title,
        "transcript_id": transcript_id,
        "source_kind": source_kind,
        "language": language,
        "model_id": model_id,
        "version": version,
        "content_sha256": CONTENT_SHA,
        "created_at": created_at,
    }


def _only(rows):
    """The one candidate §2.1's relation for a single part collapses to."""
    candidates = ordered_candidates(rows)
    assert len(candidates) == 1
    return candidates[0]


def test_the_winner_is_the_uploader_caption_over_the_machine_caption():
    """§3.2 key 1, on the pair that separates it from key 2.

    The machine caption holds the better language (``zh``, while the uploader
    caption's family is not in the order at all), so an implementation that
    ranked the family before the kind would pick the machine one: kind 1 before
    kind 2 is what this pair measures.
    """
    assert SOURCE_KIND_RANK == {"subtitle-cc": 0, "subtitle-ai": 1, "asr-local": 2}

    winner = _only(
        [
            _row(transcript_id=1, source_kind="subtitle-ai", language="ai-zh", version=3),
            _row(transcript_id=2, source_kind="subtitle-cc", language="ja-JP", version=1),
        ]
    )

    assert winner.transcript["source_kind"] == "subtitle-cc"
    assert winner.transcript["transcript_id"] == 2
    assert winner.transcript["version"] == 1


def test_the_winner_is_the_latest_version_of_the_chosen_identity():
    """§3.2 key 4 descends, and it decides by itself on one identity.

    All three rows share the store's identity ``(source_kind, language)``, so
    only the version direction separates them.  The read hands them newest first
    (§2.1), where "the first row of the part" would pass by accident; the second
    arm hands the same rows oldest first, so a ``version ASC`` regression fails
    visibly and the two orders must answer the same candidate.
    """
    rows = [
        _row(transcript_id=3, source_kind="subtitle-ai", language="ai-zh", version=3),
        _row(transcript_id=2, source_kind="subtitle-ai", language="ai-zh", version=2),
        _row(transcript_id=1, source_kind="subtitle-ai", language="ai-zh", version=1),
    ]

    assert _only(rows).transcript["version"] == 3
    assert _only(list(reversed(rows))) == _only(rows)


def test_the_language_family_order_ranks_zh_before_en_and_the_code_breaks_the_tie():
    """§3.2 keys 2 and 3, each on a pair the other key cannot settle.

    * ``ai-zh`` over ``ai-en``: one kind, and the family has to see through the
      ``ai-`` prefix — read as a family, both codes are ``ai`` and the tiebreak
      picks English, the consequence §3.2 names out loud.
    * ``en-US`` over ``de-DE``: ``de-DE`` sorts first as a *code*, so only the
      family rank can prefer English here.
    * ``de-DE`` over ``ja-JP``: two families outside the order share its last
      rank, and the code is the tiebreak between them.
    * ``zh-CN`` over ``zh-Hant``: one family, two codes the store holds no
      preference between, and the newer version is deliberately not the winner.
    """
    assert (
        _only(
            [
                _row(source_kind="subtitle-ai", language="ai-en"),
                _row(source_kind="subtitle-ai", language="ai-zh"),
            ]
        ).transcript["language"]
        == "ai-zh"
    )
    assert (
        _only(
            [
                _row(language="de-DE"),
                _row(language="en-US"),
            ]
        ).transcript["language"]
        == "en-US"
    )
    assert (
        _only(
            [
                _row(language="de-DE"),
                _row(language="ja-JP"),
            ]
        ).transcript["language"]
        == "de-DE"
    )
    assert (
        _only(
            [
                _row(transcript_id=1, language="zh-CN", version=1),
                _row(transcript_id=2, language="zh-Hant", version=5),
            ]
        ).transcript["language"]
        == "zh-CN"
    )


def test_ordered_candidates_yields_one_candidate_per_part_in_the_locked_order():
    """§2.1's order is the read's; §3.2 collapses its rows into one per part.

    The rows arrive as §2.1's query returns them — ``bvid``, ``page_index``,
    then the identity keys with ``version DESC`` — through an iterator, because
    the signature takes any ``Iterable``.  The first part holds two identities,
    so the "one candidate per part" claim has a live falsifier: a candidate per
    row would answer four.
    """
    rows = [
        _row(video_part_id=41, bvid="BV1aa", page_index=0, source_kind="subtitle-ai", language="ai-zh"),
        _row(video_part_id=41, bvid="BV1aa", page_index=0, transcript_id=2, source_kind="subtitle-cc", language="zh-CN"),
        _row(video_part_id=42, bvid="BV1aa", page_index=1),
        _row(video_part_id=51, bvid="BV1bb", page_index=0),
    ]

    candidates = ordered_candidates(row for row in rows)

    assert len(rows) == 4
    assert [candidate.work_id for candidate in candidates] == [
        "BV1aa:p0",
        "BV1aa:p1",
        "BV1bb:p0",
    ]
    winner = candidates[0]
    assert set(winner.part) == PART_KEYS
    assert set(winner.transcript) == IDENTITY_KEYS
    assert winner.transcript["source_kind"] == "subtitle-cc"  # §3.2 key 1
    assert winner.part["video_part_id"] == 41
    assert winner.part["cid"] == 987_654
    assert winner.part["part_title"] == "第一部分：开场"
    assert winner.part["duration_ms"] == 1_800_000
    assert winner.part["pubdate"] == PUBDATE


def test_limit_parts_bounds_parts_not_transcript_rows():
    """§2.2's bound is in parts, and it is validated like the repository's own.

    The first part holds three stored versions, so a bound applied to rows would
    stop inside it and answer two candidates of one part.  The validation arms
    are the shipped ``list_pending_subtitle_parts`` discipline
    (``database.py:1115-1119``), which §2.2 gives the command as the same exit
    ``1``.
    """
    versions = [
        _row(video_part_id=41, bvid="BV1aa", page_index=0, transcript_id=v, version=v)
        for v in (3, 2, 1)
    ]
    rows = versions + [
        _row(video_part_id=42, bvid="BV1aa", page_index=1),
        _row(video_part_id=51, bvid="BV1bb", page_index=0),
    ]

    assert [c.work_id for c in ordered_candidates(rows, limit=2)] == [
        "BV1aa:p0",
        "BV1aa:p1",
    ]
    assert [c.work_id for c in ordered_candidates(rows)] == [
        "BV1aa:p0",
        "BV1aa:p1",
        "BV1bb:p0",
    ]
    assert ordered_candidates(rows, limit=3) == ordered_candidates(rows)

    with pytest.raises(TypeError):
        ordered_candidates(rows, limit=True)
    with pytest.raises(TypeError):
        ordered_candidates(rows, limit="2")
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ordered_candidates(rows, limit=bad)


def test_writer_segments_convert_ms_to_seconds_and_leave_the_text_alone():
    """§3.3: ``/1000`` exactly, in ordinal order, text verbatim.

    The text carries the punctuation a "cleaner" would rewrite (a full-width
    comma and an ellipsis) and neither endpoint is a whole second, so the exact
    list equality below fails on any rewriting, rounding or re-ordering.  The
    millisecond round-trip is the SRT renderer's own arithmetic
    (``asr.py:851``: ``round(seconds * 1000)``), so a cue's printed times are the
    store's milliseconds exactly and no drift accumulates.
    """
    records = (
        TranscriptSegmentRecord(start_ms=460, end_ms=3_741, text="那，好吧…"),
        TranscriptSegmentRecord(start_ms=3_741, end_ms=9_820, text="第二句"),
    )

    segments = writer_segments(records)

    assert isinstance(segments, list)
    assert segments == [
        {"start": 0.46, "end": 3.741, "text": "那，好吧…"},
        {"start": 3.741, "end": 9.82, "text": "第二句"},
    ]
    for segment, record in zip(segments, records):
        assert round(segment["start"] * 1000) == record.start_ms
        assert round(segment["end"] * 1000) == record.end_ms
    # The writer reads these three keys and, for its confidence summary,
    # `segment.get("confidence")` — §4.2's omission is that no fourth key exists.
    assert all(set(segment) == {"start", "end", "text"} for segment in segments)


def test_a_zero_segment_body_is_refused_rather_than_published_empty():
    """§7's ``empty_transcript``: the refusal is here, not in the writer.

    ``write_archive`` would publish an empty ``srt``/``txt`` and a sidecar with
    no cue, so the projection refuses the body first and the command maps this
    ``ValueError`` onto its own bounded reason.  A stored ``TranscriptRecord``
    is never empty (``models.py:382-383``), so the input is fabricated on
    purpose: the branch is the contract's and must keep answering if a reader
    ever hands one over.
    """
    for empty in ((), []):
        with pytest.raises(ValueError):
            writer_segments(empty)


def test_projection_row_carries_the_declared_fifteen_keys_and_the_derived_field_set():
    """§5.1's fifteen keys, with the four fields this service derives itself.

    ``duration_s`` is the bridge's conversion, imported rather than re-derived
    (§3.4) — the sub-second arm shows the floor's clamp travels with it — and
    the four product paths are copied exactly as the caller recorded them, while
    any fifth key of the mapping it hands over stays off the row.
    """
    candidate = _only([_row()])

    row = projection_row(candidate.part, candidate.transcript, PATHS)

    assert set(row) == ROW_FIELDS
    assert row["work_id"] == "BV1xx4y1zz:p2"
    assert row["bvid"] == "BV1xx4y1zz"
    assert row["page_index"] == 2
    assert row["cid"] == 987_654
    assert row["title"] == "第一部分：开场"
    assert row["duration_s"] == 1800
    assert row["pubdate"] == PUBDATE
    assert row["pubdate_str"] == PUBDATE_STR
    assert row["status"] == ARCHIVED_STATUS == "archived"
    assert row["source"] == "subtitle-cc"
    assert row["language"] == "zh-CN"
    for key in ("srt_path", "vtt_path", "txt_path", "md_path", "raw_path"):
        assert row[key] == PATHS[key]

    short = _only([_row(duration_ms=999)]).part
    assert projection_row(short, candidate.transcript, PATHS)["duration_s"] == 1


def test_the_declared_language_family_order_matches_the_harvesters():
    """§3.2 key 2: the order is declared here and pinned equal to its home.

    The projection may not import ``subtitle_ingest`` — that module holds the
    gateway and repository sides, and this one is pure (§8) — so the constant is
    declared and this case is what stops the two drifting: the harvester's
    default preference is what makes an uploader caption outrank a machine one
    (``subtitle_ingest.py:59``), and a change to it that is not mirrored here
    has to fail in this file instead of silently re-ranking the store's rows.
    """
    assert LANGUAGE_FAMILY_ORDER == ("zh", "en")
    assert LANGUAGE_FAMILY_ORDER == subtitle_ingest._DEFAULT_LANGUAGE_FAMILY_ORDER


def test_an_asr_local_row_is_mapped_without_inventing_provenance():
    """§6: in range, mapped kind-agnostically, and given no ``asr_*`` key.

    The fabricated ``asr-local`` row carries the non-null ``model_id`` — the
    whole provenance the store holds for one — so an implementation that mapped
    that FK onto ``asr_*`` keys fails here; the caption row published beside it
    is the same case's control that both kinds land on one key set and that the
    ``asr-local`` part was not dropped by a kind filter.
    """
    candidates = ordered_candidates(
        [
            _row(source_kind="asr-local", language="zh-CN", model_id=7),
            _row(video_part_id=42, bvid="BV1aa", page_index=1, language="zh-Hant"),
        ]
    )
    assert [candidate.work_id for candidate in candidates] == [
        "BV1xx4y1zz:p2",
        "BV1aa:p1",
    ]

    asr = candidates[0]
    assert asr.transcript["source_kind"] == "asr-local"
    assert asr.transcript["model_id"] == 7  # the fact an invented key would read

    asr_row = projection_row(asr.part, asr.transcript, PATHS)
    caption_row = projection_row(candidates[1].part, candidates[1].transcript, PATHS)

    assert set(asr_row) == set(caption_row) == ROW_FIELDS
    assert asr_row["source"] == "asr-local"
    assert caption_row["source"] == "subtitle-cc"
    assert asr_row["language"] == "zh-CN"
    assert caption_row["language"] == "zh-Hant"
    assert [key for key in asr_row if key.startswith("asr_")] == []
    assert [key for key in asr_row if "confidence" in key] == []


def test_the_rendered_day_is_utc_regardless_of_the_runners_zone(monkeypatch):
    """§3.4's ``pubdate_str`` is the second's UTC day — pinned without ``TZ``.

    Both clocks the module could compose are supplied here as fixed
    ``struct_time`` values a day apart, so a ``localtime`` rendering fails on
    every host and the UTC rendering passes on every host
    (``{KNOWLEDGE_DIR}/testing-patterns/zone-independent-time-assertions.md``);
    the day is asserted as a literal because an expectation rendered from either
    stub would confirm whichever stub the code chose.  Scope limit the same
    precedent records: the stubs intercept ``time.gmtime``/``time.localtime``
    only, so a move to another local-time API would leave this case silent —
    ``PUBDATE_STR`` above is the second net that still discriminates on any
    non-UTC host.
    """
    utc_day = time.struct_time((1970, 1, 1, 23, 59, 59, 3, 1, 0))
    local_day = time.struct_time((1970, 1, 2, 7, 59, 59, 4, 2, 0))
    monkeypatch.setattr("bili_asr.formatting.time.gmtime", lambda _epoch: utc_day)
    monkeypatch.setattr(
        "bili_asr.formatting.time.localtime", lambda _epoch: local_day
    )

    candidate = _only([_row(pubdate=PUBDATE_UTC_DAY_EDGE)])

    row = projection_row(candidate.part, candidate.transcript, PATHS)

    assert row["pubdate_str"] == "1970-01-01"


def test_the_mirrored_family_rule_agrees_with_the_harvesters_over_its_codes():
    """§3.2 key 2's rule is a copy, and this is what makes it a pinned copy.

    ``_language_family`` mirrors ``subtitle_ingest.language_family``'s body
    because the projection may not import that module (case 9; §8), and case 9
    pins the *order tuple* only: an edit to the function's body — a new prefix
    convention, or a policy that splits ``zh-Hans``/``zh-Hant`` into families —
    would then leave this module ranking the store's rows by a stale copy with
    every case still green.  So the comparison here runs against the harvester's
    own function, and each row's expected family is a literal as well, which
    keeps the loop from being satisfied by two agreeing defects.

    The codes are §3.2's own where it names them: ``zh-CN``/``zh-Hant`` and the
    machine caption's ``ai-zh``/``ai-en`` are its consequences, ``zh-Hans`` is a
    spelling from the cited ``language_family`` docstring, ``en-US``/``de-DE``
    are the codes case 3 ranks, and ``asr-local`` carries §6's stored kind.  This
    file is the only place the coupling may exist.
    """
    codes = (
        ("zh-CN", "subtitle-cc", "zh"),
        ("zh-Hans", "subtitle-cc", "zh"),
        ("zh-Hant", "subtitle-cc", "zh"),
        ("en-US", "subtitle-cc", "en"),
        ("de-DE", "subtitle-cc", "de"),
        ("zh-CN", "asr-local", "zh"),
        ("ai-zh", "subtitle-ai", "zh"),
        ("ai-en", "subtitle-ai", "en"),
    )

    assert SOURCE_KIND_RANK[subtitle_ingest._SOURCE_KIND_BY_AI[False]] == 0
    assert SOURCE_KIND_RANK[subtitle_ingest._SOURCE_KIND_BY_AI[True]] == 1
    for language, source_kind, expected in codes:
        row = _row(language=language, source_kind=source_kind)
        assert transcript_projection._language_family(row) == expected
        assert transcript_projection._language_family(row) == (
            subtitle_ingest.language_family(
                language, source_kind == subtitle_ingest._SOURCE_KIND_BY_AI[True]
            )
        )


def test_ordered_candidates_keeps_the_order_it_is_given_rather_than_re_sorting():
    """§2.1's order has one home — the read — and this is the case that measures it.

    Case 4 hands the rows over in the read's own order, where a re-sort by
    ``(bvid, page_index)`` — the read's own leading ``ORDER BY`` — is a semantic
    no-op, so case 4 cannot tell "keeps the order it is given" from "makes one".
    (Case 10's assertion happens to catch that re-sort, because its two parts
    descend by bvid, but it is a key-set case, not an order case.)  The fixture
    here is deliberately the read's order *reversed* — both bvids and both page
    indexes descend — and the expectation is that same order: a re-sort answers
    the ascending list instead.  Row order cannot move the winner (case 2), so
    only the order claim is measured.
    """
    rows = [
        _row(video_part_id=51, bvid="BV1bb", page_index=1),
        _row(video_part_id=50, bvid="BV1bb", page_index=0),
        _row(video_part_id=42, bvid="BV1aa", page_index=1),
        _row(video_part_id=41, bvid="BV1aa", page_index=0),
    ]

    assert [candidate.work_id for candidate in ordered_candidates(rows)] == [
        "BV1bb:p1",
        "BV1bb:p0",
        "BV1aa:p1",
        "BV1aa:p0",
    ]
