"""Dynamic offset verification and bounded necessary-operation recovery."""

import pytest

from bili_asr.cli import main
from bili_asr.request_budget import RequestScheduler
from bili_asr.services.metadata_ingest import MetadataIngestor
from bili_asr.sources.models import (
    GatewayAuthenticationError, GatewayNotFound, GatewayRateLimited,
    GatewayShapeError, GatewayTransportError,
)
from bili_asr.storage import MetadataRepository, open_database
from tests.fixtures.fake_bilibili_gateway import (
    FakeGateway, fake_gateway_seam, bilibili_api_seam,
    make_videos_response, make_vlist_item, make_part_item,
)
from tests.test_metadata_ingest import _page, _summary, _part, MID


@pytest.fixture
def archive(tmp_path):
    connection = open_database(tmp_path)
    repository = MetadataRepository(connection)
    gateway = FakeGateway()
    for index, bvid in enumerate(("BV_A", "BV_B", "BV_C", "BV_NEW", "BV_X"), 1):
        gateway.script_parts(bvid, (_part(bvid, 0, cid=index),))
        gateway.script_page(index, _page(index, _summary(bvid, aid=index)))
    yield connection, repository, gateway, MetadataIngestor(gateway, repository)
    connection.close()


@pytest.fixture
def waits(monkeypatch):
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr("bili_asr.services.metadata_ingest.asyncio.sleep", sleep)
    return delays


@pytest.mark.parametrize("new_prefix", [("BV_B",), ("BV_NEW",), ("BV_C",), ()])
def test_changed_resume_prefix_requires_homepage_enumeration(archive, new_prefix):
    connection, repository, gateway, ingestor = archive
    ingestor.collect_user_pages(MID, page_limit=1)
    before = repository.read_cursor(MID)
    gateway.script_page(1, _page(1, *(_summary(bvid, aid=10) for bvid in new_prefix)))
    gateway.parts_calls.clear()
    result = ingestor.collect_user_pages(MID, skip_failed_page=True)
    assert result.outcome == "failed"
    assert result.error_code == "metadata_resume_requires_reenumeration"
    assert result.failure_operation == "resume_prefix"
    assert repository.read_cursor(MID) == before
    assert gateway.parts_calls == []
    assert [row[0] for row in connection.execute("SELECT bvid FROM videos")] == ["BV_A"]
    # Full re-enumeration discovers moved B and preserves historical A.
    gateway.script_page(1, _page(1, _summary("BV_B", aid=2)))
    gateway.script_page(2, _page(2, _summary("BV_C", aid=3)))
    gateway.script_page(3, _page(3))
    recovered = ingestor.collect_user_pages(MID, incremental=True)
    assert recovered.outcome == "complete"
    assert {row[0] for row in connection.execute("SELECT bvid FROM videos")} == {"BV_A", "BV_B", "BV_C"}


def test_checks_earlier_pages_even_when_last_boundary_is_unchanged(archive):
    _, repository, gateway, ingestor = archive
    ingestor.collect_user_pages(MID, page_limit=2)
    before = repository.read_cursor(MID)
    gateway.script_page(1, _page(1, _summary("BV_X", aid=5)))
    # Page 2 (B) is unchanged; checking it alone would miss X.
    result = ingestor.collect_user_pages(MID)
    assert result.error_code == "metadata_resume_requires_reenumeration"
    assert repository.read_cursor(MID) == before


def test_reordered_prefix_and_completed_cursor_are_checked(archive):
    _, repository, gateway, ingestor = archive
    gateway.script_page(1, _page(1, _summary("BV_A", aid=1), _summary("BV_B", aid=2)))
    gateway.script_page(2, _page(2))
    assert ingestor.collect_user_pages(MID).outcome == "complete"
    before = repository.read_cursor(MID)
    gateway.script_page(1, _page(1, _summary("BV_B", aid=2), _summary("BV_A", aid=1)))
    result = ingestor.collect_user_pages(MID)
    assert result.error_code == "metadata_resume_requires_reenumeration"
    assert repository.read_cursor(MID) == before


def test_repeated_nonempty_page_remains_limited_and_deduplicated(archive):
    connection, _, gateway, ingestor = archive
    gateway.script_page(2, _page(2, _summary("BV_A", aid=1)))
    result = ingestor.collect_user_pages(MID, page_limit=2)
    assert result.outcome == "limited"
    assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1


def test_unchanged_prefix_only_relists_and_resumes(archive):
    _, repository, gateway, ingestor = archive
    ingestor.collect_user_pages(MID, page_limit=2)
    gateway.page_calls.clear()
    gateway.parts_calls.clear()
    gateway.script_page(3, _page(3))
    result = ingestor.collect_user_pages(MID)
    assert result.outcome == "complete"
    assert result.page_count == 1
    assert gateway.page_calls == [(MID, number, 30) for number in (1, 2, 3)]
    assert gateway.parts_calls == []
    assert repository.read_cursor(MID).next_page == 3


