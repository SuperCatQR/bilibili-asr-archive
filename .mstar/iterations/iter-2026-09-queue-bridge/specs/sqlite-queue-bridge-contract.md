# Spec: the SQLite → manifest queue bridge (`derive-manifest`)

**Status:** architecture locked (2026-09-19, architect pass) — iteration `iter-2026-09-queue-bridge`, Phase 1 review chain.
**Consumers:** plan `20260919-sqlite-queue-bridge` (`{PLAN_DIR}/20260919-sqlite-queue-bridge.md`).
**Charter:** iteration compass `D1`/`D2`/`D4`/`D8`/`D9`; register row `e2e-23191782-season-7686105 · R1`
(`{PROJECT_DIR}/_default/residuals.json`); boundary text `bilibili-asr-archive/docs/metadata-storage.md:288-305`.
**Placement:** iteration-level contract (D6). The frozen repo-level spec `{SPECS_DIR}/asr-archive-cli.md` is **not**
edited by this iteration; §7 states the revision it owes and who owns it.
**Reading discipline:** every claim below names the file and line it rests on. Code lines are pinned to
`HEAD cf3f779`, the plan's drift-check stamp; if a cited line moved, re-read before trusting the claim.

---

## 1. What this contract fixes

One new command, `bili-asr derive-manifest --archive-root <archive-root>` (D9), reads the work the store
records and appends the manifest rows the ASR/audio chain needs. It replaces the hand-built
`manifest/manifest.jsonl` that every corpus run needed (`README.md:332-340`, `docs/metadata-storage.md:288-305`)
without restructuring the chain (D2) and without a migration, importer, compatibility reader or live-database
schema change (D4).

Three things the contract settles, in the order a reviewer needs them:

1. **the queue** — which store rows mean "needs work" (§2);
2. **the row** — the mapping onto the manifest's state vocabulary and the conflict policy against rows the
   chain already holds (§3);
3. **the chain's acceptance** — why the rows this command writes cannot hit the archive stage's filesystem
   trap (Q1, §4), where per-part audio/ASR evidence lives and what rotation the first slice can preserve
   (Q2, §5), the `asr-local` question (Q4, §6) and the HTTP stacks (Q5, §7).

## 2. The queue: the predicate, verbatim

**The audio queue** is the set the store's own work relation returns:

```sql
-- schema-transcripts.sql:138-141, read through TranscriptRepository.list_pending_subtitle_parts()
SELECT vp.video_part_id,
       vp.bvid || ':p' || vp.page_index AS work_id,
       vp.bvid, vp.page_index, vp.cid, vp.title AS part_title, vp.duration_ms
FROM video_parts AS vp
WHERE vp.processing_status <> 'gone'
  AND NOT EXISTS (SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id);
```

with the repository's locked order `attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`
(`storage/database.py:1091-1123`; the "locked contract the CLI reads", not a query to be shortened).

- **Mean, in one sentence:** *every stored part that holds no transcript and is not `gone`.* The command's
  `--help` and its summary line must state that set (Risk Register row 6; the label `pending:` is `status`'s
  metadata backlog — `v_pending_metadata`, `schema.sql:156-166`, printed at `cli.py:1232` — and is **not**
  this set).
- **Read through one call.** The command must call `list_pending_subtitle_parts()` and must not restate the
  predicate in its own SQL: the predicate and its order have exactly one home.
- The relation includes parts that were attempted and came back captionless (`attempted = 1`,
  `v_pending_subtitles`' attempt CTE, `schema-transcripts.sql:107-121`), and parts never attempted
  (`attempted = 0`). It excludes a part whose `processing_status` is `gone`.
- **The queue is the whole relation.** The command takes no selector, no `--limit` and no `--bvid`: a subset
  the command chose is not the store's queue (compass Acceptance Criterion 1).
- 0 rows is a legitimate outcome (an empty archive, or a fully queued one) and is **not** an error (§8).

## 3. The row mapping and the conflict policy (Q3)

### 3.1 The row

For each queue row the command writes **exactly** this record, with these nine fields and no others:

| Field | Value | Source of the fact |
|-------|-------|--------------------|
| `work_id` | `f"{bvid}:p{page_index}"`, computed by `page_identity.format_work_id` (`page_identity.py:19-27`) — the Python identity SSOT `ManifestStore.upsert` re-validates (`manifest.py:266-272`) | `video_parts.bvid` + `page_index` |
| `bvid` | `video_parts.bvid` verbatim | same |
| `page_index` | `video_parts.page_index` verbatim | same |
| `cid` | `video_parts.cid` verbatim (NOT NULL, `schema.sql:24`) | same |
| `title` | the part's own title (the relation's `part_title`) — the specific thing being archived, not the collection title | `video_parts.title` |
| `duration_s` | `max(1, duration_ms // 1000)` — see §3.2 | `video_parts.duration_ms` |
| `pubdate` | `videos.pubdate` verbatim (unix seconds) | `videos.pubdate`, `schema.sql:16` |
| `pubdate_str` | `time.strftime("%Y-%m-%d", time.gmtime(pubdate))` — UTC, the `YYYY-MM-DD` shape every fixture and the md-name formula already use (`archive.py:470`, `integrity.py:477`) | rendering of the row's `pubdate` |
| `status` | `"needs_audio"` — the only status this command ever writes (§3.3) | the store predicate |

