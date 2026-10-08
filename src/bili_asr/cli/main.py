"""Public entry point: `bili-asr` -> `main()`."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr

import argparse
import sys
import sqlite3
from bili_asr.storage.database import SchemaContractError, SQLITE_BUSY_TIMEOUT_ENV

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
    metadata_only_search = args.command == "search" and getattr(args, "scope", "transcripts") == "metadata"
    if spec.artifacts is not ArtifactPolicy.NONE and not metadata_only_search:
        try:
            args.artifact_roots = roots_for(
                args.archive_root,
                flag_value=args.artifact_root,
                require_writable=False,
            )
        except ArtifactRootError as exc:
            write_stderr(f"{args.command}: {exc}")
            return 1
    try:
        return _cli_pkg._dispatch_command(args)
    except SchemaContractError as exc:
        write_stderr(f"{args.command}: {exc}")
        return 1
    except sqlite3.OperationalError as exc:
        if getattr(exc, "sqlite_errorcode", 0) & 0xFF not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            raise
        write_stderr(f"{args.command}: SQLite contention timeout exceeded; stop competing writers "
                     f"or increase {SQLITE_BUSY_TIMEOUT_ENV}. Jobs remain recoverable; retry after contention clears.")
        return 1
    except ValueError as exc:
        if not str(exc).startswith(SQLITE_BUSY_TIMEOUT_ENV):
            raise
        write_stderr(f"{args.command}: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    """Module-level entry point retained for ``python -m bili_asr.cli.main``."""
    return _main(argv)
