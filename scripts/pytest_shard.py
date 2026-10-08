"""Run one deterministic shard of the repository's pytest node ids.

The CI workflow uses this small wrapper instead of adding a parallel-test plugin
to the product environment. Collection happens in the same checkout and the
sorted node ids are distributed by position, so a changed test set still gives
stable shard ownership without a hand-maintained file list.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def _node_ids() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    node_ids = sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    )
    if not node_ids:
        raise SystemExit("pytest collection produced no test node ids")
    return node_ids


def _parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="run the selected tests with coverage's parallel data mode",
    )
    args, pytest_args = parser.parse_known_args(argv)
    if args.shard_count < 1:
        parser.error("--shard-count must be at least 1")
    if not 0 <= args.shard_index < args.shard_count:
        parser.error("--shard-index must be within --shard-count")
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    return args, pytest_args


def main(argv: list[str] | None = None) -> int:
    args, pytest_args = _parse_args(argv)
    node_ids = _node_ids()
    selected = node_ids[args.shard_index :: args.shard_count]
    print(
        f"pytest shard {args.shard_index + 1}/{args.shard_count}: "
        f"{len(selected)} of {len(node_ids)} test(s)"
    )
    command = [sys.executable]
    if args.coverage:
        command.extend(["-m", "coverage", "run", "--branch", "--parallel-mode", "-m"])
    else:
        command.extend(["-m"])
    command.extend(["pytest", *pytest_args, *selected])
    return subprocess.run(
        command,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
