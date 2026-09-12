"""Deterministic local lifecycle oracles for the optional ASR boundary."""

from __future__ import annotations

import builtins
import json
import os
import pathlib
import sys
import types
from typing import Any

import pytest

from bili_asr import asr
from bili_asr import coordinator
from bili_asr.coordinator import RunCoordinator
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity


def _audio_row(identity, *, status="audio_ok"):
    """One manifest row the offline coordinator routes straight to ASR."""
    return {
        "bvid": identity.bvid,
        "work_id": identity.work_id,
        "page_index": identity.page_index,
        "cid": identity.cid,
        "page_label": identity.page_label,
        "status": status,
        "title": "batch-clip",
        "duration_s": 5,
        "pubdate": 1,
        "pubdate_str": "2026-01-02",
    }


def _seed_audio_batch(root, count, *, prefix="BVbatch"):
    """`count` audio_ok rows with their audio on disk; returns (store, rows)."""
    store = ManifestStore(root=root)
    identities = [
        page_identity(f"{prefix}{index}", 0, 100 + index, "p0")
        for index in range(count)
    ]
    audio_dir = pathlib.Path(root) / "audio"
    audio_dir.mkdir(exist_ok=True)
    for identity in identities:
        store.upsert(_audio_row(identity))
        (audio_dir / f"{artifact_stem(identity)}.m4a").write_bytes(b"fixture")
    return store, [(i.work_id, store.get(i.work_id)) for i in identities]


@pytest.fixture
def counted_batch_seam(monkeypatch, fake_funasr):
    """The D2.5 seam: the counted factory sits on `_load_default_model`.

    Patching the module-level factory (not `ASRRunner`) keeps the real
    `_get_model` path under test, so the counter a batch reports is the
    counter the production construction site would have produced.
    """

    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setattr(asr, "_load_default_model", fake_funasr)
    return fake_funasr


class FakeAutoModel:
    construction_count = 0
    construction_records: list[dict[str, object]] = []
    generation_records: list[dict[str, object]] = []

    def __init__(self, **kwargs):
        type(self).construction_count += 1
        type(self).construction_records.append(dict(kwargs))

    def generate(self, **kwargs):
        type(self).generation_records.append(dict(kwargs))
        return [{"text": "deterministic output", "timestamps": [
            {"token": "deterministic", "start_time": 0.125, "end_time": 1.5, "score": 0.9},
            {"token": " output", "start_time": 3.0, "end_time": 4.25, "score": 0.8},
        ]}]


@pytest.fixture
def fake_funasr(monkeypatch):
    FakeAutoModel.construction_count = 0
    FakeAutoModel.construction_records = []
    FakeAutoModel.generation_records = []
    
    # Mock torch to report CUDA is available
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    return FakeAutoModel


def test_fake_model_result_normalization_timestamps_and_rich_tag_cleanup(fake_funasr):
    assert asr.transcribe("fixture-audio.wav", model_name="local-test-model") == [
        {"start": 0.125, "end": 1.5, "text": "deterministic", "confidence": 0.9},
        {"start": 3.0, "end": 4.25, "text": "output", "confidence": 0.8},
    ]
    assert fake_funasr.construction_records == [{
        "model": "local-test-model", "device": "cuda", "trust_remote_code": False,
        "vad_model": "fsmn-vad", "vad_kwargs": {"max_single_segment_time": 30_000},
    }]
    assert fake_funasr.generation_records == [{
        "input": "fixture-audio.wav", "cache": {}, "itn": True,
        "hotwords": list(asr.DEFAULT_HOTWORDS),
    }]


def test_empty_and_malformed_results_are_ignored():
    assert asr.normalize_result([]) == []
    assert asr.normalize_result([None, "bad", {}, {"text": ""}]) == []
    assert asr.normalize_result({"text": "plain", "timestamp": []}) == [
        {"start": 0.0, "end": 0.0, "text": "plain"}
    ]
    # only the pinned shape is read; a foreign one is ignored rather than guessed
    assert asr.normalize_result({"sentences": [{"start": 10, "end": 20, "text": "<|en|>ok"}]}) == []
    assert asr.normalize_result({"text": "<|en|>ok"}) == [{"start": 0.0, "end": 0.0, "text": "ok"}]


def test_fake_generation_snapshots_include_both_input_paths(fake_funasr, monkeypatch):
    monkeypatch.setenv("BILI_ASR_MODEL", "/fixture/local-model")
    first = asr.transcribe("one.wav")
    second = asr.transcribe("two.wav")
    assert first == second
    assert fake_funasr.construction_count == 2
    assert [record["input"] for record in fake_funasr.generation_records] == ["one.wav", "two.wav"]
    assert fake_funasr.construction_records == [{
        "model": "/fixture/local-model", "device": "cuda", "trust_remote_code": False,
        "vad_model": "fsmn-vad", "vad_kwargs": {"max_single_segment_time": 30_000},
    }] * 2


