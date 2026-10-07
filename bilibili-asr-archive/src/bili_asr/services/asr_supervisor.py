"""Run the ASR CLI in a killable worker process.

GPU/native inference can wedge without returning control to Python.  The parent
process therefore owns no model and no archive lock; it only watches phase
heartbeats and terminates the worker when one phase exceeds its deadline.
"""
from __future__ import annotations

import math
import os
import secrets
import signal
import socket
import subprocess
import sys
import time

from bili_asr.diagnostics import write_stderr
from bili_asr.services.bundle_verification import _worker_environment

DEFAULT_ASR_TIMEOUT_SECONDS = 900.0
ASR_TIMEOUT_ENV_VAR = "BILI_ASR_TIMEOUT_SECONDS"
_UNREAPED: list[subprocess.Popen] = []
_PROGRESS: socket.socket | None = None
_FRAME_LIMIT = 4096


def _timeout_from_environment() -> float:
    raw = os.environ.get(ASR_TIMEOUT_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_ASR_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{ASR_TIMEOUT_ENV_VAR} must be finite and positive") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{ASR_TIMEOUT_ENV_VAR} must be finite and positive")
    return value


def inference_phase(phase: str) -> None:
    """Send one authenticated heartbeat from the worker to its parent."""

    _send_frame({"load": "L", "decode": "D", "align": "A"}[phase])


def asr_run_started(run_id: str) -> None:
    """Tell the parent which acquisition run belongs to this worker."""

    _send_frame("R", run_id)


def asr_part_started(video_part_id: int) -> None:
    """Tell the parent which part is active when native inference begins."""

    _send_frame("P", str(video_part_id))


def _send_frame(kind: str, value: str | None = None) -> None:
    if _PROGRESS is None:
        return
    frame = kind if value is None else f"{kind}:{value}"
    _PROGRESS.sendall(frame.encode("ascii") + b"\n")


def _command(port: int, token: str, argv: list[str]) -> list[str]:
    return [sys.executable, "-m", __name__, str(port), token, *argv]


