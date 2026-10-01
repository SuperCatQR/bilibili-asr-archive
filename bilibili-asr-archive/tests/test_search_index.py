"""Tests for the legacy manifest-backed FTS5 index (``SearchIndex``).

The manifest-backed surface stays behind the `search` command's legacy
flags; the store-backed layer this plan migrates to is pinned in
``test_search.py``.  Explicit ``auto_build`` values keep these tests honest
under either default.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

from bili_asr.artifact_root import ArtifactRoots
from bili_asr.cli import main
from bili_asr.manifest import ManifestStore
from bili_asr.search_index import (
    COMPLETED_STATUSES,
    FTS5UnavailableError,
    SearchIndex,
    SearchQuery,
    SearchResult,
    check_fts5_available,
    search,
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
        "source": "asr",
        "pubdate": 1600000000,
        "txt_path": os.path.join("transcripts", "BV1hegel.p0", "bundle.txt"),
        "srt_path": os.path.join("transcripts", "BV1hegel.p0", "bundle.srt"),
    }
    os.makedirs(os.path.dirname(os.path.join(tmp_root, e1["txt_path"])), exist_ok=True)
    with open(os.path.join(tmp_root, e1["txt_path"]), "w", encoding="utf-8") as fh:
        fh.write("Today we study Hegel phenomenology of spirit and dialectical idealism.")
    os.makedirs(os.path.dirname(os.path.join(tmp_root, e1["srt_path"])), exist_ok=True)
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
        "source": "subtitle",
        "sub_lan": "ai-zh",
        "pubdate": 1600000100,
        "srt_path": os.path.join("transcripts", "BV1kant.p0", "bundle.srt"),
    }
    os.makedirs(os.path.dirname(os.path.join(tmp_root, e2["srt_path"])), exist_ok=True)
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
        "source": "asr",
        "pubdate": 1600000200,
        "txt_path": os.path.join("transcripts", "BV1hegel.p1", "bundle.txt"),
    }
    os.makedirs(os.path.dirname(os.path.join(tmp_root, e6["txt_path"])), exist_ok=True)
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
    assert index.search("test") == []


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
    assert results[0].path == os.path.join("transcripts", "BV1hegel.p0", "bundle.txt")


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
    os.makedirs(os.path.join(tmp_root, "transcripts"), exist_ok=True)

    e = {
        "bvid": "BV1wmz",
        "work_id": "BV1wmz:p0",
        "page_index": 0,
        "cid": 888,
        "title": "未明子 讲 黑格尔 精神现象学",
        "status": "archived",
        "duration_s": 600,
        "txt_path": "transcripts/BV1wmz.p0/bundle.txt",
    }
    os.makedirs(os.path.dirname(os.path.join(tmp_root, e["txt_path"])), exist_ok=True)
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
    """Extract transcript text when only transcripts/{stem}/bundle.raw.json is present."""
    store = ManifestStore(root=tmp_root)
    raw_asr_dir = os.path.join(tmp_root, "transcripts", "BV1rawasr.p0")
    os.makedirs(raw_asr_dir, exist_ok=True)

    e = {
        "bvid": "BV1rawasr",
        "work_id": "BV1rawasr:p0",
        "page_index": 0,
        "cid": 777,
        "title": "Raw ASR Test",
        "status": "archived",
        "duration_s": 240,
        "raw_path": "transcripts/BV1rawasr.p0/bundle.raw.json",
    }
    raw_path = os.path.join(raw_asr_dir, "bundle.raw.json")
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
    os.makedirs(os.path.join(tmp_root, "transcripts"), exist_ok=True)

    e = {
        "bvid": "BV1barelegacy",
        "title": "Legacy Bare Bvid Lecture",
        "status": "archived",
        "duration_s": 150,
        "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "txt_path": "transcripts/BV1barelegacy/bundle.txt",
    }
    os.makedirs(os.path.dirname(os.path.join(tmp_root, e["txt_path"])), exist_ok=True)
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
        "txt_path": "transcripts/BV1new.p0/bundle.txt",
    }
    txt_path = os.path.join(tmp_root, "transcripts", "txt", "BV1new.p0.txt")
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write("Aristotle Nicomachean Ethics.")
    store.upsert(e_new)

    assert index.is_stale() is True
    index.build(store.load())
    assert index.is_stale() is False
    assert index.count() == 4


def test_is_stale_mtime_short_circuits_before_load(tmp_root, monkeypatch):
    """is_stale() returns True based on mtime without loading manifest entries."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    # Simulate older db by setting db mtime back in the past
    past_time = time.time() - 100
    os.utime(index.db_path, (past_time, past_time))

    load_called = False

    def fake_load(self):
        nonlocal load_called
        load_called = True
        raise RuntimeError("store.load() should not be called when mtime is stale")

    monkeypatch.setattr(ManifestStore, "load", fake_load)

    # Should return True without calling ManifestStore.load()
    assert index.is_stale() is True
    assert not load_called


