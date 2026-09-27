---
spec_id: queue-cutover-contract
title: Queue cutover — archive.db as the sole work queue
status: draft
owner: architect
created_at: 2026-09-27
iteration: iter-2026-09-coverage-truth
---

# Queue cutover contract (iteration-scoped draft)

> Drafted by the architect seat of the Phase-1 review-and-edit chain (PM-invoked,
> seat 2 of 3). Frozen at iteration-close; promotion to `{SPECS_DIR}` is
> `mstar-compound`'s call, not this chain's.

## 1. Current state (ground truth, verified on disk 2026-09-27)

- `fetch-meta` / `status` / `runs` / `probe-subs` / `harvest-subs` already read
  and write **only** `archive.db` (`docs/metadata-storage.md` §Subtitle
  acquisition: "archive.db is the only destination").
- `v_pending_metadata` (`processing_status='discovered'`) and `v_pending_subtitles`
  (no stored transcript, not `gone`, newest-attempt outcome attached) already
  exist as the store's work-list views.
- The ASR/audio chain (`download-audio`, `asr --pending`, `pilot`, `run`,
  `schedule`, `campaign`) reads **only** `manifest/manifest.jsonl`.
- `derive-manifest` is the sole bridge: additive append of `needs_audio` rows
  per `v_pending_subtitles` part. Its two known defects die with it:
  - `iter-2026-09-queue-bridge · R2` — a legacy bare-`bvid` row is not consulted
    as the same effective key, so an already-archived part is re-appended.
  - store facts are never read back: ASR results stay out of `archive.db`
    (`e2e-23191782-asr-vs-subtitle-webdav · R3`).

## 2. Target module boundaries

| Concern | Owner | Notes |
|---------|-------|-------|
| Queue selection (which parts need audio / ASR) | `storage/database.py` — new read API (§4) | single place; CLI handlers never SQL |
| Result write-back (transcript stored / audio acquired / outcome) | `storage/database.py` — new write API | per-part, immediate (not run-end); mirrors manifest attempt timing |
| Attempt ledger | `manifest.py` (unchanged writer) | `run`/`coordinator` keep appending attempt rows; **nothing reads them for queue decisions** |
| CLI input assembly | `cli.py` handlers | swap manifest-scan → store-API call |
| Outcome mapping (no-subtitle vs failed) | `services/subtitle_ingest.py` | §5 |
| State-set convergence | `storage/schema.sql` + `services/metadata_ingest.py` | §6 |

## 3. Data contracts

- **Manifest demoted**: keeps its existing row shape as attempt ledger. The
  compat read window (§7) keeps *readers* (`publish-transcripts`'s
  `already_published`, `verify`/`coverage`'s defect attribution) untouched for
  this iteration; dashboard-plan reads store-side interfaces for new surfaces.
- No manifest row is ever *read to decide work* after cutover. The selection
  predicate lives in one SQL view family (`v_pending_*`), one module.
- Effective-key rule: store identity is `(bvid, page_index)`. Legacy bare-bvid
  manifest rows remain readable but are never consulted for queue decisions —
  the R2 defect class disappears because there is no append step to duplicate.

## 4. Store read/write API (the interface BOTH plans code against)

**Amended + named by architect (seat 2)** — `QueueStore` renamed
`MediaQueueRepository` to sit beside the existing `MetadataRepository` /
`TranscriptRepository` in `storage/database.py`. One read model (`QueueGapItem`,
gap-keyed) serves both the cutover's CLI/coordinator handlers (per-stage
selection = filter `list_queue_gaps` by the matching `gap`) and the dashboard's
status/coverage surfaces; the write model is the two `mark_*` methods below.

