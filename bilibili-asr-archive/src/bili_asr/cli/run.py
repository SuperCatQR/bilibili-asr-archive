"""Run implementation."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr
import json
import time
from bili_asr.cli.run_record import recorded_command
from bili_asr.cli._shared import _AUDIO_BUDGET_SKIP_HINT, _is_excluded, _queue_source_is_manifest, _resolve_sessdata, _todo_for_bvid


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
            if (
                (
                    str(e.get("work_id") or key) in failed
                    or str(e.get("bvid") or "") in failed
                    or bool(e.get("transcript_writeback_error"))
                )
                and not _is_excluded(e)
            )
            and (
                e.get("status") not in TERMINAL_STATUSES
                or bool(e.get("transcript_writeback_error"))
            )
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


def _store_first_scope_rows(store, entries: dict, scope: str, *,
                            asr_with_subtitles: bool = True):
    """Campaign scope resolution: the store is the queue for ``pending``.

    The batch chain cut to the store outright (contract §7) — no rollback
    switch.  Every other scope (``failed`` and explicit selectors) still
    resolves against the manifest and the coordinator's attempt ledger, which
    the manifest write side owns.
    """

    if scope == "pending":
        return _store_pending_rows(
            store.root, "campaign", asr_with_subtitles=asr_with_subtitles
        )
    return _run_scope_rows(store, entries, scope)


@recorded_command("campaign")
def _cmd_campaign(args: argparse.Namespace) -> int:
    from bili_asr import bili_client
    from bili_asr.audio_budget import audio_cap_bytes
    from bili_asr.campaign import CampaignRunner
    from bili_asr.pipeline.locks import ArchiveBusyError

    runner = None
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
            scope_rows=lambda store, entries, scope: _store_first_scope_rows(
                store, entries, scope,
                asr_with_subtitles=args.asr_with_subtitles,
            ),
            artifact_roots=args.artifact_roots,
            # R1: the runner is the only path to the coordinator's own reclaim, so a
            # `campaign` that did not forward this would leave its documented
            # `--keep-audio/--no-keep-audio` silently inert (contract §7, D15).
            keep_audio=args.keep_audio,
            asr_with_subtitles=args.asr_with_subtitles,
        )
        summary = runner.run(args.scope, args.limit, resume=args.resume)
    except ArchiveBusyError:
        write_stderr("campaign: archive_busy")
        return 1
    except Exception:
        # Never expose runtime payloads, credentials, URLs, or traces.
        write_stderr("campaign: invalid configuration or execution failure")
        return 1
    finally:
        if runner is not None:
            args._run_record.records_existing = getattr(runner, "records_existing", None)
            args._run_record.work_ids = getattr(runner, "run_work_ids", None)
            args._run_record.last_api_error_code = getattr(runner, "last_api_error_code", None)
            args._run_record.hotwords_dropped = list(getattr(runner, "hotwords_dropped", []))
    print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
    return summary.exit_code


def _store_pending_rows(archive_root: str, command: str, *,
                        asr_with_subtitles: bool = True):
    """The pending work list from the store gap views, in coordinator row shape.

    Returns ``(rows, error)``; ``error`` is ``None`` on success.  The store is
    the sole queue input for the pending scope (contract §3): the manifest's
    needs_audio/derived rows are never read to decide work.  A missing or
    pre-transcript-schema store is the documented configuration error.
    """

    from bili_asr.manifest import ManifestStore
    from bili_asr.services import queue_source as qs

    source = qs.open_queue_source(archive_root)
    if source is None:
        write_stderr(
            f"{command}: no archive database at {archive_root}; "
            "run fetch-meta to create it"
        )
        return None, "no archive database"
    try:
        merged = source.select_pending_scope(asr_with_subtitles=asr_with_subtitles)
    finally:
        source.connection.close()
    entries = ManifestStore(root=archive_root).load()
    # A gap view can omit a subtitle that is harvested but not archived yet.
    # Merge the manifest's in-flight status back onto queue candidates while
    # keeping the store as the source of the candidate set.
    for key, queued in list(merged.items()):
        current = entries.get(key)
        if current is None:
            continue
        status = str(current.get("status") or "")
        if (
            status == "archived"
            and not queued.get("asr_required")
            and not current.get("transcript_writeback_error")
        ):
            merged.pop(key, None)
            continue
        if status in {"subtitle_done", "needs_audio", "audio_ok", "meta_ok", "archived"}:
            enriched = dict(queued)
            enriched.update(current)
            if queued.get("asr_required"):
                enriched["status"] = queued.get("status", status)
                enriched["asr_required"] = True
            elif status != "subtitle_done":
                enriched["status"] = queued.get("status", status)
            merged[key] = enriched
    for key, current in sorted(entries.items()):
        status = str(current.get("status") or "")
        if status == "subtitle_done" or (
            status == "archived" and current.get("transcript_writeback_error")
        ):
            merged.setdefault(key, dict(current))
    return [(key, entry) for key, entry in merged.items()], None


@recorded_command("run")
def _cmd_run(args: argparse.Namespace) -> int:
    from bili_asr import bili_client
    from bili_asr.pipeline.locks import ArchiveBusyError, archive_writer
    from bili_asr.coordinator import RunCoordinator
    from bili_asr.manifest import ManifestStore
    from bili_asr.audio_budget import SKIP_REASON, audio_cap_bytes
    from bili_asr.services import queue_source as qs

    record = args._run_record
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    record.records_existing = len(entries)
    if args.limit is not None and args.limit <= 0:
        write_stderr("run: --limit must be a positive integer")
        return 1
    use_manifest = _queue_source_is_manifest(args)
    if use_manifest:
        qs.print_manifest_deprecation()
    if not use_manifest and args.scope == "pending":
        # Store-native pending scope: the gap views are the queue (Task 2).
        rows, error = _store_pending_rows(
            args.archive_root, "run", asr_with_subtitles=args.asr_with_subtitles
        )
        if error:
            return 1
    else:
        rows, error = _run_scope_rows(store, entries, args.scope)
        if error:
            write_stderr(f"run: {error}")
            return 1
    if args.limit is not None:
        rows = rows[: args.limit]
    client = None
    if not args.offline:
        client = bili_client.BiliClient(sessdata=_resolve_sessdata(args))
    coord = RunCoordinator(args.archive_root, store, client=client, offline=args.offline,
                           max_audio_bytes=audio_cap_bytes(args.max_audio_gb),
                           artifact_roots=args.artifact_roots,
                           keep_audio=args.keep_audio,
                           asr_with_subtitles=args.asr_with_subtitles)
    print(f"run: scope={args.scope} selected {len(rows)} row(s)" + (" [offline]" if args.offline else ""))
    for key, entry in rows:
        print(f"  {entry.get('work_id') or key}: {entry.get('status')}")
    try:
        with archive_writer(args.archive_root):
            summary = coord.run_batch(rows)
            record.work_ids = [result.work_id for result in summary.results] or None
            ok = sum(1 for r in summary.results if r.ok)
            skipped = summary.skipped_rows
            failed = summary.failed
            for r in summary.results:
                if r.ok:
                    print(f"{r.work_id}: {r.final_status}")
            for r in failed:
                codes = ", ".join(str(c) for c in r.failure_codes) or "unknown"
                write_stderr(f"run: {r.work_id}: failed ({codes})")
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
                write_stderr("run: risk-control ceiling; stopping — re-run to resume.")
            print(f"run: {ok} completed, {len(skipped)} skipped" +
                  (f", {len(failed)} failed" if failed else "") +
                  (", scope not fully processed" if exit_code == 1 else ""))
            try:
                store.save()
            except Exception as exc:
                write_stderr(
                    f"run: manifest snapshot failed ({type(exc).__name__})"
                )
                if exit_code == 0:
                    exit_code = 1
            return exit_code
    except ArchiveBusyError:
        write_stderr("run: archive_busy")
        return 1
    finally:
        record.hotwords_dropped = list(getattr(coord, "hotwords_dropped", []))


@recorded_command("schedule")
def _cmd_schedule(args: argparse.Namespace) -> int:
    from bili_asr import bili_client
    from bili_asr.pipeline.locks import ArchiveBusyError, archive_writer
    from bili_asr.coordinator import RunCoordinator
    from bili_asr.manifest import ManifestStore
    from bili_asr.meta_cursor import MetaCursorStore
    from bili_asr.run_ledger import (
        compute_coverage_summary,
        format_coverage_summary,
        format_cursor_summary,
        utc_now_iso,
    )
    from bili_asr.audio_budget import AudioUsageError, audio_cap_bytes
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
    from bili_asr.services import queue_source as qs

    record = args._run_record
    store = ManifestStore(root=args.archive_root)
    entries = store.load()
    record.records_existing = len(entries)
    cursor_store = MetaCursorStore(root=args.archive_root)
    cursor_snapshot = cursor_store.load()
    record.cursor_snapshot = cursor_snapshot
    sched_store = SchedulerStore(root=args.archive_root)
    if args.limit is None or args.limit <= 0:
        write_stderr("schedule: --limit must be a positive integer")
        return 1
    if args.allow_long_live:
        cap_error = refuse_disabled_audio_cap(args.max_audio_gb)
        if cap_error:
            write_stderr(f"schedule: {cap_error}")
            return 1
    use_manifest = _queue_source_is_manifest(args)
    if use_manifest:
        qs.print_manifest_deprecation()
    if not use_manifest and args.scope == "pending":
        # The batch chain (schedule/campaign) cut to the store outright
        # (contract §7): no rollback switch, the gap views are the queue.
        rows, error = _store_pending_rows(
            args.archive_root, "schedule", asr_with_subtitles=args.asr_with_subtitles
        )
        if error:
            return 1
    else:
        rows, error = _run_scope_rows(store, entries, args.scope)
        if error:
            write_stderr(f"schedule: {error}")
            return 1

    skip_ids: list[str] | None = None
    matching_resume = False
    if args.resume:
        lookup = sched_store.inspect_resume(
            args.scope, allow_long_live=args.allow_long_live
        )
        if lookup.diagnostic:
            if lookup.refuse:
                write_stderr(
                    f"schedule: --resume refused ({lookup.diagnostic})"
                )
                return 1
            write_stderr(
                f"schedule: --resume ignored ({lookup.diagnostic})"
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
        write_stderr(f"schedule: {policy_error}")
        return 1
    if matching_resume and not args.allow_long_live and not rows and held:
        write_stderr(
            "schedule: --resume refused (risk-stopped long-duration "
            "row requires --allow-long-live)"
        )
        return 1

    matching = len(rows)
    # Batch completion describes the currently selected scope. Enumeration
    # progress is reported separately and may still have undiscovered pages.
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
        asr_with_subtitles=args.asr_with_subtitles,
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
    try:
        with archive_writer(args.archive_root):
            if args.allow_long_live:
                # The plan and download guard use the same owned snapshot.
                usage_snapshot = coord.prepare_audio_usage()
                for _key, entry in rows:
                    if is_long_live(entry):
                        print(format_campaign_plan(campaign_plan(
                            args.artifact_roots.write_base,
                            entry,
                            max_audio_bytes,
                            usage_bytes=usage_snapshot,
                        )))
            summary = coord.run_batch(rows)
            record.work_ids = [result.work_id for result in summary.results] or None
            if args.allow_long_live:
                try:
                    after: int | str = coord.audio_usage_bytes()
                except AudioUsageError:
                    after = "unknown"
                peak = coord.audio_peak_bytes
                print(f"schedule: long-live peak audio/ bytes={peak if peak is not None else 'unknown'}")
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

            record.last_api_error_code = last_api_error_code
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
                write_stderr(
                    "schedule: failed to persist scheduler.json "
                    f"({type(exc).__name__})"
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
                write_stderr(
                    f"schedule: {result.work_id}: failed ({codes})"
                )
            for result in skipped:
                print(
                    f"schedule: {result.work_id}: skipped "
                    f"({result.skip_reason or 'unknown'})"
                )

            exit_code = 0
            if summary.risk_interrupted:
                if persisted:
                    write_stderr(
                        "schedule: risk-control ceiling; stopping — "
                        "re-run with --resume."
                    )
                else:
                    write_stderr(
                        "schedule: risk-control ceiling; scheduler.json "
                        "was not persisted."
                    )
                exit_code = 2
            elif not summary.fully_processed:
                exit_code = 1
            if not persisted and exit_code != 2:
                exit_code = 1

            coverage = compute_coverage_summary(store.load())
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

            try:
                store.save()
            except Exception as exc:
                write_stderr(
                    f"schedule: manifest snapshot failed ({type(exc).__name__})"
                )
                if exit_code == 0:
                    exit_code = 1

            return exit_code
    except ArchiveBusyError:
        write_stderr("schedule: archive_busy")
        return 1
    except AudioUsageError:
        write_stderr("schedule: audio usage unavailable; batch refused")
        return 1
    finally:
        record.hotwords_dropped = list(getattr(coord, "hotwords_dropped", []))
