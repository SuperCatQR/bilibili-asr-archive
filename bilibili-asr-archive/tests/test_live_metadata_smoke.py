"""Opt-in bounded live smoke: one real CLI page into a temporary database.

This module holds the only networked metadata test.  It drives the real
user-facing command path — ``bili_asr.cli.main`` with plain argv, the real
``BilibiliApiGateway`` adapter over the pinned ``bilibili-api-python``
distribution, and the fresh SQLite repository — for exactly one public
metadata page of the archive owner (UID 23191782, ``--start-page 1``,
``--limit-pages 1``) inside a temporary archive root.  No subtitle, playback,
audio, or ASR code is invoked, and nothing outside the temporary root is
written.

Default pytest runs skip the smoke; it executes only when the operator sets
``BILI_LIVE_SMOKE=1``.  Two documented outcomes are valid:

- the happy path (exit 0) lands the expected normalized rows — user, videos
  joined to their user through ``mid``, parts joined to their video through
  ``bvid``, one discovery row per collected video, a terminal run row,
  exactly one page-evidence row, and the fresh cursor advanced past the
  committed page — while every persisted surface stays free of credential,
  signed-URL, and playback markers;
- the bounded upstream failure (exit 2) is a valid, documented CLI outcome:
  the failure evidence stays scalar (terminal run row, one bounded page row,
  no entity or discovery growth, no cursor row), and the smoke verifies it.
  Without a credential the run is anonymous, and an upstream rejection of
  anonymous metadata access is one bounded failure among others
  (``rate_limited``, or ``response_error`` for other upstream failures): the
  smoke reports that case as the documented no-credential behavior (a
  clearly-reasoned skip, after its assertions ran), while the same bounded
  failure with an operator credential in the environment is a loud failure.
"""

from __future__ import annotations

import importlib.metadata
import os

import pytest

from bili_asr.cli import main
from bili_asr.config import SESSDATA_ENV_VAR
from bili_asr.storage import open_database
from fixtures.fake_bilibili_gateway import (
    RAW_JSON_BODY_MARKER,
    SESSDATA_BOUNDARY_VALUE,
    SIGNED_URL_MARKER,
    UPSTREAM_ERROR_TEXT,
    FakeResponseCodeException,
    assert_leaks_no_markers,
    bilibili_api_seam,
    make_part_item,
    make_videos_response,
    make_vlist_item,
    persisted_row_text,
)

PINNED_PACKAGE_VERSION = "17.4.2"

#: The archive owner whose public metadata the bounded smoke may collect.
LIVE_SMOKE_MID = 23191782

LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"

#: Tokens that must never appear in the live smoke's persisted rows: cookie
#: names and playback-CDN signature markers indicate credential or playback
#: leakage rather than ordinary metadata.
LIVE_HYGIENE_TOKENS = ("sessdata", "pssign", "bilivideo.com")

#: Tokens scanned in CLI output.  The bare ``sessdata`` word is excluded on
#: purpose: the CLI prints the redacted presence label
#: ``sessdata: present|absent`` by design, and only the credential VALUE
#: itself (scanned separately below) must never appear.
LIVE_OUTPUT_HYGIENE_TOKENS = ("pssign", "bilivideo.com")

LEGACY_SIDECAR_PATHS = (
    os.path.join("manifest", "manifest.jsonl"),
    "meta-cursor.json",
    "run-ledger.jsonl",
)


def _live_smoke_requested() -> bool:
    """True only when the operator explicitly opts in via the environment."""

    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"


def _pinned_package_version() -> str:
    """Return the installed distribution version, or fail loudly.

    Loud-fail guard (Plan-2 live-smoke precedent): an opted-in smoke in an
    environment without the pinned distribution fails loudly with install
    guidance instead of silently skipping.
    """

    try:
        return importlib.metadata.version("bilibili-api-python")
    except importlib.metadata.PackageNotFoundError as error:
        pytest.fail(
            "live smoke was requested but bilibili-api-python is not installed"
            f" in this environment ({error}); install the pinned"
            f" bilibili-api-python=={PINNED_PACKAGE_VERSION} (uv sync) first"
        )


