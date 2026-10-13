"""Private source IO rejects unsupported facts and preserves complete evidence."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import shutil

import pytest

from bili_asr.cli import main
from bili_asr.platform_identity import ContentRef
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.source_observations import PlatformObservation
from bili_asr.source_video import SourceVideoMetadata
from bili_asr.sources.models import GatewayError, GatewayResponseError, VideoPart
from bili_asr.sources.youtube_source import YoutubeSource
from bili_asr.storage.database import connect_database
from tests.test_youtube_metadata_projection import REF


@pytest.mark.parametrize("raw_storage", [False, True])
def test_cli_source_import_reports_raw_coverage_and_metadata_reads_detached_backup(tmp_path, monkeypatch, capsys, raw_storage):
    root = tmp_path / "archive"
    initialize_archive(root, with_source_observations=raw_storage)
    source = YoutubeSource()
    source._information[REF] = {"id": REF.external_video_id, "title": "Private source",
                              "duration": 2, "description": "Two\nlines"}
    monkeypatch.setattr("bili_asr.sources.youtube_source.youtube_environment", lambda: {"ready": True})
    monkeypatch.setattr("bili_asr.sources.registry.SourceRegistry.source", lambda _registry, _ref: source)
    assert main(["source", "import", "--archive-root", str(root), "--youtube", REF.external_video_id]) == 0
    captured = capsys.readouterr()
    imported = json.loads(captured.out)
    assert imported["platform"] == "youtube" and imported["external_video_id"] == REF.external_video_id
    assert ("raw metadata coverage unavailable" in captured.err) is (not raw_storage)
    if not raw_storage:
        return
    detached = tmp_path / "detached.db"
    shutil.copy2(root / "archive.db", detached)
    before = detached.read_bytes()
    results = []
    for location in (("--archive-root", root), ("--database", detached)):
        assert main(["source", "metadata", location[0], str(location[1]), "--youtube", REF.external_video_id,
                     "--mapping-version", "source-superset/v2"]) == 0
        results.append(json.loads(capsys.readouterr().out))
    assert results[0] == results[1]
    assert results[0]["fields"]["description"] == "Two\nlines"
    assert detached.read_bytes() == before


@pytest.mark.parametrize("observations", [[], (object(),), (
    PlatformObservation.capture(platform="youtube", operation="details", endpoint="fixture",
        scope={"externalVideoId": "abcdefghijk"}, extractor="fixture", extractor_version="1",
        payload={"title": "Another video"}),)])
def test_source_video_rejects_untyped_or_foreign_observations(observations):
    with pytest.raises(ValueError, match="raw"):
        SourceVideoMetadata(REF, "Video", 1000, observations=observations)


def test_youtube_capture_without_installed_extractor_keeps_explicit_unavailable_version(monkeypatch):
    import bili_asr.sources.youtube_source as adapter
    def unavailable(_name):
        raise adapter.PackageNotFoundError("fixture absent")
    monkeypatch.setattr(adapter, "version", unavailable)
    source = YoutubeSource()
    source._information[REF] = {"id": REF.external_video_id, "title": "Source", "duration": 1}
    receipts = []
    source.set_observation_sink(receipts.append)
    assert source.metadata(REF).observations[0].envelope["extractor"]["version"] == "unavailable"
    assert len(receipts) == 1


@pytest.mark.parametrize("document,code", [("not json", "youtube_metadata_shape"),
    (json.dumps({"id": "abcdefghijk", "title": "Wrong video"}), "youtube_identity_mismatch"),
    (json.dumps({"id": REF.external_video_id, "is_live": True}), "youtube_live_unsupported")])
def test_invalid_youtube_responses_leave_failure_evidence_without_positive_cache(monkeypatch, document, code):
    source = YoutubeSource()
    monkeypatch.setattr(source, "_run", lambda *_args, **_kwargs: document)
    receipts = []
    source.set_observation_sink(receipts.append)
    with pytest.raises(GatewayError) as error:
        source.metadata(REF)
    assert error.value.code == code
    assert len(receipts) == 1 and receipts[0].envelope["state"] == "failed"
    assert receipts[0].envelope["errorCode"] == code
    assert REF not in source._information and REF not in source._observations


def test_gateway_transport_failure_records_exact_safe_code_and_retains_no_payload(monkeypatch):
    source = YoutubeSource()
    def fail(*_args, **_kwargs):
        raise GatewayResponseError(code="youtube_timeout")
    monkeypatch.setattr(source, "_run", fail)
    receipts = []
    source.set_observation_sink(receipts.append)
    with pytest.raises(GatewayError):
        source.metadata(REF)
    assert receipts[0].payload_json is None and receipts[0].envelope["errorCode"] == "youtube_timeout"


def test_refresh_refuses_parts_with_conflicting_adoption_before_any_upsert(tmp_path):
    from bili_asr.metadata_acceptance import SourceFieldReceipt
    from bili_asr.services.metadata_refresh import MetadataRefreshService
    from bili_asr.storage.metadata import MetadataRepository
    from tests.test_workflow_control_plane import _seed_part

    root = tmp_path / "archive"
    initialize_archive(root)
    with closing(connect_database(root / "archive.db")) as connection:
        _seed_part(connection)
        original = [tuple(row) for row in connection.execute("SELECT * FROM video_parts")]
        # Typed receipts have distinct identities. Their rejection is before
        # adoption validation and must roll back the prior part upserts.
        originals = [PlatformObservation.capture(platform="bilibili", operation="parts", endpoint="fixture",
            scope={"externalVideoId": "BVtest"}, extractor="fixture", extractor_version="1", payload=[])
                     for _ in range(2)]
        receipts = tuple(SourceFieldReceipt.create(field="parts", value=[], observation=item, pointer="",
            normalizer="bilibili-parts/v1", context={"bvid": "BVtest"}) for item in originals)
        first_cid = connection.execute("SELECT cid FROM video_parts WHERE page_index=0").fetchone()[0]
        class Gateway:
            async def get_video_parts(self, bvid, **_kwargs):
                return (VideoPart(bvid, 0, first_cid, "Updated first", 2000, receipts[0]),
                        VideoPart(bvid, 1, 56, "New second", 2000, receipts[1]))
        try:
            MetadataRefreshService(Gateway(), MetadataRepository(connection)).refresh(("BVtest",), operations=("parts",))
        except ValueError as error:
            assert "different source selection" in str(error)
        else:
            raise AssertionError("mixed provider selection receipts were accepted")
        assert [tuple(row) for row in connection.execute("SELECT * FROM video_parts")] == original


def test_private_export_resealed_review_cannot_claim_another_revision(tmp_path):
    from bili_asr.export_snapshot import ExportSnapshotError, _snapshot_id, _validate_snapshot
    from bili_asr.publication_export import export_editorial
    from tests.test_provenance_trace import manuscript
    connection, root, revision, edition, _release, _producers = manuscript(tmp_path)
    with closing(connection):
        output = tmp_path / "private"
        export_editorial(connection, revision_id=revision, edition_id=edition["edition_id"],
                         artifact_roots=(root,), output=output, include_provenance=True)
        review_path = output / "review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["revisionId"] = ("0" if review["revisionId"].startswith("f") else "f") + review["revisionId"][1:]
        review_path.write_text(json.dumps(review), encoding="utf-8")
        manifest_path = output / "editorial-export-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        next(item for item in manifest["files"] if item["path"] == "review.json")["sha256"] = hashlib.sha256(review_path.read_bytes()).hexdigest()
        manifest["snapshotId"] = _snapshot_id(manifest["files"], "editorial-export", "private-provenance-v1")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ExportSnapshotError, match="private provenance differs"):
            _validate_snapshot(output, "editorial-export")
