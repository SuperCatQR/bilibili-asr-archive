'Offline contract tests for ``bili-asr derive-manifest`` (spec §8).\n\nEverything here is offline.  The command is driven end to end through\n``bili_asr.cli.main.main`` — argparse, the read-only store connection, the\ntranscript-schema guard, ``TranscriptRepository``, the derivation service and\n``ManifestStore`` — against a temporary archive database, so no network call is\nmade and no live corpus is touched.\n\nWhat is pinned: the queue the command derives (the store\'s captionless parts,\nnever the metadata backlog), the row it appends (page-qualified ``work_id``,\n``needs_audio``, seconds duration, the part\'s own cid), the additive conflict\npolicy (a chain-held row is never regressed, a second run appends nothing), the\nexit taxonomy (``0`` including "nothing to derive", ``1`` for a missing\ndatabase, for a held writer lock and for an append that fails part-way through\nthe row loop), the printed lines and the summary, and the\ntwo boundaries the contract rests on — nothing is materialised, and the command\njoins the archive-writer lock set rather than inventing its own.\n\nThe store fixture is built through the repository APIs only: no test here writes\nraw SQL into ``archive.db``.\n'

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import os
import sqlite3
import threading
import time

from bili_asr.cli.main import main
from bili_asr.config import ARCHIVE_DATABASE_NAME
from bili_asr.pipeline.locks import ARCHIVE_WRITER_LOCK
from bili_asr.manifest import JOURNAL_NAME, ManifestStore
from bili_asr.persistence import file_lock
from bili_asr.storage import (
    AcquisitionRunRecord,
    MetadataRepository,
    TranscriptRepository,
    TranscriptSegmentRecord,
    open_database,
)
from tests.fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)
from tests.support.cli_derive_manifest import _archive_connection, _derive, _exit_code, _record_caption, _seed_archive

QUEUED_BVID = "BV1QUEUED"
CAPTIONED_BVID = "BV1CAPTION"
GONE_BVID = "BV1GONE"

#: ``(bvid, page_index, cid, duration_ms, processing_status)``: two captionless
#: pages of one video (the queue), one page that already holds a transcript, and
#: one upstream-reported gone.  The two durations make the seconds conversion
#: falsifiable: 3_600_500 floors to 3600 while 999 is clamped to 1, so a missing
#: floor and a missing clamp cannot both pass.
QUEUE_FIXTURE = (
    (QUEUED_BVID, 0, 3001, 3_600_500, "metadata_collected"),
    (QUEUED_BVID, 1, 3002, 999, "metadata_collected"),
    (CAPTIONED_BVID, 0, 2001, 1_234, "metadata_collected"),
    (GONE_BVID, 0, 4001, 1_234, "gone"),
)

CAPTIONED_PARTS = ((CAPTIONED_BVID, 0),)

MANIFEST_REL_PATH = os.path.join("manifest", "manifest.jsonl")
#: The manifest's own adjacent lock, shipped by ``ManifestStore``: every writer
#: of the file takes it, so it is part of the side effect set and not something
#: this command invents.
MANIFEST_LOCK_REL_PATH = MANIFEST_REL_PATH + ".lock"

#: The summary the command always prints, with every count at zero.
ZERO_SUMMARY = (
    "derive-manifest: queue=0 derived=0 already_derived=0 "
    "chain_owned=0 identity_mismatch=0"
)

#: The publication second ``fixtures.metadata_records`` stores for every video,
#: and its **UTC** calendar date — what the derived row carries.  The expectation
#: is rendered with ``gmtime`` rather than written as a literal, because a literal
#: only discriminated on a host whose own zone is not UTC.
PUBDATE = 1_700_000_000
PUBDATE_STR = time.strftime("%Y-%m-%d", time.gmtime(PUBDATE))

#: One second before the UTC date boundary — ``1970-01-01T23:59:59Z``, whose local
#: date is the 2nd at ``+08:00``.  The case at the end of this file seeds it as the
#: CLI's second anchor and asserts the literal ``1970-01-01``:
#: ``tests/test_manifest_derivation.py`` owns the argument for why a
#: ``gmtime``-derived expectation needs that anchor and that literal.
PUBDATE_UTC_DAY_EDGE = 86_399








