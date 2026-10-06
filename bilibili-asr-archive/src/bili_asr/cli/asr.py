"""Asr implementation."""

from __future__ import annotations

import bili_asr.asr.config as _module_asr_config
import bili_asr.asr.coverage as _module_asr_coverage
import bili_asr.asr.errors as _module_asr_errors
import bili_asr.asr.provenance as _module_asr_provenance
import bili_asr.asr.runner as _module_asr_runner


from bili_asr.diagnostics import write_stderr
import os
from bili_asr.cli._shared import _is_excluded, _queue_source_is_manifest, _store_transcript_todo, _todo_for_bvid
import bili_asr.cli.processing as _dependency_processing

# Kept as a local command-module handle because the writeback safety tests and
# command diagnostics exercise this helper through the ``asr`` command module.
_print_in_process_constructions = _dependency_processing._print_in_process_constructions


def _cmd_asr(args: argparse.Namespace) -> int:
    from bili_asr import archive, asr
    from bili_asr.manifest import ManifestStore
    from bili_asr.services import queue_source as qs

    # Function-local on purpose: ``pilot`` imports this module at ITS module level
    # (``_AsrItemCount``/``_print_in_process_constructions``), so a module-level import here
    # would be a cycle.  Deferring to call time keeps the dependency one-directional.
    from bili_asr.cli.processing_paths import _audio_base_holding, _reclaim_after_archive, _subtitle_segments

    use_manifest = _queue_source_is_manifest(args)
    if use_manifest:
        qs.print_manifest_deprecation()

    # Store source (default): the transcript queue is v_missing_transcript —
    # parts with audio evidence and no stored transcript.  A part holding AI
    # subtitles is satisfied in every queue and never reaches this branch.
    queue_conn = None
    queue_source = None
    if not use_manifest:
        store = ManifestStore(root=args.archive_root)
        rows, queue_source, failed = _store_transcript_todo(args, command="asr")
        if failed:
            return 1
        queue_conn = queue_source.connection
        # ``--limit`` is owned by the queue-source read: ``_store_transcript_todo``
        # already passed ``args.limit`` into the store-side ``LIMIT ?``, so a
        # second slice here would only mask which side owns the bound (the
        # download-audio store branch relies on the store limit alone).
        todo = [e for _key, e in rows] if rows else []
        if not todo:
            print("asr: queue empty (no parts need transcription)")
            queue_conn.close()
            return 0
    else:
        store = ManifestStore(root=args.archive_root)
        entries = store.load()
        if args.bvid:
            selected = _todo_for_bvid(store, args.bvid, entries)
            if selected is None:
                write_stderr(f"{args.bvid}: multi-part video needs an explicit page")
                return 1
            if not selected:
                write_stderr(
                    f"{args.bvid}: unresolved; not assigned to a page"
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
            write_stderr("asr: select targets with --pending or --bvid")
            return 1
        if args.limit is not None:
            todo = todo[:args.limit]
    ok = failed = 0
    # One invocation is one run scope (D2.2): every audio item of this
    # selection shares one lazily-built runner, and the selection states what
    # it paid.  ``asr.transcribe``'s one-shot contract is untouched (D2.4).
    runner = None
    # The declared identity is validated once, here, before the row loop and
    # outside its per-row ``try`` (QC3-F1).  A mis-declared producer used to
    # surface as N identical ``archive failed`` lines with the reason reaching
    # no stream at all; now the ``ValueError``'s own message is printed once and
    # the command exits 1, leaving the per-row path below as the backstop.
    # ``default_config()`` only reads the environment knobs, so this builds no
    # model.  A selection that never reaches the ASR path is skipped: a
    # subtitle-only run does not read these knobs and must not be refused
    # because one of them is malformed.
    #
    # Both ``ValueError`` branches are redaction-safe by construction (verified
    # by ``test_the_asr_entry_failure_message_never_carries_a_path``): the
    # unsafe-declaration branch names only the variable, and the contradiction
    # branch can only fire once *both* values have passed the identifier scan.
    config = None
    if any(entry.get("status") != "subtitle_done" for entry in todo):
        try:
            config = _module_asr_config.default_config()
        except ValueError as exc:
            write_stderr(f"asr: {exc}")
            if queue_conn is not None:
                queue_conn.close()
            return 1
    # ``asr_count`` is the printed line's denominator and counts the same event
    # the coordinator counts (D2.5): a row whose ASR stage produced a
    # transcript.  It increments at the transcribe boundary below, never after
    # the archive tail, so a row that fails downstream still counts and the
    # two paths cannot disagree on the same input.
    asr_count = _dependency_processing._AsrItemCount()
    completed = False
    try:
        if queue_source is not None:
            _dependency_processing._ensure_asr_run(
                queue_source, "asr", selector_target=args.bvid,
                requested_limit=args.limit,
            )
        for entry in todo:
            key = str(entry.get("work_id") or entry["bvid"])
            label = key
            source = "subtitle"
            raw = None
            provenance = None
            status = entry.get("status")
            subtitle_data = (
                _subtitle_segments(args.artifact_roots, entry)
                if status == "subtitle_done"
                else None
            )
            try:
                if status == "subtitle_done" and subtitle_data is None:
                    failed += 1
                    write_stderr(f"{label}: skipped (missing_subtitle_raw)")
                    continue
                if subtitle_data is not None:
                    segments, raw = subtitle_data
                else:
                    source = "asr"
                    stem = archive.archive_stem(entry)
                    from bili_asr.path_policy import confined_audio_file
                    declared = entry.get("audio_path") or os.path.join("audio", f"{stem}.m4a")
                    if runner is None:
                        runner = _module_asr_runner.ASRRunner(
                            config if config is not None else _module_asr_config.default_config()
                        )
                    # A read of the recorded value, so both bases answer (D8): a row
                    # whose audio predates the configured root still resolves.
                    audio_base = _audio_base_holding(
                        args.artifact_roots, os.fspath(declared)
                    )
                    # Evidence-based seeding (governance ruling 2026-09-28, plan
                    # 20260928-hotword-injection-governance): the paired AI-subtitle
                    # text and the run's own first-pass transcript are the only
                    # texts that may admit a hotword.  Pass 1 runs unguarded; pass 2
                    # is seeded with the tokens pass 1 produced and re-decodes with a
                    # clean model/cache state.  Dropped tokens are recorded as
                    # ``hotword_dropped_no_evidence`` in the provenance.
                    subtitle_data_for_evidence = (
                        _subtitle_segments(args.artifact_roots, entry)
                        if status == "subtitle_done"
                        else None
                    )
                    paired_subtitle_text = (
                        "".join(str(seg.get("text", "")) for seg in subtitle_data_for_evidence[0])
                        if subtitle_data_for_evidence is not None
                        else None
                    )
                    with confined_audio_file(audio_base, os.fspath(declared)) as safe_audio:
                        segments = _module_asr_runner.two_pass_transcribe(
                            runner, safe_audio, paired_subtitle_text=paired_subtitle_text
                        )
                    asr_count.value += 1
                    provenance = runner.provenance()
                coverage = _module_asr_coverage.transcribed_coverage(runner) if source == "asr" else None
                paths = archive.write_archive(
                    args.artifact_roots.write_base, entry, segments, source=source,
                    raw=raw, asr_provenance=provenance,
                    characters=_module_asr_coverage.characters_of(runner) if source == "asr" else None,
                    # The same measurement the store write-back carries (I-000188 acceptance:
                    # "visible in the store and in the bundle").  `runner` is None on the
                    # subtitle route, and the helper returns None when there is no measurement.
                    coverage=coverage,
                )
                if not archive.archive_bundle_complete(args.artifact_roots.write_base, paths):
                    raise ValueError("archive bundle incomplete")
                updated = dict(store.get(key) or entry)
                updated.update(paths)
                updated["status"] = "archived"
                updated["source"] = source
                # Content source is shared with coordinator archives.  Keep
                # the actual producer separate for operational evidence checks.
                updated["archive_producer"] = "stage-cli"
                # Coverage attestation (plan asr-coverage-attestation): the ASR route's measured
                # span rides this row.  The subtitle route runs no ASR, so it made no measurement
                # and no key is written for it — an absent ``coverage`` reads as *not evaluable*,
                # which is the honest answer, not "covered".
                if source == "asr":
                    _module_asr_provenance.apply_provenance_evidence(updated, runner)
                    _module_asr_coverage.apply_coverage_evidence(updated, runner)
                store.upsert(updated)
                _reclaim_after_archive(
                    args.artifact_roots, updated, keep=args.keep_audio
                )
                # Publication and the resumable manifest precede supplementary
                # store writes, including cue conversion that can itself fail.
                from bili_asr.page_identity import writeback_identity

                identity = writeback_identity(entry)
                if (
                    queue_source is not None and source == "asr"
                    and queue_source.asr_run_id is not None
                    and identity is not None
                ):
                    try:
                        qs.record_local_transcript(
                            queue_source,
                            run_id=queue_source.asr_run_id,
                            bvid=identity[0],
                            page_index=identity[1],
                            language=_module_asr_provenance.provenance_language(provenance),
                            segments=_dependency_processing._asr_transcript_segments(segments),
                            model_name=(provenance or {}).get("model_name", ""),
                            model_revision=(provenance or {}).get("model_revision"),
                            coverage=coverage,
                        )
                    except Exception as exc:
                        write_stderr(
                            f"{label}: transcript store write-back failed ({type(exc).__name__})"
                        )
                ok += 1
                print(f"{label}: archived ({source})")
            except _module_asr_errors.ASRDependencyError:
                failed += 1
                write_stderr(f"{label}: ASR dependency unavailable")
            except Exception as exc:
                failed += 1
                # The `run` path states the code (`failed (ValueError)`), and
                # this one used to print fixed text with no reason at all
                # (QC3-F1).  `_safe_error_code` never throws and never echoes a
                # payload: it reads `code`/`last_code` or the class name.
                from bili_asr.pipeline.attempts import _safe_error_code

                write_stderr(
                    f"{label}: archive failed ({_safe_error_code(exc)})"
                )
        completed = True
    finally:
        if queue_conn is not None:
            outcome = (
                "partial" if ok else "failed"
            ) if failed or not completed else None
            queue_source.finish_asr_run(outcome=outcome)
            queue_conn.close()
        _dependency_processing._print_in_process_constructions("asr", runner, asr_count.value)
        if runner is not None:
            runner.release()
    print(f"asr: {ok} archived" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0
