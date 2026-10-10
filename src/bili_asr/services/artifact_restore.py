"""Restore retained audio byte identity without changing production facts."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from bili_asr.archive_maintenance import archive_access
from bili_asr.archive_session import ArchiveAccessMode, open_archive_connection
from bili_asr.artifact_inventory import portable_artifact_parts, stream_hash
from bili_asr.artifact_packages import (
    ArtifactPackageError,
    capture_source_generation,
    read_package_manifest,
    restore_package_object,
)
from bili_asr.artifact_root import ArtifactRoots
from bili_asr.path_policy import (
    AUDIO_EXTENSIONS,
    confined_audio_file,
    confined_audio_path,
)
from bili_asr.storage.artifact_catalog import ArtifactCatalog, storage_key_parts
from bili_asr.storage_targets import open_directory_target


class ArtifactRestoreError(ValueError):
    """A retained object cannot safely be made available as a local input."""


def _audio_key(storage_key: str) -> tuple[str, ...]:
    parts = portable_artifact_parts(storage_key)
    if len(parts) != 2 or parts[0] != "audio" or Path(parts[1]).suffix.lower() not in AUDIO_EXTENSIONS:
        raise ArtifactRestoreError("the first restore contract supports only retained audio paths")
    return parts


def _retained_audio(connection: sqlite3.Connection, storage_key: str, object_id: str, size: int) -> None:
    rows = connection.execute("SELECT sha256,byte_size FROM audio_objects WHERE storage_key=?", (storage_key,)).fetchall()
    if not rows or not any(tuple(row) == (object_id, size) for row in rows):
        raise ArtifactRestoreError("restore path is not a retained audio reference to this object")
    if any(tuple(row) != (object_id, size) for row in rows):
        raise ArtifactRestoreError("retained audio path also identifies different bytes")


def _local_bytes(roots: ArtifactRoots, storage_key: str, object_id: str, size: int) -> bool:
    candidate = roots.write_base.joinpath(*_audio_key(storage_key))
    if not candidate.exists() and not candidate.is_symlink():
        return False
    if confined_audio_path(roots.write_base, storage_key, require_exists=True) is None:
        raise ArtifactRestoreError("local restore path is not a confined regular audio file")
    before = capture_source_generation(candidate)
    with confined_audio_file(roots.write_base, storage_key) as safe_path, open(safe_path, "rb") as source:
        actual = stream_hash(source)
    if before != capture_source_generation(candidate):
        raise ArtifactRestoreError("local audio changed during restore verification")
    if actual != (size, object_id):
        raise ArtifactRestoreError("local restore destination contains different bytes")
    return True


def _register_local(catalog: ArtifactCatalog, roots: ArtifactRoots, object_id: str,
                    storage_key: str, size: int, *, reused: bool) -> int:
    target_id = "local-artifacts" if roots.configured else "local"
    catalog.register_target(target_id, kind="local")
    current = catalog.connection.execute(
        "SELECT generation,object_id,presence FROM artifact_replicas "
        "WHERE target_id=? AND relative_key=? AND member_key='' ORDER BY generation DESC LIMIT 1",
        (target_id, storage_key),
    ).fetchone()
    same_observed_copy = current is not None and reused and current[1] == object_id and current[2] == "present"
    generation = 1 if current is None else current[0] + (not same_observed_copy)
    return catalog.record_verified_replica(object_id, target_id, storage_key, sha256=object_id,
                                            byte_size=size, generation=generation)


def restore_artifact(roots: ArtifactRoots, object_id: str, *, target_id: str,
                     target_root: Path, storage_key: str) -> dict:
    """Verify one packaged member and install it under the selected write base.

    Archive maintenance excludes supported production writers. Large reads run
    outside SQLite transactions; only operation and replica facts are committed.
    A container's historical verification is retained separately from this
    selected member's current hash verification.
    """
    _audio_key(storage_key)
    target = open_directory_target(target_root, target_id, roots=roots)
    with archive_access(roots.archive_root, exclusive=True, create_root=False), closing(
        open_archive_connection(roots.archive_root, mode=ArchiveAccessMode.WRITE, artifact_roots=roots)
    ) as connection:
        catalog = ArtifactCatalog(connection)
        obj = catalog.object(object_id)
        size = obj["byte_size"]
        _retained_audio(connection, storage_key, object_id, size)
        if not roots.write_base.is_dir():
            raise ArtifactRestoreError("configured local artifact root must already exist")
        # This guard creates only audio/ within an existing validated write base.
        destination = confined_audio_path(roots.write_base, storage_key, require_exists=False)
        if destination is None:
            raise ArtifactRestoreError("local restore destination is unsafe")
        operation_id = "restore-" + uuid.uuid4().hex
        plan = {"version": 1, "object_id": object_id, "byte_size": size,
                "target_id": target_id, "storage_key": storage_key}
        plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with connection:
            catalog.register_target(target_id, kind="directory")
            catalog.begin_transfer(operation_id, kind="restore", plan_sha256=plan_hash, target_id=target_id)
            catalog.record_transfer_item(operation_id, object_id, state="planned")
            catalog.set_transfer_state(operation_id, "copying")
        failures: list[dict] = []
        source_replica_id = None
        try:
            target.check()
            reused = _local_bytes(roots, storage_key, object_id, size)
            if not reused:
                if shutil.disk_usage(destination.parent).free < size:
                    raise ArtifactRestoreError("insufficient local free space for the restored object")
                replicas = [replica for replica in catalog.replicas_for_object(object_id)
                            if replica["target_id"] == target_id and replica["package_id"] is not None
                            and replica["presence"] != "released"]
                for replica in replicas:
                    target.check()
                    package_path = target.root.joinpath(*storage_key_parts(replica["relative_key"]))
                    try:
                        manifest = read_package_manifest(package_path)
                        if (manifest["package_id"] != replica["package_id"]
                                or manifest["manifest_sha256"] != replica["manifest_sha256"]
                                or package_path.stat().st_size != replica["package_byte_size"]):
                            raise ArtifactPackageError("package differs from retained container verification")
                        entry = next((entry for entry in manifest["objects"] if entry["object_id"] == object_id), None)
                        if entry is None or entry["member"] != replica["member_key"]:
                            raise ArtifactPackageError("package member differs from retained replica")
                        restored = restore_package_object(package_path, object_id, destination,
                                                          expected_sha256=object_id, expected_size=size)
                        if restored["installed"] and (restored["package_id"] != replica["package_id"]
                                                      or restored["manifest_sha256"] != replica["manifest_sha256"]):
                            raise ArtifactPackageError("source package changed during restoration")
                        source_replica_id = replica["replica_id"] if restored["installed"] else None
                        break
                    except (ArtifactPackageError, OSError) as exc:
                        target.check()
                        failures.append({"replica_id": replica["replica_id"], "error": str(exc)})
                        with connection:
                            catalog.observe_replica(replica["replica_id"], presence="unknown" if package_path.exists() else "missing")
                else:
                    raise ArtifactRestoreError("no accessible valid package replica contains the retained audio object")
            target.check()
            # Hash again after installation, before catalog registration. This
            # also makes installation-before-commit crashes safely repeatable.
            if not _local_bytes(roots, storage_key, object_id, size):
                raise ArtifactRestoreError("restored object disappeared before local registration")
            _retained_audio(connection, storage_key, object_id, size)
            with connection:
                local_replica = _register_local(catalog, roots, object_id, storage_key, size, reused=reused)
                if source_replica_id is not None:
                    catalog.observe_replica(source_replica_id, presence="present")
                catalog.record_transfer_item(operation_id, object_id, state="restored",
                                             source_replica_id=source_replica_id, target_replica_id=local_replica)
                catalog.set_transfer_state(operation_id, "complete")
        except (ValueError, OSError, sqlite3.Error) as exc:
            with connection:
                catalog.record_transfer_item(operation_id, object_id, state="failed", error_code="restore_unavailable")
                catalog.set_transfer_state(operation_id, "failed", error_code="restore_unavailable")
            raise ArtifactRestoreError(str(exc)) from exc
        return {"operation": "artifact-restore", "operation_id": operation_id, "object_id": object_id,
                "storage_key": storage_key, "restored_path": str(destination), "restored_bytes": 0 if reused else size,
                "verified_bytes": size, "local_replica_id": local_replica, "reused_local": reused,
                "container_reverified": False, "verification": "current-object-sha256",
                "failed_replicas": failures}


__all__ = ["ArtifactRestoreError", "restore_artifact"]
