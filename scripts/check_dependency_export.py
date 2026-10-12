"""Reject deployment requirements that differ from the current locked export."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def requirements(text: str) -> list[str]:
    # Generated provenance/comments can vary with output paths or uv flags.
    # Versions, markers and every hash must still match exactly.
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path,
                        default=Path("deployment/application-requirements.txt"))
    args = parser.parse_args()
    try:
        result = subprocess.run([
            "uv", "export", "--locked", "--default-index", "https://pypi.org/simple",
            "--extra", "asr", "--extra", "dev", "--no-emit-project",
            "--no-header", "--no-annotate",
        ], check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as error:
        parser.exit(1, f"Locked dependency export failed:\n{error.stderr}")
    if requirements(args.path.read_text(encoding="utf-8")) != requirements(result.stdout):
        parser.exit(1, "Deployment dependency export differs from uv.lock. Regenerate with "
                    "uv export --locked --default-index https://pypi.org/simple --extra asr "
                    "--extra dev --no-emit-project --output-file deployment/application-requirements.txt\n")
    print("Deployment dependency versions, markers and hashes match the locked ASR/dev export")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
