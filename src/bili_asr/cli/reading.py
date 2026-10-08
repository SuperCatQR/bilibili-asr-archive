"""Import editorial reading documents and record review decisions."""

from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3

from bili_asr.diagnostics import write_stderr
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.reading_publication import (
    DEFAULT_ISSUES_URL,
    REVIEW_STATUSES,
    export_reading_site,
    store_reading_edition,
    update_reading_status,
)


def _readonly_connection(archive_root: str) -> sqlite3.Connection:
    path = ArtifactRoots.of(archive_root).archive_root / "archive.db"
    if not path.is_file():
        raise FileNotFoundError(f"no archive database at {path}")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _cmd_reading_export(args: argparse.Namespace) -> int:
    try:
        with closing(_readonly_connection(args.archive_root)) as connection:
            count = export_reading_site(
                connection,
                artifact_roots=args.artifact_roots.read_bases(),
                output=Path(args.out),
                issues_url=args.issues_url,
            )
        print(f"Imported {count} reading document(s) into {Path(args.out)}")
        return 0
    except Exception as exc:
        write_stderr(f"reading-export: {exc}")
        return 1


def _cmd_reading_review(args: argparse.Namespace) -> int:
    path = Path(args.archive_root) / "archive.db"
    if not path.is_file():
        write_stderr(f"reading-review: no archive database at {path}")
        return 1
    from bili_asr.storage.database import open_database

    try:
        connection = open_database(args.archive_root)
        try:
            update_reading_status(
                connection,
                revision_id=args.revision_id,
                status=args.status,
                issue_url=args.issue_url,
                note=args.note,
            )
        finally:
            connection.close()
    except Exception as exc:
        write_stderr(f"reading-review: {exc}")
        return 1
    print(f"{args.revision_id}: {args.status}")
    return 0


def _cmd_reading_edit(args: argparse.Namespace) -> int:
    path = Path(args.archive_root) / "archive.db"
    if not path.is_file():
        write_stderr(f"reading-edit: no archive database at {path}")
        return 1
    from bili_asr.storage.database import open_database

    try:
        markdown_text = Path(args.markdown_file).read_text(encoding="utf-8")
        connection = open_database(args.archive_root)
        try:
            edition_id = store_reading_edition(
                connection,
                revision_id=args.revision_id,
                markdown_text=markdown_text,
                note=args.note,
            )
        finally:
            connection.close()
    except Exception as exc:
        write_stderr(f"reading-edit: {exc}")
        return 1
    print(f"{args.revision_id}: stored human edition {edition_id}; status pending-review")
    return 0


def add_reading_parsers(subparsers: argparse._SubParsersAction, *, archive_root: str) -> None:
    export = subparsers.add_parser(
        "reading-export", help="Export reviewable editorial documents to the static reading site"
    )
    export.add_argument("--archive-root", default=archive_root)
    export.add_argument("--out", default="reading-site/content")
    export.add_argument("--issues-url", default=os.environ.get("BILI_READING_ISSUES_URL", DEFAULT_ISSUES_URL))

    review = subparsers.add_parser(
        "reading-review", help="Record a review or publication status for a reading revision"
    )
    review.add_argument("revision_id")
    review.add_argument("--status", choices=REVIEW_STATUSES, required=True)
    review.add_argument("--issue-url", default=None)
    review.add_argument("--note", default="")
    review.add_argument("--archive-root", default=archive_root)

    edit = subparsers.add_parser(
        "reading-edit", help="Store accepted Issue changes as a new immutable reading edition"
    )
    edit.add_argument("revision_id")
    edit.add_argument("--markdown-file", required=True)
    edit.add_argument("--note", default="")
    edit.add_argument("--archive-root", default=archive_root)
