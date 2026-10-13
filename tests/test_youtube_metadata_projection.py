"""Complete source fields survive actual ingestion, freezing, release and backup."""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

from bili_asr.archive_session import ArchiveSession, ArchiveAccessMode
from bili_asr.contracts.json_schema import validate_json
from bili_asr.editorial import EditorialConfig
from bili_asr.export import export_records
from bili_asr.platform_identity import ContentRef
from bili_asr.publication import create_edition, get_edition, publish_edition, verify_release
from bili_asr.publication_export import export_publications, export_publication_drafts
from bili_asr.search_index.query import search_archive
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.services.archive_snapshot import save_snapshot, restore_snapshot, check_snapshot
from bili_asr.source_metadata import SourceMetadataSnapshot, public_cover_url
from bili_asr.source_observations import PlatformObservation
from bili_asr.sources.youtube_source import YoutubeSource
from bili_asr.storage.metadata import MetadataRepository
from bili_asr.storage.sources import SourceRepository
from bili_asr.storage.snapshots import validate_snapshot_database
from bili_asr.storage.source_observations import ObservationRepository
from tests.support.content_permissions import grant_test_permission
from tests.test_ai_editorial import FakeClient, insert_record, record, runtime
from tests.test_publication import approve

REF = ContentRef("youtube", "dQw4w9WgXcQ")
DESCRIPTION = "中文第一行\r\nFrançais deuxième ligne\t🙂\nhttps://example.org/design-guide"
COVER = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def _metadata(**changes):
    source = YoutubeSource()
    source._information[REF] = {"id": REF.external_video_id, "title": "Source", "duration": 2,
        "description": DESCRIPTION, "thumbnail": COVER, "tags": ["topic", "中文", "topic"],
        "categories": ["Education"], "chapters": [{"title": "One", "start_time": 0}],
        "view_count": 77, "private_debug_notes": "PRIVATE_RAW_ONLY", **changes}
    return source.metadata(REF)


@pytest.mark.parametrize("raw_storage", [False, True])
def test_real_ingestion_known_fields_snapshot_export_search_and_backup(tmp_path, raw_storage):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=raw_storage)
    metadata = _metadata()
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        with session.connection:
            part = SourceRepository(session.connection).upsert_video(metadata)
        repository = MetadataRepository(session.connection)
        source = repository.read_source_metadata(part)
        assert source.description == DESCRIPTION and source.cover_url == COVER
        assert source.tags == ("topic", "中文") and source.category_id is None
        assert source.to_dict()["version"] == "source-metadata-v2"
        assert bool(source.observation_bindings) == raw_storage
        validate_json("source-metadata/v2", source.to_dict())
        assert SourceMetadataSnapshot.from_dict(source.to_dict()) == source
        assert repository.read_source_metadata_many((part,))[part] == source
    output = json.loads(export_records(root, "json", private=True))[0]
    assert output["video_description"] == DESCRIPTION and output["video_tags"] == ["topic", "中文"]
    assert output["sourceMetadata"]["coverUrl"] == COVER
    assert search_archive(root, "deuxième", scope="metadata").hits[0].matched_fields == ("description",)
    assert search_archive(root, "topic", scope="metadata").hits[0].matched_fields == ("tags",)
    assert not search_archive(root, "PRIVATE_RAW_ONLY", scope="metadata").hits
    package = tmp_path / "backup.zip"
    save_snapshot(root, package)
    assert check_snapshot(package)["valid"]
    restored = tmp_path / "restored"
    restore_snapshot(package, restored)
    with ArchiveSession(restored, mode=ArchiveAccessMode.READ) as session:
        assert MetadataRepository(session.connection).read_source_metadata(part) == source


@pytest.mark.parametrize("refresh", ["absent", "null", "empty", "invalid", "signed-cover"])
def test_refresh_distinguishes_missing_null_empty_and_invalid_without_erasing_known_fields(tmp_path, refresh):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        repository = SourceRepository(session.connection)
        with session.connection:
            part = repository.upsert_video(_metadata())
        first = MetadataRepository(session.connection).read_source_metadata(part)
        if refresh == "absent":
            payload = {"id": REF.external_video_id, "title": "New", "duration": 2}
        elif refresh == "null":
            payload = {"id": REF.external_video_id, "title": "New", "duration": 2,
                       "description": None, "tags": None, "thumbnail": None}
        elif refresh == "empty":
            payload = {"id": REF.external_video_id, "title": "New", "duration": 2,
                       "description": "", "tags": []}
        elif refresh == "invalid":
            payload = {"id": REF.external_video_id, "title": "New", "duration": 2,
                       "description": {"not": "prose"}, "tags": [42], "thumbnail": "http://i.ytimg.com/a.jpg"}
        else:
            payload = {"id": REF.external_video_id, "title": "New", "duration": 2,
                       "thumbnail": COVER + "?token=PRIVATE"}
        source = YoutubeSource()
        source._information[REF] = payload
        with session.connection:
            assert repository.upsert_video(source.metadata(REF)) == part
        second = MetadataRepository(session.connection).read_source_metadata(part)
        assert second.title == "New" and second.cover_url == COVER
        if refresh == "empty":
            assert second.description == "" and second.tags == ()
        else:
            assert second.description == first.description and second.tags == first.tags
        # The first frozen value is a detached value, never rewritten by refresh.
        assert first.description == DESCRIPTION and first.tags == ("topic", "中文")


