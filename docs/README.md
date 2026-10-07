# Docs index

Human-facing documentation that ships with the product. The README is the entry
point for installation and the command tour; these files carry the depth the
README deliberately leaves out. Historical experiment reports are kept only
when the code or tests still use them as an operator contract. The current
system map is the source of truth for module boundaries and data ownership.

| Document | What it is | Refs |
|---|---|---|
| [ai-proofreading.md](ai-proofreading.md) | 当前工作流与 DeepSeek AI 校对的使用说明、参数、数据库及输出契约。 | — |
| [ai-proofreading-architecture.md](ai-proofreading-architecture.md) | 当前转录与校对架构说明，包含交互式架构图入口。 | — |
| [metadata-storage.md](metadata-storage.md) | `archive.db`: the normalized SQLite store behind `fetch-meta` and `harvest-subs` — tables, views, ingestion state, and the read/write contracts. | 12 |
| [wsl-rocm-gpu.md](wsl-rocm-gpu.md) | The one AMD path **measured** to give a usable ASR device on Windows WSL2 — the ROCm/torch wheel pairing, HSA/DXG detection, and the failure chain per symptom. | 8 |
| [artifact-root.md](artifact-root.md) | `--artifact-root` operator guide: which root is which, how to place products on a mount, and why some things never leave the archive root. | 7 |
| [audio-retention-policy.md](audio-retention-policy.md) | When audio is kept and when it is reclaimed, the flag pair on the archiving commands, and the reclaim scope per base. | 1 |
