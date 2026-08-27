#!/usr/bin/env python3
"""Run the deterministic, offline verification baseline for bili-asr."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA = "bili-asr-verification-baseline/v2"
SNAPSHOT_SCHEMA = "bili-asr-advisory-snapshot/v1"
SUPPORTED_PYTHON = (3, 12)
FORBIDDEN_OUTPUT = ("SESSDATA", "BILI_SESSDATA", "Authorization", "Cookie", "token=", "signature=", "deadline=", "bilivideo.com", "Traceback (most recent call last)")
URL_RE = re.compile(r"(?i)https?://[^\s\"']+")
SECRET_RE = re.compile(r"(?i)(?:sessdata|authorization|cookie|access[_-]?token|token|signature|sign|deadline)\s*(?:=|:)\s*[^\s,;]+")


class PrerequisiteError(RuntimeError):
    pass


def redact(value: str, limit: int = 500) -> str:
    return SECRET_RE.sub("[redacted]", URL_RE.sub("[redacted-url]", value))[:limit]


def safe_env() -> dict[str, str]:
    removed = {"PYTHONPATH", "BILI_SESSDATA", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}
    env = {k: v for k, v in os.environ.items() if k not in removed}
    env.update(PYTHONNOUSERSITE="1", PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    return env


def record_command(result: dict[str, Any], name: str, command: list[str], cwd: Path) -> None:
    proc = subprocess.run(command, cwd=cwd, env=safe_env(), capture_output=True, text=True)
    output = redact((proc.stdout or "") + (proc.stderr or ""))
    if any(fragment in output for fragment in FORBIDDEN_OUTPUT):
        raise RuntimeError(f"{name} emitted a forbidden diagnostic fragment")
    result["commands"].append({"name": name, "returncode": proc.returncode})
    if proc.returncode:
        if name == "create_venv":
            raise PrerequisiteError("cannot create isolated virtual environment; provide Python 3.12 with venv/ensurepip support")
        raise RuntimeError(f"{name} failed (exit {proc.returncode}): {output}")


def scripts_dir(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrerequisiteError(f"advisory snapshot unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SNAPSHOT_SCHEMA or not isinstance(data.get("advisories"), list):
        raise PrerequisiteError(f"advisory snapshot must have schema {SNAPSHOT_SCHEMA} and an advisories list")
    for item in data["advisories"]:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("id", "name", "specifier")):
            raise PrerequisiteError("advisory snapshot entries require string id, name, and specifier")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return data, digest


def venv_site_packages(venv_python: Path) -> list[str]:
    proc = subprocess.run(
        [str(venv_python), "-c", "import json, sysconfig; print(json.dumps([sysconfig.get_path('purelib'), sysconfig.get_path('platlib')]))"],
        env=safe_env(),
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        raise PrerequisiteError("cannot determine isolated virtual environment site-packages")
    try:
        paths = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PrerequisiteError("isolated virtual environment returned invalid site-packages metadata") from exc
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise PrerequisiteError("isolated virtual environment returned invalid site-packages metadata")
    return list(dict.fromkeys(paths))


def installed_packages(venv_python: Path) -> dict[str, str]:
    proc = subprocess.run(
        [str(venv_python), "-m", "pip", "list", "--format=json"],
        env=safe_env(),
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        raise PrerequisiteError("cannot inspect installed distributions in isolated virtual environment")
    try:
        distributions = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PrerequisiteError("isolated virtual environment returned invalid distribution metadata") from exc
    if not isinstance(distributions, list):
        raise PrerequisiteError("isolated virtual environment returned invalid distribution metadata")
    packages: dict[str, str] = {}
    for distribution in distributions:
        if not isinstance(distribution, dict) or not isinstance(distribution.get("name"), str) or not isinstance(distribution.get("version"), str):
            raise PrerequisiteError("isolated virtual environment returned invalid distribution metadata")
        packages[distribution["name"].lower()] = distribution["version"]
    return packages


def advisory_applies(advisory: dict[str, str], installed_version: str) -> bool:
    try:
        return Version(installed_version) in SpecifierSet(advisory["specifier"])
    except (InvalidSpecifier, InvalidVersion) as exc:
        raise PrerequisiteError(f"unsupported advisory specifier for {advisory['id']}") from exc


def audit(venv_python: Path, advisory_snapshot: Path | None, result: dict[str, Any]) -> None:
    result["audit"] = {"status": "unavailable", "policy": "local snapshot only; no pip-audit or network lookup"}
    if advisory_snapshot is None or not advisory_snapshot.is_file():
        raise PrerequisiteError("security audit unavailable: supply a reviewed local --advisory-snapshot")
    snapshot, digest = load_snapshot(advisory_snapshot)
    site_packages = venv_site_packages(venv_python)
    packages = installed_packages(venv_python)
    findings = [
        advisory["id"]
        for advisory in snapshot["advisories"]
        if advisory["name"].lower() in packages and advisory_applies(advisory, packages[advisory["name"].lower()])
    ]
    result["audit"] = {
        "status": "findings" if findings else "passed",
        "snapshot": {"schema": snapshot["schema"], "sha256_16": digest},
        "site_packages": site_packages,
        "finding_ids": findings,
    }
    if findings:
        raise RuntimeError("security audit reported findings; remediation belongs in a separate plan")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=ROOT / "verification-results" / "baseline.json")
    parser.add_argument("--advisory-snapshot", type=Path)
    parser.add_argument("--offline-packages", type=Path, help="prepared wheel/sdist directory containing project dev dependencies")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    result: dict[str, Any] = {"schema": RESULT_SCHEMA, "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "project": "bili-asr", "network_policy": "offline-only", "commands": [], "status": "failed"}
    result_path = ROOT / "verification-results" / "baseline.json"
    try:
        try:
            args = parse_args(argv)
        except SystemExit as exc:
            result["status"] = "prerequisite_failed"
            result["error"] = "invalid arguments; use --help for supported options"
            return 2
        result_path = args.result
        if sys.version_info[:2] != SUPPORTED_PYTHON:
            raise PrerequisiteError(f"Python 3.12 is required; running {sys.version_info.major}.{sys.version_info.minor}")
        if args.offline_packages is None or not args.offline_packages.is_dir():
            raise PrerequisiteError("isolated install unavailable: supply --offline-packages prepared local dependency source")
        with tempfile.TemporaryDirectory(prefix="bili-asr-verify-") as temp:
            venv = Path(temp) / "venv"
            record_command(result, "create_venv", [sys.executable, "-m", "venv", str(venv)], ROOT)
            python = scripts_dir(venv) / ("python.exe" if os.name == "nt" else "python")
            record_command(result, "install_declared_dev_extras", [str(python), "-m", "pip", "install", "--no-index", "--find-links", str(args.offline_packages.resolve()), "--no-build-isolation", ".[dev]"], ROOT)
            record_command(result, "installed_console_help", [str(scripts_dir(venv) / "bili-asr"), "--help"], ROOT)
            record_command(result, "full_test_suite", [str(python), "-m", "pytest", "-q"], ROOT)
            audit(python, args.advisory_snapshot, result)
        result["status"] = "passed"
        return 0
    except PrerequisiteError as exc:
        result["status"] = "prerequisite_failed"; result["error"] = redact(str(exc)); return 2
    except Exception as exc:
        result["status"] = "failed"; result["error"] = redact(str(exc)); return 1
    finally:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
