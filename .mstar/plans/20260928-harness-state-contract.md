---
plan_id: 20260928-harness-state-contract
iteration: iter-2026-09-harness-hygiene
iteration_compass: .mstar/iterations/iter-2026-09-harness-hygiene/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
status: registered
gate_decision: pass
gate_decision_reason: Prepare inherited from the 2026-09-28 main-based reconciliation, whose findings this plan executes; compass D1/D6 fix the discipline
gate_decided_at: 2026-09-28
registered_at: 2026-09-28
planned_at_sha: 371693b
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# Every engine-read lifecycle document passes the engine's own validators

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Steps use checkbox (`- [x]`) syntax.
>
> **Scope note.** This plan corrects *recorded state*, not product behaviour. No file under
> `bilibili-asr-archive/src/` changes except the new checker; no test outside the new
> checker's suite changes.
>
> **Boundary with plan B (`20260928-workspace-reclamation`, compass `## Scope`).** This plan
> owns the harness **documents** the engine reads: `workflows/*/snapshot.json`,
> `status.json`, `projects/*/residuals.json`, plus the checker and its test. It does **not**
> touch worktrees, branches, `.tmp/`, or `HANDOFF.md` — plan B owns the git/workspace face
> and is the only writer of `HANDOFF.md`. Two consequences a reader should not have to
> infer: (a) this plan never runs a git command that mutates a ref; (b) when the checker
> needs a harness path it takes it as an argument, so a plan-B reclamation changing a
> worktree path cannot break this plan's verification.

## Current state (evidence — re-read before dispatch)

Measured against `mstar` 3.11.2 (the CLI is installed at `/usr/local/bin/mstar`) on
2026-09-28, `main` = `371693b` (== `origin/main`, 0 ahead / 0 behind):

- **27 workflow snapshots** under `.mstar/workflows/*/snapshot.json` — 26 terminal
  (`iteration`/`completed` ×17, `plan`/`completed` ×8, `plan`/`stopped` ×1) plus **this
  iteration's own `running` snapshot** (`iter-2026-09-harness-hygiene`, an `iteration`
  registered 17:39 on 2026-09-28; the only non-terminal snapshot besides the parked
  `e2e-23191782-season-7686105`, which is `plan`/`stopped`). A first pass corrected
  these violation classes, each reproduced against the engine's own validator before and
  after: `Done` plan row carrying an `execution_lease` (3 files); terminal snapshot carrying
  `integration_merge_lease` (8); `type: plan` lifecycle carrying a blank `compass_ref` (4);
  `integration_worktree_path: null` (1); legacy `control_worktree_path` key (10);
  a legacy file missing `schema_version`/`type`/`status`/`started_at`/`updated_at` and using
  `plan_id` with a null `file` (1); and a `delivery` block with non-contract members and
  `pr` as a number (1). **Re-verified 2026-09-28: all 27 now pass
  `mstar status validate <snapshot>`, and the re-checked classes are zero** (0 files carry
  `control_worktree_path`; 0 carry a null `integration_worktree_path`; 0 `Done` rows carry
  an `execution_lease`; 0 terminal snapshots carry an `integration_merge_lease`). Nine
  `type: plan` snapshots legitimately carry **no** `compass_ref` key at all — the validator
  treats the field as optional, so this is not a violation (a key present-but-blank was the
  4-file class, and that is gone).
- **Root register** `.mstar/status.json`: `version: 2`, `updated_at: 2026-09-28`, and
  `workflows: [iter-2026-09-harness-hygiene]` — it is **no longer empty**: the engine
  registered this iteration when it started, and it passes `mstar status validate`. This is
  *correct* in both directions: the 26 terminal lifecycles were removed at terminal
  (removal-at-terminal), and the one active lifecycle is registered. **Note for Task 3:**
  the mtime-sensitive fallback observation below was made *while the register was empty*;
  its trigger condition is "the root register is legitimately empty", which is not today's
  state.
