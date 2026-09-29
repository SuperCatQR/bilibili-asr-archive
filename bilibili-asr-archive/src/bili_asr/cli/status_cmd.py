"""Status / coverage / runs handlers."""

from __future__ import annotations

from typing import Any

import json
import sys

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _MAX_DISPLAYED_PENDING_PARTS,
    _archive_database_exists,
    _metadata_database_path,
    _open_read_connection,
    _open_read_only_connection,
    _open_read_repository,
    _open_subtitle_connection,
    _record_api_error,
    _run_error_codes,
    _format_run_line,
    _subtitle_schema_rebuild_line,
    _subtitle_selector,
)
from bili_asr.config import redact_sessdata

def _cmd_status(args: argparse.Namespace) -> int:
    """Report metadata state from the fresh SQLite database only."""
    repository = _open_read_repository("status", args.archive_root)
    if repository is None:
        return 1
    try:
        connection = repository.connection
        counts = connection.execute(
            "SELECT (SELECT COUNT(*) FROM bilibili_users) AS users,"
            " (SELECT COUNT(*) FROM videos) AS videos,"
            " (SELECT COUNT(*) FROM video_parts) AS parts"
        ).fetchone()
        print(f"users: {counts['users']}")
        print(f"videos: {counts['videos']}")
        print(f"parts: {counts['parts']}")
        processing = connection.execute(
            "SELECT processing_status, COUNT(*) AS count FROM video_parts"
            " GROUP BY processing_status ORDER BY processing_status"
        ).fetchall()
        if processing:
            summary = ", ".join(
                f"{row['processing_status']}={row['count']}" for row in processing
            )
            print(f"processing: {summary}")
        # Queue view (B-D1): three gap groups from the store's own views.
        # Contract §4: the groups are NOT disjoint — their counts must never
        # be summed; the summary header reports each group separately.
        try:
            from bili_asr.services import queue_source as qs

            source = qs.open_queue_source(args.archive_root)
        except Exception:
            source = None
        if source is not None:
            try:
                conn = source.connection
                for label, view in (
                    ("missing subtitles", "v_missing_subtitle"),
                    ("missing audio", "v_missing_audio"),
                    ("missing transcripts", "v_missing_transcript"),
                ):
                    try:
                        rows = conn.execute(
                            f"SELECT bvid, page_index, part_title, video_title, "
                            f"pubdate FROM {view} ORDER BY pubdate DESC LIMIT 20"
                        ).fetchall()
                    except Exception:
                        continue
                    print(f"queue: {label}: {len(rows)} shown (top 20, newest first)")
                    for r in rows:
                        print(f"  {r['bvid']}:p{r['page_index']} {r['part_title']}")
            finally:
                conn_close = getattr(source, 'close', None)
                if callable(conn_close):
                    conn_close()
                else:
                    source.connection.close()
        pending = repository.list_pending_parts()
        print(f"pending: {len(pending)}")
        for row in pending[:_MAX_DISPLAYED_PENDING_PARTS]:
            print(f"  {row['work_id']}")
        hidden = len(pending) - _MAX_DISPLAYED_PENDING_PARTS
        if hidden > 0:
            print(f"  + {hidden} more pending part(s)")
        # The cursor row is reported exactly as stored: a failed or
        # risk-interrupted run leaves it untouched, so this line never implies
        # the cursor advanced past a failed page (C3).
        for user_row in connection.execute(
            "SELECT mid FROM bilibili_users ORDER BY mid"
        ):
            cursor = repository.read_cursor(int(user_row["mid"]))
            if cursor is not None:
                print(
                    f"cursor: mid={cursor.mid} next_page={cursor.next_page} "
                    f"state={cursor.state}"
                )
        return 0
    finally:
        repository.connection.close()


#: Coverage-side backlog statuses (exit-code contract §2): the row's own status
#: says the chain has not finished with it yet — normal operations, not damage.
#: Same set the integrity reader uses for `retryable_incomplete`
#: (`integrity.py` `if status in {...}: defects.add(RETRYABLE_INCOMPLETE)`).
_BACKLOG_STATUSES = frozenset(
    {"pending", "meta_ok", "sub_checked", "needs_audio", "audio_ok"}
)

#: Terminal-complete statuses (contract §2b R2): the row is finished as far as the
#: archive is concerned, so a missing artifact is *expected* rather than damage.
#: `gone` means the video is no longer available upstream — there was never going
#: to be a transcript.  It is in neither finding class: not backlog (no work
#: remains) and not defect (nothing is broken), so it must not move the exit code
#: by omission.  `archived` is terminal too, but only once its artifact is present;
#: an `archived` row with no artifact is real damage (`terminal_missing_artifact`)
#: and stays defect-class, which is why it is not in this set.
_TERMINAL_COMPLETE_STATUSES = frozenset({"gone"})

