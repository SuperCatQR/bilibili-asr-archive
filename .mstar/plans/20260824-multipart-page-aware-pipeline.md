# Multi-Part Page-Aware Pipeline

> Candidate source: `.mstar/plans/audit-2026-08-24/001-multipart-page-aware-pipeline.md`.
> Iteration: `iter-2026-08-archive-foundations`.
> Execution mode: `sdd`.

## Status

- Priority: P1
- Category: bug / logic
- State: Done
- Depends on: none
- Findings cleanup: zero-residual

## Goal

Process every pagelist part of a Bilibili bvid as an independently resumable archive work item, without losing page identity or overwriting artifacts.

## Locked Prepare Decisions

- Canonical work ID: `bvid:p<zero-based-page-index>`.
- Each row retains `bvid`, `page_index`, `cid`, and page label metadata; `cid` is not the primary key.
- Legacy bare-bvid rows migrate only when page ownership is unambiguous; ambiguous rows and their artifacts remain byte-for-byte preserved, are excluded from automatic page processing, and are surfaced as unresolved with an actionable operator resolution path.
- Artifact paths use `artifact_stem` `{bvid}.p{page_index}` in raw subtitle, SRT, audio, and transcript names. Never write `work_id` (contains `:`) into filenames.
- `bili_client.py` remains the sole HTTP owner; page identity is passed through injectable seams.

## Global Constraints

- Do not change the frozen API risk taxonomy or SESSDATA/signed-URL redaction boundaries.
- Do not add live-network tests, model downloads, or real media transfer.
- Preserve single-page compatibility adapters while making automatic multi-page enumeration page-aware.
- Every task must leave a reproducible test or static verification command.

## Interfaces

Locked in `.mstar/iterations/iter-2026-08-archive-foundations/specs/archive-foundations-architecture.md`.

- `PageIdentity`: `work_id`, `bvid`, `page_index`, `cid`, `page_label`.
- `format_work_id` / `parse_work_id` / `artifact_stem` (`{bvid}.p{page_index}`).
- `BiliClient.list_pages(bvid) -> list[PageIdentity]`.
- `probe_subs(bvid, cid=None)` and `fetch_playurl_audio(bvid, cid=None)`: `cid` required for multi-part; `cid is None` only when pagelist length is 1; otherwise `AmbiguousPageError` — never silent `pages[0]`.
- `ManifestStore` keys JSONL by `work_id`; `get(work_id)`; `get_compatible(bvid)` for unambiguous or unresolved legacy rows.
- `harvest_subtitle` / `download_audio` / `write_archive` take `PageIdentity` (or derive paths from `artifact_stem`).

## Tasks

### Task 1: Define identity and migrate legacy rows

- [x] Add `bili_asr.page_identity` with `PageIdentity`, `format_work_id`, `parse_work_id`, `artifact_stem`.
- [x] Key `ManifestStore` by `work_id`; keep `bvid` as a required field; add `get_compatible(bvid)`.
- [x] Atomic, deterministic migration only when pagelist length is 1 and no colliding `{bvid}.pN` artifacts exist.
- [x] Preserve ambiguous legacy rows byte-for-byte plus additive `unresolved` / `unresolved_reason=ambiguous_bare_bvid` / `excluded_from_page_processing`; report count and identifiers; no automatic page assignment.
- [x] Tests: stem has no `:`; migrate single-page; freeze multi-page bare row.

### Task 2: Enumerate and process all pages

- [x] Implement `list_pages`; create one ledger row per `PageIdentity`.
- [x] Thread each page `cid` through `probe_subs` and `fetch_playurl_audio`.
- [x] Keep p0 and p1 status transitions independent and resumable; skip unresolved rows.
- [x] Two-page fixtures for subtitle and audio branches (no live HTTP).

### Task 3: Prove distinct artifacts and reruns

- [x] Assert two-page raw/SRT/audio/transcript paths cannot collide.
- [x] Assert a completed or failed p0 does not suppress p1.
- [x] Document legacy migration and page-aware resume behavior.

## Acceptance Criteria

- Two-page fixture produces `bvid:p0` and `bvid:p1` rows with distinct `cid` values and independent outcomes.
- Subtitle/audio requests use each page's cid; no automatic path selects only page zero.
- Artifact paths are distinct and stable across reruns.
- Legacy single-page rows migrate deterministically or remain explicitly unresolved; unresolved rows/artifacts are unchanged, visible to the operator, and never automatically assigned to a page.
- Full Python 3.12 test suite passes; no live HTTP or model downloads.

## STOP Conditions

- Missing stable cid/page identity in pagelist response (`list_pages` must not invent cid).
- Ambiguous legacy row ownership (preserve; do not assign `work_id`).
- Migration would overwrite an existing `{bvid}.pN` artifact or another `work_id` row.
- Multi-part `probe_subs`/`fetch_playurl_audio` without cid (must raise `AmbiguousPageError`, not `pages[0]`).
- A required interface change would break the frozen single-page compatibility surface without a Prepare revision.

## Prepare → Execute Handoff

After PM lock and specialist edits, execute tasks serially: migration tests, page-aware pipeline, then artifact/rerun tests. Plan QC is mandatory tri-review and QA is mandatory/full.

## Durable Review Summary

- Feature HEAD / merge: `361530d0a4da34de93bb86c778d1efbe061500c4` (FF into `iteration/iter-2026-08-archive-foundations`).
- QC tri + targeted revalidation: Approve (`qc-consolidated.md`). Open Critical/Warning: 0. Open R#: none.
- QA mandatory/full: Approve. `.venv-pm/bin/python -m pytest -q` → 147 passed.
- Deferred out of scope: per-part duration on locked `PageIdentity`.