`cid` is carried so the chain needs no pagelist: `identity_from_entry` returns a `PageIdentity` only when the
row has `work_id` **and** `cid` (`page_identity.py:86-99`), and `download-audio` then skips
`resolve_page_identity`'s live call (`cli.py:1118-1134`). `page_label` is deliberately absent: the store holds
no such fact, and `archive_stem` ignores it (`archive.py:34-39`).

Both the identity check and `upsert`'s own page-qualification rule (`manifest.py:281-290`) mean a rewrite of
this row shape cannot silently become a bare-`bvid` row.

### 3.2 The milliseconds conversion is load-bearing

`duration_s`, not `duration_ms`, is what the chain reads: the audio budget fail-closes on a missing or
zero duration (`audio_budget.py:48-56`, `:87-88`), so a row that carries only `duration_ms` skips every
download.

- **Floor, not round:** `duration_ms // 1000` inverts the gateway's own encoding
  (`sources/bilibili_api_gateway.py:250` stores `math.floor(duration_seconds * 1000)`), so an integral source
  duration round-trips exactly.
- **Clamped to ≥ 1:** `duration_ms > 0` is a schema CHECK (`schema.sql:27`) but can still be < 1000; the
  budget treats `0` as *unknown* and fail-closes, so the smallest usable positive integer is written and the
  row stays downloadable.
- **Absent duration (added at the QC gate 2026-09-19, closing qc1 F-004r):** `duration_ms` is `NOT NULL CHECK (> 0)`
  (`schema.sql:27`), so a stored row cannot deliver `None`; the module nevertheless maps `None -> 1` because its
  signature accepts any mapping. That is a **deliberate module-level decision**, stated in
  `services/manifest_derivation.py` and pinned by `tests/test_manifest_derivation.py`, not a contract requirement:
  if the store ever gains a nullable duration, this section is what must change first. The alternative (propagating
  an error) was rejected because it would make an unknown duration fail a whole derivation rather than one row.

- `duration_ms` itself is **not** copied onto the row: the manifest's vocabulary is seconds
  (`docs/metadata-storage.md`, `{SPECS_DIR}/asr-archive-cli.md:132` "audio/{bvid}.m4a"), and a second unit on
  the row is exactly the trap the recon found (b) — one unit, converted once.

### 3.3 Which store fact maps to which manifest status

| Manifest status | Derived here? | Why |
|-----------------|---------------|-----|
| `needs_audio` | **yes — the only one** | "the part holds no transcript" *is* the statement "this part still needs audio/ASR"; it is the state the shipped legacy probe already wrote for a captionless part (`subtitles.py:125-131`). |
| `pending` / `meta_ok` / `sub_checked` | no | pre-caption states of the legacy chain; every part in this store already has its metadata (`fetch-meta` created it) and, where a probe ran, its caption outcome is already recorded in `acquisition_attempts` (`schema-transcripts.sql:72-96`). Deriving a pre-caption state would send the chain back to probe what the store already answered. |
| `subtitle_done` | no — **structurally impossible** | it asserts a caption document exists at `subtitles/raw/{stem}.json`; the store path never writes one (Q1, §4). |
| `audio_ok` | no | it asserts an audio artifact exists; the store records no audio object — `audio_objects` / `part_audio_objects` are declared-intentionally-empty scaffolding (`schema.sql:90-110`, recon (e)), and the bridge opens no socket and downloads nothing (`## Non-Goals`). |
| `asr_done` / `archived` / `gone` | no | each asserts work the bridge did not do (a transcript was produced / a bundle was published / upstream said gone). Writing one would be an inference about an artifact that may not exist — the rule D8 restates (§10). |

### 3.4 Conflict policy: **additive**, never authoritative

For every queue row, the command reads the manifest's *effective* row for that `work_id` — the last row per
key, which is what `ManifestStore.load()` hands the chain (`manifest.py:150-176`; a row without `work_id` is
keyed by its `bvid`, `manifest.py:55-62`):

