"""Tests for SQLite FTS5 search index and CLI search command."""

from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

from bili_asr.cli import main
from bili_asr.manifest import ManifestStore
from bili_asr.search_index import (
    COMPLETED_STATUSES,
    FTS5UnavailableError,
    SearchIndex,
    SearchResult,
    check_fts5_available,
)


def _create_sample_archive(tmp_root: str):
    """Helper to create a populated mock archive with manifest and transcript files."""
    store = ManifestStore(root=tmp_root)
    # Ensure dirs exist
    txt_dir = os.path.join(tmp_root, "transcripts", "txt")
    srt_dir = os.path.join(tmp_root, "transcripts", "srt")
    os.makedirs(txt_dir, exist_ok=True)
    os.makedirs(srt_dir, exist_ok=True)

    # 1. Archived entry with txt file (ASR branch)
    e1 = {
        "bvid": "BV1hegel",
        "work_id": "BV1hegel:p0",
        "page_index": 0,
        "cid": 101,
        "title": "Hegel Philosophy Dialectics",
        "status": "archived",
        "duration_s": 360,
        "txt_path": os.path.join("transcripts", "txt", "BV1hegel.p0.txt"),
        "srt_path": os.path.join("transcripts", "srt", "BV1hegel.p0.srt"),
    }
    with open(os.path.join(tmp_root, e1["txt_path"]), "w", encoding="utf-8") as fh:
        fh.write("Today we study Hegel phenomenology of spirit and dialectical idealism.")
    with open(os.path.join(tmp_root, e1["srt_path"]), "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,000 --> 00:00:05,000\nToday we study Hegel phenomenology of spirit.\n")

    # 2. Subtitle_done entry with srt file (Subtitle branch)
    e2 = {
        "bvid": "BV1kant",
        "work_id": "BV1kant:p0",
        "page_index": 0,
        "cid": 102,
        "title": "Kant Critique of Pure Reason",
        "status": "subtitle_done",
        "duration_s": 420,
        "srt_path": os.path.join("transcripts", "srt", "BV1kant.p0.srt"),
    }
    with open(os.path.join(tmp_root, e2["srt_path"]), "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,000 --> 00:00:04,000\nKant examines synthetic a priori propositions.\n\n2\n00:00:04,500 --> 00:00:08,000\nTranscendental aesthetic and logic.\n")

    # 3. Audio_ok entry (should NOT be indexed)
    e3 = {
        "bvid": "BV1audio",
        "work_id": "BV1audio:p0",
        "page_index": 0,
        "cid": 103,
        "title": "Unprocessed Audio Lecture",
        "status": "audio_ok",
        "duration_s": 500,
        "audio_path": "audio/BV1audio.p0.m4a",
    }

    # 4. Needs_audio entry (should NOT be indexed)
    e4 = {
        "bvid": "BV1need",
        "work_id": "BV1need:p0",
        "page_index": 0,
        "cid": 104,
        "title": "Needs Audio Download",
        "status": "needs_audio",
        "duration_s": 200,
    }

    # 5. Meta_ok entry (should NOT be indexed)
    e5 = {
        "bvid": "BV1meta",
        "work_id": "BV1meta:p0",
        "page_index": 0,
        "cid": 105,
        "title": "Meta Enumerated Only",
        "status": "meta_ok",
        "duration_s": 150,
    }

    # 6. Multi-part page 1 (archived)
    e6 = {
        "bvid": "BV1hegel",
        "work_id": "BV1hegel:p1",
        "page_index": 1,
        "cid": 106,
        "title": "Hegel Science of Logic",
        "status": "archived",
        "duration_s": 480,
        "txt_path": os.path.join("transcripts", "txt", "BV1hegel.p1.txt"),
    }
    with open(os.path.join(tmp_root, e6["txt_path"]), "w", encoding="utf-8") as fh:
        fh.write("Being nothing and becoming in Hegel science of logic.")

    # 7. Archived entry with NO paths anywhere (should NOT be indexed)
    e7 = {
        "bvid": "BV1nopaths",
        "work_id": "BV1nopaths:p0",
        "page_index": 0,
        "cid": 107,
        "title": "Missing Files on Disk",
        "status": "archived",
        "duration_s": 100,
    }

    for e in (e1, e2, e3, e4, e5, e6, e7):
        store.upsert(e)

    return store


