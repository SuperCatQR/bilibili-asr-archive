"""Deterministic local lifecycle oracles for the optional ASR boundary."""

from __future__ import annotations

import builtins
import json
import os
import sys
import types
from typing import Any

import pytest

from bili_asr import asr
from bili_asr import coordinator


class FakeAutoModel:
    construction_count = 0
    construction_records: list[dict[str, object]] = []
    generation_records: list[dict[str, object]] = []

    def __init__(self, **kwargs):
        type(self).construction_count += 1
        type(self).construction_records.append(dict(kwargs))

    def generate(self, **kwargs):
        type(self).generation_records.append(dict(kwargs))
        return [{"sentence_info": [
            {"start": 125, "end": 1500, "text": "<|zh|><|NEUTRAL|> deterministic"},
            {"start": 1500, "end": 2750, "text": "<|zh|> output"},
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
        {"start": 0.125, "end": 1.5, "text": "deterministic"},
        {"start": 1.5, "end": 2.75, "text": "output"},
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
    assert asr.normalize_result([None, "bad", {}, {"sentence_info": [{"text": ""}]}]) == []
    assert asr.normalize_result({"text": "plain", "timestamp": []}) == [
        {"start": 0.0, "end": 0.0, "text": "plain"}
    ]
    assert asr.normalize_result({"sentences": [{"start": 10, "end": 20, "text": "<|en|>ok"}]}) == [
        {"start": 0.01, "end": 0.02, "text": "ok"}
    ]


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
        "output_shape": ["end", "start", "text"],
    }
    assert set(report) == {
        "model_construction_count", "normalized_segment_count", "output_shape"
    }


def test_cuda_unavailable_raises_dependency_error_with_rocm_hint(monkeypatch):
    """CUDA unavailable should raise ASRDependencyError with ROCm installation hint."""
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
    assert "ROCm" in error_message or "7800XT" in error_message


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
        {"start": 0.125, "end": 1.5, "text": "deterministic"},
        {"start": 1.5, "end": 2.75, "text": "output"},
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
