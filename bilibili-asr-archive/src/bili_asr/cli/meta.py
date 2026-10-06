"""fetch-meta / probe-subs / harvest-subs handlers."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr

import argparse
import os
import sqlite3
import sys

from bili_asr.cli._shared import (
    _metadata_database_path,
    _open_subtitle_connection,
    _selector_cannot_name_a_part,
    _subtitle_selector,
)
from bili_asr.config import (
    SESSDATA_ENV_VAR,
    MetadataConfigError,
    load_metadata_config,
    redact_sessdata,
    resolve_sessdata,
)

def _cmd_fetch_meta(args: argparse.Namespace) -> int:
    """Collect video metadata into the fresh SQLite archive database.

    Exit taxonomy (metadata-cli-contract spec): 0 successful collection
    (reached the end, the explicit --limit-pages bound, or the implicit
    DEFAULT_PAGE_LIMIT bound); 1 usage/configuration error; 2 terminal
    failure in one of two variants — a bounded gateway failure (the
    single-attempt default or exhausted --page-retries, a bounded scalar code, cursor
    unchanged unless --skip-failed-page moved it past a failed page (every
    non-rate-limit failure is skipped, so a transient one is too; a rate
    limit never is), resume safe) or an unexpected internal error (the fixed
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
        write_stderr(f"fetch-meta: {exc}")
        return 1

    if config.resume and not os.path.isfile(
        _metadata_database_path(config.archive_root)
    ):
        write_stderr(
            f"fetch-meta: no archive database at {config.archive_root}; "
            "--resume requires a stored cursor"
        )
        return 1
    try:
        connection = open_database(config.archive_root)
    except (OSError, sqlite3.Error) as exc:
        write_stderr(
            f"fetch-meta: invalid --archive-root {config.archive_root} "
            f"({type(exc).__name__})"
        )
        return 1

    try:
        repository = MetadataRepository(connection)
        if config.resume and repository.read_cursor(config.mid) is None:
            write_stderr(
                f"fetch-meta: --resume requires a stored cursor; none recorded "
                f"for mid={config.mid} (drop --resume to start from page 1)"
            )
            return 1
        gateway = BilibiliApiGateway(sessdata=config.sessdata)
        ingestor = MetadataIngestor(gateway, repository)
        result = ingestor.collect_user_pages(
            mid=config.mid,
            start_page=config.start_page,
            page_limit=config.page_limit,
            skip_failed_page=config.skip_failed_page,
            page_retries=config.page_retries,
        )
    except Exception:
        # C5: the ingestor resolves bounded gateway failures internally, so
        # anything escaping is unexpected — exit the terminal code with a
        # fixed redacted summary, never a traceback or payload text.
        write_stderr("fetch-meta: unexpected error")
        return 2
    finally:
        connection.close()

    print(f"sessdata: {redact_sessdata(config.sessdata)}")
    print(
        f"fetch-meta: collected {result.page_count} page(s) for "
        f"mid={config.mid} (outcome={result.outcome})"
    )
    if result.outcome in {"risk_interrupted", "failed"}:
        # The clause reports the value the store now holds, not a direction of
        # movement: under ``--skip-failed-page`` the cursor was deliberately
        # committed one page past the failure, so "unchanged" would assert the
        # opposite of the stored state, while "advanced" would claim movement
        # that ``--start-page`` may have made untrue.  ``risk_interrupted`` is
        # excluded because the ingestor deliberately does not skip a rate
        # limit, so that arm still reads "unchanged".
        if (
            config.skip_failed_page
            and result.outcome == "failed"
            and result.next_cursor is not None
        ):
            cursor_clause = (
                f"cursor set to page {result.next_cursor.next_page} "
                f"(the failed page was skipped)"
            )
        elif result.next_cursor is not None:
            cursor_clause = f"cursor unchanged at page {result.next_cursor.next_page}"
        else:
            cursor_clause = "no cursor recorded"
        write_stderr(
            f"fetch-meta: metadata gateway failure ({result.error_code}); "
            f"{cursor_clause} — re-run fetch-meta to resume."
        )
        return 2
    if result.next_cursor is not None:
        print(
            f"cursor: next_page={result.next_cursor.next_page} "
            f"state={result.next_cursor.state}"
        )
    return 0


def _cmd_probe_subs(args: argparse.Namespace) -> int:
    """List the subtitle tracks the selected parts expose, writing nothing.

    Read-only by construction: ``probe-subs`` is not an archive-writer command,
    so it takes no writer lock, creates no file below the archive root, and never
    creates a missing database.  Exit taxonomy: 0 the probe ran (zero-track parts
    included); 1 usage/configuration (neither or both selectors, a non-positive
    bound, a missing database, an unknown --bvid, the schema guard); 2 the probe
    failed on every selected part, or an unexpected internal error.  A partial
    per-part failure stays visible in the printed ``failed=`` count.

    This is a deliberate read-only contract: probe observations are diagnostic
    only and must not count as harvested subtitle evidence or create a
    re-driveable archive row.
    """
    from bili_asr.services.subtitle_ingest import (
        SubtitleIngestor,
        SubtitleSelection,
    )
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    from bili_asr.storage import TranscriptRepository

    if (args.bvid is None) == (args.limit_parts is None):
        write_stderr(
            "probe-subs: exactly one of --bvid / --limit-parts is required"
        )
        return 1
    if args.limit_parts is not None and args.limit_parts < 1:
        write_stderr(
            "probe-subs: --limit-parts must be a positive integer"
        )
        return 1
    bvid, page_index = _subtitle_selector(args.bvid)
    if bvid is not None and _selector_cannot_name_a_part(bvid):
        # A blank or control-character selector names no part in any database, so
        # it is the documented configuration error and is decided before the
        # database is opened.
        write_stderr(f"probe-subs: unknown --bvid {args.bvid}")
        return 1
    sessdata = resolve_sessdata(args.sessdata, os.environ.get(SESSDATA_ENV_VAR))
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
            write_stderr(f"probe-subs: unknown --bvid {args.bvid}")
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
        write_stderr("probe-subs: unexpected error")
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
            write_stderr(
                "harvest-subs: --language entries must not be empty"
            )
            return 1
    if args.limit_parts is not None and args.limit_parts < 1:
        write_stderr(
            "harvest-subs: --limit-parts must be a positive integer"
        )
        return 1
    bvid, page_index = _subtitle_selector(args.bvid)
    if bvid is not None and _selector_cannot_name_a_part(bvid):
        # Same configuration error as an unknown bvid, and decided on the
        # argument alone: a selector the archive cannot store can never resolve to
        # a part, so no bound would make it selectable.
        write_stderr(f"harvest-subs: unknown --bvid {args.bvid}")
        return 1
    if args.limit_parts is None and page_index is None:
        # No unbounded runs: only a single named part is bounded by construction.
        write_stderr(
            "harvest-subs: --limit-parts is required unless a single bvid:pN "
            "part is selected"
        )
        return 1
    sessdata = resolve_sessdata(args.sessdata, os.environ.get(SESSDATA_ENV_VAR))
    connection = _open_subtitle_connection("harvest-subs", args.archive_root)
    if connection is None:
        return 1
    try:
        repository = TranscriptRepository(connection)
        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
            # Decided before the run is opened: an unknown selector is
            # configuration and must not leave an empty run row behind.
            write_stderr(f"harvest-subs: unknown --bvid {args.bvid}")
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
        write_stderr("harvest-subs: unexpected error")
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
