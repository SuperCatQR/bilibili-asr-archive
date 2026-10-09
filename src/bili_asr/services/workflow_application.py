"""Workflow use cases and per-invocation adapter composition."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bili_asr.archive_session import ArchiveSession
from bili_asr.editorial import EditorialConfig
from bili_asr.storage.editorial import EditorialRepository
from bili_asr.storage.transcripts import TranscriptRepository
from bili_asr.storage.workflow import WorkflowRepository
from bili_asr.storage.workflow_selection import WorkflowSelection, resolve_workflow_selection
from bili_asr.transcript_selection import choose_transcript
from bili_asr.workflow import ExecutionSummary, WorkflowExecutor
from bili_asr.workflow_models import AsrPolicy, AsrProfile, JobKind, WorkflowPlan


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
        transcripts = TranscriptRepository(self.session.connection)
        selected = []
        for target in selection.targets:
            candidate = choose_transcript(transcripts.list_stored_transcripts(
                bvid=target.bvid, page_index=target.page_index))
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
                  config: EditorialConfig) -> dict[str, Any]:
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
        prepared = editorial.build_input(base_transcript_id, reference_id, config)
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
            only_editorial: bool, limit: int | None) -> ExecutionSummary:
        from contextlib import ExitStack
        from bili_asr.editorial_runtime import EditorialWorkflowHandlers
        from bili_asr.workflow_runtime import ArchiveWorkflowHandlers

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
                    sessdata=sessdata, artifact_roots=self.session.artifact_roots)
                resources.callback(archive.close)
                registered.update(archive.handlers())
            return WorkflowExecutor(
                self.repository, worker_id=worker_id, handlers=registered,
                kinds=(JobKind.PROOFREAD, JobKind.RENDER_DOCUMENT) if only_editorial else None).run(limit=limit)