def _assert_no_credential_or_playback_leaks(
    surface_text: str, persisted_text: str
) -> None:
    """Scan live CLI output and persisted rows for leakage markers.

    The static markers cover cookie names and playback-CDN signature
    markers; when the operator supplied a credential through the
    environment, its value is scanned on both surfaces as well and must
    never appear.
    """

    lowered_rows = persisted_text.lower()
    for token in LIVE_HYGIENE_TOKENS:
        assert token not in lowered_rows, f"live smoke persisted {token!r}"
    lowered_output = surface_text.lower()
    for token in LIVE_OUTPUT_HYGIENE_TOKENS:
        assert token not in lowered_output, f"live smoke output carried {token!r}"
    credential = os.environ.get(SESSDATA_ENV_VAR)
    if credential:
        assert credential not in surface_text, (
            "live smoke output carried the operator SESSDATA value"
        )
        assert credential not in persisted_text, (
            "live smoke persisted the operator SESSDATA value"
        )


def _assert_collected_page_rows(connection, mid: int) -> str:
    """Assert the normalized evidence a successful one-page run leaves.

    The successful run is terminal (``limited`` on the explicit page bound
    with a non-empty page, ``complete`` on an empty one) and leaves exactly
    one page-evidence row, the user row, one video row per collected video
    with one run/page discovery row each, at least one part row in aggregate
    over the collected page (not one per video: an individual video may have
    no parts upstream), and a cursor that advanced past the committed page.

    Returns a one-line, count-only evidence summary (no credential, no
    collected metadata values) for the live run to print.
    """

    run_row = connection.execute(
        "SELECT outcome, requested_start_page, requested_page_limit, finished_at"
        " FROM ingestion_runs"
    ).fetchone()
    assert run_row is not None, "the run row must exist"
    assert run_row["outcome"] in ("complete", "limited"), (
        "a successful run must be terminal (not 'running')"
    )
    assert run_row["requested_start_page"] == 1
    assert run_row["requested_page_limit"] == 1
    assert run_row["finished_at"] is not None

    # Exactly one bounded page-evidence row for the one requested page.
    assert connection.execute(
        "SELECT COUNT(*) FROM ingestion_pages"
    ).fetchone()[0] == 1, "the one-page run leaves exactly one page row"
    page_row = connection.execute(
        "SELECT page_number, outcome, error_code FROM ingestion_pages"
    ).fetchone()
    assert page_row["page_number"] == 1
    assert page_row["error_code"] is None, "a committed page carries no error code"

    assert connection.execute(
        "SELECT COUNT(*) FROM bilibili_users WHERE mid = ?", (mid,)
    ).fetchone()[0] == 1
    # Every video joins its owner user through mid; every part joins its
    # video through bvid; every discovery row joins the video it discovered
    # (the normalized foreign-key relationships).
    assert connection.execute(
        "SELECT COUNT(*) FROM videos AS v"
        " LEFT JOIN bilibili_users AS u ON v.mid = u.mid"
        " WHERE u.mid IS NULL"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM video_parts AS p"
        " LEFT JOIN videos AS v ON p.bvid = v.bvid"
        " WHERE v.bvid IS NULL"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM ingestion_discoveries AS d"
        " LEFT JOIN videos AS v ON d.bvid = v.bvid"
        " WHERE v.bvid IS NULL"
    ).fetchone()[0] == 0
    video_count = connection.execute(
        "SELECT COUNT(*) FROM videos WHERE mid = ?", (mid,)
    ).fetchone()[0]
    part_count = connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0]
    discovery_count = connection.execute(
        "SELECT COUNT(*) FROM ingestion_discoveries"
    ).fetchone()[0]

    cursor_row = connection.execute(
        "SELECT next_page, state, observed_total FROM ingestion_cursors"
        " WHERE mid = ?",
        (mid,),
    ).fetchone()
    assert cursor_row is not None, "a collected page must record the fresh cursor"
    observed_total = cursor_row["observed_total"]
    if run_row["outcome"] == "limited":
        assert video_count >= 1
        # The page carries at least one part in aggregate (parts are fetched
        # for every collected video; an individual video may legitimately have
        # no parts upstream, so this is deliberately not a per-video claim),
        # and each collected video is recorded once as discovered on this page.
        assert part_count >= 1
        assert discovery_count == video_count
        assert tuple(page_row)[:2] == (1, "ok")
        assert cursor_row["state"] == "limited"
        # The cursor advanced past the committed page.
        assert cursor_row["next_page"] == page_row["page_number"] + 1
    else:  # complete: the first page came back empty and completed the run
        assert video_count == 0
        assert part_count == 0
        assert discovery_count == 0
        assert tuple(page_row)[:2] == (1, "empty")
        assert tuple(cursor_row)[:2] == (1, "complete")
    if observed_total is not None:
        assert observed_total >= video_count
    return (
        f"outcome={run_row['outcome']} videos={video_count}"
        f" parts={part_count} discoveries={discovery_count} page_rows=1"
        f" cursor_next_page={cursor_row['next_page']}"
        f" cursor_state={cursor_row['state']}"
        f" observed_total={observed_total}"
    )


