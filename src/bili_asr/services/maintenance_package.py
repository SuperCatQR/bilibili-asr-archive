"""Offline private-history packages and an unchanged installation baseline.

This protocol is separate from recovery: importing never reschedules a job,
rewrites frozen content, downloads an object, or calls a provider.
"""
from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from bili_asr import __version__
from bili_asr.archive_session import ArchiveAccessMode, ArchiveSession
from bili_asr.artifact_inventory import (
    check_artifact_collisions, collect_artifacts, portable_artifact_parts,
    require_no_links, require_regular_file, stream_hash,
)
from bili_asr.services.archive_snapshot import (
    _check_bundle_markers, _check_references, _empty_destination,
    _manifest_object, _sync_directory, _sync_file,
)
from bili_asr.services.migration_preflight import _database_state, _hash_file, _identity, _root_entries
from bili_asr.storage.archive_contracts import runtime_contract
from bili_asr.storage.maintenance_selection import refuse_unfinished, select_database, table_ledger
from bili_asr.storage.snapshots import required_artifacts, validate_snapshot_database
from bili_asr.storage.upgrade_evidence import readonly

_NAME = "maintenance.json"
_LIMIT = 16 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CONTRACT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FORMAT = "archive-maintenance-package/v1"
_PLAN = "archive-maintenance-import-plan/v1"
_RECEIPT = "archive-maintenance-import-receipt/v1"
_PROFILE = "private-history"


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def absolute(path: Path) -> Path:
    result = Path(os.path.abspath(path))
    require_no_links(result)
    return result


def _record(path: str, file: Path) -> dict:
    size, sha256, _ = _hash_file(file)
    return {"path": path, "size": size, "sha256": sha256}


def _inventory(root: Path, product: Path) -> tuple[dict, dict[str, Path]]:
    database = root / "archive.db"
    _database_state(database)
    schema_digest = validate_snapshot_database(database)
    refuse_unfinished(database)
    bases = tuple(dict.fromkeys((product, root)))
    if product != root:
        raise ValueError("first-stage maintenance export requires a unified artifact root; materialize external objects before export")
    excluded = _root_entries(root, root, product)
    files = {"archive.db": database, **collect_artifacts(bases)}
    records = [_record(key, path) for key, path in sorted(files.items())]
    _check_references(database, {entry["path"]: entry for entry in records})
    _check_attempt_artifacts(database, {entry["path"]: entry for entry in records})
    with closing(readonly(database)) as connection:
        contract = runtime_contract(connection)
    value = {"runtime_contract": contract, "database_schema_sha256": schema_digest,
             "files": records, "excluded": [{"path": entry["path"], "category": entry["category"]} for entry in excluded]}
    return {**value, "fingerprint": digest(value)}, files


def _selected_artifacts(database: Path, physical: dict[str, Path], parts: list[int]) -> dict[str, Path]:
    needed = set(required_artifacts(database))
    needed.update(_attempt_artifacts(database))
    with closing(readonly(database)) as connection:
        has_sources = connection.execute("SELECT 1 FROM sqlite_master WHERE name='source_videos'").fetchone()
        for part_id in parts:
            bvid, index = connection.execute("SELECT bvid,page_index FROM video_parts WHERE video_part_id=?", (part_id,)).fetchone()
            if bvid is not None:
                stem = f"{bvid}.p{index}"
            elif has_sources:
                platform, external_id = connection.execute("SELECT v.platform,v.external_id FROM video_parts p JOIN source_videos v USING(source_video_id) WHERE p.video_part_id=?", (part_id,)).fetchone()
                from bili_asr.platform_identity import ContentRef
                from bili_asr.source_identity import artifact_stem
                stem = artifact_stem(ContentRef(platform, external_id, index))
            else:
                raise ValueError("selected part has no portable source identity")
            for key in physical:
                if (key.startswith((f"subtitles/{stem}.", f"audio/{stem}.", f"transcripts/{stem}/",
                                    f"documents/part-{part_id}/", f"publications/part-{part_id}/"))):
                    needed.add(key)
    missing = needed - set(physical)
    if missing:
        raise ValueError("selected dependency artifact is missing: " + sorted(missing)[0])
    return {key: physical[key] for key in sorted(needed)}


