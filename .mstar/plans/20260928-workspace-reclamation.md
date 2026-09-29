---
plan_id: 20260928-workspace-reclamation
iteration: iter-2026-09-harness-hygiene
iteration_compass: .mstar/iterations/iter-2026-09-harness-hygiene/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
status: registered
gate_decision: pass
gate_decision_reason: Prepare inherited from the 2026-09-28 reconciliation; compass D1/D2 fix the boundary (Git-only reclamation, explicit exclusions)
gate_decided_at: 2026-09-28
registered_at: 2026-09-28
planned_at_sha: 371693b
agents:
  implementer: ops-engineer
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# Reclaim the workspace finished work is occupying

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Steps use checkbox (`- [ ]`) syntax.
>
> **Scope note.** Git operations and documentation only. No product code, no test changes,
> no harness *document* edits (plan A owns those). Two tracked files outside `.mstar/` are in
> scope for the Git face: `.gitignore` (Task 4) and `HANDOFF.md` (Task 3), plus the new
> `bilibili-asr-archive/docs/archive/deletion-records-20260925/` record files (Task 2).
>
> **Boundary with plan `20260928-harness-state-contract` (compass `## Scope`).** This plan
> owns the **git/workspace** face: worktrees, branches (`local`, `origin`, and the retired
> `pad/*` namespace), `.tmp/` scratch trees, `.gitignore`, and `HANDOFF.md`. It does **not** edit
> `workflows/*/snapshot.json`, `status.json`, or `projects/*/residuals.json` — plan A owns
> those documents and writes the checker that reads them. `HANDOFF.md` is the one file both
> plans reason about and the only one this plan writes; `.gitignore` is the file that makes
> compass D11's published set real rather than prose.

## Current state (evidence — re-read before dispatch)

Measured on 2026-09-28, `main` = `371693b` (== `origin/main`, 0 ahead / 0 behind):

- **11 registered worktrees** (`git worktree list | wc -l`): the control root, **10**
  `.worktrees/` children (7 `feat/*` feature checkouts, 3 iteration-integration checkouts),
  and — counted among those — the parked editorial-stages checkout.
- **11 local branches; 14 remote-tracking refs.** The 14 are `origin/HEAD` →
  `origin/main` plus **10** real `origin/*` branches and **3** `pad/pr-19-*` refs. The
  `pad/*` namespace is **stale and remote-less** (`git remote -v` lists only `origin`; its
  three tips `638fb2d`, `84e9767`, `84e9767` are all ancestors of `main`). It is not a
  remote branch set at all but a leftover ref namespace from the 2026-09-25 structure-tidy,
  whose own recovery note listed 清 `refs/remotes/pad/*` as a收尾 step that never ran. Task 1
  must not treat it as `git push`-addressable.
- Three local branches are ancestors of `main`
  (`feat/20260924-qwen3-asr-transformers`, `feat/20260927-aac-decode-contract`,
  `iteration/iter-2026-09-qwen3-asr-closeout`) — merged, reclaimable by the contract's own
  merge evidence. Several more (`feat/20260928-*`) are **squash-merged**: their content is on
  `main` but their commit objects are not ancestors. `git diff main..<branch>` is **not** a
  merge test for those — it shows a full deletion diff because `main` has moved past them —
  **nor is comparing the branch against `main` file-by-file**: `main` kept evolving after the
  squash, so `feat/20260928-audio-inventory` (vs `main`) differs on `cli.py`, `test_export.py`
  and `test_persistence_scale.py` while (vs its own squash commit `cefed49`) differs on
  **one** file. Compare against the **squash commit**, then read the residue against `main`.
- **`.tmp/` is 126 MB across 192 top-level entries.** The large ones: `batch10` 60 MB,
  `t2-review` 16 MB, **`stage_audio.sh`** 12 MB (11 731 810 B — the file is
  `stage_audio.sh`, not `staging_audio.sh`), `probe` 11 MB, `e2e-quality` 7.4 MB. The rest is
  ~180 one-off probe/download scripts from the WSL/GPU/ROCm exploration weeks. `.tmp/` is
  gitignored, and the entry count — not the byte count — is the real finding: mtime alone
  cannot date these into a lifecycle.
