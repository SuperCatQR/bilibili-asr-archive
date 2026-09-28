"""Offline tests for ``derive-audio-inventory`` — the audio inventory walk.

The four counters this covers are **product rulings**, defined in
``specs/audio-retention-contract.md`` §3.1, and this file is their executable
form.  Every fixture is offline: the audio tree is built under ``tmp_root`` and
no test touches a real corpus root.

The second half pins the findings of the L2 review that returned ``Needs fixes``
— each case names the mutant it is built to kill, because a pin whose mutant
still passes is not a pin.
"""

from __future__ import annotations

import hashlib
import os
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
    connection, *, bvid: str = "BV1TEST", page_index: int = 0,
    duration_ms: int = 1_234,
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
        (bvid, page_index, 2001 + page_index, "第一段", duration_ms, "discovered", 102, 102),
    )
    return int(cursor.lastrowid)


def _write_audio(root: Path, declared: str, data: bytes = _AUDIO_BYTES) -> None:
    """Materialise one declared audio path under ``root``."""
    target = root / declared
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _stored_object(connection, storage_key: str):
    return connection.execute(
        "SELECT audio_id, sha256, byte_size, format, duration_ms FROM audio_objects "
        "WHERE storage_key = ?",
        (storage_key,),
    ).fetchone()


def _call(root, connection, entries, *, moment=500, deep=False, **overrides):
    """One reconciliation through the repository, with the shipped signature.

    The service takes its read sets as arguments so it stays pure; this helper is
    the single place which assembles them, so a signature change touches one line
    rather than every case.  ``overrides`` lets a case supply a doctored set (for
    example a stale ``byte_size``) without re-deriving the rest.
    """
    repository = MediaQueueRepository(connection)
    kwargs = dict(
        known_objects=repository.read_audio_objects(),
        known_audio_ids=repository.read_audio_object_ids(),
        linked_audio_ids=repository.read_linked_audio_ids(),
        part_durations=repository.read_part_durations(entries),
    )
    kwargs.update(overrides)
    return reconcile_audio_inventory(
        roots=roots_for(root),
        entries=entries,
        record=repository.mark_audio_acquired,
        moment=moment,
        deep=deep,
        **kwargs,
    )


# --------------------------------------------------------------------------
# §3.1's four counters
# --------------------------------------------------------------------------


def test_derivation_records_present_audio_and_reports_absent_audio(tmp_root):
    """The four counters are distinct, and their meanings are the spec's (§3.1).

    ``missing`` is *named-but-absent* (the shipped reclaim path and a manual
    delete both produce it): the command must say the row names a file that is
    not there, not invent one and not delete the row.  ``unlinked`` is the object
    no ``part_audio_objects`` row attributes to a part.
    """
    root = Path(tmp_root)
    connection = open_database(tmp_root)
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

        outcome = _call(
            tmp_root,
            connection,
            {
                "BV1PRESENT:p0": {"audio_path": "audio/BV1PRESENT.p0.m4a"},
                "BV1ABSENT:p0": {"audio_path": "audio/BV1ABSENT.p0.m4a"},
            },
        )

        assert outcome.recorded == 1, "the present file is recorded"
        assert outcome.already == 0, "nothing was already known"
        assert outcome.missing == 1, "the named-but-absent row is reported"
        assert outcome.unlinked == 1, "the orphan object has no part link"
        assert outcome.unreadable == (), "every readable file was read"

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