def _attempt_artifacts(database: Path) -> dict[str, str | None]:
    """Registered output paths remain dependencies even after failed attempts."""
    from bili_asr.artifacts import REQUIRED_ARTIFACT_KEYS, BUNDLE_MARKER_NAME
    result = {}
    with closing(readonly(database)) as connection:
        envelopes = [row[0] for row in connection.execute("SELECT result_json FROM workflow_attempts WHERE result_json IS NOT NULL")]
        for version, raw in connection.execute("SELECT schema_version,evidence_json FROM transcript_asr_evidence"):
            value = json.loads(raw)
            if version != 1 or not isinstance(value, dict) or value.get("schema_version") != 1:
                raise ValueError("unsupported ASR evidence version")
            if "audio" in value:
                if not isinstance(value["audio"], dict):
                    raise ValueError("unsupported ASR audio evidence")
                envelopes.append(json.dumps(value["audio"]))
        for raw in envelopes:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("unsupported workflow result envelope")
            paths = []
            if "storage_key" in value:
                paths.append((value["storage_key"], value.get("sha256")))
            for key in REQUIRED_ARTIFACT_KEYS:
                if key in value:
                    paths.append((value[key], None))
            if "artifacts" in value:
                if not isinstance(value["artifacts"], dict):
                    raise ValueError("unsupported workflow artifact result")
                paths.extend((path, None) for path in value["artifacts"].values())
            if any(key in value for key in REQUIRED_ARTIFACT_KEYS):
                if not all(key in value for key in REQUIRED_ARTIFACT_KEYS):
                    raise ValueError("incomplete workflow bundle result")
                directory = str(Path(value["raw_path"]).parent).replace("\\", "/")
                paths.append((f"{directory}/{BUNDLE_MARKER_NAME}", None))
            for path, sha256 in paths:
                portable_artifact_parts(path)
                if sha256 is not None and (not isinstance(sha256, str) or not _HASH.fullmatch(sha256)):
                    raise ValueError("invalid workflow result artifact hash")
                previous = result.get(path)
                if previous is not None and sha256 is not None and previous != sha256:
                    raise ValueError("conflicting workflow result artifact identity")
                if path not in result or sha256 is not None:
                    result[path] = sha256
    return result


def _check_attempt_artifacts(database: Path, files: dict[str, dict]) -> None:
    for path, expected in _attempt_artifacts(database).items():
        if path not in files or (expected is not None and files[path]["sha256"] != expected):
            raise ValueError("workflow result references a missing or changed artifact: " + path)


def export_package(source_root: Path, output: Path, *, part_ids: list[int] | None = None,
                   bvids: list[str] | None = None, artifact_root: Path | None = None) -> dict:
    root, out = absolute(source_root), absolute(output)
    product = root if artifact_root is None else absolute(artifact_root)
    if out.is_relative_to(root) or out.is_relative_to(product):
        raise ValueError("maintenance package output must be outside its source roots")
    if out.exists():
        raise ValueError("maintenance package output already exists")
    if not out.parent.is_dir():
        raise ValueError("maintenance package output parent must exist")
    with ArchiveSession(root, mode=ArchiveAccessMode.MAINTENANCE).access():
        source, physical = _inventory(root, product)
        with tempfile.TemporaryDirectory(prefix=".maintenance-export-", dir=out.parent) as temporary:
            stage = Path(temporary)
            if part_ids or bvids:
                database = stage / "archive.db"
                selection = select_database(root / "archive.db", database, part_ids=part_ids or [], bvids=bvids or [])
                selected = _selected_artifacts(database, physical, selection["resolved_part_ids"])
                selection.update({"mode": "selected", "requested_bvids": sorted(set(bvids or []))})
            else:
                database = root / "archive.db"
                selected = {key: value for key, value in physical.items() if key != "archive.db"}
                selection = {"mode": "full", "policy": "all-private-history/v1"}
            selected = {"archive.db": database, **selected}
            files = [_record(key, path) for key, path in sorted(selected.items())]
            _check_references(database, {entry["path"]: entry for entry in files})
            _check_attempt_artifacts(database, {entry["path"]: entry for entry in files})
            # Volatile creation time is outside content identity. Decoded payload
            # and typed row ledgers are stable across repeated exports.
            provenance = {key: value for key, value in source.items() if key != "files"}
            provenance["file_count"] = len(source["files"])
            provenance["total_bytes"] = sum(entry["size"] for entry in source["files"])
            content = {"format": _FORMAT, "profile": _PROFILE, "source": provenance,
                       "selection": selection, "database_contract": validate_snapshot_database(database),
                       "tables": table_ledger(database), "files": files,
                       "redaction_policy": "none-frozen-private-history; credentials-models-cache-logs-excluded"}
            manifest = {**content, "content_id": digest(content), "producer_version": __version__,
                        "created_at": datetime.now(UTC).isoformat()}
            path = stage / "package.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
                for entry in files:
                    original = selected[entry["path"]]
                    before = _identity(original)
                    with original.open("rb") as reader, bundle.open(entry["path"], "w", force_zip64=True) as writer:
                        size, sha256 = stream_hash(reader, writer)
                    if (size, sha256) != (entry["size"], entry["sha256"]) or _identity(original) != before:
                        raise ValueError("source changed while packaging: " + entry["path"])
                bundle.writestr(_NAME, canonical(manifest))
                _check_bundle_markers(bundle, {entry["path"]: entry for entry in files})
            current, _ = _inventory(root, product)
            if current != source:
                raise ValueError("source inventory changed during maintenance export")
            with path.open("r+b") as stream:
                _sync_file(stream)
            # Never overwrite a concurrently created output.
            if os.name == "nt":
                path.rename(out)
            else:
                os.link(path, out)
                path.unlink()
            _sync_directory(out.parent)
    return {"operation": "maintenance-export", "valid": True, "package": str(out),
            "content_id": manifest["content_id"], "selection": selection, "file_count": len(files)}


