# Plan 018 — Decide the parked editorial track: rescue, re-scope, or record the abandon

## Status
- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/08-editorial-track-decision
- **Depends on**: none
- **Category**: direction
- **Evidence**: `HANDOFF.md:187-192` (ref retirement); `bilibili-asr-archive/docs/archive/deletion-records-20260925/README.md` (the tracked second home); the tarball's plan members
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issue**: `I-000178`

## Problem

The `iter-2026-09-transcript-editorial-stages` lifecycle — 校对 (proofread) and 精校 (reading
edition) as verifiable pipeline stages — is **parked with its gates still open**, and the repository
holds no reader-reachable path to it.

Three facts, each verified on this checkout:

1. **The iteration package is off `main`.** `.mstar/iterations/README.md` records the package as
   *deleted 2026-09-25 / refs retired 2026-09-30*, and points a reader at `HANDOFF.md`.
2. **The code is on no `main` commit and no branch.** `HANDOFF.md:187-192` states the six editorial
   source files (~3 400 lines: `services/editorial_alignment.py`, `services/editorial_verify.py`,
   three test modules, `docs/editorial-stages.md`) exist on no `main` commit and are **not** in the
   deletion archive either; `refs/pull/17/head` (`55f846c`) is their only home, recoverable with
   `git fetch origin refs/pull/17/head:refs/heads/<name>`. The retired ref
   `iteration/iter-2026-09-transcript-editorial-stages` (`aa86ea1`) carries no content of its own —
   its tree is byte-identical to `55f846c`.
3. **The two un-started plan files survive only inside a tracked tarball.** Verified by listing:
   `bilibili-asr-archive/docs/archive/deletion-records-20260925/harness-editorial-stages-deleted-20260925.tar.gz`
   holds `.mstar/plans/20260923-reading-edition.md` (27 349 bytes) and
   `.mstar/plans/20260923-editorial-skills.md` (18 074 bytes), alongside the iteration package
   (compass 47 394 bytes, direction-lock, README, `specs/editorial-stage-contract.md`) and the
   workflow snapshot — 24 members, byte-exact, with sha256s recorded in that directory's README and
   in `HANDOFF.md` §9.

So the work is **recoverable but not discoverable**: a fresh agent cannot read the plans, cannot see
the spec, and cannot reach the code without a fetch whose target ref no longer exists locally.

Why this is worth a decision rather than more silence: producing *reading editions* is the product's
evident next value step — the archive already holds transcripts, `proofread`/`proofread-merge`
(merge-v2) shipped as CLI in `iter-2026-09-ops-readiness`, and the editorial stages are the
verifiable-quality layer above them. The track is currently neither resumable by a reader nor
formally abandoned, which is the worst of both.

## Current state (excerpts — verify against live code before acting)

`bilibili-asr-archive/docs/archive/deletion-records-20260925/README.md` (provenance):