def _archive_files(root: str) -> list[str]:
    """Every file below the archive root, as sorted relative POSIX paths."""
    return sorted(
        os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
        for directory, _directories, names in os.walk(root)
        for name in names
    )


def _manifest_lines(root: str) -> list[str]:
    """Read the durable snapshot and pending append journal without writing."""
    snapshot = os.path.join(root, MANIFEST_REL_PATH)
    journal = os.path.join(os.path.dirname(snapshot), JOURNAL_NAME)
    lines = []
    for path in (snapshot, journal):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                lines.extend(line for line in handle.read().splitlines() if line)
    return lines






def test_derive_manifest_exits_zero_with_nothing_to_derive(tmp_root, capsys):
    """An empty queue is success, not an error, and the summary carries the zeros."""
    _seed_archive(
        tmp_root,
        ((CAPTIONED_BVID, 0, 2001, 1_234, "metadata_collected"),),
        captioned=CAPTIONED_PARTS,
    )

    assert _derive(tmp_root) == 0
    captured = capsys.readouterr()

    assert captured.out == f"{ZERO_SUMMARY}\n"
    assert captured.err == ""
    # Nothing to derive is not a reason to create the manifest file.
    assert not os.path.exists(os.path.join(tmp_root, MANIFEST_REL_PATH))
    assert ManifestStore(root=tmp_root).load() == {}


