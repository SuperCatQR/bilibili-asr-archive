"""A bounded, killable model session. Durable ownership always stays in the parent."""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from .config import ASRConfig
from .runner import ASRInferenceTimeoutError, ASRRunner, two_pass_transcribe

_DECODER_GUARDS: list[subprocess.Popen] = []


class InferenceSessionError(RuntimeError):
    """A session failed without disclosing model paths or third-party errors."""

    error_code = "inference_session_failed"


@dataclass(frozen=True)
class InferenceRequest:
    job_id: str
    owner: str
    attempt_count: int
    profile_digest: str
    runtime_binding: Mapping[str, Any]

    def identity(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "owner": self.owner,
                "attempt_count": self.attempt_count, "profile_digest": self.profile_digest,
                "runtime_binding": dict(self.runtime_binding)}


def _parent_guard() -> None:
    """Exit even when inference is blocked and the parent is killed without cleanup."""
    parent = multiprocessing.parent_process()
    original_parent = os.getppid()
    while True:
        time.sleep(0.1)
        if (parent is not None and not parent.is_alive()) or os.getppid() != original_parent:
            if os.name == "posix":
                # The session starts its own process group. This also owns its ffmpeg children.
                os.killpg(os.getpgrp(), signal.SIGKILL)
            os._exit(1)


