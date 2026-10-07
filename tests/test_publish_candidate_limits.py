"""Part limits bound stored-version reads while retaining each part's winner."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from functools import partial
from bili_asr.cli.main import _main

# Exercise the publication worker in-process so fault injection and captured
# output remain local; supervisor process/deadline tests cover the public entry.
main = partial(_main, _publication_worker=True)
from bili_asr.manifest import ManifestStore
from bili_asr.services.transcript_projection import ordered_candidates
from bili_asr.storage import TranscriptRepository, open_database

from test_transcript_repository import (
    CHANGED_BODY,
    _record,
    _run,
    _video_with_parts,
)


def _seed_versions(connection):
    repository = TranscriptRepository(connection)
    # Insert later parts first. The first page of the earlier video holds no
    # transcript, and the captioned pages are gone upstream but still publishable.
    later = _video_with_parts(connection, "BV2LIMIT", (8101, 8102))
    earlier = _video_with_parts(
        connection, "BV1LIMIT", (8201, 8202, 8203), processing_status="gone"
    )
    writes = (
        (later[1], {}),
        (later[0], {}),
        (earlier[2], {}),
        (earlier[1], {}),
        (earlier[1], {"body": CHANGED_BODY}),
        (earlier[1], {"source_kind": "subtitle-ai", "language": "ai-en"}),
        (earlier[1], {"source_kind": "subtitle-ai", "language": "ai-zh"}),
        (earlier[1], {
            "source_kind": "subtitle-ai", "language": "ai-zh", "body": CHANGED_BODY,
        }),
    )
    for index, (part, kwargs) in enumerate(writes, 1):
        _record(repository, part, run_id=_run(repository, index), **kwargs)
    return repository, earlier, later


@pytest.mark.parametrize(
    "selector,limit,expected",
    [
        ((None, None), 1, [("BV1LIMIT", 1)]),
        ((None, None), 2, [("BV1LIMIT", 1), ("BV1LIMIT", 2)]),
        (("BV2LIMIT", None), 1, [("BV2LIMIT", 0)]),
        ((None, 1), 1, [("BV1LIMIT", 1)]),
        (("BV1LIMIT", 2), 1, [("BV1LIMIT", 2)]),
        (("BV1LIMIT", 0), 1, []),
        (("BV1UNKNOWN", None), 1, []),
    ],
)
def test_repository_part_limit_keeps_all_versions_and_selector_order(
    tmp_root, selector, limit, expected,
):
    connection = open_database(tmp_root)
    try:
        repository, _, _ = _seed_versions(connection)
        all_rows = repository.list_stored_transcripts(*selector)
        selected = repository.list_stored_transcripts(*selector, limit_parts=limit)
        actual_parts = list(dict.fromkeys(
            (row["bvid"], row["page_index"]) for row in selected
        ))
        assert actual_parts == expected
        expected_rows = [
            dict(row) for row in all_rows
            if (row["bvid"], row["page_index"]) in expected
        ]
        assert [dict(row) for row in selected] == expected_rows
        assert ordered_candidates(selected) == ordered_candidates(all_rows, limit)
        if expected and expected[0] == ("BV1LIMIT", 1):
            first = ordered_candidates(selected)[0]
            assert (
                first.transcript["source_kind"], first.transcript["language"],
                first.transcript["version"],
            ) == ("subtitle-cc", "zh-CN", 2)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "value,error",
    [(True, TypeError), (1.5, TypeError), ("1", TypeError), (0, ValueError), (-1, ValueError)],
)
def test_repository_part_limit_uses_integer_validation(tmp_root, value, error):
    connection = open_database(tmp_root)
    try:
        with pytest.raises(error):
            TranscriptRepository(connection).list_stored_transcripts(limit_parts=value)
        assert not connection.in_transaction
    finally:
        connection.close()


def test_limit_one_does_not_materialize_unselected_transcript_history(tmp_root):
    connection = open_database(tmp_root)
    try:
        repository, earlier, later = _seed_versions(connection)
        real_factory = connection.row_factory
        materialized = []

        def recording_factory(cursor, values):
            names = {column[0] for column in cursor.description}
            if {"transcript_id", "part_title"} <= names:
                materialized.append(values)
            return real_factory(cursor, values)

        connection.row_factory = recording_factory

        def read_cost(limit):
            steps = [0]

            def count_steps():
                steps[0] += 100
                return 0

            materialized.clear()
            connection.set_progress_handler(count_steps, 100)
            try:
                rows = repository.list_stored_transcripts(limit_parts=limit)
            finally:
                connection.set_progress_handler(None, 0)
            return rows, steps[0], len(materialized)

        before, before_cost, before_count = read_cost(1)
        assert before_count == 5
        # Real valid rows on an unselected part: none may be decoded into Python
        # or sorted through the selected part's version query.
        connection.executemany(
            "INSERT INTO transcripts(video_part_id,source_kind,language,version,"
            "content_sha256,created_at) VALUES (?,'subtitle-ai','ai-zh',?,?,400)",
            (
                (later[1], index + 1, hashlib.sha256(str(index).encode()).hexdigest())
                for index in range(2000)
            ),
        )
        connection.commit()
        after, after_cost, after_count = read_cost(1)
        assert after_count == 5
        assert [dict(row) for row in after] == [dict(row) for row in before]
        assert {row["video_part_id"] for row in after} == {earlier[1]}
        assert after_cost <= max(before_cost * 3, 1000)
        unrestricted, unrestricted_cost, unrestricted_count = read_cost(None)
        assert len(unrestricted) == unrestricted_count == 2008
        assert unrestricted_cost > max(after_cost, 100) * 10
    finally:
        connection.close()


@pytest.mark.parametrize("selector,work_id,row_count", [
    ([], "BV1LIMIT:p1", 5),
    (["--bvid", "BV2LIMIT"], "BV2LIMIT:p0", 1),
    (["--bvid", "BV1LIMIT:p2"], "BV1LIMIT:p2", 1),
])
def test_publish_limits_the_repository_read_and_publishes_the_same_winner(
    tmp_root, monkeypatch, capsys, selector, work_id, row_count,
):
    connection = open_database(tmp_root)
    try:
        _seed_versions(connection)
    finally:
        connection.close()
    actual_reads = []
    real = TranscriptRepository.list_stored_transcripts

    def recording_read(self, *args, **kwargs):
        rows = real(self, *args, **kwargs)
        actual_reads.append((kwargs.get("limit_parts"), len(rows)))
        return rows

    monkeypatch.setattr(TranscriptRepository, "list_stored_transcripts", recording_read)
    assert main([
        "publish-transcripts", "--archive-root", tmp_root, "--limit-parts", "1", *selector,
    ]) == 0
    output = capsys.readouterr().out
    assert "candidates=1 published=1 already_published=0 failed=0" in output
    assert actual_reads == [(1, row_count)]
    rows = ManifestStore(root=tmp_root).load()
    assert list(rows) == [work_id]
    assert rows[work_id]["status"] == "archived"
    if work_id == "BV1LIMIT:p1":
        assert "source=subtitle-cc lang=zh-CN version=2" in output
        text = Path(tmp_root, rows[work_id]["srt_path"]).read_text(encoding="utf-8")
        assert CHANGED_BODY[1][2] in text
