"""Offline contract tests for the subtitle CLI (``probe-subs`` / ``harvest-subs``).

Everything here is offline.  Both commands are driven end to end through
``bili_asr.cli.main`` — argparse, the read-command database guard, the
transcript-schema guard, ``TranscriptRepository``, the service, and the printed
lines — against a temporary archive database and a scripted gateway double
installed in place of the concrete adapter, so no network call and no package
call is made.

What is pinned: the locked ``probe`` / ``harvest`` / summary line shapes and the
exit taxonomy (0 ran / 1 usage or configuration / 2 terminal), the selection
preference (CC before AI inside a language family, exact ``--language`` match),
the outcome mapping, the enumeration advancing across bounded runs, and the
boundaries — neither command reads or writes a legacy sidecar or a transcript
projection, ``probe-subs`` writes nothing at all and never creates the database,
and no display path or stored row carries the credential.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
import sqlite3
from pathlib import Path

import pytest

from bili_asr.cli import main
from bili_asr.config import ARCHIVE_DATABASE_NAME
from bili_asr.services.subtitle_ingest import (
    language_family,
    select_subtitle_track,
)
from bili_asr.sources.models import (
    GatewayNotFound,
    GatewayRateLimited,
    GatewayResponseError,
    GatewayShapeError,
    GatewayTransportError,
    SubtitleSegment,
    SubtitleTrack,
)
from bili_asr.storage import MetadataRepository, open_database
from bili_asr.storage.models import (
    ALLOWED_ACQUISITION_KINDS,
    ALLOWED_CAPTION_SOURCE_KINDS,
    MAX_TIMELINE_MS,
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
from test_storage_schema import _write_pre_iteration_database

BVID_A = "BV1SubA"
BVID_B = "BV1SubB"

#: One caption body of two segments, and a revised body of the same identity.
BODY = (
    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="第二句"),
)
CHANGED_BODY = (
    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="改写后的第二句"),
)

#: The realistic caption inventory: the uploader track and the machine one for
#: the same spoken language, plus one English uploader track.
CC_ZH = SubtitleTrack(
    language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
)
AI_ZH = SubtitleTrack(
    language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
)
CC_EN = SubtitleTrack(
    language="en-US", label="English", is_ai=False, track_id=None
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
#: ``harvest-subs`` is an archive-writer command, so the shipped lock is the one
#: file besides the database it is expected to leave behind.
ARCHIVE_WRITER_LOCK_PATH = "coordinator/archive-writer.lock"


@pytest.fixture(autouse=True)
def _anonymous_environment(monkeypatch: pytest.MonkeyPatch):
    """No credential in the environment unless a test sets one explicitly."""

    monkeypatch.delenv("BILI_SESSDATA", raising=False)


@pytest.fixture
def install_gateway(fake_gateway_seam: FakeGateway):
    """Install one scripted gateway as the CLI's concrete adapter.

    A part is addressed by its ``cid``: ``tracks`` scripts one inventory,
    ``segments`` one body, and the two failure maps raise instead of answering,
    all of them through the shared ``FakeGateway`` protocol double.  A call the
    test did not script fails loudly rather than silently answering an empty
    inventory, and every call is recorded on the double — ``listing_cids`` and
    ``body_cids`` in issue order — so the enumeration order and "the body was
    never fetched" are assertable.

    The shared ``fake_gateway_seam`` fixture installs the double at the adapter
    seam and records the credential the composition root handed it, which the
    credential test pins.
    """

    def install(
        *,
        tracks: dict[int, tuple[SubtitleTrack, ...]] | None = None,
        segments: dict[int, tuple[SubtitleSegment, ...]] | None = None,
        listing_failures: dict[int, Exception] | None = None,
        body_failures: dict[int, Exception] | None = None,
    ) -> FakeGateway:
        for cid, inventory in (tracks or {}).items():
            fake_gateway_seam.script_subtitle_tracks(cid, inventory)
        for cid, body in (segments or {}).items():
            fake_gateway_seam.script_subtitle_segments(cid, body)
        for cid, failure in (listing_failures or {}).items():
            fake_gateway_seam.script_subtitle_tracks(cid, failure)
        for cid, failure in (body_failures or {}).items():
            fake_gateway_seam.script_subtitle_segments(cid, failure)
        return fake_gateway_seam

    return install


def _seed_parts(root: str, parts: tuple[tuple[str, int, int], ...]) -> None:
    """Create ``archive.db`` with one user, one video per bvid, and these parts.

    ``parts`` is ``(bvid, page_index, cid)`` triples, so a test scripts its
    answers by the part it means.
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


def _scalar(root: str, sql: str, parameters: tuple = ()):
    """Read one scalar straight from the archive database."""

    with _archive_connection(root) as connection:
        return connection.execute(sql, parameters).fetchone()[0]


def _exit_code(argv: list[str]) -> int:
    """Return the command's exit code, argparse usage errors included.

    ``_UsageErrorArgumentParser`` maps argparse's ``2`` onto ``1`` (and keeps
    ``--help`` at ``0``) but still raises ``SystemExit`` for a malformed value,
    which is the same process exit code an operator sees.
    """

    try:
        return main(argv)
    except SystemExit as exit_signal:
        return int(exit_signal.code)


# ------------------------------------------------------------------ usage