def test_duplicate_rows_use_last_stored_position_for_prefix(archive):
    _, _, gateway, ingestor = archive
    gateway.script_page(1, _page(1, _summary("BV_A", aid=1), _summary("BV_B", aid=2), _summary("BV_A", aid=1)))
    ingestor.collect_user_pages(MID, page_limit=1)
    gateway.script_page(2, _page(2))
    assert ingestor.collect_user_pages(MID).outcome == "complete"


@pytest.mark.parametrize("failure", [GatewayAuthenticationError, GatewayRateLimited, GatewayTransportError])
def test_resume_verification_failure_never_skips_or_advances(archive, failure):
    _, repository, gateway, ingestor = archive
    ingestor.collect_user_pages(MID, page_limit=1)
    before = repository.read_cursor(MID)
    gateway.script_page(1, failure())
    result = ingestor.collect_user_pages(MID, skip_failed_page=True)
    assert result.error_code == failure().code
    assert result.failure_operation == "resume_prefix"
    assert repository.read_cursor(MID) == before


def test_skipped_prefix_cannot_claim_complete(archive):
    _, repository, gateway, ingestor = archive
    gateway.script_page(2, GatewayShapeError())
    ingestor.collect_user_pages(MID, skip_failed_page=True)
    before = repository.read_cursor(MID)
    assert before.next_page == 3
    gateway.page_calls.clear()
    result = ingestor.collect_user_pages(MID)
    assert result.error_code == "metadata_resume_requires_reenumeration"
    assert repository.read_cursor(MID) == before
    assert gateway.page_calls == []


def test_cli_changed_prefix_explains_incremental_recovery(tmp_path, fake_gateway_seam, capsys):
    gateway = fake_gateway_seam
    gateway.script_page(1, _page(1, _summary("BV_A", aid=1)))
    gateway.script_parts("BV_A", (_part("BV_A", 0),))
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--limit-pages", "1"]) == 0
    capsys.readouterr()
    gateway.script_page(1, _page(1))
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--resume", "--skip-failed-page"]) == 2
    err = capsys.readouterr().err
    assert "--incremental" in err and "cursor unchanged" in err
    assert "was skipped" not in err