def test_error_serialization_redacts_forbidden_markers_and_preserves_class(monkeypatch):
    hostile_message = (
        "SESSDATA cookie token signed-url raw exception /tmp/private.wav "
        "model-bytes media-bytes"
    )

    class ExplodingModel:
        def __init__(self, **_kwargs):
            raise RuntimeError(hostile_message)

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(
        sys.modules, "funasr", types.SimpleNamespace(AutoModel=ExplodingModel)
    )
    with pytest.raises(asr.ASRModelError) as caught:
        asr.transcribe("/tmp/private.wav")
    assert isinstance(caught.value, asr.ASRModelError)
    assert isinstance(asr.ASRDependencyError("missing"), asr.ASRDependencyError)

    record = coordinator._validate_attempt(
        {
            "stage": "asr",
            "work_id": "BVfixture.p0",
            "attempt": 1,
            "outcome": "failed",
            "error_code": caught.value.__class__.__name__,
            "artifact_paths": [],
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
        }
    )
    serialized = json.dumps(record)
    forbidden_markers = (
        "SESSDATA", "cookie", "token", "signed-url", "raw exception",
        "/tmp/private.wav", "model-bytes", "media-bytes",
    )
    assert all(marker.lower() not in serialized.lower() for marker in forbidden_markers)
    assert "ASRModelError" in serialized


def test_download_helpers_are_not_called_and_submodule_imports_are_blocked(monkeypatch, fake_funasr):
    calls: list[str] = []
    for helper_name in ("download_model", "download_audio"):
        monkeypatch.setattr(
            asr, helper_name, lambda name=helper_name: calls.append(name), raising=False
        )
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "socket" or name.startswith(("socket.", "modelscope.", "requests.")):
            raise AssertionError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert asr.transcribe("fixture.wav")
    assert calls == []


def test_config_rejects_hostile_values_and_provenance_is_redacted():
    for field, value in (("model_name", ""), ("model_revision", ""), ("device", ""), ("local_source", "prefix token=secret"), ("local_source", "C:\\\\private")):
        values = {"model_name": "safe", "model_revision": None, "device": "cpu", "offline": True, "local_source": "configured-local"}
        values[field] = value
        with pytest.raises((ValueError, TypeError)):
            asr.ASRConfig(**values)


def test_factory_gets_exact_kwargs_and_typeerror_is_not_retried(monkeypatch):
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        raise TypeError("hostile secret")
    
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    
    runner = asr.ASRRunner(asr.ASRConfig("model", model_revision="rev"), model_factory=factory)
    with pytest.raises(asr.ASRModelError) as caught:
        runner.transcribe("fixture.wav")
    assert len(calls) == 1
    assert set(calls[0]) == {
        "model", "device", "trust_remote_code", "model_revision",
        "vad_model", "vad_kwargs",
    }
    assert "hostile" not in str(caught.value)


def test_current_transcribe_constructs_once_per_call_characterization(fake_funasr):
    asr.transcribe("first.wav")
    asr.transcribe("second.wav")
    assert fake_funasr.construction_count == 2


def test_target_runner_reuse_oracle_is_target_facing(fake_funasr):
    """Target contract: one runner owns one model across all input paths."""
    runner = asr.ASRRunner(
        asr.ASRConfig(model_name="local-test-model"), model_factory=fake_funasr
    )
    outputs = [runner.transcribe(path) for path in ("first.wav", "second.wav")]
    assert outputs
    assert fake_funasr.construction_count == 1
    assert [record["input"] for record in fake_funasr.generation_records] == [
        "first.wav", "second.wav"
    ]


def test_runner_release_dereferences_owned_model(fake_funasr):
    runner = asr.ASRRunner(
        asr.ASRConfig(model_name="local-test-model"), model_factory=fake_funasr
    )
    runner.transcribe("fixture.wav")

    runner.release()

    assert runner._model is None


def test_provenance_has_stable_redacted_configuration_keys():
    config = asr.ASRConfig(
        model_name="local-model",
        model_revision="revision-1",
        device="cpu",
        language="中文",
        hotwords=("a", "b"),
        offline=True,
        local_source="configured-local",
    )
    provenance = asr.ASRRunner(config).provenance()
    assert list(provenance) == [
        "model_name", "model_revision", "device", "language", "vad_model",
        "vad_max_segment_s", "hotwords", "offline", "local_source",
    ]
    assert provenance == {
        "model_name": "local-model",
        "model_revision": "revision-1",
        "device": "cpu",
        "language": "中文",
        "vad_model": "fsmn-vad",
        "vad_max_segment_s": "30.0",
        "hotwords": "a,b",
        "offline": "True",
        "local_source": "configured-local",
    }
    assert all(isinstance(value, str) for value in provenance.values())


