#!/usr/bin/env python3
"""Run the deterministic, offline verification baseline for bili-asr."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA = "bili-asr-verification-baseline/v3"
SNAPSHOT_SCHEMA = "bili-asr-advisory-snapshot/v1"
FIXTURE_SCHEMA = "bili-asr-offline-fixture/v1"
SUPPORTED_PYTHON = (3, 12)
RESULT_DIR = ROOT / "verification-results"
DEFAULT_RESULT = RESULT_DIR / "baseline.json"
MAX_DIAGNOSTIC_LENGTH = 500
SENSITIVE_KEY = r"(?:sessdata|authorization|proxy-authorization|cookie|set-cookie|access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|token|signature|sign|deadline)"
URL_RE = re.compile(r"(?i)https?://[^\s\"']+")
HEADER_SECRET_RE = re.compile(rf"(?im)^(\s*{SENSITIVE_KEY}\s*:\s*)[^\r\n]*")
BEARER_SECRET_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]+")
JSON_SECRET_RE = re.compile(rf'(?i)("{SENSITIVE_KEY}"\s*:\s*)"(?:[^"\\]|\\.)*"')
ASSIGNMENT_SECRET_RE = re.compile(rf"(?i)(\b{SENSITIVE_KEY}\s*(?:=|:)\s*)[^\s,;]+")
BARE_SECRET_RE = re.compile(rf"(?i)(\b{SENSITIVE_KEY}\s+)[^\s,;]+")


class PrerequisiteError(RuntimeError):
    pass


def redact(value: str, limit: int = MAX_DIAGNOSTIC_LENGTH) -> str:
    """Redact routine credential and signed-URL formats before persistence."""
    redacted = URL_RE.sub("[redacted-url]", value)
    redacted = HEADER_SECRET_RE.sub(r"\1[redacted]", redacted)
    redacted = BEARER_SECRET_RE.sub("Bearer [redacted]", redacted)
    redacted = JSON_SECRET_RE.sub(r'\1"[redacted]"', redacted)
    redacted = ASSIGNMENT_SECRET_RE.sub(r"\1[redacted]", redacted)
    redacted = BARE_SECRET_RE.sub(r"\1[redacted]", redacted)
    return redacted[:limit]


def safe_env() -> dict[str, str]:
    removed = {
        "PYTHONPATH", "BILI_SESSDATA", "SESSDATA", "HTTP_PROXY", "HTTPS_PROXY",
        "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
    }
    env = {key: value for key, value in os.environ.items() if key not in removed}
    env.update(PYTHONNOUSERSITE="1", PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    return env


def record_command(result: dict[str, Any], name: str, command: list[str], cwd: Path) -> None:
    proc = subprocess.run(command, cwd=cwd, env=safe_env(), capture_output=True, text=True)
    output = redact((proc.stdout or "") + (proc.stderr or ""))
    result["commands"].append({"name": name, "returncode": proc.returncode})
    if proc.returncode:
        if name == "create_venv":
            raise PrerequisiteError("isolated_environment_unavailable: Python 3.12 venv/ensurepip support is required")
        if name == "install_declared_dev_extras":
            raise PrerequisiteError(f"offline_dependency_closure_unavailable: install failed (exit {proc.returncode}): {output}")
        raise RuntimeError(f"{name}_failed: exit {proc.returncode}: {output}")


def scripts_dir(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def snapshot_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise PrerequisiteError("advisory_snapshot_invalid: snapshot is unreadable") from exc
    if not isinstance(data, dict) or data.get("schema") != SNAPSHOT_SCHEMA or not isinstance(data.get("advisories"), list):
        raise PrerequisiteError(f"advisory_snapshot_invalid: expected schema {SNAPSHOT_SCHEMA} and advisories list")
    seen_ids: set[str] = set()
    validated: list[dict[str, str]] = []
    for item in data["advisories"]:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("id", "name", "specifier")):
            raise PrerequisiteError("advisory_snapshot_invalid: entries require non-empty string id, name, and specifier")
        advisory_id = item["id"].strip()
        if advisory_id in seen_ids:
            raise PrerequisiteError(f"advisory_snapshot_invalid: duplicate advisory id {advisory_id}")
        try:
            SpecifierSet(item["specifier"])
        except InvalidSpecifier as exc:
            raise PrerequisiteError(f"advisory_snapshot_invalid: unsupported specifier for {advisory_id}") from exc
        seen_ids.add(advisory_id)
        validated.append({"id": advisory_id, "name": canonicalize_name(item["name"]), "specifier": item["specifier"]})
    snapshot = {**data, "advisories": validated}
    return snapshot, hashlib.sha256(raw).hexdigest()[:16]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_fixture(path: Path) -> dict[str, Any]:
    manifest_path = path / "fixture-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrerequisiteError("offline_fixture_invalid: fixture-manifest.json is required and must be valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != FIXTURE_SCHEMA or not isinstance(manifest.get("artifacts"), list):
        raise PrerequisiteError(f"offline_fixture_invalid: expected schema {FIXTURE_SCHEMA} and artifacts list")
    artifacts = manifest["artifacts"]
    if not artifacts:
        raise PrerequisiteError("offline_fixture_invalid: fixture has no declared artifacts")
    artifact_names: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str) or not isinstance(item.get("sha256"), str):
            raise PrerequisiteError("offline_fixture_invalid: artifacts require filename and sha256")
        candidate = path / item["filename"]
        if item["filename"] in artifact_names or candidate.parent != path or not candidate.is_file() or file_digest(candidate) != item["sha256"]:
            raise PrerequisiteError("offline_fixture_invalid: artifact content does not match fixture manifest")
        artifact_names.add(item["filename"])
    required = manifest.get("required_distributions")
    if not isinstance(required, list) or not required or not all(isinstance(name, str) and name.strip() for name in required):
        raise PrerequisiteError("offline_fixture_invalid: required_distributions is missing")
    if len({canonicalize_name(name) for name in required}) != len(required):
        raise PrerequisiteError("offline_fixture_invalid: required_distributions contains duplicates")
    return manifest


def installed_packages(venv_python: Path) -> dict[str, str]:
    proc = subprocess.run([str(venv_python), "-m", "pip", "list", "--format=json"], env=safe_env(), capture_output=True, text=True)
    if proc.returncode:
        raise PrerequisiteError("isolated_environment_invalid: cannot inspect installed distributions")
    try:
        distributions = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PrerequisiteError("isolated_environment_invalid: invalid distribution metadata") from exc
    if not isinstance(distributions, list):
        raise PrerequisiteError("isolated_environment_invalid: invalid distribution metadata")
    packages: dict[str, str] = {}
    for distribution in distributions:
        if not isinstance(distribution, dict) or not isinstance(distribution.get("name"), str) or not isinstance(distribution.get("version"), str):
            raise PrerequisiteError("isolated_environment_invalid: invalid distribution metadata")
        packages[canonicalize_name(distribution["name"])] = distribution["version"]
    return packages


def advisory_applies(advisory: dict[str, str], installed_version: str) -> bool:
    try:
        return Version(installed_version) in SpecifierSet(advisory["specifier"])
    except (InvalidSpecifier, InvalidVersion) as exc:
        raise PrerequisiteError(f"advisory_snapshot_invalid: unsupported specifier for {advisory['id']}") from exc


def audit(venv_python: Path, snapshot: dict[str, Any], digest: str, result: dict[str, Any]) -> None:
    packages = installed_packages(venv_python)
    findings = [
        {"id": advisory["id"], "package": advisory["name"], "specifier": advisory["specifier"]}
        for advisory in snapshot["advisories"]
        if advisory["name"] in packages and advisory_applies(advisory, packages[advisory["name"]])
    ]
    result["audit"] = {
        "status": "findings" if findings else "passed",
        "policy": "local snapshot only; no pip-audit or network lookup",
        "snapshot": {"schema": snapshot["schema"], "sha256_16": digest, "advisory_count": len(snapshot["advisories"])},
        "finding_ids": [finding["id"] for finding in findings],
        "findings": findings,
        "installed_distribution_count": len(packages),
    }
    if findings:
        raise RuntimeError("security_audit_findings: remediation belongs in a separate plan")


def staged_test_tree(destination: Path) -> Path:
    staged = destination / "tests"
    shutil.copytree(ROOT / "tests", staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    (staged / "conftest.py").write_text(
        (staged / "conftest.py").read_text(encoding="utf-8").replace(
            'sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))\n',
            "",
        ),
        encoding="utf-8",
    )
    return staged


def result_path_from_args(args: argparse.Namespace) -> Path:
    requested = DEFAULT_RESULT if args.result is None else args.result.resolve()
    if requested != DEFAULT_RESULT.resolve():
        raise PrerequisiteError("result_path_invalid: --result must be verification-results/baseline.json")
    return DEFAULT_RESULT


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, help="reserved; only verification-results/baseline.json is allowed")
    parser.add_argument("--advisory-snapshot", type=Path, required=True)
    parser.add_argument("--offline-packages", type=Path, required=True, help="validated offline fixture directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    result: dict[str, Any] = {"schema": RESULT_SCHEMA, "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "project": "bili-asr", "network_policy": "offline-only", "commands": [], "status": "failed"}
    result_path = DEFAULT_RESULT
    try:
        try:
            args = parse_args(argv)
        except SystemExit:
            result["status"] = "prerequisite_failed"; result["error"] = "invalid_arguments: use --help for supported options"; return 2
        result_path_from_args(args)
        if sys.version_info[:2] != SUPPORTED_PYTHON:
            raise PrerequisiteError(f"python_version_unsupported: Python 3.12 required; running {sys.version_info.major}.{sys.version_info.minor}")
        if not args.offline_packages.is_dir():
            raise PrerequisiteError("offline_fixture_invalid: --offline-packages must be a fixture directory")
        # Complete all inexpensive, local prerequisites before creating a venv.
        fixture = validate_fixture(args.offline_packages)
        snapshot, digest = load_snapshot(args.advisory_snapshot)
        result["fixture"] = {"schema": fixture["schema"], "artifact_count": len(fixture["artifacts"]), "required_distributions": fixture["required_distributions"]}
        with tempfile.TemporaryDirectory(prefix="bili-asr-verify-") as temp:
            temporary = Path(temp)
            venv = temporary / "venv"
            record_command(result, "create_venv", [sys.executable, "-m", "venv", str(venv)], ROOT)
            python = scripts_dir(venv) / ("python.exe" if os.name == "nt" else "python")
            record_command(result, "install_declared_dev_extras", [str(python), "-m", "pip", "install", "--no-index", "--find-links", str(args.offline_packages.resolve()), "--no-build-isolation", ".[dev]"], ROOT)
            record_command(result, "installed_console_help", [str(scripts_dir(venv) / "bili-asr"), "--help"], temporary)
            staged_tests = staged_test_tree(temporary)
            record_command(result, "full_installed_distribution_test_suite", [str(python), "-m", "pytest", "-q", str(staged_tests)], temporary)
            audit(python, snapshot, digest, result)
        result["status"] = "passed"
        return 0
    except PrerequisiteError as exc:
        result["status"] = "prerequisite_failed"; result["error"] = redact(str(exc)); return 2
    except Exception as exc:
        result["status"] = "failed"; result["error"] = redact(str(exc)); return 1
    finally:
        DEFAULT_RESULT.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_RESULT.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
