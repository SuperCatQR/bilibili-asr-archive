"""Offline, evidence-bound import of existing prose without new inference."""
from __future__ import annotations

from contextlib import ExitStack, closing
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
import time

from bili_asr.canonical_json import canonical, digest
from bili_asr.manuscript_files import read_artifact, stage_artifact
from bili_asr.publication import get_ai_artifacts, get_edition, verify_release
from bili_asr.publication_content import content_from_ai, normalize_actor
from bili_asr.publication_content_v2 import normalize_content_v2
from bili_asr.source_identity import source_url
from bili_asr.storage.archive_contracts import _resource, frozen_version, require_universal_contract
from bili_asr.storage.import_origins import (
    EXTENSION, POLICY, body_digest, import_origin, read_baseline, require_import_extension, frozen_legacy_source,
)
from bili_asr.storage.publication import PublicationConflictError, PublicationRepository, read_revision
from bili_asr.storage.sources import SourceRepository

MAX_BATCH = 100
MAX_BASELINE_BYTES = 64 * 1024 * 1024


def install_preserved_body_extension(archive_root: Path) -> dict:
    """Explicit maintenance cutover of a validated DB copy, never access-time DDL.

    Operators use an offline archive copy first. A live writer lease or a SQLite
    journal prevents replacement; this function does not drain production work.
    """
    from bili_asr.archive_maintenance import archive_access
    from bili_asr.export_snapshot import checked_path, _fsync_directory
    from bili_asr.storage.database import connect_database
    from bili_asr.storage.snapshots import validate_snapshot_database

    root = checked_path(archive_root)
    database = root / "archive.db"
    checked_path(database)
    with archive_access(root, exclusive=True, create_root=False):
        with closing(connect_database(database, readonly=True, must_exist=True)) as source:
            require_universal_contract(source)
            if require_import_extension(source):
                return {"extension": EXTENSION, "installed": False}
            validate_snapshot_database(database)
            for suffix in ("-wal", "-shm", "-journal"):
                if Path(str(database) + suffix).exists():
                    raise ValueError("import-install: checkpoint and close SQLite journals before cutover")
            descriptor, name = tempfile.mkstemp(prefix=".import-schema-", suffix=".db", dir=root)
            os.close(descriptor)
            staged = Path(name)
            try:
                with closing(connect_database(staged)) as target:
                    source.backup(target)
                    target.executescript("BEGIN IMMEDIATE;\n" + _resource("schema-preserved-body-import.sql") + "\nCOMMIT;")
                    require_universal_contract(target)
                validate_snapshot_database(staged)
                with staged.open("r+b") as stream:
                    os.fsync(stream.fileno())
            except BaseException:
                staged.unlink(missing_ok=True)
                raise
        try:
            os.replace(staged, database)
            _fsync_directory(root)
        finally:
            staged.unlink(missing_ok=True)
    return {"extension": EXTENSION, "installed": True}


