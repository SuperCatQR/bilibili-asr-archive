"""Evidence-guard tests for the 2026-09-28 hotword governance ruling.

Plan 20260928-hotword-injection-governance; closes residual
``20260922-proofread-wave R1`` (the hotword list as an insertion source).
"""
from __future__ import annotations

from bili_asr import asr


def test_guard_admits_terms_present_in_evidence() -> None:
    admitted, dropped = asr.evidence_guard_hotwords(
        ("扬弃", "自在", "不存在的词"),
        ("这一段讲扬弃和自在的概念",),
    )
    assert admitted == ("扬弃", "自在")
    assert dropped == ("不存在的词",)


def test_guard_is_pure_containment_no_model_calls() -> None:
    # The guard must be plain string logic: any term occurring anywhere passes.
    admitted, _ = asr.evidence_guard_hotwords(("主义主义",), ("……主义主义……",))
    assert admitted == ("主义主义",)


def test_config_default_seeds_nothing() -> None:
    cfg = asr.ASRConfig(model_name="m")
    assert cfg.hotwords == ()
    assert cfg.hotwords_dropped == ()


def test_config_guard_drops_speculative_terms() -> None:
    cfg = asr.ASRConfig(
        model_name="m",
        hotwords=("扬弃", "空气炮"),
        evidence_texts=("黑格尔的扬弃",),
    )
    assert cfg.hotwords == ("扬弃",)
    assert cfg.hotwords_dropped == ("空气炮",)


def test_operator_env_terms_pass_through_the_same_guard() -> None:
    cfg = asr.ASRConfig(
        model_name="m",
        hotwords=("新词", "空气炮"),
        evidence_texts=("这里有新词出现",),
    )
    assert cfg.hotwords == ("新词",)
    assert cfg.hotwords_dropped == ("空气炮",)


def test_no_evidence_means_no_prompt_terms() -> None:
    # With no evidence text, nothing is admitted — the prompt stays clean.
    cfg = asr.ASRConfig(model_name="m", hotwords=("扬弃",))
    assert cfg.hotwords == ()
    assert cfg.hotwords_dropped == ("扬弃",)


def test_dedup_and_blank_filtering() -> None:
    admitted, dropped = asr.evidence_guard_hotwords(
        ("扬弃", "扬弃", " ", "自在"), ("扬弃",)
    )
    assert admitted == ("扬弃",)
    assert dropped == ("自在",)
