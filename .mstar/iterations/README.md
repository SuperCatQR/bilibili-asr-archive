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
| `iter-2026-09-asr-ops-hardening` | [`iter-2026-09-asr-ops-hardening/`](iter-2026-09-asr-ops-hardening/) | Truthful GPU enablement, reachable batch model reuse, one quality surface, declared provenance identity, VAD capture and low-confidence observability; delivered 2026-09-13 | `completed` |
| `iter-2026-09-residual-closeout` | [`iter-2026-09-residual-closeout/`](iter-2026-09-residual-closeout/) | One manifest well-formedness definition for every reader, and the intermittent suite red made diagnosable (scope reduced to 1 plan 2026-09-18; the cue-writer, hotword and ledger plans deferred — see compass Roadmap Position) | `completed` |
| `iter-2026-09-text-and-ledger-precision` | [`iter-2026-09-text-and-ledger-precision/`](iter-2026-09-text-and-ledger-precision/) | The residuals the previous iteration deferred: the six homophone hotwords measured by A/B (R3 closed — the benefit is 扬弃's alone), the pilot attempt-ledger boundary written down (R4), and an interrupted run that now records itself (R5); the cue-writer criterion was retired on evidence and R6 stays open. Delivered 2026-09-18; merged to `main` as `476dc9a` | `completed` |
| `iter-2026-09-artifact-root` | [`iter-2026-09-artifact-root/`](iter-2026-09-artifact-root/) | Make the audio/product output location configurable (`--artifact-root`/`BILI_ARTIFACT_ROOT`) so the products can live outside the archive root while state stays; the confinement guard is re-based and audio retention becomes a flag defaulting to retain | `completed` (2026-09-19) |
| `iter-2026-09-queue-bridge` | [`iter-2026-09-queue-bridge/`](iter-2026-09-queue-bridge/) | The ASR/audio chain takes its work queue from `archive.db` instead of a hand-built manifest (the queue half of the medium residual `e2e-…·R1`); the SRT/TXT/MD projection rebuild is deferred | `completed` |
| `iter-2026-09-transcript-projections` | [`iter-2026-09-transcript-projections/`](iter-2026-09-transcript-projections/) | The deferred projection half: a stored transcript in `archive.db` becomes a complete archive bundle (four artifact families + marker, products on the configured artifact root) so the caption path can produce products at all; the `check-asr-env` anchor fix rides along | `completed` (2026-09-20) |

Note: the bootstrap MVP iteration `iter-2026-08-wmz-asr-mvp` — the source of the frozen
`.mstar/specs/asr-archive-cli.md` — predates this index and its package is no longer on disk;
only the frozen spec and `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md`
still reference it.
