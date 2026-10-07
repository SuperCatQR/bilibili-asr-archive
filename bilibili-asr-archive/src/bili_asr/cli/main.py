"""Public entry point: `bili-asr` -> `main()`."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr

import argparse
import os
import sys

# Keep the historical dotted import path usable while ``cli.main`` is now a
# module.  A few orchestration tests import the module through this nested
# spelling to patch its root resolver in isolation.
__path__ = []
sys.modules.setdefault(__name__ + ".main", sys.modules[__name__])

from bili_asr.artifact_root import (
    ArtifactRootError,
    resolve_keep_audio,
    roots_for,
)
from bili_asr.cli.parser import build_parser

from bili_asr.cli.registry import (
    ARCHIVE_WRITER_COMMANDS as _ARCHIVE_WRITER_COMMANDS,
    ARTIFACT_WRITER_COMMANDS as _ARTIFACT_WRITER_COMMANDS,
    COMMANDS,
    ArtifactPolicy,
)


def _dispatch_command(args: argparse.Namespace) -> int:
    import bili_asr.cli as _cli_pkg

    spec = COMMANDS.get(args.command)
    if spec is None:
        raise ValueError(f"command {args.command!r} is not implemented")
    return getattr(_cli_pkg, spec.handler)(args)


def _main(argv: list[str] | None = None, *, _publication_worker: bool = False) -> int:
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
    if args.command == "publish-transcripts" and not _publication_worker:
        from bili_asr.services.publication_supervisor import supervise_publication
        return supervise_publication(
            list(sys.argv[1:] if argv is None else argv),
            timeout_seconds=args.io_timeout_seconds,
        )
    # One resolution for the whole invocation, before the writer lock (contract §9).
    # Only a command that declares `--artifact-root` resolves one — the six commands
    # the flag is deliberately not on read no artifact path, and refusing them for a
    # configuration they cannot honour would be a false statement about the interface
    # (D18).  Resolving here rather than inside a handler is what keeps a refused
    # invocation from creating `{archive_root}/coordinator/` (the lock's documented
    # side effect) and what keeps a handler's broad `except Exception` — `coverage`'s,
    # for one — from swallowing the real reason.
    if spec.artifacts is not ArtifactPolicy.NONE:
        try:
            args.artifact_roots = roots_for(
                args.archive_root,
                flag_value=args.artifact_root,
                require_writable=spec.artifacts is ArtifactPolicy.WRITE,
            )
        except ArtifactRootError as exc:
            write_stderr(f"{args.command}: {exc}")
            return 1
    # The retention policy resolves on its own guard, not inside the artifact-root one.
    # Nesting it there would leave `keep_audio` as `None` for a future command that
    # carries the pair without the root flag — falsy at `reclaim_audio`'s `if keep:`,
    # i.e. a silent reclaim on a command whose default is retain.  It is resolved here
    # for the five commands that carry the pair (spec §7); the libraries receive a value
    # and never read the environment themselves (D15).
    if hasattr(args, "keep_audio"):
        args.keep_audio = resolve_keep_audio(args.keep_audio, os.environ)
    if spec.mutates_archive:
        from bili_asr.coordinator import ArchiveBusyError, archive_writer

        try:
            with archive_writer(args.archive_root):
                return _cli_pkg._dispatch_command(args)
        except ArchiveBusyError:
            write_stderr(f"{args.command}: archive_busy")
            return 1
    return _cli_pkg._dispatch_command(args)


def main(argv: list[str] | None = None) -> int:
    """Module-level entry point retained for ``python -m bili_asr.cli.main``."""
    return _main(argv)
