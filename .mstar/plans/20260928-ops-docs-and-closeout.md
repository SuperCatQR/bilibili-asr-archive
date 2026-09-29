---
plan_id: 20260928-ops-docs-and-closeout
iteration: iter-2026-09-ops-readiness
iteration_compass: .mstar/iterations/iter-2026-09-ops-readiness/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: [20260928-queue-cli-cutover, 20260928-hotword-injection-governance, 20260928-proofread-pipeline, 20260928-transcript-search]
qa_gate: mandatory
qa_mode: targeted
execution_mode: inline
execution_mode_reason: >-
  CORRECTED 2026-09-28. The original note claimed the host refused delegation on that session.
  That was wrong: `subagent` was available and four implementers DID run, each reporting DONE
  (they committed on their own worktrees; an early worktree check in the coordinating thread read
  "no commits yet" and wrongly concluded dispatch had failed, so the PM then re-implemented inline
  in parallel — the duplicate files later mistaken for phantom work came from those live
  implementers). The honest record: implementation was split between the dispatched implementers
  and the PM's parallel inline work on the same plans. `inline` is kept as the declared mode
  because the per-task SDD artifacts (brief/report/diff under {SDD_DIR}) are absent by
  construction — the implementer worktrees carry no `.mstar/` (gitignored) — so the SDD trail
  cannot be reconstructed from disk. The QC tri-review ran as a full N=3 read-only fan-out and is
  unaffected. For this new iteration, dispatch works and the Review chain is dispatched per spec.
status: registered
gate_decision: pass
gate_decision_reason: Prepare satisfied — tail plan; scope is documentation and verification surfaces that only become writable once the four product plans land
gate_decided_at: 2026-09-27
registered_at: 2026-09-27
planned_at_sha: main
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# Ops docs, coverage provenance, and iteration-tail verification

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd` (single-task plan; inline
> allowed with `Execution mode: inline` if PM downgrades). Checkbox syntax.
>
> **This plan is blocked by all four product plans of this iteration** — do not dispatch
> until they are merged to the integration branch.

## Goal (intent gate)

**真实目标**：本迭代交付的能力在文档层面闭环——operator 读 README 就能跑通
"采集 → 队列 → 校对 → 检索" 全链，且 headline 数字全部本机可复现。
**非目标**：知识库大扫除（已显式 defer）、README GPU self-check（defer）。

## Task 1: README three-step chain + new subcommands

- [x] README's operator section rewritten around the post-cutover chain:
  `fetch-meta` → `download-audio` → `asr`, with the manifest bridge named as legacy.
- [x] One paragraph each for `status` (queue view semantics), `proofread` /
  `proofread-merge`, `search` / `search-index`, and the hotword governance ruling
  (keep/drop list, where it is recorded).
- Files: `bilibili-asr-archive/README.md`.

## Task 2: Coverage figure provenance + reproduction

- [ ] The README/roadmap headline coverage figure gains a provenance note: source row  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
  counts + the exact reproduction command, replacing the "150/1730 cited from another
  machine" line.
- [ ] `--strict` section and the two-class exit contract documented, worded per  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
  `.mstar/iterations/iter-2026-09-coverage-truth/specs/exit-code-contract.md` §1–§2 (from
  the evidence-dashboard plan's B-D2, if not already landed there — deduplicate per
  queue-cli-cutover Task 5).
- Files: README + `docs/metadata-storage.md` §Boundary (queue SSOT wording).

## Task 3: Tail verification sweep

- [ ] On the integration branch, run the fresh-root acceptance test written by  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
  20260928-queue-cli-cutover (its `## Verification`: download-audio → asr with store-only
  queue on a fresh archive.db-only root) as the plan's own DoD evidence, and attach the
  output to this plan's `## Verification`.
- [x] Sweep: every new subcommand appears in `bili-asr --help`; every deferred item in
  this iteration's compass has either landed or carries a roadmap row (write the missing
  rows into `.mstar/projects/_default/roadmap.md`).
  **DONE 2026-09-28**: `build_parser()` exposes 24 subcommands and all six new/affected
  ones are present (`proofread`, `proofread-merge`, `search`, `search-index`, `status`,
  `--queue-source` on `download-audio`/`asr`/`pilot`). All four compass deferrals
  (D-3/D-4 tail, B-D2, asr-local storage, hotword A/B) carry roadmap rows under P2.5 —
  nothing had to be added.

### Risk resolution: docs-sweep authority boundary (architect, Phase 1 review 2026-09-28)

The sweep touches four kinds of surface and each has a fixed owner — this plan edits only
what it owns, and verifies (never edits) the rest:

| Surface | Owner | This plan's authority |
|---------|-------|------------------------|
| `bilibili-asr-archive/README.md`, `docs/*.md` (incl. `docs/metadata-storage.md` §Boundary) | **this plan** (Tasks 1–2) | full edit |
| `.mstar/specs/asr-archive-cli.md` provenance addendum | hotword plan `20260928-hotword-injection-governance` (its Task 3) | verify only |
| new `{SPECS_DIR}/proofread.md`, `{SPECS_DIR}/transcript-search.md` | proofread / search plans (their Task 3) | verify only |
| `.mstar/projects/_default/roadmap.md` deferral rows | **this plan** (Task 3 sweep item) — roadmap process files are the closeout seat's job | full edit |
| `.mstar/knowledge/**` | **nobody in this iteration** (compass Non-Goals + chain hard rule: knowledge is off-limits in this chain) | neither edit nor sweep |

"Verify" = the DoD help-output capture and cross-links check; a gap found in a surface
this plan does not own is recorded as an issue (`mstar plan issue-add`) against the
owning plan, not fixed inline. This closes the sweep-authority ambiguity without
re-opening any product decision.

## Global Constraints

- Contract home (architect, 2026-09-28): this plan writes **no spec content** — it
  documents landed behaviour only. The surfaces it must phrase consistently are the
  exit contract (`.mstar/iterations/iter-2026-09-coverage-truth/specs/exit-code-contract.md`
  §1–§2, cited by full path), the queue contract
  (`iter-2026-09-coverage-truth/specs/queue-cutover-contract.md` §5), and the two new
  specs owned by the sibling plans (`{SPECS_DIR}/proofread.md`,
  `{SPECS_DIR}/transcript-search.md`). Edit authority per surface is pinned in Task 3's
  sweep-authority table; `.mstar/knowledge/**` is neither edited nor swept this chain.

## Definition of Done

1. README chain + subcommand docs match landed behaviour (screenshot-free text evidence:
   help output captured in the plan).
2. Coverage figure reproducible with the pinned command on this machine; output recorded.
3. Fresh-root acceptance output attached; no compass deferral without a roadmap row.

## Verification

- Static doc checks (help-output capture, command existence).
- The two recorded command outputs above are the evidence.
