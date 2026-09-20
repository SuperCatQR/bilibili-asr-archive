# Spec: projecting stored transcripts into archive bundles (`publish-transcripts`)

**Status:** architecture locked (2026-09-20, architect pass) — iteration `iter-2026-09-transcript-projections`, Phase 1 review chain (round 2; reviewed in round 3 by `writing-specialist` for corpus hygiene only — no architectural claim changed, §5.5's state table completed to the five states, and the two out-of-bound findings handed to the PM as compass D14/Q6/Q7).
**Consumers:** plan `20260920-transcript-projections` (`{PLAN_DIR}/20260920-transcript-projections.md`); compass `{ITERATION_DIR}/iter-2026-09-transcript-projections/delivery-compass.md`.
**Charter:** compass `## Scope` 1–3, `D1`/`D2`/`D3`/`D5`/`D6`/`D10`, acceptance criteria 1–6; register rows
`e2e-23191782-season-7686105 · R1` (projection half) and `e2e-23191782-longform-pair-webdav · R1` (F4, §12).
**Placement:** iteration-level contract. This iteration writes **no** `{SPECS_DIR}` file and no `{KNOWLEDGE_DIR}` file (compass D7);
§13 states the revision the frozen spec owes and who owns it. This file is the plan's declared `primary_spec`.
**Reading discipline:** every claim below names the file and line it rests on. Code lines are pinned to
`HEAD 013a507` — the plan's own drift-check stamp (`20260920-transcript-projections.md` Global Constraints,
`013a507..HEAD`). If a cited line moved, re-read it before trusting the claim; if an in-scope file changed,
re-read the excerpt and STOP on a mismatch (`mstar-phase-gates`).

---

## 1. What this contract fixes

One new command, `bili-asr publish-transcripts`, reads the transcripts `archive.db` already holds and publishes
them as complete archive bundles (the four families `srt`/`txt`/`md`/`raw` plus the `.bundle-ready` marker) under
the configured artifact root, then records the publication in `manifest/manifest.jsonl` so the archive's own
readers count the row done. The operator surface — name, selector, printed lines, exit stance — is **D10** and is
**not re-decided here** (§7 restates it only where a mechanism is needed to make it true).

The store side and the archive-writer side exist and are unchanged; the missing piece is the mapping between them.
Nothing bridges the two shapes today: `harvest-subs` stores segments and writes no file
(`services/subtitle_ingest.py:485-546` goes through `TranscriptRepository.record_acquired_transcript` and touches
no path), and **none of `write_archive`'s five call sites reads the store** — two take segments from the
filesystem or from the ASR runner (`coordinator.py:492`, `:593`) and three are the legacy/pilot subtitle and ASR
paths (`cli.py:2023`, `:2128`, `:2230`). `write_archive` (`archive.py:452`) has no caller that hands it
`transcript_segments`.

Four things this contract settles, in the order a reviewer needs them:

1. **the candidates** — which stored parts this command ranges over, and in which order (§2);
2. **the content** (compass Q2 → **D11**) — bundle identity/stem, which stored transcript wins, the ms→s conversion, the
   `raw` sidecar, and the exact frontmatter key set with its deliberate omissions (§3, §4);
3. **the recorded state** (compass Q3 → **D12**) — the manifest row, its one status, the idempotency predicate, and what
   happens to a half-written bundle (§5);
4. **`asr-local`** (compass Q4 → **D13**) — answered explicitly, with its identity rule named (§6).

The compass rows these four answers came from are withdrawn; their converged form is D10 (the operator surface and
the membership rule, §2 and §7), D11 (the content, §3–§4), D12 (the recorded state, §5) and D13 (`asr-local`, §6).

---

## 2. The candidates: the membership rule, verbatim

**The candidate set is every stored part that holds at least one stored transcript, whatever its
`processing_status`** (D10b). A part is a candidate when the `transcripts` table holds a row for its
`video_part_id`; a part with no transcript row is out of range, and so is upstream availability: a part whose
`processing_status` is `gone` **is** a candidate when it holds a transcript.

This is deliberately the **opposite relation** to the audio queue's. The queue filters both ways
(`schema-transcripts.sql:138-141`: `vp.processing_status <> 'gone'` **and** `NOT EXISTS (… transcripts …)`);
this command filters neither, because the question is different — "the store holds local text, publish it", not
"the store holds no text, go and fetch it". A `gone` part still holds local text, and D10b says so out loud.

### 2.1 The read

Membership is read through **one new repository read**, `TranscriptRepository.list_stored_transcripts()`
(§8), never restated as SQL in `cli.py` or in the service — the bridge's rule for its own relation
(`sqlite-queue-bridge-contract.md` §2 "Read through one call"), applied here:

```sql
-- one query, no per-part N+1, no processing_status predicate, no NOT EXISTS
SELECT vp.video_part_id, vp.bvid, vp.page_index, vp.cid, vp.title AS part_title,
       vp.duration_ms, vd.pubdate,
       t.transcript_id, t.source_kind, t.language, t.model_id, t.version,
       t.content_sha256, t.created_at
FROM transcripts AS t
JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id
JOIN videos      AS vd ON vd.bvid = vp.bvid
ORDER BY vp.bvid ASC, vp.page_index ASC,
         t.source_kind ASC, t.language ASC, t.version DESC
```

- **One row per stored transcript version** — the relation is over `transcripts`, not over parts. The part
  columns repeat, which is what lets the pure service (§3) pick one winner per part without a second query.
- **`pubdate`** comes from `videos` (the FK target of `video_parts.bvid`, `schema.sql:16`, `:20-33`), as
  `read_video_pubdates` already reads it (`database.py:1133-1164`). The `pubdate_str` rendering is the service's
  (§3.4) — the bridge renders it the same way (`services/manifest_derivation.py:95`).
- **`work_id` is not selected.** Unlike the queue view (which computes it in SQL, `schema-transcripts.sql:124`),
  this read leaves identity to Python: the service builds it with `page_identity.format_work_id`
  (`page_identity.py:24-31`), the SSOT `ManifestStore.upsert` re-validates (`manifest.py:267-273`). No SQL/Python
  agreement question arises, so the bridge's `identity_mismatch` branch (§3.6 there) has no counterpart here.
- **The locked order lives in the repository**, not in the caller (the queue's own discipline,
  `database.py:1106-1113`). `bvid` then `page_index` is the part order; the transcript keys after them make the
  read deterministic row-for-row, which is what §3.2 consumes and what D10c's "deterministic order" needs.
- **The selector narrows the read** (`bvid`, `page_index`), mirroring `list_selected_parts`
  (`database.py:1174-1203`).

### 2.2 The selector, and what "unknown" means

- No selector: every candidate the store holds.
- `--bvid <bvid>`: every stored part of that video; `--bvid <bvid:pN>`: exactly that part
  (`_subtitle_selector`, `cli.py:805-821`).
