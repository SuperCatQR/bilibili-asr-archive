"""Raw platform facts survive real ingestion, explicit upgrade and backup IO."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from bili_asr.contracts.registry import UPGRADE_EDGES, upgrade_path
from bili_asr.platform_identity import ContentRef
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.services.archive_snapshot import save_snapshot, restore_snapshot, check_snapshot
from bili_asr.services.archive_upgrade import plan_upgrade, apply_upgrade
from bili_asr.source_observations import PlatformObservation, project_superset
from bili_asr.storage.database import connect_database
from bili_asr.storage.metadata import MetadataRepository
from bili_asr.storage.snapshots import validate_snapshot_database
from bili_asr.storage.source_observations import ObservationRepository
from bili_asr.storage.sources import SourceRepository
from bili_asr.sources.youtube_source import YoutubeSource
from tests.fixtures.fake_bilibili_gateway import (
    bilibili_api_seam as bilibili_api_seam, MID, make_vlist_item, make_videos_response, make_part_item,
)
from tests.fixtures.frozen_migration_archive import frozen_archive

REF = ContentRef("youtube", "dQw4w9WgXcQ")


def _observation(payload, *, platform="youtube", operation="details", scope=None, **kwargs):
    return PlatformObservation.capture(platform=platform, operation=operation, endpoint="test/source",
        scope=scope or {"externalVideoId": REF.external_video_id}, extractor="test", extractor_version="1",
        payload=payload, observed_at=17, **kwargs)


@pytest.mark.parametrize("platform", ["youtube", "bilibili"])
def test_raw_unknown_nested_types_null_and_repeated_observations_roundtrip(tmp_path, platform):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    payload = {"new_platform_field": {"nested": [True, False, None, 42, 1.5, "中文🙂"]},
               "nullValue": None, "emptyValue": [], "dimension": {"width": 1920, "height": 1080},
               "title": "Title", "description": "One\r\nTwo\t🙂"}
    original = deepcopy(payload)
    first, second = _observation(payload, platform=platform), _observation(payload, platform=platform)
    assert first.observation_id != second.observation_id
    with closing(connect_database(root / "archive.db")) as connection:
        with connection:
            ObservationRepository(connection).append((first, second))
        observations = ObservationRepository(connection).read_video(platform, REF.external_video_id)
        assert len(observations) == 2
        assert [json.loads(item.payload_json) for item in observations] == [original, original]
        assert payload == original
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE platform_observations SET payload_json='{}'")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM platform_observations")
        connection.rollback()
    assert validate_snapshot_database(root / "archive.db")
    package = tmp_path / "backup.zip"
    save_snapshot(root, package)
    assert check_snapshot(package)["valid"]
    restored = tmp_path / "restored"
    restore_snapshot(package, restored)
    with closing(connect_database(restored / "archive.db", readonly=True)) as connection:
        assert [item.payload_json for item in ObservationRepository(connection).read_video(platform, REF.external_video_id)] == [first.payload_json, second.payload_json]


def test_raw_receipts_and_contract_marker_reject_insert_or_replace(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    first = _observation({"title": "Original"})
    with closing(connect_database(root / "archive.db")) as connection:
        assert connection.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
        with connection:
            ObservationRepository(connection).append((first, first))
        row = tuple(connection.execute("SELECT * FROM platform_observations").fetchone())
        replacement = (*row[:5], row[5] + 1, *row[6:])
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("INSERT OR REPLACE INTO platform_observations VALUES (?,?,?,?,?,?,?,?,?)", replacement)
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("INSERT OR REPLACE INTO platform_observation_contract VALUES (1,1)")
        connection.rollback()
        assert ObservationRepository(connection).get(first.observation_id) == first


def test_projection_preserves_namespaces_sources_and_missing_empty_failed_states():
    payload = {"description": "Original", "tags": ["Known"], "categories": ["Education"],
               "chapters": [{"title": "Chapter", "start_time": 0}], "view_count": 12}
    first = _observation(payload)
    missing = _observation({"title": "Current", "description": None})
    failed = _observation(None, state="failed", error_code="transport_error")
    report = project_superset((first, missing, failed), platform="youtube", external_video_id=REF.external_video_id)
    assert report["fields"]["description"] == "Original"
    assert report["fields"]["tags"] == ["Known"]
    assert report["fieldStates"]["description"] == "null"
    assert report["platformFields"]["youtube"][first.observation_id] == payload
    assert report["provenance"]["description"]["observationId"] == first.observation_id
    assert report["provenance"]["description"]["jsonPointer"] == "/description"
    assert "bilibiliCategoryId" not in report["fields"]
    assert "parts" not in report["coverage"]["operations"]  # YouTube has one processing unit.
    assert report["coverage"]["operations"]["details"] == "failed"
    assert report["coverage"]["complete"] is False
    empty = _observation({"description": "", "tags": []})
    report = project_superset((first, empty), platform="youtube", external_video_id=REF.external_video_id)
    assert report["fields"]["description"] == "" and report["fields"]["tags"] == []
    assert report["fieldStates"]["tags"] == "empty"


def test_historical_reads_are_bounded_explicit_and_never_silently_truncated(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    first = _observation({"description": "One"})
    second = PlatformObservation.capture(platform="youtube", operation="details", endpoint="test/source",
        scope={"externalVideoId": REF.external_video_id}, extractor="test", extractor_version="1",
        payload={"description": "Two"}, observed_at=18)
    with closing(connect_database(root / "archive.db")) as connection:
        repository = ObservationRepository(connection)
        with connection:
            repository.append((first, second))
        assert repository.get(first.observation_id) == first
        with pytest.raises(ValueError, match="budget exceeded"):
            repository.read_video("youtube", REF.external_video_id, limit=1)
        with pytest.raises(ValueError, match="budget exceeded"):
            repository.read_video("youtube", REF.external_video_id, payload_byte_limit=1)
        report = repository.superset("youtube", REF.external_video_id, observed_after=18, limit=1)
        assert report["fields"]["description"] == "Two"
        assert report["coverage"]["selection"] == {"observedAfterInclusive": 18,
            "observedBeforeInclusive": None, "limit": 1}
        assert report["coverage"]["requestedObservationsSucceeded"] is True
        assert repository.read_video("youtube", REF.external_video_id, observed_before=17) == (first,)
        with pytest.raises(ValueError, match="begins after"):
            repository.read_video("youtube", REF.external_video_id, observed_after=19, observed_before=17)


def test_new_mapping_reprojects_same_raw_evidence_offline():
    raw = _observation({"duration": 2.125, "new_platform_field": {"untouched": True}})
    before = raw.payload_json
    one = project_superset((raw,), platform="youtube", external_video_id=REF.external_video_id)
    two = project_superset((raw,), platform="youtube", external_video_id=REF.external_video_id,
                           mapping_version="source-superset/v2")
    assert "durationMs" not in one["fields"] and two["fields"]["durationMs"] == 2125
    assert one["platformFields"] == two["platformFields"]
    assert two["provenance"]["durationMs"] == {"observationId": raw.observation_id,
        "jsonPointer": "/duration", "mapping": "seconds-to-milliseconds/v2"}
    assert raw.payload_json == before


def test_transport_exclusions_are_explicit_and_original_input_unchanged():
    payload = {"title": "Video", "http_headers": {"Cookie": "SECRET"},
               "nested": {"request_headers": {"Authorization": "SECRET"}, "unknown": 9}}
    original = deepcopy(payload)
    observation = _observation(payload)
    assert "SECRET" not in observation.payload_json + observation.envelope_json
    assert observation.envelope["excludedTransportPaths"] == ["/http_headers", "/nested/request_headers"]
    assert json.loads(observation.payload_json) == {"title": "Video", "nested": {"unknown": 9}}
    assert payload == original


def test_failed_raw_domain_receipt_keeps_denial_separate_from_empty():
    failure = _observation(None, state="denied", error_code="auth_error")
    empty = _observation([])
    assert failure.payload_json is None and empty.payload_json == "[]"
    assert failure.envelope["state"] == "denied" and empty.envelope["state"] == "success"


def test_real_youtube_metadata_repository_retains_full_private_payload(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    source = YoutubeSource()
    payload = {"id": REF.external_video_id, "title": "Title", "duration": 10,
               "description": "中文\nFrançais", "tags": ["one", "two"], "thumbnail": "https://i.ytimg.com/vi/test/default.jpg",
               "chapters": [{"title": "Part", "start_time": 0}], "view_count": 3,
               "categories": ["Education"], "new_platform_field": {"kept": True}}
    source._information[REF] = payload
    metadata = source.metadata(REF)
    with closing(connect_database(root / "archive.db")) as connection:
        with connection:
            part_id = SourceRepository(connection).upsert_video(metadata)
        report = ObservationRepository(connection).superset(REF.platform, REF.external_video_id)
        assert report["fields"]["description"] == payload["description"]
        assert report["fields"]["coverUrl"] == payload["thumbnail"]
        assert report["platformFields"]["youtube"][metadata.observations[0].observation_id] == payload
        assert connection.execute("SELECT COUNT(*) FROM platform_observations").fetchone()[0] == 1
        # Reusing the same real receipt is idempotent; a new request produces a
        # new ID. This is independent of the normalized source part identity.
        with connection:
            assert SourceRepository(connection).upsert_video(metadata) == part_id
        assert connection.execute("SELECT COUNT(*) FROM platform_observations").fetchone()[0] == 1


def test_real_bilibili_gateway_ingestion_captures_page_parts_tags_and_gaps(tmp_path, bilibili_api_seam):
    from bili_asr.services.metadata_ingest import MetadataIngestor
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    bvid = "BV1DETAILSD0"
    item = make_vlist_item(bvid=bvid, description="一\n二")
    item["new_platform_field"] = {"kept": True}
    bilibili_api_seam.videos_response = make_videos_response(item, count=45)
    bilibili_api_seam.parts_response = [make_part_item(cid=2222)]
    with closing(connect_database(root / "archive.db")) as connection:
        result = MetadataIngestor(BilibiliApiGateway(_sleeper=_no_sleep), MetadataRepository(connection)).collect_user_pages(
            MID, start_page=1, page_limit=1)
        assert result.outcome == "limited"
        report = ObservationRepository(connection).superset("bilibili", bvid)
        assert report["fields"]["description"] == "一\n二"
        pages = [value for value in report["platformFields"]["bilibili"].values() if isinstance(value, dict) and "list" in value]
        assert pages[0]["list"]["vlist"][0]["new_platform_field"] == {"kept": True}
        assert report["coverage"]["operations"]["details"] == "not-requested"
        scope = next(entry["scope"] for entry in report["coverage"]["observations"] if entry["operation"] == "creator-page")
        assert scope == {"creatorId": str(MID), "pageNumber": 1, "pageSize": 30}


async def _no_sleep(_):
    return None


_EDGES = tuple(edge for edge in UPGRADE_EDGES if edge.sample == "tests/test_source_observations.py")


@pytest.mark.parametrize("edge", _EDGES, ids=lambda edge: edge.identity)
def test_explicit_upgrade_preserves_history_and_raw_observations(tmp_path, edge):
    legacy, base, source, target = (tmp_path / name for name in ("legacy", "base", "source", "target"))
    frozen_archive(legacy)
    without_observations = tuple(item for item in edge.source if item != "source-observations/v1")
    old_edges = tuple(item for item in UPGRADE_EDGES if item.sample != "tests/test_source_observations.py")
    selected = tuple(item.identity for item in upgrade_path(("bilibili-v1",), without_observations, edges=old_edges))
    apply_upgrade(plan_upgrade(legacy, base, target_contracts=without_observations, selected_path=selected,
                               no_external_control_state=True))
    if "source-observations/v1" in edge.source:
        observation_edge = next(item for item in _EDGES if item.source == without_observations and item.target == edge.source)
        apply_upgrade(plan_upgrade(base, source, target_contracts=edge.source,
                                   selected_path=(observation_edge.identity,), no_external_control_state=True))
        with closing(connect_database(source / "archive.db")) as connection:
            with connection:
                ObservationRepository(connection).append((_observation({"new_platform_field": 1}),))
    else:
        source = base
    before = hashlib.sha256((source / "archive.db").read_bytes()).hexdigest()
    with closing(connect_database(source / "archive.db", readonly=True)) as connection:
        inputs = [tuple(row) for row in connection.execute("SELECT * FROM editorial_inputs")]
        editions = [tuple(row) for row in connection.execute("SELECT * FROM publication_editions")]
    apply_upgrade(plan_upgrade(source, target, target_contracts=edge.target,
                               selected_path=(edge.identity,), no_external_control_state=True))
    assert hashlib.sha256((source / "archive.db").read_bytes()).hexdigest() == before
    with closing(connect_database(target / "archive.db", readonly=True)) as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM editorial_inputs")] == inputs
        assert [tuple(row) for row in connection.execute("SELECT * FROM publication_editions")] == editions
        if "source-observations/v1" in edge.source:
            assert json.loads(ObservationRepository(connection).read_video("youtube", REF.external_video_id)[0].payload_json) == {"new_platform_field": 1}


def test_historical_unavailable_is_not_fabricated_and_cli_reads_backup_database(tmp_path, capsys):
    from bili_asr.cli.main import main
    root = tmp_path / "archive"
    initialize_archive(root)
    assert main(["source", "metadata", "--database", str(root / "archive.db"), "--youtube", REF.external_video_id]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["coverage"]["rawHistory"] == "unavailable"
    assert report["platformFields"]["youtube"] == {}


def test_snapshot_rejects_changed_raw_receipt_digest(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=True)
    with closing(connect_database(root / "archive.db")) as connection:
        with connection:
            ObservationRepository(connection).append((_observation({"unknown": 2}),))
            connection.execute("DROP TRIGGER platform_observations_no_update")
            connection.execute("UPDATE platform_observations SET payload_json='{}'")
        # Restore the exact SQL object: schema verification passes and payload
        # identity verification still rejects the altered private source fact.
        from bili_asr.storage.source_observations import observation_objects
        connection.execute(observation_objects()["platform_observations_no_update"][1])
        connection.commit()
    with pytest.raises(ValueError, match="digest"):
        validate_snapshot_database(root / "archive.db")