```text
# storage/database.py — MediaQueueRepository (new, narrow; read side)
@dataclass(frozen=True, slots=True)
class QueueGapItem:
    work_id: str          # "{bvid}:p{page_index}"
    bvid: str
    page_index: int
    gap: str              # ∈ {"missing_subtitle","missing_audio","missing_transcript"}
    pubdate: int          # videos.pubdate; sort key (newest first)
    video_title: str
    duration_ms: int
    newest_outcome: str | None    # newest attempt outcome for this part/gap kind
    newest_error_code: str | None
    attempt_count: int

    def list_queue_gaps(self, *, gap: str,
                        limit: int | None = None) -> list[QueueGapItem]: ...
    def count_queue_gaps(self) -> dict[str, int]: ...
        # → {"missing_subtitle": n, "missing_audio": n, "missing_transcript": n}

    # write side (consumed by cutover's CLI/coordinator handlers, not the dashboard)
    def mark_audio_acquired(self, part: PartRef, audio_ref) -> None: ...
    def mark_transcript_stored(self, part: PartRef, transcript_ref) -> None: ...
```

**Gap-group predicates**（dashboard D7 的三个组名在此落为 store 侧判据；组序固定
`缺字幕 → 缺音频 → 缺转写`，组内排序 `pubdate DESC, bvid ASC, page_index ASC`——
确定性必须不依赖 merge 顺序）：

| 组 | Predicate |
|----|-----------|
| 缺字幕 | no stored transcript AND `processing_status != 'gone'`（即 `v_pending_subtitles` 的既有定义，不重建） |
| 缺音频 | **not in** 缺字幕 AND no audio evidence in store（见下） |
| 缺转写 | has audio evidence AND no stored transcript |

- **缺音频 evidence 边界（两 iteration 的写面切分，architect 定稿）**：
  `audio_objects` / `part_audio_objects` 的**首个 writer 是 iter-2026-09-metadata-audio-layout
  的 audio-inventory plan**（`derive-audio-inventory`，已 registered、Prepare-gated
  pass，同主机并行）。本契约**不**写这两张表；cutover 的 `mark_audio_acquired`
  把音频获得证据写进 **caption-only 的 `acquisition_attempts`（`kind='audio'`）**。
  因此"audio evidence"在缺音频/缺转写判据里 = **store 中任一 audio 证据**：
  - 新鲜库：`acquisition_attempts(kind='audio', outcome='stored')` **或**
    `part_audio_objects` 行（audio-inventory 写入后）；
  - 旧库（既有 archive.db）：attempts 表无 `kind` 列（CREATE IF NOT EXISTS 不补列），
    故旧库缺音频判据退化为"无 transcript 且 attempts 无 audio 行"，可能 over-select
    已下载音频的 part——**可接受的过渡态**；operator 重建 archive.db（既有 rebuild
    流程）或 audio-inventory 的 backfill 收敛后自动精确。
  - `acquisition_runs.kind` 的 CHECK 已含 `'audio'`、`acquisition_attempts` 的
    outcome CHECK 是 caption-only——见 §5/§10 的 fresh-vs-old 边界。
- `QueueGapItem.work_id` is always the store-native `"{bvid}:p{page_index}"`
  (a legacy bare-bvid manifest row never reaches the queue; only the readers
  see it during the compat window).
- `evidence-dashboard` codes its status/coverage queries against these
  `list_queue_gaps` / `count_queue_gaps` methods plus read-only counters —
  no second SQL home.
- Schema evolution constraint (from `metadata-storage.md` + queue-bridge's
  no-widening rule): `CREATE … IF NOT EXISTS` only, **no `ALTER`**, no migration.
  New columns arrive as **new tables/views**; these methods are the only consumers.

## 5. Subtitle outcome mapping (closes `20260925-archive-db-review · R1`, high)

**Amended by architect (seat 2)** after verifying the shipped gateway on disk
2026-09-27 — the earlier draft's premise (gateway can't distinguish a dead
credential) is wrong for the shipped seam:

- The shipped gateway **already** answers a dead/invalid credential on the
  subtitle listing as `not_found` (`_SUBTITLE_NOT_FOUND_API_CODES =
  _NOT_FOUND_API_CODES | {-101}`, `bilibili_api_gateway.py:62-66`; "the
  credential in effect saw nothing" → `not_found`). So the false-negative path
  is **not** the -101 branch; it is the **plain empty-inventory** branch
  (`subtitle_ingest.py:472-475`, `track is None` → `_record_captionless_part`)
  — an anonymous empty tuple that `credential_present=1` cannot flag, because
  presence records existence, not validity.
- **Schema constraint discovered on read (load-bearing for §10)**: both the
  `acquisition_attempts` table CHECK (`schema-transcripts.sql`) and the
  repository mirror (`database.py:1007-1011`) restrict a `no-subtitle` attempt's
  `error_code` to `{NULL, 'not_found'}`. So the earlier draft's
  `indeterminate_credential` / custom credential codes **do not fit the shipped
  schema** and are dropped.

Target mapping (the honest, still-bounded rule that fits the shipped CHECK):

| Observation | Recorded outcome | `error_code` (bounded scalar, ≤64 chars) |
|-------------|------------------|------------------------------------------|
| Tracks present, transcript stored/unchanged | `stored`/`unchanged` (existing) | unchanged |
| **Credential present, listing returns empty** | `no-subtitle` | `not_found` — reuse the existing code with amended semantics: "the credential in effect saw nothing for this part", covering both upstream `not_found` and a dead-credential empty inventory |
| Anonymous, listing returns empty | `no-subtitle` | `not_found` (same amended semantics — an anonymous caller also "saw nothing") |
| Gateway transport/rate/shape/response error | `failed` (existing) | its bounded code (existing) |

- `no-subtitle` keeps its meaning "nothing usable visible this attempt; the part
  stays re-attemptable"; the single `not_found` code now honestly reads as
  "nothing was visible under this credential", which is exactly the
  dead-SESSDATA case — so a dead-credential run is **no longer a durable
  `no-subtitle` row with no signal**; it is a `no-subtitle` row whose `error_code`
  says the credential saw nothing, and the operator re-probes the known
  positives to decide validity (the residual's own closing condition).
- **Mechanism for "credential present + empty"**: the ingestor currently can't
  see credential presence at `_acquire_part` (the run records it at
  `acquisition_runs.credential_present`, not per part). Task 5 threads the run's
  `credential_present` into `_record_captionless_part` so the empty-inventory
  branch can choose the code. No new vocabulary, no schema change.

## 6. `processing_status` convergence (closes `20260925-archive-db-review · R2`)

- `metadata_collected` is unreachable from every writer (verified on disk:
  `metadata_ingest.py:426` writes only `discovered`; no code path emits it).
  Decision: **delete the state by ceasing to reference it** — not by widening
  the column. The five-hop constraint holds: `CREATE TABLE IF NOT EXISTS`
  cannot `ALTER` an existing `CHECK`, and the no-migration policy forbids
  rewriting the table. Convergence is *reachability*, not schema:
  - Write discipline: no code path emits `metadata_collected` (new/modified
    writers must not reintroduce it).
  - Read discipline: the pending view filters `= 'discovered'` (the only
    reachable non-terminal value), so a residual `metadata_collected` row in an
    old database renders inert — reported by the `status` summary as a literal
    count, never as selectable backlog.
  - Fresh databases never acquire the value (the CHECK may stay as-is; nothing
    inserts it), so the domain converges to `{discovered, gone}` without
    touching the table definition.
- The `status` command's pending line follows the converged view.

## 7. Rollback / compat window

- **Amended by architect (seat 2) — Q2 resolved: rollback switch = a runtime
  flag.** Hidden `--queue-source {store,manifest}` (default `store`) on
  `download-audio` / `asr` / `pilot` / `run` only. A one-revert-commit path
  already exists at the code level; the flag makes the choice *operable* for a
  non-git operator and auditable at the command line, without a persisted
  state file (which would violate the no-migration discipline). `schedule` /
  `campaign` and the deleted `derive-manifest` get no switch — the batch chain
  cuts to store outright. The flag is removed one iteration later (at C's
  compound close), the same moment as the legacy compat-read evaluation.
- **Legacy manifest read-compat**: `publish-transcripts` and the two readers
  keep their current manifest reads unchanged this iteration. Deletion trigger
  (measurable): after one full operator cycle where
  `verify`/`coverage`/`publish-transcripts` run store-first with manifest as
  fallback and log **zero fallback hits** — evaluated at the next iteration's
  close (owner: PM, tracking: roadmap P0 item).
- `derive-manifest` command, `services/manifest_derivation.py`, and
  `tests/test_cli_derive_manifest.py` are deleted in cutover Task 4;
  `duration_s_from_ms` (its only other consumer, `transcript_projection.py:47`)
  moves into `transcript_projection.py`. `docs/metadata-storage.md` §Boundary
  and README §Derived audio queue are rewritten to describe the store-native
  queue (dashboard Task 4 owns README phrasing consistency).

## 8. Validation plan

1. Fresh-root end-to-end: `fetch-meta` (bounded) → `download-audio --bvid
   BV1:p0` resolves from store → `asr` runs → `v_pending_subtitles` membership
   drops; archive root holds no `manifest/manifest.jsonl` queue rows at all.
2. R2 regression shape: a legacy bare-`bvid` manifest row in an old root does
   **not** cause re-download (because no append step exists — assert
   `download-audio` selects zero parts when the store says the part holds a
   transcript).
3. SESSDATA (§5): fake-gateway fixture asserting the amended mapping —
   empty inventory (credential present or anonymous) yields `no-subtitle` +
   `error_code='not_found'` with credential presence threaded into the attempt;
   a gateway transport/rate/shape failure yields `failed` + its bounded code.
4. Status-set (§6): fresh database never acquires `metadata_collected`; the
   converged pending view renders and can shrink.
5. **Rotation (closes `iter-2026-09-queue-bridge · R1`)**: an audio run that
   keeps failing the same head eventually selects a different part — assert
   via the new per-part audio evidence (`acquisition_attempts.kind='audio'`).
   Fresh-vs-old DB boundary (§10) governs which evidence path the test pins.

## 9. Affected files (cutover plan write surface)

`src/bili_asr/cli.py` (download-audio / asr / pilot / run / schedule / campaign
input assembly; derive parser removal; `--queue-source`),
`services/manifest_derivation.py` (deleted), `services/subtitle_ingest.py`
(§5), `services/metadata_ingest.py` (§6 write discipline),
`storage/database.py` + `storage/schema-transcripts.sql` (§4
`MediaQueueRepository`, §5 attempt evidence), `coordinator.py` /
`scheduler.py` / `campaign.py` (stage inputs), `tests/test_cli_derive_manifest.py`
(deleted), affected `tests/test_cli_*.py` fixtures, `docs/metadata-storage.md`.

## 10. Fresh-vs-old database boundary (five-hop constraint, explicit)

The five-hop / no-migration rule means new structure lands on **fresh
databases only**; an existing `archive.db` keeps the shape it has. This
contract's store additions split accordingly:

- **Fresh-only additions** (guarded, no-op on old DBs): the `audio` attempt
  path — `acquisition_attempts` rows with `kind='audio'` and their widening of
  the outcome vocabulary. A fresh DB carries both; an old DB's attempts table
  stays caption-only, so per-part audio outcome evidence is unavailable there
  (the rotation assertion §8.5 pins the fresh-DB path; an old DB degrades to
  today's no-rotation behaviour, accepted and disclosed).
- **Safe on both** (view/read-layer only): the `MediaQueueRepository` read
  methods, the converged pending views, and the `no-subtitle`/`not_found`
  evidence amendment — these read existing columns or create views, which
  `CREATE VIEW IF NOT EXISTS` applies without touching prior definitions.
- Detection of "which shape is this DB" follows the shipped
  `_transcripts_columns` / `_has_subtitle_schema` guard pattern in
  `database.py`; the media-queue service refuses to write audio evidence to an
  old-DB attempts table rather than half-applying.

Explicit non-surface (iteration Non-Goal D4): `src/bili_asr/asr.py` hotword /
`DEFAULT_HOTWORDS` lines — untouched.
