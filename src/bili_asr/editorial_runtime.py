"""Per-job editorial adapters: durable checkpoints around pure processing."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from bili_asr.artifact_root import ArtifactRoots

from bili_asr.deepseek import DeepSeekClient, parse_response, request_body
from bili_asr.editorial import EditorialConfig, TEMPLATE_VERSION, render_documents, validate_revision
from bili_asr.manuscript_files import stage_artifact
from bili_asr.storage.editorial import EditorialRepository
from bili_asr.storage.workflow import JobKind, WorkflowJob, WorkflowRepository
from bili_asr.workflow_payloads import decode_job_payload


class EditorialWorkflowHandlers:
    def __init__(self, repository: EditorialRepository, workflow: WorkflowRepository, *, archive_root: Path,
                 client: DeepSeekClient | None = None, artifact_roots: ArtifactRoots | None = None):
        self.repository, self.workflow = repository, workflow
        self.repository.commit_guard = workflow.commit_guard
        self.artifact_roots = artifact_roots or ArtifactRoots.of(archive_root)
        self.archive_root = self.artifact_roots.archive_root
        self.client = client or DeepSeekClient()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def handlers(self):
        return {JobKind.PROOFREAD: self.proofread, JobKind.RENDER_DOCUMENT: self.render}

    def proofread(self, job: WorkflowJob) -> dict[str, Any]:
        decode_job_payload(job)
        self.workflow.assert_lease(job)
        prepared = self.repository.freeze_job_input(job)
        config = EditorialConfig(**prepared["snapshot"]["config"])
        for chunk in prepared["chunks"]:
            self.workflow.assert_lease(job)
            if self.repository.chunk_result(prepared["input_id"], chunk["chunk_id"]) is not None:
                continue
            self.workflow.renew_lease(job, lease_seconds=config.timeout_seconds + 300)
            request = request_body(chunk, config, system_prompt=prepared["snapshot"]["system_prompt"])
            call_id = self.repository.begin_call(job, prepared["input_id"], chunk["chunk_id"], request)
            envelope = None
            try:
                envelope = self.client.complete(request, config)
                # Persist the actual envelope (including usage/model identifiers)
                # before accepting content or raising a validation error.
                self.repository.finish_call(call_id, envelope)
                self.workflow.assert_lease(job)
                blocks = validate_revision(chunk, parse_response(envelope))
                self.repository.save_chunk(job, prepared["input_id"], chunk["chunk_id"], call_id, blocks)
            except Exception as exc:
                self.repository.finish_call(call_id, envelope, type(exc).__name__[:64])
                raise
        revision_id = self.repository.commit_revision(job, prepared)
        return {"input_id": prepared["input_id"], "revision_id": revision_id, "chunks": len(prepared["chunks"])}

    def render(self, job: WorkflowJob) -> dict[str, Any]:
        decode_job_payload(job)
        self.workflow.assert_lease(job)
        template = job.payload["template_version"]
        if template != TEMPLATE_VERSION:
            raise ValueError("unsupported document template version")
        revision_id = str(job.payload["revision_id"]) if "revision_id" in job.payload else self.repository.revision_for_job(
            str(job.payload["proofread_job_id"]))
        prepared, blocks = self.repository.revision(revision_id)
        part_id = prepared["snapshot"]["video_part_id"]
        if part_id != job.video_part_id:
            raise ValueError("revision belongs to a different part")
        metadata = prepared["snapshot"]["metadata"]
        documents = render_documents(metadata, prepared, blocks, revision_id)
        relative = Path("documents") / f"part-{part_id}" / revision_id / TEMPLATE_VERSION
        write_root = self.artifact_roots.write_base
        artifacts = {
            name: ((relative / name).as_posix(), hashlib.sha256(content.encode("utf-8")).hexdigest())
            for name, content in documents.items()
        }
        # Validate both artifact identities and existing registrations before
        # replacing either file.  A conflict must never leave a half-updated pair.
        self.repository.preflight_artifacts(revision_id, template, artifacts)
        with ExitStack() as staging:
            prepared_files = [staging.enter_context(stage_artifact(
                write_root, artifacts[name][0], content.encode("utf-8")))
                for name, content in documents.items()]
            with self.repository.owned_transaction(job):
                # SQLite cannot roll back files. These immutable paths safely
                # survive as unregistered artifacts if the database commit fails;
                # retry verifies their bytes before registering the complete pair.
                for artifact in prepared_files:
                    artifact.install()
                self.repository.record_artifacts(revision_id, template, artifacts)
        return {"revision_id": revision_id, "artifacts": {name: path for name, (path, _) in artifacts.items()}}
