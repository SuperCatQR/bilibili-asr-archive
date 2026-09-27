# iter-2026-09-coverage-truth

Iteration package — `delivery-compass.md` + `specs/` (drafts). Not `{KNOWLEDGE_DIR}/`. Worthy content is
**promoted** at iteration-close via `mstar-compound`.

Two locked spec points: `archive.db` becomes the **sole** work queue (retiring the `derive-manifest`
manifest bridge and its legacy bare-`bvid` coverage hole), and the evidence dashboard (status queue view,
verify/coverage exit semantics, reproducible coverage figures). Compass decisions D1–D10; the two plans run
parallel SDD on separate feature worktrees with serial integration merge.

## Documents

| Path | Purpose | Status |
|------|---------|--------|
| [`delivery-compass.md`](delivery-compass.md) | Steering compass — scope, decisions D1–D10, acceptance criteria, non-goals, milestones, branch policy, risk register | active (chain complete; PM lock pending) |
| [`specs/queue-cutover-contract.md`](specs/queue-cutover-contract.md) | Queue cutover contract — archive.db as sole work queue; §4 store read/write API (`MediaQueueRepository`), §5 subtitle outcome mapping (D6), §6 `processing_status` convergence, §7 rollback/compat window, §10 fresh-vs-old DB boundary | draft → reviewed at Phase-1 chain seat 3 |
| [`specs/exit-code-contract.md`](specs/exit-code-contract.md) | verify/coverage exit-code contract — findings graded `defect` vs `backlog`, `--strict` restores exit 1; §3 caller impact; §4 status queue view input; §5 coverage reproducibility | draft → reviewed at Phase-1 chain seat 3 |

## Plans

Registered in `{PLAN_DIR}/` (gitignored, local process):

| plan_id | Title | execution_mode | Status |
|---------|-------|----------------|--------|
| `20260927-archive-db-queue-cutover` | Archive.db 队列 SSOT cutover — 退役 manifest 桥接 | sdd | active (Todo) |
| `20260927-evidence-dashboard` | Evidence dashboard — 队列视图 + exit 语义修复 + 覆盖率本机可复现 | sdd | active (Todo) |

## Boundaries observed while drafting

- `{KNOWLEDGE_DIR}` is not written during start/execute; knowledge-destined text produced by the plans lives
  in their SDD bundles and is promoted by `mstar-compound` at iteration-close.
- Iteration-scoped drafts stay in this package (`specs/`), never in `{SPECS_DIR}/`; `{SPECS_DIR}` holds only
  the frozen `asr-archive-cli.md` and its README.
