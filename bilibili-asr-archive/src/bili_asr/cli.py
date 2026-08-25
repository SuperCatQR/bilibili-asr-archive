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

    runs = subparsers.add_parser(
        "runs", help="List recent operational runs from the ledger"
    )
    runs.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N recent runs (default: all)",
    )
    runs.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    asr_cmd = subparsers.add_parser("asr", help="Transcribe audio and write transcript archive")
    asr_cmd.add_argument("--pending", action="store_true", help="Process audio_ok entries")
    asr_cmd.add_argument("--bvid", default=None)
    asr_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    asr_cmd.add_argument("--limit", type=int, default=None)

    pilot = subparsers.add_parser(
        "pilot",
        help="Execute a bounded mixed-branch pilot (subtitle-hit and audio→ASR)",
    )
    pilot.add_argument("--n", type=int, default=20)
    pilot.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    pilot.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
    )

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
        help="Restrict to a bvid or work_id (bvid:pN); STOP if unresolved "
             "or multi-part without an explicit page",
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
        help="Restrict to a bvid or work_id (bvid:pN); STOP if unresolved "
             "or multi-part without an explicit page",
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
    store, key: str, code: int | str, starting_status: str | None = None
) -> None:
    """Attach a numeric API code to an existing work_id / compatible row."""
    del starting_status  # never invent a new bare-bvid processable row
    if not isinstance(code, int):
        return
    entry = store.get(key) or store.get_compatible(key)
    if entry is None:
        return
    updated = dict(entry)
    updated["last_api_error_code"] = code
    store.upsert(updated)


def _todo_for_bvid(store, selector: str, entries: dict):
    from .page_identity import parse_work_id

    try:
        parse_work_id(selector)
    except ValueError:
        bvid = selector
    else:
        entry = entries.get(selector) or store.get(selector)
        if entry is None or _is_excluded(entry):
            return []
        return [(selector, entry)]

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
    return []


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


def _cached_page_lister(client):
    """Reuse pagelist results and pace calls like series fetch."""
    cache: dict = {}

    def pages_for(bvid: str):
        if bvid in cache:
            return cache[bvid]
        if cache:
            jitter = getattr(client, "_jitter", lambda: 0.0)()
            client._sleeper(0.8 + max(0.0, jitter) * 0.8)
        cache[bvid] = client.list_pages(bvid)
        return cache[bvid]

    return pages_for


def _merge_page_rows(client, records: dict, existing: dict, pages_for=None) -> dict:
    """Expand each enumerated bvid into one ledger row per PageIdentity."""
    from .page_identity import apply_identity

    if pages_for is None:
        pages_for = _cached_page_lister(client)
    entries = dict(existing)
    for bvid, meta in records.items():
        bare = entries.get(bvid)
        if _is_excluded(bare):
            continue
        try:
            pages = pages_for(bvid)
        except Exception:
            continue
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


def _persist_cursor(
    cursor_store,
    *,
    mid: int,
    next_page: int,
    total: int | None,
    state: str,
    last_api_error_code: int | str | None = None,
) -> None:
    from .meta_cursor import utc_now_iso

    cursor_store.replace_atomic(
        {
            "mid": mid,
            "next_page": next_page,
            "total": total,
            "state": state,
            "last_api_error_code": last_api_error_code,
            "updated_at": utc_now_iso(),
        }
    )


def _interrupt_cursor(client, cursor_store, mid: int, last_api_error_code) -> None:
    _persist_cursor(
        cursor_store,
        mid=mid,
        next_page=client.last_failed_page,
        total=client.last_observed_total,
        state="risk_interrupted",
        last_api_error_code=last_api_error_code,
    )


def _persist_partial(client, store, existing, pages_for=None) -> int:
    """Merge and save pages already fetched (H2: honest --resume).

    Returns the number of records persisted from this partial run.
    """
    if pages_for is None:
        pages_for = _cached_page_lister(client)
    records = client.merge_pages(client.pages_fetched)
    entries = _merge_page_rows(client, records, existing, pages_for=pages_for)
    store.save(entries)
    return len(records)


