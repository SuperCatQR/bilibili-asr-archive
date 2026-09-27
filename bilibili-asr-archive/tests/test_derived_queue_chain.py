"""The chain accepts what the bridge writes (spec §4; compass criteria 2, 3, 6).

Every case starts from **Fixture F**: a disposable archive root whose
``archive.db`` records a captionless part through the shipping harvest path
(``harvest-subs`` against the scripted gateway double, which records the part's
``no-subtitle`` attempt) beside a part that already holds a stored caption.
``derive-manifest`` then appends the manifest row the chain reads, and the chain
itself is driven end to end through ``bili_asr.cli.main``.

What is pinned, per compass criterion:

- **2** — the captionless part the harvest path recorded is reachable by the
  audio path with no hand editing: ``download-audio --missing-subs --limit 1``
  does not print the shipped ``download-audio: no needs_audio entries in the
  manifest`` line, and the attempt is signed for the derived page's stored
  ``cid`` (one playurl call, no page resolution).
- **3** — ``run --scope pending --offline`` carries the derived row past the
  state the bridge gave it (``needs_audio`` → ``archived``) and no attempt
  record carries ``missing_subtitle_raw`` for a derived ``work_id`` (spec §4's
  invariant, read back from ``coordinator/attempts.jsonl``).  The negative
  control shows the code is producible (case 3): one hand-written
  ``subtitle_done`` row whose ``subtitles/raw/{stem}.json`` does not exist — the
  state the bridge refuses to write (spec §3.3, §4) — records exactly that code
  in the same run and does not reach ``archived``, so the filter the assertion
  above applies is live rather than vacuous.
- **6** — both halves of spec §5 decision 4.  A successful bounded attempt takes
  the row out of ``needs_audio``, so the next bounded selection attempts the
  other part; an attempt the chain's own audio budget skips leaves no recency
  anywhere, so the next bounded selection proposes the same head again.  The
  lost half is the residual the compass registers, demonstrated here rather than
  asserted in prose.

**No network, by construction, in three layers.**  A ``run --offline`` case
builds no client at all (``cli.py``: ``client = None`` unless the flag is
absent), so it hands the seam a transport that raises on any use and asserts the
transport recorded no call.  The ``download-audio`` cases and the budget case
replace ``bili_client.build_default_transport`` with the frozen spec's scripted
in-memory ``RouterTransport`` (``{SPECS_DIR}/asr-archive-cli.md:103-109``), which
answers from dicts and fails loudly on an unrouted URL.  On top of both, every
case installs a socket tripwire, so a code path that reached for a real socket
would fail here instead of quietly using the network.  No case downloads audio
from anywhere but the scripted payload, and the ASR model is the repository's own
stubbed runner seam (``test_coordinator._stub_asr``).

**What stays untested, and why.**  This environment has no ``[asr]`` extra
(``transformers`` is not importable), so the real-model ASR path cannot run: the
stub-free case below observes the documented install-hint stop instead, and
criterion 3's live confirmation is recorded as untested rather than passed.
"""

from __future__ import annotations

import importlib.util
import os
import socket

import pytest

from bili_asr.cli import main
from bili_asr.coordinator import AttemptLedger
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, identity_from_entry

from fixtures.fake_bilibili_gateway import FakeGateway, fake_gateway_seam
from test_audio import (
    AUDIO_BYTES,
    SPI_OK,
    STREAM_HOST,
    RouterTransport,
    nav_response,
    playurl_ok,
)
from test_cli_derive_manifest import _archive_connection, _derive, _seed_archive
from test_coordinator import _patch_cli, _row, _stub_asr

#: The captionless part: no transcript row, recorded ``no-subtitle`` by
#: ``harvest-subs``.  This is the part the bridge derives.
QUEUED_BVID = "BV1CHAINQ"
QUEUED_PAGE_INDEX = 0
QUEUED_CID = 3001
QUEUED_DURATION_MS = 3_600_500
QUEUED_WORK_ID = f"{QUEUED_BVID}:p{QUEUED_PAGE_INDEX}"

#: A part that already holds a stored caption, so the store's queue relation
#: excludes it.  The negative control hangs its hand-written ``subtitle_done``
#: row on this identity: the store holds the caption, the chain's archive stage
#: reads the filesystem, and no document was ever written there.
CAPTIONED_BVID = "BV1CHAINC"
CAPTIONED_CID = 2001
CAPTIONED_WORK_ID = f"{CAPTIONED_BVID}:p0"

