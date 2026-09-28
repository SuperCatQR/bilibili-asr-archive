"""Offline subtitle end-to-end verification: CLI → service → repository → SQLite.

Every test drives the real user-facing command path — ``bili_asr.cli.main`` with
plain argv — over the shared ``FakeGateway`` protocol double from
``tests/fixtures/``, installed in place of the concrete adapter at the gateway
seam.  The whole subtitle stack therefore runs offline exactly as an operator
runs it: argparse, the read-command database guard, the transcript-schema guard,
``TranscriptRepository``, ``SubtitleIngestor``, the acquisition run/attempt
records and the printed lines — with only the gateway boundary scripted.  (The
adapter itself and the package seam below it are covered by the gateway plan's
suite and the opt-in live smoke; this file is the deterministic evidence above
that boundary.)

What is pinned here:

- one bounded harvest lands normalized ``transcripts``/``transcript_segments``
  rows — language, ``source_kind``, version 1, the contract's content hash — with
  their ``acquisition_runs``/``acquisition_attempts`` evidence;
- re-acquiring the same part is content-idempotent: ``unchanged``, no new
  version, no duplicated segments; a revised body appends version 2 while
  version 1 stays readable through the repository;
- a part with nothing visible and a part whose body fetch fails keep bounded
  evidence rows, the run does not claim success for either of them, and the
  partial failure stays visible in the printed counts with exit code 0;
- the pending enumeration advances: a part left ``no-subtitle`` stores a
  transcript in a later run, and a never-attempted part is attempted before a
  previously attempted one;
- every run summary prints all four outcome counts including zeros, the
  persisted run id, credential presence and how many parts still lack a
  transcript; a selection that resolved to nothing (``attempted=0``) exits 0;
- ``probe-subs`` prints the locked ``probe``/``track``/``tracks=0`` lines and
  writes nothing at all — no database, no run row, no file;
- neither command leaves a legacy sidecar or a transcript projection in the
  archive root, and no credential or raw upstream text reaches output or any
  persisted row.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3

import pytest

from bili_asr.cli import main
from bili_asr.config import ARCHIVE_DATABASE_NAME
from bili_asr.sources.models import (
    GatewayRateLimited,
    GatewayResponseError,
    GatewayTransportError,
    SubtitleSegment,
    SubtitleTrack,
)
from bili_asr.storage import MetadataRepository, TranscriptRepository, open_database
from bili_asr.storage.models import (
    ALLOWED_ACQUISITION_KINDS,
    ALLOWED_CAPTION_SOURCE_KINDS,
)
from fixtures.fake_bilibili_gateway import (
    SESSDATA_BOUNDARY_VALUE,
    UPSTREAM_ERROR_TEXT,
    FakeGateway,
    assert_leaks_no_markers,
    fake_gateway_seam,
    persisted_row_text,
)
from fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)

#: The one video the scripted parts belong to; each part is addressed by its own
#: ``cid`` in the gateway script and by ``bvid:pN`` in the CLI vocabulary.
BVID = "BV1SubE2e"
CC_CID = 101
AI_CID = 102
CAPTIONLESS_CID = 201
FAILING_CID = 202

#: The realistic caption inventory: the uploader track and the machine one for
#: the same spoken language, so the default preference has a real choice to make.
CC_ZH = SubtitleTrack(
    language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
)
AI_ZH = SubtitleTrack(
    language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
)

#: One uploader body, one machine body, and a revised uploader body of the same
#: part/source/language identity.
CC_BODY = (
    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="第二句"),
)
AI_BODY = (SubtitleSegment(start_ms=0, end_ms=1_500, text="自动生成的一句"),)
REVISED_CC_BODY = (
    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="改写后的第二句"),
)

#: The legacy sidecars and the transcript projections the subtitle path owns.
LEGACY_SIDE_CAR_PATHS = (
    "manifest/manifest.jsonl",
    "meta-cursor.json",
    "run-ledger.jsonl",
    "coordinator/attempts.jsonl",
)
#: Path prefixes a harvest must NOT leave behind.  Shape A moved the srt into
#: transcripts/{stem}/, so the old "transcripts/srt/" prefix would match nothing
#: and the assertion would pass vacuously.
PROJECTION_PREFIXES = ("subtitles/raw/", "transcripts/")
#: ``harvest-subs`` is an archive-writer command, so the shipped writer lock is
#: the one file besides the database a harvest is expected to leave behind.
ARCHIVE_WRITER_LOCK_PATH = "coordinator/archive-writer.lock"


@pytest.fixture(autouse=True)
def _anonymous_environment(monkeypatch: pytest.MonkeyPatch):
    """No credential in the environment unless a test sets one explicitly."""

    monkeypatch.delenv("BILI_SESSDATA", raising=False)


def _seed_parts(root: str, parts: tuple[tuple[str, int, int], ...]) -> None:
    """Create ``archive.db`` with one user, one video per bvid, and these parts.

    ``parts`` is ``(bvid, page_index, cid)`` triples, so a test scripts its
    gateway answers by the part it means.
    """

    connection = open_database(root)
    repository = MetadataRepository(connection)
    try:
        with repository.transaction():
            repository.upsert_user(make_user_record())
            for bvid in dict.fromkeys(bvid for bvid, _page, _cid in parts):
                repository.upsert_video(
                    make_video_record(bvid, aid=None, title="字幕测试视频")
                )
            for bvid, page_index, cid in parts:
                repository.upsert_part(
                    make_part_record(
                        bvid,
                        page_index=page_index,
                        cid=cid,
                        processing_status="metadata_collected",
                    )
                )
    finally:
        connection.close()


@contextmanager
def _archive_connection(root: str):
    """Read the archive database directly, without creating or migrating it."""

    connection = sqlite3.connect(os.path.join(root, ARCHIVE_DATABASE_NAME))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _archive_files(root: str) -> list[str]:
    """Every file below the archive root, as sorted relative POSIX paths."""

    return sorted(
        os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
        for directory, _directories, names in os.walk(root)
        for name in names
    )


def _expected_content_sha256(body: tuple[SubtitleSegment, ...]) -> str:
    """Compute the contract's content hash independently of the repository.

    The storage contract digests the canonical segment JSON: the segment triples
    in stored order, unescaped non-ASCII, no separator padding.  Recomputing it
    here from the DTO restates the contract instead of reading its result back
    out of the implementation.
    """

    canonical = json.dumps(
        [[segment.start_ms, segment.end_ms, segment.text] for segment in body],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _part_ids(connection: sqlite3.Connection) -> dict[int, int]:
    """Return every seeded part's ``video_part_id``, keyed by its ``cid``."""

    return {
        int(row["cid"]): int(row["video_part_id"])
        for row in connection.execute("SELECT video_part_id, cid FROM video_parts")
    }


