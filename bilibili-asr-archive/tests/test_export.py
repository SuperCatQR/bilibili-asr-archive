"""Tests for manifest export command and formats (JSON/CSV)."""

from __future__ import annotations

import csv
import io
import json
import os
import pytest

from bili_asr.archive import write_archive
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.cli import main
from bili_asr.export import (
    COMPLETED_STATUSES,
    STANDARD_CSV_COLUMNS,
    export_coverage_summary,
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


#: Every standard column, written out rather than derived from
#: ``STANDARD_CSV_COLUMNS``: a pin that reads the constant it is checking cannot
#: fail when the constant changes — a reader who re-adds a key to the wrong place
#: still sees this list, and the literal is what makes that visible.
#: ``video_title`` sits at index 6, directly after ``title`` (index 5), so every
#: column that existed before keeps its relative order and the two titles read as
#: the pair compass **D5** says they are.
EXPECTED_CSV_HEADER = [
    "work_id", "bvid", "page_index", "cid", "page_label",
    "title", "video_title",
    "status", "duration_s", "pubdate", "source",
    "srt_path", "txt_path", "md_path", "raw_path", "audio_path",
]


def _export_row(bvid: str, *, video_title: str | None = None) -> dict:
    """One row carrying **every** standard column, so the header is the full set.

    ``format_csv_export`` writes a standard column only when some row's keys hold
    it (``fieldnames`` filters ``STANDARD_CSV_COLUMNS`` by ``seen_keys``), so a
    sparse fixture would pin a *sub*set and could not tell a standard column from
    a reordered one.  The path values need not exist on disk — the guard asks
    whether the value resolves under the base, not whether the file is there.
    """

    row = {
        "bvid": bvid, "work_id": f"{bvid}:p0", "page_index": 0, "cid": 7,
        "page_label": "P1", "title": "哲学课3", "status": "archived",
        "duration_s": 10, "pubdate": 1600000000, "source": "asr",
        "srt_path": f"transcripts/srt/{bvid}.p0.srt",
        "txt_path": f"transcripts/txt/{bvid}.p0.txt",
        "md_path": f"transcripts/md/{bvid}.p0.md",
        "raw_path": f"transcripts/raw/{bvid}.p0.json",
        "audio_path": f"audio/{bvid}.p0.m4a",
    }
    if video_title is not None:
        row["video_title"] = video_title
    return row


def test_export_csv_carries_the_video_title_beside_the_part_title(tmp_root):
    """The CSV surface carries ``video_title`` as a standard column beside ``title``.

    Compass **D5** makes ``title`` the part's own name and ``video_title`` the
    video's; the pair is the measured one, not a fabricated one — the live
    ``BV18XXcBnEz6`` part is ``哲学课3`` inside a video titled
    ``【哲学进阶】现代哲学 第二讲``, and 10 of the 63 stored parts diverge this
    way.  Both halves are asserted on the same row, because a writer that emitted
    the part title twice would satisfy either one alone.

    Expected: the header is exactly ``EXPECTED_CSV_HEADER`` — ``video_title`` at
    index 6, ``title`` at 5, everything else keeping its shipped order — and the
    row's ``title`` reads ``哲学课3`` while its ``video_title`` reads
    ``【哲学进阶】现代哲学 第二讲``.  Observed before the change: the key was
    absent from ``STANDARD_CSV_COLUMNS``, so the sanitizer passed it through as a
    *custom* key and the header carried it **last**, at index **15** after
    ``audio_path`` — away from the part title it belongs beside.  The equality
    below reports that as ``At index 6 diff: 'status' != 'video_title'``.
    """

    ManifestStore(root=tmp_root).upsert(
        _export_row("BV1vtitle", video_title="【哲学进阶】现代哲学 第二讲")
    )

    reader = csv.DictReader(io.StringIO(export_manifest(tmp_root, "csv")))
    assert reader.fieldnames == EXPECTED_CSV_HEADER
    # And the literal above is the constant's own order, so the pin cannot drift
    # away from what the module declares.
    assert EXPECTED_CSV_HEADER == list(STANDARD_CSV_COLUMNS)

    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["title"] == "哲学课3"                          # part title
    assert rows[0]["video_title"] == "【哲学进阶】现代哲学 第二讲"  # video title
    # Distinguishable, so a writer that echoed the part title into both fails.
    assert rows[0]["title"] != rows[0]["video_title"]


def test_export_csv_leaves_the_video_title_cell_empty_for_a_row_without_one(tmp_root):
    """A row with no ``video_title`` takes an empty cell, not a second header shape.

    The chain/ASR path's rows carry no ``video_title`` until the manifest half
    lands (``row_for_part``'s nine fields), so a mixed export must stay readable
    by a consumer that reads the header once: this is the CSV reading of the same
    statement the md side pins as a uniform key set
    (``test_write_archive_publishes_a_uniform_key_set_without_a_video_title``).

    Expected: with one enriched row present, the header is the full
    ``EXPECTED_CSV_HEADER`` — the same 16 columns as the case above — the
    enriched row carries its title and the other row's cell is ``""``.  Observed
    before the change: the equality failed at index 6 exactly as its sibling does,
    because the column arrived as a trailing custom key; the two rows share one
    header, so the missing value is the only difference this case can and does
    hold.
    """

    store = ManifestStore(root=tmp_root)
    store.upsert(_export_row("BV1vtitle", video_title="【哲学进阶】现代哲学 第二讲"))
    store.upsert(_export_row("BV1novtitle"))

    reader = csv.DictReader(io.StringIO(export_manifest(tmp_root, "csv")))
    assert reader.fieldnames == EXPECTED_CSV_HEADER

    by_id = {row["work_id"]: row for row in reader}
    assert by_id["BV1vtitle:p0"]["video_title"] == "【哲学进阶】现代哲学 第二讲"
    assert by_id["BV1novtitle:p0"]["video_title"] == ""
    # The part title is unaffected on the row that has no video title.
    assert by_id["BV1novtitle:p0"]["title"] == "哲学课3"


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


def test_export_repeated_json_csv_byte_stability(tmp_root):
    """Repeated export calls produce 100% byte-identical JSON and CSV output."""
    _create_sample_archive_for_export(tmp_root)

    # 1. JSON default
    json_runs = [export_manifest(tmp_root, "json") for _ in range(5)]
    assert all(r == json_runs[0] for r in json_runs)

    # 2. CSV default
    csv_runs = [export_manifest(tmp_root, "csv") for _ in range(5)]
    assert all(r == csv_runs[0] for r in csv_runs)

    # 3. JSON with text
    json_text_runs = [export_manifest(tmp_root, "json", with_text=True) for _ in range(5)]
    assert all(r == json_text_runs[0] for r in json_text_runs)

    # 4. CSV with text
    csv_text_runs = [export_manifest(tmp_root, "csv", with_text=True) for _ in range(5)]
    assert all(r == csv_text_runs[0] for r in csv_text_runs)


def test_export_bounded_limit_and_text_length(tmp_root):
    """export supports bounding total returned rows and transcript text length."""
    _create_sample_archive_for_export(tmp_root)

    # 1. Row limit
    rows_limit_2 = export_rows(ManifestStore(tmp_root), limit=2)
    assert len(rows_limit_2) == 2

    json_limit_1 = json.loads(export_manifest(tmp_root, "json", limit=1))
    assert len(json_limit_1) == 1

    # 2. Max text length
    json_text_bounded = json.loads(
        export_manifest(tmp_root, "json", with_text=True, max_text_length=10)
    )
    for row in json_text_bounded:
        if row.get("transcript_text"):
            assert len(row["transcript_text"]) <= 10


def test_export_path_safety_and_traversal_redaction(tmp_root):
    """Export neutralizes path traversal attempts and outside-root filepaths."""
    store = ManifestStore(root=tmp_root)
    dangerous_entry = {
        "bvid": "BV1traverse",
        "work_id": "BV1traverse:p0",
        "page_index": 0,
        "title": "Path Traversal Test",
        "status": "archived",
        "srt_path": "../../../../etc/passwd",
        "audio_path": "/etc/shadow",
        "txt_path": "transcripts/txt/../../secret.txt",
        "raw_path": "transcripts/raw/BV1traverse.p0.json",
    }
    store.upsert(dangerous_entry)

    rows = export_rows(store, archive_root=tmp_root)
    assert len(rows) == 1
    row = rows[0]

    # Escaping paths must be empty string
    assert row["srt_path"] == ""
    assert row["audio_path"] == ""
    assert row["txt_path"] == ""
    # Safe relative path is preserved
    assert row["raw_path"] == "transcripts/raw/BV1traverse.p0.json"
    assert "passwd" not in row["srt_path"]
    assert "shadow" not in row["audio_path"]


def test_export_nested_and_custom_url_redaction(tmp_root, capsys):
    """Export redacts nested URLs, custom _url keys, auth credentials, and stack traces."""
    store = ManifestStore(root=tmp_root)
    entry = {
        "bvid": "BV1nested",
        "work_id": "BV1nested:p0",
        "page_index": 0,
        "title": "Nested Redaction Test",
        "status": "archived",
        "cover_url": "https://i0.hdslb.com/bfs/archive/pic.jpg",
        "video_url": "https://api.bilibili.com/video/stream",
        "custom_url": "https://example.com/custom",
        "play_url": "https://play.bilibili.com",
        "access_token": "secret_oauth_token",
        "nested_meta": {
            "token": "tok_inner_123",
            "traceback": "Traceback (most recent call last): line 1",
            "safe_counter": 42,
            "api_url": "https://api.example.com",
        },
        "list_meta": [
            {"cookie": "raw_cookie_val", "name": "valid_name"},
            "https://signed.bilivideo.com/a?deadline=123&sign=xyz",
        ],
    }
    store.upsert(entry)

    code = main(["export", "--format", "json", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 1
    row = data[0]

    # Check top-level exclusion
    assert "cover_url" not in row
    assert "video_url" not in row
    assert "custom_url" not in row
    assert "play_url" not in row
    assert "access_token" not in row

    # Check nested dictionary
    assert "nested_meta" in row
    nested = row["nested_meta"]
    assert "token" not in nested
    assert "traceback" not in nested
    assert "api_url" not in nested
    assert nested.get("safe_counter") == 42

    # Check list sanitization
    assert "list_meta" in row
    list_items = row["list_meta"]
    assert "cookie" not in list_items[0]
    assert list_items[0].get("name") == "valid_name"
    assert list_items[1] == "[redacted]"

    # Ensure none of the sensitive values exist in raw output string
    assert "secret_oauth_token" not in out
    assert "tok_inner_123" not in out
    assert "raw_cookie_val" not in out
    assert "sign=xyz" not in out


def test_export_coverage_summary_explains_incomplete_and_excluded(tmp_root):
    """export_coverage_summary accurately categorizes completed vs incomplete/excluded rows."""
    store = ManifestStore(root=tmp_root)
    entries = [
        {"bvid": "BV1a", "work_id": "BV1a:p0", "status": "archived", "audio_path": "audio/BV1a.m4a"},
        {"bvid": "BV1b", "work_id": "BV1b:p0", "status": "subtitle_done"},
        {"bvid": "BV1c", "work_id": "BV1c:p0", "status": "meta_ok"},
        {"bvid": "BV1d", "work_id": "BV1d:p0", "status": "needs_audio"},
        {"bvid": "BV1e", "work_id": "BV1e:p0", "status": "gone"},
    ]
    for e in entries:
        store.upsert(e)

    # 1. Full summary without filter
    all_rows = export_rows(store, archive_root=tmp_root)
    summary_all = export_coverage_summary(all_rows, total_manifest_count=5)

    assert summary_all["total_rows"] == 5
    assert summary_all["completed_rows"] == 2
    assert summary_all["incomplete_rows"] == 3
    assert summary_all["excluded_count"] == 0
    assert summary_all["status_counts"] == {
        "archived": 1,
        "gone": 1,
        "meta_ok": 1,
        "needs_audio": 1,
        "subtitle_done": 1,
    }
    assert summary_all["reclaimed_audio_rows"] == 1

    # 2. Filtered summary (status=archived) explains excluded rows
    archived_rows = export_rows(store, status_filter=["archived"], archive_root=tmp_root)
    summary_filtered = export_coverage_summary(archived_rows, total_manifest_count=5)

    assert summary_filtered["total_rows"] == 1
    assert summary_filtered["completed_rows"] == 1
    assert summary_filtered["incomplete_rows"] == 0
    assert summary_filtered["excluded_count"] == 4
    assert summary_filtered["status_counts"] == {"archived": 1}


def test_export_independent_of_search_index(tmp_root, capsys):
    """Export is fully decoupled from search.db and does not require or mutate search index."""
    _create_sample_archive_for_export(tmp_root)
    search_db = os.path.join(tmp_root, "search.db")
    assert not os.path.exists(search_db)

    # Export runs cleanly without search.db existing
    code = main(["export", "--format", "json", "--archive-root", tmp_root])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 4

    # search.db is NOT created as a side-effect of export
    assert not os.path.exists(search_db)


def test_export_sidecars_and_manifest_remain_immutable(tmp_root):
    """Export operations never mutate manifest JSONL or existing sidecar files."""
    store = _create_sample_archive_for_export(tmp_root)
    cursor_file = os.path.join(tmp_root, "meta-cursor.json")
    ledger_file = os.path.join(tmp_root, "run-ledger.jsonl")

    with open(cursor_file, "w", encoding="utf-8") as fh:
        fh.write('{"state": "complete", "total": 4}\n')
    with open(ledger_file, "w", encoding="utf-8") as fh:
        fh.write('{"command": "fetch-meta", "exit_code": 0}\n')

    manifest_path = os.path.join(tmp_root, "manifest", "manifest.jsonl")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        orig_manifest = fh.read()
    with open(cursor_file, "r", encoding="utf-8") as fh:
        orig_cursor = fh.read()
    with open(ledger_file, "r", encoding="utf-8") as fh:
        orig_ledger = fh.read()

    # Perform multiple export commands
    export_manifest(tmp_root, "json", with_text=True)
    export_manifest(tmp_root, "csv", with_text=False)
    export_manifest(tmp_root, "json", status_filter=["archived"])
    main(["export", "--format", "csv", "--with-text", "--archive-root", tmp_root])

    with open(manifest_path, "r", encoding="utf-8") as fh:
        assert fh.read() == orig_manifest
    with open(cursor_file, "r", encoding="utf-8") as fh:
        assert fh.read() == orig_cursor
    with open(ledger_file, "r", encoding="utf-8") as fh:
        assert fh.read() == orig_ledger



def test_export_keeps_the_path_fields_of_a_configured_artifact_root(tmp_path):
    """Export resolves the artifact path fields against the bases they were written under.

    The five path fields are recorded by the artifact writers, so a containment
    check against the archive root alone is the export-side version of "a live
    archive reads as broken" (contract §10, export row).
    """
    archive = tmp_path / "state"
    artifact = tmp_path / "artifacts"
    archive.mkdir(parents=True)
    artifact.mkdir(parents=True)
    roots = ArtifactRoots.of(archive, artifact)
    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "pubdate_str": "20260828", "title": "Exported", "status": "archived"}
    row.update(write_archive(artifact, dict(row),
                             [{"start": 0, "end": 1, "text": "hegel dialectics"}], source="cc"))
    row["audio_path"] = "audio/BV1x.p0.m4a"
    ManifestStore(root=str(archive)).upsert(row)

    exported = json.loads(
        export_manifest(str(archive), "json", with_text=True, artifact_roots=roots)
    )

    path_keys = [key for key in STANDARD_CSV_COLUMNS if key.endswith("_path")]
    assert path_keys == ["srt_path", "txt_path", "md_path", "raw_path", "audio_path"]
    assert all(exported[0][key] for key in path_keys)
    assert exported[0]["srt_path"] == row["srt_path"]
    assert exported[0]["audio_path"] == "audio/BV1x.p0.m4a"
    # `--with-text` reads the transcript artifact, which lives at the configured root.
    assert "hegel dialectics" in exported[0]["transcript_text"]

    # Control: reading the same row without the context is what the field would show
    # today, and the transcript text is empty because the archive root holds no file.
    without_roots = json.loads(export_manifest(str(archive), "json", with_text=True))
    assert without_roots[0]["transcript_text"] == ""

    # The guard is re-based, not weakened: a value escaping every base is still
    # stripped from a standard path column (spec §6).
    assert sanitize_export_entry(
        {**row, "audio_path": "../escape.m4a"}, artifact_roots=roots
    )["audio_path"] == ""
