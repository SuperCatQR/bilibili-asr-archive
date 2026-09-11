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
import importlib
import os
import sqlite3

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
)
from fixtures.fake_bilibili_gateway import (
    SESSDATA_BOUNDARY_VALUE,
    UPSTREAM_ERROR_TEXT,
    assert_leaks_no_markers,
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
PROJECTION_PREFIXES = ("subtitles/raw/", "transcripts/srt/")
#: ``harvest-subs`` is an archive-writer command, so the shipped lock is the one
#: file besides the database it is expected to leave behind.
ARCHIVE_WRITER_LOCK_PATH = "coordinator/archive-writer.lock"


@pytest.fixture(autouse=True)
def _anonymous_environment(monkeypatch: pytest.MonkeyPatch):
    """No credential in the environment unless a test sets one explicitly."""

    monkeypatch.delenv("BILI_SESSDATA", raising=False)


class _ScriptedSubtitleGateway:
    """The gateway protocol's two subtitle calls, scripted per part, offline.

    A part is addressed by its ``cid``: ``tracks_by_cid`` scripts one inventory,
    ``segments_by_cid`` one body, and the two failure maps raise instead of
    answering.  A call the test did not script fails loudly rather than silently
    answering an empty inventory, and every call is recorded — ``listing_cids``
    and ``body_cids`` in issue order — so the enumeration order and "the body was
    never fetched" are assertable.
    """

    def __init__(
        self,
        *,
        tracks: dict[int, tuple[SubtitleTrack, ...]] | None = None,
        segments: dict[int, tuple[SubtitleSegment, ...]] | None = None,
        listing_failures: dict[int, Exception] | None = None,
        body_failures: dict[int, Exception] | None = None,
    ) -> None:
        self.tracks_by_cid = dict(tracks or {})
        self.segments_by_cid = dict(segments or {})
        self.listing_failures_by_cid = dict(listing_failures or {})
        self.body_failures_by_cid = dict(body_failures or {})
        self.sessdata: str | None = None
        self.listing_cids: list[int] = []
        self.body_cids: list[int] = []

    async def get_subtitle_tracks(
        self, bvid: str, cid: int
    ) -> tuple[SubtitleTrack, ...]:
        self.listing_cids.append(cid)
        failure = self.listing_failures_by_cid.get(cid)
        if failure is not None:
            raise failure
        if cid not in self.tracks_by_cid:
            raise AssertionError(f"the test did not script a listing for cid {cid}")
        return self.tracks_by_cid[cid]

    async def fetch_subtitle_segments(
        self, track: SubtitleTrack, bvid: str, cid: int
    ) -> tuple[SubtitleSegment, ...]:
        self.body_cids.append(cid)
        failure = self.body_failures_by_cid.get(cid)
        if failure is not None:
            raise failure
        if cid not in self.segments_by_cid:
            raise AssertionError(f"the test did not script a body for cid {cid}")
        return self.segments_by_cid[cid]


@pytest.fixture
def install_gateway(monkeypatch: pytest.MonkeyPatch):
    """Install one scripted gateway as the CLI's concrete adapter.

    The composition root imports ``BilibiliApiGateway`` inside each handler, so
    replacing the class in its own module keeps the whole command path under test
    with no network and no package seam.  The double records the credential the
    composition root handed it, which the credential test pins.

    The module is reached through ``importlib`` deliberately: the adapter is
    dropped from ``sys.modules`` by the package-seam fixtures of the other test
    modules, and a plain ``import ... as`` would then bind the parent package's
    stale attribute instead of the module the handler imports from.
    """

    def install(**script) -> _ScriptedSubtitleGateway:
        gateway_module = importlib.import_module(
            "bili_asr.sources.bilibili_api_gateway"
        )
        gateway = _ScriptedSubtitleGateway(**script)

        def factory(sessdata: str | None = None, proxy: str | None = None):
            del proxy
            gateway.sessdata = sessdata
            return gateway

        monkeypatch.setattr(gateway_module, "BilibiliApiGateway", factory)
        return gateway

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
        ["harvest-subs"],
        ["harvest-subs", "--bvid", BVID_A],
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
        f"harvest {BVID_B}:p1 no-subtitle",
    ]
    summary = lines[5]
    assert summary.startswith("harvest-subs: run_id=")
    assert "attempted=4 stored=2 unchanged=0 no-subtitle=2 failed=0" in summary
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
        assert run["outcome"] == "complete"
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
            ("no-subtitle", "not_found"),
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
        ).fetchone()[0] == 2


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

    gateway.segments_by_cid[101] = CHANGED_BODY
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
    gateway.tracks_by_cid[101] = (CC_ZH,)
    gateway.segments_by_cid[101] = BODY
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


@pytest.mark.parametrize("stage", ["listing", "body"])
def test_not_found_is_recorded_no_subtitle_with_its_code(
    tmp_root: str, capsys, install_gateway, stage: str
) -> None:
    """Upstream ``not_found`` is evidence without a caption, never a failure."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
    script: dict = {"tracks": {101: (CC_ZH,)}, "segments": {101: BODY}}
    script[f"{stage}_failures"] = {101: GatewayNotFound()}
    install_gateway(**script)

    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines()[1] == f"harvest {BVID_A}:p0 no-subtitle"
    assert "stored=0 unchanged=0 no-subtitle=1 failed=0" in captured.out
    with _archive_connection(tmp_root) as connection:
        attempt = connection.execute(
            "SELECT outcome, error_code, transcript_id FROM acquisition_attempts"
        ).fetchone()
    assert (attempt["outcome"], attempt["error_code"]) == ("no-subtitle", "not_found")
    assert attempt["transcript_id"] is None


def test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts(
    tmp_root: str, capsys, install_gateway
) -> None:
    """One stored and one failed part is a partial run, not a terminal failure."""

    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
    install_gateway(
        tracks={101: (CC_ZH,), 102: (CC_ZH,)},
        segments={101: BODY},
        listing_failures={102: GatewayRateLimited()},
    )

    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0

    captured = capsys.readouterr()
    assert "attempted=2 stored=1 unchanged=0 no-subtitle=0 failed=1" in captured.out
    assert captured.out.splitlines()[2] == (
        f"harvest {BVID_A}:p1 failed rate_limited"
    )
    with _archive_connection(tmp_root) as connection:
        assert connection.execute(
            "SELECT outcome FROM acquisition_runs"
        ).fetchone()[0] == "partial"
    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 1


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
