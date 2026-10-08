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
| [architecture.md](architecture.md) | 当前 CLI、SQLite workflow、处理与查询边界，以及状态所有权、恢复和并发策略。 | — |
| [architecture-maintenance.md](architecture-maintenance.md) | 架构图与源码证据的同步、生成和验证方式。 | — |
| [metadata-storage.md](metadata-storage.md) | `archive.db` 与 `fetch-meta` / `workflow`：表、视图、身份、命令、重试、并发与重建策略。 | — |
| [wsl-rocm-gpu.md](wsl-rocm-gpu.md) | The one AMD path **measured** to give a usable ASR device on Windows WSL2 — the ROCm/torch wheel pairing, HSA/DXG detection, and the failure chain per symptom. | 8 |
| [artifact-root.md](artifact-root.md) | `--artifact-root` operator guide: which root is which, how to place products on a mount, and why some things never leave the archive root. | 7 |
| [audio-retention-policy.md](audio-retention-policy.md) | 旧音频保留接口与底层回收模块的历史说明；当前 workflow 未接入这些 CLI 选项。 | 1 |