def _json(path: Path) -> dict:
    require_regular_file(path)
    if path.stat().st_size > _LIMIT:
        raise ValueError("oversized maintenance JSON document")
    document = json.loads(path.read_bytes(), object_pairs_hook=_manifest_object)
    if not isinstance(document, dict):
        raise ValueError("maintenance document must be an object")
    return document


def _read_manifest(bundle: zipfile.ZipFile) -> dict:
    members = bundle.infolist()
    names = []
    for member in members:
        if (member.orig_filename != member.filename or member.is_dir() or member.flag_bits & 1
                or member.compress_type != zipfile.ZIP_STORED):
            raise ValueError("invalid maintenance package member")
        mode = member.external_attr >> 16
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
            raise ValueError("maintenance package cannot contain links or special files")
        if member.filename != _NAME:
            portable_artifact_parts(member.filename)
        names.append(member.filename)
    if len(set(names)) != len(names):
        raise ValueError("duplicate maintenance package member")
    check_artifact_collisions([name for name in names if name != _NAME])
    member = bundle.getinfo(_NAME)
    if member.file_size > _LIMIT:
        raise ValueError("oversized maintenance manifest")
    with bundle.open(member) as stream:
        raw = stream.read(_LIMIT + 1)
    if len(raw) > _LIMIT:
        raise ValueError("oversized maintenance manifest")
    document = json.loads(raw, object_pairs_hook=_manifest_object)
    _validate_manifest(document)
    files = document["files"]
    listed = []
    for entry in files:
        if bundle.getinfo(entry["path"]).file_size != entry["size"]:
            raise ValueError("maintenance declared file size mismatch")
        listed.append(entry["path"])
    if set(names) != {*listed, _NAME}:
        raise ValueError("maintenance member inventory mismatch")
    return document


