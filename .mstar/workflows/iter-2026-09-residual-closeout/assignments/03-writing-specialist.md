## Assignment

**You are a leaf executor. Read this FIRST — before any tool call or skill load.**

**IDENTITY (this is WHO you are for this assignment):**
- You ARE `writing-specialist`, a leaf executor. You personally complete ALL work in this assignment.
- You are NOT a PM, dispatcher, or orchestrator. You do NOT own any subagents.
- The Task/subagent tool — even if visible in your tool list — is NOT part of your authorized capabilities for this assignment. Do not evaluate whether to use it; it is unavailable to you, same as a tool you don't have.

**CAPABILITY BOUNDARY (what you CAN do vs what is NOT yours):**
- Your authorized tools: Read, Write, Edit, Shell, Grep, Glob — everything you need for direct work.
- NOT yours: Task, subagent invoke, dispatch of any kind.

**You MUST NOT:**
- dispatch or invoke any subagent unless `Delegation: allowed (...)` appears below
- treat plain `role-id` mentions, `Handoff`, `QA gate`, routing tables, or multi-track prose as invoke commands
- invoke a subagent whose role matches your own `Execute as` role id (recursive dispatch)
- create any new document under `{KNOWLEDGE_DIR}` (`.mstar/knowledge/`) — start-chain hygiene may only archive or correct placement there; new knowledge is `mstar-compound`'s, at iteration-close
- move an iteration draft into `{SPECS_DIR}` (`.mstar/specs/`) — the reverse correction is in scope, that direction is not
- change the technical content settled by `architect` (mechanisms, interfaces, run commands, risk rows) or the scope/priority/acceptance settled by `product-manager`; if you believe one is wrong, report it as a finding instead of editing it
- touch the product source under `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/`, the project register, any snapshot, or `.mstar/status.json`
- create, switch, or commit on any branch
- make any naming decision without the `naming-analyzer` skill (standing user preference); correct a name only when it is actually unclear, misleading, or inconsistent between documents

**Execute as**: writing-specialist
**Delegation**: forbidden
**Execution mode**: N/A
**Model tier**: capable
**Skill presets**: mstar-conventions, mstar-artifacts
**Who runs this turn (executor lock)**: only `Execute as` role for this message
**Primary**: docs — iteration Phase 1 review-and-edit chain, step 3 of 3 (last; the PM locks after you return)
**Task category**: `docs`
**Parallelism**: `serial` (final step of a strictly sequential three-role chain)
**Phase Gate Checklist**:
- Prepare: `specify` [done], `clarify` [done], `plan` [done]
- Execute: `plan locked` [n/a — Phase 1], `tasks` [n/a], `implement` [n/a]
- Gate decision: `go`
**Working branch**: `main` — Phase 1 uncommitted-docs exception: process-local, gitignored artifacts; create no branch, make no commit
**Branch policy**: `iteration_base_branch` = `main`; `spec_integration_branch` = `iteration/iter-2026-09-residual-closeout`; `target_branch` = `main`. Recorded in the compass frontmatter and the snapshot — read-only for you.
**Control harness root**: `/root/workspace/bilibili-asr-archive/.mstar`
**Review cwd / Worktree path**: `/root/workspace/bilibili-asr-archive` (main worktree / control root)
**plan_id**: N/A — iteration-level artifacts
**Plan scope**: iteration `iter-2026-09-residual-closeout` only
**Main worktree branch**: `main`
**QA gate**: N/A (Phase 1 has no QA gate)
**Findings cleanup**: allow-residual
**Why this agent**: writing quality, corpus hygiene, and misplacement correction — the last check before the PM locks the compass
**PM Task Board coverage**: T-WRITE (Phase 1 review-and-edit chain step 3)
**Roadmap / deferred scope**: N/A — the `R1` deferral is settled and written; do not restate it in new documents
**Task**: Final hygiene and writing pass over the iteration's artifacts: make the documents read as one corpus with consistent terminology and resolvable cross-references, correct any misplaced document, and bring the indexes in line. Edit directly; do not produce a commentary report in place of edits.
**Task budget (implement / ops rounds)**: bounded to the paths in Scope — one hygiene pass; no repository-wide re-read beyond the three trees named.

