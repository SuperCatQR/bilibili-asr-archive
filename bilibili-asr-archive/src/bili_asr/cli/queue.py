"""Queue-producing handlers (derive-manifest, derive-audio-inventory, download-audio)."""

from __future__ import annotations

import os
import sys
import time

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _archive_database_exists,
    _identity_from_entry,
    _is_excluded,
    _metadata_database_path,
    _open_read_connection,
    _open_read_only_connection,
    _open_read_repository,
    _open_subtitle_connection,
    _queue_source_is_manifest,
    _record_api_error,
    _resolve_sessdata,
    _store_audio_todo,
    _store_transcript_todo,
    _todo_for_bvid,
)

def _cmd_derive_manifest(args: argparse.Namespace) -> int:
    """Append the manifest rows the stored audio queue needs.

    The queue is the store's own work relation — every part that holds no
    transcript and is not ``gone`` (``v_pending_subtitles``, read through
    ``list_pending_subtitle_parts``) — and never the metadata backlog ``status``
    prints as ``pending:``.  ``cli.py`` composes the layers here, as the
    cross-layer rule requires: the database is opened read-only through the
    subtitle guard, the derivation is a pure service call, and the write is
    ``ManifestStore.upsert`` per appended row under the manifest's own lock.

    Exit taxonomy: 0 the derivation completed, including an empty queue (a
    missing database, an unreadable one, the schema-rebuild guard, a held
    archive-writer lock and a usage error are all answered by their shipped
    paths with 1); no path of this command produces 2.  A write that fails
    part-way through the append loop is reported rather than left to a
    traceback: the summary is still printed, with ``derived`` counting the rows
    that did reach the manifest, one ``derive-manifest: append failed after <k>
    row(s)`` line on stderr names that count, and the exit code stays 1.  The
    rows already appended are complete lines the chain reads and a re-run
    answers ``already_derived`` for them, so the run stays resumable and only
    its report used to be missing.
    """
    from bili_asr.manifest import ManifestStore
    from bili_asr.page_identity import parse_work_id
    from bili_asr.services.manifest_derivation import (
        QUEUE_STATUS,
        SKIP_ALREADY_DERIVED,
        SKIP_CHAIN_OWNED,
        SKIP_IDENTITY_MISMATCH,
        derive_rows,
    )
    from bili_asr.storage import TranscriptRepository

    store = ManifestStore(root=args.archive_root)
    connection = _open_subtitle_connection(
        "derive-manifest", args.archive_root, read_only=True
    )
    if connection is None:
        return 1
    try:
        repository = TranscriptRepository(connection)
        queue = [dict(row) for row in repository.list_pending_subtitle_parts()]
        outcome = derive_rows(
            queue,
            repository.read_video_pubdates([part["bvid"] for part in queue]),
            store.load(),
        )
    finally:
        connection.close()

    def _print_summary(derived: int) -> None:
        # §8's one summary line, printed on the success path and on the append's
        # failure path alike: the counts an operator reads never depend on how
        # far the run got, and ``derived`` is the number of rows that reached
        # the manifest rather than the number the derivation proposed.
        print(
            f"derive-manifest: queue={len(queue)} derived={derived} "
            f"{SKIP_ALREADY_DERIVED}={len(outcome.already_derived)} "
            f"{SKIP_CHAIN_OWNED}={len(outcome.chain_owned)} "
            f"{SKIP_IDENTITY_MISMATCH}={len(outcome.identity_mismatch)}"
        )

    written = 0
    for row in outcome.appended:
        try:
            # The bridge never emits a bare-bvid key, so the page-qualified form
            # is re-validated at the write rather than trusted from the
            # derivation: ``upsert`` checks the same pair, but it also accepts a
            # bare row when the bvid already has a legacy one, which is a state
            # this command promises never to create.  Unreachable defence for
            # any store the shipped writers produce — the view and
            # ``format_work_id`` agree on every bvid the gateway admits — kept
            # so the promise is enforced where it is made, not assumed.
            stored_bvid, _page = parse_work_id(str(row["work_id"]))
            if stored_bvid != row["bvid"]:
                raise ValueError(
                    f"derived work_id {row['work_id']!r} does not match "
                    f"bvid {row['bvid']!r}"
                )
            store.upsert(row)
        except Exception as exc:
            # The guard spans the write and the validation in front of it, and
            # nothing else: a per-row write can fail (the manifest lock, the
            # append's own write/fsync, the record validation) and until this
            # guard existed the summary went down with the traceback on exactly
            # the run where the operator needs to know how much of the queue is
            # already durable.  The per-row ``print`` below stays outside it —
            # an output failure is not an append failure, and the line is only
            # true for the rows already written.
            print(
                f"derive-manifest: append failed after {written} row(s): "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            _print_summary(written)
            return 1
        written += 1
        print(f"{row['work_id']}: {QUEUE_STATUS} (duration_s={row['duration_s']})")
    for work_id in outcome.chain_owned:
        print(f"skip {work_id} {SKIP_CHAIN_OWNED}")
    for work_id in outcome.identity_mismatch:
        print(f"skip {work_id} {SKIP_IDENTITY_MISMATCH}")
    _print_summary(len(outcome.appended))
    return 0


def _cmd_derive_audio_inventory(args: argparse.Namespace) -> int:
    """Reconcile the audio store with the disk the manifest names.

    ``cli.py`` composes the layers here, as the cross-layer rule requires: the
    database is opened through the shipped read-command guard, the read sets come
    from the repository, the reconciliation is a pure service call, and the only
    writes are the ones ``mark_audio_acquired`` already owns.  The service does
    not print; this handler owns every operator-facing line.

    The database is opened ``read_only=False`` because a newly observed object is
    recorded — this command *writes the store*, unlike ``derive-manifest``, which
    only appends to the manifest.  It never writes the *filesystem*: the counters
    are reports, and ``missing`` names an absence rather than acting on it.

    **The whole reconciliation is inside the writer lock** (``_ARCHIVE_WRITER_COMMANDS``
    contains this command, so ``_dispatch_command`` holds ``archive_writer`` around
    this call).  That is why the read sets fetched below are consistent with the
    walk: a concurrent ``download-audio`` cannot add an object between them.

    Exit taxonomy: 0 the reconciliation ran, including a zero-row one (an empty
    result is success, matching ``derive-manifest``); 1 a shipped refusal path (a
    missing or unreadable ``archive.db``, the schema-rebuild guard, a held
    archive-writer lock, or a usage error) **and also a store failure mid-walk**;
    no path produces 2.

    A store failure is bounded rather than left to a traceback: ``record`` commits
    one transaction per row, so a failure part-way through leaves rows already
    written, and the summary still prints with the counters reached so far plus
    one stderr line naming the failure and how many rows were written before it.
    Silence would be worst exactly when the store is in a state worth reporting.
    """
    from bili_asr.artifact_root import ArtifactRootError, roots_for
    from bili_asr.manifest import ManifestStore
    from bili_asr.services.audio_inventory import AudioInventoryOutcome, reconcile_audio_inventory
    from bili_asr.storage import MediaQueueRepository

    try:
        roots = roots_for(args.archive_root, flag_value=args.artifact_root)
    except ArtifactRootError as exc:
        print(f"derive-audio-inventory: {exc}", file=sys.stderr)
        return 1

    connection = _open_subtitle_connection(
        "derive-audio-inventory", args.archive_root, read_only=False
    )
    if connection is None:
        return 1

    outcome: AudioInventoryOutcome | None = None
    try:
        repository = MediaQueueRepository(connection)
        entries = ManifestStore(root=args.archive_root).load()
        outcome = reconcile_audio_inventory(
            roots=roots,
            entries=entries,
            known_objects=repository.read_audio_objects(),
            known_audio_ids=repository.read_audio_object_ids(),
            linked_audio_ids=repository.read_linked_audio_ids(),
            part_durations=repository.read_part_durations(entries),
            record=repository.mark_audio_acquired,
            moment=int(time.time()),
            deep=bool(args.deep),
        )
    except Exception as exc:  # noqa: BLE001 - bounded, reasoned, and reported below
        # The walk died part-way.  `mark_audio_acquired` is one transaction per
        # row, so whatever was recorded before the failure is committed and the
        # operator must be told.  §3.1's summary line still prints, with the
        # **total** the store now holds in the `recorded` slot and the other three
        # reported as unknown: the per-walk counters are built inside the service
        # and are not available once it raises, and inventing them here would be
        # worse than saying what is knowable.  The count is a store read
        # (`COUNT(*)`), not a guess, and a second failure while reporting must not
        # mask the first.
        total = 0
        known = True
        try:
            total = len(repository.read_audio_object_keys())
        except Exception:  # noqa: BLE001 - the report must not itself raise
            known = False
        if known:
            print(
                f"derive-audio-inventory: recorded={total} already=? missing=? "
                f"unlinked=? (walk aborted; recorded is the store's current total)"
            )
        print(
            f"derive-audio-inventory: failed after {total} object(s) in the "
            f"store: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        connection.close()

    # §3.1's one summary line: the four counters an operator reads, in their
    # fixed order, printed on every success path including the empty one.
    print(outcome.summary_line())
    for storage_key in outcome.unreadable:
        # A present-but-unreadable file fits no counter §3.1 defines: it is not
        # `missing` (the file is there) and cannot be recorded (no digest).  It is
        # named here instead, so the number is not silently smaller than the tree.
        print(f"derive-audio-inventory: unreadable: {storage_key}", file=sys.stderr)
    return 0

#: The four product keys a publication records and a recorded row declares
#: (contract §5.1).  Kept as the command's own tuple rather than reached for
#: through ``archive``'s private one: the row's four keys and the writer's four
def _cmd_download_audio(args: argparse.Namespace) -> int:
    from bili_asr import audio, bili_client
    from bili_asr.manifest import ManifestStore
    from bili_asr.services import queue_source as qs

    if not args.missing_subs and not args.bvid:
        print("download-audio: select targets with --missing-subs "
              "and/or --bvid", file=sys.stderr)
        return 1

    use_manifest = _queue_source_is_manifest(args)
    if use_manifest:
        qs.print_manifest_deprecation()

    # The store gap views are the default queue input; a part holding AI
    # subtitles is never selected (its caption route is not exhausted, so it
    # is outside v_missing_audio) — the inversion of the pre-cutover root
    # cause.  The manifest path is the rollback and is byte-for-byte the old
    # behaviour.
    queue_conn = None
    queue_source = None
    if use_manifest:
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
    else:
        store = ManifestStore(root=args.archive_root)
        todo, queue_source, failed = _store_audio_todo(args)
        if failed:
            return 1
        queue_conn = queue_source.connection
        if not todo:
            print("download-audio: queue empty (no parts need audio)")
            queue_conn.close()
            return 0

    sessdata = _resolve_sessdata(args)
    client = bili_client.BiliClient(sessdata=sessdata)
    from bili_asr.page_identity import artifact_stem
    from bili_asr.subtitles import resolve_page_identity

    ok = failed = 0
    risk_interrupted = False
    # The products' base, resolved once (contract §4).  A write resolves on `write_base`
    # alone — never on which `audio/` directory happens to exist.
    write_base = args.artifact_roots.write_base
    for key, entry in todo:
        target = _identity_from_entry(entry, key)
        label = str(key)
        try:
            from bili_asr.page_identity import PageIdentity

            if isinstance(target, PageIdentity):
                stem = artifact_stem(target)
                out_path = os.path.join(write_base, "audio", f"{stem}.m4a")
            elif isinstance(target, str):
                target = resolve_page_identity(client, target)
                label = target.work_id
                stem = artifact_stem(target)
                out_path = os.path.join(
                    write_base, "audio", f"{stem}.m4a"
                )
            else:
                raise TypeError("unsupported download target")
            label = target.work_id
            final = audio.download_audio(
                client, target, out_path, store=store,
                artifact_roots=args.artifact_roots,
            )
            from bili_asr.path_policy import confined_audio_path
            try:
                returned_relative = os.path.relpath(
                    os.fspath(final), os.fspath(write_base)
                )
            except (OSError, ValueError, TypeError):
                returned_relative = ""
            confined = confined_audio_path(
                write_base, returned_relative, require_exists=True
            )
            if confined is None:
                raise ValueError("invalid audio path")
            absolute_audio = os.fspath(confined)
            final = os.path.relpath(confined, os.fspath(write_base))
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
        # Store write-back: the acquisition is positive audio evidence, taking
        # the part out of v_missing_audio (contract §4c/§4d).  The manifest
        # row the downloader already upserted stays the attempt ledger.
        if not use_manifest and queue_source is not None:
            qs.mark_audio_acquired(
                queue_source,
                bvid=entry.get("bvid", label),
                page_index=int(entry.get("page_index") or 0),
                audio_path=absolute_audio,
                declared_relative=final,
            )
        if key != todo[-1][0]:
            time.sleep(3.0)

    if queue_conn is not None:
        queue_conn.close()
    print(f"download-audio: {ok} audio_ok"
          + (f", {failed} failed" if failed else ""))
    if risk_interrupted:
        return 2
    return 1 if failed else 0
