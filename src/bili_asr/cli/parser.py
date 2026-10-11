"""Argument parser for the SQLite workflow CLI."""

from __future__ import annotations

import argparse

from bili_asr.cli._shared import DEFAULT_ARCHIVE_ROOT, _UsageErrorArgumentParser
from bili_asr.config import DEFAULT_MID, DEFAULT_PAGE_LIMIT


def build_parser() -> argparse.ArgumentParser:
    parser = _UsageErrorArgumentParser(
        prog="bili-asr",
        description="Bilibili metadata, transcript workflow, and archive query CLI.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    from bili_asr.cli.workflow import add_workflow_parser
    add_workflow_parser(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)
    from bili_asr.cli.publication import add_publication_parser
    from bili_asr.cli.editorial import add_editorial_parser
    add_publication_parser(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)
    add_editorial_parser(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)
    from bili_asr.cli.snapshot import add_snapshot_parser
    add_snapshot_parser(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)
    from bili_asr.cli.archive import add_archive_parser
    add_archive_parser(subparsers)
    from bili_asr.cli.artifacts import add_artifacts_parser
    add_artifacts_parser(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)
    from bili_asr.cli.remote_storage import add_remote_parsers
    add_remote_parsers(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)
    from bili_asr.cli.source import add_source_parser
    add_source_parser(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)

    dedup = subparsers.add_parser("dedup", help="Inspect exact content reuse without changing the archive")
    dedup_actions = dedup.add_subparsers(dest="dedup_action", required=True)
    report = dedup_actions.add_parser("report", help="Report exact audio and transcript reuse")
    report.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    report.add_argument("--format", choices=("text", "json"), default="text")
    report.add_argument("--limit", type=int, default=20)

    fetch_meta = subparsers.add_parser("fetch-meta", help="Collect video metadata into SQLite")
    fetch_meta.add_argument("--mid", type=int, default=DEFAULT_MID)
    cursor = fetch_meta.add_mutually_exclusive_group()
    cursor.add_argument(
        "--resume", action="store_true",
        help="Resume from the stored cursor; fails when none exists",
    )
    cursor.add_argument(
        "--start-page", type=int, default=None,
        help="Explicit one-based page; overrides and may rewind the stored cursor",
    )
    cursor.add_argument("--incremental", action="store_true", help="Discover from page 1; the resume cursor is not an increment watermark")
    fetch_meta.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    fetch_meta.add_argument("--sessdata", default=None)
    fetch_meta.add_argument(
        "--limit-pages", type=int, default=None,
        help=f"Stop after N pages (default: {DEFAULT_PAGE_LIMIT})",
    )
    fetch_meta.add_argument(
        "--page-retries", type=int, default=0,
        help="Retry rate-control or transport failures up to 5 times with 30/60/120/240/300 second waits",
    )
    fetch_meta.add_argument(
        "--operation-retries", type=int, default=0,
        help="Retry necessary detail/parts transport failures up to 5 times within the shared request budget",
    )
    fetch_meta.add_argument(
        "--skip-failed-page", action="store_true",
        help="Skip a failed page",
    )
    fetch_meta.epilog = "Start-page selection may move it backwards, including with --skip-failed-page."
    fetch_meta.add_argument("--refresh-mode", choices=("new", "missing", "stale", "force"), default="force")
    fetch_meta.add_argument("--ttl-seconds", type=int, default=86400)
    fetch_meta.add_argument("--bvid", action="append", help="Explicitly refresh archived videos; repeat this flag")
    fetch_meta.add_argument("--fields", nargs="+", choices=("summary", "details", "parts", "tags"), default=None)
    fetch_meta.add_argument("--refresh-failed", action="store_true", help="Retry failed operations recorded in an explicit v2 archive")
    fetch_meta.add_argument("--request-budget", type=int, default=10000, help="Total upstream operation attempts including retries")
    fetch_meta.add_argument("--request-timeout", type=float, default=30)
    fetch_meta.add_argument("--run-timeout", type=float, default=14400)

    fetch_tags = subparsers.add_parser("fetch-tags", help="Refresh original tags for archived videos")
    fetch_tags.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    fetch_tags.add_argument("--sessdata", default=None)
    fetch_tags.add_argument("--bvid", action="append", default=None, help="Archived BVID; repeat, or omit for all")

    status = subparsers.add_parser("status", help="Show SQLite archive and workflow status")
    status.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    runs = subparsers.add_parser("runs", help="List metadata collection runs")
    runs.add_argument("--limit", type=int, default=None)
    runs.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    search = subparsers.add_parser("search", help="Search stored video metadata and transcript segments")
    search.add_argument("query")
    search.add_argument(
        "--scope", choices=("transcripts", "metadata", "all"), default="transcripts",
        help="Search transcripts (default), title/description/tags, or both; all puts metadata first",
    )
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--rebuild", action="store_true", help="Update the transcript FTS index before searching (transcripts/all only)")
    search.add_argument("--from", dest="pubdate_from", default=None, metavar="YYYY-MM-DD")
    search.add_argument("--to", dest="pubdate_to", default=None, metavar="YYYY-MM-DD")
    search.add_argument("--format", choices=("table", "json"), default="table")
    search.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    search_index = subparsers.add_parser("search-index", help="Build or update SQLite FTS5")
    search_index.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    coverage = subparsers.add_parser("coverage", help="Report workflow coverage from SQLite")
    coverage.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    coverage.add_argument("--scope", default=None)
    coverage.add_argument("--format", choices=("json", "csv"), default="json")
    coverage.add_argument("--strict", action="store_true")

    verify = subparsers.add_parser("verify", help="Verify workflow artifacts")
    verify.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    verify.add_argument("--scope", default=None)
    verify.add_argument("--format", choices=("json", "text"), default="json")
    verify.add_argument("--strict", action="store_true")

    export = subparsers.add_parser("export", help="Export workflow records as JSON or CSV")
    export.add_argument("--format", choices=("json", "csv"), required=True)
    export.add_argument("--out", default=None)
    export.add_argument("--status", action="append", default=None)
    export.add_argument("--with-text", action="store_true")
    export.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    environment = subparsers.add_parser("check-asr-env", help="Inspect ASR deployment or verify the AMD WSL recipe")
    environment.add_argument("--backend", choices=("amd-wsl", "cuda", "rocm", "hcu"), default="amd-wsl")
    environment.add_argument("--probe-gpu", action="store_true", help="Explicit bounded tensor probe, no model loading")
    environment.add_argument("--probe-timeout", type=float, default=20)
    environment.add_argument("--cache-root", default=None)

    from bili_asr.cli.registry import add_policy_arguments
    add_policy_arguments(subparsers)
    return parser
