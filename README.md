# Bilibili ASR Archive

This repository contains the installable `bili-asr` Python CLI for personal
archival of Bilibili UP 未明子 (UID 23191782) transcripts.

The product lives in [`bilibili-asr-archive/`](bilibili-asr-archive/). It
enumerates videos, harvests AI/CC subtitles first, downloads audio only when
needed, runs local Qwen3-ASR, and writes resumable `srt` / `txt` / `md`
products. Start with the [product README](bilibili-asr-archive/README.md),
then read the [architecture guide](bilibili-asr-archive/docs/architecture.md)
before changing module boundaries.

Repository-level checks and fixture tooling are kept under the product's
`scripts/` and `tests/` directories. The offline fixture builder stages only
`pyproject.toml`, `README.md`, and `src/`; generated environments and model
checkpoints remain local.
