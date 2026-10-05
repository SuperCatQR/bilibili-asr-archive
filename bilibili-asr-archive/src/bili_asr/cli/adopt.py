"""Import verified manifest-era transcript bundles without running ASR again."""

from __future__ import annotations

from bili_asr.diagnostics import write_stderr

import argparse
import sqlite3
import sys
import time
import uuid

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT, _ARTIFACT_ROOT_HELP, _open_subtitle_connection,
    _selector_cannot_name_a_part, _subtitle_selector,
)


def add_adoption_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "adopt-transcripts",
        help="Import verified archived bundles into archive.db without ASR",
        description=(
            "Import complete manifest-era transcript bundles into archive.db so "
            "store queues skip work already archived. Verify bundle hashes, page "
            "identity and all published text before importing. Unresolved, damaged "
            "or incomplete bundles are reported and remain retryable. Existing "
            "stored transcripts are left alone. No network or ASR is used."
        ),
    )
    parser.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--artifact-root", default=None, help=_ARTIFACT_ROOT_HELP)
    parser.add_argument("--bvid", default=None, help="One video or bvid:pN already in the store")
    parser.add_argument("--limit-parts", type=int, default=None, help="Inspect at most N archived parts missing a stored transcript")


def _cmd_adopt_transcripts(args: argparse.Namespace) -> int:
    from bili_asr.manifest import ManifestStore
    from bili_asr.services.transcript_adoption import AdoptionRefused, read_archived_transcript
    from bili_asr.storage import AcquisitionRunRecord, TranscriptRepository

    command = "adopt-transcripts"
    if args.limit_parts is not None and args.limit_parts < 1:
        write_stderr(f"{command}: --limit-parts must be a positive integer")
        return 1
    bvid, page = _subtitle_selector(args.bvid)
    if bvid is not None and _selector_cannot_name_a_part(bvid):
        write_stderr(f"{command}: unknown --bvid {args.bvid}")
        return 1
    connection = _open_subtitle_connection(command, args.archive_root, read_only=False)
    if connection is None:
        return 1
    adopted = already = refused = 0
    runs: dict[str, str] = {}
    started_at = int(time.time())
    try:
        repository = TranscriptRepository(connection)
        if bvid is not None and not repository.list_selected_parts(bvid, page):
            write_stderr(f"{command}: unknown --bvid {args.bvid}")
            return 1
        parts = {
            row["work_id"]: dict(row)
            for row in connection.execute("SELECT work_id, video_part_id, cid FROM v_video_parts")
        }
        stored = {
            int(row[0]) for row in connection.execute("SELECT DISTINCT video_part_id FROM transcripts")
        }
        candidates = [
            (key, row) for key, row in sorted(ManifestStore(root=args.archive_root).load().items())
            if row.get("status") == "archived"
            and (bvid is None or row.get("bvid") == bvid)
            and (page is None or row.get("work_id") == f"{bvid}:p{page}")
        ]
        pending = []
        for key, row in candidates:
            part = parts.get(key)
            if part is not None and part["video_part_id"] in stored:
                already += 1
                print(f"{key}: already_stored")
            else:
                pending.append((key, row))
        candidates = pending
        if args.limit_parts is not None:
            candidates = candidates[:args.limit_parts]
        for key, row in candidates:
            part = parts.get(key)
            reason = "part_unknown"
            record = None
            if part is not None:
                for base in args.artifact_roots.read_bases():
                    try:
                        record = read_archived_transcript(row, part, base)
                        break
                    except AdoptionRefused as exc:
                        reason = exc.reason
            if record is None:
                refused += 1
                print(f"{key}: refused ({reason})")
                continue
            kind = "asr" if record.source_kind == "asr-local" else "subtitle"
            if kind not in runs:
                run_id = f"{command}:{kind}:{uuid.uuid4().hex}"
                repository.start_acquisition_run(AcquisitionRunRecord(
                    run_id=run_id, kind=kind,
                    selector_kind="bvid" if bvid is not None else "pending",
                    selector_target=args.bvid if bvid is not None else None,
                    requested_limit=args.limit_parts, credential_present=False,
                    started_at=started_at,
                ))
                runs[kind] = run_id
            arguments = dict(
                run_id=runs[kind], video_part_id=part["video_part_id"],
                language=record.language, segments=record.segments,
                started_at=started_at, finished_at=max(started_at, int(time.time())),
                created_at=max(started_at, int(time.time())),
            )
            try:
                if kind == "asr":
                    repository.record_local_transcript(
                        **arguments, model_name=record.model_name,
                        model_revision=record.model_revision, coverage=record.coverage,
                    )
                else:
                    repository.record_acquired_transcript(**arguments, source_kind=record.source_kind)
            except (sqlite3.Error, TypeError, ValueError) as exc:
                refused += 1
                print(f"{key}: refused (store_{type(exc).__name__})")
                continue
            adopted += 1
            stored.add(part["video_part_id"])
            print(f"{key}: adopted ({record.source_kind})")
        for kind, run_id in tuple(runs.items()):
            repository.finish_acquisition_run(
                run_id, max(started_at, int(time.time())),
                outcome="partial" if refused and adopted else "failed" if refused else "complete",
            )
            del runs[kind]
        print(f"{command}: adopted={adopted} already_stored={already} refused={refused}")
        return 1 if refused else 0
    except (OSError, sqlite3.Error, ValueError) as exc:
        write_stderr(f"{command}: failed ({type(exc).__name__})")
        return 1
    finally:
        # An interrupted import leaves already-committed parts available to the
        # next invocation, and the current process record must stop running.
        for run_id in runs.values():
            try:
                repository.finish_acquisition_run(run_id, max(started_at, int(time.time())), outcome="failed")
            except (sqlite3.Error, ValueError):
                pass
        connection.close()