def test_provenance_is_deterministic_and_revision_sensitive():
    def make_provenance(revision: str | None) -> dict[str, str]:
        return asr.ASRRunner(
            asr.ASRConfig("fixture-model", model_revision=revision)
        ).provenance()

    assert make_provenance("rev-a") == make_provenance("rev-a")
    assert make_provenance("rev-a") != make_provenance("rev-b")
    assert make_provenance(None) != make_provenance("rev-a")


def test_provenance_preserves_safe_slash_qualified_model_identifier():
    provenance = asr.ASRRunner(asr.ASRConfig("FunAudioLLM/Fun-ASR-Nano-2512")).provenance()

    assert provenance["model_name"] == "FunAudioLLM/Fun-ASR-Nano-2512"


@pytest.mark.parametrize(
    "model_name",
    (
        "/opt/models/Fun-ASR-Nano-2512",
        "C:\\models\\Fun-ASR-Nano-2512",
        "https://models.example/Fun-ASR-Nano-2512",
        "token=private-model",
    ),
)
def test_provenance_redacts_path_url_and_credential_like_model_values(model_name):
    provenance = asr.ASRRunner(asr.ASRConfig(model_name)).provenance()

    assert provenance["model_name"] == "[redacted]"
    assert model_name not in json.dumps(provenance)


def test_environment_model_path_is_runtime_only_and_not_exposed_in_provenance(
    fake_funasr, monkeypatch
):
    local_model_path = "/fixture/private-model"
    observed_provenance = []
    original_provenance = asr.ASRRunner.provenance

    def capture_provenance(runner):
        provenance = original_provenance(runner)
        observed_provenance.append(provenance)
        return provenance

    original_transcribe = asr.ASRRunner.transcribe

    def inspect_then_transcribe(runner, audio_path):
        capture_provenance(runner)
        return original_transcribe(runner, audio_path)

    monkeypatch.setattr(asr.ASRRunner, "transcribe", inspect_then_transcribe)
    monkeypatch.setenv("BILI_ASR_MODEL", local_model_path)

    asr.transcribe("fixture.wav")

    assert fake_funasr.construction_records[0]["model"] == local_model_path
    assert observed_provenance[0]["model_name"] == "[redacted]"
    assert local_model_path not in json.dumps(observed_provenance)


def test_provenance_redacts_forbidden_values_without_serializing_payloads():
    config = asr.ASRConfig("fixture-model", model_revision="rev-a")
    runner = asr.ASRRunner(config)
    safe = runner.provenance()
    forbidden_markers = (
        "SESSDATA", "cookie", "token", "http://", "https://", "Traceback",
        "/tmp/", "model-bytes", "media-bytes", "transcript-payload",
    )
    serialized = json.dumps(safe)
    assert all(marker.lower() not in serialized.lower() for marker in forbidden_markers)


def test_fixture_benchmark_reports_only_construction_and_shape(fake_funasr):
    runner = asr.ASRRunner(asr.ASRConfig("fixture-model"), model_factory=fake_funasr)
    outputs = [runner.transcribe(path) for path in ("first.wav", "second.wav")]
    report: dict[str, Any] = {
        "model_construction_count": fake_funasr.construction_count,
        "normalized_segment_count": sum(len(output) for output in outputs),
        "output_shape": sorted(outputs[0][0]),
    }
    assert report == {
        "model_construction_count": 1,
        "normalized_segment_count": 4,
        "output_shape": ["confidence", "end", "start", "text"],
    }
    assert set(report) == {
        "model_construction_count", "normalized_segment_count", "output_shape"
    }


