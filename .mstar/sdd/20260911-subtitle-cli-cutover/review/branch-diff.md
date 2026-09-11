# Branch Review Package — 20260911-subtitle-cli-cutover

Plan: `20260911-subtitle-cli-cutover` (iteration `iter-2026-09-subtitle-transcript-sqlite`)
Range: `c5a9b82..8373817`
Base: `c5a9b82` (integration branch at feature-branch cut)
Head: `8373817`
Working branch: `feature/20260911-subtitle-cli-cutover`
Commits: 8ec992b (service + CLI cutover), c501d9a (offline E2E + F3 + M3), d5c0f9e (live smoke), 8373817 (docs)

```diff
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index 0f41c13..1593524 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -100,7 +100,8 @@ in committed files or CI artifacts.
 ## Workflow
 
     bili-asr fetch-meta --mid 23191782 --archive-root archive
-    bili-asr harvest-subs --archive-root archive
+    bili-asr probe-subs --limit-parts 5 --archive-root archive
+    bili-asr harvest-subs --limit-parts 5 --archive-root archive
     bili-asr download-audio --missing-subs --archive-root archive
     bili-asr asr --pending --archive-root archive
     bili-asr status --archive-root archive
@@ -185,12 +186,13 @@ Paths, exception text, and input values are never emitted.
 ### Archive writer isolation
 
 Every archive-mutating command (`fetch-meta`, `recover`, `asr`, `pilot`,
-`probe-subs`, `harvest-subs`, `download-audio`, `run`, `campaign`, and
+`harvest-subs`, `download-audio`, `run`, `campaign`, and
 `schedule`) holds one archive-root writer lock from initial state load through
 its final state/sidecar write. A second mutation exits `1` with
 `<command>: archive_busy`; it does not wait or partially mutate the archive.
 Read-only commands such as `status`, `coverage`, `verify`, `runs`, `search`,
-`export`, and `evaluate-concurrency` do not claim this writer lock.
+`export`, `probe-subs`, and `evaluate-concurrency` do not claim this writer
+lock: `probe-subs` writes nothing at all on the SQLite subtitle path.
 
 ### Audio reclaim and bounded-disk campaigns
 
@@ -256,11 +258,11 @@ the row archived.
 ### Operational run ledger (`run-ledger.jsonl`)
 
 Every `pilot` / `run` / `schedule` run atomically appends an inspectable run
-record to `{archive-root}/run-ledger.jsonl`. The metadata CLI's `fetch-meta`
-records its runs in the fresh SQLite database
+record to `{archive-root}/run-ledger.jsonl`. The metadata and subtitle CLI
+commands record their runs in the fresh SQLite database instead
 (`{archive-root}/archive.db`, see
-[the fresh-start metadata workflow](#fresh-start-metadata-collection-fetch-meta--status--runs))
-instead. The ledger is a sidecar file that records execution history and
+[the fresh-start SQLite archive](#fresh-start-sqlite-archive-fetch-meta--status--runs)).
+The ledger is a sidecar file that records execution history and
 coverage without altering manifest row schemas or the transport layer.
 
 #### Ledger record schema
@@ -343,6 +345,13 @@ FunASR-Nano), `archive` (write `srt`/`txt`/`md`) — composing the same live
 seams as the single-purpose commands. It **complements** the frozen
 `bili-asr pilot` MVP-proof command; it does not replace it.
 
+This chain is driven from the manifest state only: `run`, `pilot`, `asr`, and
+`schedule` never read `archive.db`, so transcripts stored by the SQLite
+`harvest-subs` do not feed them (and `harvest-subs` no longer marks rows
+`needs_audio`). See
+[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)
+for that boundary.
+
     bili-asr run --scope pending|failed|<work_id>... [--offline] [--limit N] [--archive-root <root>]
 
 - **Scope**: `pending` selects all non-terminal processable rows; `failed`
@@ -488,7 +497,7 @@ The JSONL manifest (`{archive-root}/manifest/manifest.jsonl`) remains the single
 - **Vocabulary**: Consistently uses manifest `status` (never cursor `state`).
 - **Decoupled from search index**: Export operates directly over the JSONL manifest SSOT and does not require, query, or mutate `search.db`.
 
-### Fresh-start metadata collection (`fetch-meta` / `status` / `runs`)
+### Fresh-start SQLite archive (`fetch-meta` / `status` / `runs`)
 
 `bili-asr fetch-meta` collects video metadata through the pinned
 `bilibili-api-python==17.4.2` gateway and writes it to a fresh normalized
@@ -504,6 +513,10 @@ only restart path.
     bili-asr status --archive-root archive
     bili-asr runs --limit 10 --archive-root archive
 
+The subtitle commands work on that same fresh database and are described in
+[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)
+below; this subsection covers the metadata and read commands only.
+
 - **Default page bound**: `--limit-pages` is optional and defaults to
   `DEFAULT_PAGE_LIMIT = 10`. The canonical command above therefore stops
   after 10 pages (the ingestor's page size is 30 — the upstream-accepted
@@ -561,10 +574,94 @@ Exit 2 variants:
   check `status` / `runs` before re-running. Re-running is safe: it
   resumes from the stored cursor.
 
-#### Opt-in bounded live smoke
+#### Subtitle acquisition on SQLite (`probe-subs` / `harvest-subs`)
+
+`bili-asr harvest-subs` acquires captions for parts already stored in
+`archive.db` and keeps the normalized transcript **in that database**: no
+`subtitles/raw/*.json` and no `transcripts/srt/*.srt` is written, and no JSONL
+sidecar is read or written. `bili-asr probe-subs` lists the tracks the selected
+parts expose and writes nothing at all — no database creation, no run or attempt
+row, no lock file. The full contract, with the printed line shapes and the
+observed live run, is in
+[docs/metadata-storage.md](docs/metadata-storage.md).
 
-Three tests share the one switch (`BILI_LIVE_SMOKE=1`); every default pytest
-run skips all three and makes no network call:
+    bili-asr probe-subs --limit-parts 5 --archive-root archive
+    bili-asr probe-subs --bvid <bvid>:p0 --archive-root archive
+    bili-asr harvest-subs --limit-parts 5 --archive-root archive
+    bili-asr harvest-subs --bvid <bvid>:p0 --archive-root archive
+    bili-asr harvest-subs --limit-parts 5 --language ai-zh --archive-root archive
+
+- **Bounds**: no unbounded runs. `harvest-subs` requires `--limit-parts N`
+  whenever the selection is not a single `bvid:pN` part; `probe-subs` requires
+  exactly one of `--bvid` / `--limit-parts`. `--bvid BVID` selects every part of
+  that video already in the database — for `harvest-subs` that includes parts
+  that already have a transcript, which is how a video is re-checked after
+  upstream revises a caption. Neither command fetches a pagelist, and neither
+  calls upstream for a part that is not in the database.
+- **Exit codes**: `0` the bounded run completed — including a probe whose parts
+  exposed no track, and a selection that resolved to no part (`attempted=0`);
+  `1` usage/configuration (missing database, unknown `--bvid`, missing or
+  non-positive bound, neither/both `probe-subs` selectors, empty `--language`
+  entry, or the schema guard below); `2` every attempted part failed, or an
+  unexpected internal error (`<command>: unexpected error`, no traceback).
+  Partial failure stays visible in the printed counts, not in the exit code.
+- **Output shapes**: `probe-subs` prints `sessdata: present|absent`, then one
+  line per selected part — `probe <work_id> tracks=<n>` with one
+  `track <lan> <ai|cc> <label>` line each, `probe <work_id> tracks=0` with an
+  explicit `(no subtitles visible)` marker, or `probe <work_id> failed <code>` —
+  and closes with
+  `probe-subs: probed=<n> with_tracks=<n> without_tracks=<n> failed=<n>`.
+  `harvest-subs` prints one line per attempted part —
+  `harvest <work_id> stored|unchanged <source_kind> <language> v<version>`,
+  `harvest <work_id> no-subtitle`, or `harvest <work_id> failed <error_code>` —
+  and closes with `harvest-subs: run_id=<id> attempted=<n> stored=<n>
+  unchanged=<n> no-subtitle=<n> failed=<n>
+  remaining_without_transcript=<n>`, carrying all four counts including the
+  zeros. Nothing here is a claim about corpus or caption coverage.
+- **Preference rule**: the default keeps the **uploader** caption
+  (`subtitle-cc`) over the machine one (`subtitle-ai`) inside the same language
+  **family**, with families ranked `zh`, then `en`, then the rest in upstream
+  order. The family is derived from the `language` + `is_ai` facts the gateway
+  already guarantees (strip an `ai-` prefix from a machine code, then take the
+  primary subtag), so `zh-CN` / `zh-Hans` / `zh-Hant` / `ai-zh` all rank as
+  `zh`: upstream uses different exact codes per caption kind, and a fixed code
+  list would silently mis-rank codes upstream adds while a machine↔uploader
+  equivalence table would need maintaining. `--language PREF[,PREF...]` matches
+  a preference **exactly** against the code `probe-subs` prints, so
+  `--language ai-zh` keeps the machine caption reachable. This replaces the
+  legacy manifest harvest's AI-first order.
+- **Credential**: `--sessdata` or `BILI_SESSDATA` (flag wins), with the same
+  resolution and presence-only redaction as the metadata commands
+  (`sessdata: present|absent`); the value reaches the gateway's cookie only and
+  is never echoed, logged, or persisted. `harvest-subs` records the presence in
+  its run row, so a part it recorded `no-subtitle` stays interpretable — an
+  invisible caption may exist and simply be login-gated.
+- **Schema guard and rebuild**: on a database that predates the transcript
+  schema both commands print `<command>: archive database predates the
+  transcript schema; rebuild it (delete <archive-root>/archive.db and re-run
+  fetch-meta)` and exit `1`, while `fetch-meta` / `status` / `runs` keep working
+  on it. There is no in-place migration: deleting `archive.db` and re-running
+  `fetch-meta` is the rebuild. The database is created from two checked-in
+  resources, `src/bili_asr/storage/schema.sql` and
+  `src/bili_asr/storage/schema-transcripts.sql`.
+- **Legacy manifest boundary**: the ASR/pilot chain is untouched and still reads
+  `manifest/manifest.jsonl`, so `asr --pending`, `pilot`, `run`, `schedule`, and
+  `campaign` do not see transcripts stored here. In particular the new
+  `harvest-subs` no longer produces the manifest status `needs_audio`, so
+  `download-audio --missing-subs` gains no new entries from the SQLite subtitle
+  path — the two paths do not feed each other yet. Rebuilding the SRT/TXT/MD
+  projections from the stored transcripts is deferred work for a later
+  iteration.
+- **Writer lock**: `harvest-subs` is an archive-writer command and holds
+  `{archive-root}/coordinator/archive-writer.lock` for the whole run, so a
+  second mutating command exits `1` with `harvest-subs: archive_busy`. Apart
+  from `archive.db`, that lock is the only file a bounded harvest leaves behind;
+  `probe-subs` deliberately takes none.
+
+#### Opt-in bounded live smokes
+
+Four tests share the one switch (`BILI_LIVE_SMOKE=1`); every default pytest
+run skips all four and makes no network call:
 
 - `tests/test_live_metadata_smoke.py` — the real CLI against the real upstream:
   exactly one public metadata page for UID 23191782, into a temporary archive
@@ -578,6 +675,21 @@ run skips all three and makes no network call:
   and credential presence — never a URL, body, label, or credential. Run it
   from the package directory with the pinned distribution installed:
   `BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_subtitle_smoke.py -s -v`;
+- `tests/test_live_subtitle_cli_smoke.py` — the real **CLI + storage** chain
+  against the real upstream: one part through `probe-subs` and `harvest-subs`
+  in a temporary archive root, asserting the printed line shapes, the stored
+  transcript rows, and the archive root's file set. The part both commands
+  address is authored into that temporary root — the fixed public sample
+  `BV1S8hA6MEvy:p0`, recorded as `part_source=fixed-sample` — because the
+  commands only ever address parts the database already stores. Zero visible
+  tracks, a `not_found` listing, and a `rate_limited` refusal are recorded as
+  bounded evidence and skipped rather than reading green; every other bounded
+  code fails loudly. Its one count-only evidence line names the seeded part,
+  credential presence, both commands' counts, and the stored source
+  kind/language/version. Run it from the package directory of the checkout
+  under test (the package's `tests/conftest.py` puts that checkout's `src/`
+  first on `sys.path`, ahead of the control `.venv`'s editable install):
+  `BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_subtitle_cli_smoke.py -s -v`;
 - `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner`
   — the adapter-level ancestor of the CLI smoke: one real metadata page for UID
   23191782 ingested into a temporary database through the real gateway.
@@ -625,11 +737,13 @@ underlying transport/proxy requirements are documented in
 
 ### Mixed batch outcomes
 
-When `harvest-subs`, `download-audio`, `asr`, `pilot`, `run`, or `schedule`
-processes more than one work item, the process exit code is an aggregation of
-per-item outcomes — not a claim that the whole corpus is complete. `pilot`
-remains the frozen two-branch proof command; `run` remains complementary;
-`schedule` consumes this same taxonomy.
+On the legacy manifest path, when `download-audio`, `asr`, `pilot`, `run`, or
+`schedule` processes more than one work item, the process exit code is an
+aggregation of per-item outcomes — not a claim that the whole corpus is
+complete. `pilot` remains the frozen two-branch proof command; `run` remains
+complementary; `schedule` consumes this same taxonomy. The SQLite
+`harvest-subs` follows its own bounded taxonomy instead (see
+[Subtitle acquisition on SQLite](#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs)).
 
 | Exit | Meaning |
 |------|---------|
diff --git a/bilibili-asr-archive/docs/metadata-storage.md b/bilibili-asr-archive/docs/metadata-storage.md
index 376fa12..18c7140 100644
--- a/bilibili-asr-archive/docs/metadata-storage.md
+++ b/bilibili-asr-archive/docs/metadata-storage.md
@@ -1,19 +1,26 @@
-# Metadata storage (`archive.db`)
+# Metadata and subtitle storage (`archive.db`)
 
 Normalized SQLite storage for the video metadata collected by
-`bili-asr fetch-meta`. This document describes the database the metadata CLI
-creates and reads. The legacy JSONL manifest pipeline
+`bili-asr fetch-meta` and for the subtitles acquired by `bili-asr harvest-subs`.
+This document describes the database the metadata and subtitle CLI commands
+create, read, and write. The legacy JSONL manifest pipeline
 (`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) is a
-separate, untouched state: the metadata commands never read it, and no
-command migrates old data into the new database.
+separate, untouched state: none of these commands read it, and no command
+migrates old data into the new database.
 
 ## Fresh-start behavior (no migration)
 
 - `fetch-meta` creates `{archive_root}/archive.db` when it does not exist and
-  initializes the checked-in schema (`src/bili_asr/storage/schema.sql`).
-  Opening the database — for a write or a read command — always runs that
-  schema script, which is an idempotent no-op on a current-version database;
-  no schema upgrade happens in this iteration.
+  initializes the two checked-in schema resources: `src/bili_asr/storage/schema.sql`
+  (users, videos, parts, ingestion runs/pages/cursors/discoveries) and
+  `src/bili_asr/storage/schema-transcripts.sql` (acquisition runs and attempts,
+  transcripts, transcript segments, and their views). Opening the database — for
+  a write or a read command — always runs both scripts, which are idempotent
+  no-ops on a current-version database; no schema upgrade happens in this
+  iteration. A database created before the transcript contract keeps the shape
+  it has: the transcript script is skipped for it, so nothing half-applies, the
+  metadata path keeps working, and the subtitle commands report the schema guard
+  below instead.
 - `status` and `runs` are read-only. When the database is missing they fail
   with a clear configuration error and exit `1`; they never create it.
 - There is no migration, import, reset, or rewrite path. Deleting
@@ -48,12 +55,18 @@ One SQLite file at `{archive_root}/archive.db`. Foreign keys are enforced
 | `ingestion_cursors` | `mid` | The resumable one-based cursor: `next_page`, `state` (`ready`, `complete`, `limited`, `risk_interrupted`), `observed_total`. |
 | `ingestion_discoveries` | `(run_id, page_number, bvid)` | Run-scoped discovery evidence linking a run page to a discovered video. |
 
-### Reserved media boundary (empty in this plan)
+### Media and transcript tables
 
-`audio_objects`, `part_audio_objects`, `asr_models`, `transcripts`, and
-`transcript_segments` are created now so later media and transcript plans
-attach through these foreign keys instead of reintroducing sidecars. They
-stay empty in this plan; no media bytes or transcripts are written yet.
+`transcripts` and `transcript_segments` back the subtitle path: `harvest-subs`
+writes one row per acquired caption plus its ordered segments, and
+`probe-subs` reads them only through the views below. They are the only tables
+this iteration fills on the media side.
+
+`audio_objects`, `part_audio_objects`, and `asr_models` are still empty: no
+audio bytes and no ASR model rows are written by any command here. The legacy
+audio/ASR chain (`download-audio`, `asr`, `pilot`, `run`) still records its work
+in the JSONL manifest, not in these tables, so nothing on this path fills them
+yet.
 
 ### Views
 
@@ -62,15 +75,208 @@ stay empty in this plan; no media bytes or transcripts are written yet.
 | `v_video_parts` | Every part with its derived `work_id` and the joined user/video context. |
 | `v_ingestion_run_stats` | Per-run page and video counts (the `runs` command's source). |
 | `v_pending_metadata` | Parts with `processing_status = 'discovered'` (the `status` command's pending work). |
+| `v_pending_subtitles` | Every part that is not `gone` and has no stored transcript, ordered never-attempted first — the subtitle commands' work list, carrying the newest attempt's outcome, timestamp, and credential presence. |
+
+## Subtitle acquisition (`probe-subs` / `harvest-subs`)
+
+Both commands read the parts already stored in `archive.db`, acquire through the
+typed gateway, and write their result back there — `archive.db` is the only
+destination. The `cid` always comes from `video_parts`: the subtitle path never
+fetches a pagelist and never calls upstream for a part that is not in the
+database.
+
+```text
+bili-asr probe-subs  [--archive-root PATH] (--bvid BVID|BVID:pN | --limit-parts N) [--sessdata VALUE]
+bili-asr harvest-subs [--archive-root PATH] [--bvid BVID|BVID:pN] [--limit-parts N]
+                      [--language PREF[,PREF...]] [--sessdata VALUE]
+```
+
+- `--archive-root PATH` (default `archive`): the root holding `archive.db`.
+- `--bvid BVID` selects **every part of that video already in the database** —
+  for `harvest-subs` that includes parts that already have a transcript, which
+  is the explicit path for re-checking a video after upstream adds or revises a
+  caption. `--bvid BVID:pN` selects exactly one part, in the archive's own
+  zero-based part vocabulary. A selector that resolves to no stored part is a
+  configuration error — exit `1`, `unknown --bvid <value>` — never an empty
+  result.
+- `--limit-parts N` (positive integer) bounds the run. `probe-subs` requires
+  exactly one of `--bvid` / `--limit-parts`; `harvest-subs` requires the bound
+  whenever the selection is not a single `bvid:pN` part, which is bounded by
+  construction. No unbounded runs.
+- `--language PREF[,PREF...]` (`harvest-subs` only) overrides the preference
+  rule below; an empty entry is a usage error (exit `1`).
+
+### Output
+
+`probe-subs` prints presence, one line per selected part in selection order,
+then a count summary:
+
+```text
+sessdata: <present|absent>
+probe <work_id> tracks=<n>
+  track <lan> <ai|cc> <lan_doc>
+probe <work_id> tracks=0
+  (no subtitles visible)
+probe <work_id> failed <error_code>
+probe-subs: probed=<n> with_tracks=<n> without_tracks=<n> failed=<n>
+```
+
+A part with no visible track is never omitted: it carries the explicit
+`(no subtitles visible)` marker, so "no tracks" cannot be read as "not
+attempted". A part whose listing failed carries the bounded code on its own
+line, with no track lines and no success marker.
+
+`harvest-subs` prints presence, one line per attempted part in attempt order,
+then one summary line that always carries all four outcome counts including the
+zeros, the run id, the credential presence, and how many parts still have no
+transcript:
+
+```text
+sessdata: <present|absent>
+harvest <work_id> stored <source_kind> <language> v<version>
+harvest <work_id> unchanged <source_kind> <language> v<version>
+harvest <work_id> no-subtitle
+harvest <work_id> failed <error_code>
+harvest-subs: run_id=<run_id> attempted=<n> stored=<n> unchanged=<n> no-subtitle=<n> failed=<n> remaining_without_transcript=<n>
+```
+
+`remaining_without_transcript` is read after the run, so the operator can see a
+bounded run make progress. Each attempted part maps to exactly one outcome:
+
+| Upstream result | Outcome | Operator reading |
+|---|---|---|
+| The listing carried no track, or the fetch answered `not_found` | `no-subtitle` | Nothing was visible for this part at this attempt. Not a failure, and not a statement that the video has no captions: a machine caption may not exist yet, uploader captions may never have been provided, and login-gated tracks are invisible anonymously. The part stays in the pending enumeration. |
+| Content identical to what is stored for this part/source/language | `unchanged` | The archive already held this caption; nothing was rewritten. |
+| New content, or content differing from every stored version | `stored` | A new version was written; earlier versions stay readable. |
+| `rate_limited`, `transport_error`, `response_error`, `shape_error` | `failed` + the bounded code | Retry later for the first two; the last two need investigation. |
+
+No output carries a credential, a signed URL, a raw body, or upstream message
+text, and no count here is presented as coverage of the corpus.
+
+### Exit codes
+
+| Exit | Meaning |
+|------|---------|
+| 0 | The run completed. That includes a probe whose parts exposed no track at all, a harvest whose every attempted part had nothing visible, and a harvest whose selection resolved to no part (`attempted=0`). |
+| 1 | Usage/configuration: a missing `archive.db`, an unknown `--bvid`, a missing or non-positive bound, neither or both `probe-subs` selectors, an empty `--language` entry, or the transcript-schema guard below. |
+| 2 | The run failed on **every** attempted part, or an unexpected internal error (the fixed line `<command>: unexpected error`, no traceback). |
+
+Partial failure stays visible in the counts and does not by itself decide the
+exit code: a harvest that stored one part and failed another exits `0` with
+`failed=1` on its summary line. In both exit-2 variants the run row is finished
+`failed` when one was opened, and the per-part evidence already written stays
+readable.
+
+**A `not_found` listing is read differently by the two commands, on purpose.**
+The same upstream answer reaches the operator as two different readings:
+
+- `probe-subs` obtained no listing at all, so it prints
+  `probe <work_id> failed not_found` and counts the part under `failed=`. If
+  every selected part failed that way, the probe exits `2`.
+- `harvest-subs` records the part as `no-subtitle` — nothing was visible for it
+  — and exits `0` with `stored=0 unchanged=0 no-subtitle=1 failed=0`.
+
+Neither reading is "this video has no captions", and a part recorded
+`no-subtitle` stays eligible for a later attempt.
+
+### Archive writer lock
+
+`harvest-subs` is an archive-writer command: it takes the shipped writer lock at
+`{archive-root}/coordinator/archive-writer.lock` for the whole run, so a second
+mutating command exits `1` with `harvest-subs: archive_busy` instead of
+partially mutating the archive. That lock file and the database itself are the
+only files a bounded harvest leaves under the archive root.
+
+`probe-subs` is deliberately **not** an archive-writer command: it takes no
+lock and creates no file under the archive root. Its read-only promise is
+structural rather than only documented — no database creation, no transcript
+row, no acquisition run or attempt row, no lock file — and it stays a reader
+while another process writes, exactly like `status` and `runs`.
+
+### Track selection preference
+
+`harvest-subs` stores exactly one track per part. The default (no `--language`)
+ranks the visible tracks by language **family** — `zh` first, then `en`, then
+every remaining family in upstream order — and prefers an uploader caption
+(`is_ai = false`, printed `cc`) over a machine one inside the same family; the
+first track after that ranking is fetched.
+
+The family is derived from the two normalized facts the gateway DTO already
+guarantees — `language` and `is_ai` — by stripping the `ai-` prefix from a
+machine track's code and then taking the lowercase primary subtag: `zh-CN`,
+`zh-Hans`, `zh-Hant`, and `ai-zh` all land in `zh`, so the uploader caption wins
+whichever exact code upstream uses. The rule is defined on the family because
+upstream codes differ between caption kinds for the same spoken language
+(uploader Chinese is `zh-CN` / `zh-Hans` / `zh-Hant`, machine Chinese is
+`ai-zh`): a fixed list of exact codes would silently mis-rank any code upstream
+adds, and a machine↔uploader equivalence table would have to be maintained
+against upstream vocabulary and could flip without warning.
+
+`--language PREF[,PREF...]` overrides the rule: each entry is matched exactly
+against the code `probe-subs` prints, the first preference with a match wins,
+and among tracks matching the same preference the uploader caption comes before
+the machine one (then upstream order). `--language ai-zh` therefore retrieves
+the machine caption. A valid preference that matches no visible track yields
+`no-subtitle` for that part — nothing usable *for the requested language* was
+visible — never `failed`.
+
+The stored kind, language, and version are reported per part, so a run always
+shows which caption it kept:
+
+| Stored `source_kind` | Meaning |
+|---|---|
+| `subtitle-cc` | The uploader's caption. |
+| `subtitle-ai` | Upstream's machine-generated caption. |
+
+This replaces the legacy manifest harvest's AI-first preference
+(`subtitles._LAN_PREFERENCE`, `("ai-zh", "zh-CN", "zh-Hans", "en")`): the
+default now keeps the uploader caption when both are visible, and `--language`
+keeps the machine one reachable.
+
+### Schema guard and rebuild
+
+Both commands require the transcript contract in the database they open. On a
+database that predates it — one whose `transcripts` table lacks `language` /
+`content_sha256` — they print the fixed line and exit `1`:
+
+```text
+<command>: archive database predates the transcript schema; rebuild it
+(delete <archive-root>/archive.db and re-run fetch-meta)
+```
+
+The metadata commands (`fetch-meta`, `status`, `runs`) keep working on that same
+database unchanged. There is no in-place migration: the rebuild procedure is to
+delete `archive.db`, re-run `fetch-meta` to recreate it from the checked-in
+schemas, and harvest again.
+
+### Boundary with the legacy manifest path
+
+This iteration replaces the manifest semantics of the two command names; it does
+not migrate the rest of the archive. The ASR and pilot chain (`asr`, `pilot`,
+`run`, `schedule`, `campaign`, `download-audio`) is untouched and still reads
+`manifest/manifest.jsonl`:
+
+- the new `harvest-subs` no longer produces the manifest status `needs_audio`,
+  so the legacy audio feeder `download-audio --missing-subs` gains no new
+  entries from the SQLite subtitle path;
+- `bili-asr asr --pending` and the pilot chain are still driven from the
+  manifest state, not from `archive.db`, so a transcript stored here does not
+  feed them;
+- the two paths do not feed each other yet. Rebuilding the SRT/TXT/MD
+  projections from the stored transcripts, and enumerating the audio work queue
+  from SQLite — including the parts recorded `no-subtitle`, which are that
+  queue — belong to the next iteration.
 
 ## No-JSONL contract
 
-`fetch-meta`, `status`, and `runs` never read or write `manifest.jsonl`,
-`meta-cursor.json`, or `run-ledger.jsonl`. All persisted run/page evidence
-is scalar: `error_code` values are bounded strings of at most 64 characters
-from a restricted character set. Credentials, signed URLs, raw response
-bodies, and raw exception text never enter CLI output, logs, or any
-persisted row.
+`fetch-meta`, `status`, `runs`, `probe-subs`, and `harvest-subs` never read or
+write `manifest.jsonl`, `meta-cursor.json`, or `run-ledger.jsonl`. All persisted
+run/page evidence is scalar: `error_code` values are bounded strings of at most
+64 characters from a restricted character set. Credentials, signed URLs, raw
+response bodies, and raw exception text never enter CLI output, logs, or any
+persisted row. Neither subtitle command writes an on-disk projection of the
+transcript: no `subtitles/raw/*.json` and no `transcripts/srt/*.srt` — the
+normalized transcript lives in `archive.db`.
 
 ## Credential boundary
 
@@ -80,7 +286,10 @@ gateway's cookie object only: never echoed, logged, persisted, or rendered —
 CLI output shows presence only (`sessdata: present|absent`). Omitting it
 means anonymous access, and so does passing `--sessdata ""` explicitly
 (which never falls through to `BILI_SESSDATA`); a blank environment value
-likewise means anonymous.
+likewise means anonymous. `harvest-subs` additionally records the presence in
+its `acquisition_runs` row, so a part it recorded `no-subtitle` stays
+interpretable afterwards: an invisible caption may exist and simply be
+login-gated. `probe-subs` records nothing at all and only prints the presence.
 
 ## Runtime HTTP backend
 
@@ -257,6 +466,58 @@ of an explicit `export` (the gateway reads the same environment).
   no credential, no proxy, and no collected metadata value is recorded here.
   The intermittency noted above still applies to a fresh run.
 
+### Subtitle CLI smoke (`tests/test_live_subtitle_cli_smoke.py`)
+
+The same switch gates a live smoke of the subtitle commands: one public part
+through `probe-subs` and `harvest-subs` into a temporary archive root. Both
+commands address parts already in the database, so the smoke authors the one
+part it probes — the fixed public sample `BV1S8hA6MEvy:p0` — into its own
+temporary root first, and records `part_source=fixed-sample` with the identity
+in its single count-only evidence line:
+
+```
+CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
+CHECKOUT=$CONTROL/bilibili-asr-archive         # or a feature worktree's package dir
+cd "$CHECKOUT"
+set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
+export BILI_HTTP_PROXY=http://127.0.0.1:7890
+BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
+  -m pytest tests/test_live_subtitle_cli_smoke.py -s -v
+```
+
+It runs from the package directory of the checkout under test because the
+control `.venv` carries an editable install of the control checkout: the
+package's own `tests/conftest.py` puts `src/` first on `sys.path`, so the code
+exercised is the checkout the test file belongs to.
+
+- Bound: one part, `--limit-parts 1` on both commands — one track listing for
+  the probe, one listing plus one document fetch for the harvest (when a track
+  is visible). The smoke adds no retry of its own; the shipped gateway is
+  fail-fast per call, so a throttled endpoint is answered by waiting and
+  re-running, never by bending the call shape.
+- Asserted when a caption is visible: the printed presence, track, outcome and
+  summary line shapes; the normalized transcript row (an allowed
+  `source_kind`, its language, version 1, the content hash), its ordered
+  segments, the one run row with the operator's selector and the credential
+  presence, the one attempt row pointing at the transcript, a part that left
+  `v_pending_subtitles`, and an archive root holding nothing but `archive.db`
+  and `coordinator/archive-writer.lock`.
+- Recorded without reading green: zero visible tracks, a `not_found` listing,
+  and a `rate_limited` refusal each assert their bounded shapes, print the
+  evidence, and skip — a run that stored no transcript is not a subtitle
+  acquisition. Every other bounded code (`transport_error` from a dead proxy,
+  `response_error`, `shape_error`) fails loudly.
+- **Observed on 2026-09-11** (this host, credential and proxy configured), CLI
+  exit 0, bounded facts only: `part_source=fixed-sample
+  work_id=BV1S8hA6MEvy:p0 sessdata=present probe_exit=0 probed=1 with_tracks=1
+  without_tracks=0 probe_failed=0 track_count=1 tracks=ai-zh:ai harvest_exit=0
+  attempted=1 stored=1 unchanged=0 no_subtitle=0 failed=0
+  remaining_without_transcript=0 source_kind=subtitle-ai language=ai-zh
+  version=1 segments=2913 transcripts=1 attempts=1 pending_after=0`. The part
+  exposed one machine caption, the harvest stored it as version 1, and the part
+  left the pending enumeration. Count-only: no credential, no proxy, no signed
+  URL, and no caption text is recorded here.
+
 ## Exit codes
 
 ### `fetch-meta`
@@ -290,3 +551,10 @@ Exit 2 variants:
 same-second runs tie-broken deterministically by `run_id` descending — and
 includes non-terminal `running` rows: a crash can leave a stale run behind,
 and hiding it would hide real state.
+
+### `probe-subs` / `harvest-subs`
+
+Defined in the "Subtitle acquisition" section above: `0` the bounded run
+completed (a probe with zero visible tracks and a selection that resolved to no
+part included), `1` usage/configuration or the transcript-schema guard, `2` every
+attempted part failed or an unexpected internal error.
diff --git a/bilibili-asr-archive/src/bili_asr/cli.py b/bilibili-asr-archive/src/bili_asr/cli.py
index e11885f..017a0a5 100644
--- a/bilibili-asr-archive/src/bili_asr/cli.py
+++ b/bilibili-asr-archive/src/bili_asr/cli.py
@@ -119,25 +119,43 @@ def build_parser() -> argparse.ArgumentParser:
     )
 
     probe = subparsers.add_parser(
-        "probe-subs", help="Probe the subtitle list for one video (no download)"
+        "probe-subs",
+        help="List the subtitle tracks the selected archive parts expose (read-only)",
+    )
+    probe.add_argument(
+        "--bvid", default=None,
+        help="Bvid, or bvid:pN for one part, already in the archive database",
+    )
+    probe.add_argument(
+        "--limit-parts", type=int, default=None,
+        help="Probe the first N parts of the pending enumeration",
     )
-    probe.add_argument("--bvid", required=True, help="Bvid to probe")
     probe.add_argument(
         "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
         help="Archive root directory (default: ./archive)",
     )
     probe.add_argument(
         "--sessdata", default=None,
-        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
+        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
     )
 
     harvest = subparsers.add_parser(
-        "harvest-subs", help="Probe + download subtitles for pending manifest videos"
+        "harvest-subs",
+        help="Acquire subtitles for the selected archive parts as transcripts",
     )
     harvest.add_argument(
         "--bvid", default=None,
-        help="Restrict to a bvid or work_id (bvid:pN); STOP if unresolved "
-             "or multi-part without an explicit page",
+        help="Bvid, or bvid:pN for one part, already in the archive database "
+             "(parts that already have a transcript included)",
+    )
+    harvest.add_argument(
+        "--limit-parts", type=int, default=None,
+        help="Bound the run to N parts (required unless a single bvid:pN is named)",
+    )
+    harvest.add_argument(
+        "--language", default=None,
+        help="Comma-separated upstream language codes, first match wins "
+             "(default: the zh family, then en, CC before AI)",
     )
     harvest.add_argument(
         "--archive-root", default=DEFAULT_ARCHIVE_ROOT,
@@ -145,11 +163,7 @@ def build_parser() -> argparse.ArgumentParser:
     )
     harvest.add_argument(
         "--sessdata", default=None,
-        help="SESSDATA cookie for Path B (or env BILI_SESSDATA); not stored",
-    )
-    harvest.add_argument(
-        "--limit", type=int, default=None,
-        help="Stop after N videos (smoke runs)",
+        help="SESSDATA cookie (or env BILI_SESSDATA); not stored",
     )
 
     dl = subparsers.add_parser(
@@ -485,17 +499,15 @@ def _metadata_database_path(archive_root: str) -> str:
     return os.path.join(archive_root, ARCHIVE_DATABASE_NAME)
 
 
-def _open_read_repository(
-    command: str, archive_root: str
-) -> "MetadataRepository | None":
+def _open_read_connection(command: str, archive_root: str):
     """Open the fresh database for a read command; None after printing why not.
 
-    Read commands never create the database: a missing file is the
-    documented configuration error (exit 1), and an unreadable file is
-    reported bounded without raw SQLite text.  The caller owns the open
-    connection and closes it when the command finishes.
+    Read commands never create the database: a missing file is the documented
+    configuration error (exit 1), and an unreadable file is reported bounded
+    without raw SQLite text.  The caller owns the returned connection and closes
+    it when the command finishes.
     """
-    from bili_asr.storage import MetadataRepository, open_database
+    from bili_asr.storage import open_database
 
     if not os.path.isfile(_metadata_database_path(archive_root)):
         print(
@@ -505,7 +517,7 @@ def _open_read_repository(
         )
         return None
     try:
-        connection = open_database(archive_root)
+        return open_database(archive_root)
     except (OSError, sqlite3.Error) as exc:
         print(
             f"{command}: unreadable archive database at {archive_root} "
@@ -513,9 +525,81 @@ def _open_read_repository(
             file=sys.stderr,
         )
         return None
+
+
+def _open_read_repository(
+    command: str, archive_root: str
+) -> "MetadataRepository | None":
+    """Open the fresh database for a read command and wrap it in the repository.
+
+    ``None`` means :func:`_open_read_connection` already reported the reason.
+    """
+    from bili_asr.storage import MetadataRepository
+
+    connection = _open_read_connection(command, archive_root)
+    if connection is None:
+        return None
     return MetadataRepository(connection)
 
 
+def _subtitle_schema_rebuild_line(command: str, archive_root: str) -> str:
+    """Compose the fixed rebuild line for a pre-iteration archive database.
+
+    ``SchemaContractError`` carries the reason and the procedure only — it holds
+    a connection, never an archive root — so the command prefix and the actual
+    database path are composed here, and the printed line carries both.
+    """
+    return (
+        f"{command}: archive database predates the transcript schema; "
+        f"rebuild it (delete {_metadata_database_path(archive_root)} "
+        "and re-run fetch-meta)"
+    )
+
+
+def _open_subtitle_connection(command: str, archive_root: str):
+    """Open the archive database for one subtitle command; None after printing.
+
+    Neither subtitle command creates ``archive.db`` (``open_database`` does), so
+    the file is checked before opening through the shipped read-command guard,
+    and the transcript-schema capability is required immediately after opening:
+    a database that predates the contract is answered with the fixed rebuild line
+    and exit 1 instead of a raw SQLite error from the first transcript query.
+    """
+    from bili_asr.storage import SchemaContractError, require_subtitle_schema
+
+    connection = _open_read_connection(command, archive_root)
+    if connection is None:
+        return None
+    try:
+        require_subtitle_schema(connection)
+    except SchemaContractError:
+        connection.close()
+        print(
+            _subtitle_schema_rebuild_line(command, archive_root), file=sys.stderr
+        )
+        return None
+    return connection
+
+
+def _subtitle_selector(value: str | None) -> tuple[str | None, int | None]:
+    """Split an optional ``--bvid`` value into ``(bvid, page_index)``.
+
+    The archive's own part vocabulary is accepted: a bare ``bvid`` selects every
+    stored part of that video and ``bvid:pN`` (``page_identity.parse_work_id``)
+    selects exactly that part.  A value the parser cannot read is kept verbatim
+    as a bare bvid, so the database answers no row for it and the caller reports
+    the documented ``unknown --bvid`` configuration error rather than a crash.
+    """
+    from .page_identity import parse_work_id
+
+    if value is None:
+        return None, None
+    try:
+        return parse_work_id(value)
+    except ValueError:
+        return value, None
+
+
 def _cmd_fetch_meta(args: argparse.Namespace) -> int:
     """Collect video metadata into the fresh SQLite archive database.
 
@@ -654,131 +738,183 @@ def _resolve_sessdata(args: argparse.Namespace) -> str | None:
 
 
 def _cmd_probe_subs(args: argparse.Namespace) -> int:
-    from . import bili_client, subtitles
-    from .manifest import ManifestStore
+    """List the subtitle tracks the selected parts expose, writing nothing.
+
+    Read-only by construction: ``probe-subs`` is not an archive-writer command,
+    so it takes no writer lock, creates no file below the archive root, and never
+    creates a missing database.  Exit taxonomy: 0 the probe ran (zero-track parts
+    included); 1 usage/configuration (neither or both selectors, a non-positive
+    bound, a missing database, an unknown --bvid, the schema guard); 2 the probe
+    failed on every selected part, or an unexpected internal error.  A partial
+    per-part failure stays visible in the printed ``failed=`` count.
+    """
+    from bili_asr.services.subtitle_ingest import (
+        SubtitleIngestor,
+        SubtitleSelection,
+    )
+    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
+    from bili_asr.storage import TranscriptRepository
 
+    if (args.bvid is None) == (args.limit_parts is None):
+        print(
+            "probe-subs: exactly one of --bvid / --limit-parts is required",
+            file=sys.stderr,
+        )
+        return 1
+    if args.limit_parts is not None and args.limit_parts < 1:
+        print(
+            "probe-subs: --limit-parts must be a positive integer",
+            file=sys.stderr,
+        )
+        return 1
+    bvid, page_index = _subtitle_selector(args.bvid)
     sessdata = _resolve_sessdata(args)
-    client = bili_client.BiliClient(sessdata=sessdata)
-    try:
-        entries = client.probe_subs(args.bvid)
-    except bili_client.RiskBudgetExhausted as exc:
-        print(f"probe-subs: risk-control ceiling for {args.bvid} "
-              f"(last code {exc.last_code}); retry later.", file=sys.stderr)
-        return 2
-    except bili_client.APIResponseError as exc:
-        store = ManifestStore(root=args.archive_root)
-        _record_api_error(store, args.bvid, exc.code)
-        print(f"probe-subs: API response error (code {exc.code}) for "
-              f"{args.bvid}; retry later.", file=sys.stderr)
+    connection = _open_subtitle_connection("probe-subs", args.archive_root)
+    if connection is None:
         return 1
-    except bili_client.GoneResponse as exc:
-        print(f"probe-subs: terminal API response (code {exc.code}) "
-              f"for {args.bvid}.", file=sys.stderr)
-        return 2
+    try:
+        repository = TranscriptRepository(connection)
+        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
+            # A selector that resolves to no stored part is configuration, not an
+            # empty result, so the probe never reports a part-less run as a
+            # completed read.
+            print(f"probe-subs: unknown --bvid {args.bvid}", file=sys.stderr)
+            return 1
+        ingestor = SubtitleIngestor(
+            BilibiliApiGateway(sessdata=sessdata),
+            repository,
+            credential_present=sessdata is not None,
+        )
+        result = ingestor.probe(
+            SubtitleSelection(
+                bvid=bvid, page_index=page_index, limit=args.limit_parts
+            )
+        )
     except Exception:
+        # Expected gateway failures are resolved inside the service, so anything
+        # escaping is unexpected: the bounded terminal code, never a traceback.
         print("probe-subs: unexpected error", file=sys.stderr)
-        return 1
+        return 2
+    finally:
+        connection.close()
 
-    if not entries:
-        print(f"{args.bvid}: no subtitles visible at this auth tier -> "
-              f"needs_audio (run harvest-subs to record it)")
-        return 0
-    for e in entries:
-        print(f"{args.bvid}: {e.get('lan')} — {e.get('lan_doc')}")
+    print(f"sessdata: {redact_sessdata(sessdata)}")
+    for part in result.parts:
+        if part.error_code is not None:
+            print(f"probe {part.work_id} failed {part.error_code}")
+            continue
+        print(f"probe {part.work_id} tracks={len(part.tracks)}")
+        if not part.tracks:
+            print("  (no subtitles visible)")
+            continue
+        for track in part.tracks:
+            kind = "ai" if track.is_ai else "cc"
+            print(f"  track {track.language} {kind} {track.label}")
+    with_tracks = sum(1 for part in result.parts if part.tracks)
+    failed = sum(1 for part in result.parts if part.error_code is not None)
+    print(
+        f"probe-subs: probed={len(result.parts)} with_tracks={with_tracks} "
+        f"without_tracks={len(result.parts) - with_tracks - failed} "
+        f"failed={failed}"
+    )
+    if failed and failed == len(result.parts):
+        return 2
     return 0
 
 
 def _cmd_harvest_subs(args: argparse.Namespace) -> int:
-    from . import bili_client, subtitles
-    from .manifest import ManifestStore
+    """Acquire the selected parts into normalized transcripts with run evidence.
+
+    Exit taxonomy: 0 the bounded run completed — including a run whose every
+    attempted part had no visible caption, and a selection that resolved to no
+    part; 1 usage/configuration (a missing database, an unknown --bvid, a missing
+    bound, an empty --language entry, the schema guard); 2 the run failed on every
+    attempted part, or an unexpected internal error.  Partial per-part failure
+    stays visible in the printed counts rather than in the exit code.
+    """
+    from bili_asr.services.subtitle_ingest import (
+        SubtitleIngestor,
+        SubtitleSelection,
+    )
+    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway
+    from bili_asr.storage import TranscriptRepository
 
-    store = ManifestStore(root=args.archive_root)
-    entries = store.load()
-    sessdata = _resolve_sessdata(args)
-    client = bili_client.BiliClient(sessdata=sessdata)
-    if args.bvid:
-        todo = _todo_for_bvid(store, args.bvid, entries)
-        if todo is None:
-            print(f"{args.bvid}: multi-part video needs an explicit page",
-                  file=sys.stderr)
-            return 1
-        if not todo:
+    languages: tuple[str, ...] = ()
+    if args.language is not None:
+        languages = tuple(entry.strip() for entry in args.language.split(","))
+        if any(not entry for entry in languages):
             print(
-                f"{args.bvid}: unresolved; not assigned to a page",
+                "harvest-subs: --language entries must not be empty",
                 file=sys.stderr,
             )
             return 1
-    else:
-        todo = [
-            (key, e) for key, e in entries.items()
-            if e.get("status") == "meta_ok" and not _is_excluded(e)
-        ]
-    if args.limit is not None:
-        todo = todo[: args.limit]
-
-    done = needs_audio = failed = 0
-    risk_interrupted = False
-    for key, entry in todo:
-        target = _identity_from_entry(entry, key)
-        label = (
-            target.work_id if hasattr(target, "work_id") else str(key)
+    if args.limit_parts is not None and args.limit_parts < 1:
+        print(
+            "harvest-subs: --limit-parts must be a positive integer",
+            file=sys.stderr,
         )
-        try:
-            status = subtitles.harvest_subtitle(
-                client, target, store, args.archive_root
+        return 1
+    bvid, page_index = _subtitle_selector(args.bvid)
+    if args.limit_parts is None and page_index is None:
+        # No unbounded runs: only a single named part is bounded by construction.
+        print(
+            "harvest-subs: --limit-parts is required unless a single bvid:pN "
+            "part is selected",
+            file=sys.stderr,
+        )
+        return 1
+    sessdata = _resolve_sessdata(args)
+    connection = _open_subtitle_connection("harvest-subs", args.archive_root)
+    if connection is None:
+        return 1
+    try:
+        repository = TranscriptRepository(connection)
+        if bvid is not None and not repository.list_selected_parts(bvid, page_index):
+            # Decided before the run is opened: an unknown selector is
+            # configuration and must not leave an empty run row behind.
+            print(f"harvest-subs: unknown --bvid {args.bvid}", file=sys.stderr)
+            return 1
+        ingestor = SubtitleIngestor(
+            BilibiliApiGateway(sessdata=sessdata),
+            repository,
+            credential_present=sessdata is not None,
+        )
+        result = ingestor.harvest(
+            SubtitleSelection(
+                bvid=bvid,
+                page_index=page_index,
+                limit=args.limit_parts,
+                languages=languages,
             )
-        except bili_client.AmbiguousPageError:
-            failed += 1
-            print(f"{label}: multi-part video needs an explicit page",
-                  file=sys.stderr)
-            continue
-        except bili_client.RiskBudgetExhausted as exc:
-            failed += 1
-            print(f"{label}: risk-control ceiling (last code {exc.last_code}); "
-                  f"stopping — re-run to resume.", file=sys.stderr)
-            risk_interrupted = True
-            break
-        except bili_client.APIResponseError as exc:
-            failed += 1
-            _record_api_error(store, key, exc.code)
-            print(f"{label}: API response error (code {exc.code}); "
-                  f"continuing.", file=sys.stderr)
-            continue
-        except bili_client.GoneResponse as exc:
-            failed += 1
-            e = dict(store.get(key) or store.get_compatible(key) or {})
-            if e.get("work_id"):
-                e["status"] = "gone"
-                store.upsert(e)
-            print(f"{label}: terminal API response (code {exc.code}); "
-                  f"marked gone.", file=sys.stderr)
-            continue
-        except ValueError as exc:
-            failed += 1
-            msg = str(exc)
-            if "missing cid" in msg or "unresolved" in msg:
-                print(f"{label}: {msg}", file=sys.stderr)
-            else:
-                print(f"{label}: unexpected error", file=sys.stderr)
-            continue
-        except Exception:
-            failed += 1
-            print(f"{label}: unexpected error", file=sys.stderr)
-            continue
-        if status == "subtitle_done":
-            done += 1
-            print(f"{label}: subtitle downloaded -> subtitle_done")
-        else:
-            needs_audio += 1
-            print(f"{label}: no subtitles -> needs_audio")
-        if key != todo[-1][0]:
-            time.sleep(3.0)
+        )
+    except Exception:
+        # The service finishes an interrupted run as failed before anything
+        # escapes, so this is the bounded terminal code with no traceback.
+        print("harvest-subs: unexpected error", file=sys.stderr)
+        return 2
+    finally:
+        connection.close()
 
-    print(f"harvest-subs: {done} subtitle_done, {needs_audio} needs_audio"
-          + (f", {failed} failed" if failed else ""))
-    if risk_interrupted:
+    print(f"sessdata: {redact_sessdata(sessdata)}")
+    for outcome in result.parts:
+        if outcome.outcome == "failed":
+            print(f"harvest {outcome.work_id} failed {outcome.error_code}")
+        elif outcome.outcome == "no-subtitle":
+            print(f"harvest {outcome.work_id} no-subtitle")
+        else:
+            print(
+                f"harvest {outcome.work_id} {outcome.outcome} "
+                f"{outcome.source_kind} {outcome.language} v{outcome.version}"
+            )
+    print(
+        f"harvest-subs: run_id={result.run_id} attempted={result.attempted} "
+        f"stored={result.stored} unchanged={result.unchanged} "
+        f"no-subtitle={result.no_subtitle} failed={result.failed} "
+        f"remaining_without_transcript={result.remaining_without_transcript}"
+    )
+    if result.attempted and result.failed == result.attempted:
         return 2
-    return 1 if failed else 0
+    return 0
 
 
 def _cmd_download_audio(args: argparse.Namespace) -> int:
@@ -2301,7 +2437,6 @@ _ARCHIVE_WRITER_COMMANDS = frozenset({
     "recover",
     "asr",
     "pilot",
-    "probe-subs",
     "harvest-subs",
     "download-audio",
     "run",
diff --git a/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py b/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py
new file mode 100644
index 0000000..41a2dc9
--- /dev/null
+++ b/bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py
@@ -0,0 +1,595 @@
+"""Bounded subtitle acquisition between the typed gateway and transcript storage.
+
+:class:`SubtitleIngestor` owns everything between "which parts?" and "what was
+written?": the candidate enumeration order, the track-selection preference, the
+per-part transaction boundary, the run-record lifecycle, and the outcome
+mapping.  It depends on the :class:`~bili_asr.sources.models.BilibiliGateway`
+protocol and the :class:`~bili_asr.storage.database.TranscriptRepository` only —
+never on the concrete adapter or on an upstream response dictionary.
+
+The surface is synchronous, like :class:`~bili_asr.services.metadata_ingest.MetadataIngestor`'s,
+and runs the gateway's async calls on one event loop per operation.
+
+``probe`` writes nothing at all: no run, no attempt, no transcript, no file.
+``harvest`` opens exactly one ``acquisition_runs`` row, records exactly one
+attempt row per attempted part through one repository call (one transaction per
+part), and finishes the run with the outcome derived from those attempts.
+
+Outcome mapping (one outcome per attempted part):
+
+- the listing was empty, or upstream answered ``not_found`` for the listing or
+  the body → ``no-subtitle`` (the part is not a failure; it stays eligible for a
+  later run, and the attempt row carries ``not_found`` when upstream said so);
+- the body was fetched and stored → ``stored``, or ``unchanged`` when a stored
+  version of the same identity already carries that content;
+- any other bounded gateway failure → ``failed`` with that scalar error code.
+"""
+
+from __future__ import annotations
+
+import asyncio
+from collections import Counter
+from dataclasses import dataclass
+import sqlite3
+import time
+from typing import Callable
+import uuid
+
+from bili_asr.page_identity import format_work_id
+from bili_asr.sources.models import (
+    BilibiliGateway,
+    GatewayError,
+    GatewayNotFound,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage.database import TranscriptRepository
+from bili_asr.storage.models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_CAPTION_SOURCE_KINDS,
+    AcquisitionRunRecord,
+    TranscriptSegmentRecord,
+)
+
+#: The acquisition kind every run of this service records.
+_ACQUISITION_KIND = "subtitle"
+#: The stored source kind of one selected track, by its machine-generated flag.
+_SOURCE_KIND_BY_AI = {True: "subtitle-ai", False: "subtitle-cc"}
+#: The attempt outcomes this service records, as the storage vocabulary spells
+#: them.  ``stored``/``unchanged`` come back from the transcript write; the other
+#: two are the outcomes of an attempt that produced no transcript, and ``failed``
+#: is also the outcome a run unfinished by an unexpected error is closed with.
+_OUTCOME_STORED = "stored"
+_OUTCOME_UNCHANGED = "unchanged"
+_OUTCOME_NO_SUBTITLE = "no-subtitle"
+_OUTCOME_FAILED = "failed"
+#: The default language family order the selection preference ranks by.
+_DEFAULT_LANGUAGE_FAMILY_ORDER = ("zh", "en")
+
+
+def _now() -> int:
+    """Return the current Unix second used for all persisted clocks."""
+
+    return int(time.time())
+
+
+def _choice(value: str, field: str, allowed: frozenset[str]) -> str:
+    """Return ``value`` when the published storage vocabulary admits it.
+
+    The service derives the two vocabulary values it writes — the caption
+    ``source_kind`` of one selected track and the acquisition ``kind`` of one
+    run — instead of passing storage literals through, and validates each of them
+    against the enum the storage contract publishes.  A drift between the two
+    vocabularies therefore fails here with a bounded message instead of
+    surfacing as a SQLite ``CHECK`` violation in the middle of a run.
+    """
+
+    if value not in allowed:
+        raise ValueError(f"{field} is not part of the storage vocabulary: {value}")
+    return value
+
+
+def _caption_source_kind(is_ai: bool) -> str:
+    """Return the stored source kind of one selected track, validated."""
+
+    return _choice(
+        _SOURCE_KIND_BY_AI[is_ai], "source_kind", ALLOWED_CAPTION_SOURCE_KINDS
+    )
+
+
+def language_family(language: str, is_ai: bool) -> str:
+    """Return the language family one listed track belongs to.
+
+    Total by construction, because the gateway rejects a ``lan`` without a
+    non-empty primary subtag: an AI caption's ``ai-`` prefix is stripped and the
+    lowercase primary subtag — everything before the first ``-`` — is the
+    family.  The family is derived from the two normalized facts the track DTO
+    already guarantees (``language`` and ``is_ai``) because upstream spells the
+    same spoken language differently per caption kind (``zh-CN``, ``zh-Hans``
+    and ``zh-Hant`` for uploader captions against ``ai-zh`` for the machine
+    one), so a fixed list of codes would silently mis-rank a code upstream adds.
+    """
+
+    code = language.strip().lower()
+    if is_ai and code.startswith("ai-"):
+        code = code[3:]
+    return code.split("-", 1)[0]
+
+
+def _family_rank(family: str) -> int:
+    """Return one family's rank in the default order; the rest share the last."""
+
+    try:
+        return _DEFAULT_LANGUAGE_FAMILY_ORDER.index(family)
+    except ValueError:
+        return len(_DEFAULT_LANGUAGE_FAMILY_ORDER)
+
+
+def select_subtitle_track(
+    tracks: tuple[SubtitleTrack, ...], languages: tuple[str, ...] = ()
+) -> SubtitleTrack | None:
+    """Select exactly one track of a part, or ``None`` when none is usable.
+
+    Without ``languages`` the default preference applies: the default language
+    family order first (``zh``, then ``en``, then every other family in upstream
+    order), and inside one family an uploader caption before a machine-generated
+    one.  That is the total order ``(family rank, is_ai, upstream index)`` taken
+    at its minimum — the first track a stable sort on the same key would yield —
+    so the shipped legacy preference (AI first) is deliberately replaced and the
+    uploader caption wins whenever both are visible.
+
+    With ``languages`` each entry is matched exactly against a track's
+    ``language`` code — the code ``probe-subs`` prints — the first preference
+    that matches anything wins, and the tracks it matches are ranked the same
+    way (CC before AI, then upstream order).  ``None`` then means nothing usable
+    for any requested language was visible, never a failure.
+    """
+
+    if not tracks:
+        return None
+    if languages:
+        for preference in languages:
+            matching = [
+                (index, track)
+                for index, track in enumerate(tracks)
+                if track.language == preference
+            ]
+            if matching:
+                return min(matching, key=lambda pair: (pair[1].is_ai, pair[0]))[1]
+        return None
+    return min(
+        enumerate(tracks),
+        key=lambda pair: (
+            _family_rank(language_family(pair[1].language, pair[1].is_ai)),
+            pair[1].is_ai,
+            pair[0],
+        ),
+    )[1]
+
+
+@dataclass(frozen=True, slots=True)
+class SubtitleSelection:
+    """One bounded selection of archive parts to inspect or acquire.
+
+    ``bvid`` alone selects every part of that video already in the database
+    (including parts that already hold a transcript — that is how a caption
+    upstream has since added or revised is re-checked); ``bvid`` together with
+    ``page_index`` selects exactly that part, using the archive's own
+    ``bvid:pN`` vocabulary; ``bvid=None`` selects the pending enumeration.
+    ``limit`` bounds the selection and is required unless ``page_index`` names
+    one part, which is bounded by construction.  ``languages`` is empty for the
+    default preference and otherwise the exact preference order.
+    """
+
+    bvid: str | None = None
+    page_index: int | None = None
+    limit: int | None = None
+    languages: tuple[str, ...] = ()
+
+
+@dataclass(frozen=True, slots=True)
+class SubtitleProbePart:
+    """What one probed part exposed: its tracks, or the bounded failure code."""
+
+    work_id: str
+    tracks: tuple[SubtitleTrack, ...]
+    error_code: str | None = None
+
+
+@dataclass(frozen=True, slots=True)
+class ProbeResult:
+    """The read-only probe's evidence: credential presence and one entry per part."""
+
+    credential_present: bool
+    parts: tuple[SubtitleProbePart, ...]
+
+
+@dataclass(frozen=True, slots=True)
+class SubtitlePartOutcome:
+    """The one outcome one attempted part produced, with its bounded evidence."""
+
+    work_id: str
+    outcome: str
+    error_code: str | None
+    source_kind: str | None
+    language: str | None
+    version: int | None
+
+
+@dataclass(frozen=True, slots=True)
+class HarvestResult:
+    """One run's counting evidence: every number the summary line prints."""
+
+    run_id: str
+    attempted: int
+    stored: int
+    unchanged: int
+    no_subtitle: int
+    failed: int
+    credential_present: bool
+    remaining_without_transcript: int
+    parts: tuple[SubtitlePartOutcome, ...]
+
+
+@dataclass(frozen=True, slots=True)
+class _SubtitleWorkItem:
+    """One normalized unit of subtitle work.
+
+    The two repository selections answer two different row shapes — the pending
+    view carries ``bvid`` and ``cid``, the selected-parts view carries neither
+    ``bvid`` — so the service normalizes both into this one shape before any
+    gateway call: the gateway needs ``(bvid, cid)``, the transcript write needs
+    ``video_part_id``, and ``work_id`` is the identity every printed line uses.
+    """
+
+    work_id: str
+    bvid: str
+    cid: int
+    video_part_id: int
+
+
+def _pending_work_item(row: sqlite3.Row) -> _SubtitleWorkItem:
+    """Normalize one ``v_pending_subtitles`` row, which carries ``bvid``/``cid``."""
+
+    return _SubtitleWorkItem(
+        work_id=str(row["work_id"]),
+        bvid=str(row["bvid"]),
+        cid=int(row["cid"]),
+        video_part_id=int(row["video_part_id"]),
+    )
+
+
+def _selected_work_item(row: sqlite3.Row, bvid: str) -> _SubtitleWorkItem:
+    """Normalize one ``v_video_parts`` row of an explicit selection.
+
+    The selected-parts view carries no ``bvid`` column, so the caller's own
+    selector supplies it; the ``work_id`` the view carries is the identity the
+    row is already addressed by.
+    """
+
+    return _SubtitleWorkItem(
+        work_id=str(row["work_id"]),
+        bvid=bvid,
+        cid=int(row["cid"]),
+        video_part_id=int(row["video_part_id"]),
+    )
+
+
+def _selector(selection: SubtitleSelection) -> tuple[str, str | None]:
+    """Return the run's ``(selector_kind, selector_target)`` as selected.
+
+    The pending enumeration carries no target; an explicit selection records the
+    operator's own selector — the bare ``bvid``, or the ``bvid:pN`` part that was
+    named — so the run row says what was asked for, never more.
+    """
+
+    if selection.bvid is None:
+        return "pending", None
+    if selection.page_index is None:
+        return "bvid", selection.bvid
+    return "bvid", format_work_id(selection.bvid, selection.page_index)
+
+
+class SubtitleIngestor:
+    """Inspect and acquire one bounded selection of archive subtitle work.
+
+    ``credential_present`` is the composition root's own observation that a
+    SESSDATA was in effect for this run.  It is configuration, not a gateway
+    dependency: the run row records it so an attempt recorded without a caption
+    stays interpretable afterwards, and no display path ever carries the value.
+    ``clock`` is the run/attempt timestamp source, in Unix seconds.
+    """
+
+    def __init__(
+        self,
+        gateway: BilibiliGateway,
+        repository: TranscriptRepository,
+        *,
+        credential_present: bool = False,
+        clock: Callable[[], int] = _now,
+    ) -> None:
+        self._gateway = gateway
+        self._repository = repository
+        self._credential_present = bool(credential_present)
+        self._clock = clock
+
+    def probe(self, selection: SubtitleSelection) -> ProbeResult:
+        """List what each selected part exposes, writing nothing at all."""
+
+        parts = asyncio.run(self._probe_parts(self._candidate_items(selection)))
+        return ProbeResult(
+            credential_present=self._credential_present,
+            parts=parts,
+        )
+
+    def harvest(self, selection: SubtitleSelection) -> HarvestResult:
+        """Acquire the selected parts and record one run with its per-part evidence.
+
+        The run row is opened before the first part is attempted and finished
+        with the outcome derived from the attempts (``complete`` when nothing
+        failed, ``partial`` when failed and non-failed attempts coexist,
+        ``failed`` when every attempt failed) — including a selection that
+        resolved to no part at all, which is complete because nothing failed.  An
+        unexpected error escaping a part finishes the opened run as ``failed``
+        before it propagates, so a run is never left ``running``.
+        """
+
+        items = self._candidate_items(selection)
+        selector_kind, selector_target = _selector(selection)
+        run_id = uuid.uuid4().hex
+        self._repository.start_acquisition_run(
+            AcquisitionRunRecord(
+                run_id=run_id,
+                kind=_choice(_ACQUISITION_KIND, "kind", ALLOWED_ACQUISITION_KINDS),
+                selector_kind=selector_kind,
+                selector_target=selector_target,
+                requested_limit=selection.limit,
+                credential_present=self._credential_present,
+                started_at=self._clock(),
+            )
+        )
+        try:
+            outcomes = asyncio.run(
+                self._acquire_parts(run_id, items, selection.languages)
+            )
+        except BaseException:
+            self._finish_failed_run(run_id)
+            raise
+        self._repository.finish_acquisition_run(run_id, self._clock())
+        counts = Counter(outcome.outcome for outcome in outcomes)
+        return HarvestResult(
+            run_id=run_id,
+            attempted=len(outcomes),
+            stored=counts[_OUTCOME_STORED],
+            unchanged=counts[_OUTCOME_UNCHANGED],
+            no_subtitle=counts[_OUTCOME_NO_SUBTITLE],
+            failed=counts[_OUTCOME_FAILED],
+            credential_present=self._credential_present,
+            remaining_without_transcript=(
+                self._repository.count_pending_subtitle_parts()
+            ),
+            parts=outcomes,
+        )
+
+    def _finish_failed_run(self, run_id: str) -> None:
+        """Finish a run an unexpected error escaped, without masking that error.
+
+        The run row must never be left ``running``, and the escaping exception is
+        the bounded evidence the caller reports, so a failure to finish the row
+        is deliberately not raised over it.
+        """
+
+        try:
+            self._repository.finish_acquisition_run(
+                run_id, self._clock(), outcome=_OUTCOME_FAILED
+            )
+        except Exception:
+            pass
+
+    def _candidate_items(
+        self, selection: SubtitleSelection
+    ) -> list[_SubtitleWorkItem]:
+        """Return the selected parts in the locked enumeration order.
+
+        An explicit ``bvid`` reads ``list_selected_parts`` and keeps every stored
+        part of that video, already-transcribed ones included, bounded by
+        ``limit`` when one was given.  The pending selection reads
+        ``list_pending_subtitle_parts``: never-attempted parts before previously
+        attempted ones, oldest attempt first, so successive bounded runs advance
+        through the captionless backlog instead of re-attempting its head.
+        """
+
+        if selection.bvid is None:
+            return [
+                _pending_work_item(row)
+                for row in self._repository.list_pending_subtitle_parts(
+                    selection.limit
+                )
+            ]
+        rows = self._repository.list_selected_parts(
+            selection.bvid, selection.page_index
+        )
+        if selection.limit is not None:
+            rows = rows[: selection.limit]
+        return [_selected_work_item(row, selection.bvid) for row in rows]
+
+    async def _probe_parts(
+        self, items: list[_SubtitleWorkItem]
+    ) -> tuple[SubtitleProbePart, ...]:
+        """Probe every selected part in selection order."""
+
+        return tuple([await self._probe_part(item) for item in items])
+
+    async def _probe_part(self, item: _SubtitleWorkItem) -> SubtitleProbePart:
+        """List one part's inventory; a bounded failure keeps its code on the part."""
+
+        try:
+            tracks = await self._gateway.get_subtitle_tracks(item.bvid, item.cid)
+        except GatewayError as error:
+            return SubtitleProbePart(
+                work_id=item.work_id, tracks=(), error_code=error.code
+            )
+        return SubtitleProbePart(work_id=item.work_id, tracks=tuple(tracks))
+
+    async def _acquire_parts(
+        self,
+        run_id: str,
+        items: list[_SubtitleWorkItem],
+        languages: tuple[str, ...],
+    ) -> tuple[SubtitlePartOutcome, ...]:
+        """Acquire every selected part in selection order, one transaction each."""
+
+        return tuple(
+            [await self._acquire_part(run_id, item, languages) for item in items]
+        )
+
+    async def _acquire_part(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        languages: tuple[str, ...],
+    ) -> SubtitlePartOutcome:
+        """Acquire one part: list, select, fetch, store, record the attempt."""
+
+        started_at = self._clock()
+        try:
+            tracks = await self._gateway.get_subtitle_tracks(item.bvid, item.cid)
+        except GatewayNotFound:
+            return self._record_captionless_part(
+                run_id, item, "not_found", started_at
+            )
+        except GatewayError as error:
+            return self._record_failed_part(run_id, item, error, started_at)
+        track = select_subtitle_track(tracks, languages)
+        if track is None:
+            # Either nothing was visible or nothing matched the requested
+            # languages: no usable track for this attempt, which is never a
+            # failure and leaves the part pending for a later run.
+            return self._record_captionless_part(run_id, item, None, started_at)
+        try:
+            segments = await self._gateway.fetch_subtitle_segments(
+                track, item.bvid, item.cid
+            )
+        except GatewayNotFound:
+            return self._record_captionless_part(
+                run_id, item, "not_found", started_at
+            )
+        except GatewayError as error:
+            return self._record_failed_part(run_id, item, error, started_at)
+        return self._record_caption(run_id, item, track, segments, started_at)
+
+    def _record_caption(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        track: SubtitleTrack,
+        segments: tuple[SubtitleSegment, ...],
+        started_at: int,
+    ) -> SubtitlePartOutcome:
+        """Store one selected track's body with its attempt evidence, atomically.
+
+        The repository call is the whole per-part transaction: it appends a
+        version with its segments when the content is new, records the attempt
+        with the resulting ``stored``/``unchanged`` outcome, and commits — or
+        rolls the whole call back.  The body is converted field for field, and
+        the language is stored trimmed, so the reported language is the identity
+        the store holds.
+        """
+
+        finished_at = self._clock()
+        source_kind = _caption_source_kind(track.is_ai)
+        language = track.language.strip()
+        write = self._repository.record_acquired_transcript(
+            run_id=run_id,
+            video_part_id=item.video_part_id,
+            source_kind=source_kind,
+            language=language,
+            segments=tuple(
+                TranscriptSegmentRecord(
+                    start_ms=segment.start_ms,
+                    end_ms=segment.end_ms,
+                    text=segment.text,
+                )
+                for segment in segments
+            ),
+            started_at=started_at,
+            finished_at=finished_at,
+            created_at=finished_at,
+        )
+        return SubtitlePartOutcome(
+            work_id=item.work_id,
+            outcome=write.outcome,
+            error_code=None,
+            source_kind=source_kind,
+            language=language,
+            version=write.version,
+        )
+
+    def _record_captionless_part(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        error_code: str | None,
+        started_at: int,
+    ) -> SubtitlePartOutcome:
+        """Record one attempt that found no usable caption — never a failure.
+
+        An empty listing and a ``not_found`` answer both mean no usable caption
+        was visible for this part at this attempt; the attempt row is the whole
+        evidence (no transcript), and the part stays eligible for a later run.
+        """
+
+        self._repository.record_subtitle_attempt(
+            run_id=run_id,
+            video_part_id=item.video_part_id,
+            outcome=_OUTCOME_NO_SUBTITLE,
+            error_code=error_code,
+            started_at=started_at,
+            finished_at=self._clock(),
+        )
+        return SubtitlePartOutcome(
+            work_id=item.work_id,
+            outcome=_OUTCOME_NO_SUBTITLE,
+            error_code=error_code,
+            source_kind=None,
+            language=None,
+            version=None,
+        )
+
+    def _record_failed_part(
+        self,
+        run_id: str,
+        item: _SubtitleWorkItem,
+        error: GatewayError,
+        started_at: int,
+    ) -> SubtitlePartOutcome:
+        """Record one bounded gateway failure, with its scalar code as evidence."""
+
+        self._repository.record_subtitle_attempt(
+            run_id=run_id,
+            video_part_id=item.video_part_id,
+            outcome=_OUTCOME_FAILED,
+            error_code=error.code,
+            started_at=started_at,
+            finished_at=self._clock(),
+        )
+        return SubtitlePartOutcome(
+            work_id=item.work_id,
+            outcome=_OUTCOME_FAILED,
+            error_code=error.code,
+            source_kind=None,
+            language=None,
+            version=None,
+        )
+
+
+__all__ = [
+    "HarvestResult",
+    "ProbeResult",
+    "SubtitleIngestor",
+    "SubtitlePartOutcome",
+    "SubtitleProbePart",
+    "SubtitleSelection",
+    "language_family",
+    "select_subtitle_track",
+]
diff --git a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
index 92dcbd1..968987a 100644
--- a/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
+++ b/bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py
@@ -4,9 +4,10 @@ Every package-seam test scripts these fakes instead of touching the pinned
 ``bilibili-api-python`` distribution or the network:
 
 - ``FakeGateway`` is the plain ``BilibiliGateway`` protocol double used by
-  the ingestor tests: scripted pages, parts, and summary completions with
-  recorded fetch calls; unexpected fetches fail loudly instead of returning
-  script-free data.
+  the ingestor and CLI tests: scripted pages, parts, summary completions and
+  per-part subtitle listings/bodies with recorded fetch calls, plus the
+  credential the composition root handed the double; unexpected fetches fail
+  loudly instead of returning script-free data.
 - ``FakeUpstreamScript`` / ``build_fake_package`` / ``bilibili_api_seam``
   install the fake ``bilibili_api`` package on ``sys.modules`` for the real
   adapter tests.  The fake mirrors only the documented import surface the
@@ -50,6 +51,7 @@ Every package-seam test scripts these fakes instead of touching the pinned
 from __future__ import annotations
 
 import dataclasses
+import importlib
 import sys
 import types
 from enum import Enum
@@ -321,20 +323,37 @@ class FakeUpstreamScript:
 
 
 class FakeGateway:
-    """Scripted ``BilibiliGateway`` protocol double for ingestor tests.
+    """Scripted ``BilibiliGateway`` protocol double for ingestor and CLI tests.
 
     Unexpected fetches fail loudly instead of returning script-free data;
     a scripted ``BaseException`` value is raised as-is.
+
+    The two subtitle calls are scripted per part, by ``cid``:
+    ``script_subtitle_tracks`` scripts what ``get_subtitle_tracks`` answers
+    (an inventory, or an empty tuple for a part nothing is visible for, or a
+    ``GatewayError`` to raise) and ``script_subtitle_segments`` scripts what
+    ``fetch_subtitle_segments`` answers (a body, or a ``GatewayError`` to
+    raise).  ``listing_cids`` and ``body_cids`` record the parts whose listing
+    and whose body were requested, in issue order, so the candidate order, the
+    selected part, and "the body was never fetched" are assertable.  The
+    ``sessdata`` attribute holds the credential the composition root handed the
+    double — ``None`` until a test installs it that way — so the credential
+    boundary is assertable without ever comparing a value in output.
     """
 
     def __init__(self, package_version: str = FAKE_PACKAGE_VERSION) -> None:
         self.package_version = package_version
+        self.sessdata: str | None = None
         self.page_calls: list[tuple[int, int, int]] = []
         self.parts_calls: list[str] = []
         self.completion_calls: list[str] = []
+        self.listing_cids: list[int] = []
+        self.body_cids: list[int] = []
         self._pages: dict[int, object] = {}
         self._parts: dict[str, object] = {}
         self._completions: dict[str, object] = {}
+        self._subtitle_tracks: dict[int, object] = {}
+        self._subtitle_segments: dict[int, object] = {}
 
     def script_page(self, page_number: int, page: object) -> None:
         self._pages[page_number] = page
@@ -345,6 +364,16 @@ class FakeGateway:
     def script_completion(self, bvid: str, completed: object) -> None:
         self._completions[bvid] = completed
 
+    def script_subtitle_tracks(self, cid: int, tracks: object) -> None:
+        """Script what the track listing answers for one part, by its ``cid``."""
+
+        self._subtitle_tracks[cid] = tracks
+
+    def script_subtitle_segments(self, cid: int, segments: object) -> None:
+        """Script what the body fetch answers for one part, by its ``cid``."""
+
+        self._subtitle_segments[cid] = segments
+
     async def get_user_video_page(
         self, mid: int, page_number: int, page_size: int = 30
     ) -> UserVideoPage:
@@ -359,6 +388,22 @@ class FakeGateway:
         self.completion_calls.append(summary.bvid)
         return self._scripted(self._completions, summary.bvid, "completed-summary")
 
+    async def get_subtitle_tracks(
+        self, bvid: str, cid: int
+    ) -> tuple[SubtitleTrack, ...]:
+        self.listing_cids.append(cid)
+        return self._scripted(
+            self._subtitle_tracks, cid, "subtitle-track listing"
+        )
+
+    async def fetch_subtitle_segments(
+        self, track: SubtitleTrack, bvid: str, cid: int
+    ) -> tuple[SubtitleSegment, ...]:
+        self.body_cids.append(cid)
+        return self._scripted(
+            self._subtitle_segments, cid, "subtitle-segment body"
+        )
+
     def get_package_version(self) -> str:
         return self.package_version
 
@@ -815,6 +860,36 @@ def bilibili_api_seam(monkeypatch) -> FakeUpstreamScript:
         sys.modules.pop(GATEWAY_ADAPTER_MODULE, None)
 
 
+@pytest.fixture
+def fake_gateway_seam(monkeypatch) -> FakeGateway:
+    """Install one ``FakeGateway`` as the product adapter and yield it.
+
+    Every command handler imports ``BilibiliApiGateway`` inside its own body,
+    so replacing that class in its module puts the whole command path — CLI
+    composition root included — on this protocol double, with no network and no
+    package seam.  The replacement records the credential the composition root
+    handed it on ``FakeGateway.sessdata``.
+
+    The module is reached through ``importlib`` deliberately: the package-seam
+    fixture above drops the adapter module from ``sys.modules``, and a plain
+    ``import ... as`` would then bind the parent package's stale attribute
+    instead of the module the handler imports from.
+    """
+
+    gateway = FakeGateway()
+    gateway_module = importlib.import_module(GATEWAY_ADAPTER_MODULE)
+
+    def factory(
+        sessdata: str | None = None, proxy: str | None = None
+    ) -> FakeGateway:
+        del proxy
+        gateway.sessdata = sessdata
+        return gateway
+
+    monkeypatch.setattr(gateway_module, "BilibiliApiGateway", factory)
+    return gateway
+
+
 __all__ = [
     "BVID",
     "DOCUMENTED_METADATA_CALLS",
@@ -845,6 +920,7 @@ __all__ = [
     "assert_only_documented_metadata_calls",
     "bilibili_api_seam",
     "build_fake_package",
+    "fake_gateway_seam",
     "make_detail_response",
     "make_part_item",
     "make_player_response",
diff --git a/bilibili-asr-archive/tests/test_cli_asr.py b/bilibili-asr-archive/tests/test_cli_asr.py
index 010222f..4879c58 100644
--- a/bilibili-asr-archive/tests/test_cli_asr.py
+++ b/bilibili-asr-archive/tests/test_cli_asr.py
@@ -1,4 +1,11 @@
-"""Command-level frozen status transitions through harvest / download / asr."""
+"""Command-level frozen status transitions through download / asr.
+
+The legacy manifest states these commands start from (``needs_audio``,
+``subtitle_done``) are produced by the legacy subtitle producer
+(``subtitles.harvest_subtitle``) directly: ``harvest-subs`` moved to the SQLite
+transcript path and no longer writes the manifest, so these tests drive the
+ASR/audio path from the state a pre-cutover archive already holds.
+"""
 
 from __future__ import annotations
 
@@ -85,6 +92,26 @@ def _subtitle_transport():
     )
 
 
+def _legacy_subtitle_state(root, identity, transport) -> str:
+    """Produce the legacy manifest state the ASR/audio path still reads.
+
+    ``harvest-subs`` no longer writes the manifest — it stores normalized
+    transcripts in ``archive.db`` — so the legacy producer the pilot and
+    coordinator paths still call is driven directly here: the resulting row and
+    its raw/srt artifacts are exactly what a pre-cutover archive holds.
+    """
+    from bili_asr import subtitles
+
+    store = ManifestStore(root=root)
+    client = bc.BiliClient(
+        transport=transport,
+        sleeper=lambda _seconds: None,
+        jitter=lambda: 0.0,
+        sessdata=None,
+    )
+    return subtitles.harvest_subtitle(client, identity, store, root)
+
+
 def test_download_audio_rejects_escaped_downloader_result(tmp_root, monkeypatch, capsys):
     from bili_asr import audio
     identity = page_identity("BVescape", 0, 333, "p0")
@@ -97,7 +124,7 @@ def test_download_audio_rejects_escaped_downloader_result(tmp_root, monkeypatch,
     assert rc == 1
     assert "0 audio_ok" in captured.out
     assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "needs_audio"
-def test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived(
+def test_cli_audio_branch_needs_audio_audio_ok_archived(
     tmp_root, monkeypatch, capsys
 ):
     identity = page_identity("BVaud", 0, 222, "p0")
@@ -112,11 +139,9 @@ def test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived(
     _patch_cli(monkeypatch)
     monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
 
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
+    assert _legacy_subtitle_state(tmp_root, identity, _audio_transport()) == "needs_audio"
     captured = capsys.readouterr()
-    assert rc == 0, captured.err
-    after_harvest = ManifestStore(root=tmp_root).get(identity.work_id)
-    assert after_harvest["status"] == "needs_audio"
+    assert ManifestStore(root=tmp_root).get(identity.work_id)["status"] == "needs_audio"
 
     rc = main(["download-audio", "--missing-subs", "--archive-root", tmp_root])
     captured = capsys.readouterr()
@@ -136,7 +161,7 @@ def test_cli_audio_branch_meta_ok_needs_audio_audio_ok_archived(
     assert transcribe_calls == [audio_abs]
 
 
-def test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr(
+def test_cli_subtitle_branch_subtitle_done_archived_skips_asr(
     tmp_root, monkeypatch, capsys
 ):
     identity = page_identity("BVsub", 0, 111, "p0")
@@ -150,9 +175,11 @@ def test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr(
     monkeypatch.setattr(asr_mod, "transcribe", fake_transcribe)
     _patch_cli(monkeypatch, _subtitle_transport())
 
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 0, captured.err
+    assert (
+        _legacy_subtitle_state(tmp_root, identity, _subtitle_transport())
+        == "subtitle_done"
+    )
+    capsys.readouterr()
     after_harvest = ManifestStore(root=tmp_root).get(identity.work_id)
     assert after_harvest["status"] == "subtitle_done"
     assert os.path.isfile(os.path.join(tmp_root, after_harvest["srt_path"]))
@@ -166,37 +193,6 @@ def test_cli_subtitle_branch_meta_ok_subtitle_done_archived_skips_asr(
     assert transcribe_calls == []
 
 
-def test_cli_harvest_risk_exhaustion_preserves_last_stable_status(
-    tmp_root, monkeypatch, capsys
-):
-    first = page_identity("BVok", 0, 111, "p0")
-    second = page_identity("BVrisk", 0, 222, "p0")
-    store = ManifestStore(root=tmp_root)
-    store.upsert(_row(first, title="stable"))
-    store.upsert(_row(second, title="risk"))
-
-    risk = (412, {"code": -412, "message": "request too frequent"})
-    transport = RouterTransport(
-        {
-            "finger/spi": [SPI_OK] * 8,
-            "nav": [nav_ok()],
-            "player/wbi/v2": [player_ok([sub_entry()])] + [risk] * 8,
-            "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-        }
-    )
-    monkeypatch.setattr(asr_mod, "transcribe", lambda *a, **k: [])
-    _patch_cli(monkeypatch, transport)
-
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 2
-    assert "risk-control ceiling" in captured.err
-    assert "re-run to resume" in captured.err
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[first.work_id]["status"] == "subtitle_done"
-    assert loaded[second.work_id]["status"] == "meta_ok"
-
-
 def test_cli_asr_missing_optional_asr_exits_1_non_archived(
     tmp_root, monkeypatch, capsys
 ):
@@ -215,7 +211,7 @@ def test_cli_asr_missing_optional_asr_exits_1_non_archived(
     _patch_cli(monkeypatch)
     monkeypatch.setattr(bc, "build_default_transport", _audio_transport)
 
-    assert main(["harvest-subs", "--archive-root", tmp_root]) == 0
+    assert _legacy_subtitle_state(tmp_root, identity, _audio_transport()) == "needs_audio"
     capsys.readouterr()
     assert main(["download-audio", "--missing-subs", "--archive-root", tmp_root]) == 0
     capsys.readouterr()
@@ -250,7 +246,10 @@ def test_cli_asr_rerun_idempotent_leaves_unrelated_rows(
     )
     _patch_cli(monkeypatch, _subtitle_transport())
 
-    assert main(["harvest-subs", "--archive-root", tmp_root]) == 0
+    assert (
+        _legacy_subtitle_state(tmp_root, target, _subtitle_transport())
+        == "subtitle_done"
+    )
     capsys.readouterr()
     assert main(["asr", "--pending", "--archive-root", tmp_root]) == 0
     capsys.readouterr()
diff --git a/bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py b/bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py
new file mode 100644
index 0000000..b256504
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_live_subtitle_cli_smoke.py
@@ -0,0 +1,1303 @@
+"""Opt-in bounded live smoke: one real part through the shipped subtitle CLI.
+
+This module holds the only networked test of the ``probe-subs`` /
+``harvest-subs`` pair — the operator-visible CLI + storage chain.  It drives the
+real user-facing command path (``bili_asr.cli.main`` with plain argv, the real
+``BilibiliApiGateway`` adapter over the pinned ``bilibili-api-python``
+distribution, and the real SQLite transcript repository) for exactly one public
+part inside a temporary archive root.  No playback, download, audio, or ASR code
+is invoked, and nothing outside the temporary root is written.
+
+The part the smoke probes is authored into its own temporary root, because both
+commands address parts the archive already stores: ``harvest-subs`` never
+fetches a pagelist and never calls upstream for a part that is not in the
+database, so a live run needs a ``video_parts`` row before it can do anything.
+The seeded identity is the fixed public sample (:data:`SAMPLE_BVID` /
+:data:`SAMPLE_CID` / :data:`SAMPLE_PAGE_INDEX`) — one part of the archive
+owner's own public collection, fetched live by the gateway plan's probe
+(``tests/test_live_subtitle_smoke.py``) and therefore already known to expose a
+visible machine caption on this endpoint.  Only the identity is real and it is
+used verbatim; the surrounding rows the storage layer requires (user, video,
+part title and duration) are inert scaffolding that no subtitle code path reads.
+The evidence line names the seeded part and its ``part_source=fixed-sample``
+provenance, so the operator can always see which part answered.
+
+The two commands run in order, and each costs one bounded live surface: the
+probe one track listing, the harvest one listing plus one document fetch when a
+track is visible.  Default pytest runs skip the smoke; it executes only when the
+operator sets ``BILI_LIVE_SMOKE=1``.  An opted-in run without the pinned
+distribution fails loudly.  Its documented bounded outcomes are:
+
+- **stored** — the part exposes a track and the harvest stores version 1: the
+  smoke asserts the normalized ``transcripts``/``transcript_segments`` rows, the
+  run and attempt evidence, that the part left the pending enumeration, that the
+  credential presence the run row records matches the environment, and that
+  nothing but ``archive.db`` and the writer lock appeared under the root.  This
+  is the acceptance-carrying outcome;
+- **no subtitle visible now** (``tracks=0``, then ``no-subtitle`` with exit 0) —
+  a legitimate bounded observation, recorded with the printed counts and never
+  as "this video has no captions".  The run stored nothing, so it skips instead
+  of reading green;
+- **the listing answers the bounded ``not_found`` code** — the part is one
+  upstream no longer serves, or one the credential in effect cannot see.  The
+  probe prints ``failed not_found`` (an all-failed probe exits 2) because it
+  obtained no listing at all, while a harvest records the same answer as
+  ``no-subtitle`` and exits 0: both readings are the shipped contract.  The
+  smoke records the reading the probe produced and does not spend the harvest's
+  calls on a part whose listing nothing answered;
+- **upstream risk control refuses the locked call shape** (``rate_limited``) —
+  the plan's recorded bounded blocker, reported as a skip carrying the bounded
+  code, because the locked shape must not be bent to make the call pass;
+- **every other bounded code** — ``transport_error`` from a dead proxy,
+  ``response_error``, ``shape_error``, anything unrecognized — fails loudly,
+  because those mean the environment or the adapter regressed rather than
+  upstream refusing the call.
+
+Every branch of that ladder is rehearsed offline in this module — the seeding
+and its read-only sanity check, both output readers, the row assertions, and
+the bounded-code refusal ladder — so a default (offline, non-opted-in) run
+exercises the whole control flow; only the live calls themselves are live.  The
+smoke adds no retry of its own: the shipped gateway is fail-fast per call, so a
+throttled endpoint is answered by waiting and re-running the command, never by
+bending the call shape or adding retries.
+
+Run it with::
+
+    CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
+    CHECKOUT=$CONTROL/bilibili-asr-archive         # or a feature worktree's package dir
+    cd "$CHECKOUT"
+    set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
+    export BILI_HTTP_PROXY=http://127.0.0.1:7890    # proxied host
+    BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \\
+      -m pytest tests/test_live_subtitle_cli_smoke.py -s -v
+"""
+
+from __future__ import annotations
+
+import importlib.metadata
+import os
+import re
+import sqlite3
+from contextlib import contextmanager
+from dataclasses import dataclass
+from typing import Iterator, NoReturn
+
+import pytest
+
+from bili_asr.cli import main
+from bili_asr.config import (
+    ARCHIVE_DATABASE_NAME,
+    SESSDATA_ENV_VAR,
+    redact_sessdata,
+    resolve_sessdata,
+)
+from bili_asr.services.subtitle_ingest import ProbeResult, SubtitleIngestor
+from bili_asr.sources.models import (
+    GatewayNotFound,
+    GatewayRateLimited,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage import MetadataRepository, open_database
+from bili_asr.storage.models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_CAPTION_SOURCE_KINDS,
+)
+from fixtures.fake_bilibili_gateway import (
+    SESSDATA_BOUNDARY_VALUE,
+    FakeGateway,
+    assert_leaks_no_markers,
+    fake_gateway_seam,
+    persisted_row_text,
+)
+from fixtures.metadata_records import (
+    make_part_record,
+    make_user_record,
+    make_video_record,
+)
+
+PINNED_PACKAGE_DISTRIBUTION_NAME = "bilibili-api-python"
+PINNED_PACKAGE_VERSION = "17.4.2"
+
+#: The opt-in switch, shared with the metadata and gateway smokes: the smoke
+#: runs only when the operator sets it to ``1``.
+LIVE_SMOKE_ENV = "BILI_LIVE_SMOKE"
+
+#: The fixed public sample the smoke authors into its temporary root: one part
+#: of the archive owner's own public collection, fetched live by the gateway
+#: plan's probe (2026-09-11; first part of the first video of UID 23191782,
+#: ``ai-zh`` with 2913 segments).  A sample upstream has since removed surfaces
+#: as the bounded ``not_found`` answer and is replaceable in one line.
+SAMPLE_BVID = "BV1S8hA6MEvy"
+SAMPLE_CID = 41314223900
+SAMPLE_PAGE_INDEX = 0
+
+#: The ``bvid:pN`` identity both commands address, and the provenance token the
+#: evidence line records: the seeded part came from the fixed public sample, not
+#: from an operator archive.
+SAMPLE_WORK_ID = f"{SAMPLE_BVID}:p{SAMPLE_PAGE_INDEX}"
+PART_SOURCE = "fixed-sample"
+
+#: The one bound both commands run under: a single part, so the probe and the
+#: harvest cannot walk a backlog and the whole live surface stays countable.
+PART_LIMIT = 1
+
+#: The one file besides ``archive.db`` a harvest is expected to leave behind:
+#: ``harvest-subs`` is an archive-writer command, so it takes the shipped writer
+#: lock at :data:`ARCHIVE_WRITER_LOCK_PATH`.  ``probe-subs`` is deliberately not
+#: one and leaves nothing.
+ARCHIVE_WRITER_LOCK_PATH = os.path.join("coordinator", "archive-writer.lock")
+
+#: The bounded codes that are recorded as blocker evidence rather than failing
+#: the smoke.  ``rate_limited`` is an upstream refusal of the locked call shape;
+#: ``not_found`` is the bounded "nothing was visible for this part" answer the
+#: two commands deliberately read differently (the probe prints ``failed`` and
+#: can exit 2, the harvest records ``no-subtitle`` and exits 0).  The set is
+#: pinned from the documentation side by
+#: :func:`test_the_documented_bounded_codes_are_recorded`.
+RECORDED_BLOCKER_CODES = frozenset({"rate_limited", "not_found"})
+
+#: The legacy sidecars this path must never write.  The transcript projections
+#: (``subtitles/raw/``, ``transcripts/srt/``) need no separate assertion: the
+#: "nothing but the database and the lock" check fails on any extra file.
+LEGACY_SIDECAR_PATHS = (
+    os.path.join("manifest", "manifest.jsonl"),
+    "meta-cursor.json",
+    "run-ledger.jsonl",
+    "coordinator/attempts.jsonl",
+)
+
+#: The locked output shapes of section 2 of the CLI spec, as the readers below
+#: parse them.  A shape the implementation no longer prints fails here rather
+#: than passing unnoticed.
+_PROBE_TRACKS_LINE = re.compile(r"probe (?P<work_id>\S+) tracks=(?P<count>\d+)")
+_PROBE_FAILED_LINE = re.compile(r"probe (?P<work_id>\S+) failed (?P<code>\S+)")
+_PROBE_TRACK_LINE = re.compile(
+    r" {2}track (?P<language>\S+) (?P<kind>ai|cc) (?P<label>.*)"
+)
+_PROBE_ZERO_TRACK_MARKER = "  (no subtitles visible)"
+_PROBE_SUMMARY_LINE = re.compile(
+    r"probe-subs: probed=(?P<probed>\d+) with_tracks=(?P<with_tracks>\d+)"
+    r" without_tracks=(?P<without_tracks>\d+) failed=(?P<failed>\d+)"
+)
+_HARVEST_STORED_LINE = re.compile(
+    r"harvest (?P<work_id>\S+) (?P<outcome>stored|unchanged)"
+    r" (?P<source_kind>\S+) (?P<language>\S+) v(?P<version>\d+)"
+)
+_HARVEST_NO_SUBTITLE_LINE = re.compile(r"harvest (?P<work_id>\S+) no-subtitle")
+_HARVEST_FAILED_LINE = re.compile(r"harvest (?P<work_id>\S+) failed (?P<code>\S+)")
+_HARVEST_SUMMARY_LINE = re.compile(
+    r"harvest-subs: run_id=(?P<run_id>\S+) attempted=(?P<attempted>\d+)"
+    r" stored=(?P<stored>\d+) unchanged=(?P<unchanged>\d+)"
+    r" no-subtitle=(?P<no_subtitle>\d+) failed=(?P<failed>\d+)"
+    r" remaining_without_transcript=(?P<remaining>\d+)"
+)
+
+
+def _live_smoke_requested() -> bool:
+    """True only when the operator explicitly opts in via the environment."""
+
+    return os.environ.get(LIVE_SMOKE_ENV, "") == "1"
+
+
+def _pinned_package_version() -> str:
+    """Return the installed distribution version, or fail loudly.
+
+    Loud-fail guard (the metadata smoke's precedent): an opted-in smoke in an
+    environment without the pinned distribution fails loudly with install
+    guidance instead of silently skipping.
+    """
+
+    try:
+        return importlib.metadata.version(PINNED_PACKAGE_DISTRIBUTION_NAME)
+    except importlib.metadata.PackageNotFoundError as error:
+        pytest.fail(
+            "live subtitle CLI smoke was requested but"
+            f" {PINNED_PACKAGE_DISTRIBUTION_NAME} is not installed in this"
+            f" environment ({error}); install the pinned"
+            f" {PINNED_PACKAGE_DISTRIBUTION_NAME}=={PINNED_PACKAGE_VERSION}"
+            " (uv sync) first"
+        )
+
+
+def _credential_expectation() -> bool:
+    """Whether a credential is in effect for this run, by the shipped rule.
+
+    The smoke builds its own argv and passes no ``--sessdata`` flag, so the
+    environment variable is its only credential input — resolved through the
+    shipped helper, so a blank value means anonymous here exactly as it does in
+    the command.  Only presence is ever returned.
+    """
+
+    return resolve_sessdata(None, os.environ.get(SESSDATA_ENV_VAR)) is not None
+
+
+def _probe_argv(tmp_root: str) -> list[str]:
+    """The bounded ``probe-subs`` invocation: one part by the enumeration bound."""
+
+    return [
+        "probe-subs",
+        "--limit-parts",
+        str(PART_LIMIT),
+        "--archive-root",
+        tmp_root,
+    ]
+
+
+def _harvest_argv(tmp_root: str) -> list[str]:
+    """The bounded ``harvest-subs`` invocation: the same one-part selection."""
+
+    return [
+        "harvest-subs",
+        "--limit-parts",
+        str(PART_LIMIT),
+        "--archive-root",
+        tmp_root,
+    ]
+
+
+def _seed_probe_part(tmp_root: str) -> None:
+    """Author the one sample part into a fresh temporary archive root.
+
+    The two commands read their parts from ``video_parts`` and never fetch a
+    pagelist, so this is the smallest root a live subtitle run can be expressed
+    against: one user, the sample's video, and the one sample part, pending
+    (``metadata_collected``, no transcript).  The rows are written through the
+    shipped repository, so the seeded database is the schema the commands open —
+    not a hand-built one.
+    """
+
+    connection = open_database(tmp_root)
+    repository = MetadataRepository(connection)
+    try:
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            repository.upsert_video(
+                make_video_record(SAMPLE_BVID, aid=None, title="字幕冒烟样本")
+            )
+            repository.upsert_part(
+                make_part_record(
+                    SAMPLE_BVID,
+                    page_index=SAMPLE_PAGE_INDEX,
+                    cid=SAMPLE_CID,
+                    processing_status="metadata_collected",
+                )
+            )
+    finally:
+        connection.close()
+
+
+@dataclass(frozen=True, slots=True)
+class ProbeOutput:
+    """The bounded facts one ``probe-subs`` run prints for its single part."""
+
+    work_id: str
+    track_count: int | None
+    error_code: str | None
+    tracks: tuple[tuple[str, str], ...]
+    probed: int
+    with_tracks: int
+    without_tracks: int
+    failed: int
+
+
+@dataclass(frozen=True, slots=True)
+class HarvestOutput:
+    """The bounded facts one ``harvest-subs`` run prints for its single part."""
+
+    run_id: str
+    work_id: str
+    outcome: str
+    error_code: str | None
+    source_kind: str | None
+    language: str | None
+    version: int | None
+    attempted: int
+    stored: int
+    unchanged: int
+    no_subtitle: int
+    failed: int
+    remaining_without_transcript: int
+
+
+def _credential_label(expect_credential_present: bool) -> str:
+    """The presence token the command prints, from the shipped redaction helper."""
+
+    return redact_sessdata("present" if expect_credential_present else None)
+
+
+def _assert_credential_line(out: str, *, expect_credential_present: bool) -> list[str]:
+    """Assert the presence-only first line and return the remaining lines."""
+
+    lines = out.splitlines()
+    assert lines, "the command printed nothing"
+    assert lines[0] == f"sessdata: {_credential_label(expect_credential_present)}", (
+        lines[0]
+    )
+    return lines[1:]
+
+
+def _read_probe_output(out: str, *, expect_credential_present: bool) -> ProbeOutput:
+    """Assert the locked ``probe-subs`` shapes and read their bounded facts."""
+
+    body = _assert_credential_line(
+        out, expect_credential_present=expect_credential_present
+    )
+    assert body, "the probe printed no part line"
+    summary = _PROBE_SUMMARY_LINE.fullmatch(body[-1])
+    assert summary is not None, f"unexpected probe summary line: {body[-1]!r}"
+    assert int(summary["probed"]) == 1, "the smoke bounds the probe to one part"
+
+    part_lines = body[:-1]
+    failed_line = _PROBE_FAILED_LINE.fullmatch(part_lines[0])
+    if failed_line is not None:
+        assert len(part_lines) == 1, (
+            "a failed listing carries no track lines and no success marker"
+        )
+        work_id: str = failed_line["work_id"]
+        error_code: str | None = failed_line["code"]
+        track_count: int | None = None
+        tracks: tuple[tuple[str, str], ...] = ()
+    else:
+        tracks_line = _PROBE_TRACKS_LINE.fullmatch(part_lines[0])
+        assert tracks_line is not None, f"unexpected probe line: {part_lines[0]!r}"
+        work_id = tracks_line["work_id"]
+        error_code = None
+        track_count = int(tracks_line["count"])
+        track_lines = part_lines[1:]
+        if track_count == 0:
+            assert track_lines == [_PROBE_ZERO_TRACK_MARKER], (
+                "a zero-track part is printed with its explicit marker"
+            )
+            tracks = ()
+        else:
+            matches = [_PROBE_TRACK_LINE.fullmatch(line) for line in track_lines]
+            assert all(match is not None for match in matches), (
+                f"unexpected track line: {track_lines!r}"
+            )
+            assert len(matches) == track_count, "one track line per visible track"
+            tracks = tuple(
+                (match["language"], match["kind"]) for match in matches
+            )
+
+    assert work_id == SAMPLE_WORK_ID, (
+        f"the probe addressed {work_id!r}, not the part the smoke authored"
+    )
+    return ProbeOutput(
+        work_id=work_id,
+        track_count=track_count,
+        error_code=error_code,
+        tracks=tracks,
+        probed=int(summary["probed"]),
+        with_tracks=int(summary["with_tracks"]),
+        without_tracks=int(summary["without_tracks"]),
+        failed=int(summary["failed"]),
+    )
+
+
+def _read_harvest_output(
+    out: str, *, expect_credential_present: bool
+) -> HarvestOutput:
+    """Assert the locked ``harvest-subs`` shapes and read their bounded facts."""
+
+    body = _assert_credential_line(
+        out, expect_credential_present=expect_credential_present
+    )
+    assert len(body) == 2, (
+        "the one-part run prints one part line and one summary line"
+    )
+    part_line, summary_line = body
+    summary = _HARVEST_SUMMARY_LINE.fullmatch(summary_line)
+    assert summary is not None, f"unexpected harvest summary line: {summary_line!r}"
+    assert int(summary["attempted"]) == 1, "the smoke bounds the harvest to one part"
+
+    stored_line = _HARVEST_STORED_LINE.fullmatch(part_line)
+    no_subtitle_line = _HARVEST_NO_SUBTITLE_LINE.fullmatch(part_line)
+    failed_line = _HARVEST_FAILED_LINE.fullmatch(part_line)
+    matches = [
+        match
+        for match in (stored_line, no_subtitle_line, failed_line)
+        if match is not None
+    ]
+    assert len(matches) == 1, f"unexpected harvest part line: {part_line!r}"
+    match = matches[0]
+    groups = match.groupdict()
+
+    if stored_line is not None:
+        outcome: str = groups["outcome"]
+    elif no_subtitle_line is not None:
+        outcome = "no-subtitle"
+    else:
+        outcome = "failed"
+    assert groups["work_id"] == SAMPLE_WORK_ID, (
+        f"the harvest addressed {groups['work_id']!r}, not the part the smoke seeded"
+    )
+
+    return HarvestOutput(
+        run_id=summary["run_id"],
+        work_id=groups["work_id"],
+        outcome=outcome,
+        error_code=groups.get("code"),
+        source_kind=groups.get("source_kind"),
+        language=groups.get("language"),
+        version=(
+            int(groups["version"]) if groups.get("version") is not None else None
+        ),
+        attempted=int(summary["attempted"]),
+        stored=int(summary["stored"]),
+        unchanged=int(summary["unchanged"]),
+        no_subtitle=int(summary["no_subtitle"]),
+        failed=int(summary["failed"]),
+        remaining_without_transcript=int(summary["remaining"]),
+    )
+
+
+@contextmanager
+def _archive_connection(tmp_root: str) -> Iterator[sqlite3.Connection]:
+    """Read the archive database directly, without creating or migrating it."""
+
+    connection = sqlite3.connect(os.path.join(tmp_root, ARCHIVE_DATABASE_NAME))
+    connection.row_factory = sqlite3.Row
+    try:
+        yield connection
+    finally:
+        connection.close()
+
+
+def _archive_files(tmp_root: str) -> list[str]:
+    """Every file below the archive root, as sorted relative POSIX paths."""
+
+    return sorted(
+        os.path.relpath(os.path.join(directory, name), tmp_root).replace(
+            os.sep, "/"
+        )
+        for directory, _directories, names in os.walk(tmp_root)
+        for name in names
+    )
+
+
+def _assert_one_pending_part(connection: sqlite3.Connection) -> None:
+    """Assert the temporary root offers exactly the seeded part, pending.
+
+    Read-only, and checked before the harvest: the pending enumeration is what
+    ``--limit-parts 1`` selects from, so this is the check that the run about to
+    happen is the one the smoke means to make.
+    """
+
+    rows = list(
+        connection.execute("SELECT work_id, cid, attempted FROM v_pending_subtitles")
+    )
+    assert len(rows) == 1, (
+        f"the temporary root must offer exactly one pending part, got {len(rows)}"
+    )
+    row = rows[0]
+    assert (row["work_id"], row["cid"], row["attempted"]) == (
+        SAMPLE_WORK_ID,
+        SAMPLE_CID,
+        0,
+    ), "the pending part is the seeded sample, never attempted"
+
+
+def _assert_stored_rows(
+    connection: sqlite3.Connection, *, expect_credential_present: bool
+) -> str:
+    """Assert one bounded harvest stored one transcript version; render evidence.
+
+    Every fact asserted here is one the CLI contract promises about a storing
+    run: the normalized transcript row with an allowed caption source kind and
+    its language and version, its ordered segments, the one run row carrying the
+    operator's selector and the credential presence, the one attempt row
+    pointing at the stored transcript, and a part that left the pending
+    enumeration.  The returned line carries counts only: no segment text, no
+    upstream value, no credential.
+    """
+
+    transcripts = list(
+        connection.execute(
+            "SELECT t.transcript_id, t.source_kind, t.language, t.version,"
+            " t.content_sha256, t.model_id, vp.cid FROM transcripts AS t"
+            " JOIN video_parts AS vp ON vp.video_part_id = t.video_part_id"
+            " ORDER BY t.version"
+        )
+    )
+    assert len(transcripts) == 1, "one bounded part stores exactly one version"
+    transcript = transcripts[0]
+    assert transcript["cid"] == SAMPLE_CID
+    assert transcript["source_kind"] in ALLOWED_CAPTION_SOURCE_KINDS, (
+        f"unexpected source kind {transcript['source_kind']!r}"
+    )
+    assert transcript["language"], "a stored transcript names its language"
+    assert transcript["version"] == 1, "the first acquisition stores version 1"
+    assert len(transcript["content_sha256"]) == 64, "the content hash is recorded"
+
+    segments = list(
+        connection.execute(
+            "SELECT s.ordinal, s.start_ms, s.end_ms, s.text"
+            " FROM transcript_segments AS s WHERE s.transcript_id = ?"
+            " ORDER BY s.ordinal",
+            (transcript["transcript_id"],),
+        )
+    )
+    assert segments, "a stored caption carries at least one segment"
+    assert [segment["ordinal"] for segment in segments] == list(
+        range(len(segments))
+    ), "segments are stored in ordinal order"
+    starts = [segment["start_ms"] for segment in segments]
+    assert starts == sorted(starts), (
+        "the stored document's start timeline is non-decreasing"
+    )
+    assert all(
+        segment["end_ms"] > segment["start_ms"] and segment["text"].strip()
+        for segment in segments
+    ), "every stored segment is a non-empty interval"
+
+    runs = list(connection.execute("SELECT * FROM acquisition_runs"))
+    assert len(runs) == 1, "the bounded run opens exactly one run row"
+    run = runs[0]
+    assert (
+        run["kind"],
+        run["selector_kind"],
+        run["selector_target"],
+        run["requested_limit"],
+        run["credential_present"],
+        run["outcome"],
+    ) == (
+        "subtitle",
+        "pending",
+        None,
+        PART_LIMIT,
+        int(expect_credential_present),
+        "complete",
+    ), tuple(run)
+    assert run["finished_at"] is not None, "the run row is terminal"
+    assert run["kind"] in ALLOWED_ACQUISITION_KINDS
+
+    attempts = list(connection.execute("SELECT * FROM acquisition_attempts"))
+    assert len(attempts) == 1, "exactly one attempt row per attempted part"
+    attempt = attempts[0]
+    assert (attempt["outcome"], attempt["error_code"]) == ("stored", None)
+    assert attempt["transcript_id"] == transcript["transcript_id"]
+    assert attempt["finished_at"] is not None
+    assert attempt["run_id"] == run["run_id"]
+
+    assert (
+        connection.execute("SELECT COUNT(*) FROM v_pending_subtitles").fetchone()[0]
+        == 0
+    ), "a stored part leaves the pending enumeration"
+
+    return (
+        f"source_kind={transcript['source_kind']} language={transcript['language']}"
+        f" version={transcript['version']} segments={len(segments)}"
+        " transcripts=1 attempts=1 pending_after=0"
+    )
+
+
+def _assert_no_transcript_rows(
+    connection: sqlite3.Connection,
+    *,
+    outcome: str,
+    expect_credential_present: bool,
+) -> str:
+    """Assert a bounded run stored nothing and still kept honest evidence.
+
+    Both non-storing bounded outcomes land here: ``no-subtitle`` (nothing was
+    visible for the part) and ``failed`` (the bounded code is what the attempt
+    row carries).  The transcript tables stay empty, the one part stays in the
+    pending enumeration with its timestamped attempt evidence, and the run row is
+    terminal with the outcome derived from its attempts — so the run never reads
+    as a success it did not have.
+    """
+
+    assert outcome in ("no-subtitle", "failed")
+    assert (
+        connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
+    ), "a non-storing outcome writes no transcript"
+    assert (
+        connection.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0]
+        == 0
+    )
+
+    attempts = list(connection.execute("SELECT * FROM acquisition_attempts"))
+    assert len(attempts) == 1, "the attempt is still recorded as evidence"
+    attempt = attempts[0]
+    assert attempt["outcome"] == outcome
+    assert attempt["finished_at"] is not None
+    assert attempt["transcript_id"] is None
+    if outcome == "no-subtitle":
+        # Nothing visible is not a failure.  The bounded code is absent when the
+        # listing simply carried no track, and it is recorded as ``not_found``
+        # when upstream answered that code — the contract deliberately maps both
+        # readings onto ``no-subtitle`` rather than onto ``failed``.
+        assert attempt["error_code"] in (None, "not_found"), attempt["error_code"]
+    else:
+        assert attempt["error_code"], "a failed attempt carries its bounded code"
+
+    runs = list(connection.execute("SELECT * FROM acquisition_runs"))
+    assert len(runs) == 1
+    run = runs[0]
+    expected_run_outcome = "failed" if outcome == "failed" else "complete"
+    assert (run["outcome"], run["credential_present"]) == (
+        expected_run_outcome,
+        int(expect_credential_present),
+    ), tuple(run)
+    assert run["finished_at"] is not None
+
+    pending = list(connection.execute("SELECT work_id FROM v_pending_subtitles"))
+    assert [row["work_id"] for row in pending] == [SAMPLE_WORK_ID], (
+        "a part without a transcript stays eligible for a later attempt"
+    )
+
+    return f"outcome={outcome} transcripts=0 attempts=1 pending_after=1"
+
+
+def _assert_bounded_blocker_is_recordable(error_code: str, *, stage: str) -> None:
+    """Fail loudly unless this bounded code is a recordable bounded blocker.
+
+    ``rate_limited`` is upstream refusing the locked call shape and ``not_found``
+    is the bounded "nothing was visible for this part" answer; both are recorded
+    with the part that produced them and reported as a skip.  Every other code
+    means the environment or the adapter regressed — ``transport_error`` from a
+    dead proxy, ``response_error``, ``shape_error`` — so it must fail the smoke
+    instead of reading as an upstream refusal.
+    """
+
+    if error_code in RECORDED_BLOCKER_CODES:
+        return
+    pytest.fail(
+        f"the live subtitle CLI smoke ended in the bounded code {error_code!r}"
+        f" at stage {stage!r}, which the documentation does not enumerate as an"
+        " upstream refusal; it means the environment or the adapter regressed"
+        " (a dead proxy surfaces transport_error, a normalization regression"
+        " shape_error), so this run must not read as a recorded blocker"
+    )
+
+
+def _assert_root_holds_only_the_database_and_the_lock(tmp_root: str) -> None:
+    """Assert no sidecar, projection, or stray file survived the harvest.
+
+    ``harvest-subs`` is an archive-writer command, so it leaves the writer lock
+    behind; the probe is not one and creates no file at all.  Anything else — a
+    legacy sidecar, a ``subtitles/raw`` or ``transcripts/srt`` projection, any
+    unexpected file — fails here.
+    """
+
+    files = _archive_files(tmp_root)
+    assert files == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]), (
+        f"unexpected files under the archive root: {files}"
+    )
+    for sidecar in LEGACY_SIDECAR_PATHS:
+        assert sidecar not in files
+
+
+def _assert_no_credential_leak(credential: str | None, *texts: str) -> None:
+    """Assert the operator's credential value appears on no surface at all.
+
+    Deliberately an explicit ``raise`` rather than an ``assert`` on the value:
+    pytest renders both operands of a failing assertion, which would print the
+    very credential this check exists to keep out of every output — including
+    the smoke's own failure report.
+    """
+
+    if not credential:
+        return
+    for text in texts:
+        if credential in text:
+            raise AssertionError(
+                "the live subtitle CLI smoke carried the operator SESSDATA"
+                " value onto a surface; the value is not printed here on purpose"
+            )
+
+
+def _record_and_skip(outcome: str, *, detail: str) -> NoReturn:
+    """Record a bounded non-storing outcome and skip instead of reading green.
+
+    A run that obtained no transcript is real evidence about upstream, but it is
+    not the acquisition this smoke exists to carry, so it is reported as a skip
+    carrying the bounded facts already printed — never as a pass.
+    """
+
+    print(f"live subtitle CLI smoke evidence: {detail}")
+    pytest.skip(
+        f"the live subtitle CLI smoke obtained no transcript ({outcome}):"
+        f" {detail}. The bounded facts were asserted and printed above; this is"
+        " a recorded bounded observation, not a defect, and not a subtitle"
+        " acquisition — re-run when a caption is visible."
+    )
+
+
+def test_live_smoke_one_part_through_probe_and_harvest(
+    tmp_root: str,
+    capsys: pytest.CaptureFixture[str],
+) -> None:
+    """Opt-in live smoke: ONE real part through ``probe-subs`` and ``harvest-subs``.
+
+    Skipped unless the operator sets ``BILI_LIVE_SMOKE=1``.  The smoke authors
+    the fixed sample part into a temporary archive root, probes its subtitle
+    inventory through the real CLI in the locked call shape, harvests it, and
+    asserts the bounded facts the contract promises: the printed presence,
+    track, outcome and summary lines, the normalized transcript rows when a
+    caption was visible, and the archive root's file set.  A refused or
+    invisible listing is recorded as a bounded blocker; every other failure is
+    loud.
+    """
+
+    if not _live_smoke_requested():
+        pytest.skip(
+            f"live subtitle CLI smoke is opt-in: set {LIVE_SMOKE_ENV}=1 to"
+            " request it"
+        )
+
+    assert _pinned_package_version() == PINNED_PACKAGE_VERSION
+
+    credential = os.environ.get(SESSDATA_ENV_VAR)
+    expect_credential_present = _credential_expectation()
+    presence = _credential_label(expect_credential_present)
+    print(f"live subtitle CLI smoke environment: sessdata={presence}")
+    _seed_probe_part(tmp_root)
+    print(
+        "live subtitle CLI smoke part:"
+        f" part_source={PART_SOURCE} work_id={SAMPLE_WORK_ID}"
+    )
+    with _archive_connection(tmp_root) as connection:
+        _assert_one_pending_part(connection)
+
+    _flush_output(capsys)
+    probe_exit = main(_probe_argv(tmp_root))
+    probe_out, probe_err = capsys.readouterr()
+    probe = _read_probe_output(
+        probe_out, expect_credential_present=expect_credential_present
+    )
+    if probe.error_code is not None:
+        # Nothing answered the listing, so the harvest's calls would be spent on
+        # a part no listing exists for.  The probe's own reading is recorded
+        # instead — which is also the documented asymmetry: the same answer
+        # harvested is ``no-subtitle`` with exit 0.
+        assert probe_exit == 2, "an all-failed probe exits 2"
+        _assert_bounded_blocker_is_recordable(probe.error_code, stage="probe-subs")
+        _assert_no_credential_leak(credential, probe_out, probe_err)
+        _record_and_skip(
+            f"probe {probe.error_code}",
+            detail=(
+                f"part_source={PART_SOURCE} work_id={probe.work_id}"
+                f" sessdata={presence} probe_exit={probe_exit}"
+                f" probed={probe.probed} with_tracks={probe.with_tracks}"
+                f" without_tracks={probe.without_tracks} failed={probe.failed}"
+                f" error_code={probe.error_code} harvest=not_attempted"
+            ),
+        )
+    assert probe_exit == 0, f"a probe that ran exits 0 (stderr: {probe_err!r})"
+
+    harvest_exit = main(_harvest_argv(tmp_root))
+    harvest_out, harvest_err = capsys.readouterr()
+    harvest = _read_harvest_output(
+        harvest_out, expect_credential_present=expect_credential_present
+    )
+    assert_leaks_no_markers(harvest_out + harvest_err, context="live CLI output")
+    _assert_no_credential_leak(
+        credential, probe_out, probe_err, harvest_out, harvest_err
+    )
+
+    with _archive_connection(tmp_root) as connection:
+        persisted = persisted_row_text(connection)
+        if harvest.outcome in ("stored", "unchanged"):
+            assert harvest_exit == 0, harvest_err
+            assert (harvest.failed, harvest.no_subtitle) == (0, 0)
+            assert harvest.remaining_without_transcript == 0
+            evidence = _assert_stored_rows(
+                connection, expect_credential_present=expect_credential_present
+            )
+        else:
+            if harvest.outcome == "no-subtitle":
+                assert harvest_exit == 0, (
+                    "a run whose part had no visible caption still exits 0:"
+                    f" {harvest_err!r}"
+                )
+            else:
+                assert harvest_exit == 2, (
+                    f"a run that failed on every attempted part exits 2:"
+                    f" {harvest_err!r}"
+                )
+                _assert_bounded_blocker_is_recordable(
+                    harvest.error_code or "", stage="harvest-subs"
+                )
+            assert harvest.remaining_without_transcript == 1
+            evidence = _assert_no_transcript_rows(
+                connection,
+                outcome=harvest.outcome,
+                expect_credential_present=expect_credential_present,
+            )
+    _assert_no_credential_leak(credential, persisted)
+    _assert_root_holds_only_the_database_and_the_lock(tmp_root)
+
+    summary = (
+        f"part_source={PART_SOURCE} work_id={harvest.work_id}"
+        f" sessdata={presence} probe_exit={probe_exit} probed={probe.probed}"
+        f" with_tracks={probe.with_tracks} without_tracks={probe.without_tracks}"
+        f" probe_failed={probe.failed} track_count={probe.track_count}"
+        f" tracks={','.join(f'{lan}:{kind}' for lan, kind in probe.tracks) or 'none'}"
+        f" harvest_exit={harvest_exit} run_id={harvest.run_id}"
+        f" attempted={harvest.attempted} stored={harvest.stored}"
+        f" unchanged={harvest.unchanged} no_subtitle={harvest.no_subtitle}"
+        f" failed={harvest.failed}"
+        f" remaining_without_transcript={harvest.remaining_without_transcript}"
+        f" {evidence}"
+    )
+    if harvest.outcome not in ("stored", "unchanged"):
+        _record_and_skip(harvest.outcome, detail=summary)
+    print(f"live subtitle CLI smoke evidence: {summary}")
+
+
+# ------------------------------------------------------------- rehearsals
+#
+# The rehearsals below run in every default (offline) pytest run and cover the
+# smoke's own logic — the seeding, the readers, the row assertions, and the
+# bounded-code refusal ladder — through the real CLI over the shared fake
+# gateway seam.  A broken query or a loosened assertion therefore fails offline
+# instead of first surfacing during a live run.  No live behaviour is claimed
+# here, and no network call is made: the two commands run against the scripted
+# protocol double.
+
+
+@pytest.fixture
+def anonymous_environment(monkeypatch: pytest.MonkeyPatch):
+    """No credential in the environment for this rehearsal.
+
+    Requested explicitly rather than applied autouse: an autouse fixture would
+    also strip the operator's credential from the live smoke, which would then
+    run anonymously and could only ever observe "nothing visible".
+    """
+
+    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
+
+
+def _flush_output(capsys: pytest.CaptureFixture[str]) -> None:
+    """Drop everything captured so far, so the next read is the command's own.
+
+    The smoke prints its bounded preamble (environment, part provenance) before
+    it invokes the command; without this the readers would see those lines as
+    the command's first line.
+    """
+
+    capsys.readouterr()
+
+
+def _rehearsal_tracks() -> tuple[SubtitleTrack, ...]:
+    """The sample's inventory shape: one visible machine caption."""
+
+    return (
+        SubtitleTrack(language="ai-zh", label="自动生成", is_ai=True, track_id="1"),
+    )
+
+
+def _rehearsal_body() -> tuple[SubtitleSegment, ...]:
+    """One short caption document in the contract's segment shape."""
+
+    return (
+        SubtitleSegment(start_ms=0, end_ms=1_500, text="未明子"),
+        SubtitleSegment(start_ms=1_500, end_ms=2_600, text="讲座"),
+    )
+
+
+def test_seeding_authors_exactly_the_one_pending_sample_part(tmp_root: str) -> None:
+    """The temporary root the smoke builds is the one the bound selects from."""
+
+    _seed_probe_part(tmp_root)
+
+    with _archive_connection(tmp_root) as connection:
+        _assert_one_pending_part(connection)
+        assert (
+            connection.execute("SELECT COUNT(*) FROM video_parts").fetchone()[0] == 1
+        )
+
+
+def test_the_live_arguments_stay_bounded_to_one_part(tmp_root: str) -> None:
+    """Both commands carry the archive root and the one-part bound."""
+
+    assert _probe_argv(tmp_root) == [
+        "probe-subs",
+        "--limit-parts",
+        "1",
+        "--archive-root",
+        tmp_root,
+    ]
+    assert _harvest_argv(tmp_root) == [
+        "harvest-subs",
+        "--limit-parts",
+        "1",
+        "--archive-root",
+        tmp_root,
+    ]
+
+
+def test_the_live_smoke_switch_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
+    """Only the documented ``1`` opts the smoke in."""
+
+    monkeypatch.delenv(LIVE_SMOKE_ENV, raising=False)
+    assert _live_smoke_requested() is False
+    for value in ("", "0", "true", "yes", "2"):
+        monkeypatch.setenv(LIVE_SMOKE_ENV, value)
+        assert _live_smoke_requested() is False
+    monkeypatch.setenv(LIVE_SMOKE_ENV, "1")
+    assert _live_smoke_requested() is True
+
+
+def test_the_seeded_root_survives_the_probe_with_no_new_file(
+    tmp_root: str,
+    anonymous_environment,
+    capsys: pytest.CaptureFixture[str],
+    fake_gateway_seam: FakeGateway,
+) -> None:
+    """A probe over a seeded root writes nothing at all: no lock, no row.
+
+    The rehearsal also pins the reader against real command output and the
+    ``part_source``/``work_id`` provenance the live evidence line records.
+    """
+
+    _seed_probe_part(tmp_root)
+    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, _rehearsal_tracks())
+
+    assert main(_probe_argv(tmp_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+
+    probe = _read_probe_output(out, expect_credential_present=False)
+    assert (probe.work_id, probe.track_count, probe.tracks) == (
+        SAMPLE_WORK_ID,
+        1,
+        (("ai-zh", "ai"),),
+    )
+    assert (probe.probed, probe.with_tracks, probe.without_tracks, probe.failed) == (
+        1,
+        1,
+        0,
+        0,
+    )
+    assert fake_gateway_seam.listing_cids == [SAMPLE_CID]
+    assert fake_gateway_seam.body_cids == []
+    # Read-only means read-only: no writer lock, no run row, no file at all.
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+    with _archive_connection(tmp_root) as connection:
+        _assert_one_pending_part(connection)
+        assert (
+            connection.execute(
+                "SELECT COUNT(*) FROM acquisition_runs"
+            ).fetchone()[0]
+            == 0
+        )
+
+
+def test_the_seam_rehearsal_stores_a_transcript_and_passes_every_row_assertion(
+    tmp_root: str,
+    anonymous_environment,
+    capsys: pytest.CaptureFixture[str],
+    fake_gateway_seam: FakeGateway,
+) -> None:
+    """The acceptance path is driven offline: reader, rows, and root file set.
+
+    This is the rehearsal that keeps the live run honest: the real CLI stores a
+    transcript for the seeded part over the seam, and the live smoke's own
+    readers and row assertions are the ones that accept or reject it.
+    """
+
+    _seed_probe_part(tmp_root)
+    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, _rehearsal_tracks())
+    fake_gateway_seam.script_subtitle_segments(SAMPLE_CID, _rehearsal_body())
+
+    assert main(_harvest_argv(tmp_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+
+    harvest = _read_harvest_output(out, expect_credential_present=False)
+    assert (harvest.work_id, harvest.outcome) == (SAMPLE_WORK_ID, "stored")
+    assert (harvest.source_kind, harvest.language, harvest.version) == (
+        "subtitle-ai",
+        "ai-zh",
+        1,
+    )
+    assert (
+        harvest.attempted,
+        harvest.stored,
+        harvest.unchanged,
+        harvest.no_subtitle,
+        harvest.failed,
+        harvest.remaining_without_transcript,
+    ) == (1, 1, 0, 0, 0, 0)
+    assert harvest.run_id, "the summary names the persisted run"
+
+    with _archive_connection(tmp_root) as connection:
+        evidence = _assert_stored_rows(connection, expect_credential_present=False)
+        persisted = persisted_row_text(connection)
+    assert evidence == (
+        "source_kind=subtitle-ai language=ai-zh version=1 segments=2"
+        " transcripts=1 attempts=1 pending_after=0"
+    )
+    # Positive control: the rows the assertions accepted really carry the body,
+    # so the no-leak scans are not vacuous.
+    assert "未明子" in persisted
+    assert_leaks_no_markers(out + err, context="rehearsal stored output")
+    _assert_root_holds_only_the_database_and_the_lock(tmp_root)
+    for sidecar in LEGACY_SIDECAR_PATHS:
+        assert sidecar not in _archive_files(tmp_root)
+
+
+def test_a_captionless_part_is_recorded_and_never_reads_green(
+    tmp_root: str,
+    anonymous_environment,
+    capsys: pytest.CaptureFixture[str],
+    fake_gateway_seam: FakeGateway,
+) -> None:
+    """Nothing visible is a recorded observation with exit 0, not a pass.
+
+    The probe prints the zero-track part explicitly, the harvest records
+    ``no-subtitle`` and exits 0, and the part stays pending for a later attempt —
+    so the live smoke's captionless bracket is exercised end to end offline.
+    """
+
+    _seed_probe_part(tmp_root)
+    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, ())
+
+    assert main(_probe_argv(tmp_root)) == 0
+    probe_out, err = capsys.readouterr()
+    assert err == ""
+    probe = _read_probe_output(probe_out, expect_credential_present=False)
+    assert (probe.track_count, probe.tracks, probe.without_tracks) == (0, (), 1)
+
+    assert main(_harvest_argv(tmp_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    harvest = _read_harvest_output(out, expect_credential_present=False)
+    assert (harvest.outcome, harvest.error_code) == ("no-subtitle", None)
+    assert (
+        harvest.no_subtitle,
+        harvest.stored,
+        harvest.remaining_without_transcript,
+    ) == (1, 0, 1)
+
+    with _archive_connection(tmp_root) as connection:
+        evidence = _assert_no_transcript_rows(
+            connection,
+            outcome="no-subtitle",
+            expect_credential_present=False,
+        )
+    assert evidence == "outcome=no-subtitle transcripts=0 attempts=1 pending_after=1"
+    assert_leaks_no_markers(out + err, context="rehearsal captionless output")
+
+    with pytest.raises(pytest.skip.Exception):
+        _record_and_skip("no-subtitle", detail=evidence)
+
+
+def test_a_failed_harvest_is_recorded_with_its_bounded_code(
+    tmp_root: str,
+    anonymous_environment,
+    capsys: pytest.CaptureFixture[str],
+    fake_gateway_seam: FakeGateway,
+) -> None:
+    """The harvest's bounded-failure bracket: exit 2, code recorded, rows kept."""
+
+    _seed_probe_part(tmp_root)
+    fake_gateway_seam.script_subtitle_tracks(
+        SAMPLE_CID, GatewayRateLimited(detail="get_subtitle_tracks")
+    )
+
+    assert main(_harvest_argv(tmp_root)) == 2
+    out, err = capsys.readouterr()
+    assert err == ""
+    harvest = _read_harvest_output(out, expect_credential_present=False)
+    assert (harvest.outcome, harvest.error_code, harvest.failed) == (
+        "failed",
+        "rate_limited",
+        1,
+    )
+    _assert_bounded_blocker_is_recordable(harvest.error_code, stage="harvest-subs")
+
+    with _archive_connection(tmp_root) as connection:
+        evidence = _assert_no_transcript_rows(
+            connection, outcome="failed", expect_credential_present=False
+        )
+    assert evidence == "outcome=failed transcripts=0 attempts=1 pending_after=1"
+    assert_leaks_no_markers(out + err, context="rehearsal failed-harvest output")
+
+
+def test_a_refused_listing_is_read_from_the_probe_and_never_harvested(
+    tmp_root: str,
+    anonymous_environment,
+    capsys: pytest.CaptureFixture[str],
+    fake_gateway_seam: FakeGateway,
+) -> None:
+    """The bounded refusal branch: the probe's reading drives the smoke's stop.
+
+    Upstream refusing the listing means the harvest's calls would be spent on a
+    part nothing answered for, so the smoke records the probe's own bounded
+    reading and issues no harvest call at all.  The all-failed probe exit is 2,
+    while the same answer harvested is ``no-subtitle`` with exit 0 — the
+    documented asymmetry, asserted here on both sides.
+    """
+
+    _seed_probe_part(tmp_root)
+    fake_gateway_seam.script_subtitle_tracks(
+        SAMPLE_CID, GatewayRateLimited(detail="get_subtitle_tracks")
+    )
+
+    assert main(_probe_argv(tmp_root)) == 2
+    out, err = capsys.readouterr()
+    assert err == ""
+    probe = _read_probe_output(out, expect_credential_present=False)
+    assert (probe.error_code, probe.track_count, probe.tracks) == (
+        "rate_limited",
+        None,
+        (),
+    )
+    assert (probe.failed, probe.with_tracks, probe.without_tracks) == (1, 0, 0)
+    _assert_bounded_blocker_is_recordable(probe.error_code, stage="probe-subs")
+    detail = (
+        f"part_source={PART_SOURCE} work_id={probe.work_id}"
+        f" sessdata=absent probe_exit=2 probed={probe.probed}"
+        f" with_tracks={probe.with_tracks} without_tracks={probe.without_tracks}"
+        f" failed={probe.failed} error_code={probe.error_code}"
+        " harvest=not_attempted"
+    )
+    with pytest.raises(pytest.skip.Exception) as skipped:
+        _record_and_skip(f"probe {probe.error_code}", detail=detail)
+    assert detail in capsys.readouterr().out
+    assert "obtained no transcript" in str(skipped.value)
+    # No harvest call was made: only the listing was issued, and the root still
+    # holds nothing but the seeded database.
+    assert fake_gateway_seam.body_cids == []
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+
+    # The other half of the documented asymmetry: the same bounded answer
+    # harvested is ``no-subtitle`` with exit 0, not a failure.
+    refused_root = os.path.join(tmp_root, "refused")
+    os.makedirs(refused_root, exist_ok=True)
+    _seed_probe_part(refused_root)
+    fake_gateway_seam.script_subtitle_tracks(
+        SAMPLE_CID, GatewayNotFound(detail="get_subtitle_tracks")
+    )
+    assert main(_harvest_argv(refused_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    harvested = _read_harvest_output(out, expect_credential_present=False)
+    assert (harvested.outcome, harvested.error_code, harvested.no_subtitle) == (
+        "no-subtitle",
+        None,
+        1,
+    )
+    with _archive_connection(refused_root) as connection:
+        _assert_no_transcript_rows(
+            connection, outcome="no-subtitle", expect_credential_present=False
+        )
+
+
+@pytest.mark.parametrize("error_code", ["rate_limited", "not_found"])
+def test_the_documented_bounded_codes_are_recorded(error_code: str) -> None:
+    """The codes the operator documentation names are recorded, not loud.
+
+    The parameters are the literal codes the docs enumerate, deliberately not
+    derived from :data:`RECORDED_BLOCKER_CODES`: a set that drops or renames one
+    of them would otherwise shrink this test instead of failing it.
+    """
+
+    _assert_bounded_blocker_is_recordable(error_code, stage="rehearsal")
+
+
+@pytest.mark.parametrize(
+    "error_code",
+    ["transport_error", "response_error", "shape_error", "unknown_failure"],
+)
+def test_every_other_bounded_code_fails_loudly(error_code: str) -> None:
+    """A regression code fails the smoke instead of reading as a refusal."""
+
+    with pytest.raises(pytest.fail.Exception):
+        _assert_bounded_blocker_is_recordable(error_code, stage="rehearsal")
+
+
+def test_missing_pinned_distribution_fails_loudly(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """An opted-in smoke without the pin fails with guidance, not a skip."""
+
+    def missing_distribution(name: str) -> str:
+        raise importlib.metadata.PackageNotFoundError(name)
+
+    monkeypatch.setattr(importlib.metadata, "version", missing_distribution)
+
+    with pytest.raises(pytest.fail.Exception) as failure:
+        _pinned_package_version()
+
+    message = str(failure.value)
+    assert PINNED_PACKAGE_DISTRIBUTION_NAME in message
+    assert PINNED_PACKAGE_VERSION in message
+    assert "uv sync" in message
+
+
+def test_the_credential_expectation_follows_the_shipped_resolution_rule(
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """The smoke expects presence exactly as the command resolves it."""
+
+    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
+    assert _credential_expectation() is False
+    monkeypatch.setenv(SESSDATA_ENV_VAR, SESSDATA_BOUNDARY_VALUE)
+    assert _credential_expectation() is True
+    monkeypatch.setenv(SESSDATA_ENV_VAR, "")
+    assert _credential_expectation() is False
+
+
+def test_the_credential_leak_scan_is_silent_without_a_credential() -> None:
+    """No credential in play means nothing to scan, and no crash."""
+
+    _assert_no_credential_leak(None, "sessdata: absent\n")
+    _assert_no_credential_leak(SESSDATA_BOUNDARY_VALUE, "sessdata: absent\n")
+    with pytest.raises(AssertionError):
+        _assert_no_credential_leak(
+            SESSDATA_BOUNDARY_VALUE, f"sessdata: {SESSDATA_BOUNDARY_VALUE}"
+        )
+
+
+def test_probe_result_carries_the_credential_presence_the_cli_observed(
+    tmp_root: str,
+    capsys: pytest.CaptureFixture[str],
+    fake_gateway_seam: FakeGateway,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    """``ProbeResult.credential_present`` is pinned, not only the printed line.
+
+    The probe's printed ``sessdata:`` line is composed from the resolved
+    credential, while the service records its own ``credential_present``; those
+    two can drift, and the printed line alone cannot tell.  The real
+    ``SubtitleIngestor.probe`` is wrapped here — the returned result object is
+    the only place the service-side value is observable from the command path —
+    and every captured result is asserted against both the environment and the
+    line the same run printed.
+    """
+
+    monkeypatch.delenv(SESSDATA_ENV_VAR, raising=False)
+    _seed_probe_part(tmp_root)
+    fake_gateway_seam.script_subtitle_tracks(SAMPLE_CID, _rehearsal_tracks())
+    captured: list[ProbeResult] = []
+    real_probe = SubtitleIngestor.probe
+
+    def recording_probe(self, selection):
+        result = real_probe(self, selection)
+        captured.append(result)
+        return result
+
+    monkeypatch.setattr(SubtitleIngestor, "probe", recording_probe)
+
+    assert main(_probe_argv(tmp_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[0] == "sessdata: absent"
+    assert [result.credential_present for result in captured] == [False]
+    assert captured[0].parts and captured[0].parts[0].work_id == SAMPLE_WORK_ID
+
+    monkeypatch.setenv(SESSDATA_ENV_VAR, SESSDATA_BOUNDARY_VALUE)
+
+    assert main(_probe_argv(tmp_root)) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[0] == "sessdata: present"
+    assert [result.credential_present for result in captured] == [False, True]
+    # The value reached the adapter, and appears nowhere else.
+    assert fake_gateway_seam.sessdata == SESSDATA_BOUNDARY_VALUE
+    _assert_no_credential_leak(SESSDATA_BOUNDARY_VALUE, out + err)
diff --git a/bilibili-asr-archive/tests/test_mixed_outcome_contract.py b/bilibili-asr-archive/tests/test_mixed_outcome_contract.py
index 574d0c6..9ec1a30 100644
--- a/bilibili-asr-archive/tests/test_mixed_outcome_contract.py
+++ b/bilibili-asr-archive/tests/test_mixed_outcome_contract.py
@@ -206,78 +206,6 @@ def test_run_summary_locks_terminal_selectors_and_risk_precedence():
     assert risk_after_fail.fully_processed is False
 
 
-# ------------------------------------------------------------ harvest-subs
-
-def test_harvest_subs_mixed_success_and_api_failure_is_retryable(
-    tmp_root, monkeypatch, capsys,
-):
-    ok_id = page_identity("BVhOk", 0, 111, "p0")
-    fail_id = page_identity("BVhFail", 0, 222, "p0")
-    store = ManifestStore(root=tmp_root)
-    store.upsert(_row(fail_id, title="fail-first"))
-    store.upsert(_row(ok_id, title="then-ok"))
-    transport = CidRouterTransport(
-        {fail_id.cid: API_FAIL, ok_id.cid: player_ok([sub_entry()])},
-        routes=_base_routes(),
-    )
-    _patch_cli(monkeypatch, transport)
-
-    rc = main([
-        "harvest-subs", "--archive-root", tmp_root, "--sessdata", SECRET,
-    ])
-    captured = capsys.readouterr()
-    assert rc == 1
-    assert "1 subtitle_done" in captured.out
-    assert "1 failed" in captured.out
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[ok_id.work_id]["status"] == "subtitle_done"
-    assert os.path.isfile(os.path.join(tmp_root, loaded[ok_id.work_id]["srt_path"]))
-    assert loaded[fail_id.work_id]["status"] == "meta_ok"
-    assert loaded[fail_id.work_id]["last_api_error_code"] == -400
-    assert _ledger_records(tmp_root) == []
-    assert not os.path.exists(os.path.join(tmp_root, "coordinator", "attempts.jsonl"))
-    _assert_no_secrets(captured, tmp_root)
-
-    before = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 1
-    after = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    assert len(after) == len(before) + 1
-    assert after[-1]["params"]["cid"] == fail_id.cid
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[ok_id.work_id]["status"] == "subtitle_done"
-    assert loaded[fail_id.work_id]["status"] == "meta_ok"
-
-
-def test_harvest_subs_success_then_risk_exit_2_keeps_success(
-    tmp_root, monkeypatch, capsys,
-):
-    # harvest-subs walks ManifestStore insertion order (JSONL). work_id
-    # names also keep success first if todo is later sorted by work_id.
-    ok_id = page_identity("BVhAOk", 0, 111, "p0")
-    risk_id = page_identity("BVhZRisk", 0, 222, "p0")
-    store = ManifestStore(root=tmp_root)
-    store.upsert(_row(ok_id))
-    store.upsert(_row(risk_id))
-    transport = CidRouterTransport(
-        {ok_id.cid: player_ok([sub_entry()]), risk_id.cid: RISK},
-        routes=_base_routes(),
-    )
-    _patch_cli(monkeypatch, transport)
-
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    captured = capsys.readouterr()
-    assert rc == 2
-    assert "risk-control ceiling" in captured.err
-    assert "harvest-subs:" in captured.out
-    assert "1 subtitle_done" in captured.out
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[ok_id.work_id]["status"] == "subtitle_done"
-    assert loaded[risk_id.work_id]["status"] == "meta_ok"
-    _assert_no_secrets(captured, tmp_root)
-
-
 # ------------------------------------------------------------ download-audio
 
 def test_download_audio_mixed_success_and_api_failure_is_retryable(
diff --git a/bilibili-asr-archive/tests/test_page_pipeline.py b/bilibili-asr-archive/tests/test_page_pipeline.py
index 4a54e1a..37da69e 100644
--- a/bilibili-asr-archive/tests/test_page_pipeline.py
+++ b/bilibili-asr-archive/tests/test_page_pipeline.py
@@ -171,41 +171,6 @@ def test_download_pages_independent_status(tmp_root):
     assert play_cids == [111, 222]
 
 
-def test_cli_harvest_skips_unresolved_and_processes_other_page(
-    tmp_root, monkeypatch
-):
-    store = ManifestStore(root=tmp_root)
-    store.upsert({
-        "bvid": BVID, "status": "meta_ok", "title": "legacy",
-        "duration_s": 1, "pubdate": 1, "unresolved": True,
-        "unresolved_reason": "ambiguous_bare_bvid",
-        "excluded_from_page_processing": True,
-    })
-    ok = page_identity("BV1ok", 0, 333)
-    store.upsert({
-        "bvid": "BV1ok", "work_id": ok.work_id, "page_index": 0, "cid": 333,
-        "status": "meta_ok", "title": "ok", "duration_s": 1, "pubdate": 1,
-    })
-    transport = SubRouter({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
-    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[BVID]["unresolved"] is True
-    assert loaded[BVID]["status"] == "meta_ok"
-    assert "work_id" not in loaded[BVID]
-    assert loaded[ok.work_id]["status"] == "needs_audio"
-    player = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    assert len(player) == 1
-    assert player[0]["params"]["cid"] == 333
-
-
 def test_cli_download_skips_unresolved_and_processes_other_page(
     tmp_root, monkeypatch
 ):
@@ -265,25 +230,6 @@ def test_cli_download_audio_bvid_unresolved_stops(tmp_root, monkeypatch, capsys)
     assert not os.path.exists(os.path.join(tmp_root, "audio", f"{BVID}.p0.m4a"))
 
 
-def test_cli_harvest_subs_bvid_unresolved_stops(tmp_root, monkeypatch, capsys):
-    store = ManifestStore(root=tmp_root)
-    store.upsert({
-        "bvid": BVID, "status": "meta_ok", "title": "legacy",
-        "duration_s": 1, "pubdate": 1, "unresolved": True,
-        "unresolved_reason": "ambiguous_bare_bvid",
-        "excluded_from_page_processing": True,
-    })
-    monkeypatch.setattr(bc, "build_default_transport", lambda: SubRouter({}))
-    monkeypatch.setattr(bc, "default_sleeper", lambda _s=None: None)
-    rc = main(["harvest-subs", "--bvid", BVID, "--archive-root", tmp_root])
-    assert rc == 1
-    err = capsys.readouterr().err
-    assert "unresolved" in err
-    loaded = ManifestStore(root=tmp_root).load()
-    assert loaded[BVID]["unresolved"] is True
-    assert "work_id" not in loaded[BVID]
-
-
 def test_harvest_subtitle_str_skips_unresolved(tmp_root):
     store = ManifestStore(root=tmp_root)
     store.upsert({
diff --git a/bilibili-asr-archive/tests/test_persistence_scale.py b/bilibili-asr-archive/tests/test_persistence_scale.py
index c9186e0..65cdc4e 100644
--- a/bilibili-asr-archive/tests/test_persistence_scale.py
+++ b/bilibili-asr-archive/tests/test_persistence_scale.py
@@ -426,13 +426,15 @@ def test_cli_dispatch_locks_every_archive_mutation(
         "recover",
         "asr",
         "pilot",
-        "probe-subs",
         "harvest-subs",
         "download-audio",
         "run",
         "campaign",
         "schedule",
     }
+    # ``probe-subs`` reads the SQLite transcript path and writes nothing, so it
+    # is a reader like ``status``: no writer lock, no file, no new database.
+    assert "probe-subs" not in cli._ARCHIVE_WRITER_COMMANDS
 
     @contextmanager
     def busy_writer(_root):
diff --git a/bilibili-asr-archive/tests/test_subtitle_cli.py b/bilibili-asr-archive/tests/test_subtitle_cli.py
new file mode 100644
index 0000000..f3eed4a
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_subtitle_cli.py
@@ -0,0 +1,1074 @@
+"""Offline contract tests for the subtitle CLI (``probe-subs`` / ``harvest-subs``).
+
+Everything here is offline.  Both commands are driven end to end through
+``bili_asr.cli.main`` — argparse, the read-command database guard, the
+transcript-schema guard, ``TranscriptRepository``, the service, and the printed
+lines — against a temporary archive database and a scripted gateway double
+installed in place of the concrete adapter, so no network call and no package
+call is made.
+
+What is pinned: the locked ``probe`` / ``harvest`` / summary line shapes and the
+exit taxonomy (0 ran / 1 usage or configuration / 2 terminal), the selection
+preference (CC before AI inside a language family, exact ``--language`` match),
+the outcome mapping, the enumeration advancing across bounded runs, and the
+boundaries — neither command reads or writes a legacy sidecar or a transcript
+projection, ``probe-subs`` writes nothing at all and never creates the database,
+and no display path or stored row carries the credential.
+"""
+
+from __future__ import annotations
+
+from contextlib import contextmanager
+import os
+import sqlite3
+
+import pytest
+
+from bili_asr.cli import main
+from bili_asr.config import ARCHIVE_DATABASE_NAME
+from bili_asr.services.subtitle_ingest import (
+    language_family,
+    select_subtitle_track,
+)
+from bili_asr.sources.models import (
+    GatewayNotFound,
+    GatewayRateLimited,
+    GatewayResponseError,
+    GatewayShapeError,
+    GatewayTransportError,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage import MetadataRepository, open_database
+from bili_asr.storage.models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_CAPTION_SOURCE_KINDS,
+)
+from fixtures.fake_bilibili_gateway import (
+    SESSDATA_BOUNDARY_VALUE,
+    UPSTREAM_ERROR_TEXT,
+    FakeGateway,
+    assert_leaks_no_markers,
+    fake_gateway_seam,
+    persisted_row_text,
+)
+from fixtures.metadata_records import (
+    make_part_record,
+    make_user_record,
+    make_video_record,
+)
+from test_storage_schema import _write_pre_iteration_database
+
+BVID_A = "BV1SubA"
+BVID_B = "BV1SubB"
+
+#: One caption body of two segments, and a revised body of the same identity.
+BODY = (
+    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
+    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="第二句"),
+)
+CHANGED_BODY = (
+    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
+    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="改写后的第二句"),
+)
+
+#: The realistic caption inventory: the uploader track and the machine one for
+#: the same spoken language, plus one English uploader track.
+CC_ZH = SubtitleTrack(
+    language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
+)
+AI_ZH = SubtitleTrack(
+    language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
+)
+CC_EN = SubtitleTrack(
+    language="en-US", label="English", is_ai=False, track_id=None
+)
+
+#: The legacy sidecars and the transcript projections the subtitle path owns.
+LEGACY_SIDE_CAR_PATHS = (
+    "manifest/manifest.jsonl",
+    "meta-cursor.json",
+    "run-ledger.jsonl",
+    "coordinator/attempts.jsonl",
+)
+PROJECTION_PREFIXES = ("subtitles/raw/", "transcripts/srt/")
+#: ``harvest-subs`` is an archive-writer command, so the shipped lock is the one
+#: file besides the database it is expected to leave behind.
+ARCHIVE_WRITER_LOCK_PATH = "coordinator/archive-writer.lock"
+
+
+@pytest.fixture(autouse=True)
+def _anonymous_environment(monkeypatch: pytest.MonkeyPatch):
+    """No credential in the environment unless a test sets one explicitly."""
+
+    monkeypatch.delenv("BILI_SESSDATA", raising=False)
+
+
+@pytest.fixture
+def install_gateway(fake_gateway_seam: FakeGateway):
+    """Install one scripted gateway as the CLI's concrete adapter.
+
+    A part is addressed by its ``cid``: ``tracks`` scripts one inventory,
+    ``segments`` one body, and the two failure maps raise instead of answering,
+    all of them through the shared ``FakeGateway`` protocol double.  A call the
+    test did not script fails loudly rather than silently answering an empty
+    inventory, and every call is recorded on the double — ``listing_cids`` and
+    ``body_cids`` in issue order — so the enumeration order and "the body was
+    never fetched" are assertable.
+
+    The shared ``fake_gateway_seam`` fixture installs the double at the adapter
+    seam and records the credential the composition root handed it, which the
+    credential test pins.
+    """
+
+    def install(
+        *,
+        tracks: dict[int, tuple[SubtitleTrack, ...]] | None = None,
+        segments: dict[int, tuple[SubtitleSegment, ...]] | None = None,
+        listing_failures: dict[int, Exception] | None = None,
+        body_failures: dict[int, Exception] | None = None,
+    ) -> FakeGateway:
+        for cid, inventory in (tracks or {}).items():
+            fake_gateway_seam.script_subtitle_tracks(cid, inventory)
+        for cid, body in (segments or {}).items():
+            fake_gateway_seam.script_subtitle_segments(cid, body)
+        for cid, failure in (listing_failures or {}).items():
+            fake_gateway_seam.script_subtitle_tracks(cid, failure)
+        for cid, failure in (body_failures or {}).items():
+            fake_gateway_seam.script_subtitle_segments(cid, failure)
+        return fake_gateway_seam
+
+    return install
+
+
+def _seed_parts(root: str, parts: tuple[tuple[str, int, int], ...]) -> None:
+    """Create ``archive.db`` with one user, one video per bvid, and these parts.
+
+    ``parts`` is ``(bvid, page_index, cid)`` triples, so a test scripts its
+    answers by the part it means.
+    """
+
+    connection = open_database(root)
+    repository = MetadataRepository(connection)
+    try:
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            for bvid in dict.fromkeys(bvid for bvid, _page, _cid in parts):
+                repository.upsert_video(
+                    make_video_record(bvid, aid=None, title="字幕测试视频")
+                )
+            for bvid, page_index, cid in parts:
+                repository.upsert_part(
+                    make_part_record(
+                        bvid,
+                        page_index=page_index,
+                        cid=cid,
+                        processing_status="metadata_collected",
+                    )
+                )
+    finally:
+        connection.close()
+
+
+@contextmanager
+def _archive_connection(root: str):
+    """Read the archive database directly, without creating or migrating it."""
+
+    connection = sqlite3.connect(os.path.join(root, ARCHIVE_DATABASE_NAME))
+    connection.row_factory = sqlite3.Row
+    try:
+        yield connection
+    finally:
+        connection.close()
+
+
+def _archive_files(root: str) -> list[str]:
+    """Every file below the archive root, as sorted relative POSIX paths."""
+
+    return sorted(
+        os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
+        for directory, _directories, names in os.walk(root)
+        for name in names
+    )
+
+
+def _scalar(root: str, sql: str, parameters: tuple = ()):
+    """Read one scalar straight from the archive database."""
+
+    with _archive_connection(root) as connection:
+        return connection.execute(sql, parameters).fetchone()[0]
+
+
+def _exit_code(argv: list[str]) -> int:
+    """Return the command's exit code, argparse usage errors included.
+
+    ``_UsageErrorArgumentParser`` maps argparse's ``2`` onto ``1`` (and keeps
+    ``--help`` at ``0``) but still raises ``SystemExit`` for a malformed value,
+    which is the same process exit code an operator sees.
+    """
+
+    try:
+        return main(argv)
+    except SystemExit as exit_signal:
+        return int(exit_signal.code)
+
+
+# ------------------------------------------------------------------ usage
+
+@pytest.mark.parametrize(
+    "argv",
+    [
+        ["probe-subs"],
+        ["probe-subs", "--bvid", BVID_A, "--limit-parts", "1"],
+        ["probe-subs", "--limit-parts", "0"],
+        ["probe-subs", "--limit-parts", "-2"],
+        ["probe-subs", "--limit-parts", "not-a-number"],
+        ["harvest-subs"],
+        ["harvest-subs", "--bvid", BVID_A],
+        ["harvest-subs", "--limit-parts", "0"],
+        ["harvest-subs", "--limit-parts", "2", "--language", "ai-zh,"],
+        ["harvest-subs", "--limit-parts", "2", "--language", ""],
+    ],
+)
+def test_subtitle_usage_errors_exit_one_never_two(
+    tmp_root: str, capsys, argv: list[str]
+) -> None:
+    """Every usage/configuration error is exit 1 with nothing on stdout."""
+
+    assert _exit_code([*argv, "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err.strip()
+
+
+def test_probe_subs_requires_exactly_one_selector(tmp_root: str, capsys) -> None:
+    """Neither selector, and both selectors, are the same usage error."""
+
+    assert main(["probe-subs", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "exactly one of --bvid / --limit-parts" in captured.err
+
+    assert (
+        main(
+            [
+                "probe-subs",
+                "--bvid",
+                BVID_A,
+                "--limit-parts",
+                "1",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 1
+    )
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "exactly one of --bvid / --limit-parts" in captured.err
+
+
+def test_missing_database_on_both_commands_prints_the_shipped_line(
+    tmp_root: str, capsys
+) -> None:
+    """A missing database is the shipped read-command line, and nothing appears."""
+
+    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == (
+        f"probe-subs: no archive database at {tmp_root}; "
+        "run fetch-meta to create it\n"
+    )
+    # Read-only for real: no database, no writer lock, no file at all.
+    assert _archive_files(tmp_root) == []
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == (
+        f"harvest-subs: no archive database at {tmp_root}; "
+        "run fetch-meta to create it\n"
+    )
+    assert not os.path.exists(os.path.join(tmp_root, ARCHIVE_DATABASE_NAME))
+
+
+def test_probe_subs_creates_nothing_when_the_archive_root_is_absent(
+    tmp_root: str, capsys
+) -> None:
+    """A missing root is not created by a read command."""
+
+    root = os.path.join(tmp_root, "absent")
+    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "no archive database" in captured.err
+    assert not os.path.exists(root)
+
+
+def test_unknown_bvid_is_configuration_and_opens_no_run(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """A selector naming no stored part exits 1 before any upstream call."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--bvid",
+                "BV1Unknown",
+                "--limit-parts",
+                "5",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 1
+    )
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "unknown --bvid BV1Unknown" in captured.err
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0
+
+    assert main(["probe-subs", "--bvid", "BV1Unknown:p7", "--archive-root", tmp_root]) == 1
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert "unknown --bvid BV1Unknown:p7" in captured.err
+    assert gateway.listing_cids == []
+
+
+# ------------------------------------------------- selection preference
+
+@pytest.mark.parametrize(
+    ("language", "is_ai", "expected"),
+    [
+        ("zh-CN", False, "zh"),
+        ("zh-Hans", False, "zh"),
+        ("zh-Hant", False, "zh"),
+        ("ai-zh", True, "zh"),
+        ("AI-ZH", True, "zh"),
+        ("ai-en", True, "en"),
+        ("en-US", False, "en"),
+        ("ja", False, "ja"),
+        (" pt-BR ", False, "pt"),
+    ],
+)
+def test_language_family_derivation(
+    language: str, is_ai: bool, expected: str
+) -> None:
+    """The family is the lowercase primary subtag, ``ai-`` stripped for AI."""
+
+    assert language_family(language, is_ai) == expected
+
+
+@pytest.mark.parametrize("cc_language", ["zh-CN", "zh-Hans", "zh-Hant", "zh"])
+@pytest.mark.parametrize("ai_language", ["ai-zh", "ai-ZH"])
+@pytest.mark.parametrize("ai_first", [True, False])
+def test_default_preference_picks_the_uploader_caption_for_chinese_pairs(
+    cc_language: str, ai_language: str, ai_first: bool
+) -> None:
+    """For any Chinese CC/AI code pair, in either upstream order, CC wins."""
+
+    uploader = SubtitleTrack(
+        language=cc_language, label="中文（简体）", is_ai=False, track_id=None
+    )
+    machine = SubtitleTrack(
+        language=ai_language, label="中文（自动生成）", is_ai=True, track_id="1"
+    )
+    tracks = (machine, uploader) if ai_first else (uploader, machine)
+
+    assert select_subtitle_track(tracks) is uploader
+
+
+def test_default_preference_ranks_known_families_then_falls_back_to_upstream_order() -> None:
+    """``zh`` outranks ``en``, both outrank the rest, and order settles ties."""
+
+    french = SubtitleTrack(language="fr", label="Français", is_ai=False, track_id=None)
+    english_ai = SubtitleTrack(
+        language="ai-en", label="English (auto)", is_ai=True, track_id="2"
+    )
+    chinese_ai = SubtitleTrack(
+        language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
+    )
+    tr_chinese = SubtitleTrack(
+        language="zh-Hant", label="中文（繁體）", is_ai=False, track_id=None
+    )
+
+    assert select_subtitle_track((english_ai, french, chinese_ai)) is chinese_ai
+    assert select_subtitle_track((french, english_ai)) is english_ai
+    assert select_subtitle_track((french, tr_chinese)) is tr_chinese
+    # the family rank decides before the CC/AI split: zh still wins over en
+    assert select_subtitle_track((AI_ZH, CC_EN)) is AI_ZH
+    first_chinese = SubtitleTrack(
+        language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
+    )
+    assert select_subtitle_track((first_chinese, tr_chinese)) is first_chinese
+    assert select_subtitle_track(()) is None
+
+
+def test_explicit_language_matches_exactly_and_first_preference_wins() -> None:
+    """``--language`` order decides; a code nothing matches yields no track."""
+
+    assert select_subtitle_track((CC_ZH, AI_ZH), ("ai-zh",)) is AI_ZH
+    assert select_subtitle_track((AI_ZH, CC_ZH), ("zh-CN", "ai-zh")) is CC_ZH
+    assert select_subtitle_track((CC_ZH, AI_ZH), ("zh",)) is None
+    assert select_subtitle_track((), ("zh-CN",)) is None
+
+    ai_spelled_cc = SubtitleTrack(
+        language="zh-CN", label="中文（自动生成）", is_ai=True, track_id="1"
+    )
+    assert (
+        select_subtitle_track((ai_spelled_cc, CC_ZH), ("zh-CN",)) is CC_ZH
+    ), "inside one preference the uploader caption still wins"
+
+
+# ------------------------------------------------------- probe-subs output
+
+def test_probe_subs_prints_track_lines_the_zero_track_marker_and_the_summary(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """One ``probe`` line per selected part, in selection order, then the summary."""
+
+    _seed_parts(
+        tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201))
+    )
+    gateway = install_gateway(
+        tracks={101: (CC_ZH, AI_ZH), 102: ()},
+        listing_failures={201: GatewayResponseError(detail=UPSTREAM_ERROR_TEXT)},
+    )
+
+    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines() == [
+        "sessdata: absent",
+        f"probe {BVID_A}:p0 tracks=2",
+        "  track zh-CN cc 中文（简体）",
+        "  track ai-zh ai 中文（自动生成）",
+        f"probe {BVID_A}:p1 tracks=0",
+        "  (no subtitles visible)",
+        f"probe {BVID_B}:p0 failed response_error",
+        "probe-subs: probed=3 with_tracks=1 without_tracks=1 failed=1",
+    ]
+    assert_leaks_no_markers(captured.out + captured.err, context="probe output")
+
+    # Nothing was written and no body was fetched: a probe lists tracks only.
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+    assert gateway.body_cids == []
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_runs") == 0
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
+
+
+def test_probe_subs_exits_two_when_every_selected_part_failed(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """A whole-probe failure is the terminal code, with the count still printed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(listing_failures={101: GatewayRateLimited()})
+
+    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 2
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines() == [
+        "sessdata: absent",
+        f"probe {BVID_A}:p0 failed rate_limited",
+        "probe-subs: probed=1 with_tracks=0 without_tracks=0 failed=1",
+    ]
+
+
+def test_probe_subs_reports_an_empty_selection_as_zero_probed(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """No pending part is a completed read, not an error and not a stall."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    assert captured.out.splitlines() == [
+        "sessdata: absent",
+        "probe-subs: probed=0 with_tracks=0 without_tracks=0 failed=0",
+    ]
+    assert gateway.listing_cids == [101]
+
+
+# ----------------------------------------------------- harvest-subs output
+
+def test_harvest_subs_prints_every_outcome_and_the_complete_summary(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """One ``harvest`` line per attempted part, then all four counts and the run."""
+
+    _seed_parts(
+        tmp_root,
+        ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201), (BVID_B, 1, 202)),
+    )
+    install_gateway(
+        tracks={101: (CC_ZH, AI_ZH), 102: (CC_ZH,), 201: (), 202: (CC_ZH,)},
+        segments={101: BODY, 102: BODY},
+        body_failures={202: GatewayNotFound()},
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "4", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert_leaks_no_markers(captured.out + captured.err, context="harvest output")
+    lines = captured.out.splitlines()
+    assert lines[:5] == [
+        "sessdata: absent",
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1",
+        f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1",
+        f"harvest {BVID_B}:p0 no-subtitle",
+        f"harvest {BVID_B}:p1 no-subtitle",
+    ]
+    summary = lines[5]
+    assert summary.startswith("harvest-subs: run_id=")
+    assert "attempted=4 stored=2 unchanged=0 no-subtitle=2 failed=0" in summary
+    assert summary.endswith("remaining_without_transcript=2")
+    assert len(lines) == 6
+
+    with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT kind, selector_kind, selector_target, requested_limit,"
+            " credential_present, outcome, finished_at FROM acquisition_runs"
+        ).fetchone()
+        assert (
+            run["kind"],
+            run["selector_kind"],
+            run["selector_target"],
+            run["requested_limit"],
+        ) == ("subtitle", "pending", None, 4)
+        assert run["kind"] in ALLOWED_ACQUISITION_KINDS
+        assert run["credential_present"] == 0
+        assert run["outcome"] == "complete"
+        assert run["finished_at"] is not None
+        assert [
+            (row["outcome"], row["error_code"])
+            for row in connection.execute(
+                "SELECT outcome, error_code FROM acquisition_attempts"
+                " ORDER BY video_part_id"
+            )
+        ] == [
+            ("stored", None),
+            ("stored", None),
+            ("no-subtitle", None),
+            ("no-subtitle", "not_found"),
+        ]
+        stored = connection.execute(
+            "SELECT source_kind, language, version FROM transcripts"
+            " ORDER BY transcript_id"
+        ).fetchall()
+        assert [(row["source_kind"], row["language"], row["version"]) for row in stored] == [
+            ("subtitle-cc", "zh-CN", 1),
+            ("subtitle-cc", "zh-CN", 1),
+        ]
+        assert {row["source_kind"] for row in stored} <= ALLOWED_CAPTION_SOURCE_KINDS
+        assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 4
+        # every attempt carries its own timestamps, so a captionless part is
+        # timestamped evidence and never a success with empty content
+        assert connection.execute(
+            "SELECT COUNT(*) FROM acquisition_attempts"
+            " WHERE outcome = 'no-subtitle'"
+            " AND started_at IS NOT NULL AND finished_at IS NOT NULL"
+        ).fetchone()[0] == 2
+
+
+def test_default_preference_stores_the_uploader_caption_when_both_are_visible(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """The AI track is visible first upstream and the CC track is still selected."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(tracks={101: (AI_ZH, CC_ZH)}, segments={101: BODY})
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1"
+    )
+
+
+def test_language_preference_reaches_the_ai_track(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``--language`` overrides the default order by exact upstream code."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(tracks={101: (CC_ZH, AI_ZH)}, segments={101: BODY})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--limit-parts",
+                "1",
+                "--language",
+                "ai-zh, zh-CN",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 0
+    )
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-ai ai-zh v1"
+    )
+    with _archive_connection(tmp_root) as connection:
+        row = connection.execute(
+            "SELECT source_kind, language FROM transcripts"
+        ).fetchone()
+    assert (row["source_kind"], row["language"]) == ("subtitle-ai", "ai-zh")
+
+
+def test_unmatched_language_preference_is_no_subtitle_with_no_fetch(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Nothing usable *for the requested language* is no-subtitle, never failed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH, AI_ZH)})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--limit-parts",
+                "1",
+                "--language",
+                "ja",
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 0
+    )
+
+    captured = capsys.readouterr()
+    lines = captured.out.splitlines()
+    assert lines[1] == f"harvest {BVID_A}:p0 no-subtitle"
+    assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in lines[2]
+    assert gateway.body_cids == []
+    with _archive_connection(tmp_root) as connection:
+        attempt = connection.execute(
+            "SELECT outcome, error_code, transcript_id FROM acquisition_attempts"
+        ).fetchone()
+        assert (attempt["outcome"], attempt["error_code"]) == ("no-subtitle", None)
+        assert attempt["transcript_id"] is None
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs"
+        ).fetchone()[0] == "complete"
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
+
+
+def test_harvest_subs_reports_an_empty_pending_selection_as_complete(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``attempted=0`` is a completed bounded run, still with every count printed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    assert main(["harvest-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    lines = captured.out.splitlines()
+    assert lines[0] == "sessdata: absent"
+    assert "attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0" in lines[1]
+    assert lines[1].endswith("remaining_without_transcript=0")
+    assert gateway.listing_cids == [101]
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            row["outcome"]
+            for row in connection.execute(
+                "SELECT outcome FROM acquisition_runs ORDER BY started_at"
+            )
+        ] == ["complete", "complete"]
+
+
+# -------------------------------------------- enumeration and re-acquisition
+
+def test_explicit_bvid_selects_every_stored_part_including_a_stored_one(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """An explicit video selection re-checks stored parts and reports ``unchanged``."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201)))
+    gateway = install_gateway(
+        tracks={101: (CC_ZH,), 102: (CC_ZH,), 201: (CC_ZH,)},
+        segments={101: BODY, 102: BODY, 201: BODY},
+    )
+
+    assert (
+        main(
+            ["harvest-subs", "--bvid", BVID_A, "--limit-parts", "5",
+             "--archive-root", tmp_root]
+        )
+        == 0
+    )
+    capsys.readouterr()
+    assert gateway.listing_cids == [101, 102], "only that video's stored parts"
+
+    assert (
+        main(
+            ["harvest-subs", "--bvid", BVID_A, "--limit-parts", "5",
+             "--archive-root", tmp_root]
+        )
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1:3] == [
+        f"harvest {BVID_A}:p0 unchanged subtitle-cc zh-CN v1",
+        f"harvest {BVID_A}:p1 unchanged subtitle-cc zh-CN v1",
+    ]
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 2
+    with _archive_connection(tmp_root) as connection:
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs ORDER BY started_at DESC LIMIT 1"
+        ).fetchone()[0] == "complete"
+
+
+def test_a_single_named_part_needs_no_bound_and_records_its_selector(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``bvid:pN`` is bounded by construction; the run records what was named."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
+    gateway = install_gateway(tracks={102: (CC_ZH,)}, segments={102: BODY})
+
+    assert (
+        main(["harvest-subs", "--bvid", f"{BVID_A}:p1", "--archive-root", tmp_root])
+        == 0
+    )
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p1 stored subtitle-cc zh-CN v1"
+    )
+    assert gateway.listing_cids == [102]
+    with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT selector_kind, selector_target, requested_limit"
+            " FROM acquisition_runs"
+        ).fetchone()
+    assert (
+        run["selector_kind"],
+        run["selector_target"],
+        run["requested_limit"],
+    ) == ("bvid", f"{BVID_A}:p1", None)
+
+
+def test_bounded_pending_runs_advance_through_the_captionless_backlog(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Never-attempted parts come first; repeated runs rotate, never stall."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102), (BVID_B, 0, 201)))
+    gateway = install_gateway(tracks={101: (), 102: (), 201: ()})
+
+    attempted = []
+    for _run in range(4):
+        assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+        captured = capsys.readouterr()
+        assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in captured.out
+        attempted.append(gateway.listing_cids[-1])
+
+    assert attempted == [101, 102, 201, 101], (
+        "never-attempted parts first, then the oldest attempt"
+    )
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 4
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 0
+
+
+def test_unchanged_content_adds_no_version_and_changed_content_appends_one(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Re-acquisition is idempotent, and a revised body becomes the next version."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    assert (
+        main(["harvest-subs", "--bvid", f"{BVID_A}:p0", "--archive-root", tmp_root])
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 unchanged subtitle-cc zh-CN v1"
+    )
+
+    gateway.script_subtitle_segments(101, CHANGED_BODY)
+    assert (
+        main(["harvest-subs", "--bvid", f"{BVID_A}:p0", "--archive-root", tmp_root])
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v2"
+    )
+
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            row["version"]
+            for row in connection.execute(
+                "SELECT version FROM transcripts ORDER BY version"
+            )
+        ] == [1, 2]
+        assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcript_segments") == 4
+
+
+def test_a_part_without_a_caption_can_store_one_in_a_later_run(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """``no-subtitle`` is an observation at one attempt, never a terminal state."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: ()})
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == f"harvest {BVID_A}:p0 no-subtitle"
+    assert "remaining_without_transcript=1" in captured.out
+
+    # the caption appears upstream and the part is still part of the work set
+    gateway.script_subtitle_tracks(101, (CC_ZH,))
+    gateway.script_subtitle_segments(101, BODY)
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == (
+        f"harvest {BVID_A}:p0 stored subtitle-cc zh-CN v1"
+    )
+    assert "stored=1" in captured.out
+    assert "remaining_without_transcript=0" in captured.out
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            (row["outcome"], row["transcript_id"] is not None)
+            for row in connection.execute(
+                "SELECT outcome, transcript_id FROM acquisition_attempts"
+                " ORDER BY started_at, rowid"
+            )
+        ] == [("no-subtitle", False), ("stored", True)]
+
+
+# ------------------------------------------------------ outcome mapping
+
+@pytest.mark.parametrize(
+    "failure",
+    [
+        GatewayRateLimited(),
+        GatewayTransportError(),
+        GatewayResponseError(),
+        GatewayShapeError(),
+    ],
+    ids=lambda failure: failure.code,
+)
+def test_bounded_gateway_failures_map_to_failed_with_their_code(
+    tmp_root: str, capsys, install_gateway, failure: Exception
+) -> None:
+    """Every non-``not_found`` gateway failure is a bounded ``failed`` part."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
+    install_gateway(listing_failures={101: failure, 102: failure})
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 2
+
+    captured = capsys.readouterr()
+    assert (
+        f"harvest {BVID_A}:p0 failed {failure.code}"
+        in captured.out
+    )
+    assert "attempted=2 stored=0 unchanged=0 no-subtitle=0 failed=2" in captured.out
+    assert_leaks_no_markers(captured.out + captured.err, context="failed-part output")
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            (row["outcome"], row["error_code"], row["transcript_id"])
+            for row in connection.execute(
+                "SELECT outcome, error_code, transcript_id"
+                " FROM acquisition_attempts ORDER BY video_part_id"
+            )
+        ] == [("failed", failure.code, None), ("failed", failure.code, None)]
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs"
+        ).fetchone()[0] == "failed"
+
+
+@pytest.mark.parametrize("stage", ["listing", "body"])
+def test_not_found_is_recorded_no_subtitle_with_its_code(
+    tmp_root: str, capsys, install_gateway, stage: str
+) -> None:
+    """Upstream ``not_found`` is evidence without a caption, never a failure."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    script: dict = {"tracks": {101: (CC_ZH,)}, "segments": {101: BODY}}
+    script[f"{stage}_failures"] = {101: GatewayNotFound()}
+    install_gateway(**script)
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[1] == f"harvest {BVID_A}:p0 no-subtitle"
+    assert "stored=0 unchanged=0 no-subtitle=1 failed=0" in captured.out
+    with _archive_connection(tmp_root) as connection:
+        attempt = connection.execute(
+            "SELECT outcome, error_code, transcript_id FROM acquisition_attempts"
+        ).fetchone()
+    assert (attempt["outcome"], attempt["error_code"]) == ("no-subtitle", "not_found")
+    assert attempt["transcript_id"] is None
+
+
+def test_partial_failure_keeps_exit_zero_and_stays_visible_in_the_counts(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """One stored and one failed part is a partial run, not a terminal failure."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101), (BVID_A, 1, 102)))
+    install_gateway(
+        tracks={101: (CC_ZH,), 102: (CC_ZH,)},
+        segments={101: BODY},
+        listing_failures={102: GatewayRateLimited()},
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0
+
+    captured = capsys.readouterr()
+    assert "attempted=2 stored=1 unchanged=0 no-subtitle=0 failed=1" in captured.out
+    assert captured.out.splitlines()[2] == (
+        f"harvest {BVID_A}:p1 failed rate_limited"
+    )
+    with _archive_connection(tmp_root) as connection:
+        assert connection.execute(
+            "SELECT outcome FROM acquisition_runs"
+        ).fetchone()[0] == "partial"
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM transcripts") == 1
+
+
+def test_unexpected_error_exits_two_finishes_the_run_and_leaks_nothing(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Anything escaping the service is the fixed line, with the run closed."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(listing_failures={101: RuntimeError(UPSTREAM_ERROR_TEXT)})
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 2
+
+    captured = capsys.readouterr()
+    assert captured.out == ""
+    assert captured.err == "harvest-subs: unexpected error\n"
+    assert_leaks_no_markers(
+        captured.out + captured.err, context="unexpected-error output"
+    )
+    with _archive_connection(tmp_root) as connection:
+        run = connection.execute(
+            "SELECT outcome, finished_at FROM acquisition_runs"
+        ).fetchone()
+    assert run["outcome"] == "failed"
+    assert run["finished_at"] is not None
+    assert _scalar(tmp_root, "SELECT COUNT(*) FROM acquisition_attempts") == 0
+
+
+# --------------------------------------------------------- boundaries
+
+def test_credential_is_reported_as_presence_only(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """The value reaches the adapter and no output path or row ever shows it."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    gateway = install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+
+    assert (
+        main(
+            [
+                "harvest-subs",
+                "--limit-parts",
+                "1",
+                "--sessdata",
+                SESSDATA_BOUNDARY_VALUE,
+                "--archive-root",
+                tmp_root,
+            ]
+        )
+        == 0
+    )
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[0] == "sessdata: present"
+    assert SESSDATA_BOUNDARY_VALUE not in captured.out + captured.err
+    assert gateway.sessdata == SESSDATA_BOUNDARY_VALUE
+    with _archive_connection(tmp_root) as connection:
+        assert connection.execute(
+            "SELECT credential_present FROM acquisition_runs"
+        ).fetchone()[0] == 1
+        assert SESSDATA_BOUNDARY_VALUE not in persisted_row_text(connection)
+
+    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 0
+    captured = capsys.readouterr()
+    assert captured.out.splitlines()[0] == "sessdata: absent"
+
+
+def test_neither_command_writes_a_sidecar_or_a_transcript_projection(
+    tmp_root: str, capsys, install_gateway
+) -> None:
+    """Only ``archive.db`` (and the writer lock) appears under the archive root."""
+
+    _seed_parts(tmp_root, ((BVID_A, 0, 101),))
+    install_gateway(tracks={101: (CC_ZH,)}, segments={101: BODY})
+
+    assert main(["probe-subs", "--bvid", BVID_A, "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME], (
+        "a probe takes no writer lock and creates no file"
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+    files = _archive_files(tmp_root)
+    assert files == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH])
+    for sidecar in LEGACY_SIDE_CAR_PATHS:
+        assert sidecar not in files
+    for path in files:
+        assert not path.startswith(PROJECTION_PREFIXES)
+
+
+def test_both_commands_print_the_fixed_rebuild_line_for_a_legacy_database(
+    tmp_root: str, capsys
+) -> None:
+    """A pre-iteration database: both commands exit 1, the metadata path keeps working."""
+
+    database_path = os.path.join(tmp_root, ARCHIVE_DATABASE_NAME)
+    _write_pre_iteration_database(database_path)
+
+    for command, argv in (
+        (
+            "probe-subs",
+            ["probe-subs", "--bvid", "BV1Legacy", "--archive-root", tmp_root],
+        ),
+        (
+            "harvest-subs",
+            ["harvest-subs", "--bvid", "BV1Legacy:p0", "--archive-root", tmp_root],
+        ),
+    ):
+        assert main(argv) == 1
+        captured = capsys.readouterr()
+        assert captured.out == ""
+        assert captured.err == (
+            f"{command}: archive database predates the transcript schema; "
+            f"rebuild it (delete {database_path} and re-run fetch-meta)\n"
+        )
+
+    assert main(["status", "--archive-root", tmp_root]) == 0
+    assert capsys.readouterr().out.startswith("users: 1")
diff --git a/bilibili-asr-archive/tests/test_subtitle_e2e.py b/bilibili-asr-archive/tests/test_subtitle_e2e.py
new file mode 100644
index 0000000..c654a5c
--- /dev/null
+++ b/bilibili-asr-archive/tests/test_subtitle_e2e.py
@@ -0,0 +1,812 @@
+"""Offline subtitle end-to-end verification: CLI → service → repository → SQLite.
+
+Every test drives the real user-facing command path — ``bili_asr.cli.main`` with
+plain argv — over the shared ``FakeGateway`` protocol double from
+``tests/fixtures/``, installed in place of the concrete adapter at the gateway
+seam.  The whole subtitle stack therefore runs offline exactly as an operator
+runs it: argparse, the read-command database guard, the transcript-schema guard,
+``TranscriptRepository``, ``SubtitleIngestor``, the acquisition run/attempt
+records and the printed lines — with only the gateway boundary scripted.  (The
+adapter itself and the package seam below it are covered by the gateway plan's
+suite and the opt-in live smoke; this file is the deterministic evidence above
+that boundary.)
+
+What is pinned here:
+
+- one bounded harvest lands normalized ``transcripts``/``transcript_segments``
+  rows — language, ``source_kind``, version 1, the contract's content hash — with
+  their ``acquisition_runs``/``acquisition_attempts`` evidence;
+- re-acquiring the same part is content-idempotent: ``unchanged``, no new
+  version, no duplicated segments; a revised body appends version 2 while
+  version 1 stays readable through the repository;
+- a part with nothing visible and a part whose body fetch fails keep bounded
+  evidence rows, the run does not claim success for either of them, and the
+  partial failure stays visible in the printed counts with exit code 0;
+- the pending enumeration advances: a part left ``no-subtitle`` stores a
+  transcript in a later run, and a never-attempted part is attempted before a
+  previously attempted one;
+- every run summary prints all four outcome counts including zeros, the
+  persisted run id, credential presence and how many parts still lack a
+  transcript; a selection that resolved to nothing (``attempted=0``) exits 0;
+- ``probe-subs`` prints the locked ``probe``/``track``/``tracks=0`` lines and
+  writes nothing at all — no database, no run row, no file;
+- neither command leaves a legacy sidecar or a transcript projection in the
+  archive root, and no credential or raw upstream text reaches output or any
+  persisted row.
+"""
+
+from __future__ import annotations
+
+from contextlib import contextmanager
+import hashlib
+import json
+import os
+import sqlite3
+
+import pytest
+
+from bili_asr.cli import main
+from bili_asr.config import ARCHIVE_DATABASE_NAME
+from bili_asr.sources.models import (
+    GatewayRateLimited,
+    GatewayResponseError,
+    GatewayTransportError,
+    SubtitleSegment,
+    SubtitleTrack,
+)
+from bili_asr.storage import MetadataRepository, TranscriptRepository, open_database
+from bili_asr.storage.models import (
+    ALLOWED_ACQUISITION_KINDS,
+    ALLOWED_CAPTION_SOURCE_KINDS,
+)
+from fixtures.fake_bilibili_gateway import (
+    SESSDATA_BOUNDARY_VALUE,
+    UPSTREAM_ERROR_TEXT,
+    FakeGateway,
+    assert_leaks_no_markers,
+    fake_gateway_seam,
+    persisted_row_text,
+)
+from fixtures.metadata_records import (
+    make_part_record,
+    make_user_record,
+    make_video_record,
+)
+
+#: The one video the scripted parts belong to; each part is addressed by its own
+#: ``cid`` in the gateway script and by ``bvid:pN`` in the CLI vocabulary.
+BVID = "BV1SubE2e"
+CC_CID = 101
+AI_CID = 102
+CAPTIONLESS_CID = 201
+FAILING_CID = 202
+
+#: The realistic caption inventory: the uploader track and the machine one for
+#: the same spoken language, so the default preference has a real choice to make.
+CC_ZH = SubtitleTrack(
+    language="zh-CN", label="中文（简体）", is_ai=False, track_id=None
+)
+AI_ZH = SubtitleTrack(
+    language="ai-zh", label="中文（自动生成）", is_ai=True, track_id="1"
+)
+
+#: One uploader body, one machine body, and a revised uploader body of the same
+#: part/source/language identity.
+CC_BODY = (
+    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
+    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="第二句"),
+)
+AI_BODY = (SubtitleSegment(start_ms=0, end_ms=1_500, text="自动生成的一句"),)
+REVISED_CC_BODY = (
+    SubtitleSegment(start_ms=0, end_ms=1_200, text="第一句"),
+    SubtitleSegment(start_ms=1_200, end_ms=2_400, text="改写后的第二句"),
+)
+
+#: The legacy sidecars and the transcript projections the subtitle path owns.
+LEGACY_SIDE_CAR_PATHS = (
+    "manifest/manifest.jsonl",
+    "meta-cursor.json",
+    "run-ledger.jsonl",
+    "coordinator/attempts.jsonl",
+)
+PROJECTION_PREFIXES = ("subtitles/raw/", "transcripts/srt/")
+#: ``harvest-subs`` is an archive-writer command, so the shipped writer lock is
+#: the one file besides the database a harvest is expected to leave behind.
+ARCHIVE_WRITER_LOCK_PATH = "coordinator/archive-writer.lock"
+
+
+@pytest.fixture(autouse=True)
+def _anonymous_environment(monkeypatch: pytest.MonkeyPatch):
+    """No credential in the environment unless a test sets one explicitly."""
+
+    monkeypatch.delenv("BILI_SESSDATA", raising=False)
+
+
+def _seed_parts(root: str, parts: tuple[tuple[str, int, int], ...]) -> None:
+    """Create ``archive.db`` with one user, one video per bvid, and these parts.
+
+    ``parts`` is ``(bvid, page_index, cid)`` triples, so a test scripts its
+    gateway answers by the part it means.
+    """
+
+    connection = open_database(root)
+    repository = MetadataRepository(connection)
+    try:
+        with repository.transaction():
+            repository.upsert_user(make_user_record())
+            for bvid in dict.fromkeys(bvid for bvid, _page, _cid in parts):
+                repository.upsert_video(
+                    make_video_record(bvid, aid=None, title="字幕测试视频")
+                )
+            for bvid, page_index, cid in parts:
+                repository.upsert_part(
+                    make_part_record(
+                        bvid,
+                        page_index=page_index,
+                        cid=cid,
+                        processing_status="metadata_collected",
+                    )
+                )
+    finally:
+        connection.close()
+
+
+@contextmanager
+def _archive_connection(root: str):
+    """Read the archive database directly, without creating or migrating it."""
+
+    connection = sqlite3.connect(os.path.join(root, ARCHIVE_DATABASE_NAME))
+    connection.row_factory = sqlite3.Row
+    try:
+        yield connection
+    finally:
+        connection.close()
+
+
+def _archive_files(root: str) -> list[str]:
+    """Every file below the archive root, as sorted relative POSIX paths."""
+
+    return sorted(
+        os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
+        for directory, _directories, names in os.walk(root)
+        for name in names
+    )
+
+
+def _expected_content_sha256(body: tuple[SubtitleSegment, ...]) -> str:
+    """Compute the contract's content hash independently of the repository.
+
+    The storage contract digests the canonical segment JSON: the segment triples
+    in stored order, unescaped non-ASCII, no separator padding.  Recomputing it
+    here from the DTO restates the contract instead of reading its result back
+    out of the implementation.
+    """
+
+    canonical = json.dumps(
+        [[segment.start_ms, segment.end_ms, segment.text] for segment in body],
+        ensure_ascii=False,
+        separators=(",", ":"),
+    )
+    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
+
+
+def _part_ids(connection: sqlite3.Connection) -> dict[int, int]:
+    """Return every seeded part's ``video_part_id``, keyed by its ``cid``."""
+
+    return {
+        int(row["cid"]): int(row["video_part_id"])
+        for row in connection.execute("SELECT video_part_id, cid FROM video_parts")
+    }
+
+
+def _stored_versions(connection: sqlite3.Connection) -> list[tuple]:
+    """Return every transcript version with the identity it belongs to."""
+
+    return [
+        (
+            row["video_part_id"],
+            row["source_kind"],
+            row["language"],
+            row["model_id"],
+            row["version"],
+            row["content_sha256"],
+        )
+        for row in connection.execute(
+            "SELECT video_part_id, source_kind, language, model_id, version,"
+            " content_sha256 FROM transcripts ORDER BY video_part_id, version"
+        )
+    ]
+
+
+def _stored_segments(connection: sqlite3.Connection) -> list[tuple]:
+    """Return every stored segment row in version and ordinal order."""
+
+    return [
+        (
+            row["video_part_id"],
+            row["version"],
+            row["ordinal"],
+            row["start_ms"],
+            row["end_ms"],
+            row["text"],
+        )
+        for row in connection.execute(
+            "SELECT t.video_part_id, t.version, s.ordinal, s.start_ms, s.end_ms,"
+            " s.text FROM transcript_segments AS s"
+            " JOIN transcripts AS t ON t.transcript_id = s.transcript_id"
+            " ORDER BY t.video_part_id, t.version, s.ordinal"
+        )
+    ]
+
+
+def _attempt_rows(connection: sqlite3.Connection) -> list[tuple]:
+    """Return every attempt row in the order it was written."""
+
+    return [
+        (
+            row["video_part_id"],
+            row["outcome"],
+            row["error_code"],
+            row["transcript_id"],
+            row["started_at"],
+            row["finished_at"],
+            row["run_id"],
+        )
+        for row in connection.execute(
+            "SELECT * FROM acquisition_attempts ORDER BY rowid"
+        )
+    ]
+
+
+def _run_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
+    """Return every acquisition run in the order it was opened."""
+
+    return list(
+        connection.execute(
+            "SELECT * FROM acquisition_runs ORDER BY started_at, rowid"
+        )
+    )
+
+
+# ------------------------------------------------------ stored evidence
+
+def test_harvest_stores_normalized_rows_for_a_cc_and_an_ai_part(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """One bounded run lands both parts' versions, segments and run evidence.
+
+    The ``p0`` part exposes both a machine and an uploader track, so the default
+    preference has a real selection to make and keeps the uploader one; the
+    ``p1`` part exposes the machine track only.  Both ``source_kind`` values are
+    therefore exercised by real selections rather than by a scripted shortcut.
+    """
+
+    _seed_parts(tmp_root, ((BVID, 0, CC_CID), (BVID, 1, AI_CID)))
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (AI_ZH, CC_ZH))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+    fake_gateway_seam.script_subtitle_tracks(AI_CID, (AI_ZH,))
+    fake_gateway_seam.script_subtitle_segments(AI_CID, AI_BODY)
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0
+
+    out, err = capsys.readouterr()
+    assert err == ""
+    # Selection order is the pending enumeration's: page index ascending here.
+    assert fake_gateway_seam.listing_cids == [CC_CID, AI_CID]
+    assert fake_gateway_seam.body_cids == [CC_CID, AI_CID]
+
+    with _archive_connection(tmp_root) as connection:
+        part_ids = _part_ids(connection)
+        runs = _run_rows(connection)
+        assert len(runs) == 1
+        run = runs[0]
+        assert (
+            run["kind"],
+            run["kind"] in ALLOWED_ACQUISITION_KINDS,
+            run["selector_kind"],
+            run["selector_target"],
+            run["requested_limit"],
+            run["credential_present"],
+            run["outcome"],
+        ) == ("subtitle", True, "pending", None, 2, 0, "complete")
+        assert run["finished_at"] is not None
+
+        # The summary names the persisted run and every count, zeros included.
+        assert out.splitlines() == [
+            "sessdata: absent",
+            f"harvest {BVID}:p0 stored subtitle-cc zh-CN v1",
+            f"harvest {BVID}:p1 stored subtitle-ai ai-zh v1",
+            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=2"
+            " unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0",
+        ]
+
+        assert _stored_versions(connection) == [
+            (
+                part_ids[CC_CID],
+                "subtitle-cc",
+                "zh-CN",
+                None,
+                1,
+                _expected_content_sha256(CC_BODY),
+            ),
+            (
+                part_ids[AI_CID],
+                "subtitle-ai",
+                "ai-zh",
+                None,
+                1,
+                _expected_content_sha256(AI_BODY),
+            ),
+        ]
+        assert _stored_segments(connection) == [
+            (part_ids[CC_CID], 1, 0, 0, 1_200, "第一句"),
+            (part_ids[CC_CID], 1, 1, 1_200, 2_400, "第二句"),
+            (part_ids[AI_CID], 1, 0, 0, 1_500, "自动生成的一句"),
+        ]
+        assert {
+            row[1] for row in _stored_versions(connection)
+        } <= ALLOWED_CAPTION_SOURCE_KINDS
+
+        transcripts = {
+            (int(row["video_part_id"]), int(row["version"])): int(row["transcript_id"])
+            for row in connection.execute(
+                "SELECT transcript_id, video_part_id, version FROM transcripts"
+            )
+        }
+        attempts = _attempt_rows(connection)
+        assert [(attempt[0], attempt[1], attempt[2]) for attempt in attempts] == [
+            (part_ids[CC_CID], "stored", None),
+            (part_ids[AI_CID], "stored", None),
+        ]
+        assert [attempt[3] for attempt in attempts] == [
+            transcripts[(part_ids[CC_CID], 1)],
+            transcripts[(part_ids[AI_CID], 1)],
+        ]
+        for attempt in attempts:
+            # Each attempt is timestamped evidence inside its own run's lifetime
+            # (the stored clock is second-granular, so equal bounds are allowed).
+            assert attempt[6] == run["run_id"]
+            assert run["started_at"] <= attempt[4] <= attempt[5] <= run["finished_at"]
+        assert_leaks_no_markers(
+            persisted_row_text(connection), context="persisted transcript rows"
+        )
+
+
+def test_reacquiring_an_unchanged_caption_adds_no_version_and_no_segment(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """The operator's re-check path reports ``unchanged`` and rewrites nothing."""
+
+    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    # Re-checking the part upstream has not revised: explicit --bvid selection,
+    # which keeps parts that already hold a transcript (spec section 2.2).
+    assert (
+        main(
+            ["harvest-subs", "--bvid", BVID, "--limit-parts", "5",
+             "--archive-root", tmp_root]
+        )
+        == 0
+    )
+
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[1] == (
+        f"harvest {BVID}:p0 unchanged subtitle-cc zh-CN v1"
+    )
+    assert "attempted=1 stored=0 unchanged=1 no-subtitle=0 failed=0" in out
+    assert out.splitlines()[2].endswith("remaining_without_transcript=0")
+
+    with _archive_connection(tmp_root) as connection:
+        part_ids = _part_ids(connection)
+        versions = [
+            row["version"]
+            for row in connection.execute("SELECT version FROM transcripts")
+        ]
+        assert versions == [1]
+        assert _stored_versions(connection) == [
+            (
+                part_ids[CC_CID],
+                "subtitle-cc",
+                "zh-CN",
+                None,
+                1,
+                _expected_content_sha256(CC_BODY),
+            )
+        ]
+        assert _stored_segments(connection) == [
+            (part_ids[CC_CID], 1, 0, 0, 1_200, "第一句"),
+            (part_ids[CC_CID], 1, 1, 1_200, 2_400, "第二句"),
+        ]
+        # Both attempts point at the same single version: nothing was duplicated.
+        attempts = _attempt_rows(connection)
+        assert [(attempt[1], attempt[2]) for attempt in attempts] == [
+            ("stored", None),
+            ("unchanged", None),
+        ]
+        assert len({attempt[3] for attempt in attempts}) == 1
+        assert [row["outcome"] for row in _run_rows(connection)] == [
+            "complete",
+            "complete",
+        ]
+
+
+def test_a_revised_caption_appends_version_two_and_keeps_version_one_readable(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """A changed body is a new immutable version; the earlier one stays readable."""
+
+    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+
+    fake_gateway_seam.script_subtitle_segments(CC_CID, REVISED_CC_BODY)
+    assert (
+        main(
+            ["harvest-subs", "--bvid", f"{BVID}:p0", "--archive-root", tmp_root]
+        )
+        == 0
+    )
+
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[1] == f"harvest {BVID}:p0 stored subtitle-cc zh-CN v2"
+
+    with _archive_connection(tmp_root) as connection:
+        part_ids = _part_ids(connection)
+        versions = _stored_versions(connection)
+        assert [row[4] for row in versions] == [1, 2]
+        assert [row[5] for row in versions] == [
+            _expected_content_sha256(CC_BODY),
+            _expected_content_sha256(REVISED_CC_BODY),
+        ]
+        assert _stored_segments(connection) == [
+            (part_ids[CC_CID], 1, 0, 0, 1_200, "第一句"),
+            (part_ids[CC_CID], 1, 1, 1_200, 2_400, "第二句"),
+            (part_ids[CC_CID], 2, 0, 0, 1_200, "第一句"),
+            (part_ids[CC_CID], 2, 1, 1_200, 2_400, "改写后的第二句"),
+        ]
+
+    # Version 1 is still readable through the repository's own read path, where
+    # the "earlier versions stay readable" promise is made.
+    connection = open_database(tmp_root)
+    try:
+        repository = TranscriptRepository(connection)
+        part_id = _part_ids(connection)[CC_CID]
+        first = repository.read_transcript(part_id, "subtitle-cc", "zh-CN", 1)
+        latest = repository.read_transcript(part_id, "subtitle-cc", "zh-CN")
+    finally:
+        connection.close()
+    assert first is not None and latest is not None
+    assert (first.version, latest.version) == (1, 2)
+    assert first.content_sha256 == _expected_content_sha256(CC_BODY)
+    assert [
+        (segment.start_ms, segment.end_ms, segment.text) for segment in first.segments
+    ] == [
+        (0, 1_200, "第一句"),
+        (1_200, 2_400, "第二句"),
+    ]
+
+
+# ------------------------------------------- bounded evidence and progress
+
+def test_captionless_and_failing_parts_keep_bounded_evidence_and_exit_zero(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """Neither part claims success, and the partial failure stays in the counts."""
+
+    _seed_parts(tmp_root, ((BVID, 0, CAPTIONLESS_CID), (BVID, 1, FAILING_CID)))
+    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, ())
+    fake_gateway_seam.script_subtitle_tracks(FAILING_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(
+        FAILING_CID, GatewayRateLimited()
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0
+
+    out, err = capsys.readouterr()
+    assert err == ""
+    # A part whose listing is empty never reaches the body fetch at all.
+    assert fake_gateway_seam.listing_cids == [CAPTIONLESS_CID, FAILING_CID]
+    assert fake_gateway_seam.body_cids == [FAILING_CID]
+
+    with _archive_connection(tmp_root) as connection:
+        run = _run_rows(connection)[0]
+        assert out.splitlines() == [
+            "sessdata: absent",
+            f"harvest {BVID}:p0 no-subtitle",
+            f"harvest {BVID}:p1 failed rate_limited",
+            f"harvest-subs: run_id={run['run_id']} attempted=2 stored=0"
+            " unchanged=0 no-subtitle=1 failed=1 remaining_without_transcript=2",
+        ]
+        assert run["outcome"] == "partial"
+
+        part_ids = _part_ids(connection)
+        attempts = _attempt_rows(connection)
+        assert [
+            (attempt[0], attempt[1], attempt[2], attempt[3])
+            for attempt in attempts
+        ] == [
+            (part_ids[CAPTIONLESS_CID], "no-subtitle", None, None),
+            (part_ids[FAILING_CID], "failed", "rate_limited", None),
+        ]
+        for attempt in attempts:
+            assert attempt[6] == run["run_id"]
+            assert run["started_at"] <= attempt[4] <= attempt[5] <= run["finished_at"]
+        assert _stored_versions(connection) == []
+        assert _stored_segments(connection) == []
+
+
+def test_a_captionless_part_stores_one_later_and_never_attempted_parts_go_first(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """``no-subtitle`` is an observation, and a bounded run cannot stall on it."""
+
+    _seed_parts(tmp_root, ((BVID, 0, CAPTIONLESS_CID), (BVID, 1, CC_CID)))
+    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, ())
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+
+    # First bounded run: both parts are never attempted, page index decides.
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    first = capsys.readouterr()
+    assert first.out.splitlines()[1] == f"harvest {BVID}:p0 no-subtitle"
+    assert "attempted=1 stored=0 unchanged=0 no-subtitle=1 failed=0" in first.out
+    assert first.out.splitlines()[2].endswith("remaining_without_transcript=2")
+
+    # Second run: the never-attempted part goes before the attempted one.
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    second = capsys.readouterr()
+    assert second.out.splitlines()[1] == (
+        f"harvest {BVID}:p1 stored subtitle-cc zh-CN v1"
+    )
+    assert second.out.splitlines()[2].endswith("remaining_without_transcript=1")
+    assert fake_gateway_seam.listing_cids == [CAPTIONLESS_CID, CC_CID]
+
+    # The caption becomes visible upstream; the captionless part is still work.
+    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CAPTIONLESS_CID, CC_BODY)
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    third = capsys.readouterr()
+    assert third.out.splitlines()[1] == (
+        f"harvest {BVID}:p0 stored subtitle-cc zh-CN v1"
+    )
+    assert third.out.splitlines()[2].endswith("remaining_without_transcript=0")
+    assert fake_gateway_seam.listing_cids == [
+        CAPTIONLESS_CID,
+        CC_CID,
+        CAPTIONLESS_CID,
+    ]
+
+    with _archive_connection(tmp_root) as connection:
+        part_ids = _part_ids(connection)
+        assert [
+            (row[0], row[1], row[3] is not None)
+            for row in _attempt_rows(connection)
+        ] == [
+            (part_ids[CAPTIONLESS_CID], "no-subtitle", False),
+            (part_ids[CC_CID], "stored", True),
+            (part_ids[CAPTIONLESS_CID], "stored", True),
+        ]
+
+
+def test_the_summary_prints_every_count_and_an_empty_selection_exits_zero(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """All four counts appear, zeros included, and ``attempted=0`` is a success."""
+
+    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    first = capsys.readouterr()
+
+    # Nothing is pending any more: the bounded run is empty, not a stall.
+    assert main(["harvest-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+    second = capsys.readouterr()
+
+    with _archive_connection(tmp_root) as connection:
+        runs = _run_rows(connection)
+        assert len(runs) == 2
+        assert first.out.splitlines() == [
+            "sessdata: absent",
+            f"harvest {BVID}:p0 stored subtitle-cc zh-CN v1",
+            f"harvest-subs: run_id={runs[0]['run_id']} attempted=1 stored=1"
+            " unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0",
+        ]
+        assert second.out.splitlines() == [
+            "sessdata: absent",
+            f"harvest-subs: run_id={runs[1]['run_id']} attempted=0 stored=0"
+            " unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0",
+        ]
+        assert runs[0]["run_id"] != runs[1]["run_id"]
+        assert [run["outcome"] for run in runs] == ["complete", "complete"]
+        assert [run["credential_present"] for run in runs] == [0, 0]
+
+
+# ------------------------------------------------------------ probe surface
+
+def test_probe_subs_prints_the_locked_lines_and_leaves_nothing_behind(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """The probe reports tracks only and writes nothing — not even the database."""
+
+    # No database yet: the shipped read-command line, and no file is created.
+    assert main(["probe-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 1
+    out, err = capsys.readouterr()
+    assert out == ""
+    assert err == (
+        f"probe-subs: no archive database at {tmp_root}; "
+        "run fetch-meta to create it\n"
+    )
+    assert _archive_files(tmp_root) == []
+
+    _seed_parts(
+        tmp_root,
+        ((BVID, 0, CC_CID), (BVID, 1, CAPTIONLESS_CID), (BVID, 2, FAILING_CID)),
+    )
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH, AI_ZH))
+    fake_gateway_seam.script_subtitle_tracks(CAPTIONLESS_CID, ())
+    fake_gateway_seam.script_subtitle_tracks(FAILING_CID, GatewayResponseError())
+
+    assert main(["probe-subs", "--limit-parts", "3", "--archive-root", tmp_root]) == 0
+
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines() == [
+        "sessdata: absent",
+        f"probe {BVID}:p0 tracks=2",
+        "  track zh-CN cc 中文（简体）",
+        "  track ai-zh ai 中文（自动生成）",
+        f"probe {BVID}:p1 tracks=0",
+        "  (no subtitles visible)",
+        f"probe {BVID}:p2 failed response_error",
+        "probe-subs: probed=3 with_tracks=1 without_tracks=1 failed=1",
+    ]
+    # A probe lists tracks only, and writes no file at all: no writer lock, no
+    # database creation, no run, attempt, transcript or segment row.
+    assert fake_gateway_seam.body_cids == []
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME]
+    with _archive_connection(tmp_root) as connection:
+        for table in (
+            "acquisition_runs",
+            "acquisition_attempts",
+            "transcripts",
+            "transcript_segments",
+        ):
+            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
+            assert count == 0, f"{table} must stay empty"
+
+
+# --------------------------------------------------------- path boundaries
+
+def test_neither_command_leaves_a_sidecar_or_a_transcript_projection(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway
+) -> None:
+    """Only ``archive.db`` and the writer lock appear under the archive root."""
+
+    _seed_parts(tmp_root, ((BVID, 0, CC_CID),))
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+
+    assert main(["probe-subs", "--bvid", BVID, "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+    assert _archive_files(tmp_root) == [ARCHIVE_DATABASE_NAME], (
+        "a probe takes no writer lock and creates no file"
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    capsys.readouterr()
+    files = _archive_files(tmp_root)
+    assert files == sorted([ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH])
+    for sidecar in LEGACY_SIDE_CAR_PATHS:
+        assert sidecar not in files
+    for path in files:
+        assert not path.startswith(PROJECTION_PREFIXES)
+
+
+def test_no_credential_or_upstream_text_reaches_output_or_a_persisted_row(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway, monkeypatch
+) -> None:
+    """The credential stays presence-only and a body failure stays a code."""
+
+    monkeypatch.setenv("BILI_SESSDATA", SESSDATA_BOUNDARY_VALUE)
+    _seed_parts(tmp_root, ((BVID, 0, CC_CID), (BVID, 1, FAILING_CID)))
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+    fake_gateway_seam.script_subtitle_tracks(FAILING_CID, (CC_ZH,))
+    # The failure's detail carries every seam sentinel, so the scan below is not
+    # vacuous: this text really was in flight inside the run.
+    fake_gateway_seam.script_subtitle_segments(
+        FAILING_CID, GatewayTransportError(detail=UPSTREAM_ERROR_TEXT)
+    )
+
+    assert main(["harvest-subs", "--limit-parts", "2", "--archive-root", tmp_root]) == 0
+
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[0] == "sessdata: present"
+    assert out.splitlines()[2] == f"harvest {BVID}:p1 failed transport_error"
+    assert SESSDATA_BOUNDARY_VALUE not in out + err
+    assert UPSTREAM_ERROR_TEXT not in out + err
+    assert_leaks_no_markers(out + err, context="harvest output")
+
+    with _archive_connection(tmp_root) as connection:
+        persisted = persisted_row_text(connection)
+        # Positive control: the run really stored a normalized row, so the scan
+        # over the persisted text is not vacuous.
+        assert "subtitle-cc" in persisted and "第一句" in persisted
+        assert connection.execute(
+            "SELECT error_code FROM acquisition_attempts WHERE outcome = 'failed'"
+        ).fetchone()[0] == "transport_error"
+        assert_leaks_no_markers(persisted, context="persisted rows")
+
+
+# ------------------------------------------------- credential presence (env)
+
+def test_the_env_sourced_credential_is_reported_as_presence_and_composed_into_the_run_row(
+    tmp_root: str, capsys, fake_gateway_seam: FakeGateway, monkeypatch
+) -> None:
+    """``BILI_SESSDATA`` reaches the adapter and is recorded presence-only."""
+
+    _seed_parts(tmp_root, ((BVID, 0, CC_CID), (BVID, 1, AI_CID)))
+    fake_gateway_seam.script_subtitle_tracks(CC_CID, (CC_ZH,))
+    fake_gateway_seam.script_subtitle_segments(CC_CID, CC_BODY)
+    fake_gateway_seam.script_subtitle_tracks(AI_CID, (AI_ZH,))
+    fake_gateway_seam.script_subtitle_segments(AI_CID, AI_BODY)
+
+    monkeypatch.setenv("BILI_SESSDATA", SESSDATA_BOUNDARY_VALUE)
+    assert main(["harvest-subs", "--limit-parts", "1", "--archive-root", tmp_root]) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[0] == "sessdata: present"
+    assert SESSDATA_BOUNDARY_VALUE not in out + err
+    # The environment value, not a --sessdata flag, is what reached the adapter.
+    assert fake_gateway_seam.sessdata == SESSDATA_BOUNDARY_VALUE
+
+    monkeypatch.delenv("BILI_SESSDATA")
+    assert (
+        main(
+            ["harvest-subs", "--bvid", f"{BVID}:p1", "--archive-root", tmp_root]
+        )
+        == 0
+    )
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[0] == "sessdata: absent"
+    assert fake_gateway_seam.sessdata is None
+
+    with _archive_connection(tmp_root) as connection:
+        assert [
+            (row["credential_present"], row["selector_kind"], row["selector_target"])
+            for row in _run_rows(connection)
+        ] == [(1, "pending", None), (0, "bvid", f"{BVID}:p1")]
+        persisted = persisted_row_text(connection)
+        # Positive control: the credential-bearing runs really stored rows, so
+        # the scan over the persisted text is not vacuous.
+        assert "subtitle-cc" in persisted
+        assert_leaks_no_markers(
+            persisted, context="credential-bearing run rows"
+        )
+
+    # The read command reports the same presence and still writes nothing.
+    monkeypatch.setenv("BILI_SESSDATA", SESSDATA_BOUNDARY_VALUE)
+    assert main(["probe-subs", "--bvid", BVID, "--archive-root", tmp_root]) == 0
+    out, err = capsys.readouterr()
+    assert err == ""
+    assert out.splitlines()[0] == "sessdata: present"
+    assert SESSDATA_BOUNDARY_VALUE not in out + err
+    with _archive_connection(tmp_root) as connection:
+        assert len(_run_rows(connection)) == 2, "a probe opens no run"
+    assert _archive_files(tmp_root) == sorted(
+        [ARCHIVE_DATABASE_NAME, ARCHIVE_WRITER_LOCK_PATH]
+    )
diff --git a/bilibili-asr-archive/tests/test_subtitles.py b/bilibili-asr-archive/tests/test_subtitles.py
index d127213..8994408 100644
--- a/bilibili-asr-archive/tests/test_subtitles.py
+++ b/bilibili-asr-archive/tests/test_subtitles.py
@@ -1,15 +1,18 @@
-"""Unit tests for subtitle probe/harvest: mocked transport only, no network."""
+"""Unit tests for subtitle probe/harvest: mocked transport only, no network.
+
+The ``probe-subs`` / ``harvest-subs`` command surface moved to the SQLite
+transcript path and is covered by ``tests/test_subtitle_cli.py``; what stays
+here is the legacy client and harvest-helper layer that the untouched ASR,
+pilot, run, and coordinator paths still call.
+"""
 
 from __future__ import annotations
 
 import json
 import os
 
-import pytest
-
 from bili_asr import bili_client as bc
 from bili_asr import subtitles
-from bili_asr.cli import main
 from bili_asr.manifest import ManifestStore
 
 API = "https://api.bilibili.com"
@@ -259,235 +262,3 @@ def test_harvest_downloads_shortlived_url_same_run(tmp_root):
     manifest_text = open(store.path, encoding="utf-8").read()
     assert "hdslb" not in manifest_text
     assert "subtitle_url" not in manifest_text
-
-
-# ---------------------------------------------------------------- CLI
-
-def _cli_routes(monkeypatch, transport):
-    monkeypatch.setattr(bc, "build_default_transport", lambda: transport)
-    monkeypatch.setattr(bc, "default_sleeper", lambda: FastSleeper())
-
-
-def test_cli_probe_subs_empty(tmp_root, monkeypatch, capsys):
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["probe-subs", "--bvid", "BV1mk8W6dEyx",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "no subtitles" in out
-    assert "needs_audio" in out
-
-
-def test_cli_probe_subs_unknown_bvid_api_error_does_not_create_row(
-    tmp_root, monkeypatch, capsys
-):
-    sentinel_cookie = "PROBE-SESSDATA-SECRET"
-    monkeypatch.setenv("BILI_SESSDATA", sentinel_cookie)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "pagelist": [(200, {"code": -99999})],
-    })
-    _cli_routes(monkeypatch, transport)
-
-    rc = main([
-        "probe-subs", "--bvid", "BV1unknown",
-        "--archive-root", tmp_root,
-    ])
-
-    assert rc == 1
-    assert ManifestStore(root=tmp_root).get("BV1unknown") is None
-    assert not os.path.exists(ManifestStore(root=tmp_root).path)
-    captured = capsys.readouterr()
-    output = captured.out + captured.err
-    assert sentinel_cookie not in output
-    assert "http" not in output.lower()
-
-
-def test_cli_probe_subs_transport_error_redacts_exception_message(
-    tmp_root, monkeypatch, capsys
-):
-    sentinel = "SESSDATA=PROBE-SECRET https://cdn.example/sub.json?token=SIGNED"
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "pagelist": [RuntimeError(sentinel)] * 5,
-    })
-    _cli_routes(monkeypatch, transport)
-
-    rc = main([
-        "probe-subs", "--bvid", "BV1transport",
-        "--archive-root", tmp_root,
-    ])
-
-    assert rc == 2
-    captured = capsys.readouterr()
-    output = captured.out + captured.err
-    assert "RuntimeError" in output
-    assert "PROBE-SECRET" not in output
-    assert "SIGNED" not in output
-    assert not os.path.exists(ManifestStore(root=tmp_root).path)
-
-
-def test_cli_probe_subs_lists_entries(tmp_root, monkeypatch, capsys):
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["probe-subs", "--bvid", "BV1mk8W6dEyx",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    out = capsys.readouterr().out
-    assert "ai-zh" in out
-
-
-def test_cli_harvest_subs_marks_needs_audio(tmp_root, monkeypatch, capsys):
-    manifest_with(tmp_root)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    store = ManifestStore(root=tmp_root)
-    assert store.get("BV1test00:p0")["status"] == "needs_audio"
-    out = capsys.readouterr().out
-    assert "needs_audio" in out
-
-
-def test_cli_harvest_subs_downloads_and_marks_done(tmp_root, monkeypatch):
-    manifest_with(tmp_root)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    store = ManifestStore(root=tmp_root)
-    assert store.get("BV1test00:p0")["status"] == "subtitle_done"
-    assert os.path.exists(
-        os.path.join(tmp_root, "transcripts", "srt", "BV1test00.p0.srt"))
-
-
-def test_cli_harvest_sessdata_env_not_echoed(tmp_root, monkeypatch, capsys):
-    """BILI_SESSDATA is used but never echoed in output, errors, or files."""
-    manifest_with(tmp_root)
-    monkeypatch.setenv("BILI_SESSDATA", "TOPSECRET123")
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    captured = capsys.readouterr()
-    assert "TOPSECRET123" not in captured.out + captured.err
-    text = open(ManifestStore(root=tmp_root).path, encoding="utf-8").read()
-    assert "TOPSECRET123" not in text
-    # ...but it was actually sent to the API
-    player_call = [c for c in transport.calls
-                   if "player/wbi/v2" in c["url"]][0]
-    assert player_call["cookies"].get("SESSDATA") == "TOPSECRET123"
-
-
-def test_cli_harvest_api_error_preserves_status_and_mixed_batch_fails(
-    tmp_root, monkeypatch, capsys
-):
-    store = manifest_with(tmp_root, statuses=("meta_ok", "meta_ok"))
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [
-            (200, {"code": -400}),
-            pagelist_ok(),
-        ],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    monkeypatch.setattr("bili_asr.cli.time.sleep", lambda _seconds: None)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 1
-    entries = ManifestStore(root=tmp_root).load()
-    failed = entries.get("BV1test00") or entries["BV1test00:p0"]
-    assert failed["status"] == "meta_ok"
-    assert failed["last_api_error_code"] == -400
-    assert entries["BV1test01:p0"]["status"] == "needs_audio"
-    assert all(entry.get("status") != "gone" for entry in entries.values())
-    captured = capsys.readouterr()
-    output = captured.out + captured.err
-    assert "SECRET" not in output
-    assert "http" not in output.lower()
-
-
-def test_cli_harvest_budget_exhausted_exit_2(tmp_root, monkeypatch, capsys):
-    manifest_with(tmp_root)
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [(412, None)] * 5,
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 2
-    assert "risk-control" in capsys.readouterr().err
-
-
-def test_cli_harvest_skips_done_and_needs_audio(tmp_root, monkeypatch):
-    store = ManifestStore(root=tmp_root)
-    seed_legacy(
-        store,
-        {"bvid": "BV1done", "status": "subtitle_done", "title": "d",
-         "duration_s": 1, "pubdate": 1},
-        {"bvid": "BV1audio", "status": "needs_audio", "title": "a",
-         "duration_s": 1, "pubdate": 1},
-        {"bvid": "BV1todo", "status": "meta_ok", "title": "t",
-         "duration_s": 1, "pubdate": 1},
-    )
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([sub_entry()])],
-        "aisubtitle.hdslb.com": [(200, dict(SAMPLE_DOC))],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--archive-root", tmp_root])
-    assert rc == 0
-    player_calls = [c for c in transport.calls if "player/wbi/v2" in c["url"]]
-    assert len(player_calls) == 1  # only BV1todo probed
-    assert store.get("BV1done")["status"] == "subtitle_done"
-
-
-def test_cli_harvest_bvid_filter(tmp_root, monkeypatch):
-    manifest_with(tmp_root, statuses=("meta_ok", "meta_ok"))
-    transport = RouterTransport({
-        "finger/spi": [SPI_OK],
-        "nav": [nav_ok()],
-        "pagelist": [pagelist_ok()],
-        "player/wbi/v2": [player_ok([])],
-    })
-    _cli_routes(monkeypatch, transport)
-    rc = main(["harvest-subs", "--bvid", "BV1test01",
-               "--archive-root", tmp_root])
-    assert rc == 0
-    store = ManifestStore(root=tmp_root)
-    assert store.get("BV1test00")["status"] == "meta_ok"  # untouched
-    assert store.get("BV1test01:p0")["status"] == "needs_audio"
```
