# Compound round report — `iter-2026-09-subtitle-transcript-sqlite`

> Executor: writing-specialist (leaf; no subagents).
> Round: iteration-close knowledge crystallization for
> `iter-2026-09-subtitle-transcript-sqlite` (all three plans `Done`).
> Date: 2026-09-11.
> Source material: the iteration package (`README.md` + `specs/{subtitle-gateway,transcript-storage,subtitle-cli-contract}.md`),
> the three main plans under `{PLAN_DIR}`, the four pre-existing knowledge docs, and the shipped
> code/docs used to verify every claim before it was written down.

## 1. Deliverables

### 1.1 NEW `{KNOWLEDGE_DIR}/architecture-patterns/normalized-transcript-storage.md`

Path: `.mstar/knowledge/architecture-patterns/normalized-transcript-storage.md`
(frontmatter: `module: bili-asr transcript storage`, `date: 2026-09-11`, `problem_type:
architecture_pattern`, `category: architecture-patterns`, `severity: medium`, `plan_id:
20260911-transcript-storage`, six `applies_when` triggers, seven tags). Knowledge track.

Captures the delivered transcript-storage contract as durable guidance:

- **Reserved tables as the working store** — the exact `transcripts` shape (`language`
  `NOT NULL` with a non-blank check, `content_sha256` 64-lowercase-hex check, widened version
  key `(video_part_id, source_kind, language, version)`, both FKs `ON DELETE RESTRICT`) and the
  `transcript_segments` shape, including the note that "non-empty after trimming" is a
  repository rule rather than a DDL `CHECK`.
- **Locked decisions** — language as an attribute of the transcript (not the part); content
  identity as SHA-256 over the canonical JSON of `[start_ms, end_ms, text]` triples with the
  identity key deliberately excluded; the caption-only partial unique index
  `ux_transcripts_subtitle_content` and *why* its `WHERE` clause is load-bearing for the future
  `asr-local` versioning decision; immutability by three mechanisms with **no trigger**.
- **Process-record shape** — the `kind`-keyed `acquisition_runs` + `acquisition_attempts` pair
  with the verbatim DDL, `PK(run_id, video_part_id)`, the full outcome↔`error_code`↔
  `transcript_id` CHECK matrix, append-only evidence with no terminal per-part state,
  run-scoped `credential_present`, run-outcome derivation, and the recorded reason
  `ingestion_runs` (metadata-scoped, page-unit cursor semantics) was **not** overloaded.
- **Bootstrap split + structural guard** — `schema.sql` + `schema-transcripts.sql`, the
  `_accepts_transcript_script` predicate (fresh or already current, never half-applied),
  the structural `require_subtitle_schema` / `SchemaContractError` check (columns *and* the
  process tables plus the pending view), the caller-composed operator line, rebuild-by-policy
  with no migration reader, and the one guard gap (`transcript_segments`) with why it is
  unreachable through `open_database`.
- **Idempotency semantics** — `unchanged` (hash already held by some version, nothing written,
  the attempt points at the existing version) vs `stored` (`COALESCE(MAX(version),0)+1` append);
  the revert-to-older-content subtlety (the attempt references the older matched version while
  a default read returns `MAX(version)`), and the "a stored transcript is never empty" rule.
- **Pending view and enumeration order** — the `v_pending_subtitles` definition (ROW_NUMBER
  recency, `processing_status <> 'gone'`, no-transcript predicate), its columns, and the
  repository-imposed `attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`; the
  backlog-rotation rule the order exists for; the two selection sources with different row
  shapes; `work_id` view-only.
- **Normalization contracts** — `MAX_TIMELINE_MS = 10**12` and the unbounded-DTO choice, the
  repository-boundary trimming site (stored text is hashed text → whitespace-insensitive
  identity; interior control characters verbatim), positional ordinals, `end_ms > start_ms >= 0`
  re-validation, verbatim upstream order/overlaps, caller-supplied clocks, and the
  `storage` ↛ `sources` layering rule.
