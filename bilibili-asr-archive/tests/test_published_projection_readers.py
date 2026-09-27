"""The archive's own readers agree a projected row is done (contract §5.3, §10).

Every case here starts from **Fixture F**: a disposable archive root holding the
five states §5.5 discriminates, the stored part the derived audio queue owns, and
one part whose caption carries an advisory content code.  Nothing is hand-edited:
the parts come from ``MetadataRepository``, the transcripts from
``TranscriptRepository.record_acquired_transcript``, and the two bundles states
(ii) and (iv) need come from the shipped ``archive.write_archive``.

What each case pins, per compass criterion:

- **1** — a stored caption becomes a complete bundle, and the reader the archive
  itself counts bundles with (``verify --trusted-local`` → ``archive_bundle_complete``,
  ``integrity.py:356-369``) stops reporting the row.
- **2** — a second stored version leaves the published bytes identical (state
  (iii)), *beside* a bundle whose completeness probe fails, which the same run
  republishes (state (iv)).
- **3** — the three reader checks: ``verify`` exit ``0`` with no defects and no
  diagnostics, ``coverage --quality`` reporting no reason at all for the
  projected row, and ``derive-manifest``'s queue count unchanged.
- **4** — the projected md and its raw sidecar carry no ``asr_``/``confidence``
  key and name the stored source.

**Every absence assertion here has a reachable falsifier, inside its own case**
(the rule of ``{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md``):

- ``defect_count == 0`` (case 1) is asked *after* the same reader, on the same
  fixture, reported ``missing_transcript`` for state (iv) — the run heals it;
- ``reasons == []`` (case 2) is read beside a published row whose caption reports
  ``duplicate_cue`` in the same report;
- the inverted ``asr_`` check (case 3) is run against a bundle the shipped writer
  produced from an ASR-shaped input, where it matches;
- ``queue=<n>`` unchanged (case 4) is read twice around the run and once more
  after the queue's own relation is made to move.

**The criteria-bearing caption body carries no advisory content code** (contract
§10): ``CAPTION_SEGMENTS`` is two distinct cues, each far above the fragment
bounds and far below the overlong one, joining to no thrice-repeated
eight-character window.  The one part whose body *does* carry a code is the
control named above, never a part a criterion is measured on.

**What stays untested.**  ``verify`` runs against Fixture F, whose manifest is
built by this file and by ``publish-transcripts``; a live corpus carries history
this fixture deliberately does not (contract §5.4's one-row-per-``work_id``
build, and the R2 append-only-history row the readers still disagree on).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import replace

from bili_asr import archive as archive_module
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore
from bili_asr.storage import (
    AcquisitionRunRecord,
    MetadataRepository,
    TranscriptRepository,
    TranscriptSegmentRecord,
    open_database,
)
from fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)

#: The fixture's parts, one per state §5.5 discriminates, plus the stored part
#: that holds **no** transcript (the relation ``derive-manifest`` owns) and the
#: advisory-content control case 2 reads against.
FRESH_BVID = "BV1FRESH"    # (i)   stored transcript, no bundle, no row
CHAIN_BVID = "BV1CHAIN"    # (ii)  the bundle the chain archived itself
DRIFT_BVID = "BV1DRIFT"    # (iii) published, then the store gains version 2
MARKER_BVID = "BV1MARKER"  # (iv)  four families and a row, no marker
GONE_BVID = "BV1GONE"      # (v)   ``processing_status = gone``, text still local
QUEUE_BVID = "BV1QUEUE"    # holds no transcript: not a candidate, in the queue
NOISY_BVID = "BV1NOISY"    # the advisory-content-code control

#: ``(bvid, page_index, cid, duration_ms, processing_status)``.  The durations
#: matter twice: ``duration_s`` is the floored seconds the row records (contract
#: §3.4), and ``coverage --quality`` bounds every cue's end against it — so the
#: ``gone`` part carries 20 s because the caption it holds ends at 6.0 s and a
#: 5 s part would report ``out_of_range`` for a bundle this file is not asking
#: about.
PARTS = (
    (FRESH_BVID, 0, 3001, 12_000, "metadata_collected"),
    (CHAIN_BVID, 0, 5001, 7_000, "metadata_collected"),
    (DRIFT_BVID, 0, 6001, 8_000, "metadata_collected"),
    (MARKER_BVID, 0, 7001, 9_000, "metadata_collected"),
    (GONE_BVID, 0, 4001, 20_000, "gone"),
    (QUEUE_BVID, 0, 8001, 3_000, "metadata_collected"),
    (NOISY_BVID, 0, 9001, 6_000, "metadata_collected"),
)

#: Every part that holds a transcript, in the read's locked order (``bvid ASC``):
#: the candidates a run over Fixture F publishes or leaves alone.  ``BV1QUEUE``
#: is absent by construction — it is the part the queue relation owns.
CANDIDATE_WORK_IDS = tuple(
    f"{bvid}:p{page_index}"
    for bvid, page_index, _cid, _ms, _status in sorted(PARTS)
    if bvid != QUEUE_BVID
)
ALL_WORK_IDS = tuple(
    f"{bvid}:p{page_index}" for bvid, page_index, _cid, _ms, _status in sorted(PARTS)
)

FRESH_WORK_ID = f"{FRESH_BVID}:p0"
CHAIN_WORK_ID = f"{CHAIN_BVID}:p0"
DRIFT_WORK_ID = f"{DRIFT_BVID}:p0"
MARKER_WORK_ID = f"{MARKER_BVID}:p0"
GONE_WORK_ID = f"{GONE_BVID}:p0"
QUEUE_WORK_ID = f"{QUEUE_BVID}:p0"
NOISY_WORK_ID = f"{NOISY_BVID}:p0"

#: The stored caption the criteria are measured on.  Two distinct cues of nine
#: characters each: nothing opens on a leading mark, neither is a fragment
#: (``quality.py`` bounds a fragment at *both* under 6 characters and under one
#: second), both are far under ``OVERLONG_CHARS``, and the joined body holds no
#: eight-character window twice.  So the projection's row reports no advisory
#: content code and criterion 3's literal ``reasons: []`` can hold (§5.3).
CAPTION_SEGMENTS = (
    TranscriptSegmentRecord(0, 2_500, "档案里的第一句台词"),
    TranscriptSegmentRecord(3_000, 6_000, "第二句记录在案的台词"),
)
#: The body a second stored version carries: the same identity, a different
#: content hash, so the store appends ``version=2`` instead of answering
#: ``unchanged`` (``database.py``'s ``record_acquired_transcript``).
SECOND_VERSION_SEGMENTS = (TranscriptSegmentRecord(0, 1_500, "改过一次的字幕"),)
#: The advisory control's body: one text twice in a row, which
#: ``quality._check_content`` reports as ``duplicate_cue`` — and as nothing else,
#: since each cue runs 2.5 s and neither opens on a mark.
NOISY_SEGMENTS = (
    TranscriptSegmentRecord(0, 2_500, "重复的一句"),
    TranscriptSegmentRecord(2_500, 5_000, "重复的一句"),
)

#: The chain's own bundle for state (ii): the writer's segment shape, written by
#: ``write_archive`` rather than by the command under test.
CHAIN_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "档案里的第一句台词"},
    {"start": 3.0, "end": 6.0, "text": "第二句记录在案的台词"},
]

#: The four product keys a recorded row declares (contract §5.1).
PRODUCT_KEYS = ("srt_path", "txt_path", "md_path", "raw_path")

#: The ten frontmatter keys §4.1 allows and the two deliberate omissions §4.2
#: rests on: no ``asr_*`` provenance key, no confidence summary.  ``video_title``
#: is the deliberate additive revision of compass D4/D5 (§4 of the metadata
#: coverage contract): ``title`` still means the part title, and the video's own
#: title travels beside it.  The projection contract's §4.1 table was written
#: before that revision and now reads nine; this set is the live count.
FRONTMATTER_KEYS = frozenset(
    {"bvid", "title", "video_title", "date", "duration_s", "source", "url",
     "work_id", "page_index", "cid"}
)
#: Criterion 4's inverted check, verbatim in spirit: no line may open with an
#: ``asr_`` provenance key or a ``confidence`` one.
INVERTED_ASR_CHECK = re.compile(r"^\s*(?:asr_|confidence)", re.MULTILINE)

#: The ASR-shaped control bundle case 3 writes with the shipped writer, so the
#: inverted check above is shown to match something rather than to match nothing.
CONTROL_ASR_ENTRY = {
    "bvid": "BV1ASRCTL",
    "work_id": "BV1ASRCTL:p0",
    "page_index": 0,
    "cid": 1234,
    "title": "控制集",
    "duration_s": 12,
    "pubdate_str": "2023-11-14",
}
CONTROL_ASR_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "一句带分数的台词", "confidence": 0.31}
]
CONTROL_ASR_PROVENANCE = {"model_name": "sensevoice-small", "device": "cpu"}

MANIFEST_REL_PATH = os.path.join("manifest", "manifest.jsonl")
ATTEMPTS_REL_PATH = os.path.join("coordinator", "attempts.jsonl")

#: The publication second ``fixtures.metadata_records`` stores for every video,
#: and its **UTC** calendar date — the row's ``pubdate``/``pubdate_str`` and the
#: md name's leading component.  Rendered with ``gmtime`` rather than written as
#: a literal, because a literal only discriminates on a host whose zone is UTC.
PUBDATE = 1_700_000_000
PUBDATE_STR = time.strftime("%Y-%m-%d", time.gmtime(PUBDATE))


# --------------------------------------------------------------------------- #
# Fixture F
# --------------------------------------------------------------------------- #


def _md_name(bvid: str, page_index: int = 0) -> str:
    """The writer's md name for a part of ``bvid`` (§3.1)."""
    return f"{PUBDATE_STR}_{bvid}.p{page_index}_第{page_index + 1}集.md"


