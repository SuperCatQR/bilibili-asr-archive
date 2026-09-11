# QC Consolidated — 20260911-subtitle-cli-cutover

- Iteration: `iter-2026-09-subtitle-transcript-sqlite` · Plan: `20260911-subtitle-cli-cutover` (final plan)
- Review range / Diff basis: `c5a9b82..8373817` (4 commits, 13 files, +4597/−574)
- Working branch (verified by all seats): `feature/20260911-subtitle-cli-cutover`, HEAD `8373817`, worktree clean
- Seats: `qc-specialist` (qc1.md), `qc-specialist-2` (qc2.md), `qc-specialist-3` (qc3.md)

## Seat verdicts

| Seat | Verdict | Critical | Warning | Suggestion | Unconfirmed |
|------|---------|----------|---------|------------|-------------|
| qc-specialist (qc1) | **Request Changes** | 0 | **1** | 2 | 0 |
| qc-specialist-2 (qc2) | Approve | 0 | 0 | 9 | 0 |
| qc-specialist-3 (qc3) | Approve | 0 | 0 | 6 | 0 |

All three seats verified the checkout/range independently; seat 3 additionally mapped the iteration compass's
**A1–A12** and found **none falsified** (A3/A4/A5's mapping/A10 are proven offline by design; A7 is strongest —
the live file set), and all three judged the live evidence's meaning consistently: the recorded line is
test-composed (the house pattern) but every field derives from the shipped CLI's stdout or the rows it wrote,
each with an assertion that would fail if the fact were absent; the **three-invocation ledger is complete and
honest** as far as a read-only seat can judge.

## Gate decision: Request Changes → one merged fix wave, then targeted re-review

### The Warning

| ID | Finding | Disposition |
|----|---------|-------------|
| **F-001** (qc1, High confidence) | A blank/whitespace/control-character `--bvid` is reported as `<command>: unexpected error` with **exit 2**, where the spec and three shipped doc sentences promise `unknown --bvid <value>` with **exit 1**. Trace: `cli.py:584-600` swallows `parse_work_id`'s `ValueError` → `("", None)`; the guard passes because `bvid is not None`; the storage layer rejects the empty identifier; both handlers' broad `except Exception` map it to exit 2. Trigger: `probe-subs --bvid "$BVID"` with `BVID` unset. The ten-case usage parametrization does not cover it, which is why it is not pinned red | **Fix now** — validate the selector (or map the `ValueError` to the fixed `unknown --bvid` line) **and** add the case to the usage parametrization; verify with `probe-subs --bvid ""` at runtime |

### Suggestions (deduped across seats) — all folded into the same wave

**Product/behaviour-adjacent:**
- **QC2-001** (coverage): no test places a **failed part before a later success** in one bounded run, so a
  loop-early-abort regression would escape → add the ordering case.
- **QC2-002** (bounded-ladder escape, implausible trigger): a pathological upstream `to` (>1e9 s) trips the
  storage ceiling, whose `ValueError` escapes the per-part outcome ladder and aborts the whole run → handle the
  storage validation error per part as a bounded `failed` outcome.
- **QC2-003**: the probe does not literally open a **read-only** connection (`open_database` runs both
  idempotent schema scripts and commits) although every tested observable holds → open the probe connection
  read-only.
- **F-003** (qc1, defence in depth): `SubtitleTrack.label` (`lan_doc`) is printed verbatim while the gateway DTO's
  `_text` does not reject `\x00`/`\r`/`\n` (unlike its storage twin) → reject at the DTO with the bounded
  `shape_error` so a malformed label cannot split the locked one-line-per-track shape.
- **QC2-009 / Q3-03** (QA-facing hazard): the live line prints `with_tracks`/`stored`/`run_id` without
  assertions tying them to their source, and a **forgotten credential reads as a skip, not a failure** → assert
  the fields and make a missing credential loud when a live run was intended.

**Documentation precision:**
- **QC2-004 / Q3-02**: the probe's stdout is the only surface printing upstream free text (`lan_doc`) and is
  never sentinel-scanned, while `docs/metadata-storage.md:153` promises "no … upstream message text" → scan the
  probe output and scope the sentence.
- **Q3-01**: `_family_rank` collapses every non-`zh`/`en` family to rank 2, so CC-before-AI decides *across*
  distinct rest-families while the prose says "inside the same family" (the code matches the locked spec key) →
  add one docs clause **and** a pinning test for the corner.
- **Q3-04 / Task-3 Minor 3**: the docs' quoted live line omits the `run_id=` the code prints.
- **Q3-05**: `harvest-subs` takes the writer lock **before** the DB check, so a failed/mistyped harvest still
  creates `<root>/coordinator/`; the rebuild step omits the default 10-page `fetch-meta` bound; the README
  Workflow block places `harvest-subs` above `download-audio --missing-subs` with no ⚠️6 pointer.
- **F-002** (qc1): `docs/metadata-storage.md:243-244` shows the rebuild line wrapped over two lines where the
  command prints one; also state that it goes to stderr.

