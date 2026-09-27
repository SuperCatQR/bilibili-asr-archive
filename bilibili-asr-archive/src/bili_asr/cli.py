"""Command-line interface for bili-asr."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .artifact_root import (
    ARTIFACT_ROOT_ENV_VAR,
    KEEP_AUDIO_ENV_VAR,
    ArtifactRootError,
    ArtifactRoots,
    resolve_keep_audio,
    roots_for,
)
from .config import (
    ARCHIVE_DATABASE_NAME,
    DEFAULT_MID,
    DEFAULT_PAGE_LIMIT,
    SESSDATA_ENV_VAR,
    MetadataConfigError,
    load_metadata_config,
    redact_sessdata,
    resolve_sessdata,
)

DEFAULT_ARCHIVE_ROOT = os.path.join("archive")

#: The `--artifact-root` help.  One string for the twelve commands that carry it
#: (spec §9): the flag's meaning, the environment fallback and the default are one
#: contract, and twelve copies of it would be twelve chances to describe it differently.
_ARTIFACT_ROOT_HELP = (
    f"Root for audio/transcript products (or env {ARTIFACT_ROOT_ENV_VAR}); "
    "default: the archive root. Must already exist"
)

#: The retention pair's help.  The default is stated because it flipped to *retain*
#: (contract D5) and an operator upgrading into it has to be told (spec §7).
_KEEP_AUDIO_HELP = (
    f"Keep each row's audio after it is archived (or env {KEEP_AUDIO_ENV_VAR}: "
    "1 keeps, 0 reclaims; default: keep)"
)

#: The audio cap's help.  Q1's ruling is that the cap keeps its fail-closed semantics
#: and the retention interaction is named where the operator meets it — here, and on
#: the skip line the cap prints.
_MAX_AUDIO_GB_HELP = (
    "Skip audio downloads that would push audio/ past this many GiB "
    "(0 = unlimited); retained audio counts toward it, so a retaining "
    "operator keeps downloading with --max-audio-gb 0"
)

#: `schedule`'s own cap help: the retention interaction holds in both of its modes, the
#: lever does not.  `--allow-long-live` refuses a disabled cap
#: (``long_live.refuse_disabled_audio_cap``), so the shared wording above would be advice
#: that is false in one mode on the one command that has two — and a hint that is false in
#: one mode is worse than an absent hint (plan R8, QC2 W-2).  The exception is stated
#: instead of the advice, so every claim is true of the mode it is read in.
_MAX_AUDIO_GB_HELP_SCHEDULE = (
    "Skip audio downloads that would push audio/ past this many GiB "
    "(0 = unlimited); retained audio counts toward it, so a retaining "
    "operator raises the cap — --max-audio-gb 0 is refused under "
    "--allow-long-live"
)

#: The same advisory as it appears on a skip line, so the commands that print one
#: print the same words (Q1: the line that reports the cap names the flag that lifts
#: it — with retention on, `audio/` only grows, so `0` is the operator's lever).
_AUDIO_BUDGET_SKIP_HINT = (
    "; audio-dir budget cap reached (--max-audio-gb 0 = unlimited)"
)


class _UsageErrorArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors by default.

    Spec exit taxonomy reserves 2 for terminal API failure; usage/config
    errors must exit 1 (QC2-2). --help / --version keep exit 0.
    """

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 2:
            status = 1
        super().exit(status, message)


def build_parser() -> argparse.ArgumentParser:
    parser = _UsageErrorArgumentParser(
        prog="bili-asr",
        description="Bilibili ASR transcript archival CLI "
        "(AI/CC subtitles first, local FunASR fallback).",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    fetch_meta = subparsers.add_parser(
        "fetch-meta",
        help="Collect video metadata for a user into the SQLite archive database",
    )
    fetch_meta.add_argument("--mid", type=int, default=DEFAULT_MID,
                            help="Bilibili user mid")
    resume_or_start = fetch_meta.add_mutually_exclusive_group()
    resume_or_start.add_argument(
        "--resume", action="store_true",
        help="Resume from the stored cursor; fails when none exists",
    )
    resume_or_start.add_argument(
        "--start-page", type=int, default=None,
        help="Explicit one-based start page (overrides the stored cursor)",
    )
    fetch_meta.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    fetch_meta.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )
    fetch_meta.add_argument(
        "--limit-pages", type=int, default=None,
        help=f"Stop after collecting N pages (default: {DEFAULT_PAGE_LIMIT})",
    )

    status = subparsers.add_parser(
        "status",
        help="Print collected metadata status from the SQLite archive database",
    )
    status.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    runs = subparsers.add_parser(
        "runs",
        help="List recent metadata collection runs from the SQLite archive database",
    )
    runs.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N recent runs (default: all)",
    )
    runs.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    asr_cmd = subparsers.add_parser("asr", help="Transcribe audio and write transcript archive")
    asr_cmd.add_argument("--pending", action="store_true", help="Process audio_ok entries")
    asr_cmd.add_argument("--bvid", default=None)
    asr_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    asr_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    asr_cmd.add_argument(
        "--keep-audio", action=argparse.BooleanOptionalAction, default=None,
        help=_KEEP_AUDIO_HELP,
    )
    asr_cmd.add_argument("--limit", type=int, default=None)

    pilot = subparsers.add_parser(
        "pilot",
        help="Execute a bounded mixed-branch pilot (subtitle-hit and audio→ASR)",
        # RawDescription keeps the boundary statement's line breaks, so the
        # literal token `--scope failed` survives any terminal width (the
        # default formatter reflows and may break the word at its hyphen).
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Bounded mixed-branch probe (subtitle-hit and audio→ASR), not a corpus\n"
            "path. The stage-attempt ledger is written by the run coordinator behind\n"
            "`bili-asr run`, `bili-asr schedule` and `bili-asr campaign`: work archived\n"
            "through this entry point leaves no attempt records, so no per-stage truth\n"
            "exists for pilot work, and it is not reachable by `--scope failed`."
        ),
    )
    pilot.add_argument("--n", type=int, default=20)
    pilot.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    pilot.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    pilot.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help=_MAX_AUDIO_GB_HELP,
    )
    pilot.add_argument(
        "--keep-audio", action=argparse.BooleanOptionalAction, default=None,
        help=_KEEP_AUDIO_HELP,
    )
    pilot.add_argument(
        "--max-duration-min", type=int, default=45,
        help="Exclude rows longer than this many minutes from selection (0 = unlimited)",
    )
    pilot.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
    )

    probe = subparsers.add_parser(
        "probe-subs",
        help="List the subtitle tracks the selected archive parts expose (read-only)",
    )
    probe.add_argument(
        "--bvid", default=None,
        help="Bvid, or bvid:pN for one part, already in the archive database",
    )
    probe.add_argument(
        "--limit-parts", type=int, default=None,
        help="Probe the first N parts of the pending enumeration",
    )
    probe.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    probe.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )

    harvest = subparsers.add_parser(
        "harvest-subs",
        help="Acquire subtitles for the selected archive parts as transcripts",
    )
    harvest.add_argument(
        "--bvid", default=None,
        help="Bvid, or bvid:pN for one part, already in the archive database "
             "(parts that already have a transcript included)",
    )
    harvest.add_argument(
        "--limit-parts", type=int, default=None,
        help="Bound the run to N parts (required unless a single bvid:pN is named)",
    )
    harvest.add_argument(
        "--language", default=None,
        help="Comma-separated upstream language codes, first match wins "
             "(default: the zh family, then en, CC before AI)",
    )
    harvest.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    harvest.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )

    dl = subparsers.add_parser(
        "download-audio",
        help="Download audio for videos without subtitles (needs_audio)",
    )
    dl.add_argument(
        "--missing-subs", action="store_true",
        help="Process every manifest entry with status needs_audio",
    )
    dl.add_argument(
        "--bvid", default=None,
        help="Restrict to a bvid or work_id (bvid:pN); STOP if unresolved "
             "or multi-part without an explicit page",
    )
    dl.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    dl.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    dl.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )
    dl.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N videos (smoke runs)",
    )

    derive = subparsers.add_parser(
        "derive-manifest",
        help="Append manifest rows for the audio queue: parts with no transcript",
        description=(
            "Derive the audio queue from archive.db: every stored part that holds "
            "no transcript and is not gone is appended to the manifest as a "
            "needs_audio row, so the ASR/audio chain has work to select. The "
            "database is opened read-only and the manifest is only appended to; "
            "a row the chain already holds is left alone. An empty queue is "
            "success."
        ),
    )
    derive.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    publish = subparsers.add_parser(
        "publish-transcripts",
        help="Publish the stored transcripts as archive bundles (fetches nothing)",
        description=(
            "Publish the stored transcripts as complete archive bundles: the four "
            "artifact families plus the bundle marker under the configured artifact "
            "root, and one archived manifest row per publication. The range is every "
            "stored part that holds a transcript, whatever its processing status — a "
            "gone part still holds local text — and --bvid narrows it to one video or "
            "one part. The command fetches nothing: no network, no download, no ASR. "
            "It reads archive.db read-only and writes the products below the "
            "artifact root, one row to the manifest and the archive-writer lock "
            "under <archive_root>/coordinator/, and a complete published bundle is "
            "never replaced, so a store that later gains a newer transcript version "
            "leaves the published product as it is. A row that already carries an "
            "earlier manifest state is outside what the archive's readers currently "
            "agree on."
        ),
    )
    publish.add_argument(
        "--bvid", default=None,
        help="Bvid, or bvid:pN for one part, already in the archive database",
    )
    publish.add_argument(
        "--limit-parts", type=int, default=None,
        help="Bound the run to the first N stored parts holding a transcript",
    )
    publish.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    publish.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)

    run_cmd = subparsers.add_parser(
        "run",
        help="Coordinate manifest rows through stages (complements pilot)",
    )
    run_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
             "(comma- or space-separated)",
    )
    run_cmd.add_argument(
        "--offline",
        action="store_true",
        help="Never call harvest/download (deterministic local stages only)",
    )
    run_cmd.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N rows (bounded batches)",
    )
    run_cmd.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help=_MAX_AUDIO_GB_HELP,
    )
    run_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    run_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    run_cmd.add_argument(
        "--keep-audio", action=argparse.BooleanOptionalAction, default=None,
        help=_KEEP_AUDIO_HELP,
    )
    run_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )

    schedule_cmd = subparsers.add_parser(
        "schedule",
        help="Process a bounded sequential batch of the visible corpus",
    )
    schedule_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
             "(comma- or space-separated)",
    )
    schedule_cmd.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Process at most N matching rows (required explicit bound)",
    )
    schedule_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume only a matching risk-interrupted scheduler sidecar",
    )
    schedule_cmd.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help=_MAX_AUDIO_GB_HELP_SCHEDULE,
    )
    schedule_cmd.add_argument(
        "--allow-long-live",
        action="store_true",
        help=(
            "Opt in to multi-hour rows under the configured --max-audio-gb "
            "(cannot be 0). Default pending/failed selection keeps the "
            "45-minute short-video policy"
        ),
    )
    schedule_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    schedule_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    schedule_cmd.add_argument(
        "--keep-audio", action=argparse.BooleanOptionalAction, default=None,
        help=_KEEP_AUDIO_HELP,
    )
    schedule_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )

    campaign_cmd = subparsers.add_parser(
        "campaign",
        help="Run a bounded campaign batch with aggregate checkpoint evidence",
    )
    campaign_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
        "(comma- or space-separated)",
    )
    campaign_cmd.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Process at most N matching rows (required explicit bound)",
    )
    campaign_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume only a matching risk-interrupted scheduler sidecar",
    )
    campaign_cmd.add_argument(
        "--offline",
        action="store_true",
        help="Never call harvest/download (deterministic local stages only)",
    )
    campaign_cmd.add_argument(
        "--max-audio-gb",
        type=float,
        default=10.0,
        help=_MAX_AUDIO_GB_HELP,
    )
    campaign_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    campaign_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    campaign_cmd.add_argument(
        "--keep-audio", action=argparse.BooleanOptionalAction, default=None,
        help=_KEEP_AUDIO_HELP,
    )
    campaign_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )

    search_cmd = subparsers.add_parser(
        "search",
        help="Search indexed completed transcripts using SQLite FTS5",
    )
    search_cmd.add_argument("query", help="Search query string")
    search_cmd.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N results (default: all)",
    )
    search_cmd.add_argument(
        "--rebuild", action="store_true",
        help="Force rebuilding the search index from the manifest",
    )
    search_cmd.add_argument(
        "--status", action="append", default=None,
        help="Filter by manifest status (repeatable or comma-separated)",
    )
    search_cmd.add_argument(
        "--source", action="append", default=None,
        help="Filter by source (e.g. subtitle, asr)",
    )
    search_cmd.add_argument(
        "--language", action="append", default=None,
        help="Filter by language (e.g. ai-zh, zh-CN)",
    )
    search_cmd.add_argument(
        "--scope", default=None,
        help="pending | failed | one or more work_id/bvid selectors",
    )
    search_cmd.add_argument(
        "--work-id", action="append", default=None,
        help="Filter by exact work_id or bvid (repeatable or comma-separated)",
    )
    search_cmd.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (text or json)",
    )
    search_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    search_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)

    coverage_cmd = subparsers.add_parser(
        "coverage", help="Print deterministic read-only coverage telemetry"
    )
    coverage_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    coverage_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    coverage_cmd.add_argument("--scope", default=None)
    coverage_cmd.add_argument("--format", choices=["json", "csv"], default="json")
    coverage_cmd.add_argument(
        "--trusted-local", action="store_true",
        help="Trust an operator-owned local archive root for unbounded inspection",
    )
    coverage_cmd.add_argument(
        "--quality",
        action="store_true",
        help="Include deterministic artifact quality validation signals",
    )
    coverage_cmd.add_argument(
        "--reference",
        default=None,
        help=(
            "Second transcript of the same audio (SRT/TXT/JSON); needs --quality "
            "and exactly one selected row. .srt/.txt are read as plain text; a "
            "cue-less or unparsable .json is refused"
        ),
    )

    coverage_cmd.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Restore the pre-cutover exit behavior: any finding, either "
            "class, exits non-zero"
        ),
    )

    integrity_cmd = subparsers.add_parser(
        "verify", help="Verify archive integrity without modifying files"
    )
    integrity_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    integrity_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    integrity_cmd.add_argument("--scope", default=None)
    integrity_cmd.add_argument(
        "--trusted-local", action="store_true",
        help="Trust an operator-owned local archive root for unbounded inspection",
    )
    integrity_cmd.add_argument("--format", choices=["json", "text"], default="json")
    integrity_cmd.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Restore the pre-cutover exit behavior: any finding, either "
            "class, exits non-zero"
        ),
    )

    recover_cmd = subparsers.add_parser(
        "recover", help="Explicitly audit named integrity defects (no requeue execution)"
    )
    recover_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    recover_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    recover_cmd.add_argument("--work-id", action="append", default=None,
                             help="Exact work_id selector (repeatable; required for bounded recovery)")
    recover_cmd.add_argument("--defect-code", action="append", default=None,
                             help="Defect class selector (repeatable; bounded to reported defects)")
    recover_cmd.add_argument(
        "--limit", type=int, default=100,
        help="Limit must be positive; values above the maximum are capped at 100",
    )

    evaluate_concurrency = subparsers.add_parser(
        "evaluate-concurrency",
        help="Evaluate evidence only; runtime remains sequential with no daemon",
    )
    evaluate_concurrency.add_argument(
        "--evidence", required=True, help="Path to the JSON evidence mapping"
    )
    evaluate_concurrency.add_argument(
        "--thresholds", required=True, help="Path to the explicit JSON threshold mapping"
    )

    export_cmd = subparsers.add_parser(
        "export",
        help="Export manifest metadata to JSON or CSV format",
    )
    export_cmd.add_argument(
        "--format",
        choices=["json", "csv"],
        required=True,
        help="Export format (json or csv)",
    )
    export_cmd.add_argument(
        "--out",
        default=None,
        help="Output file path (default: stdout)",
    )
    export_cmd.add_argument(
        "--status",
        action="append",
        default=None,
        help="Filter by manifest status (repeatable or comma-separated)",
    )
    export_cmd.add_argument(
        "--with-text",
        action="store_true",
        help="Include transcript text body in output",
    )
    export_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    export_cmd.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)

    # The GPU/ROCm environment self-check.  This subcommand is the CLI form the
    # README and spec 01 D1.2 already document — it had no implementation, so
    # every published invocation answered "invalid choice: 'check-asr-env'"
    # while the check itself lived only in `scripts/check_asr_env.py`.
    #
    # It takes no arguments and writes nothing: it inspects the host (device
    # node, loader path, torch build, HSA runtime, a device probe) and exits
    # `0` iff all five stages hold, `1` when any fails, `2` for a usage error —
    # the same contract the script implements.
    subparsers.add_parser(
        "check-asr-env",
        help="Verify this host can run local ASR (GPU/ROCm recipe self-check)",
    )

    return parser