def test_cuda_unavailable_raises_dependency_error_with_rocm_hint(monkeypatch):
    """The device hint points at the check and the recipe, never at a wheel index."""
    class FakeTorch:
        @staticmethod
        def cuda_is_available():
            return False
        
        class cuda:
            @staticmethod
            def is_available():
                return False
    
    monkeypatch.setitem(sys.modules, "torch", FakeTorch)
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=lambda **kw: None))
    
    runner = asr.ASRRunner(asr.ASRConfig("test-model", device="cuda"))
    with pytest.raises(asr.ASRDependencyError) as caught:
        runner.transcribe("fixture.wav")
    
    error_message = str(caught.value)
    assert "CUDA/ROCm is not available" in error_message
    # D1.6: exactly these stable pointer tokens, and no vendor index URL.  The
    # broken PyTorch.org ROCm wheel must not come back through this message; the
    # literal is assembled so this file does not itself carry the dead-end URL.
    assert "ROCm" in error_message
    assert "scripts/check_asr_env.py" in error_message
    assert "docs/wsl-rocm-gpu.md" in error_message
    assert "BILI_ASR_DEVICE=cpu" in error_message
    # N-1: the hint must publish the check the way the check's own fix text and
    # docs/wsl-rocm-gpu.md do — the venv interpreter that holds torch.  A bare
    # `python3.12` invocation probes the *system* interpreter and reports a false
    # `torch-present FAIL` on a host built exactly as the recipe says, so the
    # token is banned from this surface entirely, not merely discouraged.
    # N-2: the hint is a human-readable exception message, not a paste-into-bash
    # block, so it names the venv's interpreter in plain language and keeps only
    # the runnable command.  The `${VENV:?…}` shell-expansion form stays in the
    # code blocks of README.md / docs/wsl-rocm-gpu.md, where a shell expands it.
    assert '"$VENV/bin/python" scripts/check_asr_env.py' in error_message
    assert "${VENV:" not in error_message
    assert "venv's interpreter" in error_message
    assert "python3.12" not in error_message
    assert "python3.12 scripts/check_asr_env.py" not in error_message
    assert ("download.pytorch.org" + "/whl/rocm") not in error_message
    assert "http://" not in error_message and "https://" not in error_message
    # No machine-specific layout either: the hint must not name one host's paths.
    assert "/opt/rocm" not in error_message
    assert "/root/" not in error_message and "/home/" not in error_message


def test_device_hint_doc_path_resolves_in_the_checkout():
    """Drift guard: the doc the hint names must exist in this checkout.

    Only the documented path is asserted. `scripts/` is not part of the installed
    distribution and the verification baseline stages `docs/` without it, so a
    check on the script's own path would be a property of one tree layout.
    """
    package_root = pathlib.Path(__file__).resolve().parents[1]
    assert (package_root / "docs" / "wsl-rocm-gpu.md").is_file()


def test_torch_import_error_raises_dependency_error(monkeypatch):
    """Missing torch should raise ASRDependencyError when device is cuda."""
    def fail_torch_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("No module named 'torch'")
        return builtins.__import__(name, *args, **kwargs)
    
    monkeypatch.setattr(builtins, "__import__", fail_torch_import)
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=lambda **kw: None))
    
    runner = asr.ASRRunner(asr.ASRConfig("test-model", device="cuda"))
    with pytest.raises(asr.ASRDependencyError) as caught:
        runner.transcribe("fixture.wav")
    
    error_message = str(caught.value)
    assert "PyTorch is required" in error_message or "torch" in error_message.lower()


def test_cpu_override_skips_gpu_check(fake_funasr):
    """CPU device should work without CUDA availability check."""
    runner = asr.ASRRunner(asr.ASRConfig("test-model", device="cpu"), model_factory=fake_funasr)
    result = runner.transcribe("fixture.wav")
    
    assert result == [
        {"start": 0.125, "end": 1.5, "text": "deterministic", "confidence": 0.9},
        {"start": 3.0, "end": 4.25, "text": "output", "confidence": 0.8},
    ]
    assert fake_funasr.construction_records[0]["device"] == "cpu"


def test_default_config_reads_the_documented_environment_knobs(monkeypatch):
    monkeypatch.setenv("BILI_ASR_MODEL", "/opt/checkpoints/nano")
    monkeypatch.setenv("BILI_ASR_MODEL_REVISION", "rev-9")
    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")
    monkeypatch.setenv("BILI_ASR_LANGUAGE", "中文")
    monkeypatch.setenv("BILI_ASR_VAD_MODEL", "fsmn-vad")

    config = asr.default_config()

    assert config.model_name == "/opt/checkpoints/nano"
    assert config.model_revision == "rev-9"
    assert config.device == "cpu"
    assert config.language == "中文"
    assert config.vad_model == "fsmn-vad"


def test_vad_is_the_default_and_a_blank_knob_disables_it(monkeypatch):
    """Long recordings need the VAD; an explicit blank turns that pipeline off."""

    monkeypatch.delenv("BILI_ASR_VAD_MODEL", raising=False)
    assert asr.default_config().vad_model == "fsmn-vad"

    monkeypatch.setenv("BILI_ASR_VAD_MODEL", "   ")
    assert asr.default_config().vad_model is None


def test_no_vad_configured_omits_the_component_from_the_construction(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", vad_model=None), model_factory=fake_funasr
    ).transcribe("fixture.wav")

    assert fake_funasr.construction_records == [
        {"model": "test-model", "device": "cpu", "trust_remote_code": False}
    ]


