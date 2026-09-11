"""Command-line interface for bili-asr."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

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
    asr_cmd.add_argument("--limit", type=int, default=None)

    pilot = subparsers.add_parser(
        "pilot",
        help="Execute a bounded mixed-branch pilot (subtitle-hit and audio→ASR)",
    )
    pilot.add_argument("--n", type=int, default=20)
    pilot.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    pilot.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
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
    dl.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )
    dl.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N videos (smoke runs)",
    )

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
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
    )
    run_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
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
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
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
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
    )
    campaign_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
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

    coverage_cmd = subparsers.add_parser(
        "coverage", help="Print deterministic read-only coverage telemetry"
    )
    coverage_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
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

    integrity_cmd = subparsers.add_parser(
        "verify", help="Verify archive integrity without modifying files"
    )
    integrity_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    integrity_cmd.add_argument("--scope", default=None)
    integrity_cmd.add_argument(
        "--trusted-local", action="store_true",
        help="Trust an operator-owned local archive root for unbounded inspection",
    )
    integrity_cmd.add_argument("--format", choices=["json", "text"], default="json")

    recover_cmd = subparsers.add_parser(
        "recover", help="Explicitly audit named integrity defects (no requeue execution)"
    )
    recover_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
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
    own statements; anything outside that class escapes as the unexpected
    internal error the command handlers report.
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
    for key, entry in todo:
        target = _identity_from_entry(entry, key)
        label = str(key)
        try:
            from .page_identity import PageIdentity

            if isinstance(target, PageIdentity):
                stem = artifact_stem(target)
                out_path = os.path.join(
                    args.archive_root, "audio", f"{stem}.m4a"
                )
            elif isinstance(target, str):
                target = resolve_page_identity(client, target)
                label = target.work_id
                stem = artifact_stem(target)
                out_path = os.path.join(
                    args.archive_root, "audio", f"{stem}.m4a"
                )
            else:
                raise TypeError("unsupported download target")
            label = target.work_id
            final = audio.download_audio(client, target, out_path, store=store)
            from .path_policy import confined_audio_path
            try:
                returned_relative = os.path.relpath(
                    os.fspath(final), os.fspath(args.archive_root)
                )
            except (OSError, ValueError, TypeError):
                returned_relative = ""
            confined = confined_audio_path(
                args.archive_root, returned_relative, require_exists=True
            )
            if confined is None:
                raise ValueError("invalid audio path")
            final = os.path.relpath(confined, os.fspath(args.archive_root))
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


def _cmd_coverage_quality(args: argparse.Namespace) -> int:
    import csv
    import io
    from pathlib import Path
    from .quality import QualityAnalyzer, REASON_CODES
    from .coverage_report import _select_scope, _diagnostic_rows
    from .sidecar_projection import (
        ReaderPolicy,
        project_attempt_records,
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
        for code in manifest_diagnostics
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

    denominator_available = (
        manifest_state == "available" and scope_state == "available"
    )
    rows: list[dict[str, object]] = []
    reason_counts: dict[str, int] = {code: 0 for code in REASON_CODES}
    total_cues = 0
    valid_work_items = 0
    has_defects = False

    analyzer = QualityAnalyzer()
    for work_id, entry in sorted(selected.items()):
        result = analyzer.analyze(entry, root)
        row_dict: dict[str, object] = {
            "work_id": work_id,
            "source": result.source,
            "language": result.language,
            "status": result.status,
            "cue_count": result.cue_count,
            "artifact_count": result.artifact_count,
            "reasons": list(result.reasons),
            "diagnostics": list(result.diagnostics),
        }
        rows.append(row_dict)
        for r in result.reasons:
            reason_counts[r] = reason_counts.get(r, 0) + 1
        total_cues += result.cue_count
        if not result.reasons and not result.diagnostics:
            valid_work_items += 1
        else:
            has_defects = True

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

    return 1 if (diagnostic_rows or has_defects) else 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    from .coverage_report import CoverageReport
    try:
        if getattr(args, "quality", False):
            return _cmd_coverage_quality(args)
        from .sidecar_projection import ReaderPolicy
        policy = ReaderPolicy(mode="trusted_archive") if getattr(args, "trusted_local", False) else None
        report = CoverageReport.build(args.archive_root, scope=args.scope, policy=policy)
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


def _subtitle_segments(root: str, entry: dict[str, object]) -> tuple[list[dict[str, object]], object] | None:
    import json
    from .archive import archive_stem

    stem = archive_stem(entry)
    raw_path = os.path.join(root, "subtitles", "raw", f"{stem}.json")
    if not os.path.isfile(raw_path):
        return None
    with open(raw_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    segments = [{"start": item.get("from", 0), "end": item.get("to", 0), "text": item.get("content", "")}
                for item in doc.get("body", [])]
    return segments, doc


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
    for entry in todo:
        key = str(entry.get("work_id") or entry["bvid"])
        label = key
        source = "subtitle"
        raw = None
        status = entry.get("status")
        subtitle_data = (
            _subtitle_segments(args.archive_root, entry)
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
                with confined_audio_file(args.archive_root, os.fspath(declared)) as safe_audio:
                    segments = asr.transcribe(safe_audio)
            paths = archive.write_archive(args.archive_root, entry, segments, source=source, raw=raw)
            if not archive.archive_bundle_complete(args.archive_root, paths):
                raise ValueError("archive bundle incomplete")
            updated = dict(store.get(key) or entry)
            updated.update(paths)
            updated["status"] = "archived"
            store.upsert(updated)
            _reclaim_after_archive(args.archive_root, updated)
            ok += 1
            print(f"{label}: archived ({source})")
        except asr.ASRDependencyError:
            failed += 1
            print(f"{label}: ASR dependency unavailable", file=sys.stderr)
        except Exception:
            failed += 1
            print(f"{label}: archive failed", file=sys.stderr)
    print(f"asr: {ok} archived" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


def _reclaim_after_archive(root: str, entry: dict[str, object]) -> None:
    """Best-effort audio reclaim once a row is archived (plan: audio-reclaim)."""
    from .audio_reclaim import reclaim_audio

    try:
        reclaim_audio(root, entry)
    except (OSError, ValueError):
        pass  # per-item non-fatal: transcripts exist; row stays archived


def _pilot_archive_subtitle(store, root: str, entry: dict[str, object]) -> dict[str, object]:
    from . import archive

    data = _subtitle_segments(root, entry)
    if data is None:
        raise ValueError(f"{_pilot_row_key(entry)}: subtitle raw JSON missing")
    segments, raw = data
    paths = archive.write_archive(root, entry, segments, source="subtitle", raw=raw)
    if not archive.archive_bundle_complete(root, paths):
        raise ValueError("archive bundle incomplete")
    updated = dict(entry)
    updated.update(paths)
    updated["status"] = "archived"
    store.upsert(updated)
    _reclaim_after_archive(root, updated)
    return updated


def _pilot_archive_asr(store, client, root: str, entry: dict[str, object], target) -> dict[str, object]:
    from . import archive, asr, audio
    from .page_identity import PageIdentity, artifact_stem
    from .subtitles import resolve_page_identity

    if isinstance(target, str):
        target = resolve_page_identity(client, target)
    if not isinstance(target, PageIdentity):
        raise TypeError("unsupported download target")
    stem = artifact_stem(target)
    out_path = os.path.join(root, "audio", f"{stem}.m4a")
    existing_rel = entry.get("audio_path") if entry.get("status") == "audio_ok" else None
    existing_audio_path: str | None = None
    from .path_policy import confined_audio_file, confined_audio_path
    if existing_rel:
        existing_audio_path_obj = confined_audio_path(root, os.fspath(existing_rel), require_exists=True)
        if existing_audio_path_obj is not None and existing_audio_path_obj.stat().st_size > 0:
            existing_audio_path = str(existing_audio_path_obj)
    if existing_audio_path is not None:
        audio_path = existing_audio_path
    else:
        downloaded = Path(os.fspath(audio.download_audio(client, target, out_path, store=store)))
        try:
            downloaded_relative = downloaded.resolve().relative_to(Path(root).resolve()).as_posix()
        except (OSError, ValueError):
            raise ValueError("invalid audio path")
        audio_path_obj = confined_audio_path(root, downloaded_relative, require_exists=True)
        if audio_path_obj is None or audio_path_obj.stat().st_size <= 0:
            raise ValueError("invalid audio path")
        audio_path = str(audio_path_obj)
    declared_audio = os.path.relpath(audio_path, root)
    with confined_audio_file(root, declared_audio) as safe_audio:
        segments = asr.transcribe(safe_audio)
    current = dict(store.get(target.work_id) or entry)
    paths = archive.write_archive(root, current, segments, source="asr")
    if not archive.archive_bundle_complete(root, paths):
        raise ValueError("archive bundle incomplete")
    current.update(paths)
    current["status"] = "archived"
    try:
        current["audio_path"] = os.path.relpath(audio_path, root)
    except ValueError:
        current["audio_path"] = audio_path
    store.upsert(current)
    _reclaim_after_archive(root, current)
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
                    client, target, store, args.archive_root
                )
            current = dict(store.get(key) or store.get_compatible(key) or entry)
            label = str(current.get("work_id") or key)
            if status == "subtitle_done":
                _pilot_archive_subtitle(store, args.archive_root, current)
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
                        args.archive_root, current_row, max_bytes
                    )
                ):
                    failed += 1
                    print(
                        f"{label}: skipped ({SKIP_REASON}); "
                        "audio-dir budget cap reached",
                        file=sys.stderr,
                    )
                    continue
                _pilot_archive_asr(
                    store, client, args.archive_root, current, target
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

def _cmd_run(args: argparse.Namespace) -> int:
    from . import bili_client
    from .coordinator import ArchiveBusyError, RunCoordinator, archive_writer
    from .manifest import ManifestStore
    from .run_ledger import RunLedger, build_run_record, compute_coverage_summary, utc_now_iso
    from .audio_budget import audio_cap_bytes

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
                           max_audio_bytes=audio_cap_bytes(args.max_audio_gb))
    print(f"run: scope={args.scope} selected {len(rows)} row(s)" + (" [offline]" if args.offline else ""))
    for key, entry in rows:
        print(f"  {entry.get('work_id') or key}: {entry.get('status')}")
    try:
        with archive_writer(args.archive_root):
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
                print(f"run: {r.work_id}: skipped ({r.skip_reason or 'unknown'})")
            exit_code = 2 if summary.risk_interrupted else (0 if summary.fully_processed else 1)
            if summary.risk_interrupted:
                print("run: risk-control ceiling; stopping — re-run to resume.", file=sys.stderr)
            print(f"run: {ok} completed, {len(skipped)} skipped" +
                  (f", {len(failed)} failed" if failed else "") +
                  (", scope not fully processed" if exit_code == 1 else ""))
            try:
                ledger = RunLedger(root=args.archive_root)
                ledger.append(build_run_record(command="run", started_at=started_at,
                    finished_at=utc_now_iso(), exit_code=exit_code, mid=None,
                    work_ids=[r.work_id for r in summary.results] or None,
                    records_existing=len(entries), coverage_summary=compute_coverage_summary(store.load())))
            except Exception:
                pass
            return exit_code
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
        usage_snapshot = audio_dir_usage_bytes(args.archive_root)
        for _key, entry in rows:
            if is_long_live(entry):
                print(format_campaign_plan(
                    campaign_plan(
                        args.archive_root,
                        entry,
                        max_audio_bytes,
                        usage_bytes=usage_snapshot,
                    )
                ))

    try:
        with archive_writer(args.archive_root):
            summary = coord.run_batch(rows)
            if args.allow_long_live:
                after = audio_dir_usage_bytes(args.archive_root)
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
        results = search(archive_root=args.archive_root, query=sq)
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
        )
        if not args.out or args.out == "-":
            sys.stdout.write(content + ("\n" if not content.endswith("\n") else ""))
            sys.stdout.flush()
    except Exception:
        print("export: unexpected error", file=sys.stderr)
        return 1
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from .integrity import IntegrityVerifier
    from .sidecar_projection import ReaderPolicy
    policy = ReaderPolicy(mode="trusted_archive") if getattr(args, "trusted_local", False) else None
    report = IntegrityVerifier().verify(Path(args.archive_root), scope=args.scope, policy=policy)
    payload = report.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"checked: {payload['checked']}")
        print(f"defects: {payload['defect_count']}")
        for defect in payload["defects"]:
            print(f"{defect['work_id']}: {defect['code']}")
        for diagnostic in payload["diagnostics"]:
            print(f"diagnostic: {diagnostic}")
    return 0 if not payload["defects"] and not payload["diagnostics"] else 1


def _cmd_recover(args: argparse.Namespace) -> int:
    from .integrity import IntegrityVerifier
    payload = IntegrityVerifier.recover(
        Path(args.archive_root), work_ids=args.work_id,
        defect_codes=args.defect_code, limit=args.limit,
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
    if args.command == "download-audio":
        return _cmd_download_audio(args)
    if args.command == "search":
        return _cmd_search(args)
    if args.command == "evaluate-concurrency":
        return _cmd_evaluate_concurrency(args)
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