def _entry(bvid: str, page_index: int, cid: int, duration_ms: int) -> dict:
    """The writer's entry for one stored part — the fields its frontmatter reads."""
    return {
        "bvid": bvid,
        "work_id": f"{bvid}:p{page_index}",
        "page_index": page_index,
        "cid": cid,
        "title": f"第{page_index + 1}集",
        "duration_s": max(1, duration_ms // 1000),
        "pubdate_str": PUBDATE_STR,
    }


def _seed_archive(root: str) -> None:
    """Create ``archive.db`` with one video per bvid and exactly these parts."""
    connection = open_database(root)
    try:
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            metadata.upsert_user(make_user_record())
            for bvid in dict.fromkeys(row[0] for row in PARTS):
                metadata.upsert_video(
                    make_video_record(bvid, aid=None, title="投影读者测试视频")
                )
            for bvid, page_index, cid, duration_ms, status in PARTS:
                metadata.upsert_part(
                    replace(
                        make_part_record(
                            bvid,
                            page_index=page_index,
                            cid=cid,
                            title=f"第{page_index + 1}集",
                            processing_status=status,
                        ),
                        duration_ms=duration_ms,
                    )
                )
    finally:
        connection.close()


def _part_id(connection, bvid: str, page_index: int) -> int:
    """One stored part's primary key, read from the store's own relation."""
    return int(
        connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, page_index),
        ).fetchone()["video_part_id"]
    )


