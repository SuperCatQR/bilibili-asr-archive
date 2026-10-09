"""Portable archive snapshot commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from bili_asr.artifact_root import roots_for
from bili_asr.diagnostics import write_stderr


def add_snapshot_parser(subparsers: argparse._SubParsersAction, *, archive_root: str) -> None:
    parser = subparsers.add_parser("snapshot", help="Save, check, and restore portable archive snapshots")
    actions = parser.add_subparsers(dest="snapshot_action", required=True)
    save = actions.add_parser("save", help="Save a complete archive ZIP while writers are stopped")
    save.add_argument("--archive-root", default=archive_root)
    save.add_argument("--artifact-root", default=None, help="Existing artifact root (or BILI_ARTIFACT_ROOT)")
    save.add_argument("--out", required=True, help="New snapshot ZIP outside the archive roots")
    check = actions.add_parser("check", help="Verify snapshot hashes, database contract, and file references offline")
    check.set_defaults(database_policy=None)
    check.add_argument("--file", required=True, help="Snapshot ZIP to verify")
    restore = actions.add_parser("restore", help="Restore a verified snapshot into a new or empty archive root")
    restore.add_argument("--file", required=True, help="Snapshot ZIP to restore")
    restore.add_argument("--archive-root", required=True, help="New or empty target directory")


def _cmd_snapshot(args: argparse.Namespace) -> int:
    from bili_asr.services.archive_snapshot import check_snapshot, restore_snapshot, save_snapshot

    try:
        if args.snapshot_action == "save":
            roots = roots_for(args.archive_root, flag_value=args.artifact_root, require_writable=False)
            report = save_snapshot(
                Path(args.archive_root), Path(args.out),
                artifact_root=roots.artifact_root if roots.configured else None,
            )
        elif args.snapshot_action == "check":
            report = check_snapshot(Path(args.file))
        else:
            report = restore_snapshot(Path(args.file), Path(args.archive_root))
    except (ValueError, OSError, sqlite3.Error) as exc:
        write_stderr(f"snapshot {args.snapshot_action}: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0
