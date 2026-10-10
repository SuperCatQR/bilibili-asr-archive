"""Read-only deployment evidence. No Torch import or model execution by default."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import ntpath
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

from .config import ASRConfig


PACKAGES = ("bili-asr", "torch", "transformers", "accelerate", "numpy", "soundfile", "soxr", "triton")


def installed_versions() -> dict[str, str | None]:
    result = {}
    for name in PACKAGES:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def _checkpoint(path: str, revision: str | None) -> dict:
    local = Path(path)
    explicit_local = local.exists() or local.is_absolute() or ntpath.isabs(path) or path.startswith(("./", "../", ".\\", "..\\"))
    return {"kind": "local" if explicit_local else "unverified",
            "readable": local.is_dir() and os.access(local, os.R_OK),
            "config_present": (local / "config.json").is_file(),
            "revision_declared": revision is not None, "identity": "unverified"}


def deployment_report(config: ASRConfig, *, backend: str, cache_root: str | None = None,
                      check_gpu: bool = False, timeout_seconds: float = 20) -> dict:
    """Inspect configuration; an explicit probe runs only allocation/arithmetic."""
    if backend not in ("cuda", "rocm", "hcu"):
        raise ValueError("unsupported deployment backend")
    if re.fullmatch(r"(?:cpu|cuda|rocm)(?::[0-9]+)?", config.device) is None:
        raise ValueError("deployment device must be a device identifier")
    if not 0 < timeout_seconds <= 300:
        raise ValueError("probe timeout must be within 0..300 seconds")
    packages = installed_versions()
    report = {"schema_version": 1, "state": "configured", "backend_requested": backend,
              "python": platform.python_version(), "os": platform.system(), "packages": packages,
              "configured_device": config.device, "model_dtype": config.model_dtype,
              "aligner_dtype": config.aligner_dtype,
              "model": _checkpoint(config.model_name, config.model_revision),
              "aligner": _checkpoint(config.aligner_name, config.aligner_revision),
              "model_execution": "not_run", "gpu": {"status": "unverified"},
              "cache": {"configured": cache_root is not None, "state": "unverified"}}
    missing = [name for name in ("torch", "transformers", "accelerate") if packages[name] is None]
    report["missing_packages"] = missing
    if cache_root is not None:
        root = Path(cache_root)
        report["cache"].update(exists=root.is_dir(), readable=os.access(root, os.R_OK),
                               writable=os.access(root, os.W_OK), symlink=root.is_symlink())
    if check_gpu:
        command = [sys.executable, "-m", "bili_asr.asr.device_probe", "--backend", backend,
                   "--device", config.device, "--dtype", config.model_dtype, "--dtype", config.aligner_dtype]
        try:
            child = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
            payload = json.loads(child.stdout)
            # Accept only known fields; stderr and arbitrary child text are never exported.
            allowed = {"status", "backend", "torch", "cuda", "hip", "device",
                       "precision_execution", "model_execution", "error_type"}
            if not isinstance(payload, dict) or set(payload) - allowed or payload.get("status") not in ("passed", "failed"):
                raise ValueError("invalid device report")
            report["gpu"] = payload if child.returncode == 0 else {"status": "failed", "reason": "device_probe_failed"}
        except subprocess.TimeoutExpired:
            report["gpu"] = {"status": "failed", "reason": "device_probe_timeout"}
        except (OSError, ValueError):
            report["gpu"] = {"status": "failed", "reason": "device_probe_failed"}
    report["state"] = "unverified" if not missing else "blocked"
    if config.offline and any(report[name]["kind"] == "local" and
                              (not report[name]["config_present"] or not report[name]["readable"])
                              for name in ("model", "aligner")):
        report["state"] = "blocked"
    if report["gpu"]["status"] == "failed":
        report["state"] = "blocked"
    # Deliberately no ready claim: neither offline inspection nor a tensor
    # probe has loaded both models or completed an ASR/alignment sentinel.
    return report


def cache_identity(config: ASRConfig, *, hardware: dict, packages: dict | None = None) -> dict:
    """Compatibility namespace; callers supply actual hardware, never infer it from 'cuda'."""
    values = asdict(config)
    # Device/model paths and secrets must not enter a public manifest. Their
    # digest still prevents accidental cross-configuration cache reuse.
    return {"schema_version": 1, "config_sha256": hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
        "hardware": hardware, "packages": packages if packages is not None else installed_versions(),
        "python": platform.python_version()}
