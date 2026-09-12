"""Contract tests for the host self-check: five named stages, one verdict, no tracebacks.

Every probe is injectable, so the pass and fail paths of all five stages are exercised
here on a machine with no GPU and no ROCm; the real probes stay the default.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from scripts.check_asr_env import (
    CHILD_TIMEOUT_SECONDS,
    CPU_FALLBACK,
    DOC_PATH,
    DXG_ENV,
    HSA_SONAME,
    STAGE_DEVICE,
    STAGE_DXG,
    STAGE_HSA,
    STAGE_ROCM_LOADER,
    STAGE_TORCH,
    STAGES,
    ChildOutcome,
    DeviceInfo,
    ProbeResult,
    Probes,
    classify_device_outcome,
    classify_hsa_runtime,
    classify_torch_outcome,
    discover_rocm_lib_dirs,
    main,
    make_device_probe,
    make_dxg_probe,
    make_hsa_probe,
    make_rocm_loader_probe,
    make_torch_probe,
    parse_child_payload,
    redact_observed,
    report_lines,
    run_checks,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_asr_env.py"
ABORT_LINE = "what(): Found 0 rocprofiler agents and 2 HSA agents, cannot continue"
ABORT_STDERR = (
    "terminate called after throwing an instance of 'std::runtime_error'\n"
    "Traceback (most recent call last):\n"
    '  File "<string>", line 9, in <module>\n'
    "  " + ABORT_LINE + "\n"
)
DEVICE_OK = {
    "probe": "device",
    "available": True,
    "name": "AMD Radeon RX 7800 XT",
    "arch": "gfx1101",
    "vram_gb": 15.8,
    "hip": "7.2.0",
    "hsa_runtime": "/opt/rocm-7.2.1/lib/libhsa-runtime64.so.1",
}
DEVICE_LINE = "check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.0"


@dataclass
class FakeProcess:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _probe(ok: bool, observed: str, detail: dict | None = None) -> Callable[[], ProbeResult]:
    return lambda: ProbeResult(ok, observed, detail or {})


def _device_probe_ok() -> Callable[[], ProbeResult]:
    device = DeviceInfo(name="AMD Radeon RX 7800 XT", arch="gfx1101", vram_gb=15.8, hip="7.2.0")
    return _probe(True, "device=AMD Radeon RX 7800 XT arch=gfx1101", {"device": device})


def _probes(**overrides: Callable[[], ProbeResult]) -> Probes:
    stages: dict[str, Callable[[], ProbeResult]] = {
        "dxg": _probe(True, "dxg_device=present"),
        "rocm_loader": _probe(True, "rocm_lib=/opt/rocm-9.9.9/lib"),
        "torch": _probe(True, "torch=2.9.1 hip=7.2.0"),
        "hsa": _probe(True, f"hsa_runtime=/opt/rocm-9.9.9/lib/{HSA_SONAME}"),
        "device": _device_probe_ok(),
    }
    stages.update(overrides)
    return Probes(**stages)


def _run(argv: list[str], probes: Probes | None = None) -> tuple[int, list[str]]:
    stream = io.StringIO()
    code = main(argv, probes=probes, out=stream)
    return code, stream.getvalue().splitlines()


def _child_payload(**fields: object) -> str:
    return "noise before the payload\n" + json.dumps(fields) + "\n"


# --- the published interface -------------------------------------------------


def test_stage_names_and_order_are_the_published_interface():
    assert STAGES == (STAGE_DXG, STAGE_ROCM_LOADER, STAGE_TORCH, STAGE_HSA, STAGE_DEVICE)
    assert STAGES == ("dxg-detection", "rocm-loader-path", "torch-present", "hsa-runtime", "device-probe")


def test_every_stage_is_injectable_and_reports_its_own_probe_result():
    results = run_checks(_probes())
    assert [result.name for result in results] == list(STAGES)
    assert [result.observed for result in results] == [
        "dxg_device=present",
        "rocm_lib=/opt/rocm-9.9.9/lib",
        "torch=2.9.1 hip=7.2.0",
        f"hsa_runtime=/opt/rocm-9.9.9/lib/{HSA_SONAME}",
        "device=AMD Radeon RX 7800 XT arch=gfx1101",
    ]
    assert all(result.ok for result in results)
    assert report_lines(results)[-1] == "asr-env: verified"


def test_all_stages_pass_prints_the_device_line_then_verified():
    code, lines = _run([], _probes())
    assert code == 0
    assert lines == [
        "check: dxg-detection ok",
        "check: rocm-loader-path ok",
        "check: torch-present ok",
        "check: hsa-runtime ok",
        DEVICE_LINE,
        "asr-env: verified",
    ]


@pytest.mark.parametrize("stage", STAGES)
def test_return_code_is_one_when_a_single_stage_fails(stage: str):
    failing = _probes(**{_probe_field(stage): _probe(False, "observed detail")})
    code, lines = _run([], failing)
    assert code == 1
    assert f"check: {stage} FAIL observed detail" in lines
    assert lines[-1] == "asr-env: not verified (1 failed)"
    assert "asr-env: verified" not in lines


def _probe_field(stage: str) -> str:
    return {
        STAGE_DXG: "dxg",
        STAGE_ROCM_LOADER: "rocm_loader",
        STAGE_TORCH: "torch",
        STAGE_HSA: "hsa",
        STAGE_DEVICE: "device",
    }[stage]


# --- stage 1: dxg-detection --------------------------------------------------


def test_dxg_stage_requires_both_the_device_node_and_the_detection_env(tmp_path: Path):
    device = tmp_path / "dxg"
    device.touch()
    ready = make_dxg_probe(device=device, environ={DXG_ENV: "1"})
    assert ready().ok is True

    assert make_dxg_probe(device=device, environ={})().ok is False
    assert make_dxg_probe(device=tmp_path / "missing", environ={DXG_ENV: "1"})().ok is False
    assert make_dxg_probe(device=tmp_path / "missing", environ={})().ok is False


def test_dxg_stage_observed_names_the_invariant_that_failed(tmp_path: Path):
    device = tmp_path / "dxg"
    device.touch()
    assert make_dxg_probe(device=device, environ={})().observed == f"dxg_device=present {DXG_ENV}=unset"
    assert make_dxg_probe(device=tmp_path / "missing", environ={DXG_ENV: "0"})().observed == (
        f"dxg_device=missing {DXG_ENV}=0"
    )


# --- stage 2: rocm-loader-path ----------------------------------------------


def _rocm_lib(root: Path, version: str = "9.9.9") -> Path:
    directory = root / f"rocm-{version}" / "lib"
    directory.mkdir(parents=True)
    return directory


def test_rocm_loader_path_accepts_a_versioned_dir_on_ld_library_path(tmp_path: Path):
    root = tmp_path / "opt"
    directory = _rocm_lib(root)
    probe = make_rocm_loader_probe(
        ld_library_path=f"/usr/lib:{directory}", ld_conf_dir=tmp_path / "conf", rocm_root=root
    )
    result = probe()
    assert result.ok is True
    assert str(directory) in result.observed


def test_rocm_loader_path_accepts_a_dir_named_by_ld_so_conf_d(tmp_path: Path):
    root = tmp_path / "opt"
    directory = _rocm_lib(root)
    conf_dir = tmp_path / "ld.so.conf.d"
    conf_dir.mkdir()
    (conf_dir / "rocm.conf").write_text(
        f"# ROCm userspace libs\n\n{directory}\n/usr/local/lib\n", encoding="utf-8"
    )
    probe = make_rocm_loader_probe(ld_library_path="", ld_conf_dir=conf_dir, rocm_root=root)
    assert probe().ok is True


def test_rocm_loader_path_rejects_absent_or_unrelated_entries(tmp_path: Path):
    root = tmp_path / "opt"
    _rocm_lib(root)
    unrelated = root / "cuda-1" / "lib"
    unrelated.mkdir(parents=True)
    absent = root / "rocm-1.0.0" / "lib"
    conf_dir = tmp_path / "ld.so.conf.d"
    conf_dir.mkdir()
    (conf_dir / "rocm.conf").write_text(f"{unrelated}\n{absent}\n", encoding="utf-8")

    result = make_rocm_loader_probe(
        ld_library_path=f"{root / 'rocm-9.9.9' / 'lib' / 'missing'}:{tmp_path}",
        ld_conf_dir=conf_dir,
        rocm_root=root,
    )()
    assert result.ok is False
    assert "LD_LIBRARY_PATH" in result.observed and "rocm-*/lib" in result.observed


def test_rocm_loader_path_discovery_never_pins_a_version(tmp_path: Path):
    root = tmp_path / "opt"
    directory = _rocm_lib(root, version="9.9.9")
    discovered = discover_rocm_lib_dirs(f"{directory}", tmp_path / "conf", root=root)
    assert discovered == (directory,)

    source = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"/opt/rocm-\d", source) is None
    assert "/opt/rocm-*/lib" in source


# --- stage 3: torch-present --------------------------------------------------


def test_torch_stage_passes_on_a_rocm_build():
    outcome = ChildOutcome(returncode=0, stdout=_child_payload(probe="torch", torch="2.9.1+rocm7.2.0.lw", hip="7.2.0"))
    result = classify_torch_outcome(outcome, CHILD_TIMEOUT_SECONDS)
    assert result.ok is True
    assert result.observed == "torch=2.9.1+rocm7.2.0.lw hip=7.2.0"


def test_torch_stage_fails_on_a_non_rocm_build_without_torch_version_hip():
    outcome = ChildOutcome(returncode=0, stdout=_child_payload(probe="torch", torch="2.9.1+cpu", hip=None))
    result = classify_torch_outcome(outcome, CHILD_TIMEOUT_SECONDS)
    assert result.ok is False
    assert "hip=absent" in result.observed


def test_torch_stage_fails_when_torch_is_missing():
    outcome = ChildOutcome(
        returncode=0,
        stdout=_child_payload(probe="torch", torch=None, hip=None, error="ModuleNotFoundError: No module named 'torch'"),
    )
    result = classify_torch_outcome(outcome, CHILD_TIMEOUT_SECONDS)
    assert result.ok is False
    assert "ModuleNotFoundError" in result.observed


# --- stage 4: hsa-runtime ----------------------------------------------------


def _torch_lib(tmp_path: Path) -> Path:
    directory = tmp_path / "torch" / "lib"
    directory.mkdir(parents=True)
    return directory


def test_hsa_stage_passes_when_torch_lib_links_out_to_the_system_runtime(tmp_path: Path):
    system = _rocm_lib(tmp_path / "opt")
    (system / HSA_SONAME).write_bytes(b"system hsa runtime")
    torch_lib = _torch_lib(tmp_path)
    (torch_lib / HSA_SONAME).symlink_to(system / HSA_SONAME)

    result = classify_hsa_runtime(torch_lib, (system,))
    assert result.ok is True
    assert "outside torch/lib" in result.observed


def test_hsa_stage_passes_when_torch_lib_holds_a_copy_of_the_system_runtime(tmp_path: Path):
    system = _rocm_lib(tmp_path / "opt")
    (system / f"{HSA_SONAME}.1").write_bytes(b"system hsa runtime")
    torch_lib = _torch_lib(tmp_path)
    (torch_lib / HSA_SONAME).write_bytes(b"system hsa runtime")

    assert classify_hsa_runtime(torch_lib, (system,)).ok is True


def test_hsa_stage_fails_for_the_wheel_bundled_copy(tmp_path: Path):
    system = _rocm_lib(tmp_path / "opt")
    (system / HSA_SONAME).write_bytes(b"system hsa runtime")
    torch_lib = _torch_lib(tmp_path)
    (torch_lib / HSA_SONAME).write_bytes(b"wheel bundled hsa runtime")

    result = classify_hsa_runtime(torch_lib, (system,))
    assert result.ok is False
    assert "torch-bundled copy" in result.observed


def test_hsa_stage_fails_when_no_system_runtime_is_discoverable(tmp_path: Path):
    torch_lib = _torch_lib(tmp_path)
    (torch_lib / HSA_SONAME).write_bytes(b"wheel bundled hsa runtime")
    result = classify_hsa_runtime(torch_lib, (tmp_path / "empty",))
    assert result.ok is False
    assert "torch-bundled copy" in result.observed


def test_hsa_stage_fails_when_torch_lib_carries_no_hsa_runtime(tmp_path: Path):
    result = classify_hsa_runtime(_torch_lib(tmp_path), ())
    assert result.ok is False
    assert f"no {HSA_SONAME}" in result.observed


def test_hsa_stage_fails_when_torch_is_not_importable():
    result = classify_hsa_runtime(None, ())
    assert result.ok is False
    assert "not importable" in result.observed


def test_hsa_probe_uses_the_injected_directories(tmp_path: Path):
    system = _rocm_lib(tmp_path / "opt")
    (system / HSA_SONAME).write_bytes(b"system hsa runtime")
    torch_lib = _torch_lib(tmp_path)
    (torch_lib / HSA_SONAME).write_bytes(b"system hsa runtime")

    assert make_hsa_probe(torch_lib=torch_lib, system_dirs=(system,))().ok is True


# --- stage 5: device-probe ---------------------------------------------------


def test_device_stage_passes_and_names_the_device_it_used():
    result = classify_device_outcome(
        ChildOutcome(returncode=0, stdout=_child_payload(**DEVICE_OK)), CHILD_TIMEOUT_SECONDS
    )
    assert result.ok is True
    assert result.detail["device"] == DeviceInfo(
        name="AMD Radeon RX 7800 XT", arch="gfx1101", vram_gb=15.8, hip="7.2.0"
    )


def test_device_stage_fails_when_no_device_is_available():
    payload = {"probe": "device", "available": False, "hip": "7.2.0", "hsa_runtime": "/usr/lib/libhsa-runtime64.so.1"}
    result = classify_device_outcome(ChildOutcome(returncode=0, stdout=_child_payload(**payload)), 5.0)
    assert result.ok is False
    assert "torch.cuda.is_available() == False" in result.observed
    assert "/usr/lib/libhsa-runtime64.so.1" in result.observed


def test_device_stage_fails_without_a_gcn_arch_name():
    payload = {**DEVICE_OK, "arch": ""}
    result = classify_device_outcome(ChildOutcome(returncode=0, stdout=_child_payload(**payload)), 5.0)
    assert result.ok is False
    assert "gcnArchName" in result.observed


def test_device_stage_fails_when_the_probe_aborts(monkeypatch: pytest.MonkeyPatch):
    import scripts.check_asr_env as checker

    monkeypatch.setattr(
        checker.subprocess, "run", lambda *args, **kwargs: FakeProcess(returncode=-6, stderr=ABORT_STDERR)
    )
    code, lines = _run([], _probes(device=make_device_probe()))
    assert code == 1
    assert f"check: {STAGE_DEVICE} FAIL exit -6: {ABORT_LINE}" in lines
    assert "Traceback" not in "\n".join(lines)


def test_device_stage_fails_when_the_probe_times_out(monkeypatch: pytest.MonkeyPatch):
    import scripts.check_asr_env as checker

    def _timeout(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(checker.subprocess, "run", _timeout)
    result = make_device_probe(timeout=1.0)()
    assert result.ok is False
    assert result.observed == "child did not finish within 1s"


def test_torch_stage_fails_when_the_child_prints_nothing_parseable(monkeypatch: pytest.MonkeyPatch):
    import scripts.check_asr_env as checker

    monkeypatch.setattr(
        checker.subprocess, "run", lambda *args, **kwargs: FakeProcess(returncode=0, stdout="no payload here")
    )
    result = make_torch_probe()()
    assert result.ok is False
    assert "no JSON line" in result.observed


def test_child_payload_parser_reads_the_last_json_line_and_ignores_noise():
    stdout = '{"probe": "other"}\nwarning: something\n{"probe": "device", "available": true}\nnot json\n'
    assert parse_child_payload(stdout, "device") == {"probe": "device", "available": True}
    assert parse_child_payload(stdout, "torch") is None
    assert parse_child_payload("", "device") is None


# --- failure surface ---------------------------------------------------------


def test_observed_text_is_truncated_and_home_redacted():
    home = str(Path.home())
    assert redact_observed(f"boom   at {home}/venv/lib/torch/lib\nsecond line") == "boom at ~/venv/lib/torch/lib second line"
    assert len(redact_observed("x" * 500)) == 200


def test_a_broken_probe_is_a_failure_and_never_a_traceback():
    def _explode() -> ProbeResult:
        raise RuntimeError("probe blew up")

    code, lines = _run([], _probes(torch=_explode))
    assert code == 1
    assert f"check: {STAGE_TORCH} FAIL probe raised RuntimeError: probe blew up" in lines
    assert lines[-1] == "asr-env: not verified (1 failed)"
    assert "Traceback" not in "\n".join(lines)


def test_remediation_matches_the_observed_failure_not_just_the_stage():
    _, lines = _run([], _probes(hsa=lambda: classify_hsa_runtime(None, ())))
    report = "\n".join(lines)
    assert f"check: {STAGE_HSA} FAIL torch/lib is not locatable" in report
    assert "cause: torch is not importable in this interpreter" in report
    assert "repo.radeon.com" in report
    assert report.count(DOC_PATH) == 1


def test_device_remediation_drops_the_cpu_fallback_when_torch_is_missing():
    payload = {"probe": "device", "available": False, "hip": None, "error": "ModuleNotFoundError: No module named 'torch'"}
    result = classify_device_outcome(ChildOutcome(returncode=0, stdout=_child_payload(**payload)), 5.0)
    assert result.remediation is not None
    _, lines = _run([], _probes(device=lambda: result))
    report = "\n".join(lines)
    assert "import failed: ModuleNotFoundError" in report
    assert "cause: torch is not importable in this interpreter" in report
    assert CPU_FALLBACK not in report


def test_hsa_remediation_mentions_the_copy_commands_when_the_bundled_copy_is_present(tmp_path: Path):
    system = _rocm_lib(tmp_path / "opt")
    (system / HSA_SONAME).write_bytes(b"system hsa runtime")
    torch_lib = _torch_lib(tmp_path)
    (torch_lib / HSA_SONAME).write_bytes(b"wheel bundled hsa runtime")

    _, lines = _run([], _probes(hsa=make_hsa_probe(torch_lib=torch_lib, system_dirs=(system,))))
    report = "\n".join(lines)
    assert "wheel-bundled copy, which aborts on WSL" in report
    assert 'cp -f "$ROCM_LIB"/libhsa-runtime64.so* "$TORCH_LIB"/' in report
    assert f'ls -l "$TORCH_LIB"/{HSA_SONAME}*' in report


def test_failure_output_carries_the_cause_the_commands_and_the_doc_once():
    failing = _probes(
        dxg=_probe(False, "dxg_device=missing"),
        rocm_loader=_probe(False, "no rocm lib dir"),
        torch=_probe(False, "hip=absent"),
        hsa=_probe(False, "torch-bundled copy"),
        device=_probe(False, "exit -6: " + ABORT_LINE),
    )
    code, lines = _run([], failing)
    report = "\n".join(lines)

    assert code == 1
    assert lines[-1] == "asr-env: not verified (5 failed)"
    assert lines.count("  recipe: " + DOC_PATH) == 1
    assert report.count(DOC_PATH) == 1
    assert report.count("  cause: ") == 5
    assert report.count("  fix:") == 5
    assert "    export HSA_ENABLE_DXG_DETECTION=1" in report
    assert "ld.so.conf.d/rocm.conf" in report
    assert "repo.radeon.com" in report
    assert "libhsa-runtime64.so" in report
    assert ABORT_LINE in report
    assert CPU_FALLBACK in report


def test_no_output_or_source_recommends_the_pytorch_org_rocm_wheel():
    forbidden = "download.pytorch.org" + "/whl/rocm"
    source = SCRIPT.read_text(encoding="utf-8")
    assert forbidden not in source

    failing = {_probe_field(stage): _probe(False, "observed detail") for stage in STAGES}
    _, lines = _run([], _probes(**failing))
    assert forbidden not in "\n".join(lines)
    assert "repo.radeon.com" in "\n".join(lines)


def test_usage_and_unknown_arguments_do_not_run_the_checks():
    assert _run(["--help"])[0] == 0
    assert "usage: check_asr_env.py" in _run(["--help"])[1][0]
    code, lines = _run(["--nope"])
    assert code == 2
    assert lines[0].startswith("usage: check_asr_env.py")


# --- end to end --------------------------------------------------------------


def test_script_runs_on_this_host_without_a_gpu_or_rocm():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=300, check=False
    )
    output = completed.stdout + completed.stderr
    lines = completed.stdout.splitlines()

    assert completed.returncode in (0, 1), output
    stage_lines = [line for line in lines if line.startswith("check: ")]
    assert len(stage_lines) == 5
    assert [line.split()[1] for line in stage_lines[:4]] == list(STAGES[:4])
    assert re.search(r"^asr-env: (verified|not verified \(\d+ failed\))$", lines[-1], re.MULTILINE)
    assert "Traceback" not in output
    if completed.returncode == 0:
        assert lines[-1] == "asr-env: verified"
        assert any(line.startswith("check: device ok name=") for line in lines)
    else:
        assert lines[-1].startswith("asr-env: not verified (")
        assert f"  recipe: {DOC_PATH}" in lines
