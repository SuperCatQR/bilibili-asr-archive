# Pre-iteration design archive (2026-09)

Design exploration and prototypes written **before** the
`iter-2026-09-bilibili-api-sqlite` iteration. Preserved for rationale and future
work — **not current truth**. For the shipped contracts, read:

- `.mstar/knowledge/architecture-patterns/normalized-metadata-stack.md` — the
  delivered gateway → ingestor → 3NF SQLite repository layering (knowledge SSOT).
- `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/` — the frozen
  iteration specs (storage, gateway, CLI contract).
- `src/bili_asr/storage/schema.sql` — the shipped schema (the authoritative DDL).

## Delivered by iter-2026-09 (as normalized SQLite, not the file layout sketched here)

- 3NF metadata tables (`bilibili_users`, `videos`, `video_parts`) with views-only
  derived values (`work_id`, counts) and `ON DELETE RESTRICT` foreign keys.
- Ingestion state as normalized rows (`ingestion_runs`, `ingestion_pages`,
  `ingestion_cursors`, `ingestion_discoveries`) replacing the JSONL manifest /
  cursor / run-ledger metadata roles — with **no migration**.
- Typed gateway boundary over `bilibili-api-python==17.4.2` + resumable
  `MetadataIngestor` + SQLite-backed `fetch-meta` / `status` / `runs` commands.

## Not yet delivered (candidate future iterations)

- **Content-addressed blobs**: audio/transcript SHA-256 dedup and immutable
  versioning (`content-addressed-storage.md`, `prototypes/content_addressed_store.py`).
- **Dual-store split** (`state.db` process state vs results DB) — the shipped
  design keeps one `archive.db` (`storage-architecture.md`).
- **Transcript segment versioning / exports** — currently schema reservations only.
- Audio retention is now a **config switch** (`BILI_KEEP_AUDIO=1`, see
  `docs/audio-retention-policy.md`) rather than the always-keep policy sketched here.

## Contents

| Path | What it is |
|------|------------|
| `REDESIGN-PLAN.md`, `DELIVERY-REPORT.md` | V2 redesign plan and the prototype delivery report |
| `content-addressed-storage.md`, `storage-architecture.md`, `schema-3nf-guide.md` | storage design docs from the prototype round |
| `data-acquisition-flow.md`, `bilibili-api-evaluation.md`, `bilibili-api-verification-report.md` | data-source research that fed the iteration's specs |
| `refactor-implementation-report.md` | prototype implementation report |
| `prototypes/*.py` | standalone prototype stores (`archive_store_v2`, `content_addressed_store`) + their e2e test — not imported by the package |
| `prototypes/schema-3nf.sql`, `prototypes/schema-proposal.sql` | prototype DDL — **do not copy as-is**; the shipped schema differs (`src/bili_asr/storage/schema.sql`) |

The prototype scratch data (`archive-v2/` blobs, `index.db`, exports) stayed
gitignored under `refactor/` — it is regenerable and contains local media samples.
