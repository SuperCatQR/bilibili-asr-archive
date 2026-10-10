"""Real spawn-process faults without a GPU or model downloads."""

from __future__ import annotations

import multiprocessing
import errno
import os
import signal
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from bili_asr.asr.config import ASRConfig
from bili_asr.asr.runner import ASRInferenceTimeoutError
from bili_asr.asr.session import AsrInferenceSession, InferenceRequest, InferenceSessionError


class ProcessRunner:
    def __init__(self, config):
        if config.model_name == "startup-error":
            raise ValueError("sensitive /private/model/path token-value")
        self.config = config
        self.calls = 0
        self.paired = None

    def set_hotword_evidence(self, *, evidence_text, paired_subtitle_text):
        self.paired = paired_subtitle_text

    def transcribe(self, path, *, bust_cache=False):
        self.calls += 1
        if path == "hang":
            time.sleep(20)
        if path == "error":
            raise ValueError("sensitive /model/path signed-url?secret=value")
        if path == "crash":
            os._exit(9)
        if path.startswith("orphan:"):
            sleeper = subprocess.Popen(["sleep", "30"])
            Path(path.removeprefix("orphan:")).write_text(str(sleeper.pid))
            os._exit(9)
        if path.startswith("holdgilchild:"):
            import ctypes
            sleeper = subprocess.Popen(["sleep", "30"])
            Path(path.removeprefix("holdgilchild:")).write_text(str(sleeper.pid))
            ctypes.PyDLL(None).sleep(20)
        if path == "large":
            return [{"start": 0, "end": 1, "text": "x" * 1024}] * 4096
        return [{"start": 0, "end": 1, "text": path + ":" + str(self.paired)}]

    def rebuild_hotwords_from_first_pass(self, _text):
        return []

    def provenance(self):
        return {"language": "Chinese", "pid": str(os.getpid())}

    def transcribed_coverage(self):
        return {"calls": self.calls}

    def diagnostics(self):
        return {"calls": self.calls, "quality": {"status": "not-evaluable"}}

    def release(self):
        pass


def request(attempt=1, *, binding=None):
    return InferenceRequest("job-" + str(attempt), "worker", attempt, "f" * 64, binding or {})


def invoke(session, path="first", *, config=None, attempt=1, timeout=8, checkpoint=lambda: None, binding=None):
    diagnostics = {}
    result = session.transcribe(config or ASRConfig(model_name="offline", device="cpu"), path, request=request(attempt, binding=binding),
        paired_subtitle_text=str(attempt), timeout_seconds=timeout, checkpoint=checkpoint,
        diagnostics_sink=diagnostics)
    return result, diagnostics


def test_real_spawn_reuses_models_with_independent_output_and_request_identity():
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    try:
        first, first_evidence = invoke(session)
        second, second_evidence = invoke(session, "second", attempt=2)
        assert first[0][0]["text"] == "first:1"
        assert second[0][0]["text"] == "second:2"
        assert first[1]["pid"] == second[1]["pid"]
        assert first_evidence["calls"] == 1 and second_evidence["calls"] == 2
        assert first_evidence["session"]["reused"] is False
        assert second_evidence["session"]["reused"] is True
        assert first_evidence["session"]["request_id"] != second_evidence["session"]["request_id"]
        assert second_evidence["session"]["identity"]["attempt_count"] == 2
        assert second_evidence["session"]["parent_clock"]["process_id"] == os.getpid()
        assert second_evidence["session"]["configuration_key"] == first_evidence["session"]["configuration_key"]
        assert second_evidence["session"]["parent_clock"]["domain_id"] != first_evidence["session"]["parent_clock"]["domain_id"]
    finally:
        session.close()
    assert session._process is None


@pytest.mark.parametrize("change", ["model", "binding", "revision", "batch", "compile", "attention"])
def test_full_configuration_and_runtime_identity_rebuild_session(change):
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    try:
        first, _ = invoke(session)
        config = ASRConfig(model_name="offline", device="cpu")
        binding = None
        if change == "model":
            config = replace(config, model_name="other-model")
        elif change == "revision":
            config = replace(config, aligner_revision="other-revision")
        elif change == "batch":
            config = replace(config, asr_batch_size=2)
        elif change == "compile":
            config = replace(config, asr_cache_implementation="static", asr_compile=True)
        elif change == "attention":
            config = replace(config, aligner_attention="sdpa")
        else:
            binding = {"manifest_sha256": "a" * 64}
        second, evidence = invoke(session, attempt=2, config=config, binding=binding)
        assert first[1]["pid"] != second[1]["pid"]
        assert evidence["session"]["rebuild_reason"] == "configuration_changed"
        assert evidence["calls"] == 1
    finally:
        session.close()


@pytest.mark.parametrize("path,error", [("hang", ASRInferenceTimeoutError),
                                       ("error", InferenceSessionError), ("crash", InferenceSessionError)])
def test_timeout_error_crash_reap_and_next_task_rebuild(path, error):
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    try:
        first, _ = invoke(session)
        with pytest.raises(error) as caught:
            invoke(session, path, timeout=0.5 if path == "hang" else 8)
        assert "sensitive" not in str(caught.value)
        assert session._process is None
        recovered, evidence = invoke(session, "recovered", attempt=2)
        assert recovered[1]["pid"] != first[1]["pid"]
        assert evidence["calls"] == 1
    finally:
        session.close()


