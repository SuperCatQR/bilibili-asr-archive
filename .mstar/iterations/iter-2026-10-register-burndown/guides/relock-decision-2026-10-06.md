# Re-lock decision — 2026-10-06T11:0x, operator ruling "重新锁定，从 104 行里开新批次"

> Supersedes `relock-after-pr214.md` §5's open question. That file remains as the evidence record; this one
> records the ruling and the measured facts that shaped it.

## 1. The candidate pool was re-screened, and it is much narrower than the raw count suggests

`relock-after-pr214.md` proposed C1/C2/C3 = 14 rows from the 104. That count was **wrong**, and checking it
against the rows' own acceptance text is what showed it. Of the 104 open non-declared rows:

| Acceptance shape | Count | Meaning |
|---|---|---|
| Bare token `defer` (or `accept`) | **76** | A **conditional** deferral. The real decision lives in `occurrences.evidence_json` and every one carries a `target` of the form *"the next plan that touches X"* / *"next metadata iteration"* / *"a plan that owns Y end to end"*. **These are not unconditionally actionable** — several name vehicles that closed long ago (e.g. `I-000078`/`I-000079`/`I-000085` point at `iter-2026-09-ops-readiness`, which has shipped). Pulling them into a batch would be manufacturing scope the register explicitly parked. |
| Real, unconditional acceptance | **28** | Individually actionable. This is the honest candidate pool. |

This is the same trap seat 1 caught for `I-000041`: **a bare token is not the decision; the occurrence payload
is.** 76/104 of the remainder is parked work.

## 2. The 28 actionable rows, verified at `a508d34`

Already **satisfied on `main`** by #214 or by earlier work — they need *closure*, not a plan:

| Row | Evidence |
|---|---|
| `I-000173` `set_pacing_floor` has no caller | the function is gone; only tombstone comments remain (`bilibili_api_gateway.py:773`, `test_bilibili_api_gateway.py:1538`) — **stale row** |
| `I-000179` inline terminal-status sets | `cli/run.py:48` now reads `VALID_STATUSES - TERMINAL_STATUSES` — **stale row** |
| `I-000209` no CI | `.github/workflows/ci.yml` exists, runs, and is **green** (this session) — **stale row** |
| `I-000185` no evidence sidecars | `coverage_report.py` reads/writes validated sidecars; `verification-results/` exists — **needs a re-check, likely stale** |

Still genuinely open and independently actionable (**24**):

| Cluster | Rows | Character |
|---|---|---|
| **N1 — store-route expressiveness** | `I-000156`, `I-000159`, `I-000161`, `I-000068`† | the store route cannot express a row the scheduler/fixtures need |
| **N2 — pipeline & write-back truth** | `I-000126`, `I-000153`, `I-000150`, `I-000148`, `I-000157` | queue/source and write-back contract gaps |
| **N3 — evidence & verification lane** | `I-000172`, `I-000177`, `I-000163`, `I-000211`, `I-000146` | what the checks can witness; docs that must name the pair |
| **N4 — schema & docs truth** | `I-000042`†, `I-000044`†, `I-000123`†, `I-000169`, `I-000181`, `I-000162` | unreachable states, unreported degradation, duplicated config, stale README |
| **N5 — proofread & misc defects** | `I-000189`, `I-000160`, `I-000212`, `I-000208` | real code defects with pinned tests |

† carries a conditional defer but its acceptance is concrete; **re-check the condition before including it**
— if the named vehicle has shipped, the row is actionable; if not, it stays parked.

## 3. Why "re-lock from the 104" is done by registering a **new** iteration id

The lifecycle `iter-2026-10-register-burndown` is `running` and holds three `Todo` plan rows whose subjects
#214 has satisfied. Two routes to retire it were measured and **both are refused on this harness**:

- `mstar workflow lifecycle --status stopped` → `command.invalid-input: active workflow transition requires
  workflow, main session identity, sessionRef, full expect token and operation`. That is the **active-DB**
  form; the store's **execution authority is `legacy`** (`execution_meta.authority_state = 'legacy'`), so no
  sessionRef exists to supply.
- `mstar status workflow-close` (the file route) is additionally wrong for this case: it *composes* each
  owed row's completion (`closeFileWorkflow` → `closeOwesRow` → `commitCloseRow`), i.e. it would write
  fabricated `coordination` records onto rows whose work was done by PR #214, not by this iteration. Not
  acceptable — that is the falsification `D10` forbids.

So the retirement route is **`mstar iteration register` with a new id** (create-only; it appends a root
entry and never modifies the old one) plus a recorded disposition here. The old lifecycle stays in
`status.json` as a **third** active entry — the wedged audit lifecycle is already a second, and §2.0's
`unbound-multi-active` refusal is avoided the same way it has been all iteration: **always address lifecycle
commands with an explicit `--workflow <id>` or a session envelope that names it.**

## 4. What the new iteration is

- **id**: `iter-2026-10-register-batch2` (naming checked against the repo's `iter-<YYYY>-<MM>-<slug>` precedent)
- **scale**: `L` (3–4 business plans) — the operator's "至少修复20个" cannot be met by `M`'s 2–3 plans over
  24 candidate rows spread across five clusters, and `L` stays inside the documented cap.
- **declared rows**: the 24 actionable rows above, minus any found already-satisfied at dispatch time.
- **residual deliverable carried over**: the 20 rows #214 satisfied are closed in the store by the *previous*
  iteration's closure work (no plan needed — it is a closure campaign, not a fix campaign).

## 5. STOP / honest-reporting conditions

- If, at dispatch time, more than half of the 24 turn out already satisfied, **STOP and re-lock again**
  rather than padding the count — the ≥20 target would again be unreachable and the operator must know.
- No row is closed by waiving, duplicating or superseding it to reach a number.
- Every closure cites the fixing commit and a red→green witness; rows satisfied by #214 cite **its** commits
  (`00a4356`…`88dbea3`, `f8d795f`, `dc1e78e`), never a commit this iteration did not author.
