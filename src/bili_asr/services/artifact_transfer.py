"""Manual, maintenance-window audio offload with durable per-copy release intents."""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

from bili_asr.archive_maintenance import archive_access
from bili_asr.archive_session import ArchiveAccessMode, open_archive_connection
from bili_asr.artifact_inventory import portable_artifact_parts
from bili_asr.artifact_packages import (
    PackageSource,
    capture_source_generation,
    check_artifact_package,
    create_artifact_package,
    copy_package_object,
    package_batches,
    package_manifest,
)
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.services.artifact_inventory_service import (
    ArtifactSelection,
    inventory_artifacts,
    validate_offload_plan,
)
from bili_asr.services.artifact_release import release_copy
from bili_asr.storage.artifact_catalog import ArtifactCatalog
from bili_asr.storage_targets import open_directory_target


def _local_target(roots: ArtifactRoots, root: Path) -> str:
    if root not in roots.read_bases():
        raise ValueError("plan source root is outside this invocation's artifact scope")
    return "local" if root == roots.archive_root else "local-artifacts"


def _selection(plan: dict) -> ArtifactSelection:
    return ArtifactSelection(**{key: tuple(value) for key, value in plan["selection"].items()})


def _inventory(roots, plan, external_holds):
    holds = external_holds() if callable(external_holds) else external_holds
    return inventory_artifacts(roots.archive_root / "archive.db", roots, deep=True,
                              selection=_selection(plan), external_holds=holds)


def _revalidate(roots, plan, external_holds, items) -> dict:
    current = _inventory(roots, plan, external_holds)
    copies = {copy["copy_id"]: copy for copy in current["copies"]}
    for item in items:
        copy = copies.get(item["copy_id"])
        if copy is None or not copy["candidate"] or any(copy[key] != item[key] for key in ("sha256", "size", "fingerprint")):
            raise ValueError(f"plan source changed or acquired a retention guard: {item['copy_id']}")
    return current


def _local_replica(catalog, roots, item):
    target_id = _local_target(roots, Path(item["root"]))
    catalog.register_target(target_id, kind="local")
    row = catalog.connection.execute(
        "SELECT replica_id,object_id,generation,presence FROM artifact_replicas WHERE target_id=? AND relative_key=? AND member_key='' ORDER BY generation DESC LIMIT 1",
        (target_id, item["path"]),
    ).fetchone()
    generation = row[2] if row and row[1] == item["sha256"] and row[3] == "present" else (row[2] + 1 if row else 1)
    return catalog.record_verified_replica(item["sha256"], target_id, item["path"], sha256=item["sha256"],
                                           byte_size=item["size"], generation=generation)


def _register_package(catalog, target, checked, operation_id, roots, items):
    members = {entry["object_id"]: entry for entry in checked["objects"]}
    with catalog.connection:
        catalog.record_package(checked["package_id"], target.target_id, checked["package_key"],
                               sha256=checked["package_sha256"], byte_size=checked["package_size_bytes"],
                               manifest_sha256=checked["manifest_sha256"])
        for item in items:
            identity = catalog.register_object(item["sha256"], item["size"])
            for audio_id, in catalog.connection.execute("SELECT audio_id FROM audio_objects WHERE sha256=? AND byte_size=?", (identity, item["size"])):
                catalog.bind_audio(audio_id, identity)
            source_id = _local_replica(catalog, roots, item)
            entry = members[identity]
            replica_id = catalog.record_verified_replica(identity, target.target_id, checked["package_key"],
                                                         sha256=identity, byte_size=item["size"],
                                                         package_id=checked["package_id"], member_key=entry["member"])
            catalog.record_transfer_item(operation_id, identity, state="verified", source_replica_id=source_id, target_replica_id=replica_id)
        catalog.set_transfer_state(operation_id, "verified")


def _package_evidence(catalog, target, operation_id):
    rows = list(catalog.connection.execute(
        "SELECT DISTINCT p.* FROM artifact_transfer_items i JOIN artifact_replicas r ON r.replica_id=i.target_replica_id "
        "JOIN artifact_packages p ON p.package_id=r.package_id AND p.target_id=r.target_id AND p.relative_key=r.relative_key "
        "WHERE i.transfer_id=?", (operation_id,)))
    identities = set()
    for row in rows:
        if row["target_id"] != target.target_id:
            raise ValueError("operation belongs to another target")
        target.check()
        checked = check_artifact_package(target.root / row["relative_key"], expected_sha256=row["sha256"])
        if checked["package_id"] != row["package_id"] or checked["manifest_sha256"] != row["manifest_sha256"]:
            raise ValueError("catalog and package manifest identity differ")
        identities.update(entry["object_id"] for entry in checked["objects"])
    return identities


