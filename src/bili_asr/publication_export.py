"""Reader release/draft snapshots and explicitly selected private review material."""

from __future__ import annotations

from contextlib import contextmanager
import difflib
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from bili_asr.export_snapshot import ExportSnapshotError, guard_output, json_bytes, replace_snapshot
from bili_asr.publication import content_from_ai, get_ai_artifacts, get_edition, render_publication, verify_release
from bili_asr.storage.database import require_manuscript_schema
from bili_asr.publication_content_v2 import content_from_ai_v2, render_publish_v2


def _source_fields(edition: dict) -> dict:
    source = edition["content"]["source"]
    if edition["content_version"] == 1:
        return {"bvid": source["bvid"], "pageIndex": source["pageIndex"], "sourceUrl": source["url"]}
    return {"platform": source["platform"], "externalVideoId": source["externalVideoId"],
            "partIndex": source["partIndex"], "sourceUrl": source["url"],
            "sourceMetadata": source["metadata"], "sourcePublishedAt": source["metadata"]["sourcePublishedAt"],
            "pubdateUnix": source["metadata"]["pubdateUnix"], "contentVersion": 2}


def _render_edition(edition: dict) -> bytes:
    return (render_publish_v2 if edition["content_version"] == 2 else render_publication)(edition["content"])


@contextmanager
def _read_snapshot(connection: sqlite3.Connection) -> Iterator[None]:
    owned = not connection.in_transaction
    if owned:
        connection.execute("BEGIN")
    try:
        yield
    finally:
        if owned:
            connection.rollback()


def _public_entry(release: dict, edition: dict, review_document: bytes) -> dict:
    content = edition["content"]
    source = content["source"]
    part_id = edition["video_part_id"]
    if source["videoPartId"] != part_id or release["video_part_id"] != part_id:
        raise ExportSnapshotError("publication source identity differs from its release")
    return {
        "manuscriptType": "publication",
        "slug": f"part-{part_id}",
        "title": content["title"],
        "summary": content["summary"],
        "tags": content["tags"],
        "attribution": content["attribution"],
        "editorNote": content["editorNote"],
        "releaseId": release["release_id"],
        "editionId": edition["edition_id"],
        "aiRevisionId": edition["revision_id"],
        "videoPartId": part_id,
        **_source_fields(edition),
        "contentSha256": edition["content_sha256"],
        "artifactSha256": release["artifact_sha256"],
        "templateVersion": release["template_version"],
        "publishedAt": release["published_at"],
        "file": f"articles/part-{part_id}/publish.md",
        "reviewFile": f"articles/part-{part_id}/review.md",
        "reviewArtifactSha256": hashlib.sha256(review_document).hexdigest(),
    }


def export_publications(
    connection: sqlite3.Connection,
    *,
    artifact_roots: tuple[Path, ...],
    output: Path,
) -> int:
    """Export only valid current releases, failing the whole export on corruption."""
    require_manuscript_schema(connection)
    output = guard_output(connection, output, artifact_roots)
    files: dict[str, bytes] = {}
    articles = []
    with _read_snapshot(connection):
        broken_release = connection.execute(
            "SELECT r.release_id FROM publication_releases r "
            "LEFT JOIN publication_heads h ON h.video_part_id = r.video_part_id "
            "WHERE r.status = 'published' AND h.current_release_id IS NOT r.release_id LIMIT 1"
        ).fetchone()
        if broken_release is not None:
            raise ExportSnapshotError("published release has no matching current publication head")
        # Read heads directly: a broken release relationship must not disappear
        # through an inner join and become an apparently successful empty export.
        heads = connection.execute(
            "SELECT video_part_id, current_release_id FROM publication_heads "
            "WHERE current_release_id IS NOT NULL ORDER BY video_part_id"
        ).fetchall()
        for head in heads:
            release, edition, document = verify_release(connection, str(head["current_release_id"]), artifact_roots)
            if release["status"] != "published" or release["video_part_id"] != head["video_part_id"]:
                raise ExportSnapshotError("publication head does not identify a valid current release")
            artifacts = get_ai_artifacts(connection, edition["revision_id"], artifact_roots)
            review_document = artifacts["review.md"]
            review_document.decode("utf-8")
            entry = _public_entry(release, edition, review_document)
            if entry["file"] in files:
                raise ExportSnapshotError("duplicate public article identity")
            if hashlib.sha256(document).hexdigest() != entry["artifactSha256"]:
                raise ExportSnapshotError("release artifact hash mismatch")
            document.decode("utf-8")
            files[entry["file"]] = document
            files[entry["reviewFile"]] = review_document
            articles.append(entry)
    articles.sort(key=lambda entry: (-entry["publishedAt"], entry["videoPartId"]))
    version = 3 if any(entry.get("contentVersion") == 2 for entry in articles) else 2
    files["catalog.json"] = json_bytes({"schemaVersion": version, "manuscriptType": "publication", "articles": articles})
    replace_snapshot(output, kind="publication-export", files=files)
    return len(articles)


