"""Opt-in failed-job retry maintenance command."""

import argparse
import json
from pathlib import Path

from bili_asr.diagnostics import write_stderr


def add_maintenance_parser(subparsers: argparse._SubParsersAction, *, archive_root: str) -> None:
    parser = subparsers.add_parser("retry-maintenance", help="Run scoped bounded retry maintenance or inspect its health")
    actions = parser.add_subparsers(dest="maintenance_action", required=True)
    run = actions.add_parser("tick", help="One explicit maintenance pass; never advances scope")
    run.add_argument("--archive-root", default=archive_root)
    for flag in ("policy", "state", "lock", "health"):
        run.add_argument("--" + flag, required=True, type=Path)
    # Service acquires archive write access after health start has been recorded.
    run.set_defaults(database_policy=None)
    report = actions.add_parser("health", help="Read independent maintenance and optional worker health")
    report.add_argument("--health", required=True, type=Path)
    report.add_argument("--worker-health", default=None, type=Path)
    report.add_argument("--stale-after-seconds", type=int, default=180)
    report.set_defaults(database_policy=None)


def _cmd_retry_maintenance(args) -> int:
    from bili_asr.services.retry_maintenance import health, tick

    try:
        if args.maintenance_action == "tick":
            result = tick(archive_root=args.archive_root, policy_path=args.policy,
                          state_path=args.state, lock_path=args.lock, health_path=args.health)
            code = 0  # A lock skip is observed, not reported as successful maintenance.
        else:
            result = health(health_path=args.health, stale_after_seconds=args.stale_after_seconds,
                            worker_health_path=args.worker_health)
            code = 0 if result["maintenance"]["health_status"] in {"healthy", "running"} else 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return code
    except (OSError, ValueError, RuntimeError) as exc:
        write_stderr("retry-maintenance: " + type(exc).__name__)
        return 1