```text
candidate = §3.1's row for the part
existing  = effective_row(candidate.work_id)          # ManifestStore.load(), read-only
existing is None                     -> append candidate            (reason: derived)
existing["status"] == "needs_audio"  -> append nothing              (reason: already_derived)
otherwise                            -> append nothing              (reason: chain_owned)
```

- **Never regress, never advance, never restate.** Any status the chain already holds — including `pending`,
  `meta_ok`, `sub_checked`, `subtitle_done`, `audio_ok`, `asr_done`, `archived` and `gone` — is left byte-for-byte
  as found. The bridge states store facts where the chain has said nothing; it does not overrule the chain.
- **The manifest is read, never written back.** Reading the manifest to avoid regressing a row is not the
  forbidden direction: D4 forbids reading `manifest.jsonl` *into the store*, and the store connection is
  `mode=ro` so that direction is structurally impossible (§10).
- **Idempotent, and byte-idempotent.** A second run over an unchanged store appends nothing: every candidate's
  effective row is the `needs_audio` row the first run wrote. Nothing about the second run's manifest differs
  from the first run's — the effective state *and* the file.
- **Resumable.** Rows are appended one at a time through `ManifestStore.upsert`, each re-reading the latest
  manifest under the manifest lock (`manifest.py:278-295`); a process killed mid-derivation leaves a valid
  prefix and re-running completes the queue (`{SPECS_DIR}/asr-archive-cli.md:44`, idempotent/resumable).
- **Why additive and not authoritative:** an authoritative derivation would re-queue a part the chain has
  already archived (the store keeps no transcript for chain-produced archives, so the part stays in the queue
  forever), and it would overwrite a `subtitle_done` row whose raw document exists on disk — the two states
  the compass's Risk Register rows 1 and 4 are about. Additive costs one read of a manifest the command has to
  open anyway.

### 3.5 Legacy bare-`bvid` rows

- The command **never emits a bare-`bvid` key** (its rows are page-qualified by §3.1) and **never reads,
  migrates, rewrites or removes an existing bare-`bvid` row**: a bare row keeps its key and its state.
  `ManifestStore.migrate_legacy_rows` and the `unresolved` / `excluded_from_page_processing` freeze it applies
  (`manifest.py:332-405`, invoked by `subtitles.harvest_subtitle` at `subtitles.py:101-105`) remain the only
  supported ways those rows change — the bridge is not a second migration path (D4).
- **Stated consequence, so it is not discovered later:** if such a row already carries `needs_audio`,
  `download-audio --missing-subs` selects it *as well as* the derived page-qualified row
  (`cli.py:1096-1100` selects every non-excluded `needs_audio` entry), and a bounded `--limit 1` run may spend
  its single slot on the legacy row. That is a property of the pre-existing manifest, not of this bridge: the
  command neither improves nor worsens a **page-qualified** row, and it must not be "fixed" by skipping the store row (that would
  make the derived set a subset the command chose, which §2 forbids).

*Limit disclosed at the QC gate 2026-09-19 (raised independently by two QC seats): the derivation
consults the manifest's **effective key**, so a **legacy bare-`bvid` row is not seen at all** — `ManifestStore.load()`
keys it by `bvid` while this contract's row carries `bvid:p{n}`. A part whose only record is such a row is therefore
appended as `needs_audio` and a bounded run may re-download and re-run it. The row itself is never rewritten, and the
artifact lands at the page-qualified stem, so nothing is overwritten; the cost is repeated work. The behaviour
question is registered as `iter-2026-09-queue-bridge · R2`; changing it reopens §2 and this section.*

### 3.6 Store self-contradiction

The store computes `work_id` in SQL (`schema-transcripts.sql:124`) while the manifest's identity rule is
Python's (`page_identity.format_work_id`); nothing enforces agreement (recon finding (a)). The command writes
the Python form and **skips with reason `identity_mismatch`** any queue row whose SQL-computed `work_id`
differs from it — reported, exit `0`. This is a three-line assertion, not a failure mode: on a store that
agrees (every store the shipped writers produce) it never fires.

## 4. Q1 — the archive stage's segment source, and what the bridge writes beyond the manifest

**Decision: the bridge materializes nothing and derives no `subtitle_done` row. It writes manifest rows and
nothing else. The invariant "no derived row skips with `missing_subtitle_raw`" holds because no derived row
can reach the state that skips.**

Evidence, in the order it matters:

1. The ASR/archive stage reads subtitle segments from the **filesystem**, not from `transcript_segments`:
   `coordinator._subtitle_segments` opens `{archive_root}/subtitles/raw/{stem}.json` and returns `None` when it
   is absent (`coordinator.py:396-413`), and `_stage_archive_from_subtitle` then records
   `error_code="missing_subtitle_raw"` and skips the row (`coordinator.py:442-451`). A row synthesized as
   `subtitle_done` for a part whose only caption is a store row would land exactly there.
