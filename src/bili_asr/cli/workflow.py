"""CLI for the database-backed, independent-producer workflow."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from bili_asr.asr import default_config
from bili_asr.config import SESSDATA_ENV_VAR, resolve_sessdata
from bili_asr.diagnostics import write_stderr
from bili_asr.editorial import TEMPLATE_VERSION, EditorialConfig
from bili_asr.artifact_root import roots_for, ArtifactRootError
from bili_asr.storage import AsrPolicy, AsrProfile, WorkflowRepository, open_database
from bili_asr.storage.editorial import EditorialRepository
from bili_asr.storage.database import SchemaContractError
from bili_asr.workflow import WorkflowExecutor
from bili_asr.storage.workflow_selection import resolve_workflow_selection


def add_workflow_parser(subparsers: argparse._SubParsersAction, *, archive_root: str) -> None:
    parser = subparsers.add_parser(
        "workflow",
        help="Plan and run independent subtitle, audio, and ASR jobs from SQLite",
    )
    actions = parser.add_subparsers(dest="workflow_action", required=True)
    plan = actions.add_parser("plan", help="Create idempotent jobs for stored BVIDs or explicit video-part IDs")
    plan.add_argument("--archive-root", default=archive_root)
    selection = plan.add_mutually_exclusive_group(required=True)
    selection.add_argument("--part-id", type=int, action="append", help="Exact stored video_part_id; repeat to select more")
    selection.add_argument("--bvid", action="append", help="Stored BVID; repeat to select more videos")
    plan.add_argument("--page-index", type=_nonnegative_page_index, default=None,
                      help="Stored zero-based index (0 is P1), applied to each --bvid")
    plan.add_argument("--asr-policy", choices=[item.value for item in AsrPolicy], default="all")
    plan.add_argument("--quality-threshold", type=float, default=None)
    plan.add_argument("--profile-key", default="qwen3-default")
    plan.add_argument("--model", default=None)
    plan.add_argument("--model-revision", default=None)
    plan.add_argument("--aligner", default=None)
    plan.add_argument("--aligner-revision", default=None)
    plan.add_argument("--device", default=None)
    plan.add_argument("--language", default=None)
    plan.add_argument("--chunk-seconds", type=float, default=None)
    plan.add_argument("--inference-timeout", type=float, default=None)
    plan.add_argument("--hotword", action="append", default=None)
    plan.add_argument("--model-id", default=None)
    plan.add_argument("--offline", action=argparse.BooleanOptionalAction, default=None)
    plan.add_argument("--tokens-per-second", type=float, default=None)
    plan.add_argument("--min-new-tokens", type=int, default=None)
    plan.add_argument("--second-pass-cache", action=argparse.BooleanOptionalAction, default=None)
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
    render.add_argument("--artifact-root", default=None, help="Product root used by subsequent workflow run invocations")

    run = actions.add_parser("run", help="Claim and execute ready SQLite jobs")
    run.add_argument("--archive-root", default=archive_root)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--worker-id", default=f"cli-{os.getpid()}-{uuid4().hex[:8]}")
    run.add_argument("--sessdata", default=None)
    run.add_argument("--only-editorial", action="store_true", help="Execute only proofreading/rendering jobs")
    run.add_argument("--artifact-root", default=None, help="Write products here; falls back to BILI_ARTIFACT_ROOT")

    status = actions.add_parser("status", help="Print workflow job counts from SQLite")
    status.add_argument("--archive-root", default=archive_root)
    status.add_argument("--jobs", action="store_true", help="List job IDs, stored part identity, and cancellation blockers")

    cancel = actions.add_parser("cancel", help="Cancel selected queued/running jobs at safe commit boundaries")
    cancel.add_argument("--archive-root", default=archive_root)
    cancel.add_argument("--job-id", action="append", required=True, help="Exact workflow job ID; repeat to select more")

    publish = actions.add_parser("publish", help="Rebuild archive bundles from the preferred stored transcript")
    publish.add_argument("--archive-root", default=archive_root)
    publish.add_argument("--part-id", type=int, action="append", required=True)
    status.add_argument("--details", action="store_true", help="Explain each job and its unsatisfied dependencies")
    explain = actions.add_parser("explain", help="Inspect a job, its dependency blockers and latest attempt")
    explain.add_argument("--archive-root", default=archive_root)
    explain.add_argument("--job-id", required=True)

    evidence = actions.add_parser("asr-evidence", help="Print persisted ASR diagnostics for one acquisition run")
    evidence.add_argument("--archive-root", default=archive_root)
    evidence.add_argument("--run-id", required=True)
    evidence.add_argument("--part-id", type=int, required=True)

    retry = actions.add_parser("retry", help="Requeue failed jobs while keeping attempt evidence")
    retry.add_argument("--archive-root", default=archive_root)
    retry.add_argument("--part-id", type=int, action="append", default=None)
    retry.add_argument("--job-id", action="append", default=None)
    from bili_asr.storage.workflow import JobKind
    retry.add_argument("--kind", choices=[kind.value for kind in JobKind], action="append", default=None)


def _nonnegative_page_index(value: str) -> int:
    try:
        index = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("page index must be an integer") from exc
    if index < 0:
        raise argparse.ArgumentTypeError("page index must be non-negative (0 is P1)")
    return index


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
        artifact_roots = None
        if args.workflow_action in {"run", "render"}:
            try:
                artifact_roots = roots_for(args.archive_root, flag_value=args.artifact_root,
                                           require_writable=args.workflow_action == "run")
            except ArtifactRootError as exc:
                write_stderr(f"workflow {args.workflow_action}: {exc}")
                return 1
        repository = WorkflowRepository(connection)
        if args.workflow_action != "status":
            repository.require_cancellation_contract()
        if args.workflow_action == "asr-evidence":
            from bili_asr.storage import TranscriptRepository

            evidence = TranscriptRepository(connection).read_asr_evidence(args.run_id, args.part_id)
            if evidence is None:
                write_stderr("workflow asr-evidence: no evidence for this run and part")
                return 1
            print(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        if args.workflow_action == "cancel":
            results = repository.cancel(job_ids=args.job_id)
            print(f"workflow cancel: changed={sum(item.changed for item in results)} "
                  f"noop={sum(not item.changed for item in results)}")
            for item in results:
                print(f"  job_id={item.job_id} previous={item.previous_status} "
                      f"status={item.status} changed={int(item.changed)}")
            return 0
        if args.workflow_action == "publish":
            from bili_asr.services.transcript_projection import ordered_candidates
            from bili_asr.storage import TranscriptRepository

            selection = resolve_workflow_selection(connection, part_ids=args.part_id)
            transcripts = TranscriptRepository(connection)
            selected = []
            for target in selection.targets:
                candidates = ordered_candidates(transcripts.list_stored_transcripts(
                    bvid=target.bvid, page_index=target.page_index))
                if len(candidates) != 1:
                    raise ValueError(f"no stored transcript for {target.work_id}")
                selected.append((target, int(candidates[0].transcript["transcript_id"])))
            for target, transcript_id in selected:
                job_id, created = repository.request_publication(
                    video_part_id=target.video_part_id, transcript_id=transcript_id, force=True)
                status = connection.execute("SELECT status FROM workflow_jobs WHERE job_id = ?", (job_id,)).fetchone()[0]
                print(f"workflow publish: work_id={target.work_id} transcript_id={transcript_id} "
                      f"job_id={job_id} status={status} created={int(created)}")
            return 0
        if args.workflow_action == "explain":
            try:
                print(json.dumps(repository.explain_job(args.job_id), ensure_ascii=False, sort_keys=True))
            except ValueError as exc:
                write_stderr(f"workflow explain: {exc}")
                return 1
            return 0
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
            blocked = repository.blocked_by_cancelled()
            print(f"blocked_by_cancelled: {len(blocked)}")
            if args.jobs:
                rows = connection.execute(
                    "SELECT j.*, p.bvid, p.page_index FROM workflow_jobs AS j "
                    "LEFT JOIN video_parts AS p ON p.video_part_id = j.video_part_id "
                    "ORDER BY j.created_at, j.job_id")
                for row in rows:
                    print(f"  job_id={row['job_id']} kind={row['kind']} status={row['status']} "
                          f"bvid={row['bvid']} page_index={row['page_index']} "
                          f"video_part_id={row['video_part_id']} attempts={row['attempt_count']} "
                          f"blocked_by_cancelled={int(row['job_id'] in blocked)}")
            if args.details:
                for job in repository.list_jobs():
                    print(json.dumps(repository.explain_job(job.job_id), ensure_ascii=False, sort_keys=True))
            return 0
        if args.workflow_action == "retry":
            from bili_asr.storage.workflow import JobKind
            count = repository.requeue_failed(part_ids=args.part_id, job_ids=args.job_id,
                                             kinds=None if args.kind is None else [JobKind(k) for k in args.kind])
            print(f"workflow retry: requeued={count}")
            return 0
        if args.workflow_action == "plan":
            try:
                selection = resolve_workflow_selection(
                    connection, part_ids=args.part_id, bvids=args.bvid, page_index=args.page_index,
                )
                policy = AsrPolicy(args.asr_policy)
                if policy is AsrPolicy.BELOW_THRESHOLD and (
                    args.quality_threshold is None or not 0.0 <= args.quality_threshold <= 1.0
                ):
                    raise ValueError("quality_threshold must be between 0 and 1")
                editorial_config = _editorial_config(args).to_dict() if args.proofread else None
                names = {
                    "model": "model_name", "aligner": "aligner_name",
                    "inference_timeout": "inference_timeout_seconds",
                    "second_pass_cache": "second_pass_use_cache",
                    "hotword": "hotwords",
                }
                overrides = {}
                for name in ("model", "model_revision", "aligner", "aligner_revision",
                             "device", "language", "chunk_seconds", "inference_timeout",
                             "hotword", "offline", "model_id", "tokens_per_second",
                             "min_new_tokens", "second_pass_cache"):
                    value = getattr(args, name)
                    if value is not None:
                        overrides[names.get(name, name)] = tuple(value) if name == "hotword" else value
                values = asdict(default_config(**overrides))
                values.pop("local_source")
                values["model_revision"] = values["model_revision"] or ""
                profile = AsrProfile(profile_key=args.profile_key, **values)
                profile_id = repository.register_profile(profile)
                plan = repository.plan(
                    part_ids=selection.part_ids,
                    policy=policy,
                    profile_id=profile_id,
                    quality_threshold=args.quality_threshold,
                    editorial_config=editorial_config,
                )
            except ValueError as exc:
                write_stderr(f"workflow plan: {exc}")
                return 1
            print(
                f"workflow plan: subtitle={plan.subtitle_jobs} audio={plan.audio_jobs} "
                f"asr={plan.asr_jobs} profile_id={profile_id}"
                f" proofread={plan.proofread_jobs} documents={plan.document_jobs}"
            )
            for target in selection.targets:
                print(f"  target: bvid={target.bvid} page_index={target.page_index} "
                      f"video_part_id={target.video_part_id} work_id={target.work_id}")
            for target in selection.excluded_gone:
                print(f"  excluded gone: bvid={target.bvid} page_index={target.page_index} "
                      f"video_part_id={target.video_part_id} work_id={target.work_id}")
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
                                                           archive_root=Path(args.archive_root), artifact_roots=artifact_roots)
            registered.update(editorial_handlers.handlers())
        archive_handlers = None
        if not args.only_editorial:
            from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
            archive_handlers = ArchiveWorkflowHandlers(connection, repository, archive_root=args.archive_root,
                                                       sessdata=sessdata, artifact_roots=artifact_roots)
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
        print(f"workflow run: succeeded={summary.succeeded} failed={summary.failed} "
              f"cancelled={summary.cancelled} idle={int(summary.idle)}")
        return 1 if summary.failed else 0
    except ValueError as exc:
        write_stderr(f"workflow {args.workflow_action}: {exc}")
        return 1
    finally:
        connection.close()
