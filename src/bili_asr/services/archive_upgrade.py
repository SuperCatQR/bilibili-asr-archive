"""Plan, convert and verify registered upgrades without executing business work.

Plans bind exact source bytes, converter code, policies and the target location.
Every stage stays private until all original rows and artifacts are verified.
The receipt proves the installation baseline; subsequent business writes require
a new snapshot, never reuse of an obsolete completion receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from contextlib import ExitStack, closing
from dataclasses import asdict
from importlib import resources
from pathlib import Path

from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.artifact_inventory import (
    portable_artifact_parts,
    require_no_links,
    require_regular_file,
    stream_hash,
)
from bili_asr.canonical_json import canonical, digest
from bili_asr.contracts.registry import upgrade_path
from bili_asr.services.archive_migration import (
    _empty_target,
    _sync_directory,
    migrate_archive,
)
from bili_asr.services.migration_preflight import (
    _database_state,
    _hash_file,
    _inventory_paths,
    _root_entries,
    _verify_markers,
)
from bili_asr.storage.snapshots import required_artifacts, validate_snapshot_database
from bili_asr.storage.upgrade_evidence import (
    readonly,
    source_evidence,
    verify_preserved_tables,
)


def _absolute(path: Path) -> Path:
    lexical = Path(path) if Path(path).is_absolute() else Path.cwd() / path
    require_no_links(lexical)
    return Path(os.path.abspath(lexical))


def _build_digest() -> str:
    """Bind every installed domain dependency, including SQL and frozen schemas."""
    entries = []

    def visit(root, prefix=""):
        for child in sorted(root.iterdir(), key=lambda value: value.name):
            name = prefix + child.name
            if child.is_dir() and child.name != "__pycache__":
                visit(child, name + "/")
            elif child.is_file() and Path(name).suffix in {".py", ".sql", ".json"}:
                entries.append((name, hashlib.sha256(child.read_bytes()).hexdigest()))

    visit(resources.files("bili_asr"))
    return digest(entries)


def _inventory(source: Path, product: Path) -> dict:
    database = source / "archive.db"
    before = _database_state(database)
    evidence = source_evidence(database)
    size, sha256, _ = _hash_file(database)
    bases = tuple(dict.fromkeys((product, source)))
    excluded = [entry for base in bases for entry in _root_entries(base, source, product)]
    paths = _inventory_paths(bases)
    files, selected, physical, shadowed = [], {}, {}, []
    for relative, path, base in paths:
        file_size, file_sha, _ = _hash_file(path)
        item = {"path": relative, "base": str(base), "size": file_size, "sha256": file_sha}
        if relative in selected:
            shadowed.append(item)
        else:
            files.append(item)
            selected[relative], physical[relative] = item, path
    for relative, expected in required_artifacts(database).items():
        portable_artifact_parts(relative)
        if relative not in selected:
            raise ValueError("upgrade source artifact missing: " + relative)
        if expected is not None and selected[relative]["sha256"] != expected:
            raise ValueError("upgrade source artifact hash mismatch: " + relative)
    _verify_markers(selected, physical)
    if _database_state(database) != before or _inventory_paths(bases) != paths:
        raise ValueError("upgrade source changed during inventory")
    result = {"archive_root": str(source), "artifact_root": str(product),
              "database": {"size": size, "sha256": sha256}, **evidence,
              "files": files, "shadowed": shadowed, "excluded": excluded}
    result["fingerprint"] = digest(result)
    return result


def _control_handoff(paths: tuple[Path, ...], source: Path, *, declared_none: bool) -> dict:
    """Bind external operational evidence, without placing it in public artifacts.

    Unknown operator formats remain an explicit continuation blocker. They never
    become an empty retry policy merely because the database upgrade succeeded.
    """
    if declared_none and paths:
        raise ValueError("cannot declare no external control state and supply control files")
    records = []
    with closing(readonly(source / "archive.db")) as connection:
        for path in paths:
            absolute = _absolute(path)
            size, sha256, _ = _hash_file(absolute)
            if size > 16 * 1024 * 1024:
                raise ValueError("external control state exceeds the supported inspection limit")
            state = json.loads(absolute.read_bytes())
            if not isinstance(state, dict) or not isinstance(state.get("retry_holds"), dict):
                raise ValueError("unknown external control state; retry_holds mapping required")
            holds = []
            for job_id, hold in sorted(state["retry_holds"].items()):
                if not isinstance(hold, dict) or connection.execute(
                    "SELECT 1 FROM workflow_jobs WHERE job_id=?", (job_id,)
                ).fetchone() is None:
                    raise ValueError("external retry hold cannot be bound to a source job")
                holds.append(job_id)
            if _hash_file(absolute)[:2] != (size, sha256):
                raise ValueError("external control state changed during inspection")
            records.append({"path": str(absolute), "size": size, "sha256": sha256,
                            "held_job_ids": holds, "mapping": "identity"})
    return {"declaration": "none" if declared_none else "external" if paths else "unknown",
            "records": records, "continuation_allowed": declared_none,
            "handoff_required": not declared_none}


def plan_upgrade(source_root: Path, target_root: Path, *, target_contracts: tuple[str, ...],
                 artifact_root: Path | None = None, selected_path: tuple[str, ...] | None = None,
                 control_state: tuple[Path, ...] = (), no_external_control_state: bool = False) -> dict:
    source, target = _absolute(source_root), _absolute(target_root)
    product = source if artifact_root is None else _absolute(artifact_root)
    if any(target == base or target.is_relative_to(base) or base.is_relative_to(target) for base in (source, product)):
        raise ValueError("upgrade source, artifacts and target must be disjoint")
    if product != source and source.is_relative_to(product):
        raise ValueError("artifact root cannot contain source archive")
    with ArchiveSession(source, mode=ArchiveAccessMode.MAINTENANCE).access():
        inventory = _inventory(source, product)
        path = upgrade_path(tuple(inventory["contracts"]), target_contracts, selected=selected_path)
        control = _control_handoff(control_state, source, declared_none=no_external_control_state)
    code = _build_digest()
    file_bytes = sum(item["size"] for item in inventory["files"])
    plan = {"operation": "archive-upgrade-plan", "format_version": 1, "source": inventory,
            "target_root": str(target), "target_contracts": list(target_contracts),
            "path": [{**asdict(edge), "build_sha256": code} for edge in path],
            "control_state": control,
            "actions": {"preserve_tables": [item["name"] for item in inventory["tables"]],
                        "preserve_files": len(inventory["files"]), "copy_bytes": file_bytes,
                        "new_representations": 0, "expensive_recomputation": [],
                        "review_and_heads": "preserve-exactly", "workflow_recovery": "separate-explicit-operation"},
            "required_free_bytes": file_bytes + inventory["database"]["size"] * 4 + 32 * 1024 * 1024}
    # JSON roundtrip gives one wire representation to both CLI and Python callers.
    plan = json.loads(canonical(plan))
    plan["plan_id"] = digest(plan)
    return plan


def _copy_file(original: Path, destination: Path, expected: dict) -> None:
    require_regular_file(original)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with original.open("rb") as reader, destination.open("xb") as writer:
        size, sha256 = stream_hash(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    if (size, sha256) != (expected["size"], expected["sha256"]):
        raise ValueError("source file changed during upgrade")


def _copy_source(inventory: dict, stage: Path) -> None:
    stage.mkdir()
    _copy_file(Path(inventory["archive_root"]) / "archive.db", stage / "archive.db", inventory["database"])
    for item in inventory["files"]:
        parts = portable_artifact_parts(item["path"])
        _copy_file(Path(item["base"]).joinpath(*parts), stage.joinpath(*parts), item)


def _convert(edge, stage: Path) -> None:
    if edge.converter == "install-preserved-body":
        from bili_asr.services.preserved_body_import import (
            install_preserved_body_extension,
        )
        install_preserved_body_extension(stage)
    elif edge.converter == "install-source-supplement":
        from bili_asr.services.source_supplement import (
            install_source_supplement_extension,
        )
        install_source_supplement_extension(stage)
    else:
        raise ValueError("unsupported upgrade converter")


def _validate_plan(plan: dict) -> None:
    if not isinstance(plan, dict) or plan.get("format_version") != 1 or plan.get("operation") != "archive-upgrade-plan":
        raise ValueError("unsupported upgrade plan")
    if plan.get("plan_id") != digest({key: value for key, value in plan.items() if key != "plan_id"}):
        raise ValueError("upgrade plan digest mismatch")


def apply_upgrade(plan: dict) -> dict:
    _validate_plan(plan)
    source, target = _absolute(Path(plan["source"]["archive_root"])), _absolute(Path(plan["target_root"]))
    with ExitStack() as access:
        for root in sorted((source, target), key=lambda value: os.path.normcase(str(value))):
            access.enter_context(ArchiveSession(root, mode=ArchiveAccessMode.MAINTENANCE).access(allow_missing=root == target))
        current = plan_upgrade(source, target, target_contracts=tuple(plan["target_contracts"]),
            artifact_root=Path(plan["source"]["artifact_root"]),
            selected_path=tuple(edge["identity"] for edge in plan["path"]),
            control_state=tuple(Path(item["path"]) for item in plan["control_state"]["records"]),
            no_external_control_state=plan["control_state"]["declaration"] == "none")
        if current != plan:
            raise ValueError("upgrade source, converter or policy changed; create a new plan")
        if target.exists() and any(target.iterdir()):
            return {**check_upgrade(target, expected_plan_id=plan["plan_id"]), "reused": True}
        _empty_target(target)
        if shutil.disk_usage(target.parent).free < plan["required_free_bytes"]:
            raise ValueError("insufficient space for upgrade staging and verification")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f".{target.name}.upgrade-stage-", dir=target.parent) as temporary:
            stage = Path(temporary) / "archive"
            edges = upgrade_path(tuple(plan["source"]["contracts"]), tuple(plan["target_contracts"]),
                                 selected=tuple(item["identity"] for item in plan["path"]))
            if edges[0].converter == "legacy-migrate":
                migrate_archive(source, stage, artifact_root=Path(plan["source"]["artifact_root"]))
                remaining = edges[1:]
            else:
                _copy_source(plan["source"], stage)
                remaining = edges
            verify_preserved_tables(stage / "archive.db", plan["source"]["tables"])
            for edge in remaining:
                if source_evidence(stage / "archive.db")["contracts"] != list(edge.source):
                    raise ValueError("intermediate source contract does not match registered edge")
                _convert(edge, stage)
                if source_evidence(stage / "archive.db")["contracts"] != list(edge.target):
                    raise ValueError("intermediate target contract does not match registered edge")
                verify_preserved_tables(stage / "archive.db", plan["source"]["tables"])
            installed = _inventory(stage, stage)
            if installed["contracts"] != plan["target_contracts"]:
                raise ValueError("upgrade did not produce the requested contract combination")
            if _inventory(source, Path(plan["source"]["artifact_root"])) != plan["source"]:
                raise ValueError("source changed before upgrade installation")
            if _control_handoff(tuple(Path(item["path"]) for item in plan["control_state"]["records"]), source,
                                declared_none=plan["control_state"]["declaration"] == "none") != plan["control_state"]:
                raise ValueError("external control state changed before installation")
            receipt = {"operation": "archive-upgrade", "format_version": 1, "plan": plan,
                       "target_database": installed["database"],
                       "files": [{key: value for key, value in item.items() if key != "base"} for item in installed["files"]],
                       "completed_at": int(time.time()), "elapsed_seconds": time.monotonic() - started,
                       "source_unchanged": True, "download_calls": 0, "asr_calls": 0, "ai_calls": 0}
            receipt["receipt_id"] = digest(receipt)
            path = stage / "documents" / "upgrades" / plan["plan_id"] / "receipt.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write((canonical(receipt) + "\n").encode("utf-8"))
                output.flush()
                os.fsync(output.fileno())
            check_upgrade(stage, expected_plan_id=plan["plan_id"])
            for directory, _, _ in os.walk(stage, topdown=False):
                _sync_directory(Path(directory))
            _empty_target(target)
            if target.exists():
                target.rmdir()
            stage.rename(target)
            warnings = []
            try:
                _sync_directory(target.parent)
            except OSError:
                warnings.append("target_parent_directory_sync_failed")
            return {"operation": "archive-upgrade", "valid": True, "plan_id": plan["plan_id"],
                    "target_root": str(target), "reused": False, "receipt_id": receipt["receipt_id"],
                    "control_state": plan["control_state"], "warnings": warnings}


def check_upgrade(target_root: Path, *, expected_plan_id: str) -> dict:
    if not isinstance(expected_plan_id, str) or len(expected_plan_id) != 64 or any(c not in "0123456789abcdef" for c in expected_plan_id):
        raise ValueError("invalid expected upgrade plan identity")
    target = _absolute(target_root)
    with ArchiveSession(target, mode=ArchiveAccessMode.MAINTENANCE).access():
        path = target / "documents" / "upgrades" / expected_plan_id / "receipt.json"
        require_regular_file(path)
        receipt = json.loads(path.read_bytes())
        if receipt.get("receipt_id") != digest({key: value for key, value in receipt.items() if key != "receipt_id"}):
            raise ValueError("upgrade receipt digest mismatch")
        plan = receipt["plan"]
        _validate_plan(plan)
        if plan["plan_id"] != expected_plan_id:
            raise ValueError("completed target belongs to another upgrade plan")
        before = _database_state(target / "archive.db")
        size, sha256, _ = _hash_file(target / "archive.db")
        if {"size": size, "sha256": sha256} != receipt["target_database"]:
            raise ValueError("upgrade installation baseline changed; preserve new work and take a snapshot")
        validate_snapshot_database(target / "archive.db")
        if source_evidence(target / "archive.db")["contracts"] != plan["target_contracts"]:
            raise ValueError("completed upgrade contract mismatch")
        verify_preserved_tables(target / "archive.db", plan["source"]["tables"])
        for item in receipt["files"]:
            actual = _hash_file(target.joinpath(*portable_artifact_parts(item["path"])))
            if actual[:2] != (item["size"], item["sha256"]):
                raise ValueError("upgraded artifact changed: " + item["path"])
        if _database_state(target / "archive.db") != before:
            raise ValueError("target changed during upgrade verification")
        return {"operation": "archive-upgrade-check", "valid": True, "plan_id": expected_plan_id,
                "receipt_id": receipt["receipt_id"], "target_contracts": plan["target_contracts"],
                "control_state": plan["control_state"], "installation_baseline_matches": True}