def _assert_bounded_failure_rows(connection, mid: int) -> str:
    """Assert the scalar-only evidence a bounded one-page failure leaves."""

    run_row = connection.execute(
        "SELECT outcome, finished_at FROM ingestion_runs"
    ).fetchone()
    assert run_row is not None, "the failed run row must still exist"
    assert run_row["outcome"] in ("risk_interrupted", "failed")
    assert run_row["finished_at"] is not None
    page_row = connection.execute(
        "SELECT page_number, outcome, error_code FROM ingestion_pages"
    ).fetchone()
    assert page_row is not None and page_row["page_number"] == 1
    assert page_row["outcome"] in ("risk_interrupted", "failed")
    error_code = page_row["error_code"]
    assert error_code, "the failed page must carry a bounded scalar error code"
    # The rolled-back page left no payload and no cursor movement; the user
    # row was committed with the run start and stays.
    assert connection.execute(
        "SELECT COUNT(*) FROM bilibili_users WHERE mid = ?", (mid,)
    ).fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM ingestion_discoveries"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM ingestion_cursors"
    ).fetchone()[0] == 0
    return str(error_code)


def _bounded_live_argv(tmp_root: str) -> list[str]:
    """The exact bounded smoke invocation: one explicit page, one limit."""

    return [
        "fetch-meta",
        "--mid",
        str(LIVE_SMOKE_MID),
        "--start-page",
        "1",
        "--limit-pages",
        "1",
        "--archive-root",
        tmp_root,
    ]