#: The rotation fixture: two never-attempted pages of one video, so the store's
#: locked order (``attempted ASC, last_attempt_at ASC, bvid ASC, page_index
#: ASC``) decides by ``page_index`` alone and the case cannot flake on the
#: one-second granularity of attempt timestamps.
ROTATION_BVID = "BV1CHAINR"
ROTATION_CIDS = (3101, 3102)
ROTATION_DURATIONS_MS = (1_234, 2_345)
ROTATION_WORK_IDS = (f"{ROTATION_BVID}:p0", f"{ROTATION_BVID}:p1")

CHAIN_FIXTURE = (
    (
        QUEUED_BVID,
        QUEUED_PAGE_INDEX,
        QUEUED_CID,
        QUEUED_DURATION_MS,
        "metadata_collected",
    ),
    (CAPTIONED_BVID, 0, CAPTIONED_CID, 1_234, "metadata_collected"),
)
QUEUED_PART_CIDS = (QUEUED_CID,)
CAPTIONED_PARTS = ((CAPTIONED_BVID, 0),)
ROTATION_FIXTURE = tuple(
    (ROTATION_BVID, page_index, cid, duration_ms, "metadata_collected")
    for page_index, (cid, duration_ms) in enumerate(
        zip(ROTATION_CIDS, ROTATION_DURATIONS_MS)
    )
)

#: The shipped line ``download-audio`` prints when its selection is empty
#: (``cli.py``).  Criterion 2's observable is that this string does not appear:
#: the derived row is what the command selects.
NO_NEEDS_AUDIO_LINE = "download-audio: no needs_audio entries in the manifest"

#: The attempt code the archive-from-subtitle path writes when the raw document
#: is absent (``coordinator._stage_archive_from_subtitle``); spec §4's invariant
#: is that no derived ``work_id`` ever carries it.
MISSING_SUBTITLE_RAW = "missing_subtitle_raw"

#: The audio budget's skip reason (``audio_budget.SKIP_REASON``).
AUDIO_BUDGET_SKIP = "audio_budget"

#: The stub-free case below is skipped when the extra **is** importable — the
#: opposite of a missing-extra message — so its reason is its own string: the
#: reader's condition is "this host has `transformers`", and a reason about a missing
#: extra would send a triager after the wrong thing.  Criterion 3's live clause
#: itself (a real model reaching ``archived``) is recorded as untested by the
#: last case in this file, which carries the environment facts it rests on.
ASR_EXTRA_INSTALLED = (
    "the [asr] extra is installed, so the documented install-hint stop cannot "
    "be observed"
)


@pytest.fixture(autouse=True)
def _anonymous_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No credential in the environment unless a case sets one explicitly."""

    monkeypatch.delenv("BILI_SESSDATA", raising=False)


def _forbid_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any socket this test could open fail loudly.

    The scripted transports are the first guarantee; this is the second.  Both
    the CLI's own client and anything it delegates to reach the network through
    ``socket``, so a path that got past the scripted seam would fail here rather
    than silently use the network.
    """

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "this test reached for a socket: the chain cases must stay offline"
        )

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def _audio_transport(selections: int = 1) -> RouterTransport:
    """The frozen spec's test seam: every HTTP answer scripted in memory.

    ``selections`` is how many separate ``download-audio`` runs this transport
    has to serve: each one builds its own client, so each one bootstraps the
    session (``finger/spi``, ``nav``) before it asks for a playurl.  A call the
    case did not script raises instead of answering, which is why an exhausted
    route is a test failure rather than a silent empty answer.
    """

    return RouterTransport(
        {
            "finger/spi": [SPI_OK for _ in range(selections)],
            "nav": [nav_response() for _ in range(selections)],
            "/x/player/wbi/playurl": [playurl_ok() for _ in range(selections)],
        },
        stream_routes={f"{STREAM_HOST}/a30216.m4s": AUDIO_BYTES},
    )


def _playurl_cids(transport: RouterTransport) -> list[int]:
    """The ``cid`` each playurl call was signed for, in issue order."""

    return [
        call["params"]["cid"]
        for call in transport.calls
        if "playurl" in call["url"]
    ]


