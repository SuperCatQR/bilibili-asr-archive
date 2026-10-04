"""Decide and shape the transcript projection: which stored body wins, and the row.

One direction only, and no I/O at all.  ``archive.db`` holds the text, the
manifest states what was published, and this module is the mapping between the
two and nothing else — it opens no connection, writes no file, reads no
manifest, and composes no clock the caller did not hand it.  ``cli.py`` owns the
composition (contract §8: only the composition root reaches across layers): the
repository read (``list_stored_transcripts``) yields one mapping per stored
transcript version with its part's columns, this module keeps one winner per
part and converts its body, and the caller publishes through the archive writer
and records the row through ``ManifestStore``.

The order is contract §3.2's, applied in order: the kind rank (an uploader
caption before a machine caption), the language **family** rank (``zh``, then
``en``, then every other family), the language code ascending, and the version
**descending**.  It is total because the store's
``UNIQUE (video_part_id, source_kind, language, version)``
(``schema-transcripts.sql:25``) makes ``(source_kind, language)`` an identity and
``version`` unique inside it, so keys 1–4 separate every row a shipped writer can
store and this module adds no ``transcript_id`` tiebreak.  Two consequences are
deliberate rather than accidental: a part holding both an uploader caption and a
machine caption publishes the uploader one, and a part holding ``ai-zh`` and
``ai-en`` publishes the Chinese one — the family rank is what stops the code
order from preferring English there.

The family rule is the harvester's own (``subtitle_ingest.language_family``), and
it is mirrored here rather than imported: that module holds the gateway and the
repository, so importing it would put the acquisition side inside a pure module.
``LANGUAGE_FAMILY_ORDER`` is declared for the same reason and a test pins it
equal to the harvester's default order; the rule below is pinned the same way,
against the harvester's own function over the codes §3.2 spells out.

The two shared rules that *are* imported keep one home each:
:func:`~bili_asr.services.manifest_derivation.duration_s_from_ms` for the
milliseconds→seconds conversion (§3.4), and
:func:`~bili_asr.page_identity.format_work_id` for the row's identity (§2.1,
where the read deliberately leaves ``work_id`` to Python).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from bili_asr.page_identity import format_work_id
from bili_asr.formatting import pubdate_utc
from bili_asr.artifacts import REQUIRED_ARTIFACT_KEYS as _PRODUCT_PATH_KEYS
from bili_asr.services.manifest_derivation import duration_s_from_ms

if TYPE_CHECKING:  # types only: this module never builds or checks one (§8).
    from bili_asr.storage.models import TranscriptSegmentRecord

#: The one manifest status this projection records (contract §5.2): the state
#: the chain itself writes after ``write_archive`` and a complete bundle, and the
#: status the readers require to stop counting the row unfinished.
ARCHIVED_STATUS = "archived"
#: §3.2 key 1: the kind order, which is the shipped harvester's own preference —
#: an uploader caption before a machine caption before a local ASR transcript.
SOURCE_KIND_RANK = {"subtitle-cc": 0, "subtitle-ai": 1, "asr-local": 2}
#: §3.2 key 2: the family order, declared here (see the module docstring) and
#: pinned equal to the harvester's default by a test.
LANGUAGE_FAMILY_ORDER = ("zh", "en")

#: The stored kind of a machine-generated caption, whose codes carry the ``ai-``
#: prefix the family rule strips (``_SOURCE_KIND_BY_AI``, ``subtitle_ingest.py:61``).
_MACHINE_CAPTION_KIND = "subtitle-ai"
#: §2.1's part context: what a candidate carries out of the read, and no more.
#: ``pubdate`` and ``video_title`` are the video's own columns; they are here
#: beside the part's because the read joins ``videos`` for them, and a caller
#: holding only a candidate cannot recover them.  The part's ``part_title`` and
#: the video's ``video_title`` are independent facts — measured, 10 of 63 stored
#: parts diverge — so both travel and neither stands in for the other (§3.1, D5).
_PART_KEYS = (
    "video_part_id",
    "bvid",
    "page_index",
    "cid",
    "part_title",
    "duration_ms",
    "pubdate",
    "video_title",
)
#: §2.1's identity columns for one stored version.
_TRANSCRIPT_KEYS = (
    "transcript_id",
    "source_kind",
    "language",
    "model_id",
    "version",
    "content_sha256",
    "created_at",
)
#: §5.1's product paths, root-relative to the write base — the four keys the
#: caller's mapping contributes to the row, and the only ones it may.


@dataclass(frozen=True)
class Candidate:
    """One part to publish, with the transcript identity that won it.

    ``part`` carries §2.1's part columns, plus the two the read joins ``videos``
    for (``pubdate``, ``video_title``), and ``transcript`` that version's
    identity columns alone, both copied out of the read's row, so a caller can
    hand ``part``/``transcript`` straight to :func:`projection_row` and read the
    winner off the candidate without the row's other columns travelling with it.
    ``work_id`` is built here by :func:`~bili_asr.page_identity.format_work_id`:
    §2.1's read does not select it, and ``ManifestStore.upsert`` re-validates the
    same Python identity when the row is written.
    """

    work_id: str
    part: Mapping[str, Any]
    transcript: Mapping[str, Any]


def _language_family(row: Mapping[str, Any]) -> str:
    """Return the family §3.2 key 2 ranks, by the harvester's own rule.

    ``subtitle_ingest.language_family``'s body, mirrored (see the module
    docstring for why it is not imported): the AI caption's ``ai-`` prefix is
    stripped, and the lowercase primary subtag — everything before the first
    ``-`` — is the family.  Derived rather than matched against a list of codes,
    because upstream spells one spoken language differently per caption kind
    (``zh-CN``/``zh-Hans``/``zh-Hant`` against ``ai-zh``).
    """

    code = row["language"].strip().lower()
    if row["source_kind"] == _MACHINE_CAPTION_KIND and code.startswith("ai-"):
        code = code[3:]
    return code.split("-", 1)[0]


def _family_rank(family: str) -> int:
    """Return one family's rank in the declared order; the rest share the last."""

    try:
        return LANGUAGE_FAMILY_ORDER.index(family)
    except ValueError:
        return len(LANGUAGE_FAMILY_ORDER)


