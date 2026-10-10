"""Source facts, targeted refresh and incremental discovery through real storage."""
from dataclasses import replace
import asyncio
import json
import sqlite3

import pytest

from bili_asr.formatting import pubdate_iso
from bili_asr.metadata_policy import MetadataFieldObservation, MetadataRefreshPolicy
from bili_asr.platform_identity import ContentRef
from bili_asr.request_budget import RequestScheduler
from bili_asr.services.metadata_ingest import MetadataIngestor
from bili_asr.services.metadata_refresh import MetadataRefreshService
from bili_asr.source_metadata import SourceMetadataSnapshot
from bili_asr.sources.models import GatewayTransportError, TagRead, VideoMetadataRead, VideoPart, VideoSummary
from bili_asr.storage import MetadataRepository, open_database
from bili_asr.storage.models import VideoDetailRecord
from tests.test_workflow_control_plane import _seed_part
from tests.fixtures.fake_bilibili_gateway import FakeGateway
from tests.test_metadata_ingest import _page, _summary, _part, MID
from tests.fixtures.fake_bilibili_gateway import bilibili_api_seam  # noqa: F401 - register the provider fixture
from tests.fixtures.fake_bilibili_gateway import make_detail_response, make_part_item


@pytest.fixture
def database(tmp_path):
    connection = open_database(tmp_path)
    _seed_part(connection)
    yield connection
    connection.close()


def test_iso_date_unknown_and_timezone_border():
    assert pubdate_iso(0) is None and pubdate_iso(None) is None
    assert pubdate_iso(1704038400) == "2023-12-31T16:00:00Z"
    with pytest.raises(TypeError):
        pubdate_iso(True)


def test_metadata_codec_retains_raw_unknown_and_rejects_secrets():
    snapshot = SourceMetadataSnapshot(ContentRef("bilibili", "BVtest", 0), "视频", "123", "作者", 0, 4,
                                      cover_url="https://i1.hdslb.com/bfs/archive/cover.jpg")
    data = snapshot.to_dict()
    assert data["pubdateUnix"] == 0 and data["sourcePublishedAt"] is None
    assert SourceMetadataSnapshot.from_dict(data) == snapshot
    for url in ("https://evil.invalid/picture", "https://i1.hdslb.com/picture?token=secret", "http://i1.hdslb.com/picture"):
        assert replace(snapshot, cover_url=url).to_dict()["coverUrl"] is None
    with pytest.raises(ValueError):
        SourceMetadataSnapshot.from_dict({**data, "sourcePublishedAt": "1970-01-01T00:00:00Z"})


@pytest.mark.parametrize("change", [
    {"title": None}, {"title": 4}, {"tags": None}, {"tags": "one"},
    {"tags": ["repeat", "repeat"]}, {"tags": [None]}, {"partIndex": True},
    {"creatorName": "control\x00name"}, {"title": "multi\nline"}, {"description": "bad\ud800"},
    {"title": "C1\u0085name"}, {"description": "C1\u009fname"}, {"externalVideoId": "BV\u0085test"},
    {"pubdateUnix": True}, {"aid": 0}, {"durationMs": -1},
    {"coverUrl": "https://i1.hdslb.com/image?token=private"},
    {"unexpected": None},
])
def test_metadata_decoder_rejects_external_bad_shape_with_value_error(change):
    value = SourceMetadataSnapshot(ContentRef("bilibili", "BVtest", 0), "视频", None, None, None, None).to_dict()
    with pytest.raises(ValueError):
        SourceMetadataSnapshot.from_dict({**value, **change})


@pytest.mark.parametrize("url", [
    "https://evil.invalid\\x.hdslb.com/image", "https://i1.hdslb.com\\@evil.invalid/image",
    "https://i1.hdslb.com/image with space", "https://i1.hdslb.com/\u00a0image",
    "https://foo..hdslb.com/image", "https://-bad.hdslb.com/image",
    "https://\u0131.hdslb.com/image", "https://i1.hdslb.com/image?token=private",
    "https://i1.hdslb.com/image#private", "https://user:private@i1.hdslb.com/image",
])
def test_cover_constructor_redacts_unsafe_url_and_external_decoder_rejects_it(url):
    snapshot = SourceMetadataSnapshot(ContentRef("bilibili", "BVtest", 0), "视频", None, None, None, None)
    assert replace(snapshot, cover_url=url).cover_url is None
    assert replace(snapshot, cover_url=url).to_dict()["coverUrl"] is None
    with pytest.raises(ValueError):
        SourceMetadataSnapshot.from_dict({**snapshot.to_dict(), "coverUrl": url})


