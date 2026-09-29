---
iteration_id: iter-2026-09-harness-hygiene
start_date: 2026-09-28
end_date: 2026-09-29
status: completed
iteration_base_branch: main
target_branch: main
spec_integration_branch: iteration/iter-2026-09-harness-hygiene
enforcement: soft
plans:
  - 20260928-harness-state-contract
  - 20260928-workspace-reclamation
---

# iter-2026-09-harness-hygiene Delivery Compass

## Scope

Make the harness's own recorded state honest and machine-readable, and reclaim the
workspace litter the September iterations left behind. Two locked outcomes:

1. **Every lifecycle document the engine reads passes the engine's own validators** — the
   27 workflow snapshots (26 terminal plus this iteration's own running snapshot), the
   **root register** (`.mstar/status.json`, the engine's v2 workflow-level record), and the
   **project residual register** (`.mstar/projects/_default/residuals.json`, the SSOT for open
   residual findings). A reusable **checker** in the repo
   (`bilibili-asr-archive/scripts/validate_harness_state.py`) keeps that compliance from
   silently regressing.
2. **The workspace stops carrying finished work**: merged worktrees and branches are
   reclaimed, the stale handoff page is rewritten to the truth, and the harness's
   own scratch trees are bounded.

This iteration is *harness* work, not product work. It exists because a main-based
reconciliation on 2026-09-28 found the recorded state disagreeing with the
repository in ways that made the engine report errors at session start and made
several claims in the docs false.

**Boundary between the two plans (a reader can tell from this line alone).**
Plan A (`20260928-harness-state-contract`) owns harness **documents** — the files the
engine reads (`workflows/*/snapshot.json`, `status.json`, `projects/*/residuals.json`)
and the checker that keeps them honest. Plan B (`20260928-workspace-reclamation`) owns
**git and workspace** — worktrees, branches, `.tmp/` scratch trees, and the
`HANDOFF.md` page. "Plan A" and "plan B" are the only shorthand used for these two, in this
compass and in both plans; no "plan 1" / "plan 2" form appears. Neither plan edits the other's
surface; the one shared target is `HANDOFF.md`, which only plan B writes. "Hygiene" here
therefore means *recorded state and physical worktree*, and explicitly **not**
product-code hygiene or knowledge-base re-indexing (see `## Non-Goals` and D2/D3).

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Direction locked to harness/workspace hygiene (candidates 1+3 of the explored set) | The evidence is machine-checkable and the damage is live: the engine emitted `workflow.selection.snapshot-unreadable` at session start, and `HANDOFF.md` asserts no plan is in progress while **four** iterations had since reached terminal status (`iter-2026-09-qwen3-asr-closeout` 2026-09-26, `iter-2026-09-coverage-truth` and `iter-2026-09-metadata-audio-layout` 2026-09-27, `iter-2026-09-ops-readiness` 2026-09-28) | user instruction（"重新校准，给仓库进行卫生清洁"）+ measured evidence |
| D2 | Product-code hygiene (candidate 2: `cli.py` size, `derive-manifest` retirement) is **out of scope** | It touches `cli.py`, which a concurrent session was editing; and D-3/D-4 already have durable roadmap rows — no need to duplicate the tracking | explored-set scoping; avoids cross-session write collision |
| D3 | Knowledge-base re-index (candidate 4) is **out of scope** | Its scope depends on which iteration owns each residual, which is a product-ownership question, not hygiene | explored-set scoping |
| D4 | Branch policy: base `main`, integration `iteration/iter-2026-09-harness-hygiene`, target `main` | Same triple as every prior iteration in this repo (snapshot `branch` anchors + compass frontmatter agree) | prior iteration compasses |
| D5 | The contract checker ships **in the product package's `scripts/`** with a test in the package suite | The repo's established home for operator tools is `bilibili-asr-archive/scripts/` (`check_asr_env.py`, `measure_hotwords.py`); a gitignored harness-local script would not travel with a clone, which is exactly how this drift accumulated | repo convention; `mstar-conventions` tracked-vs-process rule |
| D6 | Historical snapshots are corrected **in place, in the contract's own vocabulary**, with no status/date/outcome invented | The validator rejects shapes, not history. Where a value was genuinely unknown (e.g. a legacy plan row's `file` pointer whose `.md` never existed), the record states that fact rather than a fabricated path | `mstar-artifacts` fail-loud handoff; the 2026-09-28 reconciliation's own discipline |
| D7 | **Q1 ruled: field-complete the pre-contract residual entries from their own recorded text; do not create a standing legacy class** | Verified 2026-09-28: the field-completion set is **23** entries (missing `title`/`source`/`scope`/`tracking`), and **all 23 carry `what` prose** — so the substance is recorded and only the contract fields are absent. Plan A's legacy bucket is therefore **empty today**, and the DoD's zero-violation target is attainable without a permanent exemption. Where the entry's own text supports no value, the field carries the explicit not-recorded literal — never a plausible guess (D6). **Scope note the checker depends on:** `what` is *not* a required field and 98 of the 122 entries omit it legitimately, so the legacy bucket is scoped to the 23-entry completion set — an unscoped "no `what`" rule would fire on 98 valid entries | product-manager Phase 1 review, 2026-09-28; verified against `.mstar/projects/_default/residuals.json` via `mstar persist get --validate residuals --key _default` |
| D8 | The `HANDOFF.md` deletion archive under `.tmp/deletion-records/` is **protected evidence**, never a reclamation candidate | It is the only surviving copy of the parked iteration's harness records. `HANDOFF.md` §9 introduces it as "**Archive — the only complete copy.** Written to the 123pan delivery side", and states that the on-disk `delivery-compass.md` carried a 55 232-byte delta "that was never committed, and that delta exists **only** in the archive above"; §9 also records that `20260923-reading-edition.md` / `20260923-editorial-skills.md` were "**not** in git at all". The delivery side §9 names is **unreachable**: `/mnt/123pan` is not a mountpoint and is empty, its `rclone-123pan.service` is retired, and no `bili-asr-e2e` tree exists anywhere under `/srv`. Reclaiming this as "historical `.tmp/` litter" would destroy the last copy of files this repository's own recovery instructions point at. **Note on `/srv`:** the archive root that moved there is the *product* archive (`/srv/bili-asr-archive/{archive.db,manifest,transcripts}`) — it is not the deletion archive and holds no copy of it | verified 2026-09-28: `sha256sum` of both files matches §9's recorded hashes verbatim; `find / -path /proc -prune -o -name 'harness-editorial-stages-deleted-*' -print` and the same for `pre-delete-report-20260925*` return **exactly two paths, both under `.tmp/deletion-records/`**; `mountpoint /mnt/123pan` → "is not a mountpoint" (0 entries); `ls /mnt/123pan/bili-asr-e2e` → No such file or directory |
| D9 | **Q2 ruled: the project residual register is hand-maintainable, and the hand-edit is a sanctioned write path when it goes through the CAS-guarded store put.** The accepted acceptance test is `mstar persist residuals --key <project> --expect-version <sha256>`, and the corrected document must read back clean under `mstar persist get --validate residuals --key <project>`. If that put is ever unavailable, a direct byte edit plus the same validating read-back is the fallback — a documented procedure, not an unrecorded hand-edit | **The PM's premise was wrong and the correction is load-bearing.** The installed CLI (`/usr/local/bin/mstar` → `@mstar-harness/cli` 3.11.2) **does** ship `persist residuals` as a writable kind: `PERSIST_KINDS = ["status","snapshot","residuals","review","json"]` and `COORDINATED_PERSIST_KINDS = ["status","snapshot","residuals"]`, validated by `validateProjectRegister`, with a working CAS token. It is **not** retired on this build — `grep -c "is the only findings authority"` over `dist/mstar-harness.js` returns **0**, and no `coordination.store` text is emitted by `persist`. Reproduced end-to-end on a scratch harness: a valid register at `sha256:5528c08d…` was replaced with `persist residuals --expect-version sha256:5528c08d…` → `persist residuals/_default: OK`, and a payload written with a plain `sha256sum` token was likewise accepted and landed. The refusal the PM saw is **the validator**, not a retirement: the current register fails `validateProjectRegister` with 144 violations, and `persist` runs the kind's validator before put, so it refuses the document it is asked to write. That is a **chicken-and-egg**, and the resolution is the ruling below. `store`/`issue`/`catalog` genuinely are absent from this build (exit 1, `error: unknown command`) — the engine source at `packages/cli/src/index.ts:6403-6410` registers all three, so they are a **newer source than the published build**; conclusion (b) is therefore not available on this installation | architect Phase 1 review, 2026-09-28; established by `mstar --help`, `mstar persist --help`, `mstar store init` / `mstar issue add` (both exit 1 `unknown command`), `mstar persist residuals --expect-version sha256:<hash>` on `/tmp/castest` (rc 0, bytes landed), and `MSTAR_HARNESS_DIR=.mstar mstar persist get --validate residuals --key _default` (144 violations, rc 1) |
| D10 | **Q3 ruled: ownership metadata is not made mandatory, and hand evidence is the sanctioned path for read-only reclamation.** `mstar worktree cleanup` keeps refusing a checkout whose ownership the snapshot rows do not record; plan B reclaims by evidence and records the planner's per-ref verdict as **corroboration**, never as an authorization it must argue around | Two premises in the gap text are wrong and were corrected on disk. (i) The engine **already writes** `metadata.working_branch` at handoff (`packages/engine/src/coordination.ts:4775`, `metadata.working_branch = handoff.source_branch`) and at `prepare` (`coordination.ts:6053`, which refuses a plan whose markdown declares no `Working branch` header). The rows that lack it — the whole `feat/20260928-*` set **and** the closeout/older rows — were written by lifecycles that predate or bypass that writer, so the gap is **historical, not a missing contract**. (ii) The planner's refusal count is **7 `foreign-worktree` plus 2 `dirty-worktree`** on the 10 `.worktrees/*` checkouts (11 worktrees total, one `keep main-worktree`, one `remove.merged`); the PM's "7 refuses, 2 dirty handled separately" understates it and plan B's D-2 already carries the 7 correctly. `--worktree <path>` **does** assert ownership for a released lease — verified: `--all-workflows --worktree …/20260928-metadata-r3docs` flips that target from `foreign-worktree` to `remove | … | cleanup.remove.merged` — so the engine has a supported reclamation path for exactly the evidence cases plan B faces, and the plan should use it rather than hand-arguing | architect Phase 1 review, 2026-09-28; established by `mstar worktree cleanup --workflow iter-2026-09-harness-hygiene --all-workflows` (7 foreign / 2 dirty / 1 remove / 1 keep-worktree) and the same command with `--worktree …/20260928-metadata-r3docs` (verdict flips to `remove.merged`) |
| D11 | **The published-vs-local boundary is fixed, not widened, and is enforced in two halves.** The published set gains exactly one new member — `{ITERATION_DIR}/<id>/specs/**` — because the published set cites those drafts by exact path; the iteration process face (compass, package README, `{ITERATION_DIR}/README.md`, `guides/`) and all of `{PLAN_DIR}` stay local. **Plan B Task 4** writes the four-line re-include into `.gitignore` (which never carried the amendment — the rule was prose only), and **plan A**'s `validate_harness_state.py` asserts the result as a ratchet: new out-of-set paths fail, the six frozen debt paths are tolerated and may only shrink. `.mstar/AGENTS.md` states the amended set, its amendment note, and the per-path verdict table (5 published, 6 debt) | Verified count and attribution, which correct the gap text in two places: `git ls-files .mstar` returns **41** files, and of the **11** paths that violate the *pre-amendment* three-exception rule, **5 are rule-consistent under the Amendment** (they are iteration `specs/` drafts) and **6 are frozen debt** — so the debt figure is 6, not 11 or 9. Re-attributed by re-add commit the split is **7 by `2696711` (2026-09-27), 2 by `d1c9600`, 2 by `cefed49` (2026-09-28)** — so the PM's "`2696711`, `d1c9600`, `cefed49` added the 11" is right in aggregate and the "one day after the cleanup" framing is wrong for `d1c9600`/`cefed49` (both 2026-09-28, three days after `18e8119` on 2026-09-25). `18e8119` really did drop 527 (`git show --name-status 18e8119 \| grep -c '^D'` → 527). Also corrected: `.mstar/AGENTS.md`'s own "Five kept files … 166 such references" is **not reproducible** — the same command returns **5 files / 6 references** at `371693b`, 3/4 at `18e8119`, 4/5 at `2696711`; the page now carries the reproducible pair. **The amendment is justified by *kind*, not by citation count** — the process face *is* cited by two tracked knowledge notes (`completion-claims-need-live-evidence.md:137`, `premise-freshness-before-lock.md:98`), and those citations are deliberately left resolving locally, because `mstar-compound` promotes the process face into `{KNOWLEDGE_DIR}` at close and publishing it would compete with its own successor. Enforcement is a checker assertion rather than a hook because the repo has **no CI** (`.github/` absent) and **no hook infrastructure** (`core.hooksPath` unset, only `*.sample` under `.git/hooks/`), so a hook would be machine-local. The six are left tracked deliberately: removing them is a `git rm --cached` deletion of two closed iterations' delivery record from every future clone, which is the operator's call (plan B **D-5**), and a red-on-arrival assertion would only train readers to ignore it | architect Phase 1 review, 2026-09-28; established by `git ls-files .mstar` (41), the classifier loop over those 41 (`35 published / 6 debt` under the amended set), `git check-ignore --no-index` over each (11 ignored, 30 clean), the re-include verified in a scratch repo (`/tmp/igv3`: iteration `specs/*.md` publishable, process face and `{PLAN_DIR}` still refused, requires the parent dirs to exist), `git log --diff-filter=A` per path (7/2/2 by the three commits), `git show --name-status --format='' 18e8119 \| grep -c '^D'` (527), `git grep -lE '\.mstar/(plans\|sdd)/' <commit> -- .mstar/specs .mstar/knowledge` (**5 files / 6 refs** at `371693b`; 3/4 at `18e8119`, 4/5 at `2696711`), `ls .github` (absent), `git config --get core.hooksPath` (unset) |
| D12 | **The deletion archive is published into Git, and that is what makes plan B's protection structural.** The two files are committed to `bilibili-asr-archive/docs/archive/deletion-records-20260925/` together with a tracked `README.md` recording their provenance, both sha256 values, the file inventory, and the `HANDOFF.md` §9 anchors. `.tmp/deletion-records/` is **retained as the working original** and stops being the sole copy. `HANDOFF.md` §9 keeps its text byte-identical and gains a dated pointer to the published home | **Structurality is achieved by tracking, not by a test — and this is deliberate.** A byte-asserting pytest was considered and rejected on contract grounds: plan B is explicitly Git-and-documentation-only (`no product code, no test changes`), and the assertion cannot move to plan A either, because plan A's checker is scoped by its own Goal to *the documents the engine reads* (`workflows/*/snapshot.json`, `status.json`, `projects/*/residuals.json`) — a deletion archive is not one of those, so adding it there would break that plan's coherence to gain nothing. What tracking actually buys: the bytes survive any `.tmp/` sweep by construction (they are in the object store), any clone can re-verify them without the operator's machine, and loss becomes a `git status` fact rather than a silent deletion. Verification is a re-runnable command recorded in plan B's `## Verification`, and the residual risk (no automated gate) is carried as plan B **D-4** with an owner and trigger. **Why not the alternatives.** (a) *Leave it in `.tmp/` on prose exclusion*: rejected — `.tmp/` is gitignored and swept by design, and the exclusion would live only in a plan file the next operator may never read, with a silent, unrecoverable failure mode. (b) *`.mstar/archived/`*: that is the engine's own convention (`packages/engine/src/status.ts:25` recommends `archived/residuals/`; `execution-recovery.ts:1574` writes `archived/store-migration/recovery/`), but it sits under `.mstar/**` and is therefore **still gitignored** — it fixes nothing about "sole surviving copy". (c) *`.mstar/specs/`*: wrong kind — that is the frozen-spec home, and `mstar compound validate` / `mstar lint` treat it as such. The product `docs/` tree is the right home: tracked (26 files today), outside `{HARNESS_DIR}` so no harness ignore rule can reach it, `bilibili-asr-archive/docs/archive/` is already the established precedent for archived records, and `pyproject.toml`'s `packages.find` / `package-data` do not ship `docs/`, so publishing does not change the installed wheel | architect Phase 1 review, 2026-09-28; established by `sha256sum .tmp/deletion-records/*` (both hashes match `HANDOFF.md` §9 verbatim: `d212a8b7…`, `9d394651…`), `tar tzvf` (24 members; the 55 232-byte `delivery-compass.md` §9 calls out is present and is **not** any committed revision's 47 394), `find / -name '*editorial-stages*'` (no second copy outside `.tmp/`), `git check-ignore --no-index` on `.mstar/archived/**` (ignored), `git ls-files bilibili-asr-archive/docs` (26 tracked), `grep -n 'packages.find\|package-data' bilibili-asr-archive/pyproject.toml` (no `docs/`) |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| ~~Q1~~ | ~~Do the 22 legacy residual entries that predate the current residual contract get field-completed (source/scope/owner/title/tracking), or formally migrated as legacy?~~ **RULED by product-manager (Phase 1 review 2026-09-28): field-complete them — no standing legacy class.** The set is **23** entries (those missing at least one of `title`/`source`/`scope`/`tracking`: `iter-2026-09-ops-readiness` `O-R1`…`O-R7`, `20260926-audio-inventory` `A-R1`…`A-R9`, `20260928-layout-shape-a` `L-R1`…`L-R4`, `20260926-video-metadata-enrichment` `R5`/`R6`/`R7`), and all 23 carry their own `what` prose, so every required field is derivable from the entry's own recorded text; where a field's value is genuinely not recorded anywhere, the literal `"unknown — not recorded at registration (pre-contract entry)"` is written rather than a plausible guess (D6/D7). 11 of the 23 are fully pre-contract (also missing `decision`/`owner`/`target`); the other 12 already carry those and must keep them unchanged. The plan's legacy bucket is retained as a **residual, expected-empty** branch scoped to this set — a reporting device for an entry with no recorded substance, not an exemption this iteration may claim. Plan A's MQ1 records the same ruling; not re-openable without a new product decision. | product-manager (ruled) | No |
| Q2 | ~~Which durable answer does the project residual register's **write path** take — freeze it as history (a), migrate to `store.db` (b), or formally sanction hand-maintenance (c)?~~ **RULED by architect (Phase 1 review 2026-09-28): (c), refined — hand-maintenance through the CAS-guarded `persist` put, with the validating read-back as the acceptance test. `store.db` is not an option on this installation.** (b) is unavailable: `mstar store` and `mstar issue` are `unknown command` on the installed 3.11.2 build (the engine source registers them at `packages/cli/src/index.ts:6403-6410`, so the source is newer than the published build). (a) is rejected because DoD 3 would stop claiming a live register in a document the engine still reads. The PM's premise that `persist residuals` is retired **is wrong on this build** — see **D9** for the reproduction; the refusal it observed is the register's own 144 violations, not a retirement. Plan A Task 2 is amended to use the engine put, not a bare hand-edit | architect (ruled) | No — ruled |
| Q3 | ~~Must every plan row that has a feature worktree carry ownership metadata (`metadata.working_branch` / `worktree_path`), or is `mstar worktree cleanup`'s `cleanup.refuse.foreign-worktree` on the 7 `.worktrees/*` checkouts it cannot verify the expected outcome?~~ **RULED by architect (Phase 1 review 2026-09-28): not mandatory; hand evidence is the sanctioned path, and `--worktree <path>` is the engine's own assertion mechanism for the cases where the branch is recorded.** The metadata gap is **historical, not contractual** — the engine already writes `metadata.working_branch` at handoff (`coordination.ts:4775`) and at `prepare` (`coordination.ts:6053`), and refuses a plan whose markdown declares no `Working branch` header. The refused rows are the ones written before or around that writer existed. Plan B reclaims by evidence, records the planner's verdict per ref as corroboration, and drops the "override" framing. See **D10** | architect (ruled) | No — ruled |
| Q4 | ~~Where does the sole surviving copy of the 2026-09-25 deletion archive durably live, and is plan B's protection structural rather than prose?~~ **RULED by architect (Phase 1 review 2026-09-28): publish it into Git under `bilibili-asr-archive/docs/archive/deletion-records-20260925/`, and keep `.tmp/deletion-records/` as the working original.** The protection becomes structural through **tracking** — the bytes survive any `.tmp/` sweep by construction. A byte-asserting test was considered and rejected on contract grounds (plan B is Git-only; plan A's checker is scoped to documents the engine reads); that residual risk is carried as plan B **D-4**, not papered over. `.mstar/archived/` is not a fix (it is gitignored). See **D12** | architect (ruled) | No — ruled |