# ---------------------------------------------------------------- Basic & Prerequisite Tests


def test_fts5_prerequisite_available():
    """Verify that SQLite FTS5 is available in this test environment."""
    assert check_fts5_available(), "SQLite FTS5 must be available in the test environment"


def test_search_index_uninitialized(tmp_root):
    """Uninitialized SearchIndex returns 0 count, is_stale True, and empty search."""
    index = SearchIndex(root=tmp_root)
    assert index.count() == 0
    assert index.is_stale() is True
    assert index.search("test", auto_build=False) == []


# ---------------------------------------------------------------- Build & Filter Rules Tests


def test_build_indexes_only_completed_transcripts_with_paths(tmp_root):
    """Index only completed transcript rows (archived / subtitle_done with paths)."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)

    indexed_count = index.build(store.load())
    # Expected: e1 (BV1hegel:p0), e2 (BV1kant:p0), e6 (BV1hegel:p1) -> 3 rows
    # Excluded: e3 (audio_ok), e4 (needs_audio), e5 (meta_ok), e7 (archived but no files)
    assert indexed_count == 3
    assert index.count() == 3


def test_build_is_idempotent(tmp_root):
    """Rebuilding the index multiple times is deterministic and safe."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)

    count1 = index.build(store.load())
    count2 = index.build(store.load(), force=True)
    count3 = index.build()  # auto-loads from store

    assert count1 == 3
    assert count2 == 3
    assert count3 == 3
    assert index.count() == 3


def test_manifest_remains_unmodified_during_build_and_search(tmp_root):
    """Index build and search must never modify the manifest file."""
    store = _create_sample_archive(tmp_root)
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        original_manifest = fh.read()

    index = SearchIndex(root=tmp_root)
    index.build(store.load())
    index.search("Hegel")
    index.search("Kant")

    with open(manifest_path, "r", encoding="utf-8") as fh:
        after_manifest = fh.read()

    assert original_manifest == after_manifest


# ---------------------------------------------------------------- Search & Ranking Tests


def test_search_by_transcript_content(tmp_root):
    """Searching matches words in the transcript text."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    results = index.search("phenomenology")
    assert len(results) == 1
    assert results[0].work_id == "BV1hegel:p0"
    assert results[0].status == "archived"
    assert results[0].title == "Hegel Philosophy Dialectics"
    assert results[0].path == os.path.join("transcripts", "txt", "BV1hegel.p0.txt")


def test_search_by_title_and_work_id(tmp_root):
    """Searching matches words in title and work_id."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    # Match by title word
    kant_hits = index.search("Critique")
    assert len(kant_hits) == 1
    assert kant_hits[0].work_id == "BV1kant:p0"
    assert kant_hits[0].status == "subtitle_done"

    # Match by work_id prefix
    work_id_hits = index.search("BV1kant*")
    assert len(work_id_hits) == 1
    assert work_id_hits[0].work_id == "BV1kant:p0"


def test_search_ranking_and_multiple_hits(tmp_root):
    """Searching returns ranked results for terms matching multiple documents."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    # 'Hegel' is present in both BV1hegel:p0 and BV1hegel:p1
    results = index.search("Hegel")
    assert len(results) == 2
    work_ids = [r.work_id for r in results]
    assert "BV1hegel:p0" in work_ids
    assert "BV1hegel:p1" in work_ids
    # Verify score is a float
    assert all(isinstance(r.score, float) for r in results)


def test_search_limit_bounded(tmp_root):
    """Search respects the limit parameter."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    results = index.search("Hegel", limit=1)
    assert len(results) == 1

    results_zero = index.search("Hegel", limit=0)
    assert results_zero == []

    results_neg = index.search("Hegel", limit=-5)
    assert results_neg == []


def test_search_no_results(tmp_root):
    """Non-matching query returns empty list."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    assert index.search("Aristotle") == []
    assert index.search("") == []
    assert index.search("   ") == []


def test_search_special_characters_syntax_safety(tmp_root):
    """Queries with special characters or unclosed quotes do not crash."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    # Special syntax that could trigger FTS5 syntax errors
    assert isinstance(index.search('"unclosed quote'), list)
    assert isinstance(index.search('AND OR NOT'), list)
    assert isinstance(index.search('Hegel:p0'), list)
    assert isinstance(index.search('BV1hegel*'), list)


