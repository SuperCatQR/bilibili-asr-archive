# Specs index

Warehouse-level locked specs. Iteration drafts live under `{ITERATION_DIR}/<id>/specs/`, not here.

| Spec | Status | Notes |
|------|--------|-------|
| [asr-archive-cli.md](asr-archive-cli.md) | frozen | MVP from `iter-2026-08-wmz-asr-mvp`. JSONL and artifacts remain bvid-keyed. The file is frozen and is **not** back-edited; the lines below record what later iterations superseded. |
| [proofread.md](proofread.md) | active | Proofread pipeline contract landed by the 2026-09-28 reconciliation (`8e6419e`): the `proofread` / `proofread-merge` surface, its idempotency rule, and the sidecar shape. |

## Supersession notes (frozen specs are never back-edited)

`asr-archive-cli.md` stays frozen. The following lines no longer describe the shipped system and
are superseded without editing that file:

- **Page-aware delta** — `work_id` (`bvid:pN`), `meta-cursor.json`, and the page-aware ledger are
  **not** in the frozen file; see `{ITERATION_DIR}/iter-2026-08-archive-foundations/`.
- **Module boundary** — its `bili_client.py` line (`bili_client.py` owning all Bilibili HTTP,
  including `player/wbi/v2` and subtitle JSON) is superseded by the typed
  `src/bili_asr/sources/` gateway: metadata by `iter-2026-09-bilibili-api-sqlite`, subtitle
  listing/body by `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/`.
- **Subtitle CLI surface** — the frozen `probe-subs [--limit N]` / `harvest-subs [--limit N]`
  block is superseded for those two commands by
  `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/subtitle-cli-contract.md`
  (bounded `--limit-parts` / `--bvid` / `--language`, no JSONL sidecar on that path). The frozen
  `probe-subs` line never matched the shipped parser either: legacy `probe-subs` required
  `--bvid` and had no `--limit`. Every other command keeps the frozen surface.
- **`subtitles.py` orchestration line** — subtitle `probe`/`harvest` orchestration moves to
  `sources/` + `services/subtitle_ingest.py`. `json_to_srt` keeps its place as the legacy
  manifest path's SRT formatter; the new transcript path pins `floor(seconds * 1000)` for its
  millisecond conversion, deliberately not that `round()` rule.
- **`{SPECS_DIR}` scope** — no new `{SPECS_DIR}` file is written during Prepare for
  `iter-2026-09-subtitle-transcript-sqlite`; promotion of its contracts is decided at
  iteration-close.

The frozen spec's ADR reference
(`.mstar/iterations/iter-2026-08-wmz-asr-mvp/specs/adr-001-architecture.md`) no longer resolves:
that iteration package is not on disk (see `{ITERATION_DIR}/README.md`).
