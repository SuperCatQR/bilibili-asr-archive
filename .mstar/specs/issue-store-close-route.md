# Spec: the issue-store close route — why a privileged mutation refuses, and the route that works

**Status:** active (ruled 2026-10-04, operator; carrier for `I-000186`)
**Primary consumers:** any session that wants to `close` / `triage` / `waive` an issue row; the audit reports
under `{PLAN_DIR}/audit-2026-10-*/`; the operator's manual-close procedure
**Change policy:** requirement changes require PM change-control, the same bar as the frozen specs.

## Problem

The issue store's privileged channel (`mstar issue close` / `triage` / `waive`) **refuses in practice on this
repository**, so 52 audit-verified rows could not be closed. This spec records the measured mechanism, the
**reachable route**, and the engine-side gap as a tracked todo — so that a later reader neither re-derives the
refusal nor reads an `open` row as an unfixed defect.

> **Corrected 2026-10-04 by the session that wrote it.** The first revision of this spec ruled route (M), a
> documented manual close, on the finding that all 39 snapshots were terminal and `execution_sessions` held 0
> rows. That finding is **true and is still the reason the channel refuses**, but the conclusion drawn from it
> was wrong: a terminal-workflow repository is not a dead end, because the engine can be asked to register a
> **new** lifecycle, and a registered lifecycle is `running`. The reachable route below was then proven
> end-to-end on a scratch harness (register → bind → close → `issue_transitions.imported = 0`). Route (M) is
> retained only as the fallback for a session that cannot register a lifecycle at all. The evidence log at the
> end of this file records both measurements, the failed one included.

## The four authorization gates, in order

`mstar issue close` walks four gates. Measured on the installed engine,
`/usr/lib/node_modules/@mstar-harness/cli/dist/mstar-harness.js` (v3.11.2); the function names and line
anchors below are that file's.

| # | Gate | Engine anchor | What it requires |
|---|---|---|---|
| 1 | `authorizeMutation` | `:25046` | Calls 2 → 3 → 4 and then checks the actor label matches the envelope's seat (`ENVELOPE_SEATS[session.role]`) |
| 2 | `readScopedSession` | `:25114` | A **session envelope file must be supplied**. With none, it throws `issue.scope-refused`: *"This mutation requires an existing scoped session envelope; no session credential is written to the store."* |
| 3 | `assertEngineIssuedSession` | `:25094` | The envelope must be engine-issued for **this** harness root, its `workflow_id` must resolve to a readable snapshot, and the workflow's own coordination/plan binding must name the same session id at the same recorded path |
| 4 | `liveSnapshotOf` / `planSessionBinding` | `:25069` / `:25085` | The snapshot must be **live** (`isTerminalSnapshot` at `:22866` must be false) and must carry exactly one plan row for the envelope's `plan_id` with a session binding |

`refuseAuthority` (`:25066`) is the refusal constructor every gate-3/4 failure routes through: *"A privileged
mutation is authorized only by the engine-issued session envelope of a live workflow (contract §4); a file
that merely parses as an envelope is not a credential."*

## The exact measured refusal

Gate 4 is where this repository stops. Measured refusal text, verbatim:

```
Workflow <id> is <status> — a finished lifecycle holds no live authority.
```

Produced at `:25080-25081`, inside `liveSnapshotOf`, when `isTerminalSnapshot(snapshot)` is true.
`WORKFLOW_TERMINAL_STATUSES` (`:22426`) is `["completed", "failed", "stopped"]`.

**The terminal-workflow condition.** Measured 2026-10-04 over `{HARNESS_DIR}/workflows/*/snapshot.json`:
**all 39 snapshots are terminal** — 36 `completed` and 3 `stopped` (`e2e-23191782-queue-ssot-chain`,
`e2e-23191782-season-7686105`, `iter-2026-09-queue-ssot-closeout`). There is no live workflow to bind an
envelope to.

**The 0-row session table.** Measured the same day against `{HARNESS_DIR}/store.db`:
`SELECT COUNT(*) FROM execution_sessions` → **0**. No engine-issued envelope exists on disk either, so no
envelope can even reach gates 3–4.

Consequence, stated precisely: **the refusal is a property of the harness's current state, not of any
particular row.** It is not evidence that a row is unclosable in principle — only that no envelope can
currently authorize a privileged mutation.

## The reachable route (proven 2026-10-04)

Gate 4 refuses a **terminal** workflow. It does not refuse a *newly registered* one — and the engine will
register a lifecycle on request. The route is therefore: give the register work a lifecycle to live in.

