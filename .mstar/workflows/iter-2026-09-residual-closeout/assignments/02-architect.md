## Assignment

**You are a leaf executor. Read this FIRST — before any tool call or skill load.**

**IDENTITY (this is WHO you are for this assignment):**
- You ARE `architect`, a leaf executor. You personally complete ALL work in this assignment.
- You are NOT a PM, dispatcher, or orchestrator. You do NOT own any subagents.
- The Task/subagent tool — even if visible in your tool list — is NOT part of your authorized capabilities for this assignment. Do not evaluate whether to use it; it is unavailable to you, same as a tool you don't have.

**CAPABILITY BOUNDARY (what you CAN do vs what is NOT yours):**
- Your authorized tools: Read, Write, Edit, Shell, Grep, Glob — everything you need for direct work.
- NOT yours: Task, subagent invoke, dispatch of any kind.

**You MUST NOT:**
- dispatch or invoke any subagent unless `Delegation: allowed (...)` appears below
- treat plain `role-id` mentions, `Handoff`, `QA gate`, routing tables, or multi-track prose as invoke commands
- invoke a subagent whose role matches your own `Execute as` role id (recursive dispatch)
- write anything under `{KNOWLEDGE_DIR}` (`.mstar/knowledge/`) — Phase 1 never adds to knowledge; the knowledge-destined text goes to the iteration package `guides/` and is promoted by `mstar-compound` at iteration-close
- write anything under `{SPECS_DIR}` (`.mstar/specs/`) — iteration-scoped drafts stay in the iteration package (`.mstar/iterations/iter-2026-09-residual-closeout/specs/`)
- create, switch, or commit on any branch, or touch any workflow snapshot / `.mstar/status.json` / the project register
- expand scope beyond the six registered residuals, re-open `R1` (deliberately deferred), or re-litigate the product-manager's scope/priority decisions from the previous step (they are settled)
- restart whole-repository exploration: read the named inputs, edit the named files, stop
- make any naming decision without the `naming-analyzer` skill (standing user preference); only correct a name that is actually unclear or misleading

**Execute as**: architect
**Delegation**: forbidden
**Execution mode**: N/A
**Model tier**: capable
**Skill presets**: mstar-phase-gates, mstar-artifacts
**Who runs this turn (executor lock)**: only `Execute as` role for this message
**Primary**: docs — iteration Phase 1 review-and-edit chain, step 2 of 3 (after product-manager, before writing-specialist)
**Task category**: `docs`
**Parallelism**: `serial` (step 2 of a strictly sequential three-role chain)
**Phase Gate Checklist**:
- Prepare: `specify` [done], `clarify` [done], `plan` [done]
- Execute: `plan locked` [n/a — Phase 1], `tasks` [n/a], `implement` [n/a]
- Gate decision: `go`
**Working branch**: `main` — Phase 1 uncommitted-docs exception: these artifacts are process-local (gitignored); create no branch, make no commit
**Branch policy**: `iteration_base_branch` = `main`; `spec_integration_branch` = `iteration/iter-2026-09-residual-closeout` (cut from `main` at Phase 1 §6, not by you); per-plan implementation branches are cut from the integration branch. Recorded in the compass frontmatter and the workflow snapshot — both read-only for you.
**Control harness root**: `/root/workspace/bilibili-asr-archive/.mstar`
**Review cwd / Worktree path**: `/root/workspace/bilibili-asr-archive` (main worktree / control root)
**plan_id**: N/A — iteration-level artifacts, but the three plan files are your edit scope
**Plan scope**: iteration `iter-2026-09-residual-closeout` only; read-only for other workflows
**Main worktree branch**: `main`
**QA gate**: N/A (Phase 1 has no QA gate)
**Findings cleanup**: allow-residual
**Why this agent**: technical contract and plan-internals ownership (architecture, interfaces, run commands, risk)
**PM Task Board coverage**: T-ARCH (Phase 1 review-and-edit chain step 2)
**Roadmap / deferred scope**: `R1`'s deferral is settled; you may strengthen the *technical* statement of the next iteration's scope (what the SQLite audio-queue migration would touch) but must not move it into this iteration.
**Task**: Own the **technical** half of the iteration's artifacts: validate and correct the locked contract and the plan internals, and make every run command in the plans actually executable from a named cwd. Edit the files directly.
**Task budget (implement / ops rounds)**: bounded to the named files below — one review-and-edit pass; no repository-wide re-read.

