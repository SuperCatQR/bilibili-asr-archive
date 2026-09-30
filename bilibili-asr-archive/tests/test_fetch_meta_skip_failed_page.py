"""``--skip-failed-page``: escaping a terminally wedged page (compass D-3).

A page that fails terminally fails *identically* on every later run, so a run
that leaves the cursor parked on it never makes progress again: ``--resume``
re-fails at the same page forever.  ``--skip-failed-page`` is the deliberate,
opt-in escape hatch.  It moves only the *next* run's starting point; the run
that hit the failure still ends ``failed`` and still exits 2, the page row is
still ``failed`` with its bounded code, and ``runs`` still renders that code —
the gap stays visible rather than being erased.

The wedged page is driven by a **scripted ``GatewayShapeError``** from the protocol double
rather than by a malformed text field.  That is deliberate and stronger than a field-based
fixture: the wedge is field-independent, so no other track's change to a specific normalizer
(``title``, ``description``, or any later one) can silently make these tests stop exercising the
skip path.  The real ``title`` -> ``shape_error`` mapping is covered separately at
``tests/test_bilibili_api_gateway.py:831``.

Every test runs the shared protocol double from
``tests/fixtures/fake_bilibili_gateway.py`` over a real repository in a
temporary SQLite database, fully offline.  Test 4 additionally drives the real
``fetch-meta`` command path and reads its rendered output.
"""

from __future__ import annotations

import pytest

from bili_asr.cli import main
from bili_asr.services.metadata_ingest import MetadataIngestor
from bili_asr.sources.models import (
    GatewayRateLimited,
    GatewayShapeError,
    UserVideoPage,
    VideoPart,
    VideoSummary,
)
from bili_asr.storage import MetadataRepository, open_database
from fixtures.fake_bilibili_gateway import FakeGateway, fake_gateway_seam  # noqa: F401

MID = 23191782
FAILED_PAGE = 2

#: The documented bounded code a control-character title maps onto.
SHAPE_ERROR_CODE = "shape_error"


def _page(
    page_number: int,
    *summaries: VideoSummary,
    observed_total: int | None = None,
) -> UserVideoPage:
    """Build one validated page DTO owned by the requested user."""

    return UserVideoPage(
        mid=MID,
        page_number=page_number,
        videos=summaries,
        observed_total=observed_total,
    )


def _summary(bvid: str, *, title: str = "未明子讲座") -> VideoSummary:
    """Build one validated summary DTO owned by the requested user."""

    return VideoSummary(
        bvid=bvid,
        aid=1001,
        title=title,
        pubdate=1_725_859_200,
        mid=MID,
        author="未明子",
        pic="http://i1.hdslb.com/bfs/archive/cover.jpg",
        desc="哲学讲座简介",
        tid=124,
    )


def _part(bvid: str, page_index: int, *, cid: int = 2222) -> VideoPart:
    """Build one normalized part DTO for a page-1 video."""

    return VideoPart(
        bvid=bvid,
        page_index=page_index,
        cid=cid,
        title="第一部分",
        duration_ms=12_000,
    )


def _wedged_gateway(failed_page: int = FAILED_PAGE) -> FakeGateway:
    """Script one collected page, then one the gateway wedges terminally.

    The wedged page answers a **scripted** bounded ``GatewayShapeError`` — the
    documented page-boundary shape failure — rather than a raw validation
    error, so the fixture exercises the same arm production does.  It is
    field-independent: no normalizer change (``title``, ``description``, or
    any later one) can un-wedge it.  ``GatewayShapeError`` is not a
    ``GatewayRateLimited``, so the page and the run both read ``failed``.
    """

    gateway = FakeGateway()
    gateway.script_page(
        1, _page(1, _summary("BV1WEDGEAAAA"), observed_total=3)
    )
    gateway.script_parts("BV1WEDGEAAAA", (_part("BV1WEDGEAAAA", 0),))
    gateway.script_page(
        failed_page,
        GatewayShapeError(detail="video item is not normalizable"),
    )
    return gateway


def _ingestor(gateway: FakeGateway, repository: MetadataRepository) -> MetadataIngestor:
    return MetadataIngestor(gateway, repository)


def _page_rows(connection, run_id: str) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ? ORDER BY page_number",
            (run_id,),
        ).fetchall()
    ]


def _stop_on_the_failed_page(ingestor: MetadataIngestor) -> None:
    """Collect page 1 under a limit so the cursor rests parked on page 2."""

    first = ingestor.collect_user_pages(MID, page_limit=1)
    assert first.outcome == "limited"


def test_default_path_leaves_the_cursor_wedged(tmp_root):
    """Without the flag the cursor stays on the failed page (the status quo)."""

    gateway = _wedged_gateway()
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = _ingestor(gateway, repository)
        _stop_on_the_failed_page(ingestor)
        assert repository.read_cursor(MID).next_page == FAILED_PAGE

        result = ingestor.collect_user_pages(MID)

        assert result.outcome == "failed"
        assert result.error_code == SHAPE_ERROR_CODE
        # Console B's rule, preserved: a terminal failure keeps the cursor
        # where it was, so the page stays visible as the reason.
        assert repository.read_cursor(MID).next_page == FAILED_PAGE
        assert _page_rows(connection, result.run_id) == [
            (FAILED_PAGE, "failed", SHAPE_ERROR_CODE)
        ]
    finally:
        connection.close()


