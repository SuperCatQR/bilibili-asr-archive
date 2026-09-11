---
report_kind: qc-consolidated
plan_id: "20260825-executable-pilot-workflow"
verdict: "Approve"
generated_at: "2026-08-25"
head: "c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3"
---

# Plan A QC consolidated — final

Branch: `plan/20260825-executable-pilot-workflow`. Final HEAD `c4ce9bb`.

| Seat | Initial | Revalidation | Final |
|------|---------|--------------|-------|
| QC1 | Request Changes (F-001/F-002 + suggestions) | Approve (`c4ce9bb`) | Approve |
| QC2 | Request Changes (F-001/F-002) | Approve (`c4ce9bb`) | Approve |
| QC3 | Request Changes (F-001/F-002) | Approve (`c4ce9bb`) | Approve |

## Closed findings

- R1 (branch coverage counts only this run) — `_archived_branch_counts` seeds from archived ledger rows; resume-after-partial-ASR test added.
- R2 (empty-select skip too broad; `--n<1` fake-succeed) — leftover non-archived → exit 1 `no processable rows`; skip-0 only when all in-scope archived.
- R3 (ASRModelError/generic swallowed; risk-budget no summary) — named `type(exc).__name__`; risk-budget prints `_pilot_print_summary` before exit 2.
- Suggestions: audio_ok reuses audio_path; selected print shows expanded count; exception-class logging; R1/R2 tests.

Open Critical/Warning: none. PM pytest on final HEAD: 180 passed.
