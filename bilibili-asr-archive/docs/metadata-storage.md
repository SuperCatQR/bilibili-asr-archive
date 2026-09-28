# Metadata and subtitle storage (`archive.db`)

Normalized SQLite storage for the video metadata collected by
`bili-asr fetch-meta` and for the subtitles acquired by `bili-asr harvest-subs`.
This document describes the database the metadata and subtitle CLI commands
create, read, and write. The legacy JSONL manifest pipeline
(`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) is a
separate state: the metadata and subtitle commands described here do not read
it, and no command migrates old data into the new database. `bili-asr
derive-manifest` is the one command that does — it reads the manifest so its
appends stay additive, and appends to it; see
[Boundary with the legacy manifest path](#boundary-with-the-legacy-manifest-path).

## Fresh-start behavior (no migration)

- `fetch-meta` creates `{archive_root}/archive.db` when it does not exist and
  initializes the two checked-in schema resources: `src/bili_asr/storage/schema.sql`
  (users, videos, parts, ingestion runs/pages/cursors/discoveries) and
  `src/bili_asr/storage/schema-transcripts.sql` (acquisition runs and attempts,
  transcripts, transcript segments, and their views). Opening the database — for
  a write or a read command — always runs both scripts, which are idempotent
  no-ops on a current-version database; no schema upgrade happens in this
  iteration. A database created before the transcript contract keeps the shape
  it has: the transcript script is skipped for it, so nothing half-applies, the
  metadata path keeps working, and the subtitle commands report the schema guard
  below instead.
- `status` and `runs` are read-only. When the database is missing they fail
  with a clear configuration error and exit `1`; they never create it.
- There is no migration, import, reset, or rewrite path. Deleting
  `archive.db` is the only way to restart a collection from page 1; old
  archive data is never discovered, read, or modified by any command.
- A failed page never advances the cursor: resume is always safe, and no
  partially written page payload survives a failure.
- `--limit-pages` is optional and defaults to `DEFAULT_PAGE_LIMIT = 10`: a
  run without the flag stops after 10 pages, ends the run `limited` (exit
  0, never claimed complete), and re-running the command resumes from the
  stored cursor.

## Database layout

One SQLite file at `{archive_root}/archive.db`. Foreign keys are enforced
(`PRAGMA foreign_keys = ON`).

### Normalized entity tables

| Table | Key | Contents |
|-------|-----|----------|
| `bilibili_users` | `mid` | The collected user and its current display label. |
| `videos` | `bvid` | One row per video: `aid`, owner `mid` (FK to `bilibili_users`), `title`, `pubdate`. |
| `video_parts` | `(bvid, page_index)` | One row per part: `cid`, part `title`, `duration_ms`, zero-based `page_index` (`{bvid}:p{page_index}` is the derived `work_id`, computed, never stored), `processing_status` (`discovered`, `metadata_collected`, `gone`), FK to `videos`. |

### Ingestion process tables

| Table | Key | Contents |
|-------|-----|----------|
| `ingestion_runs` | `run_id` | One row per collection run: target `mid`, source package and version, requested start page and page limit, `started_at` / `finished_at`, terminal `outcome` (`complete`, `limited`, `risk_interrupted`, `failed`). |
| `ingestion_pages` | `(run_id, page_number)` | One evidence row per requested page: `outcome` (`ok`, `empty`, `risk_interrupted`, `failed`) and a bounded scalar `error_code` on failure. |
| `ingestion_cursors` | `mid` | The resumable one-based cursor: `next_page`, `state` (`ready`, `complete`, `limited`, `risk_interrupted`), `observed_total`. |
| `ingestion_discoveries` | `(run_id, page_number, bvid)` | Run-scoped discovery evidence linking a run page to a discovered video. |

### Media and transcript tables

`transcripts` and `transcript_segments` back the subtitle path: `harvest-subs`
writes one row per acquired caption plus its ordered segments, and
`probe-subs` reads them only through the views below. They are the only tables
this iteration fills on the media side.

`audio_objects`, `part_audio_objects`, and `asr_models` are still empty: no
audio bytes and no ASR model rows are written by any command here. The legacy
audio/ASR chain (`download-audio`, `asr`, `pilot`, `run`) still records its work
in the JSONL manifest, not in these tables, so nothing on this path fills them
yet.

### Views

| View | Contents |
|------|----------|
| `v_video_parts` | Every part with its derived `work_id` and the joined user/video context. |
| `v_ingestion_run_stats` | Per-run page and video counts (the `runs` command's source). |
| `v_pending_metadata` | Parts with `processing_status = 'discovered'` (the `status` command's pending work). |
| `v_pending_subtitles` | Every part that is not `gone` and has no stored transcript, ordered never-attempted first — the subtitle commands' work list, carrying the newest attempt's outcome, timestamp, and credential presence. |

## Subtitle acquisition (`probe-subs` / `harvest-subs`)

Both commands read the parts already stored in `archive.db`, acquire through the
typed gateway, and write their result back there — `archive.db` is the only
destination. The `cid` always comes from `video_parts`: the subtitle path never
fetches a pagelist and never calls upstream for a part that is not in the
database.

```text
bili-asr probe-subs  [--archive-root PATH] (--bvid BVID|BVID:pN | --limit-parts N) [--sessdata VALUE]
bili-asr harvest-subs [--archive-root PATH] [--bvid BVID|BVID:pN] [--limit-parts N]
                      [--language PREF[,PREF...]] [--sessdata VALUE]
```

- `--archive-root PATH` (default `archive`): the root holding `archive.db`.
- `--bvid BVID` selects **every part of that video already in the database** —
  for `harvest-subs` that includes parts that already have a transcript, which
  is the explicit path for re-checking a video after upstream adds or revises a
  caption. `--bvid BVID:pN` selects exactly one part, in the archive's own
  zero-based part vocabulary. A selector that resolves to no stored part is a
  configuration error — exit `1`, `unknown --bvid <value>` — never an empty
  result.
- `--limit-parts N` (positive integer) bounds the run. `probe-subs` requires
  exactly one of `--bvid` / `--limit-parts`; `harvest-subs` requires the bound
  whenever the selection is not a single `bvid:pN` part, which is bounded by
  construction. No unbounded runs.
- `--language PREF[,PREF...]` (`harvest-subs` only) overrides the preference
  rule below; an empty entry is a usage error (exit `1`).

### Output

`probe-subs` prints presence, one line per selected part in selection order,
then a count summary:

```text
sessdata: <present|absent>
probe <work_id> tracks=<n>
  track <lan> <ai|cc> <lan_doc>
probe <work_id> tracks=0
  (no subtitles visible)
probe <work_id> failed <error_code>
probe-subs: probed=<n> with_tracks=<n> without_tracks=<n> failed=<n>
```

A part with no visible track is never omitted: it carries the explicit
`(no subtitles visible)` marker, so "no tracks" cannot be read as "not
attempted". A part whose listing failed carries the bounded code on its own
line, with no track lines and no success marker.

`harvest-subs` prints presence, one line per attempted part in attempt order,
then one summary line that always carries all four outcome counts including the
zeros, the run id, the credential presence, and how many parts still have no
transcript:

```text
sessdata: <present|absent>
harvest <work_id> stored <source_kind> <language> v<version>
harvest <work_id> unchanged <source_kind> <language> v<version>
harvest <work_id> no-subtitle
harvest <work_id> failed <error_code>
harvest-subs: run_id=<run_id> attempted=<n> stored=<n> unchanged=<n> no-subtitle=<n> failed=<n> remaining_without_transcript=<n>
```

`remaining_without_transcript` is read after the run, so the operator can see a
bounded run make progress. Each attempted part maps to exactly one outcome:

| Upstream result | Outcome | Operator reading |
|---|---|---|
| The listing carried no track, or the fetch answered `not_found` | `no-subtitle` | Nothing was visible for this part at this attempt. Not a failure, and not a statement that the video has no captions: a machine caption may not exist yet, uploader captions may never have been provided, and login-gated tracks are invisible anonymously. The part stays in the pending enumeration. |
| Content identical to what is stored for this part/source/language | `unchanged` | The archive already held this caption; nothing was rewritten. |
| New content, or content differing from every stored version | `stored` | A new version was written; earlier versions stay readable. |
| `rate_limited`, `transport_error`, `response_error`, `shape_error` | `failed` + the bounded code | Retry later for the first two; the last two need investigation. |

The error and evidence paths carry no credential, a signed URL, a raw body, or
raw upstream message text: a bounded scalar code stands in for whatever upstream
said. The one upstream **metadata** value any output prints is the track label
(`lan_doc`) on the `track` lines above — printed as metadata, trimmed, and
rejected by the gateway as a bounded `shape_error` if it carries a control
character, so it cannot split the locked one-line-per-track shape. No count here
is presented as coverage of the corpus.

### Exit codes

| Exit | Meaning |
|------|---------|
| 0 | The run completed. That includes a probe whose parts exposed no track at all, a harvest whose every attempted part had nothing visible, and a harvest whose selection resolved to no part (`attempted=0`). |
| 1 | Usage/configuration: a missing `archive.db`, an unknown `--bvid`, a missing or non-positive bound, neither or both `probe-subs` selectors, an empty `--language` entry, or the transcript-schema guard below. |
| 2 | The run failed on **every** attempted part, or an unexpected internal error (the fixed line `<command>: unexpected error`, no traceback). |

An `archive.db` that exists but cannot be read — a file that is not a SQLite
database at all, a truncated one, or a damaged image whose header still opens —
is answered by both commands on **stderr** with the single bounded line
`<command>: unreadable archive database at <archive-root> (<ErrorType>)` and
exit `1`, the same line `status` and `runs` print for that file, which no
command repairs or rewrites.

Partial failure stays visible in the counts and does not by itself decide the
exit code: a harvest that stored one part and failed another exits `0` with
`failed=1` on its summary line. In both exit-2 variants the run row is finished
`failed` when one was opened, and the per-part evidence already written stays
readable.

**A `not_found` listing is read differently by the two commands, on purpose.**
The same upstream answer reaches the operator as two different readings:

- `probe-subs` obtained no listing at all, so it prints
  `probe <work_id> failed not_found` and counts the part under `failed=`. If
  every selected part failed that way, the probe exits `2`.
- `harvest-subs` records the part as `no-subtitle` — nothing was visible for it
  — and exits `0` with `stored=0 unchanged=0 no-subtitle=1 failed=0`.

Neither reading is "this video has no captions", and a part recorded
`no-subtitle` stays eligible for a later attempt.

### Archive writer lock

`harvest-subs` is an archive-writer command: it takes the shipped writer lock at
`{archive-root}/coordinator/archive-writer.lock` for the whole run, so a second
mutating command exits `1` with `harvest-subs: archive_busy` instead of
partially mutating the archive. That lock file and the database itself are the
only files a bounded harvest leaves under the archive root.

The lock is taken by the command dispatcher **before** the handler reaches its
database check, so a harvest pointed at a missing or mistyped `--archive-root`
still creates `<root>/coordinator/` and leaves the lock file there while exiting
`1` with the missing-database line. A failed or mistyped harvest is therefore
not a no-op on the filesystem: nothing reaches the database, but the root and
its `coordinator/` directory are created.

`probe-subs` is deliberately **not** an archive-writer command: it takes no
lock and creates no file under the archive root. Its read-only promise is
structural rather than only documented — no database creation, no transcript
row, no acquisition run or attempt row, no lock file — and it stays a reader
while another process writes, exactly like `status` and `runs`.

### Track selection preference

`harvest-subs` stores exactly one track per part. The default (no `--language`)
ranks the visible tracks by language **family** — `zh` first, then `en`, then
every remaining family in upstream order — and prefers an uploader caption
(`is_ai = false`, printed `cc`) over a machine one; the first track after that
ranking is fetched. The CC-before-AI term is deliberately **family-blind**: the
remaining families share one rank, so between two *different* non-default
families the uploader caption wins even when the machine track comes first
upstream, and upstream order settles only a tie between tracks of the same
family and the same kind. That ranking order is the locked key; `--language`
overrides the whole rule.

The family is derived from the two normalized facts the gateway DTO already
guarantees — `language` and `is_ai` — by stripping the `ai-` prefix from a
machine track's code and then taking the lowercase primary subtag: `zh-CN`,
`zh-Hans`, `zh-Hant`, and `ai-zh` all land in `zh`, so the uploader caption wins
whichever exact code upstream uses. The rule is defined on the family because
upstream codes differ between caption kinds for the same spoken language
(uploader Chinese is `zh-CN` / `zh-Hans` / `zh-Hant`, machine Chinese is
`ai-zh`): a fixed list of exact codes would silently mis-rank any code upstream
adds, and a machine↔uploader equivalence table would have to be maintained
against upstream vocabulary and could flip without warning.

`--language PREF[,PREF...]` overrides the rule: each entry is matched exactly
against the code `probe-subs` prints, the first preference with a match wins,
and among tracks matching the same preference the uploader caption comes before
the machine one (then upstream order). `--language ai-zh` therefore retrieves
the machine caption. A valid preference that matches no visible track yields
`no-subtitle` for that part — nothing usable *for the requested language* was
visible — never `failed`.

The stored kind, language, and version are reported per part, so a run always
shows which caption it kept:

| Stored `source_kind` | Meaning |
|---|---|
| `subtitle-cc` | The uploader's caption. |
| `subtitle-ai` | Upstream's machine-generated caption. |

This replaces the legacy manifest harvest's AI-first preference
(`subtitles._LAN_PREFERENCE`, `("ai-zh", "zh-CN", "zh-Hans", "en")`): the
default now keeps the uploader caption when both are visible, and `--language`
keeps the machine one reachable.

### Schema guard and rebuild

Both commands require the transcript contract in the database they open. On a
database that predates it — one whose `transcripts` table lacks `language` /
`content_sha256` — they print the fixed message below on **stderr** (their part
and summary output is stdout, and this path prints nothing there) and exit `1`.
It is one line; the wrap below is the page's, not the command's:

```text
<command>: archive database predates the transcript schema; rebuild it (delete <archive-root>/archive.db and re-run fetch-meta)
```

A zero-byte `archive.db` — a file that exists but was never initialized — is the
one state the two commands read differently, and the difference is the point:
`harvest-subs` opens through the schema-initializing `open_database`, so it
creates both schemas in that file and runs normally (a selection resolving to no
part reports `attempted=0`, exit `0`), while `probe-subs` writes nothing at all,
so its read-only open finds no transcript contract and answers with the rebuild
line above (exit `1`).

The metadata commands (`fetch-meta`, `status`, `runs`) keep working on that same
database unchanged. There is no in-place migration: the rebuild procedure is to
delete `archive.db`, re-run `fetch-meta` to recreate it from the checked-in
schemas, and harvest again. A bare `fetch-meta` stops at the implicit
`--limit-pages` bound (`DEFAULT_PAGE_LIMIT = 10`), so rebuilding a corpus
collected beyond page 10 needs the bound spelled out (`--limit-pages <n>`) — or
repeated runs with `--resume`, which continues from the stored cursor.

### Boundary with the legacy manifest path

This iteration replaces the manifest semantics of the two command names; it does
not migrate the rest of the archive. The ASR and pilot chain (`asr`, `pilot`,
`run`, `schedule`, `campaign`, `download-audio`) is untouched and still reads
`manifest/manifest.jsonl`:

- the new `harvest-subs` still produces no manifest status `needs_audio` itself;
  `bili-asr derive-manifest` is the command that feeds `download-audio
  --missing-subs` from this path, by appending a `needs_audio` row per part in
  the pending-subtitle relation — every stored part with no transcript and not
  `gone`; the parts recorded `no-subtitle` are among them — additively, never
  rewriting a row the chain already holds. And the same effective-key rule is a
  limit in the other direction: a legacy bare-`bvid` row is not consulted either,
  so a part whose only record is one is appended anyway — the cost is a
  re-download and a re-ASR for a part the chain already finished, registered as
  `iter-2026-09-queue-bridge · R2`;
- `bili-asr asr --pending` and the pilot chain are still driven from the
  manifest state, not from `archive.db`, so a transcript stored here does not
  feed them. The bridge runs the other way round: store facts are appended to the
  manifest, and the read-only store connection means nothing is ever read back
  into the database;
- of the work this section used to defer, enumerating the audio work queue from
  SQLite has shipped, as `bili-asr derive-manifest --archive-root <root>`. It
  writes no `archive.db` row and starts no download and no ASR: the operator
  still runs `download-audio` / `asr` / `run` / `schedule` / `campaign` from the
  appended rows;
- of the work this section used to defer, rebuilding the SRT/TXT/MD projections
  from the stored transcripts has shipped too, as `bili-asr publish-transcripts
  --archive-root <root> [--artifact-root <path>]`: one complete archive bundle
  per stored part that holds a transcript — the stem `{bvid}.p{page_index}` —
  and one `archived` manifest row per publication; a candidate it cannot publish
  is named and the run exits `1`. It fetches nothing, and a complete published
  bundle is never replaced, so a store that later gains a newer transcript
  version leaves the published product as it is. Two bounds belong beside that:
  a legacy `subtitle_done` part is published from the store and its
  `transcripts/{stem}/bundle.srt` is replaced when the legacy row was
  page-qualified (its document under `subtitles/raw/` is not touched), and a
  `work_id` whose manifest already carries an earlier state is outside what the
  archive's readers currently agree on. A stored caption is not re-queued for
  audio either, because the derived queue is the no-transcript relation.

## No-JSONL contract

`fetch-meta`, `status`, `runs`, `probe-subs`, and `harvest-subs` never read or
write `manifest.jsonl`, `meta-cursor.json`, or `run-ledger.jsonl`. All persisted
run/page evidence is scalar: `error_code` values are bounded strings of at most
64 characters from a restricted character set. Credentials, signed URLs, raw
response bodies, and raw exception text never enter CLI output, logs, or any
persisted row. Neither of the two subtitle commands, `probe-subs` and
`harvest-subs`, writes an on-disk projection of the transcript: neither produces
`subtitles/raw/*.json` and neither produces `transcripts/<stem>/bundle.srt` — the
normalized transcript lives in `archive.db` until `bili-asr publish-transcripts`
publishes it (see
[Boundary with the legacy manifest path](#boundary-with-the-legacy-manifest-path)).

## Credential boundary

The optional SESSDATA credential comes from `--sessdata` or the
`BILI_SESSDATA` environment variable (flag wins). It is passed to the
gateway's cookie object only: never echoed, logged, persisted, or rendered —
CLI output shows presence only (`sessdata: present|absent`). Omitting it
means anonymous access, and so does passing `--sessdata ""` explicitly
(which never falls through to `BILI_SESSDATA`); a blank environment value
likewise means anonymous. `harvest-subs` additionally records the presence in
its `acquisition_runs` row, so a part it recorded `no-subtitle` stays
interpretable afterwards: an invisible caption may exist and simply be
login-gated. `probe-subs` records nothing at all and only prints the presence.

## Runtime HTTP backend

`fetch-meta` reaches upstream through the pinned
`bilibili-api-python==17.4.2` adapter, and that distribution declares no HTTP
client of its own. With none installed, every request fails inside the process
with `ArgsException("尚未安装第三方请求库或未注册自定义第三方请求库")` — the
request never leaves the process — and the gateway maps it to the bounded
`response_error`. `curl_cffi` is therefore a declared runtime dependency of
this package, and a normal install provides it:

```
python3.12 -m pip install -e ".[dev]"     # or: uv sync
```

No separately installed backend is needed on top of that; a bare
`pip install bilibili-api-python==17.4.2` alone is not enough.

### Upstream page-call shape

The adapter issues the user-video page call itself through the package's
WBI-signed `Api` request, with the device-fingerprint (`dm`) parameters
disabled and `w_webid` sent as a present string (empty when the package
cannot derive an access id). The endpoint answers HTTP 412 to the `dm` shape
and to a missing `w_webid`; every other parameter, the WBI signature, and the
whole response normalization and validation path stay as the pinned package
and the gateway spec define them. The bounded error taxonomy is unchanged:
412/429 and the risk-control codes map to `rate_limited`, `-404`/`-62002` to
`not_found`, shape problems to `shape_error`, and other upstream failures to
`response_error`/`transport_error`.

### Page size

The adapter and the `BilibiliGateway` protocol default `page_size` to **30**,
and the shipped service path passes that same value explicitly
(`PAGE_SIZE = 30` in `src/bili_asr/services/metadata_ingest.py`); it is also the
pinned package's own documented `ps` value. Larger page sizes are **not**
guaranteed: with the same credential, proxy, and call shape, `ps=30` and
`ps=50` were answered with `code=0` while `ps=100` was rejected (HTTP 412 on
direct probes, JSON code `-400` on production runs). The adapter forwards an
explicit `page_size` override upstream unchanged — it neither clamps nor
rejects it — so an over-large override surfaces as the upstream bounded code
(`rate_limited`/`response_error`) rather than as a caller error. There is no
CLI flag for the page size.

## HTTP proxy

The pinned client builds its session with an explicitly empty proxy
(`proxies={"all": ""}`), which defeats the transport's environment lookup:
`HTTPS_PROXY` / `ALL_PROXY` alone are ignored by the package, so on a host
whose direct route to Bilibili is blocked every call ends in a connect
timeout. The gateway therefore resolves one proxy itself and applies it to the
package's request settings before the first call.

Precedence (first non-blank value wins; blank counts as unset):

1. the `BilibiliApiGateway(proxy=...)` constructor argument,
2. `BILI_HTTP_PROXY` — the documented operator knob,
3. `HTTPS_PROXY`, then `https_proxy`,
4. `ALL_PROXY`, then `all_proxy`.

When nothing resolves, the library default is left untouched and no proxy is
forced. A proxy URL is configuration, not a credential, and is never written
to DTOs, logs, exception messages, or persisted rows.

Two consequences of that design matter when troubleshooting:

- The resolved value is applied to the package's **process-global** request
  settings, so it is the effective proxy for every gateway in the process, not
  only for the instance that resolved it.
- A blank value counts as *unset*, so `BILI_HTTP_PROXY=""` cannot override a
  host-level `HTTPS_PROXY`/`ALL_PROXY`. There is no in-app "no proxy" switch:
  forcing a direct connection means unsetting every variable of the chain
  (`BILI_HTTP_PROXY`, `HTTPS_PROXY`, `https_proxy`, `ALL_PROXY`, `all_proxy`)
  for the process before the command runs.

```
export BILI_HTTP_PROXY=http://127.0.0.1:7890
bili-asr fetch-meta --mid 23191782 --limit-pages 1 --archive-root archive
```

## `observed_total` semantics

- `ingestion_cursors.observed_total` records the upstream video total
  reported by the page response (`page.count`) when it is present; it is
  provenance about the upstream snapshot, not a completion proof.
- The fake test gateway reports a per-page count (its scripted responses
  carry the scripted page size); live runs record the upstream global total.
- Run completion keys off the empty item list: the first page that returns
  no videos ends the run `complete` (bounded, spec-defined). An explicit
  `--limit-pages` bound ends the run `limited` instead — never claimed as
  complete — and the same applies to the implicit default bound
  (`DEFAULT_PAGE_LIMIT = 10`) applied when the flag is omitted.

## Exact bounded live smoke command

The smoke is opt-in and bounded: one public metadata page for UID 23191782
into a temporary archive root. On a proxied host — and on this host, whose
direct route to Bilibili is blocked — the proxy is part of the command:

```
CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
cd "$CONTROL/bilibili-asr-archive"
set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
export BILI_HTTP_PROXY=http://127.0.0.1:7890
BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
  -m pytest tests/test_live_metadata_smoke.py -s -v
```

The control checkout owns both the `.env` credential file and the `.venv`
interpreter; a linked feature worktree has neither, so a worktree run must
address them by absolute control-checkout path (as above) or provision its
own environment. `-s` (or `-rP`) is part of the command: pytest captures the
stdout of a *passing* test, so a plain `-v` run hides the evidence line on the
happy path and would force a second page request against a risk-controlled
endpoint — use `-s`/`-rP` on the first live attempt.

`BILI_SESSDATA` and `BILI_HTTP_PROXY` may come from the sourced `.env` instead
of an explicit `export` (the gateway reads the same environment).

- Opt-in only (`BILI_LIVE_SMOKE=1`); default pytest runs skip it without
  failure. An opted-in run in an environment without the pinned
  `bilibili-api-python==17.4.2` distribution fails loudly with install
  guidance instead of skipping.
- Bound: exactly one page for UID 23191782 (`--start-page 1 --limit-pages 1`)
  into a temporary archive root; no subtitle, playback, audio, or ASR code is
  invoked, and nothing outside the temporary root is written.
- **With a credential** (`BILI_SESSDATA` only — the smoke builds its own
  `fetch-meta` argv and passes no `--sessdata`, so that flag is a CLI surface
  the smoke never uses) the happy path is required: exit 0,
  `outcome=limited` on the page bound (or `complete` when
  the first page comes back empty), and real normalized rows — the user row,
  one video row per collected video joined to that user, the part rows of
  those videos, one discovery row per collected video, a terminal run row,
  exactly one page-evidence row, and a cursor advanced past the committed
  page. The run also asserts that no legacy sidecar
  (`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) appears
  and that neither the CLI output nor any persisted row carries the
  credential value or playback markers. It prints one count-only evidence
  line:
  `live smoke evidence: outcome=… videos=… parts=… discoveries=… page_rows=1 cursor_next_page=… cursor_state=… observed_total=…`.
  A bounded upstream failure while a credential is present is a loud failure.
- **Without a credential** the run is anonymous: if upstream rejects
  anonymous metadata access it ends in the bounded-failure branch, whose
  evidence the smoke then verifies (terminal run row, one page row carrying a
  scalar code — `rate_limited`, or `response_error` for other upstream
  failures — no video/part/discovery growth, no cursor row). That bounded
  no-credential outcome is reported as a reasoned skip, after its assertions
  ran, not as a defect; any other bounded code — a `transport_error` from a
  dead proxy, for instance — fails the smoke loudly, credential or not.
- **Observed on 2026-09-11** (this host, proxy configured): the live run was
  refused by upstream risk control. The CLI's one production page (the
  then-shipped page size of 100) ended twice — before and after a cooldown —
  in the bounded `response_error` branch, whose underlying upstream answer is
  the JSON code `-400`; a direct call with the same credential, proxy, and
  call shape but a page size of 5 returned `code=0` with real rows (5 videos,
  `observed_total=1691`), and later probes of both page sizes were answered
  with HTTP 412 (`rate_limited`). So the transport and the call shape do
  reach and satisfy upstream, while this egress is intermittently under
  risk control; a loud live-smoke failure means the bounded page was refused
  upstream, not that the database or the CLI is broken.
- **Settled on the same day (focused probes after the call-shape fix):** the
  endpoint does reject the old page size. With the same credential, proxy,
  and call shape, `ps=30` returned `code=0` with 30 items and `ps=50`
  returned `code=0` with 50 items, while `ps=100` was rejected — HTTP 412 on
  the probes and the JSON code `-400` on production runs. The shipped page
  size is therefore the value upstream accepts: `PAGE_SIZE = 30` in
  `src/bili_asr/services/metadata_ingest.py`, which is also the pinned
  package's own documented `ps` value.
- **Achieved on 2026-09-11 (same day, after the page-size fix):** the shipped
  path completed a real end-to-end live run — CLI exit 0, one collected page,
  `outcome=limited videos=30 parts=33 discoveries=30`, `observed_total=1691`,
  and the cursor advanced to `next_page=2` with state `limited`. Count-only:
  no credential, no proxy, and no collected metadata value is recorded here.
  The intermittency noted above still applies to a fresh run.

### Subtitle CLI smoke (`tests/test_live_subtitle_cli_smoke.py`)

The same switch gates a live smoke of the subtitle commands: one public part
through `probe-subs` and `harvest-subs` into a temporary archive root. Both
commands address parts already in the database, so the smoke authors the one
part it probes — the fixed public sample `BV1S8hA6MEvy:p0` — into its own
temporary root first, and records `part_source=fixed-sample` with the identity
in its single count-only evidence line:

```
CONTROL=/root/workspace/bilibili-asr-archive   # the control checkout
CHECKOUT=$CONTROL/bilibili-asr-archive         # or a feature worktree's package dir
cd "$CHECKOUT"
set -a; source "$CONTROL/.env"; set +a          # gitignored; absent in a worktree
export BILI_HTTP_PROXY=http://127.0.0.1:7890
BILI_LIVE_SMOKE=1 "$CONTROL/bilibili-asr-archive/.venv/bin/python" \
  -m pytest tests/test_live_subtitle_cli_smoke.py -s -v
```

It runs from the package directory of the checkout under test because the
control `.venv` carries an editable install of the control checkout: the
package's own `tests/conftest.py` puts `src/` first on `sys.path`, so the code
exercised is the checkout the test file belongs to.

- Bound: one part, `--limit-parts 1` on both commands — one track listing for
  the probe, one listing plus one document fetch for the harvest (when a track
  is visible). The smoke adds no retry of its own; the shipped gateway is
  fail-fast per call, so a throttled endpoint is answered by waiting and
  re-running, never by bending the call shape.
- Opt-in requires a resolvable credential: the smoke passes no `--sessdata` and
  reads the same environment the command reads, so an opted-in run with no
  `BILI_SESSDATA` (unset or blank) **fails loudly** with source-the-`.env`
  guidance instead of reporting its anonymous `sessdata=absent tracks=0` reading
  as a bounded observation. That reading is ambiguous — a login-gated caption
  and a part with no caption look identical — so a forgotten credential must not
  read as "nothing visible now". A default (not opted-in) pytest run still
  skips, credential or not.
- Asserted when a caption is visible: the printed presence, track, outcome and
  summary line shapes; the normalized transcript row (an allowed
  `source_kind`, its language, version 1, the content hash), its ordered
  segments, the one run row with the operator's selector and the credential
  presence, the one attempt row pointing at the transcript, a part that left
  `v_pending_subtitles`, and an archive root holding nothing but `archive.db`
  and `coordinator/archive-writer.lock`. Every field of the printed evidence
  line is tied to an assertion: the probe's `with_tracks` and the harvest's
  `stored` are checked against the part line they summarize, and the printed
  `run_id` against the persisted run row. Both commands' stdout and stderr are
  scanned for the seam's secret/payload sentinels — including the probe's, whose
  `track` lines are the one place an upstream label is printed.
- Recorded without reading green: zero visible tracks, a `not_found` listing,
  and a `rate_limited` refusal each assert their bounded shapes, print the
  evidence, and skip — a run that stored no transcript is not a subtitle
  acquisition. Every other bounded code (`transport_error` from a dead proxy,
  `response_error`, `shape_error`) fails loudly.
- **Observed on 2026-09-11** (this host, credential and proxy configured), CLI
  exit 0, bounded facts only: `part_source=fixed-sample
  work_id=BV1S8hA6MEvy:p0 sessdata=present probe_exit=0 probed=1 with_tracks=1
  without_tracks=0 probe_failed=0 track_count=1 tracks=ai-zh:ai harvest_exit=0
  run_id=1de9b7cb7cd141bfa7114112212188db attempted=1 stored=1 unchanged=0
  no_subtitle=0 failed=0 remaining_without_transcript=0 source_kind=subtitle-ai
  language=ai-zh version=1 segments=2913 transcripts=1 attempts=1
  pending_after=0`. The part exposed one machine caption, the harvest stored it
  as version 1, and the part left the pending enumeration. Count-only: no
  credential, no proxy, no signed URL, and no caption text is recorded here.

## Exit codes

### `fetch-meta`

| Exit | Meaning |
|------|---------|
| 0 | Successful collection: completed on an empty page, stopped at the explicit `--limit-pages` bound, or stopped at the implicit default bound (`DEFAULT_PAGE_LIMIT = 10` when the flag is omitted); the run row records `complete` or `limited` accordingly. |
| 1 | Usage/configuration error: non-positive page arguments, `--resume` with no stored cursor, or an unreadable archive root. Unexpected internal errors exit 2 (see below), not 1. |
| 2 | Terminal failure — two variants, distinguishable by the failure line (see below). |

Exit 2 variants:

- **Gateway failure** (bounded scalar code, e.g. `response_error`,
  `rate_limited`): the gateway is fail-fast per page — one attempt per
  page, no retry. The failed page records its bounded scalar code, the
  cursor remains unchanged, and re-running `fetch-meta` resumes safely.
- **Unexpected internal error** (the fixed line `fetch-meta: unexpected
  error`, no scalar code, no traceback): the cursor may already hold the
  last committed page of the run and the run row may remain `running` —
  check `status` / `runs` before re-running. Re-running is safe: it
  resumes from the stored cursor.

### `status` / `runs`

| Exit | Meaning |
|------|---------|
| 0 | Database read and displayed. An empty database prints `runs: empty`. |
| 1 | Configuration error: the database does not exist (or a non-positive `runs --limit`). |

`runs` lists runs newest-first — ordered by `started_at` descending, with
same-second runs tie-broken deterministically by `run_id` descending — and
includes non-terminal `running` rows: a crash can leave a stale run behind,
and hiding it would hide real state.

### `probe-subs` / `harvest-subs`

Defined in the "Subtitle acquisition" section above: `0` the bounded run
completed (a probe with zero visible tracks and a selection that resolved to no
part included), `1` usage/configuration or the transcript-schema guard, `2` every
attempted part failed or an unexpected internal error.
