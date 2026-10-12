"""Per-job editorial adapters: durable checkpoints around pure processing."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.editorial_quality import check_source_quality
from bili_asr.workflow_errors import JobExecutionError

from bili_asr.deepseek import DeepSeekClient, DeepSeekError, parse_response, request_body
from bili_asr.editorial import EditorialConfig, local_revision, validate_revision
from bili_asr.editorial_recovery import diagnostic_for_error, recovery_request
from bili_asr.manuscript_files import stage_artifact
from bili_asr.storage.editorial import EditorialRepository, template_for_input
from bili_asr.storage.workflow import JobKind, WorkflowJob, WorkflowRepository
from bili_asr.workflow_payloads import decode_job_payload
from bili_asr.workflow import attempt_checkpoint
from bili_asr.manuscript_templates import AI_RENDERERS, renderer_for


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
        check_source_quality(prepared)
        config = EditorialConfig.from_snapshot(prepared["snapshot"]["config"])
        for chunk in prepared["chunks"]:
            attempt_checkpoint(job)
            self.workflow.assert_lease(job)
            if self.repository.chunk_result(prepared["input_id"], chunk["chunk_id"]) is not None:
                continue
            self._proofread_chunk(job, prepared, chunk, config)
        revision_id = self.repository.commit_revision(job, prepared)
        return {"input_id": prepared["input_id"], "revision_id": revision_id, "chunks": len(prepared["chunks"])}

    def _proofread_chunk(self, job, prepared, chunk, config):
        input_id, chunk_id = prepared["input_id"], chunk["chunk_id"]
        original = request_body(chunk, config, system_prompt=prepared["snapshot"]["system_prompt"])
        local_blocks = local_revision(chunk)
        if local_blocks is not None:
            call_id = self.repository.begin_call(job, input_id, chunk_id, original, invocation_kind="local_precheck")
            envelope = {"id": "local-precheck", "model": "local-precheck", "choices": [],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
            self.repository.finish_call(call_id, envelope)
            self.repository.save_chunk(job, input_id, chunk_id, call_id, local_blocks)
            return
        while True:
            attempt_checkpoint(job)
            self.workflow.assert_lease(job)
            self.workflow.renew_lease(job, lease_seconds=config.timeout_seconds + 300)
            calls = self.repository.physical_calls(input_id, chunk_id)
            bounded = config.request_policy == "deepseek-v2"
            request, recovery = recovery_request(original, calls[-1] if calls else None, config) if bounded else (original, None)
            fingerprint = self.repository.request_fingerprint(input_id, chunk_id, request)
            cached = self.repository.completed_call_record(fingerprint)
            # The owned transaction reserves a physical invocation before HTTP;
            # replay and local formatting rows never consume that budget.
            call_id = self.repository.begin_call(job, input_id, chunk_id, request,
                invocation_kind="response_replay" if cached else "provider", recovery=recovery,
                replay_of_call_id=None if cached is None else cached["call_id"])
            envelope = None
            try:
                attempt_checkpoint(job)
                self.workflow.assert_lease(job)
                envelope = cached["response"] if cached else self.client.complete(request, config)
                self.repository.finish_call(call_id, envelope)
                attempt_checkpoint(job)
                self.workflow.assert_lease(job)
                blocks = validate_revision(chunk, parse_response(envelope))
                self.repository.save_chunk(job, input_id, chunk_id, call_id, blocks)
                return
            except Exception as exc:
                diagnostic = diagnostic_for_error(exc)
                self.repository.finish_call(call_id, envelope, type(exc).__name__[:64], validation_diagnostic=diagnostic)
                if cached is not None and isinstance(exc, (ValueError, DeepSeekError)):
                    # A replayed response rejected by strict validation must not
                    # remain a reusable success, or restart repeats it forever.
                    self.repository.mark_validation_failure(cached["call_id"], type(exc).__name__[:64], diagnostic)
                if bounded and config.max_chunk_regenerations and diagnostic is not None:
                    continue
                if hasattr(exc, "safe_details"):
                    details = dict(exc.safe_details, call_id=call_id, chunk_id=chunk_id)
                    raise JobExecutionError(type(exc).__name__, details) from None
                raise

    def render(self, job: WorkflowJob) -> dict[str, Any]:
        decode_job_payload(job)
        self.workflow.assert_lease(job)
        template = job.payload["template_version"]
        revision_id = str(job.payload["revision_id"]) if "revision_id" in job.payload else self.repository.revision_for_job(
            str(job.payload["proofread_job_id"]))
        prepared, blocks = self.repository.revision(revision_id)
        expected_template = template_for_input(self.repository.connection, prepared["input_id"])
        if template != expected_template:
            raise ValueError("unsupported document template version for frozen input")
        part_id = prepared["snapshot"]["video_part_id"]
        if part_id != job.video_part_id:
            raise ValueError("revision belongs to a different part")
        metadata = prepared["snapshot"]["metadata"]
        documents = renderer_for(AI_RENDERERS, template)(metadata, prepared, blocks, revision_id)
        relative = Path("documents") / f"part-{part_id}" / revision_id / template
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