@pytest.mark.skipif(not os.path.exists("/proc/self/fd"), reason="descriptor paths are POSIX")
def test_confined_descriptor_input_is_materialized_for_component_subprocesses(tmp_path):
    """The VAD component shells out to ffmpeg, which cannot open a cloexec fd."""

    payload = b"fake audio payload"
    real = tmp_path / "clip.m4a"
    real.write_bytes(payload)
    seen: list[bytes] = []

    class ReadingModel:
        def __init__(self, **_kwargs):
            pass

        def generate(self, **kwargs):
            with open(kwargs["input"], "rb") as handle:
                seen.append(handle.read())
            return [{"text": "ok", "timestamp": []}]

    descriptor = None
    fd = os.open(real, os.O_RDONLY)
    try:
        descriptor = f"/proc/self/fd/{fd}"
        segments = asr.ASRRunner(
            asr.ASRConfig("test-model", device="cpu"), model_factory=ReadingModel
        ).transcribe(descriptor)
    finally:
        os.close(fd)

    assert segments == [{"start": 0.0, "end": 0.0, "text": "ok"}]
    assert seen == [payload]
    assert descriptor is not None


def test_a_plain_path_is_never_copied(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu"), model_factory=fake_funasr
    ).transcribe("fixture.wav")

    assert fake_funasr.generation_records[0]["input"] == "fixture.wav"


def test_default_config_defaults_are_unchanged_without_the_knobs(monkeypatch):
    for name in ("BILI_ASR_MODEL", "BILI_ASR_MODEL_REVISION", "BILI_ASR_DEVICE", "BILI_ASR_LANGUAGE"):
        monkeypatch.delenv(name, raising=False)

    config = asr.default_config()

    assert config.model_name == asr.DEFAULT_MODEL
    assert config.model_revision is None
    assert config.device == "cuda"
    assert config.language is None


def test_configured_language_is_passed_and_absent_language_is_not(fake_funasr):
    """`language` is prompt text for Nano, so only a configured value is sent."""

    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", language="中文"), model_factory=fake_funasr
    ).transcribe("one.wav")
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu"), model_factory=fake_funasr
    ).transcribe("two.wav")

    assert fake_funasr.generation_records == [
        {"input": "one.wav", "cache": {}, "itn": True, "language": "中文"},
        {"input": "two.wav", "cache": {}, "itn": True},
    ]


def test_config_rejects_a_blank_language():
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", language="   ")
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", language=7)  # type: ignore[arg-type]


def test_hotwords_travel_to_the_model_and_are_recorded(monkeypatch, fake_funasr):
    """Configured terms bias decoding and are visible in provenance."""

    monkeypatch.setenv("BILI_ASR_HOTWORDS", "马恩牌, 未明子,劳动仲裁,劳动仲裁")
    config = asr.default_config()

    assert config.hotwords[: len(asr.DEFAULT_HOTWORDS)] == asr.DEFAULT_HOTWORDS
    assert config.hotwords[len(asr.DEFAULT_HOTWORDS):] == ("劳动仲裁",)

    asr.ASRRunner(config, model_factory=fake_funasr).transcribe("fixture.wav")

    assert fake_funasr.generation_records[0]["hotwords"] == list(config.hotwords)
    assert "马恩牌" in asr.ASRRunner(config).provenance()["hotwords"]


def test_no_hotwords_configured_omits_the_bias(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", hotwords=()), model_factory=fake_funasr
    ).transcribe("fixture.wav")

    assert "hotwords" not in fake_funasr.generation_records[0]


def test_config_rejects_a_malformed_hotword_entry():
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", hotwords=("ok", "  "))
    with pytest.raises(ValueError):
        asr.ASRConfig("test-model", hotwords=["ok"])  # type: ignore[arg-type]


def test_module_provenance_helper_reads_no_model(monkeypatch):
    """The CLI records provenance without loading a checkpoint."""

    def explode(**_kwargs):
        raise AssertionError("provenance must not build a model")

    monkeypatch.setattr(asr, "_load_default_model", explode)
    monkeypatch.setenv("BILI_ASR_MODEL", "FunAudioLLM/Fun-ASR-Nano-2512")

    recorded = asr.provenance()

    assert recorded["model_name"] == "FunAudioLLM/Fun-ASR-Nano-2512"
    assert recorded["device"] == "cuda"


def test_provenance_renders_absent_values_as_empty_not_none(monkeypatch):
    """A missing revision or language must not read as the string "None"."""

    monkeypatch.delenv("BILI_ASR_LANGUAGE", raising=False)
    monkeypatch.delenv("BILI_ASR_MODEL_REVISION", raising=False)

    recorded = asr.ASRRunner(asr.ASRConfig("local-model", device="cpu")).provenance()

    assert recorded["model_revision"] == ""
    assert recorded["language"] == ""
    assert "None" not in recorded.values()