def _cmd_fetch_meta(args: argparse.Namespace) -> int:
    # Imported here so --help / status never require requests at import time
    # in low-dependency environments (bili_client lazy-imports requests).
    from . import bili_client
    from .manifest import ManifestStore
    from .meta_cursor import MetaCursorStore
    from .page_identity import parse_work_id
    from .run_ledger import (
        RunLedger,
        build_run_record,
        compute_coverage_summary,
        utc_now_iso,
    )

    started_at = utc_now_iso()
    ledger = RunLedger(root=args.archive_root)
    client = bili_client.BiliClient()
    store = ManifestStore(root=args.archive_root)
    cursor_store = MetaCursorStore(root=args.archive_root)
    # Always merge prior JSONL (last-write-wins). Without --resume the
    # leftover cursor is replaced; the catalog is not truncated to page 1.
    existing = store.load()
    start_page = 1
    if args.resume:
        resumed = cursor_store.resume_start_page(args.mid)
        if resumed is not None:
            start_page = resumed
    pages_for = _cached_page_lister(client)
    # Seed fetch_pages.seen only on --resume. A full recrawl must walk
    # ceil(total/ps) even when every page-1 bvid already lives in JSONL;
    # the no-new-bvid stop would otherwise fire after the first overlap.
    known_bvids: set[str] = set()
    if args.resume:
        for key, row in existing.items():
            bvid = row.get("bvid") if isinstance(row, dict) else None
            if bvid:
                known_bvids.add(str(bvid))
                continue
            try:
                parsed, _ = parse_work_id(key)
                known_bvids.add(parsed)
            except ValueError:
                pass
    per_page_persists = 0

    def _record_exit(
        exit_code: int,
        *,
        pages_count: int | None = None,
        records_count: int | None = None,
        last_error_code: int | str | None = None,
    ) -> None:
        try:
            cursor_snapshot = cursor_store.load()
            coverage = compute_coverage_summary(store.load())
            rec = build_run_record(
                command="fetch-meta",
                started_at=started_at,
                finished_at=utc_now_iso(),
                exit_code=exit_code,
                mid=args.mid,
                pages_fetched=pages_count,
                records_fetched=records_count,
                records_existing=len(existing),
                last_api_error_code=last_error_code,
                coverage_summary=coverage,
                cursor_snapshot=cursor_snapshot,
            )
            ledger.append(rec)
        except Exception:
            pass

    def _after_successful_page() -> None:
        nonlocal existing, per_page_persists
        _persist_partial(client, store, existing, pages_for=pages_for)
        existing = store.load()
        per_page_persists += 1
        # Mid-run: never persist running; keep risk_interrupted until the
        # terminal complete/limited write after fetch_pages returns.
        _persist_cursor(
            cursor_store,
            mid=args.mid,
            next_page=client.last_completed_page + 1,
            total=client.last_observed_total,
            state="risk_interrupted",
        )

    try:
        pages = client.fetch_pages(
            args.mid,
            max_pages=args.limit_pages,
            start_page=start_page,
            on_page=_after_successful_page,
            known_bvids=known_bvids or None,
        )
    except bili_client.RiskBudgetExhausted as exc:
        unenumerated = client.last_failed_page
        partial = _persist_partial(client, store, existing, pages_for=pages_for)
        _interrupt_cursor(client, cursor_store, args.mid, exc.last_code)
        _record_exit(
            2,
            pages_count=len(client.pages_fetched),
            records_count=partial,
            last_error_code=exc.last_code,
        )
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
        partial = _persist_partial(client, store, existing, pages_for=pages_for)
        _interrupt_cursor(client, cursor_store, args.mid, exc.code)
        _record_exit(
            2,
            pages_count=len(client.pages_fetched),
            records_count=partial,
            last_error_code=exc.code,
        )
        print(
            f"fetch-meta: API response error (code {exc.code}) at page "
            f"{client.last_failed_page}; {partial} record(s) from "
            f"{len(client.pages_fetched)} fetched page(s) persisted. "
            f"Re-run with --resume to continue.",
            file=sys.stderr,
        )
        return 2
    except bili_client.GoneResponse as exc:
        partial = _persist_partial(client, store, existing, pages_for=pages_for)
        _interrupt_cursor(client, cursor_store, args.mid, exc.code)
        _record_exit(
            2,
            pages_count=len(client.pages_fetched),
            records_count=partial,
            last_error_code=exc.code,
        )
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
    if per_page_persists:
        entries = store.load()
    else:
        entries = _merge_page_rows(client, records, existing, pages_for=pages_for)
        store.save(entries)
    store.migrate_legacy_rows(pages_for, archive_root=args.archive_root)
    entries = store.load()

    next_page = client.last_completed_page + 1
    if client.enumeration_complete:
        cursor_state = "complete"
    else:
        cursor_state = "limited"
    _persist_cursor(
        cursor_store,
        mid=args.mid,
        next_page=next_page,
        total=client.last_observed_total,
        state=cursor_state,
    )
    _record_exit(
        0,
        pages_count=len(pages),
        records_count=len(records),
        last_error_code=None,
    )

    total_s = sum(e.get("duration_s", 0) for e in entries.values())
    print(f"manifest: {len(entries)} videos "
          f"({len(records)} fetched, {len(existing)} resumed)")
    print(f"total duration: {total_s / 3600:.1f} h")
    if cursor_state == "complete":
        print("enumeration: complete")
    else:
        print(
            f"enumeration: limited (next unenumerated page {next_page})"
        )
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
        _record_api_error(store, args.bvid, exc.code)
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
        if not todo:
            print(
                f"{args.bvid}: unresolved; not assigned to a page",
                file=sys.stderr,
            )
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
            e = dict(store.get(key) or store.get_compatible(key) or {})
            if e.get("work_id"):
                e["status"] = "gone"
                store.upsert(e)
            print(f"{label}: terminal API response (code {exc.code}); "
                  f"marked gone.", file=sys.stderr)
            continue
        except ValueError as exc:
            failed += 1
            msg = str(exc)
            if "missing cid" in msg or "unresolved" in msg:
                print(f"{label}: {msg}", file=sys.stderr)
            else:
                print(f"{label}: unexpected error", file=sys.stderr)
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
            print(
                f"{args.bvid}: unresolved; not assigned to a page",
                file=sys.stderr,
            )
            return 1
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
            from .page_identity import PageIdentity

            if isinstance(target, PageIdentity):
                stem = artifact_stem(target)
                out_path = os.path.join(
                    args.archive_root, "audio", f"{stem}.m4a"
                )
            elif isinstance(target, str):
                target = resolve_page_identity(client, target)
                label = target.work_id
                stem = artifact_stem(target)
                out_path = os.path.join(
                    args.archive_root, "audio", f"{stem}.m4a"
                )
            else:
                raise TypeError("unsupported download target")
            label = target.work_id
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
            _record_api_error(store, key, exc.code)
            print(f"{label}: API response error (code {exc.code}); "
                  f"continuing.", file=sys.stderr)
            continue
        except bili_client.GoneResponse as exc:
            failed += 1
            e = dict(store.get(key) or store.get_compatible(key) or {})
            if e.get("work_id"):
                e["status"] = "gone"
                store.upsert(e)
            print(f"{label}: terminal API response (code {exc.code}); "
                  f"marked gone.", file=sys.stderr)
            continue
        except ValueError as exc:
            failed += 1
            msg = str(exc)
            if "missing cid" in msg or "unresolved" in msg:
                print(f"{label}: {msg}", file=sys.stderr)
            else:
                print(f"{label}: unexpected error", file=sys.stderr)
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
    from .run_ledger import (
        RunLedger,
        format_coverage_summary,
        format_cursor_summary,
    )

    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    counts = Counter(entry.get("status", "pending") for entry in entries.values())
    if not counts:
        print("manifest: empty")
    else:
        for status in sorted(counts):
            print(f"{status}: {counts[status]}")
    unresolved = store.unresolved_identifiers()
    if unresolved:
        print(f"unresolved: {len(unresolved)}")
        for identifier in unresolved:
            print(f"  {identifier}")

    ledger = RunLedger(root=args.archive_root)
    records = ledger.load()
    if not records:
        print("runs: 0")
    else:
        print(f"runs: {len(records)}")
        latest = records[-1]
        run_id = latest.get("run_id", "unknown")
        cmd = latest.get("command", "unknown")
        code = latest.get("exit_code", "?")
        finished = latest.get("finished_at") or latest.get("started_at") or ""
        print(f"latest run: {run_id} ({cmd}, exit {code}, {finished})")
        cursor_summary = format_cursor_summary(latest.get("cursor_snapshot"))
        print(f"latest cursor: {cursor_summary}")
        cov_summary = format_coverage_summary(latest.get("coverage_summary"))
        print(f"latest coverage: {cov_summary}")
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    from .run_ledger import RunLedger, format_run_summary

    ledger = RunLedger(root=args.archive_root)
    records = ledger.load()
    if not records:
        print("runs: empty")
        return 0

    if args.limit is not None:
        if args.limit <= 0:
            print("runs: empty")
            return 0
        records = records[-args.limit:]

    for record in records:
        print(format_run_summary(record))
    return 0


