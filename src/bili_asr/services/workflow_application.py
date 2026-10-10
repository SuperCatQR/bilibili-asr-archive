"""Workflow use cases and per-invocation adapter composition."""

from __future__ import annotations

import math
import signal
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bili_asr.archive_session import ArchiveSession
from bili_asr.editorial import EditorialConfig
from bili_asr.storage.editorial import EditorialRepository
from bili_asr.storage.workflow import WorkflowRepository
from bili_asr.storage.workflow_selection import WorkflowSelection, resolve_workflow_selection
from bili_asr.transcript_selection import choose_transcript
from bili_asr.workflow import ExecutionSummary, WorkflowExecutor
from bili_asr.workflow_models import AsrPolicy, AsrProfile, JobKind, WorkflowPlan


WORKER_ROLES = {
    "asr": (JobKind.ASR,),
    "acquisition": (JobKind.SUBTITLE, JobKind.AUDIO),
    "editorial": (JobKind.PROOFREAD, JobKind.RENDER_DOCUMENT),
    "cpu": (JobKind.SUBTITLE, JobKind.AUDIO, JobKind.PUBLISH),
}


@dataclass(frozen=True)
class PlannedWorkflow:
    selection: WorkflowSelection
    profile_id: int
    jobs: WorkflowPlan


