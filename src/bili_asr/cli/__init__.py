"""Public command-line boundary for the SQLite workflow."""

from __future__ import annotations

import types
import sys

from bili_asr.cli._shared import DEFAULT_ARCHIVE_ROOT
from bili_asr.cli.parser import build_parser
from bili_asr.cli import main as main
from bili_asr.cli.main import _dispatch_command, _main
from bili_asr.cli.meta import _cmd_fetch_meta
from bili_asr.cli.status_cmd import _cmd_coverage, _cmd_runs, _cmd_status
from bili_asr.cli.search import _cmd_search, _cmd_search_index
from bili_asr.cli.ops import _cmd_check_asr_env, _cmd_export, _cmd_verify
from bili_asr.cli.workflow import _cmd_workflow
from bili_asr.cli.reading import _cmd_reading_edit, _cmd_reading_export, _cmd_reading_review

class _MainModule(types.ModuleType):
    """Keep the package attribute module-shaped and directly callable."""

    def __call__(self, argv: list[str] | None = None) -> int:
        return self.main(argv)


if not isinstance(main, _MainModule):
    main.__class__ = _MainModule


__all__ = [
    "DEFAULT_ARCHIVE_ROOT",
    "build_parser",
    "main",
]