def test_the_recorded_duration_comes_from_the_store_not_the_manifest(tmp_root):
    """F6: the store's exact ``duration_ms``, never a floor of the manifest's.

    The manifest records whole **seconds** (``duration_s``) — its writers floor
    and clamp them — so reconstructing milliseconds from a manifest row loses the
    exact value.  The defect this pins: reading ``entry["duration_ms"]``, a key no
    shipped manifest writer emits, recorded ``0`` for **every** real row (the
    schema's "unknown"), and under ``--deep`` overwrote an existing real
    ``1234000`` with ``0``.

    Mutant that must fail: take the duration from the manifest row instead of the
    store — the exact-value assertions below go red.
    """
    root = Path(tmp_root)
    exact_ms = 1_234_567  # NOT representable in whole seconds: 1234 s → 1234000 ms
    _write_audio(root, "audio/BV1DUR.p0.m4a")

    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection, bvid="BV1DUR", page_index=0, duration_ms=exact_ms)
        connection.commit()
        entries = {
            "BV1DUR:p0": {
                "audio_path": "audio/BV1DUR.p0.m4a",
                # Exactly what a shipped writer records: whole seconds.
                "duration_s": exact_ms // 1000,
            }
        }

        first = _call(tmp_root, connection, entries)
        assert first.recorded == 1
        stored = _stored_object(connection, "audio/BV1DUR.p0.m4a")
        assert stored is not None
        assert int(stored["duration_ms"]) == exact_ms, (
            "the store's exact value, not 0 and not 1234000"
        )

        # The destructive arm: a second walk under --deep must not degrade it.
        second = _call(tmp_root, connection, entries, moment=900, deep=True)
        assert (second.recorded, second.already) == (0, 1)
        after = _stored_object(connection, "audio/BV1DUR.p0.m4a")
        assert int(after["duration_ms"]) == exact_ms, (
            "--deep must never overwrite a real duration with 0"
        )
    finally:
        connection.close()


def test_a_known_row_costs_no_file_read_without_deep(tmp_root, monkeypatch):
    """The cost model, pinned: zero reads for an already-recorded row.

    ``## Task 2`` is explicit — *"one streamed read per newly recorded file;
    zero file reads for a candidate whose ``storage_key`` already has a row and
    is not passed to ``--deep``"*.  A naive implementation digests first and asks
    about the row afterwards, which pays a read per known row on every re-run over
    an unchanged corpus.  F2's ``stat``-based "and matched" check must not
    reintroduce a read.
    """
    root = Path(tmp_root)
    _write_audio(root, "audio/BV1COST.p0.m4a")
    connection = open_database(tmp_root)
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

        first = _call(tmp_root, connection, entries)
        assert (first.recorded, reads["count"]) == (1, 1), "a new file is read once"

        reads["count"] = 0
        second = _call(tmp_root, connection, entries, moment=900)
        assert (second.already, reads["count"]) == (1, 0), (
            "an already-recorded row costs no read without --deep"
        )

        reads["count"] = 0
        deep = _call(tmp_root, connection, entries, moment=1200, deep=True)
        assert (deep.already, reads["count"]) == (1, 1), (
            "--deep re-verifies the digest of a row that is already present"
        )
    finally:
        connection.close()


