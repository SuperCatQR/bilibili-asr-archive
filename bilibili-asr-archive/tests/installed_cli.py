"""Helpers for installed `bili-asr` console-script verification.

The supported delivery surface is the `bili-asr` console script declared in
`pyproject.toml` (`bili_asr.cli:main`). `python -m bili_asr` is supplemental
source-checkout coverage and is not installation proof.

Finding `bili-asr` next to the test interpreter or on PATH (including a
developer checkout `.venv`) is not isolated-install proof. These helpers
create a temporary virtualenv, install this package into it, and invoke that
venv's console script.

Missing-install policy: fail the test (never pytest.skip / xfail) with a named
prerequisite. Automated verification must not go green because a console
script was absent.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
import sys
from typing import Mapping

import pytest

PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(PACKAGE_ROOT, "src")
CHECKOUT_VENV_SCRIPT = os.path.join(PACKAGE_ROOT, ".venv", "bin", "bili-asr")

SENTINEL_COOKIE = "cli-verify-sentinel-cookie-9f3a2c"

_FORBIDDEN_OUTPUT_FRAGMENTS = (
    SENTINEL_COOKIE,
    "Traceback (most recent call last)",
    "upos-sz-",
    "bilivideo.com",
    "deadline=",
)

_BUILD_ARTIFACTS = (
    "build",
    "dist",
    os.path.join("src", "bili_asr.egg-info"),
    "bili_asr.egg-info",
)

PREREQUISITE_HELP = """\
Installed-entrypoint verification prerequisite failed: {reason}

Required:
  - Python 3.12 interpreter (this project's supported verification environment)
  - a tool that can create an isolated virtualenv (uv, or python -m venv + pip)
  - a local, offline install of this package that provides the `bili-asr`
    console script inside that virtualenv

This check does not skip. Isolated verification (no live HTTP / model download):

  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -e ".[dev]"
  .venv/bin/pytest tests/test_cli_help.py tests/test_installed_cli.py

The tests themselves provision a separate temporary virtualenv; a `bili-asr`
already present in the developer checkout is not a substitute.

`python -m bili_asr` remaining green is not a substitute for the installed
console script.
"""


@dataclass(frozen=True)
class InstalledCLI:
    """A real console-script install in an isolated venv."""

    executable: str
    python: str
    venv_dir: str
    version_info: tuple[int, int]


def _fail_prereq(reason: str) -> None:
    pytest.fail(PREREQUISITE_HELP.format(reason=reason), pytrace=False)


def require_python_312(version_info: tuple[int, ...] | None = None) -> tuple[int, int]:
    info = version_info if version_info is not None else sys.version_info
    major, minor = int(info[0]), int(info[1])
    if (major, minor) != (3, 12):
        _fail_prereq(
            f"Python {major}.{minor} is not the supported 3.12 verification interpreter"
        )
    return major, minor


def _venv_python(venv_dir: str) -> str:
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _venv_script(venv_dir: str, name: str) -> str:
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", f"{name}.exe")
    return os.path.join(venv_dir, "bin", name)


def _find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    override = os.environ.get("BILI_ASR_UV") or os.environ.get("UV_BIN")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    home_uv = os.path.expanduser("~/.local/bin/uv")
    if os.path.isfile(home_uv) and os.access(home_uv, os.X_OK):
        return home_uv
    return None


def _redact_line(text: str) -> str:
    line = text.replace(SENTINEL_COOKIE, "[redacted]").strip()
    return line[:240]


def _summarize(proc: subprocess.CompletedProcess[str]) -> str:
    blob = (proc.stderr or proc.stdout or "").strip().splitlines()
    if not blob:
        return f"exit {proc.returncode}"
    return _redact_line(blob[-1])


def _run(
    cmd: list[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else None,
        cwd=cwd or PACKAGE_ROOT,
    )


def _offline_tool_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    drop = {
        "PYTHONPATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "BILI_SESSDATA",
    }
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PYTHONNOUSERSITE"] = "1"
    env["UV_OFFLINE"] = "1"
    env["UV_LINK_MODE"] = "copy"
    env["UV_NO_PROGRESS"] = "1"
    env["PIP_NO_INDEX"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    if extra:
        env.update(extra)
    return env


def clean_cli_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for CLI subprocesses: no PYTHONPATH, no live-proxy, sentinel cookie."""
    drop = {
        "PYTHONPATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    }
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PYTHONNOUSERSITE"] = "1"
    env["BILI_SESSDATA"] = SENTINEL_COOKIE
    if extra:
        env.update(extra)
    return env


def cleanup_build_artifacts(root: str = PACKAGE_ROOT) -> None:
    for rel in _BUILD_ARTIFACTS:
        path = os.path.join(root, rel)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _ignore_pycache(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}


def _stage_sources(staging_dir: str) -> str:
    """Copy packaging inputs so the install cannot be confused with the checkout venv."""
    pkg = os.path.join(staging_dir, "pkg")
    if os.path.isdir(pkg):
        shutil.rmtree(pkg, ignore_errors=True)
    os.makedirs(pkg, exist_ok=True)
    shutil.copytree(
        SRC_DIR,
        os.path.join(pkg, "src"),
        ignore=_ignore_pycache,
    )
    shutil.copy2(os.path.join(PACKAGE_ROOT, "pyproject.toml"), pkg)
    shutil.copy2(os.path.join(PACKAGE_ROOT, "README.md"), pkg)
    return pkg


def _provision_with_uv(uv: str, venv_dir: str, staged_pkg: str) -> None:
    env = _offline_tool_env()
    created = _run([uv, "venv", "--python", "3.12", venv_dir], env=env)
    if created.returncode != 0:
        _fail_prereq(f"uv venv failed ({_summarize(created)})")
    python = _venv_python(venv_dir)
    installed = _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            python,
            "--offline",
            "--no-deps",
            staged_pkg,
        ],
        env=env,
        cwd=staged_pkg,
    )
    if installed.returncode != 0:
        _fail_prereq(
            "offline uv pip install of this package failed "
            f"({_summarize(installed)})"
        )


