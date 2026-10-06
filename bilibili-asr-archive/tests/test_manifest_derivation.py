"""Unit contract for the pure store→manifest derivation.

``bili_asr.services.manifest_derivation`` is a mapping and a policy over plain
dicts.  The store read (``list_pending_subtitle_parts`` + ``read_video_pubdates``)
and the ``ManifestStore`` write belong to the composition root, so every case
here is a dict in and a dict out — no database, no CLI, no filesystem.  The
field set is §3.1 and the milliseconds conversion §3.2 of the iteration spec
``sqlite-queue-bridge-contract.md``; the additive conflict policy is §3.4 and
its store self-contradiction check §3.6.
"""

import time

import pytest

from bili_asr.services import manifest_derivation
from bili_asr.services.manifest_derivation import (
    QUEUE_STATUS,
    SKIP_ALREADY_DERIVED,
    SKIP_CHAIN_OWNED,
    SKIP_IDENTITY_MISMATCH,
    derive_rows,
    duration_s_from_ms,
    row_for_part,
)
from tests.support.manifest_derivation import PUBDATE, _part

#: §3.1's nine fields, verbatim: the row carries these and no others.
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
}

#: ``1_700_000_000`` is ``2023-11-14T22:13:20Z``, and ``pubdate_str`` is that
#: second's **UTC** calendar date.  The expectation is therefore rendered the
#: same way rather than written as a literal: a literal only discriminated on a
#: host whose own zone is not UTC (this one is ``+08:00``, where the local date
#: of that second is the 15th).
PUBDATE_STR = time.strftime("%Y-%m-%d", time.gmtime(PUBDATE))

#: One second before the UTC date boundary — ``1970-01-01T23:59:59Z``, whose local
#: date is the 2nd at ``+08:00``.  The zone case below renders it, so the row's
#: ``pubdate_str`` is checked against the literal ``1970-01-01`` rather than
#: against a second ``gmtime`` call.
PUBDATE_UTC_DAY_EDGE = 86_399




def test_the_derivation_vocabulary_is_the_reported_one():
    """§8 prints ``skip <work_id> <reason>``; §3.1/§3.4/§3.6 fix the four names."""
    assert QUEUE_STATUS == "needs_audio"
    assert SKIP_ALREADY_DERIVED == "already_derived"
    assert SKIP_CHAIN_OWNED == "chain_owned"
    assert SKIP_IDENTITY_MISMATCH == "identity_mismatch"


def test_duration_s_is_floor_seconds_clamped_to_one():
    """§3.2's conversion, plus the absent-duration policy the contract leaves open.

    The ``0`` and ``None`` arms are not a store shape: ``duration_ms`` is
    ``INTEGER NOT NULL CHECK (duration_ms > 0)``, so neither can arrive from the
    read.  They pin this module's own decision — write the smallest usable second
    rather than a duration the audio budget reads as "unknown" — which §3.2
    defines only for a positive ``duration_ms``.  The fabricated input is
    deliberate: a change to that policy should fail here, not ship silently.
    """
    assert duration_s_from_ms(3_600_500) == 3600
    assert duration_s_from_ms(999) == 1
    # §3.2 clamps only what is *below* one second, and the floor is deliberate:
    # exactly one second is one second, a million milliseconds is a thousand.
    assert duration_s_from_ms(1000) == 1
    assert duration_s_from_ms(1_000_000) == 1000
    # `0` is the audio budget's "unknown" and fail-closes, so the smallest
    # usable second is written; an absent duration says the same thing.
    assert duration_s_from_ms(0) == 1
    assert duration_s_from_ms(None) == 1


def test_a_queue_row_becomes_a_page_qualified_needs_audio_row():
    row = row_for_part(_part(), PUBDATE)

    assert set(row) == ROW_FIELDS
    assert row["work_id"] == "BV1xx4y1zz:p2"
    assert row["bvid"] == "BV1xx4y1zz"
    assert row["page_index"] == 2
    assert row["cid"] == 987_654
    assert row["title"] == "第一部分：开场"
    assert row["duration_s"] == 1800
    assert row["pubdate"] == PUBDATE
    assert row["pubdate_str"] == PUBDATE_STR
    assert row["status"] == QUEUE_STATUS == "needs_audio"


def test_a_queue_video_title_survives_manifest_derivation():
    row = row_for_part(_part(video_title="课程总标题"), PUBDATE)

    assert row["title"] == "第一部分：开场"
    assert row["video_title"] == "课程总标题"