def _store_caption(
    root: str,
    bvid: str,
    page_index: int = 0,
    *,
    segments=CAPTION_SEGMENTS,
    version_tag: str = "v1",
) -> None:
    """Store one acquired ``subtitle-ai`` caption through the repository."""
    connection = open_database(root)
    try:
        repository = TranscriptRepository(connection)
        run_id = f"caption-{version_tag}-{bvid}-p{page_index}"
        repository.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=run_id,
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=101,
            )
        )
        repository.record_acquired_transcript(
            run_id=run_id,
            video_part_id=_part_id(connection, bvid, page_index),
            source_kind="subtitle-ai",
            language="zh-CN",
            segments=segments,
            started_at=200,
            finished_at=300,
            created_at=400,
        )
    finally:
        connection.close()


def _marker_path(base: str, declared: dict[str, str]) -> str:
    """The marker's path for a declared bundle — beside the ``srt`` family."""
    return str(
        archive_module.bundle_marker_path(os.path.join(base, declared["srt_path"]))
    )


def _chain_bundle(
    root: str, bvid: str, page_index: int, cid: int, duration_ms: int
) -> dict[str, str]:
    """Publish one bundle through the shipped writer and record its ``archived`` row.

    The chain's own path, not the command under test: states (ii) and (iv) are
    built from it, so a case that observes the projection leaving state (ii)
    alone is observing it leave the *chain's* bundle alone.
    """
    entry = _entry(bvid, page_index, cid, duration_ms)
    paths = archive_module.write_archive(
        root, entry, CHAIN_SEGMENTS, source="subtitle"
    )
    store = ManifestStore(root=root)
    store.load()
    store.upsert({**entry, **paths, "status": "archived"})
    return paths


