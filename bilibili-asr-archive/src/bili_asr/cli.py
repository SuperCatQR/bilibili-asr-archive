"""Command-line interface for bili-asr."""

from __future__ import annotations

import argparse
import os
import sys
import time

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

    status = subparsers.add_parser("status", help="Print manifest status summary")
    status.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    asr_cmd = subparsers.add_parser("asr", help="Transcribe audio and write transcript archive")
    asr_cmd.add_argument("--pending", action="store_true", help="Process audio_ok entries")
    asr_cmd.add_argument("--bvid", default=None)
    asr_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    asr_cmd.add_argument("--limit", type=int, default=None)

    pilot = subparsers.add_parser("pilot", help="Select a resumable mixed-branch pilot")
    pilot.add_argument("--n", type=int, default=20)
    pilot.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

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


def _record_api_error(
    store, bvid: str, code: int | str, starting_status: str | None = None
) -> None:
    """Attach a numeric API code, creating a resumable direct-operation row."""
    if not isinstance(code, int):
        return
    entry = store.get(bvid)
    if entry is None:
        if starting_status is None:
            return
        entry = {"bvid": bvid, "status": starting_status}
    updated = dict(entry)
    updated["last_api_error_code"] = code
    store.upsert(updated)


def _todo_for_bvid(store, bvid: str, entries: dict):
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
    return [(bvid, {"bvid": bvid, "status": "pending"})]


def _identity_from_entry(entry: dict, key: str):
    from .page_identity import page_identity

    work_id = entry.get("work_id")
    cid = entry.get("cid")
    bvid = str(entry.get("bvid") or key)
    if work_id and cid is not None:
        return page_identity(
            bvid,
            int(entry.get("page_index") or 0),
            int(cid),
            page_label=str(entry.get("page_label") or ""),
        )
    return bvid


def _is_excluded(entry: dict | None) -> bool:
    if not entry:
        return False
    return bool(
        entry.get("unresolved") or entry.get("excluded_from_page_processing")
    )


def _merge_page_rows(client, records: dict, existing: dict) -> dict:
    """Expand each enumerated bvid into one ledger row per PageIdentity."""
    from .page_identity import apply_identity

    entries = dict(existing)
    for bvid, meta in records.items():
        bare = entries.get(bvid)
        if _is_excluded(bare):
            continue
        pages = client.list_pages(bvid)
        for page in pages:
            prev = entries.get(page.work_id) or {}
            if _is_excluded(prev):
                continue
            entry = dict(prev)
            entry.update(meta)
            entry = apply_identity(entry, page)
            entry.setdefault("status", "meta_ok")
            entries[page.work_id] = entry
        if (
            bvid in entries
            and not entries[bvid].get("work_id")
            and not _is_excluded(entries[bvid])
        ):
            del entries[bvid]
    return entries


