"""Offline contract tests for ``bili-asr publish-transcripts`` (contract §7, §10).

Everything here is offline.  The command is driven end to end through
``bili_asr.cli.main`` — argparse, the read-only store connection, the
transcript-schema guard, ``TranscriptRepository``, the pure projection service,
the archive writer and ``ManifestStore`` — against a temporary archive database,
so no network call is made, no live corpus is touched and no ASR runs.

What is pinned: the five states §5.5 discriminates (a fresh transcript, a
chain-archived bundle, a second stored version, an interrupted publication and a
``gone`` part that still holds local text), the exact printed lines and the
summary with its zeros, the idempotency §5.4 rests on (a complete bundle is
never rewritten), the exit stance (``0``/``1``, never ``2``), and the boundaries
the command promises — the store is opened read-only and never written, one row
is appended per publication, and the products land under ``--artifact-root``
while the state stays at the archive root.

The store fixture is built through the repository APIs only: no test here writes
raw SQL into ``archive.db``.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import os
import sqlite3
import threading
import time

from bili_asr import archive as archive_module
from bili_asr import cli as cli_module
from bili_asr.cli import main
from bili_asr.config import ARCHIVE_DATABASE_NAME
from bili_asr.coordinator import ARCHIVE_WRITER_LOCK
from bili_asr.manifest import ManifestStore
from bili_asr.persistence import file_lock
from bili_asr.storage import (
    AcquisitionRunRecord,
    MetadataRepository,
    TranscriptRepository,
    TranscriptSegmentRecord,
    open_database,
)
from fixtures.metadata_records import (
    make_part_record,
    make_user_record,
    make_video_record,
)

#: The fixture's five states, one part each (§5.5), plus a stored part that holds
#: no transcript at all — the *known* selector that yields zero candidates.
FRESH_BVID = "BV1FRESH"
CHAIN_BVID = "BV1CHAIN"
DRIFT_BVID = "BV1DRIFT"
MARKER_BVID = "BV1MARKER"
GONE_BVID = "BV1GONE"
BARE_BVID = "BV1BARE"

#: ``(bvid, page_index, cid, duration_ms, processing_status)``.  The durations make
#: the seconds conversion falsifiable: 12_000 floors to 12 and 3_000 to 3.
PARTS = (
    (FRESH_BVID, 0, 3001, 12_000, "metadata_collected"),
    (CHAIN_BVID, 0, 5001, 7_000, "metadata_collected"),
    (DRIFT_BVID, 0, 6001, 8_000, "metadata_collected"),
    (MARKER_BVID, 0, 7001, 9_000, "metadata_collected"),
    (GONE_BVID, 0, 4001, 5_000, "gone"),
    (BARE_BVID, 0, 8001, 3_000, "metadata_collected"),
)

#: The caption body the fixture stores: two cues, no leading mark, no fragment and
#: no repeated n-gram, so a later reader check that asks for an empty ``reasons``
#: list (``quality.py:26-34``) is not defeated by this file's text.
CAPTION_SEGMENTS = (
    TranscriptSegmentRecord(0, 2_500, "档案里的第一句台词"),
    TranscriptSegmentRecord(3_000, 6_000, "第二句记录在案的台词"),
)
#: The body a second stored version carries: same identity, different content hash,
#: so the store appends ``version=2`` instead of answering ``unchanged``.
SECOND_VERSION_SEGMENTS = (TranscriptSegmentRecord(0, 1_500, "改过一次的字幕"),)

#: The four product keys a row declares (contract §5.1).
PRODUCT_KEYS = ("srt_path", "txt_path", "md_path", "raw_path")

MANIFEST_REL_PATH = os.path.join("manifest", "manifest.jsonl")

#: The publication second ``fixtures.metadata_records`` stores for every video, and
#: its **UTC** calendar date — the row's ``pubdate``/``pubdate_str`` and the md
#: name's leading component.  Rendered with ``gmtime`` rather than written as a
#: literal, because a literal only discriminates on a host whose own zone is UTC.
PUBDATE = 1_700_000_000
PUBDATE_STR = time.strftime("%Y-%m-%d", time.gmtime(PUBDATE))


def _md_name(bvid: str, page_index: int) -> str:
    """The writer's md name for page ``page_index`` of ``bvid`` (§3.1)."""
    return f"{PUBDATE_STR}_{bvid}.p{page_index}_第{page_index + 1}集.md"


