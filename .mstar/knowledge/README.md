# Knowledge index

Shipped SSOT. No start-chain additions. Page-aware `work_id` / `meta-cursor.json` promoted at iteration-close (iter-2026-08-archive-foundations). Operational sidecars promoted at iter-2026-08-pilot-ops close.

| Document | Source Plan | Description | Status |
|----------|-------------|-------------|--------|
| [bilibili-asr-archive-cli.md](architecture-patterns/bilibili-asr-archive-cli.md) | iter-2026-08-wmz-asr-mvp | Single HTTP owner, `work_id`-keyed JSONL (page-aware), `meta-cursor.json` resume, optional ASR, CDN/API risk | Active |
| [operational-sidecars.md](architecture-patterns/operational-sidecars.md) | 20260825-run-coordinator-offline | Run ledger, FTS5 search/export, run coordinator `--offline`; sidecar JSONL, no manifest schema change | Active |
