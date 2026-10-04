"""run / campaign / schedule handlers."""

from __future__ import annotations

import json
import sys

import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _AUDIO_BUDGET_SKIP_HINT,
    _archive_database_exists,
    _is_excluded,
    _metadata_database_path,
    _open_read_connection,
    _open_read_repository,
    _queue_source_is_manifest,
    _record_api_error,
    _resolve_sessdata,
    _store_audio_todo,
    _store_transcript_todo,
    _subtitle_schema_rebuild_line,
    _subtitle_selector,
    _todo_for_bvid,
)

def _run_scope_rows(store, entries: dict, scope: str):
    """Resolve --scope to processable (key, entry) rows.

    Returns (rows, error) where error is a message string when the scope
    could not be resolved at all.
    """
    from bili_asr import search_index
    from bili_asr.manifest import TERMINAL_STATUSES, VALID_STATUSES

    if scope == "pending":
        return (
            [
                (key, e)
                for key, e in sorted(entries.items())
                if e.get("status") in VALID_STATUSES - TERMINAL_STATUSES
                and not _is_excluded(e)
            ],
            None,
        )
    if scope == "failed":
        # failed scope: rows with a recorded failed stage attempt (qc1-S2:
        # definition lives next to the ledger in RunCoordinator).
        from bili_asr.coordinator import RunCoordinator

        failed = RunCoordinator(store.root, store).failed_work_ids()
        rows = [
            (key, e)
            for key, e in sorted(entries.items())
            if (str(e.get("work_id") or key) in failed
                or str(e.get("bvid") or "") in failed)
            and not _is_excluded(e)
            and e.get("status") not in TERMINAL_STATUSES
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

def _store_first_scope_rows(store, entries: dict, scope: str):
    """Campaign scope resolution: the store is the queue for ``pending``.

    The batch chain cut to the store outright (contract §7) — no rollback
    switch.  Every other scope (``failed`` and explicit selectors) still
    resolves against the manifest and the coordinator's attempt ledger, which
    the manifest write side owns.
    """

    if scope == "pending":
        return _store_pending_rows(store.root, "campaign")
    return _run_scope_rows(store, entries, scope)


def _cmd_campaign(args: argparse.Namespace) -> int:
    from bili_asr import bili_client
    from bili_asr.audio_budget import audio_cap_bytes
    from bili_asr.campaign import CampaignRunner
    from bili_asr.coordinator import ArchiveBusyError

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
            scope_rows=_store_first_scope_rows,
            artifact_roots=args.artifact_roots,
            # R1: the runner is the only path to the coordinator's own reclaim, so a
            # `campaign` that did not forward this would leave its documented
            # `--keep-audio/--no-keep-audio` silently inert (contract §7, D15).
            keep_audio=args.keep_audio,
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

class _RunInterrupted(BaseException):
    """Raised by the run body's one-shot ``SIGTERM`` disposition.

    A ``BaseException`` and not an ``Exception``: the coordinator's per-stage
    ``except Exception`` handlers would otherwise swallow the interruption and
    let the batch continue past it.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    """Put back the dispositions a swap captured (empty mapping = nothing to do)."""
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _ignore_interruption_signals() -> dict[int, Any]:
    """Leave ``SIGTERM``/``SIGINT`` ignored, and report what they were.

    The pair is swapped as a unit because the ignored state has to cover the
    whole unwind after the first delivery and the record write at its end, and
    that unwind is reached through ``SIGTERM`` *or* ``SIGINT``.  ``signal.signal``
    is main-thread only, so elsewhere nothing is swapped and the empty mapping
    reads as "nothing to restore".
    """
    if threading.current_thread() is not threading.main_thread():
        return {}
    return {
        signum: signal.signal(signum, signal.SIG_IGN)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }


@contextmanager
def _interruptible_run() -> Iterator[None]:
    """Deliver the first ``SIGTERM`` to the run body as ``_RunInterrupted``.

    One-shot: the exception is raised once, and the true previous dispositions
    -- ``SIGTERM`` *and* ``SIGINT`` -- come back in this context manager's
    ``finally``, after the record write.  Delivery therefore leaves both signals
    **ignored** instead of restoring the captured disposition: the ignored
    state, not the default, is what must hold across the coordinator's unwind
    (runner release, batch-evidence stderr write), because a repeated
    ``SIGTERM`` landing there at the default disposition would kill the process
    before the write site with no record at all.  ``SIGINT`` keeps CPython's
    ``KeyboardInterrupt`` until the run body catches it, and that branch
    installs the same ignored pair before it returns, so a repeated ``Ctrl-C``
    cannot abandon the write either.  ``signal.signal`` is main-thread only, so
    elsewhere the run body keeps the dispositions the process already had.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[int, Any] = {}

    def _on_sigterm(signum: int, _frame: Any) -> None:
        # The swapped-out dispositions are deliberately dropped: the ignored
        # state, not the disposition at delivery, is what must hold until the
        # write site has run.
        _ignore_interruption_signals()
        raise _RunInterrupted(signum)

    previous[signal.SIGTERM] = signal.signal(signal.SIGTERM, _on_sigterm)
    # ``SIGINT`` keeps its handler here (CPython's ``KeyboardInterrupt``), but
    # its disposition is captured so the run block puts both back.
    previous[signal.SIGINT] = signal.getsignal(signal.SIGINT)
    try:
        yield
    finally:
        _restore_signal_handlers(previous)


@contextmanager
def _signals_ignored() -> Iterator[None]:
    """Ignore ``SIGTERM``/``SIGINT`` for the duration of the record write."""
    previous = _ignore_interruption_signals()
    try:
        yield
    finally:
        _restore_signal_handlers(previous)


def _partial_run_state(root: str, started_at: str) -> tuple[list[str], dict[str, int]]:
    """Record inputs for a run interrupted before it could summarize.

    The interruption path has no ``RunSummary``: what the run already persisted
    durably is the record's input.  ``work_ids`` are the ids the attempts
    ledger recorded at or after this run's ``started_at``, in order and deduped
    (an earlier run's attempts stay out), and the coverage summary counts the
    manifest statuses as they stand.  ``records_existing`` is *not* derived
    here: it means "records that existed before this run", so the run body
    passes the count from the manifest it loaded above the batch, exactly as
    the normal path does.
    """
    from bili_asr.coordinator import AttemptLedger
    from bili_asr.manifest import ManifestStore
    from bili_asr.run_ledger import compute_coverage_summary

    attempts = AttemptLedger(root).load()
    work_ids = list(
        dict.fromkeys(a["work_id"] for a in attempts if a["started_at"] >= started_at)
    )
    entries = ManifestStore(root=root).load()
    return work_ids, compute_coverage_summary(entries)


def _write_run_record(
    root: str,
    started_at: str,
    exit_code: int,
    work_ids: list[str] | None,
    records_existing: int,
    coverage_summary: dict[str, int],
) -> None:
    """The run body's single ``run-ledger.jsonl`` write site.

    Every input is derived by the caller's branch before the call, so the guard
    that authorizes the write and the values it writes are bound together.
    """
    from bili_asr.run_ledger import RunLedger, build_run_record, utc_now_iso

    RunLedger(root=root).append(build_run_record(
        command="run", started_at=started_at, finished_at=utc_now_iso(),
        exit_code=exit_code, mid=None, work_ids=work_ids,
        records_existing=records_existing, coverage_summary=coverage_summary))


def _store_pending_rows(archive_root: str, command: str):
    """The pending work list from the store gap views, in coordinator row shape.

    Returns ``(rows, error)``; ``error`` is ``None`` on success.  The store is
    the sole queue input for the pending scope (contract §3): the manifest's
    needs_audio/derived rows are never read to decide work.  A missing or
    pre-transcript-schema store is the documented configuration error.
    """

    from bili_asr.services import queue_source as qs

    source = qs.open_queue_source(archive_root)
    if source is None:
        print(
            f"{command}: no archive database at {archive_root}; "
            "run fetch-meta to create it",
            file=sys.stderr,
        )
        return None, "no archive database"
    try:
        merged = source.select_pending_scope()
    finally:
        source.connection.close()
    return [(key, entry) for key, entry in merged.items()], None


def _cmd_run(args: argparse.Namespace) -> int:
    from bili_asr import bili_client
    from bili_asr.coordinator import ArchiveBusyError, RunCoordinator, archive_writer
    from bili_asr.manifest import ManifestStore
    from bili_asr.run_ledger import compute_coverage_summary, utc_now_iso
    from bili_asr.audio_budget import SKIP_REASON, audio_cap_bytes
    from bili_asr.services import queue_source as qs

    started_at = utc_now_iso()
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    if args.limit is not None and args.limit <= 0:
        print("run: --limit must be a positive integer", file=sys.stderr)
        return 1
    use_manifest = _queue_source_is_manifest(args)
    if use_manifest:
        qs.print_manifest_deprecation()
    if not use_manifest and args.scope == "pending":
        # Store-native pending scope: the gap views are the queue (Task 2).
        rows, error = _store_pending_rows(args.archive_root, "run")
        if error:
            return 1
    else:
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
                           max_audio_bytes=audio_cap_bytes(args.max_audio_gb),
                           artifact_roots=args.artifact_roots,
                           keep_audio=args.keep_audio)
    print(f"run: scope={args.scope} selected {len(rows)} row(s)" + (" [offline]" if args.offline else ""))
    for key, entry in rows:
        print(f"  {entry.get('work_id') or key}: {entry.get('status')}")
    exit_code: int | None = None
    interrupted: int | None = None
    try:
        with archive_writer(args.archive_root):
            with _interruptible_run():
                try:
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
                        # Q1: a budget skip names the flag that lifts it, the same words
                        # the pilot's line prints — `run` shares this line with every
                        # other skip reason, so the clause is carried only by that one.
                        hint = (
                            _AUDIO_BUDGET_SKIP_HINT
                            if r.skip_reason == SKIP_REASON
                            else ""
                        )
                        print(
                            f"run: {r.work_id}: skipped "
                            f"({r.skip_reason or 'unknown'}){hint}"
                        )
                    exit_code = 2 if summary.risk_interrupted else (0 if summary.fully_processed else 1)
                    if summary.risk_interrupted:
                        print("run: risk-control ceiling; stopping — re-run to resume.", file=sys.stderr)
                    print(f"run: {ok} completed, {len(skipped)} skipped" +
                          (f", {len(failed)} failed" if failed else "") +
                          (", scope not fully processed" if exit_code == 1 else ""))
                    return exit_code
                except _RunInterrupted as exc:
                    interrupted = exc.signum
                    return 128 + exc.signum
                except KeyboardInterrupt:
                    # `SIGINT` never reaches `_on_sigterm`, so the guard has to
                    # go up here, before this branch unwinds: at the captured
                    # default a repeated Ctrl-C raises again inside the record
                    # write's `finally` below and abandons the write.  Symmetric
                    # with the handler, and the true dispositions come back in
                    # `_interruptible_run`'s `finally` once the write is done.
                    _ignore_interruption_signals()
                    interrupted = signal.SIGINT
                    return 128 + signal.SIGINT
                finally:
                    # The run body's single record write: a normal exit and an
                    # interruption both leave exactly one run-ledger row here.
                    # `records_existing` is the pre-batch manifest count in both
                    # cases: the run body loaded that manifest above the batch,
                    # so this field means "records that existed before this run"
                    # on every path.
                    import bili_asr.cli as _cli_pkg
                    with _cli_pkg._signals_ignored():
                        try:
                            if interrupted is not None:
                                # No RunSummary exists on this path, so the
                                # record's counts come from what the run already
                                # persisted.
                                exit_code = 128 + interrupted
                                work_ids, coverage_summary = _partial_run_state(
                                    args.archive_root, started_at)
                            elif exit_code is not None:
                                work_ids = [r.work_id for r in summary.results] or None
                                coverage_summary = compute_coverage_summary(store.load())
                            if exit_code is not None:
                                _write_run_record(
                                    args.archive_root, started_at, exit_code, work_ids,
                                    len(entries), coverage_summary)
                        except Exception as exc:
                            # Never silent: on the interruption path this record
                            # is the only deliverable there is, and the process
                            # still exits with the interruption code.
                            print(f"run: run-ledger write failed ({type(exc).__name__})",
                                  file=sys.stderr)
    except ArchiveBusyError:
        print("run: archive_busy", file=sys.stderr)
        return 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    from bili_asr import bili_client
    from bili_asr.coordinator import ArchiveBusyError, RunCoordinator, archive_writer
    from bili_asr.manifest import ManifestStore
    from bili_asr.meta_cursor import MetaCursorStore
    from bili_asr.run_ledger import (
        RunLedger,
        build_run_record,
        compute_coverage_summary,
        format_coverage_summary,
        format_cursor_summary,
        utc_now_iso,
    )
    from bili_asr.audio_budget import audio_cap_bytes, audio_dir_usage_bytes
    from bili_asr.long_live import (
        apply_long_live_policy,
        campaign_plan,
        format_campaign_plan,
        is_long_live,
        refuse_disabled_audio_cap,
    )
    from bili_asr.scheduler import (
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
    if args.scope == "pending":
        # The batch chain (schedule/campaign) cut to the store outright
        # (contract §7): no rollback switch, the gap views are the queue.
        rows, error = _store_pending_rows(args.archive_root, "schedule")
        if error:
            return 1
    else:
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
        # `run_batch` is shared; the reuse line must name this command, not `run`.
        command="schedule",
        artifact_roots=args.artifact_roots,
        keep_audio=args.keep_audio,
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
        # D16: the cap, the peak and this pre-download plan all measure the configured
        # root's `audio/` — that is where new bytes land.
        write_base = args.artifact_roots.write_base
        usage_snapshot = audio_dir_usage_bytes(write_base)
        for _key, entry in rows:
            if is_long_live(entry):
                print(format_campaign_plan(
                    campaign_plan(
                        write_base,
                        entry,
                        max_audio_bytes,
                        usage_bytes=usage_snapshot,
                    )
                ))

    try:
        with archive_writer(args.archive_root):
            summary = coord.run_batch(rows)
            if args.allow_long_live:
                after = audio_dir_usage_bytes(args.artifact_roots.write_base)
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
