import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import replace

import pytest

from bili_asr.services import maintenance_package as package
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.source_observations import PlatformObservation
from bili_asr.storage.maintenance_selection import select_database
from bili_asr.storage.observation_rows import append_observations
from tests.fixtures.fake_bilibili_gateway import (
    bilibili_api_seam as bilibili_api_seam,  # noqa: PLC0414
)


def _observation(platform, operation, external_id, payload, *, creator=None):
    scope = {"externalVideoId": external_id}
    if creator is not None:
        scope["creatorId"] = creator
    return PlatformObservation.capture(
        platform=platform, operation=operation, endpoint="fixture",
        scope=scope, extractor="test", extractor_version="1",
        payload=payload, observed_at=1,
    )


def test_selected_observations_preserve_raw_video_and_shared_creator_page_boundary(tmp_path):
    source = tmp_path / "source"
    initialize_archive(source, with_source_observations=True)
    bili = _observation("bilibili", "details", "BV1", {"title": "raw-bili"}, creator="7")
    youtube = _observation("youtube", "video", "yt-1", {"title": "raw-youtube"}, creator="yt-creator")
    sibling = _observation("bilibili", "details", "BV-sibling", {"title": "unselected"}, creator="7")
    unrelated_page = PlatformObservation.capture(
        platform="bilibili", operation="creator-page", endpoint="fixture",
        scope={"creatorId": "7", "pageNumber": 2}, extractor="test", extractor_version="1",
        payload={"list": {"vlist": [{"bvid": "BV-sibling"}]}}, observed_at=2,
    )
    creator_page = PlatformObservation.capture(
        platform="bilibili", operation="creator-page", endpoint="fixture",
        scope={"creatorId": "7", "pageNumber": 1, "pageSize": 2},
        extractor="test", extractor_version="1",
        payload={"list": {"vlist": [{"bvid": "BV1"}, {"bvid": "BV-sibling"}]}}, observed_at=2,
    )
    with sqlite3.connect(source / "archive.db") as connection:
        connection.execute("INSERT INTO bilibili_users VALUES(7,'bili',1,1)")
        connection.execute("INSERT INTO videos VALUES('BV1',1,7,'Bili',1,1,1)")
        connection.execute(
            "INSERT INTO video_parts(video_part_id,bvid,page_index,cid,title,duration_ms,processing_status,created_at,updated_at) "
            "VALUES(1,'BV1',0,10,'Bili',100,'discovered',1,1)"
        )
        connection.execute("INSERT INTO source_creators VALUES(2,'youtube','yt-creator','YT',1,1)")
        connection.execute(
            "INSERT INTO source_videos(source_video_id,platform,external_id,creator_id,title,published_at,original_language,canonical_url,observed_at,created_at,updated_at) "
            "VALUES(2,'youtube','yt-1',2,'YT',1,'en','https://youtu.be/yt-1',1,1,1)"
        )
        connection.execute(
            "INSERT INTO video_parts(video_part_id,bvid,cid,page_index,title,duration_ms,processing_status,created_at,updated_at,source_video_id) "
            "VALUES(2,NULL,NULL,0,'YT',100,'metadata_collected',1,1,2)"
        )
        connection.execute("INSERT INTO videos VALUES('BV-sibling',3,7,'Unselected sibling',1,1,1)")
        connection.execute(
            "INSERT INTO video_parts(video_part_id,bvid,page_index,cid,title,duration_ms,processing_status,created_at,updated_at) "
            "VALUES(3,'BV-sibling',0,30,'Sibling',100,'discovered',1,1)"
        )
        append_observations(connection, (bili, youtube, creator_page, sibling, unrelated_page))
        connection.commit()

    destination = tmp_path / "selected.db"
    result = select_database(source / "archive.db", destination, part_ids=[1], bvids=[])
    assert result["observation_policy"] == "source-observations-closure/v1"
    assert result["observation_boundary"]["raw_observation_rows"] == 2
    assert len(result["observation_boundary"]["shared_creator_pages"]) == 1
    with sqlite3.connect(destination) as connection:
        rows = connection.execute(
            "SELECT observation_id,payload_json FROM platform_observations ORDER BY observed_at"
        ).fetchall()
        assert {row[0] for row in rows} == {bili.observation_id, creator_page.observation_id}
        assert connection.execute("SELECT external_id FROM source_videos").fetchall() == [("BV1",)]
        assert connection.execute("SELECT video_part_id FROM video_parts").fetchall() == [(1,)]
        assert connection.execute("SELECT COUNT(*) FROM source_metadata_observations").fetchone()[0] == 0
        assert connection.execute("SELECT singleton,version FROM platform_observation_contract").fetchone() == (1, 1)
    with sqlite3.connect(destination) as connection:
        selected_payload = connection.execute(
            "SELECT payload_json FROM platform_observations WHERE observation_id=?", (bili.observation_id,)
        ).fetchone()[0]
    assert hashlib.sha256(bili.payload_json.encode()).hexdigest() == hashlib.sha256(selected_payload.encode()).hexdigest()