def test_a_replaced_file_is_not_counted_as_already_matched(tmp_root):
    """F3: ``--deep`` re-verification has an executable form.

    §3.1's ``already`` is "present **and matched**", so a presence-only check
    asserts what it did not check.  The shipped rule: without ``--deep`` the match
    is the **size** (a ``stat``, never a read — see the cost-model test), and
    ``--deep`` escalates it to the digest.

    Mutants that must fail: (a) ``already`` keyed on presence alone — the size
    assertion below goes red; (b) ``--deep`` that reads the file and discards the
    observation — the digest assertion goes red.
    """
    root = Path(tmp_root)
    _write_audio(root, "audio/BV1REPL.p0.m4a", b"nine bytes")
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection, bvid="BV1REPL", page_index=0)
        connection.commit()
        entries = {"BV1REPL:p0": {"audio_path": "audio/BV1REPL.p0.m4a"}}

        first = _call(tmp_root, connection, entries)
        assert first.recorded == 1
        before = _stored_object(connection, "audio/BV1REPL.p0.m4a")

        # Replace the file in place with different content of a DIFFERENT size.
        _write_audio(root, "audio/BV1REPL.p0.m4a", b"sixteen bytes!!!!")
        second = _call(tmp_root, connection, entries, moment=900)
        assert second.already == 0, "a size change is not a match"
        assert second.recorded == 1, "the stale row is refreshed"
        after = _stored_object(connection, "audio/BV1REPL.p0.m4a")
        assert int(after["byte_size"]) != int(before["byte_size"])
        assert after["sha256"] == _sha256_of(b"sixteen bytes!!!!")

        # Same SIZE, different content: the size check cannot see it, --deep can.
        _write_audio(root, "audio/BV1REPL.p0.m4a", b"sixteen bytes????")
        same_size = _call(tmp_root, connection, entries, moment=1500)
        assert same_size.already == 1, "a size match is `already` without --deep"
        unchanged = _stored_object(connection, "audio/BV1REPL.p0.m4a")
        assert unchanged["sha256"] == _sha256_of(b"sixteen bytes!!!!"), (
            "without --deep the stored digest is trusted"
        )

        deep = _call(tmp_root, connection, entries, moment=1800, deep=True)
        assert deep.already == 0, "--deep sees the content change the size could not"
        assert deep.recorded == 1, "and the stale digest is refreshed"
        verified = _stored_object(connection, "audio/BV1REPL.p0.m4a")
        assert verified["sha256"] == _sha256_of(b"sixteen bytes????"), (
            "--deep must apply the digest it read, not discard the observation"
        )

        # And once refreshed, the same run converges.
        settled = _call(tmp_root, connection, entries, moment=2100)
        assert (settled.recorded, settled.already) == (0, 1)
    finally:
        connection.close()


def test_a_second_run_over_an_unchanged_tree_converges(tmp_root):
    """F8: the counters converge, not only the rows.

    The commit claimed "a re-run converges, it does not accumulate".  For
    same-content-at-a-new-path the row oscillated and **every** unchanged re-run
    reported ``recorded=2``.  The recorded key is the path actually resolved, so
    the second walk finds the row it wrote and reports ``already``.
    """
    root = Path(tmp_root)
    # The row declares .m4a but only the .flac exists — the shape whose candidate
    # list made the recorded key disagree with the file on disk.
    _write_audio(root, "audio/BV1OSC.flac")
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection, bvid="BV1OSC", page_index=0)
        connection.commit()
        entries = {
            "BV1OSC:p0": {
                "work_id": "BV1OSC:p0",
                "bvid": "BV1OSC",
                "audio_path": "audio/BV1OSC.p0.m4a",
            }
        }

        first = _call(tmp_root, connection, entries)
        assert first.recorded == 1
        key = "audio/BV1OSC.flac"
        assert _stored_object(connection, key) is not None, (
            "the store must name the file that exists"
        )
        assert _stored_object(connection, "audio/BV1OSC.p0.m4a") is None

        second = _call(tmp_root, connection, entries, moment=900)
        assert second.recorded == 0, "an unchanged tree records nothing"
        assert second.already == 1, "it converges to `already`"

        third = _call(tmp_root, connection, entries, moment=1200)
        assert (third.recorded, third.already) == (0, 1), "stable, not oscillating"
    finally:
        connection.close()