def _entry(bvid: str, page_index: int, cid: int, duration_ms: int) -> dict:
    """The writer's entry for one stored part — the fields its frontmatter reads."""
    return {
        "bvid": bvid,
        "work_id": f"{bvid}:p{page_index}",
        "page_index": page_index,
        "cid": cid,
        "title": f"第{page_index + 1}集",
        "duration_s": max(1, duration_ms // 1000),
        "pubdate_str": PUBDATE_STR,
    }


def _seed_archive(root: str, parts=PARTS) -> None:
    """Create ``archive.db`` with one video per bvid and exactly these parts."""
    connection = open_database(root)
    try:
        metadata = MetadataRepository(connection)
        with metadata.transaction():
            metadata.upsert_user(make_user_record())
            for bvid in dict.fromkeys(bvid for bvid, _page, _cid, _ms, _status in parts):
                metadata.upsert_video(
                    make_video_record(bvid, aid=None, title="投影测试视频")
                )
            for bvid, page_index, cid, duration_ms, status in parts:
                metadata.upsert_part(
                    replace(
                        make_part_record(
                            bvid,
                            page_index=page_index,
                            cid=cid,
                            title=f"第{page_index + 1}集",
                            processing_status=status,
                        ),
                        duration_ms=duration_ms,
                    )
                )
    finally:
        connection.close()


def _part_id(connection, bvid: str, page_index: int) -> int:
    """One stored part's primary key, read from the store's own relation."""
    return int(
        connection.execute(
            "SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?",
            (bvid, page_index),
        ).fetchone()["video_part_id"]
    )


def _store_caption(
    root: str,
    bvid: str,
    page_index: int,
    *,
    segments=CAPTION_SEGMENTS,
    version_tag: str = "v1",
) -> None:
    """Store one acquired ``subtitle-ai`` caption through the repository."""
    connection = open_database(root)
    try:
        repository = TranscriptRepository(connection)
        run_id = f"caption-{version_tag}-{bvid}-p{page_index}"
        repository.start_acquisition_run(
            AcquisitionRunRecord(
                run_id=run_id,
                kind="subtitle",
                selector_kind="pending",
                selector_target=None,
                requested_limit=None,
                credential_present=False,
                started_at=101,
            )
        )
        repository.record_acquired_transcript(
            run_id=run_id,
            video_part_id=_part_id(connection, bvid, page_index),
            source_kind="subtitle-ai",
            language="zh-CN",
            segments=segments,
            started_at=200,
            finished_at=300,
            created_at=400,
        )
    finally:
        connection.close()


def _chain_archive(root: str, bvid: str, page_index: int, cid: int) -> dict:
    """Publish one bundle the way the chain does and record its ``archived`` row.

    State (ii) of §5.5, built with the shipped writer rather than by the command
    under test: the four families, the marker, and the row that declares them.
    """
    entry = _entry(bvid, page_index, cid, 7_000)
    paths = archive_module.write_archive(
        root,
        entry,
        [{"start": 0.0, "end": 2.5, "text": "链上归档的台词"}],
        source="subtitle",
    )
    store = ManifestStore(root=root)
    store.load()
    store.upsert({**entry, **paths, "status": "archived"})
    return paths


def _exit_code(argv: list[str]) -> int:
    """Return the command's exit code, argparse usage errors included."""
    try:
        return main(argv)
    except SystemExit as exit_signal:
        return int(exit_signal.code)


def _publish(root: str, *extra: str) -> int:
    """Run the command the way an operator does, and return its exit code."""
    return _exit_code(["publish-transcripts", "--archive-root", root, *extra])


def _file_hashes(root: str) -> dict[str, str]:
    """Every file below ``root``, as ``relative POSIX path -> sha256``."""
    digests: dict[str, str] = {}
    for directory, _directories, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            digests[os.path.relpath(path, root).replace(os.sep, "/")] = digest
    return digests


def _bundle_hashes(base: str, declared: dict[str, str]) -> dict[str, str]:
    """``path -> sha256`` for one declared bundle: the four families and the marker."""
    paths = [os.path.join(base, declared[key]) for key in PRODUCT_KEYS]
    paths.append(str(archive_module.bundle_marker_path(paths[0])))
    digests = {}
    for path in paths:
        with open(path, "rb") as handle:
            digests[os.path.relpath(path, base)] = hashlib.sha256(handle.read()).hexdigest()
    return digests


def _manifest_lines(root: str) -> list[str]:
    """The raw append-only history, one string per stored manifest line."""
    with open(os.path.join(root, MANIFEST_REL_PATH), encoding="utf-8") as handle:
        return [line for line in handle.read().splitlines() if line]


def _archive_files(root: str) -> list[str]:
    """Every file below the archive root, as sorted relative POSIX paths."""
    return sorted(
        os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
        for directory, _directories, names in os.walk(root)
        for name in names
    )


def _declared(root: str, work_id: str) -> dict[str, str]:
    """The four product paths the effective row of ``work_id`` declares."""
    row = ManifestStore(root=root).load()[work_id]
    return {key: row[key] for key in PRODUCT_KEYS}


def _stored_bodies(root: str) -> dict[int, str]:
    """``transcript_id -> content_sha256`` as the store holds it, read directly.

    A read that opens the database without creating or migrating it, so the
    comparison is of stored content and not of a schema pass this helper ran.
    """
    connection = sqlite3.connect(os.path.join(root, ARCHIVE_DATABASE_NAME))
    try:
        connection.row_factory = sqlite3.Row
        return {
            int(row["transcript_id"]): str(row["content_sha256"])
            for row in connection.execute(
                "SELECT transcript_id, content_sha256 FROM transcripts"
            )
        }
    finally:
        connection.close()


def test_publish_transcripts_publishes_one_stored_caption_as_a_complete_bundle(
    tmp_root, capsys
):
    """States (i) and (v): a stored transcript becomes a complete bundle.

    The ``gone`` part is the falsifier for §2's membership rule: a candidate
    relation filtered by ``processing_status`` would publish one bundle here, not
    two.
    """
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    _store_caption(tmp_root, GONE_BVID, 0)

    assert _publish(tmp_root) == 0
    captured = capsys.readouterr()

    assert captured.out.splitlines() == [
        f"{FRESH_BVID}:p0: published (source=subtitle-ai lang=zh-CN version=1 "
        f"cues=2) transcripts/md/{_md_name(FRESH_BVID, 0)}",
        f"{GONE_BVID}:p0: published (source=subtitle-ai lang=zh-CN version=1 "
        f"cues=2) transcripts/md/{_md_name(GONE_BVID, 0)}",
        "publish-transcripts: candidates=2 published=2 already_published=0 failed=0",
    ]
    assert captured.err == ""

    base = os.path.abspath(tmp_root)
    for bvid in (FRESH_BVID, GONE_BVID):
        stem = f"{bvid}.p0"
        for family, suffix in (("srt", ".srt"), ("txt", ".txt"), ("raw", ".json")):
            assert os.path.isfile(os.path.join(base, "transcripts", family, stem + suffix))
        assert os.path.isfile(
            os.path.join(base, "transcripts", "md", _md_name(bvid, 0))
        )
        # The reader the archive itself counts bundles with agrees, marker hashes
        # included — the same call `verify` and `coverage` make.
        assert archive_module.archive_bundle_complete(base, _declared(tmp_root, f"{bvid}:p0"))


def test_publish_transcripts_prints_the_summary_with_every_count_including_zeros(
    tmp_root, capsys
):
    """§7: one line per candidate and a summary carrying every count, zeros too."""
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    _store_caption(tmp_root, GONE_BVID, 0)
    _store_caption(tmp_root, CHAIN_BVID, 0)
    _chain_archive(tmp_root, CHAIN_BVID, 0, 5001)

    assert _publish(tmp_root) == 0
    captured = capsys.readouterr()

    assert captured.out.splitlines()[-1] == (
        "publish-transcripts: candidates=3 published=2 already_published=1 failed=0"
    )
    # One line per candidate, in the read's locked order (bvid ascending), and the
    # `already_published` line names no path and no identity — nothing was written.
    assert captured.out.splitlines()[:3] == [
        f"{CHAIN_BVID}:p0: already_published",
        f"{FRESH_BVID}:p0: published (source=subtitle-ai lang=zh-CN version=1 "
        f"cues=2) transcripts/md/{_md_name(FRESH_BVID, 0)}",
        f"{GONE_BVID}:p0: published (source=subtitle-ai lang=zh-CN version=1 "
        f"cues=2) transcripts/md/{_md_name(GONE_BVID, 0)}",
    ]
    assert captured.err == ""


def test_publish_transcripts_is_idempotent_and_the_second_run_touches_nothing(
    tmp_root, capsys
):
    """§5.4: a complete bundle is never replaced, so run two is a no-op."""
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)

    assert _publish(tmp_root) == 0
    capsys.readouterr()
    before_files = _file_hashes(tmp_root)
    before_lines = _manifest_lines(tmp_root)
    assert before_lines

    assert _publish(tmp_root) == 0
    captured = capsys.readouterr()

    assert captured.out.splitlines() == [
        f"{FRESH_BVID}:p0: already_published",
        "publish-transcripts: candidates=1 published=0 already_published=1 failed=0",
    ]
    assert captured.err == ""
    # Every byte below the archive root is identical, the manifest history
    # included: no file, no marker and no row for a bundle that is already there.
    assert _file_hashes(tmp_root) == before_files
    assert _manifest_lines(tmp_root) == before_lines


