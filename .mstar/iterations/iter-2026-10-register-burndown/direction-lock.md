# Direction lock — iter-2026-10-register-burndown

> **Autonomous route record.** Written by the `/iteration-loop` coordinator at lock time, **before** the
> `direction-lock` anchor and before the compass draft. Mode: `Direction lock mode: autonomous` (declared by
> the command). Locked 2026-10-05 against `c59a1e6` (`main`). This file stays in the package as the durable
> lock-time record.

## 1. Locked direction

**One sentence.** Working from the open issue register left by the 2026-10-04 adjudication, run a
three-batch defect burndown that **closes at least 20 open product-defect rows by fixing their subject in
code**, starting with the two largest single-root clusters (the ASR run-record family and the
write-back/manifest durability family) plus the verification-lane rows the same fixes must exercise.

**Why this and not a re-audit.** The register was adjudicated four days ago: 56 transitions were applied
(44 `resolved`, 7 `duplicate`, 4 `waived`, 1 `superseded`; `.mstar/plans/audit-2026-10-04/README.md` §
"Applied — 2026-10-04"), and 125 rows were left `open` **because they are genuinely open** — the audit's
own per-row evidence quotes HEAD line numbers that still hold at `c59a1e6` (spot-checked below). What the
register has never had is a campaign that *fixes* those rows in bulk; the 2026-10 history is
one-audit-at-a-time. The user instruction is exactly that: *"评估项目issue，一批一批修复，至少修复20个"*.

## 2. Rationale (repo evidence, not preference)

| Rank source | Evidence | Effect on the lock |
|---|---|---|
| **Deferred / roadmap next** | `{ITERATION_DIR}/next-direction-candidates-2026-10-03.md` § A defers the E2E family (`I-000182`/`183`/`184`) into `iter-2026-10-ledger-integrity`; that iteration **closed** 2026-10-03 and all three rows are **still `open`** at `c59a1e6` (`disposition=open`, `closed_at=NULL`, measured). | The A-family is live, unrepaired, already once deferred → **highest rank**. |
| **Cross-cutting roadmap prerequisite** | `bilibili-asr-archive/docs/roadmap.md` § "cross-cutting 前置" names `I-000190`/`I-000207`/`I-000195` — the engine's shared-register lost-update family, **not product defects**. | Recorded as non-goal: this iteration cannot fix engine code; the roadmap already tracks it. |
| **Product completeness** | Three clusters own 21 of the 125 open rows: ASR run-record integrity (10), write-back + manifest durability (6), verification-lane + evidence rules (5). | Cluster-first is what makes "≥20" reachable without 20 unrelated one-file fixes. |
| **Risk / blast radius** | All target rows sit in `services/queue_source.py`, `cli/asr.py`, `coordinator.py`, `manifest.py`, `services/subtitle_ingest.py`, `storage/schema-transcripts.sql`, `tests/`, `scripts/`. No target fix needs a schema **migration** (asserted per plan; the one schema-adjacent row, `I-000210`, changes a view predicate, which is rebuildable). | Feasible slice; the plan count is driven by coherence, not by depth. |

### Which rows, exactly (21 targeted, ≥20 required)

All are `open` at `c59a1e6` — verified in `{HARNESS_DIR}/store.db`.

- **B1 `asr-run-record-integrity`** (10): `I-000182`, `I-000183`, `I-000184`, `I-000197`, `I-000198`,
  `I-000199`, `I-000180`, `I-000171`, `I-000176`, `I-000194`
- **B2 `archive-writeback-durability`** (6): `I-000191`, `I-000192`, `I-000193`, `I-000196`,
  `I-000202`, `I-000203`
- **B3 `verification-lane-contract`** (5): `I-000168`, `I-000174`, `I-000175`, `I-000210`, `I-000211`

The audit's claims were **re-verified against HEAD** during this lock (four days is enough for drift):
`grep -rn finish_acquisition_run src/` returns only `subtitle_ingest.py:359/:384` (so `I-000182` holds);
`queue_source.py:166-168` still mints `selector_kind="pending"` (so `I-000183` holds);
`cli/asr.py:289` still computes `(provenance or {}).get("language") or "und"` (so `I-000184` holds);
`manifest.py:288` still decodes with `errors='replace'` (so `I-000196` holds); `tests/conftest.py:209-225`'s
`opt_in_gate` still returns without skipping (so `I-000168` holds). A row whose claim turns out false at
HEAD is closed as already-fixed with that evidence and **does not count** toward the 20.

## 3. Acceptance criteria (iteration-level Done)

