"""Opt-in bounded live smoke: one real part through the shipped subtitle CLI.

This module holds the only networked test of the ``probe-subs`` /
``harvest-subs`` pair — the operator-visible CLI + storage chain.  It drives the
real user-facing command path (``bili_asr.cli.main`` with plain argv, the real
``BilibiliApiGateway`` adapter over the pinned ``bilibili-api-python``
distribution, and the real SQLite transcript repository) for exactly one public
part inside a temporary archive root.  No playback, download, audio, or ASR code
is invoked, and nothing outside the temporary root is written.

The part the smoke probes is authored into its own temporary root, because both
commands address parts the archive already stores: ``harvest-subs`` never
fetches a pagelist and never calls upstream for a part that is not in the
database, so a live run needs a ``video_parts`` row before it can do anything.
The seeded identity is the fixed public sample (:data:`SAMPLE_BVID` /
:data:`SAMPLE_CID` / :data:`SAMPLE_PAGE_INDEX`) — one part of the archive
owner's own public collection, fetched live by the gateway plan's probe
(``tests/test_live_subtitle_smoke.py``) and therefore already known to expose a
visible machine caption on this endpoint.  Only the identity is real and it is
used verbatim; the surrounding rows the storage layer requires (user, video,
part title and duration) are inert scaffolding that no subtitle code path reads.
The evidence line names the seeded part and its ``part_source=fixed-sample``
provenance, so the operator can always see which part answered.

The two commands run in order, and each costs one bounded live surface: the
probe one track listing, the harvest one listing plus one document fetch when a
track is visible.  Default pytest runs skip the smoke; it executes only when the
operator sets ``BILI_LIVE_SMOKE=1``.  An opted-in run without the pinned
distribution fails loudly.  Its documented bounded outcomes are:

- **stored** — the part exposes a track and the harvest stores version 1: the
  smoke asserts the normalized ``transcripts``/``transcript_segments`` rows, the
  run and attempt evidence, that the part left the pending enumeration, that the
  credential presence the run row records matches the environment, and that
  nothing but ``archive.db`` and the writer lock appeared under the root.  This
  is the acceptance-carrying outcome;
- **no subtitle visible now** (``tracks=0``, then ``no-subtitle`` with exit 0) —
  a legitimate bounded observation, recorded with the printed counts and never
  as "this video has no captions".  The run stored nothing, so it skips instead
  of reading green;
- **the listing answers the bounded ``not_found`` code** — the part is one
  upstream no longer serves, or one the credential in effect cannot see.  The
  probe prints ``failed not_found`` (an all-failed probe exits 2) because it
  obtained no listing at all, while a harvest records the same answer as
  ``no-subtitle`` and exits 0: both readings are the shipped contract.  The
  smoke records the reading the probe produced and does not spend the harvest's
  calls on a part whose listing nothing answered;
- **upstream risk control refuses the locked call shape** (``rate_limited``) —
  the plan's recorded bounded blocker, reported as a skip carrying the bounded
  code, because the locked shape must not be bent to make the call pass;
- **every other bounded code** — ``transport_error`` from a dead proxy,
  ``response_error``, ``shape_error``, anything unrecognized — fails loudly,
  because those mean the environment or the adapter regressed rather than
  upstream refusing the call.

Every branch of that ladder is rehearsed offline in this module — the seeding
and its read-only sanity check, both output readers, the row assertions, and
the bounded-code refusal ladder — so a default (offline, non-opted-in) run
exercises the whole control flow; only the live calls themselves are live.  The
smoke adds no retry of its own: the shipped gateway is fail-fast per call, so a
throttled endpoint is answered by waiting and re-running the command, never by
bending the call shape or adding retries.

Run it with::

    CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
    CHECKOUT=$CONTROL/bilibili-asr-archive         # or a feature worktree's package dir
    cd "$CHECKOUT"
    set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
    export BILI_HTTP_PROXY=http://127.0.0.1:7890    # proxied host
    BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \\
      -m pytest tests/test_live_subtitle_cli_smoke.py -s -v
"""

from __future__ import annotations

import importlib.metadata
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, NoReturn

import pytest

from bili_asr.cli import main
from bili_asr.config import (
    ARCHIVE_DATABASE_NAME,
    SESSDATA_ENV_VAR,
    redact_sessdata,
    resolve_sessdata,
)
from bili_asr.services.subtitle_ingest import ProbeResult, SubtitleIngestor
from bili_asr.sources.models import (
    GatewayNotFound,
    GatewayRateLimited,
    SubtitleSegment,
    SubtitleTrack,
)
from bili_asr.storage import MetadataRepository, open_database
from bili_asr.storage.models import (
    ALLOWED_ACQUISITION_KINDS,
    ALLOWED_CAPTION_SOURCE_KINDS,
)
from fixtures.fake_bilibili_gateway import (
    SESSDATA_BOUNDARY_VALUE,
    SIGNED_SUBTITLE_URL_MARKER,
    FakeGateway,
    assert_leaks_no_markers,
    fake_gateway_seam,
    persisted_row_text,
)
from fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)

PINNED_PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
PINNED_PACKAGE_VERSION = "17.4.2"

#: The opt-in switch, shared with the metadata and gateway smokes: the smoke
#: runs only when the operator sets it to ``1``.
LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"

#: The fixed public sample the smoke authors into its temporary root: one part
#: of the archive owner's own public collection, fetched live by the gateway
#: plan's probe (2026-09-11; first part of the first video of UID 23191782,
#: ``ai-zh`` with 2913 segments).  A sample upstream has since removed surfaces
#: as the bounded ``not_found`` answer and is replaceable in one line.
SAMPLE_BVID = "BV1S8hA6MEvy"
SAMPLE_CID = 41314223900
SAMPLE_PAGE_INDEX = 0

#: The ``bvid:pN`` identity both commands address, and the provenance token the
#: evidence line records: the seeded part came from the fixed public sample, not
#: from an operator archive.
SAMPLE_WORK_ID = f"{SAMPLE_BVID}:p{SAMPLE_PAGE_INDEX}"
PART_SOURCE = "fixed-sample"

#: The one bound both commands run under: a single part, so the probe and the
#: harvest cannot walk a backlog and the whole live surface stays countable.
PART_LIMIT = 1

#: The one file besides ``archive.db`` a harvest is expected to leave behind:
#: ``harvest-subs`` is an archive-writer command, so it takes the shipped writer
#: lock at :data:`ARCHIVE_WRITER_LOCK_PATH`.  ``probe-subs`` is deliberately not
#: one and leaves nothing.
ARCHIVE_WRITER_LOCK_PATH = os.path.join("coordinator", "archive-writer.lock")

#: The bounded codes that are recorded as blocker evidence rather than failing
#: the smoke.  ``rate_limited`` is an upstream refusal of the locked call shape;
#: ``not_found`` is the bounded "nothing was visible for this part" answer the
#: two commands deliberately read differently (the probe prints ``failed`` and
#: can exit 2, the harvest records ``no-subtitle`` and exits 0).  The set is
#: pinned from the documentation side by
#: :func:`test_the_documented_bounded_codes_are_recorded`.
RECORDED_BLOCKER_CODES = frozenset({"rate_limited", "not_found"})

