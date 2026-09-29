"""Concurrency-evidence evaluation handler."""

from __future__ import annotations

from pathlib import Path

import json
import os
import sys

_MAX_CONCURRENCY_INPUT_BYTES = 1_048_576


class _ConcurrencyInputError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _read_concurrency_json_object(path: str) -> dict[str, object]:
    from collections.abc import Mapping

    file_path = Path(path)
    try:
        if not file_path.exists():
            raise _ConcurrencyInputError("input_file_missing")
        if not file_path.is_file():
            raise _ConcurrencyInputError("input_file_not_regular")
        with file_path.open("rb") as input_file:
            payload = input_file.read(_MAX_CONCURRENCY_INPUT_BYTES + 1)
    except _ConcurrencyInputError:
        raise
    except OSError:
        raise _ConcurrencyInputError("input_file_unreadable") from None

    if len(payload) > _MAX_CONCURRENCY_INPUT_BYTES:
        raise _ConcurrencyInputError("input_file_oversized")
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise _ConcurrencyInputError("input_invalid_utf8") from None
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError:
        raise _ConcurrencyInputError("input_malformed_json") from None
    if not isinstance(value, Mapping):
        raise _ConcurrencyInputError("input_non_object_json")
    return dict(value)


def _write_concurrency_error(error_code: str) -> None:
    payload = {
        "error_code": error_code,
        "operating_mode": "sequential-no-daemon",
    }
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )


def _cmd_evaluate_concurrency(args: argparse.Namespace) -> int:
    from bili_asr.concurrency_gate import ConcurrencyGate

    # Resolve through the package namespace so monkeypatches against
    # ``bili_asr.cli`` take effect (the test contract pins the package attributes).
    import bili_asr.cli as _cli_pkg

    try:
        evidence = _cli_pkg._read_concurrency_json_object(args.evidence)
        thresholds = _cli_pkg._read_concurrency_json_object(args.thresholds)
    except _ConcurrencyInputError as exc:
        _write_concurrency_error(exc.error_code)
        return 1

    try:
        result = ConcurrencyGate.evaluate(evidence, thresholds)
    except Exception:
        _write_concurrency_error("evaluation_failure")
        return 1

    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result.ok else 1