#: The one validity reason that means "the artifact is not there yet" rather
#: than "the artifact is there and broken".  A backlog row is an in-flight
#: status whose findings are exactly this reason — `empty`/`malformed`/… are
#: damage even on an in-flight row (contract §2: malformed verdicts belong to
#: the defect class, never to backlog).  The identity reasons are deliberately
#: **not** here (§2b R3): a declared path that escapes every read base, or a
#: schema-violating identity field, is corruption on a row that may still be in
#: flight, and absorbing it would hide exactly the regression R3 names.
_BACKLOG_REASONS = frozenset({"artifact_missing"})

#: Coverage diagnostics that are backlog (contract §2b R1): the fact they name is
#: "work not yet done, retryable", which is §2's backlog definition — so they are
#: reported but never exit-bearing on the default gate.  Every other diagnostic is
#: defect-class and keeps the command failing closed.
_BACKLOG_DIAGNOSTICS = frozenset({"retryable_attempt"})


def _cmd_coverage_quality(args: argparse.Namespace) -> int:
    import csv
    import io
    from pathlib import Path
    from bili_asr.quality import (
        QualityAnalyzer,
        REASON_CODES,
        ReferenceAgreement,
        ReferenceUnavailable,
    )
    from bili_asr.coverage_report import _select_scope, _diagnostic_rows
    from bili_asr.sidecar_projection import (
        ReaderPolicy,
        project_attempt_records,
        ORDINARY_HISTORY_DIAGNOSTICS,
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
        for code in manifest_diagnostics - ORDINARY_HISTORY_DIAGNOSTICS
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

    # One reference compares against one transcript, so it is only meaningful
    # when the selection resolves to exactly one row.  Both the usage shape and
    # the comparison itself are reported as diagnostics, never as tracebacks.
    reference_path = getattr(args, "reference", None)
    if reference_path is not None:
        if len(selected) != 1:
            print(
                "coverage: --reference needs exactly one selected row "
                f"(got {len(selected)})",
                file=sys.stderr,
            )
            return 1
        reference_path = Path(reference_path)
        if not reference_path.is_file():
            print("coverage: reference unreadable", file=sys.stderr)
            return 1

    denominator_available = (
        manifest_state == "available" and scope_state == "available"
    )
    rows: list[dict[str, object]] = []
    reason_counts: dict[str, int] = {code: 0 for code in REASON_CODES}
    total_cues = 0
    valid_work_items = 0
    has_defects = False
    has_defect_rows = False
    agreement: ReferenceAgreement | None = None
    # Where each row's doubtful cues are, keyed by work_id: a value the frozen
    # CSV columns cannot carry, so it is held here for the stderr pass below.
    low_confidence_by_work_id: dict[str, tuple[float, ...]] = {}

    analyzer = QualityAnalyzer()
    for work_id, entry in sorted(selected.items()):
        try:
            result = analyzer.analyze(
                entry, root, reference_path, artifact_roots=args.artifact_roots
            )
        except ReferenceUnavailable as exc:
            print(f"coverage: {exc.reason}", file=sys.stderr)
            return 1
        row_dict: dict[str, object] = {
            "work_id": work_id,
            "source": result.source,
            "language": result.language,
            "status": result.status,
            "cue_count": result.cue_count,
            "artifact_count": result.artifact_count,
            # The projection: defect codes first, then the advisory content
            # codes, so a reader sees one reason list per row.  Only
            # ``result.reasons`` feeds validity and the exit status below.
            "reasons": [*result.reasons, *result.content_reasons],
            "diagnostics": list(result.diagnostics),
        }
        if result.low_confidence_at:
            low_confidence_by_work_id[work_id] = result.low_confidence_at
        if result.reference is not None:
            agreement = result.reference
        rows.append(row_dict)
        for r in row_dict["reasons"]:
            reason_counts[r] = reason_counts.get(r, 0) + 1
        total_cues += result.cue_count
        if not result.reasons and not result.diagnostics:
            valid_work_items += 1
        elif str(result.status) in _TERMINAL_COMPLETE_STATUSES:
            # §2b R2: terminal-complete is neither class, so an absent artifact
            # here is *expected* — `gone` means the video is no longer available
            # upstream, so there was never going to be a transcript.  It is
            # non-exit-bearing in **both** modes: `--strict` is "any finding of
            # either class" (contract §2), and a row in neither class is not one.
            # `verify` produces no finding for `gone` either, and the two readers
            # must agree on the same input, so this branch does not set either
            # gate.  Genuine corruption on such a row still counts: a present but
            # malformed artifact, or an unreadable/oversized one, is damage on any
            # status and `verify` flags it too.
            if set(result.reasons) - _BACKLOG_REASONS or result.diagnostics:
                has_defects = True
                has_defect_rows = True
        else:
            # Any finding, either class — the `--strict` total and the
            # pre-cutover gate (contract §2).
            has_defects = True
            # Backlog (contract §2): an in-flight row whose only problem is
            # that its artifact does not exist yet.  A row whose artifact is
            # present but unreadable, a row whose declared path is unusable
            # (§2b R3), or a terminal row missing its artifact, is damage and
            # must not hide behind the row's status.
            if not (
                str(result.status) in _BACKLOG_STATUSES
                and not result.diagnostics
                and set(result.reasons) <= _BACKLOG_REASONS
            ):
                has_defect_rows = True

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
    if agreement is not None:
        # The reference's basename and the two compared lengths only: the
        # operator's path, a URL, or a credential never enters the report.
        quality_data["reference"] = {
            "work_id": rows[0]["work_id"],
            "reference": agreement.reference,
            "agreement": agreement.agreement,
            "floor": agreement.floor,
            "compared_chars": {
                "transcript": agreement.compared_chars[0],
                "reference": agreement.compared_chars[1],
            },
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
        # The frozen CSV columns carry the reason names, so the values a reason
        # stands for go to stderr — the same channel the reference ratio uses.
        # `low_confidence` shipped as a bare code with no location, which left
        # the operator reading `raw.json` by hand to find the doubtful passage
        # (residual R1 of 20260912-quality-signal-merge).  One line per row that
        # has any, so a long run's stderr states *where* the doubt is.
        for r in rows:
            low_at = low_confidence_by_work_id.get(str(r.get("work_id")), ())
            if low_at:
                print(
                    f"coverage: {r.get('work_id')} low-confidence at "
                    + ", ".join(f"{value}s" for value in low_at),
                    file=sys.stderr,
                )
        if agreement is not None:
            # CSV keeps its frozen columns, so the ratio goes to stderr.
            print(
                f"coverage: reference agreement {agreement.agreement:.4f} "
                f"against {agreement.reference} "
                f"({agreement.compared_chars[0]} vs "
                f"{agreement.compared_chars[1]} chars, floor {agreement.floor})",
                file=sys.stderr,
            )

    if getattr(args, "strict", False):
        # Pre-cutover gate (contract §2): any finding of either class.
        return 1 if (diagnostic_rows or has_defects) else 0
    # Default gate (contract §2): defect-class rows and diagnostics only.
    return 1 if (diagnostic_rows or has_defect_rows) else 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    from bili_asr.coverage_report import CoverageReport
    try:
        if getattr(args, "quality", False):
            return _cmd_coverage_quality(args)
        if getattr(args, "reference", None) is not None:
            # The reference is a quality input; without --quality there is no
            # report to carry it, so say so instead of ignoring the argument.
            print("coverage: --reference requires --quality", file=sys.stderr)
            return 1
        from bili_asr.sidecar_projection import ReaderPolicy
        policy = ReaderPolicy(mode="trusted_archive") if getattr(args, "trusted_local", False) else None
        report = CoverageReport.build(
            args.archive_root, scope=args.scope, policy=policy,
            artifact_roots=args.artifact_roots,
        )
        sys.stdout.write(report.to_json() if args.format == "json" else report.to_csv())
        if args.format == "json":
            sys.stdout.write("\n")
        diagnostics = report.data["diagnostics"]
        if getattr(args, "strict", False):
            # Pre-cutover gate (contract §2): any finding of either class.
            return 1 if diagnostics else 0
        # Default gate (contract §2): the same two-class rule `--quality` and
        # `verify` use.  `retryable_attempt` is backlog (§2b R1) — "work not yet
        # done, retryable" — so gating on the raw diagnostic list made a
        # backlog-shaped archive exit 1 while `verify` exited 0 on the same input.
        return 1 if [
            row for row in diagnostics if row["code"] not in _BACKLOG_DIAGNOSTICS
        ] else 0
    except Exception:
        print("coverage: diagnostic coverage_report_unavailable", file=sys.stderr)
        return 1


def _cmd_runs(args: argparse.Namespace) -> int:
    """List ingestion runs newest-first from the fresh SQLite database.

    Non-terminal ``running`` rows are rendered too: abnormal termination
    can leave a stale run behind and hiding it would hide real state (C2).
    Ordering is deterministic: ``started_at`` descending, with same-second
    runs tie-broken by ``run_id`` descending.
    """
    repository = _open_read_repository("runs", args.archive_root)
    if repository is None:
        return 1
    try:
        if args.limit is not None and args.limit < 1:
            print("runs: --limit must be a positive integer", file=sys.stderr)
            return 1
        stats_rows = repository.run_stats()
        if not stats_rows:
            print("runs: empty")
            return 0
        # Newest first; two runs sharing the second-resolution started_at
        # order deterministically on the opaque run_id (run_id descending).
        ordered = sorted(
            stats_rows,
            key=lambda row: (row["started_at"], row["run_id"]),
            reverse=True,
        )
        selected = ordered if args.limit is None else ordered[: args.limit]
        error_codes = _run_error_codes(
            repository, [str(row["run_id"]) for row in selected]
        )
        for row in selected:
            print(_format_run_line(row, error_codes.get(str(row["run_id"]))))
        return 0
    finally:
        repository.connection.close()


_PILOT_PROCESSABLE = frozenset(
    {"meta_ok", "subtitle_done", "needs_audio", "audio_ok"}
)
_PILOT_SKIP_HARVEST = frozenset(
    {"subtitle_done", "needs_audio", "audio_ok", "archived"}
)
