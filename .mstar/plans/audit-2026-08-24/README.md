# Audit Report — bilibili-asr-archive @ ab3cd97 (2026-08-24)

Scope: standard full audit of the Python 3.12+ CLI at `bilibili-asr-archive/`. This is a read-only review; no tests, builds, installs, formatters, or live API calls were run. Plans are stamped against the clean `main` checkout at `ab3cd97`.

## Findings

| # | Finding | Category | Impact | Effort | Risk | Confidence | Evidence |
|---|---------|----------|--------|--------|------|------------|----------|
| BUG-01 | Enumerate and archive every page of multi-part videos | BUG | High: subtitle/audio work is limited to page 1, so multi-part videos can archive the wrong or incomplete media | M | MED | HIGH | `bilibili-asr-archive/src/bili_asr/bili_client.py:422-490`; `bilibili-asr-archive/PLAN.md:35`; `bilibili-asr-archive/notes/spike-player-wbi-v2.md:23`; spec `.mstar/specs/asr-archive-cli.md:51-60` |
| BUG-02 | Make resume state represent the enumeration cursor | BUG | High: a risk stop after page N restarts at page 1 and repeatedly spends requests on already merged pages; the manifest does not record the continuation point | M | MED | HIGH | `bilibili-asr-archive/src/bili_asr/bili_client.py:357-399`; `bilibili-asr-archive/src/bili_asr/cli.py:145-206`; spec `.mstar/specs/asr-archive-cli.md:18-22, 93-99` |
| BUG-03 | Make the pilot execute the frozen two-branch proof | BUG | High: `pilot` only selects/report entries and never runs subtitle harvest, audio download, ASR, or archive output, so the documented MVP proof bar cannot be met by the command | M | HIGH | HIGH | `bilibili-asr-archive/src/bili_asr/cli.py:63-65,448-461`; `bilibili-asr-archive/README.md:23-38`; spec `.mstar/specs/asr-archive-cli.md:12-22, 35-42, 133-137` |
| BUG-04 | Preserve Bilibili API contract integrity | BUG | High: non-gone negative API codes are persisted as permanent `gone` state, while playurl audio requests omit required WBI/SESSDATA handling and can fail authenticated media retrieval | M | HIGH | HIGH | `bilibili-asr-archive/src/bili_asr/bili_client.py:24,106-108,471-490`; `bilibili-asr-archive/references/bilibili-API-collect/docs/misc/risk-and-stream.md:17-35`; `bilibili-asr-archive/PLAN.md:38`; `bilibili-asr-archive/tests/test_fetch_meta.py:105-125` |
| TEST-01 | Add real-entrypoint integration coverage for the full state machine | TEST | High: existing tests heavily cover helpers and mocks but do not pin multi-page parts, `asr` CLI transitions, pilot execution, or the installed `bili-asr` entrypoint | M | MED | HIGH | `bilibili-asr-archive/tests/` (no `test_cli_asr.py`/pilot workflow test); `bilibili-asr-archive/pyproject.toml:16-32`; `bilibili-asr-archive/tests/test_cli_help.py:11-17` |

## Direction (separate)

- **DIR-01 — Treat archive progress as a first-class operational ledger.** The manifest already owns per-video state (`bilibili-asr-archive/src/bili_asr/manifest.py:13-28`), while `PLAN.md:108-116` targets a 1,737-video archive. Adding explicit run metadata, cursor, last error, and coverage summaries would make risk-controlled batch operations inspectable and would support the documented full-corpus milestone without changing the pure transport seam. Trade-off: more schema/versioning and migration work.
- **DIR-02 — Add a search/export read model after the pilot is trustworthy.** The frozen spec names search as a non-goal for MVP (`.mstar/specs/asr-archive-cli.md:24-26`) while `PLAN.md:85-89,108-116` identifies SQLite FTS5/Meilisearch as a later milestone. A read-only SQLite FTS5 index over completed transcript metadata is the lowest-operational-cost next step once archive completeness and manifest recovery are proven. Trade-off: index invalidation and title/path escaping must be designed around the manifest as SSOT.
- **DIR-03 — Separate live-risk operations from deterministic local processing.** The current CLI composes network, filesystem, and ASR work in one command module (`bilibili-asr-archive/src/bili_asr/cli.py:145-488`). A later run coordinator could persist per-stage attempts and permit offline reprocessing of downloaded subtitles/audio. Trade-off: orchestration complexity; this should follow the state-machine and pilot plans, not precede them.

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001 | Multi-part video page-aware pipeline | P1 | M | none | TODO |
| 002 | Cursor-based resumable metadata enumeration | P1 | M | none | TODO |
| 003 | Executable two-branch pilot workflow | P1 | M | 005 | TODO |
| 004 | Full state-machine and installed-entrypoint integration tests | P2 | M | 003 | TODO |
| 005 | Bilibili API contract integrity | P1 | M | none | TODO |

