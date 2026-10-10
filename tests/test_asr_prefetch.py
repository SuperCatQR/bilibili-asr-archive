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
    def observe(processor, audio):
        result = prepare(processor, audio)
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
    import bili_asr.asr.runner as module
    def cannot_clone(_value):
        raise TypeError("unsupported third-party processor")
    monkeypatch.setattr(module.copy, "deepcopy", cannot_clone)
    assert runner.transcribe("/virtual/input") == expected
    assert runner._diagnostic_passes[0]["prefetch"]["fallback"] == "processor_not_cloneable"