- **"Unknown" ranges over the store's part relation, not over the candidate set.** A selector is unknown when
  `TranscriptRepository.list_selected_parts(bvid, page_index)` returns no row (`database.py:1174-1203`) — the
  shipped guard `harvest-subs` uses (`cli.py:1124-1128`). A selector that names a **stored part holding no
  transcript** is *known* and yields zero candidates, exit `0` (D10d: no candidate is success). A selector the
  storage identifier rule can never hold is answered before the database is opened, on the argument alone
  (`_selector_cannot_name_a_part`, `cli.py:824-838`).
- `--limit-parts N` bounds the run in **parts** — the first `N` candidates in the locked order — and `N < 1` is
  exit `1` (the shipped validation shape, `cli.py:1097-1102`; `database.py:1115-1119` in the repository). A part
  is a candidate once, whatever number of transcript rows it holds, so the bound is not satisfiable by version
  rows.

---

## 3. Q2(a) — identity, and which transcript wins

### 3.1 Bundle identity: one bundle per part

The bundle stem is the writer's own rule, unchanged: `archive_stem(entry)` →
`artifact_stem(page_identity(bvid, page_index, cid, page_label))` → `"{bvid}.p{page_index}"`
(`archive.py:34-38`, `page_identity.py:41-45`). `cid` is **required** for the page-qualified branch
(`archive.py:36`: `entry.get("cid") is None` falls back to the bare `bvid`) and the store always has it
(`video_parts.cid` is `NOT NULL`, `schema.sql:24`), so every candidate is page-qualified. `work_id` never appears
in a path (`page_identity.py:1-5`).

The three other names follow from the same stem inside the writer (`archive.py:465-471`): `transcripts/srt/{stem}.srt`,
`transcripts/txt/{stem}.txt`, `transcripts/raw/{stem}.json`, and the md name
`"{pubdate_str}_{stem}_{_safe_name(title)}.md"`. **There is no room in the stem for a caption kind or a
version**, which is exactly why §3.2 has to decide one winner: the archive's bundle is one per part, not one per
stored identity.

### 3.2 The winner rule — a total order over the part's stored transcripts

Per `video_part_id`, the winner is the minimum under this key, applied in order:

| # | Key | Direction | Source of the fact |
|---|-----|-----------|--------------------|
| 1 | `source_kind` rank | `subtitle-cc` (0) → `subtitle-ai` (1) → `asr-local` (2) | the shipped harvester's own preference: an uploader caption before a machine caption (`subtitle_ingest.py:140-143`, `:162`, `:164-171`; the kind mapping is `_SOURCE_KIND_BY_AI`, `:63`) |
| 2 | language **family** rank | `zh` (0) → `en` (1) → any other family last, by code | applied through the public `language_family(language, is_ai)` (`subtitle_ingest.py:104-120`); the order `("zh", "en")` is the harvester's `_DEFAULT_LANGUAGE_FAMILY_ORDER` (`:59`), **declared** in the projection module and pinned equal by a test (§10 T3) — the `archive.CAPTURE_GAP_SECONDS` precedent for a cross-layer constant (`archive.py:296-303`) |
| 3 | `language` code | ascending, byte order | `transcripts.language`, an IANA-family code stored trimmed (`database.py:889`, `:1043`) |
| 4 | `version` | **descending** — the newest stored body of that identity | `read_transcript(…, version=None)`'s own "latest version of the identity" reading (`database.py:1030-1049`) |

**Totality, and why there is no fifth key.** `UNIQUE (video_part_id, source_kind, language, version)`
(`schema-transcripts.sql:25`) makes `(source_kind, language)` an identity and `version` unique inside it, so keys
1–4 already separate every row a shipped writer can store; the service adds no `transcript_id` tiebreak and claims
none.

**Consequences, stated rather than left to discovery:**

- A part holding both `subtitle-cc zh-CN` and `subtitle-ai ai-zh` publishes the **uploader caption**. The
  published line names only the winner (`source=`/`lang=`/`version=`, §7), because the bundle stem carries no
  kind or version — a second stored identity for the same part is not named by this command and stays in the
  store.
- A `subtitle-ai ai-zh` and a `subtitle-ai ai-en` publish the `zh` family (key 2 before key 3): the projection
  never picks English over Chinese because `"ai-en" < "ai-zh"` lexically.
- Two codes in one family (`zh-CN`, `zh-Hant`) resolve by code ascending — `zh-CN` first. Arbitrary, and
  deliberately deterministic: the store records no preference between them.

**Alternatives rejected, with the falsifier that would reopen this section.**

- *Most recently stored wins* (`transcripts.created_at DESC`, key 4 replaced): rejected because the clock records
  **when** a track was stored, not **which** the archive prefers — a later `harvest-subs --language` run would
  silently demote the uploader caption. Falsifier: an operator requirement that "the newest stored text is what
  the bundle must carry"; then key 1–3 are dropped and key 4 becomes `created_at DESC, transcript_id DESC`.
- *Publish one bundle per identity* (a kind/version-qualified stem): rejected — it changes the bundle layout the
  readers' canonical-path rule computes (`integrity.py:567-584`, `quality.py:322-344`) and would make one part
  own several bundles with no row-level record of which is which.

### 3.3 The conversion the writer's `segments` shape needs

The store holds `transcript_segments(start_ms, end_ms, text)` (`schema-transcripts.sql:37-45`) and the writer
consumes `segments: list[dict]` with **seconds** (`segments_to_srt` reads `segment['start']`/`['end']` and
`_fmt_srt_time` multiplies by 1000, `asr.py:850-867`). The projection maps, per segment, in stored ordinal order
(`database.py:1205-1222` returns them in `ordinal` order):

```python
{"start": start_ms / 1000, "end": end_ms / 1000, "text": text}
```

- **Seconds, once.** `/1000` exactly; the identity is `float` division, and the SRT rendering rounds
  `seconds * 1000` back to an integer (`asr.py:851`), so a cue's SRT times are the store's milliseconds exactly —
  no lost millisecond and no accumulated drift.
- **`end > start` is guaranteed by the store**, not re-checked: `CHECK (end_ms > start_ms)` (`:41`), re-validated
  on write (`database.py:1280-1283`). So no zero-length cue can reach `_check_cues`'s `out_of_range`
  (`quality.py:688-689`) from this path.
- **`text` is verbatim.** The store already holds it trimmed (`database.py:1284-1287`); the projection fixes no
  text and rewrites no punctuation.
- **No `confidence` key is ever added, and none is dropped**: the store has no such column (§4.2).

### 3.4 `duration_s` and `pubdate_str` — the two rendered store facts

- `duration_s = duration_s_from_ms(video_parts.duration_ms)`, the bridge's public rule (`max(1, ms // 1000)`,
  `services/manifest_derivation.py:50-68`, exported at `:171`): floor, because it inverts the gateway's own
  `math.floor(seconds * 1000)` encoding, clamped to `1` because `0` reads as *unknown* to the audio budget. The
  projection **imports** that function rather than re-deriving the rule (one home for the unit rule).
