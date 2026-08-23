"""Command-line interface for bili-asr."""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_MID = 23191782
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

    probe = subparsers.add_parser(
        "probe-subs", help="Probe the subtitle list for one video (no download)"
    )
    probe.add_argument("--bvid", required=True, help="Bvid to probe")
    probe.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    probe.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
    )

    harvest = subparsers.add_parser(
        "harvest-subs", help="Probe + download subtitles for pending manifest videos"
    )
    harvest.add_argument(
        "--bvid", default=None,
        help="Restrict to a single bvid (default: all meta_ok entries)",
    )
    harvest.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    harvest.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
    )
    harvest.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N videos (smoke runs)",
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
        help="Restrict to a single bvid (creates a fresh entry if unknown)",
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

    return parser


def _persist_partial(client, store, existing) -> int:
    """Merge and save pages already fetched (H2: honest --resume).

    Returns the number of records persisted from this partial run.
    """
    records = client.merge_pages(client.pages_fetched)
    entries = dict(existing)
    for bvid, meta in records.items():
        prev = entries.get(bvid, {})
        entry = dict(prev)
        entry.update(meta)
        entry.setdefault("status", "meta_ok")
        entries[bvid] = entry
    store.save(entries)
    return len(records)


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
        partial = _persist_partial(client, store, existing)
        print(
            f"risk-control ceiling: page {unenumerated} could not be "
            f"enumerated (retry budget exhausted, last code {exc.last_code}); "
            f"{partial} record(s) from {len(client.pages_fetched)} fetched "
            f"page(s) persisted, {len(existing)} pre-existing entries kept. "
            f"Re-run with --resume to continue.",
            file=sys.stderr,
        )
        return 2
    except bili_client.GoneResponse as exc:
        partial = _persist_partial(client, store, existing)
        if client.pages_fetched:
            print(
                f"fetch-meta: terminal API response (code {exc.code}) at "
                f"page {client.last_failed_page}; {len(client.pages_fetched)} "
                f"page(s) already fetched were persisted ({partial} "
                f"record(s)) — re-run with --resume to continue.",
                file=sys.stderr,
            )
        else:
            print(
                f"fetch-meta: terminal API response (code {exc.code}) at "
                f"page {client.last_failed_page}; no pages enumerated.",
                file=sys.stderr,
            )
        return 2
    except Exception as exc:
        # H1 belt-and-braces: any unexpected error exits 1 with a summary,
        # never a traceback.
        print(f"fetch-meta: unexpected error: {exc}", file=sys.stderr)
        return 1

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


def _resolve_sessdata(args: argparse.Namespace) -> str | None:
    """SESSDATA from --sessdata or env BILI_SESSDATA; never echoed."""
    return args.sessdata or os.environ.get("BILI_SESSDATA") or None


def _cmd_probe_subs(args: argparse.Namespace) -> int:
    from . import bili_client, subtitles
    from .manifest import ManifestStore

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    try:
        entries = client.probe_subs(args.bvid)
    except bili_client.RiskBudgetExhausted as exc:
        print(f"probe-subs: risk-control ceiling for {args.bvid} "
              f"(last code {exc.last_code}); retry later.", file=sys.stderr)
        return 2
    except bili_client.GoneResponse as exc:
        print(f"probe-subs: terminal API response (code {exc.code}) "
              f"for {args.bvid}.", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"probe-subs: unexpected error: {exc}", file=sys.stderr)
        return 1

    if not entries:
        print(f"{args.bvid}: no subtitles visible at this auth tier -> "
              f"needs_audio (run harvest-subs to record it)")
        return 0
    for e in entries:
        print(f"{args.bvid}: {e.get('lan')} — {e.get('lan_doc')}")
    return 0


def _cmd_harvest_subs(args: argparse.Namespace) -> int:
    from . import bili_client, subtitles
    from .manifest import ManifestStore

    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    if args.bvid:
        todo = [(args.bvid, entries.get(args.bvid) or
                 {"bvid": args.bvid, "status": "pending"})]
    else:
        todo = [(b, e) for b, e in entries.items() if e.get("status") == "meta_ok"]
    if args.limit is not None:
        todo = todo[: args.limit]

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    done = needs_audio = failed = 0
    for bvid, _entry in todo:
        try:
            status = subtitles.harvest_subtitle(client, bvid, store,
                                                args.archive_root)
        except bili_client.RiskBudgetExhausted as exc:
            failed += 1
            print(f"{bvid}: risk-control ceiling (last code {exc.last_code}); "
                  f"stopping — re-run to resume.", file=sys.stderr)
            return 2
        except bili_client.GoneResponse as exc:
            failed += 1
            e = dict(store.get(bvid) or {"bvid": bvid})
            e["status"] = "gone"
            store.upsert(e)
            print(f"{bvid}: terminal API response (code {exc.code}); "
                  f"marked gone.", file=sys.stderr)
            continue
        except Exception as exc:
            failed += 1
            print(f"{bvid}: unexpected error: {exc}", file=sys.stderr)
            continue
        if status == "subtitle_done":
            done += 1
            print(f"{bvid}: subtitle downloaded -> subtitle_done")
        else:
            needs_audio += 1
            print(f"{bvid}: no subtitles -> needs_audio")

    print(f"harvest-subs: {done} subtitle_done, {needs_audio} needs_audio"
          + (f", {failed} failed" if failed else ""))
    return 1 if failed and not (done or needs_audio) else 0


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
        todo = [args.bvid]
    else:
        todo = [b for b, e in entries.items()
                if e.get("status") == "needs_audio"]
    if args.limit is not None:
        todo = todo[: args.limit]
    if not todo:
        print("download-audio: no needs_audio entries in the manifest")
        return 0

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    ok = failed = 0
    for bvid in todo:
        out_path = os.path.join(args.archive_root, "audio", f"{bvid}.m4a")
        try:
            final = audio.download_audio(client, bvid, out_path, store=store)
        except audio.NoAudioStreamError as exc:
            failed += 1
            print(f"{bvid}: {exc}", file=sys.stderr)
            continue
        except bili_client.RiskBudgetExhausted as exc:
            failed += 1
            print(f"{bvid}: risk-control ceiling (last {exc.last_code}); "
                  f"stopping — re-run to resume.", file=sys.stderr)
            return 2
        except bili_client.GoneResponse as exc:
            failed += 1
            e = dict(store.get(bvid) or {"bvid": bvid})
            e["status"] = "gone"
            store.upsert(e)
            print(f"{bvid}: terminal API response (code {exc.code}); "
                  f"marked gone.", file=sys.stderr)
            continue
        except Exception as exc:
            failed += 1
            print(f"{bvid}: unexpected error: {exc}", file=sys.stderr)
            continue
        ok += 1
        print(f"{bvid}: audio downloaded -> audio_ok ({final})")

    print(f"download-audio: {ok} audio_ok"
          + (f", {failed} failed" if failed else ""))
    return 1 if failed and not ok else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "fetch-meta":
        return _cmd_fetch_meta(args)
    if args.command == "probe-subs":
        return _cmd_probe_subs(args)
    if args.command == "harvest-subs":
        return _cmd_harvest_subs(args)
    if args.command == "download-audio":
        return _cmd_download_audio(args)
    parser.error(f"command {args.command!r} is not implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())
