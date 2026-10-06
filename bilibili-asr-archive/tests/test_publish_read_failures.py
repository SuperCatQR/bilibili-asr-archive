"""A failed completeness read cannot authorize replacing a real archive."""

import errno
import os
import tempfile
from pathlib import Path

import pytest

from bili_asr import archive
from bili_asr.manifest import ManifestStore
from tests.support.cli_publish_transcripts import (
    CHAIN_BVID,
    FRESH_BVID,
    _bundle_hashes,
    _chain_archive,
    _declared,
    _publish,
    _seed_archive,
    _store_caption,
)
from tests.support.publish_read_failures import _existing_bundle, _fail_one_read






@pytest.mark.parametrize("site", ["marker", "artifact"])
@pytest.mark.parametrize("error_number", [errno.EIO, errno.EACCES])
def test_publish_preserves_complete_bundle_when_its_read_is_inconclusive(
    tmp_root, monkeypatch, capsys, site, error_number
):
    paths = _existing_bundle(tmp_root)
    assert archive.archive_bundle_complete(tmp_root, paths)
    before_bundle = _bundle_hashes(tmp_root, paths)
    before_rows = ManifestStore(root=tmp_root).load()
    target = (
        archive.bundle_marker_path(Path(tmp_root) / paths["srt_path"])
        if site == "marker"
        else Path(tmp_root) / paths["txt_path"]
    )
    pending = _fail_one_read(
        monkeypatch, target, OSError(error_number, "private device/path detail")
    )
    monkeypatch.setattr(
        archive, "write_archive", lambda *args, **kwargs: pytest.fail("overwrote existing archive")
    )

    assert _publish(tmp_root, "--bvid", CHAIN_BVID) == 1
    captured = capsys.readouterr()
    assert not pending[0]
    error_name = type(OSError(error_number, "")).__name__
    assert captured.out.splitlines() == [
        f"{CHAIN_BVID}:p0: failed ({error_name})",
        "publish-transcripts: candidates=1 published=0 already_published=0 failed=1",
    ]
    assert captured.err == ""
    assert _bundle_hashes(tmp_root, paths) == before_bundle
    assert ManifestStore(root=tmp_root).load() == before_rows
    assert archive.archive_bundle_complete(tmp_root, paths)


def test_inconclusive_bundle_read_does_not_block_another_candidate(
    tmp_root, monkeypatch, capsys
):
    paths = _existing_bundle(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    before = _bundle_hashes(tmp_root, paths)
    pending = _fail_one_read(
        monkeypatch, Path(tmp_root) / paths["srt_path"], OSError(errno.EIO, "device error")
    )
    assert _publish(tmp_root) == 1
    output = capsys.readouterr().out
    assert not pending[0]
    assert f"{CHAIN_BVID}:p0: failed (OSError)" in output
    assert f"{FRESH_BVID}:p0: published" in output
    assert output.endswith("candidates=2 published=1 already_published=0 failed=1\n")
    assert _bundle_hashes(tmp_root, paths) == before
    assert archive.archive_bundle_complete(tmp_root, _declared(tmp_root, f"{FRESH_BVID}:p0"))


def test_boolean_bundle_reader_keeps_compatibility_but_strict_reader_raises(
    tmp_root, monkeypatch
):
    paths = _existing_bundle(tmp_root)
    target = Path(tmp_root) / paths["txt_path"]
    with monkeypatch.context() as patch:
        pending = _fail_one_read(patch, target, OSError(errno.EIO, "device error"))
        assert archive.archive_bundle_complete(tmp_root, paths) is False
        assert not pending[0]
    with monkeypatch.context() as patch:
        pending = _fail_one_read(patch, target, OSError(errno.EIO, "device error"))
        with pytest.raises(OSError) as error:
            archive.archive_bundle_complete(tmp_root, paths, require_readable=True)
        assert error.value.errno == errno.EIO
        assert not pending[0]
    assert archive.archive_bundle_complete(tmp_root, paths, require_readable=True)


@pytest.mark.parametrize("damage", ["missing_marker", "missing_artifact", "invalid_marker", "oversized_marker", "corrupt_artifact"])
def test_publish_still_repairs_a_proven_incomplete_bundle(tmp_root, capsys, damage):
    paths = _existing_bundle(tmp_root)
    marker = archive.bundle_marker_path(Path(tmp_root) / paths["srt_path"])
    target = Path(tmp_root) / paths["txt_path"]
    if damage == "missing_marker":
        marker.unlink()
    elif damage == "missing_artifact":
        target.unlink()
    elif damage == "invalid_marker":
        marker.write_text("[]", encoding="ascii")
    elif damage == "oversized_marker":
        marker.write_bytes(b"x" * 9000)
    else:
        target.write_text("observed damaged text", encoding="utf-8")
    assert archive.archive_bundle_complete(tmp_root, paths, require_readable=True) is False
    assert _publish(tmp_root, "--bvid", CHAIN_BVID) == 0
    assert "candidates=1 published=1 already_published=0 failed=0" in capsys.readouterr().out
    assert archive.archive_bundle_complete(tmp_root, paths, require_readable=True)


def test_publish_reports_a_post_write_read_failure_without_recording_completion(
    tmp_root, monkeypatch, capsys
):
    _seed_archive(tmp_root)
    _store_caption(tmp_root, FRESH_BVID, 0)
    real_write = archive.write_archive
    injected = []

    def write_then_fail_read(*args, **kwargs):
        paths = real_write(*args, **kwargs)
        injected.append(_fail_one_read(
            monkeypatch, Path(tmp_root) / paths["txt_path"], OSError(errno.EIO, "device error")
        ))
        return paths

    monkeypatch.setattr(archive, "write_archive", write_then_fail_read)
    assert _publish(tmp_root, "--bvid", FRESH_BVID) == 1
    assert injected and not injected[0][0]
    assert f"{FRESH_BVID}:p0: failed (OSError)" in capsys.readouterr().out
    assert ManifestStore(root=tmp_root).load() == {}


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX named pipes")
def test_marker_fifo_is_rejected_without_waiting_for_a_writer():
    # Native /tmp supports FIFOs; the WSL workspace on /mnt/c does not.
    with tempfile.TemporaryDirectory(prefix="bili-asr-marker-fifo-", dir="/tmp") as root:
        paths = _existing_bundle(root)
        marker = archive.bundle_marker_path(Path(root) / paths["srt_path"])
        marker.unlink()
        os.mkfifo(marker)
        assert archive.archive_bundle_complete(root, paths) is False
        assert archive.archive_bundle_complete(root, paths, require_readable=True) is False


def test_regular_marker_size_limit_applies_before_json_decode(tmp_root):
    paths = _existing_bundle(tmp_root)
    marker = archive.bundle_marker_path(Path(tmp_root) / paths["srt_path"])
    # Still valid JSON, so acceptance would expose an unbounded marker read.
    marker.write_bytes(marker.read_bytes() + b" " * archive._MARKER_MAX_BYTES)
    assert archive.archive_bundle_complete(tmp_root, paths) is False
    assert archive.archive_bundle_complete(tmp_root, paths, require_readable=True) is False
