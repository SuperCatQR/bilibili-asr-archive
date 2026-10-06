# Docs index

Human-facing documentation that ships with the product. The README is the entry
point for install and the command tour; these files carry the depth the README
deliberately leaves out. Reference counts are tracked-surface hits at
2026-09-25 and only tell you what is already load-bearing.

| Document | What it is | Refs |
|---|---|---|
| [architecture.md](architecture.md) | Current module ownership, runtime boundaries, repository transactions, pipeline stages, search indexes, and test support layout. | — |
| [design-philosophy.md](design-philosophy.md) | 项目北极星：三大环节（抓取/内容处理/数据处理）、数据库四公理、五条设计哲学。方向决策的上游锚点。 | — |
| [roadmap.md](roadmap.md) | 阶段路线图：Phase 0 事件流可信（已完成）→ Phase 0.5 证据层加深（在飞）→ 处理器骨架 → 缺口队列 → 谓词收敛 → 画面/评论/关系。 | — |
| [roadmap-gantt.md](roadmap-gantt.md) | 路线图的甘特图（Mermaid）：Phase 0–7 的相对工期、关键路径、压缩空间，锚定当前在飞迭代。 | — |
| [metadata-storage.md](metadata-storage.md) | `archive.db`: the normalized SQLite store behind `fetch-meta` and `harvest-subs` — tables, views, ingestion state, and the read/write contracts. | 12 |
| [wsl-rocm-gpu.md](wsl-rocm-gpu.md) | The one AMD path **measured** to give a usable ASR device on Windows WSL2 — the ROCm/torch wheel pairing, HSA/DXG detection, and the failure chain per symptom. | 8 |
| [artifact-root.md](artifact-root.md) | `--artifact-root` operator guide: which root is which, how to place products on a mount, and why some things never leave the archive root. | 7 |
| [audio-retention-policy.md](audio-retention-policy.md) | When audio is kept and when it is reclaimed, the flag pair on the archiving commands, and the reclaim scope per base. | 1 |
| [wsl-long-live.md](wsl-long-live.md) | The opt-in acceptance procedure for one multi-hour livestream on the Windows WSL PC — run it as written; it does not change pilot defaults. | 1 |
| [wsl-long-live-evidence.md](wsl-long-live-evidence.md) | The redacted result of that acceptance, on `DESKTOP-HHFROLO` / WSL2. | 1 |
| [asr-pipeline.html](asr-pipeline.html) | Self-contained interactive diagram of the pipeline from enumeration to archived products. | 1 |
| [asr-pipeline.dataflow.json](asr-pipeline.dataflow.json) | The diagram's source data, for regeneration and review. | 1 |
| [archive/pre-iteration-2026-09/](archive/pre-iteration-2026-09/README.md) | Design exploration and prototypes from **before** `iter-2026-09-bilibili-api-sqlite`. Rationale only — **not current truth**; that directory's README maps each file to what actually shipped. | — |

Not in this directory: `notes/` (spike records kept beside the code they
informed) and `verification-results/` (the output directory of
`scripts/verify_baseline.py`; generated results are not committed).
