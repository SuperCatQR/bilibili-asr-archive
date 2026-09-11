# QC Consolidated — 20260909-metadata-cli-smoke

- Iteration: `iter-2026-09-bilibili-api-sqlite` · Plan: `20260909-metadata-cli-smoke` (SDD, Batch 3)
- Review range / Diff basis: `18b6353..c86daa7` (3 commits: 849c046, cf490ff, c86daa7)
- Working branch (verified by all seats): `feature/20260909-metadata-cli-smoke`, HEAD `c86daa7`, worktree clean
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-metadata-cli-smoke`
- Seats: `qc-specialist` (qc1.md), `qc-specialist-2` (qc2.md), `qc-specialist-3` (qc3.md) — initial tri wave, N=3, same assignment scope
- Findings cleanup: `zero-residual`

## Seat verdicts (initial wave)

| Seat | Verdict | 🔴 Critical | 🟡 Warning | 🟢 Suggestion | ⚪ Unconfirmed |
|------|---------|-------------|------------|----------------|-----------------|
| qc-specialist (qc1) | Request Changes | 0 | 1 | 12 | 3 |
| qc-specialist-2 (qc2) | Request Changes | 0 | 2 | 8 | 6 |
| qc-specialist-3 (qc3) | Request Changes | 0 | 2 | 8 | 3 |

## Gate decision: **Request Changes** (docs fix wave required)

Zero Critical across all seats. After cross-seat dedup the five seat-Warnings collapse into
TWO distinct docs-contract items (operator-facing accuracy against the plan's docs-accuracy
acceptance criterion); both are behavior-free text fixes. All three seats independently
verified the delivered composition contract-faithful: single entrypoint, repository-only
`archive.db` writes, zero legacy-sidecar I/O on the new path, structural redaction, honest
cursor/`running` rendering, bounded live smoke, genuine legacy-test supersession
(34 retired + 4 rewritten; 857−34+31=854→857→858 reconciles), C1–C6 carries applied.

## Consolidated Warnings (deduped; traceable to qcN findings)

| ID | Finding | Sources | Fix |
|----|---------|---------|-----|
| W1 | Exit-2 contract drift undocumented: the adjudicated C5 path (unexpected non-gateway exception → exit 2, fixed "unexpected error" message, NO scalar code, no cursor-unchanged guarantee; run may stay `running`) appears in no exit table; spec still says "Gateway failure after bounded retry" though the Plan-2 gateway is fail-fast per page; handler docstring (cli.py:517-519) self-contradicts; old README "exit 1 = usage/config or unexpected error" clause dropped without replacement | qc1 W-001(a,b) · qc2 W-002 · qc3 F-001 | Text-only: spec note (fail-fast + C5 no-code variant), README + docs exit-2 sub-lines (no cursor-unchanged claim on the unexpected path), handler docstring correction |
| W2 | Implicit `DEFAULT_PAGE_LIMIT=10` bound absent from README fresh-start section and docs exit-0 rows; both exit-0 rows claim "empty page reached or **explicit** `--limit-pages` bound" — factually false for the default run (silently stops at 10 pages, outcome `limited`, exit 0); spec:13 omits the applied default | qc1 W-001(c) · qc2 W-001 · qc3 F-002 | Document the default bound in README fresh-start section + docs + spec note; amend exit-0 rows to cover the default-bound case |

## Suggestions (disposition — zero-residual)

**Fix now (ride the same docs/hygiene commit):**
- S-fix-1: stale `--help` on `status`/`runs` ("manifest"/"ledger" wording) → SQLite wording (qc1 S1 · qc2 S-003 · qc3 F-003).
- S-fix-2: README anchor missing hyphen (`#fetchmeta--status--runs` → `fetch-meta` slug) (qc1 S8 · qc2 S-005 · qc3 F-007).
- S-fix-3: unbounded error-code history scan per `runs` call → bounded (LIMIT) query; keep the documented composition-root raw-SQL exception (qc3 F-005 partial).
- S-fix-4: blank `--sessdata ""` falls through to `BILI_SESSDATA` while the docstring claims "blank = anonymous" → make `""` explicit-anonymous (consistent semantics) + align the live-smoke env-presence check (`is None` vs truthiness) (qc1 S4 · qc2 S-004 · qc3 F-004).
- S-fix-5: read commands never close the DB connection → close in `finally` (resource hygiene); document that `open_database`'s schema-ensure is an idempotent no-op on a current-version DB (not silent upgrade within this iteration) (qc1 S11 · qc2 S-001 partial · qc3 F-006 partial).
- S-fix-6: `runs` same-second ordering tie-break → deterministic `ORDER BY started_at DESC, run_id DESC` (qc1 S12).
- S-fix-7: test-polish bundle — constant-only default-bound unit test; E2E test-2 leak-scan non-vacuity; unrehearsed `complete` sub-branch scripted over the seam; `status` output direct no-leak scan (restores the retired redaction-guarantee coverage) (qc1 S7 · qc2 S-007 · qc3 F-009).