def test_selected_observations_include_youtube_receipt_without_bilibili_siblings(tmp_path):
    source = tmp_path / "source"
    initialize_archive(source, with_source_observations=True)
    youtube = _observation("youtube", "video", "yt-1", {"title": "raw-youtube"}, creator="yt-creator")
    with sqlite3.connect(source / "archive.db") as connection:
        connection.execute("INSERT INTO source_creators VALUES(2,'youtube','yt-creator','YT',1,1)")
        connection.execute(
            "INSERT INTO source_videos(source_video_id,platform,external_id,creator_id,title,published_at,original_language,canonical_url,observed_at,created_at,updated_at) "
            "VALUES(2,'youtube','yt-1',2,'YT',1,'en','https://youtu.be/yt-1',1,1,1)"
        )
        connection.execute(
            "INSERT INTO video_parts(video_part_id,bvid,cid,page_index,title,duration_ms,processing_status,created_at,updated_at,source_video_id) "
            "VALUES(2,NULL,NULL,0,'YT',100,'metadata_collected',1,1,2)"
        )
        append_observations(connection, (youtube,))
        connection.commit()
    result = select_database(source / "archive.db", tmp_path / "selected.db", part_ids=[2], bvids=[])
    assert result["observation_boundary"]["raw_observation_rows"] == 1
    with sqlite3.connect(tmp_path / "selected.db") as connection:
        assert connection.execute(
            "SELECT platform,external_video_id FROM platform_observations"
        ).fetchone() == ("youtube", "yt-1")


def test_observation_selection_roundtrips_through_package_import(tmp_path):
    source = tmp_path / "source"
    initialize_archive(source, with_source_observations=True)
    observation = _observation("bilibili", "details", "BV1", {"title": "raw"}, creator="7")
    with sqlite3.connect(source / "archive.db") as connection:
        connection.execute("INSERT INTO bilibili_users VALUES(7,'bili',1,1)")
        connection.execute("INSERT INTO videos VALUES('BV1',1,7,'Bili',1,1,1)")
        connection.execute(
            "INSERT INTO video_parts(video_part_id,bvid,page_index,cid,title,duration_ms,processing_status,created_at,updated_at) "
            "VALUES(1,'BV1',0,10,'Bili',100,'discovered',1,1)"
        )
        append_observations(connection, (observation,))
        connection.commit()
    exported = tmp_path / "selected.zip"
    package.export_package(source, exported, part_ids=[1])
    target = tmp_path / "target"
    plan = package.plan_import(exported, target)
    plan_path = tmp_path / "plan.json"
    package.write_plan(plan, plan_path)
    assert package.apply_import(plan_path)["valid"]
    with sqlite3.connect(target / "archive.db") as connection:
        assert connection.execute("SELECT observation_id FROM platform_observations").fetchone() == (observation.observation_id,)


