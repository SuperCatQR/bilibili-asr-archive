"""Offline metadata CLI contract tests for the SQLite command path.

All coverage is offline: ``fetch-meta`` drives the real product gateway
adapter (``bili_asr.sources.bilibili_api_gateway.BilibiliApiGateway``) over
the fake ``bilibili_api`` package seam from ``tests/fixtures/``, while
``status`` and ``runs`` read a temporary SQLite database.  Every test also
pins the no-legacy-sidecar and no-credential boundaries of the metadata CLI
contract:

- ``fetch-meta`` creates exactly ``{archive_root}/archive.db`` and never
  writes ``manifest/manifest.jsonl``, ``meta-cursor.json`` or
  ``run-ledger.jsonl``.
- ``status``/``runs`` fail clearly with exit 1 when that database is
  missing, and read only the fresh database.
- Exit taxonomy: 0 success, 1 usage/configuration error, 2 terminal
  failure — a bounded gateway failure (cursor unchanged) or an unexpected
  internal error (the fixed ``fetch-meta: unexpected error`` message with
  no scalar code).
"""

from __future__ import annotations

import itertools
import os
import time

import pytest

from bili_asr.cli import build_parser, main
from bili_asr.config import (
    DEFAULT_MID,
    DEFAULT_PAGE_LIMIT,
    load_metadata_config,
    redact_sessdata,
    resolve_sessdata,
)
from bili_asr.storage import MetadataRepository, open_database
from bili_asr.storage.models import IngestionRunRecord, UserRecord
from fixtures.fake_bilibili_gateway import (
    MID,
    SESSDATA_BOUNDARY_VALUE,
    UPSTREAM_ERROR_TEXT,
    FakeResponseCodeException,
    assert_leaks_no_markers,
    bilibili_api_seam,
    make_part_item,
    make_vlist_item,
    make_videos_response,
    persisted_row_text,
)

LEGACY_SIDECAR_PATHS = (
    os.path.join("manifest", "manifest.jsonl"),
    "meta-cursor.json",
    "run-ledger.jsonl",
)


def _script_upstream(
    script,
    *,
    pages: dict[int, list[dict]],
    parts: list[dict] | None = None,
) -> None:
    """Script the fake upstream: named pages, missing pages come back empty."""

    def videos_response(pn: int, ps: int):
        items = pages.get(pn, [])
        return make_videos_response(*items, count=len(items))

    script.videos_response = videos_response
    script.parts_response = parts


@pytest.fixture
def _ingest_clock(monkeypatch: pytest.MonkeyPatch):
    """Deterministic monotonic clock for ingestor-produced records.

    Patching the ingestor module's clock keeps run/page timestamps strictly
    increasing, so newest-first output order is testable without real sleeps.
    """

    counter = itertools.count(1)
    monkeypatch.setattr(
        "bili_asr.services.metadata_ingest._now", lambda: next(counter)
    )


def _collect_once(
    tmp_root: str,
    script,
    *,
    bvid: str,
    part_count: int = 1,
    limit_pages: int | None = None,
    sessdata: str | None = None,
    aid: int | None = None,
) -> str:
    """Run one scripted ``fetch-meta`` invocation and return its run id.

    The invocation itself is asserted to exit 0.  ``aid`` overrides the
    fixture's default video aid so a test that collects several distinct
    videos into one database keeps them unique on ``videos.aid``.
    """

    summary_item = (
        make_vlist_item(bvid=bvid)
        if aid is None
        else make_vlist_item(bvid=bvid, aid=aid)
    )
    _script_upstream(
        script,
        pages={1: [summary_item]},
        parts=[
            make_part_item(cid=2222 + index, page=index + 1)
            for index in range(part_count)
        ],
    )
    argv = ["fetch-meta", "--archive-root", tmp_root]
    if limit_pages is not None:
        argv += ["--limit-pages", str(limit_pages)]
    if sessdata is not None:
        argv += ["--sessdata", sessdata]
    assert main(argv) == 0
    return _newest_run_id(tmp_root)


def _newest_run_id(tmp_root: str) -> str:
    """Return the id of the newest ingestion run in the root's database."""

    connection = open_database(tmp_root)
    try:
        run_row = connection.execute(
            "SELECT run_id FROM ingestion_runs"
            " ORDER BY started_at DESC, run_id DESC LIMIT 1"
        ).fetchone()
        assert run_row is not None
        return str(run_row["run_id"])
    finally:
        connection.close()