#: The legacy sidecars this path must never write.  The transcript projections
#: (``subtitles/raw/``, ``transcripts/srt/``) need no separate assertion: the
#: "nothing but the database and the lock" check fails on any extra file.
LEGACY_SIDECAR_PATHS = (
    os.path.join("manifest", "manifest.jsonl"),
    "meta-cursor.json",
    "run-ledger.jsonl",
    "coordinator/attempts.jsonl",
)

#: The locked output shapes of section 2 of the CLI spec, as the readers below
#: parse them.  A shape the implementation no longer prints fails here rather
#: than passing unnoticed.
_PROBE_TRACKS_LINE = re.compile(r"probe (?P<work_id>\S+) tracks=(?P<count>\d+)")
_PROBE_FAILED_LINE = re.compile(r"probe (?P<work_id>\S+) failed (?P<code>\S+)")
_PROBE_TRACK_LINE = re.compile(
    r" {2}track (?P<language>\S+) (?P<kind>ai|cc) (?P<label>.*)"
)
_PROBE_ZERO_TRACK_MARKER = "  (no subtitles visible)"
_PROBE_SUMMARY_LINE = re.compile(
    r"probe-subs: probed=(?P<probed>\d+) with_tracks=(?P<with_tracks>\d+)"
    r" without_tracks=(?P<without_tracks>\d+) failed=(?P<failed>\d+)"
)
_HARVEST_STORED_LINE = re.compile(
    r"harvest (?P<work_id>\S+) (?P<outcome>stored|unchanged)"
    r" (?P<source_kind>\S+) (?P<language>\S+) v(?P<version>\d+)"
)
_HARVEST_NO_SUBTITLE_LINE = re.compile(r"harvest (?P<work_id>\S+) no-subtitle")
_HARVEST_FAILED_LINE = re.compile(r"harvest (?P<work_id>\S+) failed (?P<code>\S+)")
_HARVEST_SUMMARY_LINE = re.compile(
    r"harvest-subs: run_id=(?P<run_id>\S+) attempted=(?P<attempted>\d+)"
    r" stored=(?P<stored>\d+) unchanged=(?P<unchanged>\d+)"
    r" no-subtitle=(?P<no_subtitle>\d+) failed=(?P<failed>\d+)"
    r" remaining_without_transcript=(?P<remaining>\d+)"
)


def _live_smoke_requested() -> bool:
    """True only when the operator explicitly opts in via the environment."""

    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"


#: The default-run skip text; the central gate (conftest ``opt_in_gate``) reuses
#: it byte-identically, and the rehearsal below pins the literal.
_LIVE_SMOKE_SKIP_REASON = (
    f"live subtitle CLI smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to request it"
)


def _pinned_package_version() -> str:
    """Return the installed distribution version, or fail loudly.

    Loud-fail guard (the metadata smoke's precedent): an opted-in smoke in an
    environment without the pinned distribution fails loudly with install
    guidance instead of silently skipping.
    """

    try:
        return importlib.metadata.version(PINNED_PACKAGE_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError as error:
        pytest.fail(
            "live subtitle CLI smoke was requested but"
            f" {PINNED_PACKAGE_DISTRIBUTION_NAME} is not installed in this"
            f" environment ({error}); install the pinned"
            f" {PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION}"
            " (uv sync) first"
        )


def _credential_expectation() -> bool:
    """Whether a credential is in effect for this run, by the shipped rule.

    The smoke builds its own argv and passes no ``--sessdata`` flag, so the
    environment variable is its only credential input — resolved through the
    shipped helper, so a blank value means anonymous here exactly as it does in
    the command.  Only presence is ever returned.
    """

    return resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR)) is not None


def _require_live_credential() -> None:
    """Fail loudly when an opted-in smoke has no resolvable credential.

    Reached only after the opt-in gate, so a default pytest run still skips
    without a credential.  Once the operator has asked for a live run, a
    forgotten credential must not read as a benign skip: the smoke derives its
    own expectation from the same environment the command reads, so an
    anonymous run answers ``sessdata=absent`` with no visible tracks and would
    report "nothing visible now" — indistinguishable from a login-gated caption
    and from a part that simply has none.  Failing here costs no upstream call.
    """

    if _credential_expectation():
        return
    pytest.fail(
        "the live subtitle CLI smoke was requested but no credential resolves:"
        f" {SESSDATA_ENV_VAR} is unset or blank.  Source the control checkout's"
        " gitignored .env (set -a; source .env; set +a) or export"
        f" {SESSDATA_ENV_VAR}, then re-run — an anonymous run cannot tell a"
        " login-gated caption from a part that has none, so a forgotten"
        " credential must not read as a benign skip"
    )


def _live_preconditions() -> None:
    """Apply the smoke's three preconditions, in their documented order.

    Opt in first, so a default pytest run skips without needing a credential or
    the pinned distribution; then the pin, which fails loudly rather than
    skipping; then the credential, which fails loudly for the same reason
    (:func:`_require_live_credential`).  Extracted so the order itself is
    rehearsable offline, instead of resting on a live run.
    """

    if not _live_smoke_requested():
        pytest.skip(_LIVE_SMOKE_SKIP_REASON)
    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
    _require_live_credential()


def _probe_argv(tmp_root: str) -> list[str]:
    """The bounded ``probe-subs`` invocation: one part by the enumeration bound."""

    return [
        "probe-subs",
        "--limit-parts",
        str(PART_LIMIT),
        "--archive-root",
        tmp_root,
    ]


def _harvest_argv(tmp_root: str) -> list[str]:
    """The bounded ``harvest-subs`` invocation: the same one-part selection."""

    return [
        "harvest-subs",
        "--limit-parts",
        str(PART_LIMIT),
        "--archive-root",
        tmp_root,
    ]


def _seed_probe_part(tmp_root: str) -> None:
    """Author the one sample part into a fresh temporary archive root.

    The two commands read their parts from ``video_parts`` and never fetch a
    pagelist, so this is the smallest root a live subtitle run can be expressed
    against: one user, the sample's video, and the one sample part, pending
    (``metadata_collected``, no transcript).  The rows are written through the
    shipped repository, so the seeded database is the schema the commands open —
    not a hand-built one.
    """

    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        with repository.transaction():
            repository.upsert_user(make_user_record())
            repository.upsert_video(
                make_video_record(SAMPLE_BVID, aid=None, title="字幕冒烟样本")
            )
            repository.upsert_part(
                make_part_record(
                    SAMPLE_BVID,
                    page_index=SAMPLE_PAGE_INDEX,
                    cid=SAMPLE_CID,
                    processing_status="metadata_collected",
                )
            )
    finally:
        connection.close()


@dataclass(frozen=True, slots=True)
class ProbeOutput:
    """The bounded facts one ``probe-subs`` run prints for its single part."""

    work_id: str
    track_count: int | None
    error_code: str | None
    tracks: tuple[tuple[str, str], ...]
    probed: int
    with_tracks: int
    without_tracks: int
    failed: int


