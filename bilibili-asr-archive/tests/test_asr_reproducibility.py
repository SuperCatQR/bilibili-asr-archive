"""Deterministic local lifecycle oracles for the optional ASR boundary."""

from __future__ import annotations

import builtins
import json
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
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    return FakeAutoModel


def test_fake_model_result_normalization_timestamps_and_rich_tag_cleanup(fake_funasr):
    assert asr.transcribe("fixture-audio.wav", model_name="local-test-model") == [
        {"start": 0.125, "end": 1.5, "text": "deterministic"},
        {"start": 1.5, "end": 2.75, "text": "output"},
    ]
    assert fake_funasr.construction_records == [{"model": "local-test-model", "trust_remote_code": False, "device": "cpu", "offline": True, "local_source": "configured-local"}]
    assert fake_funasr.generation_records == [{"input": "fixture-audio.wav", "cache": {}, "language": "auto", "use_itn": True, "batch_size_s": 60, "merge_vad": True, "merge_length_s": 15}]


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
    assert fake_funasr.construction_records == [{"model": "/fixture/local-model", "trust_remote_code": False, "device": "cpu", "offline": True, "local_source": "configured-local"}] * 2


def test_error_serialization_redacts_forbidden_markers_and_preserves_class(monkeypatch):
    hostile_message = (
        "SESSDATA cookie token signed-url raw exception /tmp/private.wav "
        "model-bytes media-bytes"
    )

    class ExplodingModel:
        def __init__(self, **_kwargs):
            raise RuntimeError(hostile_message)

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


def test_factory_gets_exact_kwargs_and_typeerror_is_not_retried():
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        raise TypeError("hostile secret")
    runner = asr.ASRRunner(asr.ASRConfig("model", model_revision="rev"), model_factory=factory)
    with pytest.raises(asr.ASRModelError) as caught:
        runner.transcribe("fixture.wav")
    assert len(calls) == 1
    assert set(calls[0]) == {
        "model", "device", "trust_remote_code", "offline", "local_source", "model_revision"
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
        offline=True,
        local_source="configured-local",
    )
    provenance = asr.ASRRunner(config).provenance()
    assert list(provenance) == [
        "model_name", "model_revision", "device", "offline", "local_source"
    ]
    assert provenance == {
        "model_name": "local-model",
        "model_revision": "revision-1",
        "device": "cpu",
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
    provenance = asr.ASRRunner(asr.ASRConfig("iic/SenseVoiceSmall")).provenance()

    assert provenance["model_name"] == "iic/SenseVoiceSmall"


@pytest.mark.parametrize(
    "model_name",
    (
        "/opt/models/SenseVoiceSmall",
        "C:\\models\\SenseVoiceSmall",
        "https://models.example/SenseVoiceSmall",
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
