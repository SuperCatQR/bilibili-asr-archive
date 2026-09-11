---
iteration_id: iter-2026-09-subtitle-transcript-sqlite
start_date: 2026-09-11
status: locked
iteration_base_branch: main
spec_integration_branch: iteration/iter-2026-09-subtitle-transcript-sqlite
target_branch: main
plans:
  - 20260911-subtitle-gateway
  - 20260911-transcript-storage
  - 20260911-subtitle-cli-cutover
effort_scale: M
---

# iter-2026-09-subtitle-transcript-sqlite Delivery Compass

## Scope

### Problem

The caption half of the pipeline is the last part of the archive still keyed to the JSONL
manifest. Today `harvest-subs` reads manifest rows, downloads the raw subtitle JSON into
`subtitles/raw/`, writes an SRT next to it, and records `sub_lan` / `srt_path` on a manifest
row. The operator therefore cannot query caption text, cannot count per-part caption
coverage, and cannot tell from the stored state whether a caption is AI-generated or
uploader-authored without reading file names and sidecar rows. The `transcripts` /
`transcript_segments` foreign-key boundary reserved by the previous iteration's schema plan
stays unused, so the audio/ASR iteration has no normalized target to write into. Failure
modes are equally opaque: "this part exposes no caption track" and "risk control blocked the
call" both surface as manifest status transitions rather than as bounded, actionable codes.

### User value

After this iteration the operator works against `{archive_root}/archive.db` alone and can:

- **See before downloading** — `probe-subs` lists the tracks a part actually exposes
  (language, display label, AI vs CC) without storing anything and without creating the
  database.
- **Acquire bounded, and know it was bounded** — `harvest-subs` attempts an explicitly
  bounded work set and prints every outcome count (including zeros), the run id, and how
  many parts still have no transcript. Re-running is safe: identical content writes nothing,
  changed content appends a new version, and previously stored versions stay readable.
- **Tell "no captions" from "cannot see captions"** — bounded scalar codes plus
  credential-presence reporting separate an anonymous probe that found nothing from an
  authenticated probe that found nothing, and from a risk-control block.
- **Trust the boundary** — no credential, signed subtitle URL, or raw response body reaches
  a DTO, a database row, a log line, or standard output.

The maintainer gets the typed acquisition boundary and the normalized transcript contract
the audio/ASR iteration writes into, with the head-of-line decisions (process records,
versioning, language, content idempotency) made explicitly and pinned by tests.

### Locked spec points

Phase 1 direction lock: interactive, confirmed by the user on 2026-09-11 as the roadmap's next
iteration. Three spec points, one plan each:

1. **Typed subtitle gateway** (`specs/subtitle-gateway.md`) — AI/CC track listing through the
   pin's own WBI-signed player endpoint (`x/player/wbi/v2`; the credentials in effect decide
   which login-gated tracks are visible — the pin declares no `need_login_subtitle` flag, see
   the spec) and subtitle-body download (short-lived signed URL) move off `bili_client`'s raw
   HTTP surface into the typed `sources/` boundary with application-owned DTOs and bounded
   scalar error codes; the credential and the signed URL are never persisted or logged.
2. **Normalized transcript storage** (`specs/transcript-storage.md`) — the `transcripts` /
   `transcript_segments` boundary reserved by the previous iteration's schema plan becomes
   the working store, with subtitle source (`subtitle-ai` / `subtitle-cc`), language,
   immutably versioned rows, and millisecond segments; the process-record schema for
   subtitle/transcript acquisition is decided explicitly (carry F-010: `ingestion_runs` is
   metadata-scoped).
3. **Subtitle CLI cutover** (`specs/subtitle-cli-contract.md`) — `harvest-subs` reads SQLite
   metadata and writes normalized transcript rows instead of manifest rows, `probe-subs` is a
   read-only track probe, and neither command reads or writes a JSONL sidecar.

