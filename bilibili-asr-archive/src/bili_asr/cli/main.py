"""Public entry point: `bili-asr` -> `main()`."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr

import argparse
import os
import sys

from bili_asr.artifact_root import (
    ArtifactRootError,
    resolve_keep_audio,
    roots_for,
)
from bili_asr.cli.parser import build_parser

_ARCHIVE_WRITER_COMMANDS = frozenset({
    "fetch-meta",
    "recover",
    "asr",
    "pilot",
    "derive-manifest",
    # derive-audio-inventory writes audio_objects / part_audio_objects, so it
    # takes the same lock every other store-writing command takes.  Without
    # this the docstring's `archive_busy` refusal could not happen, and the
    # store would be written while another writer held the lock -- while the
    # read sets are fetched before the walk, so an unlocked run could report
    # counters computed against a store that moved under it.
    "derive-audio-inventory",
    "adopt-transcripts",
    "publish-transcripts",
    "harvest-subs",
    "download-audio",
    "run",
    "campaign",
    "schedule",
})


_ARTIFACT_WRITER_COMMANDS = frozenset({
    "asr", "pilot", "download-audio", "run", "campaign", "schedule",
    "publish-transcripts", "proofread", "proofread-merge",
})


def _dispatch_command(args: argparse.Namespace) -> int:
    import bili_asr.cli as _cli_pkg

    if args.command == "fetch-meta":
        return _cli_pkg._cmd_fetch_meta(args)
    if args.command == "status":
        return _cli_pkg._cmd_status(args)
    if args.command == "coverage":
        return _cli_pkg._cmd_coverage(args)
    if args.command == "verify":
        return _cli_pkg._cmd_verify(args)
    if args.command == "recover":
        return _cli_pkg._cmd_recover(args)
    if args.command == "runs":
        return _cli_pkg._cmd_runs(args)
    if args.command == "asr":
        return _cli_pkg._cmd_asr(args)
    if args.command == "pilot":
        return _cli_pkg._cmd_pilot(args)
    if args.command == "probe-subs":
        return _cli_pkg._cmd_probe_subs(args)
    if args.command == "harvest-subs":
        return _cli_pkg._cmd_harvest_subs(args)
    if args.command == "derive-manifest":
        return _cli_pkg._cmd_derive_manifest(args)
    if args.command == "derive-audio-inventory":
        return _cli_pkg._cmd_derive_audio_inventory(args)
    if args.command == "adopt-transcripts":
        return _cli_pkg._cmd_adopt_transcripts(args)
    if args.command == "publish-transcripts":
        return _cli_pkg._cmd_publish_transcripts(args)
    if args.command == "proofread":
        return _cli_pkg._cmd_proofread(args)
    if args.command == "proofread-merge":
        return _cli_pkg._cmd_proofread_merge(args)
    if args.command == "download-audio":
        return _cli_pkg._cmd_download_audio(args)
    if args.command == "search":
        return _cli_pkg._cmd_search(args)
    if args.command == "search-index":
        return _cli_pkg._cmd_search_index(args)
    if args.command == "evaluate-concurrency":
        return _cli_pkg._cmd_evaluate_concurrency(args)
    if args.command == "check-asr-env":
        return _cli_pkg._cmd_check_asr_env(args)
    if args.command == "export":
        return _cli_pkg._cmd_export(args)
    if args.command == "run":
        return _cli_pkg._cmd_run(args)
    if args.command == "campaign":
        return _cli_pkg._cmd_campaign(args)
    if args.command == "schedule":
        return _cli_pkg._cmd_schedule(args)
    raise ValueError(f"command {args.command!r} is not implemented")


def _main(argv: list[str] | None = None) -> int:
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
    # One resolution for the whole invocation, before the writer lock (contract §9).
    # Only a command that declares `--artifact-root` resolves one — the six commands
    # the flag is deliberately not on read no artifact path, and refusing them for a
    # configuration they cannot honour would be a false statement about the interface
    # (D18).  Resolving here rather than inside a handler is what keeps a refused
    # invocation from creating `{archive_root}/coordinator/` (the lock's documented
    # side effect) and what keeps a handler's broad `except Exception` — `coverage`'s,
    # for one — from swallowing the real reason.
    if hasattr(args, "artifact_root"):
        try:
            args.artifact_roots = roots_for(
                args.archive_root,
                flag_value=args.artifact_root,
                require_writable=args.command in _ARTIFACT_WRITER_COMMANDS,
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
    if args.command in _ARCHIVE_WRITER_COMMANDS:
        from bili_asr.coordinator import ArchiveBusyError, archive_writer

        try:
            with archive_writer(args.archive_root):
                return _cli_pkg._dispatch_command(args)
        except ArchiveBusyError:
            write_stderr(f"{args.command}: archive_busy")
            return 1
    return _cli_pkg._dispatch_command(args)
