#!/usr/bin/env python3
"""Build a bounded, validated offline fixture and optionally run the baseline."""
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

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCHEMA = "bili-asr-offline-fixture/v1"
PROJECT_NAME = "bili-asr"
WHEEL_NAME_RE = re.compile(r"^(?P<name>.+?)-(?P<version>[^-]+)(?:-[^-]+)*\.whl$", re.IGNORECASE)


class FixturePrerequisiteError(RuntimeError):
    """A local fixture input cannot satisfy the bounded offline contract."""


def artifact_name(path: Path) -> str:
    try:
        name, _, _, _ = parse_wheel_filename(path.name)
    except Exception as exc:
        raise FixturePrerequisiteError(f"unsupported wheel filename: {path.name}") from exc
    return canonicalize_name(name)


def artifact_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_requirements(project_root: Path) -> list[str]:
    try:
        import tomllib

        config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise FixturePrerequisiteError("project_metadata_invalid: pyproject.toml is unreadable") from exc
    requirements = config.get("build-system", {}).get("requires", [])
    if not isinstance(requirements, list) or not all(isinstance(item, str) and item.strip() for item in requirements):
        raise FixturePrerequisiteError("project_metadata_invalid: build-system requires must be a list")
    return requirements


def offline_install_commands(python: Path, fixture: Path) -> tuple[list[str], list[str]]:
    options = ["--no-index", "--find-links", str(fixture.resolve())]
    bootstrap = [str(python), "-m", "pip", "install", *options, *build_requirements(ROOT)]
    project = [str(python), "-m", "pip", "install", *options, "--no-build-isolation", ".[dev]"]
    return bootstrap, project


def pyproject_requirements(project_root: Path) -> list[str]:
    try:
        import tomllib

        config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise FixturePrerequisiteError("project_metadata_invalid: pyproject.toml is unreadable") from exc
    build_requires = config.get("build-system", {}).get("requires", [])
    dependencies = config.get("project", {}).get("dependencies", [])
    dev_requires = config.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    if not all(isinstance(group, list) for group in (build_requires, dependencies, dev_requires)):
        raise FixturePrerequisiteError("project_metadata_invalid: dependency groups must be lists")
    return [str(requirement) for requirement in [*build_requires, *dependencies, *dev_requires]]


def collect_wheels(source: Path) -> dict[str, Path]:
    if not source.is_dir():
        raise FixturePrerequisiteError("wheel_source_invalid: --wheel-source must be an existing directory")
    wheels: dict[str, Path] = {}
    for candidate in sorted(source.glob("*.whl")):
        name = artifact_name(candidate)
        if name in wheels:
            raise FixturePrerequisiteError(f"wheel_source_invalid: multiple wheels provided for {name}")
        wheels[name] = candidate
    if not wheels:
        raise FixturePrerequisiteError("wheel_source_invalid: no wheels found")
    return wheels


def build_fixture(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FixturePrerequisiteError(f"refusing to overwrite existing output directory: {output}")
    requirements = [Requirement(text) for text in pyproject_requirements(ROOT)]
    wheels = collect_wheels(source)
    missing = sorted({canonicalize_name(requirement.name) for requirement in requirements} - set(wheels))
    if missing:
        raise FixturePrerequisiteError(
            "offline_dependency_closure_unavailable: wheel source lacks declared roots: " + ", ".join(missing)
        )

    output.mkdir(parents=True)
    try:
        for wheel in wheels.values():
            shutil.copy2(wheel, output / wheel.name)
        manifest = {
            "schema": FIXTURE_SCHEMA,
            "project": PROJECT_NAME,
            "required_distributions": sorted(wheels),
            "artifacts": [
                {"filename": wheel.name, "sha256": artifact_digest(output / wheel.name)}
                for wheel in sorted(wheels.values(), key=lambda item: item.name.lower())
            ],
        }
        (output / "fixture-manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        preflight_fixture(output)
        return manifest
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def preflight_fixture(fixture: Path) -> None:
    """Prove the exact isolated-project install contract consumed by the verifier."""
    with tempfile.TemporaryDirectory(prefix="bili-asr-fixture-preflight-") as temp:
        temporary = Path(temp)
        project = temporary / "project"
        shutil.copytree(
            ROOT,
            project,
            ignore=shutil.ignore_patterns(".git", ".venv", ".test-tmp", ".pytest_cache", "__pycache__", "verification-results"),
        )
        venv = temporary / "venv"
        create = subprocess.run([sys.executable, "-m", "venv", str(venv)], cwd=project, capture_output=True, text=True)
        if create.returncode:
            raise FixturePrerequisiteError("isolated_environment_unavailable: Python 3.12 venv/ensurepip support is required")
        scripts = venv / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        bootstrap, command = offline_install_commands(python, fixture)
        bootstrap_proc = subprocess.run(bootstrap, cwd=project, capture_output=True, text=True)
        if bootstrap_proc.returncode:
            raise FixturePrerequisiteError("offline_dependency_closure_unavailable: build backend bootstrap failed")
        proc = subprocess.run(command, cwd=project, capture_output=True, text=True)
        console = scripts / ("bili-asr.exe" if os.name == "nt" else "bili-asr")
    if proc.returncode:
        raise FixturePrerequisiteError("offline_dependency_closure_unavailable: exact project install preflight failed")
    if not console.is_file():
        raise FixturePrerequisiteError("offline_dependency_closure_unavailable: installed console script is missing")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-source", type=Path, required=True, help="curated wheel directory with the full dependency closure")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="run verify_baseline.py after creating the fixture")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        build_fixture(args.wheel_source, args.output)
    except FixturePrerequisiteError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not args.run:
        return 0
    return subprocess.run(
        [
            sys.executable,
            "scripts/verify_baseline.py",
            "--offline-packages",
            str(args.output.resolve()),
            "--advisory-snapshot",
            "tests/fixtures/advisories-empty.json",
        ],
        cwd=ROOT,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