def _empty_attempts_sidecar(root: str) -> None:
    """An empty ``coordinator/attempts.jsonl``, present (§5.3).

    ``verify`` exits ``0`` only when defects **and** diagnostics are empty, and a
    manifest without the attempts sidecar raises ``missing_attempts_sidecar``
    (``integrity.py:314-328``).  The projection writes no attempt — that ledger
    is chain stage evidence — so the fixture supplies the sidecar the chain would
    have written, empty.
    """
    os.makedirs(os.path.join(root, "coordinator"), exist_ok=True)
    with open(os.path.join(root, ATTEMPTS_REL_PATH), "w", encoding="utf-8"):
        pass


def _build_fixture_f(root: str) -> None:
    """Build Fixture F — the five states §5.5 discriminates, in one archive root."""
    _seed_archive(root)
    _empty_attempts_sidecar(root)
    # (i), (iii), (v) and the advisory control start as a stored caption with no
    # bundle: the projection's own publish path is what the case measures.
    for bvid, segments in (
        (FRESH_BVID, CAPTION_SEGMENTS),
        (DRIFT_BVID, CAPTION_SEGMENTS),
        (GONE_BVID, CAPTION_SEGMENTS),
        (NOISY_BVID, NOISY_SEGMENTS),
    ):
        _store_caption(root, bvid, 0, segments=segments)

    # (ii) the chain already published this part's bundle, and the store also
    # holds its caption — so the part is a candidate the projection must leave
    # alone.
    _store_caption(root, CHAIN_BVID, 0)
    _chain_bundle(root, CHAIN_BVID, 0, 5001, 7_000)

    # (iv) the four families are on disk and a row declares them, but the marker
    # the completeness reader recomputes is gone, so §5.4's probe returns False
    # and the candidate is published rather than trusted.
    _store_caption(root, MARKER_BVID, 0)
    declared = _chain_bundle(root, MARKER_BVID, 0, 7001, 9_000)
    os.unlink(_marker_path(root, declared))


# --------------------------------------------------------------------------- #
# Reading the fixture back
# --------------------------------------------------------------------------- #


def _exit_code(argv: list[str]) -> int:
    """Return the command's exit code, argparse usage errors included."""
    try:
        return main(argv)
    except SystemExit as exit_signal:
        return int(exit_signal.code)


def _publish(root: str, *extra: str) -> int:
    """Run the command the way an operator does, and return its exit code."""
    return _exit_code(["publish-transcripts", "--archive-root", root, *extra])


def _verify(root: str) -> int:
    """Run the shipped verifier the way an operator does (§5.3)."""
    return _exit_code(["verify", "--trusted-local", "--archive-root", root])


def _manifest_lines(root: str) -> list[str]:
    """The raw append-only history, one string per stored manifest line."""
    with open(os.path.join(root, MANIFEST_REL_PATH), encoding="utf-8") as handle:
        return [line for line in handle.read().splitlines() if line]


def _manifest_rows_per_work_id(root: str) -> dict[str, int]:
    """How many manifest lines each ``work_id`` carries."""
    counts: dict[str, int] = {}
    for line in _manifest_lines(root):
        work_id = str(json.loads(line)["work_id"])
        counts[work_id] = counts.get(work_id, 0) + 1
    return counts


def _declared(root: str, work_id: str) -> dict[str, str]:
    """The four product paths the effective row of ``work_id`` declares."""
    row = ManifestStore(root=root).load()[work_id]
    return {key: row[key] for key in PRODUCT_KEYS}