def _stored_versions(connection: sqlite3.Connection) -> list[tuple]:
    """Return every transcript version with the identity it belongs to."""

    return [
        (
            row["video_part_id"],
            row["source_kind"],
            row["language"],
            row["model_id"],
            row["version"],
            row["content_sha256"],
        )
        for row in connection.execute(
            "SELECT video_part_id, source_kind, language, model_id, version,"
            " content_sha256 FROM transcripts ORDER BY video_part_id, version"
        )
    ]


def _stored_segments(connection: sqlite3.Connection) -> list[tuple]:
    """Return every stored segment row in version and ordinal order."""

    return [
        (
            row["video_part_id"],
            row["version"],
            row["ordinal"],
            row["start_ms"],
            row["end_ms"],
            row["text"],
        )
        for row in connection.execute(
            "SELECT t.video_part_id, t.version, s.ordinal, s.start_ms, s.end_ms,"
            " s.text FROM transcript_segments AS s"
            " JOIN transcripts AS t ON t.transcript_id = s.transcript_id"
            " ORDER BY t.video_part_id, t.version, s.ordinal"
        )
    ]


def _attempt_rows(connection: sqlite3.Connection) -> list[tuple]:
    """Return every attempt row in the order it was written."""

    return [
        (
            row["video_part_id"],
            row["outcome"],
            row["error_code"],
            row["transcript_id"],
            row["started_at"],
            row["finished_at"],
            row["run_id"],
        )
        for row in connection.execute(
            "SELECT * FROM acquisition_attempts ORDER BY rowid"
        )
    ]