- **Known limits (as shipped)** — any `transcripts` row counts as "has a caption" (the ASR
  iteration must choose its own predicate); the write path checks the run exists but not its
  `kind`; pending queries are O(attempts); one immutability mechanism is inspection-only; the
  audio/ASR tables stay reservations.

### 1.2 NEW `{KNOWLEDGE_DIR}/architecture-patterns/subtitle-acquisition-contract.md`

Path: `.mstar/knowledge/architecture-patterns/subtitle-acquisition-contract.md`
(frontmatter: `module: bili-asr subtitle gateway`, `date: 2026-09-11`,
`problem_type: architecture_pattern`, `category: architecture-patterns`, `severity: medium`,
`plan_id: 20260911-subtitle-gateway`, five `applies_when` triggers, six tags). Knowledge track.

Captures the acquisition contract as verified against the installed pin
(`bilibili-api-python==17.4.2`), leading with the facts that cost the most to learn:

- **The player endpoint** — `video.API["info"]["get_player_info"]` →
  `https://api.bilibili.com/x/player/wbi/v2`, the declared field table, the `data`-vs-`params`
  difference from the user-video page endpoint, and why the adapter sends `bvid` instead of the
  package's aid-resolving helper.
- **Pin-verified negatives** — `need_login_subtitle` exists nowhere in the installed package
  (the legacy `probe_subs` docstring is explicitly marked as non-evidence); `w_webid` is
  declared and live-required only for the *user-video page* endpoint.
- **Why each override exists** — `dm=False` (fabricated device fingerprints; the sibling WBI
  endpoint answered HTTP 412 with them), `verify=False` (in the pin, `verify=True` only raises
  locally on missing SESSDATA — it is not an upstream check), the exact declared parameter set
  with `bvid`, and retries belonging to the package's bounded `-403` re-sign.
- **The body fetch** — `Api(...)` with an explicitly empty `Credential()` (SESSDATA stays off
  the CDN host) called as `request(raw=True)`; `raw`/`byte` are `Api.request` parameters, not
  constructor fields, and `raw=True` is required because a subtitle document has no
  `data`/`result` envelope; HTTP 404 on the signed URL is `not_found`, not transport.
- **URL normalization** — exactly three accepted forms (`//host/…` and `http://…` rewritten to
  `https://`, `https://` passed through, everything else refused with `shape_error` *before* any
  request).
- **The raise-versus-drop boundary** — a condition table separating entries that cannot be read
  as a segment (document-level `shape_error`) from readable entries that carry nothing usable
  (dropped per row), `body` absent/`null`/non-array as `shape_error`, and empty/all-dropped
  bodies as `not_found`; `floor(seconds*1000)`; verbatim order and overlaps; the `-zh` primary
  subtag rejection; interior control characters kept in caption text but rejected in
  operator-facing labels.
- **No-usable-track signalling** — empty tuple from the listing vs `GatewayNotFound` from the
  fetch, with the "never" column, and credential presence as the anonymous-vs-authenticated
  distinction.
- **The bounded single re-list** — re-list-and-match by `language` + `is_ai` (`track_id`
  tie-break, ambiguity `shape_error`, absence `not_found`), at most one extra listing + fetch
  pair on expiry/transport only, **never** on `rate_limited`, worst case 2 + 2; and the plainly
  stated cost of the happy path (two listings per part, the price of keeping the URL out of
  every DTO).
- **Failure vocabulary** — the taxonomy table, and the deliberate `-101` divergence from the
  metadata path (there `response_error`, here `not_found`), pinned in both directions.
- **Track preference** — the `language_family()` derivation, the default family ranking with CC
  before AI inside a family, exact `--language` matching, and *why the rule is family-blind*
  (any Chinese CC code beats any Chinese AI code in either upstream order; no code list, no
  translation table), plus the explicit note that the legacy AI-first order is not reused.
- **Secret boundary**, **known limits** (legacy client still has subtitle methods; whole-`user`
  module import still bound; the live probe ran against a fixed public sample; an inventory is
  not a promise).