def _result(connection, operation_id, *, released_bytes=0):
    operation = dict(connection.execute("SELECT * FROM artifact_transfers WHERE transfer_id=?", (operation_id,)).fetchone())
    counts = dict(connection.execute("SELECT state,COUNT(*) FROM artifact_transfer_items WHERE transfer_id=? GROUP BY state", (operation_id,)))
    packages = list(connection.execute(
        "SELECT DISTINCT p.relative_key,p.byte_size FROM artifact_transfer_items i JOIN artifact_replicas r ON r.replica_id=i.target_replica_id "
        "JOIN artifact_packages p ON p.package_id=r.package_id AND p.target_id=r.target_id AND p.relative_key=r.relative_key "
        "WHERE i.transfer_id=?", (operation_id,)))
    return {"operation": operation, "items_by_state": counts, "packages": [dict(row) for row in packages],
            "verified_payload_bytes": connection.execute(
                "SELECT COALESCE(SUM(o.byte_size),0) FROM artifact_transfer_items i JOIN artifact_objects o USING(object_id) WHERE i.transfer_id=? AND i.target_replica_id IS NOT NULL", (operation_id,)).fetchone()[0],
            "released_bytes_this_run": released_bytes,
            "released_copies": connection.execute("SELECT COUNT(*) FROM artifact_release_intents WHERE transfer_id=? AND state='released'", (operation_id,)).fetchone()[0]}


def _live_hold(connection, obj, external_holds):
    holds = external_holds() if callable(external_holds) else external_holds
    if holds is None:
        return True
    parts = {ref["part_id"] for ref in obj["references"] if ref["part_id"] is not None}
    keys = {obj["object_id"], *(f"part:{part}" for part in parts),
            *(f"path:{ref['path']}" for ref in obj["references"])}
    for part in parts:
        keys.update(row[0] for row in connection.execute("SELECT job_id FROM workflow_jobs WHERE video_part_id=? UNION SELECT d.job_id FROM workflow_job_dependencies d JOIN workflow_jobs j ON j.job_id=d.prerequisite_job_id WHERE j.video_part_id=?", (part, part)))
    return any(holds.get(key) for key in keys)


def _recheck_target_object(catalog, target, operation_id, identity):
    class Discard:
        def write(self, block):
            return len(block)
    row = catalog.connection.execute(
        "SELECT r.*,p.manifest_sha256 FROM artifact_transfer_items i JOIN artifact_replicas r ON r.replica_id=i.target_replica_id "
        "JOIN artifact_packages p ON p.package_id=r.package_id AND p.target_id=r.target_id AND p.relative_key=r.relative_key "
        "WHERE i.transfer_id=? AND i.object_id=?", (operation_id, identity)).fetchone()
    if row is None or row["target_id"] != target.target_id:
        raise ValueError("release requires a current verified external object")
    target.check()
    copy_package_object(target.root / row["relative_key"], identity, Discard(),
                        expected_size=row["verified_byte_size"], package_id=row["package_id"],
                        manifest_sha256=row["manifest_sha256"])
    target.check()


