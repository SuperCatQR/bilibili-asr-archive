"""search and search-index handlers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sys

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _metadata_database_path,
    _open_read_only_connection,
    _open_subtitle_connection,
)
from bili_asr import search_index

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
        print(f"search: {flag} must be YYYY-MM-DD, got {value!r}", file=sys.stderr)
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

    index = search_index.TranscriptSearchIndex(
        args.archive_root, artifact_roots=args.artifact_roots
    )
    try:
        indexed = index.build()
    except search_index.FTS5UnavailableError as exc:
        print(f"search-index: {exc}", file=sys.stderr)
        return 1
    except search_index.TranscriptStoreError as exc:
        print(f"search-index: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"search-index: transcript store unreadable: {exc}", file=sys.stderr)
        return 1
    print(f"search-index: indexed {indexed} block(s); total {index.count()}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    """Query the store-backed FTS5 index for transcript blocks.

    Exit contract (exit-code-contract §1–§2 applied to the index): a healthy
    archive — including an empty result set and a not-yet-built index — exits
    0; store/index corruption (the defect class) exits 1; usage errors exit 2.
    The legacy manifest filters (``--status/--source/--language/--scope/
    --work-id``) keep the manifest-backed index behind them; the store-backed
    path is the default and answers ``--from/--to`` pubdate windows.
    """
    from bili_asr.search_index import (
        SearchIndexMissingError,
        SearchQuery,
        TranscriptStoreError,
        search,
    )

    if args.limit is not None and args.limit <= 0:
        print("search: --limit must be a positive integer", file=sys.stderr)
        raise SystemExit(2)

    pubdate_from = _parse_pubdate_bound(getattr(args, "pubdate_from", None), "--from")
    pubdate_to = _parse_pubdate_bound(
        getattr(args, "pubdate_to", None), "--to", inclusive_end=True
    )
    if pubdate_from is not None and pubdate_to is not None and pubdate_from >= pubdate_to:
        print("search: --from must be earlier than --to", file=sys.stderr)
        raise SystemExit(2)

    legacy_filters = any(
        (args.status, args.source, args.language, args.scope, args.work_id)
    )
    if args.rebuild:
        if legacy_filters:
            search_index.SearchIndex(
                args.archive_root, artifact_roots=args.artifact_roots
            ).build(force=True)
        else:
            _cmd_search_index(args)
    index = search_index.TranscriptSearchIndex(
        args.archive_root, artifact_roots=args.artifact_roots
    )
    if not legacy_filters:
        try:
            hits = index.search_blocks(
                args.query,
                pubdate_from=pubdate_from,
                pubdate_to=pubdate_to,
                limit=args.limit if args.limit is not None else 20,
            )
        except SearchIndexMissingError:
            # Backlog class: the index is work-not-yet-done, never a defect.
            print("search: index missing — run `bili-asr search-index` to build it")
            print(f"search: no hits for {args.query!r}")
            return 0
        except (search_index.TranscriptStoreError, OSError) as exc:
            print(f"search: {exc}", file=sys.stderr)
            return 1
        except search_index.FTS5UnavailableError as exc:
            print(f"search: {exc}", file=sys.stderr)
            return 1
        return _print_block_hits(args, hits)

    source_filter = _parse_status_filter(args.source)
    lang_filter = _parse_status_filter(args.language)
    work_id_filter = _parse_status_filter(args.work_id)

    sq = SearchQuery(
        query=args.query,
        status=_parse_status_filter(args.status),
        source=source_filter,
        language=lang_filter,
        scope=args.scope,
        work_id=work_id_filter,
        limit=args.limit,
        rebuild=args.rebuild,
        auto_build=True,
    )

    try:
        results = search(
            archive_root=args.archive_root, query=sq,
            artifact_roots=args.artifact_roots,
        )
    except search_index.FTS5UnavailableError as exc:
        print(f"search: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("search: unexpected error", file=sys.stderr)
        return 1

    if not results:
        print(f"search: no hits for {args.query!r}")
        return 0

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
