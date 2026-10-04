"""Transcript publication and proofread handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import sys
from bili_asr.formatting import pubdate_utc

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _archive_database_exists,
    _declared_bundle_paths,
    _identity_from_entry,
    _is_excluded,
    _metadata_database_path,
    _open_read_connection,
    _open_read_repository,
    _open_subtitle_connection,
    _selector_cannot_name_a_part,
    _subtitle_schema_rebuild_line,
    _subtitle_selector,
    _todo_for_bvid,
)
from bili_asr.config import resolve_sessdata

def _cmd_publish_transcripts(args: argparse.Namespace) -> int:
    """Publish the stored transcripts as complete archive bundles (contract §7).

    ``cli.py`` composes the layers here, as the cross-layer rule requires: the
    store is read through ``TranscriptRepository`` on the read-only connection,
    the winner and the manifest row are the pure service's, the publication is
    the shipped archive writer, and the record is ``ManifestStore``.  Nothing is
    written back into ``archive.db``.

    Per candidate, in the read's locked order: a row that already declares a
    **complete** bundle at the write base is ``already_published`` and nothing is
    written for it — no file, no marker, no row (§5.4) — which is what makes a
    second run byte-identical.  Otherwise the winner's stored body is read,
    mapped to the writer's segment shape, published under the write base,
    re-asked of the same completeness reader ``verify`` calls, and only then
    recorded (§5.1's fifteen keys merged into the row the part already has,
    ``status: archived``).  A publication the reader does not confirm is
    ``failed`` and records no row.  When the writer unwound — it returned, raised
    or was interrupted by ``Ctrl-C`` — its staging directory is gone and the next
    pass republishes the bundle: that is the state a run killed between its write
    and its ``upsert`` leaves behind.  A termination that does not unwind the
    writer — ``SIGKILL``, ``SIGTERM`` at its default disposition, the OOM killer —
    leaves the fixed-name ``transcripts/.archive-bundle-stage`` in place instead,
    and the writer then refuses every later publication into that root — each
    candidate reporting ``failed (OSError)`` — until an operator removes it.

    Every line's ``<reason>`` is a bounded redacted scalar (§7): this command's
    own two literals ``empty_transcript`` / ``bundle_incomplete`` where it
    decides, and ``coordinator._safe_error_code`` otherwise — never an exception
    message, a path or a URL.

    Exit taxonomy: ``0`` when every candidate is published or already published,
    including a run with no candidate at all; ``1`` for a usage/configuration
    error (a refused artifact root, an unknown ``--bvid``, a non-positive
    ``--limit-parts``, a missing or unreadable database, the transcript-schema
    guard, a held archive-writer lock) and for a candidate that could not be
    published.  No path of this command produces ``2``: it opens no socket, and
    ``_UsageErrorArgumentParser`` maps argparse's own usage exit to ``1``.
    """
    from bili_asr import archive
    from bili_asr.coordinator import _safe_error_code
    from bili_asr.manifest import ManifestStore
    from bili_asr.services.manifest_derivation import duration_s_from_ms
    from bili_asr.services.transcript_projection import (
        ordered_candidates,
        projection_row,
        writer_segments,
    )
    from bili_asr.storage import TranscriptRepository

    if args.limit_parts is not None and args.limit_parts < 1:
        print(
            "publish-transcripts: --limit-parts must be a positive integer",
            file=sys.stderr,
        )
        return 1
    bvid, page_index = _subtitle_selector(args.bvid)
    if bvid is not None and _selector_cannot_name_a_part(bvid):
        # The same configuration error as an unknown bvid, decided on the
        # argument alone and before the database is opened: a selector the
        # storage identifier rule cannot hold names no part in any database.
        print(f"publish-transcripts: unknown --bvid {args.bvid}", file=sys.stderr)
        return 1
    connection = _open_subtitle_connection(
        "publish-transcripts", args.archive_root, read_only=True
    )
    if connection is None:
        return 1
    candidates: tuple[Any, ...] = ()
    published = already_published = failed = 0
    try:
        repository = TranscriptRepository(connection)
        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
            # "Unknown" ranges over the store's part relation, not over the
            # candidate set: a stored part that holds no transcript is known and
            # yields zero candidates, exit 0 (§2.2).
            print(f"publish-transcripts: unknown --bvid {args.bvid}", file=sys.stderr)
            return 1
        candidates = ordered_candidates(
            (dict(row) for row in repository.list_stored_transcripts(bvid, page_index)),
            args.limit_parts,
        )
        store = ManifestStore(root=args.archive_root)
        recorded = store.load()
        write_base = args.artifact_roots.write_base
        for candidate in candidates:
            work_id = candidate.work_id
            part = candidate.part
            kind = candidate.transcript["source_kind"]
            language = candidate.transcript["language"]
            version = candidate.transcript["version"]
            declared = _declared_bundle_paths(recorded.get(work_id))
            if declared is not None and archive.archive_bundle_complete(
                write_base, declared
            ):
                # Probed at the write base, deliberately (§5.4): the promise is
                # that the products are under the configured root, and asking
                # every read base would answer `already_published` for a bundle
                # the configured root does not hold.
                already_published += 1
                print(f"{work_id}: already_published")
                continue

            reason: str | None = None
            written: dict[str, str] = {}
            try:
                record = repository.read_transcript(
                    part["video_part_id"], kind, language, version
                )
            except Exception as exc:
                # One candidate's read failing is that candidate's failure: the
                # rest of the run still publishes and the summary still counts.
                reason = str(_safe_error_code(exc))
            if reason is None and record is None:
                # Unreachable for the identity this run's own read just answered
                # — a stored version is never deleted and no shipped writer
                # deletes one — kept bounded rather than assumed, so a store that
                # moved under the run reports a failed candidate instead of
                # raising out of the loop.
                reason = str(_safe_error_code(LookupError()))
            if reason is None:
                try:
                    segments = writer_segments(record.segments)
                except ValueError:
                    # §7's own literal.  A stored transcript is never empty
                    # (`storage/models.py:382-383`), so this names a shape the
                    # store cannot deliver rather than a live path.
                    reason = "empty_transcript"
            if reason is None:
                # The writer's entry: the part's own facts plus §3.4's two
                # renderings, which are the values `projection_row` records one
                # layer down — the frontmatter is built from this entry, so the
                # date and the seconds have to be resolved before the write.
                entry = {
                    "bvid": part["bvid"],
                    "work_id": work_id,
                    "page_index": part["page_index"],
                    "cid": part["cid"],
                    "title": part["part_title"],
                    "video_title": part["video_title"],
                    "duration_s": duration_s_from_ms(part["duration_ms"]),
                    "pubdate_str": pubdate_utc(part["pubdate"]),
                }
                try:
                    written = archive.write_archive(
                        write_base, entry, segments, source=kind
                    )
                    if not archive.archive_bundle_complete(write_base, written):
                        reason = "bundle_incomplete"
                    else:
                        # Merged into the effective row, the way the chain's own
                        # ``archived`` transition merges (``coordinator.py:520-527``
                        # reads the current entry, updates it and upserts it): the
                        # projection's own keys win, and every key the fifteen do
                        # not restate — ``audio_path``, ``artifact_paths`` — is
                        # carried over, so the row keeps naming what it named.
                        merged = {
                            **(recorded.get(work_id) or {}),
                            **projection_row(part, candidate.transcript, written),
                        }
                        store.upsert(merged)
                except Exception as exc:
                    reason = str(_safe_error_code(exc))
            if reason is not None:
                failed += 1
                print(f"{work_id}: failed ({reason})")
                continue
            published += 1
            print(
                f"{work_id}: published (source={kind} lang={language} "
                f"version={version} cues={len(segments)}) {written['md_path']}"
            )
    finally:
        connection.close()
    print(
        f"publish-transcripts: candidates={len(candidates)} published={published} "
        f"already_published={already_published} failed={failed}"
    )
    return 1 if failed else 0


def _proofread_target(args: argparse.Namespace) -> tuple[str, int] | None:
    """Resolve ``--bvid``/``--part`` into one concrete part.

    ``None`` means the configuration error was already printed.  A selector
    that cannot name a stored part — or names more than one without ``--part`` —
    is the documented exit-1 usage error, decided before any route is read.
    """

    selector_bvid, selector_part = _subtitle_selector(args.bvid)
    if selector_bvid is None or _selector_cannot_name_a_part(selector_bvid):
        print(f"{args.command}: unknown --bvid {args.bvid}", file=sys.stderr)
        return None
    part = selector_part if selector_part is not None else 0
    return selector_bvid, part


def _cmd_proofread(args: argparse.Namespace) -> int:
    """Build the side-by-side table + alignment jsonl for one part.

    Exit ``0`` when the table and jsonl are written; ``1`` for a usage error
    (unknown selector), a missing route, or a Guard A violation — each printed
    bounded, naming the work id and, for the guard, the block.  ``2`` is never
    produced: no socket is opened and argparse's own usage exit is mapped to 1.

    ``--asr-root`` / ``--caption-root`` move each route's *read* independently
    (the E2E's two roots hold one route each); neither is resolved or validated
    here, because the readers already refuse a root that does not yield its
    route with a message naming the path they looked at — the same line whether
    the root was defaulted or passed.  They are not routed through
    ``roots_for``: that is the write base's guard, and the two read roots are
    neither written to nor created.
    """

    from bili_asr.proofread import GuardViolationError, ProofreadRouteError, build_sidebyside

    target = _proofread_target(args)
    if target is None:
        return 1
    bvid, part = target
    work_id = f"{bvid}:p{part}"
    try:
        sidebyside_path, align_path = build_sidebyside(
            bvid, part,
            archive_root=args.archive_root,
            artifact_root=os.fspath(args.artifact_roots.write_base),
            asr_root=args.asr_root,
            caption_root=args.caption_root,
        )
    except ProofreadRouteError as exc:
        print(f"proofread: {exc}", file=sys.stderr)
        return 1
    except GuardViolationError as exc:
        print(f"proofread: {exc}", file=sys.stderr)
        return 1
    print(f"{work_id}: side-by-side written ({sidebyside_path})")
    print(f"{work_id}: alignment written ({align_path})")
    return 0


def _cmd_proofread_merge(args: argparse.Namespace) -> int:
    """Merge a completed side-by-side定稿 into the final transcript artifact.

    The定稿 is the marked-up copy of this part's ``.sidebyside.md`` — same bytes
    plus ``>>`` decision markers on the block headings; it is found as the only
    ``.sidebyside.md.定稿`` file directly under ``.tmp/proofread-work/inputs/``.
    Exit ``0`` when the transcript and the corrections accounting are written;
    ``1`` for a usage error, a missing input, or a merge-contract violation.
    """

    from bili_asr.proofread import (
        ProofreadMergeError,
        ProofreadRouteError,
        merge_sidebyside,
    )

    target = _proofread_target(args)
    if target is None:
        return 1
    bvid, part = target
    work_id = f"{bvid}:p{part}"
    inputs_dir = (
        Path(os.fspath(args.artifact_roots.write_base))
        / ".tmp" / "proofread-work" / "inputs"
    )
    marked = inputs_dir / f"{bvid}.p{part}.sidebyside.md.定稿"
    if not marked.is_file():
        print(
            f"proofread-merge: {work_id}: no completed side-by-side at {marked}; "
            "copy the .sidebyside.md there and add >> decision markers",
            file=sys.stderr,
        )
        return 1
    try:
        transcript_path, corrections_path = merge_sidebyside(
            marked, bvid=bvid, part=part,
            artifact_root=os.fspath(args.artifact_roots.write_base),
        )
    except ProofreadMergeError as exc:
        print(f"proofread-merge: {work_id}: {exc}", file=sys.stderr)
        return 1
    except ProofreadRouteError as exc:
        print(f"proofread-merge: {exc}", file=sys.stderr)
        return 1
    print(f"{work_id}: proofread transcript written ({transcript_path})")
    print(f"{work_id}: corrections accounting written ({corrections_path})")
    return 0


