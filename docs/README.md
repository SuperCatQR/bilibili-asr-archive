# Docs index

Human-facing documentation that ships with the product. The README is the entry
point for installation and the command tour; these files carry the depth the
README deliberately leaves out. Historical experiment reports are kept only
when the code or tests still use them as an operator contract.

| Document | What it is | Refs |
|---|---|---|
| [ai-proofreading.md](ai-proofreading.md) | 当前工作流与 DeepSeek AI 校对的使用说明、参数、数据库及输出契约。 | — |
| [ai-proofreading-architecture.md](ai-proofreading-architecture.md) | 当前转录与校对架构说明，包含交互式架构图入口。 | — |
| [ai-proofreading-e2e-BV16jryYNEbT.md](ai-proofreading-e2e-BV16jryYNEbT.md) | 当前字幕采集、音频下载、WSL 本地 ASR、DeepSeek 校对与 Markdown 渲染的完整链路实测。 | — |
| [design-philosophy.md](design-philosophy.md) | 项目北极星：三大环节（抓取/内容处理/数据处理）、数据库四公理、五条设计哲学。方向决策的上游锚点。 | — |
| [metadata-storage.md](metadata-storage.md) | `archive.db`: the normalized SQLite store behind `fetch-meta` and `harvest-subs` — tables, views, ingestion state, and the read/write contracts. | 12 |
| [wsl-rocm-gpu.md](wsl-rocm-gpu.md) | The one AMD path **measured** to give a usable ASR device on Windows WSL2 — the ROCm/torch wheel pairing, HSA/DXG detection, and the failure chain per symptom. | 8 |
| [artifact-root.md](artifact-root.md) | `--artifact-root` operator guide: which root is which, how to place products on a mount, and why some things never leave the archive root. | 7 |
| [audio-retention-policy.md](audio-retention-policy.md) | When audio is kept and when it is reclaimed, the flag pair on the archiving commands, and the reclaim scope per base. | 1 |
| [wsl-long-live.md](wsl-long-live.md) | The opt-in acceptance procedure for one multi-hour livestream on the Windows WSL PC — run it as written; it does not change pilot defaults. | 1 |
| [wsl-long-live-evidence.md](wsl-long-live-evidence.md) | The redacted result of that acceptance, on `DESKTOP-HHFROLO` / WSL2. | 1 |
| [asr-pipeline.html](asr-pipeline.html) | Self-contained interactive diagram of the pipeline from enumeration to archived products. | 1 |
| [asr-pipeline.dataflow.json](asr-pipeline.dataflow.json) | The diagram's source data, for regeneration and review. | 1 |
Not in this directory: `notes/` (spike records kept beside the code they
informed) and `verification-results/` (the output directory of
`scripts/verify_baseline.py`; generated results are not committed).