class Gateway:
    def __init__(self, *, parts=None, error=None):
        self.calls, self.parts, self.error = [], parts, error

    async def get_video_metadata(self, bvid):
        self.calls.append(("metadata", bvid))
        if self.error:
            raise self.error
        summary = VideoSummary("BVtest", None, "刷新视频", 1704038400, 1, "作者", desc="新简介")
        return VideoMetadataRead(summary, (
            MetadataFieldObservation("title", "present", summary.title),
            MetadataFieldObservation("pubdate", "present", summary.pubdate),
            MetadataFieldObservation("aid", "missing"),
            MetadataFieldObservation("pic", "missing"),
            MetadataFieldObservation("desc", "present", summary.desc),
            MetadataFieldObservation("tid", "missing"),
        ), self.parts)

    async def get_video_parts(self, bvid, video_title_fallback=""):
        self.calls.append(("parts", bvid))
        return (VideoPart(bvid, 0, 1, "刷新分P", 1000),)

    async def read_video_tags(self, bvid):
        self.calls.append(("tags", bvid))
        return TagRead(())


def test_target_refresh_changes_pubdate_preserves_missing_fields_and_cursor(database):
    repository = MetadataRepository(database)
    with repository.transaction():
        repository.upsert_video_details(VideoDetailRecord("BVtest", "https://i1.hdslb.com/old.jpg", "旧简介", 7, 2))
    before_cursor = list(database.execute("SELECT * FROM ingestion_cursors"))
    gateway = Gateway(parts=(VideoPart("BVtest", 0, 1, "新版P", 2000),))
    outcomes = MetadataRefreshService(gateway, repository).refresh(("BVtest",))
    assert [outcome.state for outcome in outcomes] == ["present", "present", "present", "empty"]
    assert gateway.calls == [("metadata", "BVtest"), ("tags", "BVtest")]
    assert tuple(database.execute('SELECT pic,"desc",tid FROM video_details').fetchone()) == ("https://i1.hdslb.com/old.jpg", "新简介", 7)
    metadata = repository.read_source_metadata(1).to_dict()
    assert metadata["sourcePublishedAt"] == "2023-12-31T16:00:00Z"
    assert metadata["partTitle"] == "新版P" and metadata["durationMs"] == 2000
    assert list(database.execute("SELECT * FROM ingestion_cursors")) == before_cursor


def test_target_refresh_failure_and_cid_change_preserve_prior_facts(database):
    repository = MetadataRepository(database)
    original = tuple(database.execute("SELECT title,pubdate FROM videos").fetchone())
    assert MetadataRefreshService(Gateway(error=GatewayTransportError()), repository).refresh(
        ("BVtest",), operations=("summary",))[0].error_code == "transport_error"
    assert tuple(database.execute("SELECT title,pubdate FROM videos").fetchone()) == original
    class Changed(Gateway):
        async def get_video_parts(self, bvid, video_title_fallback=""):
            return (VideoPart(bvid, 0, 999, "不同内容", 8000),)
    outcome = MetadataRefreshService(Changed(), repository).refresh(("BVtest",), operations=("parts",))[0]
    assert outcome.error_code == "metadata_part_identity_conflict"
    assert database.execute("SELECT cid FROM video_parts").fetchone()[0] == 1


def test_explicit_empty_retracts_but_missing_preserves_fields(database):
    repository = MetadataRepository(database)
    with repository.transaction():
        repository.upsert_video_details(VideoDetailRecord("BVtest", "https://i1.hdslb.com/old.jpg", "旧简介", 7, 2))
        repository.observe_video_details(VideoDetailRecord("BVtest", None, None, None, 5), (
            MetadataFieldObservation("pic", "missing"), MetadataFieldObservation("desc", "empty"),
            MetadataFieldObservation("tid", "unavailable"),))
    assert tuple(database.execute('SELECT pic,"desc",tid FROM video_details').fetchone()) == ("https://i1.hdslb.com/old.jpg", None, 7)


