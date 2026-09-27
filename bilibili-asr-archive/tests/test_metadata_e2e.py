"""Offline end-to-end metadata verification: CLI → ingestor → repository.

Every test drives the real user-facing command path — ``bili_asr.cli.main``
with plain argv — over the fake ``bilibili_api`` package seam from
``tests/fixtures/``, so the whole stack runs offline exactly as an operator
would run it: CLI composition root, real gateway adapter
(``bili_asr.sources.bilibili_api_gateway.BilibiliApiGateway``),
``MetadataIngestor``, and the Plan-1 repository persisting into a temporary
SQLite database.  The tests produce the deterministic iteration acceptance
evidence:

- one scripted page holding a single-part and a multipart video lands all
  normalized rows (user/video/part/discovery/run/page/cursor) with the
  computed ``work_id`` view values;
- re-running the same scripted page duplicates no entity rows and keeps
  discovery evidence unique per ``(run_id, page_number, bvid)`` (discovery
  rows are run-scoped by the repository's primary key);
- a failed page preserves the stored cursor byte-for-byte and persists a
  bounded scalar error code only, and a later run resumes from the prior
  cursor and completes;
- no legacy JSONL/cursor/ledger sidecar is created in the archive root, and
  no credential or raw upstream payload sentinel reaches CLI output or any
  persisted row.
"""

from __future__ import annotations

import itertools
import os

import pytest

from bili_asr.cli import main
from bili_asr.config import DEFAULT_PAGE_LIMIT
from bili_asr.storage import open_database
from fixtures.fake_bilibili_gateway import (
    MID,
    RAW_JSON_BODY_MARKER,
    SESSDATA_BOUNDARY_VALUE,
    SIGNED_URL_MARKER,
    UPSTREAM_ERROR_TEXT,
    FakeResponseCodeException,
    assert_leaks_no_markers,
    assert_only_documented_metadata_calls,
    bilibili_api_seam,
    make_part_item,
    make_videos_response,
    make_vlist_item,
    persisted_row_text,
    script_parts_by_bvid,
)

LEGACY_SIDECAR_PATHS = (
    os.path.join("manifest", "manifest.jsonl"),
    "meta-cursor.json",
    "run-ledger.jsonl",
)

SINGLE_PART_BVID = "BV1SINGLEPT1"
MULTI_PART_BVID = "BV1MULTIPRT2"
RESUMED_BVID = "BV1RESUMEPG2"


def _script_upstream(
    script,
    *,
    pages: dict[int, list[dict]],
    parts_by_bvid: dict[str, list[dict]],
) -> None:
    """Script named upstream video pages plus each video's own parts.

    Unscripted pages come back empty; a parts fetch for a bvid outside
    ``parts_by_bvid`` fails loudly.
    """

    def videos_response(pn: int, ps: int):
        items = pages.get(pn, [])
        return make_videos_response(*items, count=len(items))

    script.videos_response = videos_response
    script_parts_by_bvid(script, parts_by_bvid)


@pytest.fixture
def _ingest_clock(monkeypatch: pytest.MonkeyPatch):
    """Deterministic monotonic clock for multi-run ordering.

    Patching the ingestor module's clock keeps every run's ``started_at``
    strictly below the next run's, so ``_newest_run_id`` and the newest-first
    runs listing stay deterministic without real sleeps.
    """

    counter = itertools.count(1)
    monkeypatch.setattr(
        "bili_asr.services.metadata_ingest._now", lambda: next(counter)
    )


def _newest_run_id(tmp_root: str) -> str:
    """Return the id of the newest ingestion run in the root's database."""

    connection = open_database(tmp_root)
    try:
        run_row = connection.execute(
            "SELECT run_id FROM ingestion_runs"
            " ORDER BY started_at DESC, run_id DESC LIMIT 1"
        ).fetchone()
        assert run_row is not None
        return str(run_row["run_id"])
    finally:
        connection.close()


def _cursor_row(connection):
    return connection.execute(
        "SELECT mid, next_page, observed_total, state, last_error_code, updated_at"
        " FROM ingestion_cursors"
    ).fetchone()


def _discovery_rows(connection):
    return connection.execute(
        "SELECT run_id, page_number, bvid, source_position"
        " FROM ingestion_discoveries ORDER BY run_id, page_number, bvid"
    ).fetchall()


