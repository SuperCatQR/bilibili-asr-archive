"""Tests for ``align-transcripts`` — the two-route alignment builder (Task 3).

The command is the only place D13's route choice lives: the caption route is a
read of the store, the ASR route is a read of the bundle's ``raw`` sidecar, and
the pure service (``services/editorial_alignment``) opens neither.  These cases
drive the command end to end through ``bili_asr.cli.main`` against synthetic
archive roots — one stored part, its caption row in the store and its ASR
sidecar below the root, built through the repository APIs and the shipped
writer's own path rule (``archive.bundle_paths``) rather than by guessing a
filename — so the two routes the command reads are the two routes the archive
actually publishes.

Everything here is inline and self-contained on purpose: the ``/mnt/123pan``
corpus is a measurement artifact, not a test dependency, so this suite passes on
a machine that has never seen it.  The corpus cases that follow the crafted ones
``skipif`` the corpus is absent (D12).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import NamedTuple

import pytest

from bili_asr import archive as archive_module
from bili_asr.cli import main
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

# --- the crafted fixture ------------------------------------------------------

BVID = "BV1T3ALIGN"
CID_P0 = 903_001
CID_P1 = 903_002
#: The artifact root's family (D16): ``<artifact-root>/alignments/<work_id>.jsonl``.
ALIGNMENTS = "alignments"

#: The crafted ASR route, in the service's own unit (milliseconds).  The two
#: segments are 1000 ms apart, below ``GAP_MS = 1500``, so they form **one**
#: block — the merge path, not the break path.
ASR_ROUTE = ((0, 3_000, "第一段，此在。"), (4_000, 7_000, "第二段。"))
#: The crafted caption route.  Cue 1's midpoint (1500 ms) falls inside the block;
#: cue 2's (11000 ms) falls past its end, which is the unattached bucket §E's
#: accounting has to show rather than drop.
CAPTION_ROUTE = ((0, 3_000, "第一段，装置。"), (10_000, 12_000, "另一段。"))

#: The accounting the crafted pair must print, as ``accounting_line`` spells it.
EXPECTED_LINE = (
    f"{BVID}:p0: aligned blocks=1 segments_in=2 segments_attached=2 "
    "segments_unattached=0 cues_in=2 cues_attached=1 cues_unattached=1"
)
EXPECTED_HEADER = {
    "kind": "header",
    "work_id": f"{BVID}:p0",
    "blocks": 1,
    "segments_in": 2,
    "segments_attached": 2,
    "segments_unattached": 0,
    "cues_in": 2,
    "cues_attached": 1,
    "cues_unattached": 1,
}


def _exit_code(argv: list[str]) -> int:
    """The command's exit code, argparse's own ``SystemExit`` included."""
    try:
        return main(argv)
    except SystemExit as signal:
        return int(signal.code)


def _entry(page_index: int, cid: int, bvid: str = BVID) -> dict:
    """The writer's entry for one stored part — the fields ``archive_stem`` reads."""
    return {
        "bvid": bvid,
        "work_id": f"{bvid}:p{page_index}",
        "page_index": page_index,
        "cid": cid,
        "unresolved": False,
        "page_label": "",
    }


def _sidecar_path(root: str, page_index: int, cid: int, bvid: str = BVID) -> Path:
    """The bundle's ``raw`` sidecar path, through the shipped writer's own rule."""
    return archive_module.bundle_paths(root, _entry(page_index, cid, bvid))["raw_path"]


def _seed_part(root: str, page_index: int, cid: int) -> None:
    """Create the store with exactly one stored part, through the repositories."""
    connection = open_database(root)
    try:
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            metadata.upsert_user(make_user_record())
            metadata.upsert_video(make_video_record(BVID, aid=None, title="T3"))
            metadata.upsert_part(
                make_part_record(BVID, page_index=page_index, cid=cid)
            )
    finally:
        connection.close()


