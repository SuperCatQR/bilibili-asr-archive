# Multi-Part Video Enumeration and Archival Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. This audit plan is a candidate for the normal Prepare -> Execute flow; it does not register or execute itself.

**Goal:** Automatically enumerate, process, and archive ALL `pagelist` parts for each Bilibili bvid, with a stable unique identity per part, independent resumability, and distinct subtitle/audio/transcript artifacts per part.

**Architecture:** Keep `bili_client.py` as the only HTTP owner. Expand the manifest identity from bare `bvid` to a stable video-part key such as `bvid:p<page_index>` (exact delimiter/schema must be locked in Prepare), carrying `bvid`, page index, `cid`, and page label as fields. Enumeration produces one child work item per pagelist entry; subtitle/audio/archive code receives that page identity and never falls back to `pages[0]` for an automatically enumerated multi-part video. Preserve the single-page compatibility view only as a migration/read adapter, not as the completion behavior.

**Tech Stack:** Python 3.12+, `requests`, pytest, existing `Transport` protocol and JSONL manifest.

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `ab3cd97`, 2026-08-24
- **State**: TODO

## Finding and current state

The current subtitle and audio paths each fetch a pagelist and unconditionally select the first item:

- `bilibili-asr-archive/src/bili_asr/bili_client.py:422-440` uses `cid = pages[0].get("cid")` for subtitle probing.
- `bilibili-asr-archive/src/bili_asr/bili_client.py:471-489` repeats `cid = pages[0].get("cid")` for audio playurl lookup.
- `bilibili-asr-archive/src/bili_asr/subtitles.py:59-102` and `audio.py:82-133` accept only a bvid and therefore cannot independently resume parts.
- The project plan explicitly calls out `bvid -> cid` and multi-P handling at `bilibili-asr-archive/PLAN.md:35`; the frozen architecture contract requires page-aware `cid` handling at `.mstar/specs/asr-archive-cli.md:51-60`.
- The live spike sampled only single-P videos, so it calibrates reachability but cannot disprove this structural completeness defect (`bilibili-asr-archive/notes/spike-player-wbi-v2.md:23`).

## Interfaces

Retain compatibility adapters where practical:

- `BiliClient.probe_subs(bvid: str, *, page_index: int = 0) -> list[dict[str, Any]]` may remain as a single-page adapter.
- `BiliClient.fetch_playurl_audio(bvid: str, *, page_index: int = 0) -> list[dict[str, Any]]` may remain as a single-page adapter.

Add a canonical page-aware interface used by enumeration, for example:

- `PageIdentity`: stable `work_id`, `bvid`, `page_index`, `cid`, and page label.
- `BiliClient.list_pages(bvid: str) -> list[PageIdentity]` or an equivalent result owned by the HTTP client.
- `probe_subs_page(page: PageIdentity)` and `fetch_playurl_audio_page(page: PageIdentity)`.
- `ManifestStore` rows keyed by `work_id`, with stable `bvid`, `page_index`, and `cid` fields.

The exact names may differ, but the executor must keep the page identity explicit at every boundary. Signed URLs remain transient and must never enter a manifest key, field, log, or archive filename.

## Manifest and artifact migration (must be designed, not deferred)

- For a single-page legacy row keyed by `bvid`, preserve its stable metadata and migrate it to `bvid:p0` (or the locked equivalent) exactly once, retaining a backward-compatible lookup from bare bvid when unambiguous.
- For a multi-page bvid, create one row per page identity, e.g. `bvid:p0` and `bvid:p1`; each row independently progresses through `meta_ok -> sub_checked -> subtitle_done` or `needs_audio -> audio_ok -> archived`.
- Include `page_index`/`cid` in raw subtitle, audio, and transcript paths or another collision-proof naming scheme. Two pages must never overwrite the same `{bvid}.srt`, `{bvid}.m4a`, or markdown artifact.
- Persist migration/version metadata atomically using the existing same-directory temp-file and `os.replace` pattern (`manifest.py:59-70`). Define behavior for duplicate legacy rows, missing `cid`, and reruns during migration in Prepare.

## In scope

- `bilibili-asr-archive/src/bili_asr/bili_client.py`
- `bilibili-asr-archive/src/bili_asr/subtitles.py`
- `bilibili-asr-archive/src/bili_asr/audio.py`
- `bilibili-asr-archive/src/bili_asr/cli.py`
- `bilibili-asr-archive/src/bili_asr/manifest.py`
- `bilibili-asr-archive/src/bili_asr/archive.py` where filenames need page identity
- `bilibili-asr-archive/tests/test_subtitles.py`
- `bilibili-asr-archive/tests/test_audio.py`
- `bilibili-asr-archive/tests/test_manifest.py`
- `bilibili-asr-archive/tests/test_archive_md.py`
- New focused tests under `bilibili-asr-archive/tests/` as needed
- `bilibili-asr-archive/README.md` for migration/resume behavior