2. The SQLite caption path deliberately writes **no** filesystem projection — no `subtitles/raw/*.json`, no
   `transcripts/srt/*.srt`; the normalized transcript lives in `archive.db`
   (`.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md:236-250`, "Projection and feeder
   boundary"; the writer is `services/subtitle_ingest.py`, which goes through
   `TranscriptRepository.record_acquired_transcript` and touches no path). Only the **legacy**
   `subtitles.harvest_subtitle` writes raw + srt (`subtitles.py:136-147`) — and that path is the one
   `harvest-subs` bypasses.
3. **Every part in the queue is captionless** (§2's predicate is "no `transcripts` row at all"), so the state
   the row needs is the audio path, not the caption path. `needs_audio` is not a claim about a caption; it is
   the statement that the part has none.
4. The alternative — materializing `subtitles/raw/{stem}.json` from stored segments — is **excluded**, not
   merely unnecessary:
   - it is the projection rebuild D1 puts out of scope, in the same class of artefact the store path stopped
     writing (evidence 2);
   - it needs a document the store does not hold: the chain's raw format is `body[].{from,to,content}` in
     **seconds** (`coordinator.py:405-412`; `subtitles.json_to_srt` multiplies by 1000, `subtitles.py:41-57`)
     while `transcript_segments` holds `start_ms`/`end_ms`/`text` (`schema-transcripts.sql:37-45`), and the
     document's remaining fields (`lan`, `lan_doc`) are not in the store at all — so a re-encoding would be
     lossy *and* would invent a second stem/version-identity rule;
   - it would let a file derived from the store become the chain's evidence of an upstream caption — the
     inverse of D8's rule and the reason the compass lists the projection rebuild as its own deferred piece.

**Which rows the invariant ranges over:** exactly the rows this command writes — the `needs_audio` rows of §3.1
— and, more strongly, over every row the chain will read for a derived `work_id` until the chain advances it.
Because §3.4 never regresses a chain-held row, a derived `work_id` is either (a) a fresh `needs_audio` row, or
(b) a row the chain already owns. In neither case does the bridge put a `subtitle_done` row on the manifest.

**What the bridge writes beyond the manifest: nothing.** No `subtitles/raw/`, no `audio/`, no
`transcripts/{srt,txt,md,raw}/`, and nothing into `archive.db` (mode=`ro`, §10). The one directory side effect
it inherits from the shipped writer lock is `{archive_root}/coordinator/` (`cli.py:3075-3085`, `:3134-3142`) —
the same side effect `harvest-subs` documents
(`.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md:231-236`).

**What the bridge does *not* do, stated so it cannot be read wider than it is:** a part whose caption is stored
but whose SRT/TXT/MD bundle does not exist is **not** re-queued by this iteration — it holds a transcript, so
it is not in the queue. Closing that gap is the projection rebuild (piece 2), which stays out of scope (D1) and
open in the register.

## 5. Q2 — where per-part audio/ASR evidence lives, and the rotation the first slice can keep

**Decisions**

1. **The bridge is read-only on the store.** It writes no `acquisition_runs` row, no `acquisition_attempts`
   row, and no transcript; the connection is `mode=ro` so this is structural (§10). Deriving a queue is not an
   acquisition, and the store's one declared work queue is not drained by deriving it (compass Acceptance
   Criterion 1's last check).
2. **Per-part audio/ASR evidence stays where it already is, outside the store:**
   - the manifest's own forward transitions (`needs_audio → audio_ok → asr_done/archived`) — the only writer
     is the chain itself; and
   - the per-stage attempt ledger `{archive_root}/coordinator/attempts.jsonl`, which records one row per
     attempted `(work_id, stage)` with `stage ∈ {harvest, download, asr, archive}`, a redacted `error_code`
     and timestamps (`coordinator.py:34-58`, `:354-378`) — already per-part audio/ASR evidence, already
     durable, already outside SQLite. Its own boundary (the pilot writes none) is register row `R4` and is not
     touched here.
3. **The store cannot hold per-part audio/ASR evidence in this iteration.**
   `acquisition_attempts.outcome ∈ {stored, unchanged, no-subtitle, failed}` with a CHECK matrix binding each
   outcome to `transcript_id`/`error_code` (`schema-transcripts.sql:75-94`): a successful *audio* attempt
   produces no transcript and has no legal outcome shape. The run-level slot exists —
   `acquisition_runs.kind ∈ {subtitle, audio, asr}` (`schema-transcripts.sql:50-67`) — but this iteration
   writes no run (decision 1) and the chain writes no SQLite (D2). Widening the attempt CHECK would require a
   schema change, and the schema policy is explicit that `CREATE TABLE IF NOT EXISTS` cannot widen a
   constraint and an existing archive keeps the shape it has (`schema-transcripts.sql:4-10`) — i.e. a widened
   CHECK applies to **fresh databases only**, which D4 forbids relying on. So: **no per-part audio/ASR evidence
   in the store, and no schema change proposed.**
4. **The first slice cannot preserve the store-side rotation contract for the audio queue — stated plainly,
   and registered.** Rotation is a repository-level `ORDER BY` over per-part attempt evidence
   (`database.py:1091-1123`) whose evidence is caption-only (`schema-transcripts.sql:107-121` restricts the
   attempt CTE to `kind = 'subtitle'`). No store column can express "this part was last attempted for audio at
   T" without the widening of decision 3.
   - **What is preserved:** the manifest's own forward state. A successfully attempted row leaves
     `needs_audio` (`audio.py:174-181` marks `audio_ok` when the audio file already exists; `coordinator.py:621-624`
     records `download: ok`), so it is no longer selected by `download-audio --missing-subs`
     (`cli.py:1096-1100`) and §3.4 will not re-queue it. Compass Acceptance Criterion 6 — "after a first
     bounded run has attempted part A the next bounded selection attempts B" — therefore **holds for a
     successful attempt**.
   - **What is lost:** a *failed* audio attempt leaves the row at `needs_audio` with no recency anywhere in
     the store, so successive bounded runs re-select the same head until it succeeds; and no store-side report
     can answer "was this part attempted for audio, and when?". That loss is disclosed here, keeps Risk
     Register row 4 open, and is the PM's residual to register (the same fallback the compass already commits
     to for Criterion 6).

