"""Metadata collection handler."""

from __future__ import annotations

import os
import sqlite3

from bili_asr.cli._shared import _metadata_database_path
from bili_asr.config import MetadataConfigError, load_metadata_config, redact_sessdata
from bili_asr.diagnostics import write_stderr


def _cmd_fetch_meta(args) -> int:
    """Collect Bilibili metadata into the SQLite archive database."""
    from bili_asr.services import MetadataIngestor
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    from bili_asr.storage import MetadataRepository, open_database

    try:
        config = load_metadata_config(args)
    except MetadataConfigError as exc:
        write_stderr(f"fetch-meta: {exc}")
        return 1
    if config.resume and not os.path.isfile(_metadata_database_path(config.archive_root)):
        write_stderr(f"fetch-meta: no archive database at {config.archive_root}; --resume requires a stored cursor")
        return 1
    try:
        connection = open_database(config.archive_root)
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
    print(f"fetch-meta: collected {result.page_count} page(s) for mid={config.mid} (outcome={result.outcome})")
    if result.outcome in {"risk_interrupted", "failed"}:
        if config.skip_failed_page and result.outcome == "failed" and result.next_cursor is not None:
            cursor_clause = f"cursor set to page {result.next_cursor.next_page} (the failed page was skipped)"
        elif result.next_cursor is not None:
            cursor_clause = f"cursor unchanged at page {result.next_cursor.next_page}"
        else:
            cursor_clause = "no cursor recorded"
        write_stderr(f"fetch-meta: metadata gateway failure ({result.error_code}); {cursor_clause} — re-run fetch-meta to resume.")
        return 2
    if result.next_cursor is not None:
        print(f"cursor: next_page={result.next_cursor.next_page} state={result.next_cursor.state}")
    return 0