def test_search_cjk_chinese_text(tmp_root):
    """Indexing and searching CJK / Chinese text content."""
    store = ManifestStore(root=tmp_root)
    os.makedirs(os.path.join(tmp_root, "transcripts", "txt"), exist_ok=True)

    e = {
        "bvid": "BV1wmz",
        "work_id": "BV1wmz:p0",
        "page_index": 0,
        "cid": 888,
        "title": "未明子 讲 黑格尔 精神现象学",
        "status": "archived",
        "duration_s": 600,
        "txt_path": "transcripts/txt/BV1wmz.p0.txt",
    }
    with open(os.path.join(tmp_root, e["txt_path"]), "w", encoding="utf-8") as fh:
        fh.write("今天 我们 讨论 辩证法 与 绝对精神")
    store.upsert(e)

    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    res1 = index.search("未明子")
    assert len(res1) == 1
    assert res1[0].work_id == "BV1wmz:p0"

    res2 = index.search("辩证法")
    assert len(res2) == 1
    assert res2[0].work_id == "BV1wmz:p0"


def test_extract_transcript_from_raw_subtitles_json(tmp_root):
    """Extract transcript text when only subtitles/raw/{stem}.json is present."""
    store = ManifestStore(root=tmp_root)
    raw_sub_dir = os.path.join(tmp_root, "subtitles", "raw")
    os.makedirs(raw_sub_dir, exist_ok=True)

    e = {
        "bvid": "BV1rawsub",
        "work_id": "BV1rawsub:p0",
        "page_index": 0,
        "cid": 555,
        "title": "Raw Subtitle Test",
        "status": "subtitle_done",
        "duration_s": 180,
    }
    raw_path = os.path.join(raw_sub_dir, "BV1rawsub.p0.json")
    with open(raw_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "body": [
                    {"from": 0.0, "to": 2.0, "content": "Raw subtitle snippet"},
                    {"from": 2.0, "to": 4.0, "content": "Second sentence content"},
                ]
            },
            fh,
        )
    store.upsert(e)

    index = SearchIndex(root=tmp_root)
    count = index.build(store.load())
    assert count == 1

    hits = index.search("snippet")
    assert len(hits) == 1
    assert hits[0].work_id == "BV1rawsub:p0"


def test_extract_transcript_from_raw_asr_json(tmp_root):
    """Extract transcript text when only transcripts/raw/{stem}.json is present."""
    store = ManifestStore(root=tmp_root)
    raw_asr_dir = os.path.join(tmp_root, "transcripts", "raw")
    os.makedirs(raw_asr_dir, exist_ok=True)

    e = {
        "bvid": "BV1rawasr",
        "work_id": "BV1rawasr:p0",
        "page_index": 0,
        "cid": 777,
        "title": "Raw ASR Test",
        "status": "archived",
        "duration_s": 240,
        "raw_path": "transcripts/raw/BV1rawasr.p0.json",
    }
    raw_path = os.path.join(raw_asr_dir, "BV1rawasr.p0.json")
    with open(raw_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "source": "asr",
                "segments": [
                    {"start": 0.0, "end": 2.0, "text": "Raw ASR recognized text segment"},
                ],
            },
            fh,
        )
    store.upsert(e)

    index = SearchIndex(root=tmp_root)
    count = index.build(store.load())
    assert count == 1

    hits = index.search("recognized")
    assert len(hits) == 1
    assert hits[0].work_id == "BV1rawasr:p0"


def test_legacy_bare_bvid_indexing(tmp_root):
    """Archived legacy bare-bvid entries are indexed using bare bvid stem."""
    store = ManifestStore(root=tmp_root)
    os.makedirs(os.path.join(tmp_root, "transcripts", "txt"), exist_ok=True)

    e = {
        "bvid": "BV1barelegacy",
        "title": "Legacy Bare Bvid Lecture",
        "status": "archived",
        "duration_s": 150,
        "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "txt_path": "transcripts/txt/BV1barelegacy.txt",
    }
    with open(os.path.join(tmp_root, e["txt_path"]), "w", encoding="utf-8") as fh:
        fh.write("Legacy archival content without work_id.")
    store.upsert(e)

    index = SearchIndex(root=tmp_root)
    count = index.build(store.load())
    assert count == 1

    hits = index.search("archival")
    assert len(hits) == 1
    assert hits[0].work_id == "BV1barelegacy"