## 6. Q4 — may an `asr-local` transcript drain the backlog?

**Decision: for the audio queue, yes — and that is correct. The *caption backlog's* label is what is wrong,
and repairing it belongs to the iteration that first writes `asr-local`.**

- `v_pending_subtitles`' `NOT EXISTS` carries no `source_kind` filter (`schema-transcripts.sql:139-141`), so a
  part holding an `asr-local` transcript leaves both the view and `count_pending_subtitle_parts`
  (`database.py:1125-1131`). For **this command** that is the right reading: the queue means "parts that hold
  no text at all", and a stored ASR transcript means the text exists and the audio/ASR work for that part is
  done. Re-queueing it would re-download and re-transcribe a part whose transcript is already stored.
- The **conflation** is on the caption side: `harvest-subs`' candidate enumeration and the CLI's
  "remaining without a transcript" reporting read the same relation, so once an `asr-local` row exists, a
  caption-backlog count silently means "no text of any kind" rather than "no caption"
  (`.mstar/knowledge/architecture-patterns/normalized-transcript-storage.md:237-262`). Fixing that means a
  source-kind-scoped view — and `CREATE VIEW IF NOT EXISTS` (`schema-transcripts.sql:106`) cannot replace a
  view on an existing database either, so it is the same fresh-database-only shape as §5's CHECK widening.
- **Therefore:** this iteration does not modify the view, does not add a source-kind filter to the queue, and
  does not report a caption backlog. The deferred repair is recorded with the rest of the `asr-local` work:
  D5 already hands the identity rule for `asr-local` transcripts to "the audio/ASR iteration"
  (`schema-transcripts.sql:30-35`), and the source-kind-scoped view belongs to that same iteration — it can
  only be tested once such rows exist.
- The bridge's own naming duty (Risk Register row 6) is the mitigation available today: the command's help
  text and summary line name the set as *parts with no transcript*, never as an unqualified "pending".

## 7. Q5 — which HTTP stack serves the audio path

**Decision: the bridged audio path keeps the stack it already has — `bili_client` — and this iteration
introduces no second stack and migrates nothing. The bridge itself opens no socket at all.**

- **The audio path today:** `download-audio` and `run`'s download stage construct
  `bili_client.BiliClient` (`cli.py:1108`, `cli.py:2446`, `cli.py:2618`) and go through
  `audio.download_audio` → `client.fetch_playurl_audio` / `client.download_audio_stream`
  (`audio.py:156-200`). D2 leaves that code untouched, so the answer cannot be anything else in this slice.
- **The bridge:** composes a read-only store connection and `ManifestStore` only. It must import no HTTP
  module and construct no client — checkable by
  `grep -n "bili_client\|bilibili_api\|requests\|httpx\|urllib\|socket" src/bili_asr/services/manifest_derivation.py`
  returning no match, and by `derive-manifest` not appearing in the client-constructing families
  (`cli.py:1108`, `:2446`, `:2618`).