Bounded verification closes the iteration: an offline fake-gateway E2E plus one opt-in
bounded live smoke (parts within one page of one UP, temporary archive root).

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260911-subtitle-gateway | Subtitle gateway and typed subtitle contract | Done | Merged `5dc9c40`; QC+QA Approve; R1 deferred | P0, serial 1/3. Delivers the typed caption boundary and the fake-seam parity evidence; operator effect: probe output is expressed in application terms (language, label, AI vs CC) and every failure becomes a stable code, with no credential or signed URL persisted anywhere. |
| 20260911-transcript-storage | Normalized transcript storage on the reserved tables | Done | Merged `f490fd1`; QC+QA Approve | P0, serial 2/3. Delivers the versioned, content-idempotent transcript store plus the explicit process-record decision; operator effect: captions become queryable per part, re-runs are safe, and no earlier version is ever overwritten. |
| 20260911-subtitle-cli-cutover | Subtitle CLI cutover and bounded verification | Done | Merged `d1a0b7e`; QC+QA Approve; DoD 11/11 | P0, serial 3/3, and the only plan with an operator-visible surface. Delivers `probe-subs` (read-only) and `harvest-subs` (bounded, SQLite-only), the offline E2E, one bounded live smoke, and operator docs that match the shipped behaviour. |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

Dependencies: storage (Plan 2) consumes the gateway DTOs (Plan 1); the CLI cutover (Plan 3)
consumes both. The plans are serial because no plan delivers operator value alone: Plans 1–2
are contracts and storage, and every operator-visible acceptance criterion lands in Plan 3.

## Milestones

| Milestone | Target date | Exit evidence | Status |
|-----------|-------------|---------------|--------|
| Spec freeze (review chain complete + PM lock) | 2026-09-11 | Three specs locked, plan sign-offs complete, compass `status: locked` | pending |
| Dev complete (3 plans Done) | 2026-09-12 | All three plans implemented, task-reviewed, QC tri + QA gate complete | pending |
| QC complete (per-plan tri + QA gate) | 2026-09-12 | Review/QA gate summaries filled per plan; zero open blocking findings | pending |
| Iteration close + PR | 2026-09-13 | Offline E2E green, bounded live smoke recorded, docs match behaviour, PR open against `main` | pending |

## Acceptance Criteria

Every criterion is observable by the operator (CLI output, database rows, or files present
or absent) and traceable to the plan that owns it. `P1` = `20260911-subtitle-gateway`,
`P2` = `20260911-transcript-storage`, `P3` = `20260911-subtitle-cli-cutover`.