def test_incremental_from_page_one_after_completed_cursor_and_reuse(tmp_path):
    connection = open_database(tmp_path)
    repository = MetadataRepository(connection)
    first = FakeGateway()
    first.script_page(1, _page(1, _summary("BVold", aid=10)))
    first.script_parts("BVold", (_part("BVold", 0),))
    first.script_page(2, _page(2))
    MetadataIngestor(first, repository).collect_user_pages(MID)
    assert repository.read_cursor(MID).next_page == 2
    original_part_stamp = connection.execute("SELECT updated_at FROM video_parts WHERE bvid='BVold'").fetchone()[0]
    next_gateway = FakeGateway()
    next_gateway.script_page(1, _page(1, _summary("BVnew", aid=11), _summary("BVold", aid=10)))
    next_gateway.script_parts("BVnew", (_part("BVnew", 0, cid=3333),))
    next_gateway.script_page(2, _page(2))
    result = MetadataIngestor(next_gateway, repository).collect_user_pages(
        MID, incremental=True, refresh_policy=MetadataRefreshPolicy("missing"))
    assert result.outcome == "complete" and result.reused_operation_count == 2
    assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
    assert next_gateway.parts_calls == ["BVnew"] and next_gateway.tag_calls == ["BVnew"]
    assert connection.execute("SELECT updated_at FROM video_parts WHERE bvid='BVold'").fetchone()[0] == original_part_stamp
    connection.close()


def test_request_budget_timeout_and_cancellation_are_bounded():
    async def verify():
        budget = RequestScheduler(max_requests=1, request_seconds=0.01)
        assert await budget.run("summary", lambda: asyncio.sleep(0, result=4)) == 4
        with pytest.raises(GatewayTransportError, match="request_budget_exhausted"):
            await budget.run("parts", lambda: asyncio.sleep(0))
        timeout = RequestScheduler(request_seconds=0.01)
        with pytest.raises(GatewayTransportError, match="request_timeout"):
            await timeout.run("details", lambda: asyncio.sleep(60))
        task = asyncio.create_task(RequestScheduler().run("parts", lambda: asyncio.sleep(60)))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(verify())


def test_v1_failed_recovery_explicitly_requires_new_observation_contract(database):
    with pytest.raises(ValueError, match="universal-v2"):
        MetadataRefreshService(Gateway(), MetadataRepository(database)).failed_targets()


@pytest.fixture
def v2_database(tmp_path):
    from bili_asr.storage.archive_contracts import bootstrap_contract
    connection = sqlite3.connect(tmp_path / "archive.db")
    connection.row_factory = sqlite3.Row
    bootstrap_contract(connection)
    _seed_part(connection)
    yield connection
    connection.close()


def test_v2_failed_refresh_is_durable_targeted_and_retains_successful_metadata(v2_database):
    repository = MetadataRepository(v2_database)
    service = MetadataRefreshService(Gateway(error=GatewayTransportError()), repository)
    assert service.refresh(("BVtest",), operations=("summary",))[0].error_code == "transport_error"
    assert service.failed_targets() == (("BVtest", "summary"),)
    assert v2_database.execute("SELECT title FROM videos").fetchone()[0] == "test"
    repaired = MetadataRefreshService(Gateway(), repository)
    assert repaired.refresh(("BVtest",), operations=("summary",))[0].state == "present"
    assert repaired.failed_targets() == ()
    row = v2_database.execute("SELECT state,value_json,last_success_at FROM source_metadata_observations WHERE field='pubdate'").fetchone()
    assert row[0] == "present" and json.loads(row[1]) == 1704038400 and row[2] > 0
    assert v2_database.execute("SELECT COUNT(*) FROM metadata_refresh_attempts").fetchone()[0] == 2


