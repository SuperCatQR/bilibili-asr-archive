"""A provider-neutral acquisition reaches the real publication/search/export."""
from __future__ import annotations

import csv
import io
import json
import sys

import pytest

from bili_asr.archive_session import ArchiveSession, ArchiveAccessMode
from bili_asr.export import export_records
from bili_asr.search_index import TranscriptSearchIndex
from bili_asr.search_index.query import search_archive
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.services.archive_snapshot import save_snapshot,check_snapshot,restore_snapshot
from bili_asr.services.source_workflow import compose_source_handlers
from bili_asr.services.workflow_projection import workflow_records
from bili_asr.sources.registry import SourceRegistry
from bili_asr.sources.youtube_source import YoutubeSource
from bili_asr.storage.sources import SourceRepository
from bili_asr.storage.workflow import WorkflowRepository, AsrPolicy
from bili_asr.workflow import WorkflowExecutor
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_youtube_source import REF
from tests.test_youtube_source import extractor as extractor, evidence as evidence
from tests.test_workflow_control_plane import _profile


def test_youtube_caption_real_process_to_bundle_fts_export_and_snapshot(tmp_path,extractor,evidence):
    root = tmp_path / "archive"
    initialize_archive(root)
    source = YoutubeSource(command=(sys.executable,str(extractor)))
    with ArchiveSession(root,mode=ArchiveAccessMode.WRITE) as session:
        connection = session.connection
        with connection:
            part_id = SourceRepository(connection).upsert_video(source.metadata(REF))
        workflow = WorkflowRepository(connection)
        plan = workflow.plan(part_ids=[part_id],policy=AsrPolicy.BELOW_THRESHOLD,
                             profile_id=_profile(workflow),quality_threshold=.5)
        assert plan.subtitle_jobs == 1 and plan.audio_jobs == 0
        runtime = ArchiveWorkflowHandlers(connection,workflow,archive_root=root,sessdata=None)
        registry = SourceRegistry(youtube_factory=lambda **kwargs: YoutubeSource(command=(sys.executable,str(extractor)),**kwargs))
        handlers = dict(runtime.handlers())
        handlers.update(compose_source_handlers(runtime,registry))
        summary = WorkflowExecutor(workflow,worker_id="youtube-test",handlers=handlers).run()
        assert summary.failed == 0 and summary.succeeded == 2
        transcript = connection.execute("SELECT * FROM transcripts").fetchone()
        assert transcript["language"] == "en" and transcript["source_kind"] == "subtitle-cc"
        attempt = connection.execute("SELECT * FROM acquisition_attempts").fetchone()
        assert attempt["credential_verified"] == attempt["absence_verified"] == 0
        observation = connection.execute("SELECT * FROM source_caption_observations").fetchone()
        assert observation["state"] == "tracks" and observation["access_context"] == "anonymous"
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
        runtime.close()
    projected = workflow_records(root,with_text=True)
    entry = projected["youtube:dQw4w9WgXcQ:p0"]
    assert entry["status"] == "archived" and entry["transcript_text"] == "A complete English sentence."
    assert entry["pubdateUnix"] == 1577923200 and entry["sourcePublishedAt"] == "2020-01-02T00:00:00Z"
    assert entry["bvid"] is None and entry["cid"] is None
    markdown = (root / entry["md_path"]).read_text()
    assert "platform: \"youtube\"" in markdown and "bvid:" not in markdown and "cid:" not in markdown
    raw = json.loads((root / entry["raw_path"]).read_text())
    assert raw["sourceMetadata"]["externalVideoId"] == REF.external_video_id
    before = (root / "archive.db").read_bytes()
    missing = search_archive(root,"English")
    assert not missing.hits and missing.diagnostics
    assert search_archive(root,"English",scope="metadata").hits[0].platform == "youtube"
    assert (root / "archive.db").read_bytes() == before
    index = TranscriptSearchIndex(root)
    assert index.build() == 1 and index.build() == 0
    assert index.count() == 1 and index.stamp() == transcript["transcript_id"]
    before = (root / "archive.db").read_bytes()
    hit = search_archive(root,"English").hits[0]
    assert hit.bvid is None and hit.to_dict()["platform"] == "youtube"
    assert hit.to_dict()["url"].endswith(REF.external_video_id)
    assert len(search_archive(root,"English",scope="all").hits) == 2
    exported = json.loads(export_records(root,"json",with_text=True))
    assert exported[0]["platform"] == "youtube" and exported[0]["external_video_id"] == REF.external_video_id
    rows = list(csv.DictReader(io.StringIO(export_records(root,"csv",with_text=True))))
    assert rows[0]["bvid"] == "" and rows[0]["platform"] == "youtube"
    assert (root / "archive.db").read_bytes() == before
    snapshot = tmp_path / "archive.zip"
    save_snapshot(root,snapshot)
    assert check_snapshot(snapshot)["valid"]
    restored = tmp_path / "restored"
    restore_snapshot(snapshot,restored)
    assert workflow_records(restored,with_text=True)[entry["work_id"]]["transcript_text"] == entry["transcript_text"]


@pytest.mark.parametrize("code",["auth_failed","rate_limited","youtube_caption_shape"])
def test_youtube_body_failure_never_attests_absence(tmp_path,monkeypatch,extractor,evidence,code):
    from bili_asr.sources.models import GatewayResponseError
    root = tmp_path / "archive"
    initialize_archive(root)
    source = YoutubeSource(command=(sys.executable,str(extractor)))
    def fail(*args,**kwargs):
        raise GatewayResponseError(detail="secret provider diagnostic",code=code)
    async def bad_body(*args,**kwargs):
        fail()
    source.read_body = bad_body
    with ArchiveSession(root,mode=ArchiveAccessMode.WRITE) as session:
        connection = session.connection
        with connection:
            part_id = SourceRepository(connection).upsert_video(source.metadata(REF))
        workflow = WorkflowRepository(connection)
        workflow.plan(part_ids=[part_id],policy=AsrPolicy.BELOW_THRESHOLD,
                      profile_id=_profile(workflow),quality_threshold=.5)
        runtime = ArchiveWorkflowHandlers(connection,workflow,archive_root=root,sessdata=None)
        handlers = compose_source_handlers(runtime,SourceRegistry(youtube_factory=lambda **kwargs: source))
        result = WorkflowExecutor(workflow,worker_id="youtube-test",handlers=handlers).run(limit=1)
        assert result.failed == 1
        job = connection.execute("SELECT * FROM workflow_jobs").fetchone()
        assert job["last_error_code"] == code
        assert not connection.execute("SELECT 1 FROM transcripts").fetchone()
        assert not connection.execute("SELECT 1 FROM v_missing_audio").fetchone()
        observation = connection.execute("SELECT * FROM source_caption_observations").fetchone()
        assert observation["state"] == "unavailable" and observation["error_code"] == code
        assert "secret provider" not in json.dumps(dict(observation))
