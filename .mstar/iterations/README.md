# Iterations

| Iteration | Path | Description | Status |
|-----------|------|-------------|--------|
| `iter-2026-08-persistence-scale-safety` | [`iter-2026-08-persistence-scale-safety/`](iter-2026-08-persistence-scale-safety/) | M autonomous persistence/read-scale safety and reproducible local ASR execution | completed |
| `iter-2026-08-corpus-coverage` | [`iter-2026-08-corpus-coverage/`](iter-2026-08-corpus-coverage/) | XL controlled corpus coverage, telemetry, quality, search, integrity, and concurrency safety gate | completed |
| `iter-2026-08-corpus-operations` | [`iter-2026-08-corpus-operations/`](iter-2026-08-corpus-operations/) | Full-visible-corpus scheduling, long-live safety, mixed outcomes, verification baseline | completed |
| `iter-2026-08-live-pc-pilot` | [`iter-2026-08-live-pc-pilot/`](iter-2026-08-live-pc-pilot/) | Windows WSL bounded live M2; audio reclaim; 10 GiB peak | completed |
| `iter-2026-08-pilot-ops` | [`iter-2026-08-pilot-ops/`](iter-2026-08-pilot-ops/) | Executable pilot workflow, state-machine entrypoint tests, operational ledger, FTS5 search/export, offline run coordinator | completed |
| `iter-2026-08-archive-foundations` | [`iter-2026-08-archive-foundations/`](iter-2026-08-archive-foundations/) | Page-complete archive identity and resumable metadata cursor | completed |
| `iter-2026-09-funasr-nano-7800xt` | [`iter-2026-09-funasr-nano-7800xt/`](iter-2026-09-funasr-nano-7800xt/) | Migrate ASR to FunASR-Nano on AMD 7800XT GPU | completed |
| `iter-2026-09-bilibili-api-sqlite` | [`iter-2026-09-bilibili-api-sqlite/`](iter-2026-09-bilibili-api-sqlite/) | Replace metadata acquisition with bilibili-api and normalized SQLite storage | completed |
| `iter-2026-09-subtitle-transcript-sqlite` | [`iter-2026-09-subtitle-transcript-sqlite/`](iter-2026-09-subtitle-transcript-sqlite/) | Subtitle acquisition and normalized transcript storage on SQLite | completed (2026-09-11) |
| `iter-2026-09-asr-ops-hardening` | [`iter-2026-09-asr-ops-hardening/`](iter-2026-09-asr-ops-hardening/) | Truthful GPU enablement, reachable batch model reuse, one quality surface, declared provenance identity, VAD capture and low-confidence observability | `active` |

Note: the bootstrap MVP iteration `iter-2026-08-wmz-asr-mvp` — the source of the frozen
`.mstar/specs/asr-archive-cli.md` — predates this index and its package is no longer on disk;
only the frozen spec and `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md`
still reference it.