def test_cancellation_during_inflight_request_discards_result_and_reaps_process():
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    try:
        invoke(session)
        pid = session._process.pid
        deadline = time.monotonic() + 0.2
        def cancelled():
            if time.monotonic() >= deadline:
                raise RuntimeError("attempt revoked")
        with pytest.raises(RuntimeError, match="attempt revoked"):
            invoke(session, "hang", checkpoint=cancelled)
        assert session._process is None
        if os.name == "posix":
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        result, evidence = invoke(session, "new-attempt", attempt=2)
        assert result[0][0]["text"] == "new-attempt:2"
        assert evidence["calls"] == 1
    finally:
        session.close()


def test_runner_construction_failure_is_sanitized_at_the_process_boundary(capfd):
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    try:
        with pytest.raises(InferenceSessionError):
            invoke(session, config=ASRConfig(model_name="startup-error", device="cpu"))
        assert "sensitive" not in capfd.readouterr().err
        assert session._process is None
        recovered, _ = invoke(session)
        assert recovered[0][0]["text"] == "first:1"
    finally:
        session.close()


def test_large_ipc_response_is_drained_before_join_and_oneshot_restarts():
    session = AsrInferenceSession(runner_factory=ProcessRunner, persistent=False)
    try:
        first, _ = invoke(session, "large")
        assert len(first[0]) == 4096
        assert session._process is None
        second, _ = invoke(session)
        assert second[1]["pid"] != first[1]["pid"]
    finally:
        session.close()


def test_mismatched_late_response_cannot_be_consumed_by_a_new_request():
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    try:
        _, evidence = invoke(session)
        stale = {"protocol": 1, "generation": evidence["session"]["generation"],
            "request_id": evidence["session"]["request_id"], "identity": request().identity(),
            "ok": True, "segments": [{"start": 0, "end": 1, "text": "stale"}], "provenance": {}}
        session._responses.put(stale)
        with pytest.raises(InferenceSessionError, match="identity mismatch"):
            invoke(session, "hang", attempt=2)
        assert session._process is None
        recovered, _ = invoke(session, "fresh", attempt=3)
        assert recovered[0][0]["text"] == "fresh:3"
    finally:
        session.close()


def _process_is_live(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        # procfs can return ESRCH after open succeeds but before read finishes.
        return False
    # A zombie no longer executes or holds GPU state; init owns reaping.
    return state != "Z"


@pytest.mark.parametrize("error", [FileNotFoundError(errno.ENOENT, "gone"),
                                  ProcessLookupError(errno.ESRCH, "gone")])
def test_process_probe_accepts_disappearance_during_read(monkeypatch, error):
    def disappeared(_path):
        raise error
    monkeypatch.setattr(Path, "read_text", disappeared)
    assert not _process_is_live(123)


@pytest.mark.parametrize("state,live", [("S", True), ("R", True), ("Z", False)])
def test_process_probe_distinguishes_live_and_zombie_states(monkeypatch, state, live):
    monkeypatch.setattr(Path, "read_text", lambda _: f"123 (worker with ) spaces) {state} 1 2 3")
    assert _process_is_live(123) is live


def test_process_probe_does_not_hide_permission_failures(monkeypatch):
    def denied(_path):
        raise PermissionError(errno.EACCES, "denied")
    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError):
        _process_is_live(123)


@pytest.mark.skipif(os.name != "posix", reason="POSIX owned process group cleanup")
def test_crashed_session_leader_reaps_its_remaining_decoder_process(tmp_path):
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    child_file = tmp_path / "decoder.pid"
    try:
        with pytest.raises(InferenceSessionError):
            invoke(session, "orphan:" + str(child_file))
        decoder_pid = int(child_file.read_text())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not _process_is_live(decoder_pid):
                break
            time.sleep(0.02)
        else:
            pytest.fail("decoder survived its crashed inference group leader")
    finally:
        session.close()


def _parent_with_session(pipe, decoder_file=None):
    session = AsrInferenceSession(runner_factory=ProcessRunner)
    result, _ = invoke(session)
    pipe.send(int(result[1]["pid"]))
    invoke(session, "hang" if decoder_file is None else "holdgilchild:" + decoder_file, timeout=40)


@pytest.mark.skipif(os.name != "posix", reason="POSIX parent death and process-group proof")
def test_parent_sigkill_during_inference_does_not_leave_live_child():
    context = multiprocessing.get_context("spawn")
    read, write = context.Pipe(duplex=False)
    parent = context.Process(target=_parent_with_session, args=(write,))
    parent.start()
    write.close()
    try:
        assert read.poll(10)
        child_pid = read.recv()
        os.kill(parent.pid, signal.SIGKILL)
        parent.join(timeout=3)
        deadline = time.monotonic() + 5
        live = True
        while time.monotonic() < deadline:
            live = _process_is_live(child_pid)
            if not live:
                break
            time.sleep(0.05)
        assert not live
    finally:
        if parent.is_alive():
            parent.kill()
            parent.join(timeout=3)
        parent.close()
        read.close()


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="Linux kernel parent death signal")
def test_parent_sigkill_while_model_holds_gil_cleans_gpu_and_decoder(tmp_path):
    context = multiprocessing.get_context("spawn")
    read, write = context.Pipe(duplex=False)
    decoder_file = tmp_path / "decoder.pid"
    parent = context.Process(target=_parent_with_session, args=(write, str(decoder_file)))
    parent.start()
    write.close()
    try:
        assert read.poll(10)
        gpu_pid = read.recv()
        deadline = time.monotonic() + 5
        while not decoder_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        decoder_pid = int(decoder_file.read_text())
        os.kill(parent.pid, signal.SIGKILL)
        parent.join(timeout=2)
        for pid in (gpu_pid, decoder_pid):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not _process_is_live(pid):
                    break
                time.sleep(0.02)
            else:
                pytest.fail(f"owned process survived parent death: {pid}")
    finally:
        if parent.is_alive():
            parent.kill()
            parent.join(timeout=2)
        parent.close()
        read.close()