def test_derive_manifest_appends_one_page_qualified_needs_audio_row_per_queue_part(
    tmp_root, capsys
):
    """The derived set is exactly the store's queue, one page-qualified row each."""
    _seed_archive(tmp_root, QUEUE_FIXTURE, captioned=CAPTIONED_PARTS)

    assert _derive(tmp_root) == 0
    captured = capsys.readouterr()

    with _archive_connection(tmp_root) as connection:
        expected = {
            (row["work_id"], row["cid"], row["duration_ms"])
            for row in connection.execute(
                "SELECT bvid || ':p' || page_index AS work_id, cid, duration_ms "
                "FROM v_pending_subtitles"
            )
        }
    # The fixture is what this case claims it is: the captioned part and the gone
    # part are not in the store's queue relation.
    assert expected == {
        (f"{QUEUED_BVID}:p0", 3001, 3_600_500),
        (f"{QUEUED_BVID}:p1", 3002, 999),
    }

    rows = ManifestStore(root=tmp_root).load()
    assert set(rows) == {work_id for work_id, _cid, _ms in expected}
    for work_id, cid, duration_ms in expected:
        row = rows[work_id]
        assert row["status"] == "needs_audio"
        assert row["duration_s"] == max(1, duration_ms // 1000)
        assert row["cid"] == cid
        assert row["bvid"] == QUEUED_BVID
        assert row["page_index"] == int(work_id.rsplit(":p", 1)[1])
        assert row["pubdate"] == PUBDATE
        assert row["pubdate_str"] == PUBDATE_STR
    assert rows[f"{QUEUED_BVID}:p0"]["duration_s"] == 3600
    assert rows[f"{QUEUED_BVID}:p1"]["duration_s"] == 1
    # Nothing was materialised below the archive root: no subtitles/raw/, no
    # audio/, no transcript projection — the whole side effect is the manifest,
    # its own lock, and the shipped archive-writer lock.
    assert _archive_files(tmp_root) == sorted(
        [
            "archive.db",
            ARCHIVE_WRITER_LOCK,
            MANIFEST_LOCK_REL_PATH,
            MANIFEST_REL_PATH,
        ]
    )

    assert captured.out.splitlines() == [
        f"{QUEUED_BVID}:p0: needs_audio (duration_s=3600)",
        f"{QUEUED_BVID}:p1: needs_audio (duration_s=1)",
        "derive-manifest: queue=2 derived=2 already_derived=0 "
        "chain_owned=0 identity_mismatch=0",
    ]
    assert captured.err == ""


def test_derive_manifest_renders_the_utc_day_not_the_runners_day(
    tmp_root, capsys, monkeypatch
):
    """The row's ``pubdate_str`` is the second's UTC date, on any runner.

    The expectation above is derived from ``gmtime``, which ignores ``TZ``, so on
    a UTC runner it holds the same string the old literal did and a ``localtime``
    regression passes there.  ``tests/test_manifest_derivation.py`` shows why no
    second epoch and no ``TZ`` pin closes that on every platform; this case takes
    the same route through the CLI — the module's ``gmtime`` and ``localtime`` are
    answered by fixed ``struct_time`` values one day apart — and asserts the
    literal UTC day, so a ``localtime`` rendering fails wherever the host sits.
    """
    from bili_asr.services import manifest_derivation

    _seed_archive(
        tmp_root,
        ((QUEUED_BVID, 0, 3001, 3_600_500, "metadata_collected"),),
        pubdates={QUEUED_BVID: PUBDATE_UTC_DAY_EDGE},
    )
    monkeypatch.setattr(
        manifest_derivation.time,
        "gmtime",
        lambda _epoch: time.struct_time((1970, 1, 1, 23, 59, 59, 3, 1, 0)),
    )
    monkeypatch.setattr(
        manifest_derivation.time,
        "localtime",
        lambda _epoch: time.struct_time((1970, 1, 2, 7, 59, 59, 4, 2, 0)),
    )

    assert _derive(tmp_root) == 0
    captured = capsys.readouterr()

    row = ManifestStore(root=tmp_root).load()[f"{QUEUED_BVID}:p0"]
    assert row["pubdate"] == PUBDATE_UTC_DAY_EDGE
    assert row["pubdate_str"] == "1970-01-01"
    assert captured.err == ""


def test_derive_manifest_is_idempotent_and_leaves_the_effective_state_unchanged(
    tmp_root, capsys
):
    """The second run decides on the effective state and appends nothing."""
    _seed_archive(tmp_root, QUEUE_FIXTURE, captioned=CAPTIONED_PARTS)

    assert _derive(tmp_root) == 0
    capsys.readouterr()
    before = ManifestStore(root=tmp_root).load()
    before_lines = _manifest_lines(tmp_root)
    assert before_lines

    assert _derive(tmp_root) == 0
    captured = capsys.readouterr()

    # The effective state is the last row per work_id, which is what the chain
    # reads — compared through the store, not as raw bytes.
    assert ManifestStore(root=tmp_root).load() == before
    assert _manifest_lines(tmp_root) == before_lines
    assert captured.out.splitlines() == [
        "derive-manifest: queue=2 derived=0 already_derived=2 "
        "chain_owned=0 identity_mismatch=0"
    ]

    # A third run over the same store makes the same decision.
    assert _derive(tmp_root) == 0
    assert ManifestStore(root=tmp_root).load() == before
    assert _manifest_lines(tmp_root) == before_lines


def test_derive_manifest_never_regresses_a_row_the_chain_advanced(tmp_root, capsys):
    """A row the chain already advanced is left byte-for-byte as found."""
    _seed_archive(tmp_root, QUEUE_FIXTURE, captioned=CAPTIONED_PARTS)
    advanced = {
        "work_id": f"{QUEUED_BVID}:p0",
        "bvid": QUEUED_BVID,
        "page_index": 0,
        "cid": 3001,
        "title": "第1集",
        "duration_s": 3600,
        "pubdate": 1_700_000_000,
        "pubdate_str": "2023-11-14",
        "status": "archived",
    }
    store = ManifestStore(root=tmp_root)
    store.load()
    store.upsert(advanced)
    assert len(_manifest_lines(tmp_root)) == 1

    assert _derive(tmp_root) == 0
    captured = capsys.readouterr()

    rows = ManifestStore(root=tmp_root).load()
    assert rows[f"{QUEUED_BVID}:p0"] == advanced
    assert rows[f"{QUEUED_BVID}:p1"]["status"] == "needs_audio"
    assert captured.out.splitlines() == [
        f"{QUEUED_BVID}:p1: needs_audio (duration_s=1)",
        f"skip {QUEUED_BVID}:p0 chain_owned",
        "derive-manifest: queue=2 derived=1 already_derived=0 "
        "chain_owned=1 identity_mismatch=0",
    ]
    # One line for the chain's own row and one for the derived sibling: the
    # command appended only where the chain had said nothing.
    assert len(_manifest_lines(tmp_root)) == 2


def test_a_failed_append_keeps_the_prefix_and_still_reports(tmp_root, capsys, monkeypatch):
    """A write that fails mid-loop keeps the summary and names the prefix.

    The data outcome is the designed one: the rows already appended are complete
    lines the chain can read, and a re-run answers ``already_derived`` for them.
    What an operator needs on that run is the report — the summary (with
    ``derived`` counting what actually reached the manifest) plus one
    command-specific line naming the count — instead of a bare traceback, and
    exit ``1``, the code this command reserves for a run that could not complete.
    """
    _seed_archive(tmp_root, QUEUE_FIXTURE, captioned=CAPTIONED_PARTS)
    real_upsert = ManifestStore.upsert
    attempts: list[str] = []

    def failing_upsert(self, entry):
        attempts.append(str(entry["work_id"]))
        if len(attempts) == 2:
            raise OSError("no space left on device")
        return real_upsert(self, entry)

    monkeypatch.setattr(ManifestStore, "upsert", failing_upsert)

    assert _derive(tmp_root) == 1
    captured = capsys.readouterr()

    # The prefix the write did reach is durable: one complete line, the first
    # queue row, and nothing for the row the failure stopped short of.
    assert len(_manifest_lines(tmp_root)) == 1
    assert list(ManifestStore(root=tmp_root).load()) == [f"{QUEUED_BVID}:p0"]

    assert captured.out == (
        f"{QUEUED_BVID}:p0: needs_audio (duration_s=3600)\n"
        "derive-manifest: queue=2 derived=1 already_derived=0 "
        "chain_owned=0 identity_mismatch=0\n"
    )
    assert captured.err == (
        "derive-manifest: append failed after 1 row(s): "
        "OSError: no space left on device\n"
    )


def test_derive_manifest_missing_database_is_a_configuration_error(tmp_root, capsys):
    """No database, no derivation: the shipped line, exit 1, nothing created."""
    assert _derive(tmp_root) == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == (
        f"derive-manifest: no archive database at {tmp_root}; "
        "run fetch-meta to create it\n"
    )
    # The command creates neither the database nor a manifest; only the shipped
    # writer lock's own directory is there, which is the documented side effect
    # of taking the root lock before running.
    assert _archive_files(tmp_root) == [ARCHIVE_WRITER_LOCK]


def test_derive_manifest_help_names_the_queue_not_the_metadata_backlog(capsys):
    """``--help`` exits 0 and names the parts with no transcript, never ``pending:``."""
    assert _exit_code(["derive-manifest", "--help"]) == 0
    captured = capsys.readouterr()

    # argparse rewraps the description to the terminal width, so the phrase is
    # asserted on the de-wrapped text: the requirement is that the help says
    # which set it derives, not where the line breaks fall.
    assert "no transcript" in " ".join(captured.out.split())
    assert "audio queue" in " ".join(captured.out.split())
    assert "--archive-root" in captured.out
    # The queue is the whole relation: no selector and no bound (§2), so no other
    # flag exists to print.
    assert "--limit" not in captured.out
    assert "--bvid" not in captured.out
    # ``pending:`` is ``status``'s metadata backlog (v_pending_metadata), a
    # different set this command must not be confused with.
    assert "pending:" not in captured.out


def test_derive_manifest_holds_the_archive_writer_lock(tmp_root, capsys):
    """It joins the archive-writer set; a held root lock refuses with ``archive_busy``."""
    _seed_archive(tmp_root, QUEUE_FIXTURE, captioned=CAPTIONED_PARTS)

    assert _derive(tmp_root) == 0
    capsys.readouterr()
    lock_path = os.path.join(tmp_root, ARCHIVE_WRITER_LOCK)
    assert os.path.isfile(lock_path)

    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        # ``archive_writer`` is reentrant within one thread, so the lock has to
        # be held from another one for the command to meet a busy archive.
        with file_lock(lock_path):
            held.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    try:
        assert held.wait(timeout=30)
        assert _derive(tmp_root) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "derive-manifest: archive_busy\n"
    finally:
        release.set()
        holder.join(timeout=30)
    assert not holder.is_alive()
