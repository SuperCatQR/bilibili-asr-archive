"""Pilot implementation."""

from __future__ import annotations

import bili_asr.asr.config as _module_asr_config
import bili_asr.asr.coverage as _module_asr_coverage
import bili_asr.asr.errors as _module_asr_errors
import bili_asr.asr.provenance as _module_asr_provenance
import bili_asr.asr.runner as _module_asr_runner


from bili_asr.diagnostics import write_stderr
from pathlib import Path
from typing import Any
import os
import time
from bili_asr.cli._shared import _AUDIO_BUDGET_SKIP_HINT, _identity_from_entry, _is_excluded, _queue_source_is_manifest, _record_api_error, _resolve_sessdata
from bili_asr.cli.processing import _AsrItemCount, _asr_transcript_segments, _print_in_process_constructions
from bili_asr.cli.status_cmd import _PILOT_PROCESSABLE, _PILOT_SKIP_HARVEST
from bili_asr.cli.run_record import recorded_command
import bili_asr.cli.processing_paths as _dependency_processing_paths


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
    from bili_asr.audio_budget import max_duration_exceeded

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
    from bili_asr.audio_budget import max_duration_exceeded

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


def _pilot_archive_subtitle(
    store, roots: ArtifactRoots, entry: dict[str, object], *, keep: bool
) -> dict[str, object]:
    from bili_asr import archive

    base = roots.write_base
    data = _dependency_processing_paths._subtitle_segments(roots, entry)
    if data is None:
        raise ValueError(f"{_pilot_row_key(entry)}: subtitle raw JSON missing")
    segments, raw = data
    paths = archive.write_archive(base, entry, segments, source="subtitle", raw=raw)
    if not archive.archive_bundle_complete(base, paths):
        raise ValueError("archive bundle incomplete")
    updated = dict(entry)
    updated.update(paths)
    updated["status"] = "archived"
    store.upsert(updated)
    _dependency_processing_paths._reclaim_after_archive(roots, updated, keep=keep)
    return updated