def _bundle_hashes(base: str, declared: dict[str, str]) -> dict[str, str]:
    """``path -> sha256`` for one declared bundle: four families and the marker."""
    paths = [os.path.join(base, value) for value in declared.values()]
    paths.append(_marker_path(base, declared))
    digests: dict[str, str] = {}
    for path in paths:
        with open(path, "rb") as handle:
            digests[os.path.relpath(path, base)] = hashlib.sha256(
                handle.read()
            ).hexdigest()
    return digests


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _frontmatter(md_text: str) -> dict[str, str]:
    """The published md's frontmatter, as ``key -> raw JSON value``."""
    lines = md_text.splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    pairs = {}
    for line in lines[1:end]:
        key, _, value = line.partition(": ")
        pairs[key] = value
    return pairs


def _published_line(work_id: str, cues: int, md_name: str) -> str:
    """The line a run prints for a candidate it publishes (§7)."""
    return (
        f"{work_id}: published (source=subtitle-ai lang=zh-CN version=1 "
        f"cues={cues}) transcripts/md/{md_name}"
    )


def _part_row(bvid: str) -> tuple:
    """Fixture F's declared part record for one bvid: ``(bvid, page, cid, ms, status)``."""
    return next(row for row in PARTS if row[0] == bvid)


def _row_for(payload: dict, work_id: str) -> dict:
    """One reader's row for one work item, or a failure naming what it reported."""
    rows = [row for row in payload["rows"] if row["work_id"] == work_id]
    assert len(rows) == 1, (work_id, payload["rows"])
    return rows[0]


# --------------------------------------------------------------------------- #
# Criterion 1 and 3: `verify --trusted-local`
# --------------------------------------------------------------------------- #


def test_verify_counts_the_projected_row_complete_and_absent_from_defects(
    tmp_root, capsys
):
    """Criterion 1 and §5.3: exit ``0``, no defects, no diagnostics — on this fixture.

    The negative control is the fixture's own state (iv), read by the **same**
    reader **before** the run: its four families are on disk and its row declares
    them, but the marker is gone, so the verifier reports ``missing_transcript``
    for it.  ``defect_count == 0`` below is therefore a statement this fixture
    can and does falsify, not a tautology about an empty manifest.
    """
    _build_fixture_f(tmp_root)
    # The build holds exactly one manifest row per work_id — the state the
    # readers agree on (contract §10) — and both of them are the chain's own.
    assert _manifest_rows_per_work_id(tmp_root) == {
        CHAIN_WORK_ID: 1,
        MARKER_WORK_ID: 1,
    }

    assert _verify(tmp_root) == 1
    before = json.loads(capsys.readouterr().out)
    assert [(d["work_id"], d["code"]) for d in before["defects"]] == [
        (MARKER_WORK_ID, "missing_transcript")
    ]
    # Nothing is *malformed* before the run either: the diagnostic surface is
    # empty on both sides of it, so the assertion below cannot be carried by a
    # fixture that merely fails to be readable.
    assert before["diagnostics"] == []

    assert _publish(tmp_root) == 0
    published = capsys.readouterr().out.splitlines()
    assert published == [
        f"{CHAIN_WORK_ID}: already_published",
        _published_line(DRIFT_WORK_ID, len(CAPTION_SEGMENTS), _md_name(DRIFT_BVID)),
        _published_line(FRESH_WORK_ID, len(CAPTION_SEGMENTS), _md_name(FRESH_BVID)),
        _published_line(GONE_WORK_ID, len(CAPTION_SEGMENTS), _md_name(GONE_BVID)),
        _published_line(MARKER_WORK_ID, len(CAPTION_SEGMENTS), _md_name(MARKER_BVID)),
        _published_line(NOISY_WORK_ID, len(NOISY_SEGMENTS), _md_name(NOISY_BVID)),
        "publish-transcripts: candidates=6 published=5 already_published=1 failed=0",
    ]

    assert _verify(tmp_root) == 0
    after = json.loads(capsys.readouterr().out)
    assert after["checked"] == len(CANDIDATE_WORK_IDS)
    assert after["defect_count"] == 0
    assert after["defects"] == []
    assert after["diagnostics"] == []
    # The reader the criterion names is the completeness reader, asked at a base
    # the row resolves under — so the projection's own statement is checked by
    # the shipped function and not only by the verifier's summary.
    assert archive_module.archive_bundle_complete(
        os.path.abspath(tmp_root), _declared(tmp_root, FRESH_WORK_ID)
    )


# --------------------------------------------------------------------------- #
# Criterion 3: `coverage --quality --format json`
# --------------------------------------------------------------------------- #