| # | Acceptance criterion (operator-visible) | Evidence | Plan |
|---|-----------------------------------------|----------|------|
| A1 | `probe-subs` prints one line per probed part with its `work_id` (`bvid:pN`), the visible track count, and each track's language / display label / AI-vs-CC marker; parts with zero visible tracks are printed explicitly, never omitted. | CLI output over the fake seam + one bounded live probe | P3 (surface), P1 (data) |
| A2 | A bounded `harvest-subs` run stores `transcripts` + `transcript_segments` rows FK-linked to `video_parts`, with source kind (`subtitle-ai` / `subtitle-cc`), language, version 1, and milliseconds converted as `floor(seconds * 1000)`. | E2E row assertions | P2, P3 |
| A3 | Repeating the same bounded acquisition writes no new version and no duplicate segments and reports `unchanged`; a changed subtitle body appends version 2 while version 1 stays readable. | E2E re-run and body-change assertions | P2, P3 |
| A4 | A part with no usable track is reported as `no-subtitle` — not `failed`, not `stored` — and leaves bounded, timestamped per-part evidence; no success marker is written for it, and a later run may still store a transcript for that part. | E2E + process-record rows | P2, P3 |
| A5 | Caption answers map onto the existing bounded scalar codes: risk control → `rate_limited`, an expired signed URL or transport failure → `transport_error`, a malformed payload → `shape_error`, and the login signal `-101` → `not_found`, i.e. the `no-subtitle` outcome; the run never claims success for a part it could not acquire. | Taxonomy assertions + no-leak scans | P1, P3 |
| A6 | Subtitle/transcript process records have an explicit home that does not overload metadata-scoped `ingestion_runs`, pinned by schema and repository tests. | Schema/repository test evidence (carry F-010 resolved) | P2 |
| A7 | The new subtitle path reads and writes no `manifest.jsonl`, `meta-cursor.json`, or `run-ledger.jsonl`; tests assert those files are absent from the temporary archive root. | Zero-sidecar assertions | P1, P2, P3 |
| A8 | `SESSDATA`, signed `subtitle_url` values, and raw response bodies appear in no DTO, row, file, log line, or CLI output; `SESSDATA` is presence-only in display. | Sentinel no-leak scans over output and all persisted rows | P1, P3 |
| A9 | `harvest-subs` prints all four outcome counts (including zeros), the run id, credential presence (never the value), and the number of parts still pending a transcript — a bounded run is never presented as full coverage. | CLI output assertions | P3 |
| A10 | Successive bounded runs make progress: parts with a stored transcript are excluded from the pending set, and never-attempted parts are attempted before previously attempted ones. | Repository/service assertions across two runs | P2, P3 |
| A11 | Offline fake-gateway E2E is green with no network; the opt-in bounded live smoke yields real normalized rows, or records an explicit bounded blocker. | Test suite output + recorded live-smoke outcome | P3 (with P1's live probe) |
| A12 | Operator documentation matches shipped behaviour: the two commands, their bounds, the exit-code taxonomy, the preference rule, the SQLite-only projection boundary, and the untouched legacy manifest path. | README + `docs/metadata-storage.md` reviewed against the CLI | P3 |

Explicitly **not** claimed by this iteration: caption coverage across the corpus, caption
quality, that a `no-subtitle` result means the video has no captions, or that any on-disk
SRT/TXT/MD projection exists for parts harvested on the new path.

## Non-Goals

This iteration acquires subtitles and stores them normalized. It explicitly does not:

- **No audio, no ASR, no local model execution.** Audio download, audio objects, and
  `asr-local` transcripts stay out of scope: `source_kind = 'asr-local'`, `audio_objects`,
  and `asr_models` remain empty reservations owned by the next iteration.
- **No migration, no compatibility reader.** Existing `manifest.jsonl`,
  `meta-cursor.json`, `run-ledger.jsonl`, `subtitles/raw/*.json`, and `transcripts/srt/*.srt`
  files are left untouched and are never imported, reconciled, or read by the new subtitle
  path.
- **No on-disk projection on the new path.** `harvest-subs` on the SQLite path writes
  neither `subtitles/raw/*.json` nor `transcripts/srt/*.srt`; the transcript lives in
  `archive.db`. Rebuilding SRT/TXT/MD projections from the database for newly harvested
  parts is deferred work owned by `project-manager`, trigger "this iteration delivered"
  (see Roadmap Position). Pre-existing projection files stay valid for parts harvested
  before this iteration.
- **No legacy-path migration or retirement.** `download-audio`, `asr`, `pilot`, `run`,
  `campaign`, `schedule`, `export`, `coverage`, and `search` keep their current
  manifest/sidecar behaviour. Consequence to state plainly: the new subtitle path no longer
  produces the manifest status `needs_audio`, so the legacy audio feeder
  (`download-audio --missing-subs`) receives no new entries after this iteration; audio
  acquisition for newly harvested parts is deferred to the next iteration.
- **No second source of truth.** No parallel executable, no `v2` runtime, no second metadata
  store: the subtitle path reads and writes only `{archive_root}/archive.db`.
- **No new export format, search index, vector store, cloud storage, or multi-user
  authentication.**
- **No coverage claims.** A green bounded run, exit code `0`, or a `no-subtitle` count say
  nothing about the corpus as a whole, about caption quality, or about what a different
  credential tier would see for the same part.

## Roadmap Position

- **Current iteration (`iter-2026-09-subtitle-transcript-sqlite`)** — mandate from the
  previous iteration's roadmap: move subtitle acquisition and transcript storage out of the
  JSONL-manifest world into the normalized SQLite stack and honour the reserved FK boundary.
  **Done when**: subtitle tracks and transcript segments are queryable through normalized
  tables, no sidecar is (re)introduced on the subtitle path, and the operator-visible
  criteria A1–A12 above hold.
- **Carry-in resolutions**: carry **F-010** (process records for subtitle/transcript work
  must be decided explicitly because `ingestion_runs` is metadata-scoped) is resolved by Plan
  2 and pinned by tests. Carry **C3** (`ingestion_cursors.state = 'risk_interrupted'` has no
  producer) is untouched and must stay untouched: the subtitle path introduces no cursor
  state and does not depend on one.
- **Next iteration (audio/ASR)** — audio download (external objects) plus local ASR
  execution (FunASR-Nano / SenseVoice), with transcript segments versioned per model/run.
  Trigger: this iteration delivered. Owner: `project-manager`. It inherits three explicit
  inputs from this iteration: the normalized transcript contract, the process-record shape
  (reused with `kind='audio'` / `kind='asr'`), and the enumeration of parts with no
  transcript — including parts recorded as `no-subtitle`, which the audio path needs as its
  work queue. Rebuilding SRT/TXT/MD projections from SQLite is also owned there.
- **Final vision** — a personal long-lived speech-to-text archive where all metadata, audio
  references, and transcript segments are queryable in SQLite, and SRT/TXT/MD are rebuildable
  projections rather than canonical state.

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot `{WORKFLOW_DIR}/<id>/snapshot.json` `branch` anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main`（AGENTS.md 项目约定 + 上一迭代同构；非静默默认） |
| `spec_integration_branch` | `iteration/iter-2026-09-subtitle-transcript-sqlite` |
| `target_branch` | `main`（最终 PR 目标） |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Caption availability is not a fixed property.** AI tracks are auto-generated and may not exist yet for a part, uploader CC may be absent entirely, and login-gated tracks are only visible when a credential is in effect — so `no-subtitle` is an artifact of this credential at this time, not proof of absence. | High | High | Define `no-subtitle` in the specs and docs as "no usable track was visible for this part with the credentials in effect", print credential presence with every run, keep such parts eligible for later attempts, and never store a terminal "unavailable" state. |
| **Operator expectation: the legacy audio feeder stops being fed.** `harvest-subs` no longer writes the manifest status `needs_audio`, so `download-audio --missing-subs` finds nothing new for parts harvested on the SQLite path. | High | Med | Record the boundary in Non-Goals, in the CLI spec, and in `docs/metadata-storage.md`; name the next iteration (audio/ASR) as the owner of audio enumeration from SQLite; leave pre-existing `needs_audio` entries working. |
| **Operator expectation: no SRT/raw JSON file for newly harvested parts.** The new path stores only SQLite rows, so the file-based workflow the operator has today changes shape. | High | Med | Declare it as a Non-Goal with a named owner and trigger, document it in README + `docs/metadata-storage.md`, and keep pre-existing files untouched. |
| **Track-selection change.** The legacy harvest preferred `ai-zh` first (`subtitles.pick_subtitle`); the new default prefers uploader/human captions over AI for the same language, which can select a different track for the same part. | Med | Med | Locked mechanism (CLI spec §3): the default is defined on the language family (`ai-` prefix stripped for AI tracks, then the lowercase primary subtag), ranked `zh`, `en`, then the rest in upstream order, with CC before AI inside a family — so the CC-before-AI property holds for any upstream code pair, pinned by a property test. Documented in CLI help and docs; the stored `source_kind` + language + version are printed per part; `--language` matches exactly the code `probe-subs` prints, so the other track stays reachable. |
| Subtitle endpoints need login / hit risk control (`-101` / `-352` / 412) | Med | High | Locked call shape (spec §1.2): endpoint mirror from the pin's own description, `dm=False`, `verify=False`, `bvid`-based declared parameter set, package-owned bounded `-403` re-sign. `-101` maps to `not_found` on the subtitle methods only; `-352`/`-412`/`-799` and HTTP 412/429 map to `rate_limited`. The live smoke may record a bounded blocker instead of failing the iteration; a refusal of the locked shape is an escalation, not a licence to fabricate fingerprint parameters. |
| **Undeclared-parameter folklore re-enters the call.** `need_login_subtitle` and `w_webid` are absent from the pin's player endpoint description (verified: no occurrence in the installed package; the package's own player call sends neither), yet both were requested by the pre-review spec and the legacy `probe_subs` docstring. | Med | Med | Recorded as a pin fact in the gateway spec §1.1, enforced by the seam parity test (the recorded call's parameter set is asserted), and listed as a STOP condition in the gateway plan: undeclared parameters are not added to make a call pass. |
| Signed URL expiry window on subtitle-body download | Med | Med | The URL never crosses the gateway boundary: `fetch_subtitle_segments` re-lists, matches the track by `language` + `is_ai` (`track_id` tie-break), and allows at most one extra listing + fetch pair on an expiry/transport-class failure (never on `rate_limited`), pinned by the seam's exact call list. |
| **Partial coverage read as success.** A bounded run that exits `0` because every attempted part had no captions can be mistaken for "the archive is covered". | Med | Med | Always print all four outcome counts (including zeros), the run id, credential presence, and how many parts still lack a transcript; Acceptance A9 and the docs make this checkable. |
| **Bounded runs fail to advance.** If parts with no usable track stay in the pending set without ordering, repeated bounded runs re-attempt the same parts and never reach later ones. | Med | Med | Require deterministic enumeration that prefers never-attempted parts over previously attempted ones (Acceptance A10) and assert progress across two runs. |
| Process-record schema decision conflicts with metadata run semantics | Med | Med | Locked: a separate `kind`-keyed pair `acquisition_runs` + `acquisition_attempts` (one attempt row per attempted part, append-only evidence, no terminal per-part state), reusable by the audio/ASR iteration with `kind='audio'`/`'asr'`; `ingestion_runs` and its views untouched (carry F-010 resolved), pinned by schema and repository tests. |
| **A pre-iteration `archive.db` cannot accept the widened `transcripts` table.** `CREATE TABLE IF NOT EXISTS` does not alter an existing table, and the live-collected metadata database from the previous iteration has the old shape. | High | Med | Rebuild-only stance made executable: the schema splits into `schema.sql` + `schema-transcripts.sql`, `initialize_schema` skips the transcript script when the table is legacy (nothing half-applies, metadata commands keep working), and both subtitle commands call `require_subtitle_schema` and exit `1` with the fixed rebuild line. No `ALTER TABLE`, no backfill, no compatibility reader. |
| **The anonymous probe fails locally instead of honestly.** In the pinned `Api`, `verify=True` only raises when no SESSDATA is configured, so mirroring it would turn "nothing visible anonymously" into an exception. | Med | High | `verify=False` is a locked, documented adapter override with the pin's semantics recorded in the gateway spec §1.2; credential presence stays the operator-visible distinction (the `sessdata:` line, presence-only), and `acquisition_runs.credential_present` keeps the stored evidence interpretable. |
| **`probe-subs` silently keeps write-side effects.** It is currently an archive-writer command, so it takes `coordinator/archive-writer.lock` (creating a file, and the root) even though the spec promises a read-only probe that never creates the database. | Med | Med | Remove `probe-subs` from `_ARCHIVE_WRITER_COMMANDS` in the CLI plan; the E2E asserts that a probe leaves no new file under the archive root and does not create a missing database. |
| Legacy manifest path and the new SQLite path coexist as two state machines | Med | Med | Non-Goal: only the subtitle path is migrated; ASR/pilot/audio still run on the manifest, and the boundary — including the `needs_audio` feeder gap — is stated in the specs and docs. |
| `transcript_segments` time-axis precision drifts (seconds vs milliseconds) | Low | Med | Both sides pin milliseconds: the gateway converts with `floor(seconds * 1000)` (the same rule as `duration_ms`, deliberately **not** `subtitles.json_to_srt`'s `round()`), drops any segment violating `end_ms > start_ms >= 0`, and the repository re-validates the same bounds at the DB boundary (CHECK plus `ValueError`), with conversion tests on both sides. |
| Caption text quality (AI errors, punctuation, segmentation) is mistaken for a defect of the new path | Low | Low | Docs state that the store preserves upstream text verbatim and makes no quality claim; quality tooling is future work. |

## Iteration package

> Sibling paths under `{ITERATION_DIR}/<iteration-id>/` — not in `{SPECS_DIR}/` or `{KNOWLEDGE_DIR}/`. Promoted to knowledge at iteration-close via **`mstar-compound`**.

| Path | Purpose |
|------|---------|
| `guides/` | Process notes; created only if this iteration accumulates exploration notes |
| `specs/` | Iteration-scoped spec drafts (subtitle-gateway / transcript-storage / subtitle-cli-contract) |
| `README.md` | Package document index |

## Quality Gate Summary

> Filled at iteration-close. Human summary only; per-plan gate details stay in each main plan, and open residual SSOT stays in `{PROJECT_DIR}/<id>/residuals.json`.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260911-subtitle-gateway | pending | mandatory | pending | `{PLAN_DIR}/20260911-subtitle-gateway.md#review-gate-summary` |
| 20260911-transcript-storage | pending | mandatory | pending | `{PLAN_DIR}/20260911-transcript-storage.md#review-gate-summary` |
| 20260911-subtitle-cli-cutover | pending | mandatory | pending | `{PLAN_DIR}/20260911-subtitle-cli-cutover.md#review-gate-summary` |

Notes:

- Raw review bundle: `{SDD_DIR}/review/` (ephemeral; do not rely on it after Done).
- Open residual SSOT: `{PROJECT_DIR}/<id>/residuals.json` `entries[<plan-id>]` (default `{HARNESS_DIR}/projects/<id>/`).

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：pending
- 新增 CONCEPTS.md 条目：pending
- 触发 compound-refresh：pending

Prepare-stage promotion candidates (registered by writing-specialist, 2026-09-11; judged at
iteration-close by `mstar-compound` — the Prepare chain mints no knowledge):

- `specs/transcript-storage.md` §2–§3 — the transcript / process-record contract
  (`acquisition_runs` + `acquisition_attempts`, content-hash idempotency, the rebuild stance and
  the `require_subtitle_schema` guard). The strongest promotion candidate: the next
  (audio/ASR) iteration consumes it directly.
- `specs/subtitle-gateway.md` §1–§2 — pin facts (`need_login_subtitle` absent, `w_webid` specific
  to the user-video endpoint, why `dm`/`verify` are overridden) and the bounded re-list rule.
  Transport knowledge, adjacent to the shipped
  `{KNOWLEDGE_DIR}/architecture-patterns/normalized-metadata-stack.md`.
- `specs/subtitle-cli-contract.md` §3 — the language-family preference mechanism and its
  CC-before-AI property test. A CLI-convention candidate.
- `{SPECS_DIR}/README.md` now carries this iteration's frozen-MVP supersession notes; at close,
  decide whether a formal supersession record is warranted.

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- 做得好的：
- 可改进的：
- 下迭代建议：