@dataclass(frozen=True, slots=True)
class HarvestOutput:
    """The bounded facts one ``harvest-subs`` run prints for its single part."""

    run_id: str
    work_id: str
    outcome: str
    error_code: str | None
    source_kind: str | None
    language: str | None
    version: int | None
    attempted: int
    stored: int
    unchanged: int
    no_subtitle: int
    failed: int
    remaining_without_transcript: int


def _credential_label(expect_credential_present: bool) -> str:
    """The presence token the command prints, from the shipped redaction helper."""

    return redact_sessdata("present" if expect_credential_present else None)


def _assert_credential_line(out: str, *, expect_credential_present: bool) -> list[str]:
    """Assert the presence-only first line and return the remaining lines."""

    lines = out.splitlines()
    assert lines, "the command printed nothing"
    assert lines[0] == f"sessdata: {_credential_label(expect_credential_present)}", (
        lines[0]
    )
    return lines[1:]


def _read_probe_output(out: str, *, expect_credential_present: bool) -> ProbeOutput:
    """Assert the locked ``probe-subs`` shapes and read their bounded facts."""

    body = _assert_credential_line(
        out, expect_credential_present=expect_credential_present
    )
    assert body, "the probe printed no part line"
    summary = _PROBE_SUMMARY_LINE.fullmatch(body[-1])
    assert summary is not None, f"unexpected probe summary line: {body[-1]!r}"
    assert int(summary["probed"]) == 1, "the smoke bounds the probe to one part"

    part_lines = body[:-1]
    failed_line = _PROBE_FAILED_LINE.fullmatch(part_lines[0])
    if failed_line is not None:
        assert len(part_lines) == 1, (
            "a failed listing carries no track lines and no success marker"
        )
        work_id: str = failed_line["work_id"]
        error_code: str | None = failed_line["code"]
        track_count: int | None = None
        tracks: tuple[tuple[str, str], ...] = ()
    else:
        tracks_line = _PROBE_TRACKS_LINE.fullmatch(part_lines[0])
        assert tracks_line is not None, f"unexpected probe line: {part_lines[0]!r}"
        work_id = tracks_line["work_id"]
        error_code = None
        track_count = int(tracks_line["count"])
        track_lines = part_lines[1:]
        if track_count == 0:
            assert track_lines == [_PROBE_ZERO_TRACK_MARKER], (
                "a zero-track part is printed with its explicit marker"
            )
            tracks = ()
        else:
            matches = [_PROBE_TRACK_LINE.fullmatch(line) for line in track_lines]
            assert all(match is not None for match in matches), (
                f"unexpected track line: {track_lines!r}"
            )
            assert len(matches) == track_count, "one track line per visible track"
            tracks = tuple(
                (match["language"], match["kind"]) for match in matches
            )

    assert work_id == SAMPLE_WORK_ID, (
        f"the probe addressed {work_id!r}, not the part the smoke authored"
    )
    probed = int(summary["probed"])
    with_tracks = int(summary["with_tracks"])
    without_tracks = int(summary["without_tracks"])
    failed = int(summary["failed"])
    # The summary's counts are tied to the part line they summarize, so the
    # evidence line's ``with_tracks`` is derived from the probe's own output
    # rather than re-emitted on trust (QC2-009/Q3-03).
    assert with_tracks == (1 if track_count else 0), (
        "with_tracks counts the parts that listed a track"
    )
    assert without_tracks == (1 if track_count == 0 else 0), (
        "without_tracks counts the parts that listed no track"
    )
    assert failed == (1 if error_code is not None else 0), (
        "failed counts the parts whose listing failed"
    )
    assert probed == with_tracks + without_tracks + failed, (
        "the three brackets partition the probed parts"
    )
    return ProbeOutput(
        work_id=work_id,
        track_count=track_count,
        error_code=error_code,
        tracks=tracks,
        probed=probed,
        with_tracks=with_tracks,
        without_tracks=without_tracks,
        failed=failed,
    )


def _read_harvest_output(
    out: str, *, expect_credential_present: bool
) -> HarvestOutput:
    """Assert the locked ``harvest-subs`` shapes and read their bounded facts."""

    body = _assert_credential_line(
        out, expect_credential_present=expect_credential_present
    )
    assert len(body) == 2, (
        "the one-part run prints one part line and one summary line"
    )
    part_line, summary_line = body
    summary = _HARVEST_SUMMARY_LINE.fullmatch(summary_line)
    assert summary is not None, f"unexpected harvest summary line: {summary_line!r}"
    assert int(summary["attempted"]) == 1, "the smoke bounds the harvest to one part"

    stored_line = _HARVEST_STORED_LINE.fullmatch(part_line)
    no_subtitle_line = _HARVEST_NO_SUBTITLE_LINE.fullmatch(part_line)
    failed_line = _HARVEST_FAILED_LINE.fullmatch(part_line)
    matches = [
        match
        for match in (stored_line, no_subtitle_line, failed_line)
        if match is not None
    ]
    assert len(matches) == 1, f"unexpected harvest part line: {part_line!r}"
    match = matches[0]
    groups = match.groupdict()

    if stored_line is not None:
        outcome: str = groups["outcome"]
    elif no_subtitle_line is not None:
        outcome = "no-subtitle"
    else:
        outcome = "failed"
    assert groups["work_id"] == SAMPLE_WORK_ID, (
        f"the harvest addressed {groups['work_id']!r}, not the part the smoke seeded"
    )

    attempted = int(summary["attempted"])
    stored = int(summary["stored"])
    unchanged = int(summary["unchanged"])
    no_subtitle = int(summary["no_subtitle"])
    failed = int(summary["failed"])
    # The four outcome counts are tied to the one part line above them: exactly
    # one of them is 1 and they partition the single attempt, so the evidence
    # line's ``stored`` is derived from the harvest's own output instead of
    # being re-emitted on trust (QC2-009/Q3-03).
    expected_counts = {
        "stored": (1, 0, 0, 0),
        "unchanged": (0, 1, 0, 0),
        "no-subtitle": (0, 0, 1, 0),
        "failed": (0, 0, 0, 1),
    }[outcome]
    assert (stored, unchanged, no_subtitle, failed) == expected_counts, (
        f"the part line's outcome {outcome!r} disagrees with its counts"
    )
    assert stored + unchanged + no_subtitle + failed == attempted, (
        "the four outcome counts partition the attempted parts"
    )
    assert summary["run_id"], "the summary line names the persisted run"

    return HarvestOutput(
        run_id=summary["run_id"],
        work_id=groups["work_id"],
        outcome=outcome,
        error_code=groups.get("code"),
        source_kind=groups.get("source_kind"),
        language=groups.get("language"),
        version=(
            int(groups["version"]) if groups.get("version") is not None else None
        ),
        attempted=attempted,
        stored=stored,
        unchanged=unchanged,
        no_subtitle=no_subtitle,
        failed=failed,
        remaining_without_transcript=int(summary["remaining"]),
    )


@contextmanager
def _archive_connection(tmp_root: str) -> Iterator[sqlite3.Connection]:
    """Read the archive database directly, without creating or migrating it."""

    connection = sqlite3.connect(os.path.join(tmp_root, ARCHIVE_DATABASE_NAME))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _archive_files(tmp_root: str) -> list[str]:
    """Every file below the archive root, as sorted relative POSIX paths."""

    return sorted(
        os.path.relpath(os.path.join(directory, name), tmp_root).replace(
            os.sep, "/"
        )
        for directory, _directories, names in os.walk(tmp_root)
        for name in names
    )