- **`.tmp/deletion-records/` is protected evidence** (compass **D8**): it holds the only
  surviving copies of the 2026-09-25 parked-iteration record deletion archive
  (`harness-editorial-stages-deleted-20260925.tar.gz`, 147 218 B, and
  `pre-delete-report-20260925-harness-editorial-stages.txt`, 71 489 B; both sha256 values match
  `HANDOFF.md` §9's recorded hashes). The 123pan delivery copy §9 names is gone — that mount
  was unmounted on 2026-09-28 and the archive root has since moved to `/srv/bili-asr-archive`.
  Task 2 must exclude this directory **by name**.
- **`.tmp/live-snapshot-backup.json` is an input, not litter** — a pre-correction backup of
  `iter-2026-09-text-and-ledger-precision`. Exclude by name too.
- **`.mstar/sdd/` carries 2 stray top-level files** that are not per-plan directories:
  `iter-2026-09-subtitle-transcript-sqlite-compound-report.md` and
  `qa-acceptance-20260927-three-plans.md`. **The `_reports/` conditional resolves to *no*:**
  no `_reports/` convention exists anywhere under `.mstar/` (the 41 per-plan SDD dirs use
  `review/`, `review2/`, and per-task files), so Task 2 leaves both files in place and records
  the observation. Neither file is referenced by any document except this plan.
- **`HANDOFF.md` (245 lines) is now false at its head**: it opens "Parked 2026-09-24 … Nothing
  in this file is in progress. Read it first when picking the project up", while **four**
  iterations have shipped since the park — `iter-2026-09-qwen3-asr-closeout` (ended
  2026-09-26), `iter-2026-09-coverage-truth` and `iter-2026-09-metadata-audio-layout` (both
  ended 2026-09-27), `iter-2026-09-ops-readiness` (ended 2026-09-28) — and `main` has moved
  **30 commits** since `f326398` through **7 merge PRs** (#18, #20, #21, #23, #24, #25, #26;
  re-derive with `git log --format='%s' f326398..main | grep -oE 'pull request #[0-9]+|#[0-9]+\)'`).
  Its §1 tip table says `main` = `f326398` while the actual tip is `371693b`, and its
  subcommand count ("20 on `main`, 22 at the integration tip") is stale against the repo's own
  later record of 24. Its §2–§3 open gates and §6 residual table describe the parked
  editorial-stages lifecycle, which **is** still parked — that content stays valid, and the
  tracked `.mstar/iterations/README.md:26` row for `iter-2026-09-transcript-editorial-stages`
  points at `HANDOFF.md` §9 for the deleted package's recovery path, so the page must be
  **reframed**, not deleted.
- **The sanctioned planner already exists and mostly refuses.** `mstar worktree cleanup
  --workflow iter-2026-09-harness-hygiene --all-workflows` (dry-run, the safe default) decides,
  over the 11 worktrees: `keep` the main worktree (`cleanup.keep.main-worktree`); **`refuse`**
  all **10** `.worktrees/*` checkouts, split **7** `cleanup.refuse.foreign-worktree` /
  **2** `cleanup.refuse.dirty-worktree`; and `remove` exactly **one** —
  `.worktrees/iter-2026-09-qwen3-asr-closeout-integration` (`cleanup.remove.merged`). On local
  branches: `keep` `main` (`cleanup.keep.protected-ref`), 3 `cleanup.refuse.foreign-branch`, 7
  `cleanup.refuse.checked-out`. It also emits 20 notes, one per iteration:
  `merged-evidence base "<iteration branch>" does not resolve — candidates against it refuse as
  unmerged`, because per-iteration base branches were never pushed. Task 1 must say how it
  relates to this planner (see Global Constraints).
- **Two different "dirty" definitions are in play, and they disagree.** The engine's probe is
  `git status --porcelain --ignored=matching` (`packages/cli/src/index.ts:3222-3256`), which
  counts **ignored** files as dirt. Under it, `iter-2026-09-metadata-audio-layout-integration`
  and `.worktrees/20260926-audio-inventory` are the two `cleanup.refuse.dirty-worktree` cases —
  and every entry in them is an `!!` ignored path (`.pytest_cache/`, `.test-tmp/`,
  `__pycache__/`; 12 entries each), i.e. test by-products, not work. A third checkout,
  `20260927-aac-decode-contract`, reports 6 such entries but the planner refuses it as
  **foreign**, not dirty, because it has no ownership row. Genuinely dirty is only
  `.worktrees/20260923-transcript-proofread` (6 real entries: modified
  `.mstar/iterations/README.md` and `.mstar/status.json`, plus 4 deleted editorial-stages
  files) — and that branch is on the do-not-touch list. The executor must confirm what plain
  `git worktree remove` (no `--force`) accepts on the ignored-only worktrees rather than
  assuming either probe's verdict.

## Goal (intent gate)

**真实目标**：工作区只保留有活的工作；交接页说真话。
**成功判据**：DoD 1–4。**非目标**：删除任何 parked 生命周期（`HANDOFF.md` §9 治理）；
触碰 `.mstar/plans|workflows|projects`（plan A 的面）；改产品代码；删除
`.tmp/deletion-records/` 或 `.tmp/live-snapshot-backup.json`（两者都是**仅存的本地副本**，
D8）；触碰 `/srv/bili-asr-archive`（现役归档根，且经 filebrowser 只读共享 —— `.tmp` 的
清理与它无关，不要把两者混为一谈）。

## Task 1: Reclaim merged worktrees and branches

- [ ] Run the **sanctioned planner first** and record its verdict verbatim:
  `mstar worktree cleanup --workflow iter-2026-09-harness-hygiene --all-workflows`
  (dry-run is the default; do not add a write flag until the verdict table is in the report).
  Treat its per-ref decision as the **engine's own verdict**, and this plan's evidence work as
  **corroboration where an assertion is available** — not as an override to be argued around.
  **Re-verified 2026-09-28: the refusal census is 7 `foreign-worktree` + 2 `dirty-worktree` on
  the 10 `.worktrees/*` checkouts** (plus `keep` on the control root and `remove.merged` on
  `iter-2026-09-qwen3-asr-closeout-integration`). The planner refuses on
  `cleanup.refuse.foreign-worktree` because those snapshot rows record no ownership — a
  **historical metadata gap**, not proof the branch is unowned, but also not a verdict this
  plan may treat as evidence in either direction on its own authority.
- [ ] **Use the engine's assertion path where it exists (compass D10).** `mstar worktree cleanup
  --all-workflows --worktree <abs-path>` asserts ownership for a released-lease checkout when the
  checked-out branch is recorded by exactly one snapshot row, and re-plans it under the same
  guards. **Verified 2026-09-28**: it flips
  `.worktrees/20260928-metadata-r3docs` from `refuse | foreign-worktree` to
  `remove | … | cleanup.remove.merged`. So for every checkout whose branch *is* recorded
  (the `track_branches` set), the reclamation runs through the planner with `--worktree`, and
  the report captures both runs — the bare sweep and the asserted one. Only checkouts the
  assertion cannot reach are reclaimed on hand evidence, and the report says so per ref, naming
  the branch and the reason the assertion did not apply.
- [ ] Determine, **per ref**, whether it is reclaimable, using the contract's evidence and
  not `git diff main..<ref>`:
  - local branch ancestor of `main` → reclaimable;
  - squash-merged branch → reclaimable **only** after confirming its content is present on
    `main` by a per-file comparison against the branch's **squash commit** —
    `git show <squash-commit>:<path>` vs `git show main:<path>` for every file the branch
    touched — recorded in the report, with any residue explicitly attributed to `main`
    evolving after the squash (comparing against `main` alone will mark every squash-merged
    branch as unmerged and refuse it wrongly);
  - branch or worktree owned by a **non-terminal** lifecycle → never reclaim.
- [ ] Reclaim the worktrees first, then the branches (branch deletion fails while a worktree
  has it checked out — order matters; `git worktree remove` then `git branch -d`).
- [ ] **Do not touch**: the control root; `feat/20260923-transcript-proofread` (genuinely
  dirty, and `HANDOFF.md` §2 keeps it as the fix-rider branch),
  `iteration/iter-2026-09-transcript-editorial-stages` and its worktree (parked, operator-owned,
  `HANDOFF.md` §9). For the two iteration-integration checkouts — and only these two — reclaim
  is allowed once their lifecycle is terminal **and** their diffs are confirmed present on
  `main`; both lifecycles *are* terminal (verified: ended 2026-09-26 and 2026-09-27) and the
  planner independently returns `cleanup.remove.merged` for
  `.worktrees/iter-2026-09-qwen3-asr-closeout-integration`, so the outstanding half is the
  per-file diff proof, not the lifecycle. `iter-2026-09-metadata-audio-layout-integration` is
  refused by the planner as `dirty-worktree` on ignored cache only — if the diff proof passes
  and plain `git worktree remove` still refuses, report the refusal rather than escalating.
- [ ] Remote branches: delete only those whose content is provably on `main` and whose
  remote tip is exactly the ref observed at dispatch time
  (`git push --force-with-lease=refs/heads/<b>:<observed-oid> origin :refs/heads/<b>` —
  never a bare delete of a moved ref). The **`pad/pr-19-*` refs are out of that mechanism**:
  they are local remote-tracking refs with no configured remote, so they are removed with
  `git update-ref -d` after the ancestry check, and the action is reported as a ref-namespace
  cleanup rather than a remote deletion. If the executor finds a live reason to keep them,
  keep them and record it — this is the one item here with no functional cost either way.
- Evidenced by a before/after `git worktree list` and `git branch -a` pair in the report,
  plus the per-ref reclaimability table.

## Task 2: Bound the harness scratch trees

- [ ] Report the size breakdown of `.tmp/` and classify each top-level entry: **active**
  (referenced by a live plan/workflow/current iteration), **historical** (an e2e or probe
  from a closed lifecycle), or **unknown**.
- [ ] Delete only the **historical** entries, and only those older than the newest closed
  lifecycle that references them; keep anything a live plan names. **Two exclusions are
  mandatory, not discretionary** (compass D8 and the Current-state evidence):
  `.tmp/deletion-records/` and `.tmp/live-snapshot-backup.json`. Both are excluded by name,
  even if their mtime classes them historical. The first is the only surviving copy of the
  deleted parked records; the second is the input to plan A's snapshot correction. If the
  classifier would delete an excluded path, that is a **bug in the classifier** — fix the
  classifier, do not delete.
- [ ] **Publish the deletion archive into Git (compass D12).** This is the task that makes the
  protection structural, and it changes the exclusion's nature without weakening it. Copy both
  files, byte for byte, into `bilibili-asr-archive/docs/archive/deletion-records-20260925/`,
  with a tracked `README.md` recording: provenance (the 2026-09-25 parked-iteration record
  deletion), both sha256 values, the file inventory, the `HANDOFF.md` §9 anchors, and the note
  that the 123pan delivery side named in §9 is retired. Then commit. **Do not delete or move
  `.tmp/deletion-records/`** — it stays as the working original; after this task it is no longer
  the *only* copy, which is the whole point. Verification is a three-way comparison the report
  carries:
  ```sh
  # 1. published bytes are identical to the working copy
  cmp .tmp/deletion-records/<f> bilibili-asr-archive/docs/archive/deletion-records-20260925/<f>
  # 2. and match HANDOFF.md §9's recorded hashes
  sha256sum bilibili-asr-archive/docs/archive/deletion-records-20260925/*
  # 3. and are actually in the tree, not just on disk
  git ls-files bilibili-asr-archive/docs/archive/deletion-records-20260925/
  ```
  The archive is small (two files, ~213 KB) and `pyproject.toml`'s `packages.find` /
  `package-data` do not ship `docs/`, so this does not change the installed wheel.
- [ ] Report the deletion as a count of top-level entries *and* the byte total, so "126 MB
  reclaimed" cannot be claimed from a total that includes the two protected paths.
- [ ] `.mstar/sdd/` stray files: the conditional resolves to **leave in place**. Verified
  2026-09-28: no `_reports/` convention exists anywhere under `.mstar/`, so no move is
  authorised; record the observation (both file names, their owning lifecycles, and the fact
  that only this plan references them) and do not delete evidence.
- [ ] Record the reclaimed total and the retained set with reasons.

## Task 3: Rewrite `HANDOFF.md` to the truth

- [ ] Reframe the page so its head states the actual position: **four** iterations shipped
  since the park (`iter-2026-09-qwen3-asr-closeout` ended 2026-09-26;
  `iter-2026-09-coverage-truth` and `iter-2026-09-metadata-audio-layout` ended 2026-09-27;
  `iter-2026-09-ops-readiness` ended 2026-09-28), `main` at `371693b` (30 commits and seven
  merge PRs past the parked reading), **and** the parked editorial-stages lifecycle still
  parked with its gates open.
- [ ] Keep §9 (the deletion record) and the recovery instructions **byte-identical** — they
  are the authoritative record for paths that no longer exist. Keep the residual table.
  **Do not "fix" §9's 123pan path**: it is a record of where the archive *was* written, and
  the correct treatment of the retired mount is a dated note elsewhere in the page, not an
  edit to §9. **Add** a dated pointer (outside §9) to the published archive at
  `bilibili-asr-archive/docs/archive/deletion-records-20260925/` (compass D12), stating that
  §9 remains the record of the deletion while the bytes now have a second, tracked home.
- [ ] Add a short "how to resume" section that names the current harness entry points
  (`/iteration-start`, `/iteration-drive`, the harness dir), the two protected `.tmp/` paths
  this plan deliberately kept (so the next reader does not "clean" them), and the one open
  harness observation plan A records.
- [ ] Correct §1's tip table only where it is verifiably wrong, each correction carrying the
  command that establishes it. The three known-wrong entries: `main` (`f326398` → `371693b`),
  the subcommand count, and the "nothing in progress" head.

## Task 4: Make compass D11's published set real in `.gitignore`

- [ ] **This is the mechanical half of compass D11 — without it the amendment exists only in
  prose.** `.gitignore` currently carries three exceptions (`.mstar/AGENTS.md`,
  `{SPECS_DIR}/**`, `{KNOWLEDGE_DIR}/**`); the amendment adds
  `{ITERATION_DIR}/<id>/specs/**`. Append exactly these four lines immediately after the
  existing `!.mstar/specs/**` line, in this order:
  ```gitignore
  !.mstar/iterations/
  !.mstar/iterations/*/
  !.mstar/iterations/*/specs/
  !.mstar/iterations/*/specs/**
  ```
  Order matters: git cannot re-include a path whose parent directory is still excluded, so the
  three parent re-includes must precede the leaf. **Do not add a bare `!.mstar/iterations/**`**
  — that would publish the iteration process face (compass, package README,
  `{ITERATION_DIR}/README.md`), which D11 keeps local.
- [ ] Verify with the two commands that decide the question, and put both in the report:
  ```sh
  # the published set now matches D11 exactly: these 4 exist, everything else under
  # iterations/ is refused
  git add --dry-run .mstar | sed 's/^add //' | sort
  git check-ignore -q --no-index .mstar/iterations/README.md && echo "process face still refused — correct"
  ```
  Expected: the dry-run lists `{HARNESS_DIR}/AGENTS.md`, `{SPECS_DIR}` files,
  `{KNOWLEDGE_DIR}` files, and iteration `specs/*.md` only — **no** `delivery-compass.md`,
  **no** iteration `README.md`, **no** `{PLAN_DIR}` file.
- [ ] **Do not `git rm --cached` anything in this task.** The six debt paths stay tracked and
  stay ignored (compass D11 / **D-5**); this task only changes what *future* `git add` calls
  publish. The distinction is deliberate: the ratchet in plan A tolerates the six, and
  removing them is the operator's call.
- Files: `.gitignore` (tracked; this is the one non-`.mstar` file this plan writes, and it is
  a Git-face file — no product code, no harness *document*).

## Global Constraints

- **Relationship to the sanctioned planner.** `mstar worktree cleanup` is the engine's
  guarded cleanup path and its dry-run is the first evidence this plan produces. This plan
  does **not** reimplement its ladder and does **not** bypass it silently. Where the planner's
  bare sweep refuses on the historical metadata gap, the plan **re-runs it with
  `--worktree <path>`** — the engine's own assertion path (compass D10, verified to flip
  `.worktrees/20260928-metadata-r3docs` to `remove.merged`) — rather than substituting hand
  evidence for an engine verdict. Only where the assertion cannot reach a checkout does the
  plan fall back to recorded evidence, and the report then states, per ref: the refusal code,
  the branch, why the assertion did not apply, and what independent evidence replaces it.
  Where the planner's verdict is stronger than this plan's (it says `remove`), the executor may
  not refuse without a recorded reason.
- Never destroy reflog-only work. Before deleting any branch, confirm the content exists on
  a surviving ref (local or remote); if it does not, **stop and report** instead of deleting.
- `git worktree remove` without `--force` unless the worktree is verifiably clean; a dirty
  worktree is a finding, not an obstacle to bulldoze. **"Clean" means the worktree's own
  tracked state is clean** — the engine's `--ignored=matching` probe counts test by-products
  (`.pytest_cache/`, `.test-tmp/`, `__pycache__/`) as dirt, and this plan does not delete a
  worktree whose only dirt is regenerable build cache; it records the finding and, if
  `git worktree remove` refuses, reports the refusal with the ignored-path list rather than
  escalating to `--force`.
- No `git gc`, no `git prune`, no `git worktree prune` (they can touch foreign registrations
  and other lifecycles' objects).
- **Do not delete, move, or rewrite anything whose only copy is local** (compass D8):
  `.tmp/deletion-records/` and `.tmp/live-snapshot-backup.json` are named exclusions, and the
  rule generalises — when the classifier cannot tell whether a copy survives elsewhere, the
  entry is `unknown` and is kept.
- Report structure: a per-ref table (ref, kind, verdict, evidence, action), not prose.
- New names via `naming-analyzer`.

## Open questions (owned, non-blocking)

| # | Question | Owner |
|---|---|---|
| `~~MQ1~~` | ~~Are the two `iter-2026-09-*-integration` worktrees reclaimable, given their lifecycles are terminal and their content is on `main`?~~ **ANSWERED by product-manager (Phase 1 review 2026-09-28): the lifecycle half is settled, the diff half is Task 1's job.** Both lifecycles are terminal — `iter-2026-09-metadata-audio-layout` ended 2026-09-27 and `iter-2026-09-qwen3-asr-closeout` ended 2026-09-26 — so the "confirmed terminal" condition is met and removes itself as a blocker. The engine's own planner already returns `remove | .../iter-2026-09-qwen3-asr-closeout-integration | cleanup.remove.merged`. What remains is the per-file diff proof against each branch's merge base, which Task 1 performs and records; **no further product ruling is needed**, and a refusal is a Task 1 finding to report, not a question back to the PM. | product-manager (answered) |

## Definition of Done

1. Every reclaimed ref appears with its evidence in the report; every retained ref appears
   with its reason. The report names, per ref, the sanctioned planner's verdict and any
   divergence from it — and for the divergences, the `--worktree` assertion run that supplies
   the engine's own verdict rather than hand evidence (compass D10).
2. No branch was deleted whose content is not provably on a surviving ref.
3. `.tmp/` holds no historical entry; the retained set is enumerated with reasons, and
  **AMENDED 2026-09-29 (QC seat 2, QB2-F1): this clause is met with an authorised exception, not literally.** Task 2 deleted 141 of 192 entries and RETAINED 14 that its own report labels historical (plus 3 it labels active whose only citations are untracked records). The retention is the correct call under this plan's own never-delete-evidence constraint — one of them, `.tmp/sync-2026-09-17/pre-delete-report.txt`, is the **only surviving inventory of 7 deleted roots** — but the DoD line was written as if the sweep would be exhaustive. **Ruling: the 14 are an authorised exception**, enumerated with per-entry reasons in `task-2-report.md` §4.6. The clause is satisfied in the sense that matters (no historical entry was deleted that should have been kept) and NOT satisfied literally (historical entries remain). Do not delete them to make this line true.
   `.tmp/deletion-records/` + `.tmp/live-snapshot-backup.json` are enumerated as
   **deliberately retained** (not merely "still present").
4. `HANDOFF.md`'s head describes the current position (four shipped iterations, seven merge
   PRs, `main` = `371693b`); §9 and the recovery instructions are unchanged byte-for-byte
   (verified by diffing those sections before and after), and the published-archive pointer
   sits outside §9.
5. **The deletion archive has a second, tracked home (compass D12).** Both files exist under
   `bilibili-asr-archive/docs/archive/deletion-records-20260925/`, are tracked by Git
   (`git ls-files` lists them), are byte-identical to the `.tmp/` working originals, and their
   sha256 values match `HANDOFF.md` §9. The archive is no longer the sole copy of anything.
6. **The published set is mechanically real (compass D11, Task 4).** `.gitignore` carries the
   four-line iteration-`specs` re-include; `cd <repo-root> && GIT_INDEX_FILE=$(mktemp -u) git add --dry-run .mstar | wc -l` → 35 (QA-C3: the recipe must run **from the repo root**, because `.mstar` resolves relative to cwd, and `mktemp -u` — a bare `mktemp` creates the file first and git then fails with `index file smaller than expected`; both corrections were measured) lists exactly
   `{HARNESS_DIR}/AGENTS.md`, `{SPECS_DIR}` files, `{KNOWLEDGE_DIR}` files, and iteration
   `specs/*.md`; the iteration process face and `{PLAN_DIR}` remain refused. **No
   `git rm --cached` was run** — the six debt paths stay tracked (D-5).

## Verification

- Before/after `git worktree list` + `git branch -a` + `du -sh .tmp` captured in the report.
- The sanctioned planner's dry-run output, before and after, captured in the report (the
  strongest single check available: the engine re-derives ownership from the snapshot rows,
  so a post-reclamation run that still lists a target ref proves the sweep was incomplete).
  **For every checkout reclaimed on the assertion path, both runs are captured** — the bare
  `--all-workflows` sweep and the `--all-workflows --worktree <path>` run — so the engine's
  verdict is on the record rather than the executor's reasoning about it.
- A `git diff` of `HANDOFF.md` showing only the reframed sections changed and §9 untouched.
- **The deletion archive, three ways** (compass D12): `cmp` against the `.tmp/` working copies,
  `sha256sum` against the §9-recorded hashes
  (`d212a8b712fd25a7b17b9f6710720cec119bf4ed72934812221ec02ba196394e` for the tarball,
  `9d394651b4adb62e3e06648e154093b4de7a8c669007c7f0581f7a3f40dec413` for the report), and
  `git ls-files` proving the published copies are tracked rather than merely present. The
  second half of the original negative control still applies: assert
  `.tmp/deletion-records/harness-editorial-stages-deleted-20260925.tar.gz` **still exists** and
  still hashes to its recorded value, because the failure mode this plan guards against (a
  classifier deleting it) is silent and unrecoverable. An absence-or-presence assertion is
  evidence only if the check can reach the falsifier
  (`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md`); for the protected
  paths the falsifier is "hash changed or file missing". **After D12 lands, the same falsifier
  applies to the published copies**, which is what makes the protection survive this plan.
- Negative control: `git log --oneline <any deleted branch>` must fail afterwards while
  `git cat-file -e <its tip>` still succeeds (the object survives until gc), proving the
  reclaim removed a ref and not history.
- **The `.gitignore` amendment, both directions** (Task 4): `GIT_INDEX_FILE=$(mktemp) git add --dry-run .mstar` (the bare form is index-masked and prints nothing where this plan says to run it — QC2-F6) lists the
  four published groups and nothing else, **and** `git check-ignore -q --no-index` still refuses
  the iteration process face and `{PLAN_DIR}`. A one-sided check would pass just as happily if
  the amendment had published everything.

## Deferred

| # | Deferred | Why | Trigger / owner |
|---|----------|-----|-----------------|
| D-1 | Any parked-lifecycle cleanup (editorial-stages refs, its archive) | Operator-owned by `HANDOFF.md` §9 | Operator decision; owner operator |
| D-2 | The worktrees the engine refuses as `cleanup.refuse.foreign-worktree` and the assertion cannot reach | **Ruled by architect (compass D10): the metadata gap is historical, not contractual** — the engine already writes `metadata.working_branch` at handoff (`coordination.ts:4775`) and refuses a plan whose markdown declares no `Working branch` header at `prepare` (`coordination.ts:6053`). The refused rows predate or bypass that writer. Reclaiming those on hand evidence alone would make this plan the owner of rows it does not write; the ones the `--worktree` assertion *can* reach are handled in Task 1 under the engine's own verdict. So this row now covers only the residue the assertion cannot reach | Next harness-maintenance round, for any ref still refused after Task 1's assertion pass; owner PM |
| D-3 | The 47 register entries with no `lifecycle` key (the repo's ceiling for `total_open: 90`) | Repo consistency, not an engine violation — the contract treats the key as optional, so writing values would be a data decision about what is open, and that belongs with the register's owner | With the register work in the next product-facing iteration; owner PM |
| D-4 | An automated gate asserting the published deletion-archive bytes | Plan B is Git-and-documentation-only (`no product code, no test changes`), and plan A's checker is scoped by its own Goal to the documents the engine reads, so neither plan can host the test without breaking its own boundary. Tracking the archive (Task 2) removes the *sole-copy* risk this plan exists to close; what remains is a regression risk against silent corruption, which is a smaller and non-urgent exposure | When a future plan legitimately owns the package test suite or a harness-file checker; owner PM |
| D-5 | Removing the **six** frozen debt paths from the index (4 iteration process files + 2 plans) so `.gitignore`'s published set and `git ls-files .mstar` agree absolutely | The five *iteration `specs/`* paths in the 11-file non-conforming set are already rule-consistent under compass **D11**'s amendment; only these six are debt. `git rm --cached` on them deletes the delivery record of two **closed** iterations (including both `delivery-compass.md` files and the two `{PLAN_DIR}` plans) from every future clone, and the operator has not been asked. Plan A's checker therefore asserts a **ratchet** — new out-of-set paths fail, the six are tolerated and may only shrink — rather than an absolute that would be red on arrival and ignored. This is a boundary change, so it needs an explicit human decision, not a hygiene side effect | Operator sign-off, before the next clone is cut; owner operator |

### Architect ruling (Phase 1 review 2026-09-28) — worktree ownership metadata

**Ruled: ownership metadata is not made mandatory, and hand evidence is the sanctioned
reclamation path — but only for the refs the engine's own assertion cannot reach.** Recorded as
compass **D10** and Q3. Two premises in the gap text above were wrong and are corrected here;
the ruling is narrower than the gap text implied, and the narrowing is what makes it safe.

**Correction 1 — the contract is not missing the writer; it already has one.**

- `packages/engine/src/coordination.ts:4775` — `completeStandaloneRow` sets
  `metadata.working_branch = handoff.source_branch` and `metadata.worktree_path =
  handoff.worktree_path` on the terminal transition, so **a row that goes through reconcile
  gets correct ownership metadata from the engine**.
- `metadata.working_branch` refusal text at `prepare` (`coordination.ts:6053`, "declares no
  Working branch header") shows the writer is enforced on the way in, not just on the way out.
- The rows that lack it were written by lifecycles that predate or bypass that writer — the
  `feat/20260928-*` set and the closeout/older rows. **So this is a historical metadata debt,
  not a contract the engine fails to satisfy.** Writing the missing values by hand in this
  plan would manufacture ownership the engine never confirmed, which is exactly why the
  ruling below does not ask for it.

**Correction 2 — the planner's refusals, counted correctly, split by cause.** Verified
2026-09-28 over the 10 `.worktrees/*` checkouts:

| Refusal | Count | Cause | This plan's handling |
|---------|-------|-------|----------------------|
| `cleanup.refuse.foreign-worktree` | **7** | ownership not recorded on the row for that branch | engine `--worktree <path>` assertion where the branch is recorded; hand evidence otherwise |
| `cleanup.refuse.dirty-worktree` | **2** | ignored build cache in the working tree | Task 1 handles directly (clean the ignored cache) |
| `cleanup.remove.merged` | 1 | `.worktrees/iter-2026-09-qwen3-asr-closeout-integration` | reclaimed |
| `cleanup.keep.main-worktree` | 1 | the control root | kept |

The gap text's "**7** refusals … (the 2 `dirty-worktree` refusals are a different cause)" was
right about the cause split and undercounted the total: **9 refusals, 7 foreign + 2 dirty.**

**Correction 3 — the engine has a supported assertion path, and it works.** `mstar worktree
cleanup --all-workflows --worktree <abs-path>` attributes ownership for a released-lease
checkout whose checked-out branch is recorded by exactly one snapshot row, and re-plans it under
the same guards. **Reproduced:** `--worktree …/20260928-metadata-r3docs` flips that target from
`refuse | foreign-worktree` to `remove | … | cleanup.remove.merged`. With that path available,
the gap text's framing ("this plan has to argue around its verdict instead of using it") is
wrong for every checkout whose branch is recorded: **the plan uses the engine's verdict there.**

**The ruling, precisely.**

1. **No new mandatory field, and no retro-fit in this plan.** The engine writes ownership
   metadata on the paths that matter; the deficit is historical. Requiring the 7 rows to be
   hand-populated would put unverified ownership claims into the same documents this iteration
   is cleaning up — the opposite of the goal.
2. **Hand evidence is the sanctioned path only where the engine cannot reach the ref** — i.e.
   checkouts whose branch no snapshot row records, and branches reached outside the planner's
   scope. There the report carries the evidence per ref (ancestry or squash-commit comparison)
   and names the refusal code it diverges from. It is **corroboration subject to a guard**,
   never a claim that the engine was wrong — this plan does not get to overturn
   `cleanup.refuse.*`.
3. **The guard is absolute.** No hand evidence may reclaim a checkout the planner refuses as
   `cleanup.refuse.dirty-worktree` or `cleanup.refuse.checked-out`. Those are live-state
   verdicts, not ownership verdicts: a dirty tree means uncommitted work may exist, and
   `checked-out` means a worktree still holds the ref. Hand evidence speaks to *ownership*
   only, and ownership was never the reason those two refuse.
4. **Forward contract.** Any future plan row that gets a feature worktree takes its ownership
   metadata from the engine's own writer on the terminal transition — no PM hand-writing of
   `metadata.working_branch`, and no second source of truth added beside it.

**Consequence for this plan's Task 1.** The assertion pass is **not optional**: it is how the
majority of the 7 are reclaimed, and it is the reason the "argue around the verdict" framing is
gone. Task 1 runs the bare sweep, then the asserted per-path runs, and only the residue is
hand-evidenced. Deferred row **D-2** is re-scoped accordingly: it now covers only the residue
the assertion could not reach, rather than all 7.