def _winner_key(row: Mapping[str, Any]) -> tuple[int, int, str, int]:
    """Return §3.2's total order for one stored version, smallest first.

    ``-version`` is the descending direction.  An unknown ``source_kind`` is a
    ``KeyError`` rather than an invented last rank: the column's ``CHECK`` admits
    exactly the three kinds, so a fourth is a store this module does not know how
    to rank, and answering it silently would be a preference nobody decided.
    """

    return (
        SOURCE_KIND_RANK[row["source_kind"]],
        _family_rank(_language_family(row)),
        row["language"],
        -row["version"],
    )


def ordered_candidates(
    rows: Iterable[Mapping[str, Any]], limit: int | None = None
) -> tuple[Candidate, ...]:
    """Return one candidate per part, in the order the parts first appear.

    ``rows`` is §2.1's read handed over as mappings: one row per stored
    transcript version, in the repository's locked order (``bvid``,
    ``page_index``, then the identity keys), which is why the parts come back in
    that same order — the order rule has one home, in the read (§2.1), and this
    function only keeps the order it is given.  The winner inside a part is
    §3.2's minimum, so it does not depend on the row order at all.

    ``limit`` bounds the run in **parts**: the first ``limit`` candidates, never
    the first ``limit`` rows, because a part is a candidate once whatever number
    of versions it holds.  The validation is the shipped
    ``list_pending_subtitle_parts`` discipline — ``TypeError`` for a non-integer,
    ``ValueError`` for a non-positive one — which is also the shape the command's
    own ``--limit-parts`` exit ``1`` rests on (§2.2).
    """

    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer or None")
        if limit < 1:
            raise ValueError("limit must be a positive integer")

    winners: dict[Any, Mapping[str, Any]] = {}
    for row in rows:
        part_id = row["video_part_id"]
        held = winners.get(part_id)
        if held is None or _winner_key(row) < _winner_key(held):
            winners[part_id] = row

    candidates = tuple(
        Candidate(
            work_id=format_work_id(row["bvid"], row["page_index"]),
            part={key: row[key] for key in _PART_KEYS},
            transcript={key: row[key] for key in _TRANSCRIPT_KEYS},
        )
        for row in winners.values()
    )
    return candidates if limit is None else candidates[:limit]


