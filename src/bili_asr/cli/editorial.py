"""Internal review exports have an explicit command and separate output contract."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from bili_asr.cli.publication import _common, archive_connection, print_result
from bili_asr.cli.registry import ArtifactPolicy
from bili_asr.diagnostics import write_stderr


def _cmd_editorial(args) -> int:
    from bili_asr.publication_export import export_editorial

    try:
        with closing(archive_connection(args.archive_root)) as connection:
            result = export_editorial(
                connection, revision_id=args.revision_id, edition_id=args.edition_id,
                artifact_roots=args.artifact_roots.read_bases(), output=Path(args.out),
            )
        print_result(result, args.format)
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        write_stderr(f"editorial export: {getattr(exc, 'code', type(exc).__name__)}: {exc}")
        return 1


def add_editorial_parser(subparsers, *, archive_root: str) -> None:
    parser = subparsers.add_parser("editorial", help="Export AI 合成稿件 and 校验参照稿件 for internal review")
    actions = parser.add_subparsers(dest="editorial_action", required=True)
    export = actions.add_parser("export", help="Export selected edition, fixed references and differences")
    _common(export, archive_root, artifacts=ArtifactPolicy.READ)
    export.add_argument("--revision-id", required=True)
    export.add_argument("--edition-id", required=True)
    export.add_argument("--out", required=True)
