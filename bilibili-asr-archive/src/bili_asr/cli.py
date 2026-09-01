"""Command-line interface for bili-asr."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

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
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
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
        "--max-audio-gb", type=float, default=10.0,
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
    )
    pilot.add_argument(
        "--max-duration-min", type=int, default=45,
        help="Exclude rows longer than this many minutes from selection (0 = unlimited)",
    )
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

    run_cmd = subparsers.add_parser(
        "run",
        help="Coordinate manifest rows through stages (complements pilot)",
    )
    run_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
             "(comma- or space-separated)",
    )
    run_cmd.add_argument(
        "--offline",
        action="store_true",
        help="Never call harvest/download (deterministic local stages only)",
    )
    run_cmd.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N rows (bounded batches)",
    )
    run_cmd.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
    )
    run_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    run_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )

    schedule_cmd = subparsers.add_parser(
        "schedule",
        help="Process a bounded sequential batch of the visible corpus",
    )
    schedule_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
             "(comma- or space-separated)",
    )
    schedule_cmd.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Process at most N matching rows (required explicit bound)",
    )
    schedule_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume only a matching risk-interrupted scheduler sidecar",
    )
    schedule_cmd.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
    )
    schedule_cmd.add_argument(
        "--allow-long-live",
        action="store_true",
        help=(
            "Opt in to multi-hour rows under the configured --max-audio-gb "
            "(cannot be 0). Default pending/failed selection keeps the "
            "45-minute short-video policy"
        ),
    )
    schedule_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    schedule_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )

    campaign_cmd = subparsers.add_parser(
        "campaign",
        help="Run a bounded campaign batch with aggregate checkpoint evidence",
    )
    campaign_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
        "(comma- or space-separated)",
    )
    campaign_cmd.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Process at most N matching rows (required explicit bound)",
    )
    campaign_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume only a matching risk-interrupted scheduler sidecar",
    )
    campaign_cmd.add_argument(
        "--offline",
        action="store_true",
        help="Never call harvest/download (deterministic local stages only)",
    )
    campaign_cmd.add_argument(
        "--max-audio-gb",
        type=float,
        default=10.0,
        help="Skip audio downloads that would push audio/ past this many GiB (0 = unlimited)",
    )
    campaign_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    campaign_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )

    search_cmd = subparsers.add_parser(
        "search",
        help="Search indexed completed transcripts using SQLite FTS5",
    )
    search_cmd.add_argument("query", help="Search query string")
    search_cmd.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N results (default: all)",
    )
    search_cmd.add_argument(
        "--rebuild", action="store_true",
        help="Force rebuilding the search index from the manifest",
    )
    search_cmd.add_argument(
        "--status", action="append", default=None,
        help="Filter by manifest status (repeatable or comma-separated)",
    )
    search_cmd.add_argument(
        "--source", action="append", default=None,
        help="Filter by source (e.g. subtitle, asr)",
    )
    search_cmd.add_argument(
        "--language", action="append", default=None,
        help="Filter by language (e.g. ai-zh, zh-CN)",
    )
    search_cmd.add_argument(
        "--scope", default=None,
        help="pending | failed | one or more work_id/bvid selectors",
    )
    search_cmd.add_argument(
        "--work-id", action="append", default=None,
        help="Filter by exact work_id or bvid (repeatable or comma-separated)",
    )
    search_cmd.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (text or json)",
    )
    search_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    coverage_cmd = subparsers.add_parser(
        "coverage", help="Print deterministic read-only coverage telemetry"
    )
    coverage_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    coverage_cmd.add_argument("--scope", default=None)
    coverage_cmd.add_argument("--format", choices=["json", "csv"], default="json")
    coverage_cmd.add_argument(
        "--trusted-local", action="store_true",
        help="Trust an operator-owned local archive root for unbounded inspection",
    )
    coverage_cmd.add_argument(
        "--quality",
        action="store_true",
        help="Include deterministic artifact quality validation signals",
    )

    integrity_cmd = subparsers.add_parser(
        "verify", help="Verify archive integrity without modifying files"
    )
    integrity_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    integrity_cmd.add_argument("--scope", default=None)
    integrity_cmd.add_argument(
        "--trusted-local", action="store_true",
        help="Trust an operator-owned local archive root for unbounded inspection",
    )
    integrity_cmd.add_argument("--format", choices=["json", "text"], default="json")

    recover_cmd = subparsers.add_parser(
        "recover", help="Explicitly audit named integrity defects (no requeue execution)"
    )
    recover_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    recover_cmd.add_argument("--work-id", action="append", default=None,
                             help="Exact work_id selector (repeatable; required for bounded recovery)")
    recover_cmd.add_argument("--defect-code", action="append", default=None,
                             help="Defect class selector (repeatable; bounded to reported defects)")
    recover_cmd.add_argument(
        "--limit", type=int, default=100,
        help="Limit must be positive; values above the maximum are capped at 100",
    )

    evaluate_concurrency = subparsers.add_parser(
        "evaluate-concurrency",
        help="Evaluate evidence only; runtime remains sequential with no daemon",
    )
    evaluate_concurrency.add_argument(
        "--evidence", required=True, help="Path to the JSON evidence mapping"
    )
    evaluate_concurrency.add_argument(
        "--thresholds", required=True, help="Path to the explicit JSON threshold mapping"
    )

    export_cmd = subparsers.add_parser(
        "export",
        help="Export manifest metadata to JSON or CSV format",
    )
    export_cmd.add_argument(
        "--format",
        choices=["json", "csv"],
        required=True,
        help="Export format (json or csv)",
    )
    export_cmd.add_argument(
        "--out",
        default=None,
        help="Output file path (default: stdout)",
    )
    export_cmd.add_argument(
        "--status",
        action="append",
        default=None,
        help="Filter by manifest status (repeatable or comma-separated)",
    )
    export_cmd.add_argument(
        "--with-text",
        action="store_true",
        help="Include transcript text body in output",
    )
    export_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
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
    from .page_identity import identity_from_entry

    return identity_from_entry(entry, key)


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
    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
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
    try:
        store.migrate_legacy_rows(
            pages_for,
            archive_root=args.archive_root,
            coalesce_existing_page=True,
        )
    except Exception:
        print("fetch-meta: legacy migration failed", file=sys.stderr)
        return 1
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
    risk_interrupted = False
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
            risk_interrupted = True
            break
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
    if risk_interrupted:
        return 2
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
    risk_interrupted = False
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
            from .path_policy import confined_audio_path
            try:
                returned_relative = os.path.relpath(
                    os.fspath(final), os.fspath(args.archive_root)
                )
            except (OSError, ValueError, TypeError):
                returned_relative = ""
            confined = confined_audio_path(
                args.archive_root, returned_relative, require_exists=True
            )
            if confined is None:
                raise ValueError("invalid audio path")
            final = os.path.relpath(confined, os.fspath(args.archive_root))
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
            risk_interrupted = True
            break
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
    if risk_interrupted:
        return 2
    return 1 if failed else 0


def _cmd_status(args: argparse.Namespace) -> int:
    from collections import Counter
    from .manifest import ManifestStore
    from .run_ledger import RunLedger, format_coverage_summary, format_cursor_summary

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
    records = RunLedger(root=args.archive_root).load()
    if not records:
        print("runs: 0")
    else:
        print(f"runs: {len(records)}")
        latest = records[-1]
        print(f"latest run: {latest.get('run_id', 'unknown')} ({latest.get('command', 'unknown')}, exit {latest.get('exit_code', '?')}, {latest.get('finished_at') or latest.get('started_at') or ''})")
        print(f"latest cursor: {format_cursor_summary(latest.get('cursor_snapshot'))}")
        print(f"latest coverage: {format_coverage_summary(latest.get('coverage_summary'))}")
    return 0


def _cmd_coverage_quality(args: argparse.Namespace) -> int:
    import csv
    import io
    from pathlib import Path
    from .quality import QualityAnalyzer, REASON_CODES
    from .coverage_report import _select_scope, _diagnostic_rows
    from .sidecar_projection import (
        ReaderPolicy,
        project_attempt_records,
        project_manifest_records,
    )

    root = Path(args.archive_root).resolve()
    diagnostics: set[tuple[str, str]] = set()
    policy = (
        ReaderPolicy(mode="trusted_archive")
        if getattr(args, "trusted_local", False)
        else None
    )
    manifest, manifest_state, manifest_diagnostics = project_manifest_records(
        root / "manifest" / "manifest.jsonl", policy=policy
    )
    diagnostics.update(
        (
            "sidecar_record_limit" if code.endswith("row_limit_exceeded") else
            "sidecar_byte_limit" if code.endswith("byte_limit_exceeded") else code,
            "manifest",
        )
        for code in manifest_diagnostics
    )
    attempts, _attempts_state, attempt_diagnostics = project_attempt_records(
        root / "coordinator" / "attempts.jsonl", policy=policy
    )
    diagnostics.update(
        (
            "sidecar_record_limit" if code.endswith("row_limit_exceeded") else
            "sidecar_byte_limit" if code.endswith("byte_limit_exceeded") else
            "sidecar_malformed" if code == "truncated_attempts_line" else code,
            "attempt",
        )
        for code in attempt_diagnostics
    )
    selected, scope_state = _select_scope(manifest, attempts, args.scope)
    if scope_state == "unavailable":
        diagnostics.add(("unknown_scope", "scope"))

    denominator_available = (
        manifest_state == "available" and scope_state == "available"
    )
    rows: list[dict[str, object]] = []
    reason_counts: dict[str, int] = {code: 0 for code in REASON_CODES}
    total_cues = 0
    valid_work_items = 0
    has_defects = False

    analyzer = QualityAnalyzer()
    for work_id, entry in sorted(selected.items()):
        result = analyzer.analyze(entry, root)
        row_dict: dict[str, object] = {
            "work_id": work_id,
            "source": result.source,
            "language": result.language,
            "status": result.status,
            "cue_count": result.cue_count,
            "artifact_count": result.artifact_count,
            "reasons": list(result.reasons),
            "diagnostics": list(result.diagnostics),
        }
        rows.append(row_dict)
        for r in result.reasons:
            reason_counts[r] = reason_counts.get(r, 0) + 1
        total_cues += result.cue_count
        if not result.reasons and not result.diagnostics:
            valid_work_items += 1
        else:
            has_defects = True

    diagnostic_rows = _diagnostic_rows(diagnostics)
    summary = {
        "total_work_items": len(rows) if denominator_available else 0,
        "valid_work_items": valid_work_items if denominator_available else 0,
        "total_cues": total_cues if denominator_available else 0,
        **reason_counts,
    }

    quality_data = {
        "schema_version": "coverage-quality-v1",
        "scope": args.scope,
        "denominator": {
            "unit": "work_items",
            "count": len(rows) if denominator_available else None,
            "state": "available" if denominator_available else "unavailable",
            "source": "manifest_snapshot",
        },
        "summary": summary,
        "rows": rows,
        "diagnostics": diagnostic_rows,
    }

    if args.format == "json":
        sys.stdout.write(
            json.dumps(
                quality_data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        sys.stdout.write("\n")
    else:
        columns = (
            "schema_version",
            "scope",
            "denominator_unit",
            "denominator_count",
            "denominator_state",
            "denominator_source",
            "work_id",
            "source",
            "language",
            "status",
            "cue_count",
            "artifact_count",
            "reasons",
            "diagnostics",
        )
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        csv_rows = rows or [
            {
                "work_id": "",
                "source": "",
                "language": "",
                "status": "",
                "cue_count": "",
                "artifact_count": "",
                "reasons": [],
                "diagnostics": [],
            }
        ]
        denom = quality_data["denominator"]
        for r in csv_rows:
            writer.writerow(
                {
                    "schema_version": quality_data["schema_version"],
                    "scope": quality_data["scope"] or "",
                    "denominator_unit": denom["unit"],
                    "denominator_count": (
                        denom["count"] if denom["count"] is not None else ""
                    ),
                    "denominator_state": denom["state"],
                    "denominator_source": denom["source"],
                    "work_id": r.get("work_id", ""),
                    "source": r.get("source") or "",
                    "language": r.get("language") or "",
                    "status": r.get("status") or "",
                    "cue_count": r.get("cue_count", ""),
                    "artifact_count": r.get("artifact_count", ""),
                    "reasons": ";".join(r.get("reasons", [])),
                    "diagnostics": ";".join(r.get("diagnostics", [])),
                }
            )
        sys.stdout.write(output.getvalue())

    return 1 if (diagnostic_rows or has_defects) else 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    from .coverage_report import CoverageReport
    try:
        if getattr(args, "quality", False):
            return _cmd_coverage_quality(args)
        from .sidecar_projection import ReaderPolicy
        policy = ReaderPolicy(mode="trusted_archive") if getattr(args, "trusted_local", False) else None
        report = CoverageReport.build(args.archive_root, scope=args.scope, policy=policy)
        sys.stdout.write(report.to_json() if args.format == "json" else report.to_csv())
        if args.format == "json":
            sys.stdout.write("\n")
        return 1 if report.data["diagnostics"] else 0
    except Exception:
        print("coverage: diagnostic coverage_report_unavailable", file=sys.stderr)
        return 1


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


def _pilot_select(
    entries: dict[str, dict[str, object]], n: int,
    max_duration_min: int = 0,
) -> list[dict[str, object]]:
    """Select a small mixed pilot while guaranteeing both branches when possible."""
    if n < 1:
        return []
    from .audio_budget import max_duration_exceeded

    processable = [
        e for e in _pilot_processable(entries)
        if not max_duration_exceeded(e, max_duration_min)
    ]
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
    max_duration_min: int = 0,
) -> list[dict[str, object]]:
    """Include duration-eligible pagelist siblings for selected bvids."""
    if not selected:
        return selected
    from .audio_budget import max_duration_exceeded

    chosen = {_pilot_row_key(e) for e in selected}
    bvids = {str(e.get("bvid") or "") for e in selected}
    extras = [
        e for e in _pilot_processable(entries)
        if str(e.get("bvid") or "") in bvids
        and _pilot_row_key(e) not in chosen
        and not max_duration_exceeded(e, max_duration_min)
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
        status = entry.get("status")
        subtitle_data = (
            _subtitle_segments(args.archive_root, entry)
            if status == "subtitle_done"
            else None
        )
        try:
            if status == "subtitle_done" and subtitle_data is None:
                failed += 1
                print(f"{label}: skipped (missing_subtitle_raw)", file=sys.stderr)
                continue
            if subtitle_data is not None:
                segments, raw = subtitle_data
            else:
                source = "asr"
                stem = archive.archive_stem(entry)
                from .path_policy import confined_audio_file
                declared = entry.get("audio_path") or os.path.join("audio", f"{stem}.m4a")
                with confined_audio_file(args.archive_root, os.fspath(declared)) as safe_audio:
                    segments = asr.transcribe(safe_audio)
            paths = archive.write_archive(args.archive_root, entry, segments, source=source, raw=raw)
            if not archive.archive_bundle_complete(args.archive_root, paths):
                raise ValueError("archive bundle incomplete")
            updated = dict(store.get(key) or entry)
            updated.update(paths)
            updated["status"] = "archived"
            store.upsert(updated)
            _reclaim_after_archive(args.archive_root, updated)
            ok += 1
            print(f"{label}: archived ({source})")
        except asr.ASRDependencyError:
            failed += 1
            print(f"{label}: ASR dependency unavailable", file=sys.stderr)
        except Exception:
            failed += 1
            print(f"{label}: archive failed", file=sys.stderr)
    print(f"asr: {ok} archived" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


def _reclaim_after_archive(root: str, entry: dict[str, object]) -> None:
    """Best-effort audio reclaim once a row is archived (plan: audio-reclaim)."""
    from .audio_reclaim import reclaim_audio

    try:
        reclaim_audio(root, entry)
    except (OSError, ValueError):
        pass  # per-item non-fatal: transcripts exist; row stays archived


def _pilot_archive_subtitle(store, root: str, entry: dict[str, object]) -> dict[str, object]:
    from . import archive

    data = _subtitle_segments(root, entry)
    if data is None:
        raise ValueError(f"{_pilot_row_key(entry)}: subtitle raw JSON missing")
    segments, raw = data
    paths = archive.write_archive(root, entry, segments, source="subtitle", raw=raw)
    if not archive.archive_bundle_complete(root, paths):
        raise ValueError("archive bundle incomplete")
    updated = dict(entry)
    updated.update(paths)
    updated["status"] = "archived"
    store.upsert(updated)
    _reclaim_after_archive(root, updated)
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
    existing_audio_path: str | None = None
    from .path_policy import confined_audio_file, confined_audio_path
    if existing_rel:
        existing_audio_path_obj = confined_audio_path(root, os.fspath(existing_rel), require_exists=True)
        if existing_audio_path_obj is not None and existing_audio_path_obj.stat().st_size > 0:
            existing_audio_path = str(existing_audio_path_obj)
    if existing_audio_path is not None:
        audio_path = existing_audio_path
    else:
        downloaded = Path(os.fspath(audio.download_audio(client, target, out_path, store=store)))
        try:
            downloaded_relative = downloaded.resolve().relative_to(Path(root).resolve()).as_posix()
        except (OSError, ValueError):
            raise ValueError("invalid audio path")
        audio_path_obj = confined_audio_path(root, downloaded_relative, require_exists=True)
        if audio_path_obj is None or audio_path_obj.stat().st_size <= 0:
            raise ValueError("invalid audio path")
        audio_path = str(audio_path_obj)
    declared_audio = os.path.relpath(audio_path, root)
    with confined_audio_file(root, declared_audio) as safe_audio:
        segments = asr.transcribe(safe_audio)
    current = dict(store.get(target.work_id) or entry)
    paths = archive.write_archive(root, current, segments, source="asr")
    if not archive.archive_bundle_complete(root, paths):
        raise ValueError("archive bundle incomplete")
    current.update(paths)
    current["status"] = "archived"
    try:
        current["audio_path"] = os.path.relpath(audio_path, root)
    except ValueError:
        current["audio_path"] = audio_path
    store.upsert(current)
    _reclaim_after_archive(root, current)
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
    batch_subtitle_count: int,
    batch_audio_count: int,
    coverage_subtitle_count: int,
    coverage_audio_count: int,
    failed: int,
    terminals: list[str],
) -> None:
    print(
        "pilot batch branches: "
        f"subtitle={batch_subtitle_count}, audio-asr={batch_audio_count}"
        + (f", failed={failed}" if failed else "")
    )
    print(
        "pilot coverage branches: "
        f"subtitle={coverage_subtitle_count}, audio-asr={coverage_audio_count}"
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

    selected = _expand_selected_pages(
        entries,
        _pilot_select(entries, args.n, args.max_duration_min),
        args.max_duration_min,
    )
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
    coverage_subtitle_count, coverage_audio_count = _archived_branch_counts(entries)
    batch_subtitle_count = batch_audio_count = 0
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
                batch_subtitle_count += 1
                coverage_subtitle_count += 1
                terminals.append(f"{label}: archived (subtitle)")
                print(f"{label}: archived (subtitle)")
            elif status in {"needs_audio", "audio_ok"}:
                from .audio_budget import (
                    SKIP_REASON,
                    audio_cap_bytes,
                    would_exceed_budget,
                )

                max_bytes = audio_cap_bytes(args.max_audio_gb)
                current_row = dict(store.get(key) or current)
                if (
                    status == "needs_audio"
                    and would_exceed_budget(
                        args.archive_root, current_row, max_bytes
                    )
                ):
                    failed += 1
                    print(
                        f"{label}: skipped ({SKIP_REASON}); "
                        "audio-dir budget cap reached",
                        file=sys.stderr,
                    )
                    continue
                _pilot_archive_asr(
                    store, client, args.archive_root, current, target
                )
                batch_audio_count += 1
                coverage_audio_count += 1
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
            _pilot_print_summary(
                batch_subtitle_count,
                batch_audio_count,
                coverage_subtitle_count,
                coverage_audio_count,
                failed,
                terminals,
            )
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
            _pilot_print_summary(
                batch_subtitle_count,
                batch_audio_count,
                coverage_subtitle_count,
                coverage_audio_count,
                failed,
                terminals,
            )
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

    _pilot_print_summary(
        batch_subtitle_count,
        batch_audio_count,
        coverage_subtitle_count,
        coverage_audio_count,
        failed,
        terminals,
    )
    if coverage_subtitle_count == 0 or coverage_audio_count == 0:
        missing = []
        if coverage_subtitle_count == 0:
            missing.append("subtitle")
        if coverage_audio_count == 0:
            missing.append("audio-asr")
        print(
            "pilot: missing branch coverage: " + ", ".join(missing),
            file=sys.stderr,
        )
        return _record_exit(1)
    if failed:
        return _record_exit(1)
    return _record_exit(0)


def _run_scope_rows(store, entries: dict, scope: str):
    """Resolve --scope to processable (key, entry) rows.

    Returns (rows, error) where error is a message string when the scope
    could not be resolved at all.
    """
    from .manifest import VALID_STATUSES

    if scope == "pending":
        return (
            [
                (key, e)
                for key, e in sorted(entries.items())
                if e.get("status") in VALID_STATUSES - {"archived", "gone"}
                and not _is_excluded(e)
            ],
            None,
        )
    if scope == "failed":
        # failed scope: rows with a recorded failed stage attempt (qc1-S2:
        # definition lives next to the ledger in RunCoordinator).
        from .coordinator import RunCoordinator

        failed = RunCoordinator(store.root, store).failed_work_ids()
        rows = [
            (key, e)
            for key, e in sorted(entries.items())
            if (str(e.get("work_id") or key) in failed
                or str(e.get("bvid") or "") in failed)
            and not _is_excluded(e)
            and e.get("status") not in {"archived", "gone"}
        ]
        return rows, None

    selectors = [s for part in scope.split(",") for s in part.split() if s]
    rows: list[tuple[str, dict]] = []
    for selector in selectors:
        todo = _todo_for_bvid(store, selector, entries)
        if todo is None:
            return None, (
                f"{selector}: multi-part video needs an explicit page"
            )
        if not todo:
            return None, f"{selector}: unresolved; not assigned to a page"
        rows.extend(todo)
    if not selectors:
        return None, "empty --scope"
    return rows, None

def _cmd_campaign(args: argparse.Namespace) -> int:
    from . import bili_client
    from .audio_budget import audio_cap_bytes
    from .campaign import CampaignRunner
    from .coordinator import ArchiveBusyError

    try:
        client = None
        if not args.offline:
            client = bili_client.BiliClient(sessdata=_resolve_sessdata(args))
        runner = CampaignRunner(
            args.archive_root,
            client=client,
            offline=args.offline,
            max_audio_bytes=audio_cap_bytes(args.max_audio_gb),
            sleep=time.sleep,
            scope_rows=_run_scope_rows,
        )
        summary = runner.run(args.scope, args.limit, resume=args.resume)
    except ArchiveBusyError:
        print("campaign: archive_busy", file=sys.stderr)
        return 1
    except Exception:
        # Never expose runtime payloads, credentials, URLs, or traces.
        print("campaign: invalid configuration or execution failure", file=sys.stderr)
        return 1
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
    return summary.exit_code

def _cmd_run(args: argparse.Namespace) -> int:
    from . import bili_client
    from .coordinator import ArchiveBusyError, RunCoordinator, archive_writer
    from .manifest import ManifestStore
    from .run_ledger import RunLedger, build_run_record, compute_coverage_summary, utc_now_iso
    from .audio_budget import audio_cap_bytes

    started_at = utc_now_iso()
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    if args.limit is not None and args.limit <= 0:
        print("run: --limit must be a positive integer", file=sys.stderr)
        return 1
    rows, error = _run_scope_rows(store, entries, args.scope)
    if error:
        print(f"run: {error}", file=sys.stderr)
        return 1
    if args.limit is not None:
        rows = rows[: args.limit]
    client = None
    if not args.offline:
        client = bili_client.BiliClient(sessdata=_resolve_sessdata(args))
    coord = RunCoordinator(args.archive_root, store, client=client, offline=args.offline,
                           max_audio_bytes=audio_cap_bytes(args.max_audio_gb))
    print(f"run: scope={args.scope} selected {len(rows)} row(s)" + (" [offline]" if args.offline else ""))
    for key, entry in rows:
        print(f"  {entry.get('work_id') or key}: {entry.get('status')}")
    try:
        with archive_writer(args.archive_root):
            summary = coord.run_batch(rows)
            ok = sum(1 for r in summary.results if r.ok)
            skipped = summary.skipped_rows
            failed = summary.failed
            for r in summary.results:
                if r.ok:
                    print(f"{r.work_id}: {r.final_status}")
            for r in failed:
                codes = ", ".join(str(c) for c in r.failure_codes) or "unknown"
                print(f"run: {r.work_id}: failed ({codes})", file=sys.stderr)
            for r in skipped:
                print(f"run: {r.work_id}: skipped ({r.skip_reason or 'unknown'})")
            exit_code = 2 if summary.risk_interrupted else (0 if summary.fully_processed else 1)
            if summary.risk_interrupted:
                print("run: risk-control ceiling; stopping — re-run to resume.", file=sys.stderr)
            print(f"run: {ok} completed, {len(skipped)} skipped" +
                  (f", {len(failed)} failed" if failed else "") +
                  (", scope not fully processed" if exit_code == 1 else ""))
            try:
                ledger = RunLedger(root=args.archive_root)
                ledger.append(build_run_record(command="run", started_at=started_at,
                    finished_at=utc_now_iso(), exit_code=exit_code, mid=None,
                    work_ids=[r.work_id for r in summary.results] or None,
                    records_existing=len(entries), coverage_summary=compute_coverage_summary(store.load())))
            except Exception:
                pass
            return exit_code
    except ArchiveBusyError:
        print("run: archive_busy", file=sys.stderr)
        return 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    from . import bili_client
    from .coordinator import ArchiveBusyError, RunCoordinator, archive_writer
    from .manifest import ManifestStore
    from .meta_cursor import MetaCursorStore
    from .run_ledger import (
        RunLedger,
        build_run_record,
        compute_coverage_summary,
        format_coverage_summary,
        format_cursor_summary,
        utc_now_iso,
    )
    from .audio_budget import audio_cap_bytes, audio_dir_usage_bytes
    from .long_live import (
        apply_long_live_policy,
        campaign_plan,
        format_campaign_plan,
        is_long_live,
        refuse_disabled_audio_cap,
    )
    from .scheduler import (
        SchedulerStore,
        classify_batch_state,
        settled_processed_ids,
        terminal_resume_ids,
    )

    started_at = utc_now_iso()
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    cursor_store = MetaCursorStore(root=args.archive_root)
    sched_store = SchedulerStore(root=args.archive_root)
    if args.limit is None or args.limit <= 0:
        print("schedule: --limit must be a positive integer", file=sys.stderr)
        return 1
    if args.allow_long_live:
        cap_error = refuse_disabled_audio_cap(args.max_audio_gb)
        if cap_error:
            print(f"schedule: {cap_error}", file=sys.stderr)
            return 1
    rows, error = _run_scope_rows(store, entries, args.scope)
    if error:
        print(f"schedule: {error}", file=sys.stderr)
        return 1

    skip_ids: list[str] | None = None
    matching_resume = False
    if args.resume:
        lookup = sched_store.inspect_resume(
            args.scope, allow_long_live=args.allow_long_live
        )
        if lookup.diagnostic:
            if lookup.refuse:
                print(
                    f"schedule: --resume refused ({lookup.diagnostic})",
                    file=sys.stderr,
                )
                return 1
            print(
                f"schedule: --resume ignored ({lookup.diagnostic})",
                file=sys.stderr,
            )
        if lookup.processed_ids is not None:
            matching_resume = True
            skip_ids = terminal_resume_ids(lookup.processed_ids, entries)
            skip = set(skip_ids)
            rows = [
                (key, entry)
                for key, entry in rows
                if str(entry.get("work_id") or key) not in skip
            ]

    rows, held, policy_error = apply_long_live_policy(
        rows,
        allow_long_live=args.allow_long_live,
        explicit_scope=args.scope not in {"pending", "failed"},
    )
    if policy_error:
        print(f"schedule: {policy_error}", file=sys.stderr)
        return 1
    if matching_resume and not args.allow_long_live and not rows and held:
        print(
            "schedule: --resume refused (risk-stopped long-duration "
            "row requires --allow-long-live)",
            file=sys.stderr,
        )
        return 1

    matching = len(rows)
    truncated = matching > args.limit or held > 0
    rows = rows[: args.limit]

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    max_audio_bytes = audio_cap_bytes(args.max_audio_gb)
    coord = RunCoordinator(
        args.archive_root,
        store,
        client=client,
        offline=False,
        max_audio_bytes=max_audio_bytes,
        sleep=time.sleep,
    )
    print(
        f"schedule: scope={args.scope} limit={args.limit} "
        f"selected {len(rows)} row(s) ({matching} matching)"
    )
    for key, entry in rows:
        print(f"  {entry.get('work_id') or key}: {entry.get('status')}")
    if held:
        print(
            f"schedule: {held} long-duration row(s) held; "
            "re-run with --allow-long-live"
        )
    if args.allow_long_live:
        usage_snapshot = audio_dir_usage_bytes(args.archive_root)
        for _key, entry in rows:
            if is_long_live(entry):
                print(format_campaign_plan(
                    campaign_plan(
                        args.archive_root,
                        entry,
                        max_audio_bytes,
                        usage_bytes=usage_snapshot,
                    )
                ))

    try:
        with archive_writer(args.archive_root):
            summary = coord.run_batch(rows)
            if args.allow_long_live:
                after = audio_dir_usage_bytes(args.archive_root)
                print(f"schedule: long-live peak audio/ bytes={coord.audio_peak_bytes}")
                print(f"schedule: long-live audio/ after bytes={after}")
            batch_state = classify_batch_state(
                risk_interrupted=summary.risk_interrupted,
                truncated=truncated,
            )

            previous = list(skip_ids or [])
            settled = previous + settled_processed_ids(
                summary.results, risk_interrupted=summary.risk_interrupted
            )
            processed: list[str] = []
            seen: set[str] = set()
            for work_id in settled:
                if work_id not in seen:
                    seen.add(work_id)
                    processed.append(work_id)

            last_api_error_code: int | str | None = None
            if summary.risk_interrupted and summary.results:
                codes = summary.results[-1].failure_codes
                if codes:
                    last_api_error_code = codes[-1]

            persisted = False
            try:
                sched_store.replace_atomic(
                    {
                        "scope": args.scope,
                        "limit": args.limit,
                        "state": batch_state,
                        "processed_work_ids": processed,
                        "last_api_error_code": last_api_error_code,
                        "allow_long_live": bool(args.allow_long_live),
                        "updated_at": utc_now_iso(),
                    }
                )
                persisted = True
            except Exception as exc:
                print(
                    "schedule: failed to persist scheduler.json "
                    f"({type(exc).__name__})",
                    file=sys.stderr,
                )

            ok = sum(1 for result in summary.results if result.ok)
            skipped = summary.skipped_rows
            failed = summary.failed
            for result in summary.results:
                if result.ok:
                    print(f"{result.work_id}: {result.final_status}")
            for result in failed:
                codes = ", ".join(
                    str(code) for code in result.failure_codes
                ) or "unknown"
                print(
                    f"schedule: {result.work_id}: failed ({codes})",
                    file=sys.stderr,
                )
            for result in skipped:
                print(
                    f"schedule: {result.work_id}: skipped "
                    f"({result.skip_reason or 'unknown'})"
                )

            exit_code = 0
            if summary.risk_interrupted:
                if persisted:
                    print(
                        "schedule: risk-control ceiling; stopping — "
                        "re-run with --resume.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "schedule: risk-control ceiling; scheduler.json "
                        "was not persisted.",
                        file=sys.stderr,
                    )
                exit_code = 2
            elif not summary.fully_processed:
                exit_code = 1
            if not persisted and exit_code != 2:
                exit_code = 1

            coverage = compute_coverage_summary(store.load())
            cursor_snapshot = cursor_store.load()
            if persisted:
                print(f"schedule: batch={batch_state}")
            else:
                print(f"schedule: batch={batch_state} (not persisted)")
            print(f"enumeration: {format_cursor_summary(cursor_snapshot)}")
            print(f"coverage: [{format_coverage_summary(coverage)}]")
            print(
                f"schedule: {ok} completed, {len(skipped)} skipped"
                + (f", {len(failed)} failed" if failed else "")
                + (", scope not fully processed" if exit_code == 1 else "")
            )

            ledger = RunLedger(root=args.archive_root)
            try:
                record = build_run_record(
                    command="schedule",
                    started_at=started_at,
                    finished_at=utc_now_iso(),
                    exit_code=exit_code,
                    mid=None,
                    work_ids=[result.work_id for result in summary.results] or None,
                    records_existing=len(entries),
                    last_api_error_code=last_api_error_code,
                    coverage_summary=coverage,
                    cursor_snapshot=cursor_snapshot,
                )
                ledger.append(record)
            except Exception:
                pass
            return exit_code
    except ArchiveBusyError:
        print("schedule: archive_busy", file=sys.stderr)
        return 1


def _cmd_search(args: argparse.Namespace) -> int:
    from .manifest import VALID_STATUSES
    from .search_index import FTS5UnavailableError, SearchQuery, search

    if args.limit is not None and args.limit <= 0:
        print("search: --limit must be a positive integer", file=sys.stderr)
        return 1

    status_filter = _parse_status_filter(args.status)
    if status_filter is not None:
        invalid = status_filter - VALID_STATUSES
        if invalid:
            print(
                f"search: invalid status filter: {sorted(invalid)}; "
                f"valid statuses: {sorted(VALID_STATUSES)}",
                file=sys.stderr,
            )
            return 1

    source_filter = _parse_status_filter(args.source)
    lang_filter = _parse_status_filter(args.language)
    work_id_filter = _parse_status_filter(args.work_id)

    sq = SearchQuery(
        query=args.query,
        status=status_filter,
        source=source_filter,
        language=lang_filter,
        scope=args.scope,
        work_id=work_id_filter,
        limit=args.limit,
        rebuild=args.rebuild,
    )

    try:
        results = search(archive_root=args.archive_root, query=sq)
    except FTS5UnavailableError as exc:
        print(f"search: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("search: unexpected error", file=sys.stderr)
        return 1

    if not results:
        print(
            f"search: no matching transcripts found for {args.query!r}",
            file=sys.stderr,
        )
        return 1

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


def _cmd_export(args: argparse.Namespace) -> int:
    from .export import export_manifest
    from .manifest import VALID_STATUSES

    status_filter = _parse_status_filter(args.status)
    if status_filter is not None:
        invalid = status_filter - VALID_STATUSES
        if invalid:
            print(
                f"export: invalid status filter: {sorted(invalid)}; "
                f"valid statuses: {sorted(VALID_STATUSES)}",
                file=sys.stderr,
            )
            return 1

    try:
        content = export_manifest(
            archive_root=args.archive_root,
            fmt=args.format,
            out_path=args.out,
            status_filter=status_filter,
            with_text=args.with_text,
        )
        if not args.out or args.out == "-":
            sys.stdout.write(content + ("\n" if not content.endswith("\n") else ""))
            sys.stdout.flush()
    except Exception:
        print("export: unexpected error", file=sys.stderr)
        return 1
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from .integrity import IntegrityVerifier
    from .sidecar_projection import ReaderPolicy
    policy = ReaderPolicy(mode="trusted_archive") if getattr(args, "trusted_local", False) else None
    report = IntegrityVerifier().verify(Path(args.archive_root), scope=args.scope, policy=policy)
    payload = report.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"checked: {payload['checked']}")
        print(f"defects: {payload['defect_count']}")
        for defect in payload["defects"]:
            print(f"{defect['work_id']}: {defect['code']}")
        for diagnostic in payload["diagnostics"]:
            print(f"diagnostic: {diagnostic}")
    return 0 if not payload["defects"] and not payload["diagnostics"] else 1


def _cmd_recover(args: argparse.Namespace) -> int:
    from .integrity import IntegrityVerifier
    payload = IntegrityVerifier.recover(
        Path(args.archive_root), work_ids=args.work_id,
        defect_codes=args.defect_code, limit=args.limit,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("ok") else 1


_MAX_CONCURRENCY_INPUT_BYTES = 1_048_576


class _ConcurrencyInputError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _read_concurrency_json_object(path: str) -> dict[str, object]:
    from collections.abc import Mapping

    file_path = Path(path)
    try:
        if not file_path.exists():
            raise _ConcurrencyInputError("input_file_missing")
        if not file_path.is_file():
            raise _ConcurrencyInputError("input_file_not_regular")
        with file_path.open("rb") as input_file:
            payload = input_file.read(_MAX_CONCURRENCY_INPUT_BYTES + 1)
    except _ConcurrencyInputError:
        raise
    except OSError:
        raise _ConcurrencyInputError("input_file_unreadable") from None

    if len(payload) > _MAX_CONCURRENCY_INPUT_BYTES:
        raise _ConcurrencyInputError("input_file_oversized")
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _ConcurrencyInputError("input_invalid_utf8") from None
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError:
        raise _ConcurrencyInputError("input_malformed_json") from None
    if not isinstance(value, Mapping):
        raise _ConcurrencyInputError("input_non_object_json")
    return dict(value)


def _write_concurrency_error(error_code: str) -> None:
    payload = {
        "error_code": error_code,
        "operating_mode": "sequential-no-daemon",
    }
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )


def _cmd_evaluate_concurrency(args: argparse.Namespace) -> int:
    from .concurrency_gate import ConcurrencyGate

    try:
        evidence = _read_concurrency_json_object(args.evidence)
        thresholds = _read_concurrency_json_object(args.thresholds)
    except _ConcurrencyInputError as exc:
        _write_concurrency_error(exc.error_code)
        return 1

    try:
        result = ConcurrencyGate.evaluate(evidence, thresholds)
    except Exception:
        _write_concurrency_error("evaluation_failure")
        return 1

    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result.ok else 1


_ARCHIVE_WRITER_COMMANDS = frozenset({
    "fetch-meta",
    "recover",
    "asr",
    "pilot",
    "probe-subs",
    "harvest-subs",
    "download-audio",
    "run",
    "campaign",
    "schedule",
})


def _dispatch_command(args: argparse.Namespace) -> int:
    if args.command == "fetch-meta":
        return _cmd_fetch_meta(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "coverage":
        return _cmd_coverage(args)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "recover":
        return _cmd_recover(args)
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
    if args.command == "search":
        return _cmd_search(args)
    if args.command == "evaluate-concurrency":
        return _cmd_evaluate_concurrency(args)
    if args.command == "export":
        return _cmd_export(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "campaign":
        return _cmd_campaign(args)
    if args.command == "schedule":
        return _cmd_schedule(args)
    raise ValueError(f"command {args.command!r} is not implemented")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command in _ARCHIVE_WRITER_COMMANDS:
        from .coordinator import ArchiveBusyError, archive_writer

        try:
            with archive_writer(args.archive_root):
                return _dispatch_command(args)
        except ArchiveBusyError:
            print(f"{args.command}: archive_busy", file=sys.stderr)
            return 1
    return _dispatch_command(args)



if __name__ == "__main__":
    raise SystemExit(main())