def _selected_baseline(connection, selector: dict, artifact_roots) -> tuple[dict, bytes, bytes]:
    if (not isinstance(selector, dict) or set(selector) != {"kind", "id"}
            or not isinstance(selector["kind"], str) or selector["kind"] not in {"ai-revision", "edition"}):
        raise ValueError("import-selector: explicitly select ai-revision or edition and ID")
    size = 32 if selector["kind"] == "edition" else 64
    if not isinstance(selector["id"], str) or re.fullmatch(rf"[0-9a-f]{{{size}}}", selector["id"]) is None:
        raise ValueError("import-selector: invalid legacy source ID")
    old_edition = get_edition(connection, selector["id"]) if selector["kind"] == "edition" else None
    revision_id = old_edition["revision_id"] if old_edition else selector["id"]
    revision, prepared = read_revision(connection, revision_id)
    if frozen_version(connection, "input", revision["input_id"]) != 1 or (old_edition and old_edition["content_version"] != 1):
        raise ValueError("import-selector: only verified legacy v1 inputs and editions are eligible")
    artifacts = get_ai_artifacts(connection, revision_id, artifact_roots)
    legacy = old_edition["content"] if old_edition else content_from_ai(prepared, artifacts["ai-draft.md"].decode("utf-8"))
    body = legacy["markdown"].encode("utf-8") if old_edition else artifacts["ai-draft.md"]
    part_id = revision["video_part_id"]
    ref = SourceRepository(connection).part(part_id)["content_ref"]
    metadata = prepared["snapshot"]["metadata"]
    if (ref.platform, ref.external_video_id, ref.part_index) != ("bilibili", metadata["bvid"], metadata["page_index"]):
        raise ValueError("import-integrity: legacy source mapping differs from frozen input")
    # v1 inputs attest only title and identity. Missing facts stay unknown; no
    # current observations or editorial title/tags are presented as source facts.
    source_metadata, evidence = frozen_legacy_source(connection, prepared)
    content = normalize_content_v2({
        **legacy, "markdown": body.decode("utf-8"),
        "source": {"platform": ref.platform, "externalVideoId": ref.external_video_id,
                   "partIndex": ref.part_index, "videoPartId": part_id, "url": source_url(ref), "metadata": source_metadata},
        "attribution": "Body preserved from a legacy AI-assisted manuscript; no new AI inference during import.",
        "editorNote": "Imported edition requires human review. The reference is the historical AI baseline.",
    })
    if content["markdown"].encode("utf-8") != body or body.startswith(b"\xef\xbb\xbf"):
        raise ValueError("body_not_canonical: import would alter the selected UTF-8 body")
    release = PublicationRepository(connection).release_for_edition(old_edition["edition_id"]) if old_edition else None
    if release:
        verify_release(connection, release["release_id"], artifact_roots)
    baseline = {
        "policyVersion": POLICY, "selector": selector, "videoPartId": part_id,
        "revisionId": revision_id, "inputId": revision["input_id"],
        "legacyEditionId": old_edition["edition_id"] if old_edition else None,
        "legacyReleaseId": release["release_id"] if release else None,
        "sourceFingerprint": digest({"ref": source_metadata, "videoPartId": part_id}),
        "bodySha256": hashlib.sha256(body).hexdigest(), "reviewSha256": hashlib.sha256(artifacts["review.md"]).hexdigest(),
        "content": content, "metadataEvidence": evidence,
        "legacyAttribution": legacy["attribution"], "legacyEditorNote": legacy["editorNote"],
    }
    return baseline, body, artifacts["review.md"]


def plan_preserved_body_import(connection, *, selectors: list[dict], artifact_roots) -> dict:
    require_universal_contract(connection)
    if not isinstance(selectors, list) or not 1 <= len(selectors) <= MAX_BATCH:
        raise ValueError(f"import-plan: select between 1 and {MAX_BATCH} sources per atomic batch")
    repository = PublicationRepository(connection)
    entries, blocked, skipped, seen = [], [], [], set()
    owned = not connection.in_transaction
    if owned:
        connection.execute("BEGIN")
    try:
        for selector in selectors:
            try:
                baseline, body, review = _selected_baseline(connection, selector, artifact_roots)
                part_id = baseline["videoPartId"]
                if part_id in seen:
                    raise ValueError("import-plan: multiple selected sources for the same part")
                seen.add(part_id)
                head = repository.head(part_id)
                current = get_edition(connection, head["current_edition_id"]) if head else None
                if current and current["content_version"] == 2:
                    skipped.append({"selector": selector, "reason": "existing-v2-edition", "editionId": current["edition_id"]})
                    continue
                entries.append({"importId": digest(baseline), "baseline": baseline,
                    "expectedEditionId": head["current_edition_id"] if head else None,
                    "expectedReleaseId": head["current_release_id"] if head else None,
                    "bodyBytes": len(body), "reviewBytes": len(review),
                    "previousReviewStatus": current["review_status"] if current else None,
                    "discardsCurrentEdits": bool(current and current["content"]["markdown"].encode("utf-8") != body),
                    "unknownMetadataFields": [key for key, value in baseline["metadataEvidence"].items() if value["kind"] == "unobserved"],
                })
            except (ValueError, OSError) as error:
                blocked.append({"selector": selector, "reason": str(error)})
        plan = {"schemaVersion": 1, "policyVersion": POLICY, "entries": entries, "skipped": skipped, "blocked": blocked}
        if sum(entry["bodyBytes"] + entry["reviewBytes"] for entry in entries) > MAX_BASELINE_BYTES:
            blocked.append({"selector": None, "reason": "import-plan: batch exceeds 64 MiB baseline bytes; split the selections"})
        return {**plan, "planDigest": digest(plan)}
    finally:
        if owned:
            connection.rollback()


