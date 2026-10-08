"""Explicit editing, review and release commands for publication manuscripts."""

from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from bili_asr.cli._shared import _ARTIFACT_ROOT_HELP
from bili_asr.cli.registry import ArtifactPolicy
from bili_asr.diagnostics import write_stderr


def archive_connection(archive_root: str, *, readonly: bool = True) -> sqlite3.Connection:
    from bili_asr.storage.database import require_manuscript_schema
    from bili_asr.manuscript_files import secure_path

    path = secure_path(Path(archive_root), "archive.db")
    if not path.is_file():
        raise FileNotFoundError(f"no archive database at {path}")
    mode = "ro" if readonly else "rw"
    connection = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        require_manuscript_schema(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        if readonly:
            connection.execute("PRAGMA query_only = ON")
        return connection
    except BaseException:
        connection.close()
        raise


def validate_archive(archive_root: str) -> None:
    with closing(archive_connection(archive_root)):
        pass


def _json_object(path: str) -> dict:
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate metadata key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    result = json.loads(Path(path).read_text(encoding="utf-8"),
                        object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("metadata file must contain a JSON object")
    return result


def print_result(result: dict, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        for key, value in result.items():
            if not isinstance(value, (dict, list)):
                print(f"{key}: {value}")
        if "content" in result:
            from bili_asr.publication import render_publication
            print()
            print(render_publication(result["content"]).decode("utf-8"), end="")


def _cmd_publication(args: argparse.Namespace) -> int:
    from bili_asr import publication

    action = args.publication_action
    readonly = action in {"show", "export"}
    try:
        with closing(archive_connection(args.archive_root, readonly=readonly)) as connection:
            if action == "create":
                result = publication.create_edition(
                    connection, revision_id=args.revision_id,
                    artifact_roots=args.artifact_roots.read_bases(),
                    actor=args.actor, note=args.note, expected_edition_id=args.expected_edition_id,
                )
            elif action == "edit":
                metadata = _json_object(args.metadata_file) if args.metadata_file else None
                result = publication.edit_edition(
                    connection, edition_id=args.edition_id,
                    markdown_text=Path(args.markdown_file).read_text(encoding="utf-8"),
                    metadata=metadata, actor=args.actor, note=args.note,
                )
            elif action == "review":
                result = publication.review_edition(
                    connection, edition_id=args.edition_id, status=args.status,
                    content_sha256=args.content_sha256, expected_status=args.expected_status,
                    actor=args.actor, note=args.note, issue_url=args.issue_url,
                )
            elif action == "publish":
                result = publication.publish_edition(
                    connection, edition_id=args.edition_id,
                    artifact_roots=args.artifact_roots.read_bases(), write_root=args.artifact_roots.write_base,
                    actor=args.actor, expected_release_id=args.expected_release_id,
                )
            elif action == "withdraw":
                result = publication.withdraw_release(
                    connection, release_id=args.release_id, actor=args.actor, note=args.note,
                )
            elif action == "show":
                result = publication.get_edition(connection, args.edition_id)
            else:
                from bili_asr.publication_export import export_publications
                count = export_publications(connection, artifact_roots=args.artifact_roots.read_bases(),
                                            output=Path(args.out))
                result = {"manuscriptType": "publication", "count": count, "output": args.out}
        print_result(result, args.format)
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        write_stderr(f"publication {action}: {getattr(exc, 'code', type(exc).__name__)}: {exc}")
        return 1


def _common(parser, archive_root, *, artifacts=ArtifactPolicy.NONE, actor=False, note=False):
    parser.add_argument("--archive-root", default=archive_root)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.set_defaults(artifact_policy=artifacts)
    if artifacts is not ArtifactPolicy.NONE:
        parser.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    if actor:
        parser.add_argument("--actor", required=True, help="Recorded operator identifier")
    if note:
        parser.add_argument("--note", required=True)


def add_publication_parser(subparsers, *, archive_root: str) -> None:
    parser = subparsers.add_parser("publication", help="Edit, review and explicitly release 发布稿")
    actions = parser.add_subparsers(dest="publication_action", required=True)
    create = actions.add_parser("create", help="Create a pending edition from AI 合成稿件")
    _common(create, archive_root, artifacts=ArtifactPolicy.READ, actor=True)
    create.add_argument("--revision-id", required=True)
    create.add_argument("--expected-edition-id", default=None)
    create.add_argument("--note", default="")

    edit = actions.add_parser("edit", help="Save an immutable edition using the expected parent")
    _common(edit, archive_root, actor=True, note=True)
    edit.add_argument("--edition-id", required=True, help="Expected current parent edition")
    edit.add_argument("--markdown-file", required=True)
    edit.add_argument("--metadata-file", default=None, help="Strict JSON with allowed reader fields")

    review = actions.add_parser("review", help="Review a specific edition and its complete content hash")
    _common(review, archive_root, actor=True, note=True)
    review.add_argument("--edition-id", required=True)
    review.add_argument("--status", required=True,
                        choices=("in-review", "changes-requested", "approved", "rejected"))
    review.add_argument("--content-sha256", required=True)
    review.add_argument("--expected-status", required=True,
                        choices=("pending-review", "in-review", "changes-requested", "approved", "rejected"))
    review.add_argument("--issue-url", default=None)

    publish = actions.add_parser("publish", help="Materialize publish.md from an approved edition")
    _common(publish, archive_root, artifacts=ArtifactPolicy.WRITE, actor=True)
    publish.add_argument("--edition-id", required=True)
    publish.add_argument("--expected-release-id", default=None)

    withdraw = actions.add_parser("withdraw", help="Withdraw the specified release, retaining its history")
    _common(withdraw, archive_root, actor=True, note=True)
    withdraw.add_argument("--release-id", required=True)

    show = actions.add_parser("show", help="Read edition content, review hash and draft/release pointers")
    _common(show, archive_root)
    show.add_argument("--edition-id", required=True)

    export = actions.add_parser("export", help="Export only currently released 发布稿")
    _common(export, archive_root, artifacts=ArtifactPolicy.READ)
    export.add_argument("--out", required=True)