**Recorded, not code (PM-owned):**
- **QC2-005**: the run row does not persist the `--language` preference (a schema column decision for a storage
  owner) → recorded in the plan's durable roadmap.
- **Q3-06**: the "retiring `bili_client` subtitle methods" deferral and nit M2 need an owner/trigger → PM adds
  them to the plan text.
- The **three-invocation live deviation** stays a durable note (plan summary + this consolidation + the
  iteration close), never a `residuals.json` entry: the register is the finding/severity SSOT and this deviation
  has no defect and no closure condition. The one machine-trackable residue is QC2-009/Q3-03's slow-fail, which
  the fix wave closes.

## Residuals

`R1` (plan 1, `low`, `defer`) remains the only register entry and stays correct — this range touches no
`sources/` file. This plan registers no residual of its own.

## ⚠️ Hand-off to the mandatory QA gate (L4)

1. Reproduce the offline suite at HEAD (implementer-reported `1279 passed, 4 skipped`; every QC seat is
   read-only and none re-ran it) and re-take the **bounded live smoke**; if a re-taken run stores nothing,
   require `sessdata=present` before accepting it as a bounded upstream observation.
2. Re-verify F-001's fix at runtime (`probe-subs --bvid ""` → the `unknown --bvid` line, exit 1) and the
   pre-iteration-database case (`tests/test_subtitle_cli.py:1047-1074`).
3. Do not normalize the one-run live budget for later plans — the deviation is recorded, not absorbed.

## FINAL GATE DECISION (after the N=3 targeted re-review of fix wave `8373817..7e57eb6`)

**Approve** — Critical 0 · Warning 0 · open Suggestions 0 · Unconfirmed 0 · this plan registers no residual
(the register still holds only plan 1's `R1`, correctly open and retargeted).

| Seat | Initial | After revalidation |
|------|---------|--------------------|
| qc-specialist (qc1) | Request Changes (1 Warning: F-001) | **Approve** — F-001 closed at the taxonomy level (guard before the DB open, predicate mirroring the storage rule byte-for-byte, byte-exact `unknown --bvid` line + exit 1, 15 usage cases + a 7-value × 2-command case, runtime reproduced by the seat itself); F-002/F-003 closed; the F-003 **audit finding confirmed** (caption bodies keep interior control characters, labels reject them; the split's removal fails the new regression test) |
| qc-specialist-2 (qc2) | Approve (9 Suggestions) | **Approve** — five closed as specified (QC2-001 failure-first ordering; QC2-002 per-part ceiling bound with the corrected pre-transaction comment; QC2-003 `mode=ro` with a write-proof test; QC2-004 probe-stdout scan + docs scoping; QC2-009 asserted counts/`run_id` + a loud opted-in credential gate), four dispositioned by record; regression lens classified all 92 deleted lines with no assertion weakened (test arithmetic +16 corroborates) |
| qc-specialist-3 (qc3) | Approve (6 Suggestions) | **Approve** — Q3-01/02/03/04/05 closed and verified (the Q3-01 pin is genuinely discriminating: the old prose's reading fails it); **Q3-06 closed by the PM** after the seat flagged the legacy-retirement bullet as the one item still lacking owner/trigger. The seat's **A1–A12 re-check**: no criterion falsified, A7 and A8 now *strengthened*, A9's precision flag lifted, A12 clean |

### What the fix wave produced

A merged wave (`7e57eb6`, 9 files, +899/−92) closing the one Warning and the eleven Suggestions, whose
**audit also caught a real regression in an interrupted run's WIP**: sharing F-003's strict helper would have
rejected interior control characters in caption body text, so a two-line cue would have ended a whole harvest
(now split: captions keep them, operator-facing labels reject them, with a regression test).

### Open items carried out of this plan (all recorded with owner/trigger, none blocking)

`QC2-005` (the run row does not persist the `--language` preference), the two new
`unreadable archive database` branches (untested/undocumented; the QA gate exercises them at runtime), the
`unknown --bvid` raw-echo nit, the `_archive_files` empty-directory blindness, the private cross-module test
import, and the seam follow-up decision (a package-seam subtitle E2E is a larger future task).

### ⚠️ Hand-off to the mandatory QA gate (L4)

1. Reproduce the full offline suite at `7e57eb6` (implementer-reported **1311 passed, 4 skipped**) — no seat
   re-ran it.
2. Re-take the **bounded live smoke** (opt-in) and record `part_source` + `sessdata`; the credential gate now
   **fails loudly** when opted in without a resolvable credential, so a silent skip can no longer pass as
   evidence.
3. Exercise the two `unreadable archive database` branches at runtime (the seat-1 observation).
4. Confirm the DoD/acceptance boxes map to evidence and that the iteration-level A1–A12 remain satisfied at
   the merged revision.
5. Keep the three-invocation live deviation recorded (not normalized) — it belongs in the iteration close's
   durable summary.
