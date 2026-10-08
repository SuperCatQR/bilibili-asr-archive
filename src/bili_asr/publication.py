"""Frozen reader content, exact-version approval and explicit publication."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterable
from urllib.parse import urlparse

from bili_asr.editorial import canonical, digest, render_documents
from bili_asr.manuscript_files import atomic_write_artifact, read_artifact
from bili_asr.storage.publication import PublicationConflictError, PublicationRepository


PUBLISH_TEMPLATE_VERSION = "publish-v1"
AI_TEMPLATE_VERSION = "ai-draft-v1"
_CONTENT_KEYS = frozenset({"title", "markdown", "summary", "tags", "source", "attribution", "editorNote"})
_EDITABLE_METADATA = _CONTENT_KEYS - {"markdown", "source"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY = re.compile(r"[A-Za-z0-9_-]+\Z")


def _text(value: Any, name: str, *, nonempty: bool = False, multiline: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"publication-content: {name} must be text")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"publication-content: {name} must be valid UTF-8 text") from exc
    if "\x00" in value or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"publication-content: {name} contains control characters")
    if not multiline and ("\n" in value or "\t" in value):
        raise ValueError(f"publication-content: {name} must be one line")
    value = value.strip()
    if nonempty and not value:
        raise ValueError(f"publication-content: {name} must not be empty")
    return value


def _actor(actor: str) -> str:
    return _text(actor, "actor", nonempty=True, multiline=False)


def normalize_content(content: dict[str, Any]) -> dict[str, Any]:
    """Normalize the entire reader-visible object before canonical JSON hashing."""
    if not isinstance(content, dict) or set(content) != _CONTENT_KEYS:
        raise ValueError("publication-content: reader content fields do not match the contract")
    source = content["source"]
    if not isinstance(source, dict) or set(source) != {"bvid", "pageIndex", "videoPartId", "url"}:
        raise ValueError("publication-content: invalid source fields")
    bvid = _text(source["bvid"], "source.bvid", nonempty=True, multiline=False)
    if not _IDENTITY.fullmatch(bvid):
        raise ValueError("publication-content: invalid BVID")
    for key, minimum in (("pageIndex", 0), ("videoPartId", 1)):
        if type(source[key]) is not int or source[key] < minimum:
            raise ValueError(f"publication-content: source.{key} must be an integer >= {minimum}")
    url = f"https://www.bilibili.com/video/{bvid}/?p={source['pageIndex'] + 1}"
    if source["url"] != url:
        raise ValueError("publication-content: source URL must match the frozen video and part")
    tags = content["tags"]
    if not isinstance(tags, list):
        raise ValueError("publication-content: tags must be a list")
    tags = [_text(tag, "tag", nonempty=True, multiline=False) for tag in tags]
    if len(tags) != len(set(tags)):
        raise ValueError("publication-content: duplicate tags are forbidden")
    normalized = {
        "title": _text(content["title"], "title", nonempty=True, multiline=False),
        "markdown": _text(content["markdown"], "markdown", nonempty=True) + "\n",
        "summary": _text(content["summary"], "summary"),
        "tags": tags,
        "source": {"bvid": bvid, "pageIndex": source["pageIndex"], "videoPartId": source["videoPartId"], "url": url},
        "attribution": _text(content["attribution"], "attribution", nonempty=True),
        "editorNote": _text(content["editorNote"], "editorNote"),
    }
    return normalized


def _roots(artifact_roots: Iterable[Path]) -> tuple[Path, ...]:
    # CLI callers normally pass read_bases(); accepting ArtifactRoots keeps the
    # filesystem policy in one place without making it a service dependency.
    if hasattr(artifact_roots, "read_bases"):
        artifact_roots = artifact_roots.read_bases()
    roots = tuple(Path(root) for root in artifact_roots)
    if not roots:
        raise ValueError("manuscript-path: at least one artifact root is required")
    return roots


def _revision(connection: sqlite3.Connection, revision_id: str) -> tuple[dict, dict]:
    if not isinstance(revision_id, str) or not _IDENTITY.fullmatch(revision_id):
        raise ValueError("publication-revision: invalid revision ID")
    row = connection.execute(
        "SELECT r.*, i.video_part_id, i.base_transcript_id, i.reference_transcript_id, "
        "i.prepared_json FROM editorial_revisions r "
        "JOIN editorial_inputs i ON i.input_id = r.input_id WHERE r.revision_id = ?",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise ValueError("publication-revision: unknown revision ID")
    try:
        prepared = json.loads(row["prepared_json"])
        snapshot = prepared["snapshot"]
        blocks = json.loads(row["blocks_json"])
        metadata = snapshot["metadata"]
        if (prepared["input_id"] != row["input_id"] or digest(snapshot) != row["input_id"]
                or digest({"input_id": row["input_id"], "blocks": blocks}) != revision_id
                or snapshot["video_part_id"] != row["video_part_id"]
                or snapshot["base"]["transcript_id"] != row["base_transcript_id"]
                or (snapshot["reference"]["transcript_id"] if snapshot["reference"] else None)
                    != row["reference_transcript_id"]):
            raise ValueError("publication-integrity: frozen revision identity mismatch")
        for transcript_id in (row["base_transcript_id"], row["reference_transcript_id"]):
            if transcript_id is None:
                continue
            transcript = connection.execute(
                "SELECT video_part_id FROM transcripts WHERE transcript_id = ?", (transcript_id,)
            ).fetchone()
            if transcript is None or transcript[0] != row["video_part_id"]:
                raise ValueError("publication-integrity: frozen transcript belongs to another part")
        job = connection.execute(
            "SELECT video_part_id FROM workflow_jobs WHERE job_id = ?", (row["job_id"],)
        ).fetchone()
        if job is None or job[0] != row["video_part_id"]:
            raise ValueError("publication-integrity: frozen revision job belongs to another part")
        live = connection.execute(
            "SELECT bvid, page_index FROM video_parts WHERE video_part_id = ?", (row["video_part_id"],)
        ).fetchone()
        if live is None or tuple(live) != (metadata["bvid"], metadata["page_index"]):
            raise ValueError("publication-integrity: frozen revision belongs to another video part")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("publication-integrity: invalid frozen revision") from exc
    return dict(row), prepared


def get_ai_artifacts(connection: sqlite3.Connection, revision_id: str,
                     artifact_roots: Iterable[Path]) -> dict[str, bytes]:
    PublicationRepository(connection)
    revision, prepared = _revision(connection, revision_id)
    documents = render_documents(prepared["snapshot"]["metadata"], prepared,
                                 json.loads(revision["blocks_json"]), revision_id)
    rows = connection.execute(
        "SELECT * FROM document_artifacts WHERE revision_id = ?", (revision_id,)
    ).fetchall()
    expected = {"ai-draft.md": "ai-draft", "review.md": "review-reference"}
    if len(rows) != 2 or {r["artifact_name"] for r in rows} != expected.keys():
        raise ValueError("publication-integrity: complete paired AI artifacts are required")
    roots = _roots(artifact_roots)
    artifacts = {}
    for row in rows:
        name = row["artifact_name"]
        path = f"documents/part-{revision['video_part_id']}/{revision_id}/{AI_TEMPLATE_VERSION}/{name}"
        if (row["template_version"] != AI_TEMPLATE_VERSION or row["manuscript_role"] != expected[name]
                or row["relative_path"] != path or not _SHA256.fullmatch(row["content_sha256"])
                or row["content_sha256"] != hashlib.sha256(documents[name].encode("utf-8")).hexdigest()):
            raise ValueError("publication-integrity: AI artifact identity does not match revision")
        artifacts[name] = read_artifact(path, row["content_sha256"], roots)
    return artifacts


def get_edition(connection: sqlite3.Connection, edition_id: str) -> dict:
    repository = PublicationRepository(connection)
    edition = repository.edition(edition_id)
    revision, prepared = _revision(connection, edition["revision_id"])
    normalized = normalize_content(edition["content"])
    metadata = prepared["snapshot"]["metadata"]
    if (normalized != edition["content"] or edition["video_part_id"] != revision["video_part_id"]
            or normalized["source"]["videoPartId"] != edition["video_part_id"]
            or normalized["source"]["bvid"] != metadata["bvid"]
            or normalized["source"]["pageIndex"] != metadata["page_index"]):
        raise ValueError("publication-integrity: edition content or source identity mismatch")
    if edition["parent_edition_id"]:
        parent = repository.edition(edition["parent_edition_id"])
        if parent["video_part_id"] != edition["video_part_id"]:
            raise ValueError("publication-integrity: edition parent belongs to another part")
    return edition


def content_from_ai(prepared: dict, markdown_text: str) -> dict:
    """Build the complete default edition and review baseline from frozen input."""
    snapshot = prepared["snapshot"]
    metadata = snapshot["metadata"]
    return normalize_content({
        "title": metadata["title"], "markdown": markdown_text,
        "summary": "", "tags": [],
        "source": {"bvid": metadata["bvid"], "pageIndex": metadata["page_index"],
                   "videoPartId": snapshot["video_part_id"],
                   "url": f"https://www.bilibili.com/video/{metadata['bvid']}/?p={metadata['page_index'] + 1}"},
        "attribution": "\u6839\u636e\u89c6\u9891\u8f6c\u5f55\u6574\u7406\uff0c\u7ecf AI "
                       "\u5408\u6210\u5e76\u7531\u4eba\u5de5\u5ba1\u6838\u53d1\u5e03\u3002",
        "editorNote": "",
    })


def create_edition(connection: sqlite3.Connection, *, revision_id: str,
                   artifact_roots: Iterable[Path], actor: str, note: str = "",
                   expected_edition_id: str | None = None) -> dict:
    actor, note = _actor(actor), _text(note, "note")
    repository = PublicationRepository(connection)
    artifacts = get_ai_artifacts(connection, revision_id, artifact_roots)
    with repository.transaction():
        revision, prepared = _revision(connection, revision_id)
        content = content_from_ai(prepared, artifacts["ai-draft.md"].decode("utf-8"))
        return repository.insert_edition(
            part_id=revision["video_part_id"], revision_id=revision_id, content=content,
            parent_edition_id=expected_edition_id, actor=actor, note=note, event_type="created",
        )


def edit_edition(connection: sqlite3.Connection, *, edition_id: str, markdown_text: str,
                 metadata: dict | None = None, actor: str, note: str) -> dict:
    actor, note = _actor(actor), _text(note, "note", nonempty=True)
    if metadata is not None and (not isinstance(metadata, dict) or set(metadata) - _EDITABLE_METADATA):
        raise ValueError("publication-content: metadata contains unsupported or immutable fields")
    repository = PublicationRepository(connection)
    with repository.transaction():
        parent = get_edition(connection, edition_id)
        content = deepcopy(parent["content"])
        content["markdown"] = markdown_text
        content.update(metadata or {})
        return repository.insert_edition(
            part_id=parent["video_part_id"], revision_id=parent["revision_id"],
            content=normalize_content(content), parent_edition_id=edition_id,
            actor=actor, note=note, event_type="edited",
        )


def review_edition(connection: sqlite3.Connection, *, edition_id: str, status: str,
                   content_sha256: str, expected_status: str, actor: str,
                   note: str = "", issue_url: str | None = None) -> dict:
    actor, note = _actor(actor), _text(note, "note")
    if not isinstance(content_sha256, str) or not _SHA256.fullmatch(content_sha256):
        raise ValueError("publication-approval: invalid reviewed content hash")
    if issue_url is not None:
        issue_url = _text(issue_url, "issue URL", nonempty=True, multiline=False)
        parsed = urlparse(issue_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("publication-review: issue URL must be an absolute HTTPS URL")
    repository = PublicationRepository(connection)
    with repository.transaction():
        get_edition(connection, edition_id)
        return repository.set_review(
            edition_id=edition_id, status=status, content_sha256=content_sha256,
            expected_status=expected_status, actor=actor, note=note, issue_url=issue_url,
        )


def _markdown_inline(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", text)


def render_publication(content: dict[str, Any]) -> bytes:
    """Render only the approved frozen reader object with a fixed template."""
    content = normalize_content(content)
    parts = [f"# {_markdown_inline(content['title'])}"]
    if content["summary"]:
        parts.append(content["summary"])
    parts.append(content["markdown"].rstrip("\n"))
    source = content["source"]
    parts.append(f"\u6765\u6e90\uff1a[{_markdown_inline(source['bvid'])} / P{source['pageIndex'] + 1}]({source['url']})")
    if content["attribution"]:
        parts.append(content["attribution"])
    if content["editorNote"]:
        parts.append(content["editorNote"])
    if content["tags"]:
        parts.append("\u6807\u7b7e\uff1a" + "\u3001".join(_markdown_inline(tag) for tag in content["tags"]))
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def _verify_release_identity(connection: sqlite3.Connection, release: dict) -> dict:
    edition = get_edition(connection, release["edition_id"])
    expected_id = digest({"edition_id": edition["edition_id"], "content_sha256": edition["content_sha256"],
                          "template_version": PUBLISH_TEMPLATE_VERSION})
    expected_path = f"publications/part-{edition['video_part_id']}/{expected_id}/{PUBLISH_TEMPLATE_VERSION}/publish.md"
    if (release["release_id"] != expected_id or release["video_part_id"] != edition["video_part_id"]
            or release["review_id"] != edition["review_id"] or edition["review_status"] != "approved"
            or release["content_sha256"] != edition["content_sha256"]
            or release["template_version"] != PUBLISH_TEMPLATE_VERSION or release["relative_path"] != expected_path
            or release["artifact_sha256"] != hashlib.sha256(render_publication(edition["content"])).hexdigest()):
        raise ValueError("publication-integrity: release is not bound to the exact approved edition")
    if (release["status"] == "published") != (edition["current_release_id"] == release["release_id"]):
        raise ValueError("publication-integrity: release state disagrees with effective head")
    events = connection.execute(
        "SELECT * FROM publication_events WHERE release_id = ? ORDER BY event_id",
        (release["release_id"],),
    ).fetchall()
    previous = None
    transitions = {None: {"published"}, "published": {"superseded", "withdrawn"},
                   "superseded": {"withdrawn"}, "withdrawn": set()}
    for event in events:
        status = event["event_type"]
        if (status not in transitions.get(previous, set()) or event["from_status"] != previous
                or event["to_status"] != status or event["video_part_id"] != edition["video_part_id"]
                or event["edition_id"] != edition["edition_id"] or event["review_id"] != edition["review_id"]
                or event["content_sha256"] != edition["content_sha256"]
                or (status == "published" and event["actor"] != release["published_by"])):
            raise ValueError("publication-integrity: release audit event identity or transition mismatch")
        previous = status
    if previous != release["status"]:
        raise ValueError("publication-integrity: release state disagrees with audit events")
    return edition


def verify_release(connection: sqlite3.Connection, release_id: str,
                   artifact_roots: Iterable[Path]) -> tuple[dict, dict, bytes]:
    repository = PublicationRepository(connection)
    release = repository.release(release_id)
    edition = _verify_release_identity(connection, release)
    data = read_artifact(release["relative_path"], release["artifact_sha256"], _roots(artifact_roots))
    return release, edition, data


def publish_edition(connection: sqlite3.Connection, *, edition_id: str,
                    artifact_roots: Iterable[Path], write_root: Path, actor: str,
                    expected_release_id: str | None = None) -> dict:
    actor = _actor(actor)
    roots = _roots(artifact_roots)
    repository = PublicationRepository(connection)
    existing = repository.release_for_edition(edition_id)
    if existing:
        release, _, _ = verify_release(connection, existing["release_id"], roots)
        return {**release, "idempotent": True}
    edition = get_edition(connection, edition_id)
    if edition["review_status"] != "approved":
        raise ValueError("publication-approval: edition has not been approved")
    if edition["current_release_id"] != expected_release_id:
        raise PublicationConflictError("publication-conflict: effective release differs from expected release")
    if expected_release_id:
        verify_release(connection, expected_release_id, roots)
    data = render_publication(edition["content"])
    release_id = digest({"edition_id": edition_id, "content_sha256": edition["content_sha256"],
                         "template_version": PUBLISH_TEMPLATE_VERSION})
    path = f"publications/part-{edition['video_part_id']}/{release_id}/{PUBLISH_TEMPLATE_VERSION}/publish.md"
    atomic_write_artifact(Path(write_root), path, data)
    with repository.transaction():
        existing = repository.release_for_edition(edition_id)
        if existing:
            release, _, _ = verify_release(connection, existing["release_id"], roots)
            return {**release, "idempotent": True}
        current = get_edition(connection, edition_id)
        if current["content_sha256"] != edition["content_sha256"] or current["review_status"] != "approved":
            raise ValueError("publication-approval: approval or content changed before publication")
        # Verify installed bytes immediately before registering the database head.
        read_artifact(path, hashlib.sha256(data).hexdigest(), (Path(write_root),))
        release = {
            "release_id": release_id, "video_part_id": edition["video_part_id"],
            "edition_id": edition_id, "review_id": edition["review_id"],
            "content_sha256": edition["content_sha256"], "template_version": PUBLISH_TEMPLATE_VERSION,
            "relative_path": path, "artifact_sha256": hashlib.sha256(data).hexdigest(),
            "published_at": int(time.time()), "published_by": actor, "status": "published",
        }
        return {**repository.register_release(edition=current, release=release,
                    expected_release_id=expected_release_id, actor=actor), "idempotent": False}


def withdraw_release(connection: sqlite3.Connection, *, release_id: str, actor: str, note: str) -> dict:
    actor, note = _actor(actor), _text(note, "note", nonempty=True)
    repository = PublicationRepository(connection)
    with repository.transaction():
        release = repository.release(release_id)
        _verify_release_identity(connection, release)
        return repository.withdraw(release_id=release_id, actor=actor, note=note)


__all__ = ["PublicationConflictError", "create_edition", "edit_edition", "review_edition",
           "publish_edition", "withdraw_release", "get_edition", "verify_release",
           "get_ai_artifacts", "normalize_content", "content_from_ai", "render_publication", "PUBLISH_TEMPLATE_VERSION"]