def test_coverage_quality_reports_no_reason_for_the_projected_row(tmp_root, capsys):
    """Criterion 3 and §5.3: no reason, four artifacts, two cues per segment.

    ``reasons`` is the union of the defect codes and the advisory content codes
    (``cli.py``'s ``_cmd_coverage_quality`` projects the row that way), so the
    literal empty list needs a caption body that carries neither.  The control is
    in the same report: ``BV1NOISY``'s published body repeats one cue text, so the
    reader *does* report ``duplicate_cue`` for it — the empty list above is a
    reading this fixture can move.
    """
    _build_fixture_f(tmp_root)
    assert _publish(tmp_root) == 0
    capsys.readouterr()

    assert (
        _exit_code(
            ["coverage", "--quality", "--format", "json", "--archive-root", tmp_root]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)

    assert report["scope"] is None
    assert report["diagnostics"] == []
    assert report["denominator"]["state"] == "available"

    projected = _row_for(report, FRESH_WORK_ID)
    assert projected["reasons"] == []
    assert projected["diagnostics"] == []
    # The four families: srt, txt, md and the raw sidecar.
    assert projected["artifact_count"] == 4
    # Both the srt and the sidecar carry the cues, so the count is twice the
    # winner's stored segment count (§5.3).
    assert projected["cue_count"] == 2 * len(CAPTION_SEGMENTS)
    assert projected["source"] == "subtitle-ai"
    assert projected["language"] == "zh-CN"
    assert projected["status"] == "archived"

    # The row is *in* the summary's count of valid work items: every manifest row
    # is valid, and the projected one is among them.
    summary = report["summary"]
    assert summary["total_work_items"] == len(CANDIDATE_WORK_IDS)
    assert summary["valid_work_items"] == summary["total_work_items"]
    assert summary["valid_work_items"] == len(report["rows"])
    assert [row["work_id"] for row in report["rows"]] == sorted(CANDIDATE_WORK_IDS)

    # The control, same report: the produced vocabulary is live, and a content
    # code alone is advisory — it leaves validity and the exit status alone.
    noisy = _row_for(report, NOISY_WORK_ID)
    assert noisy["reasons"] == ["duplicate_cue"]
    assert noisy["diagnostics"] == []
    assert noisy["artifact_count"] == 4


# --------------------------------------------------------------------------- #
# Criterion 4: the bundle claims no more than the store knows
# --------------------------------------------------------------------------- #


def test_the_projected_md_and_sidecar_carry_no_asr_key_and_name_the_stored_source(
    tmp_root, capsys
):
    """Criterion 4 and §4.1/§4.2/§4.3: ten frontmatter keys, no provenance."""
    _build_fixture_f(tmp_root)
    assert _publish(tmp_root) == 0
    capsys.readouterr()

    base = os.path.abspath(tmp_root)
    declared = _declared(tmp_root, FRESH_WORK_ID)
    md_text = _read_text(os.path.join(base, declared["md_path"]))
    raw_text = _read_text(os.path.join(base, declared["raw_path"]))

    # §4.1: exactly these ten keys, the live count after the D4/D5 revision
    # (`FRONTMATTER_KEYS` above; the contract's own table still reads nine —
    # M2).  The omissions of §4.2 are the same statement read from the other
    # side, and the inverted check is criterion 4's own: no line opens with an
    # `asr_` or `confidence` key.
    frontmatter = _frontmatter(md_text)
    assert set(frontmatter) == FRONTMATTER_KEYS
    assert json.loads(frontmatter["source"]) == "subtitle-ai"
    assert json.loads(frontmatter["work_id"]) == FRESH_WORK_ID
    assert json.loads(frontmatter["bvid"]) == FRESH_BVID
    # D5/D4 on the published artifact: the two titles are different facts and
    # both are present — the part's own name and the video's.  Fixture F seeds
    # every video as 投影读者测试视频 with parts named 第{n}集, so a writer that
    # emitted the part title twice, or dropped the video's, fails here rather
    # than satisfying the key-set equality above.
    assert json.loads(frontmatter["title"]) == "第1集"
    assert json.loads(frontmatter["video_title"]) == "投影读者测试视频"
    assert json.loads(frontmatter["date"]) == PUBDATE_STR
    # `duration_s` is the floored seconds of the stored milliseconds (§3.4).
    assert json.loads(frontmatter["duration_s"]) == _part_row(FRESH_BVID)[3] // 1000
    assert INVERTED_ASR_CHECK.search(md_text) is None

    # §4.3: the writer's own sidecar shape, one segment per stored segment, text
    # verbatim, seconds once — and no confidence key, because the store holds
    # none and `_confidence_summary` returns {} rather than a measured zero.
    sidecar = json.loads(raw_text)
    assert set(sidecar) == {"segments", "source"}
    assert sidecar["source"] == "subtitle-ai"
    assert [
        (segment["start"], segment["end"], segment["text"])
        for segment in sidecar["segments"]
    ] == [
        (segment.start_ms / 1000, segment.end_ms / 1000, segment.text)
        for segment in CAPTION_SEGMENTS
    ]
    assert INVERTED_ASR_CHECK.search(raw_text) is None

    # The control: the same writer, handed an ASR-shaped input, emits exactly the
    # keys the two checks above forbid — so the regex and the key-set equality
    # are shown to discriminate rather than to pass on any text at all.  It is
    # written under its own root, which Fixture F's manifest never declares.
    control_root = os.path.join(tmp_root, "control-asr")
    os.makedirs(control_root)
    control_paths = archive_module.write_archive(
        control_root,
        CONTROL_ASR_ENTRY,
        CONTROL_ASR_SEGMENTS,
        source="asr",
        asr_provenance=CONTROL_ASR_PROVENANCE,
    )
    control_md = _read_text(os.path.join(control_root, control_paths["md_path"]))
    control_raw = _read_text(os.path.join(control_root, control_paths["raw_path"]))
    assert INVERTED_ASR_CHECK.search(control_md) is not None
    assert set(json.loads(control_raw)) == {"segments", "source", "provenance"}
    assert set(_frontmatter(control_md)) != FRONTMATTER_KEYS


# --------------------------------------------------------------------------- #
# Criterion 3: `derive-manifest`
# --------------------------------------------------------------------------- #


def test_derive_manifest_queue_is_unchanged_by_the_projection(tmp_root, capsys):
    """Criterion 3 and §8: the queue is the store's relation, and it did not move.

    ``derive-manifest`` reads ``v_pending_subtitles`` — every part that holds no
    transcript and is not ``gone`` — so the projection publishing products beside
    the store must leave its count alone.  The control is the last step: the same
    relation is made to move by giving the queued part a transcript, which shows
    ``queue=1`` above is a live reading rather than a constant.
    """
    _build_fixture_f(tmp_root)

    assert _exit_code(["derive-manifest", "--archive-root", tmp_root]) == 0
    first = capsys.readouterr().out.splitlines()
    assert first == [
        f"{QUEUE_WORK_ID}: needs_audio (duration_s=3)",
        "derive-manifest: queue=1 derived=1 already_derived=0 chain_owned=0 "
        "identity_mismatch=0",
    ]

    assert _publish(tmp_root) == 0
    published = capsys.readouterr().out.splitlines()
    assert published[-1] == (
        "publish-transcripts: candidates=6 published=5 already_published=1 failed=0"
    )

    assert _exit_code(["derive-manifest", "--archive-root", tmp_root]) == 0
    second = capsys.readouterr().out.splitlines()
    assert second == [
        "derive-manifest: queue=1 derived=0 already_derived=1 chain_owned=0 "
        "identity_mismatch=0",
    ]

    # The control: the queue relation answers to its own condition, so the two
    # `queue=1` readings above are measured rather than assumed.
    _store_caption(tmp_root, QUEUE_BVID, 0)
    assert _exit_code(["derive-manifest", "--archive-root", tmp_root]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "derive-manifest: queue=0 derived=0 already_derived=0 chain_owned=0 "
        "identity_mismatch=0",
    ]


# --------------------------------------------------------------------------- #
# Criterion 2: idempotence, and the state that is not idempotent
# --------------------------------------------------------------------------- #


def test_a_second_stored_version_leaves_the_published_bytes_identical(
    tmp_root, capsys
):
    """State (iii) and §5.5: a newer stored version changes no published byte.

    The run's own contrast carries the claim: the same second run that answers
    ``already_published`` for the drifted part republishes the part whose
    completeness probe fails, so "nothing was written" is shown beside a
    candidate for which this run does write.
    """
    _build_fixture_f(tmp_root)
    assert _publish(tmp_root) == 0
    capsys.readouterr()

    base = os.path.abspath(tmp_root)
    declared = _declared(tmp_root, DRIFT_WORK_ID)
    before_bundle = _bundle_hashes(base, declared)
    before_lines = _manifest_rows_per_work_id(tmp_root)

    # The store gains a second version of the identity the bundle was published
    # from: the winner key's last component is `version` descending, so the read
    # now offers version 2 — and the row already declares a complete bundle.
    _store_caption(
        tmp_root,
        DRIFT_BVID,
        0,
        segments=SECOND_VERSION_SEGMENTS,
        version_tag="v2",
    )
    # The control, in the same run: state (iv) again, so the run has one
    # candidate it must leave alone and one it must republish.
    os.unlink(_marker_path(base, _declared(tmp_root, MARKER_WORK_ID)))

    assert _publish(tmp_root) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"{CHAIN_WORK_ID}: already_published",
        f"{DRIFT_WORK_ID}: already_published",
        f"{FRESH_WORK_ID}: already_published",
        f"{GONE_WORK_ID}: already_published",
        _published_line(MARKER_WORK_ID, len(CAPTION_SEGMENTS), _md_name(MARKER_BVID)),
        f"{NOISY_WORK_ID}: already_published",
        "publish-transcripts: candidates=6 published=1 already_published=5 failed=0",
    ]

    # Every byte of the drifted part's bundle is the first version's, marker
    # included, and the manifest records no second statement about it.
    assert _bundle_hashes(base, _declared(tmp_root, DRIFT_WORK_ID)) == before_bundle
    assert _manifest_rows_per_work_id(tmp_root)[DRIFT_WORK_ID] == before_lines[
        DRIFT_WORK_ID
    ]
    sidecar = json.loads(_read_text(os.path.join(base, declared["raw_path"])))
    assert [segment["text"] for segment in sidecar["segments"]] == [
        segment.text for segment in CAPTION_SEGMENTS
    ]
    # ... while the part whose probe failed was healed: it carries a marker now,
    # and the completeness reader confirms the four families it names.
    assert os.path.isfile(
        _marker_path(base, _declared(tmp_root, MARKER_WORK_ID))
    )
    assert archive_module.archive_bundle_complete(
        base, _declared(tmp_root, MARKER_WORK_ID)
    )


