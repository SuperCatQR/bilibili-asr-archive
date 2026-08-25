"""Tests for manifest export command and formats (JSON/CSV)."""

from __future__ import annotations

import csv
import io
import json
import os
import pytest

from bili_asr.cli import main
from bili_asr.export import (
    STANDARD_CSV_COLUMNS,
    export_manifest,
    export_rows,
    format_csv_export,
    format_json_export,
    sanitize_export_entry,
)
from bili_asr.manifest import ManifestStore


def _create_sample_archive_for_export(tmp_root: str) -> ManifestStore:
    """Create sample archive with various statuses and transcript files."""
    store = ManifestStore(root=tmp_root)
    txt_dir = os.path.join(tmp_root, "transcripts", "txt")
    srt_dir = os.path.join(tmp_root, "transcripts", "srt")
    os.makedirs(txt_dir, exist_ok=True)
    os.makedirs(srt_dir, exist_ok=True)

    # 1. Archived entry with text
    e1 = {
        "bvid": "BV1hegel",
        "work_id": "BV1hegel:p0",
        "page_index": 0,
        "cid": 101,
        "page_label": "P1",
        "title": "Hegel Dialectics",
        "status": "archived",
        "duration_s": 360,
        "pubdate": 1600000000,
        "source": "asr",
        "txt_path": os.path.join("transcripts", "txt", "BV1hegel.p0.txt"),
        "srt_path": os.path.join("transcripts", "srt", "BV1hegel.p0.srt"),
    }
    with open(os.path.join(tmp_root, e1["txt_path"]), "w", encoding="utf-8") as fh:
        fh.write("Hegel dialectical idealism transcript content.")

    # 2. Subtitle_done entry
    e2 = {
        "bvid": "BV1kant",
        "work_id": "BV1kant:p0",
        "page_index": 0,
        "cid": 102,
        "page_label": "P1",
        "title": "Kant Pure Reason",
        "status": "subtitle_done",
        "duration_s": 420,
        "pubdate": 1600000100,
        "source": "subtitle",
        "srt_path": os.path.join("transcripts", "srt", "BV1kant.p0.srt"),
    }
    with open(os.path.join(tmp_root, e2["srt_path"]), "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,000 --> 00:00:05,000\nKant synthetic a priori proposition.\n")

    # 3. Meta_ok entry (no transcripts)
    e3 = {
        "bvid": "BV1meta",
        "work_id": "BV1meta:p0",
        "page_index": 0,
        "cid": 103,
        "page_label": "P1",
        "title": "Enumerated Video Only",
        "status": "meta_ok",
        "duration_s": 150,
        "pubdate": 1600000200,
    }

    # 4. Needs_audio entry
    e4 = {
        "bvid": "BV1need",
        "work_id": "BV1need:p0",
        "page_index": 0,
        "cid": 104,
        "page_label": "P1",
        "title": "Waiting For Audio Download",
        "status": "needs_audio",
        "duration_s": 200,
        "pubdate": 1600000300,
    }

    for entry in (e1, e2, e3, e4):
        store.upsert(entry)

    return store


def test_export_json_default_without_text(tmp_root, capsys):
    """bili-asr export --format json writes manifest metadata without transcript text by default."""
    _create_sample_archive_for_export(tmp_root)
    code = main(["export", "--format", "json", "--archive-root", tmp_root])
    assert code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 4

    work_ids = [row["work_id"] for row in data]
    assert "BV1hegel:p0" in work_ids
    assert "BV1kant:p0" in work_ids
    assert "BV1meta:p0" in work_ids
    assert "BV1need:p0" in work_ids

    # Verify column name is status, not state
    for row in data:
        assert "status" in row
        assert "state" not in row
        # By default without --with-text, transcript text is not included
        assert "transcript_text" not in row
        assert "text" not in row


def test_export_json_with_text(tmp_root, capsys):
    """bili-asr export --format json --with-text includes transcript text body."""
    _create_sample_archive_for_export(tmp_root)
    code = main(["export", "--format", "json", "--with-text", "--archive-root", tmp_root])
    assert code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 4

    by_id = {row["work_id"]: row for row in data}
    assert "transcript_text" in by_id["BV1hegel:p0"]
    assert "Hegel dialectical idealism" in by_id["BV1hegel:p0"]["transcript_text"]
    assert "Kant synthetic a priori" in by_id["BV1kant:p0"]["transcript_text"]
    assert by_id["BV1meta:p0"]["transcript_text"] == ""