```bash
H=/root/workspace/bilibili-asr-archive/.mstar

# 1. Register a standalone plan workflow.  The plan document must be
#    {PLAN_DIR}/<plan-id>.md and must declare `plan_id:` in its frontmatter.
mstar workflow register \
  --workflow 20261004-issue-register-audit \
  --plan-id  audit-2026-10-04 \
  --plan-title "Issue Register Audit — 2026-10-04" \
  --plan-file  $H/plans/audit-2026-10-04.md \
  --delivery-kind verification/report-only \
  --completion-policy "the audit report records every verdict with its evidence" \
  --branch-source main --branch-target main --project _default \
  --harness $H
# → {"status":"ok","code":"workflow.register.ok"} and the snapshot is `status: running`

# 2. Bind the coordinator seat.  The engine WRITES the envelope (createSessionEnvelope,
#    flag "wx"); nothing here is hand-authored.  --session-id supplies the identity that
#    the engine would otherwise take from a host session.
mstar plan bind --coordinator --workflow 20261004-issue-register-audit \
  --session-id audit-2026-10-04-s1 --harness $H
# → {"status":"ok","code":"plan.bind.ok"} and
#   $H/workflows/20261004-issue-register-audit/sessions/coordinator-audit-2026-10-04-s1.json

# 3. Close a row through the ordinary privileged verb.
mstar issue close --id I-000013 --disposition resolved --actor project-manager \
  --session $H/workflows/20261004-issue-register-audit/sessions/coordinator-audit-2026-10-04-s1.json \
  --operation-id <unique-per-call> --expect <the row's `revision`> \
  --payload '{"reason":"…","references":["…"],"alignmentRef":"…"}' --harness $H
# → {"status":"ok","code":"issue.close.ok","data":{"revision":2,"storeRevision":105,"created":false}}
```

Measured on the scratch harness `/root/tmp-work/scratch/gitprobe`, 2026-10-04: step 3 returned
`issue.close.ok` for `I-000013`, the row flipped to `disposition='resolved'`, and an `issue_transitions`
row was written with `imported = 0` — i.e. a **live** closure, not the `imported = 1` shape the legacy
history carries. The store revision advanced.

Three properties of this route matter:

