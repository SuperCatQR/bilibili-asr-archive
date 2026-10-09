"""Source tag acquisition evidence and immutable edition propagation."""
from __future__ import annotations

import json
import importlib
import pytest

from bili_asr import cli
from bili_asr.services.video_tags import refresh_video_tags
from bili_asr.sources.models import GatewayRateLimited, GatewayShapeError, VideoTag
from bili_asr.storage import open_database, MetadataRepository, VideoTagRecord
from bili_asr.publication import create_edition, get_edition
from bili_asr.publication_export import export_publication_drafts
from bili_asr.publication_tags import sync_source_tags
from tests.fixtures.fake_bilibili_gateway import FakeGateway
from tests.test_metadata_ingest import _page, _summary, _part, _ingestor, MID
from tests.test_publication import seeded_publication
from tests.test_ai_editorial import insert_record, record, runtime, FakeClient
from bili_asr.editorial import EditorialConfig


@pytest.mark.parametrize("tags,state,success,failure", [
    (None, "unavailable", 0, 1), ((), "success_empty", 1, 0),
    ((VideoTag(1, "original", "type"),), "success_nonempty", 1, 0),
    (GatewayRateLimited(), "unavailable", 0, 1),
    (GatewayShapeError(), "unavailable", 0, 1),
])
def test_tag_observations_distinguish_optional_failure_from_empty(tmp_path, tags, state, success, failure):
    gateway = FakeGateway()
    gateway.script_page(1, _page(1, _summary("BVtag")))
    gateway.script_parts("BVtag", (_part("BVtag", 0),))
    gateway.script_tags("BVtag", tags)
    gateway.script_page(2, _page(2))
    connection = open_database(tmp_path)
    try:
        result = _ingestor(gateway, MetadataRepository(connection)).collect_user_pages(MID)
        assert result.outcome == "complete"
        assert (result.tag_attempt_count, result.tag_success_count, result.tag_failure_count) == (1, success, failure)
        observation = connection.execute("SELECT * FROM video_tag_observations").fetchone()
        assert observation["state"] == state and observation["observed_at"] >= 0
        assert observation["run_id"] == result.run_id
        assert observation["error_code"] == (getattr(tags, "code", "unavailable") if failure else None)
    finally:
        connection.close()


def test_refresh_preserves_last_successful_set_and_can_clear_only_on_success(tmp_path):
    connection, _, _ = seeded_publication(tmp_path)
    repository = MetadataRepository(connection)
    gateway = FakeGateway()
    try:
        with repository.transaction():
            repository.upsert_video_tags("BVtest", [VideoTagRecord("BVtest", 1, "original", "type")])
        gateway.script_tags("BVtest", None)
        assert refresh_video_tags(connection, gateway, ["BVtest"]) == {"attempted": 1, "succeeded": 0, "failed": 1}
        assert connection.execute("SELECT tag_name FROM video_tags").fetchone()[0] == "original"
        assert connection.execute("SELECT state FROM video_tag_observations").fetchone()[0] == "unavailable"
        gateway.script_tags("BVtest", ())
        assert refresh_video_tags(connection, gateway, ["BVtest"])["succeeded"] == 1
        assert not connection.execute("SELECT * FROM video_tags").fetchall()
        assert connection.execute("SELECT state FROM video_tag_observations").fetchone()[0] == "success_empty"
    finally:
        connection.close()


def test_create_freezes_deduplicated_source_names_and_sync_is_audited_cas(tmp_path):
    root = tmp_path / "archive"
    connection, revision, roots = seeded_publication(root)
    repository = MetadataRepository(connection)
    try:
        with repository.transaction():
            repository.upsert_video_tags("BVtest", [VideoTagRecord("BVtest", 1, "original", "type"),
                                                       VideoTagRecord("BVtest", 2, "original", "type"),
                                                       VideoTagRecord("BVtest", 3, "another", "type")])
        first = create_edition(connection, revision_id=revision, artifact_roots=roots, actor="creator")
        assert first["content"]["tags"] == ["original", "another"]
        first_hash = first["content_sha256"]
        gateway = FakeGateway()
        gateway.script_tags("BVtest", (VideoTag(1, "updated", "type"),))
        refresh_video_tags(connection, gateway, ["BVtest"])
        assert get_edition(connection, first["edition_id"])["content"]["tags"] == ["original", "another"]
        second = sync_source_tags(connection, edition_id=first["edition_id"], actor="operator", note="source metadata")
        assert second["content"]["tags"] == ["updated"]
        assert second["review_status"] == "pending-review"
        assert get_edition(connection, first["edition_id"])["content_sha256"] == first_hash
        with pytest.raises(ValueError, match="current edition"):
            sync_source_tags(connection, edition_id=first["edition_id"], actor="stale", note="stale")
        event = connection.execute("SELECT actor, note FROM publication_events ORDER BY event_id DESC").fetchone()
        assert event["actor"] == "operator" and "Source video_tags sync" in event["note"]
        output = tmp_path / "drafts"
        export_publication_drafts(connection, artifact_roots=roots, output=output)
        assert json.loads((output / "catalog.json").read_text(encoding="utf-8"))["articles"][0]["tags"] == ["updated"]
    finally:
        connection.close()


