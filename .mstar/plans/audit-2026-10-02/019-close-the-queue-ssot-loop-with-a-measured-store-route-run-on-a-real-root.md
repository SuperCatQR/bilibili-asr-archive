# Plan 019 — Close the queue-SSOT loop with a measured store-route run

## Status
- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Confidence**: MED
- **Fingerprint**: audit-2026-10-02r2/09-measured-store-route-run
- **Depends on**: plans/017-*.md
- **Category**: direction
- **Evidence**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py:300,329` (write-back entry points, landed); live root `/srv/bili-asr-archive` (read-only counts below)
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issue**: `I-000181`

## Problem

The store route and the R14 transcript write-back have **landed on `main`**, but the repository has
never measured a store-route run end to end. Every performance and convergence claim about the queue
path is therefore analytic:

- the ledger/runtime cost of a corpus-scale derivation (README's own text says so: "an analytic bound
  only: no runtime measurement was taken on a real archive");
- whether `v_missing_transcript` actually **drains** when the write-back runs through the real guard
  (`cli/asr.py:284-296`);
- whether the gap views agree with each other after a real run.

Verified on this checkout: `11374d1` and `aee6f2e` are both ancestors of `main`, and the write-back
entry points are present at `queue_source.py:300` (`record_local_transcript`) and `:329`
(`record_transcript`). Meanwhile the published contract still tells the operator the chain is
manifest-driven (plan 017 fixes that).

Live-root evidence, read read-only from `/srv/bili-asr-archive` (2026-10-02):

| surface | count |
|---|---|
| `videos` | 30 |
| `video_parts` | 33 |
| `transcripts` | 1 |
| `v_missing_transcript` | 0 |
| `v_pending_subtitles` | 32 |

Read carefully: 30 videos against a documented ~1730-row corpus, one transcript, and a
`v_missing_transcript` of **0** — a converged view on a root that is nearly empty. That is exactly the
shape that can mislead: the convergence claim is unmeasured on a root with work in it.

**Why this is a direction plan and not a bug:** nothing here is proven broken. What is missing is the
*evidence* that would let the operator either close the queue-SSOT question or find the next defect —
and the repo's own `{KNOWLEDGE_DIR}` repeatedly records that a claim is only as good as its evidence
pointer (`best-practices/completion-claims-need-live-evidence.md`,
`best-practices/premise-freshness-before-lock.md`).

## Current state (excerpts — verify against live code before running anything)

`bilibili-asr-archive/src/bili_asr/services/queue_source.py:300` (the write-back home):

```python
def mark_audio_acquired(
```

— and `:329`:

```python
def record_local_transcript(
```

The guard any measurement must exercise — `bilibili-asr-archive/src/bili_asr/cli/asr.py:284-296`:

```python
                        page_index=int(entry.get("page_index") or 0),
```

(Plan 015 owns that line's correctness; this plan only observes the run.)

The convergence surface — `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql`
(`v_missing_transcript`).

## Conventions to follow

- The repo's measurement discipline (`{KNOWLEDGE_DIR}/testing-patterns/*`): state the premise the run
  would falsify **before** running it, record the exact commands, and publish no claim the probe did
  not read. A measurement that reports a count it did not query is the failure mode this plan exists
  to avoid.
- Verifying a real environment is explicitly **not** a development-AC obligation in this repo — so
  this plan must be scheduled as its own bounded run with an operator-available root, and must not be
  attached as a gate to any other plan.
- Costs are real: a GPU ASR run is expensive. Bound the run (a small `--limit`), and prefer a row
  whose audio is already archived so the measurement exercises the store path rather than the GPU.
- Never run against the operator's archive root destructively: the store is opened read-write by the
  run; take a copy of `archive.db` + `manifest/` first, or use an operator-designated scratch root.

## Tasks

### Task 1 — Pre-register the measurement (Effort: XS)

**Files**
- Create: `bilibili-asr-archive/verification-results/queue-ssot-run-<YYYY-MM-DD>.md`

**Change.** Before running anything, write down:
- the root under test and how it was prepared (copied? scratch?);
- the exact command(s) to be run, with the bound (`--limit`, `--queue-source store`);
- the counts to be read **before** and **after**, each with the SQL that produces it
  (`transcripts`, `v_missing_transcript`, `v_pending_subtitles`, `v_pending_metadata`, rows in
  `acquisition_runs` / `acquisition_attempts` for the run);
- the ledger sizes to be recorded (`manifest/manifest.jsonl`, `manifest/manifest.journal.jsonl`);
- the premise each number would falsify (e.g. "if `transcripts` does not increase by exactly the
  number of archived parts, the write-back guard is not firing");
- what would make the run **uninformative** (e.g. every selected row already holds a transcript).

### Task 2 — Run it bounded (Effort: M)

**Change.** Execute the pre-registered command against the prepared root. Capture stdout/stderr, the
exit code, and the wall time. Then read back the after-counts with the pre-registered SQL and record
both sets side by side in the same file.

If the run must touch the GPU host, that is an operator-coordinated act — record the environment
(host, device, engine version) rather than assuming it.

### Task 3 — Reconcile the claim (Effort: XS, same round)

**Change.** In the same file, state which of the pre-registered premises held and which did not, and
**re-scope the register rows the measurement settles** through the issue verbs (they are the SSOT):
- `I-000067` (ASR stage writes no transcripts row) — if the write-back fires and the view drains,
  record the closure rationale; if it does not, the measurement is the reproduction.
- `I-000181` (contract drift) — cross-reference plan 017.

Where the measurement contradicts a published claim, correct the claim in the same round (or hand it
to plan 017 if 017 is still in flight).

## STOP conditions

- **Before any run**: if no operator-designated root is available, STOP — do not run against
  `/srv/bili-asr-archive` in place. This plan is not a licence to write to a live archive.
- If the selected rows would all require GPU transcription (no archived audio), STOP and re-select:
  the point is the store path, not the ASR engine, and the run should stay cheap.
- If the after-counts cannot be read (store locked, schema predates the transcript tables), STOP and
  record the refusal — a rebuild line is itself a finding for the register.
- If a pre-registered number comes back **different from the mechanism's prediction**, STOP before
  "fixing" anything: that discrepancy is the deliverable. Report it.
- Never edit a published claim to match the measurement inside this plan without the evidence line —
  the measurement file is the evidence, and it must be committed with the claim change.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/services/queue_source.py bilibili-asr-archive/src/bili_asr/cli/asr.py
```

If either changed, re-read the guard before pre-registering the command.

## Done criteria

- [ ] The pre-registration file exists **before** the run and names every count with its SQL
- [ ] The run's exact command, exit code, stdout/stderr and wall time are recorded
- [ ] Before/after counts are recorded side by side, each with the query that produced it
- [ ] Each pre-registered premise is marked held / did-not-hold with the number that decided it
- [ ] The register rows the measurement settles are updated through the issue verbs (record the ids and the resulting status)
- [ ] Any contradicted published claim is corrected in the same round, citing this file
- [ ] `git diff --check` exits 0; `git status --short` shows no source file modified outside the claim corrections

## Verification notes

This plan's own evidence **is** the measurement file; there is no test to run. Do not add the run to
any other plan's gates, and do not claim convergence for a root whose counts were not read back.

If the operator declines the run, the honest outcome is that the convergence question stays open and
the file records the decline — not that it was verified.

## Engine lifecycle ownership

Deliverable is a committed measurement record (plus claim corrections). No workflow registration is
created by this plan; if the operator wants the run scheduled as an iteration scenario, PM registers
it per `mstar-iteration`.

**Boundary note:** this plan is a *development* plan whose task is a bounded measurement on a
prepared root; it does not create a `mstar-e2e` workflow, and its AC must not require a real-device or
deployed-environment receipt. If the operator wants real-environment E2E verification, that is a
separately requested `mstar-e2e` workflow, which PM orchestrates and `ops-engineer` executes.