### 1.3 UPDATE `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md` (in place)

Updated in place — no third CLI doc. `last_updated` bumped `2026-08-30` → `2026-09-11`; all
pre-existing content kept.

- **New `### Subtitle acquisition commands (SQLite path)`** under Guidance, placed before
  `### Installed Python baseline`: the two commands and their bounds/selectors (including the
  unstorable/unknown-selector rule answered as exit-1 config from the argument alone), the full
  exit taxonomy (`0` bounded success/read incl. `attempted=0`, `1` usage/config incl. the schema
  guard, `2` all-parts-failed or unexpected internal error, usage errors never `2`), the run
  reporting contract (all four counts including zeros, run id, credential presence, remaining
  parts), the **composed schema-rebuild line** (in a fenced block, with the reason the CLI
  composes prefix + root and the zero-byte asymmetry), the **damaged-database bounded line**
  (`<command>: unreadable archive database at {archive_root} (<ErrorType>)`, `(OSError,
  sqlite3.Error)` only, first read inside the handler), the **loud credential rule** for an
  opted-in live run with no resolvable credential, the **read-only `mode=ro` probe connection**
  (and why it cannot be the schema-initializing `open_database`), the **writer-lock ordering**
  (lock taken in the entrypoint before the database check, so a failed harvest still creates
  `{archive_root}/coordinator/`; `harvest-subs: archive_busy`), the **no-sidecar/no-projection
  and `needs_audio`-gone boundary** with the ASR/pilot manifest boundary and the deferred
  projection/audio-queue owners, and the **live-smoke command shape** (fenced, with the
  skip-vs-loud-fail code classes).
- **Two legacy claims qualified, not deleted**: the manifest state-machine sentence now states
  that it is the legacy archival flow's state machine and that the subtitle path was **cut over
  at `iter-2026-09-subtitle-transcript-sqlite`** (the one-line cutover note); the transient-audio
  policy paragraph now states that the SQLite subtitle path produces no `needs_audio` rows.
- **Evidence bullet added**: the cutover revision `d1a0b7e`, the suite at cutover (1314 passed,
  4 skipped — the opt-in live gates), the recorded bounded live smoke, and links to both new docs.

### 1.4 Index

- `.mstar/knowledge/README.md` — the intro sentence now records this iteration's close, and the
  table gained **one row per new doc** (Document / Source Plan / Description / Status, both
  `Active`, source plans `20260911-transcript-storage` and `20260911-subtitle-gateway` with the
  iteration id). The existing CLI row's Source Plan and Description were extended with the
  subtitle-path refresh (no row added, no doc duplicated).

## 2. Trace lines added (`Promoted to:`)

