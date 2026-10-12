#!/usr/bin/env python3
"""Replay explicitly selected real provider calls without network or source writes."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from bili_asr.services.editorial_evaluation import load_sample, replay_sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--call-id", action="append", required=True)
    args = parser.parse_args()
    if not 1 <= len(args.call_id) <= 5 or len(set(args.call_id)) != len(args.call_id):
        parser.error("select one to five distinct saved calls")
    try:
        reports = [replay_sample(load_sample(args.database, call_id)) for call_id in args.call_id]
    except (ValueError, KeyError, TypeError, sqlite3.Error) as error:
        # Do not print exceptions containing SQL, paths or saved model content.
        parser.exit(1, f"Evidence replay failed ({type(error).__name__})\n")
    print(json.dumps({"schema": "editorial-evaluation-v1", "mode": "offline_replay",
                      "samples": reports, "provider_parameter_enforcement": "not_verified"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
