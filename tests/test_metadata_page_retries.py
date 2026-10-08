"""Bounded upload-list recovery, cursor preservation, and explicit rewind."""

from __future__ import annotations

import pytest

from bili_asr.cli.parser import build_parser
from bili_asr.cli.main import main
from bili_asr.config import MetadataConfigError, load_metadata_config
from bili_asr.services.metadata_ingest import MetadataIngestor
from bili_asr.sources.models import (
    GatewayAuthenticationError,
    GatewayNotFound,
    GatewayRateLimited,
    GatewayResponseError,
    GatewayShapeError,
    GatewayTransportError,
    UserVideoPage,
    VideoPart,
    VideoSummary,
)
from bili_asr.storage import MetadataRepository, open_database
from tests.fixtures.fake_bilibili_gateway import (
    MID,
    UPSTREAM_ERROR_TEXT,
    FakeGateway,
    FakeResponseCodeException,
    assert_leaks_no_markers,
    bilibili_api_seam,  # noqa: F401
    fake_gateway_seam,  # noqa: F401
    make_part_item,
    make_videos_response,
    make_vlist_item,
    persisted_row_text,
)


@pytest.fixture
def retry_waits(monkeypatch):
    """Await every cooldown without wall-clock delays, including gateway pacing."""

    waits = []

    async def wait(delay):
        waits.append(delay)

    monkeypatch.setattr("bili_asr.services.metadata_ingest.asyncio.sleep", wait)
    return waits


def _first_page(gateway):
    bvid = "BV1RECOVER01"
    summary = VideoSummary(
        bvid=bvid, aid=101, title="first", pubdate=100, mid=MID
    )
    gateway.script_page(
        1, UserVideoPage(mid=MID, page_number=1, videos=(summary,), observed_total=2)
    )
    gateway.script_parts(
        bvid, (VideoPart(bvid=bvid, page_index=0, cid=102, title="first", duration_ms=1000),)
    )


def test_cli_retries_rate_control_then_collects_the_same_page_once(
    tmp_root, bilibili_api_seam, retry_waits, capsys
):
    """Real adapter retains sequential per-video pacing after upload-list recovery."""

    script = bilibili_api_seam
    upload_calls = []

    def response(pn, ps):
        upload_calls.append((pn, ps, tuple(retry_waits)))
        if len(upload_calls) < 3:
            raise FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT)
        return make_videos_response(make_vlist_item(), count=1)

    script.videos_response = response
    script.parts_response = [make_part_item()]

    assert main([
        "fetch-meta", "--archive-root", tmp_root, "--limit-pages", "1",
        "--page-retries", "2",
    ]) == 0

    assert [call[:2] for call in upload_calls] == [(1, 30)] * 3
    assert [call[2] for call in upload_calls] == [(), (30,), (30, 60)]
    assert retry_waits[:2] == [30, 60]
    # Normal parts and tag pacing is still paid once per endpoint.
    assert len(retry_waits) == 4
    assert all(0.8 <= delay <= 1.6 for delay in retry_waits[2:])
    assert len(script.calls) == 5
    assert all("pn=1" in call for call in script.calls[:3])
    connection = open_database(tmp_root)
    try:
        repository = MetadataRepository(connection)
        assert repository.read_cursor(MID).next_page == 2
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        assert [tuple(row) for row in connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages"
        )] == [(1, "ok", None)]
        assert connection.execute("SELECT outcome FROM ingestion_runs").fetchone()[0] == "limited"
        assert repository.list_pending_parts() == []
        assert_leaks_no_markers(persisted_row_text(connection), context="retry records")
    finally:
        connection.close()
    output = capsys.readouterr()
    assert output.err == ""
    assert_leaks_no_markers(output.out, context="retry CLI output")