def _run_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return every acquisition run in the order it was opened."""

    return list(
        connection.execute(
            "SELECT * FROM acquisition_runs ORDER BY started_at, rowid"
        )
    )


# ------------------------------------------------------ stored evidence

def test_harvest_stores_normalized_rows_for_a_cc_and_an_ai_part(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """One bounded run lands both parts' versions, segments and run evidence.

    The ``p0`` part exposes both a machine and an uploader track, so the default
    preference has a real selection to make and keeps the uploader one; the
    ``p1`` part exposes the machine track only.  Both ``source_kind`` values are
    therefore exercised by real selections rather than by a scripted shortcut.
    """

    _seed_parts(tmp_root, ((BVID, 0, CC_CID), (BVID, 1, AI_CID)))
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (AI_ZH, CC_ZH))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
    fake_gateway_seam.script_subtitle_tracks(AI_CID, (AI_ZH,))
    fake_gateway_seam.script_subtitle_segments(AI_CID, AI_BODY)

    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0

    out, err = capsys.readouterr()
    assert err == ""
    # Selection order is the pending enumeration's: page index ascending here.
    assert fake_gateway_seam.listing_cids == [CC_CID, AI_CID]
    assert fake_gateway_seam.body_cids == [CC_CID, AI_CID]

    with _archive_connection(tmp_root) as connection:
        part_ids = _part_ids(connection)
        runs = _run_rows(connection)
        assert len(runs) == 1
        run = runs[0]
        assert (
            run["kind"],
            run["kind"] in ALLOWED_ACQUISITION_KINDS,
            run["selector_kind"],
            run["selector_target"],
            run["requested_limit"],
            run["credential_present"],
            run["outcome"],
        ) == ("subtitle", True, "pending", None, 2, 0, "complete")
        assert run["finished_at"] is not None

        # The summary names the persisted run and every count, zeros included.
        assert out.splitlines() == [
            "sessdata: absent",
            f"harvest {BVID}:p0 stored subtitle-cc zh-CN v1",
            f"harvest {BVID}:p1 stored subtitle-ai ai-zh v1",
            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=2"
            " unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0",
        ]

        assert _stored_versions(connection) == [
            (
                part_ids[CC_CID],
                "subtitle-cc",
                "zh-CN",
                None,
                1,
                _expected_content_sha256(CC_BODY),
            ),
            (
                part_ids[AI_CID],
                "subtitle-ai",
                "ai-zh",
                None,
                1,
                _expected_content_sha256(AI_BODY),
            ),
        ]
        assert _stored_segments(connection) == [
            (part_ids[CC_CID], 1, 0, 0, 1_200, "第一句"),
            (part_ids[CC_CID], 1, 1, 1_200, 2_400, "第二句"),
            (part_ids[AI_CID], 1, 0, 0, 1_500, "自动生成的一句"),
        ]
        assert {
            row[1] for row in _stored_versions(connection)
        } <= ALLOWED_CAPTION_SOURCE_KINDS

        transcripts = {
            (int(row["video_part_id"]), int(row["version"])): int(row["transcript_id"])
            for row in connection.execute(
                "SELECT transcript_id, video_part_id, version FROM transcripts"
            )
        }
        attempts = _attempt_rows(connection)
        assert [(attempt[0], attempt[1], attempt[2]) for attempt in attempts] == [
            (part_ids[CC_CID], "stored", None),
            (part_ids[AI_CID], "stored", None),
        ]
        assert [attempt[3] for attempt in attempts] == [
            transcripts[(part_ids[CC_CID], 1)],
            transcripts[(part_ids[AI_CID], 1)],
        ]
        for attempt in attempts:
            # Each attempt is timestamped evidence inside its own run's lifetime
            # (the stored clock is second-granular, so equal bounds are allowed).
            assert attempt[6] == run["run_id"]
            assert run["started_at"] <= attempt[4] <= attempt[5] <= run["finished_at"]
        assert_leaks_no_markers(
            persisted_row_text(connection), context="persisted transcript rows"
        )


def test_reacquiring_an_unchanged_caption_adds_no_version_and_no_segment(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """The operator's re-check path reports ``unchanged`` and rewrites nothing."""

    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    # Re-checking the part upstream has not revised: explicit --bvid selection,
    # which keeps parts that already hold a transcript (spec section 2.2).
    assert (
        main(
            ["harvest-subs", "--bvid", BVID, "--limit-parts", "5",
             "--archive-root", tmp_root]
        )
        == 0
    )

    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[1] == (
        f"harvest {BVID}:p0 unchanged subtitle-cc zh-CN v1"
    )
    assert "attempted=1 stored=0 unchanged=1 no-subtitle=0 failed=0" in out
    assert out.splitlines()[2].endswith("remaining_without_transcript=0")

    with _archive_connection(tmp_root) as connection:
        part_ids = _part_ids(connection)
        versions = [
            row["version"]
            for row in connection.execute("SELECT version FROM transcripts")
        ]
        assert versions == [1]
        assert _stored_versions(connection) == [
            (
                part_ids[CC_CID],
                "subtitle-cc",
                "zh-CN",
                None,
                1,
                _expected_content_sha256(CC_BODY),
            )
        ]
        assert _stored_segments(connection) == [
            (part_ids[CC_CID], 1, 0, 0, 1_200, "第一句"),
            (part_ids[CC_CID], 1, 1, 1_200, 2_400, "第二句"),
        ]
        # Both attempts point at the same single version: nothing was duplicated.
        attempts = _attempt_rows(connection)
        assert [(attempt[1], attempt[2]) for attempt in attempts] == [
            ("stored", None),
            ("unchanged", None),
        ]
        assert len({attempt[3] for attempt in attempts}) == 1
        assert [row["outcome"] for row in _run_rows(connection)] == [
            "complete",
            "complete",
        ]