@pytest.mark.parametrize("scoped", [False, True])
def test_real_accepted_cache_and_frozen_receipts_roundtrip(tmp_path, bilibili_api_seam, scoped):
    from bili_asr.editorial import EditorialConfig
    from bili_asr.services.metadata_refresh import MetadataRefreshService
    from bili_asr.storage.database import connect_database
    from bili_asr.storage.metadata import MetadataRepository
    from bili_asr.storage.metadata_acceptance import read_bindings_many
    from bili_asr.storage.source_observations import verify_frozen_source_bindings
    from tests.test_ai_editorial import FakeClient, insert_record, record, runtime
    from tests.test_bilibili_metadata_acceptance import BVID, _metadata, _seed

    source = tmp_path / "source"
    gateway, part = _seed(source, bilibili_api_seam)
    with closing(connect_database(source / "archive.db")) as connection:
        insert_record(connection, replace(record(("A sentence.",)), video_part_id=part))
        _, editorial, _, _ = runtime(connection, source, FakeClient())
        prepared = editorial.prepare(1, None, EditorialConfig())
        frozen = prepared["snapshot"]["metadata"]["source_metadata"]
        assert len(frozen["observationBindings"]) == 11
        assert connection.execute("SELECT COUNT(*) FROM platform_observations WHERE operation='accepted-metadata'").fetchone()[0] == 8
        _metadata(bilibili_api_seam, title="Later accepted title", desc="Later description")
        outcomes = MetadataRefreshService(gateway, MetadataRepository(connection)).refresh((BVID,), operations=("summary",))
        assert outcomes[0].state == "present"
        assert MetadataRepository(connection).read_source_metadata(part).title == "Later accepted title"
        original_cache = connection.execute("SELECT * FROM source_metadata_observations ORDER BY field").fetchall()
        original_receipts = connection.execute("SELECT * FROM platform_observations ORDER BY observation_id").fetchall()
        before = MetadataRepository(connection).read_source_metadata(part)
    exported = tmp_path / "selected.zip"
    from bili_asr.storage.maintenance_scope import scope
    specification = scope(part_ids=[part]) if scoped else None
    result = package.export_package(source, exported, part_ids=[part], scope=specification)
    assert result["selection"]["observation_boundary"]["raw_observation_rows"] == len(original_receipts)
    target = tmp_path / "target"
    plan_path = tmp_path / "plan.json"
    package.write_plan(package.plan_import(exported, target), plan_path)
    assert package.apply_import(plan_path)["valid"]
    with closing(connect_database(target / "archive.db", readonly=True)) as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM source_metadata_observations ORDER BY field")] == [tuple(row) for row in original_cache]
        assert [tuple(row) for row in connection.execute("SELECT * FROM platform_observations ORDER BY observation_id")] == [tuple(row) for row in original_receipts]
        assert MetadataRepository(connection).read_source_metadata(part) == before
        assert read_bindings_many(connection, (BVID,))[BVID]
        assert json.loads(connection.execute("SELECT prepared_json FROM editorial_inputs").fetchone()[0])["snapshot"]["metadata"]["source_metadata"] == frozen
        verify_frozen_source_bindings(connection)


@pytest.mark.parametrize("extension", ["schema-artifact-storage.sql", "schema-preserved-body-import.sql"])
def test_other_registered_extensions_remain_full_export_only(tmp_path, extension):
    from bili_asr.storage.archive_contracts import _resource

    source = tmp_path / "source"
    initialize_archive(source, with_source_observations=True)
    with sqlite3.connect(source / "archive.db") as connection:
        connection.executescript(_resource(extension))
    with pytest.raises(ValueError, match="other extensions require full export"):
        select_database(source / "archive.db", tmp_path / "rejected.db", part_ids=[1], bvids=[])
    assert not (tmp_path / "rejected.db").exists()


@pytest.mark.parametrize("platform,operation", [("youtube", "details"), ("bilibili", "creator-page")])
@pytest.mark.usefixtures("enable_content_publication_for_tests")
def test_frozen_final_publication_bindings_survive_selective_import(tmp_path, platform, operation):
    from bili_asr.services.provenance import trace
    from bili_asr.storage.database import connect_database
    from bili_asr.storage.source_observations import verify_frozen_source_bindings
    from tests.test_provenance_trace import manuscript

    connection, source, _, _, release, _ = manuscript(tmp_path, platform, raw_kind=operation)
    with closing(connection):
        part = release["video_part_id"]
        frozen_inputs = [tuple(row) for row in connection.execute("SELECT input_id,prepared_json FROM editorial_inputs ORDER BY input_id")]
        frozen_editions = [tuple(row) for row in connection.execute("SELECT edition_id,content_json FROM publication_editions ORDER BY edition_id")]
        originals = [tuple(row) for row in connection.execute("SELECT * FROM platform_observations ORDER BY observation_id")]
        rights = [tuple(row) for row in connection.execute("SELECT * FROM content_rights_events ORDER BY event_id")]
        assert rights
        original_graph = trace(connection, release_id=release["release_id"], artifact_roots=(source,))
    exported = tmp_path / "final.zip"
    package.export_package(source, exported, part_ids=[part])
    target = tmp_path / "restored"
    plan_path = tmp_path / "final-plan.json"
    package.write_plan(package.plan_import(exported, target), plan_path)
    package.apply_import(plan_path)
    with closing(connect_database(target / "archive.db", readonly=True)) as connection:
        assert [tuple(row) for row in connection.execute("SELECT input_id,prepared_json FROM editorial_inputs ORDER BY input_id")] == frozen_inputs
        assert [tuple(row) for row in connection.execute("SELECT edition_id,content_json FROM publication_editions ORDER BY edition_id")] == frozen_editions
        assert [tuple(row) for row in connection.execute("SELECT * FROM platform_observations ORDER BY observation_id")] == originals
        assert [tuple(row) for row in connection.execute("SELECT * FROM content_rights_events ORDER BY event_id")] == rights
        verify_frozen_source_bindings(connection)
        assert trace(connection, release_id=release["release_id"], artifact_roots=(target,)) == original_graph


