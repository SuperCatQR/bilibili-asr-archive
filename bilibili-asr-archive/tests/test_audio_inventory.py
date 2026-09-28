"""Offline tests for ``derive-audio-inventory`` — the audio inventory walk.

The four counters this covers are **product rulings**, defined in
``specs/audio-retention-contract.md`` §3.1, and this file is their executable
form.  Every fixture is offline: the audio tree is built under ``tmp_root`` and
no test touches a real corpus root.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from bili_asr.artifact_root import roots_for
from bili_asr.cli import main
from bili_asr.services.audio_inventory import (
    ACQUISITION_SOURCE,
    AudioInventoryOutcome,
    reconcile_audio_inventory,
)
from bili_asr.storage import MediaQueueRepository, open_database

_AUDIO_BYTES = b"fake m4a payload for a streamed digest"


def _sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _insert_user_video_part(
    connection, *, bvid: str = "BV1TEST", page_index: int = 0
) -> int:
    # The user row is shared: `mid` is a primary key, so a second call for
    # another page of the same uploader must not try to insert it twice.
    existing = connection.execute(
        "SELECT COUNT(*) FROM bilibili_users WHERE mid = ?", (23191782,)
    ).fetchone()[0]
    if not existing:
        connection.execute(
            "INSERT INTO bilibili_users(mid, display_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (23191782, "未明子", 100, 100),
        )
    if not connection.execute(
        "SELECT COUNT(*) FROM videos WHERE bvid = ?", (bvid,)
    ).fetchone()[0]:
        connection.execute(
            "INSERT INTO videos(bvid, aid, mid, title, pubdate, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            # `aid` is UNIQUE too, so it is derived from the bvid rather than a
            # constant: several videos share this fixture's uploader.
            (bvid, abs(hash(bvid)) % 10**9, 23191782, "视频", 1_700_000_000, 101, 101),
        )
    cursor = connection.execute(
        """
        INSERT INTO video_parts(
            bvid, page_index, cid, title, duration_ms, processing_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bvid, page_index, 2001 + page_index, "第一段", 1_234, "discovered", 102, 102),
    )
    return int(cursor.lastrowid)


def _write_audio(root: Path, declared: str, data: bytes = _AUDIO_BYTES) -> None:
    """Materialise one declared audio path under ``root``."""
    target = root / declared
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _stored_object(connection, storage_key: str):
    return connection.execute(
        "SELECT audio_id, sha256, byte_size, format FROM audio_objects "
        "WHERE storage_key = ?",
        (storage_key,),
    ).fetchone()


# --------------------------------------------------------------------------
# §3.1's four counters
# --------------------------------------------------------------------------


def test_derivation_records_present_audio_and_reports_absent_audio(tmp_root):
    """The four counters are distinct, and their meanings are the spec's (§3.1).

    ``recorded`` / ``already`` / ``missing`` / ``unlinked`` are defined in
    ``specs/audio-retention-contract.md`` §3.1; this test is their executable
    form.  ``missing`` is *named-but-absent* (the shipped reclaim path and a
    manual delete both produce it): the command must say the row names a file
    that is not there, not invent one and not delete the row.  ``unlinked`` is
    the object no ``part_audio_objects`` row attributes to a part.
    """
    root = Path(tmp_root)
    connection = open_database(tmp_root)
    repository = MediaQueueRepository(connection)
    try:
        _insert_user_video_part(connection, bvid="BV1PRESENT", page_index=0)
        _insert_user_video_part(connection, bvid="BV1ABSENT", page_index=0)
        _insert_user_video_part(connection, bvid="BV1ORPHAN", page_index=0)

        _write_audio(root, "audio/BV1PRESENT.p0.m4a")
        # BV1ABSENT names a file that is not on disk at all.
        # An object no link attributes to a part: the `unlinked` observation.
        connection.execute(
            "INSERT INTO audio_objects(sha256, byte_size, format, duration_ms, "
            "storage_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("c" * 64, 7, "m4a", 0, "audio/BV1ORPHAN.p0.m4a", 1),
        )
        connection.commit()

        outcome = reconcile_audio_inventory(
            roots=roots_for(tmp_root),
            entries={
                "BV1PRESENT:p0": {"audio_path": "audio/BV1PRESENT.p0.m4a"},
                "BV1ABSENT:p0": {"audio_path": "audio/BV1ABSENT.p0.m4a"},
            },
            known_storage_keys=repository.read_audio_object_keys(),
            known_audio_ids=repository.read_audio_object_ids(),
            linked_audio_ids=repository.read_linked_audio_ids(),
            record=repository.mark_audio_acquired,
            moment=500,
        )
    finally:
        connection.close()

    assert outcome.recorded == 1, "the present file is recorded"
    assert outcome.already == 0, "nothing was already known"
    assert outcome.missing == 1, "the named-but-absent row is reported"
    assert outcome.unlinked == 1, "the orphan object has no part link"

    # `missing` never invents: no row exists for the absent candidate, and the
    # absent row was not deleted because there was nothing to delete.
    connection = open_database(tmp_root)
    try:
        assert _stored_object(connection, "audio/BV1ABSENT.p0.m4a") is None
        stored = _stored_object(connection, "audio/BV1PRESENT.p0.m4a")
        assert stored is not None
        assert stored["sha256"] == _sha256_of(_AUDIO_BYTES)
        assert stored["byte_size"] == len(_AUDIO_BYTES)
        assert stored["format"] == "m4a"
        link = connection.execute(
            "SELECT COUNT(*) FROM part_audio_objects WHERE audio_id = ?",
            (int(stored["audio_id"]),),
        ).fetchone()[0]
        assert link == 1, "the recorded object is attributed to its part"
    finally:
        connection.close()