def writer_segments(
    segments: Sequence[TranscriptSegmentRecord],
) -> list[dict[str, Any]]:
    """Return one transcript's stored segments in the archive writer's shape (§3.3).

    The store holds ``(start_ms, end_ms, text)`` and the writer consumes
    ``{"start": <seconds>, "end": <seconds>, "text": <verbatim>}``, in the
    ordinal order the read already returned.  ``/1000`` exactly: the SRT
    renderer rounds ``seconds * 1000`` back to an integer (``asr.py:851``), so a
    cue's printed times are the store's milliseconds, with no lost millisecond
    and no accumulated drift.

    An empty sequence is refused here rather than published: the writer would
    emit an empty ``srt``/``txt`` and a sidecar with no cue, and §7 has the
    command name this ``ValueError`` as its ``empty_transcript`` reason.  A
    stored transcript is never empty (``storage/models.py:382-383``), so the
    branch is this module's refusal of a shape the store cannot deliver rather
    than a live path.
    """

    if not segments:
        raise ValueError("a stored transcript carries no segment to publish")
    return [
        {
            "start": segment.start_ms / 1000,
            "end": segment.end_ms / 1000,
            "text": segment.text,
        }
        for segment in segments
    ]


def projection_row(
    part: Mapping[str, Any],
    transcript: Mapping[str, Any],
    paths: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the manifest row one published candidate records (§5.1).

    Exactly the fifteen keys and no others: the nine store-derived fields the
    queue bridge's own row carries (``manifest_derivation.py:87-97``) with this
    command's one status, this publication's four product paths copied from
    ``paths`` root-relative to the write base, and the winning identity in the
    readers' vocabulary — ``source`` and ``language`` as ``quality`` and
    ``search_index`` already read them.

    Nothing else is added and nothing is guessed: no ``audio_path`` (a caption
    has no audio), no ``sub_lan``/``lan_doc`` (the legacy subtitle keys), no
    ``artifact_paths`` (a chain attempt key), and no ``asr_*`` provenance — the
    store holds no device, VAD or hotword fact to write, so the keys are absent
    rather than zero-filled (§4.2).  ``duration_s`` and the ``pubdate_str`` day
    are §3.4's two renderings: the bridge's floor-and-clamp, imported, and the
    second's **UTC** calendar date.  Only the four product keys are read out of
    ``paths``, so a caller's mapping may hold more (the marker's path, say)
    without any of it reaching the manifest.
    """

    bvid = part["bvid"]
    page_index = part["page_index"]
    pubdate = part["pubdate"]
    row = {
        "work_id": format_work_id(bvid, page_index),
        "bvid": bvid,
        "page_index": page_index,
        "cid": part["cid"],
        "title": part["part_title"],
        "duration_s": duration_s_from_ms(part["duration_ms"]),
        "pubdate": pubdate,
        "pubdate_str": pubdate_utc(pubdate),
        "status": ARCHIVED_STATUS,
        "source": transcript["source_kind"],
        "language": transcript["language"],
    }
    for key in _PRODUCT_PATH_KEYS:
        row[key] = paths[key]
    return row


__all__ = [
    "ARCHIVED_STATUS",
    "Candidate",
    "LANGUAGE_FAMILY_ORDER",
    "SOURCE_KIND_RANK",
    "ordered_candidates",
    "projection_row",
    "writer_segments",
]