def _validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or set(plan) != {"schemaVersion", "policyVersion", "entries", "skipped", "blocked", "planDigest"}:
        raise ValueError("import-plan: unknown plan fields")
    semantic = {key: value for key, value in plan.items() if key != "planDigest"}
    if (type(plan["schemaVersion"]) is not int or plan["schemaVersion"] != 1
            or plan["policyVersion"] != POLICY or digest(semantic) != plan["planDigest"]
            or not isinstance(plan["entries"], list) or not 1 <= len(plan["entries"]) <= MAX_BATCH
            or not isinstance(plan["skipped"], list) or not isinstance(plan["blocked"], list) or plan["blocked"]):
        raise ValueError("import-plan: altered, blocked, empty or unsupported plan")
    fields = {"importId", "baseline", "expectedEditionId", "expectedReleaseId", "bodyBytes", "reviewBytes",
              "previousReviewStatus", "discardsCurrentEdits", "unknownMetadataFields"}
    for entry in plan["entries"]:
        if (not isinstance(entry, dict) or set(entry) != fields or not isinstance(entry["baseline"], dict)
                or type(entry["baseline"].get("videoPartId")) is not int or digest(entry["baseline"]) != entry["importId"]):
            raise ValueError("import-plan: invalid entry identity or fields")
        if any(type(entry[field]) is not int or entry[field] < 0 for field in ("bodyBytes", "reviewBytes")):
            raise ValueError("import-plan: invalid byte budget")
    if len({entry["baseline"]["videoPartId"] for entry in plan["entries"]}) != len(plan["entries"]):
        raise ValueError("import-plan: duplicate parts")
    if sum(entry["bodyBytes"] + entry["reviewBytes"] for entry in plan["entries"]) > MAX_BASELINE_BYTES:
        raise ValueError("import-plan: baseline byte budget exceeds 64 MiB")
    return semantic


def check_preserved_body_import(connection, *, edition_id: str, artifact_roots) -> dict:
    edition = get_edition(connection, edition_id)
    origin = import_origin(connection, edition_id)
    if origin is None:
        raise ValueError("import-check: edition has no preservation origin")
    stored = read_baseline(connection, origin["import_id"])
    baseline, body, review = _selected_baseline(connection, stored["baseline"]["selector"], artifact_roots)
    if baseline != stored["baseline"]:
        raise ValueError("import-integrity: legacy evidence differs from import baseline")
    if (read_artifact(stored["body_path"], stored["body_sha256"], artifact_roots) != body
            or read_artifact(stored["review_path"], stored["review_sha256"], artifact_roots) != review):
        raise ValueError("import-integrity: baseline files differ from legacy evidence")
    return {"valid": True, "importId": origin["import_id"], "editionId": edition_id,
            "bodyPreserved": origin["relation"] == "preserved", "baselineBodySha256": stored["body_sha256"],
            "currentBodySha256": body_digest(edition["content"]["markdown"]), "reviewArtifactSha256": stored["review_sha256"]}


def _receipt(connection, plan, artifact_roots) -> dict | None:
    row = connection.execute("SELECT * FROM manuscript_import_batches WHERE plan_digest=?", (plan["planDigest"],)).fetchone()
    if row is None:
        return None
    if row["plan_json"] != canonical(plan):
        raise ValueError("import-integrity: receipt plan mismatch")
    result = json.loads(row["result_json"])
    if (not isinstance(result, dict) or set(result) != {"planDigest", "editions", "idempotent"}
            or result["planDigest"] != plan["planDigest"] or result["idempotent"] is not False
            or canonical(result) != row["result_json"] or len(result["editions"]) != len(plan["entries"])):
        raise ValueError("import-integrity: invalid batch receipt")
    for entry, imported in zip(plan["entries"], result["editions"], strict=True):
        checked = check_preserved_body_import(connection, edition_id=imported["editionId"], artifact_roots=artifact_roots)
        edition = get_edition(connection, imported["editionId"])
        origin = import_origin(connection, imported["editionId"])
        if (set(imported) != {"importId", "editionId", "contentSha256"}
                or checked["importId"] != entry["importId"] or imported["importId"] != entry["importId"]
                or edition["content_sha256"] != imported["contentSha256"]
                or origin["root_edition_id"] != imported["editionId"]):
            raise ValueError("import-integrity: receipt edition mismatch")
    return {**result, "idempotent": True}