def _store_caption(root: str, page_index: int, segments=CAPTION_ROUTE) -> None:
    """Store one ``subtitle-ai`` caption body — the caption route (D13)."""
    connection = open_database(root)
    try:
        part_id = int(
            connection.execute(
                "SELECT video_part_id FROM video_parts "
                "WHERE bvid = ? AND page_index = ?",
                (BVID, page_index),
            ).fetchone()["video_part_id"]
        )
        repository = TranscriptRepository(connection)
        run_id = f"caption-{BVID}-{page_index}"
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
            video_part_id=part_id,
            source_kind="subtitle-ai",
            language="zh-CN",
            segments=tuple(
                TranscriptSegmentRecord(start, end, text)
                for start, end, text in segments
            ),
            started_at=200,
            finished_at=300,
            created_at=400,
        )
    finally:
        connection.close()


def _write_sidecar(
    root: str, page_index: int, cid: int, segments=ASR_ROUTE, *,
    source: str = "asr", hotwords: str = "拉康",
) -> Path:
    """Write the bundle's ASR sidecar — the ASR route (D13) — at its writer path.

    The sidecar records **seconds** (``archive.write_archive`` writes whatever an
    ASR run produced) while the store holds milliseconds, so this fixture is the
    unit boundary Task 3 has to convert across, not a copy of the store's shape.
    """
    sidecar = _sidecar_path(root, page_index, cid)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    document: dict = {
        "segments": [
            {"start": start / 1000, "end": end / 1000, "text": text}
            for start, end, text in segments
        ],
        "source": source,
    }
    if source == "asr":
        document["provenance"] = {"model": "t3-fixture", "hotwords": hotwords}
    sidecar.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return sidecar


def _fixture_root(tmp_root: str, *, pages: tuple[int, ...] = (0,)) -> tuple[str, str]:
    """One archive root holding both routes for every page, plus an artifact root.

    The artifact root is a **sibling** of the archive root on purpose: D16's write
    goes below the configured root, and the point of the flag is that it can be a
    different directory from the archive's own state.
    """
    root = os.path.join(tmp_root, "archive")
    artifacts = os.path.join(tmp_root, "artifacts")
    os.makedirs(root, exist_ok=True)
    os.makedirs(artifacts, exist_ok=True)
    for page_index in pages:
        cid = CID_P0 if page_index == 0 else CID_P1
        _seed_part(root, page_index, cid)
        _store_caption(root, page_index)
        _write_sidecar(root, page_index, cid)
    return root, artifacts


def _align(root: str, artifacts: str, bvid: str | None = None) -> int:
    """Run the command the way an operator does, and return its exit code."""
    argv = ["align-transcripts", "--archive-root", root, "--artifact-root", artifacts]
    if bvid is not None:
        argv += ["--bvid", bvid]
    return _exit_code(argv)


def _jsonl(root: str, artifacts: str, work_id: str) -> list[str]:
    """The artifact's lines, as the operator would read them."""
    path = Path(artifacts) / ALIGNMENTS / f"{work_id}.jsonl"
    return path.read_text(encoding="utf-8").splitlines()


def _files(root: str) -> dict[str, tuple[int, str]]:
    """Every file below ``root``: size and sha256, for a before/after diff."""
    base = Path(root)
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


# --- 1. the printed surface ---------------------------------------------------