- **The frozen spec sentence is already false in substance and needs a revision — owned by the PM (Q6), not
  edited here.** `{SPECS_DIR}/asr-archive-cli.md:62` says "HTTP ownership: exactly one module (`bili_client`)
  opens sockets". Since the SQLite metadata/subtitle iteration, the shipping rule is narrower and different:
  the typed gateway `sources/bilibili_api_gateway.py` is the only module that may import `bilibili_api` (its
  own module docstring, lines 1-4) and it opens sockets through that package on the `probe-subs` /
  `harvest-subs` path, while `bili_client` owns the legacy transport used by the ASR/audio chain. The accurate
  statement is therefore **two named stacks with a per-path owner**, and the frozen spec's single-owner
  sentence should be revised to say so. Per the Assignment's constraint I do not edit `{SPECS_DIR}`: the
  revision and its sign-off are the PM's (`{SPECS_DIR}/asr-archive-cli.md:6`, change policy). **This revision
  is not a precondition for the plan**: the bridge changes neither stack, and D9 adds no exit-code value that
  the frozen taxonomy would have to absorb.

## 8. The operator surface

```text
bili-asr derive-manifest --archive-root <archive-root>
```

- **Exactly this command name and flag** (D9). `--archive-root` defaults to `DEFAULT_ARCHIVE_ROOT`, as every
  other command's does (`cli.py:198-200`). No other flag in this slice — no selector, no `--limit`, no
  `--dry-run` (§2).
- **Composition:** `cli.py` composes the layers, as the cross-layer rule requires
  (`{SPECS_DIR}/asr-archive-cli.md:61`): `_open_subtitle_connection("derive-manifest", root, read_only=True)`
  for the store (`cli.py:648-704`, `:580-618`) → `TranscriptRepository(connection)` → the derivation service
  → `ManifestStore(root=...).upsert(row)` per appended row, closing the connection in `finally`. The shape
  follows `_cmd_harvest_subs` (`cli.py:971-1071`) line for line.
- **Writer lock:** `derive-manifest` joins `_ARCHIVE_WRITER_COMMANDS` (`cli.py:3075-3085`), so `main()` takes
  `archive_writer(args.archive_root)` before dispatch (`cli.py:3134-3142`). No new lock code. Consequences,
  both shipped behaviour: a concurrent archive-writer command makes it exit `1` with
  `derive-manifest: archive_busy`; the lock creates `{archive_root}/coordinator/` even when the command then
  fails (`bilibili-asr-archive-cli.md:231-236`).
- **Exit codes — no new value** (D9; `{SPECS_DIR}/asr-archive-cli.md:97-101`):
  - `0` — the derivation completed, **including "nothing to derive"** (queue 0, or every candidate already
    queued). Precedent: `download-audio --missing-subs` treats an empty queue as success (`cli.py:1103-1105`).
  - `1` — the command could not run: a missing `archive.db` (`cli.py:540-556`), an unreadable one
    (`cli.py:594-598`), a database predating the transcript schema (`cli.py:634-646`), `archive_busy`
    (`cli.py:3140-3142`), or a usage error (argparse's `2` is mapped to `1` by `_UsageErrorArgumentParser`,
    `cli.py:31-42`).
  - `2` — not produced by this command: it performs no network operation and no per-part attempt, so it has no
    "every attempt failed" case and no unexpected-error path of its own. Anything escaping the store read is a
    programming error and reaches the interpreter as it does for the other read commands.