def _harvest_the_captionless_parts(
    root: str, gateway: FakeGateway, *, cids: tuple[int, ...]
) -> None:
    """Record the fixture's captionless parts through the shipping harvest path.

    Fixture F's captionless class is the part ``harvest-subs`` attempted and
    found no caption for, so the fixture runs the command instead of writing the
    store's attempt tables by hand: the gateway double answers an empty track
    inventory for these cids and the real service records the ``no-subtitle``
    attempt.
    """

    for cid in cids:
        gateway.script_subtitle_tracks(cid, ())
    assert (
        main(
            [
                "harvest-subs",
                "--limit-parts",
                str(len(cids)),
                "--archive-root",
                root,
            ]
        )
        == 0
    )


def _part_attempt_outcomes(root: str, bvid: str, page_index: int) -> list[str]:
    """The harvest path's recorded outcomes for one part, in issue order.

    This is the fixture's provenance check: a captionless part in the store is a
    part ``harvest-subs`` attempted and answered ``no-subtitle`` for — not a part
    the test wrote into the queue's tables by hand.
    """

    with _archive_connection(root) as connection:
        return [
            str(row["outcome"])
            for row in connection.execute(
                "SELECT a.outcome FROM acquisition_attempts AS a "
                "JOIN video_parts AS vp ON vp.video_part_id = a.video_part_id "
                "WHERE vp.bvid = ? AND vp.page_index = ? ORDER BY a.started_at",
                (bvid, page_index),
            )
        ]


def _part_transcript_count(root: str, bvid: str, page_index: int) -> int:
    """How many transcripts the store holds for one part."""

    with _archive_connection(root) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM transcripts AS t JOIN video_parts AS vp "
                "ON vp.video_part_id = t.video_part_id "
                "WHERE vp.bvid = ? AND vp.page_index = ?",
                (bvid, page_index),
            ).fetchone()[0]
        )


def _derived_row(root: str, work_id: str) -> dict:
    """The effective manifest row for one ``work_id`` (what the chain reads)."""

    return ManifestStore(root=root).load()[work_id]


def _stem(root: str, work_id: str) -> str:
    """The artifact stem the chain derives from one manifest row."""

    return artifact_stem(identity_from_entry(_derived_row(root, work_id), work_id))