def _record_api_error(
    store, key: str, code: int | str, starting_status: str | None = None
) -> None:
    """Attach a numeric API code to an existing work_id / compatible row."""
    del starting_status  # never invent a new bare-bvid processable row
    if not isinstance(code, int):
        return
    entry = store.get(key) or store.get_compatible(key)
    if entry is None:
        return
    updated = dict(entry)
    updated["last_api_error_code"] = code
    store.upsert(updated)


def _todo_for_bvid(store, selector: str, entries: dict):
    from .page_identity import parse_work_id

    try:
        parse_work_id(selector)
    except ValueError:
        bvid = selector
    else:
        entry = entries.get(selector) or store.get(selector)
        if entry is None or _is_excluded(entry):
            return []
        return [(selector, entry)]

    matching = [
        (key, e) for key, e in entries.items()
        if e.get("bvid") == bvid and not _is_excluded(e)
    ]
    if len(matching) > 1:
        return None
    if len(matching) == 1:
        return matching
    compat = store.get_compatible(bvid)
    if compat is not None and _is_excluded(compat):
        return []
    return []


def _identity_from_entry(entry: dict, key: str):
    from .page_identity import identity_from_entry

    return identity_from_entry(entry, key)


def _is_excluded(entry: dict | None) -> bool:
    if not entry:
        return False
    return bool(
        entry.get("unresolved") or entry.get("excluded_from_page_processing")
    )


_MAX_DISPLAYED_PENDING_PARTS = 20


def _metadata_database_path(archive_root: str) -> str:
    """Return the fresh SQLite database path below an archive root."""
    return os.path.join(archive_root, ARCHIVE_DATABASE_NAME)


def _archive_database_exists(command: str, archive_root: str) -> bool:
    """Require an existing ``archive.db`` below the root; print the shipped line when absent.

    Neither subtitle command creates the database and read commands never do, so
    the file is checked before any connection is opened — the shipped read
    command's missing-database answer (fixed line, exit 1, nothing created).
    """
    if os.path.isfile(_metadata_database_path(archive_root)):
        return True
    print(
        f"{command}: no archive database at {archive_root}; "
        "run fetch-meta to create it",
        file=sys.stderr,
    )
    return False