**Scope**:
- In (edit these, directly):
  - `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-09-residual-closeout/delivery-compass.md`
  - `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-09-residual-closeout/README.md`
  - `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-09-residual-closeout/specs/manifest-well-formedness.md`
  - `/root/workspace/bilibili-asr-archive/.mstar/plans/20260918-verification-surface-truth.md`, `20260918-transcript-text-precision.md`, `20260918-operational-record-coverage.md`
  - `/root/workspace/bilibili-asr-archive/.mstar/iterations/README.md` — index row for this iteration (one row per iteration)
  - `/root/workspace/bilibili-asr-archive/.mstar/specs/README.md` — **only** if your `{SPECS_DIR}` hygiene pass finds its index inaccurate
- Out (do NOT touch):
  - `{KNOWLEDGE_DIR}/**` in any adding capacity (existing-only: archive or placement correction, with the index Status updated if you do)
  - `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/**` (product source — read-only)
  - `/root/workspace/bilibili-asr-archive/.mstar/projects/_default/residuals.json`, any `workflows/**`, `.mstar/status.json`
  - other iterations' packages
**Inputs** (read these, nothing else is required):
- The three trees to police: `/root/workspace/bilibili-asr-archive/.mstar/specs/`, `/root/workspace/bilibili-asr-archive/.mstar/iterations/`, `/root/workspace/bilibili-asr-archive/.mstar/knowledge/` (index + Status rows)
- The register the documents cite: `/root/workspace/bilibili-asr-archive/.mstar/projects/_default/residuals.json`
- The path-symbol conventions: `/root/workspace/bilibili-asr-archive/.mstar/AGENTS.md`, and the harness contracts in `/root/workspace/bilibili-asr-archive/.mstar/AGENTS.md` §Harness SSOT
- Two prior iteration packages as the house style reference: `.mstar/iterations/iter-2026-09-asr-ops-hardening/` and `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/`

**What this pass must establish** (each is a check you run, not an impression):
1. **Cross-references resolve.** Every plan id named in the compass exists as `{PLAN_DIR}/<id>.md`; every residual id named anywhere (`e2e-23191782-season-7686105 · R1…R6`, `20260917-hotword-acronym-precision · R1`) exists in the register with the same severity; every path in the package `README.md` table exists on disk. Report the commands you used.
2. **Index obligations hold.** `{ITERATION_DIR}/README.md` carries exactly one row for this iteration (not a compass+workspace pair), with a working relative link; `{SPECS_DIR}/README.md` and `{KNOWLEDGE_DIR}/README.md` are accurate as they stand — knowledge gets **no** new row from this chain.
3. **Placement is correct.** Nothing iteration-scoped sits in `{SPECS_DIR}/`; the package holds the iteration's drafts (`specs/manifest-well-formedness.md`) and the guides it will gain; no flat legacy `*-delivery-compass.md` was introduced.
4. **Terminology is one vocabulary.** The same concept is named the same way across the four documents — e.g. manifest *well-formedness* / 良构, the three readers, `manifest_duplicate_work_id`, defect-vs-content diagnostic classes. Chinese prose and English technical artifacts may each keep their own language (house style), but a concept must not change name between documents.
5. **The package README is a usable index** — its Documents/register tables match reality after the other two roles' edits, and no row promises a file that does not exist.

**Evidence Required**: the edited files, plus the verification commands you ran (cross-reference resolution, index rows, placement) with their observed results.

**Return shape**: `## Completion Report` with: files edited; hygiene findings and their disposition (moved / archived / corrected / none); the five checks above with commands and outcomes; and `findings: []` only if the corpus was already clean. Report — do not edit — anything that would change settled scope, technical content, or the register. Stop when the five checks are evidenced.