def _put_audio_on_disk(root: str, work_id: str) -> str:
    """Place the derived row's audio artifact where the chain looks for it."""

    audio_dir = os.path.join(root, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    path = os.path.join(audio_dir, f"{_stem(root, work_id)}.m4a")
    with open(path, "wb") as handle:
        handle.write(AUDIO_BYTES)
    return path


def _asr_stack_is_installed() -> bool:
    """Whether the optional ``[asr]`` extra is importable in this environment.

    ``transformers`` is the marker: Qwen3-ASR has native support in it, and the boundary imports it
    (with torch, accelerate and the audio readers) only when a runner first transcribes.
    """

    return importlib.util.find_spec("transformers") is not None


def _attempts(root: str) -> list[dict]:
    """Every attempt record the run left in ``coordinator/attempts.jsonl``."""

    return AttemptLedger(root).load()


def test_a_derived_row_is_selected_by_missing_subs_and_attempts_that_work_id(
    tmp_root, monkeypatch, capsys, fake_gateway_seam
):
    """Criterion 2: the harvest-recorded captionless part reaches the audio path."""

    _forbid_sockets(monkeypatch)
    _seed_archive(tmp_root, CHAIN_FIXTURE, captioned=CAPTIONED_PARTS)
    _harvest_the_captionless_parts(tmp_root, fake_gateway_seam, cids=QUEUED_PART_CIDS)
    capsys.readouterr()

    assert _derive(tmp_root) == 0
    capsys.readouterr()

    # The fixture is what this case claims it is: the bridged row is the part
    # the harvest path answered `no-subtitle` for, `needs_audio` with the
    # store's duration in seconds, and the captioned part is not in the manifest
    # at all.
    rows = ManifestStore(root=tmp_root).load()
    assert set(rows) == {QUEUED_WORK_ID}
    assert rows[QUEUED_WORK_ID]["status"] == "needs_audio"
    assert rows[QUEUED_WORK_ID]["duration_s"] == QUEUED_DURATION_MS // 1000
    assert (
        _part_attempt_outcomes(tmp_root, QUEUED_BVID, QUEUED_PAGE_INDEX)
        == ["no-subtitle"]
    )
    assert _part_transcript_count(tmp_root, CAPTIONED_BVID, 0) == 1

    transport = _audio_transport()
    _patch_cli(monkeypatch, transport)

    assert (
        main(
            [
                "download-audio",
                "--missing-subs",
                "--limit",
                "1",
                "--archive-root",
                tmp_root,
            ]
        )
        == 0
    )
    captured = capsys.readouterr()

    # The shipped "nothing was selected" line must not appear: the derived row
    # is selected, and the one attempt is signed for that part's stored cid.
    assert NO_NEEDS_AUDIO_LINE not in captured.out
    assert captured.out.splitlines() == [
        f"{QUEUED_WORK_ID}: audio downloaded -> audio_ok "
        f"(audio/{_stem(tmp_root, QUEUED_WORK_ID)}.m4a)",
        "download-audio: 1 audio_ok",
    ]
    assert _playurl_cids(transport) == [QUEUED_CID]
    # The row carries its cid, so no page resolution was needed (spec §3.1).
    assert [c for c in transport.calls if "player/wbi/v2" in c["url"]] == []
    assert _derived_row(tmp_root, QUEUED_WORK_ID)["status"] == "audio_ok"
    assert os.path.isfile(
        os.path.join(tmp_root, "audio", f"{_stem(tmp_root, QUEUED_WORK_ID)}.m4a")
    )


def test_a_derived_queue_runs_to_archived_without_missing_subtitle_raw(
    tmp_root, monkeypatch, capsys, fake_gateway_seam
):
    """Criterion 3: the derived row is consumed by the chain, with no trap."""

    _forbid_sockets(monkeypatch)
    _seed_archive(tmp_root, CHAIN_FIXTURE, captioned=CAPTIONED_PARTS)
    _harvest_the_captionless_parts(tmp_root, fake_gateway_seam, cids=QUEUED_PART_CIDS)
    capsys.readouterr()

    assert _derive(tmp_root) == 0
    capsys.readouterr()
    assert _derived_row(tmp_root, QUEUED_WORK_ID)["status"] == "needs_audio"

    audio_path = _put_audio_on_disk(tmp_root, QUEUED_WORK_ID)
    assert os.path.getsize(audio_path) > 0
    transcribe_calls: list[str] = []
    _stub_asr(monkeypatch, transcribe_calls)
    # `--offline` builds no client at all; this transport would raise if one
    # were built and used, and the assertions below read back that it was not.
    transport = RouterTransport({})
    _patch_cli(monkeypatch, transport)

    assert (
        main(["run", "--scope", "pending", "--offline", "--archive-root", tmp_root])
        == 0
    )
    captured = capsys.readouterr()

    assert captured.out.splitlines() == [
        "run: scope=pending selected 1 row(s) [offline]",
        f"  {QUEUED_WORK_ID}: needs_audio",
        f"{QUEUED_WORK_ID}: archived",
        "run: 1 completed, 0 skipped",
    ]
    assert transport.calls == [] and transport.stream_calls == []
    # The ASR stage really ran: the stubbed runner transcribed the artifact the
    # fixture placed for the derived row.
    assert len(transcribe_calls) == 1
    assert _derived_row(tmp_root, QUEUED_WORK_ID)["status"] == "archived"

    attempts = _attempts(tmp_root)
    assert [(record["stage"], record["outcome"]) for record in attempts] == [
        ("asr", "ok"),
        ("archive", "ok"),
    ]
    # Spec §4's invariant, read from the ledger the chain itself writes.  Case 3
    # below is the control that makes this filter live: no reachable input makes
    # this assertion fail on its own.
    assert [r for r in attempts if r["error_code"] == MISSING_SUBTITLE_RAW] == []


def test_a_chain_held_subtitle_done_row_without_its_raw_document_skips(
    tmp_root, monkeypatch, capsys, fake_gateway_seam
):
    """The negative control: the ``missing_subtitle_raw`` code is producible (case 3).

    The same fixture plus one hand-written ``subtitle_done`` row for the part
    whose caption the store holds: the chain's archive stage reads the segments
    from ``subtitles/raw/{stem}.json``, that document was never written, and the
    run records exactly the code the derived row must never carry.  This is the
    state spec §3.3 makes structurally impossible for a derived row, so the filter
    the case above applies is live rather than vacuous.
    """

    _forbid_sockets(monkeypatch)
    _seed_archive(tmp_root, CHAIN_FIXTURE, captioned=CAPTIONED_PARTS)
    _harvest_the_captionless_parts(tmp_root, fake_gateway_seam, cids=QUEUED_PART_CIDS)
    capsys.readouterr()
    store = ManifestStore(root=tmp_root)
    store.load()
    store.upsert(
        _row(
            identity_from_entry(
                {"work_id": CAPTIONED_WORK_ID, "bvid": CAPTIONED_BVID,
                 "page_index": 0, "cid": CAPTIONED_CID},
                CAPTIONED_WORK_ID,
            ),
            status="subtitle_done",
            title="stored caption, no raw document",
        )
    )

    assert _derive(tmp_root) == 0
    capsys.readouterr()

    # The trap's two preconditions: the caption is *in the store*, and no raw
    # document exists on the filesystem for the chain's archive stage to read.
    assert _part_transcript_count(tmp_root, CAPTIONED_BVID, 0) == 1
    raw_path = os.path.join(
        tmp_root, "subtitles", "raw", f"{_stem(tmp_root, CAPTIONED_WORK_ID)}.json"
    )
    assert not os.path.exists(raw_path)

    _put_audio_on_disk(tmp_root, QUEUED_WORK_ID)
    _stub_asr(monkeypatch)
    transport = RouterTransport({})
    _patch_cli(monkeypatch, transport)

    assert (
        main(["run", "--scope", "pending", "--offline", "--archive-root", tmp_root])
        == 1
    )
    capsys.readouterr()
    assert transport.calls == [] and transport.stream_calls == []

    attempts = _attempts(tmp_root)
    assert [
        (r["work_id"], r["stage"], r["outcome"], r["error_code"])
        for r in attempts
        if r["error_code"] == MISSING_SUBTITLE_RAW
    ] == [(CAPTIONED_WORK_ID, "archive", "skipped", MISSING_SUBTITLE_RAW)]
    # The chain-held row did not advance, and the derived row in the same run
    # did — the contrast the invariant rests on.
    loaded = ManifestStore(root=tmp_root).load()
    assert loaded[CAPTIONED_WORK_ID]["status"] == "subtitle_done"
    assert loaded[QUEUED_WORK_ID]["status"] == "archived"


def test_a_second_bounded_selection_rotates_past_the_attempted_part(
    tmp_root, monkeypatch, capsys
):
    """Criterion 6, preserved half: a successful attempt advances the queue."""

    _forbid_sockets(monkeypatch)
    _seed_archive(tmp_root, ROTATION_FIXTURE)
    assert _derive(tmp_root) == 0
    capsys.readouterr()

    # The bridge appended the queue in the store's locked order, so the two
    # bounded selections below have a head to rotate away from.
    assert list(ManifestStore(root=tmp_root).load()) == list(ROTATION_WORK_IDS)

    transport = _audio_transport(selections=2)
    _patch_cli(monkeypatch, transport)

    for _selection in range(2):
        assert (
            main(
                [
                    "download-audio",
                    "--missing-subs",
                    "--queue-source",
                    "manifest",
                    "--limit",
                    "1",
                    "--archive-root",
                    tmp_root,
                ]
            )
            == 0
        )
        capsys.readouterr()

    # Two selections, two different parts, in the queue's own order: the row the
    # first one advanced left `needs_audio`, so the second could not see it.
    assert _playurl_cids(transport) == list(ROTATION_CIDS)
    loaded = ManifestStore(root=tmp_root).load()
    assert [loaded[work_id]["status"] for work_id in ROTATION_WORK_IDS] == [
        "audio_ok",
        "audio_ok",
    ]


def test_a_budget_capped_run_downloads_nothing_and_leaves_the_head_queued(
    tmp_root, monkeypatch, capsys, fake_gateway_seam
):
    """Criterion 6, lost half: the chain's own local skip, hit before any HTTP.

    The audio budget is the mechanism the chain itself offers for skipping a
    ``needs_audio`` row locally (``audio_budget.would_exceed_budget``, checked in
    ``RunCoordinator._stage_download`` before the client is touched).  With a cap
    no duration can fit, the attempt is recorded as a skip with **zero**
    transport activity — no socket, no download — and the row stays where the
    bridge put it, because a skipped attempt leaves no recency anywhere (spec §5
    decision 4, the residual the compass registers).  The second half of the case
    demonstrates that loss: the next bounded selection proposes the same head.
    """

    _forbid_sockets(monkeypatch)
    _seed_archive(tmp_root, CHAIN_FIXTURE, captioned=CAPTIONED_PARTS)
    _harvest_the_captionless_parts(tmp_root, fake_gateway_seam, cids=QUEUED_PART_CIDS)
    capsys.readouterr()
    assert _derive(tmp_root) == 0
    capsys.readouterr()

    # Nothing is scripted: any transport use would raise, and the assertions
    # below read back that there was none.
    transport = RouterTransport({})
    _patch_cli(monkeypatch, transport)

    assert (
        main(
            [
                "run",
                "--scope",
                "pending",
                "--max-audio-gb",
                "1e-09",
                "--archive-root",
                tmp_root,
            ]
        )
        == 1
    )
    captured = capsys.readouterr()

    assert transport.calls == [] and transport.stream_calls == []
    assert f"run: {QUEUED_WORK_ID}: skipped ({AUDIO_BUDGET_SKIP})" in captured.out
    assert [
        (r["stage"], r["outcome"], r["error_code"]) for r in _attempts(tmp_root)
    ] == [("download", "skipped", AUDIO_BUDGET_SKIP)]
    assert _derived_row(tmp_root, QUEUED_WORK_ID)["status"] == "needs_audio"

    # The recorded loss: the skipped row is still the queue's head, so the next
    # bounded selection proposes it again rather than rotating away.
    reselected = _audio_transport()
    _patch_cli(monkeypatch, reselected)
    assert (
        main(
            [
                "download-audio",
                "--missing-subs",
                "--limit",
                "1",
                "--archive-root",
                tmp_root,
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert _playurl_cids(reselected) == [QUEUED_CID]
    assert _derived_row(tmp_root, QUEUED_WORK_ID)["status"] == "audio_ok"


@pytest.mark.skipif(
    _asr_stack_is_installed(),
    reason=ASR_EXTRA_INSTALLED,
)
def test_a_stub_free_run_stops_at_the_documented_asr_dependency(
    tmp_root, monkeypatch, capsys, fake_gateway_seam
):
    """Without the extra, the derived row reaches the ASR stage and stops there.

    No ASR stub: the runner builds its real model factory, the ``transformers`` import
    fails, and the stage records the dependency code the product documents
    (``asr._INSTALL_HINT``).  The observable that matters here is that the
    derived row reached the **ASR** stage at all — the archive stage stays clean
    — and that the run does not report it archived.
    """

    _forbid_sockets(monkeypatch)
    _seed_archive(tmp_root, CHAIN_FIXTURE, captioned=CAPTIONED_PARTS)
    _harvest_the_captionless_parts(tmp_root, fake_gateway_seam, cids=QUEUED_PART_CIDS)
    capsys.readouterr()
    assert _derive(tmp_root) == 0
    capsys.readouterr()

    _put_audio_on_disk(tmp_root, QUEUED_WORK_ID)
    transport = RouterTransport({})
    _patch_cli(monkeypatch, transport)

    rc = main(["run", "--scope", "pending", "--offline", "--archive-root", tmp_root])
    captured = capsys.readouterr()

    assert rc != 0
    assert transport.calls == [] and transport.stream_calls == []
    attempts = _attempts(tmp_root)
    assert [(r["stage"], r["outcome"], r["error_code"]) for r in attempts] == [
        ("asr", "failed", "ASRDependencyError")
    ]
    assert f"run: {QUEUED_WORK_ID}: failed (ASRDependencyError)" in captured.err
    assert _derived_row(tmp_root, QUEUED_WORK_ID)["status"] == "needs_audio"


def test_the_live_run_with_the_real_asr_model_is_untested_here():
    """Criterion 3's live clause, recorded as untested rather than passed.

    The compass's criterion 3 names an opt-in live confirmation — a real model
    reaching ``"status":"archived"`` for the derived part — and states that
    without the optional extra the run stops at the ASR stage's documented
    install-hint failure and that step is reported untested.  This case is that
    record: it can never silently pass, and it states the environment fact it
    rests on instead of leaving the gap to prose.
    """

    pytest.skip(
        "the [asr] extra is not installed in this environment "
        f"(transformers importable: {_asr_stack_is_installed()}), and a real model would "
        "also need the network this file must not touch; the stubbed-run cases "
        "are criterion 3's gate evidence, and the live confirmation is untested, "
        "not passed"
    )