```
On **2026-09-25** the operator had the harness records of the parked iteration
`iter-2026-09-transcript-editorial-stages` deleted: 8 roots, 24 files, 433 316 bytes of
`.mstar/**` trees ...
```

`HANDOFF.md` (the ref table):

```
| `feat/20260923-transcript-proofread` (local + `origin`) | `55f846c` — Plan 1's branch, merged via PR #17 | `git fetch origin refs/pull/17/head:refs/heads/<any-name>` → `55f846c` (identical OID) |
```

`HANDOFF.md` (what retirement does not mean):

```
**What the retirement does *not* mean.** The parked iteration is **still parked and its gates are
still open** (§2, §3) — retiring the refs removes a branch name, not the work. ... `refs/pull/17/head`
is now their only home. A resuming agent must fetch that ref **before** reading any of them
```

## Conventions to follow

- This is a **design/spike plan**, not a build plan: its deliverable is a recorded decision plus the
  reader-reachable artifacts that make the decision actionable. Do not re-lift or merge the editorial
  tree as part of this plan.
- The repo's harness rules require a decision record that names its evidence, its bound, and the path
  a future reader takes: `HANDOFF.md` and `{ITERATION_DIR}/README.md` are the operator-facing records
  and are the surfaces to update.
- `{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md` applies to the decision text: say what
  was verified on this checkout and what was not.

## Tasks

### Task 1 — Extract and read the parked record (Effort: XS)

**Files (read-only inputs)**
- `bilibili-asr-archive/docs/archive/deletion-records-20260925/harness-editorial-stages-deleted-20260925.tar.gz`
- `bilibili-asr-archive/docs/archive/deletion-records-20260925/pre-delete-report-20260925-harness-editorial-stages.txt`
- `HANDOFF.md` §1–§4, §9

**Change.** Extract the tarball to a scratch directory (outside the repo) and read the four members
that matter: the iteration package (`delivery-compass.md`, `direction-lock.md`, `README.md`,
`specs/editorial-stage-contract.md`) and the two plans. Record, in the task report: what each plan
proposed, what the compass locked as its acceptance criteria, and which of the §2/§3 open gates are
gating.

**Do not** commit the extracted files in this task.

### Task 2 — Decide (Effort: XS)

Choose and record exactly one:

- **Rescue** — commit the two plan files into `{PLAN_DIR}` (they are the work's own specification) and
  record `refs/pull/17/head` → `55f846c` as a named recovery path in `HANDOFF.md` and the iteration
  index, so a resuming agent has no fetch-and-hope step.
- **Re-scope** — write a smaller successor scope and mark the original plans superseded (state what is
  dropped and why).
- **Abandon** — record the decision with its reasoning and keep the recovery path documented so the
  bytes stay findable.

The decision is the operator's; the plan's job is to make the options concrete (each option's
consequences for the four open gates and for the two plan files) and to land the chosen one.

### Task 3 — Land the decision so a fresh reader can act on it (Effort: XS, same round)

**Files**
- Modify: `HANDOFF.md` (the position table and §1's recovery paragraph)
- Modify: `.mstar/iterations/README.md` (the `iter-2026-09-transcript-editorial-stages` row)
- If the decision is **rescue**: add `{PLAN_DIR}/20260923-reading-edition.md` and
  `{PLAN_DIR}/20260923-editorial-skills.md` from the tarball (commit them — a plan only a tarball
  holds is not a plan in this harness)

**Change.** Whichever option is chosen, the reader path must resolve: the iteration row names the
decision, and `HANDOFF.md` states the code's home (fetchable ref + OID) and the plans' home.

## STOP conditions

- If the current `HANDOFF.md` no longer carries the parked-lifecycle sections (a later iteration
  resumed or deleted them), STOP and report — the decision may already be recorded.
- If `git fetch origin refs/pull/17/head` **fails** (e.g. the remote pruned the ref), STOP immediately
  and report: the ~3 400 lines would then have no reachable copy, which is a materially different
  problem (data loss) from the one this plan addresses.
- If the extraction shows the two plans are not the work's specification but only stubs, STOP and
  re-scope the plan — do not commit stubs as if they specified the track.
- Do not modify the tarball or the pre-delete report: they are the frozen record.

## Drift check

```
git log --oneline -5 -- HANDOFF.md .mstar/iterations/README.md
git ls-tree -r --name-only HEAD bilibili-asr-archive/docs/archive/deletion-records-20260925/
```

If `HANDOFF.md` or the iteration index moved since `1e756df`, re-read the cited sections first.

## Done criteria

- [ ] Each of the three options is written up with its consequence for the four open gates and the
      two plan files
- [ ] Exactly one decision is recorded, attributed to the operator
- [ ] The chosen decision is landed in `HANDOFF.md` and the iteration-index row
- [ ] If rescue: the two plan files are committed in `{PLAN_DIR}` and `git log --oneline -1 -- .mstar/plans/20260923-reading-edition.md` shows the commit
- [ ] Scoped evidence recorded verbatim: `tar -tzf <tarball> | grep plans/` output (both plan members listed) and `git fetch origin refs/pull/17/head:refs/heads/<scratch> && git rev-parse <scratch>` → `55f846c…`
- [ ] Every reader path named in the decision resolves (HANDOFF section, iteration row, plan file if rescue)
- [ ] `git diff --check` exits 0; `git status --short` shows no out-of-scope file

## Verification notes

The fetch is read-only with respect to `main` (it creates a scratch ref). The tarball extraction
happens outside the repository. Nothing in this plan requires the GPU host or the network beyond the
single fetch; if the fetch cannot run in the executing environment, record that as the blocker rather
than asserting the recovery path works.

## Engine lifecycle ownership

This plan produces a decision record and (on rescue) commits two plan files. It does **not** register
a workflow or enter the per-plan state machine by itself: the plans it rescues are candidates the PM
registers when (and if) the operator schedules the track. No delivery tail is promised here.