def _validate_manifest(document: dict) -> None:
    from bili_asr.contracts.json_schema import validate_json
    validate_json(_FORMAT, document)
    keys = {"format", "profile", "source", "selection", "database_contract", "tables", "files",
            "redaction_policy", "content_id", "producer_version", "created_at"}
    if not isinstance(document, dict) or set(document) != keys or document["format"] != _FORMAT or document["profile"] != _PROFILE:
        raise ValueError("unsupported maintenance manifest contract")
    content = {key: value for key, value in document.items() if key not in {"content_id", "created_at", "producer_version"}}
    if document["content_id"] != digest(content):
        raise ValueError("maintenance content identity mismatch")
    if (not isinstance(document["database_contract"], str) or not _CONTRACT.fullmatch(document["database_contract"])
            or not isinstance(document["producer_version"], str)
            or document["redaction_policy"] != "none-frozen-private-history; credentials-models-cache-logs-excluded"):
        raise ValueError("invalid maintenance contract or privacy policy")
    try:
        timestamp = datetime.fromisoformat(document["created_at"])
        if timestamp.utcoffset() != UTC.utcoffset(timestamp):
            raise ValueError("not UTC")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid maintenance creation timestamp") from exc
    source = document["source"]
    if (not isinstance(source, dict) or set(source) != {"runtime_contract", "database_schema_sha256", "excluded", "fingerprint", "file_count", "total_bytes"}
            or source["runtime_contract"] not in {"bilibili-v1", "universal-v2"}
            or not isinstance(source["fingerprint"], str) or not _HASH.fullmatch(source["fingerprint"])
            or not isinstance(source["database_schema_sha256"], str) or not _CONTRACT.fullmatch(source["database_schema_sha256"])
            or type(source["file_count"]) is not int or source["file_count"] < 1
            or type(source["total_bytes"]) is not int or source["total_bytes"] < 0
            or not isinstance(source["excluded"], list)):
        raise ValueError("invalid maintenance source provenance")
    selection = document["selection"]
    if not isinstance(selection, dict):
        raise ValueError("invalid maintenance selection")
    if selection.get("mode") == "full":
        if selection != {"mode": "full", "policy": "all-private-history/v1"}:
            raise ValueError("unsupported maintenance full selection policy")
    elif selection.get("mode") == "selected":
        if (set(selection) != {"mode", "policy", "requested_part_ids", "resolved_part_ids", "requested_bvids"}
                or selection["policy"] != "native-full-part-history-fk-owned-json/v1"
                or not isinstance(selection["requested_bvids"], list)
                or any(not isinstance(value, str) or not value for value in selection["requested_bvids"])):
            raise ValueError("unsupported maintenance selected policy")
        for key in ("requested_part_ids", "resolved_part_ids"):
            values = selection[key]
            if not isinstance(values, list) or not values or any(type(value) is not int or value < 1 for value in values) or values != sorted(set(values)):
                raise ValueError("invalid maintenance part selection")
        if not set(selection["requested_part_ids"]) <= set(selection["resolved_part_ids"]):
            raise ValueError("maintenance closure excludes requested parts")
    else:
        raise ValueError("unsupported maintenance selection mode")
    tables = document["tables"]
    if not isinstance(tables, list) or not tables:
        raise ValueError("invalid maintenance typed table ledger")
    for table in tables:
        if (not isinstance(table, dict) or set(table) != {"name", "columns", "row_count", "sha256", "includes_rowid"}
                or not isinstance(table["name"], str) or not table["name"]
                or not isinstance(table["columns"], list) or not table["columns"]
                or any(not isinstance(value, str) or not value for value in table["columns"])
                or type(table["row_count"]) is not int or table["row_count"] < 0
                or type(table["includes_rowid"]) is not bool
                or not isinstance(table["sha256"], str) or not _HASH.fullmatch(table["sha256"])):
            raise ValueError("invalid maintenance typed table entry")
    if len({table["name"] for table in tables}) != len(tables):
        raise ValueError("duplicate maintenance table entry")
    files = document["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("invalid maintenance file inventory")
    listed = []
    for entry in files:
        if (not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}
                or type(entry["size"]) is not int or entry["size"] < 0
                or not isinstance(entry["sha256"], str) or not _HASH.fullmatch(entry["sha256"])):
            raise ValueError("invalid maintenance file entry")
        portable_artifact_parts(entry["path"])
        listed.append(entry["path"])
    check_artifact_collisions(listed)
    if len(set(listed)) != len(listed) or "archive.db" not in listed:
        raise ValueError("maintenance member inventory mismatch")


def inspect_package(package: Path) -> dict:
    path = absolute(package)
    require_regular_file(path)
    with zipfile.ZipFile(path) as bundle:
        manifest = _read_manifest(bundle)
    return {"operation": "maintenance-inspect", "valid": True, "payload_verified": False, "manifest": manifest}