1. **Count**: ≥ 20 of the 21 rows above carry `disposition = resolved` in `{HARNESS_DIR}/store.db`, closed
   through the engine's own privileged verbs, with closure evidence naming the fixing commit. Closures by
   re-adjudication (`waived`/`duplicate`/`superseded`) are reported separately and **do not count**.
2. **Witness**: every closed row has at least one witness that is **red before the fix and green after**
   (a test, or a named scoped check for a non-executable claim such as a docstring or a spec sentence), and
   that witness is recorded in its plan's durable review-gate summary.
3. **No regressions**: each plan runs its own module suites; the pre-existing failure baseline is
   **measured and recorded**, never asserted.
4. **Honest remainder**: every targeted row not closed is listed in compass `## Roadmap Position` with the
   measured reason (blocked / already-fixed / needs a product decision) and an owner. No silent stale `open`.
5. **No schema migration**: no target fix requires in-place DDL. A fix that would need one is STOPped and
   re-scoped, not migrated.
6. **Register truth**: after close, `mstar status tech-debt` reflects the drop, and each unclosed row carries
   an occurrence/comment recording why.

## 4. Non-goals (explicit exclusions, each with its reason)

- **`I-000215` + the wedged `20261004-issue-register-audit` lifecycle** — harness/engine defect on
  `@mstar-harness` 3.11.2, already ruled by the operator as a *named blocker for its owner* (lifecycle
  contract §5). The row stays open as the record; the wedge is not repaired, and nothing in this iteration
  depends on it (every command this iteration runs names its workflow explicitly).
- **`I-000190` / `I-000207` / `I-000195`** — engine shared-register lost-update family. Not product code.
  Tracked by the roadmap's cross-cutting prerequisite; owner = engine upstream.
- **`I-000136` / `I-000135`** — dependency-closure / stale-`uv.lock`. Regenerating the lock on this project
  silently pulls a PyPI CUDA torch onto the one host every GPU result comes from; stays a documented
  operator procedure.
- **`I-000041`** (high) — its own `acceptance` field in the store reads `defer`: an explicit, already-recorded
  operator deferral, not an unassessed row. Left open, not counted.
- **`I-000209`** (no CI) — standing up CI is a host/repo operation, not a fix to a defect subject.
- **`I-000189`** (proofread-merge block accounting) — coherent on its own but in a module no other target
  plan touches; deferred to `## Roadmap Position` rather than padding B2 with an unrelated file.
- **Greenfield feasibility** (new processors, corpus expansion, layout migration) — out; this iteration fixes
  existing subjects only.

## 5. Scale budget

The command was invoked **without a scale token** → the documented default applies: **`M` = 2–3 business
plans**. **3 business plans are registered** (B1, B2, B3) — the cap, not a padded list.

Only business plans are counted. The harness work this iteration necessarily performs — the §1.6 Review &
Edit chain, per-plan QC, QA gates, `compound`, `iteration-close`, PR, merge-ready, post-merge close — is
mandatory process: it consumes **no** slot and no process-only plan is registered to absorb one.

**Overflow rule**: targeted rows that cannot be closed inside these three plans (or rows assessed and
deferred) go to compass `## Roadmap Position` with reason + owner + trigger. The budget is not expanded
mid-flight, and rows are not invented to fill it.

## 6. Branch policy (autonomous resolve)

Resolution order per `autonomous-direction-lock.md`: workflow snapshot anchors → prior iteration compass
frontmatter → current branch **only if** it is a documented delivery/policy branch → STOP.

| Step | Evidence | Result |
|---|---|---|
| Workflow snapshot `branch` anchors | does not exist yet (registration is §1.5) | — |
| Prior iteration compass frontmatter | `{ITERATION_DIR}/iter-2026-10-ledger-integrity/delivery-compass.md` → `iteration_base_branch: main`, `target_branch: main`; same pair in `iter-2026-10-asr-success-attestable` | **hit** |
| Repo policy | `AGENTS.md` § Branch policy: *"Default integration / PR target: `main`; Feature work: plan branches merging into `iteration/<iteration-id>`"* | **confirms** |

- `iteration_base_branch` = **`main`**
- `spec_integration_branch` = **`iteration/iter-2026-10-register-burndown`**
- `target_branch` = **`main`**
- Main worktree (control root) residency observed at lock: **`main`** (`c59a1e6`) — recorded, never switched.

## 7. Stop check before the anchor

- Credible candidate with file/status evidence: **yes** (register rows + audit verdicts + HEAD re-verification).
- Branch metadata resolvable without defaulting to a bare `main`: **yes** (§6).
- User direction argument present: **yes** ("评估项目issue，一批一批修复，至少修复20个") → no STOP.