def test_align_transcripts_prints_one_line_per_candidate_then_the_closing_counts_line(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """D11(c): the accounting line per candidate, then the counts line with zeros."""
    root, artifacts = _fixture_root(tmp_root)

    assert _align(root, artifacts) == 0
    assert capsys.readouterr().out.splitlines() == [
        EXPECTED_LINE,
        "align-transcripts: candidates=1 aligned=1 refused=0",
    ]


def test_align_transcripts_covers_every_stored_part_when_no_selector_is_given(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """D11(b): no ``--bvid`` means every stored part, in the read's locked order."""
    root, artifacts = _fixture_root(tmp_root, pages=(0, 1))

    assert _align(root, artifacts) == 0
    out = capsys.readouterr().out.splitlines()
    # One accounting line per stored part, in the read's locked order (page
    # order), then the closing counts.
    assert out[0].startswith(f"{BVID}:p0: aligned ")
    assert out[1].startswith(f"{BVID}:p1: aligned ")
    assert out[2] == "align-transcripts: candidates=2 aligned=2 refused=0"
    assert len(out) == 3


def test_align_transcripts_bvid_pn_selects_exactly_that_part(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The shipped ``_subtitle_selector`` rule: ``bvid:pN`` names one part."""
    root, artifacts = _fixture_root(tmp_root, pages=(0, 1))

    assert _align(root, artifacts, bvid=f"{BVID}:p1") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"{BVID}:p1: aligned ")
    assert out[-1] == "align-transcripts: candidates=1 aligned=1 refused=0"
    assert (Path(artifacts) / ALIGNMENTS / f"{BVID}:p1.jsonl").is_file()
    assert not (Path(artifacts) / ALIGNMENTS / f"{BVID}:p0.jsonl").exists()


def test_an_unknown_bvid_is_the_documented_configuration_error_on_exit_1(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The shipped line form, exit 1 — and no candidate is invented for it."""
    root, artifacts = _fixture_root(tmp_root)

    assert _align(root, artifacts, bvid="BV1nosuchpart") == 1
    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "align-transcripts: unknown --bvid BV1nosuchpart"
    ]
    assert captured.out == ""
    assert not (Path(artifacts) / ALIGNMENTS).exists()


def test_zero_candidates_is_exit_0(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty is success (D11(d)): every count printed, all of them zero."""
    root, artifacts = _fixture_root(tmp_root, pages=())
    _seed_part(root, 0, CID_P0)
    # A stored part with no stored transcript holds no caption route, so the
    # range is empty rather than one invented candidate.

    assert _align(root, artifacts) == 0
    assert capsys.readouterr().out.splitlines() == [
        "align-transcripts: candidates=0 aligned=0 refused=0"
    ]
    assert not (Path(artifacts) / ALIGNMENTS).exists()


# --- 2. the artifact (D16) ----------------------------------------------------


def test_align_transcripts_writes_the_header_then_one_line_per_input_unit(
    tmp_root: str,
) -> None:
    """D16: the header carries ``blocks`` + the six counts, then one unit a line."""
    root, artifacts = _fixture_root(tmp_root)

    assert _align(root, artifacts) == 0
    lines = _jsonl(root, artifacts, f"{BVID}:p0")
    records = [json.loads(line) for line in lines]

    assert records[0] == EXPECTED_HEADER
    assert records[1:] == [
        {"kind": "segment", "index": 1, "start_ms": 0, "end_ms": 3_000, "block": 1},
        {"kind": "segment", "index": 2, "start_ms": 4_000, "end_ms": 7_000, "block": 1},
        {"kind": "cue", "index": 1, "start_ms": 0, "end_ms": 3_000, "block": 1},
        {"kind": "cue", "index": 2, "start_ms": 10_000, "end_ms": 12_000, "block": None},
    ]
    # One line per input unit, in route order: 2 ASR + 2 caption + the header.
    assert len(lines) == 1 + 2 + 2


def test_align_transcripts_writes_nothing_under_the_transcript_families(
    tmp_root: str,
) -> None:
    """The STOP condition: the four product families belong to the archive writer."""
    root, artifacts = _fixture_root(tmp_root)
    before = _files(os.path.join(root, "transcripts"))

    assert _align(root, artifacts) == 0

    assert _files(os.path.join(root, "transcripts")) == before
    for family in ("srt", "txt", "md"):
        assert not (Path(root) / "transcripts" / family).exists()
    assert (Path(artifacts) / ALIGNMENTS / f"{BVID}:p0.jsonl").is_file()


def test_a_second_run_rewrites_the_jsonl_byte_identically(tmp_root: str) -> None:
    """D16: a second run is byte-identical, so the artifact is reproducible."""
    root, artifacts = _fixture_root(tmp_root)
    path = Path(artifacts) / ALIGNMENTS / f"{BVID}:p0.jsonl"

    assert _align(root, artifacts) == 0
    first = path.read_bytes()
    assert _align(root, artifacts) == 0
    assert path.read_bytes() == first


# --- 3. the refusals ----------------------------------------------------------


def test_a_part_whose_asr_sidecar_is_missing_is_refused_by_name_never_aligned(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A named selector asserts the part is ready; a missing route is a refusal."""
    root, artifacts = _fixture_root(tmp_root)
    _sidecar_path(root, 0, CID_P0).unlink()

    assert _align(root, artifacts, bvid=f"{BVID}:p0") == 1
    out = capsys.readouterr().out.splitlines()
    # §E: the message carries the part (in ``work_id``) plus which route is
    # absent, in the shipped ``refused (<rule>) at <location>`` form.
    assert out[0] == f"{BVID}:p0: refused (route_absent_for_part) at asr route (absent)"
    assert out[-1] == "align-transcripts: candidates=1 aligned=0 refused=1"
    assert not (Path(artifacts) / ALIGNMENTS / f"{BVID}:p0.jsonl").exists()


def test_no_path_through_the_command_produces_exit_2(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """D8: ``2`` is reserved for terminal API failure and no socket is opened."""
    root, artifacts = _fixture_root(tmp_root)
    for argv in (
        ["align-transcripts"],
        ["align-transcripts", "--bvid"],
        ["align-transcripts", "--archive-root"],
        ["align-transcripts", "--no-such-flag"],
        ["align-transcripts", "--archive-root", root, "--artifact-root", "/nonexistent-root"],
    ):
        assert _exit_code(argv) != 2
    capsys.readouterr()

    # Non-vacuity: the same command, given a root that exists, is a clean run —
    # so the loop above is not passing because nothing can ever succeed.
    assert _align(root, artifacts) == 0
    assert capsys.readouterr().out.splitlines() == [
        EXPECTED_LINE,
        "align-transcripts: candidates=1 aligned=1 refused=0",
    ]


# --- 4. the real corpus, when this machine has it (D12) -----------------------


class CorpusItem(NamedTuple):
    """One delivered corpus item: its written base, its two routes, its numbers.

    **D12** keeps the corpus path-referenced — these are paths below
    ``CORPUS_ROOT``, never a copy — so the three pins are sha256 digests of files
    that stay where the wave left them.  ``recorded_line`` is the accounting the
    command printed for this item on 2026-09-24, frozen verbatim: the replay case
    asserts the command prints it again, so a drift in either the routes, the
    service's block rule or the line's spelling fails here rather than in an
    operator's terminal.  The wave's own ``INDEX.md`` counts 对齐块 with the
    *machine-baseline's* ~12-second algorithm, which is not this service's
    ``GAP_MS`` rule, so that column is deliberately **not** an oracle here.
    """

    bvid: str
    markdown: str
    asr_sidecar: str
    caption_sidecar: str
    markdown_sha256: str
    asr_sha256: str
    caption_sha256: str
    recorded_line: str


CORPUS_ROOT = "/mnt/123pan/bili-asr-e2e"


def _item(bvid: str, markdown_digest: str, asr_digest: str, caption_digest: str,
          work_line: str) -> CorpusItem:
    """One of the frozen six, with its three paths fixed by the item's own name."""
    return CorpusItem(
        bvid=bvid,
        markdown=f"proofread-transcripts/md/{bvid}.p0.md",
        asr_sidecar=f"asr-vs-subtitle/transcripts/raw/{bvid}.p0.json",
        caption_sidecar=f"subtitle-publish/transcripts/raw/{bvid}.p0.json",
        markdown_sha256=markdown_digest,
        asr_sha256=asr_digest,
        caption_sha256=caption_digest,
        recorded_line=work_line,
    )


#: The frozen six (D12), digests measured 2026-09-24 against the delivered tree.
CORPUS: tuple[CorpusItem, ...] = (
    _item(
        "BV11p5qzAE6s",
        "fa37c489d3a3d1967e1e00e0654b2c6359732ce522930279a03cbb7bfbda8204",
        "06de4e45b3522dddcab36d4609f81ca1b9d4cf30921e60db5871f35f8bf43b2f",
        "c8a4cc8958ec041d5f6c89c4b1e92c04cfd78cccef83caec3c6d833d80668d14",
        "BV11p5qzAE6s:p0: aligned blocks=90 segments_in=503 segments_attached=503 segments_unattached=0 cues_in=918 cues_attached=903 cues_unattached=15",
    ),
    _item(
        "BV1BdtazGEBE",
        "005cd5fab1c65ac372d6e066494ad041cf2f34d4f101541a3b750d843640f568",
        "f71993f8c71a8198c9aaab76ec1c722640789ff5c9e720097722c4951314d826",
        "05ec43be74928670662769c0ee8a0a01caca685c0fec9720da6b6ab07fa36990",
        "BV1BdtazGEBE:p0: aligned blocks=315 segments_in=1248 segments_attached=1248 segments_unattached=0 cues_in=2318 cues_attached=2244 cues_unattached=74",
    ),
    _item(
        "BV1iddQYQE7D",
        "f68bfe7568cfa455a244c7b64b4737669a4bdf40f86818a5fc9396b9f2416667",
        "db012cdc42982bd4c35d51c984dc5ccb3dfb640606d7d7fc5c88960115f35e79",
        "8ae784458d708b0ad76644b944a1806ca89b8adfb99904457b5bbb270549ef62",
        "BV1iddQYQE7D:p0: aligned blocks=333 segments_in=1489 segments_attached=1489 segments_unattached=0 cues_in=2918 cues_attached=2814 cues_unattached=104",
    ),
    _item(
        "BV1vNTqzFEve",
        "57cbebbf4a7e4a4070b59cf9b2facb780b0a91c1207894d54b0a155796e0874d",
        "c50b9f0877131c309eed4ec7b7c1db2ebd63d0be6305b191aa12f065f1cd7b39",
        "0ee4bd2bb25710b69638797ceea4ab8e2585faadf24b6b84c8c64146f5cfed7b",
        "BV1vNTqzFEve:p0: aligned blocks=260 segments_in=952 segments_attached=952 segments_unattached=0 cues_in=1709 cues_attached=1638 cues_unattached=71",
    ),
    _item(
        "BV1Y7M4zNEfF",
        "2de64eea7e3941f40ee6716fc3e14a89a5d48ab4b6faf0ab9d7167dd3bee2b75",
        "b4a941e9a43ec2e3ec9a1988c5e005b030fe162f4754123a716b3a6766a242e6",
        "e650a2c0f8316dcf4717b192e2e4a81f1f21cc0d344b070f2da58536ad6906d8",
        "BV1Y7M4zNEfF:p0: aligned blocks=110 segments_in=489 segments_attached=489 segments_unattached=0 cues_in=947 cues_attached=916 cues_unattached=31",
    ),
    _item(
        "BV1zz5zzFENq",
        "f6c5de5f628c1b9a228308bf9c2a0a6fbfe48e129a0ba14d00760cbfe8c8d97a",
        "a814d5084ebf092f83a3d4c06fd880a234d7427bb17c354a6a20a68227b38f5d",
        "0c3e89896e7619663865910d0c3a3b13ce68c3d89a9b89e8d25eed7a852dbfda",
        "BV1zz5zzFENq:p0: aligned blocks=50 segments_in=425 segments_attached=425 segments_unattached=0 cues_in=797 cues_attached=783 cues_unattached=14",
    ),
)

corpus_present = pytest.mark.skipif(
    not os.path.isdir(os.path.join(CORPUS_ROOT, "proofread-transcripts", "md")),
    reason="the /mnt/123pan measurement corpus is not mounted on this machine",
)


def corpus_path(item: CorpusItem, field: str) -> Path:
    """One item's file below the corpus root, addressed by field name."""
    return Path(CORPUS_ROOT) / getattr(item, field)


#: Which pin guards which field; the two route fields are named for their role.
PINS = {
    "markdown": lambda item: item.markdown_sha256,
    "asr_sidecar": lambda item: item.asr_sha256,
    "caption_sidecar": lambda item: item.caption_sha256,
}


def pinned_bytes(item: CorpusItem, field: str) -> bytes:
    """One pinned corpus file's bytes, or a refusal naming that file (D12).

    A missing file and a digest mismatch are the two answers this raises; both
    name the path, because "the corpus disagrees with the pin" is not an operator
    -actionable sentence without it.  The corpus is never repaired from here.
    """
    path = corpus_path(item, field)
    pin = PINS[field](item)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AssertionError(f"corpus file unreadable: {path} ({exc.strerror})") from exc
    measured = hashlib.sha256(data).hexdigest()
    if measured != pin:
        raise AssertionError(
            f"corpus digest mismatch: {path} (recorded {pin}, measured {measured})"
        )
    return data


def _corpus_route(document: dict) -> tuple[tuple[int, int, str], ...]:
    """A route from a corpus sidecar, in the store's unit (milliseconds).

    Both corpus sidecars record **seconds** — they are the writer's own output,
    while ``archive.db`` holds milliseconds — so this is the unit boundary the
    command crosses for the ASR route and this helper crosses for the caption
    route.  Reading a sidecar as milliseconds is the mistake that looks like a
    degenerate cue: ``364.509`` truncates into ``start_ms == end_ms``.
    """
    return tuple(
        (
            int(round(float(segment["start"]) * 1000)),
            int(round(float(segment["end"]) * 1000)),
            str(segment.get("text", "")),
        )
        for segment in document["segments"]
    )


def replay_item(item: CorpusItem, tmp_root: str) -> tuple[str, str]:
    """Replay one corpus item; return the printed line beside the recorded one.

    The corpus is a **route** source here, not a store (D12 with D13): the
    caption route is loaded into a synthetic store through the shipped repository
    API, and the ASR route is copied — as a file, byte for byte — to the bundle
    path the writer's own rule names, so the command reads the same two routes an
    operator's archive would hold.  The copy respects D12: the corpus is read,
    never modified, and nothing enters the repository.  The artifact root is a
    sibling of the archive root, so D16's write lands outside both.
    """
    root = os.path.join(tmp_root, item.bvid, "archive")
    artifacts = os.path.join(tmp_root, item.bvid, "artifacts")
    os.makedirs(root, exist_ok=True)
    os.makedirs(artifacts, exist_ok=True)

    caption = json.loads(pinned_bytes(item, "caption_sidecar"))
    cues = _corpus_route(caption)

    connection = open_database(root)
    try:
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            metadata.upsert_user(make_user_record())
            metadata.upsert_video(make_video_record(item.bvid, aid=None, title=item.bvid))
            metadata.upsert_part(make_part_record(item.bvid, page_index=0, cid=CID_P0))
        part_id = int(
            connection.execute(
                "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = 0",
                (item.bvid,),
            ).fetchone()["video_part_id"]
        )
        repository = TranscriptRepository(connection)
        run_id = f"corpus-{item.bvid}"
        repository.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=run_id,
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=1,
            )
        )
        repository.record_acquired_transcript(
            run_id=run_id,
            video_part_id=part_id,
            source_kind="subtitle-ai",
            language="zh-CN",
            segments=tuple(
                TranscriptSegmentRecord(start, end, text) for start, end, text in cues
            ),
            started_at=2,
            finished_at=3,
            created_at=4,
        )
    finally:
        connection.close()

    # The sidecar goes to the path the writer's own rule names for *this* item:
    # a name guessed from the crafted fixture would leave the part out of range.
    sidecar = _sidecar_path(root, 0, CID_P0, item.bvid)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(corpus_path(item, "asr_sidecar"), sidecar)

    work_id = f"{item.bvid}:p0"
    assert _align(root, artifacts) == 0, f"{work_id}: the corpus replay must exit 0"
    lines = _jsonl(root, artifacts, work_id)
    header = json.loads(lines[0])
    printed = (
        f"{work_id}: aligned blocks={header['blocks']} "
        f"segments_in={header['segments_in']} "
        f"segments_attached={header['segments_attached']} "
        f"segments_unattached={header['segments_unattached']} "
        f"cues_in={header['cues_in']} cues_attached={header['cues_attached']} "
        f"cues_unattached={header['cues_unattached']}"
    )
    return printed, item.recorded_line


@corpus_present
@pytest.mark.parametrize("item", CORPUS, ids=[entry.bvid for entry in CORPUS])
def test_the_corpus_frozen_six_carry_their_two_routes_and_their_sha256_pins(
    item: CorpusItem,
) -> None:
    """D12: the pins are the corpus's identity, and the two routes are present."""
    for field in ("markdown", "asr_sidecar", "caption_sidecar"):
        assert pinned_bytes(item, field)

    asr = json.loads(pinned_bytes(item, "asr_sidecar"))
    caption = json.loads(pinned_bytes(item, "caption_sidecar"))
    assert asr["source"] == "asr"
    assert caption["source"] == "subtitle-ai"
    # The two routes are the two places D13 names, and neither is empty: an item
    # whose routes were absent would make the replay case below vacuous.  Both
    # routes must also survive the seconds-to-milliseconds crossing the command
    # performs, which is where a degenerate interval would surface.
    for document in (asr, caption):
        route = _corpus_route(document)
        assert route
        assert all(end > start for start, end, _ in route)


@corpus_present
@pytest.mark.parametrize("item", CORPUS, ids=[entry.bvid for entry in CORPUS])
def test_the_corpus_replays_offline_and_reproduces_the_recorded_accounting_line(
    item: CorpusItem, tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterion 4's builder half: the six replay offline and match the record."""
    printed, recorded = replay_item(item, tmp_root)
    out = capsys.readouterr().out.splitlines()

    assert printed == recorded
    assert out[0] == recorded
    assert out[-1] == "align-transcripts: candidates=1 aligned=1 refused=0"
    assert len(out) == 2


def test_a_corpus_file_missing_or_digest_mismatched_is_refused_naming_that_file(
    tmp_root: str,
) -> None:
    """D12: the pin mechanism refuses by name — and this case needs no corpus.

    Both mutations are applied to an item's *path* and its *pin*, never to the
    corpus: nothing is written below ``CORPUS_ROOT``, so this case runs on a
    machine that has never seen the corpus (the only corpus case without
    ``corpus_present``).  The missing-file half needs no corpus at all; the
    digest half reads one real file when it is there.
    """
    absent = CORPUS[0]._replace(markdown="proofread-transcripts/md/NO-SUCH-ITEM.p0.md")
    with pytest.raises(AssertionError) as missing:
        pinned_bytes(absent, "markdown")
    assert "NO-SUCH-ITEM.p0.md" in str(missing.value)

    for item in CORPUS:
        path = corpus_path(item, "markdown")
        if not path.is_file():
            continue
        # Mutating the *pin* is what makes this non-vacuous: the file is
        # untouched, so a mismatch can only come from the pin check itself.
        with pytest.raises(AssertionError) as wrong:
            pinned_bytes(item._replace(markdown_sha256="0" * 64), "markdown")
        assert str(path) in str(wrong.value)
        assert "digest mismatch" in str(wrong.value)
        # ...and the recorded pin is the real digest, so the mutation is the
        # only difference between the two calls.
        assert pinned_bytes(item, "markdown")
        break
    else:
        # Corpus absent: the digest half cannot run, and it is not pretended to.
        assert not os.path.isdir(os.path.join(CORPUS_ROOT, "proofread-transcripts", "md"))


def test_the_stage_document_names_the_commands_routes_exits_artifact_and_disclosures() -> None:
    """Criterion 5: the written surface carries the disclosures, not just the help."""
    document = Path(__file__).resolve().parents[1] / "docs" / "editorial-stages.md"
    text = document.read_text(encoding="utf-8")

    for token in (
        "align-transcripts",
        "verify-proofread",
        "alignments/<work_id>.jsonl",
        "archive.db",
        "transcripts/raw/<stem>.json",
        "unknown --bvid",
    ):
        assert token in text, f"the stage document omits {token!r}"
    # The two disclosures criterion 5 names: neither route is ground truth, and
    # no audio was listened to by the commands.
    assert "ground truth" in text
    assert "no audio" in text.lower() or "audio was" in text.lower()