## Out of scope

- Cursor state for metadata page enumeration; that is plan 002 and is independent of media-part identity.
- Multi-video concurrency or rate-limit tuning; existing sequential pacing remains.
- Search/indexing, diarization, LLM cleanup, GUI, or external downloader integration.

## Conventions and exemplars

- Inject transport through `BiliClient(transport=...)` as in `tests/test_subtitles.py:24-100` and `tests/test_audio.py:25-92`; do not add live-network tests.
- Preserve retry, cookie, and WBI behavior in `bili_client.py:249-340`; page expansion is data plumbing, not a second HTTP implementation.
- Persist only stable identifiers and relative artifact paths, matching `subtitles.py:95-101`, `audio.py:135-148`, and `archive.py:62-67`.

## Tasks

### Task 1: Design and implement the page identity migration

**Files:** Modify `manifest.py`, `bili_client.py`, `archive.py`; test `test_manifest.py`, `test_archive_md.py`.

- [ ] Define and implement the canonical `work_id`, page fields, schema/version marker, legacy bare-bvid adapter, and duplicate/missing-cid behavior. This is the planned manifest identity migration, not an immediate STOP condition.
- [ ] Implement atomic migration from existing single-page rows without losing status or stable metadata.
- [ ] Ensure page-aware artifact names are deterministic and collision-free.

Run: `python -m pytest bilibili-asr-archive/tests/test_manifest.py bilibili-asr-archive/tests/test_archive_md.py -q` -> migration, key, and filename tests pass.

### Task 2: Enumerate all pages and run each through subtitle/audio branches

**Files:** Modify `bili_client.py`, `subtitles.py`, `audio.py`, `cli.py`; test `test_subtitles.py`, `test_audio.py`, and a new `test_multipart_pipeline.py`.

- [ ] Enumerate every pagelist entry for a bvid and create one manifest work item per page.
- [ ] Pass each page's own `cid` through subtitle and playurl requests; no automatic multi-page path may use `pages[0]` as the only work item.
- [ ] Make each page independently resumable: a failure or completed state for p0 must not suppress or overwrite p1.

Run: `python -m pytest bilibili-asr-archive/tests/test_multipart_pipeline.py bilibili-asr-archive/tests/test_subtitles.py bilibili-asr-archive/tests/test_audio.py -q` -> two-page fixtures show two work IDs, two selected cids, and independent outcomes.

### Task 3: Prove distinct artifacts and reruns

- [ ] Add a two-page fixture that produces two distinct subtitle/raw/SRT or audio/transcript artifacts.
- [ ] Assert both rows can be rerun independently and that one page's completed state does not skip the other.
- [ ] Document legacy migration and page-aware resume in README.

Run: `python -m pytest bilibili-asr-archive/tests -q` -> full suite passes with no duplicate page artifacts.

## STOP conditions

- If the exact Bilibili pagelist response lacks stable `cid`/page identity, STOP and report which additional endpoint or identifier is required; do not silently collapse pages.
- If a legacy bare-bvid row has ambiguous page ownership, STOP that row's migration and preserve it for explicit operator resolution; do not guess.
- If a page-aware artifact migration would overwrite an existing file, STOP before deleting or replacing it and report the collision.

## Drift check

Before execution run:

`git diff --stat ab3cd97..HEAD -- bilibili-asr-archive/src/bili_asr bilibili-asr-archive/tests bilibili-asr-archive/README.md`

If any in-scope file changed, compare the page identity, migration, and `pages[0]` excerpts above with live code. Update the plan only through Prepare clarification; do not improvise a schema migration.

## Done criteria

- [ ] A two-part pagelist fixture automatically creates two stable, unique, independently resumable manifest identities for one bvid.
- [ ] The two identities persist distinct `page_index`/`cid` values and are both processed by the pipeline.
- [ ] Subtitle and/or audio requests for the two identities use their distinct cids.
- [ ] A two-part bvid produces two distinct manifest identities and two distinct raw/subtitle/audio/transcript artifact paths with no overwrite.
- [ ] Completing or failing p0 does not skip, mark, or overwrite p1; a rerun processes only the unfinished identity.
- [ ] Legacy single-page rows migrate deterministically and remain readable through the documented compatibility adapter.
- [ ] `python -m pytest bilibili-asr-archive/tests -q` exits 0.
- [ ] `grep -R "pages\[0\]" bilibili-asr-archive/src/bili_asr` returns no automatic multi-page work selection.
- [ ] `git status --short` shows only in-scope files changed.

## Prepare -> Execute handoff

During Prepare, lock the exact work-id delimiter, migration/version format, artifact naming convention, and whether page metadata is fetched during `fetch-meta` or lazily before media work. During Execute, land migration tests first, then the all-pages pipeline, then distinct-artifact/rerun tests. This plan is complete only when a two-page fixture proves two durable work items, not merely a caller-selected second-page request.