def test_a_revised_caption_appends_version_two_and_keeps_version_one_readable(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """A changed body is a new immutable version; the earlier one stays readable."""

    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    fake_gateway_seam.script_subtitle_segments(CC_CID, REVISED_CC_BODY)
    assert (
        main(
            ["harvest-subs", "--bvid", f"{BVID}:p0", "--archive-root", tmp_root]
        )
        == 0
    )

    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[1] == f"harvest {BVID}:p0 stored subtitle-cc zh-CN v2"

    with _archive_connection(tmp_root) as connection:
        part_ids = _part_ids(connection)
        versions = _stored_versions(connection)
        assert [row[4] for row in versions] == [1, 2]
        assert [row[5] for row in versions] == [
            _expected_content_sha256(CC_BODY),
            _expected_content_sha256(REVISED_CC_BODY),
        ]
        assert _stored_segments(connection) == [
            (part_ids[CC_CID], 1, 0, 0, 1_200, "第一句"),
            (part_ids[CC_CID], 1, 1, 1_200, 2_400, "第二句"),
            (part_ids[CC_CID], 2, 0, 0, 1_200, "第一句"),
            (part_ids[CC_CID], 2, 1, 1_200, 2_400, "改写后的第二句"),
        ]

    # Version 1 is still readable through the repository's own read path, where
    # the "earlier versions stay readable" promise is made.
    connection = open_database(tmp_root)
    try:
        repository = TranscriptRepository(connection)
        part_id = _part_ids(connection)[CC_CID]
        first = repository.read_transcript(part_id, "subtitle-cc", "zh-CN", 1)
        latest = repository.read_transcript(part_id, "subtitle-cc", "zh-CN")
    finally:
        connection.close()
    assert first is not None and latest is not None
    assert (first.version, latest.version) == (1, 2)
    assert first.content_sha256 == _expected_content_sha256(CC_BODY)
    assert [
        (segment.start_ms, segment.end_ms, segment.text) for segment in first.segments
    ] == [
        (0, 1_200, "第一句"),
        (1_200, 2_400, "第二句"),
    ]


# ------------------------------------------- bounded evidence and progress

def test_captionless_and_failing_parts_keep_bounded_evidence_and_exit_zero(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """Neither part claims success, and the partial failure stays in the counts."""

    _seed_parts(tmp_root, ((BVID, 0, CAPTIONLESS_CID), (BVID, 1, FAILING_CID)))
    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, ())
    fake_gateway_seam.script_subtitle_tracks(FAILING_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(
        FAILING_CID, GatewayRateLimited()
    )

    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0

    out, err = capsys.readouterr()
    assert err == ""
    # A part whose listing is empty never reaches the body fetch at all.
    assert fake_gateway_seam.listing_cids == [CAPTIONLESS_CID, FAILING_CID]
    assert fake_gateway_seam.body_cids == [FAILING_CID]

    with _archive_connection(tmp_root) as connection:
        run = _run_rows(connection)[0]
        assert out.splitlines() == [
            "sessdata: absent",
            f"harvest {BVID}:p0 no-subtitle",
            f"harvest {BVID}:p1 failed rate_limited",
            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=0"
            " unchanged=0 no-subtitle=1 failed=1 remaining_without_transcript=2",
        ]
        assert run["outcome"] == "partial"

        part_ids = _part_ids(connection)
        attempts = _attempt_rows(connection)
        assert [
            (attempt[0], attempt[1], attempt[2], attempt[3])
            for attempt in attempts
        ] == [
            (part_ids[CAPTIONLESS_CID], "no-subtitle", None, None),
            (part_ids[FAILING_CID], "failed", "rate_limited", None),
        ]
        for attempt in attempts:
            assert attempt[6] == run["run_id"]
            assert run["started_at"] <= attempt[4] <= attempt[5] <= run["finished_at"]
        assert _stored_versions(connection) == []
        assert _stored_segments(connection) == []


def test_a_captionless_part_stores_one_later_and_never_attempted_parts_go_first(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """``no-subtitle`` is an observation, and a bounded run cannot stall on it."""

    _seed_parts(tmp_root, ((BVID, 0, CAPTIONLESS_CID), (BVID, 1, CC_CID)))
    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, ())
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)

    # First bounded run: both parts are never attempted, page index decides.
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    first = capsys.readouterr()
    assert first.out.splitlines()[1] == f"harvest {BVID}:p0 no-subtitle"
    assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in first.out
    assert first.out.splitlines()[2].endswith("remaining_without_transcript=2")

    # Second run: the never-attempted part goes before the attempted one.
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    second = capsys.readouterr()
    assert second.out.splitlines()[1] == (
        f"harvest {BVID}:p1 stored subtitle-cc zh-CN v1"
    )
    assert second.out.splitlines()[2].endswith("remaining_without_transcript=1")
    assert fake_gateway_seam.listing_cids == [CAPTIONLESS_CID, CC_CID]

    # The caption becomes visible upstream; the captionless part is still work.
    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CAPTIONLESS_CID, CC_BODY)
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    third = capsys.readouterr()
    assert third.out.splitlines()[1] == (
        f"harvest {BVID}:p0 stored subtitle-cc zh-CN v1"
    )
    assert third.out.splitlines()[2].endswith("remaining_without_transcript=0")
    assert fake_gateway_seam.listing_cids == [
        CAPTIONLESS_CID,
        CC_CID,
        CAPTIONLESS_CID,
    ]

    with _archive_connection(tmp_root) as connection:
        part_ids = _part_ids(connection)
        assert [
            (row[0], row[1], row[3] is not None)
            for row in _attempt_rows(connection)
        ] == [
            (part_ids[CAPTIONLESS_CID], "no-subtitle", False),
            (part_ids[CC_CID], "stored", True),
            (part_ids[CAPTIONLESS_CID], "stored", True),
        ]


