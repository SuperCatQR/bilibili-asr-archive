# Architecture: Archive Completeness Foundations

Iteration-scoped draft. Not `{SPECS_DIR}` and not `{KNOWLEDGE_DIR}`. Frozen MVP remains `.mstar/specs/asr-archive-cli.md` (bvid-keyed).

## Prepare & Plan Package (Architecture)

### Clarify Validation

- Inputs Checked: delivery compass, both product plans, live `manifest.py` / `bili_client.py` / `subtitles.py` / `audio.py` / `archive.py` / `cli.py`, knowledge pattern `architecture-patterns/bilibili-asr-archive-cli.md` (read-only), locked product decisions in the architect assignment.
- Impactful Ambiguities: none remaining that block implement. Operator resolution of unresolved legacy rows is a documented CLI/report action, not an automatic rewrite. Windows-invalid `:` in `work_id` is resolved by a separate `artifact_stem`.
- Gate Decision: go

### Plan

- Option A: Keep JSONL keyed by `bvid` and store pages as nested arrays. Trade-off: smaller migration, but independent page status, resume, and artifact paths stay second-class and collide.
- Option B (selected): One JSONL row per pagelist part, keyed by canonical `work_id`. Nested pages would hide the state machine already owned by `ManifestStore`.
- Selected Approach: typed `PageIdentity` at every HTTP/filesystem seam; manifest key = `work_id`; `bvid` remains a field; filesystem names use `artifact_stem`; cursor I/O lives beside the manifest, never in `bili_client`.
- Long-term Target State: every visible part is an independently resumable ledger row with collision-free artifacts; metadata crawls resume from an atomic mid-keyed sidecar with honest `risk_interrupted` / `limited` / `complete` terminals.
- Durable Slice for This Batch: plan 001 identity + migration + page-aware harvest/playurl/archive; plan 002 cursor sidecar + optional `start_page` on `fetch_pages`.
- Roadmap if Split: serial 001 then 002; executable two-branch pilot and installed-entrypoint suites remain later iterations (compass non-goals).
- Module Boundaries / API/Data Contracts / Risks / Validation: sections below.
- Effort (agent-oriented): L (two serial SDD plans; session band 2–4 implementer sessions plus mandatory QC/QA).

## Overview

This iteration replaces the current bvid-only ledger and `pages[0]` media path with a page-complete archive identity, then adds an independent metadata cursor. Transport, risk taxonomy, SESSDATA/signed-URL redaction, and `gone` remain unchanged.

## Long-term Target State

- Ledger key = `work_id` (`bvid:p<zero-based-page-index>`).
- `cid` is a required field on every automatic page row, never the primary key.
- Artifact paths cannot collide across pages on POSIX or Windows.
- `fetch-meta --resume` continues from `meta-cursor.json` after risk stop; `limited` is not `complete`.

## Staged Roadmap

1. Plan `20260824-multipart-page-aware-pipeline` (this package identity/ledger/artifacts).
2. Plan `20260824-cursor-based-resume` (this package cursor + `start_page`).
3. Next iteration: executable two-branch pilot after audit plan 005 API contract integrity.
4. Later: audit plan 004 installed-entrypoint / full state-machine suite.

## Architecture Diagram

```text
BiliClient (HTTP only)
  list_pages(bvid) -> list[PageIdentity]
  probe_subs(bvid, cid)
  fetch_playurl_audio(bvid, cid)
  fetch_pages(mid, max_pages=None, start_page=1)  # no FS

ManifestStore (JSONL, key=work_id)
  load / get / get_compatible(bvid) / upsert / save
  migrate_legacy_rows(list_pages)

MetaCursorStore (archive-root meta-cursor.json)
  load / replace_atomic  # CLI/manifest seam only

harvest_subtitle / download_audio / write_archive
  consume PageIdentity; paths from artifact_stem
```

## Tech Stack

Unchanged: Python 3.12, injectable `Transport`, atomic `os.replace`, JSONL manifest.

## Module Breakdown