def test_live_smoke_fetch_meta_one_page_lands_normalized_rows(
    tmp_root: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Opt-in live probe: ONE public metadata page through the real CLI.

    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The probe runs
    the real ``fetch-meta`` command for UID 23191782 with ``--start-page 1
    --limit-pages 1`` into a temporary archive root, asserts the normalized
    table relationships on the happy path (user, videos, parts, discovery,
    run, page and cursor), and asserts the scalar-only failure evidence when
    upstream rejects the page.  It never invokes subtitle, playback, audio,
    or ASR code.
    """

    if not _live_smoke_requested():
        pytest.skip(f"live smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to request it")

    # Loud-fail guard: an opted-in smoke without the pinned distribution
    # fails loudly with install guidance instead of silently skipping.
    assert _pinned_package_version() == PINNED_PACKAGE_VERSION

    exit_code = main(_bounded_live_argv(tmp_root))
    out, err = capsys.readouterr()

    assert os.path.isfile(os.path.join(tmp_root, "archive.db"))
    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(tmp_root, relative))

    connection = open_database(tmp_root)
    try:
        persisted = persisted_row_text(connection)
        _assert_no_credential_or_playback_leaks(out + err, persisted)
        if exit_code == 0:
            assert err == ""
            assert "sessdata:" in out
            assert "outcome=" in out
            evidence = _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
            # Count-only evidence for the operator's record of the live run:
            # no credential, no proxy, and no collected metadata values.
            print(f"live smoke evidence: {evidence}")
            return

        assert exit_code == 2
        if "unexpected error" in err:
            pytest.fail(
                "live smoke hit an unexpected internal error (exit 2 without"
                " a bounded run record); rerun to capture the failure shape"
            )
        error_code = _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID)
        # The bounded scalar code only: no output text, no upstream payload.
        print(f"live smoke evidence: exit=2 error_code={error_code}")
        assert error_code in err
        assert "metadata gateway failure" in err
        # Same resolution rule as ``resolve_sessdata``: a missing or blank
        # BILI_SESSDATA means no credential was in play.
        if not os.environ.get(SESSDATA_ENV_VAR):
            pytest.skip(
                "live smoke ended in the documented bounded anonymous"
                f" rejection (error_code={error_code!r}, exit 2): without a"
                " credential the run is anonymous, and upstream rejects some"
                " anonymous metadata access; the smoke accepts this bounded"
                " no-credential outcome rather than treating it as a defect."
                f" Provide a credential via {SESSDATA_ENV_VAR} in the"
                " environment for the happy-path run; this smoke builds its"
                " own argv, so its --sessdata flag is never passed."
            )
        pytest.fail(
            "live smoke ended in a bounded upstream failure despite an"
            f" operator credential (error_code={error_code!r}); rerun when"
            " upstream recovers"
        )
    finally:
        connection.close()


def test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam(
    tmp_root: str,
    bilibili_api_seam,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rehearse the live-smoke outcome branches offline through the CLI.

    The live smoke's database assertions are plain SQL over the fresh
    schema; this rehearsal runs them against the same real CLI path over
    the fake ``bilibili_api`` seam, so a broken assertion or query is
    caught by every default (offline) run instead of first failing at the
    QA gate's live execution.  The scripted branches cover the limited
    happy path, the ``complete`` happy-path sub-branch (an empty first
    page — practically unreachable live for this UID), and the bounded
    upstream failure.  No live behavior is claimed here.
    """

    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
    script = bilibili_api_seam

    def videos_response(pn: int, ps: int):
        # Payload-laden upstream item: the seam sentinels ride the page so
        # the no-leak assertions scan a surface that really carried them.
        items = (
            [
                make_vlist_item(
                    bvid="BV1REHEARSE1",
                    sessdata_note=SESSDATA_BOUNDARY_VALUE,
                    frame_url=SIGNED_URL_MARKER,
                    raw_note=RAW_JSON_BODY_MARKER,
                )
            ]
            if pn == 1
            else []
        )
        return make_videos_response(*items, count=len(items))

    script.videos_response = videos_response
    script.parts_response = [make_part_item(cid=2222)]

    # Branch one: the limited happy path lands every normalized row family.
    assert main(_bounded_live_argv(tmp_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "sessdata: absent" in out
    assert "outcome=limited" in out
    assert "cursor: next_page=2 state=limited" in out
    connection = open_database(tmp_root)
    try:
        evidence = _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
        # The evidence line the live run prints is count-only and keeps its
        # documented fields, so the offline rehearsal guards its shape.
        assert "outcome=limited" in evidence
        assert "videos=1" in evidence
        assert "cursor_next_page=2" in evidence
        # Positive control: a normalized video row really persisted, so the
        # no-leak scans are not vacuous.
        persisted = persisted_row_text(connection)
        assert "BV1REHEARSE1" in persisted
        assert_leaks_no_markers(out + err, context="rehearsal output")
        assert_leaks_no_markers(persisted, context="rehearsal persisted rows")
    finally:
        connection.close()
    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(tmp_root, relative))

    # Branch two: the complete happy-path sub-branch over the seam — an
    # empty first page completes the run without any collected video, a
    # shape a live run for this UID practically never sees.
    complete_root = os.path.join(tmp_root, "complete")
    script.videos_response = lambda pn, ps: make_videos_response(count=0)
    script.parts_response = None
    assert main(_bounded_live_argv(complete_root)) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "outcome=complete" in out
    assert "cursor: next_page=1 state=complete" in out
    connection = open_database(complete_root)
    try:
        _assert_collected_page_rows(connection, LIVE_SMOKE_MID)
        assert_leaks_no_markers(out + err, context="rehearsal complete output")
    finally:
        connection.close()
    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(complete_root, relative))

    # Branch three: a bounded upstream failure on a fresh root stays scalar.
    failure_root = os.path.join(tmp_root, "failure")
    script.videos_response = None
    script.parts_response = None
    script.videos_error = FakeResponseCodeException(-400, UPSTREAM_ERROR_TEXT)
    assert main(_bounded_live_argv(failure_root)) == 2
    out, err = capsys.readouterr()
    assert "metadata gateway failure" in err
    connection = open_database(failure_root)
    try:
        assert _assert_bounded_failure_rows(connection, LIVE_SMOKE_MID) == (
            "response_error"
        )
        assert_leaks_no_markers(out + err, context="rehearsal failure output")
        assert_leaks_no_markers(
            persisted_row_text(connection),
            context="rehearsal failure persisted rows",
        )
    finally:
        connection.close()
    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(failure_root, relative))
