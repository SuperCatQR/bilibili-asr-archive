# iter-2026-09-subtitle-transcript-sqlite — iteration package

Phase 1 package for the subtitle/transcript iteration. Main artifacts:

| Path | Purpose |
|------|---------|
| `delivery-compass.md` | Iteration SSOT: scope, plans, acceptance, non-goals, branch policy, close summaries |
| `specs/subtitle-gateway.md` | Spec point 1 — typed subtitle acquisition over the pinned package |
| `specs/transcript-storage.md` | Spec point 2 — normalized transcript storage + process-record decision |
| `specs/subtitle-cli-contract.md` | Spec point 3 — CLI subtitle path on SQLite |
| `guides/` | Process notes; created only if this iteration accumulates exploration notes |

Plan files live in `{PLAN_DIR}` (`.mstar/plans/`):

- `20260911-subtitle-gateway.md`
- `20260911-transcript-storage.md`
- `20260911-subtitle-cli-cutover.md`

Phase 1 status: scaffolding written by PM; specs and plans were edited by the Review & Edit
chain (product-manager → architect → writing-specialist), and the chain is complete pending the
PM lock. The product intent pass completed 2026-09-11 (product-manager), the architecture pass
completed 2026-09-11 (architect: all three specs carry `Status: architecture locked
(2026-09-11)` and all three plans carry `Architecture: reviewed (architect, 2026-09-11)`), and
the writing/corpus hygiene pass completed 2026-09-11 (writing-specialist: all three specs carry
`writing/corpus hygiene reviewed (writing-specialist, 2026-09-11)`, all three plans carry
`Writing/corpus hygiene: reviewed (writing-specialist, 2026-09-11)`). No knowledge additions
happen in this chain (`{KNOWLEDGE_DIR}` is fed by `mstar-compound` at iteration-close).

## What the iteration delivers (operator view)

Against `{archive_root}/archive.db` only:

1. `probe-subs` lists the tracks a part exposes — language, display label, AI vs CC —
   without storing anything and without creating the database.
2. `harvest-subs` runs a bounded acquisition and stores normalized transcript rows
   (`transcripts` + `transcript_segments`), reporting all four outcome counts including the
   zeros, the run id, credential presence, and how many parts still lack a transcript.
3. Re-running is safe: identical content is a no-op, changed content appends a version, and
   earlier versions stay readable.

Corpus coverage, caption quality, and on-disk SRT/TXT/MD projections for newly harvested
parts are explicitly **not** claimed by this iteration (see the compass `## Non-Goals`).

## Behaviour changes vs the legacy subtitle path

These are deliberate and documented, so the cutover does not surprise the operator:

- `probe-subs` / `harvest-subs` no longer read or write `manifest.jsonl`,
  `meta-cursor.json`, or `run-ledger.jsonl`; the database is the only source of truth on this
  path.
- `harvest-subs` writes no `subtitles/raw/*.json` and no `transcripts/srt/*.srt`; the
  transcript lives in `archive.db` (projection rebuild is deferred, owner `project-manager`).
- `harvest-subs` no longer produces the manifest status `needs_audio`, so
  `download-audio --missing-subs` receives no new entries from this path; the audio work
  queue moves to SQLite in the next iteration.
- Default track preference becomes uploader/human captions before AI captions for the same
  language (the legacy `subtitles.pick_subtitle` preferred `ai-zh` first). `--language`
  overrides the order, and the stored source kind + language are reported per run.
- `harvest-subs` requires a bound — `--limit-parts N`, or a single explicit `bvid:pN` part.
  `--bvid` addresses parts with the archive's own `bvid` / `bvid:pN` vocabulary.
- A part reported as `no-subtitle` means "no usable track was visible with the credentials in
  effect at that attempt", not "the video has no captions"; such parts stay eligible for a
  later attempt.

## Carry-over from the previous iteration

- Subtitle/transcript process records must be decided explicitly: `ingestion_runs`
  is metadata-scoped (carry F-010 from `iter-2026-09-bilibili-api-sqlite` plan 3 QC).
  Resolved by `20260911-transcript-storage` and pinned by schema/repository tests.
- `ingestion_cursors.state = 'risk_interrupted'` still has no producer (carry C3);
  the subtitle path must not depend on it and introduces no cursor state.
- Transport lessons are reusable: declare/keep the HTTP backend, resolve the proxy
  explicitly, prefer the WBI-signed package call with `dm` disabled, and pin call shapes with
  an offline fake-seam parity test. **The `w_webid` half of that lesson is endpoint-specific**
  (the user-video page endpoint declares it and answers HTTP 412 without it); the player
  endpoint declares neither `w_webid` nor `need_login_subtitle`, and the subtitle adapter sends
  neither — see `specs/subtitle-gateway.md` §1.1/§1.2.
  See `{KNOWLEDGE_DIR}/architecture-patterns/normalized-metadata-stack.md`.
- Documented behaviour is an acceptance item: the previous iteration closed with
  docs-accuracy findings, so this package makes "docs match shipped behaviour" an explicit
  acceptance criterion (A12) and a plan-3 task.
