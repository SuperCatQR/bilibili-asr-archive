"""Provider acquisitions composed from explicit installation and workflow ports."""
from __future__ import annotations

import asyncio
import tempfile
import time
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from bili_asr.canonical_json import canonical
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.sources.models import GatewayError, GatewayResponseError
from bili_asr.sources.registry import SourceRegistry
from bili_asr.storage.models import AcquisitionRunRecord, TranscriptSegmentRecord
from bili_asr.storage.sources import SourceRepository, acquisition_selector
from bili_asr.storage.transcripts import TranscriptRepository
from bili_asr.workflow_errors import JobExecutionError
from bili_asr.workflow_models import JobKind, WorkflowJob


class SourceWorkflowControl(Protocol):
    def assert_lease(self, job: WorkflowJob) -> None: ...
    def owned_transaction(self, job: WorkflowJob) -> AbstractContextManager: ...
    def request_publication(self, *, video_part_id: int, transcript_id: int,
                            source_job: WorkflowJob) -> tuple[str, bool]: ...


@dataclass(frozen=True)
class SourceWorkflowPorts:
    """Only the capabilities provider acquisitions consume, composed by the app."""

    connection: sqlite3.Connection
    workflow: SourceWorkflowControl
    artifact_roots: ArtifactRoots
    bilibili_subtitle: Callable[[WorkflowJob], Mapping[str, Any]]
    bilibili_audio: Callable[[WorkflowJob], Mapping[str, Any]]
    store_audio: Callable[[WorkflowJob, Mapping[str, Any], Path, Path], Mapping[str, Any]]


class SourceWorkflowHandlers:
    """Dispatch source acquisition; scheduling and inference remain existing ports."""
    def __init__(self, ports: SourceWorkflowPorts, registry: SourceRegistry):
        self.ports, self.registry = ports, registry
        self.connection, self.workflow = ports.connection, ports.workflow

    def handlers(self):
        return {JobKind.SUBTITLE: self.subtitle, JobKind.AUDIO: self.audio}

    def _source(self, job, part):
        return self.registry.source(part["content_ref"], checkpoint=lambda: self.workflow.assert_lease(job))

    def subtitle(self, job):
        part = SourceRepository(self.connection).part(job.video_part_id)
        if part["platform"] == "bilibili":
            return self.ports.bilibili_subtitle(job)
        self.workflow.assert_lease(job)
        source = self._source(job, part)
        policy = self.registry.caption_policy(part["content_ref"])
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
                raise GatewayResponseError(code=policy.translation_only_error)
            attempted = 0
            for caption in ordered[:policy.candidate_limit]:
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
                    raise GatewayResponseError(code=policy.candidate_budget_error)
                raise GatewayResponseError(code=failures[0] if failures else policy.body_unavailable_error)
            if chosen is None:
                if not access.verified:
                    raise GatewayResponseError(code=policy.access_unverified_error)
                with self.workflow.owned_transaction(job):
                    self.connection.execute(
                        "INSERT INTO acquisition_attempts(run_id,video_part_id,outcome,error_code,transcript_id,started_at,finished_at,credential_verified,absence_verified) "
                        "VALUES (?,?,'no-subtitle',NULL,NULL,?,?,0,0)", (run_id, job.video_part_id, started, int(time.time())))
                    self._observation(job, run_id, policy.version, "no-tracks", access.access_context,
                        {"extractor": policy.extractor, "policy": policy.version, "verified": access.verified})
                result = {"run_id": run_id, "outcome": "no-subtitle", "platform": part["platform"], "policy_version": policy.version}
            else:
                # A whole result context also includes the provenance observation.
                from contextlib import contextmanager
                @contextmanager
                def result_context():
                    with self.workflow.owned_transaction(job):
                        yield
                        self._observation(job, run_id, policy.version, "tracks", access.access_context,
                                          {**chosen.provenance(), "candidate_count": len(ordered),
                                           "attempted_candidates": attempted, "failed_candidates": failures,
                                           "selection_policy": policy.selection})
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
                          "platform": part["platform"], "caption_provenance": chosen.provenance()}
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
                    self._observation(job, run_id, policy.version, "unavailable", "anonymous", {"extractor": policy.extractor}, exc.code)
            finally:
                repository.finish_acquisition_run(run_id, int(time.time()), outcome="failed")
            raise JobExecutionError(exc.code, {"platform": part["platform"]}) from None
        except BaseException:
            repository.finish_acquisition_run(run_id, int(time.time()), outcome="failed")
            raise

    def _observation(self, job, run_id, policy_version, state, context, provenance, error_code=None):
        self.connection.execute("INSERT INTO source_caption_observations(video_part_id,run_id,policy_version,state,access_context,error_code,observed_at,provenance_json) "
            "VALUES (?,?,?,?,?,?,?,?)", (job.video_part_id, run_id, policy_version, state, context, error_code, int(time.time()), canonical(provenance)))

    def audio(self, job):
        part = SourceRepository(self.connection).part(job.video_part_id)
        if part["platform"] == "bilibili":
            return self.ports.bilibili_audio(job)
        self.workflow.assert_lease(job)
        from bili_asr.services.workflow_audio_access import (
            retained_audio,
            verified_local_audio,
        )
        retained = retained_audio(self.connection, job.video_part_id)
        if retained is not None:
            verified_local_audio(self.connection, self.ports.artifact_roots, retained)
            return {key: retained[key] for key in ("storage_key", "sha256", "duration_ms", "object_id")}
        row = self.connection.execute("SELECT a.storage_key,a.sha256,a.duration_ms FROM part_audio_objects p JOIN audio_objects a USING(audio_id) WHERE p.video_part_id=? ORDER BY a.audio_id DESC LIMIT 1", (job.video_part_id,)).fetchone()
        if row is not None:
            from bili_asr.artifact_inventory import stream_hash
            from bili_asr.artifact_root import usable_audio_path
            from bili_asr.path_policy import confined_audio_file
            found = usable_audio_path(self.ports.artifact_roots, (row["storage_key"],))
            if found is None:
                raise JobExecutionError("audio_missing")
            base, declared, _path = found
            with confined_audio_file(base, declared) as path, path.open("rb") as stream:
                _size, digest = stream_hash(stream)
            if digest != row["sha256"]:
                raise JobExecutionError("audio_digest_mismatch")
            self.workflow.assert_lease(job)
            return dict(row)
        directory = self.ports.artifact_roots.write_base / "audio"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".workflow-audio-", dir=directory) as name:
            staging = Path(name)
            source = self._source(job, part)
            try:
                final = source.download_audio(part["content_ref"], staging / part["artifact_stem"], staging_root=staging)
            except GatewayError as exc:
                raise JobExecutionError(exc.code, {"platform": part["platform"]}) from None
            self.workflow.assert_lease(job)
            return self.ports.store_audio(job, part, final, directory / final.name)


def compose_source_handlers(ports: SourceWorkflowPorts, registry: SourceRegistry | None = None) -> dict:
    """Actual application composition overlays provider acquisitions only."""
    return SourceWorkflowHandlers(ports, registry or SourceRegistry()).handlers()