def test_a_second_run_converges_instead_of_accumulating(tmp_root):
    """A re-run increments ``already``; it never writes a second row (§3.1).

    Also pins the ``--deep`` ruling: a run **without** ``--deep`` records a row
    **with** a correct digest, because digesting is not optional — ``sha256`` is
    ``NOT NULL UNIQUE``, so a row without one cannot be deduplicated.  ``--deep``
    re-verifies the digest of a row that is already present; it is not a
    "hash or don't" switch.
    """
    root = Path(tmp_root)
    _write_audio(root, "audio/BV1TWICE.p0.m4a")

    connection = open_database(tmp_root)
    repository = MediaQueueRepository(connection)
    try:
        _insert_user_video_part(connection, bvid="BV1TWICE", page_index=0)
        connection.commit()
        entries = {"BV1TWICE:p0": {"audio_path": "audio/BV1TWICE.p0.m4a"}}
        roots = roots_for(tmp_root)

        first = reconcile_audio_inventory(
            roots=roots,
            entries=entries,
            known_storage_keys=repository.read_audio_object_keys(),
            known_audio_ids=repository.read_audio_object_ids(),
            linked_audio_ids=repository.read_linked_audio_ids(),
            record=repository.mark_audio_acquired,
            moment=500,
        )
        assert (first.recorded, first.already) == (1, 0)

        stored = _stored_object(connection, "audio/BV1TWICE.p0.m4a")
        assert stored is not None
        assert stored["sha256"] == _sha256_of(_AUDIO_BYTES), (
            "a run without --deep still records a real digest"
        )

        second = reconcile_audio_inventory(
            roots=roots,
            entries=entries,
            known_storage_keys=repository.read_audio_object_keys(),
            known_audio_ids=repository.read_audio_object_ids(),
            linked_audio_ids=repository.read_linked_audio_ids(),
            record=repository.mark_audio_acquired,
            moment=900,
        )
        assert (second.recorded, second.already) == (0, 1), "the re-run converges"

        count = connection.execute(
            "SELECT COUNT(*) FROM audio_objects WHERE storage_key = ?",
            ("audio/BV1TWICE.p0.m4a",),
        ).fetchone()[0]
        assert count == 1, "never a second row for one object"

        # --deep re-verifies a row that is already present.
        deep = reconcile_audio_inventory(
            roots=roots,
            entries=entries,
            known_storage_keys=repository.read_audio_object_keys(),
            known_audio_ids=repository.read_audio_object_ids(),
            linked_audio_ids=repository.read_linked_audio_ids(),
            record=repository.mark_audio_acquired,
            moment=1200,
            deep=True,
        )
        assert (deep.recorded, deep.already) == (0, 1)
    finally:
        connection.close()


def test_a_known_row_costs_no_file_read_without_deep(tmp_root, monkeypatch):
    """The plan's cost model, pinned: zero reads for an already-recorded row.

    ``## Task 2`` is explicit — *"one streamed read per newly recorded file;
    zero file reads for a candidate whose ``storage_key`` already has a row and
    is not passed to ``--deep``"*.  The digest is not optional (``sha256`` is
    ``NOT NULL UNIQUE``), so a naive implementation digests first and asks about
    the row afterwards, which pays a read per known row on every re-run over an
    unchanged corpus.  This test is what keeps the check on the near side of the
    read: it counts the bytes actually read from the audio file.
    """
    root = Path(tmp_root)
    _write_audio(root, "audio/BV1COST.p0.m4a")
    connection = open_database(tmp_root)
    repository = MediaQueueRepository(connection)
    try:
        _insert_user_video_part(connection, bvid="BV1COST", page_index=0)
        connection.commit()

        import bili_asr.services.audio_inventory as module

        reads = {"count": 0}
        real_read = module._digest_and_size

        def counting_digest(path):
            reads["count"] += 1
            return real_read(path)

        monkeypatch.setattr(module, "_digest_and_size", counting_digest)
        entries = {"BV1COST:p0": {"audio_path": "audio/BV1COST.p0.m4a"}}
        roots = roots_for(tmp_root)

        def run(moment, deep=False):
            return module.reconcile_audio_inventory(
                roots=roots,
                entries=entries,
                known_storage_keys=repository.read_audio_object_keys(),
                known_audio_ids=repository.read_audio_object_ids(),
                linked_audio_ids=repository.read_linked_audio_ids(),
                record=repository.mark_audio_acquired,
                moment=moment,
                deep=deep,
            )

        first = run(500)
        assert (first.recorded, reads["count"]) == (1, 1), "a new file is read once"

        reads["count"] = 0
        second = run(900)
        assert (second.already, reads["count"]) == (1, 0), (
            "an already-recorded row costs no read without --deep"
        )

        reads["count"] = 0
        deep = run(1200, deep=True)
        assert (deep.already, reads["count"]) == (1, 1), (
            "--deep re-verifies the digest of a row that is already present"
        )
    finally:
        connection.close()