def test_missing_tags_warn_and_failed_observation_cannot_clear_edition(tmp_path, capsys, monkeypatch):
    connection, revision, roots = seeded_publication(tmp_path)
    try:
        assert cli.main(["publication", "create", "--archive-root", str(tmp_path), "--revision-id", revision,
                         "--actor", "editor", "--format", "json"]) == 0
        output = capsys.readouterr()
        assert "tag coverage not_attempted" in output.err
        edition = json.loads(output.out)
        with pytest.raises(ValueError, match="coverage incomplete"):
            sync_source_tags(connection, edition_id=edition["edition_id"], actor="operator", note="retry")
        gateway = FakeGateway()
        gateway.script_tags("BVtest", None)
        # Other metadata tests evict the adapter from sys.modules; import the
        # current module instead of patching a stale package attribute.
        adapter = importlib.import_module("bili_asr.sources.bilibili_api_gateway")
        monkeypatch.setattr(adapter, "BilibiliApiGateway", lambda **kwargs: gateway)
        assert cli.main(["fetch-tags", "--archive-root", str(tmp_path), "--bvid", "BVtest"]) == 2
        assert "coverage incomplete" in capsys.readouterr().err
        gateway.script_tags("BVtest", ())
        assert cli.main(["fetch-tags", "--archive-root", str(tmp_path), "--bvid", "BVtest"]) == 0
        assert cli.main(["publication", "sync-source-tags", "--archive-root", str(tmp_path),
                         "--edition-id", edition["edition_id"], "--actor", "operator", "--note", "empty observed",
                         "--format", "json"]) == 0
    finally:
        connection.close()


def test_observation_extension_preserves_existing_archive_manuscripts(tmp_path):
    connection, revision, roots = seeded_publication(tmp_path)
    first = create_edition(connection, revision_id=revision, artifact_roots=roots, actor="creator")
    with connection:
        connection.execute("DROP TABLE video_tag_observations")
    connection.close()
    connection = open_database(tmp_path)
    try:
        assert get_edition(connection, first["edition_id"])["content_sha256"] == first["content_sha256"]
        assert connection.execute("SELECT COUNT(*) FROM video_tag_observations").fetchone()[0] == 0
    finally:
        connection.close()


def test_multipart_uses_video_source_tags_without_leaking_other_video_tags(tmp_path):
    connection, revision, roots = seeded_publication(tmp_path)
    try:
        with connection:
            connection.execute("INSERT INTO videos SELECT 'BVother', 2002, mid, title, pubdate, created_at, updated_at FROM videos WHERE bvid='BVtest'")
            connection.execute("INSERT INTO video_parts SELECT 2, bvid, 1, 22, title, duration_ms, processing_status, created_at, updated_at FROM video_parts WHERE video_part_id=1")
            connection.execute("INSERT INTO video_tags VALUES ('BVtest', 1, 'original', 'type')")
            connection.execute("INSERT INTO video_tags VALUES ('BVother', 1, 'original', 'type')")
            connection.execute("INSERT INTO video_tags VALUES ('BVother', 2, 'unrelated', 'type')")
        insert_record(connection, record(transcript_id=2, part=2))
        workflow, repository, _, executor = runtime(connection, roots[0], FakeClient())
        prepared = repository.prepare(2, None, EditorialConfig())
        jobs = workflow.request_editorial(video_part_id=2, input_id=prepared['input_id'])
        assert executor.run().succeeded == 2
        second_revision = repository.revision_for_job(jobs[0])
        first = create_edition(connection, revision_id=revision, artifact_roots=roots, actor='creator')
        second = create_edition(connection, revision_id=second_revision, artifact_roots=roots, actor='creator')
        assert first['content']['tags'] == second['content']['tags'] == ['original']
    finally:
        connection.close()


def test_source_tag_sync_keeps_approved_release_bytes_and_head(tmp_path):
    from tests.test_publication import approve
    from bili_asr.publication import publish_edition, verify_release
    connection, revision, roots = seeded_publication(tmp_path)
    try:
        first = create_edition(connection, revision_id=revision, artifact_roots=roots, actor='creator')
        approve(connection, first)
        release = publish_edition(connection, edition_id=first['edition_id'], artifact_roots=roots,
                                  write_root=roots[0], actor='publisher')
        original = verify_release(connection, release['release_id'], roots)[2]
        gateway = FakeGateway()
        gateway.script_tags('BVtest', (VideoTag(1, 'original', 'type'),))
        refresh_video_tags(connection, gateway, ['BVtest'])
        second = sync_source_tags(connection, edition_id=first['edition_id'], actor='editor', note='source')
        assert second['review_status'] == 'pending-review'
        assert second['current_release_id'] == release['release_id']
        assert verify_release(connection, release['release_id'], roots)[2] == original
    finally:
        connection.close()


def test_tag_commands_acquire_archive_access_before_dispatch(tmp_path, monkeypatch):
    from contextlib import contextmanager
    held = []

    @contextmanager
    def access(root):
        held.append(root)
        try:
            yield
        finally:
            held.pop()

    def handler(args):
        assert held == [str(tmp_path)]
        return 0

    monkeypatch.setattr(cli.main, "archive_access", access)
    monkeypatch.setattr(cli, "_cmd_fetch_tags", handler)
    monkeypatch.setattr(cli, "_cmd_publication", handler)
    assert cli.main(["fetch-tags", "--archive-root", str(tmp_path)]) == 0
    assert cli.main(["publication", "sync-source-tags", "--archive-root", str(tmp_path),
                     "--edition-id", "expected", "--actor", "operator", "--note", "source"]) == 0