def _cursor_row(connection):
    return connection.execute(
        "SELECT mid, next_page, observed_total, state, last_error_code, updated_at"
        " FROM ingestion_cursors"
    ).fetchone()


def _run_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("run ")]


# ---------------------------------------------------------------- parser behavior


def test_fetch_meta_help_documents_contract_arguments_and_default_bound(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The parser advertises the metadata CLI contract and its page bound."""

    parser = build_parser()
    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["fetch-meta", "--help"])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    for argument in (
        "--mid",
        "--start-page",
        "--limit-pages",
        "--resume",
        "--archive-root",
        "--sessdata",
    ):
        assert argument in help_text
    assert str(DEFAULT_PAGE_LIMIT) in help_text
    assert "default" in help_text.lower()


def test_resume_and_start_page_are_mutually_exclusive(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--resume and --start-page cannot be combined (usage error, exit 1)."""

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "fetch-meta",
                "--archive-root",
                tmp_root,
                "--resume",
                "--start-page",
                "2",
            ]
        )
    assert exit_info.value.code == 1


@pytest.mark.parametrize(
    "argv_tail",
    [["--start-page", "0"], ["--limit-pages", "0"], ["--limit-pages", "-1"]],
    ids=["start-page-zero", "limit-pages-zero", "limit-pages-negative"],
)
def test_non_positive_page_arguments_exit_one(
    tmp_root: str, argv_tail: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Page arguments must be positive integers (exit 1, bounded message)."""

    assert main(["fetch-meta", "--archive-root", tmp_root, *argv_tail]) == 1
    error_text = capsys.readouterr().err
    assert "positive" in error_text
    assert "Traceback" not in error_text


# ---------------------------------------------------------------- configuration


def test_sessdata_resolves_flag_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SESSDATA comes from --sessdata, else BILI_SESSDATA, else absent."""

    parser = build_parser()
    monkeypatch.setenv("BILI_SESSDATA", "env-cookie")
    assert load_metadata_config(parser.parse_args(["fetch-meta"])).sessdata == "env-cookie"
    assert (
        load_metadata_config(
            parser.parse_args(["fetch-meta", "--sessdata", "flag-cookie"])
        ).sessdata
        == "flag-cookie"
    )
    monkeypatch.delenv("BILI_SESSDATA", raising=False)
    assert load_metadata_config(parser.parse_args(["fetch-meta"])).sessdata is None


def test_blank_sessdata_flag_forces_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--sessdata "" is explicit-anonymous and never adopts BILI_SESSDATA."""

    parser = build_parser()
    monkeypatch.setenv("BILI_SESSDATA", "env-cookie")
    blank_flag_config = load_metadata_config(
        parser.parse_args(["fetch-meta", "--sessdata", ""])
    )
    assert blank_flag_config.sessdata is None
    # The resolution rule itself: an explicitly blank flag forces anonymous
    # access even when the environment carries a credential, while a blank
    # environment also resolves to no credential.
    assert resolve_sessdata("", "env-cookie") is None
    assert resolve_sessdata(None, "env-cookie") == "env-cookie"
    assert resolve_sessdata(None, "") is None
    assert resolve_sessdata("flag-cookie", "env-cookie") == "flag-cookie"


def test_sessdata_display_path_is_redacted() -> None:
    """Display/debug helpers show presence only, never the credential value."""

    assert redact_sessdata(None) == "absent"
    masked = redact_sessdata(SESSDATA_BOUNDARY_VALUE)
    assert masked != SESSDATA_BOUNDARY_VALUE
    assert SESSDATA_BOUNDARY_VALUE not in masked


def test_metadata_config_repr_hides_sessdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config repr never carries the SESSDATA value."""

    parser = build_parser()
    config = load_metadata_config(
        parser.parse_args(["fetch-meta", "--sessdata", SESSDATA_BOUNDARY_VALUE])
    )
    assert SESSDATA_BOUNDARY_VALUE not in repr(config)


def test_default_page_bound_applies_when_limit_pages_omitted() -> None:
    """Omitting --limit-pages applies the documented default bound (C1)."""

    config = load_metadata_config(build_parser().parse_args(["fetch-meta"]))
    assert config.page_limit == DEFAULT_PAGE_LIMIT
    assert isinstance(DEFAULT_PAGE_LIMIT, int)
    assert DEFAULT_PAGE_LIMIT >= 1


def test_default_mid_is_the_archive_owner() -> None:
    """The documented default --mid is the archive owner's UID."""

    assert DEFAULT_MID == 23191782


# ---------------------------------------------------------------- fetch-meta


@pytest.mark.parametrize("part_count", [1, 2], ids=["single-part", "multipart"])
def test_fetch_meta_creates_fresh_database_and_completes(
    tmp_root: str,
    bilibili_api_seam,
    part_count: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One scripted page lands normalized rows, a completing cursor, exit 0."""

    bvid = "BV1SEAMRUNAA"
    _collect_once(tmp_root, bilibili_api_seam, bvid=bvid, part_count=part_count)

    assert os.path.isfile(os.path.join(tmp_root, "archive.db"))
    connection = open_database(tmp_root)
    try:
        assert connection.execute("SELECT COUNT(*) FROM bilibili_users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0]
            == part_count
        )
        run_row = connection.execute(
            "SELECT mid, outcome, requested_page_limit FROM ingestion_runs"
        ).fetchone()
        assert run_row["mid"] == MID
        assert run_row["outcome"] == "complete"
        assert run_row["requested_page_limit"] == DEFAULT_PAGE_LIMIT
        cursor_row = _cursor_row(connection)
        assert tuple(cursor_row)[:5] == (MID, 2, 0, "complete", None)
        pending = MetadataRepository(connection).list_pending_parts()
        assert pending == []
        assert connection.execute(
            "SELECT COUNT(*) FROM video_parts WHERE processing_status = 'metadata_collected'"
        ).fetchone()[0] == part_count
    finally:
        connection.close()

    out, err = capsys.readouterr()
    # page_count mirrors v_ingestion_run_stats: one evidence row per page
    # the run touched, including the completing empty page.
    assert "2 page(s)" in out
    assert "state=complete" in out
    assert err == ""
    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(tmp_root, relative))

    # The pinned adapter drove exactly the documented upstream calls: one
    # page fetch, one parts fetch, one tag fetch, one empty-page fetch (aid
    # present, so no detail call).
    assert bilibili_api_seam.calls == [
        "space.arc.search(pn=1, ps=30)",
        "video.get_pages",
        "video.tags",
        "space.arc.search(pn=2, ps=30)",
    ]


def test_fetch_meta_limit_pages_stops_limited_exit_zero(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
) -> None:
    """An explicit --limit-pages ends the run as limited (still exit 0)."""

    _script_upstream(
        bilibili_api_seam,
        pages={
            1: [make_vlist_item(bvid="BV1LIMITSTO1")],
            2: [make_vlist_item(bvid="BV1LIMITSTO2")],
        },
        parts=[make_part_item(cid=2222)],
    )
    exit_code = main(["fetch-meta", "--archive-root", tmp_root, "--limit-pages", "1"])

    assert exit_code == 0
    out, _err = capsys.readouterr()
    assert "outcome=limited" in out
    assert "complete" not in out
    connection = open_database(tmp_root)
    try:
        run_row = connection.execute(
            "SELECT outcome, requested_page_limit FROM ingestion_runs"
        ).fetchone()
        assert run_row["outcome"] == "limited"
        assert run_row["requested_page_limit"] == 1
        assert connection.execute(
            "SELECT state FROM ingestion_cursors"
        ).fetchone()[0] == "limited"
    finally:
        connection.close()
    assert [
        call for call in bilibili_api_seam.calls if call.startswith("space.arc.search")
    ] == ["space.arc.search(pn=1, ps=30)"]


def test_fetch_meta_start_page_overrides_cursor(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
) -> None:
    """--start-page ignores the stored cursor and starts at the given page."""

    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1FIRSTPG11")

    _script_upstream(
        bilibili_api_seam,
        pages={1: [make_vlist_item(bvid="BV1RESTARTP1", aid=222)]},
        parts=[make_part_item(cid=3333)],
    )
    assert main(["fetch-meta", "--archive-root", tmp_root, "--start-page", "1"]) == 0

    # Page 1 was requested again even though the stored cursor pointed at 2.
    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=30)") == 2
    connection = open_database(tmp_root)
    try:
        start_pages = [
            row[0]
            for row in connection.execute(
                "SELECT requested_start_page FROM ingestion_runs"
            ).fetchall()
        ]
        assert start_pages == [1, 1]
    finally:
        connection.close()
    assert capsys.readouterr().err == ""


def test_fetch_meta_without_flags_resumes_from_stored_cursor(
    tmp_root: str,
    bilibili_api_seam,
    capsys: pytest.CaptureFixture[str],
    _ingest_clock,
) -> None:
    """Without --resume/--start-page the run continues at the cursor page."""

    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1CURSORPG1")

    _script_upstream(
        bilibili_api_seam,
        pages={2: [make_vlist_item(bvid="BV1CURSORPG2", aid=333)]},
        parts=[make_part_item(cid=4444)],
    )
    assert main(["fetch-meta", "--archive-root", tmp_root]) == 0

    # Page 1 was not refetched: the run resumed at the cursor's page 2,
    # while run 1's own completion check already touched page 2.
    assert bilibili_api_seam.calls.count("space.arc.search(pn=1, ps=30)") == 1
    connection = open_database(tmp_root)
    try:
        start_pages = [
            row[0]
            for row in connection.execute(
                "SELECT requested_start_page FROM ingestion_runs"
                " ORDER BY started_at"
            ).fetchall()
        ]
        assert start_pages == [1, 2]
    finally:
        connection.close()


def test_fetch_meta_resume_requires_cursor_without_database(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--resume with no database fails clearly (exit 1) and creates nothing."""

    assert main(["fetch-meta", "--archive-root", tmp_root, "--resume"]) == 1
    error_text = capsys.readouterr().err
    assert "no archive database" in error_text
    assert not os.path.isfile(os.path.join(tmp_root, "archive.db"))


def test_fetch_meta_resume_requires_cursor_in_existing_database(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
) -> None:
    """--resume on an existing cursor-less database fails clearly (exit 1)."""

    connection = open_database(tmp_root)
    connection.close()
    assert main(["fetch-meta", "--archive-root", tmp_root, "--resume"]) == 1
    assert "cursor" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("upstream_code", "expected_code"),
    [(-412, "rate_limited"), (-400, "response_error")],
    ids=["rate-limited", "response-error"],
)
def test_fetch_meta_upstream_failure_exits_two_with_cursor_unchanged(
    tmp_root: str,
    bilibili_api_seam,
    upstream_code: int,
    expected_code: str,
    capsys: pytest.CaptureFixture[str],
    _ingest_clock,
) -> None:
    """A failed page is terminal for the run (exit 2); the cursor never moves."""

    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1FIRSTPG11")
    connection = open_database(tmp_root)
    try:
        cursor_before = _cursor_row(connection)
        assert cursor_before is not None
    finally:
        connection.close()

    script = bilibili_api_seam
    script.videos_response = None
    script.parts_response = None
    script.info_response = None
    script.videos_error = FakeResponseCodeException(upstream_code, UPSTREAM_ERROR_TEXT)
    assert main(["fetch-meta", "--archive-root", tmp_root]) == 2

    connection = open_database(tmp_root)
    try:
        cursor_after = _cursor_row(connection)
        assert tuple(cursor_after) == tuple(cursor_before)
        newest_run_id = connection.execute(
            "SELECT run_id FROM ingestion_runs"
            " ORDER BY started_at DESC, run_id DESC LIMIT 1"
        ).fetchone()[0]
        failed_pages = connection.execute(
            "SELECT outcome, error_code FROM ingestion_pages"
            " WHERE run_id = ? AND outcome != 'ok'",
            (newest_run_id,),
        ).fetchall()
        expected_outcome = (
            "risk_interrupted" if expected_code == "rate_limited" else "failed"
        )
        assert [tuple(row) for row in failed_pages] == [
            (expected_outcome, expected_code)
        ]
        run_row = connection.execute(
            "SELECT outcome FROM ingestion_runs ORDER BY started_at DESC, run_id DESC"
        ).fetchone()
        assert run_row["outcome"] == expected_outcome
    finally:
        connection.close()

    out, err = capsys.readouterr()
    assert expected_code in err
    assert "cursor unchanged" in err
    assert_leaks_no_markers(out + err, context="fetch-meta failure output")


def test_fetch_meta_unexpected_error_is_bounded_exit_two_no_traceback(
    tmp_root: str,
    bilibili_api_seam,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-gateway exceptions map to the terminal exit with a generic message."""

    class _UnexpectedIngestor:
        def __init__(self, gateway, repository) -> None:
            del gateway, repository

        def collect_user_pages(self, *args, **kwargs):
            raise RuntimeError("raw-unexpected-payload-sentinel")

    monkeypatch.setattr("bili_asr.services.MetadataIngestor", _UnexpectedIngestor)

    assert main(["fetch-meta", "--archive-root", tmp_root]) == 2
    out, err = capsys.readouterr()
    assert err == "fetch-meta: unexpected error\n"
    assert "raw-unexpected-payload-sentinel" not in out + err
    assert "Traceback" not in err


@pytest.mark.parametrize("fail_upstream", [False, True], ids=["success", "failure"])
def test_fetch_meta_never_writes_legacy_sidecars(
    tmp_root: str, bilibili_api_seam, fail_upstream: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """No command path creates the old JSONL/cursor/ledger sidecars."""

    script = bilibili_api_seam
    if fail_upstream:
        script.videos_error = FakeResponseCodeException(-412, UPSTREAM_ERROR_TEXT)
    else:
        _script_upstream(script, pages={1: [make_vlist_item(bvid="BV1NOSIDECR1")]})

    main(["fetch-meta", "--archive-root", tmp_root])

    for relative in LEGACY_SIDECAR_PATHS:
        assert not os.path.exists(os.path.join(tmp_root, relative))


def test_fetch_meta_persists_no_secret_markers(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
) -> None:
    """The SESSDATA value never reaches output or any persisted row."""

    _collect_once(
        tmp_root,
        bilibili_api_seam,
        bvid="BV1NOSECRET1",
        sessdata=SESSDATA_BOUNDARY_VALUE,
    )

    out, err = capsys.readouterr()
    assert_leaks_no_markers(out + err, context="fetch-meta output")
    connection = open_database(tmp_root)
    try:
        assert_leaks_no_markers(
            persisted_row_text(connection), context="fetch-meta persisted rows"
        )
    finally:
        connection.close()


# ---------------------------------------------------------------- status


def test_status_fails_clearly_when_database_missing(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read command on a fresh root exits 1 with a bounded configuration error."""

    assert main(["status", "--archive-root", tmp_root]) == 1
    out, err = capsys.readouterr()
    assert "no archive database" in err
    assert out == ""


def test_status_reports_counts_pending_and_cursor_from_sqlite(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
) -> None:
    """status counts entities and pending work from the fresh database only."""

    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1STATUSPRB", part_count=2)

    assert main(["status", "--archive-root", tmp_root]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "users: 1" in out
    assert "videos: 1" in out
    assert "parts: 2" in out
    assert "metadata_collected=2" in out
    assert "pending: 0" in out
    assert "state=complete" in out


def test_status_ignores_legacy_sidecar_rows(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
) -> None:
    """status never reads or rewrites legacy metadata sidecars."""

    from bili_asr.manifest import ManifestStore

    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1STATUSPU1")
    legacy_store = ManifestStore(root=tmp_root)
    legacy_store.upsert(
        {"work_id": "BV1LEGACYROW:p0", "bvid": "BV1LEGACYROW", "status": "archived"}
    )
    legacy_cursor_path = os.path.join(tmp_root, "meta-cursor.json")
    with open(legacy_cursor_path, "w", encoding="utf-8") as cursor_handle:
        cursor_handle.write('{"mid": 1, "state": "legacy-cursor-state"}\n')

    assert main(["status", "--archive-root", tmp_root]) == 0
    out, _err = capsys.readouterr()
    assert "BV1LEGACYROW" not in out
    assert "legacy-cursor-state" not in out
    assert os.path.isfile(legacy_cursor_path)
    # ``status`` must not rewrite the legacy sidecars either: the legacy
    # manifest row stays an unread journal entry (the snapshot the other
    # legacy-sidecar tests pin is never materialized), the legacy cursor
    # keeps its bytes.  What ``status`` must never do is create the snapshot
    # itself — ``fetch-meta``'s contract above is that it writes only
    # ``archive.db``, so the bare ``manifest/`` directory is the honest
    # post-condition.
    manifest_dir = os.path.join(tmp_root, "manifest")
    assert os.path.isdir(manifest_dir)
    assert not os.path.exists(os.path.join(manifest_dir, "manifest.jsonl"))


# ---------------------------------------------------------------- runs


def test_runs_fails_clearly_when_database_missing(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """runs on a fresh root exits 1 with a bounded configuration error."""

    assert main(["runs", "--archive-root", tmp_root]) == 1
    out, err = capsys.readouterr()
    assert "no archive database" in err
    assert out == ""


def test_runs_empty_database_prints_empty_exit_zero(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """An existing database without runs prints runs: empty (exit 0)."""

    connection = open_database(tmp_root)
    connection.close()
    assert main(["runs", "--archive-root", tmp_root]) == 0
    out, _err = capsys.readouterr()
    assert "runs: empty" in out


def test_runs_rejects_non_positive_limit(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str]
) -> None:
    """--limit must be a positive integer when given (exit 1)."""

    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA1")
    assert main(["runs", "--archive-root", tmp_root, "--limit", "0"]) == 1
    error_text = capsys.readouterr().err
    assert "positive" in error_text
    assert "Traceback" not in error_text


def test_runs_lists_newest_first_and_renders_running_rows(
    tmp_root: str,
    bilibili_api_seam,
    capsys: pytest.CaptureFixture[str],
    _ingest_clock,
) -> None:
    """Runs output is newest-first and includes non-terminal running rows (C2)."""

    first_run_id = _collect_once(
        tmp_root, bilibili_api_seam, bvid="BV1RUNHIST1A", aid=441
    )
    second_run_id = _collect_once(
        tmp_root, bilibili_api_seam, bvid="BV1RUNHIST2A", aid=442
    )
    stub_run_id = "stub-running-run-0001"
    connection = open_database(tmp_root)
    try:
        MetadataRepository(connection).start_run(
            IngestionRunRecord(
                run_id=stub_run_id,
                mid=MID,
                source_package="bilibili-api-python",
                source_version="17.4.2",
                requested_start_page=1,
                requested_page_limit=DEFAULT_PAGE_LIMIT,
                started_at=int(time.time()) + 60,
                outcome="running",
            )
        )
    finally:
        connection.close()

    assert main(["runs", "--archive-root", tmp_root]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    run_ids = [line.split()[1] for line in out.splitlines() if line.startswith("run ")]
    assert len(run_ids) == 3
    assert run_ids[0] == stub_run_id
    assert "outcome=running" in out
    assert {first_run_id, second_run_id} <= set(run_ids)


def test_runs_orders_same_second_runs_by_run_id_desc(
    tmp_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two runs sharing a started_at second render in run_id-descending order."""

    same_second = 1_000
    connection = open_database(tmp_root)
    try:
        repository = MetadataRepository(connection)
        # The runs' mid foreign key needs its owner row first.
        repository.upsert_user(
            UserRecord(
                mid=MID,
                display_name=str(MID),
                created_at=same_second,
                updated_at=same_second,
            )
        )
        for run_id in ("stub-same-second-aaa", "stub-same-second-bbb"):
            repository.start_run(
                IngestionRunRecord(
                    run_id=run_id,
                    mid=MID,
                    source_package="bilibili-api-python",
                    source_version="17.4.2",
                    requested_start_page=1,
                    requested_page_limit=DEFAULT_PAGE_LIMIT,
                    started_at=same_second,
                    outcome="running",
                )
            )
    finally:
        connection.close()

    assert main(["runs", "--archive-root", tmp_root]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    run_ids = [line.split()[1] for line in _run_lines(out)]
    assert run_ids == ["stub-same-second-bbb", "stub-same-second-aaa"]


def test_runs_limit_shows_only_recent_rows(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str], _ingest_clock
) -> None:
    """--limit bounds the runs listing to the most recent rows."""

    oldest_run_id = _collect_once(
        tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA1", aid=451
    )
    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA2", aid=452)
    _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNLIMIA3", aid=453)

    assert main(["runs", "--archive-root", tmp_root, "--limit", "2"]) == 0
    out, _err = capsys.readouterr()
    run_lines = _run_lines(out)
    assert len(run_lines) == 2
    assert oldest_run_id not in out


def test_runs_shows_bounded_error_codes_only(
    tmp_root: str, bilibili_api_seam, capsys: pytest.CaptureFixture[str], _ingest_clock
) -> None:
    """A failed run renders its bounded scalar code, never upstream payload text."""

    first_run_id = _collect_once(tmp_root, bilibili_api_seam, bvid="BV1RUNCOMPL1")
    script = bilibili_api_seam
    script.videos_response = None
    script.parts_response = None
    script.info_response = None
    script.videos_error = FakeResponseCodeException(-400, UPSTREAM_ERROR_TEXT)
    assert main(["fetch-meta", "--archive-root", tmp_root]) == 2

    assert main(["runs", "--archive-root", tmp_root]) == 0
    out, _err = capsys.readouterr()
    assert f"run {first_run_id}" in out and "outcome=complete" in out
    assert "outcome=failed" in out
    assert "error=response_error" in out
    assert_leaks_no_markers(out, context="runs output")