def export_publication_drafts(
    connection: sqlite3.Connection,
    *,
    artifact_roots: tuple[Path, ...],
    output: Path,
) -> int:
    """Export current reader drafts that have never had a release of any status."""
    require_manuscript_schema(connection)
    output = guard_output(connection, output, artifact_roots)
    files: dict[str, bytes] = {}
    articles = []
    with _read_snapshot(connection):
        missing_head = connection.execute(
            "SELECT e.video_part_id FROM publication_editions e "
            "LEFT JOIN publication_heads h ON h.video_part_id = e.video_part_id "
            "WHERE h.video_part_id IS NULL LIMIT 1"
        ).fetchone()
        if missing_head is not None:
            raise ExportSnapshotError("edition part has no current draft head")
        broken_release = connection.execute(
            "SELECT r.release_id FROM publication_releases r "
            "LEFT JOIN publication_heads h ON h.video_part_id = r.video_part_id "
            "WHERE r.status = 'published' AND h.current_release_id IS NOT r.release_id LIMIT 1"
        ).fetchone()
        if broken_release is not None:
            raise ExportSnapshotError("published release has no matching current publication head")
        # Read heads before checking eligibility. An invalid pointer must fail
        # rather than vanish through a join or become an empty draft snapshot.
        heads = connection.execute(
            "SELECT video_part_id, current_edition_id FROM publication_heads ORDER BY video_part_id"
        ).fetchall()
        for head in heads:
            edition = get_edition(connection, head["current_edition_id"])
            if (edition["video_part_id"] != head["video_part_id"]
                    or edition["current_edition_id"] != edition["edition_id"]):
                raise ExportSnapshotError("draft head does not identify a current edition of the same part")
            released = connection.execute(
                "SELECT 1 FROM publication_releases WHERE edition_id = ? LIMIT 1",
                (edition["edition_id"],),
            ).fetchone()
            if released is not None:
                continue
            # Verify both immutable AI artifacts before exporting the original
            # review reference. Model-call audits remain outside the snapshot.
            artifacts = get_ai_artifacts(connection, edition["revision_id"], artifact_roots)
            review_document = artifacts["review.md"]
            review_document.decode("utf-8")
            content = edition["content"]
            document = _render_edition(edition)
            slug = f"edition-{edition['edition_id']}"
            entry = {
                "manuscriptType": "publication-draft", "slug": slug,
                "title": content["title"], "summary": content["summary"], "tags": content["tags"],
                "attribution": content["attribution"], "editorNote": content["editorNote"],
                "editionId": edition["edition_id"], "aiRevisionId": edition["revision_id"],
                "videoPartId": edition["video_part_id"], **_source_fields(edition),
                "contentSha256": edition["content_sha256"],
                "artifactSha256": hashlib.sha256(document).hexdigest(),
                "reviewStatus": edition["review_status"], "createdAt": edition["created_at"],
                "file": f"drafts/{slug}/preview.md",
                "reviewFile": f"drafts/{slug}/review.md",
                "reviewArtifactSha256": hashlib.sha256(review_document).hexdigest(),
            }
            if entry["file"] in files:
                raise ExportSnapshotError("duplicate reader draft identity")
            files[entry["file"]] = document
            files[entry["reviewFile"]] = review_document
            articles.append(entry)
    articles.sort(key=lambda entry: (-entry["createdAt"], entry["videoPartId"], entry["editionId"]))
    version = 3 if any(entry.get("contentVersion") == 2 for entry in articles) else 2
    files["catalog.json"] = json_bytes({"schemaVersion": version, "manuscriptType": "publication-draft", "articles": articles})
    replace_snapshot(output, kind="publication-draft-export", files=files)
    return len(articles)