@pytest.mark.parametrize("operation", ["parts", "summary"])
def test_transient_necessary_read_recovers_without_repeating_list(archive, waits, operation):
    _, _, gateway, ingestor = archive
    if operation == "summary":
        gateway.script_page(1, _page(1, _summary("BV_A", aid=None)))
    calls = []
    original = gateway.get_video_parts if operation == "parts" else gateway.get_completed_video_summary

    async def read(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise GatewayTransportError()
        return await original(*args, **kwargs)

    if operation == "parts":
        gateway.get_video_parts = read
    else:
        gateway.script_completion("BV_A", _summary("BV_A", aid=1))
        gateway.get_completed_video_summary = read
    result = ingestor.collect_user_pages(MID, page_limit=1, operation_retries=1)
    assert result.outcome == "limited"
    assert len(calls) == 2 and waits == [30]
    assert gateway.page_calls == [(MID, 1, 30)]
    assert result.video_count == result.part_count == 1


@pytest.mark.parametrize("failure", [
    GatewayAuthenticationError(), GatewayShapeError(), GatewayNotFound(), GatewayRateLimited(),
    GatewayTransportError(code="request_budget_exhausted"),
])
def test_non_transient_operation_stops_without_retry(archive, waits, failure):
    connection, repository, gateway, ingestor = archive
    gateway.script_parts("BV_A", failure)
    result = ingestor.collect_user_pages(MID, page_limit=1, operation_retries=5)
    assert result.error_code == failure.code
    assert gateway.parts_calls == ["BV_A"] and waits == []
    assert repository.read_cursor(MID) is None
    assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0


def test_exhausted_operations_keep_one_final_failure_and_no_half_page(archive, waits):
    connection, repository, gateway, ingestor = archive
    gateway.script_page(1, _page(1, _summary("BV_A", aid=1), _summary("BV_B", aid=2)))
    gateway.script_parts("BV_B", GatewayTransportError())
    result = ingestor.collect_user_pages(MID, page_limit=1, operation_retries=5)
    assert result.error_code == "transport_error"
    assert gateway.parts_calls == ["BV_A"] + ["BV_B"] * 6
    assert waits == [30, 60, 120, 240, 300]
    assert result.failure_bvid == "BV_B" and result.failure_operation == "parts"
    assert repository.read_cursor(MID) is None
    assert connection.execute("SELECT COUNT(*) FROM ingestion_pages").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0


def test_operation_exhaustion_keeps_previous_committed_cursor(archive, waits):
    connection, repository, gateway, ingestor = archive
    ingestor.collect_user_pages(MID, page_limit=1)
    before = repository.read_cursor(MID)
    gateway.script_parts("BV_B", GatewayTransportError())
    result = ingestor.collect_user_pages(MID, page_limit=1, operation_retries=2)
    assert result.error_code == "transport_error"
    assert repository.read_cursor(MID) == before
    assert {row[0] for row in connection.execute("SELECT bvid FROM videos")} == {"BV_A"}
    assert waits == [30, 60]


@pytest.mark.parametrize("budget", [1, 2])
def test_gateway_operation_retries_consume_shared_request_budget(tmp_path, bilibili_api_seam, waits, budget):
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    script = bilibili_api_seam
    script.videos_response = make_videos_response(make_vlist_item(), count=1)
    script.parts_error = RuntimeError("transient")
    scheduler = RequestScheduler(max_requests=budget, sleeper=lambda delay: _no_wait(delay))
    gateway = BilibiliApiGateway(request_scheduler=scheduler, _sleeper=_no_wait)
    connection = open_database(tmp_path)
    try:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(
            MID, page_limit=1, operation_retries=5)
        assert result.error_code == "request_budget_exhausted"
        assert result.request_metrics["request_count"] == budget
        assert result.next_cursor is None
    finally:
        connection.close()


async def _no_wait(delay):
    pass


def test_shared_deadline_stops_retry_wait_without_another_request(archive):
    _, _, gateway, ingestor = archive
    ticks = [0.0]

    async def advance(delay):
        ticks[0] += delay

    scheduler = RequestScheduler(total_seconds=20, clock=lambda: ticks[0], sleeper=advance)
    gateway.request_scheduler = scheduler
    gateway.script_parts("BV_A", GatewayTransportError())
    original = gateway.get_video_parts

    async def parts(*args, **kwargs):
        return await scheduler.run("parts", lambda: original(*args, **kwargs))

    gateway.get_video_parts = parts
    result = ingestor.collect_user_pages(MID, page_limit=1, operation_retries=5)
    assert result.error_code == "request_budget_exhausted"
    assert gateway.parts_calls == ["BV_A"]
    assert scheduler.metrics()["request_count"] == 1
    assert ticks == [0.0]


def test_real_gateway_transient_parts_recovery_preserves_attempt_metrics(tmp_path, bilibili_api_seam):
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    script = bilibili_api_seam
    script.videos_response = make_videos_response(make_vlist_item(), count=1)
    calls = []

    def parts(bvid):
        calls.append(bvid)
        if len(calls) == 1:
            raise RuntimeError("temporary transport failure")
        return [make_part_item()]

    script.parts_response = parts
    scheduler = RequestScheduler(max_requests=4, sleeper=_no_wait)
    gateway = BilibiliApiGateway(request_scheduler=scheduler, _sleeper=_no_wait)
    connection = open_database(tmp_path)
    try:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(
            MID, page_limit=1, operation_retries=1)
        assert result.outcome == "limited"
        assert result.request_metrics["operations"] == {"get_user_video_page": 1, "get_video_parts": 2, "get_video_tags": 1}
        assert result.request_metrics["failures"] == {"get_video_parts": 1}
        assert result.video_count == result.part_count == 1
    finally:
        connection.close()


def test_cli_operation_retry_option_reaches_gateway(tmp_path, bilibili_api_seam, waits, capsys):
    script = bilibili_api_seam
    script.videos_response = make_videos_response(make_vlist_item(), count=1)
    calls = []

    def parts(bvid):
        calls.append(bvid)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return [make_part_item()]

    script.parts_response = parts
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--limit-pages", "1",
                 "--operation-retries", "1"]) == 0
    output = capsys.readouterr()
    assert "requests: attempted=4" in output.out
    assert len(calls) == 2 and 30 in waits
    assert output.err == ""


@pytest.mark.parametrize("retries", [-1, 6, True, 1.5])
def test_invalid_operation_retry_bound_rejected_before_network(archive, retries):
    _, _, gateway, ingestor = archive
    with pytest.raises((TypeError, ValueError)):
        ingestor.collect_user_pages(MID, operation_retries=retries)
    assert gateway.page_calls == []


@pytest.mark.parametrize("retries", ["-1", "6"])
def test_cli_rejects_invalid_operation_retry_bound(tmp_path, retries, capsys):
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--operation-retries", retries]) == 1
    assert "--operation-retries" in capsys.readouterr().err
    assert not (tmp_path / "archive.db").exists()


def test_targeted_refresh_does_not_silently_ignore_operation_retries(tmp_path, capsys):
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--bvid", "BV_A",
                 "--operation-retries", "1"]) == 1
    assert "paginated collection" in capsys.readouterr().err
