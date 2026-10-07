"""search and search-index handlers."""

from __future__ import annotations

import bili_asr.search_index.errors as _module_search_index_errors
import bili_asr.search_index.store as _module_search_index_store


from bili_asr.diagnostics import write_stderr

from datetime import datetime, timezone
import json
import sys


def _parse_pubdate_bound(value: str | None, flag: str, *, inclusive_end: bool = False) -> int | None:
    """Parse a YYYY-MM-DD date bound into a unix-second window edge (usage error on bad input).

    ``--from`` is the day's start; ``--to`` (``inclusive_end``) is the *end* of
    the named day, so ``--to 2020-09-13`` keeps a video published on that day.
    """
    if value is None:
        return None
    try:
        day = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        write_stderr(f"search: {flag} must be YYYY-MM-DD, got {value!r}")
        raise SystemExit(2)
    day = day.replace(tzinfo=timezone.utc)
    if inclusive_end:
        from datetime import timedelta

        day = day + timedelta(days=1)
    return int(day.timestamp())


def _format_ms(ms: int) -> str:
    """Render a millisecond offset as HH:MM:SS,mmm for timestamped jump-to playback."""
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _cmd_search_index(args: argparse.Namespace) -> int:
    """Build (or top up) the store-backed FTS5 index inside ``archive.db``.

    Idempotent and incremental: existing rows are never rewritten, only newly
    stored transcript segments are appended.  Exit 1 only when the store is
    unreadable/corrupt or FTS5 is unavailable — never merely because rows are
    missing or unindexed (the two-class exit contract).
    """
    from bili_asr import search_index

    if not search_index.check_fts5_available():
        write_stderr("search-index: SQLite FTS5 is unavailable")
        return 1

    index = _module_search_index_store.TranscriptSearchIndex(
        args.archive_root, artifact_roots=args.artifact_roots
    )
    try:
        indexed = index.build()
    except _module_search_index_errors.FTS5UnavailableError as exc:
        write_stderr(f"search-index: {exc}")
        return 1
    except _module_search_index_errors.TranscriptStoreError as exc:
        write_stderr(f"search-index: {exc}")
        return 1
    except OSError as exc:
        write_stderr(f"search-index: transcript store unreadable: {exc}")
        return 1
    print(f"search-index: indexed {indexed} block(s); total {index.count()}")
    return 0

def _cmd_search(args: argparse.Namespace) -> int:
    """Query the store-backed FTS5 index for transcript blocks.

    Exit contract (exit-code-contract §1–§2 applied to the index): a healthy
    archive — including an empty result set and a not-yet-built index — exits
    0; store/index corruption (the defect class) exits 1; usage errors exit 2.
    The SQLite transcript store is the only search source.
    """
    from bili_asr.search_index.errors import SearchIndexMissingError, TranscriptStoreError
    if args.limit is not None and args.limit <= 0:
        write_stderr("search: --limit must be a positive integer")
        raise SystemExit(2)

    pubdate_from = _parse_pubdate_bound(getattr(args, "pubdate_from", None), "--from")
    pubdate_to = _parse_pubdate_bound(
        getattr(args, "pubdate_to", None), "--to", inclusive_end=True
    )
    if pubdate_from is not None and pubdate_to is not None and pubdate_from >= pubdate_to:
        write_stderr("search: --from must be earlier than --to")
        raise SystemExit(2)

    if args.rebuild:
        _cmd_search_index(args)
    index = _module_search_index_store.TranscriptSearchIndex(
        args.archive_root, artifact_roots=args.artifact_roots
    )
    try:
        hits = index.search_blocks(
            args.query,
            pubdate_from=pubdate_from,
            pubdate_to=pubdate_to,
            limit=args.limit if args.limit is not None else 20,
        )
    except SearchIndexMissingError:
        print("search: index missing — run `bili-asr search-index` to build it")
        print(f"search: no hits for {args.query!r}")
        return 0
    except (_module_search_index_errors.TranscriptStoreError, OSError,
            _module_search_index_errors.FTS5UnavailableError) as exc:
        write_stderr(f"search: {exc}")
        return 1
    return _print_block_hits(args, hits)


def _print_block_hits(args: argparse.Namespace, hits) -> int:
    """Render store-backed block hits as table (default) or JSON."""
    if getattr(args, "format", "table") == "json":
        print(json.dumps([h.to_dict() for h in hits], indent=2, ensure_ascii=False))
        return 0
    if not hits:
        print(f"search: no hits for {args.query!r}")
        return 0
    for hit in hits:
        pubdate_day = datetime.fromtimestamp(
            hit.pubdate, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        snippet = hit.snippet.replace("\n", " ")
        title = hit.video_title or "(untitled)"
        print(
            f"{hit.bvid} P{hit.page_index} {title} "
            f"[{_format_ms(hit.start_ms)} → {_format_ms(hit.end_ms)}] "
            f"({pubdate_day}) {snippet}"
        )
    return 0
