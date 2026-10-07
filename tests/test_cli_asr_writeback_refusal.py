"""Store-backed CLI publication survives a refused acquisition-run write."""

import os
from pathlib import Path
import sqlite3

import pytest

from bili_asr import archive
from bili_asr.cli.main import main
from bili_asr.manifest import ManifestStore
from bili_asr.storage import TranscriptRepository, open_database

from tests.support.cli_asr import _patch_cli, _stub_runner_model
from tests.support.cli_queue_source import _seed_store, _write_audio_file


@pytest.mark.skipif(os.name == "nt", reason="descriptor-safe audio access requires POSIX")
def test_asr_cli_publishes_bundle_when_acquisition_run_is_refused(
    tmp_root, monkeypatch, capsys,
):
    _, identity = _seed_store(tmp_root)
    _write_audio_file(tmp_root, identity)
    _stub_runner_model(monkeypatch, [])
    _patch_cli(monkeypatch)
    refused_runs = []

    def refuse_run(self, record):
        assert record.kind == "asr"
        refused_runs.append(record.run_id)
        raise sqlite3.OperationalError("private-store-path-and-credential")

    # Exercise the real QueueSource.ensure_asr_run refusal boundary, after the
    # metadata and positive audio evidence have been committed to the store.
    monkeypatch.setattr(TranscriptRepository, "start_acquisition_run", refuse_run)
    result = main([
        "asr", "--pending", "--limit", "1", "--keep-audio",
        "--archive-root", tmp_root,
    ])
    assert result == 0
    assert len(refused_runs) == 1
    captured = capsys.readouterr()
    assert f"{identity.work_id}: archived (asr)" in captured.out
    assert captured.err.count("acquisition run refused by the store") == 1
    assert "OperationalError" in captured.err
    assert "archive failed" not in captured.err
    assert "private-store-path-and-credential" not in captured.out + captured.err

    # Check the actual persisted publication, rather than a mocked archive
    # writer or only the command's success message.
    row = ManifestStore(tmp_root).get(identity.work_id)
    assert row["status"] == "archived"
    paths = {key: row[key] for key in ("srt_path", "txt_path", "md_path", "raw_path")}
    assert archive.archive_bundle_complete(tmp_root, paths)
    assert all(Path(tmp_root, path).is_file() for path in paths.values())
    assert Path(tmp_root, row["txt_path"]).read_text(encoding="utf-8").strip()

    connection = open_database(tmp_root)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM transcripts AS t "
            "JOIN video_parts AS p ON p.video_part_id=t.video_part_id "
            "WHERE p.bvid=? AND p.page_index=?",
            (identity.bvid, identity.page_index),
        ).fetchone()[0]
        assert count == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM acquisition_runs WHERE kind='asr'",
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM v_missing_transcript WHERE bvid=? AND page_index=?",
            (identity.bvid, identity.page_index),
        ).fetchone()[0] == 1
    finally:
        connection.close()
