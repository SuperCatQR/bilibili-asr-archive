# Assignment — Phase 1 Review & Edit (product-manager)

**IDENTITY**

- Execute as: `product-manager`
- Delegation: forbidden (leaf executor; complete this yourself; no subagents)
- Who runs this turn: product-manager

**Scope**

Iteration `iter-2026-08-live-pc-pilot` Phase 1 review chain, seat 1/3 (product).

**Working branch / Branch policy**: control worktree `/root/workspace/bilibili-asr-archive` (docs-only; harness artifacts are gitignored; no business-repo branch).

**Task category**: docs

**Inputs (read-only)**

- `.mstar/iterations/iter-2026-08-live-pc-pilot/delivery-compass.md`
- `.mstar/plans/20260826-audio-reclaim-on-archive.md`
- `.mstar/plans/20260826-bounded-live-pc-pilot.md`
- `bilibili-asr-archive/PLAN.md` (product milestones M0–M4)

**Edit targets (direct file edits, not a report)**

- Compass: scope/acceptance/non-goals clarity; anything product-inconsistent.
- Plans: clarify sections, acceptance wording, user-value framing.
- Optionally `.mstar/iterations/iter-2026-08-live-pc-pilot/specs/` iteration deltas.

**Product questions to resolve (edit in place)**

1. Is skipping livestreams in N=20 acceptable for M2 evidence, or must the plan name the deferred long-live proof explicitly in Roadmap?
2. 45-minute duration threshold — right default?
3. Budget flag default 10 GiB and skip-vs-stop semantics.

**NEVER**

- Do not touch `bilibili-asr-archive/src/**` or tests.
- Do not add anything under `.mstar/knowledge/`.
- Do not run git commands; do not commit.
- Do not dispatch subagents.

**Completion Report**

Reply with: files edited (paths + one-line change summary), open product risks, verdict Approve/Revise for seat 2 (architect).
