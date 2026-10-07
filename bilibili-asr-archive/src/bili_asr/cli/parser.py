"""argparse parser construction for the bili-asr CLI."""

from __future__ import annotations

import argparse

from bili_asr.cli._shared import (
    DEFAULT_ARCHIVE_ROOT,
    _MAX_AUDIO_GB_HELP,
    _MAX_AUDIO_GB_HELP_SCHEDULE,
    _UsageErrorArgumentParser,
)
from bili_asr.config import DEFAULT_MID, DEFAULT_PAGE_LIMIT


def _add_asr_policy(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--asr-with-subtitles",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Run local ASR even when AI/CC subtitles exist (default: enabled); "
            "use --no-asr-with-subtitles for subtitle-only archival"
        ),
    )

def build_parser() -> argparse.ArgumentParser:
    parser = _UsageErrorArgumentParser(
        prog="bili-asr",
        description="Bilibili ASR transcript archival CLI "
        "(AI/CC subtitles first, local FunASR fallback).",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(dest="command")
    from bili_asr.cli.adopt import add_adoption_parser
    from bili_asr.cli.workflow import add_workflow_parser

    add_adoption_parser(subparsers)
    add_workflow_parser(subparsers, archive_root=DEFAULT_ARCHIVE_ROOT)

    fetch_meta = subparsers.add_parser(
        "fetch-meta",
        help="Collect video metadata for a user into the SQLite archive database",
    )
    fetch_meta.add_argument("--mid", type=int, default=DEFAULT_MID,
                            help="Bilibili user mid")
    resume_or_start = fetch_meta.add_mutually_exclusive_group()
    resume_or_start.add_argument(
        "--resume", action="store_true",
        help="Resume from the stored cursor; fails when none exists",
    )
    resume_or_start.add_argument(
        "--start-page", type=int, default=None,
        help=(
            "Explicit one-based start page (overrides the stored cursor and "
            "may move it backwards, including with --skip-failed-page)"
        ),
    )
    fetch_meta.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    fetch_meta.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )
    fetch_meta.add_argument(
        "--limit-pages", type=int, default=None,
        help=f"Stop after collecting N pages (default: {DEFAULT_PAGE_LIMIT})",
    )
    fetch_meta.add_argument(
        "--page-retries", type=int, default=0,
        help=(
            "Retry the same upload-list page after rate-control or transport "
            "errors, 0-3 additional attempts (default: 0), waiting 30/60/120 "
            "seconds. Exhaustion preserves the normal failure and cursor; "
            "no page is skipped by retries."
        ),
    )
    fetch_meta.add_argument(
        "--skip-failed-page", action="store_true",
        help=(
            "Set the cursor past a page whose gateway call failed instead "
            "of leaving it wedged, so the next --resume makes progress. Every "
            "non-rate-limit failure is skipped, so a transient error is skipped "
            "too; a rate limit never is. The page is still recorded as failed "
            "in ingestion_pages and still shown by `runs`; this is never the "
            "default behaviour."
        ),
    )

    status = subparsers.add_parser(
        "status",
        help="Print collected metadata status from the SQLite archive database",
    )
    status.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)

    runs = subparsers.add_parser(
        "runs",
        help="List recent metadata collection runs from the SQLite archive database",
    )
    runs.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N recent runs (default: all)",
    )
    runs.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    asr_cmd = subparsers.add_parser("asr", help="Transcribe audio and write transcript archive")
    _add_asr_policy(asr_cmd)
    asr_cmd.add_argument("--pending", action="store_true", help="Process audio_ok entries")
    asr_cmd.add_argument("--bvid", default=None)
    asr_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    asr_cmd.add_argument("--limit", type=int, default=None)
    asr_cmd.add_argument(
        "--queue-source",
        choices=("store", "manifest"),
        default="store",
        help="Where to read the work queue: archive.db gap views (default) "
             "or the manifest (deprecated rollback)",
    )

    pilot = subparsers.add_parser(
        "pilot",
        help="Execute a bounded mixed-branch pilot (subtitle-hit and audio→ASR)",
        # RawDescription keeps the boundary statement's line breaks, so the
        # literal token `--scope failed` survives any terminal width (the
        # default formatter reflows and may break the word at its hyphen).
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Bounded mixed-branch probe (subtitle-hit and audio→ASR), not a corpus\n"
            "path. The stage-attempt ledger is written by the run coordinator behind\n"
            "`bili-asr run`, `bili-asr schedule` and `bili-asr campaign`: work archived\n"
            "through this entry point leaves no attempt records, so no per-stage truth\n"
            "exists for pilot work, and it is not reachable by `--scope failed`."
        ),
    )
    pilot.add_argument("--n", type=int, default=20)
    pilot.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    pilot.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help=_MAX_AUDIO_GB_HELP,
    )
    _add_asr_policy(pilot)
    pilot.add_argument(
        "--max-duration-min", type=int, default=45,
        help="Exclude rows longer than this many minutes from selection (0 = unlimited)",
    )
    pilot.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
    )
    pilot.add_argument(
        "--queue-source",
        choices=("store", "manifest"),
        default="store",
        help="Where to read the work queue: archive.db gap views (default) "
             "or the manifest (deprecated rollback)",
    )

    probe = subparsers.add_parser(
        "probe-subs",
        help="List the subtitle tracks the selected archive parts expose (read-only)",
    )
    probe.add_argument(
        "--bvid", default=None,
        help="Bvid, or bvid:pN for one part, already in the archive database",
    )
    probe.add_argument(
        "--limit-parts", type=int, default=None,
        help="Probe the first N parts of the pending enumeration",
    )
    probe.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    probe.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )

    harvest = subparsers.add_parser(
        "harvest-subs",
        help="Acquire subtitles for the selected archive parts as transcripts",
    )
    harvest.add_argument(
        "--bvid", default=None,
        help="Bvid, or bvid:pN for one part, already in the archive database "
             "(parts that already have a transcript included)",
    )
    harvest.add_argument(
        "--limit-parts", type=int, default=None,
        help="Bound the run to N parts (required unless a single bvid:pN is named)",
    )
    harvest.add_argument(
        "--language", default=None,
        help="Comma-separated upstream language codes, first match wins "
             "(default: the zh family, then en, CC before AI)",
    )
    harvest.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    harvest.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )

    dl = subparsers.add_parser(
        "download-audio",
        help="Download audio for videos without subtitles (needs_audio)",
    )
    dl.add_argument(
        "--missing-subs", action="store_true",
        help="Process every manifest entry with status needs_audio",
    )
    dl.add_argument(
        "--bvid", default=None,
        help="Restrict to a bvid or work_id (bvid:pN); STOP if unresolved "
             "or multi-part without an explicit page",
    )
    dl.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    dl.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
    )
    dl.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N videos (smoke runs)",
    )
    dl.add_argument(
        "--queue-source",
        choices=("store", "manifest"),
        default="store",
        help="Where to read the work queue: archive.db gap views (default) "
             "or the manifest (deprecated rollback)",
    )

    derive = subparsers.add_parser(
        "derive-manifest",
        help="Append manifest rows for the audio queue: parts with no transcript",
        description=(
            "Derive the audio queue from archive.db: every stored part that holds "
            "no transcript and is not gone is appended to the manifest as a "
            "needs_audio row, so the ASR/audio chain has work to select. The "
            "database is opened read-only and the manifest is only appended to; "
            "a row the chain already holds is left alone. An empty queue is "
            "success."
        ),
    )
    derive.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    inventory = subparsers.add_parser(
        "derive-audio-inventory",
        help="Reconcile the audio store with the files the manifest names",
        description=(
            "Reconcile audio_objects / part_audio_objects against the manifest's "
            "audio candidates and the audio tree: report how many objects were "
            "newly recorded, already known, named-but-absent, and unlinked to any "
            "part. The command is additive and read-only over the audio tree: no "
            "counter deletes, re-creates or moves a file, and an empty "
            "reconciliation is success."
        ),
    )
    inventory.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    inventory.add_argument(
        "--deep", action="store_true",
        help=(
            "Re-verify the digest of an object whose row is already present "
            "(default: trust the stored row and read no bytes for it)"
        ),
    )

    publish = subparsers.add_parser(
        "publish-transcripts",
        help="Publish the stored transcripts as archive bundles (fetches nothing)",
        description=(
            "Publish the stored transcripts as complete archive bundles: the four "
            "artifact families plus the bundle marker under the configured artifact "
            "root, and one archived manifest row per publication. The range is every "
            "stored part that holds a transcript, whatever its processing status — a "
            "gone part still holds local text — and --bvid narrows it to one video or "
            "one part. The command fetches nothing: no network, no download, no ASR. "
            "It reads archive.db read-only and writes the products below the "
            "artifact root, one row to the manifest and the archive-writer lock "
            "under <archive_root>/coordinator/, and a complete published bundle is "
            "never replaced, so a store that later gains a newer transcript version "
            "leaves the published product as it is. A row that already carries an "
            "earlier manifest state is outside what the archive's readers currently "
            "agree on."
        ),
    )
    publish.add_argument(
        "--bvid", default=None,
        help="Bvid, or bvid:pN for one part, already in the archive database",
    )
    publish.add_argument(
        "--limit-parts", type=int, default=None,
        help=(
            "Bound the run to the first N stored parts holding a transcript; "
            "with --pending, attempt at most N incomplete parts"
        ),
    )
    publish.add_argument(
        "--io-timeout-seconds", type=float, default=60.0,
        help="Publication setup, each candidate and final snapshot deadline (default: 60; finite positive)",
    )
    publish.add_argument(
        "--verify-read-budget-bytes", type=int, default=256 * 1024 * 1024,
        help="Total strict verification byte budget per invocation (default: 268435456; positive)",
    )
    publish.add_argument(
        "--verify-timeout-seconds", type=float, default=30.0,
        help="Deadline for each strict bundle verification worker (default: 30; excludes writes)",
    )
    publish.add_argument(
        "--pending", action="store_true",
        help="Skip complete published bundles and continue to unpublished or damaged parts",
    )
    publish.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    proofread = subparsers.add_parser(
        "proofread",
        help="Build the side-by-side ASR/字幕 table for a stored part (no adjudication)",
        description=(
            "Read one part's two machine routes — the archived ASR raw sidecar and "
            "the archived AI/CC subtitles (read through the transcript store) — and "
            "write the machine-pre-aligned side-by-side table plus the alignment "
            "jsonl under <artifact-root>/.tmp/proofread-work/. Blocks come from ASR "
            "VAD segments only; the table aligns, it never adjudicates. Guard A "
            "(coverage) aborts non-zero naming the block when a count fails."
        ),
    )
    proofread.add_argument(
        "--bvid", required=True,
        help="Bvid, or bvid:pN for one part, already in the archive database",
    )
    proofread.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    proofread.add_argument(
        "--asr-root", default=None,
        help=(
            "Root holding the ASR raw sidecar "
            "(transcripts/<bvid>.p<N>/bundle.raw.json); default: the artifact root. "
            "Use it when the two routes live on different roots"
        ),
    )
    proofread.add_argument(
        "--caption-root", default=None,
        help=(
            "Root holding archive.db, which the AI/CC caption route is read from; "
            "default: the archive root. Use it when the two routes live on different roots"
        ),
    )

    proofread_merge = subparsers.add_parser(
        "proofread-merge",
        help="Merge a completed side-by-side定稿 into the final transcript artifact",
        description=(
            "Read the completed side-by-side copy (the .sidebyside.md the operator "
            "marked with per-block '>> keep|use-asr|use-sub|custom: <text>' decisions) "
            "and write the final .proofread transcript families (srt/txt/raw) under "
            "the artifact root, plus the corrections accounting next to the "
            "alignment jsonl. Every unmarked block defaults to keep."
        ),
    )
    proofread_merge.add_argument(
        "--bvid", required=True,
        help="Bvid, or bvid:pN for one part, already in the archive database",
    )
    proofread_merge.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    run_cmd = subparsers.add_parser(
        "run",
        help="Coordinate manifest rows through stages (complements pilot)",
    )
    run_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
             "(comma- or space-separated)",
    )
    _add_asr_policy(run_cmd)
    run_cmd.add_argument(
        "--offline",
        action="store_true",
        help="Never call harvest/download (deterministic local stages only)",
    )
    run_cmd.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N rows (bounded batches)",
    )
    run_cmd.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help=_MAX_AUDIO_GB_HELP,
    )
    run_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    run_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )
    run_cmd.add_argument(
        "--queue-source",
        choices=("store", "manifest"),
        default="store",
        help="Where to read the queue scopes (pending/failed): archive.db gap "
             "views (default) or the manifest (deprecated rollback)",
    )

    schedule_cmd = subparsers.add_parser(
        "schedule",
        help="Process a bounded sequential batch of the visible corpus",
    )
    schedule_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
             "(comma- or space-separated)",
    )
    _add_asr_policy(schedule_cmd)
    schedule_cmd.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Process at most N matching rows (required explicit bound)",
    )
    schedule_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume only a matching risk-interrupted scheduler sidecar",
    )
    schedule_cmd.add_argument(
        "--max-audio-gb", type=float, default=10.0,
        help=_MAX_AUDIO_GB_HELP_SCHEDULE,
    )
    schedule_cmd.add_argument(
        "--allow-long-live",
        action="store_true",
        help=(
            "Opt in to multi-hour rows under the configured --max-audio-gb "
            "(cannot be 0). Default pending/failed selection keeps the "
            "45-minute short-video policy"
        ),
    )
    schedule_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    schedule_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )
    schedule_cmd.add_argument(
        "--queue-source",
        choices=("store", "manifest"),
        default="store",
        help="Where to read pending/failed queues: archive.db gap views "
             "(default) or the manifest (deprecated rollback)",
    )

    campaign_cmd = subparsers.add_parser(
        "campaign",
        help="Run a bounded campaign batch with aggregate checkpoint evidence",
    )
    campaign_cmd.add_argument(
        "--scope",
        required=True,
        help="pending | failed | one or more work_id/bvid selectors "
        "(comma- or space-separated)",
    )
    _add_asr_policy(campaign_cmd)
    campaign_cmd.add_argument(
        "--limit",
        type=int,
        required=True,
        help="Process at most N matching rows (required explicit bound)",
    )
    campaign_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume only a matching risk-interrupted scheduler sidecar",
    )
    campaign_cmd.add_argument(
        "--offline",
        action="store_true",
        help="Never call harvest/download (deterministic local stages only)",
    )
    campaign_cmd.add_argument(
        "--max-audio-gb",
        type=float,
        default=10.0,
        help=_MAX_AUDIO_GB_HELP,
    )
    campaign_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )
    campaign_cmd.add_argument(
        "--sessdata", default=None,
        help="SESSDATA cookie for live stages (or env BILI_SESSDATA); not stored",
    )

    search_cmd = subparsers.add_parser(
        "search",
        help="Search indexed completed transcripts using SQLite FTS5",
    )
    search_cmd.add_argument("query", help="Search query string")
    search_cmd.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N results (default: all)",
    )
    search_cmd.add_argument(
        "--rebuild", action="store_true",
        help="Force rebuilding the search index from the manifest",
    )
    search_cmd.add_argument(
        "--status", action="append", default=None,
        help="Filter by manifest status (repeatable or comma-separated)",
    )
    search_cmd.add_argument(
        "--source", action="append", default=None,
        help="Filter by source (e.g. subtitle, asr)",
    )
    search_cmd.add_argument(
        "--language", action="append", default=None,
        help="Filter by language (e.g. ai-zh, zh-CN)",
    )
    search_cmd.add_argument(
        "--scope", default=None,
        help="pending | failed | one or more work_id/bvid selectors",
    )
    search_cmd.add_argument(
        "--work-id", action="append", default=None,
        help="Filter by exact work_id or bvid (repeatable or comma-separated)",
    )
    search_cmd.add_argument(
        "--from", dest="pubdate_from", default=None, metavar="YYYY-MM-DD",
        help="Only blocks whose video's pubdate is on/after this date",
    )
    search_cmd.add_argument(
        "--to", dest="pubdate_to", default=None, metavar="YYYY-MM-DD",
        help="Only blocks whose video's pubdate is before this date",
    )
    search_cmd.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="Output format (default: table)",
    )
    search_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    search_index_cmd = subparsers.add_parser(
        "search-index",
        help="Build or top up the store-backed FTS5 transcript index in archive.db",
    )
    search_index_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    coverage_cmd = subparsers.add_parser(
        "coverage", help="Print deterministic read-only coverage telemetry"
    )
    coverage_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    coverage_cmd.add_argument("--scope", default=None)
    coverage_cmd.add_argument("--format", choices=["json", "csv"], default="json")
    coverage_cmd.add_argument(
        "--trusted-local", action="store_true",
        help="Trust an operator-owned local archive root for unbounded inspection",
    )
    coverage_cmd.add_argument(
        "--quality",
        action="store_true",
        help="Include deterministic artifact quality validation signals",
    )
    coverage_cmd.add_argument(
        "--reference",
        default=None,
        help=(
            "Second transcript of the same audio (SRT/TXT/JSON); needs --quality "
            "and exactly one selected row. .srt/.txt are read as plain text; a "
            "cue-less or unparsable .json is refused"
        ),
    )

    coverage_cmd.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Restore the pre-cutover exit behavior: any finding, either "
            "class, exits non-zero. Applies to the plain projection and to "
            "--quality"
        ),
    )

    integrity_cmd = subparsers.add_parser(
        "verify", help="Verify archive integrity without modifying files"
    )
    integrity_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    integrity_cmd.add_argument("--scope", default=None)
    integrity_cmd.add_argument(
        "--trusted-local", action="store_true",
        help="Trust an operator-owned local archive root for unbounded inspection",
    )
    integrity_cmd.add_argument("--format", choices=["json", "text"], default="json")
    integrity_cmd.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Restore the pre-cutover exit behavior: any finding, either "
            "class, exits non-zero"
        ),
    )

    recover_cmd = subparsers.add_parser(
        "recover", help="Explicitly audit named integrity defects (no requeue execution)"
    )
    recover_cmd.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    recover_cmd.add_argument("--work-id", action="append", default=None,
                             help="Exact work_id selector (repeatable; required for bounded recovery)")
    recover_cmd.add_argument("--defect-code", action="append", default=None,
                             help="Defect class selector (repeatable; bounded to reported defects)")
    recover_cmd.add_argument(
        "--limit", type=int, default=100,
        help="Limit must be positive; values above the maximum are capped at 100",
    )

    evaluate_concurrency = subparsers.add_parser(
        "evaluate-concurrency",
        help="Evaluate evidence only; runtime remains sequential with no daemon",
    )
    evaluate_concurrency.add_argument(
        "--evidence", required=True, help="Path to the JSON evidence mapping"
    )
    evaluate_concurrency.add_argument(
        "--thresholds", required=True, help="Path to the explicit JSON threshold mapping"
    )

    export_cmd = subparsers.add_parser(
        "export",
        help="Export manifest metadata to JSON or CSV format",
    )
    export_cmd.add_argument(
        "--format",
        choices=["json", "csv"],
        required=True,
        help="Export format (json or csv)",
    )
    export_cmd.add_argument(
        "--out",
        default=None,
        help="Output file path (default: stdout)",
    )
    export_cmd.add_argument(
        "--status",
        action="append",
        default=None,
        help="Filter by manifest status (repeatable or comma-separated)",
    )
    export_cmd.add_argument(
        "--with-text",
        action="store_true",
        help="Include transcript text body in output",
    )
    export_cmd.add_argument(
        "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
        help="Archive root directory (default: ./archive)",
    )

    # The GPU/ROCm environment self-check.  This subcommand is the CLI form the
    # README and spec 01 D1.2 already document — it had no implementation, so
    # every published invocation answered "invalid choice: 'check-asr-env'"
    # while the check itself lived only in `scripts/check_asr_env.py`.
    #
    # It takes no arguments and writes nothing: it inspects the host (device
    # node, loader path, torch build, HSA runtime, a device probe) and exits
    # `0` iff all five stages hold, `1` when any fails, `2` for a usage error —
    # the same contract the script implements.
    subparsers.add_parser(
        "check-asr-env",
        help="Verify this host can run local ASR (GPU/ROCm recipe self-check)",
    )

    from bili_asr.cli.registry import add_policy_arguments

    add_policy_arguments(subparsers)
    return parser
