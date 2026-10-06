# Phase 2 readiness — the measured ceremony contract for `iter-2026-10-register-burndown`

> Written during Phase 1 lock (2026-10-05) from measurements on engine v3.11.2 at `c59a1e6`. Purpose: Phase 2
> must not re-derive these. Everything here is either a **measured** fact or a **source-anchored** rule, with
> the anchor named so a later reader can re-check it.

## 1. Two different Assignment contracts (do not mix them up)

The §1.6 Review & Edit chain and the Phase 2 plan ceremony are validated by **two different parsers** with
**different field sets**. Writing one shape where the other is required fails with a field-missing refusal.

| | §1.6 chain dispatch | Phase 2 plan ceremony (`plan prepare`) |
|---|---|---|
| Validator | `mstar-harness dispatch validate <file>` (exit 0/1) | engine `parseAssignmentBytes` (`mstar-harness.js:22253`) |
| `Execute as` | the seat being dispatched (`product-manager` / `architect` / `writing-specialist`) | **`project-manager`** — hard-checked, no other value passes |
| Other required fields | `Execute as`, `Delegation`, `Task category`, one branch form, `Task budget (implement / ops rounds)` | `execution scope` (= `plan`), `execute as`, `delegation` (must start with `allowed`), `control harness root`, `workflow id`, `plan id`, `plan path`, `worktree path`, `working branch`, `sdd dir`, `qa gate`, `findings cleanup`, `prepare gate` |
| Value constraints | free text | `qa gate` ∈ {`mandatory`, `pm-acceptance`}; `findings cleanup` ∈ {`zero-residual`, `allow-residual`}; `prepare gate` = `go`; all four path headers must be **absolute** |
| Header region | everything **before** the first `#` / `---` heading (the dispatch gate slices at the first heading) | the **whole** file, fences skipped |

**Consequence for this iteration**: the three seat Assignments written for §1.6 are the *dispatch* shape on
purpose. The Phase 2 per-plan Assignments (one per plan row) must be authored in the **ceremony** shape by
the PM seat, with `Execute as: project-manager`, `QA gate: mandatory` and `Findings cleanup: allow-residual`
for all three plans (the open linked issues force `mandatory`; see the compass plan table).

## 2. Scope resolution is byte-pinned

`resolvePlanScope` (`:29114`) → `scopeFromAssignment` (`:29490`) checks, in order:

1. `Control harness root` equals the canonical process harness root;
2. `Plan id` / `Workflow id` are safe single path components;
3. the snapshot's `id` equals `Workflow id`;
4. a row exists whose id is `Plan id` (exactly one match);
5. `row.coordination.prepared.assignment_path` — when already prepared, the path must be **byte-equal** to
   the Assignment you are passing;
6. `SDD dir` must equal `canonicalizeNearestExisting(resolveSddDir(harnessRoot, planId))`;
7. `Plan Path`'s dirname must equal the resolved plan dir and its basename must be `<plan-id>.md`.

**So**: the Assignment is a pinned artifact, not a convenience file. Editing a prepared Assignment's path or
moving the file breaks the row permanently (there is no `unprepare`; see §4).

## 3. The legacy (pre-activation) route is the live one here

`execution_meta.authority_state = 'legacy'` in `{HARNESS_DIR}/store.db` (measured), so
`resolveExecutionReadRoute` returns `files` and `assertLegacyRoute` does **not** throw. The file-route verbs
(`plan prepare` / `bind` / `handoff` / `accept` / `complete`, `status workflow-close`) are therefore
available; the active-DB forms would refuse with `execution.consumer-not-ready`. `mstar issue close` needs no
execution authority at all — only a **live** workflow snapshot + an engine-issued session envelope.

## 4. The wedge this iteration must not repeat

Reference: `{SPECS_DIR}/issue-store-close-route.md` § "The lifecycle's own completion ceremony, and where this
repository wedges" (the still-active `20261004-issue-register-audit` lifecycle, captured as `I-000215`).

The failure was **not** the ceremony; it was preparing a plan against the **control root as its plan
worktree**. Because every ceremony step commits a write to `<control root>/.mstar/workflows/<id>/snapshot.json`
— a *tracked* path — `assertFeatureCheckout` then finds the plan worktree dirty, and committing that write
moves `HEAD` past the pinned `source_sha`. The two conditions are mutually unsatisfiable **in one worktree**.

**Rule for this iteration**: every plan row's `Worktree path` must be a **separate feature worktree**
under `.worktrees/`, created from `iteration/iter-2026-10-register-burndown` (which is itself a checkout in
its own integration worktree). The control root stays on `main` and is never a plan worktree.

## 5. Two active lifecycles — always address explicitly

`status.json` currently holds **two** entries: the wedged `20261004-issue-register-audit` and this iteration.
`selectActiveWorkflow` (`dsh/dist/index.js:19522`) returns the single entry when there is exactly one, and
`workflow.selection.unbound-multi-active` when there are several and no lease/cwd match. Practical rule used
throughout this iteration: **every** lifecycle command passes `--workflow <id>` explicitly (or a session
envelope that names it), so the ambiguity never becomes a refusal. This also keeps the wedge untouched, which
is the compass decision D9.

## 6. Register-truth rule for closures

Closure of a target row must go through `mstar issue close` with a **real** engine-issued envelope (see the
close-route spec for the 4 gates) and must name evidence that exists: the commit that fixed it, the test that
witnesses it. `issue_transitions.imported` must read `0` for a live closure. A closure authored with
invented evidence is worse than an open row — the compass D10 states this as a decision, not a preference.
