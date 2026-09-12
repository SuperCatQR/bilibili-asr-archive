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


def _nano_tokens(pairs: list[tuple[str, float, float]]) -> list[dict[str, object]]:
    """Fun-ASR-Nano's recorded token shape: seconds, punctuation as its own token."""

    return [
        {"token": token, "start_time": start, "end_time": end, "score": 0.9}
        for token, start, end in pairs
    ]


def test_normalize_nano_tokens_group_into_punctuated_cues():
    """Recorded Fun-ASR-Nano output: cue text keeps the punctuation tokens."""

    result = [
        {
            "text": "就是我注册一个域名，叫做 labor。然后大家都知道了。",
            "timestamps": _nano_tokens(
                [
                    ("就", 0.18, 0.24),
                    ("是", 0.30, 0.36),
                    ("我", 1.02, 1.08),
                    ("注", 1.20, 1.26),
                    ("册", 1.26, 1.32),
                    ("一", 1.32, 1.38),
                    ("个", 1.38, 1.44),
                    ("域", 1.44, 1.50),
                    ("名", 1.50, 1.56),
                    ("，", 1.56, 1.62),
                    ("叫", 1.62, 1.68),
                    ("做", 1.68, 1.74),
                    ("labor", 1.74, 2.10),
                    ("。", 2.10, 2.16),
                    ("然", 5.00, 5.06),
                    ("后", 5.06, 5.12),
                    ("。", 5.12, 5.18),
                ]
            ),
        }
    ]
    segments = asr.normalize_result(result)
    assert segments == [
        {"start": 0.18, "end": 2.16, "text": "就是我注册一个域名，叫做labor。"},
        {"start": 5.00, "end": 5.18, "text": "然后。"},
    ]


def test_normalize_nano_tokens_stay_in_seconds_and_closed_on_pause():
    """A pause alone closes a cue, and seconds are never divided by 1000."""

    segments = asr.normalize_result(
        [
            {
                "timestamps": _nano_tokens(
                    [("前", 10.0, 10.5), ("半", 10.5, 11.0), ("后", 12.0, 12.5), ("半", 12.5, 13.0)]
                )
            }
        ]
    )
    assert [segment["text"] for segment in segments] == ["前半", "后半"]
    assert [segment["start"] for segment in segments] == [10.0, 12.0]


def test_normalize_nano_tokens_close_on_cue_length_ceiling():
    segments = asr.normalize_result(
        [{"timestamps": _nano_tokens([("字", 0.1 * index, 0.1 * index + 0.05) for index in range(130)])}]
    )
    assert len(segments) >= 3
    assert all(len(segment["text"]) <= 60 for segment in segments)
    assert all(segment["end"] > segment["start"] for segment in segments)


def test_normalize_nano_shape_without_usable_tokens_falls_back_to_text():
    """Malformed token entries never claim a timing they cannot support."""

    result = [{"text": "整段", "timestamps": [{"token": "x"}, "bad", 7]}]
    assert asr.normalize_result(result) == [
        {"start": 0.0, "end": 0.0, "text": "整段"}
    ]


def test_transcribe_missing_dependency_has_install_hint(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "funasr":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(asr.ASRDependencyError, match="bilibili-asr-archive/\\[asr\\]"):
        runner = asr.ASRRunner(asr.ASRConfig(model_name="test-model", device="cpu"))
        runner.transcribe("missing.wav")