def test_vad_cap_is_configurable_and_validated(monkeypatch):
    """The measured-optimal cap is a knob, not a constant frozen in the code."""

    monkeypatch.delenv("BILI_ASR_VAD_MAX_SEGMENT_S", raising=False)
    assert asr.default_config().vad_max_segment_s == asr.DEFAULT_VAD_MAX_SEGMENT_S

    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "30")
    assert asr.default_config().vad_max_segment_s == 30.0
    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", " 7.5s ")
    assert asr.default_config().vad_max_segment_s == 7.5
    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "   ")
    assert asr.default_config().vad_max_segment_s == asr.DEFAULT_VAD_MAX_SEGMENT_S

    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "soon")
    with pytest.raises(ValueError):
        asr.default_config()
    monkeypatch.setenv("BILI_ASR_VAD_MAX_SEGMENT_S", "-1")
    with pytest.raises(ValueError):
        asr.default_config()

    with pytest.raises(ValueError):
        asr.ASRConfig("m", vad_max_segment_s=0)
    with pytest.raises(ValueError):
        asr.ASRConfig("m", vad_max_segment_s=True)  # type: ignore[arg-type]


def test_the_configured_cap_reaches_the_vad_component(fake_funasr):
    asr.ASRRunner(
        asr.ASRConfig("test-model", device="cpu", vad_max_segment_s=10),
        model_factory=fake_funasr,
    ).transcribe("fixture.wav")

    assert fake_funasr.construction_records[0]["vad_kwargs"] == {"max_single_segment_time": 10_000}


# ------------------------------------------- Task 1: the construction counter


def test_runner_counter_is_zero_until_the_model_is_built(fake_funasr):
    """Asking for no transcript costs no construction; release never resets."""

    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"), model_factory=fake_funasr
    )
    assert runner.model_constructions == 0

    runner.transcribe("first.wav")
    assert runner.model_constructions == 1
    # Reuse is not a second construction.
    runner.transcribe("second.wav")
    assert runner.model_constructions == 1

    runner.release()
    assert runner.model_constructions == 1
    runner.transcribe("third.wav")
    assert runner.model_constructions == 2


def test_a_failed_load_does_not_inflate_the_counter(monkeypatch):
    """A factory that raised built nothing, so the count stays 0."""

    def exploding_factory(**_kwargs):
        raise RuntimeError("no checkpoint")

    runner = asr.ASRRunner(
        asr.ASRConfig("local-test-model", device="cpu"),
        model_factory=exploding_factory,
    )
    with pytest.raises(asr.ASRModelError):
        runner.transcribe("fixture.wav")

    # Nothing was built, so nothing is claimed: no model, no count.
    assert runner._model is None
    assert runner.model_constructions == 0


def test_three_item_batch_through_the_documented_path_constructs_once(
    tmp_root, counted_batch_seam
):
    """D2.5: one run scope, one runner, one construction — over 3 ASR rows."""

    store, rows = _seed_audio_batch(tmp_root, 3)
    coordinator_ = RunCoordinator(tmp_root, store, offline=True)

    summary = coordinator_.run_batch(rows)

    assert summary.asr_items == 3
    assert summary.model_constructions == 1
    assert counted_batch_seam.construction_count == 1
    # ...and all three rows really were transcribed by that one model.
    assert len(counted_batch_seam.generation_records) == 3
    assert [result.final_status for result in summary.results] == ["archived"] * 3
    # The coordinator owns and releases what it created.
    assert coordinator_.asr_runner is None


def test_batch_prints_the_reuse_line_once_with_the_exact_format(
    tmp_root, counted_batch_seam, capsys
):
    """A2: the run's own output states the construction count."""

    store, rows = _seed_audio_batch(tmp_root, 3)
    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 3 asr item(s)",
    ]
    assert summary.model_constructions == 1
    assert summary.asr_items == 3


def test_the_printed_line_is_the_shared_helper_string():
    """One source of the shipped string, so README can quote the exact literal."""

    assert coordinator.model_constructions_line("run", 1, 3) == (
        "run: model constructions=1 for 3 asr item(s)"
    )
    assert coordinator.model_constructions_line("asr", 3, 12) == (
        "asr: model constructions=3 for 12 asr item(s)"
    )


def test_the_batch_line_names_the_invoking_command(tmp_root, counted_batch_seam, capsys):
    """`run_batch` is shared, so the label is a constructor argument.

    `schedule` / `campaign` wrap the same batch entry; they pass their own
    name here instead of the line claiming to be `run`.
    """

    store, rows = _seed_audio_batch(tmp_root, 2, prefix="BVlabel")
    RunCoordinator(tmp_root, store, offline=True, command="schedule").run_batch(rows)

    assert capsys.readouterr().err.splitlines() == [
        "schedule: model constructions=1 for 2 asr item(s)",
    ]