@pytest.mark.parametrize(
    "argv",
    [
        ["probe-subs"],
        ["probe-subs", "--bvid", BVID_A, "--limit-parts", "1"],
        ["probe-subs", "--limit-parts", "0"],
        ["probe-subs", "--limit-parts", "-2"],
        ["probe-subs", "--limit-parts", "not-a-number"],
        # A selector the archive cannot store names no part in any database, so it
        # is the documented configuration error (exit 1) exactly like an unknown
        # bvid — never the unexpected-internal-error exit 2 (F-001).
        ["probe-subs", "--bvid", ""],
        ["probe-subs", "--bvid", "   "],
        ["probe-subs", "--bvid", f"{BVID_A}\x00"],
        ["harvest-subs"],
        ["harvest-subs", "--bvid", BVID_A],
        ["harvest-subs", "--bvid", "  ", "--limit-parts", "2"],
        ["harvest-subs", "--bvid", f"{BVID_A}\np0", "--limit-parts", "2"],
        ["harvest-subs", "--limit-parts", "0"],
        ["harvest-subs", "--limit-parts", "2", "--language", "ai-zh,"],
        ["harvest-subs", "--limit-parts", "2", "--language", ""],
    ],
)
def test_subtitle_usage_errors_exit_one_never_two(
    tmp_root: str, capsys, argv: list[str]
) -> None:
    """Every usage/configuration error is exit 1 with nothing on stdout."""

    assert _exit_code([*argv, "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip()


@pytest.mark.parametrize(
    "value",
    ["", " ", "   ", "\t", f"{BVID_A}\x00", f"{BVID_A}\n", f"  {BVID_A}\x00  "],
)
def test_an_unstorable_bvid_is_answered_as_unknown_bvid(
    tmp_root: str, capsys, install_gateway, value: str
) -> None:
    """A blank/control-character selector is ``unknown --bvid <value>``, exit 1.

    The archive stores ``bvid`` values through the storage contract's identifier
    rule, which rejects a value that is empty once stripped and one carrying a
    control character, so no database can hold the part such a selector names.
    Both commands therefore answer it with the documented configuration error —
    byte for byte, on stderr, with nothing on stdout — instead of reaching the
    repository, whose own validation would surface as an unexpected internal
    error with exit 2 (F-001).
    """

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})

    for command, argv in (
        ("probe-subs", ["probe-subs", "--bvid", value, "--archive-root", tmp_root]),
        (
            "harvest-subs",
            [
                "harvest-subs",
                "--bvid",
                value,
                "--limit-parts",
                "2",
                "--archive-root",
                tmp_root,
            ],
        ),
    ):
        assert _exit_code(argv) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == f"{command}: unknown --bvid {value}\n"
        if command == "probe-subs":
            assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME], (
                "the read-only probe leaves no file at all"
            )

    # Configuration, decided before any call and before any run row.  The writer
    # lock of the failing harvest is the one file this exits-1 path adds: it is
    # taken by main() before the handler runs, which the docs state.
    assert gateway.listing_cids == []
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0
    assert _archive_files(tmp_root) == sorted(
        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
    )