def test_byte_identical_files_do_not_oscillate_the_store(tmp_root):
    """F8, the harder shape: several candidates sharing one content.

    The single-candidate case above was fixed by keying on the resolved path, but
    that is not sufficient.  ``audio_objects`` permits exactly **one** row per
    ``sha256``, so three byte-identical files can only ever own one row: keyed on
    the path alone, each run repoints that row to a different candidate and
    reports the others as newly ``recorded`` — for ever.  Measured on the shipped
    round: the stored key bounced ``BV1A -> BV1B -> BV1C -> BV1B`` with
    ``recorded=2`` on every unchanged re-run.

    The rule this pins: a candidate whose **content** the store already holds is
    ``already``, never a second ``recorded`` — which is also what §3.1 says
    ``already`` never does ("never a second row for one ``sha256``").

    Mutant that must fail: drop the ``sha256`` membership check and record every
    candidate whose *path* is unknown — the stability assertion below goes red.

    (Found by the L2 re-reviewer of this fix round, which died before writing its
    verdict; its probe scripts survived under /tmp and the PM reproduced it.)
    """
    root = Path(tmp_root)
    payload = b"three parts, one recording session"
    connection = open_database(tmp_root)
    try:
        for bvid in ("BV1A", "BV1B", "BV1C"):
            _insert_user_video_part(connection, bvid=bvid, page_index=0)
            _write_audio(root, f"audio/{bvid}.p0.m4a", payload)
        connection.commit()
        entries = {
            f"{bvid}:p0": {
                "work_id": f"{bvid}:p0",
                "bvid": bvid,
                "audio_path": f"audio/{bvid}.p0.m4a",
            }
            for bvid in ("BV1A", "BV1B", "BV1C")
        }

        first = _call(tmp_root, connection, entries)
        assert first.recorded == 1, "one object for one content"
        assert first.already == 2, "the other two are the same object"

        settled_key = connection.execute(
            "SELECT storage_key FROM audio_objects"
        ).fetchone()[0]
        for moment in (900, 1200, 1500):
            again = _call(tmp_root, connection, entries, moment=moment)
            assert (again.recorded, again.already) == (0, 3), (
                "an unchanged tree records nothing, every time"
            )
            assert (
                connection.execute("SELECT storage_key FROM audio_objects").fetchone()[0]
                == settled_key
            ), "and the single row stops moving"
    finally:
        connection.close()


