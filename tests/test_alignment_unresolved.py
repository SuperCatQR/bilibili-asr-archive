"""Preserve unmatched text; never fabricate a usable timing for it."""

import numpy as np
import pytest

from bili_asr.asr.admission import assess_output
from bili_asr.asr.alignment import _aligned_cues, _thread_text, threading_evidence
from bili_asr.asr.config import ASRConfig
from bili_asr.asr.runner import ASRRunner, set_progress_hook
from bili_asr.storage import JobKind
from bili_asr.storage.asr_quality import read_assessment
from bili_asr.workflow import WorkflowExecutor
from bili_asr.workflow_runtime import ArchiveWorkflowHandlers
from tests.test_asr_admission import runtime as _runtime
from tests.support.asr_quality import coverage
from tests.test_asr_qwen import _FakeModelSet, _units


@pytest.fixture
def runtime(tmp_path):
    yield from _runtime.__wrapped__(tmp_path)


@pytest.mark.parametrize("text,units", [
    ("未对齐开头。", []), ("遗漏开头。已对齐。", _units("已对齐。")),
    ("已对齐但结尾遗漏", _units("已对齐")),
])
def test_unmatched_meaningful_text_is_preserved_and_rejected_even_if_cue_span_is_positive(text, units):
    pieces = _thread_text(text, units)
    report = threading_evidence(text, units, pieces)
    cues = _aligned_cues(pieces)
    assert "".join(piece["text"] for piece in pieces) == text
    assert "".join(cue["text"] for cue in cues) == text
    assert report["unmatched_text_characters"] > 0
    assert report["private_witness"]["recognized_text"] == text
    assert report["private_witness"]["units"] == units
    result = assess_output(cues, diagnostics={"passes": [{"chunks": [{"alignment": report}]}]})
    assert result["status"] == "unusable" and "asr_alignment_unresolved" in result["issue_counts"]
    if not units:
        assert cues[0]["start"] == cues[0]["end"] == 0
        assert not result["representable"]


def test_punctuation_and_whitespace_are_not_unmatched_speech_and_private_witness_is_bounded():
    text = "您好，世界。"
    units = _units(text)
    result = threading_evidence(text, units, _thread_text(text, units))
    assert result["unmatched_text_characters"] == 0 and "private_witness" not in result
    units = [{"text": "额" * 32, "start_time": 1, "end_time": 2}] * 600
    witness = threading_evidence("未" * 10000, units, _thread_text("未" * 10000, units))["private_witness"]
    assert len(witness["units"]) == 512 and len(witness["recognized_text"]) == 8192
    assert sum(len(unit["text"]) for unit in witness["units"]) <= 8192
    assert witness["units_truncated"] and witness["text_truncated"]


def test_runner_keeps_chunk_boundary_evidence_and_real_completed_progress(tmp_path, monkeypatch, mock_torch):
    import soundfile as sf
    path = tmp_path / "two.wav"
    sf.write(path, np.zeros(32000, dtype=np.float32), 16000)
    models = _FakeModelSet("未对齐。", [])
    runner = ASRRunner(ASRConfig(model_name="offline", device="cpu", chunk_seconds=1), model_factory=lambda **kwargs: models)
    events = []
    set_progress_hook(events.append)
    try:
        cues = runner.transcribe(str(path))
    finally:
        set_progress_hook(None)
        runner.release()
    chunks = runner.diagnostics()["passes"][-1]["chunks"]
    assert len(chunks) == 2
    assert [chunk["start_s"] for chunk in chunks] == [0, 1]
    assert all(chunk["alignment"]["unmatched_text_characters"] == 3 for chunk in chunks)
    assert events.count("chunk_complete") == 2 and "model_ready" in events and "audio_ready" in events
    assert assess_output(cues, diagnostics=runner.diagnostics())["status"] == "unusable"


def test_unresolved_alignment_preserves_private_evidence_and_blocks_paid_work(runtime):
    connection, workflow, _, root = runtime
    text, units = "遗漏开头。已对齐。", _units("已对齐。")
    pieces = _thread_text(text, units)
    cues = _aligned_cues(pieces)
    alignment = threading_evidence(text, units, pieces)
    def infer(config, path, *, diagnostics_sink, **kwargs):
        diagnostics_sink.update({"quality": {"status": "needs-review"},
            "passes": [{"completed": True, "chunks": [{"chunk_index": 0, "alignment": alignment}]}]})
        return cues, {"language": "Chinese"}, coverage(4, max(cue["end"] for cue in cues))
    handlers = ArchiveWorkflowHandlers(connection, workflow, archive_root=root, sessdata=None, timeout_transcriber=infer)
    try:
        assert WorkflowExecutor(workflow, worker_id="alignment", handlers=handlers.handlers(), kinds=(JobKind.ASR,)).run().failed == 1
    finally:
        handlers.close()
    run = connection.execute("SELECT run_id,outcome FROM acquisition_runs WHERE kind='asr'").fetchone()
    evidence = read_assessment(connection, run_id=run["run_id"], video_part_id=1, include_evidence=True)
    assert run["outcome"] == "complete" and evidence["status"] == "unusable"
    assert evidence["evidence"]["original_segments"] == cues
    assert evidence["evidence"]["asr_evidence"]["diagnostics"]["passes"][0]["chunks"][0]["alignment"] == alignment
    assert workflow.claim("paid", kinds=(JobKind.PROOFREAD,)) is None
    attempt = connection.execute("SELECT result_json FROM workflow_attempts WHERE outcome='failed'").fetchone()[0]
    assert text not in attempt
