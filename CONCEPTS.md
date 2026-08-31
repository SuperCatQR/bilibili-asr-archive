# CONCEPTS — bilibili-asr-archive

Project-specific domain vocabulary. General programming terms do not belong here.

| Term | Meaning |
|------|---------|
| `work_id` | Ledger key for an archive item: `bvid:p<zero-based-page-index>` for multi-part videos (bare `bvid` for single-part). Distinct from the filesystem `artifact_stem` `{bvid}.p{page_index}`, which never contains `:`. |
| `meta-cursor.json` | Archive-root sidecar persisting metadata enumeration state (`next_page`, `total`, `state`, `last_api_error_code`, `updated_at`); `state` ∈ `running` (never persisted) / `risk_interrupted` (the only `--resume`-consumed state) / `limited` / `complete`. |
| risk stop (exit 2) | Batch-stop on API risk-control exhaustion; persists a resumable cursor and exits 2, distinct from per-video failures and from deliberate `--limit-pages` caps. |