def _extract(package: Path, stage: Path, *, artifacts: bool = True) -> dict:
    require_regular_file(package)
    with zipfile.ZipFile(package) as bundle:
        manifest = _read_manifest(bundle)
        for entry in manifest["files"]:
            output = stage.joinpath(*portable_artifact_parts(entry["path"]))
            with bundle.open(entry["path"]) as reader:
                if artifacts or entry["path"] == "archive.db":
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with output.open("xb") as writer:
                        actual = stream_hash(reader, writer)
                        _sync_file(writer)
                else:
                    actual = stream_hash(reader)
            if actual != (entry["size"], entry["sha256"]):
                raise ValueError("maintenance file hash mismatch: " + entry["path"])
        _check_bundle_markers(bundle, {entry["path"]: entry for entry in manifest["files"]})
    database = stage / "archive.db"
    validate_snapshot_database(database, expected_contract=manifest["database_contract"])
    refuse_unfinished(database)
    if table_ledger(database) != manifest["tables"]:
        raise ValueError("maintenance typed table ledger mismatch")
    _check_references(database, {entry["path"]: entry for entry in manifest["files"]})
    _check_attempt_artifacts(database, {entry["path"]: entry for entry in manifest["files"]})
    return manifest


def verify_package(package: Path) -> dict:
    path = absolute(package)
    before = _hash_file(path)[:2]
    with tempfile.TemporaryDirectory(prefix="maintenance-verify-") as temporary:
        manifest = _extract(path, Path(temporary), artifacts=False)
    if _hash_file(path)[:2] != before:
        raise ValueError("maintenance package changed during verification")
    return {"operation": "maintenance-verify", "valid": True, "content_id": manifest["content_id"],
            "file_count": len(manifest["files"]), "total_bytes": sum(entry["size"] for entry in manifest["files"])}


def _free_space(target: Path, needed: int) -> None:
    ancestor = target.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < needed:
        raise ValueError("maintenance target lacks staging space")


def plan_import(package: Path, target_root: Path) -> dict:
    path, target = absolute(package), absolute(target_root)
    if path.is_relative_to(target):
        raise ValueError("maintenance target cannot contain its package")
    _empty_destination(target)
    before = _record("package", path)
    verified = verify_package(path)
    if _record("package", path) != before:
        raise ValueError("maintenance package changed during preflight")
    needed = verified["total_bytes"] + 32 * 1024**2
    _free_space(target, needed)
    plan = {"format": _PLAN, "policy": "new-target-only", "package": str(path),
            "package_file": before, "content_id": verified["content_id"],
            "target_root": str(target), "required_free_bytes": needed}
    return {**plan, "plan_id": digest(plan)}


def _validate_plan(plan: dict) -> None:
    if (set(plan) != {"format", "policy", "package", "package_file", "content_id", "target_root", "required_free_bytes", "plan_id"}
            or plan["format"] != _PLAN or plan["policy"] != "new-target-only"
            or plan["plan_id"] != digest({key: value for key, value in plan.items() if key != "plan_id"})):
        raise ValueError("invalid maintenance import plan")
    if type(plan["required_free_bytes"]) is not int or plan["required_free_bytes"] < 32 * 1024**2:
        raise ValueError("invalid maintenance staging estimate")
    if str(absolute(Path(plan["target_root"]))) != plan["target_root"] or str(absolute(Path(plan["package"]))) != plan["package"]:
        raise ValueError("maintenance plan paths must be absolute")


def _receipt_path(root: Path, plan_id: str) -> Path:
    if not isinstance(plan_id, str) or not _HASH.fullmatch(plan_id):
        raise ValueError("invalid maintenance plan identity")
    return root / "documents" / "maintenance" / plan_id / "receipt.json"