- `pubdate_str = time.strftime("%Y-%m-%d", time.gmtime(pubdate))` — UTC, the shape `archive.py:470` and
  `integrity.py:572` both consume (the bridge renders it identically, `manifest_derivation.py:95`).
- **Disclosed limit of the floor:** `coverage --quality` bounds every cue's end against the row's `duration_s`
  (`quality.py:668-696`, tolerance 1 ms). A caption whose last cue ends more than 1 ms past the **floored**
  duration adds the defect reason `out_of_range` for that row. The store's own second-resolution is the cause, not
  this mapping (the same floor is the bridge's shipped rule); `verify` is untouched by it — its artifact check
  reads shape, not the duration bound (`integrity.py:588-619`).

---

## 4. Q2(b) — the frontmatter, the `raw` sidecar, and what is deliberately absent

### 4.1 The exact frontmatter key set

`write_archive` builds frontmatter from the entry it is handed (`archive.py:472-480`). Handing it the candidate's
part facts plus `source=<stored source_kind>` produces **exactly these nine keys, and no others**:

| Key | Value | Source of the fact |
|-----|-------|--------------------|
| `bvid` | `video_parts.bvid` | store |
| `title` | `video_parts.title` (the **part** title, not the collection's) | store |
| `date` | `pubdate_str` (§3.4) | store, rendered |
| `duration_s` | `duration_s_from_ms(duration_ms)` (§3.4) | store, converted |
| `source` | the winner's `transcripts.source_kind` **verbatim** | store |
| `url` | `archive_url(entry)` — `https://www.bilibili.com/video/{bvid}` (+`?p=n` for `page_index > 0`) | derived from `bvid`/`page_index`, `archive.py:41-45` |
| `work_id` | `{bvid}:p{page_index}` | store, Python identity |
| `page_index` | `video_parts.page_index` | store |
| `cid` | `video_parts.cid` | store |

The last three are emitted because the entry is resolved (`archive.py:478-479`: `work_id` present and not
`unresolved`). Keys are rendered as `f"{k}: {json.dumps(v, ensure_ascii=False)}"` (`archive.py:480`), so string
values appear quoted.

### 4.2 The keys this bundle **omits**, and why each omission is deliberate

| Omitted key(s) | Why it cannot appear | Mechanism |
|----------------|----------------------|-----------|
| `asr_mean_confidence`, `asr_low_confidence_cues`, `asr_low_confidence_at`, plus any per-cue `confidence` in the sidecar | the store has **no confidence column and no score to read**: `transcript_segments` holds `start_ms`/`end_ms`/`text` only (`schema-transcripts.sql:37-45`). A zero score would read as a measured `0.0` | `_confidence_summary` returns `{}` when no segment carries a numeric `confidence` (`archive.py:351-362`) and its `update` is a no-op (`:475`) — the omission is structural, not a convention |
| `asr_vad_segments`, `asr_vad_captured_s`, `asr_vad_captured_ratio` | the VAD/capture summary is an **ASR-capture** measurement; the store records no VAD boundary list and a caption is not a capture | emitted only when `source == "asr"` (`archive.py:473-474`); this command's `source` is the stored caption kind (§4.1), so the call never runs |
| every other `asr_*` provenance key — the nine `ASRConfig` fields the runner renders, each prefixed `asr_` by the writer: `model_name`, `model_revision`, `device`, `language`, `vad_model`, `vad_max_segment_s`, `hotwords`, `offline`, `local_source` (`asr.py:647-688`; `archive.py:476-477`) | `asr_provenance` is the ASR runner's redaction-safe configuration; the store holds `transcripts.model_id` (a nullable FK, `schema-transcripts.sql:19`, `:27`) and no device/VAD/hotword facts, so nothing true can be written | the parameter is passed **not at all** (`archive.py:452`, `:476-477`); no key is fabricated and none is defaulted |

**No key is zero-filled or guessed.** A key that cannot be supported is absent, and absence is the claim: the
bundle says *this is a caption, published from the store*, not *this is an ASR run*. Compass criterion 4 checks
exactly this by inversion — `rg -n '^\s*(asr_|confidence)' <published md>` must return **no match**.

### 4.3 The `raw` sidecar

The projection passes **`raw=None`** and lets the writer synthesize (`archive.py:481-484`):

```json
{"segments": [{"start": 0.46, "end": 3.74, "text": "…"}], "source": "subtitle-ai"}
```

- **Why the writer's own shape and not a hand-built dict:** a second sidecar shape is a second contract, and the
  readers already accept exactly this one — `integrity._valid_artifact` reads `document.get("body",
  document.get("segments"))` and requires a list of objects (`integrity.py:606-618`), and `quality._read_cues`
  reads `segments[].start/end/text` (`quality.py:589-625`). No `provenance` key is added, because
  `asr_provenance` is not passed (`archive.py:483-484`).
- **The store has no `lan`/`lan_doc`**, so the legacy raw document's fields (`{lan, lan_doc, body[]}` with
  seconds under `from`/`to`, `subtitles.py:146-155`, `:160-165`) are neither reproduced nor imitated. The projection writes
  `transcripts/raw/`, never `subtitles/raw/` — the directory the store path deliberately stopped writing
  (`sqlite-queue-bridge-contract.md` §4).

---

## 5. Q3 — the recorded state, idempotency, and half-written bundles

### 5.1 The row: one status, and the exact key set

The command appends **one manifest row per published candidate** through `ManifestStore.upsert`
(`manifest.py:261-296`, append-only), carrying **exactly these fifteen keys**:

| Group | Keys |
|-------|------|
| the store-derived field set (the bridge's nine, `manifest_derivation.py:87-97`) | `work_id`, `bvid`, `page_index`, `cid`, `title`, `duration_s`, `pubdate`, `pubdate_str`, `status` |
| this publication's products, root-relative to the write base (`archive.py:488`) | `srt_path`, `txt_path`, `md_path`, `raw_path` |
| the published transcript's identity, in the readers' own vocabulary | `source` (the winner's `source_kind`), `language` (the winner's `language`) |

`source`/`language` are added because the readers already read those two keys and the products record neither:
`quality` reads `row["source"]`/`row["language"]` for its per-row columns (`quality.py:300-302`), and
`search_index` reads `entry.get("source")` / `entry.get("sub_lan") or entry.get("lan") or
entry.get("language")` for its `--source`/`--language` filters (`search_index.py:593-594`; the CLI exposes both,
`cli.py:438-445`). Nothing else is added: no `audio_path` (no audio exists for a caption), no `sub_lan`/
`sub_lan_doc` (legacy subtitle keys, `subtitles.py:161-165`), no `artifact_paths` (a coordinator attempt-record
key).

### 5.2 `status: archived` — and why not the other two

The row's `status` is **`archived`**.

| Candidate status | Verdict | Mechanism |
|------------------|---------|-----------|
| `archived` | **chosen** | it is the state the chain itself writes after `write_archive` **and** a successful `archive_bundle_complete` (`coordinator.py:501-518`; `_mark_archived`, `:520-527`, `:621-624`). The projection performs exactly that work, so it records exactly that statement. It is also the status the readers require to stop calling the row unfinished (§5.3) |
| `subtitle_done` | **structurally excluded** | the reader additionally requires `subtitles/raw/{canonical_stem}.json` and raises `missing_raw_subtitle` when it is absent (`integrity.py:370-380`) — and the store path never writes that document (`sqlite-queue-bridge-contract.md` §4). Choosing it would publish a row `verify` reports defective |
| `asr_done` | rejected | it asserts ASR produced the transcript (the chain's `asr_done` sits between `audio_ok` and the archive stage). For a caption that statement is false; the bridge's §3.3 rule is the same one — a derived row may not claim work that was not done |

Consequences of `archived`, each a shipped behaviour and not a new one: `coordinator.TERMINAL_STATUSES` contains
it (`coordinator.py:45`), so `run`/`schedule`/`campaign` skip the row; `_SKIP_HARVEST_STATUSES` contains it
(`:41-43`), so the chain never re-harvests it; `export.COMPLETED_STATUSES` and
`search_index.COMPLETED_STATUSES` contain it (`export.py:35`, `search_index.py:21`), so the row becomes
exportable and indexable; `coverage`'s `_category` counts it complete (`coverage_report.py:520-524`).

### 5.3 How the readers agree it is done

- `verify --trusted-local` no longer raises `retryable_incomplete` (raised for `pending`/`meta_ok`/`sub_checked`/
  `needs_audio`/`audio_ok`, `integrity.py:385`), and for `archived` it requires the four families to be present
  **and** `archive_bundle_complete` to pass at a base the row resolves under (`integrity.py:356-369`).
- `coverage --quality` counts the row valid when its artifact set yields no **defect** code
  (`cli.py:1578-1584`; defect vocabulary `quality.py:15-25`) and reports `artifact_count` as the number of
  readable declared artifacts (`quality.py:271`, `:305`) and `cue_count` as the accumulated cue count over the
  artifacts that carry cues (`quality.py:272`, `:564-627`) — for a projected row: the `srt` and the `raw` sidecar
  carry cues, so the expected value is `2 × (the winner's segment count)`.
- **The JSON `reasons` list is wider than validity.** The row's `reasons` is the union of the defect codes and
  the advisory content codes (`cli.py:1564-1567`), while validity reads the defect list alone (`cli.py:1578`).
  Compass criterion 3 asks for `reasons: []`, so **Fixture F's caption body must carry no advisory content code
  either** (`low_confidence`, `leading_mark`, `fragment_cue`, `overlong_cue`, `duplicate_cue`, `repeated_ngram`;
  `quality.py:26-34`, `:699-733`) — the fixture's text is chosen for that, and T5 pins the literal empty list. On
  a real corpus an advisory code may appear on a perfectly valid row; that is not a defect and not this command's
  to prevent.
- **The green `verify` exit needs the fixture's attempts sidecar.** `verify` exits `0` only when both `defects`
  **and** `diagnostics` are empty (`cli.py:3328`), and a manifest without `coordinator/attempts.jsonl` raises
  `missing_attempts_sidecar` (`integrity.py:314-328`, `MISSING_ATTEMPTS` at `:32`). The projection writes no
  attempts record — that ledger is chain stage evidence (`coordinator.py:34-58`) and writing one would be
  inventing a stage attempt. **Fixture F must therefore hold `coordinator/attempts.jsonl`** (an existing empty
  file reads as `available` with zero records, `sidecar_projection.py:259-299`); the plan's T5 builds it that way
  and the compass criterion 1/3 check is run on that fixture. On a root where the chain never ran, the same
  diagnostic appears regardless of this command.

### 5.4 The `already_published` predicate — the only thing that makes "never rewrite" true

Per candidate, against the write base (`artifact_roots.write_base`, the base a write would use,
`artifact_root.py:127-130`):

```text
recorded = ManifestStore.load().get(work_id)      # effective row, last write wins; None if absent
declared = the four *_path strings of `recorded`  (all four present and strings, else None)
already  = declared is not None
           and archive_bundle_complete(write_base, declared)      # recomputes the marker's sha256s
```

- **`already_published` ⇒ nothing is written at all**: no file, no marker, no manifest row. This is what makes
  compass criterion 2's byte-identical comparison true, and it is the range D3 states: *"left alone" ranges over
  a bundle the archive's own completeness reader counts complete*.
- **The probe is the reader, not a bespoke check**: `archive_bundle_complete` (`archive.py:170-206`) is the same
  function `verify` calls (`integrity.py:356-358`) and `coverage` calls (`coverage_report.py:469-471`), and it
  returns `False` — never raises — for a missing file, a missing marker, a marker whose shape is wrong, or a
  marker whose recorded `sha256` disagrees with the file (`archive.py:170-206`).
- **The probe is against the write base, deliberately.** `verify`/`coverage` resolve a recorded path over
  `read_bases()` (artifact root, then archive root; `artifact_root.py:132-136`, `integrity.py:170-192`). This
  command instead asks "is the bundle **where I would write it**", because its promise is that the products are
  under the configured root (criterion 1) — probing all read bases would print `already_published` while the
  configured root held nothing. Both `verify` and `coverage` still find the bundle at the write base first.
  Falsifier: an operator requirement that a legacy bundle at the archive root must suppress publication into a
  configured artifact root — that reopens §2.2/§5.4, not the writer.
- **Products without a row are not `already_published`** (no `declared` = the row does not record a bundle): the
  candidate is published — the writer re-emits the same bytes for the same stored body — and then records the
  row, so the state left behind by a run killed between its write and its `upsert` heals on the next run instead
  of staying invisible forever.

### 5.5 The five states the fixture discriminates

| State | Decision | Mechanism |
|-------|----------|-----------|
| (i) transcript, no bundle, no row | `published`, exit `0` | no `declared` ⇒ publish path |
| (ii) chain-archived bundle (row `archived` + four declared paths + valid marker) | `already_published`, **nothing written** | §5.4's probe passes at the write base |
| (iii) published, then the store gained a **second version** | `already_published`; the published bytes stay identical | the row already declares a complete bundle, and the projection never consults the winner's segments for an `already_published` candidate — the next-version drift non-goal, disclosed in `--help` (§7) |
| (iv) publication interrupted before the marker (or a marker whose hashes disagree) | `published` — the writer invalidates a stale marker before replacing and writes the new marker **last** (`archive.py:239-242`), so the row heals. If the writer's staging guard refuses (`.archive-bundle-stage` left behind by the interrupted attempt, `archive.py:228-230`), that part prints `failed (<code>)` and the run exits `1` | §5.4 returns `False` ⇒ publish path; D10d keeps the exit stance |
| (v) a `gone` part holding a transcript, no bundle, no row | `published`, exit `0` | §2's membership rule is not filtered by `processing_status` (D10b): a `gone` part still holds local text, so (v) takes (i)'s path — nothing in §5.4 keys on the part's upstream state |

### 5.6 What is *not* recorded, and what does not move

- **The store is read, never written.** The connection is the shipped read-only one (`mode=ro` URI,
  `cli.py:680-716`, opened through `_open_subtitle_connection(..., read_only=True)`, `:748-802`) — a write would
  fail inside SQLite rather than reach the file. `processing_status`, `transcripts`, `transcript_segments`,
  `acquisition_runs` and `acquisition_attempts` are untouched; the projection writes no run and no attempt row.
  The `mode=ro` precedent is `probe-subs`' own "writes nothing at all" promise (`cli.py:759-762`) and the bridge
  (`derive-manifest`, `cli.py:1206-1221`).
- **Nothing is written back into the store from the manifest** (D3): the row records a publication; it changes no
  store state, and the derived audio queue is unaffected (criterion 3's `derive-manifest queue=<n>` check, §10).
- **No `subtitles/raw/` document**, no audio, no second artifact family beyond the writer's four (§4.3).
- **The writer publishes atomically-enough and verifiably**: after `write_archive`, the command re-asks
  `archive_bundle_complete` before recording the row — the chain's own discipline at the same point
  (`coordinator.py:501-505`). A publication that the reader does not confirm is a `failed` candidate,
  `exit 1`, and **no row** is written for it.

---

## 6. Q4 — `asr-local`: in range, with its identity rule named and its provenance gap disclosed

**Decision: the candidate relation is not filtered by `source_kind` (D10b ranges over "every stored part that
holds a transcript"), the mapping is kind-agnostic, and the `asr-local` *identity/provenance* rule is explicitly
deferred to the audio/ASR iteration — names and citations below. No producer exists today.**

- **No shipped command can write an `asr-local` row.** The one transcript writer validates its `source_kind`
  against the *caption* vocabulary — `ALLOWED_CAPTION_SOURCE_KINDS = ALLOWED_SOURCE_KINDS - {"asr-local"}`
  (`storage/models.py:471-476`), used at `database.py:885-889` — while the column's CHECK admits all three
  (`schema-transcripts.sql:15-17`). The read path already accepts the reservation with "no rows yet"
  (`database.py:1036-1042`). The ASR/audio chain writes no SQLite at all (D2).
- **The mapping needs no new rule for it.** The command passes `source=<the stored source_kind>` verbatim (§4.1)
  and converts segments identically, so if such a row appears the candidate publishes without a contract change.
  The bundle stays per part: this iteration adds **no** identity rule inside the store and none in the path
  (§3.1), which is what keeps the deferral from blocking the range.
- **The deferred half, named:** `asr-local` keeps a **per-model/run** identity rule rather than the caption kinds'
  content-hash uniqueness — `ux_transcripts_subtitle_content` is `WHERE source_kind IN ('subtitle-ai',
  'subtitle-cc')` and the schema says in as many words that the `asr-local` identity rule belongs to the
  audio/ASR iteration (`schema-transcripts.sql:30-35`); the queue-bridge contract already hands it to the same
  iteration (`sqlite-queue-bridge-contract.md` §6, D5). Deciding it means deciding what makes two `asr-local`
  transcripts of one part the same transcript (the `model_id` + run relation), which needs rows that do not exist.
- **The disclosed gap:** for an `asr-local` transcript the projected bundle would carry `source: "asr-local"`
  and **no `asr_*` provenance keys**, because the store's provenance is `transcripts.model_id` (an FK into
  `asr_models`) and this iteration maps no `asr_models` read. The seam exists and is not redesigned: the writer
  already takes `asr_provenance` and writes `asr_*` keys from it (`archive.py:452`, `:476-477`), so carrying
  provenance later is passing an argument, not changing the bundle layout. The branch is unreachable for stores
  the shipped writers produce; it is pinned by fabricated input (§10 T3) so a reader can tell a defensive branch
  from a live risk.

---

## 7. The operator surface (D10, restated only where a mechanism is needed)

```text
bili-asr publish-transcripts [--bvid <bvid[:pN]>] [--limit-parts N]
                             [--archive-root <root>] [--artifact-root <root>]
```

- **Printed lines**, one per candidate, in §2's locked order, then the summary line with every count including
  the zeros:

  ```text
  <work_id>: published (source=<source_kind> lang=<language> version=<v> cues=<n>) <md path>
  <work_id>: already_published
  <work_id>: failed (<reason>)
  publish-transcripts: candidates=<n> published=<n> already_published=<n> failed=<n>
  ```

  `<md path>` is the recorded root-relative form (`transcripts/md/{name}.md`, `archive.py:488`), **not** a
  filesystem path — the convention the archive already records (`artifact_root.py`, D7). `cues=<n>` is the
  winner's stored segment count. `<reason>` is a bounded redacted scalar: the command's own literals
  `empty_transcript` / `bundle_incomplete`, and otherwise `coordinator._safe_error_code(exc)`
  (`coordinator.py:117-128`: a `code` attribute, else the exception class name, sanitised to ≤64 characters —
  `:34-58`). No exception message, path or URL is printed. `published + already_published + failed == candidates`
  holds by construction, and the summary prints whether or not a candidate failed.
- **`--archive-root`** defaults to `DEFAULT_ARCHIVE_ROOT` (`cli.py:36`, the convention every command shares);
  `--artifact-root` is carried like the other product-writing commands — flag wins over `BILI_ARTIFACT_ROOT`,
  unset = the archive root, resolved once before the writer lock by `roots_for` and refused with its four named
  lines as exit `1` (`cli.py:3482-3495`, `artifact_root.py:90-136, 224-270`).
- **The writer lock.** The command joins `_ARCHIVE_WRITER_COMMANDS` (`cli.py:3420-3431`), so `main()` takes
  `archive_writer(args.archive_root)` before dispatch (`:3504-3512`) and a concurrent archive-writer command
  makes it exit `1` with `publish-transcripts: archive_busy`. It writes files and appends manifest rows, so it is
  a writer by the set's own meaning; the lock also creates `{archive_root}/coordinator/` even when the run then
  fails (shipped behaviour).
- **Exit stance (D10d).** `0` when every candidate is published or already published — **including no
  candidate**; `1` for a usage/configuration error (a refused artifact root, an unknown `--bvid`, a
  non-positive `--limit-parts`, a missing/unreadable `archive.db`, the transcript-schema guard, `archive_busy`)
  or a candidate whose bundle could not be published (that part is named, the summary still prints); **`2` is not
  produced by this command** — it opens no socket, and `_UsageErrorArgumentParser` maps argparse's `2` to `1`
  (`cli.py:83-93`). The frozen exit taxonomy is untouched (§13).
- **`--help` must carry the range and the two disclosures**, in these literal substrings (criterion 6a is a text
  check): `stored transcripts`; `fetches nothing`; `a complete published bundle is never replaced`;
  `newer transcript version`; `already carries an earlier manifest state`. The wording must not widen the
  promise: the bundle that is "never replaced" is the **complete** one (§5.4), and the earlier-manifest-state
  limit is the readers' append-only-history defect (`e2e-23191782-season-7686105 · R2`, high) the projection
  inherits.
- **A disclosed consequence of §5.4** (goes on the same operator surface, §11): a part whose row the **legacy**
  caption path published (`subtitles.harvest_subtitle`: `status: subtitle_done`, only `srt_path` + `sub_lan`,
  `subtitles.py:160-165`) does not declare a complete bundle, so the projection publishes the four families from
  the store's transcript and **replaces that part's `transcripts/srt/{stem}.srt`** when the legacy row was
  page-qualified (its stem is the same `artifact_stem`, `subtitles.py:151-153`; a bare-`bvid` legacy row's file is
  named after the `bvid` alone, `archive.py:34-38`, and is not touched). The legacy raw document under
  `subtitles/raw/` is never touched. This is inside D3's stated range (a bundle the completeness reader does not
  count), and it is stated here so it is not discovered later.

---

## 8. Modules, interfaces, affected readers

**Composition follows the repo's cross-layer rule** — only `cli.py` composes layers
(`{SPECS_DIR}/asr-archive-cli.md:61`; the same shape as `_cmd_derive_manifest`, `cli.py:1172-1276`): the store
read is a repository call, the decision is a pure service, the publication is the existing writer, the record is
`ManifestStore`. No service imports another layer to perform I/O.

```text
cli.py  _cmd_publish_transcripts
  ├─ _open_subtitle_connection("publish-transcripts", root, read_only=True)   cli.py:748-802
  ├─ TranscriptRepository(connection)
  │    ├─ list_selected_parts(bvid, page_index)        # the selector guard, database.py:1174-1203
  │    ├─ list_stored_transcripts(bvid, page_index)    # NEW — §2.1
  │    └─ read_transcript(part_id, kind, lang, version)  # the winner's body, database.py:1023-1075
  ├─ services.transcript_projection                     # NEW, pure: no I/O, no manifest, no archive import
  │    ├─ ordered_candidates(rows, limit) -> tuple[Candidate, ...]
  │    ├─ writer_segments(record.segments) -> list[dict]
  │    └─ projection_row(part, transcript, paths) -> dict
  ├─ archive.bundle_paths(write_base, entry)            # NEW public extraction of archive.py:465-471
  ├─ archive.archive_bundle_complete(base, paths)       # the shipped reader, archive.py:170-206
  ├─ archive.write_archive(write_base, entry, segments, source=kind)   # archive.py:452, raw=None
  └─ ManifestStore(root=archive_root).upsert(row)       # manifest.py:261-296
```

**Consumes**

| Input | Contract |
|-------|----------|
| `{archive_root}/archive.db` | opened **read-only** (`mode=ro`), existing file only, transcript-schema capability required (`cli.py:680-716`, `:748-802`) |
| `TranscriptRepository.list_selected_parts(bvid, page_index)` | the selector guard (§2.2) |
| `TranscriptRepository.list_stored_transcripts(bvid=None, page_index=None)` | **new read** (§2.1) — one row per stored transcript version with its part context, in the locked order |
| `TranscriptRepository.read_transcript(video_part_id, source_kind, language, version)` | the winner's `TranscriptRecord` with its segments, existing read (`database.py:1023-1075`) |
| `{archive_root}/manifest/manifest.jsonl` | read-only through `ManifestStore.load()` (`manifest.py:151-177`) for §5.4 |
| `ArtifactRoots` | `write_base` for every write and probe, `read_bases()` only where a reader resolves (`artifact_root.py:94-136`) |

**Produces**

| Output | Contract |
|--------|----------|
| `{write_base}/transcripts/{srt,txt,md,raw}/…` + `.bundle-ready` marker | the existing writer's four families and its `archive-bundle-v1` marker (`archive.py:109-114`, `:220-261`) |
| appended rows in `{archive_root}/manifest/manifest.jsonl` | §5.1's fifteen keys, `status: archived`, through `ManifestStore.upsert` |
| `{archive_root}/coordinator/archive-writer.lock` | created by the shipped lock, not by this command (§7) |
| stdout/stderr | §7's per-candidate lines and one summary line |

**Affected readers** (all unchanged by this iteration; listed because the command adds rows and products they
read — the same blast-radius table the bridge kept):

| Reader | Where | Effect of a projected row |
|--------|-------|--------------------------|
| `verify --trusted-local` | `cli.py:3310-3328` via `integrity.py:251-388` | row stops being `retryable_incomplete`; bundle required and marker recomputed (`:356-369`) |
| `coverage` / `coverage --quality` | `cli.py:1710`, `:1466` via `coverage_report.py`, `quality.py:216-311` | `artifact_present` true, category complete, `artifact_count=4`, cues counted |
| `export`, `search` | `export.py:35`, `search_index.py:21`, `:593-594` | `archived` puts the row in the completed set; `source`/`language` feed the filters |
| `download-audio --missing-subs`, `asr --pending`, `pilot`, `run`/`schedule`/`campaign --scope pending` | `cli.py:1306`, `:1773-1776`, `:1808-1809`, `:2530-2548` | **unchanged result**: a projected row is terminal (`coordinator.py:45`) and outside `_HARVEST_STATUSES` (`:39`) |
| `derive-manifest` | `cli.py:1172-1276` | **unchanged**: its relation is the no-transcript view (`schema-transcripts.sql:138-141`); the store did not move |
| `status`, `runs` | `cli.py:1418-1461` (`status`: "metadata state from the fresh SQLite database only"), `_cmd_runs` | unchanged — they read the metadata tables/backlog, not the manifest and not this relation |

---

## 9. Risks and rollback

- **Risk — a projected bundle is not accepted by the archive's own readers** (wrong stem, wrong md name, a
  sidecar the readers reject). Mitigated by §3.1/§4.3 using the writer's own names and shapes, and proven by the
  plan's T5, which runs `verify --trusted-local` and `coverage --quality` rather than a bespoke probe. If it
  fails, the failure is a contract defect: STOP and return to this file, not to the test.
- **Risk — the projection rewrites something the chain published.** Mitigated by §5.4 (`already_published`
  writes nothing at all) and pinned by criterion 2's hash comparison, including the chain-archived control. The
  one republish path that touches a chain-written file is the legacy `subtitle_done` `srt` (§7) — disclosed, not
  silent.
- **Risk — the frontmatter claims more than a caption can know.** Mitigated structurally (§4.2: the omissions
  are the writer's own branches given this command's inputs) and checked by criterion 4's inverted `rg`.
- **Risk — a store that gained a newer version silently keeps stale products.** This is the stated non-goal, not
  a defect: the command prints `already_published`, the bytes stay, and `--help` discloses the limit (§7).
- **Rollback.** Stop running the command: nothing else changed. The store is untouched, the manifest is
  append-only, and the chain's vocabulary and code are untouched. A projected row's effect is that its part is
  terminal for the chain (as a chain-archived row would be) and its bundle is readable by the shipped readers.
  To undo one: delete the four files and the marker, and append the row the operator wants — the command itself
  offers no delete path. No schema change, no migration, no new dependency, no socket.

---

## 10. Validation plan — how the compass criteria become checkable

**Pinned invocation for every case below** (the plan's Global Constraints; Phase 2 runs in a linked worktree with
no `.venv`, and the control root's editable install points at the control root's `src`):

```bash
cd <worktree>/bilibili-asr-archive \
  && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v
cd <worktree>/bilibili-asr-archive \
  && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -c \
     "import bili_asr, pathlib; print(pathlib.Path(bili_asr.__file__).resolve())"
```

**Fixture F** (criteria 1–4): a disposable archive root built **in a test**, through the repository APIs (the
derive-manifest test file's own discipline: "no test here writes raw SQL into `archive.db`",
`tests/test_cli_derive_manifest.py:23-26`), holding the five states the criteria discriminate:
(i) a part holding a `subtitle-ai` transcript and no bundle; (ii) a part whose bundle the chain archived normally;
(iii) a part whose bundle was published and whose store then gained a **second transcript version**;
(iv) a part whose publication was interrupted before the marker; (v) a part whose `processing_status` is `gone`
and which holds a transcript. It also holds an **empty `{F}/coordinator/attempts.jsonl`** (§5.3) and **at most one
manifest row per `work_id`** (the readers' append-only-history non-goal, `e2e-23191782-season-7686105 · R2`). Its
caption body is chosen to carry no advisory content code either, so criterion 3's literal `reasons: []` holds
(§5.3).

| Criterion | What makes it checkable, from this contract |
|-----------|---------------------------------------------|
| **1** (a stored transcript becomes a complete bundle) | §2.1's relation + §3's identity/content + §4's key set + §7's printed line and summary. Expected stem `{bvid}.p{page_index}`, four families under `write_base`, marker beside the `srt`; the reader that counts them is `verify --trusted-local` (§5.3), run in T5 |
| **2** (idempotent; never rewrites a complete bundle) | §5.4 is the predicate: run 2 prints `published=0 already_published=<n>`, every hash identical, store counts and `content_sha256` unchanged because the connection is `mode=ro` (§5.6). (ii) moves nothing; (iii) stays byte-identical; (iv) republishes or fails per §5.5 |
| **3** (the readers agree the row is done) | §5.2's status + §5.3's three reader checks (`verify` exit `0` with no defects **and** no diagnostics on Fixture F; `coverage --quality` `reasons == []` (the fixture body carries no advisory code either, §5.3), `artifact_count=4`, `cue_count=2×segments`, the row in `valid_work_items`; `derive-manifest` `queue=<n>` unchanged) |
| **4** (the bundle claims no more than the store knows) | §4.1's nine-key list, §4.2's omission table, §4.3's sidecar. The check is the inverted `rg -n '^\s*(asr_|confidence)' <published md>` (no match) plus the sidecar's key set, and `source:` equals the stored `source_kind` verbatim |
| **5** (F4: cwd-independent self-check) | §12: the anchor plus one test that runs `cli.main(["check-asr-env"])` from a cwd that is neither the package root nor the repo root, asserting the located-script outcome (five `check:` lines and one `asr-env:` verdict, never `no check script found`) and exit `0`/`1` |
| **6** (the bound is stated where an operator reads it) | §7's five literal `--help` substrings; the documentation task's `rg` check over the two named files (§11); and the compass's own `## Roadmap Position` read (PM-owned) |

**Named cases the tasks must contain** — pure service: winner = uploader caption over machine caption; winner =
latest version of the chosen identity; family order `zh` before `en` and code as the in-family tiebreak; one
candidate per part; `--limit-parts` bounds parts; ms→s conversion exact; a zero-segment winner refuses rather
than publishing an empty bundle; the row's key set equals the declared fifteen; the declared family order equals
the harvester's; an `asr-local` fabricated row maps with no invented provenance. Repository: one row per version
with part context; locked order; a `gone` part included; a part without a transcript excluded; selector
narrowing; empty store. CLI: the printed line and summary shapes; idempotence by hash; the chain-archived
control; the marker-less republish; the stale-staging failure and exit `1`; unknown `--bvid` exit `1` and no
write; a known `--bvid` with no transcript = zero candidates, exit `0`; non-positive `--limit-parts` exit `1`;
help text; the writer lock; the store connection is read-only; products under `--artifact-root` with state at
the archive root. Readers (T5): the three reader checks of criterion 3, the criterion 4 key checks, and the
second-version drift check.

---

## 11. Disclosures the published surfaces must carry

| Disclosure | Where it must appear |
|------------|----------------------|
| The command publishes **stored** transcripts and fetches nothing: no network, no download, no ASR | `--help` (criterion 6a); README's command section (T6) |
| A **complete** published bundle is never replaced; a store that later gains a newer transcript version leaves the published product as it is | `--help`; README; `docs/metadata-storage.md` (T6) |
| A row that already carries an earlier manifest state is outside what the archive's readers currently agree on (`e2e-23191782-season-7686105 · R2`, high) | `--help`; README |
| One bundle per part, so a part holding two transcript identities publishes **one** of them (the §3.2 winner) and the other stays in the store | README (T6); the run's own line names the winner on every published candidate |
| A legacy `subtitle_done` part is republished from the store and its `srt` is replaced (§7) | README; `docs/metadata-storage.md` |
| An `asr-local` transcript would publish with `source: "asr-local"` and **no** `asr_*` provenance keys (§6) | contract only (no producer exists); README one sentence if the T6 pass judges it operator-relevant |

The documentation files the "publish the boundary" task may edit are **exactly** two:
`bilibili-asr-archive/README.md` and `bilibili-asr-archive/docs/metadata-storage.md` (the plan's Global
Constraints limits doc edits to the files named here). Everything else stays out — `{KNOWLEDGE_DIR}/**`,
`{SPECS_DIR}/**`, any other file under `docs/`, and any other iteration's package. Two claims of the same command
sit outside this bound and are the PM's (compass **D14**, rows **Q6**/**Q7**): the added-command enumeration and the
"**11** commands" `--artifact-root` count in `{SPECS_DIR}/asr-archive-cli.md` (§13 below), and the same count and the
same command lists in `bilibili-asr-archive/docs/artifact-root.md:89-103`.

---

## 12. The folded-in F4 fix (`check-asr-env`'s anchor) — the mechanism this contract fixes

Finding F4 / register row `e2e-23191782-longform-pair-webdav · R1`: the handler anchors its script at
`Path(__file__).resolve().parents[3] / "scripts" / "check_asr_env.py"` (`cli.py:3229`) with the comment
"src/bili_asr/cli.py -> repository root -> scripts/" (`:3228`) and a docstring that repeats the wrong arithmetic
(`:3210-3214`, "``src/bili_asr/cli.py`` → ``../../../scripts/``"). In this repository `parents[2]` is the
**package root** (`…/bilibili-asr-archive/bilibili-asr-archive`, which holds `scripts/`), so `parents[3]` always
names `…/bilibili-asr-archive/scripts/check_asr_env.py`, which does not exist; the only candidate that can hit is
the cwd-relative one (`:3230`). Measured: exit `0` from the package root, exit `1` with `no check script found`
from the login cwd and from the repo root (`e2e.md` §R2-A1, `:291-300`).

**Fix shape:** `parents[3]` → `parents[2]`, plus the comment and the docstring corrected to the same arithmetic.
The candidate order (override → package anchor → cwd) and the exit contract are unchanged — D6 fixes this item to
the anchor plus one test, and the no-new-exit-code non-goal forbids widening it. **The test** (T7) runs
`bili_asr.cli.main(["check-asr-env"])` with `BILI_ASR_CHECK_SCRIPT` deleted and the cwd set to a directory that is
neither the package root nor the repo root, and asserts the *located-script* outcome: the five `check:` lines and
one `asr-env: verified|not verified (n failed)` verdict on stdout, `no check script found` absent, and exit `0`
or `1` per host. On the pre-fix anchor that assertion fails (no candidate resolves from a foreign cwd); that is
the discriminator, and it is what makes criterion 5's claim checkable without a GPU.

---

## 13. What the frozen spec owes (recorded; the revision is the PM's)

`{SPECS_DIR}/asr-archive-cli.md` is frozen and **is not edited by this iteration**. Two sentences of its own
revision note become stale the moment `publish-transcripts` ships, and one sentence stays true:

1. **Stale — the command list.** `asr-archive-cli.md:42-44` enumerates the commands added since the frozen list
   (`derive-manifest`, `coverage`, …, `reconcile`). `publish-transcripts` belongs in that enumeration and is not
   there.
2. **Stale — the flag count.** `asr-archive-cli.md:45` reads "**`--artifact-root`** … on the **11** commands";
   after this plan the flag is on the twelfth (`cli.py:38`'s comment says "eleven" today and moves with it).
3. **Unchanged — the exit taxonomy.** `asr-archive-cli.md:110-112` needs no revision for this command: it opens
   no socket, produces `0`/`1` only, and adds no exit value (`_UsageErrorArgumentParser` already maps argparse's
   `2` to `1`, `cli.py:83-93`). The command's `--artifact-root` semantics are the ones the note already records.

**Conclusion:** the frozen spec owes a revision of items 1–2 (a documentation delta, not a contract change); the
plan does **not** depend on it, and the revision plus its sign-off are the PM's (`asr-archive-cli.md:6`: change
policy). Recorded here so the next reader does not "fix" the spec inside a plan.

---

## 14. Deferred, and where the deferral is tracked

| Deferred | Where it is tracked |
|----------|---------------------|
| `asr-local`'s per-model/run identity rule and its provenance mapping (`model_id` → `asr_*` keys) | §6; `schema-transcripts.sql:30-35`; the audio/ASR iteration (queue-bridge contract §6, D5) |
| Replacing a published product when the store gains a newer transcript version | compass `## Non-Goals` (next-version drift); §5.5 (iii); disclosed in `--help` |
| The readers' append-only-history disagreement (`e2e-23191782-season-7686105 · R2`, high) | compass `## Non-Goals`; §5.4's one-row-per-`work_id` fixture limit |
| The artifact-root measurement hardening (`iter-2026-09-artifact-root · R2`) and the five-module path pairing (`· R3`) | compass `## Non-Goals` / `## Roadmap Position`; untouched here |
| `{SPECS_DIR}/asr-archive-cli.md` revision (items 1–2 of §13) | §13; owner PM |
| The live E2E re-run of the pair on the target host | compass `## Roadmap Position` item 1; owner `project-manager` after this iteration merges (D5: never a task or gate of this plan) |

---

## Recall receipt (Prepare input, per `mstar-phase-gates` §A)

**Read and reused**

- `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md` — the cross-layer composition rule and the
  read-only probe precedent the command follows (§8); the exit taxonomy (§7).
- `{KNOWLEDGE_DIR}/architecture-patterns/normalized-transcript-storage.md` — the transcript identity quadrant
  (`video_part_id`, `source_kind`, `language`, `version`), the content-hash uniqueness and the `asr-local`
  reservation: the basis of §3.2 and §6.
- `{KNOWLEDGE_DIR}/architecture-patterns/artifact-root-split.md` — `write_base` vs `read_bases()`, root-relative
  recorded paths and the four refusal lines: §2.2, §5.4, §7.
- `{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md` — the no-back-write rule §5.6 restates, and the
  manifest-well-formedness judgement behind §5.1.
- `{KNOWLEDGE_DIR}/architecture-patterns/queue-derivation-bridge.md` — the bridge's additive policy, its
  field-set discipline and its "one call, not restated SQL" rule: the model for §2 and §5.
- `{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md` — the review lens for every sentence here; §4.2's
  omission table, §5.4's probe base, §6's disclosure and §7's help wording are written to its rules.
- `{KNOWLEDGE_DIR}/best-practices/pairing-rule-travels-with-behaviour.md` — the reason §2.1's membership rule
  travels with the read rather than with the command.
- `{KNOWLEDGE_DIR}/testing-patterns/worktree-test-invocation.md` — the pinned invocation in §10.
- The previous iteration's contract `{ITERATION_DIR}/iter-2026-09-queue-bridge/specs/sqlite-queue-bridge-contract.md`
  — the house shape (§-by-§, `file:line` for every claim, alternatives with their falsifiers, a validation-plan
  table) and the joint parts of the boundary this contract continues (its §3.1/§3.3/§3.4/§4/§6).
- The E2E report `.mstar/workflows/e2e-23191782-longform-pair-webdav/reports/e2e.md` — §R2-A1 (the F4 measurement),
  §R2-A3 (the two stored captions and their segment counts), §R2-A4 (the derived queue is idempotent and
  excludes transcript-holding parts), §R2-A8 (`verify`'s diagnostic surface and `coverage --quality`'s shape).
- `{SPECS_DIR}/asr-archive-cli.md` — the cross-layer rule (`:61`), the exit taxonomy (`:110-112`) and the
  revision note `:42-45` §13 concludes is stale.

**Read and rejected**

- "Write a `subtitles/raw/{stem}.json` from the store so the chain's archive stage can consume it" — rejected:
  that is the legacy document the store path stopped writing, it is lossy (no `lan`/`lan_doc`), and it would let
  a store-derived file become the chain's evidence of an upstream caption (queue-bridge contract §4).
- "Record `subtitle_done` so the row looks like the legacy caption path" — rejected in §5.2: the reader demands
  `subtitles/raw/` and would report `missing_raw_subtitle`.
- "Let each candidate's `already_published` probe every read base" — rejected in §5.4, with its falsifier.
- "Publish one bundle per stored identity (kind/version-qualified stem)" — rejected in §3.2: it changes the name
  rule the readers derive, and the stem carries no room for it.
- "Filter the candidate relation to the caption kinds" — rejected in §6: it would silently narrow D10b's
  membership rule, and the mapping needs no kind-specific rule.
- "Skip a part whose effective row is a legacy `subtitle_done`" — rejected in §7/§9: D3's range republishes what
  the completeness reader does not count, and the alternative invents a third skip vocabulary D10 does not have.