| Module | Owns | Must not own |
|--------|------|----------------|
| `bili_asr.page_identity` (new) | `PageIdentity`, `format_work_id`, `artifact_stem`, parse/validate | HTTP, FS I/O |
| `bili_asr.bili_client` | HTTP, WBI, risk/retry, `list_pages`, cid-aware probe/playurl, optional `start_page` | cursor files, manifest rewrite |
| `bili_asr.manifest` | JSONL keyed by `work_id`, compatibility lookup, unresolved flags, atomic save | HTTP |
| `bili_asr.meta_cursor` (new, plan 002) | `MetaCursor` schema, atomic sidecar read/write | HTTP |
| `bili_asr.subtitles` / `audio` / `archive` / `cli` | page-aware orchestration and CLI summaries | new sockets |

## API Contracts

### `PageIdentity`

Immutable record (dataclass or TypedDict; name locked: `PageIdentity`):

| Field | Type | Notes |
|-------|------|--------|
| `work_id` | `str` | `{bvid}:p{page_index}` ; `:` is identity punctuation, not a path char |
| `bvid` | `str` | BV id |
| `page_index` | `int` | zero-based pagelist order |
| `cid` | `int` | pagelist cid; required for automatic processing |
| `page_label` | `str` | pagelist `part` / title; may be empty |

Helpers (names locked):

- `format_work_id(bvid: str, page_index: int) -> str`
- `parse_work_id(work_id: str) -> tuple[str, int]`
- `artifact_stem(identity: PageIdentity) -> str` → `{bvid}.p{page_index}` (no colon; Windows-safe)
- `page_query_index(page_index: int) -> int` → `page_index + 1` for public `?p=` URLs only

### `BiliClient`

- `list_pages(self, bvid: str) -> list[PageIdentity]`
  - Calls existing pagelist endpoint once.
  - `page_index = enumerate(data, start=0)`.
  - Empty pagelist remains `_GoneResponse("pagelist-empty")`.
  - Missing `cid` on any returned part is STOP (do not invent).
- `probe_subs(self, bvid: str, cid: int | None = None) -> list[dict]`
  - New required path: pass `cid`.
  - Compatibility: `cid is None` allowed only after `list_pages` would return exactly one part; otherwise raise a typed `AmbiguousPageError` (name locked). Do not silently use `pages[0]` for multi-part.
- `fetch_playurl_audio(self, bvid: str, cid: int | None = None)` — same cid rule as `probe_subs`.
- `fetch_pages(self, mid, max_pages=None, start_page: int = 1)`
  - `start_page` is 1-based `pn` (Bilibili page number, not video part index).
  - Default `1` preserves current callers.
  - Loop initializes `pn = start_page`; retry taxonomy, empty-streak, jitter, and `last_failed_page` unchanged.
  - No filesystem access.

### ManifestStore

- In-memory dict key and JSONL identity field: `work_id` (required on every automatic row).
- `bvid` remains required on every row.
- `upsert` keys by `work_id`; rejects missing `work_id` for new automatic rows.
- `get(work_id: str)` exact key.
- `get_compatible(bvid: str)` (name locked):
  1. If exactly one non-unresolved row exists with that `bvid`, return it.
  2. If a preserved unresolved bare-bvid row exists, return it and never treat it as a processable page.
  3. Otherwise `None` (do not guess among multiple pages).
- Load of mixed files: last write still wins **per key**; keys are `work_id` when present, else temporary load of bare `bvid` only to feed migration.

### Harvest / audio / archive

- `harvest_subtitle(client, identity: PageIdentity, store, archive_root)`
- `download_audio(client, identity: PageIdentity, out_path, store=None)` — callers pass `out_path` derived from `artifact_stem`.
- `write_archive(..., entry, ...)` filenames use `artifact_stem`; markdown frontmatter includes `work_id`, `bvid`, `page_index`, `cid`; `url` may append `?p={page_index+1}`.

Existing CLI commands that accept a bare bvid resolve via `list_pages` + `get_compatible` and STOP on unresolved or multi-part without an explicit page.

## Data Model

### Automatic page row (JSONL object)

