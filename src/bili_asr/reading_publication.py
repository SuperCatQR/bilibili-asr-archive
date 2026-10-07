"""Read-only export of editorial revisions and audited review status updates."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from urllib.parse import urlencode, urlsplit


REVIEW_STATUSES = (
    "pending-review",
    "in-review",
    "changes-requested",
    "approved",
    "published",
    "rejected",
    "withdrawn",
)
HIDDEN_STATUSES = frozenset({"rejected", "withdrawn"})
STATUS_TRANSITIONS = {
    "pending-review": frozenset({"pending-review", "in-review", "rejected", "withdrawn"}),
    "in-review": frozenset({"in-review", "changes-requested", "approved", "rejected", "withdrawn"}),
    "changes-requested": frozenset({"in-review", "rejected", "withdrawn"}),
    "approved": frozenset({"approved", "published", "changes-requested", "withdrawn"}),
    "published": frozenset({"published", "withdrawn"}),
    "rejected": frozenset({"rejected", "pending-review", "withdrawn"}),
    "withdrawn": frozenset({"withdrawn", "pending-review"}),
}
DEFAULT_ISSUES_URL = "https://github.com/SuperCatQR/markdown-reading-site/issues/new"
_MANAGED_FILE_RE = re.compile(r"^part-[0-9]+-[0-9a-f]{64}\.md$")


def _validate_issue_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        raise ValueError("Issue 地址必须是有效的 HTTPS URL")
    return value


def _issue_link(base_url: str, entry: dict[str, object]) -> str:
    title = str(entry["title"])
    source_url = str(entry["sourceUrl"])
    body = (
        "## 阅读稿\n\n"
        f"- 修订 ID: `{entry['revisionId']}`\n"
        f"- 人工修订 ID: `{entry.get('editionId') or '无'}`\n"
        f"- 视频分段: `{entry['videoPartId']}`\n"
        f"- 当前质量状态: `{entry['qualityStatus']}`\n"
        f"- 原视频: {source_url}\n\n"
        "## 建议修改\n\n"
        "请指出段落或原句，写明建议内容与理由。接受修改后会生成新的修订记录。\n"
    )
    return f"{base_url}?{urlencode({'template': 'review.md', 'title': f'[阅读稿审核] {title}', 'body': body})}"


def _reading_document(relative_path: str, digest: str, roots: tuple[Path, ...]) -> str:
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("reading.md 路径越界")
    for root in roots:
        base = root.resolve()
        candidate = root / relative
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(base)
        except (OSError, ValueError):
            continue
        if not resolved.is_file():
            continue
        content = resolved.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"reading.md 哈希与数据库不一致: {relative_path}")
        return content.decode("utf-8")
    raise FileNotFoundError(f"找不到归档文档: {relative_path}")


def _verify_markdown(markdown_text: str, digest: str) -> str:
    if hashlib.sha256(markdown_text.encode("utf-8")).hexdigest() != digest:
        raise ValueError("reading document edition hash mismatch")
    return markdown_text


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".import-", delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _previous_managed_files(output: Path, articles: Path, reviews: Path) -> tuple[set[str], set[str]]:
    manifest_path = output / "db-import-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("数据库导入清单无效，拒绝覆盖阅读稿")
        articles_list = manifest.get("articles", manifest.get("files"))
        reviews_list = manifest.get("reviews", [])
        if (
            not isinstance(articles_list, list)
            or not isinstance(reviews_list, list)
            or any(not isinstance(name, str) or not _MANAGED_FILE_RE.fullmatch(name) for name in (*articles_list, *reviews_list))
        ):
            raise ValueError("数据库导入清单无效，拒绝覆盖阅读稿")
        managed_articles = set(articles_list)
        managed_reviews = set(reviews_list)
    else:
        catalog_path = output / "catalog.json"
        if catalog_path.exists() and json.loads(catalog_path.read_text(encoding="utf-8")) != []:
            raise ValueError("catalog.json 中已有手工稿件；请先迁移到数据库导入流程")
        managed_articles = set()
        managed_reviews = set()

    foreign_files = {
        path.name for path in articles.glob("*.md")
        if path.name not in managed_articles
    }
    if foreign_files:
        raise ValueError(f"articles 目录含非数据库导入稿件: {sorted(foreign_files)}")
    foreign_reviews = {
        path.name for path in reviews.glob("*.md")
        if path.name not in managed_reviews
    }
    if foreign_reviews:
        raise ValueError(f"reviews 目录含非数据库导入稿件: {sorted(foreign_reviews)}")
    return managed_articles, managed_reviews


def export_reading_site(
    connection: sqlite3.Connection,
    *,
    artifact_roots: tuple[Path, ...],
    output: Path,
    issues_url: str = DEFAULT_ISSUES_URL,
) -> int:
    """Export all rendered revisions except rejected/withdrawn ones.

    The caller owns a SQLite connection opened in read-only mode. Output files are
    a generated site snapshot; the database remains the source of truth.
    """
    issues_url = _validate_issue_url(issues_url)
    output = output.resolve()
    articles = output / "articles"
    reviews = output / "reviews"
    managed_articles, managed_reviews = _previous_managed_files(output, articles, reviews)
    objects = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    has_status = "reading_publications" in objects
    status_join = (
        "LEFT JOIN reading_publications pub ON pub.revision_id = r.revision_id"
        if has_status else ""
    )
    status_select = (
        "COALESCE(pub.status, 'pending-review') AS review_status, pub.issue_url, "
        "pub.current_edition_id, ed.markdown_text, ed.content_sha256 AS edition_sha256"
        if has_status else
        "'pending-review' AS review_status, NULL AS issue_url, NULL AS current_edition_id, "
        "NULL AS markdown_text, NULL AS edition_sha256"
    )
    edition_join = (
        "LEFT JOIN reading_document_editions ed ON ed.edition_id = pub.current_edition_id"
        if has_status else ""
    )
    rows = connection.execute(
        f"SELECT r.revision_id, r.quality_status, r.created_at, i.video_part_id, "
        f"p.bvid, p.page_index, v.title, {status_select}, "
        "da.relative_path, da.content_sha256, ra.relative_path AS review_relative_path, "
        "ra.content_sha256 AS review_content_sha256 "
        "FROM editorial_revisions r "
        "JOIN editorial_inputs i ON i.input_id = r.input_id "
        "JOIN video_parts p ON p.video_part_id = i.video_part_id "
        "JOIN videos v ON v.bvid = p.bvid "
        "JOIN document_artifacts da ON da.revision_id = r.revision_id "
        "AND da.artifact_name = 'reading.md' AND da.template_version = ("
        "SELECT MAX(da2.template_version) FROM document_artifacts da2 "
        "WHERE da2.revision_id = r.revision_id AND da2.artifact_name = 'reading.md') "
        "LEFT JOIN document_artifacts ra ON ra.revision_id = r.revision_id "
        "AND ra.artifact_name = 'review.md' AND ra.template_version = ("
        "SELECT MAX(ra2.template_version) FROM document_artifacts ra2 "
        "WHERE ra2.revision_id = r.revision_id AND ra2.artifact_name = 'review.md') "
        f"{status_join} {edition_join} ORDER BY r.created_at, r.revision_id"
    ).fetchall()

    catalog: list[dict[str, object]] = []
    new_article_files: set[str] = set()
    new_review_files: set[str] = set()
    for row in rows:
        review_status = str(row["review_status"])
        if review_status in HIDDEN_STATUSES:
            continue
        revision_id = str(row["revision_id"])
        if not re.fullmatch(r"[0-9a-f]{64}", revision_id):
            raise ValueError(f"invalid editorial revision ID: {revision_id}")
        part_id = int(row["video_part_id"])
        page_index = int(row["page_index"])
        source_url = f"https://www.bilibili.com/video/{row['bvid']}?p={page_index + 1}"
        title = f"{row['title']} · P{page_index + 1}"
        quality_status = str(row["quality_status"])
        slug = f"part-{part_id}-{revision_id}"
        filename = f"{slug}.md"
        if not _MANAGED_FILE_RE.fullmatch(filename):
            raise ValueError(f"无法生成安全的稿件文件名: {filename}")
        if row["markdown_text"] is not None:
            body = _verify_markdown(str(row["markdown_text"]), str(row["edition_sha256"]))
            edition_id = str(row["current_edition_id"])
        else:
            body = _reading_document(str(row["relative_path"]), str(row["content_sha256"]), artifact_roots)
            edition_id = ""
        if row["review_relative_path"] is None or row["review_content_sha256"] is None:
            raise FileNotFoundError(f"找不到归档文档: review.md ({revision_id})")
        review_body = _reading_document(
            str(row["review_relative_path"]), str(row["review_content_sha256"]), artifact_roots
        )
        entry: dict[str, object] = {
            "slug": slug,
            "title": title,
            "date": time.strftime("%Y-%m-%d", time.gmtime(int(row["created_at"]))),
            "summary": f"{row['bvid']} · 第 {page_index + 1}P · {'有待核对' if quality_status == 'needs-review' else 'AI 整理稿'}",
            "tags": ["有待核对" if quality_status == "needs-review" else "AI 整理稿"],
            "file": filename,
            "reviewFile": filename,
            "revisionId": revision_id,
            "editionId": edition_id,
            "videoPartId": part_id,
            "qualityStatus": quality_status,
            "reviewStatus": review_status,
            "sourceUrl": source_url,
            "issueUrl": str(row["issue_url"]) if row["issue_url"] else "",
        }
        if not entry["issueUrl"]:
            entry["issueUrl"] = _issue_link(issues_url, entry)
        _atomic_write(articles / filename, body.encode("utf-8"))
        _atomic_write(reviews / filename, review_body.encode("utf-8"))
        new_article_files.add(filename)
        new_review_files.add(filename)
        catalog.append(entry)

    for stale in managed_articles - new_article_files:
        stale_path = articles / stale
        if stale_path.is_symlink():
            raise ValueError(f"拒绝删除符号链接: {stale_path}")
        if stale_path.exists():
            stale_path.unlink()
    for stale in managed_reviews - new_review_files:
        stale_path = reviews / stale
        if stale_path.is_symlink():
            raise ValueError(f"拒绝删除符号链接: {stale_path}")
        if stale_path.exists():
            stale_path.unlink()

    catalog.sort(key=lambda item: (str(item["date"]), str(item["title"])), reverse=True)
    _atomic_write(output / "catalog.json", (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    manifest = {
        "version": 2,
        "source": "bili-asr editorial_revisions",
        "articles": sorted(new_article_files),
        "reviews": sorted(new_review_files),
    }
    _atomic_write(output / "db-import-manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return len(catalog)


def update_reading_status(
    connection: sqlite3.Connection,
    *,
    revision_id: str,
    status: str,
    issue_url: str | None = None,
    note: str = "",
) -> None:
    if status not in REVIEW_STATUSES:
        raise ValueError(f"invalid reading status: {status}")
    if issue_url is not None:
        issue_url = _validate_issue_url(issue_url)
    if connection.execute("SELECT 1 FROM editorial_revisions WHERE revision_id = ?", (revision_id,)).fetchone() is None:
        raise ValueError(f"unknown editorial revision: {revision_id}")

    now = int(time.time())
    current = connection.execute(
        "SELECT status, issue_url, published_at, current_edition_id FROM reading_publications WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()
    previous_status = str(current["status"]) if current else None
    effective_previous = previous_status or "pending-review"
    if status not in STATUS_TRANSITIONS[effective_previous]:
        raise ValueError(f"invalid reading status transition: {effective_previous} -> {status}")
    resolved_issue_url = issue_url if issue_url is not None else (current["issue_url"] if current else None)
    published_at = current["published_at"] if current else None
    current_edition_id = current["current_edition_id"] if current else None
    if status == "published" and published_at is None:
        published_at = now

    with connection:
        connection.execute(
            "INSERT INTO reading_publications(revision_id, current_edition_id, status, issue_url, updated_at, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(revision_id) DO UPDATE SET "
            "status=excluded.status, issue_url=excluded.issue_url, updated_at=excluded.updated_at, "
            "published_at=excluded.published_at",
            (revision_id, current_edition_id, status, resolved_issue_url, now, published_at),
        )
        if previous_status != status or issue_url is not None or note:
            connection.execute(
                "INSERT INTO reading_publication_events "
                "(revision_id, edition_id, from_status, to_status, issue_url, note, changed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (revision_id, current_edition_id, previous_status, status, resolved_issue_url, note, now),
            )


def store_reading_edition(
    connection: sqlite3.Connection,
    *,
    revision_id: str,
    markdown_text: str,
    note: str = "",
) -> str:
    if not markdown_text.strip():
        raise ValueError("reading document cannot be empty")
    if connection.execute("SELECT 1 FROM editorial_revisions WHERE revision_id = ?", (revision_id,)).fetchone() is None:
        raise ValueError(f"unknown editorial revision: {revision_id}")

    current = connection.execute(
        "SELECT status, issue_url, current_edition_id, published_at "
        "FROM reading_publications WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()
    parent_id = str(current["current_edition_id"]) if current and current["current_edition_id"] else None
    content_sha256 = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()
    edition_id = hashlib.sha256(
        f"{revision_id}\n{parent_id or ''}\n{content_sha256}".encode("utf-8")
    ).hexdigest()
    now = int(time.time())
    previous_status = str(current["status"]) if current else None
    issue_url = current["issue_url"] if current else None
    published_at = current["published_at"] if current else None

    with connection:
        connection.execute(
            "INSERT OR IGNORE INTO reading_document_editions "
            "(edition_id, revision_id, parent_edition_id, markdown_text, content_sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (edition_id, revision_id, parent_id, markdown_text, content_sha256, now),
        )
        connection.execute(
            "INSERT INTO reading_publications "
            "(revision_id, current_edition_id, status, issue_url, updated_at, published_at) "
            "VALUES (?, ?, 'pending-review', ?, ?, ?) ON CONFLICT(revision_id) DO UPDATE SET "
            "current_edition_id=excluded.current_edition_id, status='pending-review', "
            "updated_at=excluded.updated_at, published_at=NULL",
            (revision_id, edition_id, issue_url, now, published_at),
        )
        connection.execute(
            "INSERT INTO reading_publication_events "
            "(revision_id, edition_id, from_status, to_status, issue_url, note, changed_at) "
            "VALUES (?, ?, ?, 'pending-review', ?, ?, ?)",
            (revision_id, edition_id, previous_status, issue_url, note or "new human-edited edition", now),
        )
    return edition_id
