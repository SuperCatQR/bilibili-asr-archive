from __future__ import annotations

import builtins

import pytest

from bili_asr import asr

#: An absorbed tail fragment may push a cue past the 60-character target.
_CUE_CEILING_TOLERANCE = 70


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


def test_an_unpinned_result_shape_is_ignored_not_half_read():
    """Only the pinned model's shape is normalised; other shapes are not guessed."""

    assert asr.normalize_result([{"sentence_info": [{"start": 1000, "end": 2500, "text": "内容"}]}]) == []
    # ...while a plain text result still survives, with rich tags stripped
    assert asr.normalize_result([{"text": "<|zh|><|NEUTRAL|>内容"}]) == [
        {"start": 0.0, "end": 0.0, "text": "内容"}
    ]


def test_text_without_token_timings_keeps_one_zero_length_segment():
    """Leaving the timing unknown beats inventing one from a foreign field."""

    result = [{"text": "整段", "timestamp": [[500, 800], [900, 1600]]}]
    assert asr.normalize_result(result) == [
        {"start": 0.0, "end": 0.0, "text": "整段"}
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
    # The trailing "然后。" is below the cue floor, so it is absorbed into the
    # sentence before it instead of becoming a two-character subtitle.
    assert [(s["start"], s["end"], s["text"]) for s in segments] == [
        (0.18, 5.18, "就是我注册一个域名，叫做labor。然后。"),
    ]
    assert 0.0 <= segments[0]["confidence"] <= 1.0


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
    assert [segment["text"] for segment in segments] == ["前半后半"]
    assert [segment["start"] for segment in segments] == [10.0]
    assert [segment["end"] for segment in segments] == [13.0]


def test_normalize_nano_tokens_close_on_cue_length_ceiling():
    segments = asr.normalize_result(
        [{"timestamps": _nano_tokens([("字", 0.1 * index, 0.1 * index + 0.05) for index in range(130)])}]
    )
    assert all(segment["end"] > segment["start"] for segment in segments)
    # the ceiling is a readability target, not a hard cut: an absorbed tail
    # fragment may push a cue slightly past it, and nothing may be dropped
    assert sum(len(segment["text"]) for segment in segments) == 130
    assert max(len(segment["text"]) for segment in segments) <= 70


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


def test_cues_absorb_a_leading_mark_and_punctuation_only_groups():
    """A mark never opens a cue; a punctuation-only group never stands alone."""

    tokens = _nano_tokens(
        [
            ("第", 0.0, 0.2), ("一", 0.2, 0.4), ("句", 0.4, 0.6), ("话", 0.6, 0.8),
            ("。", 0.8, 0.86),
            ("，", 3.0, 3.06), ("第", 3.06, 3.2), ("二", 3.2, 3.4), ("句", 3.4, 3.6),
            ("话", 3.6, 3.8), ("就", 3.8, 4.0), ("到", 4.0, 4.2), ("这", 4.2, 4.4),
            ("里", 4.4, 4.6), ("了", 4.6, 4.8), ("。", 4.8, 4.86),
            ("。", 4.9, 4.96),
        ]
    )
    segments = asr.normalize_result([{"timestamps": tokens}])

    assert all(not segment["text"][:1] in "，。！？、；：" for segment in segments)
    assert all(segment["text"].strip("，。！？、；：") for segment in segments)
    assert [segment["text"] for segment in segments] == [
        "第一句话。，",
        "第二句话就到这里了。。",
    ]


def test_a_dense_stream_keeps_every_character_and_stays_near_the_ceiling():
    """The ceiling is a readability target; keeping the text is the hard rule."""

    # ~5 characters per second, i.e. ordinary speech: the duration floor must
    # not fire and merge the ceiling-sized cues back together
    head = [("甲", 0.0, 0.2), ("乙", 0.2, 0.4), ("丙", 0.4, 0.6), ("丁", 0.6, 0.8),
            ("戊", 0.8, 1.0), ("己", 1.0, 1.2), ("庚", 1.2, 1.4), ("辛", 1.4, 1.6)]
    tail = [("字", 2.0 + 0.2 * index, 2.2 + 0.2 * index) for index in range(120)]
    segments = asr.normalize_result([{"timestamps": _nano_tokens(head + tail)}])

    assert sum(len(segment["text"]) for segment in segments) == len(head) + len(tail)
    assert all(len(segment["text"]) <= _CUE_CEILING_TOLERANCE for segment in segments)
    assert all(segment["end"] >= segment["start"] for segment in segments)


def test_absorbed_latin_fragment_keeps_a_word_separator():
    """The model's own tokens carry the spaces; absorbing a cue must not lose them."""

    segments = asr.normalize_result(
        [
            {
                "timestamps": _nano_tokens(
                    [
                        ("我", 0.0, 0.2), ("们", 0.2, 0.4), ("说", 0.4, 0.6),
                        (" labor", 0.6, 1.0), (" gang", 1.0, 1.4),
                        ("。", 1.4, 1.46),
                        ("好", 3.0, 3.2), ("。", 3.2, 3.26),      # undersized: absorbed
                    ]
                )
            }
        ]
    )

    text = "".join(segment["text"] for segment in segments)
    assert text == "我们说 labor gang。好。"
    assert "labor gang" in text