```json
{
  "work_id": "BVexample:p0",
  "bvid": "BVexample",
  "page_index": 0,
  "cid": 123,
  "page_label": "part title",
  "status": "pending",
  "aid": 1,
  "title": "video title",
  "duration_s": 0,
  "pubdate": 0
}
```

Status set unchanged: `pending` … `archived` plus `gone` (per work item, not per bvid).

### Unresolved legacy row

Byte-for-byte preserve original object; **add only** these fields if absent (additive, never rewrite artifacts or status):

| Field | Value |
|-------|--------|
| `unresolved` | `true` |
| `unresolved_reason` | `ambiguous_bare_bvid` |
| `excluded_from_page_processing` | `true` |

Do **not** invent `work_id`, `page_index`, or `cid` on unresolved rows. Ledger key for that line remains the original `bvid` until an operator resolution command (out of this iteration except reporting) rewrites it.

### Migration (plan 001, atomic with `ManifestStore.save`)

Unambiguous iff current pagelist length is 1 **and** the row has no `work_id` **and** no second page's `artifact_stem` files exist. Then rewrite key to `format_work_id(bvid, 0)`, set `page_index=0`, copy cid/label from `list_pages`.

Ambiguous (pagelist length ≠ 1, conflicting artifacts, or missing cid): leave JSONL line and `{bvid}.*` artifacts untouched; mark unresolved; exclude from automatic page loops; CLI/status reports count + identifiers.

Collision STOP: migration that would overwrite an existing `{bvid}.pN.*` or a different `work_id` row.

### Artifact paths

Directories unchanged (`subtitles/raw`, `transcripts/srt|txt|md|raw`, audio dir used by CLI today).

Basenames (stem = `artifact_stem`):

| Kind | Path |
|------|------|
| raw subtitle JSON | `subtitles/raw/{stem}.json` |
| harvested SRT | `transcripts/srt/{stem}.srt` |
| audio | `{audio_dir}/{stem}.m4a` (flac sibling same stem) |
| archive srt/txt/raw | `transcripts/{srt,txt,raw}/{stem}.*` |
| markdown | `transcripts/md/{pubdate}_{stem}_{title}.md` |

Never use `work_id` as a filename.

## Security

Unchanged: no SESSDATA, signed URLs, or raw transport exception text in JSONL, cursor, logs, or user diagnostics. Cursor scalars only (`last_api_error_code` already-redacted code).

## Scalability

Serial page processing; no new concurrency. Cursor `start_page` avoids re-fetching enumerated archive list pages (UP space pages, not video parts).

## Meta-cursor (plan 002)

See companion contract: `meta-cursor.md`. Ownership: `bili_asr.meta_cursor` + `_cmd_fetch_meta`. HTTP client only receives integer `start_page`.

## Risks and Rollback

| Risk | Mitigation | Rollback |
|------|------------|----------|
| Colon in `work_id` breaks Windows paths | `artifact_stem` without `:` | N/A; do not file `work_id` |
| Partial identity adoption overwrites p1 | grep seams; two-page fixture | restore JSONL from `.tmp` failed replace (no replace) |
| Ambiguous migration | unresolved preserve | do not write work_id |
| Cursor/HTTP coupling | `start_page` int only | omit cursor module; keep fetch_pages default |
| `limited` vs `complete` | distinct `state` enum | STOP rather than reuse one terminal |

## Validation Plan

- Unit: `format_work_id` / `artifact_stem` / parse round-trip; colon never in stem.
- Manifest: unambiguous single-page migrate; multi-page bare row unresolved and byte-stable; `get_compatible` never returns a guessed page.
- Client: `list_pages` indices; `probe_subs`/`fetch_playurl_audio` send fixture cid not `pages[0]` on two-page pagelist; `cid=None` on two-page raises `AmbiguousPageError`.
- Pipeline: two-page fixture independent status; distinct artifact paths; p0 terminal does not skip p1.
- Cursor (plan 002): stop page 2 → `next_page=2` → resume; no duplicate JSONL; `limited` vs `complete`; sidecar has no secrets.
- Full `python -m pytest` on 3.12; no live HTTP / model / media.

## Effort (agent-oriented)

L for the iteration slice; plan 001 M–L, plan 002 S–M.