def _assert_one_pending_part(connection: sqlite3.Connection) -> None:
    """Assert the temporary root offers exactly the seeded part, pending.

    Read-only, and checked before the harvest: the pending enumeration is what
    ``--limit-parts 1`` selects from, so this is the check that the run about to
    happen is the one the smoke means to make.
    """

    rows = list(
        connection.execute("SELECT work_id, cid, attempted FROM v_pending_subtitles")
    )
    assert len(rows) == 1, (
        f"the temporary root must offer exactly one pending part, got {len(rows)}"
    )
    row = rows[0]
    assert (row["work_id"], row["cid"], row["attempted"]) == (
        SAMPLE_WORK_ID,
        SAMPLE_CID,
        0,
    ), "the pending part is the seeded sample, never attempted"


def _assert_stored_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    expect_credential_present: bool,
) -> str:
    """Assert one bounded harvest stored one transcript version; render evidence.

    Every fact asserted here is one the CLI contract promises about a storing
    run: the normalized transcript row with an allowed caption source kind and
    its language and version, its ordered segments, the one run row carrying the
    operator's selector and the credential presence, the one attempt row
    pointing at the stored transcript, and a part that left the pending
    enumeration.  ``run_id`` is the id the command printed on its summary line,
    and it is asserted against the persisted row — the evidence line's
    ``run_id`` is therefore tied to its source (QC2-009/Q3-03).  The returned
    line carries counts only: no segment text, no upstream value, no credential.
    """

    transcripts = list(
        connection.execute(
            "SELECT t.transcript_id, t.source_kind, t.language, t.version,"
            " t.content_sha256, t.model_id, vp.cid FROM transcripts AS t"
            " JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id"
            " ORDER BY t.version"
        )
    )
    assert len(transcripts) == 1, "one bounded part stores exactly one version"
    transcript = transcripts[0]
    assert transcript["cid"] == SAMPLE_CID
    assert transcript["source_kind"] in ALLOWED_CAPTION_SOURCE_KINDS, (
        f"unexpected source kind {transcript['source_kind']!r}"
    )
    assert transcript["language"], "a stored transcript names its language"
    assert transcript["version"] == 1, "the first acquisition stores version 1"
    assert len(transcript["content_sha256"]) == 64, "the content hash is recorded"

    segments = list(
        connection.execute(
            "SELECT s.ordinal, s.start_ms, s.end_ms, s.text"
            " FROM transcript_segments AS s WHERE s.transcript_id = ?"
            " ORDER BY s.ordinal",
            (transcript["transcript_id"],),
        )
    )
    assert segments, "a stored caption carries at least one segment"
    assert [segment["ordinal"] for segment in segments] == list(
        range(len(segments))
    ), "segments are stored in ordinal order"
    starts = [segment["start_ms"] for segment in segments]
    assert starts == sorted(starts), (
        "the stored document's start timeline is non-decreasing"
    )
    assert all(
        segment["end_ms"] > segment["start_ms"] and segment["text"].strip()
        for segment in segments
    ), "every stored segment is a non-empty interval"

    runs = list(connection.execute("SELECT * FROM acquisition_runs"))
    assert len(runs) == 1, "the bounded run opens exactly one run row"
    run = runs[0]
    assert run["run_id"] == run_id, (
        "the printed run id is the persisted run row's own id"
    )
    assert (
        run["kind"],
        run["selector_kind"],
        run["selector_target"],
        run["requested_limit"],
        run["credential_present"],
        run["outcome"],
    ) == (
        "subtitle",
        "pending",
        None,
        PART_LIMIT,
        int(expect_credential_present),
        "complete",
    ), tuple(run)
    assert run["finished_at"] is not None, "the run row is terminal"
    assert run["kind"] in ALLOWED_ACQUISITION_KINDS

    attempts = list(connection.execute("SELECT * FROM acquisition_attempts"))
    assert len(attempts) == 1, "exactly one attempt row per attempted part"
    attempt = attempts[0]
    assert (attempt["outcome"], attempt["error_code"]) == ("stored", None)
    assert attempt["transcript_id"] == transcript["transcript_id"]
    assert attempt["finished_at"] is not None
    assert attempt["run_id"] == run["run_id"]

    assert (
        connection.execute("SELECT COUNT(*) FROM v_pending_subtitles").fetchone()[0]
        == 0
    ), "a stored part leaves the pending enumeration"

    return (
        f"source_kind={transcript['source_kind']} language={transcript['language']}"
        f" version={transcript['version']} segments={len(segments)}"
        " transcripts=1 attempts=1 pending_after=0"
    )


def _assert_no_transcript_rows(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    outcome: str,
    expect_credential_present: bool,
) -> str:
    """Assert a bounded run stored nothing and still kept honest evidence.

    Both non-storing bounded outcomes land here: ``no-subtitle`` (nothing was
    visible for the part) and ``failed`` (the bounded code is what the attempt
    row carries).  The transcript tables stay empty, the one part stays in the
    pending enumeration with its timestamped attempt evidence, and the run row is
    terminal with the outcome derived from its attempts — so the run never reads
    as a success it did not have.  ``run_id`` is the id the command printed on
    its summary line, asserted against the persisted row, so the evidence line's
    ``run_id`` is tied to its source (QC2-009/Q3-03).
    """

    assert outcome in ("no-subtitle", "failed")
    assert (
        connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
    ), "a non-storing outcome writes no transcript"
    assert (
        connection.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
        == 0
    )

    attempts = list(connection.execute("SELECT * FROM acquisition_attempts"))
    assert len(attempts) == 1, "the attempt is still recorded as evidence"
    attempt = attempts[0]
    assert attempt["outcome"] == outcome
    assert attempt["finished_at"] is not None
    assert attempt["transcript_id"] is None
    if outcome == "no-subtitle":
        # Nothing visible is not a failure.  The bounded code is absent when the
        # listing simply carried no track, and it is recorded as ``not_found``
        # when upstream answered that code — the contract deliberately maps both
        # readings onto ``no-subtitle`` rather than onto ``failed``.
        assert attempt["error_code"] in (None, "not_found"), attempt["error_code"]
    else:
        assert attempt["error_code"], "a failed attempt carries its bounded code"

    runs = list(connection.execute("SELECT * FROM acquisition_runs"))
    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == run_id, (
        "the printed run id is the persisted run row's own id"
    )
    expected_run_outcome = "failed" if outcome == "failed" else "complete"
    assert (run["outcome"], run["credential_present"]) == (
        expected_run_outcome,
        int(expect_credential_present),
    ), tuple(run)
    assert run["finished_at"] is not None

    pending = list(connection.execute("SELECT work_id FROM v_pending_subtitles"))
    assert [row["work_id"] for row in pending] == [SAMPLE_WORK_ID], (
        "a part without a transcript stays eligible for a later attempt"
    )

    return f"outcome={outcome} transcripts=0 attempts=1 pending_after=1"