def test_publish_transcripts_leaves_a_chain_archived_bundle_byte_identical(
    tmp_root, capsys
):
    """State (ii): a bundle the chain archived is the control §5.4 must not touch."""
    _seed_archive(tmp_root)
    _store_caption(tmp_root, CHAIN_BVID, 0)
    _chain_archive(tmp_root, CHAIN_BVID, 0, 5001)
    work_id = f"{CHAIN_BVID}:p0"
    base = os.path.abspath(tmp_root)
    before_bundle = _bundle_hashes(base, _declared(tmp_root, work_id))
    before_lines = _manifest_lines(tmp_root)

    assert _publish(tmp_root) == 0
    captured = capsys.readouterr()

    assert captured.out.splitlines() == [
        f"{CHAIN_BVID}:p0: already_published",
        "publish-transcripts: candidates=1 published=0 already_published=1 failed=0",
    ]
    assert captured.err == ""
    assert _bundle_hashes(base, _declared(tmp_root, work_id)) == before_bundle
    assert _manifest_lines(tmp_root) == before_lines


def test_publish_transcripts_republishes_a_bundle_whose_marker_is_missing(
    tmp_root, capsys
):
    """State (iv): a publication interrupted before its marker heals on the next run.

    The row is there and the four files are there, but the completeness reader
    returns ``False`` without the marker, so the candidate is republished rather
    than trusted — and the writer invalidates a stale marker before writing the
    new one last.
    """
    _seed_archive(tmp_root)
    _store_caption(tmp_root, MARKER_BVID, 0)
    assert _publish(tmp_root) == 0
    capsys.readouterr()

    base = os.path.abspath(tmp_root)
    marker = archive_module.bundle_marker_path(
        os.path.join(base, "transcripts", "srt", f"{MARKER_BVID}.p0.srt")
    )
    assert os.path.isfile(marker)
    os.unlink(marker)
    work_id = f"{MARKER_BVID}:p0"
    before_row = dict(ManifestStore(root=tmp_root).load()[work_id])
    before_declared = _declared(tmp_root, work_id)
    assert not archive_module.archive_bundle_complete(base, before_declared)
    assert len(_manifest_lines(tmp_root)) == 1

    assert _publish(tmp_root) == 0
    captured = capsys.readouterr()

    assert captured.out.splitlines() == [
        f"{MARKER_BVID}:p0: published (source=subtitle-ai lang=zh-CN version=1 "
        f"cues=2) transcripts/md/{_md_name(MARKER_BVID, 0)}",
        "publish-transcripts: candidates=1 published=1 already_published=0 failed=0",
    ]
    assert os.path.isfile(marker)
    assert archive_module.archive_bundle_complete(base, before_declared)
    # The republished row is the same statement the first run recorded: the
    # append-only history gained a line (the readers' own history defect, R2), the
    # effective state did not move.
    assert ManifestStore(root=tmp_root).load()[work_id] == before_row
    assert len(_manifest_lines(tmp_root)) == 2