def _pilot_archive_asr(
    store, client, roots: ArtifactRoots, entry: dict[str, object], target, runner=None,
    asr_count: "_AsrItemCount | None" = None, *, keep: bool,
    hotwords_dropped: list[str] | None = None,
) -> dict[str, object]:
    """Archive one pilot row over ASR.

    ``runner`` is the invocation-scoped ``ASRRunner``: the pilot's loop holds
    one for its whole selection (D2.3), so this function transcribes through
    the caller's runner and never builds a second model.  Omitting it keeps the
    single-row entry point working with its own short-lived runner.

    ``asr_count`` is the caller's ``_AsrItemCount``.  When given, the row is
    counted as soon as it produced a transcript — the same event ``run``
    counts at its ``asr: ok`` attempt (D2.5) — so a row that fails later in
    this function's archive tail keeps its place in the line's denominator.

    It is **not optional for a loop caller**: the counter is how this
    function's increment reaches the batch's printed line, and the only caller
    able to pass the loop's box is the loop itself.  ``None`` is for the
    single-row entry point, whose caller prints no line; a multi-row loop that
    leaves it at ``None`` silently under-counts, so passing it is asserted
    below rather than left to convention.
    """
    from bili_asr import archive, asr, audio
    from bili_asr.page_identity import PageIdentity, artifact_stem
    from bili_asr.subtitles import resolve_page_identity

    if runner is not None and asr_count is None:
        # A caller-supplied runner means "I am the loop" (D2.3): without the
        # box this row's transcript never reaches the line's denominator.
        raise TypeError("_pilot_archive_asr needs asr_count with a caller runner")

    if isinstance(target, str):
        target = resolve_page_identity(client, target)
    if not isinstance(target, PageIdentity):
        raise TypeError("unsupported download target")
    # Writes use `write_base` alone; reads walk the ordered bases (contract §4/§5).
    base = roots.write_base
    stem = artifact_stem(target)
    out_path = os.path.join(base, "audio", f"{stem}.m4a")
    existing_rel = entry.get("audio_path") if entry.get("status") in {"audio_ok", "subtitle_done"} else None
    existing_audio_path: str | None = None
    # The base the row's audio is read from: whichever base holds it — the recorded copy's
    # for a row written before the root was configured, the downloader's return for a row
    # that had to fetch (or re-find) it.  The ASR stage re-confines the value **there** and
    # records it back **there** (contract §5, D6/D8): measuring a legacy copy against
    # `write_base` alone yields a `..`-bearing string the audio guard refuses, so the row
    # fails instead of archiving.
    audio_base = base
    from bili_asr.path_policy import confined_audio_file, confined_audio_path
    if existing_rel:
        try:
            holding = _dependency_processing_paths._audio_base_holding(roots, os.fspath(existing_rel))
        except OSError:
            holding = None
        if holding is not None:
            existing_audio_path_obj = confined_audio_path(
                holding, os.fspath(existing_rel), require_exists=True
            )
            if existing_audio_path_obj is not None and existing_audio_path_obj.stat().st_size > 0:
                existing_audio_path = str(existing_audio_path_obj)
                audio_base = holding
    if existing_audio_path is not None:
        audio_path = existing_audio_path
    else:
        downloaded = Path(os.fspath(audio.download_audio(
            client, target, out_path, store=store, artifact_roots=roots
        )))
        # The downloader may return a file it *found* rather than wrote — a legacy copy at
        # the archive root (D6) — so the base that holds the return is the one the value is
        # re-confined and recorded against, the same rule as the recorded branch above.
        try:
            audio_base = _dependency_processing_paths._audio_base_for_path(roots, downloaded)
        except OSError:
            raise ValueError("invalid audio path")
        downloaded_rel = os.path.relpath(downloaded, audio_base).replace(os.sep, "/")
        audio_path_obj = confined_audio_path(audio_base, downloaded_rel, require_exists=True)
        if audio_path_obj is None or audio_path_obj.stat().st_size <= 0:
            raise ValueError("invalid audio path")
        audio_path = str(audio_path_obj)
    declared_audio = os.path.relpath(audio_path, audio_base).replace(os.sep, "/")
    owns_runner = runner is None
    if owns_runner:
        runner = _module_asr_runner.ASRRunner(_module_asr_config.default_config())
    try:
        with confined_audio_file(audio_base, declared_audio) as safe_audio:
            segments = runner.transcribe(safe_audio)
        if hotwords_dropped is not None:
            from bili_asr.run_ledger import collect_hotwords_dropped

            collect_hotwords_dropped(hotwords_dropped, runner)
        if asr_count is not None:
            asr_count.value += 1
        current = dict(store.get(target.work_id) or entry)
        paths = archive.write_archive(
            base, current, segments, source="asr", asr_provenance=runner.provenance(),
            characters=_module_asr_coverage.characters_of(runner),
            # Same measurement as the store write-back below (I-000188: store *and* bundle).
            coverage=_module_asr_coverage.transcribed_coverage(runner),
        )
    finally:
        if owns_runner:
            runner.release()
    if not archive.archive_bundle_complete(base, paths):
        raise ValueError("archive bundle incomplete")
    current.update(paths)
    current["status"] = "archived"
    _module_asr_provenance.apply_provenance_evidence(current, runner)
    # Coverage attestation (plan asr-coverage-attestation): this route runs ASR, so its measured
    # span rides the row it writes — the same carrier as the `asr` loop and the coordinator.
    _module_asr_coverage.apply_coverage_evidence(current, runner)
    try:
        current["audio_path"] = os.path.relpath(audio_path, audio_base).replace(os.sep, "/")
    except ValueError:
        current["audio_path"] = audio_path
    store.upsert(current)
    _dependency_processing_paths._reclaim_after_archive(roots, current, keep=keep)
    return current


def _open_writeback_source(args, use_manifest: bool):
    """The live queue source the pilot's write-backs write through, or ``None``.

    The selection-time source is closed once the work list is built (its only
    job is the read), so the write-backs need their own connection.  This is
    best-effort by construction: a store that cannot be opened here simply
    skips the write-back, exactly as a store that refuses a write does — the
    archive on disk is never lost to a store problem.  The ``kind='asr'`` run
    the transcript write-backs key to is (re)created on this source.
    """

    if use_manifest:
        return None
    from bili_asr.services import queue_source as qs

    source = qs.open_queue_source(args.archive_root)
    if source is not None:
        source.ensure_asr_run(
            "pilot", selector_target=getattr(args, "bvid", None),
            requested_limit=args.n,
        )
    return source