def test_the_rendered_day_is_utc_regardless_of_the_runners_zone(monkeypatch):
    """The UTC day of the second, not the runner's day — pinned without ``TZ``.

    ``gmtime`` ignores ``TZ``, so an expectation derived from ``gmtime`` can only
    fall with the implementation on a host whose zone is not UTC: on a UTC runner
    the two render the same string and a ``localtime`` regression passes.  No
    second epoch closes that, because on a UTC runner the local rendering of *any*
    epoch is its UTC date; neither does pinning ``TZ``, which needs ``tzset`` (not
    on every platform).  So this case supplies both clocks itself: the module's
    ``time.gmtime`` and ``time.localtime`` are answered by fixed ``struct_time``
    values one day apart, which no host's zone can make equal.  The row must
    render the UTC one; if it renders the local one the assertion fails on every
    host, and the date is asserted against a literal because an expectation
    rendered from either stub would confirm whichever stub the code chose.
    """
    utc_day = time.struct_time((1970, 1, 1, 23, 59, 59, 3, 1, 0))
    local_day = time.struct_time((1970, 1, 2, 7, 59, 59, 4, 2, 0))
    monkeypatch.setattr("bili_asr.formatting.time.gmtime", lambda _epoch: utc_day)
    monkeypatch.setattr(
        "bili_asr.formatting.time.localtime", lambda _epoch: local_day
    )

    row = row_for_part(_part(), PUBDATE_UTC_DAY_EDGE)

    assert row["pubdate_str"] == "1970-01-01"


def test_a_part_whose_store_work_id_disagrees_is_skipped():
    """§3.6's skip, on a ``work_id`` no store can hold.

    The store's SQL form and the Python identity agree for every bvid the gateway
    admits and every ``page_index`` the schema accepts, so this branch is
    unreachable defence for shipped-writer stores, pinned here by a fabricated
    ``work_id`` on purpose: it must keep answering as the contract says if the
    store ever stops agreeing with itself.
    """
    # §3.6: the store computes work_id in SQL while the manifest's identity rule
    # is Python's, so a row whose two forms differ is skipped, never rewritten.
    part = _part(page_index=2, work_id="BV1xx4y1zz:p3")

    outcome = derive_rows([part], {part["bvid"]: PUBDATE}, {})

    assert outcome.identity_mismatch == ("BV1xx4y1zz:p3",)
    assert outcome.appended == ()
    assert outcome.already_derived == ()
    assert outcome.chain_owned == ()


def test_an_existing_needs_audio_row_is_not_appended():
    existing = {
        "BV1xx4y1zz:p2": {"work_id": "BV1xx4y1zz:p2", "status": "needs_audio"}
    }

    outcome = derive_rows([_part()], {"BV1xx4y1zz": PUBDATE}, existing)

    assert outcome.already_derived == ("BV1xx4y1zz:p2",)
    assert outcome.appended == ()
    assert outcome.chain_owned == ()
    assert outcome.identity_mismatch == ()


@pytest.mark.parametrize("status", ["archived", "subtitle_done", "audio_ok"])
def test_a_chain_owned_row_is_never_regressed(status):
    held = {"work_id": "BV1xx4y1zz:p2", "status": status, "title": "the chain's row"}
    existing = {"BV1xx4y1zz:p2": dict(held)}

    outcome = derive_rows([_part()], {"BV1xx4y1zz": PUBDATE}, existing)

    assert outcome.chain_owned == ("BV1xx4y1zz:p2",)
    assert outcome.appended == ()
    assert outcome.already_derived == ()
    # Byte-for-byte as found: the bridge does not overrule the chain (§3.4).
    assert existing == {"BV1xx4y1zz:p2": held}


def test_appended_rows_keep_the_queue_order():
    existing = {"BV1bb:p1": {"work_id": "BV1bb:p1", "status": "asr_done"}}
    parts = [_part(bvid="BV1aa", page_index=0), _part(bvid="BV1bb", page_index=1),
             _part(bvid="BV1cc", page_index=2)]
    pubdates = {"BV1aa": PUBDATE, "BV1bb": PUBDATE, "BV1cc": PUBDATE}

    outcome = derive_rows(parts, pubdates, existing)

    assert [row["work_id"] for row in outcome.appended] == ["BV1aa:p0", "BV1cc:p2"]
    assert outcome.chain_owned == ("BV1bb:p1",)


def test_a_part_without_a_stored_pubdate_is_not_given_a_default():
    # `videos` is the part's foreign key, so a missing publication second is a
    # corrupt store — it stays a KeyError instead of becoming an invented date.
    with pytest.raises(KeyError):
        derive_rows([_part()], {}, {})
