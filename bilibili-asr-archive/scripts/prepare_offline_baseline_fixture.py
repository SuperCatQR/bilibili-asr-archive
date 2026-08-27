#!/usr/bin/env python3
"""Build a disposable offline package set and optionally run the baseline."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
def cached_wheels() -> list[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "cache", "list", "--format=abspath"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in proc.stdout.splitlines() if line.endswith(".whl")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="run verify_baseline.py after creating the fixture")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {args.output}")
    args.output.mkdir(parents=True)
    try:
        wheels = cached_wheels()
        if not wheels:
            raise SystemExit("no cached wheels available; provide a complete offline package directory instead")
        for wheel in wheels:
            shutil.copy2(wheel, args.output / Path(wheel).name)
        if args.run:
            return subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_baseline.py",
                    "--offline-packages",
                    str(args.output.resolve()),
                    "--advisory-snapshot",
                    "tests/fixtures/advisories-empty.json",
                ],
                cwd=ROOT,
            ).returncode
        return 0
    except Exception:
        shutil.rmtree(args.output, ignore_errors=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