def _record_pilot_audio_acquired(
    queue_source, roots: ArtifactRoots, entry: dict[str, object]
) -> None:
    """Record pilot-acquired audio back into the store (best-effort).

    The pilot downloads (or reuses) the audio it archives over ASR; that
    acquisition is positive audio evidence, taking the part out of
    ``v_missing_audio`` — the same write-back ``download-audio`` owns through
    :func:`bili_asr.services.queue_source.mark_audio_acquired`.  Without it a
    pilot-archived part keeps sitting in the audio queue and is re-served on
    every run.  Best-effort: a store failure must not lose an archive already
    on disk.
    """

    from bili_asr.services import queue_source as qs

    audio_rel = entry.get("audio_path")
    from bili_asr.page_identity import writeback_identity

    identity = writeback_identity(entry)
    if not audio_rel or identity is None:
        return
    try:
        base = _dependency_processing_paths._audio_base_holding(roots, os.fspath(audio_rel))
    except OSError:
        return
    audio_path = os.path.join(os.fspath(base), os.fspath(audio_rel))
    qs.mark_audio_acquired(
        queue_source,
        bvid=identity[0],
        page_index=identity[1],
        audio_path=audio_path,
        declared_relative=os.fspath(audio_rel),
    )


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


def _store_pilot_entries(source: Any, *, asr_with_subtitles: bool = True) -> dict[str, dict[str, Any]]:
    """Merge all store queue views while preserving the most advanced route."""
    merged: dict[str, dict[str, Any]] = {}
    for select in (
        source.select_audio_queue(),
        source.select_transcript_queue(),
        source.select_subtitle_queue(),
    ):
        for key, entry in select.entries.items():
            merged.setdefault(key, entry)
    if asr_with_subtitles:
        for key, entry in source.select_asr_subtitle_queue().entries.items():
            merged.setdefault(key, entry)
    return merged