def _check_installation(root: Path, plan_id: str, *, staged: bool = False) -> dict:
    path = _receipt_path(root, plan_id)
    receipt = _json(path)
    if (set(receipt) != {"format", "plan", "manifest", "receipt_id"} or receipt["format"] != _RECEIPT
            or receipt["receipt_id"] != digest({key: value for key, value in receipt.items() if key != "receipt_id"})):
        raise ValueError("invalid maintenance receipt")
    _validate_plan(receipt["plan"])
    if receipt["plan"]["plan_id"] != plan_id:
        raise ValueError("maintenance receipt belongs to another plan")
    if not staged and receipt["plan"]["target_root"] != str(root):
        raise ValueError("maintenance receipt target path does not match this installation")
    manifest = receipt["manifest"]
    _validate_manifest(manifest)
    if manifest["content_id"] != receipt["plan"]["content_id"]:
        raise ValueError("maintenance receipt content mismatch")
    before = _database_state(root / "archive.db")
    files = {"archive.db": root / "archive.db", **collect_artifacts((root,))}
    baseline = {entry["path"]: entry for entry in manifest["files"]}
    receipt_key = path.relative_to(root).as_posix()
    if set(files) != set(baseline) | {receipt_key}:
        raise ValueError("maintenance installation file set changed")
    for key, expected in baseline.items():
        if _record(key, files[key]) != expected:
            raise ValueError("maintenance installation baseline changed: " + key)
    validate_snapshot_database(root / "archive.db", expected_contract=manifest["database_contract"])
    if table_ledger(root / "archive.db") != manifest["tables"]:
        raise ValueError("maintenance installation typed rows changed")
    _check_references(root / "archive.db", baseline)
    _check_attempt_artifacts(root / "archive.db", baseline)
    if _database_state(root / "archive.db") != before:
        raise ValueError("maintenance installation changed during verification")
    return {"operation": "maintenance-import-check", "valid": True, "plan_id": plan_id,
            "receipt_id": receipt["receipt_id"], "installation_baseline_matches": True}


def check_import(target_root: Path, *, plan_id: str) -> dict:
    root = absolute(target_root)
    with ArchiveSession(root, mode=ArchiveAccessMode.MAINTENANCE).access():
        return _check_installation(root, plan_id)


def apply_import(plan_path: Path) -> dict:
    plan = _json(absolute(plan_path))
    _validate_plan(plan)
    package, target = absolute(Path(plan["package"])), absolute(Path(plan["target_root"]))
    if _record("package", package) != plan["package_file"]:
        raise ValueError("maintenance package changed since import planning")
    target.parent.mkdir(parents=True, exist_ok=True)
    with ArchiveSession(target, mode=ArchiveAccessMode.MAINTENANCE).access(allow_missing=True):
        if _receipt_path(target, plan["plan_id"]).exists():
            return {**_check_installation(target, plan["plan_id"]), "reused": True}
        current = plan_import(package, target)
        if current != plan:
            raise ValueError("maintenance preflight no longer matches its plan")
        with tempfile.TemporaryDirectory(prefix=f".{target.name}.maintenance-", dir=target.parent) as temporary:
            stage = Path(temporary) / "archive"
            stage.mkdir()
            manifest = _extract(package, stage)
            if _record("package", package) != plan["package_file"]:
                raise ValueError("maintenance package changed during import")
            path = _receipt_path(stage, plan["plan_id"])
            if path.exists():
                raise ValueError("package collides with its new import receipt")
            path.parent.mkdir(parents=True, exist_ok=True)
            value = {"format": _RECEIPT, "plan": plan, "manifest": manifest}
            receipt = {**value, "receipt_id": digest(value)}
            with path.open("xb") as stream:
                stream.write(canonical(receipt) + b"\n")
                _sync_file(stream)
            _check_installation(stage, plan["plan_id"], staged=True)
            for directory, _, _ in os.walk(stage, topdown=False):
                _sync_directory(Path(directory))
            if _empty_destination(target):
                target.rmdir()
            stage.rename(target)
            _sync_directory(target.parent)
    return {"operation": "maintenance-import-apply", "valid": True, "plan_id": plan["plan_id"],
            "receipt_id": receipt["receipt_id"], "reused": False, "target_root": str(target)}


def write_plan(plan: dict, output: Path) -> None:
    """Save a plan exclusively; a failed write never leaves a partial document."""
    out = absolute(output)
    if out.exists() or not out.parent.is_dir() or out.is_relative_to(Path(plan["target_root"])):
        raise ValueError("plan output must be a new file outside the target with an existing parent")
    with tempfile.TemporaryDirectory(prefix=".maintenance-plan-", dir=out.parent) as temporary:
        staged = Path(temporary) / "plan.json"
        with staged.open("xb") as stream:
            stream.write(canonical(plan) + b"\n")
            _sync_file(stream)
        if os.name == "nt":
            staged.rename(out)
        else:
            os.link(staged, out)
            staged.unlink()
        _sync_directory(out.parent)