def _provision_with_stdlib_venv(venv_dir: str, staged_pkg: str) -> None:
    env = _offline_tool_env()
    created = _run([sys.executable, "-m", "venv", venv_dir], env=env)
    if created.returncode != 0:
        _fail_prereq(
            "python -m venv failed and uv was not found "
            f"({_summarize(created)})"
        )
    python = _venv_python(venv_dir)
    pip_probe = _run([python, "-m", "pip", "--version"], env=env)
    if pip_probe.returncode != 0:
        _fail_prereq(
            "isolated venv has no pip (ensurepip unavailable); install uv "
            f"({_summarize(pip_probe)})"
        )
    installed = _run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            staged_pkg,
        ],
        env=env,
        cwd=staged_pkg,
    )
    if installed.returncode != 0:
        _fail_prereq(
            "offline pip install of this package failed "
            f"({_summarize(installed)})"
        )


def _assert_isolated_script(venv_dir: str, executable: str) -> None:
    real_exe = os.path.realpath(executable)
    real_venv = os.path.realpath(venv_dir)
    try:
        common = os.path.commonpath([real_exe, real_venv])
    except ValueError:
        common = ""
    if common != real_venv:
        _fail_prereq(
            "installed 'bili-asr' console script is not inside the isolated venv"
        )
    if os.path.isfile(CHECKOUT_VENV_SCRIPT):
        if real_exe == os.path.realpath(CHECKOUT_VENV_SCRIPT):
            _fail_prereq(
                "console script resolved to the developer checkout venv, "
                "not the isolated install"
            )


def provision_isolated_cli(venv_dir: str) -> InstalledCLI:
    """Install this package into ``venv_dir`` and return the console script.

    Intentionally fails (does not skip) when the isolated install cannot be
    created or ``bili-asr`` is missing afterwards. Does not treat a checkout
    or PATH script as proof.
    """
    require_python_312()
    parent = os.path.dirname(os.path.abspath(venv_dir))
    os.makedirs(parent, exist_ok=True)
    if os.path.exists(venv_dir):
        shutil.rmtree(venv_dir, ignore_errors=True)

    uv = _find_uv()
    staging_root = os.path.abspath(venv_dir) + "-src"
    staged_pkg: str | None = None
    try:
        staged_pkg = _stage_sources(staging_root)
        if uv:
            _provision_with_uv(uv, venv_dir, staged_pkg)
        else:
            _provision_with_stdlib_venv(venv_dir, staged_pkg)

        python = _venv_python(venv_dir)
        if not os.path.isfile(python):
            _fail_prereq(f"isolated venv python missing at {python}")

        version_proc = _run(
            [
                python,
                "-c",
                "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
            ],
            env=_offline_tool_env(),
        )
        if version_proc.returncode != 0:
            _fail_prereq(
                f"isolated venv python could not report its version ({_summarize(version_proc)})"
            )
        reported = (version_proc.stdout or "").strip()
        if reported != "3.12":
            _fail_prereq(
                f"isolated venv Python {reported or 'unknown'} is not the supported 3.12 interpreter"
            )

        executable = _venv_script(venv_dir, "bili-asr")
        if not os.path.isfile(executable):
            _fail_prereq(
                "isolated install did not produce the 'bili-asr' console script"
            )
        _assert_isolated_script(venv_dir, executable)
        return InstalledCLI(
            executable=executable,
            python=python,
            venv_dir=venv_dir,
            version_info=(3, 12),
        )
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
        cleanup_build_artifacts(PACKAGE_ROOT)
        if staged_pkg:
            cleanup_build_artifacts(staged_pkg)


def run_installed(
    cli: InstalledCLI,
    args: list[str],
    *,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = clean_cli_env(extra_env)
    env["PATH"] = os.path.dirname(cli.executable) + os.pathsep + os.defpath
    return subprocess.run(
        [cli.executable, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cli.venv_dir,
    )


def run_module(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Supplemental ``python -m bili_asr`` coverage (source checkout, not install proof)."""
    env = clean_cli_env({"PYTHONPATH": SRC_DIR})
    return subprocess.run(
        [sys.executable, "-m", "bili_asr", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=PACKAGE_ROOT,
    )


def combined_output(proc: subprocess.CompletedProcess[str]) -> str:
    return f"{proc.stdout or ''}{proc.stderr or ''}"


def assert_redacted(proc: subprocess.CompletedProcess[str]) -> None:
    blob = combined_output(proc)
    for fragment in _FORBIDDEN_OUTPUT_FRAGMENTS:
        assert fragment not in blob, f"CLI output leaked {fragment!r}"