@recorded_command("pilot")
def _cmd_pilot(args: argparse.Namespace) -> int:
    from bili_asr import asr, audio, bili_client, subtitles
    from bili_asr.manifest import ManifestStore

    record = args._run_record
    record.capture_cursor = True
    store = ManifestStore(root=args.archive_root)
    from bili_asr.services import queue_source as qs

    use_manifest = _queue_source_is_manifest(args)
    if use_manifest:
        qs.print_manifest_deprecation()
        entries = store.load()
    else:
        # Store source: the pilot's work is the union of the audio queue
        # (captionless, download→ASR) and the transcript queue (audio-backed,
        # ASR directly).  A part holding subtitles is in neither.
        source = qs.open_queue_source(args.archive_root)
        if source is None:
            write_stderr(
                f"pilot: no archive database at {args.archive_root}; "
                "run fetch-meta to create it"
            )
            return 1
        try:
            entries = _store_pilot_entries(
                source, asr_with_subtitles=args.asr_with_subtitles
            )
        finally:
            source.connection.close()
    record.records_existing = len(entries)
    last_api_error_code: int | str | None = None
    selected_work_ids: list[str] | None = None

    def _record_exit(code: int) -> int:
        record.last_api_error_code = last_api_error_code
        return code

    selected = _expand_selected_pages(
        entries,
        _pilot_select(entries, args.n, args.max_duration_min),
        args.max_duration_min,
    )
    selected_work_ids = [_pilot_row_key(e) for e in selected] if selected else None
    record.work_ids = selected_work_ids
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
            write_stderr("pilot: no processable rows in the manifest")
            return _record_exit(1)
        if any(e.get("status") == "archived" for e in entries.values()):
            print("pilot: skip — all selected work already archived")
            return _record_exit(0)
        write_stderr("pilot: no processable rows in the manifest")
        return _record_exit(1)

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    coverage_subtitle_count, coverage_audio_count = _archived_branch_counts(entries)
    batch_subtitle_count = batch_audio_count = 0
    failed = 0
    terminals: list[str] = []
    # One pilot invocation is one run scope (D2.3): the selection shares one
    # runner, and the `finally` below states what it paid and releases it on
    # every exit path — including the early returns inside the loop.
    runner = None
    # Same denominator rule as ``_cmd_asr`` (D2.5): the row is counted when
    # its ASR stage produced a transcript, inside ``_pilot_archive_asr``.
    asr_count = _AsrItemCount()
    # The store write-backs' live connection, opened lazily on first use and
    # closed on every exit path (the ``finally`` below).  ``None`` on the
    # manifest route or when the store cannot be opened — the write-backs are
    # best-effort and skip rather than fail the archive.
    writeback_source = None
    completed = False
    from bili_asr.audio_budget import AudioUsageError, AudioUsageTracker

    usage_tracker = None
    usage_unavailable = False

    try:
        for index, entry in enumerate(selected):
            key = _pilot_row_key(entry)
            record.visited_work_ids.append(key)
            target = _identity_from_entry(entry, key)
            label = key
            status = entry.get("status")
            if status == "archived":
                continue
            audio_attempted = audio_completed = False
            try:
                if status not in _PILOT_SKIP_HARVEST:
                    status = subtitles.harvest_subtitle(
                        client, target, store, args.archive_root,
                        artifact_roots=args.artifact_roots,
                    )
                current = dict(store.get(key) or store.get_compatible(key) or entry)
                label = str(current.get("work_id") or key)
                if status == "subtitle_done" and not args.asr_with_subtitles:
                    _pilot_archive_subtitle(
                        store, args.artifact_roots, current, keep=args.keep_audio
                    )
                    batch_subtitle_count += 1
                    coverage_subtitle_count += 1
                    terminals.append(f"{label}: archived (subtitle)")
                    print(f"{label}: archived (subtitle)")
                elif status == "subtitle_done" or status in {"needs_audio", "audio_ok"}:
                    from bili_asr.audio_budget import (
                        SKIP_REASON,
                        audio_cap_bytes,
                        would_exceed_budget,
                    )

                    max_bytes = audio_cap_bytes(args.max_audio_gb)
                    current_row = dict(store.get(key) or current)
                    if status == "needs_audio" and max_bytes:
                        if usage_unavailable:
                            raise AudioUsageError("audio usage unavailable")
                        if usage_tracker is None:
                            usage_tracker = AudioUsageTracker(args.artifact_roots.write_base)
                    if (
                        status == "needs_audio"
                        and would_exceed_budget(
                            args.artifact_roots.write_base, current_row, max_bytes,
                            usage_bytes=usage_tracker.usage_bytes if usage_tracker else None,
                        )
                    ):
                        failed += 1
                        # Q1's ruling: the cap keeps its fail-closed semantics, and the
                        # line that reports it names the flag that lifts it.  With audio
                        # retained, `audio/` only grows, so `0` is the operator's lever.
                        write_stderr(
                            f"{label}: skipped ({SKIP_REASON})"
                            f"{_AUDIO_BUDGET_SKIP_HINT}"
                        )
                        continue
                    if runner is None:
                        runner = _module_asr_runner.ASRRunner(_module_asr_config.default_config())
                    audio_attempted = True
                    archived_row = _pilot_archive_asr(
                        store, client, args.artifact_roots, current, target, runner,
                        asr_count, keep=args.keep_audio,
                        hotwords_dropped=record.hotwords_dropped,
                    )
                    audio_completed = True
                    # Store write-backs, both best-effort (the archive already
                    # succeeded on disk): the acquired audio is positive audio
                    # evidence taking the part out of v_missing_audio — the same
                    # write-back download-audio owns — and the locally-produced
                    # transcript is a real transcripts row taking it out of
                    # v_missing_transcript (plan 20260929-asr-local-transcript-
                    # storage, Task 2).
                    if not use_manifest:
                        if writeback_source is None:
                            writeback_source = _open_writeback_source(
                                args, use_manifest
                            )
                        if writeback_source is not None:
                            _record_pilot_audio_acquired(
                                writeback_source, args.artifact_roots, archived_row
                            )
                            if getattr(writeback_source, "asr_run_id", None):
                                try:
                                    provenance = runner.provenance() if runner else {}
                                except Exception:
                                    provenance = {}
                                recorded = (
                                    runner.transcribed_segments() if runner else None
                                )
                                from bili_asr.page_identity import writeback_identity

                                identity = writeback_identity(current)
                                if recorded and identity is not None:
                                    qs.record_local_transcript(
                                        writeback_source,
                                        run_id=writeback_source.asr_run_id,
                                        bvid=identity[0],
                                        page_index=identity[1],
                                        language=_module_asr_provenance.provenance_language(provenance),
                                        segments=_asr_transcript_segments(recorded),
                                        model_name=provenance.get("model_name", ""),
                                        model_revision=provenance.get("model_revision"),
                                        coverage=_module_asr_coverage.transcribed_coverage(runner),
                                    )
                    batch_audio_count += 1
                    coverage_audio_count += 1
                    terminals.append(f"{label}: archived (asr)")
                    print(f"{label}: archived (asr)")
                else:
                    raise ValueError(f"unexpected status {status!r}")
            except _module_asr_errors.ASRDependencyError as exc:
                write_stderr(str(exc))
                write_stderr(
                    f"{label}: ASR dependency unavailable; row not archived"
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
                write_stderr(f"{label}: multi-part video needs an explicit page")
            except bili_client.RiskBudgetExhausted as exc:
                failed += 1
                last_api_error_code = exc.last_code
                record.last_api_error_code = last_api_error_code
                write_stderr(
                    f"{label}: risk-control ceiling (last code {exc.last_code}); "
                    f"stopping — re-run to resume."
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
                record.last_api_error_code = last_api_error_code
                _record_api_error(store, key, exc.code)
                write_stderr(
                    f"{label}: API response error (code {exc.code}); continuing."
                )
            except bili_client.GoneResponse as exc:
                failed += 1
                last_api_error_code = exc.code
                record.last_api_error_code = last_api_error_code
                gone = dict(store.get(key) or store.get_compatible(key) or {})
                if gone.get("work_id"):
                    gone["status"] = "gone"
                    store.upsert(gone)
                write_stderr(
                    f"{label}: terminal API response (code {exc.code}); marked gone."
                )
            except audio.NoAudioStreamError:
                failed += 1
                write_stderr(f"{label}: no audio stream available")
            except AudioUsageError:
                usage_unavailable = True
                failed += 1
                write_stderr(f"{label}: audio usage unavailable; download refused")
            except bili_client.StreamDownloadError:
                failed += 1
                write_stderr(f"{label}: audio stream failed; continuing.")
            except ValueError as exc:
                failed += 1
                msg = str(exc)
                if (
                    "missing cid" in msg
                    or "unresolved" in msg
                    or "subtitle raw JSON missing" in msg
                ):
                    write_stderr(f"{label}: {msg}")
                else:
                    write_stderr(f"{label}: {type(exc).__name__}")
            except Exception as exc:
                failed += 1
                write_stderr(f"{label}: {type(exc).__name__}")
            finally:
                if usage_tracker is not None and audio_attempted:
                    try:
                        if audio_completed:
                            usage_tracker.refresh_entry(dict(store.get(key) or current))
                        else:
                            usage_tracker.rescan()
                    except (OSError, ValueError):
                        usage_unavailable = True
            if index != len(selected) - 1:
                time.sleep(3.0)
        completed = True
    finally:
        _print_in_process_constructions("pilot", runner, asr_count.value)
        if runner is not None:
            runner.release()
        if writeback_source is not None:
            outcome = (
                "partial" if batch_subtitle_count + batch_audio_count else "failed"
            ) if failed or not completed else None
            writeback_source.finish_asr_run(outcome=outcome)
            writeback_source.connection.close()

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
        write_stderr(
            "pilot: missing branch coverage: " + ", ".join(missing)
        )
        return _record_exit(1)
    if failed:
        return _record_exit(1)
    return _record_exit(0)