def test_the_summary_prints_every_count_and_an_empty_selection_exits_zero(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """All four counts appear, zeros included, and ``attempted=0`` is a success."""

    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    first = capsys.readouterr()

    # Nothing is pending any more: the bounded run is empty, not a stall.
    assert main(["harvest-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
    second = capsys.readouterr()

    with _archive_connection(tmp_root) as connection:
        runs = _run_rows(connection)
        assert len(runs) == 2
        assert first.out.splitlines() == [
            "sessdata: absent",
            f"harvest {BVID}:p0 stored subtitle-cc zh-CN v1",
            f"harvest-subs: run_id={runs[0]['run_id']} attempted=1 stored=1"
            " unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0",
        ]
        assert second.out.splitlines() == [
            "sessdata: absent",
            f"harvest-subs: run_id={runs[1]['run_id']} attempted=0 stored=0"
            " unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0",
        ]
        assert runs[0]["run_id"] != runs[1]["run_id"]
        assert [run["outcome"] for run in runs] == ["complete", "complete"]
        assert [run["credential_present"] for run in runs] == [0, 0]


# ------------------------------------------------------------ probe surface

def test_probe_subs_prints_the_locked_lines_and_leaves_nothing_behind(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """The probe reports tracks only and writes nothing — not even the database."""

    # No database yet: the shipped read-command line, and no file is created.
    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err == (
        f"probe-subs: no archive database at {tmp_root}; "
        "run fetch-meta to create it\n"
    )
    assert _archive_files(tmp_root) == []

    _seed_parts(
        tmp_root,
        ((BVID, 0, CC_CID), (BVID, 1, CAPTIONLESS_CID), (BVID, 2, FAILING_CID)),
    )
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH, AI_ZH))
    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, ())
    fake_gateway_seam.script_subtitle_tracks(FAILING_CID, GatewayResponseError())

    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0

    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines() == [
        "sessdata: absent",
        f"probe {BVID}:p0 tracks=2",
        "  track zh-CN cc 中文（简体）",
        "  track ai-zh ai 中文（自动生成）",
        f"probe {BVID}:p1 tracks=0",
        "  (no subtitles visible)",
        f"probe {BVID}:p2 failed response_error",
        "probe-subs: probed=3 with_tracks=1 without_tracks=1 failed=1",
    ]
    # A probe lists tracks only, and writes no file at all: no writer lock, no
    # database creation, no run, attempt, transcript or segment row.
    assert fake_gateway_seam.body_cids == []
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
    with _archive_connection(tmp_root) as connection:
        for table in (
            "acquisition_runs",
            "acquisition_attempts",
            "transcripts",
            "transcript_segments",
        ):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, f"{table} must stay empty"


# --------------------------------------------------------- path boundaries

def test_neither_command_leaves_a_sidecar_or_a_transcript_projection(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
) -> None:
    """Only ``archive.db`` and the writer lock appear under the archive root."""

    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)

    assert main(["probe-subs", "--bvid", BVID, "--archive-root", tmp_root]) == 0
    capsys.readouterr()
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME], (
        "a probe takes no writer lock and creates no file"
    )

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    capsys.readouterr()
    files = _archive_files(tmp_root)
    assert files == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH])
    for sidecar in LEGACY_SIDE_CAR_PATHS:
        assert sidecar not in files
    for path in files:
        assert not path.startswith(PROJECTION_PREFIXES)


