"""Command-line interface for bili-asr (split package)."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bili_asr.artifact_root import (
    ARTIFACT_ROOT_ENV_VAR,
    KEEP_AUDIO_ENV_VAR,
    ArtifactRootError,
    ArtifactRoots,
    resolve_keep_audio,
    roots_for,
)
from bili_asr.config import (
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
    from bili_asr.page_identity import parse_work_id

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
    from bili_asr.page_identity import identity_from_entry

    return identity_from_entry(entry, key)


def _is_excluded(entry: dict | None) -> bool:
    if not entry:
        return False
    return bool(
        entry.get("unresolved") or entry.get("excluded_from_page_processing")
    )


def _queue_source_is_manifest(args: argparse.Namespace) -> bool:
    """Whether the operator pinned the pre-cutover manifest queue.

    ``--queue-source manifest`` is the documented rollback; it preserves the
    manifest-scan behaviour exactly and prints one deprecation line so the
    choice is auditable.  Every other mode reads the store gap views.
    """

    return getattr(args, "queue_source", "store") == "manifest"


def _store_audio_todo(args: argparse.Namespace):
    """The download-audio work list from the store's ``v_missing_audio`` view.

    Returns ``(todo, queue_source, error)``: ``todo`` is the ``(work_id,
    entry)`` rows in the repository's locked order, ``queue_source`` is the
    open :class:`~bili_asr.services.queue_source.QueueSource` the caller must
    close, and ``error`` is a bounded line already printed when the store is
    unusable.  A part holding subtitles is never selected: the view only holds
    parts whose caption route is exhausted and that carry no audio evidence —
    the inversion of the pre-cutover root cause.
    """

    from bili_asr.services import queue_source as qs

    source = qs.open_queue_source(args.archive_root)
    if source is None:
        print(
            f"download-audio: no archive database at {args.archive_root}; "
            "run fetch-meta to create it",
            file=sys.stderr,
        )
        return None, None, True
    bvid = page = None
    if args.bvid:
        from bili_asr.page_identity import parse_work_id

        try:
            bvid, page = parse_work_id(args.bvid)
        except ValueError:
            bvid, page = args.bvid, None
    selection = source.select_audio_queue(bvid=bvid, page=page, limit=args.limit)
    todo = [(key, entry) for key, entry in selection.entries.items()]
    return todo, source, False


def _store_transcript_todo(args: argparse.Namespace, *, command: str):
    """The asr work list from the store's ``v_missing_transcript`` view."""

    from bili_asr.services import queue_source as qs

    source = qs.open_queue_source(args.archive_root)
    if source is None:
        print(
            f"{command}: no archive database at {args.archive_root}; "
            "run fetch-meta to create it",
            file=sys.stderr,
        )
        return None, None, True
    bvid = page = None
    selector = getattr(args, "bvid", None)
    if selector:
        from bili_asr.page_identity import parse_work_id

        try:
            bvid, page = parse_work_id(selector)
        except ValueError:
            bvid, page = selector, None
    selection = source.select_transcript_queue(bvid=bvid, page=page, limit=args.limit)
    todo = [(key, entry) for key, entry in selection.entries.items()]
    return todo, source, False


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
    from bili_asr.page_identity import parse_work_id

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


def _resolve_sessdata(args: argparse.Namespace) -> str | None:
    """SESSDATA from --sessdata or env BILI_SESSDATA; blank forces anonymous."""
    return resolve_sessdata(args.sessdata, os.environ.get(SESSDATA_ENV_VAR))


#: The four product path keys whose recorded values make a row "already
#: published" (§5.4).  The vocabulary is the writer's own: the archive writer
#: names its products with these keys, so the completeness read and the
#: writes are the same vocabulary, and the writer's return is what supplies the
#: values (``archive.py:488``, root-relative — exactly the recorded form).
from bili_asr.artifacts import REQUIRED_ARTIFACT_KEYS as _PRODUCT_PATH_KEYS


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
