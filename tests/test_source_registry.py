"""Provider credentials are runtime configuration, never durable source facts."""
from dataclasses import asdict
import json
import sys

from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.services.source_workflow import compose_source_handlers
from bili_asr.sources.registry import SourceRegistry
from bili_asr.sources.youtube_source import YoutubeSource
from bili_asr.storage.sources import SourceRepository
from bili_asr.storage.workflow import AsrPolicy, WorkflowRepository
from bili_asr.workflow import WorkflowExecutor
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_workflow_control_plane import _profile
from tests import test_youtube_source as youtube_fixtures

REF = youtube_fixtures.REF
evidence = youtube_fixtures.evidence
extractor = youtube_fixtures.extractor


def test_runtime_cookie_environment_is_refreshed_and_explicit_path_takes_precedence(tmp_path, monkeypatch):
    registry = SourceRegistry(youtube_factory=lambda **kwargs: kwargs)
    first, second, explicit = (tmp_path / name for name in ("first", "second", "explicit"))
    monkeypatch.setenv("BILI_YOUTUBE_COOKIES", str(first))
    assert registry.source(REF)["cookie_file"] == first
    monkeypatch.setenv("BILI_YOUTUBE_COOKIES", str(second))
    assert registry.source(REF)["cookie_file"] == second
    preferred = SourceRegistry(cookie_file=explicit, youtube_factory=lambda **kwargs: kwargs)
    assert preferred.source(REF)["cookie_file"] == explicit
    monkeypatch.setenv("BILI_YOUTUBE_COOKIES", "   ")
    assert registry.source(REF)["cookie_file"] is None


def test_runtime_cookie_path_and_secret_do_not_enter_source_or_workflow_database(tmp_path, monkeypatch, extractor, evidence):
    cookies = tmp_path / "private-cookie-capability.txt"
    cookies.write_text("# Netscape HTTP Cookie File\nSECRET_COOKIE_VALUE", encoding="utf-8")
    monkeypatch.setenv("BILI_YOUTUBE_COOKIES", str(cookies))
    registry = SourceRegistry(youtube_factory=lambda **kwargs: YoutubeSource(
        command=(sys.executable, str(extractor)), **kwargs))
    source = registry.source(REF)
    metadata = source.metadata(REF)
    assert str(cookies) not in json.dumps(asdict(metadata))
    root = tmp_path / "archive"
    initialize_archive(root)
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        connection = session.connection
        with connection:
            part_id = SourceRepository(connection).upsert_video(metadata)
        workflow = WorkflowRepository(connection)
        workflow.plan(part_ids=[part_id], policy=AsrPolicy.BELOW_THRESHOLD,
                      profile_id=_profile(workflow), quality_threshold=.5)
        runtime = ArchiveWorkflowHandlers(connection, workflow, archive_root=root, sessdata=None)
        try:
            handlers = dict(runtime.handlers())
            handlers.update(compose_source_handlers(runtime, registry))
            summary = WorkflowExecutor(workflow, worker_id="cookie-runtime", handlers=handlers).run()
            assert summary.failed == 0 and summary.succeeded == 2
            context = connection.execute("SELECT access_context FROM source_caption_observations").fetchone()[0]
            assert context == "credentialed"
            durable = "\n".join(connection.iterdump())
            assert str(cookies) not in durable and "SECRET_COOKIE_VALUE" not in durable
        finally:
            runtime.close()
    invocations = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert all(args[args.index("--cookies") + 1] == str(cookies) for args in invocations)