| Source file | Line added (first line of the file's existing status blockquote) |
|---|---|
| `{ITERATION_DIR}/iter-2026-09-subtitle-transcript-sqlite/specs/transcript-storage.md` | `> Promoted to: `.mstar/knowledge/architecture-patterns/normalized-transcript-storage.md` (2026-09-11)` |
| `…/specs/subtitle-gateway.md` | `> Promoted to: `.mstar/knowledge/architecture-patterns/subtitle-acquisition-contract.md` (2026-09-11)` |
| `…/specs/subtitle-cli-contract.md` | `> Promoted to: `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md` (2026-09-11; refreshed the existing CLI pattern's subtitle path)` |

Form and placement mirror the precedent in
`{ITERATION_DIR}/iter-2026-08-persistence-scale-safety/specs/*.md`. Nothing else in those three
specs was touched (`git diff` shows only the inserted line in each).

## 3. CONCEPTS.md proposals (NOT written — PM decides)

Every candidate was checked against the existing `CONCEPTS.md` (7 entries: `work_id`,
`meta-cursor.json`, risk stop, evidence projection, audit-only recovery, `sequential-no-daemon`,
run-scoped ASR) — none overlap.

| Term | One-line meaning | Why project-specific |
|---|---|---|
| **acquisition attempt** | One append-only evidence row per attempted part inside one acquisition run: outcome (`stored` / `unchanged` / `no-subtitle` / `failed`), optional bounded error code, and the transcript version it produced; never a per-part status. | The whole honesty rule of this archive rests on it — an attempt is evidence scoped to a run, so a captionless part stays re-attemptable instead of becoming a terminal "unavailable" state, and the outcome↔code↔transcript combinations are a database CHECK matrix, not a convention. |
| **`no-subtitle`** | The attempt outcome meaning "no usable caption track was visible for this part with the credentials in effect at this attempt" — not a failure, not a success, and not a statement that the video has no captions. | The token is a stored enum value whose reading is deliberately narrower than its everyday meaning (credential-, time-, and upstream-dependent), it never counts as `failed`, and a part carrying it stays in the pending work queue. |
| **subtitle track** (with `label` and the `ai`/`cc` marker) | One inventory entry a part exposes at one moment: normalized upstream `lan`, printable `lan_doc` label, and an AI-vs-CC classification where a missing upstream marker reads as CC. | "Track" here is a caption-track inventory row with a conservative classification rule and a printed label — not an audio track or a media stream; an empty inventory is a legitimate result, and the label is the only upstream metadata value the CLI prints. |
| **transcript version** | An immutable revision of one `(part, source kind, language)` caption: appended when the content differs from every stored version, never rewritten or deleted, all earlier versions permanently readable. | The append trigger is a content hash and the identity key is `(part, source kind, language)`, so a "version" is neither a run id nor a monotonic attempt counter — the shipped read/attempt disagreement after a content revert belongs to this term's meaning. |
| **content identity** (`content_sha256`) | The SHA-256 over the canonical JSON of the millisecond segment triples, which decides "the archive already holds this caption text" independently of the part/source/language slot. | Both halves are project decisions: what is hashed (ms + trimmed text only; the identity key excluded) and how it is enforced (a partial unique index scoped to the caption kinds, deliberately not covering `asr-local`). |
| *(secondary)* **caption source kind** (`subtitle-ai` / `subtitle-cc` / `asr-local`) | Closed vocabulary naming where a transcript row came from; `asr-local` is reserved and currently unwritten. | It is a stored enum that decides identity, uniqueness, and the pending-queue predicate — not a free-form provenance string. Could be folded into the `subtitle track` row instead if the PM prefers fewer entries. |

Not proposed: `probe-subs` / `harvest-subs` (ordinary command names documented in the CLI
pattern), `v_pending_subtitles` (an implementation object whose meaning is fully carried by the
two rows above), `MAX_TIMELINE_MS` (a bound, not a domain noun).

## 4. Deliberately left out (with reasons)

1. **A reciprocal "See also" line inside `normalized-metadata-stack.md`.** The brief asked for
   cross-links "in both directions", but the hard rules forbid editing the other knowledge docs,
   so the two new docs (and the CLI doc) link *to* it and it was not modified. If the PM wants
   the back-link, one line under its `## Supersedes (metadata path only)` section does it:
   `Transcript storage and the caption acquisition boundary are documented in
   [normalized-transcript-storage.md](normalized-transcript-storage.md) and
   [subtitle-acquisition-contract.md](subtitle-acquisition-contract.md).`
2. **The iteration package `README.md` promotion table.** The writable set was knowledge docs,
   the knowledge index, the spec trace lines, and this report, so the package-level
   `Source | Promoted to | Date | Notes` table used by earlier iterations was left to the PM.
3. **`CONCEPTS.md` itself** — proposals only, as instructed.
4. **The compass `## Compound Round Summary` / `## Quality Gate Summary`** — PM-owned artifacts,
   outside the writable set.
5. **Per-plan QC/QA finding ids, seat numbers, and review choreography.** Durable docs state the
   shipped contract and its reasons; the findings stay in
   `.mstar/sdd/<plan-id>/review/` (their sanctioned genre). Where a fix changed the shipped shape
   (the bounded damaged-database line), the *behaviour* is documented and the incident narrative
   is not.
6. **A bug-track doc for the damaged-database traceback escape.** It was a defect fixed inside
   the iteration, and its durable value — the first read belongs inside the bounded handler
   because a damaged file fails on statement one, not on connect — is captured as guidance in the
   CLI doc. A separate incident log would duplicate it.
7. **A separate doc for the language-family preference mechanism.** It is a mechanism of the
   acquisition service, so it lives inside `subtitle-acquisition-contract.md`; a third doc would
   have been a duplicate of one section (Q5 high-overlap rule).
8. **New frontmatter keys (`source`, `supersedes`) and new tags on the CLI doc.** No sibling uses
   the keys; the CLI doc's `tags` list already sits at the schema's maximum of 8.
9. **A `{SPECS_DIR}` frozen copy.** The specs' own promotion sections and the compass leave the
   `{SPECS_DIR}`-vs-`{KNOWLEDGE_DIR}` decision to iteration-close; this round wrote knowledge
   only, as scoped.
10. **Reference-heuristic cleanup beyond the fixable cases.** See §6: the remaining
    `compound.reference.*` findings are the validator's heuristic expecting `.ts` modules in a
    Python repository, plus two pin-internal paths; making them disappear would mean deleting
    true statements.

## 5. Validation performed

- **Frontmatter**: `mstar compound validate --knowledge-dir …` was run for all three docs.
  Isolated frontmatter validation (`validateSchemaYaml` via the installed harness bundle) returns
  `ok=true` for each — required fields present, `problem_type`/`severity`/`category` consistent
  with `category-mapping` rule 1, `date` and `last_updated` as `YYYY-MM-DD`, `applies_when` a
  list. The CLI tool's overall `FAIL` verdict is produced by the **reference heuristic** below,
  not by the schema contract (the pre-existing CLI doc fails identically before and after this
  round's edit).
- **Index rows**: both new docs carry a README row; the CLI row was refreshed in place.
- **Reference heuristic (informational)**: CLI doc 4 findings — identical set to its committed
  version, so this round added none; storage doc 1 (`acquisition_runs.credential_present`, a
  symbol-ref heuristic); acquisition doc 6 (symbol refs such as `subtitles.json_to_srt`,
  `user.get_api`; plus `video.py`, a path inside the installed distribution). Repo paths the
  heuristic *can* resolve were rewritten to full repo-relative form
  (`bilibili-asr-archive/src/…`), and the schema-rebuild/damaged-database/live-smoke lines were
  moved into fenced blocks so quoted operator output is not mistaken for a path.
- **Fact-checking**: every DDL statement, CHECK matrix, guard object, ordering key, code path,
  exit line, and pin fact in the three docs was read back from the shipped source
  (`storage/schema-transcripts.sql`, `storage/database.py`, `storage/models.py`,
  `sources/bilibili_api_gateway.py`, `sources/models.py`, `cli.py`, `services/subtitle_ingest.py`,
  the two opt-in live smoke tests) or from the operator docs, not from the plans' prose alone.
- **Scope**: `git status` shows only the intended files — three specs (one trace line each), the
  knowledge README, the CLI knowledge doc, the two new knowledge docs, and this report. No
  product code, plan, compass, snapshot, `status.json`, or other knowledge doc was modified.

## 6. Refresh trigger (Phase 7) — one concrete recommendation

`normalized-metadata-stack.md` `## Supersedes (metadata path only)` still says the JSONL sidecars
"remain the archival-flow state machine for subtitle/audio/ASR processing". After this
iteration's cutover the **subtitle** half of that sentence is stale: the sidecars remain only for
the ASR/pilot/audio flow. Recommend:

```
Consider: /pm compound-refresh .mstar/knowledge/architecture-patterns/normalized-metadata-stack.md
```

No other staleness was found: `operational-sidecars.md` describes the legacy archival flow, which
is still shipped and still manifest-driven, and `run-scoped-asr-provenance.md` is untouched by
this iteration's scope.