def _difference(before: str, after: str, before_name: str, after_name: str) -> bytes:
    # Preserve missing-newline information in a conventional patch rather than
    # silently treating final-line differences as identical text.
    result = []
    for line in difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=before_name, tofile=after_name):
        result.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(result).encode("utf-8")


def export_editorial(
    connection: sqlite3.Connection,
    *,
    revision_id: str,
    edition_id: str,
    artifact_roots: tuple[Path, ...],
    output: Path,
) -> dict:
    """Export an exact edition and its immutable AI baseline for private review."""
    require_manuscript_schema(connection)
    output = guard_output(connection, output, artifact_roots)
    with _read_snapshot(connection):
        edition = get_edition(connection, edition_id)
        if edition["revision_id"] != revision_id:
            raise ExportSnapshotError("selected edition does not belong to the selected AI revision")
        artifacts = get_ai_artifacts(connection, revision_id, artifact_roots)
        baseline = artifacts["ai-draft.md"].decode("utf-8")
        artifacts["review.md"].decode("utf-8")
        content = edition["content"]
        parent_id = edition["parent_edition_id"]
        parent = get_edition(connection, parent_id) if parent_id else None
        if parent is not None and parent["video_part_id"] != edition["video_part_id"]:
            raise ExportSnapshotError("edition parent belongs to another video part")
        parent_content = parent["content"] if parent else None
        reviews = [dict(row) for row in connection.execute(
            "SELECT * FROM publication_edition_reviews WHERE edition_id = ? ORDER BY updated_at, review_id",
            (edition_id,),
        )]
        events = [dict(row) for row in connection.execute(
            "SELECT * FROM publication_events WHERE edition_id = ? ORDER BY event_id", (edition_id,),
        )]
        row = connection.execute(
            "SELECT r.quality_status, r.created_at, i.prepared_json FROM editorial_revisions r "
            "JOIN editorial_inputs i ON i.input_id = r.input_id WHERE r.revision_id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ExportSnapshotError("selected AI revision has no fixed input")
        prepared = json.loads(row["prepared_json"])
        version = edition["content_version"]
        ai_content = (content_from_ai_v2 if version == 2 else content_from_ai)(prepared, baseline)
        ai_metadata = {
            "revisionId": revision_id,
            "templateVersion": "ai-draft-v2" if version == 2 else "ai-draft-v1",
            "qualityStatus": row["quality_status"],
            "createdAt": row["created_at"],
            "config": prepared["snapshot"]["config"],
            "promptSha256": prepared["snapshot"]["prompt_sha256"],
            "artifactSha256": {name: hashlib.sha256(value).hexdigest() for name, value in artifacts.items()},
        }
        review_document = {
            "schemaVersion": 1,
            "manuscriptType": "editorial-review",
            "revisionId": revision_id,
            "editionId": edition_id,
            "videoPartId": edition["video_part_id"],
            "contentSha256": edition["content_sha256"],
            "reviewStatus": edition["review_status"],
            "parentEditionId": parent_id,
            "parentContentSha256": parent["content_sha256"] if parent else None,
            "reviews": reviews,
            "events": events,
            "ai": ai_metadata,
        }
        # Full-object parent patches also show reader-visible metadata changes.
        files = {
            **artifacts,
            "edition.md": _render_edition(edition),
            "edition.json": json_bytes(content),
            "review.json": json_bytes(review_document),
            "differences/ai.patch": _difference(json_bytes(ai_content).decode("utf-8"), json_bytes(content).decode("utf-8"),
                                                 "ai-baseline.json", "edition.json"),
            "differences/parent.patch": _difference(
                json_bytes(parent_content).decode("utf-8"), json_bytes(content).decode("utf-8"),
                f"edition-{parent_id}.json", "edition.json",
            ) if parent else _difference(json_bytes(ai_content).decode("utf-8"), json_bytes(content).decode("utf-8"),
                                         "ai-baseline.json", "edition.json"),
        }
    snapshot_id = replace_snapshot(output, kind="editorial-export", files=files)
    return {"revision_id": revision_id, "edition_id": edition_id, "content_sha256": edition["content_sha256"], "snapshot_id": snapshot_id, "output": str(output)}