def _session_worker(config, commands, responses, generation, runner_factory, prefetch, prefetch_bytes):
    if os.name == "posix":
        os.setsid()
    if sys.platform.startswith("linux"):
        # Native inference may hold the GIL. Linux's parent-death signal still
        # kills the GPU owner when a Python guardian thread cannot run.
        import ctypes
        creator = multiprocessing.parent_process()
        expected_parent = creator.pid if creator is not None else os.getppid()
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise RuntimeError("cannot establish inference parent-death ownership")
        if os.getppid() != expected_parent:
            os._exit(1)
    if os.name == "posix":
        # A separate interpreter can observe EOF after the GPU owner is killed,
        # including by the kernel parent-death signal. It also cleans up decoder
        # descendants when the leader no longer exists. No model modules load here.
        guard_code = (
            "import os,signal,sys;sys.stdin.buffer.read();"
            "os.killpg(int(sys.argv[1]),signal.SIGKILL)"
        )
        _DECODER_GUARDS.append(subprocess.Popen([sys.executable, "-c", guard_code, str(os.getpid())],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    threading.Thread(target=_parent_guard, daemon=True, name="asr-parent-guard").start()
    runner = None
    try:
        while True:
            command = commands.get()
            if command is None:
                return
            envelope = {key: command[key] for key in ("protocol", "generation", "request_id", "identity")}
            if command["protocol"] != 1 or command["generation"] != generation:
                return
            try:
                if runner is None:
                    runner = runner_factory(config)
                    if prefetch:
                        configure = getattr(runner, "configure_prefetch", None)
                        if callable(configure):
                            configure(enabled=True, max_bytes=prefetch_bytes)
                segments = two_pass_transcribe(runner, command["audio_path"],
                                              paired_subtitle_text=command["paired_subtitle_text"])
                responses.put({**envelope, "ok": True, "segments": segments,
                               "provenance": runner.provenance(), "coverage": runner.transcribed_coverage(),
                               "diagnostics": runner.diagnostics()})
            except BaseException as exc:  # noqa: BLE001 - complete the process protocol on model errors.
                responses.put({**envelope, "ok": False, "error_type": type(exc).__name__[:64]})
                # A failure may leave CUDA state or task-local state corrupt. Never reuse it.
                return
    finally:
        if runner is not None:
            runner.release()


class AsrInferenceSession:
    """One sequential GPU lane, rebuilt on configuration changes or any failed request."""

    def __init__(self, *, persistent: bool = True, runner_factory: Callable = ASRRunner,
                 context: Any = None, prefetch: bool = False, prefetch_bytes: int = 64 * 1024 * 1024):
        if isinstance(prefetch_bytes, bool) or prefetch_bytes < 1:
            raise ValueError("prefetch_bytes must be positive")
        self.persistent = persistent
        self.runner_factory = runner_factory
        self.context = context or multiprocessing.get_context("spawn")
        self.prefetch, self.prefetch_bytes = prefetch, prefetch_bytes
        self._process = self._commands = self._responses = None
        self._key = None
        self._generation = 0
        self._lock = threading.Lock()
        self._previous_finish: float | None = None
        self._reason = "initial"

    @staticmethod
    def configuration_key(config: ASRConfig, request: InferenceRequest) -> str:
        raw = json.dumps({"config": asdict(config), "runtime_binding": dict(request.runtime_binding)},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _start(self, config: ASRConfig, key: str) -> None:
        self._generation += 1
        self._commands = self.context.Queue(maxsize=1)
        self._responses = self.context.Queue(maxsize=1)
        self._process = self.context.Process(target=_session_worker,
            args=(config, self._commands, self._responses, self._generation,
                  self.runner_factory, self.prefetch, self.prefetch_bytes),
            name=f"bili-asr-session-{self._generation}", daemon=True)
        try:
            self._process.start()
        except BaseException:
            self.terminate()
            raise
        self._key = key

    def transcribe(self, config: ASRConfig, audio_path: str, *, request: InferenceRequest,
                   paired_subtitle_text: str | None, timeout_seconds: float,
                   checkpoint: Callable[[], None] = lambda: None,
                   diagnostics_sink: dict[str, Any] | None = None):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("an inference session accepts one active request")
        try:
            checkpoint()
            key = self.configuration_key(config, request)
            if self._process is not None and (self._key != key or not self._process.is_alive()):
                self._reason = "configuration_changed" if self._key != key else "child_exited"
                self.terminate()
            reused = self._process is not None
            if self._process is None:
                self._start(config, key)
            request_id = uuid4().hex
            envelope = {"protocol": 1, "generation": self._generation,
                        "request_id": request_id, "identity": request.identity()}
            start = time.monotonic()
            deadline = start + timeout_seconds
            self._commands.put({**envelope, "audio_path": audio_path,
                                "paired_subtitle_text": paired_subtitle_text}, timeout=min(1, timeout_seconds))
            while True:
                checkpoint()
                if time.monotonic() >= deadline:
                    raise ASRInferenceTimeoutError("ASR inference deadline elapsed; session terminated")
                try:
                    result = self._responses.get(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
                except queue.Empty:
                    if not self._process.is_alive():
                        # A final queue feeder may still be delivering. Give it one bounded drain.
                        try:
                            result = self._responses.get(timeout=min(0.2, max(0.001, deadline - time.monotonic())))
                        except queue.Empty:
                            raise InferenceSessionError("ASR session exited without a result") from None
                    else:
                        continue
                if any(result.get(key) != value for key, value in envelope.items()):
                    raise InferenceSessionError("ASR session response identity mismatch")
                checkpoint()
                if time.monotonic() >= deadline:
                    raise ASRInferenceTimeoutError("ASR result arrived after the request deadline")
                if not result.get("ok"):
                    raise InferenceSessionError("ASR session failed; restart required")
                diagnostics = dict(result.get("diagnostics") or {})
                diagnostics["session"] = {"schema_version": 1, "generation": self._generation,
                    "request_id": request_id, "identity": request.identity(), "reused": reused,
                    "rebuild_reason": None if reused else self._reason,
                    "parent_wall_s": time.monotonic() - start,
                    "task_gap_s": None if self._previous_finish is None else start - self._previous_finish,
                    "mode": "persistent" if self.persistent else "oneshot"}
                if diagnostics_sink is not None:
                    diagnostics_sink.clear()
                    diagnostics_sink.update(diagnostics)
                self._previous_finish = time.monotonic()
                if not self.persistent:
                    self.close()
                return list(result["segments"]), dict(result["provenance"]), result.get("coverage")
        except BaseException:
            self._reason = "request_failed"
            self.terminate()
            raise
        finally:
            self._lock.release()

    def terminate(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.pid is not None:
            if process.is_alive():
                try:
                    if os.name == "posix" and os.getpgid(process.pid) == process.pid:
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                except ProcessLookupError:
                    pass
                process.join(timeout=1)
                if process.is_alive():
                    try:
                        if os.name == "posix" and os.getpgid(process.pid) == process.pid:
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    process.join(timeout=1)
            else:
                process.join(timeout=0)
            if os.name == "posix":
                # A crashed group leader can leave ffmpeg alive in its owned group.
                # Group IDs remain reserved while members exist; never scan or kill
                # unrelated PIDs to find these descendants.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.close()
        self._key = None
        for name in ("_commands", "_responses"):
            channel = getattr(self, name)
            if channel is not None:
                channel.cancel_join_thread()
                channel.close()
                setattr(self, name, None)

    def close(self) -> None:
        if self._process is not None and self._process.is_alive():
            try:
                self._commands.put(None, timeout=0.1)
                self._process.join(timeout=1)
            except queue.Full:
                pass
        self.terminate()