@pytest.mark.parametrize("cover", ["https://i.ytimg.com.evil.org/image.jpg", "https://user:secret@i.ytimg.com/a.jpg",
    "https://i.ytimg.com/a.jpg?token=secret", "https://i.ytimg.com/a.jpg#x", "https://i.ytimg.com:444/a.jpg",
    "https://i.ytimg.com/a.jpg\n", "https://static.example.org/image.jpg"])
def test_versioned_cover_boundary_remains_strict(cover):
    assert public_cover_url(cover, platform="youtube", codec_version=2) is None


def test_v1_codec_is_unchanged_and_v2_keeps_platform_cover_ownership():
    old = SourceMetadataSnapshot(REF, "Source", None, None, None, None, cover_url=COVER)
    assert old.cover_url is None and old.to_dict()["version"] == "source-metadata-v1"
    assert "observationBindings" not in old.to_dict()
    assert public_cover_url(COVER, platform="bilibili", codec_version=2) is None
    assert public_cover_url("https://i0.hdslb.com/bfs/a.jpg", platform="youtube", codec_version=2) is None
    validate_json("source-metadata/v1", old.to_dict())


def test_private_projection_tamper_cannot_claim_an_unchanged_raw_receipt(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        with session.connection:
            part = SourceRepository(session.connection).upsert_video(_metadata())
            row = session.connection.execute("SELECT value_json FROM source_metadata_observations WHERE field='desc'").fetchone()
            projected = json.loads(row[0])
            projected["value"] = "Changed without a new platform observation"
            session.connection.execute("UPDATE source_metadata_observations SET value_json=? WHERE field='desc'", (json.dumps(projected),))
        with pytest.raises(ValueError, match="differs from its original"):
            MetadataRepository(session.connection).read_source_metadata(part)
    with pytest.raises(ValueError, match="differs from its original"):
        save_snapshot(root, tmp_path / "tampered.zip")


def test_real_new_release_freezes_original_fields_and_uses_catalog_v4(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        connection = session.connection
        with connection:
            part = SourceRepository(connection).upsert_video(_metadata())
        transcript = replace(record(("A complete source sentence.",)), video_part_id=part, language="en")
        insert_record(connection, transcript)
        workflow, editorial, _handlers, executor = runtime(connection, root, FakeClient())
        prepared = editorial.prepare(transcript.transcript_id, None, EditorialConfig())
        frozen = prepared["snapshot"]["metadata"]["source_metadata"]
        assert frozen["description"] == DESCRIPTION and frozen["coverUrl"] == COVER
        assert frozen["tags"] == ["topic", "中文"] and len(frozen["observationBindings"]) == 1
        job, *_ = workflow.request_editorial(video_part_id=part, input_id=prepared["input_id"])
        assert executor.run().failed == 0
        edition = create_edition(connection, revision_id=editorial.revision_for_job(job), artifact_roots=(root,), actor="editor")
        assert edition["content"]["source"]["metadata"] == frozen
        grant_test_permission(connection, edition, (root,))
        drafts = tmp_path / "drafts"
        assert export_publication_drafts(connection, artifact_roots=(root,), output=drafts) == 1
        assert json.loads((drafts / "catalog.json").read_text(encoding="utf-8"))["schemaVersion"] == 4
        approve(connection, edition)
        release = publish_edition(connection, edition_id=edition["edition_id"], artifact_roots=(root,), write_root=root, actor="publisher")
        release_bytes = verify_release(connection, release["release_id"], (root,))[2]
        with connection:
            SourceRepository(connection).upsert_video(_metadata(description="A refreshed description", tags=[]))
        assert get_edition(connection, edition["edition_id"])["content"]["source"]["metadata"] == frozen
        public = tmp_path / "public"
        assert export_publications(connection, artifact_roots=(root,), output=public) == 1
        encoded = (public / "catalog.json").read_text(encoding="utf-8")
        catalog = json.loads(encoded)
        assert catalog["schemaVersion"] == 4 and catalog["articles"][0]["sourceMetadata"] == frozen
        assert "PRIVATE_RAW_ONLY" not in encoded and "platformFields" not in encoded and "chapters" not in encoded
        validate_json("publication-catalog/v4", catalog)
    package = tmp_path / "published.zip"
    save_snapshot(root, package)
    restored = tmp_path / "restored"
    restore_snapshot(package, restored)
    with ArchiveSession(restored, mode=ArchiveAccessMode.READ) as session:
        assert verify_release(session.connection, release["release_id"], (restored,))[2] == release_bytes


def test_batch_current_fields_use_set_queries_and_bounded_original_receipts(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        ids = []
        with session.connection:
            for number in range(60):
                ref = ContentRef("youtube", f"clip{number:07d}")
                observation = PlatformObservation.capture(platform="youtube", operation="details", endpoint="test",
                    scope={"externalVideoId": ref.external_video_id}, extractor="test", extractor_version="1",
                    payload={"description": DESCRIPTION, "tags": ["topic"], "thumbnail": COVER})
                ids.append(SourceRepository(session.connection).upsert_video(replace(_metadata(), ref=ref,
                    observations=(observation,))))
        statements = []
        session.connection.set_trace_callback(statements.append)
        assert len(MetadataRepository(session.connection).read_source_metadata_many(ids)) == 60
        session.connection.set_trace_callback(None)
        assert sum("SELECT * FROM source_metadata_observations" in sql for sql in statements) == 1
        assert sum("SELECT * FROM platform_observations" in sql for sql in statements) == 1


@pytest.mark.parametrize("tamper", ["owner", "digest"])
def test_batch_projection_cannot_hide_a_conflicting_receipt(tmp_path, tamper):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        connection = session.connection
        with connection:
            first = SourceRepository(connection).upsert_video(_metadata())
            other = ContentRef("youtube", "abcdefghijk")
            observed = PlatformObservation.capture(platform="youtube", operation="details", endpoint="test",
                scope={"externalVideoId": other.external_video_id}, extractor="test", extractor_version="1",
                payload={"description": DESCRIPTION, "tags": ["topic", "中文"], "thumbnail": COVER})
            second = SourceRepository(connection).upsert_video(replace(_metadata(), ref=other, observations=(observed,)))
            projected = json.loads(connection.execute("SELECT value_json FROM source_metadata_observations "
                "WHERE external_id=? AND field='desc'", (REF.external_video_id,)).fetchone()[0])
            if tamper == "owner":
                original = json.loads(connection.execute("SELECT value_json FROM source_metadata_observations "
                    "WHERE external_id=? AND field='desc'", (other.external_video_id,)).fetchone()[0])
                projected["observation"] = original["observation"]
            else:
                projected["observation"]["payloadSha256"] = "0" * 64
            connection.execute("UPDATE source_metadata_observations SET value_json=? "
                "WHERE external_id=? AND field='desc'", (json.dumps(projected), REF.external_video_id))
        with pytest.raises(ValueError, match="receipt"):
            MetadataRepository(connection).read_source_metadata_many((first, second))
    with pytest.raises(ValueError, match="receipt"):
        validate_snapshot_database(root / "archive.db")


def test_older_frozen_receipt_remains_required_after_refresh(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        connection = session.connection
        with connection:
            part = SourceRepository(connection).upsert_video(_metadata())
        insert_record(connection, replace(record(("A source sentence.",)), video_part_id=part, language="en"))
        _workflow, editorial, _handlers, _executor = runtime(connection, root, FakeClient())
        prepared = editorial.prepare(1, None, EditorialConfig())
        identity = prepared["snapshot"]["metadata"]["source_metadata"]["observationBindings"][0]["observationId"]
        with connection:
            SourceRepository(connection).upsert_video(_metadata(description="Refreshed"))
            triggers = tuple(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' "
                                                "AND tbl_name='platform_observations'"))
            for name, _sql in triggers:
                connection.execute('DROP TRIGGER "' + name + '"')
            connection.execute("DELETE FROM platform_observations WHERE observation_id=?", (identity,))
            for _name, sql in triggers:
                connection.execute(sql)
        assert MetadataRepository(connection).read_source_metadata(part).description == "Refreshed"
    with pytest.raises(ValueError, match="unavailable"):
        validate_snapshot_database(root / "archive.db")


def test_creator_page_nonobject_values_are_preserved_without_poisoning_reads(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    bvid = "BV1234567890"
    payload = {"list": {"vlist": ["opaque", None, 5, [], {"bvid": bvid}]}}
    observation = PlatformObservation.capture(platform="bilibili", operation="creator-page", endpoint="test",
        scope={"creatorId": "1"}, extractor="test", extractor_version="1", payload=payload)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        repository = ObservationRepository(session.connection)
        with session.connection:
            repository.append((observation,))
        assert repository.read_video("bilibili", bvid) == (observation,)
        assert repository.read_video("bilibili", "other") == ()
        assert repository.read_videos("bilibili", (bvid, "other")) == {bvid: (observation,), "other": ()}
        assert json.loads(repository.get(observation.observation_id).payload_json) == payload