def test_failed_new_video_page_replay_preserves_a_later_successful_cursor(v2_database):
    repository = MetadataRepository(v2_database)
    failed = FakeGateway()
    failed.script_page(1, _page(1, _summary("BVfailed", aid=20)))
    failed.script_parts("BVfailed", GatewayTransportError())
    result = MetadataIngestor(failed, repository).collect_user_pages(MID, page_limit=1)
    assert result.outcome == "failed" and result.failure_bvid == "BVfailed"
    assert v2_database.execute("SELECT 1 FROM videos WHERE bvid='BVfailed'").fetchone() is None
    assert MetadataRefreshService(failed, repository).failed_targets() == (("BVfailed", "parts"),)
    detail = json.loads(v2_database.execute("SELECT details_json FROM metadata_refresh_attempts").fetchone()[0])
    assert detail["mid"] == MID and detail["page_number"] == 1

    later = FakeGateway()
    later.script_page(2, _page(2, _summary("BVlater", aid=21)))
    later.script_parts("BVlater", (_part("BVlater", 0, cid=21),))
    MetadataIngestor(later, repository).collect_user_pages(MID, start_page=2, page_limit=1)
    cursor_before = tuple(v2_database.execute("SELECT * FROM ingestion_cursors WHERE mid=?", (MID,)).fetchone())
    assert repository.read_cursor(MID).next_page == 3

    repaired = FakeGateway()
    repaired.script_page(1, _page(1, _summary("BVfailed", aid=20)))
    repaired.script_parts("BVfailed", (_part("BVfailed", 0, cid=20),))
    service = MetadataRefreshService(repaired, repository)
    assert service.retry_failed()[0].state == "present"
    assert repaired.page_calls == [(MID, 1, 30)]
    assert service.failed_targets() == ()
    assert tuple(v2_database.execute("SELECT * FROM ingestion_cursors WHERE mid=?", (MID,)).fetchone()) == cursor_before
    assert v2_database.execute("SELECT COUNT(*) FROM videos WHERE bvid IN ('BVfailed','BVlater')").fetchone()[0] == 2


def test_failed_replay_with_changed_page_retains_explicit_unresolved_failure(v2_database):
    repository = MetadataRepository(v2_database)
    with repository.transaction():
        repository.record_metadata_attempt("BVdisappeared", "parts", "unavailable", 1, 1, "transport_error",
                                           details={"mid": MID, "page_number": 1})
    gateway = FakeGateway()
    gateway.script_page(1, _page(1))
    service = MetadataRefreshService(gateway, repository)
    outcome = service.retry_failed()[0]
    assert outcome.state == "unavailable" and outcome.error_code == "metadata_retry_context_changed"
    assert service.failed_targets() == (("BVdisappeared", "parts"),)


def test_metadata_attempt_diagnostics_refuse_capability_values(v2_database):
    repository = MetadataRepository(v2_database)
    with pytest.raises(ValueError):
        repository.record_metadata_attempt("BVtest", "parts", "unavailable", 1, 1,
                                           "transport_error", details={"url": "https://private.invalid"})


def test_v2_youtube_metadata_has_real_identity_and_unknown_source_date(v2_database):
    from bili_asr.storage.sources import SourceRepository, SourceVideoMetadata
    with v2_database:
        part_id = SourceRepository(v2_database).upsert_video(SourceVideoMetadata(
            ContentRef("youtube", "aBcdEfGhIjK"), "YouTube源视频", 2000,
            creator_external_id="UC_example", creator_name="真实作者", observed_at=9))
    data = MetadataRepository(v2_database).read_source_metadata(part_id).to_dict()
    assert data["platform"] == "youtube" and data["externalVideoId"] == "aBcdEfGhIjK"
    assert data["pubdateUnix"] is None and data["sourcePublishedAt"] is None
    assert data["creatorId"] == "UC_example" and data["metadataObservedAt"] == 9


@pytest.mark.parametrize("fixture_name", ["database", "v2_database"])
def test_source_metadata_many_matches_single_reads_and_rejects_incomplete_batches(request, fixture_name):
    connection = request.getfixturevalue(fixture_name)
    repository = MetadataRepository(connection)
    with connection:
        connection.execute("INSERT INTO video_details VALUES ('BVtest',?,?,?,?)",
                           ("https://i1.hdslb.com/cover.jpg", "简介\n第二行", 17, 6))
        connection.executemany("INSERT INTO video_tags VALUES ('BVtest',?,?,'old')",
                               ((3, "第二"), (1, "第一"), (2, "第一")))
        connection.execute("INSERT INTO video_parts(bvid,page_index,cid,title,duration_ms,processing_status,created_at,updated_at) "
                           "VALUES ('BVtest',1,2,'second',2000,'metadata_collected',1,1)")
    assert repository.read_source_metadata_many((2, 1, 2)) == {
        2: repository.read_source_metadata(2), 1: repository.read_source_metadata(1),
    }
    assert repository.read_source_metadata_many((1,))[1].tags == ("第一", "第二")
    assert repository.read_source_metadata_many(()) == {}
    for identities in ((1, 999), (True,), (0,), ("1",), (1,) * 257):
        with pytest.raises(ValueError):
            repository.read_source_metadata_many(identities)
    assert not connection.in_transaction


