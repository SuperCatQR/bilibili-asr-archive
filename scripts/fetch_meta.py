# -*- coding: utf-8 -*-
"""Deprecated research script -> thin wrapper over the installed CLI.

Superseded by `bili-asr fetch-meta` (src/bili_asr/bili_client.py), which
implements the same x/series/recArchivesByKeywords enumeration with buvid
bootstrap via x/frontend/finger/spi and the spec'd risk backoff budget.
Kept as an entry point for prior muscle memory only.
"""
import sys

from bili_asr.cli.main import main

if __name__ == "__main__":
    argv = ["fetch-meta", "--mid", "23191782"]
    if "--resume" in sys.argv:
        argv.append("--resume")
    sys.exit(main(argv))
