"""Command-line interface for bili-asr."""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_MID = 23191782
DEFAULT_ARCHIVE_ROOT = os.path.join("archive")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bili-asr",
        description="Bilibili ASR transcript archival CLI "
        "(AI/CC subtitles first, local SenseVoice fallback).",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    fetch_meta = subparsers.add_parser(
        "fetch-meta",
        help="Enumerate videos for a mid and write the manifest ledger",
    )
    fetch_meta.add_argument("--mid", type=int, default=DEFAULT_MID,
                            help="Bilibili user mid")
    fetch_meta.add_argument(
        "--resume", action="store_true", help="Resume without duplicating bvids"
    )
    fetch_meta.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    fetch_meta.add_argument(
        "--limit-pages", type=int, default=None,
        help="Stop after N pages (smoke runs)",
    )

    subparsers.add_parser("status", help="Print manifest status summary")

    return parser


def _cmd_fetch_meta(args: argparse.Namespace) -> int:
    # Imported here so --help / status never require requests at import time
    # in low-dependency environments (bili_client lazy-imports requests).
    from . import bili_client
    from .manifest import ManifestStore

    client = bili_client.BiliClient()
    store = ManifestStore(root=args.archive_root)
    existing = store.load() if args.resume else {}

    try:
        pages = client.fetch_pages(args.mid, max_pages=args.limit_pages)
    except bili_client.RiskBudgetExhausted as exc:
        unenumerated = client.last_failed_page
        print(
            f"risk-control ceiling: page {unenumerated} could not be "
            f"enumerated (retry budget exhausted, last code {exc.last_code}); "
            f"{len(existing)} existing manifest entries kept for resume. "
            f"Re-run with --resume to continue.",
            file=sys.stderr,
        )
        return 2
    except bili_client.GoneResponse as exc:
        print(
            f"fetch-meta: terminal API response (code {exc.code}) at page "
            f"{client.last_failed_page}; no pages enumerated.",
            file=sys.stderr,
        )
        return 2

    records = client.merge_pages(pages)
    entries = dict(existing)
    for bvid, meta in records.items():
        prev = entries.get(bvid, {})
        entry = dict(prev)
        entry.update(meta)
        entry.setdefault("status", "meta_ok")
        entries[bvid] = entry
    store.save(entries)

    total_s = sum(e.get("duration_s", 0) for e in entries.values())
    print(f"manifest: {len(entries)} videos "
          f"({len(records)} fetched, {len(existing)} resumed)")
    print(f"total duration: {total_s / 3600:.1f} h")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "fetch-meta":
        return _cmd_fetch_meta(args)
    parser.error(f"command {args.command!r} is not implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())
