from __future__ import annotations

import builtins

import pytest

from bili_asr import asr


def test_segments_to_srt_and_txt():
    segments = [
        {"start": 0.125, "end": 1.5, "text": "第一句"},
        {"start": 61.0, "end": 62.25, "text": "第二句"},
    ]
    assert asr.segments_to_srt(segments) == (
        "1\n00:00:00,125 --> 00:00:01,500\n第一句\n\n"
        "2\n00:01:01,000 --> 00:01:02,250\n第二句\n"
    )
    assert asr.segments_to_txt(segments) == "第一句\n第二句"


def test_normalize_sentence_info_and_rich_tags():
    result = [{"sentence_info": [
        {"start": 1000, "end": 2500, "text": "<|zh|><|NEUTRAL|>内容"}
    ]}]
    assert asr.normalize_result(result) == [
        {"start": 1.0, "end": 2.5, "text": "内容"}
    ]


def test_normalize_single_text_uses_outer_timestamps():
    result = [{"text": "整段", "timestamp": [[500, 800], [900, 1600]]}]
    assert asr.normalize_result(result) == [
        {"start": 0.5, "end": 1.6, "text": "整段"}
    ]


def test_transcribe_missing_dependency_has_install_hint(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "funasr":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(asr.ASRDependencyError, match="bilibili-asr-archive/\\[asr\\]"):
        asr.transcribe("missing.wav")