def test_no_credential_or_upstream_text_reaches_output_or_a_persisted_row(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway, monkeypatch
) -> None:
    """The credential stays presence-only and a body failure stays a code."""

    monkeypatch.setenv("BILI_SESSDATA", SESSDATA_BOUNDARY_VALUE)
    _seed_parts(tmp_root, ((BVID, 0, CC_CID), (BVID, 1, FAILING_CID)))
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
    fake_gateway_seam.script_subtitle_tracks(FAILING_CID, (CC_ZH,))
    # The failure's detail carries every seam sentinel, so the scan below is not
    # vacuous: this text really was in flight inside the run.
    fake_gateway_seam.script_subtitle_segments(
        FAILING_CID, GatewayTransportError(detail=UPSTREAM_ERROR_TEXT)
    )

    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0

    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[0] == "sessdata: present"
    assert out.splitlines()[2] == f"harvest {BVID}:p1 failed transport_error"
    assert SESSDATA_BOUNDARY_VALUE not in out + err
    assert UPSTREAM_ERROR_TEXT not in out + err
    assert_leaks_no_markers(out + err, context="harvest output")

    with _archive_connection(tmp_root) as connection:
        persisted = persisted_row_text(connection)
        # Positive control: the run really stored a normalized row, so the scan
        # over the persisted text is not vacuous.
        assert "subtitle-cc" in persisted and "第一句" in persisted
        assert connection.execute(
            "SELECT error_code FROM acquisition_attempts WHERE outcome = 'failed'"
        ).fetchone()[0] == "transport_error"
        assert_leaks_no_markers(persisted, context="persisted rows")


