"""Immutable archive evidence and its inheritance through imported editions."""
from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from functools import lru_cache

from bili_asr.canonical_json import canonical, digest
from bili_asr.source_supplements import KIND, POLICY, validate_supplement
from bili_asr.storage.archive_contracts import _resource


@lru_cache(maxsize=1)
def supplement_objects() -> dict:
    with sqlite3.connect(":memory:") as reference:
        reference.executescript(_resource("schema-source-supplements.sql"))
        return {row[0]: (row[1], row[2]) for row in reference.execute(
            "SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}


def require_supplement_extension(connection, *, required=False) -> bool:
    from bili_asr.storage.database import SchemaContractError, _normalize_manuscript_sql
    actual = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL")}
    expected = supplement_objects()
    if not expected.keys() & actual.keys():
        if required:
            raise SchemaContractError("source-supplement: install on an offline archive copy first")
        return False
    if "publication_import_origins" not in actual:
        raise SchemaContractError("source-supplement: preservation extension is required")
    for name, (kind, sql) in expected.items():
        current = actual.get(name)
        if current is None or current[0] != kind or _normalize_manuscript_sql(current[1]) != _normalize_manuscript_sql(sql):
            raise SchemaContractError(f"source-supplement: missing or altered extension object: {name}")
    if [tuple(row) for row in connection.execute("SELECT singleton,policy FROM source_supplement_contract")] != [(1, POLICY)]:
        raise SchemaContractError("source-supplement: altered policy marker")
    return True


def edition_supplement(connection, edition_id: str) -> dict | None:
    if not require_supplement_extension(connection):
        return None
    row = connection.execute("SELECT * FROM publication_source_supplements WHERE edition_id=?", (edition_id,)).fetchone()
    return dict(row) if row else None


def capture_part_title(connection, edition: dict) -> dict:
    """Capture only the stored part title, never a caller's proposed value."""
    from bili_asr.storage.sources import SourceRepository
    part = SourceRepository(connection).part(edition["video_part_id"])
    source = edition["content"]["source"]["metadata"]
    ref = part["content_ref"]
    if (ref.platform != "bilibili" or any(source[field] != value for field, value in (
            ("platform", ref.platform), ("externalVideoId", ref.external_video_id), ("partIndex", ref.part_index)))):
        raise ValueError("source-supplement: current part differs from frozen identity")
    # Old collection allowed a video-title fallback for an empty single-part
    # title. Without raw evidence, an equal title cannot attest a real part title.
    if part["title"] == part["video_title"]:
        raise ValueError("source-supplement: title may be a video-title fallback; require explicit part evidence")
    evidence = {"version": 1, "platform": ref.platform, "externalVideoId": ref.external_video_id,
        "partIndex": ref.part_index, "videoPartId": edition["video_part_id"], "cid": part["cid"],
        "field": "partTitle", "value": part["title"], "sourceKind": KIND, "observedAt": None}
    result = {"supplementId": digest(evidence), "evidence": evidence}
    validate_supplement(result, {**source, "partTitle": part["title"]}, edition["video_part_id"])
    return result


def stored_supplement(connection, link: dict, source: dict, part_id: int) -> dict:
    row = connection.execute("SELECT * FROM source_metadata_supplements WHERE supplement_id=?", (link["supplement_id"],)).fetchone()
    if row is None:
        raise ValueError("source-supplement: evidence is missing")
    evidence = json.loads(row["evidence_json"])
    result = {"supplementId": row["supplement_id"], "evidence": evidence}
    if canonical(evidence) != row["evidence_json"] or type(row["registered_at"]) is not int or row["registered_at"] < 0:
        raise ValueError("source-supplement: invalid stored evidence")
    validate_supplement(result, source, part_id)
    from bili_asr.storage.sources import SourceRepository
    part = SourceRepository(connection).part(part_id)
    if part["cid"] != evidence["cid"]:
        raise ValueError("source-supplement: CID binding mismatch")
    return result


def expected_source(connection, edition: dict, baseline: dict) -> dict:
    """Rebuild each edition's source without consulting mutable title values."""
    source = deepcopy(baseline["content"]["source"])
    link = edition_supplement(connection, edition["edition_id"])
    if link is None:
        return source
    current_metadata = edition["content"]["source"]["metadata"]
    supplement = stored_supplement(connection, link, current_metadata, edition["video_part_id"])
    if source["metadata"]["partTitle"] is not None:
        raise ValueError("source-supplement: cannot overwrite a frozen title")
    source["metadata"]["partTitle"] = supplement["evidence"]["value"]
    from bili_asr.storage.import_origins import body_digest, import_origin
    from bili_asr.storage.publication import PublicationRepository
    repository = PublicationRepository(connection)
    root = repository.edition(link["root_edition_id"])
    root_link = edition_supplement(connection, root["edition_id"])
    root_origin = import_origin(connection, root["edition_id"])
    current_origin = import_origin(connection, edition["edition_id"])
    if (root_link is None or root_origin is None or current_origin is None
            or root_link["supplement_id"] != link["supplement_id"]
            or root_link["root_edition_id"] != root["edition_id"]
            or any(root_origin[key] != current_origin[key] for key in ("import_id", "root_edition_id"))
            or root["content_version"] != 2 or root["video_part_id"] != baseline["videoPartId"]
            or root["revision_id"] != baseline["revisionId"] or root["content"]["source"] != source
            or not root["parent_edition_id"]):
        raise ValueError("source-supplement: invalid supplemental root")
    parent = repository.edition(root["parent_edition_id"])
    parent_origin = import_origin(connection, parent["edition_id"])
    if (edition_supplement(connection, parent["edition_id"]) is not None or parent_origin is None
            or any(parent_origin[key] != root_origin[key] for key in ("import_id", "root_edition_id"))
            or parent["content_version"] != 2 or parent["revision_id"] != baseline["revisionId"]
            or parent["video_part_id"] != baseline["videoPartId"]
            or parent["content"]["source"] != baseline["content"]["source"]):
        raise ValueError("source-supplement: invalid supplemental parent")
    expected_content = deepcopy(parent["content"])
    expected_content["source"] = source
    if (root["content"] != expected_content
            or root_origin["expected_markdown_sha256"] != body_digest(root["content"]["markdown"])):
        raise ValueError("source-supplement: supplementation changed existing manuscript content")
    return source


def validate_supplement_inheritance(connection, child: dict, parent: dict) -> None:
    child_link = edition_supplement(connection, child["edition_id"])
    parent_link = edition_supplement(connection, parent["edition_id"])
    if child_link and child_link["root_edition_id"] == child["edition_id"]:
        if parent_link:
            raise ValueError("source-supplement: repeated supplemental root")
        return
    if (child_link is None) != (parent_link is None) or (child_link and any(
            child_link[key] != parent_link[key] for key in ("supplement_id", "root_edition_id"))):
        raise ValueError("source-supplement: ancestor lost or changed evidence")


def inherit_supplement(connection, parent_id: str, edition_id: str) -> None:
    link = edition_supplement(connection, parent_id)
    if link:
        connection.execute("INSERT INTO publication_source_supplements VALUES (?,?,?)",
            (edition_id, link["supplement_id"], link["root_edition_id"]))
