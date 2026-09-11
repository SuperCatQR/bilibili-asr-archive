# Metadata storage (`archive.db`)

Normalized SQLite storage for the video metadata collected by
`bili-asr fetch-meta`. This document describes the database the metadata CLI
creates and reads. The legacy JSONL manifest pipeline
(`manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl`) is a
separate, untouched state: the metadata commands never read it, and no
command migrates old data into the new database.

## Fresh-start behavior (no migration)

- `fetch-meta` creates `{archive_root}/archive.db` when it does not exist and
  initializes the checked-in schema (`src/bili_asr/storage/schema.sql`).
  Opening the database — for a write or a read command — always runs that
  schema script, which is an idempotent no-op on a current-version database;
  no schema upgrade happens in this iteration.
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

### Reserved media boundary (empty in this plan)

`audio_objects`, `part_audio_objects`, `asr_models`, `transcripts`, and
`transcript_segments` are created now so later media and transcript plans
attach through these foreign keys instead of reintroducing sidecars. They
stay empty in this plan; no media bytes or transcripts are written yet.

### Views

| View | Contents |
|------|----------|
| `v_video_parts` | Every part with its derived `work_id` and the joined user/video context. |
| `v_ingestion_run_stats` | Per-run page and video counts (the `runs` command's source). |
| `v_pending_metadata` | Parts with `processing_status = 'discovered'` (the `status` command's pending work). |

## No-JSONL contract

`fetch-meta`, `status`, and `runs` never read or write `manifest.jsonl`,
`meta-cursor.json`, or `run-ledger.jsonl`. All persisted run/page evidence
is scalar: `error_code` values are bounded strings of at most 64 characters
from a restricted character set. Credentials, signed URLs, raw response
bodies, and raw exception text never enter CLI output, logs, or any
persisted row.

## Credential boundary

The optional SESSDATA credential comes from `--sessdata` or the
`BILI_SESSDATA` environment variable (flag wins). It is passed to the
gateway's cookie object only: never echoed, logged, persisted, or rendered —
CLI output shows presence only (`sessdata: present|absent`). Omitting it
means anonymous access, and so does passing `--sessdata ""` explicitly
(which never falls through to `BILI_SESSDATA`); a blank environment value
likewise means anonymous.

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