def test_is_stale_journal_append_without_snapshot_change(tmp_root):
    """Journal append (upsert) with unchanged snapshot mtime makes is_stale() True."""
    store = _create_sample_archive(tmp_root)
    index = SearchIndex(root=tmp_root)
    index.build(store.load())
    assert index.is_stale() is False

    # Materialize the snapshot so the upsert below is a pure journal append;
    # then pin snapshot + db mtimes so only the journal can be newer.
    store.save()
    past_time = time.time() - 100
    os.utime(index.db_path, (past_time, past_time))
    os.utime(index.manifest_path, (past_time, past_time))

    # Same-count change: journal append only, snapshot untouched.  BV1audio
    # is audio_ok (not indexable), so the completed-count check cannot
    # short-circuit the journal-mtime check this test exercises.
    store.upsert(
        {
            "bvid": "BV1audio",
            "work_id": "BV1audio:p0",
            "page_index": 0,
            "cid": 103,
            "title": "Unprocessed Audio Lecture",
            "status": "audio_ok",
            "duration_s": 501,
            "audio_path": "audio/BV1audio.p0.m4a",
        }
    )

    assert os.path.isfile(index.journal_path)
    assert index.is_stale() is True

    # Rebuild folds the journal back in and restores freshness.
    index.build(store.load())
    assert index.is_stale() is False


# ---------------------------------------------------------------- CLI Command Tests


def test_cli_search_matching_results(tmp_root, capsys):
    """bili-asr search <query> prints matching rows and exits 0."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Hegel", "--status", "archived", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    assert "BV1hegel" in out


def test_cli_search_no_results_exits_zero_with_explicit_line(tmp_root, capsys):
    """No matches is healthy (exit 0) with an explicit "no hits" line."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Nietzsche", "--status", "archived", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    assert "no hits" in out


