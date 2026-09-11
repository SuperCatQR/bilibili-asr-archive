# CONCEPTS — bilibili-asr-archive

Project-specific domain vocabulary. General programming terms do not belong here.

| Term | Meaning |
|------|---------|
| `work_id` | Ledger key for an archive item: `bvid:p<zero-based-page-index>` for multi-part videos (bare `bvid` for single-part). Distinct from the filesystem `artifact_stem` `{bvid}.p{page_index}`, which never contains `:`. |
| `meta-cursor.json` | Archive-root sidecar persisting archival-flow enumeration state (`next_page`, `total`, `state`, `last_api_error_code`, `updated_at`); `state` ∈ `running` (never persisted) / `risk_interrupted` (the only `--resume`-consumed state) / `limited` / `complete`. Metadata-command enumeration state now lives in the SQLite `ingestion_cursors` table instead (iter-2026-09); this sidecar keeps its role only in the archival flow. |
| risk stop (exit 2) | Batch-stop on API risk-control exhaustion; persists a resumable cursor and exits 2, distinct from per-video failures and from deliberate `--limit-pages` caps. |
| evidence projection | Bounded derived report or sidecar (`campaign.json`, coverage/quality, search index, integrity report, recovery audit, gate result) that may describe manifest-owned work but never becomes a second item state machine or back-writes inferred state. |
| audit-only recovery | Explicit bounded selection of currently verified integrity defects that appends redacted recovery evidence; it does not requeue work, change manifest status, or edit transcript/audio artifacts. |
| `sequential-no-daemon` | The concurrency gate's permanent report mode in this iteration: evaluation can return `go` evidence, but no worker, daemon, service, autostart, or concurrent manifest writer is enabled without a separate approved plan. |
| `run-scoped ASR` | One lazily constructed local ASR model is owned and reused only within a sequential coordinator batch, then released according to creator ownership; it is not a global cache or a concurrency mechanism. |
| `acquisition attempt` | One append-only evidence row per attempted part inside one acquisition run: outcome (`stored` / `unchanged` / `no-subtitle` / `failed`), an optional bounded error code, and the transcript version it produced; never a per-part status. |
| `no-subtitle` | The attempt outcome meaning no usable caption track was visible for this part with the credentials in effect at that attempt — not a failure, not a success, and not a claim that the video has no captions. |
| subtitle track (with `label` and the `ai`/`cc` marker) | One inventory entry a part exposes at one moment: normalized upstream `lan`, printable `lan_doc` label, and an AI-vs-CC classification where a missing upstream marker reads as CC (an audio track or media stream is not a "track" here). |
| transcript version | An immutable revision of one `(part, source kind, language)` caption, appended when its content hash differs from every stored version and never rewritten or deleted; the source-kind vocabulary (`subtitle-ai` / `subtitle-cc` / `asr-local`) is part of its identity. |
| content identity (`content_sha256`) | The SHA-256 over the canonical JSON of the millisecond segment triples that decides whether the archive already holds this caption text, enforced by a partial unique index scoped to the caption kinds (deliberately excluding `asr-local`). |