def test_the_tree_is_untouched_byte_for_byte(tmp_root):
    """F9: the read-only promise, as a test rather than a commit-message claim.

    The commit message cited a byte-snapshot fixture; none existed.  This is it:
    hash every file under the root (including a stray one no manifest row names),
    walk, hash again, and require the two maps to be identical and the file set
    unchanged.  A stray file also proves the walk did not "tidy up".
    """
    root = Path(tmp_root)
    _write_audio(root, "audio/BV1RO.p0.m4a")
    _write_audio(root, "audio/BV1RO.p1.m4a", b"other payload")
    _write_audio(root, "audio/stray.m4a", b"nobody declared me")
    _write_audio(root, "audio/BV1GONE.p0.m4a", b"will be removed below")

    connection = open_database(tmp_root)
    try:
        for page in (0, 1):
            _insert_user_video_part(connection, bvid="BV1RO", page_index=page)
        _insert_user_video_part(connection, bvid="BV1GONE", page_index=0)
        connection.commit()
        entries = {
            "BV1RO:p0": {"audio_path": "audio/BV1RO.p0.m4a"},
            "BV1RO:p1": {"audio_path": "audio/BV1RO.p1.m4a"},
            "BV1GONE:p0": {"audio_path": "audio/BV1GONE.p0.m4a"},
        }

        def snapshot() -> dict[str, str]:
            """Every file under ``audio/``, byte-hashed.

            The promise under test is over the **audio tree** — "no counter
            authorises a write to the filesystem" — so the snapshot is the audio
            directory, not the whole root.  The command legitimately writes the
            store (``archive.db``) and takes the manifest's lock, and the test
            itself seeds the manifest; none of those is an audio file.
            """
            audio_root = root / "audio"
            return {
                str(path.relative_to(audio_root)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(audio_root.rglob("*"))
                if path.is_file()
            }

        before = snapshot()
        # The reclaim path: a named file that is gone by the time the walk runs.
        os.unlink(root / "audio" / "BV1GONE.p0.m4a")

        # Run the **command**, not the service: the promise is about what an
        # operator's invocation does, and a mutant that deleted a file from the
        # CLI handler would slip past a service-level check.  (Measured: a
        # handler-level `os.unlink` mutant left the service-level version of this
        # case green.)
        from bili_asr.manifest import ManifestStore

        store = ManifestStore(root=tmp_root)
        for work_id, entry in entries.items():
            store.upsert(
                {
                    "work_id": work_id,
                    "bvid": work_id.split(":", 1)[0],
                    **entry,
                    "status": "needs_audio",
                }
            )
        code = main(["derive-audio-inventory", "--archive-root", tmp_root])
        assert code == 0
        after = snapshot()

        assert "BV1GONE.p0.m4a" in before
        del before["BV1GONE.p0.m4a"]  # the one deliberate removal, above
        assert set(after) == set(before), (
            "no file created, and none beyond the one deliberately removed"
        )
        for name, digest in after.items():
            assert digest == before[name], f"{name} was modified by the walk"
        assert "stray.m4a" in after, "an undeclared file is not tidied away"
    finally:
        connection.close()


def test_a_row_that_names_no_audio_path_is_not_a_candidate(tmp_root):
    """``missing`` counts rows that *name* a file — silence is not absence.

    A manifest row without ``audio_path`` neither records nor reports: it never
    declared audio, so calling it ``missing`` would invent a candidate the
    archive never held.
    """
    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection, bvid="BV1SILENT", page_index=0)
        connection.commit()
        outcome = _call(tmp_root, connection, {"BV1SILENT:p0": {"audio_path": None}})
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

        outcome = _call(
            tmp_root,
            connection,
            {"BV1GONE:p0": {"audio_path": "audio/BV1GONE.p0.m4a"}},
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


def test_a_present_but_unreadable_file_is_neither_missing_nor_recorded(tmp_root, monkeypatch):
    """F1b: the fixed branch, now pinned (it had no test at all).

    A present-but-unreadable file fits **no** §3.1 counter: it is not ``missing``
    (the file is there) and cannot be recorded (no digest, and ``sha256`` is
    ``NOT NULL UNIQUE``).  It is therefore counted as neither and named in the
    outcome, so the operator's numbers are not silently smaller than the tree.

    Mutant that must fail: re-adding ``missing += 1`` in the ``except OSError``
    branch — the ``missing == 0`` and ``unreadable`` assertions go red.

    **Why the read is forced rather than staged on disk.** The obvious trigger —
    ``chmod 000`` — does nothing here: this suite runs as root, and root bypasses
    the permission bits, so a chmod probe silently takes the *readable* path.  A
    directory in the file's place never reaches this branch either, because
    ``resolve_audio_path(require_exists=True)`` declines to call a directory a
    file and the row is reported ``missing`` instead.  So the read itself is
    made to fail, which is exactly the condition the branch exists for; the
    file's presence is real, so the "not ``missing``" half of the claim is
    genuinely exercised.
    """
    root = Path(tmp_root)
    _write_audio(root, "audio/BV1UNREAD.p0.m4a")

    import bili_asr.services.audio_inventory as module

    def unreadable(path):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(module, "_digest_and_size", unreadable)

    connection = open_database(tmp_root)
    try:
        _insert_user_video_part(connection, bvid="BV1UNREAD", page_index=0)
        connection.commit()
        outcome = _call(
            tmp_root,
            connection,
            {"BV1UNREAD:p0": {"audio_path": "audio/BV1UNREAD.p0.m4a"}},
        )
    finally:
        connection.close()

    assert outcome.missing == 0, "the file is present, so it is not `missing`"
    assert outcome.recorded == 0, "no digest means it cannot be recorded"
    assert outcome.unreadable == ("audio/BV1UNREAD.p0.m4a",), (
        "the unreadable row must be named rather than counted"
    )


# --------------------------------------------------------------------------
# The command surface
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
    """An empty result is success, matching ``derive-manifest``."""
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


def test_the_command_takes_the_archive_writer_lock(tmp_root, capsys):
    """F5: the documented refusal path must exist.

    ``derive-audio-inventory`` writes ``audio_objects`` / ``part_audio_objects``,
    so it belongs in ``_ARCHIVE_WRITER_COMMANDS`` beside ``derive-manifest``.
    Before the fix the docstring claimed an ``archive_busy`` refusal that could
    not happen: the command ran and exited 0 while another writer held the lock.

    Mutant that must fail: removing the command from that set.
    """
    from bili_asr.cli import _ARCHIVE_WRITER_COMMANDS
    from bili_asr.coordinator import archive_writer

    assert "derive-audio-inventory" in _ARCHIVE_WRITER_COMMANDS

    connection = open_database(tmp_root)
    try:
        pass
    finally:
        connection.close()

    # `archive_writer` is reentrant *within the owning thread*, so holding it
    # here would let the command re-enter rather than refuse.  A second thread
    # owns it instead, which is the real contention the refusal exists for.
    import threading

    held = threading.Event()
    release = threading.Event()

    def holder():
        with archive_writer(tmp_root):
            held.set()
            release.wait(timeout=30)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(timeout=30), "the helper thread took the lock"
        code = main(["derive-audio-inventory", "--archive-root", tmp_root])
    finally:
        release.set()
        thread.join(timeout=30)
    captured = capsys.readouterr()
    assert code == 1, "a held archive-writer lock is a refusal path"
    assert "archive_busy" in captured.err


def test_a_store_failure_mid_walk_is_bounded(tmp_root, capsys, monkeypatch):
    """F4: a store error reports instead of escaping, and says what landed.

    ``record`` commits one transaction per row, so a failure part-way through
    leaves rows written.  Before the fix the walk died as a traceback with **no
    summary line** and no count of what had landed (measured 1 of 4 rows) — the
    command went silent exactly when the store was worth reporting on.

    Mutant that must fail: dropping the handler's ``except Exception`` bound.
    """
    root = Path(tmp_root)
    # Distinct content per page: identical bytes would be ONE object (content is
    # the store's dedup key), so only the first would reach `record` and the
    # injected second failure would never fire.
    for page in range(2):
        _write_audio(root, f"audio/BV1FAIL.p{page}.m4a", f"payload {page}".encode())
    connection = open_database(tmp_root)
    try:
        for page in range(2):
            _insert_user_video_part(connection, bvid="BV1FAIL", page_index=page)
        connection.commit()
    finally:
        connection.close()

    from bili_asr.manifest import ManifestStore

    store = ManifestStore(root=tmp_root)
    for page in range(2):
        store.upsert(
            {
                "work_id": f"BV1FAIL:p{page}",
                "bvid": "BV1FAIL",
                "audio_path": f"audio/BV1FAIL.p{page}.m4a",
                "status": "needs_audio",
            }
        )

    import bili_asr.services.audio_inventory as module

    real = module.reconcile_audio_inventory
    calls = {"n": 0}

    def failing(*args, **kwargs):
        # Fail on the second record, after the first has committed.
        record = kwargs["record"]

        def record_then_die(**fields):
            calls["n"] += 1
            audio_id = record(**fields)
            if calls["n"] == 2:
                raise RuntimeError("simulated store failure")
            return audio_id

        kwargs["record"] = record_then_die
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "reconcile_audio_inventory", failing)

    code = main(["derive-audio-inventory", "--archive-root", tmp_root])
    captured = capsys.readouterr()
    assert code == 1, "a bounded store failure exits 1"
    assert "failed after" in captured.err, "the failure line names what landed"
    assert "RuntimeError" in captured.err, "and the failure's own type"


def test_the_summary_line_is_the_contracts_field_order():
    """The line is a contract, not a naming exercise (§3.1)."""
    assert AudioInventoryOutcome(1, 2, 3, 4).summary_line() == (
        "derive-audio-inventory: recorded=1 already=2 missing=3 unlinked=4"
    )
    assert ACQUISITION_SOURCE == "derive-audio-inventory"
