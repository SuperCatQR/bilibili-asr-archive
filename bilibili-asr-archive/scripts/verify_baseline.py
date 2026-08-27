#!/usr/bin/env python3
"""Run the deterministic, offline verification baseline for bili-asr.

The script deliberately has no dependency on a live advisory service. It builds
an isolated Python 3.12 virtual environment, installs the local project and its
declared ``dev`` extras from the local wheel cache only, runs the full pytest
suite, then emits a redacted JSON result. A pinned pip-audit executable and a
pinned advisory snapshot are optional inputs; without both, the audit result is
``unavailable`` and the script fails with an actionable prerequisite instead of
claiming a security green result.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA = "bili-asr-verification-baseline/v1"
SUPPORTED_PYTHON = (3, 12)
PIP_AUDIT_VERSION = "2.8.0"
FORBIDDEN_OUTPUT = (
    "SESSDATA",
    "BILI_SESSDATA",
    "Authorization",
    "Cookie",
    "token=",
    "signature=",
    "deadline=",
    "bilivideo.com",
    "Traceback (most recent call last)",
)
URL_RE = re.compile(r"(?i)https?://[^\s\"']+")
SECRET_RE = re.compile(
    r"(?i)(?:sessdata|authorization|cookie|access[_-]?token|token|signature|sign|deadline)"
    r"\s*(?:=|:)\s*[^\s,;]+"
)


class PrerequisiteError(RuntimeError):
    """A named requirement was unavailable; never convert this to a green run."""


def redact(value: str, limit: int = 500) -> str:
    value = URL_RE.sub("[redacted-url]", value)
    value = SECRET_RE.sub("[redacted]", value)
    return value[:limit]


def safe_env() -> dict[str, str]:
    removed = {
        "PYTHONPATH", "BILI_SESSDATA", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    }
    env = {key: value for key, value in os.environ.items() if key not in removed}
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
        }
    )
    return env


def record_command(result: dict[str, Any], name: str, command: list[str], cwd: Path) -> None:
    proc = subprocess.run(command, cwd=cwd, env=safe_env(), capture_output=True, text=True)
    output = redact((proc.stdout or "") + (proc.stderr or ""))
    if any(fragment in output for fragment in FORBIDDEN_OUTPUT):
        raise RuntimeError(f"{name} emitted a forbidden diagnostic fragment")
    result["commands"].append({"name": name, "returncode": proc.returncode})
    if proc.returncode:
        if name == "create_venv":
            raise PrerequisiteError(
                "cannot create an isolated virtual environment; install the Python 3.12 venv/ensurepip "
                "package or provide a Python 3.12 interpreter with `python -m venv` support"
            )
        raise RuntimeError(f"{name} failed (exit {proc.returncode}): {output}")


def scripts_dir(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def audit(venv_python: Path, audit_path: Path | None, advisory_snapshot: Path | None, result: dict[str, Any]) -> None:
    policy = {
        "tool": "pip-audit",
        "required_version": PIP_AUDIT_VERSION,
        "network": "disabled; never query a live advisory database",
        "snapshot": "a versioned local advisory snapshot must be supplied",
    }
    result["audit"] = {"policy": policy, "status": "unavailable"}
    if audit_path is None:
        raise PrerequisiteError(
            f"security audit unavailable: supply --pip-audit PATH pinned to pip-audit=={PIP_AUDIT_VERSION} "
            "and --advisory-snapshot PATH; live advisory lookups are intentionally disabled"
        )
    if advisory_snapshot is None or not advisory_snapshot.is_file():
        raise PrerequisiteError(
            "security audit unavailable: supply a reviewed, versioned local advisory snapshot via "
            "--advisory-snapshot; live advisory lookups are intentionally disabled"
        )
    version = subprocess.run([str(audit_path), "--version"], env=safe_env(), capture_output=True, text=True)
    version_text = redact((version.stdout or "") + (version.stderr or ""))
    if version.returncode or PIP_AUDIT_VERSION not in version_text:
        raise PrerequisiteError(
            f"security audit unavailable: --pip-audit must report pip-audit {PIP_AUDIT_VERSION}; got {version_text!r}"
        )
    # pip-audit supports --local to inspect exactly the isolated environment.
    proc = subprocess.run(
        [str(audit_path), "--local", "--format", "json", "--progress-spinner", "off"],
        env=safe_env(), cwd=venv_python.parent.parent, capture_output=True, text=True,
    )
    output = redact((proc.stdout or "") + (proc.stderr or ""))
    if any(fragment in output for fragment in FORBIDDEN_OUTPUT):
        raise RuntimeError("security audit emitted a forbidden diagnostic fragment")
    result["audit"] = {
        "policy": policy,
        "status": "passed" if proc.returncode == 0 else "findings",
        "advisory_snapshot": advisory_snapshot.name,
        "returncode": proc.returncode,
    }
    if proc.returncode:
        raise RuntimeError("security audit reported findings; record evidence-backed remediation in a separate plan")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=ROOT / "verification-results" / "baseline.json")
    parser.add_argument("--pip-audit", type=Path)
    parser.add_argument("--advisory-snapshot", type=Path)
    args = parser.parse_args()

    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "project": "bili-asr",
        "network_policy": "offline-only; no Bilibili HTTP, model downloads, media transfer, or environment dumps",
        "commands": [],
        "status": "failed",
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    try:
        if sys.version_info[:2] != SUPPORTED_PYTHON:
            raise PrerequisiteError(
                f"Python {SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]} is required; running {sys.version_info.major}.{sys.version_info.minor}"
            )
        with tempfile.TemporaryDirectory(prefix="bili-asr-verify-") as temp:
            venv = Path(temp) / "venv"
            record_command(result, "create_venv", [sys.executable, "-m", "venv", str(venv)], ROOT)
            python = scripts_dir(venv) / ("python.exe" if os.name == "nt" else "python")
            record_command(
                result,
                "install_declared_dev_extras",
                [str(python), "-m", "pip", "install", "--no-index", "--no-build-isolation", "-e", ".[dev]"],
                ROOT,
            )
            record_command(result, "installed_console_help", [str(scripts_dir(venv) / "bili-asr"), "--help"], ROOT)
            record_command(
                result,
                "full_test_suite",
                [str(python), "-m", "pytest", "-q"],
                ROOT,
            )
            audit(python, args.pip_audit, args.advisory_snapshot, result)
        result["status"] = "passed"
        return 0
    except PrerequisiteError as exc:
        result["status"] = "prerequisite_failed"
        result["error"] = redact(str(exc))
        return 2
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = redact(str(exc))
        return 1
    finally:
        args.result.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