def test_fetch_meta_normalizes_single_part_and_multipart_videos_end_to_end(
    tmp_root: str,
    bilibili_api_seam,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One CLI run lands every normalized row family and the work_id views."""

    script = bilibili_api_seam
    # Payload-laden upstream items: the seam sentinels ride the raw responses
    # so the no-leak assertions scan surfaces that really carried them.
    _script_upstream(
        script,
        pages={
            1: [
                make_vlist_item(
                    bvid=SINGLE_PART_BVID,
                    aid=111,
                    sessdata_note=SESSDATA_BOUNDARY_VALUE,
                    frame_url=SIGNED_URL_MARKER,
                    raw_note=RAW_JSON_BODY_MARKER,
                ),
                make_vlist_item(bvid=MULTI_PART_BVID, aid=222),
            ]
        },
        parts_by_bvid={
            SINGLE_PART_BVID: [make_part_item(cid=2222)],
            MULTI_PART_BVID: [
                make_part_item(cid=3331, page=1, part="上篇"),
                make_part_item(cid=3332, page=2, part="下篇"),
            ],
        },
    )
    assert (
        main(
            [
                "fetch-meta",
                "--archive-root",
                tmp_root,
                "--sessdata",
                SESSDATA_BOUNDARY_VALUE,
            ]
        )
        == 0
    )

    # The user-facing surface stays redacted and outcome-honest.
    out, err = capsys.readouterr()
    assert err == ""
    assert "sessdata: present" in out
    assert "2 page(s)" in out
    assert "outcome=complete" in out
    assert "cursor: next_page=2 state=complete" in out
    assert_leaks_no_markers(out + err, context="fetch-meta output")

    assert os.path.isfile(os.path.join(tmp_root, "archive.db"))
    connection = open_database(tmp_root)
    try:
        user_row = connection.execute(
            "SELECT mid, display_name FROM bilibili_users"
        ).fetchone()
        # The uploader's own name, read off the collected page: the row no
        # longer holds the owner-mid placeholder.
        assert tuple(user_row) == (MID, "未明子")

        video_rows = connection.execute(
            "SELECT bvid, aid, mid, title, pubdate FROM videos ORDER BY bvid"
        ).fetchall()
        assert [tuple(row) for row in video_rows] == [
            (MULTI_PART_BVID, 222, MID, "未明子讲座", 1_725_859_200),
            (SINGLE_PART_BVID, 111, MID, "未明子讲座", 1_725_859_200),
        ]

        part_rows = connection.execute(
            "SELECT bvid, page_index, cid, title, duration_ms, processing_status"
            " FROM video_parts ORDER BY bvid, page_index"
        ).fetchall()
        assert [tuple(row) for row in part_rows] == [
            (MULTI_PART_BVID, 0, 3331, "上篇", 12_000, "discovered"),
            (MULTI_PART_BVID, 1, 3332, "下篇", 12_000, "discovered"),
            (SINGLE_PART_BVID, 0, 2222, "第一部分", 12_000, "discovered"),
        ]

        run_row = connection.execute(
            "SELECT run_id, mid, source_package, source_version,"
            " requested_start_page, requested_page_limit, outcome, finished_at"
            " FROM ingestion_runs"
        ).fetchone()
        assert run_row is not None
        assert tuple(run_row)[1:7] == (
            MID,
            "bilibili-api-python",
            "17.4.2",
            1,
            DEFAULT_PAGE_LIMIT,
            "complete",
        )
        assert run_row["finished_at"] is not None
        run_id = str(run_row["run_id"])

        page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " ORDER BY page_number"
        ).fetchall()
        assert [tuple(row) for row in page_rows] == [
            (1, "ok", None),
            (2, "empty", None),
        ]

        discovery_rows = _discovery_rows(connection)
        assert [tuple(row) for row in discovery_rows] == [
            (run_id, 1, MULTI_PART_BVID, 1),
            (run_id, 1, SINGLE_PART_BVID, 0),
        ]

        cursor_row = _cursor_row(connection)
        assert tuple(cursor_row)[:5] == (MID, 2, 0, "complete", None)
        assert cursor_row["updated_at"] > 0

        # The computed work_id view values join user and video context.
        view_rows = connection.execute(
            "SELECT work_id, user_name, video_title, part_title, processing_status"
            " FROM v_video_parts ORDER BY work_id"
        ).fetchall()
        assert [row["work_id"] for row in view_rows] == [
            f"{MULTI_PART_BVID}:p0",
            f"{MULTI_PART_BVID}:p1",
            f"{SINGLE_PART_BVID}:p0",
        ]
        first_view_row = view_rows[0]
        # End-to-end proof that the stored name reaches a reader: the view joins
        # ``bilibili_users``, so this column is the collected ``author`` and not
        # the owner-mid placeholder the user row used to hold.
        assert first_view_row["user_name"] == "未明子"
        assert first_view_row["video_title"] == "未明子讲座"
        assert first_view_row["part_title"] == "上篇"
        assert first_view_row["processing_status"] == "discovered"

        pending = connection.execute(
            "SELECT work_id FROM v_pending_metadata ORDER BY bvid, page_index"
        ).fetchall()
        assert [row["work_id"] for row in pending] == [
            f"{MULTI_PART_BVID}:p0",
            f"{MULTI_PART_BVID}:p1",
            f"{SINGLE_PART_BVID}:p0",
        ]

        # Positive control: a normalized video row really persisted, so the
        # no-leak scan is not vacuous.
        persisted = persisted_row_text(connection)
        assert SINGLE_PART_BVID in persisted
        assert_leaks_no_markers(persisted, context="fetch-meta persisted rows")
    finally:
        connection.close()

    # The read commands close the loop over the same SQLite database.
    assert main(["status", "--archive-root", tmp_root]) == 0
    status_out, status_err = capsys.readouterr()
    assert status_err == ""
    assert "users: 1" in status_out
    assert "videos: 2" in status_out
    assert "parts: 3" in status_out
    assert "discovered=3" in status_out
    assert "pending: 3" in status_out
    assert f"{SINGLE_PART_BVID}:p0" in status_out
    assert "cursor: mid=23191782 next_page=2 state=complete" in status_out
    assert_leaks_no_markers(status_out + status_err, context="status output")

    assert main(["runs", "--archive-root", tmp_root]) == 0
    runs_out, runs_err = capsys.readouterr()
    assert runs_err == ""
    assert "outcome=complete" in runs_out
    assert "pages=2" in runs_out
    assert "videos=2" in runs_out
    assert_leaks_no_markers(runs_out, context="runs output")

    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(tmp_root, relative))

    # The pinned adapter drove exactly the documented metadata calls: one
    # page fetch, then one parts fetch per distinct video and one tag fetch
    # per distinct video, then the completing empty-page fetch (aids present,
    # so no detail calls).  The tag fetch is per-video rather than per-part
    # however many parts that video has: the multipart video below has two
    # parts and still costs exactly one tag call.
    assert script.calls == [
        "space.arc.search(pn=1, ps=30)",
        "video.get_pages",
        "video.get_pages",
        "video.tags",
        "video.tags",
        "space.arc.search(pn=2, ps=30)",
    ]
    assert_only_documented_metadata_calls(script.calls)


def test_fetch_meta_rerun_of_same_page_stores_no_duplicate_rows(
    tmp_root: str,
    bilibili_api_seam,
    capsys: pytest.CaptureFixture[str],
    _ingest_clock,
) -> None:
    """Re-collecting the same scripted page duplicates no persisted facts.

    Entities upsert onto their existing rows; discovery evidence is
    run-scoped by the repository's primary key ``(run_id, page_number,
    bvid)``, so each run records exactly one discovery row per distinct
    video and no run duplicates another's rows.
    """

    script = bilibili_api_seam
    _script_upstream(
        script,
        pages={
            1: [
                make_vlist_item(bvid=SINGLE_PART_BVID, aid=111),
                make_vlist_item(bvid=MULTI_PART_BVID, aid=222),
            ]
        },
        parts_by_bvid={
            SINGLE_PART_BVID: [make_part_item(cid=2222)],
            MULTI_PART_BVID: [
                make_part_item(cid=3331, page=1, part="上篇"),
                make_part_item(cid=3332, page=2, part="下篇"),
            ],
        },
    )
    assert (
        main(
            [
                "fetch-meta",
                "--archive-root",
                tmp_root,
                "--sessdata",
                SESSDATA_BOUNDARY_VALUE,
            ]
        )
        == 0
    )
    first_run_id = _newest_run_id(tmp_root)

    # Re-run the same page explicitly: --start-page overrides the cursor.
    assert (
        main(
            [
                "fetch-meta",
                "--archive-root",
                tmp_root,
                "--start-page",
                "1",
                "--sessdata",
                SESSDATA_BOUNDARY_VALUE,
            ]
        )
        == 0
    )
    second_run_id = _newest_run_id(tmp_root)
    assert second_run_id != first_run_id

    connection = open_database(tmp_root)
    try:
        # Entities stay single: one user, one row per video, one per part.
        assert (
            connection.execute("SELECT COUNT(*) FROM bilibili_users").fetchone()[0]
            == 1
        )
        video_bvids = [
            row[0]
            for row in connection.execute("SELECT bvid FROM videos ORDER BY bvid")
        ]
        assert video_bvids == [MULTI_PART_BVID, SINGLE_PART_BVID]
        part_keys = [
            tuple(row)
            for row in connection.execute(
                "SELECT bvid, page_index, cid FROM video_parts"
                " ORDER BY bvid, page_index"
            )
        ]
        assert part_keys == [
            (MULTI_PART_BVID, 0, 3331),
            (MULTI_PART_BVID, 1, 3332),
            (SINGLE_PART_BVID, 0, 2222),
        ]

        # Discovery evidence: two runs, each recording page 1 exactly once
        # per video (run ids are unordered hex, so compare as a set).
        discoveries = set(
            tuple(row) for row in _discovery_rows(connection)
        )
        assert discoveries == {
            (first_run_id, 1, MULTI_PART_BVID, 1),
            (first_run_id, 1, SINGLE_PART_BVID, 0),
            (second_run_id, 1, MULTI_PART_BVID, 1),
            (second_run_id, 1, SINGLE_PART_BVID, 0),
        }

        # The re-run also verified completion through the empty page.
        second_run_pages = connection.execute(
            "SELECT page_number, outcome FROM ingestion_pages"
            " WHERE run_id = ? ORDER BY page_number",
            (second_run_id,),
        ).fetchall()
        assert [tuple(row) for row in second_run_pages] == [(1, "ok"), (2, "empty")]

        assert (
            connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]
            == 2
        )
        cursor_row = _cursor_row(connection)
        assert tuple(cursor_row)[:5] == (MID, 2, 0, "complete", None)

        # Positive control: a normalized video row really persisted, so the
        # re-run's no-leak scan is not vacuous.
        persisted = persisted_row_text(connection)
        assert SINGLE_PART_BVID in persisted
        assert_leaks_no_markers(persisted, context="re-run persisted rows")
    finally:
        connection.close()

    out, err = capsys.readouterr()
    assert err == ""
    # Positive control: the credential really flowed through this run's
    # flag path, so the re-run's output no-leak scan is not vacuous.
    assert "sessdata: present" in out
    assert_leaks_no_markers(out + err, context="fetch-meta re-run output")
    # Page 1 was fetched exactly twice: once per run.
    assert script.calls.count("space.arc.search(pn=1, ps=30)") == 2

    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(tmp_root, relative))


def test_fetch_meta_failed_page_preserves_cursor_and_resume_succeeds(
    tmp_root: str,
    bilibili_api_seam,
    capsys: pytest.CaptureFixture[str],
    _ingest_clock,
) -> None:
    """A failed page stores bounded evidence only; the prior cursor resumes."""

    script = bilibili_api_seam
    _script_upstream(
        script,
        pages={1: [make_vlist_item(bvid=SINGLE_PART_BVID, aid=111)]},
        parts_by_bvid={
            SINGLE_PART_BVID: [make_part_item(cid=2222)],
            RESUMED_BVID: [make_part_item(cid=4444)],
        },
    )
    # The explicit bound stops the run after page 1: the cursor points at 2.
    assert main(["fetch-meta", "--archive-root", tmp_root, "--limit-pages", "1"]) == 0
    limited_run_id = _newest_run_id(tmp_root)

    connection = open_database(tmp_root)
    try:
        cursor_before_failure = _cursor_row(connection)
        assert tuple(cursor_before_failure)[:5] == (MID, 2, 1, "limited", None)
    finally:
        connection.close()

    # Arm a terminal upstream failure for the resume page.
    script.videos_error = FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT)
    assert main(["fetch-meta", "--archive-root", tmp_root]) == 2
    failed_run_id = _newest_run_id(tmp_root)
    assert failed_run_id != limited_run_id

    out, err = capsys.readouterr()
    assert "rate_limited" in err
    assert "cursor unchanged" in err
    assert_leaks_no_markers(out + err, context="fetch-meta failure output")

    connection = open_database(tmp_root)
    try:
        # The cursor is preserved byte-for-byte: a failed page never writes it.
        assert tuple(_cursor_row(connection)) == tuple(cursor_before_failure)

        # Bounded failure evidence only: no entity or discovery growth.
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM ingestion_discoveries").fetchone()[0]
            == 1
        )
        failed_page_rows = connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ? ORDER BY page_number",
            (failed_run_id,),
        ).fetchall()
        assert [tuple(row) for row in failed_page_rows] == [
            (2, "risk_interrupted", "rate_limited")
        ]
        failed_run_row = connection.execute(
            "SELECT outcome, finished_at FROM ingestion_runs WHERE run_id = ?",
            (failed_run_id,),
        ).fetchone()
        assert failed_run_row["outcome"] == "risk_interrupted"
        assert failed_run_row["finished_at"] is not None
        assert_leaks_no_markers(
            persisted_row_text(connection),
            context="persisted rows after failed page",
        )
    finally:
        connection.close()

    # The upstream recovers; the next run resumes from the preserved cursor.
    script.videos_error = None
    _script_upstream(
        script,
        pages={2: [make_vlist_item(bvid=RESUMED_BVID, aid=222)]},
        parts_by_bvid={RESUMED_BVID: [make_part_item(cid=4444)]},
    )
    assert main(["fetch-meta", "--archive-root", tmp_root]) == 0
    resumed_run_id = _newest_run_id(tmp_root)
    assert resumed_run_id != failed_run_id

    connection = open_database(tmp_root)
    try:
        resumed_run_row = connection.execute(
            "SELECT requested_start_page, outcome FROM ingestion_runs"
            " WHERE run_id = ?",
            (resumed_run_id,),
        ).fetchone()
        assert tuple(resumed_run_row) == (2, "complete")

        video_bvids = [
            row[0]
            for row in connection.execute("SELECT bvid FROM videos ORDER BY bvid")
        ]
        assert video_bvids == [RESUMED_BVID, SINGLE_PART_BVID]
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 2

        discoveries = [tuple(row) for row in _discovery_rows(connection)]
        assert sorted(discoveries, key=lambda row: (row[1], row[2])) == [
            (limited_run_id, 1, SINGLE_PART_BVID, 0),
            (resumed_run_id, 2, RESUMED_BVID, 0),
        ]

        cursor_row = _cursor_row(connection)
        assert tuple(cursor_row)[:5] == (MID, 3, 0, "complete", None)
    finally:
        connection.close()

    # The runs listing renders every outcome with its bounded error code.
    assert main(["runs", "--archive-root", tmp_root]) == 0
    runs_out, runs_err = capsys.readouterr()
    assert runs_err == ""
    assert "outcome=limited" in runs_out
    assert "outcome=risk_interrupted" in runs_out
    assert "outcome=complete" in runs_out
    assert "error=rate_limited" in runs_out
    assert_leaks_no_markers(runs_out, context="runs output after failure and resume")

    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(tmp_root, relative))

    # The full call trace: bounded page fetches, one parts and one tag fetch
    # per new video, the failed resume page, then the successful resume.
    assert script.calls == [
        "space.arc.search(pn=1, ps=30)",
        "video.get_pages",
        "video.tags",
        "space.arc.search(pn=2, ps=30)",
        "space.arc.search(pn=2, ps=30)",
        "video.get_pages",
        "video.tags",
        "space.arc.search(pn=3, ps=30)",
    ]
    assert_only_documented_metadata_calls(script.calls)