def test_flag_advances_the_cursor_past_the_failed_page(tmp_root):
    """With the flag the next resume starts past the wedge, and the gap stays.

    The cursor advance is asserted on a **fresh connection** as well: the
    ingestor writes it in its own committed transaction, so what a later
    ``--resume`` reads back from disk is the advanced page rather than the
    wedged one.
    """

    gateway = _wedged_gateway()
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = _ingestor(gateway, repository)
        _stop_on_the_failed_page(ingestor)

        result = ingestor.collect_user_pages(MID, skip_failed_page=True)

        # The run still failed, and still says so: the flag moves the cursor,
        # never the outcome.
        assert result.outcome == "failed"
        assert result.error_code == SHAPE_ERROR_CODE
        assert repository.read_cursor(MID).next_page == FAILED_PAGE + 1
        # The gap is recorded, not erased.
        assert _page_rows(connection, result.run_id) == [
            (FAILED_PAGE, "failed", SHAPE_ERROR_CODE)
        ]
    finally:
        connection.close()

    reopened = open_database(tmp_root)
    try:
        cursor = MetadataRepository(reopened).read_cursor(MID)
        assert cursor.next_page == FAILED_PAGE + 1
    finally:
        reopened.close()


def test_flag_still_stops_on_a_rate_limit(tmp_root):
    """A rate limit is transient: the flag must not skip past it."""

    gateway = FakeGateway()
    gateway.script_page(1, _page(1, _summary("BV1RATEAAAA"), observed_total=3))
    gateway.script_parts("BV1RATEAAAA", (_part("BV1RATEAAAA", 0),))
    gateway.script_page(
        FAILED_PAGE, GatewayRateLimited(detail="get_user_video_page")
    )
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        ingestor = _ingestor(gateway, repository)
        _stop_on_the_failed_page(ingestor)

        result = ingestor.collect_user_pages(MID, skip_failed_page=True)

        assert result.outcome == "risk_interrupted"
        assert result.error_code == "rate_limited"
        assert repository.read_cursor(MID).next_page == FAILED_PAGE
        assert _page_rows(connection, result.run_id) == [
            (FAILED_PAGE, "risk_interrupted", "rate_limited")
        ]
    finally:
        connection.close()


def test_runs_shows_the_gap(tmp_root, capsys, fake_gateway_seam):
    """After the skip, ``runs`` still renders the failed page's bounded code.

    The end-to-end check of the constraint that makes the flag honest: the
    escape hatch may not hide what it skipped.  The same scripted double is
    installed as the product adapter, so the whole ``fetch-meta`` command path
    runs offline through the real handler.
    """

    gateway = fake_gateway_seam
    gateway.script_page(1, _page(1, _summary("BV1WEDGEAAAA"), observed_total=3))
    gateway.script_parts("BV1WEDGEAAAA", (_part("BV1WEDGEAAAA", 0),))
    gateway.script_page(
        FAILED_PAGE, GatewayShapeError(detail="video item is not normalizable")
    )

    assert main(["fetch-meta", "--archive-root", tmp_root, "--limit-pages", "1"]) == 0
    capsys.readouterr()

    # A page genuinely failed: the exit code stays the terminal one.
    assert (
        main(
            [
                "fetch-meta",
                "--archive-root",
                tmp_root,
                "--resume",
                "--skip-failed-page",
            ]
        )
        == 2
    )
    failure_out, failure_err = capsys.readouterr()
    assert "outcome=failed" in failure_out
    assert SHAPE_ERROR_CODE in failure_err

    # The advance survives the command: the CLI closes its connection in a
    # ``finally``, so a cursor written outside a committed transaction would be
    # rolled back here and the next ``--resume`` would re-fail at the same page.
    reopened = open_database(tmp_root)
    try:
        cursor = MetadataRepository(reopened).read_cursor(MID)
        assert cursor.next_page == FAILED_PAGE + 1
    finally:
        reopened.close()

    assert main(["runs", "--archive-root", tmp_root]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    run_lines = [line for line in out.splitlines() if line.startswith("run ")]
    # Both runs are listed, and exactly one of them renders the failed page's
    # bounded code.  The assertion is order-independent on purpose: without a
    # deterministic clock both runs can land in the same started_at second, and
    # ``runs`` then breaks the tie by run_id rather than by which failed.
    assert len(run_lines) == 2
    gapped = [line for line in run_lines if f"error={SHAPE_ERROR_CODE}" in line]
    assert len(gapped) == 1, out
    assert "outcome=failed" in gapped[0]
    assert "pages=1" in gapped[0]


def test_failure_line_reports_the_advanced_cursor(tmp_root, capsys, fake_gateway_seam):
    """The failure line must not claim "unchanged" once the cursor moved.

    Under ``--skip-failed-page`` the cursor is committed one page past the
    failure, so the old unconditional ``cursor unchanged at page N`` asserted
    the opposite of what the store holds.  This is the regression guard: the
    line has to say ``advanced to page`` and must not say ``unchanged``.
    """

    gateway = fake_gateway_seam
    gateway.script_page(1, _page(1, _summary("BV1WEDGEAAAA"), observed_total=3))
    gateway.script_parts("BV1WEDGEAAAA", (_part("BV1WEDGEAAAA", 0),))
    gateway.script_page(
        FAILED_PAGE, GatewayShapeError(detail="video item is not normalizable")
    )

    assert main(["fetch-meta", "--archive-root", tmp_root, "--limit-pages", "1"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "fetch-meta",
                "--archive-root",
                tmp_root,
                "--resume",
                "--skip-failed-page",
            ]
        )
        == 2
    )
    failure_out, failure_err = capsys.readouterr()
    assert SHAPE_ERROR_CODE in failure_err
    assert f"advanced to page {FAILED_PAGE + 1}" in failure_err
    assert "unchanged" not in failure_err
    assert "unchanged" not in failure_out