- **Project residual register** `.mstar/projects/_default/residuals.json`: 122 entries in
  28 groups. Evaluated against the engine's `validateResidual` +
  `validateProjectRegister` rules: **144 violations**, independently reproduced twice
  (`mstar persist get --validate residuals --key _default` returns exactly this count and
  exit 1; a local re-implementation of the engine's rule set agrees on the total and on
  every class). Dominant classes: `source` (23), `scope` (23), `tracking` (23), `title`
  (22) absent/blank; `owner` (11), `decision` (11), `target` (11) absent; plus 7 invalid
  `decision` values, 7 `source_plan` ≠ entries-key mismatches, and 6 invalid `lifecycle`
  values (`closed`, `partially-closed` — neither is in the enum
  `open|resolved|waived|superseded|duplicate`). The absent-field sets are **not identical**:
  `source`/`scope`/`tracking` are each missing on **23** entries, `title` on **22** — and the
  22 are a strict subset of the 23 (the extra entry is `20260926-video-metadata-enrichment`
  `R5`, a partially-migrated entry that has a `title` but no provenance fields). The
  field-completion set for Task 2 is therefore **23 entries**, while DoD 3 is stated over all
  122. Re-derive both counts with
  `MSTAR_HARNESS_DIR=.mstar mstar persist get --validate residuals --key _default`.
- **`mstar status tech-debt`** reports `total_open: 90` (43 `open` + 47 with no `lifecycle`
  key) — the register is the live authority, so its shape errors degrade every downstream
  reading of open work. It exits 0 even while the register fails validation, printing
  "project register is the source of truth — no stored summary to drift (informational)";
  the violations are surfaced by the validating readers, not by this one.
- The engine emitted `workflow.selection.snapshot-unreadable` at session start before the
  snapshot pass; the selection then resolved to a *different* lifecycle on each check as
  file mtimes moved. That was observed while the root register was empty, so the fallback
  path's mtime sensitivity is a harness observation, not a document defect — it is recorded
  here and **not** fixed by this plan (see `## Deferred`).

## Goal (intent gate)

**真实目标**：引擎读到的每一个生命周期文档都通过引擎自己的校验器；并且这种一致性由一个**可重复运行**的检查守住，而不是靠一次性人工核对。
**成功判据**：DoD 1–4。**非目标**：任何产品行为变更；重建缺失的 SDD 记录；改动引擎自身；触碰 git/worktree/分支/`.tmp`（plan B 的面）。