def test_injected_runner_reports_the_per_batch_delta(tmp_root, counted_batch_seam):
    """D2.5: a caller-owned runner reused across batches reports this batch only."""

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVdelta")
    runner = asr.ASRRunner(asr.default_config(), model_factory=counted_batch_seam)
    coordinator_ = RunCoordinator(tmp_root, store, offline=True, asr_runner=runner)

    first = coordinator_.run_batch(rows)
    assert first.model_constructions == 1
    assert first.asr_items == 3

    # Second batch over fresh rows reuses the same caller-owned model: the
    # runner's lifetime counter is 1, but the batch delta must be 0.
    store2, rows2 = _seed_audio_batch(tmp_root, 2, prefix="BVdelta2")
    second = coordinator_.run_batch(rows2)

    assert runner.model_constructions == 1
    assert second.model_constructions == 0
    assert second.asr_items == 2
    # The injected runner stays caller-owned.
    assert coordinator_.asr_runner is runner


def test_per_item_failure_continues_the_batch_with_one_construction(
    tmp_root, monkeypatch, fake_funasr, capsys
):
    """A shared runner changes the construction count only, not the outcome."""

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVflaky")
    monkeypatch.setenv("BILI_ASR_DEVICE", "cpu")

    class FlakyModel:
        def __init__(self):
            self.calls = 0

        def generate(self, **_kwargs):
            self.calls += 1
            if self.calls == 2:  # the middle row pays for the failure
                raise asr.ASRModelError("boom")
            return [{"text": "ok", "timestamp": [[0, 1000]]}]

    def factory(**_kwargs):
        fake_funasr.construction_count += 1
        return FlakyModel()

    monkeypatch.setattr(asr, "_load_default_model", factory)

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert [len(result.failure_codes) for result in summary.results] == [0, 1, 0]
    assert [result.ok for result in summary.results] == [True, False, True]
    # One construction still served the whole batch, and the denominator
    # counts only the rows that produced a transcript.
    assert fake_funasr.construction_count == 1
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 2 asr item(s)",
    ]


def test_subtitle_only_batch_prints_no_reuse_line(tmp_root, counted_batch_seam, capsys):
    """D2.6: a zero-ASR batch prints the line on neither stream."""

    store = ManifestStore(root=tmp_root)
    identity = page_identity("BVsubonly", 0, 111, "p0")
    store.upsert({**_audio_row(identity, status="subtitle_done")})
    raw_dir = pathlib.Path(tmp_root) / "subtitles" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / f"{artifact_stem(identity)}.json").write_text(
        json.dumps({"body": [{"from": 0.0, "to": 1.0, "content": "hi"}]}),
        encoding="utf-8",
    )

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(
        [(identity.work_id, store.get(identity.work_id))]
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
    assert summary.asr_items == 0
    assert summary.model_constructions == 0
    assert counted_batch_seam.construction_count == 0


def test_the_batch_line_goes_to_stderr_and_never_to_stdout(
    tmp_root, counted_batch_seam, capsys
):
    """D2.6 as amended: the line is a diagnostic, so stdout keeps its contract.

    `campaign`'s stdout is one JSON document; `run`'s stdout is its row
    report. The batch label goes to stderr so neither is disturbed.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVstreams")
    RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert "model constructions=" in captured.err
    assert "model constructions=" not in captured.out
    assert captured.out == ""



def test_batch_that_paid_a_construction_and_failed_every_row_still_states_it(
    tmp_root, monkeypatch, counted_batch_seam, capsys
):
    """D2.6 as amended at plan-QC: the guard is "nothing was paid".

    All three QC seats independently reproduced this: the model is built (the
    ~34 s/item cost the line exists to expose), every transcription then
    raises, and the old ``asr_items <= 0`` guard printed nothing — hiding
    precisely the first-decode failure (GPU / ROCm / checkpoint) an operator
    needs stated while the batch has already paid for it.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVpaidfail")

    def exploding_generate(**_kwargs):
        raise asr.ASRModelError("first decode failed")

    monkeypatch.setattr(FakeAutoModel, "generate", exploding_generate)

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert counted_batch_seam.construction_count == 1
    assert summary.model_constructions == 1
    assert summary.asr_items == 0
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 0 asr item(s)",
    ]
    assert "model constructions=" not in captured.out


