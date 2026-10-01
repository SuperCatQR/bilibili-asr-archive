"""Characterization test for the consolidated canonical-stem contract (compass D5).

D5: a part's stem derives from its ``(bvid, page_index)`` identity and is
parseable back to it; ``page_label`` is a display concern, NOT part of the
stem; a row missing ``bvid`` raises (fail-loud).

The rows below are the divergence rows that made the three pre-consolidation
implementations (``quality._canonical_stem``, ``integrity._canonical_stem``,
``coordinator.artifact_stem_for_entry``) disagree — see the cluster-5 STOP in
plan 010-dedupe-shared-helpers and plan stem-contract-consolidation. Each row
now pins the ONE D5 behaviour across all three entry points.
"""

from __future__ import annotations

import pytest

from bili_asr.coordinator import artifact_stem_for_entry
from bili_asr.integrity import IntegrityVerifier
from bili_asr.page_identity import canonical_stem, display_label, parse_work_id
from bili_asr.quality import _canonical_stem as quality_stem


def _well_formed() -> dict:
    return {
        "bvid": "BV1demo",
        "work_id": "BV1demo:p1",
        "page_index": 1,
        "cid": 123,
        "page_label": "P2 标题",
    }


def test_d5_well_formed_row_stem_is_identity_derived():
    row = _well_formed()
    for stem in (
        canonical_stem(row),
        quality_stem(row),
        IntegrityVerifier._canonical_stem(row),
        artifact_stem_for_entry(row),
    ):
        assert stem == "BV1demo.p1"
    # parseable back to the identity
    assert parse_work_id("BV1demo:p1") == ("BV1demo", 1)


def test_d5_page_label_never_enters_the_stem():
    row = _well_formed()
    row["page_label"] = "a very different label"
    assert canonical_stem(row) == "BV1demo.p1"
    # display helper surfaces the label only as display
    assert display_label({"page_label": "orphan label"}) == "orphan label"


def test_d5_missing_bvid_raises_fail_loud():
    # D5 contract layer: a row missing bvid raises (fail-loud), matching the
    # archive's own archive_stem. The report surfaces (quality's probe) map
    # the same row to None — identity-invalid rows are reported, not crashed.
    row = {"work_id": "BV1demo:p1", "page_index": 1, "cid": 123}
    with pytest.raises(KeyError):
        canonical_stem(row)
    with pytest.raises(KeyError):
        IntegrityVerifier._canonical_stem(row)
    with pytest.raises(KeyError):
        artifact_stem_for_entry(row)
    assert quality_stem(row) is None


def test_d5_unresolved_row_falls_back_to_bare_bvid():
    row = {"bvid": "BV1demo", "unresolved": True}
    for stem in (
        canonical_stem(row),
        quality_stem(row),
        IntegrityVerifier._canonical_stem(row),
        artifact_stem_for_entry(row),
    ):
        assert stem == "BV1demo"


def test_d5_malformed_work_id_raises_instead_of_fallback():
    # pre-consolidation quality/integrity returned the raw work_id string
    # ("junk") — a display value leaking into a path. D5 fails loud at the
    # contract layer; quality's report probe maps it to None.
    row = {"bvid": "BV1demo", "work_id": "junk", "cid": 5}
    with pytest.raises(ValueError):
        canonical_stem(row)
    with pytest.raises(ValueError):
        IntegrityVerifier._canonical_stem(row)
    with pytest.raises(ValueError):
        artifact_stem_for_entry(row)
    assert quality_stem(row) is None


def test_d5_work_id_bvid_mismatch_uses_work_id_identity():
    # pre-consolidation integrity returned the raw "BV1:p1" string (display
    # leak) and archive_stem returned row["bvid"]-based "BV2.p1" (trusting the
    # row's possibly-stale bvid over the parsed identity). D5 parses work_id.
    row = {"bvid": "BV2other", "work_id": "BV1demo:p1", "page_index": 1, "cid": 7}
    assert canonical_stem(row) == "BV1demo.p1"
    assert IntegrityVerifier._canonical_stem(row) == "BV1demo.p1"
    assert artifact_stem_for_entry(row) == "BV1demo.p1"


def test_d5_work_id_carries_page_index_cid_is_not_needed():
    # archive_stem treated a work_id'd row without cid as unresolved; D5's
    # identity is (bvid, page_index), both carried by work_id itself, so the
    # stem still parses. This is exactly the shape test_quality.row() uses.
    row = {"bvid": "BV1demo", "work_id": "BV1demo:p1"}
    assert canonical_stem(row) == "BV1demo.p1"
    assert quality_stem(row) == "BV1demo.p1"
    assert IntegrityVerifier._canonical_stem(row) == "BV1demo.p1"
    assert artifact_stem_for_entry(row) == "BV1demo.p1"


def test_d5_bvid_only_row():
    row = {"bvid": "BV1demo"}
    for stem in (
        canonical_stem(row),
        quality_stem(row),
        IntegrityVerifier._canonical_stem(row),
        artifact_stem_for_entry(row),
    ):
        assert stem == "BV1demo"


def test_quality_display_fallback_for_identityless_row():
    # A row with no identity at all: quality's report probe answers None
    # (never raising out of the report path), and the display helper owns
    # the human-readable surface — page_label included, never as a path.
    assert quality_stem({}) is None
    assert quality_stem({"page_label": "only a label"}) is None
    assert display_label({"page_label": "only a label"}) == "only a label"
    assert display_label({"bvid": "BV1demo", "work_id": "junk"}) == "junk"