@pytest.mark.parametrize("failure", [GatewayRateLimited, GatewayTransportError])
def test_cli_exhausted_retries_keep_cursor_and_one_terminal_page(
    tmp_root, fake_gateway_seam, retry_waits, capsys, failure
):
    gateway = fake_gateway_seam
    _first_page(gateway)
    assert main(["fetch-meta", "--archive-root", tmp_root, "--limit-pages", "1"]) == 0
    connection = open_database(tmp_root)
    try:
        before = MetadataRepository(connection).read_cursor(MID)
    finally:
        connection.close()
    gateway.page_calls.clear()
    gateway.script_page(2, failure(detail=UPSTREAM_ERROR_TEXT))
    capsys.readouterr()

    assert main([
        "fetch-meta", "--archive-root", tmp_root, "--resume", "--page-retries", "3",
    ]) == 2

    assert gateway.page_calls == [(MID, 2, 30)] * 4
    assert retry_waits == [30, 60, 120]
    expected_outcome = "risk_interrupted" if failure is GatewayRateLimited else "failed"
    connection = open_database(tmp_root)
    try:
        assert MetadataRepository(connection).read_cursor(MID) == before
        assert [tuple(row) for row in connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages WHERE page_number = 2"
        )] == [(2, expected_outcome, failure().code)]
        assert connection.execute(
            "SELECT COUNT(*) FROM ingestion_runs WHERE outcome = ? AND finished_at IS NOT NULL",
            (expected_outcome,),
        ).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert_leaks_no_markers(persisted_row_text(connection), context="exhausted retry records")
    finally:
        connection.close()
    output = capsys.readouterr()
    assert "cursor unchanged at page 2" in output.err
    assert failure().code in output.err
    assert_leaks_no_markers(output.out + output.err, context="exhausted retry output")


def test_transport_recovery_waits_before_retrying_without_skipping(tmp_root, retry_waits):
    class TransientGateway(FakeGateway):
        async def get_user_video_page(self, mid, page_number, page_size=30):
            if not self.page_calls:
                self.page_calls.append((mid, page_number, page_size))
                raise GatewayTransportError(detail="temporary failure")
            assert retry_waits == [30]
            return await super().get_user_video_page(mid, page_number, page_size)

    gateway = TransientGateway()
    _first_page(gateway)
    connection = open_database(tmp_root)
    try:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(
            MID, page_limit=1, page_retries=1
        )
        assert result.outcome == "limited"
        assert result.page_count == 1
        assert result.video_count == result.part_count == 1
        assert gateway.page_calls == [(MID, 1, 30)] * 2
        assert gateway.parts_calls == ["BV1RECOVER01"]
        assert result.next_cursor.next_page == 2
    finally:
        connection.close()


def test_retry_backoff_ladder_caps_at_300_seconds(tmp_root, retry_waits):
    gateway = FakeGateway()
    gateway.script_page(1, GatewayRateLimited())
    connection = open_database(tmp_root)
    try:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(
            MID, page_retries=5
        )
        assert result.outcome == "risk_interrupted"
        assert gateway.page_calls == [(MID, 1, 30)] * 6
        assert retry_waits == [30, 60, 120, 240, 300]
    finally:
        connection.close()


@pytest.mark.parametrize("failure", [
    GatewayShapeError, GatewayResponseError, GatewayAuthenticationError, GatewayNotFound,
])
def test_non_transient_gateway_failure_is_not_retried(tmp_root, retry_waits, failure):
    gateway = FakeGateway()
    gateway.script_page(1, failure(detail="bounded"))
    connection = open_database(tmp_root)
    try:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(
            MID, page_retries=3
        )
        assert result.outcome == "failed"
        assert result.error_code == failure().code
        assert result.next_cursor is None
        assert gateway.page_calls == [(MID, 1, 30)]
        assert retry_waits == []
    finally:
        connection.close()


def test_default_still_stops_after_one_attempt(tmp_root, retry_waits):
    gateway = FakeGateway()
    gateway.script_page(1, GatewayRateLimited())
    connection = open_database(tmp_root)
    try:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(MID)
        assert result.outcome == "risk_interrupted"
        assert gateway.page_calls == [(MID, 1, 30)]
        assert retry_waits == []
    finally:
        connection.close()


