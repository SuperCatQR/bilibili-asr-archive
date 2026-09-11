# QC Consolidated — 20260825-run-coordinator-offline

- **plan_id**: `20260825-run-coordinator-offline`
- **Working branch**: `plan/20260825-run-coordinator-offline`
- **Review range / Diff basis**: `5b392cc64f44099e48f83e32a8fc2ade6fe01e4c..2abf3e45ec560266c304a7d7d03438a5b7f137a0`
- **Execution mode**: sdd → **QC mode: full tri-review (N=3)**
- **Findings cleanup**: zero-residual
- **Date**: 2026-08-25

## Seat verdicts (initial wave)

| Seat | Lens | Verdict | Report |
|------|------|---------|--------|
| qc-specialist | Architecture coherence & maintainability | **Request Changes** | `review/qc1.md` |
| qc-specialist-2 | Security & correctness | **Request Changes** | `review/qc2.md` |
| qc-specialist-3 | Performance & reliability | **Request Changes** | `review/qc3.md` |

Note: qc2's first closing message mis-relayed qc3's content and its report file was initially missing; PM re-dispatched the same seat (send_message) and `qc2.md` was then written by the seat itself. Verdicts above are from each seat's own on-disk report.

## Findings disposition (initial wave)

**Warning (blocking):**
- **W1 / F-001 (all three seats converge)** — `download` and `archive` stage failures write no `outcome="failed"` record to `attempts.jsonl` (only harvest/asr have failure-recording wrappers). Violates locked interface "Stage failures recorded; batch continues" and silently drops those rows from `--scope failed` re-selection. → **fix now**
- **F-002 (qc2)** — explicit-scope rerun of an already-terminal row exits 1 ("scope not fully processed") although nothing remains to process; `--scope pending` masks it. → **fix now**

**Suggestion (zero-residual: fix now unless noted):**
- qc1-S1 — `_identity_for` duplicates cli `_identity_from_entry` verbatim → extract single seam (fix now)
- qc1-S2 — dead `RunCoordinator.failed_work_ids()`; CLI re-implements inline → wire CLI to the method (fix now)
- qc1-S3 / qc3-S3 — `--limit <= 0` silently selects zero rows, exit 0 → usage error (fix now)
- qc2-F-003 — ledger `append` fsyncs tmp file but not parent dir after `os.replace` → add dir fsync (fix now)
- qc3-S1 — add `simplify:` marker on `AttemptLedger.append` naming the O(n²) whole-file-rewrite ceiling + upgrade path (fix now)
- qc3-S2 — `_safe_error_code` does not sanitize `_FORBIDDEN_MARKERS`; hostile code string would make `_record` raise and mask the original stage exception → sanitize in `_safe_error_code` (fix now)
- qc2-F-004 — `error_code` doubles as skip-reason channel → **keep-as-is**: sidecar field set is locked by plan §Interfaces (no `reason` field); README one-line clarification instead (fix now, doc-only)
- qc3-S4 — `RunSummary` properties recompute per access → **no change requested by seat** (keep)

Known plan-QC notes (M3, M5, T2-M1, T2-M2) were pre-assessed by all seats; none rises to Warning.

## Gate decision (initial wave)

**QC: Request Changes** — 0 Critical / 2 distinct blocking Warnings (W1 converged ×3 seats, F-002) + fixable Suggestions. One fix dispatch (full list above), then targeted re-review of all three seats (all raised blocking findings).

## Gate decision (after fix round d665034 + targeted re-review)

**QC: Approve — zero open findings.** Fix round `d665034` (single commit) resolved both blocking Warnings and all Suggestions; all three seats revalidated in place (`## Revalidation` in qc1/qc2/qc3) against HEAD source: Approve ×3, 0 remaining open findings per lens. New-issue scans on all three lenses found no new Critical/Warning. Runtime suite execution (277 passed claim) is L3-out-of-scope — deferred to QA gate L4.

| Seat | Initial | Re-review | Open findings |
|------|---------|-----------|---------------|
| qc-specialist | Request Changes (0C/1W/3S) | **Approve** | 0 |
| qc-specialist-2 | Request Changes (0C/2W/2S) | **Approve** | 0 |
| qc-specialist-3 | Request Changes (0C/1W/4S) | **Approve** | 0 |

## Handoff

- `QA gate: mandatory`, `QA mode: acceptance-only`
- L1 evidence: implementer reports `task-1-report.md` (266 at 6827180) / `task-2-report.md` (277 at d665034 after fix round; 271 at 2abf3e4)
- Final branch HEAD: `d665034`; branch review = `5b392cc..2abf3e4` + fix diff `2abf3e4..d665034`
