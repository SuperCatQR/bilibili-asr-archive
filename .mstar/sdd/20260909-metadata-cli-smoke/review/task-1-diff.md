# Task 1 Diff — 20260909-metadata-cli-smoke

Base: `18b6353`
Head: `849c046`

```diff
diff --git a/bilibili-asr-archive/src/bili_asr/cli.py b/bilibili-asr-archive/src/bili_asr/cli.py
index baf8131..bcb9f56 100644
--- a/bilibili-asr-archive/src/bili_asr/cli.py
+++ b/bilibili-asr-archive/src/bili_asr/cli.py
@@ -5,11 +5,22 @@ from __future__ import annotations
 import argparse
 import json
 import os
+import sqlite3
 import sys
 import time
 from pathlib import Path
 
-DEFAULT_MID = 23191782
+from .config import (
+    ARCHIVE_DATABASE_NAME,
+    DEFAULT_MID,
+    DEFAULT_PAGE_LIMIT,
+    SESSDATA_ENV_VAR,
+    MetadataConfigError,
+    load_metadata_config,
+    redact_sessdata,
+    resolve_sessdata,
+)
+
 DEFAULT_ARCHIVE_ROOT = os.path.join("archive")
 
 
@@ -37,12 +48,18 @@ def build_parser() -> argparse.ArgumentParser:
 
     fetch_meta = subparsers.add_parser(
         "fetch-meta",
-        help="Enumerate videos for a mid and write the manifest ledger",
+        help="Collect video metadata for a user into the SQLite archive database",
     )
     fetch_meta.add_argument("--mid", type=int, default=DEFAULT_MID,
                             help="Bilibili user mid")
-    fetch_meta.add_argument(
-        "--resume", action="store_true", help="Resume without duplicating bvids"
+    resume_or_start = fetch_meta.add_mutually_exclusive_group()
+    resume_or_start.add_argument(
+        "--resume", action="store_true",
+        help="Resume from the stored cursor; fails when none exists",
+    )
+    resume_or_start.add_argument(
+        "--start-page", type=int, default=None,
+        help="Explicit one-based start page (overrides the stored cursor)",
     )
     fetch_meta.add_argument(
         "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
@@ -54,7 +71,7 @@ def build_parser() -> argparse.ArgumentParser:
     )
     fetch_meta.add_argument(
         "--limit-pages", type=int, default=None,
-        help="Stop after N pages (smoke runs)",
+        help=f"Stop after collecting N pages (default: {DEFAULT_PAGE_LIMIT})",
     )
 
     status = subparsers.add_parser("status", help="Print manifest status summary")
@@ -456,315 +473,163 @@ def _is_excluded(entry: dict | None) -> bool:
     )
 
 
-def _cached_page_lister(client):
-    """Reuse pagelist results and pace calls like series fetch."""
-    cache: dict = {}
+_MAX_DISPLAYED_PENDING_PARTS = 20
 
-    def pages_for(bvid: str):
-        if bvid in cache:
-            return cache[bvid]
-        if cache:
-            jitter = getattr(client, "_jitter", lambda: 0.0)()
-            client._sleeper(0.8 + max(0.0, jitter) * 0.8)
-        cache[bvid] = client.list_pages(bvid)
-        return cache[bvid]
 
-    return pages_for
-
-
-def _merge_page_rows(client, records: dict, existing: dict, pages_for=None) -> dict:
-    """Expand each enumerated bvid into one ledger row per PageIdentity."""
-    from .page_identity import apply_identity
-
-    if pages_for is None:
-        pages_for = _cached_page_lister(client)
-    entries = dict(existing)
-    for bvid, meta in records.items():
-        bare = entries.get(bvid)
-        if _is_excluded(bare):
-            continue
-        try:
-            pages = pages_for(bvid)
-        except Exception:
-            continue
-        for page in pages:
-            prev = entries.get(page.work_id) or {}
-            if _is_excluded(prev):
-                continue
-            entry = dict(prev)
-            entry.update(meta)
-            entry = apply_identity(entry, page)
-            entry.setdefault("status", "meta_ok")
-            entries[page.work_id] = entry
-        if (
-            bvid in entries
-            and not entries[bvid].get("work_id")
-            and not _is_excluded(entries[bvid])
-        ):
-            del entries[bvid]
-    return entries
-
-
-def _persist_cursor(
-    cursor_store,
-    *,
-    mid: int,
-    next_page: int,
-    total: int | None,
-    state: str,
-    last_api_error_code: int | str | None = None,
-) -> None:
-    from .meta_cursor import utc_now_iso
-
-    cursor_store.replace_atomic(
-        {
-            "mid": mid,
-            "next_page": next_page,
-            "total": total,
-            "state": state,
-            "last_api_error_code": last_api_error_code,
-            "updated_at": utc_now_iso(),
-        }
-    )
+def _metadata_database_path(archive_root: str) -> str:
+    """Return the fresh SQLite database path below an archive root."""
+    return os.path.join(archive_root, ARCHIVE_DATABASE_NAME)
 
 
-def _interrupt_cursor(client, cursor_store, mid: int, last_api_error_code) -> None:
-    _persist_cursor(
-        cursor_store,
-        mid=mid,
-        next_page=client.last_failed_page,
-        total=client.last_observed_total,
-        state="risk_interrupted",
-        last_api_error_code=last_api_error_code,
-    )
+def _open_read_repository(
+    command: str, archive_root: str
+) -> "MetadataRepository | None":
+    """Open the fresh database for a read command; None after printing why not.
 
-
-def _persist_partial(client, store, existing, pages_for=None) -> int:
-    """Merge and save pages already fetched (H2: honest --resume).
-
-    Returns the number of records persisted from this partial run.
+    Read commands never create the database: a missing file is the
+    documented configuration error (exit 1), and an unreadable file is
+    reported bounded without raw SQLite text.
     """
-    if pages_for is None:
-        pages_for = _cached_page_lister(client)
-    records = client.merge_pages(client.pages_fetched)
-    entries = _merge_page_rows(client, records, existing, pages_for=pages_for)
-    store.save(entries)
-    return len(records)
+    from bili_asr.storage import MetadataRepository, open_database
 
+    if not os.path.isfile(_metadata_database_path(archive_root)):
+        print(
+            f"{command}: no archive database at {archive_root}; "
+            "run fetch-meta to create it",
+            file=sys.stderr,
+        )
+        return None
+    try:
+        connection = open_database(archive_root)
+    except (OSError, sqlite3.Error) as exc:
+        print(
+            f"{command}: unreadable archive database at {archive_root} "
+            f"({type(exc).__name__})",
+            file=sys.stderr,
+        )
+        return None
+    return MetadataRepository(connection)
 
-def _cmd_fetch_meta(args: argparse.Namespace) -> int:
-    # Imported here so --help / status never require requests at import time
-    # in low-dependency environments (bili_client lazy-imports requests).
-    from . import bili_client
-    from .manifest import ManifestStore
-    from .meta_cursor import MetaCursorStore
-    from .page_identity import parse_work_id
-    from .run_ledger import (
-        RunLedger,
-        build_run_record,
-        compute_coverage_summary,
-        utc_now_iso,
-    )
 
-    started_at = utc_now_iso()
-    ledger = RunLedger(root=args.archive_root)
-    sessdata = _resolve_sessdata(args)
-    client = bili_client.BiliClient(sessdata=sessdata)
-    store = ManifestStore(root=args.archive_root)
-    cursor_store = MetaCursorStore(root=args.archive_root)
-    # Always merge prior JSONL (last-write-wins). Without --resume the
-    # leftover cursor is replaced; the catalog is not truncated to page 1.
-    existing = store.load()
-    start_page = 1
-    if args.resume:
-        resumed = cursor_store.resume_start_page(args.mid)
-        if resumed is not None:
-            start_page = resumed
-    pages_for = _cached_page_lister(client)
-    # Seed fetch_pages.seen only on --resume. A full recrawl must walk
-    # ceil(total/ps) even when every page-1 bvid already lives in JSONL;
-    # the no-new-bvid stop would otherwise fire after the first overlap.
-    known_bvids: set[str] = set()
-    if args.resume:
-        for key, row in existing.items():
-            bvid = row.get("bvid") if isinstance(row, dict) else None
-            if bvid:
-                known_bvids.add(str(bvid))
-                continue
-            try:
-                parsed, _ = parse_work_id(key)
-                known_bvids.add(parsed)
-            except ValueError:
-                pass
-    per_page_persists = 0
-
-    def _record_exit(
-        exit_code: int,
-        *,
-        pages_count: int | None = None,
-        records_count: int | None = None,
-        last_error_code: int | str | None = None,
-    ) -> None:
-        try:
-            cursor_snapshot = cursor_store.load()
-            coverage = compute_coverage_summary(store.load())
-            rec = build_run_record(
-                command="fetch-meta",
-                started_at=started_at,
-                finished_at=utc_now_iso(),
-                exit_code=exit_code,
-                mid=args.mid,
-                pages_fetched=pages_count,
-                records_fetched=records_count,
-                records_existing=len(existing),
-                last_api_error_code=last_error_code,
-                coverage_summary=coverage,
-                cursor_snapshot=cursor_snapshot,
-            )
-            ledger.append(rec)
-        except Exception:
-            pass
+def _cmd_fetch_meta(args: argparse.Namespace) -> int:
+    """Collect video metadata into the fresh SQLite archive database.
 
-    def _after_successful_page() -> None:
-        nonlocal existing, per_page_persists
-        _persist_partial(client, store, existing, pages_for=pages_for)
-        existing = store.load()
-        per_page_persists += 1
-        # Mid-run: never persist running; keep risk_interrupted until the
-        # terminal complete/limited write after fetch_pages returns.
-        _persist_cursor(
-            cursor_store,
-            mid=args.mid,
-            next_page=client.last_completed_page + 1,
-            total=client.last_observed_total,
-            state="risk_interrupted",
-        )
+    Exit taxonomy (metadata-cli-contract spec): 0 successful collection
+    (reached end or explicit --limit-pages); 1 usage/configuration error;
+    2 terminal gateway failure with the cursor unchanged.  This handler
+    never reads or writes the legacy manifest/cursor/ledger sidecars.
+    """
+    from bili_asr.services import MetadataIngestor
+    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
+    from bili_asr.storage import MetadataRepository, open_database
 
     try:
-        pages = client.fetch_pages(
-            args.mid,
-            max_pages=args.limit_pages,
-            start_page=start_page,
-            on_page=_after_successful_page,
-            known_bvids=known_bvids or None,
-        )
-    except bili_client.RiskBudgetExhausted as exc:
-        unenumerated = client.last_failed_page
-        partial = _persist_partial(client, store, existing, pages_for=pages_for)
-        _interrupt_cursor(client, cursor_store, args.mid, exc.last_code)
-        _record_exit(
-            2,
-            pages_count=len(client.pages_fetched),
-            records_count=partial,
-            last_error_code=exc.last_code,
-        )
+        config = load_metadata_config(args)
+    except MetadataConfigError as exc:
+        print(f"fetch-meta: {exc}", file=sys.stderr)
+        return 1
+
+    if config.resume and not os.path.isfile(
+        _metadata_database_path(config.archive_root)
+    ):
         print(
-            f"risk-control ceiling: page {unenumerated} could not be "
-            f"enumerated (retry budget exhausted, last code {exc.last_code}); "
-            f"{partial} record(s) from {len(client.pages_fetched)} fetched "
-            f"page(s) persisted, {len(existing)} pre-existing entries kept. "
-            f"Re-run with --resume to continue.",
+            f"fetch-meta: no archive database at {config.archive_root}; "
+            "--resume requires a stored cursor",
             file=sys.stderr,
         )
-        return 2
-    except bili_client.APIResponseError as exc:
-        partial = _persist_partial(client, store, existing, pages_for=pages_for)
-        _interrupt_cursor(client, cursor_store, args.mid, exc.code)
-        _record_exit(
-            2,
-            pages_count=len(client.pages_fetched),
-            records_count=partial,
-            last_error_code=exc.code,
-        )
+        return 1
+    try:
+        connection = open_database(config.archive_root)
+    except (OSError, sqlite3.Error) as exc:
         print(
-            f"fetch-meta: API response error (code {exc.code}) at page "
-            f"{client.last_failed_page}; {partial} record(s) from "
-            f"{len(client.pages_fetched)} fetched page(s) persisted. "
-            f"Re-run with --resume to continue.",
+            f"fetch-meta: invalid --archive-root {config.archive_root} "
+            f"({type(exc).__name__})",
             file=sys.stderr,
         )
-        return 2
-    except bili_client.GoneResponse as exc:
-        partial = _persist_partial(client, store, existing, pages_for=pages_for)
-        _interrupt_cursor(client, cursor_store, args.mid, exc.code)
-        _record_exit(
-            2,
-            pages_count=len(client.pages_fetched),
-            records_count=partial,
-            last_error_code=exc.code,
-        )
-        if client.pages_fetched:
-            print(
-                f"fetch-meta: terminal API response (code {exc.code}) at "
-                f"page {client.last_failed_page}; {len(client.pages_fetched)} "
-                f"page(s) already fetched were persisted ({partial} "
-                f"record(s)) — re-run with --resume to continue.",
-                file=sys.stderr,
-            )
-        else:
+        return 1
+
+    try:
+        repository = MetadataRepository(connection)
+        if config.resume and repository.read_cursor(config.mid) is None:
             print(
-                f"fetch-meta: terminal API response (code {exc.code}) at "
-                f"page {client.last_failed_page}; no pages enumerated.",
+                f"fetch-meta: --resume requires a stored cursor; none recorded "
+                f"for mid={config.mid} (drop --resume to start from page 1)",
                 file=sys.stderr,
             )
-        return 2
+            return 1
+        gateway = BilibiliApiGateway(sessdata=config.sessdata)
+        ingestor = MetadataIngestor(gateway, repository)
+        result = ingestor.collect_user_pages(
+            mid=config.mid,
+            start_page=config.start_page,
+            page_limit=config.page_limit,
+        )
     except Exception:
-        # H1 belt-and-braces: any unexpected error exits 1 with a fixed,
-        # redacted summary and never a traceback.
+        # C5: the ingestor resolves bounded gateway failures internally, so
+        # anything escaping is unexpected — exit the terminal code with a
+        # fixed redacted summary, never a traceback or payload text.
         print("fetch-meta: unexpected error", file=sys.stderr)
-        return 1
+        return 2
+    finally:
+        connection.close()
 
-    records = client.merge_pages(pages)
-    if per_page_persists:
-        entries = store.load()
-    else:
-        entries = _merge_page_rows(client, records, existing, pages_for=pages_for)
-        store.save(entries)
-    try:
-        store.migrate_legacy_rows(
-            pages_for,
-            archive_root=args.archive_root,
-            coalesce_existing_page=True,
+    print(f"sessdata: {redact_sessdata(config.sessdata)}")
+    print(
+        f"fetch-meta: collected {result.page_count} page(s) for "
+        f"mid={config.mid} (outcome={result.outcome})"
+    )
+    if result.outcome in {"risk_interrupted", "failed"}:
+        cursor_clause = (
+            f"cursor unchanged at page {result.next_cursor.next_page}"
+            if result.next_cursor is not None
+            else "no cursor recorded"
         )
-    except Exception:
-        print("fetch-meta: legacy migration failed", file=sys.stderr)
-        return 1
-    entries = store.load()
-    next_page = client.last_completed_page + 1
-    if client.enumeration_complete:
-        cursor_state = "complete"
-    else:
-        cursor_state = "limited"
-    _persist_cursor(
-        cursor_store,
-        mid=args.mid,
-        next_page=next_page,
-        total=client.last_observed_total,
-        state=cursor_state,
-    )
-    _record_exit(
-        0,
-        pages_count=len(pages),
-        records_count=len(records),
-        last_error_code=None,
-    )
-
-    total_s = sum(e.get("duration_s", 0) for e in entries.values())
-    print(f"manifest: {len(entries)} videos "
-          f"({len(records)} fetched, {len(existing)} resumed)")
-    print(f"total duration: {total_s / 3600:.1f} h")
-    if cursor_state == "complete":
-        print("enumeration: complete")
-    else:
         print(
-            f"enumeration: limited (next unenumerated page {next_page})"
+            f"fetch-meta: metadata gateway failure ({result.error_code}); "
+            f"{cursor_clause} — re-run fetch-meta to resume.",
+            file=sys.stderr,
+        )
+        return 2
+    if result.next_cursor is not None:
+        print(
+            f"cursor: next_page={result.next_cursor.next_page} "
+            f"state={result.next_cursor.state}"
         )
     return 0
 
 
+def _run_error_codes(repository: "MetadataRepository") -> dict[str, str]:
+    """Collect one bounded error code per run from recorded page evidence."""
+    codes: dict[str, str] = {}
+    rows = repository.connection.execute(
+        "SELECT run_id, error_code FROM ingestion_pages"
+        " WHERE error_code IS NOT NULL ORDER BY run_id, page_number"
+    ).fetchall()
+    for row in rows:
+        codes.setdefault(str(row["run_id"]), str(row["error_code"]))
+    return codes
+
+
+def _format_run_line(stats: sqlite3.Row, error_code: str | None) -> str:
+    """Render one run row: identity, times, outcome, counts, bounded error."""
+    finished = stats["finished_at"]
+    fields = [
+        f"run {stats['run_id']}",
+        f"mid={stats['mid']}",
+        f"started={stats['started_at']}",
+        f"finished={finished if finished is not None else '-'}",
+        f"outcome={stats['outcome']}",
+        f"pages={stats['page_count']}",
+        f"videos={stats['video_count']}",
+    ]
+    if error_code is not None:
+        fields.append(f"error={error_code}")
+    return " ".join(fields)
+
+
 def _resolve_sessdata(args: argparse.Namespace) -> str | None:
     """SESSDATA from --sessdata or env BILI_SESSDATA; never echoed."""
-    return args.sessdata or os.environ.get("BILI_SESSDATA") or None
+    return resolve_sessdata(args.sessdata, os.environ.get(SESSDATA_ENV_VAR))
 
 
 def _cmd_probe_subs(args: argparse.Namespace) -> int:
@@ -1031,32 +896,45 @@ def _cmd_download_audio(args: argparse.Namespace) -> int:
 
 
 def _cmd_status(args: argparse.Namespace) -> int:
-    from collections import Counter
-    from .manifest import ManifestStore
-    from .run_ledger import RunLedger, format_coverage_summary, format_cursor_summary
-
-    store = ManifestStore(root=args.archive_root)
-    entries = store.load()
-    counts = Counter(entry.get("status", "pending") for entry in entries.values())
-    if not counts:
-        print("manifest: empty")
-    else:
-        for status in sorted(counts):
-            print(f"{status}: {counts[status]}")
-    unresolved = store.unresolved_identifiers()
-    if unresolved:
-        print(f"unresolved: {len(unresolved)}")
-        for identifier in unresolved:
-            print(f"  {identifier}")
-    records = RunLedger(root=args.archive_root).load()
-    if not records:
-        print("runs: 0")
-    else:
-        print(f"runs: {len(records)}")
-        latest = records[-1]
-        print(f"latest run: {latest.get('run_id', 'unknown')} ({latest.get('command', 'unknown')}, exit {latest.get('exit_code', '?')}, {latest.get('finished_at') or latest.get('started_at') or ''})")
-        print(f"latest cursor: {format_cursor_summary(latest.get('cursor_snapshot'))}")
-        print(f"latest coverage: {format_coverage_summary(latest.get('coverage_summary'))}")
+    """Report metadata state from the fresh SQLite database only."""
+    repository = _open_read_repository("status", args.archive_root)
+    if repository is None:
+        return 1
+    connection = repository.connection
+    counts = connection.execute(
+        "SELECT (SELECT COUNT(*) FROM bilibili_users) AS users,"
+        " (SELECT COUNT(*) FROM videos) AS videos,"
+        " (SELECT COUNT(*) FROM video_parts) AS parts"
+    ).fetchone()
+    print(f"users: {counts['users']}")
+    print(f"videos: {counts['videos']}")
+    print(f"parts: {counts['parts']}")
+    processing = connection.execute(
+        "SELECT processing_status, COUNT(*) AS count FROM video_parts"
+        " GROUP BY processing_status ORDER BY processing_status"
+    ).fetchall()
+    if processing:
+        summary = ", ".join(
+            f"{row['processing_status']}={row['count']}" for row in processing
+        )
+        print(f"processing: {summary}")
+    pending = repository.list_pending_parts()
+    print(f"pending: {len(pending)}")
+    for row in pending[:_MAX_DISPLAYED_PENDING_PARTS]:
+        print(f"  {row['work_id']}")
+    hidden = len(pending) - _MAX_DISPLAYED_PENDING_PARTS
+    if hidden > 0:
+        print(f"  + {hidden} more pending part(s)")
+    # The cursor row is reported exactly as stored: a failed or
+    # risk-interrupted run leaves it untouched, so this line never implies
+    # the cursor advanced past a failed page (C3).
+    for user_row in connection.execute("SELECT mid FROM bilibili_users ORDER BY mid"):
+        cursor = repository.read_cursor(int(user_row["mid"]))
+        if cursor is not None:
+            print(
+                f"cursor: mid={cursor.mid} next_page={cursor.next_page} "
+                f"state={cursor.state}"
+            )
     return 0
 
 
@@ -1246,22 +1124,30 @@ def _cmd_coverage(args: argparse.Namespace) -> int:
 
 
 def _cmd_runs(args: argparse.Namespace) -> int:
-    from .run_ledger import RunLedger, format_run_summary
+    """List ingestion runs newest-first from the fresh SQLite database.
 
-    ledger = RunLedger(root=args.archive_root)
-    records = ledger.load()
-    if not records:
+    Non-terminal ``running`` rows are rendered too: abnormal termination
+    can leave a stale run behind and hiding it would hide real state (C2).
+    """
+    repository = _open_read_repository("runs", args.archive_root)
+    if repository is None:
+        return 1
+    if args.limit is not None and args.limit < 1:
+        print("runs: --limit must be a positive integer", file=sys.stderr)
+        return 1
+    stats_rows = repository.run_stats()
+    if not stats_rows:
         print("runs: empty")
         return 0
-
-    if args.limit is not None:
-        if args.limit <= 0:
-            print("runs: empty")
-            return 0
-        records = records[-args.limit:]
-
-    for record in records:
-        print(format_run_summary(record))
+    error_codes = _run_error_codes(repository)
+    ordered = sorted(
+        stats_rows,
+        key=lambda row: (row["started_at"], row["run_id"]),
+        reverse=True,
+    )
+    selected = ordered if args.limit is None else ordered[: args.limit]
+    for row in selected:
+        print(_format_run_line(row, error_codes.get(str(row["run_id"]))))
     return 0
 
 
diff --git a/bilibili-asr-archive/src/bili_asr/config.py b/bilibili-asr-archive/src/bili_asr/config.py
new file mode 100644
index 0000000..6c5c73d
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/config.py
@@ -0,0 +1,142 @@
+"""Configuration for the SQLite-backed metadata commands.
+
+``fetch-meta`` resolves its settings through :func:`load_metadata_config`
+so the command layer only composes validated values, and so every display
+or debug path that could show the credential instead shows a redacted
+presence label.  The SESSDATA value is resolved from ``--sessdata`` or the
+``BILI_SESSDATA`` environment variable, is never echoed, logged,
+persisted, or rendered by any helper here.  ``status`` and ``runs`` take
+no credential and no page arguments; they share only the database-name
+constant below.
+"""
+
+from __future__ import annotations
+
+import argparse
+import os
+from dataclasses import dataclass, field
+
+#: Bilibili user collected by default (未明子).
+DEFAULT_MID = 23191782
+
+#: Documented default bound for full-collection runs (carry item C1).
+#:
+#: ``--limit-pages`` defaults to this instead of unbounded: a full
+#: collection without an explicit bound would otherwise only terminate on
+#: an upstream empty page, exposing every run to unbounded anti-bot risk.
+#: Ten pages at the ingestor's page size of 100 is a resumable, conservative
+#: slice; operators opt into longer batches explicitly.
+DEFAULT_PAGE_LIMIT = 10
+
+#: Environment variable carrying the optional SESSDATA credential.
+SESSDATA_ENV_VAR = "BILI_SESSDATA"
+
+#: File name of the fresh SQLite database below the archive root.  Must
+#: stay identical to the storage layer's archive database name because the
+#: read commands check for its existence before opening it.
+ARCHIVE_DATABASE_NAME = "archive.db"
+
+#: Presence labels used wherever configuration display would show SESSDATA.
+SESSDATA_PRESENT_LABEL = "present"
+SESSDATA_ABSENT_LABEL = "absent"
+
+
+class MetadataConfigError(ValueError):
+    """A metadata command received an invalid configuration value."""
+
+
+@dataclass(frozen=True)
+class MetadataConfig:
+    """Resolved settings for one metadata command invocation.
+
+    ``sessdata`` is excluded from the repr so any accidental debug or
+    traceback rendering of the configuration can never carry the value;
+    display paths use :func:`redact_sessdata` explicitly.
+    """
+
+    mid: int
+    archive_root: str
+    start_page: int | None
+    page_limit: int | None
+    resume: bool
+    sessdata: str | None = field(repr=False)
+
+
+def load_metadata_config(args: argparse.Namespace) -> MetadataConfig:
+    """Validate parsed arguments and environment into a metadata config.
+
+    Page arguments must be positive integers, ``--resume`` and
+    ``--start-page`` are mutually exclusive, and an omitted
+    ``--limit-pages`` keeps the documented :data:`DEFAULT_PAGE_LIMIT` bound
+    so a full-collection run always terminates on a bounded slice (C1).
+    Raises :class:`MetadataConfigError` (a ``ValueError``) for any
+    violation, which the command maps to the usage-error exit.
+    """
+
+    mid = args.mid
+    start_page = args.start_page
+    page_limit = args.limit_pages
+    resume = bool(args.resume)
+
+    if isinstance(mid, bool) or not isinstance(mid, int) or mid < 1:
+        raise MetadataConfigError("--mid must be a positive integer")
+    if start_page is not None and (
+        isinstance(start_page, bool) or not isinstance(start_page, int) or start_page < 1
+    ):
+        raise MetadataConfigError("--start-page must be a positive integer")
+    if page_limit is not None and (
+        isinstance(page_limit, bool) or not isinstance(page_limit, int) or page_limit < 1
+    ):
+        raise MetadataConfigError("--limit-pages must be a positive integer")
+    if resume and start_page is not None:
+        raise MetadataConfigError("--resume and --start-page are mutually exclusive")
+    if page_limit is None:
+        page_limit = DEFAULT_PAGE_LIMIT
+
+    return MetadataConfig(
+        mid=mid,
+        archive_root=args.archive_root,
+        start_page=start_page,
+        page_limit=page_limit,
+        resume=resume,
+        sessdata=resolve_sessdata(
+            getattr(args, "sessdata", None), os.environ.get(SESSDATA_ENV_VAR)
+        ),
+    )
+
+
+def resolve_sessdata(
+    flag_value: str | None, environment_value: str | None = None
+) -> str | None:
+    """Return the credential from the flag, else the environment, else None.
+
+    The value is resolved for gateway construction only and is never
+    echoed; blank values mean public (anonymous) access.
+    """
+
+    return flag_value or environment_value or None
+
+
+def redact_sessdata(sessdata: str | None) -> str:
+    """Render SESSDATA presence for any display or debug path.
+
+    Only presence is shown — the credential value itself never appears in
+    output, logs, errors, or persisted rows (C6).
+    """
+
+    return SESSDATA_PRESENT_LABEL if sessdata else SESSDATA_ABSENT_LABEL
+
+
+__all__ = [
+    "ARCHIVE_DATABASE_NAME",
+    "DEFAULT_MID",
+    "DEFAULT_PAGE_LIMIT",
+    "SESSDATA_ABSENT_LABEL",
+    "SESSDATA_ENV_VAR",
+    "SESSDATA_PRESENT_LABEL",
+    "MetadataConfig",
+    "MetadataConfigError",
+    "load_metadata_config",
+    "redact_sessdata",
+    "resolve_sessdata",
+]
diff --git a/bilibili-asr-archive/tests/test_cli_help.py b/bilibili-asr-archive/tests/test_cli_help.py
index 1b65f69..3898681 100644
--- a/bilibili-asr-archive/tests/test_cli_help.py
+++ b/bilibili-asr-archive/tests/test_cli_help.py
@@ -36,12 +36,12 @@ def test_installed_console_script_help(isolated_cli) -> None:
     assert_redacted(proc)
 
 
-def test_installed_console_script_status_uses_temp_archive_root(isolated_cli, tmp_path: Path) -> None:
+def test_installed_console_script_status_fails_without_database(isolated_cli, tmp_path: Path) -> None:
     archive_root = tmp_path / "archive"
     proc = run_installed(isolated_cli, ["status", "--archive-root", str(archive_root)])
-    assert proc.returncode == 0, proc.stderr
-    assert "manifest: empty" in proc.stdout
-    assert str(archive_root) not in proc.stdout
+    assert proc.returncode == 1, proc.stdout
+    assert "no archive database" in proc.stderr
+    assert proc.stdout == ""
     assert_redacted(proc)
 
 
@@ -80,14 +80,14 @@ def test_module_help_is_supplemental_coverage() -> None:
     assert_redacted(proc)
 
 
-def test_module_status_uses_temp_archive_root(tmp_path: Path) -> None:
+def test_module_status_fails_without_database(tmp_path: Path) -> None:
     proc = run_module(["status", "--archive-root", str(tmp_path)])
-    assert proc.returncode == 0, proc.stderr
-    assert "manifest: empty" in proc.stdout
+    assert proc.returncode == 1, proc.stdout
+    assert "no archive database" in proc.stderr
     assert_redacted(proc)
 
 
-def test_installed_console_script_status_with_manifest_records(isolated_cli, tmp_path: Path) -> None:
+def test_installed_console_script_status_ignores_legacy_manifest(isolated_cli, tmp_path: Path) -> None:
     from bili_asr.manifest import ManifestStore
 
     store = ManifestStore(root=str(tmp_path))
@@ -95,16 +95,18 @@ def test_installed_console_script_status_with_manifest_records(isolated_cli, tmp
     store.upsert({"work_id": "BV1test_meta:p1", "bvid": "BV1test_meta", "status": "meta_ok"})
 
     proc = run_installed(isolated_cli, ["status", "--archive-root", str(tmp_path)])
-    assert proc.returncode == 0, proc.stderr
-    assert "archived: 1" in proc.stdout
-    assert "meta_ok: 1" in proc.stdout
+    # status reads only the fresh SQLite database: with no archive.db the
+    # legacy manifest rows are neither read nor rewritten (exit 1).
+    assert proc.returncode == 1, proc.stdout
+    assert "BV1test_inst" not in proc.stdout
+    assert "no archive database" in proc.stderr
     assert_redacted(proc)
 
 
-def test_module_runs_empty_archive(tmp_path: Path) -> None:
+def test_module_runs_fails_without_database(tmp_path: Path) -> None:
     proc = run_module(["runs", "--archive-root", str(tmp_path)])
-    assert proc.returncode == 0, proc.stderr
-    assert "runs: empty" in proc.stdout
+    assert proc.returncode == 1, proc.stdout
+    assert "no archive database" in proc.stderr
     assert_redacted(proc)
 
 
diff --git a/bilibili-asr-archive/tests/test_fetch_meta.py b/bilibili-asr-archive/tests/test_fetch_meta.py
index 6eecceb..e3c0842 100644
--- a/bilibili-asr-archive/tests/test_fetch_meta.py
+++ b/bilibili-asr-archive/tests/test_fetch_meta.py
@@ -1,15 +1,16 @@
-"""Unit tests for fetch-meta: mocked transport only, no live network."""
+"""Unit tests for bili_client transport: mocked transport only, no live network.
 
-from __future__ import annotations
+The fetch-meta CLI contract lives in tests/test_metadata_cli.py (SQLite
+metadata path).  This module keeps covering the bili_client transport
+layer that the future subtitle/audio/ASR modules still drive.
+"""
 
-import json
-import os
+from __future__ import annotations
 
 import pytest
 
 from bili_asr import bili_client as bc
-from bili_asr.cli import main
-from bili_asr.manifest import ManifestStore
+from bili_asr.cli import build_parser
 
 API = "https://api.bilibili.com"
 
@@ -340,133 +341,10 @@ def test_merge_pages_dedupes_across_pages():
     assert records["BV1A"]["title"] == "t BV1A"
 
 
-# ---------------------------------------------------------------- CLI
-
-
-def test_cli_fetch_meta_writes_manifest(tmp_root, fast_sleep, monkeypatch):
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A", duration=3600), arc("BV1B", duration=1800)],
-                          total=2)),
-            (200, ok_page([], total=2)),  # next page empty -> stop
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 0
-    entries = ManifestStore(root=tmp_root).load()
-    assert set(entries) == {"BV1A:p0", "BV1B:p0"}
-    for e in entries.values():
-        assert e["status"] == "meta_ok"
-        assert e["work_id"].endswith(":p0")
-    assert entries["BV1A:p0"]["duration_s"] == 3600
-    assert entries["BV1A:p0"]["pubdate"] == 1700000000
-
-
-def test_cli_fetch_meta_uses_env_sessdata_without_echoing(
-    tmp_root, fast_sleep, monkeypatch, capsys
-):
-    secret = "FETCH-META-ENV-SESSDATA"
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A")], total=1)),
-            (200, ok_page([], total=1)),
-        ]
-    )
-    monkeypatch.setenv("BILI_SESSDATA", secret)
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-
-    assert rc == 0
-    assert transport.calls
-    assert all(call["cookies"].get("SESSDATA") == secret for call in transport.calls)
-    captured = capsys.readouterr()
-    assert secret not in captured.out + captured.err
-    manifest_text = open(
-        ManifestStore(root=tmp_root).path, encoding="utf-8"
-    ).read()
-    assert secret not in manifest_text
-
-
-def test_cli_fetch_meta_redacts_successful_run_migration_failure(
-    tmp_root, fast_sleep, monkeypatch, capsys
-):
-    secret = "migration /secret/SESSDATA=https://signed.example"
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A")], total=1)),
-            (200, ok_page([], total=1)),
-        ]
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-
-    def fail_migration(*_args, **_kwargs):
-        raise RuntimeError(secret)
-
-    monkeypatch.setattr(ManifestStore, "migrate_legacy_rows", fail_migration)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-
-    captured = capsys.readouterr()
-    assert rc == 1
-    assert captured.err == "fetch-meta: legacy migration failed\n"
-    assert secret not in captured.out + captured.err
-
-
-def test_cli_resume_does_not_duplicate(tmp_root, fast_sleep, monkeypatch):
-    store = ManifestStore(root=tmp_root)
-    store.load()
-    store.save({
-        "BV1A": {
-            "bvid": "BV1A", "status": "meta_ok", "title": "t BV1A",
-            "duration_s": 100, "pubdate": 1,
-        }
-    })
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A"), arc("BV1B")], total=2)),
-            (200, ok_page([], total=2)),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--resume",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    entries = store.load()
-    assert set(entries) == {"BV1A:p0", "BV1B:p0"}
-    lines = open(store.path, encoding="utf-8").read().strip().splitlines()
-    bvids = [json.loads(line)["bvid"] for line in lines]
-    assert set(bvids) == {"BV1A", "BV1B"}
-    assert set(store.load()) == {"BV1A:p0", "BV1B:p0"}
-
-
-def test_cli_budget_exhausted_exit_2(tmp_root, fast_sleep, monkeypatch, capsys):
-    transport = FakeTransport([(412, None)] * 5, spi=[SPI_OK, SPI_NEW])
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-    captured = capsys.readouterr()
-    out = captured.out + captured.err
-    assert "risk-control ceiling" in out
-    assert "page 1" in out  # un-enumerated page count documented
-
-
-def test_cli_pages_limit(tmp_root, fast_sleep, monkeypatch):
-    transport = FakeTransport(
-        [(200, ok_page([arc("BV1A")], total=99))],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--limit-pages", "1",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    entries = ManifestStore(root=tmp_root).load()
-    assert set(entries) == {"BV1A:p0"}
+# ------------------------------------------------- fix wave 1 (QC1/2/3) tests
+# (the fetch-meta CLI contract moved to tests/test_metadata_cli.py — SQLite
+# metadata path; these tests keep covering the bili_client transport layer
+# that the future subtitle/audio/ASR modules still drive)
 
 
 # ------------------------------------------------- fix wave 1 (QC1/2/3) tests
@@ -540,136 +418,6 @@ def test_spi_transport_error_wrapped_as_budget_exhausted(fast_sleep):
         client.fetch_pages(23191782, max_pages=1)
 
 
-# H2: partial pages persisted on RiskBudgetExhausted / GoneResponse mid-run
-
-
-def test_cli_budget_exhausted_midrun_persists_partial(tmp_root, fast_sleep,
-                                                      monkeypatch, capsys):
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A"), arc("BV1B")], total=99)),
-            (412, None), (412, None), (412, None), (412, None), (412, None),
-        ],
-        spi=[SPI_OK, SPI_NEW],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-    entries = ManifestStore(root=tmp_root).load()
-    assert set(entries) == {"BV1A:p0", "BV1B:p0"}  # partial run persisted
-    err = capsys.readouterr().err
-    assert "page 2" in err
-    assert "2" in err and "persisted" in err
-
-
-def test_cli_budget_exhausted_page1_persists_nothing(tmp_root, fast_sleep,
-                                                     monkeypatch):
-    transport = FakeTransport([(412, None)] * 5, spi=[SPI_OK, SPI_NEW])
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-    assert not os.path.exists(ManifestStore(root=tmp_root).path)
-
-
-# APIResponseError/GoneResponse: persist partial, honest message
-
-
-def test_cli_api_error_midrun_persists_partial(tmp_root, fast_sleep,
-                                               monkeypatch, capsys):
-    store = ManifestStore(root=tmp_root)
-    store.load()
-    store.save({
-        "BVexisting": {"bvid": "BVexisting", "status": "subtitle_done"},
-    })
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A")], total=99)),
-            (200, {"code": -400}),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main([
-        "fetch-meta", "--mid", "23191782", "--resume",
-        "--archive-root", tmp_root,
-    ])
-    assert rc == 2
-    entries = store.load()
-    assert entries["BVexisting"]["status"] == "subtitle_done"
-    assert entries["BV1A:p0"]["status"] == "meta_ok"
-    assert all(entry.get("status") != "gone" for entry in entries.values())
-    err = capsys.readouterr().err
-    assert "API response error (code -400)" in err
-    assert "Traceback" not in err
-
-
-def test_cli_gone_midrun_persists_partial(tmp_root, fast_sleep, monkeypatch,
-                                          capsys):
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A")], total=99)),
-            (200, ok_page([arc("BV1B")], total=99)),
-            (404, None),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-    entries = ManifestStore(root=tmp_root).load()
-    assert set(entries) == {"BV1A:p0", "BV1B:p0"}
-    err = capsys.readouterr().err
-    assert "2 page(s)" in err
-    assert "no pages enumerated" not in err
-
-
-class SelectivePagelistTransport(FakeTransport):
-    def get_json(self, url, params=None, headers=None, cookies=None, timeout=None):
-        if "pagelist" in url:
-            self.calls.append(
-                {"url": url, "params": dict(params or {}), "cookies": dict(cookies or {})}
-            )
-            bvid = (params or {}).get("bvid")
-            if bvid == "BV1B":
-                return 200, {"code": -404}
-            return 200, {
-                "code": 0,
-                "data": [{"cid": 11, "page": 1, "part": ""}],
-            }
-        return super().get_json(url, params=params, headers=headers, cookies=cookies, timeout=timeout)
-
-
-def test_cli_fetch_meta_pagelist_failure_keeps_other_bvid(
-    tmp_root, fast_sleep, monkeypatch
-):
-    transport = SelectivePagelistTransport(
-        [(200, ok_page([arc("BV1A"), arc("BV1B")], total=2))],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 0
-    entries = ManifestStore(root=tmp_root).load()
-    assert "BV1A:p0" in entries
-    assert "BV1B" not in entries
-    assert "BV1B:p0" not in entries
-    pagelist = [c for c in transport.calls if "pagelist" in c["url"]]
-    assert [c["params"]["bvid"] for c in pagelist] == ["BV1A", "BV1B"]
-
-
-def test_cli_gone_on_first_page_reports_no_pages(tmp_root, fast_sleep,
-                                                 monkeypatch, capsys):
-    transport = FakeTransport([(200, {"code": -62002})])
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-    err = capsys.readouterr().err
-    assert "no pages" in err
-
-
 # QC2-2: argparse usage errors exit 1, not 2
 
 
@@ -692,45 +440,3 @@ def test_argparse_help_exits_0():
     with pytest.raises(SystemExit) as exc:
         parser.parse_args(["--help"])
     assert exc.value.code == 0
-
-
-# H1 CLI-level: RiskBudgetExhausted carries no traceback (exit 2, summary)
-
-
-def test_cli_unexpected_error_exit_1_no_traceback(tmp_root, monkeypatch,
-                                                  capsys):
-    sentinel = "SESSDATA=FETCH-SECRET https://cdn.example/audio.m4s?token=SIGNED"
-
-    def boom(self, *a, **k):
-        raise RuntimeError(sentinel)
-
-    monkeypatch.setattr(bc.BiliClient, "fetch_pages", boom)
-    rc = main(["fetch-meta", "--mid", "1", "--archive-root", tmp_root])
-    assert rc == 1
-    err = capsys.readouterr().err
-    assert "fetch-meta: unexpected error" in err
-    assert "Traceback" not in err
-    assert "FETCH-SECRET" not in err
-    assert "SIGNED" not in err
-
-
-def test_cli_transport_error_redacts_exception_message(
-    tmp_root, fast_sleep, monkeypatch, capsys
-):
-    sentinel = "SESSDATA=TRANSPORT-SECRET https://cdn.example/a.m4s?token=SIGNED"
-    transport = FakeTransport(
-        [_FakeRequestsError(sentinel)] * 5,
-        spi=[SPI_OK, SPI_NEW],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-
-    rc = main(["fetch-meta", "--mid", "1", "--archive-root", tmp_root])
-
-    assert rc == 2
-    captured = capsys.readouterr()
-    output = captured.out + captured.err
-    assert "_FakeRequestsError" in output
-    assert "TRANSPORT-SECRET" not in output
-    assert "SIGNED" not in output
-    assert not os.path.exists(ManifestStore(root=tmp_root).path)
diff --git a/bilibili-asr-archive/tests/test_meta_cursor.py b/bilibili-asr-archive/tests/test_meta_cursor.py
index 1523778..8b3743a 100644
--- a/bilibili-asr-archive/tests/test_meta_cursor.py
+++ b/bilibili-asr-archive/tests/test_meta_cursor.py
@@ -1,15 +1,18 @@
-"""MetaCursorStore + fetch-meta resume/limited/complete (no live HTTP)."""
+"""MetaCursorStore sidecar contract (no live HTTP).
+
+The fetch-meta CLI resume/limited/complete behavior moved to the SQLite
+metadata path (tests/test_metadata_cli.py and tests/test_metadata_e2e.py);
+this module keeps covering the MetaCursorStore sidecar that scheduler and
+coordinator flows still use.
+"""
 
 from __future__ import annotations
 
-import json
 import os
 
 import pytest
 
 from bili_asr import bili_client as bc
-from bili_asr.cli import main
-from bili_asr.manifest import ManifestStore
 from bili_asr.meta_cursor import MetaCursorStore, utc_now_iso
 
 from test_fetch_meta import FakeTransport, FastSleeper, SPI_NEW, SPI_OK, arc, ok_page
@@ -142,170 +145,8 @@ def test_bili_client_does_not_import_meta_cursor():
     assert "meta_cursor" not in src
 
 
-def test_cli_risk_writes_cursor_exit_2(tmp_root, fast_sleep, monkeypatch, capsys):
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A"), arc("BV1B")], total=99)),
-            (412, None), (412, None), (412, None), (412, None), (412, None),
-        ],
-        spi=[SPI_OK, SPI_NEW],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "risk_interrupted"
-    assert cursor["next_page"] == 2
-    assert cursor["mid"] == 23191782
-    assert cursor["last_api_error_code"] is not None
-    err = capsys.readouterr().err
-    assert "page 2" in err
-
-
-def test_cli_resume_consumes_risk_cursor(tmp_root, fast_sleep, monkeypatch):
-    _seed_risk(tmp_root, next_page=2, total=2)
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1B")], total=2)),
-            (200, ok_page([], total=2)),
-            (200, ok_page([], total=2)),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main([
-        "fetch-meta", "--mid", "23191782", "--resume",
-        "--archive-root", tmp_root,
-    ])
-    assert rc == 0
-    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
-    assert page_calls[0]["params"]["pn"] == 2
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "complete"
-
-
-def test_cli_without_resume_starts_at_page_one(tmp_root, fast_sleep, monkeypatch):
-    _seed_risk(tmp_root, next_page=5, total=99)
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A")], total=1)),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 0
-    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
-    assert page_calls[0]["params"]["pn"] == 1
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "complete"
-    assert cursor["next_page"] == 2
-
-
-def test_cli_limit_pages_is_limited_not_complete(
-    tmp_root, fast_sleep, monkeypatch, capsys
-):
-    transport = FakeTransport(
-        [(200, ok_page([arc("BV1A")], total=99))],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main([
-        "fetch-meta", "--mid", "23191782", "--limit-pages", "1",
-        "--archive-root", tmp_root,
-    ])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "complete" not in out
-    assert "limited" in out
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "limited"
-    assert cursor["next_page"] == 2
-    assert _cursor(tmp_root).resume_start_page(23191782) is None
-
-
-def test_cli_resume_persists_after_each_page(tmp_root, fast_sleep, monkeypatch):
-    """R1: --resume still merges JSONL and advances next_page per page."""
-    ManifestStore(root=tmp_root).save(
-        {
-            "BV1A:p0": {
-                "work_id": "BV1A:p0", "bvid": "BV1A", "page_index": 0,
-                "cid": 1, "status": "meta_ok",
-            },
-        }
-    )
-    _seed_risk(tmp_root, next_page=2, total=90)
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1B")], total=90)),
-            (412, None), (412, None), (412, None), (412, None), (412, None),
-        ],
-        spi=[SPI_OK, SPI_NEW],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main([
-        "fetch-meta", "--mid", "23191782", "--resume",
-        "--archive-root", tmp_root,
-    ])
-    assert rc == 2
-    entries = ManifestStore(root=tmp_root).load()
-    assert "BV1A:p0" in entries
-    assert "BV1B:p0" in entries
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "risk_interrupted"
-    assert cursor["next_page"] == 3
-
-
-def test_cli_no_resume_merges_prior_jsonl_not_prefix(
-    tmp_root, fast_sleep, monkeypatch,
-):
-    """R2: without --resume, page-1 must not clobber a complete JSONL."""
-    ManifestStore(root=tmp_root).save(
-        {
-            "BVOLD:p0": {
-                "work_id": "BVOLD:p0", "bvid": "BVOLD", "page_index": 0,
-                "cid": 9, "status": "meta_ok",
-            },
-        }
-    )
-    _seed_risk(tmp_root, next_page=5, total=99)
-    transport = FakeTransport(
-        [(200, ok_page([arc("BV1A")], total=1))],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 0
-    entries = ManifestStore(root=tmp_root).load()
-    assert set(entries) >= {"BVOLD:p0", "BV1A:p0"}
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "complete"
-    assert _cursor(tmp_root).resume_start_page(23191782) is None
-
-
-def test_cli_limit_pages_counts_this_call(tmp_root, fast_sleep, monkeypatch):
-    """R3: --resume from next_page=5 plus --limit-pages 2 fetches two pages."""
-    _seed_risk(tmp_root, next_page=5, total=300)
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1E")], total=300)),
-            (200, ok_page([arc("BV1F")], total=300)),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main([
-        "fetch-meta", "--mid", "23191782", "--resume", "--limit-pages", "2",
-        "--archive-root", tmp_root,
-    ])
-    assert rc == 0
-    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
-    assert [c["params"]["pn"] for c in page_calls] == [5, 6]
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "limited"
-    assert cursor["next_page"] == 7
+# (fetch-meta CLI resume/limited/complete behavior moved to the SQLite
+# metadata path: tests/test_metadata_cli.py and tests/test_metadata_e2e.py)
 
 
 def test_fetch_pages_stops_at_last_catalog_page(fast_sleep):
@@ -335,37 +176,6 @@ def test_fetch_pages_stops_when_nonempty_adds_no_new(fast_sleep):
     assert client.enumeration_complete is True
 
 
-def test_cli_full_recrawl_walks_catalog_despite_page1_overlap(
-    tmp_root, fast_sleep, monkeypatch,
-):
-    """F-005: without --resume, overlapping JSONL must not stop after page 1."""
-    ManifestStore(root=tmp_root).save(
-        {
-            "BV1A:p0": {
-                "work_id": "BV1A:p0", "bvid": "BV1A", "page_index": 0,
-                "cid": 1, "status": "meta_ok", "title": "stale",
-            },
-        }
-    )
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A", title="fresh")], total=60)),
-            (200, ok_page([arc("BV1B")], total=60)),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 0
-    page_calls = [c for c in transport.calls if "recArchivesByKeywords" in c["url"]]
-    assert [c["params"]["pn"] for c in page_calls] == [1, 2]
-    entries = ManifestStore(root=tmp_root).load()
-    assert set(entries) >= {"BV1A:p0", "BV1B:p0"}
-    assert entries["BV1A:p0"]["title"] == "fresh"
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "complete"
-
-
 def test_load_corrupt_cursor_notes_stderr(tmp_root, capsys):
     path = _cursor(tmp_root).path
     os.makedirs(tmp_root, exist_ok=True)
@@ -375,69 +185,6 @@ def test_load_corrupt_cursor_notes_stderr(tmp_root, capsys):
     assert "corrupt sidecar" in capsys.readouterr().err
 
 
-def test_cli_full_run_marks_complete(tmp_root, fast_sleep, monkeypatch, capsys):
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A"), arc("BV1B")], total=2)),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "enumeration: complete" in out
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "complete"
-    text = open(_cursor(tmp_root).path, encoding="utf-8").read()
-    assert "SESSDATA" not in text
-    assert "cookie" not in text.lower()
-
-
-def test_cli_page2_stop_resume_is_idempotent(tmp_root, fast_sleep, monkeypatch):
-    """Risk stop on page 2 → next_page=2; --resume starts there with no dup rows."""
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1A"), arc("BV1B")], total=33)),
-            (412, None), (412, None), (412, None), (412, None), (412, None),
-        ],
-        spi=[SPI_OK, SPI_NEW],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: fast_sleep)
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-    cursor = _cursor(tmp_root).load()
-    assert cursor["state"] == "risk_interrupted"
-    assert cursor["next_page"] == 2
-    store = ManifestStore(root=tmp_root)
-    first = store.load()
-    assert set(first) == {"BV1A:p0", "BV1B:p0"}
-    assert cursor["state"] != "complete"
-
-    transport2 = FakeTransport(
-        [
-            (200, ok_page([arc("BV1C")], total=33)),
-            (200, ok_page([], total=33)),
-            (200, ok_page([], total=33)),
-        ],
-    )
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport2)
-    rc2 = main([
-        "fetch-meta", "--mid", "23191782", "--resume",
-        "--archive-root", tmp_root,
-    ])
-    assert rc2 == 0
-    page_calls = [c for c in transport2.calls if "recArchivesByKeywords" in c["url"]]
-    assert page_calls[0]["params"]["pn"] == 2
-    entries = store.load()
-    assert set(entries) == {"BV1A:p0", "BV1B:p0", "BV1C:p0"}
-    lines = open(store.path, encoding="utf-8").read().strip().splitlines()
-    work_ids = [json.loads(line)["work_id"] for line in lines]
-    assert len(work_ids) == len(set(work_ids))
-    assert _cursor(tmp_root).load()["state"] == "complete"
-
-
 def test_cursor_strips_extra_keys_and_rejects_secrets(tmp_root):
     store = _cursor(tmp_root)
     stored = store.replace_atomic(
diff --git a/bilibili-asr-archive/tests/test_metadata_cli.py b/bilibili-asr-archive/tests/test_metadata_cli.py
new file mode 100644
index 0000000..5c36f37
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_metadata_cli.py
@@ -0,0 +1,743 @@
+"""Offline metadata CLI contract tests for the SQLite command path.
+
+All coverage is offline: ``fetch-meta`` drives the real product gateway
+adapter (``bili_asr.sources.bilibili_api_gateway.BilibiliApiGateway``) over
+the fake ``bilibili_api`` package seam from ``tests/fixtures/``, while
+``status`` and ``runs`` read a temporary SQLite database.  Every test also
+pins the no-legacy-sidecar and no-credential boundaries of the metadata CLI
+contract:
+
+- ``fetch-meta`` creates exactly ``{archive_root}/archive.db`` and never
+  writes ``manifest/manifest.jsonl``, ``meta-cursor.json`` or
+  ``run-ledger.jsonl``.
+- ``status``/``runs`` fail clearly with exit 1 when that database is
+  missing, and read only the fresh database.
+- Exit taxonomy: 0 success, 1 usage/configuration error, 2 terminal gateway
+  failure with the cursor unchanged.
+"""
+
+from __future__ import annotations
+
+import itertools
+import os
+import time
+
+import pytest
+
+from bili_asr.cli import build_parser, main
+from bili_asr.config import (
+    DEFAULT_MID,
+    DEFAULT_PAGE_LIMIT,
+    load_metadata_config,
+    redact_sessdata,
+)
+from bili_asr.storage import MetadataRepository, open_database
+from bili_asr.storage.models import IngestionRunRecord
+from fixtures.fake_bilibili_gateway import (
+    MID,
+    SESSDATA_BOUNDARY_VALUE,
+    UPSTREAM_ERROR_TEXT,
+    FakeResponseCodeException,
+    assert_leaks_no_markers,
+    bilibili_api_seam,
+    make_part_item,
+    make_vlist_item,
+    make_videos_response,
+    persisted_row_text,
+)
+
+LEGACY_SIDECAR_PATHS = (
+    os.path.join("manifest", "manifest.jsonl"),
+    "meta-cursor.json",
+    "run-ledger.jsonl",
+)
+
+
+def _script_upstream(
+    script,
+    *,
+    pages: dict[int, list[dict]],
+    parts: list[dict] | None = None,
+) -> None:
+    """Script the fake upstream: named pages, missing pages come back empty."""
+
+    def videos_response(pn: int, ps: int):
+        items = pages.get(pn, [])
+        return make_videos_response(*items, count=len(items))
+
+    script.videos_response = videos_response
+    script.parts_response = parts
+
+
+@pytest.fixture
+def _ingest_clock(monkeypatch: pytest.MonkeyPatch):
+    """Deterministic monotonic clock for ingestor-produced records.
+
+    Patching the ingestor module's clock keeps run/page timestamps strictly
+    increasing, so newest-first output order is testable without real sleeps.
+    """
+
+    counter = itertools.count(1)
+    monkeypatch.setattr(
+        "bili_asr.services.metadata_ingest._now", lambda: next(counter)
+    )
+
+
+def _collect_once(
+    tmp_root: str,
+    script,
+    *,
+    bvid: str,
+    part_count: int = 1,
+    limit_pages: int | None = None,
+    sessdata: str | None = None,
+    aid: int | None = None,
+) -> str:
+    """Run one scripted ``fetch-meta`` invocation and return its run id.
+
+    The invocation itself is asserted to exit 0.  ``aid`` overrides the
+    fixture's default video aid so a test that collects several distinct
+    videos into one database keeps them unique on ``videos.aid``.
+    """
+
+    summary_item = (
+        make_vlist_item(bvid=bvid)
+        if aid is None
+        else make_vlist_item(bvid=bvid, aid=aid)
+    )
+    _script_upstream(
+        script,
+        pages={1: [summary_item]},
+        parts=[
+            make_part_item(cid=2222 + index, page=index + 1)
+            for index in range(part_count)
+        ],
+    )
+    argv = ["fetch-meta", "--archive-root", tmp_root]
+    if limit_pages is not None:
+        argv += ["--limit-pages", str(limit_pages)]
+    if sessdata is not None:
+        argv += ["--sessdata", sessdata]
+    assert main(argv) == 0
+    return _newest_run_id(tmp_root)
+
+
+def _newest_run_id(tmp_root: str) -> str:
+    """Return the id of the newest ingestion run in the root's database."""
+
+    connection = open_database(tmp_root)
+    try:
+        run_row = connection.execute(
+            "SELECT run_id FROM ingestion_runs"
+            " ORDER BY started_at DESC, run_id DESC LIMIT 1"
+        ).fetchone()
+        assert run_row is not None
+        return str(run_row["run_id"])
+    finally:
+        connection.close()
+
+
+def _cursor_row(connection):
+    return connection.execute(
+        "SELECT mid, next_page, observed_total, state, last_error_code, updated_at"
+        " FROM ingestion_cursors"
+    ).fetchone()
+
+
+def _run_lines(output: str) -> list[str]:
+    return [line for line in output.splitlines() if line.startswith("run ")]
+
+
+# ---------------------------------------------------------------- parser behavior
+
+
+def test_fetch_meta_help_documents_contract_arguments_and_default_bound(
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """The parser advertises the metadata CLI contract and its page bound."""
+
+    parser = build_parser()
+    with pytest.raises(SystemExit) as exit_info:
+        parser.parse_args(["fetch-meta", "--help"])
+    assert exit_info.value.code == 0
+    help_text = capsys.readouterr().out
+    for argument in (
+        "--mid",
+        "--start-page",
+        "--limit-pages",
+        "--resume",
+        "--archive-root",
+        "--sessdata",
+    ):
+        assert argument in help_text
+    assert str(DEFAULT_PAGE_LIMIT) in help_text
+    assert "default" in help_text.lower()
+
+
+def test_resume_and_start_page_are_mutually_exclusive(
+    tmp_root: str, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """--resume and --start-page cannot be combined (usage error, exit 1)."""
+
+    with pytest.raises(SystemExit) as exit_info:
+        main(
+            [
+                "fetch-meta",
+                "--archive-root",
+                tmp_root,
+                "--resume",
+                "--start-page",
+                "2",
+            ]
+        )
+    assert exit_info.value.code == 1
+
+
+@pytest.mark.parametrize(
+    "argv_tail",
+    [["--start-page", "0"], ["--limit-pages", "0"], ["--limit-pages", "-1"]],
+    ids=["start-page-zero", "limit-pages-zero", "limit-pages-negative"],
+)
+def test_non_positive_page_arguments_exit_one(
+    tmp_root: str, argv_tail: list[str], capsys: pytest.CaptureFixture[str]
+) -> None:
+    """Page arguments must be positive integers (exit 1, bounded message)."""
+
+    assert main(["fetch-meta", "--archive-root", tmp_root, *argv_tail]) == 1
+    error_text = capsys.readouterr().err
+    assert "positive" in error_text
+    assert "Traceback" not in error_text
+
+
+# ---------------------------------------------------------------- configuration
+
+
+def test_sessdata_resolves_flag_over_environment(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """SESSDATA comes from --sessdata, else BILI_SESSDATA, else absent."""
+
+    parser = build_parser()
+    monkeypatch.setenv("BILI_SESSDATA", "env-cookie")
+    assert load_metadata_config(parser.parse_args(["fetch-meta"])).sessdata == "env-cookie"
+    assert (
+        load_metadata_config(
+            parser.parse_args(["fetch-meta", "--sessdata", "flag-cookie"])
+        ).sessdata
+        == "flag-cookie"
+    )
+    monkeypatch.delenv("BILI_SESSDATA", raising=False)
+    assert load_metadata_config(parser.parse_args(["fetch-meta"])).sessdata is None
+
+
+def test_sessdata_display_path_is_redacted() -> None:
+    """Display/debug helpers show presence only, never the credential value."""
+
+    assert redact_sessdata(None) == "absent"
+    masked = redact_sessdata(SESSDATA_BOUNDARY_VALUE)
+    assert masked != SESSDATA_BOUNDARY_VALUE
+    assert SESSDATA_BOUNDARY_VALUE not in masked
+
+
+def test_metadata_config_repr_hides_sessdata(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """The config repr never carries the SESSDATA value."""
+
+    parser = build_parser()
+    config = load_metadata_config(
+        parser.parse_args(["fetch-meta", "--sessdata", SESSDATA_BOUNDARY_VALUE])
+    )
+    assert SESSDATA_BOUNDARY_VALUE not in repr(config)
+
+
+def test_default_page_bound_is_bounded_not_unbounded() -> None:
+    """Full-collection runs are bounded by the documented default (C1)."""
+
+    assert isinstance(DEFAULT_PAGE_LIMIT, int)
+    assert DEFAULT_PAGE_LIMIT >= 1
+    assert DEFAULT_MID == 23191782
+
+
+# ---------------------------------------------------------------- fetch-meta
+
+
+@pytest.mark.parametrize("part_count", [1, 2], ids=["single-part", "multipart"])
+def test_fetch_meta_creates_fresh_database_and_completes(
+    tmp_root: str,
+    bilibili_api_seam,
+    part_count: int,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """One scripted page lands normalized rows, a completing cursor, exit 0."""
+
+    bvid = "BV1SEAMRUNAA"
+    _collect_once(tmp_root, bilibili_api_seam, bvid=bvid, part_count=part_count)
+
+    assert os.path.isfile(os.path.join(tmp_root, "archive.db"))
+    connection = open_database(tmp_root)
+    try:
+        assert connection.execute("SELECT COUNT(*) FROM bilibili_users").fetchone()[0] == 1
+        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
+        assert (
+            connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0]
+            == part_count
+        )
+        run_row = connection.execute(
+            "SELECT mid, outcome, requested_page_limit FROM ingestion_runs"
+        ).fetchone()
+        assert run_row["mid"] == MID
+        assert run_row["outcome"] == "complete"
+        assert run_row["requested_page_limit"] == DEFAULT_PAGE_LIMIT
+        cursor_row = _cursor_row(connection)
+        assert tuple(cursor_row)[:5] == (MID, 2, 0, "complete", None)
+        pending = MetadataRepository(connection).list_pending_parts()
+        assert [row["work_id"] for row in pending] == [
+            f"{bvid}:p{index}" for index in range(part_count)
+        ]
+    finally:
+        connection.close()
+
+    out, err = capsys.readouterr()
+    # page_count mirrors v_ingestion_run_stats: one evidence row per page
+    # the run touched, including the completing empty page.
+    assert "2 page(s)" in out
+    assert "state=complete" in out
+    assert err == ""
+    for relative in LEGACY_SIDECAR_PATHS:
+        assert not os.path.exists(os.path.join(tmp_root, relative))
+
+    # The pinned adapter drove exactly the documented upstream calls: one
+    # page fetch, one parts fetch, one empty-page fetch (aid present, so no
+    # detail call).
+    assert bilibili_api_seam.calls == [
+        "user.get_videos(pn=1, ps=100)",
+        "video.get_pages",
+        "user.get_videos(pn=2, ps=100)",
+    ]
+
+
+def test_fetch_meta_limit_pages_stops_limited_exit_zero(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """An explicit --limit-pages ends the run as limited (still exit 0)."""
+
+    _script_upstream(
+        bilibili_api_seam,
+        pages={
+            1: [make_vlist_item(bvid="BV1LIMITSTO1")],
+            2: [make_vlist_item(bvid="BV1LIMITSTO2")],
+        },
+        parts=[make_part_item(cid=2222)],
+    )
+    exit_code = main(["fetch-meta", "--archive-root", tmp_root, "--limit-pages", "1"])
+
+    assert exit_code == 0
+    out, _err = capsys.readouterr()
+    assert "outcome=limited" in out
+    assert "complete" not in out
+    connection = open_database(tmp_root)
+    try:
+        run_row = connection.execute(
+            "SELECT outcome, requested_page_limit FROM ingestion_runs"
+        ).fetchone()
+        assert run_row["outcome"] == "limited"
+        assert run_row["requested_page_limit"] == 1
+        assert connection.execute(
+            "SELECT state FROM ingestion_cursors"
+        ).fetchone()[0] == "limited"
+    finally:
+        connection.close()
+    assert [
+        call for call in bilibili_api_seam.calls if call.startswith("user.get_videos")
+    ] == ["user.get_videos(pn=1, ps=100)"]
+
+
+def test_fetch_meta_start_page_overrides_cursor(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """--start-page ignores the stored cursor and starts at the given page."""
+
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1FIRSTPG11")
+
+    _script_upstream(
+        bilibili_api_seam,
+        pages={1: [make_vlist_item(bvid="BV1RESTARTP1", aid=222)]},
+        parts=[make_part_item(cid=3333)],
+    )
+    assert main(["fetch-meta", "--archive-root", tmp_root, "--start-page", "1"]) == 0
+
+    # Page 1 was requested again even though the stored cursor pointed at 2.
+    assert bilibili_api_seam.calls.count("user.get_videos(pn=1, ps=100)") == 2
+    connection = open_database(tmp_root)
+    try:
+        start_pages = [
+            row[0]
+            for row in connection.execute(
+                "SELECT requested_start_page FROM ingestion_runs"
+            ).fetchall()
+        ]
+        assert start_pages == [1, 1]
+    finally:
+        connection.close()
+    assert capsys.readouterr().err == ""
+
+
+def test_fetch_meta_without_flags_resumes_from_stored_cursor(
+    tmp_root: str,
+    bilibili_api_seam,
+    capsys: pytest.CaptureFixture[str],
+    _ingest_clock,
+) -> None:
+    """Without --resume/--start-page the run continues at the cursor page."""
+
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1CURSORPG1")
+
+    _script_upstream(
+        bilibili_api_seam,
+        pages={2: [make_vlist_item(bvid="BV1CURSORPG2", aid=333)]},
+        parts=[make_part_item(cid=4444)],
+    )
+    assert main(["fetch-meta", "--archive-root", tmp_root]) == 0
+
+    # Page 1 was not refetched: the run resumed at the cursor's page 2,
+    # while run 1's own completion check already touched page 2.
+    assert bilibili_api_seam.calls.count("user.get_videos(pn=1, ps=100)") == 1
+    connection = open_database(tmp_root)
+    try:
+        start_pages = [
+            row[0]
+            for row in connection.execute(
+                "SELECT requested_start_page FROM ingestion_runs"
+                " ORDER BY started_at"
+            ).fetchall()
+        ]
+        assert start_pages == [1, 2]
+    finally:
+        connection.close()
+
+
+def test_fetch_meta_resume_requires_cursor_without_database(
+    tmp_root: str, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """--resume with no database fails clearly (exit 1) and creates nothing."""
+
+    assert main(["fetch-meta", "--archive-root", tmp_root, "--resume"]) == 1
+    error_text = capsys.readouterr().err
+    assert "no archive database" in error_text
+    assert not os.path.isfile(os.path.join(tmp_root, "archive.db"))
+
+
+def test_fetch_meta_resume_requires_cursor_in_existing_database(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """--resume on an existing cursor-less database fails clearly (exit 1)."""
+
+    connection = open_database(tmp_root)
+    connection.close()
+    assert main(["fetch-meta", "--archive-root", tmp_root, "--resume"]) == 1
+    assert "cursor" in capsys.readouterr().err
+
+
+@pytest.mark.parametrize(
+    ("upstream_code", "expected_code"),
+    [(-412, "rate_limited"), (-400, "response_error")],
+    ids=["rate-limited", "response-error"],
+)
+def test_fetch_meta_upstream_failure_exits_two_with_cursor_unchanged(
+    tmp_root: str,
+    bilibili_api_seam,
+    upstream_code: int,
+    expected_code: str,
+    capsys: pytest.CaptureFixture[str],
+    _ingest_clock,
+) -> None:
+    """A failed page is terminal for the run (exit 2); the cursor never moves."""
+
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1FIRSTPG11")
+    connection = open_database(tmp_root)
+    try:
+        cursor_before = _cursor_row(connection)
+        assert cursor_before is not None
+    finally:
+        connection.close()
+
+    script = bilibili_api_seam
+    script.videos_response = None
+    script.parts_response = None
+    script.info_response = None
+    script.videos_error = FakeResponseCodeException(upstream_code, UPSTREAM_ERROR_TEXT)
+    assert main(["fetch-meta", "--archive-root", tmp_root]) == 2
+
+    connection = open_database(tmp_root)
+    try:
+        cursor_after = _cursor_row(connection)
+        assert tuple(cursor_after) == tuple(cursor_before)
+        newest_run_id = connection.execute(
+            "SELECT run_id FROM ingestion_runs"
+            " ORDER BY started_at DESC, run_id DESC LIMIT 1"
+        ).fetchone()[0]
+        failed_pages = connection.execute(
+            "SELECT outcome, error_code FROM ingestion_pages"
+            " WHERE run_id = ? AND outcome != 'ok'",
+            (newest_run_id,),
+        ).fetchall()
+        expected_outcome = (
+            "risk_interrupted" if expected_code == "rate_limited" else "failed"
+        )
+        assert [tuple(row) for row in failed_pages] == [
+            (expected_outcome, expected_code)
+        ]
+        run_row = connection.execute(
+            "SELECT outcome FROM ingestion_runs ORDER BY started_at DESC, run_id DESC"
+        ).fetchone()
+        assert run_row["outcome"] == expected_outcome
+    finally:
+        connection.close()
+
+    out, err = capsys.readouterr()
+    assert expected_code in err
+    assert "cursor unchanged" in err
+    assert_leaks_no_markers(out + err, context="fetch-meta failure output")
+
+
+def test_fetch_meta_unexpected_error_is_bounded_exit_two_no_traceback(
+    tmp_root: str,
+    bilibili_api_seam,
+    monkeypatch: pytest.MonkeyPatch,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """Non-gateway exceptions map to the terminal exit with a generic message."""
+
+    class _UnexpectedIngestor:
+        def __init__(self, gateway, repository) -> None:
+            del gateway, repository
+
+        def collect_user_pages(self, *args, **kwargs):
+            raise RuntimeError("raw-unexpected-payload-sentinel")
+
+    monkeypatch.setattr("bili_asr.services.MetadataIngestor", _UnexpectedIngestor)
+
+    assert main(["fetch-meta", "--archive-root", tmp_root]) == 2
+    out, err = capsys.readouterr()
+    assert err == "fetch-meta: unexpected error\n"
+    assert "raw-unexpected-payload-sentinel" not in out + err
+    assert "Traceback" not in err
+
+
+@pytest.mark.parametrize("fail_upstream", [False, True], ids=["success", "failure"])
+def test_fetch_meta_never_writes_legacy_sidecars(
+    tmp_root: str, bilibili_api_seam, fail_upstream: bool, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """No command path creates the old JSONL/cursor/ledger sidecars."""
+
+    script = bilibili_api_seam
+    if fail_upstream:
+        script.videos_error = FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT)
+    else:
+        _script_upstream(script, pages={1: [make_vlist_item(bvid="BV1NOSIDECR1")]})
+
+    main(["fetch-meta", "--archive-root", tmp_root])
+
+    for relative in LEGACY_SIDECAR_PATHS:
+        assert not os.path.exists(os.path.join(tmp_root, relative))
+
+
+def test_fetch_meta_persists_no_secret_markers(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """The SESSDATA value never reaches output or any persisted row."""
+
+    _collect_once(
+        tmp_root,
+        bilibili_api_seam,
+        bvid="BV1NOSECRET1",
+        sessdata=SESSDATA_BOUNDARY_VALUE,
+    )
+
+    out, err = capsys.readouterr()
+    assert_leaks_no_markers(out + err, context="fetch-meta output")
+    connection = open_database(tmp_root)
+    try:
+        assert_leaks_no_markers(
+            persisted_row_text(connection), context="fetch-meta persisted rows"
+        )
+    finally:
+        connection.close()
+
+
+# ---------------------------------------------------------------- status
+
+
+def test_status_fails_clearly_when_database_missing(
+    tmp_root: str, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """A read command on a fresh root exits 1 with a bounded configuration error."""
+
+    assert main(["status", "--archive-root", tmp_root]) == 1
+    out, err = capsys.readouterr()
+    assert "no archive database" in err
+    assert out == ""
+
+
+def test_status_reports_counts_pending_and_cursor_from_sqlite(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """status counts entities and pending work from the fresh database only."""
+
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1STATUSPRB", part_count=2)
+
+    assert main(["status", "--archive-root", tmp_root]) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert "users: 1" in out
+    assert "videos: 1" in out
+    assert "parts: 2" in out
+    assert "discovered=2" in out
+    assert "pending: 2" in out
+    assert "BV1STATUSPRB:p0" in out
+    assert "BV1STATUSPRB:p1" in out
+    assert "state=complete" in out
+
+
+def test_status_ignores_legacy_sidecar_rows(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """status never reads or rewrites legacy metadata sidecars."""
+
+    from bili_asr.manifest import ManifestStore
+
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1STATUSPU1")
+    legacy_store = ManifestStore(root=tmp_root)
+    legacy_store.upsert(
+        {"work_id": "BV1LEGACYROW:p0", "bvid": "BV1LEGACYROW", "status": "archived"}
+    )
+    legacy_cursor_path = os.path.join(tmp_root, "meta-cursor.json")
+    with open(legacy_cursor_path, "w", encoding="utf-8") as cursor_handle:
+        cursor_handle.write('{"mid": 1, "state": "legacy-cursor-state"}\n')
+
+    assert main(["status", "--archive-root", tmp_root]) == 0
+    out, _err = capsys.readouterr()
+    assert "BV1LEGACYROW" not in out
+    assert "legacy-cursor-state" not in out
+    assert os.path.isfile(legacy_cursor_path)
+    assert os.path.isfile(os.path.join(tmp_root, "manifest", "manifest.jsonl"))
+
+
+# ---------------------------------------------------------------- runs
+
+
+def test_runs_fails_clearly_when_database_missing(
+    tmp_root: str, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """runs on a fresh root exits 1 with a bounded configuration error."""
+
+    assert main(["runs", "--archive-root", tmp_root]) == 1
+    out, err = capsys.readouterr()
+    assert "no archive database" in err
+    assert out == ""
+
+
+def test_runs_empty_database_prints_empty_exit_zero(
+    tmp_root: str, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """An existing database without runs prints runs: empty (exit 0)."""
+
+    connection = open_database(tmp_root)
+    connection.close()
+    assert main(["runs", "--archive-root", tmp_root]) == 0
+    out, _err = capsys.readouterr()
+    assert "runs: empty" in out
+
+
+def test_runs_rejects_non_positive_limit(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
+) -> None:
+    """--limit must be a positive integer when given (exit 1)."""
+
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA1")
+    assert main(["runs", "--archive-root", tmp_root, "--limit", "0"]) == 1
+    error_text = capsys.readouterr().err
+    assert "positive" in error_text
+    assert "Traceback" not in error_text
+
+
+def test_runs_lists_newest_first_and_renders_running_rows(
+    tmp_root: str,
+    bilibili_api_seam,
+    capsys: pytest.CaptureFixture[str],
+    _ingest_clock,
+) -> None:
+    """Runs output is newest-first and includes non-terminal running rows (C2)."""
+
+    first_run_id = _collect_once(
+        tmp_root, bilibili_api_seam, bvid="BV1RUNHIST1A", aid=441
+    )
+    second_run_id = _collect_once(
+        tmp_root, bilibili_api_seam, bvid="BV1RUNHIST2A", aid=442
+    )
+    stub_run_id = "stub-running-run-0001"
+    connection = open_database(tmp_root)
+    try:
+        MetadataRepository(connection).start_run(
+            IngestionRunRecord(
+                run_id=stub_run_id,
+                mid=MID,
+                source_package="bilibili-api-python",
+                source_version="17.4.2",
+                requested_start_page=1,
+                requested_page_limit=DEFAULT_PAGE_LIMIT,
+                started_at=int(time.time()) + 60,
+                outcome="running",
+            )
+        )
+    finally:
+        connection.close()
+
+    assert main(["runs", "--archive-root", tmp_root]) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    run_ids = [line.split()[1] for line in out.splitlines() if line.startswith("run ")]
+    assert len(run_ids) == 3
+    assert run_ids[0] == stub_run_id
+    assert "outcome=running" in out
+    assert {first_run_id, second_run_id} <= set(run_ids)
+
+
+def test_runs_limit_shows_only_recent_rows(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str], _ingest_clock
+) -> None:
+    """--limit bounds the runs listing to the most recent rows."""
+
+    oldest_run_id = _collect_once(
+        tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA1", aid=451
+    )
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA2", aid=452)
+    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA3", aid=453)
+
+    assert main(["runs", "--archive-root", tmp_root, "--limit", "2"]) == 0
+    out, _err = capsys.readouterr()
+    run_lines = _run_lines(out)
+    assert len(run_lines) == 2
+    assert oldest_run_id not in out
+
+
+def test_runs_shows_bounded_error_codes_only(
+    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str], _ingest_clock
+) -> None:
+    """A failed run renders its bounded scalar code, never upstream payload text."""
+
+    first_run_id = _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNCOMPL1")
+    script = bilibili_api_seam
+    script.videos_response = None
+    script.parts_response = None
+    script.info_response = None
+    script.videos_error = FakeResponseCodeException(-400, UPSTREAM_ERROR_TEXT)
+    assert main(["fetch-meta", "--archive-root", tmp_root]) == 2
+
+    assert main(["runs", "--archive-root", tmp_root]) == 0
+    out, _err = capsys.readouterr()
+    assert f"run {first_run_id}" in out and "outcome=complete" in out
+    assert "outcome=failed" in out
+    assert "error=response_error" in out
+    assert_leaks_no_markers(out, context="runs output")
diff --git a/bilibili-asr-archive/tests/test_persistence_scale.py b/bilibili-asr-archive/tests/test_persistence_scale.py
index 11079c9..c9186e0 100644
--- a/bilibili-asr-archive/tests/test_persistence_scale.py
+++ b/bilibili-asr-archive/tests/test_persistence_scale.py
@@ -440,6 +440,12 @@ def test_cli_dispatch_locks_every_archive_mutation(
         yield
 
     monkeypatch.setattr(coordinator, "archive_writer", busy_writer)
+    # status is a read command: it never takes the writer lock, so it
+    # succeeds against an existing fresh database while the writer lock
+    # stays busy.
+    from bili_asr.storage import open_database
+
+    open_database(os.fspath(tmp_path)).close()
     assert cli.main(["status", "--archive-root", os.fspath(tmp_path)]) == 0
     capsys.readouterr()
     assert cli.main([
diff --git a/bilibili-asr-archive/tests/test_run_ledger.py b/bilibili-asr-archive/tests/test_run_ledger.py
index 2d15776..748751a 100644
--- a/bilibili-asr-archive/tests/test_run_ledger.py
+++ b/bilibili-asr-archive/tests/test_run_ledger.py
@@ -32,7 +32,7 @@ from test_audio import (
     nav_response,
     playurl_ok,
 )
-from test_fetch_meta import FakeTransport, FastSleeper, SPI_NEW, arc, ok_page
+from test_fetch_meta import FastSleeper
 from test_subtitles import SAMPLE_DOC, nav_ok, player_ok, sub_entry
 
 
@@ -313,81 +313,9 @@ def test_bili_client_does_not_import_run_ledger():
     assert "run_ledger" not in src
 
 
-# ---------------------------------------------------------------- CLI fetch-meta wiring
-
-
-def test_cli_fetch_meta_exit_0_appends_ledger(tmp_root, fast_sleep, monkeypatch, capsys):
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1"), arc("BV2")], total=2)),
-        ],
-    )
-    _patch_client(monkeypatch, transport, sleeper=fast_sleep)
-
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 0
-
-    ledger = RunLedger(root=tmp_root)
-    records = ledger.load()
-    assert len(records) == 1
-    rec = records[0]
-    assert rec["command"] == "fetch-meta"
-    assert rec["exit_code"] == 0
-    assert rec["mid"] == 23191782
-    assert rec["pages_fetched"] == 1
-    assert rec["records_fetched"] == 2
-    assert rec["coverage_summary"] == {"meta_ok": 2}
-    assert rec["cursor_snapshot"] is not None
-    assert rec["cursor_snapshot"]["state"] == "complete"
-    assert rec["cursor_snapshot"]["mid"] == 23191782
-    assert rec["last_api_error_code"] is None
-
-
-def test_cli_fetch_meta_exit_2_risk_appends_ledger(tmp_root, fast_sleep, monkeypatch, capsys):
-    transport = FakeTransport(
-        [
-            (200, ok_page([arc("BV1")], total=99)),
-            (412, None), (412, None), (412, None), (412, None), (412, None),
-        ],
-        spi=[SPI_OK, SPI_NEW],
-    )
-    _patch_client(monkeypatch, transport, sleeper=fast_sleep)
-
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-
-    ledger = RunLedger(root=tmp_root)
-    records = ledger.load()
-    assert len(records) == 1
-    rec = records[0]
-    assert rec["command"] == "fetch-meta"
-    assert rec["exit_code"] == 2
-    assert rec["last_api_error_code"] is not None
-    assert rec["cursor_snapshot"] is not None
-    assert rec["cursor_snapshot"]["state"] == "risk_interrupted"
-
-
-def test_cli_fetch_meta_exit_2_gone_appends_ledger(tmp_root, fast_sleep, monkeypatch, capsys):
-    transport = FakeTransport(
-        [
-            (200, {"code": -404, "message": "not found"}),
-        ],
-    )
-    _patch_client(monkeypatch, transport, sleeper=fast_sleep)
-
-    rc = main(["fetch-meta", "--mid", "23191782", "--archive-root", tmp_root])
-    assert rc == 2
-
-    ledger = RunLedger(root=tmp_root)
-    records = ledger.load()
-    assert len(records) == 1
-    rec = records[0]
-    assert rec["command"] == "fetch-meta"
-    assert rec["exit_code"] == 2
-    assert rec["last_api_error_code"] == -404
-
-
 # ---------------------------------------------------------------- CLI pilot wiring
+# (fetch-meta no longer appends JSONL ledger records: the SQLite metadata
+# path writes normalized runs; see tests/test_metadata_cli.py)
 
 
 def _pilot_row(identity, *, duration_s, title="clip"):
@@ -536,183 +464,6 @@ def test_format_run_summary():
     assert "(2026-08-25T10:00:00Z)" in line
 
 
-def test_cli_status_empty_archive(tmp_root, capsys):
-    rc = main(["status", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "manifest: empty" in out
-    assert "runs: 0" in out
-
-
-def test_cli_status_with_manifest_and_runs(tmp_root, capsys):
-    store = ManifestStore(root=tmp_root)
-    store.upsert({"work_id": "BV1:p0", "bvid": "BV1", "status": "archived"})
-    store.upsert({"work_id": "BV2:p0", "bvid": "BV2", "status": "meta_ok"})
-
-    ledger = RunLedger(root=tmp_root)
-    ledger.append(
-        build_run_record(
-            command="fetch-meta",
-            started_at="2026-08-25T10:00:00Z",
-            finished_at="2026-08-25T10:01:00Z",
-            exit_code=0,
-            run_id="run-1",
-            coverage_summary={"meta_ok": 2},
-            cursor_snapshot={
-                "mid": 23191782,
-                "next_page": 2,
-                "total": 2,
-                "state": "complete",
-                "last_api_error_code": None,
-                "updated_at": utc_now_iso(),
-            },
-        )
-    )
-    ledger.append(
-        build_run_record(
-            command="pilot",
-            started_at="2026-08-25T10:02:00Z",
-            finished_at="2026-08-25T10:03:00Z",
-            exit_code=0,
-            run_id="run-2",
-            coverage_summary={"archived": 1, "meta_ok": 1},
-        )
-    )
-
-    rc = main(["status", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "archived: 1" in out
-    assert "meta_ok: 1" in out
-    assert "runs: 2" in out
-    assert "latest run: run-2 (pilot, exit 0, 2026-08-25T10:03:00Z)" in out
-    assert "latest cursor: none" in out
-    assert "latest coverage: archived: 1, meta_ok: 1" in out
-
-
-def test_cli_status_limited_cursor_does_not_claim_full_enumeration(tmp_root, capsys):
-    ledger = RunLedger(root=tmp_root)
-    ledger.append(
-        build_run_record(
-            command="fetch-meta",
-            started_at="2026-08-25T10:00:00Z",
-            finished_at="2026-08-25T10:01:00Z",
-            exit_code=0,
-            run_id="run-limit",
-            coverage_summary={"meta_ok": 30},
-            cursor_snapshot={
-                "mid": 23191782,
-                "next_page": 2,
-                "total": 100,
-                "state": "limited",
-                "last_api_error_code": None,
-                "updated_at": utc_now_iso(),
-            },
-        )
-    )
-
-    rc = main(["status", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "latest cursor: limited (next_page 2, observed_total 100)" in out
-    assert "complete" not in out.lower()
-
-
-def test_cli_runs_empty(tmp_root, capsys):
-    rc = main(["runs", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "runs: empty" in out
-
-
-def test_cli_runs_listing_and_limit(tmp_root, capsys):
-    ledger = RunLedger(root=tmp_root)
-    for i in range(1, 4):
-        ledger.append(
-            build_run_record(
-                command="fetch-meta" if i == 1 else "pilot",
-                started_at=f"2026-08-25T10:0{i}:00Z",
-                finished_at=f"2026-08-25T10:0{i}:30Z",
-                exit_code=0,
-                run_id=f"run-{i}",
-                coverage_summary={"archived": i},
-            )
-        )
-
-    # All runs
-    rc = main(["runs", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "run-1" in out
-    assert "run-2" in out
-    assert "run-3" in out
-
-    # Limit 2 -> shows run-2 and run-3
-    rc = main(["runs", "--limit", "2", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "run-1" not in out
-    assert "run-2" in out
-    assert "run-3" in out
-
-    # Limit 0 -> runs: empty
-    rc = main(["runs", "--limit", "0", "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "runs: empty" in out
-
-
-def test_cli_runs_corrupt_lines_handled(tmp_root, capsys):
-    ledger = RunLedger(root=tmp_root)
-    ledger.append(
-        build_run_record(
-            command="fetch-meta",
-            started_at="2026-08-25T10:00:00Z",
-            finished_at="2026-08-25T10:01:00Z",
-            exit_code=0,
-            run_id="run-good-1",
-        )
-    )
-    with open(ledger.path, "a", encoding="utf-8") as fh:
-        fh.write("{bad json\n")
-    ledger.append(
-        build_run_record(
-            command="pilot",
-            started_at="2026-08-25T10:02:00Z",
-            finished_at="2026-08-25T10:03:00Z",
-            exit_code=0,
-            run_id="run-good-2",
-        )
-    )
-
-    rc = main(["runs", "--archive-root", tmp_root])
-    assert rc == 0
-    captured = capsys.readouterr()
-    assert "run-good-1" in captured.out
-    assert "run-good-2" in captured.out
-    assert "run-ledger: ignoring corrupt line" in captured.err
-
-
-def test_cli_status_and_runs_redaction_guarantees(tmp_root, capsys):
-    ledger = RunLedger(root=tmp_root)
-    ledger.append(
-        build_run_record(
-            command="pilot",
-            started_at="2026-08-25T10:00:00Z",
-            finished_at="2026-08-25T10:01:00Z",
-            exit_code=0,
-            run_id="run-safe-01",
-            coverage_summary={"archived": 2},
-        )
-    )
-
-    main(["status", "--archive-root", tmp_root])
-    status_out = capsys.readouterr().out
-
-    main(["runs", "--archive-root", tmp_root])
-    runs_out = capsys.readouterr().out
-
-    for out in [status_out, runs_out]:
-        for forbidden in ["SESSDATA", "cookie", "http://", "https://", "Traceback"]:
-            assert forbidden.lower() not in out.lower()
+# (the CLI status/runs tests moved to the SQLite metadata path:
+# tests/test_metadata_cli.py)
 
```
