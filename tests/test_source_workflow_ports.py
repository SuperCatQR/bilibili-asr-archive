"""Provider acquisitions consume declared capabilities, never an archive handler."""
from dataclasses import dataclass, replace

from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.platform_identity import ContentRef
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.services.source_workflow import SourceWorkflowPorts, compose_source_handlers
from bili_asr.source_video import SourceVideoMetadata
from bili_asr.sources.caption_policy import YOUTUBE_CAPTION_POLICY
from bili_asr.sources.models import SubtitleBodyRead, SubtitleSegment, SubtitleTrack
from bili_asr.sources.protocols import SourceAccessObservation
from bili_asr.sources.registry import SourceRegistry
from bili_asr.storage.sources import SourceRepository
from bili_asr.storage.workflow import AsrPolicy, AsrProfile, WorkflowRepository
from bili_asr.workflow_models import JobKind


@dataclass(frozen=True)
class ExampleCaption:
    track: SubtitleTrack
    language: str = "en"
    original_language: str = "en"
    translated: bool = False

    def provenance(self):
        return {"extractor": "example-port", "language": self.language}


class ExampleSource:
    """Independent protocol implementation with no provider adapter inheritance."""
    caption = ExampleCaption(SubtitleTrack("en", "English", False, "original-en"))

    def metadata(self, ref):
        return SourceVideoMetadata(ref, "Synthetic source", 2000, original_language="en")

    def captions(self, ref):
        return (self.caption,)

    async def list_tracks(self, ref):
        return (self.caption.track,)

    async def read_body(self, track, ref):
        return SubtitleBodyRead((SubtitleSegment(0, 2000, "A synthetic caption."),), 1)

    async def fetch_segments(self, track, ref):
        return (await self.read_body(track, ref)).segments

    async def verify_access(self, ref):
        return SourceAccessObservation("anonymous", True)

    def download_audio(self, ref, target, *, staging_root):
        assert target.parent == staging_root
        final = target.with_suffix(".flac")
        final.write_bytes(b"synthetic audio for the injected installer")
        return final


def test_independent_source_and_explicit_ports_complete_subtitle_and_audio(tmp_path):
    root = tmp_path / "archive"
    initialize_archive(root)
    source = ExampleSource()
    ref = ContentRef("youtube", "abcdefghijk")
    policy = replace(YOUTUBE_CAPTION_POLICY, selection="example-original-v1", extractor="example-port")
    registry = SourceRegistry(factories={"youtube": lambda **kwargs: source},
                              caption_policies={"youtube": policy})
    with ArchiveSession(root, mode=ArchiveAccessMode.WRITE) as session:
        connection = session.connection
        with connection:
            part_id = SourceRepository(connection).upsert_video(source.metadata(ref))
        workflow = WorkflowRepository(connection)
        profile_id = workflow.register_profile(AsrProfile("example", "local", device="cpu"))
        workflow.plan(part_ids=[part_id], policy=AsrPolicy.ALL, profile_id=profile_id)
        installed = []
        def legacy_callback(job):
            raise AssertionError("an independent source must not invoke legacy acquisition")
        def install(job, part, staging, destination):
            workflow.assert_lease(job)
            assert staging.parent.name.startswith(".workflow-audio-")
            assert staging.suffix == destination.suffix == ".flac"
            assert staging.read_bytes().startswith(b"synthetic audio")
            installed.append(destination)
            return {"storage_key": "audio/" + destination.name, "sha256": "a" * 64, "duration_ms": 2000}
        ports = SourceWorkflowPorts(connection, workflow, session.artifact_roots,
                                    legacy_callback, legacy_callback, install)
        handlers = compose_source_handlers(ports, registry)
        subtitle = workflow.claim("source", kinds=(JobKind.SUBTITLE,))
        result = handlers[JobKind.SUBTITLE](subtitle)
        workflow.finish(subtitle.job_id, worker_id="source", result=result)
        assert result["caption_provenance"]["extractor"] == "example-port"
        observation = connection.execute("SELECT provenance_json FROM source_caption_observations").fetchone()[0]
        assert "example-original-v1" in observation
        audio = workflow.claim("source", kinds=(JobKind.AUDIO,))
        result = handlers[JobKind.AUDIO](audio)
        assert result["storage_key"].endswith(".flac") and len(installed) == 1
        assert not list((root / "audio").glob(".workflow-audio-*"))
