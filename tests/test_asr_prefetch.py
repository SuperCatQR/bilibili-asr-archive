"""CPU preparation overlap keeps serial cue/coverage and two-pass identities."""

from __future__ import annotations

import threading

import pytest

from bili_asr.asr.errors import AudioDecodeError
from bili_asr.asr.runner import two_pass_transcribe
from test_asr_qwen import _runner


def test_two_pass_reuses_verified_waveform_and_clears_scope_between_tasks(monkeypatch, tmp_path):
    import soundfile as sf
    runner, _ = _runner(monkeypatch, text="今天。", hotwords=("今天",))
    path = tmp_path / "verified.audio"
    path.write_bytes(b"identity bytes; reader is injected")
    original = sf.read
    calls = []
    def read(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(sf, "read", read)
    two_pass_transcribe(runner, str(path), paired_subtitle_text=None)
    assert len(calls) == 1
    assert [p["waveform_reused"] for p in runner.diagnostics()["passes"]] == [False, True]
    assert runner._prepared_audio is None
    assert runner._audio_reuse_scope is False
    two_pass_transcribe(runner, str(path), paired_subtitle_text=None)
    assert len(calls) == 2
    assert len(runner.diagnostics()["passes"]) == 2


def test_source_change_between_passes_fails_and_clears_cached_output(monkeypatch, tmp_path):
    runner, _ = _runner(monkeypatch, text="今天。", hotwords=("今天",))
    path = tmp_path / "changing.audio"
    path.write_bytes(b"first")
    rebuild = runner.rebuild_hotwords_from_first_pass
    def change(text):
        path.write_bytes(b"different same task input")
        return rebuild(text)
    monkeypatch.setattr(runner, "rebuild_hotwords_from_first_pass", change)
    with pytest.raises(AudioDecodeError, match="changed between"):
        two_pass_transcribe(runner, str(path), paired_subtitle_text=None)
    assert runner._prepared_audio is None
    assert runner.transcribed_segments() is None
    assert runner.transcribed_coverage() is None


def test_cpu_prefetch_overlaps_first_decode_using_distinct_processor_and_preserves_products(monkeypatch):
    serial, _ = _runner(monkeypatch, text="今天。", chunk_seconds=1)
    expected = serial.transcribe("/virtual/input")
    expected_coverage = serial.transcribed_coverage()
    runner, _ = _runner(monkeypatch, text="今天。", chunk_seconds=1)
    runner.configure_prefetch(enabled=True, max_bytes=64 * 1024 * 1024)
    prepared = threading.Event()
    processors = []
    prepare = runner._prepare_decode_inputs
    def observe(processor, audio, **kwargs):
        result = prepare(processor, audio, **kwargs)
        processors.append(processor)
        if threading.current_thread() is not threading.main_thread():
            prepared.set()
        return result
    monkeypatch.setattr(runner, "_prepare_decode_inputs", observe)
    transcribe = runner._transcribe_chunk
    first = True
    def decode(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            assert prepared.wait(2), "next CPU input did not run while this chunk owned decode"
        return transcribe(*args, **kwargs)
    monkeypatch.setattr(runner, "_transcribe_chunk", decode)
    assert runner.transcribe("/virtual/input") == expected
    assert runner.transcribed_coverage() == expected_coverage
    primary = runner._get_models().processor
    assert primary in processors and any(item is not primary for item in processors)
    report = runner.diagnostics()["passes"][0]
    assert report["prefetch"]["depth"] == 1 and report["prefetch"]["submitted"] == 2
    assert report["prefetch"]["fallback"] is None
    assert all(event["start_s"] <= event["end_s"] for event in report["trace"])
    assert {"cpu_input_prepare", "cpu_input_wait", "device_transfer", "model_generate", "align"} <= {
        event["phase"] for event in report["trace"]}
    assert all(event["measurement"] == "wall" for event in report["trace"])


def test_small_budget_falls_back_to_serial_without_losing_chunks(monkeypatch):
    serial, _ = _runner(monkeypatch, text="今天。", chunk_seconds=1)
    expected = serial.transcribe("/virtual/input")
    runner, _ = _runner(monkeypatch, text="今天。", chunk_seconds=1)
    runner.configure_prefetch(enabled=True, max_bytes=1)
    assert runner.transcribe("/virtual/input") == expected
    report = runner.diagnostics()["passes"][0]
    assert report["prefetch"]["submitted"] == 0
    assert report["prefetch"]["fallback"] == "input_budget"


def test_uncloneable_processor_falls_back_without_changing_cues(monkeypatch):
    runner, _ = _runner(monkeypatch, text="今天。", chunk_seconds=1)
    expected = runner.transcribe("/virtual/input")
    runner.configure_prefetch(enabled=True)
    import bili_asr.asr.preparation as module
    def cannot_clone(_value):
        raise TypeError("unsupported third-party processor")
    monkeypatch.setattr(module.copy, "deepcopy", cannot_clone)
    assert runner.transcribe("/virtual/input") == expected
    assert runner._diagnostic_passes[0]["prefetch"]["fallback"] == "processor_not_cloneable"


@pytest.mark.parametrize("budget,submitted", [(737_280_000, 1), (737_279_999, 0), (64 * 1024 * 1024, 0)])
def test_180_second_prefetch_admission_boundary_preserves_audio(monkeypatch, budget, submitted):
    import numpy as np
    import soundfile as sf
    runner, _ = _runner(monkeypatch, text="today", chunk_seconds=180)
    import bili_asr.asr.constants as constants
    monkeypatch.setattr(constants, "_CHUNK_SEARCH_EXPAND_S", 0)
    samples = np.zeros(16_000 * 360, dtype=np.float64)
    monkeypatch.setattr(sf, "read", lambda *a, **kw: (samples, 16_000))
    expected = runner.transcribe("/virtual/input")
    runner.configure_prefetch(enabled=True, max_bytes=budget)
    assert runner.transcribe("/virtual/input") == expected
    report = runner.diagnostics()["passes"][0]
    assert report["decoded_s"] == 360
    assert report["prefetch"]["submitted"] == submitted
    entry = report["prefetch"]["chunks"][0]
    assert entry["waveform_bytes"] == 11_520_000
    assert entry["reserved_bytes"] == 737_280_000
    assert entry["status"] == ("consumed" if submitted else "serial_fallback")
    assert report["prefetch"]["fallback_counts"] == ({} if submitted else {"input_budget": 1})


def test_long_blocks_and_short_tail_keep_all_admission_reasons(monkeypatch):
    import numpy as np
    import soundfile as sf
    runner, _ = _runner(monkeypatch, text="today", chunk_seconds=180)
    import bili_asr.asr.constants as constants
    monkeypatch.setattr(constants, "_CHUNK_SEARCH_EXPAND_S", 0)
    monkeypatch.setattr(sf, "read", lambda *a, **kw: (np.zeros(16_000 * 361, dtype=np.float32), 16_000))
    runner.configure_prefetch(enabled=True)
    runner.transcribe("/virtual/input")
    report = runner.diagnostics()["passes"][0]["prefetch"]
    assert report["submitted"] == report["consumed"] == 1
    assert report["fallback_counts"] == {"input_budget": 1}
    assert [c["status"] for c in report["chunks"]] == ["serial_fallback", "consumed"]


@pytest.mark.parametrize("unknown", [False, True])
def test_prepared_size_overflow_or_unknown_discards_then_uses_serial(monkeypatch, unknown):
    from types import SimpleNamespace
    runner, _ = _runner(monkeypatch, text="today", chunk_seconds=1)
    expected = runner.transcribe("/virtual/input")
    original = runner._prepare_decode_inputs
    def oversized(processor, audio, **kwargs):
        inputs = original(processor, audio, **kwargs)
        if threading.current_thread() is not threading.main_thread():
            inputs["extra"] = object() if unknown else SimpleNamespace(nbytes=65 * 1024 * 1024)
        return inputs
    monkeypatch.setattr(runner, "_prepare_decode_inputs", oversized)
    runner.configure_prefetch(enabled=True)
    assert runner.transcribe("/virtual/input") == expected
    report = runner.diagnostics()["passes"][0]["prefetch"]
    reason = "prepared_input_size_unknown" if unknown else "prepared_input_budget"
    assert report["submitted"] == report["discarded"] == 2
    assert report["consumed"] == 0
    assert report["fallback_counts"] == {reason: 2}


def test_decode_failure_drains_preparation_without_replacing_original_error(monkeypatch):
    runner, _ = _runner(monkeypatch, text="today", chunk_seconds=1)
    runner.configure_prefetch(enabled=True)
    def fail_prepare(*args, **kwargs):
        raise ValueError("preparation error")
    def fail_decode(*args, **kwargs):
        raise RuntimeError("decode error")
    monkeypatch.setattr(runner, "_prepare_decode_inputs", fail_prepare)
    monkeypatch.setattr(runner, "_transcribe_chunk", fail_decode)
    with pytest.raises(RuntimeError, match="decode error"):
        runner.transcribe("/virtual/input")
    assert runner.transcribed_segments() is None
    assert runner.diagnostics()["passes"][0]["prefetch"]["discarded"] == 1


def test_alignment_stage_trace_has_chunk_identity_and_wall_measurement(monkeypatch):
    runner, _ = _runner(monkeypatch, text="today", chunk_seconds=1)
    runner.transcribe("/virtual/input")
    events = runner.diagnostics()["passes"][0]["trace"]
    phases = {"align_prepare", "align_transfer", "align_forward", "align_postprocess"}
    for index in range(3):
        stages = [e for e in events if e["phase"] in phases and e["chunk_index"] == index]
        assert {e["phase"] for e in stages} == phases
        assert all(e["measurement"] == "wall" and e["start_s"] <= e["end_s"] for e in stages)