def _release_intents(catalog, roots, target, plan, operation_id, external_holds, *, current_inventory=None):
    identities = _package_evidence(catalog, target, operation_id)
    current = current_inventory if current_inventory is not None else _inventory(roots, plan, external_holds)
    retention = {obj["sha256"]: obj["retention_reasons"] for obj in current["objects"] if obj["sha256"]}
    object_facts = {obj["sha256"]: obj for obj in current["objects"] if obj["sha256"]}
    copies = {copy["copy_id"]: copy for copy in current["copies"]}
    planned = {item["copy_id"]: item for item in plan["items"]}
    released_bytes = 0
    for intent in list(catalog.connection.execute("SELECT * FROM artifact_release_intents WHERE transfer_id=? ORDER BY copy_id", (operation_id,))):
        if intent["state"] == "released":
            continue
        item = planned.get(intent["copy_id"])
        if item is None or intent["object_id"] != item["sha256"] or intent["source_key"] != item["path"] or intent["quarantine_key"] != f"audio/.artifact-release-{operation_id}-{intent['copy_id']}":
            raise ValueError("release intent differs from frozen plan")
        root = Path(item["root"])
        if _local_target(roots, root) != intent["source_target_id"] or intent["object_id"] not in identities:
            raise ValueError("release intent lacks verified target evidence")
        copy = copies.get(intent["copy_id"])
        held = (external_holds is None or intent["object_id"] not in retention
                or bool(retention.get(intent["object_id"])) or catalog.pinned(intent["object_id"]))
        if copy and copy["state"] not in {"missing", "verified"}:
            held = True
        if copy and copy["state"] == "verified" and copy["sha256"] != intent["object_id"]:
            raise ValueError("release source was replaced; preserve source and quarantine for inspection")
        target.check()

        def isolated(copy_id=intent["copy_id"]):
            with catalog.connection:
                catalog.connection.execute("UPDATE artifact_release_intents SET state='isolated',updated_at=? WHERE transfer_id=? AND copy_id=?", (int(time.time()), operation_id, copy_id))

        def before_delete(identity=intent["object_id"]):
            _recheck_target_object(catalog, target, operation_id, identity)
            if catalog.pinned(identity) or _live_hold(catalog.connection, object_facts[identity], external_holds):
                raise ValueError("release acquired a retention guard after isolation")

        outcome = release_copy(root, intent["source_key"], intent["quarantine_key"], intent["object_id"],
                               json.loads(intent["source_generation_json"]), allow_delete=not held,
                               isolated=isolated, before_delete=before_delete)
        released_bytes += outcome["released_bytes"]
        with catalog.connection:
            catalog.connection.execute("UPDATE artifact_release_intents SET state=?,updated_at=? WHERE transfer_id=? AND copy_id=?",
                                       (outcome["state"], int(time.time()), operation_id, intent["copy_id"]))
            if outcome["state"] == "released":
                catalog.observe_replica(intent["source_replica_id"], presence="released")
    with catalog.connection:
        for identity, in catalog.connection.execute("SELECT object_id FROM artifact_transfer_items WHERE transfer_id=?", (operation_id,)):
            pending = catalog.connection.execute("SELECT 1 FROM artifact_release_intents WHERE transfer_id=? AND object_id=? AND state!='released'", (operation_id, identity)).fetchone()
            if pending is None:
                catalog.connection.execute("UPDATE artifact_transfer_items SET state='released',updated_at=? WHERE transfer_id=? AND object_id=?", (int(time.time()), operation_id, identity))
        cancelled = catalog.connection.execute("SELECT 1 FROM artifact_release_intents WHERE transfer_id=? AND state='cancelled'", (operation_id,)).fetchone()
        catalog.set_transfer_state(operation_id, "failed" if cancelled else "complete", error_code="retention_guard" if cancelled else None)
    return _result(catalog.connection, operation_id, released_bytes=released_bytes)


