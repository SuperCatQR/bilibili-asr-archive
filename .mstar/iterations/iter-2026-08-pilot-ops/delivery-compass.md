---
iteration_id: iter-2026-08-pilot-ops
start_date: 2026-08-25
status: completed
end_date: 2026-08-25
iteration_base_branch: main
target_branch: main
plans:
  - 20260825-executable-pilot-workflow
  - 20260825-state-machine-entrypoint-tests
  - 20260825-operational-ledger
  - 20260825-search-export-fts5
  - 20260825-run-coordinator-offline
---

# iter-2026-08-pilot-ops Delivery Compass

## Product Outcome

An operator can prove the frozen MVP two-branch pilot on a bounded `N`, inspect per-run progress (cursor, last error, coverage) without opening JSONL by hand, search/export completed transcripts from a derived FTS5 read model, and reprocess already-downloaded artifacts offline without mixing that work into live-risk HTTP.

## Scope

Executable two-branch pilot + operational layer: run ledger, FTS5 search/export, run coordinator + offline reprocessing.

- Prove the frozen MVP proof bar (`.mstar/specs/asr-archive-cli.md`): `bili-asr pilot --n N` runs subtitle-hit and audio→ASR to terminal states (plan A); pin the state machine and installed `bili-asr` entrypoint with deterministic integration tests (plan B).
- Operator-visible ledger: persist per-run metadata (cursor, last error, coverage summary) and surface it via `status` / `runs` without changing JSONL row schema (plan C / DIR-01).
- Read-only SQLite FTS5 search/export over completed transcript metadata; manifest stays SSOT (plan D / DIR-02 / PLAN.md M4). Meilisearch is out of this iteration.
- Run coordinator that records per-stage attempts and supports `--offline` reprocessing of on-disk artifacts only (plan E / DIR-03). `run` complements frozen `pilot`; it does not replace the MVP proof command.

New CLI verbs (`runs`, `search`, `export`, `run`) are this iteration's product surface. They extend the frozen MVP command list; they do not rewrite MVP goals, risk taxonomy, or JSONL schema.

## Direction Lock (autonomous)

- **Locked direction**: "executable two-branch pilot + operational layer: run ledger, FTS5 search/export, run coordinator + offline reprocessing"
- **Rationale** (evidence): audit plan 003 (P1, deps on 005) and plan 004 (P2, deps 003) are the deferred next items from `iter-2026-08-archive-foundations` `## Roadmap Position`. Prior iteration outcomes 001/002/005 merged to `main` at `559dfcb`. DIR-01/02/03 in `.mstar/plans/audit-2026-08-24/README.md` plus `PLAN.md` M4 (SQLite FTS5 检索) are the operational-layer candidates. All five are business delivery; none are process-only.
- **Acceptance criteria** (iteration-level): see `## Acceptance Criteria` (single SSOT; do not diverge this bullet list).
- **Non-goals**: see `## Non-Goals`.
- **Scale budget**: XL — 5 business plans (A–E). No process-only plans counted.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260825-executable-pilot-workflow | Executable two-branch pilot workflow | Done | Merged FF at `c4ce9bb`; QC/QA Approve; 180 passed |
| 20260825-state-machine-entrypoint-tests | State-machine + installed entrypoint integration tests | Done | Merged FF at `7965288`; QC/QA Approve; 189 passed |
| 20260825-operational-ledger | Operational run ledger | Done | Merged FF at `cffe0f1`; QC tri Approve; QA Pass; 218 passed |
| 20260825-search-export-fts5 | SQLite FTS5 search/export read model | Done | Merged FF at `5b392cc`; QC tri Approve; QA Pass; 255 passed |
| 20260825-run-coordinator-offline | Run coordinator + offline reprocessing | Done | Merged FF at `d665034`; QC tri Approve; QA Pass; 277 passed |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Direction lock + compass | 2026-08-25 | done |
| Plan A (pilot) complete | 2026-08-25 | done |
| Plan B (integration tests) complete | 2026-08-25 | done |
| Plans C/D/E complete | 2026-08-26 | done |
| QC + QA complete | 2026-08-26 | done |
| Iteration close | 2026-08-26 | done |

## Acceptance Criteria

Measurable operator/test bar (all under fakes; no live HTTP, model downloads, or real media transfer):

