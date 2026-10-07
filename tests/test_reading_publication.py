from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from bili_asr.reading_publication import export_reading_site, store_reading_edition, update_reading_status
from bili_asr.cli.parser import build_parser
from bili_asr.cli.reading import _readonly_connection
from bili_asr.cli.registry import COMMANDS
from bili_asr.storage.database import open_database


def database_with_revision(tmp_path: Path) -> tuple[sqlite3.Connection, Path, str, str]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE videos (bvid TEXT PRIMARY KEY, title TEXT NOT NULL);
        CREATE TABLE video_parts (video_part_id INTEGER PRIMARY KEY, bvid TEXT NOT NULL, page_index INTEGER NOT NULL);
        CREATE TABLE editorial_inputs (input_id TEXT PRIMARY KEY, video_part_id INTEGER NOT NULL);
        CREATE TABLE editorial_revisions (
            revision_id TEXT PRIMARY KEY, input_id TEXT NOT NULL,
            quality_status TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE document_artifacts (
            revision_id TEXT NOT NULL, template_version TEXT NOT NULL,
            artifact_name TEXT NOT NULL, relative_path TEXT NOT NULL,
            content_sha256 TEXT NOT NULL
        );
        CREATE TABLE reading_publications (
            revision_id TEXT PRIMARY KEY, current_edition_id TEXT, status TEXT NOT NULL, issue_url TEXT,
            updated_at INTEGER NOT NULL, published_at INTEGER
        );
        CREATE TABLE reading_document_editions (
            edition_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL,
            parent_edition_id TEXT, markdown_text TEXT NOT NULL,
            content_sha256 TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE reading_publication_events (
            event_id INTEGER PRIMARY KEY, revision_id TEXT NOT NULL,
            edition_id TEXT, from_status TEXT, to_status TEXT NOT NULL, issue_url TEXT,
            note TEXT NOT NULL, changed_at INTEGER NOT NULL
        );
        """
    )
    revision_id = "a" * 64
    content = "# This heading is not part of reading.md\n\n这是正文。\n"
    review_content = "# 审核稿\n\n请核对这段内容。\n"
    relative_path = Path("documents") / "part-7" / revision_id / "reading-v2" / "reading.md"
    document = tmp_path / relative_path
    document.parent.mkdir(parents=True)
    document.write_bytes(content.encode("utf-8"))
    review_relative_path = Path("documents") / "part-7" / revision_id / "review-v2" / "review.md"
    review_document = tmp_path / review_relative_path
    review_document.parent.mkdir(parents=True)
    review_document.write_bytes(review_content.encode("utf-8"))
    connection.execute("INSERT INTO videos VALUES (?, ?)", ("BV1test00001", "示例视频"))
    connection.execute("INSERT INTO video_parts VALUES (?, ?, ?)", (7, "BV1test00001", 1))
    connection.execute("INSERT INTO editorial_inputs VALUES (?, ?)", ("input-1", 7))
    connection.execute(
        "INSERT INTO editorial_revisions VALUES (?, ?, ?, ?)",
        (revision_id, "input-1", "needs-review", 1_791_360_000),
    )
    connection.execute(
        "INSERT INTO document_artifacts VALUES (?, ?, ?, ?, ?)",
        (revision_id, "reading-v2", "reading.md", relative_path.as_posix(), hashlib.sha256(content.encode()).hexdigest()),
    )
    connection.execute(
        "INSERT INTO document_artifacts VALUES (?, ?, ?, ?, ?)",
        (revision_id, "review-v2", "review.md", review_relative_path.as_posix(), hashlib.sha256(review_content.encode()).hexdigest()),
    )
    return connection, tmp_path, revision_id, content


def test_export_uses_reading_artifact_and_marks_revision_pending(tmp_path: Path) -> None:
    connection, root, revision_id, content = database_with_revision(tmp_path)
    output = tmp_path / "reading-site" / "content"

    count = export_reading_site(connection, artifact_roots=(root,), output=output)

    assert count == 1
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    entry = catalog[0]
    assert entry["reviewStatus"] == "pending-review"
    assert entry["qualityStatus"] == "needs-review"
    assert entry["revisionId"] == revision_id
    assert entry["sourceUrl"] == "https://www.bilibili.com/video/BV1test00001?p=2"
    assert "issues/new?" in entry["issueUrl"]
    assert (output / "articles" / entry["file"]).read_text(encoding="utf-8") == content
    assert entry["reviewFile"] == entry["file"]
    assert (output / "reviews" / entry["reviewFile"]).read_text(encoding="utf-8") == "# 审核稿\n\n请核对这段内容。\n"


def test_export_hides_rejected_revisions_and_removes_only_managed_stale_files(tmp_path: Path) -> None:
    connection, root, revision_id, _ = database_with_revision(tmp_path)
    output = tmp_path / "reading-site" / "content"
    export_reading_site(connection, artifact_roots=(root,), output=output)
    entry = json.loads((output / "catalog.json").read_text(encoding="utf-8"))[0]
    update_reading_status(connection, revision_id=revision_id, status="rejected", note="not ready")

    assert export_reading_site(connection, artifact_roots=(root,), output=output) == 0
    assert json.loads((output / "catalog.json").read_text(encoding="utf-8")) == []
    assert not (output / "articles" / entry["file"]).exists()
    assert not (output / "reviews" / entry["reviewFile"]).exists()
    event = connection.execute(
        "SELECT from_status, to_status, note FROM reading_publication_events ORDER BY event_id"
    ).fetchone()
    assert tuple(event) == (None, "rejected", "not ready")


def test_update_review_status_keeps_quality_revision_immutable(tmp_path: Path) -> None:
    connection, _, revision_id, _ = database_with_revision(tmp_path)
    issue_url = "https://github.com/SuperCatQR/bilibili-asr-archive/issues/123"

    update_reading_status(
        connection,
        revision_id=revision_id,
        status="in-review",
        issue_url=issue_url,
        note="review requested",
    )

    assert connection.execute("SELECT quality_status FROM editorial_revisions WHERE revision_id = ?", (revision_id,)).fetchone()[0] == "needs-review"
    publication = connection.execute("SELECT status, issue_url FROM reading_publications WHERE revision_id = ?", (revision_id,)).fetchone()
    assert tuple(publication) == ("in-review", issue_url)


def test_issue_edits_become_a_new_immutable_edition(tmp_path: Path) -> None:
    connection, root, revision_id, _ = database_with_revision(tmp_path)
    edition_text = "人工修订后的正文。\n"
    edition_id = store_reading_edition(
        connection,
        revision_id=revision_id,
        markdown_text=edition_text,
        note="accepted issue suggestion",
    )

    assert connection.execute("SELECT quality_status FROM editorial_revisions WHERE revision_id = ?", (revision_id,)).fetchone()[0] == "needs-review"
    publication = connection.execute("SELECT current_edition_id, status FROM reading_publications WHERE revision_id = ?", (revision_id,)).fetchone()
    assert tuple(publication) == (edition_id, "pending-review")
    output = tmp_path / "reading-site" / "content"
    export_reading_site(connection, artifact_roots=(root,), output=output)
    entry = json.loads((output / "catalog.json").read_text(encoding="utf-8"))[0]
    assert entry["editionId"] == edition_id
    assert (output / "articles" / entry["file"]).read_text(encoding="utf-8") == edition_text
    assert (output / "reviews" / entry["reviewFile"]).exists()


def test_new_human_edition_returns_a_published_document_to_review(tmp_path: Path) -> None:
    connection, _, revision_id, _ = database_with_revision(tmp_path)
    update_reading_status(connection, revision_id=revision_id, status="in-review")
    update_reading_status(connection, revision_id=revision_id, status="approved")
    update_reading_status(connection, revision_id=revision_id, status="published")
    store_reading_edition(connection, revision_id=revision_id, markdown_text="updated text")

    publication = connection.execute(
        "SELECT status, published_at FROM reading_publications WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()
    assert tuple(publication) == ("pending-review", None)


def test_review_state_cannot_skip_approval_before_publication(tmp_path: Path) -> None:
    connection, _, revision_id, _ = database_with_revision(tmp_path)
    with pytest.raises(ValueError, match="pending-review -> published"):
        update_reading_status(connection, revision_id=revision_id, status="published")


def test_export_refuses_modified_artifact_hash_and_unmanaged_markdown(tmp_path: Path) -> None:
    connection, root, _, _ = database_with_revision(tmp_path)
    output = tmp_path / "reading-site" / "content"
    row = connection.execute("SELECT relative_path FROM document_artifacts").fetchone()
    (root / row[0]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="哈希与数据库不一致"):
        export_reading_site(connection, artifact_roots=(root,), output=output)

    (root / row[0]).write_text("restored", encoding="utf-8")
    articles = output / "articles"
    articles.mkdir(parents=True)
    (articles / "manual.md").write_text("manual", encoding="utf-8")
    with pytest.raises(ValueError, match="非数据库导入稿件"):
        export_reading_site(connection, artifact_roots=(root,), output=output)


def test_reading_cli_commands_and_database_schema_are_registered() -> None:
    parser = build_parser()
    command_parsers = parser._subparsers._group_actions[0].choices
    assert {"reading-export", "reading-review", "reading-edit"} <= set(command_parsers)
    assert {"reading-export", "reading-review", "reading-edit"} <= set(COMMANDS)

    connection = open_database(":memory:")
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"reading_publications", "reading_publication_events", "reading_document_editions"} <= tables
    finally:
        connection.close()


def test_export_connection_is_sqlite_read_only(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    db_path = archive / "archive.db"
    writable = sqlite3.connect(db_path)
    writable.execute("CREATE TABLE sample (value TEXT)")
    writable.execute("INSERT INTO sample VALUES ('kept')")
    writable.commit()
    writable.close()

    connection = _readonly_connection(str(archive))
    try:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "kept"
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO sample VALUES ('blocked')")
    finally:
        connection.close()