# --------------------------------------------------------------------------- #
# State (v): a gone part that still holds local text
# --------------------------------------------------------------------------- #


def test_a_gone_part_holding_a_transcript_is_published(tmp_root, capsys):
    """State (v) and §2: the membership rule is not filtered by ``processing_status``.

    The contrast is read from the store in the same case: the queue relation
    ``derive-manifest`` owns excludes this part on that very column, while this
    command publishes it — a gone part still holds local text.
    """
    _build_fixture_f(tmp_root)

    connection = open_database(tmp_root)
    try:
        # The two relations, read through the repository, on the same store: the
        # part is excluded from the queue for holding a transcript **and** for
        # being gone, and included here for the same first fact.
        status = connection.execute(
            "SELECT processing_status FROM video_parts WHERE bvid = ? AND page_index = 0",
            (GONE_BVID,),
        ).fetchone()["processing_status"]
        assert status == "gone"
        queued = {
            str(row["bvid"])
            for row in TranscriptRepository(connection).list_pending_subtitle_parts()
        }
    finally:
        connection.close()
    assert GONE_BVID not in queued
    assert QUEUE_BVID in queued

    assert _publish(tmp_root) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (
        _published_line(GONE_WORK_ID, len(CAPTION_SEGMENTS), _md_name(GONE_BVID))
        in lines
    )
    # The published candidate is a normal, complete bundle: the same four
    # families, the same marker, and the reader that counts them agrees.
    base = os.path.abspath(tmp_root)
    declared = _declared(tmp_root, GONE_WORK_ID)
    for key in PRODUCT_KEYS:
        assert os.path.isfile(os.path.join(base, declared[key]))
    assert archive_module.archive_bundle_complete(base, declared)
    assert ManifestStore(root=tmp_root).load()[GONE_WORK_ID]["status"] == "archived"