def _terminate(worker: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except OSError:
            pass
    else:
        try:
            killer = subprocess.Popen(
                ["taskkill", "/PID", str(worker.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                killer.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                killer.kill()
                _UNREAPED.append(killer)
        except OSError:
            pass
        try:
            worker.kill()
        except OSError:
            pass
    try:
        worker.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        _UNREAPED.append(worker)


def _finalize_timed_out_run(
    archive_root: str | os.PathLike[str] | None,
    run_id: str | None,
    video_part_id: int | None,
) -> None:
    """Close the worker's ASR run after a hard timeout, best-effort and idempotently."""

    if archive_root is None or run_id is None:
        return
    connection = None
    try:
        from bili_asr.services import _common
        from bili_asr.storage import TranscriptRepository
        from bili_asr.storage.database import open_database

        connection = open_database(archive_root)
        repository = TranscriptRepository(connection)
        row = connection.execute(
            "SELECT outcome FROM acquisition_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None or row["outcome"] != "running":
            return
        now = _common._now()
        if video_part_id is not None:
            repository.record_asr_failure(
                run_id=run_id,
                video_part_id=video_part_id,
                error_code="inference_timeout",
                started_at=now,
                finished_at=now,
            )
        repository.finish_acquisition_run(run_id, now, outcome="failed")
    except Exception:
        # The worker has already been stopped.  Do not replace the useful
        # timeout diagnostic with a database payload or traceback.
        write_stderr("asr: timeout recovery could not finalize acquisition run")
    finally:
        if connection is not None:
            connection.close()


def supervise_asr(
    argv: list[str],
    *,
    timeout_seconds: float | None = None,
    archive_root: str | os.PathLike[str] | None = None,
) -> int:
    """Run ``asr`` with a bounded worker-owned inference lock."""

    try:
        timeout = _timeout_from_environment() if timeout_seconds is None else timeout_seconds
    except ValueError as exc:
        write_stderr(f"asr: {exc}")
        return 1
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        write_stderr("asr: ASR timeout must be finite and positive")
        return 1
    if not math.isfinite(timeout) or timeout <= 0:
        write_stderr("asr: ASR timeout must be finite and positive")
        return 1
    _UNREAPED[:] = [worker for worker in _UNREAPED if worker.poll() is None]
    if len(_UNREAPED) >= 4:
        write_stderr("asr: ASR worker capacity exhausted")
        return 1

    token = secrets.token_hex(16)
    worker: subprocess.Popen | None = None
    progress: socket.socket | None = None
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.setblocking(False)
        deadline = time.monotonic() + float(timeout)
        try:
            worker = subprocess.Popen(
                _command(listener.getsockname()[1], token, argv),
                stdout=sys.stdout,
                stderr=sys.stderr,
                env=_worker_environment(),
                close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name == "posix",
            )
            authenticated = False
            greeting = b""
            frames = b""
            run_id: str | None = None
            video_part_id: int | None = None
            while True:
                status = worker.poll()
                if status is not None:
                    return status if status >= 0 else 1
                if time.monotonic() >= deadline:
                    _terminate(worker)
                    _finalize_timed_out_run(archive_root, run_id, video_part_id)
                    write_stderr(
                        "asr: inference deadline exceeded; invocation stopped; "
                        "unfinished item remains retryable"
                    )
                    return 1
                if progress is None:
                    try:
                        progress, _ = listener.accept()
                        progress.setblocking(False)
                    except BlockingIOError:
                        pass
                if progress is not None:
                    try:
                        data = progress.recv(4096)
                    except BlockingIOError:
                        data = None
                    if data:
                        if not authenticated:
                            greeting += data
                            prefix = token.encode("ascii") + b"\n"
                            if len(greeting) >= len(prefix):
                                if greeting[: len(prefix)] != prefix:
                                    raise OSError("invalid ASR progress channel")
                                authenticated = True
                                data = greeting[len(prefix) :]
                        if authenticated and data:
                            frames += data
                            if len(frames) > _FRAME_LIMIT:
                                raise OSError("ASR progress frame buffer exceeded")
                            while b"\n" in frames:
                                frame, frames = frames.split(b"\n", 1)
                                if frame in {b"L", b"D", b"A"}:
                                    deadline = time.monotonic() + float(timeout)
                                elif frame.startswith(b"R:"):
                                    candidate = frame[2:].decode("ascii")
                                    if not candidate or "\n" in candidate:
                                        raise OSError("invalid ASR run frame")
                                    run_id = candidate
                                    deadline = time.monotonic() + float(timeout)
                                elif frame.startswith(b"P:"):
                                    try:
                                        candidate_part = int(frame[2:].decode("ascii"))
                                    except (UnicodeDecodeError, ValueError):
                                        raise OSError("invalid ASR part frame") from None
                                    if candidate_part < 1:
                                        raise OSError("invalid ASR part frame")
                                    video_part_id = candidate_part
                                    deadline = time.monotonic() + float(timeout)
                                else:
                                    raise OSError("invalid ASR progress event")
                time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))
        except OSError:
            if worker is not None:
                _terminate(worker)
                _finalize_timed_out_run(archive_root, run_id, video_part_id)
            write_stderr("asr: supervisor failed")
            return 1
        except BaseException:
            if worker is not None:
                _terminate(worker)
                _finalize_timed_out_run(archive_root, run_id, video_part_id)
            raise
        finally:
            if progress is not None:
                progress.close()


def _worker() -> int:
    import bili_asr.asr.runner as runner
    from bili_asr.services import queue_source

    port, token, *argv = sys.argv[1:]
    with socket.create_connection(("127.0.0.1", int(port)), timeout=5) as progress:
        progress.sendall(token.encode("ascii") + b"\n")
        global _PROGRESS
        _PROGRESS = progress
        runner.set_progress_hook(inference_phase)
        queue_source.set_asr_supervision_hooks(asr_run_started, asr_part_started)
        try:
            from bili_asr.cli.main import _main

            return _main(argv, _asr_worker=True)
        finally:
            runner.set_progress_hook(None)
            queue_source.set_asr_supervision_hooks(None, None)
            _PROGRESS = None


if __name__ == "__main__":
    raise SystemExit(_worker())
