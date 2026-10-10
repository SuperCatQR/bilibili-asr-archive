"""Public origin profile: exact fields and catalog/evidence cross-file binding."""
from __future__ import annotations

import re

from bili_asr.canonical_json import digest
from bili_asr.contracts.registry import ORIGIN_PROFILE as PROFILE

COMMON = {"kind", "editionId", "aiRevisionId", "videoPartId", "contentSha256",
          "sourceMetadataSha256", "inputVersion", "aiTemplateVersion"}
IMPORTED = {"importId", "policyVersion", "legacyAiRevisionId", "legacyEditionId", "legacyReleaseId",
            "baselineBodySha256", "currentBodySha256", "reviewArtifactSha256", "importedAt",
            "bodyPreserved", "metadataEvidence"}


def public_origin(connection, edition: dict, artifact_roots) -> dict:
    from bili_asr.services.preserved_body_import import check_preserved_body_import
    from bili_asr.storage.import_origins import import_origin, read_baseline
    from bili_asr.storage.publication import read_revision
    from bili_asr.storage.archive_contracts import frozen_version

    if edition["content_version"] != 2:
        raise ValueError("origin-profile: legacy content cannot enter universal-origin-v1")
    origin = import_origin(connection, edition["edition_id"])
    result = {"kind": "ai-generated-v2", "editionId": edition["edition_id"],
        "aiRevisionId": edition["revision_id"], "videoPartId": edition["video_part_id"],
        "contentSha256": edition["content_sha256"], "sourceMetadataSha256": digest(edition["content"]["source"]["metadata"]),
        "inputVersion": 2, "aiTemplateVersion": "ai-draft-v2"}
    if origin is None:
        revision, _ = read_revision(connection, edition["revision_id"])
        if frozen_version(connection, "input", revision["input_id"]) != 2:
            raise ValueError("origin-profile: native edition requires v2 input")
        return result
    checked = check_preserved_body_import(connection, edition_id=edition["edition_id"], artifact_roots=artifact_roots)
    stored = read_baseline(connection, origin["import_id"])
    baseline = stored["baseline"]
    result.update({"kind": "preserved-legacy-body" if checked["bodyPreserved"] else "edited-after-preservation",
        "inputVersion": 1, "aiTemplateVersion": "ai-draft-v1", "importId": origin["import_id"],
        "policyVersion": baseline["policyVersion"], "legacyAiRevisionId": baseline["revisionId"],
        "legacyEditionId": baseline["legacyEditionId"], "legacyReleaseId": baseline["legacyReleaseId"],
        "baselineBodySha256": checked["baselineBodySha256"], "currentBodySha256": checked["currentBodySha256"],
        "reviewArtifactSha256": checked["reviewArtifactSha256"], "importedAt": stored["imported_at"],
        "bodyPreserved": checked["bodyPreserved"], "metadataEvidence": [
            {"field": field, "kind": evidence["kind"], "observedAt": evidence["observedAt"], "valueSha256": evidence["valueSha256"]}
            for field, evidence in sorted(baseline["metadataEvidence"].items())]})
    return result