def _persist_partial(client, store, existing) -> int:
    """Merge and save pages already fetched (H2: honest --resume).

    Returns the number of records persisted from this partial run.
    """
    records = client.merge_pages(client.pages_fetched)
    entries = _merge_page_rows(client, records, existing)
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
    except bili_client.APIResponseError as exc:
        partial = _persist_partial(client, store, existing)
        print(
            f"fetch-meta: API response error (code {exc.code}) at page "
            f"{client.last_failed_page}; {partial} record(s) from "
            f"{len(client.pages_fetched)} fetched page(s) persisted. "
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
    except Exception:
        # H1 belt-and-braces: any unexpected error exits 1 with a fixed,
        # redacted summary and never a traceback.
        print("fetch-meta: unexpected error", file=sys.stderr)
        return 1

    records = client.merge_pages(pages)
    entries = _merge_page_rows(client, records, existing)
    store.save(entries)
    store.migrate_legacy_rows(client.list_pages, archive_root=args.archive_root)
    entries = store.load()

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
    except bili_client.APIResponseError as exc:
        store = ManifestStore(root=args.archive_root)
        _record_api_error(store, args.bvid, exc.code, starting_status="meta_ok")
        print(f"probe-subs: API response error (code {exc.code}) for "
              f"{args.bvid}; retry later.", file=sys.stderr)
        return 1
    except bili_client.GoneResponse as exc:
        print(f"probe-subs: terminal API response (code {exc.code}) "
              f"for {args.bvid}.", file=sys.stderr)
        return 2
    except Exception:
        print("probe-subs: unexpected error", file=sys.stderr)
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
    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    if args.bvid:
        todo = _todo_for_bvid(store, args.bvid, entries)
        if todo is None:
            print(f"{args.bvid}: multi-part video needs an explicit page",
                  file=sys.stderr)
            return 1
    else:
        todo = [
            (key, e) for key, e in entries.items()
            if e.get("status") == "meta_ok" and not _is_excluded(e)
        ]
    if args.limit is not None:
        todo = todo[: args.limit]

    done = needs_audio = failed = 0
    for key, entry in todo:
        target = _identity_from_entry(entry, key)
        label = (
            target.work_id if hasattr(target, "work_id") else str(key)
        )
        try:
            status = subtitles.harvest_subtitle(
                client, target, store, args.archive_root
            )
        except bili_client.AmbiguousPageError:
            failed += 1
            print(f"{label}: multi-part video needs an explicit page",
                  file=sys.stderr)
            continue
        except bili_client.RiskBudgetExhausted as exc:
            failed += 1
            print(f"{label}: risk-control ceiling (last code {exc.last_code}); "
                  f"stopping — re-run to resume.", file=sys.stderr)
            return 2
        except bili_client.APIResponseError as exc:
            failed += 1
            _record_api_error(store, key, exc.code)
            print(f"{label}: API response error (code {exc.code}); "
                  f"continuing.", file=sys.stderr)
            continue
        except bili_client.GoneResponse as exc:
            failed += 1
            e = dict(store.get(key) or {"bvid": str(entry.get("bvid") or key)})
            e["status"] = "gone"
            store.upsert(e)
            print(f"{label}: terminal API response (code {exc.code}); "
                  f"marked gone.", file=sys.stderr)
            continue
        except Exception:
            failed += 1
            print(f"{label}: unexpected error", file=sys.stderr)
            continue
        if status == "subtitle_done":
            done += 1
            print(f"{label}: subtitle downloaded -> subtitle_done")
        else:
            needs_audio += 1
            print(f"{label}: no subtitles -> needs_audio")
        if key != todo[-1][0]:
            time.sleep(3.0)

    print(f"harvest-subs: {done} subtitle_done, {needs_audio} needs_audio"
          + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


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
        selected = _todo_for_bvid(store, args.bvid, entries)
        if selected is None:
            print(f"{args.bvid}: multi-part video needs an explicit page",
                  file=sys.stderr)
            return 1
        todo = selected
        if not todo:
            todo = [(args.bvid, {"bvid": args.bvid, "status": "needs_audio"})]
    else:
        todo = [
            (key, e) for key, e in entries.items()
            if e.get("status") == "needs_audio" and not _is_excluded(e)
        ]
    if args.limit is not None:
        todo = todo[: args.limit]
    if not todo:
        print("download-audio: no needs_audio entries in the manifest")
        return 0

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    from .page_identity import artifact_stem
    from .subtitles import resolve_page_identity

    ok = failed = 0
    for key, entry in todo:
        target = _identity_from_entry(entry, key)
        label = str(key)
        try:
            if isinstance(target, str):
                target = resolve_page_identity(client, target)
            label = target.work_id
            stem = artifact_stem(target)
            out_path = os.path.join(args.archive_root, "audio", f"{stem}.m4a")
            final = audio.download_audio(client, target, out_path, store=store)
        except bili_client.AmbiguousPageError:
            failed += 1
            print(f"{label}: multi-part video needs an explicit page",
                  file=sys.stderr)
            continue
        except audio.NoAudioStreamError:
            failed += 1
            print(f"{label}: no audio stream available", file=sys.stderr)
            continue
        except bili_client.RiskBudgetExhausted as exc:
            failed += 1
            print(f"{label}: risk-control ceiling (last {exc.last_code}); "
                  f"stopping — re-run to resume.", file=sys.stderr)
            return 2
        except bili_client.StreamDownloadError:
            failed += 1
            print(f"{label}: audio stream failed; continuing.", file=sys.stderr)
            continue
        except bili_client.APIResponseError as exc:
            failed += 1
            _record_api_error(
                store, key, exc.code, starting_status="needs_audio"
            )
            print(f"{label}: API response error (code {exc.code}); "
                  f"continuing.", file=sys.stderr)
            continue
        except bili_client.GoneResponse as exc:
            failed += 1
            e = dict(store.get(key) or {"bvid": str(entry.get("bvid") or key)})
            e["status"] = "gone"
            store.upsert(e)
            print(f"{label}: terminal API response (code {exc.code}); "
                  f"marked gone.", file=sys.stderr)
            continue
        except Exception:
            failed += 1
            print(f"{label}: unexpected error", file=sys.stderr)
            continue
        ok += 1
        print(f"{label}: audio downloaded -> audio_ok ({final})")
        if key != todo[-1][0]:
            time.sleep(3.0)

    print(f"download-audio: {ok} audio_ok"
          + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


def _cmd_status(args: argparse.Namespace) -> int:
    from collections import Counter
    from .manifest import ManifestStore

    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    counts = Counter(entry.get("status", "pending") for entry in entries.values())
    if not counts:
        print("manifest: empty")
        return 0
    for status in sorted(counts):
        print(f"{status}: {counts[status]}")
    unresolved = store.unresolved_identifiers()
    if unresolved:
        print(f"unresolved: {len(unresolved)}")
        for identifier in unresolved:
            print(f"  {identifier}")
    return 0


def _pilot_select(entries: dict[str, dict[str, object]], n: int) -> list[dict[str, object]]:
    """Select a small mixed pilot while guaranteeing both branches when possible."""
    if n < 1:
        return []
    subtitle = [e for e in entries.values() if e.get("status") == "subtitle_done"]
    audio = [e for e in entries.values() if e.get("status") in {"needs_audio", "audio_ok"}]
    key = lambda e: (e.get("duration_s") or 0, str(e.get("bvid")))
    subtitle.sort(key=key)
    audio.sort(key=key)
    selected: list[dict[str, object]] = []
    for candidate in (subtitle[:1] + audio[:1]):
        if candidate and candidate not in selected:
            selected.append(candidate)
    remaining = sorted((e for e in entries.values() if e not in selected), key=key)
    selected.extend(remaining[: max(0, n - len(selected))])
    return selected[:n]


def _subtitle_segments(root: str, entry: dict[str, object]) -> tuple[list[dict[str, object]], object] | None:
    import json
    bvid = str(entry["bvid"])
    raw_path = os.path.join(root, "subtitles", "raw", f"{bvid}.json")
    if not os.path.isfile(raw_path):
        return None
    with open(raw_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    segments = [{"start": item.get("from", 0), "end": item.get("to", 0), "text": item.get("content", "")}
                for item in doc.get("body", [])]
    return segments, doc


def _cmd_asr(args: argparse.Namespace) -> int:
    from . import archive, asr
    from .manifest import ManifestStore

    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    if args.bvid:
        todo = [dict(entries.get(args.bvid) or {"bvid": args.bvid, "status": "audio_ok"})]
    elif args.pending:
        todo = [e for e in entries.values() if e.get("status") in {"subtitle_done", "audio_ok"}]
    else:
        print("asr: select targets with --pending or --bvid", file=sys.stderr)
        return 1
    if args.limit is not None:
        todo = todo[:args.limit]
    ok = failed = 0
    for entry in todo:
        bvid = str(entry["bvid"])
        source = "subtitle"
        raw = None
        subtitle_data = _subtitle_segments(args.archive_root, entry) if entry.get("status") == "subtitle_done" else None
        try:
            if subtitle_data is not None:
                segments, raw = subtitle_data
            else:
                source = "asr"
                audio_path = os.path.join(args.archive_root, str(entry.get("audio_path") or os.path.join("audio", f"{bvid}.m4a")))
                segments = asr.transcribe(audio_path)
            paths = archive.write_archive(args.archive_root, entry, segments, source=source, raw=raw)
            updated = dict(store.get(bvid) or entry)
            updated.update(paths)
            updated["status"] = "archived"
            store.upsert(updated)
            ok += 1
            print(f"{bvid}: archived ({source})")
        except asr.ASRDependencyError:
            print(f"{bvid}: ASR dependency unavailable", file=sys.stderr)
            return 1
        except Exception:
            failed += 1
            print(f"{bvid}: archive failed", file=sys.stderr)
    print(f"asr: {ok} archived" + (f", {failed} failed" if failed else ""))
    return 1 if failed and not ok else 0


def _cmd_pilot(args: argparse.Namespace) -> int:
    from .manifest import ManifestStore
    entries = ManifestStore(root=args.archive_root).load()
    selected = _pilot_select(entries, args.n)
    subtitle_count = sum(e.get("status") == "subtitle_done" for e in selected)
    audio_count = sum(e.get("status") in {"needs_audio", "audio_ok"} for e in selected)
    print(f"pilot: selected {len(selected)}/{args.n} videos")
    print(f"pilot branches: subtitle={subtitle_count}, audio-asr={audio_count}")
    for entry in selected:
        print(f"{entry.get('bvid')}: {entry.get('status')} ({entry.get('duration_s', 0)}s)")
    if subtitle_count == 0 or audio_count == 0:
        print("pilot: both subtitle and audio-asr branches are not available in the manifest", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "fetch-meta":
        return _cmd_fetch_meta(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "asr":
        return _cmd_asr(args)
    if args.command == "pilot":
        return _cmd_pilot(args)
    if args.command == "probe-subs":
        return _cmd_probe_subs(args)
    if args.command == "harvest-subs":
        return _cmd_harvest_subs(args)
    if args.command == "download-audio":
        return _cmd_download_audio(args)
    parser.error(f"command {args.command!r} is not implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())