1. **Pilot (MVP proof bar):** `bili-asr pilot --n N` (default N is the frozen ~20; `--n` may be lowered for smoke) executes both subtitle-hit and audio→ASR branches to terminal states. Subtitle-hit rows archive without ASR. Audio rows archive only after transcript write. Missing optional ASR → nonzero exit, install hint, row not archived. Unavailable branch coverage → nonzero summary naming the missing branch. Rerun is idempotent. If a selected bvid has multiple pagelist parts, each part is processed or reported failed (page-aware identity from the prior iteration).
2. **Integration tests:** every frozen manifest transition used by the shipped commands, plus installed `bili-asr --help` / `bili-asr status` as console-script subprocesses (not `PYTHONPATH` as install proof). Risk exhaustion → exit 2, last stable state preserved.
3. **Ledger:** after `fetch-meta` (exit 0 or 2) and after bounded batch commands in this iteration (`pilot`, and `run` once plan E lands), `bili-asr status` and `bili-asr runs` show cursor snapshot, last API error code (not raw exception text), and per-status coverage (manifest `status` counts; cursor `state` remains `risk_interrupted`/`limited`/`complete`) without claiming full enumeration for `limited`. Sidecar JSONL; no manifest row schema change.
4. **Search/export:** `bili-asr search <query>` ranks completed transcript metadata (rows with transcript artifacts: `archived` / `subtitle_done` with archive paths). `bili-asr export --format json|csv` writes metadata; `--with-text` optional. Neither command rewrites the manifest. Empty search → exit 1 with a clear message.
5. **Coordinator:** `bili-asr run --offline` never issues HTTP and only reprocesses artifacts already on disk; missing input is skipped with reason. Per-stage attempts persist. Per-item failures do not stop the batch. `run` does not replace `pilot`.
6. **Safety:** full Python 3.12 suite passes. Credentials, signed URLs, and raw exception text absent from manifests, cursors, ledgers, search index, coordinator records, and diagnostics.

## Non-Goals

- Full-corpus scheduling, concurrency, diarization, LLM cleanup/polish, search UI, GUI, redistribution of media.
- Meilisearch; replacing pytest; dependency upgrades; pip-audit / installed-entrypoint CI matrix (next verification slice).
- Manifest schema migration; changing retry limits or the frozen risk taxonomy.
- Replacing frozen `pilot` with `run`; changing MVP proof bar to full-corpus coverage.
- Mixed per-video exit-code characterization from audit 004 red-team (README vs CLI) — deferred follow-up, not this iteration.
- Live API operations beyond the operator-invoked bounded `pilot` / `run` (non-offline) surfaces.

## Roadmap Position

- **Current iteration (iter-2026-08-pilot-ops)**: **delivered** — executable two-branch pilot + operational layer (run ledger, FTS5 search/export, run coordinator + offline reprocessing). Merged on `iteration/iter-2026-08-pilot-ops` at `d665034`.
- **Next iteration**: full-visible-corpus scheduling once this PR lands on `main`; trigger: both pilot branches covered + integration suite green + ledger/search inspectable; owner: project-manager with fullstack-dev.
- **Following slice**: installed-entrypoint CI matrix, pip-audit/verification baseline, and mixed per-video exit-code characterization once command surface settles.

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot `workflows/<id>/snapshot.json` branch anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-08-pilot-ops` |
| `target_branch` | `main` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Pilot grows unbounded / calls live network in tests | Medium | High | Bound by N, fake transport + stubbed ASR in tests, missing-ASR nonzero contract |
| Ledger/FTS5 breaks JSONL compatibility | Medium | High | Sidecar/read-only models; last-write-wins manifest untouched; migration-free |
| Offline reprocessing conflicts with live state | Medium | High | Run coordinator owns per-stage attempt ledger; deterministic local reprocessing only over downloaded artifacts |
| Integration suite pokes live API | Low | High | Fake transport + lazy-import seams; no live calls permitted |

## Iteration package

| Path | Purpose |
|------|---------|
| `guides/` | Phase 1 review-chain assignments (snapshot-only) |
| `README.md` | Documents table, promotion log |
| `specs/` | Unused this round — warehouse MVP stays frozen at `.mstar/specs/asr-archive-cli.md`; no iteration spec drafts |

## Quality Gate Summary

> Filled at iteration-close.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260825-executable-pilot-workflow | Approve | Pass | none | `.mstar/plans/20260825-executable-pilot-workflow.md#durable-review-summary` |
| 20260825-state-machine-entrypoint-tests | Approve | Pass | none | `.mstar/plans/20260825-state-machine-entrypoint-tests.md#durable-review-summary` |
| 20260825-operational-ledger | Approve (tri, re-review) | Pass | none | `.mstar/plans/20260825-operational-ledger.md#durable-review-summary` |
| 20260825-search-export-fts5 | Approve (tri, QC3 re-review) | Pass | none | `.mstar/plans/20260825-search-export-fts5.md#durable-review-summary` |
| 20260825-run-coordinator-offline | Approve (tri, re-review) | Pass | none | `.mstar/plans/20260825-run-coordinator-offline.md#durable-review-summary` |

## Compound Round Summary

> Filled at iteration-close.

- Crystallized documents: `architecture-patterns/operational-sidecars.md` (new); pointer added on `bilibili-asr-archive-cli.md`
- Iteration package promotion: guides kept as snapshot-only (Phase 1 assignment copies; Q1–Q8 ≤2); no specs in package
- New CONCEPTS.md entries: none (no new domain vocabulary beyond existing work_id / sidecar terms)
- compound-refresh triggered: no (single new doc, low overlap)

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- What went well: serial SDD + zero-residual QC produced five merged plans; sidecars kept JSONL frozen; coordinator suite closed at 277 passed
- What to improve: workflow snapshot lagged durable QC/QA reports (plan E sat InReview after Approve/Pass); compass Plans table drifted from snapshot
- Next iteration recommendation: full-visible-corpus scheduling after this PR lands; keep `run` complementary to `pilot`