def test_exhausted_rate_retries_are_never_skipped(tmp_root, retry_waits):
    gateway = FakeGateway()
    _first_page(gateway)
    gateway.script_page(2, GatewayRateLimited())
    connection = open_database(tmp_root)
    try:
        repository = MetadataRepository(connection)
        ingestor = MetadataIngestor(gateway, repository)
        ingestor.collect_user_pages(MID, page_limit=1)
        before = repository.read_cursor(MID)
        result = ingestor.collect_user_pages(MID, page_retries=1, skip_failed_page=True)
        assert result.outcome == "risk_interrupted"
        assert result.next_cursor == before
        assert retry_waits == [30]
        assert gateway.page_calls == [(MID, 1, 30), (MID, 2, 30), (MID, 2, 30)]
    finally:
        connection.close()


def test_page_retries_do_not_repeat_failed_per_video_fanout(tmp_root, retry_waits):
    gateway = FakeGateway()
    _first_page(gateway)
    gateway.script_parts("BV1RECOVER01", GatewayTransportError())
    connection = open_database(tmp_root)
    try:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(
            MID, page_limit=1, page_retries=3
        )
        assert result.outcome == "failed"
        assert result.error_code == "transport_error"
        assert result.video_count == result.part_count == 0
        assert result.next_cursor is None
        assert gateway.page_calls == [(MID, 1, 30)]
        assert gateway.parts_calls == ["BV1RECOVER01"]
        assert gateway.tag_calls == []
        assert retry_waits == []
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.parametrize(("value", "expected"), [
    (-1, ValueError), (6, ValueError), (True, TypeError), (1.5, TypeError), (None, TypeError),
])
def test_invalid_retry_bound_is_rejected_before_starting_a_run(value, expected):
    gateway = FakeGateway()
    connection = open_database(":memory:")
    try:
        with pytest.raises(expected, match="page_retries"):
            MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(
                MID, page_retries=value
            )
        assert gateway.page_calls == []
        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.parametrize("value", [-1, 6])
def test_cli_invalid_retry_bound_is_a_usage_error(tmp_root, capsys, value):
    assert main([
        "fetch-meta", "--archive-root", tmp_root, "--page-retries", str(value),
    ]) == 1
    assert "--page-retries must be an integer between 0 and 5" in capsys.readouterr().err


def test_config_rejects_boolean_retry_bound():
    args = build_parser().parse_args(["fetch-meta"])
    assert load_metadata_config(args).page_retries == 0
    args.page_retries = True
    with pytest.raises(MetadataConfigError, match="page-retries"):
        load_metadata_config(args)


def test_explicit_start_and_skip_can_rewind_a_persisted_cursor(
    tmp_root, fake_gateway_seam, capsys
):
    """A caller-requested rewind is durable, truthful, and visible in runs."""

    gateway = fake_gateway_seam
    gateway.script_page(40, UserVideoPage(mid=MID, page_number=40, videos=(), observed_total=None))
    assert main(["fetch-meta", "--archive-root", tmp_root, "--start-page", "40"]) == 0
    gateway.script_page(3, GatewayShapeError(detail="unreadable earlier page"))
    capsys.readouterr()
    assert main([
        "fetch-meta", "--archive-root", tmp_root, "--start-page", "3", "--skip-failed-page",
    ]) == 2
    assert "cursor set to page 4" in capsys.readouterr().err
    connection = open_database(tmp_root)
    try:
        assert MetadataRepository(connection).read_cursor(MID).next_page == 4
        assert [tuple(row) for row in connection.execute(
            "SELECT page_number, outcome, error_code FROM ingestion_pages WHERE page_number = 3"
        )] == [(3, "failed", "shape_error")]
    finally:
        connection.close()
    gateway.script_page(4, UserVideoPage(mid=MID, page_number=4, videos=(), observed_total=None))
    assert main(["fetch-meta", "--archive-root", tmp_root, "--resume"]) == 0
    assert gateway.page_calls == [(MID, 40, 30), (MID, 3, 30), (MID, 4, 30)]


def test_help_explains_retries_and_explicit_rewind(capsys):
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["fetch-meta", "--help"])
    assert exit_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "--page-retries" in help_text
    assert "30/60/120/240/300" in help_text
    assert "may move it backwards, including with --skip-failed-page" in help_text
