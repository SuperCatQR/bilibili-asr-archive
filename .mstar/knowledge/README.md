# Knowledge index

Shipped SSOT. No start-chain additions. Page-aware `work_id` / `meta-cursor.json` promoted at iteration-close (iter-2026-08-archive-foundations). Operational sidecars promoted at iter-2026-08-pilot-ops close; scheduler, mixed-outcome, and installed-baseline contracts refreshed at iter-2026-08-corpus-operations; campaign, coverage, quality, explorer, integrity/audit-only recovery, and concurrency-gate guidance refreshed at iter-2026-08-corpus-coverage.

| Document | Source Plan | Description | Status |
|----------|-------------|-------------|--------|
| [bilibili-asr-archive-cli.md](architecture-patterns/bilibili-asr-archive-cli.md) | iter-2026-08-wmz-asr-mvp; iter-2026-08-corpus-coverage | Single HTTP owner, `work_id`-keyed JSONL, resumable sequential scheduling, optional ASR, transient audio budget, installed baseline, and measured non-enabling concurrency decision chain; refreshed at iter-2026-08-corpus-coverage | Active |
| [operational-sidecars.md](architecture-patterns/operational-sidecars.md) | 20260825-run-coordinator-offline; iter-2026-08-corpus-coverage; iter-2026-08-persistence-scale-safety | Run/attempt ledgers, durable append/projection and single-writer boundaries, scheduler and campaign checkpoints, coverage/quality projections, atomic transcript publication, confined integrity verification, audit-only recovery, and concurrency gate | Active |
| [run-scoped-asr-provenance.md](architecture-patterns/run-scoped-asr-provenance.md) | 20260831-asr-reproducibility | Sequential run-scoped model reuse, ownership-aware cleanup, fixture-injectable construction, and redaction-safe local ASR provenance | Active |