- **Printed output** (the command's report is part of its contract, per
  `bilibili-asr-archive-cli.md:186-190`):
  - one line per **appended** row: `<work_id>: needs_audio (duration_s=<n>)`;
  - one line per **`chain_owned`** and per **`identity_mismatch`** skip:
    `skip <work_id> <reason>` — the two cases where an operator's expectation can differ from the outcome;
    `already_derived` rows are not printed one by one (they are the command's own previous output);
  - one summary line, always printed, with all counts including zeros:
    `derive-manifest: queue=<q> derived=<n> already_derived=<a> chain_owned=<c> identity_mismatch=<m>`.
- **`--help`** exits `0` and names the set it derives — the audio queue = stored parts with no transcript and
  not `gone` — without reusing the bare label `pending:` (§2, Risk Register row 6).

## 9. Interfaces

**Consumes**

| Input | Contract |
|-------|----------|
| `{archive_root}/archive.db` | opened **read-only** (`mode=ro`), existing file only, transcript-schema capability required (`cli.py:580-618`, `:648-704`) |
| `TranscriptRepository.list_pending_subtitle_parts()` | the queue and its locked order (`database.py:1091-1123`) |
| `TranscriptRepository.read_video_pubdates(bvids)` | **new read method** (plan Task 2): the stored `videos.pubdate` per bvid, so §3.1's `pubdate`/`pubdate_str` are store facts and not invented. `TranscriptRepository` already joins metadata tables by key (`list_selected_parts`, `database.py:1133-1162`) — no new layering |
| `{archive_root}/manifest/manifest.jsonl` | read-only, through `ManifestStore.load()` (`manifest.py:150-176`), for §3.4's effective rows |

**Produces**

| Output | Contract |
|--------|----------|
| appended rows in `manifest/manifest.jsonl` | §3.1's nine fields, `status: needs_audio`, page-qualified `work_id`, through `ManifestStore.upsert` (`manifest.py:260-295`) |
| `{archive_root}/coordinator/archive-writer.lock` | created by the shipped lock, not by the bridge (§8) |
| stdout/stderr | §8's per-row lines and one summary line |

**Affected readers** — the blast radius the register's tracking names, listed here because the command adds
rows these readers will read (`e2e-23191782-season-7686105 · R2` was **closed on 2026-09-18** by plan
`20260918-verification-surface-truth`, which reconciled the three readers; this iteration adds rows they read
and does **not** promise anything new about `verify`/`coverage` exit `0` on a real archive):

| Reader | Where |
|--------|-------|
| `download-audio --missing-subs` | selects every `needs_audio` entry (`cli.py:1096-1100`) |
| `asr --pending`, `pilot` | manifest-status selectors |
| `run` / `schedule` / `campaign --scope pending` | non-terminal rows (`cli.py:2217-2237`) |
| `coverage` | `cli.py:1497`, via `sidecar_projection` |
| `coverage --quality` | `cli.py:1255+`, reads `manifest/manifest.jsonl` directly |
| `verify` | `cli.py:2969`, via `sidecar_projection` |
| `export` | writes a manifest-shaped file (`cli.py:2937`) |
| `status` | **unchanged**: its `pending:` line stays the metadata backlog (§2) |

## 10. D8 restated next to the contract

The knowledge rule the compass cites — `.mstar/knowledge/architecture-patterns/operational-sidecars.md:234-236`:

> "None of these projections may back-write an inferred truth into the manifest."

**How this contract reads that rule (D8, product-locked):** the rule constrains what may *become* manifest
state — it forbids a projection's *inference* (a guess about an artifact that may not exist) from becoming a
recorded state; it does not forbid the manifest from being *derived* from recorded store facts. This bridge is
on the permitted side of the line, and structurally so:

- **What it writes is a recorded store fact plus the state that fact entails**: the part's identity
  (`bvid`/`page_index`/`cid`), its stored duration, its stored publication second, and "the store holds no
  transcript for this part" → `needs_audio`. §3.3 is the exhaustive list of states it may write, and it writes
  one of them.
- **It never writes a state that asserts an artifact**: no `subtitle_done` (no raw document — §4), no
  `audio_ok` (no audio object, and it downloads nothing), no `asr_done`/`archived`/`gone`.
- **It never copies manifest state back**: the store connection is `mode=ro`, so a write would fail inside
  SQLite rather than reach the file — the same structural argument `probe-subs` uses
  (`bilibili-asr-archive-cli.md:225-230`) — and D4 already fixes the opposite direction (no importer, no
  compatibility reader).
- **It never overrules the chain**: §3.4 is additive, so a manifest state the chain recorded is not replaced
  by a store-derived one.

The boundary it closes is `docs/metadata-storage.md:288-305`; the boundary it leaves open is the projection
rebuild (`## Non-Goals` of the compass, piece 2).

## 11. Deferred, and where the deferral is tracked

| Deferred | Where it is tracked |
|----------|--------------------|
| The SRT/TXT/MD projection rebuild from stored transcripts (piece 2) | compass `## Non-Goals` (D1) + register `e2e-23191782-season-7686105 · R1` (stays open; PM records at close) |
| Per-part audio/ASR evidence in the store (`acquisition_attempts` widening / a new table) | §5 decision 3-4; Risk Register row 4; PM registers the rotation loss as a residual at close |
| A source-kind-scoped pending view for the caption backlog (`asr-local`) | §6; the iteration that writes `asr-local` transcripts (D5's owner) |
| The `asr-local` per-model/run identity rule | D5 (decided, not implemented, this iteration) — `schema-transcripts.sql:30-35` |
| `{SPECS_DIR}/asr-archive-cli.md` revision: one HTTP owner → two named stacks with a per-path owner; and a `derive-manifest` row in the frozen CLI surface | §7; Q6, owner PM (revision + sign-off; the plan does not depend on it) |
| `e2e-23191782-season-7686105 · R2` (three manifest readers disagree about append-only history) | **Closed 2026-09-18 by plan `20260918-verification-surface-truth`**; the register reads `resolved`. Recorded here because this table was written against the assumption that it was still live (PM correction 2026-09-19). The bridge adds rows those readers read and must not be read as changing their verdicts. Remaining latent reader debt: `20260918-verification-surface-truth · R1`/`R2` |

## 12. Risks and rollback

- **Risk — a derived row is not accepted by the chain.** Mitigated by §3.1/§4 and proven by the plan's Task 3
  (a derived queue runs to `archived` with no `missing_subtitle_raw`). If that proof fails, the failure is a
  contract defect, not a test defect: STOP and return to this spec.
- **Risk — re-queueing rows the chain already advanced.** Mitigated by §3.4's additive policy; proven by the
  plan's Task 2 case (an `archived` row for a part still in the store queue is not touched) and Task 3's
  second-run check.
- **Risk — the derived set is silently a subset.** Mitigated by §2 (no selector, no limit) and by the additive
  policy being *reported* rather than silent (§8's counts).
- **Risk — the naming trap** (`pending:` = metadata backlog). Mitigated by §2's naming duty and tested in
  Task 2's help case.
- **Rollback.** Stop running the command: nothing else changed. The manifest is append-only and the chain's
  vocabulary is untouched, so no cleanup is required — a derived row's only effect is that the chain will
  process a part that has no transcript, which is the work the operator asked for. No schema change, no
  migration, no new dependency, no socket.

## 13. Validation plan — how the compass criteria become checkable

| Criterion | What makes it checkable, from this contract |
|-----------|---------------------------------------------|
| 1 (one command derives the queue) | §2's relation + §3.1's row + §3.4's byte-idempotence + §8's help/summary naming. The manifest-side expected set is the derived rows for the queue rows the store returns; on a fixture whose manifest was empty before the first run the two sets are equal by construction |
| 2 (the captionless part reaches the audio path) | §3.1's `status: needs_audio` + §3.2's `duration_s` — the two expected values the criterion reads |
| 3 (a run consumes the derived queue, no `missing_subtitle_raw`) | §4: every derived row is `needs_audio`, so `process_row` routes it to the audio/ASR path (`coordinator.py:694-700`), never to the subtitle-archive path that skips |
| 4 (no double write, no second SSOT claim) | §1, §7 and §10; the command's contract lives in this file, not in `{SPECS_DIR}` |
| 5 (the bound is stated) | §11 + §8's documented operator sequence entry |
| 6 (bounded runs still make progress) | §5 decision 4: preserved for a successful attempt (the row leaves `needs_audio`), with the failed-attempt loss stated and registered |

## Recall receipt (Prepare input, per `mstar-phase-gates` §A)

**Read and reused**

- `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md` — exit taxonomy (:177-190), read-only
  probe (:225-230), writer-lock ordering (:231-236), projection and feeder boundary (:236-250): the command's
  surface is modelled on `harvest-subs`, including its lock, its read-only connection and its documented
  refusal to write projections.
- `.mstar/knowledge/architecture-patterns/normalized-transcript-storage.md` — the pending-work relation and
  its ordering (:237-262), the CHECK matrix and the no-terminal-state attempt design (:1-120 area): reused as
  the queue contract and as the reason per-part audio evidence has no home.
- `.mstar/knowledge/architecture-patterns/operational-sidecars.md:234-236` — the no-back-write rule, restated
  in §10 as D8 requires; and §3's stage-attempt ledger as the per-part audio/ASR evidence of record (§5).
- `.mstar/knowledge/testing-patterns/worktree-test-invocation.md` — the pinned-invocation rule the plan's
  commands obey (`PYTHONPATH=$PWD/src` + the resolved-`bili_asr.__file__` probe), because Phase 2 runs in a
  linked worktree with no `.venv`.
- `{SPECS_DIR}/asr-archive-cli.md` — the frozen exit taxonomy (:97-101), the cross-layer composition rule
  (:61) and the state machine (:118-122): honoured verbatim, and §7 names the one sentence this iteration
  concludes must be revised (PM-owned).

**Read and rejected**

- The register's alternative surface `download-audio --from-sqlite` — rejected by D2/D9 (a flag on the chain's
  own command is not the standalone derivation the user locked).
- "Make the bridge authoritative" (replace an existing row's state) — rejected in §3.4: it would re-queue
  archived parts and overwrite a live `subtitle_done` row.
- "Materialize `subtitles/raw/{stem}.json` from `transcript_segments`" — rejected in §4 (piece 2, lossy
  re-encoding, and the store holds neither seconds nor the document's metadata fields).
- "Add a source-kind filter to the queue" — rejected in §6 (correct for the caption backlog, wrong for the
  audio queue, and a fresh-database-only view change).
- Folding `20260918-operational-record-coverage · R3` into this plan — rejected here as well as in the compass
  `## Plans`: it touches `cli.py`'s run-ledger timestamp comparison, not this command, and would widen the
  review surface the register's own `target` does not ask for.
