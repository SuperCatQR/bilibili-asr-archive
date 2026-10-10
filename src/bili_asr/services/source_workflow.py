"""YouTube acquisition composition using the existing workflow and lease fence."""
from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from bili_asr.canonical_json import canonical
from bili_asr.sources.models import GatewayError, GatewayResponseError
from bili_asr.sources.registry import SourceRegistry
from bili_asr.storage.models import AcquisitionRunRecord, TranscriptSegmentRecord
from bili_asr.storage.sources import SourceRepository, acquisition_selector
from bili_asr.storage.transcripts import TranscriptRepository
from bili_asr.workflow_models import JobKind
from bili_asr.workflow_errors import JobExecutionError


class SourceWorkflowHandlers:
    """Dispatch source acquisition; scheduling and inference remain existing ports."""
    def __init__(self, archive, registry: SourceRegistry):
        self.archive, self.registry = archive, registry
        self.connection, self.workflow = archive.connection, archive.repository

    def handlers(self):
        return {JobKind.SUBTITLE: self.subtitle, JobKind.AUDIO: self.audio}

    def _source(self, job, part):
        return self.registry.source(part["content_ref"], checkpoint=lambda: self.workflow.assert_lease(job))

    def subtitle(self, job):
        part = SourceRepository(self.connection).part(job.video_part_id)
        if part["platform"] == "bilibili":
            return self.archive.subtitle(job)
        self.workflow.assert_lease(job)
        source = self._source(job, part)
        repository = TranscriptRepository(self.connection, write_transaction=lambda: self.workflow.owned_transaction(job))
        started = int(time.time())
        run_id = uuid4().hex
        selector, target = acquisition_selector(part)
        repository.start_acquisition_run(AcquisitionRunRecord(run_id, "subtitle", selector, target, 1, False, started))
        try:
            tracks = asyncio.run(source.list_tracks(part["content_ref"]))
            access = asyncio.run(source.verify_access(part["content_ref"]))
            self.workflow.assert_lease(job)
            captions = source.captions(part["content_ref"])
            preferred_language = part.get("original_language")
            # Automatic translations are visible inventory, but are not a
            # substitute for original captions or evidence of no subtitles.
            ordered = sorted((caption for caption in captions if caption.translated is not True), key=lambda caption: (
                caption.track.is_ai,
                not bool(preferred_language and caption.language.split("-", 1)[0] == preferred_language.split("-", 1)[0]),
                caption.language))
            chosen, segments = None, ()
            failures = []
            if tracks and not ordered:
                raise GatewayResponseError(code="youtube_caption_translation_only")
            attempted = 0
            for caption in ordered[:32]:
                attempted += 1
                try:
                    segments = asyncio.run(source.read_body(caption.track, part["content_ref"])).segments
                except GatewayError as exc:
                    if exc.code in {"auth_failed", "auth_error", "rate_limited"}:
                        raise
                    failures.append(exc.code)
                    self.workflow.assert_lease(job)
                    continue
                self.workflow.assert_lease(job)
                if segments:
                    chosen = caption
                    break
            # Successful metadata/listing provides anonymous visibility facts;
            # empty caption bodies after listing remain unavailable, not absence.
            if chosen is None and tracks:
                if len(ordered) > attempted:
                    raise GatewayResponseError(code="youtube_caption_candidate_budget")
                raise GatewayResponseError(code=failures[0] if failures else "youtube_caption_body_unavailable")
            if chosen is None:
                if not access.verified:
                    raise GatewayResponseError(code="youtube_access_unverified")
                with self.workflow.owned_transaction(job):
                    self.connection.execute(
                        "INSERT INTO acquisition_attempts(run_id,video_part_id,outcome,error_code,transcript_id,started_at,finished_at,credential_verified,absence_verified) "
                        "VALUES (?,?,'no-subtitle',NULL,NULL,?,?,0,0)", (run_id, job.video_part_id, started, int(time.time())))
                    self._observation(job, run_id, "no-tracks", access.access_context,
                        {"extractor": "yt-dlp", "policy": "youtube-public-v1", "verified": access.verified})
                result = {"run_id": run_id, "outcome": "no-subtitle", "platform": "youtube", "policy_version": "youtube-public-v1"}
            else:
                # A whole result context also includes the provenance observation.
                from contextlib import contextmanager
                @contextmanager
                def result_context():
                    with self.workflow.owned_transaction(job):
                        yield
                        self._observation(job, run_id, "tracks", access.access_context,
                                          {**chosen.provenance(), "candidate_count": len(ordered),
                                           "attempted_candidates": attempted, "failed_candidates": failures,
                                           "selection_policy": "youtube-original-captions-v1"})
                result_repository = TranscriptRepository(self.connection, write_transaction=result_context)
                written = result_repository.record_acquired_transcript(run_id=run_id, video_part_id=job.video_part_id,
                    source_kind="subtitle-ai" if chosen.track.is_ai else "subtitle-cc", language=chosen.language,
                    segments=tuple(TranscriptSegmentRecord(item.start_ms, item.end_ms, item.text) for item in segments),
                    started_at=started, finished_at=int(time.time()), created_at=int(time.time()))
                publication_id, _ = self.workflow.request_publication(video_part_id=job.video_part_id,
                    transcript_id=written.transcript_id, source_job=job)
                result = {"run_id": run_id, "transcript_id": written.transcript_id, "version": written.version,
                          "source_kind": "subtitle-ai" if chosen.track.is_ai else "subtitle-cc",
                          "language": chosen.language, "publication_job_id": publication_id,
                          "platform": "youtube", "caption_provenance": chosen.provenance()}
            repository.finish_acquisition_run(run_id, int(time.time()))
            return result
        except GatewayError as exc:
            try:
                with self.workflow.owned_transaction(job):
                    # The body failure and unavailable observation share the same
                    # lease fence; neither establishes subtitle exhaustion.
                    self.connection.execute(
                        "INSERT INTO acquisition_attempts(run_id,video_part_id,outcome,error_code,transcript_id,started_at,finished_at) "
                        "VALUES (?,?,'failed',?,NULL,?,?)", (run_id, job.video_part_id, exc.code, started, int(time.time())))
                    self._observation(job, run_id, "unavailable", "anonymous", {"extractor": "yt-dlp"}, exc.code)
            finally:
                repository.finish_acquisition_run(run_id, int(time.time()), outcome="failed")
            raise JobExecutionError(exc.code, {"platform": "youtube"}) from None
        except BaseException:
            repository.finish_acquisition_run(run_id, int(time.time()), outcome="failed")
            raise

    def _observation(self, job, run_id, state, context, provenance, error_code=None):
        self.connection.execute("INSERT INTO source_caption_observations(video_part_id,run_id,policy_version,state,access_context,error_code,observed_at,provenance_json) "
            "VALUES (?,?,'youtube-public-v1',?,?,?,?,?)", (job.video_part_id, run_id, state, context, error_code, int(time.time()), canonical(provenance)))

    def audio(self, job):
        part = SourceRepository(self.connection).part(job.video_part_id)
        if part["platform"] == "bilibili":
            return self.archive.audio(job)
        self.workflow.assert_lease(job)
        row = self.connection.execute("SELECT a.storage_key,a.sha256,a.duration_ms FROM part_audio_objects p JOIN audio_objects a USING(audio_id) WHERE p.video_part_id=? ORDER BY a.audio_id DESC LIMIT 1", (job.video_part_id,)).fetchone()
        if row is not None:
            from bili_asr.artifact_root import usable_audio_path
            from bili_asr.path_policy import confined_audio_file
            from bili_asr.artifact_inventory import stream_hash
            found = usable_audio_path(self.archive.artifact_roots, (row["storage_key"],))
            if found is None:
                raise JobExecutionError("audio_missing")
            base, declared, _path = found
            with confined_audio_file(base, declared) as path, path.open("rb") as stream:
                _size, digest = stream_hash(stream)
            if digest != row["sha256"]:
                raise JobExecutionError("audio_digest_mismatch")
            self.workflow.assert_lease(job)
            return dict(row)
        directory = self.archive.artifact_roots.write_base / "audio"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".workflow-audio-", dir=directory) as name:
            staging = Path(name)
            source = self._source(job, part)
            try:
                final = source.download_audio(part["content_ref"], staging / part["artifact_stem"], staging_root=staging)
            except GatewayError as exc:
                raise JobExecutionError(exc.code, {"platform": "youtube"}) from None
            self.workflow.assert_lease(job)
            return self.archive.store_audio(job, part, final, directory / final.name)


def compose_source_handlers(archive, registry: SourceRegistry | None = None) -> dict:
    """Actual application composition overlays provider acquisitions only."""
    return SourceWorkflowHandlers(archive, registry or SourceRegistry()).handlers()