_PILOT_PROCESSABLE = frozenset(
    {"meta_ok", "subtitle_done", "needs_audio", "audio_ok"}
)
_PILOT_SKIP_HARVEST = frozenset(
    {"subtitle_done", "needs_audio", "audio_ok", "archived"}
)


def _pilot_row_key(entry: dict[str, object]) -> str:
    return str(entry.get("work_id") or entry.get("bvid") or "")


def _pilot_duration_key(entry: dict[str, object]):
    return (entry.get("duration_s") or 0, str(entry.get("bvid") or ""), _pilot_row_key(entry))


def _pilot_processable(entries: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return [
        e for e in entries.values()
        if e.get("status") in _PILOT_PROCESSABLE and not _is_excluded(e)
    ]


def _pilot_select(entries: dict[str, dict[str, object]], n: int) -> list[dict[str, object]]:
    """Select a small mixed pilot while guaranteeing both branches when possible."""
    if n < 1:
        return []
    processable = _pilot_processable(entries)
    subtitle = [e for e in processable if e.get("status") == "subtitle_done"]
    audio = [e for e in processable if e.get("status") in {"needs_audio", "audio_ok"}]
    subtitle.sort(key=_pilot_duration_key)
    audio.sort(key=_pilot_duration_key)
    selected: list[dict[str, object]] = []
    for candidate in (subtitle[:1] + audio[:1]):
        if candidate and candidate not in selected:
            selected.append(candidate)
    remaining = sorted(
        (e for e in processable if e not in selected),
        key=_pilot_duration_key,
    )
    selected.extend(remaining[: max(0, n - len(selected))])
    return selected[:n]


def _expand_selected_pages(
    entries: dict[str, dict[str, object]],
    selected: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Include every processable pagelist work_id for selected bvids."""
    if not selected:
        return selected
    chosen = {_pilot_row_key(e) for e in selected}
    bvids = {str(e.get("bvid") or "") for e in selected}
    extras = [
        e for e in _pilot_processable(entries)
        if str(e.get("bvid") or "") in bvids and _pilot_row_key(e) not in chosen
    ]
    extras.sort(key=_pilot_duration_key)
    return selected + extras


def _subtitle_segments(root: str, entry: dict[str, object]) -> tuple[list[dict[str, object]], object] | None:
    import json
    from .archive import archive_stem

    stem = archive_stem(entry)
    raw_path = os.path.join(root, "subtitles", "raw", f"{stem}.json")
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
        selected = _todo_for_bvid(store, args.bvid, entries)
        if selected is None:
            print(f"{args.bvid}: multi-part video needs an explicit page",
                  file=sys.stderr)
            return 1
        if not selected:
            print(
                f"{args.bvid}: unresolved; not assigned to a page",
                file=sys.stderr,
            )
            return 1
        todo = [e for _key, e in selected]
    elif args.pending:
        todo = [
            e for e in entries.values()
            if e.get("status") in {"subtitle_done", "audio_ok"}
            and not _is_excluded(e)
        ]
    else:
        print("asr: select targets with --pending or --bvid", file=sys.stderr)
        return 1
    if args.limit is not None:
        todo = todo[:args.limit]
    ok = failed = 0
    for entry in todo:
        key = str(entry.get("work_id") or entry["bvid"])
        label = key
        source = "subtitle"
        raw = None
        subtitle_data = _subtitle_segments(args.archive_root, entry) if entry.get("status") == "subtitle_done" else None
        try:
            if subtitle_data is not None:
                segments, raw = subtitle_data
            else:
                source = "asr"
                stem = archive.archive_stem(entry)
                audio_path = os.path.join(
                    args.archive_root,
                    str(entry.get("audio_path") or os.path.join("audio", f"{stem}.m4a")),
                )
                segments = asr.transcribe(audio_path)
            paths = archive.write_archive(args.archive_root, entry, segments, source=source, raw=raw)
            updated = dict(store.get(key) or entry)
            updated.update(paths)
            updated["status"] = "archived"
            store.upsert(updated)
            ok += 1
            print(f"{label}: archived ({source})")
        except asr.ASRDependencyError:
            print(f"{label}: ASR dependency unavailable", file=sys.stderr)
            return 1
        except Exception:
            failed += 1
            print(f"{label}: archive failed", file=sys.stderr)
    print(f"asr: {ok} archived" + (f", {failed} failed" if failed else ""))
    return 1 if failed and not ok else 0


def _pilot_archive_subtitle(store, root: str, entry: dict[str, object]) -> dict[str, object]:
    from . import archive

    data = _subtitle_segments(root, entry)
    if data is None:
        raise ValueError(f"{_pilot_row_key(entry)}: subtitle raw JSON missing")
    segments, raw = data
    paths = archive.write_archive(root, entry, segments, source="subtitle", raw=raw)
    updated = dict(entry)
    updated.update(paths)
    updated["status"] = "archived"
    store.upsert(updated)
    return updated


def _pilot_archive_asr(store, client, root: str, entry: dict[str, object], target) -> dict[str, object]:
    from . import archive, asr, audio
    from .page_identity import PageIdentity, artifact_stem
    from .subtitles import resolve_page_identity

    if isinstance(target, str):
        target = resolve_page_identity(client, target)
    if not isinstance(target, PageIdentity):
        raise TypeError("unsupported download target")
    stem = artifact_stem(target)
    out_path = os.path.join(root, "audio", f"{stem}.m4a")
    existing_rel = entry.get("audio_path") if entry.get("status") == "audio_ok" else None
    if existing_rel:
        existing_abs = (
            existing_rel if os.path.isabs(str(existing_rel))
            else os.path.join(root, str(existing_rel))
        )
        if os.path.isfile(existing_abs) and os.path.getsize(existing_abs) > 0:
            out_path = existing_abs
    audio_path = audio.download_audio(client, target, out_path, store=store)
    segments = asr.transcribe(audio_path)
    current = dict(store.get(target.work_id) or entry)
    paths = archive.write_archive(root, current, segments, source="asr")
    current.update(paths)
    current["status"] = "archived"
    try:
        current["audio_path"] = os.path.relpath(audio_path, root)
    except ValueError:
        current["audio_path"] = audio_path
    store.upsert(current)
    return current


def _archived_branch_counts(entries: dict[str, dict[str, object]]) -> tuple[int, int]:
    subtitle_count = audio_count = 0
    for entry in entries.values():
        if entry.get("status") != "archived":
            continue
        if entry.get("audio_path"):
            audio_count += 1
        else:
            subtitle_count += 1
    return subtitle_count, audio_count


def _pilot_print_summary(
    subtitle_count: int, audio_count: int, failed: int, terminals: list[str]
) -> None:
    print(
        f"pilot branches: subtitle={subtitle_count}, audio-asr={audio_count}"
        + (f", failed={failed}" if failed else "")
    )
    for line in terminals:
        print(f"pilot terminal: {line}")


def _cmd_pilot(args: argparse.Namespace) -> int:
    from . import asr, audio, bili_client, subtitles
    from .manifest import ManifestStore
    from .meta_cursor import MetaCursorStore
    from .run_ledger import (
        RunLedger,
        build_run_record,
        compute_coverage_summary,
        utc_now_iso,
    )

    started_at = utc_now_iso()
    ledger = RunLedger(root=args.archive_root)
    cursor_store = MetaCursorStore(root=args.archive_root)
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    last_api_error_code: int | str | None = None
    selected_work_ids: list[str] | None = None

    def _record_exit(code: int) -> int:
        try:
            cursor_snapshot = cursor_store.load()
            coverage = compute_coverage_summary(store.load())
            rec = build_run_record(
                command="pilot",
                started_at=started_at,
                finished_at=utc_now_iso(),
                exit_code=code,
                mid=None,
                work_ids=selected_work_ids,
                pages_fetched=None,
                records_fetched=None,
                records_existing=len(entries),
                last_api_error_code=last_api_error_code,
                coverage_summary=coverage,
                cursor_snapshot=cursor_snapshot,
            )
            ledger.append(rec)
        except Exception:
            pass
        return code

    selected = _expand_selected_pages(entries, _pilot_select(entries, args.n))
    selected_work_ids = [_pilot_row_key(e) for e in selected] if selected else None
    print(
        f"pilot: selected {len(selected)} rows "
        f"(--n {args.n}; includes pagelist siblings)"
    )
    for entry in selected:
        print(
            f"{_pilot_row_key(entry)}: {entry.get('status')} "
            f"({entry.get('duration_s', 0)}s)"
        )
    leftover = [e for e in entries.values() if e.get("status") != "archived"]
    if not selected:
        if leftover:
            print("pilot: no processable rows in the manifest", file=sys.stderr)
            return _record_exit(1)
        if any(e.get("status") == "archived" for e in entries.values()):
            print("pilot: skip — all selected work already archived")
            return _record_exit(0)
        print("pilot: no processable rows in the manifest", file=sys.stderr)
        return _record_exit(1)

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    subtitle_count, audio_count = _archived_branch_counts(entries)
    failed = 0
    terminals: list[str] = []

    for index, entry in enumerate(selected):
        key = _pilot_row_key(entry)
        target = _identity_from_entry(entry, key)
        label = key
        status = entry.get("status")
        if status == "archived":
            continue
        try:
            if status not in _PILOT_SKIP_HARVEST:
                status = subtitles.harvest_subtitle(
                    client, target, store, args.archive_root
                )
            current = dict(store.get(key) or store.get_compatible(key) or entry)
            label = str(current.get("work_id") or key)
            if status == "subtitle_done":
                _pilot_archive_subtitle(store, args.archive_root, current)
                subtitle_count += 1
                terminals.append(f"{label}: archived (subtitle)")
                print(f"{label}: archived (subtitle)")
            elif status in {"needs_audio", "audio_ok"}:
                _pilot_archive_asr(
                    store, client, args.archive_root, current, target
                )
                audio_count += 1
                terminals.append(f"{label}: archived (asr)")
                print(f"{label}: archived (asr)")
            else:
                raise ValueError(f"unexpected status {status!r}")
        except asr.ASRDependencyError as exc:
            print(str(exc), file=sys.stderr)
            print(
                f"{label}: ASR dependency unavailable; row not archived",
                file=sys.stderr,
            )
            _pilot_print_summary(subtitle_count, audio_count, failed, terminals)
            return _record_exit(1)
        except bili_client.AmbiguousPageError:
            failed += 1
            print(f"{label}: multi-part video needs an explicit page",
                  file=sys.stderr)
        except bili_client.RiskBudgetExhausted as exc:
            failed += 1
            last_api_error_code = exc.last_code
            print(
                f"{label}: risk-control ceiling (last code {exc.last_code}); "
                f"stopping — re-run to resume.",
                file=sys.stderr,
            )
            _pilot_print_summary(subtitle_count, audio_count, failed, terminals)
            return _record_exit(2)
        except bili_client.APIResponseError as exc:
            failed += 1
            last_api_error_code = exc.code
            _record_api_error(store, key, exc.code)
            print(
                f"{label}: API response error (code {exc.code}); continuing.",
                file=sys.stderr,
            )
        except bili_client.GoneResponse as exc:
            failed += 1
            last_api_error_code = exc.code
            gone = dict(store.get(key) or store.get_compatible(key) or {})
            if gone.get("work_id"):
                gone["status"] = "gone"
                store.upsert(gone)
            print(
                f"{label}: terminal API response (code {exc.code}); marked gone.",
                file=sys.stderr,
            )
        except audio.NoAudioStreamError:
            failed += 1
            print(f"{label}: no audio stream available", file=sys.stderr)
        except bili_client.StreamDownloadError:
            failed += 1
            print(f"{label}: audio stream failed; continuing.", file=sys.stderr)
        except ValueError as exc:
            failed += 1
            msg = str(exc)
            if (
                "missing cid" in msg
                or "unresolved" in msg
                or "subtitle raw JSON missing" in msg
            ):
                print(f"{label}: {msg}", file=sys.stderr)
            else:
                print(f"{label}: {type(exc).__name__}", file=sys.stderr)
        except Exception as exc:
            failed += 1
            print(f"{label}: {type(exc).__name__}", file=sys.stderr)
        if index != len(selected) - 1:
            time.sleep(3.0)

    _pilot_print_summary(subtitle_count, audio_count, failed, terminals)
    if subtitle_count == 0 or audio_count == 0:
        missing = []
        if subtitle_count == 0:
            missing.append("subtitle")
        if audio_count == 0:
            missing.append("audio-asr")
        print(
            "pilot: missing branch coverage: " + ", ".join(missing),
            file=sys.stderr,
        )
        return _record_exit(1)
    if failed:
        return _record_exit(1)
    return _record_exit(0)


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
    if args.command == "runs":
        return _cmd_runs(args)
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