def test_an_unstorable_bvid_outranks_the_missing_database_guard(
    tmp_root: str, capsys
) -> None:
    """The selector check is decided on the argument, before the database guard.

    ``--bvid ""`` names no part in any database, so the operator is told that —
    even on a root that holds no ``archive.db`` yet — instead of being sent to
    ``fetch-meta`` for a selector ``fetch-meta`` could never satisfy either.
    A padded-but-addressable value is deliberately *not* rejected: it reaches the
    database and is answered as an unknown bvid there, because the storage rule
    can hold it.
    """

    root = os.path.join(tmp_root, "absent")
    assert main(["probe-subs", "--bvid", "", "--archive-root", root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "probe-subs: unknown --bvid \n"
    assert not os.path.exists(root), "still nothing created on a read command"

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    padded = f" {BVID_A} "
    assert main(["probe-subs", "--bvid", padded, "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"probe-subs: unknown --bvid {padded}\n"


def test_probe_subs_requires_exactly_one_selector(tmp_root: str, capsys) -> None:
    """Neither selector, and both selectors, are the same usage error."""

    assert main(["probe-subs", "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "exactly one of --bvid / --limit-parts" in captured.err

    assert (
        main(
            [
                "probe-subs",
                "--bvid",
                BVID_A,
                "--limit-parts",
                "1",
                "--archive-root",
                tmp_root,
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "exactly one of --bvid / --limit-parts" in captured.err


def test_missing_database_on_both_commands_prints_the_shipped_line(
    tmp_root: str, capsys
) -> None:
    """A missing database is the shipped read-command line, and nothing appears."""

    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"probe-subs: no archive database at {tmp_root}; "
        "run fetch-meta to create it\n"
    )
    # Read-only for real: no database, no writer lock, no file at all.
    assert _archive_files(tmp_root) == []

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"harvest-subs: no archive database at {tmp_root}; "
        "run fetch-meta to create it\n"
    )
    assert not os.path.exists(os.path.join(tmp_root, ARCHIVE_DATABASE_NAME))


def test_probe_subs_creates_nothing_when_the_archive_root_is_absent(
    tmp_root: str, capsys
) -> None:
    """A missing root is not created by a read command."""

    root = os.path.join(tmp_root, "absent")
    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no archive database" in captured.err
    assert not os.path.exists(root)


def test_unknown_bvid_is_configuration_and_opens_no_run(
    tmp_root: str, capsys, install_gateway
) -> None:
    """A selector naming no stored part exits 1 before any upstream call."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: (CC_ZH,)})

    assert (
        main(
            [
                "harvest-subs",
                "--bvid",
                "BV1Unknown",
                "--limit-parts",
                "5",
                "--archive-root",
                tmp_root,
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown --bvid BV1Unknown" in captured.err
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0

    assert main(["probe-subs", "--bvid", "BV1Unknown:p7", "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown --bvid BV1Unknown:p7" in captured.err
    assert gateway.listing_cids == []


# ------------------------------------------------- selection preference

@pytest.mark.parametrize(
    ("language", "is_ai", "expected"),
    [
        ("zh-CN", False, "zh"),
        ("zh-Hans", False, "zh"),
        ("zh-Hant", False, "zh"),
        ("ai-zh", True, "zh"),
        ("AI-ZH", True, "zh"),
        ("ai-en", True, "en"),
        ("en-US", False, "en"),
        ("ja", False, "ja"),
        (" pt-BR ", False, "pt"),
    ],
)
def test_language_family_derivation(
    language: str, is_ai: bool, expected: str
) -> None:
    """The family is the lowercase primary subtag, ``ai-`` stripped for AI."""

    assert language_family(language, is_ai) == expected


@pytest.mark.parametrize("cc_language", ["zh-CN", "zh-Hans", "zh-Hant", "zh"])
@pytest.mark.parametrize("ai_language", ["ai-zh", "ai-ZH"])
@pytest.mark.parametrize("ai_first", [True, False])
def test_default_preference_picks_the_uploader_caption_for_chinese_pairs(
    cc_language: str, ai_language: str, ai_first: bool
) -> None:
    """For any Chinese CC/AI code pair, in either upstream order, CC wins."""

    uploader = SubtitleTrack(
        language=cc_language, label="中文（简体）", is_ai=False, track_id=None
    )
    machine = SubtitleTrack(
        language=ai_language, label="中文（自动生成）", is_ai=True, track_id="1"
    )
    tracks = (machine, uploader) if ai_first else (uploader, machine)

    assert select_subtitle_track(tracks) is uploader


def test_default_preference_ranks_known_families_then_falls_back_to_upstream_order() -> None:
    """``zh`` outranks ``en``, both outrank the rest, and order settles ties."""

    french = SubtitleTrack(language="fr", label="Français", is_ai=False, track_id=None)
    english_ai = SubtitleTrack(
        language="ai-en", label="English (auto)", is_ai=True, track_id="2"
    )
    chinese_ai = SubtitleTrack(
        language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
    )
    tr_chinese = SubtitleTrack(
        language="zh-Hant", label="中文（繁體）", is_ai=False, track_id=None
    )

    assert select_subtitle_track((english_ai, french, chinese_ai)) is chinese_ai
    assert select_subtitle_track((french, english_ai)) is english_ai
    assert select_subtitle_track((french, tr_chinese)) is tr_chinese
    # the family rank decides before the CC/AI split: zh still wins over en
    assert select_subtitle_track((AI_ZH, CC_EN)) is AI_ZH
    first_chinese = SubtitleTrack(
        language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
    )
    assert select_subtitle_track((first_chinese, tr_chinese)) is first_chinese
    assert select_subtitle_track(()) is None


def test_the_cc_before_ai_preference_decides_across_two_rest_families() -> None:
    """The corner the prose used to mis-state: a CC/AI pair in distinct families.

    ``_family_rank`` collapses every family outside ``zh``/``en`` onto one rank,
    so the CC-before-AI term is family-blind there: a later French uploader
    caption beats an earlier Japanese machine one, even though the machine track
    comes first upstream.  The ranking key is the locked spec's, so this pins the
    shipped reading; ``test_default_preference_ranks_known_families_then_falls_back_to_upstream_order``
    covers the equal-kind direction and this covers the cross-family one
    (Q3-01).  Neither track is ``zh``/``en`` and neither kind repeats, so the
    family rank and the upstream index each disagree with the outcome on their
    own — the CC/AI term is the only one that produces it.
    """

    japanese_ai = SubtitleTrack(
        language="ai-ja", label="日本語（自動生成）", is_ai=True, track_id="1"
    )
    french_cc = SubtitleTrack(
        language="fr", label="Français", is_ai=False, track_id=None
    )

    assert select_subtitle_track((japanese_ai, french_cc)) is french_cc, (
        "across two rest-families the uploader caption wins, wherever it sits"
    )
    assert select_subtitle_track((french_cc, japanese_ai)) is french_cc, (
        "the CC/AI term is family-blind, so upstream order does not move it"
    )

    other_french = SubtitleTrack(
        language="fr-CA", label="Français (CA)", is_ai=False, track_id=None
    )
    assert (
        select_subtitle_track((japanese_ai, french_cc, other_french)) is french_cc
    ), "same family and same kind: upstream order settles that tie"


def test_explicit_language_matches_exactly_and_first_preference_wins() -> None:
    """``--language`` order decides; a code nothing matches yields no track."""

    assert select_subtitle_track((CC_ZH, AI_ZH), ("ai-zh",)) is AI_ZH
    assert select_subtitle_track((AI_ZH, CC_ZH), ("zh-CN", "ai-zh")) is CC_ZH
    assert select_subtitle_track((CC_ZH, AI_ZH), ("zh",)) is None
    assert select_subtitle_track((), ("zh-CN",)) is None

    ai_spelled_cc = SubtitleTrack(
        language="zh-CN", label="中文（自动生成）", is_ai=True, track_id="1"
    )
    assert (
        select_subtitle_track((ai_spelled_cc, CC_ZH), ("zh-CN",)) is CC_ZH
    ), "inside one preference the uploader caption still wins"


# ------------------------------------------------------- probe-subs output

def test_probe_subs_prints_track_lines_the_zero_track_marker_and_the_summary(
    tmp_root: str, capsys, install_gateway
) -> None:
    """One ``probe`` line per selected part, in selection order, then the summary."""

    _seed_parts(
        tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201))
    )
    gateway = install_gateway(
        tracks={101: (CC_ZH, AI_ZH), 102: ()},
        listing_failures={201: GatewayResponseError(detail=UPSTREAM_ERROR_TEXT)},
    )

    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "sessdata: absent",
        f"probe {BVID_A}:p0 tracks=2",
        "  track zh-CN cc 中文（简体）",
        "  track ai-zh ai 中文（自动生成）",
        f"probe {BVID_A}:p1 tracks=0",
        "  (no subtitles visible)",
        f"probe {BVID_B}:p0 failed response_error",
        "probe-subs: probed=3 with_tracks=1 without_tracks=1 failed=1",
    ]
    assert_leaks_no_markers(captured.out + captured.err, context="probe output")

    # Nothing was written and no body was fetched: a probe lists tracks only.
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
    assert gateway.body_cids == []
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0


def test_probe_subs_exits_two_when_every_selected_part_failed(
    tmp_root: str, capsys, install_gateway
) -> None:
    """A whole-probe failure is the terminal code, with the count still printed."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    install_gateway(listing_failures={101: GatewayRateLimited()})

    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 2

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "sessdata: absent",
        f"probe {BVID_A}:p0 failed rate_limited",
        "probe-subs: probed=1 with_tracks=0 without_tracks=0 failed=1",
    ]


def test_probe_subs_reports_an_empty_selection_as_zero_probed(
    tmp_root: str, capsys, install_gateway
) -> None:
    """No pending part is a completed read, not an error and not a stall."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "sessdata: absent",
        "probe-subs: probed=0 with_tracks=0 without_tracks=0 failed=0",
    ]
    assert gateway.listing_cids == [101]


# ----------------------------------------------------- harvest-subs output

def test_harvest_subs_prints_every_outcome_and_the_complete_summary(
    tmp_root: str, capsys, install_gateway
) -> None:
    """One ``harvest`` line per attempted part, then all four counts and the run."""

    _seed_parts(
        tmp_root,
        ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201), (BVID_B, 1, 202)),
    )
    install_gateway(
        tracks={101: (CC_ZH, AI_ZH), 102: (CC_ZH,), 201: (), 202: (CC_ZH,)},
        segments={101: BODY, 102: BODY},
        body_failures={202: GatewayNotFound()},
    )

    assert main(["harvest-subs", "--limit-parts", "4", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert_leaks_no_markers(captured.out + captured.err, context="harvest output")
    lines = captured.out.splitlines()
    assert lines[:5] == [
        "sessdata: absent",
        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1",
        f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1",
        f"harvest {BVID_B}:p0 no-subtitle",
        f"harvest {BVID_B}:p1 failed subtitle_body_unavailable",
    ]
    summary = lines[5]
    assert summary.startswith("harvest-subs: run_id=")
    assert "attempted=4 stored=2 unchanged=0 no-subtitle=1 failed=1" in summary
    assert summary.endswith("remaining_without_transcript=2")
    assert len(lines) == 6

    with _archive_connection(tmp_root) as connection:
        run = connection.execute(
            "SELECT kind, selector_kind, selector_target, requested_limit,"
            " credential_present, outcome, finished_at FROM acquisition_runs"
        ).fetchone()
        assert (
            run["kind"],
            run["selector_kind"],
            run["selector_target"],
            run["requested_limit"],
        ) == ("subtitle", "pending", None, 4)
        assert run["kind"] in ALLOWED_ACQUISITION_KINDS
        assert run["credential_present"] == 0
        assert run["outcome"] == "partial"
        assert run["finished_at"] is not None
        assert [
            (row["outcome"], row["error_code"])
            for row in connection.execute(
                "SELECT outcome, error_code FROM acquisition_attempts"
                " ORDER BY video_part_id"
            )
        ] == [
            ("stored", None),
            ("stored", None),
            ("no-subtitle", None),
            ("failed", "subtitle_body_unavailable"),
        ]
        stored = connection.execute(
            "SELECT source_kind, language, version FROM transcripts"
            " ORDER BY transcript_id"
        ).fetchall()
        assert [(row["source_kind"], row["language"], row["version"]) for row in stored] == [
            ("subtitle-cc", "zh-CN", 1),
            ("subtitle-cc", "zh-CN", 1),
        ]
        assert {row["source_kind"] for row in stored} <= ALLOWED_CAPTION_SOURCE_KINDS
        assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 4
        # every attempt carries its own timestamps, so a captionless part is
        # timestamped evidence and never a success with empty content
        assert connection.execute(
            "SELECT COUNT(*) FROM acquisition_attempts"
            " WHERE outcome = 'no-subtitle'"
            " AND started_at IS NOT NULL AND finished_at IS NOT NULL"
        ).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM v_missing_audio").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM v_pending_subtitles").fetchone()[0] == 2
        assert [row[0] for row in connection.execute(
            "SELECT absence_verified FROM acquisition_attempts"
        )] == [0, 0, 0, 0]


def test_default_preference_stores_the_uploader_caption_when_both_are_visible(
    tmp_root: str, capsys, install_gateway
) -> None:
    """The AI track is visible first upstream and the CC track is still selected."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    install_gateway(tracks={101: (AI_ZH, CC_ZH)}, segments={101: BODY})

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == (
        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1"
    )


def test_language_preference_reaches_the_ai_track(
    tmp_root: str, capsys, install_gateway
) -> None:
    """``--language`` overrides the default order by exact upstream code."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    install_gateway(tracks={101: (CC_ZH, AI_ZH)}, segments={101: BODY})

    assert (
        main(
            [
                "harvest-subs",
                "--limit-parts",
                "1",
                "--language",
                "ai-zh, zh-CN",
                "--archive-root",
                tmp_root,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == (
        f"harvest {BVID_A}:p0 stored subtitle-ai ai-zh v1"
    )
    with _archive_connection(tmp_root) as connection:
        row = connection.execute(
            "SELECT source_kind, language FROM transcripts"
        ).fetchone()
    assert (row["source_kind"], row["language"]) == ("subtitle-ai", "ai-zh")


def test_unmatched_language_preference_is_no_subtitle_with_no_fetch(
    tmp_root: str, capsys, install_gateway
) -> None:
    """Nothing usable *for the requested language* is no-subtitle, never failed."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: (CC_ZH, AI_ZH)})

    assert (
        main(
            [
                "harvest-subs",
                "--limit-parts",
                "1",
                "--language",
                "ja",
                "--archive-root",
                tmp_root,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[1] == f"harvest {BVID_A}:p0 no-subtitle"
    assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in lines[2]
    assert gateway.body_cids == []
    with _archive_connection(tmp_root) as connection:
        attempt = connection.execute(
            "SELECT outcome, error_code, transcript_id FROM acquisition_attempts"
        ).fetchone()
        assert (attempt["outcome"], attempt["error_code"]) == ("no-subtitle", None)
        assert attempt["transcript_id"] is None
        assert connection.execute(
            "SELECT outcome FROM acquisition_runs"
        ).fetchone()[0] == "complete"
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0


def test_harvest_subs_reports_an_empty_pending_selection_as_complete(
    tmp_root: str, capsys, install_gateway
) -> None:
    """``attempted=0`` is a completed bounded run, still with every count printed."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    assert main(["harvest-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0] == "sessdata: absent"
    assert "attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0" in lines[1]
    assert lines[1].endswith("remaining_without_transcript=0")
    assert gateway.listing_cids == [101]
    with _archive_connection(tmp_root) as connection:
        assert [
            row["outcome"]
            for row in connection.execute(
                "SELECT outcome FROM acquisition_runs ORDER BY started_at"
            )
        ] == ["complete", "complete"]


# -------------------------------------------- enumeration and re-acquisition

def test_explicit_bvid_selects_every_stored_part_including_a_stored_one(
    tmp_root: str, capsys, install_gateway
) -> None:
    """An explicit video selection re-checks stored parts and reports ``unchanged``."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201)))
    gateway = install_gateway(
        tracks={101: (CC_ZH,), 102: (CC_ZH,), 201: (CC_ZH,)},
        segments={101: BODY, 102: BODY, 201: BODY},
    )

    assert (
        main(
            ["harvest-subs", "--bvid", BVID_A, "--limit-parts", "5",
             "--archive-root", tmp_root]
        )
        == 0
    )
    capsys.readouterr()
    assert gateway.listing_cids == [101, 102], "only that video's stored parts"

    assert (
        main(
            ["harvest-subs", "--bvid", BVID_A, "--limit-parts", "5",
             "--archive-root", tmp_root]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out.splitlines()[1:3] == [
        f"harvest {BVID_A}:p0 unchanged subtitle-cc zh-CN v1",
        f"harvest {BVID_A}:p1 unchanged subtitle-cc zh-CN v1",
    ]
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 2
    with _archive_connection(tmp_root) as connection:
        assert connection.execute(
            "SELECT outcome FROM acquisition_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()[0] == "complete"


def test_a_single_named_part_needs_no_bound_and_records_its_selector(
    tmp_root: str, capsys, install_gateway
) -> None:
    """``bvid:pN`` is bounded by construction; the run records what was named."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
    gateway = install_gateway(tracks={102: (CC_ZH,)}, segments={102: BODY})

    assert (
        main(["harvest-subs", "--bvid", f"{BVID_A}:p1", "--archive-root", tmp_root])
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == (
        f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1"
    )
    assert gateway.listing_cids == [102]
    with _archive_connection(tmp_root) as connection:
        run = connection.execute(
            "SELECT selector_kind, selector_target, requested_limit"
            " FROM acquisition_runs"
        ).fetchone()
    assert (
        run["selector_kind"],
        run["selector_target"],
        run["requested_limit"],
    ) == ("bvid", f"{BVID_A}:p1", None)


def test_bounded_pending_runs_advance_through_the_captionless_backlog(
    tmp_root: str, capsys, install_gateway
) -> None:
    """Never-attempted parts come first; repeated runs rotate, never stall."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201)))
    gateway = install_gateway(tracks={101: (), 102: (), 201: ()})

    attempted = []
    for _run in range(4):
        assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
        captured = capsys.readouterr()
        assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in captured.out
        attempted.append(gateway.listing_cids[-1])

    assert attempted == [101, 102, 201, 101], (
        "never-attempted parts first, then the oldest attempt"
    )
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 4
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0


def test_unchanged_content_adds_no_version_and_changed_content_appends_one(
    tmp_root: str, capsys, install_gateway
) -> None:
    """Re-acquisition is idempotent, and a revised body becomes the next version."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    assert (
        main(["harvest-subs", "--bvid", f"{BVID_A}:p0", "--archive-root", tmp_root])
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == (
        f"harvest {BVID_A}:p0 unchanged subtitle-cc zh-CN v1"
    )

    gateway.script_subtitle_segments(101, CHANGED_BODY)
    assert (
        main(["harvest-subs", "--bvid", f"{BVID_A}:p0", "--archive-root", tmp_root])
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == (
        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v2"
    )

    with _archive_connection(tmp_root) as connection:
        assert [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM transcripts ORDER BY version"
            )
        ] == [1, 2]
        assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 4


def test_a_part_without_a_caption_can_store_one_in_a_later_run(
    tmp_root: str, capsys, install_gateway
) -> None:
    """``no-subtitle`` is an observation at one attempt, never a terminal state."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: ()})

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == f"harvest {BVID_A}:p0 no-subtitle"
    assert "remaining_without_transcript=1" in captured.out

    # the caption appears upstream and the part is still part of the work set
    gateway.script_subtitle_tracks(101, (CC_ZH,))
    gateway.script_subtitle_segments(101, BODY)
    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == (
        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1"
    )
    assert "stored=1" in captured.out
    assert "remaining_without_transcript=0" in captured.out
    with _archive_connection(tmp_root) as connection:
        assert [
            (row["outcome"], row["transcript_id"] is not None)
            for row in connection.execute(
                "SELECT outcome, transcript_id FROM acquisition_attempts"
                " ORDER BY started_at, rowid"
            )
        ] == [("no-subtitle", False), ("stored", True)]


# ------------------------------------------------------ outcome mapping

@pytest.mark.parametrize(
    "failure",
    [
        GatewayRateLimited(),
        GatewayTransportError(),
        GatewayResponseError(),
        GatewayShapeError(),
    ],
    ids=lambda failure: failure.code,
)
def test_bounded_gateway_failures_map_to_failed_with_their_code(
    tmp_root: str, capsys, install_gateway, failure: Exception
) -> None:
    """Every non-``not_found`` gateway failure is a bounded ``failed`` part."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
    install_gateway(listing_failures={101: failure, 102: failure})

    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 2

    captured = capsys.readouterr()
    assert (
        f"harvest {BVID_A}:p0 failed {failure.code}"
        in captured.out
    )
    assert "attempted=2 stored=0 unchanged=0 no-subtitle=0 failed=2" in captured.out
    assert_leaks_no_markers(captured.out + captured.err, context="failed-part output")
    with _archive_connection(tmp_root) as connection:
        assert [
            (row["outcome"], row["error_code"], row["transcript_id"])
            for row in connection.execute(
                "SELECT outcome, error_code, transcript_id"
                " FROM acquisition_attempts ORDER BY video_part_id"
            )
        ] == [("failed", failure.code, None), ("failed", failure.code, None)]
        assert connection.execute(
            "SELECT outcome FROM acquisition_runs"
        ).fetchone()[0] == "failed"


@pytest.mark.parametrize(
    "stage, expected_exit, expected_outcome, expected_code",
    [("listing", 0, "no-subtitle", "not_found"),
     ("body", 2, "failed", "subtitle_body_unavailable")],
)
def test_not_found_listing_proves_absence_but_body_failure_retries(
    tmp_root: str, capsys, install_gateway, stage: str,
    expected_exit: int, expected_outcome: str, expected_code: str,
) -> None:
    """Only the listing's definite not-found response proves subtitle absence."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    script: dict = {"tracks": {101: (CC_ZH,)}, "segments": {101: BODY}}
    script[f"{stage}_failures"] = {101: GatewayNotFound()}
    install_gateway(**script)

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == expected_exit

    captured = capsys.readouterr()
    expected_line = f"harvest {BVID_A}:p0 {expected_outcome}"
    if stage == "body":
        expected_line += " subtitle_body_unavailable"
    assert captured.out.splitlines()[1] == expected_line
    if stage == "listing":
        assert "stored=0 unchanged=0 no-subtitle=1 failed=0" in captured.out
    else:
        assert "stored=0 unchanged=0 no-subtitle=0 failed=1" in captured.out
    with _archive_connection(tmp_root) as connection:
        attempt = connection.execute(
            "SELECT outcome, error_code, transcript_id, absence_verified FROM acquisition_attempts"
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM v_missing_audio").fetchone()[0] == int(stage == "listing")
        assert connection.execute("SELECT COUNT(*) FROM v_pending_subtitles").fetchone()[0] == 1
    assert (attempt["outcome"], attempt["error_code"]) == (expected_outcome, expected_code)
    assert attempt["absence_verified"] == int(stage == "listing")
    assert attempt["transcript_id"] is None


def test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts(
    tmp_root: str, capsys, install_gateway
) -> None:
    """The failing part comes *first*: the loop continues into a later success.

    The order is the point.  With the failure last (the direction the E2E scripts
    it) a regression that aborted the loop on the first non-stored outcome would
    still read green here, so this case scripts the failure on the first part and
    asserts that the part after it was really attempted, really stored, and really
    counted — one part's failure does not end a bounded run (QC2-001).
    """

    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
    gateway = install_gateway(
        tracks={101: (CC_ZH,), 102: (CC_ZH,)},
        segments={102: BODY},
        listing_failures={101: GatewayRateLimited()},
    )

    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert_leaks_no_markers(captured.out + captured.err, context="partial-run output")
    with _archive_connection(tmp_root) as connection:
        run = connection.execute(
            "SELECT run_id, outcome FROM acquisition_runs"
        ).fetchone()
        assert captured.out.splitlines() == [
            "sessdata: absent",
            f"harvest {BVID_A}:p0 failed rate_limited",
            f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1",
            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=1"
            " unchanged=0 no-subtitle=0 failed=1 remaining_without_transcript=1",
        ]
        # Both parts were attempted, in selection order, and only the part after
        # the failure fetched a body.
        assert gateway.listing_cids == [101, 102]
        assert gateway.body_cids == [102]
        # The later part's own evidence: the stored transcript is p1's, and the
        # two attempts are the failed one and the stored one, in part order.
        stored = connection.execute(
            "SELECT vp.cid, vp.page_index, t.source_kind, t.language, t.version"
            " FROM transcripts AS t JOIN video_parts AS vp"
            " ON vp.video_part_id = t.video_part_id"
        ).fetchone()
        assert (stored["cid"], stored["page_index"]) == (102, 1)
        assert (
            stored["source_kind"],
            stored["language"],
            stored["version"],
        ) == ("subtitle-cc", "zh-CN", 1)
        assert [
            (row["outcome"], row["error_code"], row["transcript_id"] is not None)
            for row in connection.execute(
                "SELECT a.outcome, a.error_code, a.transcript_id"
                " FROM acquisition_attempts AS a"
                " JOIN video_parts AS vp ON vp.video_part_id = a.video_part_id"
                " ORDER BY vp.page_index"
            )
        ] == [("failed", "rate_limited", False), ("stored", None, True)]
        assert run["outcome"] == "partial"
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 1
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 2


def test_a_body_the_storage_boundary_refuses_is_one_parts_bounded_failure(
    tmp_root: str, capsys, install_gateway
) -> None:
    """A pathological timeline cannot abort the whole bounded run (QC2-002).

    The gateway script is the seam, so the scripted segment is exactly what a
    finite-but-absurd upstream ``to`` produces: a millisecond position above the
    storage contract's caption range (``MAX_TIMELINE_MS``).  The storage boundary
    rejects it with its bounded ``ValueError``, and that rejection is answered as
    *this part's* ``failed``/``shape_error`` attempt — so the part after it is
    still attempted and stored, and the run stays exit 0 with the partial counts
    instead of collapsing into ``<command>: unexpected error`` with exit 2.
    """

    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
    gateway = install_gateway(
        tracks={101: (CC_ZH,), 102: (CC_ZH,)},
        segments={
            101: (
                SubtitleSegment(
                    start_ms=0, end_ms=MAX_TIMELINE_MS + 1, text="越界的一句"
                ),
            ),
            102: BODY,
        },
    )

    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert_leaks_no_markers(captured.out, context="pathological-timeline output")
    with _archive_connection(tmp_root) as connection:
        run = connection.execute(
            "SELECT run_id, outcome FROM acquisition_runs"
        ).fetchone()
        assert captured.out.splitlines() == [
            "sessdata: absent",
            f"harvest {BVID_A}:p0 failed shape_error",
            f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1",
            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=1"
            " unchanged=0 no-subtitle=0 failed=1 remaining_without_transcript=1",
        ]
        assert gateway.listing_cids == [101, 102]
        assert gateway.body_cids == [101, 102]
        assert [
            (row["outcome"], row["error_code"], row["transcript_id"] is not None)
            for row in connection.execute(
                "SELECT a.outcome, a.error_code, a.transcript_id"
                " FROM acquisition_attempts AS a"
                " JOIN video_parts AS vp ON vp.video_part_id = a.video_part_id"
                " ORDER BY vp.page_index"
            )
        ] == [("failed", "shape_error", False), ("stored", None, True)]
        assert run["outcome"] == "partial"
        # The refused part stored nothing at all: no transcript, no segment, and
        # the part stays pending for a later attempt.
        assert [
            (row["cid"], row["version"])
            for row in connection.execute(
                "SELECT vp.cid, t.version FROM transcripts AS t"
                " JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id"
            )
        ] == [(102, 1)]
        stored_part = connection.execute(
            "SELECT video_part_id FROM transcripts"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT COUNT(*) FROM transcript_segments WHERE transcript_id IN"
            " (SELECT transcript_id FROM transcripts WHERE video_part_id = ?)",
            (stored_part,),
        ).fetchone()[0] == len(BODY)


def test_unexpected_error_exits_two_finishes_the_run_and_leaks_nothing(
    tmp_root: str, capsys, install_gateway
) -> None:
    """Anything escaping the service is the fixed line, with the run closed."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    install_gateway(listing_failures={101: RuntimeError(UPSTREAM_ERROR_TEXT)})

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "harvest-subs: unexpected error\n"
    assert_leaks_no_markers(
        captured.out + captured.err, context="unexpected-error output"
    )
    with _archive_connection(tmp_root) as connection:
        run = connection.execute(
            "SELECT outcome, finished_at FROM acquisition_runs"
        ).fetchone()
    assert run["outcome"] == "failed"
    assert run["finished_at"] is not None
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0


# --------------------------------------------------------- boundaries

def test_credential_is_reported_as_presence_only(
    tmp_root: str, capsys, install_gateway
) -> None:
    """The value reaches the adapter and no output path or row ever shows it."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})

    assert (
        main(
            [
                "harvest-subs",
                "--limit-parts",
                "1",
                "--sessdata",
                SESSDATA_BOUNDARY_VALUE,
                "--archive-root",
                tmp_root,
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out.splitlines()[0] == "sessdata: present"
    assert SESSDATA_BOUNDARY_VALUE not in captured.out + captured.err
    assert gateway.sessdata == SESSDATA_BOUNDARY_VALUE
    with _archive_connection(tmp_root) as connection:
        assert connection.execute(
            "SELECT credential_present FROM acquisition_runs"
        ).fetchone()[0] == 1
        assert SESSDATA_BOUNDARY_VALUE not in persisted_row_text(connection)

    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[0] == "sessdata: absent"


def test_the_probe_opens_the_archive_read_only_and_cannot_write(
    tmp_root: str, capsys, install_gateway, monkeypatch
) -> None:
    """The probe's ``mode=ro`` connection is write-proof, not just well-behaved.

    ``probe-subs`` promises it writes nothing at all, and that promise used to
    hold only because the probe happened to call no write: it opened the same
    schema-initializing connection as ``status``/``runs``, and ``open_database``
    executes both idempotent schema scripts and commits them.  The connection the
    probe now opens is asserted here (the URI it asks SQLite for) and then used
    directly, so the "cannot write" claim is functional rather than conventional
    (QC2-003).
    """

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    install_gateway(tracks={101: (CC_ZH,)})

    real_connect = sqlite3.connect
    opened: list[tuple[tuple, dict]] = []

    def recording_connect(*args, **kwargs):
        opened.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    capsys.readouterr()

    assert len(opened) == 1, "the probe opens exactly one connection"
    arguments, keywords = opened[0]
    uri = arguments[0]
    assert keywords == {"uri": True}
    assert uri == (
        Path(os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)).resolve().as_uri()
        + "?mode=ro"
    )

    # The URI the probe used is really write-proof: neither DDL nor DML succeeds
    # through it, so a later edit on the probe path cannot silently write.
    read_only = real_connect(uri, uri=True)
    try:
        for statement in (
            "CREATE TABLE probe_must_not_create(x INTEGER)",
            "DELETE FROM transcripts",
            "INSERT INTO acquisition_runs(run_id, kind, selector_kind,"
            " selector_target, requested_limit, credential_present, started_at,"
            " finished_at, outcome) VALUES ('x', 'subtitle', 'pending', NULL, 1,"
            " 0, 0, NULL, 'running')",
        ):
            with pytest.raises(sqlite3.OperationalError):
                read_only.execute(statement)
    finally:
        read_only.close()

    # And every observable of the probe run is unchanged: one file, no rows.
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
    for table in (
        "acquisition_runs",
        "acquisition_attempts",
        "transcripts",
        "transcript_segments",
    ):
        assert _scalar(tmp_root, f"SELECT COUNT(*) FROM {table}") == 0


def test_neither_command_writes_a_sidecar_or_a_transcript_projection(
    tmp_root: str, capsys, install_gateway
) -> None:
    """Only ``archive.db`` (and the writer lock) appears under the archive root."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})

    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 0
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


def test_both_commands_print_the_fixed_rebuild_line_for_a_legacy_database(
    tmp_root: str, capsys
) -> None:
    """A pre-iteration database: both commands exit 1, the metadata path keeps working."""

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    _write_pre_iteration_database(database_path)

    for command, argv in (
        (
            "probe-subs",
            ["probe-subs", "--bvid", "BV1Legacy", "--archive-root", tmp_root],
        ),
        (
            "harvest-subs",
            ["harvest-subs", "--bvid", "BV1Legacy:p0", "--archive-root", tmp_root],
        ),
    ):
        assert main(argv) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == (
            f"{command}: archive database predates the transcript schema; "
            f"rebuild it (delete {database_path} and re-run fetch-meta)\n"
        )

    assert main(["status", "--archive-root", tmp_root]) == 0
    assert capsys.readouterr().out.startswith("users: 1")


# ------------------------------------------- damaged and empty databases

def _damage_page_one(database_path: str) -> None:
    """Corrupt page 1's body and leave the SQLite header intact.

    The canonical "database disk image is malformed" state an unclean
    shutdown, a full disk, or a partial copy leaves behind: the header still
    answers a ``PRAGMA schema_version``, so the damage surfaces only on the
    first statement that reads ``sqlite_master``.
    """

    with open(database_path, "r+b") as handle:
        handle.seek(64)
        handle.write(b"\x00" * 4096)


def _overwrite_with_text(database_path: str) -> None:
    """Leave a file carrying no SQLite magic at all in the database's place."""

    with open(database_path, "wb") as handle:
        handle.write(b"not a database\n")


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(_damage_page_one, id="damaged-page-1"),
        pytest.param(_overwrite_with_text, id="not-a-database"),
    ],
)
def test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands(
    tmp_root: str, capsys, damage
) -> None:
    """An existing but unreadable database: one bounded line, exit 1, no repair.

    Every ``unreadable archive database`` handler is pinned here: the two open
    helpers (``_open_read_connection`` for ``harvest-subs``,
    ``_open_read_only_connection`` for ``probe-subs``) through the
    not-a-database recipe, and the transcript-schema guard inside
    ``_open_subtitle_connection`` through the damaged-but-openable one, whose
    intact header passes the helper's ``PRAGMA schema_version``.  Before
    F-QA-001 that guard sat outside the bounded handler, so the probe printed a
    raw SQLite traceback instead of the line its own docstring promised.
    Neither command repairs, rewrites, or replaces the damaged database, and a
    harvest leaves only the documented writer lock beside it.
    """

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    damage(database_path)
    damaged_bytes = Path(database_path).read_bytes()

    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"probe-subs: unreadable archive database at {tmp_root} (DatabaseError)\n"
    )
    # The probe is not an archive-writer command: no lock, no other file.
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
    assert Path(database_path).read_bytes() == damaged_bytes

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"harvest-subs: unreadable archive database at {tmp_root} (DatabaseError)\n"
    )
    # A harvest is an archive-writer command, so the documented writer lock is
    # the only other file it leaves.
    assert _archive_files(tmp_root) == sorted(
        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
    )
    assert Path(database_path).read_bytes() == damaged_bytes


def test_a_zero_byte_database_is_initialized_by_harvest_and_refused_by_probe(
    tmp_root: str, capsys
) -> None:
    """The documented empty-file asymmetry: the harvest initializes, the probe refuses.

    ``open_database`` initializes both schema scripts into an existing zero-byte
    file, and that is the shipped semantics ``fetch-meta``, ``status``, ``runs``,
    and ``harvest-subs`` share.  ``probe-subs`` promises to write nothing at all,
    so it refuses the same file with the rebuild line rather than creating the
    transcript contract in it.  Documented in ``docs/metadata-storage.md``
    ("Schema guard and rebuild").
    """

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    with open(database_path, "wb"):
        pass

    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"probe-subs: archive database predates the transcript schema; "
        f"rebuild it (delete {database_path} and re-run fetch-meta)\n"
    )
    # The read-only promise holds structurally: the file is still empty.
    assert os.path.getsize(database_path) == 0
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0] == "sessdata: absent"
    assert "attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0" in lines[1]
    assert lines[1].endswith("remaining_without_transcript=0")
    # Initialized for real: the transcript contract is in the file now.
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
    assert _archive_files(tmp_root) == sorted(
        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
    )
