"""CLI for the database-backed, independent-producer workflow."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import uuid4

from bili_asr.asr import DEFAULT_ALIGNER_MODEL, DEFAULT_MODEL
from bili_asr.config import SESSDATA_ENV_VAR, resolve_sessdata
from bili_asr.diagnostics import write_stderr
from bili_asr.storage import AsrPolicy, AsrProfile, WorkflowRepository, open_database
from bili_asr.workflow import WorkflowExecutor
from bili_asr.editorial import EditorialConfig, TEMPLATE_VERSION
from bili_asr.storage.editorial import EditorialRepository
from bili_asr.storage.database import SchemaContractError


def add_workflow_parser(subparsers: argparse._SubParsersAction, *, archive_root: str) -> None:
    parser = subparsers.add_parser(
        "workflow",
        help="Plan and run independent subtitle, audio, and ASR jobs from SQLite",
    )
    actions = parser.add_subparsers(dest="workflow_action", required=True)
    plan = actions.add_parser("plan", help="Create idempotent jobs for explicit video-part IDs")
    plan.add_argument("--archive-root", default=archive_root)
    plan.add_argument("--part-id", type=int, action="append", required=True)
    plan.add_argument("--asr-policy", choices=[item.value for item in AsrPolicy], default="all")
    plan.add_argument("--quality-threshold", type=float, default=None)
    plan.add_argument("--profile-key", default="qwen3-default")
    plan.add_argument("--model", default=DEFAULT_MODEL)
    plan.add_argument("--model-revision", default="")
    plan.add_argument("--aligner", default=DEFAULT_ALIGNER_MODEL)
    plan.add_argument("--device", default=os.environ.get("BILI_ASR_DEVICE", "cuda"))
    plan.add_argument("--language", default=None)
    plan.add_argument("--proofread", action="store_true", help="Queue AI proofreading after ASR and then render Markdown")
    _add_editorial_arguments(plan)

    proofread = actions.add_parser("proofread", help="Freeze stored transcript versions and queue AI proofreading")
    proofread.add_argument("--archive-root", default=archive_root)
    selection = proofread.add_mutually_exclusive_group(required=True)
    selection.add_argument("--part-id", type=int, help="Use the newest stored ASR version at planning time")
    selection.add_argument("--base-transcript-id", type=int, help="Use this explicit base transcript version")
    reference = proofread.add_mutually_exclusive_group()
    reference.add_argument("--reference-transcript-id", type=int, default=None)
    reference.add_argument("--no-reference", action="store_true")
    _add_editorial_arguments(proofread)

    render = actions.add_parser("render", help="Queue deterministic Markdown rendering without calling AI")
    render.add_argument("--archive-root", default=archive_root)
    render.add_argument("--revision-id", required=True)
    render.add_argument("--template-version", choices=[TEMPLATE_VERSION], default=TEMPLATE_VERSION)

    run = actions.add_parser("run", help="Claim and execute ready SQLite jobs")
    run.add_argument("--archive-root", default=archive_root)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--worker-id", default=f"cli-{os.getpid()}-{uuid4().hex[:8]}")
    run.add_argument("--sessdata", default=None)
    run.add_argument("--only-editorial", action="store_true", help="Execute only proofreading/rendering jobs")

    status = actions.add_parser("status", help="Print workflow job counts from SQLite")
    status.add_argument("--archive-root", default=archive_root)

    retry = actions.add_parser("retry", help="Requeue failed jobs while keeping attempt evidence")
    retry.add_argument("--archive-root", default=archive_root)
    retry.add_argument("--part-id", type=int, action="append", default=None)


def _add_editorial_arguments(parser: argparse.ArgumentParser) -> None:
    defaults = EditorialConfig()
    parser.add_argument("--editorial-model", default=defaults.model)
    parser.add_argument("--context-tokens", type=int, default=defaults.context_tokens)
    parser.add_argument("--max-input-tokens", type=int, default=defaults.max_input_tokens)
    parser.add_argument("--max-output-tokens", type=int, default=defaults.max_output_tokens)
    parser.add_argument("--context-segments", type=int, default=defaults.context_segments)
    parser.add_argument("--api-timeout", type=int, default=defaults.timeout_seconds)
    parser.add_argument("--reasoning-effort", choices=("low", "high", "max"), default=defaults.reasoning_effort)
    parser.add_argument("--top-p", type=float, default=defaults.top_p)


def _editorial_config(args: argparse.Namespace) -> EditorialConfig:
    return EditorialConfig(model=args.editorial_model, context_tokens=args.context_tokens,
                           max_input_tokens=args.max_input_tokens, max_output_tokens=args.max_output_tokens,
                           context_segments=args.context_segments, timeout_seconds=args.api_timeout,
                           reasoning_effort=args.reasoning_effort, top_p=args.top_p)


def _cmd_workflow(args: argparse.Namespace) -> int:
    try:
        return _execute_workflow(args)
    except SchemaContractError as exc:
        write_stderr(f"workflow {args.workflow_action}: {exc}")
        return 1


def _execute_workflow(args: argparse.Namespace) -> int:
    connection = open_database(args.archive_root)
    try:
        repository = WorkflowRepository(connection)
        if args.workflow_action == "proofread":
            editorial = EditorialRepository(connection)
            try:
                if args.base_transcript_id is not None:
                    base_id = args.base_transcript_id
                    base = editorial.read_source(base_id)
                    part_id = base.video_part_id
                    default_reference = editorial.latest_reference(part_id, base.language) if base.source_kind == "asr-local" else None
                else:
                    part_id = args.part_id
                    base_id, default_reference = editorial.latest_sources(part_id)
                reference_id = None if args.no_reference else (
                    args.reference_transcript_id if args.reference_transcript_id is not None else default_reference)
                prepared = editorial.prepare(base_id, reference_id, _editorial_config(args))
                proof_id, render_id, _, _ = repository.request_editorial(video_part_id=part_id, input_id=prepared["input_id"])
            except ValueError as exc:
                write_stderr(f"workflow proofread: {exc}")
                return 1
            print(f"workflow proofread: input_id={prepared['input_id']} chunks={len(prepared['chunks'])} "
                  f"job_id={proof_id} render_job_id={render_id}")
            return 0
        if args.workflow_action == "render":
            editorial = EditorialRepository(connection)
            try:
                prepared, _ = editorial.revision(args.revision_id)
                job_id, _ = repository.request_document(video_part_id=prepared["snapshot"]["video_part_id"],
                                                       revision_id=args.revision_id, template_version=args.template_version)
            except ValueError as exc:
                write_stderr(f"workflow render: {exc}")
                return 1
            print(f"workflow render: job_id={job_id}")
            return 0
        if args.workflow_action == "status":
            counts = repository.count_by_status()
            for status in ("queued", "running", "succeeded", "failed", "cancelled"):
                print(f"{status}: {counts.get(status, 0)}")
            return 0
        if args.workflow_action == "retry":
            count = repository.requeue_failed(part_ids=args.part_id)
            print(f"workflow retry: requeued={count}")
            return 0
        if args.workflow_action == "plan":
            profile = AsrProfile(
                profile_key=args.profile_key,
                model_name=args.model,
                model_revision=args.model_revision,
                aligner_name=args.aligner,
                device=args.device,
                language=args.language,
            )
            profile_id = repository.register_profile(profile)
            try:
                plan = repository.plan(
                    part_ids=args.part_id,
                    policy=AsrPolicy(args.asr_policy),
                    profile_id=profile_id,
                    quality_threshold=args.quality_threshold,
                    editorial_config=_editorial_config(args).to_dict() if args.proofread else None,
                )
            except ValueError as exc:
                write_stderr(f"workflow plan: {exc}")
                return 1
            print(
                f"workflow plan: subtitle={plan.subtitle_jobs} audio={plan.audio_jobs} "
                f"asr={plan.asr_jobs} profile_id={profile_id}"
                f" proofread={plan.proofread_jobs} documents={plan.document_jobs}"
            )
            return 0
        sessdata = resolve_sessdata(args.sessdata, os.environ.get(SESSDATA_ENV_VAR))
        # Planning and status are useful on a minimal SQLite installation.  The
        # concrete API/model adapter is needed only when a worker actually runs.
        from bili_asr.editorial_runtime import EditorialWorkflowHandlers
        from bili_asr.storage.workflow import JobKind

        editorial_handlers = None
        has_manuscript_contract = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'manuscript_contract'"
        ).fetchone() is not None
        registered = {}
        if has_manuscript_contract or args.only_editorial:
            editorial_handlers = EditorialWorkflowHandlers(EditorialRepository(connection), repository,
                                                           archive_root=Path(args.archive_root))
            registered.update(editorial_handlers.handlers())
        archive_handlers = None
        if not args.only_editorial:
            from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
            archive_handlers = ArchiveWorkflowHandlers(connection, repository, archive_root=args.archive_root, sessdata=sessdata)
            registered.update(archive_handlers.handlers())
        try:
            summary = WorkflowExecutor(
                repository, worker_id=args.worker_id, handlers=registered,
                kinds=(JobKind.PROOFREAD, JobKind.RENDER_DOCUMENT) if args.only_editorial else None,
            ).run(limit=args.limit)
        finally:
            if editorial_handlers is not None:
                editorial_handlers.close()
            if archive_handlers is not None:
                archive_handlers.close()
        print(f"workflow run: succeeded={summary.succeeded} failed={summary.failed} idle={int(summary.idle)}")
        return 1 if summary.failed else 0
    finally:
        connection.close()