def test_export_csv_default_without_text(tmp_root, capsys):
    """bili-asr export --format csv writes CSV rows without transcript_text header/body."""
    _create_sample_archive_for_export(tmp_root)
    code = main(["export", "--format", "csv", "--archive-root", tmp_root])
    assert code == 0

    out = capsys.readouterr().out
    reader = csv.DictReader(io.StringIO(out))
    rows = list(reader)
    assert len(rows) == 4

    assert reader.fieldnames is not None
    assert "status" in reader.fieldnames
    assert "state" not in reader.fieldnames
    assert "transcript_text" not in reader.fieldnames

    work_ids = [r["work_id"] for r in rows]
    assert "BV1hegel:p0" in work_ids
    assert "BV1kant:p0" in work_ids


def test_export_csv_with_text(tmp_root, capsys):
    """bili-asr export --format csv --with-text includes transcript_text column and values."""
    _create_sample_archive_for_export(tmp_root)
    code = main(["export", "--format", "csv", "--with-text", "--archive-root", tmp_root])
    assert code == 0

    out = capsys.readouterr().out
    reader = csv.DictReader(io.StringIO(out))
    rows = list(reader)
    assert len(rows) == 4

    assert reader.fieldnames is not None
    assert "transcript_text" in reader.fieldnames

    by_id = {r["work_id"]: r for r in rows}
    assert "Hegel dialectical idealism" in by_id["BV1hegel:p0"]["transcript_text"]
    assert "Kant synthetic a priori" in by_id["BV1kant:p0"]["transcript_text"]
    assert by_id["BV1meta:p0"]["transcript_text"] == ""