# ---------------------------------------------------------------- Stale Detection Tests


def test_stale_detection_lifecycle(tmp_root):
    """Test is_stale() transitions: missing -> fresh -> modified manifest -> fresh."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)

    # 1. Before build: missing db is stale
    assert index.is_stale() is True

    # 2. After build: fresh
    index.build(store.load())
    assert index.is_stale() is False

    # 3. Simulate older db by setting db mtime back in the past
    past_time = time.time() - 100
    os.utime(index.db_path, (past_time, past_time))
    assert index.is_stale() is True

    # 4. Rebuild restores freshness
    index.build(store.load())
    assert index.is_stale() is False

    # 5. Row count change makes it stale
    e_new = {
        "bvid": "BV1new",
        "work_id": "BV1new:p0",
        "page_index": 0,
        "cid": 999,
        "title": "New Aristotle Transcript",
        "status": "archived",
        "txt_path": "transcripts/txt/BV1new.p0.txt",
    }
    txt_path = os.path.join(tmp_root, "transcripts", "txt", "BV1new.p0.txt")
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write("Aristotle Nicomachean Ethics.")
    store.upsert(e_new)

    assert index.is_stale() is True
    index.build(store.load())
    assert index.is_stale() is False
    assert index.count() == 4


# ---------------------------------------------------------------- CLI Command Tests


def test_cli_search_matching_results(tmp_root, capsys):
    """bili-asr search <query> prints matching rows and exits 0."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Hegel", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    assert "BV1hegel:p0" in out
    assert "Hegel Philosophy Dialectics" in out
    assert "[archived]" in out


def test_cli_search_no_results_exits_one(tmp_root, capsys):
    """bili-asr search <query> with no matches prints message to stderr and exits 1."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Nietzsche", "--archive-root", tmp_root])
    assert code == 1
    err = capsys.readouterr().err
    assert "no matching transcripts found" in err


def test_cli_search_with_limit(tmp_root, capsys):
    """bili-asr search <query> --limit N bounds the output."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Hegel", "--limit", "1", "--archive-root", tmp_root])
    assert code == 0
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(lines) == 1


def test_cli_search_with_rebuild(tmp_root, capsys):
    """bili-asr search <query> --rebuild forces index rebuild and exits 0."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Kant", "--rebuild", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    assert "BV1kant:p0" in out
    assert "[subtitle_done]" in out


def test_cli_search_auto_builds_when_missing(tmp_root, capsys):
    """bili-asr search builds index automatically if search.db does not exist."""
    _create_sample_archive(tmp_root)
    db_path = os.path.join(tmp_root, "search.db")
    assert not os.path.exists(db_path)

    code = main(["search", "Kant", "--archive-root", tmp_root])
    assert code == 0
    assert os.path.exists(db_path)
    out = capsys.readouterr().out
    assert "BV1kant:p0" in out


def test_cli_search_missing_query_arg_exits_one(tmp_root, capsys):
    """bili-asr search without query exits 1 (usage error)."""
    with pytest.raises(SystemExit) as exc:
        main(["search", "--archive-root", tmp_root])
    assert exc.value.code == 1


def test_fts5_unavailable_error_handling(tmp_root, monkeypatch, capsys):
    """When FTS5 is not available in SQLite, clear error is raised/handled."""
    _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)

    real_connect = sqlite3.connect

    class FakeConn:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def execute(self, sql, *args):
            if "USING fts5" in sql or "_test_fts5" in sql:
                raise sqlite3.OperationalError("no such module: fts5")
            return self._real_conn.execute(sql, *args)

        def commit(self):
            return self._real_conn.commit()

        def close(self):
            return self._real_conn.close()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_connect(*args, **kwargs):
        return FakeConn(real_connect(*args, **kwargs))

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    with pytest.raises(FTS5UnavailableError, match="SQLite FTS5 extension is not available"):
        index.build()

    code = main(["search", "test", "--archive-root", tmp_root])
    assert code == 1
    err = capsys.readouterr().err
    assert "FTS5" in err or "SQLite" in err