def test_unknown_extension_refused_before_destination_creation(tmp_path):
    source = tmp_path / "source"
    initialize_archive(source, with_source_observations=True)
    with sqlite3.connect(source / "archive.db") as connection:
        connection.execute("CREATE TABLE future_evidence(id INTEGER PRIMARY KEY, value TEXT)")
    with pytest.raises(ValueError, match="other extensions require full export"):
        select_database(source / "archive.db", tmp_path / "rejected.db", part_ids=[1], bvids=[])
    assert not (tmp_path / "rejected.db").exists()


def _rewrite_package_manifest(source, destination, change):
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, 'w') as altered:
        for member in original.infolist():
            value = original.read(member)
            if member.filename == 'maintenance.json':
                document = json.loads(value)
                change(document)
                document['content_id'] = package.digest({key: item for key, item in document.items()
                    if key not in {'content_id', 'created_at', 'producer_version'}})
                value = package.canonical(document)
            altered.writestr(member, value)


@pytest.mark.parametrize('scoped', [False, True])
@pytest.mark.parametrize('tampering', ['delete', 'count', 'missing-page', 'different-page'])
def test_selected_observation_boundaries_are_verified_against_database(tmp_path, scoped, tampering):
    from bili_asr.storage.maintenance_scope import scope

    source = tmp_path / 'source'
    initialize_archive(source, with_source_observations=True)
    observation = PlatformObservation.capture(platform='bilibili', operation='creator-page', endpoint='fixture',
        scope={'creatorId': '7', 'pageNumber': 1}, extractor='test', extractor_version='1', observed_at=1,
        payload={'list': {'vlist': [{'bvid': 'BV1'}, {'bvid': 'BV-sibling'}]}})
    with sqlite3.connect(source / 'archive.db') as connection:
        connection.execute("INSERT INTO bilibili_users VALUES(7,'bili',1,1)")
        connection.execute("INSERT INTO videos VALUES('BV1',1,7,'Bili',1,1,1)")
        connection.execute("INSERT INTO video_parts(video_part_id,bvid,page_index,cid,title,duration_ms,processing_status,created_at,updated_at) VALUES(1,'BV1',0,10,'Bili',100,'discovered',1,1)")
        append_observations(connection, (observation,))
    exported = tmp_path / 'selected.zip'
    package.export_package(source, exported, part_ids=[1], scope=scope(part_ids=[1]) if scoped else None)

    def change(document):
        selection = document['selection']
        if tampering == 'delete':
            selection.pop('observation_policy')
            selection.pop('observation_boundary')
        elif tampering == 'count':
            selection['observation_boundary']['raw_observation_rows'] += 1
        elif tampering == 'missing-page':
            selection['observation_boundary']['shared_creator_pages'] = []
        else:
            selection['observation_boundary']['shared_creator_pages'] = ['a' * 32]

    altered = tmp_path / 'altered.zip'
    _rewrite_package_manifest(exported, altered, change)
    # Its self-consistent manifest digest alone must not prove the DB boundary.
    assert package.inspect_package(altered)['valid']
    with pytest.raises(ValueError, match='observation (policy|boundary)'):
        package.verify_package(altered)
    target = tmp_path / 'target'
    with pytest.raises(ValueError, match='observation (policy|boundary)'):
        package.plan_import(altered, target)
    assert not target.exists()


@pytest.mark.parametrize('observations,selected', [(False, True), (True, False), (False, False)])
def test_observation_boundary_requirement_keeps_old_native_and_full_packages_readable(tmp_path, observations, selected):
    source = tmp_path / 'source'
    initialize_archive(source, with_source_observations=observations)
    with sqlite3.connect(source / 'archive.db') as connection:
        connection.execute("INSERT INTO bilibili_users VALUES(7,'bili',1,1)")
        connection.execute("INSERT INTO videos VALUES('BV1',1,7,'Bili',1,1,1)")
        connection.execute("INSERT INTO video_parts(video_part_id,bvid,page_index,cid,title,duration_ms,processing_status,created_at,updated_at) VALUES(1,'BV1',0,10,'Bili',100,'discovered',1,1)")
        if observations:
            append_observations(connection, (_observation('bilibili', 'details', 'BV1', {'raw': True}),))
    exported = tmp_path / 'compatible.zip'
    package.export_package(source, exported, part_ids=[1] if selected else None)
    selection = package.inspect_package(exported)['manifest']['selection']
    assert 'observation_policy' not in selection and 'observation_boundary' not in selection
    assert package.verify_package(exported)['valid']
    target = tmp_path / 'target'
    plan_path = tmp_path / 'plan.json'
    package.write_plan(package.plan_import(exported, target), plan_path)
    assert package.apply_import(plan_path)['valid']