# ------------------------------------------------- credential presence (env)

def test_the_env_sourced_credential_is_reported_as_presence_and_composed_into_the_run_row(
    tmp_root: str, capsys, fake_gateway_seam: FakeGateway, monkeypatch
) -> None:
    """``BILI_SESSDATA`` reaches the adapter and is recorded presence-only."""

    _seed_parts(tmp_root, ((BVID, 0, CC_CID), (BVID, 1, AI_CID)))
    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
    fake_gateway_seam.script_subtitle_tracks(AI_CID, (AI_ZH,))
    fake_gateway_seam.script_subtitle_segments(AI_CID, AI_BODY)

    monkeypatch.setenv("BILI_SESSDATA", SESSDATA_BOUNDARY_VALUE)
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[0] == "sessdata: present"
    assert SESSDATA_BOUNDARY_VALUE not in out + err
    # The environment value, not a --sessdata flag, is what reached the adapter.
    assert fake_gateway_seam.sessdata == SESSDATA_BOUNDARY_VALUE

    monkeypatch.delenv("BILI_SESSDATA")
    assert (
        main(
            ["harvest-subs", "--bvid", f"{BVID}:p1", "--archive-root", tmp_root]
        )
        == 0
    )
    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[0] == "sessdata: absent"
    assert fake_gateway_seam.sessdata is None

    with _archive_connection(tmp_root) as connection:
        assert [
            (row["credential_present"], row["selector_kind"], row["selector_target"])
            for row in _run_rows(connection)
        ] == [(1, "pending", None), (0, "bvid", f"{BVID}:p1")]
        persisted = persisted_row_text(connection)
        # Positive control: the credential-bearing runs really stored rows, so
        # the scan over the persisted text is not vacuous.
        assert "subtitle-cc" in persisted
        assert_leaks_no_markers(
            persisted, context="credential-bearing run rows"
        )

    # The read command reports the same presence and still writes nothing.
    monkeypatch.setenv("BILI_SESSDATA", SESSDATA_BOUNDARY_VALUE)
    assert main(["probe-subs", "--bvid", BVID, "--archive-root", tmp_root]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[0] == "sessdata: present"
    assert SESSDATA_BOUNDARY_VALUE not in out + err
    with _archive_connection(tmp_root) as connection:
        assert len(_run_rows(connection)) == 2, "a probe opens no run"
    assert _archive_files(tmp_root) == sorted(
        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
    )
