"""Public entry point: `bili-asr` -> `main()`."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr

import argparse
from pathlib import Path
import sys

# Keep the historical dotted import path usable while ``cli.main`` is now a
# module.  A few orchestration tests import the module through this nested
# spelling to patch its root resolver in isolation.
__path__ = []
sys.modules.setdefault(__name__ + ".main", sys.modules[__name__])

from bili_asr.artifact_root import (
    ArtifactRootError,
    roots_for,
)
from bili_asr.cli.parser import build_parser
from bili_asr.archive_maintenance import ArchiveAccessError, archive_access

from bili_asr.cli.registry import (
    COMMANDS,
    ArtifactPolicy,
)


def _dispatch_command(args: argparse.Namespace) -> int:
    import bili_asr.cli as _cli_pkg

    spec = COMMANDS.get(args.command)
    if spec is None:
        raise ValueError(f"command {args.command!r} is not implemented")
    return getattr(_cli_pkg, spec.handler)(args)


def _main(
    argv: list[str] | None = None,
    *,
    _publication_worker: bool = False,
    _asr_worker: bool = False,
) -> int:
    """Implementation of ``main``; the public ``main`` lives in ``bili_asr.cli``
    so that tests monkeypatching ``bili_asr.cli.build_parser`` /
    ``bili_asr.cli._dispatch_command`` observe the patched attributes."""
    # Resolve through the package namespace so monkeypatches against
    # ``bili_asr.cli`` take effect (the split moved ``main`` out of the package
    # ``__init__``, but the test contract still pins the package attributes).
    import bili_asr.cli as _cli_pkg

    parser = _cli_pkg.build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    spec = COMMANDS.get(args.command)
    if spec is None:
        raise ValueError(f"command {args.command!r} is not implemented")
    # Resolve configured artifact roots once at the command boundary.
    if spec.artifacts is not ArtifactPolicy.NONE:
        try:
            args.artifact_roots = roots_for(
                args.archive_root,
                flag_value=args.artifact_root,
                require_writable=False,
            )
        except ArtifactRootError as exc:
            write_stderr(f"{args.command}: {exc}")
            return 1
    # Include commands that initialize schema or rebuild FTS, even when their
    # main purpose is querying. Snapshot service owns its exclusive access.
    writes_archive = args.command in {
        "fetch-meta", "workflow", "reading-review", "reading-edit", "search-index",
    } or (args.command == "search" and args.rebuild) or (
        args.command in {"status", "runs"} and (Path(args.archive_root) / "archive.db").is_file()
    )
    if writes_archive:
        try:
            with archive_access(args.archive_root):
                return _cli_pkg._dispatch_command(args)
        except ArchiveAccessError as exc:
            write_stderr(f"{args.command}: {exc}")
            return 1
    return _cli_pkg._dispatch_command(args)


def main(argv: list[str] | None = None) -> int:
    """Module-level entry point retained for ``python -m bili_asr.cli.main``."""
    return _main(argv)
