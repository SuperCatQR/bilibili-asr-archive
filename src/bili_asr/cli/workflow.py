"""CLI for the database-backed, independent-producer workflow."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from uuid import uuid4

from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.artifact_root import roots_for
from bili_asr.asr import default_config
from bili_asr.config import SESSDATA_ENV_VAR, resolve_sessdata
from bili_asr.diagnostics import write_stderr
from bili_asr.editorial import TEMPLATE_VERSION, EditorialConfig
from bili_asr.services.workflow_application import WORKER_ROLES, WorkflowApplication
from bili_asr.storage.database import SchemaContractError
from bili_asr.workflow_models import AsrPolicy, AsrProfile, JobKind


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
    render.add_argument("--template-version", choices=[TEMPLATE_VERSION, "ai-draft-v2"], default=TEMPLATE_VERSION)
    render.add_argument("--artifact-root", default=None, help="Product root used by subsequent workflow run invocations")

    run = actions.add_parser("run", help="Claim and execute ready SQLite jobs")
    run.add_argument("--archive-root", default=archive_root)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--worker-id", default=f"cli-{os.getpid()}-{uuid4().hex[:8]}")
    run.add_argument("--sessdata", default=None)
    run.add_argument("--only-editorial", action="store_true", help="Execute only proofreading/rendering jobs")
    worker_selection = run.add_mutually_exclusive_group()
    worker_selection.add_argument("--kind", choices=[kind.value for kind in JobKind], action="append",
                                  help="Claim only this job kind; repeat to select more")
    worker_selection.add_argument("--role", choices=tuple(WORKER_ROLES),
                                  help="Select the fixed ASR/acquisition/editorial/CPU handler set")
    run.add_argument("--drain-file", default=None, help="Stop claiming when this file exists")
    run.add_argument("--drain-timeout", type=float, default=None,
                     help="Grace period after drain; GPU inference is terminated on expiry")
    run.add_argument("--gpu-session", choices=("persistent", "oneshot"), default="persistent",
                     help="Reuse one killable model session or restart for each GPU task")
    run.add_argument("--asr-prefetch", action="store_true",
                     help="Experimental depth-one CPU preparation using a separate processor")
    run.add_argument("--asr-prefetch-bytes", type=int, default=64 * 1024 * 1024,
                     help="Conservative reservation budget for the prepared next chunk")
    run.add_argument("--runtime-bindings", default=None,
                     help="Verified checkpoint relocation file; frozen profiles remain unchanged")
    run.add_argument("--poll-interval", type=float, default=0,
                     help="Keep this worker alive and poll idle queues; zero runs until idle once")

    supervise = actions.add_parser("supervise", help="Own fixed worker slots, restart with backoff and drain on exit")
    supervise.set_defaults(database_policy=None)
    supervise.add_argument("--archive-root", default=archive_root)
    supervise.add_argument("--artifact-root", default=None)
    supervise.add_argument("--asr-slots", type=int, default=1)
    supervise.add_argument("--cpu-slots", type=int, default=1)
    supervise.add_argument("--editorial-slots", type=int, default=1)
    supervise.add_argument("--poll-interval", type=float, default=5)
    supervise.add_argument("--drain-file", default=None)
    supervise.add_argument("--drain-timeout", type=float, default=60)
    supervise.add_argument("--max-restarts", type=int, default=8)
    supervise.add_argument("--gpu-session", choices=("persistent", "oneshot"), default="persistent")
    supervise.add_argument("--asr-prefetch", action="store_true")
    supervise.add_argument("--asr-prefetch-bytes", type=int, default=64 * 1024 * 1024)
    supervise.add_argument("--runtime-bindings", default=None)
    run.add_argument("--artifact-root", default=None, help="Write products here; falls back to BILI_ARTIFACT_ROOT")

    status = actions.add_parser("status", help="Print workflow job counts from SQLite")
    status.set_defaults(database_policy=ArchiveAccessMode.READ)
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
    explain.set_defaults(database_policy=ArchiveAccessMode.READ)
    explain.add_argument("--archive-root", default=archive_root)
    explain.add_argument("--job-id", required=True)

    evidence = actions.add_parser("asr-evidence", help="Print persisted ASR diagnostics for one acquisition run")
    evidence.set_defaults(database_policy=ArchiveAccessMode.READ)
    evidence.add_argument("--archive-root", default=archive_root)
    evidence.add_argument("--run-id", required=True)
    evidence.add_argument("--part-id", type=int, required=True)

    retry = actions.add_parser("retry", help="Requeue failed jobs while keeping attempt evidence")
    retry.add_argument("--archive-root", default=archive_root)
    retry.add_argument("--part-id", type=int, action="append", default=None)
    retry.add_argument("--job-id", action="append", default=None)
    retry.add_argument("--kind", choices=[kind.value for kind in JobKind], action="append", default=None)

    repair = actions.add_parser("repair-dependencies", help="Plan or apply a fenced repair of legacy producer edges")
    repair.set_defaults(database_policy=ArchiveAccessMode.READ)
    repair.add_argument("--archive-root", default=archive_root)
    repair.add_argument("--part-id", type=int, action="append", required=True)
    repair.add_argument("--apply", action="store_true", help="Apply the exact inspected plan")
    repair.add_argument("--expected-plan-id", default=None, help="Required inspected plan identity for --apply")
    repair.add_argument("--retry-failed", action="store_true", help="Requeue failed audio and ASR producers, preserving attempts")


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
    except (SchemaContractError, ValueError, OSError) as exc:
        write_stderr(f"workflow {args.workflow_action}: {exc}")
        return 1


def _execute_workflow(args: argparse.Namespace) -> int:
    if args.workflow_action == "supervise":
        from bili_asr.workflow_supervisor import WorkerSupervisor
        supervisor = WorkerSupervisor(archive_root=args.archive_root, artifact_root=args.artifact_root,
            slots={"asr": args.asr_slots, "cpu": args.cpu_slots, "editorial": args.editorial_slots},
            poll_interval=args.poll_interval, drain_file=args.drain_file, drain_timeout=args.drain_timeout,
            max_restarts=args.max_restarts, gpu_session=args.gpu_session,
            asr_prefetch=args.asr_prefetch, asr_prefetch_bytes=args.asr_prefetch_bytes,
            runtime_bindings=args.runtime_bindings)
        supervisor.run()
        return 0
    artifact_roots = None
    if args.workflow_action in {"run", "render"}:
        artifact_roots = roots_for(args.archive_root, flag_value=args.artifact_root,
                                   require_writable=args.workflow_action == "run")
    readonly = args.workflow_action in {"status", "explain", "asr-evidence"} or (
        args.workflow_action == "repair-dependencies" and not args.apply)
    mode = ArchiveAccessMode.READ if readonly else ArchiveAccessMode.WRITE
    session = ArchiveSession(args.archive_root, mode=mode, artifact_roots=artifact_roots).open()
    connection = session.connection
    try:
        application = WorkflowApplication(session)
        repository = application.repository
        if args.workflow_action != "status":
            repository.require_cancellation_contract()
        if args.workflow_action == "repair-dependencies":
            if args.apply and args.expected_plan_id is None:
                raise ValueError("--apply requires --expected-plan-id from the inspected plan")
            from bili_asr.storage.workflow_dependency_repair import repair_producer_dependencies
            report = repair_producer_dependencies(connection, args.part_id, apply=args.apply,
                expected_plan_id=args.expected_plan_id, retry_failed=args.retry_failed)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
            return 0
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
            for item in application.publish(args.part_id):
                print("workflow publish: " + " ".join(f"{name}={value}" for name, value in item.items()))
            return 0
        if args.workflow_action == "explain":
            try:
                print(json.dumps(repository.explain_job(args.job_id), ensure_ascii=False, sort_keys=True))
            except ValueError as exc:
                write_stderr(f"workflow explain: {exc}")
                return 1
            return 0
        if args.workflow_action == "proofread":
            item = application.proofread(part_id=args.part_id, base_transcript_id=args.base_transcript_id,
                reference_transcript_id=args.reference_transcript_id, no_reference=args.no_reference,
                config=_editorial_config(args))
            print("workflow proofread: " + " ".join(f"{name}={value}" for name, value in item.items()))
            return 0
        if args.workflow_action == "render":
            job_id = application.render(args.revision_id, args.template_version)
            print(f"workflow render: job_id={job_id}")
            return 0
        if args.workflow_action == "status":
            counts = repository.count_by_status()
            for status in ("queued", "running", "succeeded", "failed", "cancelled"):
                print(f"{status}: {counts.get(status, 0)}")
            blocked = repository.blocked_by_cancelled()
            print(f"blocked_by_cancelled: {len(blocked)}")
            if args.jobs:
                rows = repository.list_job_identities()
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
            count = repository.requeue_failed(part_ids=args.part_id, job_ids=args.job_id,
                                             kinds=None if args.kind is None else [JobKind(k) for k in args.kind])
            print(f"workflow retry: requeued={count}")
            return 0
        if args.workflow_action == "plan":
            try:
                policy = AsrPolicy(args.asr_policy)
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
                planned = application.plan(part_ids=args.part_id, bvids=args.bvid, page_index=args.page_index,
                    policy=policy, profile=profile, quality_threshold=args.quality_threshold,
                    editorial_config=editorial_config)
                profile_id, plan, selection = planned.profile_id, planned.jobs, planned.selection
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
        config_resolver = None
        if args.runtime_bindings is not None:
            from bili_asr.runtime_bindings import load_runtime_bindings
            config_resolver = load_runtime_bindings(args.runtime_bindings).resolve
        summary = application.run(worker_id=args.worker_id, sessdata=sessdata,
            only_editorial=args.only_editorial, limit=args.limit,
            kinds=None if args.kind is None else tuple(JobKind(kind) for kind in args.kind), role=args.role,
            drain_file=args.drain_file, drain_timeout_seconds=args.drain_timeout,
            gpu_session=args.gpu_session, config_resolver=config_resolver,
            asr_prefetch=args.asr_prefetch, asr_prefetch_bytes=args.asr_prefetch_bytes,
            poll_interval_seconds=args.poll_interval)
        print(f"workflow run: succeeded={summary.succeeded} failed={summary.failed} "
              f"cancelled={summary.cancelled} idle={int(summary.idle)}")
        return 1 if summary.failed else 0
    except ValueError as exc:
        write_stderr(f"workflow {args.workflow_action}: {exc}")
        return 1
    finally:
        session.close()
