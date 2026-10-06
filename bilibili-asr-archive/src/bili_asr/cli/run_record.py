"""One run-ledger record around a complete batch command invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import ExitStack
from functools import wraps
import signal
from typing import Any, Callable

from bili_asr.diagnostics import write_stderr


@dataclass
class CommandRunRecord:
    root: str
    command: str
    started_at: str | None = None
    exit_code: int = 1
    interrupted: bool = False
    records_existing: int | None = None
    work_ids: list[str] | None = None
    # Pilot has no coordinator attempt ledger; retain the rows it actually entered.
    visited_work_ids: list[str] = field(default_factory=list)
    hotwords_dropped: list[str] = field(default_factory=list)
    last_api_error_code: int | str | None = None
    cursor_snapshot: dict[str, Any] | None = None
    capture_cursor: bool = False


def _append_record(state: CommandRunRecord) -> None:
    from bili_asr import cli
    from bili_asr.manifest import ManifestStore
    from bili_asr.meta_cursor import MetaCursorStore
    from bili_asr.run_ledger import RunLedger, build_run_record, compute_coverage_summary, utc_now_iso

    started_at = state.started_at or utc_now_iso()
    coverage: dict[str, int] = {}
    work_ids = state.work_ids
    try:
        if state.interrupted:
            work_ids, coverage = cli._partial_run_state(state.root, started_at)
            work_ids = list(dict.fromkeys([*work_ids, *state.visited_work_ids])) or None
        else:
            coverage = compute_coverage_summary(ManifestStore(root=state.root).load())
        if state.capture_cursor:
            state.cursor_snapshot = MetaCursorStore(root=state.root).load()
    except Exception:
        # State projection can fail during an early-load interruption. A minimal
        # record still accounts for this invocation, without inventing counts.
        if state.interrupted:
            work_ids = list(dict.fromkeys(state.visited_work_ids)) or None
        write_stderr(f"{state.command}: run-ledger state unavailable")

    try:
        RunLedger(root=state.root).append(build_run_record(
            command=state.command,
            started_at=started_at,
            finished_at=utc_now_iso(),
            exit_code=state.exit_code,
            work_ids=work_ids,
            records_existing=state.records_existing,
            last_api_error_code=state.last_api_error_code,
            coverage_summary=coverage,
            cursor_snapshot=state.cursor_snapshot,
            hotwords_dropped=state.hotwords_dropped,
        ))
    except Exception:
        # Do not emit exception payloads or even attacker-controlled class names.
        write_stderr(f"{state.command}: run-ledger write failed")


def recorded_command(command: str) -> Callable:
    """Install interruption handling before command loads or constructs anything.

    CLI package aliases are looked up at invocation time so existing hooks for
    signal guards and partial-state projection continue to work after the split.
    The archive writer lock is already owned at the CLI dispatch boundary.
    """
    def decorate(handler: Callable) -> Callable:
        @wraps(handler)
        def invoke(args: Any) -> int:
            from bili_asr import cli
            from bili_asr.run_ledger import utc_now_iso

            state = CommandRunRecord(root=args.archive_root, command=command)
            args._run_record = state
            with cli._interruptible_run():
                try:
                    state.started_at = utc_now_iso()
                    state.exit_code = handler(args)
                except cli._RunInterrupted as exc:
                    state.interrupted = True
                    state.exit_code = 128 + exc.signum
                except KeyboardInterrupt:
                    # A manually raised KeyboardInterrupt (including library
                    # cancellations) follows the same exit contract as SIGINT.
                    state.interrupted = True
                    state.exit_code = 128 + signal.SIGINT
                finally:
                    with ExitStack() as protection:
                        try:
                            protection.enter_context(cli._signals_ignored())
                        except cli._RunInterrupted as exc:
                            # First delivery while entering the write guard is
                            # still before any append; the handler already made
                            # repeated deliveries inert, so finishing is safe.
                            state.interrupted = True
                            state.exit_code = 128 + exc.signum
                            protection.enter_context(cli._signals_ignored())
                        except KeyboardInterrupt:
                            state.interrupted = True
                            state.exit_code = 128 + signal.SIGINT
                            protection.enter_context(cli._signals_ignored())
                        _append_record(state)
            return state.exit_code
        return invoke
    return decorate
