"""Build evidence captured once per interpreter, independent of the work queue."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

MANIFEST_NAME = "_build_identity.json"
PACKAGE_ROOT = Path(__file__).resolve().parent
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ReleaseIdentityError(RuntimeError):
    """The selected immutable release does not match this interpreter."""


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def package_files(root: Path) -> dict[str, str]:
    """Hash executable source and packaged contracts; exclude bytecode caches."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".py", ".json", ".sql"} or path.name == MANIFEST_NAME:
            continue
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink() or not path.is_file():
            raise ReleaseIdentityError("package contains an unsupported file")
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def create_manifest(root: Path, source_commit: str, lock_sha256: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40,64}", source_commit) or not _HEX64.fullmatch(lock_sha256):
        raise ReleaseIdentityError("invalid release identity")
    value = {"schema_version": 1, "source_commit": source_commit,
             "lock_sha256": lock_sha256, "files": package_files(root)}
    return {**value, "build_id": _digest(value)}


def validate_manifest(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
            "schema_version", "source_commit", "lock_sha256", "files", "build_id"}:
        raise ReleaseIdentityError("invalid build manifest")
    if value["schema_version"] != 1 or not isinstance(value["source_commit"], str) or not re.fullmatch(
            r"[0-9a-f]{40,64}", value["source_commit"]):
        raise ReleaseIdentityError("invalid build manifest")
    for key in ("lock_sha256", "build_id"):
        if not isinstance(value[key], str) or not _HEX64.fullmatch(value[key]):
            raise ReleaseIdentityError("invalid build manifest")
    files = value["files"]
    if not isinstance(files, dict) or not files or len(files) > 10000:
        raise ReleaseIdentityError("invalid build file inventory")
    for name, checksum in files.items():
        if (not isinstance(name, str) or "\\" in name or name.startswith("/")
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or Path(name).suffix not in {".py", ".json", ".sql"}
                or not isinstance(checksum, str) or not _HEX64.fullmatch(checksum)):
            raise ReleaseIdentityError("invalid build file inventory")
    if _digest({k: v for k, v in value.items() if k != "build_id"}) != value["build_id"]:
        raise ReleaseIdentityError("build manifest digest mismatch")
    return value


def _capture() -> tuple[dict | None, str | None]:
    path = PACKAGE_ROOT / MANIFEST_NAME
    try:
        if not path.exists():
            return None, "unattested"
        if path.stat().st_size > 2 * 1024 * 1024 or path.is_symlink():
            return None, "invalid_manifest"
        return validate_manifest(json.loads(path.read_text(encoding="utf-8"))), None
    except (OSError, ValueError, ReleaseIdentityError):
        return None, "invalid_manifest"


# This value never changes after package import. Re-reading an overwritten
# wheel must not make an old PID claim it loaded the new build.
_STARTUP_MANIFEST, _STARTUP_ERROR = _capture()


def build_status(*, expected_build_id: str | None = None) -> dict:
    expected = expected_build_id or os.environ.get("BILI_ASR_EXPECTED_BUILD_ID")
    manifest = _STARTUP_MANIFEST
    result = {"schema_version": 1, "build_id": manifest["build_id"] if manifest else None,
              "source_commit": manifest["source_commit"] if manifest else None,
              "lock_sha256": manifest["lock_sha256"] if manifest else None,
              "state": _STARTUP_ERROR or "verified", "production_acceptance": "pending"}
    if expected is not None and (manifest is None or expected != manifest["build_id"]):
        return {**result, "state": "unexpected_build"}
    if manifest is None:
        return result
    try:
        disk_manifest, disk_error = _capture()
        if disk_error or disk_manifest != manifest or package_files(PACKAGE_ROOT) != manifest["files"]:
            result["state"] = "disk_drift"
    except (OSError, ReleaseIdentityError):
        result["state"] = "disk_unreadable"
    return result


def require_expected_build(expected_build_id: str | None = None) -> dict:
    status = build_status(expected_build_id=expected_build_id)
    if (expected_build_id or os.environ.get("BILI_ASR_EXPECTED_BUILD_ID")) and status["state"] != "verified":
        raise ReleaseIdentityError("release verification failed: " + status["state"])
    if status["state"] not in {"verified", "unattested"}:
        raise ReleaseIdentityError("release verification failed: " + status["state"])
    return status