- **The envelope is engine-issued.** `bindCoordinatorSession` calls the engine's own `createSessionEnvelope`
  and records the resulting path in the snapshot's `coordination.coordinator`. A hand-written envelope is
  explicitly **not** a credential — the engine says so itself (`refuseAuthority`: *"a file that merely parses
  as an envelope is not a credential"*). Nothing in this route edits an envelope or the store directly.
- **The workflow must stay running while the closures are applied.** Closing it is a separate ceremony
  (§ below), and once closed its authority is gone.
- **The plan document is the registration authority.** `workflow.register` cross-checks the supplied
  `--plan-title` against the document and refuses a mismatch; the file must sit at `{PLAN_DIR}/<plan-id>.md`
  and declare `plan_id:`. A subdirectory (`plans/<id>/README.md`) is **refused** by `resolvePlanDir`'s
  pointer rule — the audit report at `{PLAN_DIR}/audit-2026-10-04/README.md` is not itself a registrable plan.

### If no lifecycle can be registered

Register the lifecycle that owns the work rather than bypassing the gate. A session that genuinely cannot
register one (no Git process root, no harness write access) falls back to route (M). Route (M) is a
documented procedure, not an improvisation, and produces the same artifact shape as the engine path.

## Route (M) — the fallback, retained

| Route | What it requires | Owner |
|---|---|---|
| **(E) Engine provides a reachable route for out-of-plan findings** | **Superseded**: the engine already has one — register a lifecycle, bind its coordinator, close. See above. No engine change is needed for the closure path itself | Engine (`@mstar-harness/cli`), **not repo code** |
| **(M) Documented manual closure** | Fallback only, for a session that cannot register a lifecycle: the closure payload is authored, evidenced and recorded in the repo, and applied once a live lifecycle exists | Operator + PM |

## Ruling (2026-10-04, corrected)

**Route (E) via a registered lifecycle is the intended route.** The audit's verified-stale rows are closable
through the engine's own verbs; no by-hand mutation is required or sanctioned.

Route (M) is retained as a **fallback** for a session that cannot register a lifecycle at all. Its scope stays
as narrow as it was: it covers out-of-plan findings — rows belonging to no live plan — and it produces a
recorded payload, never a hand-edited store. Rows that belong to a live plan remain that plan session's to
close through the normal channel.

The worked example is
**`.mstar/sdd/caption-exhaustion-attestation/I-000187-closure.md`** — a fully evidenced closure payload staged
ready-to-apply, written when `I-000187`'s fix merged while the channel refused. Read it as the template. Its
required parts:

- **The refusal, quoted.** The section opens by naming `issue.scope-refused` and stating that the row's `open`
  state is a channel failure, not an unfixed defect.
- **Disposition** — one of `resolved` / `waived` / `duplicate`, with the reason.
- **Acceptance evidence table** — one row per reference: the PR, the squash merge commit on `main`, the source
  files, the test names, the review artifacts. Every claim resolvable by a reader.
- **Verification numbers** — the suites run, with counts (e.g. "211 passed / 1 skipped").
- **Alignment** — the compass decisions the closure rests on (e.g. D10/D11).
- **Residuals this closure does NOT cover**, registered separately.

## Consequence a reader must carry

**A row with disposition `open` may already be closed in fact, and this store cannot say so.** When a closure
record exists for a row, read the record before reading the row's state. The honest description of a
verified-stale row whose closure has not yet been applied is "closure recorded at `<path>`; the store's row is
a channel artifact", never "still open, needs fixing".

This is the failure mode `{PLAN_DIR}/audit-2026-10-04/README.md` opens with. Its verdicts are *recommendations*
until applied — but the obstacle is now only that the applying session must have a live lifecycle registered,
not that the channel is unreachable. Prefer applying them through the route above; treat a row as
"unfixed product work" only after checking whether a closure record exists for it.

## Engine-side todo (tracked here, not as a new issue row)

Registered in this section rather than as an issue row **because the register is the thing the gap concerns, and
a new row would need the same channel**. The gap, one paragraph — note it is now narrowed: it is a
**convenience** gap, not a blocker.

> `liveSnapshotOf` (`mstar-harness.js:25080`) refuses every envelope whose workflow snapshot is terminal
> (`completed`/`failed`/`stopped`). A repository between iterations is normally all-terminal, so closing a
> strap of register-hygiene rows requires first registering a lifecycle to hold the authority — extra ceremony
> that leaves a `running` workflow to be closed afterwards. The convenient repair is a maintenance route for
> register-only mutations (`issue close`/`triage`/`waive`) that proves the same engine-issued-envelope property
> without requiring a *live* workflow. It belongs **upstream** in `@mstar-harness/cli`; it is not repo code and
> is not attempted here. It does **not** gate the audit's closures.

## Evidence log

| Check | Command / path | Result (2026-10-04) |
|---|---|---|
| Gate source | `/usr/lib/node_modules/@mstar-harness/cli/dist/mstar-harness.js:25046,25066,25069,25085,25094,25114` | the four gates and `refuseAuthority`, as tabled above |
| Terminal definition | same file `:22866` (+ `:22426`) | `["completed","failed","stopped"]` |
| Terminal snapshots | `{HARNESS_DIR}/workflows/*/snapshot.json` | 39 total: 36 `completed`, 3 `stopped` — measured in the **real** harness |
| Session rows | `{HARNESS_DIR}/store.db` → `SELECT COUNT(*) FROM execution_sessions` | 0 — measured in the **real** harness |
| Worked example | `{SDD_DIR}/caption-exhaustion-attestation/I-000187-closure.md` | full closure payload, staged (route M shape) |
| Upstream version | `mstar` engine status | v3.11.2 |

### The falsifying measurement (route E)

The three rows above describe the *refusal*. This one describes the *route past it*, and it is the reason the
first revision of this file was wrong. Run on a **scratch** harness (`/root/tmp-work/scratch/gitprobe`), so the
real register was never at risk:

| Step | Command (abbreviated) | Observed result |
|---|---|---|
| Register | `mstar iteration register` / `mstar workflow register … --delivery-kind verification/report-only --completion-policy …` | `workflow.register.ok`; snapshot `status: running` |
| Bind | `mstar plan bind --coordinator --workflow <id> --session-id <sid>` | `plan.bind.ok`; envelope written by `createSessionEnvelope` |
| Close | `mstar issue close --id I-000013 --disposition resolved … --expect 1` | `issue.close.ok` → `{"revision":2,"storeRevision":105,"created":false}` |
| Read back | `select disposition, closed_at from issues where id='I-000013'` | `resolved`, `2026-10-04T05:55:23.657Z` |
| Transition | `select imported from issue_transitions where issue_id='I-000013'` | **`imported = 0`** — a live closure, not legacy history |
| Endgame | `mstar status workflow-close --workflow <id> --outcome stopped` | not reachable: the CLI exposes no `--outcome`; close composes the row's completion first, so a closure lifecycle must be taken to a recorded completion before it can be closed |

Two further engine facts measured while establishing the route, both load-bearing for a session that repeats it:

- `plan bind --coordinator` with **no** session identity returns exit 2 `command.invalid-input` — *"coordinator
  bind requires runtime session identity"*. The engine's own `--session-id` option supplies it
  (`context: "sessionId"`), which is what makes the route reachable from a plain CLI invocation.
- `workflow.register` refuses a `--plan-title` that disagrees with the plan document (`derivePlanRegistration`),
  and refuses a plan file that is not `{PLAN_DIR}/<plan-id>.md`. A mismatched title is a constraint against the
  document, never an override.
