"""Explicit legacy archive inspection before a separately implemented migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bili_asr.diagnostics import write_stderr


def add_archive_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("archive", help="Inspect a legacy archive before migration")
    actions = parser.add_subparsers(dest="archive_action", required=True)
    preflight = actions.add_parser(
        "migration-preflight", help="Validate and inventory a stopped, checkpointed legacy archive",
    )
    preflight.add_argument("--source-root", required=True, help="Existing legacy archive directory")
    preflight.add_argument(
        "--source-artifact-root", help="Explicit source artifact root; does not use BILI_ARTIFACT_ROOT",
    )
    preflight.add_argument("--format", choices=("json", "text"), default="json")


def _cmd_archive(args: argparse.Namespace) -> int:
    from bili_asr.services.migration_preflight import migration_preflight

    try:
        report = migration_preflight(
            Path(args.source_root),
            artifact_root=Path(args.source_artifact_root) if args.source_artifact_root else None,
        )
    except (ValueError, OSError) as exc:
        write_stderr(f"archive migration-preflight: {exc}")
        return 1
    if args.format == "json":
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