def test_cli_search_with_limit(tmp_root, capsys):
    """bili-asr search <query> --limit N bounds the output."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Hegel", "--status", "archived", "--limit", "1", "--archive-root", tmp_root])
    assert code == 0
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(lines) == 1


def test_cli_search_with_rebuild(tmp_root, capsys):
    """bili-asr search <query> --rebuild re-runs the index build and exits 0."""
    _create_sample_archive(tmp_root)
    code = main(["search", "Kant", "--status", "subtitle_done", "--rebuild", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    assert "BV1kant" in out


def test_cli_search_never_auto_builds_when_index_missing(tmp_root, capsys):
    """Read paths never auto-create the index; a missing index is exit 0."""
    _create_sample_archive(tmp_root)
    db_path = os.path.join(tmp_root, "archive.db")
    assert not os.path.exists(db_path)

    code = main(["search", "Kant", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    assert "index missing" in out
    assert "search-index" in out


def test_cli_search_missing_query_arg_is_usage_error(tmp_root, capsys):
    """bili-asr search without query is a usage error (argparse exit 1)."""
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

        def executescript(self, sql):
            return self._real_conn.executescript(sql)

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

    code = main(["search-index", "--archive-root", tmp_root])
    assert code == 1
    err = capsys.readouterr().err
    assert "FTS5" in err or "SQLite" in err


# ---------------------------------------------------------------- SearchQuery & Public search() Tests


def test_public_search_function_interface(tmp_root):
    """Test public search(archive_root, query) surface with SearchQuery and str."""
    _create_sample_archive(tmp_root)

    # 1. Calling search with SearchQuery object
    sq = SearchQuery(query="Hegel", limit=10)
    results = search(tmp_root, sq)
    assert isinstance(results, list)
    assert len(results) == 2
    for r in results:
        assert isinstance(r, dict)
        assert "work_id" in r
        assert "bvid" in r
        assert "title" in r
        assert "status" in r
        assert "score" in r
        assert "path" in r
        assert "duration_s" in r
        assert "transcript_snippet" in r
        assert "archive_paths" in r
        assert isinstance(r["score"], float)
        assert isinstance(r["archive_paths"], dict)

    # 2. Calling search with string
    results_str = search(tmp_root, "Kant")
    assert len(results_str) == 1
    assert results_str[0]["work_id"] == "BV1kant:p0"
    assert results_str[0]["status"] == "subtitle_done"


def test_search_query_status_filters(tmp_root):
    """Filter search results by manifest status."""
    _create_sample_archive(tmp_root)

    # Filter for archived only
    res_archived = search(tmp_root, SearchQuery(status="archived"))
    assert len(res_archived) == 2
    assert all(r["status"] == "archived" for r in res_archived)

    # Filter for subtitle_done only
    res_sub = search(tmp_root, SearchQuery(status=["subtitle_done"]))
    assert len(res_sub) == 1
    assert res_sub[0]["work_id"] == "BV1kant:p0"

    # Multi-status filter (comma-separated or collection)
    res_both = search(tmp_root, SearchQuery(status="archived,subtitle_done"))
    assert len(res_both) == 3

    # Incomplete status that is not indexed yields 0 hits
    res_meta = search(tmp_root, SearchQuery(status="meta_ok"))
    assert res_meta == []


def test_search_query_source_and_language_filters(tmp_root):
    """Filter search results by source (asr/subtitle) and language."""
    _create_sample_archive(tmp_root)

    # Source filter
    res_asr = search(tmp_root, SearchQuery(source="asr"))
    assert len(res_asr) == 2
    assert all(r["source"] == "asr" for r in res_asr)

    res_sub = search(tmp_root, SearchQuery(source="subtitle"))
    assert len(res_sub) == 1
    assert res_sub[0]["work_id"] == "BV1kant:p0"

    # Language filter
    res_lang = search(tmp_root, SearchQuery(language="ai-zh"))
    assert len(res_lang) == 1
    assert res_lang[0]["work_id"] == "BV1kant:p0"

    res_no_lang = search(tmp_root, SearchQuery(language="en-US"))
    assert res_no_lang == []


def test_search_query_work_id_and_bvid_filters(tmp_root):
    """Filter search results by explicit work_id or bvid."""
    _create_sample_archive(tmp_root)

    # Exact work_id
    res_work = search(tmp_root, SearchQuery(work_id="BV1hegel:p0"))
    assert len(res_work) == 1
    assert res_work[0]["work_id"] == "BV1hegel:p0"

    # Exact bvid matching multiple pages
    res_bvid = search(tmp_root, SearchQuery(work_id="BV1hegel"))
    assert len(res_bvid) == 2
    ids = {r["work_id"] for r in res_bvid}
    assert ids == {"BV1hegel:p0", "BV1hegel:p1"}

    # List of work_ids
    res_list = search(tmp_root, SearchQuery(work_id=["BV1kant:p0", "BV1hegel:p1"]))
    assert len(res_list) == 2


def test_search_query_scope_filter(tmp_root):
    """Filter search results using the standard scope taxonomy."""
    _create_sample_archive(tmp_root)

    # Scope with specific work_ids
    res_scoped = search(tmp_root, SearchQuery(scope="BV1kant:p0"))
    assert len(res_scoped) == 1
    assert res_scoped[0]["work_id"] == "BV1kant:p0"

    # Scope pending selects non-terminal rows (subtitle_done matches, archived excluded)
    res_pending = search(tmp_root, SearchQuery(scope="pending"))
    assert len(res_pending) == 1
    assert res_pending[0]["work_id"] == "BV1kant:p0"

    # Query matching archived row with scope pending returns empty
    res_pending_hegel = search(tmp_root, SearchQuery(query="Hegel", scope="pending"))
    assert res_pending_hegel == []

    # Scope failed without attempts ledger yields empty results
    res_failed_empty = search(tmp_root, SearchQuery(scope="failed"))
    assert res_failed_empty == []

    # Scope failed with recorded attempts ledger
    attempts_dir = os.path.join(tmp_root, "coordinator")
    os.makedirs(attempts_dir, exist_ok=True)
    with open(os.path.join(attempts_dir, "attempts.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"work_id": "BV1hegel:p0", "stage": "asr", "attempt": 1, "outcome": "failed"}) + "\n")

    res_failed = search(tmp_root, SearchQuery(scope="failed"))
    assert len(res_failed) == 1
    assert res_failed[0]["work_id"] == "BV1hegel:p0"


def test_search_query_title_and_duration_filters(tmp_root):
    """Filter search results by title substring and duration range."""
    _create_sample_archive(tmp_root)

    # Title filter
    res_title = search(tmp_root, SearchQuery(title="Pure Reason"))
    assert len(res_title) == 1
    assert res_title[0]["work_id"] == "BV1kant:p0"

    # Duration range filter
    res_duration = search(tmp_root, SearchQuery(min_duration_s=400, max_duration_s=500))
    assert len(res_duration) == 2  # BV1kant:p0 (420) and BV1hegel:p1 (480)
    work_ids = {r["work_id"] for r in res_duration}
    assert work_ids == {"BV1kant:p0", "BV1hegel:p1"}


def test_search_deterministic_tie_break_ordering(tmp_root):
    """When ranking scores tie, results must be deterministically ordered by (work_id, path)."""
    store = ManifestStore(root=tmp_root)
    txt_dir = os.path.join(tmp_root, "transcripts", "txt")
    os.makedirs(txt_dir, exist_ok=True)

    # Create 3 items with identical text and identical score
    for i in (3, 1, 2):
        work_id = f"BV1tie{i}:p0"
        rel_txt = f"transcripts/BV1tie{i}.p0/bundle.txt"
        os.makedirs(os.path.dirname(os.path.join(tmp_root, rel_txt)), exist_ok=True)
        with open(os.path.join(tmp_root, rel_txt), "w", encoding="utf-8") as fh:
            fh.write("Identical transcript text content for deterministic ordering verification.")
        store.upsert({
            "bvid": f"BV1tie{i}",
            "work_id": work_id,
            "page_index": 0,
            "title": f"Tie Video {i}",
            "status": "archived",
            "txt_path": rel_txt,
        })

    index = SearchIndex(root=tmp_root)
    index.build(store.load())

    results = search(tmp_root, SearchQuery(query="deterministic"))
    assert len(results) == 3
    # Verify deterministic work_id tie break order: BV1tie1:p0, BV1tie2:p0, BV1tie3:p0
    result_ids = [r["work_id"] for r in results]
    assert result_ids == ["BV1tie1:p0", "BV1tie2:p0", "BV1tie3:p0"]


def test_search_pagination_offset_and_limit(tmp_root):
    """Pagination via limit and offset provides stable sequential slices."""
    _create_sample_archive(tmp_root)

    # 3 total indexed items in sample archive: BV1hegel:p0, BV1hegel:p1, BV1kant:p0
    page1 = search(tmp_root, SearchQuery(status="archived,subtitle_done", limit=2, offset=0))
    assert len(page1) == 2

    page2 = search(tmp_root, SearchQuery(status="archived,subtitle_done", limit=2, offset=2))
    assert len(page2) == 1

    page3 = search(tmp_root, SearchQuery(status="archived,subtitle_done", limit=2, offset=10))
    assert page3 == []

    # Combined pages cover all 3 distinct items
    combined_ids = [r["work_id"] for r in page1] + [r["work_id"] for r in page2]
    assert len(set(combined_ids)) == 3


def test_search_bounded_invalid_limits(tmp_root):
    """Invalid or non-positive limits/offsets safely yield no results without error."""
    _create_sample_archive(tmp_root)

    assert search(tmp_root, SearchQuery(query="Hegel", limit=0)) == []
    assert search(tmp_root, SearchQuery(query="Hegel", limit=-5)) == []
    assert search(tmp_root, SearchQuery(query="Hegel", offset=-1)) == []


def test_search_manifest_immutability_with_search_query(tmp_root):
    """Search operations with SearchQuery must NEVER rewrite or modify the manifest JSONL."""
    store = _create_sample_archive(tmp_root)
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        original_manifest = fh.read()
    mtime_before = os.path.getmtime(manifest_path)

    search(tmp_root, SearchQuery(query="Hegel", status="archived"))
    search(tmp_root, SearchQuery(source="subtitle", language="ai-zh"))
    search(tmp_root, SearchQuery(rebuild=True))

    with open(manifest_path, "r", encoding="utf-8") as fh:
        after_manifest = fh.read()
    mtime_after = os.path.getmtime(manifest_path)

    assert original_manifest == after_manifest
    assert mtime_before == mtime_after


def test_search_sanitization_and_path_containment(tmp_root):
    """Search output must contain safe relative paths and redacted sensitive tokens."""
    store = ManifestStore(root=tmp_root)
    txt_dir = os.path.join(tmp_root, "transcripts", "txt")
    os.makedirs(txt_dir, exist_ok=True)

    rel_txt = "transcripts/BV1safe.p0/bundle.txt"
    os.makedirs(os.path.dirname(os.path.join(tmp_root, rel_txt)), exist_ok=True)
    with open(os.path.join(tmp_root, rel_txt), "w", encoding="utf-8") as fh:
        fh.write(
            "Discussion on ethics https://secret-stream.bilivideo.com/auth?token=leak_token_abc "
            "SESSDATA=secret_cookie_val and philosophy."
        )

    store.upsert({
        "bvid": "BV1safe",
        "work_id": "BV1safe:p0",
        "page_index": 0,
        "title": "Safe Redaction Video",
        "status": "archived",
        "txt_path": rel_txt,
    })

    results = search(tmp_root, SearchQuery(query="ethics"))
    assert len(results) == 1
    res = results[0]

    # Path must be relative
    assert not os.path.isabs(res["path"])
    assert ".." not in res["path"]

    # Snippet must be redacted
    snippet = res["transcript_snippet"]
    assert "secret-stream" not in snippet
    assert "leak_token_abc" not in snippet
    assert "secret_cookie_val" not in snippet
    assert "[redacted]" in snippet


def test_cli_search_with_status_source_language_filters(tmp_root, capsys):
    """bili-asr search CLI options --status, --source, --language, --work-id work properly."""
    _create_sample_archive(tmp_root)

    # 1. Filter by status
    code1 = main(["search", "Hegel", "--status", "archived", "--archive-root", tmp_root])
    assert code1 == 0
    out1 = capsys.readouterr().out
    assert "BV1hegel" in out1

    # 2. Filter by status mismatch: no hits is exit 0 (healthy class)
    code2 = main(["search", "Hegel", "--status", "subtitle_done", "--archive-root", tmp_root])
    assert code2 == 0
    out2 = capsys.readouterr().out
    assert "no hits" in out2

    # 3. Filter by source
    code3 = main(["search", "Kant", "--source", "subtitle", "--archive-root", tmp_root])
    assert code3 == 0
    out3 = capsys.readouterr().out
    assert "BV1kant" in out3

    # 4. Filter by language
    code4 = main(["search", "Kant", "--language", "ai-zh", "--archive-root", tmp_root])
    assert code4 == 0
    out4 = capsys.readouterr().out
    assert "BV1kant" in out4

    # 5. Filter by work-id
    code5 = main(["search", "Hegel", "--work-id", "BV1hegel", "--archive-root", tmp_root])
    assert code5 == 0
    out5 = capsys.readouterr().out
    assert "BV1hegel" in out5


def test_cli_search_json_format_output(tmp_root, capsys):
    """bili-asr search --format json outputs valid formatted JSON array."""
    _create_sample_archive(tmp_root)

    code = main(["search", "Kant", "--status", "subtitle_done", "--format", "json", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["bvid"] == "BV1kant"


def test_cli_search_invalid_limit_and_status_diagnostics(tmp_root, capsys):
    """Invalid --limit is a usage error (exit 2); unknown status filters match nothing."""
    _create_sample_archive(tmp_root)

    # Invalid non-positive limit
    with pytest.raises(SystemExit) as exc:
        main(["search", "Hegel", "--limit", "0", "--archive-root", tmp_root])
    assert exc.value.code == 2

    # Status filters name manifest rows; the store layer has no such vocabulary,
    # so an unknown value matches nothing rather than crashing.
    code_stat = main(["search", "Hegel", "--status", "invalid_status", "--archive-root", tmp_root])
    assert code_stat == 0


def test_the_index_reads_transcripts_from_the_artifact_root(tmp_path):
    """`search.db` stays at the archive root; every artifact probe walks the bases.

    The class holds both roots: the index file is state (D13) while the transcript
    documents it reads are products, so a single-root `SearchIndex` indexes an
    archive whose transcripts moved as if they were gone (contract §10, search row).
    """
    assert check_fts5_available(), "SQLite FTS5 must be available in the test environment"
    archive = tmp_path / "state"
    artifact = tmp_path / "artifacts"
    archive.mkdir(parents=True)
    (artifact / "transcripts" / "BV1hegel.p0").mkdir(parents=True)
    (artifact / "transcripts" / "BV1kant.p0").mkdir(parents=True)
    roots = ArtifactRoots.of(archive, artifact)
    store = ManifestStore(root=str(archive))

    # A recorded row: text is read through the recorded path at the configured root.
    recorded = {"work_id": "BV1hegel:p0", "bvid": "BV1hegel", "cid": 101, "page_index": 0,
                "title": "Hegel", "status": "archived", "duration_s": 10, "source": "asr",
                "srt_path": "transcripts/BV1hegel.p0/bundle.srt",
                "txt_path": "transcripts/BV1hegel.p0/bundle.txt"}
    store.upsert(recorded)
    (artifact / "transcripts" / "BV1hegel.p0" / "bundle.txt").write_text(
        "hegel dialectics and phenomenology\n", encoding="utf-8")
    (artifact / "transcripts" / "BV1hegel.p0" / "bundle.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhegel dialectics\n", encoding="utf-8")

    # A row with no path metadata at all: only the on-disk probe can index it.
    store.upsert({"work_id": "BV1kant:p0", "bvid": "BV1kant", "cid": 102, "page_index": 0,
                  "title": "Kant", "status": "archived", "duration_s": 10, "source": "asr"})
    (artifact / "transcripts" / "BV1kant.p0" / "bundle.txt").write_text(
        "kant synthetic a priori\n", encoding="utf-8")

    index = SearchIndex(str(archive), artifact_roots=roots)

    assert index.db_path == os.path.join(str(archive), "search.db")
    assert index.build() == 2
    assert (archive / "search.db").is_file()
    assert not (artifact / "search.db").exists()
    hits = index.search_query(SearchQuery(query="phenomenology"))
    assert [hit.work_id for hit in hits] == ["BV1hegel:p0"]
    assert [
        hit["work_id"]
        for hit in search(str(archive), "phenomenology", artifact_roots=roots)
    ] == ["BV1hegel:p0"]
    # The on-disk-only row is indexed too, and its text came from the configured root.
    assert [
        hit["work_id"]
        for hit in search(str(archive), "synthetic", artifact_roots=roots)
    ] == ["BV1kant:p0"]

    # Control: the same index without the context still lists the metadata row, but no
    # transcript text can be read and the on-disk-only row is invisible — today's
    # single-base behaviour, which is the regression this case pins.
    single = SearchIndex(str(archive))
    assert single.build() == 1
    assert search(str(archive), "phenomenology") == []
