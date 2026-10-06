"""Public entry point: `bili-asr` -> `main()`."""

from __future__ import annotations

import bili_asr.cli.asr as _module_cli_asr
import bili_asr.cli.pilot as _module_cli_pilot
import bili_asr.cli.run as _module_cli_run


from bili_asr.diagnostics import write_stderr

import argparse
import sys
import types
import os
import sys
import bili_asr.cli.parser as _module_cli_parser

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
    from bili_asr.cli import adopt as adopt_commands
    from bili_asr.cli import asr as asr_commands
    from bili_asr.cli import concurrency as concurrency_commands
    from bili_asr.cli import meta as meta_commands
    from bili_asr.cli import ops as ops_commands
    from bili_asr.cli import pilot as pilot_commands
    from bili_asr.cli import publish as publish_commands
    from bili_asr.cli import queue as queue_commands
    from bili_asr.cli import run as run_commands
    from bili_asr.cli import search as search_commands
    from bili_asr.cli import status_cmd as status_cmd_commands

    if args.command == "fetch-meta":
        return meta_commands._cmd_fetch_meta(args)
    if args.command == "status":
        return status_cmd_commands._cmd_status(args)
    if args.command == "coverage":
        return status_cmd_commands._cmd_coverage(args)
    if args.command == "verify":
        return ops_commands._cmd_verify(args)
    if args.command == "recover":
        return ops_commands._cmd_recover(args)
    if args.command == "runs":
        return status_cmd_commands._cmd_runs(args)
    if args.command == "asr":
        return _module_cli_asr._cmd_asr(args)
    if args.command == "pilot":
        return _module_cli_pilot._cmd_pilot(args)
    if args.command == "probe-subs":
        return meta_commands._cmd_probe_subs(args)
    if args.command == "harvest-subs":
        return meta_commands._cmd_harvest_subs(args)
    if args.command == "derive-manifest":
        return queue_commands._cmd_derive_manifest(args)
    if args.command == "derive-audio-inventory":
        return queue_commands._cmd_derive_audio_inventory(args)
    if args.command == "adopt-transcripts":
        return adopt_commands._cmd_adopt_transcripts(args)
    if args.command == "publish-transcripts":
        return publish_commands._cmd_publish_transcripts(args)
    if args.command == "proofread":
        return publish_commands._cmd_proofread(args)
    if args.command == "proofread-merge":
        return publish_commands._cmd_proofread_merge(args)
    if args.command == "download-audio":
        return queue_commands._cmd_download_audio(args)
    if args.command == "search":
        return search_commands._cmd_search(args)
    if args.command == "search-index":
        return search_commands._cmd_search_index(args)
    if args.command == "evaluate-concurrency":
        return concurrency_commands._cmd_evaluate_concurrency(args)
    if args.command == "check-asr-env":
        return ops_commands._cmd_check_asr_env(args)
    if args.command == "export":
        return ops_commands._cmd_export(args)
    if args.command == "run":
        return _module_cli_run._cmd_run(args)
    if args.command == "campaign":
        return _module_cli_run._cmd_campaign(args)
    if args.command == "schedule":
        return _module_cli_run._cmd_schedule(args)
    raise ValueError(f"command {args.command!r} is not implemented")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, resolve roots and dispatch under the writer lock."""
    parser = _module_cli_parser.build_parser()
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
        from bili_asr.pipeline.locks import ArchiveBusyError, archive_writer

        try:
            with archive_writer(args.archive_root):
                return _dispatch_command(args)
        except ArchiveBusyError:
            write_stderr(f"{args.command}: archive_busy")
            return 1
    return _dispatch_command(args)


class _CallableModule(types.ModuleType):
    """Make the dispatcher module usable as the console-script callable."""

    def __call__(self, argv: list[str] | None = None) -> int:
        return _main_impl(argv)


_main_impl = main
sys.modules[__name__].__class__ = _CallableModule
# Preserve the historical import shape used by subprocess hooks while keeping
# the module itself callable for the console-script entry point.
main = sys.modules[__name__]
sys.modules[__name__ + ".main"] = sys.modules[__name__]
__path__ = []
