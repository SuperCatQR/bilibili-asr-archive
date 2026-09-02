"""Deterministic local lifecycle oracles for the optional ASR boundary."""

from __future__ import annotations

import builtins
import json
import sys
import types

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
    assert fake_funasr.construction_records == [{"model": "local-test-model", "trust_remote_code": True, "device": "cpu", "vad_model": "fsmn-vad", "punc_model": "ct-punc"}]
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
    assert fake_funasr.construction_records == [{"model": "/fixture/local-model", "trust_remote_code": True, "device": "cpu", "vad_model": "fsmn-vad", "punc_model": "ct-punc"}] * 2


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


def test_current_transcribe_constructs_once_per_call_characterization(fake_funasr):
    asr.transcribe("first.wav")
    asr.transcribe("second.wav")
    assert fake_funasr.construction_count == 2


@pytest.mark.xfail(strict=False, reason="ASRRunner is introduced by Task 2")
def test_target_runner_reuse_oracle_is_target_facing(fake_funasr):
    """Target contract: one runner owns one model across all input paths."""
    runner_type = getattr(asr, "ASRRunner", None)
    if runner_type is None:
        pytest.xfail("Task 2 has not introduced bili_asr.asr.ASRRunner yet")
    runner = runner_type(model_name="local-test-model")
    assert runner.transcribe_many(["first.wav", "second.wav"])
    assert fake_funasr.construction_count == 1
    assert [record["input"] for record in fake_funasr.generation_records] == [
        "first.wav", "second.wav"
    ]
