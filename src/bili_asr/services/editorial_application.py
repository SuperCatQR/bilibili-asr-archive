"""Freeze editorial inputs and bind scheduling facts in one owned transaction."""
from __future__ import annotations
import json
from typing import Any
from bili_asr.editorial import EditorialConfig
from bili_asr.storage.editorial_facts import template_for_input
from bili_asr.workflow_models import WorkflowJob

def freeze_job_input(repository, workflow, job: WorkflowJob) -> dict[str, Any]:
    source_selection = None
    row = repository.connection.execute("SELECT input_id FROM editorial_job_inputs WHERE job_id = ?", (job.job_id,)).fetchone()
    if row:
        prepared = repository.load_input(row["input_id"])
        with repository.owned_transaction(job):
            workflow.bind_editorial_render(job.job_id, template_for_input(repository.connection, prepared["input_id"]))
        return prepared
    if "input_id" in job.payload:
        prepared = repository.load_input(str(job.payload["input_id"]))
    else:
        # Automatic acquisition chain fixes the exact ASR prerequisite result,
        # rather than selecting whichever ASR happens to be newest on retry.
        prerequisite = repository.connection.execute(
            "SELECT attempt_id,result_json FROM workflow_attempts WHERE job_id = ? AND outcome = 'succeeded' "
            "ORDER BY finished_at DESC, rowid DESC LIMIT 1", (job.payload["asr_job_id"],)).fetchone()
        if prerequisite is None:
            raise ValueError("ASR prerequisite result is missing")
        result = json.loads(prerequisite["result_json"])
        base_id = int(result["transcript_id"])
        if result.get("run_id") is not None:
            source_selection = {"format": "editorial-source-selection/v1", "asr_job_id": job.payload["asr_job_id"],
                                "attempt_id": prerequisite["attempt_id"], "run_id": result["run_id"], "transcript_id": base_id}
        base = repository.read_source(base_id)
        reference_id = repository.latest_reference(base.video_part_id, base.language)
        prepared = repository.build_input(base_id, reference_id, EditorialConfig.from_snapshot(job.payload["editorial_config"]),
                                    reuse_existing=True)
    if prepared["snapshot"]["video_part_id"] != job.video_part_id:
        raise ValueError("editorial input belongs to another video part")
    with repository.owned_transaction(job):
        repository.store_input(prepared)
        repository.bind_job_input(job.job_id, prepared["input_id"])
        workflow.bind_editorial_render(job.job_id, template_for_input(repository.connection, prepared["input_id"]))
    # Execution evidence stays outside the immutable input identity. The successful
    # attempt records what this invocation actually selected; old/resumed inputs
    # cannot acquire a retrospective selection from the newest prerequisite.
    if source_selection is not None:
        prepared = dict(prepared, source_selection=source_selection)
    return prepared
