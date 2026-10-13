"""Internal review exports have an explicit command and separate output contract."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from bili_asr.cli.publication import _common, archive_connection, print_result
from bili_asr.cli.registry import ArtifactPolicy
from bili_asr.diagnostics import write_stderr


def _cmd_editorial(args) -> int:
    from bili_asr.publication_export import export_editorial

    try:
        if args.editorial_action == "plan":
            from dataclasses import replace

            from bili_asr.editorial import EditorialConfig
            from bili_asr.editorial_budget import plan_report, replan
            from bili_asr.storage.editorial import EditorialRepository

            with closing(archive_connection(args.archive_root)) as connection:
                original = EditorialRepository(connection).load_input(args.input_id)
            config = EditorialConfig.from_snapshot(original["snapshot"]["config"])
            plans = []
            for preset in args.preset or ("baseline-v1", "large-v1"):
                guards = EditorialConfig.preset(preset)
                candidate = replace(config, budget_policy="token-budget-v2", chunk_preset=preset,
                                    max_chunk_segments=guards.max_chunk_segments, max_chunk_chars=guards.max_chunk_chars)
                plans.append(plan_report(replan(original, candidate)))
            print_result({"source_input_id": args.input_id, "plans": plans, "physical_calls": 0}, "json")
            return 0
        with closing(archive_connection(args.archive_root)) as connection:
            result = export_editorial(
                connection, revision_id=args.revision_id, edition_id=args.edition_id,
                artifact_roots=args.artifact_roots.read_bases(), output=Path(args.out),
            )
        print_result(result, args.format)
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        write_stderr(f"editorial: {getattr(exc, 'error_code', getattr(exc, 'code', type(exc).__name__))}: {exc}")
        return 1


def add_editorial_parser(subparsers, *, archive_root: str) -> None:
    parser = subparsers.add_parser("editorial", help="Export AI 合成稿件 and 校验参照稿件 for internal review")
    actions = parser.add_subparsers(dest="editorial_action", required=True)
    plan = actions.add_parser("plan", help="Compare chunk presets over one immutable saved input without calling a model")
    _common(plan, archive_root)
    plan.add_argument("--input-id", required=True)
    plan.add_argument("--preset", action="append", choices=("baseline-v1", "large-v1"))
    export = actions.add_parser("export", help="Export selected edition, fixed references and differences")
    _common(export, archive_root, artifacts=ArtifactPolicy.READ)
    export.add_argument("--revision-id", required=True)
    export.add_argument("--edition-id", required=True)
    export.add_argument("--out", required=True)