def validate_origins(value: object, articles: list[dict], manuscript_type: str) -> dict:
    from bili_asr.export_snapshot import ExportSnapshotError

    def fail(message):
        raise ExportSnapshotError("origin-profile: " + message)

    def hexadecimal(identity, size=64):
        return isinstance(identity, str) and re.fullmatch(rf"[0-9a-f]{{{size}}}", identity) is not None

    if (not isinstance(value, dict) or set(value) != {"schemaVersion", "manuscriptType", "contractProfile", "entries"}
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or value["manuscriptType"] != manuscript_type or value["contractProfile"] != PROFILE
            or not isinstance(value["entries"], list)):
        fail("unknown origins envelope")
    indexed = {article["editionId"]: article for article in articles}
    if len(indexed) != len(articles) or len(value["entries"]) != len(articles):
        fail("one origin per article is required")
    seen = []
    for entry in value["entries"]:
        if not isinstance(entry, dict):
            fail("origin must be an object")
        native = entry.get("kind") == "ai-generated-v2"
        if entry.get("kind") not in {"ai-generated-v2", "preserved-legacy-body", "edited-after-preservation"} or set(entry) != (COMMON if native else COMMON | IMPORTED):
            fail("unknown origin kind or fields")
        if not hexadecimal(entry["editionId"], 32):
            fail("invalid edition ID")
        article = indexed.get(entry["editionId"])
        if article is None or article.get("contentVersion") != 2:
            fail("origin has no universal article")
        seen.append(entry["editionId"])
        for field in ("editionId", "aiRevisionId", "videoPartId", "contentSha256"):
            if type(entry[field]) is not type(article[field]) or entry[field] != article[field]:
                fail("article identity mismatch: " + field)
        if entry["sourceMetadataSha256"] != digest(article["sourceMetadata"]):
            fail("source metadata digest mismatch")
        integers = [entry["videoPartId"], article["partIndex"], article.get("createdAt", article.get("publishedAt"))]
        integers.extend(value for value in article["sourceMetadata"].values() if type(value) is int)
        if any(type(value) is not int or not 0 <= value <= 2**53 - 1 for value in integers):
            fail("public integer outside JavaScript safe range")
        if type(entry["inputVersion"]) is not int or entry["inputVersion"] != (2 if native else 1) or entry["aiTemplateVersion"] != ("ai-draft-v2" if native else "ai-draft-v1"):
            fail("origin input/template mismatch")
        if native:
            continue
        for field in ("importId", "baselineBodySha256", "currentBodySha256", "reviewArtifactSha256"):
            if not hexadecimal(entry[field]):
                fail("invalid digest: " + field)
        for field, size in (("legacyEditionId", 32), ("legacyReleaseId", 64)):
            if entry[field] is not None and not hexadecimal(entry[field], size):
                fail("invalid legacy identity")
        if (entry["legacyAiRevisionId"] != article["aiRevisionId"] or entry["policyVersion"] != "legacy-frozen-facts-v1"
                or entry["reviewArtifactSha256"] != article["reviewArtifactSha256"]
                or type(entry["importedAt"]) is not int or not 0 <= entry["importedAt"] <= 2**53 - 1):
            fail("invalid import binding or time")
        preserved = entry["kind"] == "preserved-legacy-body"
        if type(entry["bodyPreserved"]) is not bool or entry["bodyPreserved"] != preserved or (entry["baselineBodySha256"] == entry["currentBodySha256"]) != preserved:
            fail("false body preservation claim")
        evidence = entry["metadataEvidence"]
        if not isinstance(evidence, list) or len(evidence) != len(article["sourceMetadata"]):
            fail("incomplete metadata evidence")
        fields = []
        for fact in evidence:
            if not isinstance(fact, dict) or set(fact) != {"field", "kind", "observedAt", "valueSha256"}:
                fail("invalid evidence fields")
            field = fact["field"]
            if not isinstance(field, str) or field not in article["sourceMetadata"]:
                fail("unknown evidence field")
            fields.append(field)
            known = field in {"version", "platform", "externalVideoId", "partIndex", "title"}
            if (fact["kind"] != ("legacy-input" if known else "unobserved") or fact["observedAt"] is not None
                    or fact["valueSha256"] != digest(article["sourceMetadata"][field])):
                fail("metadata evidence differs from frozen-facts policy")
            if not known and article["sourceMetadata"][field] != ([] if field == "tags" else None):
                fail("unobserved source value is not unknown")
        if fields != sorted(article["sourceMetadata"]) or len(set(fields)) != len(fields):
            fail("metadata evidence is duplicated or unsorted")
    if seen != sorted(indexed) or len(set(seen)) != len(seen):
        fail("origins are duplicated, missing or unsorted")
    return value