def transfer_artifacts(roots: ArtifactRoots, plan: dict, *, target_root: Path, mode: str = "copy",
                       external_holds=None, max_bytes: int = 1024**3, max_objects: int = 1000) -> dict:
    """Execute a frozen audio plan with exclusive archive access and bounded batches."""
    validate_offload_plan(plan)
    if mode not in {"copy", "offload"}:
        raise ValueError("transfer mode must be copy or offload")
    for item in plan["items"]:
        _local_target(roots, Path(item["root"]))
        parts = portable_artifact_parts(item["path"])
        if len(parts) != 2 or parts[0] != "audio":
            raise ValueError("manual transfer currently requires an audio-only plan")
    if not plan["items"]:
        raise ValueError("plan contains no eligible audio copies")
    target = open_directory_target(target_root, plan["target_id"], roots=roots)
    operation_id = f"{mode}-{plan['plan_sha256']}"
    with archive_access(roots.archive_root, exclusive=True, create_root=False):
        connection = open_archive_connection(roots.archive_root, mode=ArchiveAccessMode.WRITE, artifact_roots=roots)
        try:
            catalog = ArtifactCatalog(connection)
            existing = connection.execute("SELECT state FROM artifact_transfers WHERE transfer_id=?", (operation_id,)).fetchone()
            if existing and existing[0] == "complete":
                _package_evidence(catalog, target, operation_id)
                return _result(connection, operation_id)
            if connection.execute("SELECT 1 FROM artifact_release_intents WHERE transfer_id=?", (operation_id,)).fetchone():
                return _release_intents(catalog, roots, target, plan, operation_id, external_holds)
            _revalidate(roots, plan, external_holds, plan["items"])
            if mode == "offload" and any(catalog.pinned(item["sha256"]) for item in plan["items"]):
                raise ValueError("selected audio is pinned")
            sources = {}
            for item in plan["items"]:
                path = Path(item["root"]) / item["path"]
                sources.setdefault(item["sha256"], PackageSource(item["sha256"], path, item["path"], item["sha256"], item["size"], capture_source_generation(path)))
            batches = package_batches(sources.values(), max_bytes=max_bytes, max_objects=max_objects)
            missing_batches = [batch for index, batch in enumerate(batches) if not (
                target.root / "packages" / f"artifact-{package_manifest(batch, operation_id, plan['plan_sha256'], index)['package_id']}.zip"
            ).exists()]
            missing_objects = [source for batch in missing_batches for source in batch]
            needed = sum(source.size_bytes for source in missing_objects) + max(64 * 1024**2, len(missing_objects) * 4096)
            if missing_batches and shutil.disk_usage(target.root).free < needed:
                raise ValueError("storage target lacks space for payload and package overhead")
            with connection:
                catalog.register_target(target.target_id)
                catalog.begin_transfer(operation_id, kind=mode, plan_sha256=plan["plan_sha256"], target_id=target.target_id)
                catalog.set_transfer_state(operation_id, "copying")
            try:
                for index, batch in enumerate(batches):
                    target.check()
                    checked = create_artifact_package(target.root, batch, operation_id=operation_id,
                                                      plan_sha256=plan["plan_sha256"], batch_index=index)
                    selected = [item for item in plan["items"] if item["sha256"] in {source.object_id for source in batch}]
                    _register_package(catalog, target, checked, operation_id, roots, selected)
                if mode == "copy":
                    with connection:
                        catalog.set_transfer_state(operation_id, "complete")
                    return _result(connection, operation_id)
                # The expensive target copy/verification precedes this second live
                # inventory. Persist all intents before any source is isolated.
                current = _revalidate(roots, plan, external_holds, plan["items"])
                with connection:
                    for item in plan["items"]:
                        source_id = _local_replica(catalog, roots, item)
                        now = int(time.time())
                        connection.execute("INSERT INTO artifact_release_intents VALUES (?,?,?,?,?,?,?,?, 'planned',?,?)",
                                           (operation_id, item["copy_id"], item["sha256"], _local_target(roots, Path(item["root"])),
                                            item["path"], f"audio/.artifact-release-{operation_id}-{item['copy_id']}", source_id,
                                            json.dumps(capture_source_generation(Path(item["root"]) / item["path"]), sort_keys=True), now, now))
                    catalog.set_transfer_state(operation_id, "releasing")
                return _release_intents(catalog, roots, target, plan, operation_id, external_holds, current_inventory=current)
            except (ValueError, OSError, sqlite3.Error):
                with connection:
                    catalog.set_transfer_state(operation_id, "failed", error_code="transfer_interrupted")
                raise
        finally:
            connection.close()


def reconcile_artifact_transfer(roots: ArtifactRoots, plan: dict, *, target_root: Path, external_holds=None) -> dict:
    """Resume a journaled offload without interpreting an old plan as permission."""
    validate_offload_plan(plan)
    target = open_directory_target(target_root, plan["target_id"], roots=roots)
    operation_id = f"offload-{plan['plan_sha256']}"
    with archive_access(roots.archive_root, exclusive=True, create_root=False):
        connection = open_archive_connection(roots.archive_root, mode=ArchiveAccessMode.WRITE, artifact_roots=roots)
        try:
            catalog = ArtifactCatalog(connection)
            if not connection.execute("SELECT 1 FROM artifact_release_intents WHERE transfer_id=?", (operation_id,)).fetchone():
                raise ValueError("no persisted release intents; resume transfer with the same plan instead")
            return _release_intents(catalog, roots, target, plan, operation_id, external_holds)
        finally:
            connection.close()