def test_universal_projection_batches_source_facts_and_preserves_both_platforms(v2_database, tmp_path, monkeypatch):
    from bili_asr.services import workflow_projection
    from bili_asr.storage.sources import SourceRepository, SourceVideoMetadata
    with v2_database:
        v2_database.execute("UPDATE videos SET title='源标题',pubdate=1704038400,updated_at=8 WHERE bvid='BVtest'")
        v2_database.execute("UPDATE bilibili_users SET display_name='源作者' WHERE mid=1")
        v2_database.execute("INSERT INTO video_details VALUES ('BVtest',?,?,?,?)",
                            ("https://i1.hdslb.com/cover.jpg", "简介", 17, 8))
        v2_database.execute("INSERT INTO video_tags VALUES ('BVtest',1,'源标签','old')")
        for index in range(1, 8):
            v2_database.execute("INSERT INTO video_parts(bvid,page_index,cid,title,duration_ms,processing_status,created_at,updated_at) "
                                "VALUES ('BVtest',?,?,?,1000,'metadata_collected',1,1)", (index, index + 1, f"P{index}"))
        for index, external_id in enumerate(("aBcdEfGhIjK", "bBcdEfGhIjK", "cBcdEfGhIjK", "dBcdEfGhIjK")):
            SourceRepository(v2_database).upsert_video(SourceVideoMetadata(
                ContentRef("youtube", external_id), f"YouTube {index}", 2000,
                creator_external_id="UC_example", creator_name="YT作者", observed_at=9))
    statements = []
    connect = workflow_projection.open_archive_connection

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(workflow_projection, "_PART_READ_BATCH_SIZE", 4)
    monkeypatch.setattr(workflow_projection, "open_archive_connection", traced_connect)
    records = workflow_projection.workflow_records(tmp_path, verify_artifacts=False)
    assert len(records) == 12
    bili = records["BVtest:p0"]["sourceMetadata"]
    assert bili["title"] == "源标题" and bili["creatorId"] == "1" and bili["creatorName"] == "源作者"
    assert bili["pubdateUnix"] == 1704038400 and bili["sourcePublishedAt"] == "2023-12-31T16:00:00Z"
    assert bili["description"] == "简介" and bili["categoryId"] == 17 and bili["tags"] == ["源标签"]
    assert bili["aid"] == 1 and bili["coverUrl"] == "https://i1.hdslb.com/cover.jpg"
    youtube = records["youtube:aBcdEfGhIjK:p0"]
    assert youtube["bvid"] is None and youtube["cid"] is None
    assert youtube["sourceMetadata"]["creatorName"] == "YT作者"
    assert youtube["pubdateUnix"] is None and youtube["sourcePublishedAt"] is None
    assert youtube["sourceMetadata"]["metadataObservedAt"] == 9
    assert youtube["sourceMetadata"]["description"] is None and youtube["sourceMetadata"]["tags"] == []
    source_queries = [sql for sql in statements if "FROM v_source_parts s" in sql]
    tag_queries = [sql for sql in statements if "SELECT bvid,tag_name FROM video_tags" in sql]
    assert len(source_queries) == 3 and len(tag_queries) == 2
    assert all(" IN (" in sql for sql in (*source_queries, *tag_queries))
    assert not any("WHERE video_part_id=" in sql for sql in statements)


def test_gateway_explicit_metadata_reuses_validated_pages_and_reports_missing_fields(bilibili_api_seam):
    import importlib
    script = bilibili_api_seam
    script.info_response = make_detail_response(desc="", pages=[make_part_item()])
    gateway = importlib.import_module("bili_asr.sources.bilibili_api_gateway").BilibiliApiGateway()
    read = asyncio.run(gateway.get_video_metadata(script.info_response["bvid"]))
    assert read.parts and len(read.parts) == 1
    states = {field.field: field.state for field in read.fields}
    assert states["desc"] == "empty" and states["pic"] == "missing"
    assert script.calls == ["video.get_info"]