def _assert_bounded_blocker_is_recordable(error_code: str, *, stage: str) -> None:
    """Fail loudly unless this bounded code is a recordable bounded blocker.

    ``rate_limited`` is upstream refusing the locked call shape and ``not_found``
    is the bounded "nothing was visible for this part" answer; both are recorded
    with the part that produced them and reported as a skip.  Every other code
    means the environment or the adapter regressed — ``transport_error`` from a
    dead proxy, ``response_error``, ``shape_error`` — so it must fail the smoke
    instead of reading as an upstream refusal.
    """

    if error_code in RECORDED_BLOCKER_CODES:
        return
    pytest.fail(
        f"the live subtitle CLI smoke ended in the bounded code {error_code!r}"
        f" at stage {stage!r}, which the documentation does not enumerate as an"
        " upstream refusal; it means the environment or the adapter regressed"
        " (a dead proxy surfaces transport_error, a normalization regression"
        " shape_error), so this run must not read as a recorded blocker"
    )


def _assert_root_holds_only_the_database_and_the_lock(tmp_root: str) -> None:
    """Assert no sidecar, projection, or stray file survived the harvest.

    ``harvest-subs`` is an archive-writer command, so it leaves the writer lock
    behind; the probe is not one and creates no file at all.  Anything else — a
    legacy sidecar, a ``subtitles/raw`` or ``transcripts/srt`` projection, any
    unexpected file — fails here.
    """

    files = _archive_files(tmp_root)
    assert files == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]), (
        f"unexpected files under the archive root: {files}"
    )
    for sidecar in LEGACY_SIDECAR_PATHS:
        assert sidecar not in files


def _assert_no_credential_leak(credential: str | None, *texts: str) -> None:
    """Assert the operator's credential value appears on no surface at all.

    Deliberately an explicit ``raise`` rather than an ``assert`` on the value:
    pytest renders both operands of a failing assertion, which would print the
    very credential this check exists to keep out of every output — including
    the smoke's own failure report.
    """

    if not credential:
        return
    for text in texts:
        if credential in text:
            raise AssertionError(
                "the live subtitle CLI smoke carried the operator SESSDATA"
                " value onto a surface; the value is not printed here on purpose"
            )


def _record_and_skip(outcome: str, *, detail: str) -> NoReturn:
    """Record a bounded non-storing outcome and skip instead of reading green.

    A run that obtained no transcript is real evidence about upstream, but it is
    not the acquisition this smoke exists to carry, so it is reported as a skip
    carrying the bounded facts already printed — never as a pass.
    """

    print(f"live subtitle CLI smoke evidence: {detail}")
    pytest.skip(
        f"the live subtitle CLI smoke obtained no transcript ({outcome}):"
        f" {detail}. The bounded facts were asserted and printed above; this is"
        " a recorded bounded observation, not a defect, and not a subtitle"
        " acquisition — re-run when a caption is visible."
    )


@pytest.mark.live_smoke
def test_live_smoke_one_part_through_probe_and_harvest(
    tmp_root: str,
    capsys: pytest.CaptureFixture[str],
    opt_in_gate,
) -> None:
    """Opt-in live smoke: ONE real part through ``probe-subs`` and ``harvest-subs``.

    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The smoke authors
    the fixed sample part into a temporary archive root, probes its subtitle
    inventory through the real CLI in the locked call shape, harvests it, and
    asserts the bounded facts the contract promises: the printed presence,
    track, outcome and summary lines, the normalized transcript rows when a
    caption was visible, and the archive root's file set.  A refused or
    invisible listing is recorded as a bounded blocker; every other failure is
    loud.
    """

    # Opt in, the pinned distribution, the credential — in that order, and the
    # credential one is loud (see :func:`_live_preconditions`). The central
    # gate fixture resolves the marker's env knob (BILI_LIVE_SMOKE); the
    # precondition re-check below keeps the documented order rehearsable.
    env_var, _marker = opt_in_gate
    assert env_var == LIVE_SMOKE_ENV
    _live_preconditions()

    credential = os.environ.get(SESSDATA_ENV_VAR)
    expect_credential_present = _credential_expectation()
    presence = _credential_label(expect_credential_present)
    print(f"live subtitle CLI smoke environment: sessdata={presence}")
    _seed_probe_part(tmp_root)
    print(
        "live subtitle CLI smoke part:"
        f" part_source={PART_SOURCE} work_id={SAMPLE_WORK_ID}"
    )
    with _archive_connection(tmp_root) as connection:
        _assert_one_pending_part(connection)

    _flush_output(capsys)
    probe_exit = main(_probe_argv(tmp_root))
    probe_out, probe_err = capsys.readouterr()
    probe = _read_probe_output(
        probe_out, expect_credential_present=expect_credential_present
    )
    # The probe's stdout is the one surface that renders an upstream free-text
    # field (the track label, printed as metadata), so the sentinel scan covers
    # stdout as well as stderr here — a signed URL or a raw body arriving
    # through that field fails the smoke instead of passing unnoticed
    # (QC2-004/Q3-02).
    assert_leaks_no_markers(probe_out + probe_err, context="live probe output")
    if probe.error_code is not None:
        # Nothing answered the listing, so the harvest's calls would be spent on
        # a part no listing exists for.  The probe's own reading is recorded
        # instead — which is also the documented asymmetry: the same answer
        # harvested is ``no-subtitle`` with exit 0.
        assert probe_exit == 2, "an all-failed probe exits 2"
        _assert_bounded_blocker_is_recordable(probe.error_code, stage="probe-subs")
        _assert_no_credential_leak(credential, probe_out, probe_err)
        _record_and_skip(
            f"probe {probe.error_code}",
            detail=(
                f"part_source={PART_SOURCE} work_id={probe.work_id}"
                f" sessdata={presence} probe_exit={probe_exit}"
                f" probed={probe.probed} with_tracks={probe.with_tracks}"
                f" without_tracks={probe.without_tracks} failed={probe.failed}"
                f" error_code={probe.error_code} harvest=not_attempted"
            ),
        )
    assert probe_exit == 0, f"a probe that ran exits 0 (stderr: {probe_err!r})"

    harvest_exit = main(_harvest_argv(tmp_root))
    harvest_out, harvest_err = capsys.readouterr()
    harvest = _read_harvest_output(
        harvest_out, expect_credential_present=expect_credential_present
    )
    assert_leaks_no_markers(harvest_out + harvest_err, context="live CLI output")
    _assert_no_credential_leak(
        credential, probe_out, probe_err, harvest_out, harvest_err
    )

    with _archive_connection(tmp_root) as connection:
        persisted = persisted_row_text(connection)
        if harvest.outcome in ("stored", "unchanged"):
            assert harvest_exit == 0, harvest_err
            assert (harvest.failed, harvest.no_subtitle) == (0, 0)
            assert harvest.remaining_without_transcript == 0
            assert (harvest.stored, harvest.unchanged) == (
                (1, 0) if harvest.outcome == "stored" else (0, 1)
            ), "the one-part run's stored/unchanged counts follow its outcome"
            evidence = _assert_stored_rows(
                connection,
                run_id=harvest.run_id,
                expect_credential_present=expect_credential_present,
            )
        else:
            if harvest.outcome == "no-subtitle":
                assert harvest_exit == 0, (
                    "a run whose part had no visible caption still exits 0:"
                    f" {harvest_err!r}"
                )
            else:
                assert harvest_exit == 2, (
                    f"a run that failed on every attempted part exits 2:"
                    f" {harvest_err!r}"
                )
                _assert_bounded_blocker_is_recordable(
                    harvest.error_code or "", stage="harvest-subs"
                )
            assert harvest.remaining_without_transcript == 1
            evidence = _assert_no_transcript_rows(
                connection,
                run_id=harvest.run_id,
                outcome=harvest.outcome,
                expect_credential_present=expect_credential_present,
            )
    _assert_no_credential_leak(credential, persisted)
    _assert_root_holds_only_the_database_and_the_lock(tmp_root)

    summary = (
        f"part_source={PART_SOURCE} work_id={harvest.work_id}"
        f" sessdata={presence} probe_exit={probe_exit} probed={probe.probed}"
        f" with_tracks={probe.with_tracks} without_tracks={probe.without_tracks}"
        f" probe_failed={probe.failed} track_count={probe.track_count}"
        f" tracks={','.join(f'{lan}:{kind}' for lan, kind in probe.tracks) or 'none'}"
        f" harvest_exit={harvest_exit} run_id={harvest.run_id}"
        f" attempted={harvest.attempted} stored={harvest.stored}"
        f" unchanged={harvest.unchanged} no_subtitle={harvest.no_subtitle}"
        f" failed={harvest.failed}"
        f" remaining_without_transcript={harvest.remaining_without_transcript}"
        f" {evidence}"
    )
    if harvest.outcome not in ("stored", "unchanged"):
        _record_and_skip(harvest.outcome, detail=summary)
    print(f"live subtitle CLI smoke evidence: {summary}")


