"""Offline maintenance package CLI; services own every access boundary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import zipfile


def add_maintenance_package_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("maintenance", help="Offline private-history packages; new-target imports only")
    actions = parser.add_subparsers(dest="maintenance_action", required=True)
    export = actions.add_parser("export", help="Export all history or native video/part dependency closure")
    export.add_argument("--source-root", type=Path, required=True)
    export.add_argument("--artifact-root", type=Path)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--part-id", type=int, action="append")
    export.add_argument("--bvid", action="append")
    export.add_argument("--profile", choices=("private-history",), default="private-history")
    for action in ("inspect", "verify"):
        child = actions.add_parser(action)
        child.add_argument("--package", type=Path, required=True)
    plan = actions.add_parser("import-plan", help="Verify and preflight without creating a target")
    plan.add_argument("--package", type=Path, required=True)
    plan.add_argument("--target-root", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    apply = actions.add_parser("import-apply", help="Revalidate a saved plan and atomically install a staged target")
    apply.add_argument("--plan", type=Path, required=True)
    check = actions.add_parser("import-check", help="Verify the immutable installation baseline")
    check.add_argument("--target-root", type=Path, required=True)
    check.add_argument("--plan-id", required=True)


def _cmd_maintenance_package(args: argparse.Namespace) -> int:
    from bili_asr.services.maintenance_package import (
        apply_import, check_import, export_package, inspect_package, plan_import, verify_package, write_plan,
    )
    action = args.maintenance_action
    try:
        if action == "export":
            report = export_package(args.source_root, args.output, part_ids=args.part_id,
                                    bvids=args.bvid, artifact_root=args.artifact_root)
        elif action == "inspect":
            report = inspect_package(args.package)
        elif action == "verify":
            report = verify_package(args.package)
        elif action == "import-plan":
            report = plan_import(args.package, args.target_root)
            write_plan(report, args.output)
        elif action == "import-apply":
            report = apply_import(args.plan)
        else:
            report = check_import(args.target_root, plan_id=args.plan_id)
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile, KeyError, TypeError, UnicodeError, RecursionError) as exc:
        print(json.dumps({"operation": "maintenance-" + action, "valid": False,
                          "error": {"code": "maintenance-validation-failed", "message": str(exc)}}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0
