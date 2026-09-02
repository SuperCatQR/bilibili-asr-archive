"""Deterministic local lifecycle oracles for the optional ASR boundary."""

from __future__ import annotations

import builtins
import sys
import types

import pytest

from bili_asr import asr


class FakeAutoModel:
    construction_count = 0
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs):
        type(self).construction_count += 1
        type(self).calls.append(kwargs)

    def generate(self, **kwargs):
        type(self).calls.append(kwargs)
        return [{
            "sentence_info": [
                {"start": 125, "end": 1500, "text": "<|zh|><|NEUTRAL|> deterministic"},
                {"start": 1500, "end": 2750, "text": "<|zh|> output"},
            ]
        }]


@pytest.fixture
def fake_funasr(monkeypatch):
    FakeAutoModel.construction_count = 0
    FakeAutoModel.calls = []
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    return FakeAutoModel


def test_fake_model_result_normalization_timestamps_and_rich_tag_cleanup(fake_funasr):
    segments = asr.transcribe("fixture-audio.wav", model_name="local-test-model")

    assert segments == [
        {"start": 0.125, "end": 1.5, "text": "deterministic"},
        {"start": 1.5, "end": 2.75, "text": "output"},
    ]
    assert fake_funasr.construction_count == 1
    assert fake_funasr.calls[0] == {
        "model": "local-test-model",
        "trust_remote_code": True,
        "device": "cpu",
        "vad_model": "fsmn-vad",
        "punc_model": "ct-punc",
    }
    assert fake_funasr.calls[1]["input"] == "fixture-audio.wav"
    assert fake_funasr.calls[1]["cache"] == {}
    assert fake_funasr.calls[1]["language"] == "auto"


def test_fake_generation_inputs_are_deterministic_and_cpu_offline_intent_explicit(fake_funasr, monkeypatch):
    monkeypatch.setenv("BILI_ASR_MODEL", "/fixture/local-model")

    first = asr.transcribe("one.wav")
    second = asr.transcribe("two.wav")

    assert first == second
    assert fake_funasr.construction_count == 2
    for call in fake_funasr.calls[::2]:
        assert call["model"] == "/fixture/local-model"
        assert call["device"] == "cpu"
        assert call["trust_remote_code"] is True
    for call in fake_funasr.calls[1::2]:
        assert call["language"] == "auto"
        assert call["use_itn"] is True
        assert call["batch_size_s"] == 60
        assert call["merge_vad"] is True
        assert call["merge_length_s"] == 15


def test_model_errors_are_redacted_and_no_network_or_model_download_helpers_called(monkeypatch):
    class ExplodingModel:
        def __init__(self, **_kwargs):
            raise RuntimeError("SESSDATA=secret-cookie /tmp/private.wav model-bytes")

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=ExplodingModel))
    with pytest.raises(asr.ASRModelError) as caught:
        asr.transcribe("/tmp/private.wav")

    message = str(caught.value)
    assert "SESSDATA" not in message
    assert "secret-cookie" not in message
    assert "/tmp/private.wav" not in message
    assert "model-bytes" not in message


def test_transcribe_does_not_import_socket_or_download_helpers(monkeypatch):
    real_import = builtins.__import__
    forbidden = {"socket", "modelscope", "requests"}

    def blocked(name, *args, **kwargs):
        if name in forbidden:
            raise AssertionError(f"forbidden helper imported: {name}")
        return real_import(name, *args, **kwargs)

    class LocalModel(FakeAutoModel):
        pass

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=LocalModel))
    monkeypatch.setattr(builtins, "__import__", blocked)
    assert asr.transcribe("fixture.wav")


def test_current_transcribe_constructs_once_per_call_characterization(fake_funasr):
    asr.transcribe("first.wav")
    asr.transcribe("second.wav")
    assert fake_funasr.construction_count == 2


def test_target_runner_reuse_oracle_is_pending_until_runner_exists():
    pytest.fail("target lifecycle requires one runner construction for multiple audio paths")