def test_publish_transcripts_reports_failed_and_exits_one_on_a_stale_staging_directory(
    tmp_root, capsys
):
    """§5.5 (iv): the writer's staging guard refuses, the part is named, exit 1.

    The summary still prints — the counts an operator reads do not depend on how
    far the run got — and no row is recorded for the part that could not publish.
    """
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    base = os.path.abspath(tmp_root)
    os.makedirs(os.path.join(base, "transcripts", ".archive-bundle-stage"))

    assert _publish(tmp_root) == 1
    captured = capsys.readouterr()

    assert captured.out.splitlines() == [
        f"{FRESH_BVID}:p0: failed (OSError)",
        "publish-transcripts: candidates=1 published=0 already_published=0 failed=1",
    ]
    assert captured.err == ""
    assert ManifestStore(root=tmp_root).load() == {}
    assert not os.path.exists(
        os.path.join(base, "transcripts", "srt", f"{FRESH_BVID}.p0.srt")
    )


def test_publish_transcripts_opens_the_only_connection_read_only(
    tmp_root, capsys, monkeypatch
):
    """§5.6: the store is read, never written — the connection refuses a write.

    The probe is taken while the run holds its own connection (the handler closes
    it before returning), and the schema-initializing open helper is made fatal:
    a run that took that path would raise instead of publishing.  What the store
    held is compared before and after, so a write that reached the file would be
    visible even if the probe had been fooled.
    """
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    before = _stored_bodies(tmp_root)
    captured: dict[str, BaseException] = {}

    def forbidden(*args, **kwargs):
        raise AssertionError("the schema-initializing connection was opened")

    real_list = TranscriptRepository.list_stored_transcripts

    def spy(self, bvid=None, page_index=None):
        try:
            self.connection.execute("CREATE TABLE probe (value INTEGER)")
        except sqlite3.Error as exc:
            captured["write_error"] = exc
        return real_list(self, bvid, page_index)

    monkeypatch.setattr(cli_module, "_open_read_connection", forbidden)
    monkeypatch.setattr(TranscriptRepository, "list_stored_transcripts", spy)

    assert _publish(tmp_root) == 0
    capsys.readouterr()

    error = captured["write_error"]
    assert isinstance(error, sqlite3.OperationalError)
    assert "readonly" in str(error)
    assert _stored_bodies(tmp_root) == before