class WorkflowApplication:
    def __init__(self, session: ArchiveSession):
        self.session = session
        self.repository = WorkflowRepository(session.connection)

    def plan(self, *, part_ids: Iterable[int] | None, bvids: Iterable[str] | None,
             page_index: int | None, policy: AsrPolicy, profile: AsrProfile,
             quality_threshold: float | None, editorial_config: Mapping[str, Any] | None) -> PlannedWorkflow:
        selection = resolve_workflow_selection(self.session.connection, part_ids=part_ids,
                                               bvids=bvids, page_index=page_index)
        profile_id, jobs = self.repository.plan_with_profile(
            part_ids=selection.part_ids, policy=policy, profile=profile,
            quality_threshold=quality_threshold, editorial_config=editorial_config)
        return PlannedWorkflow(selection, profile_id, jobs)

    def publish(self, part_ids: Iterable[int]) -> list[dict[str, Any]]:
        selection = resolve_workflow_selection(self.session.connection, part_ids=part_ids)
        selected = []
        for target in selection.targets:
            # The processing unit ID is authoritative for every platform. BVID is
            # a compatibility field and is absent for a YouTube unit.
            candidate = choose_transcript(self.session.connection.execute(
                "SELECT transcript_id,source_kind,language,version FROM transcripts WHERE video_part_id=?",
                (target.video_part_id,)).fetchall())
            if candidate is None:
                raise ValueError(f"no stored transcript for {target.work_id}")
            selected.append((target, int(candidate["transcript_id"])))
        with self.repository.commit_guard.transaction():
            return [self._request_publication(target.work_id, target.video_part_id, transcript_id)
                    for target, transcript_id in selected]

    def _request_publication(self, work_id: str, part_id: int, transcript_id: int) -> dict[str, Any]:
        job_id, created = self.repository.enqueue_publication(
            video_part_id=part_id, transcript_id=transcript_id, force=True)
        return {"work_id": work_id, "transcript_id": transcript_id, "job_id": job_id,
                "status": self.repository.explain_job(job_id)["status"], "created": int(created)}

    def proofread(self, *, part_id: int | None, base_transcript_id: int | None,
                  reference_transcript_id: int | None, no_reference: bool,
                  config: EditorialConfig, refresh_input: bool = False) -> dict[str, Any]:
        editorial = EditorialRepository(self.session.connection, commit_guard=self.repository.commit_guard)
        if base_transcript_id is not None:
            base = editorial.read_source(base_transcript_id)
            part_id = base.video_part_id
            default_reference = editorial.latest_reference(part_id, base.language) if base.source_kind == "asr-local" else None
        else:
            if part_id is None:
                raise ValueError("proofreading requires a video part or base transcript")
            base_transcript_id, default_reference = editorial.latest_sources(part_id)
        reference_id = None if no_reference else (
            reference_transcript_id if reference_transcript_id is not None else default_reference)
        prepared = editorial.build_input(base_transcript_id, reference_id, config, reuse_existing=not refresh_input)
        with self.repository.commit_guard.transaction():
            editorial.store_input(prepared)
            proof_id, render_id, _, _ = self.repository.enqueue_editorial(
                video_part_id=part_id, input_id=prepared["input_id"])
        return {"input_id": prepared["input_id"], "chunks": len(prepared["chunks"]),
                "job_id": proof_id, "render_job_id": render_id}

    def render(self, revision_id: str, template_version: str) -> str:
        prepared, _ = EditorialRepository(self.session.connection).revision(revision_id)
        job_id, _ = self.repository.request_document(
            video_part_id=prepared["snapshot"]["video_part_id"], revision_id=revision_id,
            template_version=template_version)
        return job_id

    def run(self, *, worker_id: str, sessdata: str | None,
            only_editorial: bool = False, limit: int | None = None,
            kinds: tuple[JobKind, ...] | None = None, role: str | None = None,
            drain_file: str | None = None, drain_timeout_seconds: float | None = None,
            gpu_session: str = "persistent", config_resolver=None,
            asr_prefetch: bool = False, asr_prefetch_bytes: int = 64 * 1024 * 1024,
            poll_interval_seconds: float = 0, shutdown_event: threading.Event | None = None,
            source_registry=None, warmup_audio: str | None = None,
            warmup_timeout_seconds: float = 300, cache_root: str | None = None,
            cache_max_bytes: int = 10 * 1024**3) -> ExecutionSummary:
        from contextlib import ExitStack

        from bili_asr.editorial_runtime import EditorialWorkflowHandlers
        from bili_asr.workflow_runtime import ArchiveWorkflowHandlers

        if role is not None and role not in WORKER_ROLES:
            raise ValueError("unknown worker role")
        if sum((bool(only_editorial), kinds is not None, role is not None)) > 1:
            raise ValueError("choose only one of only-editorial, role or kind")
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be finite and nonnegative")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("limit must be positive")
        if gpu_session == "legacy" and (warmup_audio is not None or cache_root is not None):
            raise ValueError("explicit warmup/cache options require a supervised inference session")
        if not math.isfinite(warmup_timeout_seconds) or warmup_timeout_seconds <= 0:
            raise ValueError("warmup timeout must be finite and positive")
        if warmup_audio is not None:
            sentinel = Path(warmup_audio)
            if not sentinel.is_absolute() or not sentinel.is_file():
                raise ValueError("warmup audio must be an existing absolute file")
        selected = WORKER_ROLES[role] if role is not None else (
            WORKER_ROLES["editorial"] if only_editorial else kinds)
        registered = {}
        with ExitStack() as resources:
            if self.repository.has_manuscript_contract() or only_editorial:
                editorial = EditorialWorkflowHandlers(
                    EditorialRepository(self.session.connection, commit_guard=self.repository.commit_guard),
                    self.repository, archive_root=Path(self.session.archive_root),
                    artifact_roots=self.session.artifact_roots)
                resources.callback(editorial.close)
                registered.update(editorial.handlers())
            if not only_editorial:
                archive = ArchiveWorkflowHandlers(
                    self.session.connection, self.repository, archive_root=self.session.archive_root,
                    sessdata=sessdata, artifact_roots=self.session.artifact_roots,
                    gpu_session=gpu_session, config_resolver=config_resolver,
                    cache_root=cache_root, cache_max_bytes=cache_max_bytes,
                    asr_prefetch=asr_prefetch, asr_prefetch_bytes=asr_prefetch_bytes)
                resources.callback(archive.close)
                registered.update(archive.handlers())
                from bili_asr.services.source_workflow import compose_source_handlers
                registered.update(compose_source_handlers(archive, source_registry))
            stop = shutdown_event or threading.Event()
            if threading.current_thread() is threading.main_thread():
                def request_drain(_signum, _frame):
                    stop.set()
                for signum in (signal.SIGINT, signal.SIGTERM):
                    previous = signal.signal(signum, request_drain)
                    resources.callback(signal.signal, signum, previous)
            def prepare(candidate, checkpoint):
                if not only_editorial:
                    archive.prepare_candidate(candidate, checkpoint, timeout_seconds=warmup_timeout_seconds,
                                              audio_path=warmup_audio)
            executor = WorkflowExecutor(
                self.repository, worker_id=worker_id, handlers=registered,
                kinds=tuple(registered) if selected is None else tuple(dict.fromkeys(selected)),
                drain_requested=lambda: stop.is_set() or (drain_file is not None and Path(drain_file).exists()),
                drain_timeout_seconds=drain_timeout_seconds,
                prepare_candidate=prepare if not only_editorial and gpu_session != "legacy" else None)
            succeeded = failed = cancelled = 0
            while True:
                remaining = None if limit is None else limit - succeeded - failed - cancelled
                summary = executor.run(limit=remaining)
                succeeded += summary.succeeded
                failed += summary.failed
                cancelled += summary.cancelled
                if (not poll_interval_seconds or executor.drain_requested()
                        or (limit is not None and succeeded + failed + cancelled >= limit)):
                    return ExecutionSummary(succeeded, failed, succeeded + failed + cancelled == 0, cancelled)
                stop.wait(poll_interval_seconds)