def test_a_row_that_names_no_audio_path_is_not_a_candidate(tmp_root):
    """``missing`` counts rows that *name* a file — silence is not absence.

    A manifest row without ``audio_path`` neither records nor reports: it never
    declared audio, so calling it ``missing`` would invent a candidate the
    archive never held.
    """
    connection = open_database(tmp_root)
    repository = MediaQueueRepository(connection)
    try:
        _insert_user_video_part(connection, bvid="BV1SILENT", page_index=0)
        connection.commit()
        outcome = reconcile_audio_inventory(
            roots=roots_for(tmp_root),
            entries={"BV1SILENT:p0": {"audio_path": None}},
            known_storage_keys=repository.read_audio_object_keys(),
            known_audio_ids=repository.read_audio_object_ids(),
            linked_audio_ids=repository.read_linked_audio_ids(),
            record=repository.mark_audio_acquired,
            moment=500,
        )
    finally:
        connection.close()

    assert (outcome.recorded, outcome.already, outcome.missing) == (0, 0, 0)


def test_missing_reports_the_absence_without_touching_the_store(tmp_root):
    """The reclaim path's leftover: a named file is gone, the row is reported.

    This is the shipped reclaim scenario — the row still names an ``audio_path``
    whose file was unlinked.  The command must report it, must not invent a row
    from nothing, and must not delete anything.
    """
    connection = open_database(tmp_root)
    repository = MediaQueueRepository(connection)
    try:
        _insert_user_video_part(connection, bvid="BV1GONE", page_index=0)
        repository.mark_audio_acquired(
            bvid="BV1GONE",
            page_index=0,
            audio_path="audio/BV1GONE.p0.m4a",
            sha256="d" * 64,
            byte_size=11,
            format="m4a",
            duration_ms=1234,
            acquisition_source="download-audio",
            acquired_at=100,
        )
        before = (
            connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0],
        )

        outcome = reconcile_audio_inventory(
            roots=roots_for(tmp_root),
            entries={"BV1GONE:p0": {"audio_path": "audio/BV1GONE.p0.m4a"}},
            known_storage_keys=repository.read_audio_object_keys(),
            known_audio_ids=repository.read_audio_object_ids(),
            linked_audio_ids=repository.read_linked_audio_ids(),
            record=repository.mark_audio_acquired,
            moment=500,
        )
        after = (
            connection.execute("SELECT COUNT(*) FROM audio_objects").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0],
        )
    finally:
        connection.close()

    assert outcome.missing == 1
    assert (outcome.recorded, outcome.already) == (0, 0)
    assert after == before, "no row invented and none deleted"


# --------------------------------------------------------------------------
# The command surface: one summary line, exit 0 on an empty reconciliation
# --------------------------------------------------------------------------


def test_the_command_prints_one_summary_line_with_all_four_counters(tmp_root, capsys):
    root = Path(tmp_root)
    _write_audio(root, "audio/BV1CLI.p0.m4a")
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection, bvid="BV1CLI", page_index=0)
        connection.commit()
    finally:
        connection.close()

    from bili_asr.manifest import ManifestStore

    ManifestStore(root=tmp_root).upsert(
        {
            "work_id": "BV1CLI:p0",
            "bvid": "BV1CLI",
            "audio_path": "audio/BV1CLI.p0.m4a",
            "status": "needs_audio",
        }
    )

    code = main(["derive-audio-inventory", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert code == 0
    summary = [
        line for line in captured.out.splitlines()
        if line.startswith("derive-audio-inventory: ")
    ]
    assert len(summary) == 1, "§3.1's one summary line"
    assert summary[0] == (
        "derive-audio-inventory: recorded=1 already=0 missing=0 unlinked=0"
    )


def test_an_empty_reconciliation_exits_zero(tmp_root, capsys):
    """An empty result is success, matching ``derive-manifest`` (§ Interfaces)."""
    connection = open_database(tmp_root)
    try:
        pass
    finally:
        connection.close()

    code = main(["derive-audio-inventory", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert code == 0
    assert (
        "derive-audio-inventory: recorded=0 already=0 missing=0 unlinked=0"
        in captured.out
    )


def test_the_summary_line_is_the_contracts_field_order():
    """The line is a contract, not a naming exercise (§3.1)."""
    assert AudioInventoryOutcome(1, 2, 3, 4).summary_line() == (
        "derive-audio-inventory: recorded=1 already=2 missing=3 unlinked=4"
    )
    assert ACQUISITION_SOURCE == "derive-audio-inventory"