def test_export_out_file(tmp_root):
    """bili-asr export --format json|csv --out <path> writes to output file."""
    _create_sample_archive_for_export(tmp_root)
    json_out = os.path.join(tmp_root, "exports", "manifest.json")
    csv_out = os.path.join(tmp_root, "exports", "manifest.csv")

    code_json = main(["export", "--format", "json", "--out", json_out, "--archive-root", tmp_root])
    assert code_json == 0
    assert os.path.isfile(json_out)
    with open(json_out, "r", encoding="utf-8") as fh:
        json_data = json.load(fh)
    assert len(json_data) == 4

    code_csv = main(["export", "--format", "csv", "--out", csv_out, "--archive-root", tmp_root])
    assert code_csv == 0
    assert os.path.isfile(csv_out)
    with open(csv_out, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        csv_rows = list(reader)
    assert len(csv_rows) == 4


def test_export_status_filter_single_and_multi(tmp_root, capsys):
    """bili-asr export --status filters rows to matching statuses."""
    _create_sample_archive_for_export(tmp_root)

    # 1. Single status filter
    code1 = main(["export", "--format", "json", "--status", "archived", "--archive-root", tmp_root])
    assert code1 == 0
    data1 = json.loads(capsys.readouterr().out)
    assert len(data1) == 1
    assert data1[0]["work_id"] == "BV1hegel:p0"
    assert data1[0]["status"] == "archived"

    # 2. Multi-flag status filter
    code2 = main([
        "export", "--format", "json",
        "--status", "archived",
        "--status", "subtitle_done",
        "--archive-root", tmp_root,
    ])
    assert code2 == 0
    data2 = json.loads(capsys.readouterr().out)
    assert len(data2) == 2
    statuses2 = {r["status"] for r in data2}
    assert statuses2 == {"archived", "subtitle_done"}

    # 3. Comma-separated status filter
    code3 = main([
        "export", "--format", "json",
        "--status", "meta_ok,needs_audio",
        "--archive-root", tmp_root,
    ])
    assert code3 == 0
    data3 = json.loads(capsys.readouterr().out)
    assert len(data3) == 2
    statuses3 = {r["status"] for r in data3}
    assert statuses3 == {"meta_ok", "needs_audio"}


def test_export_invalid_status_filter_exits_one(tmp_root, capsys):
    """bili-asr export --status with invalid status reports error and exits 1."""
    _create_sample_archive_for_export(tmp_root)
    code = main(["export", "--format", "json", "--status", "invalid_status", "--archive-root", tmp_root])
    assert code == 1
    err = capsys.readouterr().err
    assert "invalid status filter" in err
    assert "invalid_status" in err


def test_export_manifest_immutability(tmp_root):
    """Export operations must NEVER rewrite or modify the manifest JSONL file."""
    store = _create_sample_archive_for_export(tmp_root)
    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        original_content = fh.read()

    # Perform various export commands
    main(["export", "--format", "json", "--archive-root", tmp_root])
    main(["export", "--format", "csv", "--with-text", "--archive-root", tmp_root])
    main(["export", "--format", "json", "--status", "archived", "--archive-root", tmp_root])

    with open(manifest_path, "r", encoding="utf-8") as fh:
        after_content = fh.read()

    assert original_content == after_content


def test_export_empty_manifest(tmp_root, capsys):
    """Exporting an empty manifest produces valid empty JSON array or CSV header."""
    ManifestStore(root=tmp_root)  # creates empty store

    # JSON export of empty manifest
    code_json = main(["export", "--format", "json", "--archive-root", tmp_root])
    assert code_json == 0
    data = json.loads(capsys.readouterr().out)
    assert data == []

    # CSV export of empty manifest
    code_csv = main(["export", "--format", "csv", "--archive-root", tmp_root])
    assert code_csv == 0
    out_csv = capsys.readouterr().out
    reader = csv.DictReader(io.StringIO(out_csv))
    assert reader.fieldnames == list(STANDARD_CSV_COLUMNS)
    assert list(reader) == []


def test_export_sanitizes_credentials_and_signed_urls(tmp_root, capsys):
    """Export strictly omits credentials, cookies, and signed URLs."""
    store = ManifestStore(root=tmp_root)
    entry = {
        "bvid": "BV1secret",
        "work_id": "BV1secret:p0",
        "page_index": 0,
        "cid": 999,
        "title": "Secret Test",
        "status": "archived",
        "duration_s": 100,
        "sessdata": "secret_cookie_token_123",
        "cookie": "buvid3=xyz",
        "stream_url": "https://upos-sz-mirror08c.bilivideo.com/test.m4a?deadline=1700000000&sign=abcd",
        "signed_url": "https://signed.bilivideo.com/audio",
        "traceback": "Traceback (most recent call last): ...",
    }
    store.upsert(entry)

    code = main(["export", "--format", "json", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 1
    row = data[0]

    assert "sessdata" not in row
    assert "cookie" not in row
    assert "stream_url" not in row
    assert "signed_url" not in row
    assert "traceback" not in row
    assert "secret_cookie_token_123" not in out
    assert "sign=abcd" not in out


def test_export_legacy_and_unresolved_rows(tmp_root, capsys):
    """Legacy bare-bvid and unresolved rows are safely exported with metadata."""
    store = ManifestStore(root=tmp_root)
    entry = {
        "bvid": "BV1legacybare",
        "title": "Legacy Bare Bvid",
        "status": "meta_ok",
        "unresolved": True,
        "unresolved_reason": "ambiguous_bare_bvid",
        "excluded_from_page_processing": True,
    }
    store.upsert(entry)

    code = main(["export", "--format", "json", "--archive-root", tmp_root])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["bvid"] == "BV1legacybare"
    assert data[0]["unresolved"] is True
    assert data[0]["unresolved_reason"] == "ambiguous_bare_bvid"


def test_export_missing_or_invalid_format_exits_one(tmp_root):
    """Missing or invalid --format argument produces usage error (exit 1)."""
    with pytest.raises(SystemExit) as exc1:
        main(["export", "--archive-root", tmp_root])
    assert exc1.value.code == 1

    with pytest.raises(SystemExit) as exc2:
        main(["export", "--format", "xml", "--archive-root", tmp_root])
    assert exc2.value.code == 1


def test_export_atomic_out_write_and_cleanup_on_failure(tmp_root, monkeypatch):
    """export_manifest writes atomically and cleans up .tmp file if an error occurs."""
    _create_sample_archive_for_export(tmp_root)
    out_file = os.path.join(tmp_root, "exports", "failed.json")
    tmp_file = out_file + ".tmp"

    def fail_replace(src, dst):
        raise OSError("Simulated disk error during replace")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="Simulated disk error"):
        export_manifest(
            archive_root=tmp_root,
            fmt="json",
            out_path=out_file,
        )

    assert not os.path.exists(out_file)
    assert not os.path.exists(tmp_file)