def apply_preserved_body_import(connection, *, plan: dict, artifact_roots, write_root: Path, actor: str) -> dict:
    _validate_plan(plan)
    actor = normalize_actor(actor)
    require_universal_contract(connection)
    require_import_extension(connection, required=True)
    artifact_roots = tuple(Path(path) for path in artifact_roots)
    repository = PublicationRepository(connection)
    from bili_asr.services.import_staging import import_staging
    with import_staging(Path(write_root)) as temporary_root, ExitStack() as staging:
        receipt = _receipt(connection, plan, artifact_roots)
        if receipt:
            return receipt
        prepared = []
        for entry in plan["entries"]:
            baseline, body, review = _selected_baseline(connection, entry["baseline"]["selector"], artifact_roots)
            if baseline != entry["baseline"] or digest(baseline) != entry["importId"]:
                raise ValueError("import-plan: selected legacy evidence changed")
            if len(body) != entry["bodyBytes"] or len(review) != entry["reviewBytes"]:
                raise ValueError("import-plan: declared byte budget differs from baseline files")
            import_id = entry["importId"]
            body_path, review_path = (f"documents/imports/{import_id}/{name}" for name in ("body.md", "review.md"))
            staged = [staging.enter_context(stage_artifact(Path(write_root), path, data, temporary_root=temporary_root))
                      for path, data in ((body_path, body), (review_path, review))]
            prepared.append((entry, staged, body_path, review_path))
        with repository.transaction():
            # A concurrent successful identical batch wins without moving heads.
            receipt = _receipt(connection, plan, (*artifact_roots, Path(write_root)))
            if receipt:
                return receipt
            for entry, _, _, _ in prepared:
                baseline = entry["baseline"]
                revision, _ = read_revision(connection, baseline["revisionId"])
                if revision["input_id"] != baseline["inputId"] or revision["video_part_id"] != baseline["videoPartId"]:
                    raise ValueError("import-plan: legacy source identity changed")
                head = repository.head(baseline["videoPartId"])
                current = head["current_edition_id"] if head else None
                released = head["current_release_id"] if head else None
                if current != entry["expectedEditionId"] or released != entry["expectedReleaseId"]:
                    raise PublicationConflictError("import-conflict: draft or release head changed; create a new plan")
            results = []
            for entry, staged, body_path, review_path in prepared:
                for artifact in staged:
                    artifact.install()
                baseline = entry["baseline"]
                existing = connection.execute("SELECT 1 FROM manuscript_import_baselines WHERE import_id=?", (entry["importId"],)).fetchone()
                if existing:
                    if read_baseline(connection, entry["importId"])["baseline"] != baseline:
                        raise ValueError("import-integrity: existing baseline mismatch")
                else:
                    connection.execute("INSERT INTO manuscript_import_baselines VALUES (?,?,?,?,?,?,?,?,?,?)", (
                        entry["importId"], baseline["videoPartId"], baseline["revisionId"], baseline["legacyEditionId"],
                        canonical(baseline), body_path, baseline["bodySha256"], review_path, baseline["reviewSha256"], int(time.time())))
                edition = repository.insert_edition(part_id=baseline["videoPartId"], revision_id=baseline["revisionId"],
                    content=baseline["content"], parent_edition_id=entry["expectedEditionId"], actor=actor,
                    note=f"Preserved body import {entry['importId']}", event_type="created", content_version=2)
                connection.execute("INSERT INTO publication_import_origins VALUES (?,?,?,?,?)", (
                    edition["edition_id"], entry["importId"], edition["edition_id"], "preserved", baseline["bodySha256"]))
                get_edition(connection, edition["edition_id"])
                results.append({"importId": entry["importId"], "editionId": edition["edition_id"], "contentSha256": edition["content_sha256"]})
            result = {"planDigest": plan["planDigest"], "editions": results, "idempotent": False}
            connection.execute("INSERT INTO manuscript_import_batches VALUES (?,?,?,?,?)", (
                plan["planDigest"], canonical(plan), canonical(result), actor, int(time.time())))
        return result