Dependency graph: 001 is the media-part identity and all-parts prerequisite. 002 is independent because its metadata pagination cursor is separate from media-part identity. 003 primarily depends on 005 for authenticated/API-correct execution; automatic all-part pilot coverage also requires 001. 004 primarily depends on 003 and should integrate 001, 002, and 005 behavior where its fixtures cover those contracts. Plan 005 is independently executable and should precede API-sensitive pilot work.

## Findings considered and rejected

- Hardcoded WBI keys: not worth doing because the implementation derives keys from `nav` and the golden-vector test covers the permutation/signature (`bili_client.py:342-353`, `tests/test_fetch_meta.py:83-99`).
- CDN URL persistence: not worth doing because subtitle and audio paths deliberately omit signed URLs and existing tests assert this (`subtitles.py:80-101`, `audio.py:99-133`, `tests/test_subtitles.py:208-240`, `tests/test_audio.py:242-257`).
- Missing retry jitter or inter-page pacing: not worth doing because both are implemented and directly tested (`bili_client.py:225-228,395-399`, `tests/test_fetch_meta.py:221-249`).
- Broad SSRF/path-traversal claim: not worth doing because the current CLI consumes Bilibili-returned URLs and writes bvid-derived local paths; the evidence does not establish attacker-controlled input crossing a privileged interpreter. URL allowlisting remains a future hardening option, not a retained finding.
- Per-video exceptions swallowed by `except Exception`: not worth doing as a standalone finding because the CLI intentionally continues independent CDN/video failures; the pilot and state-machine gaps are retained.
- Dependency vulnerability upgrade: rejected because no read-only ecosystem audit was run under the role's no-runtime-execution constraint, and no reachable advisory evidence is present in the repository.
- Verification baseline/dependency lock policy: deferred as lower leverage than the retained correctness and contract plans; the repository still needs an explicit verification follow-up after those plans settle.

## Red-team dispositions

- BUG-01: survived; counter-example is any multi-page Bilibili video, simpler explanation does not account for the unconditional `pages[0]`, and cited lines show both subtitle and audio paths choose the first page. The single-P spike sample calibrates reachability but does not resolve structural incompleteness.
- BUG-02: survived; the `--resume` flag only preserves prior manifest entries while `fetch_pages()` always initializes `pn = 1`; cited lines support a missing continuation cursor.
- BUG-03: survived; `pilot` calls only `_pilot_select`, prints counts, and returns, while the README/spec describe a complete pilot proof.
- BUG-04: survived; cited classification and playurl code conflict with the local code contract and frozen gone-code semantics; existing `-101` coverage demonstrates the regression is pinned incorrectly.
- TEST-01: survived; test inventory lacks the listed command paths and tests invoke `main()` or `python -m` with `PYTHONPATH`, not the installed console script.
- Mixed per-video failure disposition: retained as an unplanned follow-up, not claimed as consistent. `bilibili-asr-archive/README.md:38` says a per-video failure exits 1, but `bilibili-asr-archive/src/bili_asr/cli.py:292,356,445` return 0 after mixed success; plan 004 should add characterization tests or a separately approved CLI contract correction.
- Verification baseline: deferred rather than retained as plan 005 because API-contract correctness is higher leverage and must be stabilized first.
- Potential secret exposure: not found in tracked source/docs; secrets were not reproduced.
- Prompt-injection content: none found in repository content inspected; repository files were treated as data.

## Validation and limitations

`mstar_audit_validate` is available and was run for every plan after writing. See the completion report for the validation results. No source or Git state was modified.

Unaudited: live Bilibili behavior beyond the cited single-P spike, actual Python 3.12 execution, installed-package behavior on Windows, ffmpeg/FunASR runtime compatibility, resolved dependency advisories (`pip-audit` was not run), throughput/storage measurements, full-corpus operational behavior, and external API availability. Historical metadata counts in `PLAN.md` were treated as context only, not current evidence. Verification/lockfile policy remains deferred; mixed per-video exit-code behavior remains an unplanned follow-up pending characterization.