def test_publish_transcripts_unknown_bvid_is_exit_one_and_writes_nothing(tmp_root, capsys):
    """§2.2: a selector no stored part answers is configuration, exit 1."""
    _seed_archive(tmp_root)

    assert _publish(tmp_root, "--bvid", "BV1ABSENT") == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == "publish-transcripts: unknown --bvid BV1ABSENT\n"
    assert ManifestStore(root=tmp_root).load() == {}
    # Only the shipped writer lock's own directory: no manifest, no products.
    assert _archive_files(tmp_root) == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK])


def test_publish_transcripts_a_known_bvid_holding_no_transcript_is_zero_candidates(
    tmp_root, capsys
):
    """§2.2: a stored part without a transcript is *known* — zero candidates, exit 0."""
    _seed_archive(tmp_root)

    assert _publish(tmp_root, "--bvid", BARE_BVID) == 0
    captured = capsys.readouterr()

    assert captured.out == (
        "publish-transcripts: candidates=0 published=0 already_published=0 failed=0\n"
    )
    assert captured.err == ""
    assert ManifestStore(root=tmp_root).load() == {}
    assert _archive_files(tmp_root) == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK])


def test_publish_transcripts_non_positive_limit_parts_is_exit_one(tmp_root, capsys):
    """§2.2: the bound is in parts and must be positive; the run never starts."""
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)

    for value in ("0", "-1"):
        assert _publish(tmp_root, "--limit-parts", value) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == (
            "publish-transcripts: --limit-parts must be a positive integer\n"
        )
    assert ManifestStore(root=tmp_root).load() == {}


def test_publish_transcripts_help_names_the_range_and_the_disclosures(capsys):
    """Criterion 6a: the five literal substrings, and the four flags, in ``--help``."""
    assert _exit_code(["publish-transcripts", "--help"]) == 0
    captured = capsys.readouterr()

    # argparse rewraps the description to the terminal width, so the phrases are
    # asserted on the de-wrapped text: the requirement is what the help says, not
    # where the line breaks fall.
    help_text = " ".join(captured.out.split())
    assert "stored transcripts" in help_text
    assert "fetches nothing" in help_text
    assert "a complete published bundle is never replaced" in help_text
    assert "newer transcript version" in help_text
    assert "already carries an earlier manifest state" in help_text
    for flag in ("--bvid", "--limit-parts", "--archive-root", "--artifact-root"):
        assert flag in help_text
    assert "--keep-audio" not in help_text