def _open_read_connection(command: str, archive_root: str):
    """Open the fresh database for a read command; None after printing why not.

    Read commands never create the database: a missing file is the documented
    configuration error (exit 1), and an unreadable file is reported bounded
    without raw SQLite text.  The caller owns the returned connection and closes
    it when the command finishes.
    """
    from bili_asr.storage import open_database

    if not _archive_database_exists(command, archive_root):
        return None
    try:
        return open_database(archive_root)
    except (OSError, sqlite3.Error) as exc:
        print(
            f"{command}: unreadable archive database at {archive_root} "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        return None


def _open_read_only_connection(command: str, archive_root: str):
    """Open an existing archive database strictly read-only; None after printing why not.

    ``probe-subs`` promises that it writes nothing at all, so it deliberately
    does not go through :func:`~bili_asr.storage.open_database`: that path
    executes both idempotent schema scripts and commits them even when nothing
    changes.  This connection is opened through a ``mode=ro`` URI instead, so the
    promise is structural rather than conventional — a write attempted through it
    fails inside SQLite instead of reaching the file.  The database existence
    guard is the shipped one, and an unreadable file is reported bounded exactly
    as the write-capable read path reports it.  The first read is taken here,
    inside that bounded handler, because a file that is not a database at all
    only fails on the first statement, not on connect.
    """
    if not _archive_database_exists(command, archive_root):
        return None
    connection = None
    try:
        resolved = Path(_metadata_database_path(archive_root)).resolve()
        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
        # The repository contract requires both of these of any connection it is
        # handed, and neither touches the database file: ``sqlite3.Row`` is a
        # client-side row factory and ``foreign_keys`` is a per-connection
        # setting.
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA schema_version").fetchone()
    except (OSError, sqlite3.Error) as exc:
        if connection is not None:
            connection.close()
        print(
            f"{command}: unreadable archive database at {archive_root} "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        return None
    return connection


def _open_read_repository(
    command: str, archive_root: str
) -> "MetadataRepository | None":
    """Open the fresh database for a read command and wrap it in the repository.

    ``None`` means :func:`_open_read_connection` already reported the reason.
    """
    from bili_asr.storage import MetadataRepository

    connection = _open_read_connection(command, archive_root)
    if connection is None:
        return None
    return MetadataRepository(connection)


def _subtitle_schema_rebuild_line(command: str, archive_root: str) -> str:
    """Compose the fixed rebuild line for a pre-iteration archive database.

    ``SchemaContractError`` carries the reason and the procedure only — it holds
    a connection, never an archive root — so the command prefix and the actual
    database path are composed here, and the printed line carries both.
    """
    return (
        f"{command}: archive database predates the transcript schema; "
        f"rebuild it (delete {_metadata_database_path(archive_root)} "
        "and re-run fetch-meta)"
    )


def _open_subtitle_connection(
    command: str, archive_root: str, *, read_only: bool = False
):
    """Open the archive database for one subtitle command; None after printing.

    Neither subtitle command creates ``archive.db`` (``open_database`` does), so
    the file is checked before opening through the shipped read-command guard,
    and the transcript-schema capability is required immediately after opening:
    a database that predates the contract is answered with the fixed rebuild line
    and exit 1 instead of a raw SQLite error from the first transcript query.

    ``read_only`` is set by ``probe-subs``, whose "writes nothing at all" promise
    is then structural: its connection is the ``mode=ro`` one from
    :func:`_open_read_only_connection`, never the schema-initializing
    ``open_database`` the write commands and the other read commands share.

    The capability guard reads the database, so a damaged-but-openable file
    (intact header, corrupted page) fails here rather than when the connection
    is opened.  That failure is storage-side — the guard only executes SQL — and
    it is bounded with the same fixed ``unreadable archive database`` line, and
    the same ``(OSError, sqlite3.Error)`` class, both open helpers use for their
    own statements.  Anything outside that class is a programming error and is
    not bounded here: this function runs before the command handlers' ``try``
    blocks, so it reaches the interpreter as an uncaught traceback and exit 1,
    never their ``unexpected error`` line.
    """
    from bili_asr.storage import SchemaContractError, require_subtitle_schema

    connection = (
        _open_read_only_connection(command, archive_root)
        if read_only
        else _open_read_connection(command, archive_root)
    )
    if connection is None:
        return None
    try:
        require_subtitle_schema(connection)
    except SchemaContractError:
        connection.close()
        print(
            _subtitle_schema_rebuild_line(command, archive_root), file=sys.stderr
        )
        return None
    except (OSError, sqlite3.Error) as exc:
        # The guard executes SQL against the file, so a malformed image surfaces
        # on its first read rather than on ``connect``: answer it exactly as
        # both open helpers answer their own statements (F-QA-001).
        connection.close()
        print(
            f"{command}: unreadable archive database at {archive_root} "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        return None
    return connection


def _subtitle_selector(value: str | None) -> tuple[str | None, int | None]:
    """Split an optional ``--bvid`` value into ``(bvid, page_index)``.

    The archive's own part vocabulary is accepted: a bare ``bvid`` selects every
    stored part of that video and ``bvid:pN`` (``page_identity.parse_work_id``)
    selects exactly that part.  A value the parser cannot read is kept verbatim
    as a bare bvid, so the database answers no row for it and the caller reports
    the documented ``unknown --bvid`` configuration error rather than a crash.
    """
    from .page_identity import parse_work_id

    if value is None:
        return None, None
    try:
        return parse_work_id(value)
    except ValueError:
        return value, None


def _selector_cannot_name_a_part(bvid: str) -> bool:
    """Report whether a ``--bvid`` value can never name a stored part.

    The archive stores ``bvid`` values through the storage contract's own
    identifier rule, which rejects a value that is empty once stripped and one
    that carries a control character (``\\x00``/``\\r``/``\\n``), so such a
    selector resolves to zero rows in every database there is.  It is therefore
    answered as the documented configuration error — the fixed
    ``unknown --bvid <value>`` line, exit 1 — decided on the argument alone and
    before the database is opened, instead of being handed to the repository,
    whose identifier validation would reject it and surface as an unexpected
    internal error.  A padded-but-addressable value is deliberately *not*
    rejected here: only a value the storage rule cannot hold is.
    """
    return not bvid.strip() or any(mark in bvid for mark in "\x00\r\n")


def _cmd_fetch_meta(args: argparse.Namespace) -> int:
    """Collect video metadata into the fresh SQLite archive database.

    Exit taxonomy (metadata-cli-contract spec): 0 successful collection
    (reached the end, the explicit --limit-pages bound, or the implicit
    DEFAULT_PAGE_LIMIT bound); 1 usage/configuration error; 2 terminal
    failure in one of two variants — a bounded gateway failure (the
    fail-fast gateway: one attempt per page, a bounded scalar code, cursor
    unchanged, resume safe) or an unexpected internal error (the fixed
    "fetch-meta: unexpected error" message with no scalar code; the cursor
    may hold the last committed page of the run and the run row may remain
    `running`, so consult status/runs before re-running).  This handler
    never reads or writes the legacy manifest/cursor/ledger sidecars.
    """
    from bili_asr.services import MetadataIngestor
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    from bili_asr.storage import MetadataRepository, open_database

    try:
        config = load_metadata_config(args)
    except MetadataConfigError as exc:
        print(f"fetch-meta: {exc}", file=sys.stderr)
        return 1

    if config.resume and not os.path.isfile(
        _metadata_database_path(config.archive_root)
    ):
        print(
            f"fetch-meta: no archive database at {config.archive_root}; "
            "--resume requires a stored cursor",
            file=sys.stderr,
        )
        return 1
    try:
        connection = open_database(config.archive_root)
    except (OSError, sqlite3.Error) as exc:
        print(
            f"fetch-meta: invalid --archive-root {config.archive_root} "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        return 1

    try:
        repository = MetadataRepository(connection)
        if config.resume and repository.read_cursor(config.mid) is None:
            print(
                f"fetch-meta: --resume requires a stored cursor; none recorded "
                f"for mid={config.mid} (drop --resume to start from page 1)",
                file=sys.stderr,
            )
            return 1
        gateway = BilibiliApiGateway(sessdata=config.sessdata)
        ingestor = MetadataIngestor(gateway, repository)
        result = ingestor.collect_user_pages(
            mid=config.mid,
            start_page=config.start_page,
            page_limit=config.page_limit,
        )
    except Exception:
        # C5: the ingestor resolves bounded gateway failures internally, so
        # anything escaping is unexpected — exit the terminal code with a
        # fixed redacted summary, never a traceback or payload text.
        print("fetch-meta: unexpected error", file=sys.stderr)
        return 2
    finally:
        connection.close()

    print(f"sessdata: {redact_sessdata(config.sessdata)}")
    print(
        f"fetch-meta: collected {result.page_count} page(s) for "
        f"mid={config.mid} (outcome={result.outcome})"
    )
    if result.outcome in {"risk_interrupted", "failed"}:
        cursor_clause = (
            f"cursor unchanged at page {result.next_cursor.next_page}"
            if result.next_cursor is not None
            else "no cursor recorded"
        )
        print(
            f"fetch-meta: metadata gateway failure ({result.error_code}); "
            f"{cursor_clause} — re-run fetch-meta to resume.",
            file=sys.stderr,
        )
        return 2
    if result.next_cursor is not None:
        print(
            f"cursor: next_page={result.next_cursor.next_page} "
            f"state={result.next_cursor.state}"
        )
    return 0


def _run_error_codes(
    repository: "MetadataRepository", run_ids: list[str]
) -> dict[str, str]:
    """Collect one bounded error code per rendered run from page evidence.

    Only the runs the listing renders are queried and each query takes at
    most one row (LIMIT 1), so the scan never grows with page history.
    """
    codes: dict[str, str] = {}
    for run_id in run_ids:
        # Composition-root exception (adjudicated): this raw SQL read stays at the CLI seam.
        row = repository.connection.execute(
            "SELECT error_code FROM ingestion_pages"
            " WHERE run_id = ? AND error_code IS NOT NULL"
            " ORDER BY page_number LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is not None:
            codes[run_id] = str(row["error_code"])
    return codes


def _format_run_line(stats: sqlite3.Row, error_code: str | None) -> str:
    """Render one run row: identity, times, outcome, counts, bounded error."""
    finished = stats["finished_at"]
    fields = [
        f"run {stats['run_id']}",
        f"mid={stats['mid']}",
        f"started={stats['started_at']}",
        f"finished={finished if finished is not None else '-'}",
        f"outcome={stats['outcome']}",
        f"pages={stats['page_count']}",
        f"videos={stats['video_count']}",
    ]
    if error_code is not None:
        fields.append(f"error={error_code}")
    return " ".join(fields)


def _resolve_sessdata(args: argparse.Namespace) -> str | None:
    """SESSDATA from --sessdata or env BILI_SESSDATA; blank forces anonymous."""
    return resolve_sessdata(args.sessdata, os.environ.get(SESSDATA_ENV_VAR))


def _cmd_probe_subs(args: argparse.Namespace) -> int:
    """List the subtitle tracks the selected parts expose, writing nothing.

    Read-only by construction: ``probe-subs`` is not an archive-writer command,
    so it takes no writer lock, creates no file below the archive root, and never
    creates a missing database.  Exit taxonomy: 0 the probe ran (zero-track parts
    included); 1 usage/configuration (neither or both selectors, a non-positive
    bound, a missing database, an unknown --bvid, the schema guard); 2 the probe
    failed on every selected part, or an unexpected internal error.  A partial
    per-part failure stays visible in the printed ``failed=`` count.
    """
    from bili_asr.services.subtitle_ingest import (
        SubtitleIngestor,
        SubtitleSelection,
    )
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    from bili_asr.storage import TranscriptRepository

    if (args.bvid is None) == (args.limit_parts is None):
        print(
            "probe-subs: exactly one of --bvid / --limit-parts is required",
            file=sys.stderr,
        )
        return 1
    if args.limit_parts is not None and args.limit_parts < 1:
        print(
            "probe-subs: --limit-parts must be a positive integer",
            file=sys.stderr,
        )
        return 1
    bvid, page_index = _subtitle_selector(args.bvid)
    if bvid is not None and _selector_cannot_name_a_part(bvid):
        # A blank or control-character selector names no part in any database, so
        # it is the documented configuration error and is decided before the
        # database is opened.
        print(f"probe-subs: unknown --bvid {args.bvid}", file=sys.stderr)
        return 1
    sessdata = _resolve_sessdata(args)
    connection = _open_subtitle_connection(
        "probe-subs", args.archive_root, read_only=True
    )
    if connection is None:
        return 1
    try:
        repository = TranscriptRepository(connection)
        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
            # A selector that resolves to no stored part is configuration, not an
            # empty result, so the probe never reports a part-less run as a
            # completed read.
            print(f"probe-subs: unknown --bvid {args.bvid}", file=sys.stderr)
            return 1
        ingestor = SubtitleIngestor(
            BilibiliApiGateway(sessdata=sessdata),
            repository,
            credential_present=sessdata is not None,
        )
        result = ingestor.probe(
            SubtitleSelection(
                bvid=bvid, page_index=page_index, limit=args.limit_parts
            )
        )
    except Exception:
        # Expected gateway failures are resolved inside the service, so anything
        # escaping is unexpected: the bounded terminal code, never a traceback.
        print("probe-subs: unexpected error", file=sys.stderr)
        return 2
    finally:
        connection.close()

    print(f"sessdata: {redact_sessdata(sessdata)}")
    for part in result.parts:
        if part.error_code is not None:
            print(f"probe {part.work_id} failed {part.error_code}")
            continue
        print(f"probe {part.work_id} tracks={len(part.tracks)}")
        if not part.tracks:
            print("  (no subtitles visible)")
            continue
        for track in part.tracks:
            kind = "ai" if track.is_ai else "cc"
            print(f"  track {track.language} {kind} {track.label}")
    with_tracks = sum(1 for part in result.parts if part.tracks)
    failed = sum(1 for part in result.parts if part.error_code is not None)
    print(
        f"probe-subs: probed={len(result.parts)} with_tracks={with_tracks} "
        f"without_tracks={len(result.parts) - with_tracks - failed} "
        f"failed={failed}"
    )
    if failed and failed == len(result.parts):
        return 2
    return 0


def _cmd_harvest_subs(args: argparse.Namespace) -> int:
    """Acquire the selected parts into normalized transcripts with run evidence.

    Exit taxonomy: 0 the bounded run completed — including a run whose every
    attempted part had no visible caption, and a selection that resolved to no
    part; 1 usage/configuration (a missing database, an unknown --bvid, a missing
    bound, an empty --language entry, the schema guard); 2 the run failed on every
    attempted part, or an unexpected internal error.  Partial per-part failure
    stays visible in the printed counts rather than in the exit code.
    """
    from bili_asr.services.subtitle_ingest import (
        SubtitleIngestor,
        SubtitleSelection,
    )
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    from bili_asr.storage import TranscriptRepository

    languages: tuple[str, ...] = ()
    if args.language is not None:
        languages = tuple(entry.strip() for entry in args.language.split(","))
        if any(not entry for entry in languages):
            print(
                "harvest-subs: --language entries must not be empty",
                file=sys.stderr,
            )
            return 1
    if args.limit_parts is not None and args.limit_parts < 1:
        print(
            "harvest-subs: --limit-parts must be a positive integer",
            file=sys.stderr,
        )
        return 1
    bvid, page_index = _subtitle_selector(args.bvid)
    if bvid is not None and _selector_cannot_name_a_part(bvid):
        # Same configuration error as an unknown bvid, and decided on the
        # argument alone: a selector the archive cannot store can never resolve to
        # a part, so no bound would make it selectable.
        print(f"harvest-subs: unknown --bvid {args.bvid}", file=sys.stderr)
        return 1
    if args.limit_parts is None and page_index is None:
        # No unbounded runs: only a single named part is bounded by construction.
        print(
            "harvest-subs: --limit-parts is required unless a single bvid:pN "
            "part is selected",
            file=sys.stderr,
        )
        return 1
    sessdata = _resolve_sessdata(args)
    connection = _open_subtitle_connection("harvest-subs", args.archive_root)
    if connection is None:
        return 1
    try:
        repository = TranscriptRepository(connection)
        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
            # Decided before the run is opened: an unknown selector is
            # configuration and must not leave an empty run row behind.
            print(f"harvest-subs: unknown --bvid {args.bvid}", file=sys.stderr)
            return 1
        ingestor = SubtitleIngestor(
            BilibiliApiGateway(sessdata=sessdata),
            repository,
            credential_present=sessdata is not None,
        )
        result = ingestor.harvest(
            SubtitleSelection(
                bvid=bvid,
                page_index=page_index,
                limit=args.limit_parts,
                languages=languages,
            )
        )
    except Exception:
        # The service finishes an interrupted run as failed before anything
        # escapes, so this is the bounded terminal code with no traceback.
        print("harvest-subs: unexpected error", file=sys.stderr)
        return 2
    finally:
        connection.close()

    print(f"sessdata: {redact_sessdata(sessdata)}")
    for outcome in result.parts:
        if outcome.outcome == "failed":
            print(f"harvest {outcome.work_id} failed {outcome.error_code}")
        elif outcome.outcome == "no-subtitle":
            print(f"harvest {outcome.work_id} no-subtitle")
        else:
            print(
                f"harvest {outcome.work_id} {outcome.outcome} "
                f"{outcome.source_kind} {outcome.language} v{outcome.version}"
            )
    print(
        f"harvest-subs: run_id={result.run_id} attempted={result.attempted} "
        f"stored={result.stored} unchanged={result.unchanged} "
        f"no-subtitle={result.no_subtitle} failed={result.failed} "
        f"remaining_without_transcript={result.remaining_without_transcript}"
    )
    if result.attempted and result.failed == result.attempted:
        return 2
    return 0


def _cmd_derive_manifest(args: argparse.Namespace) -> int:
    """Append the manifest rows the stored audio queue needs.

    The queue is the store's own work relation — every part that holds no
    transcript and is not ``gone`` (``v_pending_subtitles``, read through
    ``list_pending_subtitle_parts``) — and never the metadata backlog ``status``
    prints as ``pending:``.  ``cli.py`` composes the layers here, as the
    cross-layer rule requires: the database is opened read-only through the
    subtitle guard, the derivation is a pure service call, and the write is
    ``ManifestStore.upsert`` per appended row under the manifest's own lock.

    Exit taxonomy: 0 the derivation completed, including an empty queue (a
    missing database, an unreadable one, the schema-rebuild guard, a held
    archive-writer lock and a usage error are all answered by their shipped
    paths with 1); no path of this command produces 2.  A write that fails
    part-way through the append loop is reported rather than left to a
    traceback: the summary is still printed, with ``derived`` counting the rows
    that did reach the manifest, one ``derive-manifest: append failed after <k>
    row(s)`` line on stderr names that count, and the exit code stays 1.  The
    rows already appended are complete lines the chain reads and a re-run
    answers ``already_derived`` for them, so the run stays resumable and only
    its report used to be missing.
    """
    from .manifest import ManifestStore
    from .page_identity import parse_work_id
    from .services.manifest_derivation import (
        QUEUE_STATUS,
        SKIP_ALREADY_DERIVED,
        SKIP_CHAIN_OWNED,
        SKIP_IDENTITY_MISMATCH,
        derive_rows,
    )
    from .storage import TranscriptRepository

    store = ManifestStore(root=args.archive_root)
    connection = _open_subtitle_connection(
        "derive-manifest", args.archive_root, read_only=True
    )
    if connection is None:
        return 1
    try:
        repository = TranscriptRepository(connection)
        queue = [dict(row) for row in repository.list_pending_subtitle_parts()]
        outcome = derive_rows(
            queue,
            repository.read_video_pubdates([part["bvid"] for part in queue]),
            store.load(),
        )
    finally:
        connection.close()

    def _print_summary(derived: int) -> None:
        # §8's one summary line, printed on the success path and on the append's
        # failure path alike: the counts an operator reads never depend on how
        # far the run got, and ``derived`` is the number of rows that reached
        # the manifest rather than the number the derivation proposed.
        print(
            f"derive-manifest: queue={len(queue)} derived={derived} "
            f"{SKIP_ALREADY_DERIVED}={len(outcome.already_derived)} "
            f"{SKIP_CHAIN_OWNED}={len(outcome.chain_owned)} "
            f"{SKIP_IDENTITY_MISMATCH}={len(outcome.identity_mismatch)}"
        )

    written = 0
    for row in outcome.appended:
        try:
            # The bridge never emits a bare-bvid key, so the page-qualified form
            # is re-validated at the write rather than trusted from the
            # derivation: ``upsert`` checks the same pair, but it also accepts a
            # bare row when the bvid already has a legacy one, which is a state
            # this command promises never to create.  Unreachable defence for
            # any store the shipped writers produce — the view and
            # ``format_work_id`` agree on every bvid the gateway admits — kept
            # so the promise is enforced where it is made, not assumed.
            stored_bvid, _page = parse_work_id(str(row["work_id"]))
            if stored_bvid != row["bvid"]:
                raise ValueError(
                    f"derived work_id {row['work_id']!r} does not match "
                    f"bvid {row['bvid']!r}"
                )
            store.upsert(row)
        except Exception as exc:
            # The guard spans the write and the validation in front of it, and
            # nothing else: a per-row write can fail (the manifest lock, the
            # append's own write/fsync, the record validation) and until this
            # guard existed the summary went down with the traceback on exactly
            # the run where the operator needs to know how much of the queue is
            # already durable.  The per-row ``print`` below stays outside it —
            # an output failure is not an append failure, and the line is only
            # true for the rows already written.
            print(
                f"derive-manifest: append failed after {written} row(s): "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            _print_summary(written)
            return 1
        written += 1
        print(f"{row['work_id']}: {QUEUE_STATUS} (duration_s={row['duration_s']})")
    for work_id in outcome.chain_owned:
        print(f"skip {work_id} {SKIP_CHAIN_OWNED}")
    for work_id in outcome.identity_mismatch:
        print(f"skip {work_id} {SKIP_IDENTITY_MISMATCH}")
    _print_summary(len(outcome.appended))
    return 0


#: The four product keys a publication records and a recorded row declares
#: (contract §5.1).  Kept as the command's own tuple rather than reached for
#: through ``archive``'s private one: the row's four keys and the writer's four
#: writes are the same vocabulary, and the writer's return is what supplies the
#: values (``archive.py:488``, root-relative — exactly the recorded form).
_PRODUCT_PATH_KEYS = ("srt_path", "txt_path", "md_path", "raw_path")


def _declared_bundle_paths(row: Any) -> dict[str, str] | None:
    """Return the four product paths a recorded row declares, or ``None`` (§5.4).

    ``None`` means the row declares no bundle — it is absent, it is a legacy
    ``subtitle_done`` row carrying ``srt_path`` alone (``subtitles.py:160-165``),
    or one of the four values is not a string — and such a candidate is
    published rather than skipped.  The strings are read from the row itself and
    never re-derived: the question §5.4 asks is what the manifest records, and a
    re-derivation would disagree with it the moment a title or a pubdate moved.
    """

    if not row:
        return None
    declared = {key: row.get(key) for key in _PRODUCT_PATH_KEYS}
    if not all(isinstance(value, str) for value in declared.values()):
        return None
    return declared


def _cmd_publish_transcripts(args: argparse.Namespace) -> int:
    """Publish the stored transcripts as complete archive bundles (contract §7).

    ``cli.py`` composes the layers here, as the cross-layer rule requires: the
    store is read through ``TranscriptRepository`` on the read-only connection,
    the winner and the manifest row are the pure service's, the publication is
    the shipped archive writer, and the record is ``ManifestStore``.  Nothing is
    written back into ``archive.db``.

    Per candidate, in the read's locked order: a row that already declares a
    **complete** bundle at the write base is ``already_published`` and nothing is
    written for it — no file, no marker, no row (§5.4) — which is what makes a
    second run byte-identical.  Otherwise the winner's stored body is read,
    mapped to the writer's segment shape, published under the write base,
    re-asked of the same completeness reader ``verify`` calls, and only then
    recorded (§5.1's fifteen keys merged into the row the part already has,
    ``status: archived``).  A publication the reader does not confirm is
    ``failed`` and records no row.  When the writer unwound — it returned, raised
    or was interrupted by ``Ctrl-C`` — its staging directory is gone and the next
    pass republishes the bundle: that is the state a run killed between its write
    and its ``upsert`` leaves behind.  A termination that does not unwind the
    writer — ``SIGKILL``, ``SIGTERM`` at its default disposition, the OOM killer —
    leaves the fixed-name ``transcripts/.archive-bundle-stage`` in place instead,
    and the writer then refuses every later publication into that root — each
    candidate reporting ``failed (OSError)`` — until an operator removes it.

    Every line's ``<reason>`` is a bounded redacted scalar (§7): this command's
    own two literals ``empty_transcript`` / ``bundle_incomplete`` where it
    decides, and ``coordinator._safe_error_code`` otherwise — never an exception
    message, a path or a URL.

    Exit taxonomy: ``0`` when every candidate is published or already published,
    including a run with no candidate at all; ``1`` for a usage/configuration
    error (a refused artifact root, an unknown ``--bvid``, a non-positive
    ``--limit-parts``, a missing or unreadable database, the transcript-schema
    guard, a held archive-writer lock) and for a candidate that could not be
    published.  No path of this command produces ``2``: it opens no socket, and
    ``_UsageErrorArgumentParser`` maps argparse's own usage exit to ``1``.
    """
    from . import archive
    from .coordinator import _safe_error_code
    from .manifest import ManifestStore
    from .services.manifest_derivation import duration_s_from_ms
    from .services.transcript_projection import (
        ordered_candidates,
        projection_row,
        writer_segments,
    )
    from .storage import TranscriptRepository

    if args.limit_parts is not None and args.limit_parts < 1:
        print(
            "publish-transcripts: --limit-parts must be a positive integer",
            file=sys.stderr,
        )
        return 1
    bvid, page_index = _subtitle_selector(args.bvid)
    if bvid is not None and _selector_cannot_name_a_part(bvid):
        # The same configuration error as an unknown bvid, decided on the
        # argument alone and before the database is opened: a selector the
        # storage identifier rule cannot hold names no part in any database.
        print(f"publish-transcripts: unknown --bvid {args.bvid}", file=sys.stderr)
        return 1
    connection = _open_subtitle_connection(
        "publish-transcripts", args.archive_root, read_only=True
    )
    if connection is None:
        return 1
    candidates: tuple[Any, ...] = ()
    published = already_published = failed = 0
    try:
        repository = TranscriptRepository(connection)
        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
            # "Unknown" ranges over the store's part relation, not over the
            # candidate set: a stored part that holds no transcript is known and
            # yields zero candidates, exit 0 (§2.2).
            print(f"publish-transcripts: unknown --bvid {args.bvid}", file=sys.stderr)
            return 1
        candidates = ordered_candidates(
            (dict(row) for row in repository.list_stored_transcripts(bvid, page_index)),
            args.limit_parts,
        )
        store = ManifestStore(root=args.archive_root)
        recorded = store.load()
        write_base = args.artifact_roots.write_base
        for candidate in candidates:
            work_id = candidate.work_id
            part = candidate.part
            kind = candidate.transcript["source_kind"]
            language = candidate.transcript["language"]
            version = candidate.transcript["version"]
            declared = _declared_bundle_paths(recorded.get(work_id))
            if declared is not None and archive.archive_bundle_complete(
                write_base, declared
            ):
                # Probed at the write base, deliberately (§5.4): the promise is
                # that the products are under the configured root, and asking
                # every read base would answer `already_published` for a bundle
                # the configured root does not hold.
                already_published += 1
                print(f"{work_id}: already_published")
                continue

            reason: str | None = None
            written: dict[str, str] = {}
            try:
                record = repository.read_transcript(
                    part["video_part_id"], kind, language, version
                )
            except Exception as exc:
                # One candidate's read failing is that candidate's failure: the
                # rest of the run still publishes and the summary still counts.
                reason = str(_safe_error_code(exc))
            if reason is None and record is None:
                # Unreachable for the identity this run's own read just answered
                # — a stored version is never deleted and no shipped writer
                # deletes one — kept bounded rather than assumed, so a store that
                # moved under the run reports a failed candidate instead of
                # raising out of the loop.
                reason = str(_safe_error_code(LookupError()))
            if reason is None:
                try:
                    segments = writer_segments(record.segments)
                except ValueError:
                    # §7's own literal.  A stored transcript is never empty
                    # (`storage/models.py:382-383`), so this names a shape the
                    # store cannot deliver rather than a live path.
                    reason = "empty_transcript"
            if reason is None:
                # The writer's entry: the part's own facts plus §3.4's two
                # renderings, which are the values `projection_row` records one
                # layer down — the frontmatter is built from this entry, so the
                # date and the seconds have to be resolved before the write.
                entry = {
                    "bvid": part["bvid"],
                    "work_id": work_id,
                    "page_index": part["page_index"],
                    "cid": part["cid"],
                    "title": part["part_title"],
                    "duration_s": duration_s_from_ms(part["duration_ms"]),
                    "pubdate_str": time.strftime(
                        "%Y-%m-%d", time.gmtime(part["pubdate"])
                    ),
                }
                try:
                    written = archive.write_archive(
                        write_base, entry, segments, source=kind
                    )
                    if not archive.archive_bundle_complete(write_base, written):
                        reason = "bundle_incomplete"
                    else:
                        # Merged into the effective row, the way the chain's own
                        # ``archived`` transition merges (``coordinator.py:520-527``
                        # reads the current entry, updates it and upserts it): the
                        # projection's own keys win, and every key the fifteen do
                        # not restate — ``audio_path``, ``artifact_paths`` — is
                        # carried over, so the row keeps naming what it named.
                        merged = {
                            **(recorded.get(work_id) or {}),
                            **projection_row(part, candidate.transcript, written),
                        }
                        store.upsert(merged)
                except Exception as exc:
                    reason = str(_safe_error_code(exc))
            if reason is not None:
                failed += 1
                print(f"{work_id}: failed ({reason})")
                continue
            published += 1
            print(
                f"{work_id}: published (source={kind} lang={language} "
                f"version={version} cues={len(segments)}) {written['md_path']}"
            )
    finally:
        connection.close()
    print(
        f"publish-transcripts: candidates={len(candidates)} published={published} "
        f"already_published={already_published} failed={failed}"
    )
    return 1 if failed else 0


def _cmd_download_audio(args: argparse.Namespace) -> int:
    from . import audio, bili_client
    from .manifest import ManifestStore

    if not args.missing_subs and not args.bvid:
        print("download-audio: select targets with --missing-subs "
              "and/or --bvid", file=sys.stderr)
        return 1

    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    if args.bvid:
        selected = _todo_for_bvid(store, args.bvid, entries)
        if selected is None:
            print(f"{args.bvid}: multi-part video needs an explicit page",
                  file=sys.stderr)
            return 1
        todo = selected
        if not todo:
            print(
                f"{args.bvid}: unresolved; not assigned to a page",
                file=sys.stderr,
            )
            return 1
    else:
        todo = [
            (key, e) for key, e in entries.items()
            if e.get("status") == "needs_audio" and not _is_excluded(e)
        ]
    if args.limit is not None:
        todo = todo[: args.limit]
    if not todo:
        print("download-audio: no needs_audio entries in the manifest")
        return 0

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    from .page_identity import artifact_stem
    from .subtitles import resolve_page_identity

    ok = failed = 0
    risk_interrupted = False
    # The products' base, resolved once (contract §4).  A write resolves on `write_base`
    # alone — never on which `audio/` directory happens to exist.
    write_base = args.artifact_roots.write_base
    for key, entry in todo:
        target = _identity_from_entry(entry, key)
        label = str(key)
        try:
            from .page_identity import PageIdentity

            if isinstance(target, PageIdentity):
                stem = artifact_stem(target)
                out_path = os.path.join(write_base, "audio", f"{stem}.m4a")
            elif isinstance(target, str):
                target = resolve_page_identity(client, target)
                label = target.work_id
                stem = artifact_stem(target)
                out_path = os.path.join(
                    write_base, "audio", f"{stem}.m4a"
                )
            else:
                raise TypeError("unsupported download target")
            label = target.work_id
            final = audio.download_audio(
                client, target, out_path, store=store,
                artifact_roots=args.artifact_roots,
            )
            from .path_policy import confined_audio_path
            try:
                returned_relative = os.path.relpath(
                    os.fspath(final), os.fspath(write_base)
                )
            except (OSError, ValueError, TypeError):
                returned_relative = ""
            confined = confined_audio_path(
                write_base, returned_relative, require_exists=True
            )
            if confined is None:
                raise ValueError("invalid audio path")
            final = os.path.relpath(confined, os.fspath(write_base))
        except bili_client.AmbiguousPageError:
            failed += 1
            print(f"{label}: multi-part video needs an explicit page",
                  file=sys.stderr)
            continue
        except audio.NoAudioStreamError:
            failed += 1
            print(f"{label}: no audio stream available", file=sys.stderr)
            continue
        except bili_client.RiskBudgetExhausted as exc:
            failed += 1
            print(f"{label}: risk-control ceiling (last {exc.last_code}); "
                  f"stopping — re-run to resume.", file=sys.stderr)
            risk_interrupted = True
            break
        except bili_client.StreamDownloadError:
            failed += 1
            print(f"{label}: audio stream failed; continuing.", file=sys.stderr)
            continue
        except bili_client.APIResponseError as exc:
            failed += 1
            _record_api_error(store, key, exc.code)
            print(f"{label}: API response error (code {exc.code}); "
                  f"continuing.", file=sys.stderr)
            continue
        except bili_client.GoneResponse as exc:
            failed += 1
            e = dict(store.get(key) or store.get_compatible(key) or {})
            if e.get("work_id"):
                e["status"] = "gone"
                store.upsert(e)
            print(f"{label}: terminal API response (code {exc.code}); "
                  f"marked gone.", file=sys.stderr)
            continue
        except ValueError as exc:
            failed += 1
            msg = str(exc)
            if "missing cid" in msg or "unresolved" in msg:
                print(f"{label}: {msg}", file=sys.stderr)
            else:
                print(f"{label}: unexpected error", file=sys.stderr)
            continue
        except Exception:
            failed += 1
            print(f"{label}: unexpected error", file=sys.stderr)
            continue
        ok += 1
        print(f"{label}: audio downloaded -> audio_ok ({final})")
        if key != todo[-1][0]:
            time.sleep(3.0)

    print(f"download-audio: {ok} audio_ok"
          + (f", {failed} failed" if failed else ""))
    if risk_interrupted:
        return 2
    return 1 if failed else 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Report metadata state from the fresh SQLite database only."""
    repository = _open_read_repository("status", args.archive_root)
    if repository is None:
        return 1
    try:
        connection = repository.connection
        counts = connection.execute(
            "SELECT (SELECT COUNT(*) FROM bilibili_users) AS users,"
            " (SELECT COUNT(*) FROM videos) AS videos,"
            " (SELECT COUNT(*) FROM video_parts) AS parts"
        ).fetchone()
        print(f"users: {counts['users']}")
        print(f"videos: {counts['videos']}")
        print(f"parts: {counts['parts']}")
        processing = connection.execute(
            "SELECT processing_status, COUNT(*) AS count FROM video_parts"
            " GROUP BY processing_status ORDER BY processing_status"
        ).fetchall()
        if processing:
            summary = ", ".join(
                f"{row['processing_status']}={row['count']}" for row in processing
            )
            print(f"processing: {summary}")
        pending = repository.list_pending_parts()
        print(f"pending: {len(pending)}")
        for row in pending[:_MAX_DISPLAYED_PENDING_PARTS]:
            print(f"  {row['work_id']}")
        hidden = len(pending) - _MAX_DISPLAYED_PENDING_PARTS
        if hidden > 0:
            print(f"  + {hidden} more pending part(s)")
        # The cursor row is reported exactly as stored: a failed or
        # risk-interrupted run leaves it untouched, so this line never implies
        # the cursor advanced past a failed page (C3).
        for user_row in connection.execute(
            "SELECT mid FROM bilibili_users ORDER BY mid"
        ):
            cursor = repository.read_cursor(int(user_row["mid"]))
            if cursor is not None:
                print(
                    f"cursor: mid={cursor.mid} next_page={cursor.next_page} "
                    f"state={cursor.state}"
                )
        return 0
    finally:
        repository.connection.close()


#: Coverage-side backlog statuses (exit-code contract §2): the row's own status
#: says the chain has not finished with it yet — normal operations, not damage.
#: Same set the integrity reader uses for `retryable_incomplete`
#: (`integrity.py` `if status in {...}: defects.add(RETRYABLE_INCOMPLETE)`).
_BACKLOG_STATUSES = frozenset(
    {"pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"}
)

#: The one validity reason that means "the artifact is not there yet" rather
#: than "the artifact is there and broken".  A backlog row is an in-flight
#: status whose findings are exactly this reason — `empty`/`malformed`/… are
#: damage even on an in-flight row (contract §2: malformed verdicts belong to
#: the defect class, never to backlog).
_BACKLOG_REASONS = frozenset({"artifact_missing"})


def _cmd_coverage_quality(args: argparse.Namespace) -> int:
    import csv
    import io
    from pathlib import Path
    from .quality import (
        QualityAnalyzer,
        REASON_CODES,
        ReferenceAgreement,
        ReferenceUnavailable,
    )
    from .coverage_report import _select_scope, _diagnostic_rows
    from .sidecar_projection import (
        ReaderPolicy,
        project_attempt_records,
        ORDINARY_HISTORY_DIAGNOSTICS,
        project_manifest_records,
    )

    root = Path(args.archive_root).resolve()
    diagnostics: set[tuple[str, str]] = set()
    policy = (
        ReaderPolicy(mode="trusted_archive")
        if getattr(args, "trusted_local", False)
        else None
    )
    manifest, manifest_state, manifest_diagnostics = project_manifest_records(
        root / "manifest" / "manifest.jsonl", policy=policy
    )
    diagnostics.update(
        (
            "sidecar_record_limit" if code.endswith("row_limit_exceeded") else
            "sidecar_byte_limit" if code.endswith("byte_limit_exceeded") else code,
            "manifest",
        )
        for code in manifest_diagnostics - ORDINARY_HISTORY_DIAGNOSTICS
    )
    attempts, _attempts_state, attempt_diagnostics = project_attempt_records(
        root / "coordinator" / "attempts.jsonl", policy=policy
    )
    diagnostics.update(
        (
            "sidecar_record_limit" if code.endswith("row_limit_exceeded") else
            "sidecar_byte_limit" if code.endswith("byte_limit_exceeded") else
            "sidecar_malformed" if code == "truncated_attempts_line" else code,
            "attempt",
        )
        for code in attempt_diagnostics
    )
    selected, scope_state = _select_scope(manifest, attempts, args.scope)
    if scope_state == "unavailable":
        diagnostics.add(("unknown_scope", "scope"))

    # One reference compares against one transcript, so it is only meaningful
    # when the selection resolves to exactly one row.  Both the usage shape and
    # the comparison itself are reported as diagnostics, never as tracebacks.
    reference_path = getattr(args, "reference", None)
    if reference_path is not None:
        if len(selected) != 1:
            print(
                "coverage: --reference needs exactly one selected row "
                f"(got {len(selected)})",
                file=sys.stderr,
            )
            return 1
        reference_path = Path(reference_path)
        if not reference_path.is_file():
            print("coverage: reference unreadable", file=sys.stderr)
            return 1

    denominator_available = (
        manifest_state == "available" and scope_state == "available"
    )
    rows: list[dict[str, object]] = []
    reason_counts: dict[str, int] = {code: 0 for code in REASON_CODES}
    total_cues = 0
    valid_work_items = 0
    has_defects = False
    has_defect_rows = False
    agreement: ReferenceAgreement | None = None
    # Where each row's doubtful cues are, keyed by work_id: a value the frozen
    # CSV columns cannot carry, so it is held here for the stderr pass below.
    low_confidence_by_work_id: dict[str, tuple[float, ...]] = {}

    analyzer = QualityAnalyzer()
    for work_id, entry in sorted(selected.items()):
        try:
            result = analyzer.analyze(
                entry, root, reference_path, artifact_roots=args.artifact_roots
            )
        except ReferenceUnavailable as exc:
            print(f"coverage: {exc.reason}", file=sys.stderr)
            return 1
        row_dict: dict[str, object] = {
            "work_id": work_id,
            "source": result.source,
            "language": result.language,
            "status": result.status,
            "cue_count": result.cue_count,
            "artifact_count": result.artifact_count,
            # The projection: defect codes first, then the advisory content
            # codes, so a reader sees one reason list per row.  Only
            # ``result.reasons`` feeds validity and the exit status below.
            "reasons": [*result.reasons, *result.content_reasons],
            "diagnostics": list(result.diagnostics),
        }
        if result.low_confidence_at:
            low_confidence_by_work_id[work_id] = result.low_confidence_at
        if result.reference is not None:
            agreement = result.reference
        rows.append(row_dict)
        for r in row_dict["reasons"]:
            reason_counts[r] = reason_counts.get(r, 0) + 1
        total_cues += result.cue_count
        if not result.reasons and not result.diagnostics:
            valid_work_items += 1
        else:
            # Any finding, either class — the `--strict` total and the
            # pre-cutover gate (contract §2).
            has_defects = True
            # Backlog (contract §2): an in-flight row whose only problem is
            # that its artifact does not exist yet.  A row whose artifact is
            # present but unreadable, or a terminal row missing its artifact,
            # is damage and must not hide behind the row's status.
            if not (
                str(result.status) in _BACKLOG_STATUSES
                and not result.diagnostics
                and set(result.reasons) <= _BACKLOG_REASONS
            ):
                has_defect_rows = True

    diagnostic_rows = _diagnostic_rows(diagnostics)
    summary = {
        "total_work_items": len(rows) if denominator_available else 0,
        "valid_work_items": valid_work_items if denominator_available else 0,
        "total_cues": total_cues if denominator_available else 0,
        **reason_counts,
    }

    quality_data = {
        "schema_version": "coverage-quality-v1",
        "scope": args.scope,
        "denominator": {
            "unit": "work_items",
            "count": len(rows) if denominator_available else None,
            "state": "available" if denominator_available else "unavailable",
            "source": "manifest_snapshot",
        },
        "summary": summary,
        "rows": rows,
        "diagnostics": diagnostic_rows,
    }
    if agreement is not None:
        # The reference's basename and the two compared lengths only: the
        # operator's path, a URL, or a credential never enters the report.
        quality_data["reference"] = {
            "work_id": rows[0]["work_id"],
            "reference": agreement.reference,
            "agreement": agreement.agreement,
            "floor": agreement.floor,
            "compared_chars": {
                "transcript": agreement.compared_chars[0],
                "reference": agreement.compared_chars[1],
            },
        }

    if args.format == "json":
        sys.stdout.write(
            json.dumps(
                quality_data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        sys.stdout.write("\n")
    else:
        columns = (
            "schema_version",
            "scope",
            "denominator_unit",
            "denominator_count",
            "denominator_state",
            "denominator_source",
            "work_id",
            "source",
            "language",
            "status",
            "cue_count",
            "artifact_count",
            "reasons",
            "diagnostics",
        )
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        csv_rows = rows or [
            {
                "work_id": "",
                "source": "",
                "language": "",
                "status": "",
                "cue_count": "",
                "artifact_count": "",
                "reasons": [],
                "diagnostics": [],
            }
        ]
        denom = quality_data["denominator"]
        for r in csv_rows:
            writer.writerow(
                {
                    "schema_version": quality_data["schema_version"],
                    "scope": quality_data["scope"] or "",
                    "denominator_unit": denom["unit"],
                    "denominator_count": (
                        denom["count"] if denom["count"] is not None else ""
                    ),
                    "denominator_state": denom["state"],
                    "denominator_source": denom["source"],
                    "work_id": r.get("work_id", ""),
                    "source": r.get("source") or "",
                    "language": r.get("language") or "",
                    "status": r.get("status") or "",
                    "cue_count": r.get("cue_count", ""),
                    "artifact_count": r.get("artifact_count", ""),
                    "reasons": ";".join(r.get("reasons", [])),
                    "diagnostics": ";".join(r.get("diagnostics", [])),
                }
            )
        sys.stdout.write(output.getvalue())
        # The frozen CSV columns carry the reason names, so the values a reason
        # stands for go to stderr — the same channel the reference ratio uses.
        # `low_confidence` shipped as a bare code with no location, which left
        # the operator reading `raw.json` by hand to find the doubtful passage
        # (residual R1 of 20260912-quality-signal-merge).  One line per row that
        # has any, so a long run's stderr states *where* the doubt is.
        for r in rows:
            low_at = low_confidence_by_work_id.get(str(r.get("work_id")), ())
            if low_at:
                print(
                    f"coverage: {r.get('work_id')} low-confidence at "
                    + ", ".join(f"{value}s" for value in low_at),
                    file=sys.stderr,
                )
        if agreement is not None:
            # CSV keeps its frozen columns, so the ratio goes to stderr.
            print(
                f"coverage: reference agreement {agreement.agreement:.4f} "
                f"against {agreement.reference} "
                f"({agreement.compared_chars[0]} vs "
                f"{agreement.compared_chars[1]} chars, floor {agreement.floor})",
                file=sys.stderr,
            )

    if getattr(args, "strict", False):
        # Pre-cutover gate (contract §2): any finding of either class.
        return 1 if (diagnostic_rows or has_defects) else 0
    # Default gate (contract §2): defect-class rows and diagnostics only.
    return 1 if (diagnostic_rows or has_defect_rows) else 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    from .coverage_report import CoverageReport
    try:
        if getattr(args, "quality", False):
            return _cmd_coverage_quality(args)
        if getattr(args, "reference", None) is not None:
            # The reference is a quality input; without --quality there is no
            # report to carry it, so say so instead of ignoring the argument.
            print("coverage: --reference requires --quality", file=sys.stderr)
            return 1
        from .sidecar_projection import ReaderPolicy
        policy = ReaderPolicy(mode="trusted_archive") if getattr(args, "trusted_local", False) else None
        report = CoverageReport.build(
            args.archive_root, scope=args.scope, policy=policy,
            artifact_roots=args.artifact_roots,
        )
        sys.stdout.write(report.to_json() if args.format == "json" else report.to_csv())
        if args.format == "json":
            sys.stdout.write("\n")
        return 1 if report.data["diagnostics"] else 0
    except Exception:
        print("coverage: diagnostic coverage_report_unavailable", file=sys.stderr)
        return 1


def _cmd_runs(args: argparse.Namespace) -> int:
    """List ingestion runs newest-first from the fresh SQLite database.

    Non-terminal ``running`` rows are rendered too: abnormal termination
    can leave a stale run behind and hiding it would hide real state (C2).
    Ordering is deterministic: ``started_at`` descending, with same-second
    runs tie-broken by ``run_id`` descending.
    """
    repository = _open_read_repository("runs", args.archive_root)
    if repository is None:
        return 1
    try:
        if args.limit is not None and args.limit < 1:
            print("runs: --limit must be a positive integer", file=sys.stderr)
            return 1
        stats_rows = repository.run_stats()
        if not stats_rows:
            print("runs: empty")
            return 0
        # Newest first; two runs sharing the second-resolution started_at
        # order deterministically on the opaque run_id (run_id descending).
        ordered = sorted(
            stats_rows,
            key=lambda row: (row["started_at"], row["run_id"]),
            reverse=True,
        )
        selected = ordered if args.limit is None else ordered[: args.limit]
        error_codes = _run_error_codes(
            repository, [str(row["run_id"]) for row in selected]
        )
        for row in selected:
            print(_format_run_line(row, error_codes.get(str(row["run_id"]))))
        return 0
    finally:
        repository.connection.close()


_PILOT_PROCESSABLE = frozenset(
    {"meta_ok", "subtitle_done", "needs_audio", "audio_ok"}
)
_PILOT_SKIP_HARVEST = frozenset(
    {"subtitle_done", "needs_audio", "audio_ok", "archived"}
)


def _pilot_row_key(entry: dict[str, object]) -> str:
    return str(entry.get("work_id") or entry.get("bvid") or "")


def _pilot_duration_key(entry: dict[str, object]):
    return (entry.get("duration_s") or 0, str(entry.get("bvid") or ""), _pilot_row_key(entry))


def _pilot_processable(entries: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return [
        e for e in entries.values()
        if e.get("status") in _PILOT_PROCESSABLE and not _is_excluded(e)
    ]


def _pilot_select(
    entries: dict[str, dict[str, object]], n: int,
    max_duration_min: int = 0,
) -> list[dict[str, object]]:
    """Select a small mixed pilot while guaranteeing both branches when possible."""
    if n < 1:
        return []
    from .audio_budget import max_duration_exceeded

    processable = [
        e for e in _pilot_processable(entries)
        if not max_duration_exceeded(e, max_duration_min)
    ]
    subtitle = [e for e in processable if e.get("status") == "subtitle_done"]
    audio = [e for e in processable if e.get("status") in {"needs_audio", "audio_ok"}]
    subtitle.sort(key=_pilot_duration_key)
    audio.sort(key=_pilot_duration_key)
    selected: list[dict[str, object]] = []
    for candidate in (subtitle[:1] + audio[:1]):
        if candidate and candidate not in selected:
            selected.append(candidate)
    remaining = sorted(
        (e for e in processable if e not in selected),
        key=_pilot_duration_key,
    )
    selected.extend(remaining[: max(0, n - len(selected))])
    return selected[:n]


def _expand_selected_pages(
    entries: dict[str, dict[str, object]],
    selected: list[dict[str, object]],
    max_duration_min: int = 0,
) -> list[dict[str, object]]:
    """Include duration-eligible pagelist siblings for selected bvids."""
    if not selected:
        return selected
    from .audio_budget import max_duration_exceeded

    chosen = {_pilot_row_key(e) for e in selected}
    bvids = {str(e.get("bvid") or "") for e in selected}
    extras = [
        e for e in _pilot_processable(entries)
        if str(e.get("bvid") or "") in bvids
        and _pilot_row_key(e) not in chosen
        and not max_duration_exceeded(e, max_duration_min)
    ]
    extras.sort(key=_pilot_duration_key)
    return selected + extras


def _subtitle_segments(
    roots: ArtifactRoots, entry: dict[str, object]
) -> tuple[list[dict[str, object]], object] | None:
    """Read one row's harvested caption document over the ordered bases (contract §5).

    The document is a **read**, and the recorded path is root-relative (D7), so the
    first base that holds it wins: a row harvested before the artifact root was
    configured keeps resolving at the archive root.
    """
    import json
    from .archive import archive_stem

    stem = archive_stem(entry)
    relative = os.path.join("subtitles", "raw", f"{stem}.json")
    for base in roots.read_bases():
        raw_path = os.path.join(os.fspath(base), relative)
        if not os.path.isfile(raw_path):
            continue
        with open(raw_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        segments = [{"start": item.get("from", 0), "end": item.get("to", 0), "text": item.get("content", "")}
                    for item in doc.get("body", [])]
        return segments, doc
    return None


class _AsrItemCount:
    """The printed reuse line's ASR-item denominator (D2.5).

    A one-field box, not an ``int``, because the in-process loops count the
    row at two different call depths: ``_cmd_asr`` counts inline, while
    ``pilot`` counts inside ``_pilot_archive_asr``, which has to report the
    increment to its caller.  Every path increments at the same event — the
    row's ASR stage produced a transcript — which is what ``RunCoordinator``
    counts at its own ``asr: ok`` attempt, so ``asr``/``pilot`` and ``run``
    state the same denominator for the same input.
    """

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = 0


def _print_in_process_constructions(
    command: str, runner: object, asr_items: int
) -> None:
    """State one in-process ASR loop's constructions, once, on stderr (D2.6).

    ``RunCoordinator.run_batch`` prints this for the coordinator path; ``asr``
    and ``pilot`` never enter it, so they print through the same shared string
    for their own command label.  ``runner`` is ``None`` when the selection
    needed no model.

    The guard is "nothing was paid", not "no ASR items" — the same rule the
    coordinator applies: a loop that built the model and then failed every
    transcription still states ``… for 0 asr item(s)``, while a subtitle-only
    selection (no construction, no transcript) prints nothing at all.  Stderr
    keeps every command's stdout contract intact; when fd 2 is closed
    ``sys.stderr`` is ``None`` and ``print(..., file=None)`` would fall back to
    stdout, so a missing stream prints nothing rather than breaking it.
    """
    from .coordinator import model_constructions_line

    constructions = (
        int(getattr(runner, "model_constructions", 0)) if runner is not None else 0
    )
    if asr_items <= 0 and constructions <= 0:
        return
    if sys.stderr is None:
        return
    print(
        model_constructions_line(command, constructions, asr_items),
        file=sys.stderr,
    )


def _cmd_asr(args: argparse.Namespace) -> int:
    from . import archive, asr
    from .manifest import ManifestStore

    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    if args.bvid:
        selected = _todo_for_bvid(store, args.bvid, entries)
        if selected is None:
            print(f"{args.bvid}: multi-part video needs an explicit page",
                  file=sys.stderr)
            return 1
        if not selected:
            print(
                f"{args.bvid}: unresolved; not assigned to a page",
                file=sys.stderr,
            )
            return 1
        todo = [e for _key, e in selected]
    elif args.pending:
        todo = [
            e for e in entries.values()
            if e.get("status") in {"subtitle_done", "audio_ok"}
            and not _is_excluded(e)
        ]
    else:
        print("asr: select targets with --pending or --bvid", file=sys.stderr)
        return 1
    if args.limit is not None:
        todo = todo[:args.limit]
    ok = failed = 0
    # One invocation is one run scope (D2.2): every audio item of this
    # selection shares one lazily-built runner, and the selection states what
    # it paid.  ``asr.transcribe``'s one-shot contract is untouched (D2.4).
    runner = None
    # The declared identity is validated once, here, before the row loop and
    # outside its per-row ``try`` (QC3-F1).  A mis-declared producer used to
    # surface as N identical ``archive failed`` lines with the reason reaching
    # no stream at all; now the ``ValueError``'s own message is printed once and
    # the command exits 1, leaving the per-row path below as the backstop.
    # ``default_config()`` only reads the environment knobs, so this builds no
    # model.  A selection that never reaches the ASR path is skipped: a
    # subtitle-only run does not read these knobs and must not be refused
    # because one of them is malformed.
    #
    # Both ``ValueError`` branches are redaction-safe by construction (verified
    # by ``test_the_asr_entry_failure_message_never_carries_a_path``): the
    # unsafe-declaration branch names only the variable, and the contradiction
    # branch can only fire once *both* values have passed the identifier scan.
    config = None
    if any(entry.get("status") != "subtitle_done" for entry in todo):
        try:
            config = asr.default_config()
        except ValueError as exc:
            print(f"asr: {exc}", file=sys.stderr)
            return 1
    # ``asr_count`` is the printed line's denominator and counts the same event
    # the coordinator counts (D2.5): a row whose ASR stage produced a
    # transcript.  It increments at the transcribe boundary below, never after
    # the archive tail, so a row that fails downstream still counts and the
    # two paths cannot disagree on the same input.
    asr_count = _AsrItemCount()
    try:
        for entry in todo:
            key = str(entry.get("work_id") or entry["bvid"])
            label = key
            source = "subtitle"
            raw = None
            provenance = None
            status = entry.get("status")
            subtitle_data = (
                _subtitle_segments(args.artifact_roots, entry)
                if status == "subtitle_done"
                else None
            )
            try:
                if status == "subtitle_done" and subtitle_data is None:
                    failed += 1
                    print(f"{label}: skipped (missing_subtitle_raw)", file=sys.stderr)
                    continue
                if subtitle_data is not None:
                    segments, raw = subtitle_data
                else:
                    source = "asr"
                    stem = archive.archive_stem(entry)
                    from .path_policy import confined_audio_file
                    declared = entry.get("audio_path") or os.path.join("audio", f"{stem}.m4a")
                    if runner is None:
                        runner = asr.ASRRunner(
                            config if config is not None else asr.default_config()
                        )
                    # A read of the recorded value, so both bases answer (D8): a row
                    # whose audio predates the configured root still resolves.
                    audio_base = _audio_base_holding(
                        args.artifact_roots, os.fspath(declared)
                    )
                    with confined_audio_file(audio_base, os.fspath(declared)) as safe_audio:
                        segments = runner.transcribe(safe_audio)
                    asr_count.value += 1
                    provenance = runner.provenance()
                paths = archive.write_archive(
                    args.artifact_roots.write_base, entry, segments, source=source,
                    raw=raw, asr_provenance=provenance,
                )
                if not archive.archive_bundle_complete(args.artifact_roots.write_base, paths):
                    raise ValueError("archive bundle incomplete")
                updated = dict(store.get(key) or entry)
                updated.update(paths)
                updated["status"] = "archived"
                store.upsert(updated)
                _reclaim_after_archive(
                    args.artifact_roots, updated, keep=args.keep_audio
                )
                ok += 1
                print(f"{label}: archived ({source})")
            except asr.ASRDependencyError:
                failed += 1
                print(f"{label}: ASR dependency unavailable", file=sys.stderr)
            except Exception as exc:
                failed += 1
                # The `run` path states the code (`failed (ValueError)`), and
                # this one used to print fixed text with no reason at all
                # (QC3-F1).  `_safe_error_code` never throws and never echoes a
                # payload: it reads `code`/`last_code` or the class name.
                from .coordinator import _safe_error_code

                print(
                    f"{label}: archive failed ({_safe_error_code(exc)})",
                    file=sys.stderr,
                )
    finally:
        _print_in_process_constructions("asr", runner, asr_count.value)
        if runner is not None:
            runner.release()
    print(f"asr: {ok} archived" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


def _audio_base_holding(roots: ArtifactRoots, declared: str) -> Path:
    """The first base that holds one recorded ``audio_path`` (contract §5, D8).

    A recorded value stays root-relative, so the base it is resolved against is decided
    by which one holds the file — the row's audio may predate the configured root.  A
    value no base holds is a failure of the read, reported as the guard's own
    ``OSError`` so the row's ``archive failed`` line keeps naming the same class.
    """
    from .path_policy import confined_audio_path

    for base in roots.read_bases():
        if confined_audio_path(base, declared, require_exists=True) is not None:
            return base
    raise OSError("invalid audio path")


def _audio_base_for_path(roots: ArtifactRoots, path: str | os.PathLike[str]) -> Path:
    """The first base that holds one on-disk audio path (contract §5, D6).

    ``audio.download_audio`` hands back what its own resolver found over ``read_bases()``
    when the bytes are already there, so the return may live under the **archive root**
    for a row that predates the configured root — while ``write_base`` only ever names
    where a write goes.  Same rule as :func:`_audio_base_holding`, on an absolute path
    instead of the recorded root-relative one.
    """
    from .path_policy import confined_audio_path

    target = os.fspath(path)
    for base in roots.read_bases():
        try:
            declared = os.path.relpath(target, base)
        except ValueError:  # Windows across drives
            continue
        if confined_audio_path(base, declared, require_exists=True) is not None:
            return base
    raise OSError("invalid audio path")


def _reclaim_after_archive(
    roots: ArtifactRoots, entry: dict[str, object], *, keep: bool
) -> None:
    """Best-effort audio reclaim once a row is archived (plan: audio-reclaim).

    ``keep`` is the retention policy the command boundary resolved (contract §7, D15);
    the library never reads the environment.  ``roots`` carries both bases, because "do
    not keep this row's audio" means the copy, wherever it is.
    """
    from .audio_reclaim import reclaim_audio

    try:
        reclaim_audio(
            roots.archive_root, entry, artifact_roots=roots, keep=keep
        )
    except (OSError, ValueError):
        pass  # per-item non-fatal: transcripts exist; row stays archived


def _pilot_archive_subtitle(
    store, roots: ArtifactRoots, entry: dict[str, object], *, keep: bool
) -> dict[str, object]:
    from . import archive

    base = roots.write_base
    data = _subtitle_segments(roots, entry)
    if data is None:
        raise ValueError(f"{_pilot_row_key(entry)}: subtitle raw JSON missing")
    segments, raw = data
    paths = archive.write_archive(base, entry, segments, source="subtitle", raw=raw)
    if not archive.archive_bundle_complete(base, paths):
        raise ValueError("archive bundle incomplete")
    updated = dict(entry)
    updated.update(paths)
    updated["status"] = "archived"
    store.upsert(updated)
    _reclaim_after_archive(roots, updated, keep=keep)
    return updated


def _pilot_archive_asr(
    store, client, roots: ArtifactRoots, entry: dict[str, object], target, runner=None,
    asr_count: "_AsrItemCount | None" = None, *, keep: bool,
) -> dict[str, object]:
    """Archive one pilot row over ASR.

    ``runner`` is the invocation-scoped ``ASRRunner``: the pilot's loop holds
    one for its whole selection (D2.3), so this function transcribes through
    the caller's runner and never builds a second model.  Omitting it keeps the
    single-row entry point working with its own short-lived runner.

    ``asr_count`` is the caller's ``_AsrItemCount``.  When given, the row is
    counted as soon as it produced a transcript — the same event ``run``
    counts at its ``asr: ok`` attempt (D2.5) — so a row that fails later in
    this function's archive tail keeps its place in the line's denominator.

    It is **not optional for a loop caller**: the counter is how this
    function's increment reaches the batch's printed line, and the only caller
    able to pass the loop's box is the loop itself.  ``None`` is for the
    single-row entry point, whose caller prints no line; a multi-row loop that
    leaves it at ``None`` silently under-counts, so passing it is asserted
    below rather than left to convention.
    """
    from . import archive, asr, audio
    from .page_identity import PageIdentity, artifact_stem
    from .subtitles import resolve_page_identity

    if runner is not None and asr_count is None:
        # A caller-supplied runner means "I am the loop" (D2.3): without the
        # box this row's transcript never reaches the line's denominator.
        raise TypeError("_pilot_archive_asr needs asr_count with a caller runner")

    if isinstance(target, str):
        target = resolve_page_identity(client, target)
    if not isinstance(target, PageIdentity):
        raise TypeError("unsupported download target")
    # Writes use `write_base` alone; reads walk the ordered bases (contract §4/§5).
    base = roots.write_base
    stem = artifact_stem(target)
    out_path = os.path.join(base, "audio", f"{stem}.m4a")
    existing_rel = entry.get("audio_path") if entry.get("status") == "audio_ok" else None
    existing_audio_path: str | None = None
    # The base the row's audio is read from: whichever base holds it — the recorded copy's
    # for a row written before the root was configured, the downloader's return for a row
    # that had to fetch (or re-find) it.  The ASR stage re-confines the value **there** and
    # records it back **there** (contract §5, D6/D8): measuring a legacy copy against
    # `write_base` alone yields a `..`-bearing string the audio guard refuses, so the row
    # fails instead of archiving.
    audio_base = base
    from .path_policy import confined_audio_file, confined_audio_path
    if existing_rel:
        try:
            holding = _audio_base_holding(roots, os.fspath(existing_rel))
        except OSError:
            holding = None
        if holding is not None:
            existing_audio_path_obj = confined_audio_path(
                holding, os.fspath(existing_rel), require_exists=True
            )
            if existing_audio_path_obj is not None and existing_audio_path_obj.stat().st_size > 0:
                existing_audio_path = str(existing_audio_path_obj)
                audio_base = holding
    if existing_audio_path is not None:
        audio_path = existing_audio_path
    else:
        downloaded = Path(os.fspath(audio.download_audio(
            client, target, out_path, store=store, artifact_roots=roots
        )))
        # The downloader may return a file it *found* rather than wrote — a legacy copy at
        # the archive root (D6) — so the base that holds the return is the one the value is
        # re-confined and recorded against, the same rule as the recorded branch above.
        try:
            audio_base = _audio_base_for_path(roots, downloaded)
        except OSError:
            raise ValueError("invalid audio path")
        audio_path_obj = confined_audio_path(
            audio_base, os.path.relpath(downloaded, audio_base), require_exists=True
        )
        if audio_path_obj is None or audio_path_obj.stat().st_size <= 0:
            raise ValueError("invalid audio path")
        audio_path = str(audio_path_obj)
    declared_audio = os.path.relpath(audio_path, audio_base)
    owns_runner = runner is None
    if owns_runner:
        runner = asr.ASRRunner(asr.default_config())
    try:
        with confined_audio_file(audio_base, declared_audio) as safe_audio:
            segments = runner.transcribe(safe_audio)
        if asr_count is not None:
            asr_count.value += 1
        current = dict(store.get(target.work_id) or entry)
        paths = archive.write_archive(
            base, current, segments, source="asr", asr_provenance=runner.provenance()
        )
    finally:
        if owns_runner:
            runner.release()
    if not archive.archive_bundle_complete(base, paths):
        raise ValueError("archive bundle incomplete")
    current.update(paths)
    current["status"] = "archived"
    try:
        current["audio_path"] = os.path.relpath(audio_path, audio_base)
    except ValueError:
        current["audio_path"] = audio_path
    store.upsert(current)
    _reclaim_after_archive(roots, current, keep=keep)
    return current


def _archived_branch_counts(entries: dict[str, dict[str, object]]) -> tuple[int, int]:
    subtitle_count = audio_count = 0
    for entry in entries.values():
        if entry.get("status") != "archived":
            continue
        if entry.get("audio_path"):
            audio_count += 1
        else:
            subtitle_count += 1
    return subtitle_count, audio_count


def _pilot_print_summary(
    batch_subtitle_count: int,
    batch_audio_count: int,
    coverage_subtitle_count: int,
    coverage_audio_count: int,
    failed: int,
    terminals: list[str],
) -> None:
    print(
        "pilot batch branches: "
        f"subtitle={batch_subtitle_count}, audio-asr={batch_audio_count}"
        + (f", failed={failed}" if failed else "")
    )
    print(
        "pilot coverage branches: "
        f"subtitle={coverage_subtitle_count}, audio-asr={coverage_audio_count}"
    )
    for line in terminals:
        print(f"pilot terminal: {line}")


def _cmd_pilot(args: argparse.Namespace) -> int:
    from . import asr, audio, bili_client, subtitles
    from .manifest import ManifestStore
    from .meta_cursor import MetaCursorStore
    from .run_ledger import (
        RunLedger,
        build_run_record,
        compute_coverage_summary,
        utc_now_iso,
    )

    started_at = utc_now_iso()
    ledger = RunLedger(root=args.archive_root)
    cursor_store = MetaCursorStore(root=args.archive_root)
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    last_api_error_code: int | str | None = None
    selected_work_ids: list[str] | None = None

    def _record_exit(code: int) -> int:
        try:
            cursor_snapshot = cursor_store.load()
            coverage = compute_coverage_summary(store.load())
            rec = build_run_record(
                command="pilot",
                started_at=started_at,
                finished_at=utc_now_iso(),
                exit_code=code,
                mid=None,
                work_ids=selected_work_ids,
                pages_fetched=None,
                records_fetched=None,
                records_existing=len(entries),
                last_api_error_code=last_api_error_code,
                coverage_summary=coverage,
                cursor_snapshot=cursor_snapshot,
            )
            ledger.append(rec)
        except Exception:
            pass
        return code

    selected = _expand_selected_pages(
        entries,
        _pilot_select(entries, args.n, args.max_duration_min),
        args.max_duration_min,
    )
    selected_work_ids = [_pilot_row_key(e) for e in selected] if selected else None
    print(
        f"pilot: selected {len(selected)} rows "
        f"(--n {args.n}; includes pagelist siblings)"
    )
    for entry in selected:
        print(
            f"{_pilot_row_key(entry)}: {entry.get('status')} "
            f"({entry.get('duration_s', 0)}s)"
        )
    leftover = [e for e in entries.values() if e.get("status") != "archived"]
    if not selected:
        if leftover:
            print("pilot: no processable rows in the manifest", file=sys.stderr)
            return _record_exit(1)
        if any(e.get("status") == "archived" for e in entries.values()):
            print("pilot: skip — all selected work already archived")
            return _record_exit(0)
        print("pilot: no processable rows in the manifest", file=sys.stderr)
        return _record_exit(1)

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    coverage_subtitle_count, coverage_audio_count = _archived_branch_counts(entries)
    batch_subtitle_count = batch_audio_count = 0
    failed = 0
    terminals: list[str] = []
    # One pilot invocation is one run scope (D2.3): the selection shares one
    # runner, and the `finally` below states what it paid and releases it on
    # every exit path — including the early returns inside the loop.
    runner = None
    # Same denominator rule as ``_cmd_asr`` (D2.5): the row is counted when
    # its ASR stage produced a transcript, inside ``_pilot_archive_asr``.
    asr_count = _AsrItemCount()

    try:
        for index, entry in enumerate(selected):
            key = _pilot_row_key(entry)
            target = _identity_from_entry(entry, key)
            label = key
            status = entry.get("status")
            if status == "archived":
                continue
            try:
                if status not in _PILOT_SKIP_HARVEST:
                    status = subtitles.harvest_subtitle(
                        client, target, store, args.archive_root,
                        artifact_roots=args.artifact_roots,
                    )
                current = dict(store.get(key) or store.get_compatible(key) or entry)
                label = str(current.get("work_id") or key)
                if status == "subtitle_done":
                    _pilot_archive_subtitle(
                        store, args.artifact_roots, current, keep=args.keep_audio
                    )
                    batch_subtitle_count += 1
                    coverage_subtitle_count += 1
                    terminals.append(f"{label}: archived (subtitle)")
                    print(f"{label}: archived (subtitle)")
                elif status in {"needs_audio", "audio_ok"}:
                    from .audio_budget import (
                        SKIP_REASON,
                        audio_cap_bytes,
                        would_exceed_budget,
                    )

                    max_bytes = audio_cap_bytes(args.max_audio_gb)
                    current_row = dict(store.get(key) or current)
                    if (
                        status == "needs_audio"
                        and would_exceed_budget(
                            args.artifact_roots.write_base, current_row, max_bytes
                        )
                    ):
                        failed += 1
                        # Q1's ruling: the cap keeps its fail-closed semantics, and the
                        # line that reports it names the flag that lifts it.  With audio
                        # retained, `audio/` only grows, so `0` is the operator's lever.
                        print(
                            f"{label}: skipped ({SKIP_REASON})"
                            f"{_AUDIO_BUDGET_SKIP_HINT}",
                            file=sys.stderr,
                        )
                        continue
                    if runner is None:
                        runner = asr.ASRRunner(asr.default_config())
                    _pilot_archive_asr(
                        store, client, args.artifact_roots, current, target, runner,
                        asr_count, keep=args.keep_audio,
                    )
                    batch_audio_count += 1
                    coverage_audio_count += 1
                    terminals.append(f"{label}: archived (asr)")
                    print(f"{label}: archived (asr)")
                else:
                    raise ValueError(f"unexpected status {status!r}")
            except asr.ASRDependencyError as exc:
                print(str(exc), file=sys.stderr)
                print(
                    f"{label}: ASR dependency unavailable; row not archived",
                    file=sys.stderr,
                )
                _pilot_print_summary(
                    batch_subtitle_count,
                    batch_audio_count,
                    coverage_subtitle_count,
                    coverage_audio_count,
                    failed,
                    terminals,
                )
                return _record_exit(1)
            except bili_client.AmbiguousPageError:
                failed += 1
                print(f"{label}: multi-part video needs an explicit page",
                      file=sys.stderr)
            except bili_client.RiskBudgetExhausted as exc:
                failed += 1
                last_api_error_code = exc.last_code
                print(
                    f"{label}: risk-control ceiling (last code {exc.last_code}); "
                    f"stopping — re-run to resume.",
                    file=sys.stderr,
                )
                _pilot_print_summary(
                    batch_subtitle_count,
                    batch_audio_count,
                    coverage_subtitle_count,
                    coverage_audio_count,
                    failed,
                    terminals,
                )
                return _record_exit(2)
            except bili_client.APIResponseError as exc:
                failed += 1
                last_api_error_code = exc.code
                _record_api_error(store, key, exc.code)
                print(
                    f"{label}: API response error (code {exc.code}); continuing.",
                    file=sys.stderr,
                )
            except bili_client.GoneResponse as exc:
                failed += 1
                last_api_error_code = exc.code
                gone = dict(store.get(key) or store.get_compatible(key) or {})
                if gone.get("work_id"):
                    gone["status"] = "gone"
                    store.upsert(gone)
                print(
                    f"{label}: terminal API response (code {exc.code}); marked gone.",
                    file=sys.stderr,
                )
            except audio.NoAudioStreamError:
                failed += 1
                print(f"{label}: no audio stream available", file=sys.stderr)
            except bili_client.StreamDownloadError:
                failed += 1
                print(f"{label}: audio stream failed; continuing.", file=sys.stderr)
            except ValueError as exc:
                failed += 1
                msg = str(exc)
                if (
                    "missing cid" in msg
                    or "unresolved" in msg
                    or "subtitle raw JSON missing" in msg
                ):
                    print(f"{label}: {msg}", file=sys.stderr)
                else:
                    print(f"{label}: {type(exc).__name__}", file=sys.stderr)
            except Exception as exc:
                failed += 1
                print(f"{label}: {type(exc).__name__}", file=sys.stderr)
            if index != len(selected) - 1:
                time.sleep(3.0)
    finally:
        _print_in_process_constructions("pilot", runner, asr_count.value)
        if runner is not None:
            runner.release()

    _pilot_print_summary(
        batch_subtitle_count,
        batch_audio_count,
        coverage_subtitle_count,
        coverage_audio_count,
        failed,
        terminals,
    )
    if coverage_subtitle_count == 0 or coverage_audio_count == 0:
        missing = []
        if coverage_subtitle_count == 0:
            missing.append("subtitle")
        if coverage_audio_count == 0:
            missing.append("audio-asr")
        print(
            "pilot: missing branch coverage: " + ", ".join(missing),
            file=sys.stderr,
        )
        return _record_exit(1)
    if failed:
        return _record_exit(1)
    return _record_exit(0)


def _run_scope_rows(store, entries: dict, scope: str):
    """Resolve --scope to processable (key, entry) rows.

    Returns (rows, error) where error is a message string when the scope
    could not be resolved at all.
    """
    from .manifest import VALID_STATUSES

    if scope == "pending":
        return (
            [
                (key, e)
                for key, e in sorted(entries.items())
                if e.get("status") in VALID_STATUSES - {"archived", "gone"}
                and not _is_excluded(e)
            ],
            None,
        )
    if scope == "failed":
        # failed scope: rows with a recorded failed stage attempt (qc1-S2:
        # definition lives next to the ledger in RunCoordinator).
        from .coordinator import RunCoordinator

        failed = RunCoordinator(store.root, store).failed_work_ids()
        rows = [
            (key, e)
            for key, e in sorted(entries.items())
            if (str(e.get("work_id") or key) in failed
                or str(e.get("bvid") or "") in failed)
            and not _is_excluded(e)
            and e.get("status") not in {"archived", "gone"}
        ]
        return rows, None

    selectors = [s for part in scope.split(",") for s in part.split() if s]
    rows: list[tuple[str, dict]] = []
    for selector in selectors:
        todo = _todo_for_bvid(store, selector, entries)
        if todo is None:
            return None, (
                f"{selector}: multi-part video needs an explicit page"
            )
        if not todo:
            return None, f"{selector}: unresolved; not assigned to a page"
        rows.extend(todo)
    if not selectors:
        return None, "empty --scope"
    return rows, None

def _cmd_campaign(args: argparse.Namespace) -> int:
    from . import bili_client
    from .audio_budget import audio_cap_bytes
    from .campaign import CampaignRunner
    from .coordinator import ArchiveBusyError

    try:
        client = None
        if not args.offline:
            client = bili_client.BiliClient(sessdata=_resolve_sessdata(args))
        runner = CampaignRunner(
            args.archive_root,
            client=client,
            offline=args.offline,
            max_audio_bytes=audio_cap_bytes(args.max_audio_gb),
            sleep=time.sleep,
            scope_rows=_run_scope_rows,
            artifact_roots=args.artifact_roots,
            # R1: the runner is the only path to the coordinator's own reclaim, so a
            # `campaign` that did not forward this would leave its documented
            # `--keep-audio/--no-keep-audio` silently inert (contract §7, D15).
            keep_audio=args.keep_audio,
        )
        summary = runner.run(args.scope, args.limit, resume=args.resume)
    except ArchiveBusyError:
        print("campaign: archive_busy", file=sys.stderr)
        return 1
    except Exception:
        # Never expose runtime payloads, credentials, URLs, or traces.
        print("campaign: invalid configuration or execution failure", file=sys.stderr)
        return 1
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
    return summary.exit_code

class _RunInterrupted(BaseException):
    """Raised by the run body's one-shot ``SIGTERM`` disposition.

    A ``BaseException`` and not an ``Exception``: the coordinator's per-stage
    ``except Exception`` handlers would otherwise swallow the interruption and
    let the batch continue past it.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    """Put back the dispositions a swap captured (empty mapping = nothing to do)."""
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _ignore_interruption_signals() -> dict[int, Any]:
    """Leave ``SIGTERM``/``SIGINT`` ignored, and report what they were.

    The pair is swapped as a unit because the ignored state has to cover the
    whole unwind after the first delivery and the record write at its end, and
    that unwind is reached through ``SIGTERM`` *or* ``SIGINT``.  ``signal.signal``
    is main-thread only, so elsewhere nothing is swapped and the empty mapping
    reads as "nothing to restore".
    """
    if threading.current_thread() is not threading.main_thread():
        return {}
    return {
        signum: signal.signal(signum, signal.SIG_IGN)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }


@contextmanager
def _interruptible_run() -> Iterator[None]:
    """Deliver the first ``SIGTERM`` to the run body as ``_RunInterrupted``.

    One-shot: the exception is raised once, and the true previous dispositions
    -- ``SIGTERM`` *and* ``SIGINT`` -- come back in this context manager's
    ``finally``, after the record write.  Delivery therefore leaves both signals
    **ignored** instead of restoring the captured disposition: the ignored
    state, not the default, is what must hold across the coordinator's unwind
    (runner release, batch-evidence stderr write), because a repeated
    ``SIGTERM`` landing there at the default disposition would kill the process
    before the write site with no record at all.  ``SIGINT`` keeps CPython's
    ``KeyboardInterrupt`` until the run body catches it, and that branch
    installs the same ignored pair before it returns, so a repeated ``Ctrl-C``
    cannot abandon the write either.  ``signal.signal`` is main-thread only, so
    elsewhere the run body keeps the dispositions the process already had.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[int, Any] = {}

    def _on_sigterm(signum: int, _frame: Any) -> None:
        # The swapped-out dispositions are deliberately dropped: the ignored
        # state, not the disposition at delivery, is what must hold until the
        # write site has run.
        _ignore_interruption_signals()
        raise _RunInterrupted(signum)

    previous[signal.SIGTERM] = signal.signal(signal.SIGTERM, _on_sigterm)
    # ``SIGINT`` keeps its handler here (CPython's ``KeyboardInterrupt``), but
    # its disposition is captured so the run block puts both back.
    previous[signal.SIGINT] = signal.getsignal(signal.SIGINT)
    try:
        yield
    finally:
        _restore_signal_handlers(previous)


@contextmanager
def _signals_ignored() -> Iterator[None]:
    """Ignore ``SIGTERM``/``SIGINT`` for the duration of the record write."""
    previous = _ignore_interruption_signals()
    try:
        yield
    finally:
        _restore_signal_handlers(previous)


def _partial_run_state(root: str, started_at: str) -> tuple[list[str], dict[str, int]]:
    """Record inputs for a run interrupted before it could summarize.

    The interruption path has no ``RunSummary``: what the run already persisted
    durably is the record's input.  ``work_ids`` are the ids the attempts
    ledger recorded at or after this run's ``started_at``, in order and deduped
    (an earlier run's attempts stay out), and the coverage summary counts the
    manifest statuses as they stand.  ``records_existing`` is *not* derived
    here: it means "records that existed before this run", so the run body
    passes the count from the manifest it loaded above the batch, exactly as
    the normal path does.
    """
    from .coordinator import AttemptLedger
    from .manifest import ManifestStore
    from .run_ledger import compute_coverage_summary

    attempts = AttemptLedger(root).load()
    work_ids = list(
        dict.fromkeys(a["work_id"] for a in attempts if a["started_at"] >= started_at)
    )
    entries = ManifestStore(root=root).load()
    return work_ids, compute_coverage_summary(entries)


def _write_run_record(
    root: str,
    started_at: str,
    exit_code: int,
    work_ids: list[str] | None,
    records_existing: int,
    coverage_summary: dict[str, int],
) -> None:
    """The run body's single ``run-ledger.jsonl`` write site.

    Every input is derived by the caller's branch before the call, so the guard
    that authorizes the write and the values it writes are bound together.
    """
    from .run_ledger import RunLedger, build_run_record, utc_now_iso

    RunLedger(root=root).append(build_run_record(
        command="run", started_at=started_at, finished_at=utc_now_iso(),
        exit_code=exit_code, mid=None, work_ids=work_ids,
        records_existing=records_existing, coverage_summary=coverage_summary))


def _cmd_run(args: argparse.Namespace) -> int:
    from . import bili_client
    from .coordinator import ArchiveBusyError, RunCoordinator, archive_writer
    from .manifest import ManifestStore
    from .run_ledger import compute_coverage_summary, utc_now_iso
    from .audio_budget import SKIP_REASON, audio_cap_bytes

    started_at = utc_now_iso()
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    if args.limit is not None and args.limit <= 0:
        print("run: --limit must be a positive integer", file=sys.stderr)
        return 1
    rows, error = _run_scope_rows(store, entries, args.scope)
    if error:
        print(f"run: {error}", file=sys.stderr)
        return 1
    if args.limit is not None:
        rows = rows[: args.limit]
    client = None
    if not args.offline:
        client = bili_client.BiliClient(sessdata=_resolve_sessdata(args))
    coord = RunCoordinator(args.archive_root, store, client=client, offline=args.offline,
                           max_audio_bytes=audio_cap_bytes(args.max_audio_gb),
                           artifact_roots=args.artifact_roots,
                           keep_audio=args.keep_audio)
    print(f"run: scope={args.scope} selected {len(rows)} row(s)" + (" [offline]" if args.offline else ""))
    for key, entry in rows:
        print(f"  {entry.get('work_id') or key}: {entry.get('status')}")
    exit_code: int | None = None
    interrupted: int | None = None
    try:
        with archive_writer(args.archive_root):
            with _interruptible_run():
                try:
                    summary = coord.run_batch(rows)
                    ok = sum(1 for r in summary.results if r.ok)
                    skipped = summary.skipped_rows
                    failed = summary.failed
                    for r in summary.results:
                        if r.ok:
                            print(f"{r.work_id}: {r.final_status}")
                    for r in failed:
                        codes = ", ".join(str(c) for c in r.failure_codes) or "unknown"
                        print(f"run: {r.work_id}: failed ({codes})", file=sys.stderr)
                    for r in skipped:
                        # Q1: a budget skip names the flag that lifts it, the same words
                        # the pilot's line prints — `run` shares this line with every
                        # other skip reason, so the clause is carried only by that one.
                        hint = (
                            _AUDIO_BUDGET_SKIP_HINT
                            if r.skip_reason == SKIP_REASON
                            else ""
                        )
                        print(
                            f"run: {r.work_id}: skipped "
                            f"({r.skip_reason or 'unknown'}){hint}"
                        )
                    exit_code = 2 if summary.risk_interrupted else (0 if summary.fully_processed else 1)
                    if summary.risk_interrupted:
                        print("run: risk-control ceiling; stopping — re-run to resume.", file=sys.stderr)
                    print(f"run: {ok} completed, {len(skipped)} skipped" +
                          (f", {len(failed)} failed" if failed else "") +
                          (", scope not fully processed" if exit_code == 1 else ""))
                    return exit_code
                except _RunInterrupted as exc:
                    interrupted = exc.signum
                    return 128 + exc.signum
                except KeyboardInterrupt:
                    # `SIGINT` never reaches `_on_sigterm`, so the guard has to
                    # go up here, before this branch unwinds: at the captured
                    # default a repeated Ctrl-C raises again inside the record
                    # write's `finally` below and abandons the write.  Symmetric
                    # with the handler, and the true dispositions come back in
                    # `_interruptible_run`'s `finally` once the write is done.
                    _ignore_interruption_signals()
                    interrupted = signal.SIGINT
                    return 128 + signal.SIGINT
                finally:
                    # The run body's single record write: a normal exit and an
                    # interruption both leave exactly one run-ledger row here.
                    # `records_existing` is the pre-batch manifest count in both
                    # cases: the run body loaded that manifest above the batch,
                    # so this field means "records that existed before this run"
                    # on every path.
                    with _signals_ignored():
                        try:
                            if interrupted is not None:
                                # No RunSummary exists on this path, so the
                                # record's counts come from what the run already
                                # persisted.
                                exit_code = 128 + interrupted
                                work_ids, coverage_summary = _partial_run_state(
                                    args.archive_root, started_at)
                            elif exit_code is not None:
                                work_ids = [r.work_id for r in summary.results] or None
                                coverage_summary = compute_coverage_summary(store.load())
                            if exit_code is not None:
                                _write_run_record(
                                    args.archive_root, started_at, exit_code, work_ids,
                                    len(entries), coverage_summary)
                        except Exception as exc:
                            # Never silent: on the interruption path this record
                            # is the only deliverable there is, and the process
                            # still exits with the interruption code.
                            print(f"run: run-ledger write failed ({type(exc).__name__})",
                                  file=sys.stderr)
    except ArchiveBusyError:
        print("run: archive_busy", file=sys.stderr)
        return 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    from . import bili_client
    from .coordinator import ArchiveBusyError, RunCoordinator, archive_writer
    from .manifest import ManifestStore
    from .meta_cursor import MetaCursorStore
    from .run_ledger import (
        RunLedger,
        build_run_record,
        compute_coverage_summary,
        format_coverage_summary,
        format_cursor_summary,
        utc_now_iso,
    )
    from .audio_budget import audio_cap_bytes, audio_dir_usage_bytes
    from .long_live import (
        apply_long_live_policy,
        campaign_plan,
        format_campaign_plan,
        is_long_live,
        refuse_disabled_audio_cap,
    )
    from .scheduler import (
        SchedulerStore,
        classify_batch_state,
        settled_processed_ids,
        terminal_resume_ids,
    )

    started_at = utc_now_iso()
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    cursor_store = MetaCursorStore(root=args.archive_root)
    sched_store = SchedulerStore(root=args.archive_root)
    if args.limit is None or args.limit <= 0:
        print("schedule: --limit must be a positive integer", file=sys.stderr)
        return 1
    if args.allow_long_live:
        cap_error = refuse_disabled_audio_cap(args.max_audio_gb)
        if cap_error:
            print(f"schedule: {cap_error}", file=sys.stderr)
            return 1
    rows, error = _run_scope_rows(store, entries, args.scope)
    if error:
        print(f"schedule: {error}", file=sys.stderr)
        return 1

    skip_ids: list[str] | None = None
    matching_resume = False
    if args.resume:
        lookup = sched_store.inspect_resume(
            args.scope, allow_long_live=args.allow_long_live
        )
        if lookup.diagnostic:
            if lookup.refuse:
                print(
                    f"schedule: --resume refused ({lookup.diagnostic})",
                    file=sys.stderr,
                )
                return 1
            print(
                f"schedule: --resume ignored ({lookup.diagnostic})",
                file=sys.stderr,
            )
        if lookup.processed_ids is not None:
            matching_resume = True
            skip_ids = terminal_resume_ids(lookup.processed_ids, entries)
            skip = set(skip_ids)
            rows = [
                (key, entry)
                for key, entry in rows
                if str(entry.get("work_id") or key) not in skip
            ]

    rows, held, policy_error = apply_long_live_policy(
        rows,
        allow_long_live=args.allow_long_live,
        explicit_scope=args.scope not in {"pending", "failed"},
    )
    if policy_error:
        print(f"schedule: {policy_error}", file=sys.stderr)
        return 1
    if matching_resume and not args.allow_long_live and not rows and held:
        print(
            "schedule: --resume refused (risk-stopped long-duration "
            "row requires --allow-long-live)",
            file=sys.stderr,
        )
        return 1

    matching = len(rows)
    truncated = matching > args.limit or held > 0
    rows = rows[: args.limit]

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    max_audio_bytes = audio_cap_bytes(args.max_audio_gb)
    coord = RunCoordinator(
        args.archive_root,
        store,
        client=client,
        offline=False,
        max_audio_bytes=max_audio_bytes,
        sleep=time.sleep,
        # `run_batch` is shared; the reuse line must name this command, not `run`.
        command="schedule",
        artifact_roots=args.artifact_roots,
        keep_audio=args.keep_audio,
    )
    print(
        f"schedule: scope={args.scope} limit={args.limit} "
        f"selected {len(rows)} row(s) ({matching} matching)"
    )
    for key, entry in rows:
        print(f"  {entry.get('work_id') or key}: {entry.get('status')}")
    if held:
        print(
            f"schedule: {held} long-duration row(s) held; "
            "re-run with --allow-long-live"
        )
    if args.allow_long_live:
        # D16: the cap, the peak and this pre-download plan all measure the configured
        # root's `audio/` — that is where new bytes land.
        write_base = args.artifact_roots.write_base
        usage_snapshot = audio_dir_usage_bytes(write_base)
        for _key, entry in rows:
            if is_long_live(entry):
                print(format_campaign_plan(
                    campaign_plan(
                        write_base,
                        entry,
                        max_audio_bytes,
                        usage_bytes=usage_snapshot,
                    )
                ))

    try:
        with archive_writer(args.archive_root):
            summary = coord.run_batch(rows)
            if args.allow_long_live:
                after = audio_dir_usage_bytes(args.artifact_roots.write_base)
                print(f"schedule: long-live peak audio/ bytes={coord.audio_peak_bytes}")
                print(f"schedule: long-live audio/ after bytes={after}")
            batch_state = classify_batch_state(
                risk_interrupted=summary.risk_interrupted,
                truncated=truncated,
            )

            previous = list(skip_ids or [])
            settled = previous + settled_processed_ids(
                summary.results, risk_interrupted=summary.risk_interrupted
            )
            processed: list[str] = []
            seen: set[str] = set()
            for work_id in settled:
                if work_id not in seen:
                    seen.add(work_id)
                    processed.append(work_id)

            last_api_error_code: int | str | None = None
            if summary.risk_interrupted and summary.results:
                codes = summary.results[-1].failure_codes
                if codes:
                    last_api_error_code = codes[-1]

            persisted = False
            try:
                sched_store.replace_atomic(
                    {
                        "scope": args.scope,
                        "limit": args.limit,
                        "state": batch_state,
                        "processed_work_ids": processed,
                        "last_api_error_code": last_api_error_code,
                        "allow_long_live": bool(args.allow_long_live),
                        "updated_at": utc_now_iso(),
                    }
                )
                persisted = True
            except Exception as exc:
                print(
                    "schedule: failed to persist scheduler.json "
                    f"({type(exc).__name__})",
                    file=sys.stderr,
                )

            ok = sum(1 for result in summary.results if result.ok)
            skipped = summary.skipped_rows
            failed = summary.failed
            for result in summary.results:
                if result.ok:
                    print(f"{result.work_id}: {result.final_status}")
            for result in failed:
                codes = ", ".join(
                    str(code) for code in result.failure_codes
                ) or "unknown"
                print(
                    f"schedule: {result.work_id}: failed ({codes})",
                    file=sys.stderr,
                )
            for result in skipped:
                print(
                    f"schedule: {result.work_id}: skipped "
                    f"({result.skip_reason or 'unknown'})"
                )

            exit_code = 0
            if summary.risk_interrupted:
                if persisted:
                    print(
                        "schedule: risk-control ceiling; stopping — "
                        "re-run with --resume.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "schedule: risk-control ceiling; scheduler.json "
                        "was not persisted.",
                        file=sys.stderr,
                    )
                exit_code = 2
            elif not summary.fully_processed:
                exit_code = 1
            if not persisted and exit_code != 2:
                exit_code = 1

            coverage = compute_coverage_summary(store.load())
            cursor_snapshot = cursor_store.load()
            if persisted:
                print(f"schedule: batch={batch_state}")
            else:
                print(f"schedule: batch={batch_state} (not persisted)")
            print(f"enumeration: {format_cursor_summary(cursor_snapshot)}")
            print(f"coverage: [{format_coverage_summary(coverage)}]")
            print(
                f"schedule: {ok} completed, {len(skipped)} skipped"
                + (f", {len(failed)} failed" if failed else "")
                + (", scope not fully processed" if exit_code == 1 else "")
            )

            ledger = RunLedger(root=args.archive_root)
            try:
                record = build_run_record(
                    command="schedule",
                    started_at=started_at,
                    finished_at=utc_now_iso(),
                    exit_code=exit_code,
                    mid=None,
                    work_ids=[result.work_id for result in summary.results] or None,
                    records_existing=len(entries),
                    last_api_error_code=last_api_error_code,
                    coverage_summary=coverage,
                    cursor_snapshot=cursor_snapshot,
                )
                ledger.append(record)
            except Exception:
                pass
            return exit_code
    except ArchiveBusyError:
        print("schedule: archive_busy", file=sys.stderr)
        return 1


def _cmd_search(args: argparse.Namespace) -> int:
    from .manifest import VALID_STATUSES
    from .search_index import FTS5UnavailableError, SearchQuery, search

    if args.limit is not None and args.limit <= 0:
        print("search: --limit must be a positive integer", file=sys.stderr)
        return 1

    status_filter = _parse_status_filter(args.status)
    if status_filter is not None:
        invalid = status_filter - VALID_STATUSES
        if invalid:
            print(
                f"search: invalid status filter: {sorted(invalid)}; "
                f"valid statuses: {sorted(VALID_STATUSES)}",
                file=sys.stderr,
            )
            return 1

    source_filter = _parse_status_filter(args.source)
    lang_filter = _parse_status_filter(args.language)
    work_id_filter = _parse_status_filter(args.work_id)

    sq = SearchQuery(
        query=args.query,
        status=status_filter,
        source=source_filter,
        language=lang_filter,
        scope=args.scope,
        work_id=work_id_filter,
        limit=args.limit,
        rebuild=args.rebuild,
    )

    try:
        results = search(
            archive_root=args.archive_root, query=sq,
            artifact_roots=args.artifact_roots,
        )
    except FTS5UnavailableError as exc:
        print(f"search: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("search: unexpected error", file=sys.stderr)
        return 1

    if not results:
        print(
            f"search: no matching transcripts found for {args.query!r}",
            file=sys.stderr,
        )
        return 1

    if getattr(args, "format", "text") == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    for res in results:
        score = float(res.get("score") or 0.0)
        print(
            f"{res['work_id']}: {res['title']} [{res['status']}] "
            f"(score: {score:.4f}, path: {res['path']})"
        )
    return 0


def _parse_status_filter(status_args: list[str] | None) -> set[str] | None:
    """Parse repeatable and/or comma-separated status filter arguments."""
    if not status_args:
        return None
    statuses: set[str] = set()
    for item in status_args:
        for s in item.split(","):
            s = s.strip()
            if s:
                statuses.add(s)
    return statuses if statuses else None


def _cmd_check_asr_env(args: argparse.Namespace) -> int:
    """Run the host self-check the README and spec 01 D1.2 name.

    The check is `scripts/check_asr_env.py`, which is deliberately **not** part
    of the installed package: it is environment surgery's own verifier, lives
    beside the recipe in the checkout, and imports nothing from ``bili_asr``.
    The published invocation therefore names the CLI — so the CLI has to find
    the script rather than reimplement the five stages here.

    Resolution order, first hit wins:

    1. ``$BILI_ASR_CHECK_SCRIPT`` — an explicit override, for a host that keeps
       the script somewhere unusual.
    2. ``scripts/check_asr_env.py`` relative to this file's package root
       (``src/bili_asr/cli.py`` → ``../../scripts/``), which is the checkout
       layout every documented example assumes.
    3. ``scripts/check_asr_env.py`` under the current working directory, i.e.
       the product directory the README tells the operator to run from.

    When none exists the command reports that and exits ``1`` — a missing
    prerequisite is stated, never simulated as a pass.  The script's own exit
    codes pass through unchanged (``0`` verified, ``1`` a failed stage, ``2``
    usage).
    """

    import importlib.util

    candidates: list[Path] = []
    override = os.environ.get("BILI_ASR_CHECK_SCRIPT")
    if override:
        candidates.append(Path(override).expanduser())
    # src/bili_asr/cli.py -> package root -> scripts/
    candidates.append(Path(__file__).resolve().parents[2] / "scripts" / "check_asr_env.py")
    candidates.append(Path.cwd() / "scripts" / "check_asr_env.py")

    for candidate in candidates:
        if candidate.is_file():
            script = candidate
            break
    else:
        print(
            "check-asr-env: no check script found; looked for "
            + ", ".join(str(path) for path in candidates)
            + " (set BILI_ASR_CHECK_SCRIPT to point at it)",
            file=sys.stderr,
        )
        return 1

    # The script carries its own argparse-free usage contract: no arguments on
    # the command line, so it is called with none.  Loaded by path and invoked
    # as a function rather than through `runpy`: the script's `main()` defaults
    # to `sys.argv[1:]`, which here still holds this subcommand's own name, so
    # the `__main__` route would answer every invocation as a usage error.
    spec = importlib.util.spec_from_file_location("_bili_asr_env_check", script)
    if spec is None or spec.loader is None:
        print(f"check-asr-env: cannot load {script}", file=sys.stderr)
        return 1
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: the script defines frozen dataclasses, and
    # `dataclasses._process_class` resolves `cls.__module__` through
    # `sys.modules`, which a bare `module_from_spec` does not populate.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        print(f"check-asr-env: cannot load {script}", file=sys.stderr)
        return 1
    check_main = getattr(module, "main", None)
    if not callable(check_main):
        print(f"check-asr-env: {script} has no main()", file=sys.stderr)
        return 1
    try:
        return int(check_main([]))
    except SystemExit as exc:  # the script's own `raise SystemExit(main())` guard
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1


def _cmd_export(args: argparse.Namespace) -> int:
    from .export import export_manifest
    from .manifest import VALID_STATUSES

    status_filter = _parse_status_filter(args.status)
    if status_filter is not None:
        invalid = status_filter - VALID_STATUSES
        if invalid:
            print(
                f"export: invalid status filter: {sorted(invalid)}; "
                f"valid statuses: {sorted(VALID_STATUSES)}",
                file=sys.stderr,
            )
            return 1

    try:
        content = export_manifest(
            archive_root=args.archive_root,
            fmt=args.format,
            out_path=args.out,
            status_filter=status_filter,
            with_text=args.with_text,
            artifact_roots=args.artifact_roots,
        )
        if not args.out or args.out == "-":
            sys.stdout.write(content + ("\n" if not content.endswith("\n") else ""))
            sys.stdout.flush()
    except Exception:
        print("export: unexpected error", file=sys.stderr)
        return 1
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from .integrity import BACKLOG_CATEGORY, DEFECT_CATEGORY, IntegrityVerifier
    from .sidecar_projection import ReaderPolicy
    policy = ReaderPolicy(mode="trusted_archive") if getattr(args, "trusted_local", False) else None
    report = IntegrityVerifier().verify(
        Path(args.archive_root), scope=args.scope, policy=policy,
        artifact_roots=args.artifact_roots,
    )
    payload = report.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"checked: {payload['checked']}")
        print(f"defects: {payload['defect_count']}")
        for defect in payload["defects"]:
            if defect["category"] != DEFECT_CATEGORY:
                continue
            print(f"{defect['work_id']}: {defect['code']}")
        print(f"backlog: {payload['backlog_count']}")
        for defect in payload["defects"]:
            if defect["category"] != BACKLOG_CATEGORY:
                continue
            print(f"{defect['work_id']}: {defect['code']}")
        for diagnostic in payload["diagnostics"]:
            print(f"diagnostic: {diagnostic}")
    if getattr(args, "strict", False):
        # Pre-cutover gate (contract §2): any finding of either class.
        return 0 if not payload["defects"] and not payload["diagnostics"] else 1
    # Default gate (contract §2): defect-class findings and diagnostics only.
    # Backlog rows are printed in their own section and never move the exit code.
    return 1 if payload["defect_count"] or payload["diagnostics"] else 0


def _cmd_recover(args: argparse.Namespace) -> int:
    from .integrity import IntegrityVerifier
    payload = IntegrityVerifier.recover(
        Path(args.archive_root), work_ids=args.work_id,
        defect_codes=args.defect_code, limit=args.limit,
        artifact_roots=args.artifact_roots,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("ok") else 1


_MAX_CONCURRENCY_INPUT_BYTES = 1_048_576


class _ConcurrencyInputError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _read_concurrency_json_object(path: str) -> dict[str, object]:
    from collections.abc import Mapping

    file_path = Path(path)
    try:
        if not file_path.exists():
            raise _ConcurrencyInputError("input_file_missing")
        if not file_path.is_file():
            raise _ConcurrencyInputError("input_file_not_regular")
        with file_path.open("rb") as input_file:
            payload = input_file.read(_MAX_CONCURRENCY_INPUT_BYTES + 1)
    except _ConcurrencyInputError:
        raise
    except OSError:
        raise _ConcurrencyInputError("input_file_unreadable") from None

    if len(payload) > _MAX_CONCURRENCY_INPUT_BYTES:
        raise _ConcurrencyInputError("input_file_oversized")
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _ConcurrencyInputError("input_invalid_utf8") from None
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError:
        raise _ConcurrencyInputError("input_malformed_json") from None
    if not isinstance(value, Mapping):
        raise _ConcurrencyInputError("input_non_object_json")
    return dict(value)


def _write_concurrency_error(error_code: str) -> None:
    payload = {
        "error_code": error_code,
        "operating_mode": "sequential-no-daemon",
    }
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )


def _cmd_evaluate_concurrency(args: argparse.Namespace) -> int:
    from .concurrency_gate import ConcurrencyGate

    try:
        evidence = _read_concurrency_json_object(args.evidence)
        thresholds = _read_concurrency_json_object(args.thresholds)
    except _ConcurrencyInputError as exc:
        _write_concurrency_error(exc.error_code)
        return 1

    try:
        result = ConcurrencyGate.evaluate(evidence, thresholds)
    except Exception:
        _write_concurrency_error("evaluation_failure")
        return 1

    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result.ok else 1


_ARCHIVE_WRITER_COMMANDS = frozenset({
    "fetch-meta",
    "recover",
    "asr",
    "pilot",
    "derive-manifest",
    "publish-transcripts",
    "harvest-subs",
    "download-audio",
    "run",
    "campaign",
    "schedule",
})


def _dispatch_command(args: argparse.Namespace) -> int:
    if args.command == "fetch-meta":
        return _cmd_fetch_meta(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "coverage":
        return _cmd_coverage(args)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "recover":
        return _cmd_recover(args)
    if args.command == "runs":
        return _cmd_runs(args)
    if args.command == "asr":
        return _cmd_asr(args)
    if args.command == "pilot":
        return _cmd_pilot(args)
    if args.command == "probe-subs":
        return _cmd_probe_subs(args)
    if args.command == "harvest-subs":
        return _cmd_harvest_subs(args)
    if args.command == "derive-manifest":
        return _cmd_derive_manifest(args)
    if args.command == "publish-transcripts":
        return _cmd_publish_transcripts(args)
    if args.command == "download-audio":
        return _cmd_download_audio(args)
    if args.command == "search":
        return _cmd_search(args)
    if args.command == "evaluate-concurrency":
        return _cmd_evaluate_concurrency(args)
    if args.command == "check-asr-env":
        return _cmd_check_asr_env(args)
    if args.command == "export":
        return _cmd_export(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "campaign":
        return _cmd_campaign(args)
    if args.command == "schedule":
        return _cmd_schedule(args)
    raise ValueError(f"command {args.command!r} is not implemented")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
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
            args.artifact_roots = roots_for(args.archive_root, flag_value=args.artifact_root)
        except ArtifactRootError as exc:
            print(f"{args.command}: {exc}", file=sys.stderr)
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
        from .coordinator import ArchiveBusyError, archive_writer

        try:
            with archive_writer(args.archive_root):
                return _dispatch_command(args)
        except ArchiveBusyError:
            print(f"{args.command}: archive_busy", file=sys.stderr)
            return 1
    return _dispatch_command(args)



if __name__ == "__main__":
    raise SystemExit(main())