**Phase 1 review record.** The architect seat's review of 2026-09-28 settled **four** gaps, ruled
as **D9** (the residual register's write path), **D10** (worktree ownership metadata), **D11** (the
published-vs-local boundary), and **D12** (the deletion archive's second home). The long-form
narrative — the gap each ruling closed, the premise it corrected, and the command that established
it — is kept in `guides/architect-phase-1-review-20260928.md`; each plan repeats the ruling it
depends on in its own `### Architect ruling (Phase 1 review 2026-09-28)` section. Read the ruling
row above for the decision; read the guide for how it was reached.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| `20260928-harness-state-contract` | Every engine-read lifecycle document passes the engine's validators, with a durable checker | Todo | 27 snapshots + root register + project register; ships `scripts/validate_harness_state.py` + a package test; **also asserts the D11 published-set boundary as a ratchet** |
| `20260928-workspace-reclamation` | Reclaim merged worktrees/branches, bound the harness scratch trees, rewrite the handoff page | Todo | Git-operations plan; no product code; **writes `HANDOFF.md`; makes D11 real in `.gitignore` (Task 4); publishes `.tmp/deletion-records/` under `docs/archive/` (D12) and never deletes it** |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Checker landed and green over the whole harness | 2026-09-28 | open |
| Register contract violations triaged (fixed or explicitly legacy-labelled) | 2026-09-28 | open |
| Workspace reclaimed; handoff page rewritten | 2026-09-28 | open |

## Acceptance Criteria

- `scripts/validate_harness_state.py` exits 0 over the whole `.mstar/` tree, and the
  package test that wraps it is green (or skips with a stated reason when the harness
  dir is not reachable from the package). **The checker also asserts the D11 published-set
  boundary**: a tracked path under `.mstar/` that the amended `.gitignore` set does not
  publish is a violation naming the path, so the next force-add fails a repo check instead
  of waiting for the next hygiene pass.
- No workflow snapshot violates the engine's contract; every value either comes from
  the repository's own history or states plainly that it is unknown.
- The project residual register's violations are resolved or carry an explicit
  legacy disposition — the count reported by the checker is zero for the "violating"
  bucket. Per D7 the legacy bucket is additionally expected to be **zero**. That bucket is
  scoped to the 23-entry field-completion set, so a non-zero count means an entry in that set
  has no recorded substance to derive from — reported, not waived. An absent `what` outside that
  set is **not** a finding: it is contract-valid on 98 entries. Per **D9** the corrected register
  reads back clean under `mstar persist get --validate residuals --key _default` (exit 0),
  which is the acceptance test — not merely a checker the plan wrote itself.
- Merged worktrees and their branches are reclaimed; no reflog-only work is destroyed.
  Per **D10** every reclaimable ref is reclaimed through the engine's own verdict path where
  one exists (`--worktree <path>` assertion for the released-lease cases), and any divergence
  from the planner names the refusal code it diverges from.
- `HANDOFF.md` describes the actual current state (four iterations shipped since the park
  — PRs #18, #20, #21, #23, #24, #25, #26 — one active) and does not assert "nothing is in
  progress".
- Per **D12** the 2026-09-25 deletion archive exists in Git under
  `bilibili-asr-archive/docs/archive/deletion-records-20260925/`, byte-identical to the
  `.tmp/` working copy, with both sha256 values recorded in the tracked README.

## Non-Goals

- Any product behaviour change; any edit under `bilibili-asr-archive/src/` except the
  new `scripts/` checker and its test.
- `cli.py` size / `derive-manifest` retirement (roadmap-tracked already).
- Deleting the parked `iter-2026-09-transcript-editorial-stages` refs (operator-owned;
  `HANDOFF.md` §9 governs them).
- Reconstructing absent SDD trails for iterations whose worktrees never carried a
  `.mstar/` copy.
- **Anything under `{KNOWLEDGE_DIR}`** — no re-index, no `compound-refresh` pass, no
  doc merged or deleted. (D3.) The `{KNOWLEDGE_DIR}` documents the roadmap's P3 row tracks
  stay exactly as they are. That row reads "6/9 篇 … 过不了 engine 自己的 `compound validate`",
  carried forward unverified; re-measured 2026-09-28 over the 25 tracked non-README knowledge
  docs, **0 fail** `mstar compound validate`, so both the 6 and the 9 are stale. Correcting the
  roadmap row is out of scope here (D3, and the roadmap is another session's file) — recorded so
  the next pass does not inherit the stale pair.
- **Deleting `.tmp/deletion-records/`** or any other file whose only copy is local
  (D8, D12). Reclamation removes re-derivable scratch, never the last copy of a deleted
  path. D12 changes how that is guaranteed — the archive is now published into Git, so the
  `.tmp/` copy is no longer the last one — but the exclusion itself stands unchanged.
- **Register rewrites through a retired writer path**: this iteration corrects
  `residuals.json` in place and does **not** stand up a second findings authority beside
  `store.db`, and does **not** initialise an issue store. **Amended by D9:** the correction
  goes through `mstar persist residuals --expect-version <sha256>` — which *is* live on this
  installation, contrary to the original gap text — not through a bare hand-edit. The
  prohibition on standing up `store.db` is unchanged: `mstar store` / `mstar issue` do not
  exist on this build at all.
- **Product-source quality work of any kind**: no lint/format sweep, no dead-code
  removal, no dependency upgrade, no `src/` or `tests/` cleanup — a reader should
  not assume "hygiene" reaches the package tree.
- **Deleting or rewriting the two `.mstar/sdd/` stray top-level reports**, and no new
  `_reports/` convention invented (plan B inspects and records only).
- **Widening the published set beyond D11's single amendment.** Iteration contract drafts
  (`{ITERATION_DIR}/<id>/specs/**`) are published because the published set cites them by
  exact path; the iteration process face and all of `{PLAN_DIR}` stay local. The 11 currently
  non-conforming paths are classified per D11's table — **five are rule-consistent under the
  Amendment and stay, six are frozen debt** (4 iteration process files + 2 plans). **The
  boundary is enforced by the plan A checker as a ratchet**, not re-decided here: a *new* path
  outside the published set fails immediately, and the six may only shrink. Removing those six
  from the index is a `git rm --cached` step this iteration deliberately does **not** perform —
  it drops the delivery record of two closed iterations out of a clone, which is a boundary
  change the operator should see before it happens, not a side effect of a hygiene pass
  (deferred as plan B **D-5**).

## Roadmap Position

- Current iteration: harness + workspace hygiene — the recorded state stops lying to
  the engine, and finished work stops occupying the working tree.
- Next iteration: the product-facing residual backlog registered against
  `iter-2026-09-ops-readiness` (O-R1..O-R7) and the roadmap's P2.5 tails, owner PM,
  trigger = this iteration's Phase 6 close.
- Carried out of this iteration to a later harness round (each has an architect ruling recorded
  in the plan that owns it — none is left as a marker; the full narrative of all four rulings is
  `guides/architect-phase-1-review-20260928.md`):
  - **the project residual register's write path and findings authority** (plan A §"Architect
    ruling (Phase 1 review 2026-09-28) — the register's write path", ruled **D9**): that register
    is hand-maintainable through the CAS-guarded `persist` put on this installation; migrating to
    `store.db` becomes available only when a build ships `mstar store` / `mstar issue`, which
    this one does not (plan A **D-2** is the trigger).
  - **whether snapshot rows must carry worktree-ownership metadata** (plan B §"Architect ruling
    (Phase 1 review 2026-09-28) — worktree ownership metadata", ruled **D10**): not mandatory.
    The engine already writes it at handoff and `prepare`, so the refused rows are historical,
    and `--worktree <path>` is the sanctioned assertion path for the cases plan B can evidence
    (plan B **D-2** covers only the residue the assertion cannot reach).
  - **the published-vs-local tracked-file boundary** (`.mstar/AGENTS.md`, ruled **D11**): fixed
    with one amendment (iteration contract drafts), enforced by the plan A checker as a ratchet.
    The **six** frozen debt paths stay tracked in this iteration — no plan here owns a
    `git rm --cached` step — so the checker's D11 leg tolerates exactly those six and fails on
    anything new. Recorded so the checker's first run is not misread as a defect in this
    iteration, and so the six cannot silently grow (plan B **D-5** carries the removal).
  - **the deletion archive's second home** (plan B §Task 2, ruled **D12**): plan B publishes it
    under `bilibili-asr-archive/docs/archive/deletion-records-20260925/`; the residual
    no-automated-gate risk is plan B **D-4**.
  - **`.mstar/sdd/` stray top-level gate reports** — left as a recorded observation by plan B
    with no owner; a future harness round should give them a home or retire them, since neither
    plan owns the SDD surface.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| iteration_base_branch | main |
| spec_integration_branch | iteration/iter-2026-09-harness-hygiene |
| target_branch | main |

## Iteration package

Package root: `.mstar/iterations/iter-2026-09-harness-hygiene/`. These are **local process
artifacts** — D11 keeps the process face out of the published set, so a clone carries only
`specs/**` from this package. Promoted to `{KNOWLEDGE_DIR}/` by `mstar-compound` at iteration
close (`mstar-iteration` §3.2).

| Path | Purpose |
|------|---------|
| `delivery-compass.md` | This file — iteration state SSOT (frontmatter `status`) |
| `guides/architect-phase-1-review-20260928.md` | The four Phase 1 gaps and how each was ruled (D9–D12) |
| `guides/` | Further iteration-level exploration and process notes |
| `specs/` | Iteration-scoped spec drafts (empty today — both plans work from `{SPECS_DIR}/asr-archive-cli.md`) |
| `README.md` | Package index |

## Compound Round Summary

Round outcome: **created** (1 new knowledge doc). One lesson met the bar — it is general,
reusable beyond this repo, and it was learned by *failing three review rounds on it*:

- `{KNOWLEDGE_DIR}/best-practices/verdicts-need-an-unsteerable-channel.md` — a wrapper that
  reaches its verdict by parsing a child process's output has handed the verdict channel to
  whatever is being judged. Four steerable channels reproduced on one real CLI (field values,
  paths, child environment, argv), the shape that holds (classify readability yourself, then
  let the exit code carry the verdict), why the suite's own oracle agreed with the bug by
  construction, and two transferable git side-notes.

Not promoted (deliberately):
- the checker itself is tooling, not a contract — no new `{SPECS_DIR}` document. What it
  asserts about the published boundary was already ruled (compass D11) and is recorded in
  `.mstar/AGENTS.md`, which this iteration amended.
- `.mstar/AGENTS.md`'s amendment is a rule change, not a lesson; it lives in the harness
  document that owns it rather than being duplicated into knowledge.
- the iteration-scoped architect review stays in the package
  (`{ITERATION_DIR}/iter-2026-09-harness-hygiene/guides/architect-phase-1-review-20260928.md`).

## Quality Gate Summary

| gate | outcome |
|---|---|
| Phase 1 Review & Edit chain | 3 dispatched seats in order (product-manager → architect → writing-specialist), each returning edits to disk; PM lock after all three |
| Per-task L2 (plan A, Task 1) | **4 review rounds**: 1 initial + 3 re-reviews. Found and closed 3 Criticals, 3 Importants, 1 Minor, each reproduced before and after |
| Per-task L2 (plan A, Tasks 2-3) | 1 round, Approved (0 Critical / 0 Important / 3 Minor, report-text only) |
| Per-task L2 (plan B, Tasks 1-4) | no L2 round; the plan's work is ops/docs, reviewed at plan level |
| Plan QC tri-review (N=3, both plans) | plan A: 3 Critical / 7 Important / 6 Minor, all fixed. plan B: 0 Critical / 24 Important+Minor across three angles, all actionable ones fixed |
| QA gate (mandatory, both plans) | plan A: pass-with-conditions (5, all closed). plan B: pass-with-conditions (5, all closed) |
| Delivered test suite | `54 passed, 3 skipped` in a worktree; `57 passed, 0 skipped` where the live harness is reachable. The three skips each state a reason and are covered by fixture cases |
| Durable guard | the two plans' own checker, asserted by its own suite, over the real tree: exit 0, `documents=30 ok=30 fail=0 not-validated=0`, `published=35`, `frozen-debt=6`, `tracked=41` |

Three defects the iteration's own gates caught are worth naming, because each was a *self*-error:

1. The PM's first checker design derived verdicts from engine prose; **the existing tests
   caught it** (the test file was never weakened to make it pass).
2. A register bound left at `<= 144` from a pre-fix state let a `0 -> 1` regression pass; the
   QC seat measured it, and the fix became an exact assertion.
3. The PM's fix for a truncated commit hash **introduced the same defect one letter over**
   (`ebbbac` for `ebbbbbac6`); the QA gate caught that too.

