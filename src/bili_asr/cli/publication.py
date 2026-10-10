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
from bili_asr.archive_session import ArchiveAccessMode, ArchiveContract, open_archive_connection


def archive_connection(archive_root: str, *, readonly: bool = True) -> sqlite3.Connection:
    return open_archive_connection(archive_root,
        mode=ArchiveAccessMode.READ if readonly else ArchiveAccessMode.WRITE,
        contract=ArchiveContract.MANUSCRIPT)


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
    if action == "series":
        return _cmd_series(args)
    readonly = action in {"show", "export", "export-drafts"}
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
            elif action == "sync-source-tags":
                from bili_asr.publication_tags import sync_source_tags
                result = sync_source_tags(connection, edition_id=args.edition_id,
                                          actor=args.actor, note=args.note)
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
            elif action == "export-drafts":
                from bili_asr.publication_export import export_publication_drafts
                count = export_publication_drafts(connection, artifact_roots=args.artifact_roots.read_bases(),
                                                 output=Path(args.out), series_file=Path(args.series_file) if args.series_file else None)
                result = {"manuscriptType": "publication-draft", "count": count, "output": args.out}
            else:
                from bili_asr.publication_export import export_publications
                count = export_publications(connection, artifact_roots=args.artifact_roots.read_bases(),
                                            output=Path(args.out), series_file=Path(args.series_file) if args.series_file else None)
                result = {"manuscriptType": "publication", "count": count, "output": args.out}
            if action == "create" and (result["content_version"] == 1 or result["content"]["source"]["platform"] == "bilibili"):
                from bili_asr.publication_tags import tag_coverage
                source = result["content"]["source"]
                bvid = source["bvid"] if result["content_version"] == 1 else source["externalVideoId"]
                coverage = tag_coverage(connection, bvid)
                if coverage in {"not_attempted", "unavailable"}:
                    write_stderr(f"publication create: source tag coverage {coverage}; run fetch-tags then sync-source-tags")
        print_result(result, args.format)
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        write_stderr(f"publication {action}: {getattr(exc, 'code', type(exc).__name__)}: {exc}")
        return 1


def _cmd_series(args: argparse.Namespace) -> int:
    from bili_asr.publication_series import edit_series, read_series_with_sha256, editorial_version
    try:
        if args.series_action == "edit":
            result = edit_series(Path(args.input), Path(args.out), actor=args.actor,
                                 expected_sha256=args.expected_sha256)
        else:
            path = Path(args.series_file)
            value, digest = read_series_with_sha256(path)
            result = {"sha256": digest,
                      "editorialVersion": editorial_version(value), "seriesCount": len(value["series"])}
            if args.series_action == "show":
                result["content"] = value
        # Series content is JSON, rather than the manuscript markdown printer.
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        write_stderr(f"publication series {args.series_action}: {exc}")
        return 1


def _common(parser, archive_root, *, artifacts=ArtifactPolicy.NONE, actor=False, note=False,
            database=ArchiveAccessMode.READ):
    parser.add_argument("--archive-root", default=archive_root)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.set_defaults(artifact_policy=artifacts, database_policy=database)
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
    _common(create, archive_root, artifacts=ArtifactPolicy.READ, actor=True, database=ArchiveAccessMode.WRITE)
    create.add_argument("--revision-id", required=True)
    create.add_argument("--expected-edition-id", default=None)
    create.add_argument("--note", default="")

    edit = actions.add_parser("edit", help="Save an immutable edition using the expected parent")
    _common(edit, archive_root, actor=True, note=True, database=ArchiveAccessMode.WRITE)
    edit.add_argument("--edition-id", required=True, help="Expected current parent edition")
    edit.add_argument("--markdown-file", required=True)
    edit.add_argument("--metadata-file", default=None, help="Strict JSON with allowed reader fields")

    sync_tags = actions.add_parser("sync-source-tags", help="Freeze original video tags into a new pending-review edition")
    _common(sync_tags, archive_root, actor=True, note=True, database=ArchiveAccessMode.WRITE)
    sync_tags.add_argument("--edition-id", required=True, help="Expected current parent edition")

    review = actions.add_parser("review", help="Review a specific edition and its complete content hash")
    _common(review, archive_root, actor=True, note=True, database=ArchiveAccessMode.WRITE)
    review.add_argument("--edition-id", required=True)
    review.add_argument("--status", required=True,
                        choices=("in-review", "changes-requested", "approved", "rejected"))
    review.add_argument("--content-sha256", required=True)
    review.add_argument("--expected-status", required=True,
                        choices=("pending-review", "in-review", "changes-requested", "approved", "rejected"))
    review.add_argument("--issue-url", default=None)

    publish = actions.add_parser("publish", help="Materialize publish.md from an approved edition")
    _common(publish, archive_root, artifacts=ArtifactPolicy.WRITE, actor=True, database=ArchiveAccessMode.WRITE)
    publish.add_argument("--edition-id", required=True)
    publish.add_argument("--expected-release-id", default=None)

    withdraw = actions.add_parser("withdraw", help="Withdraw the specified release, retaining its history")
    _common(withdraw, archive_root, actor=True, note=True, database=ArchiveAccessMode.WRITE)
    withdraw.add_argument("--release-id", required=True)

    show = actions.add_parser("show", help="Read edition content, review hash and draft/release pointers")
    _common(show, archive_root)
    show.add_argument("--edition-id", required=True)

    export = actions.add_parser("export", help="Export only currently released 发布稿")
    _common(export, archive_root, artifacts=ArtifactPolicy.READ)
    export.add_argument("--out", required=True)
    export.add_argument("--series-file", default=None, help="Editor-confirmed series source, optional and separately versioned")

    drafts = actions.add_parser("export-drafts", help="Export current reader drafts that have never been released")
    _common(drafts, archive_root, artifacts=ArtifactPolicy.READ)
    drafts.add_argument("--out", required=True)
    drafts.add_argument("--series-file", default=None, help="Editor-confirmed series source, optional and separately versioned")

    series = actions.add_parser("series", help="Maintain editor-confirmed series metadata without changing the archive database")
    series_actions = series.add_subparsers(dest="series_action", required=True)
    for action in ("validate", "show", "edit"):
        command = series_actions.add_parser(action)
        command.set_defaults(artifact_policy=ArtifactPolicy.NONE, database_policy=None)
        if action == "edit":
            command.add_argument("--input", required=True)
            command.add_argument("--out", required=True)
            command.add_argument("--actor", required=True)
            command.add_argument("--expected-sha256", required=True, help="Current raw file SHA-256, or new for a new file")
        else:
            command.add_argument("--series-file", required=True)
