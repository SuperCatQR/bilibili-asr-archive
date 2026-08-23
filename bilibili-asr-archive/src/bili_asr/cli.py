"""Command-line interface for bili-asr."""

from __future__ import annotations

import argparse


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
    fetch_meta.add_argument("--mid", type=int, default=23191782, help="Bilibili user mid")
    fetch_meta.add_argument(
        "--resume", action="store_true", help="Resume without duplicating bvids"
    )

    subparsers.add_parser("status", help="Print manifest status summary")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    parser.error(f"command {args.command!r} is not implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())
