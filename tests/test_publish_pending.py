"""A finite pending publication advances while preserving complete bundles."""

from __future__ import annotations

import errno
import sqlite3
from pathlib import Path

import pytest

from bili_asr import archive
from functools import partial
from bili_asr.cli.main import _main

# Exercise the publication worker in-process so fault injection and captured
# output remain local; supervisor process/deadline tests cover the public entry.
main = partial(_main, _publication_worker=True)
from bili_asr.manifest import ManifestStore
from bili_asr.services.transcript_projection import ordered_candidates
from bili_asr.storage import TranscriptRepository, open_database

from test_cli_publish_transcripts import (
    CHAIN_BVID, FRESH_BVID, _bundle_hashes, _declared, _store_caption,
)
from test_publish_candidate_limits import _seed_versions
from test_publish_read_failures import _existing_bundle, _fail_one_read
from test_transcript_repository import _record, _run, _video_with_parts


def _publish(root, *extra):
    return main([
        "publish-transcripts", "--archive-root", str(root), "--pending", *extra,
    ])


def _seed(root):
    connection = open_database(root)
    try:
        _seed_versions(connection)
    finally:
        connection.close()


def test_repeated_pending_limit_one_drains_all_parts_without_rewriting(
    tmp_root, monkeypatch, capsys,
):
    _seed(tmp_root)
    expected = ["BV1LIMIT:p1", "BV1LIMIT:p2", "BV2LIMIT:p0", "BV2LIMIT:p1"]
    published_hashes = {}
    real_write = archive.write_archive
    writes = []

    def recording_write(root, entry, *args, **kwargs):
        writes.append(entry["work_id"])
        return real_write(root, entry, *args, **kwargs)

    monkeypatch.setattr(archive, "write_archive", recording_write)
    for index, work_id in enumerate(expected):
        assert _publish(tmp_root, "--limit-parts", "1") == 0
        output = capsys.readouterr().out
        assert f"{work_id}: published" in output
        assert output.endswith(
            f"candidates={index + 1} published=1 already_published={index} failed=0\n"
        )
        assert writes == expected[:index + 1]
        rows = ManifestStore(root=tmp_root).load()
        assert list(rows) == expected[:index + 1]
        for previous, hashes in published_hashes.items():
            assert _bundle_hashes(tmp_root, _declared(tmp_root, previous)) == hashes
        published_hashes[work_id] = _bundle_hashes(tmp_root, _declared(tmp_root, work_id))
    before_manifest = Path(ManifestStore(root=tmp_root).path).read_bytes()
    monkeypatch.setattr(
        ManifestStore, "save", lambda *args, **kwargs: pytest.fail("saved a no-op manifest")
    )
    assert _publish(tmp_root, "--limit-parts", "1") == 0
    assert capsys.readouterr().out.endswith(
        "candidates=4 published=0 already_published=4 failed=0\n"
    )
    assert writes == expected
    assert Path(ManifestStore(root=tmp_root).path).read_bytes() == before_manifest


def test_keyset_part_batches_keep_every_version_and_have_no_offset(tmp_root):
    connection = open_database(tmp_root)
    try:
        repository, _, _ = _seed_versions(connection)
        expected = ordered_candidates(repository.list_stored_transcripts())
        actual = []
        after = None
        while True:
            batch = ordered_candidates(repository.list_stored_transcripts(
                limit_parts=1, after_part=after,
            ))
            if not batch:
                break
            assert len(batch) == 1
            actual.extend(batch)
            after = (batch[-1].part["bvid"], batch[-1].part["page_index"])
        assert tuple(actual) == expected
        assert actual[0].transcript["source_kind"] == "subtitle-cc"
        assert actual[0].transcript["version"] == 2
        assert not connection.in_transaction
    finally:
        connection.close()


@pytest.mark.parametrize("after,error", [
    (["BV1LIMIT", 1], TypeError), (("BV1LIMIT",), TypeError),
    (("BV1LIMIT", True), TypeError), (("BV1LIMIT", -1), ValueError),
])
def test_keyset_cursor_validation_does_not_open_a_transaction(tmp_root, after, error):
    connection = open_database(tmp_root)
    try:
        with pytest.raises(error):
            TranscriptRepository(connection).list_stored_transcripts(
                limit_parts=1, after_part=after,
            )
        assert not connection.in_transaction
    finally:
        connection.close()