> **What "the engine's own validators" means here, precisely.** `mstar status validate
> <path>` covers a snapshot and the v2 root register. For `projects/*/residuals.json` the
> same command **misroutes** — it reports `status.migration-required` (the document has no
> `schema_version`) instead of validating it, and exits 1 for a document that is in fact
> fine. That is exactly why Task 1's requirement to delegate rather than hand-roll carries
> an exception, and why Task 2's verification uses `mstar persist get --validate residuals
> --key <project>` — the one engine-backed surface that runs `validateProjectRegister` and
> returns exit 0/1 with the violation list. Both facts were reproduced on 2026-09-28:
> `status validate` on the register → 1 `status.migration-required` violation, exit 1;
> `persist get --validate` on the same bytes → 144 real violations, exit 1.

## Task 1: Ship the checker as a repo tool + package test

- [x] Add `bilibili-asr-archive/scripts/validate_harness_state.py`: walks a harness dir and
  validates (a) every `workflows/*/snapshot.json`, (b) `status.json`, (c) every
  `projects/*/residuals.json`, printing per-document pass/fail with the violation code
  and message. Exit 0 when clean, 1 when any violation, 2 on usage.
  The **root register** here is `.mstar/status.json` (the engine's v2 workflow-level record);
  the **project residual register** is `.mstar/projects/<project>/residuals.json` (the
  severity SSOT for open residual findings, `_default` for this repo).
- [x] The checker must delegate to the **engine's own rules**, not a hand-rolled copy: it
  shells out to `mstar status validate <path>` where that command applies (snapshots, root
  register) and to `mstar persist get --validate residuals --key <project>` for
  `residuals.json` — the only engine-backed reader that reaches a register. Where neither
  command can reach a document it must **fail loud** (report "not validated", never a silent
  pass), and the module docstring must cite the engine rule set by `file:line` so a future
  reader can re-derive it.
- [x] **Assert the published-set boundary (compass D11) — as a ratchet, not an absolute.**
  Two terms this leg defines once and uses throughout: the **published set** is the four
  prefixes the amended `.gitignore` publishes — `{HARNESS_DIR}/AGENTS.md`, `{SPECS_DIR}/**`,
  `{KNOWLEDGE_DIR}/**`, `{ITERATION_DIR}/<id>/specs/**` — and nothing else; a **ratchet** is a
  check that fails on any *new* out-of-set path while tolerating a frozen, finite debt list
  that may only shrink. That **frozen debt list** is the six tracked process-face paths named
  and attributed in `.mstar/AGENTS.md` — the delivery records of two *closed* iterations whose
  removal is the operator's call.
   The checker gains a fourth leg: enumerate tracked paths under `{HARNESS_DIR}`
  (`git ls-files .mstar`) and fail on any path outside the published set — i.e. anything not
  under `{HARNESS_DIR}/AGENTS.md`, `{SPECS_DIR}/**`, `{KNOWLEDGE_DIR}/**`, or
  `{ITERATION_DIR}/<id>/specs/**` — **unless it is one of the six debt paths frozen in
  `.mstar/AGENTS.md`**. The debt list is read from that file, so the two cannot drift, and it
  may only shrink: a listed path that is no longer tracked is reported as **stale debt** (a
  note, not a failure), so the ratchet tightens by itself once the operator removes one.
  **Why a ratchet rather than a clean sweep:** the six are the delivery record of two *closed*
  iterations, and `git rm --cached` on them is a boundary change the operator should make
  knowingly (plan B **D-5**), not a side effect of this plan. An absolute assertion would be
  red on arrival, which teaches the reader to ignore it.
  **Two boundaries the assertion must respect** (both verified 2026-09-28, and getting either
  wrong turns the check into a false alarm):
  - the published-set prefix list is `{"AGENTS.md", "specs/", "knowledge/", "iterations/<id>/specs/"}`
    **excluding** `{ITERATION_DIR}/README.md` — a bare `iterations/` prefix would wrongly pass
    the iteration *process* face, which D11 keeps local;
  - the classification uses `git check-ignore --no-index`, **never** bare `git check-ignore`:
    a tracked file is masked by the index, so the plain form reports nothing for exactly the
    paths this leg exists to find (reproduced: plain form silent, `--no-index` reports
    `IGNORED`). The checker must read the *rules*, not the index, and must compare against the
    `D11` prefix list rather than merely asking "is it ignored" — a force-added process file
    is both tracked and ignored, which is the whole finding.
- [x] **The check must have working negative controls** (same requirement as the register
  leg), and both halves need one: assert against a scratch fixture that force-adding a path
  outside the published set makes the leg exit 1 and names the path, **and** that a fixture
  path on the frozen debt list is tolerated. Without the second control, "the ratchet works"
  and "the check is simply off" are indistinguishable. An absence assertion counts as
  evidence only when the fixture can reach the falsifier
  (`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md`).
- [x] Add `bilibili-asr-archive/tests/test_harness_state.py`: locates the harness dir
  relative to the package (`../../.mstar`), runs the checker, asserts exit 0; **skips with
  an explicit reason** when the harness dir is not reachable (the repo's corpus-gated
  precedent — a skip must say why, never silently pass).
- Files: `bilibili-asr-archive/scripts/validate_harness_state.py` (new),
  `bilibili-asr-archive/tests/test_harness_state.py` (new).

## Task 2: Resolution rule for the register's 144 violations

- [x] Fix the **mechanically decidable** violations in place, preserving every semantic
  value:
  - invalid `lifecycle: "closed"` → `resolved`. There are **four**: `D-R12`
    (`20260927-evidence-dashboard`, already carries `closed_at: 2026-09-27`) and `A-R4`/`A-R5`/
    `A-R6` (`20260926-audio-inventory`), which have **no `closed_at` key at all** — verified
    absent, not null. The engine requires `closed_at` (`status.ts:365-380`) for any lifecycle
    other than `open`, so those three gain a **new** violation the moment the enum is fixed.
  - invalid `lifecycle: "partially-closed"` → **`open`**, not `resolved`, for R3 and R4
    (`20260926-video-metadata-enrichment`). Their own notes say so in words — R3: "HALF CLOSED
    … The second half of R3 scope is NOT closed"; R4: "MERGE HALF SETTLED, GOVERNANCE HALF
    OPEN … Leave open for the ruling". They already carry `closed_at: 2026-09-28`, which is
    valid on an `open` entry, so nothing else changes. Mapping them to `resolved` would assert
    a closure their own text denies.
  - invalid `decision` (`open`, `closed`, `waive`) → the enum member the entry's own prose
    supports (`defer` / `accept` / `risk-accepted`);
  - `source_plan` ≠ the `entries` key → correct `source_plan` to the key (the key is the
    plan the register groups by). **Note the shape of this class:** all 7 are one group
    (`iter-2026-09-ops-readiness`) whose `source_plan` carries a trailing provenance
    string (`"iter-2026-09-ops-readiness QC tri 2026-09-28"`). The provenance belongs in
    `source` (or `tracking`), not in `source_plan`; move it, do not delete it.
- [x] For the **23 pre-contract entries** — exactly the entries missing at least one of
  `title`/`source`/`scope`/`tracking`: `iter-2026-09-ops-readiness` `O-R1`…`O-R7` (7),
  `20260926-audio-inventory` `A-R1`…`A-R9` (9), `20260928-layout-shape-a` `L-R1`…`L-R4` (4),
  and `20260926-video-metadata-enrichment` `R5`/`R6`/`R7` (3). Populate each field from the
  entry's own recorded text (`what`/`closure_note`/`tracking` prose). Where a field is
  genuinely not recorded anywhere, write the literal disposition
  `"unknown — not recorded at registration (pre-contract entry)"` rather than inventing a
  plausible value. Two sub-shapes, because they need different work:
  - **11 fully pre-contract** (the 7 `O-R*` + 4 `L-R*`): these also lack `decision`, `owner`
    and `target` — four required fields to derive, all four present in the plans that
    registered them.
  - **12 partially migrated** (the 3 `R*` + 9 `A-R*`): these already carry
    `decision`/`owner`/`target` and need only the four absent provenance fields. Do **not**
    rewrite the fields they already have — they were written under the current contract.
  Per compass **D7** (the Q1 ruling) field-completion is the *only* path: there is no
  standing legacy class here, because all 23 carry their own `what` prose. **The bucket is a
  recorded verification, not a checker behaviour** — struck as a tool requirement under DoD 3
  with the PM ruling and its reason (membership is a historical property the delivered
  document cannot recover); see the DoD 3 note. What `what` absence does and does not mean
  is still a Global Constraint, and Task 2 honoured it.
- [x] **Do not treat an absent `what` as a defect on its own.** 98 of the 122 entries have no
  `what` key, and they are **contract-valid** — `what` is not one of the nine required
  fields. It matters here only as one *source of derivation* for the 23 above; the accuracy of
  this plan's Task 2 rule depends on that distinction, and an executor who "fixes" the other
  98 by inventing `what` text has invented product history.
- [x] No entry's `severity` or business state changes; **the only `lifecycle` transitions are
  the two enum repairs above** (`closed` → `resolved`; `partially-closed` → `open`), and no
  entry's `created`/raising date changes. Two consequences the executor must not paper over:
  - the three `A-R4`/`A-R5`/`A-R6` entries gain a **required** `closed_at` when their enum is
    repaired. Supply the date from the entry's own `closure_note` text — all three record
    "CLOSED… 2026-09-28" — which is a recorded value, not an invented one. If an entry's note
    did **not** carry a date, `closed_at` stays absent and the entry is reported, never dated
    by guess;
  - `D-R12` and `R3`/`R4` need no date work: the first already has `2026-09-27`, and the other
    two keep `2026-09-28` (valid on `open`).
- [x] **Write path — the engine put exists, and the register has to be corrected *locally* first
  to reach it (compass D9).** This plan's original text said the register was a retired writer
  target and that Task 2 must therefore be a bare hand-edit. **That was wrong on this
  installation and has been corrected.** On the installed `@mstar-harness/cli` 3.11.2
  (`/usr/local/bin/mstar`), `residuals` **is** a writable coordinated kind:
  `PERSIST_KINDS = ["status","snapshot","residuals","review","json"]` and
  `COORDINATED_PERSIST_KINDS = ["status","snapshot","residuals"]`, validated by
  `validateProjectRegister`. The sequence that clears the run is a deliberately two-step one,
  because the put validates before it writes — which is the chicken-and-egg to break:
  1. **Correct the document in place** (bare hand-edit), because `persist` will refuse a
     document that fails its own validator — the current register produces 144 violations,
     so there is no state in which the engine will accept the first write.
  2. **Then land that same document through the engine put**, against the token for the bytes
     just written:
     ```sh
     # token for the exact bytes now on disk (a plain sha256sum is accepted;
     # `persist get --versioned` cannot be used yet — it validates before printing)
     V="sha256:$(sha256sum .mstar/projects/_default/residuals.json | cut -d' ' -f1)"
     MSTAR_HARNESS_DIR=.mstar mstar persist residuals --key _default \
       --file .mstar/projects/_default/residuals.json --expect-version "$V"
     ```
     Reproduced end-to-end on a scratch harness: `persist residuals/_default: OK`.
     **Two verified facts the executor must not re-derive wrongly:**
     - `mstar persist get --versioned` **cannot supply this token while the register is
       invalid** — it validates before printing and exits 1, so the token must come from
       `sha256sum` on the corrected file. This is *only* true for the broken state; once the
       document validates, `--versioned` works normally.
     - **The put preserves the outer `{ "entries": … }` shape and re-serializes the payload**
       (2-space indent), so the written bytes are semantically equal to the payload but not
       byte-identical to an arbitrarily formatted input file. Verified by `cmp` + a
       `json.load` equality check. The executor should therefore treat the **read-back** as the
       acceptance test, not a byte comparison of the input file.
  3. **Acceptance test:** `MSTAR_HARNESS_DIR=.mstar mstar persist get --validate residuals
     --key _default` exits **0** and prints no violations. This is an engine-produced verdict,
     not the checker's own opinion, and Task 3 relies on it.
  **Do not** initialise `store.db`, do not run `mstar migrate`, and do not migrate the register
  to the issue store: `mstar store`, `mstar issue` and `mstar catalog` are `unknown command` on
  this installed build (exit 1), so that route is not merely out of scope, it does not exist
  here. The engine source registers all three (`packages/cli/src/index.ts:6403-6410`), so a
  future build will offer it — that is the trigger on **D-2** below, not this plan's work.
- Files: `.mstar/projects/_default/residuals.json` (local process artifact — gitignored by
  convention; the correction is verified by the engine read-back in step 3 and by re-running the
  checker).

## Task 3: Prove the whole tree clean, and record the residual observation

- [x] Run the checker over `.mstar/` and attach the output (exit code + the per-document
  summary lines) to this plan's `## Verification`.
- [x] Record in `.mstar/projects/_default/roadmap.md` (append-only section, not a rewrite)
  the one item this plan deliberately does NOT fix: the engine's fallback lifecycle
  selection is mtime-sensitive when the root register is legitimately empty, so a session
  can resolve to a different historical lifecycle on successive starts. Closing condition
  and owner stated, **and the precondition written down** — the observation was made while
  the register was empty, so the row must say that, or a later reader will test it against
  a register that now carries an active entry and conclude the row was never true.
- [x] Confirm no snapshot's `status`/`ended_at`/`plans[].status` differs from what it was
  before this plan began: `git diff` over the harness tree is not available (process
  artifacts are gitignored), so the check is a field-by-field diff against the plan-time
  values recorded in Task 1's test fixture. **This plan's own snapshot is the one
  legitimate exception** — `iter-2026-09-harness-hygiene` is `running` and the engine
  advances its `updated_at`/plan rows as this plan runs; exclude it from the diff by name
  rather than by pretending it is frozen.

## Global Constraints

- The engine is the authority. Where the engine's validator and this plan's prose
  disagree, the validator wins and the plan text is corrected.
- Never invent a status, date, merge commit, or plan outcome. A genuinely unknown value is
  written as unknown; a genuinely absent plan file is recorded as absent.
- `mstar status validate` does **not** accept a project register path — it routes by
  document discriminator and reports `status.migration-required`. The checker must not
  misreport that misrouting as a register violation, and must route the register through
  `mstar persist get --validate residuals --key <project>` instead (Task 1).
- The register's engine writer is **live on this build, and this plan uses it** (compass D9):
  Task 2 corrects the document in place only to break the validate-before-write
  chicken-and-egg, then lands it through
  `mstar persist residuals --expect-version <sha256>`, and the acceptance test is
  `mstar persist get --validate residuals --key _default` exiting 0. Do not initialise
  `store.db`, do not run `mstar migrate`, and do not migrate the register to the issue store —
  those verbs (`store` / `issue` / `catalog`) do not exist on the installed 3.11.2 build, and
  moving the findings authority is out of this iteration's scope anyway (compass Non-Goals).
- **`what` is not a required field and its absence is not a violation.** 98 of 122 entries
  omit it and are contract-valid; the 23 entries Task 2 completes all happen to carry it.
  Had the bucket been implemented as a tool check it would have had to be scoped to those 23
  (not the 98), which is exactly why it cannot be: see the DoD 3 ruling. Re-derive the split
  with the engine's own reader before acting:
  `MSTAR_HARNESS_DIR=.mstar mstar persist get --validate residuals --key _default`.
- **`lifecycle` is optional** — 47 entries omit it and that is contract-valid. Do not
  backfill it (that would be a data decision about what is open, deferred as plan B's D-3).
- New names go through `naming-analyzer` before use.
- Verification is scoped: run the new checker and the new test; the full package suite is
  CI's job (and is unaffected — no product module changes).

## Open questions (owned, non-blocking)

| # | Question | Owner |
|---|---|---|
| `~~MQ1~~` | ~~Should the 22 legacy entries be field-completed or formally migrated out as legacy?~~ **RULED by product-manager (Phase 1 review 2026-09-28): field-completed, no standing legacy class — compass D7.** The set is **23** entries (those missing at least one of `title`/`source`/`scope`/`tracking`: 7 `iter-2026-09-ops-readiness` `O-R*`, 9 `20260926-audio-inventory` `A-R*`, 4 `20260928-layout-shape-a` `L-R*`, 3 `20260926-video-metadata-enrichment` `R5`/`R6`/`R7`), and all 23 carry their own `what` prose, so each required field is derivable from the entry's own recorded text and the literal not-recorded disposition covers the remainder. The "migrated out as legacy" alternative was rejected because it would create a permanent exemption class in a document whose other 99 entries all satisfy the contract, and because nothing here is genuinely unrecorded. The checker's legacy bucket survives as a **residual, expected-empty** branch **scoped to those 23** — a reporting device, not an exemption this plan may claim; scoping matters because 98 further entries legitimately omit `what` (it is not a required field). Not re-openable without a new product decision. | product-manager (ruled) |

## Verification (captured 2026-09-28; QC seat 2, Q2-F3)

The acceptance run, verbatim:

```
$ python scripts/validate_harness_state.py /root/workspace/bilibili-asr-archive/.mstar
summary: documents=30 ok=30 fail=0 not-validated=0 | frozen-debt=6 | new-out-of-set=0 |
         published=35 | registers=1 | root-register=1 | snapshots=27 | stale-debt=0 | tracked=41
exit=0
```

Negative control (required by this section). The injected violation is a malformed
`execution_lease`; **the count and the codes depend on which row carries it** (QA
gate, F-1):
- on a row whose status is **not** `Done` (the row used): `[snapshots] FAIL …: 3 violations`
  naming `lease.execution-lease.missing-claimed-at`, `…missing-worktree-path`,
  `…missing-working-branch`;
- on a **`Done`** row (as an earlier caption here said): **5 violations**, adding
  `status.plan-row.done-with-lease` and `lease.execution-lease.missing-holder`.

Either way the falsifier is reachable and correctly named, so the clean run above is
evidence rather than an absence. The caption is corrected rather than the control.

Full DoD-by-DoD evidence: `.mstar/sdd/20260928-harness-state-contract/task-3-report.md`.

### Naming (QC seat 2, Q2-F4)

The plan's Global Constraints require new names to go through `naming-analyzer`. Trace:
the only new public names are the checker's file name (`validate_harness_state.py`, chosen
to sit beside the package's existing `check_asr_env.py` / `verify_baseline.py` and to read
as an operator tool), its entry point (`main`, `run_all`), and the leg labels
(`snapshots` / `status` / `registers` / `ratchet`), which mirror the four document classes
the plan enumerates rather than inventing a private vocabulary. No new identifier was
introduced without checking it against the package's existing conventions; no rename was
performed.

## Definition of Done

1. `python scripts/validate_harness_state.py <repo-root>/.mstar` exits 0.
2. `pytest tests/test_harness_state.py` passes (or skips with a stated reason); the test
   fails loudly when a snapshot or the register regresses to a violating shape.
3. Zero entries in the residual register carry an out-of-enum `lifecycle`/`decision`, a
   `source_plan` mismatch, or an absent required field; entries whose value is genuinely
   unrecorded say so in words. **All 122 entries are in scope.** ~~The checker also reports the **legacy bucket**,
defined narrowly as *entries in the 23-entry field-completion set whose `what` is also
absent*; all 23 carry `what`, so the bucket reports zero.~~
**PM RULING 2026-09-28 (QC seat 2, Q2-F1) — clause STRUCK as a tool requirement, reason
CORRECTED per QA gate F-3.** The underlying fact is verified and stands: the field-completion
set is exactly 23, and 0 of them lack `what`. The clause is struck because it cannot be
encoded *faithfully enough to be a guard*, and the accurate statement of why is sharper than
the first version of this note claimed:

- **The `{no what}` proxy is wrong** (98 entries, i.e. the false alarm the clause forbids).
- **The `{has what}` proxy is *nearly* right**: it selects **24 = the 23 ∪
  `20260926-video-metadata-enrichment/R1`** — verified on the delivered register
  (122 entries, 24 with `what`). So a proxy does separate the 23 from the 98, up to one
  named entry.
- **What defeats it is that nothing distinguishes `R1`.** `R1` carries `what` and is not
  in the pre-contract completion set; no key-presence, key-absence, blank-value, key-order
  or field-token predicate separates it from the 23 (QA searched a 4 959-token pool with all
  conjunctions up to 4 atoms over 475 predicates, and found no exact selector).

So the clause is not "unencodable because history"; it is **one entry away from encodable,
with no principled way to exclude that entry**, and a guard that needs an exception carved
for a specific id is a device that will be edited whenever it complains. DoD 3's kept half
("zero contract violations") is tool-enforced and met (144 → 0, engine read-back exit 0); the
bucket stays a **recorded verification** in `task-2-report.md`, the QC reports and here.
**Not re-openable without a new product decision.**

**Additionally (compass D9):** the corrected register passes the engine's own verdict —
   `MSTAR_HARNESS_DIR=.mstar mstar persist get --validate residuals --key _default` exits 0 —
   and the document was landed through `mstar persist residuals --expect-version <sha256>`,
   not left as an unlanded hand-edit.
4. The mtime-sensitive selection observation is recorded in `roadmap.md` with a closing
   condition and owner **and with its precondition stated**: it was observed while the root
   register was legitimately empty, which is not today's state.
5. **The published-set boundary holds as a ratchet (compass D11).** The checker's tracked-set
   leg fails on any tracked path outside `{HARNESS_DIR}/AGENTS.md`, `{SPECS_DIR}/**`,
   `{KNOWLEDGE_DIR}/**`, and `{ITERATION_DIR}/<id>/specs/**` that is **not on the frozen
   six-path debt list recorded in `.mstar/AGENTS.md`** — so a *new* force-add fails
   immediately and the six may only shrink. Both halves are asserted, because otherwise
   "the ratchet works" and "the check is simply off" are indistinguishable: one negative
   control proves a new out-of-set path fails, and a second proves the six are tolerated.
   Removing those six from the index is **not** this iteration's work — plan B **D-5**
   carries it to the operator, since dropping two closed iterations' delivery record out of a
   clone is a boundary change, not a hygiene side effect.

## Verification

- The checker's own output over `.mstar/` (exit code + summary), captured in the
  completion report.
- The engine's own verdict on the corrected register:
  `MSTAR_HARNESS_DIR=.mstar mstar persist get --validate residuals --key _default` → exit 0,
  empty violation list. This is the acceptance test DoD 3 names, and it is the one check in
  this plan that the plan did not write itself.
- A negative control: temporarily inject one violation (e.g. add `execution_lease` to a
  `Done` row in a scratch copy), confirm the checker exits 1 and names it, then restore.
  The control is required — an absence assertion is evidence only if the fixture can reach
  the falsifier (`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md`).
- **A second negative control for the D11 tracked-set leg**: in a scratch fixture, force-add a
  path outside the published set and confirm the leg exits 1 naming that path. The falsifier is
  exactly the condition that produced the 11 (`git add -f` against `.mstar/**`), and without
  this control the leg is an assertion that cannot fail.

## Deferred

| # | Deferred | Why | Trigger / owner |
|---|----------|-----|-----------------|
| D-1 | The mtime-sensitive fallback lifecycle selection when the root register is empty | It is engine behaviour, not a document defect; this plan can only record it | roadmap row written by Task 3; owner PM, at the next harness-maintenance round |
| D-2 | Migrating the project register into `store.db` as the findings authority | The verbs do not exist on the installed build: `mstar store` / `mstar issue` / `mstar catalog` all exit 1 `unknown command` on 3.11.2, while the engine source registers them (`packages/cli/src/index.ts:6403-6410`). The migration is the engine's own stated direction, but it needs a build that ships it, and it moves the findings authority — out of this iteration's scope (compass Non-Goals) | When an installed build exposes the `store`/`issue` families; owner PM, at the next harness-maintenance round |

### Architect ruling (Phase 1 review 2026-09-28) — the register's write path

**Ruled: (c), refined — hand-maintenance through the CAS-guarded `persist` put, with the
engine's own validating read-back as the acceptance test.** Recorded as compass **D9** and Q2.
The route the plan actually takes is in Task 2's write-path step; this section records why, and
corrects the premises the gap text was written on.

**(b) migrate to `store.db` is not available.** `mstar store init` and `mstar issue add` both
exit 1 with `error: unknown command` on the installed CLI (`/usr/local/bin/mstar` →
`@mstar-harness/cli` 3.11.2). The engine **source** does register them
(`packages/cli/src/index.ts:6403-6410`, `registerIssueCommands` / `registerCatalogCommands` /
`registerStoreCommands`), so the published build is behind its own source — the migration path
exists in the codebase but not on this machine. It cannot be this iteration's write path.

**(a) freeze is rejected.** DoD 3 would stop claiming a live register in a document the engine
still reads, and `mstar status tech-debt` derives `total_open` from it. Freezing would make the
plan honest about a number it had just stopped maintaining, which is the opposite of the
iteration's purpose.

**(c) is accepted, and the reason the plan *looked* like it had no writer is a misreading worth
recording.** `mstar persist residuals` **is** a writable coordinated kind on this build —
`PERSIST_KINDS = ["status","snapshot","residuals","review","json"]`,
`COORDINATED_PERSIST_KINDS = ["status","snapshot","residuals"]`, gated by
`validateProjectRegister`. `grep -c "is the only findings authority"` over the installed
`dist/mstar-harness.js` returns **0**: the retirement text is not in this binary. What the PM
seat observed as "the write verbs refuse" is **the validator refusing an invalid document** —
`persist` validates before put, and the register currently fails with 144 violations. Confirmed
by the reproduction on a scratch harness (valid register, correct token) →
`persist residuals/_default: OK`, bytes landed. The consequence is the two-step sequence in
Task 2, not a bare hand-edit: **correct in place to break the chicken-and-egg, then land it
through the engine.** If a future build ever does retire the kind, the fallback is the direct
byte edit plus the same validating read-back — a documented procedure, which is what (c) means
— and the trigger for revisiting is **D-2**.

This plan is the **only** writer of `.mstar/projects/_default/residuals.json` in this
iteration, and it writes it exactly once. The compass carries the decision row (D9); nothing
here changes plan B's surface. Throughout this plan, **plan B** means
`20260928-workspace-reclamation`, the git/workspace plan.

## Engine lifecycle

- Scoped sequence: this plan row is advanced by the coordinator only, one engine verb per
  transition. Precondition: none (`blocked_by: []`).