def test_subtitle_only_batch_prints_nothing_with_the_widened_guard(
    tmp_root, counted_batch_seam, capsys
):
    """The other half of the amendment: neither counter moved ⇒ silence.

    A subtitle-only batch pays no construction *and* transcribes nothing, so
    widening the guard must not start printing ``for 0 asr item(s)`` here.
    """

    store = ManifestStore(root=tmp_root)
    identity = page_identity("BVsubsilent", 0, 120, "p0")
    store.upsert({**_audio_row(identity, status="subtitle_done")})
    raw_dir = pathlib.Path(tmp_root) / "subtitles" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{artifact_stem(identity)}.json").write_text(
        json.dumps({"body": [{"from": 0.0, "to": 1.0, "content": "hi"}]}),
        encoding="utf-8",
    )

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(
        [(identity.work_id, store.get(identity.work_id))]
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
    assert summary.asr_items == 0
    assert summary.model_constructions == 0
    assert counted_batch_seam.construction_count == 0


def test_interrupted_batch_still_states_what_it_paid(
    tmp_root, monkeypatch, counted_batch_seam, capsys
):
    """Ctrl-C mid-batch: the count and the release both survive the unwind.

    The print used to sit *after* the ``try/finally``, so a KeyboardInterrupt
    (or any other exception) carried the line away while ``asr``/``pilot`` kept
    theirs; the on-call reading of a Ctrl-C'd run lost the count on the very
    action the plan names.  Assignments and print now live inside the
    ``finally``, and the original exception must still propagate.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVinterrupt")
    coordinator_ = RunCoordinator(tmp_root, store, offline=True)

    original = coordinator_._run_batch_locked

    def interrupt_after_two(rows_arg):
        original(rows_arg[:2])
        raise KeyboardInterrupt("operator pressed Ctrl-C")

    monkeypatch.setattr(coordinator_, "_run_batch_locked", interrupt_after_two)

    with pytest.raises(KeyboardInterrupt):
        coordinator_.run_batch(rows)

    captured = capsys.readouterr()
    assert counted_batch_seam.construction_count == 1
    # The batch paid one construction and transcribed two rows before the
    # interrupt; both facts still reach stderr.
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 2 asr item(s)",
    ]
    # The coordinator-owned runner is still handed back on the interrupt path.
    assert coordinator_.asr_runner is None


def test_the_reuse_line_is_dropped_when_stderr_is_closed(
    tmp_root, monkeypatch, counted_batch_seam, capsys
):
    """fd 2 closed: CPython sets ``sys.stderr = None`` and ``file=None`` is stdout.

    A closed stderr must never push the diagnostic into ``campaign``'s single
    JSON document, so both print sites refuse to print when the stream is gone.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVnostderr")
    monkeypatch.setattr(sys, "stderr", None)

    summary = RunCoordinator(tmp_root, store, offline=True).run_batch(rows)

    captured = capsys.readouterr()
    assert "model constructions=" not in captured.out
    assert captured.out == ""
    assert summary.model_constructions == 1
    assert summary.asr_items == 3


def test_run_batch_refuses_to_nest_and_keeps_the_outer_denominator(
    tmp_root, counted_batch_seam, capsys
):
    """W2b: a nested ``run_batch`` would clobber the outer count silently.

    ``_batch_asr_items`` is per-coordinator, reset on entry and printed on
    exit, so an inner call would zero the outer denominator and print a second
    line for unfinished work.  No caller nests today; the tripwire makes that
    an error instead of a wrong number.
    """

    store, rows = _seed_audio_batch(tmp_root, 3, prefix="BVnest")
    coordinator_ = RunCoordinator(tmp_root, store, offline=True)
    seen: dict[str, object] = {}

    original = coordinator_._run_batch_locked

    def nest(rows_arg):
        try:
            coordinator_.run_batch(rows_arg[:1])
        except RuntimeError as exc:
            seen["error"] = str(exc)
        return original(rows_arg)

    coordinator_._run_batch_locked = nest
    summary = coordinator_.run_batch(rows)

    captured = capsys.readouterr()
    assert "re-entrant" in str(seen.get("error"))
    # The outer batch is intact: one line, its own denominator.
    assert summary.asr_items == 3
    assert captured.err.splitlines() == [
        "run: model constructions=1 for 3 asr item(s)",
    ]
    # And the tripwire does not leak: a later batch still runs.
    store2, rows2 = _seed_audio_batch(tmp_root, 1, prefix="BVnest2")
    later = coordinator_.run_batch(rows2)
    assert later.asr_items == 1


# ------------------------------------------------------------ docs lock

def test_readme_publishes_the_paid_or_transcribed_rule():
    """W3: the documented rule is the shipped rule, guarded like the others."""

    readme = os.path.join(os.path.dirname(__file__), "..", "README.md")
    text = open(readme, encoding="utf-8").read()
    # The shipped literal and the two labels README quotes.
    assert "model constructions=" in text
    assert "for <m> asr item(s)" in text
    assert "run: model constructions=1 for 3 asr item(s)" in text
    # The per-item loop README warns about (A2's greppable statement).
    assert "forfeits that reuse" in text
    assert "bili-asr asr --bvid <bvid>" in text
    # The amended guard: paid-but-empty states its cost, subtitle-only is silent.
    assert "failed every transcription" in text
    assert "subtitle-only" in text
