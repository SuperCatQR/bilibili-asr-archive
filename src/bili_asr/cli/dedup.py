"""Read-only exact-duplicate inventory command."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from bili_asr.dedup import build_report, format_text
from bili_asr.diagnostics import write_stderr
from bili_asr.artifact_root import ArtifactRoots


def _readonly_connection(archive_root: str) -> sqlite3.Connection:
    path = ArtifactRoots.of(archive_root).archive_root / "archive.db"
    if not path.is_file():
        raise FileNotFoundError(f"no archive database at {path}")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _cmd_dedup(args: argparse.Namespace) -> int:
    if args.dedup_action != "report":
        write_stderr("dedup: unsupported action")
        return 1
    if args.limit < 1:
        write_stderr("dedup report: --limit must be positive")
        return 1
    try:
        with closing(_readonly_connection(args.archive_root)) as connection:
            report = build_report(connection, limit=args.limit)
    except (OSError, sqlite3.Error, ValueError) as exc:
        write_stderr(f"dedup report: {exc}")
        return 1
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_text(report))
    return 0