**Accepted with rationale (no code):** CLI-layer raw SQL as a documented composition-root exception (qc1 S2 · qc2 S-002 · qc3 F-005 remainder); "collected N page(s)" wording before the failure line (honest outcome= inline; cosmetic) (qc1 S5 · qc2 S-006 · qc3 F-008); anonymous-skip breadth (all seats re-judged safe-by-design; assertions run first) (qc1 S9); `status` pending full materialization (qc2 S-008); `ARCHIVE_DATABASE_NAME` duplication (adjudicated, comment-guarded) (qc1 S3).

**Carried to next iteration (durable roadmap):** read-path TOCTOU + connection lifecycle hardening beyond this iteration's scope (qc2 S-001 / qc3 F-006 remainder); `ingestion_runs` is metadata-scoped — the subtitle/transcript process-record schema decision must be explicit in the next plan (qc3 F-010).

## ⚪ Unconfirmed (→ mandatory QA gate; pre-dispositioned routings, consistent across seats)

- U1: full-suite/focused counts implementer-reported (854→857→858 + skips; arithmetic + replacement mapping reconciled) → QA re-runs.
- U2: opted-in live smoke execution — anonymous bounded-failure skip AND credential happy path (SESSDATA) → QA gate owns the run; offline rehearsal of both branches verified in the diff.
- U3: isolated-install packaging evidence implementer-reported (static pyproject inspection supports) → QA re-run or verifies the existing isolated-install tests.
- U4: third-party runtime side-effects outside the temp root during the live smoke (bilibili-api package caches) → QA owns observation during the opted-in run.

## Revalidation round (targeted, N=3: all three seats raised Warnings)

Fix wave landed as commit `1a99751` (`c86daa7..1a99751`, 7 files, +277/−91; storage /
pyproject / uv.lock untouched; live smoke still opt-in-skipped; focused 38 passed +1 skipped,
full 861 +2 skipped — implementer-reported; TDD red→green on the sessdata semantics). The PM
separately edited the frozen spec's exit-code section (harness artifact; text-only). All
three seats re-derived their evidence from the diff and the post-fix sources:

- qc-specialist (qc1.md `## Revalidation`): **W-001 RESOLVED** across all four artifacts
  (spec / README / docs / handler docstring; cross-seat sub-items also honestly replaced);
  S-fix-1…7 delivered as dispositioned; regression lens clean — behavior deltas are exactly
  the disclosed three (blank `--sessdata` explicit-anonymous with verified blast radius,
  bounded per-run LIMIT query, read-command finally-close). Verdict floor = **Unconfirmed**
  solely per its three ⚪ QA routings (template rule), with explicit "no further fix wave
  needed from this seat".
- qc-specialist-2 (qc2.md `## Revalidation`): **W-001/W-002 RESOLVED** (re-derived) —
  spec↔README↔docs↔docstring↔test-docstring five-way consistency; all 8 suggestions
  dispositioned; manual live probe accepted (disclosed, does not discharge U2). Verdict
  **Approve**.
- qc-specialist-3 (qc3.md `## Revalidation`): **F-001/F-002 RESOLVED** (four-way
  consistent); all suggestions dispositioned; disclosed deviation accepted; TOCTOU remainder
  carried. Verdict **Approve**.

PM dispositions of seat-1's two coverage notes (both recorded here per 未提及 = 未审查):
- qc1-S6 (test-local helper duplication across the three new test files) — **accepted with
  rationale**: deliberate scope-respect carried over from Task 2's same finding; consolidation
  is a polish candidate for the next iteration's test-suite touch, not this wave.
- qc1-S7(a) (positive control absent from `test_metadata_cli.py`'s no-secret test) —
  **accepted with rationale**: the persisted-row sentinel scan at the write boundary remains
  the structural guarantee (restored coverage covers status/E2E render paths); optional polish
  for a future docs/test touch.

## Final gate decision: **QC converged — Approve conditional on the mandatory QA gate**

- Defect state after convergence: zero unresolved Critical/Warning/Suggestion across all
  seats (seat 2 Approve with both W resolved; seat 3 Approve; seat 1 no open defects —
  Unconfirmed solely per the ⚪ template floor, with the stated resolution path).
- Per the consolidated verdict math the plan-level gate Approve is issued **after** the
  mandatory QA gate closes the routed evidence with fresh L4 runs:
  U1 full-suite + focused re-run at the post-fix baseline (expect 861 passed + 2 skipped;
  focused 38 + 1 skipped), U2 opted-in live smoke (anonymous bounded-failure skip + credential
  happy path via `BILI_SESSDATA`; the pinned dist must be installed — `uv sync` first), U3
  isolated-install packaging evidence, U4 third-party side-effect observation during the live run.
- Zero open residual R# (`zero-residual` satisfied); next-iteration carries (TOCTOU remainder,
  `ingestion_runs` metadata-scoped note, test-helper consolidation polish) tracked in the
  plan's Durable Roadmap.
- Final reviewed head: `1a99751` on `feature/20260909-metadata-cli-smoke`; cumulative plan
  branch `18b6353..1a99751` (4 commits).