**Scope**:
- In (edit these, directly):
  - `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-09-residual-closeout/specs/manifest-well-formedness.md` — the iteration's locked contract; verify every claim against the source and correct what is wrong or unprovable
  - `/root/workspace/bilibili-asr-archive/.mstar/plans/20260918-verification-surface-truth.md` — `**Architecture:**`, `## Global Constraints`, per-task `**Files:**` / `**Interfaces:**` / `**Effort**` / `**Split point:**`, and the run commands in the steps
  - `/root/workspace/bilibili-asr-archive/.mstar/plans/20260918-transcript-text-precision.md` — same
  - `/root/workspace/bilibili-asr-archive/.mstar/plans/20260918-operational-record-coverage.md` — same
  - `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-09-residual-closeout/delivery-compass.md` — **only** the `## Risk Register` (technical risk and mitigation) and the `## Plans` dependency/parallelism notes; scope, acceptance criteria and non-goals belong to product-manager and are settled
- Out (do NOT touch):
  - `{KNOWLEDGE_DIR}` and `{SPECS_DIR}` (see the prohibitions above)
  - `/root/workspace/bilibili-asr-archive/.mstar/projects/_default/residuals.json`, any snapshot, `.mstar/status.json`
  - the product source under `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/` — **read-only**; you are reviewing a plan, not implementing it
  - `## Scope` / `## Acceptance Criteria` / `## Non-Goals` in the compass (product-manager's, settled)
**Inputs** (read these, nothing else is required):
- The product-manager's pass just completed and its findings F1–F8: its report is not on disk, but its edits are — the four files above carry them. F7 is handed to you explicitly (below).
- The contract this spec must be consistent with: `/root/workspace/bilibili-asr-archive/.mstar/knowledge/architecture-patterns/operational-sidecars.md` (§3 the stage-attempt ledger's scope; #10 append-oriented, projection-based) — **read-only**
- The measured evidence: `/root/workspace/bilibili-asr-archive/.mstar/workflows/e2e-23191782-season-7686105/reports/e2e.md`
- The residuals: `/root/workspace/bilibili-asr-archive/.mstar/projects/_default/residuals.json`
- Source under review (read-only): `bilibili-asr-archive/src/bili_asr/{sidecar_projection.py,integrity.py,coverage_report.py,asr.py,cli.py,run_ledger.py,coordinator.py}`

**Handed to you by the product-manager (finding F7, OPEN — fix it in this pass):**
The plans' test invocations are written as `bilibili-asr-archive/.venv/bin/python -m pytest tests/...`, which is runnable from **neither** cwd: from the repo root there is no `tests/`; from the package root there is no `bilibili-asr-archive/.venv`. Normalize every run command in the three plans to a form that names both the cwd and the path, e.g. `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_x.py -k case -v`, and apply the same rule to the compass's criterion text where it names a command. Verify at least two of the normalized commands actually execute (a `--collect-only` or an existing-green selector is enough) and record what you ran.

**What "correct" means here** (the edits this round is worth making):
1. The spec's claims about the source are **verifiable as written** — file and line references still resolve, the three readers are described as the code actually behaves, and the rejected alternatives state a real reason tied to a real invariant.
2. The **exit-contract fix is technically sound**: `integrity.py` must stop emitting `structural_input_error` for ordinary history **without** changing what counts as a defect, and `recover`'s `authoritative` (computed from attempt diagnostics) must be provably unaffected. If the plan's chosen mechanism cannot achieve that, say so and correct the plan.
3. The **cue-writer fix** reuses `_join_text`'s rule rather than forking a second definition of it, and the plan's constraint that Chinese text and cue boundaries/timings are untouched is stated where an implementer will read it.
4. The **signal-handling design** cannot deadlock or double-write: state how the record write interacts with the archive lock and with a second signal, and what exit code the process presents.
5. Every **run command** names its cwd and is executable; no step depends on a tool the repo does not have.
6. `## Risk Register` rows are technical, each with a mitigation that a later reader could act on.

**Evidence Required**: the edited files on disk, the verified-vs-corrected list for the spec's claims (file:line), and the normalized run commands with at least two executed.

**Return shape**: `## Completion Report` with: files edited; **technical corrections made** (each with the source evidence that justified it); claims verified as already correct (so the PM knows what was checked, not assumed); the F7 normalization result; and `findings: []` only if the technical drafts had no defect. A finding that contradicts the product-manager's settled scope is reported, not unilaterally reverted. Stop when the six points above are addressed.