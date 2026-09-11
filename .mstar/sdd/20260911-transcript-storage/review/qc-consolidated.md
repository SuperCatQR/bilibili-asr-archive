# QC Consolidated — 20260911-transcript-storage

- Iteration: `iter-2026-09-subtitle-transcript-sqlite` · Plan: `20260911-transcript-storage`
- Review range / Diff basis: `6ee7c6a..5f93e05` (4 commits, 8 files, +4028/−58)
- Working branch (verified by all seats): `feature/20260911-transcript-storage`, HEAD `5f93e05`, worktree clean
- Seats: `qc-specialist` (qc1.md), `qc-specialist-2` (qc2.md), `qc-specialist-3` (qc3.md) — tri wave, N=3

## Seat verdicts

| Seat | Verdict | Critical | Warning | Suggestion | Unconfirmed |
|------|---------|----------|---------|------------|-------------|
| qc-specialist (qc1) | Approve | 0 | 0 | 4 | 0 |
| qc-specialist-2 (qc2) | Approve | 0 | 0 | 2 | 0 |
| qc-specialist-3 (qc3) | **Request Changes** | 0 | **1** | 4 | 0 |

Both Approving seats verified the evidence channel independently (qc1: the package diff is byte-identical to
the live diff, 175 516 chars; qc3 reproduced `git diff --check` itself), re-derived the schema contract from
the pin's own artifacts, and re-judged the L2 severities.

## Gate decision: Request Changes → one test-only fix wave, then targeted re-review

### The Warning

| ID | Finding | Disposition |
|----|---------|-------------|
| W1 (QC3-001) | The locked pending order's last key (`page_index ASC`) is **not falsifiable**: the committed fixture inserts every part of a `bvid` in ascending page order, so rowid order coincides with page order and the `drop page_index ASC` mutation passes — while this plan's DoD claims the order is "pinned by tests", and the residue was recorded as a "may add either" nit with **no owner** | **Fix now** (seat 3's cheaper route): test-only, insert a part whose `page_index` is higher than a sibling inserted after it and extend the expected list, so the mutation fails; the plan's roadmap line now records the closure |

### Suggestions (deduped) and dispositions

- **QC1-001 / QC2-S1 (same class, backlog rotation):** `v_pending_subtitles` treats any `transcripts` row as
  "has a caption" and the write paths do not scope an attempt to its run's `kind`, so `asr-local` transcripts
  (or a mis-kinded attempt) would silently rotate a part out of the subtitle backlog. Spec-locked behaviour →
  **recorded in the plan's durable roadmap** with the audio/ASR iteration as the deciding owner.
- **QC1-002 / QC2-S2 (same class, hardening):** the structural guard omits `transcript_segments` and the
  "no UPDATE/DELETE code path" immutability mechanism is inspection-only → **recorded as nits** in the durable
  roadmap (both unreachable today: `open_database` heals the table; the source is clean).
- **QC1-004:** `start_acquisition_run` inherits the shipped "commit without rollback on failed insert"
  pattern → accepted (mirrors `MetadataRepository.start_run`; single-connection usage).
- **QC2 handoff (projections):** after a revert-to-older-content acquisition, default `read_transcript`
  returns `MAX(version)` while the newest attempt references the older matched version → **recorded as a
  handoff** for the next iteration's projection owner (both facts are stored and spec-locked).
- **QC3-002 / QC3-003 / QC3-005 (CLI-plan readiness):** the repository's missing `__init__` guard, the
  `docs/metadata-storage.md` sentence that this plan invalidates, and the `SchemaContractError` line/root
  assertion → **recorded in the CLI plan** (QC3-002 is additionally closed in this plan's fix wave 2 by making
  `__init__` fail fast with the bounded error).
- **QC3-004 (performance characteristic):** the pending view's `ROW_NUMBER()` CTE has no predicate pushdown
  and attempts are never pruned → **recorded in the durable roadmap** so the audio/ASR iteration inherits it.

### ⚠️ Hand-off to the mandatory QA gate

1. The full offline suite at HEAD (`1201 passed, 3 skipped`) and every mutation claim are implementer evidence
   at each task level — reproduce the suite yourself, plus the legacy-database bootstrap guarantee on the
   **shipped** `open_database` path (not only the synthetic fixture).
2. Confirm the fix wave's ordering pin actually discriminates (the `drop page_index ASC` mutation must fail).
3. Confirm the CLI plan has absorbed F3, R1's carriage, and the three readiness items before plan 3 is
   dispatched.
4. `docs/metadata-storage.md` must land before the CLI plan's Done (its own file list owns it).

## Residuals

No residual was registered by this plan. The only open entry remains **R1** from
`20260911-subtitle-gateway` (`low`, `decision: defer`, target = the next plan whose file list includes
`sources/bilibili_api_gateway.py`; this plan does not touch that file, so R1 correctly stays open).
