"""Real damaged store rows must not strand the other publication candidates."""

from __future__ import annotations

from pathlib import Path

import pytest

from bili_asr.archive import archive_bundle_complete
from bili_asr.cli.main import main
from bili_asr.manifest import ManifestStore
from bili_asr.storage import TranscriptRepository, open_database

from tests.support.transcript_repository import _record, _run, _video_with_parts


def _seed(root: Path, damage: str) -> tuple[str, int]:
    connection = open_database(root)
    try:
        repository = TranscriptRepository(connection)
        run = _run(repository, 1)
        bvid = "BV1:BAD" if damage == "identity" else "BV1BAD"
        bad = _video_with_parts(
            connection, bvid, (901,),
            pubdate=2**63 - 1 if damage == "pubdate" else 1_700_000_000,
        )[0]
        _record(repository, bad, run_id=run)
        good = _video_with_parts(connection, "BV2GOOD", (902,))[0]
        _record(repository, good, run_id=run)
        if damage == "source_kind":
            # A fourth kind simulates a damaged/foreign database. Two versions
            # actually enter _winner_key; one row alone never compares ranks.
            _record(repository, bad, run_id=_run(repository, 2), language="en")
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE transcripts SET source_kind='unknown-secret-kind' "
                "WHERE video_part_id=? AND language='zh-CN'", (bad,),
            )
            connection.commit()
        return bvid, bad
    finally:
        connection.close()


@pytest.mark.parametrize("damage", ["pubdate", "identity", "source_kind"])
@pytest.mark.parametrize("pending", [False, True])
def test_bad_projection_or_entry_is_one_failed_candidate(
    tmp_root, capsys, damage: str, pending: bool,
):
    bvid, part_id = _seed(tmp_root, damage)
    database = Path(tmp_root) / "archive.db"
    before = database.read_bytes()
    extra = ["--pending", "--limit-parts", "2"] if pending else []

    assert main(["publish-transcripts", "--archive-root", str(tmp_root), *extra]) == 1

    output = capsys.readouterr().out
    bad_label = f"part:{part_id}" if damage == "identity" else f"{bvid}:p0"
    assert f"{bad_label}: failed (" in output
    assert "BV2GOOD:p0: published" in output
    assert "unknown-secret-kind" not in output
    assert output.endswith(
        "candidates=2 published=1 already_published=0 failed=1\n"
    )
    rows = ManifestStore(root=tmp_root).load()
    assert list(rows) == ["BV2GOOD:p0"]
    assert archive_bundle_complete(tmp_root, {
        key: rows["BV2GOOD:p0"][key]
        for key in ("srt_path", "txt_path", "md_path", "raw_path")
    })
    assert database.read_bytes() == before


@pytest.mark.parametrize("damage", ["pubdate", "identity", "source_kind"])
def test_bad_pending_candidate_consumes_the_finite_attempt_budget(
    tmp_root, capsys, damage: str,
):
    _seed(tmp_root, damage)

    assert main([
        "publish-transcripts", "--archive-root", str(tmp_root),
        "--pending", "--limit-parts", "1",
    ]) == 1

    assert capsys.readouterr().out.endswith(
        "candidates=1 published=0 already_published=0 failed=1\n"
    )
    assert ManifestStore(root=tmp_root).load() == {}
    assert not (Path(tmp_root) / "transcripts" / "BV2GOOD.p0").exists()


def test_pending_cursor_advances_past_a_full_batch_of_invalid_work_ids(tmp_root, capsys):
    connection = open_database(tmp_root)
    try:
        repository = TranscriptRepository(connection)
        run = _run(repository, 1)
        for index in range(32):
            part = _video_with_parts(connection, f"BV1:BAD{index:02}", (1000 + index,))[0]
            _record(repository, part, run_id=run)
        good = _video_with_parts(connection, "BV2GOOD", (1100,))[0]
        _record(repository, good, run_id=run)
    finally:
        connection.close()

    assert main([
        "publish-transcripts", "--archive-root", str(tmp_root), "--pending",
    ]) == 1

    output = capsys.readouterr().out
    assert output.count(": failed (ValueError)") == 32
    assert "BV2GOOD:p0: published" in output
    assert output.endswith(
        "candidates=33 published=1 already_published=0 failed=32\n"
    )
    assert list(ManifestStore(root=tmp_root).load()) == ["BV2GOOD:p0"]
