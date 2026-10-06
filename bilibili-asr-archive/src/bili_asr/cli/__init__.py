"""Command-line interface for bili-asr (split package).

The original ``cli.py`` (~4,600 lines) was split by concern into this
subpackage. Public surface: ``main`` and ``build_parser``. The remaining
names are re-exported for backward compatibility with the existing test
suite, which pins private helpers.
"""

from __future__ import annotations

import time

from bili_asr import search_index

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _archive_database_exists,
    _metadata_database_path,
    _open_read_connection,
    _open_read_only_connection,
    _open_read_repository,
    _open_subtitle_connection,
    _queue_source_is_manifest,
    _record_api_error,
    _store_audio_todo,
    _store_transcript_todo,
    _subtitle_schema_rebuild_line,
    _subtitle_selector,
    _todo_for_bvid,
)
from bili_asr.cli.parser import build_parser
from bili_asr.cli.main import _ARCHIVE_WRITER_COMMANDS, _dispatch_command, _main
from bili_asr.cli.meta import _cmd_fetch_meta, _cmd_harvest_subs, _cmd_probe_subs
from bili_asr.cli.queue import (
    _cmd_derive_audio_inventory,
    _cmd_derive_manifest,
    _cmd_download_audio,
)
from bili_asr.cli.publish import (
    _cmd_proofread,
    _cmd_proofread_merge,
    _cmd_publish_transcripts,
)
from bili_asr.cli.status_cmd import (
    _BACKLOG_DIAGNOSTICS,
    _BACKLOG_REASONS,
    _BACKLOG_STATUSES,
    _cmd_coverage,
    _cmd_coverage_quality,
    _cmd_runs,
    _cmd_status,
)
from bili_asr.cli.asr import _cmd_asr
from bili_asr.cli.adopt import _cmd_adopt_transcripts
from bili_asr.cli.pilot import (
    _cmd_pilot,
    _expand_selected_pages,
    _pilot_archive_asr,
    _pilot_select,
)
from bili_asr.cli.run import (
    _cmd_campaign,
    _cmd_run,
    _cmd_schedule,
    _partial_run_state,
    _RunInterrupted,
    _interruptible_run,
    _signals_ignored,
)
from bili_asr.cli.search import _cmd_search, _cmd_search_index
from bili_asr.cli.ops import _cmd_check_asr_env, _cmd_export, _cmd_recover, _cmd_verify
from bili_asr.cli.concurrency import (
    _cmd_evaluate_concurrency,
    _ConcurrencyInputError,
    _read_concurrency_json_object,
)
from bili_asr.cli.workflow import _cmd_workflow

def main(argv: list[str] | None = None) -> int:
    """Public entry point; delegates to ``bili_asr.cli.main._main`` so that
    monkeypatches against ``bili_asr.cli.build_parser`` /
    ``bili_asr.cli._dispatch_command`` take effect."""
    return _main(argv)


__all__ = [
    "DEFAULT_ARCHIVE_ROOT",
    "build_parser",
    "main",
]