def test_pubdate_backfill_and_explicit_correction_never_overwrite_with_zero(database):
    from bili_asr.storage.models import VideoRecord
    repository = MetadataRepository(database)
    with repository.transaction():
        database.execute("UPDATE videos SET pubdate=0")
        repository.upsert_video(VideoRecord("BVtest", 1, 1, "first", 100, 1, 2))
    assert database.execute("SELECT pubdate FROM videos").fetchone()[0] == 100
    with repository.transaction():
        repository.upsert_video(VideoRecord("BVtest", 1, 1, "regular", 200, 1, 3))
    assert database.execute("SELECT pubdate FROM videos").fetchone()[0] == 100
    with repository.transaction():
        repository.upsert_video(VideoRecord("BVtest", 1, 1, "explicit", 200, 1, 4), refresh_pubdate=True)
        repository.upsert_video(VideoRecord("BVtest", 1, 1, "unknown", 0, 1, 5), refresh_pubdate=True)
    assert database.execute("SELECT pubdate FROM videos").fetchone()[0] == 200


@pytest.mark.parametrize("mode,known,present,stamp,expected", [
    ("new", False, False, None, True), ("new", True, False, None, False),
    ("missing", True, False, None, True), ("missing", True, True, 0, False),
    ("stale", True, True, 99, False), ("stale", True, True, 1, True),
    ("stale", True, True, None, True), ("force", True, True, 99, True),
])
def test_refresh_modes_keep_new_missing_stale_and_force_distinct(mode, known, present, stamp, expected):
    assert MetadataRefreshPolicy(mode, 50).needs_read(known_video=known, present=present,
                                                     observed_at=stamp, now=100) is expected


def test_real_cli_incremental_discovers_new_video_without_repeating_known_operations(tmp_path, bilibili_api_seam, capsys):
    from bili_asr.cli.main import main
    from tests.fixtures.fake_bilibili_gateway import make_vlist_item, make_videos_response
    script = bilibili_api_seam
    current = [make_vlist_item(aid=501)]
    script.videos_response = lambda pn, ps: make_videos_response(*current if pn == 1 else (), count=len(current))
    script.parts_response = [make_part_item()]
    assert main(["fetch-meta", "--archive-root", str(tmp_path)]) == 0
    script.calls.clear()
    current = [make_vlist_item(bvid="BV1zyxWvUtSr", aid=502), *current]
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--incremental", "--refresh-mode", "missing"]) == 0
    assert script.calls.count("video.get_pages") == 1
    connection = open_database(tmp_path)
    assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 2
    connection.close()
    assert "reused_operations=2" in capsys.readouterr().out


def test_real_cli_target_refresh_updates_time_without_page_cursor(tmp_path, bilibili_api_seam, capsys):
    from bili_asr.cli.main import main
    from tests.fixtures.fake_bilibili_gateway import make_vlist_item, make_videos_response, BVID
    script = bilibili_api_seam
    script.videos_response = lambda pn, ps: make_videos_response(make_vlist_item(), count=1) if pn == 1 else make_videos_response(count=1)
    script.parts_response = [make_part_item()]
    assert main(["fetch-meta", "--archive-root", str(tmp_path)]) == 0
    connection = open_database(tmp_path)
    before = list(map(tuple, connection.execute("SELECT * FROM ingestion_cursors")))
    connection.close()
    script.info_response = make_detail_response(aid=501, pubdate=1704038400)
    script.calls.clear()
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--bvid", BVID, "--fields", "summary"]) == 0
    connection = open_database(tmp_path)
    assert connection.execute("SELECT pubdate FROM videos").fetchone()[0] == 1704038400
    assert list(map(tuple, connection.execute("SELECT * FROM ingestion_cursors"))) == before
    connection.close()
    assert script.calls == ["video.get_info"]


def test_invalid_request_budget_does_not_create_database(tmp_path, capsys):
    from bili_asr.cli.main import main
    assert main(["fetch-meta", "--archive-root", str(tmp_path), "--request-budget", "0"]) == 1
    assert not (tmp_path / "archive.db").exists()
