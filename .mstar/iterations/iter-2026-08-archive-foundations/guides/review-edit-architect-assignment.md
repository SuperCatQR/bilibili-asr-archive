# Phase 1 Review-and-Edit Assignment: architect

**IDENTITY**
- Execute as: architect
- Act as: architect
- Who runs this turn: Phase 1 specialist reviewer/editor
- Delegation: forbidden
- Task category: docs / architecture
- Iteration: `iter-2026-08-archive-foundations`
- Working branch: `main` (Phase 1 documentation draft only; do not commit or create branches)

**You are a leaf executor. You MUST NOT:**
- invoke or delegate to any other agent;
- create commits, branches, worktrees, pull requests, or pushes;
- modify product source, tests, dependency files, `{KNOWLEDGE_DIR}`, or root workflow status JSON;
- mark the compass locked or claim Phase 1 complete.

## Skill load

Read in order: `mstar-harness-core` → `mstar-host` → `references/dsh.md` → `mstar-roles` → `references/architect.md` → `mstar-phase-gates` → `mstar-conventions` → `mstar-coding-behavior` (for naming/interface discipline) → `naming-analyzer` before proposing type/function/file names.

## Scope

Review and edit only these draft artifacts:

- `.mstar/iterations/iter-2026-08-archive-foundations/delivery-compass.md`
- `.mstar/iterations/iter-2026-08-archive-foundations/README.md`
- `.mstar/plans/20260824-multipart-page-aware-pipeline.md`
- `.mstar/plans/20260824-cursor-based-resume.md`

You may create or edit iteration-package files under `.mstar/iterations/iter-2026-08-archive-foundations/{guides,specs}/` when they lock module boundaries, interfaces, or data contracts. Do not write `{KNOWLEDGE_DIR}` or `{SPECS_DIR}`.

## Locked product decisions (do not reopen)

- Direction: archive completeness foundation, not pilot or test-only scope.
- Plans: multi-part page-aware pipeline, then cursor-based metadata resume.
- Canonical part identity: `bvid:p<zero-based-page-index>`.
- `cid` is a field, not the primary key.
- Ambiguous legacy bare-bvid rows stay byte-for-byte preserved, unresolved, excluded from automatic page processing.
- Cursor persistence: archive-root atomic `meta-cursor.json` sidecar.
- Cursor states distinguish risk-interrupted, `limited`, and `complete`.
- Delivery branches: `iteration_base_branch=main`, `spec_integration_branch=iteration/iter-2026-08-archive-foundations`, `target_branch=main`.

## Live code facts to reconcile

- `ManifestStore` currently keys JSONL by `entry["bvid"]` (`bilibili-asr-archive/src/bili_asr/manifest.py`).
- `harvest_subtitle` and `download_audio` currently take a bare `bvid` and write `{bvid}.json` / `{bvid}.srt` / audio by that name.
- `BiliClient.probe_subs` and `fetch_playurl_audio` currently select `pages[0]`.
- `BiliClient.fetch_pages()` always starts `pn = 1` and has no start-page/cursor seam.
- `bili_client.py` remains the only HTTP owner; cursor filesystem I/O must not enter that module.
- Knowledge pattern: `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md` still describes a bvid-keyed manifest; do not edit knowledge now, but design the page-aware ledger so a later compound promotion can replace that pattern.

## Architecture review objectives

Lock a target architecture that implementers can execute without guessing:

- Typed `PageIdentity` (or better name after naming-analyzer) and work-id ownership at every seam: client, manifest, subtitle, audio, archive paths.
- Manifest key migration: how `work_id` becomes the JSONL key while `bvid` remains a field; compatibility lookup for unambiguous legacy rows; unresolved-row schema.
- Artifact naming that cannot collide across pages, including raw subtitle, SRT, audio, and transcripts.
- Cursor helper ownership: CLI/manifest seam, atomic replace, mid-keyed records, no HTTP/filesystem coupling.
- Optional `start_page` on `fetch_pages` without changing retry taxonomy or forcing I/O into the HTTP client.
- Serial plan order and STOP conditions that remain technically honest.
- Preserve transport protocol, SESSDATA/signed-URL redaction, and the prior-iteration gone/risk contract.

Write the architecture package into the iteration `specs/` directory using the architect output structure (clarify validation, selected approach, module boundaries, API/data contracts, risks/rollback, validation plan). Edit the two plans so Interfaces/Tasks/STOP match that package.

## Required return

State files edited, architecture decisions locked, remaining impactful ambiguities if any, and whether the draft is ready for writing-specialist review. Do not mark Phase 1 locked. Put the completion report in the closing message.
