"""The `_cmd_asr` handler and its helpers."""

from __future__ import annotations

import os
import sys

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _archive_database_exists,
    _is_excluded,
    _metadata_database_path,
    _open_read_connection,
    _open_read_repository,
    _queue_source_is_manifest,
    _store_audio_todo,
    _store_transcript_todo,
    _subtitle_schema_rebuild_line,
    _subtitle_selector,
    _todo_for_bvid,
)

class _AsrItemCount:
    """The printed reuse line's ASR-item denominator (D2.5).

    A one-field box, not an ``int``, because the in-process loops count the
    row at two different call depths: ``_cmd_asr`` counts inline, while
    ``pilot`` counts inside ``_pilot_archive_asr``, which has to report the
    increment to its caller.  Every path increments at the same event — the
    row's ASR stage produced a transcript — which is what ``RunCoordinator``
    counts at its own ``asr: ok`` attempt, so ``asr``/``pilot`` and ``run``
    state the same denominator for the same input.
    """

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = 0


def _print_in_process_constructions(
    command: str, runner: object, asr_items: int
) -> None:
    """State one in-process ASR loop's constructions, once, on stderr (D2.6).

    ``RunCoordinator.run_batch`` prints this for the coordinator path; ``asr``
    and ``pilot`` never enter it, so they print through the same shared string
    for their own command label.  ``runner`` is ``None`` when the selection
    needed no model.

    The guard is "nothing was paid", not "no ASR items" — the same rule the
    coordinator applies: a loop that built the model and then failed every
    transcription still states ``… for 0 asr item(s)``, while a subtitle-only
    selection (no construction, no transcript) prints nothing at all.  Stderr
    keeps every command's stdout contract intact; when fd 2 is closed
    ``sys.stderr`` is ``None`` and ``print(..., file=None)`` would fall back to
    stdout, so a missing stream prints nothing rather than breaking it.
    """
    from bili_asr.coordinator import model_constructions_line

    constructions = (
        int(getattr(runner, "model_constructions", 0)) if runner is not None else 0
    )
    if asr_items <= 0 and constructions <= 0:
        return
    if sys.stderr is None:
        return
    print(
        model_constructions_line(command, constructions, asr_items),
        file=sys.stderr,
    )


def _cmd_asr(args: argparse.Namespace) -> int:
    from bili_asr import archive, asr
    from bili_asr.manifest import ManifestStore
    from bili_asr.services import queue_source as qs

    # Function-local on purpose: ``pilot`` imports this module at ITS module level
    # (``_AsrItemCount``/``_print_in_process_constructions``), so a module-level import here
    # would be a cycle.  Deferring to call time keeps the dependency one-directional.
    from bili_asr.cli.pilot import (
        _audio_base_holding,
        _reclaim_after_archive,
        _subtitle_segments,
    )

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
        todo = [e for _key, e in rows] if rows else []
        if args.limit is not None:
            todo = todo[:args.limit]
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
            config = asr.default_config()
        except ValueError as exc:
            print(f"asr: {exc}", file=sys.stderr)
            return 1
    # ``asr_count`` is the printed line's denominator and counts the same event
    # the coordinator counts (D2.5): a row whose ASR stage produced a
    # transcript.  It increments at the transcribe boundary below, never after
    # the archive tail, so a row that fails downstream still counts and the
    # two paths cannot disagree on the same input.
    asr_count = _AsrItemCount()
    try:
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
                    print(f"{label}: skipped (missing_subtitle_raw)", file=sys.stderr)
                    continue
                if subtitle_data is not None:
                    segments, raw = subtitle_data
                else:
                    source = "asr"
                    stem = archive.archive_stem(entry)
                    from bili_asr.path_policy import confined_audio_file
                    declared = entry.get("audio_path") or os.path.join("audio", f"{stem}.m4a")
                    if runner is None:
                        runner = asr.ASRRunner(
                            config if config is not None else asr.default_config()
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
                    # is seeded with the tokens pass 1 produced.  Dropped tokens are
                    # recorded as ``hotword_dropped_no_evidence`` in the provenance.
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
                    runner.set_hotword_evidence(
                        evidence_text=None, paired_subtitle_text=paired_subtitle_text
                    )
                    with confined_audio_file(audio_base, os.fspath(declared)) as safe_audio:
                        first_pass = runner.transcribe(safe_audio)
                    transcript_text = "".join(str(seg.get("text", "")) for seg in first_pass)
                    if runner.rebuild_hotwords_from_first_pass(transcript_text):  # kept tokens
                        with confined_audio_file(audio_base, os.fspath(declared)) as safe_audio:
                            segments = runner.transcribe(safe_audio)
                    else:
                        segments = first_pass
                    asr_count.value += 1
                    provenance = runner.provenance()
                paths = archive.write_archive(
                    args.artifact_roots.write_base, entry, segments, source=source,
                    raw=raw, asr_provenance=provenance,
                )
                if not archive.archive_bundle_complete(args.artifact_roots.write_base, paths):
                    raise ValueError("archive bundle incomplete")
                updated = dict(store.get(key) or entry)
                updated.update(paths)
                updated["status"] = "archived"
                store.upsert(updated)
                _reclaim_after_archive(
                    args.artifact_roots, updated, keep=args.keep_audio
                )
                ok += 1
                print(f"{label}: archived ({source})")
            except asr.ASRDependencyError:
                failed += 1
                print(f"{label}: ASR dependency unavailable", file=sys.stderr)
            except Exception as exc:
                failed += 1
                # The `run` path states the code (`failed (ValueError)`), and
                # this one used to print fixed text with no reason at all
                # (QC3-F1).  `_safe_error_code` never throws and never echoes a
                # payload: it reads `code`/`last_code` or the class name.
                from bili_asr.coordinator import _safe_error_code

                print(
                    f"{label}: archive failed ({_safe_error_code(exc)})",
                    file=sys.stderr,
                )
    finally:
        if queue_conn is not None:
            queue_conn.close()
        _print_in_process_constructions("asr", runner, asr_count.value)
        if runner is not None:
            runner.release()
    print(f"asr: {ok} archived" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0
