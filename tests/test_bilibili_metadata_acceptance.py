"""Actual gateway DTO selection survives rejection, refresh and offline backup."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import replace

import pytest

from bili_asr.canonical_json import canonical
from bili_asr.editorial import EditorialConfig
from bili_asr.metadata_acceptance import CONTRACT, unpack_cache
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.services.archive_snapshot import (
    check_snapshot,
    restore_snapshot,
    save_snapshot,
)
from bili_asr.services.metadata_ingest import MetadataIngestor
from bili_asr.services.metadata_refresh import MetadataRefreshService
from bili_asr.source_observations import PlatformObservation
from bili_asr.storage.database import connect_database
from bili_asr.storage.metadata import MetadataRepository
from bili_asr.storage.metadata_acceptance import (
    record_acceptance,
    verify_acceptance_graph,
)
from bili_asr.storage.models import UserRecord, VideoPartRecord, VideoRecord
from bili_asr.storage.snapshots import validate_snapshot_database
from bili_asr.storage.source_observations import ObservationRepository
from bili_asr.storage.source_supplements import capture_description
from tests.fixtures.fake_bilibili_gateway import (
    MID,
    make_detail_response,
    make_part_item,
    make_tag_item,
    make_videos_response,
    make_vlist_item,
)
from tests.fixtures.fake_bilibili_gateway import (
    bilibili_api_seam as bilibili_api_seam,  # noqa: PLC0414 - register the fixture
)
from tests.test_ai_editorial import FakeClient, insert_record, record, runtime

BVID = "BV1DETAILSD0"
DESCRIPTION = "一\nDeuxième\t🙂"
COVER = "https://i1.hdslb.com/bfs/archive/picture.jpg"


async def _no_sleep(_):
    return None


def _seed(root, seam):
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    initialize_archive(root, with_source_observations=True)
    seam.videos_response = make_videos_response(make_vlist_item(bvid=BVID, description=DESCRIPTION, pic=COVER), count=1)
    seam.parts_response = [make_part_item(part="第一\n部分")]
    seam.tags_response = [make_tag_item(tag_name="主题")]
    gateway = BilibiliApiGateway(_sleeper=_no_sleep)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        result = MetadataIngestor(gateway, repository).collect_user_pages(MID, start_page=1, page_limit=1)
        assert result.outcome == "limited"
        part = connection.execute("SELECT video_part_id FROM video_parts WHERE bvid=?", (BVID,)).fetchone()[0]
    return gateway, part


def _cache(connection, field):
    row = connection.execute("SELECT value_json FROM source_metadata_observations WHERE external_id=? AND field=?", (BVID, field)).fetchone()
    return json.loads(row[0])


def _metadata(seam, **changes):
    seam.info_response = make_detail_response(**{"bvid": BVID, "pic": COVER, "desc": DESCRIPTION, "tid": 124, **changes})


def test_real_dtos_record_exact_pointers_normalizers_and_original_payload(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        source = MetadataRepository(connection).read_source_metadata(part)
        assert source.codec_version == 2 and source.description == DESCRIPTION
        assert source.part_title == "第一 部分" and source.tags == ("主题",)
        assert len(source.observation_bindings) == 11  # Eight choices and three provider responses.
        title, description, parts, tags = (_cache(connection, field) for field in ("title", "desc", "parts", "tags"))
        assert title["receipt"]["jsonPointer"] == "/list/vlist/0/title"
        assert description["receipt"]["jsonPointer"] == "/list/vlist/0/description"
        assert title["receipt"]["normalizer"] == "bilibili-summary/v1"
        assert parts["receipt"]["normalizer"] == "bilibili-parts/v1" and parts["receipt"]["jsonPointer"] == ""
        assert tags["receipt"]["normalizer"] == "bilibili-tags/v1"
        repo = ObservationRepository(connection)
        original = repo.get(description["receipt"]["source"]["observationId"])
        assert json.loads(original.payload_json)["list"]["vlist"][0] == bilibili_api_seam.videos_response["list"]["vlist"][0]
        accepted = repo.get(description["acceptance"]["observationId"])
        assert verify_acceptance_graph(connection, accepted)["fields"] == [description["receipt"]]
        assert accepted.envelope["endpoint"] == "bili-asr/metadata/acceptance"
        assert accepted.envelope["extractor"] == {"name": "bili-asr", "version": CONTRACT}
        report = repo.superset("bilibili", BVID)
        assert len(report["platformFields"]["bilibili"]) == 3
        assert "accepted-metadata" not in report["coverage"]["operations"]
        assert all(item["operation"] != "accepted-metadata" for item in report["coverage"]["observations"])
    assert validate_snapshot_database(root / "archive.db")


def test_rejected_new_response_cannot_replace_old_selected_raw_or_acceptance(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    gateway, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        before = repository.read_source_metadata(part)
        old_cache = _cache(connection, "desc")
        _metadata(bilibili_api_seam, title="Rejected response", tid=-1)
        outcomes = MetadataRefreshService(gateway, repository).refresh((BVID,), operations=("summary", "details"))
        assert all(outcome.error_code == "shape_error" for outcome in outcomes)
        assert repository.read_source_metadata(part) == before
        assert _cache(connection, "desc") == old_cache
        raw = ObservationRepository(connection).read_video("bilibili", BVID)
        rejected = next(item for item in raw if item.envelope["operation"] == "details")
        assert json.loads(rejected.payload_json)["tid"] == -1
        assert rejected.observation_id not in {item[0] for item in before.observation_bindings}


def test_summary_refresh_keeps_description_actual_receipt_and_historical_freeze(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    gateway, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        insert_record(connection, replace(record(("A sentence.",)), video_part_id=part))
        _, editorial, _, _ = runtime(connection, root, FakeClient())
        prepared = editorial.prepare(1, None, EditorialConfig())
        frozen = deepcopy(prepared["snapshot"]["metadata"]["source_metadata"])
        description = _cache(connection, "desc")
        _metadata(bilibili_api_seam, title="New title", desc="Unused new description")
        result = MetadataRefreshService(gateway, repository).refresh((BVID,), operations=("summary",))
        assert result[0].state == "present"
        current = repository.read_source_metadata(part)
        assert current.title == "New title" and current.description == DESCRIPTION
        assert _cache(connection, "desc") == description
        assert prepared["snapshot"]["metadata"]["source_metadata"] == frozen
    assert validate_snapshot_database(root / "archive.db")
    package = tmp_path / "backup.zip"
    save_snapshot(root, package)
    assert check_snapshot(package)["valid"]
    restored = tmp_path / "restored"
    restore_snapshot(package, restored)
    with closing(connect_database(restored / "archive.db", readonly=True)) as connection:
        assert MetadataRepository(connection).read_source_metadata(part).title == "New title"
        source = json.loads(connection.execute("SELECT prepared_json FROM editorial_inputs").fetchone()[0])
        assert source["snapshot"]["metadata"]["source_metadata"] == frozen


def test_failed_normalized_transaction_preserves_old_receipt_and_application_log(tmp_path, bilibili_api_seam, monkeypatch):
    root = tmp_path / "archive"
    gateway, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        before, cache = repository.read_source_metadata(part), _cache(connection, "title")
        adoption_count = connection.execute("SELECT COUNT(*) FROM platform_observations WHERE operation='accepted-metadata'").fetchone()[0]
        _metadata(bilibili_api_seam, title="Must roll back")
        def fail_attempt(*args, **kwargs):
            raise sqlite3.OperationalError("synthetic commit path failure")
        monkeypatch.setattr(repository, "record_metadata_attempt", fail_attempt)
        with pytest.raises(sqlite3.OperationalError, match="synthetic"):
            MetadataRefreshService(gateway, repository).refresh((BVID,), operations=("summary",))
        assert repository.read_source_metadata(part) == before
        assert _cache(connection, "title") == cache
        assert connection.execute("SELECT COUNT(*) FROM platform_observations WHERE operation='accepted-metadata'").fetchone()[0] == adoption_count
        assert connection.execute("SELECT COUNT(*) FROM platform_observations WHERE operation='details'").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["value", "pointer", "normalizer", "scope", "digest", "adoption"])
def test_current_and_snapshot_reject_tampered_acceptance_cache(tmp_path, bilibili_api_seam, change):
    root = tmp_path / "archive"
    _, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        cache = _cache(connection, "desc")
        if change == "value":
            cache["value"] = cache["receipt"]["value"] = "Invented"
        elif change == "pointer":
            cache["receipt"]["jsonPointer"] = "/list/vlist/0/title"
        elif change == "normalizer":
            cache["receipt"]["normalizer"] = "bilibili-details/v1"
        elif change == "scope":
            cache["receipt"]["context"]["bvid"] = "BV1234567890"
        elif change == "digest":
            cache["receipt"]["source"]["payloadSha256"] = "0" * 64
        else:
            cache["acceptance"] = _cache(connection, "title")["acceptance"]
        with connection:
            connection.execute("UPDATE source_metadata_observations SET value_json=? WHERE external_id=? AND field='desc'",
                               (canonical(cache), BVID))
        with pytest.raises(ValueError, match="accepted|acceptance|receipt"):
            MetadataRepository(connection).read_source_metadata(part)
    with pytest.raises(ValueError, match="accepted|acceptance|receipt"):
        validate_snapshot_database(root / "archive.db")


def test_legacy_plain_cache_remains_unknown_and_supplement_evidence_unchanged(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        source = MetadataRepository(connection).read_source_metadata(part).to_dict()
        edition = {"video_part_id": part, "content": {"source": {"metadata": source}}}
        selected = capture_description(connection, edition)
        row = connection.execute("SELECT last_success_at,value_json FROM source_metadata_observations WHERE field='desc'").fetchone()
        with connection:
            connection.execute("UPDATE source_metadata_observations SET value_json=? WHERE field='desc'", (json.dumps(unpack_cache(row[1])[0]),))
        assert capture_description(connection, edition) == selected
        with connection:
            for cache in connection.execute("SELECT rowid,value_json FROM source_metadata_observations"):
                connection.execute("UPDATE source_metadata_observations SET value_json=? WHERE rowid=?",
                                   (json.dumps(unpack_cache(cache[1])[0]), cache[0]))
        unknown = MetadataRepository(connection).read_source_metadata(part)
        assert unknown.codec_version == 1 and unknown.observation_bindings == ()
        assert unknown.description == DESCRIPTION


def test_current_read_ignores_more_than_ten_thousand_historical_receipts(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        before = MetadataRepository(connection).read_source_metadata(part)
        repository = ObservationRepository(connection)
        with connection:
            repository.append(PlatformObservation.capture(platform="bilibili", operation="details", endpoint="video/info/detail",
                scope={"externalVideoId": BVID}, extractor="test", extractor_version="1", observed_at=1,
                payload={"bvid": BVID, "title": "Repeated rejected/unselected raw", "tid": -1}) for _ in range(10001))
        with pytest.raises(ValueError, match="budget exceeded"):
            repository.read_videos("bilibili", (BVID,))
        statements = []
        connection.set_trace_callback(statements.append)
        current = MetadataRepository(connection).read_source_metadata_many((part,))[part]
        connection.set_trace_callback(None)
        assert current == before
        raw_queries = [sql for sql in statements if "SELECT * FROM platform_observations" in sql]
        assert len(raw_queries) == 2 and all("observation_id IN" in sql for sql in raw_queries)


def test_256_current_videos_use_bounded_set_queries(tmp_path):
    from bili_asr.sources.bilibili_metadata_codec import (
        _normalize_video_summary_item,
        bind_summary,
    )
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        ids = []
        with repository.transaction():
            repository.upsert_user(UserRecord(MID, "Creator", 1, 1))
            for number in range(256):
                bvid = "BV" + f"{number:010d}"
                item = make_vlist_item(bvid=bvid, aid=number + 1000)
                raw = PlatformObservation.capture(platform="bilibili", operation="creator-page", endpoint="user/info/video",
                    scope={"creatorId": str(MID), "pageNumber": 1, "pageSize": 30}, extractor="test", extractor_version="1",
                    observed_at=1, payload=make_videos_response(item))
                ObservationRepository(connection).append((raw,))
                summary = bind_summary(_normalize_video_summary_item(item, MID), raw, item, "/list/vlist/0")
                repository.upsert_video(VideoRecord(bvid, summary.aid, MID, summary.title, summary.pubdate, 1, 1))
                ids.append(repository.upsert_part(VideoPartRecord(bvid, 0, 1000 + number, "Part", 1000, "metadata_collected", 1, 1)))
                record_acceptance(connection, bvid, tuple(receipt for receipt in summary.source_receipts
                                  if receipt.field in {"title", "pubdate", "aid"}), 1)
        statements = []
        connection.set_trace_callback(statements.append)
        sources = repository.read_source_metadata_many(ids)
        connection.set_trace_callback(None)
        assert len(sources) == 256 and all(source.codec_version == 2 for source in sources.values())
        assert sum("SELECT * FROM source_metadata_observations" in sql for sql in statements) == 1
        assert sum("SELECT * FROM platform_observations" in sql for sql in statements) == 4
        assert all("observation_id IN" in sql for sql in statements if "SELECT * FROM platform_observations" in sql)


def test_direct_legacy_write_invalidates_changed_selection_only(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        old = _cache(connection, "desc")
        row = connection.execute("SELECT aid,pubdate FROM videos WHERE bvid=?", (BVID,)).fetchone()
        with repository.transaction():
            repository.upsert_video(VideoRecord(BVID, row[0], MID, "Manual title", row[1], 1, 2))
        source = repository.read_source_metadata(part)
        assert source.title == "Manual title" and _cache(connection, "desc") == old
        assert unpack_cache(connection.execute("SELECT value_json FROM source_metadata_observations WHERE field='title'").fetchone()[0])[1] is None


def test_historical_acceptance_requires_source_pointer_value_relation(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, _ = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        cache = _cache(connection, "desc")
        invented = deepcopy(cache["receipt"])
        invented["jsonPointer"] = "/list/vlist/0/title"
        observation = PlatformObservation.capture(platform="bilibili", operation="accepted-metadata",
            endpoint="bili-asr/metadata/acceptance", scope={"externalVideoId": BVID}, extractor="bili-asr",
            extractor_version=CONTRACT, payload={"version": CONTRACT, "externalVideoId": BVID, "fields": [invented]})
        with connection:
            ObservationRepository(connection).append((observation,))
        with pytest.raises(ValueError, match="source DTO"):
            verify_acceptance_graph(connection, observation)
    with pytest.raises(ValueError, match="source DTO"):
        validate_snapshot_database(root / "archive.db")


def test_parts_and_tags_refresh_select_actual_dtos_and_empty_tags(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    gateway, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        old_title = _cache(connection, "title")
        bilibili_api_seam.parts_response = [make_part_item(part="新的\n部分", duration=12.345)]
        bilibili_api_seam.tags_response = []
        outcomes = MetadataRefreshService(gateway, repository).refresh((BVID,), operations=("parts", "tags"))
        assert [outcome.state for outcome in outcomes] == ["present", "empty"]
        assert repository.read_source_metadata(part).part_title == "新的 部分"
        assert repository.read_source_metadata(part).duration_ms == 12345
        assert repository.read_source_metadata(part).tags == ()
        assert _cache(connection, "tags")["value"] == []
        assert _cache(connection, "title") == old_title
        bilibili_api_seam.parts_response = [make_part_item(cid=999999)]
        prior = _cache(connection, "parts")
        assert MetadataRefreshService(gateway, repository).refresh((BVID,), operations=("parts",))[0].error_code == "metadata_part_identity_conflict"
        assert _cache(connection, "parts") == prior
    assert validate_snapshot_database(root / "archive.db")


def test_completed_aid_and_fallback_title_have_explicit_selection_context(tmp_path, bilibili_api_seam):
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    bilibili_api_seam.videos_response = make_videos_response(make_vlist_item(bvid=BVID, aid=None))
    bilibili_api_seam.info_response = make_detail_response(bvid=BVID, aid=789)
    bilibili_api_seam.parts_response = [make_part_item(part="")]
    bilibili_api_seam.tags_response = []
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        result = MetadataIngestor(BilibiliApiGateway(_sleeper=_no_sleep), repository).collect_user_pages(MID, start_page=1, page_limit=1)
        assert result.outcome == "limited"
        aid = _cache(connection, "aid")
        assert aid["receipt"]["normalizer"] == "bilibili-completed-aid/v1"
        assert aid["receipt"]["jsonPointer"] == "/aid" and aid["value"] == 789
        parts = _cache(connection, "parts")
        assert parts["receipt"]["context"]["fallbackTitle"] == "未明子讲座"
        part = connection.execute("SELECT video_part_id FROM video_parts").fetchone()[0]
        assert repository.read_source_metadata(part).part_title == "未明子讲座"
    assert validate_snapshot_database(root / "archive.db")


def test_unadopted_stable_aid_does_not_replace_actual_original_receipt(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    gateway, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = MetadataRepository(connection)
        previous = _cache(connection, "aid")
        _metadata(bilibili_api_seam, title="New title", aid=222)
        outcome = MetadataRefreshService(gateway, repository).refresh((BVID,), operations=("summary",))
        assert outcome[0].state == "present"
        source = repository.read_source_metadata(part)
        assert source.aid == 111 and source.title == "New title"
        assert _cache(connection, "aid") == previous


@pytest.mark.parametrize("corruption", ["missing-raw", "frozen-value", "missing-binding"])
def test_snapshot_checks_historical_acceptance_after_complete_refresh(tmp_path, bilibili_api_seam, corruption):
    root = tmp_path / "archive"
    gateway, part = _seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        insert_record(connection, replace(record(("A sentence.",)), video_part_id=part))
        _, editorial, _, _ = runtime(connection, root, FakeClient())
        prepared = editorial.prepare(1, None, EditorialConfig())
        raw_identity = _cache(connection, "desc")["receipt"]["source"]["observationId"]
        _metadata(bilibili_api_seam, title="Refreshed", desc="New description")
        assert all(outcome.state == "present" for outcome in MetadataRefreshService(gateway, MetadataRepository(connection)).refresh(
            (BVID,), operations=("summary", "details")))
        assert MetadataRepository(connection).read_source_metadata(part).description == "New description"
        with connection:
            if corruption == "missing-raw":
                triggers = tuple(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='platform_observations'"))
                for name, _ in triggers:
                    connection.execute('DROP TRIGGER "' + name + '"')
                connection.execute("DELETE FROM platform_observations WHERE observation_id=?", (raw_identity,))
            else:
                triggers = tuple(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='editorial_inputs'"))
                for name, _ in triggers:
                    connection.execute('DROP TRIGGER "' + name + '"')
                source = prepared["snapshot"]["metadata"]["source_metadata"]
                if corruption == "frozen-value":
                    source["description"] = "Invented historical description"
                else:
                    source["observationBindings"] = [item for item in source["observationBindings"] if item["observationId"] != raw_identity]
                connection.execute("UPDATE editorial_inputs SET prepared_json=? WHERE input_id=?", (json.dumps(prepared), prepared["input_id"]))
            for _, sql in triggers:
                connection.execute(sql)
    with pytest.raises(ValueError, match="receipt|acceptance"):
        validate_snapshot_database(root / "archive.db")


def test_current_receipt_budget_fails_explicitly_without_partial_metadata(tmp_path, bilibili_api_seam, monkeypatch):
    root = tmp_path / "archive"
    _, part = _seed(root, bilibili_api_seam)
    monkeypatch.setattr("bili_asr.storage.metadata_acceptance.MAX_READ_BYTES", 1)
    with closing(connect_database(root / "archive.db")) as connection, pytest.raises(ValueError, match="read budget"):
        MetadataRepository(connection).read_source_metadata_many((part,))
