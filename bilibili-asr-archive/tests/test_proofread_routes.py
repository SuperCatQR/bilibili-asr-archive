"""Route-integrity tests for ``proofread`` (plan 20261001-cue-timeline-and-proofread, C).

Two defects, one file:

1. ``read_asr_route_ms`` accepted *any* parseable ``bundle.raw.json``.  On a root
   that held only caption products — the E2E's ``route1-ai-caption`` shape — the
   caption-derived sidecar (``source: "subtitle-ai"``) was read as the ASR route,
   so the same text sat on both sides of the table: every block scored ``agree
   1.000`` and nothing needed adjudicating.  Measured before the fix on the four
   published 爱情 drafts (``/root/share/未明子-爱情四稿/AI字幕``): 20 blocks, 20 of
   them ``agree 1.000``, exit 0, no error.  A fake success is worse than a
   refusal — it is the failure this file exists to prevent, so the negative
   control below is the point of the file and not one case among many.
2. The two routes had to share one root (ASR read from the artifact root, captions
   from ``<archive-root>/archive.db``).  A run that exhausts the caption route on
   one root and produces ASR on another — exactly what the E2E does — was refused
   with ``missing caption route``.  ``--asr-root`` / ``--caption-root`` separate
   the two reads; naming neither must read exactly what was read before, so the
   default path is pinned here by the sha256 of both outputs, captured from the
   pre-change module.

Fixtures are synthetic and offline: the ASR sidecars are written in-test (no live
archive root is read) and the caption route is built on a real SQLite transcript
store, the same way ``tests/test_proofread.py`` builds its routes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "proofread"

#: The default path's outputs, hashed from the **pre-change** module (primary
#: checkout at ``73e90d3``, whose ``src/bili_asr/proofread.py`` is byte-identical
#: to this branch's parent) over the fixture assembled by :func:`_clean_default_workspace`.
#: Pinning the digests — rather than re-asserting the same invariants the
#: implementation computes — is what makes "the default path did not move" a
#: falsifiable claim instead of a restatement.
DEFAULT_SIDEBYSIDE_SHA256 = "e43d631420eff35a2841bbf52b32c7d9c5135b72755e58f368f08a557b381d9a"
DEFAULT_ALIGNMENT_SHA256 = "15cc5f73ff33d3a8b6ad6f98c6f2dbb84b946a6bb7c6a8f601d44157013babad"

#: The two caption rows the default-path fixture stores.  Copied from
#: ``tests/test_proofread.py`` (``CLEAN_CAPTIONS_MS``) **on purpose**: the golden
#: digests above were taken over that exact fixture, so re-deriving the text here
#: would invalidate them.
CLEAN_CAPTIONS_MS = [
    (0, 3200, "大家好，我们今天继续讨论。"),
    (3200, 6000, "我们先看一下基本情况。"),
    (6600, 10000, "这个问题的大背景是这样的。"),
    (12600, 15600, "所以我们先给出结论。"),
    (15600, 18800, "结论就是前面说的那样。"),
    (19600, 22600, "谢谢大家收看。"),
]


def _write_caption_route(
    connection, *, bvid: str, page_index: int, cid: int,
    segments_ms: list[tuple[int, int, str]],
) -> None:
    """Store one synthetic caption transcript (``source_kind=subtitle-ai``)."""

    from bili_asr.storage import MetadataRepository, TranscriptRepository
    from bili_asr.storage.models import AcquisitionRunRecord, TranscriptSegmentRecord
    from fixtures.metadata_records import (
        make_part_record,
        make_user_record,
        make_video_record,
    )

    metadata = MetadataRepository(connection)
    with metadata.transaction():
        metadata.upsert_user(make_user_record())
        metadata.upsert_video(make_video_record(bvid, aid=None, title=f"{bvid} 视频"))
        metadata.upsert_part(
            make_part_record(
                bvid, page_index=page_index, cid=cid, title=f"{bvid} p{page_index}",
                processing_status="metadata_collected",
            )
        )
    part_id = int(connection.execute(
        "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
        (bvid, page_index),
    ).fetchone()["video_part_id"])

    repository = TranscriptRepository(connection)
    run_id = f"fixture-caption-{bvid}-{page_index}"
    repository.start_acquisition_run(AcquisitionRunRecord(
        run_id=run_id, kind="subtitle", selector_kind="bvid", selector_target=bvid,
        requested_limit=None, credential_present=False, started_at=1_700_000_000,
    ))
    repository.record_acquired_transcript(
        run_id=run_id, video_part_id=part_id, source_kind="subtitle-ai",
        language="ai-zh",
        segments=tuple(
            TranscriptSegmentRecord(start_ms=start, end_ms=end, text=text)
            for start, end, text in segments_ms
        ),
        started_at=1_700_000_000, finished_at=1_700_000_000, created_at=1_700_000_000,
    )


def _write_raw(root: Path, stem: str, document: dict) -> Path:
    """Write one ``bundle.raw.json`` at the shape-A path under ``root``."""

    directory = root / "transcripts" / stem
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "bundle.raw.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def _clean_default_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """The fixture the golden digests were taken over: both routes on one root.

    ``archive_root`` holds the caption store; ``artifact_root`` holds the ASR
    sidecar *and* receives the outputs — the identity case when no artifact root
    is configured.
    """

    from bili_asr.storage import open_database

    archive_root = tmp_path / "archive"
    artifact_root = tmp_path / "artifacts"
    (artifact_root / "transcripts").mkdir(parents=True)
    connection = open_database(os.fspath(archive_root))
    try:
        _write_caption_route(connection, bvid="BV1proofClean", page_index=0, cid=101,
                             segments_ms=CLEAN_CAPTIONS_MS)
    finally:
        connection.close()
    directory = artifact_root / "transcripts" / "BV1proofClean.p0"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bundle.raw.json").write_bytes(
        (FIXTURES / "BV1proofClean.p0.json").read_bytes()
    )
    return archive_root, artifact_root


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------------------
# The negative control: a caption-derived sidecar is not the ASR route.
# --------------------------------------------------------------------------------------


def _caption_derived_sidecar() -> dict:
    """The shape a caption publication writes: the same text on both routes.

    ``archive.write_archive`` emits ``{"segments", "source"}`` with the caption
    ``source`` kind (``archive.py:570`` and ``:545``'s ``source=`` argument), and
    the published 爱情 drafts carry exactly these two keys with ``subtitle-ai``.
    """

    return {
        "segments": [
            {"start": start / 1000, "end": end / 1000, "text": text}
            for start, end, text in CLEAN_CAPTIONS_MS
        ],
        "source": "subtitle-ai",
    }


def test_caption_derived_raw_is_refused_and_names_the_source(tmp_path: Path) -> None:
    """The core regression: no silent all-``agree 1.000`` table, and the error says why.

    A caption-derived sidecar holds the caption route's own text, so accepting it
    as the ASR route puts one route on both sides: every block agrees with
    itself and nothing is adjudicated — measured as 20/20 blocks at ``agree
    1.000`` on the published drafts, exit 0.  The refusal must name the source
    actually found, because "invalid raw" alone leaves the operator to guess
    which of the two files was picked up.
    """

    from bili_asr.proofread import ProofreadRouteError, build_sidebyside

    archive_root = tmp_path / "archive"
    artifact_root = tmp_path / "artifacts"
    (artifact_root / "transcripts").mkdir(parents=True)
    raw_path = _write_raw(artifact_root, "BV1fakeAsr.p0", _caption_derived_sidecar())

    from bili_asr.storage import open_database

    connection = open_database(os.fspath(archive_root))
    try:
        _write_caption_route(connection, bvid="BV1fakeAsr", page_index=0, cid=201,
                             segments_ms=CLEAN_CAPTIONS_MS)
    finally:
        connection.close()

    with pytest.raises(ProofreadRouteError) as excinfo:
        build_sidebyside("BV1fakeAsr", 0, archive_root=os.fspath(archive_root),
                         artifact_root=os.fspath(artifact_root))

    message = str(excinfo.value)
    assert "BV1fakeAsr:p0" in message
    assert "expected source=asr, found source=subtitle-ai" in message
    assert os.fspath(raw_path) in message
    # The failure is total: a rejected read writes nothing, so no half-built
    # table can be mistaken for a completed one.
    assert not (artifact_root / ".tmp" / "proofread-work" / "inputs").exists()


@pytest.mark.parametrize(
    ("document_source", "expected"),
    [
        ("subtitle-ai", "found source=subtitle-ai"),
        ("subtitle", "found source=subtitle"),
        ("proofread", "found source=proofread"),
        (None, "found source=<missing>"),
    ],
)
def test_read_asr_route_rejects_every_source_that_is_not_asr(
    tmp_path: Path, document_source: object, expected: str
) -> None:
    """``source == "asr"`` is the whole rule, not a caption-shaped special case.

    ``proofread`` is the merged route and ``subtitle`` the CC one; a missing
    ``source`` is what a hand-written or truncated sidecar looks like.  All of
    them are *some* other route's text or an unknown origin, and none may be
    presented as the ASR route.
    """

    from bili_asr.proofread import ProofreadRouteError, read_asr_route_ms

    artifact_root = tmp_path / "artifacts"
    (artifact_root / "transcripts").mkdir(parents=True)
    document: dict = {"segments": [{"start": 0.0, "end": 1.0, "text": "句子。"}]}
    if document_source is not None:
        document["source"] = document_source
    _write_raw(artifact_root, "BV1src.p0", document)

    with pytest.raises(ProofreadRouteError) as excinfo:
        read_asr_route_ms(artifact_root, "BV1src", 0)

    assert expected in str(excinfo.value)


def test_asr_shaped_sidecar_still_reads(tmp_path: Path) -> None:
    """The control for the refusal: ``source=asr`` is accepted, unchanged.

    Without this, a reader that rejected everything would satisfy the test above.
    """

    from bili_asr.proofread import read_asr_route_ms

    artifact_root = tmp_path / "artifacts"
    (artifact_root / "transcripts").mkdir(parents=True)
    _write_raw(artifact_root, "BV1ok.p0", {
        "segments": [{"start": 0.5, "end": 1.25, "text": "第一句。"},
                     {"start": 1.25, "end": 2.0, "text": "第二句。"}],
        "source": "asr",
        "provenance": {"model": "Qwen3-ASR"},
    })

    assert read_asr_route_ms(artifact_root, "BV1ok", 0) == [
        (500, 1250, "第一句。"),
        (1250, 2000, "第二句。"),
    ]


# --------------------------------------------------------------------------------------
# The positive: two roots, one route each.
# --------------------------------------------------------------------------------------


def _split_root_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """The E2E shape: ASR products on one root, the caption store on another.

    The texts differ by more than the agree threshold in one block, so a table
    that came back all-``agree`` would itself be the failure — the fixture has to
    be able to *disagree* for this test to mean anything.
    """

    from bili_asr.storage import open_database

    asr_root = tmp_path / "route2-asr"
    caption_root = tmp_path / "route1-ai-caption"
    asr_root.mkdir()
    _write_raw(asr_root, "BV1split.p0", {
        "segments": [
            {"start": 0.0, "end": 4.0, "text": "我们来讨论劳动法的相关问题。"},
            {"start": 4.0, "end": 8.0, "text": "这里涉及很多具体的案例。"},
            {"start": 30.0, "end": 34.0, "text": "所以回到最初的问题上来。"},
        ],
        "source": "asr",
    })
    connection = open_database(os.fspath(caption_root))
    try:
        _write_caption_route(
            connection, bvid="BV1split", page_index=0, cid=301,
            segments_ms=[
                (0, 4000, "我们聊一聊劳动法的问题。"),
                (4000, 8000, "这里面有很多具体案例。"),
                (30000, 34000, "所以我们回到最初的问题上来。"),
            ],
        )
    finally:
        connection.close()
    return asr_root, caption_root


def test_asr_root_moves_the_read_off_its_default(tmp_path: Path) -> None:
    """``asr_root`` must actually MOVE the read: a decoy default must not be read.

    The sibling split-root tests pass ``asr_root`` the same value as
    ``artifact_root``, so an implementation that ignores the parameter entirely
    satisfies them (measured: constants at the two ternaries leave all of the
    older split-root tests green).  Here the default location holds a different,
    wrong document: if ``asr_root`` is honoured the decoy is never opened and the
    table carries the real ASR text; if it is ignored the decoy is read and the
    assertion fails.
    """

    from bili_asr.proofread import build_sidebyside

    asr_root, caption_root = _split_root_workspace(tmp_path)
    decoy = tmp_path / "decoy-asr"
    decoy.mkdir()
    _write_raw(decoy, "BV1split.p0", {
        "segments": [
            {"start": 0.0, "end": 8.0, "text": "这是诱饵文件，绝不应被读取。"},
            {"start": 30.0, "end": 34.0, "text": "诱饵的第二段。"},
        ],
        "source": "asr",
    })

    sidebyside_path, _ = build_sidebyside(
        "BV1split", 0,
        archive_root=os.fspath(caption_root),
        artifact_root=os.fspath(decoy),
        asr_root=os.fspath(asr_root),
        caption_root=os.fspath(caption_root),
    )

    table = sidebyside_path.read_text(encoding="utf-8")
    assert "诱饵" not in table, "asr_root was ignored: the default root was read"
    assert "劳动法" in table, "the real ASR root's text is missing from the table"


def test_caption_root_moves_the_read_off_its_default(tmp_path: Path) -> None:
    """``caption_root`` must actually MOVE the read: a decoy default must not be read."""

    from bili_asr.proofread import build_sidebyside
    from bili_asr.storage import open_database

    asr_root, caption_root = _split_root_workspace(tmp_path)
    decoy = tmp_path / "decoy-caption"
    decoy.mkdir()
    connection = open_database(os.fspath(decoy))
    try:
        _write_caption_route(
            connection, bvid="BV1split", page_index=0, cid=301,
            segments_ms=[(0, 8000, "诱饵字幕，绝不应被读取。"),
                         (30000, 34000, "诱饵字幕第二段。")],
        )
    finally:
        connection.close()

    sidebyside_path, _ = build_sidebyside(
        "BV1split", 0,
        archive_root=os.fspath(decoy),
        artifact_root=os.fspath(asr_root),
        asr_root=os.fspath(asr_root),
        caption_root=os.fspath(caption_root),
    )

    table = sidebyside_path.read_text(encoding="utf-8")
    assert "诱饵字幕" not in table, "caption_root was ignored: the default root was read"


def test_split_roots_produce_the_sidebyside(tmp_path: Path) -> None:
    """``asr_root`` + ``caption_root`` read the two routes from two roots."""

    from bili_asr.proofread import build_sidebyside

    asr_root, caption_root = _split_root_workspace(tmp_path)

    sidebyside_path, align_path = build_sidebyside(
        "BV1split", 0,
        archive_root=os.fspath(caption_root),
        artifact_root=os.fspath(asr_root),
        asr_root=os.fspath(asr_root),
        caption_root=os.fspath(caption_root),
    )

    # Writes stay under the artifact root — the new parameters move reads only.
    assert sidebyside_path == (
        asr_root / ".tmp" / "proofread-work" / "inputs" / "BV1split.p0.sidebyside.md"
    )
    assert align_path == (
        asr_root / ".tmp" / "proofread-work" / "align" / "BV1split.p0.alignment.jsonl"
    )
    assert not (caption_root / ".tmp").exists()

    headings = [
        line for line in sidebyside_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    # The 0–8 s ASR segments run consecutively (gap 0 ≤ BLOCK_GAP_MS), so they
    # form one block; 8→30 s is a real gap and opens the second.  Both routes
    # were read: block 1 pairs ASR text with *different* caption text and scores
    # below 1.000.  Reading one root twice — the defect — would show 1.000 here.
    assert headings == [
        "## 1 [00:00:00,000-00:00:30,000] (review 0.735)",
        "## 2 [00:00:30,000-00:00:42,000] (agree 0.923)",
    ], headings
    assert "1.000" not in "".join(headings)

    # Each column holds its own root's text, spelled out, so "two roots were
    # read" is checked against the words and not only against a score.
    row = [
        line for line in sidebyside_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("| 00:00:00,000")
    ][0]
    assert "我们来讨论劳动法的相关问题。这里涉及很多具体的案例。" in row   # asr_root
    assert "我们聊一聊劳动法的问题。这里面有很多具体案例。" in row          # caption_root


def test_split_roots_without_the_caption_root_still_refuses(tmp_path: Path) -> None:
    """Dropping ``caption_root`` reproduces the old refusal, not a quiet pass.

    The separation is *opt-in*: with ``caption_root`` unset the caption route is
    read from ``archive_root``, which is the pre-change behaviour — here the ASR
    root, which holds no store at all.
    """

    from bili_asr.proofread import ProofreadRouteError, build_sidebyside

    asr_root, _ = _split_root_workspace(tmp_path)

    with pytest.raises(ProofreadRouteError) as excinfo:
        build_sidebyside("BV1split", 0, archive_root=os.fspath(asr_root),
                         artifact_root=os.fspath(asr_root),
                         asr_root=os.fspath(asr_root))

    assert "missing caption route" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# The regression: no new flags means byte-identical behaviour.
# --------------------------------------------------------------------------------------


def test_default_roots_are_byte_identical_to_the_pre_change_module(tmp_path: Path) -> None:
    """No ``asr_root`` / ``caption_root``: both outputs match the captured digests.

    The digests come from the module as it was before this change, run over this
    exact fixture, so a mismatch is a behaviour change on the default path — the
    one path every existing caller and every documented invocation takes.
    """

    from bili_asr.proofread import build_sidebyside

    archive_root, artifact_root = _clean_default_workspace(tmp_path)

    sidebyside_path, align_path = build_sidebyside(
        "BV1proofClean", 0, archive_root=os.fspath(archive_root),
        artifact_root=os.fspath(artifact_root),
    )

    assert _sha256(sidebyside_path) == DEFAULT_SIDEBYSIDE_SHA256
    assert _sha256(align_path) == DEFAULT_ALIGNMENT_SHA256


def test_cli_default_path_reads_the_root_it_always_read(tmp_path: Path) -> None:
    """The command line, unchanged: same exit, same lines, same files, no new flags.

    ``--asr-root`` / ``--caption-root`` are additive, so their absence has to
    leave the printed contract exactly as it was.
    """

    from bili_asr.cli import main

    archive_root, artifact_root = _clean_default_workspace(tmp_path)

    rc = main([
        "proofread", "--bvid", "BV1proofClean:p0",
        "--archive-root", os.fspath(archive_root),
        "--artifact-root", os.fspath(artifact_root),
    ])

    assert rc == 0
    work = artifact_root / ".tmp" / "proofread-work"
    assert _sha256(work / "inputs" / "BV1proofClean.p0.sidebyside.md") == (
        DEFAULT_SIDEBYSIDE_SHA256
    )
    assert _sha256(work / "align" / "BV1proofClean.p0.alignment.jsonl") == (
        DEFAULT_ALIGNMENT_SHA256
    )


# --------------------------------------------------------------------------------------
# The two flags through the command line (the operator-facing half).
# --------------------------------------------------------------------------------------


def test_cli_split_roots_writes_under_the_artifact_root(tmp_path: Path, capsys) -> None:
    """``--asr-root`` / ``--caption-root`` reach ``build_sidebyside``."""

    from bili_asr.cli import main

    asr_root, caption_root = _split_root_workspace(tmp_path)

    rc = main([
        "proofread", "--bvid", "BV1split:p0",
        "--archive-root", os.fspath(caption_root),
        "--artifact-root", os.fspath(asr_root),
        "--asr-root", os.fspath(asr_root),
        "--caption-root", os.fspath(caption_root),
    ])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "BV1split:p0: side-by-side written" in captured.out
    assert "BV1split:p0: alignment written" in captured.out
    assert (asr_root / ".tmp" / "proofread-work" / "inputs"
            / "BV1split.p0.sidebyside.md").is_file()


def test_cli_refuses_a_caption_derived_asr_root(tmp_path: Path, capsys) -> None:
    """The negative control at the boundary an operator actually meets it.

    ``--asr-root`` pointing at a root of caption products is the E2E mistake in
    one flag: the run must exit 1 with the source named, and print no success
    line.
    """

    from bili_asr.cli import main
    from bili_asr.storage import open_database

    asr_root = tmp_path / "route1-ai-caption"
    caption_root = tmp_path / "route1-ai-caption"
    asr_root.mkdir()
    _write_raw(asr_root, "BV1wrongroot.p0", _caption_derived_sidecar())
    connection = open_database(os.fspath(caption_root))
    try:
        _write_caption_route(connection, bvid="BV1wrongroot", page_index=0, cid=401,
                             segments_ms=CLEAN_CAPTIONS_MS)
    finally:
        connection.close()

    rc = main([
        "proofread", "--bvid", "BV1wrongroot:p0",
        "--archive-root", os.fspath(caption_root),
        "--artifact-root", os.fspath(asr_root),
        "--asr-root", os.fspath(asr_root),
        "--caption-root", os.fspath(caption_root),
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "expected source=asr, found source=subtitle-ai" in captured.err
    assert "written" not in captured.out
