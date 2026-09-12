"""Cue shaping, checked against a recorded Fun-ASR-Nano token stream.

The fixture is the real result for one archived part: 2037 tokens carrying the
model's own confidence scores.  It exercises the shapes that matter — Chinese
punctuation tokens, a slow English domain-name spelling, long unpunctuated
runs — without needing a GPU, a model download, or a human adjudication.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bili_asr import asr

FIXTURE = Path(__file__).parent / "fixtures" / "asr-cues" / "BV1wLTP6NE9h.p0.tokens.json"
PUNCT = "。，？！、；：,?!.;:…—·\"'“”‘’（）()《》"
LEADING = "，。！？、；："


def flatten(text: str) -> str:
    return re.sub(f"[{re.escape(PUNCT)}]", "", text).replace(" ", "")


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))[0]


@pytest.fixture(scope="module")
def cues(payload: dict) -> list[dict]:
    return asr._token_cues(payload["timestamps"])


def test_cues_reassemble_into_exactly_the_recognised_text(cues, payload):
    """Shaping may move boundaries; it may never add, drop, or reorder text."""

    assert flatten("".join(cue["text"] for cue in cues)) == flatten(payload["text"])


def test_cues_are_well_formed_subtitles(cues):
    assert cues
    for cue in cues:
        assert cue["end"] > cue["start"]
        assert cue["text"].strip()
        assert cue["text"][0] not in LEADING, "a closing mark never opens a cue"


def test_cues_carry_the_models_own_confidence(cues):
    """Quality is measurable from the artefact alone — no human reference."""

    confident = [cue for cue in cues if "confidence" in cue]
    assert len(confident) == len(cues)
    assert all(0.0 <= cue["confidence"] <= 1.0 for cue in cues)
    # the least confident cue is the English domain-name spelling, which is
    # exactly where the second system also fell apart
    worst = min(cues, key=lambda cue: cue["confidence"])
    assert worst["start"] < 10.0
    assert worst["confidence"] < 0.5


def test_cue_shaping_is_deterministic(payload):
    first = asr._token_cues(payload["timestamps"])
    second = asr._token_cues(payload["timestamps"])
    assert first == second


def test_no_fragment_cues_on_recorded_speech(cues):
    """Neither a one-word subtitle nor a punctuation-only line survives shaping."""

    for cue in cues:
        body = cue["text"].strip(LEADING).strip()
        assert body, "punctuation-only cue"
        assert len(body) >= 6 or (cue["end"] - cue["start"]) >= 1.0, cue["text"]