# ------------------------------------------------------------- rehearsals
#
# The rehearsals below run in every default (offline) pytest run and cover the
# smoke's own logic — the seeding, the readers, the row assertions, and the
# bounded-code refusal ladder — through the real CLI over the shared fake
# gateway seam.  A broken query or a loosened assertion therefore fails offline
# instead of first surfacing during a live run.  No live behaviour is claimed
# here, and no network call is made: the two commands run against the scripted
# protocol double.


@pytest.fixture
def anonymous_environment(monkeypatch: pytest.MonkeyPatch):
    """No credential in the environment for this rehearsal.

    Requested explicitly rather than applied autouse: an autouse fixture would
    also strip the operator's credential from the live smoke, which would then
    run anonymously and could only ever observe "nothing visible".
    """

    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)


def _flush_output(capsys: pytest.CaptureFixture[str]) -> None:
    """Drop everything captured so far, so the next read is the command's own.

    The smoke prints its bounded preamble (environment, part provenance) before
    it invokes the command; without this the readers would see those lines as
    the command's first line.
    """

    capsys.readouterr()


def _rehearsal_tracks() -> tuple[SubtitleTrack, ...]:
    """The sample's inventory shape: one visible machine caption."""

    return (
        SubtitleTrack(language="ai-zh", label="自动生成", is_ai=True, track_id="1"),
    )


def _rehearsal_body() -> tuple[SubtitleSegment, ...]:
    """One short caption document in the contract's segment shape."""

    return (
        SubtitleSegment(start_ms=0, end_ms=1_500, text="未明子"),
        SubtitleSegment(start_ms=1_500, end_ms=2_600, text="讲座"),
    )


def test_seeding_authors_exactly_the_one_pending_sample_part(tmp_root: str) -> None:
    """The temporary root the smoke builds is the one the bound selects from."""

    _seed_probe_part(tmp_root)

    with _archive_connection(tmp_root) as connection:
        _assert_one_pending_part(connection)
        assert (
            connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
        )


def test_the_live_arguments_stay_bounded_to_one_part(tmp_root: str) -> None:
    """Both commands carry the archive root and the one-part bound."""

    assert _probe_argv(tmp_root) == [
        "probe-subs",
        "--limit-parts",
        "1",
        "--archive-root",
        tmp_root,
    ]
    assert _harvest_argv(tmp_root) == [
        "harvest-subs",
        "--limit-parts",
        "1",
        "--archive-root",
        tmp_root,
    ]


def test_the_live_smoke_switch_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the documented ``1`` opts the smoke in."""

    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
    assert _live_smoke_requested() is False
    for value in ("", "0", "true", "yes", "2"):
        monkeypatch.setenv(LIVE_SMOKE_ENV, value)
        assert _live_smoke_requested() is False
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
    assert _live_smoke_requested() is True


def test_the_live_preconditions_gate_in_the_documented_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default skips; opted in without a credential fails loudly; else it runs.

    The three preconditions are the live smoke's own preamble, so driving them
    offline is what keeps the live body from resting on a single recorded run.
    The order matters twice over: the opt-in gate comes first, so a default
    pytest run skips without a credential *or* the pinned distribution; and past
    that gate a missing credential is a failure rather than a skip, because the
    smoke derives its expectation from the same environment the command reads —
    an anonymous run answers ``sessdata=absent`` with no visible tracks, which is
    exactly what a login-gated caption looks like (QC2-009/Q3-03).
    """

    # Default: not opted in, so the skip is decided before anything else — no
    # credential and no pinned distribution are needed.
    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        _live_preconditions()
    assert f"{LIVE_SMOKE_ENV}=1" in str(skipped.value)

    # Opted in, no credential: loud, and by a plain ``fail`` rather than a
    # ``skip`` — a skip here is the hazard this guard exists to remove.
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
    with pytest.raises(pytest.fail.Exception) as refused:
        _live_preconditions()
    assert SESSDATA_ENV_VAR in str(refused.value)
    assert "benign skip" in str(refused.value)

    # A blank value means anonymous by the shipped rule, so it is refused too.
    monkeypatch.setenv(SESSDATA_ENV_VAR, "")
    with pytest.raises(pytest.fail.Exception):
        _live_preconditions()

    # A resolvable credential is the only shape that gets through.
    monkeypatch.setenv(SESSDATA_ENV_VAR, SESSDATA_BOUNDARY_VALUE)
    assert _credential_expectation() is True
    assert _live_preconditions() is None


def test_the_seeded_root_survives_the_probe_with_no_new_file(
    tmp_root: str,
    anonymous_environment,
    capsys: pytest.CaptureFixture[str],
    fake_gateway_seam: FakeGateway,
) -> None:
    """A probe over a seeded root writes nothing at all: no lock, no row.

    The rehearsal also pins the reader against real command output and the
    ``part_source``/``work_id`` provenance the live evidence line records.
    """

    _seed_probe_part(tmp_root)
    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, _rehearsal_tracks())

    assert main(_probe_argv(tmp_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""

    probe = _read_probe_output(out, expect_credential_present=False)
    assert (probe.work_id, probe.track_count, probe.tracks) == (
        SAMPLE_WORK_ID,
        1,
        (("ai-zh", "ai"),),
    )
    assert (probe.probed, probe.with_tracks, probe.without_tracks, probe.failed) == (
        1,
        1,
        0,
        0,
    )
    assert fake_gateway_seam.listing_cids == [SAMPLE_CID]
    assert fake_gateway_seam.body_cids == []
    # Read-only means read-only: no writer lock, no run row, no file at all.
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
    with _archive_connection(tmp_root) as connection:
        _assert_one_pending_part(connection)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM acquisition_runs"
            ).fetchone()[0]
            == 0
        )