@pytest.mark.parametrize("limit", [1, 2])
def test_unreadable_bundle_consumes_pending_budget_and_keeps_its_products(
    tmp_root, monkeypatch, capsys, limit,
):
    paths = _existing_bundle(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    before = _bundle_hashes(tmp_root, paths)
    pending = _fail_one_read(
        monkeypatch, Path(tmp_root) / paths["txt_path"], OSError(errno.EIO, "device error")
    )
    assert _publish(tmp_root, "--limit-parts", str(limit)) == 1
    output = capsys.readouterr().out
    assert not pending[0]
    assert f"{CHAIN_BVID}:p0: failed (OSError)" in output
    assert output.endswith(
        f"candidates={limit} published={limit - 1} already_published=0 failed=1\n"
    )
    assert _bundle_hashes(tmp_root, paths) == before
    rows = ManifestStore(root=tmp_root).load()
    assert (f"{FRESH_BVID}:p0" in rows) is (limit == 2)
    if limit == 1:
        assert _publish(tmp_root, "--limit-parts", "1") == 0
        assert capsys.readouterr().out.endswith(
            "candidates=2 published=1 already_published=1 failed=0\n"
        )


@pytest.mark.parametrize("damage", ["missing", "corrupt", "marker"])
def test_pending_repairs_proven_damage_even_when_manifest_says_archived(
    tmp_root, capsys, damage,
):
    paths = _existing_bundle(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    target = Path(tmp_root) / paths["txt_path"]
    if damage == "missing":
        target.unlink()
    elif damage == "corrupt":
        target.write_text("damaged archived product", encoding="utf-8")
    else:
        archive.bundle_marker_path(Path(tmp_root) / paths["srt_path"]).write_text(
            "[]", encoding="ascii"
        )
    assert _publish(tmp_root, "--limit-parts", "1") == 0
    assert capsys.readouterr().out.endswith(
        "candidates=1 published=1 already_published=0 failed=0\n"
    )
    assert archive.archive_bundle_complete(tmp_root, paths, require_readable=True)
    assert f"{FRESH_BVID}:p0" not in ManifestStore(root=tmp_root).load()


@pytest.mark.parametrize("selector,code,expected", [
    ("BV1UNKNOWN", 1, []), ("BV1LIMIT:p0", 0, []),
    ("BV1LIMIT:p2", 0, ["BV1LIMIT:p2"]),
    ("BV2LIMIT", 0, ["BV2LIMIT:p0", "BV2LIMIT:p1"]),
])
def test_pending_preserves_unknown_empty_and_scoped_selectors(
    tmp_root, capsys, selector, code, expected,
):
    _seed(tmp_root)
    assert _publish(tmp_root, "--bvid", selector) == code
    output = capsys.readouterr()
    assert list(ManifestStore(root=tmp_root).load()) == expected
    if code:
        assert "unknown --bvid" in output.err
    else:
        assert output.out.endswith(
            f"candidates={len(expected)} published={len(expected)} already_published=0 failed=0\n"
        )


def test_pending_keyset_batches_keep_the_database_read_only_and_bound_reads(
    tmp_root, monkeypatch, capsys,
):
    _seed(tmp_root)
    real_list = TranscriptRepository.list_stored_transcripts
    reads = []

    def recording_read(self, *args, **kwargs):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            self.connection.execute("CREATE TABLE illegal_pending_write(value INTEGER)")
        rows = real_list(self, *args, **kwargs)
        reads.append((kwargs["after_part"], kwargs["limit_parts"], len(rows)))
        return rows

    monkeypatch.setattr(TranscriptRepository, "list_stored_transcripts", recording_read)
    assert _publish(tmp_root, "--limit-parts", "1") == 0
    capsys.readouterr()
    assert reads == [(None, 1, 5)]
    reads.clear()
    assert _publish(tmp_root, "--limit-parts", "1") == 0
    capsys.readouterr()
    assert reads == [(None, 1, 5), (("BV1LIMIT", 1), 1, 1)]


def test_unlimited_pending_reads_in_small_batches_and_drains_larger_queue(
    tmp_root, monkeypatch, capsys,
):
    connection = open_database(tmp_root)
    try:
        repository = TranscriptRepository(connection)
        parts = _video_with_parts(connection, "BV1BATCH", tuple(range(9001, 9041)))
        for page, part in parts.items():
            _record(repository, part, run_id=_run(repository, page + 1))
    finally:
        connection.close()
    real_list = TranscriptRepository.list_stored_transcripts
    batch_sizes = []

    def recording_read(self, *args, **kwargs):
        rows = real_list(self, *args, **kwargs)
        batch_sizes.append((kwargs["limit_parts"], len(rows)))
        return rows

    monkeypatch.setattr(TranscriptRepository, "list_stored_transcripts", recording_read)
    assert _publish(tmp_root) == 0
    assert capsys.readouterr().out.endswith(
        "candidates=40 published=40 already_published=0 failed=0\n"
    )
    assert batch_sizes == [(32, 32), (32, 8), (32, 0)]
    assert len(ManifestStore(root=tmp_root).load()) == 40