def test_publish_transcripts_holds_the_archive_writer_lock(tmp_root, capsys):
    """§7: it joins the archive-writer set; a held root lock refuses ``archive_busy``."""
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)

    assert _publish(tmp_root) == 0
    capsys.readouterr()
    lock_path = os.path.join(tmp_root, ARCHIVE_WRITER_LOCK)
    assert os.path.isfile(lock_path)

    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        # ``archive_writer`` is reentrant within one thread, so the lock has to be
        # held from another one for the command to meet a busy archive.
        with file_lock(lock_path):
            held.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    try:
        assert held.wait(timeout=30)
        assert _publish(tmp_root) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "publish-transcripts: archive_busy\n"
    finally:
        release.set()
        holder.join(timeout=30)
    assert not holder.is_alive()


def test_publish_transcripts_records_the_fifteen_key_row_the_readers_read(tmp_root, capsys):
    """§5.1: exactly the fifteen keys, and each one the value the readers read."""
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)

    assert _publish(tmp_root) == 0
    capsys.readouterr()

    row = ManifestStore(root=tmp_root).load()[f"{FRESH_BVID}:p0"]
    assert set(row) == {
        "work_id", "bvid", "page_index", "cid", "title", "duration_s", "pubdate",
        "pubdate_str", "status", "srt_path", "txt_path", "md_path", "raw_path",
        "source", "language",
    }
    assert row["work_id"] == f"{FRESH_BVID}:p0"
    assert row["bvid"] == FRESH_BVID
    assert row["page_index"] == 0
    assert row["cid"] == 3001
    assert row["title"] == "第1集"
    assert row["duration_s"] == 12
    assert row["pubdate"] == PUBDATE
    assert row["pubdate_str"] == PUBDATE_STR
    # `archived` is the state the chain itself writes after a complete bundle, and
    # the state the readers require to stop counting the row unfinished (§5.2).
    assert row["status"] == "archived"
    # The published identity, in the vocabulary `quality` and `search_index` read.
    assert row["source"] == "subtitle-ai"
    assert row["language"] == "zh-CN"
    assert row["srt_path"] == f"transcripts/srt/{FRESH_BVID}.p0.srt"
    assert row["txt_path"] == f"transcripts/txt/{FRESH_BVID}.p0.txt"
    assert row["raw_path"] == f"transcripts/raw/{FRESH_BVID}.p0.json"
    assert row["md_path"] == f"transcripts/md/{_md_name(FRESH_BVID, 0)}"


def test_publish_transcripts_writes_products_under_the_artifact_root_and_state_at_the_archive_root(
    tmp_root, capsys
):
    """D10/§7: the products follow ``--artifact-root``, the recorded state stays put."""
    archive_root = os.path.join(tmp_root, "state")
    artifact_root = os.path.join(tmp_root, "products")
    os.makedirs(archive_root)
    os.makedirs(artifact_root)
    _seed_archive(archive_root)
    _store_caption(archive_root, FRESH_BVID, 0)

    assert _exit_code(
        [
            "publish-transcripts",
            "--archive-root", archive_root,
            "--artifact-root", artifact_root,
        ]
    ) == 0
    captured = capsys.readouterr()

    # The printed path is the recorded root-relative form, never a filesystem path.
    assert captured.out.splitlines()[0] == (
        f"{FRESH_BVID}:p0: published (source=subtitle-ai lang=zh-CN version=1 "
        f"cues=2) transcripts/md/{_md_name(FRESH_BVID, 0)}"
    )
    assert artifact_root not in captured.out
    assert archive_module.archive_bundle_complete(
        artifact_root, _declared(archive_root, f"{FRESH_BVID}:p0")
    )
    assert os.path.isfile(os.path.join(archive_root, MANIFEST_REL_PATH))
    assert not os.path.exists(os.path.join(archive_root, "transcripts"))
    assert _archive_files(archive_root) == sorted(
        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK, MANIFEST_REL_PATH,
         MANIFEST_REL_PATH + ".lock"]
    )