def test_the_probe_surface_scan_catches_a_sentinel_arriving_as_a_track_label(
    tmp_root: str,
    anonymous_environment,
    capsys: pytest.CaptureFixture[str],
    fake_gateway_seam: FakeGateway,
) -> None:
    """The probe's stdout is scanned, and the scan can really fire there.

    The track label is the one upstream free-text value this CLI prints (as
    metadata, on the documented ``track <lan> <ai|cc> <label>`` line), so the
    scan that guards every other surface has to be shown to work on this one
    rather than assumed.  The leak scripted here is the shape that field would
    produce — a signed document URL echoed as the label, which is what reading
    the wrong upstream field looks like — and the scan catches it (QC2-004).
    """

    _seed_probe_part(tmp_root)
    fake_gateway_seam.script_subtitle_tracks(
        SAMPLE_CID,
        (
            SubtitleTrack(
                language="ai-zh",
                label=SIGNED_SUBTITLE_URL_MARKER,
                is_ai=True,
                track_id="1",
            ),
        ),
    )

    assert main(_probe_argv(tmp_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""
    probe = _read_probe_output(out, expect_credential_present=False)
    assert probe.tracks == (("ai-zh", "ai"),)
    assert SIGNED_SUBTITLE_URL_MARKER in out, (
        "the label is printed as metadata, which is why it is scanned"
    )
    with pytest.raises(AssertionError):
        assert_leaks_no_markers(out + err, context="probe rehearsal output")
    # And the scan stays silent on the benign surface, so it is not a
    # formality that fires on every run:
    assert_leaks_no_markers(
        out.replace(SIGNED_SUBTITLE_URL_MARKER, "自动生成"),
        context="probe rehearsal output without the sentinel",
    )


def test_the_seam_rehearsal_stores_a_transcript_and_passes_every_row_assertion(
    tmp_root: str,
    anonymous_environment,
    capsys: pytest.CaptureFixture[str],
    fake_gateway_seam: FakeGateway,
) -> None:
    """The acceptance path is driven offline: reader, rows, and root file set.

    This is the rehearsal that keeps the live run honest: the real CLI stores a
    transcript for the seeded part over the seam, and the live smoke's own
    readers and row assertions are the ones that accept or reject it.
    """

    _seed_probe_part(tmp_root)
    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, _rehearsal_tracks())
    fake_gateway_seam.script_subtitle_segments(SAMPLE_CID, _rehearsal_body())

    assert main(_harvest_argv(tmp_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""

    harvest = _read_harvest_output(out, expect_credential_present=False)
    assert (harvest.work_id, harvest.outcome) == (SAMPLE_WORK_ID, "stored")
    assert (harvest.source_kind, harvest.language, harvest.version) == (
        "subtitle-ai",
        "ai-zh",
        1,
    )
    assert (
        harvest.attempted,
        harvest.stored,
        harvest.unchanged,
        harvest.no_subtitle,
        harvest.failed,
        harvest.remaining_without_transcript,
    ) == (1, 1, 0, 0, 0, 0)
    assert harvest.run_id, "the summary names the persisted run"

    with _archive_connection(tmp_root) as connection:
        evidence = _assert_stored_rows(
            connection,
            run_id=harvest.run_id,
            expect_credential_present=False,
        )
        persisted = persisted_row_text(connection)
    assert evidence == (
        "source_kind=subtitle-ai language=ai-zh version=1 segments=2"
        " transcripts=1 attempts=1 pending_after=0"
    )
    # Positive control: the rows the assertions accepted really carry the body,
    # so the no-leak scans are not vacuous.
    assert "未明子" in persisted
    assert_leaks_no_markers(out + err, context="rehearsal stored output")
    _assert_root_holds_only_the_database_and_the_lock(tmp_root)
    for sidecar in LEGACY_SIDECAR_PATHS:
        assert sidecar not in _archive_files(tmp_root)


def test_a_captionless_part_is_recorded_and_never_reads_green(
    tmp_root: str,
    anonymous_environment,
    capsys: pytest.CaptureFixture[str],
    fake_gateway_seam: FakeGateway,
) -> None:
    """Nothing visible is a recorded observation with exit 0, not a pass.

    The probe prints the zero-track part explicitly, the harvest records
    ``no-subtitle`` and exits 0, and the part stays pending for a later attempt —
    so the live smoke's captionless bracket is exercised end to end offline.
    """

    _seed_probe_part(tmp_root)
    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, ())

    assert main(_probe_argv(tmp_root)) == 0
    probe_out, err = capsys.readouterr()
    assert err == ""
    probe = _read_probe_output(probe_out, expect_credential_present=False)
    assert (probe.track_count, probe.tracks, probe.without_tracks) == (0, (), 1)

    assert main(_harvest_argv(tmp_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""
    harvest = _read_harvest_output(out, expect_credential_present=False)
    assert (harvest.outcome, harvest.error_code) == ("no-subtitle", None)
    assert (
        harvest.no_subtitle,
        harvest.stored,
        harvest.remaining_without_transcript,
    ) == (1, 0, 1)

    with _archive_connection(tmp_root) as connection:
        evidence = _assert_no_transcript_rows(
            connection,
            run_id=harvest.run_id,
            outcome="no-subtitle",
            expect_credential_present=False,
        )
    assert evidence == "outcome=no-subtitle transcripts=0 attempts=1 pending_after=1"
    assert_leaks_no_markers(out + err, context="rehearsal captionless output")

    with pytest.raises(pytest.skip.Exception):
        _record_and_skip("no-subtitle", detail=evidence)


def test_a_failed_harvest_is_recorded_with_its_bounded_code(
    tmp_root: str,
    anonymous_environment,
    capsys: pytest.CaptureFixture[str],
    fake_gateway_seam: FakeGateway,
) -> None:
    """The harvest's bounded-failure bracket: exit 2, code recorded, rows kept."""

    _seed_probe_part(tmp_root)
    fake_gateway_seam.script_subtitle_tracks(
        SAMPLE_CID, GatewayRateLimited(detail="get_subtitle_tracks")
    )

    assert main(_harvest_argv(tmp_root)) == 2
    out, err = capsys.readouterr()
    assert err == ""
    harvest = _read_harvest_output(out, expect_credential_present=False)
    assert (harvest.outcome, harvest.error_code, harvest.failed) == (
        "failed",
        "rate_limited",
        1,
    )
    _assert_bounded_blocker_is_recordable(harvest.error_code, stage="harvest-subs")

    with _archive_connection(tmp_root) as connection:
        evidence = _assert_no_transcript_rows(
            connection,
            run_id=harvest.run_id,
            outcome="failed",
            expect_credential_present=False,
        )
    assert evidence == "outcome=failed transcripts=0 attempts=1 pending_after=1"
    assert_leaks_no_markers(out + err, context="rehearsal failed-harvest output")


def test_a_refused_listing_is_read_from_the_probe_and_never_harvested(
    tmp_root: str,
    anonymous_environment,
    capsys: pytest.CaptureFixture[str],
    fake_gateway_seam: FakeGateway,
) -> None:
    """The bounded refusal branch: the probe's reading drives the smoke's stop.

    Upstream refusing the listing means the harvest's calls would be spent on a
    part nothing answered for, so the smoke records the probe's own bounded
    reading and issues no harvest call at all.  The all-failed probe exit is 2,
    while the same answer harvested is ``no-subtitle`` with exit 0 — the
    documented asymmetry, asserted here on both sides.
    """

    _seed_probe_part(tmp_root)
    fake_gateway_seam.script_subtitle_tracks(
        SAMPLE_CID, GatewayRateLimited(detail="get_subtitle_tracks")
    )

    assert main(_probe_argv(tmp_root)) == 2
    out, err = capsys.readouterr()
    assert err == ""
    probe = _read_probe_output(out, expect_credential_present=False)
    assert (probe.error_code, probe.track_count, probe.tracks) == (
        "rate_limited",
        None,
        (),
    )
    assert (probe.failed, probe.with_tracks, probe.without_tracks) == (1, 0, 0)
    _assert_bounded_blocker_is_recordable(probe.error_code, stage="probe-subs")
    detail = (
        f"part_source={PART_SOURCE} work_id={probe.work_id}"
        f" sessdata=absent probe_exit=2 probed={probe.probed}"
        f" with_tracks={probe.with_tracks} without_tracks={probe.without_tracks}"
        f" failed={probe.failed} error_code={probe.error_code}"
        " harvest=not_attempted"
    )
    with pytest.raises(pytest.skip.Exception) as skipped:
        _record_and_skip(f"probe {probe.error_code}", detail=detail)
    assert detail in capsys.readouterr().out
    assert "obtained no transcript" in str(skipped.value)
    # No harvest call was made: only the listing was issued, and the root still
    # holds nothing but the seeded database.
    assert fake_gateway_seam.body_cids == []
    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]

    # The other half of the documented asymmetry: the same bounded answer
    # harvested is ``no-subtitle`` with exit 0, not a failure.
    refused_root = os.path.join(tmp_root, "refused")
    os.makedirs(refused_root, exist_ok=True)
    _seed_probe_part(refused_root)
    fake_gateway_seam.script_subtitle_tracks(
        SAMPLE_CID, GatewayNotFound(detail="get_subtitle_tracks")
    )
    assert main(_harvest_argv(refused_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""
    harvested = _read_harvest_output(out, expect_credential_present=False)
    assert (harvested.outcome, harvested.error_code, harvested.no_subtitle) == (
        "no-subtitle",
        None,
        1,
    )
    with _archive_connection(refused_root) as connection:
        _assert_no_transcript_rows(
            connection,
            run_id=harvested.run_id,
            outcome="no-subtitle",
            expect_credential_present=False,
        )


@pytest.mark.parametrize("error_code", ["rate_limited", "not_found"])
def test_the_documented_bounded_codes_are_recorded(error_code: str) -> None:
    """The codes the operator documentation names are recorded, not loud.

    The parameters are the literal codes the docs enumerate, deliberately not
    derived from :data:`RECORDED_BLOCKER_CODES`: a set that drops or renames one
    of them would otherwise shrink this test instead of failing it.
    """

    _assert_bounded_blocker_is_recordable(error_code, stage="rehearsal")


@pytest.mark.parametrize(
    "error_code",
    ["transport_error", "response_error", "shape_error", "unknown_failure"],
)
def test_every_other_bounded_code_fails_loudly(error_code: str) -> None:
    """A regression code fails the smoke instead of reading as a refusal."""

    with pytest.raises(pytest.fail.Exception):
        _assert_bounded_blocker_is_recordable(error_code, stage="rehearsal")


def test_missing_pinned_distribution_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An opted-in smoke without the pin fails with guidance, not a skip."""

    def missing_distribution(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing_distribution)

    with pytest.raises(pytest.fail.Exception) as failure:
        _pinned_package_version()

    message = str(failure.value)
    assert PINNED_PACKAGE_DISTRIBUTION_NAME in message
    assert PINNED_PACKAGE_VERSION in message
    assert "uv sync" in message


def test_the_credential_expectation_follows_the_shipped_resolution_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The smoke expects presence exactly as the command resolves it."""

    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
    assert _credential_expectation() is False
    monkeypatch.setenv(SESSDATA_ENV_VAR, SESSDATA_BOUNDARY_VALUE)
    assert _credential_expectation() is True
    monkeypatch.setenv(SESSDATA_ENV_VAR, "")
    assert _credential_expectation() is False


def test_the_credential_leak_scan_is_silent_without_a_credential() -> None:
    """No credential in play means nothing to scan, and no crash."""

    _assert_no_credential_leak(None, "sessdata: absent\n")
    _assert_no_credential_leak(SESSDATA_BOUNDARY_VALUE, "sessdata: absent\n")
    with pytest.raises(AssertionError):
        _assert_no_credential_leak(
            SESSDATA_BOUNDARY_VALUE, f"sessdata: {SESSDATA_BOUNDARY_VALUE}"
        )


def test_probe_result_carries_the_credential_presence_the_cli_observed(
    tmp_root: str,
    capsys: pytest.CaptureFixture[str],
    fake_gateway_seam: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ProbeResult.credential_present`` is pinned, not only the printed line.

    The probe's printed ``sessdata:`` line is composed from the resolved
    credential, while the service records its own ``credential_present``; those
    two can drift, and the printed line alone cannot tell.  The real
    ``SubtitleIngestor.probe`` is wrapped here — the returned result object is
    the only place the service-side value is observable from the command path —
    and every captured result is asserted against both the environment and the
    line the same run printed.
    """

    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
    _seed_probe_part(tmp_root)
    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, _rehearsal_tracks())
    captured: list[ProbeResult] = []
    real_probe = SubtitleIngestor.probe

    def recording_probe(self, selection):
        result = real_probe(self, selection)
        captured.append(result)
        return result

    monkeypatch.setattr(SubtitleIngestor, "probe", recording_probe)

    assert main(_probe_argv(tmp_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[0] == "sessdata: absent"
    assert [result.credential_present for result in captured] == [False]
    assert captured[0].parts and captured[0].parts[0].work_id == SAMPLE_WORK_ID

    monkeypatch.setenv(SESSDATA_ENV_VAR, SESSDATA_BOUNDARY_VALUE)

    assert main(_probe_argv(tmp_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.splitlines()[0] == "sessdata: present"
    assert [result.credential_present for result in captured] == [False, True]
    # The value reached the adapter, and appears nowhere else.
    assert fake_gateway_seam.sessdata == SESSDATA_BOUNDARY_VALUE
    _assert_no_credential_leak(SESSDATA_BOUNDARY_VALUE, out + err)


def test_live_smoke_skip_reason_is_stable() -> None:
    """The opt-in skip text stays the byte-identical string docs quote.

    The default run's skip now comes from the central conftest gate
    (``opt_in_gate``), so this rehearsal pins the exact text the smoke has
    always skipped with: a wording drift would break operator docs and the
    reason-keyed skip tallies that read the report.
    """

    assert _LIVE_SMOKE_SKIP_REASON == (
        "live subtitle CLI smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it"
    )
