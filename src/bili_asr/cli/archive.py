"""Explicit empty-target initialization and offline archive conversion."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from bili_asr.diagnostics import write_stderr


def add_archive_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("archive", help="Initialize, inspect or explicitly convert an archive")
    actions = parser.add_subparsers(dest="archive_action", required=True)
    preflight = actions.add_parser(
        "migration-preflight", help="Validate and inventory a stopped, checkpointed legacy archive",
    )
    preflight.add_argument("--source-root", required=True, help="Existing legacy archive directory")
    preflight.add_argument(
        "--source-artifact-root", help="Explicit source artifact root; does not use BILI_ARTIFACT_ROOT",
    )
    preflight.add_argument("--format", choices=("json", "text"), default="json")
    initialize = actions.add_parser("init", help="Explicitly initialize an empty universal-v2 archive")
    initialize.add_argument("--target-root", required=True)
    initialize.set_defaults(database_policy=None)
    convert = actions.add_parser("migrate", help="Copy and validate a stopped Bilibili archive into a separate empty universal target")
    source = convert.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-root")
    source.add_argument("--source-snapshot")
    convert.add_argument("--source-artifact-root")
    convert.add_argument("--target-root", required=True)
    convert.add_argument("--dry-run", action="store_true")
    convert.add_argument("--expected-fingerprint")
    convert.set_defaults(database_policy=None)
    check = actions.add_parser("migration-check", help="Verify the immutable migration report and preserved target objects")
    check.add_argument("--target-root", required=True)
    check.set_defaults(database_policy=None)


def _cmd_archive(args: argparse.Namespace) -> int:
    from bili_asr.services.migration_preflight import migration_preflight
    from bili_asr.services.archive_migration import initialize_archive, migrate_archive, check_migrated_archive, migrate_snapshot

    try:
        if args.archive_action == "init":
            report = initialize_archive(Path(args.target_root))
        elif args.archive_action == "migration-check":
            report = check_migrated_archive(Path(args.target_root))
        elif args.archive_action == "migrate":
            options = {"dry_run": args.dry_run, "expected_fingerprint": args.expected_fingerprint}
            if args.source_snapshot:
                if args.source_artifact_root:
                    raise ValueError("snapshot migration cannot select an external artifact root")
                report = migrate_snapshot(Path(args.source_snapshot), Path(args.target_root), **options)
            else:
                report = migrate_archive(Path(args.source_root), Path(args.target_root),
                    artifact_root=Path(args.source_artifact_root) if args.source_artifact_root else None, **options)
        else:
            report = migration_preflight(
            Path(args.source_root),
            artifact_root=Path(args.source_artifact_root) if args.source_artifact_root else None,
        )
    except (ValueError, OSError) as exc:
        write_stderr(f"archive {args.archive_action}: {exc}")
        return 1
    except sqlite3.Error:
        write_stderr(f"archive {args.archive_action}: database validation failed")
        return 1
    if getattr(args, "format", "json") == "json":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        totals = report["totals"]
        print(f"Source contract: {report['source']['contract_id']}")
        print(f"Source fingerprint: {report['source']['fingerprint']}")
        print(f"Tables: {len(report['tables'])}; rows: {totals['table_rows']}; "
              f"files: {totals['file_count']}; bytes: {totals['file_bytes']}")
        print("Mode: stopped-checkpointed; conversion performed: false; target created: false")
        print("Recovery candidates: " + json.dumps(report["recovery_candidates"], sort_keys=True))
    return 0
