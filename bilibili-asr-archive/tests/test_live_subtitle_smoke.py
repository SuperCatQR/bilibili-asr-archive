"""Opt-in bounded live probe: ONE real part's subtitle inventory and body.

This module holds the only networked subtitle test.  It drives the real
``BilibiliApiGateway`` adapter over the pinned ``bilibili-api-python``
distribution for exactly one ``(bvid, cid)`` and records the bounded facts the
gateway contract promises: the track inventory (count, language codes, AI
versus CC) and, when a track is visible, the fetched document's segment count
and millisecond timeline.  Nothing else leaves the run: no signed URL, no
response body, no credential, and no label body is printed, and no database,
sidecar, or fixture is written.

Where the probed part comes from:

- the operator's archive database is preferred, read through a read-only
  SQLite URI (``mode=ro``): ``BILI_LIVE_ARCHIVE_DB`` when set, else
  ``archive/archive.db`` below the package directory — the root the
  ``fetch-meta`` command defaults to.  The newest part row (highest
  ``video_part_id``) is the deterministic one probed, provided the archive has
  not already marked it ``gone`` and its ``bvid`` is a BV id — two checks that
  keep a part the archive has itself written off, or a foreign row, from
  spending the probe's one live call or reaching the adapter's ``ValueError``.
  A missing, unreadable, or part-less database is not a probe failure;
- when no archived part is readable — a fresh checkout has no ``archive/``
  root at all — the probe falls back to the fixed public sample instead
  (:data:`SAMPLE_BVID` / :data:`SAMPLE_CID`): one part of the archive owner's
  own public collection, discovered once through the delivered metadata
  gateway while this probe was authored.  The fallback deliberately costs no
  metadata call at run time.  The evidence line records which source answered
  (``part_source=archive-db`` or ``part_source=fixed-sample``) together with
  the probed ``bvid``/``cid``, so a sample that upstream has since removed is
  visible rather than silent.

The probe's live surface is wider than the two calls it drives itself — one
listing and one document fetch — because the pinned package and the delivered
adapter each add to that bound:

- the listing is WBI-signed, and the pin's own request loop re-signs and
  retries it on a ``-403`` answer, up to the pin's ``wbi_retry_times`` budget
  (3 attempts by default);
- the document fetch is issued with ``wbi=False``, so the pin neither re-signs
  nor retries it: one attempt per fetch call;
- the first adapter call in a process bootstraps the pin's process-global
  ``buvid`` fingerprint whenever the credential carries none — which the
  document fetch's explicitly empty ``Credential()`` always does — costing up
  to two further requests (the SPI fingerprint endpoint and its activation
  POST), once per process;
- the delivered adapter adds at most one re-list + fetch pair per
  ``fetch_subtitle_segments`` call, and only on the expiry/transport class.

Default pytest runs skip the probe; it executes only when the operator sets
``BILI_LIVE_SMOKE=1``.  An opted-in probe fails loudly when the pinned
distribution is missing.  Its documented bounded outcomes are:

- the part exposes no track (``track_count=0``): a legitimate observation,
  recorded together with the credential presence — never "this video has no
  captions";
- the listing itself answers the bounded ``not_found`` code
  (``track_count=not_found``): the part is one upstream no longer serves, or one
  the credential in effect cannot see — this boundary deliberately collapses
  both into the one code the caller records as ``no-subtitle``.  The outcome is
  recorded with the part that produced it and the probe skips, because a run
  that obtained no listing at all must not read green; a sample upstream has
  since removed lands here;
- upstream risk control refuses the locked call shape (``rate_limited``): the
  plan's recorded bounded blocker, reported as a skip carrying the bounded code
  and the stage, because the locked shape must not be bent to make the call
  pass;
- a listed track whose body carries nothing usable (``not_found``): recorded
  with the bounded code, so a run that obtained no segment evidence never reads
  green;
- every other bounded code — ``transport_error`` from a dead proxy,
  ``response_error``, ``shape_error`` — fails loudly, because those mean the
  environment or the adapter regressed rather than upstream refusing.

Every branch of that ladder is rehearsed offline in this module — part
selection, the two loud-fail guards, both evidence renderers, and all four
record-and-skip branches — so a default (offline, non-opted-in) run exercises
the whole control flow; only the two boundary calls themselves are live.

Run it with::

    cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 \\
        .venv/bin/python -m pytest tests/test_live_subtitle_smoke.py -v -s

The probe adds no retry of its own — the single bounded re-list inside one
fetch belongs to the delivered adapter — and never reaches playback, audio,
download, or ASR code.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import pathlib
import re
import sqlite3
import sys
from typing import NoReturn

import pytest

from bili_asr.cli import DEFAULT_ARCHIVE_ROOT
from bili_asr.config import (
    ARCHIVE_DATABASE_NAME,
    SESSDATA_ENV_VAR,
    redact_sessdata,
    resolve_proxy,
    resolve_sessdata,
)
from bili_asr.sources.models import (
    BilibiliGateway,
    GatewayNotFound,
    GatewayRateLimited,
    SubtitleSegment,
    SubtitleTrack,
)
from bili_asr.storage.database import MetadataRepository, open_database
from bili_asr.storage.models import ProcessingStatus, VideoPartRecord
from fixtures.fake_bilibili_gateway import (
    BVID,
    RAW_JSON_BODY_MARKER,
    SIGNED_SUBTITLE_URL_MARKER,
    assert_leaks_no_markers,
)
from fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)

PINNED_PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
PINNED_PACKAGE_VERSION = "17.4.2"

#: The opt-in switch, shared with the metadata smoke: the probe runs only when
#: the operator sets it to ``1``.
LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"

#: The part cid the offline rehearsals seed and select.
REHEARSAL_CID = 2222

#: The part cid the offline rehearsals seed as already ``gone``.
REHEARSAL_GONE_CID = 3333

#: The BV-id shape the adapter requires before it issues a call
#: (``^BV[a-zA-Z0-9]{10}$``).  Mirrored here rather than imported from the
#: adapter, which imports the pinned distribution at module scope: this module
#: must stay importable, and its rehearsals runnable, in an environment without
#: that distribution.
BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")

#: The fixed public sample the probe probes when no archived part is readable:
#: one part of the archive owner's own collection, discovered once through the
#: delivered metadata gateway while this probe was authored (2026-09-11; first
#: page of UID 23191782, first part of the first video).  A sample upstream has
#: since removed surfaces in the evidence line as ``track_count=0`` or a
#: bounded code; replacing these two identifiers is then a one-line change.
SAMPLE_BVID = "BV1S8hA6MEvy"
SAMPLE_CID = 41314223900

#: Environment override for the operator's archive database, for a checkout
#: whose own ``archive/`` root is elsewhere (a feature worktree, for instance).
#: The database is opened read-only either way.
ARCHIVE_DATABASE_PATH_ENV_VAR = "BILI_LIVE_ARCHIVE_DB"

#: The archive database the CLI writes by default, resolved from this file so
#: the probe follows the checkout it runs in.
DEFAULT_ARCHIVE_DATABASE_PATH = str(
    pathlib.Path(__file__).resolve().parent.parent
    / DEFAULT_ARCHIVE_ROOT
    / ARCHIVE_DATABASE_NAME
)


def _live_smoke_requested() -> bool:
    """True only when the operator explicitly opts in via the environment."""

    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"


#: The default-run skip text; the central gate (conftest ``opt_in_gate``) reuses
#: it byte-identically, and the rehearsal below pins the literal.
_LIVE_SMOKE_SKIP_REASON = (
    f"live subtitle probe is opt-in: set {LIVE_SMOKE_ENV}=1 to request it"
)


def _pinned_package_version() -> str:
    """Return the installed distribution version, or fail loudly.

    Loud-fail guard (the metadata smoke's precedent): an opted-in probe in an
    environment without the pinned distribution fails loudly with install
    guidance instead of silently skipping.
    """

    try:
        return importlib.metadata.version(PINNED_PACKAGE_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError as error:
        pytest.fail(
            "live subtitle probe was requested but"
            f" {PINNED_PACKAGE_DISTRIBUTION_NAME} is not installed in this"
            f" environment ({error}); install the pinned"
            f" {PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION}"
            " (uv sync) first"
        )


def _load_gateway(sessdata: str | None):
    """Build the real adapter, failing loudly when the pin is not importable."""

    try:
        from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
    except ImportError as error:
        pytest.fail(
            "live subtitle probe was requested but the pinned package is not"
            f" importable in this environment ({error}); install"
            f" {PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION}"
            " (uv sync) first"
        )
    return BilibiliApiGateway(sessdata=sessdata)


def _read_archive_part(database_path: str) -> tuple[str, int] | None:
    """Read one part's ``(bvid, cid)`` from the archive, strictly read-only.

    The database is opened through a ``mode=ro`` SQLite URI, so the probe can
    neither create, migrate, nor write anything; the newest part row (highest
    ``video_part_id``) is the deterministic one probed, provided the archive has
    not already marked it ``gone`` — a part upstream no longer serves is exactly
    the one the player endpoint answers ``not_found`` for, and the probe has one
    live call to spend — and provided its ``bvid`` has the BV shape the adapter
    requires, so a foreign or hand-edited row cannot turn into an adapter
    ``ValueError``.  A database that does not exist, a file that is not a
    readable SQLite database, a database without a usable part row, and a row
    the adapter would reject all answer ``None`` and hand the probe to its
    documented sample fallback.
    """

    path = pathlib.Path(database_path)
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute(
            "SELECT bvid, cid FROM video_parts"
            " WHERE cid > 0 AND processing_status != 'gone'"
            " ORDER BY video_part_id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    if row is None:
        return None
    bvid, cid = row
    if not isinstance(bvid, str) or BVID_PATTERN.fullmatch(bvid) is None:
        return None
    if isinstance(cid, bool) or not isinstance(cid, int):
        return None
    return bvid, cid


def _resolve_probe_part() -> tuple[str, int, str]:
    """Resolve the one ``(bvid, cid)`` the probe runs for, and its source.

    The archived part wins when the operator's database carries one; otherwise
    the fixed public sample answers.  The third element is the bounded source
    label the evidence line records (``archive-db`` or ``fixed-sample``); the
    probed ``bvid``/``cid`` travel with it, so the record always names what was
    probed.
    """

    database_path = (
        os.environ.get(ARCHIVE_DATABASE_PATH_ENV_VAR) or DEFAULT_ARCHIVE_DATABASE_PATH
    )
    archived = _read_archive_part(database_path)
    if archived is not None:
        return archived[0], archived[1], "archive-db"
    return SAMPLE_BVID, SAMPLE_CID, "fixed-sample"


def _track_evidence(tracks: tuple[SubtitleTrack, ...]) -> str:
    """Assert the listing's shape and render its bounded, printable evidence.

    The listing must be a tuple of track DTOs — never ``None``, never a raw
    upstream mapping — and the rendered line carries the count, the language
    codes, and AI versus CC only.  Display labels are deliberately left out:
    the bounded facts this probe records do not need them, so no upstream
    string reaches the probe's output at all.
    """

    assert isinstance(tracks, tuple), "the listing must answer a tuple"
    assert all(isinstance(track, SubtitleTrack) for track in tracks), (
        "every listed track must be a SubtitleTrack DTO"
    )
    inventory = ",".join(
        f"{track.language}:{'ai' if track.is_ai else 'cc'}" for track in tracks
    )
    return f"track_count={len(tracks)} tracks={inventory or 'none'}"


def _assert_bounded_segment_facts(segments: tuple[SubtitleSegment, ...]) -> str:
    """Assert the fetched timeline and render its bounded evidence.

    What the contract guarantees per row (``end_ms > start_ms >= 0`` with
    non-empty text) is enforced by :class:`SubtitleSegment` itself and covered
    by the offline suite; what this probe adds is the document-level fact no
    offline test can see — that the real document's start timeline is
    non-decreasing, which is the order the adapter preserves verbatim.  The
    evidence line carries counts and milliseconds only.
    """

    assert segments, "a fetched document must answer at least one segment"
    starts = [segment.start_ms for segment in segments]
    assert starts == sorted(starts), (
        "the probed document's start timeline is not non-decreasing; the"
        " adapter preserves upstream order verbatim (spec section 3), so this"
        " is an observation about the upstream document and needs a recorded"
        " decision instead of a silent pass"
    )
    return (
        f"segments={len(segments)} first_start_ms={starts[0]}"
        f" last_end_ms={segments[-1].end_ms} timeline=non-decreasing"
    )


def _record_risk_control_refusal(
    refusal: GatewayRateLimited, *, stage: str, part_source: str
) -> NoReturn:
    """Record one upstream risk-control refusal and skip the live probe.

    The plan's STOP condition applies: the player endpoint refusing the locked
    call shape is escalated with this bounded evidence, never answered by
    enabling the fabricated fingerprint parameters or by adding undeclared
    parameters.  The run therefore reports a skip carrying the bounded code and
    the stage — not a pass (no call-shape evidence was obtained) and not a
    failure (the adapter did exactly what it must).
    """

    print(
        f"live subtitle probe evidence: part_source={part_source}"
        f" stage={stage} refusal_code={refusal.code}"
    )
    pytest.skip(
        "the player endpoint refused the locked call shape with the bounded"
        f" risk-control code {refusal.code!r} at stage {stage!r}: the plan's"
        " STOP condition applies, so this is a recorded bounded blocker — do"
        " not enable the fabricated dm fingerprint parameters and do not add"
        " undeclared parameters to make the call pass."
    )


def _probe_one_part(
    gateway: BilibiliGateway, bvid: str, cid: int, part_source: str
) -> None:
    """Run the probe's two boundary calls for one part and record the evidence.

    The listing is issued first, and the body only when a track is visible.  The
    evidence lines and every record-and-skip branch live here rather than inline
    in the live test so a default (offline) pytest run can drive all of them
    through a scripted gateway: a branch only a live run can enter is a branch no
    offline run has ever verified.
    """

    try:
        tracks = asyncio.run(gateway.get_subtitle_tracks(bvid, cid))
    except GatewayRateLimited as refusal:
        _record_risk_control_refusal(
            refusal, stage="track-listing", part_source=part_source
        )
    except GatewayNotFound:
        # The part is not visible upstream: an inventory nothing answered for,
        # which is what a sample upstream has since removed looks like — and
        # what the boundary reports when the credential in effect cannot see
        # the part at all (its ``-101`` signal).  Both are bounded outcomes the
        # caller records as ``no-subtitle``, so the probe records them instead
        # of dying with a traceback and no evidence line.
        print(
            "live subtitle probe evidence: part_source="
            f"{part_source} stage=track-listing track_count=not_found"
        )
        pytest.skip(
            "the player endpoint answered the bounded not_found code for this"
            " part: upstream no longer serves it, or the credential in effect"
            " cannot see it — the boundary collapses both into the code the"
            " caller records as no-subtitle.  No listing evidence was obtained,"
            " so the run must not read as green: probe another part, or refresh"
            " the archive metadata when the part came from the archive"
            " database."
        )
    print(
        "live subtitle probe evidence: stage=track-listing"
        f" {_track_evidence(tracks)}"
    )
    if not tracks:
        # A legitimate bounded observation, never "this video has no captions":
        # the credential presence printed above is part of the record.
        print(
            "live subtitle probe evidence: no usable track was visible for"
            " this part under the credential in effect"
        )
        return

    track = tracks[0]
    try:
        segments = asyncio.run(gateway.fetch_subtitle_segments(track, bvid, cid))
    except GatewayRateLimited as refusal:
        _record_risk_control_refusal(
            refusal, stage="subtitle-body", part_source=part_source
        )
    except GatewayNotFound:
        print(
            "live subtitle probe evidence: stage=subtitle-body"
            " segments=not_found"
        )
        pytest.skip(
            "the listed track's document carried nothing usable (bounded"
            " not_found): the outcome is recorded, but a run without segment"
            " evidence must not read as green — rerun the probe later."
        )
    track_kind = "ai" if track.is_ai else "cc"
    print(
        "live subtitle probe evidence: stage=subtitle-body"
        f" track={track.language}:{track_kind}"
        f" {_assert_bounded_segment_facts(segments)}"
    )


@pytest.mark.live_smoke(skip_reason=_LIVE_SMOKE_SKIP_REASON)
def test_live_subtitle_probe_reports_one_real_part_inventory(opt_in_gate):
    """Opt-in live probe: ONE real part's subtitle inventory and body.

    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe resolves
    one part (the operator's archive first, the bounded sample fallback
    second), lists its subtitle inventory through the real adapter in the
    locked call shape, and — when a track is visible — fetches that track's
    body and checks the document-level timeline.  It asserts and prints the
    bounded facts only: counts, language codes, AI versus CC, segment count,
    and milliseconds.
    """


    assert _pinned_package_version() == PINNED_PACKAGE_VERSION

    sessdata = resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR))
    gateway = _load_gateway(sessdata)
    proxy = resolve_proxy(None, os.environ)
    print(
        "live subtitle probe environment:"
        f" sessdata={redact_sessdata(sessdata)}"
        f" proxy={'present' if proxy else 'absent'}"
    )

    bvid, cid, part_source = _resolve_probe_part()
    print(
        f"live subtitle probe part: source={part_source} bvid={bvid} cid={cid}"
    )

    _probe_one_part(gateway, bvid, cid, part_source)


# ------------------------------------------------------------- rehearsals
#
# The rehearsals below run in every default (offline) pytest run and cover the
# probe's own logic — part selection, the read-only archive query, both loud-fail
# guards, the bounded evidence renderers, and every record-and-skip branch — so a
# broken query or a loosened assertion fails offline instead of first surfacing
# during a live run.  No live behaviour is claimed here, and no network call is
# made: the live flow's two calls are driven through a scripted gateway.


def _seed_archive(
    database_path: str,
    *,
    bvid: str,
    cid: int,
    processing_status: ProcessingStatus = "discovered",
    extra_parts: tuple[VideoPartRecord, ...] = (),
) -> None:
    """Seed one user, one video, and the given part rows into a real archive."""

    connection = open_database(database_path)
    repository = MetadataRepository(connection)
    try:
        with repository.transaction():
            repository.upsert_user(make_user_record())
            repository.upsert_video(make_video_record(bvid))
            repository.upsert_part(
                make_part_record(bvid, cid=cid, processing_status=processing_status)
            )
            for part in extra_parts:
                repository.upsert_part(part)
    finally:
        connection.close()


def test_archive_part_selection_reads_the_shipped_schema_and_stays_read_only(
    tmp_root: str, monkeypatch: pytest.MonkeyPatch
):
    """The probe's archive query works on the shipped schema, read-only.

    The archived part is selected from a database the real storage layer
    created, through a connection whose URI is pinned to ``mode=ro``: the probe
    has no code path that could create, migrate, or write the operator's
    archive, and every unreadable case degrades to the sample fallback.
    """

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    _seed_archive(database_path, bvid=BVID, cid=REHEARSAL_CID)
    requested_uris: list[str] = []
    real_connect = sqlite3.connect

    def recording_connect(database: str, **kwargs: object):
        requested_uris.append(database)
        return real_connect(database, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)

    assert _read_archive_part(database_path) == (BVID, REHEARSAL_CID)
    (requested_uri,) = requested_uris
    assert requested_uri.startswith("file://")
    assert requested_uri.endswith("?mode=ro")

    assert _read_archive_part(
        os.path.join(tmp_root, "absent", ARCHIVE_DATABASE_NAME)
    ) is None
    empty_dir = os.path.join(tmp_root, "empty")
    os.makedirs(empty_dir, exist_ok=True)
    assert _read_archive_part(os.path.join(empty_dir, ARCHIVE_DATABASE_NAME)) is None


def test_probe_part_selection_prefers_the_archive_and_falls_back_to_the_sample(
    tmp_root: str, monkeypatch: pytest.MonkeyPatch
):
    """An archived part wins; without one the fixed public sample answers.

    The fallback must not depend on any live call: the second branch scripts
    nothing at all, and the probe still resolves a part — the player endpoint
    and the document it lists are the only live surfaces this probe touches.
    """

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    _seed_archive(database_path, bvid=BVID, cid=REHEARSAL_CID)
    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)

    assert _resolve_probe_part() == (BVID, REHEARSAL_CID, "archive-db")

    monkeypatch.setenv(
        ARCHIVE_DATABASE_PATH_ENV_VAR,
        os.path.join(tmp_root, "absent", ARCHIVE_DATABASE_NAME),
    )
    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")


def test_probe_part_selection_ignores_an_archive_without_a_part(
    tmp_root: str, monkeypatch: pytest.MonkeyPatch
):
    """An archive that carries no part row hands the probe to the sample.

    A database the real storage layer created — schema present, no part row —
    is the shape an operator sees before the first collection, and it must not
    fail the probe.
    """

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    connection = open_database(database_path)
    connection.close()
    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)

    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")


def test_probe_part_selection_skips_a_part_the_archive_marked_gone(
    tmp_root: str, monkeypatch: pytest.MonkeyPatch
):
    """A part the archive knows is gone is never probed, even as the newest row.

    ``gone`` is a first-class shipped part status, and a part upstream no longer
    serves is exactly the one the player endpoint answers ``not_found`` for, so
    selecting it would spend the probe's one live call on a bounded blocker its
    own database could have predicted.  An archive whose every part is gone
    lands on the sample fallback the way an empty one does.
    """

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    _seed_archive(
        database_path,
        bvid=BVID,
        cid=REHEARSAL_CID,
        extra_parts=(
            make_part_record(
                BVID,
                page_index=1,
                cid=REHEARSAL_GONE_CID,
                processing_status="gone",
            ),
        ),
    )
    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)

    # The gone part carries the higher ``video_part_id``, so the ordering alone
    # would select exactly the row the archive has already written off.
    assert _read_archive_part(database_path) == (BVID, REHEARSAL_CID)
    assert _resolve_probe_part() == (BVID, REHEARSAL_CID, "archive-db")

    gone_only_path = os.path.join(tmp_root, "gone-only", ARCHIVE_DATABASE_NAME)
    os.makedirs(os.path.dirname(gone_only_path), exist_ok=True)
    _seed_archive(
        gone_only_path,
        bvid=BVID,
        cid=REHEARSAL_GONE_CID,
        processing_status="gone",
    )
    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, gone_only_path)

    assert _read_archive_part(gone_only_path) is None
    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")


def test_probe_part_selection_ignores_a_row_that_is_not_a_bv_id(
    tmp_root: str, monkeypatch: pytest.MonkeyPatch
):
    """A newest row the adapter would reject hands the probe to the sample.

    The row is written with raw SQL rather than through the repository, which
    validates the shape: this guard exists for the case the repository cannot
    produce — a foreign or hand-edited row — whose ``bvid`` the adapter would
    refuse with ``ValueError`` instead of the probe falling back to its sample.
    """

    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
    _seed_archive(database_path, bvid=BVID, cid=REHEARSAL_CID)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO video_parts("
            " bvid, page_index, cid, title, duration_ms, processing_status,"
            " created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("not-a-bv-id", 9, 4444, "foreign row", 1_000, "discovered", 1, 1),
        )
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setenv(ARCHIVE_DATABASE_PATH_ENV_VAR, database_path)

    # The foreign row is the newest one, so the shape check — not the ordering —
    # is what keeps the adapter's ``ValueError`` out of the probe.
    assert _read_archive_part(database_path) is None
    assert _resolve_probe_part() == (SAMPLE_BVID, SAMPLE_CID, "fixed-sample")


def test_missing_pinned_distribution_fails_loudly(monkeypatch: pytest.MonkeyPatch):
    """An opted-in probe without the pin fails with guidance, not a skip."""

    def missing_distribution(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing_distribution)

    with pytest.raises(pytest.fail.Exception):
        _pinned_package_version()


def test_unimportable_pinned_module_fails_loudly(monkeypatch: pytest.MonkeyPatch):
    """An opted-in probe that cannot import the adapter fails with guidance.

    A module replaced by ``None`` on ``sys.modules`` is what an unimportable
    adapter looks like to an ``import`` statement, so the guard is driven
    offline rather than first by a live run in a half-installed environment.
    """

    monkeypatch.setitem(sys.modules, "bili_asr.sources.bilibili_api_gateway", None)

    with pytest.raises(pytest.fail.Exception) as failure:
        _load_gateway(None)

    message = str(failure.value)
    assert PINNED_PACKAGE_DISTRIBUTION_NAME in message
    assert PINNED_PACKAGE_VERSION in message
    assert "uv sync" in message


def test_live_smoke_switch_is_opt_in(monkeypatch: pytest.MonkeyPatch):
    """Only the documented ``1`` opts the probe in."""

    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
    assert _live_smoke_requested() is False
    for value in ("", "0", "true", "yes", "2"):
        monkeypatch.setenv(LIVE_SMOKE_ENV, value)
        assert _live_smoke_requested() is False
    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
    assert _live_smoke_requested() is True


def test_track_evidence_carries_counts_languages_and_ai_cc_only():
    """The listing evidence is bounded: no label body, no URL, no body text."""

    tracks = (
        SubtitleTrack(
            language="ai-zh",
            label=f"自动生成 {SIGNED_SUBTITLE_URL_MARKER}",
            is_ai=True,
            track_id="1",
        ),
        SubtitleTrack(
            language="zh-CN",
            label=RAW_JSON_BODY_MARKER,
            is_ai=False,
            track_id=None,
        ),
    )

    evidence = _track_evidence(tracks)

    assert evidence == "track_count=2 tracks=ai-zh:ai,zh-CN:cc"
    assert_leaks_no_markers(evidence, context="live subtitle track evidence")
    assert RAW_JSON_BODY_MARKER not in evidence
    assert _track_evidence(()) == "track_count=0 tracks=none"


def test_segment_evidence_requires_a_non_decreasing_timeline():
    """The document-level timeline fact is asserted, and an unordered one fails."""

    forward = (
        SubtitleSegment(start_ms=0, end_ms=1500, text="未明子"),
        SubtitleSegment(start_ms=1500, end_ms=2600, text="讲座"),
    )

    assert _assert_bounded_segment_facts(forward) == (
        "segments=2 first_start_ms=0 last_end_ms=2600 timeline=non-decreasing"
    )
    with pytest.raises(AssertionError):
        _assert_bounded_segment_facts(tuple(reversed(forward)))
    with pytest.raises(AssertionError):
        _assert_bounded_segment_facts(())


class _ScriptedGateway:
    """The probe's two boundary calls, scripted, with no network at all.

    ``_probe_one_part`` is driven through this double so the live flow's control
    flow — every record-and-skip branch included — is entered by a default
    (offline, non-opted-in) pytest run.  ``calls`` records which of the two calls
    were made, in order, so a rehearsal can pin that a listing which never
    answered is not followed by a body fetch.
    """

    def __init__(
        self,
        *,
        tracks: tuple[SubtitleTrack, ...] = (),
        segments: tuple[SubtitleSegment, ...] = (),
        listing_failure: Exception | None = None,
        body_failure: Exception | None = None,
        credential_failure: Exception | None = None,
    ) -> None:
        self._tracks = tracks
        self._segments = segments
        self._listing_failure = listing_failure
        self._body_failure = body_failure
        self._credential_failure = credential_failure
        self.calls: list[str] = []

    async def get_subtitle_tracks(
        self, bvid: str, cid: int
    ) -> tuple[SubtitleTrack, ...]:
        self.calls.append("get_subtitle_tracks")
        if self._listing_failure is not None:
            raise self._listing_failure
        return self._tracks

    async def fetch_subtitle_segments(
        self, track: SubtitleTrack, bvid: str, cid: int
    ) -> tuple[SubtitleSegment, ...]:
        self.calls.append("fetch_subtitle_segments")
        if self._body_failure is not None:
            raise self._body_failure
        return self._segments

    async def validate_subtitle_credentials(self) -> None:
        self.calls.append("validate_subtitle_credentials")
        if self._credential_failure is not None:
            raise self._credential_failure


def _rehearsal_track() -> SubtitleTrack:
    """One track DTO whose display label carries both leak sentinels."""

    return SubtitleTrack(
        language="ai-zh",
        label=f"自动生成 {SIGNED_SUBTITLE_URL_MARKER} {RAW_JSON_BODY_MARKER}",
        is_ai=True,
        track_id="1",
    )


def test_probe_records_an_empty_listing_and_stops_before_the_body(capsys):
    """No visible track is a recorded observation, and the body is not fetched."""

    gateway = _ScriptedGateway()

    _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "fixed-sample")

    evidence = capsys.readouterr().out
    assert "stage=track-listing track_count=0 tracks=none" in evidence
    assert "no usable track was visible" in evidence
    assert gateway.calls == ["get_subtitle_tracks"]


@pytest.mark.parametrize(
    (
        "listing_failure",
        "body_failure",
        "expected_evidence",
        "expected_skip",
        "expected_calls",
    ),
    [
        pytest.param(
            GatewayRateLimited(detail="get_subtitle_tracks"),
            None,
            "part_source=fixed-sample stage=track-listing refusal_code=rate_limited",
            "STOP condition",
            ["get_subtitle_tracks"],
            id="listing-risk-control-refusal",
        ),
        pytest.param(
            GatewayNotFound(detail="get_subtitle_tracks"),
            None,
            "part_source=fixed-sample stage=track-listing track_count=not_found",
            "must not read as green",
            ["get_subtitle_tracks"],
            id="listing-not-found",
        ),
        pytest.param(
            None,
            GatewayRateLimited(detail="fetch_subtitle_segments"),
            "stage=subtitle-body refusal_code=rate_limited",
            "STOP condition",
            ["get_subtitle_tracks", "fetch_subtitle_segments"],
            id="body-risk-control-refusal",
        ),
        pytest.param(
            None,
            GatewayNotFound(detail="fetch_subtitle_segments"),
            "stage=subtitle-body segments=not_found",
            "must not read as green",
            ["get_subtitle_tracks", "fetch_subtitle_segments"],
            id="body-not-found",
        ),
    ],
)
def test_probe_records_each_bounded_blocker_and_never_reads_green(
    capsys,
    listing_failure: Exception | None,
    body_failure: Exception | None,
    expected_evidence: str,
    expected_skip: str,
    expected_calls: list[str],
):
    """All four record-and-skip branches are rehearsed, and none of them passes.

    Each line names the bounded code and the stage — the listing-side lines also
    name the part that produced them; each branch skips instead of passing, which
    is what keeps a run without evidence from reading green; and a listing that
    never answered is never followed by a body fetch.
    """

    gateway = _ScriptedGateway(
        tracks=(_rehearsal_track(),),
        listing_failure=listing_failure,
        body_failure=body_failure,
    )

    with pytest.raises(pytest.skip.Exception) as skipped:
        _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "fixed-sample")

    evidence = capsys.readouterr().out
    assert expected_evidence in evidence
    assert expected_skip in str(skipped.value)
    assert gateway.calls == expected_calls


def test_probe_records_the_whole_evidence_chain_without_leaking_a_label(capsys):
    """The visible-track path prints both bounded lines and no upstream text."""

    gateway = _ScriptedGateway(
        tracks=(_rehearsal_track(),),
        segments=(
            SubtitleSegment(start_ms=0, end_ms=1500, text="未明子"),
            SubtitleSegment(start_ms=1500, end_ms=2600, text="讲座"),
        ),
    )

    _probe_one_part(gateway, SAMPLE_BVID, SAMPLE_CID, "archive-db")

    evidence = capsys.readouterr().out
    assert "stage=track-listing track_count=1 tracks=ai-zh:ai" in evidence
    assert (
        "stage=subtitle-body track=ai-zh:ai segments=2 first_start_ms=0"
        " last_end_ms=2600 timeline=non-decreasing"
    ) in evidence
    assert_leaks_no_markers(evidence, context="live subtitle probe rehearsal")
    assert RAW_JSON_BODY_MARKER not in evidence
    assert gateway.calls == ["get_subtitle_tracks", "fetch_subtitle_segments"]


def test_live_smoke_skip_reason_is_stable():
    """The opt-in skip text stays the byte-identical string docs quote.

    The default run's skip now comes from the central conftest gate
    (``opt_in_gate``), so this rehearsal pins the exact text the probe has
    always skipped with: a wording drift would break operator docs and the
    reason-keyed skip tallies that read the report.
    """

    assert _LIVE_SMOKE_SKIP_REASON == (
        "live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it"
    )
