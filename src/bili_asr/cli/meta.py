"""Metadata collection handler."""

from __future__ import annotations

import os
import sqlite3

from bili_asr.cli._shared import _metadata_database_path
from bili_asr.config import MetadataConfigError, load_metadata_config, redact_sessdata
from bili_asr.diagnostics import write_stderr
from bili_asr.archive_session import ArchiveAccessMode, open_archive_connection


def _cmd_fetch_meta(args) -> int:
    """Collect Bilibili metadata into the SQLite archive database."""
    from bili_asr.services import MetadataIngestor
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    from bili_asr.storage import MetadataRepository

    try:
        config = load_metadata_config(args)
    except MetadataConfigError as exc:
        write_stderr(f"fetch-meta: {exc}")
        return 1
    if config.resume and not os.path.isfile(_metadata_database_path(config.archive_root)):
        write_stderr(f"fetch-meta: no archive database at {config.archive_root}; --resume requires a stored cursor")
        return 1
    try:
        connection = open_archive_connection(config.archive_root, mode=ArchiveAccessMode.BOOTSTRAP)
    except (OSError, sqlite3.Error) as exc:
        write_stderr(f"fetch-meta: invalid --archive-root {config.archive_root} ({type(exc).__name__})")
        return 1
    try:
        repository = MetadataRepository(connection)
        if config.resume and repository.read_cursor(config.mid) is None:
            write_stderr(f"fetch-meta: --resume requires a stored cursor; none recorded for mid={config.mid}")
            return 1
        result = MetadataIngestor(
            BilibiliApiGateway(sessdata=config.sessdata), repository
        ).collect_user_pages(
            mid=config.mid,
            start_page=config.start_page,
            page_limit=config.page_limit,
            skip_failed_page=config.skip_failed_page,
            page_retries=config.page_retries,
        )
    except Exception:
        write_stderr("fetch-meta: unexpected error")
        return 2
    finally:
        connection.close()

    print(f"sessdata: {redact_sessdata(config.sessdata)}")
    print(f"fetch-meta: recorded {result.page_count} page(s) for mid={config.mid} "
          f"(outcome={result.outcome}); collected_pages={result.collected_page_count} "
          f"videos={result.video_count} parts={result.part_count}")
    print(f"tags: attempted={result.tag_attempt_count} succeeded={result.tag_success_count} "
          f"failed={result.tag_failure_count}")
    if result.tag_failure_count:
        write_stderr("fetch-meta: optional tag coverage incomplete; use fetch-tags to retry archived videos")
    if result.outcome in {"risk_interrupted", "failed"}:
        if result.error_diagnostic is not None:
            write_stderr(f"fetch-meta: diagnostic {result.error_diagnostic.format()}")
        if config.skip_failed_page and result.outcome == "failed" and result.next_cursor is not None:
            cursor_clause = f"cursor set to page {result.next_cursor.next_page} (the failed page was skipped)"
        elif result.next_cursor is not None:
            cursor_clause = f"cursor unchanged at page {result.next_cursor.next_page}"
        else:
            cursor_clause = "no cursor recorded"
        if result.next_cursor is None:
            recovery = (f"re-run fetch-meta with --start-page {config.start_page or 1}; "
                        "--resume requires a stored cursor")
        else:
            recovery = "re-run fetch-meta without --start-page to continue from the stored cursor"
        if result.error_code == "auth_error":
            recovery = f"refresh BILI_SESSDATA before retrying; {recovery}"
        write_stderr(f"fetch-meta: metadata gateway failure ({result.error_code}); {cursor_clause} — {recovery}.")
        return 2
    if result.next_cursor is not None:
        print(f"cursor: next_page={result.next_cursor.next_page} state={result.next_cursor.state}")
    return 0


def _cmd_fetch_tags(args) -> int:
    from bili_asr.config import resolve_sessdata
    from bili_asr.services.video_tags import refresh_video_tags
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    from pathlib import Path

    if not Path(_metadata_database_path(args.archive_root)).is_file():
        write_stderr("fetch-tags: archive database does not exist")
        return 1
    try:
        connection = open_archive_connection(args.archive_root, mode=ArchiveAccessMode.BOOTSTRAP)
        try:
            selected = args.bvid or [row[0] for row in connection.execute("SELECT bvid FROM videos ORDER BY bvid")]
            result = refresh_video_tags(connection, BilibiliApiGateway(
                sessdata=resolve_sessdata(args.sessdata, os.environ.get("BILI_SESSDATA"))), selected)
        finally:
            connection.close()
    except (ValueError, OSError, sqlite3.Error) as exc:
        write_stderr(f"fetch-tags: invalid archive or request ({type(exc).__name__})")
        return 1
    print(f"tags: attempted={result['attempted']} succeeded={result['succeeded']} failed={result['failed']}")
    if result["failed"]:
        write_stderr("fetch-tags: optional tag coverage incomplete; previous successful tags preserved")
        return 2
    return 0
